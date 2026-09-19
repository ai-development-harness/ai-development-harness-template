---
name: fix-step
description: Fix confirmed findings from the latest failing review of a STEP, then hand off to a fresh independent review.
---
# fix-step

Используй для `STEP FIX STEP-NNN`.

Сначала выполни deterministic resolver и перед mutation отметь phase:

```bash
python3 tools/harness/resolve-next-command.py --json STEP-NNN
python3 tools/harness/execution-state.py begin STEP-NNN \
  --command 'STEP FIX STEP-NNN'
```

Найди последний применимый FAIL review. Передай подтверждённые findings implementer. Исправляй только их и необходимый supporting code в scope. Новый architecture/product scope → corrective STEP, а не скрытое расширение. Запусти relevant verification, обнови Evidence с command/exit code/observed facts; не выдавай реконструированный terminal output за буквальный. Старый review не изменяй.

Только после полного исправления findings + verification + Evidence запиши:

```bash
python3 tools/harness/execution-state.py complete STEP-NNN \
  --command 'STEP FIX STEP-NNN' \
  --result SUCCESS
```

Если session оборвалась раньше, следующий запуск повторяет `STEP FIX STEP-NNN` в resume-semantics и продолжает существующий diff.

Следующая команда всегда свежий `STEP REVIEW STEP-NNN`.
