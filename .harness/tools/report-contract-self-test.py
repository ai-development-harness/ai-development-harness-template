#!/usr/bin/env python3
"""Regression self-test durable operational report contracts."""
from __future__ import annotations

from pathlib import Path
import tempfile

from report_contract import (
    validate_all_operational_reports,
    validate_audit_report,
    validate_release_report,
    validate_skill_search_report,
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def manifest() -> str:
    return """skills:
  search:
    maxResults: 3
protocol:
  auditDirectory: work/audits
  releaseDirectory: work/releases
  skillSearchDirectory: work/skill-searches
"""


def valid_audit() -> str:
    return """---
schema: 1
kind: audit
scope: STEP-001
mode: audit
created_at: 2026-09-21T08:00:00+00:00
result: complete
---

# Audit — 2026-09-21

## Sources checked

- STEP-001

## Actual state

Observed.

## Drift / findings

None.

## Evidence

Checked.

## Corrective actions

- none
"""


def valid_release() -> str:
    return """---
schema: 1
kind: release_check
target: v1.0.0
verdict: ready
created_at: 2026-09-21T08:00:00+00:00
---

# Release Check — 2026-09-21

## Requirements / scope

REQ-001.

## Verification gates

PASS.

## Security / migrations / compatibility

Checked.

## Unresolved blockers

None.

## Evidence

Build/test PASS.
"""


def valid_search(count: int = 1) -> str:
    candidate = """### #1 — docker-skill

- Repository: owner/repo
- Path: skills/docker
- URL: https://github.com/owner/repo/tree/main/skills/docker
- Ref/commit inspected: abcdef
- License: MIT
- Why it fits: Docker workflow.
- Limitations: None found.
- Safety notes: Static inspection only.
- Recommendation: Suitable.
"""
    return f"""---
schema: 1
kind: skill_search
query: Docker workflow
status: complete
created_at: 2026-09-21T08:00:00+00:00
candidate_count: {count}
---

# SKILL SEARCH — 2026-09-21T080000Z

## Search strategy

GitHub source inspection.

## Ranking criteria

Relevance and safety.

## Candidates

{candidate}
## Rejected / notable alternatives

None.

## Next command

SKILL INSTALL: #1
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-report-contract-") as tmp:
        root = Path(tmp)
        write(root / ".harness/manifest.yaml", manifest())

        audit = root / "work/audits/AUDIT-20260921T080000Z.md"
        release = root / "work/releases/RELEASE-20260921T080000Z.md"
        search = root / "work/skill-searches/SKILL-SEARCH-20260921T080000Z.md"
        write(audit, valid_audit())
        write(release, valid_release())
        write(search, valid_search())

        errors = validate_all_operational_reports(root)
        assert not errors, errors

        write(search, valid_search(count=2))
        errors = validate_skill_search_report(root, search)
        assert any("contiguous #1..#candidate_count" in item for item in errors), errors
        write(search, valid_search())

        write(release, valid_release().replace("verdict: ready", "verdict: maybe"))
        errors = validate_release_report(root, release)
        assert any("verdict must be ready|blocked" in item for item in errors), errors
        write(release, valid_release())

        write(audit, valid_audit().replace("## Evidence\n\nChecked.\n", ""))
        errors = validate_audit_report(root, audit)
        assert any("Evidence" in item for item in errors), errors

    print("REPORT CONTRACT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
