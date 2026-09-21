#!/usr/bin/env python3
"""Детерминированный contract immutable STEP review reports.

Review recovery имеет право доверять только report, который прошёл schema
validation и относится к точной текущей repository revision.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from typing import Any

from document_contract import (
    DocumentError,
    REVIEW_VERDICTS,
    STEP_ID_RE,
    parse_document,
    require_schema,
)
from harness_config import review_directory
from planning_contract import read_task
from review_gates import required_reviewers


SEVERITIES = {"critical", "high", "medium", "low"}
CATEGORIES = {"implementation", "evidence", "contract"}
SPECIALIZED_STATUSES = {"pass", "fail", "blocked", "not_required"}


def _git(root: Path, *args: str) -> tuple[int, bytes]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return 127, b""
    return proc.returncode, proc.stdout


def repository_revision(root: Path) -> dict[str, str | None]:
    code, head = _git(root, "rev-parse", "HEAD")
    git_head = head.decode("utf-8", errors="replace").strip() if code == 0 else None

    code, status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if code != 0:
        raise ValueError("cannot read git worktree state")
    if not status:
        return {"git_head": git_head, "worktree_hash": None}

    digest = hashlib.sha256()
    digest.update(status)
    code, diff = _git(root, "diff", "--binary", "HEAD")
    if code != 0:
        raise ValueError("cannot hash git worktree diff")
    digest.update(diff)

    # Git diff не включает untracked content. Добавляем path+bytes, чтобы PASS
    # нельзя было применить к изменившемуся незакоммиченному файлу.
    entries = [entry for entry in status.split(b"\0") if entry]
    for entry in entries:
        decoded = entry.decode("utf-8", errors="surrogateescape")
        if not decoded.startswith("?? "):
            continue
        rel = decoded[3:]
        path = root / rel
        digest.update(rel.encode("utf-8", errors="surrogateescape"))
        if path.is_file():
            digest.update(path.read_bytes())
    return {"git_head": git_head, "worktree_hash": "sha256:" + digest.hexdigest()}


def _parse_findings(document: dict[str, Any]) -> list[dict[str, str]]:
    section = document["sections"].get("Findings", "")
    findings: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in section.splitlines():
        if line.startswith("### F-"):
            if current is not None:
                findings.append(current)
            current = {"heading": line[4:].strip()}
            continue
        if current is None:
            continue
        for field in ("Severity", "Category", "Location", "Scenario", "Impact", "Fix direction"):
            prefix = f"**{field}:**"
            if line.startswith(prefix):
                current[field] = line[len(prefix):].strip()
                break
    if current is not None:
        findings.append(current)
    return findings


def validate_review_report(root: Path, path: Path, *, require_current_revision: bool = False) -> list[str]:
    errors: list[str] = []
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]
    meta = document["frontmatter"]
    errors.extend(require_schema(document, kind="step_review"))

    step_id = meta.get("step_id")
    if not isinstance(step_id, str) or STEP_ID_RE.fullmatch(step_id) is None:
        errors.append("step_id must be STEP-NNN")
        return errors
    try:
        task = read_task(root, step_id)
    except Exception as exc:
        errors.append(f"cannot read referenced STEP: {exc}")
        return errors

    verdict = meta.get("verdict")
    if verdict not in REVIEW_VERDICTS:
        errors.append("verdict must be pass|fail|blocked")

    revision = meta.get("reviewed_revision")
    if not isinstance(revision, dict):
        errors.append("reviewed_revision must be a mapping")
    else:
        git_head = revision.get("git_head")
        worktree_hash = revision.get("worktree_hash")
        if git_head is not None and (not isinstance(git_head, str) or not git_head.strip()):
            errors.append("reviewed_revision.git_head must be null or non-empty string")
        if worktree_hash is not None and (
            not isinstance(worktree_hash, str)
            or not worktree_hash.startswith("sha256:")
            or len(worktree_hash) != 71
        ):
            errors.append("reviewed_revision.worktree_hash must be null or sha256")
        if require_current_revision:
            try:
                current = repository_revision(root)
            except ValueError as exc:
                errors.append(str(exc))
            else:
                if revision != current:
                    errors.append("reviewed_revision does not match current repository state")

    findings = _parse_findings(document)
    for index, finding in enumerate(findings, 1):
        prefix = f"finding F-{index:03d}"
        if finding.get("Severity") not in SEVERITIES:
            errors.append(f"{prefix}: invalid or missing Severity")
        if finding.get("Category") not in CATEGORIES:
            errors.append(f"{prefix}: invalid or missing Category")
        for field in ("Location", "Scenario", "Impact", "Fix direction"):
            if not finding.get(field):
                errors.append(f"{prefix}: missing {field}")

    if verdict == "pass" and findings:
        errors.append("PASS review must not contain material findings")
    if verdict == "fail":
        if not findings:
            errors.append("FAIL review requires at least one finding")
        if any(item.get("Category") == "contract" for item in findings):
            errors.append("FAIL cannot contain contract findings; contract defect must be BLOCKED")
        if not any(item.get("Category") in {"implementation", "evidence"} for item in findings):
            errors.append("FAIL requires implementation/evidence finding")
    if verdict == "blocked":
        if not findings:
            errors.append("BLOCKED review requires at least one finding")
        if not any(item.get("Category") == "contract" for item in findings):
            errors.append("BLOCKED review requires a contract finding")

    specialized = meta.get("specialized_reviews")
    if not isinstance(specialized, dict):
        errors.append("specialized_reviews must be a mapping")
    else:
        required = set(required_reviewers(root, step_id)["required"])
        for kind in ("security", "tests"):
            status = specialized.get(kind)
            if status not in SPECIALIZED_STATUSES:
                errors.append(f"specialized_reviews.{kind} has invalid status")
                continue
            report = specialized.get(f"{kind}_report")
            reason = specialized.get(f"{kind}_reason")
            if kind in required and status == "not_required":
                errors.append(f"{kind} reviewer is deterministically required")
            if status == "not_required" and (not isinstance(reason, str) or not reason.strip()):
                errors.append(f"{kind} not_required requires reason")
            if status != "not_required" and (not isinstance(report, str) or not report.strip()):
                errors.append(f"{kind} review status {status} requires report reference")

    for required_section in ("Scope checked", "Findings", "Verification observations", "Verdict rationale"):
        if required_section not in document["sections"]:
            errors.append(f"missing section '## {required_section}'")
        elif required_section != "Findings" and not document["sections"][required_section].strip():
            errors.append(f"empty section '## {required_section}'")
    return errors


def review_reports(root: Path, step_id: str) -> list[dict[str, Any]]:
    directory = review_directory(root) / step_id
    if not directory.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("REVIEW-*.md")):
        errors = validate_review_report(root, path)
        if errors:
            continue
        doc = parse_document(path)
        result.append({
            "path": path,
            "verdict": str(doc["frontmatter"]["verdict"]).upper(),
            "document": doc,
        })
    return result


def latest_review(root: Path, step_id: str, *, require_current_revision: bool = False) -> dict[str, Any] | None:
    reports = review_reports(root, step_id)
    if not reports:
        return None
    report = reports[-1]
    if require_current_revision:
        if validate_review_report(root, report["path"], require_current_revision=True):
            return None
    return report


def validate_all_review_reports(root: Path) -> list[str]:
    errors: list[str] = []
    directory = review_directory(root)
    if not directory.is_dir():
        return errors
    for path in sorted(directory.glob("STEP-*/REVIEW-*.md")):
        for issue in validate_review_report(root, path):
            errors.append(f"review: {path.relative_to(root)}: {issue}")
    return errors


def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--file")
    parser.add_argument("--step")
    parser.add_argument("--current-revision", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    if args.file:
        path = (root / args.file).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            errors = ["review path escapes repository"]
        else:
            errors = validate_review_report(
                root,
                path,
                require_current_revision=args.current_revision,
            )
    elif args.step:
        errors = []
        directory = review_directory(root) / args.step
        for path in sorted(directory.glob("REVIEW-*.md")) if directory.is_dir() else []:
            errors.extend(
                f"{path.relative_to(root)}: {item}"
                for item in validate_review_report(root, path)
            )
    else:
        errors = validate_all_review_reports(root)

    result = {"status": "PASS" if not errors else "FAIL", "errors": errors}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["status"])
        for item in errors:
            print(f"- {item}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
