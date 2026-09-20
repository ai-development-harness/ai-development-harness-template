# Git workflow Harness

Harness отделяет разработку от публикации изменений. `STEP IMPLEMENT` / `STEP REVIEW` не создают commits автоматически. Git-операции выполняются явными командами области `GIT` и управляются `.harness/git-policy.toml`.

## Команды

```text
GIT CHECK
GIT COMMIT
GIT COMMIT: <необязательная подсказка>
GIT PUSH
GIT PR
GIT SYNC

# shorthand-цепочка
GIT CHECK > COMMIT > PUSH > PR
```

### `GIT CHECK`

Read-only preflight: branch/upstream, ahead/behind, staged/unstaged/untracked, Harness integrity, подозрительные файлы и предполагаемый commit type/scope.

### `GIT COMMIT`

`GIT COMMIT`:

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

### `GIT PUSH`

`GIT PUSH` сначала выполняет fetch/divergence/safety checks, затем публикует текущую ветку в configured remote без force. По умолчанию:

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

### `GIT PR`

`GIT PR` можно вызвать отдельно. Агент использует `.github/pull_request_template.md`, не создаёт duplicate PR и заполняет traceability/verification из repository evidence.

### `GIT SYNC`

Default `GIT SYNC` только fetch + ahead/behind report. Для автоматического безопасного fast-forward:

```toml
[sync]
mode = "ff-only"
```

Merge/rebase конфликтующей истории автоматически не выполняются.

## Цепочка публикации

Для обычной последовательной публикации допустим shorthand:

```text
GIT CHECK > COMMIT > PUSH > PR
```

Он эквивалентен четырём отдельным canonical commands той же области. Structural validity определяется не этим prose-описанием, а `.harness/command-transitions.json`; полная матрица находится в [`COMMAND_TRANSITIONS.md`](COMMAND_TRANSITIONS.md). Для Git graph соответствует publication flow `CHECK → COMMIT → PUSH → PR` с дополнительными explicit shortcut edges из таблицы. Обратный/неразрешённый порядок отклоняется как `INVALID_CHAIN` до любых действий. После structural PASS runtime conditions каждого edge проверяются отдельно. Уже созданный commit не откатывается автоматически, если последующий push или PR оказался blocked.

Cross-domain chain запрещён: `STEP RUN STEP-NNN > GIT COMMIT` не является допустимой командой. Полная семантика — в [`COMMAND_SYNTAX.md`](COMMAND_SYNTAX.md).

## Safety defaults

Harness никогда по умолчанию не выполняет:

- `git push --force` / `--force-with-lease`;
- `git reset --hard`;
- `git clean -fd`;
- автоматический merge/rebase;
- commit amend;
- staging подозрительных/несвязанных файлов.

Перед `GIT COMMIT` / `GIT PUSH` запускается `.harness/tools/validate.py`. CI запускает тот же валидатор, поэтому локальные и remote gates основаны на одном контракте.

## Что настраивать

Главный файл: `.harness/git-policy.toml`.

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

Для typo/formatting/другого подтверждённого micro-change STEP не обязателен. Если пользователь уже внёс правку, достаточно `GIT CHECK > COMMIT` либо тех же команд по отдельности. Git operator обязан проверить, что diff действительно не меняет behavior/API/data/security/architecture/dependencies. Подробности: [`QUICK_CHANGES.md`](QUICK_CHANGES.md).

Язык commit message берётся из `.harness/manifest.yaml` → `language.commitMessages`.
