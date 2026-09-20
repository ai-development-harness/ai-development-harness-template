#!/usr/bin/env python3
"""Regression self-test deterministic planning contract helpers.

Сценарии специально проверяют то, что не должно требовать reasoning-модели:
manifest-driven paths, transitive Plan basis, dependency cycles, missing refs и
OPEN question blocker для Ready plan.
"""
from __future__ import annotations

from pathlib import Path
import tempfile

from planning_contract import (
    planning_context_basis,
    task_path,
    validate_planning_contracts,
)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def task(
    *,
    step_id: str,
    depends: str = "—",
    req: str = "REQ-001",
    adr: str = "не требуется",
    status: str = "Запланировано",
    plan_status: str = "Not planned",
    plan_basis: str = "—",
) -> str:
    return f"""# {step_id} — Planning contract self-test

**Статус:** {status}
**Type:** IMPLEMENTATION
**Приоритет:** Средний
**Фаза:** Test
**Depends on:** {depends}

## Requirements

- {req}

## ADR

- {adr}

## Risk flags

- none

## Goal

Проверить planning contract.

## Context

Self-test.

## Scope

- deterministic checks.

## Mutation policy

### Allowed

- fixture

### Conditional

- —

### Forbidden

- unrelated

## Out of scope

- unrelated.

## Acceptance criteria

- validator сообщает точный результат.

## Verification

- planning-contract-self-test.py.

## Deliverables

- fixture.

## Implementation plan

**Plan status:** {plan_status}
**Plan revision:** 1
**Plan basis:** {plan_basis}
**Planned at:** 2026-09-20T00:00:00+00:00

1. fixture

## Evidence

—

## Review status

**Latest verdict:** NOT REVIEWED
**Latest report:** —

## Blocker / Failure reason

—
"""


def requirement(extra: str = "") -> str:
    return f"""# REQ-001 — Planning contract

## Requirement

Plan учитывает upstream contract. {extra}

## Rationale

Self-test.

## Acceptance

Fingerprint меняется при изменении requirement.

## Traceability

STEP-001
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="harness-planning-contract-") as tmp:
        root = Path(tmp)
        write(
            root / ".harness/manifest.yaml",
            """execution:
  maxFixReviewCycles: 2
sources:
  requirements: spec/requirements
  architecture: spec/architecture.md
protocol:
  taskDirectory: work/tasks
  reviewDirectory: work/reviews
""",
        )
        write(root / "spec/requirements/REQ-001-contract.md", requirement())
        write(root / "spec/architecture.md", "# Architecture\n\nBaseline A.\n")
        write(root / "work/tasks/STEP-001.md", task(step_id="STEP-001"))

        # 1. Manifest path обязан быть source of truth; hard-coded planning/tasks
        # здесь не существует.
        resolved = task_path(root, "STEP-001")
        assert resolved == root / "work/tasks/STEP-001.md", resolved

        # 2. Linked REQ и architecture входят в transitive Plan basis.
        basis_a = planning_context_basis(root, "STEP-001")
        write(root / "spec/requirements/REQ-001-contract.md", requirement("Изменено."))
        basis_b = planning_context_basis(root, "STEP-001")
        assert basis_a != basis_b, (basis_a, basis_b)

        write(root / "spec/architecture.md", "# Architecture\n\nBaseline B.\n")
        basis_c = planning_context_basis(root, "STEP-001")
        assert basis_b != basis_c, (basis_b, basis_c)

        # 3. Dependency contract тоже upstream input.
        write(
            root / "work/tasks/STEP-002.md",
            task(step_id="STEP-002", req="REQ-001", status="Выполнено"),
        )
        write(
            root / "work/tasks/STEP-001.md",
            task(step_id="STEP-001", depends="STEP-002"),
        )
        basis_d = planning_context_basis(root, "STEP-001")
        dep_text = (root / "work/tasks/STEP-002.md").read_text(encoding="utf-8")
        dep_text = dep_text.replace("Проверить planning contract.", "Проверить изменённый dependency contract.")
        write(root / "work/tasks/STEP-002.md", dep_text)
        basis_e = planning_context_basis(root, "STEP-001")
        assert basis_d != basis_e, (basis_d, basis_e)

        # 4. Ready plan с точным basis проходит static validator.
        write(
            root / "work/tasks/STEP-001.md",
            task(step_id="STEP-001", depends="STEP-002"),
        )
        ready_basis = planning_context_basis(root, "STEP-001")
        write(
            root / "work/tasks/STEP-001.md",
            task(
                step_id="STEP-001",
                depends="STEP-002",
                plan_status="Ready",
                plan_basis=ready_basis,
            ),
        )
        assert validate_planning_contracts(root) == [], validate_planning_contracts(root)

        # 5. Изменение REQ после planning делает Ready plan stale.
        write(root / "spec/requirements/REQ-001-contract.md", requirement("После planning."))
        errors = validate_planning_contracts(root)
        assert any("Ready plan is stale" in item for item in errors), errors

        # Вернуть актуальный basis перед следующими независимыми checks.
        current_basis = planning_context_basis(root, "STEP-001")
        write(
            root / "work/tasks/STEP-001.md",
            task(
                step_id="STEP-001",
                depends="STEP-002",
                plan_status="Ready",
                plan_basis=current_basis,
            ),
        )

        # 6. Ready plan не может зависеть от незавершённого STEP.
        dep_text = (root / "work/tasks/STEP-002.md").read_text(encoding="utf-8")
        write(
            root / "work/tasks/STEP-002.md",
            dep_text.replace("**Статус:** Выполнено", "**Статус:** В работе"),
        )
        errors = validate_planning_contracts(root)
        assert any("incomplete dependency STEP-002" in item for item in errors), errors
        write(root / "work/tasks/STEP-002.md", dep_text)

        # 7. Linked ADR обязан быть Accepted до Ready.
        write(
            root / "docs/adr/ADR-001-test.md",
            """# ADR-001 — Test decision

