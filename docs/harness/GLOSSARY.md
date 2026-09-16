# Глоссарий AI Development Harness

Этот документ определяет **каноническое значение терминов самого Harness**. Если термин используется в protocol, AGENTS, planning или отчётах агентов, его смысл должен соответствовать этому словарю.

Продуктовые термины конкретного проекта находятся отдельно в `docs/GLOSSARY.md` и заполняются при `INIT PROJECT`.


## Общие понятия Harness

### Harness

Набор repository-level правил, agents, skills, templates, policies и deterministic tools, который организует разработку проекта. Harness — это **прослойка процесса**, а не product framework и не runtime dependency будущего приложения.

### Protocol Layer

Стабильная часть репозитория, задающая способ работы агентов: `AGENTS.md`, `planning/EXECUTION_PROTOCOL.md`, core skills, agent configs, policies и `docs/harness/*`.

### Project Knowledge Base

Нормализованная проектная база знаний после INIT: `PROJECT.md`, REQ, architecture, ADR, glossary, planning и связанные документы. Она должна позволять новой сессии восстановить контекст без chat history.

### Source of Truth

Авторитетный источник конкретного вида информации. Harness использует не один глобальный файл, а иерархию источников истины для factual state, architecture contract, requirements и task scope.

### Artifact

Любой долговечный результат, сохранённый в репозитории: requirement, ADR, STEP, review report, code, migration, test, config, audit report и т. п.

### Generated Block

Ограниченный участок файла между специальными markers, который агенту разрешено переписывать автоматически.

Пример:

```text
<!-- PROJECT:START -->
...
<!-- PROJECT:END -->
```

Статический текст вне generated block не должен переписываться initializer без отдельной причины.

### ID / Stable ID

Устойчивый идентификатор артефакта, который не переиспользуется и не меняется после появления в истории проекта.

Примеры: `REQ-014`, `ADR-007`, `STEP-042`.

### TBD — To Be Determined

Явная отметка, что значение ещё не определено. `TBD` лучше выдуманного ответа, но не должно бесконечно оставаться в обязательном контракте: blocking TBD превращается в Open Question / RESEARCH / ADR STEP.

## Planning metadata

### Status

Текущее lifecycle-состояние артефакта.

Для STEP Harness использует:

- `Запланировано` — task существует, но implementation не начат;
- `В работе` — STEP фактически выполняется;
- `Выполнено` — acceptance criteria доказаны verification/evidence и необходимые review gates пройдены;
- `Заблокировано` — работа не может продолжаться без внешнего prerequisite/решения;
- `Отменено` — STEP сознательно больше не требуется;
- `Заменено` — STEP исторически сохранён, но его роль выполняет другой STEP/решение.

### Priority

Относительная важность STEP для порядка работы. Priority не отменяет dependencies: критичный, но заблокированный STEP не становится executable только из-за высокого приоритета.

Конкретная шкала может быть определена проектом, например `Критический / Высокий / Средний / Низкий`.

### Phase

Логическая стадия roadmap, объединяющая несколько STEP по продуктовой/архитектурной цели. Phase помогает навигации, но не заменяет dependency graph.

### Severity

Серьёзность finding в review/audit/security report. Обычно используется шкала `critical / high / medium / low` или эквивалент проекта. Severity описывает impact/risk, а не приоритет разработчика «по ощущениям».

### Type

Класс STEP, определяющий допустимую семантику выполнения (`IMPLEMENTATION`, `BUGFIX`, `ADR`, `RESEARCH`, `AUDIT`, `REVIEW`, `DOCUMENTATION`, `HARDENING`, `RELEASE`). `RUN STEP-NNN` обязан учитывать Type.

## Часто встречающиеся технические сокращения

### PR — Pull Request

Запрос на интеграцию изменений одной Git branch в другую с review/CI history.

### CI — Continuous Integration

Автоматическое выполнение проверок при push/PR. В Harness различаются baseline Harness Integrity CI и product-specific CI.

