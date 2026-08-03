"""Decision-match shadow metrics — paper-only, no checkpoint load.

Consumes the live ``production_equivalence_comparison.json`` and the
continuous-remediation gap matrix to quantify why V2 actions diverge
from legacy actions. NEVER invents outcomes. NEVER deserializes any
checkpoint. NEVER mutates legacy.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

COMPARISON_PATH = Path(
    "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/production_equivalence_comparison.json"
)
GAP_MATRIX_PATH = Path(
    "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/continuous_remediation/legacy_log_v2_gap_matrix.json"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def compute_shadow_metrics() -> dict[str, Any]:
    cmp_payload = _load_json(COMPARISON_PATH)
    gap_matrix = _load_json(GAP_MATRIX_PATH)
    per_symbol = cmp_payload.get("per_symbol") or []
    n_symbols = len(per_symbol)
    n_matches = sum(1 for r in per_symbol if r.get("match") is True)
    n_mismatches = sum(1 for r in per_symbol if r.get("match") is False)
    action_match_rate = (n_matches / n_symbols) if n_symbols else None
    v2_hold_due_checkpoint_count = sum(
        1
        for r in per_symbol
        if r.get("mismatch_source") == "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
    )
    v2_hold_due_strict_gate_count = sum(
        1
        for r in per_symbol
        if (r.get("v2") or {}).get("paper_fill_allowed") is False
        and (r.get("v2") or {}).get("paper_fill_gate_block_reasons")
    )
    missing_legacy_log_evidence_count = sum(
        1
        for g in gap_matrix.get("gaps") or []
        if g.get("cause") == "missing_legacy_log_action_evidence"
    )
    no_action_safe_block_count = sum(
        1
        for g in gap_matrix.get("gaps") or []
        if g.get("severity") == "NO_ACTION_REQUIRED_SAFE_BLOCK"
    )
    rows: list[dict[str, Any]] = []
    for r in per_symbol:
        v2 = r.get("v2") or {}
        legacy = r.get("legacy") or {}
        rows.append(
            {
                "symbol": r.get("symbol"),
                "legacy_action": legacy.get("action"),
                "v2_action": v2.get("selected_action"),
                "match": bool(r.get("match")),
                "checkpoint_blocker_active": (
                    v2.get("checkpoint_blocker")
                    == "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
                ),
                "strict_gate_blocker_active": v2.get("paper_fill_allowed") is False,
                "feature_missing_or_stale": v2.get("feature_freshness_state")
                not in (None, "fresh"),
                "mismatch_source": r.get("mismatch_source"),
                "paper_fill_gate_block_reasons": list(
                    v2.get("paper_fill_gate_block_reasons") or []
                ),
            }
        )
    # Decide the exact next required fix for each row.
    next_required_by_symbol: dict[str, str] = {}
    for row in rows:
        if row["match"]:
            next_required_by_symbol[row["symbol"]] = "NO_ACTION_REQUIRED_SAFE_BLOCK"
        elif row["checkpoint_blocker_active"]:
            next_required_by_symbol[row["symbol"]] = "CHECKPOINT_ARTIFACT_REQUIRED_OR_FULL_OBSERVATION_BUILDER_OR_POLICY_PORT"
        elif row["strict_gate_blocker_active"]:
            next_required_by_symbol[row["symbol"]] = "NO_ACTION_REQUIRED_SAFE_BLOCK"
        elif row["feature_missing_or_stale"]:
            next_required_by_symbol[row["symbol"]] = "FEATURE_FIELD_MISSING_OR_STALE"
        else:
            next_required_by_symbol[row["symbol"]] = "UNDETERMINED_REQUIRES_REVIEW"
    return {
        "schema_version": "v2_model_decision_match_shadow_metrics_v1",
        "generated_utc": _utc_iso(),
        "comparator_source": str(COMPARISON_PATH),
        "gap_matrix_source": str(GAP_MATRIX_PATH),
        "symbols_total": n_symbols,
        "action_match_count": n_matches,
        "action_mismatch_count": n_mismatches,
        "action_match_rate": action_match_rate,
        "v2_hold_due_checkpoint_count": v2_hold_due_checkpoint_count,
        "v2_hold_due_strict_gate_count": v2_hold_due_strict_gate_count,
        "missing_legacy_log_evidence_count": missing_legacy_log_evidence_count,
        "no_action_safe_block_count": no_action_safe_block_count,
        "per_symbol": rows,
        "next_required_by_symbol": next_required_by_symbol,
        "no_invented_outcomes": True,
        "paper_edge_claimed": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def write_shadow_metrics(worklog_path: Path, public_path: Path) -> dict[str, Any]:
    payload = compute_shadow_metrics()
    worklog_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog_path.write_text(body, encoding="utf-8")
    public_path.write_text(body, encoding="utf-8")
    return payload
