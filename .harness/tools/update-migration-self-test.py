#!/usr/bin/env python3
"""Regression self-test Harness update boundaries + project-owned schema migration."""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib

from document_contract import parse_document
from harness_config import (
    load_update_policy,
    update_lock_path,
    update_manifest_path,
    update_report_directory,
)
from planning_contract import step_completion_proof
from project_migration import legacy_schema_pending, migrate_project
from review_contract import legacy_review_pins, validate_all_review_reports


def run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode:
        raise AssertionError(f"{' '.join(args)} failed: {proc.stderr}")
    return proc


def repo_root() -> Path:
    here = Path(__file__).resolve()
    proc = run(here.parent, "git", "rev-parse", "--show-toplevel")
    return Path(proc.stdout.strip())


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def route_to_latest(graph: dict, start: str) -> tuple[list[str], list[dict]]:
    latest = graph["latest"]
    outgoing = {edge["from"]: edge for edge in graph["transitions"]}
    route = [start]
    edges: list[dict] = []
    current = start
    seen: set[str] = set()
    while current != latest:
        require(current not in seen, f"update graph cycle from {start}")
        seen.add(current)
        edge = outgoing.get(current)
        require(edge is not None, f"no update path from {current} to {latest}")
        edges.append(edge)
        current = edge["to"]
        route.append(current)
    return route, edges


def test_policy_driven_paths(root: Path) -> None:
    policy = load_update_policy(root)
    require(update_manifest_path(root) == root / policy["source"]["update_manifest"], "update_manifest config ignored")
    require(update_lock_path(root) == root / policy["state"]["lock_file"], "lock_file config ignored")
    require(update_report_directory(root) == root / policy["state"]["report_directory"], "report_directory config ignored")


def test_routing(root: Path) -> None:
    canonical = load_json(update_manifest_path(root))
    legacy = load_json(root / ".project/harness-update-graph.json")
    require(canonical == legacy, "legacy routing endpoint drifted from canonical graph")

    route, edges = route_to_latest(canonical, "v0.4.0")
    require(route[:3] == ["v0.4.0", "v0.4.1", "v0.4.2"], f"legacy bridge prefix changed: {route}")
    bridge = next(edge for edge in edges if edge["from"] == "v0.4.1")
    require(bridge["kind"] == "bridge" and bridge["reloadRequired"] is True, "v0.4.2 bridge contract changed")
    relocation = next(edge for edge in edges if edge["from"] == "v0.4.2")
    require(relocation["reloadRequired"] is True, "bootstrap relocation must require reload")


def test_ownership_contract(root: Path) -> None:
    with (root / ".harness/harness-update.toml").open("rb") as fh:
        policy = tomllib.load(fh)
    ownership = policy["ownership"]
    managed = (
        list(ownership.get("harness_owned", []))
        + list(ownership.get("shared", []))
        + list(ownership.get("marker_merge", []))
    )
    project_templates = [
        "docs/requirements/TEMPLATE.md",
        "docs/adr/TEMPLATE.md",
        "docs/open-questions/TEMPLATE.md",
        "planning/tasks/TEMPLATE.md",
        "planning/reviews/TEMPLATE.md",
        "planning/plan-reviews/TEMPLATE.md",
        "planning/init-reviews/TEMPLATE.md",
        "planning/audits/TEMPLATE.md",
        "planning/releases/TEMPLATE.md",
        "planning/skill-searches/TEMPLATE.md",
    ]
    for path in project_templates:
        require(not matches_any(path, managed), f"PROJECT RECONCILE-owned template became updater-managed: {path}")

    require(matches_any(".harness/manifest.yaml", ownership.get("shared", [])), "manifest must remain shared")
    require(matches_any(".harness/git-policy.toml", ownership.get("shared", [])), "git policy must remain shared")


def synthetic_manifest() -> str:
    return """harness:
  version: "1"
  release: "0.5.3"
project:
  initialized: true
  name: legacy-test
  initializedAt: "2026-09-20T00:00:00+00:00"
execution:
  maxFixReviewCycles: 2
review:
  security: auto
  tests: auto
skills:
  search:
    maxResults: 5
language:
  default: ru
sources:
  localBrief: PROJECT_BRIEF.local.md
  projectOverview: docs/PROJECT.md
  requirements: docs/requirements
  adrDirectory: docs/adr
  architecture: docs/architecture.md
  openQuestions: docs/open-questions
  openQuestionsIndex: docs/OPEN_QUESTIONS.md
  roadmap: planning/PLAN.md
  status: planning/STATUS.md
protocol:
  file: .harness/docs/EXECUTION_PROTOCOL.md
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
  planningReviewDirectory: planning/plan-reviews
  initReviewDirectory: planning/init-reviews
  auditDirectory: planning/audits
  releaseDirectory: planning/releases
  skillSearchDirectory: planning/skill-searches
  skillRegistry: docs/skills/REGISTRY.md
repository:
  gitPolicy: .harness/git-policy.toml
  harnessPolicy: .harness/harness-policy.toml
  harnessUpdatePolicy: .harness/harness-update.toml
  harnessValidation: .harness/tools/validate.py
  harnessCI: .github/workflows/harness-integrity.yml
"""


