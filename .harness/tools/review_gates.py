#!/usr/bin/env python3
"""Deterministic preselector минимально обязательных specialized reviewers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from document_contract import stable_hash
from harness_config import review_policy
from planning_contract import read_task


SECURITY_FLAGS = {
    "security-sensitive",
    "data-migration",
    "destructive",
    "public-api",
    "external-integration",
}
TEST_TYPES = {"implementation", "bugfix", "refactor", "hardening"}
SECURITY_PATH_RE = re.compile(
    r"(?i)(auth|security|crypto|permission|session|token|secret|migration|iam|oauth)"
)
TEST_SURFACE_RE = re.compile(
    r"(?i)(\.(py|ts|tsx|js|jsx|go|rs|java|kt|cs|rb|php)$|(^|/)(src|lib|app|tests?|spec)(/|$))"
)


def _git_changed_paths(root: Path) -> list[str]:
    paths: set[str] = set()
    for args in (
        ("diff", "--name-only", "HEAD"),
        ("diff", "--cached", "--name-only"),
    ):
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            continue
        if proc.returncode == 0:
            paths.update(line.strip() for line in proc.stdout.splitlines() if line.strip())
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if proc.returncode == 0:
            paths.update(line.strip() for line in proc.stdout.splitlines() if line.strip())
    except OSError:
        pass
    return sorted(paths)


def required_reviewers(root: Path, step_id: str) -> dict[str, Any]:
    task = read_task(root, step_id)
    meta = task["frontmatter"]
    flags = set(meta.get("risk_flags", [])) if isinstance(meta.get("risk_flags"), list) else set()
    step_type = meta.get("type")
    paths = _git_changed_paths(root)

    required: set[str] = set()
    reasons: dict[str, list[str]] = {"security": [], "tests": []}
    security_policy = review_policy(root, "security")
    tests_policy = review_policy(root, "tests")

    if security_policy == "always":
        required.add("security")
        reasons["security"].append("manifest review.security=always")
    else:
        matched_flags = sorted(flags.intersection(SECURITY_FLAGS))
        if matched_flags:
            required.add("security")
            reasons["security"].append("risk_flags=" + ",".join(matched_flags))
        sensitive_paths = [path for path in paths if SECURITY_PATH_RE.search(path)]
        if sensitive_paths:
            required.add("security")
            reasons["security"].append("security-relevant changed paths")

    if tests_policy == "always":
        required.add("tests")
        reasons["tests"].append("manifest review.tests=always")
    else:
        if step_type in TEST_TYPES:
            required.add("tests")
            reasons["tests"].append(f"step type={step_type}")
        if any(TEST_SURFACE_RE.search(path) for path in paths):
            required.add("tests")
            reasons["tests"].append("code/test surface changed")

    basis_payload = {
        "schema": 1,
        "stepId": step_id,
        "stepType": step_type,
        "riskFlags": sorted(flags),
        "securityPolicy": security_policy,
        "testsPolicy": tests_policy,
        "changedPaths": paths,
    }
    return {
        "stepId": step_id,
        "required": sorted(required),
        "reasons": reasons,
        "changedPaths": paths,
        "basis": stable_hash(basis_payload),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("step_id")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = required_reviewers(root, args.step_id)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(", ".join(result["required"]) or "none")
        for kind in ("security", "tests"):
            if result["reasons"][kind]:
                print(f"{kind}: " + "; ".join(result["reasons"][kind]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
