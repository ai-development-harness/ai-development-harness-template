# Harness Integrity CI

`Harness Integrity` — baseline CI, который существует ещё до выбора технологического стека проекта.

Workflow: `.github/workflows/harness-integrity.yml`.

Validator написан на Python и использует только standard library. Минимальная версия — Python 3.11+, потому что структурная проверка TOML опирается на `tomllib`. Это осознанная небольшая tooling dependency Harness, а не зависимость будущего продукта.

Bash не используется как реализация validator: текущие проверки требуют корректного TOML parsing, работы с Git index, glob/path semantics, UTF-8/binary content и структурой skills/configs. Перенос в shell либо ослабил бы эти проверки, либо добавил внешние parser dependencies. Docker также не является обязательным runtime, чтобы локальная validation не зависела от daemon/image/network.

В GitHub Actions версия Python задаётся явно через `actions/setup-python`, поэтому CI не зависит от случайной версии интерпретатора в `ubuntu-latest`.

Workflow запускает baseline validator и dependency-free smoke/self-tests protocol tooling:

```bash
python3 .harness/tools/validate.py --mode ci
python3 .harness/tools/check-command-references.py --json
python3 .harness/tools/command-references-self-test.py
python3 .harness/tools/validate-command.py --json -- 'GIT CHECK > COMMIT > PUSH > PR'
python3 .harness/tools/execution-self-test.py
python3 .harness/tools/planning-contract-self-test.py
python3 .harness/tools/update-migration-self-test.py
```

Для command transition gate workflow дополнительно проверяет отрицательный case (`GIT PR > COMMIT` обязан завершиться non-zero).

Update migration self-test создаёт synthetic legacy state и проверяет deterministic update-contract: legacy route/reload boundaries, target relocation layout, ownership project templates и marker blocks, tracked-vs-ignored Git scope, deferred REQ migration и согласованность release metadata. Он не запускает LLM/agent и не заменяет периодический real-project dogfood.

Baseline validator детерминированно проверяет schema-v1 planning contracts: configured task/REQ/ADR/OQ paths, strict refs/enums, dependency cycles, type-specific completion proofs, mutation-policy grammar, explicit architecture refs, Ready `context_basis` + отдельный `content_hash` и наличие matching immutable planning-review PASS. Stale context может быть warning на глобальной проверке, но resolver всё равно запрещает конкретный IMPLEMENT до fresh PLAN. `context_basis` fingerprint-ит STEP contract, linked REQ/ADR, direct dependency completion proofs, referenced architecture sections и relevant OQ; `content_hash` отдельно fingerprint-ит Implementation plan. Семантическую непротиворечивость static gate не угадывает — её доказывает обязательный independent planning-review.

Baseline validator также детерминированно проверяет requirements document model: уникальность `REQ-NNN`, соответствие filename/H1 и обязательных standalone-секций, одинаковый набор REQ в `SPEC.md`/`STATUS.md`, прямые ссылки projections на canonical `REQ-NNN-*.md` и совпадение названий. Смысл requirement validator не интерпретирует.

Проверяются только invariants Harness/repository hygiene. Этот workflow **не должен** пытаться угадать project-specific `test`, `lint`, `typecheck`, `build` или deploy commands.

После `PROJECT INIT` проект добавляет отдельные CI workflows, когда реальные команды известны из repository tooling. Они могут быть связаны с STEP Verification/Release Check, но Harness Integrity остаётся независимым structural gate.

## Локальный запуск

Требуются Git и Python 3.11+:

```bash
python3 .harness/tools/validate.py --mode manual
```

`manual` остаётся строгим для обычного состояния, но может разрешить явно распознанное active project schema migration-pending состояние после Harness update как warning. Это нужно только для завершения control-plane hop; `commit` и `ci` такое состояние не принимают. Перед commit необходимо выполнить `PROJECT RECONCILE`.

Для GIT COMMIT / GIT PUSH agent использует:

```bash
python3 .harness/tools/validate.py --mode commit
```

Если Python 3.11+ отсутствует, validator должен считаться недоступным gate, а не молча заменяться частичной shell-проверкой. То же относится к отсутствующему Git binary/repository metadata: проверки tracked state требуют реального Git index, поэтому validator возвращает `HARNESS VALIDATION: BLOCKED` (exit code 2), а не подменяет tracked files содержимым filesystem.

## Настройка

`.harness/harness-policy.toml` определяет required files/skills/agents/commands, forbidden tracked globs, managed formatting paths, максимальный размер tracked file и список self-documented YAML/TOML configs. Для этих configs validator требует комментарий и либо пример, либо описание формата непосредственно рядом с каждым параметром. Ослабляй правило только осознанно; если project действительно должен хранить необычный артефакт, добавь узкое исключение вместо отключения всего класса checks.
