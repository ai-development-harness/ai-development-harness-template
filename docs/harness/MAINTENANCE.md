# Поддержка Harness

## Что относится к protocol layer

- `AGENTS.md` (кроме generated project block);
- `.codex/`;
- `.agents/skills/`;
- `planning/EXECUTION_PROTOCOL.md`;
- `docs/harness/`;
- templates.

## Что относится к конкретному проекту

- generated blocks README/AGENTS;
- `docs/PROJECT.md`;
- requirements;
- ADR;
- architecture/subsystem docs;
- roadmap/tasks/reviews/audits;
- product code/tests/config.

## Правило обновлений

Не копируй новый harness поверх проекта вслепую. Сначала сравни protocol layer, затем перенеси изменение с учётом project-specific дополнений.

## Версия Harness

`.project/manifest.yaml` содержит `harness.version`. Пока Harness находится в экспериментальной фазе и не прошёл реальное dogfooding, сохраняй версию `1`. Не повышай номер за каждую итерацию шаблона. Версионирование схемы/совместимости вводится отдельно после стабилизации protocol.

## Project-specific skills

Добавляй отдельно. Универсальный `implement-step` не должен знать конкретный framework. Если technology skill нужен большинству задач проекта — зарегистрируй его в `.agents/skills/` и упомяни в generated project context/architecture docs.


## Third-party skills

Не смешивай upstream skill upgrades с обычным harness update. У каждого внешнего skill должен быть `UPSTREAM.md` и запись в `docs/skills/REGISTRY.md`. Обновление upstream требует повторного inspection; не делай silent auto-update.

## Самодокументируемые конфиги

Tracked YAML/TOML в `.project/`, `.codex/` и baseline GitHub Actions должны оставаться читаемыми без перехода в отдельную справку. Каждый параметр обязан иметь рядом комментарий с назначением и примером. Harness Integrity проверяет это правило для patterns из `.project/harness-policy.toml`.

При добавлении нового policy/config key одновременно:

1. объясни назначение;
2. перечисли допустимое поведение, если оно неочевидно;
3. приведи `Пример:` или `Example:`;
4. только после этого добавляй значение.
