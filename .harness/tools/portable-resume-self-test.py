#!/usr/bin/env python3
"""#301: отрицательные проверки безопасного portable adoption.

Это unit-boundary проверки. Реальные два Git clone и все race scenarios
остаются отдельным обязательным этапом #302.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from execution_status import ExecutionCheckpointError
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
        patch("command_dispatch.resolve_root", side_effect=AssertionError("must not resume source execution")),
    ):
        result = resume_dispatch(ROOT)
        start.assert_called_once_with(ROOT, "STEP PLAN STEP-001")
        assert result["executionId"] == "exec-new-local"
        assert result["portableAdoption"]["importedExecution"] is False
        assert result["portableAdoption"]["externalSideEffectsExecuted"] is False

if __name__ == "__main__":
    test_portable_gate()
    test_local_precedence()
    test_dispatch_creates_new_local_plan()
    print("portable-resume-self-test: PASS")
