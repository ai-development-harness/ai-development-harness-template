#!/usr/bin/env python3
"""Deterministic command dispatcher AI Development Harness.

Dispatcher объединяет уже существующие contracts в одну runtime boundary:

raw command
  -> CTS structural validation
  -> execution state
  -> deterministic command handler ИЛИ semantic handoff
  -> completion
  -> resolver следующего segment

Он не выполняет LLM reasoning и не читает product source. Для semantic command
возвращается только canonical skill + phase-specific STEP context, если он нужен.
Таким образом root-model больше не воспроизводит orchestration вручную.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from command_transitions import (
    dispatch_spec,
    load_transition_table,
    parse_canonical_command,
    validate_command_text,
    validate_transition_table,
)
from execution_status import (
    begin_command,
    block_execution,
    complete_command,
    load_status,
    resolve_root,
    start_execution,
)
from git_action import GitActionError, execute_pr_finish, execute_sync
from git_preflight import GitPreflightError, check as git_check
from harness_help import help_catalog
from harness_ux import (
    harness_config,
    harness_doctor,
    harness_resume,
    harness_status,
    step_list,
    step_show,
)
from step_context import build_step_context
from step_next import resolve_step_next
from verification import run_step_verification


SCHEMA_VERSION = 1


class DispatchError(RuntimeError):
    """Fail-closed ошибка deterministic dispatcher."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _table(root: Path) -> dict[str, Any]:
    table = load_transition_table(root)
    errors = validate_transition_table(table)
    if errors:
        raise DispatchError(
            "INVALID_TRANSITION_TABLE",
            "; ".join(errors),
        )
    return table


def route_command(root: Path, command: str) -> dict[str, Any]:
    """Разрешить одну canonical command в exact dispatch contract."""
    table = _table(root)
    parsed = parse_canonical_command(command, table)
    if not parsed.get("valid"):
        raise DispatchError(
            str(parsed.get("code") or "INVALID_COMMAND"),
            str(parsed.get("message") or "cannot parse canonical command"),
        )
    spec = dispatch_spec(
        table,
        str(parsed["domain"]),
        str(parsed["operation"]),
    )
    return {
        "command": parsed["normalized"],
        "domain": parsed["domain"],
        "operation": parsed["operation"],
        "target": parsed.get("target"),
        "input": parsed.get("input"),
        "dispatch": spec,
    }


def _execution_identity(execution: dict[str, Any]) -> dict[str, Any]:
    return {
        "executionId": execution.get("executionId"),
        "rootCommand": execution.get("rootCommand"),
    }


def _active_execution(root: Path, root_command: str) -> dict[str, Any] | None:
    """Найти active execution без изменения attempt/resolver state."""
    status = load_status(root)
    for execution in reversed(status.get("executions", [])):
        if (
            execution.get("rootCommand") == root_command
            and execution.get("status") == "running"
        ):
            return execution
    return None


