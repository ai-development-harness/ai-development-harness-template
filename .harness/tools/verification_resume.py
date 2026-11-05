#!/usr/bin/env python3
"""Producer-bound продолжение свежей automated стадии при manual evidence.

Checkpoint относится к одному STEP/subject/execution; это не FIX reuse и не
cross-STEP cache. Mutable external checks повторяются по явной policy (#385).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any

from document_contract import atomic_write_text
from planning_contract import read_task

RESUME_TTL_SECONDS = 1800
NON_REUSABLE_FLAGS = {
    "external-integration", "security-sensitive", "data-migration",
    "destructive", "release-critical",
}


def _path(root: Path, step_id: str) -> Path:
    if re.fullmatch(r"STEP-\d{3,}", step_id) is None:
        raise ValueError("invalid verification STEP identifier")
    return root / ".harness/local/verification-resume" / (step_id + ".json")


def _environment_basis(commands: list[str]) -> str:
    executables = []
    for command in commands:
        # Parse the same command contract as the actual runner.
        from verification import _argv
        try:
            argv = _argv(command)
        except ValueError:
            # Невалидная команда не даёт proof. Штатный runner вернёт BLOCKED,
            # а preflight не должен падать раньше его factual результата.
            return ""
        resolved = shutil.which(argv[0])
        if resolved is None:
            return ""  # no proof about executable identity
        try:
            stat = Path(resolved).stat()
            # Metadata недостаточно при замене бинарника с прежними size/mtime.
            digest = hashlib.sha256(Path(resolved).read_bytes()).hexdigest()
        except OSError:
            return ""
        executables.append((resolved, stat.st_size, stat.st_mtime_ns, digest))
    # Subprocess inherits the *entire* process environment, not just PATH and
    # runtime selectors. A test can depend on any variable (feature flags,
    # credentials, database endpoints). Reusing PASS after an untracked env
    # change would be a false positive. Only the digest is persisted, never
    # individual variable names or values from this snapshot.
    environment = {
        "inheritedEnvironment": sorted(os.environ.items()),
        "python": sys.version,
        "executables": executables,
    }
    return hashlib.sha256(json.dumps(environment, ensure_ascii=True, sort_keys=True).encode()).hexdigest()


def _execution(root: Path, step_id: str) -> dict[str, str] | None:
    """Привязать checkpoint к единственной активной IMPLEMENT/FIX execution."""
    from execution_status import active_execution_for_command
    matches = []
    for operation in ("IMPLEMENT", "FIX"):
        owner = active_execution_for_command(root, f"STEP {operation} {step_id}")
        if owner is not None:
            matches.append({key: owner[key] for key in ("executionId", "rootCommand")}
                           | {"command": f"STEP {operation} {step_id}"})
    if len(matches) > 1:
        raise ValueError("MANUAL_CONTINUATION_EXECUTION_AMBIGUOUS")
    return matches[0] if matches else None


def _policy(root: Path, step_id: str, names: list[str]) -> dict[str, Any]:
    """Отделить локальные проверки от mutable external state до запуска команд.

    High-risk STEP требует project-owned декларацию. Read-only относится ко
    всем manual/product observations; изменяющая состояние процедура требует full.
    """
    from harness_config import get, load_manifest
    flags = read_task(root, step_id)["frontmatter"].get("risk_flags", [])
    high_risk = bool(NON_REUSABLE_FLAGS.intersection(flags))
    configured = get(load_manifest(root), "verification.manualContinuation", {})
    if not isinstance(configured, dict):
        raise ValueError("MANUAL_CONTINUATION_POLICY_INVALID")
    policy = configured.get(step_id)
    if policy is None:
        if high_risk:
            raise ValueError("MANUAL_CONTINUATION_POLICY_REQUIRED")
        return {"readOnly": True, "localCommands": names, "repeatCommands": []}
    if (not isinstance(policy, dict)
            or set(policy) != {"readOnly", "localCommands", "repeatCommands"}
            or not isinstance(policy["readOnly"], bool)):
        raise ValueError("MANUAL_CONTINUATION_POLICY_INVALID")
    local, repeat = policy["localCommands"], policy["repeatCommands"]
    if (not isinstance(local, list) or not isinstance(repeat, list)
            or any(not isinstance(name, str) for name in local + repeat)
            or len(set(local + repeat)) != len(local + repeat)
            or set(local + repeat) != set(names)):
        raise ValueError("MANUAL_CONTINUATION_COMMAND_COVERAGE_INVALID")
    if not policy["readOnly"]:
        raise ValueError("MANUAL_CONTINUATION_STATE_CHANGED")
    if high_risk and _execution(root, step_id) is None:
        raise ValueError("MANUAL_CONTINUATION_EXECUTION_REQUIRED")
    return policy


def _safe_path(root: Path, step_id: str) -> Path:
    """Не читать и не записывать checkpoint через symlink любого предка."""
    path = _path(root, step_id)
    parts = [path]
    while parts[-1] != root:
        parts.append(parts[-1].parent)
    if any(part.is_symlink() for part in parts[:-1]):
        raise ValueError("MANUAL_CONTINUATION_SYMLINK")
    return path


def remember_pending(root: Path, step_id: str, *, result: dict[str, Any]) -> None:
    """Сохранить только опубликованный MANUAL_REQUIRED с producer-bound bytes.

    Partial/crash запись не даёт reuse: digest checkpoint закрепляется в proof
    последним. Исходный возраст сохраняется при нескольких manual дополнениях.
    """
    commands = result["commands"]
    forget_pending(root, step_id)
    if not commands or any(item.get("status") != "PASS" or item.get("exitCode") != 0
                           or item.get("composite") for item in commands):
        return
    names = [item["command"] for item in commands]
    try:
        policy = _policy(root, step_id, names)
        path = _safe_path(root, step_id)
        execution = _execution(root, step_id)
        environment = _environment_basis(names)
    except (OSError, ValueError):
        return
    if not environment or environment != result.get("automatedEnvironmentBasis"):
        return
    payload = {
        "schemaVersion": 2, "stepId": step_id,
        "recordedAt": result.get("automatedStageRecordedAt", time.time()),
        "runAt": result["runAt"], "execution": execution,
        "contractBasis": result["contractBasis"], "contextBasis": result["contextBasis"],
        "subjectRevision": result["subjectRevision"],
        "timeoutSeconds": result["timeoutSeconds"],
        "policy": policy, "environmentBasis": environment,
        "commands": [{key: value for key, value in item.items()
                      if key not in {"stdoutTail", "stderrTail"}} for item in commands],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = (json.dumps(payload, sort_keys=True) + "\n").encode()
    atomic_write_text(path, checkpoint.decode())
    from verification_proof import _safe_proof_path
    proof_path = _safe_proof_path(root, step_id)
    original = proof_path.read_bytes()
    proof = json.loads(original)
    if proof.get("status") != "MANUAL_REQUIRED" or proof.get("runAt") != result["runAt"]:
        return
    proof["manualCheckpointSha256"] = hashlib.sha256(checkpoint).hexdigest()
    atomic_write_text(proof_path, json.dumps(proof, sort_keys=True) + "\n", expected_bytes=original)


def continuation_plan(root: Path, step_id: str, *, contract: str, context: str,
                      subject: dict[str, Any], names: list[str], timeout: int) -> dict[str, Any]:
    """Read-only preflight: точные повторы и причина известны до side effects."""
    fallback = {"reused": {}, "executedChecks": names, "reusedChecks": []}
    try:
        policy = _policy(root, step_id, names)
        path = _safe_path(root, step_id)
        checkpoint = path.read_bytes()
        cached = json.loads(checkpoint)
        if not isinstance(cached, dict) or cached.get("schemaVersion") != 2:
            raise ValueError("MANUAL_CONTINUATION_CHECKPOINT_INVALID")
        recorded_at = cached.get("recordedAt")
        if (not isinstance(recorded_at, (int, float)) or isinstance(recorded_at, bool)
                or not 0 <= time.time() - recorded_at <= RESUME_TTL_SECONDS):
            raise ValueError("MANUAL_CONTINUATION_EXPIRED")
        current_inputs = {
            "stepId": step_id, "contractBasis": contract, "contextBasis": context,
            "subjectRevision": subject, "timeoutSeconds": timeout, "policy": policy,
            "execution": _execution(root, step_id), "environmentBasis": _environment_basis(names),
        }
        changed = [key for key, value in current_inputs.items() if cached.get(key) != value]
        if not cached.get("environmentBasis") and "environmentBasis" not in changed:
            changed.append("environmentBasis")
        if changed:
            # Публикуются только имена компонентов: values окружения и прочие
            # приватные входы остаются локальными, а причина повтора проверяема.
            return {**fallback, "reasonCode": "MANUAL_CONTINUATION_INPUTS_CHANGED",
                    "changedInputs": sorted(changed)}
        from verification import EVIDENCE_START, EVIDENCE_END
        from verification_proof import _safe_proof_path, verification_proof_error
        proof = json.loads(_safe_proof_path(root, step_id).read_bytes())
        section = read_task(root, step_id)["sections"].get("Evidence", "")
        block = re.search(re.escape(EVIDENCE_START) + "(.*?)" + re.escape(EVIDENCE_END), section, re.S)
        if (not isinstance(proof, dict) or block is None
                or verification_proof_error(root, step_id, block=block.group(1), status="MANUAL_REQUIRED")
                or proof.get("runAt") != cached.get("runAt")
                or proof.get("manualCheckpointSha256") != hashlib.sha256(checkpoint).hexdigest()):
            raise ValueError("MANUAL_CONTINUATION_PRODUCER_MISMATCH")
        commands = cached.get("commands")
        if (not isinstance(commands, list) or len(commands) != len(names)
                or any(not isinstance(item, dict) or item.get("command") != name
                       or item.get("status") != "PASS" or item.get("exitCode") != 0
                       for name, item in zip(names, commands))):
            raise ValueError("MANUAL_CONTINUATION_RESULTS_INVALID")
        reused = {item["command"]: item for item in commands
                  if item["command"] in policy["localCommands"]}
        return {"reused": reused, "executedChecks": policy["repeatCommands"],
                "reusedChecks": list(reused), "producerRunAt": cached["runAt"],
                "recordedAt": recorded_at, "execution": cached["execution"],
                "reasonCode": "MANUAL_CONTINUATION_EXTERNAL_STATE" if policy["repeatCommands"]
                              else "MANUAL_CONTINUATION_UNCHANGED"}
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        return {**fallback, "reasonCode": str(exc) if isinstance(exc, ValueError)
                else "MANUAL_CONTINUATION_CHECKPOINT_UNAVAILABLE"}


def forget_pending(root: Path, step_id: str) -> None:
    """Удалить только обычный checkpoint; symlink никогда не разыменовывать."""
    try:
        path = _safe_path(root, step_id)
        if path.is_file():
            path.unlink()
    except (OSError, ValueError):
        pass


def preview_pending(root: Path, step_id: str) -> dict[str, Any]:
    """Выдать компактный read-only план до expensive completion side effects."""
    from verification import (parse_verification, verification_contract_basis,
                              verification_context_basis, verification_subject_revision)
    from harness_config import verification_command_timeout_seconds
    plan = continuation_plan(
        root, step_id, contract=verification_contract_basis(root, step_id),
        context=verification_context_basis(root, step_id),
        subject=verification_subject_revision(root, step_id),
        names=[entry["value"] for entry in parse_verification(root, step_id)
               if entry["kind"] == "command"],
        timeout=verification_command_timeout_seconds(root),
    )
    return {key: value for key, value in plan.items() if key != "reused"}
