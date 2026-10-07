#!/usr/bin/env python3
"""Synthetic regression для canonical release-qualification entrypoint."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


SOURCE = Path(__file__).with_name("release-qualification.py")


def run(
    command: list[str],
    *,
    cwd: Path,
    expect: int,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != expect:
        raise AssertionError(
            f"expected exit {expect}, got {proc.returncode}: "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    return proc


def write_tool(root: Path, name: str, body: str) -> None:
    path = root / ".harness" / "tools" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def git(root: Path, *args: str) -> str:
    proc = run(["git", *args], cwd=root, expect=0)
    return proc.stdout.strip()


def commit_all(root: Path, message: str) -> str:
    git(root, "add", ".")
    git(root, "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def bootstrap(root: Path) -> str:
    tools = root / ".harness" / "tools"
    tools.mkdir(parents=True)
    shutil.copy2(SOURCE, tools / SOURCE.name)

    pass_script = "import sys\nraise SystemExit(0)\n"
    write_tool(root, "validate.py", pass_script)
    write_tool(root, "run-self-tests.py", pass_script)
    write_tool(root, "run-stress-tests.py", pass_script)
    for name in (
        "harness-config-self-test.py",
        "document-contract-self-test.py",
        "execution-self-test.py",
        "verification-self-test.py",
        "reliable-orchestration-fault-self-test.py",
        "update-engine-self-test.py",
    ):
        write_tool(root, name, pass_script)

    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "release-qualification@example.invalid")
    git(root, "config", "user.name", "Release Qualification Self Test")
    return commit_all(root, "bootstrap")


def invoke(
    root: Path,
    sha: str,
    *,
    lane: str = "current",
    expected_python: str | None = None,
    expect: int = 0,
) -> dict[str, object]:
    cmd = [
        sys.executable,
        ".harness/tools/release-qualification.py",
        "--lane",
        lane,
        "--expect-sha",
        sha,
        "--json",
    ]
    if expected_python is not None:
        cmd.extend(["--expected-python", expected_python])
    proc = run(cmd, cwd=root, expect=expect)
    return json.loads(proc.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-release-qualification-") as td:
        root = Path(td)
        sha = bootstrap(root)

        payload = invoke(root, sha)
        assert payload["status"] == "PASS", payload
        assert payload["repositoryRevision"] == sha, payload
        assert payload["expectedRevision"] == sha, payload
        assert [item["id"] for item in payload["gates"]] == [
            "validate-ci",
            "synthetic-self-tests",
            "bounded-stress-suite",
            "checkout-clean-after",
        ], payload

        mismatch = invoke(root, "0" * 40, expect=2)
        assert mismatch["status"] == "BLOCKED", mismatch
        assert mismatch["reason"] == "REVISION_MISMATCH", mismatch

        bad_python = "0.0"
        runtime_mismatch = invoke(
            root,
            sha,
            expected_python=bad_python,
            expect=2,
        )
        assert runtime_mismatch["status"] == "BLOCKED", runtime_mismatch
        assert str(runtime_mismatch["reason"]).startswith(
            "PYTHON_VERSION_MISMATCH:"
        ), runtime_mismatch

        write_tool(
            root,
            "run-self-tests.py",
            "import sys\nprint('synthetic failure')\nraise SystemExit(7)\n",
        )
        failed_sha = commit_all(root, "failing gate")
        failed = invoke(root, failed_sha, expect=1)
        assert failed["status"] == "FAIL", failed
        gate = next(
            item for item in failed["gates"] if item["id"] == "synthetic-self-tests"
        )
        assert gate["exitCode"] == 7, gate

        write_tool(
            root,
            "run-self-tests.py",
            "from pathlib import Path\n"
            "Path('qualification-mutation.txt').write_text('mutated', encoding='utf-8')\n",
        )
        mutation_sha = commit_all(root, "mutating gate")
        mutation = invoke(root, mutation_sha, expect=1)
        assert mutation["status"] == "FAIL", mutation
        clean_gate = next(
            item for item in mutation["gates"] if item["id"] == "checkout-clean-after"
        )
        assert clean_gate["status"] == "FAIL", clean_gate
        (root / "qualification-mutation.txt").unlink()

        write_tool(
            root,
            "run-self-tests.py",
            "import sys\nraise SystemExit(0)\n",
        )
        run(
            [sys.executable, ".harness/tools/run-self-tests.py"],
            cwd=root,
            expect=0,
        )
        restored_sha = commit_all(root, "restore passing gate")

        min_expect = 0 if sys.version_info[:2] == (3, 11) else 2
        minimum = invoke(root, restored_sha, lane="minimum", expect=min_expect)
        if min_expect == 0:
            assert minimum["status"] == "PASS", minimum
        else:
            assert minimum["status"] == "BLOCKED", minimum
            assert minimum["reason"] == "MINIMUM_LANE_REQUIRES_PYTHON_3_11", minimum

        windows_expect = 0 if sys.platform.startswith("win") else 2
        windows = invoke(root, restored_sha, lane="windows", expect=windows_expect)
        if windows_expect == 0:
            assert windows["status"] == "PASS", windows
        else:
            assert windows["status"] == "BLOCKED", windows
            assert windows["reason"] == "WINDOWS_LANE_REQUIRES_WINDOWS", windows

    print("release qualification self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
