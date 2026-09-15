---
name: release-check
description: Run a project-specific production/release readiness gate and persist blockers/evidence in a release report.
---
# release-check

Используй для `RELEASE CHECK`. Определи фактическую release model из repo. Проверь unresolved critical/high findings, release-critical REQ/STEP, actual build/test/type/lint/package/deploy gates, migrations/upgrades/rollback, security and docs/release notes where applicable. Создай `planning/releases/` report. Verdict READY/BLOCKED. Не выдумывай gates, которых нет в проекте.
