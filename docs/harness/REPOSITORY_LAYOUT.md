# Структура репозитория

Базовый template разделён на protocol layer, project knowledge base и будущую реализацию.

```text
.
├── README.md                         # короткая project entry point + ссылки на Harness docs
├── AGENTS.md                         # постоянные repository-level инструкции агентам
├── PROJECT_BRIEF.example.md          # шаблон локального сырого brief
├── .project/                         # machine-readable состояние и policies Harness
├── .codex/                           # project-scoped роли и model/effort configuration
├── .agents/skills/                   # workflow + project/technology skills
├── docs/
│   ├── PROJECT.md                    # нормализованное описание конкретного проекта
│   ├── architecture.md               # текущий architecture baseline
│   ├── GLOSSARY.md                   # продуктовый словарь после INIT
│   ├── OPEN_QUESTIONS.md
│   ├── requirements/                 # REQ definitions + status projection
│   ├── adr/                          # immutable architecture decisions
│   ├── skills/                       # registry/provenance дополнительных skills
│   └── harness/                      # документация самого Harness
├── planning/
│   ├── EXECUTION_PROTOCOL.md
│   ├── PLAN.md
│   ├── STATUS.md
│   ├── tasks/                        # canonical STEP files
│   ├── reviews/                      # immutable review reports
│   ├── audits/                       # audit/reconcile reports
│   ├── releases/                     # release reports
│   └── skill-searches/               # durable FIND SKILL results
├── tools/harness/                    # deterministic Harness tooling
└── .github/                          # PR template + Harness CI
```

## Три слоя

```text
HARNESS / PROTOCOL
AGENTS + commands + skills + policies + templates
                     ↓
PROJECT KNOWLEDGE BASE
PROJECT + REQ + ADR + architecture + planning
                     ↓
IMPLEMENTATION
code + tests + migrations + runtime configuration
```

Product implementation folders намеренно отсутствуют из template и появляются только после инициализации/реальных STEP.
