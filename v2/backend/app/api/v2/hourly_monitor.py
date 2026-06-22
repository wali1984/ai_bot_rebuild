"""V2 hourly monitor status route.

Serves combined status from raw_evidence/*.json artifacts written by the
continuous hourly monitor CLI. Read-only; never mutates exchange or Redis.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/monitor", tags=["v2-monitor"])

_REPO_ROOT = Path(__file__).resolve().parents[5]
_EVIDENCE_DIR = _REPO_ROOT / "raw_evidence"

_ARTIFACT_FILES: dict[str, str] = {
    "soak": "paper_soak_500_trade_status.json",
    "loss_recovery": "paper_loss_recovery_status.json",
    "quality_3h": "latest_3h_paper_quality_status.json",
    "monitor_summary": "continuous_hourly_monitor_status.json",
    "pnl": "paper_trader_hourly_pnl.json",
    "orchestrator": "orchestrator_hourly_decision_quality.json",
    "leverage": "adaptive_action_leverage_margin_hourly_status.json",
    "shap": "shap_attribution_status.json",
    "runtime_update": "adaptive_runtime_update_status.json",
}

_NO_GO_FILE = "NO_GO_UNTIL_3H_EDGE_VALIDATED.md"


def _read_json(name: str) -> dict[str, Any]:
    path = _EVIDENCE_DIR / name
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"_missing": True, "file": name}


def _read_marker_line() -> str:
    path = _EVIDENCE_DIR / _NO_GO_FILE
    try:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "V2_CONTINUOUS_PAPER" in line or "PAPER_VALIDATED" in line:
                return line.strip().lstrip("*# ").rstrip("*")
    except Exception:
        pass
    return "V2_CONTINUOUS_PAPER_LOSS_RECOVERY_AND_ADAPTIVE_RUNTIME_CONTROL_BLOCKED"


@router.get("/hourly")
async def get_hourly_monitor_status() -> dict[str, Any]:
    artifacts: dict[str, Any] = {k: _read_json(v) for k, v in _ARTIFACT_FILES.items()}
    marker = _read_marker_line()

    soak = artifacts["soak"]
    monitor = artifacts["monitor_summary"]
    loss = artifacts["loss_recovery"]
    quality = artifacts["quality_3h"]
    pnl = artifacts["pnl"]
    orch = artifacts["orchestrator"]
    lev = artifacts["leverage"]
    shap = artifacts["shap"]
    rt = artifacts["runtime_update"]

    return {
        "final_marker": marker,
        "live_gate": "blocked_human_only",
        "mutates_exchange": False,
        "places_real_order": False,
        "generated_at": monitor.get("generated_at"),

        "soak": {
            "closed_trade_count": soak.get("closed_trade_count", 0),
            "soak_target": soak.get("soak_target", 500),
            "soak_progress_pct": soak.get("soak_progress_pct", 0),
            "soak_remaining": soak.get("soak_remaining"),
            "soak_met": soak.get("soak_met", False),
            "win_rate": soak.get("win_rate"),
            "win_rate_target": soak.get("win_rate_target", 0.55),
            "blocker_3_status": soak.get("blocker_3_status"),
        },

        "quality_3h": {
            "verdict": quality.get("quality_verdict"),
            "windows_evaluated": quality.get("windows_evaluated", 0),
            "clean_windows": quality.get("clean_windows", 0),
            "losing_windows": quality.get("losing_windows", 0),
            "total_closed_trades_3h": quality.get("total_closed_trades_3h", 0),
            "total_realized_pnl_3h": quality.get("total_realized_pnl_3h", 0),
        },

        "monitor_summary": {
            "hourly_windows_computed": monitor.get("hourly_windows_computed", 0),
            "cumulative_artifacts_written": monitor.get("cumulative_artifacts_written", 0),
            "outcome_memory_buckets_updated": monitor.get("outcome_memory_buckets_updated", 0),
            "closed_trades_all_time": monitor.get("closed_trades_all_time", 0),
            "closed_trades_3h_windows": monitor.get("closed_trades_3h_windows", 0),
            "shap_blocker_status": monitor.get("shap_blocker_status"),
        },

        "loss_recovery": {
            "tightening_active": loss.get("tightening_active", False),
            "tightening_reason": loss.get("tightening_reason"),
            "losing_windows": loss.get("losing_windows", 0),
            "clean_windows": loss.get("clean_windows", 0),
            "consecutive_clean_windows": loss.get("consecutive_clean_windows", 0),
            "recovery_required_windows": loss.get("recovery_required_windows", 3),
            "gate_overrides_active": loss.get("gate_overrides_active", False),
            "min_confidence_if_tightened": loss.get("min_confidence_if_tightened"),
            "min_edge_bps_if_tightened": loss.get("min_edge_bps_if_tightened"),
        },

        "pnl": {
            "fill_count": pnl.get("fill_count", 0),
            "closed_trade_count": pnl.get("closed_trade_count", 0),
            "open_position_count": pnl.get("open_position_count", 0),
            "blocked_count": pnl.get("blocked_count", 0),
            "paper_realized_pnl": pnl.get("paper_realized_pnl"),
            "paper_unrealized_pnl": pnl.get("paper_unrealized_pnl"),
            "win_count": pnl.get("win_count", 0),
            "loss_count": pnl.get("loss_count", 0),
            "win_rate": pnl.get("win_rate"),
            "profit_factor": pnl.get("profit_factor"),
            "max_drawdown_usdt": pnl.get("max_drawdown_usdt"),
            "top_block_reasons": pnl.get("top_block_reasons", []),
            "exit_reason_counts": pnl.get("exit_reason_counts", {}),
            "live_mutation_count_must_be_zero": pnl.get("live_mutation_count_must_be_zero", 0),
        },

        "orchestrator": {
            "total_decisions": orch.get("total_decisions", 0),
            "accepted_count": orch.get("accepted_count", 0),
            "blocked_count": orch.get("blocked_count", 0),
            "accept_rate": orch.get("orchestrator_accept_rate"),
        },

        "leverage": {
            "adaptive_leverage_recommendation_count": lev.get("adaptive_leverage_recommendation_count", 0),
            "adaptive_margin_recommendation_count": lev.get("adaptive_margin_recommendation_count", 0),
            "note": "Count=0 expected for pre-wiring-sprint events. New fills through Phase 3/4/9 gates will populate this.",
        },

        "shap": {
            "blocker_4_status": shap.get("blocker_4_status"),
            "shap_available": shap.get("shap_available", False),
            "attribution_method": shap.get("attribution_method"),
            "attribution_note": shap.get("attribution_note"),
            "predictions_enriched": shap.get("predictions_enriched", 0),
            "waiveable_by_operator_for_paper": shap.get("waiveable_by_operator_for_paper", True),
        },

        "outcome_memory": {
            "buckets_updated": rt.get("outcome_memory_update", {}).get("buckets_updated", 0),
            "events_processed": rt.get("outcome_memory_update", {}).get("events_processed", 0),
            "bucket_keys": rt.get("outcome_memory_update", {}).get("bucket_keys", []),
            "stores_updated": rt.get("stores_updated", 0),
            "store_types": rt.get("store_types", []),
        },
    }


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return {
        "group": "monitor",
        "prefix": "/monitor",
        "endpoints": ("/hourly",),
        "exchange_action_taken": False,
        "live_gate": "blocked_human_only",
    }
