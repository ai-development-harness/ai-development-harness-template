---
name: run-step
description: Orchestrate PLAN → IMPLEMENT → verification → independent REVIEW → bounded FIX/REVIEW cycles for one STEP.
---
# run-step

Используй для `STEP RUN STEP-NNN`.

1. Resolve STEP, blockers и Type.
2. Прочитай `.project/manifest.yaml`: `execution.maxFixReviewCycles` должен быть целым 1–5, а `review.security` и `review.tests` — только `auto` или `always`. При отсутствующей/недопустимой настройке остановись с configuration blocker и не подставляй скрытый default.
3. Dispatch: implementation-like → coding flow; ADR → architect/decision flow; RESEARCH → research deliverables; AUDIT → audit-only; REVIEW → review-only; DOCUMENTATION/RELEASE → task-specific mutations/gates.
4. Для coding flow: если plan отсутствует/stale — planner → сохранить PLAN.
5. implementer → реализация.
6. deterministic verification.
7. independent reviewer обязателен; security/test reviewers запускай согласно `review.security` / `review.tests`: `auto` — по risk/factual diff/test surface, `always` — для каждого review-прохода.
8. FAIL → implementer FIX → fresh REVIEW; повторять не более `execution.maxFixReviewCycles` циклов.
9. PASS + gates → close/sync evidence/docs/status.
10. BLOCKED или исчерпан лимит FIX/REVIEW → stop, сохранить факты, не объявлять success.

Не запускай параллельные write-agents над одним scope.
