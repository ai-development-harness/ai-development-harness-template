#!/usr/bin/env python3
"""#295: transitive stale completion evidence and runtime-neutral Verify guards.

Регрессия использует реальные canonical REQ/STEP snapshots и подменяет только
исторический REVIEW storage. Это проверяет dependency freshness независимо
от git history/LLM, не создавая фиктивные «новые» завершения.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
from unittest.mock import patch

from planning_contract import (
    dependency_completion_basis,
    planning_context_basis,
    step_completion_proof,
)
from verification import verification_context_basis, verification_dependency_facts


MANIFEST = """execution:
  verificationCommandTimeoutSeconds: 300
sources:
  requirements: docs/requirements
  adrDirectory: docs/adr
  openQuestions: docs/open-questions
  principles: docs/principles
  architecture: docs/architecture.md
protocol:
  taskDirectory: planning/tasks
  reviewDirectory: planning/reviews
"""


def write(root: Path, rel: str, value: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def requirement(step_id: str, req_id: str) -> str:
    return f"""---
schema: 1
id: {req_id}
source: fixture
priority: medium
steps:
  - {step_id}
adrs: []
---

# {req_id} — Completion fixture

## Requirement

Implement {step_id} with approved behavior.

## Rationale

Dependency test.

## Acceptance

- Behavior remains correct.
"""


def step(step_id: str, req_id: str, dependency: str | None = None) -> str:
    deps = "depends_on: []" if dependency is None else f"depends_on:\n  - {dependency}"
    return f"""---
schema: 1
id: {step_id}
status: completed
type: implementation
priority: medium
phase: P1
{deps}
requirements:
  - {req_id}
adrs: []
architecture_refs: []
risk_flags:
  - none
plan:
  status: not_planned
  revision: 0
  context_basis: null
  content_hash: null
  reviewed_report: null
  planned_at: null
---

# {step_id} — Dependency fixture

## Goal

Deliver {step_id}.

## Context

Fixture.

## Scope

- Implement.

## Mutation policy

### Allowed

- src/

### Conditional

- none

### Forbidden

- unrelated

## Out of scope

- Other work.

## Acceptance criteria

- Deliver stable behavior.

## Verification

- manual: verify feature

## Deliverables

- Implementation.

## Implementation plan

- Implementation done.

## Evidence

- Verified by independent review.

## Blocker / Failure reason

