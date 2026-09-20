---
name: plan-step
description: Produce and persist a concrete implementation plan for an existing STEP without changing production code.
---
# plan-step

Используй для `STEP PLAN STEP-NNN`.

Execution Status для команды ведёт global command wrapper; skill не создаёт отдельный per-STEP state.

## Phase A — Contract validation

До написания Implementation plan восстанови task → hard dependencies → canonical REQ → Accepted ADR → architecture → blocking OPEN_QUESTIONS → relevant code/tests/config.

Сначала выполни deterministic checks:

```bash
python3 .harness/tools/validate.py --mode manual
```

Затем проведи semantic consistency review. Для сложной задачи делегируй независимый read-only анализ `planner`. Обязательно проверь:

- Goal не противоречит Scope/Out of scope;
- Acceptance полностью следует из REQ/ADR и не требует запрещённой mutation;
- Verification действительно способна доказать Acceptance;
- linked REQ совместимы друг с другом и с Accepted ADR/architecture;
- dependencies достаточны и не скрывают missing prerequisite;
- текущий STEP не конфликтует по ownership с соседним roadmap STEP;
- OPEN question/TBD не влияет на решение, которое требуется для реализации.

Если найден contract conflict, missing decision/prerequisite, impossible acceptance или blocker — не создавай Ready plan и не запускай `stamp-plan`. Заверши PLAN как `BLOCKED` с конкретной причиной и предложенным RESEARCH/ADR/corrective STEP. Не исправляй продуктовый контракт догадкой.

## Phase B — Implementation planning

Только после PASS Phase A подготовь порядок реализации, impacted areas/files, data/API compatibility, tests, verification, risks/rollback. Root-agent сохраняет итог в `## Implementation plan`.

После сохранения plan обязательно выполни:

```bash
python3 .harness/tools/execution-state.py stamp-plan STEP-NNN
```

`stamp-plan` детерминированно выставляет `Plan status: Ready`, увеличивает revision, записывает transitive `Plan basis: sha256:...` и timestamp. Basis включает STEP contract и upstream planning context (linked REQ/ADR, hard dependency contracts и architecture baseline), поэтому их изменение автоматически делает plan stale.

Если session оборвалась после `stamp-plan`, но до записи execution `complete`, resolver может признать PLAN завершённым по valid Plan basis и не повторять planning.

Не ставь STEP `В работе` и не меняй production code.
