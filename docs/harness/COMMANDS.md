# Команды Harness

Команды — стабильный человеко-машинный интерфейс. Каноническая форма начинается с явного namespace: `<DOMAIN> <ACTION> ...`. Подробный синтаксис и chain operator `>` описаны в [`COMMAND_SYNTAX.md`](COMMAND_SYNTAX.md).

Допустимость переходов между командами определяется **только** machine-readable graph `.project/command-transitions.json`. Полная человекочитаемая матрица — [`COMMAND_TRANSITIONS.md`](COMMAND_TRANSITIONS.md). До skill routing canonical command проходит deterministic `tools/harness/validate-command.py`.

State transitions выполнения описаны в `planning/EXECUTION_PROTOCOL.md`.

Старые ненеймспейсные формы не являются каноническими alias. Локальные пользовательские alias-команды можно добавить только явно в `AGENTS.local.md`; они читаются после `AGENTS.md`.

## Цепочки

Для разрешённых команд одной области можно не повторять namespace:

```text
GIT CHECK > COMMIT > PUSH > PR
STEP PLAN STEP-024 > IMPLEMENT > REVIEW
HARNESS UPDATE CHECK TO v0.4.0 > APPLY
```

Вся цепочка сначала нормализуется и проверяется по `.project/command-transitions.json`. Отсутствующий edge означает `INVALID_CHAIN` и ноль выполненных сегментов. После structural PASS дальнейшее выполнение определяется `onPreviousResult` и `runtimePreconditions` конкретного edge. Полные правила — в [`COMMAND_SYNTAX.md`](COMMAND_SYNTAX.md) и [`COMMAND_TRANSITIONS.md`](COMMAND_TRANSITIONS.md).

## `PROJECT INIT`

Однократный bootstrap из `PROJECT_BRIEF.local.md`. Создаёт project knowledge base и initial roadmap, но не production code. Повторный INIT после `initialized: true` не выполняется автоматически.

## `STEP ADD: <описание>`

Преобразует короткую человеческую задачу в корректный новый STEP:

- ищет дубликаты/пересечения;
- выбирает следующий стабильный ID;
- классифицирует Type/Priority/Phase/Risk flags;
- связывает существующие REQ/ADR;
- создаёт новый REQ только при появлении нового продуктового контракта;
- не выдумывает ADR; при необходимости создаёт prerequisite ADR/RESEARCH STEP;
- вычисляет dependencies;
- формирует Goal/Context/Scope/Mutation policy/Out of scope/Acceptance/Verification/Deliverables;
- обновляет PLAN/STATUS;
- возвращает `STEP PLAN STEP-NNN`.

Production code не меняется.

## `SKILL FIND: <описание>`

Ищет подходящие Agent Skills/repository skills на GitHub и в доступном web, инспектирует содержимое и сохраняет shortlist в `planning/skill-searches/`. Максимальное число кандидатов задаёт `skills.search.maxResults` (1–10, default 5). Ничего не устанавливает. Для каждого кандидата возвращает exact source/path/link, fit, limitations, license/provenance и safety notes.

Следующий шаг: `SKILL INSTALL: #N` либо `SKILL CREATE: <описание>`.

## `SKILL INSTALL: <source | #N>`

После явного выбора пользователя повторно инспектирует сторонний skill, не выполняя его scripts, блокирует high-risk варианты, затем устанавливает bundle в `.agents/skills/`, фиксирует `UPSTREAM.md`, обновляет `docs/skills/REGISTRY.md` и generated `SKILL-ROUTING` block `AGENTS.md`. `#N` resolve-ится из последнего durable search report, а не из chat history.

## `SKILL CREATE: <описание>`

Создаёт project-native skill, если готового подходящего варианта нет. Основан на project conventions и актуальной авторитетной документации, регистрируется в Registry и routing block. Не дублирует core harness protocol.

## `GITHUB GENERATE TEMPLATES`

Изучает актуальные technologies/tooling/CI/project conventions и полностью пересоздаёт managed GitHub Issue Forms и Pull Request template. Работает на любом этапе; существующие target files заменяются, чтобы пользователь увидел изменение в обычном diff. Язык берётся из `language.githubTemplates`. Подробнее: `GITHUB_TEMPLATES.md`.

## `PROJECT QUICK FIX: <описание>`

Выполняет маленькую low-risk правку без создания STEP/REQ/ADR. Разрешён только для micro-change без изменения product/API/data/security/architecture/dependencies. Если scope оказался больше — команда прекращается и предлагает `STEP ADD:`. Если пользователь уже исправил мелочь вручную, можно сразу использовать `GIT CHECK > COMMIT` или отдельные `GIT CHECK` и `GIT COMMIT`. Подробнее: `QUICK_CHANGES.md`.

## `STEP PLAN STEP-NNN`

Проводит pre-implementation analysis и **сохраняет** результат в `## Implementation plan` task-файла. Production code не меняется. План должен быть достаточно конкретным, чтобы следующая сессия могла выполнить `STEP IMPLEMENT STEP-NNN` без истории чата.

## `STEP IMPLEMENT STEP-NNN`

Реализует сохранённый план в пределах task contract. Ставит STEP в `В работе`, добавляет/обновляет tests и запускает verification. Не закрывает STEP до независимого review.

## `STEP REVIEW STEP-NNN`

