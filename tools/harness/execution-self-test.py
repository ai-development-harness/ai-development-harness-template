#!/usr/bin/env python3
"""Deterministic self-test for universal Harness execution status."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

from command_transitions import load_transition_table
from execution_status import (
    begin_command,
    complete_command,
    find_completed,
    load_status,
    resolve_root,
    stamp_plan,
    start_execution,
    unresolved_executions,
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def task_text() -> str:
    return """# STEP-001 — Execution state test

**Статус:** Запланировано
**Type:** IMPLEMENTATION
**Приоритет:** Средний
**Фаза:** Test
**Depends on:** —

## Requirements

- REQ-001

## ADR

- не требуется

## Risk flags

- none

## Goal

Проверить universal execution status.

## Context

Self-test.

## Scope

- Test fixture.

## Mutation policy

### Allowed

- fixture

### Conditional

- —

### Forbidden

- unrelated

## Out of scope

- unrelated

## Acceptance criteria

- fixture готов.

## Verification

- deterministic check.

## Deliverables

- fixture.

## Implementation plan

**Plan status:** Not planned
**Plan revision:** —
**Plan basis:** —
**Planned at:** —

1. Test plan.

## Evidence

—

## Review status

**Latest verdict:** NOT REVIEWED
**Latest report:** —

## Blocker / Failure reason

—
"""


def create_review(root: Path, name: str, verdict: str) -> str:
    rel = f"planning/reviews/STEP-001/{name}"
    write(
        root / rel,
        f"""# REVIEW STEP-001

**Reviewer role:** reviewer
**Verdict:** {verdict}
**Reviewed revision:** test

## Scope checked

fixture

## Findings

none

## Verification observations

fixture

## Specialized reviews

- Security: not required
- Tests: not required

## Verdict rationale

