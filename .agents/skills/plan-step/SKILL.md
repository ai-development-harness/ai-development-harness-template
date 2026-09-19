---
name: plan-step
description: Produce and persist a concrete implementation plan for an existing STEP without changing production code.
---
# plan-step

Используй для `STEP PLAN STEP-NNN`.

Resolve task → dependencies → REQ → ADR → architecture → code/tests/config. При сложной задаче делегируй анализ `planner`. Проверь blockers и необходимость ADR.

Перед работой отметь crash-safe phase:

```bash
python3 tools/harness/execution-state.py begin STEP-NNN \
  --command 'STEP PLAN STEP-NNN'
```

Подготовь порядок реализации, impacted areas/files, data/API compatibility, tests, verification, risks/rollback. Root-agent сохраняет итог в `## Implementation plan`.

После сохранения plan обязательно выполни:

```bash
python3 tools/harness/execution-state.py stamp-plan STEP-NNN
python3 tools/harness/execution-state.py complete STEP-NNN \
  --command 'STEP PLAN STEP-NNN' \
  --result SUCCESS
```

`stamp-plan` детерминированно выставляет `Plan status: Ready`, увеличивает revision, записывает `Plan basis: sha256:...` от текущего task contract и timestamp.

Если session оборвалась после `stamp-plan`, но до completion-checkpoint, resolver всё равно распознаёт PLAN как завершённый по valid Plan basis и не тратит токены на повторный planning.

Не ставь STEP `В работе` и не меняй production code.