### CD — Continuous Delivery / Continuous Deployment

Автоматизация подготовки или фактического развёртывания release. Harness не включает универсальный product CD заранее: он проектируется после выбора реального deployment stack.

### CLI — Command-Line Interface

Интерфейс программы через терминал. Например GitHub CLI `gh` может использоваться Git workflow для PR.

### API — Application Programming Interface

Формализованный программный интерфейс между компонентами/системами. В requirements/ADR термин должен сопровождаться конкретным контрактом, если он влияет на compatibility.

### URL — Uniform Resource Locator

Адрес ресурса. В brief может использоваться для референсов; в security-sensitive implementation URL input может потребовать отдельной проверки (например SSRF controls).

### AuthN / Authentication

Проверка **кто** является пользователем/клиентом.

### AuthZ / Authorization

Проверка **что** аутентифицированному субъекту разрешено делать.

### IDOR — Insecure Direct Object Reference

Класс authorization defect, когда пользователь может получить доступ к чужому объекту, подставив его идентификатор без корректной серверной проверки прав.

### SSRF — Server-Side Request Forgery

Уязвимость, при которой атакующий заставляет сервер выполнять нежелательные сетевые запросы, например к internal/private endpoints.

### XSS — Cross-Site Scripting

Инъекция исполняемого browser-side script/content в страницу другого пользователя из-за небезопасной обработки untrusted input/output.

### CSRF — Cross-Site Request Forgery

Атака, при которой браузер аутентифицированного пользователя принуждают отправить нежелательный state-changing request без должной защиты.

## Идентификаторы и артефакты

### REQ — Requirement

**REQ** — устойчивое проверяемое требование к продукту или системе: что должно быть истинно с точки зрения поведения, качества, безопасности, совместимости или другого продукта-контракта.

REQ отвечает на вопрос:

> **Что система обязана обеспечивать?**

Пример ID:

```text
REQ-014
REQ-AUTH-003
```

REQ не должен описывать конкретный файл или implementation technique без необходимости. Один REQ может реализовываться несколькими STEP.

Canonical source: `docs/requirements/SPEC.md`.

### ADR — Architecture Decision Record

**ADR** — неизменяемая историческая запись устойчивого архитектурного решения, его контекста, альтернатив и последствий.

ADR отвечает на вопрос:

> **Какое архитектурное решение принято и почему?**

Пример:

```text
ADR-007 — Использовать PostgreSQL как основной transactional storage
```

Accepted ADR не переписывается задним числом при смене решения. Создаётся новый ADR с `Supersedes`.

ADR не создаётся для каждой мелкой реализации. Он нужен, когда решение формирует долгоживущий контракт, границу подсистем, security/data model, integration strategy или другой значимый trade-off.

Canonical source: `docs/adr/`.

### ASR

**ASR не является термином AI Development Harness.** В текущем protocol и шаблонах такой сущности нет.

Если `ASR` встречается в контексте Harness, это следует считать ошибкой/неоднозначностью и проверить, не имелся ли в виду **ADR**. Агент не должен самостоятельно придумывать расшифровку `ASR` или создавать новый тип артефакта без явного изменения protocol.

В конкретном продукте `ASR` может иметь собственное доменное значение — тогда оно определяется в `docs/GLOSSARY.md`, а не здесь.

### STEP

**STEP** — ограниченная единица планируемой работы с устойчивым идентификатором `STEP-NNN`.

STEP отвечает на вопрос:

> **Какую конкретную работу нужно выполнить, чтобы приблизить проект к требуемому состоянию?**

Task-файл определяет status, type, priority, dependencies, связанные REQ/ADR, goal, context, scope, mutation policy, out of scope, acceptance criteria, verification, deliverables, implementation plan и evidence.

Canonical source: `planning/tasks/STEP-NNN.md`.

### PLAN

Термин используется в двух смыслах:

