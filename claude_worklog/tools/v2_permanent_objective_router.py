#!/usr/bin/env python3
"""V2 Permanent Objective Router.

Reads the live blocker matrices, parity gap matrix, paper edge state, expected-move
model review, trainer bridge status, and worker porting state. Picks the highest
priority blocker, classifies whether a Claude task is already running, and emits a
router_status.json that downstream supervisors can act on.

Hard rules:
- Does not place, cancel, or modify exchange orders.
- Does not change leverage or margin mode.
- Does not write to old Redis.
- Does not enable live trading.
- Does not produce final live or Redis-trim approval tokens.
- Does not route to UI-only tasks unless P0 runtime blockers are cleared.

The router is read-mostly: it writes only into
- claude_worklog/final_readiness/permanent_migration_runtime/latest/
- v2/frontend/public/permanent_migration_runtime/latest/
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# Inputs
BLOCKER_MATRIX = ROOT / "claude_worklog/final_readiness/codex_shutdown_readiness_takeover/latest/blocker_matrix.json"
OBSERVATORY = ROOT / "v2/frontend/public/operator_runtime/legacy_v2_decision_comparator/latest/legacy_v2_decision_comparator_status.json"
PAPER_EDGE_PAYLOAD = ROOT / "v2/frontend/public/paper_edge_recovery/latest/operator_dashboard_payload.json"
PAPER_SHADOW_OUTCOME = ROOT / "v2/frontend/public/operator_runtime/paper_shadow_outcome_observer/latest/paper_shadow_outcome_observer_status.json"
EXPECTED_MOVE_REVIEW = ROOT / "v2/frontend/public/expected_move_model_review/latest/operator_dashboard_payload.json"
PARITY_MATRIX = ROOT / "claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/v2_parity_gap_matrix.json"
NEXT_REMEDIATION = ROOT / "claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/next_remediation_tasks_for_claude.json"
WORKER_PORTING = ROOT / "claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/worker_porting_state.json"
TRAINER_BRIDGE_STATUS = ROOT / "v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json"
OPERATOR_RUNTIME = ROOT / "v2/frontend/public/operator_runtime"

# Outputs
OUT_DIR = ROOT / "claude_worklog/final_readiness/permanent_migration_runtime/latest"
PUBLIC_DIR = ROOT / "v2/frontend/public/permanent_migration_runtime/latest"
STATUS_JSON = OUT_DIR / "router_status.json"
STATUS_MD = OUT_DIR / "ROUTER_STATUS.md"
PUBLIC_STATUS = PUBLIC_DIR / "router_status.json"

# Forbidden-action and live-only guards
FORBIDDEN_TASKS = {
    "claude_enable_live_trading",
    "claude_authorize_canary",
    "claude_redis_trim_approval",
    "claude_legacy_shutdown_authorize",
    "claude_change_leverage",
    "claude_change_margin_mode",
}


# ---------------------------------------------------------------------------- helpers


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _review_current_enough(*, reviewed: int, current: int) -> bool:
    if current <= reviewed:
        return True
    drift = current - reviewed
    tolerance = max(10, int(max(reviewed, 1) * 0.25))
    return drift <= tolerance


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


# ---------------------------------------------------------------------------- ingestion


def load_inputs() -> dict[str, Any]:
    return {
        "blocker_matrix": read_json(BLOCKER_MATRIX) or {},
        "observatory": read_json(OBSERVATORY) or {},
        "paper_edge": read_json(PAPER_EDGE_PAYLOAD) or {},
        "paper_shadow_outcome": read_json(PAPER_SHADOW_OUTCOME) or {},
        "expected_move_review": read_json(EXPECTED_MOVE_REVIEW) or {},
        "parity_matrix": read_json(PARITY_MATRIX) or {},
        "next_remediation": read_json(NEXT_REMEDIATION) or {},
        "worker_porting": read_json(WORKER_PORTING) or {},
        "trainer_bridge": read_json(TRAINER_BRIDGE_STATUS) or {},
    }


# ---------------------------------------------------------------------------- priorities


PRIORITY_ORDER = [
    # P0
    ("P0", "PAPER_EDGE_UNPROVEN"),
    ("P0", "EXPECTED_MOVE_MODEL_REVIEW_INCOMPLETE"),
    ("P0", "TRAINER_PARITY_INCOMPLETE"),
    ("P0", "RISK_TRADER_ACTION_PARITY_INCOMPLETE"),
    ("P0", "SIGNAL_PUBLISHER_SCHEMA_PARITY_INCOMPLETE"),
    ("P0", "ORCHESTRATOR_PARITY_INCOMPLETE"),
    ("P0", "ACCOUNT_READONLY_PERMISSION_EVIDENCE_INCOMPLETE"),
    ("P0", "FRESHNESS_GUARD_BLOCKED_ON_STALE_PUBLIC_ARTIFACTS"),
    # P1
    ("P1", "FRONTEND_TRUTH_PAYLOADS_MISSING"),
    ("P1", "REPLAY_BACKTEST_COMPARISON_INCOMPLETE"),
    ("P1", "EXPLAINABILITY_REPORTS_INCOMPLETE"),
    # P2 (always blocked until P0/P1 clear)
    ("P2", "LIVE_CANARY_PROOF_PROTOCOL"),
]


def classify_blockers(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate raw inputs into a uniform list of router blocker rows."""
    rows: list[dict[str, Any]] = []

    bm = inputs.get("blocker_matrix", {}) or {}
    for b in bm.get("blockers", []) or []:
        rows.append({
            "id": b.get("id"),
            "category": b.get("category"),
            "evidence": b.get("evidence", ""),
            "remediation_task_id": b.get("remediation_task_id"),
            "source": "codex_shutdown_readiness_takeover",
        })

    em = inputs.get("expected_move_review", {}) or {}
    shadow = inputs.get("paper_shadow_outcome", {}) or {}
    reviewed_false_blocks = _as_int(em.get("false_block_count"))
    current_false_blocks = _as_int(shadow.get("false_block_count"))
    review_current_enough = _review_current_enough(
        reviewed=reviewed_false_blocks,
        current=current_false_blocks,
    )
    if em.get("outcome_status") == "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED" or not review_current_enough:
        review_state = "current" if review_current_enough else "stale_against_shadow_observer"
        rows.append({
            "id": "EXPECTED_MOVE_MODEL_REVIEW_INCOMPLETE",
            "category": "P0_SHUTDOWN_BLOCKER",
            "evidence": (
                f"expected_move_review.go_no_go={em.get('go_no_go')} outcome={em.get('outcome_status')} "
                f"review_state={review_state} reviewed_false_blocks={reviewed_false_blocks} "
                f"current_false_blocks={current_false_blocks}"
            ),
            "remediation_task_id": "claude_v2_expected_move_model_review_and_false_block_calibration",
            "source": "expected_move_model_review",
        })

    tb = inputs.get("trainer_bridge", {}) or {}
    parity_status = tb.get("trainer_parity_status") or tb.get("legacy_hybrid_parity_status")
    if parity_status and parity_status != "FULL_LEGACY_PARITY_READY":
        rows.append({
            "id": "TRAINER_PARITY_INCOMPLETE",
            "category": "P0_SHUTDOWN_BLOCKER",
            "evidence": f"trainer_bridge.parity_status={parity_status}",
            "remediation_task_id": "claude_port_v2_trainer_bridge_full_legacy_parity",
            "source": "v2_trainer_bridge",
        })

    pm = inputs.get("parity_matrix", {}) or {}
    sc = pm.get("summary_counts") or {}
    if sc.get("FULLY_MIGRATED", 0) == 0 and any(
        sc.get(k, 0) > 0 for k in ("PARTIALLY_MIGRATED", "MISSING_IN_V2", "BLOCKED_BY_TRAINER_PARITY")
    ):
        rows.append({
            "id": "PARITY_MATRIX_NO_FULLY_MIGRATED",
            "category": "P0_SHUTDOWN_BLOCKER",
            "evidence": f"parity_matrix.summary_counts={sc}",
            "remediation_task_id": "claude_resolve_parity_matrix_gaps",
            "source": "legacy_rl_risk_trainer_trader_closure",
        })

    wp = inputs.get("worker_porting", {}) or {}
    for b in wp.get("blockers", []) or []:
        if b.get("id") and not any(r.get("id") == b.get("id") for r in rows):
            rows.append({
                "id": b.get("id"),
                "category": b.get("category", "P0_SHUTDOWN_BLOCKER"),
                "evidence": b.get("evidence", ""),
                "remediation_task_id": b.get("remediation_task_id"),
                "source": "worker_porting_orchestrator",
            })

    return rows


