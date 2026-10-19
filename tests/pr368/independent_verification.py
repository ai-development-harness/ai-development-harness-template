#!/usr/bin/env python3
"""Independent differential Verification smoke for a disposable Harness fixture.

Usage: python3 independent_verification.py --repo /path/to/harness --mode candidate|baseline
No network, repository mutations or external dependencies. All writes are inside TemporaryDirectory.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def load_fixture(path: Path):
    spec = importlib.util.spec_from_file_location("verification_release_fixture", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure(action):
    t0 = time.perf_counter_ns()
    result = action()
    elapsed_ms = (time.perf_counter_ns() - t0) / 1_000_000
    return result, round(elapsed_ms, 3)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--mode", choices=("baseline", "candidate"), required=True)
    args = p.parse_args()
    src = args.repo.resolve()
    tools = src / ".harness/tools"
    assert (tools / "verification.py").is_file(), src
    sys.path.insert(0, str(tools))
    fixture = load_fixture(tools / "verification-self-test.py")
    from verification import run_step_verification
    from completion_gate import acceptance_criteria

    delay = float(os.environ.get("PR368_CHECK_DELAY", "0.12"))
    assert 0.0 <= delay <= 5.0
    # Runnable check commands: no dependencies and measurable, intentional work.
    ui = (f'python3 -c "import pathlib,sys,time;time.sleep({delay});'
          'sys.exit(int(\'BROKEN\' in pathlib.Path(\'src/ui/button.tsx\').read_text()))"')
    backend = (f'python3 -c "import pathlib,sys,time;time.sleep({delay});'
               'sys.exit(int(\'BROKEN\' in pathlib.Path(\'src/backend/service.py\').read_text()))"')
    rows = []

    def check(name, result, expected, ms):
        observed = result.get("status")
        if observed != expected:
            raise AssertionError(f"{name}: status {observed}, expected {expected}: {result}")
        rows.append({
            "case": name, "status": observed, "ms": ms,
            "mode": result.get("verificationMode"),
            "executed": result.get("executedCount"),
            "reused": result.get("reusedCount"),
            "fallback": result.get("fallbackReason"),
        })
        return result

    with tempfile.TemporaryDirectory(prefix=f"pr368-{args.mode}-") as temp:
        root = Path(temp)
        fixture.prepare(root)
        step_id = "STEP-001"
        task_file = root / "planning/tasks/STEP-001.md"
        write(task_file, fixture.task(fixture.command_line(ui) + "\n" + fixture.command_line(backend)))
        write(root / "src/ui/button.tsx", "export const name = 'valid';\n")
        write(root / "src/backend/service.py", "print('valid')\n")
        criteria = acceptance_criteria(root, step_id)
        manifest = root / ".harness/manifest.yaml"
        policy_path = root / "docs/verification/impact-map.json"
        policy = {"schemaVersion": 1, "steps": {step_id: {
            "checks": [
                {"id": "ui", "command": ui, "inputs": ["src/ui/**", "src/shared/**"],
                 "dependsOn": [], "acceptance": criteria, "reusable": True},
                {"id": "backend", "command": backend,
                 "inputs": ["src/backend/**", "src/shared/**"],
                 "dependsOn": [], "acceptance": criteria, "reusable": True},
            ],
            "infrastructure": ["docs/verification/**", ".harness/manifest.yaml", "package-lock.json"],
        }}}
        if args.mode == "candidate":
            write(policy_path, json.dumps(policy))
            write(manifest, manifest.read_text(encoding="utf-8") +
                  "\nverification:\n  impactMap: docs/verification/impact-map.json\n")

        baseline, ms = measure(lambda: run_step_verification(root, step_id))
        check("initial-full", baseline, "PASS", ms)
        if args.mode == "candidate":
            assert baseline["verificationMode"] == "full" and baseline["executedCount"] == 2, baseline

        # Identical inputs, only UI changed. Candidate is allowed to reuse backend.
        write(root / "src/ui/button.tsx", "export const name = 'changed';\n")
        changed, ms = measure(lambda: run_step_verification(root, step_id))
        check("ui-change", changed, "PASS", ms)
        if args.mode == "candidate":
            assert changed["verificationMode"] == "incremental", changed
            assert changed["executedCount"] == 1 and changed["reusedCount"] == 1, changed
            # Full comparison is read-only on exactly the same subject, not after another mutation.
            full, full_ms = measure(lambda: run_step_verification(root, step_id, force_full=True, write_evidence=False))
            check("ui-identical-full", full, "PASS", full_ms)
            assert full["executedCount"] == 2 and full["reusedCount"] == 0, full
            rows.append({"case": "ui-saved", "ms": round(full_ms - ms, 3),
                         "saved_pct": round(100 * (full_ms-ms) / full_ms, 2),
                         "skipped_mandatory": 0, "reused_proven": 1})
        else:
            # Existing implementation always ran the full contract.
            assert all(x.get("verificationMode") is None for x in (baseline, changed))
            assert len(changed["commands"]) == 2

        if args.mode == "candidate":
            write(root / "src/shared/types.ts", "export type Shared = string;\n")
            shared, ms = measure(lambda: run_step_verification(root, step_id))
            check("shared-change", shared, "PASS", ms)
            assert shared["executedCount"] == 2 and shared["reusedCount"] == 0, shared

            # A regression in backend must be detected in both modes.
            write(root / "src/backend/service.py", "# BROKEN\n")
            defect, ms = measure(lambda: run_step_verification(root, step_id))
            check("backend-defect", defect, "FAIL", ms)
            forced, ms = measure(lambda: run_step_verification(root, step_id, force_full=True, write_evidence=False))
            check("backend-defect-full", forced, "FAIL", ms)
            assert defect["commands"][1]["status"] == "FAIL"
            write(root / "src/backend/service.py", "print('repaired')\n")
            healed, ms = measure(lambda: run_step_verification(root, step_id))
            check("repair", healed, "PASS", ms)

            # A corrupted checkpoint must never skip commands.
            checkpoint = root / ".harness/local/verification-incremental/STEP-001.json"
            assert checkpoint.exists(), checkpoint
            write(checkpoint, "{ broken")
            corrupt, ms = measure(lambda: run_step_verification(root, step_id))
            check("corrupt-cache", corrupt, "PASS", ms)
            assert corrupt["verificationMode"] == "full" and corrupt["executedCount"] == 2

            # Shared test infrastructure modification requires an ordinary full run.
            write(root / "package-lock.json", '{"version":2}\n')
            infra, ms = measure(lambda: run_step_verification(root, step_id))
            check("infra-change", infra, "PASS", ms)
            assert infra["verificationMode"] == "full" and infra["executedCount"] == 2

            # Unmapped changes must not be quietly ignored.
            write(root / "src/elsewhere/outside.ts", "export const x = 1;\n")
            unmapped, ms = measure(lambda: run_step_verification(root, step_id))
            check("unmapped-source", unmapped, "PASS", ms)
            assert unmapped["verificationMode"] == "full" and unmapped["executedCount"] == 2

    summary = {"target": args.mode, "repoHead": src.name,
               "status": "PASS", "cases": rows}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
