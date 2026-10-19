#!/usr/bin/env python3
"""Synthetic late-defect preservation and completed-STEP verification reuse."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
from review_contract import latest_review, latest_trusted_review, validate_review_report
from execution_status import start_execution, complete_command, resolve_root, begin_command, block_execution
from fix_delta import capture_fix, complete_fix, review_scope

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


def validated_pass_review(root: Path, name: str, completion: str) -> str:
    """Создать настоящий, schema-valid v3 REVIEW без мокания trust boundary."""
    spec = importlib.util.spec_from_file_location(
        "execution_review_fixture", Path(__file__).with_name("execution-self-test.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    relative = module.review_report(root, "PASS", name, completion_result=completion)
    path = root / relative
    original = path.read_text(encoding="utf-8")
    updated = original.replace(
        "reviewer_role: reviewer", "finding_contract: 3\nreviewer_role: reviewer"
    )
    ticks = chr(96) * 3
    updated += (
        "\n## Machine-readable findings\n\n" + ticks + "json\n"
        + '{"schemaVersion":3,"findings":[]}\n' + ticks + "\n"
    )
    path.write_text(updated, encoding="utf-8", newline="\n")
    errors = validate_review_report(root, path, expected_step_id="STEP-001")
    assert not errors, errors
    return relative


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
        # Active STEP: настоящий REVIEW PASS с completion BLOCKED, не
        # исторический completion proof. Никаких подмен trusted origin.
        blocked_report = validated_pass_review(
            root, "REVIEW-20261019T070000Z.md", "BLOCKED"
        )
        blocked_review = latest_review(root, "STEP-001")
        assert blocked_review and blocked_review["verdict"] == "PASS"
        assert blocked_review["completionResult"] == "BLOCKED"
        assert latest_trusted_review(root, "STEP-001") is None
        from execution_status import _post_pass_fix_allowed
        assert not _post_pass_fix_allowed(root, "STEP REVIEW STEP-001", "SUCCESS"), (
            "ordinary PASS must not open an implicit FIX without observation"
        )
        no_observation_chain = (
            "STEP REVIEW STEP-001 > STEP FIX STEP-001 > STEP REVIEW STEP-001"
        )
        start_execution(root, no_observation_chain)
        complete_command(root, no_observation_chain, "STEP REVIEW STEP-001", "SUCCESS")
        denied = resolve_root(root, no_observation_chain)
        assert denied["status"] == "DONE" and denied["command"] is None, denied

        active_observation = record(
            root, "STEP-001", criterion=criteria[0],
            given="Button is present", when="The screen reader focuses it",
            expected="Accessible name is announced",
            observed="No accessible name was announced",
            evidence_path="docs/architecture.md", invalidated_checks=["ui"],
        )
        active_rel = active_observation["path"]
        assert read(root, "STEP-001", active_rel)["source"]["statusAtObservation"] == "in_progress"

        # CTS не открывает FIX после PASS без durable observation.
        chain = "STEP REVIEW STEP-001 > STEP FIX STEP-001"
        started = start_execution(root, chain)
        complete_command(root, chain, "STEP REVIEW STEP-001", "SUCCESS")
        decision = resolve_root(root, chain)
        assert decision["status"] == "NEXT" and decision["command"] == "STEP FIX STEP-001", decision
        begun = begin_command(root, chain, "STEP FIX STEP-001")
        captured = capture_fix(root, "STEP-001", begun["executionId"])
        assert captured["observation"] == active_rel
        # Реальный FIX меняет продукт, canonical Verification перепроверяет
        # исправленный сценарий и только после PASS закрывает delta handoff.
        write(root / "src/ui/Button.tsx", "export const label = 'Fixed accessible name';\\n")
        verified_fix = run_step_verification(
            root, "STEP-001", manual_results=[{
                "check": "Проверить доступное имя кнопки",
                "status": "PASS",
                "observed": "Post-PASS defect fixed and screen-reader name confirmed.",
            }],
        )
        assert verified_fix["status"] == "PASS", verified_fix
        complete_fix(root, "STEP-001", begun["executionId"])
        scoped = review_scope(root, "STEP-001")
        assert scoped["mode"] == "fix_delta", scoped
        assert scoped["observation"]["path"] == active_rel, scoped
        assert scoped["previousFingerprints"] == [], "no forged FAIL findings"
        assert "src/ui/Button.tsx" in scoped["changedPaths"], scoped
        block_execution(root, chain, command="STEP FIX STEP-001")

        # После завершения исходного STEP старый REVIEW/STEP не меняется.
        review_rel = validated_pass_review(root, "REVIEW-20261019T080000Z.md", "PASS")
        review_path = root / review_rel
        source_original = source.read_text(encoding="utf-8")
        write(source, source_original.replace("status: in_progress", "status: completed", 1))
        accepted_bytes = source.read_bytes()
        review_bytes = review_path.read_bytes()
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
        # Next local FIX still compares with original full baseline,
        # while the first corrected UI PASS is now a valid own proof.
        write(root / "src/ui/Button.tsx", "export const label = 'Improved accessible name';\n")
        another = run_step_verification(
            root, "STEP-002", manual_results=[{
                "check": "Проверить доступное имя кнопки",
                "status": "PASS", "observed": "Improved accessible name checked.",
            }],
        )
        assert another["status"] == "PASS" and another["verificationMode"] == "incremental", another
        assert another["executedChecks"] == [ui] and another["reusedCount"] == 1, another
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