test
""",
    )
    return rel


def sample_command(domain: str, operation: str, spec: dict) -> str:
    value = spec["canonical"].replace("STEP-NNN", "STEP-001")
    if spec.get("target") == "release-optional":
        value += " TO v0.4.0"
    if spec.get("input") == "required":
        value += " sample"
    return value


def assert_resolved(
    value: dict,
    status: str,
    command: str | None,
    reason: str,
) -> None:
    assert value["status"] == status, value
    assert value.get("command") == command, value
    assert value["reasonCode"] == reason, value


def main() -> int:
    source = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="harness-execution-") as tmp:
        root = Path(tmp)
        (root / ".project").mkdir(parents=True)
        shutil.copy2(
            source / ".project/command-transitions.json",
            root / ".project/command-transitions.json",
        )
        write(root / "planning/tasks/STEP-001.md", task_text())

        # 1. Every canonical Harness command can be tracked as an independent
        # single execution. No global transition between separate invocations
        # is required.
        table = load_transition_table(root)
        canonical_samples: list[str] = []
        for domain_name, domain in table["domains"].items():
            for operation, spec in domain["commands"].items():
                command = sample_command(domain_name, operation, spec)
                canonical_samples.append(command)
                execution = start_execution(root, command)
                if execution["mode"] == "orchestration":
                    # STEP RUN is intentionally left to the dedicated test below.
                    complete_command(
                        root,
                        execution["rootCommand"],
                        execution["current"]["command"],
                        "SUCCESS",
                    )
                else:
                    complete_command(
                        root,
                        execution["rootCommand"],
                        execution["current"]["command"],
                        "SUCCESS",
                    )

        status = load_status(root)
        assert len(status["executions"]) == len(canonical_samples), (
            len(status["executions"]),
            len(canonical_samples),
        )

        # 2. Manual independent commands are valid even when CTS has no edge
        # between them: STEP PLAN, then GIT COMMIT.
        plan = start_execution(root, "STEP PLAN STEP-001")
        complete_command(
            root,
            plan["rootCommand"],
            "STEP PLAN STEP-001",
            "SUCCESS",
        )
        assert_resolved(
            resolve_root(root, "STEP PLAN STEP-001"),
            "DONE",
            None,
            "EXECUTION_COMPLETE",
        )
        commit = start_execution(root, "GIT COMMIT")
        assert commit["mode"] == "single"
        complete_command(root, "GIT COMMIT", "GIT COMMIT", "SUCCESS")

        # 3. Full Git chain advances only inside that explicit root execution.
        git_root = "GIT CHECK > COMMIT > PUSH > PR"
        git_exec = start_execution(root, git_root)
        assert git_exec["mode"] == "chain"
        complete_command(root, git_root, "GIT CHECK", "PASS")
        assert_resolved(
            resolve_root(root, git_root),
            "NEXT",
            "GIT COMMIT",
            "CHAIN_NEXT_SEGMENT",
        )
        begin_command(root, git_root, "GIT COMMIT")
        complete_command(root, git_root, "GIT COMMIT", "SUCCESS")
        assert resolve_root(root, git_root)["command"] == "GIT PUSH"
        begin_command(root, git_root, "GIT PUSH")
        complete_command(root, git_root, "GIT PUSH", "SUCCESS")
        assert resolve_root(root, git_root)["command"] == "GIT PR"
        begin_command(root, git_root, "GIT PR")
        complete_command(root, git_root, "GIT PR", "SUCCESS")
        assert_resolved(
            resolve_root(root, git_root),
            "DONE",
            None,
            "EXECUTION_COMPLETE",
        )

        # 4. Conditional chain stops cleanly when an edge result is not active.
        review_chain = "STEP REVIEW STEP-001 > FIX > REVIEW"
        conditional = start_execution(root, review_chain)
        complete_command(
            root,
            review_chain,
            "STEP REVIEW STEP-001",
            "PASS",
        )
        finished = next(
            item
            for item in reversed(load_status(root)["executions"])
            if item["executionId"] == conditional["executionId"]
        )
        assert finished["status"] == "complete", finished
        assert finished["notExecuted"] == [
            "STEP FIX STEP-001",
            "STEP REVIEW STEP-001",
        ], finished

        # Same structural chain follows REVIEW --FAIL--> FIX.
        conditional2 = start_execution(root, review_chain)
        complete_command(
            root,
            review_chain,
            "STEP REVIEW STEP-001",
            "FAIL",
        )
        assert_resolved(
            resolve_root(root, review_chain),
            "NEXT",
            "STEP FIX STEP-001",
            "CHAIN_NEXT_SEGMENT",
        )

        # 5. Harness update chain keeps inherited target across a session.
        update_root = "HARNESS UPDATE CHECK TO v0.4.0 > APPLY"
        update = start_execution(root, update_root)
        complete_command(
            root,
            update_root,
            "HARNESS UPDATE CHECK TO v0.4.0",
            "PASS",
        )
        update_next = resolve_root(root, update_root)
        assert update_next["command"] == "HARNESS UPDATE APPLY TO v0.4.0", update_next
        assert "matching-update-target-and-route" in update_next["runtimePreconditions"]

        # 6. A successful standalone update check remains discoverable even
        # after unrelated commands, so APPLY can verify a cross-session handoff.
        check = start_execution(root, "HARNESS UPDATE CHECK TO v0.4.0")
        complete_command(
            root,
            check["rootCommand"],
            "HARNESS UPDATE CHECK TO v0.4.0",
            "PASS",
        )
        status_cmd = start_execution(root, "PROJECT STATUS")
        complete_command(root, "PROJECT STATUS", "PROJECT STATUS", "SUCCESS")
        assert find_completed(
            root,
            "HARNESS UPDATE CHECK TO v0.4.0",
            result="PASS",
        ) is not None

        # 7. STEP RUN orchestration may be interrupted while another independent
        # command runs. The new command must not overwrite the interrupted one.
        stamp_plan(root, "STEP-001")
        run_root = "STEP RUN STEP-001"
        run_exec = start_execution(root, run_root)
        begin_command(root, run_root, "STEP PLAN STEP-001")
        # Durable plan proof recovers PLAN even if local completion wasn't written.
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

        overlay = start_execution(root, "GIT CHECK")
        complete_command(root, "GIT CHECK", "GIT CHECK", "PASS")
        still_interrupted = resolve_root(root, run_root)
        assert still_interrupted["command"] == "STEP IMPLEMENT STEP-001", still_interrupted

        active = unresolved_executions(root)
        assert any(
            item["executionId"] == run_exec["executionId"]
            and item["command"] == "STEP IMPLEMENT STEP-001"
            for item in active
        ), active

        # 8. Coding orchestration follows existing CTS edges.
        complete_command(
            root,
            run_root,
            "STEP IMPLEMENT STEP-001",
            "SUCCESS",
        )
        assert resolve_root(root, run_root)["command"] == "STEP REVIEW STEP-001"
        begin_command(root, run_root, "STEP REVIEW STEP-001")

        # Crash after immutable FAIL report: resolver recovers the REVIEW result.
        create_review(root, "REVIEW-20260919-120000.md", "FAIL")
        recovered_review = resolve_root(root, run_root)
        assert recovered_review["command"] == "STEP FIX STEP-001", recovered_review
        begin_command(root, run_root, "STEP FIX STEP-001")
        assert resolve_root(root, run_root)["status"] == "RESUME"
        complete_command(root, run_root, "STEP FIX STEP-001", "SUCCESS")
        assert resolve_root(root, run_root)["command"] == "STEP REVIEW STEP-001"

        begin_command(root, run_root, "STEP REVIEW STEP-001")
        create_review(root, "REVIEW-20260919-121000.md", "PASS")
        finalization = resolve_root(root, run_root)
        assert_resolved(
            finalization,
            "RESUME",
            "STEP RUN STEP-001",
            "ORCHESTRATION_CONTINUE",
        )
        begin_command(root, run_root, "STEP RUN STEP-001")
        complete_command(root, run_root, "STEP RUN STEP-001", "SUCCESS")
        assert resolve_root(root, run_root)["status"] == "DONE"

        # 9. Re-entering the same unfinished root resumes one execution instead
        # of creating duplicates.
        first = start_execution(root, "PROJECT RECONCILE")
        second = start_execution(root, "PROJECT RECONCILE")
        assert first["executionId"] == second["executionId"], (first, second)
        matching = [
            item
            for item in load_status(root)["executions"]
            if item["rootCommand"] == "PROJECT RECONCILE"
            and item["status"] == "running"
        ]
        assert len(matching) == 1, matching
        assert matching[0]["current"]["attempt"] == 2, matching[0]

        # 10. Structurally invalid chains never create execution state.
        before = len(load_status(root)["executions"])
        try:
            start_execution(root, "GIT PR > COMMIT")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid reverse Git chain was accepted")
        after = len(load_status(root)["executions"])
        assert before == after, (before, after)

        # 11. Fixed project-level path: never create per-STEP state files.
        fixed = root / ".project/local/execution/execution-status.json"
        assert fixed.is_file(), fixed
        assert not list((root / ".project/local/execution").glob("STEP-*.json"))

    print("EXECUTION STATUS SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
