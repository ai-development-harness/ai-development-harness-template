#!/usr/bin/env python3
"""Dispatcher-aware incremental Verification from a canonical full baseline.

Project configuration is opt-in. Missing/invalid provenance degrades to a
*full execution*, never to a prior unverified PASS.
"""
from __future__ import annotations

from pathlib import Path
import json
import re
import time
from typing import Any

from document_contract import atomic_write_text
from harness_config import (get, load_manifest, resolve_repo_path,
                            requirements_directory, roadmap_path, status_path,
                            open_questions_index_path, review_directory,
                            planning_review_directory, init_review_directory)
from planning_contract import read_task, task_path
from verification_impact import (ImpactError, FULL_ONLY_FLAGS, digest,
                                 full_baseline, read_map, select)


MAX_BYTES = 3_000_000


def _path(root: Path, step_id: str) -> Path:
    if re.fullmatch(r"STEP-\d{3,}", step_id) is None:
        raise ImpactError("invalid incremental STEP ID")
    return root / ".harness/local/verification-incremental" / (step_id + ".json")


def _excluded(root: Path, step_id: str) -> set[str]:
    """Ignore generated changes that also do not alter product content identity."""
    root = root.resolve()
    excluded = {task_path(root, step_id).resolve().relative_to(root).as_posix()}
    for source in (roadmap_path, status_path, open_questions_index_path):
        try:
            excluded.add(source(root).relative_to(root).as_posix())
        except (OSError, ValueError):
            pass
    try:
        req = requirements_directory(root)
        for name in ("SPEC.md", "STATUS.md"):
            excluded.add((req / name).relative_to(root).as_posix())
    except (OSError, ValueError):
        pass
    # Only immutable report-shaped files, not an entire directory.
    for resolve, pattern in (
        (review_directory, "STEP-*/REVIEW-*.md"),
        (planning_review_directory, "STEP-*/PLAN-REVIEW-*.md"),
        (init_review_directory, "INIT-REVIEW-*.md"),
    ):
        try:
            directory = resolve(root)
        except (OSError, ValueError):
            continue
        if directory.is_dir():
            excluded.update(p.relative_to(root).as_posix() for p in directory.glob(pattern)
                            if p.is_file() and not p.is_symlink())
    return excluded


def _configuration(root: Path, step_id: str, commands: list[str]) -> dict[str, Any] | None:
    manifest = load_manifest(root)
    directory = get(manifest, "sources.verificationImpactDirectory")
    if directory is None:
        return None
    location = resolve_repo_path(root, directory, label="sources.verificationImpactDirectory")
    if not location.is_dir() or location.is_symlink():
        raise ImpactError("verification impact directory unavailable")
    task = read_task(root, step_id)
    flags = task["frontmatter"].get("risk_flags", [])
    if not isinstance(flags, list) or FULL_ONLY_FLAGS.intersection(flags):
        raise ImpactError("risk flags require full Verification")
    # Avoid circular imports: completion_gate imports verification. The exact
    # same Acceptance bullet parsing is kept as a small local read-only helper.
    import re as _re
    acceptance = [match.group(1).strip()
                  for line in task["sections"].get("Acceptance criteria", "").splitlines()
                  if (match := _re.match(r"^\s*[-*]\s+(.+?)\s*$", line))]
    mapping = read_map(location / (step_id + ".json"),
                       commands=commands, acceptance=acceptance)
    from verification import _argv
    for group in mapping["checks"]:
        _argv(group["command"])  # no shell, same parser as canonical full Verification
    return mapping


