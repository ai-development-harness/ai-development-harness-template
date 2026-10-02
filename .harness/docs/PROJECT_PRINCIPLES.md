# Project Principles

Project Principle (`PRN-NNN`) — project-owned долгоживущий инженерный инвариант, который применяется ко множеству будущих решений и может блокировать PLAN/REVIEW.

Это не REQ и не ADR:

- **REQ** — что должна делать система;
- **ADR** — какое конкретное архитектурное решение принято и почему;
- **PRN** — какое общее инженерное правило обязаны соблюдать будущие решения.

## Contract

Principles хранятся в configured `sources.principles` (по умолчанию `docs/principles`).

```yaml
schema: 1
id: PRN-004
status: active
severity: blocking
scope: project
superseded_by: null
requirements: []
adrs: []
```

Обязательные sections: `Rule`, `Rationale`, `Applies to`, `Exceptions / approved deviation`.

Statuses: `active | superseded | deprecated`. Severity: `blocking | advisory`.

## Enforcement

- `PROJECT INIT` создаёт PRN только для действительно global engineering constraints.
- `STEP PLAN` проверяет applicable principles до Ready.
- `STEP REVIEW` проверяет implementation against applicable principles.
- `PROJECT RECONCILE` ищет violations и obsolete references.
- `RELEASE CHECK` блокирует release при unresolved applicable violation blocking principle.

Applicability — semantic judgement. Schema, IDs, lifecycle и freshness — deterministic.

Все **active blocking** principles входят в planning context fingerprint. Поэтому изменение project-wide blocking rule автоматически делает существующий Ready plan stale. Advisory principle сам по себе execution не блокирует.

## Governance

Blocking principle нельзя менять как побочный эффект обычного FIX. Старая версия переводится в `superseded` с `superseded_by: PRN-NNN` либо `deprecated` reviewable change.

Approved deviation должна быть явной и traceable в STEP/ADR; модель не может молча проигнорировать blocking principle.
