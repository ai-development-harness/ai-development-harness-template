#!/usr/bin/env python3
"""Regression self-test stateful deterministic command dispatcher."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from command_dispatch import (
    complete_dispatch,
    route_command,
    start_dispatch,
)
from command_transitions import load_transition_table, validate_transition_table
from execution_status import load_status


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def run(root: Path, *args: str) -> None:
    proc = subprocess.run(
        args,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} failed ({proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )


def copy_tracked(target: Path) -> None:
    raw = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=SOURCE_ROOT,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout
    for token in raw.split(b"\0"):
        if not token:
            continue
        rel = token.decode("utf-8")
        source = SOURCE_ROOT / rel
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    run(target, "git", "init", "-q", "-b", "main")
    run(target, "git", "config", "user.email", "dispatcher@example.invalid")
    run(target, "git", "config", "user.name", "Dispatcher Test")
    run(target, "git", "add", ".")
    run(target, "git", "commit", "-qm", "fixture")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-dispatcher-") as tmp:
        root = Path(tmp)
        copy_tracked(root)

        # CTS является единственным routing registry: semantic route и
        # phase-specific context metadata получаются без чтения skill prose.
        plan_route = route_command(root, "STEP PLAN STEP-123")
        assert plan_route["dispatch"] == {
            "kind": "semantic",
            "skill": "plan-step",
            "contextPhase": "plan",
        }, plan_route

        # Удалённый dispatch metadata должен ломать graph fail-closed.
        table = load_transition_table(root)
        del table["domains"]["STEP"]["commands"]["PLAN"]["dispatch"]
        errors = validate_transition_table(table)
        assert any(
            "STEP.PLAN.dispatch must be an object" in item
            for item in errors
        ), errors

        # Read-only deterministic command исполняется самим dispatcher и
        # завершает execution без semantic handoff.
        help_result = start_dispatch(root, "HARNESS HELP")
        assert help_result["status"] == "DONE", help_result
        assert help_result["result"]["status"] == "PASS", help_result
        assert any(
            item["domain"] == "STEP"
            for item in help_result["result"]["domains"]
        ), help_result

        # Structural FAIL ничего не записывает в execution state.
        before = len(load_status(root)["executions"])
        invalid = start_dispatch(root, "GIT PR > COMMIT")
        after = len(load_status(root)["executions"])
        assert invalid["status"] == "BLOCKED", invalid
        assert invalid["reasonCode"] == "INVALID_CHAIN", invalid
        assert before == after, (before, after)

        # Semantic command возвращает только exact skill handoff.
        quick = start_dispatch(root, "PROJECT QUICK FIX: исправить опечатку")
        assert quick["status"] == "SEMANTIC", quick
        assert quick["skill"] == "quick-fix", quick
        assert quick["skillPath"] == ".agents/skills/quick-fix/SKILL.md", quick
        assert quick["commandData"]["input"] == "исправить опечатку", quick
        done = complete_dispatch(
            root,
            quick["rootCommand"],
            quick["command"],
            "SUCCESS",
        )
        assert done["status"] == "DONE", done

        # Chain continuation больше не требует ручного resolve/begin/routing:
        # completion первого semantic node сразу возвращает следующий handoff.
        chain = start_dispatch(root, "GIT CHECK > COMMIT")
        assert chain["status"] == "SEMANTIC", chain
        assert chain["command"] == "GIT CHECK", chain
        assert chain["skill"] == "git-workflow", chain

        next_node = complete_dispatch(
            root,
            chain["rootCommand"],
            chain["command"],
            "PASS",
        )
        assert next_node["status"] == "SEMANTIC", next_node
        assert next_node["command"] == "GIT COMMIT", next_node
        assert next_node["skill"] == "git-workflow", next_node

        chain_done = complete_dispatch(
            root,
            next_node["rootCommand"],
            next_node["command"],
            "SUCCESS",
        )
        assert chain_done["status"] == "DONE", chain_done

        # HARNESS RESUME не создаёт отдельную root execution и возвращает
        # semantic handoff существующей interrupted command.
        interrupted = start_dispatch(root, "PROJECT QUICK FIX: resume test")
        assert interrupted["status"] == "SEMANTIC", interrupted
        count_before_resume = len(load_status(root)["executions"])
        resumed = start_dispatch(root, "HARNESS RESUME")
        count_after_resume = len(load_status(root)["executions"])
        assert resumed["status"] == "SEMANTIC", resumed
        assert resumed["rootCommand"] == interrupted["rootCommand"], resumed
        assert resumed["command"] == interrupted["command"], resumed
        assert count_before_resume == count_after_resume
        complete_dispatch(
            root,
            resumed["rootCommand"],
            resumed["command"],
            "SUCCESS",
        )

    print("COMMAND DISPATCH SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
