#!/usr/bin/env python3
"""Regression suite generic deterministic progress guard (#204)."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

from execution_status import (
    ProgressExecutionError,
    begin_command,
    load_status,
    start_execution,
)
from progress_guard import (
    MAX_PROGRESS_SAMPLES,
    capture_progress,
    compare_progress,
    new_telemetry,
    observe_resume,
    observe_transition,
)


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise AssertionError(f"{' '.join(args)} failed: {proc.stderr}")


def manifest() -> str:
    return """execution:
  maxFixReviewCycles: 3
review:
  security: auto
  tests: auto
sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  architecture: docs/architecture.md
  openQuestions: docs/open-questions
  openQuestionsIndex: docs/OPEN_QUESTIONS.md
  roadmap: planning/PLAN.md
  status: planning/STATUS.md
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
  planningReviewDirectory: planning/plan-reviews
  initReviewDirectory: planning/init-reviews
  auditDirectory: planning/audits
  releaseDirectory: planning/releases
  skillSearchDirectory: planning/skill-searches
repository:
  gitPolicy: .harness/git-policy.toml
  harnessUpdatePolicy: .harness/harness-update.toml
"""


def requirement() -> str:
    return """---
schema: 1
id: REQ-001
priority: medium
source: progress-guard-self-test
steps:
  - STEP-001
adrs: []
---

# REQ-001 — Progress guard

## Requirement

Long-running execution detects deterministic traps.

## Rationale

Repeated model activity is not proof of progress.

## Acceptance

- Stagnation is bounded.
"""


def task(evidence: str = "—", group_path: str = "src/core") -> str:
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
  status: draft
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
  execution_groups:
    core:
      title: Core work
      steps:
        - 1
      dependsOn: []
      mutationPaths:
        - {group_path}
      verificationResponsibilities:
        - Verify core behavior
      parallel: false
---

# STEP-001 — Progress guard fixture

## Goal

Exercise progress guard.

## Context

Synthetic fixture.

## Scope

- Deterministic progress telemetry.

## Mutation policy

### Allowed

- fixture.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- production behavior.

## Acceptance criteria

- Repeated no-op resume is bounded.
- Repository activity alone does not imply semantic completion.

## Verification

- progress-guard-self-test.py.

## Deliverables

- Deterministic guard.

## Implementation plan

### 1. Core

Implement guard.

## Evidence

{evidence}

## Blocker / Failure reason

—
"""


def prepare(root: Path) -> None:
    write(root / ".harness/manifest.yaml", manifest())
    write(root / ".harness/git-policy.toml", '[push]\nremote = "origin"\n')
    write(
        root / ".harness/harness-update.toml",
        '[state]\nreport_directory = "planning/harness-updates"\n',
    )
    shutil.copy2(
        SOURCE_ROOT / ".harness/command-transitions.json",
        root / ".harness/command-transitions.json",
    )
    write(root / "docs/requirements/REQ-001-progress.md", requirement())
    write(root / "docs/architecture.md", "# Architecture\n")
    write(root / "planning/tasks/STEP-001.md", task())
    write(root / "src/core/placeholder.txt", "initial\n")
    run(root, "git", "init", "-q")
    run(root, "git", "config", "user.email", "harness-test@example.invalid")
    run(root, "git", "config", "user.name", "Harness Test")
    write(root / ".gitignore", ".harness/local/\n")
    run(root, "git", "add", ".")
    run(root, "git", "commit", "-qm", "fixture")


