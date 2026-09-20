# Requirements Specification

> Projection/index продуктовых требований. Каноническое определение каждого REQ хранится в отдельном `REQ-NNN-*.md`.

## Правила

- ID стабилен и не переиспользуется: `REQ-001`, `REQ-002`, ...
- Каждый REQ хранится отдельным файлом `docs/requirements/REQ-NNN-<slug>.md`.
- Требование должно быть проверяемым.
- Техническая задача сама по себе не требует отдельного REQ.
- Implementation detail не маскируй под product requirement.
- При изменении смысла requirement обновляй его canonical-файл, traceability и связанные projections.
- `SPEC.md` содержит только индекс и не дублирует Requirement / Rationale / Acceptance / Traceability.
- Lifecycle-статус REQ хранится только в `docs/requirements/STATUS.md` и выводится из STEP, evidence и review.

## Требования

`PROJECT INIT` удалит template REQ, создаст фактические `REQ-NNN-*.md` и перестроит этот индекс.

| REQ | Название | Приоритет | Источник |
|---|---|---|---|
| [REQ-001](REQ-001-template.md) | TEMPLATE | Средний | PROJECT_BRIEF |
