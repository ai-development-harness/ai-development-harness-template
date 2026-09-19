# `.project/`

Служебная metadata AI Development Harness.

`manifest.yaml` содержит только техническое состояние Harness, current release, project initialization state и ссылки на основные источники истины. Бизнес-требования, архитектурные решения и планы здесь хранить нельзя.

`project.initialized` меняется на `true` только после успешного `PROJECT INIT` и проверки согласованности созданной документации.

## Execution policy

`.project/manifest.yaml → execution.maxFixReviewCycles` задаёт максимальное число циклов `FIX → REVIEW` внутри одного `STEP RUN STEP`. Допустимый диапазон — от 1 до 5 включительно; template default — 3.

`review.security` и `review.tests` управляют дополнительными specialized reviewers: `auto` запускает reviewer по фактическим рискам/diff/test surface, `always` — при каждом review-проходе. Режима `never` намеренно нет: настройка может усилить review, но не отключить safety gate.

`skills.search.maxResults` задаёт максимальный размер shortlist команды `SKILL FIND`; допустимо от 1 до 10, template default — 5.

Все эти значения проверяются `tools/harness/validate.py`, поэтому отсутствующая или недопустимая настройка блокирует Harness validation до запуска orchestration.

Локальные/секретные overrides при необходимости складываются в `.project/local/`; каталог игнорируется Git.

## Repository policies

- `git-policy.toml` — поведение GIT COMMIT / GIT PUSH / GIT PR / GIT SYNC, ветки и commit messages.
- `harness-policy.toml` — deterministic integrity/safety checks для local preflight и CI.
- `harness-update.toml` — source repository, ownership classes, путь к remote update manifest и merge policy для self-update.
- `harness.lock.json` — машинный known BASE текущего Harness release; JSON намеренно не требует inline-комментариев.
- `harness-update-graph.json` — machine-readable граф допустимых переходов между immutable Harness releases; локальная копия входит в protocol layer, а выбор маршрута делается по версии из canonical `default_branch`.
- `command-transitions.json` — machine-readable source of truth для canonical command surface, chain eligibility, explicit transition edges, `onPreviousResult` и runtime preconditions. До skill routing canonical command проходит structural validation по этому graph.
`.project/local/execution/execution-status.json` — единый local operational state всех canonical Harness executions. Он игнорируется Git, не является product evidence и может хранить несколько независимых running/completed records. Canonical repository artifacts имеют приоритет над local state.

`harness.lock.json` не содержит secrets. Его нужно хранить в Git вместе с проектом; удаление lock переводит updater в legacy-adoption mode.

Все tracked YAML/TOML policy/config files в template снабжены inline-комментариями для каждого параметра. При добавлении нового параметра сохраняй это правило: назначение, допустимое поведение и хотя бы один пример должны быть видны рядом с настройкой.

## Language policy

`.project/manifest.yaml` → `language` — единый источник языка docs/commits/comments/tests/fixtures/GitHub templates/release notes.
