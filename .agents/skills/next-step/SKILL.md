---
name: next-step
description: Select the next executable project action using dependencies, task state, priority, risk and critical path.
---
# next-step

Используй для `NEXT STEP`. Read-only. Не выбирай просто наименьший номер. Исключи blocked hard dependencies и completed/cancelled work. Учитывай corrective prerequisites и фактическое состояние task: если implementation уже есть и review отсутствует, следующая команда может быть REVIEW, а не PLAN. Верни один основной выбор и точную команду.
