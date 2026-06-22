"""Codex fail classifier and fail map compatibility helpers."""

from __future__ import annotations

from typing import Any


UNSAFE_TOKENS = (
    "exchange mutation",
    "canary",
    "shutdown",
    "redis_trim",
    "unsafe",
    "live order",
)

OPERATOR_TOKENS = (
    "operator required",
    "manual",
    "approval",
)


def classify_from_output(text: str) -> dict[str, Any]:
    lowered = (text or "").lower()
    operator_required = any(token in lowered for token in OPERATOR_TOKENS)
    unsafe_to_fix = any(token in lowered for token in UNSAFE_TOKENS)
    if unsafe_to_fix:
        classification = "unsafe_to_fix"
    elif operator_required:
        classification = "operator_required"
    else:
        classification = "remediation_available"
    return {
        "classification": classification,
        "operator_required": operator_required or unsafe_to_fix,
        "unsafe_to_fix": unsafe_to_fix,
    }


def classify_fail(blockers: list[str]) -> dict[str, Any]:
    return classify_from_output(" ".join(blockers))


def build_codex_fail_to_remediation_map(store, task_id: str, blockers: list[str]) -> dict[str, Any]:
    classification = classify_fail(blockers)
    remediation_task_id = None
    if not classification["operator_required"] and not classification["unsafe_to_fix"]:
        remediation_task_id = f"closed_loop_remediation_{task_id}"
    created = store.add_codex_fail_map(
        codex_task_id=task_id,
        classification=classification["classification"],
        remediation_task_id=remediation_task_id,
        operator_required=classification["operator_required"],
        unsafe_to_fix=classification["unsafe_to_fix"],
        payload={"blockers": blockers, "generated_by": "v2_closed_loop"},
    )
    return {
        "task_id": task_id,
        "created": bool(created),
        "remediation_task_id": remediation_task_id,
        "classification": classification,
    }
