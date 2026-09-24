#!/usr/bin/env python3
"""Regression self-test Git path transport в specialized review gate."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from review_gates import _git_changed_paths, required_reviewers


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def git(root: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")


def manifest() -> str:
    return """review:
  security: auto
  tests: auto
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
"""


def task() -> str:
    return """---
schema: 1
id: STEP-001
status: planned
type: documentation
priority: medium
phase: test
depends_on: []
requirements: []
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# STEP-001 — Review path transport

## Goal

Проверить точную передачу Git paths.
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-review-paths-") as tmp:
        root = Path(tmp)
        write(root / ".harness/manifest.yaml", manifest())
        write(root / "planning/tasks/STEP-001.md", task())
        write(root / "README.md", "fixture\n")

        git(root, "init", "-q")
        git(root, "config", "user.email", "harness-test@example.invalid")
        git(root, "config", "user.name", "Harness Test")
        git(root, "add", ".")
        git(root, "commit", "-qm", "fixture")

        # Unstaged tracked Unicode path: default Git quoting раньше превращал
        # кириллицу в escaped octal sequence и ломал path heuristics.
        unicode_code = root / "src/кириллица.ts"
        write(unicode_code, "export const value = 1;\n")
        git(root, "add", "--", unicode_code.relative_to(root).as_posix())
        git(root, "commit", "-qm", "add unicode code path")
        write(unicode_code, "export const value = 2;\n")

        # Staged path нужен для отдельного --cached collector.
        staged_security = root / "security/секрет файл.md"
        write(staged_security, "security fixture\n")
        git(root, "add", "--", staged_security.relative_to(root).as_posix())

        # Untracked paths проверяют ls-files -z. Newline обязан остаться частью
        # одного имени, а trailing whitespace нельзя strip-нуть.
        newline_path = root / "docs/строка\nперенос.md"
        trailing_path = root / "docs/trailing-space "
        write(newline_path, "newline path\n")
        write(trailing_path, "trailing path\n")

        paths, mode = _git_changed_paths(root)
        assert mode == "worktree", (mode, paths)
        expected = {
            "src/кириллица.ts",
            "security/секрет файл.md",
            "docs/строка\nперенос.md",
            "docs/trailing-space ",
        }
        assert expected.issubset(set(paths)), paths
        assert "docs/строка" not in paths and "перенос.md" not in paths, paths

        gate = required_reviewers(root, "STEP-001")
        assert "security" in gate["required"], gate
        assert "tests" in gate["required"], gate
        assert "src/кириллица.ts" in gate["changedPaths"], gate
        assert "docs/строка\nперенос.md" in gate["changedPaths"], gate

        # Реальный dirty product surface также обязан быть инвариантен к
        # появлению Harness-owned report: worktree/paths/required/basis не меняются.
        dirty_report = root / "planning/reviews/STEP-001/REVIEW-20981231T235959Z.md"
        write(dirty_report, "dirty report fixture\n")
        dirty_with_report = required_reviewers(root, "STEP-001")
        assert dirty_with_report["surfaceMode"] == gate["surfaceMode"] == "worktree", (
            gate,
            dirty_with_report,
        )
        assert dirty_with_report["changedPaths"] == gate["changedPaths"], (
            gate,
            dirty_with_report,
        )
        assert dirty_with_report["required"] == gate["required"], (
            gate,
            dirty_with_report,
        )
        assert dirty_with_report["basis"] == gate["basis"], (
            gate,
            dirty_with_report,
        )
        dirty_report.unlink()

        # Clean-tree fallback использует diff-tree и обязан сохранять те же raw
        # path boundaries/Unicode после commit.
        git(root, "add", ".")
        git(root, "commit", "-qm", "commit path fixtures")
        fallback_paths, fallback_mode = _git_changed_paths(root)
        assert fallback_mode == "clean-tree-fallback", (fallback_mode, fallback_paths)
        assert expected.issubset(set(fallback_paths)), fallback_paths

        # Regression #77: Harness-owned report не является product surface и не
        # имеет права переключать режим/required/basis только фактом резервирования.
        fallback_gate = required_reviewers(root, "STEP-001")
        report_path = root / "planning/reviews/STEP-001/REVIEW-20990101T000000Z.md"
        write(report_path, "reserved report fixture\n")

        after_report_paths, after_report_mode = _git_changed_paths(root)
        assert after_report_mode == fallback_mode, (
            fallback_mode,
            after_report_mode,
            after_report_paths,
        )
        assert after_report_paths == fallback_paths, (
            fallback_paths,
            after_report_paths,
        )

        after_report_gate = required_reviewers(root, "STEP-001")
        assert after_report_gate["surfaceMode"] == fallback_gate["surfaceMode"], (
            fallback_gate,
            after_report_gate,
        )
        assert after_report_gate["required"] == fallback_gate["required"], (
            fallback_gate,
            after_report_gate,
        )
        assert after_report_gate["basis"] == fallback_gate["basis"], (
            fallback_gate,
            after_report_gate,
        )

    print("REVIEW GATES SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
