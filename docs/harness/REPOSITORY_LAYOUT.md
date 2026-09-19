# Структура репозитория

Базовый template разделён на protocol layer, runtime adapters, project knowledge base и будущую реализацию.

```text
.
├── README.md                         # project entry point; generated PROJECT block сохраняется при update
├── AGENTS.md                         # канонические repository-level инструкции Harness
├── CLAUDE.md                         # Claude Code bridge: импортирует AGENTS.md
├── PROJECT_BRIEF.example.md          # шаблон локального сырого brief
├── .project/
│   ├── manifest.yaml                 # protocol generation + current release + project state
│   ├── harness.lock.json             # immutable source BASE текущего Harness release
│   ├── harness-update-graph.json     # machine-readable граф маршрутов Harness update
│   ├── command-transitions.json      # canonical command/chain transition graph
│   ├── harness-update.toml           # source/ownership/merge policy self-update
│   ├── harness-policy.toml           # deterministic integrity policy
│   └── git-policy.toml               # Git workflow policy
├── .codex/                           # Codex project-scoped roles и model/effort configuration
├── .claude/                          # Claude Code project settings и role profiles
│   ├── settings.json
│   └── agents/
├── .agents/skills/                   # runtime-neutral core workflow + project/technology skills
├── docs/
│   ├── PROJECT.md                    # нормализованное описание конкретного проекта
│   ├── architecture.md               # текущий architecture baseline
│   ├── GLOSSARY.md                   # продуктовый словарь после INIT
│   ├── OPEN_QUESTIONS.md
│   ├── requirements/                 # REQ definitions + status projection
│   ├── adr/                          # immutable architecture decisions
│   ├── skills/                       # registry/provenance дополнительных skills
│   └── harness/                      # документация самого Harness, включая runtime adapters
├── planning/
│   ├── EXECUTION_PROTOCOL.md
│   ├── PLAN.md
│   ├── STATUS.md
│   ├── tasks/                        # canonical STEP files
│   ├── reviews/                      # immutable review reports
│   ├── audits/                       # audit/reconcile reports
│   ├── releases/                     # release reports
│   ├── harness-updates/              # durable HARNESS UPDATE APPLY reports
│   └── skill-searches/               # durable SKILL FIND results
├── tools/harness/
│   ├── validate.py                   # deterministic integrity/safety validator
│   ├── command_transitions.py        # parser + graph validator + Markdown renderer
│   ├── validate-command.py           # pre-interpretation structural command gate
│   ├── execution_status.py           # universal crash-safe execution state + resolver
│   ├── execution-state.py            # CLI управления execution-status.json
│   ├── resolve-next-command.py       # deterministic next/resume resolver
│   └── execution-self-test.py        # self-test single/chain/orchestration recovery
└── .github/                          # PR template + Harness CI
```

## Слои

```text
HARNESS / PROTOCOL
AGENTS + commands + skills + policies + templates
                     ↓
RUNTIME ADAPTERS
Codex (.codex) / Claude Code (CLAUDE.md + .claude)
                     ↓
PROJECT KNOWLEDGE BASE
PROJECT + REQ + ADR + architecture + planning
                     ↓
IMPLEMENTATION
code + tests + migrations + runtime configuration
```

Runtime adapter не является источником семантики Harness. Один и тот же STEP/REQ/ADR/Git contract должен исполняться одинаково независимо от Codex или Claude Code.

Command transition graph также относится к protocol layer: отсутствие edge в `.project/command-transitions.json` означает запрет перехода независимо от runtime/LLM interpretation.

Product implementation folders намеренно отсутствуют из template и появляются только после инициализации/реальных STEP.

Self-updater использует allowlist source paths и по умолчанию считает всё неизвестное project-owned. Допустимый target и обязательные промежуточные releases определяются remote `.project/harness-update-graph.json`; moving `main` при этом не становится source baseline — содержимое каждого hop читается только из immutable tag.
