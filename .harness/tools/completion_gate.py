#!/usr/bin/env python3
"""Completion / Convergence Gate for STEP closure.

REVIEW answers whether the inspected implementation has material defects.
Completion answers whether all in-scope Acceptance obligations are actually
covered and closure is justified. The gate reuses the existing STEP lifecycle;
it does not introduce a second state machine.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from planning_contract import (
    generated_verification_status,
    implementation_prerequisite_failures,
    read_task,
)


class CompletionGateError(ValueError):
    """Completion payload violates the deterministic contract."""


def acceptance_criteria(root: Path, step_id: str) -> list[str]:
    task=read_task(root,step_id)
    text=task["sections"].get("Acceptance criteria","")
    result: list[str]=[]
    for raw in text.splitlines():
        match=re.match(r"^\s*[-*]\s+(.+?)\s*$",raw)
        if match:
            value=match.group(1).strip()
            if value:
                result.append(value)
    return result


def deterministic_precheck(root: Path, step_id: str) -> dict[str, Any]:
    """Cheap/factual checks that run before semantic convergence judgement."""
    task=read_task(root,step_id)
    criteria=acceptance_criteria(root,step_id)
    verification=generated_verification_status(task)
    failures: list[dict[str,str]]=[]
    if not criteria:
        failures.append({
            "code":"ACCEPTANCE_MISSING",
            "kind":"contract",
            "message":"STEP has no machine-discoverable Acceptance criteria",
        })
    if verification is not None and verification != "PASS":
        failures.append({
            "code":"VERIFICATION_NOT_PASS",
            "kind":"evidence",
            "message":f"generated Verification evidence status is {verification}",
        })
    # This catches stale Ready fingerprints/current OQ/dependency prerequisites.
    # In completion context, dependency/plan drift is a contract blocker, not FIX.
    for reason in implementation_prerequisite_failures(root,step_id):
        if reason.startswith("dependency-incomplete"):
            continue
        failures.append({
            "code":"CURRENT_CONTRACT_NOT_EXECUTABLE",
            "kind":"contract",
            "message":reason,
        })
    return {
        "schemaVersion":1,
        "status":"PASS" if not failures else "BLOCKED",
        "stepId":step_id,
        "acceptanceCriteria":criteria,
        "verificationStatus":verification,
        "findings":failures,
    }


def _text(value: Any, label: str) -> str:
    if not isinstance(value,str) or not value.strip():
        raise CompletionGateError(f"{label} must be a non-empty string")
    return value.strip()


def normalize_semantic_completion(payload: Any, criteria: list[str]) -> dict[str,Any]:
    if not isinstance(payload,dict):
        raise CompletionGateError("completion must be an object")
    unexpected=sorted(set(payload)-{"disposition","coverage","findings","rationale"})
    if unexpected:
        raise CompletionGateError("completion has unsupported keys: "+", ".join(unexpected))
    disposition=payload.get("disposition")
    if disposition not in {"pass","fix","blocked"}:
        raise CompletionGateError("completion.disposition must be pass|fix|blocked")
    coverage=payload.get("coverage")
    if not isinstance(coverage,list):
        raise CompletionGateError("completion.coverage must be an array")
    normalized: list[dict[str,Any]]=[]
    observed: set[str]=set()
    for index,item in enumerate(coverage):
        if not isinstance(item,dict):
            raise CompletionGateError(f"coverage[{index}] must be an object")
        if set(item)-{"criterion","status","evidence"}:
            raise CompletionGateError(f"coverage[{index}] has unsupported keys")
        criterion=_text(item.get("criterion"),f"coverage[{index}].criterion")
        if criterion not in criteria:
            raise CompletionGateError(f"coverage[{index}] references out-of-scope criterion")
        if criterion in observed:
            raise CompletionGateError(f"duplicate coverage criterion: {criterion}")
        observed.add(criterion)
        status=item.get("status")
        if status not in {"covered","missing"}:
            raise CompletionGateError(f"coverage[{index}].status must be covered|missing")
        evidence=item.get("evidence")
        if not isinstance(evidence,list) or any(not isinstance(x,str) or not x.strip() for x in evidence):
            raise CompletionGateError(f"coverage[{index}].evidence must be string array")
        if status=="covered" and not evidence:
            raise CompletionGateError(f"covered criterion requires evidence: {criterion}")
        normalized.append({"criterion":criterion,"status":status,"evidence":[x.strip() for x in evidence]})
    missing_criteria=[item for item in criteria if item not in observed]
    missing_coverage=[item["criterion"] for item in normalized if item["status"]=="missing"]
    findings=payload.get("findings")
    if not isinstance(findings,list) or any(not isinstance(x,str) or not x.strip() for x in findings):
        raise CompletionGateError("completion.findings must be string array")
    rationale=_text(payload.get("rationale"),"completion.rationale")

    if disposition=="pass" and (missing_criteria or missing_coverage or findings):
        raise CompletionGateError("completion PASS requires complete coverage and no findings")
    if disposition in {"fix","blocked"} and not (missing_criteria or missing_coverage or findings):
        raise CompletionGateError(f"completion {disposition.upper()} requires a material gap")

    return {
        "disposition":disposition,
        "coverage":normalized,
        "missingCriteria":missing_criteria,
        "findings":[x.strip() for x in findings],
        "rationale":rationale,
    }


def evaluate_completion(root: Path, step_id: str, payload: Any | None) -> dict[str,Any]:
    precheck=deterministic_precheck(root,step_id)
    if precheck["status"]!="PASS":
        return {
            "schemaVersion":1,
            "status":"BLOCKED",
            "completionResult":"BLOCKED",
            "stepId":step_id,
            "reasonCode":"COMPLETION_PRECHECK_BLOCKED",
            "precheck":precheck,
        }

    criteria=precheck["acceptanceCriteria"]
    if payload is None:
        return {
            "schemaVersion":1,
            "status":"INCOMPLETE",
            "completionResult":"FAIL",
            "stepId":step_id,
            "reasonCode":"COMPLETION_COVERAGE_MISSING",
            "precheck":precheck,
            "findings":["Semantic acceptance coverage was not supplied."],
        }

    semantic=normalize_semantic_completion(payload,criteria)
    disposition=semantic["disposition"]
    if disposition=="pass":
        status,result="PASS","PASS"
    elif disposition=="fix":
        status,result="INCOMPLETE","FAIL"
    else:
        status,result="BLOCKED","BLOCKED"
    return {
        "schemaVersion":1,
        "status":status,
        "completionResult":result,
        "stepId":step_id,
        "reasonCode":None if disposition=="pass" else (
            "COMPLETION_IN_SCOPE_WORK_MISSING" if disposition=="fix"
            else "COMPLETION_CONTRACT_BLOCKED"
        ),
        "precheck":precheck,
        "semantic":semantic,
    }
