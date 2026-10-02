#!/usr/bin/env python3
"""Synthetic regressions for role-specific Context Contracts."""
from __future__ import annotations
from pathlib import Path
import tempfile

from context_contracts import ContextContractError, build_context_contract, validate_expansion

MANIFEST="""sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  architecture: docs/architecture.md
  openQuestions: docs/open-questions
protocol:
  taskDirectory: planning/tasks
"""

STEP="""---
schema: 1
id: STEP-001
status: planned
type: implementation
priority: medium
phase: P1
depends_on:
  - STEP-000
requirements:
  - REQ-001
adrs:
  - ADR-001
architecture_refs:
  - docs/architecture.md#api
risk_flags:
  - public-api
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-001 — Test

## Goal

Goal.

## Context

Context.

## Scope

- work

## Mutation policy

### Allowed

- src

### Conditional

- none

### Forbidden

- unrelated

## Out of scope

- unrelated

## Acceptance criteria

- works

## Verification

- manual: check

## Deliverables

- code

## Implementation plan

Plan.

## Evidence

Evidence.

## Blocker / Failure reason

—
"""
DEP=STEP.replace("STEP-001","STEP-000").replace("depends_on:\n  - STEP-000","depends_on: []").replace("requirements:\n  - REQ-001","requirements: []").replace("adrs:\n  - ADR-001","adrs: []").replace("architecture_refs:\n  - docs/architecture.md#api","architecture_refs: []")
REQ="""---
schema: 1
id: REQ-001
priority: high
source: brief
steps:
  - STEP-001
adrs:
  - ADR-001
---

# REQ-001 — R

## Requirement

Behavior.

## Rationale

Reason.

## Acceptance

- observable
"""
ADR="""---
schema: 1
id: ADR-001
status: accepted
date: 2026-01-01
deciders: []
supersedes: []
superseded_by: []
requirements:
  - REQ-001
steps:
  - STEP-001
---

# ADR-001 — A

## Context

C.

## Problem

P.

## Decision

D.

## Alternatives considered

A.

## Consequences

C.

## Security implications

None.

## Data / migration implications

None.

## Compatibility / operational implications

None.
"""

def main()->int:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/".harness").mkdir()
        (root/".harness"/"manifest.yaml").write_text(MANIFEST,encoding="utf-8")
        for d in ("docs/requirements","docs/adr","docs/open-questions","planning/tasks","src"):
            (root/d).mkdir(parents=True,exist_ok=True)
        (root/"planning/tasks/STEP-001.md").write_text(STEP,encoding="utf-8")
        (root/"planning/tasks/STEP-000.md").write_text(DEP,encoding="utf-8")
        (root/"docs/requirements/REQ-001-r.md").write_text(REQ,encoding="utf-8")
        (root/"docs/adr/ADR-001-a.md").write_text(ADR,encoding="utf-8")
        (root/"docs/architecture.md").write_text("# Architecture\n\n## API\n\nContract.\n",encoding="utf-8")
        (root/"docs/unrelated.md").write_text("noise",encoding="utf-8")
        (root/"src/extra.ts").write_text("export {}",encoding="utf-8")
        (root/".harness"/"tools").mkdir()
        (root/".harness"/"tools"/"secret.py").write_text("internal",encoding="utf-8")

        planner=build_context_contract(root,"STEP-001","planner")
        reviewer=build_context_contract(root,"STEP-001","reviewer")
        assert planner["role"]=="planner" and reviewer["role"]=="reviewer"
        assert planner["metrics"]["fullRepositoryPreload"] is False
        paths={x["path"] for x in planner["required"]}
        assert "docs/unrelated.md" not in paths
        step_item=next(x for x in planner["required"] if x["artifact"]=="STEP-001")
        review_item=next(x for x in reviewer["required"] if x["artifact"]=="STEP-001")
        assert "Context" in step_item["sections"]
        assert "Evidence" not in step_item["sections"]
        assert "Evidence" in review_item["sections"]

        expanded=validate_expansion(root,"src/extra.ts","integration implementation detail required")
        assert expanded["status"]=="PASS"
        try:
            validate_expansion(root,".harness/tools/secret.py","inspect implementation")
        except ContextContractError:
            pass
        else:
            raise AssertionError("tool source expansion must be blocked")
        try:
            validate_expansion(root,"src/extra.ts","")
        except ContextContractError:
            pass
        else:
            raise AssertionError("expansion without reason must be blocked")
    print("context-contract self-test: PASS")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
