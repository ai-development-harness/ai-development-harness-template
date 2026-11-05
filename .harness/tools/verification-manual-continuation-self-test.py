#!/usr/bin/env python3
"""Регрессия #385: MANUAL_REQUIRED продолжается через canonical dispatcher.

Счётчики в игнорируемом local state показывают реальные side effects. Ready
план и producer proof создаются штатными writers, положительный путь без моков.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
from self_test_fixture import set_fixture_verification
import tempfile
import subprocess
import sys
from unittest.mock import patch

from command_dispatch import start_dispatch, complete_dispatch, resume_dispatch
from completion_gate import step_completion_proof, acceptance_criteria
from execution_status import start_execution, complete_command
from semantic_artifacts import write_plan_draft, write_planning_review, write_step_review
from verification import (parse_verification, run_step_verification, verification_freshness,
                          verification_contract_basis, verification_context_basis,
                          verification_subject_revision, write_verification_evidence, VerificationInputsStale)
from harness_config import verification_command_timeout_seconds
from verification_resume import continuation_plan, NON_REUSABLE_FLAGS, RESUME_TTL_SECONDS

SID = "STEP-001"
CHECK = "Сверить результат с контрактом."
OBSERVATIONS = [{"check": CHECK, "status": "PASS", "observed": "Результат совпадает с контрактом."}]
COMMANDS = ["python3 case/check.py local", "python3 case/check.py external"]


def fixture_module():
    """Загрузить существующий минимальный synthetic scaffold."""
    spec = importlib.util.spec_from_file_location("manual_fixture", Path(__file__).with_name("verification-self-test.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def setup(root: Path, flag: str, *, repeat: bool = False) -> dict:
    """Подготовить STEP с reviewed Ready plan и явной local/external policy."""
    fixture = fixture_module()
    fixture.prepare(root)
    case = root / "case/check.py"
    case.parent.mkdir()
    case.write_text('''import sys
from pathlib import Path
p = Path(".harness/local/count-" + sys.argv[1])
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(str(int(p.read_text()) + 1) if p.exists() else "1")
print(sys.argv[1])
sys.exit(9 if Path(".harness/local/force-fail").exists() else 0)
''', encoding="utf-8")
    step = root / "planning/tasks/STEP-001.md"
    step.write_text(fixture.task("\n".join(fixture.command_line(c) for c in COMMANDS)
                                + "\n- manual: " + CHECK).replace("  - none\nplan:", f"  - {flag}\nplan:"), encoding="utf-8")
    policy = {"readOnly": True, "localCommands": COMMANDS[:1] if repeat else COMMANDS,
              "repeatCommands": COMMANDS[1:] if repeat else []}
    manifest = root / ".harness/manifest.yaml"
    manifest.write_text(manifest.read_text(encoding="utf-8")
                        .replace("  initialized: false", "  initialized: true")
                        .replace("  name: null", "  name: manual-continuation-fixture")
                        .replace("  initializedAt: null", '  initializedAt: "2026-11-05T12:00:00Z"'),
                        encoding="utf-8")
    set_fixture_verification(root, {"manualContinuation": {SID: policy}})
    episode = start_execution(root, f"STEP PLAN {SID}")
    write_plan_draft(root, SID, {
        "implementationPlan": [{"title": "Проверить результат", "actions": ["Выполнить локальные проверки."], "files": ["case/**"]}],
        "verification": parse_verification(root, SID),
    })
    report = write_planning_review(root, SID, {"verdict": "pass", "findings": [],
        "rationale": "Локальные команды и read-only observations проверены; external state требует повтора."})
    assert report["status"] == "PASS", report
    complete_command(root, episode["rootCommand"], f"STEP PLAN {SID}", "SUCCESS")
    handoff = start_dispatch(root, f"STEP IMPLEMENT {SID}")
    assert handoff["status"] == "SEMANTIC", handoff
    pending = complete(root, handoff)
    assert pending["reasonCode"] == "VERIFICATION_MANUAL_REQUIRED", pending
    assert counts(root) == [1, 1]
    next_plan = pending["verification"]["continuationPlan"]
    assert next_plan["executedChecks"] == policy["repeatCommands"], next_plan
    assert next_plan["reusedChecks"] == policy["localCommands"], next_plan
    return handoff


def complete(root: Path, handoff: dict, *, observations=None) -> dict:
    """Завершить только exact producer execution через штатную boundary."""
    return complete_dispatch(root, root_command=handoff["rootCommand"], command=handoff["command"],
                             execution_id=handoff["executionId"], result="SUCCESS",
                             details={"manualVerification": observations} if observations is not None else None)


def counts(root: Path) -> list[int]:
    """Прочитать наблюдаемые счётчики, а не внутренние selection flags."""
    return [int((root / f".harness/local/count-{name}").read_text()) for name in ("local", "external")]


def preview(root: Path) -> dict:
    """Вычислить тот же read-only preflight, что предоставляет public CLI."""
    return continuation_plan(root, SID, contract=verification_contract_basis(root, SID),
                             context=verification_context_basis(root, SID),
                             subject=verification_subject_revision(root, SID), names=COMMANDS,
                             timeout=verification_command_timeout_seconds(root))


def negatives(root: Path) -> None:
    """Порча/freshness/producer нарушения обязаны запрещать reuse до запуска."""
    checkpoint = root / ".harness/local/verification-resume/STEP-001.json"
    proof = root / ".harness/local/verification-proofs/STEP-001.json"
    saved, producer = checkpoint.read_bytes(), proof.read_bytes()
    cached = json.loads(saved)
    assert len(preview(root)["reused"]) == 2
    for key, value in (("schemaVersion", 0), ("recordedAt", 0),
                       ("recordedAt", float("nan")), ("subjectRevision", {}),
                       ("contractBasis", "changed"), ("contextBasis", "changed"),
                       ("timeoutSeconds", 1), ("environmentBasis", "changed"),
                       ("execution", {}), ("commands", [None]), ("policy", {})):
        modified = deepcopy(cached)
        modified[key] = value
        checkpoint.write_text(json.dumps(modified), encoding="utf-8")
        assert not preview(root)["reused"], key
    checkpoint.write_bytes(saved)
    with patch("verification_resume.time.time", return_value=cached["recordedAt"] + RESUME_TTL_SECONDS + 1):
        assert preview(root)["reasonCode"] == "MANUAL_CONTINUATION_EXPIRED"
    # patch.dict(os.environ) восстанавливает всю mapping через clear/update.
    # На Windows _wputenv удаляет пустые values из native environment, хотя
    # Python mapping ещё хранит их: @link https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/putenv-wputenv
    variable = "ISSUE385_ENVIRONMENT"
    while variable in os.environ:
        variable += "_TEST"
    os.environ[variable] = "changed"
    try:
        changed = preview(root)
        assert not changed["reused"] and changed["changedInputs"] == ["environmentBasis"], changed
    finally:
        del os.environ[variable]
    with patch("verification_resume._environment_basis", return_value="different-toolchain"):
        assert not preview(root)["reused"]
    with patch("verification_resume._execution", side_effect=ValueError("ambiguous")):
        assert not preview(root)["reused"]
    for invalid in (b"{", b"[]", b"null"):
        checkpoint.write_bytes(invalid)
        assert not preview(root)["reused"]
    checkpoint.unlink()
    assert not preview(root)["reused"]
    # Symlink проверяется только там, где ОС даёт создать его без привилегий.
    try:
        checkpoint.symlink_to(proof)
    except OSError:
        pass
    else:
        assert not preview(root)["reused"]
        checkpoint.unlink()
    checkpoint.write_bytes(saved)
    for invalid in (b"{", b"[]", producer.replace(b'MANUAL_REQUIRED', b'FAIL')):
        proof.write_bytes(invalid)
        assert not preview(root)["reused"]
    proof.unlink()
    assert not preview(root)["reused"]
    proof.write_bytes(producer)
    source = root / "case/check.py"
    original = source.read_bytes()
    source.write_bytes(original + "\n# Изменён subject.\n".encode())
    assert not preview(root)["reused"]
    source.write_bytes(original)
    manifest = root / ".harness/manifest.yaml"
    original_manifest = manifest.read_bytes()
    manifest.write_bytes(original_manifest.replace(b'readOnly: true', b'readOnly: false'))
    assert preview(root)["reasonCode"] == "MANUAL_CONTINUATION_STATE_CHANGED"
    set_fixture_verification(root, None)
    assert preview(root)["reasonCode"] == "MANUAL_CONTINUATION_POLICY_REQUIRED"
    manifest.write_bytes(original_manifest.replace(COMMANDS[0].encode(), b"unknown-command"))
    assert preview(root)["reasonCode"] == "MANUAL_CONTINUATION_COMMAND_COVERAGE_INVALID"
    manifest.write_bytes(original_manifest)
    step = root / "planning/tasks/STEP-001.md"
    original_step = step.read_bytes()
    for old, new in ((b"Verification PASS.", b"New acceptance."),
                     (COMMANDS[0].encode(), b"python3 case/check.py other"),
                     (b"- Status: MANUAL_REQUIRED", b"- Status: FAIL")):
        step.write_bytes(original_step.replace(old, new))
        assert not preview(root)["reused"]
    step.write_bytes(original_step)
    # Race после selection, но до Evidence CAS: повреждённый producer нельзя
    # опубликовать новым aggregate PASS даже при прежнем Git subject.
    selected = run_step_verification(root, SID, manual_results=OBSERVATIONS, write_evidence=False)
    assert selected["status"] == "PASS" and selected["automatedResumed"], selected
    proof.write_bytes(b"{}")
    try:
        write_verification_evidence(root, SID, selected)
    except VerificationInputsStale:
        pass
    else:
        raise AssertionError("Producer race разрешил публикацию PASS")
    proof.write_bytes(producer)
    assert counts(root) == [1, 1]


def review_completion(root: Path) -> None:
    """Проверить переход synthetic PASS через существующие REVIEW/completion gates."""
    handoff = start_dispatch(root, f"STEP REVIEW {SID}")
    assert handoff["status"] == "SEMANTIC", handoff
    evidence = "Счётчики равны единице; producer-bound PASS свежий, local/external policy проверена."
    report = write_step_review(root, SID, {
        "verdict": "pass", "findings": [], "rationale": evidence,
        "verificationObservations": evidence,
        "specializedReviews": {kind: {"status": "pass", "evidence": evidence}
                               for kind in ("security", "tests")},
        "completion": {"disposition": "pass", "findings": [],
            "coverage": [{"criterion": criterion, "status": "covered", "evidence": [evidence]}
                         for criterion in acceptance_criteria(root, SID)],
            "assertions": {kind: {"status": "not_applicable" if kind == "requirementObligations" else "covered",
                                  "evidence": [evidence]}
                           for kind in ("requirementObligations", "plannedScope", "specializedObligations")},
            "rationale": evidence},
    })
    assert report["status"] == "PASS", report
    assert report["stepCompletion"]["completed"], report
    # Штатный writer уже подтвердил completed STEP; resolver согласует root
    # по durable proof без повторного semantic completion.
    recovered = resume_dispatch(root, root_command=handoff["rootCommand"])
    assert recovered["status"] == "DONE", recovered
    proof = step_completion_proof(root, SID)
    assert proof["complete"], proof
    assert counts(root) == [1, 1]


def main() -> int:
    """Параметризовать каждый guard flag и доказать адресный external повтор."""
    if "--environment-child" not in sys.argv[1:]:
        # Пустая переменная приходит через CreateProcess/env block, а не через
        # Windows putenv. Old bulk restore воспроизводимо теряет её до restart.
        environment = dict(os.environ, HARNESS_MANUAL_EMPTY_ENV="")
        return subprocess.run([sys.executable, str(Path(__file__).resolve()),
                               "--environment-child"], env=environment, check=False).returncode
    assert os.environ.get("HARNESS_MANUAL_EMPTY_ENV") == ""
    with tempfile.TemporaryDirectory(prefix="harness-manual-continuation-") as directory:
        for flag in sorted(NON_REUSABLE_FLAGS):
            root = Path(directory) / flag
            root.mkdir()
            handoff = setup(root, flag)
            checkpoint = root / ".harness/local/verification-resume/STEP-001.json"
            original = json.loads(checkpoint.read_bytes())
            negatives(root)
            resumed = resume_dispatch(root, root_command=handoff["rootCommand"])
            assert resumed["executionId"] == handoff["executionId"], resumed
            assert checkpoint.read_bytes() == (json.dumps(original, sort_keys=True) + "\n").encode()
            # Новый процесс использует public CLI, checkpoint и producer с диска.
            process = subprocess.run([sys.executable, str(root / ".harness/tools/verify-step.py"),
                                      SID, "--continuation-plan"], cwd=root,
                                     capture_output=True, text=True, check=True)
            assert json.loads(process.stdout)["executedChecks"] == [], process.stdout
            assert counts(root) == [1, 1]
            result = complete(root, handoff, observations=OBSERVATIONS)
            assert result["status"] == "DONE", result
            assert counts(root) == [1, 1], (flag, result)
            fresh = verification_freshness(root, SID)
            assert fresh["fresh"], fresh
            new_proof = json.loads((root / ".harness/local/verification-proofs/STEP-001.json").read_bytes())
            assert new_proof["status"] == "PASS"
            assert not checkpoint.exists()
            # Исходные per-command observations сохранены в новом aggregate.
            text = (root / "planning/tasks/STEP-001.md").read_text(encoding="utf-8")
            for command in original["commands"]:
                assert f"  - Duration ms: {command['durationMs']}" in text
                assert command["stdoutSha256"] in text
            if flag == "external-integration":
                review_completion(root)
        root = Path(directory) / "mutable-external"
        root.mkdir()
        handoff = setup(root, "external-integration", repeat=True)
        plan = preview(root)
        assert plan["executedChecks"] == COMMANDS[1:]
        assert plan["reasonCode"] == "MANUAL_CONTINUATION_EXTERNAL_STATE"
        final = complete(root, handoff, observations=OBSERVATIONS)
        assert final["status"] == "DONE", final
        assert counts(root) == [1, 2]
        assert verification_freshness(root, SID)["fresh"]
        for scenario in ("corrupt", "state-changing", "previous-fail"):
            root = Path(directory) / scenario
            root.mkdir()
            handoff = setup(root, "security-sensitive")
            if scenario == "corrupt":
                (root / ".harness/local/verification-resume/STEP-001.json").write_text("[]")
            elif scenario == "state-changing":
                manifest = root / ".harness/manifest.yaml"
                manifest.write_bytes(manifest.read_bytes().replace(b"readOnly: true", b"readOnly: false"))
            else:
                marker = root / ".harness/local/force-fail"
                marker.touch()
                failed = complete(root, handoff)
                assert failed["reasonCode"] == "VERIFICATION_FAIL", failed
                assert not (root / ".harness/local/verification-resume/STEP-001.json").exists()
                marker.unlink()
            final = complete(root, handoff, observations=OBSERVATIONS)
            assert final["status"] == "DONE", final
            expected = 3 if scenario == "previous-fail" else 2
            assert counts(root) == [expected, expected], scenario
            assert verification_freshness(root, SID)["fresh"]
    print("VERIFICATION MANUAL CONTINUATION SELF-TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
