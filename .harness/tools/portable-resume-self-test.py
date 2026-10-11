#!/usr/bin/env python3
"""#301: отрицательные проверки безопасного portable adoption.

Это unit-boundary проверки. Реальные два Git clone и все race scenarios
остаются отдельным обязательным этапом #302.
"""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import tempfile
from unittest.mock import patch

from execution_status import ExecutionCheckpointError, empty_status, load_status, start_execution
from planning_contract import planning_context_basis, plan_content_hash, latest_matching_planning_review
from portable_handoff import write_handoff
from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts
from portable_resume import portable_resume_candidate
from harness_ux import harness_resume


ROOT = Path("/unused/repository")


def _preview(*, count: int = 1, fresh: bool = True) -> dict:
    return {
        "status": "PASS",
        "candidates": [
            {"stepId": f"STEP-{i:03d}", "planFreshness": "fresh" if fresh else "stale",
             "reasonCode": "PLAN_BASIS_STALE"}
            for i in range(1, count + 1)
        ],
    }


def _proof() -> dict:
    return {"status": "PASS", "path": "planning/handoffs/STEP-001.json"}


def test_portable_gate() -> None:
    empty = {"executions": [], "recentTerminals": [], "stepRecovery": {}}
    with (
        patch("portable_resume.load_status", return_value=empty),
        patch("portable_resume.repository_recovery_preview", return_value=_preview()),
        patch("portable_resume.check_handoff", return_value=_proof()),
    ):
        result = portable_resume_candidate(ROOT)
        assert result["status"] == "PASS"
        assert result["portable"] is True
        assert result["command"] == "STEP PLAN STEP-001"
        assert "executionId" not in result

    for field, occupied in (
        ("executions", [{"executionId": "old"}]),
        ("recentTerminals", [{"executionId": "old"}]),
        ("stepRecovery", {"STEP-001": {"old": True}}),
    ):
        state = {**empty, field: occupied}
        with patch("portable_resume.load_status", return_value=state):
            assert portable_resume_candidate(ROOT)["reasonCode"] == "PORTABLE_LOCAL_HISTORY_PRESENT"

    with (
        patch("portable_resume.load_status", return_value=empty),
        patch("portable_resume.repository_recovery_preview", return_value=_preview(count=2)),
    ):
        assert portable_resume_candidate(ROOT)["reasonCode"] == "PORTABLE_CANDIDATES_AMBIGUOUS"

    with (
        patch("portable_resume.load_status", return_value=empty),
        patch("portable_resume.repository_recovery_preview", return_value=_preview(fresh=False)),
        patch("portable_resume.check_handoff", return_value=_proof()),
    ):
        assert portable_resume_candidate(ROOT)["reasonCode"] == "PLAN_BASIS_STALE"

    with (
        patch("portable_resume.load_status", return_value=empty),
        patch("portable_resume.repository_recovery_preview", return_value=_preview()),
        patch("portable_resume.check_handoff", return_value={"status": "BLOCKED", "reasonCode": "HANDOFF_STEP_CHANGED"}),
    ):
        assert portable_resume_candidate(ROOT)["reasonCode"] == "HANDOFF_STEP_CHANGED"

    with patch("portable_resume.load_status", side_effect=ExecutionCheckpointError("UNAVAILABLE", "lost marker")):
        try:
            portable_resume_candidate(ROOT)
        except ExecutionCheckpointError:
            pass
        else:
            raise AssertionError("Lost local checkpoint must not fall back to portable")


