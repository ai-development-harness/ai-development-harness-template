# Open Questions

> Tracked projection/index. Canonical вопросы хранятся отдельными versioned файлами в каталоге из `sources.openQuestions`. Этот файл не является источником истины и пересобирается детерминированно.

| OQ | Статус | Вопрос | Affects |
|---|---|---|---|

## Blocking semantics

`status: open` блокирует STEP, если `affects` содержит сам STEP, его linked REQ/ADR либо `PROJECT` в контексте INIT. `deferred` допустим только когда вопрос доказанно не блокирует текущий executable scope.
