#!/usr/bin/env python3
"""Synthetic regressions for Requirements Quality Gate contract."""
from __future__ import annotations

from requirements_quality import RequirementsQualityError, normalize_result


BASE_QUALITY = {
    "completeness": "pass",
    "clarity": "pass",
    "measurability": "pass",
    "scenarioCoverage": "pass",
}


def expect_error(payload: object, needle: str) -> None:
    try:
        normalize_result(payload)
    except RequirementsQualityError as exc:
        if needle not in str(exc):
            raise AssertionError(f"unexpected error: {exc}") from exc
    else:
        raise AssertionError("expected RequirementsQualityError")


def main() -> int:
    passed = normalize_result(
        {
            "schemaVersion": 1,
            "status": "PASS",
            "quality": dict(BASE_QUALITY),
            "findings": [],
        }
    )
    assert passed["status"] == "PASS"

    needs_input = normalize_result(
        {
            "schemaVersion": 1,
            "status": "NEEDS_INPUT",
            "quality": {**BASE_QUALITY, "measurability": "fail"},
            "findings": [
                {
                    "code": "AMBIGUOUS_RECOVERY_POLICY",
                    "severity": "blocking",
                    "owner": "REQ-014",
                    "question": "Какой recovery behavior обязателен после timeout?",
                    "rationale": "Ответ меняет acceptance и retry semantics.",
                    "sourceRefs": ["REQ-014#Reliability"],
                }
            ],
        }
    )
    assert needs_input["findings"][0]["owner"] == "REQ-014"

    warning_only = normalize_result(
        {
            "schemaVersion": 1,
            "status": "PASS",
            "quality": {**BASE_QUALITY, "clarity": "warn"},
            "findings": [
                {
                    "code": "MINOR_TERMINOLOGY_DRIFT",
                    "severity": "warning",
                    "owner": "STEP-024",
                    "question": "Унифицировать термин в следующем редактировании?",
                    "rationale": "Не меняет implementation или validation.",
                    "sourceRefs": [],
                }
            ],
        }
    )
    assert warning_only["status"] == "PASS"

    repeated = normalize_result(needs_input)
    assert repeated == needs_input

    expect_error(
        {
            "schemaVersion": 1,
            "status": "NEEDS_INPUT",
            "quality": dict(BASE_QUALITY),
            "findings": [
                {
                    "code": "WRONG_OWNER",
                    "severity": "blocking",
                    "owner": "docs/requirements/foo.md",
                    "question": "Кто владеет решением?",
                    "rationale": "Owner должен быть canonical.",
                    "sourceRefs": [],
                }
            ],
        },
        "owner must be PROJECT or canonical",
    )
    expect_error(
        {
            "schemaVersion": 1,
            "status": "PASS",
            "quality": dict(BASE_QUALITY),
            "findings": [
                {
                    "code": "BLOCKER_IN_PASS",
                    "severity": "blocking",
                    "owner": "PROJECT",
                    "question": "Нужен ответ?",
                    "rationale": "Blocking finding не совместим с PASS.",
                    "sourceRefs": [],
                }
            ],
        },
        "PASS cannot contain blocking",
    )
    print("requirements-quality self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
