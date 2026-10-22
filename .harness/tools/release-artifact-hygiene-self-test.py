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

# Обходы построчных шаблонов: flow sequence ниже ключа и на нескольких строках,
# SHA в env, перенос git-команды и flow mapping checkout `with`.
BYPASS = """on:
  push:
    branches:
      [main, fix/x]
  pull_request:
    branches-ignore: [
      'feature/**',
      codex/z
    ]
env:
  UPSTREAM: 1e4245d58f50035fa114fd97e1e6ec05903e741a
jobs:
  overlay:
    steps:
      - run: |
          git fetch origin \\
            1e4245d58f50035fa114fd97e1e6ec05903e741a
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7
        with: {ref: 1e4245d58f50035fa114fd97e1e6ec05903e741a}
"""

# Flow mapping trigger с несколькими ключами и ключ в кавычках;
# `branches:` внутри текста команды ключом не является.
FLOW_MAPPING = """on:
  push: {branches: [main, fix/x], branches-ignore: codex/y}
  pull_request: {'branches': ['feature/**',
    pr380-check]}
jobs:
  validate:
    steps:
      - run: echo "protected branches: main"
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

        fixture(root, {"harness-integrity.yml": BYPASS})
        report = invoke(root, 1)
        assert [(v["code"], v["line"]) for v in report["violations"]] == [
            ("TEMPORARY_BRANCH_TRIGGER", 4), ("TEMPORARY_BRANCH_TRIGGER", 6),
            ("PINNED_UPSTREAM_COMMIT", 11), ("PINNED_UPSTREAM_COMMIT", 17), ("PINNED_UPSTREAM_COMMIT", 19),
        ], report
        assert [v["value"] for v in report["violations"][:2]] == ["fix/x", "codex/z"], report

        fixture(root, {"harness-integrity.yml": FLOW_MAPPING})
        report = invoke(root, 1)
        assert [(v["code"], v["line"], v["value"]) for v in report["violations"]] == [
            ("TEMPORARY_BRANCH_TRIGGER", 2, "fix/x"), ("TEMPORARY_BRANCH_TRIGGER", 2, "codex/y"),
            ("TEMPORARY_BRANCH_TRIGGER", 3, "pr380-check"),
        ], report

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
