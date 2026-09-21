#!/usr/bin/env python3
"""Default schema-v1 project-owned templates.

Protocol-owned definitions задают bootstrap/default content, но после INIT
существующий TEMPLATE.md принадлежит проекту и не перезаписывается RECONCILE.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from document_contract import DocumentError, parse_document
from harness_config import (
    adr_directory,
    architecture_path,
    get,
    audit_directory,
    init_review_directory,
    open_questions_directory,
    planning_review_directory,
    release_directory,
    requirements_directory,
    review_directory,
    load_manifest,
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
  - "docs/architecture.md#relevant-section"
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-NNN — Название

## Goal

Один чёткий результат STEP.

## Context

Почему задача появилась и какое текущее состояние важно.

## Scope

- Конкретная работа внутри STEP.

## Mutation policy

### Allowed

- Явно перечислить допустимые области mutation.

### Conditional

- Указать изменения, допустимые только при доказанной необходимости.

### Forbidden

- unrelated scope.

## Out of scope

- Явно перечислить то, что легко случайно реализовать «заодно».

## Acceptance criteria

- Проверяемый критерий 1.
- Проверяемый критерий 2.

## Verification

- Реальные команды/проверки; не выдумывать отсутствующие scripts.

## Deliverables

- Expected code/docs/tests/config artifacts.

## Implementation plan

Заполняется командой `STEP PLAN STEP-NNN`. Пока semantic planning-review не дал PASS для текущих context basis + content hash, `plan.status` не может быть `ready`.

## Evidence

Заполняется по факту реализации и verification. Для каждой значимой проверки указывай Command, Exit code и Observed.

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

Проверяемое описание требуемого поведения/результата без привязки к случайной реализации.

## Rationale

Почему requirement существует.

## Acceptance

- Наблюдаемый критерий 1.
- Наблюдаемый критерий 2.
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

Почему требуется устойчивое решение.

## Problem

Какую архитектурную проблему нужно решить.

## Decision

Принятое решение.

## Alternatives considered

### Вариант A

Плюсы/минусы.

### Вариант B

Плюсы/минусы.

## Consequences

Положительные и отрицательные последствия.

## Security implications

Если не применимо — явно указать.

## Data / migration implications

Если не применимо — явно указать.

## Compatibility / operational implications

Если не применимо — явно указать.
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

Почему вопрос существенный и почему его нельзя безопасно решить предположением.

## Decision needed

Какое решение требуется.

## Resolution

Заполняется после решения вопроса. Для `status: open` может быть пустым.
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
  gate_basis: sha256:...
  required: []
  security: not_required
  security_evidence: null
  security_reason: no_security_surface
  tests: not_required
  tests_evidence: null
  tests_reason: no_test_surface
---

# STEP REVIEW STEP-NNN — YYYY-MM-DD HH:MM

## Scope checked

- Task contract
- REQ/ADR/OQ/architecture refs
- Implementation plan
- Diff/current code
- Tests/verification

## Findings

При PASS material findings отсутствуют.

### F-001 — Title

**Severity:** high
**Category:** implementation
**Location:** path:line / component
**Scenario:** Given / When / Then
**Impact:** ...
**Fix direction:** ...

## Verification observations

Зафиксировать реальные проверки и ограничения доказательств.

## Verdict rationale

Кратко объяснить, почему verdict следует из findings и evidence.
"""

PLAN_REVIEW_TEMPLATE = """---
schema: 1
kind: planning_review
step_id: STEP-NNN
verdict: pass
reviewer_role: reviewer
finding_count: 0
context_basis: sha256:...
plan_content_hash: sha256:...
created_at: YYYY-MM-DDTHH:MM:SSZ
---

# Planning Review STEP-NNN — YYYY-MM-DD HH:MM

## Scope checked

- STEP contract
- Dependencies/completion proofs
- Linked REQ/Accepted ADR/Open Questions
- Architecture refs
- Proposed Implementation plan
- Verification feasibility

## Findings

При PASS material semantic contradictions отсутствуют.

## Verdict rationale

TBD
"""

