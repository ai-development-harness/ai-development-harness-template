#!/usr/bin/env python3
"""Regression self-test crash-safe Execution Status on schema-v1 contracts."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from execution_status import (
    begin_command,
    block_execution,
    complete_command,
    load_status,
    resolve_root,
    stamp_plan,
    start_execution,
    unresolved_executions,
)
from planning_contract import plan_content_hash, planning_context_basis
from review_contract import repository_revision


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(args, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise AssertionError(f"{' '.join(args)} failed: {proc.stderr}")


def manifest() -> str:
    return """execution:
  maxFixReviewCycles: 1
review:
  security: auto
  tests: auto
sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  architecture: docs/architecture.md
  openQuestions: docs/open-questions
  openQuestionsIndex: docs/OPEN_QUESTIONS.md
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
  planningReviewDirectory: planning/plan-reviews
  initReviewDirectory: planning/init-reviews
"""


def requirement() -> str:
    return """---
schema: 1
id: REQ-001
priority: medium
source: self_test
steps:
  - STEP-001
adrs: []
---

# REQ-001 — Execution state

## Requirement

Execution state работает детерминированно.

## Rationale

Self-test.

## Acceptance

- Recovery воспроизводим.
"""


def task(plan_status: str = "draft", basis: str | None = None, phash: str | None = None, report: str | None = None) -> str:
    def val(value: str | None) -> str:
        return "null" if value is None else value
    return f"""---
schema: 1
id: STEP-001
status: planned
type: implementation
priority: medium
phase: test
depends_on: []
requirements:
  - REQ-001
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: {plan_status}
  revision: {1 if plan_status == "ready" else 0}
  context_basis: {val(basis)}
  content_hash: {val(phash)}
  reviewed_report: {val(report)}
  planned_at: {"2026-09-21T00:00:00+00:00" if plan_status == "ready" else "null"}
review:
  latest_verdict: not_reviewed
  latest_report: null
---

# STEP-001 — Execution state test

## Goal

Проверить execution status.

## Context

Self-test.

## Scope

- fixture.

## Mutation policy

### Allowed

- fixture.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- unrelated.

## Acceptance criteria

- recovery deterministic.

## Verification

- execution-self-test.py.

## Deliverables

- fixture.

## Implementation plan

1. Execute fixture.
2. Review exact revision.

## Evidence

—

## Blocker / Failure reason

—
"""


def planning_review(basis: str, phash: str) -> str:
    return f"""---
schema: 1
kind: planning_review
step_id: STEP-001
verdict: pass
reviewer_role: planner
context_basis: {basis}
plan_content_hash: {phash}
created_at: 2026-09-21T00:00:00+00:00
---

# Planning Review STEP-001 — self-test

## Scope checked

Contract and plan.

## Findings

No material findings.

## Verdict rationale

PASS.
"""


def review_report(root: Path, verdict: str, name: str) -> str:
    revision = repository_revision(root)
    if verdict == "FAIL":
        findings = """### F-001 — Fixture defect

**Severity:** high
**Category:** implementation
**Location:** fixture
**Scenario:** Given fixture / When reviewed / Then defect is found
**Impact:** acceptance is not proven
**Fix direction:** fix fixture
"""
    else:
        findings = "No material findings.\n"
    rel = f"planning/reviews/STEP-001/{name}"
    write(
        root / rel,
        f"""---
schema: 1
kind: step_review
step_id: STEP-001
verdict: {verdict.lower()}
reviewer_role: reviewer
created_at: 2026-09-21T00:00:00+00:00
reviewed_revision:
  git_head: {revision["git_head"] or "null"}
  worktree_hash: {revision["worktree_hash"] or "null"}
specialized_reviews:
  security: not_required
  security_report: null
  security_reason: no_security_surface
  tests: pass
  tests_report: tests/self-test
  tests_reason: implementation_step
---

# STEP REVIEW STEP-001 — self-test

## Scope checked

Exact fixture revision.

## Findings

{findings}
## Verification observations

Self-test verification.

## Verdict rationale

