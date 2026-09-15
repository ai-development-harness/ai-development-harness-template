# Структура репозитория

Базовый template разделён на protocol layer, project knowledge base и будущую реализацию.

```text
.
├── README.md                         # project entry point; generated PROJECT block сохраняется при update
├── AGENTS.md                         # repository-level инструкции; generated blocks сохраняются при update
├── PROJECT_BRIEF.example.md          # шаблон локального сырого brief
├── .project/
│   ├── manifest.yaml                 # protocol generation + current release + project state
│   ├── harness.lock.json             # immutable source BASE текущего Harness release
│   ├── harness-update.toml           # source/ownership/merge policy self-update
│   ├── harness-policy.toml           # deterministic integrity policy
│   └── git-policy.toml               # Git workflow policy
├── .codex/                           # project-scoped roles и model/effort configuration
├── .agents/skills/                   # core workflow + project/technology skills
├── docs/
│   ├── PROJECT.md                    # нормализованное описание конкретного проекта
│   ├── architecture.md               # текущий architecture baseline
│   ├── GLOSSARY.md                   # продуктовый словарь после INIT
│   ├── OPEN_QUESTIONS.md
│   ├── requirements/                 # REQ definitions + status projection
│   ├── adr/                          # immutable architecture decisions
│   ├── skills/                       # registry/provenance дополнительных skills
│   └── harness/                      # документация самого Harness, включая UPDATES.md
├── planning/
│   ├── EXECUTION_PROTOCOL.md
│   ├── PLAN.md
│   ├── STATUS.md
│   ├── tasks/                        # canonical STEP files
│   ├── reviews/                      # immutable review reports
│   ├── audits/                       # audit/reconcile reports
│   ├── releases/                     # release reports
│   ├── harness-updates/              # durable UPDATE HARNESS reports
│   └── skill-searches/               # durable FIND SKILL results
├── tools/harness/
│   └── validate.py                   # deterministic integrity/safety validator
└── .github/                          # PR template + Harness CI
```

## Три слоя

```text
HARNESS / PROTOCOL
AGENTS + commands + skills + policies + templates + update-agent
                     ↓
PROJECT KNOWLEDGE BASE
PROJECT + REQ + ADR + architecture + planning
                     ↓
IMPLEMENTATION
code + tests + migrations + runtime configuration
```

Product implementation folders намеренно отсутствуют из template и появляются только после инициализации/реальных STEP.

Self-updater использует allowlist source paths и по умолчанию считает всё неизвестное project-owned.