Независимая проверка. Reviewer read-only по product code. Security/test reviewer запускаются по `review.security` / `review.tests`: `auto` — по фактической необходимости, `always` — для каждого review-прохода. Создаётся immutable report в `planning/reviews/STEP-NNN/`. Verdict: `PASS`, `FAIL`, `BLOCKED`.

## `STEP FIX STEP-NNN`

Исправляет подтверждённые findings последнего применимого FAIL review. Не расширяет scope. После FIX следующая команда — `STEP REVIEW STEP-NNN`.

## `STEP RUN STEP-NNN`

Автоматический orchestrated flow:

```text
PLAN (если актуального плана нет)
 → IMPLEMENT
 → deterministic verification
 → REVIEW
 → [security/test review по review.* policy]
 → FIX ↔ REVIEW (лимит из `execution.maxFixReviewCycles`, допустимо 1–5)
 → CLOSE
```

При blocker или исчерпании циклов останавливается и не маскирует failure.

## `STEP AUDIT STEP-NNN`

Формальная проверка фактического состояния без production mutation. Подходит для historical reconciliation, architecture/data/security audits. Defects становятся findings/corrective STEP, а не скрытыми исправлениями.

## `PROJECT STATUS`

Проверяет и при необходимости регенерирует projection статусов, показывает blockers, unblocked work и drift indicators. Не пишет product code.

## `STEP NEXT`

Read-only рекомендация следующего **unblocked** шага на основании dependencies, priority, risk и roadmap. Не выбирает просто минимальный номер.

## `PROJECT RECONCILE`

Работает только после успешного `PROJECT INIT` (`.project/manifest.yaml → project.initialized: true`).

Если проект ещё не инициализирован, команда ничего не меняет, не создаёт audit report/REQ/ADR/STEP и возвращает `PROJECT RECONCILE: NOT_APPLICABLE` с handoff → `PROJECT INIT`.

В инициализированном проекте сравнивает code/tests/config с REQ/ADR/architecture/STEP/evidence, создаёт audit report и при необходимости corrective STEP. Не исправляет production code молча.

## `RELEASE CHECK`

Финальный release-oriented review по фактическим проектным gates: unresolved critical/high findings, requirements, migrations, tests/build, security, docs, upgrade/deploy concerns. Создаёт report в `planning/releases/`.

## `HARNESS UPDATE CHECK [TO <tag>]`

Read-only проверка доступного маршрута Harness update. Использует `.project/harness.lock.json` как BASE, `.project/harness-update.toml` как source/ownership policy и canonical remote `.project/harness-update-graph.json` как routing metadata.

Без `TO` конечный target берётся из `.project/harness-update-graph.json.latest`. С `TO <tag>` пользователь задаёт конкретный конечный target. В обоих случаях updater обязан построить допустимую цепочку release hops; существующий immutable tag без route не считается допустимым target.

Команда моделирует весь route hop-by-hop, показывает bridge/reload boundaries, safe changes/conflicts и не меняет working tree, Git refs, lock, STEP, commit, push или PR.

Команда разрешена как до, так и после `PROJECT INIT`: `project.initialized: false` не является blocker для проверки Harness update.

## `HARNESS UPDATE APPLY [TO <tag>]`

Maintenance mutation protocol layer без STEP. Допускается только после успешного check **для того же конечного target и route**.

Команда применяет заранее проверенную цепочку строго hop-by-hop. Каждый hop использует immutable release tags и обычные ownership/3-way rules. Lock обновляется только после postcondition соответствующего hop. Если edge помечен `reloadRequired`, текущий запуск останавливается на достигнутом bridge с `UPDATER_RELOAD_REQUIRED`; после reload повторяется та же команда до исходного конечного target.

Команда разрешена до `PROJECT INIT`. Pre-init update обновляет только protocol layer/lock, не выполняет bootstrap проекта и не переводит `project.initialized` в `true`.

Пример конечного target:

```text
HARNESS UPDATE APPLY TO v0.2.3
```

Updater не выполняет executable migration/install/bootstrap actions из `.project/harness-update-graph.json` или target release, не делает commit/push/PR. После неё: inspect diff → `GIT CHECK > COMMIT` либо те же команды отдельно.

## `GIT CHECK`

Read-only Git preflight: проверяет branch/upstream/ahead-behind, staged/unstaged/untracked, Harness integrity, policy и подозрительные файлы. Ничего не stage/commit/push.

## `GIT COMMIT` / `GIT COMMIT: <подсказка>`

Безопасно формирует локальный commit по `.project/git-policy.toml`: проверяет Harness/diff, исключает unrelated/suspicious files, при необходимости создаёт ветку, stage-ит разрешённые файлы и формирует подробный Conventional Commit message по `.gitmessage`. `GIT COMMIT` никогда не делает push.

## `GIT PUSH`

Проверяет Harness, fetch/divergence и protected-branch policy, затем без force отправляет текущую ветку в configured remote. После успешного push применяет PR-policy: ничего, предложить PR или создать PR при отсутствии.

## `GIT PR`

Создаёт Pull Request для опубликованной ветки либо возвращает существующий PR согласно policy. Использует `.github/pull_request_template.md`, repository evidence и verification; дубликаты не создаёт.

## `GIT SYNC`

Fetch + ahead/behind/divergence. По умолчанию read-only report; при `sync.mode="ff-only"` допускает только безопасный fast-forward чистой рабочей копии. Merge/rebase автоматически не выполняются.
