"""Compatibility wrapper for Codex fail remap tooling."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from typing import Any

from v2.backend.app.closed_loop.services.fail_mapper import (
    build_codex_fail_to_remediation_map,
    classify_fail,
    classify_from_output,
)

__all__ = [
    "build_codex_fail_to_remediation_map",
    "classify_codex_fail",
    "classify_fail",
    "classify_from_output",
]


def classify_codex_fail(*, verdict: dict[str, Any]) -> dict[str, Any]:
    fail_blockers = [str(row) for row in verdict.get("fail_blockers") or []]
    review_text = " ".join(
        fail_blockers
        + [str(verdict.get("verdict") or ""), str(verdict.get("next_action") or "")]
    )
    classification = classify_fail(fail_blockers) if fail_blockers else classify_from_output(
        review_text
    )
    lowered = review_text.lower()
    if "operator-approved" in lowered or "operator approved" in lowered:
        classification["operator_required"] = True
        classification["unsafe_to_fix"] = False
    existing_remediation_descriptor_path = verdict.get("existing_remediation_descriptor_path")
    remediation_required = not classification["operator_required"] and not classification[
        "unsafe_to_fix"
    ]
    terminal_classification = None
    not_automatable_reason = None
    if existing_remediation_descriptor_path:
        remediation_required = False
        terminal_classification = "EXISTING_REMEDIATION_REFERENCED"
    elif classification["unsafe_to_fix"]:
        remediation_required = False
        terminal_classification = "UNSAFE_TO_FIX_AUTOMATION_BLOCKED"
        not_automatable_reason = "unsafe_to_fix"
    elif classification["operator_required"]:
        remediation_required = False
        terminal_classification = "OPERATOR_REQUIRED"
        not_automatable_reason = "operator_required"
    elif fail_blockers:
        terminal_classification = "REMEDIATION_DESCRIPTOR_REQUIRED"
    return {
        "codex_fail_id": verdict.get("task_id"),
        "codex_review_path": verdict.get("path"),
        "failed_gate": verdict.get("verdict"),
        "fail_blockers": fail_blockers,
        "remediation_required": remediation_required,
        "remediation_descriptor_created": False,
        "remediation_descriptor_path": None,
        "existing_remediation_descriptor_path": existing_remediation_descriptor_path,
        "duplicate_suppressed": False,
        "operator_required": bool(classification["operator_required"]),
        "unsafe_to_fix": bool(classification["unsafe_to_fix"]),
        "not_automatable_reason": not_automatable_reason,
        "next_action": verdict.get("next_action"),
        "terminal_classification": terminal_classification,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args(argv)
    _ = args.db_path
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
