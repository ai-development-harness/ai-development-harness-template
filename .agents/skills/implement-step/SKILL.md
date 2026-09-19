---
name: implement-step
description: Implement a planned STEP within its scope, update tests, run verification, and record evidence without self-approving completion.
---
# implement-step

Используй для `STEP IMPLEMENT STEP-NNN`.

Execution Status ведёт global wrapper.

- Прочитай актуальный Implementation plan и проверь `Plan basis`, если PLAN обязателен.
- Проверь dependencies.
- Если execution-status показывает resume этой же команды, сначала изучи существующий diff/Evidence и продолжи недостающее; не переделывай готовое.
- При первой mutation Status → `В работе`.
- Используй `implementer` или `mechanic` по сложности.
- Соблюдай mutation policy/out-of-scope и Accepted ADR.
- Добавь необходимые tests.
- Выполни реальные verification targets.
- Запиши Evidence: command, exit code и observed facts. Не реконструируй terminal output.
- Не ставь `Выполнено` до independent review PASS.
- После полного scope + verification + Evidence command завершается result `SUCCESS`.

Single IMPLEMENT после SUCCESS останавливается. Только explicit chain или `STEP RUN` может продолжить к REVIEW.
