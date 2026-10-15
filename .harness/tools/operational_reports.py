#!/usr/bin/env python3
"""Детерминированная запись operational reports из semantic payload (#316).

Здесь нет второй schema/parser/state machine. Текущий project-owned TEMPLATE
задаёт разделы, document_contract — формат и immutable reservation,
report_contract — final structural validation, execution_status — provenance.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

from document_contract import (
    create_durable_report,
    has_unresolved_placeholder,
    parse_document,
    render_document,
)
from execution_status import (
    active_execution_for_command,
    execution_state_lock,
    normalize_single_command,
    record_operational_report,
)
from harness_config import (
    audit_directory,
    release_directory,
    skill_search_directory,
    skill_search_max_results,
)
from report_contract import (
    validate_audit_report,
    validate_release_report,
    validate_skill_search_report,
)
from review_contract import repository_subject_content_hash


KIND_CONFIG = {
    "audit": (audit_directory, "AUDIT-", validate_audit_report, "# Audit — "),
    "release_check": (release_directory, "RELEASE-", validate_release_report, "# Release Check — "),
    "skill_search": (skill_search_directory, "SKILL-SEARCH-", validate_skill_search_report, "# SKILL SEARCH — "),
}
COMMAND_KINDS = {
    ("PROJECT", "RECONCILE"): "audit",
    ("STEP", "AUDIT"): "audit",
    ("RELEASE", "CHECK"): "release_check",
    ("SKILL", "FIND"): "skill_search",
}
CANDIDATE_FIELDS = {
    "Repository": "repository",
    "Path": "path",
    "URL": "url",
    "Ref/commit inspected": "inspectedRef",
    "License": "license",
    "Why it fits": "whyItFits",
    "Limitations": "limitations",
    "Safety notes": "safetyNotes",
    "Recommendation": "recommendation",
}


class OperationalReportError(ValueError):
    """Нарушен writer/command/report contract; статус выполнения не меняется."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _object(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise OperationalReportError(
            "REPORT_PAYLOAD_INVALID",
            f"{label} requires exactly {sorted(expected)}",
        )
    return value


