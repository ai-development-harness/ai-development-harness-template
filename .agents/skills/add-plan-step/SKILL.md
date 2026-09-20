---
name: add-plan-step
description: Convert a short user request into a correctly classified, traceable, dependency-aware STEP and update roadmap projections.
---
# add-plan-step

Используй для `STEP ADD: ...`.

- Сначала semantic duplicate/overlap search по существующим STEP и REQ.
- ID = следующий после максимального когда-либо использованного; дырки не переиспользуются.
- Определи Type/Priority/Phase/Risk flags.
- Свяжи existing REQ; новый REQ только для нового product contract. Новый REQ создавай отдельным `docs/requirements/REQ-NNN-<slug>.md` по template и добавляй в `SPEC.md` + `STATUS.md` projections.
- Не создавай ADR для implementation detail. Если нужен durable decision — prerequisite ADR/RESEARCH flow.
- Определи dependencies и влияние на будущий roadmap.
- Заполни Goal, Context, Scope, Mutation policy, Out of scope, Acceptance, Verification, Deliverables.
- Перед handoff проверь новый STEP на конфликты с linked REQ/ADR, соседними STEP, architecture, dependencies и OPEN_QUESTIONS. Объективный overlap не маскируй новым STEP: расширь/свяжи существующий либо явно раздели ownership.
- Blocking ambiguity должна стать OPEN_QUESTION или prerequisite RESEARCH/ADR STEP; текущий STEP обязан зависеть от prerequisite и не считаться executable до его завершения.
- `Implementation plan` оставь Not planned.
- Обнови PLAN/STATUS, canonical REQ traceability и requirements projections.
- Запусти `python3 .harness/tools/validate.py --mode manual`; static planning errors исправь до завершения ADD.
- Production code не меняй.
- Верни `STEP PLAN STEP-NNN` только для непротиворечивого unblocked STEP. Иначе явно верни blocker/prerequisite.
