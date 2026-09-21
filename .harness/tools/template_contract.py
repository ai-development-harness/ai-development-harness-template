#!/usr/bin/env python3
"""Canonical schema-v1 project-owned templates used only by PROJECT RECONCILE.

HARNESS UPDATE не перезаписывает project-owned templates. RECONCILE refreshes
их из protocol-owned definitions here, что сохраняет ownership boundary.
"""
from __future__ import annotations

from pathlib import Path

from harness_config import (
    adr_directory,
    audit_directory,
    init_review_directory,
    open_questions_directory,
    planning_review_directory,
    release_directory,
    requirements_directory,
    review_directory,
    skill_search_directory,
    task_directory,
)


STEP_TEMPLATE = """---
schema: 1
id: STEP-NNN
status: planned
type: implementation
priority: medium
phase: TBD
depends_on: []
requirements:
  - REQ-NNN
adrs: []
architecture_refs:
  - docs/architecture.md#relevant-section
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
review:
  latest_verdict: not_reviewed
  latest_report: null
---

# STEP-NNN — Название

## Goal

Один чёткий результат STEP.

## Context

Почему задача появилась.

## Scope

- Конкретная работа внутри STEP.

## Mutation policy

### Allowed

- Допустимые области mutation.

### Conditional

- Условно допустимые изменения.

### Forbidden

- unrelated scope.

## Out of scope

- Явные границы.

## Acceptance criteria

- Проверяемый критерий.

## Verification

- Реальные проверки.

## Deliverables

- Expected artifacts.

## Implementation plan

Заполняется STEP PLAN.

## Evidence

Заполняется по факту.

## Blocker / Failure reason

—
"""

REQ_TEMPLATE = """---
schema: 1
id: REQ-NNN
priority: medium
source: brief
steps:
  - STEP-NNN
adrs: []
---

# REQ-NNN — Название

## Requirement

Проверяемое требование.

## Rationale

Почему requirement существует.

## Acceptance

- Наблюдаемый критерий.
"""

ADR_TEMPLATE = """---
schema: 1
id: ADR-NNN
status: proposed
date: YYYY-MM-DD
deciders: []
supersedes: []
superseded_by: []
requirements:
  - REQ-NNN
steps:
  - STEP-NNN
---

# ADR-NNN — Название решения

## Context

TBD

## Problem

TBD

## Decision

TBD

## Alternatives considered

TBD

## Consequences

TBD

## Security implications

TBD

## Data / migration implications

TBD

## Compatibility / operational implications

TBD
"""

OQ_TEMPLATE = """---
schema: 1
id: OQ-NNN
status: open
affects:
  - PROJECT
created_at: YYYY-MM-DDTHH:MM:SSZ
resolved_at: null
---

# OQ-NNN — Краткий вопрос

## Context

Почему вопрос существенный.

## Decision needed

Какое решение требуется.

## Resolution


"""

REVIEW_TEMPLATE = """---
schema: 1
kind: step_review
step_id: STEP-NNN
verdict: pass
reviewer_role: reviewer
created_at: YYYY-MM-DDTHH:MM:SSZ
reviewed_revision:
  git_head: null
  worktree_hash: null
specialized_reviews:
  security: not_required
  security_report: null
  security_reason: reason
  tests: not_required
  tests_report: null
  tests_reason: reason
---

# STEP REVIEW STEP-NNN — YYYY-MM-DD HH:MM

## Scope checked

TBD

## Findings

При PASS material findings отсутствуют.

### F-001 — Title

**Severity:** high
**Category:** implementation
**Location:** path:line
**Scenario:** Given / When / Then
**Impact:** ...
**Fix direction:** ...

## Verification observations

TBD

## Verdict rationale

TBD
"""

PLAN_REVIEW_TEMPLATE = """---
schema: 1
kind: planning_review
step_id: STEP-NNN
verdict: pass
reviewer_role: planner
context_basis: sha256:...
plan_content_hash: sha256:...
created_at: YYYY-MM-DDTHH:MM:SSZ
---

# Planning Review STEP-NNN — YYYY-MM-DD HH:MM

## Scope checked

TBD

## Findings

TBD

## Verdict rationale

TBD
"""

INIT_REVIEW_TEMPLATE = """---
schema: 1
kind: init_review
stage: requirements
verdict: pass
reviewer_role: initializer
basis: sha256:...
created_at: YYYY-MM-DDTHH:MM:SSZ
---

# PROJECT INIT Review — YYYY-MM-DD HH:MM

## Scope checked

TBD

## Findings

TBD

## Verdict rationale

TBD
"""

AUDIT_TEMPLATE = """---
schema: 1
kind: audit
scope: project
mode: audit
created_at: YYYY-MM-DDTHH:MM:SSZ
result: complete
---

# Audit — YYYY-MM-DD

## Sources checked

TBD

## Actual state

TBD

## Drift / findings

TBD

## Evidence

TBD

## Corrective actions

- none
"""

RELEASE_TEMPLATE = """---
schema: 1
kind: release_check
target: version-or-tag
verdict: blocked
created_at: YYYY-MM-DDTHH:MM:SSZ
---

# Release Check — YYYY-MM-DD

## Requirements / scope

TBD

## Verification gates

TBD

## Security / migrations / compatibility

TBD

## Unresolved blockers

TBD

## Evidence

TBD
"""

SKILL_SEARCH_TEMPLATE = """---
schema: 1
kind: skill_search
query: user-description
status: complete
created_at: YYYY-MM-DDTHH:MM:SSZ
candidate_count: 0
---

# SKILL SEARCH — timestamp

## Search strategy

TBD

## Ranking criteria

TBD

## Candidates

TBD

## Rejected / notable alternatives

TBD

## Next command

TBD
"""


def template_targets(root: Path) -> dict[Path, str]:
    return {
        task_directory(root) / "TEMPLATE.md": STEP_TEMPLATE,
        requirements_directory(root) / "TEMPLATE.md": REQ_TEMPLATE,
        adr_directory(root) / "TEMPLATE.md": ADR_TEMPLATE,
        open_questions_directory(root) / "TEMPLATE.md": OQ_TEMPLATE,
        review_directory(root) / "TEMPLATE.md": REVIEW_TEMPLATE,
        planning_review_directory(root) / "TEMPLATE.md": PLAN_REVIEW_TEMPLATE,
        init_review_directory(root) / "TEMPLATE.md": INIT_REVIEW_TEMPLATE,
        audit_directory(root) / "TEMPLATE.md": AUDIT_TEMPLATE,
        release_directory(root) / "TEMPLATE.md": RELEASE_TEMPLATE,
        skill_search_directory(root) / "TEMPLATE.md": SKILL_SEARCH_TEMPLATE,
    }


def refresh_project_templates(root: Path) -> list[str]:
    changed: list[str] = []
    for path, expected in template_targets(root).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual != expected:
            path.write_text(expected, encoding="utf-8", newline="\n")
            changed.append(path.relative_to(root).as_posix())
    return changed
