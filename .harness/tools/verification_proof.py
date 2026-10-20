#!/usr/bin/env python3
"""Локальное подтверждение происхождения сгенерированного Verification Evidence.

Отпечаток Git/STEP доказывает только актуальность входов. Сам блок Evidence
редактируем, поэтому PASS нельзя принимать без отдельного доказательства,
созданного deterministic Verification writer. Запись ограничена одним
checkpoint на STEP и никогда не становится источником project intent.

Этот механизм защищает от обычного/ошибочного редактирования Evidence. Он не
является криптографической защитой от процесса с правом изменять и STEP,
и локальное операционное состояние Harness.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from document_contract import atomic_write_text

PROOF_DIRECTORY = ".harness/local/verification-proofs"
PROOF_VERSION = 1


def _proof_path(root: Path, step_id: str) -> Path:
    if re.fullmatch(r"STEP-\d{3,}", step_id) is None:
        raise ValueError("invalid STEP ID for verification proof")
    return root / PROOF_DIRECTORY / f"{step_id}.json"


def _digest(block: str) -> str:
    return "sha256:" + hashlib.sha256(block.encode("utf-8")).hexdigest()


def _safe_proof_path(root: Path, step_id: str) -> Path:
    path = _proof_path(root, step_id)
    directory = path.parent
    if directory.is_symlink() or path.is_symlink():
        raise ValueError("verification proof path must not be a symlink")
    return path


def _consistent_status(result: dict[str, Any]) -> bool:
    """Сводный PASS не может противоречить результатам команды/наблюдения."""
    groups = (result.get("commands"), result.get("manual"), result.get("product"))
    if any(not isinstance(group, list) for group in groups):
        return False
    for item in groups[0]:
        if not isinstance(item, dict) or item.get("status") not in {"PASS", "FAIL"}:
            return False
        if item["status"] == "PASS" and item.get("exitCode") != 0:
            return False
    # Legacy results have no groups. For a qualified decomposition,
    # the canonical parent PASS requires PASS from every included child.
    for item in groups[0]:
        nested = item.get("groups")
        if nested is None:
            continue
        if (not isinstance(nested, list) or len(nested) < 2 or
                any(not isinstance(child, dict) or
                    child.get("status") != "PASS" or child.get("exitCode") != 0
                    for child in nested)):
            if item.get("status") == "PASS":
                return False
    for group in groups[1:]:
        if any(
            not isinstance(item, dict) or item.get("status") not in {"PASS", "FAIL"}
            for item in group
        ):
            return False
    manual_pending = result.get("manualPending")
    product_pending = result.get("productPending")
    if not isinstance(manual_pending, list) or not isinstance(product_pending, list):
        return False
    all_checks = [item for group in groups for item in group]
    derived = (
        "FAIL" if any(item["status"] == "FAIL" for item in all_checks)
        else "MANUAL_REQUIRED" if manual_pending or product_pending
        else "PASS"
    )
    return derived == result.get("status")


def record_verification_proof(
    root: Path,
    step_id: str,
    *,
    block: str,
    result: dict[str, Any],
) -> None:
    """После публикации Evidence зафиксировать exact producer-bound result.

    Отдельный operational proof не редактируется model-authored STEP writer.
    Для следующего Verification тот же STEP получает новый bounded proof.
    """
    path = _safe_proof_path(root, step_id)
    status = result.get("status")
    if status not in {"PASS", "FAIL", "MANUAL_REQUIRED"} or not _consistent_status(result):
        raise ValueError("verification result is inconsistent with its commands/observations")
    record = {
        "schemaVersion": PROOF_VERSION,
        "producer": "deterministic-step-verification",
        "stepId": step_id,
        "status": status,
        "runAt": result.get("runAt"),
        "contractBasis": result.get("contractBasis"),
        "contextBasis": result.get("contextBasis"),
        "subjectRevision": result.get("subjectRevision"),
        "blockSha256": _digest(block),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def bind_incremental_cache_proof(
    root: Path, step_id: str, *, run_at: str, checkpoint: bytes,
) -> None:
    """Привязать optional cache к уже опубликованному canonical PASS proof.

    Evidence/producer остаются главным доказательством. Cache без этой
    привязки не может разрешать пропуск test command после crash или
    частичной записи и потребует обычного полного Verification.
    """
    path = _safe_proof_path(root, step_id)
    original = path.read_bytes()
    saved = json.loads(original.decode("utf-8"))
    if (not isinstance(saved, dict)
            or saved.get("schemaVersion") != PROOF_VERSION
            or saved.get("producer") != "deterministic-step-verification"
            or saved.get("stepId") != step_id
            or saved.get("runAt") != run_at or saved.get("status") != "PASS"):
        raise ValueError("verification producer proof changed before cache binding")
    saved["incrementalCacheSha256"] = (
        "sha256:" + hashlib.sha256(checkpoint).hexdigest()
    )
    atomic_write_text(
        path,
        json.dumps(saved, sort_keys=True, ensure_ascii=False) + "\n",
        expected_bytes=original,
    )


def incremental_cache_proof_error(
    root: Path, step_id: str, checkpoint: bytes,
) -> str | None:
    """Отдельная порча cache не должна порождать новый reused PASS."""
    try:
        path = _safe_proof_path(root, step_id)
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return "CHECKPOINT_PRODUCER_UNAVAILABLE"
    if (not isinstance(saved, dict)
            or saved.get("schemaVersion") != PROOF_VERSION
            or saved.get("producer") != "deterministic-step-verification"
            or saved.get("stepId") != step_id
            or saved.get("status") != "PASS"):
        return "CHECKPOINT_PRODUCER_INVALID"
    expected = "sha256:" + hashlib.sha256(checkpoint).hexdigest()
    if saved.get("incrementalCacheSha256") != expected:
        return "CHECKPOINT_PRODUCER_MISMATCH"
    return None


def record_targeted_proof(root: Path, step_id: str, checkpoint: bytes) -> None:
    """Закрепить bytes targeted PASS отдельно от редактируемого cache.

    Canonical Evidence не изменяется: targeted feedback остаётся только
    кандидатом на reuse, пока Core не проверит актуальный subject и coverage.
    """
    path = _safe_proof_path(root, step_id).with_suffix(".targeted.json")
    if path.is_symlink():
        raise ValueError("targeted proof path must not be a symlink")
    payload = {
        "schemaVersion": PROOF_VERSION, "stepId": step_id,
        "producer": "deterministic-targeted-verification",
        "checkpointSha256": "sha256:" + hashlib.sha256(checkpoint).hexdigest(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, sort_keys=True) + "\n")


def targeted_proof_error(root: Path, step_id: str, checkpoint: bytes) -> str | None:
    """Одиночная правка targeted cache требует реального запуска команды."""
    try:
        path = _safe_proof_path(root, step_id).with_suffix(".targeted.json")
        if path.is_symlink():
            return "TARGETED_PRODUCER_INVALID"
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return "TARGETED_PRODUCER_UNAVAILABLE"
    expected = "sha256:" + hashlib.sha256(checkpoint).hexdigest()
    if (not isinstance(saved, dict)
            or saved.get("schemaVersion") != PROOF_VERSION
            or saved.get("stepId") != step_id
            or saved.get("producer") != "deterministic-targeted-verification"
            or saved.get("checkpointSha256") != expected):
        return "TARGETED_PRODUCER_MISMATCH"
    return None


def verification_proof_error(
    root: Path,
    step_id: str,
    *,
    block: str,
    status: str,
) -> str | None:
    """Только сохранённый детерминированным writer результат может быть fresh.

    Отсутствующее/битое локальное состояние не превращаем в PASS. Для
    восстановленного checkout достаточно запустить обычную Verification.
    """
    try:
        path = _safe_proof_path(root, step_id)
    except ValueError:
        return "VERIFICATION_PROOF_INVALID"
    if not path.is_file():
        return "VERIFICATION_PROOF_MISSING"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return "VERIFICATION_PROOF_INVALID"
    if not isinstance(saved, dict):
        return "VERIFICATION_PROOF_INVALID"
    if (
        saved.get("schemaVersion") != PROOF_VERSION
        or saved.get("producer") != "deterministic-step-verification"
        or saved.get("stepId") != step_id
    ):
        return "VERIFICATION_PROOF_INVALID"
    if saved.get("status") != status or saved.get("blockSha256") != _digest(block):
        return "VERIFICATION_PROOF_MISMATCH"
    return None