{verdict}.
""",
    )
    return rel


def assert_resolved(value: dict, status: str, command: str | None, reason: str) -> None:
    assert value["status"] == status, value
    assert value.get("command") == command, value
    assert value["reasonCode"] == reason, value


def main() -> int:
    source = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="harness-execution-v1-") as tmp:
        root = Path(tmp)
        write(root / ".harness/manifest.yaml", manifest())
        shutil.copy2(source / ".harness/command-transitions.json", root / ".harness/command-transitions.json")
        write(root / "docs/requirements/REQ-001-execution.md", requirement())
        write(root / "docs/architecture.md", "# Architecture\n")
        write(root / "planning/tasks/STEP-001.md", task())

        run(root, "git", "init", "-q")
        run(root, "git", "config", "user.email", "harness-test@example.invalid")
        run(root, "git", "config", "user.name", "Harness Test")
        write(root / ".gitignore", ".harness/local/\n")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "fixture")

        # Create durable planning-review matching the draft plan, then stamp Ready.
        basis = planning_context_basis(root, "STEP-001")
        phash = plan_content_hash(root, "STEP-001")
        plan_report = "planning/plan-reviews/STEP-001/PLAN-REVIEW-20260921T000000Z.md"
        write(root / plan_report, planning_review(basis, phash))
        stamped = stamp_plan(root, "STEP-001")
        assert stamped["planStatus"] == "ready", stamped

        # Independent commands coexist and invalid reverse chains never create state.
        first = start_execution(root, "PROJECT STATUS")
        complete_command(root, first["rootCommand"], "PROJECT STATUS", "SUCCESS")
        before = len(load_status(root)["executions"])
        try:
            start_execution(root, "GIT PR > COMMIT")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid reverse Git chain accepted")
        assert len(load_status(root)["executions"]) == before

        # Explicit chain advances only on allowed previous result.
        chain = "GIT CHECK > COMMIT > PUSH > PR"
        execution = start_execution(root, chain)
        complete_command(root, chain, "GIT CHECK", "PASS")
        assert_resolved(resolve_root(root, chain), "NEXT", "GIT COMMIT", "CHAIN_NEXT_SEGMENT")
        begin_command(root, chain, "GIT COMMIT")
        complete_command(root, chain, "GIT COMMIT", "SUCCESS")
        assert resolve_root(root, chain)["command"] == "GIT PUSH"

        # STEP RUN recovers completed PLAN from matching basis+content+planning-review.
        run_root = "STEP RUN STEP-001"
        run_exec = start_execution(root, run_root)
        begin_command(root, run_root, "STEP PLAN STEP-001")
        assert_resolved(
            resolve_root(root, run_root),
            "NEXT",
            "STEP IMPLEMENT STEP-001",
            "ORCHESTRATION_CTS_TRANSITION",
        )

        begin_command(root, run_root, "STEP IMPLEMENT STEP-001")
        assert_resolved(
            resolve_root(root, run_root),
            "RESUME",
            "STEP IMPLEMENT STEP-001",
            "COMMAND_INTERRUPTED",
        )
        # An unrelated execution must not overwrite interrupted orchestration.
        overlay = start_execution(root, "GIT CHECK")
        complete_command(root, overlay["rootCommand"], "GIT CHECK", "PASS")
        assert resolve_root(root, run_root)["command"] == "STEP IMPLEMENT STEP-001"
        assert any(item["executionId"] == run_exec["executionId"] for item in unresolved_executions(root))

        # REVIEW crash recovery trusts only valid report for exact revision.
        complete_command(root, run_root, "STEP IMPLEMENT STEP-001", "SUCCESS")
        begin_command(root, run_root, "STEP REVIEW STEP-001")
        review_report(root, "FAIL", "REVIEW-20260921T010000Z.md")
        recovered = resolve_root(root, run_root)
        assert_resolved(recovered, "NEXT", "STEP FIX STEP-001", "ORCHESTRATION_CTS_TRANSITION")

        begin_command(root, run_root, "STEP FIX STEP-001")
        complete_command(root, run_root, "STEP FIX STEP-001", "SUCCESS")
        begin_command(root, run_root, "STEP REVIEW STEP-001")
        review_report(root, "PASS", "REVIEW-20260921T020000Z.md")
        assert_resolved(
            resolve_root(root, run_root),
            "RESUME",
            "STEP RUN STEP-001",
            "ORCHESTRATION_CONTINUE",
        )

        # Exact revision invalidation: product mutation after report prevents recovery.
        other_root = "STEP RUN STEP-001"
        existing = resolve_root(root, run_root)
        if existing["status"] == "RESUME":
            begin_command(root, run_root, "STEP RUN STEP-001")
            complete_command(root, run_root, "STEP RUN STEP-001", "SUCCESS")
        second = start_execution(root, other_root)
        begin_command(root, other_root, "STEP IMPLEMENT STEP-001")
        complete_command(root, other_root, "STEP IMPLEMENT STEP-001", "SUCCESS")
        begin_command(root, other_root, "STEP REVIEW STEP-001")
        review_report(root, "PASS", "REVIEW-20260921T030000Z.md")
        write(root / "src/product.txt", "changed after review\n")
        unresolved = resolve_root(root, other_root)
        assert unresolved["status"] == "RESUME" and unresolved["command"] == "STEP REVIEW STEP-001", unresolved

        # maxFixReviewCycles=1 blocks a second FAIL after one successful FIX→REVIEW cycle.
        # Finish current review explicitly so a clean independent RUN can start.
        complete_command(root, other_root, "STEP REVIEW STEP-001", "PASS")
        begin_command(root, other_root, "STEP RUN STEP-001")
        complete_command(root, other_root, "STEP RUN STEP-001", "SUCCESS")

        limited = start_execution(root, run_root)
        begin_command(root, run_root, "STEP IMPLEMENT STEP-001")
        complete_command(root, run_root, "STEP IMPLEMENT STEP-001", "SUCCESS")
        begin_command(root, run_root, "STEP REVIEW STEP-001")
        complete_command(root, run_root, "STEP REVIEW STEP-001", "FAIL")
        assert resolve_root(root, run_root)["command"] == "STEP FIX STEP-001"
        begin_command(root, run_root, "STEP FIX STEP-001")
        complete_command(root, run_root, "STEP FIX STEP-001", "SUCCESS")
        begin_command(root, run_root, "STEP REVIEW STEP-001")
        complete_command(root, run_root, "STEP REVIEW STEP-001", "FAIL")
        exhausted = resolve_root(root, run_root)
        assert_resolved(exhausted, "BLOCKED", None, "FIX_REVIEW_LIMIT_REACHED")
        assert exhausted["fixReviewCycles"] == 1
        blocked = block_execution(root, run_root, command="STEP REVIEW STEP-001")
        assert blocked["current"]["result"] == "FAIL"

        # One fixed project-level state file, no per-STEP JSON.
        fixed = root / ".harness/local/execution/execution-status.json"
        assert fixed.is_file()
        assert not list((root / ".harness/local/execution").glob("STEP-*.json"))

    print("EXECUTION STATUS SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
