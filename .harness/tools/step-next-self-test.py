#!/usr/bin/env python3
"""Synthetic regression deterministic STEP NEXT recommendation."""
from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import errno
import shutil
import subprocess
import tempfile
import time

import step_next as step_next_module
from command_dispatch import start_dispatch
from execution_status import complete_command, start_execution
from step_next import resolve_step_action, resolve_step_next


from self_test_fixture import copy_effective_harness_checkout, isolate_project_artifacts


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed ({proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )


def copy_tracked(target: Path) -> None:
    copy_effective_harness_checkout(SOURCE_ROOT, target)

def step_text(
    step_id: str,
    *,
    priority: str = "medium",
    status: str = "planned",
    step_type: str = "implementation",
    depends: list[str] | None = None,
    adrs: list[str] | None = None,
    risks: list[str] | None = None,
) -> str:
    deps = depends or []
    linked_adrs = adrs or []
    flags = risks or ["none"]
    dep_yaml = "[]"
    if deps:
        dep_yaml = "\n" + "\n".join(f"  - {item}" for item in deps)
    adr_yaml = "[]"
    if linked_adrs:
        adr_yaml = "\n" + "\n".join(f"  - {item}" for item in linked_adrs)
    risk_yaml = "\n" + "\n".join(f"  - {item}" for item in flags)
    return f"""---
schema: 1
id: {step_id}
status: {status}
type: {step_type}
priority: {priority}
phase: test
depends_on: {dep_yaml}
requirements: []
adrs: {adr_yaml}
architecture_refs: []
risk_flags: {risk_yaml}
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# {step_id} — Next fixture {step_id}

## Goal

Проверить STEP NEXT.

## Context

Synthetic.

## Scope

- Next selection.

## Mutation policy

### Allowed

- synthetic.

### Conditional

- none.

### Forbidden

- unrelated.

## Out of scope

- product.

## Acceptance criteria

- Deterministic recommendation.

## Verification

- command: `python3 -V`

## Deliverables

- Recommendation.

## Implementation plan

TBD.

## Evidence

—

## Blocker / Failure reason

—
"""


def write_step(root: Path, step_id: str, **kwargs) -> None:
    path = root / f"planning/tasks/{step_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(step_text(step_id, **kwargs), encoding="utf-8", newline="\n")


def write_adr(root: Path, adr_id: str, *, status: str = "proposed") -> None:
    path = root / f"docs/adr/{adr_id}-synthetic.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
schema: 1
id: {adr_id}
status: {status}
date: 2026-10-04
deciders: []
supersedes: []
superseded_by: []
requirements: []
steps: []
---

# {adr_id} — Synthetic ADR

## Context

Synthetic STEP NEXT regression fixture.
""",
        encoding="utf-8",
        newline="\n",
    )


def reset_steps(root: Path) -> None:
    directory = root / "planning/tasks"
    for path in directory.glob("STEP-*.md"):
        path.unlink()


@contextmanager
def temporary_git_checkout():
    """Очистить временный Git checkout без случайного падения из-за race.

    На Python 3.11 rmtree иногда встречает временно непустую .git. Повторяем
    только этот конкретный сбой, не игнорируя постоянную ошибку очистки.
    """
    temporary = tempfile.TemporaryDirectory(prefix="harness-step-next-")
    try:
        yield temporary.name
    finally:
        for attempt in range(3):
            try:
                temporary.cleanup()
                break
            except OSError as exc:
                if exc.errno != errno.ENOTEMPTY or attempt == 2:
                    raise
                time.sleep(0.1 * (attempt + 1))


def main() -> int:
    with temporary_git_checkout() as tmp:
        root = Path(tmp)
        copy_tracked(root)
        isolate_project_artifacts(root)
        reset_steps(root)

        run(root, "git", "init", "-q", "-b", "main")
        run(root, "git", "config", "user.email", "next@example.invalid")
        run(root, "git", "config", "user.name", "Next Test")
        # Во временной фикстуре не нужен фоновый Git maintenance / auto-gc.
        run(root, "git", "config", "gc.auto", "0")
        run(root, "git", "config", "maintenance.auto", "false")
        run(root, "git", "add", ".")
        run(root, "git", "commit", "-qm", "fixture")

        # Dependency completion is a hard gate before ranking, even when the
        # blocked downstream task has critical priority.
        write_step(
            root,
            "STEP-001",
            priority="critical",
            depends=["STEP-010"],
        )
        write_step(root, "STEP-010", priority="low")
        first = resolve_step_next(root)
        assert first["status"] == "PASS", first
        assert first["command"] == "STEP RUN STEP-010", first
        assert first["selected"]["ranking"]["priority"] == "low", first
        assert any(x["stepId"] == "STEP-001" for x in first["blockers"]), first

        exact = resolve_step_action(root, "STEP-001")
        assert exact["status"] == "PASS", exact
        assert exact["stepType"] == "implementation", exact
        assert exact["command"] == "STEP PLAN STEP-001", exact

        # A five-STEP DAG: unfinished prerequisites never compete on priority.
        reset_steps(root)
        write_step(root, "STEP-001", priority="low")
        write_step(root, "STEP-002", priority="critical", depends=["STEP-001"])
        write_step(root, "STEP-003", priority="medium")
        write_step(
            root, "STEP-004", priority="high",
            depends=["STEP-002", "STEP-003"],
        )
        write_step(
            root, "STEP-005", priority="critical",
            depends=["STEP-001", "STEP-002", "STEP-003", "STEP-004"],
        )
        dag = resolve_step_next(root)
        assert dag["command"] == "STEP RUN STEP-003", dag
        assert dag["eligibleCount"] == 2, dag
        assert dag["alternatives"][0]["command"] == "STEP RUN STEP-001", dag
        assert {item["stepId"] for item in dag["blockers"]} == {
            "STEP-002", "STEP-004", "STEP-005",
        }, dag
        assert "dependency-incomplete:STEP-001" in " ".join(
            next(item["reasons"] for item in dag["blockers"]
                 if item["stepId"] == "STEP-002")
        ), dag
        # Manually requested PLAN retains the old permissive prerequisite rule.
        manual = resolve_step_action(root, "STEP-005")
        assert manual["status"] == "PASS", manual
        assert manual["command"] == "STEP PLAN STEP-005", manual

        # Completed metadata alone is not enough: a research dependency needs
        # durable evidence before it can unlock an implementation STEP.
        reset_steps(root)
        write_step(root, "STEP-020", priority="critical", depends=["STEP-021"])
        write_step(
            root, "STEP-021", status="completed", step_type="research",
        )
        no_proof = resolve_step_next(root)
        assert no_proof["status"] == "BLOCKED", no_proof
        assert no_proof["reasonCode"] == "NO_EXECUTABLE_STEP", no_proof
        assert any(
            reason.startswith("dependency-incomplete:STEP-021")
            for item in no_proof["blockers"] for reason in item["reasons"]
        ), no_proof

        completed_research = root / "planning/tasks/STEP-021.md"
        research_text = completed_research.read_text(encoding="utf-8")
        assert "## Evidence\n\n—" in research_text
        completed_research.write_text(
            research_text.replace(
                "## Evidence\n\n—", "## Evidence\n\n- Synthetic research proof."
            ),
            encoding="utf-8",
            newline="\n",
        )
        ready_after_proof = resolve_step_next(root)
        assert ready_after_proof["status"] == "PASS", ready_after_proof
        assert ready_after_proof["command"] == "STEP RUN STEP-020", ready_after_proof

        # Missing dependencies and dependency cycles are never executable.
        reset_steps(root)
        write_step(root, "STEP-030", depends=["STEP-031"])
        missing = resolve_step_next(root)
        assert missing["status"] == "BLOCKED", missing
        assert any(
            reason.startswith("dependency-unprovable:STEP-031")
            for item in missing["blockers"] for reason in item["reasons"]
        ), missing
        write_step(root, "STEP-031", depends=["STEP-030"])
        cycle = resolve_step_next(root)
        assert cycle["status"] == "BLOCKED", cycle
        assert any(
            reason.startswith("dependency-cycle:")
            for item in cycle["blockers"] for reason in item["reasons"]
        ), cycle

        # ADR STEP owns its linked proposed ADR: requiring accepted before PLAN
        # would create a cyclic prerequisite. Ordinary implementation STEPs
        # remain blocked by the same proposed ADR status.
        reset_steps(root)
        write_adr(root, "ADR-1000", status="proposed")
        write_adr(root, "ADR-1001", status="proposed")
        write_step(
            root,
            "STEP-011",
            priority="critical",
            step_type="adr",
            adrs=["ADR-1000"],
        )
        write_step(
            root,
            "STEP-012",
            priority="high",
            adrs=["ADR-1001"],
        )

        adr_action = resolve_step_action(root, "STEP-011")
        assert adr_action["status"] == "PASS", adr_action
        assert adr_action["stepType"] == "adr", adr_action
        assert adr_action["command"] == "STEP PLAN STEP-011", adr_action

        implementation_action = resolve_step_action(root, "STEP-012")
        assert implementation_action["status"] == "BLOCKED", implementation_action
        assert (
            "adr-not-accepted:ADR-1001" in implementation_action["reasons"]
        ), implementation_action

        adr_next = resolve_step_next(root)
        assert adr_next["status"] == "PASS", adr_next
        assert adr_next["command"] == "STEP RUN STEP-011", adr_next

        # Same priority: a STEP that unlocks more downstream active work wins.
        reset_steps(root)
        write_step(root, "STEP-002", priority="high")
        write_step(root, "STEP-003", priority="high")
        write_step(
            root,
            "STEP-004",
            priority="low",
            status="blocked",
            depends=["STEP-002"],
        )
        downstream = resolve_step_next(root)
        assert downstream["command"] == "STEP RUN STEP-002", downstream
        assert downstream["selected"]["ranking"]["downstreamImpact"] == 1, downstream

        # Risk is only a deterministic visibility tie-breaker, not a severity
        # model. With all earlier ranking dimensions equal, explicit risk wins.
        reset_steps(root)
        write_step(root, "STEP-005", priority="medium")
        write_step(
            root,
            "STEP-006",
            priority="medium",
            risks=["security-sensitive", "public-api"],
        )
        risk = resolve_step_next(root)
        assert risk["command"] == "STEP RUN STEP-006", risk
        assert risk["selected"]["ranking"]["riskFlagCount"] == 2, risk

        # Existing interrupted STEP execution always wins over higher-priority
        # fresh work. This preserves user continuity without LLM arbitration.
        write_step(root, "STEP-007", priority="critical")
        active = start_execution(root, "STEP PLAN STEP-005")
        assert active["status"] == "running", active
        continuity = resolve_step_next(root)
        assert continuity["command"] == "STEP PLAN STEP-005", continuity
        assert continuity["reasonCode"] == "RESUME_STEP_EXECUTION", continuity
        assert continuity["selected"]["source"] == "execution", continuity
        assert continuity["alternatives"][0]["command"] == "STEP RUN STEP-007", continuity

        # REVIEW PASS and completion are different durable facts. A PASS review
        # with in-scope completion FAIL still requires canonical FIX; a semantic
        # completion blocker must not be converted into new implementation work.
        original_latest_review = step_next_module.latest_review
        try:
            step_next_module.latest_review = lambda *_args, **_kwargs: {
                "verdict": "PASS",
                "completionResult": "FAIL",
            }
            completion_fix = resolve_step_action(root, "STEP-005")
            assert completion_fix["status"] == "PASS", completion_fix
            assert completion_fix["command"] == "STEP FIX STEP-005", completion_fix

            step_next_module.latest_review = lambda *_args, **_kwargs: {
                "verdict": "PASS",
                "completionResult": "BLOCKED",
            }
            completion_blocked = resolve_step_action(root, "STEP-005")
            assert completion_blocked["status"] == "BLOCKED", completion_blocked
            assert (
                "current-review-completion-blocked"
                in completion_blocked["reasons"]
            ), completion_blocked
        finally:
            step_next_module.latest_review = original_latest_review

        # Dispatcher executes STEP NEXT itself; no next-step semantic skill is
        # needed to choose the recommendation.
        dispatched = start_dispatch(root, "STEP NEXT")
        assert dispatched["status"] == "DONE", dispatched
        result = dispatched["result"]
        assert result["status"] == "PASS", result
        assert result["command"] == "STEP PLAN STEP-005", result

        # Clean up the synthetic interrupted command to leave no hidden state.
        complete_command(
            root,
            active["rootCommand"],
            active["current"]["command"],
            "BLOCKED",
        )

        # Interrupted PLAN is not an exception to dependency gating.
        # Reading STEP NEXT must not rewrite durable execution state.
        reset_steps(root)
        write_step(root, "STEP-040", priority="critical", depends=["STEP-041"])
        write_step(root, "STEP-041", priority="low")
        unsafe = start_execution(root, "STEP PLAN STEP-040")
        state_file = root / ".harness/local/execution/execution-status.json"
        before = state_file.read_bytes()
        guarded = resolve_step_next(root)
        after = state_file.read_bytes()
        assert before == after, "STEP NEXT mutated execution state"
        assert guarded["command"] == "STEP RUN STEP-041", guarded
        assert guarded["selected"]["source"] == "fresh", guarded
        assert any(
            item["stepId"] == "STEP-040" for item in guarded["blockers"]
        ), guarded
        complete_command(
            root,
            unsafe["rootCommand"],
            unsafe["current"]["command"],
            "BLOCKED",
        )

    print("STEP NEXT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
