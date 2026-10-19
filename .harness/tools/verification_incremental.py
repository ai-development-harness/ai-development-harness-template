#!/usr/bin/env python3
"""Консервативное переиспользование отдельных Verification-команд.

Карта влияния принадлежит проекту и требует проверки при PLAN. Если Core не
может доказать актуальность *каждой* сохранённой проверки, он выбирает полный
прогон. Верификационный PASS по-прежнему создаёт штатный Evidence writer.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from document_contract import atomic_write_text
from harness_config import get, load_manifest, resolve_repo_path
from planning_contract import read_task, task_path
from verification_resume import NON_REUSABLE_FLAGS, _environment_basis

STATE_VERSION = 1
POLICY_VERSION = 1
STATE_DIRECTORY = ".harness/local/verification-incremental"
_CHECK_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_GLOB = re.compile(r"[A-Za-z0-9._/@*?+\-]+\Z")
_HASH = re.compile(r"sha256:[a-f0-9]{64}\Z")


class IncrementalError(ValueError):
    """Недостоверный checkpoint/impact map; требуется полный Verification."""


def _run(root: Path, *args: str) -> bytes:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    if proc.returncode:
        raise IncrementalError(f"git {args[0]} failed: {proc.stderr[:250]!r}")
    return proc.stdout


def _digest(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _state_path(root: Path, step_id: str) -> Path:
    if not re.fullmatch(r"STEP-\d{3,}", step_id):
        raise IncrementalError("invalid STEP identifier")
    path = root / STATE_DIRECTORY / f"{step_id}.json"
    if path.parent.is_symlink() or path.is_symlink():
        raise IncrementalError("incremental state must not be a symlink")
    return path


def _source_map(root: Path, step_id: str, commands: list[str], acceptance: list[str]) -> dict[str, Any]:
    configured = get(load_manifest(root), "verification.impactMap")
    if configured is None:
        raise IncrementalError("IMPACT_MAP_NOT_CONFIGURED")
    path = resolve_repo_path(root, configured, label="verification.impactMap")
    if path.is_symlink() or not path.is_file():
        raise IncrementalError("IMPACT_MAP_MISSING_OR_SYMLINK")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError) as exc:
        raise IncrementalError("IMPACT_MAP_INVALID_JSON") from exc
    if not isinstance(data, dict) or set(data) != {"schemaVersion", "steps"} or data["schemaVersion"] != POLICY_VERSION:
        raise IncrementalError("IMPACT_MAP_SCHEMA_INVALID")
    steps = data["steps"]
    if not isinstance(steps, dict) or step_id not in steps:
        raise IncrementalError("STEP_MAP_MISSING")
    policy = steps[step_id]
    if not isinstance(policy, dict) or set(policy) != {"checks", "infrastructure"}:
        raise IncrementalError("STEP_MAP_SCHEMA_INVALID")
    raw = policy["checks"]
    if not isinstance(raw, list) or not raw:
        raise IncrementalError("CHECK_MAP_EMPTY")
    if not isinstance(policy["infrastructure"], list):
        raise IncrementalError("INFRASTRUCTURE_INVALID")
    _validate_patterns(policy["infrastructure"])
    ids: set[str] = set()
    seen_commands: set[str] = set()
    obligations: set[str] = set()
    for check in raw:
        if not isinstance(check, dict) or set(check) != {"id", "command", "inputs", "dependsOn", "acceptance", "reusable"}:
            raise IncrementalError("CHECK_SCHEMA_INVALID")
        cid, command = check["id"], check["command"]
        if not isinstance(cid, str) or not _CHECK_ID.fullmatch(cid) or cid in ids:
            raise IncrementalError("CHECK_ID_INVALID_OR_DUPLICATED")
        if not isinstance(command, str) or command not in commands or command in seen_commands:
            raise IncrementalError("COMMAND_COVERAGE_INVALID")
        ids.add(cid)
        seen_commands.add(command)
        if type(check["reusable"]) is not bool:
            raise IncrementalError("REUSABLE_MUST_BE_BOOLEAN")
        _validate_patterns(check["inputs"], nonempty=True)
        depends = check["dependsOn"]
        if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends) or len(set(depends)) != len(depends):
            raise IncrementalError("DEPENDENCY_LIST_INVALID")
        covered = check["acceptance"]
        if not isinstance(covered, list) or not covered or not all(isinstance(c, str) and c in acceptance for c in covered):
            raise IncrementalError("ACCEPTANCE_COVERAGE_INVALID")
        obligations.update(covered)
    if seen_commands != set(commands) or len(commands) != len(seen_commands):
        raise IncrementalError("COMMAND_COVERAGE_INCOMPLETE")
    if obligations != set(acceptance):
        raise IncrementalError("ACCEPTANCE_COVERAGE_INCOMPLETE")
    for check in raw:
        if any(dep not in ids or dep == check["id"] for dep in check["dependsOn"]):
            raise IncrementalError("CHECK_DEPENDENCY_INVALID")
    graph = {c["id"]: c["dependsOn"] for c in raw}
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(cid: str) -> None:
        if cid in visiting:
            raise IncrementalError("CHECK_DEPENDENCY_CYCLE")
        if cid in visited:
            return
        visiting.add(cid)
        for dep in graph[cid]:
            visit(dep)
        visiting.remove(cid)
        visited.add(cid)
    for cid in ids:
        visit(cid)
    return {"checks": raw, "infrastructure": policy["infrastructure"], "hash": _digest(data), "mapPath": path.relative_to(root.resolve()).as_posix()}


def _validate_patterns(patterns: Any, *, nonempty: bool = False) -> None:
    if not isinstance(patterns, list) or (nonempty and not patterns) or not all(isinstance(p, str) for p in patterns) or len(patterns) != len(set(patterns)):
        raise IncrementalError("INPUT_PATTERNS_INVALID")
    for pattern in patterns:
        if (not isinstance(pattern, str) or not pattern or not _GLOB.fullmatch(pattern)
                or pattern.startswith("/") or ".." in pattern.split("/") or "//" in pattern):
            raise IncrementalError("INPUT_PATTERN_UNSAFE")


def _match(path: str, patterns: list[str]) -> bool:
    # В policy ** обозначает все уровни; * внутри сегмента не пересекает /.
    for pattern in patterns:
        escaped = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        if re.fullmatch(escaped, path):
            return True
    return False


def _tree(root: Path) -> str:
    # Тот же точный alternate-index snapshot, который уже использует FIX delta.
    from fix_delta import _snapshot_tree
    return _snapshot_tree(root)


def _tree_entries(root: Path, tree: str) -> list[tuple[str, str, str]]:
    raw = _run(root, "ls-tree", "-r", "-z", tree)
    entries: list[tuple[str, str, str]] = []
    for row in raw.split(b"\0"):
        if not row:
            continue
        meta, delim, name = row.partition(b"\t")
        cols = meta.split()
        if not delim or len(cols) != 3:
            raise IncrementalError("GIT_TREE_ENTRY_INVALID")
        entries.append((name.decode("utf-8", "surrogateescape"), cols[0].decode(), cols[2].decode()))
    return entries


def _inputs_basis(entries: list[tuple[str, str, str]], patterns: list[str]) -> str:
    return _digest([(path, mode, oid) for path, mode, oid in entries if _match(path, patterns)])


def _changed_paths(root: Path, base_tree: str, current_tree: str) -> list[str]:
    raw = _run(root, "diff", "--no-renames", "--name-only", "-z", base_tree, current_tree)
    return [x.decode("utf-8", "surrogateescape") for x in raw.split(b"\0") if x]


def _safe_result(item: dict[str, Any]) -> dict[str, Any]:
    keys = ("kind", "command", "argv", "status", "exitCode", "durationMs",
            "stdoutSha256", "stderrSha256", "stdoutBytes", "stderrBytes")
    return {key: item.get(key) for key in keys}


def _read_checkpoint(root: Path, step_id: str) -> dict[str, Any]:
    path = _state_path(root, step_id)
    if not path.is_file():
        raise IncrementalError("FULL_BASELINE_MISSING")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError) as exc:
        raise IncrementalError("FULL_BASELINE_CORRUPT") from exc
    if not isinstance(value, dict) or value.get("schemaVersion") != STATE_VERSION or value.get("stepId") != step_id:
        raise IncrementalError("FULL_BASELINE_INVALID")
    return value


def prepare(
    root: Path, step_id: str, *, commands: list[str], acceptance: list[str],
    contract_basis: str, context_basis: str, timeout: int,
    subject_hash: str, full: bool = False,
) -> dict[str, Any]:
    """Return accepted cached commands/required executions, never a guessed PASS."""
    def fallback(reason: str) -> dict[str, Any]:
        return {"mode": "full", "reasonCode": reason, "executed": list(commands), "reused": {}, "snapshot": None}
    if full:
        return fallback("FULL_VERIFICATION_REQUESTED")
    try:
        flags = read_task(root, step_id)["frontmatter"].get("risk_flags", [])
        if not isinstance(flags, list) or any(flag in NON_REUSABLE_FLAGS for flag in flags):
            return fallback("RISK_REQUIRES_FULL")
        policy = _source_map(root, step_id, commands, acceptance)
        checkpoint = _read_checkpoint(root, step_id)
        environment = _environment_basis(commands)
        if not environment:
            return fallback("ENVIRONMENT_UNPROVEN")
        if (checkpoint.get("contractBasis") != contract_basis or checkpoint.get("contextBasis") != context_basis
                or checkpoint.get("timeout") != timeout or checkpoint.get("environmentBasis") != environment):
            return fallback("SEMANTIC_OR_ENVIRONMENT_CHANGED")
        if checkpoint.get("policyHash") != policy["hash"]:
            return fallback("IMPACT_MAP_CHANGED")
        base = checkpoint.get("fullBaseline")
        if not isinstance(base, dict) or not re.fullmatch(r"[0-9a-f]{40,64}", str(base.get("tree", ""))):
            return fallback("BASELINE_TREE_INVALID")
        original = checkpoint.get("latestChecks")
        if (not isinstance(original, dict) or set(original) != {c["id"] for c in policy["checks"]}
                or not all(isinstance(item, dict) for item in original.values())):
            return fallback("CHECKPOINT_COVERAGE_INVALID")
        current = _tree(root)
        paths = _changed_paths(root, base["tree"], current)
        task_relative = task_path(root, step_id).relative_to(root).as_posix()
        meaningful = [p for p in paths if p != task_relative]
        if any(_match(p, policy["infrastructure"]) or p == policy["mapPath"] for p in meaningful):
            return fallback("TEST_INFRASTRUCTURE_CHANGED")
        if any(not any(_match(p, c["inputs"]) for c in policy["checks"]) for p in meaningful):
            return fallback("UNMAPPED_CHANGED_PATH")
        entries = _tree_entries(root, current)
        basis = {c["id"]: _inputs_basis(entries, c["inputs"]) for c in policy["checks"]}
        affected = {c["id"] for c in policy["checks"] if not c["reusable"] or
                    original[c["id"]].get("inputBasis") != basis[c["id"]]}
        # Зависимым тестам недостаточно собственного неизменённого glob, если
        # пересмотрена логика, на которую они опираются.
        while True:
            extended = affected | {c["id"] for c in policy["checks"] if set(c["dependsOn"]) & affected}
            if extended == affected:
                break
            affected = extended
        executed: list[str] = []
        reused: dict[str, dict[str, Any]] = {}
        for check in policy["checks"]:
            record = original[check["id"]]
            item = record.get("result")
            if (check["id"] in affected or not isinstance(item, dict) or
                    item.get("status") != "PASS" or item.get("exitCode") != 0 or
                    item.get("command") != check["command"] or not _HASH.fullmatch(str(record.get("inputBasis")))):
                executed.append(check["command"])
            else:
                reused[check["command"]] = {**item, "reusedFrom": record.get("source") or "full-baseline"}
        if not executed and not reused:
            return fallback("EMPTY_INCREMENTAL_SELECTION")
        return {
            "mode": "incremental", "reasonCode": None,
            "executed": executed, "reused": reused, "snapshot": current,
            "policy": policy, "checkpoint": checkpoint, "inputBases": basis,
            "changedPaths": meaningful, "subjectHash": subject_hash,
        }
    except (IncrementalError, OSError, ValueError) as exc:
        # Никогда не превращаем повреждённый state/policy в permission skip.
        return fallback(str(exc)[:180])


def record(
    root: Path, step_id: str, *, result: dict[str, Any], plan: dict[str, Any] | None,
    commands: list[str], acceptance: list[str],
) -> None:
    """Called ONLY by canonical Evidence writer after a producer-bound PASS."""
    if result.get("status") != "PASS":
        return
    try:
        policy = _source_map(root, step_id, commands, acceptance)
        environment = _environment_basis(commands)
        if not environment:
            return
        current = _tree(root)
        entries = _tree_entries(root, current)
        if result.get("verificationMode") == "incremental":
            if plan is None or plan.get("mode") != "incremental" or plan["policy"]["hash"] != policy["hash"]:
                raise IncrementalError("INCREMENTAL_BASELINE_CHANGED")
            if not set(plan["executed"]).issubset(set(result.get("executedChecks", []))):
                raise IncrementalError("INCREMENTAL_SELECTION_CHANGED")
            original = plan["checkpoint"]
            baseline = original["fullBaseline"]
        else:
            baseline = {"tree": current, "subjectHash": result["subjectContentHash"], "runAt": result["runAt"]}
        by_command = {item["command"]: item for item in result["commands"]}
        if set(by_command) != set(commands) or any(item.get("status") != "PASS" or item.get("exitCode") != 0 for item in by_command.values()):
            raise IncrementalError("AGGREGATE_COMMAND_RESULTS_INCOMPLETE")
        latest = {}
        executed = set(result.get("executedChecks", commands))
        for check in policy["checks"]:
            name = check["command"]
            latest[check["id"]] = {
                "inputBasis": _inputs_basis(entries, check["inputs"]),
                "source": "execution" if name in executed else "reused",
                "result": _safe_result(by_command[name]),
            }
        state = {
            "schemaVersion": STATE_VERSION, "stepId": step_id,
            "policyHash": policy["hash"], "contractBasis": result["contractBasis"],
            "contextBasis": result["contextBasis"], "environmentBasis": environment,
            "timeout": result["timeoutSeconds"], "fullBaseline": baseline,
            "latestChecks": latest,
        }
        path = _state_path(root, step_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(state, sort_keys=True, ensure_ascii=False) + "\n")
    except (OSError, ValueError):
        # Cache is optional. Its loss means full-run fallback, not failed PASS.
        return


def _targeted_path(root: Path, step_id: str) -> Path:
    path = _state_path(root, step_id).with_suffix(".targeted.json")
    if path.is_symlink():
        raise IncrementalError("targeted cache path must not be a symlink")
    return path


def remember_targeted(
    root: Path, step_id: str, *, results: list[dict[str, Any]],
    commands: list[str], acceptance: list[str], contract_basis: str,
    context_basis: str, timeout: int, subject_hash: str,
) -> None:
    """Save trusted selected command results, not a completion proof."""
    try:
        policy = _source_map(root, step_id, commands, acceptance)
        _read_checkpoint(root, step_id)  # targeted without full baseline is only feedback
        environment = _environment_basis(commands)
        selected = {item.get("command"): item for item in results if isinstance(item, dict)}
        if (not environment or len(selected) != len(results) or not selected
                or not set(selected).issubset(set(commands))
                or any(item.get("status") != "PASS" or item.get("exitCode") != 0 for item in selected.values())):
            return
        payload = {
            "schemaVersion": STATE_VERSION, "producer": "targeted-verification",
            "stepId": step_id, "policyHash": policy["hash"],
            "contractBasis": contract_basis, "contextBasis": context_basis,
            "timeout": timeout, "environmentBasis": environment,
            "subjectHash": subject_hash,
            "commands": {name: _safe_result(item) for name, item in selected.items()},
        }
        path = _targeted_path(root, step_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
    except (OSError, ValueError):
        return


def reuse_targeted(
    root: Path, step_id: str, *, selection: dict[str, Any],
    commands: list[str], contract_basis: str, context_basis: str,
    timeout: int, subject_hash: str,
) -> dict[str, dict[str, Any]]:
    """Consume selected feedback only for checks Core already selected to execute."""
    if selection.get("mode") != "incremental":
        return {}
    try:
        path = _targeted_path(root, step_id)
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or any((
            data.get("schemaVersion") != STATE_VERSION,
            data.get("producer") != "targeted-verification",
            data.get("stepId") != step_id,
            data.get("policyHash") != selection["policy"]["hash"],
            data.get("contractBasis") != contract_basis,
            data.get("contextBasis") != context_basis,
            data.get("timeout") != timeout,
            data.get("environmentBasis") != _environment_basis(commands),
            data.get("subjectHash") != subject_hash,
        )):
            return {}
        stored = data.get("commands")
        if not isinstance(stored, dict):
            return {}
        return {
            name: {**item, "reusedFrom": "targeted-feedback"}
            for name, item in stored.items()
            if (name in selection["executed"] and isinstance(item, dict)
                and item.get("command") == name and item.get("status") == "PASS"
                and item.get("exitCode") == 0)
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {}
