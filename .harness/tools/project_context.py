#!/usr/bin/env python3
"""Deterministic boundary разрешения Harness Project Context.

Модуль намеренно отделяет два разных понятия:

- projectRoot — корень выбранного Harness member project;
- gitRoot — корень общего Git worktree.

Он не выполняет orchestration и не выбирает runtime. Его задача — один раз,
детерминированно определить project identity и предоставить общие containment
primitives, чтобы последующие tools не изобретали собственную root semantics.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Mapping

from harness_config import ConfigError, get, load_manifest


# Stable machine reason codes из MULTI_PROJECT_CONTEXTS architecture contract.
PROJECT_ROOT_INVALID = "PROJECT_ROOT_INVALID"
PROJECT_ROOT_SELECTION_REQUIRED = "PROJECT_ROOT_SELECTION_REQUIRED"
PROJECT_ROOT_OUTSIDE_GIT_WORKTREE = "PROJECT_ROOT_OUTSIDE_GIT_WORKTREE"
PROJECT_PATH_ESCAPE = "PROJECT_PATH_ESCAPE"
SIBLING_PROJECT_MUTATION_FORBIDDEN = "SIBLING_PROJECT_MUTATION_FORBIDDEN"
PROJECT_CONTEXT_VERSION_CONFLICT = "PROJECT_CONTEXT_VERSION_CONFLICT"


class ProjectContextError(RuntimeError):
    """Fail-closed ошибка project-context resolution/containment."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, object]:
        return {
            "status": "BLOCKED",
            "reasonCode": self.code,
            "message": self.message,
            **self.details,
        }


