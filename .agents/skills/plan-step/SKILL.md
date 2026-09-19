---
name: plan-step
description: Produce and persist a concrete implementation plan for an existing STEP without changing production code.
---
# plan-step

Используй для `STEP PLAN STEP-NNN`.

Execution Status для команды ведёт global command wrapper; skill не создаёт отдельный per-STEP state.

Resolve task → dependencies → REQ → ADR → architecture → code/tests/config. При сложной задаче делегируй анализ `planner`. Проверь blockers и необходимость ADR.

Подготовь порядок реализации, impacted areas/files, data/API compatibility, tests, verification, risks/rollback. Root-agent сохраняет итог в `## Implementation plan`.

После сохранения plan обязательно выполни:

```bash
python3 tools/harness/execution-state.py stamp-plan STEP-NNN
```

`stamp-plan` детерминированно выставляет `Plan status: Ready`, увеличивает revision, записывает `Plan basis: sha256:...` от текущего task contract и timestamp.

Если session оборвалась после `stamp-plan`, но до записи execution `complete`, resolver может признать PLAN завершённым по valid Plan basis и не повторять planning.

Не ставь STEP `В работе` и не меняй production code.
