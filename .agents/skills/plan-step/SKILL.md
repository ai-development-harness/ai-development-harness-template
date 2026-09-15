---
name: plan-step
description: Produce and persist a concrete implementation plan for an existing STEP without changing production code.
---
# plan-step

Используй для `PLAN STEP-NNN`.

Resolve task → dependencies → REQ → ADR → architecture → code/tests/config. При сложной задаче делегируй анализ `planner`. Проверь blockers и необходимость ADR. Подготовь порядок реализации, impacted areas/files, data/API compatibility, tests, verification, risks/rollback. Root-agent сохраняет итог в `## Implementation plan` с plan revision/timestamp. Не ставь STEP `В работе` и не меняй production code.
