---
name: git-workflow
description: Safe Git workflow using configured repository policy plus deterministic preflight gates before COMMIT, PUSH, PR and SYNC mutations.
---
# git-workflow

Используй для `GIT CHECK`, `GIT COMMIT`, `GIT PUSH`, `GIT PR`, `GIT PR FINISH`, `GIT SYNC` и валидных Git-chain segments.

## Главный принцип

Git policy остаётся в configured `.harness/manifest.yaml → repository.gitPolicy`, но safety-critical решение «можно ли сейчас выполнять mutation» принимает deterministic tool:

```bash
python3 .harness/tools/git-preflight.py check --json
python3 .harness/tools/git-preflight.py commit --json [--commit-type <type>] [--slug <slug>]
python3 .harness/tools/git-preflight.py push --json
python3 .harness/tools/git-preflight.py pr --json
python3 .harness/tools/git-preflight.py sync --json
```

Agent не должен вручную переопределять `PASS/BLOCKED`, protected-branch decision, remote ahead/behind, publish state, PR base/tool или ff-only safety.

Preflight остаётся read-oriented proof. Для `GIT COMMIT`, `GIT PUSH`, `GIT SYNC` и `GIT PR FINISH` mutation выполняй через `git-action.py`, который повторяет preflight и проверяет postcondition. `GIT PR` пока остаётся provider boundary: его title/body — semantic inputs, создание/переиспользование выполняется provider tooling после deterministic preflight.

## Общие правила

1. До mutation изучи фактический diff/status и semantic scope.
2. Не включай unrelated changes.
3. `require_single_logical_change` остаётся semantic обязанностью агента: deterministic tool не угадывает смысл файлов.
4. STEP/REQ/ADR traceability не обязательна для подтверждённого micro-change/PROJECT QUICK FIX.
5. Если diff без STEP меняет behavior/API/data/security/architecture/dependencies — остановись и предложи `STEP ADD:`.
6. Force-push, destructive reset/clean, automatic merge/rebase и amend запрещены без отдельного явного protocol path; обычный Git workflow их не использует.

## GIT CHECK

Запусти:

```bash
python3 .harness/tools/git-preflight.py check --json
```

Покажи branch, protection, upstream, staged/unstaged/untracked, configured remotes/base и Harness validation result. CHECK ничего не stage/commit/push.

## GIT COMMIT

1. Определи фактический logical change по diff.
2. Выбери commit type только из `commit.types`; optional user hint не заменяет diff.
3. Stage согласно `commit.stage_mode`:
   - `staged-only` — не добавлять новые paths к index;
   - `tracked-only` — не stage новые files;
   - `all-safe` — stage только проверенный logical change, без `git add .` вслепую.
4. Сформируй semantic commit message по `.gitmessage`/policy и сохрани его в local-only `.harness/local/git/commit-message.txt`.
5. Выполни mutation только через:

```bash
python3 .harness/tools/git-action.py commit --json \
  --commit-type '<type>' \
  --slug '<short semantic slug>' \
  --message-file .harness/local/git/commit-message.txt
```

Executor повторяет commit preflight, при exact `PROTECTED_BRANCH_REQUIRES_NEW_BRANCH` создаёт только returned branch, валидирует mechanical message constraints, создаёт commit и проверяет изменение HEAD. COMMIT никогда не делает push.

Machine gate детерминированно проверяет Harness validation, empty commit, stage-mode ограничения, protected branch и initial-commit exception. Семантику logical change/message всё ещё обязан проверить агент.

## GIT PUSH

После semantic проверки scope выполни push через:

```bash
python3 .harness/tools/git-action.py push --json
```

Tool:

- использует только configured `push.remote`;
- выполняет fetch, если `fetch_before_push=true`;
- запускает Harness validation, если требуется;
- применяет `require_clean_worktree`;
- проверяет protected branch / initial bootstrap exception;
- считает exact ahead/behind относительно configured remote branch;
- блокирует remote-ahead состояние: при `force=never` безопасного автоматического push поверх неизвестных remote commits нет;
- гарантирует `force=never`;
- формирует `mutationPlan.argv` с `--set-upstream` / tag behavior согласно policy.

Executor сам повторяет preflight, исполняет только returned non-force argv и проверяет, что configured remote branch совпал с local HEAD. Не выполняй `git push` вручную.

После успешного push применяй `pull_request.after_push`: `never | ask | create-if-missing`.

## GIT PR

Сначала semantic часть: по repository evidence и configured template подготовь только PR body в regular file под `.harness/local/git/**`. Title-файл нужен только если preflight сообщает `titleFromCommit=false`; при default `true` executor сам берёт exact subject текущего commit.

Не ищи existing PR, не вызывай `gh pr create/list/view` и не записывай `pr-state.json` вручную. Вызови:

```bash
python3 .harness/tools/git-action.py pr --body-file .harness/local/git/pr-body.md --json
```

При `titleFromCommit=false` добавь `--title-file .harness/local/git/pr-title.txt`.

Executor сам повторяет PR preflight, использует только configured provider/tool/head/base/draft policy, ищет exact open head/base PR, переиспользует его при `reuse_existing=true` либо создаёт новый, проверяет provider head OID == exact published HEAD и атомарно сохраняет local PR lifecycle state. Повторный запуск idempotent для того же PR.


## GIT PR FINISH

Выполни `python3 .harness/tools/git-action.py pr-finish --json`. Executor повторяет provider/Git preflight, исполняет ordered steps, проверяет return branch и удаление exact PR-head ref, после чего удаляет local PR state только при полном успехе. При `BLOCKED` не обходи его ручным switch/delete.

## GIT SYNC

Выполни:

```bash
python3 .harness/tools/git-action.py sync --json
```

Executor сначала запускает canonical sync preflight: fetch-ит только `sync.fetch_remote`, считает ahead/behind и выполняет mutation только для exact ff-only plan.

- `mode=report` → mutation запрещена, только отчёт.
- `mode=ff-only` → tool выдаёт `git merge --ff-only <remote>/<branch>` только для clean behind-only state.
- local-ahead или diverged state блокирует автоматический sync.
- automatic merge/rebase не разрешены.

Не выполняй returned merge argv вручную: executor проверяет postcondition local HEAD == configured remote branch.

## Failure policy

Любой `BLOCKED` останавливает текущий Git segment. Не обходи blocker ручной командой с более слабыми параметрами.

Типичные blockers:

- detached HEAD;
- invalid configured Git policy;
- Harness validation failure;
- empty commit при `allow_empty=false`;
- protected-branch commit/push;
- remote missing/ahead;
- dirty worktree при strict push/sync;
- unpublished PR head;
- unavailable configured PR tool;
- missing PR base/template;
- diverged/non-ff sync.

После изменения Git policy или preflight contract обновляй synthetic regression и документацию одновременно.
