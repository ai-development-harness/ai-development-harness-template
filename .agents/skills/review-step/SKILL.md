---
name: review-step
description: Run an independent read-only review of a STEP implementation, optionally compose security/test reviewers, and persist an immutable report.
---
# review-step

Используй для `REVIEW STEP-NNN`.

Обязателен независимый `reviewer`. Сверь task/REQ/ADR/plan с фактической реализацией и tests. По risk/factual diff условно запусти `security_reviewer` и/или `test_reviewer`, желательно параллельно только для read-only анализа. Синтезируй дубликаты. Создай новый immutable report в `planning/reviews/STEP-NNN/`. Verdict PASS/FAIL/BLOCKED. PASS закрывает STEP только при успешных deterministic gates; FAIL ведёт в FIX; BLOCKED фиксирует blocker. Product code не исправляй.
