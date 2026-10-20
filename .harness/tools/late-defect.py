#!/usr/bin/env python3
"""Register an immutable user-observed defect after independent REVIEW PASS."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from late_defect import ObservationError, read, record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--source-step", required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("record")
    add.add_argument("--criterion", required=True)
    add.add_argument("--given", required=True)
    add.add_argument("--when", required=True)
    add.add_argument("--expected", required=True)
    add.add_argument("--observed", required=True)
    add.add_argument("--evidence-path", required=True)
    add.add_argument("--invalidate-check", action="append", required=True)
    check = sub.add_parser("check")
    check.add_argument("--path", required=True)
    args = parser.parse_args()
    try:
        if args.action == "record":
            result = record(
                args.root, args.source_step, criterion=args.criterion,
                given=args.given, when=args.when, expected=args.expected,
                observed=args.observed, evidence_path=args.evidence_path,
                invalidated_checks=args.invalidate_check,
            )
        else:
            result = {
                "status": "PASS",
                "observation": read(args.root, args.source_step, args.path),
            }
    except (OSError, ValueError, ObservationError) as exc:
        result = {"status": "BLOCKED", "reasonCode": "LATE_DEFECT_UNPROVEN",
                  "message": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