def priority_index(row: dict[str, Any]) -> int:
    """Lower index = higher priority. Unknown blockers go last."""
    rid = (row.get("id") or "").upper()
    cat = (row.get("category") or "").upper()
    # explicit P0 mapping
    map_p0 = {
        "PAPER_EDGE_UNPROVEN": 0,
        "EXPECTED_MOVE_MODEL_REVIEW_INCOMPLETE": 1,
        "TRAINER_PARITY_INCOMPLETE": 2,
        "LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED": 2,
        "LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE": 2,
        "LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED": 2,
        "PARITY_MATRIX_NO_FULLY_MIGRATED": 3,
        "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY": 4,
        "FRESHNESS_GUARD_BLOCKED_ON_STALE_PUBLIC_ARTIFACTS": 5,
    }
    if rid in map_p0:
        return map_p0[rid]
    if cat.startswith("P0"):
        return 10
    if cat.startswith("OPERATOR_DECISION_REQUIRED"):
        return 20
    if cat.startswith("P1"):
        return 30
    if cat.startswith("INFO"):
        return 90
    if cat.startswith("P2"):
        return 99
    return 100


def select_highest_priority(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    ordered = sorted(rows, key=priority_index)
    return ordered[0]


# ---------------------------------------------------------------------------- safety guards


def safety_guard(task_id: str | None) -> dict[str, Any]:
    if not task_id:
        return {"safe": True, "reason": "no_task_dispatched"}
    if task_id in FORBIDDEN_TASKS:
        return {"safe": False, "reason": f"forbidden_task:{task_id}"}
    if "live" in task_id and "block" not in task_id and "blocked" not in task_id:
        # allow tasks that *manage* the live block but not those that authorize live.
        if any(k in task_id for k in ("authorize", "enable", "approve", "activate")):
            return {"safe": False, "reason": f"forbidden_live_authorization_task:{task_id}"}
    if "redis_trim" in task_id and "approval" in task_id:
        return {"safe": False, "reason": f"forbidden_redis_trim_approval_task:{task_id}"}
    return {"safe": True, "reason": "ok"}


# ---------------------------------------------------------------------------- routing


def route(inputs: dict[str, Any]) -> dict[str, Any]:
    rows = classify_blockers(inputs)
    selected = select_highest_priority(rows)
    next_action: dict[str, Any] = {
        "selected_blocker": selected,
        "next_task_id": (selected or {}).get("remediation_task_id"),
        "priority_bucket": "P0" if priority_index(selected or {}) <= 10 else
                          ("P1" if priority_index(selected or {}) <= 30 else "P2_OR_INFO"),
    }
    guard = safety_guard(next_action.get("next_task_id"))
    next_action["safety_guard"] = guard

    p0_clear = not any(priority_index(r) <= 10 for r in rows)
    p1_clear = p0_clear and not any(priority_index(r) <= 30 for r in rows)

    next_action["p0_blockers_remaining"] = sum(1 for r in rows if priority_index(r) <= 10)
    next_action["p1_blockers_remaining"] = sum(1 for r in rows if 10 < priority_index(r) <= 30)
    next_action["p2_blockers_blocked_until_p0_p1_clear"] = sum(1 for r in rows if priority_index(r) >= 90)

    next_action["routing_allowed_to_ui_only_work"] = p0_clear
    next_action["routing_allowed_to_live_canary_work"] = False
    next_action["live_gate"] = "blocked_human_only"
    next_action["live_symbols"] = []
    next_action["final_approval_token"] = "absent"
    next_action["redis_trim_approval_token"] = "absent"
    next_action["all_blockers"] = rows
    return next_action


# ---------------------------------------------------------------------------- main


def build_status(inputs: dict[str, Any]) -> dict[str, Any]:
    routing = route(inputs)
    status: dict[str, Any] = {
        "router_id": "v2_permanent_objective_router",
        "generated_utc": now_iso(),
        "contract_ref": "claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md",
        "inputs_present": {k: bool(v) for k, v in inputs.items()},
        "routing": routing,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "must_remain_blocked_human_only": True,
    }
    return status


def render_md(status: dict[str, Any]) -> str:
    r = status["routing"]
    sel = r.get("selected_blocker") or {}
    lines = [
        "# V2 Permanent Objective Router Status",
        "",
        f"Generated: `{status['generated_utc']}`",
        f"Live gate: `{r.get('live_gate')}`",
        f"Live symbols: `{json.dumps(r.get('live_symbols'))}`",
        f"Final approval token: `{status.get('approves_live') and 'present' or 'absent'}`",
        "",
        "## Selected highest-priority blocker",
        "",
        f"- id: `{sel.get('id') or 'NONE'}`",
        f"- category: `{sel.get('category') or 'n/a'}`",
        f"- source: `{sel.get('source') or 'n/a'}`",
        f"- remediation task id: `{sel.get('remediation_task_id') or 'n/a'}`",
        f"- evidence: `{(sel.get('evidence') or '')[:240]}`",
        "",
        "## Routing summary",
        "",
        f"- P0 blockers remaining: `{r['p0_blockers_remaining']}`",
        f"- P1 blockers remaining: `{r['p1_blockers_remaining']}`",
        f"- P2 blockers (always blocked until P0/P1 clear): `{r['p2_blockers_blocked_until_p0_p1_clear']}`",
        f"- Safety guard: `{r['safety_guard']['reason']}` (safe={r['safety_guard']['safe']})",
        f"- UI-only routing allowed: `{r['routing_allowed_to_ui_only_work']}`",
        f"- Live/canary routing allowed: `{r['routing_allowed_to_live_canary_work']}`",
        "",
        "## All blockers",
        "",
    ]
    for b in r.get("all_blockers", []):
        lines.append(f"- `{b.get('id')}` ({b.get('category')}) from `{b.get('source')}` -> task `{b.get('remediation_task_id')}`")
    lines.append("")
    lines.append("This router does not approve live, canary, legacy shutdown, or Redis trim.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="V2 Permanent Objective Router")
    p.add_argument("--dry-run", action="store_true", help="Compute status but do not write outputs.")
    args = p.parse_args(argv)

    inputs = load_inputs()
    status = build_status(inputs)
    md = render_md(status)

    if args.dry_run:
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0

    write_json(STATUS_JSON, status)
    write_json(PUBLIC_STATUS, status)
    write_text(STATUS_MD, md)
    print(f"router_status_written generated_utc={status['generated_utc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