def _load(root: Path, step_id: str) -> dict[str, Any]:
    path = _path(root, step_id)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ImpactError("full Verification baseline not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, UnicodeError) as exc:
        raise ImpactError("invalid full baseline") from exc
    if not isinstance(data, dict) or data.get("stepId") != step_id:
        raise ImpactError("invalid full baseline identity")
    if (data.get("status") != "PASS" or not isinstance(data.get("originCommands"), list)
            or data.get("producer") != "deterministic-full-verification"):
        raise ImpactError("full baseline has no PASS provenance")
    return data


def remember_full(root: Path, step_id: str, result: dict[str, Any]) -> None:
    """Run only *after* canonical full PASS and Evidence proof publication.

    Cache write failure is not a Verification failure: the next run simply
    executes the complete contract again.
    """
    if result.get("status") != "PASS" or result.get("incremental") is not None:
        return
    commands = [item["command"] for item in result.get("commands", [])]
    try:
        mapping = _configuration(root, step_id, commands)
        if mapping is None:
            return
        baseline = full_baseline(root, mapping=mapping,
                                 contract=result["contractBasis"],
                                 context=result["contextBasis"],
                                 subject=result["subjectContentHash"],
                                 exclude=_excluded(root, step_id))
        baseline.update(stepId=step_id, status="PASS", originCommands=result["commands"],
                        originRunAt=result["runAt"])
        text = json.dumps(baseline, ensure_ascii=False, sort_keys=True) + "\n"
        if len(text.encode("utf-8")) > MAX_BYTES:
            return
        path = _path(root, step_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_symlink():
            atomic_write_text(path, text)
    except (OSError, ValueError, KeyError):
        return  # Fallback on next run, never fabricate partial provenance.


def _aggregate(parent: str, groups: list[dict[str, Any]],
               originals: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe composed results without pretending the parent was rerun."""
    origin = next((item for item in originals if item.get("command") == parent), None)
    if not isinstance(origin, dict) or origin.get("status") != "PASS" or origin.get("exitCode") != 0:
        raise ImpactError("original command was not PASS")
    if all(item["reused"] for item in groups):
        return {**origin, "verificationMode": "reused-full-baseline"}
    blocked = next((item for item in groups if item["status"] == "BLOCKED"), None)
    failed = next((item for item in groups if item["status"] == "FAIL"), None)
    status = "BLOCKED" if blocked else "FAIL" if failed else "PASS"
    recorded = [item["result"] for item in groups if not item["reused"]]
    composed = {
        "kind": "command", "command": parent, "argv": origin.get("argv", []),
        "status": status, "exitCode": None if blocked else (1 if failed else 0),
        "durationMs": sum(item.get("durationMs", 0) for item in groups),
        "stdoutSha256": digest([item.get("stdoutSha256") for item in recorded]),
        "stderrSha256": digest([item.get("stderrSha256") for item in recorded]),
        "stdoutBytes": sum(item.get("stdoutBytes", 0) for item in recorded),
        "stderrBytes": sum(item.get("stderrBytes", 0) for item in recorded),
        "verificationMode": "composed-groups",
    }
    if blocked or failed:
        composed["reasonCode"] = (blocked or failed).get("reasonCode", "INCREMENTAL_CHECK_FAILED")
    return composed


def try_incremental(
    root: Path, step_id: str, *, commands: list[str], contract: str,
    context: str, revision: dict[str, Any], timeout: int,
    force_full: bool = False,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None, str | None]:
    """Returns (aggregate canonical commands, selection detail, fallback reason).

    An unknown mapping does not mutate anything. A concurrent worktree/ref
    mutation is a BLOCKED verification result, not reusable evidence.
    """
    if force_full:
        return None, None, "FULL_EXPLICIT"
    try:
        mapping = _configuration(root, step_id, commands)
        if mapping is None:
            return None, None, None
        baseline = _load(root, step_id)
        choice = select(root, mapping=mapping, baseline=baseline, contract=contract,
                        context=context, exclude=_excluded(root, step_id))
    except (OSError, ValueError) as exc:
        return None, None, "INCREMENTAL_FALLBACK: " + str(exc)

    from verification import _run_command, _refs_snapshot, _revision_equal
    from review_contract import repository_revision
    start_refs = _refs_snapshot(root)
    selected = set(choice["executed"])
    results: list[dict[str, Any]] = []
    for group in mapping["checks"]:
        if group["id"] not in selected:
            results.append({"id": group["id"], "parent": group["parent"],
                            "command": group["command"], "reused": True,
                            "status": "PASS", "durationMs": 0})
            continue
        if not _revision_equal(repository_revision(root), revision) or _refs_snapshot(root) != start_refs:
            return [{"kind": "command", "command": group["parent"], "status": "BLOCKED",
                     "reasonCode": "VERIFICATION_INPUTS_STALE"}], {"blocked": True}, None
        started = time.monotonic()
        item = _run_command(root, group["command"], timeout_seconds=timeout)
        results.append({"id": group["id"], "parent": group["parent"],
                        "command": group["command"], "reused": False,
                        "status": item["status"], "durationMs": int((time.monotonic()-started)*1000),
                        "result": item})
        if not _revision_equal(repository_revision(root), revision) or _refs_snapshot(root) != start_refs:
            return [{"kind": "command", "command": group["parent"], "status": "BLOCKED",
                     "reasonCode": "VERIFICATION_MUTATED_REPOSITORY"}], {"blocked": True}, None
        if item["status"] in {"BLOCKED", "FAIL"}:
            # A pending/FAIL group never becomes reused PASS in this result.
            # The next attempt recomputes all affected groups against the full baseline.
            break

    # Incomplete selection must not be presented as a PASS aggregate.
    done = {item["id"] for item in results}
    if len(done) != len(mapping["checks"]):
        failed = next(item for item in results if item["status"] != "PASS")
        return [{"kind": "command", "command": failed["parent"], "status": failed["status"],
                 "exitCode": failed.get("result", {}).get("exitCode"),
                 "reasonCode": "INCREMENTAL_GROUP_FAILED"}], {
                     "blocked": failed["status"] == "BLOCKED", "groups": results,
                 }, None

    aggregates = [
        _aggregate(parent, [item for item in results if item["parent"] == parent],
                   baseline["originCommands"]) for parent in commands
    ]
    return aggregates, {
        "mode": "incremental", "baseline": choice["baseline"],
        "baselineDigest": digest(baseline),
        "changedPaths": choice["changedPaths"],
        "executed": choice["executed"], "reused": choice["reused"],
        "executedCount": len(choice["executed"]),
        "reusedCount": len(choice["reused"]),
        "groups": [{k: v for k, v in item.items() if k != "result"} for item in results],
    }, None


__all__ = ["try_incremental", "remember_full"]
