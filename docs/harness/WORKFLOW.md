# Workflow Design

Harness разделён на три слоя:

```text
HARNESS / protocol
AGENTS + skills + commands + templates
             ↓
PROJECT KNOWLEDGE BASE
REQ + ADR + architecture + planning
             ↓
CODE / TESTS / CONFIG
реализация и evidence
```

## Почему история чата не используется как база знаний

Новая сессия должна восстановить контекст из репозитория. Поэтому каждая стадия сохраняет durable handoff:

- PLAN → task `Implementation plan`;
- REVIEW → immutable review report;
- audit/reconcile → audit report;
- completion → Evidence + status projections.

## Почему REQ, ADR и STEP разделены

`REQ` отвечает на вопрос «что должно быть истинно для продукта?».
`ADR` — «какое устойчивое решение принято и почему?».
`STEP` — «какую ограниченную работу мы сейчас выполняем?».

Смешивание этих сущностей приводит к тому, что roadmap превращается в ТЗ, ADR — в changelog, а требования — в список файлов.

## Почему PLAN сохраняется в task

PLAN нужен не только текущему чату. Он является handoff от reasoning-heavy planner к более экономичному implementer и обеспечивает воспроизводимость между сессиями.

## Почему REVIEW отдельным файлом

Review report — исторический артефакт с verdict и findings. Он не должен исчезать после исправления и не должен переписывать исходный task contract.

## Почему RECONCILE обязателен

Реальный проект неизбежно получает ручные изменения, hotfix, drift документации и stale statuses. `PROJECT RECONCILE` периодически восстанавливает согласованность без скрытого исправления production code.


## Skill supply chain

Technology-specific knowledge не нужно заранее встраивать в template. Harness использует on-demand pipeline:

```text
Need capability
   ↓
SKILL FIND
   ↓ configured shortlist + durable report
User selects
   ↓
SKILL INSTALL
   ↓ inspect / provenance / routing
.agents/skills/<name>
```

Если достойного upstream нет:

```text
SKILL CREATE
   ↓
project-native SKILL.md
```

Это сохраняет template универсальным и одновременно не заставляет пользователя вручную искать/писать каждый technology playbook.

## Micro-change path

Не вся работа проходит через STEP. Безопасная мелкая правка использует короткий путь:

```text
PROJECT QUICK FIX: ...   или ручная правка
        ↓
proportional check
        ↓
GIT CHECK
        ↓
GIT COMMIT
```

Если обнаруживается contract/risk change, короткий путь прекращается и начинается `STEP ADD:`.

## Collaboration templates как производный артефакт

Issue/PR templates зависят от текущего tooling и периодически регенерируются командой `GITHUB GENERATE TEMPLATES`. Они не являются canonical source требований или verification commands: генератор извлекает эти данные из repository state.
