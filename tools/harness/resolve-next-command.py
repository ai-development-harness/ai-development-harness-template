#!/usr/bin/env python3
"""Resolve the next STEP command after normal progress or interrupted execution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from execution_recovery import active_recovery_candidates, resolve_step


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministically resolve restart-safe STEP continuation."
    )
    parser.add_argument("step_id", nargs="?")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    root = repo_root()
    value = (
        resolve_step(root, args.step_id)
        if args.step_id
        else {
            "status": "ACTIVE_EXECUTIONS",
            "candidates": active_recovery_candidates(root),
        }
    )

    if args.as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif args.step_id:
        print(value["status"])
        if value.get("command"):
            print(value["command"])
        print(value["reasonCode"])
    else:
        for item in value["candidates"]:
            command = item.get("command") or "—"
            print(f"{item['stepId']}: {item['status']} -> {command} ({item['reasonCode']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