1. **`planning/PLAN.md`** — roadmap projection всех STEP и их порядка/зависимостей.
2. **`PLAN STEP-NNN`** — команда, которая проводит pre-implementation analysis и сохраняет `Implementation plan` в task-файл.

`PLAN.md` не заменяет task-файлы и не является вторым каноническим описанием STEP.

### STATUS

`planning/STATUS.md` — производная сводка текущего состояния STEP, blockers и progress.

`docs/requirements/STATUS.md` — производная сводка состояния REQ.

STATUS-файлы — **projection**, а не самостоятельный источник контрактов.

### PROJECT_BRIEF

`PROJECT_BRIEF.local.md` — локальный сырой ввод пользователя для bootstrap. Он может быть неполным, субъективным и содержать приватные ссылки.

Brief не является permanent source of truth после `INIT PROJECT`. Нормализованный контекст переносится в project documentation.

### PROJECT.md

`docs/PROJECT.md` — нормализованное описание продукта: назначение, пользователи, цели, границы, constraints и high-level scenarios.

### Architecture baseline

`docs/architecture.md` — актуальная документальная проекция текущей архитектуры. В отличие от ADR, baseline может обновляться по мере эволюции системы, но должен оставаться согласованным с Accepted ADR и фактическим состоянием.

### Open Question

Нерешённый вопрос, на который нельзя безопасно ответить на основании имеющихся источников.

Хранится в `docs/OPEN_QUESTIONS.md` либо превращается в `RESEARCH`/`ADR` STEP, если блокирует движение проекта.

## Содержимое STEP

### Goal

Краткое целевое состояние STEP — что должно измениться после его успешного выполнения.

### Context

Факты, причины и окружение, необходимые для понимания задачи. Context не должен раздуваться в полный пересказ проекта.

### Scope

Явно разрешённый объём работы текущего STEP.

### Out of scope

То, что сознательно **не входит** в STEP, даже если находится рядом по смыслу. Это основной механизм против scope creep.

### Mutation policy

Ограничение на категории файлов/подсистем, которые STEP разрешает изменять, изменять условно или запрещает менять.

### Acceptance Criteria

Набор проверяемых условий, которые должны быть истинны, чтобы считать STEP выполненным.

Acceptance criteria описывают результат, а не просто действия разработчика.

### Verification

Конкретные проверки, команды, тесты или наблюдения, которыми доказываются acceptance criteria.

Verification должен ссылаться на реальные tools/scripts проекта; агенту запрещено выдумывать команды.

### Evidence

Конкретные доказательства выполненной работы: изменённые артефакты, tests, commands и результаты, migrations, screenshots/measurements при необходимости, commit/PR reference и т. п.

Фраза `проверено, работает` evidence не является.

### Deliverable

Артефакт, который STEP обязан создать или изменить: код, документ, migration, workflow, package, configuration и т. п.

### Dependency

Другой STEP или обязательное внешнее условие, без которого текущий STEP нельзя корректно выполнить или закрыть.

### Blocker

Факт, препятствующий продолжению работы. Blocker должен содержать причину и required next action, а не только статус.

### Risk Flag

Классификация риска, влияющая на orchestration. Например security-sensitive, data migration, concurrency, breaking API, infrastructure. Risk flags могут запускать дополнительного reviewer или более сильную модель.

### Implementation Plan

Durable технический handoff, создаваемый `PLAN STEP-NNN` и сохраняемый внутри task-файла. Должен быть достаточно конкретным, чтобы implementer мог работать в новой сессии без chat history.

## Типы STEP

### IMPLEMENTATION

Добавление или изменение product behavior/code/configuration/tests.

### BUGFIX

Исправление подтверждённого дефекта с воспроизводимым ожидаемым поведением.

### ADR

STEP, целью которого является принятие или reconciliation архитектурного решения, а не реализация production code.

### RESEARCH

Исследование неизвестного, сравнение вариантов, spike или получение evidence перед решением. Не должен выдавать догадку за Accepted ADR.

### AUDIT

Формальная проверка состояния без скрытого исправления production code. Найденные дефекты становятся findings/corrective work.

