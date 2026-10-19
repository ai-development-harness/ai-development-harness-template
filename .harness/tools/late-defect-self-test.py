#!/usr/bin/env python3
"""Synthetic late-defect preservation and completed-STEP verification reuse."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from completion_gate import acceptance_criteria
from late_defect import ObservationError, read, record
from verification import run_step_verification, verification_freshness


def fixture_api() -> dict:
    spec = importlib.util.spec_from_file_location(
        "verification_original_fixture", Path(__file__).with_name("verification-self-test.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return vars(module)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    fx = fixture_api()
    with tempfile.TemporaryDirectory(prefix="harness-late-defect-") as folder:
        root = Path(folder)
        fx["prepare"](root)
        source = root / "planning/tasks/STEP-001.md"
        ui = 'python3 -c "print(101)"'
        backend = 'python3 -c "print(202)"'
        verification_text = (
            fx["command_line"](ui) + "\n" + fx["command_line"](backend)
            + "\n- manual: Проверить доступное имя кнопки"
        )
        write(source, fx["task"](verification_text))
        manifest = root / ".harness/manifest.yaml"
        write(manifest, manifest.read_text(encoding="utf-8")
              + "\nverification:\n  impactMap: docs/verification/impact-map.json\n")
        write(root / "src/ui/Button.tsx", "export const label = 'Button';\n")
        write(root / "src/backend/service.py", "print('backend')\n")
        criteria = acceptance_criteria(root, "STEP-001")
        checks = [
            {"id": "ui", "command": ui, "inputs": ["src/ui/**"],
             "dependsOn": [], "acceptance": criteria, "reusable": True},
            {"id": "backend", "command": backend, "inputs": ["src/backend/**"],
             "dependsOn": [], "acceptance": criteria, "reusable": True},
        ]
        infrastructure = [".harness/manifest.yaml", "docs/verification/**"]
        policy = {"schemaVersion": 1, "steps": {
            "STEP-001": {"checks": checks, "infrastructure": infrastructure},
        }}
        map_path = root / "docs/verification/impact-map.json"
        write(map_path, json.dumps(policy))
        initial = run_step_verification(
            root, "STEP-001", manual_results=[{
                "check": "Проверить доступное имя кнопки",
                "status": "PASS", "observed": "Accessible UI passed.",
            }],
        )
        assert initial["status"] == "PASS", initial
        source_cache = root / ".harness/local/verification-incremental/STEP-001.json"
        assert source_cache.is_file()
        review_rel = "planning/reviews/STEP-001/REVIEW-20261019T080000Z.md"
        review_path = root / review_rel
        write(review_path, "Trusted independent original REVIEW fixture.\n")
        source_original = source.read_text(encoding="utf-8")
        write(source, source_original.replace("status: in_progress", "status: completed", 1))
        accepted_bytes = source.read_bytes()
        review_bytes = review_path.read_bytes()
        original_source = {"review": review_rel,
                           "reviewSha256": "sha256:accepted-review-fixture",
                           "evidenceSha256": "sha256:verified-evidence-fixture"}
        # Only the accepted REVIEW origin is stubbed: actual old Verification
        # Evidence, Git trees, cached checks and current subject are real.
        with patch("late_defect._origin", return_value=original_source):
            outcome = record(
                root, "STEP-001", criterion=criteria[0],
                given="The button is rendered", when="A screen reader queries name",
                expected="Accessible name exists",
                observed="Accessible name is missing",
                evidence_path="docs/architecture.md",
                invalidated_checks=["ui"],
            )
            obs_rel = outcome["path"]
            current = read(root, "STEP-001", obs_rel)
            assert current["reuse"] is not None, current
            original_observation = (root / obs_rel).read_bytes()
            (root / obs_rel).write_bytes(original_observation.replace(
                b"Accessible name is missing", b"Accessible name is absent"
            ))
            try:
                read(root, "STEP-001", obs_rel)
            except ObservationError as exc:
                assert "changed" in str(exc)
            else:
                raise AssertionError("mutated immutable observation accepted")
            (root / obs_rel).write_bytes(original_observation)
            assert read(root, "STEP-001", obs_rel)["sourceStep"] == "STEP-001"
            new_step = (
                fx["task"](verification_text)
                .replace("STEP-001", "STEP-002")
                .replace("Synthetic fixture.", "Fix observed defect: " + obs_rel)
            )
            write(root / "planning/tasks/STEP-002.md", new_step)
            policy["steps"]["STEP-002"] = {
                "checks": deepcopy(checks),
                "infrastructure": infrastructure,
                "reuse": {"sourceStep": "STEP-001", "observation": obs_rel},
            }
            write(map_path, json.dumps(policy))
            write(root / "src/ui/Button.tsx", "export const label = 'Accessible name';\n")
            correction = run_step_verification(
                root, "STEP-002", manual_results=[{
                    "check": "Проверить доступное имя кнопки",
                    "status": "PASS", "observed": "Accessible name was verified.",
                }],
            )
            assert correction["status"] == "PASS", correction
            assert correction["verificationMode"] == "incremental", correction
            assert correction["executedChecks"] == [ui] and correction["reusedCount"] == 1, correction
            assert verification_freshness(root, "STEP-002")["fresh"] is True
            assert source.read_bytes() == accepted_bytes, "completed STEP mutated"
            assert review_path.read_bytes() == review_bytes, "trusted REVIEW mutated"
            assert (root / obs_rel).read_bytes() == original_observation, "observation mutated"

            # Lost/moved source operational proof => full Verification, never
            # synthetic PASS from orphaned source CHECK records.
            (root / ".harness/local/verification-incremental/STEP-002.json").unlink()
            source_cache.unlink()
            fallback = run_step_verification(
                root, "STEP-002", manual_results=[{
                    "check": "Проверить доступное имя кнопки", "status": "PASS",
                    "observed": "All checks were re-run.",
                }],
            )
            assert fallback["status"] == "PASS" and fallback["verificationMode"] == "full", fallback
            assert fallback["executedCount"] == 2, fallback

    print("LATE DEFECT SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
