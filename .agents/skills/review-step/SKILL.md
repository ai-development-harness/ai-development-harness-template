---
name: review-step
description: Run an independent read-only review of a STEP implementation, optionally compose security/test reviewers, and persist an immutable report.
---
# review-step

Используй для `STEP REVIEW STEP-NNN`.

Обязателен независимый `reviewer`. Сверь task/REQ/ADR/plan с фактической реализацией и tests. Прочитай `.project/manifest.yaml → review.security` и `review.tests`: режим `auto` запускает соответствующего specialized reviewer по risk/factual diff/test surface, режим `always` запускает его для каждого review-прохода. Другие/отсутствующие значения — configuration blocker; скрытый default запрещён. Specialized reviewers по возможности запускай параллельно только для read-only анализа. Синтезируй дубликаты. Создай новый immutable report в `planning/reviews/STEP-NNN/`. Verdict PASS/FAIL/BLOCKED. PASS закрывает STEP только при успешных deterministic gates; FAIL ведёт в FIX; BLOCKED фиксирует blocker. Product code не исправляй.
