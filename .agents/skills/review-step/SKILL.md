---
name: review-step
description: Run an independent read-only review of a STEP implementation, optionally compose security/test reviewers, and persist an immutable report.
---
# review-step

Используй для `STEP REVIEW STEP-NNN`.

Execution Status ведёт global wrapper и при старте REVIEW запоминает previous immutable review report.

Обязателен независимый `reviewer`. Сверь task/REQ/ADR/Implementation plan с фактической реализацией и tests. Перед verdict выполни полный проход по текущему revision и собери все material findings, которые можно доказать сейчас; не останавливай review после первого FAIL.

Для каждого finding укажи категорию:

- `implementation` — код/тест/evidence не соответствует непротиворечивому contract;
- `contract` — STEP/REQ/ADR/Acceptance/dependency сами противоречивы, неполны или требуют отсутствующего решения;
- `evidence` — реализация может быть корректной, но verification/evidence недостаточны для доказательства acceptance.

Прочитай `.harness/manifest.yaml → review.security` и `review.tests`: `auto` запускает specialized reviewer по risk/factual diff/test surface, `always` — для каждого review-прохода. Другие/отсутствующие значения — configuration blocker.

Routing verdict:

- `PASS` — material findings нет, acceptance доказан;
- `FAIL` — есть подтверждённые implementation/evidence findings, исправимые в scope текущего STEP;
- `BLOCKED` — найден semantic contract conflict, impossible acceptance, missing durable decision/prerequisite, stale planning context или другой дефект, который `STEP FIX` не имеет права чинить скрытым расширением scope.

При `BLOCKED` укажи, какой contract/prerequisite нужно скорректировать и нужен ли corrective STEP/RESEARCH/ADR. Не отправляй такую проблему в бесконечный `FAIL → FIX`.

Создай новый immutable report в `planning/reviews/STEP-NNN/` (либо manifest-configured reviewDirectory). Global wrapper записывает тот же verdict как command result.

Если session оборвалась после создания нового immutable report, но до записи `complete`, resolver может восстановить verdict и не повторять expensive review.

Product code не исправляй.