def _line(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise OperationalReportError("REPORT_PAYLOAD_INVALID", f"{label} must be non-empty text")
    cleaned = value.strip()
    if any(char in cleaned for char in ("\n", "\r", "\0")):
        raise OperationalReportError("REPORT_PAYLOAD_INVALID", f"{label} must be one line")
    if has_unresolved_placeholder(cleaned):
        raise OperationalReportError("REPORT_PLACEHOLDER", f"{label} has placeholder")
    return cleaned


def _section(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128 * 1024:
        raise OperationalReportError("REPORT_PAYLOAD_INVALID", f"{label} must contain evidence")
    text = value.strip()
    if has_unresolved_placeholder(text):
        raise OperationalReportError("REPORT_PLACEHOLDER", f"{label} contains TBD/TODO")
    # Payload может содержать H3, списки и фрагменты кода, но не подменять
    # canonical H2 sections template своими заголовками.
    if re.search(r"(?m)^##\s+", text):
        raise OperationalReportError("REPORT_SECTION_UNSAFE", f"{label} contains H2")
    return text


def _candidates(value: Any, root: Path) -> tuple[str, int]:
    if not isinstance(value, list):
        raise OperationalReportError("REPORT_PAYLOAD_INVALID", "candidates must be an array")
    limit = skill_search_max_results(root)
    if len(value) > limit:
        raise OperationalReportError("REPORT_CANDIDATES_EXCEEDED", f"maxResults={limit}")
    if not value:
        return "- none", 0
    blocks: list[str] = []
    for index, item in enumerate(value, start=1):
        row = _object(item, {"name", *CANDIDATE_FIELDS.values()}, f"candidate #{index}")
        blocks.append(f"### #{index} — {_line(row['name'], 'candidate.name')}")
        for display, key in CANDIDATE_FIELDS.items():
            blocks.append(f"- {display}: {_line(row[key], key)}")
        blocks.append("")
    return "\n".join(blocks).strip(), len(value)


def _report_parts(
    root: Path, kind: str, payload: Any, template: dict[str, Any], command: dict[str, Any],
) -> tuple[dict[str, Any], str, dict[str, str]]:
    """Построить metadata только из validated semantic inputs + template."""
    if kind == "audit":
        p = _object(payload, {"scope", "sections"}, "audit payload")
        scope = _line(p["scope"], "scope")
        expected = ("project" if command["domain"] == "PROJECT" else command["target"])
        if scope != expected:
            raise OperationalReportError("REPORT_SCOPE_MISMATCH", f"audit scope must be {expected}")
        updates = {"scope": scope, "mode": "audit", "result": "complete"}
        title = scope
    elif kind == "release_check":
        p = _object(payload, {"target", "verdict", "sections"}, "release payload")
        target = _line(p["target"], "target")
        if command.get("target") and command["target"] != target:
            raise OperationalReportError("REPORT_TARGET_MISMATCH", "release target differs from command")
        verdict = p["verdict"]
        if verdict not in {"ready", "blocked"}:
            raise OperationalReportError("REPORT_PAYLOAD_INVALID", "verdict must be ready|blocked")
        updates = {"target": target, "verdict": verdict}
        title = target
    else:
        p = _object(payload, {"query", "candidates", "sections"}, "skill search payload")
        query = _line(p["query"], "query")
        if query != command.get("input"):
            raise OperationalReportError("REPORT_QUERY_MISMATCH", "query differs from active SKILL FIND")
        candidates, count = _candidates(p["candidates"], root)
        updates = {"query": query, "status": "complete", "candidate_count": count}
        title = query

    sections = p["sections"]
    if not isinstance(sections, dict):
        raise OperationalReportError("REPORT_PAYLOAD_INVALID", "sections must be a map")

    required = list(template["sections"])
    supplied = set(sections)
    if kind == "skill_search":
        if "Candidates" not in required or "Candidates" in supplied:
            raise OperationalReportError("REPORT_PAYLOAD_INVALID", "Candidates is generated by writer")
        required_without_candidates = set(required) - {"Candidates"}
        if supplied != required_without_candidates:
            raise OperationalReportError("REPORT_TEMPLATE_MISMATCH", "missing/extra configured report sections")
        complete_sections = {name: (candidates if name == "Candidates" else _section(sections[name], name))
                             for name in required}
    else:
        if supplied != set(required):
            raise OperationalReportError("REPORT_TEMPLATE_MISMATCH", "missing/extra configured report sections")
        complete_sections = {name: _section(sections[name], name) for name in required}

    meta = dict(template["frontmatter"])
    meta.update({"schema": 1, "kind": kind, **updates})
    return meta, title, complete_sections


def _active(root: Path, execution_id: str, kind: str) -> tuple[str, dict[str, Any]]:
    """Сверить identity с текущей running command; не доверять kind от LLM."""
    if not isinstance(execution_id, str) or not execution_id:
        raise OperationalReportError("EXECUTION_ID_REQUIRED", "executionId from handoff required")
    from execution_status import load_status
    state = load_status(root)
    matches = [e for e in state.get("executions", [])
               if e.get("executionId") == execution_id
               and e.get("status") == "running"
               and isinstance(e.get("current"), dict)
               and e["current"].get("status") == "running"]
    if len(matches) != 1:
        raise OperationalReportError("REPORT_EXECUTION_STALE", "executionId not running")
    current = matches[0]["current"]
    command = str(current["command"])
    parsed = normalize_single_command(root, command)
    if COMMAND_KINDS.get((parsed["domain"], parsed["operation"])) != kind:
        raise OperationalReportError("REPORT_COMMAND_MISMATCH", "active command does not require requested report")
    owner = active_execution_for_command(root, command)
    if owner is None or owner["executionId"] != execution_id:
        raise OperationalReportError("REPORT_EXECUTION_AMBIGUOUS", "multiple active owners or stale execution")
    if current.get("context", {}).get("operationalReport") is not None:
        raise OperationalReportError("REPORT_ALREADY_RECORDED", "current execution already has a report")
    return command, parsed


def write_operational_report(
    root: Path, kind: str, payload: Any, *, execution_id: str,
) -> dict[str, Any]:
    """Создать и валидировать immutable report, затем записать receipt в local state.

    Crash после durable create, но до receipt может оставить orphan report.
    Такой файл не даёт SUCCESS; повторный вызов резервирует НОВОЕ имя.
    """
    root = root.resolve()
    if kind not in KIND_CONFIG:
        raise OperationalReportError("REPORT_KIND_UNSUPPORTED", f"unsupported kind: {kind}")
    directory_fn, prefix, validate, heading = KIND_CONFIG[kind]
    with execution_state_lock(root):
        command, parsed = _active(root, execution_id, kind)
        directory = directory_fn(root)
        if not directory.resolve().is_relative_to(root):
            raise OperationalReportError("REPORT_DIRECTORY_UNSAFE", "report directory escapes root")
        if directory.is_symlink():
            raise OperationalReportError("REPORT_DIRECTORY_UNSAFE", "report directory is symlink")
        template_path = directory / "TEMPLATE.md"
        if template_path.is_symlink() or not template_path.is_file():
            raise OperationalReportError("REPORT_TEMPLATE_MISSING", "configured TEMPLATE.md unavailable")
        template = parse_document(template_path)
        if template["frontmatter"].get("kind") != kind or template["frontmatter"].get("schema") != 1:
            raise OperationalReportError("REPORT_TEMPLATE_INVALID", "TEMPLATE schema/kind mismatch")
        meta, title, sections = _report_parts(root, kind, payload, template, parsed)
        subject_before = repository_subject_content_hash(root)
        def render(created_at: str) -> str:
            frontmatter = {**meta, "created_at": created_at}
            body = heading + title + "\n\n" + "\n\n".join(
                f"## {name}\n\n{text}" for name, text in sections.items()
            )
            return render_document(frontmatter, body)

        path, instant = create_durable_report(prefix, directory=directory, content_factory=render)
        content = render(instant).encode("utf-8")
        issues = validate(root, path)
        if issues or path.read_bytes() != content:
            # Не удаляем чужую concurrent mutation: ownership ограничено
            # только неизменёнными bytes только что созданного report.
            if path.is_file() and not path.is_symlink() and path.read_bytes() == content:
                path.unlink()
            raise OperationalReportError("REPORT_VALIDATION_FAILED", "; ".join(issues) or "report bytes changed")
        if subject_before != repository_subject_content_hash(root):
            raise OperationalReportError("REPORT_SOURCE_CHANGED", "project changed while writing report")
        report_rel = path.resolve().relative_to(root).as_posix()
        receipt = {
            "kind": kind,
            "command": command,
            "executionId": execution_id,
            "path": report_rel,
            "sha256": hashlib.sha256(content).hexdigest(),
            "subjectHash": subject_before,
        }
        # Единственное место записи execution-bound provenance.
        record_operational_report(root, command, execution_id, receipt)
        return {
            "schemaVersion": 1,
            "status": "PASS",
            "completionResult": "SUCCESS",
            "executionId": execution_id,
            "kind": kind,
            "report": report_rel,
            "reportSha256": receipt["sha256"],
            "writerValidated": True,
        }


__all__ = ["OperationalReportError", "write_operational_report", "COMMAND_KINDS"]
