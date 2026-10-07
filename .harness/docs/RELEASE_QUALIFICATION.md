# Release Qualification

Release Qualification — отдельный release-level contract поверх обычного Harness Integrity.

## Зачем нужен отдельный gate

`Harness Integrity` отвечает на вопрос:

> внутренне ли валиден конкретный commit Harness?

Он проверяет repository/protocol invariants и regression suite, но сам по себе не доказывает, что commit безопасно публиковать как новый release для существующих downstream-проектов.

`Harness Release Qualification` отвечает на другой вопрос:

> безопасно ли распространять **этот exact candidate SHA** как release?

Release evidence всегда относится к конкретному commit. Новый commit делает прежнее qualification evidence stale.

## Canonical entrypoint

Единый deterministic executable:

~~~bash
python3 .harness/tools/release-qualification.py \
  --lane current \
  --expect-sha '<exact-candidate-sha>' \
  --expected-python 3.13 \
  --json
~~~

Доступные lanes:

| Lane | Назначение |
|---|---|
| `current` | основной supported Linux/Python runtime: validator + полный discoverable synthetic suite |
| `minimum` | та же deterministic surface строго на Python 3.11 |
| `windows` | validator + targeted Windows-specific process/locking/update boundaries |

Один и тот же entrypoint используется external release orchestrator-ом во всех lanes. Workflow не должен вручную копировать список core qualification commands.

## Exact revision

`--expect-sha` обязателен. Entry point сравнивает его с реальным `git rev-parse HEAD`.

Несовпадение — `BLOCKED`, а не warning. Поэтому результат нельзя случайно переиспользовать для другого release commit.

Опциональный `--expected-python X.Y` позволяет release workflow доказать, что lane исполняется на ожидаемом runtime.

## Checkout isolation

До запуска gates checkout обязан быть clean.

После выполнения gates entrypoint повторно проверяет `git status --porcelain`. Любая tracked или untracked mutation делает qualification `FAIL`, даже если отдельные validators/tests вернули zero.

Это не заменяет disposable checkout canary flow; это дополнительный fail-closed guard самого core entrypoint.

## Machine result

`--json` возвращает schema v1:

~~~json
{
  "schemaVersion": 1,
  "kind": "harness_release_qualification",
  "status": "PASS",
  "lane": "current",
  "expectedRevision": "<sha>",
  "repositoryRevision": "<sha>",
  "python": "3.13.0",
  "platform": "linux",
  "gates": []
}
~~~

Для каждого gate сохраняются status, exit code, SHA-256 stdout/stderr и размер вывода. Полный stdout/stderr остаётся в job logs; compact result не копирует потенциально большой вывод.

Exit codes:

- `0` — PASS;
- `1` — один или несколько qualification gates FAIL;
- `2` — qualification BLOCKED до запуска gates: wrong SHA/runtime/platform, dirty checkout или недоступный Git state.

## Что входит в #260

Этот contract задаёт core deterministic lanes. Release-level orchestration расширяется отдельными слоями:

- initialized downstream upgrade/canary — core #261, canonical runner [`release-upgrade-qualification.py`](../tools/release-upgrade-qualification.py);
- bounded concurrency/process stress — core #262;
- reusable multi-lane workflow и private canary checkout — `maintainer-tools#7`;
- exact-SHA publish hard gate — `maintainer-tools#8`.

Ни один из этих внешних layers не должен объявляться пройденным только потому, что `current` lane дала PASS.

## Локальная проверка

Для текущего checkout:

~~~bash
SHA="$(git rev-parse HEAD)"
python3 .harness/tools/release-qualification.py \
  --lane current \
  --expect-sha "$SHA" \
  --json
~~~

Команда предназначена для clean checkout. Для обычной разработки продолжай использовать Harness Integrity / `validate.py`; Release Qualification не заменяет pre-commit validation.


## Initialized downstream lane

После platform/runtime core lanes release orchestrator обязан отдельно выполнить initialized downstream upgrade через `release-upgrade-qualification.py`.

Runner принимает local authenticated baseline/candidate checkouts, создаёт disposable project clone и ephemeral source mirror, применяет exact release-prepared candidate штатным updater-ом, разрешает reload/schema migration, запускает STATUS/DOCTOR/validator/self-tests, проверяет project-owned preservation и требует repeated APPLY = `NO_UPDATE`.

Подробный contract: [`INITIALIZED_UPGRADE_QUALIFICATION.md`](INITIALIZED_UPGRADE_QUALIFICATION.md).
