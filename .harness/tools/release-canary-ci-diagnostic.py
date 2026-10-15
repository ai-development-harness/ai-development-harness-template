#!/usr/bin/env python3
"""Temporary CI reproduction of the v0.11.6 -> v0.12.0 initialized canary.

This script uses disposable checkouts only. The candidate is prepared from
this PR's current commit (including fixes), never from a moving remote SHA.
It is intentionally NOT named *-self-test.py to avoid recursive test runs.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[2]
CANARY_URL = "https://github.com/ai-development-harness/release-canary.git"
CANARY_SHA = "1d5b3027c5ac3a51ad3f6f75abfa70b3fd0d0e92"
PREVIOUS = "v0.11.6"
TARGET = "v0.12.0"


def run(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        args, cwd=cwd, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        timeout=300,
    )
    if result.returncode:
        raise RuntimeError(
            f"command {args[0]} failed: code={result.returncode}, "
            f"stderr_tail={result.stderr[-600:]!r}"
        )
    return result.stdout.strip()


def prepare(root: Path) -> str:
    # This test may run on a synthetic PR merge SHA; use only this checkout.
    run("git", "checkout", "-q", "-B", "main", cwd=root)
    run("git", "config", "user.email", "canary-diagnostic@example.invalid", cwd=root)
    run("git", "config", "user.name", "Harness Canary Diagnostic", cwd=root)

    manifest = root / ".harness/manifest.yaml"
    text = manifest.read_text(encoding="utf-8")
    text, count = re.subn(
        r'(?m)^(  release:)\s*"[^"]+"',
        r'\g<1> "0.12.0"',
        text, count=1,
    )
    if count != 1:
        raise RuntimeError("manifest release marker not found")
    manifest.write_text(text, encoding="utf-8")

    lock_path = root / ".harness/harness.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["release"] = "0.12.0"
    lock["source"]["ref"] = TARGET
    lock["source"].pop("commit", None)
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    graph_path = root / ".harness/harness-update-graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    if graph["latest"] != PREVIOUS:
        raise RuntimeError(f"unexpected prior release: {graph['latest']!r}")
    graph["transitions"].append({
        "from": PREVIOUS, "to": TARGET, "kind": "standard",
        "reloadRequired": True,
    })
    graph["latest"] = TARGET
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    run("git", "add", ".harness/manifest.yaml",
        ".harness/harness.lock.json", ".harness/harness-update-graph.json", cwd=root)
    run("git", "commit", "-qm", "test: temporary release candidate", cwd=root)
    run("git", "tag", TARGET, cwd=root)
    return run("git", "rev-parse", "HEAD", cwd=root)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-ci-real-canary-") as folder:
        temp = Path(folder)
        candidate = temp / "candidate"
        baseline = temp / "canary"
        run("git", "clone", "-q", "--no-local", str(SOURCE), str(candidate), cwd=temp)
        run("git", "clone", "-q", CANARY_URL, str(baseline), cwd=temp)
        run("git", "checkout", "-q", "--detach", CANARY_SHA, cwd=baseline)
        candidate_sha = prepare(candidate)
        command = [
            sys.executable, ".harness/tools/release-upgrade-qualification.py",
            "--baseline-project", str(baseline),
            "--baseline-sha", CANARY_SHA,
            "--candidate-source", str(candidate),
            "--candidate-sha", candidate_sha,
            "--json",
        ]
        import os
        diagnostic_env = os.environ.copy()
        diagnostic_env["HARNESS_CI_CANARY_DEBUG"] = "1"
        proc = subprocess.run(
            command, cwd=candidate, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            timeout=900, env=diagnostic_env,
        )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            print("canary qualification returned invalid JSON", file=sys.stderr)
            print(proc.stderr[-700:], file=sys.stderr)
            return 1
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if proc.returncode:
            print("REAL CANARY UPGRADE: FAIL", file=sys.stderr)
            return 1
        if payload.get("status") != "PASS":
            return 1
        print("REAL CANARY UPGRADE: PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
