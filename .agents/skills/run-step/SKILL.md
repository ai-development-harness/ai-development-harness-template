---
name: run-step
description: Orchestrate one STEP through its existing type-specific flow with restart-safe command execution.
---
# run-step

Используй для `STEP RUN STEP-NNN`.

Global command wrapper уже зарегистрировал root execution:

```text
mode = orchestration
rootCommand = STEP RUN STEP-NNN
```

1. Resolve STEP, blockers и Type.
2. Прочитай `.harness/manifest.yaml`: `execution.maxFixReviewCycles`, `review.security`, `review.tests` должны быть валидны, если применимы.
3. Dispatch по существующему Type: coding flow, ADR, RESEARCH, AUDIT, REVIEW, DOCUMENTATION или RELEASE. Execution profiles не существуют.
4. Перед продолжением root execution вызови:
   ```bash
   python3 .harness/tools/resolve-next-command.py --json \
     --root 'STEP RUN STEP-NNN'
   ```
5. Если resolver возвращает interrupted child command — resume её.
6. Если RUN запускает canonical child command, отметь её:
   ```bash
   python3 .harness/tools/execution-state.py begin \
     --root 'STEP RUN STEP-NNN' \
     --command '<child command>'
   ```
7. После child completion global wrapper записывает result и RUN снова вызывает resolver.
8. Для PLAN → IMPLEMENT → REVIEW → FIX переходы определяет CTS.
9. Если Type выполняется внутри RUN без отдельной canonical child command, current остаётся `STEP RUN STEP-NNN`; после interruption resume-ится сам RUN.
10. После REVIEW PASS без следующего CTS edge resolver возвращает root RUN для remaining close/sync/finalization.
11. BLOCKED останавливает root execution.
12. Не запускай параллельные write-agents над одним scope.

Повторный явный `STEP RUN STEP-NNN` при уже running root resume-ит существующий execution, а не создаёт второй.
