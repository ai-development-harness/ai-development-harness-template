---
name: add-plan-step
description: Convert a short user request into a correctly classified, traceable, dependency-aware STEP and update roadmap projections.
---
# add-plan-step

Используй для `STEP ADD: ...`.

- Сначала semantic duplicate/overlap search.
- ID = следующий после максимального когда-либо использованного; дырки не переиспользуются.
- Определи Type/Priority/Phase/Risk flags.
- Свяжи existing REQ; новый REQ только для нового product contract. Новый REQ создавай отдельным `docs/requirements/REQ-NNN-<slug>.md` по template и добавляй в `docs/requirements/SPEC.md` + `STATUS.md` projections.
- Не создавай ADR для implementation detail. Если нужен durable decision — prerequisite ADR/RESEARCH flow.
- Определи dependencies и влияние на будущий roadmap.
- Заполни Goal, Context, Scope, Mutation policy, Out of scope, Acceptance, Verification, Deliverables.
- `Implementation plan` оставь Not planned.
- Обнови PLAN/STATUS, canonical REQ traceability и requirements SPEC/STATUS projections.
- Production code не меняй.
- Верни `STEP PLAN STEP-NNN`.
