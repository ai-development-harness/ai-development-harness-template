#!/usr/bin/env python3
"""Идемпотентная migration active project documents в frontmatter schema=1.

Исторические immutable review/audit/update reports не переписываются. Миграция
касается active STEP/REQ/ADR/OQ и project-owned templates/projections.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from document_contract import (
    ADR_ID_RE,
    OQ_ID_RE,
    REQ_ID_RE,
    STEP_ID_RE,
    content_hash,
    render_document,
    split_frontmatter,
)
from harness_config import (
    adr_directory,
    audit_directory,
    open_questions_directory,
    open_questions_index_path,
    requirements_directory,
    task_directory,
)
from projection_contract import write_projections
from review_contract import current_legacy_review_snapshots, legacy_review_pins
from template_contract import refresh_project_templates


STATUS_MAP = {
    "Запланировано": "planned",
    "В работе": "in_progress",
    "Заблокировано": "blocked",
    "Выполнено": "completed",
    "Отложено": "deferred",
    "Отменено": "cancelled",
    "Заменено": "cancelled",
}
PRIORITY_MAP = {
    "Критический": "critical",
    "Высокий": "high",
    "Средний": "medium",
    "Низкий": "low",
}
ADR_STATUS_MAP = {
    "Proposed": "proposed",
    "Accepted": "accepted",
    "Superseded": "superseded",
    "Rejected": "rejected",
}
RISK_FLAGS = {
    "none", "security-sensitive", "data-migration", "destructive", "public-api",
    "architecture", "concurrency", "external-integration",
    "performance-critical", "release-critical",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _legacy_metadata(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in re.finditer(r"(?m)^\*\*([^*]+?):\*\*\s*(.*)$", text):
        result[match.group(1).strip()] = match.group(2).strip()
    return result


def _sections(text: str) -> dict[str, str]:
    result: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.replace("\r\n", "\n").splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip()
            result.setdefault(current, [])
            continue
        if current is not None:
            result[current].append(line)
    return {key: "\n".join(value).strip() for key, value in result.items()}


def _ids(value: str, pattern: re.Pattern[str]) -> list[str]:
    return sorted(set(pattern.findall(value)))


def _h1(text: str, pattern: re.Pattern[str]) -> tuple[str, str]:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    match = re.fullmatch(rf"# ({pattern.pattern}) — (.+)", first)
    if not match:
        raise ValueError(f"cannot parse legacy H1: {first}")
    return match.group(1), match.group(2)


def _body_from_sections(title: str, sections: dict[str, str], names: list[str]) -> str:
    chunks = [title, ""]
    for name in names:
        if name not in sections:
            continue
        chunks.extend([f"## {name}", "", sections[name], ""])
    return "\n".join(chunks).strip()


def _clean_plan_section(value: str) -> str:
    lines = []
    for line in value.splitlines():
        if re.match(r"^\*\*(Plan status|Plan revision|Plan basis|Planned at):\*\*", line):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    return cleaned or "Требуется повторный STEP PLAN после schema migration."


def migrate_legacy_step(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if split_frontmatter(text)[0] is not None:
        return False
    step_id, title = _h1(text, STEP_ID_RE)
    meta = _legacy_metadata(text)
    sections = _sections(text)
    old_plan = _legacy_metadata(sections.get("Implementation plan", ""))
    old_ready = old_plan.get("Plan status") == "Ready"
    risks = [
        flag for flag in RISK_FLAGS
        if re.search(rf"(?<![A-Za-z0-9-]){re.escape(flag)}(?![A-Za-z0-9-])", sections.get("Risk flags", ""))
    ] or ["none"]

    frontmatter: dict[str, Any] = {
        "schema": 1,
        "id": step_id,
        "status": STATUS_MAP.get(meta.get("Статус", ""), "planned"),
        "type": meta.get("Type", "IMPLEMENTATION").lower(),
        "priority": PRIORITY_MAP.get(meta.get("Приоритет", ""), "medium"),
        "phase": meta.get("Фаза") or "TBD",
        "depends_on": _ids(meta.get("Depends on", ""), STEP_ID_RE),
        "requirements": _ids(sections.get("Requirements", ""), REQ_ID_RE),
        "adrs": _ids(sections.get("ADR", ""), ADR_ID_RE),
        "architecture_refs": [],
        "risk_flags": risks,
        "plan": {
            # Старый Ready не имеет durable planning-review/content hash и не
            # переносится как доказанный Ready.
            "status": "draft" if old_ready else "not_planned",
            "revision": int(old_plan.get("Plan revision", "0")) if old_plan.get("Plan revision", "").isdigit() else 0,
            "context_basis": None,
            "content_hash": None,
            "reviewed_report": None,
            "planned_at": None,
        },
        "review": {
            "latest_verdict": "not_reviewed",
            "latest_report": None,
        },
    }

    kept = [
        "Goal", "Context", "Scope", "Mutation policy", "Out of scope",
        "Acceptance criteria", "Verification", "Deliverables",
        "Implementation plan", "Evidence", "Blocker / Failure reason",
    ]
    if "Implementation plan" in sections:
        sections["Implementation plan"] = _clean_plan_section(sections["Implementation plan"])
    body = _body_from_sections(f"# {step_id} — {title}", sections, kept)
    path.write_text(render_document(frontmatter, body), encoding="utf-8", newline="\n")
    return True


def migrate_legacy_requirement(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if split_frontmatter(text)[0] is not None:
        return False
    req_id, title = _h1(text, REQ_ID_RE)
    meta = _legacy_metadata(text)
    sections = _sections(text)
    trace = sections.get("Traceability", "")
    frontmatter = {
        "schema": 1,
        "id": req_id,
        "priority": PRIORITY_MAP.get(meta.get("Приоритет", ""), "medium"),
        "source": (meta.get("Источник") or "other").lower().replace(" ", "_"),
        "steps": _ids(trace, STEP_ID_RE),
        "adrs": _ids(trace, ADR_ID_RE),
    }
    body = _body_from_sections(
        f"# {req_id} — {title}",
        sections,
        ["Requirement", "Rationale", "Acceptance"],
    )
    path.write_text(render_document(frontmatter, body), encoding="utf-8", newline="\n")
    return True


def migrate_monolithic_requirements(root: Path) -> list[str]:
    directory = requirements_directory(root)
    spec = directory / "SPEC.md"
    if not spec.is_file():
        return []
    text = spec.read_text(encoding="utf-8")
    if list(directory.glob("REQ-*.md")):
        return []
    matches = list(re.finditer(r"(?m)^#{2,}\s+(REQ-\d{3,})\s+—\s+(.+)$", text))
    changed: list[str] = []
    for index, match in enumerate(matches):
        req_id, title = match.group(1), match.group(2).strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = text[match.start():end]
        sub: dict[str, str] = {}
        for name in ("Requirement", "Rationale", "Acceptance", "Traceability"):
            heading = re.search(rf"(?m)^#{{2,6}}\s+{re.escape(name)}\s*$", chunk)
            if not heading:
                continue
            next_heading = re.search(r"(?m)^#{2,6}\s+", chunk[heading.end():])
            finish = heading.end() + next_heading.start() if next_heading else len(chunk)
            sub[name] = chunk[heading.end():finish].strip()
        frontmatter = {
            "schema": 1,
            "id": req_id,
            "priority": "medium",
            "source": "legacy",
            "steps": _ids(sub.get("Traceability", ""), STEP_ID_RE),
            "adrs": _ids(sub.get("Traceability", ""), ADR_ID_RE),
        }
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "requirement"
        path = directory / f"{req_id}-{slug}.md"
        body = _body_from_sections(
            f"# {req_id} — {title}",
            sub,
            ["Requirement", "Rationale", "Acceptance"],
        )
        path.write_text(render_document(frontmatter, body), encoding="utf-8", newline="\n")
        changed.append(path.relative_to(root).as_posix())
    return changed


def migrate_legacy_adr(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if split_frontmatter(text)[0] is not None:
        return False
    adr_id, title = _h1(text, ADR_ID_RE)
    meta = _legacy_metadata(text)
    sections = _sections(text)
    trace = sections.get("Traceability", "")
    frontmatter = {
        "schema": 1,
        "id": adr_id,
        "status": ADR_STATUS_MAP.get(meta.get("Status", ""), "proposed"),
        "date": meta.get("Date") or None,
        "deciders": [item.strip() for item in meta.get("Deciders", "").split(",") if item.strip() and item.strip() != "TBD"],
        "supersedes": _ids(meta.get("Supersedes", ""), ADR_ID_RE),
        "superseded_by": _ids(meta.get("Superseded by", ""), ADR_ID_RE),
        "requirements": _ids(trace, REQ_ID_RE),
        "steps": _ids(trace, STEP_ID_RE),
    }
    body = _body_from_sections(
        f"# {adr_id} — {title}",
        sections,
        [
            "Context", "Problem", "Decision", "Alternatives considered",
            "Consequences", "Security implications", "Data / migration implications",
            "Compatibility / operational implications",
        ],
    )
    path.write_text(render_document(frontmatter, body), encoding="utf-8", newline="\n")
    return True


def migrate_monolithic_open_questions(root: Path) -> list[str]:
    index = open_questions_index_path(root)
    if not index.is_file():
        return []
    text = index.read_text(encoding="utf-8")
    if "| OQ |" in text:
        return []
    directory = open_questions_directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    starts = list(re.finditer(r"(?m)^(?:#{1,6}\s+)?(OQ-\d{3,})\s+—\s+(.+)$", text))
    changed: list[str] = []
    for pos, match in enumerate(starts):
        oq_id, title = match.group(1), match.group(2).strip()
        end = starts[pos + 1].start() if pos + 1 < len(starts) else len(text)
        chunk = text[match.end():end]
        status_match = re.search(r"(?mi)^(?:\*\*)?Status:(?:\*\*)?\s*(OPEN|RESOLVED|DEFERRED)", chunk)
        affects_match = re.search(r"(?mi)^(?:\*\*)?Affects:(?:\*\*)?\s*(.+)$", chunk)
        context = re.search(r"(?mi)^(?:\*\*)?Context:(?:\*\*)?\s*(.+)$", chunk)
        decision = re.search(r"(?mi)^(?:\*\*)?Decision needed:(?:\*\*)?\s*(.+)$", chunk)
        resolution = re.search(r"(?mi)^(?:\*\*)?Resolution:(?:\*\*)?\s*(.+)$", chunk)
        affects: list[str] = []
        if affects_match:
            affects.extend(_ids(affects_match.group(1), STEP_ID_RE))
            affects.extend(_ids(affects_match.group(1), REQ_ID_RE))
            affects.extend(_ids(affects_match.group(1), ADR_ID_RE))
            if "PROJECT" in affects_match.group(1):
                affects.append("PROJECT")
        frontmatter = {
            "schema": 1,
            "id": oq_id,
            "status": (status_match.group(1).lower() if status_match else "open"),
            "affects": sorted(set(affects)) or ["PROJECT"],
            "created_at": None,
            "resolved_at": None,
        }
        body = (
            f"# {oq_id} — {title}\n\n"
            f"## Context\n\n{context.group(1).strip() if context else 'Legacy context not structured.'}\n\n"
            f"## Decision needed\n\n{decision.group(1).strip() if decision else 'Требуется решение.'}\n\n"
            f"## Resolution\n\n{resolution.group(1).strip() if resolution else ''}"
        )
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "question"
        path = directory / f"{oq_id}-{slug}.md"
        path.write_text(render_document(frontmatter, body), encoding="utf-8", newline="\n")
        changed.append(path.as_posix())
    return changed


def _pending_legacy_review_pins(root: Path) -> dict[str, str]:
    """Новые legacy reviews для pinning; corruption уже pinned history блокирует migration."""
    try:
        recorded = legacy_review_pins(root)
    except ValueError as exc:
        raise ValueError(f"invalid recorded legacy review pins: {exc}") from exc
    current = current_legacy_review_snapshots(root)

    for rel, expected in recorded.items():
        path = root / rel
        if not path.is_file():
            raise ValueError(f"pinned legacy review is missing: {rel}")
        try:
            actual = content_hash(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"cannot read pinned legacy review {rel}: {exc}") from exc
        if actual != expected:
            raise ValueError(f"pinned legacy review changed after migration: {rel}")

    return {
        rel: digest
        for rel, digest in current.items()
        if rel not in recorded
    }


def legacy_schema_pending(root: Path) -> bool:
    paths: list[Path] = []
    paths.extend(task_directory(root).glob("STEP-*.md"))
    paths.extend(
        path for path in requirements_directory(root).glob("REQ-*.md")
        if path.name != "TEMPLATE.md"
    )
    paths.extend(
        path for path in adr_directory(root).glob("ADR-*.md")
        if path.name != "TEMPLATE.md"
    )
    for path in paths:
        try:
            if split_frontmatter(path.read_text(encoding="utf-8"))[0] is None:
                return True
        except (OSError, UnicodeDecodeError):
            return True
    spec = requirements_directory(root) / "SPEC.md"
    if spec.is_file() and not list(requirements_directory(root).glob("REQ-*.md")):
        if re.search(r"(?m)^#{2,}\s+REQ-\d{3,}\b", spec.read_text(encoding="utf-8")):
            return True
    index = open_questions_index_path(root)
    if index.is_file():
        data = index.read_text(encoding="utf-8")
        if re.search(r"(?m)^(?:#{1,6}\s+)?OQ-\d{3,}\s+—", data):
            return True
    try:
        if _pending_legacy_review_pins(root):
            return True
    except ValueError:
        return True
    return False


def migrate_project(root: Path) -> dict[str, Any]:
    pending_legacy_reviews = _pending_legacy_review_pins(root)
    changed: list[str] = []
    changed.extend(migrate_monolithic_requirements(root))
    for path in sorted(task_directory(root).glob("STEP-*.md")):
        if migrate_legacy_step(path):
            changed.append(path.relative_to(root).as_posix())
    for path in sorted(requirements_directory(root).glob("REQ-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        if migrate_legacy_requirement(path):
            changed.append(path.relative_to(root).as_posix())
    for path in sorted(adr_directory(root).glob("ADR-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        if migrate_legacy_adr(path):
            changed.append(path.relative_to(root).as_posix())
    changed.extend(
        str(Path(item).relative_to(root)) if Path(item).is_absolute() else item
        for item in migrate_monolithic_open_questions(root)
    )

    # Project-owned templates не обновляются HARNESS UPDATE. RECONCILE
    # синхронизирует их из protocol-owned definitions и затем projections.
    changed.extend(refresh_project_templates(root))
    changed.extend(write_projections(root))

    unique_changed = sorted(set(changed))
    if not unique_changed and not pending_legacy_reviews:
        return {
            "status": "NO_CHANGES",
            "changed": [],
            "report": None,
        }

    report_dir = audit_directory(root)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = report_dir / f"MIGRATION-{timestamp}.md"
    body = "# Project Schema Migration\n\n## Changed artifacts\n\n"
    body += "\n".join(f"- {item}" for item in unique_changed) if unique_changed else "- none"
    body += (
        "\n\n## Legacy immutable reviews\n\n"
        + (
            "\n".join(f"- pinned {rel}" for rel in sorted(pending_legacy_reviews))
            if pending_legacy_reviews
            else "- no new legacy review pins"
        )
    )
    body += "\n\n## Notes\n\nHistorical immutable reports were not rewritten."
    report_meta = {
        "schema": 1,
        "kind": "migration",
        "created_at": _utc_now(),
        "result": "complete",
        "changed_count": len(unique_changed),
        "legacy_review_reports": [
            f"{digest} {rel}"
            for rel, digest in sorted(pending_legacy_reviews.items())
        ],
    }
    report.write_text(render_document(report_meta, body), encoding="utf-8", newline="\n")
    return {
        "status": "MIGRATED",
        "changed": unique_changed,
        "report": report.relative_to(root).as_posix(),
    }
