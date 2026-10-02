#!/usr/bin/env python3
"""Regressions for Project Principles contract."""
from __future__ import annotations
from pathlib import Path
import tempfile
from document_contract import stable_hash
from principles import active_blocking_principles, validate_principles

MANIFEST="""sources:
  principles: docs/principles
"""

def write(root: Path, name: str, body: str) -> None:
    path=root/"docs"/"principles"/name
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(body,encoding="utf-8")

def principle(prn: str, *, status: str="active", severity: str="blocking", superseded_by: str="null") -> str:
    return f"""---
schema: 1
id: {prn}
status: {status}
severity: {severity}
scope: project
superseded_by: {superseded_by}
requirements: []
adrs: []
---

# {prn} — Test principle

## Rule

Public contract changes preserve backward compatibility.

## Rationale

Future steps must not silently break consumers.

## Applies to

Project-wide public contracts.

## Exceptions / approved deviation

Only explicit reviewed deviation.
"""

def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        (root/".harness").mkdir()
        (root/".harness"/"manifest.yaml").write_text(MANIFEST,encoding="utf-8")
        write(root,"PRN-001-compat.md",principle("PRN-001"))
        assert validate_principles(root)==[]
        first=stable_hash(active_blocking_principles(root))
        write(root,"PRN-001-compat.md",principle("PRN-001").replace("backward compatibility","one-release backward compatibility"))
        second=stable_hash(active_blocking_principles(root))
        assert first != second
        write(root,"PRN-002-advisory.md",principle("PRN-002",severity="advisory"))
        assert "PRN-002" not in active_blocking_principles(root)
        write(root,"PRN-003-old.md",principle("PRN-003",status="superseded",superseded_by="PRN-999"))
        assert any("superseding principle does not exist" in e for e in validate_principles(root))
    print("project-principles self-test: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
