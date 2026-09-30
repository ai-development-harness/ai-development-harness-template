# Adaptive FIX ↔ REVIEW stopping

## Назначение

`execution.maxFixReviewCycles` остаётся абсолютным safety cap. Adaptive stopping добавляет более раннюю deterministic остановку, когда следующий FIX уже не имеет доказанного смысла или предыдущий repair ухудшил результат.

Порядок применения:

~~~text
REVIEW = FAIL
  ↓
hard cap exhausted? ── yes → FIX_REVIEW_LIMIT_REACHED
  │ no
  ↓
есть сравнимая repair telemetry? ── no → следующий FIX
  │ yes
  ↓
NO_PROGRESS / REPEATED_FINDINGS / REGRESSION → BLOCKED
  │ иначе
  ↓
следующий FIX
~~~

Hard cap проверяется первым, поэтому существующая семантика `FIX_REVIEW_LIMIT_REACHED` остаётся обратно совместимой.

## Источник данных

Adaptive decision не использует chat history и не просит модель оценить «есть ли прогресс». Сравниваются два immutable Review Contract v2 report:

- предыдущий report берётся из `current.context.reviewReportBefore`, зафиксированного при старте REVIEW;
- текущий report — новый canonical REVIEW artifact;
- findings сравниваются по stable `fingerprint` из Review Contract v2;
- repository delta берётся из `reviewed_revision`;
- semantic scope сравнивается через `contract_basis`.

Новые REVIEW reports получают `contract_basis = planning_context_basis(STEP)` и `verification_basis` — SHA-256 canonical Verification/Evidence snapshot. Historical v2 reports без этих полей остаются валидными; отсутствие `contract_basis` отключает adaptive classification fail-safe, а отсутствие verification basis даёт `verificationChanged=null`.

## Решения

### REPEATED_FINDINGS

Contract scope не менялся, repository revision изменилась, но множество material finding fingerprints осталось тем же. FIX что-то изменил в repository, но не устранил ни один зафиксированный дефект.

### NO_PROGRESS

Используется в двух консервативных случаях при неизменном contract scope:

- repository revision не изменилась и findings остались теми же;
- ни один finding не resolved, а highest material severity не снизилась.

### REGRESSION

Contract scope не менялся, после FIX появился новый finding и highest severity стала выше предыдущей. Новый finding сам по себе не считается regression.

### REPAIR_BLOCKED

`REPAIR_BLOCKED` зарезервирован для deterministic repair prerequisite/blocker и не подменяет verdict `BLOCKED` самого REVIEW. Текущая версия не генерирует этот code из эвристики findings: если данные сравнения недоступны или legacy, adaptive stop отключается, а hard cap остаётся активным.

## Scope-change guard

`contract_basis` включает STEP contract, связанные REQ/ADR, dependencies, architecture refs и relevant OQ. Если basis между REVIEW отличается, `scopeComparable=false` и comparator возвращает `continue` независимо от новых findings.

Это предотвращает ложную REGRESSION при легитимном изменении постановки во время repair lifecycle.

## Bounded telemetry

Execution state хранит только **последнюю** сводку `repairTelemetry`, а не историю циклов:

~~~json
{
  "cycle": 2,
  "findingsBefore": 4,
  "findingsAfter": 3,
  "resolved": 2,
  "persisted": 2,
  "introduced": 1,
  "highestSeverityBefore": "high",
  "highestSeverityAfter": "medium",
  "repositoryRevisionChanged": true,
  "contractBasisChanged": false,
  "scopeComparable": true,
  "verificationChanged": true,
  "stopDecision": "continue",
  "reasonCode": null
}
~~~

Fingerprint lists не копируются в execution state. Полный delta всегда восстанавливается из immutable reports. Размер telemetry дополнительно ограничен тем же bounded metadata gate, что и execution details.

`verificationChanged` вычисляется по `verification_basis`: SHA-256 canonical snapshot разделов `Verification` и `Evidence` на момент REVIEW. Harness не интерпретирует semantic prose `Verification observations` как proof; delta показывает только факт изменения deterministic verification/evidence snapshot.

## Restart semantics

Telemetry записывается при completion второго и последующих `REVIEW=FAIL`, после как минимум одного успешного `FIX → REVIEW` цикла. Resolver использует сохранённый `stopDecision`; после restart chat history не требуется.

Первый FAIL review (`fixReviewCycles=0`) никогда не создаёт adaptive stop.

## Граница ответственности

- CTS определяет допустимость REVIEW → FIX;
- Review Contract v2 определяет finding identity;
- `repair_cycle.py` вычисляет delta;
- `execution_status.py` хранит последнюю telemetry и применяет stop;
- `maxFixReviewCycles` остаётся hard upper bound.

Модель не может переопределить deterministic stop reason.