### REVIEW

Проверка уже существующего результата относительно task/REQ/ADR/acceptance/evidence.

### DOCUMENTATION

Документационная работа, где production behavior не должен изменяться.

### HARDENING

Усиление reliability/security/performance/operability существующей capability.

### RELEASE

Release-oriented gate: готовность версии/развёртывания/миграций/документации и других release constraints.

## Review и качество

### Review

Независимая проверка реализации. Reviewer не должен быть автором проверяемого изменения.

Review report хранится отдельно и не переписывает task contract.

### Finding

Конкретная проблема, найденная review/audit. Хороший finding содержит severity, location, scenario/preconditions, impact и fix direction.

### Verdict

Итог review:

- `PASS` — существенных проблем, блокирующих закрытие, не найдено;
- `FAIL` — найдены подтверждённые проблемы, требующие исправления;
- `BLOCKED` — reviewer не может достоверно завершить проверку из-за отсутствующего prerequisite/evidence/environment.

### FIX

Отдельный проход исправления подтверждённых findings последнего применимого FAIL review. FIX не должен превращаться в новую бесконтрольную реализацию.

### Corrective STEP

Новый STEP, создаваемый для дефекта/drift/prerequisite, который не должен скрыто исправляться в scope текущей работы.

### Gate / Deterministic Gate

Проверяемое машиной или воспроизводимой процедурой условие: tests, typecheck, lint, build, migration check, schema validation и т. п.

AI verdict не заменяет deterministic gate.

### Release Check

Проверка проекта перед выпуском: unresolved findings, requirements, tests/build, security, migrations, docs, compatibility/deploy concerns.

## Согласованность документации

### Canonical Source

Файл/артефакт, являющийся основным источником конкретного контракта. Например task-файл — canonical source STEP, а `PLAN.md` — его projection.

### Projection

Производное представление канонических данных, удобное для навигации или отчётности. Projection обязана синхронизироваться с canonical sources.

### Traceability

Возможность пройти связь в обе стороны между requirement, decision, task, implementation и evidence.

Базовая цепочка:

```text
REQ ↔ STEP ↔ Evidence
       ↑
      ADR
```

### Drift

Расхождение между слоями проекта.

#### Architecture Drift

Фактическая реализация расходится с Accepted ADR или устойчивым архитектурным контрактом.

#### Documentation Drift

Документация описывает не то, что реально существует или принято.

#### Status Drift

PLAN/STATUS/REQ status не соответствует canonical task/evidence/factual state.

### RECONCILE

Процесс обнаружения и документированного разрешения drift через `RECONCILE PROJECT`. Он не должен молча переписывать production code.

## Агенты и execution

### Root Agent

Основной агент текущей сессии, который принимает пользовательскую команду, читает protocol и оркестрирует специализированные роли.

### Subagent

Отдельный agent thread со своей ролью, model/effort/configuration и ограниченным контекстом.

### Role

Специализация субагента: `planner`, `implementer`, `reviewer`, `architect`, `git_operator` и т. п.

### Model

Конкретная модель, используемая ролью. Настраивается в `.codex/agents/*.toml` и может отличаться между ролями.

### Reasoning Effort

Объём reasoning budget модели (`low`, `medium`, `high` и другие поддерживаемые конкретной моделью значения). Больше effort обычно дороже и медленнее, поэтому выбирается по сложности роли.

### Sandbox Mode

Ограничение filesystem/tool mutation агента. Например `read-only` для reviewer/planner и `workspace-write` для implementer.

### Approval Policy

Правило, когда Codex должен запросить человеческое подтверждение перед потенциально чувствительным действием.

### Orchestration

Координация стадий/ролей, например:

```text
PLAN → IMPLEMENT → REVIEW → FIX → REVIEW
```

### Durable Handoff

Сохранённый в репозитории результат стадии, позволяющий следующему агенту/сессии продолжить работу без chat history.

## Skills

### Skill / Repository Skill

