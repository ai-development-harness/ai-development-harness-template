<!-- PROJECT:START -->
# AI Development Harness — новый проект

Проект ещё не инициализирован.

1. Создай локальный brief:

   ```bash
   cp PROJECT_BRIEF.example.md PROJECT_BRIEF.local.md
   ```

2. Опиши проект своими словами в `PROJECT_BRIEF.local.md`: цель, пользователей, сценарии, ограничения, предпочтительный стек, референсы и любые важные заметки.
3. При необходимости скопируй `AGENTS.local.example.md` в `AGENTS.local.md` и добавь локальные команды/предпочтения.
4. Открой репозиторий в Codex или Claude Code.
5. Выполни:

   ```text
   PROJECT INIT
   ```

После успешной инициализации агент заменит **только этот блок** описанием конкретного проекта, ключевыми ссылками и текущей точкой входа в разработку.
<!-- PROJECT:END -->

## Runtime adapters

Harness protocol не привязан к одной модели или одному coding agent:

- Codex: `.codex/config.toml` + `.codex/agents/*.toml`;
- Claude Code: `CLAUDE.md` + `.claude/settings.json` + `.claude/agents/*.md`.

`AGENTS.md`, execution protocol, REQ/ADR/STEP и `.agents/skills/` остаются общими источниками истины.

## Документация Harness

- [Начало работы](docs/harness/GETTING_STARTED.md)
- [Как устроена документация и связи REQ / ADR / STEP / PLAN / STATUS](docs/harness/DOCUMENT_MODEL.md)
- [Глоссарий терминов Harness](docs/harness/GLOSSARY.md)
- [Структура репозитория](docs/harness/REPOSITORY_LAYOUT.md)
- [Команды](docs/harness/COMMANDS.md)
- [Execution Protocol](docs/harness/EXECUTION_PROTOCOL.md)
- [Обновление Harness в существующем проекте](docs/harness/UPDATES.md)
- [Агенты, модели и reasoning effort](docs/harness/AGENT_CONFIGURATION.md)
- [Claude Code adapter](docs/harness/CLAUDE_CODE.md)
- [Git workflow: GIT CHECK / GIT COMMIT / GIT PUSH / GIT PR / GIT SYNC](docs/harness/GIT_WORKFLOW.md)
- [CI и Harness Integrity](docs/harness/CI.md)
- [Skills: SKILL FIND / SKILL INSTALL / SKILL CREATE](docs/harness/SKILL_MANAGEMENT.md)
- [Синтаксис команд и цепочек](docs/harness/COMMAND_SYNTAX.md)
- [Таблица допустимых переходов команд](docs/harness/COMMAND_TRANSITIONS.md)
- [Полное оглавление документации Harness](docs/harness/README.md)