@dataclass(frozen=True)
class ProjectContext:
    """Machine-readable identity одного выбранного Harness member project."""

    schemaVersion: int
    projectRoot: str
    gitRoot: str
    selectionSource: str
    projectName: str | None
    harnessRelease: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _run_git(cwd: Path, *args: str) -> str | None:
    """Выполнить read-only Git query без shell и вернуть trimmed stdout."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def git_root_for(path: Path) -> Path | None:
    """Вернуть actual Git worktree root для path либо None вне worktree."""
    target = path if path.is_dir() else path.parent
    value = _run_git(target, "rev-parse", "--show-toplevel")
    return None if value is None else Path(value).resolve()


def _path_key(path: Path, *, case_sensitive: bool | None = None) -> str:
    """Нормализовать path для containment/equality на текущей filesystem.

    При обычной работе os.path.normcase даёт platform-native semantics.
    Параметр case_sensitive нужен self-tests, чтобы отдельно доказать
    case-insensitive boundary, даже если CI выполняется на Linux.
    """
    value = os.path.realpath(os.fspath(path))
    if case_sensitive is None:
        value = os.path.normcase(value)
    elif not case_sensitive:
        value = value.casefold()
    return os.path.normpath(value)


def is_within(
    path: Path,
    parent: Path,
    *,
    case_sensitive: bool | None = None,
) -> bool:
    """Проверить realpath containment, включая Windows drive/case semantics."""
    child_key = _path_key(path, case_sensitive=case_sensitive)
    parent_key = _path_key(parent, case_sensitive=case_sensitive)
    try:
        return os.path.commonpath([child_key, parent_key]) == parent_key
    except ValueError:
        # Например, разные Windows drives не имеют общего допустимого root.
        return False


def _read_identity(root: Path) -> tuple[str | None, str]:
    """Минимально валидировать canonical marker и protocol identity."""
    marker = root / ".harness" / "manifest.yaml"
    if not marker.is_file():
        raise ProjectContextError(
            PROJECT_ROOT_INVALID,
            f"Harness marker not found: {marker}",
            details={"projectRoot": str(root)},
        )

    try:
        manifest = load_manifest(root)
    except ConfigError as exc:
        raise ProjectContextError(
            PROJECT_ROOT_INVALID,
            f"Invalid Harness manifest at {marker}: {exc}",
            details={"projectRoot": str(root)},
        ) from exc

    version = get(manifest, "harness.version")
    release = get(manifest, "harness.release")
    if not isinstance(version, str) or not version.strip():
        raise ProjectContextError(
            PROJECT_ROOT_INVALID,
            "manifest harness.version must be a non-empty string",
            details={"projectRoot": str(root)},
        )
    if not isinstance(release, str) or not release.strip():
        raise ProjectContextError(
            PROJECT_ROOT_INVALID,
            "manifest harness.release must be a non-empty string",
            details={"projectRoot": str(root)},
        )

    project_name = get(manifest, "project.name")
    if project_name is not None and (
        not isinstance(project_name, str) or not project_name.strip()
    ):
        raise ProjectContextError(
            PROJECT_ROOT_INVALID,
            "manifest project.name must be null or a non-empty string",
            details={"projectRoot": str(root)},
        )

    return project_name, release


def _normalize_candidate(value: str | Path, *, start: Path) -> Path:
    """Разрешить explicit/env root; относительный path считается от start."""
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = start / candidate
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:
        raise ProjectContextError(
            PROJECT_ROOT_INVALID,
            f"Project root cannot be resolved: {candidate}: {exc}",
            details={"projectRoot": str(candidate)},
        ) from exc


def _nearest_marker(start: Path) -> Path | None:
    """Искать marker только вверх по parent chain.

    Descendant scanning намеренно отсутствует: при нескольких members выбор
    "первого найденного" был бы nondeterministic.
    """
    current = start if start.is_dir() else start.parent
    current = current.resolve()

    while True:
        marker = current / ".harness" / "manifest.yaml"
        if marker.exists():
            # Возвращаем ближайший marker даже если он окажется невалидным.
            # _read_identity затем fail-closed заблокирует context вместо
            # опасного fallback к более высокому parent project.
            return current
        if current.parent == current:
            return None
        current = current.parent


def resolve_project_context(
    *,
    start: Path | None = None,
    explicit_root: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ProjectContext:
    """Разрешить selected project согласно accepted precedence contract.

    Precedence:
    1. explicit project root;
    2. HARNESS_PROJECT_ROOT;
    3. nearest valid parent marker;
    4. fail-closed selection required.

    Invalid explicit/environment root никогда не fallback-ится к cwd/parent.
    """
    start = (start or Path.cwd()).expanduser().resolve()
    env = os.environ if env is None else env
    invocation_git_root = git_root_for(start)

    if explicit_root is not None:
        candidate = _normalize_candidate(explicit_root, start=start)
        source = "explicit"
    elif env.get("HARNESS_PROJECT_ROOT"):
        candidate = _normalize_candidate(env["HARNESS_PROJECT_ROOT"], start=start)
        source = "environment"
    else:
        nearest = _nearest_marker(start)
        if nearest is None:
            raise ProjectContextError(
                PROJECT_ROOT_SELECTION_REQUIRED,
                "Harness project root cannot be inferred; explicit selection is required",
                details={"start": str(start)},
            )
        candidate = nearest
        source = "nearest-parent"

    if not candidate.is_dir():
        raise ProjectContextError(
            PROJECT_ROOT_INVALID,
            f"Project root is not a directory: {candidate}",
            details={"projectRoot": str(candidate)},
        )

    project_name, harness_release = _read_identity(candidate)
    candidate_git_root = git_root_for(candidate)
    if candidate_git_root is None:
        raise ProjectContextError(
            PROJECT_ROOT_INVALID,
            f"Project root is not inside a Git worktree: {candidate}",
            details={"projectRoot": str(candidate)},
        )

    # Если invocation уже находится в Git worktree, explicit/env root обязан
    # принадлежать именно этому worktree. Иначе accidental cross-repo mutation
    # могла бы выглядеть как обычное переключение member project.
    if (
        invocation_git_root is not None
        and _path_key(candidate_git_root) != _path_key(invocation_git_root)
    ):
        raise ProjectContextError(
            PROJECT_ROOT_OUTSIDE_GIT_WORKTREE,
            "Selected Harness project belongs to a different Git worktree",
            details={
                "projectRoot": str(candidate),
                "projectGitRoot": str(candidate_git_root),
                "invocationGitRoot": str(invocation_git_root),
            },
        )

    return ProjectContext(
        schemaVersion=1,
        projectRoot=str(candidate),
        gitRoot=str(candidate_git_root),
        selectionSource=source,
        projectName=project_name,
        harnessRelease=harness_release,
    )


def resolve_project_local_path(
    project_root: Path,
    value: str,
    *,
    label: str = "project path",
) -> Path:
    """Разрешить project-local path с lexical + realpath containment.

    Для Harness artifacts/control state выход за selected projectRoot запрещён.
    """
    if not isinstance(value, str) or not value.strip():
        raise ProjectContextError(
            PROJECT_PATH_ESCAPE,
            f"{label} must be a non-empty relative path",
        )

    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise ProjectContextError(
            PROJECT_PATH_ESCAPE,
            f"{label} must stay inside selected project: {value}",
            details={"projectRoot": str(project_root)},
        )

    base = project_root.resolve()
    candidate = (base / rel).resolve(strict=False)
    if not is_within(candidate, base):
        raise ProjectContextError(
            PROJECT_PATH_ESCAPE,
            f"{label} escapes selected project: {value}",
            details={"projectRoot": str(base), "path": str(candidate)},
        )
    return candidate


def nearest_harness_root_for_path(
    path: Path,
    *,
    git_root: Path,
) -> Path | None:
    """Найти Harness owner target path внутри одного Git worktree."""
    current = path if path.is_dir() else path.parent
    current = current.resolve(strict=False)
    git_root = git_root.resolve()

    if not is_within(current, git_root):
        return None

    while True:
        if (current / ".harness" / "manifest.yaml").is_file():
            return current
        if _path_key(current) == _path_key(git_root):
            return None
        current = current.parent


def resolve_product_mutation_path(
    *,
    project_root: Path,
    git_root: Path,
    value: str,
    label: str = "product mutation",
) -> Path:
    """Проверить mutation target, который может лежать вне projectRoot.

    Разрешён shared product code внутри gitRoot, но запрещены:
    - escape за gitRoot;
    - mutation внутрь другого Harness member project.
    """
    if not isinstance(value, str) or not value.strip():
        raise ProjectContextError(
            PROJECT_PATH_ESCAPE,
            f"{label} must be a non-empty path",
        )

    raw = Path(value)
    candidate = raw if raw.is_absolute() else project_root / raw
    candidate = candidate.resolve(strict=False)
    git_root = git_root.resolve()
    project_root = project_root.resolve()

    if not is_within(candidate, git_root):
        raise ProjectContextError(
            PROJECT_PATH_ESCAPE,
            f"{label} escapes Git worktree: {value}",
            details={"gitRoot": str(git_root), "path": str(candidate)},
        )

    owner = nearest_harness_root_for_path(candidate, git_root=git_root)
    if owner is not None and _path_key(owner) != _path_key(project_root):
        raise ProjectContextError(
            SIBLING_PROJECT_MUTATION_FORBIDDEN,
            f"{label} targets another Harness project: {owner}",
            details={
                "projectRoot": str(project_root),
                "targetProjectRoot": str(owner),
                "path": str(candidate),
            },
        )

    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve deterministic Harness Project Context."
    )
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--start", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    try:
        context = resolve_project_context(
            start=args.start,
            explicit_root=args.project_root,
        )
        payload: dict[str, object] = {"status": "PASS", **context.to_dict()}
        code = 0
    except ProjectContextError as exc:
        payload = exc.to_dict()
        code = 2

    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    elif code == 0:
        for key, value in payload.items():
            print(f"{key}: {value}")
    else:
        print(
            f"{payload['reasonCode']}: {payload['message']}",
            file=sys.stderr,
        )

    return code


if __name__ == "__main__":
    raise SystemExit(main())
