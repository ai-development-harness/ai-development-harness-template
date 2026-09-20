---
name: reconcile-project
description: Detect code/documentation/architecture/status drift across the whole repository and create corrective work without silently changing production code.
---
# reconcile-project

Используй для `PROJECT RECONCILE` только после успешного `PROJECT INIT`.

Precondition: `.harness/manifest.yaml → project.initialized: true`.

Если `project.initialized: false`, команда неприменима: ничего не меняй, не создавай audit report/REQ/ADR/STEP и не пытайся reconcile-ить template placeholders. Верни `PROJECT RECONCILE: NOT_APPLICABLE` и handoff → `PROJECT INIT`.

Для инициализированного проекта сравни code/config/migrations/tests с REQ, Accepted ADR, architecture docs, tasks, evidence и projections. Найди undocumented behavior, stale docs/status, architecture drift и requirement gaps.

До итогового вывода обязательно запусти deterministic проверку актуальности ссылок на Harness commands:

```bash
python3 .harness/tools/check-command-references.py --json
```

Она берёт основные project paths и `taskDirectory` из `.harness/manifest.yaml`, дополнительно проверяет `README.md` и live project Markdown под `docs/**`, и намеренно не сканирует immutable/history-oriented reports и ADR history. Каждый finding вида `legacy → canonical` включи в reconcile report как command-syntax drift, если это не явно намеренная историческая цитата. Нельзя писать «drift не обнаружен», пока эта проверка не выполнена или её BLOCKED-состояние не раскрыто в Evidence.

Production code не исправляй. Однозначные projections и чисто документальный command-syntax drift можно синхронизировать.

Если проект создан старой версией Harness и canonical definitions всё ещё находятся внутри монолитного `docs/requirements/SPEC.md`, выполни lossless document-model migration. Каждый существующий REQ создай как отдельный `docs/requirements/REQ-NNN-<slug>.md` **по текущему `docs/requirements/TEMPLATE.md`**: используй актуальную структуру standalone-документа и уровни заголовков, но заполняй её только данными legacy REQ, сохраняя ID, название, metadata, Requirement, Rationale, Acceptance и Traceability без изменения смысла; template placeholders не копируй. Затем перестрой `SPEC.md` и `STATUS.md` в их **текущем projection-формате**, сохранив lifecycle-state, STEP coverage и Evidence. Lifecycle-state не переноси в canonical REQ или `SPEC.md`. Если legacy-содержимое невозможно lossless отобразить в текущий template/projections или структура legacy SPEC неоднозначна, зафиксируй blocker вместо угадывания.

Substantive gaps → corrective STEP. Сохрани audit report.