def synthetic(
    fingerprint: str,
    *,
    operation: str,
    command: str,
    step_status: str = "in_progress",
    reasons: int = 2,
    precheck: int = 2,
    verification: str = "FAIL",
    evidence: str = "sha256:a",
    activity: str = "activity-a",
) -> dict:
    return {
        "schemaVersion": 1,
        "stepId": "STEP-001",
        "command": command,
        "operation": operation,
        "materialFingerprint": fingerprint,
        "activityFingerprint": activity,
        "fingerprint": f"{fingerprint}:{activity}",
        "metrics": {
            "stepStatus": step_status,
            "completionComplete": False,
            "completionReasonCount": reasons,
            "completionPrecheckFindingCount": precheck,
            "reviewFindingCount": 0,
            "completionFindingCount": 0,
            "verificationStatus": verification,
            "evidenceHash": evidence,
            "executionGroupsHash": "sha256:group",
        },
        "capturedAt": "2026-10-05T00:00:00+00:00",
    }


def policy_tests() -> None:
    base = synthetic(
        "material-a",
        operation="IMPLEMENT",
        command="STEP IMPLEMENT STEP-001",
    )
    same = dict(base)
    no_change = compare_progress(base, same)
    assert no_change["classification"] == "NO_CHANGE", no_change

    activity = synthetic(
        "material-a",
        operation="IMPLEMENT",
        command="STEP IMPLEMENT STEP-001",
        activity="activity-b",
    )
    activity_delta = compare_progress(base, activity)
    assert activity_delta["classification"] == "ACTIVITY_ONLY", activity_delta

    progressed = synthetic(
        "material-b",
        operation="IMPLEMENT",
        command="STEP IMPLEMENT STEP-001",
        reasons=1,
        precheck=1,
        verification="PASS",
        evidence="sha256:b",
        activity="activity-b",
    )
    progress_delta = compare_progress(base, progressed)
    assert progress_delta["classification"] == "PROGRESS", progress_delta
    assert "verification" in progress_delta["improvements"], progress_delta

    # Repeated exact no-op resume is bounded.
    telemetry = new_telemetry(base)
    first = observe_resume(telemetry, same)
    assert first["blocker"] is None, first
    second = observe_resume(first["telemetry"], same)
    assert second["blocker"]["reasonCode"] == "EXECUTION_STAGNATION", second

    # Activity-only changes reset stagnation: long IMPLEMENT may mutate code
    # several times before acceptance/evidence becomes observable.
    active = observe_resume(telemetry, activity)
    assert active["blocker"] is None, active
    assert active["telemetry"]["unchangedResumes"] == 0, active

    # Exact A -> B -> A authoritative state is a bounded cycle.
    plan_a = synthetic(
        "material-a",
        operation="PLAN",
        command="STEP PLAN STEP-001",
    )
    implement_b = synthetic(
        "material-b",
        operation="IMPLEMENT",
        command="STEP IMPLEMENT STEP-001",
        activity="activity-b",
    )
    cycle_a = synthetic(
        "material-a",
        operation="PLAN",
        command="STEP PLAN STEP-001",
    )
    telemetry = new_telemetry(plan_a)
    step_b = observe_transition(telemetry, implement_b)
    cycle = observe_transition(step_b["telemetry"], cycle_a)
    assert cycle["blocker"]["reasonCode"] == "EXECUTION_CYCLE", cycle

    # REVIEW/FIX policy remains owned by #153.
    review_a = synthetic(
        "repair-a",
        operation="REVIEW",
        command="STEP REVIEW STEP-001",
    )
    fix_a = synthetic(
        "repair-a",
        operation="FIX",
        command="STEP FIX STEP-001",
    )
    repair = new_telemetry(review_a)
    repair = observe_transition(repair, fix_a, suppress_stop=True)["telemetry"]
    repair_result = observe_transition(repair, review_a, suppress_stop=True)
    assert repair_result["blocker"] is None, repair_result

    # Two consecutive factual worsening deltas classify deterministic drift.
    drift0 = synthetic(
        "d0",
        operation="IMPLEMENT",
        command="STEP IMPLEMENT STEP-001",
        reasons=1,
        precheck=1,
        verification="PASS",
    )
    drift1 = synthetic(
        "d1",
        operation="IMPLEMENT",
        command="STEP IMPLEMENT STEP-001",
        reasons=2,
        precheck=2,
        verification="FAIL",
        activity="activity-b",
    )
    drift2 = synthetic(
        "d2",
        operation="IMPLEMENT",
        command="STEP IMPLEMENT STEP-001",
        reasons=3,
        precheck=3,
        verification="BLOCKED",
        activity="activity-c",
    )
    drift = new_telemetry(drift0)
    one = observe_resume(drift, drift1)
    assert one["blocker"] is None, one
    two = observe_resume(one["telemetry"], drift2)
    assert two["blocker"]["reasonCode"] == "EXECUTION_DRIFT", two

    assert len(two["telemetry"]["samples"]) <= MAX_PROGRESS_SAMPLES, two


