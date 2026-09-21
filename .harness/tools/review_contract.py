#!/usr/bin/env python3
"""Детерминированный contract immutable STEP review reports.

Review recovery имеет право доверять только report, который прошёл schema
validation и относится к точной текущей repository revision.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess
from typing import Any

from document_contract import (
    DocumentError,
    REVIEW_VERDICTS,
    STEP_ID_RE,
    content_hash,
    parse_document,
    require_schema,
    split_frontmatter,
    string_list,
)
from harness_config import (
    audit_directory,
    init_review_directory,
    planning_review_directory,
    review_directory,
)
from planning_contract import read_task
from review_gates import required_reviewers


SEVERITIES = {"critical", "high", "medium", "low"}
CATEGORIES = {"implementation", "evidence", "contract"}
SPECIALIZED_STATUSES = {"pass", "fail", "blocked", "not_required"}


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(char in "0123456789abcdef" for char in value[7:].lower())
    )


def legacy_review_pins(root: Path) -> dict[str, str]:
    """Прочитать hash-pinned legacy review allowlist из migration reports."""
    pins: dict[str, str] = {}
    directory = audit_directory(root)
    if not directory.is_dir():
        return pins
    for report in sorted(directory.glob("MIGRATION-*.md")):
        try:
            document = parse_document(report)
        except DocumentError:
            continue
        meta = document["frontmatter"]
        if meta.get("schema") != 1 or meta.get("kind") != "migration":
            continue
        values = meta.get("legacy_review_reports", [])
        if values is None:
            continue
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise ValueError(f"{report.relative_to(root)}: legacy_review_reports must be a string list")
        for token in values:
            digest, sep, rel = token.partition(" ")
            if not sep or not _valid_sha256(digest) or not rel:
                raise ValueError(f"{report.relative_to(root)}: invalid legacy review pin {token!r}")
            candidate = (root / rel).resolve()
            try:
                candidate.relative_to(review_directory(root).resolve())
            except ValueError as exc:
                raise ValueError(
                    f"{report.relative_to(root)}: legacy review pin escapes configured review directory: {rel}"
                ) from exc
            previous = pins.get(rel)
            if previous is not None and previous != digest:
                raise ValueError(f"conflicting legacy review pins for {rel}")
            pins[rel] = digest
    return pins


def current_legacy_review_snapshots(root: Path) -> dict[str, str]:
    """Вернуть no-frontmatter legacy reports с content hashes."""
    snapshots: dict[str, str] = {}
    directory = review_directory(root)
    if not directory.is_dir():
        return snapshots
    for path in sorted(directory.glob("STEP-*/REVIEW-*.md")):
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, _ = split_frontmatter(text)
        except (OSError, UnicodeDecodeError, DocumentError):
            continue
        if frontmatter is None:
            snapshots[path.relative_to(root).as_posix()] = content_hash(text)
    return snapshots


def _legacy_review_verdict(path: Path, step_id: str) -> str | None:
    """Минимально прочитать verdict старого immutable report без его переписывания."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    identity = re.search(r"\b(STEP-\d{3,})\b", first)
    if identity is None or identity.group(1) != step_id:
        return None
    match = re.search(r"(?mi)^\*\*Verdict:\*\*\s*(PASS|FAIL|BLOCKED)\s*$", text)
    return match.group(1).upper() if match else None


