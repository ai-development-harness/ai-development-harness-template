#!/usr/bin/env python3
"""Canonical deterministic entrypoint для release-level qualification Harness.

Один executable используется всеми platform/runtime lanes. Внешний orchestrator
выбирает lane, но не дублирует набор команд qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Sequence


SCHEMA_VERSION = 1
MINIMUM_PYTHON = (3, 11)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=root)


def _current_revision(root: Path) -> str | None:
    proc = _git(root, "rev-parse", "HEAD")
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def _worktree_status(root: Path) -> tuple[int, str, str]:
    proc = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    return proc.returncode, proc.stdout, proc.stderr


def _gate(
    gate_id: str,
    command: Sequence[str],
    *,
    root: Path,
) -> dict[str, object]:
    proc = _run(command, cwd=root)
    return {
        "id": gate_id,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "exitCode": proc.returncode,
        "stdoutSha256": _sha256(proc.stdout),
        "stderrSha256": _sha256(proc.stderr),
        "stdoutBytes": len(proc.stdout.encode("utf-8")),
        "stderrBytes": len(proc.stderr.encode("utf-8")),
    }


def _lane_commands(lane: str) -> list[tuple[str, list[str]]]:
    py = sys.executable
    if lane in {"current", "minimum"}:
        commands = [
            (
                "validate-ci",
                [py, ".harness/tools/validate.py", "--mode", "ci"],
            ),
            (
                "synthetic-self-tests",
                [py, ".harness/tools/run-self-tests.py"],
            ),
        ]
        if lane == "current":
            commands.append(
                (
                    "bounded-stress-suite",
                    [
                        py,
                        ".harness/tools/run-stress-tests.py",
                        "--iterations",
                        "20",
                    ],
                )
            )
        return commands
    if lane == "windows":
        targeted = [
            "harness-config-self-test.py",
            "document-contract-self-test.py",
            "execution-self-test.py",
            "verification-self-test.py",
            "reliable-orchestration-fault-self-test.py",
            "update-engine-self-test.py",
        ]
        commands: list[tuple[str, list[str]]] = [
            (
                "validate-ci",
                [py, ".harness/tools/validate.py", "--mode", "ci"],
            )
        ]
        commands.extend(
            (
                f"windows-{name.removesuffix('.py')}",
                [py, f".harness/tools/{name}"],
            )
            for name in targeted
        )
        return commands
    raise ValueError(f"unsupported lane: {lane}")


def _blocked_result(
    *,
    lane: str,
    expected_revision: str,
    repository_revision: str | None,
    reason: str,
) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "harness_release_qualification",
        "status": "BLOCKED",
        "lane": lane,
        "expectedRevision": expected_revision,
        "repositoryRevision": repository_revision,
        "python": platform.python_version(),
        "platform": platform.system().lower(),
        "reason": reason,
        "gates": [],
    }


def qualify(
    *,
    lane: str,
    expected_revision: str,
    expected_python: str | None = None,
) -> tuple[int, dict[str, object]]:
    root = _repo_root()
    revision = _current_revision(root)
    if revision is None:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=None,
            reason="GIT_HEAD_UNAVAILABLE",
        )
    if revision != expected_revision:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason="REVISION_MISMATCH",
        )

    if sys.version_info[:2] < MINIMUM_PYTHON:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason="UNSUPPORTED_PYTHON",
        )
    if expected_python is not None:
        actual = f"{sys.version_info.major}.{sys.version_info.minor}"
        if actual != expected_python:
            return 2, _blocked_result(
                lane=lane,
                expected_revision=expected_revision,
                repository_revision=revision,
                reason=f"PYTHON_VERSION_MISMATCH:{actual}",
            )
    if lane == "minimum" and sys.version_info[:2] != MINIMUM_PYTHON:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason="MINIMUM_LANE_REQUIRES_PYTHON_3_11",
        )
    if lane == "windows" and os.name != "nt":
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason="WINDOWS_LANE_REQUIRES_WINDOWS",
        )

    status_code, before, status_stderr = _worktree_status(root)
    if status_code != 0:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason=f"GIT_STATUS_FAILED:{_sha256(status_stderr)}",
        )
    if before:
        return 2, _blocked_result(
            lane=lane,
            expected_revision=expected_revision,
            repository_revision=revision,
            reason="CHECKOUT_NOT_CLEAN",
        )

    gates: list[dict[str, object]] = []
    failed = False
    for gate_id, command in _lane_commands(lane):
        item = _gate(gate_id, command, root=root)
        gates.append(item)
        if item["status"] != "PASS":
            failed = True

    after_code, after, after_stderr = _worktree_status(root)
    if after_code != 0:
        gates.append(
            {
                "id": "checkout-clean-after",
                "status": "FAIL",
                "exitCode": after_code,
                "stdoutSha256": _sha256(after),
                "stderrSha256": _sha256(after_stderr),
                "stdoutBytes": len(after.encode("utf-8")),
                "stderrBytes": len(after_stderr.encode("utf-8")),
            }
        )
        failed = True
    else:
        clean = not after
        gates.append(
            {
                "id": "checkout-clean-after",
                "status": "PASS" if clean else "FAIL",
                "exitCode": 0 if clean else 1,
                "stdoutSha256": _sha256(after),
                "stderrSha256": _sha256(after_stderr),
                "stdoutBytes": len(after.encode("utf-8")),
                "stderrBytes": len(after_stderr.encode("utf-8")),
            }
        )
        if not clean:
            failed = True

    payload: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "harness_release_qualification",
        "status": "FAIL" if failed else "PASS",
        "lane": lane,
        "expectedRevision": expected_revision,
        "repositoryRevision": revision,
        "python": platform.python_version(),
        "platform": platform.system().lower(),
        "gates": gates,
    }
    return (1 if failed else 0), payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Qualify an exact Harness release-candidate checkout."
    )
    parser.add_argument(
        "--lane",
        choices=("current", "minimum", "windows"),
        required=True,
        help="Qualification lane selected by the release orchestrator.",
    )
    parser.add_argument(
        "--expect-sha",
        required=True,
        help="Exact candidate commit SHA that this checkout must contain.",
    )
    parser.add_argument(
        "--expected-python",
        help="Optional exact major.minor runtime required by the caller, e.g. 3.13.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    code, payload = qualify(
        lane=args.lane,
        expected_revision=args.expect_sha,
        expected_python=args.expected_python,
    )
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(
            f"HARNESS RELEASE QUALIFICATION: {payload['status']} "
            f"(lane={payload['lane']}, sha={payload.get('repositoryRevision')})"
        )
        if payload.get("reason"):
            print(f"Reason: {payload['reason']}", file=sys.stderr)
        for gate in payload.get("gates", []):
            print(f"[{gate['status']}] {gate['id']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
