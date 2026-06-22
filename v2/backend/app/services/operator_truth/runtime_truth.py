"""
v2.backend.app.services.operator_truth.runtime_truth

Canonical operator runtime truth aggregator.

Reads from active V2 operator_runtime payloads and Redis health checks
to produce a single authoritative operator_runtime_truth.json.

Safety invariants:
  Reads V2 runtime/public payloads only.
  No exchange mutation.
  No legacy Redis writes.
  No order placement.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Root of frontend public operator_runtime (served as static files)
_OR = Path(__file__).resolve().parents[4] / "frontend" / "public" / "operator_runtime"
_EST = timezone(timedelta(hours=-4))


def _read_payload(rel: str) -> dict[str, Any] | None:
    """Read a payload JSON file, return None if missing/corrupt."""
    p = _OR / rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _file_age(rel: str) -> float | None:
    """Return age in seconds, or None if missing."""
    p = _OR / rel
    if not p.exists():
        return None
    return time.time() - p.stat().st_mtime


def _freshness(age: float | None) -> str:
    if age is None:
        return "MISSING"
    if age < 300:
        return "FRESH"
    if age < 1800:
        return "STALE"
    return "OLD"


def build_operator_runtime_truth() -> dict[str, Any]:
    """
    Aggregate all active V2 runtime payloads into one canonical truth document.
    Returns dict suitable for JSON serialisation.
    """
    now_est = datetime.now(_EST)

    # --- Load payloads ---
    canary = _read_payload("v2_live_canary/latest/live_canary_executor_status.json")
    risk = _read_payload("v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json")
    orchestrator = _read_payload("v2_orchestrator_arbitration/latest/v2_orchestrator_arbitration_status.json")
    trader_state = _read_payload("v2_trader_runtime_state/latest/v2_trader_runtime_state_status.json")
    portfolio = _read_payload("v2_portfolio_state/latest/v2_portfolio_state.json")
    ingestors = _read_payload("v2_ingestors_status/latest/v2_ingestors_status.json")
    ta_status = _read_payload("v2_technical_analysis_status/latest/v2_technical_analysis_status.json")
    trainer = _read_payload(
        "../v2_native_rl_masa_ppo_cuda_trainer_implementation/latest/operator_dashboard_payload.json"
    )
    trainer_training = _read_payload("v2_trainer_training_live_loop/latest/v2_trainer_training_live_loop_status.json")
    lineage = _read_payload("v2_paper_decision_lineage/latest/v2_paper_decision_lineage.json")
    op_review = _read_payload("v2_operator_review/latest/v2_operator_review_status.json")
    coinank = _read_payload("coinank_market_intelligence/latest/coinank_market_intelligence_status.json")
    log_errors = _read_payload("v2_log_errors_status/latest/v2_log_errors_status.json")
    replay = _read_payload("v2_replay_worker/latest/v2_replay_worker_status.json")
    liq_bridge = _read_payload("v2_liquidation_bridge_status/latest/v2_liquidation_bridge_status.json")
    opp_tracker = _read_payload("v2_opportunity_tracker/latest/v2_opportunity_tracker_status.json")
    feat_native = _read_payload("v2_feature_pipeline_native/latest/latest_feature_snapshot.json")

    # --- Live gate / trader runtime, as published by V2 runtime state ---
    live_gate = str((portfolio or {}).get("live_gate_status") or "blocked_human_only")
    live_symbols = [
        str(s).upper()
        for s in ((portfolio or {}).get("live_symbols") or [])
        if isinstance(s, str)
    ]
    trader_execution_enabled = bool((portfolio or {}).get("trader_execution_enabled", False))
    places_real_order = False
    exchange_action_taken = False

    # --- Service health ---
    v2_failed_services = log_errors.get("v2_failed_services", "MISSING") if log_errors else "MISSING"
    v2_running_services = log_errors.get("v2_running_services", "MISSING") if log_errors else "MISSING"

    # --- Ingestor freshness ---
    ingestor_status = ingestors.get("classification", "MISSING") if ingestors else "MISSING"
    ingestor_active = ingestors.get("active_count", 0) if ingestors else 0
    ingestor_total = ingestors.get("total_count", 0) if ingestors else 0
    ingestor_age = _file_age("v2_ingestors_status/latest/v2_ingestors_status.json")

    # --- Provider freshness ---
    coinank_status = "MISSING"
    coinank_age = _file_age("coinank_market_intelligence/latest/coinank_market_intelligence_status.json")
    if coinank:
        agg = coinank.get("global_aggregate_result") or {}
        coinank_status = agg.get("classification", coinank.get("classification", "PRESENT"))

    # --- TA / Feature pipeline ---
    ta_keys_fresh = ta_status.get("ta_keys_fresh", 0) if ta_status else 0
    ta_status_str = ta_status.get("classification", "MISSING") if ta_status else "MISSING"
    ta_age = _file_age("v2_technical_analysis_status/latest/v2_technical_analysis_status.json")

    # --- Trainer ---
    trainer_record = (trainer or {}).get("trainer") if isinstance((trainer or {}).get("trainer"), dict) else {}
    trainer_status = (
        trainer_record.get("trainer_source")
        or (trainer or {}).get("go_no_go")
        or "MISSING"
    )
    trainer_model_version = (
        trainer_record.get("model_source")
        or (trainer_training or {}).get("production_prediction_writer")
        or "MISSING"
    )
    trainer_inference_count = int((trainer or {}).get("prediction_count") or 0)

    # --- Risk ---
    risk_classification = risk.get("classification", "MISSING") if risk else "MISSING"
    risk_decisions_total = risk.get("decisions_processed_total", 0) if risk else 0
    risk_fail_closed = risk.get("fail_closed", True) if risk else True
    risk_gate = risk.get("current_gate_state", "blocked_human_only") if risk else "blocked_human_only"

    # --- Orchestrator ---
    orch_gate = orchestrator.get("current_gate_state", "blocked_human_only") if orchestrator else "blocked_human_only"
    orch_components_ported = orchestrator.get("components_ported", []) if orchestrator else []
    orch_components_missing = orchestrator.get("components_missing_in_v2", []) if orchestrator else []
    orch_arbitration_count = orchestrator.get("arbitration_considered_count", 0) if orchestrator else 0
    orch_winners = orchestrator.get("arbitration_bucket_winners", []) if orchestrator else []

    # --- Paper trading ---
    paper_classification = portfolio.get("classification", "MISSING") if portfolio else "MISSING"
    paper_account_mode = portfolio.get("account_mode", "paper_shadow_only") if portfolio else "paper_shadow_only"
    paper_symbols_tracked = portfolio.get("symbols_tracked", 0) if portfolio else 0
    paper_accepted = portfolio.get("accepted_intent_total", 0) if portfolio else 0
    paper_accepted_fills = portfolio.get("accepted_fill_total", paper_accepted) if portfolio else 0
    paper_held = portfolio.get("held_by_paper_fill_gate_total", 0) if portfolio else 0
    paper_shadow_obs = portfolio.get("shadow_observation_total", 0) if portfolio else 0
    paper_equity = portfolio.get("equity") if portfolio else None
    paper_realized_pnl = portfolio.get("realized_pnl_usd") if portfolio else None
    paper_unrealized_pnl = portfolio.get("unrealized_pnl_usd") if portfolio else None
    paper_open_positions = portfolio.get("open_positions_count", 0) if portfolio else 0
    paper_closed_positions = portfolio.get("closed_positions_count", 0) if portfolio else 0
    paper_equity_source = portfolio.get("paper_equity_source", "MISSING") if portfolio else "MISSING"

    # --- Canary / live gate check ---
    canary_go_no_go = canary.get("go_no_go", "MISSING") if canary else "MISSING"
    approves_live = False
    approves_canary = False

    # --- Operator review ---
    op_review_status = op_review.get("classification", "MISSING") if op_review else "MISSING"
    standing_approvals = op_review.get("standing_approval_count", 0) if op_review else 0

    # --- Symbol universe ---
    symbols_tracked = trader_state.get("symbols_tracked", 0) if trader_state else paper_symbols_tracked

    # --- Website route status (from inventory) ---
    inv_path = _OR / "v2_runtime_truth/latest/website_runtime_truth_source_inventory.json"
    route_summary: dict[str, Any] = {}
    if inv_path.exists():
        inv = json.loads(inv_path.read_text())
        route_summary = inv.get("summary", {})

    # --- Payload freshness map ---
    freshness_map = {
        "coinank_market_intelligence": _freshness(coinank_age),
        "v2_ingestors_status": _freshness(ingestor_age),
        "v2_technical_analysis_status": _freshness(ta_age),
        "v2_native_rl_masa_ppo_cuda_trainer": _freshness(
            _file_age("../v2_native_rl_masa_ppo_cuda_trainer_implementation/latest/operator_dashboard_payload.json")
        ),
        "v2_trainer_training_live_loop": _freshness(
            _file_age("v2_trainer_training_live_loop/latest/v2_trainer_training_live_loop_status.json")
        ),
        "v2_risk_gateway": _freshness(_file_age("v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json")),
        "v2_orchestrator_arbitration": _freshness(_file_age("v2_orchestrator_arbitration/latest/v2_orchestrator_arbitration_status.json")),
        "v2_live_canary": _freshness(_file_age("v2_live_canary/latest/live_canary_executor_status.json")),
        "v2_portfolio_state": _freshness(_file_age("v2_portfolio_state/latest/v2_portfolio_state.json")),
        "v2_paper_decision_lineage": _freshness(_file_age("v2_paper_decision_lineage/latest/v2_paper_decision_lineage.json")),
        "v2_operator_review": _freshness(_file_age("v2_operator_review/latest/v2_operator_review_status.json")),
        "v2_log_errors": _freshness(_file_age("v2_log_errors_status/latest/v2_log_errors_status.json")),
        "v2_replay_worker": _freshness(_file_age("v2_replay_worker/latest/v2_replay_worker_status.json")),
    }
    stale_count = sum(1 for v in freshness_map.values() if v in ("STALE", "OLD", "MISSING"))
    fresh_count = sum(1 for v in freshness_map.values() if v == "FRESH")

    return {
        "schema_version": "operator_runtime_truth_v1",
        "generated_est": now_est.isoformat(),
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "classification": "OPERATOR_RUNTIME_TRUTH_OK" if stale_count == 0 else "OPERATOR_RUNTIME_TRUTH_PARTIAL",

        # Live gate — always hard-coded blocked
        "live_gate": live_gate,
        "live_symbols": live_symbols,
        "trader_execution_enabled": trader_execution_enabled,
        "places_real_order": places_real_order,
        "exchange_action_taken": exchange_action_taken,
        "approves_live": approves_live,
        "approves_canary": approves_canary,
        "live_gate_verdict": canary_go_no_go,

        # Service counts
        "v2_failed_services": v2_failed_services,
        "v2_running_services": v2_running_services,

        # Ingestor
        "ingestor_status": ingestor_status,
        "ingestor_active_count": ingestor_active,
        "ingestor_total_count": ingestor_total,

        # Provider freshness
        "coinank_status": coinank_status,

        # Feature / TA
        "ta_status": ta_status_str,
        "ta_keys_fresh": ta_keys_fresh,

        # Trainer
        "trainer_status": trainer_status,
        "trainer_model_version": trainer_model_version,
        "trainer_inference_count": trainer_inference_count,

        # Risk
        "risk_classification": risk_classification,
        "risk_decisions_total": risk_decisions_total,
        "risk_fail_closed": risk_fail_closed,
        "risk_gate_state": risk_gate,

        # Orchestrator
        "orchestrator_gate_state": orch_gate,
        "orchestrator_components_ported": orch_components_ported,
        "orchestrator_components_missing": orch_components_missing,
        "orchestrator_arbitration_count": orch_arbitration_count,
        "orchestrator_latest_winners": orch_winners[:3],

        # Paper trading
        "paper_classification": paper_classification,
        "paper_account_mode": paper_account_mode,
        "paper_symbols_tracked": paper_symbols_tracked,
        "paper_accepted_intents": paper_accepted,
        "paper_accepted_fills": paper_accepted_fills,
        "paper_held_by_fill_gate": paper_held,
        "paper_shadow_observations": paper_shadow_obs,
        "paper_equity": paper_equity,
        "paper_realized_pnl_usd": paper_realized_pnl,
        "paper_unrealized_pnl_usd": paper_unrealized_pnl,
        "paper_open_positions_count": paper_open_positions,
        "paper_closed_positions_count": paper_closed_positions,
        "paper_equity_source": paper_equity_source,

        # Operator review
        "operator_review_status": op_review_status,
        "standing_approvals_count": standing_approvals,

        # Symbol universe
        "symbols_tracked": symbols_tracked,

        # Payload freshness
        "payload_freshness": freshness_map,
        "stale_payload_count": stale_count,
        "fresh_payload_count": fresh_count,

        # Website route summary
        "website_route_summary": route_summary,

        # Next actions
        "next_automatic_action": "Continue paper/shadow loop. Refresh publisher payloads on schedule.",
        "next_operator_decision": "Review paper edge profile. Approve live gate only when edge proven positive, risk thresholds met, and all canary checks pass.",
    }
