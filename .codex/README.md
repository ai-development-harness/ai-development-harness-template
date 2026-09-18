# Codex agents

`.codex/config.toml` регистрирует project-scoped роли через `[agents.<role>]` и `config_file`.

Настройки модели/effort находятся в `.codex/agents/*.toml`, чтобы стоимость и качество можно было менять независимо для каждой роли.

Перед изменением конфигурации прочитай `docs/harness/AGENT_CONFIGURATION.md`.

- `skill-curator` — поиск, inspection, установка и создание repository skills.
- `harness-updater` — безопасный `HARNESS UPDATE CHECK` / `HARNESS UPDATE APPLY` с сохранением project-owned state.
