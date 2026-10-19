#!/usr/bin/env python3
"""Changed inherited process environment must invalidate incremental PASS."""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from completion_gate import acceptance_criteria
from verification import run_step_verification

def main() -> int:
    path = Path(__file__).with_name("verification-self-test.py")
    spec = importlib.util.spec_from_file_location("env_fixture", path)
    assert spec and spec.loader
    f = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(f)
    variable = "PR368_ENV_POLICY"
    old = os.environ.get(variable)
    with tempfile.TemporaryDirectory(prefix="harness-verification-env-") as temp:
        root = Path(temp)
        f.prepare(root)
        task_id = "STEP-001"
        env_cmd = (
            'python3 -c "import os,sys;'
            "sys.exit(0 if os.environ.get('PR368_ENV_POLICY')=='pass' else 7)\""
        )
        backend_cmd = 'python3 -c "print(123)"'
        (root / "planning/tasks/STEP-001.md").write_text(
            f.task(f.command_line(env_cmd) + "\n" + f.command_line(backend_cmd)),
            encoding="utf-8",
        )
        (root / "src").mkdir(exist_ok=True)
        (root / "src/ui.ts").write_text("export const x = 1;\n", encoding="utf-8")
        (root / "src/backend.ts").write_text("export const x = 2;\n", encoding="utf-8")
        acceptance = acceptance_criteria(root, task_id)
        policy = {"schemaVersion": 1, "steps": {task_id: {
            "checks": [
                {"id": "ui", "command": env_cmd, "inputs": ["src/ui.ts"],
                 "dependsOn": [], "acceptance": acceptance, "reusable": True},
                {"id": "backend", "command": backend_cmd, "inputs": ["src/backend.ts"],
                 "dependsOn": [], "acceptance": acceptance, "reusable": True},
            ],
            "infrastructure": [".harness/manifest.yaml", "docs/verification/**"],
        }}}
        map_path = root / "docs/verification/impact-map.json"
        map_path.parent.mkdir(parents=True, exist_ok=True)
        map_path.write_text(json.dumps(policy), encoding="utf-8")
        manifest = root / ".harness/manifest.yaml"
        manifest.write_text(manifest.read_text(encoding="utf-8")
                            + "\nverification:\n  impactMap: docs/verification/impact-map.json\n",
                            encoding="utf-8")
        try:
            os.environ[variable] = "pass"
            first = run_step_verification(root, task_id)
            assert first["status"] == "PASS" and first["verificationMode"] == "full", first
            steady = run_step_verification(root, task_id)
            assert steady["status"] == "PASS" and steady["verificationMode"] == "incremental", steady
            assert steady["executedCount"] == 0 and steady["reusedCount"] == 2, steady

            # Only the env value changes: no Git file mutation.
            os.environ[variable] = "fail"
            changed = run_step_verification(root, task_id)
            forced = run_step_verification(root, task_id, force_full=True, write_evidence=False)
            assert changed["status"] == forced["status"] == "FAIL", (changed, forced)
            assert changed["verificationMode"] == "full", changed
            assert changed["executedCount"] == 2 and changed["reusedCount"] == 0, changed
            assert changed["fallbackReason"] == "SEMANTIC_OR_ENVIRONMENT_CHANGED", changed
            assert changed["commands"][0]["exitCode"] == 7, changed

            os.environ[variable] = "pass"
            recovered = run_step_verification(root, task_id)
            assert recovered["status"] == "PASS" and recovered["verificationMode"] == "full", recovered
            (root / "src/ui.ts").write_text("export const x = 3;\n", encoding="utf-8")
            targeted = run_step_verification(root, task_id)
            assert targeted["status"] == "PASS" and targeted["verificationMode"] == "incremental", targeted
            assert targeted["executedCount"] == 1 and targeted["reusedCount"] == 1, targeted
        finally:
            if old is None: os.environ.pop(variable, None)
            else: os.environ[variable] = old
    print("VERIFICATION ENVIRONMENT SELF-TEST: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
