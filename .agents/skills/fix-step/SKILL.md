---
name: fix-step
description: Fix confirmed findings from the latest failing review of a STEP, then hand off to a fresh independent review.
---
# fix-step

Используй для `FIX STEP-NNN`.

Найди последний применимый FAIL review. Передай подтверждённые findings implementer. Исправляй только их и необходимый supporting code в scope. Новый architecture/product scope → corrective STEP, а не скрытое расширение. Запусти relevant verification, обнови Evidence с command/exit code/observed facts; не выдавай реконструированный terminal output за буквальный. Старый review не изменяй. Следующая команда всегда свежий `REVIEW STEP-NNN`.
