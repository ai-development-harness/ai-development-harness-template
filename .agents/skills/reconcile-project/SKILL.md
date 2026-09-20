---
name: reconcile-project
description: Detect code/documentation/architecture/status drift across the whole repository and create corrective work without silently changing production code.
---
# reconcile-project

Используй для `PROJECT RECONCILE` только после успешного `PROJECT INIT`.

Precondition: `.project/manifest.yaml → project.initialized: true`.

Если `project.initialized: false`, команда неприменима: ничего не меняй, не создавай audit report/REQ/ADR/STEP и не пытайся reconcile-ить template placeholders. Верни `PROJECT RECONCILE: NOT_APPLICABLE` и handoff → `PROJECT INIT`.

Для инициализированного проекта сравни code/config/migrations/tests с REQ, Accepted ADR, architecture docs, tasks, evidence и projections. Найди undocumented behavior, stale docs/status, architecture drift и requirement gaps.

До итогового вывода обязательно запусти deterministic проверку актуальности ссылок на Harness commands:

```bash
python3 tools/harness/check-command-references.py --json
```

Она берёт основные project paths и `taskDirectory` из `.project/manifest.yaml`, дополнительно проверяет `README.md` и live project Markdown под `docs/**`, и намеренно не сканирует immutable/history-oriented reports и ADR history. Каждый finding вида `legacy → canonical` включи в reconcile report как command-syntax drift, если это не явно намеренная историческая цитата. Нельзя писать «drift не обнаружен», пока эта проверка не выполнена или её BLOCKED-состояние не раскрыто в Evidence.

Production code не исправляй. Однозначные projections и чисто документальный command-syntax drift можно синхронизировать.

Если проект создан старой версией Harness и canonical definitions всё ещё находятся внутри монолитного `docs/requirements/SPEC.md`, выполни lossless document-model migration: для каждого существующего REQ создай отдельный `docs/requirements/REQ-NNN-<slug>.md` с теми же ID, metadata, Requirement, Rationale, Acceptance и Traceability; затем перестрой `SPEC.md` как index и сохрани `STATUS.md` как lifecycle projection. Не переписывай смысл требований и не меняй их lifecycle-state. Если структура legacy SPEC неоднозначна и lossless split нельзя доказать, зафиксируй blocker вместо угадывания.

Substantive gaps → corrective STEP. Сохрани audit report.
