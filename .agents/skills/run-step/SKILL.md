---
name: run-step
description: Orchestrate PLAN → IMPLEMENT → verification → independent REVIEW → bounded FIX/REVIEW cycles for one STEP.
---
# run-step

Используй для `STEP RUN STEP-NNN`.

1. Resolve STEP, blockers и Type.
2. Прочитай `.project/manifest.yaml`: `execution.maxFixReviewCycles` должен быть целым 1–5, а `review.security` и `review.tests` — только `auto` или `always`. При отсутствующей/недопустимой настройке остановись с configuration blocker и не подставляй скрытый default.
3. Dispatch: IMPLEMENTATION/BUGFIX/REFACTOR/HARDENING → restart-safe coding flow; ADR → architect/decision flow; RESEARCH → research deliverables; AUDIT → audit-only; REVIEW → review-only; DOCUMENTATION/RELEASE → task-specific mutations/gates.

### Restart-safe coding flow

Перед первой интерпретацией phase зарегистрируй root orchestration command:

```bash
python3 tools/harness/execution-state.py start STEP-NNN \
  --root-command 'STEP RUN STEP-NNN'
```

Затем **всегда** спрашивай deterministic resolver:

```bash
python3 tools/harness/resolve-next-command.py --json STEP-NNN
```

Resolver имеет приоритет над устным предположением агента о текущей стадии.

4. Если resolver вернул `STEP PLAN STEP-NNN` — выполни PLAN skill. После его completion снова вызови resolver.
5. Если resolver вернул `STEP IMPLEMENT STEP-NNN` — выполни IMPLEMENT skill в resume-semantics. После completion снова вызови resolver.
6. Если resolver вернул `STEP REVIEW STEP-NNN` — выполни fresh independent REVIEW. После сохранения report/checkpoint снова вызови resolver.
7. Если resolver вернул `STEP FIX STEP-NNN` — выполни FIX только по latest FAIL findings. После completion снова вызови resolver.
8. Если resolver вернул `STEP RUN STEP-NNN` с `reasonCode=FINALIZE_AFTER_PASS`, **не запускай PLAN/IMPLEMENT/REVIEW заново**: выполни только оставшиеся deterministic gates и close/sync evidence/docs/status.
9. Если resolver вернул `DONE`, вызови:
   ```bash
   python3 tools/harness/execution-state.py finish STEP-NNN --status completed
   ```
   и заверши RUN.
10. Если resolver вернул `BLOCKED`, зафиксируй blocker, при необходимости:
   ```bash
   python3 tools/harness/execution-state.py finish STEP-NNN --status blocked
   ```
   и не объявляй success.
11. После каждой завершённой phase решение о следующем переходе снова принимает resolver/CTS, а не заранее сохранённый reasoning текущей session.

### Recovery guarantees

- `PLAN` после обрыва считается завершённым только если `Plan status: Ready` и `Plan basis` совпадает с hash текущего task contract.
- `IMPLEMENT` и `FIX` без successful local completion-checkpoint считаются незавершёнными; их нужно **resume**, сначала изучив уже существующий diff/evidence.
- `REVIEW` может считаться завершённым без local checkpoint, если после начала phase появился новый immutable review report; resolver использует его verdict.
- удаление `.project/local/execution/` не делает проект некорректным: resolver опирается на durable artifacts и при недостатке доказательств консервативно повторяет незавершённую phase.
- лимит FIX/REVIEW восстанавливается из durable FAIL review reports и `execution.maxFixReviewCycles`, а не только из local cursor.

Не запускай параллельные write-agents над одним scope.
