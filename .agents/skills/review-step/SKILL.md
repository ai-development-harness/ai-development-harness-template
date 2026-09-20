---
name: review-step
description: Run an independent read-only review of a STEP implementation, optionally compose security/test reviewers, and persist an immutable report.
---
# review-step

Используй для `STEP REVIEW STEP-NNN`.

Execution Status ведёт global wrapper и при старте REVIEW запоминает previous immutable review report.

Обязателен независимый `reviewer`. Сверь task/REQ/ADR/plan с фактической реализацией и tests. Прочитай `.harness/manifest.yaml → review.security` и `review.tests`: `auto` запускает specialized reviewer по risk/factual diff/test surface, `always` — для каждого review-прохода. Другие/отсутствующие значения — configuration blocker.

Создай новый immutable report в `planning/reviews/STEP-NNN/`. Verdict: `PASS`, `FAIL` или `BLOCKED`. Global wrapper записывает тот же verdict как command result.

Если session оборвалась после создания нового immutable report, но до записи `complete`, resolver может восстановить verdict и не повторять expensive review.

Product code не исправляй.
