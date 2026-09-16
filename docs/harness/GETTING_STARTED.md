# Начало работы

## Требования к локальному окружению

- Git — Harness использует repository state, diff/index и Git workflow как часть deterministic gates.
- Python 3.11+ — нужен только для `tools/harness/validate.py`; product runtime от Python не зависит.

В CI версия Python задаётся явно. Переписывать validator на Bash только ради устранения Python dependency не рекомендуется: validator разбирает TOML стандартным `tomllib` и выполняет структурные проверки, которые shell-скрипт без дополнительного парсера воспроизводил бы менее надёжно.

## 1. Создай новый репозиторий

Предпочтительный путь — GitHub **Use this template**. После этого клонируй уже созданный репозиторий проекта.

Если template клонируется напрямую, перед первым `PUSH` замени `origin` на репозиторий нового проекта.

Template уже содержит `.project/harness.lock.json`: это BASE для будущих `CHECK HARNESS UPDATE` / `UPDATE HARNESS`. Не удаляй lock при инициализации проекта. Источником обновлений являются только immutable release tags, а не moving `main`.

## 2. Создай локальный project brief

```bash
cp PROJECT_BRIEF.example.md PROJECT_BRIEF.local.md
```

`PROJECT_BRIEF.local.md` заранее добавлен в `.gitignore`. Он предназначен для сырого пользовательского контекста и может содержать приватные ссылки, временные заметки и незрелые идеи.

## 3. Опиши проект своими словами

Структура `PROJECT_BRIEF.example.md` — подсказка, а не обязательная анкета. Полезно указать:

- что нужно создать;
- зачем существует проект;
- кто им пользуется;
- ключевые сценарии;
- ограничения;
- обязательные или желательные технологии;
- что точно не входит в scope;
- ссылки на референсы, API, дизайн и документацию;
- любые дополнительные мысли.

Не требуется заранее оформлять REQ, ADR или STEP — это задача initializer.

## 4. Запусти bootstrap

```text
INIT PROJECT
```

Initializer должен:

- прочитать brief и доступные референсы;
- создать `docs/PROJECT.md`;
- нормализовать продуктовые требования в `docs/requirements/SPEC.md`;
- сформировать минимальный архитектурный baseline;
- создать ADR только там, где устойчивое решение действительно принято или обязательно до реализации;
- вынести неизвестное в `docs/OPEN_QUESTIONS.md` или ранний `RESEARCH` / `ADR` STEP;
- создать roadmap и полноценные `planning/tasks/STEP-NNN.md`;
- связать REQ ↔ ADR ↔ STEP;
- заполнить scope, out of scope, dependencies, acceptance criteria и verification;
- заменить generated project blocks в `README.md` и `AGENTS.md`;
- выставить `project.initialized: true` в `.project/manifest.yaml` только после consistency check;
- не создавать production code;
- не изменять Harness release/lock как часть INIT.

## 5. Проверь результат

Особое внимание удели:

- не выдуманы ли требования;
- не создано ли слишком много ADR;
- правильно ли разбит roadmap;
- нет ли пропущенных dependencies;
- реалистичны ли acceptance criteria;
- достаточно ли ясны первые STEP.

Полезные команды:

```text
STATUS PROJECT
NEXT STEP
```

## 6. Настрой профили агентов

Изучи [`AGENT_CONFIGURATION.md`](AGENT_CONFIGURATION.md) и при необходимости измени `.codex/config.toml` / `.codex/agents/*.toml`.

Базовый принцип:

- reasoning-heavy роли — сильная модель и высокий effort;
- основной implementer — balanced профиль;
- механические роли — более экономичный профиль;
- reviewer должен оставаться независимым от implementer.

Пользовательские изменения этих файлов сохраняются при Harness update через 3-way merge.

## 7. Зафиксируй bootstrap

```text
GIT CHECK
COMMIT
PUSH
```

Политика веток/PR задаётся в `.project/git-policy.toml`. Подробно: [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md).

## 8. Начни разработку

Ручной flow:

```text
PLAN STEP-001
IMPLEMENT STEP-001
REVIEW STEP-001
```

Автоматизированный flow:

```text
RUN STEP-001
```

Новая задача обычным языком:

```text
ADD STEP: <описание>
```

Нужны дополнительные знания/technology playbook:

```text
FIND SKILL: <описание>
```

## 9. Обновляй Harness отдельно от project work

Проверка:

```text
CHECK HARNESS UPDATE
```

Применение:

```text
UPDATE HARNESS
```

Это maintenance flow без STEP и без автоматического commit/push/PR. Подробно: [`UPDATES.md`](UPDATES.md).

## Необязательные локальные инструкции

```bash
cp AGENTS.local.example.md AGENTS.local.md
```

`AGENTS.local.md` заранее игнорируется Git и читается после `AGENTS.md`. Для проектов, созданных до переименования, legacy `AGENT.local.md` временно поддерживается как fallback; при наличии обоих файлов используется `AGENTS.local.md`.

Перед INIT при необходимости настрой языки в `.project/manifest.yaml` → `language`.