**Status:** Proposed

## Context
self-test
""",
        )
        write(
            root / "work/tasks/STEP-001.md",
            task(
                step_id="STEP-001",
                depends="STEP-002",
                adr="ADR-001",
            ),
        )
        adr_basis = planning_context_basis(root, "STEP-001")
        write(
            root / "work/tasks/STEP-001.md",
            task(
                step_id="STEP-001",
                depends="STEP-002",
                adr="ADR-001",
                plan_status="Ready",
                plan_basis=adr_basis,
            ),
        )
        errors = validate_planning_contracts(root)
        assert any("non-Accepted ADR-001" in item for item in errors), errors
        adr_text = (root / "docs/adr/ADR-001-test.md").read_text(encoding="utf-8")
        write(
            root / "docs/adr/ADR-001-test.md",
            adr_text.replace("**Status:** Proposed", "**Status:** Accepted"),
        )
        accepted_basis = planning_context_basis(root, "STEP-001")
        write(
            root / "work/tasks/STEP-001.md",
            task(
                step_id="STEP-001",
                depends="STEP-002",
                adr="ADR-001",
                plan_status="Ready",
                plan_basis=accepted_basis,
            ),
        )
        assert validate_planning_contracts(root) == [], validate_planning_contracts(root)

        # 8. OPEN question, влияющий на STEP/linked REQ, не совместим с Ready.
        write(
            root / "docs/OPEN_QUESTIONS.md",
            """# Open Questions

## OQ-001 — Нужен выбор
Status: OPEN
Affects: REQ-001, STEP-001
Context: self-test
Decision needed: choose
Resolution: —
""",
        )
        errors = validate_planning_contracts(root)
        assert any("blocked by OQ-001" in item for item in errors), errors

        # 9. Dependency cycle ловится без модели.
        (root / "docs/OPEN_QUESTIONS.md").unlink()
        step2 = (root / "work/tasks/STEP-002.md").read_text(encoding="utf-8")
        step2 = step2.replace("**Depends on:** —", "**Depends on:** STEP-001")
        write(root / "work/tasks/STEP-002.md", step2)
        errors = validate_planning_contracts(root)
        assert any("dependency cycle" in item for item in errors), errors

        # 10. Missing canonical REQ — deterministic contract failure.
        (root / "spec/requirements/REQ-001-contract.md").unlink()
        errors = validate_planning_contracts(root)
        assert any("expected exactly one canonical requirement file" in item for item in errors), errors

    print("PLANNING CONTRACT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
