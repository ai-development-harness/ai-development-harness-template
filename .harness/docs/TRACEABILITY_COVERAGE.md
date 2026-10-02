# Traceability Coverage

`traceability-coverage.py` строит read-only deterministic graph:

```text
REQ → STEP → completion/evidence proof
```

Он не использует LLM для explicit links и не подменяет semantic review.

## Запуск

```bash
python3 .harness/tools/traceability-coverage.py --json
```

JSON schema v1 содержит:

- aggregate `metrics`;
- состояние каждого REQ;
- `orphanSteps`;
- `invalidReferences`;
- open blocking OQ.

REQ states:

- `uncovered` — нет executable/active STEP;
- `covered` — STEP есть, но completion evidence ещё не доказан полностью;
- `verified` — все executable linked STEP имеют current completion proof;
- `stale_evidence` — STEP помечен completed, но current proof больше не подтверждает completion;
- `blocked` — на REQ/STEP/PROJECT влияет OPEN OQ.

Orphan detection не считает maintenance-only `research/adr/audit/review/documentation/release` STEP ошибкой только из-за отсутствия REQ. Для coding-oriented STEP нужен REQ или ADR rationale.

`releaseRelevant=true` выставляется для high/critical REQ и позволяет RELEASE CHECK фильтровать release-critical gaps без повторного repository scan.
