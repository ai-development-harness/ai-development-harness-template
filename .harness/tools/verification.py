#!/usr/bin/env python3
"""Deterministic STEP Verification runner.

Verification section accepts explicit entries:
- command: <backtick-wrapped argv text>
- manual: human/semantic check description

Commands run directly as argv without shell. The runner records factual evidence,
checks that verification itself did not mutate repository revision, and updates
only a generated block inside the STEP Evidence section.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import threading
import time
from typing import Any

from document_contract import DocumentWriteConflict, atomic_write_text, markdown_headings, stable_hash
from harness_config import verification_command_timeout_seconds
from planning_contract import (
    dependency_ids,
    plan_content_hash,
    planning_context_basis,
    read_task,
    step_completion_proof,
    task_path,
)
from project_verification import (
    ProjectVerificationError,
    validate_product_observations,
)
from review_contract import repository_revision, repository_subject_content_hash
from verification_resume import remember_pending, reuse_pending, forget_pending
from verification_proof import record_verification_proof, verification_proof_error
from verification_incremental import (
    prepare as prepare_incremental, record as record_incremental,
    reuse_targeted, _source_map,
)


COMMAND_RE = re.compile(r"^- command:\s*\x60([^\x60]+)\x60\s*$")
MANUAL_RE = re.compile(r"^- manual:\s*(.+?)\s*$")
PRODUCT_RE = re.compile(r"^- product:\s*(FEATURE-[A-Z0-9][A-Z0-9._-]{1,63})\s*$")
EVIDENCE_START = "<!-- VERIFICATION-EVIDENCE:START -->"
EVIDENCE_END = "<!-- VERIFICATION-EVIDENCE:END -->"
SHELL_CONTROL_TOKENS = {
    "|", "||", "&&", ";", "<", ">", ">>", "2>", "2>>", "&",
}


class VerificationError(ValueError):
    """Invalid or unprovable Verification contract."""


class VerificationInputsStale(VerificationError):
    """Входы Verification изменились после фактического запуска проверок."""

    code = "VERIFICATION_INPUTS_STALE"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_verification(root: Path, step_id: str) -> list[dict[str, str]]:
    """Parse only explicit command/manual entries; never guess prose."""
    task = read_task(root, step_id)
    section = task["sections"].get("Verification", "")
    entries: list[dict[str, str]] = []
    errors: list[str] = []

    for number, raw in enumerate(section.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        command = COMMAND_RE.fullmatch(line)
        if command:
            value = command.group(1).strip()
            if value:
                entries.append({"kind": "command", "value": value})
            else:
                errors.append(f"line {number}: empty command")
            continue
        manual = MANUAL_RE.fullmatch(line)
        if manual:
            value = manual.group(1).strip()
            if value:
                entries.append({"kind": "manual", "value": value})
            else:
                errors.append(f"line {number}: empty manual check")
            continue
        product = PRODUCT_RE.fullmatch(line)
        if product:
            entries.append({"kind": "product", "value": product.group(1)})
            continue
        errors.append(
            f"line {number}: unsupported Verification entry; "
            "use explicit command, manual or product format"
        )

    if errors:
        raise VerificationError("; ".join(errors))
    if not entries:
        raise VerificationError("Verification section has no command/manual entries")
    return entries


def validate_verification_entries(entries: Any) -> list[dict[str, str]]:
    """Validate structured Verification payload before STEP mutation."""
    if not isinstance(entries, list) or not entries:
        raise VerificationError("verification must be a non-empty array")
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(entries, 1):
        if not isinstance(item, dict):
            raise VerificationError(f"verification[{index}] must be an object")
        unexpected = sorted(set(item) - {"kind", "value"})
        if unexpected:
            raise VerificationError(
                f"verification[{index}] has unsupported keys: " + ", ".join(unexpected)
            )
        kind = item.get("kind")
        value = item.get("value")
        if kind not in {"command", "manual", "product"}:
            raise VerificationError(
                f"verification[{index}].kind must be command, manual or product"
            )
        if not isinstance(value, str) or not value.strip():
            raise VerificationError(
                f"verification[{index}].value must be non-empty"
            )
        value = value.strip()
        if kind == "command":
            _argv(value)
        if kind == "product" and PRODUCT_RE.fullmatch(f"- product: {value}") is None:
            raise VerificationError(
                f"verification[{index}].value must be a FEATURE-* id"
            )
        normalized.append({"kind": kind, "value": value})
    return normalized


def render_verification_entries(entries: Any) -> str:
    """Render validated structured Verification entries into canonical Markdown."""
    values = validate_verification_entries(entries)
    tick = chr(96)
    lines: list[str] = []
    for item in values:
        if item["kind"] == "command":
            lines.append(f"- command: {tick}{item['value']}{tick}")
        elif item["kind"] == "manual":
            lines.append(f"- manual: {item['value']}")
        else:
            lines.append(f"- product: {item['value']}")
    return "\n".join(lines)


def _argv(command: str) -> list[str]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise VerificationError(f"cannot parse verification command {command!r}: {exc}") from exc
    if not argv:
        raise VerificationError("verification command is empty")
    controls = sorted(token for token in argv if token in SHELL_CONTROL_TOKENS)
    if controls:
        raise VerificationError(
            "shell control operators are not supported; move complex logic "
            "into a repository script: " + ", ".join(controls)
        )
    return argv


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tail(value: bytes, limit: int = 800) -> str | None:
    if not value:
        return None
    text = value.decode("utf-8", errors="replace").strip()
    return text[-limit:] if text else None


def _revision_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("git_head") == right.get("git_head")
        and left.get("worktree_hash") == right.get("worktree_hash")
    )


def verification_contract_basis(root: Path, step_id: str) -> str:
    """Stable hash exact Verification entries; independent from generated Evidence."""
    entries = parse_verification(root, step_id)
    encoded = json.dumps(
        entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def verification_dependency_facts(root: Path, step_id: str) -> list[dict[str, Any]]:
    """Текущий transitive completion proof для explicit зависимостей STEP.

    Не строим ещё одну dependency graph: доверяем существующим canonical
    step_completion_proof и dependency_ids. Hash меняется при устаревшем
    upstream контракте, даже если direct STEP contract downstream не менялся.
    """
    task = read_task(root, step_id)
    facts: list[dict[str, Any]] = []
    for dep_id in sorted(set(dependency_ids(task))):
        try:
            proof = step_completion_proof(root, dep_id)
        except (OSError, ValueError) as exc:
            facts.append({
                "step": dep_id, "complete": False, "reason": f"unprovable:{exc}",
            })
        else:
            facts.append({
                "step": dep_id,
                "complete": proof["complete"],
                "proof": proof["proof_hash"],
                "reasons": proof["reasons"],
            })
    return facts


def verification_context_basis(root: Path, step_id: str) -> str:
    """Контракт STEP/REQ/ADR, план и timeout, независимо от generated Evidence.

    Subject revision исключает STEP, иначе запись Evidence сама сбивала бы PASS.
    Поэтому используем существующие planning fingerprints для semantic fields.
    """
    basis = {
        "schemaVersion": 1,
        "planningContextBasis": planning_context_basis(root, step_id),
        "planContentHash": plan_content_hash(root, step_id),
        "timeoutSeconds": verification_command_timeout_seconds(root),
    }
    dependencies = verification_dependency_facts(root, step_id)
    if dependencies:
        # STEP без depends_on должен иметь прежний basis byte-for-byte:
        # обновление Harness не требует ложной повторной Verification.
        basis["dependencyCompletion"] = dependencies
    return stable_hash(basis)


def _resume_contract_basis(contract: str, context: str) -> str:
    """Кэш ручной стадии не переживает изменение acceptance или плана."""
    return stable_hash({"verificationContract": contract, "verificationContext": context})


def _stale_inputs_reason(root: Path, step_id: str, result: dict[str, Any]) -> str | None:
    """Проверка входов непосредственно перед сохранением результата."""
    if result.get("contractBasis") != verification_contract_basis(root, step_id):
        return "Verification command contract changed"
    if result.get("contextBasis") != verification_context_basis(root, step_id):
        return "STEP/REQ/ADR/plan verification context changed"
    if result.get("subjectRevision") != verification_subject_revision(root, step_id):
        return "Verification subject changed"
    if result.get("subjectContentHash") != verification_subject_content_hash(root, step_id):
        return "Verification subject content changed"
    if result.get("revision") != repository_revision(root):
        return "Repository changed during verification"
    return None


def verification_subject_revision(root: Path, step_id: str) -> dict[str, str | None]:
    """Revision product/config surface without mutable STEP Evidence container."""
    rel = task_path(root, step_id).resolve().relative_to(root.resolve()).as_posix()
    return repository_revision(root, ignored_paths={rel})


def verification_subject_content_hash(root: Path, step_id: str) -> str:
    """Отпечаток проверенных файлов (не Git history и не Evidence самого STEP)."""
    rel = task_path(root, step_id).resolve().relative_to(root.resolve()).as_posix()
    return repository_subject_content_hash(root, ignored_paths={rel})


def _subject_freshness(
    root: Path,
    step_id: str,
    *,
    content_hash: str | None,
    stored_revision: dict[str, str | None],
    current_revision: dict[str, str | None],
) -> tuple[bool, str | None, str | None]:
    """Старые Evidence сравниваются строго; новые — по содержимому.

    Нельзя преобразовать прежний hash *изменений* в hash всех файлов.
    Отсутствие нового поля не даёт права угадать content equivalence.
    """
    if content_hash is None:
        valid = stored_revision == current_revision
        return valid, None if valid else "VERIFICATION_SUBJECT_STALE", None
    if re.fullmatch(r"sha256:[0-9a-f]{64}", content_hash) is None:
        return False, "VERIFICATION_CONTENT_IDENTITY_INVALID", None
    actual = verification_subject_content_hash(root, step_id)
    return (
        content_hash == actual,
        None if content_hash == actual else "VERIFICATION_SUBJECT_STALE",
        actual,
    )


def verification_command_evidence(
    root: Path,
    step_id: str,
    command: str,
) -> dict[str, Any]:
    """Return fresh factual evidence for one exact Verification command.

    Unlike verification_freshness(), this helper does not require the aggregate
    run status to be PASS. A command can be proven PASS while unrelated manual
    checks are still pending; callers remain responsible for their own manual
    completion gates.
    """
    entries = parse_verification(root, step_id)
    configured = [
        item["value"]
        for item in entries
        if item["kind"] == "command" and item["value"] == command
    ]
    if len(configured) != 1:
        return {
            "status": "UNKNOWN",
            "fresh": False,
            "reasonCode": (
                "VERIFICATION_COMMAND_NOT_CONFIGURED"
                if not configured
                else "VERIFICATION_COMMAND_AMBIGUOUS"
            ),
            "command": command,
        }

    task_value = read_task(root, step_id)
    section = task_value["sections"].get("Evidence", "")
    match = re.search(
        r"<!-- VERIFICATION-EVIDENCE:START -->(.*?)<!-- VERIFICATION-EVIDENCE:END -->",
        section,
        re.S,
    )
    if match is None:
        return {
            "status": "MISSING",
            "fresh": False,
            "reasonCode": "VERIFICATION_EVIDENCE_MISSING",
            "command": command,
        }
    block = match.group(1)

    def field(label: str) -> str | None:
        found = re.search(rf"(?m)^- {re.escape(label)}: (.+?)\s*$", block)
        return found.group(1).strip() if found else None

    stored_basis = field("Verification contract basis")
    stored_context = field("Verification context basis")
    stored_head = field("Subject git head")
    stored_worktree = field("Subject worktree hash")
    if stored_basis is None or stored_context is None or stored_head is None or stored_worktree is None:
        return {
            "status": "UNKNOWN",
            "fresh": False,
            "reasonCode": "VERIFICATION_FRESHNESS_UNKNOWN",
            "command": command,
        }

    current_basis = verification_contract_basis(root, step_id)
    current_context = verification_context_basis(root, step_id)
    current_subject = verification_subject_revision(root, step_id)
    stored_subject = {
        "git_head": None if stored_head == "none" else stored_head,
        "worktree_hash": None if stored_worktree == "clean" else stored_worktree,
    }
    if stored_basis != current_basis:
        return {
            "status": "STALE",
            "fresh": False,
            "reasonCode": "VERIFICATION_CONTRACT_STALE",
            "command": command,
        }
    if stored_context != current_context:
        return {
            "status": "STALE",
            "fresh": False,
            "reasonCode": "VERIFICATION_CONTEXT_STALE",
            "command": command,
        }
    same, reason, current_content = _subject_freshness(
        root, step_id,
        content_hash=field("Subject content hash"),
        stored_revision=stored_subject,
        current_revision=current_subject,
    )
    if not same:
        return {
            "status": "STALE",
            "fresh": False,
            "reasonCode": reason,
            "command": command,
        }

    proof_error = verification_proof_error(
        root, step_id, block=block, status=field("Status") or "UNKNOWN",
    )
    if proof_error is not None:
        return {
            "status": "UNKNOWN",
            "fresh": False,
            "reasonCode": proof_error,
            "command": command,
        }

    pattern = re.compile(
        rf"(?m)^- Command: {re.escape(command)}\s*$"
        rf"\n  - Status: (PASS|FAIL|BLOCKED)\s*$"
        rf"\n  - Exit code: (.+?)\s*$"
    )
    results = pattern.findall(block)
    if len(results) != 1:
        return {
            "status": "UNKNOWN",
            "fresh": False,
            "reasonCode": "VERIFICATION_COMMAND_EVIDENCE_AMBIGUOUS",
            "command": command,
        }
    status, exit_code = results[0]
    return {
        "status": status,
        "fresh": True,
        "reasonCode": None if status == "PASS" else "VERIFICATION_COMMAND_NOT_PASS",
        "command": command,
        "exitCode": exit_code,
        "contractBasis": current_basis,
        "subjectRevision": current_subject,
        "subjectContentHash": current_content,
    }


def verification_freshness(root: Path, step_id: str) -> dict[str, Any]:
    """Prove generated PASS evidence still belongs to current contract/subject."""
    task_value = read_task(root, step_id)
    section = task_value["sections"].get("Evidence", "")
    match = re.search(
        r"<!-- VERIFICATION-EVIDENCE:START -->(.*?)<!-- VERIFICATION-EVIDENCE:END -->",
        section,
        re.S,
    )
    if match is None:
        return {"status": "MISSING", "fresh": False, "reasonCode": "VERIFICATION_EVIDENCE_MISSING"}
    block = match.group(1)

    def field(label: str) -> str | None:
        found = re.search(rf"(?m)^- {re.escape(label)}: (.+?)\s*$", block)
        return found.group(1).strip() if found else None

    status = field("Status") or "UNKNOWN"
    stored_basis = field("Verification contract basis")
    stored_context = field("Verification context basis")
    stored_head = field("Subject git head")
    stored_worktree = field("Subject worktree hash")
    if stored_basis is None or stored_context is None or stored_head is None or stored_worktree is None:
        return {
            "status": status,
            "fresh": False,
            "reasonCode": "VERIFICATION_FRESHNESS_UNKNOWN",
        }

    current_basis = verification_contract_basis(root, step_id)
    current_context = verification_context_basis(root, step_id)
    current_subject = verification_subject_revision(root, step_id)
    stored_subject = {
        "git_head": None if stored_head == "none" else stored_head,
        "worktree_hash": None if stored_worktree == "clean" else stored_worktree,
    }
    if stored_basis != current_basis:
        return {
            "status": status,
            "fresh": False,
            "reasonCode": "VERIFICATION_CONTRACT_STALE",
            "storedContractBasis": stored_basis,
            "currentContractBasis": current_basis,
        }
    if stored_context != current_context:
        return {
            "status": status,
            "fresh": False,
            "reasonCode": "VERIFICATION_CONTEXT_STALE",
            "storedContextBasis": stored_context,
            "currentContextBasis": current_context,
        }
    same, reason, current_content = _subject_freshness(
        root, step_id,
        content_hash=field("Subject content hash"),
        stored_revision=stored_subject,
        current_revision=current_subject,
    )
    if not same:
        return {
            "status": status,
            "fresh": False,
            "reasonCode": reason,
            "storedSubjectRevision": stored_subject,
            "currentSubjectRevision": current_subject,
        }
    proof_error = verification_proof_error(root, step_id, block=block, status=status)
    if proof_error is not None:
        return {"status": status, "fresh": False, "reasonCode": proof_error}
    return {
        "status": status,
        "fresh": status == "PASS",
        "reasonCode": None if status == "PASS" else "VERIFICATION_NOT_PASS",
        "contractBasis": current_basis,
        "subjectRevision": current_subject,
        "subjectContentHash": current_content,
    }


# Сколько последних bytes каждого потока держать в памяти для diagnostic tail.
# Hash и byte count считаются по всему выводу потоково.
CAPTURE_TAIL_BYTES = 64 * 1024
# Сколько ждать закрытия pipes после завершения/убийства process group.
PIPE_DRAIN_SECONDS = 5


class _StreamCapture:
    """Потоковый hash + byte count + bounded tail одного pipe."""

    def __init__(self, stream: Any):
        self._stream = stream
        self.digest = hashlib.sha256()
        self.size = 0
        self.tail = bytearray()
        self.thread = threading.Thread(target=self._drain, daemon=True)
        self.thread.start()

    def _drain(self) -> None:
        try:
            while True:
                chunk = self._stream.read(65536)
                if not chunk:
                    return
                self.digest.update(chunk)
                self.size += len(chunk)
                self.tail.extend(chunk)
                if len(self.tail) > CAPTURE_TAIL_BYTES:
                    del self.tail[: len(self.tail) - CAPTURE_TAIL_BYTES]
        except (OSError, ValueError):
            return

    def finish(self) -> None:
        self.thread.join(PIPE_DRAIN_SECONDS)


def _popen_group_kwargs() -> dict[str, Any]:
    # Отдельная process group: timeout убивает и внуков (`sh -c`, test runners),
    # иначе они продолжали бы работать и держать pipes (#115).
    if os.name == "posix":
        return {"start_new_session": True}
    return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    else:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            proc.kill()


def _run_command(
    root: Path,
    command: str,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    argv = _argv(command)
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_popen_group_kwargs(),
        )
    except FileNotFoundError as exc:
        return {
            "kind": "command",
            "command": command,
            "argv": argv,
            "status": "BLOCKED",
            "reasonCode": "EXECUTABLE_NOT_FOUND",
            "message": str(exc),
        }
    stdout = _StreamCapture(proc.stdout)
    stderr = _StreamCapture(proc.stderr)
    timed_out = False
    try:
        proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        # Verification не оставляет фоновых процессов ни после timeout, ни
        # после нормального завершения lead process. На Windows завершённый
        # PID мог быть переиспользован, поэтому taskkill — только по timeout.
        if os.name == "posix" or timed_out:
            _kill_group(proc)
        proc.wait()
        stdout.finish()
        stderr.finish()

    stdout_tail = bytes(stdout.tail)
    stderr_tail = bytes(stderr.tail)
    result: dict[str, Any] = {
        "kind": "command",
        "command": command,
        "argv": argv,
        "durationMs": int((time.monotonic() - started) * 1000),
        "stdoutSha256": stdout.digest.hexdigest(),
        "stderrSha256": stderr.digest.hexdigest(),
        "stdoutBytes": stdout.size,
        "stderrBytes": stderr.size,
    }
    if timed_out:
        result.update(
            status="FAIL",
            reasonCode="TIMEOUT",
            timeoutSeconds=timeout_seconds,
            exitCode=None,
            stdoutTail=_tail(stdout_tail),
            stderrTail=_tail(stderr_tail),
        )
        return result
    result["status"] = "PASS" if proc.returncode == 0 else "FAIL"
    result["exitCode"] = proc.returncode
    if proc.returncode != 0:
        result["stdoutTail"] = _tail(stdout_tail)
        result["stderrTail"] = _tail(stderr_tail)
    return result


def _run_composite_groups(
    root: Path,
    parent: str,
    groups: list[dict[str, Any]],
    *,
    timeout: int,
    revision: dict[str, Any],
) -> list[dict[str, Any]]:
    """Execute/reuse all qualified groups with a per-command mutation guard.

    A group PASS never becomes a replacement for a monolith on its own:
    the caller still builds one fully covered canonical parent result.
    """
    outcome: list[dict[str, Any]] = []
    for item in groups:
        spec = item["spec"]
        reused = item.get("reused")
        if isinstance(reused, dict):
            result = dict(reused)
        else:
            before = repository_revision(root)
            if not _revision_equal(before, revision):
                raise VerificationInputsStale("subject changed before composite group")
            refs = _refs_snapshot(root)
            result = _run_command(root, spec["command"], timeout_seconds=timeout)
            if refs != _refs_snapshot(root):
                raise VerificationInputsStale("composite group mutated Git refs")
            if not _revision_equal(repository_revision(root), revision):
                raise VerificationInputsStale("composite group mutated repository")
        outcome.append({"id": spec["id"], "command": spec["command"],
                        "acceptance": list(spec["acceptance"]), **result})
        if result.get("status") == "BLOCKED":
            raise VerificationError("composite group is BLOCKED: " + spec["command"])
    return outcome


def _aggregate_composite(
    command: str,
    groups: list[dict[str, Any]],
    *,
    full_command_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Represent proven groups as one canonical command entry for Completion Gate."""
    if not groups:
        raise VerificationError("composite must cover at least one group")
    statuses = [item.get("status") for item in groups]
    if any(value not in {"PASS", "FAIL"} for value in statuses):
        raise VerificationError("composite group has unsupported status")
    passed = all(value == "PASS" for value in statuses)
    if full_command_result is not None:
        value = dict(full_command_result)
        if not passed and value.get("status") == "PASS":
            value["status"] = "FAIL"
            value["exitCode"] = 1
            value["reasonCode"] = "COMPOSITE_GROUP_FAILED"
    else:
        # Only a qualified *full baseline* permits this aggregate. Its nested
        # group observations are part of producer-bound Evidence/operational cache.
        identity = json.dumps(groups, ensure_ascii=False, sort_keys=True).encode("utf-8")
        value = {
            "kind": "command",
            "command": command,
            "argv": _argv(command),
            "status": "PASS" if passed else "FAIL",
            "exitCode": 0 if passed else 1,
            "durationMs": sum(int(g.get("durationMs") or 0)
                              for g in groups if not g.get("reusedFrom")),
            "stdoutSha256": hashlib.sha256(identity).hexdigest(),
            "stderrSha256": hashlib.sha256(b"").hexdigest(),
            "stdoutBytes": 0,
            "stderrBytes": 0,
            "composite": True,
        }
    value["groups"] = groups
    return value


