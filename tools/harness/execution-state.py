#!/usr/bin/env python3
"""Manage crash-safe local Harness execution cursors."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from execution_recovery import (
    begin_phase,
    complete_phase,
    contract_basis,
    finish_execution,
    load_execution_state,
    stamp_plan,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage local restart-safe Harness execution state."
    )
    sub = parser.add_subparsers(dest="action", required=True)

    begin = sub.add_parser("begin")
    begin.add_argument("step_id")
    begin.add_argument("--command", required=True)
    begin.add_argument("--root-command")

    complete = sub.add_parser("complete")
    complete.add_argument("step_id")
    complete.add_argument("--command", required=True)
    complete.add_argument(
        "--result",
        required=True,
        choices=["SUCCESS", "PASS", "FAIL", "BLOCKED"],
    )

    finish = sub.add_parser("finish")
    finish.add_argument("step_id")
    finish.add_argument(
        "--status",
        required=True,
        choices=["completed", "blocked"],
    )

    show = sub.add_parser("show")
    show.add_argument("step_id")

    basis = sub.add_parser("plan-basis")
    basis.add_argument("step_id")

    stamp = sub.add_parser("stamp-plan")
    stamp.add_argument("step_id")

    args = parser.parse_args()
    root = repo_root()

    if args.action == "begin":
        emit(
            begin_phase(
                root,
                args.step_id,
                args.command,
                root_command=args.root_command,
            )
        )
    elif args.action == "complete":
        emit(
            complete_phase(
                root,
                args.step_id,
                args.command,
                result=args.result,
            )
        )
    elif args.action == "finish":
        emit(finish_execution(root, args.step_id, status=args.status))
    elif args.action == "show":
        emit(load_execution_state(root, args.step_id))
    elif args.action == "plan-basis":
        print(contract_basis(root, args.step_id))
    elif args.action == "stamp-plan":
        emit(stamp_plan(root, args.step_id))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