def trusted_review_reports(
    root: Path,
    step_id: str,
    *,
    extra_legacy_pins: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Schema-v1 reports + exact hash-pinned legacy history для completion proof.

    extra_legacy_pins используется только внутри одной schema-migration
    транзакции: projections могут вычислить final state до публикации migration
    report, который затем делает те же pins durable.
    """
    result = review_reports(root, step_id)
    try:
        pins = legacy_review_pins(root)
    except ValueError:
        pins = {}
    if extra_legacy_pins:
        for rel, digest in extra_legacy_pins.items():
            previous = pins.get(rel)
            if previous is not None and previous != digest:
                raise ValueError(f"conflicting legacy review pin for {rel}")
            pins[rel] = digest
    directory = review_directory(root) / step_id
    if directory.is_dir():
        for path in sorted(directory.glob("REVIEW-*.md")):
            rel = path.relative_to(root).as_posix()
            expected = pins.get(rel)
            if expected is None:
                continue
            try:
                actual = content_hash(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if actual != expected:
                continue
            verdict = _legacy_review_verdict(path, step_id)
            if verdict is None:
                continue
            result.append({
                "path": path,
                "verdict": verdict,
                "document": None,
                "legacy": True,
                "content_hash": actual,
            })
    result.sort(key=lambda item: item["path"].name)
    return result


def latest_trusted_review(
    root: Path,
    step_id: str,
    *,
    extra_legacy_pins: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    reports = trusted_review_reports(
        root,
        step_id,
        extra_legacy_pins=extra_legacy_pins,
    )
    return reports[-1] if reports else None


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


def _is_step_review_report_path(root: Path, path: Path) -> bool:
    """Проверить, является ли path именно implementation review report."""
    try:
        suffix = path.resolve().relative_to(review_directory(root).resolve()).as_posix()
    except ValueError:
        return False
    return re.fullmatch(r"STEP-\\d{3,}/REVIEW-.+\\.md", suffix) is not None


def repository_revision(root: Path) -> dict[str, str | None]:
    """Fingerprint exact review target, excluding report/state written by review itself.

    STEP REVIEW сначала фиксирует product/config worktree, затем создаёт immutable
    report. Сам report и .harness/local/** не должны менять reviewed revision.
    """
    code, head = _git(root, "rev-parse", "HEAD")
    git_head = head.decode("utf-8", errors="replace").strip() if code == 0 else None

    code, status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if code != 0:
        raise ValueError("cannot read git worktree state")

    ignored_local = (root / ".harness" / "local").resolve()

    def excluded(path: Path) -> bool:
        resolved = path.resolve()
        try:
            resolved.relative_to(ignored_local)
            return True
        except ValueError:
            pass
        # Configurable reviewDirectory не является blanket trust boundary:
        # исключаем только файлы, которые STEP REVIEW сам создаёт после snapshot.
        return _is_step_review_report_path(root, path)

    entries = [entry for entry in status.split(b"\0") if entry]
    changed: list[tuple[bytes, str]] = []
    skip_next_rename_source = False
    for raw in entries:
        if skip_next_rename_source:
            skip_next_rename_source = False
            continue
        decoded = raw.decode("utf-8", errors="surrogateescape")
        if len(decoded) < 4:
            continue
        xy = raw[:2]
        rel = decoded[3:]
        if "R" in decoded[:2] or "C" in decoded[:2]:
            skip_next_rename_source = True
        path = root / rel
        if excluded(path):
            continue
        changed.append((xy, rel))

    if not changed:
        return {"git_head": git_head, "worktree_hash": None}

    digest = hashlib.sha256()
    for xy, rel in sorted(changed, key=lambda item: item[1]):
        digest.update(xy)
        digest.update(b"\0")
        digest.update(rel.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        path = root / rel
        if path.is_symlink():
            digest.update(b"SYMLINK\0")
            digest.update(str(path.readlink()).encode("utf-8", errors="surrogateescape"))
        elif path.is_file():
            digest.update(b"FILE\0")
            digest.update(path.read_bytes())
        elif path.exists():
            digest.update(b"OTHER\0")
        else:
            digest.update(b"DELETED\0")
        digest.update(b"\0")
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
    if meta.get("reviewer_role") != "reviewer":
        errors.append("reviewer_role must be reviewer")

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
        gate_basis = specialized.get("gate_basis")
        if not _valid_sha256(gate_basis):
            errors.append("specialized_reviews.gate_basis must be sha256")
        reported_required, required_errors = string_list(
            specialized.get("required"),
            "specialized_reviews.required",
        )
        errors.extend(required_errors)
        unknown_required = sorted(set(reported_required) - {"security", "tests"})
        if unknown_required:
            errors.append(
                "specialized_reviews.required contains unknown reviewers: "
                + ", ".join(unknown_required)
            )
        required_set = set(reported_required)
        for kind in ("security", "tests"):
            status = specialized.get(kind)
            if status not in SPECIALIZED_STATUSES:
                errors.append(f"specialized_reviews.{kind} has invalid status")
                continue
            evidence = specialized.get(f"{kind}_evidence")
            reason = specialized.get(f"{kind}_reason")
            if kind in required_set and status == "not_required":
                errors.append(f"{kind} reviewer is marked required but not_required")
            if status == "not_required" and (not isinstance(reason, str) or not reason.strip()):
                errors.append(f"{kind} not_required requires reason")
            if status != "not_required" and (
                not isinstance(evidence, str) or not evidence.strip()
            ):
                errors.append(
                    f"{kind} review status {status} requires evidence summary/reference"
                )

        required_blocked = sorted(
            kind for kind in required_set if specialized.get(kind) == "blocked"
        )
        required_failed = sorted(
            kind for kind in required_set if specialized.get(kind) == "fail"
        )
        if required_blocked and verdict != "blocked":
            errors.append(
                "required specialized reviewer BLOCKED requires overall BLOCKED: "
                + ", ".join(required_blocked)
            )
        if verdict == "pass" and required_failed:
            errors.append(
                "PASS review requires PASS for all required specialized reviewers: "
                + ", ".join(required_failed)
            )

        # Только current-review gate можно честно пересчитать по factual worktree.
        # Historical reports проверяются по сохранённому gate proof, иначе будущий
        # unrelated diff ретроактивно ломал бы immutable history.
        if require_current_revision:
            current_gate = required_reviewers(root, step_id)
            if gate_basis != current_gate["basis"]:
                errors.append("specialized_reviews.gate_basis does not match current review gate")
            if required_set != set(current_gate["required"]):
                errors.append("specialized_reviews.required does not match current review gate")

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


def _is_immutable_review_path(root: Path, rel: str) -> bool:
    """Распознать только реальные immutable reports, не TEMPLATE.md."""
    candidate = (root / rel).resolve()
    patterns = (
        (review_directory(root).resolve(), re.compile(r"^STEP-\\d{3,}/REVIEW-.+\\.md$")),
        (planning_review_directory(root).resolve(), re.compile(r"^STEP-\\d{3,}/PLAN-REVIEW-.+\\.md$")),
        (init_review_directory(root).resolve(), re.compile(r"^INIT-REVIEW-.+\\.md$")),
    )
    for base, pattern in patterns:
        try:
            suffix = candidate.relative_to(base).as_posix()
        except ValueError:
            continue
        return pattern.fullmatch(suffix) is not None
    return False


def _git_changed_review_paths(root: Path, *diff_args: str) -> tuple[list[str], str | None]:
    code, raw = _git(root, *diff_args)
    if code != 0:
        return [], "cannot inspect Git diff for immutable review reports"
    values = raw.decode("utf-8", errors="replace").splitlines()
    return [value for value in values if value and _is_immutable_review_path(root, value)], None


def validate_review_immutability(root: Path, *, ci_mode: bool = False) -> list[str]:
    """Запретить mutation/delete/rename уже существующих immutable reports.

    Addition допустим. До commit проверяем staged + unstaged состояние против
    HEAD. В CI сравниваем итоговый commit с первым родителем: PR merge commit
    тем самым проверяется относительно base, обычный push — относительно parent.
    """
    errors: list[str] = []
    directories = [
        review_directory(root).relative_to(root).as_posix(),
        planning_review_directory(root).relative_to(root).as_posix(),
        init_review_directory(root).relative_to(root).as_posix(),
    ]

    probes: list[tuple[str, tuple[str, ...]]] = [
        (
            "worktree",
            ("diff", "--name-only", "--diff-filter=MDRT", "HEAD", "--", *directories),
        ),
        (
            "index",
            ("diff", "--cached", "--name-only", "--diff-filter=MDRT", "HEAD", "--", *directories),
        ),
    ]
    if ci_mode:
        parent_code, _ = _git(root, "rev-parse", "--verify", "HEAD^1")
        if parent_code == 0:
            probes.append(
                (
                    "commit",
                    ("diff", "--name-only", "--diff-filter=MDRT", "HEAD^1", "HEAD", "--", *directories),
                )
            )
        else:
            # Root commit не имеет baseline и потому не может переписать
            # существующий report. Shallow non-root checkout, напротив, не
            # должен тихо обходить immutability proof.
            count_code, count = _git(root, "rev-list", "--count", "HEAD")
            if count_code != 0 or count.decode("utf-8", errors="replace").strip() != "1":
                errors.append("review immutability: cannot resolve CI baseline HEAD^1")

    seen: set[str] = set()
    for label, args in probes:
        paths, blocker = _git_changed_review_paths(root, *args)
        if blocker is not None:
            errors.append(f"review immutability ({label}): {blocker}")
            continue
        for rel in paths:
            token = f"{label}:{rel}"
            if token in seen:
                continue
            seen.add(token)
            errors.append(f"review immutability: existing report changed ({label}): {rel}")
    return errors


def validate_all_review_reports(root: Path, *, ci_mode: bool = False) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_review_immutability(root, ci_mode=ci_mode))
    directory = review_directory(root)
    if not directory.is_dir():
        return errors
    try:
        pins = legacy_review_pins(root)
    except ValueError as exc:
        pins = {}
        errors.append(f"review: invalid legacy review pins: {exc}")

    # Hash-pinned legacy history должна оставаться физически неизменной.
    for rel, expected in sorted(pins.items()):
        path = root / rel
        if not path.is_file():
            errors.append(f"review: pinned legacy report missing: {rel}")
            continue
        try:
            actual = content_hash(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"review: cannot read pinned legacy report {rel}: {exc}")
            continue
        if actual != expected:
            errors.append(f"review: pinned legacy report changed: {rel}")

    for path in sorted(directory.glob("STEP-*/REVIEW-*.md")):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            frontmatter, _ = split_frontmatter(text)
        except (OSError, UnicodeDecodeError, DocumentError) as exc:
            errors.append(f"review: {rel}: {exc}")
            continue
        if frontmatter is None:
            if pins.get(rel) == content_hash(text):
                continue
            errors.append(
                f"review: {rel}: legacy immutable report is not hash-pinned by schema migration"
            )
            continue
        for issue in validate_review_report(root, path):
            errors.append(f"review: {rel}: {issue}")
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
