# Команды Harness

Команды — стабильный человеко-машинный интерфейс. Подробные state transitions описаны в `planning/EXECUTION_PROTOCOL.md`. Локальные пользовательские alias-команды можно добавить в `AGENTS.local.md`; они читаются после `AGENTS.md`.

## `INIT PROJECT`

Однократный bootstrap из `PROJECT_BRIEF.local.md`. Создаёт project knowledge base и initial roadmap, но не production code. Повторный INIT после `initialized: true` не выполняется автоматически.

## `ADD STEP: <описание>`

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
- возвращает `PLAN STEP-NNN`.

Production code не меняется.

## `FIND SKILL: <описание>`

Ищет подходящие Agent Skills/repository skills на GitHub и в доступном web, инспектирует содержимое и сохраняет TOP-5 в `planning/skill-searches/`. Ничего не устанавливает. Для каждого кандидата возвращает exact source/path/link, fit, limitations, license/provenance и safety notes.

Следующий шаг: `INSTALL SKILL: #N` либо `CREATE SKILL: <описание>`.

## `INSTALL SKILL: <source | #N>`

После явного выбора пользователя повторно инспектирует сторонний skill, не выполняя его scripts, блокирует high-risk варианты, затем устанавливает bundle в `.agents/skills/`, фиксирует `UPSTREAM.md`, обновляет `docs/skills/REGISTRY.md` и generated `SKILL-ROUTING` block `AGENTS.md`. `#N` resolve-ится из последнего durable search report, а не из chat history.

## `CREATE SKILL: <описание>`

Создаёт project-native skill, если готового подходящего варианта нет. Основан на project conventions и актуальной авторитетной документации, регистрируется в Registry и routing block. Не дублирует core harness protocol.

## `GENERATE GITHUB TEMPLATES`

Изучает актуальные technologies/tooling/CI/project conventions и полностью пересоздаёт managed GitHub Issue Forms и Pull Request template. Работает на любом этапе; существующие target files заменяются, чтобы пользователь увидел изменение в обычном diff. Язык берётся из `language.githubTemplates`. Подробнее: `GITHUB_TEMPLATES.md`.

## `QUICK FIX: <описание>`

Выполняет маленькую low-risk правку без создания STEP/REQ/ADR. Разрешён только для micro-change без изменения product/API/data/security/architecture/dependencies. Если scope оказался больше — команда прекращается и предлагает `ADD STEP:`. Если пользователь уже исправил мелочь вручную, можно сразу использовать `GIT CHECK`/`COMMIT`. Подробнее: `QUICK_CHANGES.md`.

## `PLAN STEP-NNN`

Проводит pre-implementation analysis и **сохраняет** результат в `## Implementation plan` task-файла. Production code не меняется. План должен быть достаточно конкретным, чтобы следующая сессия могла выполнить `IMPLEMENT` без истории чата.

## `IMPLEMENT STEP-NNN`

Реализует сохранённый план в пределах task contract. Ставит STEP в `В работе`, добавляет/обновляет tests и запускает verification. Не закрывает STEP до независимого review.

## `REVIEW STEP-NNN`

Независимая проверка. Reviewer read-only по product code. Создаётся immutable report в `planning/reviews/STEP-NNN/`. Verdict: `PASS`, `FAIL`, `BLOCKED`.

## `FIX STEP-NNN`

Исправляет подтверждённые findings последнего применимого FAIL review. Не расширяет scope. После FIX следующая команда — `REVIEW STEP-NNN`.

## `RUN STEP-NNN`

Автоматический orchestrated flow:

```text
PLAN (если актуального плана нет)
 → IMPLEMENT
 → deterministic verification
 → REVIEW
 → [условно security/test review]
 → FIX ↔ REVIEW (максимум 3 цикла)
 → CLOSE
```

При blocker или исчерпании циклов останавливается и не маскирует failure.

## `AUDIT STEP-NNN`

Формальная проверка фактического состояния без production mutation. Подходит для historical reconciliation, architecture/data/security audits. Defects становятся findings/corrective STEP, а не скрытыми исправлениями.

## `STATUS PROJECT`

Проверяет и при необходимости регенерирует projection статусов, показывает blockers, unblocked work и drift indicators. Не пишет product code.

## `NEXT STEP`

Read-only рекомендация следующего **unblocked** шага на основании dependencies, priority, risk и roadmap. Не выбирает просто минимальный номер.

## `RECONCILE PROJECT`

Сравнивает code/tests/config с REQ/ADR/architecture/STEP/evidence. Создаёт audit report и при необходимости corrective STEP. Не исправляет production code молча.

## `RELEASE CHECK`

Финальный release-oriented review по фактическим проектным gates: unresolved critical/high findings, requirements, migrations, tests/build, security, docs, upgrade/deploy concerns. Создаёт report в `planning/releases/`.

## `CHECK HARNESS UPDATE`

Read-only проверка доступной версии Harness. Использует `.project/harness.lock.json` как BASE и `.project/harness-update.toml` как ownership/source policy. Показывает safe changes/conflicts, но не меняет working tree, Git refs, lock, STEP, commit, push или PR.

Если lock отсутствует, возвращает legacy-adoption blocker вместо угадывания BASE. Подробно: [`UPDATES.md`](UPDATES.md).

## `UPDATE HARNESS`

Maintenance mutation protocol layer без STEP. Допускается только после успешного `CHECK HARNESS UPDATE`.

Updater меняет только allowlisted Harness paths, использует 3-way merge для shared files, сохраняет generated project blocks в `README.md`/`AGENTS.md` и останавливается до mutation при конфликтах.

Команда не запускает migration/install/bootstrap scripts из target release и не выполняет commit/push/PR. После неё: inspect diff → `GIT CHECK` → `COMMIT`.

## `GIT CHECK`

Read-only Git preflight: проверяет branch/upstream/ahead-behind, staged/unstaged/untracked, Harness integrity, policy и подозрительные файлы. Ничего не stage/commit/push.

## `COMMIT` / `COMMIT: <подсказка>`

Безопасно формирует локальный commit по `.project/git-policy.toml`: проверяет Harness/diff, исключает unrelated/suspicious files, при необходимости создаёт ветку, stage-ит разрешённые файлы и формирует подробный Conventional Commit message по `.gitmessage`. `COMMIT` никогда не делает push.

## `PUSH`

Проверяет Harness, fetch/divergence и protected-branch policy, затем без force отправляет текущую ветку в configured remote. После успешного push применяет PR-policy: ничего, предложить PR или создать PR при отсутствии.

## `PR`

Создаёт Pull Request для опубликованной ветки либо возвращает существующий PR согласно policy. Использует `.github/pull_request_template.md`, repository evidence и verification; дубликаты не создаёт.

## `SYNC`

Fetch + ahead/behind/divergence. По умолчанию read-only report; при `sync.mode="ff-only"` допускает только безопасный fast-forward чистой рабочей копии. Merge/rebase автоматически не выполняются.
