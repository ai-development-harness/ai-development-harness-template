#!/usr/bin/env python3
"""Проверить live project docs на устаревшие Harness command references."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from command_references import project_live_document_paths, scan_files


def repo_root() -> Path:
    here = Path(__file__).resolve()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=here.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        proc = None
    if proc is not None and proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return here.parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect deprecated pre-namespace Harness commands in live project documents."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    args = parser.parse_args()

    root = repo_root()
    try:
        findings = scan_files(root, project_live_document_paths(root))
    except RuntimeError as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "status": "BLOCKED",
                        "scope": "live-project-documents",
                        "error": str(exc),
                        "findings": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"COMMAND REFERENCE CHECK: BLOCKED — {exc}")
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "status": "PASS" if not findings else "DRIFT",
                    "scope": "live-project-documents",
                    "findings": [
                        {
                            "path": item.path,
                            "line": item.line,
                            "legacy": item.legacy,
                            "canonical": item.canonical,
                            "excerpt": item.excerpt,
                        }
                        for item in findings
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif findings:
        print("COMMAND REFERENCE CHECK: DRIFT")
        for item in findings:
            print(
                f"  - {item.path}:{item.line}: "
                f"{item.legacy} -> {item.canonical} | {item.excerpt}"
            )
    else:
        print("COMMAND REFERENCE CHECK: PASS")

    # DRIFT — валидный audit result для PROJECT RECONCILE, а не tool failure.
    # Ненулевой код зарезервирован для BLOCKED/ошибки выполнения checker.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
