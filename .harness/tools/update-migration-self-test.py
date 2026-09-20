#!/usr/bin/env python3
"""Dependency-free regression smoke-test безопасного Harness update/migration.

Это не исполняет agent-driven updater. Вместо этого тест закрепляет deterministic
границы, на которых реальный dogfood v0.4.0 -> v0.5.x находил дефекты:
routing/reload, bootstrap relocation layout, ownership project templates,
ignored runtime artifacts, deferred REQ migration и marker/shared contracts.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib

import validate as harness_validate


def run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        list(args),
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    return proc


def repo_root() -> Path:
    here = Path(__file__).resolve()
    proc = run(here.parent, "git", "rev-parse", "--show-toplevel")
    return Path(proc.stdout.strip())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def test_routing(root: Path) -> None:
    canonical = load_json(root / ".harness/harness-update-graph.json")
    legacy = load_json(root / ".project/harness-update-graph.json")
    require(canonical == legacy, "legacy routing endpoint drifted from canonical graph")

    route, edges = route_to_latest(canonical, "v0.4.0")
    require(route[:3] == ["v0.4.0", "v0.4.1", "v0.4.2"], f"legacy bridge prefix changed: {route}")
    bridge = next((edge for edge in edges if edge["from"] == "v0.4.1"), None)
    require(bridge is not None and bridge["to"] == "v0.4.2", "missing v0.4.1 -> v0.4.2 bridge")
    require(bridge["kind"] == "bridge" and bridge["reloadRequired"] is True, "v0.4.2 bridge must require reload")

    relocation = next((edge for edge in edges if edge["from"] == "v0.4.2"), None)
    require(relocation is not None, "legacy route must continue from v0.4.2 to current latest")
    require(relocation["reloadRequired"] is True, "bootstrap relocation from v0.4.2 must require reload")


def test_relocation_layout(root: Path) -> None:
    expected = {
        ".harness/harness-update.toml",
        ".harness/harness-policy.toml",
        ".harness/harness.lock.json",
        ".harness/manifest.yaml",
        ".harness/git-policy.toml",
        ".harness/command-transitions.json",
        ".harness/docs/EXECUTION_PROTOCOL.md",
        ".harness/docs/UPDATES.md",
        ".harness/tools/validate.py",
    }
    retired = {
        ".project/harness-update.toml",
        ".project/harness-policy.toml",
        ".project/harness.lock.json",
        ".project/manifest.yaml",
        ".project/git-policy.toml",
        ".project/command-transitions.json",
        ".project/README.md",
        "planning/EXECUTION_PROTOCOL.md",
    }
    for rel in expected:
        require((root / rel).is_file(), f"relocation target missing: {rel}")
    for rel in retired:
        require(not (root / rel).exists(), f"retired control-plane path returned: {rel}")
    require(not (root / "docs/harness").exists(), "legacy docs/harness directory returned")
    require(not (root / "tools/harness").exists(), "legacy tools/harness directory returned")


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
        "planning/tasks/TEMPLATE.md",
        "planning/reviews/TEMPLATE.md",
        "planning/audits/TEMPLATE.md",
        "planning/releases/TEMPLATE.md",
        "planning/skill-searches/TEMPLATE.md",
    ]
    for path in project_templates:
        require(not matches_any(path, managed), f"project template became updater-managed again: {path}")

    require(matches_any(".harness/manifest.yaml", ownership.get("shared", [])), "manifest must remain shared")
    require(matches_any(".harness/git-policy.toml", ownership.get("shared", [])), "git policy must remain shared")

    markers = policy.get("markers", {})
    require(
        set(markers.get("AGENTS.md", {}).get("blocks", [])) >= {"PROJECT-CONTEXT", "SKILL-ROUTING"},
        "AGENTS project marker preservation contract drifted",
    )
    require(
        "PROJECT" in markers.get("README.md", {}).get("blocks", []),
        "README project marker preservation contract drifted",
    )


def test_ignored_runtime_artifacts() -> None:
    with tempfile.TemporaryDirectory(prefix="harness-update-scope-") as tmp:
        root = Path(tmp)
        run(root, "git", "init", "-q")
        run(root, "git", "config", "user.email", "harness-test@example.invalid")
        run(root, "git", "config", "user.name", "Harness Test")

        (root / ".gitignore").write_text("__pycache__/\n*.py[cod]\n", encoding="utf-8")
        managed = root / "tools/harness"
        managed.mkdir(parents=True)
        (managed / "validate.py").write_text("print('tracked')\n", encoding="utf-8")
        run(root, "git", "add", ".gitignore", "tools/harness/validate.py")
        run(root, "git", "commit", "-qm", "fixture")

        cache = managed / "__pycache__/validate.cpython-313.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"\x00\x01\x02binary")
        collision = managed / "custom-local.txt"
        collision.write_text("local\n", encoding="utf-8")

        require(run(root, "git", "check-ignore", "-q", str(cache), check=False).returncode == 0,
                "Python cache fixture must be ignored")
        require(run(root, "git", "ls-files", "--error-unmatch", str(cache), check=False).returncode != 0,
                "ignored Python cache must stay untracked")
        require(run(root, "git", "check-ignore", "-q", str(collision), check=False).returncode != 0,
                "non-ignored local collision fixture unexpectedly ignored")
        require(run(root, "git", "ls-files", "--error-unmatch", str(collision), check=False).returncode != 0,
                "collision fixture must remain untracked")


def test_deferred_requirements_migration() -> None:
    with tempfile.TemporaryDirectory(prefix="harness-legacy-req-") as tmp:
        root = Path(tmp)
        req = root / "docs/requirements"
        req.mkdir(parents=True)
        (req / "SPEC.md").write_text(
            "# Requirements Specification\n\n"
            "### REQ-001 — Legacy requirement\n\n"
            "#### Requirement\n\nLegacy contract.\n",
            encoding="utf-8",
        )
        (req / "STATUS.md").write_text("# Requirements Status\n", encoding="utf-8")

        require(
            harness_validate.legacy_requirements_migration_pending(root),
            "exact legacy REQ layout must be recognized as migration-pending",
        )

        (req / "REQ-001-legacy-requirement.md").write_text(
            "# REQ-001 — Legacy requirement\n",
            encoding="utf-8",
        )
        require(
            not harness_validate.legacy_requirements_migration_pending(root),
            "partial migration must not receive legacy manual bypass",
        )


def test_manifest_requirements_path() -> None:
    with tempfile.TemporaryDirectory(prefix="harness-custom-req-path-") as tmp:
        root = Path(tmp)
        harness = root / ".harness"
        harness.mkdir(parents=True)
        (harness / "manifest.yaml").write_text(
            """sources:
  requirements: spec/requirements