def legacy_step() -> str:
    return """# STEP-001 — Legacy step

**Статус:** Выполнено
**Type:** IMPLEMENTATION
**Приоритет:** Средний
**Фаза:** Core
**Depends on:** —

## Requirements

- REQ-001

## ADR

- ADR-001

## Risk flags

- none

## Goal

Legacy goal.

## Context

Legacy context.

## Scope

- legacy.

## Mutation policy

### Allowed

- fixture

### Conditional

- none

### Forbidden

- unrelated

## Out of scope

- unrelated

## Acceptance criteria

- works

## Verification

- test

## Deliverables

- artifact

## Implementation plan

**Plan status:** Ready
**Plan revision:** 2
**Plan basis:** sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
**Planned at:** 2026-09-20T00:00:00+00:00

1. Old plan.

## Evidence

Legacy verification evidence.

## Review status

**Latest verdict:** NOT REVIEWED
**Latest report:** —

## Blocker / Failure reason

—
"""


def legacy_review() -> str:
    return """# REVIEW STEP-001

**Reviewer role:** reviewer
**Verdict:** PASS
**Reviewed revision:** legacy-revision

## Scope checked

Legacy fixture.

## Findings

none

## Verification observations

Legacy verification passed.

## Specialized reviews

- Security: not required
- Tests: pass

## Verdict rationale

Acceptance was proven at the time of review.
"""


def legacy_adr() -> str:
    return """# ADR-001 — Legacy accepted decision

**Status:** Accepted
**Date:** 2026-09-20
**Deciders:** team
**Supersedes:** —
**Superseded by:** —

## Context

Legacy.

## Problem

Problem.

## Decision

Keep decision.

## Alternatives considered

Other.

## Consequences

Known.

## Security implications

None.

## Data / migration implications

None.

## Compatibility / operational implications

None.

## Traceability

- REQ: REQ-001
- STEP: STEP-001
"""


