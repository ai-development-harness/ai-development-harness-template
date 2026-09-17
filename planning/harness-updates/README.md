# Harness update reports

Этот каталог хранит durable evidence применения `UPDATE HARNESS` к конкретному проекту.

- `README.md` принадлежит Harness protocol layer.
- `UPDATE-<UTC timestamp>.md` принадлежит конкретному проекту и создаётся updater-ом после успешной mutation; report фиксирует initial release, requested final target, фактически пройденный route/hops и возможную `reloadRequired` boundary.
- Reports не являются STEP и не меняют product roadmap/status.
- `CHECK HARNESS UPDATE` ничего сюда не пишет.
- Report не означает commit/push/PR: после него требуется обычный `GIT CHECK` → `COMMIT`.

При конфликте report не создаётся, потому что updater обязан остановиться до mutation.
