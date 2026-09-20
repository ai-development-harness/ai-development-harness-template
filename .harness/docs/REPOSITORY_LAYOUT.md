# Структура репозитория

Базовый template разделён на **Harness control plane**, runtime integration surfaces, project knowledge base и project planning state.

## Главное правило владения

```text
.harness/**   → namespace/control plane AI Development Harness
docs/**       → документация конкретного проекта
planning/**   → planning state и история конкретного проекта
```

Расположение внутри `.harness/` **не является ownership class само по себе**. Внутри namespace есть:

- `harness_owned` core: `.harness/docs/**`, `.harness/tools/**`, update/integrity policies и machine-readable protocol metadata;
- `shared`: например `.harness/manifest.yaml` и `.harness/git-policy.toml`;
- local-only state: `.harness/local/**`, который никогда не должен попадать в Git.

Colocated `TEMPLATE.md` рядом с project artifacts, например `docs/requirements/TEMPLATE.md`, `docs/adr/TEMPLATE.md` и `planning/tasks/TEMPLATE.md`, считаются **project-owned scaffolds**. Harness требует их наличие и использует как локальные шаблоны, но self-updater не меняет их автоматически; это сохраняет legacy/custom project adaptations.

Runtime integration surfaces (`AGENTS.md`, `.agents/`, `.codex/`, `.claude/`, `CLAUDE.md`) остаются в ожидаемых runtime местах и не переносятся внутрь `.harness/`.

## Layout

```text
.
├── README.md                         # project entry point; generated PROJECT block сохраняется при update
├── AGENTS.md                         # repository-level contract / runtime entry point
├── CLAUDE.md                         # Claude Code bridge: импортирует AGENTS.md
├── PROJECT_BRIEF.example.md          # scaffold локального сырого brief
├── .harness/                         # Harness namespace / control plane
│   ├── README.md                     # краткое описание internal namespace
│   ├── manifest.yaml                 # release, project state и Harness settings
│   ├── harness.lock.json             # immutable source BASE текущего Harness release
│   ├── harness-update-graph.json     # machine-readable граф маршрутов Harness update
│   ├── command-transitions.json      # canonical command/chain transition graph
│   ├── harness-update.toml           # source/ownership/merge policy self-update
│   ├── harness-policy.toml           # deterministic integrity policy
│   ├── git-policy.toml               # Git workflow policy
│   ├── docs/                         # human-readable документация ядра
│   │   ├── README.md
│   │   ├── EXECUTION_PROTOCOL.md
│   │   ├── COMMANDS.md
│   │   ├── COMMAND_SYNTAX.md
│   │   ├── COMMAND_TRANSITIONS.md
│   │   └── ...
│   ├── tools/                        # dependency-free deterministic tooling
│   │   ├── validate.py
│   │   ├── command_transitions.py
│   │   ├── command_references.py
│   │   ├── validate-command.py
│   │   ├── check-command-references.py
│   │   ├── execution_status.py
│   │   ├── execution-state.py
│   │   ├── resolve-next-command.py
│   │   └── execution-self-test.py
│   └── local/                        # local-only operational state, gitignored
│       └── execution/
│           └── execution-status.json
├── .agents/skills/                   # runtime-neutral core + project/technology skills
├── .codex/                           # Codex integration surface
├── .claude/                          # Claude Code integration surface
├── docs/                             # только project knowledge/scaffold
│   ├── PROJECT.md
│   ├── architecture.md
│   ├── GLOSSARY.md
│   ├── OPEN_QUESTIONS.md
│   ├── requirements/
│   │   ├── REQ-NNN-*.md              # canonical requirement definitions
│   │   ├── SPEC.md                   # index projection REQ
│   │   ├── STATUS.md                 # lifecycle projection REQ
│   │   └── TEMPLATE.md               # colocated scaffold
│   ├── adr/                          # project architecture decisions + template
│   └── skills/                       # project skill registry/provenance
├── planning/                         # только project planning/history/scaffold
│   ├── PLAN.md
│   ├── STATUS.md
│   ├── tasks/
│   ├── reviews/
│   ├── audits/
│   ├── releases/
│   ├── harness-updates/              # история update конкретного project instance
│   └── skill-searches/
└── .github/                          # collaboration/CI integration surface
```

## Слои

```text
HARNESS CONTROL PLANE
.harness/**
                     ↓
RUNTIME INTEGRATION
AGENTS / .agents / .codex / .claude / CLAUDE.md
                     ↓
PROJECT KNOWLEDGE
docs/**
                     ↓
PROJECT PLANNING / HISTORY
planning/**
                     ↓
IMPLEMENTATION
code + tests + migrations + runtime configuration
```

Runtime adapter не является источником семантики Harness. Один и тот же STEP/REQ/ADR/Git contract должен исполняться одинаково независимо от Codex или Claude Code.

Command transition graph относится к ядру: отсутствие edge в `.harness/command-transitions.json` означает запрет перехода независимо от runtime/LLM interpretation.

Product implementation folders намеренно отсутствуют из template и появляются только после инициализации/реальных STEP.

Self-updater использует ownership policy из `.harness/harness-update.toml` и по умолчанию считает неизвестные paths project-owned. Допустимый target и обязательные промежуточные releases определяются remote `.harness/harness-update-graph.json`; moving `main` при этом не становится source baseline — содержимое каждого hop читается только из immutable tag.
