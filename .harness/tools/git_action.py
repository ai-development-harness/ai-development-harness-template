#!/usr/bin/env python3
"""Deterministic executor безопасных Git mutations после preflight.

Semantic inputs остаются у модели/пользователя: staging scope, commit type,
commit message и PR prose. После этого mechanical mutation выполняет этот tool:
он повторно запускает canonical preflight, исполняет только разрешённый argv и
проверяет postcondition.

GIT PR creation намеренно не входит в executor: provider action пока остаётся
отдельной trust boundary с semantic title/body и provider state.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from harness_config import ConfigError
from git_preflight import (
    GitPreflightError,
    PR_STATE_PATH,
    Repo,
    commit_preflight,
    pr_finish_preflight,
    push_preflight,
    sync_preflight,
)


class GitActionError(RuntimeError):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.details = details


def _run(root: Path, argv: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        argv,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode:
        raise GitActionError(
            "MUTATION_FAILED",
            proc.stderr.strip() or proc.stdout.strip() or "Git mutation failed",
            argv=argv,
            exitCode=proc.returncode,
        )
    return proc


def _message_path(root: Path, value: Path) -> Path:
    path = value if value.is_absolute() else root / value
    path = path.resolve()
    allowed = (root / ".harness/local/git").resolve()
    try:
        path.relative_to(allowed)
    except ValueError as exc:
        raise GitActionError(
            "COMMIT_MESSAGE_PATH_BLOCKED",
            "commit message file must stay under .harness/local/git/",
        ) from exc
    if not path.is_file():
        raise GitActionError("COMMIT_MESSAGE_MISSING", f"commit message file not found: {path}")
    return path


def _validate_commit_message(
    message: str,
    *,
    commit_type: str,
    gate: dict[str, Any],
) -> None:
    lines = message.splitlines()
    subject = lines[0].strip() if lines else ""
    checks = gate.get("semanticChecks", {})
    limit = checks.get("subjectMaxLength")
    if not subject:
        raise GitActionError("COMMIT_MESSAGE_INVALID", "commit subject is empty")
    if isinstance(limit, int) and len(subject) > limit:
        raise GitActionError(
            "COMMIT_MESSAGE_INVALID",
            f"commit subject exceeds configured limit {limit}",
        )
    if checks.get("messageStyle") == "conventional":
        pattern = rf"^{re.escape(commit_type)}(?:\([^)]+\))?!?:\s+\S"
        if re.match(pattern, subject) is None:
            raise GitActionError(
                "COMMIT_MESSAGE_INVALID",
                f"subject must be Conventional Commit with type {commit_type}",
            )
    if checks.get("requireBody") and not any(line.strip() for line in lines[1:]):
        raise GitActionError("COMMIT_MESSAGE_INVALID", "commit body is required by policy")


def execute_commit(
    root: Path,
    *,
    commit_type: str,
    slug: str,
    message_file: Path,
) -> dict[str, Any]:
    """Создать commit; при exact protected-branch plan создать required branch."""
    repo = Repo(root)
    created_branch: str | None = None
    try:
        gate = commit_preflight(root, commit_type=commit_type, slug=slug)
    except GitPreflightError as exc:
        if exc.code != "PROTECTED_BRANCH_REQUIRES_NEW_BRANCH":
            raise
        required = exc.details.get("requiredBranch")
        if not isinstance(required, str) or not required:
            raise GitActionError(
                "REQUIRED_BRANCH_UNRESOLVED",
                "preflight requires branch creation but returned no exact branch",
            ) from exc
        exists = repo.git(
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{required}",
            check=False,
        )
        if exists.returncode == 0:
            raise GitActionError(
                "REQUIRED_BRANCH_EXISTS",
                f"required branch already exists: {required}",
            ) from exc
        _run(root, ["git", "switch", "-c", required])
        if Repo(root).branch() != required:
            raise GitActionError("BRANCH_POSTCONDITION_FAILED", "created branch is not current")
        created_branch = required
        gate = commit_preflight(root, commit_type=commit_type, slug=slug)

    path = _message_path(root, message_file)
    message = path.read_text(encoding="utf-8")
    _validate_commit_message(message, commit_type=commit_type, gate=gate)

    before = Repo(root).head()
    argv = ["git", "commit"]
    if gate.get("sign"):
        argv.append("-S")
    if gate.get("allowEmpty") and not gate.get("staged"):
        argv.append("--allow-empty")
    argv.extend(["-F", str(path)])
    _run(root, argv)
    after = Repo(root).head()
    if not after or after == before:
        raise GitActionError("COMMIT_POSTCONDITION_FAILED", "Git HEAD did not advance")

    path.unlink(missing_ok=True)
    return {
        "status": "SUCCESS",
        "action": "commit",
        "branch": Repo(root).branch(),
        "createdBranch": created_branch,
        "head": after,
        "mutation": {"argv": argv},
    }


def execute_push(root: Path) -> dict[str, Any]:
    gate = push_preflight(root)
    plan = gate.get("mutationPlan", {})
    argv = plan.get("argv")
    if not isinstance(argv, list) or argv[:2] != ["git", "push"]:
        raise GitActionError("UNSAFE_MUTATION_PLAN", "push preflight returned invalid argv")
    if any(str(item).startswith("--force") or item == "-f" for item in argv):
        raise GitActionError("UNSAFE_MUTATION_PLAN", "force push is forbidden")
    head = Repo(root).head()
    _run(root, [str(item) for item in argv])
    repo = Repo(root)
    remote_head = repo.remote_ref(str(gate["remote"]), str(gate["branch"]))
    if head is None or remote_head != head:
        raise GitActionError(
            "PUSH_POSTCONDITION_FAILED",
            "configured remote branch does not match local HEAD after push",
            localHead=head,
            remoteHead=remote_head,
        )
    return {
        "status": "SUCCESS",
        "action": "push",
        "branch": gate["branch"],
        "remote": gate["remote"],
        "head": head,
        "mutation": {"argv": argv},
    }


def execute_sync(root: Path) -> dict[str, Any]:
    gate = sync_preflight(root)
    plan = gate.get("mutationPlan", {})
    operation = plan.get("operation")
    if operation in {"report", "noop"}:
        return {
            "status": "SUCCESS",
            "action": "sync",
            "mutated": False,
            "branch": gate["branch"],
            "ahead": gate.get("ahead"),
            "behind": gate.get("behind"),
        }

    argv = plan.get("argv")
    expected_prefix = ["git", "merge", "--ff-only"]
    if not isinstance(argv, list) or argv[:3] != expected_prefix:
        raise GitActionError("UNSAFE_MUTATION_PLAN", "sync preflight returned non-ff-only argv")
    _run(root, [str(item) for item in argv])
    repo = Repo(root)
    head = repo.head()
    remote_head = repo.remote_ref(str(gate["remote"]), str(gate["branch"]))
    if head is None or remote_head != head:
        raise GitActionError(
            "SYNC_POSTCONDITION_FAILED",
            "local HEAD does not match configured remote after ff-only sync",
        )
    return {
        "status": "SUCCESS",
        "action": "sync",
        "mutated": True,
        "branch": gate["branch"],
        "head": head,
        "mutation": {"argv": argv},
    }


def execute_pr_finish(
    root: Path,
    *,
    pr_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gate = pr_finish_preflight(root, pr_data=pr_data)
    steps = gate.get("mutationPlan", {}).get("steps")
    if not isinstance(steps, list):
        raise GitActionError("UNSAFE_MUTATION_PLAN", "PR finish plan has no ordered steps")

    executed: list[dict[str, Any]] = []
    for step in steps:
        argv = step.get("argv") if isinstance(step, dict) else None
        if not isinstance(argv, list) or not argv or argv[0] != "git":
            raise GitActionError("UNSAFE_MUTATION_PLAN", "PR finish contains invalid argv")
        _run(root, [str(item) for item in argv])
        executed.append({"operation": step.get("operation"), "argv": argv})

    repo = Repo(root)
    if repo.branch() != gate["returnBranch"]:
        raise GitActionError(
            "PR_FINISH_POSTCONDITION_FAILED",
            "current branch does not match verified return branch",
        )
    removed = repo.git(
        "show-ref",
        "--verify",
        "--quiet",
        f"refs/heads/{gate['branch']}",
        check=False,
    )
    if removed.returncode == 0:
        raise GitActionError(
            "PR_FINISH_POSTCONDITION_FAILED",
            "verified PR head branch still exists locally",
        )

    state_file = gate.get("stateFile")
    if gate.get("deleteStateFileAfterSuccess") and isinstance(state_file, str):
        (root / state_file).unlink(missing_ok=True)

    return {
        "status": "SUCCESS",
        "action": "pr-finish",
        "pr": gate["pr"],
        "returnBranch": gate["returnBranch"],
        "executed": executed,
        "stateFileDeleted": bool(gate.get("deleteStateFileAfterSuccess")),
    }


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic Git mutation executor")
    parser.add_argument("action", choices=["commit", "push", "sync", "pr-finish"])
    parser.add_argument("--commit-type")
    parser.add_argument("--slug")
    parser.add_argument("--message-file", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = repo_root()

    try:
        if args.action == "commit":
            if not args.commit_type or not args.slug or args.message_file is None:
                raise GitActionError(
                    "COMMIT_INPUT_REQUIRED",
                    "commit requires --commit-type, --slug and --message-file",
                )
            result = execute_commit(
                root,
                commit_type=args.commit_type,
                slug=args.slug,
                message_file=args.message_file,
            )
        elif args.action == "push":
            result = execute_push(root)
        elif args.action == "sync":
            result = execute_sync(root)
        else:
            result = execute_pr_finish(root)
    except (GitActionError, GitPreflightError, ConfigError, OSError, UnicodeError) as exc:
        code = getattr(exc, "code", "CONFIG_OR_IO_ERROR")
        result = {
            "status": "BLOCKED",
            "action": args.action,
            "reasonCode": code,
            "message": str(exc),
        }
        details = getattr(exc, "details", None)
        if details:
            result["details"] = details
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        else:
            print(f"BLOCKED: {code}: {exc}")
        return 2

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"SUCCESS: {args.action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
