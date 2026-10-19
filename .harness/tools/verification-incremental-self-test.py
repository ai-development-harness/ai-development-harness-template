#!/usr/bin/env python3
"""Интеграционная регрессия составного Verification PASS (#367).

Только замкнутые synthetic fixtures: реальные Git snapshots, canonical
Verification writer, изменяемые исходники, Evidence proof и freshness.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from completion_gate import acceptance_criteria
from verification import run_step_verification, verification_freshness, verification_command_evidence


def fixture_functions() -> dict[str, object]:
    fixture = Path(__file__).with_name("verification-self-test.py")
    spec = importlib.util.spec_from_file_location("verification_original_fixture", fixture)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return vars(module)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def observation(status: str = "PASS") -> list[dict[str, str]]:
    return [{"check": "Проверить доступное имя кнопки", "status": status,
             "observed": "Кнопка обнаруживается по имени" if status == "PASS" else "Имя отсутствует"}]


def main() -> int:
    fixture = fixture_functions()
    with tempfile.TemporaryDirectory(prefix="harness-verification-incremental-") as folder:
        root = Path(folder)
        fixture["prepare"](root)
        step_id = "STEP-001"
        step = root / "planning/tasks/STEP-001.md"
        ui = 'python3 -c "print(123)"'
        backend = 'python3 -c "print(456)"'
        write(step, fixture["task"](
            fixture["command_line"](ui) + "\n" + fixture["command_line"](backend)
            + "\n- manual: Проверить доступное имя кнопки"
        ))
        manifest = root / ".harness/manifest.yaml"
        write(manifest, manifest.read_text(encoding="utf-8")
              + "\nverification:\n  impactMap: docs/verification/impact-map.json\n")
        write(root / "src/ui/button.tsx", 'export const title = "Button";\n')
        write(root / "src/backend/service.py", 'print("backend")\n')
        criteria = acceptance_criteria(root, step_id)
        assert criteria == ["Verification PASS."], criteria
        policy = {"schemaVersion": 1, "steps": {step_id: {
            "checks": [
                {"id": "ui", "command": ui, "inputs": ["src/ui/**", "tests/ui/**"],
                 "dependsOn": [], "acceptance": criteria, "reusable": True},
                {"id": "backend", "command": backend,
                 "inputs": ["src/backend/**", "tests/backend/**"],
                 "dependsOn": [], "acceptance": criteria, "reusable": True},
            ],
            "infrastructure": ["docs/verification/**", ".harness/manifest.yaml", "package-lock.json"],
        }}}
        write(root / "docs/verification/impact-map.json", json.dumps(policy))

        # Без полного PASS cache не создаётся; ручная проверка обязательна.
        pending = run_step_verification(root, step_id)
        assert pending["status"] == "MANUAL_REQUIRED", pending
        assert not (root / ".harness/local/verification-incremental/STEP-001.json").exists()
        initial = run_step_verification(root, step_id, manual_results=observation())
        assert initial["status"] == "PASS" and initial["verificationMode"] == "full", initial
        checkpoint = root / ".harness/local/verification-incremental/STEP-001.json"
        assert checkpoint.is_file()
        baseline = json.loads(checkpoint.read_text(encoding="utf-8"))["fullBaseline"]["tree"]

        # Новый настоящий immutable REVIEW после полного baseline не должен
        # выглядеть как неизвестный product input: это обычный FIX workflow.
        reviewer_spec = importlib.util.spec_from_file_location(
            "execution_review_fixture", Path(__file__).with_name("execution-self-test.py")
        )
        assert reviewer_spec is not None and reviewer_spec.loader is not None
        reviewer = importlib.util.module_from_spec(reviewer_spec)
        reviewer_spec.loader.exec_module(reviewer)
        review_rel = reviewer.review_report(
            root, "PASS", "REVIEW-20261019T130000Z.md", completion_result="BLOCKED",
        )
        from review_contract import validate_review_report
        assert not validate_review_report(root, root / review_rel, expected_step_id=step_id)

        # Дефект UI не должен заставлять повторять доказанно независимый backend.
        write(root / "src/ui/button.tsx", 'export const label = "Accessible button";\n')
        first = run_step_verification(root, step_id, manual_results=observation())
        assert first["status"] == "PASS" and first["verificationMode"] == "incremental", first
        assert first["executedChecks"] == [ui] and first["reusedCount"] == 1, first
        assert verification_freshness(root, step_id)["fresh"] is True
        # Aggregate PASS of the reused backend check remains current, but
        # an exact-command consumer must not mistake reuse for a new execution.
        exact_backend = verification_command_evidence(root, step_id, backend)
        assert exact_backend["fresh"] is False
        assert exact_backend["reasonCode"] == "VERIFICATION_EXACT_COMMAND_NOT_EXECUTED", exact_backend
        assert "Verification mode: incremental" in step.read_text(encoding="utf-8")
        assert "Provenance: " in step.read_text(encoding="utf-8")
        assert json.loads(checkpoint.read_text(encoding="utf-8"))["fullBaseline"]["tree"] == baseline

        # Изменение только cache fingerprint не может превратить старый PASS
        # в proof для другого input basis: hash cache хранится в producer proof.
        altered = json.loads(checkpoint.read_text(encoding="utf-8"))
        altered["latestChecks"]["backend"]["inputBasis"] = "sha256:" + "f" * 64
        checkpoint.write_text(json.dumps(altered) + "\n", encoding="utf-8")
        tampered = run_step_verification(root, step_id, manual_results=observation())
        assert tampered["status"] == "PASS" and tampered["verificationMode"] == "full", tampered
        assert tampered["fallbackReason"] == "CHECKPOINT_PRODUCER_MISMATCH", tampered
        baseline = json.loads(checkpoint.read_text(encoding="utf-8"))["fullBaseline"]["tree"]

        # Report, который уже ВХОДИЛ в новый полный baseline, не должен
        # автоматически исключаться как новый. Его изменение — full fallback.
        review_path = root / review_rel
        review_path.write_text(
            review_path.read_text(encoding="utf-8") + "\nChanged historical review.\n",
            encoding="utf-8",
        )
        changed_history = run_step_verification(root, step_id, manual_results=observation())
        assert changed_history["status"] == "PASS" and changed_history["verificationMode"] == "full", changed_history
        assert changed_history["fallbackReason"] == "HISTORICAL_REVIEW_CHANGED", changed_history
        baseline = json.loads(checkpoint.read_text(encoding="utf-8"))["fullBaseline"]["tree"]

        # Выбранную UI-проверку, уже пройденную на этой exact revision,
        # повторно при completion не запускаем.
        from verification_selective import run_selected
        write(root / "src/ui/button.tsx", 'export const label = "Updated accessible button";\n')
        targeted = run_selected(root, step_id, [ui])
        assert targeted["status"] == "PASS" and targeted["completionProof"] is False, targeted
        targeted_completion = run_step_verification(root, step_id, manual_results=observation())
        assert targeted_completion["status"] == "PASS", targeted_completion
        assert targeted_completion["verificationMode"] == "incremental", targeted_completion
        assert targeted_completion["executedCount"] == 0, targeted_completion
        assert targeted_completion["targetedReusedCount"] == 1, targeted_completion

        # Повторное изменение другой подсистемы не теряет исходный полный baseline.
        write(root / "src/backend/service.py", 'print("backend updated")\n')
        second = run_step_verification(root, step_id, manual_results=observation())
        assert second["status"] == "PASS" and second["verificationMode"] == "incremental", second
        assert second["executedChecks"] == [backend], second
        assert json.loads(checkpoint.read_text(encoding="utf-8"))["fullBaseline"]["tree"] == baseline

        # Rename, test-only change и staged/untracked sources тоже влияют на
        # Git tree input fingerprints, без зависимости от HEAD.
        (root / "src/ui/button.tsx").rename(root / "src/ui/renamed-button.tsx")
        renamed = run_step_verification(root, step_id, manual_results=observation())
        assert renamed["status"] == "PASS" and renamed["verificationMode"] == "incremental", renamed
        assert renamed["executedChecks"] == [ui], renamed
        write(root / "tests/ui/accessible.test.ts", "test accessible name\n")
        from subprocess import run as subprocess_run
        staged = subprocess_run(["git", "add", "tests/ui/accessible.test.ts"],
                                cwd=root, capture_output=True, check=False)
        assert staged.returncode == 0, staged.stderr
        test_only = run_step_verification(root, step_id, manual_results=observation())
        assert test_only["status"] == "PASS" and test_only["executedChecks"] == [ui], test_only

        # Если карта кэша повреждена, полный запуск безопасно пересоздаёт её.
        checkpoint.write_text("{invalid json", encoding="utf-8")
        corrupted = run_step_verification(root, step_id, manual_results=observation())
        assert corrupted["status"] == "PASS" and corrupted["verificationMode"] == "full", corrupted
        assert corrupted["fallbackReason"] == "FULL_BASELINE_CORRUPT", corrupted

        # Изменение общего config/lockfile требует полного Verify даже при
        # формально неизменных исходниках UI/backend.
        write(root / "package-lock.json", '{"new":true}\n')
        infrastructure = run_step_verification(root, step_id, manual_results=observation())
        assert infrastructure["status"] == "PASS" and infrastructure["verificationMode"] == "full", infrastructure
        assert infrastructure["fallbackReason"] == "TEST_INFRASTRUCTURE_CHANGED", infrastructure

        # Новый файл вне объявленного покрытия приводит к объяснимому полному прогону.
        write(root / "unmapped.txt", "unknown change\n")
        fallback = run_step_verification(root, step_id, manual_results=observation())
        assert fallback["status"] == "PASS" and fallback["verificationMode"] == "full", fallback
        assert fallback["fallbackReason"] == "UNMAPPED_CHANGED_PATH", fallback

        # Изменение матрицы проверок/coverage не позволяет сократить обязательства.
        policy["steps"][step_id]["checks"][0]["inputs"] = ["src/ui/**"]
        write(root / "docs/verification/impact-map.json", json.dumps(policy))
        changed_map = run_step_verification(root, step_id, manual_results=observation())
        assert changed_map["status"] == "PASS" and changed_map["verificationMode"] == "full", changed_map

        # Без карты проект сохраняет классическое поведение.
        write(manifest, manifest.read_text(encoding="utf-8").replace(
            "\nverification:\n  impactMap: docs/verification/impact-map.json\n", "\n"))
        legacy = run_step_verification(root, step_id, manual_results=observation())
        assert legacy["status"] == "PASS" and legacy["verificationMode"] == "full", legacy
        # Монолитный command остаётся источником baseline: только полный
        # initial PASS вместе с обоими PASS групп разрешает decomposition.
        # После локального UI delta сам monolith второй раз не запускается.
        with tempfile.TemporaryDirectory(prefix="harness-composite-") as folder2:
            second_root = Path(folder2)
            fixture["prepare"](second_root)
            composite_step = second_root / "planning/tasks/STEP-001.md"
            monolith = (
                'python3 -c "from pathlib import Path;'
                " p=Path('.harness/local/monolith-count.txt');"
                " p.parent.mkdir(parents=True, exist_ok=True);"
                " p.open('a').write('1')"
                '"'
            )
            group_ui = 'python3 -c "print(12)"'
            group_backend = 'python3 -c "print(34)"'
            write(composite_step, fixture["task"](
                fixture["command_line"](monolith)
                + "\n- manual: Проверить доступное имя кнопки"
            ))
            composite_manifest = second_root / ".harness/manifest.yaml"
            write(composite_manifest, composite_manifest.read_text(encoding="utf-8")
                  + "\nverification:\n  impactMap: docs/verification/impact-map.json\n")
            write(second_root / "src/ui/button.tsx", 'export const title = "Button";\n')
            write(second_root / "src/backend/logic.py", "print('backend')\n")
            composite_criteria = acceptance_criteria(second_root, "STEP-001")
            compound = {
                "schemaVersion": 1, "steps": {"STEP-001": {
                    "checks": [{
                        "id": "all", "command": monolith, "inputs": ["src/ui/**", "src/backend/**"],
                        "dependsOn": [], "acceptance": composite_criteria, "reusable": True,
                        "groups": [
                            {"id": "ui", "command": group_ui, "inputs": ["src/ui/**"],
                             "dependsOn": [], "acceptance": composite_criteria, "reusable": True},
                            {"id": "backend", "command": group_backend,
                             "inputs": ["src/backend/**"],
                             "dependsOn": [], "acceptance": composite_criteria, "reusable": True},
                        ],
                    }],
                    "infrastructure": [".harness/manifest.yaml", "docs/verification/**"],
                }},
            }
            write(second_root / "docs/verification/impact-map.json", json.dumps(compound))
            from verification_incremental import _environment_for_policy, _source_map
            group_policy = _source_map(second_root, "STEP-001", [monolith], composite_criteria)
            with patch("verification_incremental._environment_basis", return_value="environment") as observed_env:
                assert _environment_for_policy([monolith], group_policy) == "environment"
                assert set(observed_env.call_args.args[0]) == {
                    monolith, group_ui, group_backend
                }, observed_env.call_args
            seeded = run_step_verification(second_root, "STEP-001", manual_results=observation())
            assert seeded["status"] == "PASS" and seeded["verificationMode"] == "full", seeded
            assert [item["status"] for item in seeded["commands"][0]["groups"]] == ["PASS", "PASS"], seeded
            counter = second_root / ".harness/local/monolith-count.txt"
            assert counter.read_text(encoding="utf-8") == "1"
            assert verification_command_evidence(
                second_root, "STEP-001", monolith,
            )["fresh"] is True, "full baseline must prove exact executed command"
            write(second_root / "src/ui/button.tsx", 'export const title = "Accessible";\n')
            composite_result = run_step_verification(second_root, "STEP-001", manual_results=observation())
            assert composite_result["status"] == "PASS" and composite_result["verificationMode"] == "incremental", composite_result
            assert counter.read_text(encoding="utf-8") == "1", "qualified monolith was rerun"
            proof = verification_command_evidence(second_root, "STEP-001", monolith)
            assert proof["fresh"] is False and proof["reasonCode"] == "VERIFICATION_EXACT_COMMAND_NOT_EXECUTED", proof
            groups = composite_result["commands"][0]["groups"]
            assert [g["id"] for g in groups] == ["ui", "backend"], groups
            assert "reusedFrom" not in groups[0] and groups[1].get("reusedFrom"), groups
            assert verification_freshness(second_root, "STEP-001")["fresh"] is True
            # A path covered by parent but NOT by a group cannot be skipped.
            compound["steps"]["STEP-001"]["checks"][0]["inputs"].append("src/extra/**")
            write(second_root / "docs/verification/impact-map.json", json.dumps(compound))
            write(second_root / "src/extra/ambiguous.ts", "export const value = 1;\n")
            blocked_selection = run_step_verification(second_root, "STEP-001", manual_results=observation())
            assert blocked_selection["verificationMode"] == "full", blocked_selection
            assert counter.read_text(encoding="utf-8") == "11", "full fallback omitted monolith"

        # Новый targeted FAIL отменяет предыдущий producer-bound PASS:
        # обычная Verification возвращается к полному режиму, не наследуя
        # старый тестовый результат из локального checkpoint.
        from verification_selective import run_selected
        assert verification_freshness(root, step_id)["fresh"] is True
        with patch("verification_selective._run_command", return_value={
            "command": ui, "status": "FAIL", "exitCode": 3,
        }):
            observed_fail = run_selected(root, step_id, [ui])
        assert observed_fail["status"] == "FAIL", observed_fail
        assert not checkpoint.exists(), "cached prior PASS survived targeted FAIL"
        assert verification_freshness(root, step_id)["fresh"] is False
        assert verification_freshness(root, step_id)["reasonCode"] == "VERIFICATION_PROOF_MISSING"
        recovered = run_step_verification(root, step_id, manual_results=observation())
        assert recovered["status"] == "PASS" and recovered["verificationMode"] == "full", recovered

        print("INCREMENTAL VERIFICATION SELF-TEST: PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