def test_local_precedence() -> None:
    local = {
        "status": "RESUME",
        "rootCommand": "STEP RUN STEP-009",
        "command": "STEP IMPLEMENT STEP-009",
        "executionId": "exec-local",
    }
    with (
        patch("harness_ux.unresolved_executions", return_value=[local]),
        patch("harness_ux.portable_resume_candidate", side_effect=AssertionError("portable must not run")),
    ):
        decision = harness_resume(ROOT)
        assert decision["executionId"] == "exec-local"
        assert decision["instruction"] == "resume-existing-execution-without-starting-new-root"

    # Уже завершённые локальные executions не actionable, но являются
    # частью истории. Старый API возвращает NO_RESUMABLE_EXECUTION с executions=[].
    for reason in ("PORTABLE_LOCAL_HISTORY_PRESENT", "NO_RESUMABLE_EXECUTION"):
        with (
            patch("harness_ux.unresolved_executions", return_value=[]),
            patch("harness_ux.portable_resume_candidate", return_value={
                "status": "BLOCKED", "reasonCode": reason,
            }),
        ):
            assert harness_resume(ROOT) == {
                "status": "BLOCKED",
                "reasonCode": "NO_RESUMABLE_EXECUTION",
                "executions": [],
            }

    # Локальный blocker не должен превращаться в portable fallback.
    with (
        patch("harness_ux.unresolved_executions", return_value=[
            {"status": "BLOCKED", "reasonCode": "COMMAND_BLOCKED"}
        ]),
        patch("harness_ux.portable_resume_candidate",
              side_effect=AssertionError("blocked local history must not use portable")),
    ):
        assert harness_resume(ROOT)["reasonCode"] == "NO_RESUMABLE_EXECUTION"

    with (
        patch("harness_ux.unresolved_executions", return_value=[]),
        patch("harness_ux.portable_resume_candidate", return_value={
            "status": "PASS", "portable": True, "command": "STEP PLAN STEP-001",
        }),
    ):
        assert harness_resume(ROOT)["portable"] is True



def test_dispatch_creates_new_local_plan() -> None:
    from command_dispatch import resume_dispatch
    decision = {
        "status": "PASS",
        "portable": True,
        "rootCommand": "STEP PLAN STEP-001",
        "command": "STEP PLAN STEP-001",
        "sourceHandoff": "planning/handoffs/STEP-001.json",
    }
    started = {
        "status": "SEMANTIC",
        "executionId": "exec-new-local",
        "command": "STEP PLAN STEP-001",
    }
    with (
        patch("command_dispatch.harness_resume", return_value=decision),
        patch("command_dispatch.start_dispatch", return_value=started) as start,
        patch("command_dispatch.portable_resume_candidate", return_value=decision),
        patch("command_dispatch.resolve_root", side_effect=AssertionError("must not resume source execution")),
    ):
        result = resume_dispatch(ROOT)
        start.assert_called_once_with(ROOT, "STEP PLAN STEP-001", require_fresh_clone=True)
        assert result["executionId"] == "exec-new-local"
        assert result["portableAdoption"]["importedExecution"] is False
        assert result["portableAdoption"]["externalSideEffectsExecuted"] is False



def _git(root: Path, *args: str) -> str:
    """Запустить настоящий Git в isolated fixture, без доступа к сети."""
    done = subprocess.run(
        ("git", *args), cwd=root, text=True, encoding="utf-8",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45, check=False,
    )
    assert done.returncode == 0, (args, done.stdout, done.stderr)
    return done.stdout.strip()


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _task() -> str:
    """Минимальный реальный STEP с draft-планом (без forged runtime proofs)."""
    return """---
schema: 1
id: STEP-017
status: in_progress
type: implementation
priority: high
phase: backend
depends_on: []
requirements: []
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
---

# STEP-017 — Portable resume integration

## Goal

- Continue published work without copying local execution state.

## Context

- Two independent Git clones share one canonical STEP.

## Scope

- Inspect the published implementation before further mutation.

## Mutation policy

### Allowed

- src/

### Conditional

- none

### Forbidden

- unrelated files

## Out of scope

- Replay of Git side effects.

## Acceptance criteria

- New clone receives a new local planning execution only.

## Verification

- manual: verify published implementation

## Deliverables

- Git-backed STEP.

## Implementation plan

1. Inspect the published code and task.
2. Verify current acceptance against the repository.

## Evidence

—

## Blocker / Failure reason

—
"""


