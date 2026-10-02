#!/usr/bin/env python3
"""Runtime-neutral role-specific Context Contracts for STEP semantic work.

The resolver returns repository references and exact section projections. It does
not summarize semantic content and never silently falls back to a full-repo scan.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from document_contract import parse_document
from harness_config import get, load_manifest, resolve_repo_path
from planning_contract import (
    adr_ids,
    architecture_refs,
    canonical_adr_path,
    canonical_requirement_path,
    dependency_ids,
    read_task,
    relevant_open_questions,
    requirement_ids,
    task_path,
)

SCHEMA_VERSION = 1
ROLES = {"planner", "implementer", "reviewer"}
ROLE_SECTIONS = {
    "planner": {
        "step": ["Goal", "Context", "Scope", "Mutation policy", "Out of scope", "Acceptance criteria", "Verification"],
        "requirement": ["Requirement", "Rationale", "Acceptance"],
        "adr": ["Decision", "Consequences", "Security implications", "Data / migration implications", "Compatibility / operational implications"],
        "dependency": ["Goal", "Acceptance criteria"],
        "oq": ["Context", "Decision needed", "Resolution"],
    },
    "implementer": {
        "step": ["Scope", "Mutation policy", "Out of scope", "Acceptance criteria", "Verification", "Implementation plan"],
        "requirement": ["Requirement", "Acceptance"],
        "adr": ["Decision", "Consequences", "Security implications", "Data / migration implications", "Compatibility / operational implications"],
        "dependency": ["Goal", "Acceptance criteria", "Evidence"],
        "oq": ["Decision needed", "Resolution"],
    },
    "reviewer": {
        "step": ["Scope", "Mutation policy", "Out of scope", "Acceptance criteria", "Verification", "Implementation plan", "Evidence"],
        "requirement": ["Requirement", "Acceptance"],
        "adr": ["Decision", "Consequences", "Security implications", "Data / migration implications", "Compatibility / operational implications"],
        "dependency": ["Goal", "Acceptance criteria", "Evidence"],
        "oq": ["Context", "Decision needed", "Resolution"],
    },
}


class ContextContractError(ValueError):
    """Context cannot be resolved safely and must fail closed."""


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ContextContractError(f"context path escapes repository: {path}") from exc


def _projection(root: Path, path: Path, artifact: str, sections: list[str]) -> dict[str, Any]:
    doc = parse_document(path)
    missing = [name for name in sections if name not in doc["sections"]]
    if missing:
        raise ContextContractError(
            f"{artifact}: required sections missing: " + ", ".join(missing)
        )
    return {
        "artifact": artifact,
        "path": _rel(root, path),
        "sections": sections,
    }


def _architecture_projection(root: Path, ref: str) -> dict[str, Any]:
    path_part, marker, fragment = ref.partition("#")
    if not path_part:
        raise ContextContractError(f"architecture ref has empty path: {ref}")
    path = (root / path_part).resolve()
    _rel(root, path)
    if not path.is_file():
        raise ContextContractError(f"architecture ref file not found: {ref}")
    return {
        "artifact": ref,
        "path": _rel(root, path),
        "anchor": fragment if marker else None,
        "sections": [],
    }


def _optional_principles(root: Path) -> list[dict[str, Any]]:
    """Include configured active PRN surfaces without depending on #169 implementation."""
    manifest = load_manifest(root)
    configured = get(manifest, "sources.principles")
    if configured is None:
        return []
    directory = resolve_repo_path(root, configured, label="manifest sources.principles")
    if not directory.is_dir():
        raise ContextContractError(f"configured principles directory missing: {_rel(root, directory)}")
    result: list[dict[str, Any]] = []
    for path in sorted(directory.glob("PRN-*.md")):
        if path.name == "TEMPLATE.md":
            continue
        doc = parse_document(path)
        meta = doc["frontmatter"]
        if meta.get("status") != "active":
            continue
        result.append({
            "artifact": str(meta.get("id") or path.stem),
            "path": _rel(root, path),
            "sections": ["Rule", "Applies to", "Exceptions / approved deviation"],
        })
    return result


def build_context_contract(root: Path, step_id: str, role: str) -> dict[str, Any]:
    if role not in ROLES:
        raise ContextContractError(f"role must be one of {sorted(ROLES)}")
    root = root.resolve()
    sections = ROLE_SECTIONS[role]
    task = read_task(root, step_id)
    required: list[dict[str, Any]] = [
        _projection(root, task_path(root, step_id), step_id, sections["step"])
    ]

    for req_id in requirement_ids(task):
        required.append(
            _projection(root, canonical_requirement_path(root, req_id), req_id, sections["requirement"])
        )
    for adr_id in adr_ids(task):
        required.append(
            _projection(root, canonical_adr_path(root, adr_id), adr_id, sections["adr"])
        )
    for dependency_id in dependency_ids(task):
        required.append(
            _projection(root, task_path(root, dependency_id), dependency_id, sections["dependency"])
        )
    for item in relevant_open_questions(root, task):
        required.append(
            _projection(root, item["path"], str(item["id"]), sections["oq"])
        )
    required.extend(_architecture_projection(root, ref) for ref in architecture_refs(task))

    if role in {"planner", "reviewer"}:
        required.extend(_optional_principles(root))

    # Deduplicate exact projection identity while preserving deterministic order.
    seen: set[tuple[str, str, tuple[str, ...], str | None]] = set()
    unique: list[dict[str, Any]] = []
    for item in required:
        key = (
            str(item["artifact"]),
            str(item["path"]),
            tuple(item.get("sections") or []),
            item.get("anchor"),
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)

    forbidden = [
        ".harness/tools/**",
        "planning/** unrelated to current STEP",
        "docs/** unrelated to explicit canonical links",
        ".agents/skills/** except selected command skill",
    ]
    optional = [
        {
            "trigger": "material integration/security/domain boundary discovered",
            "action": "request explicit expansion with repository-relative path and reason",
        },
        {
            "trigger": "verification/review evidence references an additional file",
            "action": "request explicit expansion with repository-relative path and reason",
        },
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "role": role,
        "stepId": step_id,
        "required": unique,
        "optionalExpansions": optional,
        "forbiddenOrUnnecessary": forbidden,
        "metrics": {
            "artifactCount": len(unique),
            "sectionCount": sum(len(item.get("sections") or []) for item in unique),
            "fullRepositoryPreload": False,
        },
    }


def validate_expansion(root: Path, path: str, reason: str) -> dict[str, Any]:
    if not isinstance(reason, str) or not reason.strip():
        raise ContextContractError("context expansion requires a non-empty reason")
    candidate = resolve_repo_path(root, path, label="context expansion")
    rel = _rel(root, candidate)
    if rel == ".harness/tools" or rel.startswith(".harness/tools/"):
        raise ContextContractError("tool source is forbidden in normal semantic context")
    if not candidate.is_file():
        raise ContextContractError(f"expanded context file not found: {rel}")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "PASS",
        "path": rel,
        "reason": reason.strip(),
    }
