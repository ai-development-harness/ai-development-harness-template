#!/usr/bin/env python3
"""Узкое исключение для Verification высокорискового FIX (#382).

Policy принадлежит проекту и входит в independent planning basis. Этот модуль
проверяет полномочия FIX и invalidation findings; общий incremental engine
по-прежнему доказывает неизменность inputs, environment и producer checkpoint.
Любая недоказанная связь приводит к полному прогону, а не к разрешению skip.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from verification_resume import NON_REUSABLE_FLAGS


def _digest(data: bytes) -> str:
    """Сопоставить exact bytes с clone-local producer pin без записи данных."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def validate_policy(policy: Any, checks: list[dict[str, Any]]) -> None:
    """Отклонить неполный риск/state контракт до выбора каких-либо проверок."""
    if not isinstance(policy, dict) or set(policy) != {
        "riskChecks", "externalState", "maxAgeSeconds",
    }:
        raise ValueError("HIGH_RISK_POLICY_SCHEMA_INVALID")
    ids = {item["id"] for item in checks}
    risks = policy["riskChecks"]
    if (not isinstance(risks, dict) or not risks
            or set(risks) - NON_REUSABLE_FLAGS
            or any(not isinstance(value, list) or not value
                   or any(not isinstance(cid, str) or cid not in ids for cid in value)
                   or len(set(value)) != len(value) for value in risks.values())):
        raise ValueError("HIGH_RISK_OBLIGATIONS_INVALID")
    state = policy["externalState"]
    if (not isinstance(state, dict) or set(state) != ids
            or any(value not in ("none", "always-run") for value in state.values())):
        raise ValueError("HIGH_RISK_EXTERNAL_STATE_UNDECLARED")
    age = policy["maxAgeSeconds"]
    if type(age) is not int or not 1 <= age <= 86400:
        raise ValueError("HIGH_RISK_MAX_AGE_INVALID")


def planning_policy_basis(root: Path, step_id: str) -> dict[str, str] | None:
    """Включить весь opt-in файл в planning context, включая неизвестные keys.

    Обычные карты сохраняют старый planning contract. Для high-risk opt-in
    изменение даже соседнего STEP policy требует fresh PLAN и полного PASS.
    """
    from harness_config import get, load_manifest, resolve_repo_path
    configured = get(load_manifest(root), "verification.impactMap")
    if configured is None:
        return None
    try:
        path = resolve_repo_path(root, configured, label="verification.impactMap")
        if path.is_symlink():
            return None
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError):
        # Обычная broken map должна по-прежнему давать full fallback.
        # У ранее opt-in STEP исчезнувший component stale-ит Ready plan.
        return None
    steps = data.get("steps") if isinstance(data, dict) else None
    selected = steps.get(step_id, {}) if isinstance(steps, dict) else {}
    if not isinstance(selected, dict) or "highRiskFix" not in selected:
        return None
    return {"path": path.relative_to(root.resolve()).as_posix(), "sha256": _digest(raw)}


def _capture_proof_path(root: Path, step_id: str) -> Path:
    """Разрешить существующий proof namespace без перехода через symlink."""
    from verification_proof import _safe_proof_path
    path = _safe_proof_path(root, step_id).with_suffix(".fix.json")
    if path.is_symlink():
        raise ValueError("HIGH_RISK_CAPTURE_PROOF_SYMLINK")
    return path


def _capture_receipt(step_id: str, execution_id: str, raw: bytes) -> dict[str, Any]:
    """Описать только происхождение capture; результаты проверок сюда не входят."""
    return {"schemaVersion": 1, "producer": "deterministic-fix-capture",
            "stepId": step_id, "executionId": execution_id,
            "fixBaselineSha256": _digest(raw)}


def _capture_binding_status(root: Path, step_id: str, execution_id: str, raw: bytes) -> bool | None:
    """Отличить legacy absence от повреждённого существующего receipt.

    Legacy может использовать ещё действующий PASS pin. Повреждённый receipt
    нельзя маскировать этим fallback: нужен новый capture либо полный режим.
    """
    path = _capture_proof_path(root, step_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_bytes()) == _capture_receipt(step_id, execution_id, raw)
    except (OSError, ValueError):
        return False


