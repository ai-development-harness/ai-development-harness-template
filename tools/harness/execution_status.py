#!/usr/bin/env python3
"""Universal crash-safe execution status for AI Development Harness."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any
from uuid import uuid4

from command_transitions import (
    load_transition_table,
    parse_canonical_command,
    validate_command_text,
)

STATUS_PATH = ".project/local/execution/execution-status.json"
EXECUTION_MODES = {"single", "chain", "orchestration"}
EXECUTION_STATUSES = {"running", "complete", "blocked"}
COMMAND_STATUSES = {"running", "complete", "blocked"}
RESULTS = {"SUCCESS", "PASS", "FAIL", "BLOCKED"}

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
REVIEW_VERDICTS = {"PASS", "FAIL", "BLOCKED", "NOT REVIEWED"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def status_path(root: Path) -> Path:
    return root / STATUS_PATH


def empty_status() -> dict[str, Any]:
    return {"schemaVersion": 1, "executions": []}


def load_status(root: Path) -> dict[str, Any]:
    path = status_path(root)
    if not path.is_file():
        return empty_status()
    with path.open("r", encoding="utf-8") as fh:
        value = json.load(fh)
    errors = validate_status(value)
    if errors:
        raise ValueError("; ".join(errors))
    return value


def validate_status(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if value.get("schemaVersion") != 1:
        errors.append("execution-status: schemaVersion must be 1")
    executions = value.get("executions")
    if not isinstance(executions, list):
        return errors + ["execution-status: executions must be an array"]

    ids: set[str] = set()
    for index, execution in enumerate(executions):
        prefix = f"execution-status.executions[{index}]"
        if not isinstance(execution, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        execution_id = execution.get("executionId")
        if not isinstance(execution_id, str) or not execution_id:
            errors.append(f"{prefix}: executionId must be non-empty")
        elif execution_id in ids:
            errors.append(f"{prefix}: duplicate executionId {execution_id}")
        else:
            ids.add(execution_id)

        if execution.get("mode") not in EXECUTION_MODES:
            errors.append(f"{prefix}: invalid mode")
        if execution.get("status") not in EXECUTION_STATUSES:
            errors.append(f"{prefix}: invalid status")
        if not isinstance(execution.get("rootCommand"), str) or not execution.get("rootCommand"):
            errors.append(f"{prefix}: rootCommand must be non-empty")

        sequence = execution.get("sequence")
        if not isinstance(sequence, list) or any(
            not isinstance(item, str) or not item for item in sequence
        ):
            errors.append(f"{prefix}: sequence must be a non-empty string array")

        current = execution.get("current")
        if not isinstance(current, dict):
            errors.append(f"{prefix}: current must be an object")
            continue
        if not isinstance(current.get("command"), str) or not current.get("command"):
            errors.append(f"{prefix}: current.command must be non-empty")
        if current.get("status") not in COMMAND_STATUSES:
            errors.append(f"{prefix}: invalid current.status")
        result = current.get("result")
        if result is not None and result not in RESULTS:
            errors.append(f"{prefix}: invalid current.result")
        attempt = current.get("attempt")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            errors.append(f"{prefix}: current.attempt must be >= 1")
    return errors


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
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


def save_status(root: Path, value: dict[str, Any]) -> None:
    errors = validate_status(value)
    if errors:
        raise ValueError("; ".join(errors))
    _atomic_write_json(status_path(root), value)


def _normalize_root(root: Path, raw: str) -> dict[str, Any]:
    table = load_transition_table(root)
    result = validate_command_text(raw, table)
    if not result.get("valid"):
        raise ValueError(
            f"{result.get('code')}: {result.get('message', 'invalid command')}"
        )
    normalized = result["normalized"]
    root_command = " > ".join(normalized)
    first = parse_canonical_command(normalized[0], table)
    if not first.get("valid"):
        raise ValueError("normalized root command failed canonical parser")

    if len(normalized) > 1:
        mode = "chain"
    elif first.get("domain") == "STEP" and first.get("operation") == "RUN":
        mode = "orchestration"
    else:
        mode = "single"

    return {
        "mode": mode,
        "rootCommand": root_command,
        "sequence": normalized,
        "first": first,
    }


def normalize_single_command(root: Path, raw: str) -> dict[str, Any]:
    table = load_transition_table(root)
    parsed = parse_canonical_command(raw, table)
    if not parsed.get("valid"):
        raise ValueError(
            f"{parsed.get('code')}: {parsed.get('message', 'invalid command')}"
        )
    return parsed


def _latest_execution(
    status: dict[str, Any],
    *,
    root_command: str | None = None,
    execution_id: str | None = None,
    statuses: set[str] | None = None,
) -> dict[str, Any] | None:
    candidates = status.get("executions", [])
    for item in reversed(candidates):
        if execution_id is not None and item.get("executionId") != execution_id:
            continue
        if root_command is not None and item.get("rootCommand") != root_command:
            continue
        if statuses is not None and item.get("status") not in statuses:
            continue
        return item
    return None


def _git_head(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _command_context(root: Path, command: str) -> dict[str, Any]:
    parsed = normalize_single_command(root, command)
    context: dict[str, Any] = {}

    if parsed.get("domain") == "STEP" and parsed.get("target"):
        step_id = parsed["target"]
        if parsed.get("operation") in {"PLAN", "IMPLEMENT", "REVIEW", "FIX"}:
            try:
                context["planBasisAtStart"] = contract_basis(root, step_id)
            except (OSError, ValueError, FileNotFoundError):
                pass
        if parsed.get("operation") == "REVIEW":
            review = latest_review(root, step_id)
            context["reviewReportBefore"] = review["path"] if review else None

    if parsed.get("domain") == "GIT" and parsed.get("operation") == "COMMIT":
        context["gitHeadBefore"] = _git_head(root)

    return context


def start_execution(root: Path, raw_command: str) -> dict[str, Any]:
    normalized = _normalize_root(root, raw_command)
    status = load_status(root)

    existing = _latest_execution(
        status,
        root_command=normalized["rootCommand"],
        statuses={"running"},
    )
    if existing is not None:
        current = existing["current"]
        if current.get("status") == "running":
            current["attempt"] = int(current.get("attempt", 1)) + 1
            current["startedAt"] = utc_now()
            existing["updatedAt"] = utc_now()
            save_status(root, status)
        return existing

    now = utc_now()
    first_command = normalized["sequence"][0]
    execution = {
        "executionId": "exec-" + uuid4().hex,
        "mode": normalized["mode"],
        "requestedCommand": raw_command.strip(),
        "rootCommand": normalized["rootCommand"],
        "sequence": normalized["sequence"],
        "currentIndex": 0 if normalized["mode"] in {"single", "chain"} else None,
        "status": "running",
        "current": {
            "command": first_command if normalized["mode"] != "orchestration" else normalized["rootCommand"],
            "status": "running",
            "result": None,
            "attempt": 1,
            "startedAt": now,
            "completedAt": None,
            "context": _command_context(
                root,
                first_command if normalized["mode"] != "orchestration" else normalized["rootCommand"],
            ),
        },
        "notExecuted": [],
        "startedAt": now,
        "completedAt": None,
        "updatedAt": now,
    }
    status["executions"].append(execution)
    save_status(root, status)
    return execution


def _edge_for(
    root: Path,
    from_command: str,
    to_command: str,
) -> dict[str, Any] | None:
    table = load_transition_table(root)
    left = parse_canonical_command(from_command, table)
    right = parse_canonical_command(to_command, table)
    if not left.get("valid") or not right.get("valid"):
        return None
    if left.get("domain") != right.get("domain"):
        return None
    domain = table["domains"][left["domain"]]
    for edge in domain.get("transitions", []):
        if edge.get("from") == left.get("operation") and edge.get("to") == right.get("operation"):
            return edge
    return None


def _build_next_from_edge(
    root: Path,
    current_command: str,
    edge: dict[str, Any],
) -> str:
    table = load_transition_table(root)
    parsed = parse_canonical_command(current_command, table)
    domain_name = parsed["domain"]
    spec = table["domains"][domain_name]["commands"][edge["to"]]
    canonical = spec["canonical"]

    if spec.get("target") == "step":
        target = parsed.get("target")
        if not target:
            raise ValueError("STEP transition lost target")
        canonical = canonical.replace("STEP-NNN", target)
    elif spec.get("target") == "release-optional":
        target = parsed.get("target")
        if target:
            canonical = f"{canonical} TO {target}"
    return canonical.rstrip(":")


def _mark_root_complete(execution: dict[str, Any], *, blocked: bool = False) -> None:
    execution["status"] = "blocked" if blocked else "complete"
    execution["completedAt"] = utc_now()
    execution["updatedAt"] = utc_now()


def complete_command(
    root: Path,
    root_command: str,
    command: str,
    result: str,
) -> dict[str, Any]:
    if result not in RESULTS:
        raise ValueError(f"result must be one of {sorted(RESULTS)}")

    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    normalized_command = normalize_single_command(root, command)["normalized"]
    status = load_status(root)
    execution = _latest_execution(
        status,
        root_command=normalized_root,
        statuses={"running", "blocked"},
    )
    if execution is None:
        raise ValueError(f"active execution not found for {normalized_root}")

    current = execution["current"]
    if current.get("command") != normalized_command:
        raise ValueError(
            f"current command is {current.get('command')}, not {normalized_command}"
        )
    if current.get("status") != "running":
        raise ValueError("current command is not running")

    current["status"] = "blocked" if result == "BLOCKED" else "complete"
    current["result"] = result
    current["completedAt"] = utc_now()
    execution["updatedAt"] = utc_now()

    if result == "BLOCKED":
        _mark_root_complete(execution, blocked=True)
        save_status(root, status)
        return execution

    mode = execution["mode"]
    if mode == "single":
        _mark_root_complete(execution)
    elif mode == "chain":
        index = int(execution["currentIndex"])
        sequence = execution["sequence"]
        if index + 1 >= len(sequence):
            _mark_root_complete(execution)
        else:
            next_command = sequence[index + 1]
            edge = _edge_for(root, current["command"], next_command)
            if edge is None or result not in edge.get("onPreviousResult", []):
                execution["notExecuted"] = sequence[index + 1 :]
                _mark_root_complete(execution)
    elif mode == "orchestration":
        if current["command"] == execution["rootCommand"]:
            _mark_root_complete(execution)

    save_status(root, status)
    return execution


def _orchestration_first_child_allowed(
    root: Path,
    execution: dict[str, Any],
    command: str,
) -> bool:
    table = load_transition_table(root)
    root_parsed = parse_canonical_command(execution["rootCommand"], table)
    child = parse_canonical_command(command, table)
    if not root_parsed.get("valid") or not child.get("valid"):
        return False
    if root_parsed.get("domain") != "STEP" or root_parsed.get("operation") != "RUN":
        return False
    if child.get("domain") != "STEP":
        return False
    if child.get("target") != root_parsed.get("target"):
        return False
    return child.get("operation") in {"PLAN", "IMPLEMENT", "REVIEW", "FIX", "AUDIT"}


def begin_command(
    root: Path,
    root_command: str,
    command: str,
) -> dict[str, Any]:
    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    normalized_command = normalize_single_command(root, command)["normalized"]
    status = load_status(root)
    execution = _latest_execution(
        status,
        root_command=normalized_root,
        statuses={"running"},
    )
    if execution is None:
        execution = start_execution(root, root_command)
        status = load_status(root)
        execution = _latest_execution(
            status,
            root_command=normalized_root,
            statuses={"running"},
        )
        assert execution is not None

    current = execution["current"]
    if current.get("command") == normalized_command and current.get("status") == "running":
        current["attempt"] = int(current.get("attempt", 1)) + 1
        current["startedAt"] = utc_now()
        current["context"] = _command_context(root, normalized_command)
        execution["updatedAt"] = utc_now()
        save_status(root, status)
        return execution

    if execution["mode"] == "single":
        raise ValueError("single execution cannot switch to another command")

    resolved = resolve_execution(root, execution, mutate=False)
    expected = resolved.get("command")

    allow_first_orchestration_child = (
        execution["mode"] == "orchestration"
        and current.get("command") == execution["rootCommand"]
        and current.get("status") == "running"
        and _orchestration_first_child_allowed(root, execution, normalized_command)
    )

    if not allow_first_orchestration_child and expected != normalized_command:
        raise ValueError(
            f"resolver expects {expected!r}, cannot begin {normalized_command!r}"
        )

    if execution["mode"] == "chain":
        sequence = execution["sequence"]
        index = sequence.index(normalized_command)
        execution["currentIndex"] = index

    execution["current"] = {
        "command": normalized_command,
        "status": "running",
        "result": None,
        "attempt": 1,
        "startedAt": utc_now(),
        "completedAt": None,
        "context": _command_context(root, normalized_command),
    }
    execution["updatedAt"] = utc_now()
    save_status(root, status)
    return execution


def block_execution(
    root: Path,
    root_command: str,
    *,
    command: str | None = None,
) -> dict[str, Any]:
    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    status = load_status(root)
    execution = _latest_execution(
        status,
        root_command=normalized_root,
        statuses={"running"},
    )
    if execution is None:
        raise ValueError(f"active execution not found for {normalized_root}")
    current = execution["current"]
    if command is not None:
        normalized_command = normalize_single_command(root, command)["normalized"]
        if current.get("command") != normalized_command:
            raise ValueError("block command does not match current command")
    current["status"] = "blocked"
    current["result"] = "BLOCKED"
    current["completedAt"] = utc_now()
    _mark_root_complete(execution, blocked=True)
    save_status(root, status)
    return execution


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


def contract_snapshot(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    return {
        "metadata": {
            key: task["metadata"].get(key, "")
            for key in CONTRACT_METADATA
        },
        "sections": {
            key: task["sections"].get(key, "")
            for key in CONTRACT_SECTIONS
        },
    }


def contract_basis(root: Path, step_id: str) -> str:
    encoded = json.dumps(
        contract_snapshot(root, step_id),
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
    plan_status = fields.get("Plan status", "")
    return {
        "status": plan_status,
        "storedBasis": stored_basis,
        "currentBasis": current_basis,
        "ready": plan_status == "Ready" and stored_basis == current_basis,
    }


def _replace_plan_field(text: str, field: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^\*\*{re.escape(field)}:\*\*\s*.*$")
    replacement = f"**{field}:** {value}"
    if not pattern.search(text):
        raise ValueError(f"task Implementation plan missing field: {field}")
    return pattern.sub(replacement, text, count=1)


def stamp_plan(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    section = task["sections"].get("Implementation plan", "")
    fields, _ = parse_markdown(section)
    try:
        revision = int(fields.get("Plan revision", "—")) + 1
    except (TypeError, ValueError):
        revision = 1
    basis = contract_basis(root, step_id)
    updated = task["text"]
    updated = _replace_plan_field(updated, "Plan status", "Ready")
    updated = _replace_plan_field(updated, "Plan revision", str(revision))
    updated = _replace_plan_field(updated, "Plan basis", basis)
    updated = _replace_plan_field(updated, "Planned at", utc_now())
    fd, tmp_name = tempfile.mkstemp(
        prefix=task["path"].name + ".",
        suffix=".tmp",
        dir=str(task["path"].parent),
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(updated)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, task["path"])
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return {
        "stepId": step_id,
        "planStatus": "Ready",
        "planRevision": revision,
        "planBasis": basis,
    }


def _review_verdict(path: Path) -> str | None:
    if not path.is_file():
        return None
    metadata, _ = parse_markdown(path.read_text(encoding="utf-8"))
    verdict = metadata.get("Verdict")
    return verdict if verdict in REVIEW_VERDICTS else None


def review_reports(root: Path, step_id: str) -> list[dict[str, Any]]:
    directory = root / "planning/reviews" / step_id
    if not directory.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("REVIEW-*.md")):
        verdict = _review_verdict(path)
        if verdict is not None:
            result.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "verdict": verdict,
                }
            )
    return result


def latest_review(root: Path, step_id: str) -> dict[str, Any] | None:
    reports = review_reports(root, step_id)
    return reports[-1] if reports else None


def _durable_recovery_result(
    root: Path,
    execution: dict[str, Any],
) -> str | None:
    current = execution["current"]
    if current.get("status") != "running":
        return None
    parsed = normalize_single_command(root, current["command"])

    if parsed.get("domain") == "STEP" and parsed.get("operation") == "PLAN":
        target = parsed.get("target")
        if target:
            try:
                if plan_info(root, target)["ready"]:
                    return "SUCCESS"
            except (OSError, ValueError, FileNotFoundError):
                return None

    if parsed.get("domain") == "STEP" and parsed.get("operation") == "REVIEW":
        target = parsed.get("target")
        baseline = current.get("context", {}).get("reviewReportBefore")
        if target:
            review = latest_review(root, target)
            if review is not None and review.get("path") != baseline:
                verdict = review.get("verdict")
                if verdict in {"PASS", "FAIL", "BLOCKED"}:
                    return verdict

    if parsed.get("domain") == "GIT" and parsed.get("operation") == "COMMIT":
        before = current.get("context", {}).get("gitHeadBefore")
        now = _git_head(root)
        if before and now and before != now:
            return "SUCCESS"

    return None


def _apply_recovered_completion(
    root: Path,
    status: dict[str, Any],
    execution: dict[str, Any],
    result: str,
) -> None:
    current = execution["current"]
    current["status"] = "blocked" if result == "BLOCKED" else "complete"
    current["result"] = result
    current["completedAt"] = utc_now()
    current["recoveredFromDurableState"] = True
    execution["updatedAt"] = utc_now()

    if result == "BLOCKED":
        _mark_root_complete(execution, blocked=True)
    elif execution["mode"] == "single":
        _mark_root_complete(execution)
    elif execution["mode"] == "chain":
        index = int(execution["currentIndex"])
        sequence = execution["sequence"]
        if index + 1 >= len(sequence):
            _mark_root_complete(execution)
        else:
            edge = _edge_for(root, current["command"], sequence[index + 1])
            if edge is None or result not in edge.get("onPreviousResult", []):
                execution["notExecuted"] = sequence[index + 1 :]
                _mark_root_complete(execution)
    elif execution["mode"] == "orchestration" and current["command"] == execution["rootCommand"]:
        _mark_root_complete(execution)
    save_status(root, status)


def resolve_execution(
    root: Path,
    execution: dict[str, Any],
    *,
    mutate: bool = True,
) -> dict[str, Any]:
    if execution.get("status") == "complete":
        return {
            "status": "DONE",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": None,
            "reasonCode": "EXECUTION_COMPLETE",
        }
    if execution.get("status") == "blocked":
        return {
            "status": "BLOCKED",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": None,
            "reasonCode": "EXECUTION_BLOCKED",
        }

    current = execution["current"]
    if current.get("status") == "running":
        recovered = _durable_recovery_result(root, execution)
        if recovered is not None and mutate:
            status = load_status(root)
            stored = _latest_execution(
                status,
                execution_id=execution["executionId"],
            )
            if stored is not None:
                _apply_recovered_completion(root, status, stored, recovered)
                return resolve_execution(root, stored, mutate=False)
        return {
            "status": "RESUME",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": current["command"],
            "reasonCode": "COMMAND_INTERRUPTED",
            "attempt": current.get("attempt", 1),
        }

    if current.get("status") == "blocked":
        return {
            "status": "BLOCKED",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": None,
            "reasonCode": "COMMAND_BLOCKED",
        }

    result = current.get("result")
    if execution["mode"] == "single":
        return {
            "status": "DONE",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": None,
            "reasonCode": "SINGLE_COMMAND_COMPLETE",
        }

    if execution["mode"] == "chain":
        index = int(execution["currentIndex"])
        sequence = execution["sequence"]
        if index + 1 >= len(sequence):
            return {
                "status": "DONE",
                "executionId": execution["executionId"],
                "rootCommand": execution["rootCommand"],
                "command": None,
                "reasonCode": "CHAIN_COMPLETE",
            }
        next_command = sequence[index + 1]
        edge = _edge_for(root, current["command"], next_command)
        if edge is None or result not in edge.get("onPreviousResult", []):
            return {
                "status": "DONE",
                "executionId": execution["executionId"],
                "rootCommand": execution["rootCommand"],
                "command": None,
                "reasonCode": "CHAIN_CONDITION_NOT_MET",
                "notExecuted": sequence[index + 1 :],
            }
        return {
            "status": "NEXT",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": next_command,
            "reasonCode": "CHAIN_NEXT_SEGMENT",
            "runtimePreconditions": edge.get("runtimePreconditions", []),
        }

    # STEP RUN is the only current orchestration command. Child transitions
    # use the same CTS as manually entered STEP chains.
    if execution["mode"] == "orchestration":
        if current["command"] == execution["rootCommand"]:
            return {
                "status": "RESUME",
                "executionId": execution["executionId"],
                "rootCommand": execution["rootCommand"],
                "command": execution["rootCommand"],
                "reasonCode": "ORCHESTRATION_ROOT_INTERRUPTED",
            }

        table = load_transition_table(root)
        parsed = parse_canonical_command(current["command"], table)
        domain = table["domains"].get(parsed.get("domain"), {})
        candidates = [
            edge
            for edge in domain.get("transitions", [])
            if edge.get("from") == parsed.get("operation")
            and result in edge.get("onPreviousResult", [])
        ]
        if len(candidates) == 1:
            next_command = _build_next_from_edge(root, current["command"], candidates[0])
            return {
                "status": "NEXT",
                "executionId": execution["executionId"],
                "rootCommand": execution["rootCommand"],
                "command": next_command,
                "reasonCode": "ORCHESTRATION_CTS_TRANSITION",
                "runtimePreconditions": candidates[0].get("runtimePreconditions", []),
            }
        if len(candidates) > 1:
            return {
                "status": "BLOCKED",
                "executionId": execution["executionId"],
                "rootCommand": execution["rootCommand"],
                "command": None,
                "reasonCode": "AMBIGUOUS_CTS_TRANSITION",
            }
        return {
            "status": "RESUME",
            "executionId": execution["executionId"],
            "rootCommand": execution["rootCommand"],
            "command": execution["rootCommand"],
            "reasonCode": "ORCHESTRATION_CONTINUE",
        }

    raise ValueError(f"unsupported execution mode: {execution['mode']}")


def resolve_root(root: Path, root_command: str) -> dict[str, Any]:
    normalized_root = _normalize_root(root, root_command)["rootCommand"]
    status = load_status(root)
    execution = _latest_execution(
        status,
        root_command=normalized_root,
        statuses={"running", "blocked"},
    )
    if execution is None:
        completed = _latest_execution(
            status,
            root_command=normalized_root,
            statuses={"complete"},
        )
        if completed is not None:
            return resolve_execution(root, completed)
        return {
            "status": "NOT_FOUND",
            "rootCommand": normalized_root,
            "command": None,
            "reasonCode": "EXECUTION_NOT_FOUND",
        }
    return resolve_execution(root, execution)


def unresolved_executions(root: Path) -> list[dict[str, Any]]:
    status = load_status(root)
    values: list[dict[str, Any]] = []
    for execution in status.get("executions", []):
        if execution.get("status") in {"running", "blocked"}:
            resolved = resolve_execution(root, execution)
            resolved["mode"] = execution["mode"]
            resolved["updatedAt"] = execution["updatedAt"]
            values.append(resolved)
    values.sort(key=lambda item: item.get("updatedAt") or "", reverse=True)
    return values


def find_completed(
    root: Path,
    command: str,
    *,
    result: str | None = None,
) -> dict[str, Any] | None:
    normalized = normalize_single_command(root, command)["normalized"]
    status = load_status(root)
    for execution in reversed(status.get("executions", [])):
        current = execution.get("current", {})
        if (
            current.get("command") == normalized
            and current.get("status") == "complete"
            and (result is None or current.get("result") == result)
        ):
            return execution
    return None
