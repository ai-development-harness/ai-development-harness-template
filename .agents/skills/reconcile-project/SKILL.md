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

Она проверяет только live project-owned documents (README/live project docs under docs/**/PLAN/STATUS/current STEP contracts) и намеренно не сканирует immutable/history-oriented reports и ADR history. Каждый finding вида `legacy → canonical` включи в reconcile report как command-syntax drift, если это не явно намеренная историческая цитата. Нельзя писать «drift не обнаружен», пока эта проверка не выполнена или её BLOCKED-состояние не раскрыто в Evidence.

Production code не исправляй. Однозначные projections и чисто документальный command-syntax drift можно синхронизировать; substantive gaps → corrective STEP. Сохрани audit report.
