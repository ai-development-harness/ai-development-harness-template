---
name: fix-step
description: Fix confirmed findings from the latest failing review of a STEP, then hand off to a fresh independent review.
---
# fix-step

Используй для `STEP FIX STEP-NNN`.

Execution Status ведёт global wrapper.

Найди последний применимый FAIL review. Передай подтверждённые findings implementer. Исправляй только их и необходимый supporting code в scope. Новый architecture/product scope → corrective STEP, а не скрытое расширение.

Если command resume-ится после interruption, сначала изучи существующий diff и продолжи незавершённые findings.

Запусти relevant verification, обнови Evidence с command/exit code/observed facts; не выдавай реконструированный terminal output за буквальный.

После полного исправления command завершается result `SUCCESS`. Старый review не изменяй.

Single FIX после SUCCESS останавливается. Только explicit chain или `STEP RUN` может продолжить к свежему REVIEW.
