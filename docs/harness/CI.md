# Harness Integrity CI

`Harness Integrity` — baseline CI, который существует ещё до выбора технологического стека проекта.

Workflow: `.github/workflows/harness-integrity.yml`.

Validator написан на Python и использует только standard library. Минимальная версия — Python 3.11+, потому что структурная проверка TOML опирается на `tomllib`. Это осознанная небольшая tooling dependency Harness, а не зависимость будущего продукта.

Bash не используется как реализация validator: текущие проверки требуют корректного TOML parsing, работы с Git index, glob/path semantics, UTF-8/binary content и структурой skills/configs. Перенос в shell либо ослабил бы эти проверки, либо добавил внешние parser dependencies. Docker также не является обязательным runtime, чтобы локальная validation не зависела от daemon/image/network.

В GitHub Actions версия Python задаётся явно через `actions/setup-python`, поэтому CI не зависит от случайной версии интерпретатора в `ubuntu-latest`.

Workflow запускает:

```bash
python3 tools/harness/validate.py --mode ci
```

Проверяются только invariants Harness/repository hygiene. Этот workflow **не должен** пытаться угадать project-specific `test`, `lint`, `typecheck`, `build` или deploy commands.

После `PROJECT INIT` проект добавляет отдельные CI workflows, когда реальные команды известны из repository tooling. Они могут быть связаны с STEP Verification/Release Check, но Harness Integrity остаётся независимым structural gate.

## Локальный запуск

Требуются Git и Python 3.11+:

```bash
python3 tools/harness/validate.py --mode manual
```

Для GIT COMMIT / GIT PUSH agent использует:

```bash
python3 tools/harness/validate.py --mode commit
```

Если Python 3.11+ отсутствует, validator должен считаться недоступным gate, а не молча заменяться частичной shell-проверкой. То же относится к отсутствующему Git binary/repository metadata: проверки tracked state требуют реального Git index, поэтому validator возвращает `HARNESS VALIDATION: BLOCKED` (exit code 2), а не подменяет tracked files содержимым filesystem.

## Настройка

`.project/harness-policy.toml` определяет required files/skills/agents/commands, forbidden tracked globs, managed formatting paths, максимальный размер tracked file и список self-documented YAML/TOML configs. Для этих configs validator требует комментарий и пример непосредственно рядом с каждым параметром. Ослабляй правило только осознанно; если project действительно должен хранить необычный артефакт, добавь узкое исключение вместо отключения всего класса checks.
