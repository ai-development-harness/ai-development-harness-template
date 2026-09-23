---
name: implement-step
description: Implement a planned STEP within its scope, update tests, run verification, and record evidence without self-approving completion.
---
# implement-step

Используй для `STEP IMPLEMENT STEP-NNN`.

Execution Status ведёт global wrapper.

- В начале вызови `python3 .harness/tools/step-context.py STEP-NNN --phase implement --json`. Execution wrapper уже проверил `step-implement-ready`; manifest должен подтвердить `implementPrerequisites.status=PASS` и даст exact `readPaths`. Прочитай эти artifacts, не обходи project docs вручную.
- До product mutation запусти обычную deterministic validation проекта/Harness согласно workflow; не дублируй prerequisite reasoning.
- Если execution-status показывает resume этой же команды, сначала изучи существующий diff/Evidence и продолжи недостающее; не переделывай готовое.
- При первой фактической product mutation canonical `status → in_progress`.
- Используй `implementer` или `mechanic` по сложности.
- Соблюдай mutation policy/out-of-scope и Accepted ADR.
- Добавь необходимые tests.
- Verification commands вручную не запускай только ради completion: при result `SUCCESS` dispatcher сам запускает canonical Verification и пишет generated Evidence.
- `VERIFICATION_FAIL` возвращает factual command failure — исправь его и повтори completion. `VERIFICATION_MANUAL_REQUIRED` означает выполнить только перечисленные manual checks и передать exact `manualVerification` observations через dispatcher details.
- `VERIFICATION_BLOCKED` не обходи reasoning-ом: invalid/mutating verification требует исправления contract/workflow.
- Не ставь `status: completed` до independent schema-valid review PASS и type-specific completion proof.
- После полного scope предложи result `SUCCESS`; фактический verification gate принадлежит dispatcher.

Single IMPLEMENT после SUCCESS останавливается. Только explicit chain или `STEP RUN` может продолжить к REVIEW.