def bind_fix(root: Path, step_id: str, raw: bytes, *, capture: bool = False) -> None:
    """Закрепить capture в PASS; отдельный receipt выдаёт только capture owner.

    Receipt переживает invalidation результатов и FAIL, но не доказывает PASS.
    Evidence writer переносит уже проверенную связь только в новый full PASS,
    не создавая receipt из произвольно изменённого local JSON после правок.
    """
    from document_contract import atomic_write_text
    from execution_status import active_execution_for_command, execution_state_lock
    from verification_proof import _safe_proof_path, verification_proof_error
    try:
        with execution_state_lock(root):
            if planning_policy_basis(root, step_id) is None:
                return
            path = _safe_proof_path(root, step_id)
            original = path.read_bytes()
            proof = json.loads(original)
            if (proof.get("producer") != "deterministic-step-verification"
                    or proof.get("stepId") != step_id or proof.get("status") != "PASS"):
                return
            receipt = None
            if capture:
                from planning_contract import read_task
                from verification import EVIDENCE_START, EVIDENCE_END
                execution = active_execution_for_command(root, f"STEP FIX {step_id}")
                data = json.loads(raw)
                section = read_task(root, step_id)["sections"].get("Evidence", "")
                block = re.search(re.escape(EVIDENCE_START) + r"(.*?)" + re.escape(EVIDENCE_END), section, re.S)
                if (not execution or data.get("executionId") != execution["executionId"]
                        or data.get("stepId") != step_id or data.get("complete") is not False
                        or block is None or verification_proof_error(
                            root, step_id, block=block.group(1), status="PASS") is not None):
                    return
                receipt = _capture_receipt(step_id, execution["executionId"], raw)
                receipt_path = _capture_proof_path(root, step_id)
            proof["fixBaselineSha256"] = _digest(raw)
            atomic_write_text(path, json.dumps(proof, sort_keys=True, ensure_ascii=False) + "\n",
                              expected_bytes=original)
            if receipt is not None:
                # Только успешный CAS canonical producer разрешает выдать
                # capture receipt. Crash до этой записи безопасно теряет recovery.
                atomic_write_text(receipt_path, json.dumps(receipt, sort_keys=True) + "\n")
    except (OSError, ValueError, TypeError, AttributeError):
        return


