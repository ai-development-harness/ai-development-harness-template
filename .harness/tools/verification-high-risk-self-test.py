#!/usr/bin/env python3
"""Проверить high-risk FIX на настоящем Git и canonical writers (#382).

По умолчанию создаётся synthetic проект; --canary клонирует принятую историю
переданного canary и добавляет только изолированный тестовый STEP. Импортируется
проверяемый Core, файлы установленного Harness и исходный canary не заменяются.
Reports создаются normal writers, а не подделываются положительные PASS.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from command_dispatch import start_dispatch, complete_dispatch, resume_dispatch
from completion_gate import acceptance_criteria
from execution_status import start_execution, complete_command
from harness_config import task_directory
from planning_contract import read_task, planning_context_basis, implementation_prerequisite_failures
from semantic_artifacts import write_plan_draft, write_planning_review, write_step_review
from verification import run_step_verification, verification_freshness
from verification_incremental import validate_impact_map
from verification_selective import run_selected


def write(path: Path, body: str) -> None:
    """Создать только test inputs внутри disposable fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def git(root: Path, *args: str) -> str:
    """Исполнить Git в disposable fixture, сохраняя ошибку проверки."""
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 0, (args, result.stderr)
    return result.stdout.strip()


def fixture_module():
    """Повторно использовать минимальный project scaffold Verification suite."""
    spec = importlib.util.spec_from_file_location("high_risk_fixture", Path(__file__).with_name("verification-self-test.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plan(root: Path, sid: str, commands: list[str]) -> None:
    """Создать fresh independent planning report штатными writers."""
    episode = start_execution(root, f"STEP PLAN {sid}")
    write_plan_draft(root, sid, {
        "implementationPlan": [{"title": "Проверить UI и общие зависимости",
                                "actions": ["Покрыть findings тестами и повторить critical checks."],
                                "files": ["case/**"]}],
        "verification": [{"kind": "command", "value": command} for command in commands],
    })
    result = write_planning_review(root, sid, {"verdict": "pass", "findings": [],
        "rationale": "Synthetic reviewer: inputs, shared dependencies, critical и external-state policy проверены."})
    assert result["status"] == "PASS", result
    complete_command(root, episode["rootCommand"], f"STEP PLAN {sid}", "SUCCESS")
    assert not implementation_prerequisite_failures(root, sid)


def review(root: Path, sid: str, *, location: str | None, repeated: bool = False) -> dict:
    """Создать schema-valid независимый FAIL/PASS в настоящей REVIEW execution."""
    handoff = start_dispatch(root, f"STEP REVIEW {sid}")
    assert handoff["status"] == "SEMANTIC", handoff
    findings = [] if location is None else [{
        "title": "Не хватает сценариев изменения и очистки имени",
        "severity": "high", "category": "evidence", "location": {"path": location, "line": 1},
        "scenario": {"given": "Проверки проходят без browser cases", "when": "Проверено покрытие формы",
                     "then": "Изменение и очистка имени не проверены"},
        "expected": "Оба сценария проверены", "observed": "Нет нужных browser cases",
        "impact": "PASS не доказывает форму", "repair": {"direction": "Добавить browser cases"},
        "constraints": [], "evidence": ["case/tests/ui/cases.json"],
        "evidenceBasis": {"kind": "reproduced", "source": "Отсутствующие cases в fixture",
            "preconditions": ["Первый полный набор прошёл"],
            "verification": {"method": "Прочитаны browser cases", "result": "Нужного coverage нет", "outcome": "confirmed"}},
    }]
    payload = {"verdict": "fail" if findings else "pass", "findings": findings,
               "verificationObservations": "Canonical PASS и actual command provenance проверены.",
               "rationale": "Только finding и его прямые регрессии.",
               "specializedReviews": {kind: {"status": "pass", "evidence": "Synthetic отдельная роль проверила scoped obligations."}
                                      for kind in ("security", "tests")}}
    if repeated and findings:
        payload["fixDeltaCausality"] = {"F-001": "FIX изменил shared validator, поэтому найденный дефект причинно относится к этому patch."}
    if not findings:
        payload["completion"] = {"disposition": "pass", "findings": [],
            "coverage": [{"criterion": criterion, "status": "covered",
                          "evidence": ["Post-FIX cases и свежий canonical aggregate PASS"]}
                         for criterion in acceptance_criteria(root, sid)],
            "assertions": {name: {"status": "covered" if name != "requirementObligations" else "not_applicable",
                                  "evidence": ["Ready plan и обязательные reviewers подтверждены"]}
                           for name in ("requirementObligations", "plannedScope", "specializedObligations")},
            "rationale": "Scope и исправление доказаны без повторного полного запуска."}
    result = write_step_review(root, sid, payload)
    assert result["status"] in ("PASS", "FAIL"), result
    complete_dispatch(root, root_command=handoff["rootCommand"], command=f"STEP REVIEW {sid}",
                      execution_id=handoff["executionId"], result="FAIL" if findings else "PASS")
    return result


def negative_cases(root: Path, sid: str, policy: dict, commands: list[str]) -> None:
    """Недоказанная policy/provenance/freshness обязана закрыться full fallback."""
    map_path = root / "docs/verification/issue-382.json"
    original_map = map_path.read_bytes()
    checkpoint = root / f".harness/local/verification-incremental/{sid}.json"
    original_checkpoint = checkpoint.read_bytes()
    fixed = root / f".harness/local/execution/fix-delta/{sid}.json"
    original_fix = fixed.read_bytes()

    def full(reason: str | None = None) -> dict:
        value = run_step_verification(root, sid, write_evidence=False)
        assert value["status"] == "PASS" and value["verificationMode"] == "full", value
        if reason:
            assert value["fallbackReason"] == reason, value
        return value

    without = deepcopy(policy)
    del without["steps"][sid]["highRiskFix"]
    write(map_path, json.dumps(without))
    full("RISK_REQUIRES_FULL")
    write(map_path, "{")
    full("RISK_REQUIRES_FULL")
    map_path.unlink()
    full("RISK_REQUIRES_FULL")
    map_path.write_bytes(original_map)
    changed = deepcopy(policy)
    del changed["steps"][sid]["highRiskFix"]["externalState"]["backend"]
    write(map_path, json.dumps(changed))
    assert validate_impact_map(root)
    full("RISK_REQUIRES_FULL")
    map_path.write_bytes(original_map)

    # Даже корректное сужение policy меняет independent planning basis.
    changed = deepcopy(policy)
    changed["steps"][sid]["checks"][3]["inputs"] = ["case/src/backend/**"]
    before_basis = planning_context_basis(root, sid)
    write(map_path, json.dumps(changed))
    assert planning_context_basis(root, sid) != before_basis
    assert "plan-context-basis-is-stale" in implementation_prerequisite_failures(root, sid)
    full()
    map_path.write_bytes(original_map)
    with patch.dict(os.environ, {"HARNESS_382_FIX_ENV": "changed"}):
        full("SEMANTIC_OR_ENVIRONMENT_CHANGED")

    class Future(datetime):
        """Изменить только часы freshness, сохранив inputs и environment."""
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=2)

    with patch("verification_high_risk.datetime", Future):
        full("HIGH_RISK_BASELINE_EXPIRED")
    extra = root / "case/unknown.txt"
    write(extra, "Непокрытый input\n")
    full("UNMAPPED_CHANGED_PATH")
    extra.unlink()
    altered = json.loads(original_fix)
    altered["beforeTree"] = git(root, "rev-parse", "HEAD^{tree}")
    write(fixed, json.dumps(altered))
    full("HIGH_RISK_CAPTURE_PRODUCER_MISMATCH")
    fixed.write_bytes(original_fix)
    # Capture receipt не является result cache: проверяется отдельно и не
    # может быть заменён чужой execution или отредактированным local JSON.
    from verification_high_risk import retained_fix_binding
    capture_proof = root / f".harness/local/verification-proofs/{sid}.fix.json"
    original_receipt = capture_proof.read_bytes()
    for field, invalid in (("executionId", "exec-" + "f" * 32),
                           ("fixBaselineSha256", "sha256:" + "f" * 64),
                           ("schemaVersion", 2)):
        edited = json.loads(original_receipt)
        edited[field] = invalid
        write(capture_proof, json.dumps(edited))
        assert retained_fix_binding(root, sid) is None
        full("HIGH_RISK_CAPTURE_PRODUCER_MISMATCH")
    write(capture_proof, "{")
    assert retained_fix_binding(root, sid) is None
    full("HIGH_RISK_CAPTURE_PRODUCER_MISMATCH")
    capture_proof.write_bytes(original_receipt)
    capture_proof.unlink()
    assert retained_fix_binding(root, sid) == original_fix
    capture_proof.write_bytes(original_receipt)
    changed = json.loads(original_checkpoint)
    changed["latestChecks"]["backend"]["inputBasis"] = "sha256:" + "e" * 64
    write(checkpoint, json.dumps(changed))
    full("CHECKPOINT_PRODUCER_MISMATCH")
    checkpoint.write_bytes(original_checkpoint)

    # Producer-bound targeted PASS не закрывает обязательный rerun finding.
    selected = run_selected(root, sid, [commands[0]])
    assert selected["status"] == "PASS" and selected["completionProof"] is False, selected
    current = run_step_verification(root, sid, write_evidence=False)
    assert current["verificationMode"] == "incremental" and current["targetedReusedCount"] == 0, current
    assert commands[0] in current["executedChecks"]

    # Настоящая конкурентная запись между execution и publication должна
    # остановить producer; раньше вычисленный aggregate не публикуется.
    import verification
    actual = verification._run_command
    cases = root / "case/tests/ui/cases.json"
    cases_before = cases.read_bytes()
    def concurrent(*args, **kwargs):
        value = actual(*args, **kwargs)
        write(cases, '["change"]\n')
        return value
    with patch("verification._run_command", concurrent):
        raced = run_step_verification(root, sid)
    assert raced["status"] == "BLOCKED", raced
    cases.write_bytes(cases_before)
    assert verification_freshness(root, sid)["fresh"]


def composite_case(root: Path) -> None:
    """Finding groups распространяют invalidation; critical parent exact-run."""
    from verification import verification_command_evidence
    fixture = fixture_module()
    fixture.prepare(root)
    sid = "STEP-001"
    commands = {name: f"python3 case/checks.py {name}" for name in
                ("all", "consumer", "auth", "ui", "backend", "token", "session")}
    contract = fixture.task("\n".join(fixture.command_line(commands[name]) for name in ("all", "consumer", "auth")))
    write(task_directory(root) / f"{sid}.md", contract.replace("  - none\nplan:", "  - security-sensitive\nplan:"))
    write(root / "case/src/ui/form.txt", "displayName\n")
    write(root / "case/src/backend/service.txt", "PATCH\n")
    write(root / "case/tests/ui/cases.json", "[]\n")
    write(root / "case/checks.py", '''import json, sys
from pathlib import Path
if sys.argv[1] in ("all", "ui"):
    for case in json.loads(Path("case/tests/ui/cases.json").read_text()):
        assert case in ("change", "clear")
if sys.argv[1] in ("all", "backend"):
    assert Path("case/src/backend/service.txt").read_text().strip() == "PATCH"
print(sys.argv[1])
''')
    def check(name: str, inputs: list[str], deps: list[str] | None = None) -> dict:
        return {"id": name, "command": commands[name], "inputs": inputs,
                "dependsOn": deps or [], "acceptance": ["Verification PASS."], "reusable": True}
    all_checks = check("all", ["case/src/ui/**", "case/tests/ui/**", "case/src/backend/**"])
    all_checks["groups"] = [check("ui", ["case/src/ui/**", "case/tests/ui/**"]),
                            check("backend", ["case/src/backend/**"])]
    auth = check("auth", ["case/src/auth/**"])
    auth["groups"] = [check("token", ["case/src/auth/**"]), check("session", ["case/src/auth/**"])]
    policy = {"schemaVersion": 1, "steps": {sid: {
        "checks": [all_checks, check("consumer", ["case/src/consumer/**"], ["all"]), auth],
        "infrastructure": ["case/checks.py", ".harness/manifest.yaml", "docs/verification/**"],
        "highRiskFix": {"riskChecks": {"security-sensitive": ["auth"]},
                        "externalState": {name: "none" for name in ("all", "consumer", "auth")},
                        "maxAgeSeconds": 3600}}}}
    manifest = root / ".harness/manifest.yaml"
    write(manifest, manifest.read_text(encoding="utf-8") + "\nverification:\n  impactMap: docs/verification/issue-382.json\n")
    write(root / "docs/verification/issue-382.json", json.dumps(policy))
    plan(root, sid, [commands[n] for n in ("all", "consumer", "auth")])
    initial = run_step_verification(root, sid)
    assert initial["status"] == "PASS" and initial["groupExecutedCount"] == 4, initial
    review(root, sid, location="case/src/ui/form.txt")
    fix = start_dispatch(root, f"STEP FIX {sid}")
    assert fix["status"] == "SEMANTIC", fix
    write(root / "case/tests/ui/cases.json", '["change", "clear"]\n')
    for _ in range(2):
        result = run_step_verification(root, sid)
        assert result["status"] == "PASS" and result["verificationMode"] == "incremental", result
        assert result["executedCount"] == 2 and result["groupExecutedCount"] == 3 and result["groupReusedCount"] == 1, result
        rows = {item["command"]: item for item in result["commands"]}
        assert rows[commands["all"]]["composite"] and not rows[commands["auth"]].get("composite"), rows
        assert verification_command_evidence(root, sid, commands["all"])["fresh"] is False
        assert verification_command_evidence(root, sid, commands["auth"])["fresh"] is True
        assert commands["consumer"] in result["executedChecks"]


def exercise(root: Path, sid: str) -> dict:
    """Полный PASS → FAIL → повторные FIX → incremental PASS → delta REVIEW."""
    fixture = fixture_module()
    names = ["ui", "lint", "types", "backend", "migration", "auth", "migration-safety", "provisioning"]
    commands = [f"python3 case/checks.py {name}" for name in names]
    task = fixture.task("\n".join(fixture.command_line(c) for c in commands)).replace("STEP-001", sid)
    task = task.replace("  - none\nplan:", "  - security-sensitive\n  - data-migration\nplan:")
    step = task_directory(root) / f"{sid}.md"
    write(step, task)
    write(root / "case/src/ui/form.txt", "displayName\n")
    write(root / "case/src/backend/service.txt", "PATCH\n")
    write(root / "case/src/shared/validator.py", "def trim(value):\n    return value.strip()\n")
    write(root / "case/tests/ui/cases.json", "[]\n")
    write(root / "case/checks.py", '''import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src/shared"))
sys.dont_write_bytecode = True
from validator import trim
assert trim("  Имя  ") == "Имя"
assert trim("  ") == ""
if sys.argv[1] == "ui":
    for case in json.loads(Path("case/tests/ui/cases.json").read_text()):
        assert case in ("change", "clear")
print(sys.argv[1])
''')
    manifest = root / ".harness/manifest.yaml"
    write(manifest, manifest.read_text(encoding="utf-8")
          + "\nverification:\n  # Project-owned opt-in fixture. Пример: docs/verification/issue-382.json\n  impactMap: docs/verification/issue-382.json\n")
    shared = ["case/src/shared/**"]
    policy = {"schemaVersion": 1, "steps": {sid: {"checks": [
        {"id": name, "command": command,
         "inputs": ["case/src/ui/**", "case/tests/ui/**"] + shared if name in ("ui", "lint", "types")
                   else [f"case/src/{name}/**"] + shared,
         "dependsOn": ["ui"] if name in ("lint", "types") else [],
         "acceptance": ["Verification PASS."], "reusable": True}
        for name, command in zip(names, commands)],
        "infrastructure": ["case/checks.py", ".harness/manifest.yaml", "docs/verification/**", "package-lock.json"],
        "highRiskFix": {"riskChecks": {"security-sensitive": ["auth"], "data-migration": ["migration-safety"]},
                        "externalState": {name: "always-run" if name in ("auth", "provisioning") else "none" for name in names},
                        "maxAgeSeconds": 3600},
    }}}
    map_path = root / "docs/verification/issue-382.json"
    write(map_path, json.dumps(policy))
    plan(root, sid, commands)
    assert not validate_impact_map(root)
    initial = run_step_verification(root, sid)
    assert initial["status"] == "PASS" and initial["verificationMode"] == "full", initial
    outside = run_step_verification(root, sid)
    assert outside["verificationMode"] == "full" and outside["fallbackReason"] == "HIGH_RISK_ACTIVE_FIX_REQUIRED", outside
    source_review = review(root, sid, location="case/src/ui/form.txt")
    # REVIEW resolver нормализует каталог, а caller может передать иной alias.
    # Lexical alias воспроизводит Windows RUNNER~1/runneradmin без symlink прав.
    from review_findings import latest_structured_findings
    alias_directory = root / "lexical-root-alias"
    alias_directory.mkdir()
    aliased = latest_structured_findings(alias_directory / "..", sid)
    assert aliased["report"] == source_review["report"], aliased
    alias_directory.rmdir()
    fix = start_dispatch(root, f"STEP FIX {sid}")
    assert fix["status"] == "SEMANTIC", fix
    index = (root / ".git/index").read_bytes()
    write(root / "case/tests/ui/cases.json", '["change", "clear"]\n')
    first = run_step_verification(root, sid)
    assert first["status"] == "PASS" and first["verificationMode"] == "incremental", first
    assert first["executedChecks"] == [c for n, c in zip(names, commands) if n not in ("backend", "migration")], first
    assert first["reusedCount"] == 2 and "ui" in first["invalidatedChecks"], first
    assert (root / ".git/index").read_bytes() == index
    negative_cases(root, sid, policy, commands)
    checkpoint = root / f".harness/local/verification-incremental/{sid}.json"
    baseline = json.loads(checkpoint.read_text(encoding="utf-8"))["fullBaseline"]["tree"]

    # Resume сохраняет pre-FIX tree; dirty/staged/untracked delta считается
    # от исходного полного baseline, а не только от последнего маленького FIX.
    resumed = resume_dispatch(root, root_command=fix["rootCommand"])
    assert resumed["executionId"] == fix["executionId"], resumed
    write(root / "case/tests/ui/new.json", "{}\n")
    git(root, "add", "case/tests/ui/new.json")
    write(root / "case/tests/ui/new.json", '{"dirty": true}\n')
    write(root / "case/tests/ui/untracked.json", "{}\n")
    second = run_step_verification(root, sid)
    assert second["verificationMode"] == "incremental" and second["reusedCount"] == 2, second
    assert json.loads(checkpoint.read_text(encoding="utf-8"))["fullBaseline"]["tree"] == baseline
    git(root, "mv", "case/tests/ui/new.json", "case/tests/ui/renamed.json")
    (root / "case/tests/ui/untracked.json").unlink()
    moved = run_step_verification(root, sid)
    assert moved["verificationMode"] == "incremental", moved

    # Risk flags сохраняются; boundary inputs запускают предусмотренные
    # exact safety checks, сохраняя доказанно независимый backend PASS.
    write(root / "case/src/auth/policy.txt", "Проверить новую auth boundary\n")
    write(root / "case/src/migration-safety/schema.txt", "Проверить migration boundary\n")
    boundary = run_step_verification(root, sid)
    assert boundary["verificationMode"] == "incremental" and boundary["reusedCount"] == 2, boundary
    assert read_task(root, sid)["frontmatter"]["risk_flags"] == ["security-sensitive", "data-migration"]

    # Реальная общая зависимость затрагивает все потребители, включая backend.
    write(root / "case/src/shared/validator.py", "def trim(value):\n    return value.lstrip().rstrip()\n")
    shared_result = run_step_verification(root, sid)
    assert shared_result["verificationMode"] == "incremental" and shared_result["executedCount"] == 8, shared_result
    assert shared_result["reusedCount"] == 0

    # Forced full согласуется по результату с тем же проверенным subject.
    forced = run_step_verification(root, sid, force_full=True)
    assert forced["status"] == shared_result["status"] == "PASS" and forced["executedCount"] == 8
    # Явный full обновляет квалификацию, сохраняя тот же pre-FIX capture:
    # completion не должен скрыто повторять полный набор ещё раз.
    after_full = run_step_verification(root, sid)
    assert after_full["verificationMode"] == "incremental", after_full

    # Полный fallback при tampered bytes и неизвестной зависимости.
    altered = json.loads(checkpoint.read_text(encoding="utf-8"))
    altered["latestChecks"]["backend"]["inputBasis"] = "sha256:" + "f" * 64
    write(checkpoint, json.dumps(altered))
    tamper = run_step_verification(root, sid)
    assert tamper["verificationMode"] == "full" and tamper["fallbackReason"] == "CHECKPOINT_PRODUCER_MISMATCH", tamper

    # Canonical FAIL расходует результаты, сохраняя исходный capture receipt.
    # Новый full PASS заново доказывает все команды и восстанавливает только pin.
    capture_proof = root / f".harness/local/verification-proofs/{sid}.fix.json"
    capture_before = capture_proof.read_bytes()
    cases = root / "case/tests/ui/cases.json"
    saved_cases = cases.read_bytes()
    write(cases, '["broken"]\n')
    canonical_failed = run_step_verification(root, sid)
    assert canonical_failed["status"] == "FAIL", canonical_failed
    assert capture_proof.read_bytes() == capture_before
    cases.write_bytes(saved_cases)
    canonical_repaired = run_step_verification(root, sid)
    assert canonical_repaired["status"] == "PASS" and canonical_repaired["verificationMode"] == "full", canonical_repaired
    qualified_again = run_step_verification(root, sid, write_evidence=False)
    assert qualified_again["verificationMode"] == "incremental" and qualified_again["reusedCount"] == 2, qualified_again

    # Более новый реальный targeted FAIL уничтожает прежний trusted cache.
    # Capture receipt остаётся тем же и не делает старый PASS пригодным.
    write(cases, '["broken"]\n')
    failed_feedback = run_selected(root, sid, [commands[0]])
    assert failed_feedback["status"] == "FAIL", failed_feedback
    assert not checkpoint.exists()
    assert capture_proof.read_bytes() == capture_before
    failed_full = run_step_verification(root, sid)
    assert failed_full["status"] == "FAIL" and failed_full["verificationMode"] == "full", failed_full
    cases.write_bytes(saved_cases)
    repaired = run_step_verification(root, sid)
    assert repaired["status"] == "PASS" and repaired["verificationMode"] == "full", repaired
    assert capture_proof.read_bytes() == capture_before
    assert verification_freshness(root, sid)["fresh"]

    # Финальный lifecycle использует НОВЫЙ настоящий FAIL/FIX, чей pre-FIX
    # pin подтверждает текущий producer. Старые immutable reports не меняются.
    done = complete_dispatch(root, root_command=fix["rootCommand"], command=f"STEP FIX {sid}",
                             execution_id=fix["executionId"], result="SUCCESS")
    assert done["status"] == "DONE", done
    # Fresh full PASS после FAIL уже переквалифицировал все проверки.
    # Completion того же subject не должен скрыто повторять full ещё раз.
    recovered_checkpoint = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert recovered_checkpoint["fullBaseline"]["runAt"] == repaired["runAt"], recovered_checkpoint
    recovery_evidence = step.read_text(encoding="utf-8")
    assert "- Verification mode: incremental\n" in recovery_evidence, done
    assert f"- Incremental executed checks: {len(names) - 2}\n" in recovery_evidence, done
    assert "- Incremental reused checks: 2\n" in recovery_evidence, done
    review(root, sid, location="case/src/ui/form.txt", repeated=True)
    final_fix = start_dispatch(root, f"STEP FIX {sid}")
    assert final_fix["status"] == "SEMANTIC", final_fix
    write(root / "case/tests/ui/cases.json", '["clear", "change"]\n')
    final = complete_dispatch(root, root_command=final_fix["rootCommand"], command=f"STEP FIX {sid}",
                              execution_id=final_fix["executionId"], result="SUCCESS")
    assert final["status"] == "DONE", final
    assert "- Verification mode: incremental\n" in step.read_text(encoding="utf-8"), final
    assert verification_freshness(root, sid)["fresh"]
    review(root, sid, location=None)
    assert read_task(root, sid)["frontmatter"]["status"] == "completed"
    return {"status": "PASS", "testOnlyExecuted": first["executedCount"],
            "testOnlyReused": first["reusedCount"], "sharedExecuted": shared_result["executedCount"],
            "completed": True}


def main() -> int:
    """Прогнать один bounded lifecycle без изменения принятой базы canary."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--canary", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="high-risk-verification-") as directory:
        root = Path(directory) / "project"
        if args.canary:
            git(args.canary, "clone", "--quiet", "--no-local", str(args.canary.resolve()), str(root))
            git(root, "config", "user.email", "high-risk@example.invalid")
            git(root, "config", "user.name", "High Risk Fixture")
        else:
            root.mkdir()
            fixture_module().prepare(root)
        result = exercise(root, "STEP-910" if args.canary else "STEP-001")
        if not args.canary:
            grouped = Path(directory) / "grouped"
            grouped.mkdir()
            composite_case(grouped)
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
