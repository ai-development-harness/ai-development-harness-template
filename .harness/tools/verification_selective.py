#!/usr/bin/env python3
"""Targeted feedback runner: NEVER a substitute for full STEP Verification.

FIX can run specific configured test commands before declaring completion,
avoiding repeated full suites during local trial-and-error. Dispatcher still
runs the complete mandatory Verification contract before SUCCESS.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from review_contract import repository_revision
from harness_config import verification_command_timeout_seconds
from verification import (
    parse_verification, _run_command, _refs_snapshot,
    verification_contract_basis, verification_context_basis,
    verification_subject_content_hash,
)
from verification_incremental import remember_targeted


def run_selected(root: Path, step_id: str, commands: list[str]) -> dict[str, Any]:
    if not isinstance(commands, list) or not 1 <= len(commands) <= 8 or len(set(commands)) != len(commands):
        return {"status": "BLOCKED", "reasonCode": "INVALID_SELECTION"}
    available = [
        entry["value"] for entry in parse_verification(root, step_id)
        if entry["kind"] == "command"
    ]
    if any(command not in available for command in commands):
        return {"status": "BLOCKED", "reasonCode": "UNCONFIGURED_COMMAND"}
    revision = repository_revision(root)
    refs = _refs_snapshot(root)
    timeout = verification_command_timeout_seconds(root)
    results = []
    for command in commands:
        if repository_revision(root) != revision or _refs_snapshot(root) != refs:
            return {"status": "BLOCKED", "reasonCode": "SUBJECT_CHANGED"}
        record = _run_command(root, command, timeout_seconds=timeout)
        results.append(record)
        if repository_revision(root) != revision or _refs_snapshot(root) != refs:
            return {"status": "BLOCKED", "reasonCode": "SELECTED_COMMAND_MUTATED_REPOSITORY"}
        if record["status"] == "BLOCKED":
            return {"status": "BLOCKED", "reasonCode": record.get("reasonCode"), "commands": results}
        if record["status"] == "FAIL":
            return {"status": "FAIL", "commands": results,
                    "fullVerificationRequired": True, "completionProof": False}
    # Сами выбранные команды не создают completion proof. Они могут войти в
    # итоговый proof только после последующей повторной проверки map/inputs.
    try:
        from completion_gate import acceptance_criteria
        from execution_status import execution_state_lock
        with execution_state_lock(root):
            if repository_revision(root) == revision and _refs_snapshot(root) == refs:
                remember_targeted(
                    root, step_id, results=results, commands=available,
                    acceptance=acceptance_criteria(root, step_id),
                    contract_basis=verification_contract_basis(root, step_id),
                    context_basis=verification_context_basis(root, step_id),
                    timeout=timeout,
                    subject_hash=verification_subject_content_hash(root, step_id),
                )
    except (OSError, ValueError):
        # Loss of optional feedback cache does not affect factual PASS.
        pass
    return {"status": "PASS", "commands": results,
            "fullVerificationRequired": True, "completionProof": False,
            "mode": "targeted-feedback-only"}
