#!/usr/bin/env python3
"""Deterministic smoke tests for restart-safe STEP recovery."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

from execution_recovery import (
    begin_phase,
    complete_phase,
    resolve_step,
    stamp_plan,
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def task_text(status: str = "Запланировано", verdict: str = "NOT REVIEWED", report: str = "—") -> str:
    return f"""# STEP-001 — Recovery test

**Статус:** {status}
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

Проверить restart-safe flow.

## Context

Self-test.

## Scope

- Изменить test fixture.

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

**Latest verdict:** {verdict}
**Latest report:** {report}

## Blocker / Failure reason

—
"""


def update_review_status(path: Path, verdict: str, report: str, status: str = "В работе") -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace("**Статус:** Запланировано", f"**Статус:** {status}")
    text = text.replace("**Статус:** В работе", f"**Статус:** {status}")
    for old in ("NOT REVIEWED", "FAIL", "PASS", "BLOCKED"):
        text = text.replace(f"**Latest verdict:** {old}", f"**Latest verdict:** {verdict}")
    current = next(
        line.split("**Latest report:** ", 1)[1]
        for line in text.splitlines()
        if line.startswith("**Latest report:** ")
    )
    text = text.replace(f"**Latest report:** {current}", f"**Latest report:** {report}")
    path.write_text(text, encoding="utf-8")


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


def expect(result: dict, status: str, command: str | None, reason: str) -> None:
    assert result["status"] == status, result
    assert result.get("command") == command, result
    assert result["reasonCode"] == reason, result


def main() -> int:
    source = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="harness-recovery-") as tmp:
        root = Path(tmp)
        (root / ".project").mkdir(parents=True)
        shutil.copy2(
            source / ".project/command-transitions.json",
            root / ".project/command-transitions.json",
        )
        shutil.copy2(
            source / ".project/execution-recovery.json",
            root / ".project/execution-recovery.json",
        )
        write(
            root / ".project/manifest.yaml",
            "execution:\n  maxFixReviewCycles: 3\n",
        )
        task = root / "planning/tasks/STEP-001.md"
        write(task, task_text())

        expect(
            resolve_step(root, "STEP-001"),
            "NEXT",
            "STEP PLAN STEP-001",
            "PLAN_MISSING",
        )

        begin_phase(root, "STEP-001", "STEP PLAN STEP-001")
        stamp_plan(root, "STEP-001")

        # Crash after durable PLAN proof, before local completion checkpoint.
        expect(
            resolve_step(root, "STEP-001"),
            "NEXT",
            "STEP IMPLEMENT STEP-001",
            "PLAN_PROVEN_AFTER_INTERRUPTION",
        )

        # Resume interrupted IMPLEMENT instead of repeating PLAN.
        begin_phase(root, "STEP-001", "STEP IMPLEMENT STEP-001")
        expect(
            resolve_step(root, "STEP-001"),
            "RESUME",
            "STEP IMPLEMENT STEP-001",
            "INTERRUPTED_IMPLEMENT",
        )

        complete_phase(
            root,
            "STEP-001",
            "STEP IMPLEMENT STEP-001",
            result="SUCCESS",
        )
        expect(
            resolve_step(root, "STEP-001"),
            "NEXT",
            "STEP REVIEW STEP-001",
            "IMPLEMENT_COMPLETED",
        )

        # New immutable review report proves interrupted REVIEW completion.
        begin_phase(root, "STEP-001", "STEP REVIEW STEP-001")
        report1 = create_review(root, "REVIEW-20260919-120000.md", "FAIL")
        update_review_status(task, "FAIL", report1)
        expect(
            resolve_step(root, "STEP-001"),
            "NEXT",
            "STEP FIX STEP-001",
            "LATEST_REVIEW_FAIL",
        )

        begin_phase(root, "STEP-001", "STEP FIX STEP-001")
        expect(
            resolve_step(root, "STEP-001"),
            "RESUME",
            "STEP FIX STEP-001",
            "INTERRUPTED_FIX",
        )
        complete_phase(
            root,
            "STEP-001",
            "STEP FIX STEP-001",
            result="SUCCESS",
        )
        expect(
            resolve_step(root, "STEP-001"),
            "NEXT",
            "STEP REVIEW STEP-001",
            "FIX_COMPLETED",
        )

        begin_phase(root, "STEP-001", "STEP REVIEW STEP-001")
        report2 = create_review(root, "REVIEW-20260919-121000.md", "PASS")
        update_review_status(task, "PASS", report2)
        expect(
            resolve_step(root, "STEP-001"),
            "RESUME",
            "STEP RUN STEP-001",
            "FINALIZE_AFTER_PASS",
        )

        update_review_status(task, "PASS", report2, status="Выполнено")
        expect(
            resolve_step(root, "STEP-001"),
            "DONE",
            None,
            "STEP_COMPLETED",
        )

        # Contract mutation invalidates PLAN deterministically.
        text = task.read_text(encoding="utf-8").replace(
            "Проверить restart-safe flow.",
            "Проверить изменённый restart-safe flow.",
        )
        text = text.replace("**Статус:** Выполнено", "**Статус:** В работе")
        task.write_text(text, encoding="utf-8")
        result = resolve_step(root, "STEP-001")
        assert result["command"] == "STEP PLAN STEP-001", result
        assert result["reasonCode"].startswith("PLAN_STALE"), result

    print("RECOVERY SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
