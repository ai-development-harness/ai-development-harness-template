#!/usr/bin/env python3
"""Regression для release gate временных CI-артефактов в managed workflows (#379)."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


TOOL = Path(__file__).with_name("release-artifact-hygiene.py")

CLEAN = """name: Harness Integrity
on:
  pull_request:
    # Пример: codex/pr368-review-fixes в комментарии не является триггером.
    branches:
      - main
      - 'feature/**'
  push:
    branches: [main]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
      - run: git fetch origin main
"""

TEMPORARY_TRIGGER = """on:
  push:
    branches:
      - main
      - codex/pr368-review-fixes
  pull_request:
    branches-ignore: ["fix/376-windows-incremental-paths"]
"""

PINNED = """on:
  pull_request:
    branches:
    - main
jobs:
  overlay:
    steps:
      - run: |
          git fetch origin 1e4245d58f50035fa114fd97e1e6ec05903e741a
          git restore --source=1e4245d58f50035fa114fd97e1e6ec05903e741a -- tool.py
          git -C upstream checkout 1e4245d58f50035fa114fd97e1e6ec05903e741a
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          ref: '1e4245d58f50035fa114fd97e1e6ec05903e741a'
"""


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def invoke(root: Path, expect: int) -> dict:
    proc = subprocess.run([sys.executable, str(TOOL), "--root", str(root), "--json"],
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert proc.returncode == expect, (proc.returncode, proc.stdout, proc.stderr)
    return json.loads(proc.stdout)


def fixture(root: Path, files: dict[str, str]) -> None:
    folder = root / ".github/workflows"
    folder.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (folder / name).write_text(body, encoding="utf-8")
    git(root, "add", "-A")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-release-hygiene-") as td:
        root = Path(td)
        git(root, "init", "-q", "-b", "main")
        fixture(root, {"harness-integrity.yml": CLEAN})
        assert invoke(root, 0) == {"kind": "release_artifact_hygiene", "status": "PASS", "violations": []}

        fixture(root, {"harness-integrity.yml": TEMPORARY_TRIGGER})
        report = invoke(root, 1)
        assert [(v["code"], v["value"]) for v in report["violations"]] == [
            ("TEMPORARY_BRANCH_TRIGGER", "codex/pr368-review-fixes"),
            ("TEMPORARY_BRANCH_TRIGGER", "fix/376-windows-incremental-paths"),
        ], report
        assert report["violations"][0]["line"] == 5, report

        fixture(root, {"harness-integrity.yml": CLEAN, "pr377-windows-regression.yml": PINNED})
        report = invoke(root, 1)
        assert [v["code"] for v in report["violations"]] == [
            "TEMPORARY_WORKFLOW_FILE", "PINNED_UPSTREAM_COMMIT", "PINNED_UPSTREAM_COMMIT",
            "PINNED_UPSTREAM_COMMIT", "PINNED_UPSTREAM_COMMIT",
        ], report
        assert [v["line"] for v in report["violations"]] == [None, 9, 10, 11, 14], report

        # Gate проверяет поставляемые (tracked) paths, а не локальный мусор.
        git(root, "rm", "-q", "--cached", ".github/workflows/pr377-windows-regression.yml")
        assert invoke(root, 0)["status"] == "PASS"
    print("RELEASE ARTIFACT HYGIENE SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