def integration_tests(root: Path) -> None:
    # executionGroups are part of the canonical progress material.
    sample = capture_progress(
        root,
        "STEP-001",
        "STEP PLAN STEP-001",
        "PLAN",
    )
    assert sample["metrics"]["executionGroupsHash"], sample

    changed_task = task(group_path="src/other")
    write(root / "planning/tasks/STEP-001.md", changed_task)
    changed = capture_progress(
        root,
        "STEP-001",
        "STEP PLAN STEP-001",
        "PLAN",
    )
    assert (
        changed["metrics"]["executionGroupsHash"]
        != sample["metrics"]["executionGroupsHash"]
    ), (sample, changed)
    write(root / "planning/tasks/STEP-001.md", task())

    # Real execution: first no-op resume is tolerated, second is stagnation.
    execution = start_execution(root, "STEP PLAN STEP-001")
    assert execution["progressTelemetry"]["samples"], execution
    first = begin_command(
        root,
        execution["rootCommand"],
        execution["current"]["command"],
    )
    assert first["progressTelemetry"]["unchangedResumes"] == 1, first
    try:
        begin_command(
            root,
            execution["rootCommand"],
            execution["current"]["command"],
        )
    except ProgressExecutionError as exc:
        assert exc.code == "EXECUTION_STAGNATION", exc
        assert exc.details["unchangedAttempts"] == 2, exc.details
    else:
        raise AssertionError("second no-op resume unexpectedly succeeded")

    state = load_status(root)
    blocked = state["executions"][0]
    assert blocked["status"] == "blocked", blocked
    assert blocked["blockedBy"]["reasonCode"] == "EXECUTION_STAGNATION", blocked

    # New root after the blocked invocation: repository activity alone must not
    # be mistaken for stagnation.
    execution = start_execution(root, "STEP PLAN STEP-001")
    begin_command(root, execution["rootCommand"], execution["current"]["command"])
    write(root / "src/core/placeholder.txt", "changed product work\n")
    active = begin_command(
        root,
        execution["rootCommand"],
        execution["current"]["command"],
    )
    assert active["status"] == "running", active
    assert active["progressTelemetry"]["unchangedResumes"] == 0, active
    assert (
        active["progressTelemetry"]["lastDelta"]["classification"]
        == "ACTIVITY_ONLY"
    ), active["progressTelemetry"]

    # Material Evidence progress also resets the no-op streak.
    write(root / "planning/tasks/STEP-001.md", task(evidence="progress proof"))
    progressed = begin_command(
        root,
        execution["rootCommand"],
        execution["current"]["command"],
    )
    assert progressed["status"] == "running", progressed
    assert progressed["progressTelemetry"]["unchangedResumes"] == 0, progressed
    assert (
        progressed["progressTelemetry"]["lastDelta"]["classification"]
        == "PROGRESS"
    ), progressed["progressTelemetry"]


def main() -> int:
    policy_tests()
    with tempfile.TemporaryDirectory(prefix="harness-progress-guard-") as tmp:
        root = Path(tmp)
        prepare(root)
        integration_tests(root)
    print("PROGRESS GUARD SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
