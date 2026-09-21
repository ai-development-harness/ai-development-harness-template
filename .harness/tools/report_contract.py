#!/usr/bin/env python3
"""Строгие contracts durable AUDIT / RELEASE CHECK / SKILL FIND reports.

Эти reports используются как долговременные факты repository. Особенно важен
SKILL SEARCH: команда SKILL INSTALL: #N resolve-ит выбор пользователя именно из
последнего сохранённого отчёта, а не из chat history.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import argparse
import json
import re
from typing import Any

from document_contract import DocumentError, parse_document
from harness_config import (
    audit_directory,
    release_directory,
    skill_search_directory,
    skill_search_max_results,
)


def _valid_iso_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _valid_timestamped_filename(name: str, prefix: str) -> bool:
    match = re.fullmatch(rf"{re.escape(prefix)}(\d{{8}}T\d{{6}}Z)\.md", name)
    if match is None:
        return False
    try:
        datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ")
    except ValueError:
        return False
    return True


def _require_sections(document: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    for name in names:
        value = document["sections"].get(name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"missing or empty section '## {name}'")
    return errors


def validate_audit_report(root: Path, path: Path) -> list[str]:
    errors: list[str] = []
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]
    meta = document["frontmatter"]

    if meta.get("schema") != 1:
        errors.append("schema must be 1")
    if meta.get("kind") != "audit":
        errors.append("kind must be audit")
    if not isinstance(meta.get("scope"), str) or not meta.get("scope", "").strip():
        errors.append("scope must be non-empty string")
    if meta.get("mode") != "audit":
        errors.append("mode must be audit")
    if meta.get("result") != "complete":
        errors.append("result must be complete")
    if not _valid_iso_timestamp(meta.get("created_at")):
        errors.append("created_at must be ISO-8601")
    if not _valid_timestamped_filename(path.name, "AUDIT-"):
        errors.append("filename must be AUDIT-<UTC timestamp>.md")
    if not document.get("h1", "").startswith("# Audit — "):
        errors.append("H1 must start with '# Audit — '")
    errors.extend(
        _require_sections(
            document,
            ("Sources checked", "Actual state", "Drift / findings", "Evidence", "Corrective actions"),
        )
    )
    return errors


def validate_release_report(root: Path, path: Path) -> list[str]:
    errors: list[str] = []
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]
    meta = document["frontmatter"]

    if meta.get("schema") != 1:
        errors.append("schema must be 1")
    if meta.get("kind") != "release_check":
        errors.append("kind must be release_check")
    if not isinstance(meta.get("target"), str) or not meta.get("target", "").strip():
        errors.append("target must be non-empty string")
    if meta.get("verdict") not in {"ready", "blocked"}:
        errors.append("verdict must be ready|blocked")
    if not _valid_iso_timestamp(meta.get("created_at")):
        errors.append("created_at must be ISO-8601")
    if not _valid_timestamped_filename(path.name, "RELEASE-"):
        errors.append("filename must be RELEASE-<UTC timestamp>.md")
    if not document.get("h1", "").startswith("# Release Check — "):
        errors.append("H1 must start with '# Release Check — '")
    errors.extend(
        _require_sections(
            document,
            (
                "Requirements / scope",
                "Verification gates",
                "Security / migrations / compatibility",
                "Unresolved blockers",
                "Evidence",
            ),
        )
    )
    return errors


_CANDIDATE_HEADING_RE = re.compile(r"(?m)^### #(\d+) — (.+?)\s*$")
_CANDIDATE_FIELD_RE = re.compile(
    r"(?m)^- (Repository|Path|URL|Ref/commit inspected|License|Why it fits|Limitations|Safety notes|Recommendation):\s*(.+?)\s*$"
)
_REQUIRED_CANDIDATE_FIELDS = {
    "Repository",
    "Path",
    "URL",
    "Ref/commit inspected",
    "License",
    "Why it fits",
    "Limitations",
    "Safety notes",
    "Recommendation",
}


def _validate_skill_candidates(section: str, count: int) -> list[str]:
    errors: list[str] = []
    headings = list(_CANDIDATE_HEADING_RE.finditer(section))
    numbers = [int(match.group(1)) for match in headings]
    expected = list(range(1, count + 1))
    if numbers != expected:
        errors.append(
            "Candidates headings must be contiguous #1..#candidate_count "
            f"(expected {expected}, got {numbers})"
        )

    for index, heading in enumerate(headings):
        number = int(heading.group(1))
        end = headings[index + 1].start() if index + 1 < len(headings) else len(section)
        block = section[heading.end():end]
        fields = {match.group(1) for match in _CANDIDATE_FIELD_RE.finditer(block)}
        missing = sorted(_REQUIRED_CANDIDATE_FIELDS - fields)
        if missing:
            errors.append(
                f"candidate #{number} missing fields: " + ", ".join(missing)
            )
    return errors


def validate_skill_search_report(root: Path, path: Path) -> list[str]:
    errors: list[str] = []
    try:
        document = parse_document(path)
    except DocumentError as exc:
        return [str(exc)]
    meta = document["frontmatter"]

    if meta.get("schema") != 1:
        errors.append("schema must be 1")
    if meta.get("kind") != "skill_search":
        errors.append("kind must be skill_search")
    if not isinstance(meta.get("query"), str) or not meta.get("query", "").strip():
        errors.append("query must be non-empty string")
    if meta.get("status") != "complete":
        errors.append("status must be complete")
    if not _valid_iso_timestamp(meta.get("created_at")):
        errors.append("created_at must be ISO-8601")

    count = meta.get("candidate_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        errors.append("candidate_count must be a non-negative integer")
        count_value = 0
    else:
        count_value = count
        try:
            maximum = skill_search_max_results(root)
        except Exception as exc:
            errors.append(f"cannot resolve skills.search.maxResults: {exc}")
        else:
            if count > maximum:
                errors.append(
                    f"candidate_count exceeds skills.search.maxResults ({maximum})"
                )

    if not _valid_timestamped_filename(path.name, "SKILL-SEARCH-"):
        errors.append("filename must be SKILL-SEARCH-<UTC timestamp>.md")
    if not document.get("h1", "").startswith("# SKILL SEARCH — "):
        errors.append("H1 must start with '# SKILL SEARCH — '")

    errors.extend(
        _require_sections(
            document,
            (
                "Search strategy",
                "Ranking criteria",
                "Candidates",
                "Rejected / notable alternatives",
                "Next command",
            ),
        )
    )
    candidates = document["sections"].get("Candidates", "")
    if isinstance(candidates, str):
        errors.extend(_validate_skill_candidates(candidates, count_value))
    return errors


def validate_all_operational_reports(root: Path) -> list[str]:
    """Проверить все durable operational reports, кроме migration/reviews."""
    errors: list[str] = []

    audit_root = audit_directory(root)
    if audit_root.is_dir():
        for path in sorted(audit_root.glob("*.md")):
            if path.name in {"README.md", "TEMPLATE.md"} or path.name.startswith("MIGRATION-"):
                continue
            if not path.name.startswith("AUDIT-"):
                errors.append(
                    f"audit-report: unexpected durable artifact name: {path.relative_to(root)}"
                )
                continue
            for issue in validate_audit_report(root, path):
                errors.append(f"audit-report: {path.relative_to(root)}: {issue}")

    release_root = release_directory(root)
    if release_root.is_dir():
        for path in sorted(release_root.glob("*.md")):
            if path.name in {"README.md", "TEMPLATE.md"}:
                continue
            if not path.name.startswith("RELEASE-"):
                errors.append(
                    f"release-report: unexpected durable artifact name: {path.relative_to(root)}"
                )
                continue
            for issue in validate_release_report(root, path):
                errors.append(f"release-report: {path.relative_to(root)}: {issue}")

    search_root = skill_search_directory(root)
    if search_root.is_dir():
        for path in sorted(search_root.glob("*.md")):
            if path.name in {"README.md", "TEMPLATE.md"}:
                continue
            if not path.name.startswith("SKILL-SEARCH-"):
                errors.append(
                    f"skill-search-report: unexpected durable artifact name: {path.relative_to(root)}"
                )
                continue
            for issue in validate_skill_search_report(root, path):
                errors.append(f"skill-search-report: {path.relative_to(root)}: {issue}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file")
    parser.add_argument("--kind", choices=["audit", "release_check", "skill_search"])
    parser.add_argument("--all", action="store_true", dest="validate_all")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    if args.validate_all:
        errors = validate_all_operational_reports(root)
    elif args.file and args.kind:
        path = (root / args.file).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            errors = ["report path escapes repository"]
        else:
            validators = {
                "audit": validate_audit_report,
                "release_check": validate_release_report,
                "skill_search": validate_skill_search_report,
            }
            errors = validators[args.kind](root, path)
    else:
        parser.error("use --all or --file <path> --kind <kind>")

    result = {"valid": not errors, "errors": errors}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("REPORT CONTRACT: FAIL")
        for item in errors:
            print(f"  - {item}")
    else:
        print("REPORT CONTRACT: PASS")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