—
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-dependency-enforcement-") as tmp:
        root = Path(tmp)
        write(root, ".harness/manifest.yaml", MANIFEST)
        for number in range(1, 4):
            step_id, req_id = f"STEP-{number:03d}", f"REQ-{number:03d}"
            write(root, f"docs/requirements/{req_id}-fixture.md",
                  requirement(step_id, req_id))
            write(root, f"planning/tasks/{step_id}.md",
                  step(step_id, req_id, "STEP-001" if number == 2 else None))
            write(root, f"planning/reviews/{step_id}/REVIEW-proof.md",
                  "Immutable historical evidence.\n")

        basis = {
            f"STEP-{n:03d}": planning_context_basis(root, f"STEP-{n:03d}")
            for n in range(1, 4)
        }

        # Только snapshot из настоящего REVIEW, а не изменяемый current state,
        # может подтвердить повторную проверку downstream after upstream re-plan.
        dependency_review_basis: str | None = None
        review_paths = {
            f"STEP-{n:03d}": root / f"planning/reviews/STEP-{n:03d}/REVIEW-proof.md"
            for n in range(1, 4)
        }

        def trusted(_root: Path, step_id: str, **_kwargs):
            meta = {"contract_basis": basis[step_id]}
            if step_id == "STEP-002" and dependency_review_basis is not None:
                meta["dependency_completion_basis"] = dependency_review_basis
            return {
                "path": review_paths[step_id],
                "verdict": "PASS",
                "document": {"frontmatter": meta},
            }

        with patch("review_contract.latest_trusted_review", side_effect=trusted):
            dependency_review_basis = dependency_completion_basis(root, "STEP-002")
            assert dependency_review_basis is not None
            for number in range(1, 4):
                assert step_completion_proof(root, f"STEP-{number:03d}")["complete"]

            before_dependency = verification_context_basis(root, "STEP-002")
            before_unrelated = verification_context_basis(root, "STEP-003")

            # Уточнение REQ-001 не меняет STEP-001 contract напрямую.
            # Однако его REVIEW был сделан для предыдущей семантики и
            # уже не может быть current completion proof для STEP-002.
            req = root / "docs/requirements/REQ-001-fixture.md"
            old = req.read_text(encoding="utf-8")
            req.write_text(
                old.replace("approved behavior", "revised required behavior"),
                encoding="utf-8", newline="\n",
            )
            direct = step_completion_proof(root, "STEP-001")
            assert not direct["complete"], direct
            assert "completion-contract-stale:STEP-001" in direct["reasons"], direct

            downstream = step_completion_proof(root, "STEP-002")
            assert not downstream["complete"], downstream
            assert any("dependency-incomplete:STEP-001" in value
                       for value in downstream["reasons"]), downstream
            facts = verification_dependency_facts(root, "STEP-002")
            assert len(facts) == 1 and facts[0]["complete"] is False, facts
            assert verification_context_basis(root, "STEP-002") != before_dependency
            assert verification_context_basis(root, "STEP-003") == before_unrelated
            assert step_completion_proof(root, "STEP-003")["complete"]

            # После новой upstream Verification/REVIEW прежний downstream PASS
            # не должен снова стать valid. Его immutable REVIEW помнит старый
            # dependency completion basis, даже если upstream снова complete.
            first_review_basis = basis["STEP-001"]
            first_review_path = review_paths["STEP-001"]
            basis["STEP-001"] = planning_context_basis(root, "STEP-001")
            new_report = root / "planning/reviews/STEP-001/REVIEW-new-approval.md"
            write(root, "planning/reviews/STEP-001/REVIEW-new-approval.md",
                  "New independent REVIEW of revised REQ-001.\n")
            review_paths["STEP-001"] = new_report
            assert step_completion_proof(root, "STEP-001")["complete"]
            old_child = step_completion_proof(root, "STEP-002")
            assert not old_child["complete"], old_child
            assert "completion-dependency-proof-stale:STEP-002" in old_child["reasons"], old_child

            # Независимый REVIEW downstream вправе связаться с новым proof.
            dependency_review_basis = dependency_completion_basis(root, "STEP-002")
            assert dependency_review_basis is not None
            assert step_completion_proof(root, "STEP-002")["complete"]

            # Вернуть исторические proof snapshots для следующих сценариев.
            basis["STEP-001"] = first_review_basis
            review_paths["STEP-001"] = first_review_path
            req.write_text(old, encoding="utf-8", newline="\n")
            dependency_review_basis = dependency_completion_basis(root, "STEP-002")

            # Изменение обратной traceability metadata не меняет semantic
            # contract: связанный STEP не инвалидируется без основания.
            req.write_text(old, encoding="utf-8", newline="\n")
            assert step_completion_proof(root, "STEP-001")["complete"]
            assert verification_context_basis(root, "STEP-002") == before_dependency

            # Известные cycles никогда не становятся доказанным completion.
            first = root / "planning/tasks/STEP-001.md"
            first.write_text(
                first.read_text(encoding="utf-8").replace(
                    "depends_on: []", "depends_on:\n  - STEP-002", 1,
                ),
                encoding="utf-8", newline="\n",
            )
            cyclic = step_completion_proof(root, "STEP-002")
            assert not cyclic["complete"], cyclic
            assert "dependency-cycle:" in str(cyclic["reasons"]), cyclic
            assert step_completion_proof(root, "STEP-003")["complete"]

            # Missing upstream STEP не должен давать ложный completion PASS
            # и не должен затрагивать несвязанный STEP-003.
            first.write_text(
                first.read_text(encoding="utf-8").replace(
                    "depends_on:\n  - STEP-002", "depends_on: []", 1,
                ),
                encoding="utf-8", newline="\n",
            )
            second = root / "planning/tasks/STEP-002.md"
            second.write_text(
                second.read_text(encoding="utf-8").replace(
                    "  - STEP-001", "  - STEP-999", 1,
                ),
                encoding="utf-8", newline="\n",
            )
            missing = step_completion_proof(root, "STEP-002")
            assert not missing["complete"], missing
            assert "dependency-unprovable:STEP-999" in str(missing["reasons"]), missing
            assert step_completion_proof(root, "STEP-003")["complete"]

    print("DEPENDENCY EVIDENCE ENFORCEMENT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