def _refs_snapshot(root: Path) -> str:
    """Все refs и HEAD: Verification не должна создавать/двигать ветки и теги."""
    refs = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname) %(objectname)"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    head = subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return refs.stdout.decode("utf-8", "replace") + "HEAD=" + head.stdout.decode("utf-8", "replace")


def _manual_results(
    entries: list[dict[str, str]],
    supplied: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    expected = [item["value"] for item in entries if item["kind"] == "manual"]
    if not expected:
        return [], []
    if supplied is None:
        return [], expected
    if not isinstance(supplied, list):
        raise VerificationError("manualVerification must be an array")

    by_check: dict[str, dict[str, Any]] = {}
    for item in supplied:
        if not isinstance(item, dict):
            raise VerificationError("manualVerification entries must be objects")
        check = item.get("check")
        status = item.get("status")
        observed = item.get("observed")
        if not isinstance(check, str) or check not in expected:
            raise VerificationError(f"unknown manual verification check: {check!r}")
        if check in by_check:
            raise VerificationError(f"duplicate manual verification check: {check}")
        if status not in {"PASS", "FAIL"}:
            raise VerificationError(
                f"manual verification status for {check!r} must be PASS or FAIL"
            )
        if not isinstance(observed, str) or not observed.strip():
            raise VerificationError(
                f"manual verification observed for {check!r} must be non-empty"
            )
        by_check[check] = {
            "kind": "manual",
            "check": check,
            "status": status,
            "observed": observed.strip(),
        }

    missing = [check for check in expected if check not in by_check]
    ordered = [by_check[check] for check in expected if check in by_check]
    return ordered, missing


def _evidence_block(result: dict[str, Any]) -> str:
    revision = result["revision"]
    lines = [
        EVIDENCE_START,
        f"- Verification run: {result['runAt']}",
        f"- Status: {result['status']}",
        f"- Automated resumed: {str(result.get('automatedResumed', False)).lower()}",
        f"- Verification mode: {result.get('verificationMode', 'full')}",
        f"- Incremental executed checks: {result.get('executedCount', len(result.get('commands', [])))}",
        f"- Incremental reused checks: {result.get('reusedCount', 0)}",
        f"- Targeted feedback reused: {result.get('targetedReusedCount', 0)}",
        f"- Incremental fallback reason: {result.get('fallbackReason') or 'none'}",
        f"- Git head: {revision.get('git_head') or 'none'}",
        f"- Worktree hash: {revision.get('worktree_hash') or 'clean'}",
        f"- Verification contract basis: {result['contractBasis']}",
        f"- Verification context basis: {result['contextBasis']}",
        f"- Subject git head: {result['subjectRevision'].get('git_head') or 'none'}",
        f"- Subject worktree hash: {result['subjectRevision'].get('worktree_hash') or 'clean'}",
        *([f"- Subject content hash: {result['subjectContentHash']}"]
          if result.get("subjectContentHash") else []),
        "",
        "### Automated verification",
    ]
    automated = result.get("commands", [])
    if not automated:
        lines.append("- none")
    for item in automated:
        lines.extend(
            [
                f"- Command: {item['command']}",
                f"  - Status: {item['status']}",
                f"  - Exit code: {item.get('exitCode')}",
                f"  - Duration ms: {item.get('durationMs')}",
                f"  - stdout sha256: {item.get('stdoutSha256')}",
                f"  - stderr sha256: {item.get('stderrSha256')}",
                f"  - stdout bytes: {item.get('stdoutBytes')}",
                f"  - stderr bytes: {item.get('stderrBytes')}",
                f"  - Provenance: {item.get('reusedFrom') or ('qualified-composite' if item.get('groups') else 'executed')}",
            ]
        )
        for group in item.get("groups", []):
            lines.extend([
                f"  - Group id: {group['id']}",
                f"    - Group command: {group['command']}",
                f"    - Group status: {group['status']}",
                f"    - Group exit code: {group.get('exitCode')}",
                f"    - Group duration ms: {group.get('durationMs')}",
                f"    - Group provenance: {group.get('reusedFrom') or 'executed'}",
                f"    - Group acceptance: {json.dumps(group['acceptance'], ensure_ascii=False)}",
            ])

    lines.extend(["", "### Product verification"])
    product = result.get("product", [])
    product_pending = result.get("productPending", [])
    if not product and not product_pending:
        lines.append("- none")
    for item in product:
        lines.extend(
            [
                f"- Feature: {item['featureId']}",
                f"  - Surface: {item['surface']}",
                f"  - Status: {item['status']}",
                "  - Observed: " + json.dumps(item["observed"], ensure_ascii=False),
                f"  - Driver skill sha256: {item['driverSkillSha256']}",
                f"  - Feature map basis: {item['featureMapBasis']}",
                f"  - Source basis: {item['sourceBasis']}",
            ]
        )
        for proof in item.get("evidence", []):
            lines.append(
                f"  - Evidence: {proof['path']} {proof['sha256']} ({proof['bytes']} bytes)"
            )
    for feature_id in product_pending:
        lines.extend([f"- Feature: {feature_id}", "  - Status: PENDING"])

    lines.extend(["", "### Manual verification"])
    manual = result.get("manual", [])
    pending = result.get("manualPending", [])
    if not manual and not pending:
        lines.append("- none")
    for item in manual:
        lines.extend(
            [
                f"- Check: {item['check']}",
                f"  - Status: {item['status']}",
                "  - Observed: " + json.dumps(item["observed"], ensure_ascii=False),
            ]
        )
    for check in pending:
        lines.extend([f"- Check: {check}", "  - Status: PENDING"])

    lines.append(EVIDENCE_END)
    return "\n".join(lines)


def _replace_evidence_block(text: str, block: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    h2 = [
        (index, title)
        for index, level, title in markdown_headings(text)
        if level == 2
    ]
    evidence_indexes = [index for index, title in h2 if title == "Evidence"]
    if len(evidence_indexes) != 1:
        raise VerificationError(
            f"expected exactly one Evidence section, found {len(evidence_indexes)}"
        )
    heading_index = evidence_indexes[0]
    next_indexes = [index for index, _ in h2 if index > heading_index]
    section_end = min(next_indexes) if next_indexes else len(lines)

    current = lines[heading_index + 1 : section_end]
    start = current.index(EVIDENCE_START) if EVIDENCE_START in current else -1
    end = current.index(EVIDENCE_END) if EVIDENCE_END in current else -1
    if (start >= 0) != (end >= 0):
        raise VerificationError("malformed generated verification Evidence markers")
    if start >= 0:
        if end < start:
            raise VerificationError("reversed generated verification Evidence markers")
        current = current[:start] + block.splitlines() + current[end + 1 :]
    else:
        semantic = "\n".join(current).strip()
        if semantic == "—":
            semantic = ""
        current = block.splitlines() + (["", semantic] if semantic else [])

    result = lines[: heading_index + 1] + [""] + current + [""] + lines[section_end:]
    return "\n".join(result).rstrip() + "\n"


def _write_evidence(root: Path, step_id: str, result: dict[str, Any]) -> None:
    """Записать Evidence и независимый proof только для того же STEP snapshot.

    Execution lock сериализует два канонических writer-а; optimistic CAS
    обнаруживает несовместимое редактирование STEP до atomic replace.
    """
    # Локальный импорт устраняет цикл execution_status → completion_gate →
    # verification; общая блокировка работает и для standalone verify-step.
    from execution_status import execution_state_lock

    with execution_state_lock(root):
        stale_reason = _stale_inputs_reason(root, step_id, result)
        if stale_reason is not None:
            raise VerificationInputsStale(stale_reason)
        path = task_path(root, step_id)
        original = path.read_bytes()
        updated = _replace_evidence_block(
            original.decode("utf-8"),
            _evidence_block(result),
        )
        try:
            atomic_write_text(path, updated, expected_bytes=original)
        except DocumentWriteConflict as exc:
            raise VerificationInputsStale(str(exc)) from exc

        # Запись STEP и операционного proof не составляет одну filesystem
        # transaction. Если crash произошёл между ними, без proof старый PASS
        # считается UNKNOWN и штатная Verification повторяется.
        if path.read_bytes() != updated.encode("utf-8"):
            raise VerificationInputsStale("STEP changed after Evidence publication")
        if (
            result.get("contractBasis") != verification_contract_basis(root, step_id)
            or result.get("contextBasis") != verification_context_basis(root, step_id)
            or result.get("subjectRevision") != verification_subject_revision(root, step_id)
            or result.get("subjectContentHash") != verification_subject_content_hash(root, step_id)
        ):
            raise VerificationInputsStale("verification inputs changed after Evidence publication")

        match = re.search(
            rf"{re.escape(EVIDENCE_START)}(.*?){re.escape(EVIDENCE_END)}",
            updated, re.S,
        )
        if match is None:
            raise VerificationError("generated Evidence block is missing after publication")
        record_verification_proof(
            root, step_id, block=match.group(1), result=result,
        )
        # Только штатный Evidence writer имеет право продвинуть checkpoint.
        # При ошибке optional cache остаётся прежним; PASS не превращаем в FAIL.
        from completion_gate import acceptance_criteria
        commands = [entry["value"] for entry in parse_verification(root, step_id)
                    if entry["kind"] == "command"]
        plan = None
        if result.get("verificationMode") == "incremental":
            plan = prepare_incremental(
                root, step_id, commands=commands,
                acceptance=acceptance_criteria(root, step_id),
                contract_basis=result["contractBasis"],
                context_basis=result["contextBasis"],
                timeout=result["timeoutSeconds"],
                subject_hash=result["subjectContentHash"],
            )
        record_incremental(
            root, step_id, result=result, plan=plan,
            commands=commands, acceptance=acceptance_criteria(root, step_id),
        )


def write_verification_evidence(
    root: Path,
    step_id: str,
    result: dict[str, Any],
) -> None:
    """Persist an already-computed factual Verification result."""
    _write_evidence(root, step_id, result)


def run_step_verification(
    root: Path,
    step_id: str,
    *,
    manual_results: list[dict[str, Any]] | None = None,
    product_results: list[dict[str, Any]] | None = None,
    write_evidence: bool = True,
    force_full: bool = False,
) -> dict[str, Any]:
    """Run canonical Verification, optionally reusing proven check inputs."""
    try:
        entries = parse_verification(root, step_id)
        timeout = verification_command_timeout_seconds(root)
        manual, pending = _manual_results(entries, manual_results)
        product_ids = [
            item["value"] for item in entries if item["kind"] == "product"
        ]
        product, product_pending = validate_product_observations(
            root,
            product_ids,
            product_results,
        )
        revision = repository_revision(root)
        contract_basis = verification_contract_basis(root, step_id)
        context_basis = verification_context_basis(root, step_id)
        subject_revision = verification_subject_revision(root, step_id)
        subject_content_hash = verification_subject_content_hash(root, step_id)
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "stepId": step_id,
            "reasonCode": "VERIFICATION_CONTRACT_INVALID",
            "message": str(exc),
        }

    # Новая Verification требует сохранного принятого результата прямых
    # prerequisites. Сегодняшний контекст старых completed STEP здесь
    # не пересматривается: актуальность относится к новой работе (#355).
    dependency_failures = [
        item for item in verification_dependency_facts(root, step_id)
        if not item["complete"]
    ]
    if dependency_failures:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "stepId": step_id,
            "reasonCode": "VERIFICATION_DEPENDENCY_UNPROVEN",
            "dependencies": dependency_failures,
        }

    resume_basis = _resume_contract_basis(contract_basis, context_basis)
    command_names = [item["value"] for item in entries if item["kind"] == "command"]
    from completion_gate import acceptance_criteria
    acceptance = acceptance_criteria(root, step_id)
    # Проверяем producer-bound происхождение предыдущего Evidence ДО проверки
    # subject freshness. Иначе tampered Evidence со stale subject мог бы
    # замаскироваться кодом VERIFICATION_SUBJECT_STALE и разрешить cache reuse.
    try:
        previous_section = read_task(root, step_id)["sections"].get("Evidence", "")
    except (OSError, ValueError):
        # A STEP can change between the preflight snapshot and this read.
        # In that case nothing from the old cache is trustworthy; the
        # canonical final revision/CAS gate still decides completion.
        previous_section = ""
    previous_block_match = re.search(
        rf"{re.escape(EVIDENCE_START)}(.*?){re.escape(EVIDENCE_END)}",
        previous_section, re.S,
    )
    untrusted_evidence = True
    previous_failed_commands: set[str] = set()
    if previous_block_match is not None:
        previous_block = previous_block_match.group(1)
        previous_status = re.search(r"(?m)^- Status: (PASS|FAIL|MANUAL_REQUIRED)\s*$", previous_block)
        if previous_status is not None:
            untrusted_evidence = verification_proof_error(
                root, step_id, block=previous_block, status=previous_status.group(1),
            ) is not None
            if not untrusted_evidence:
                # A failed check cannot inherit an older cached PASS even when
                # its declared inputs happen to be unchanged.
                previous_failed_commands = {
                    match.group(1) for match in re.finditer(
                        r"(?m)^- Command: (.+)\s*\n  - Status: FAIL\s*$",
                        previous_block,
                    )
                }
    selection = prepare_incremental(
        root, step_id, commands=command_names, acceptance=acceptance,
        contract_basis=contract_basis, context_basis=context_basis,
        timeout=timeout, subject_hash=subject_content_hash,
        full=force_full or untrusted_evidence,
    )
    if selection["mode"] == "incremental" and previous_failed_commands:
        for name in command_names:
            if name in previous_failed_commands and name in selection["reused"]:
                del selection["reused"][name]
                selection["executed"].append(name)
    targeted = reuse_targeted(
        root, step_id, selection=selection, commands=command_names,
        contract_basis=contract_basis, context_basis=context_basis,
        timeout=timeout, subject_hash=subject_content_hash,
    )
    # A group adapter is permitted only if the entire configured map is
    # valid. If the map is invalid, do not run any adapter commands: fallback
    # to the historical full Verification contract.
    try:
        group_policy = _source_map(root, step_id, command_names, acceptance)
        qualified_groups = {
            item["command"]: item["groups"] for item in group_policy["checks"]
            if "groups" in item
        }
    except (OSError, ValueError):
        qualified_groups = {}
    reused = None
    if not force_full and (manual_results is not None or product_results is not None):
        reused = reuse_pending(
            root, step_id, contract=resume_basis,
            subject=subject_revision, names=command_names, timeout=timeout,
        )
    commands: list[dict[str, Any]] = list(reused) if reused is not None else []
    try:
        for entry in ([] if reused is not None else entries):
            if entry["kind"] != "command":
                continue
            if selection["mode"] == "incremental" and entry["value"] in selection["reused"]:
                commands.append(selection["reused"][entry["value"]])
                continue
            if entry["value"] in targeted and entry["value"] not in qualified_groups:
                commands.append(targeted[entry["value"]])
                continue
            composite_plan = selection.get("composites", {}).get(entry["value"])
            if composite_plan is not None:
                group_results = _run_composite_groups(
                    root, entry["value"], composite_plan["groups"],
                    timeout=timeout, revision=revision,
                )
                commands.append(_aggregate_composite(
                    entry["value"], group_results, full_command_result=None,
                ))
                continue
            before = repository_revision(root)
            if not _revision_equal(before, revision):
                return {
                    "schemaVersion": 1,
                    "status": "BLOCKED",
                    "stepId": step_id,
                    "reasonCode": "VERIFICATION_BASELINE_CHANGED",
                    "commands": commands,
                }

            refs_before = _refs_snapshot(root)
            item = _run_command(
                root,
                entry["value"],
                timeout_seconds=timeout,
            )
            if item["status"] == "PASS" and entry["value"] in qualified_groups:
                # The first full run qualifies the declared decomposition by
                # executing the monolith and all its groups on the same subject.
                group_plan = [
                    {"spec": group, "reused": None}
                    for group in qualified_groups[entry["value"]]
                ]
                results = _run_composite_groups(
                    root, entry["value"], group_plan, timeout=timeout,
                    revision=revision,
                )
                item = _aggregate_composite(
                    entry["value"], results, full_command_result=item,
                )
            commands.append(item)
            if _refs_snapshot(root) != refs_before:
                return {
                    "schemaVersion": 1,
                    "status": "BLOCKED",
                    "stepId": step_id,
                    "reasonCode": "VERIFICATION_MUTATED_REFS",
                    "commands": commands,
                }
            if item["status"] == "BLOCKED":
                return {
                    "schemaVersion": 1,
                    "status": "BLOCKED",
                    "stepId": step_id,
                    "reasonCode": item.get("reasonCode"),
                    "commands": commands,
                    "message": item.get("message"),
                }

            after = repository_revision(root)
            if not _revision_equal(revision, after):
                return {
                    "schemaVersion": 1,
                    "status": "BLOCKED",
                    "stepId": step_id,
                    "reasonCode": "VERIFICATION_MUTATED_REPOSITORY",
                    "commands": commands,
                    "revisionBefore": revision,
                    "revisionAfter": after,
                }
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "stepId": step_id,
            "reasonCode": "VERIFICATION_RUNTIME_BLOCKED",
            "commands": commands,
            "message": str(exc),
        }

    if any(item["status"] == "FAIL" for item in commands):
        status = "FAIL"
    elif any(item["status"] == "FAIL" for item in product):
        status = "FAIL"
    elif any(item["status"] == "FAIL" for item in manual):
        status = "FAIL"
    elif product_pending or pending:
        status = "MANUAL_REQUIRED"
    else:
        status = "PASS"

    # Проверки могли занять минуты. Устаревшие результаты нельзя сохранять.
    inputs = {
        "contractBasis": contract_basis,
        "contextBasis": context_basis,
        "subjectRevision": subject_revision,
        "subjectContentHash": subject_content_hash,
        "revision": revision,
    }
    try:
        stale_reason = _stale_inputs_reason(root, step_id, inputs)
    except (OSError, ValueError) as exc:
        stale_reason = str(exc)
    if stale_reason is not None:
        return {
            "schemaVersion": 1,
            "status": "BLOCKED",
            "stepId": step_id,
            "reasonCode": "VERIFICATION_INPUTS_STALE",
            "message": stale_reason,
            "commands": commands,
        }

    if status == "MANUAL_REQUIRED" and reused is None:
        remember_pending(
            root, step_id, contract=resume_basis,
            subject=subject_revision, commands=commands, timeout=timeout,
        )
    elif status != "MANUAL_REQUIRED":
        forget_pending(root, step_id)

    result = {
        "schemaVersion": 1,
        "status": status,
        "automatedResumed": reused is not None,
        "verificationMode": selection["mode"],
        "executedChecks": [
            name for name in command_names
            if reused is None and name in selection["executed"] and name not in targeted
        ],
        "targetedChecks": [] if reused is not None else list(targeted),
        "executedCount": 0 if reused is not None else len(selection["executed"]) - len(targeted),
        "reusedCount": len(commands) if reused is not None else len(selection["reused"]),
        "targetedReusedCount": 0 if reused is not None else len(targeted),
        "groupExecutedCount": sum(
            1 for item in commands for group in item.get("groups", [])
            if not group.get("reusedFrom")
        ),
        "groupReusedCount": sum(
            1 for item in commands for group in item.get("groups", [])
            if group.get("reusedFrom")
        ),
        "fallbackReason": selection.get("reasonCode"),
        "stepId": step_id,
        "runAt": utc_now(),
        "revision": revision,
        "contractBasis": contract_basis,
        "contextBasis": context_basis,
        "subjectRevision": subject_revision,
        "subjectContentHash": subject_content_hash,
        "timeoutSeconds": timeout,
        "commands": commands,
        "product": product,
        "productPending": product_pending,
        "manual": manual,
        "manualPending": pending,
    }
    if write_evidence:
        try:
            _write_evidence(root, step_id, result)
        except (OSError, ValueError) as exc:
            return {
                **result,
                "status": "BLOCKED",
                "reasonCode": getattr(exc, "code", "EVIDENCE_WRITE_FAILED"),
                "message": str(exc),
            }
    return result


__all__ = [
    "VerificationError",
    "parse_verification",
    "render_verification_entries",
    "run_step_verification",
    "write_verification_evidence",
    "verification_contract_basis",
    "verification_context_basis",
    "verification_dependency_facts",
    "verification_freshness",
    "verification_subject_revision",
    "verification_subject_content_hash",
    "validate_verification_entries",
]