def _prepare_ready_step(root: Path) -> None:
    """Сформировать настоящий Ready plan и immutable independent PLAN-REVIEW."""
    path = root / "planning/tasks/STEP-017.md"
    draft = _task()
    _write(path, draft)
    basis = planning_context_basis(root, "STEP-017")
    content_hash = plan_content_hash(root, "STEP-017")
    review = "planning/plan-reviews/STEP-017/PLAN-REVIEW-20261011T000000Z.md"
    _write(root / review, f"""---
schema: 1
kind: planning_review
step_id: STEP-017
verdict: pass
reviewer_role: reviewer
finding_count: 0
context_basis: {basis}
plan_content_hash: {content_hash}
created_at: 2026-10-11T00:00:00Z
---

# Planning Review STEP-017 — integration fixture

## Scope checked

Published STEP and implementation plan.

## Findings

No material findings.

## Verdict rationale

Plan is consistent with canonical task.
""")
    ready = draft.replace("  status: draft", "  status: ready", 1)
    ready = ready.replace("  revision: 0", "  revision: 1", 1)
    ready = ready.replace("  context_basis: null", f"  context_basis: {basis}", 1)
    ready = ready.replace("  content_hash: null", f"  content_hash: {content_hash}", 1)
    ready = ready.replace("  reviewed_report: null", f"  reviewed_report: {review}", 1)
    ready = ready.replace("  planned_at: null", "  planned_at: 2026-10-11T00:00:00+00:00", 1)
    _write(path, ready)
    assert latest_matching_planning_review(root, "STEP-017") is not None


