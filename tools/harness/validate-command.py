#!/usr/bin/env python3
"""Validate canonical Harness command/chain before skill routing or execution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from command_transitions import load_transition_table, validate_command_text


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Harness command syntax and structural transition graph."
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Canonical command string. Quote chains in the shell.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    raw = " ".join(args.command).strip()
    if raw.startswith("-- "):
        raw = raw[3:].strip()

    table = load_transition_table(repo_root())
    result = validate_command_text(raw, table)

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["valid"]:
        print(result["code"])
        for value in result["normalized"]:
            print(f"  - {value}")
        for edge in result.get("transitions", []):
            print(
                "  -> "
                + edge["to"]
                + " [on="
                + "/".join(edge["onPreviousResult"])
                + "; pre="
                + (", ".join(edge["runtimePreconditions"]) or "none")
                + "]"
            )
    else:
        print(f"{result['code']}: {result['message']}", file=sys.stderr)

    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
