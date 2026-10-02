#!/usr/bin/env python3
"""Synthetic fixtures for deterministic traceability coverage."""
from __future__ import annotations
from pathlib import Path
import tempfile
from traceability_coverage import build_coverage

MANIFEST="""sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  openQuestions: docs/open-questions
protocol:
  taskDirectory: planning/tasks
"""

REQ=lambda rid,steps,priority="medium":f"""---
schema: 1
id: {rid}
priority: {priority}
source: brief
steps:{steps}
adrs: []
---

# {rid} — Requirement

## Requirement

Behavior.

## Rationale

Reason.

## Acceptance

- Observable.
"""

STEP=lambda sid,reqs,status="planned",stype="implementation",adrs=" []":f"""---
schema: 1
id: {sid}
status: {status}
type: {stype}
priority: medium
phase: P1
depends_on: []
requirements:{reqs}
adrs:{adrs}
architecture_refs: []
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

# {sid} — Step

## Goal

Goal.

## Context

Context.

## Scope

- scope

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

- done

## Verification

- manual: check

## Deliverables

- code

## Implementation plan

Not planned.

## Evidence

Pending.

## Blocker / Failure reason

—
"""

OQ="""---
schema: 1
id: OQ-001
status: open
affects:
  - REQ-002
created_at: 2026-01-01T00:00:00Z
resolved_at: null
---

# OQ-001 — Question

## Context

Context.

## Decision needed

Decision.

## Resolution

Pending.
"""

def main()->int:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/".harness").mkdir()
        (root/".harness"/"manifest.yaml").write_text(MANIFEST,encoding="utf-8")
        for d in ("docs/requirements","docs/adr","docs/open-questions","planning/tasks"):
            (root/d).mkdir(parents=True,exist_ok=True)
        (root/"docs/requirements/REQ-001-a.md").write_text(REQ("REQ-001","\n  - STEP-001"),encoding="utf-8")
        (root/"docs/requirements/REQ-002-b.md").write_text(REQ("REQ-002"," []","high"),encoding="utf-8")
        (root/"planning/tasks/STEP-001.md").write_text(STEP("STEP-001","\n  - REQ-001",status="completed"),encoding="utf-8")
        (root/"planning/tasks/STEP-002.md").write_text(STEP("STEP-002"," []"),encoding="utf-8")
        (root/"planning/tasks/STEP-003.md").write_text(STEP("STEP-003"," []",stype="research"),encoding="utf-8")
        (root/"docs/open-questions/OQ-001-gap.md").write_text(OQ,encoding="utf-8")

        def proof(_root:Path,step_id:str):
            return {"complete":step_id=="STEP-001","reasons":[] if step_id=="STEP-001" else ["incomplete"]}

        result=build_coverage(root,completion_provider=proof)
        by_id={x["id"]:x for x in result["requirements"]}
        assert by_id["REQ-001"]["status"]=="verified"
        assert by_id["REQ-002"]["status"]=="uncovered"
        assert result["metrics"]["verified"]==1
        assert result["metrics"]["uncovered"]==1
        assert [x["stepId"] for x in result["orphanSteps"]]==["STEP-002"]
        assert all(x["stepId"]!="STEP-003" for x in result["orphanSteps"])
        assert result["blockingOpenQuestions"][0]["id"]=="OQ-001"

        # Broken explicit link changes output deterministically.
        (root/"planning/tasks/STEP-001.md").write_text(STEP("STEP-001","\n  - REQ-999",status="completed"),encoding="utf-8")
        broken=build_coverage(root,completion_provider=proof)
        assert any(x["code"]=="UNKNOWN_REQ_REFERENCE" for x in broken["invalidReferences"])
    print("traceability-coverage self-test: PASS")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
