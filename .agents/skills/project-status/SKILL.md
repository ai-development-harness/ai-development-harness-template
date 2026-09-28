---
name: project-status
description: Refresh deterministic projections from canonical project artifacts and report current work, blockers, recent completion and the highest-priority unblocked next work.
---
# project-status

Используй для `PROJECT STATUS`.

1. Все paths разрешай через `.harness/manifest.yaml`.
2. Canonical source — STEP/REQ/ADR/OQ, type-specific completion proofs и schema-valid review/evidence. Projection-файлы не интерпретируй как independent state.
3. Сначала пересобери projections:
   ```bash
   python3 .harness/tools/sync-projections.py
   ```
4. Затем выполни:
   ```bash
   python3 .harness/tools/validate.py --mode manual
   ```
5. Lifecycle-status REQ выводится только из canonical REQ + STEP completion proofs. Не меняй смысл REQ/ADR и не пиши product code.
6. В ответе раздели:
   - **In progress** — реально начатая незавершённая работа;
   - **Blocked** — blocker + required next action;
   - **Recently completed** — недавняя работа с completion proof;
   - **Next unblocked** — наиболее приоритетная доступная работа с учётом dependencies/OQ, но не выдавай рекомендацию за глобальный workflow lock.

Если projections/validator BLOCKED, покажи это как состояние проекта, а не скрывай за частичным summary.
