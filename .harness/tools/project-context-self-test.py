#!/usr/bin/env python3
"""Regression self-test multiple-project Project Context foundation."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from project_context import (
    PROJECT_PATH_ESCAPE,
    PROJECT_ROOT_INVALID,
    PROJECT_ROOT_OUTSIDE_GIT_WORKTREE,
    PROJECT_ROOT_SELECTION_REQUIRED,
    SIBLING_PROJECT_MUTATION_FORBIDDEN,
    ProjectContextError,
    is_within,
    resolve_product_mutation_path,
    resolve_project_context,
    resolve_project_local_path,
)


def run(cwd: Path, *args: str) -> None:
    subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def write_manifest(
    root: Path,
    *,
    name: str | None,
    release: str = "0.10.4",
) -> None:
    path = root / ".harness" / "manifest.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    project_name = "null" if name is None else name
    path.write_text(
        "harness:\n"
        '  version: "1"\n'
        f'  release: "{release}"\n'
        "project:\n"
        f"  name: {project_name}\n",
        encoding="utf-8",
        newline="\n",
    )


def assert_blocked(code: str, call) -> None:
    try:
        call()
    except ProjectContextError as exc:
        assert exc.code == code, (exc.code, exc)
    else:
        raise AssertionError(f"expected {code}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-project-context-") as tmp:
        base = Path(tmp)

        # Existing single-root Harness project остаётся backward-compatible:
        # projectRoot и gitRoot совпадают.
        single = base / "single"
        single.mkdir()
        run(single, "git", "init")
        write_manifest(single, name="single")
        context = resolve_project_context(start=single, env={})
        assert Path(context.projectRoot) == single.resolve()
        assert Path(context.gitRoot) == single.resolve()
        assert context.selectionSource == "nearest-parent"

        # Synthetic monorepo: Git root сам не является Harness project.
        repo = base / "repo"
        repo.mkdir()
        run(repo, "git", "init")
        web = repo / "apps" / "web"
        api = repo / "services" / "api"
        shared = repo / "packages" / "shared"
        web.mkdir(parents=True)
        api.mkdir(parents=True)
        shared.mkdir(parents=True)
        write_manifest(web, name="web")
        write_manifest(api, name="api", release="0.9.0")

        # nearest-parent выбирает member, а не Git root/descendant scan.
        context = resolve_project_context(start=web, env={})
        assert Path(context.projectRoot) == web.resolve()
        assert Path(context.gitRoot) == repo.resolve()
        assert context.selectionSource == "nearest-parent"
        assert context.projectName == "web"

        # Explicit root имеет высший приоритет.
        context = resolve_project_context(
            start=repo,
            explicit_root=api,
            env={"HARNESS_PROJECT_ROOT": str(web)},
        )
        assert Path(context.projectRoot) == api.resolve()
        assert context.selectionSource == "explicit"
        assert context.harnessRelease == "0.9.0"

        # Environment override работает только при отсутствии explicit root.
        context = resolve_project_context(
            start=repo,
            env={"HARNESS_PROJECT_ROOT": str(web)},
        )
        assert Path(context.projectRoot) == web.resolve()
        assert context.selectionSource == "environment"

        # Git root без собственного marker и без selection fail-closed.
        assert_blocked(
            PROJECT_ROOT_SELECTION_REQUIRED,
            lambda: resolve_project_context(start=repo, env={}),
        )

        # Invalid explicit root не fallback-ится к nearest valid member.
        invalid = repo / "invalid"
        invalid.mkdir()
        assert_blocked(
            PROJECT_ROOT_INVALID,
            lambda: resolve_project_context(
                start=web,
                explicit_root=invalid,
                env={},
            ),
        )

        # Invalid nearest marker также не должен silently выбрать parent project.
        nested = single / "nested"
        nested.mkdir()
        invalid_marker = nested / ".harness" / "manifest.yaml"
        invalid_marker.parent.mkdir(parents=True)
        invalid_marker.write_text(
            'harness:\n  version: "1"\n',
            encoding="utf-8",
            newline="\n",
        )
        assert_blocked(
            PROJECT_ROOT_INVALID,
            lambda: resolve_project_context(start=nested, env={}),
        )

        # Project-local artifacts не выходят за selected project.
        assert (
            resolve_project_local_path(web, "planning/tasks")
            == web / "planning" / "tasks"
        )
        assert_blocked(
            PROJECT_PATH_ESCAPE,
            lambda: resolve_project_local_path(web, "../api"),
        )

        # Shared product code внутри gitRoot допустим.
        shared_target = resolve_product_mutation_path(
            project_root=web,
            git_root=repo,
            value="../../packages/shared/component.ts",
        )
        assert shared_target == shared / "component.ts"

        # Но sibling Harness member mutation запрещён.
        assert_blocked(
            SIBLING_PROJECT_MUTATION_FORBIDDEN,
            lambda: resolve_product_mutation_path(
                project_root=web,
                git_root=repo,
                value="../../services/api/src/main.py",
            ),
        )

        # И выход за общий Git worktree также запрещён.
        assert_blocked(
            PROJECT_PATH_ESCAPE,
            lambda: resolve_product_mutation_path(
                project_root=web,
                git_root=repo,
                value="../../../outside.txt",
            ),
        )

        # Symlink escape из project-local surface должен быть заблокирован.
        outside = base / "outside"
        outside.mkdir()
        link = web / "escape-link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass
        else:
            assert_blocked(
                PROJECT_PATH_ESCAPE,
                lambda: resolve_project_local_path(web, "escape-link/file.txt"),
            )

        # Case-insensitive comparator отдельно проверяется на Linux CI.
        assert is_within(
            Path("/Repo/Apps/Web"),
            Path("/repo"),
            case_sensitive=False,
        )

        # Explicit root из другого worktree не может подменить selected repo.
        other = base / "other"
        other.mkdir()
        run(other, "git", "init")
        foreign = other / "member"
        foreign.mkdir()
        write_manifest(foreign, name="foreign")
        assert_blocked(
            PROJECT_ROOT_OUTSIDE_GIT_WORKTREE,
            lambda: resolve_project_context(
                start=web,
                explicit_root=foreign,
                env={},
            ),
        )

    print("PROJECT CONTEXT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
