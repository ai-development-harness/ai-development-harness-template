#!/usr/bin/env python3
"""Conservative, project-declared per-check inputs for incremental Verification.

This module does not infer dependencies from filenames. A baseline must come
from a successful *full* run, and the map must account for every command and
Acceptance criterion. Unknown input changes always require the full run.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from typing import Any

SCHEMA_VERSION = 1
MAX_CHECKS = 128
MAX_FILES = 20000
FULL_ONLY_FLAGS = frozenset({
    "security-sensitive", "data-migration", "external-integration",
    "destructive", "release-critical",
})
INFRA_NAMES = frozenset({
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "poetry.lock", "uv.lock", "Pipfile.lock", "Cargo.lock", "go.sum",
    "pytest.ini", "pyproject.toml", "package.json", "nx.json",
})
INFRA_PREFIXES = (".github/", ".harness/tools/", ".harness/manifest.yaml")


class ImpactError(ValueError):
    """Unprovable selection. Caller must run full Verification."""


def digest(data: Any) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _git(root: Path, *argv: str) -> bytes:
    proc = subprocess.run(["git", *argv], cwd=root, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=False)
    if proc.returncode:
        raise ImpactError("git input scan failed: " + proc.stderr.decode("utf-8", "replace")[:180])
    return proc.stdout


def _safe_path(value: str) -> str:
    if (not isinstance(value, str) or not value or value.startswith("/")
            or "\\" in value or "\0" in value or ".." in PurePosixPath(value).parts
            or value.startswith("./") or value.endswith("/")):
        raise ImpactError("invalid repository input path")
    if value == "." or value.startswith(".harness/local/"):
        raise ImpactError("unsafe repository input path")
    return value


def _matches(path: str, pattern: str) -> bool:
    return (path == pattern[:-3] or path.startswith(pattern[:-3] + "/")) if pattern.endswith("/**") else path == pattern


def _patterns(values: Any) -> list[str]:
    if not isinstance(values, list) or not values:
        raise ImpactError("inputs must be a non-empty path array")
    if len(values) > MAX_CHECKS or any(not isinstance(v, str) for v in values):
        raise ImpactError("invalid input path array")
    result = [_safe_path(v[:-3]) + "/**" if v.endswith("/**") else _safe_path(v) for v in values]
    if len(set(result)) != len(result):
        raise ImpactError("duplicate input path")
    return result


def validate_map(mapping: Any, *, commands: list[str], acceptance: list[str]) -> dict[str, Any]:
    """Require complete project-declared mapping, never infer test coverage."""
    if not isinstance(mapping, dict) or set(mapping) != {"schemaVersion", "checks", "globalInputs", "environment"}:
        raise ImpactError("invalid impact map shape")
    if type(mapping["schemaVersion"]) is not int or mapping["schemaVersion"] != SCHEMA_VERSION:
        raise ImpactError("unsupported impact map version")
    checks = mapping["checks"]
    if not isinstance(checks, list) or not 1 <= len(checks) <= MAX_CHECKS:
        raise ImpactError("impact map requires bounded checks")
    expected = set(commands)
    actual: set[str] = set()
    ids: set[str] = set()
    covered: set[str] = set()
    if len(expected) != len(commands):
        raise ImpactError("ambiguous duplicate Verification commands")
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"id", "parent", "command", "inputs", "obligations", "reusable"}:
            raise ImpactError("invalid check shape")
        ident, parent, command = (check[k] for k in ("id", "parent", "command"))
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", ident) or ident in ids:
            raise ImpactError("duplicate/invalid check ID")
        ids.add(ident)
        if parent not in expected or not isinstance(command, str) or not command.strip():
            raise ImpactError("check command is not tied to a canonical parent")
        if type(check["reusable"]) is not bool:
            raise ImpactError("reusable must be a boolean")
        _patterns(check["inputs"])
        obligations = check["obligations"]
        if not isinstance(obligations, list) or not obligations or len(set(obligations)) != len(obligations):
            raise ImpactError("each check requires exact Acceptance obligations")
        if any(not isinstance(o, str) or o not in acceptance for o in obligations):
            raise ImpactError("check covers unknown Acceptance obligation")
        covered.update(obligations)
        actual.add(parent)
    if actual != expected or covered != set(acceptance):
        raise ImpactError("map does not cover all commands and Acceptance obligations")
    globals_ = mapping["globalInputs"]
    if not isinstance(globals_, list) or any(not isinstance(i, str) for i in globals_):
        raise ImpactError("invalid global inputs")
    for item in globals_:
        _safe_path(item[:-3] if item.endswith("/**") else item)
    env = mapping["environment"]
    if not isinstance(env, list) or len(env) > 64 or len(set(env)) != len(env) or any(
        not isinstance(k, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) for k in env
    ):
        raise ImpactError("invalid environment inputs")
    return mapping


def read_map(path: Path, *, commands: list[str], acceptance: list[str]) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ImpactError("impact map missing or symlinked")
    try:
        return validate_map(json.loads(path.read_text(encoding="utf-8")), commands=commands, acceptance=acceptance)
    except (OSError, ValueError, UnicodeError) as exc:
        raise ImpactError("invalid impact map: " + str(exc)) from exc


def _files(root: Path, *, exclude: set[str]) -> dict[str, str]:
    """Record exact tracked + nonignored untracked worktree bytes/mode.

    Index membership is used only to enumerate paths. A staged change and an
    unstaged change of the same file are both represented by real worktree data.
    """
    if _git(root, "ls-files", "--unmerged", "-z"):
        raise ImpactError("unmerged Git index")
    tracked = _git(root, "ls-files", "--cached", "-z")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    names = {v.decode("utf-8", "surrogateescape") for v in (tracked + untracked).split(b"\0") if v}
    if len(names) > MAX_FILES:
        raise ImpactError("input snapshot exceeds maximum files")
    result: dict[str, str] = {}
    base = root.resolve()
    for name in sorted(names):
        if name in exclude or name.startswith(".harness/local/"):
            continue
        if _safe_path(name) != name:
            raise ImpactError("unsafe Git path")
        path = base / name
        try:
            path.parent.resolve().relative_to(base)
        except ValueError as exc:
            raise ImpactError("path outside repository") from exc
        if path.is_symlink():
            data = os.readlink(path).encode("utf-8", "surrogateescape")
            mode = "link"
        elif path.is_file():
            if not path.resolve().is_relative_to(base):
                raise ImpactError("file escapes repository")
            data = path.read_bytes()
            mode = "executable" if path.stat().st_mode & 0o111 else "file"
        elif not path.exists():
            continue
        else:
            raise ImpactError("unsupported Git item in input snapshot")
        result[name] = digest([mode, hashlib.sha256(data).hexdigest()])
    return result


def environment_basis(mapping: dict[str, Any]) -> str:
    """Conservative global toolchain fingerprint, including all executables."""
    names = {str(check["command"]).split()[0] for check in mapping["checks"]}
    names.update(str(check["parent"]).split()[0] for check in mapping["checks"])
    tools: dict[str, Any] = {}
    for name in sorted(names):
        resolved = shutil.which(name)
        if not resolved:
            raise ImpactError("Verification executable not found: " + name)
        st = Path(resolved).stat()
        tools[name] = [resolved, st.st_size, st.st_mtime_ns]
    return digest({"python": sys.version, "platform": sys.platform, "path": os.environ.get("PATH"),
                   "environment": {name: os.environ.get(name) for name in mapping["environment"]},
                   "tools": tools})


def full_baseline(root: Path, *, mapping: dict[str, Any], contract: str, context: str,
                  subject: str, exclude: set[str]) -> dict[str, Any]:
    """Called only after canonical complete Verification PASS is published."""
    return {"schemaVersion": SCHEMA_VERSION, "producer": "deterministic-full-verification",
            "mapHash": digest(mapping), "contractBasis": contract, "contextBasis": context,
            "subjectContentHash": subject, "environmentBasis": environment_basis(mapping),
            "files": _files(root, exclude=exclude)}


def select(root: Path, *, mapping: dict[str, Any], baseline: dict[str, Any],
           contract: str, context: str, exclude: set[str]) -> dict[str, Any]:
    """Return executable checks/reused checks, else require full Verification.

    Compare every change to the *original full baseline*, never to the last
    selective execution. Stale semantic inputs, unknown paths and infra changes
    cannot be laundered into an unrelated reused PASS.
    """
    if not isinstance(baseline, dict) or baseline.get("schemaVersion") != 1 or baseline.get("producer") != "deterministic-full-verification":
        raise ImpactError("full baseline missing or invalid")
    if baseline.get("mapHash") != digest(mapping) or baseline.get("contractBasis") != contract or baseline.get("contextBasis") != context:
        raise ImpactError("map or semantic Verification contract changed")
    if baseline.get("environmentBasis") != environment_basis(mapping):
        raise ImpactError("toolchain/environment changed")
    before = baseline.get("files")
    if not isinstance(before, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in before.items()):
        raise ImpactError("baseline has no complete file snapshot")
    now = _files(root, exclude=exclude)
    changed = {path for path in set(before) | set(now) if before.get(path) != now.get(path)}
    groups = mapping["checks"]
    for path in changed:
        if (path in INFRA_NAMES or any(path.startswith(prefix) for prefix in INFRA_PREFIXES)
                or any(_matches(path, pattern) for pattern in mapping["globalInputs"])):
            raise ImpactError("shared infrastructure changed: " + path)
        if not any(any(_matches(path, i) for i in group["inputs"]) for group in groups):
            raise ImpactError("unknown impact of changed file: " + path)
    executed = []
    reused = []
    for group in groups:
        affected = not group["reusable"] or any(
            any(_matches(path, i) for i in group["inputs"]) for path in changed
        )
        (executed if affected else reused).append(group["id"])
    return {"mode": "incremental", "baseline": baseline["subjectContentHash"],
            "changedPaths": sorted(changed), "executed": executed, "reused": reused,
            "currentFiles": now}


__all__ = ["ImpactError", "digest", "validate_map", "read_map", "full_baseline", "select"]
