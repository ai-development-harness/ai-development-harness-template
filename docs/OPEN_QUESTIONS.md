# Open Questions

Здесь находятся существенные вопросы, которые нельзя безопасно решить предположением.

Формат:

```text
OQ-001 — Краткий вопрос
Status: OPEN | RESOLVED | DEFERRED
Affects: REQ-..., STEP-..., ADR-...
Context: ...
Decision needed: ...
Resolution: ...
```

`PROJECT INIT` должен предпочесть OPEN_QUESTION выдуманному архитектурному решению. Когда вопрос решён, зафиксируй результат в соответствующем REQ/ADR/STEP и обнови статус здесь.

## Blocking semantics

`OPEN` question считается blocking для STEP, если его `Affects` содержит сам STEP, linked REQ/ADR этого STEP либо решение, без которого нельзя честно определить Scope/Acceptance/architecture.

В таком случае:

- вопрос должен быть разрешён до `Plan status: Ready`;
- если для ответа нужна отдельная работа, создай prerequisite `RESEARCH` или `ADR` STEP и добавь dependency;
- `STEP PLAN` возвращает `BLOCKED`, пока prerequisite не завершён;
- deterministic validator отклоняет Ready-plan, если в `OPEN_QUESTIONS.md` остаётся `OPEN` вопрос, явно влияющий на STEP/linked REQ/ADR.

`DEFERRED` допустим только когда вопрос доказанно не блокирует текущий executable scope.
