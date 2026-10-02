#!/usr/bin/env python3
"""Contract regressions for Completion / Convergence Gate."""
from __future__ import annotations
from completion_gate import CompletionGateError, normalize_semantic_completion

CRITERIA=["User can save the record.","Failed save preserves input."]

def main()->int:
    complete=normalize_semantic_completion({
        "disposition":"pass",
        "coverage":[
            {"criterion":CRITERIA[0],"status":"covered","evidence":["test_save PASS"]},
            {"criterion":CRITERIA[1],"status":"covered","evidence":["test_failed_save PASS"]},
        ],
        "findings":[],
        "rationale":"All in-scope acceptance obligations are proven.",
    },CRITERIA)
    assert complete["disposition"]=="pass"

    fix=normalize_semantic_completion({
        "disposition":"fix",
        "coverage":[
            {"criterion":CRITERIA[0],"status":"covered","evidence":["test_save PASS"]},
            {"criterion":CRITERIA[1],"status":"missing","evidence":[]},
        ],
        "findings":["Error path is not implemented."],
        "rationale":"Missing behavior is inside approved STEP scope.",
    },CRITERIA)
    assert fix["disposition"]=="fix"

    blocked=normalize_semantic_completion({
        "disposition":"blocked",
        "coverage":[
            {"criterion":CRITERIA[0],"status":"covered","evidence":["test_save PASS"]}
        ],
        "findings":["Second criterion depends on an unresolved product contract."],
        "rationale":"Contract-level decision is missing.",
    },CRITERIA)
    assert blocked["missingCriteria"]==[CRITERIA[1]]

    try:
        normalize_semantic_completion({
            "disposition":"pass",
            "coverage":[{"criterion":"Out of scope obligation","status":"covered","evidence":["x"]}],
            "findings":[],
            "rationale":"invalid",
        },CRITERIA)
    except CompletionGateError as exc:
        assert "out-of-scope" in str(exc)
    else:
        raise AssertionError("out-of-scope completion obligation was accepted")
    print("completion-gate self-test: PASS")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
