# Harness Integrity CI

`Harness Integrity` — baseline CI, который существует ещё до выбора технологического стека проекта.

Workflow: `.github/workflows/harness-integrity.yml`.

Он запускает:

```bash
python3 tools/harness/validate.py --mode ci
```

Проверяются только invariants Harness/repository hygiene. Этот workflow **не должен** пытаться угадать project-specific `test`, `lint`, `typecheck`, `build` или deploy commands.

После `INIT PROJECT` проект добавляет отдельные CI workflows, когда реальные команды известны из repository tooling. Они могут быть связаны с STEP Verification/Release Check, но Harness Integrity остаётся независимым structural gate.

## Локальный запуск

```bash
python3 tools/harness/validate.py --mode manual
```

Для COMMIT/PUSH agent использует:

```bash
python3 tools/harness/validate.py --mode commit
```

## Настройка

`.project/harness-policy.toml` определяет required files/skills/agents/commands, forbidden tracked globs, managed formatting paths, максимальный размер tracked file и список self-documented YAML/TOML configs. Для этих configs validator требует комментарий и пример непосредственно рядом с каждым параметром. Ослабляй правило только осознанно; если project действительно должен хранить необычный артефакт, добавь узкое исключение вместо отключения всего класса checks.