""",
            encoding="utf-8",
        )
        req = root / "spec/requirements"
        req.mkdir(parents=True)
        (req / "SPEC.md").write_text(
            "# Requirements Specification\n\n"
            "### REQ-001 — Legacy requirement\n\n"
            "#### Requirement\n\nLegacy contract.\n",
            encoding="utf-8",
        )
        (req / "STATUS.md").write_text("# Requirements Status\n", encoding="utf-8")

        require(
            harness_validate.legacy_requirements_migration_pending(root),
            "legacy detector must honor manifest sources.requirements",
        )


def test_release_metadata(root: Path) -> None:
    graph = load_json(root / ".harness/harness-update-graph.json")
    lock = load_json(root / ".harness/harness.lock.json")
    manifest = (root / ".harness/manifest.yaml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^  release:\s*"([^"]+)"', manifest)
    require(match is not None, "manifest harness.release missing")
    release = match.group(1)
    require(graph["latest"] == f"v{release}", "graph.latest must match manifest release")
    require(lock["release"] == release, "lock release must match manifest release")
    require(lock["source"]["ref"] == f"v{release}", "lock source.ref must match manifest release")


def main() -> int:
    root = repo_root()
    tests = [
        ("routing/reload", lambda: test_routing(root)),
        ("relocation layout", lambda: test_relocation_layout(root)),
        ("ownership/templates/markers", lambda: test_ownership_contract(root)),
        ("ignored runtime artifacts", test_ignored_runtime_artifacts),
        ("deferred requirements migration", test_deferred_requirements_migration),
        ("manifest requirements path", test_manifest_requirements_path),
        ("release metadata", lambda: test_release_metadata(root)),
    ]
    for name, test in tests:
        test()
        print(f"PASS: {name}")
    print(f"HARNESS UPDATE MIGRATION SELF-TEST: PASS ({len(tests)} contracts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