def _verification_before_completion(
    root: Path,
    root_command: str,
    command: str,
    result: str,
    details: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Enforce Verification before IMPLEMENT/FIX SUCCESS.

    Первый элемент tuple — early dispatcher response. None означает, что
    completion разрешён. Второй — compact details для durable execution state.
    """
    if result != "SUCCESS":
        return None, details

    route = route_command(root, command)
    if route.get("domain") != "STEP" or route.get("operation") not in {
        "IMPLEMENT",
        "FIX",
    }:
        return None, details

    step_id = route.get("target")
    if not isinstance(step_id, str) or not step_id:
        return (
            {
                "schemaVersion": SCHEMA_VERSION,
                "status": "BLOCKED",
                "rootCommand": root_command,
                "command": command,
                "reasonCode": "VERIFICATION_STEP_TARGET_MISSING",
            },
            None,
        )

    manual_results = None
    if isinstance(details, dict):
        value = details.get("manualVerification")
        if value is not None:
            manual_results = value

    verification = run_step_verification(
        root,
        step_id,
        manual_results=manual_results,
        write_evidence=True,
    )
    verification_status = verification.get("status")

    if verification_status == "PASS":
        compact = {
            key: value
            for key, value in (details or {}).items()
            if key != "manualVerification"
        }
        compact["verification"] = {
            "status": "PASS",
            "runAt": verification.get("runAt"),
            "revision": verification.get("revision"),
        }
        return None, compact

    if verification_status in {"FAIL", "MANUAL_REQUIRED"}:
        execution = _active_execution(root, root_command)
        if execution is None:
            return (
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "status": "BLOCKED",
                    "rootCommand": root_command,
                    "command": command,
                    "reasonCode": "ACTIVE_EXECUTION_NOT_FOUND",
                    "verification": verification,
                },
                None,
            )
        handoff = _semantic_handoff(root, execution, command)
        handoff["reasonCode"] = "VERIFICATION_" + str(verification_status)
        handoff["verification"] = verification
        return handoff, None

    try:
        block_execution(root, root_command, command=command)
    except (OSError, ValueError):
        pass
    return (
        {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "rootCommand": root_command,
            "command": command,
            "reasonCode": verification.get(
                "reasonCode",
                "VERIFICATION_BLOCKED",
            ),
            "verification": verification,
        },
        None,
    )


def _semantic_handoff(
    root: Path,
    execution: dict[str, Any],
    command: str,
) -> dict[str, Any]:
    route = route_command(root, command)
    dispatch = route["dispatch"]
    if dispatch.get("kind") != "semantic":
        raise DispatchError(
            "NOT_SEMANTIC",
            f"{command} is not a semantic dispatch",
        )

    skill = str(dispatch["skill"])
    skill_path = root / ".agents" / "skills" / skill / "SKILL.md"
    if not skill_path.is_file():
        raise DispatchError(
            "SKILL_MISSING",
            f"dispatch skill does not exist: {skill}",
        )

    context: dict[str, Any] | None = None
    context_phase = dispatch.get("contextPhase")
    if context_phase is not None:
        target = route.get("target")
        if not isinstance(target, str) or not target:
            raise DispatchError(
                "CONTEXT_TARGET_MISSING",
                f"{command}: contextPhase requires STEP target",
            )
        context = build_step_context(root, target, str(context_phase))
        if context.get("status") != "PASS":
            raise DispatchError(
                "STEP_CONTEXT_BLOCKED",
                f"{command}: deterministic STEP context is not PASS",
            )

    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "SEMANTIC",
        **_execution_identity(execution),
        "command": route["command"],
        "skill": skill,
        "skillPath": skill_path.relative_to(root).as_posix(),
        "commandData": {
            "domain": route["domain"],
            "operation": route["operation"],
            "target": route.get("target"),
            "input": route.get("input"),
        },
    }
    if context is not None:
        result["context"] = context
    return result


def _deterministic_handler(
    root: Path,
    command: str,
) -> dict[str, Any]:
    route = route_command(root, command)
    dispatch = route["dispatch"]
    handler = dispatch.get("handler")

    if handler == "harness-help":
        return {"status": "PASS", "domains": help_catalog(root)}
    if handler == "harness-status":
        return harness_status(root)
    if handler == "harness-doctor":
        return harness_doctor(root)
    if handler == "harness-config":
        return harness_config(root)
    if handler == "step-list":
        return step_list(root)
    if handler == "step-show":
        target = route.get("target")
        if not isinstance(target, str) or not target:
            raise DispatchError("STEP_TARGET_MISSING", "STEP SHOW requires target")
        return step_show(root, target)
    if handler == "step-next":
        return resolve_step_next(root)
    if handler == "git-check":
        try:
            return git_check(root)
        except GitPreflightError as exc:
            return {
                "status": "BLOCKED",
                "reasonCode": exc.code,
                "message": str(exc),
                "details": exc.details,
            }
    if handler == "git-pr-finish":
        try:
            return execute_pr_finish(root)
        except (GitActionError, GitPreflightError) as exc:
            return {
                "status": "BLOCKED",
                "reasonCode": exc.code,
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
    if handler == "git-sync":
        try:
            return execute_sync(root)
        except (GitActionError, GitPreflightError) as exc:
            return {
                "status": "BLOCKED",
                "reasonCode": exc.code,
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            }
    if handler == "harness-resume":
        # HARNESS RESUME не создаёт собственную execution. Его special flow
        # обрабатывается start_dispatch()/resume_dispatch().
        return harness_resume(root)

    raise DispatchError(
        "UNSUPPORTED_DETERMINISTIC_HANDLER",
        f"unsupported deterministic handler: {handler}",
    )


def _terminal(
    execution: dict[str, Any],
    resolved: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "status": resolved.get("status"),
        **_execution_identity(execution),
        "command": resolved.get("command"),
        "reasonCode": resolved.get("reasonCode"),
    }
    if result is not None:
        value["result"] = result
    if resolved.get("notExecuted") is not None:
        value["notExecuted"] = resolved.get("notExecuted")
    return value


def _dispatch_running(
    root: Path,
    execution: dict[str, Any],
    command: str,
) -> dict[str, Any]:
    route = route_command(root, command)
    dispatch = route["dispatch"]
    if dispatch.get("kind") == "semantic":
        return _semantic_handoff(root, execution, route["command"])

    result = _deterministic_handler(root, route["command"])
    status = result.get("status")
    if status not in {"PASS", "SUCCESS", "FAIL", "BLOCKED"}:
        raise DispatchError(
            "DETERMINISTIC_RESULT_INVALID",
            f"{route['command']}: unsupported deterministic status {status!r}",
        )
    command_result = str(status)
    completed = complete_command(
        root,
        str(execution["rootCommand"]),
        route["command"],
        command_result,
        details={
            "dispatch": {
                "kind": "deterministic",
                "handler": dispatch.get("handler"),
                "status": status,
            }
        },
    )
    resolved = resolve_root(root, str(execution["rootCommand"]))

    if resolved.get("status") == "NEXT" and resolved.get("command"):
        next_command = str(resolved["command"])
        next_execution = begin_command(
            root,
            str(execution["rootCommand"]),
            next_command,
        )
        return _dispatch_running(root, next_execution, next_command)

    return _terminal(completed, resolved, result=result)


def start_dispatch(root: Path, raw_command: str) -> dict[str, Any]:
    """Начать explicit user command и вернуть result либо semantic handoff."""
    table = _table(root)
    structural = validate_command_text(raw_command, table)
    if not structural.get("valid"):
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reasonCode": structural.get("code"),
            "message": structural.get("message"),
        }

    normalized = list(structural.get("normalized") or [])
    if normalized == ["HARNESS RESUME"]:
        return resume_dispatch(root)

    try:
        execution = start_execution(root, raw_command)
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "reasonCode": "EXECUTION_START_BLOCKED",
            "message": str(exc),
        }

    current = execution.get("current") or {}
    command = current.get("command")
    if not isinstance(command, str) or not command:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            **_execution_identity(execution),
            "reasonCode": "CURRENT_COMMAND_MISSING",
        }
    try:
        return _dispatch_running(root, execution, command)
    except (DispatchError, OSError, ValueError) as exc:
        try:
            block_execution(
                root,
                str(execution["rootCommand"]),
                command=command,
            )
        except (OSError, ValueError):
            pass
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            **_execution_identity(execution),
            "command": command,
            "reasonCode": getattr(exc, "code", "DISPATCH_BLOCKED"),
            "message": str(exc),
        }


def complete_dispatch(
    root: Path,
    root_command: str,
    command: str,
    result: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Зафиксировать semantic result и сразу dispatch-нуть continuation."""
    try:
        early, completion_details = _verification_before_completion(
            root,
            root_command,
            command,
            result,
            details,
        )
        if early is not None:
            return early

        execution = complete_command(
            root,
            root_command,
            command,
            result,
            details=completion_details,
        )
        resolved = resolve_root(root, root_command)
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "rootCommand": root_command,
            "command": command,
            "reasonCode": "EXECUTION_COMPLETE_BLOCKED",
            "message": str(exc),
        }

    if resolved.get("status") == "NEXT" and resolved.get("command"):
        next_command = str(resolved["command"])
        try:
            execution = begin_command(root, root_command, next_command)
            return _dispatch_running(root, execution, next_command)
        except (DispatchError, OSError, ValueError) as exc:
            try:
                block_execution(root, root_command, command=next_command)
            except (OSError, ValueError):
                pass
            return {
                "schemaVersion": SCHEMA_VERSION,
                "status": "BLOCKED",
                **_execution_identity(execution),
                "command": next_command,
                "reasonCode": getattr(exc, "code", "NEXT_DISPATCH_BLOCKED"),
                "message": str(exc),
            }

    return _terminal(execution, resolved)


def resume_dispatch(
    root: Path,
    root_command: str | None = None,
) -> dict[str, Any]:
    """Продолжить explicit root либо единственную resumable execution."""
    if root_command is None:
        selection = harness_resume(root)
        if selection.get("status") != "PASS":
            return {
                "schemaVersion": SCHEMA_VERSION,
                **selection,
            }
        root_command = str(selection["rootCommand"])

    resolved = resolve_root(root, root_command)
    if resolved.get("status") not in {"RESUME", "NEXT"} or not resolved.get("command"):
        return {
            "schemaVersion": SCHEMA_VERSION,
            **resolved,
        }

    command = str(resolved["command"])
    try:
        execution = begin_command(root, root_command, command)
        return _dispatch_running(root, execution, command)
    except (DispatchError, OSError, ValueError) as exc:
        try:
            block_execution(root, root_command, command=command)
        except (OSError, ValueError):
            pass
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "BLOCKED",
            "rootCommand": root_command,
            "command": command,
            "reasonCode": getattr(exc, "code", "RESUME_DISPATCH_BLOCKED"),
            "message": str(exc),
        }


__all__ = [
    "DispatchError",
    "complete_dispatch",
    "resume_dispatch",
    "route_command",
    "start_dispatch",
]
