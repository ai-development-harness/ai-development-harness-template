---
name: next-step
description: Select the next executable project action using dependencies, task state, priority, risk and critical path.
---
# next-step

Используй для `STEP NEXT`. Read-only.

Первым шагом выполни:

```bash
python3 tools/harness/resolve-next-command.py --json
```

Если есть interrupted/active execution candidates, они имеют приоритет над стартом нового STEP. При одном кандидате верни его exact resolved command. При нескольких сначала выбирай среди recovery candidates по обычным dependency/priority/risk правилам и только потом рассматривай новый STEP.

Не выбирай просто наименьший номер. Исключи blocked hard dependencies и completed/cancelled work. Учитывай corrective prerequisites и фактическое состояние task: если implementation уже есть и review отсутствует, следующая команда может быть REVIEW, а не PLAN. Верни один основной выбор и точную команду.
