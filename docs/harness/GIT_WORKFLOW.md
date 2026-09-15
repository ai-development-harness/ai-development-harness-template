# Git workflow Harness

Harness отделяет разработку от публикации изменений. `IMPLEMENT/REVIEW` не создают commits автоматически. Git-операции выполняются явными командами и управляются `.project/git-policy.toml`.

## Команды

```text
GIT CHECK
COMMIT
COMMIT: <необязательная подсказка>
PUSH
PR
SYNC
```

### GIT CHECK

Read-only preflight: branch/upstream, ahead/behind, staged/unstaged/untracked, Harness integrity, подозрительные файлы и предполагаемый commit type/scope.

### COMMIT

`COMMIT`:

- проверяет Harness и staged/worktree;
- не включает секреты, local brief, build/cache мусор;
- выявляет unrelated changes;
- при необходимости создаёт ветку согласно policy;
- формирует подробный Conventional Commit message;
- создаёт **только локальный commit**.

Message строится по `.gitmessage`:

```text
feat(auth): добавь ротацию refresh-токенов

Контекст:
- Исключает повторное использование отозванной сессии.

Изменения:
- Добавлена ротация refresh token.
- Повторное использование старого token отзывает цепочку сессии.

Проверки:
- yarn test auth — PASS
- yarn typecheck — PASS

Traceability:
- STEP-024
- REQ-017
- ADR-006
```

Если diff содержит две независимые задачи, предпочтительны два commits, а не один общий `chore`.

### Branch policy

Default:

```text
main + feat  → feature/<slug>
main + fix   → bugfix/<slug>
main + docs  → docs/<slug>
main + chore → chore/<slug>
```

Это меняется через:

```toml
[branch]
when_on_protected = "auto-create" # auto-create | stay | block
```

Первый commit пустого template repo может остаться в `main` благодаря `allow_initial_commit_on_protected=true`.

### PUSH

`PUSH` сначала выполняет fetch/divergence/safety checks, затем публикует текущую ветку в configured remote без force. По умолчанию:

```toml
[pull_request]
after_push = "create-if-missing"
```

Поэтому после push агент проверяет наличие PR и создаёт его при отсутствии. Чтобы только отправлять ветку:

```toml
[pull_request]
after_push = "never"
```

Для GitHub PR Harness предпочитает `gh`. Если CLI недоступен/не авторизован, push не объявляется неуспешным, но PR creation показывается как отдельный blocker.

### PR

`PR` можно вызвать отдельно. Агент использует `.github/pull_request_template.md`, не создаёт duplicate PR и заполняет traceability/verification из repository evidence.

### SYNC

Default `SYNC` только fetch + ahead/behind report. Для автоматического безопасного fast-forward:

```toml
[sync]
mode = "ff-only"
```

Merge/rebase конфликтующей истории автоматически не выполняются.

## Safety defaults

Harness никогда по умолчанию не выполняет:

- `git push --force` / `--force-with-lease`;
- `git reset --hard`;
- `git clean -fd`;
- автоматический merge/rebase;
- commit amend;
- staging подозрительных/несвязанных файлов.

Перед COMMIT/PUSH запускается `tools/harness/validate.py`. CI запускает тот же валидатор, поэтому локальные и remote gates основаны на одном контракте.

## Что настраивать

Главный файл: `.project/git-policy.toml`.

Чаще всего меняются:

- `commit.language`;
- `commit.stage_mode`;
- `branch.when_on_protected`;
- `branch.name_pattern` и prefixes;
- `push.remote`;
- `push.allow_protected`;
- `pull_request.after_push`;
- `pull_request.draft`;
- `sync.mode`.

## Мелкие изменения без STEP

Для typo/formatting/другого подтверждённого micro-change STEP не обязателен. Если пользователь уже внёс правку, достаточно `GIT CHECK` → `COMMIT`. Git operator обязан проверить, что diff действительно не меняет behavior/API/data/security/architecture/dependencies. Подробности: [`QUICK_CHANGES.md`](QUICK_CHANGES.md).

Язык commit message берётся из `.project/manifest.yaml` → `language.commitMessages`.
