---
name: run-step
description: Orchestrate PLAN → IMPLEMENT → verification → independent REVIEW → bounded FIX/REVIEW cycles for one STEP.
---
# run-step

Используй для `RUN STEP-NNN`.

1. Resolve STEP, blockers и Type.
2. Dispatch: implementation-like → coding flow; ADR → architect/decision flow; RESEARCH → research deliverables; AUDIT → audit-only; REVIEW → review-only; DOCUMENTATION/RELEASE → task-specific mutations/gates.
3. Для coding flow: если plan отсутствует/stale — planner → сохранить PLAN.
4. implementer → реализация.
5. deterministic verification.
6. independent reviewer; security/test reviewers только при необходимости.
7. FAIL → implementer FIX → fresh REVIEW; максимум 3 цикла.
8. PASS + gates → close/sync evidence/docs/status.
9. BLOCKED или 3 FAIL → stop, сохранить факты, не объявлять success.

Не запускай параллельные write-agents над одним scope.
