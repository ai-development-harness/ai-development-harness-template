---
name: documentation-sync
description: Synchronize verified implementation changes into project documentation and projections without inventing behavior.
---
# documentation-sync

Обновляй только затронутые docs после подтверждённой реализации. Source — фактический code/tests/evidence + Accepted ADR/REQ. Не придумывай API. Синхронизируй REQ traceability, PLAN/STATUS, task evidence и relevant subsystem docs; lifecycle-status REQ меняй только в `docs/requirements/STATUS.md`, не в `SPEC.md`. Accepted ADR immutable. Используй `docs` agent для механической части.
