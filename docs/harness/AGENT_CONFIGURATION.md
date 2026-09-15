# Настройка моделей и reasoning effort

Цель — тратить дорогой reasoning там, где он действительно повышает качество, а не на механические изменения.

## Базовый профиль

| Роль | Модель | Effort | Когда |
|---|---|---|---|
| initializer | GPT-5.6 Sol | high | только bootstrap/re-bootstrap analysis |
| architect | GPT-5.6 Sol | high | архитектурные решения |
| planner | GPT-5.6 Sol | high | сложный анализ перед реализацией |
| implementer | GPT-5.6 Terra | medium | основной coding volume |
| reviewer | GPT-5.6 Sol | high | независимый поиск дефектов |
| security-reviewer | GPT-5.6 Sol | high | условно, security-sensitive changes |
| test-reviewer | GPT-5.6 Terra | low | условно, сложная test surface |
| docs | GPT-5.6 Terra | low | синхронизация документации |
| mechanic | GPT-5.6 Terra | low | локальная механическая работа |
| skill-curator | GPT-5.6 Sol | medium | внешние skills требуют careful inspection/provenance |
| git-operator | GPT-5.6 Terra | medium | diff classification, commit/branch/PR safety |
| harness-updater | GPT-5.6 Sol | high | BASE/OURS/THEIRS reconciliation и ownership conflicts |

## Главный принцип экономии

Сначала сокращай **лишние агентные проходы и контекст**, а уже затем снижай effort.

Не запускай security/test reviewer для задачи, которой они не касаются. Planner можно пропустить внутри `RUN`, если task уже имеет свежий и достаточный Implementation plan. Механические изменения не должны уходить к Sol.

## Когда повышать implementer до Sol

Повышай роль на STEP, если присутствуют несколько факторов:

- cross-module/cross-service refactoring;
- concurrency/race conditions;
- сложные migrations/data transformations;
- security boundary;
- public API/protocol compatibility;
- сложная state machine;
- критичный performance path;
- много неочевидных side effects.

В остальных случаях Terra Medium — рекомендуемый default.

## Когда допустим Low

Low подходит для хорошо специфицированных, локальных задач:

- rename;
- boilerplate;
- простое поле/DTO/config;
- очевидные unit-test additions;
- документация;
- механический refactor без изменения поведения.

Если reviewer регулярно находит substantive findings после Low implementer, верни Medium. Используй фактическую статистику проекта, а не предположение.

## Почему reviewer обычно сильнее implementer

Implementer получает готовый task/plan и решает задачу в заданной рамке. Reviewer должен самостоятельно обнаружить то, что автор пропустил. Поэтому при ограниченном бюджете выгоднее экономить на механической реализации, а не на независимом контроле качества.

## Контекст и output

Агенты должны:

- читать только релевантные skills/docs;
- не пересказывать целиком task/ADR/REQ в финальном ответе;
- отдавать короткий structured handoff;
- не запускать параллельно несколько write-agents над одними файлами.

## Как изменить модель

Редактируй конкретный файл `.codex/agents/<role>.toml`:

```toml
model = "gpt-5.6-terra"
model_reasoning_effort = "medium"
```

Root defaults и лимит параллелизма находятся в `.codex/config.toml`.

## Профили

### Quality-first

- initializer/architect/planner/reviewer/security/harness-updater: Sol High
- implementer: Sol Medium или High для critical STEP
- test-reviewer: Terra Medium

### Balanced (default)

- reasoning roles: Sol High
- implementer: Terra Medium
- mechanical roles: Terra Low по умолчанию; Luna можно использовать как дополнительную экономию только после проверки совместимости с текущей версией Codex
- harness-updater: Sol High, потому что запускается редко и ошибка может повредить protocol layer проекта

### Budget-first

- planner: Terra High для обычных задач, Sol High только для architecture-heavy
- implementer: Terra Low/Medium
- reviewer: Sol High только для major/risky STEP, Terra Medium для малых corrective STEP
- mechanic/docs: Terra Low (или Luna Low, если текущая версия Codex поддерживает Luna для spawned custom agents в твоей конфигурации)
- harness-updater не понижать автоматически: update лучше запускать реже, но с сильным reconciliation profile

Budget-first не отменяет security/release gates для high-risk изменений.

## Skill curator

`skill-curator` вызывается редко, поэтому здесь выгоднее умеренно сильный профиль, чем максимальная экономия: он читает недоверенные third-party instructions/scripts и принимает решение об installation risk. Default — Sol Medium. Для широко известного, простого, чисто документального skill можно временно использовать Terra Medium; для skill со scripts/hooks/network/security tooling разумно повысить curator до Sol High или дополнительно привлечь `security_reviewer`.

## Git operator

Default:

```text
git-operator → GPT-5.6 Terra / Medium
```

Задача в основном механическая, но требует аккуратно классифицировать diff, отделять unrelated files и формировать commit/PR metadata. Low допустим для очень простого репозитория, но Medium является более безопасным default. Git operator не должен принимать архитектурные решения и не заменяет reviewer.

## Harness updater

Default:

```text
harness-updater → GPT-5.6 Sol / High
```

Роль сравнивает immutable source BASE, local OURS и target THEIRS, определяет ownership boundary и должна предпочитать blocker потенциально разрушительному auto-merge. Она не выполняет product work, STEP или Git publication и не запускает target migration scripts.
