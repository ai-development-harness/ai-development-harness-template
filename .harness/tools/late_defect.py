#!/usr/bin/env python3
"""Immutable observation for a confirmed defect discovered after REVIEW PASS.

An observation is a new artifact. It never changes completed STEP, Evidence,
or an immutable REVIEW, and it never manufactures a synthetic FAIL review.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any

from completion_gate import acceptance_criteria
from harness_config import review_directory
from planning_contract import read_task, step_completion_proof
from review_contract import latest_trusted_review

STEP_ID = re.compile(r"STEP-\d{3,}\Z")
NAME = re.compile(r"OBSERVATION-(\d{8}T\d{6}Z)-([0-9a-f]{12})\.json\Z")
SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")


class ObservationError(ValueError):
    """Unverifiable origin or malformed immutable observation."""


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _origin(root: Path, step_id: str) -> dict[str, Any]:
    if not STEP_ID.fullmatch(step_id):
        raise ObservationError("invalid source STEP id")
    task = read_task(root, step_id)
    if task["frontmatter"].get("status") != "completed":
        raise ObservationError("observation requires a completed source STEP")
    proof = step_completion_proof(root, step_id, _historical=True)
    if not proof.get("complete"):
        raise ObservationError("source completion proof unavailable: " +
                               "; ".join(proof.get("reasons", [])))
    trusted = latest_trusted_review(root, step_id)
    if trusted is None or trusted.get("verdict") != "PASS":
        raise ObservationError("source requires an independent trusted PASS REVIEW")
    report = trusted["path"]
    if report.is_symlink() or not report.is_file():
        raise ObservationError("source REVIEW is invalid")
    try:
        rel = report.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ObservationError("source REVIEW escapes repository") from exc
    if not rel.startswith((review_directory(root) / step_id).relative_to(root).as_posix() + "/"):
        raise ObservationError("source REVIEW is outside configured review directory")
    return {
        "review": rel,
        "reviewSha256": _digest(report.read_bytes()),
        "evidenceSha256": _digest(
            task["sections"].get("Evidence", "").encode("utf-8")),
    }


def _reuse_origin(root: Path, step_id: str) -> dict[str, Any] | None:
    """Pin the exact full Verification baseline if local producer proof exists."""
    from verification import (
        parse_verification, EVIDENCE_START, EVIDENCE_END,
    )
    from verification_incremental import _source_map, _state_path
    from verification_proof import verification_proof_error
    section = read_task(root, step_id)["sections"].get("Evidence", "")
    match = re.search(
        re.escape(EVIDENCE_START) + r"(.*?)" + re.escape(EVIDENCE_END),
        section, re.S,
    )
    if match is None or verification_proof_error(
        root, step_id, block=match.group(1), status="PASS",
    ) is not None:
        return None
    names = [
        value["value"] for value in parse_verification(root, step_id)
        if value["kind"] == "command"
    ]
    try:
        policy = _source_map(root, step_id, names, acceptance_criteria(root, step_id))
        checkpoint_path = _state_path(root, step_id)
        proof_path = root / ".harness/local/verification-proofs" / (step_id + ".json")
        if (not checkpoint_path.is_file() or checkpoint_path.is_symlink()
                or not proof_path.is_file() or proof_path.is_symlink()):
            return None
        raw = checkpoint_path.read_bytes()
        check = json.loads(raw)
        if (not isinstance(check, dict) or check.get("stepId") != step_id
                or check.get("policyHash") != policy["hash"]):
            return None
        return {
            "checkpointSha256": _digest(raw),
            "proofSha256": _digest(proof_path.read_bytes()),
            "checks": policy["checks"],
        }
    except (OSError, ValueError, UnicodeError):
        return None


def _directory(root: Path, step_id: str) -> Path:
    directory = review_directory(root) / step_id
    try:
        rel = directory.relative_to(root.resolve())
    except ValueError as exc:
        raise ObservationError("observation directory escapes repository") from exc
    cursor = root.resolve()
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ObservationError("observation directory contains symlink")
    return directory


def record(
    root: Path, step_id: str, *,
    criterion: str, given: str, when: str, expected: str, observed: str,
    evidence_path: str, invalidated_checks: list[str],
) -> dict[str, Any]:
    """Reserve an immutable file only after source and evidence are verified."""
    root = root.resolve()
    source = _origin(root, step_id)
    if criterion not in acceptance_criteria(root, step_id):
        raise ObservationError("criterion must exactly match source Acceptance")
    for label, value in (
        ("given", given), ("when", when), ("expected", expected),
        ("observed", observed),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ObservationError(label + " must be non-empty")
    if (not isinstance(invalidated_checks, list) or not invalidated_checks
            or any(not isinstance(x, str) or not x.strip() for x in invalidated_checks)
            or len(invalidated_checks) != len(set(invalidated_checks))):
        raise ObservationError("invalidatedChecks must be a nonempty unique list")
    from harness_config import resolve_repo_path
    evidence = resolve_repo_path(root, evidence_path, label="late defect evidence")
    if not evidence.is_file() or evidence.is_symlink():
        raise ObservationError("reproducer evidence file must exist and not be a symlink")
    evidence_rel = evidence.relative_to(root).as_posix()
    proof = {"path": evidence_rel, "sha256": _digest(evidence.read_bytes())}
    directory = _directory(root, step_id)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"OBSERVATION-{stamp}-{secrets.token_hex(6)}.json"
    path = directory / name
    value = {
        "schemaVersion": 1, "kind": "late-defect",
        "sourceStep": step_id, "observedAt": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "reuse": _reuse_origin(root, step_id),
        "finding": {
            "criterion": criterion,
            "given": given.strip(), "when": when.strip(),
            "expected": expected.strip(), "observed": observed.strip(),
            "reproducerEvidence": proof,
            "invalidatedChecks": invalidated_checks,
        },
    }
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    # O_EXCL prevents overwrite or following a symlink on concurrent writers.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"path": path.relative_to(root).as_posix(), "observation": value}


def read(root: Path, source_id: str, relative: str) -> dict[str, Any]:
    """Fail closed if origin REVIEW, evidence or the observation was altered."""
    root = root.resolve()
    if not STEP_ID.fullmatch(source_id):
        raise ObservationError("invalid source STEP id")
    if not isinstance(relative, str):
        raise ObservationError("observation path must be a string")
    rel = Path(relative)
    if rel.is_absolute() or "." in rel.parts or ".." in rel.parts:
        raise ObservationError("observation path must be canonical")
    directory = _directory(root, source_id)
    path = root / rel
    if path.parent != directory or not NAME.fullmatch(path.name) or path.is_symlink():
        raise ObservationError("observation path is not canonical")
    if not path.is_file():
        raise ObservationError("observation is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ObservationError("observation is unreadable") from exc
    if (not isinstance(value, dict) or set(value) != {
        "schemaVersion", "kind", "sourceStep", "observedAt", "source", "reuse", "finding"}
            or value["schemaVersion"] != 1 or value["kind"] != "late-defect"
            or value["sourceStep"] != source_id):
        raise ObservationError("observation schema invalid")
    if value["source"] != _origin(root, source_id):
        raise ObservationError("source REVIEW/Evidence changed since observation")
    finding = value["finding"]
    if not isinstance(finding, dict) or set(finding) != {
        "criterion", "given", "when", "expected", "observed",
        "reproducerEvidence", "invalidatedChecks"
    }:
        raise ObservationError("finding schema invalid")
    if finding["criterion"] not in acceptance_criteria(root, source_id):
        raise ObservationError("observation criterion is no longer canonical")
    if not all(isinstance(finding.get(key), str) and finding[key].strip()
               for key in ("given", "when", "expected", "observed")):
        raise ObservationError("observation must describe a reproducible defect")
    invalidated = finding["invalidatedChecks"]
    if (not isinstance(invalidated, list) or not invalidated or
            not all(isinstance(x, str) and x for x in invalidated)
            or len(invalidated) != len(set(invalidated))):
        raise ObservationError("invalidated checks invalid")
    origin_evidence = finding["reproducerEvidence"]
    if (not isinstance(origin_evidence, dict) or
            set(origin_evidence) != {"path", "sha256"}):
        raise ObservationError("reproducer evidence schema invalid")
    from harness_config import resolve_repo_path
    proof_path = resolve_repo_path(
        root, origin_evidence["path"], label="late defect repro"
    )
    if (not proof_path.is_file() or proof_path.is_symlink()
            or _digest(proof_path.read_bytes()) != origin_evidence["sha256"]):
        raise ObservationError("reproducer evidence is stale")
    return value
