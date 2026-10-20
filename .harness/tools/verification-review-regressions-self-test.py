#!/usr/bin/env python3
"""Регрессии review #368: parent dependencies, targeted proof и счётчики."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile

from completion_gate import acceptance_criteria
from verification import run_step_verification, verification_freshness, verification_subject_content_hash
from verification_selective import run_selected


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def prepare(root: Path, commands: list[str], checks: list[dict]) -> None:
    """Использовать настоящий canonical writer и существующий Git fixture."""
    spec = importlib.util.spec_from_file_location(
        "review_regression_fixture", Path(__file__).with_name("verification-self-test.py"),
    )
    assert spec is not None and spec.loader is not None
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.prepare(root)
    write(root / "planning/tasks/STEP-001.md", fixture.task(
        "\n".join(fixture.command_line(command) for command in commands),
    ))
    manifest = root / ".harness/manifest.yaml"
    write(manifest, manifest.read_text(encoding="utf-8")
          + "\nverification:\n  impactMap: docs/verification/impact-map.json\n")
    criteria = acceptance_criteria(root, "STEP-001")
    for check in checks:
        check.update(acceptance=criteria, reusable=True)
        for group in check.get("groups", []):
            group.update(acceptance=criteria, reusable=True)
    write(root / "docs/verification/impact-map.json", json.dumps({
        "schemaVersion": 1, "steps": {"STEP-001": {
            "checks": checks,
            "infrastructure": [".harness/manifest.yaml", "docs/verification/**"],
        }},
    }))


def check(identifier: str, command: str, inputs: list[str], dependencies: list[str] | None = None) -> dict:
    return {"id": identifier, "command": command, "inputs": inputs,
            "dependsOn": dependencies or []}


def composite_dependency() -> None:
    """Одновременный own delta не отменяет зависимость всего parent."""
    with tempfile.TemporaryDirectory(prefix="harness-review-dependency-") as directory:
        root = Path(directory)
        upstream = 'python3 -c "print(101)"'
        ui = 'python3 -c "print(202)"'
        backend = ('python3 -c "from pathlib import Path;import sys;'
                   "sys.exit(0 if Path('src/shared.txt').read_text()=='good' else 7)\"")
        parent = backend.replace("else 7", "else 8")
        aggregate = check("all", parent, ["src/ui.txt", "src/backend.txt"], ["shared"])
        aggregate["groups"] = [check("ui", ui, ["src/ui.txt"]),
                               check("backend", backend, ["src/backend.txt"])]
        prepare(root, [upstream, parent], [check("shared", upstream, ["src/shared.txt"]), aggregate])
        for name in ("shared", "ui", "backend"):
            write(root / f"src/{name}.txt", "good")
        assert run_step_verification(root, "STEP-001")["status"] == "PASS"
        write(root / "src/shared.txt", "bad")
        write(root / "src/ui.txt", "changed")
        incremental = run_step_verification(root, "STEP-001")
        full = run_step_verification(root, "STEP-001", force_full=True, write_evidence=False)
        assert incremental["status"] == full["status"] == "FAIL", (incremental, full)
        assert incremental["verificationMode"] == "incremental", incremental
        assert incremental["groupReusedCount"] == 0, incremental
        assert verification_freshness(root, "STEP-001")["fresh"] is False


def targeted_provenance() -> None:
    """Правка единственного targeted cache не переносит PASS на новый subject."""
    with tempfile.TemporaryDirectory(prefix="harness-review-targeted-") as directory:
        root = Path(directory)
        ui = ('python3 -c "from pathlib import Path;import sys;'
              "sys.exit(0 if Path('src/ui.txt').read_text().strip()=='good' else 7)\"")
        backend = 'python3 -c "print(202)"'
        prepare(root, [ui, backend], [check("ui", ui, ["src/ui.txt"]),
                                     check("backend", backend, ["src/backend.txt"])])
        write(root / "src/ui.txt", "good")
        write(root / "src/backend.txt", "stable")
        assert run_step_verification(root, "STEP-001")["status"] == "PASS"
        write(root / "src/ui.txt", "good\n")
        assert run_selected(root, "STEP-001", [ui])["status"] == "PASS"
        write(root / "src/ui.txt", "bad")
        path = root / ".harness/local/verification-incremental/STEP-001.targeted.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["subjectHash"] = verification_subject_content_hash(root, "STEP-001")
        write(path, json.dumps(payload) + "\n")
        incremental = run_step_verification(root, "STEP-001")
        full = run_step_verification(root, "STEP-001", force_full=True, write_evidence=False)
        assert incremental["status"] == full["status"] == "FAIL", (incremental, full)
        assert incremental["targetedReusedCount"] == 0, incremental
        assert verification_freshness(root, "STEP-001")["fresh"] is False
        # Потеря независимого proof также требует реального запуска команды.
        write(root / "src/ui.txt", "good")
        assert run_step_verification(root, "STEP-001")["status"] == "PASS"
        write(root / "src/ui.txt", "good\n\n")
        assert run_selected(root, "STEP-001", [ui])["status"] == "PASS"
        (root / ".harness/local/verification-proofs/STEP-001.targeted.json").unlink()
        missing = run_step_verification(root, "STEP-001")
        assert missing["status"] == "PASS" and missing["targetedReusedCount"] == 0, missing
        assert missing["executedChecks"] == [ui], missing


def targeted_group_counts() -> None:
    """Две reused группы не вычитаются из одной родительской проверки."""
    with tempfile.TemporaryDirectory(prefix="harness-review-counts-") as directory:
        root = Path(directory)
        parent, ui, backend = [f'python3 -c "print({number})"' for number in (100, 200, 300)]
        aggregate = check("all", parent, ["src/ui.txt", "src/backend.txt"])
        aggregate["groups"] = [check("ui", ui, ["src/ui.txt"]),
                               check("backend", backend, ["src/backend.txt"])]
        prepare(root, [parent], [aggregate])
        for name in ("ui", "backend"):
            write(root / f"src/{name}.txt", "first")
        assert run_step_verification(root, "STEP-001")["status"] == "PASS"
        for name in ("ui", "backend"):
            write(root / f"src/{name}.txt", "second")
        assert run_selected(root, "STEP-001", [ui, backend])["status"] == "PASS"
        result = run_step_verification(root, "STEP-001")
        assert result["status"] == "PASS" and result["verificationMode"] == "incremental", result
        assert result["executedCount"] == 0 and result["executedChecks"] == [parent], result
        assert result["targetedReusedCount"] == 2, result
        assert result["groupExecutedCount"] == 0 and result["groupReusedCount"] == 2, result
        assert verification_freshness(root, "STEP-001")["fresh"] is True


def main() -> int:
    composite_dependency()
    targeted_provenance()
    targeted_group_counts()
    print("VERIFICATION REVIEW REGRESSIONS SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
