# Начало работы

## Требования к локальному окружению

- Git — Harness использует repository state, diff/index и Git workflow как часть deterministic gates.
- Python 3.11+ — нужен только для `.harness/tools/validate.py`; product runtime от Python не зависит.
- Один поддерживаемый AI runtime: Codex или Claude Code. Для Claude-specific project configuration см. [`CLAUDE_CODE.md`](CLAUDE_CODE.md).

В CI версия Python задаётся явно. Переписывать validator на Bash только ради устранения Python dependency не рекомендуется: validator разбирает TOML стандартным `tomllib`, JSON стандартным `json` и выполняет структурные проверки, которые shell-скрипт без дополнительного парсера воспроизводил бы менее надёжно.

## 1. Создай новый репозиторий

Предпочтительный путь — GitHub **Use this template**. После этого клонируй уже созданный репозиторий проекта.

Если template клонируется напрямую, перед первым `GIT PUSH` замени `origin` на репозиторий нового проекта.

Template уже содержит `.harness/harness.lock.json`: это BASE для будущих `HARNESS UPDATE CHECK` / `HARNESS UPDATE APPLY`. Не удаляй lock при инициализации проекта. Источником обновлений являются только immutable release tags, а не moving `main`.

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

## 4. Открой репозиторий в выбранном runtime

### Codex

Codex использует `AGENTS.md`, `.codex/config.toml` и `.codex/agents/*.toml`.

### Claude Code

Claude Code использует `CLAUDE.md`, который импортирует `@AGENTS.md`, плюс `.claude/settings.json` и `.claude/agents/*.md`.

Core `.agents/skills/` общие для обоих runtime adapters.

## 5. Перед INIT проверь актуальность Harness

Если после создания репозитория из template вышел новый Harness release, обновиться можно **до** `PROJECT INIT`:

```text
HARNESS UPDATE CHECK
HARNESS UPDATE APPLY
```

`project.initialized: false` не блокирует эти команды. Pre-init update меняет только Harness protocol layer/lock, не выполняет bootstrap проекта и не переводит `project.initialized` в `true`. Локальный `PROJECT_BRIEF.local.md` не является managed Harness path и не перезаписывается updater-ом.

После update проверь и отдельно зафиксируй maintenance diff, чтобы не смешивать его с будущим bootstrap проекта:

```text
inspect diff
GIT CHECK > COMMIT
```

Если доступного update нет, переходи сразу к `PROJECT INIT`.

## 6. Запусти bootstrap

```text
PROJECT INIT
```

Initializer должен:

- прочитать brief и доступные референсы;
- создать `docs/PROJECT.md`;
- создать каждый продуктовый REQ отдельным `docs/requirements/REQ-NNN-*.md`, перестроить `docs/requirements/SPEC.md` как index projection и инициализировать lifecycle-state только в `docs/requirements/STATUS.md`;
- сформировать минимальный архитектурный baseline;
- создать ADR только там, где устойчивое решение действительно принято или обязательно до реализации;
- вынести неизвестное в `docs/OPEN_QUESTIONS.md` или ранний `RESEARCH` / `ADR` STEP;
- создать roadmap и полноценные `planning/tasks/STEP-NNN.md`;
- связать REQ ↔ ADR ↔ STEP;
- заполнить scope, out of scope, dependencies, acceptance criteria и verification;
- заменить generated project blocks в `README.md` и `AGENTS.md`;
- выставить `project.initialized: true` в `.harness/manifest.yaml` только после consistency check;
- не создавать production code;
- не изменять Harness release/lock как часть INIT.

## 7. Проверь результат

Особое внимание удели:

- не выдуманы ли требования;
- не создано ли слишком много ADR;
- правильно ли разбит roadmap;
- нет ли пропущенных dependencies;
- реалистичны ли acceptance criteria;
- достаточно ли ясны первые STEP.

Полезные команды:

```text
PROJECT STATUS
STEP NEXT
```

## 8. Настрой профили агентов

Изучи [`AGENT_CONFIGURATION.md`](AGENT_CONFIGURATION.md).

Для Codex при необходимости измени:

```text
.codex/config.toml
.codex/agents/*.toml
```

Для Claude Code:

```text
.claude/settings.json
.claude/agents/*.md
```

Если Claude model/effort нужно изменить только локально, используй `.claude/settings.local.json`, не создавая repository diff.

У Codex сейчас нет нативного project-local файла с такой семантикой. Не создавай `.codex/config.local.toml`; варианты персонального override и причина различия между runtime описаны в [`AGENT_CONFIGURATION.md`](AGENT_CONFIGURATION.md#локальные-настройки-runtime).

Базовый принцип:

- reasoning-heavy роли — сильная модель и высокий effort;
- основной implementer — balanced профиль;
- механические роли — более экономичный профиль;
- reviewer должен оставаться независимым от implementer.

Tracked runtime configs сохраняются при Harness update через 3-way merge.

## 9. Зафиксируй bootstrap

```text
GIT CHECK > COMMIT > PUSH
```

Политика веток/PR задаётся в `.harness/git-policy.toml`. Подробно: [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md).

## 10. Начни разработку

Ручной flow:

```text
STEP PLAN STEP-001
STEP IMPLEMENT STEP-001
STEP REVIEW STEP-001
```

Автоматизированный flow:

```text
STEP RUN STEP-001
```

Новая задача обычным языком:

```text
STEP ADD: <описание>
```

Нужны дополнительные знания/technology playbook:

```text
SKILL FIND: <описание>
```

## 11. Обновляй Harness отдельно от project work

Проверка:

```text
HARNESS UPDATE CHECK
```

Применение:

```text
HARNESS UPDATE APPLY
```

Это maintenance flow без STEP и без автоматического commit/push/PR. Подробно: [`UPDATES.md`](UPDATES.md).

## Необязательные локальные инструкции

Общие local overrides:

```bash
cp AGENTS.local.example.md AGENTS.local.md
```

`AGENTS.local.md` заранее игнорируется Git и читается после `AGENTS.md` согласно Harness contract.

Claude-specific private instructions можно хранить в `CLAUDE.local.md`; Claude Code автоматически читает его рядом с `CLAUDE.md`. Файл также игнорируется Git.

Перед INIT при необходимости настрой языки в `.harness/manifest.yaml` → `language`.
