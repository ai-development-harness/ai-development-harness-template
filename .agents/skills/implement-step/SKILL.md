---
name: implement-step
description: Implement a planned STEP within its scope, update tests, run verification, and record evidence without self-approving completion.
---
# implement-step

Используй для `IMPLEMENT STEP-NNN`.

- Прочитай актуальный Implementation plan.
- Проверь dependencies.
- При первой mutation Status → `В работе`.
- Используй `implementer` или `mechanic` по сложности.
- Соблюдай mutation policy/out-of-scope и Accepted ADR.
- Добавь необходимые tests.
- Выполни реальные verification targets.
- Запиши Evidence.
- Не ставь `Выполнено` до independent review PASS.
- Handoff: `REVIEW STEP-NNN`.
