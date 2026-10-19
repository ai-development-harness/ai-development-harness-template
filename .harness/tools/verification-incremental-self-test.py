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

        # Дефект UI не должен заставлять повторять доказанно независимый backend.
        write(root / "src/ui/button.tsx", 'export const label = "Accessible button";\n')
        first = run_step_verification(root, step_id, manual_results=observation())
        assert first["status"] == "PASS" and first["verificationMode"] == "incremental", first
        assert first["executedChecks"] == [ui] and first["reusedCount"] == 1, first
        assert verification_freshness(root, step_id)["fresh"] is True
        assert verification_command_evidence(root, step_id, backend)["fresh"] is True
        assert "Verification mode: incremental" in step.read_text(encoding="utf-8")
        assert "Provenance: " in step.read_text(encoding="utf-8")
        assert json.loads(checkpoint.read_text(encoding="utf-8"))["fullBaseline"]["tree"] == baseline

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
        print("INCREMENTAL VERIFICATION SELF-TEST: PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
