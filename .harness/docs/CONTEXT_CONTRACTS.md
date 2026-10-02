# Context Contracts / Progressive Disclosure

Context Contract определяет **минимальный task-local контекст** для semantic роли. Один contract используется и Codex, и Claude adapters; runtime может отличаться способом чтения файлов, но не semantic selection.

## Roles

- `planner`: STEP contract, linked REQ/ADR, dependency contract, relevant OQ, architecture refs и configured active principles.
- `implementer`: implementation-facing STEP sections, Acceptance/Verification, governing ADR и dependency evidence.
- `reviewer`: reviewed STEP contract + Implementation plan/Evidence, linked acceptance/decisions и review-relevant context.

Resolver возвращает не указание «прочитать весь файл», а projection:

```json
{
  "artifact": "REQ-007",
  "path": "docs/requirements/REQ-007-example.md",
  "sections": ["Requirement", "Acceptance"]
}
```

Architecture refs используют exact anchor.

## Запуск

```bash
python3 .harness/tools/context-contract.py STEP-024 --role planner --json
python3 .harness/tools/context-contract.py STEP-024 --role implementer --json
python3 .harness/tools/context-contract.py STEP-024 --role reviewer --json
```

Обычный `step-context.py` уже включает соответствующий contract в поле `contextContract`.

## Expansion

Дополнительный context разрешён только с явной причиной:

```bash
python3 .harness/tools/context-contract.py \
  --expand src/integrations/provider.ts \
  --reason 'integration boundary discovered' --json
```

Expansion fail-closed:

- пустая reason запрещена;
- path обязан оставаться внутри repository;
- файл обязан существовать;
- `.harness/tools/**` не входит в normal semantic context.

## Метрики

Contract публикует `artifactCount`, `sectionCount` и `fullRepositoryPreload=false`. Это стабильные tokenizer-neutral regressions; brittle лимит «ровно N токенов» не используется.

Tool source, unrelated docs/REQ/ADR и весь repository не загружаются «на всякий случай». Если resolver не может доказать canonical link или required section, он возвращает BLOCKED вместо silent fallback.
