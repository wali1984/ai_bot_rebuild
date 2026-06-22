"""V2 Autonomous Work Selector.

Reads the latest issue snapshot from the issue classifier and the
pending-task watchdog, then selects ONE next work item — or signals
``NO_AUTOMATABLE_WORK_REMAINING`` — according to the priority order
spelled out in the operator's V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING
spec.

The selector NEVER picks any of these even if they look "next":

- policy architecture (operator gate, requires observation gate first)
- checkpoint load (operator gate, do not deserialize blobs)
- live trading
- canary trading
- shutdown acceptance
- paid endpoint adoption
- automatic Symbol Universe adoption
- external source adoption without operator decision

When no automatable work remains, the selector emits a
``no_automatable_work_remaining.json`` payload listing the operator /
external / event / position gates that are blocking further automated
progress.

Read-only with respect to legacy code, Redis, exchanges. Only writes
local JSON status artifacts.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
)

# Order matches the user's PHASE 5 priority list.
PRIORITY_ORDER: tuple[str, ...] = (
    # 1 safety drift
    "LIVE_GATE_DRIFT",
    "SYMBOL_UNIVERSE_MUTATION_RISK",
    "OLD_REDIS_WRITE_RISK",
    "EXCHANGE_MUTATION_RISK",
    "SECRET_LEAK_RISK",
    # 2 runtime liveness
    "RUNTIME_PROCESS_DOWN",
    "REDIS_NAMESPACE_EMPTY",
    # 3 stale payloads
    "PAYLOAD_STALE",
    # 4 failed Codex reviews
    "CODEX_REVIEW_FAIL",
    # 5 pending/stalled exact-source tasks
    "CLAUDE_TASK_STALLED",
    "CODEX_TASK_STALLED",
    # 6 full-observation exact-source tasks
    "EXACT_SOURCE_IMPLEMENTATION_GAP",
    "MISSING_RUNTIME_PAYLOAD_FIELD",
    # 7 frontend truth
    "FRONTEND_TRUTH_MISMATCH",
    # 8 schema / test
    "SCHEMA_MISMATCH",
    "TEST_FAILURE",
    # 9-11 gates the selector never auto-picks but reports
    "POLICY_ARCHITECTURE_GATE_REQUIRED",
    "CHECKPOINT_ARTIFACT_REQUIRED",
    "EXTERNAL_SOURCE_REQUIRED",
    "OPERATOR_DECISION_REQUIRED",
    "EVENT_DEPENDENT",
    "POSITION_DEPENDENT",
)

# Categories the selector will report but NEVER pick autonomously.
NEVER_AUTO_PICK: frozenset[str] = frozenset({
    "POLICY_ARCHITECTURE_GATE_REQUIRED",
    "CHECKPOINT_ARTIFACT_REQUIRED",
    "EXTERNAL_SOURCE_REQUIRED",
    "OPERATOR_DECISION_REQUIRED",
    "EVENT_DEPENDENT",
    "POSITION_DEPENDENT",
    "LIVE_GATE_DRIFT",  # surface but escalate to operator
    "SECRET_LEAK_RISK",  # surface but escalate to operator
    "SYMBOL_UNIVERSE_MUTATION_RISK",
    "OLD_REDIS_WRITE_RISK",
    "EXCHANGE_MUTATION_RISK",
    "REDIS_NAMESPACE_EMPTY",  # whole-runtime issue: operator
})

UNSAFE_CODEX_FAIL_SOURCE_TOKENS: tuple[str, ...] = (
    "live_canary",
    "canary",
    "shutdown",
    "one_order",
    "approval",
    "redis_trim",
    "legacy_shutdown",
)

SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "INFO": 3}


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _is_unsafe_codex_fail_item(item: dict[str, Any]) -> bool:
    source = str(item.get("source") or "").lower()
    evidence = json.dumps(item.get("exact_evidence") or {}, sort_keys=True).lower()
    text = f"{source} {evidence}"
    return any(token in text for token in UNSAFE_CODEX_FAIL_SOURCE_TOKENS)


def select(issues_doc: dict[str, Any]) -> dict[str, Any]:
    issues = issues_doc.get("issues") or []
    by_category: dict[str, list[dict[str, Any]]] = {}
    for it in issues:
        by_category.setdefault(it["category"], []).append(it)

    selected: dict[str, Any] | None = None
    skipped: list[dict[str, Any]] = []
    no_auto_for_operator: list[dict[str, Any]] = []
    for cat in PRIORITY_ORDER:
        items = by_category.get(cat) or []
        if not items:
            continue
        items.sort(key=lambda it: SEVERITY_RANK.get(it.get("severity", "P2"), 99))
        if cat == "CODEX_REVIEW_FAIL":
            safe_items: list[dict[str, Any]] = []
            for it in items:
                if _is_unsafe_codex_fail_item(it):
                    no_auto_for_operator.append({
                        "category": cat,
                        "severity": it.get("severity"),
                        "source": it.get("source"),
                        "owner": "OPERATOR",
                        "evidence": it.get("exact_evidence"),
                        "remediation": (
                            "live/canary/shutdown/approval Codex failures are "
                            "operator-held; do not auto-remediate before prior gates"
                        ),
                    })
                    continue
                safe_items.append(it)
            if len(safe_items) != len(items):
                skipped.append({
                    "category": cat,
                    "reason": "unsafe_live_shutdown_or_approval_failures_operator_held",
                    "operator_held_count": len(items) - len(safe_items),
                })
            items = safe_items
            if not items:
                continue
        if cat in NEVER_AUTO_PICK:
            for it in items:
                no_auto_for_operator.append({
                    "category": cat,
                    "severity": it.get("severity"),
                    "source": it.get("source"),
                    "owner": it.get("owner"),
                    "evidence": it.get("exact_evidence"),
                    "remediation": it.get("exact_remediation_action"),
                })
            skipped.append({"category": cat, "reason": "never_auto_pick"})
            continue
        if selected is None:
            selected = {
                "category": cat,
                "severity": items[0].get("severity"),
                "owner": items[0].get("owner"),
                "source": items[0].get("source"),
                "evidence": items[0].get("exact_evidence"),
                "remediation": items[0].get("exact_remediation_action"),
                "duplicate_key": items[0].get("duplicate_key"),
            }

    automatable_remaining = sum(
        1 for it in issues if it.get("owner") in ("CLAUDE", "CODEX")
        and it.get("category") not in NEVER_AUTO_PICK
        and not (
            it.get("category") == "CODEX_REVIEW_FAIL"
            and _is_unsafe_codex_fail_item(it)
        )
    )

    result: dict[str, Any] = {
        "schema_version": "v2_autonomous_full_rebuild_self_healing_work_selection_v1",
        "generated_utc": _utc_iso(),
        "automatable_remaining": automatable_remaining,
        "selected_work": selected,
        "skipped_categories": skipped,
        "operator_owned_blockers": no_auto_for_operator,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    if selected is None:
        result["status"] = "NO_AUTOMATABLE_WORK_REMAINING"
        result["next_action"] = (
            "await operator-approved next gate (policy architecture, "
            "checkpoint artifact, paid alt-data, external sources, "
            "event-dependent, position-dependent)"
        )
    else:
        result["status"] = "AUTOMATABLE_WORK_SELECTED"
        result["next_action"] = (
            f"controller dispatches Claude/Codex fix for category"
            f" {selected['category']}"
        )
    return result


def write_artifacts(result: dict[str, Any]) -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (WORKLOG_DIR / "latest_selected_work.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (PUBLIC_DIR / "latest_selected_work.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if result.get("status") == "NO_AUTOMATABLE_WORK_REMAINING":
        (WORKLOG_DIR / "no_automatable_work_remaining.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--issues-path",
        default=str(WORKLOG_DIR / "latest_issues.json"),
        help="path to latest_issues.json from the issue classifier",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    doc = _read_json(Path(args.issues_path))
    if doc is None:
        print(json.dumps({
            "status": "NO_ISSUES_DOC",
            "issues_path": args.issues_path,
            "remediation": "run v2_autonomous_issue_classifier.py first",
        }, indent=2, sort_keys=True))
        return 1
    result = select(doc)
    write_artifacts(result)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "generated_utc": result["generated_utc"],
            "status": result["status"],
            "selected_work": result.get("selected_work"),
            "automatable_remaining": result.get("automatable_remaining"),
            "operator_owned_blockers": len(result.get("operator_owned_blockers") or []),
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
