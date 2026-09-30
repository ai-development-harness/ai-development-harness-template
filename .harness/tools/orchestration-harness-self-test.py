#!/usr/bin/env python3
"""Deterministic orchestration/runtime/fault-injection regression suite."""
from __future__ import annotations

from pathlib import Path
import sys

from command_transitions import load_transition_table, parse_canonical_command
from runtime_adapter_conformance import run_all_declared_adapters
from scripted_runtime import FAULT_POINTS, ScriptedFault, ScriptedRuntime, ScriptedRuntimeError


def _edge_allows(root: Path, source: str, target: str, result: str) -> bool:
    table = load_transition_table(root)
    left = parse_canonical_command(source, table)
    right = parse_canonical_command(target, table)
    if not left.get("valid") or not right.get("valid"):
        return False
    if left.get("domain") != right.get("domain"):
        return False
    domain = table["domains"][left["domain"]]
    return any(
        edge.get("from") == left.get("operation")
        and edge.get("to") == right.get("operation")
        and result in edge.get("onPreviousResult", [])
        for edge in domain.get("transitions", [])
    )


def main() -> int:
    root = Path(__file__).resolve().parents[2]

    # Common deterministic conformance for every declared production adapter.
    conformance = run_all_declared_adapters(root)
    assert [item["runtimeId"] for item in conformance] == ["claude", "codex"], conformance
    assert all(item["status"] == "PASS" for item in conformance), conformance

    # Canonical STEP RUN repair path is proven against the real CTS, not a
    # second transition table hidden in the test double.
    flow = [
        ("STEP PLAN STEP-001", "SUCCESS"),
        ("STEP IMPLEMENT STEP-001", "SUCCESS"),
        ("STEP REVIEW STEP-001", "FAIL"),
        ("STEP FIX STEP-001", "SUCCESS"),
        ("STEP REVIEW STEP-001", "PASS"),
    ]
    for (source, result), (target, _) in zip(flow, flow[1:]):
        assert _edge_allows(root, source, target, result), (source, result, target)

    runtime = ScriptedRuntime(
        {
            "steps": [
                {
                    "expect": "STEP PLAN STEP-001",
                    "result": "SUCCESS",
                    "events": [
                        {"type": "run.started"},
                        {"type": "model.message.completed", "data": {"phase": "plan"}},
                        {"type": "run.completed"},
                    ],
                },
                {
                    "expect": "STEP IMPLEMENT STEP-001",
                    "result": "SUCCESS",
                    "events": [
                        {"type": "run.started"},
                        {"type": "model.message.completed", "data": {"phase": "implement"}},
                        {"type": "run.completed"},
                    ],
                },
                {
                    "expect": "STEP REVIEW STEP-001",
                    "result": "FAIL",
                    "events": [
                        {"type": "run.started"},
                        {
                            "type": "model.message.completed",
                            "data": {"findings": ["F-001"]},
                        },
                        {"type": "run.completed"},
                    ],
                },
                {
                    "expect": "STEP FIX STEP-001",
                    "result": "SUCCESS",
                    "sideEffectIdentity": "fix:STEP-001:F-001",
                    "events": [
                        {"type": "run.started"},
                        {"type": "tool.started", "data": {"tool": "edit"}},
                        {"type": "tool.completed", "data": {"tool": "edit"}},
                        {"type": "run.completed"},
                    ],
                },
                {
                    "expect": "STEP REVIEW STEP-001",
                    "result": "PASS",
                    "events": [
                        {"type": "run.started"},
                        {"type": "model.message.completed", "data": {"findings": []}},
                        {"type": "run.completed"},
                    ],
                },
            ]
        }
    )

    results = [runtime.start(command) for command, _result in flow]
    assert [item["result"] for item in results] == [item[1] for item in flow], results
    runtime.assert_complete()

    event_types = [item["type"] for item in runtime.events()]
    assert event_types == [
        "run.started", "model.message.completed", "run.completed",
        "run.started", "model.message.completed", "run.completed",
        "run.started", "model.message.completed", "run.completed",
        "run.started", "tool.started", "tool.completed", "run.completed",
        "run.started", "model.message.completed", "run.completed",
    ], event_types

    # Fault after external side effect: resume repeats the interaction but
    # ScriptedRuntime records the side-effect identity only once.
    recover = ScriptedRuntime(
        {
            "steps": [
                {
                    "expect": "STEP FIX STEP-002",
                    "expectResume": "STEP FIX STEP-002",
                    "result": "SUCCESS",
                    "sideEffectIdentity": "fix:STEP-002:F-001",
                    "faultOnce": "after_side_effect_before_observation",
                    "events": [
                        {"type": "run.started"},
                        {"type": "tool.completed", "data": {"tool": "write"}},
                    ],
                }
            ]
        }
    )
    try:
        recover.start("STEP FIX STEP-002")
    except ScriptedFault as exc:
        assert exc.checkpoint == "after_side_effect_before_observation", exc
    else:
        raise AssertionError("fault injection did not interrupt the scripted step")
    resumed = recover.resume("STEP FIX STEP-002")
    assert resumed["result"] == "SUCCESS", resumed
    assert recover.applied_side_effects() == ["fix:STEP-002:F-001"], recover.applied_side_effects()
    recover.assert_complete()

    # Every declared named fault checkpoint is executable, not just a schema enum.
    for checkpoint in sorted(
        FAULT_POINTS - {"runtime_disconnect", "input_required"}
    ):
        injected = ScriptedRuntime(
            {
                "steps": [
                    {
                        "expect": "STEP IMPLEMENT STEP-099",
                        "faultOnce": checkpoint,
                        **(
                            {"sideEffectIdentity": "fault-side-effect"}
                            if checkpoint in {
                                "after_side_effect_before_observation",
                                "after_observation_before_completion_checkpoint",
                            }
                            else {}
                        ),
                    }
                ]
            }
        )
        try:
            injected.start("STEP IMPLEMENT STEP-099")
        except ScriptedFault as exc:
            assert exc.checkpoint == checkpoint, (checkpoint, exc)
        else:
            raise AssertionError(f"{checkpoint} did not interrupt")

    # Runtime disconnect and input-required are first-class named interruptions.
    for checkpoint, expected_event in (
        ("runtime_disconnect", "run.interrupted"),
        ("input_required", "input.required"),
    ):
        interrupted = ScriptedRuntime(
            {
                "steps": [
                    {
                        "expect": "STEP IMPLEMENT STEP-003",
                        "faultOnce": checkpoint,
                        "events": [{"type": "run.started"}],
                    }
                ]
            }
        )
        try:
            interrupted.start("STEP IMPLEMENT STEP-003")
        except ScriptedFault as exc:
            assert exc.checkpoint == checkpoint, exc
        else:
            raise AssertionError(f"{checkpoint} did not interrupt")
        assert interrupted.events()[-1]["type"] == expected_event, interrupted.events()

    # Explicit unsupported capability must fail at the exact scenario step.
    unsupported = ScriptedRuntime(
        {
            "steps": [
                {
                    "expect": "STEP IMPLEMENT STEP-004",
                    "requiresCapability": "interactiveInput",
                }
            ]
        },
        capability_overrides={"interactiveInput": "unsupported"},
    )
    try:
        unsupported.start("STEP IMPLEMENT STEP-004")
    except ScriptedRuntimeError as exc:
        assert "does not support interactiveInput" in str(exc), exc
    else:
        raise AssertionError("unsupported capability was accepted")

    # Failure output contains exact step/expected/actual interaction.
    mismatch = ScriptedRuntime({"steps": [{"expect": "STEP PLAN STEP-005"}]})
    try:
        mismatch.start("STEP REVIEW STEP-005")
    except ScriptedRuntimeError as exc:
        message = str(exc)
        assert "step 0" in message and "STEP PLAN STEP-005" in message and "STEP REVIEW STEP-005" in message
    else:
        raise AssertionError("scenario mismatch was accepted")

    print("orchestration-harness-self-test: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
