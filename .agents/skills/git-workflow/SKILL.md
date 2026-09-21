---
name: git-workflow
description: Safe repository Git workflow for GIT CHECK, GIT COMMIT, GIT PUSH, GIT PR and GIT SYNC using project policy and deterministic integrity checks.
---
# git-workflow

Используй для `GIT CHECK`, `GIT COMMIT`, `GIT PUSH`, `GIT PR`, `GIT SYNC` и сегментов валидной Git-цепочки вроде `GIT CHECK > COMMIT > PUSH > PR`.

## Общие правила

1. Разреши `.harness/manifest.yaml → repository.gitPolicy` и прочитай configured Git policy. Не подменяй её hardcoded `.harness/git-policy.toml`.
2. До mutation изучи `git status --short --branch`, staged/unstaged diff и untracked files.
3. Запусти `python3 .harness/tools/validate.py --mode commit` (для read-only check тоже допустимо).
4. Никогда не выполняй `git reset --hard`, `git clean -fd`, force-push, automatic merge/rebase или amend без явного запроса пользователя.
5. Не включай unrelated changes. При нескольких независимых логических изменениях останови GIT COMMIT и предложи разбиение.
6. Секреты/local brief/generated мусор не должны попадать в index/commit.
7. Язык commit message бери из `.harness/manifest.yaml` → `language.commitMessages`; не используй отдельный скрытый default.
8. STEP/REQ/ADR traceability не обязательна для подтверждённого micro-change/PROJECT QUICK FIX. Если diff без STEP меняет behavior/API/data/security/architecture/dependencies — GIT COMMIT должен остановиться и предложить `STEP ADD:`.

## GIT CHECK

Read-only. Покажи branch, upstream/ahead-behind, staged/unstaged/untracked, policy, suspicious files, Harness validation, вероятный commit type/scope и blockers. Ничего не stage/commit/push.

## GIT COMMIT

Применяй **все** поля `[commit]` и `[branch]` configured policy; валидный, но проигнорированный параметр считается protocol defect.

1. Определи фактический logical change по diff; optional `GIT COMMIT: <hint>` — только подсказка, diff является источником истины.
2. Определи commit type из `commit.types`. Если `commit.style=conventional`, используй Conventional Commit type/scope.
3. Примени branch policy:
   - `branch.protected` определяет protected branches;
   - `branch.when_on_protected=auto-create|stay|block` выполняется буквально;
   - initial commit на protected branch разрешён только при `allow_initial_commit_on_protected=true`;
   - existing non-protected branch переиспользуй только при `reuse_current_non_protected=true`;
   - новую branch строй из `branch.prefixes` + `branch.name_pattern`, ограничивая semantic slug через `slug_max_length`;
   - `branch.default_base` используется как base новой branch, если явный контекст не задаёт другой.
4. Stage согласно `commit.stage_mode`:
   - `staged-only` — не добавлять ничего;
   - `tracked-only` — только изменённые tracked files;
   - `all-safe` — только проверенный набор относящихся к change tracked/untracked files; не использовать бездумный `git add .`.
5. Если `commit.require_single_logical_change=true`, mixed logical changes блокируют commit. Если false — всё равно не добавляй unrelated/suspicious files.
6. Если `commit.require_harness_validation=true`, Harness validation обязан PASS непосредственно перед commit.
7. Повторно проверь staged diff. Empty commit допустим только при `commit.allow_empty=true`.
8. Сформируй сообщение по `.gitmessage` и configured policy:
   - subject не длиннее `commit.subject_max_length`;
   - body обязателен только при `commit.require_body=true`;
   - verification включай при `commit.include_verification=true`;
   - STEP/REQ/ADR traceability включай при `commit.include_traceability=true` и наличии релевантных ссылок.
9. При `commit.sign=true` используй обычный Git signing, уже настроенный в repository/user config; отсутствие рабочей signing-конфигурации — BLOCKED, не отключай signing молча.
10. Выполни commit. GIT COMMIT никогда не делает push.
11. Верни hash, branch, subject, files, verification и следующую рекомендуемую команду.

## GIT PUSH

1. Используй **только** `push.remote` configured policy. Если `push.fetch_before_push=true`, сначала выполни fetch этого remote.
2. Если `push.require_harness_validation=true`, Harness validation обязан PASS непосредственно перед push.
3. Если `push.require_clean_worktree=true`, любой staged/unstaged/untracked project change блокирует push; если false, всё равно не включай эти изменения в push автоматически.
4. Проверь configured remote branch/ahead-behind/divergence. При remote-ahead выполняй `push.if_remote_ahead`; значение `block` останавливает mutation.
5. `push.force` применяется буквально; schema-v1 допускает только `never`, поэтому force/force-with-lease запрещены.
6. Protected branch push разрешён только при `push.allow_protected=true`; первый push initial commit — только при `push.allow_initial_push_to_protected=true`.
7. При первом push устанавливай upstream только при `push.set_upstream=true`.
8. Git tags публикуй вместе с push только при `push.push_tags=true`; иначе tags не трогай.
9. После успешного push применяй `pull_request.after_push`:
   - `never` — завершить;
   - `ask` — предложить `GIT PR`;
   - `create-if-missing` — проверить существующий PR и создать при отсутствии.
10. PR automation использует `pull_request.provider` и `pull_request.preferred_tool`; не подменяй configured tool на `gh` или другой CLI. Если configured provider/tool недоступен или не авторизован, push остаётся успешным, а PR creation возвращает отдельный BLOCKED.

## PR

1. Используй `pull_request.provider` + `pull_request.preferred_tool`; отсутствие поддерживаемого/авторизованного configured tool — BLOCKED без выдуманного успеха.
2. Head branch должна быть опубликована. Base бери из `pull_request.base`, а не из `branch.default_base`.
3. При `pull_request.reuse_existing=true` переиспользуй существующий открытый PR той же head/base; при false новый PR допустим, но не создавай неявный duplicate при неоднозначности.
4. Если `pull_request.title_from_commit=true`, title выводи из фактического основного commit/change; иначе сформируй title из фактического diff/STEP contract.
5. Body строится по `pull_request.body_template` из configured `repository.gitPolicy`, заполненному фактическими STEP/REQ/ADR, verification, risks и review.
6. `pull_request.draft` определяет draft/non-draft.
7. Верни URL или конкретный blocker.

## GIT SYNC

1. Fetch выполняй через `sync.fetch_remote`; не подменяй его `push.remote`.
2. Покажи ahead/behind/diverged относительно выбранного upstream/base context.
3. В `sync.mode=report` ничего больше не меняй.
4. В `sync.mode=ff-only` разрешён только safe fast-forward чистой рабочей копии.
5. Никогда автоматически не merge/rebase конфликтующую историю.
