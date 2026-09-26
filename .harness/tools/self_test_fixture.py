#!/usr/bin/env python3
"""Изоляция project-owned state в synthetic self-tests Harness."""
from __future__ import annotations

from pathlib import Path
import shutil

from harness_config import (
    adr_directory,
    audit_directory,
    init_review_directory,
    open_questions_directory,
    planning_review_directory,
    release_directory,
    requirements_directory,
    review_directory,
    skill_search_directory,
    task_directory,
    update_report_directory,
)
from projection_contract import write_projections


def _remove_files(directory: Path, pattern: str, *, keep: set[str] | None = None) -> None:
    """Удалить canonical artifacts fixture, сохранив protocol scaffolding."""
    if not directory.is_dir():
        return
    preserved = keep or set()
    for path in directory.glob(pattern):
        if path.name in preserved:
            continue
        if path.is_file() or path.is_symlink():
            path.unlink()


def _clear_generated_directory(directory: Path) -> None:
    """Очистить durable generated state, не удаляя README/TEMPLATE."""
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if path.name in {"README.md", "TEMPLATE.md"}:
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def isolate_project_artifacts(root: Path) -> None:
    """Удалить inherited project artifacts из synthetic fixture.

    Self-tests копируют tracked checkout, чтобы использовать текущий Harness
    runtime. Canonical STEP/REQ/ADR/OQ, durable reports и projections при этом
    принадлежат host project и не должны влиять на synthetic expectations.
    После очистки projections пересобираются из оставшегося canonical state.
    """
    _remove_files(task_directory(root), "STEP-*.md")
    _remove_files(
        requirements_directory(root),
        "REQ-*.md",
        keep={"REQ-001-template.md"},
    )
    _remove_files(adr_directory(root), "ADR-*.md")
    _remove_files(open_questions_directory(root), "OQ-*.md")

    for directory in (
        review_directory(root),
        planning_review_directory(root),
        init_review_directory(root),
        audit_directory(root),
        release_directory(root),
        skill_search_directory(root),
        update_report_directory(root),
    ):
        _clear_generated_directory(directory)

    write_projections(root)