def retained_fix_binding(root: Path, step_id: str) -> bytes | None:
    """Перенести только аутентифицированный capture при новом PASS.

    FAIL/targeted FAIL расходуют result proof, сохраняя отдельный capture receipt.
    Его отсутствие либо порча не дают права пересоздать pre-FIX snapshot.
    """
    from execution_status import active_execution_for_command
    from fix_delta import _load, _path
    from verification_proof import _safe_proof_path
    try:
        execution = active_execution_for_command(root, f"STEP FIX {step_id}")
        fix = _load(root, step_id)
        if not execution or not fix or fix.get("complete") is not False or fix.get("executionId") != execution["executionId"]:
            return None
        raw = _path(root, step_id).read_bytes()
        binding = _capture_binding_status(root, step_id, execution["executionId"], raw)
        if binding is not None:
            return raw if binding else None
        # Совместимость с capture до появления отдельного receipt: действующий
        # PASS pin пригоден, но утраченный pin нельзя восстановить догадкой.
        proof = json.loads(_safe_proof_path(root, step_id).read_bytes())
        if proof.get("status") == "PASS" and proof.get("fixBaselineSha256") == _digest(raw):
            return raw
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def prepare_fix(
    root: Path, step_id: str, policy: dict[str, Any],
    checkpoint: dict[str, Any], flags: list[str],
) -> dict[str, Any]:
    """Доказать настоящий FAIL → активный FIX и обязательный fresh execution.

    Не доверяем самодекларированному имени execution или findings в local JSON:
    проверяются current dispatcher owner, bytes REVIEW в pre-FIX tree, его
    schema, planning PASS, полный baseline proof и producer pin FIX snapshot.
    """
    from execution_status import active_execution_for_command
    from fix_delta import _load, _path, _run
    from planning_contract import read_task, implementation_prerequisite_failures, planning_context_basis
    from document_contract import parse_document
    from review_contract import validate_review_report
    from review_findings import latest_structured_findings
    from verification_incremental import _match
    from verification_proof import _safe_proof_path, _digest as block_digest
    from verification import EVIDENCE_START, EVIDENCE_END

    option = policy.get("highRiskFix")
    if not isinstance(option, dict) or policy.get("reuse") is not None:
        raise ValueError("RISK_REQUIRES_FULL")
    if read_task(root, step_id)["frontmatter"].get("status") != "in_progress":
        raise ValueError("HIGH_RISK_ACTIVE_STEP_REQUIRED")
    missing = implementation_prerequisite_failures(root, step_id)
    if missing:
        raise ValueError("HIGH_RISK_PLANNING_REVIEW_REQUIRED")
    excluded = set(flags) & NON_REUSABLE_FLAGS
    if not excluded.issubset(option["riskChecks"]):
        raise ValueError("HIGH_RISK_OBLIGATIONS_INCOMPLETE")
    execution = active_execution_for_command(root, f"STEP FIX {step_id}")
    fix = _load(root, step_id)
    if (not execution or not fix or fix.get("complete") is not False
            or fix.get("executionId") != execution.get("executionId")
            or fix.get("observation") is not None):
        raise ValueError("HIGH_RISK_ACTIVE_FIX_REQUIRED")
    raw = _path(root, step_id).read_bytes()
    receipt = {"fixBaselineSha256": _digest(raw), "executionId": fix["executionId"]}
    if _capture_binding_status(root, step_id, execution["executionId"], raw) is False:
        raise ValueError("HIGH_RISK_CAPTURE_PRODUCER_MISMATCH")
    proof = json.loads(_safe_proof_path(root, step_id).read_bytes())
    if (proof.get("fixBaselineSha256") != receipt["fixBaselineSha256"]
            and checkpoint.get("highRiskFixReceipt") != receipt):
        raise ValueError("HIGH_RISK_FIX_PRODUCER_MISMATCH")
    review = latest_structured_findings(root, step_id)
    report = root / review["report"]
    review_meta = parse_document(report)["frontmatter"]
    if (review["verdict"] != "fail" or not review["findings"]
            or review["report"] != fix.get("sourceReport")
            or [item["fingerprint"] for item in review["findings"]] != fix.get("findings")
            or review_meta.get("contract_basis") != planning_context_basis(root, step_id)
            or validate_review_report(root, report, expected_step_id=step_id)
            or _run(root, "show", fix["beforeTree"] + ":" + review["report"]) != report.read_bytes()):
        raise ValueError("HIGH_RISK_FAIL_REVIEW_UNPROVEN")
    baseline = checkpoint["fullBaseline"]
    full_proof = baseline.get("producerProof")
    evidence = baseline.get("evidence")
    if not isinstance(full_proof, dict) or not isinstance(evidence, str):
        raise ValueError("HIGH_RISK_FULL_PROOF_REQUIRED")
    block = re.search(re.escape(EVIDENCE_START) + r"(.*?)" + re.escape(EVIDENCE_END), evidence, re.S)
    if (block is None or "- Verification mode: full\n" not in block.group(1)
            or full_proof.get("schemaVersion") != 1
            or full_proof.get("producer") != "deterministic-step-verification"
            or full_proof.get("stepId") != step_id or full_proof.get("status") != "PASS"
            or full_proof.get("runAt") != baseline.get("runAt")
            or full_proof.get("blockSha256") != block_digest(block.group(1))
            or full_proof.get("contractBasis") != checkpoint.get("contractBasis")
            or full_proof.get("contextBasis") != checkpoint.get("contextBasis")):
        raise ValueError("HIGH_RISK_FULL_PROOF_INVALID")
    recorded = datetime.fromisoformat(baseline["runAt"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - recorded).total_seconds()
    if not 0 <= age <= option["maxAgeSeconds"]:
        raise ValueError("HIGH_RISK_BASELINE_EXPIRED")
    invalidated: set[str] = set()
    reasons: dict[str, list[str]] = {}
    for finding in review["findings"]:
        affected: set[str] = set()
        for item in policy["checks"]:
            if not _match(finding["location"]["path"], item["inputs"]):
                continue
            if "groups" not in item:
                affected.add(item["id"])
                continue
            # Qualified groups имеют собственные полные inputs. Неизвестная
            # связь finding с монолитом не доказывает независимость siblings.
            nested = {item["id"] + "/" + group["id"] for group in item["groups"]
                      if _match(finding["location"]["path"], group["inputs"])}
            if not nested:
                raise ValueError("HIGH_RISK_FINDING_GROUP_UNMAPPED")
            affected.update(nested)
        if not affected:
            raise ValueError("HIGH_RISK_FINDING_UNMAPPED")
        invalidated.update(affected)
        for cid in affected:
            reasons.setdefault(cid, []).append("finding:" + finding["fingerprint"])
    exact = {cid for flag in excluded for cid in option["riskChecks"][flag]}
    exact.update(cid for cid, state in option["externalState"].items() if state == "always-run")
    for cid in exact:
        reasons.setdefault(cid, []).append("critical-or-external-state")
    return {"invalidatedChecks": sorted(invalidated), "exactChecks": sorted(exact),
            "receipt": receipt, "reasons": reasons}
