# AI Development Harness — документация

Эта папка описывает **сам Harness**, а не конкретный продукт. После `INIT PROJECT` продуктовая документация живёт уровнем выше в `docs/`, а правила разработки остаются здесь.

## С чего начать

- [`GETTING_STARTED.md`](GETTING_STARTED.md) — создание проекта из template и `INIT PROJECT`.
- [`DOCUMENT_MODEL.md`](DOCUMENT_MODEL.md) — какие артефакты существуют, что является источником истины и как связаны REQ / ADR / STEP / PLAN / STATUS / Evidence / Review.
- [`GLOSSARY.md`](GLOSSARY.md) — полный словарь терминов и сокращений Harness.
- [`REPOSITORY_LAYOUT.md`](REPOSITORY_LAYOUT.md) — файловая архитектура и разделение protocol / knowledge / implementation.
- [`COMMANDS.md`](COMMANDS.md) — пользовательский командный интерфейс.
- [`LANGUAGE_POLICY.md`](LANGUAGE_POLICY.md) — единая настройка языка для docs/commits/comments/tests/fixtures/templates.
- [`QUICK_CHANGES.md`](QUICK_CHANGES.md) — когда мелкая правка не требует STEP.
- [`UPDATES.md`](UPDATES.md) — безопасное обновление Harness в уже идущем проекте.
- [`../../planning/EXECUTION_PROTOCOL.md`](../../planning/EXECUTION_PROTOCOL.md) — формальная семантика state transitions и выполнения STEP.

## Агенты и автоматизация

- [`AGENT_CONFIGURATION.md`](AGENT_CONFIGURATION.md) — роли субагентов, модели, reasoning effort и стратегии экономии.
- [`WORKFLOW.md`](WORKFLOW.md) — устройство orchestration и durable handoff между стадиями.
- [`REPORTING.md`](REPORTING.md) — требования к итоговым отчётам.
- [`SKILL_MANAGEMENT.md`](SKILL_MANAGEMENT.md) — поиск, inspection, установка и создание skills.
- [`GITHUB_TEMPLATES.md`](GITHUB_TEMPLATES.md) — регенерация Issue Forms и PR template по текущему стеку проекта.

## Repository operations

- [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) — `GIT CHECK`, `COMMIT`, `PUSH`, `PR`, `SYNC`.
- [`CI.md`](CI.md) — Harness Integrity CI и граница между Harness CI и product CI.
- [`MAINTENANCE.md`](MAINTENANCE.md) — как изменять Harness, не смешивая protocol layer с product knowledge.
- [`UPDATES.md`](UPDATES.md) — release/lock/ownership/legacy-adoption lifecycle self-update.

## Project-specific документация

После `INIT PROJECT` основными продуктовым источниками становятся:

- [`../PROJECT.md`](../PROJECT.md) — что это за проект и его границы;
- [`../requirements/SPEC.md`](../requirements/SPEC.md) — требования;
- [`../architecture.md`](../architecture.md) — текущий архитектурный baseline;
- [`../adr/`](../adr/) — история устойчивых архитектурных решений;
- [`../../planning/PLAN.md`](../../planning/PLAN.md) — roadmap projection;
- [`../../planning/tasks/`](../../planning/tasks/) — канонические task contracts;
- [`../GLOSSARY.md`](../GLOSSARY.md) — **продуктовый** глоссарий конкретного проекта.

Не смешивай продуктовый глоссарий с [`GLOSSARY.md`](GLOSSARY.md): последний определяет язык и сущности самого Harness.