Версионируемый playbook в `.agents/skills/<name>/`, основной инструкцией которого является `SKILL.md`. Может включать references/scripts/assets.

### Skill Routing

Короткое правило в generated-block `AGENTS.md`, указывающее, для какого класса задач применять установленный skill.

### Skill Registry

`docs/skills/REGISTRY.md` — реестр дополнительных skills, их происхождения и локальных адаптаций.

### Provenance

Информация о происхождении стороннего skill: repository, path, URL, commit/ref, license, дата установки и local modifications.

### Upstream

В контексте skills — исходный внешний источник, из которого skill установлен.

## Git и CI

### COMMIT

Harness-команда для безопасной подготовки локального Git commit: preflight, staging policy, hygiene checks, commit message и traceability. Не выполняет PUSH.

### Conventional Commit

Формат subject вида:

```text
feat(scope): краткое описание
```

Harness дополняет его body с Context / Changes / Verification / Traceability согласно policy.

### PUSH

Публикация уже существующих commit текущей ветки в configured remote после fetch/divergence/safety checks.

### PR — Pull Request

Запрос на интеграцию опубликованной ветки в base branch. Harness может создавать или переиспользовать PR согласно `.project/git-policy.toml`.

### SYNC

Проверка состояния local/remote branch. По умолчанию read-only report; policy может разрешать только безопасный fast-forward.

### Protected Branch

Ветка (`main`, `master` и т. п.), для которой Harness применяет повышенные ограничения на commit/push.

### Remote

Именованный Git remote, обычно `origin`.

### Upstream Branch

В Git-контексте — remote branch, с которой связана локальная ветка. Не путать с upstream источником стороннего skill.

### CI — Continuous Integration

Автоматические проверки репозитория при push/PR.

### Harness Integrity CI

Минимальный CI самого Harness: обязательные файлы, configs, agent bindings, forbidden tracked files, repository hygiene и форматные invariants.

### Product CI

Проверки конкретного продукта после INIT: tests, lint, typecheck, build, migrations, deploy checks и другие реальные gates выбранного стека.

### Local-only file

Файл, намеренно не отслеживаемый Git, например `PROJECT_BRIEF.local.md`, `.env` или локальные overrides.

## Команды Harness

Канонический список пользовательских команд и их семантика находится в [`COMMANDS.md`](COMMANDS.md). State transitions — в `planning/EXECUTION_PROTOCOL.md`.

## QUICK FIX

Команда/режим для micro-change, которому не нужна отдельная STEP/REQ/ADR traceability. Не является способом обойти процесс для маленькой фичи или скрытого behavior change.

## Micro-change

Маленькое низкорисковое изменение без изменения product/API/data/security/architecture/dependency contract. Пример: опечатка, пунктуация, безопасный комментарий, локальное formatting.

## Language Policy

Централизованные языковые настройки `.project/manifest.yaml` → `language`, определяющие язык documentation, commits, comments, test names, fixtures, GitHub templates и release notes. Не меняют identifiers/API keys и не отменяют multilingual domain requirements.

## GitHub Issue Form

Structured YAML template из `.github/ISSUE_TEMPLATE/*.yml`, который GitHub использует для создания типизированного issue с обязательными/необязательными полями. Harness генерирует формы по фактическому tooling проекта через `GENERATE GITHUB TEMPLATES`.

## Pull Request Template

`.github/pull_request_template.md` — форма описания PR. В Harness она может регенерироваться по текущим verification gates и traceability conventions проекта.

## `GENERATE GITHUB TEMPLATES`

Idempotent-команда, которая инспектирует актуальный repository stack/tooling/CI и заменяет managed Issue/PR templates. Не создаёт commit автоматически.

## `AGENTS.local.md`

Локальный, исключённый из Git файл пользовательских alias-команд и предпочтений. `AGENTS.md` требует читать его последним, если он существует. Локальные инструкции расширяют workflow, но не должны скрыто обходить safety/ADR/STEP/security gates.
