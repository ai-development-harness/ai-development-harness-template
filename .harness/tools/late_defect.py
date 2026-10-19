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
    status = task["frontmatter"].get("status")
    if status == "completed":
        proof = step_completion_proof(root, step_id, _historical=True)
        if not proof.get("complete"):
            raise ObservationError("source completion proof unavailable: " +
                                   "; ".join(proof.get("reasons", [])))
    elif status == "in_progress":
        # A reviewed-but-not-finalized STEP may receive a user observation.
        # Its *current* producer-bound PASS must exist before the FIX starts.
        from verification import verification_freshness
        fresh = verification_freshness(root, step_id)
        if fresh.get("status") != "PASS" or fresh.get("fresh") is not True:
            raise ObservationError("active source requires fresh Verification PASS")
    else:
        raise ObservationError("observation requires completed or reviewed active STEP")
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
        "statusAtObservation": status,
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
    # A reproducer kept only in gitignored/local state disappears on checkout.
    # Such a path cannot be a durable source of correction evidence.
    import subprocess
    ignored = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", "--", evidence_rel],
        cwd=root, capture_output=True, check=False,
    )
    if ignored.returncode != 1:
        raise ObservationError("reproducer must be a non-ignored repository file")
    proof = {"path": evidence_rel, "sha256": _digest(evidence.read_bytes())}
    reuse = _reuse_origin(root, step_id)
    if reuse is not None:
        available = {item["id"] for item in reuse["checks"]}
        for item in reuse["checks"]:
            available.update(child["id"] for child in item.get("groups", []))
        if any(value not in available for value in invalidated_checks):
            raise ObservationError("invalidatedChecks contains unknown check IDs")
    directory = _directory(root, step_id)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    value = {
        "schemaVersion": 1, "kind": "late-defect",
        "sourceStep": step_id, "observedAt": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "reuse": reuse,
        "finding": {
            "criterion": criterion,
            "given": given.strip(), "when": when.strip(),
            "expected": expected.strip(), "observed": observed.strip(),
            "reproducerEvidence": proof,
            "invalidatedChecks": invalidated_checks,
        },
    }
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    # Content-derived suffix prevents undetected edits to the observation.
    name = f"OBSERVATION-{stamp}-{hashlib.sha256(payload).hexdigest()[:12]}.json"
    path = directory / name
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
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest()[:12] != NAME.fullmatch(path.name).group(2):
            raise ObservationError("immutable observation content was changed")
        value = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ObservationError("observation is unreadable") from exc
    if (not isinstance(value, dict) or set(value) != {
        "schemaVersion", "kind", "sourceStep", "observedAt", "source", "reuse", "finding"}
            or value["schemaVersion"] != 1 or value["kind"] != "late-defect"
            or value["sourceStep"] != source_id):
        raise ObservationError("observation schema invalid")
    saved_source = value["source"]
    if not isinstance(saved_source, dict):
        raise ObservationError("source provenance invalid")
    if saved_source.get("statusAtObservation") == "in_progress":
        # FIX updates the active STEP's generated Evidence. The original
        # producer-bound PASS is now pinned by immutable observation + original
        # REVIEW bytes; do not demand current Evidence equal its old contents.
        source_report = saved_source.get("review")
        if not isinstance(source_report, str):
            raise ObservationError("observation source REVIEW path invalid")
        original = root / source_report
        from review_contract import validate_review_report
        if (original.parent != _directory(root, source_id) or
                not original.is_file() or original.is_symlink() or
                _digest(original.read_bytes()) != saved_source.get("reviewSha256")
                or validate_review_report(root, original, expected_step_id=source_id)):
            raise ObservationError("original reviewed PASS source is no longer trusted")
        if read_task(root, source_id)["frontmatter"].get("status") not in {
            "in_progress", "completed",
        }:
            raise ObservationError("active source changed lifecycle incompatibly")
    elif saved_source != _origin(root, source_id):
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