def test_two_clone_real_dispatch() -> None:
    """Positive path: Git publish -> clone -> real HARNESS RESUME dispatcher."""
    from command_dispatch import start_dispatch

    with tempfile.TemporaryDirectory(prefix="portable-resume-integration-") as temp:
        root = Path(temp)
        desktop, laptop, origin = root / "desktop", root / "laptop", root / "origin.git"
        desktop.mkdir()
        copy_effective_harness_checkout(Path(__file__).resolve().parents[2], desktop)
        isolate_project_artifacts(desktop)
        manifest = desktop / ".harness/manifest.yaml"
        original = manifest.read_text(encoding="utf-8")
        assert "initialized: false" in original
        _write(manifest, original.replace("initialized: false", "initialized: true", 1))
        _prepare_ready_step(desktop)

        _git(root, "init", "--bare", "-q", "-b", "main", str(origin))
        _git(desktop, "init", "-q", "-b", "main")
        _git(desktop, "config", "user.email", "portable@example.invalid")
        _git(desktop, "config", "user.name", "Portable Integration")
        _git(desktop, "remote", "add", "origin", str(origin))
        _git(desktop, "add", ".")
        _git(desktop, "commit", "-qm", "published implementation")
        _git(desktop, "push", "-q", "-u", "origin", "main")

        # Producer имеет собственную незавершённую invocation. Она не переносится.
        source_local = start_execution(desktop, "PROJECT QUICK FIX: local session")
        exported = write_handoff(desktop, "STEP-017")
        assert exported["status"] == "PASS", exported
        _git(desktop, "add", exported["path"])
        _git(desktop, "commit", "-qm", "publish portable handoff")
        _git(desktop, "push", "-q", "origin", "main")
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(laptop))

        assert not (laptop / ".harness/local/execution/execution-status.json").exists()
        assert not (laptop / ".harness/.execution-checkpoint-known").exists()
        selection = harness_resume(laptop)
        assert selection["status"] == "PASS" and selection["portable"] is True, selection
        assert selection["command"] == "STEP PLAN STEP-017", selection
        assert not (laptop / ".harness/local/execution/execution-status.json").exists()

        # Проверяем именно public dispatcher, а не mock его ответа.
        output = subprocess.run(
            (sys.executable, ".harness/tools/harness-dispatch.py", "start",
             "--command", "HARNESS RESUME"),
            cwd=laptop, text=True, encoding="utf-8",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45, check=False,
        )
        assert output.returncode == 0, (output.stdout, output.stderr)
        response = json.loads(output.stdout)
        assert response["status"] == "SEMANTIC", response
        assert response["command"] == "STEP PLAN STEP-017", response
        assert response["skill"] == "plan-step", response
        assert response["portableAdoption"]["importedExecution"] is False, response
        assert response["portableAdoption"]["externalSideEffectsExecuted"] is False, response
        assert response["executionId"] != source_local["executionId"], response
        local = load_status(laptop)
        assert len(local["executions"]) == 1, local
        assert local["executions"][0]["rootCommand"] == "STEP PLAN STEP-017", local
        assert local["executions"][0]["current"]["context"]["intentBasis"], local
        assert _git(laptop, "status", "--porcelain") == ""

        # Повторная команда продолжает NEW local PLAN, а не создаёт ещё один root.
        resumed = start_dispatch(laptop, "HARNESS RESUME")
        assert resumed["executionId"] == response["executionId"], resumed
        assert len(load_status(laptop)["executions"]) == 1

        # Новый clone с сохранённым пустым local state НЕ является fresh clone.
        prior = root / "prior-local"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(prior))
        _write(
            prior / ".harness/local/execution/execution-status.json",
            json.dumps(empty_status()) + "\n",
        )
        assert harness_resume(prior)["reasonCode"] == "NO_RESUMABLE_EXECUTION"
        with patch("command_dispatch.harness_resume", return_value=selection):
            rejected = start_dispatch(prior, "HARNESS RESUME")
            # The patched selection still must hit the atomic fresh state guard.
            assert rejected["status"] == "BLOCKED", rejected
            assert rejected["reasonCode"] == "EXECUTION_STATE_INCOMPATIBLE", rejected
        assert load_status(prior)["executions"] == []

        # Uncommitted files and diverged branch cannot provide adoption proof.
        dirty = root / "dirty"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(dirty))
        _write(dirty / "unpublished.txt", "not in Git\n")
        assert harness_resume(dirty)["reasonCode"] == "WORKTREE_DIRTY"
        assert not (dirty / ".harness/local/execution/execution-status.json").exists()

        wrong_branch = root / "wrong-branch"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(wrong_branch))
        _git(wrong_branch, "switch", "-q", "-c", "unrelated")
        assert harness_resume(wrong_branch)["reasonCode"] == "HANDOFF_BRANCH_CHANGED"

        # Multiple in_progress STEP candidates remain ambiguous.
        ambiguous = root / "ambiguous"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(ambiguous))
        second = _task().replace("STEP-017", "STEP-018").replace("  status: draft", "  status: not_planned")
        _write(ambiguous / "planning/tasks/STEP-018.md", second)
        _git(ambiguous, "config", "user.email", "portable@example.invalid")
        _git(ambiguous, "config", "user.name", "Portable Integration")
        _git(ambiguous, "add", "planning/tasks/STEP-018.md")
        _git(ambiguous, "commit", "-qm", "second STEP candidate")
        assert harness_resume(ambiguous)["reasonCode"] == "PORTABLE_CANDIDATES_AMBIGUOUS"

        # Local execution start between read-only selection and dispatch
        # must not be overwritten/reused by portable PLAN.
        race = root / "local-race"
        _git(root, "clone", "-q", "--branch", "main", str(origin), str(race))
        selected = harness_resume(race)
        assert selected["status"] == "PASS", selected
        competing = start_execution(race, "PROJECT QUICK FIX: started concurrently")
        with patch("command_dispatch.harness_resume", return_value=selected):
            blocked = start_dispatch(race, "HARNESS RESUME")
        assert blocked["status"] == "BLOCKED", blocked
        assert blocked["reasonCode"] == "PORTABLE_LOCAL_HISTORY_PRESENT", blocked
        state = load_status(race)
        assert len(state["executions"]) == 1, state
        assert state["executions"][0]["executionId"] == competing["executionId"]


if __name__ == "__main__":
    test_portable_gate()
    test_local_precedence()
    test_dispatch_creates_new_local_plan()
    test_two_clone_real_dispatch()
    print("portable-resume-self-test: PASS")
