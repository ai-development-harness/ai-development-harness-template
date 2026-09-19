---
name: implement-step
description: Implement a planned STEP within its scope, update tests, run verification, and record evidence without self-approving completion.
---
# implement-step

Используй для `STEP IMPLEMENT STEP-NNN`.

- Сначала выполни deterministic recovery preflight:
  ```bash
  python3 tools/harness/resolve-next-command.py --json STEP-NNN
  ```
  Если resolver требует повторный PLAN или другой phase, не обходи его.
- Перед implementation отметь crash-safe phase:
  ```bash
  python3 tools/harness/execution-state.py begin STEP-NNN \
    --command 'STEP IMPLEMENT STEP-NNN'
  ```
- Прочитай актуальный Implementation plan и проверь, что `Plan basis` соответствует текущему task contract.
- Проверь dependencies.
- При первой mutation Status → `В работе`.
- Используй `implementer` или `mechanic` по сложности.
- Соблюдай mutation policy/out-of-scope и Accepted ADR.
- Добавь необходимые tests.
- Выполни реальные verification targets.
- Запиши Evidence: command, exit code и observed facts. Не реконструируй terminal output; буквальный output допустим только если реально захвачен.
- Не ставь `Выполнено` до independent review PASS.
- Только после полного scope + verification + Evidence отметь successful handoff:
  ```bash
  python3 tools/harness/execution-state.py complete STEP-NNN \
    --command 'STEP IMPLEMENT STEP-NNN' \
    --result SUCCESS
  ```
- Если session оборвалась до completion-checkpoint, следующий запуск обязан повторить `STEP IMPLEMENT STEP-NNN` в resume-semantics: сначала изучить существующий diff/evidence и продолжить недостающее, а не переделывать уже готовое.
- Handoff: `STEP REVIEW STEP-NNN`.
