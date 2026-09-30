#!/usr/bin/env python3
"""Детерминированная проекция состояния Harness-проекта для UI/Navigator.

Модуль собирает canonical артефакты и связи в стабильный JSON graph. Он не
вызывает LLM, не мутирует repository и не выбирает визуальный layout: эти
обязанности намеренно остаются на стороне клиента.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

from document_contract import DocumentError, parse_document
from harness_config import (
    adr_directory,
    load_manifest,
    open_questions_directory,
    requirements_directory,
    review_directory,
    task_directory,
)
from planning_contract import step_completion_proof
from review_contract import review_reports, validate_review_report


class ProjectStateError(RuntimeError):
    """Canonical project state нельзя безопасно превратить в graph snapshot."""


CORE_TYPES = {"REQ", "ADR", "STEP", "OQ"}


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _title(document: dict[str, Any]) -> str:
    h1 = str(document.get("h1") or "").strip()
    if " — " in h1:
        return h1.split(" — ", 1)[1].strip()
    return h1.lstrip("# ").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _canonical_docs(
    root: Path,
    directory: Path,
    pattern: str,
    *,
    id_prefix: str,
    exact_stem: bool = False,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob(pattern)):
        if path.name == "TEMPLATE.md" or path.is_symlink():
            continue
        try:
            document = parse_document(path)
        except DocumentError as exc:
            raise ProjectStateError(
                f"cannot parse canonical artifact {_rel(root, path)}: {exc}"
            ) from exc
        meta = document["frontmatter"]
        artifact_id = meta.get("id")
        if not isinstance(artifact_id, str) or not artifact_id.startswith(id_prefix + "-"):
            raise ProjectStateError(
                f"invalid {id_prefix} identity in {_rel(root, path)}"
            )
        if exact_stem:
            identity_ok = path.stem == artifact_id
        else:
            identity_ok = path.stem == artifact_id or path.name.startswith(artifact_id + "-")
        if not identity_ok:
            raise ProjectStateError(
                f"artifact id {artifact_id} does not match path {_rel(root, path)}"
            )
        result.append({"path": path, "document": document})
    return result


def _requirement_status(root: Path, meta: dict[str, Any], steps_by_id: dict[str, dict[str, Any]]) -> str:
    step_ids = _string_list(meta.get("steps"))
    if not step_ids:
        return "planned"

    completed = 0
    deferred = 0
    cancelled = 0
    existing = 0
    for step_id in step_ids:
        step = steps_by_id.get(step_id)
        if step is None:
            continue
        existing += 1
        status = step["document"]["frontmatter"].get("status")
        if status == "deferred":
            deferred += 1
        elif status == "cancelled":
            cancelled += 1
        try:
            proof = step_completion_proof(root, step_id)
        except Exception:
            proof = {"complete": False}
        if proof.get("complete"):
            completed += 1

    if existing == 0:
        return "planned"
    if completed == existing:
        return "completed"
    if completed:
        return "partial"
    if deferred == existing:
        return "deferred"
    if cancelled == existing:
        return "cancelled"
    return "planned"


def _skill_nodes(root: Path) -> list[dict[str, Any]]:
    skills_root = root / ".agents" / "skills"
    if not skills_root.is_dir():
        return []
    nodes: list[dict[str, Any]] = []
    for directory in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_file = directory / "SKILL.md"
        if not skill_file.is_file() or skill_file.is_symlink():
            continue
        slug = directory.name
        nodes.append(
            {
                "id": f"SKILL:{slug}",
                "artifactId": slug,
                "type": "SKILL",
                "title": slug,
                "status": "available",
                "path": _rel(root, skill_file),
                "metadata": {},
            }
        )
    return nodes


def _dependency_analysis(step_nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dependents: dict[str, set[str]] = defaultdict(set)
    dependencies: dict[str, list[str]] = {}
    for step_id, item in step_nodes.items():
        values = [
            value
            for value in _string_list(item["document"]["frontmatter"].get("depends_on"))
            if value in step_nodes
        ]
        dependencies[step_id] = values
        for dependency in values:
            dependents[dependency].add(step_id)

    cycles: list[list[str]] = []
    color: dict[str, int] = {step_id: 0 for step_id in step_nodes}
    stack: list[str] = []

    def visit(node: str) -> None:
        color[node] = 1
        stack.append(node)
        for dep in dependencies.get(node, []):
            if color[dep] == 0:
                visit(dep)
            elif color[dep] == 1:
                try:
                    start = stack.index(dep)
                except ValueError:
                    continue
                cycle = stack[start:] + [dep]
                if cycle not in cycles:
                    cycles.append(cycle)
        stack.pop()
        color[node] = 2

    for step_id in sorted(step_nodes):
        if color[step_id] == 0:
            visit(step_id)

    longest: list[str] = []
    if not cycles:
        memo: dict[str, list[str]] = {}

        def downstream_chain(node: str) -> list[str]:
            if node in memo:
                return memo[node]
            best: list[str] = []
            for child in sorted(dependents.get(node, set())):
                candidate = downstream_chain(child)
                if len(candidate) > len(best):
                    best = candidate
            memo[node] = [node, *best]
            return memo[node]

        for step_id in sorted(step_nodes):
            candidate = downstream_chain(step_id)
            if len(candidate) > len(longest):
                longest = candidate

    impact: dict[str, list[str]] = {}
    for step_id in sorted(step_nodes):
        seen: set[str] = set()
        pending = list(dependents.get(step_id, set()))
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(dependents.get(current, set()))
        impact[step_id] = sorted(seen)

    return {
        "longestChain": longest,
        "cycles": cycles,
        "downstreamImpact": impact,
    }


def build_project_state(root: Path) -> dict[str, Any]:
    root = root.resolve()
    try:
        manifest = load_manifest(root)
    except Exception as exc:
        raise ProjectStateError(f"cannot load .harness/manifest.yaml: {exc}") from exc

    requirements = _canonical_docs(
        root,
        requirements_directory(root),
        "REQ-*.md",
        id_prefix="REQ",
    )
    adrs = _canonical_docs(root, adr_directory(root), "ADR-*.md", id_prefix="ADR")
    steps = _canonical_docs(
        root,
        task_directory(root),
        "STEP-*.md",
        id_prefix="STEP",
        exact_stem=True,
    )
    oqs = _canonical_docs(
        root,
        open_questions_directory(root),
        "OQ-*.md",
        id_prefix="OQ",
    )

    steps_by_id = {
        item["document"]["frontmatter"]["id"]: item
        for item in steps
    }

    nodes: dict[str, dict[str, Any]] = {}
    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    harness = manifest.get("harness") if isinstance(manifest.get("harness"), dict) else {}
    project_name = project.get("name") if isinstance(project.get("name"), str) else None
    nodes["PROJECT"] = {
        "id": "PROJECT",
        "artifactId": "PROJECT",
        "type": "PROJECT",
        "title": project_name or "Project",
        "status": "initialized" if project.get("initialized") is True else "not_initialized",
        "path": ".harness/manifest.yaml",
        "metadata": {"initializedAt": project.get("initializedAt")},
    }

    for item in requirements:
        doc = item["document"]
        meta = doc["frontmatter"]
        artifact_id = meta["id"]
        nodes[artifact_id] = {
            "id": artifact_id,
            "artifactId": artifact_id,
            "type": "REQ",
            "title": _title(doc),
            "status": _requirement_status(root, meta, steps_by_id),
            "path": _rel(root, item["path"]),
            "metadata": {
                "priority": meta.get("priority"),
                "source": meta.get("source"),
            },
        }

    for item in adrs:
        doc = item["document"]
        meta = doc["frontmatter"]
        artifact_id = meta["id"]
        nodes[artifact_id] = {
            "id": artifact_id,
            "artifactId": artifact_id,
            "type": "ADR",
            "title": _title(doc),
            "status": meta.get("status"),
            "path": _rel(root, item["path"]),
            "metadata": {"date": meta.get("date")},
        }

    for item in steps:
        doc = item["document"]
        meta = doc["frontmatter"]
        artifact_id = meta["id"]
        plan = meta.get("plan") if isinstance(meta.get("plan"), dict) else {}
        nodes[artifact_id] = {
            "id": artifact_id,
            "artifactId": artifact_id,
            "type": "STEP",
            "title": _title(doc),
            "status": meta.get("status"),
            "path": _rel(root, item["path"]),
            "metadata": {
                "stepType": meta.get("type"),
                "priority": meta.get("priority"),
                "phase": meta.get("phase"),
                "riskFlags": _string_list(meta.get("risk_flags")),
              for dependency in values:
            dependents[dependency].add(step_id)

    cycles: list[list[str]] = []
    color: dict[str, int] = {step_id: 0 for step_id in step_nodes}
    stack: list[str] = []

    def visit(node: str) -> None:
        color[node] = 1
        stack.append(node)
        for dep in dependencies.get(node, []):
            if color[dep] == 0:
                visit(dep)
            elif color[dep] == 1:
                try:
                    start = stack.index(dep)
                except ValueError:
                    continue
                cycle = stack[start:] + [dep]
                if cycle not in cycles:
                    cycles.append(cycle)
        stack.pop()
        color[node] = 2

    for step_id in sorted(step_nodes):
        if color[step_id] == 0:
            visit(step_id)

    longest: list[str] = []
    if not cycles:
        memo: dict[str, list[str]] = {}

        def downstream_chain(node: str) -> list[str]:
            if node in memo:
                return memo[node]
            best: list[str] = []
            for child in sorted(dependents.get(node, set())):
                candidate = downstream_chain(child)
                if len(candidate) > len(best):
                    best = candidate
            memo[node] = [node, *best]
            return memo[node]

        for step_id in sorted(step_nodes):
            candidate = downstream_chain(step_id)
            if len(candidate) > len(longest):
                longest = candidate

    impact: dict[str, list[str]] = {}
    for step_id in sorted(step_nodes):
        seen: set[str] = set()
        pending = list(dependents.get(step_id, set()))
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(dependents.get(current, set()))
        impact[step_id] = sorted(seen)

    return {
        "longestChain": longest,
        "cycles": cycles,
        "downstreamImpact": impact,
    }


def build_project_state(root: Path) -> dict[str, Any]:
    root = root.resolve()
    try:
        manifest = load_manifest(root)
    except Exception as exc:
        raise ProjectStateError(f"cannot load .harness/manifest.yaml: {exc}") from exc

    requirements = _canonical_docs(
        root,
        requirements_directory(root),
        "REQ-*.md",
        id_prefix="REQ",
    )
    adrs = _canonical_docs(root, adr_directory(root), "ADR-*.md", id_prefix="ADR")
    steps = _canonical_docs(
        root,
        task_directory(root),
        "STEP-*.md",
        id_prefix="STEP",
        exact_stem=True,
    )
    oqs = _canonical_docs(
        root,
        open_questions_directory(root),
        "OQ-*.md",
        id_prefix="OQ",
    )

    steps_by_id = {
        item["document"]["frontmatter"]["id"]: item
        for item in steps
    }

    nodes: dict[str, dict[str, Any]] = {}
    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    harness = manifest.get("harness") if isinstance(manifest.get("harness"), dict) else {}
    project_name = project.get("name") if isinstance(project.get("name"), str) else None
    nodes["PROJECT"] = {
        "id": "PROJECT",
        "artifactId": "PROJECT",
        "type": "PROJECT",
        "title": project_name or "Project",
        "status": "initialized" if project.get("initialized") is True else "not_initialized",
        "path": ".harness/manifest.yaml",
        "metadata": {"initializedAt": project.get("initializedAt")},
    }

    for item in requirements:
        doc = item["document"]
        meta = doc["frontmatter"]
        artifact_id = meta["id"]
        nodes[artifact_id] = {
            "id": artifact_id,
            "artifactId": artifact_id,
            "type": "REQ",
            "title": _title(doc),
            "status": _requirement_status(root, meta, steps_by_id),
            "path": _rel(root, item["path"]),
            "metadata": {
                "priority": meta.get("priority"),
                "source": meta.get("source"),
            },
        }

    for item in adrs:
        doc = item["document"]
        meta = doc["frontmatter"]
        artifact_id = meta["id"]
        nodes[artifact_id] = {
            "id": artifact_id,
            "artifactId": artifact_id,
            "type": "ADR",
            "title": _title(doc),
            "status": meta.get("status"),
            "path": _rel(root, item["path"]),
            "metadata": {"date": meta.get("date")},
        }

    for item in steps:
        doc = item["document"]
        meta = doc["frontmatter"]
        artifact_id = meta["id"]
        plan = meta.get("plan") if isinstance(meta.get("plan"), dict) else {}
        nodes[artifact_id] = {
            "id": artifact_id,
            "artifactId": artifact_id,
            "type": "STEP",
            "title": _title(doc),
            "status": meta.get("status"),
            "path": _rel(root, item["path"]),
            "metadata": {
                "stepType": meta.get("type"),
                "priority": meta.get("priority"),
                "phase": meta.get("phase"),
                "riskFlags": _string_list(meta.get("risk_flags")),
                "planStatus": plan.get("status"),
                "planRevision": plan.get("revision"),
            },
        }

    for item in oqs:
        doc = item["document"]
        meta = doc["frontmatter"]
        artifact_id = meta["id"]
        nodes[artifact_id] = {
            "id": artifact_id,
            "artifactId": artifact_id,
            "type": "OQ",
            "title": _title(doc),
            "status": meta.get("status"),
            "path": _rel(root, item["path"]),
            "metadata": {
                "createdAt": meta.get("created_at"),
                "resolvedAt": meta.get("resolved_at"),
            },
        }

    for node in _skill_nodes(root):
        nodes[node["id"]] = node

    diagnostics: list[dict[str, Any]] = []
    edge_map: dict[tuple[str, str, str], dict[str, Any]] = {}

    def ensure_target(target_id: str, *, source_id: str, relation: str) -> str:
        if target_id in nodes:
            return target_id
        missing_id = f"MISSING:{target_id}"
        if missing_id not in nodes:
            prefix = target_id.split("-", 1)[0] if "-" in target_id else "UNKNOWN"
            nodes[missing_id] = {
                "id": missing_id,
                "artifactId": target_id,
                "type": "MISSING",
                "title": target_id,
                "status": "missing",
                "path": None,
                "metadata": {"expectedType": prefix},
            }
        diagnostics.append(
            {
                "code": "MISSING_REFERENCE",
                "source": source_id,
                "target": target_id,
                "relation": relation,
            }
        )
        return missing_id

    def add_edge(source: str, target: str, relation: str, declared_by: str) -> None:
        actual_target = ensure_target(target, source_id=source, relation=relation)
        key = (source, actual_target, relation)
        edge = edge_map.get(key)
        if edge is None:
            edge = {
                "id": f"{relation}:{source}:{actual_target}",
                "source": source,
                "target": actual_target,
                "relation": relation,
                "declaredBy": [],
            }
            edge_map[key] = edge
        if declared_by not in edge["declaredBy"]:
            edge["declaredBy"].append(declared_by)
            edge["declaredBy"].sort()

    # REQ объявляют implementing STEP и связанные ADR; reciprocal declarations ниже схлопываются в один edge.
    for item in requirements:
        meta = item["document"]["frontmatter"]
        req_id = meta["id"]
        for step_id in _string_list(meta.get("steps")):
            add_edge(req_id, step_id, "implemented_by", req_id)
        for adr_id in _string_list(meta.get("adrs")):
            actual_adr = ensure_target(adr_id, source_id=req_id, relation="addresses")
            # Relation direction is normalized ADR -> REQ regardless of which side declares it.
            source = actual_adr
            key = (source, req_id, "addresses")
            edge = edge_map.get(key)
            if edge is None:
                edge = {
                    "id": f"addresses:{source}:{req_id}",
                    "source": source,
                    "target": req_id,
                    "relation": "addresses",
                    "declaredBy": [],
                }
                edge_map[key] = edge
            if req_id not in edge["declaredBy"]:
                edge["declaredBy"].append(req_id)
                edge["declaredBy"].sort()

    # Направление ADR-связей канонизировано: ADR → REQ и ADR → STEP.
    for item in adrs:
        meta = item["document"]["frontmatter"]
        adr_id = meta["id"]
        for req_id in _string_list(meta.get("requirements")):
            add_edge(adr_id, req_id, "addresses", adr_id)
        for step_id in _string_list(meta.get("steps")):
            add_edge(adr_id, step_id, "governs", adr_id)

    # STEP может повторно объявить REQ/ADR связь; edge identity остаётся единой, а provenance копится в declaredBy.
    for item in steps:
        meta = item["document"]["frontmatter"]
        step_id = meta["id"]
        for dependency in _string_list(meta.get("depends_on")):
            add_edge(step_id, dependency, "depends_on", step_id)
        for req_id in _string_list(meta.get("requirements")):
            actual_req = ensure_target(req_id, source_id=step_id, relation="implemented_by")
            source = actual_req
            key = (source, step_id, "implemented_by")
            edge = edge_map.get(key)
            if edge is None:
                edge = {
                    "id": f"implemented_by:{source}:{step_id}",
                    "source": source,
                    "target": step_id,
                    "relation": "implemented_by",
                    "declaredBy": [],
                }
                edge_map[key] = edge
            if step_id not in edge["declaredBy"]:
                edge["declaredBy"].append(step_id)
                edge["declaredBy"].sort()
        for adr_id in _string_list(meta.get("adrs")):
            actual_adr = ensure_target(adr_id, source_id=step_id, relation="governs")
            source = actual_adr
            key = (source, step_id, "governs")
            edge = edge_map.get(key)
            if edge is None:
                edge = {
                    "id": f"governs:{source}:{step_id}",
                    "source": source,
                    "target": step_id,
                    "relation": "governs",
                    "declaredBy": [],
                }
                edge_map[key] = edge
            if step_id not in edge["declaredBy"]:
                edge["declaredBy"].append(step_id)
                edge["declaredBy"].sort()

    for item in oqs:
        meta = item["document"]["frontmatter"]
        oq_id = meta["id"]
        for target in _string_list(meta.get("affects")):
            add_edge(oq_id, target, "affects", oq_id)

    # Immutable implementation REVIEW — historical artifacts; каждый REVIEW всегда связан со своим STEP.
    review_root = review_directory(root)
    invalid_review_count = 0
    if review_root.is_dir():
        for step_id in sorted(steps_by_id):
            directory = review_root / step_id
            if not directory.is_dir():
                continue
            valid_by_path = {item["path"]: item for item in review_reports(root, step_id)}
            for path in sorted(directory.glob("REVIEW-*.md")):
                if path.is_symlink():
                    continue
                errors = validate_review_report(root, path, expected_step_id=step_id)
                if errors:
                    invalid_review_count += 1
                    diagnostics.append(
                        {
                            "code": "INVALID_REVIEW",
                            "path": _rel(root, path),
                            "errors": errors,
                        }
                    )
                    continue
                report = valid_by_path.get(path)
                if report is None:
                    continue
                doc = report["document"]
                meta = doc["frontmatter"]
                review_id = f"REVIEW:{step_id}:{path.stem}"
                nodes[review_id] = {
                    "id": review_id,
                    "artifactId": path.stem,
                    "type": "REVIEW",
                    "title": f"Review {step_id}",
                    "status": str(meta.get("verdict") or "unknown"),
                    "path": _rel(root, path),
                    "metadata": {
                        "stepId": step_id,
                        "createdAt": meta.get("created_at"),
                        "verificationStatus": meta.get("verification_status"),
                    },
                }
                add_edge(review_id, step_id, "reviews", review_id)

    edges = sorted(edge_map.values(), key=lambda item: (item["relation"], item["source"], item["target"]))
    node_list = sorted(nodes.values(), key=lambda item: (item["type"], item["id"]))

    degree: Counter[str] = Counter()
    for edge in edges:
        if not edge["source"].startswith("MISSING:") and not edge["target"].startswith("MISSING:"):
            degree[edge["source"]] += 1
            degree[edge["target"]] += 1

    core_nodes = [node for node in node_list if node["type"] in CORE_TYPES]
    connected_core = [node for node in core_nodes if degree[node["id"]] > 0]
    relationship_coverage = (
        round(100.0 * len(connected_core) / len(core_nodes), 1)
        if core_nodes
        else 100.0
    )

    by_type = Counter(node["type"] for node in core_nodes)
    by_status = Counter(str(node["status"]) for node in core_nodes)
    review_count = sum(1 for node in node_list if node["type"] == "REVIEW")
    skill_count = sum(1 for node in node_list if node["type"] == "SKILL")

    dependency = _dependency_analysis(steps_by_id)
    blocked: list[dict[str, Any]] = []
    for step_id, item in sorted(steps_by_id.items()):
        if item["document"]["frontmatter"].get("status") == "blocked":
            downstream = dependency["downstreamImpact"].get(step_id, [])
            blocked.append(
                {
                    "nodeId": step_id,
                    "kind": "blocked_step",
                    "affects": downstream,
                    "impactCount": len(downstream),
                }
            )
    for item in oqs:
        meta = item["document"]["frontmatter"]
        if meta.get("status") == "open":
            blocked.append(
                {
                    "nodeId": meta["id"],
                    "kind": "open_question",
                    "affects": _string_list(meta.get("affects")),
                    "impactCount": len(_string_list(meta.get("affects"))),
                }
            )

    uncovered_requirements = sorted(
        node["id"]
        for node in core_nodes
        if node["type"] == "REQ"
        and not any(edge["source"] == node["id"] and edge["relation"] == "implemented_by" for edge in edges)
    )
    isolated = sorted(
        node["id"]
        for node in core_nodes
        if degree[node["id"]] == 0
    )
    missing_count = sum(1 for node in node_list if node["type"] == "MISSING")

    integrity = "degraded" if diagnostics or dependency["cycles"] else "ok"
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "integrity": integrity,
        "project": {
            "name": project_name,
            "initialized": project.get("initialized") is True,
            "initializedAt": project.get("initializedAt"),
            "harnessVersion": harness.get("version"),
            "harnessRelease": harness.get("release"),
        },
        "summary": {
            "artifacts": len(core_nodes),
            "reviews": review_count,
            "skills": skill_count,
            "relationships": len(edges),
            "byType": dict(sorted(by_type.items())),
            "byStatus": dict(sorted(by_status.items())),
            "blockers": len(blocked),
            "missingReferences": missing_count,
            "invalidReviews": invalid_review_count,
            "relationshipCoveragePercent": relationship_coverage,
        },
        "graph": {
            "rootNodeId": "PROJECT",
            "nodes": node_list,
            "edges": edges,
        },
        "insights": {
            "blockers": blocked,
            "uncoveredRequirements": uncovered_requirements,
            "isolatedArtifacts": isolated,
            "dependency": {
                "longestChain": dependency["longestChain"],
                "cycles": dependency["cycles"],
            },
        },
        "diagnostics": diagnostics,
        "sources": {
            "requirements": _rel(root, requirements_directory(root)),
            "adrs": _rel(root, adr_directory(root)),
            "steps": _rel(root, task_directory(root)),
            "openQuestions": _rel(root, open_questions_directory(root)),
            "reviews": _rel(root, review_directory(root)),
            "skills": ".agents/skills",
        },
    }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Построить deterministic machine-readable graph состояния Harness-проекта."
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    root = (args.root or repo_root()).resolve()

    try:
        result = build_project_state(root)
    except (OSError, UnicodeError, ValueError, ProjectStateError) as exc:
        blocked = {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "error": str(exc),
        }
        if args.as_json:
            print(json.dumps(blocked, ensure_ascii=False, separators=(",", ":")))
        else:
            print(f"PROJECT STATE: BLOCKED: {exc}")
        return 1

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        summary = result["summary"]
        print(f"PROJECT STATE: PASS ({result['integrity']})")
        print(f"artifacts: {summary['artifacts']}")
        print(f"relationships: {summary['relationships']}")
        print(f"blockers: {summary['blockers']}")
        print(f"relationshipCoveragePercent: {summary['relationshipCoveragePercent']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
