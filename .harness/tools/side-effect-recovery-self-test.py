#!/usr/bin/env python3
"""Synthetic tests bounded SideEffectProof contract без real Git/provider."""
from __future__ import annotations

import sys

from side_effect_recovery import (
    MAX_PROOF_BYTES,
    checkpoint,
    recovery_decision,
    validate_checkpoint,
)


def main() -> int:
    prepared = checkpoint(
        kind="git_push",
        phase="prepared",
        attempt=1,
        proof={
            "localHead": "a" * 40,
            "remote": "origin",
            "branch": "feature/x",
            "remoteHeadBefore": "b" * 40,
        },
    )
    started = checkpoint(
        kind="git_push",
        phase="side_effect_started",
        attempt=1,
        proof=prepared["proof"],
        previous=prepared,
    )
    observed = checkpoint(
        kind="git_push",
        phase="side_effect_observed",
        attempt=1,
        proof={**started["proof"], "observedRemoteHead": "a" * 40},
        previous=started,
    )
    verified = checkpoint(
        kind="git_push",
        phase="postconditions_verified",
        attempt=1,
        proof=observed["proof"],
        previous=observed,
    )
    assert validate_checkpoint(verified) == []

    assert recovery_decision(
        observed="a" * 40,
        expected="a" * 40,
        baseline="b" * 40,
    ) == "ALREADY_APPLIED"
    assert recovery_decision(
        observed="b" * 40,
        expected="a" * 40,
        baseline="b" * 40,
    ) == "SAFE_RETRY"
    assert recovery_decision(
        observed="c" * 40,
        expected="a" * 40,
        baseline="b" * 40,
    ) == "AMBIGUOUS"

    try:
        checkpoint(
            kind="git_push",
            phase="prepared",
            attempt=1,
            proof={"authToken": "should-never-persist"},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("secret-like proof key was accepted")

    too_large = {
        "contractVersion": 1,
        "kind": "file_write",
        "phase": "prepared",
        "attempt": 1,
        "preparedAt": "2026-01-01T00:00:00+00:00",
        "updatedAt": "2026-01-01T00:00:00+00:00",
        "proof": {"payload": "x" * (MAX_PROOF_BYTES + 1)},
    }
    assert validate_checkpoint(too_large)

    try:
        checkpoint(
            kind="git_push",
            phase="prepared",
            attempt=1,
            proof=prepared["proof"],
            previous=started,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("phase rollback was accepted")

    print("side-effect-recovery-self-test: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
