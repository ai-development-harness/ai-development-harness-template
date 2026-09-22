---
name: implement-step
description: Implement a planned STEP within its scope, update tests, run verification, and record evidence without self-approving completion.
---
# implement-step

Используй для `STEP IMPLEMENT STEP-NNN`.

Execution Status ведёт global wrapper.

- Execution wrapper до dispatch детерминированно проверяет `step-implement-ready`: актуальный Ready plan, fingerprints/review, Accepted ADR/Open OQ и type-specific completion proofs direct dependencies. Если command уже запущена, этот gate пройден; не пересчитывай его reasoning-ом.
- До product mutation запусти обычную deterministic validation проекта/Harness согласно workflow; не дублируй проверку prerequisites вручную.
- Если execution-status показывает resume этой же команды, сначала изучи существующий diff/Evidence и продолжи недостающее; не переделывай готовое.
- При первой фактической product mutation canonical `status → in_progress`.
- Используй `implementer` или `mechanic` по сложности.
- Соблюдай mutation policy/out-of-scope и Accepted ADR.
- Добавь необходимые tests.
- Выполни реальные verification targets.
- Запиши Evidence: command, exit code и observed facts. Не реконструируй terminal output.
- Не ставь `status: completed` до independent schema-valid review PASS и type-specific completion proof.
- После полного scope + verification + Evidence command завершается result `SUCCESS`.

Single IMPLEMENT после SUCCESS останавливается. Только explicit chain или `STEP RUN` может продолжить к REVIEW.
