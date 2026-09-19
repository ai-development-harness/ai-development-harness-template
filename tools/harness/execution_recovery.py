#!/usr/bin/env python3
"""Crash-safe execution cursor and deterministic STEP recovery for Harness."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from uuid import uuid4

from command_transitions import load_transition_table, parse_canonical_command

RECOVERY_POLICY_PATH = ".project/execution-recovery.json"
DEFAULT_STATE_DIRECTORY = ".project/local/execution"
CONTRACT_METADATA = ("Type", "Depends on")
CONTRACT_SECTIONS = (
    "Requirements",
    "ADR",
    "Risk flags",
    "Goal",
    "Context",
    "Scope",
    "Mutation policy",
    "Out of scope",
    "Acceptance criteria",
    "Verification",
    "Deliverables",
)
COMPLETED_STATUSES = {"Выполнено", "Completed", "DONE"}
BLOCKED_STATUSES = {"Заблокировано", "Blocked", "BLOCKED"}
REVIEW_VERDICTS = {"PASS", "FAIL", "BLOCKED", "NOT REVIEWED"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_recovery_policy(root: Path) -> dict[str, Any]:
    path = root / RECOVERY_POLICY_PATH
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_recovery_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if policy.get("schemaVersion") != 1:
        errors.append("execution-recovery: schemaVersion must be 1")
    if policy.get("stateDirectory") != DEFAULT_STATE_DIRECTORY:
        errors.append(
            f"execution-recovery: stateDirectory must be {DEFAULT_STATE_DIRECTORY!r}"
        )
    if policy.get("authorityOrder") != [
        "canonical-artifacts",
        "local-execution-cursor",
    ]:
        errors.append(
            "execution-recovery: authorityOrder must be canonical-artifacts -> local-execution-cursor"
        )
    if policy.get("atomicWrites") is not True:
        errors.append("execution-recovery: atomicWrites must be true")
    if policy.get("interruptedDefault") != "retry-same-command":
        errors.append(
            "execution-recovery: interruptedDefault must be 'retry-same-command'"
        )

    step_run = policy.get("stepRun")
    if not isinstance(step_run, dict):
        return errors + ["execution-recovery: stepRun must be an object"]

    phases = step_run.get("phases")
    expected = {
        "PLAN": ("STEP PLAN STEP-NNN", "plan-ready-current-basis"),
        "IMPLEMENT": (
            "STEP IMPLEMENT STEP-NNN",
            "local-completed-checkpoint",
        ),
        "REVIEW": (
            "STEP REVIEW STEP-NNN",
            "new-immutable-review-report",
        ),
        "FIX": ("STEP FIX STEP-NNN", "local-completed-checkpoint"),
    }
    if not isinstance(phases, list):
        errors.append("execution-recovery: stepRun.phases must be an array")
        phases = []

    seen: set[str] = set()
    for phase in phases:
        if not isinstance(phase, dict):
            errors.append("execution-recovery: each phase must be an object")
            continue
        operation = phase.get("operation")
        if operation not in expected:
            errors.append(f"execution-recovery: unknown STEP phase {operation!r}")
            continue
        if operation in seen:
            errors.append(f"execution-recovery: duplicate STEP phase {operation}")
        seen.add(operation)
        command, proof = expected[operation]
        if phase.get("command") != command:
            errors.append(
                f"execution-recovery: {operation}.command must be {command!r}"
            )
        if phase.get("completionProof") != proof:
            errors.append(
                f"execution-recovery: {operation}.completionProof must be {proof!r}"
            )

    if seen != set(expected):
        errors.append(
            "execution-recovery: STEP phases must contain PLAN/IMPLEMENT/REVIEW/FIX exactly once"
        )
    if step_run.get("completionProof") != "step-status-completed":
        errors.append(
            "execution-recovery: stepRun.completionProof must be 'step-status-completed'"
        )
    if step_run.get("finalizeCommand") != "STEP RUN STEP-NNN":
        errors.append(
            "execution-recovery: stepRun.finalizeCommand must be 'STEP RUN STEP-NNN'"
        )
    if (
        step_run.get("fixReviewLimitSource")
        != ".project/manifest.yaml:execution.maxFixReviewCycles"
    ):
        errors.append(
            "execution-recovery: unexpected fixReviewLimitSource"
        )
    return errors


def _normalize_text(value: str) -> str:
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def parse_markdown(text: str) -> tuple[dict[str, str], dict[str, str]]:
    metadata: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in text.replace("\r\n", "\n").split("\n"):
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip()
            sections.setdefault(current, [])
            continue

        meta = re.match(r"^\*\*([^*]+?):\*\*\s*(.*)$", line)
        if meta:
            metadata[meta.group(1).strip()] = meta.group(2).strip()

        if current is not None:
            sections[current].append(line)

    return metadata, {
        name: _normalize_text("\n".join(lines))
        for name, lines in sections.items()
    }


def task_path(root: Path, step_id: str) -> Path:
    if not re.fullmatch(r"STEP-\d{3,}", step_id):
        raise ValueError(f"invalid STEP id: {step_id}")
    path = root / "planning/tasks" / f"{step_id}.md"
    if not path.is_file():
        raise FileNotFoundError(f"task file not found: {path.relative_to(root)}")
    return path


def read_task(root: Path, step_id: str) -> dict[str, Any]:
    path = task_path(root, step_id)
    text = path.read_text(encoding="utf-8")
    metadata, sections = parse_markdown(text)
    return {
        "path": path,
        "text": text,
        "metadata": metadata,
        "sections": sections,
    }


def contract_basis(root: Path, step_id: str) -> str:
    task = read_task(root, step_id)
    payload: dict[str, Any] = {
        "metadata": {
            key: task["metadata"].get(key, "")
            for key in CONTRACT_METADATA
        },
        "sections": {
            key: task["sections"].get(key, "")
            for key in CONTRACT_SECTIONS
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def plan_info(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    section = task["sections"].get("Implementation plan", "")
    fields, _ = parse_markdown(section)
    current_basis = contract_basis(root, step_id)
    stored_basis = fields.get("Plan basis", "")
    status = fields.get("Plan status", "")
    return {
        "status": status,
        "revision": fields.get("Plan revision", "—"),
        "storedBasis": stored_basis,
        "currentBasis": current_basis,
        "plannedAt": fields.get("Planned at", "—"),
        "ready": status == "Ready" and stored_basis == current_basis,
        "stale": status == "Ready" and stored_basis != current_basis,
    }


def _replace_plan_field(text: str, field: str, value: str) -> str:
    pattern = re.compile(
        rf"(?m)^\*\*{re.escape(field)}:\*\*\s*.*$"
    )
    replacement = f"**{field}:** {value}"
    if not pattern.search(text):
        raise ValueError(f"task Implementation plan missing field: {field}")
    return pattern.sub(replacement, text, count=1)


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def stamp_plan(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    info = plan_info(root, step_id)
    revision_raw = info["revision"]
    try:
        revision = int(revision_raw) + 1
    except (TypeError, ValueError):
        revision = 1

    basis = info["currentBasis"]
    updated = task["text"]
    updated = _replace_plan_field(updated, "Plan status", "Ready")
    updated = _replace_plan_field(updated, "Plan revision", str(revision))
    updated = _replace_plan_field(updated, "Plan basis", basis)
    updated = _replace_plan_field(updated, "Planned at", utc_now())
    _atomic_write_text(task["path"], updated)

    return {
        "stepId": step_id,
        "planStatus": "Ready",
        "planRevision": revision,
        "planBasis": basis,
    }


def _report_verdict(path: Path) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    metadata, _ = parse_markdown(text)
    verdict = metadata.get("Verdict")
    if verdict in REVIEW_VERDICTS:
        return verdict
    return None


def review_reports(root: Path, step_id: str) -> list[dict[str, Any]]:
    directory = root / "planning/reviews" / step_id
    if not directory.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("REVIEW-*.md")):
        verdict = _report_verdict(path)
        if verdict is None:
            continue
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "verdict": verdict,
                "mtime": path.stat().st_mtime,
            }
        )
    result.sort(key=lambda item: (item["mtime"], item["path"]))
    return result


def latest_review(root: Path, step_id: str) -> dict[str, Any] | None:
    task = read_task(root, step_id)
    configured = task["metadata"].get("Latest report", "")
    configured_path: Path | None = None
    if configured and configured not in {"—", "-"}:
        configured_path = root / configured
        verdict = _report_verdict(configured_path)
        if verdict is not None:
            return {
                "path": configured_path.relative_to(root).as_posix(),
                "verdict": verdict,
                "mtime": configured_path.stat().st_mtime,
            }

    reports = review_reports(root, step_id)
    return reports[-1] if reports else None


def max_fix_review_cycles(root: Path) -> int:
    manifest = root / ".project/manifest.yaml"
    text = manifest.read_text(encoding="utf-8")
    match = re.search(
        r"(?m)^\s*maxFixReviewCycles:\s*(\d+)\s*$",
        text,
    )
    if not match:
        raise ValueError(
            "manifest execution.maxFixReviewCycles is missing"
        )
    value = int(match.group(1))
    if not 1 <= value <= 5:
        raise ValueError(
            "manifest execution.maxFixReviewCycles must be in range 1..5"
        )
    return value


def _state_directory(root: Path) -> Path:
    policy = load_recovery_policy(root)
    return root / policy.get("stateDirectory", DEFAULT_STATE_DIRECTORY)


def execution_state_path(root: Path, step_id: str) -> Path:
    return _state_directory(root) / f"{step_id}.json"


def load_execution_state(root: Path, step_id: str) -> dict[str, Any] | None:
    path = execution_state_path(root, step_id)
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as fh:
        state = json.load(fh)
    if state.get("schemaVersion") != 1 or state.get("target") != step_id:
        raise ValueError(f"invalid execution state: {path.relative_to(root)}")
    return state


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    content = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    ) + "\n"
    _atomic_write_text(path, content)


def _new_state(step_id: str, root_command: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "schemaVersion": 1,
        "executionId": "exec-" + uuid4().hex,
        "target": step_id,
        "rootCommand": root_command,
        "status": "active",
        "cursor": None,
        "lastCompleted": None,
        "fixReviewCyclesUsed": 0,
        "createdAt": now,
        "updatedAt": now,
    }


def _parse_step_phase(root: Path, command: str) -> dict[str, Any]:
    table = load_transition_table(root)
    parsed = parse_canonical_command(command, table)
    if not parsed.get("valid"):
        raise ValueError(
            f"invalid canonical command: {parsed.get('code')} "
            f"{parsed.get('message')}"
        )
    if parsed.get("domain") != "STEP":
        raise ValueError("execution recovery currently supports STEP phases only")
    if parsed.get("operation") not in {"PLAN", "IMPLEMENT", "REVIEW", "FIX"}:
        raise ValueError(
            "execution cursor phase must be STEP PLAN/IMPLEMENT/REVIEW/FIX"
        )
    return parsed


def begin_phase(
    root: Path,
    step_id: str,
    command: str,
    *,
    root_command: str | None = None,
) -> dict[str, Any]:
    parsed = _parse_step_phase(root, command)
    if parsed.get("target") != step_id:
        raise ValueError(
            f"command target {parsed.get('target')} does not match {step_id}"
        )

    path = execution_state_path(root, step_id)
    state = load_execution_state(root, step_id)
    if state is None or state.get("status") == "completed":
        state = _new_state(step_id, root_command or command)
    elif root_command and state.get("rootCommand") != root_command:
        state["rootCommand"] = root_command

    cursor = state.get("cursor")
    if (
        isinstance(cursor, dict)
        and cursor.get("state") == "running"
        and cursor.get("command") != command
    ):
        raise ValueError(
            "another phase is marked running; resolve/recover it before "
            f"starting {command}: {cursor.get('command')}"
        )

    attempt = 1
    if (
        isinstance(cursor, dict)
        and cursor.get("command") == command
    ):
        attempt = int(cursor.get("attempt", 0)) + 1

    review = latest_review(root, step_id)
    context = {
        "planBasisAtStart": contract_basis(root, step_id),
        "reviewReportBefore": review["path"] if review else None,
        "sourceReview": review["path"] if parsed["operation"] == "FIX" and review else None,
    }

    if parsed["operation"] == "FIX" and not (
        isinstance(cursor, dict)
        and cursor.get("state") == "running"
        and cursor.get("command") == command
    ):
        state["fixReviewCyclesUsed"] = int(
            state.get("fixReviewCyclesUsed", 0)
        ) + 1

    state["status"] = "active"
    state["cursor"] = {
        "command": command,
        "operation": parsed["operation"],
        "state": "running",
        "attempt": attempt,
        "startedAt": utc_now(),
        "completedAt": None,
        "result": None,
        "context": context,
    }
    state["updatedAt"] = utc_now()
    _atomic_write_json(path, state)
    return state


def _activated_next_command(
    root: Path,
    operation: str,
    result: str,
    step_id: str,
) -> str | None:
    table = load_transition_table(root)
    domain = table["domains"]["STEP"]
    candidates = [
        edge
        for edge in domain.get("transitions", [])
        if edge.get("from") == operation
        and result in edge.get("onPreviousResult", [])
    ]
    if len(candidates) > 1:
        raise ValueError(
            f"ambiguous CTS recovery edge for STEP {operation} result {result}"
        )
    if not candidates:
        return None
    return f"STEP {candidates[0]['to']} {step_id}"


def complete_phase(
    root: Path,
    step_id: str,
    command: str,
    *,
    result: str,
) -> dict[str, Any]:
    if result not in {"SUCCESS", "PASS", "FAIL", "BLOCKED"}:
        raise ValueError("result must be SUCCESS/PASS/FAIL/BLOCKED")

    parsed = _parse_step_phase(root, command)
    path = execution_state_path(root, step_id)
    state = load_execution_state(root, step_id)
    if state is None:
        raise ValueError("execution state does not exist; call begin first")

    cursor = state.get("cursor")
    if not isinstance(cursor, dict) or cursor.get("command") != command:
        raise ValueError(
            f"current cursor does not match completion command: {command}"
        )

    completed_at = utc_now()
    completed = dict(cursor)
    completed["state"] = "completed"
    completed["completedAt"] = completed_at
    completed["result"] = result
    state["lastCompleted"] = completed

    next_command = _activated_next_command(
        root,
        parsed["operation"],
        result,
        step_id,
    )
    if result == "BLOCKED":
        state["status"] = "blocked"
    else:
        state["status"] = "active"

    state["cursor"] = (
        {
            "command": next_command,
            "operation": next_command.split()[1] if next_command else None,
            "state": "pending",
            "attempt": 0,
            "startedAt": None,
            "completedAt": None,
            "result": None,
            "context": {},
        }
        if next_command
        else {
            "command": command,
            "operation": parsed["operation"],
            "state": "completed",
            "attempt": completed.get("attempt", 1),
            "startedAt": completed.get("startedAt"),
            "completedAt": completed_at,
            "result": result,
            "context": completed.get("context", {}),
        }
    )
    state["updatedAt"] = utc_now()
    _atomic_write_json(path, state)
    return state


def finish_execution(
    root: Path,
    step_id: str,
    *,
    status: str,
) -> dict[str, Any]:
    if status not in {"completed", "blocked"}:
        raise ValueError("execution status must be completed or blocked")
    state = load_execution_state(root, step_id)
    if state is None:
        state = _new_state(step_id, f"STEP RUN {step_id}")
    state["status"] = status
    state["updatedAt"] = utc_now()
    _atomic_write_json(execution_state_path(root, step_id), state)
    return state


def _review_after_baseline(
    review: dict[str, Any] | None,
    baseline: str | None,
) -> bool:
    return review is not None and review.get("path") != baseline


def _fix_completed_for_review(
    state: dict[str, Any] | None,
    review: dict[str, Any] | None,
) -> bool:
    if state is None or review is None:
        return False
    completed = state.get("lastCompleted")
    if not isinstance(completed, dict):
        return False
    return (
        completed.get("operation") == "FIX"
        and completed.get("result") == "SUCCESS"
        and completed.get("context", {}).get("sourceReview") == review.get("path")
    )


def _result(
    status: str,
    step_id: str,
    *,
    command: str | None,
    reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "status": status,
        "stepId": step_id,
        "command": command,
        "reasonCode": reason,
    }
    if details:
        value["details"] = details
    return value


def resolve_step(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    task_status = task["metadata"].get("Статус") or task["metadata"].get("Status", "")
    plan = plan_info(root, step_id)
    state = load_execution_state(root, step_id)
    review = latest_review(root, step_id)
    reports = review_reports(root, step_id)
    fail_count = sum(1 for item in reports if item["verdict"] == "FAIL")
    limit = max_fix_review_cycles(root)

    if task_status in COMPLETED_STATUSES:
        return _result(
            "DONE",
            step_id,
            command=None,
            reason="STEP_COMPLETED",
        )

    cursor = state.get("cursor") if state else None
    if isinstance(cursor, dict) and cursor.get("state") == "running":
        operation = cursor.get("operation")
        command = cursor.get("command")

        if operation == "PLAN":
            if plan["ready"]:
                return _result(
                    "NEXT",
                    step_id,
                    command=f"STEP IMPLEMENT {step_id}",
                    reason="PLAN_PROVEN_AFTER_INTERRUPTION",
                    details={"planBasis": plan["currentBasis"]},
                )
            return _result(
                "RESUME",
                step_id,
                command=command,
                reason="INTERRUPTED_PLAN",
            )

        if operation == "IMPLEMENT":
            if not plan["ready"]:
                return _result(
                    "REPLAN",
                    step_id,
                    command=f"STEP PLAN {step_id}",
                    reason="PLAN_STALE_DURING_IMPLEMENT",
                    details={
                        "storedBasis": plan["storedBasis"],
                        "currentBasis": plan["currentBasis"],
                    },
                )
            return _result(
                "RESUME",
                step_id,
                command=command,
                reason="INTERRUPTED_IMPLEMENT",
            )

        if operation == "REVIEW":
            baseline = cursor.get("context", {}).get("reviewReportBefore")
            if _review_after_baseline(review, baseline):
                return _resolve_review_result(
                    root,
                    step_id,
                    review,
                    state,
                    fail_count,
                    limit,
                    task_status,
                )
            return _result(
                "RESUME",
                step_id,
                command=command,
                reason="INTERRUPTED_REVIEW",
            )

        if operation == "FIX":
            return _result(
                "RESUME",
                step_id,
                command=command,
                reason="INTERRUPTED_FIX",
            )

    if not plan["ready"]:
        return _result(
            "NEXT",
            step_id,
            command=f"STEP PLAN {step_id}",
            reason="PLAN_STALE" if plan["stale"] else "PLAN_MISSING",
            details={
                "storedBasis": plan["storedBasis"],
                "currentBasis": plan["currentBasis"],
            },
        )

    if review is not None:
        resolved = _resolve_review_result(
            root,
            step_id,
            review,
            state,
            fail_count,
            limit,
            task_status,
        )
        if resolved["status"] != "NO_DECISION":
            return resolved

    if state:
        completed = state.get("lastCompleted")
        if isinstance(completed, dict):
            if (
                completed.get("operation") == "IMPLEMENT"
                and completed.get("result") == "SUCCESS"
            ):
                return _result(
                    "NEXT",
                    step_id,
                    command=f"STEP REVIEW {step_id}",
                    reason="IMPLEMENT_COMPLETED",
                )

    if task_status in BLOCKED_STATUSES:
        return _result(
            "BLOCKED",
            step_id,
            command=None,
            reason="STEP_BLOCKED",
        )

    return _result(
        "NEXT",
        step_id,
        command=f"STEP IMPLEMENT {step_id}",
        reason=(
            "CONSERVATIVE_IMPLEMENT_RESUME"
            if task_status == "В работе"
            else "PLAN_READY"
        ),
        details={"planBasis": plan["currentBasis"]},
    )


def _resolve_review_result(
    root: Path,
    step_id: str,
    review: dict[str, Any],
    state: dict[str, Any] | None,
    fail_count: int,
    limit: int,
    task_status: str,
) -> dict[str, Any]:
    verdict = review["verdict"]
    if verdict == "FAIL":
        if _fix_completed_for_review(state, review):
            return _result(
                "NEXT",
                step_id,
                command=f"STEP REVIEW {step_id}",
                reason="FIX_COMPLETED",
                details={"sourceReview": review["path"]},
            )
        if fail_count > limit:
            return _result(
                "BLOCKED",
                step_id,
                command=None,
                reason="FIX_REVIEW_LIMIT_EXHAUSTED",
                details={
                    "failReviews": fail_count,
                    "maxFixReviewCycles": limit,
                    "latestReview": review["path"],
                },
            )
        return _result(
            "NEXT",
            step_id,
            command=f"STEP FIX {step_id}",
            reason="LATEST_REVIEW_FAIL",
            details={
                "latestReview": review["path"],
                "requestedFixCycle": fail_count,
                "maxFixReviewCycles": limit,
            },
        )

    if verdict == "BLOCKED":
        return _result(
            "BLOCKED",
            step_id,
            command=None,
            reason="LATEST_REVIEW_BLOCKED",
            details={"latestReview": review["path"]},
        )

    if verdict == "PASS":
        if task_status in COMPLETED_STATUSES:
            return _result(
                "DONE",
                step_id,
                command=None,
                reason="STEP_COMPLETED",
            )
        return _result(
            "RESUME",
            step_id,
            command=f"STEP RUN {step_id}",
            reason="FINALIZE_AFTER_PASS",
            details={"latestReview": review["path"]},
        )

    return _result(
        "NO_DECISION",
        step_id,
        command=None,
        reason="REVIEW_NOT_ACTIONABLE",
    )


def active_recovery_candidates(root: Path) -> list[dict[str, Any]]:
    directory = _state_directory(root)
    if not directory.is_dir():
        return []
    candidates: list[tuple[str, dict[str, Any]]] = []
    for path in directory.glob("STEP-*.json"):
        try:
            with path.open("r", encoding="utf-8") as fh:
                state = json.load(fh)
            if state.get("status") not in {"active", "blocked"}:
                continue
            step_id = state.get("target")
            if not isinstance(step_id, str):
                continue
            resolved = resolve_step(root, step_id)
            resolved["executionUpdatedAt"] = state.get("updatedAt")
            candidates.append((state.get("updatedAt") or "", resolved))
        except (OSError, ValueError, json.JSONDecodeError, FileNotFoundError):
            continue
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in candidates]
