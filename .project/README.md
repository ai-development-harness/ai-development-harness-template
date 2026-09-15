# `.project/`

Служебная metadata AI Development Harness.

`manifest.yaml` содержит только техническое состояние Harness, current release, project initialization state и ссылки на основные источники истины. Бизнес-требования, архитектурные решения и планы здесь хранить нельзя.

`project.initialized` меняется на `true` только после успешного `INIT PROJECT` и проверки согласованности созданной документации.

Локальные/секретные overrides при необходимости складываются в `.project/local/`; каталог игнорируется Git.

## Repository policies

- `git-policy.toml` — поведение COMMIT/PUSH/PR/SYNC, ветки и commit messages.
- `harness-policy.toml` — deterministic integrity/safety checks для local preflight и CI.
- `harness-update.toml` — source repository, ownership classes и merge policy для self-update.
- `harness.lock.json` — машинный known BASE текущего Harness release; JSON намеренно не требует inline-комментариев.

`harness.lock.json` не содержит secrets. Его нужно хранить в Git вместе с проектом; удаление lock переводит updater в legacy-adoption mode.

Все tracked YAML/TOML policy/config files в template снабжены inline-комментариями для каждого параметра. При добавлении нового параметра сохраняй это правило: назначение, допустимое поведение и хотя бы один пример должны быть видны рядом с настройкой.

## Language policy

`.project/manifest.yaml` → `language` — единый источник языка docs/commits/comments/tests/fixtures/GitHub templates/release notes.
