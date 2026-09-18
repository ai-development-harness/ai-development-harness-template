---
name: reconcile-project
description: Detect code/documentation/architecture/status drift across the whole repository and create corrective work without silently changing production code.
---
# reconcile-project

Используй для `RECONCILE PROJECT` только после успешного `INIT PROJECT`.

Precondition: `.project/manifest.yaml → project.initialized: true`.

Если `project.initialized: false`, команда неприменима: ничего не меняй, не создавай audit report/REQ/ADR/STEP и не пытайся reconcile-ить template placeholders. Верни `RECONCILE PROJECT: NOT_APPLICABLE` и handoff → `INIT PROJECT`.

Для инициализированного проекта сравни code/config/migrations/tests с REQ, Accepted ADR, architecture docs, tasks, evidence и projections. Найди undocumented behavior, stale docs/status, architecture drift и requirement gaps. Production code не исправляй. Однозначные projections можно синхронизировать; substantive gaps → corrective STEP. Сохрани audit report.
