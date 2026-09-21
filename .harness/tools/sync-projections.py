#!/usr/bin/env python3
"""Пересобрать tracked project projections из canonical documents."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from projection_contract import validate_projections, write_projections


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]

    if args.check:
        errors = validate_projections(root)
        result = {"status": "PASS" if not errors else "DRIFT", "errors": errors}
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["status"])
            for item in errors:
                print(f"- {item}")
        return 0 if not errors else 1

    changed = write_projections(root)
    result = {"status": "UPDATED", "changed": changed}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("UPDATED")
        for item in changed:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