INIT_REVIEW_TEMPLATE = """---
schema: 1
kind: init_review
stage: requirements
verdict: pass
reviewer_role: reviewer
finding_count: 0
basis: sha256:...
created_at: YYYY-MM-DDTHH:MM:SSZ
---

# PROJECT INIT Review — requirements | roadmap — YYYY-MM-DD HH:MM

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

- STEP-NNN / none
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

- queries/sources used

## Ranking criteria

- relevance;
- SKILL.md / Agent Skills compatibility;
- workflow quality;
- provenance/maintenance;
- license;
- safety.

## Candidates

### #1 — name

- Repository: owner/repo
- Path: path
- URL: url
- Ref/commit inspected: ref
- License: license/unknown
- Why it fits: ...
- Limitations: ...
- Safety notes: ...
- Recommendation: ...

## Rejected / notable alternatives

- candidate: reason

## Next command

`SKILL INSTALL: #1` либо `SKILL CREATE: <description>`.
"""

def template_targets(root: Path) -> dict[Path, str]:
    architecture_ref = architecture_path(root).relative_to(root.resolve()).as_posix()
    step_template = STEP_TEMPLATE.replace(
        "docs/architecture.md#relevant-section",
        f"{architecture_ref}#relevant-section",
    )
    return {
        task_directory(root) / "TEMPLATE.md": step_template,
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
    """Создать отсутствующие project-owned templates, не переписывая custom content."""
    changed: list[str] = []
    for path, expected in template_targets(root).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            continue
        path.write_text(expected, encoding="utf-8", newline="\n")
        changed.append(path.relative_to(root).as_posix())
    return changed


def _required_mapping_shape(expected: Any, actual: Any, *, prefix: str) -> list[str]:
    """Проверить наличие structural keys, не сравнивая project-owned values."""
    errors: list[str] = []
    if not isinstance(expected, dict):
        return errors
    if not isinstance(actual, dict):
        return [f"{prefix} must be a mapping"]
    for key, expected_value in expected.items():
        child = f"{prefix}.{key}" if prefix else key
        if key not in actual:
            errors.append(f"missing structural key {child}")
            continue
        errors.extend(
            _required_mapping_shape(
                expected_value,
                actual[key],
                prefix=child,
            )
        )
    return errors


def _validate_template_shape(path: Path, expected: str) -> list[str]:
    """Проверить текущую schema shape, сохранив custom prose/values проекта."""
    errors: list[str] = []
    try:
        actual_doc = parse_document(path)
    except (DocumentError, OSError, UnicodeDecodeError) as exc:
        return [str(exc)]

    # Expected definitions — protocol-owned constants этого release, поэтому
    # их parse failure является programmer error и не маскируется.
    expected_path = path.with_name(path.name + ".expected")
    try:
        expected_path.write_text(expected, encoding="utf-8", newline="\n")
        expected_doc = parse_document(expected_path)
    finally:
        expected_path.unlink(missing_ok=True)

    errors.extend(
        _required_mapping_shape(
            expected_doc["frontmatter"],
            actual_doc["frontmatter"],
            prefix="frontmatter",
        )
    )
    if actual_doc["frontmatter"].get("schema") != expected_doc["frontmatter"].get("schema"):
        errors.append(
            "frontmatter.schema differs from current template schema "
            f"{expected_doc['frontmatter'].get('schema')}"
        )
    expected_kind = expected_doc["frontmatter"].get("kind")
    if expected_kind is not None and actual_doc["frontmatter"].get("kind") != expected_kind:
        errors.append(f"frontmatter.kind must be {expected_kind}")

    for section in expected_doc["sections"]:
        if section not in actual_doc["sections"]:
            errors.append(f"missing structural section '## {section}'")
    return errors


def validate_project_templates(root: Path) -> list[str]:
    """До INIT нужен exact baseline; после INIT — compatible shape без overwrite."""
    errors: list[str] = []
    initialized = bool(get(load_manifest(root), "project.initialized", False))
    for path, expected in template_targets(root).items():
        if not path.is_file():
            errors.append(f"project template missing: {path.relative_to(root)}")
            continue
        if not initialized:
            if path.read_text(encoding="utf-8") != expected:
                errors.append(f"template baseline drift before PROJECT INIT: {path.relative_to(root)}")
            continue
        for issue in _validate_template_shape(path, expected):
            errors.append(f"project template incompatible: {path.relative_to(root)}: {issue}")
    return errors
