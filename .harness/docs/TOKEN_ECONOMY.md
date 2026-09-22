# Token Economy

## Цель

AI Development Harness проектируется так, чтобы модель тратила reasoning и context только на решения, которые действительно требуют семантической оценки. Проверяемая, вычислимая и механическая работа должна выполняться deterministic tooling.

> **Model consumes decisions/results, not implementation/config internals.**

Это архитектурное требование, а не рекомендация по стилю.

## Граница ответственности

В deterministic слой по умолчанию относятся:

- parsing и structural validation;
- hashes/fingerprints и dependency state;
- Git/repository state и policy checks;
- command routing и execution state;
- report naming/writing и другие механические mutations;
- чтение machine-readable config, когда результат можно вернуть модели компактным JSON.

Модель нужна для задач, где есть смысловая неоднозначность:

- составление и semantic review плана;
- анализ требований и архитектурных альтернатив;
- implementation/code review;
- security reasoning;
- оценка соответствия реализации intent/Acceptance criteria.

Если один и тот же результат можно корректно и безопасно получить Python-скриптом без LLM, protocol должен предпочитать скрипт.

## Always-on context

Always-on context — Harness instructions, которые runtime получает до выбора command-specific skill.

На baseline v0.7.0 gate учитывает:

- Codex: Harness-controlled часть `AGENTS.md`;
- Claude Code: Harness-controlled часть `AGENTS.md` плюс `CLAUDE.md` adapter.

Generated blocks `PROJECT-CONTEXT` и `SKILL-ROUTING` являются project-owned динамическим контекстом. Gate показывает их размер отдельно, но не включает их в core Harness budget: `PROJECT INIT` не должен становиться невалидным только из-за содержимого конкретного проекта.

Локальные/private overrides также не являются частью tracked Harness baseline.

## Почему измерение идёт в символах, а не в токенах

Token count зависит от модели и tokenizer. Core CI не должен зависеть от внешнего tokenizer package или конкретного runtime. Поэтому hard gate использует число Unicode characters как стабильную dependency-free метрику.

Это не попытка точно предсказать счёт за API. Метрика нужна для другого invariant: always-on Harness context не должен незаметно расти.

Baseline после progressive-disclosure refactor:

| Runtime | Harness-controlled chars | До refactor | Снижение |
| --- | ---: | ---: | ---: |
| Codex | 7 224 | 19 275 | 62,5% |
| Claude Code | 8 029 | 20 080 | 60,0% |

`AGENTS.md` после refactor является bootstrap/router. Command playbooks остаются pull-based в skills/docs и не должны возвращаться в always-on файл.

Повышение этих лимитов считается архитектурным изменением и должно быть явно видно в diff/review. Снижение лимита после очередной оптимизации приветствуется и фиксирует достигнутую экономию как новый ceiling.

## Python source и комментарии

Подробные комментарии в `.harness/tools/*.py` не являются always-on context. При обычной эксплуатации агент должен **исполнять tool**, а не читать его исходник. Source читается только когда это действительно нужно: разработка/аудит самого Harness, диагностика tool failure или явный запрос пользователя.

Поэтому экономия токенов не должна достигаться удалением полезных комментариев из deterministic implementation. Правильная оптимизация — не загружать implementation в LLM context без необходимости.

## Config и документация

Machine-readable config должен читать deterministic tool, когда модель не обязана интерпретировать параметр семантически. Tool возвращает минимальный результат или компактный JSON.

Подробная документация хранится pull-based в `.harness/docs/**` и читается по необходимости. Always-on bootstrap должен оставаться картой/routing surface, а не полным manual.

## Gate

Проверка:

```bash
python3 .harness/tools/context-budget.py
python3 .harness/tools/context-budget.py --json
```

`validate.py` включает тот же invariant в baseline integrity validation, а Harness Integrity CI отдельно запускает synthetic regression self-test.

Нарушение budget — deterministic `FAIL`: новый always-on текст нельзя добавить незаметно. Сначала следует вынести детали в skill/docs/tool output или осознанно пересмотреть baseline.