def test_project_owned_migration() -> None:
    with tempfile.TemporaryDirectory(prefix="harness-schema-migration-") as tmp:
        root = Path(tmp)
        (root / ".harness").mkdir(parents=True)
        (root / ".harness/manifest.yaml").write_text(synthetic_manifest(), encoding="utf-8")
        (root / "docs/PROJECT.md").parent.mkdir(parents=True)
        (root / "docs/PROJECT.md").write_text("# Project\n", encoding="utf-8")
        (root / "docs/architecture.md").write_text("# Architecture\n", encoding="utf-8")

        req = root / "docs/requirements"
        req.mkdir(parents=True)
        (req / "SPEC.md").write_text(
            "# Requirements Specification\n\n"
            "### REQ-001 — Legacy requirement\n\n"
            "#### Requirement\n\nLegacy contract.\n\n"
            "#### Rationale\n\nLegacy reason.\n\n"
            "#### Acceptance\n\n- Works.\n\n"
            "#### Traceability\n\nSTEP-001 ADR-001\n",
            encoding="utf-8",
        )
        (req / "STATUS.md").write_text("# Requirements Status\n", encoding="utf-8")

        (root / "planning/tasks").mkdir(parents=True)
        (root / "planning/tasks/STEP-001.md").write_text(legacy_step(), encoding="utf-8")
        legacy_review_path = root / "planning/reviews/STEP-001/REVIEW-20260920T000000Z.md"
        legacy_review_path.parent.mkdir(parents=True)
        legacy_review_path.write_text(legacy_review(), encoding="utf-8")
        legacy_review_before = legacy_review_path.read_text(encoding="utf-8")
        (root / "docs/adr").mkdir(parents=True)
        (root / "docs/adr/ADR-001-legacy.md").write_text(legacy_adr(), encoding="utf-8")
        (root / "docs/OPEN_QUESTIONS.md").write_text(
            "# Open Questions\n\n"
            "OQ-001 — Legacy question\n"
            "Status: RESOLVED\n"
            "Affects: REQ-001\n"
            "Context: legacy\n"
            "Decision needed: choose\n"
            "Resolution: chosen\n",
            encoding="utf-8",
        )

        require(legacy_schema_pending(root), "legacy schema not detected")
        first = migrate_project(root)
        require(first["status"] == "MIGRATED", first)
        require(not legacy_schema_pending(root), "migration left active legacy schema")

        step = parse_document(root / "planning/tasks/STEP-001.md")
        require(step["frontmatter"]["schema"] == 1, "STEP schema not migrated")
        require(step["frontmatter"]["plan"]["status"] == "draft", "legacy Ready must become draft")

        req_files = list((root / "docs/requirements").glob("REQ-001-*.md"))
        require(len(req_files) == 1, f"REQ split failed: {req_files}")
        requirement = parse_document(req_files[0])
        require(requirement["frontmatter"]["id"] == "REQ-001", "REQ id lost")

        decision = parse_document(root / "docs/adr/ADR-001-legacy.md")
        require(decision["frontmatter"]["status"] == "accepted", "Accepted ADR status lost")

        oq_files = list((root / "docs/open-questions").glob("OQ-001-*.md"))
        require(len(oq_files) == 1, "OQ split failed")
        require(parse_document(oq_files[0])["frontmatter"]["status"] == "resolved", "OQ status lost")

        # Legacy immutable review остаётся byte-for-byte прежним, но migration
        # report фиксирует его hash как durable compatibility proof.
        require(
            legacy_review_path.read_text(encoding="utf-8") == legacy_review_before,
            "legacy immutable review was rewritten",
        )
        pins = legacy_review_pins(root)
        legacy_rel = legacy_review_path.relative_to(root).as_posix()
        require(legacy_rel in pins, f"legacy review was not pinned: {pins}")
        require(not validate_all_review_reports(root), validate_all_review_reports(root))
        proof = step_completion_proof(root, "STEP-001")
        require(proof["complete"], f"legacy PASS review did not preserve completion proof: {proof}")

        # Legacy report identity is exact: STEP-001 must not trust STEP-0010.
        wrong_identity = legacy_review_before.replace("STEP-001", "STEP-0010")
        legacy_review_path.write_text(wrong_identity, encoding="utf-8")
        wrong = step_completion_proof(root, "STEP-001")
        require(not wrong["complete"], f"STEP-001 trusted STEP-0010 legacy review: {wrong}")
        legacy_review_path.write_text(legacy_review_before, encoding="utf-8")

        # RECONCILE owns template refresh, not updater.
        require((root / "planning/reviews/TEMPLATE.md").is_file(), "review template not refreshed")
        require((root / "planning/plan-reviews/TEMPLATE.md").is_file(), "planning-review template missing")

        # Second run is a true no-op: no extra migration report.
        reports_before = sorted((root / "planning/audits").glob("MIGRATION-*.md"))
        second = migrate_project(root)
        reports_after = sorted((root / "planning/audits").glob("MIGRATION-*.md"))
        require(second["status"] == "NO_CHANGES", second)
        require(reports_before == reports_after, "idempotent reconcile created an extra migration report")

        # После pinning historical report становится immutable contract:
        # mutation должна обнаруживаться, а RECONCILE не имеет права re-pin её.
        legacy_review_path.write_text(legacy_review_before + "\nTampered.\n", encoding="utf-8")
        review_errors = validate_all_review_reports(root)
        require(any("pinned legacy report changed" in item for item in review_errors), review_errors)
        try:
            migrate_project(root)
        except ValueError as exc:
            require("pinned legacy review changed" in str(exc), str(exc))
        else:
            raise AssertionError("tampered pinned legacy review was silently re-migrated")


def test_release_metadata(root: Path) -> None:
    graph = load_json(update_manifest_path(root))
    lock = load_json(update_lock_path(root))
    manifest = (root / ".harness/manifest.yaml").read_text(encoding="utf-8")
    import re
    match = re.search(r'(?m)^  release:\s*"([^"]+)"', manifest)
    require(match is not None, "manifest harness.release missing")
    release = match.group(1)
    require(graph["latest"] == f"v{release}", "graph.latest must match manifest release")
    require(lock["release"] == release, "lock release must match manifest release")
    require(lock["source"]["ref"] == f"v{release}", "lock source.ref must match manifest release")


def main() -> int:
    root = repo_root()
    tests = [
        ("policy-driven update paths", lambda: test_policy_driven_paths(root)),
        ("routing/reload", lambda: test_routing(root)),
        ("ownership boundary", lambda: test_ownership_contract(root)),
        ("project-owned schema migration", test_project_owned_migration),
        ("release metadata", lambda: test_release_metadata(root)),
    ]
    for name, test in tests:
        test()
        print(f"PASS: {name}")
    print(f"HARNESS UPDATE MIGRATION SELF-TEST: PASS ({len(tests)} contracts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
