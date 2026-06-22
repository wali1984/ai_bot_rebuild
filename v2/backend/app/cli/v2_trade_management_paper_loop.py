"""V2 paper trade management live loop (paper-only).

Consumes v2:signals:paper, applies fee-ratio gate, churn veto,
hedge fail-closed engine, and produces:
- v2:paper:intents
- v2:paper:positions  (paper-only ledger, no exchange touch)
- v2:paper:ledger
- v2:risk:decisions

Never places, cancels, or modifies real orders. Never writes legacy
Redis. Never imports an exchange SDK.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from v2.backend.app.services.live_gate.runtime_execution_state import (
    LIVE_GATE_BLOCKED,
    LIVE_GATE_ENABLED,
    read_runtime_execution_state,
)
from v2.backend.app.services.native_trainer.feedback_enrichment import (
    AUDIT_QUALITY_FEEDBACK_FIELDS,
    REQUIRED_FEEDBACK_FIELDS,
    audit_quality_rejection_reasons,
    build_strategy_hedge_exit_feedback,
    feedback_status,
)
from v2.backend.app.services.strategy_router import (
    route_strategy,
    summarize_strategy_router_performance,
)
from v2.backend.app.services.paper_trade_management.entry_gate import (
    expected_move_after_cost_favorable_for_side,
)
from v2.backend.app.services.paper_trade_management.exits import PAPER_EXIT_POLICY_VERSION
from v2.backend.app.services.paper_trade_management.position_state import atr_bps_from_payloads

V2_REDIS_PREFIX = "v2:"
PAPER_SIZING_SOURCE_ADAPTIVE = "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR"
TRIAL_STATUS_REDIS_KEY = f"{V2_REDIS_PREFIX}paper:confidence_threshold_trial:status"
TRIAL_DRAWDOWN_GUARD_REDIS_KEY = f"{V2_REDIS_PREFIX}paper:confidence_threshold_trial:drawdown_guard"
DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json"
)
PAPER_LOOP_LOCK_PATH = Path("logs/v2_trade_management_paper_loop.lock")
CHECKPOINT_DIR = Path(".local_models/v2_native_rl_masa_ppo")
TRADE_MANAGEMENT_PUBLIC_DIR = Path(
    "v2/frontend/public/operator_runtime/v2_paper_trade_management/latest"
)
PREDICTION_STALE_SECONDS = 900
PAPER_SIGNAL_STALE_SECONDS = PREDICTION_STALE_SECONDS
CURRENT_PREDICTION_STATUSES = {
    "PRESENT_CURRENT",
    "PRESENT_CURRENT_RL_CORE_SIDECAR_NOT_CUDA_PARITY",
    "CURRENT_RUNTIME_PAPER_SIGNAL",
}
DIRECTIONAL_COLLAPSE_GUARD_NAME = "PAPER_ONLY_DIRECTIONAL_COLLAPSE_GUARD"
DIRECTIONAL_COLLAPSE_BLOCK_REASON = "DIRECTIONAL_COLLAPSE_RUNTIME_GUARD_BLOCKED"
DIRECTIONAL_COLLAPSE_MIN_CLOSED_TRADES = 50
DIRECTIONAL_COLLAPSE_MIN_SIDE_TRADES = 50
DIRECTIONAL_COLLAPSE_MAJOR_SIDE_SHARE = 0.90
STRATEGY_MODE_COLLAPSE_GUARD_NAME = "PAPER_ONLY_STRATEGY_MODE_COLLAPSE_GUARD"
STRATEGY_MODE_COLLAPSE_BLOCK_REASON = "STRATEGY_MODE_COLLAPSE_RUNTIME_GUARD_BLOCKED"
STRATEGY_MODE_COLLAPSE_MIN_CLOSED_TRADES = 50
STRATEGY_MODE_COLLAPSE_MAJOR_MODE_SHARE = 0.80
PAPER_DRAWDOWN_RECOVERY_GUARD_NAME = "PAPER_ONLY_DRAWDOWN_RECOVERY_ADMISSION_GUARD"
PAPER_DRAWDOWN_RECOVERY_REASON = "PAPER_DRAWDOWN_RECOVERY_MINORITY_SIDE_REDUCE_SIZE"
PAPER_DRAWDOWN_RECOVERY_MIN_CONFIDENCE = 0.65
PAPER_DRAWDOWN_RECOVERY_SIZE_MULTIPLIER = 0.25
PAPER_RUNTIME_EVIDENCE_BLOCK_REASON = "PAPER_RUNTIME_EVIDENCE_BLOCKED"
PAPER_RUNTIME_TRANSIENT_TTL_SECONDS = 10 * 60
PAPER_TRAINING_EVIDENCE_TTL_SECONDS = 30 * 24 * 60 * 60
PAPER_AUDIT_ENTRY_GATE_NAME = "PAPER_ONLY_2026_06_19_AUDIT_ENTRY_GATE"
PAPER_AUDIT_BLOCKED_ENTRY_TIMEFRAMES = frozenset({"5m", "4h"})
PAPER_AUDIT_ALLOWED_ENTRY_TIMEFRAMES = frozenset({"1m", "15m", "1h"})
PAPER_AUDIT_SYMBOL_EXCLUSION_LIST = frozenset({
    "NIGHTUSDT",
    "TIAUSDT",
    "TRUMPUSDT",
    "PUMPUSDT",
    "PORTALUSDT",
})
CORRELATION_CANDLE_TIMEFRAME = "1m"
CORRELATION_MIN_RETURN_POINTS = 30
CORRELATION_MAX_CANDLE_AGE_SECONDS = 6 * 60 * 60
CORRELATION_FAIL_CLOSED_EXPOSURE_PCT = 1.0
ADAPTIVE_ALLOCATION_ATTRIBUTION_BLOCK_REASON = "ADAPTIVE_ALLOCATION_ATTRIBUTION_INCOMPLETE"
ADAPTIVE_PAPER_REQUIRED_ALLOCATION_FIELDS = (
    "adaptive_capital_policy_version",
    "risk_budget_usd",
    "gross_notional_usd",
    "allocated_margin_usd",
    "recommended_leverage",
    "effective_leverage",
    "recommended_margin_mode",
    "stop_distance_bps",
    "liquidation_price_estimate",
    "liquidation_buffer_bps",
    "expected_fees_usd",
    "expected_slippage_usd",
    "expected_funding_usd",
    "expected_net_pnl_usd",
    "expected_shortfall_usd",
    "hedge_budget_usd",
    "capital_allocation_reason",
)
COUNTERFACTUAL_MARKET_COST_REQUIREMENTS = (
    ("actual_observed_spread_entry_bps", "MISSING_ACTUAL_SPREAD"),
    ("expected_slippage_bps", "MISSING_SLIPPAGE"),
    ("fee_bps", "MISSING_FEES"),
    ("expected_funding_bps", "MISSING_FUNDING"),
    ("orderbook_depth_usd", "MISSING_MARKET_DEPTH"),
)
PAPER_TIER_A_GRADE_EXECUTION = "A_GRADE_EXECUTION_PAPER"
PAPER_TIER_B_GRADE_EXPLORATION = "B_GRADE_EXPLORATION_PAPER"
PAPER_TIER_SHADOW_ONLY = "SHADOW_ONLY"
PAPER_TIER_NO_TRADE = "NO_TRADE"
OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT = (
    "c4b8fb1ed12aabcb87224723f1758563eefff10de90288be09866d2bf3fa74b5"
)
PAPER_OPPORTUNITY_TIERS = (
    PAPER_TIER_A_GRADE_EXECUTION,
    PAPER_TIER_B_GRADE_EXPLORATION,
    PAPER_TIER_SHADOW_ONLY,
    PAPER_TIER_NO_TRADE,
)
PAPER_STRICT_A_CONFIDENCE_THRESHOLD = 0.75
B_GRADE_EXPLORATION_MIN_CONFIDENCE = 0.50
B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL = 0.25
B_GRADE_EXPLORATION_DRAWDOWN_STOP_BPS = 500.0
B_GRADE_EXPLORATION_SCALABLE_ALLOCATION_FIELDS = (
    "target_notional_usdt",
    "target_quantity",
    "risk_budget_usd",
    "gross_notional_usd",
    "allocated_margin_usd",
    "expected_fees_usd",
    "expected_slippage_usd",
    "expected_funding_usd",
    "expected_net_pnl_usd",
    "expected_shortfall_usd",
    "hedge_budget_usd",
    "risk_budget_pct",
    "risk_budget_pct_of_equity",
    "risk_budget_pct_of_available_margin",
)


def _runtime_default_symbol() -> str:
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    return resolve_symbols()[0]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _build_trainer_feedback_rows(
    *,
    close_events: list[dict[str, Any]],
    outcome_labels: list[dict[str, Any]],
    entry_context_rows: list[dict[str, Any]] | None = None,
    predictions_by_id: dict[str, dict[str, Any]] | None = None,
    feature_snapshots_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    outcomes_by_feedback_id = {
        row.get("trainer_feedback_id"): row
        for row in outcome_labels
        if isinstance(row, dict) and row.get("trainer_feedback_id")
    }
    entry_context_by_fill_id = _entry_feedback_context_by_fill_id(entry_context_rows or [])
    predictions_by_id = predictions_by_id or {}
    require_feature_snapshot_deref = feature_snapshots_by_id is not None
    feature_snapshots_by_id = feature_snapshots_by_id or {}
    rows: list[dict[str, Any]] = []
    for close_event in close_events:
        if not isinstance(close_event, dict):
            continue
        feedback_id = close_event.get("trainer_feedback_id")
        outcome = outcomes_by_feedback_id.get(feedback_id)
        if not isinstance(outcome, dict):
            continue
        source_context = _source_entry_context_for_close(
            close_event=close_event,
            entry_context_by_fill_id=entry_context_by_fill_id,
        )
        if source_context:
            close_event = _with_feedback_context_fallback(close_event, source_context)
            outcome = _with_feedback_context_fallback(outcome, source_context)
        entry_prediction_id = str(
            _first_present(
                close_event.get("entry_prediction_id"),
                outcome.get("entry_prediction_id"),
                close_event.get("prediction_id"),
                outcome.get("prediction_id"),
                "",
            )
        )
        entry_feature_snapshot_id = _first_present(
            close_event.get("entry_feature_snapshot_id"),
            outcome.get("entry_feature_snapshot_id"),
            close_event.get("feature_snapshot_id"),
            outcome.get("feature_snapshot_id"),
        )
        prediction = predictions_by_id.get(entry_prediction_id, {}) if entry_prediction_id else {}
        feature_snapshot = (
            feature_snapshots_by_id.get(str(entry_feature_snapshot_id))
            if entry_feature_snapshot_id
            else None
        )
        close_event = _reconstruct_trust_from_prediction(
            row=close_event,
            prediction=prediction,
            feature_snapshot=feature_snapshot,
            require_feature_snapshot_deref=require_feature_snapshot_deref,
            prediction_id=entry_prediction_id,
            feature_snapshot_id=entry_feature_snapshot_id,
        )
        outcome = _reconstruct_trust_from_prediction(
            row=outcome,
            prediction=prediction,
            feature_snapshot=feature_snapshot,
            require_feature_snapshot_deref=require_feature_snapshot_deref,
            prediction_id=entry_prediction_id,
            feature_snapshot_id=entry_feature_snapshot_id,
        )
        rows.append(
            build_strategy_hedge_exit_feedback(
                close_event=close_event,
                outcome_label=outcome,
            )
        )
    return rows


_FEEDBACK_ENTRY_CONTEXT_FIELDS: tuple[str, ...] = (
    "prediction_id",
    "source_prediction_id",
    "entry_prediction_id",
    "signal_id",
    "source_signal_id",
    "entry_signal_id",
    "feature_snapshot_id",
    "entry_feature_snapshot_id",
    "entry_feature_snapshot",
    "decision_id",
    "mtf_snapshot_id",
    "feature_cutoff",
    "decision_time",
    "available_at",
    "selected_action",
    "model_version",
    "checkpoint_id",
    "source_hashes",
    "confidence_raw",
    "confidence_calibrated",
    "selected_action_probability",
    "expected_move_bps",
    "expected_move_after_cost_bps",
    "action_probabilities",
    "policy_value",
    "value_baseline",
    "prediction_score_source",
    "prediction_score_missing_reason",
    "feature_vector_hash",
    "input_feature_hash",
    "prediction_hash",
    "source_lineage_hash",
    "market_state_id",
    "entry_market_state_id",
    "timeframe",
    "side",
    "action",
    "entry_price",
    "exit_price",
    "realized_pnl",
    "realized_pnl_usd",
    "realized_pnl_usdt",
    "strategy_id",
    "strategy_family",
    "strategy_subtype",
    "strategy_selected_mode",
    "entry_reason",
    "hedge_state",
    "hedge_reason",
    "drawdown_at_entry",
    "drawdown_bps",
    "market_regime_at_entry",
    "market_regime_at_exit",
    "liquidity_zone_context",
    "liquidity_context",
    "liquidation_distance_context",
    "liquidation_context",
    "microstructure_context",
    "oi_funding_context",
    "public_intel_context",
    "major_move_signal_id",
    "squeeze_evidence_score",
    "future_window_label_source",
    "paper_fill_persistence_status",
    "paper_opportunity_tier",
    "paper_opportunity_tier_reason",
    "paper_fill_allowed_source",
    "strict_paper_fill_allowed_upstream",
    "b_grade_exploration_budget_cap_applied",
    "risk_budget_fraction_of_normal_adaptive",
    "normal_adaptive_risk_budget_usd",
    "normal_adaptive_gross_notional_usd",
    "calibration_label_purpose",
    "original_fill_utc",
    "fill_price_utc",
    "lineage_backfilled_from_prediction_id",
    *AUDIT_QUALITY_FEEDBACK_FIELDS,
)


def _entry_feedback_context_by_fill_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        fill_ids = [
            row.get("fill_id"),
            row.get("ledger_row_id"),
            row.get("intent_id"),
            row.get("signal_id"),
            row.get("prediction_id"),
            row.get("source_prediction_id"),
        ]
        context = {field: row.get(field) for field in _FEEDBACK_ENTRY_CONTEXT_FIELDS if row.get(field) not in (None, "")}
        if not context:
            continue
        for fill_id in fill_ids:
            if fill_id:
                indexed.setdefault(str(fill_id), context)
    return indexed


def _source_entry_context_for_close(
    *,
    close_event: dict[str, Any],
    entry_context_by_fill_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_fill_ids = close_event.get("source_fill_ids")
    if not isinstance(source_fill_ids, list):
        source_fill_ids = []
    candidates = [
        *source_fill_ids,
        close_event.get("entry_signal_id"),
        close_event.get("entry_prediction_id"),
    ]
    for candidate in candidates:
        if candidate and str(candidate) in entry_context_by_fill_id:
            return entry_context_by_fill_id[str(candidate)]
    return {}


def _with_feedback_context_fallback(row: dict[str, Any], source_context: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    for field in _FEEDBACK_ENTRY_CONTEXT_FIELDS:
        if enriched.get(field) in (None, "") and source_context.get(field) not in (None, ""):
            enriched[field] = source_context[field]
    if enriched.get("market_regime_at_exit") in (None, "") and enriched.get("market_regime_at_entry") not in (None, ""):
        enriched["market_regime_at_exit"] = enriched["market_regime_at_entry"]
    if enriched.get("drawdown_at_entry") in (None, "") and enriched.get("drawdown_bps") not in (None, ""):
        enriched["drawdown_at_entry"] = enriched["drawdown_bps"]
    if enriched.get("entry_prediction_id") in (None, "") and enriched.get("prediction_id") not in (None, ""):
        enriched["entry_prediction_id"] = enriched["prediction_id"]
    if enriched.get("entry_feature_snapshot_id") in (None, "") and enriched.get("feature_snapshot_id") not in (None, ""):
        enriched["entry_feature_snapshot_id"] = enriched["feature_snapshot_id"]
    if enriched.get("entry_market_state_id") in (None, "") and enriched.get("market_state_id") not in (None, ""):
        enriched["entry_market_state_id"] = enriched["market_state_id"]
    if enriched.get("entry_signal_id") in (None, "") and enriched.get("signal_id") not in (None, ""):
        enriched["entry_signal_id"] = enriched["signal_id"]
    return enriched


def _source_hashes_from_row(row: dict[str, Any]) -> dict[str, Any]:
    source_hashes = row.get("source_hashes") if isinstance(row.get("source_hashes"), dict) else {}
    out = dict(source_hashes)
    for key, value in {
        "feature_vector_hash": _first_present(row.get("feature_vector_hash"), row.get("input_feature_hash")),
        "prediction_hash": row.get("prediction_hash"),
        "source_lineage_hash": row.get("source_lineage_hash"),
        "missing_mask_hash": row.get("missing_mask_hash"),
        "stale_mask_hash": row.get("stale_mask_hash"),
    }.items():
        if value not in (None, ""):
            out.setdefault(key, value)
    return out


def _trust_lineage_source(signal: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    merged = dict(prediction or {})
    for key, value in (signal or {}).items():
        if value not in (None, ""):
            merged[key] = value
    return merged


def _trust_envelope_from_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": _first_present(prediction.get("decision_id"), prediction.get("orchestrator_decision_id")),
        "feature_snapshot_id": prediction.get("feature_snapshot_id"),
        "mtf_snapshot_id": prediction.get("mtf_snapshot_id"),
        "feature_cutoff": _first_present(
            prediction.get("feature_cutoff"),
            prediction.get("ppo_feature_cutoff"),
            prediction.get("masa_feature_cutoff"),
        ),
        "decision_time": _first_present(prediction.get("decision_time"), prediction.get("generated_at")),
        "available_at": _first_present(prediction.get("available_at"), prediction.get("generated_at"), prediction.get("decision_time")),
        "selected_action": _first_present(
            prediction.get("selected_action"),
            prediction.get("action"),
            prediction.get("side"),
            prediction.get("ppo_action"),
        ),
        "model_version": _first_present(prediction.get("model_version"), prediction.get("model_source"), prediction.get("model_id")),
        "checkpoint_id": prediction.get("checkpoint_id"),
        "source_hashes": _source_hashes_from_row(prediction),
        "confidence_raw": prediction.get("confidence_raw"),
        "confidence_calibrated": _first_present(
            prediction.get("confidence_calibrated"),
            prediction.get("confidence"),
        ),
        "selected_action_probability": _first_present(
            prediction.get("selected_action_probability"),
            prediction.get("action_probability"),
            prediction.get("probability_selected_action"),
        ),
        "expected_move_bps": _first_present(
            prediction.get("expected_move_bps"),
            prediction.get("price_target_bps"),
        ),
        "expected_move_after_cost_bps": _first_present(
            prediction.get("expected_move_after_cost_bps"),
            prediction.get("expected_net_edge_bps"),
        ),
        "action_probabilities": _first_present(
            prediction.get("action_probabilities"),
            prediction.get("policy_action_probabilities"),
        ),
        "policy_value": _first_present(
            prediction.get("policy_value"),
            prediction.get("value_estimate"),
        ),
        "value_baseline": prediction.get("value_baseline"),
        "prediction_score_source": (
            "VERIFIED_ENTRY_PREDICTION"
            if _first_present(
                prediction.get("confidence_calibrated"),
                prediction.get("confidence"),
            ) not in (None, "")
            and _first_present(
                prediction.get("expected_move_after_cost_bps"),
                prediction.get("expected_net_edge_bps"),
            ) not in (None, "")
            else None
        ),
        "feature_vector_hash": _first_present(prediction.get("feature_vector_hash"), prediction.get("input_feature_hash")),
        "input_feature_hash": prediction.get("input_feature_hash"),
    }


def _lineage_reconstruction_rejection_reasons(
    *,
    row: dict[str, Any],
    prediction: dict[str, Any],
    feature_snapshot: dict[str, Any] | None = None,
    require_feature_snapshot_deref: bool = False,
) -> list[str]:
    reasons: list[str] = []
    if not prediction:
        return ["ENTRY_PREDICTION_NOT_FOUND"]
    row_symbol = str(row.get("symbol") or "").upper()
    prediction_symbol = str(prediction.get("symbol") or "").upper()
    if row_symbol and prediction_symbol and row_symbol != prediction_symbol:
        reasons.append("SYMBOL_MISMATCH")
    row_timeframe = str(row.get("timeframe") or "")
    prediction_timeframe = str(prediction.get("timeframe") or "")
    if row_timeframe and prediction_timeframe and row_timeframe != prediction_timeframe:
        reasons.append("TIMEFRAME_MISMATCH")
    row_action = str(_first_present(row.get("selected_action"), row.get("action"), row.get("side")) or "").lower()
    envelope = _trust_envelope_from_prediction(prediction)
    prediction_action = str(envelope.get("selected_action") or "").lower()
    if row_action and prediction_action and row_action != prediction_action:
        reasons.append("ACTION_MISMATCH")
    row_feature = _first_present(row.get("entry_feature_snapshot_id"), row.get("feature_snapshot_id"))
    prediction_feature = envelope.get("feature_snapshot_id")
    if row_feature and prediction_feature and str(row_feature) != str(prediction_feature):
        reasons.append("FEATURE_SNAPSHOT_MISMATCH")
    if require_feature_snapshot_deref:
        if not isinstance(feature_snapshot, dict) or not feature_snapshot:
            reasons.append("ENTRY_FEATURE_SNAPSHOT_NOT_FOUND")
        else:
            snapshot_id = feature_snapshot.get("feature_snapshot_id")
            if row_feature and snapshot_id and str(row_feature) != str(snapshot_id):
                reasons.append("ENTRY_FEATURE_SNAPSHOT_ID_MISMATCH")
            snapshot_symbol = str(feature_snapshot.get("symbol") or "").upper()
            if row_symbol and snapshot_symbol and row_symbol != snapshot_symbol:
                reasons.append("ENTRY_FEATURE_SNAPSHOT_SYMBOL_MISMATCH")
            snapshot_timeframe = str(feature_snapshot.get("timeframe") or "")
            if row_timeframe and snapshot_timeframe and row_timeframe != snapshot_timeframe:
                reasons.append("ENTRY_FEATURE_SNAPSHOT_TIMEFRAME_MISMATCH")
            snapshot_available_at = _parse_strategy_time(
                _first_present(
                    feature_snapshot.get("available_at"),
                    feature_snapshot.get("generated_utc"),
                    feature_snapshot.get("generated_at"),
                )
            )
            snapshot_feature_cutoff = _parse_strategy_time(
                _first_present(
                    feature_snapshot.get("feature_cutoff"),
                    feature_snapshot.get("source_available_time"),
                )
            )
            decision_time_for_snapshot = _parse_strategy_time(envelope.get("decision_time"))
            if snapshot_available_at is not None and decision_time_for_snapshot is not None and snapshot_available_at > decision_time_for_snapshot:
                reasons.append("ENTRY_FEATURE_SNAPSHOT_AVAILABLE_AT_AFTER_DECISION_TIME")
            if snapshot_feature_cutoff is not None and decision_time_for_snapshot is not None and snapshot_feature_cutoff > decision_time_for_snapshot:
                reasons.append("ENTRY_FEATURE_SNAPSHOT_FEATURE_CUTOFF_AFTER_DECISION_TIME")
    missing = [
        field
        for field in (
            "decision_id",
            "feature_snapshot_id",
            "mtf_snapshot_id",
            "feature_cutoff",
            "decision_time",
            "available_at",
            "selected_action",
            "model_version",
            "checkpoint_id",
            "source_hashes",
        )
        if envelope.get(field) in (None, "") or (field == "source_hashes" and not envelope.get(field))
    ]
    reasons.extend(f"PREDICTION_TRUST_{field.upper()}_MISSING" for field in missing)
    decision_time = _parse_strategy_time(envelope.get("decision_time"))
    available_at = _parse_strategy_time(envelope.get("available_at"))
    feature_cutoff = _parse_strategy_time(envelope.get("feature_cutoff"))
    if decision_time is None:
        reasons.append("DECISION_TIME_UNPARSEABLE")
    if available_at is None:
        reasons.append("AVAILABLE_AT_UNPARSEABLE")
    elif decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if feature_cutoff is None:
        reasons.append("FEATURE_CUTOFF_UNPARSEABLE")
    elif decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    return sorted(set(reasons))


def _reconstruct_trust_from_prediction(
    *,
    row: dict[str, Any],
    prediction: dict[str, Any],
    feature_snapshot: dict[str, Any] | None,
    require_feature_snapshot_deref: bool,
    prediction_id: str,
    feature_snapshot_id: str | None,
) -> dict[str, Any]:
    enriched = dict(row)
    reasons = _lineage_reconstruction_rejection_reasons(
        row=row,
        prediction=prediction,
        feature_snapshot=feature_snapshot,
        require_feature_snapshot_deref=require_feature_snapshot_deref,
    )
    if reasons:
        enriched["trust_reconstructed"] = False
        enriched["trust_reconstruction_rejection_reasons"] = reasons
        return enriched
    envelope = _trust_envelope_from_prediction(prediction)
    for key, value in envelope.items():
        if value not in (None, "") and (key != "source_hashes" or value):
            enriched[key] = value
    missing_score_fields = [
        field
        for field in ("confidence_calibrated", "expected_move_after_cost_bps")
        if enriched.get(field) in (None, "")
    ]
    if missing_score_fields and enriched.get("prediction_score_missing_reason") in (None, ""):
        enriched["prediction_score_missing_reason"] = (
            "VERIFIED_ENTRY_PREDICTION_MISSING_SCORE_FIELDS:"
            + ",".join(missing_score_fields)
        )
    enriched["trust_reconstructed"] = True
    enriched["trust_source_ids"] = {
        "entry_prediction_id": prediction_id,
        "entry_feature_snapshot_id": feature_snapshot_id,
        "prediction_feature_snapshot_id": prediction.get("feature_snapshot_id"),
        "replay_snapshot_id": prediction.get("replay_snapshot_id"),
        "checkpoint_id": prediction.get("checkpoint_id"),
    }
    enriched["trust_reconstruction_rejection_reasons"] = []
    return enriched


def _live_context(r) -> dict:
    runtime = read_runtime_execution_state(redis_client=r)
    payload = runtime.get("payload") if isinstance(runtime.get("payload"), dict) else {}
    validation = runtime.get("validation") if isinstance(runtime.get("validation"), dict) else {}
    return {
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "runtime_validation": validation,
        "runtime_source": runtime.get("source"),
    }


def _safe_write(r, key: str, value: str, ex: int | None = None) -> bool:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        if ex is not None:
            r.set(key, value, ex=int(ex))
        else:
            r.set(key, value)
        return True
    except Exception:
        return False


def _read_json_key(r, key: str) -> dict:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return {}
    try:
        raw = r.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _paper_confidence_trial_guard(r) -> dict:
    guard = _read_json_key(r, TRIAL_DRAWDOWN_GUARD_REDIS_KEY)
    status = _read_json_key(r, TRIAL_STATUS_REDIS_KEY)
    guard_status = str(guard.get("status") or status.get("status") or "")
    paused = (
        guard_status in {
            "TRIAL_PAUSED_DRAWDOWN_GUARD",
            "TRIAL_BLOCKED_INSUFFICIENT_OUTCOME_SAMPLE",
        }
        or guard.get("stop_promoting_new_threshold_trial_signals") is True
        or (
            status.get("trial_enabled") is False
            and str(status.get("drawdown_guard_reason") or "").strip() != ""
        )
    )
    return {
        "paused": bool(paused),
        "status": guard_status or "TRIAL_GUARD_NOT_SET",
        "drawdown_guard_reason": guard.get("drawdown_guard_reason") or status.get("drawdown_guard_reason"),
    }


def _is_paper_confidence_trial_row(row: dict) -> bool:
    return (
        row.get("paper_confidence_threshold_trial") is True
        or row.get("paper_confidence_trial_promoted") is True
        or str(row.get("signal_id") or "").startswith("sig_paper_conf_trial_")
        or str(row.get("paper_confidence_trial_id") or "").startswith("paper_conf_trial_")
    )


def _read_paper_signals(r) -> list[dict]:
    if r is None:
        return []
    rows: list[dict] = []
    trial_guard = _paper_confidence_trial_guard(r)
    trial_paused = bool(trial_guard["paused"])
    now = datetime.now(timezone.utc)

    def _paper_signal_stale_reason(row: dict[str, Any]) -> str | None:
        generated_raw = _first_present(
            row.get("generated_utc"),
            row.get("generated_at"),
            row.get("available_at"),
            row.get("generated_est"),
        )
        generated = _parse_strategy_time(generated_raw)
        if generated is not None and (now - generated).total_seconds() > PAPER_SIGNAL_STALE_SECONDS:
            return f"STALE_SIGNAL_GT_{PAPER_SIGNAL_STALE_SECONDS}s_EXCLUDED_FROM_PAPER_ADMISSION"
        return None

    def _is_enriched_paper_signal(row: dict) -> bool:
        """Return true for current paper-orchestrator signals.

        Older per-symbol paper signal keys can contain display-only rows that
        have prediction IDs but no paper gate, market-state integrity, risk, or
        orchestrator lineage. Feeding those rows into the paper loop creates a
        wall of blocked "missing market_state_id" ledger rows and hides the
        valid aggregate ``v2:signals:paper`` candidates. Strict paper execution
        still requires ``_paper_signal_integrity_gate`` later in this loop.
        Per-symbol keys also carry their own generated/available time, so stale
        rows are excluded before they can be counted as current paper candidates.
        """
        if _paper_signal_stale_reason(row):
            return False
        if row.get("paper_fill_allowed") is True:
            return bool(row.get("market_state_id") and row.get("valid_for_paper") is True)
        if row.get("paper_fill_allowed") is False:
            return bool(row.get("paper_fill_gate_block_reasons") or row.get("market_state_reject_reasons"))
        return False

    def append_payload(raw: str | None, *, require_enriched: bool = False) -> None:
        if not raw:
            return
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        if isinstance(data, list):
            rows.extend([
                s
                for s in data
                if isinstance(s, dict)
                and (not trial_paused or not _is_paper_confidence_trial_row(s))
                and (not require_enriched or _is_enriched_paper_signal(s))
            ])
        elif isinstance(data, dict):
            if (
                (not trial_paused or not _is_paper_confidence_trial_row(data))
                and (not require_enriched or _is_enriched_paper_signal(data))
            ):
                rows.append(data)

    try:
        append_payload(r.get(f"{V2_REDIS_PREFIX}signals:paper"))
    except Exception:
        pass
    try:
        for key in r.scan_iter(match=f"{V2_REDIS_PREFIX}signals:paper:*", count=500):
            append_payload(r.get(str(key)), require_enriched=True)
    except Exception:
        pass

    def _dedupe_key(row: dict[str, Any]) -> str:
        prediction_id = _first_present(row.get("prediction_id"), row.get("source_prediction_id"))
        if prediction_id:
            return f"prediction:{prediction_id}"
        signal_id = _first_present(row.get("signal_id"), row.get("paper_intent_id"))
        if signal_id:
            return f"signal:{signal_id}"
        return (
            f"symbol:{row.get('symbol')}:{row.get('timeframe')}:"
            f"{row.get('side') or row.get('action') or row.get('selected_action')}:"
            f"{row.get('generated_utc') or row.get('generated_est') or row.get('available_at')}"
        )

    def _dedupe_score(row: dict[str, Any]) -> tuple[int, int, str]:
        lineage_score = sum(
            1
            for key in (
                "winner_proposal_id",
                "signal_id",
                "prediction_id",
                "risk_decision_id",
                "orchestrator_decision_id",
                "market_state_id",
                "feature_snapshot_id",
            )
            if row.get(key) not in (None, "")
        )
        gate_score = int(row.get("paper_fill_allowed") is True) + int(row.get("valid_for_paper") is True)
        generated = str(row.get("generated_utc") or row.get("generated_est") or row.get("available_at") or "")
        return (lineage_score, gate_score, generated)

    by_identity: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = _dedupe_key(row)
        existing = by_identity.get(identity)
        if existing is None or _dedupe_score(row) > _dedupe_score(existing):
            by_identity[identity] = row
    return list(by_identity.values())


# Price provenance markers. Source strings are quoted verbatim into the
# v2:paper:positions and v2:paper:ledger payloads so the
# position_price_tracking_recorder and operator dashboards can audit
# which V2-owned input the fill price came from. NEVER fabricate a
# price; NEVER use legacy Redis as current truth; NEVER substitute a
# static sample value.
ENTRY_PRICE_SOURCE_V2_MARKET = "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE"
ENTRY_PRICE_SOURCE_V2_FEATURES = "V2_FEATURES_LATEST_FRESH_CLOSE_PRICE"
ENTRY_PRICE_BLOCKER_MISSING_FILL = "MISSING_V2_MARKET_PRICE_FOR_FILL"
EXIT_PRICE_BLOCKER_MISSING_EXIT = "MISSING_V2_MARKET_PRICE_FOR_EXIT"
REALIZED_EXIT_NOT_RECORDED = "REALIZED_EXIT_NOT_RECORDED_IN_V2_INPUTS"
ENTRY_SPREAD_SOURCE_V2_ORDERBOOK = "V2_MARKET_ORDERBOOK_TOP_OF_BOOK"


def _coerce_float(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(value, str):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        return v if v == v else None
    return None


def _iso_from_epoch_ms(value: Any) -> str | None:
    parsed = _coerce_float(value)
    if parsed is None or parsed <= 0:
        return None
    if parsed < 10_000_000_000:
        parsed *= 1000.0
    try:
        parsed_dt = datetime.fromtimestamp(parsed / 1000.0, tz=timezone.utc)
        return parsed_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _best_level_price(levels: Any) -> float | None:
    if not isinstance(levels, list) or not levels:
        return None
    first = levels[0]
    if isinstance(first, (list, tuple)) and first:
        return _coerce_float(first[0])
    if isinstance(first, dict):
        return _coerce_float(first.get("price") or first.get("p"))
    return _coerce_float(first)


def _top_depth_quantity(levels: Any, *, depth: int = 5) -> float | None:
    if not isinstance(levels, list) or not levels:
        return None
    total = 0.0
    seen = 0
    for row in levels[:depth]:
        qty = None
        if isinstance(row, (list, tuple)) and len(row) > 1:
            qty = _coerce_float(row[1])
        elif isinstance(row, dict):
            qty = _coerce_float(row.get("quantity") or row.get("qty") or row.get("q"))
        if qty is None:
            continue
        total += max(0.0, qty)
        seen += 1
    return total if seen else None


def _top_depth_notional_usd(levels: Any, *, depth: int = 5) -> float | None:
    if not isinstance(levels, list) or not levels:
        return None
    total = 0.0
    seen = 0
    for row in levels[:depth]:
        price = None
        qty = None
        if isinstance(row, (list, tuple)) and len(row) > 1:
            price = _coerce_float(row[0])
            qty = _coerce_float(row[1])
        elif isinstance(row, dict):
            price = _coerce_float(row.get("price") or row.get("p"))
            qty = _coerce_float(row.get("quantity") or row.get("qty") or row.get("q"))
        if price is None or qty is None or price <= 0 or qty <= 0:
            continue
        total += price * qty
        seen += 1
    return total if seen else None


def _read_v2_orderbook_microstructure(r, symbol: str) -> dict[str, Any]:
    """Read V2-owned top-of-book spread evidence for paper entry telemetry.

    The returned timestamp is the market-data ``entry_spread_available_at``.
    The paper fill/allocation decision remains the current loop execution time.
    """
    if r is None or not symbol:
        return {}
    normalized = str(symbol).upper()
    for key in (
        f"{V2_REDIS_PREFIX}market:orderbook:{normalized}",
        f"{V2_REDIS_PREFIX}market:orderbook:binance:{normalized}",
    ):
        try:
            raw = r.get(key)
        except Exception:
            raw = None
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        spread_bps = _coerce_float(payload.get("spread_bps") or payload.get("bid_ask_spread_bps"))
        bid = _coerce_float(payload.get("best_bid") or payload.get("bid") or payload.get("bidPrice"))
        ask = _coerce_float(payload.get("best_ask") or payload.get("ask") or payload.get("askPrice"))
        if bid is None:
            bid = _best_level_price(payload.get("bids") or payload.get("b"))
        if ask is None:
            ask = _best_level_price(payload.get("asks") or payload.get("a"))
        mid = _coerce_float(payload.get("mid") or payload.get("mid_price") or payload.get("midPrice"))
        if mid is None and bid is not None and ask is not None:
            mid = (bid + ask) / 2.0
        if spread_bps is None and bid is not None and ask is not None and mid and mid > 0:
            spread_bps = abs(ask - bid) / mid * 10_000.0
        if spread_bps is None:
            continue
        bids = payload.get("bids") or payload.get("b")
        asks = payload.get("asks") or payload.get("a")
        bid_qty = _top_depth_quantity(bids)
        ask_qty = _top_depth_quantity(asks)
        bid_depth_usd = _top_depth_notional_usd(bids)
        ask_depth_usd = _top_depth_notional_usd(asks)
        generic_depth_candidates = [
            value for value in (bid_depth_usd, ask_depth_usd)
            if value is not None and value > 0
        ]
        top_depth_usd = min(generic_depth_candidates) if generic_depth_candidates else None
        imbalance = None
        if bid_qty is not None and ask_qty is not None and (bid_qty + ask_qty) > 0:
            imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty)
        available_at = _iso_from_epoch_ms(
            payload.get("E")
            or payload.get("T")
            or payload.get("time")
            or payload.get("event_time")
            or payload.get("generated_at_ms")
        )
        return {
            "source": f"{ENTRY_SPREAD_SOURCE_V2_ORDERBOOK}:{key}",
            "bid_ask_spread_bps": round(float(spread_bps), 8),
            "best_bid": bid,
            "best_ask": ask,
            "mid_price": mid,
            "orderbook_imbalance": imbalance,
            "bid_depth_usd": round(float(bid_depth_usd), 8) if bid_depth_usd is not None else None,
            "ask_depth_usd": round(float(ask_depth_usd), 8) if ask_depth_usd is not None else None,
            "orderbook_depth_usd": round(float(top_depth_usd), 8) if top_depth_usd is not None else None,
            "top_of_book_depth_usd": round(float(top_depth_usd), 8) if top_depth_usd is not None else None,
            "market_depth_usd": round(float(top_depth_usd), 8) if top_depth_usd is not None else None,
            "orderbook_depth_source": f"{key}:top5_notional_usd" if top_depth_usd is not None else None,
            "entry_spread_available_at": available_at,
            "entry_spread_decision_time": _utc_iso(),
        }
    return {}


def _read_v2_market_price(r, symbol: str) -> tuple[float | None, str, str | None]:
    """Read the last price for ``symbol`` from V2-owned market data.

    Search order is strict and V2-only:

    1. ``v2:market:prices:{symbol}.ticker_24hr.lastPrice``
    2. ``v2:features:latest:{symbol}:1m.features.close_price`` only when
       the snapshot's ``feature_freshness_state`` is ``CURRENT``.

    Returns ``(price, source_label, generated_utc)``. When neither
    source is available, returns ``(None, MISSING blocker, None)`` so
    the caller can attach the explicit MISSING marker to the paper
    payload instead of fabricating a price.
    """
    if r is None or not symbol:
        return None, ENTRY_PRICE_BLOCKER_MISSING_FILL, None
    try:
        raw = r.get(f"{V2_REDIS_PREFIX}market:prices:{symbol}")
    except Exception:
        raw = None
    if raw:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            ticker = payload.get("ticker_24hr") if isinstance(payload.get("ticker_24hr"), dict) else None
            if isinstance(ticker, dict):
                px = _coerce_float(ticker.get("lastPrice"))
                if px is not None and px > 0:
                    return px, ENTRY_PRICE_SOURCE_V2_MARKET, payload.get("fetched_utc")
    try:
        raw = r.get(f"{V2_REDIS_PREFIX}features:latest:{symbol}:1m")
    except Exception:
        raw = None
    if raw:
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            payload = None
        if isinstance(payload, dict) and payload.get("feature_freshness_state") == "CURRENT":
            feats = payload.get("features") if isinstance(payload.get("features"), dict) else {}
            for key in ("close_price", "last_price", "lastPrice"):
                px = _coerce_float(feats.get(key))
                if px is not None and px > 0:
                    return px, ENTRY_PRICE_SOURCE_V2_FEATURES, payload.get("generated_at")
    return None, ENTRY_PRICE_BLOCKER_MISSING_FILL, None


def _validated_v2_feature_snapshot_payload(
    payload: Any,
    *,
    redis_key: str,
    decision_time: str,
    expected_feature_snapshot_id: str | None = None,
    expected_symbol: str | None = None,
    expected_timeframe: str | None = None,
) -> dict[str, Any]:
    try:
        parsed_payload = json.loads(payload) if isinstance(payload, str) else payload
    except (TypeError, ValueError):
        return {"features": {}, "unavailable_reason": "INVALID_V2_FEATURE_SNAPSHOT_JSON", "redis_key": redis_key}
    if not isinstance(parsed_payload, dict):
        return {"features": {}, "unavailable_reason": "INVALID_V2_FEATURE_SNAPSHOT_PAYLOAD", "redis_key": redis_key}
    payload = parsed_payload
    snapshot_id = _first_present(payload.get("feature_snapshot_id"), payload.get("snapshot_id"))
    if expected_feature_snapshot_id and str(snapshot_id or "") != str(expected_feature_snapshot_id):
        return {
            "features": {},
            "unavailable_reason": "FEATURE_SNAPSHOT_ID_MISMATCH",
            "redis_key": redis_key,
            "expected_feature_snapshot_id": expected_feature_snapshot_id,
            "feature_snapshot_id": snapshot_id,
        }
    if expected_symbol and str(payload.get("symbol") or "").upper() != str(expected_symbol).upper():
        return {
            "features": {},
            "unavailable_reason": "FEATURE_SNAPSHOT_SYMBOL_MISMATCH",
            "redis_key": redis_key,
            "expected_symbol": str(expected_symbol).upper(),
            "symbol": payload.get("symbol"),
        }
    if expected_timeframe and str(payload.get("timeframe") or "") != str(expected_timeframe):
        return {
            "features": {},
            "unavailable_reason": "FEATURE_SNAPSHOT_TIMEFRAME_MISMATCH",
            "redis_key": redis_key,
            "expected_timeframe": str(expected_timeframe),
            "timeframe": payload.get("timeframe"),
        }
    if str(payload.get("feature_freshness_state") or "").upper() != "CURRENT":
        return {
            "features": {},
            "unavailable_reason": "NON_CURRENT_V2_FEATURE_SNAPSHOT",
            "feature_freshness_state": payload.get("feature_freshness_state"),
            "redis_key": redis_key,
        }
    if payload.get("candle_closed_confirmed") is False:
        return {
            "features": {},
            "unavailable_reason": "UNFINISHED_CANDLE_FEATURE_SNAPSHOT_REJECTED",
            "redis_key": redis_key,
        }
    available_at = _first_present(
        payload.get("available_at"),
        payload.get("generated_at"),
        payload.get("source_available_time"),
    )
    available_dt = _parse_strategy_time(available_at)
    decision_dt = _parse_strategy_time(decision_time)
    if available_dt is None or decision_dt is None:
        return {
            "features": {},
            "unavailable_reason": "FEATURE_SNAPSHOT_TIME_UNPARSEABLE",
            "available_at": available_at,
            "decision_time": decision_time,
            "redis_key": redis_key,
        }
    if available_dt > decision_dt:
        return {
            "features": {},
            "unavailable_reason": "FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME",
            "available_at": available_at,
            "decision_time": decision_time,
            "redis_key": redis_key,
        }
    feature_cutoff = _first_present(
        payload.get("feature_cutoff"),
        payload.get("candle_close_time"),
        payload.get("source_event_time_est"),
    )
    feature_cutoff_dt = _parse_strategy_time(feature_cutoff)
    if feature_cutoff_dt is None:
        return {
            "features": {},
            "unavailable_reason": "FEATURE_CUTOFF_MISSING_OR_UNPARSEABLE",
            "feature_cutoff": feature_cutoff,
            "decision_time": decision_time,
            "redis_key": redis_key,
        }
    if feature_cutoff_dt > decision_dt:
        return {
            "features": {},
            "unavailable_reason": "FEATURE_CUTOFF_AFTER_DECISION_TIME",
            "feature_cutoff": feature_cutoff,
            "decision_time": decision_time,
            "redis_key": redis_key,
        }
    features = payload.get("features") if isinstance(payload.get("features"), dict) else {}
    if not features:
        return {"features": {}, "unavailable_reason": "EMPTY_V2_FEATURE_SNAPSHOT", "redis_key": redis_key}
    return {
        "features": features,
        "redis_key": redis_key,
        "feature_snapshot_id": snapshot_id,
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "feature_freshness_state": payload.get("feature_freshness_state"),
        "available_at": available_at,
        "generated_at": payload.get("generated_at"),
        "feature_cutoff": feature_cutoff,
        "source_available_time": payload.get("source_available_time"),
        "candle_close_time": payload.get("candle_close_time"),
        "candle_closed_confirmed": payload.get("candle_closed_confirmed"),
        "latest_unclosed_kline_excluded": payload.get("latest_unclosed_kline_excluded"),
        "source_hashes": payload.get("source_hashes"),
    }


def _read_v2_feature_snapshot_by_id(
    r,
    feature_snapshot_id: Any,
    *,
    decision_time: str,
    symbol: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    if r is None or feature_snapshot_id in (None, ""):
        return {"features": {}, "unavailable_reason": "MISSING_FEATURE_SNAPSHOT_ID_OR_REDIS"}
    snapshot_id = str(feature_snapshot_id)
    key = f"{V2_REDIS_PREFIX}features:snapshot:{snapshot_id}"
    try:
        raw = r.get(key)
    except Exception:
        raw = None
    if not raw:
        return {"features": {}, "unavailable_reason": "MISSING_V2_FEATURE_SNAPSHOT", "redis_key": key}
    return _validated_v2_feature_snapshot_payload(
        raw,
        redis_key=key,
        decision_time=decision_time,
        expected_feature_snapshot_id=snapshot_id,
        expected_symbol=symbol,
        expected_timeframe=timeframe,
    )


def _entry_feature_snapshot_evidence(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    features = snapshot.get("features") if isinstance(snapshot.get("features"), dict) else {}
    if not features:
        return None
    evidence = {
        "feature_snapshot_id": snapshot.get("feature_snapshot_id"),
        "symbol": snapshot.get("symbol"),
        "timeframe": snapshot.get("timeframe"),
        "available_at": snapshot.get("available_at"),
        "generated_at": snapshot.get("generated_at"),
        "feature_cutoff": snapshot.get("feature_cutoff"),
        "source_available_time": snapshot.get("source_available_time"),
        "candle_close_time": snapshot.get("candle_close_time"),
        "candle_closed_confirmed": snapshot.get("candle_closed_confirmed"),
        "latest_unclosed_kline_excluded": snapshot.get("latest_unclosed_kline_excluded"),
        "feature_freshness_state": snapshot.get("feature_freshness_state"),
        "source_hashes": snapshot.get("source_hashes"),
        "features": dict(features),
    }
    return {key: value for key, value in evidence.items() if value not in (None, "", {}, [])}


def _read_v2_feature_snapshot(
    r,
    symbol: str,
    timeframe: str | None,
    *,
    decision_time: str,
) -> dict[str, Any]:
    if r is None or not symbol:
        return {"features": {}, "unavailable_reason": "MISSING_SYMBOL_OR_REDIS"}
    normalized_symbol = str(symbol).upper()
    normalized_timeframe = str(timeframe or "1m")
    key = f"{V2_REDIS_PREFIX}features:latest:{normalized_symbol}:{normalized_timeframe}"
    try:
        raw = r.get(key)
    except Exception:
        raw = None
    if not raw:
        return {"features": {}, "unavailable_reason": "MISSING_V2_FEATURE_SNAPSHOT", "redis_key": key}
    return _validated_v2_feature_snapshot_payload(
        raw,
        redis_key=key,
        decision_time=decision_time,
        expected_symbol=normalized_symbol,
        expected_timeframe=normalized_timeframe,
    )


def _attach_entry_price_provenance(intent: dict, price: float | None, source: str, source_utc: str | None) -> None:
    """Attach entry / fill / latest price provenance to a paper intent.

    Paper has no clock skew between intent and fill (no exchange
    touch), so fill_price == entry_price == latest_price by
    construction. Each field gets its own provenance label so
    consumers can audit which V2-owned input fed the value.
    """
    now = _utc_iso()
    if price is not None and price > 0:
        intent["entry_price"] = float(price)
        intent["entry_price_source"] = source
        intent["entry_price_utc"] = now
        intent["entry_price_source_generated_utc"] = source_utc
        intent["fill_price"] = float(price)
        intent["fill_price_source"] = source
        intent["fill_price_utc"] = now
        intent["latest_price"] = float(price)
        intent["latest_price_source"] = source
        intent["latest_price_utc"] = now
        intent["entry_price_provenance_present"] = True
        intent["entry_price_blocker"] = None
    else:
        intent["entry_price"] = None
        intent["entry_price_source"] = source or ENTRY_PRICE_BLOCKER_MISSING_FILL
        intent["entry_price_utc"] = None
        intent["entry_price_source_generated_utc"] = None
        intent["fill_price"] = None
        intent["fill_price_source"] = source or ENTRY_PRICE_BLOCKER_MISSING_FILL
        intent["fill_price_utc"] = None
        intent["latest_price"] = None
        intent["latest_price_source"] = source or ENTRY_PRICE_BLOCKER_MISSING_FILL
        intent["latest_price_utc"] = None
        intent["entry_price_provenance_present"] = False
        intent["entry_price_blocker"] = ENTRY_PRICE_BLOCKER_MISSING_FILL


def _read_held_by_paper_fill_gate(r) -> list[dict]:
    """Read symbols the orchestrator held back due to the strict P0.2F
    paper-fill gate. These rows carry the gate block reasons and are NOT
    fills; they exist so the paper-intent layer / comparator / frontend
    can surface the exact block reason without changing gate behavior.
    """
    if r is None:
        return []
    raw = r.get(f"{V2_REDIS_PREFIX}orchestrator:decisions")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    held = data.get("held_by_paper_fill_gate") or []
    return [h for h in held if isinstance(h, dict)]


IMMUTABLE_ACCEPTED_FILL_FIELDS = (
    "entry_price",
    "entry_price_source",
    "entry_price_utc",
    "entry_price_source_generated_utc",
    "fill_price",
    "fill_price_source",
    "fill_price_utc",
    "mark_price_at_fill",
    "quantity",
    "notional",
    "notional_usdt",
    "paper_sizing_source",
)
PERSISTENT_ACCEPTED_FILL_METADATA_FIELDS = (
    "adaptive_capital_policy_version",
    "policy_activated_at",
    "paper_opportunity_tier",
    "paper_opportunity_tier_reason",
    "paper_fill_allowed_source",
    "strict_paper_fill_allowed_upstream",
    "b_grade_exploration_budget_cap_applied",
    "risk_budget_fraction_of_normal_adaptive",
    "normal_adaptive_risk_budget_usd",
    "normal_adaptive_gross_notional_usd",
    "normal_adaptive_allocated_margin_usd",
    "normal_adaptive_expected_net_pnl_usd",
    "b_grade_exploration_uncertainty_factor",
    "b_grade_exploration_drawdown_factor",
    "calibration_label_purpose",
    "risk_budget_usd",
    "gross_notional_usd",
    "allocated_margin_usd",
    "recommended_leverage",
    "effective_leverage",
    "recommended_margin_mode",
    "stop_distance_bps",
    "liquidation_price_estimate",
    "liquidation_buffer_bps",
    "expected_fees_usd",
    "expected_slippage_usd",
    "expected_funding_usd",
    "expected_funding_bps",
    "expected_funding_bps_source",
    "funding_rate",
    "funding_bps",
    "funding_rate_bps",
    "funding_interval_seconds",
    "expected_net_pnl_usd",
    "expected_shortfall_usd",
    "hedge_budget_usd",
    "capital_allocation_reason",
    "allocation_id",
    "allocator_decision",
    "allocator_reason",
    "entry_feature_snapshot",
    "confidence_raw",
    "confidence_calibrated",
    "selected_action_probability",
    "expected_move_bps",
    "expected_move_after_cost_bps",
    "action_probabilities",
    "policy_value",
    "value_baseline",
    "prediction_score_source",
    "prediction_score_missing_reason",
)
PERSISTENT_ACCEPTED_FILL_MODEL_INPUT_FIELDS = (
    "confidence_raw",
    "confidence_calibrated",
    "selected_action_probability",
    "expected_move_bps",
    "expected_move_after_cost_bps",
    "policy_value",
    "value_baseline",
    "expected_funding_bps",
    "funding_bps",
    "funding_rate_bps",
    "funding_rate",
    "funding_interval_seconds",
    "paper_opportunity_tier",
    "risk_budget_fraction_of_normal_adaptive",
    "normal_adaptive_risk_budget_usd",
    "normal_adaptive_gross_notional_usd",
)


def _accepted_fill_identity(row: dict[str, Any]) -> str:
    return str(
        _first_present(
            row.get("fill_id"),
            row.get("ledger_row_id"),
            row.get("intent_id"),
            row.get("signal_id"),
            row.get("prediction_id"),
            row.get("source_prediction_id"),
            row.get("source_intent_id"),
            f"{row.get('symbol')}:{row.get('timeframe')}:{row.get('side')}",
        )
    )


def _read_existing_accepted_fills(r) -> dict[str, dict]:
    if r is None:
        return {}
    try:
        raw = r.get(f"{V2_REDIS_PREFIX}paper:ledger")
    except Exception:
        raw = None
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    rows = payload.get("accepted") or payload.get("accepted_intents") or []
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        identity = _accepted_fill_identity(row)
        if identity:
            out[identity] = row
    return out


def _row_has_economic_fill_fields(row: dict[str, Any]) -> bool:
    return (
        _coerce_float(row.get("quantity")) is not None
        and _coerce_float(_first_present(row.get("notional"), row.get("notional_usdt"))) is not None
        and _coerce_float(row.get("entry_price")) is not None
        and _coerce_float(row.get("fill_price")) is not None
        and bool(row.get("symbol"))
        and bool(row.get("side"))
        and bool(row.get("prediction_id") or row.get("source_prediction_id"))
        and bool(row.get("risk_decision_id"))
        and bool(row.get("orchestrator_decision_id"))
        and bool(row.get("signal_id"))
    )


def _has_metadata_value(value: Any) -> bool:
    return value is not None and value != ""


def _copy_missing_metadata_fields(
    target: dict[str, Any],
    source: dict[str, Any],
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        if not _has_metadata_value(target.get(field)) and _has_metadata_value(source.get(field)):
            target[field] = source[field]


def _preserve_persistent_accepted_fill_metadata(
    *,
    preserved: dict[str, Any],
    prior: dict[str, Any],
) -> None:
    _copy_missing_metadata_fields(
        preserved,
        prior,
        PERSISTENT_ACCEPTED_FILL_METADATA_FIELDS,
    )
    prior_allocation = (
        prior.get("adaptive_allocation")
        if isinstance(prior.get("adaptive_allocation"), dict)
        else {}
    )
    current_allocation = (
        dict(preserved.get("adaptive_allocation"))
        if isinstance(preserved.get("adaptive_allocation"), dict)
        else {}
    )
    if prior_allocation and not current_allocation:
        current_allocation = dict(prior_allocation)
    elif prior_allocation:
        _copy_missing_metadata_fields(
            current_allocation,
            prior_allocation,
            PERSISTENT_ACCEPTED_FILL_METADATA_FIELDS,
        )
        prior_model_inputs = (
            prior_allocation.get("model_inputs")
            if isinstance(prior_allocation.get("model_inputs"), dict)
            else {}
        )
        current_model_inputs = (
            dict(current_allocation.get("model_inputs"))
            if isinstance(current_allocation.get("model_inputs"), dict)
            else {}
        )
        _copy_missing_metadata_fields(
            current_model_inputs,
            prior_model_inputs,
            PERSISTENT_ACCEPTED_FILL_MODEL_INPUT_FIELDS,
        )
        if current_model_inputs:
            current_allocation["model_inputs"] = current_model_inputs
    if current_allocation:
        preserved["adaptive_allocation"] = current_allocation


def _merge_persistent_accepted_fills(existing: dict[str, dict], current: list[dict]) -> list[dict]:
    """Preserve accepted paper fill economics across paper loop cycles.

    ``v2:paper:ledger`` is the paper accounting source of truth. A fill's
    entry/fill price and quantity must be immutable after acceptance;
    otherwise mark-to-market can never move because entry chases the
    latest price. Current signals may update ``latest_price`` only.
    """
    merged: dict[str, dict] = {}
    for identity, row in existing.items():
        persisted = dict(row)
        persisted.setdefault("fill_id", identity)
        persisted.setdefault("ledger_row_id", identity)
        persisted["paper_fill_persistence_status"] = "EXISTING_FILL_CARRIED_FORWARD"
        merged[identity] = persisted

    for row in current:
        identity = _accepted_fill_identity(row)
        incoming = dict(row)
        incoming.setdefault("fill_id", identity)
        incoming.setdefault("ledger_row_id", identity)
        incoming.setdefault("mark_price_at_fill", incoming.get("fill_price"))
        prior = merged.get(identity)
        if prior and _row_has_economic_fill_fields(prior):
            preserved = dict(incoming)
            for field in IMMUTABLE_ACCEPTED_FILL_FIELDS:
                if prior.get(field) is not None:
                    preserved[field] = prior[field]
            _preserve_persistent_accepted_fill_metadata(
                preserved=preserved,
                prior=prior,
            )
            preserved["fill_price_immutable"] = True
            preserved["paper_fill_persistence_status"] = "EXISTING_FILL_IMMUTABLE_FIELDS_PRESERVED"
            preserved["original_fill_utc"] = _first_present(prior.get("original_fill_utc"), prior.get("fill_price_utc"))
            preserved["latest_price"] = incoming.get("latest_price")
            preserved["latest_price_source"] = incoming.get("latest_price_source")
            preserved["latest_price_utc"] = incoming.get("latest_price_utc")
            merged[identity] = preserved
        else:
            incoming["fill_price_immutable"] = True
            incoming["paper_fill_persistence_status"] = "NEW_ACCEPTED_FILL_RECORDED"
            incoming["original_fill_utc"] = incoming.get("fill_price_utc")
            merged[identity] = incoming
    return list(merged.values())


def _backfill_fill_lineage_from_predictions(
    rows: list[dict[str, Any]],
    predictions_by_id: dict[str, dict[str, Any]],
    *,
    feature_snapshots_by_id: dict[str, dict[str, Any]] | None = None,
    require_feature_snapshot_deref: bool = False,
) -> list[dict[str, Any]]:
    feature_snapshots_by_id = feature_snapshots_by_id or {}
    repaired: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        prediction_id = str(
            _first_present(
                item.get("prediction_id"),
                item.get("source_prediction_id"),
                item.get("entry_prediction_id"),
                "",
            )
        )
        prediction = predictions_by_id.get(prediction_id, {}) if prediction_id else {}
        if prediction:
            for target, source in (
                ("feature_snapshot_id", "feature_snapshot_id"),
                ("entry_feature_snapshot_id", "feature_snapshot_id"),
                ("market_state_id", "market_state_id"),
                ("entry_market_state_id", "market_state_id"),
                ("timeframe", "timeframe"),
            ):
                if item.get(target) in (None, "") and prediction.get(source) not in (None, ""):
                    item[target] = prediction.get(source)
            feature_snapshot_id = _first_present(
                item.get("entry_feature_snapshot_id"),
                item.get("feature_snapshot_id"),
                prediction.get("feature_snapshot_id"),
            )
            feature_snapshot = (
                feature_snapshots_by_id.get(str(feature_snapshot_id))
                if feature_snapshot_id not in (None, "")
                else None
            )
            item = _reconstruct_trust_from_prediction(
                row=item,
                prediction=prediction,
                feature_snapshot=feature_snapshot,
                require_feature_snapshot_deref=require_feature_snapshot_deref,
                prediction_id=prediction_id,
                feature_snapshot_id=feature_snapshot_id,
            )
            if item.get("trust_reconstructed") is True:
                item.setdefault("lineage_backfilled_from_prediction_id", prediction_id)
        repaired.append(item)
    return repaired


def _scan_prediction_rows(r) -> list[dict]:
    rows: list[dict] = []
    if r is None:
        return rows
    now = datetime.now(timezone.utc)
    try:
        for key in r.scan_iter(match=f"{V2_REDIS_PREFIX}prediction:*", count=500):
            raw = r.get(str(key))
            if not raw:
                continue
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("prediction_id"):
                item = dict(payload)
                item["_redis_key"] = str(key)
                stale_reason = _prediction_stale_reason(item, now=now)
                if stale_reason:
                    item["paper_candidate_excluded_reason"] = stale_reason
                    continue
                rows.append(item)
    except Exception:
        return rows
    return rows


def _prediction_stale_reason(row: dict[str, Any], *, now: datetime) -> str | None:
    status = str(row.get("status") or "").strip()
    if status == "STALE_TF_PREDICTION":
        return "STALE_TF_PREDICTION_EXCLUDED_FROM_PAPER_ACTIONABILITY"
    if status and status not in CURRENT_PREDICTION_STATUSES:
        return f"NON_CURRENT_PREDICTION_STATUS_EXCLUDED:{status}"
    freshness = str(row.get("feature_freshness_state") or row.get("prediction_freshness_state") or "").upper()
    if freshness in {"STALE", "EXPIRED"}:
        return f"{freshness}_PREDICTION_EXCLUDED_FROM_PAPER_ACTIONABILITY"
    generated_raw = _first_present(
        row.get("generated_utc"),
        row.get("generated_at"),
        row.get("available_at"),
        row.get("created_at"),
    )
    generated = _parse_strategy_time(generated_raw)
    if generated is not None and (now - generated).total_seconds() > PREDICTION_STALE_SECONDS:
        return f"STALE_GT_{PREDICTION_STALE_SECONDS}s_EXCLUDED_FROM_PAPER_ACTIONABILITY"
    return None


def _scan_predictions_by_id(r) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in _scan_prediction_rows(r):
        out[str(row["prediction_id"])] = row
    return out


def _checkpoint_metadata_for_id(checkpoint_id: Any) -> dict[str, Any]:
    if checkpoint_id in (None, ""):
        return {}
    checkpoint_id_str = str(checkpoint_id)
    path = CHECKPOINT_DIR / f"{checkpoint_id_str}.json"
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(metadata, dict):
        return {}
    if str(metadata.get("checkpoint_id") or "") != checkpoint_id_str:
        return {}
    if metadata.get("weight_blob_written") is False:
        return {}
    return metadata


def _lineage_context_by_prediction_id(*row_collections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    fields = (
        "prediction_id",
        "entry_prediction_id",
        "signal_id",
        "entry_signal_id",
        "feature_snapshot_id",
        "entry_feature_snapshot_id",
        "symbol",
        "timeframe",
        "selected_action",
        "action",
        "side",
        "checkpoint_id",
        "model_version",
        "model_source",
        "model_id",
    )
    for rows in row_collections:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            prediction_id = _first_present(row.get("entry_prediction_id"), row.get("prediction_id"))
            if prediction_id in (None, ""):
                continue
            context = contexts.setdefault(str(prediction_id), {})
            for field in fields:
                value = row.get(field)
                if context.get(field) in (None, "") and value not in (None, ""):
                    context[field] = value
    return contexts


def _prediction_from_replay_snapshot(snapshot: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    checkpoint_id = _first_present(snapshot.get("checkpoint_id"), context.get("checkpoint_id"))
    checkpoint_metadata = _checkpoint_metadata_for_id(checkpoint_id)
    checkpoint_id = checkpoint_metadata.get("checkpoint_id") if checkpoint_metadata else snapshot.get("checkpoint_id")
    model_version = _first_present(
        snapshot.get("model_version"),
        snapshot.get("model_source"),
        snapshot.get("model_id"),
        context.get("model_version"),
        context.get("model_source"),
        context.get("model_id"),
        checkpoint_metadata.get("model_id") if checkpoint_metadata else None,
    )
    merged = dict(snapshot)
    merged.update(
        {
            "prediction_id": _first_present(snapshot.get("prediction_id"), context.get("entry_prediction_id"), context.get("prediction_id")),
            "symbol": _first_present(snapshot.get("symbol"), context.get("symbol")),
            "timeframe": _first_present(snapshot.get("timeframe"), context.get("timeframe")),
            "selected_action": _first_present(
                snapshot.get("selected_action"),
                snapshot.get("action"),
                snapshot.get("side"),
                snapshot.get("ppo_action"),
                context.get("selected_action"),
                context.get("action"),
                context.get("side"),
            ),
            "feature_snapshot_id": _first_present(
                snapshot.get("feature_snapshot_id"),
                context.get("entry_feature_snapshot_id"),
                context.get("feature_snapshot_id"),
            ),
            "checkpoint_id": checkpoint_id,
            "model_version": model_version,
            "source_hashes": _source_hashes_from_row(snapshot),
            "trust_reconstruction_source": "V2_REPLAY_SNAPSHOT_AND_CHECKPOINT_METADATA",
        }
    )
    return merged


def _read_replay_snapshot_predictions(
    r,
    contexts_by_prediction_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if r is None:
        return out
    for prediction_id, context in contexts_by_prediction_id.items():
        try:
            raw = r.get(f"{V2_REDIS_PREFIX}replay:snapshots:{prediction_id}")
        except Exception:
            continue
        if not raw:
            continue
        try:
            snapshot = json.loads(raw)
        except Exception:
            continue
        if not isinstance(snapshot, dict):
            continue
        prediction = _prediction_from_replay_snapshot(snapshot, context)
        if prediction.get("prediction_id"):
            out[str(prediction["prediction_id"])] = prediction
    return out


def _read_feature_snapshots_by_id(
    r,
    contexts_by_prediction_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if r is None:
        return out
    feature_ids = sorted(
        {
            str(feature_id)
            for context in contexts_by_prediction_id.values()
            for feature_id in (
                context.get("entry_feature_snapshot_id"),
                context.get("feature_snapshot_id"),
            )
            if feature_id not in (None, "")
        }
    )
    for feature_id in feature_ids:
        try:
            raw = r.get(f"{V2_REDIS_PREFIX}features:snapshot:{feature_id}")
        except Exception:
            continue
        if not raw:
            continue
        try:
            snapshot = json.loads(raw)
        except Exception:
            continue
        if isinstance(snapshot, dict):
            out[feature_id] = snapshot
    return out


def _feature_snapshots_from_replay_predictions(
    replay_predictions_by_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for prediction in replay_predictions_by_id.values():
        if not isinstance(prediction, dict):
            continue
        snapshot = prediction.get("feature_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            continue
        snapshot_id = _first_present(
            snapshot.get("feature_snapshot_id"),
            snapshot.get("snapshot_id"),
            prediction.get("feature_snapshot_id"),
        )
        prediction_snapshot_id = prediction.get("feature_snapshot_id")
        if snapshot_id in (None, ""):
            continue
        if prediction_snapshot_id not in (None, "") and str(snapshot_id) != str(prediction_snapshot_id):
            continue
        out[str(snapshot_id)] = snapshot
    return out


def _first_present(*values):
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _group_predictions_by_symbol(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        grouped.setdefault(symbol, []).append(row)
    for symbol_rows in grouped.values():
        symbol_rows.sort(
            key=lambda row: (
                _first_present(
                    row.get("generated_utc"),
                    row.get("generated_at"),
                    row.get("generated_est"),
                )
                or "",
                row.get("timeframe") or "",
            )
        )
    return grouped


def _count_values(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "missing")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _paper_adaptive_sizing_runtime_status(
    allocation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    accepted_count = sum(
        1
        for row in allocation_rows
        if row.get("allocator_decision") in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    )
    blocked_count = sum(
        1
        for row in allocation_rows
        if str(row.get("allocator_decision") or "").startswith("BLOCK_")
    )
    return {
        "allocator": "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR",
        "fixed_runtime_notional_removed": True,
        "paper_candidates_with_allocation": len(allocation_rows),
        "candidate_allocation_count": len(allocation_rows),
        "candidate_allocations": allocation_rows,
        "candidate_allocations_complete": True,
        "candidate_allocations_source": (
            "paper_loop_allocation_rows_before_sample_truncation"
        ),
        "candidate_allocations_selected_before_outcome": True,
        "candidate_allocations_future_labels_used_as_features": False,
        "allocator_decision_counts": _count_values(allocation_rows, "allocator_decision"),
        "accepted_allocation_count": accepted_count,
        "blocked_allocation_count": blocked_count,
        "sample_allocations": allocation_rows[:25],
        "generated_utc": _utc_iso(),
        "paper_only": True,
    }


def _count_list_values(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        values = row.get(key) if isinstance(row, dict) else None
        if not isinstance(values, list):
            continue
        for value in values:
            label = str(value or "missing")
            counts[label] = counts.get(label, 0) + 1
    return counts


def _clamp_float(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _explicit_paper_opportunity_tier(row: dict[str, Any]) -> str | None:
    raw = _first_present(
        row.get("paper_opportunity_tier"),
        row.get("paper_execution_tier"),
        row.get("opportunity_tier"),
        row.get("calibrated_opportunity_tier"),
    )
    if raw is None:
        return None
    tier = str(raw).strip().upper()
    if tier in PAPER_OPPORTUNITY_TIERS:
        return tier
    return None


def _count_paper_opportunity_tiers(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        tier = str(row.get("paper_opportunity_tier") or "").strip().upper()
        if tier not in PAPER_OPPORTUNITY_TIERS:
            continue
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def _missing_paper_opportunity_tier_count(rows: list[dict[str, Any]]) -> int:
    return sum(
        1
        for row in rows
        if str(row.get("paper_opportunity_tier") or "").strip().upper()
        not in PAPER_OPPORTUNITY_TIERS
    )


def _b_grade_exploration_budget_fraction(
    *,
    confidence_calibrated: Any,
    drawdown_bps: Any,
) -> dict[str, Any]:
    confidence = _coerce_float(confidence_calibrated)
    drawdown = _coerce_float(drawdown_bps) or 0.0
    if confidence is None or confidence < B_GRADE_EXPLORATION_MIN_CONFIDENCE:
        return {
            "risk_budget_fraction_of_normal_adaptive": 0.0,
            "b_grade_exploration_uncertainty_factor": 0.0,
            "b_grade_exploration_drawdown_factor": 0.0,
            "b_grade_exploration_budget_formula": "confidence_below_b_grade_exploration_floor",
        }
    confidence_span = max(
        1e-9,
        PAPER_STRICT_A_CONFIDENCE_THRESHOLD - B_GRADE_EXPLORATION_MIN_CONFIDENCE,
    )
    confidence_progress = _clamp_float(
        (confidence - B_GRADE_EXPLORATION_MIN_CONFIDENCE) / confidence_span,
        0.0,
        1.0,
    )
    # The budget rises as uncertainty falls, then fades to zero as drawdown
    # approaches the paper-only exploration stop.
    uncertainty_factor = 0.25 + 0.75 * confidence_progress
    drawdown_pressure = _clamp_float(
        max(0.0, drawdown) / B_GRADE_EXPLORATION_DRAWDOWN_STOP_BPS,
        0.0,
        1.0,
    )
    drawdown_factor = 1.0 - drawdown_pressure
    fraction = (
        B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL
        * uncertainty_factor
        * drawdown_factor
    )
    return {
        "risk_budget_fraction_of_normal_adaptive": round(max(0.0, fraction), 8),
        "b_grade_exploration_uncertainty_factor": round(uncertainty_factor, 8),
        "b_grade_exploration_drawdown_factor": round(drawdown_factor, 8),
        "b_grade_exploration_budget_formula": (
            "max_fraction_of_normal_adaptive"
            "*confidence_uncertainty_factor*drawdown_guard_factor"
        ),
    }


def _allocation_allows_economic_paper_fill(allocation: dict[str, Any]) -> bool:
    return allocation.get("allocator_decision") in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}


def _classify_paper_opportunity_tier(
    *,
    signal: dict[str, Any],
    intent: dict[str, Any],
    allocation: dict[str, Any],
    integrity_gate: dict[str, Any],
    local_trade_gates_pass: bool,
    exploration_trade_gates_pass: bool | None = None,
    paper_fill_allowed_upstream: bool,
    portfolio_drawdown_bps: Any,
) -> dict[str, Any]:
    confidence = _first_present(
        intent.get("confidence_calibrated"),
        signal.get("confidence_calibrated"),
        signal.get("confidence"),
        allocation.get("confidence_calibrated"),
    )
    expected_edge = _coerce_float(
        _first_present(
            intent.get("expected_move_after_cost_bps"),
            signal.get("expected_move_after_cost_bps"),
            allocation.get("expected_move_after_cost_bps"),
        )
    )
    side = str(
        _first_present(
            intent.get("side"),
            signal.get("side"),
            intent.get("action"),
            signal.get("selected_action"),
            signal.get("action"),
        )
        or ""
    ).strip().lower()
    signed_edge_favorable = expected_move_after_cost_favorable_for_side(
        side=side,
        expected_move_after_cost_bps=expected_edge,
    )
    exploration_trade_gates_allowed = (
        bool(local_trade_gates_pass)
        if exploration_trade_gates_pass is None
        else bool(exploration_trade_gates_pass)
    )
    explicit_tier = _explicit_paper_opportunity_tier(signal)
    if explicit_tier is None:
        explicit_tier = _explicit_paper_opportunity_tier(intent)
    base = {
        "paper_only": True,
        "places_real_order": False,
        "strict_paper_fill_allowed_upstream": bool(paper_fill_allowed_upstream),
        "explicit_paper_opportunity_tier": explicit_tier,
    }
    if integrity_gate.get("allowed") is not True:
        return {
            **base,
            "paper_opportunity_tier": PAPER_TIER_NO_TRADE,
            "paper_opportunity_tier_reason": "MARKET_STATE_INTEGRITY_INVALID",
        }
    if expected_edge is None or not signed_edge_favorable:
        return {
            **base,
            "paper_opportunity_tier": PAPER_TIER_NO_TRADE,
            "paper_opportunity_tier_reason": "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST",
            "expected_move_side": side or None,
        }
    if not _allocation_allows_economic_paper_fill(allocation):
        return {
            **base,
            "paper_opportunity_tier": PAPER_TIER_NO_TRADE,
            "paper_opportunity_tier_reason": str(
                allocation.get("allocator_decision") or "ADAPTIVE_ALLOCATOR_NOT_ALLOWING_SIZE"
            ),
        }
    if paper_fill_allowed_upstream and local_trade_gates_pass:
        return {
            **base,
            "paper_opportunity_tier": PAPER_TIER_A_GRADE_EXECUTION,
            "paper_opportunity_tier_reason": "STRICT_UPSTREAM_PAPER_FILL_GATE_ALLOWED",
            "paper_fill_allowed_source": "STRICT_UPSTREAM_PAPER_FILL_GATE",
        }
    if explicit_tier == PAPER_TIER_A_GRADE_EXECUTION and local_trade_gates_pass:
        return {
            **base,
            "paper_opportunity_tier": PAPER_TIER_A_GRADE_EXECUTION,
            "paper_opportunity_tier_reason": "DYNAMIC_A_GRADE_SIGNAL_TAG_ALLOWED_PAPER_ONLY",
            "paper_fill_allowed_source": "DYNAMIC_A_GRADE_PAPER_TAG",
        }
    b_grade_source = None
    if explicit_tier == PAPER_TIER_B_GRADE_EXPLORATION:
        b_grade_source = "EXPLICIT_B_GRADE_PAPER_TAG"
    elif _is_paper_confidence_trial_row(signal):
        b_grade_source = "PAPER_CONFIDENCE_THRESHOLD_TRIAL"
    elif exploration_trade_gates_allowed:
        b_grade_source = "DYNAMIC_POSITIVE_EDGE_BELOW_A_GRADE_EXPLORATION"
    if b_grade_source:
        budget = _b_grade_exploration_budget_fraction(
            confidence_calibrated=confidence,
            drawdown_bps=portfolio_drawdown_bps,
        )
        if budget["risk_budget_fraction_of_normal_adaptive"] > 0.0:
            return {
                **base,
                **budget,
                "paper_opportunity_tier": PAPER_TIER_B_GRADE_EXPLORATION,
                "paper_opportunity_tier_reason": b_grade_source,
                "paper_fill_allowed_source": "B_GRADE_EXPLORATION_PAPER_LOCAL_GATE",
                "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            }
        return {
            **base,
            **budget,
            "paper_opportunity_tier": PAPER_TIER_SHADOW_ONLY,
            "paper_opportunity_tier_reason": "B_GRADE_EXPLORATION_BUDGET_FRACTION_ZERO",
        }
    if not local_trade_gates_pass:
        return {
            **base,
            "paper_opportunity_tier": PAPER_TIER_NO_TRADE,
            "paper_opportunity_tier_reason": "LOCAL_PAPER_TRADE_GATES_FAILED",
        }
    return {
        **base,
        "paper_opportunity_tier": PAPER_TIER_SHADOW_ONLY,
        "paper_opportunity_tier_reason": "UPSTREAM_PAPER_FILL_GATE_BLOCKED_AND_NOT_EXPLORATION_ELIGIBLE",
    }


def _apply_paper_tier_classification(
    *,
    intent: dict[str, Any],
    allocation: dict[str, Any],
    classification: dict[str, Any],
) -> None:
    for field in (
        "paper_opportunity_tier",
        "paper_opportunity_tier_reason",
        "paper_fill_allowed_source",
        "strict_paper_fill_allowed_upstream",
        "explicit_paper_opportunity_tier",
        "risk_budget_fraction_of_normal_adaptive",
        "b_grade_exploration_uncertainty_factor",
        "b_grade_exploration_drawdown_factor",
        "b_grade_exploration_budget_formula",
        "calibration_label_purpose",
    ):
        if field in classification:
            intent[field] = classification[field]
            allocation[field] = classification[field]
    model_inputs = allocation.get("model_inputs") if isinstance(allocation.get("model_inputs"), dict) else {}
    if model_inputs is not allocation.get("model_inputs"):
        allocation["model_inputs"] = model_inputs
    for field in (
        "paper_opportunity_tier",
        "risk_budget_fraction_of_normal_adaptive",
        "b_grade_exploration_uncertainty_factor",
        "b_grade_exploration_drawdown_factor",
        "b_grade_exploration_budget_formula",
    ):
        if field in classification:
            model_inputs[field] = classification[field]


def _scale_allocation_field(value: Any, fraction: float, *, field: str) -> float | None:
    parsed = _coerce_float(value)
    if parsed is None:
        return None
    digits = 12 if field == "target_quantity" else 8
    return round(parsed * fraction, digits)


def _apply_b_grade_exploration_budget_cap(
    *,
    intent: dict[str, Any],
    allocation: dict[str, Any],
    risk_budget_fraction_of_normal_adaptive: Any,
) -> None:
    fraction = _coerce_float(risk_budget_fraction_of_normal_adaptive) or 0.0
    fraction = _clamp_float(
        fraction,
        0.0,
        B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL,
    )
    allocation["b_grade_exploration_budget_cap_applied"] = True
    allocation["risk_budget_fraction_of_normal_adaptive"] = round(fraction, 8)
    allocation["paper_only"] = True
    allocation["places_real_order"] = False
    intent["b_grade_exploration_budget_cap_applied"] = True
    intent["risk_budget_fraction_of_normal_adaptive"] = round(fraction, 8)
    intent["paper_only"] = True
    intent["places_real_order"] = False
    for field in (
        "risk_budget_usd",
        "gross_notional_usd",
        "allocated_margin_usd",
        "expected_net_pnl_usd",
        "target_notional_usdt",
        "target_quantity",
    ):
        value = allocation.get(field)
        if value not in (None, ""):
            normal_field = f"normal_adaptive_{field}"
            allocation.setdefault(normal_field, value)
            intent.setdefault(normal_field, value)
    for field in B_GRADE_EXPLORATION_SCALABLE_ALLOCATION_FIELDS:
        scaled = _scale_allocation_field(allocation.get(field), fraction, field=field)
        if scaled is not None:
            allocation[field] = scaled
    if allocation.get("target_notional_usdt") is not None:
        allocation["gross_notional_usd"] = allocation["target_notional_usdt"]
    model_inputs = allocation.get("model_inputs") if isinstance(allocation.get("model_inputs"), dict) else {}
    if model_inputs is not allocation.get("model_inputs"):
        allocation["model_inputs"] = model_inputs
    model_inputs["b_grade_exploration_budget_cap_applied"] = True
    model_inputs["risk_budget_fraction_of_normal_adaptive"] = round(fraction, 8)
    model_inputs["normal_adaptive_risk_budget_usd"] = allocation.get("normal_adaptive_risk_budget_usd")
    model_inputs["normal_adaptive_gross_notional_usd"] = allocation.get("normal_adaptive_gross_notional_usd")
    if _coerce_float(model_inputs.get("selected_allocated_margin_usd")) is not None:
        model_inputs["normal_adaptive_selected_allocated_margin_usd"] = model_inputs[
            "selected_allocated_margin_usd"
        ]
        model_inputs["selected_allocated_margin_usd"] = allocation.get("allocated_margin_usd")
    reason = str(allocation.get("final_size_reason") or allocation.get("capital_allocation_reason") or "")
    capped_reason = "b_grade_exploration_fraction_of_normal_adaptive_budget"
    allocation["final_size_reason"] = f"{reason}:{capped_reason}" if reason else capped_reason
    allocation["capital_allocation_reason"] = allocation["final_size_reason"]
    intent["capital_allocation_reason"] = allocation["capital_allocation_reason"]


def _paper_exploration_tier_status(
    *,
    accepted_rows: list[dict[str, Any]],
    blocked_rows: list[dict[str, Any]],
    shadow_rows: list[dict[str, Any]],
    held_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = accepted_rows + blocked_rows + shadow_rows + held_rows
    b_grade_accepted = [
        row
        for row in accepted_rows
        if row.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
    ]
    fractions = [
        value
        for value in (
            _coerce_float(row.get("risk_budget_fraction_of_normal_adaptive"))
            for row in b_grade_accepted
        )
        if value is not None
    ]
    return {
        "status": "ACTIVE",
        "paper_only": True,
        "live_path_changed": False,
        "tiers": list(PAPER_OPPORTUNITY_TIERS),
        "tier_counts": _count_paper_opportunity_tiers(rows),
        "accepted_tier_counts": _count_paper_opportunity_tiers(accepted_rows),
        "blocked_tier_counts": _count_paper_opportunity_tiers(blocked_rows),
        "shadow_tier_counts": _count_paper_opportunity_tiers(shadow_rows),
        "held_tier_counts": _count_paper_opportunity_tiers(held_rows),
        "legacy_unclassified_tier_count": _missing_paper_opportunity_tier_count(rows),
        "legacy_accepted_without_tier_count": _missing_paper_opportunity_tier_count(accepted_rows),
        "blocked_without_tier_count": _missing_paper_opportunity_tier_count(blocked_rows),
        "shadow_without_tier_count": _missing_paper_opportunity_tier_count(shadow_rows),
        "held_without_tier_count": _missing_paper_opportunity_tier_count(held_rows),
        "b_grade_exploration_accepted_count": len(b_grade_accepted),
        "b_grade_exploration_max_risk_fraction_of_normal_adaptive": (
            B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL
        ),
        "b_grade_exploration_observed_max_risk_fraction": (
            round(max(fractions), 8) if fractions else 0.0
        ),
        "b_grade_exploration_budget_cap_applied_count": sum(
            1 for row in b_grade_accepted if row.get("b_grade_exploration_budget_cap_applied") is True
        ),
        "b_grade_exploration_live_routing_blocked": all(
            row.get("paper_only") is True and row.get("places_real_order") is False
            for row in b_grade_accepted
        ),
        "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
        "sample_b_grade_exploration_fills": b_grade_accepted[:25],
        "generated_utc": _utc_iso(),
    }


def _normalized_directional_side(value: Any) -> str | None:
    side = str(value or "").strip().lower()
    if side in {"long", "buy", "open_long", "proceed_long"} or side.endswith("_long"):
        return "long"
    if side in {"short", "sell", "open_short", "proceed_short"} or side.endswith("_short"):
        return "short"
    return None


def _closed_trade_side_counts(existing_ledger: dict[str, Any]) -> dict[str, int]:
    counts = {"long": 0, "short": 0}
    rows = existing_ledger.get("closed_trades") or existing_ledger.get("closes") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        side = _normalized_directional_side(
            _first_present(row.get("side"), row.get("action"), row.get("direction"))
        )
        if side in counts:
            counts[side] += 1
    return counts


def _paper_directional_collapse_guard(existing_ledger: dict[str, Any], candidate_side: Any) -> dict[str, Any]:
    side = _normalized_directional_side(candidate_side)
    counts = _closed_trade_side_counts(existing_ledger)
    total = counts["long"] + counts["short"]
    majority_side = "long" if counts["long"] >= counts["short"] else "short"
    minority_side = "short" if majority_side == "long" else "long"
    majority_count = counts[majority_side]
    minority_count = counts[minority_side]
    majority_share = (majority_count / total) if total else None
    status = {
        "guard": DIRECTIONAL_COLLAPSE_GUARD_NAME,
        "candidate_side": side,
        "allowed": True,
        "block_reason": None,
        "closed_trade_count": total,
        "long_closed_trade_count": counts["long"],
        "short_closed_trade_count": counts["short"],
        "majority_side": majority_side if total else None,
        "majority_side_share": majority_share,
        "minority_side": minority_side if total else None,
        "minimum_closed_trades": DIRECTIONAL_COLLAPSE_MIN_CLOSED_TRADES,
        "minimum_side_trades": DIRECTIONAL_COLLAPSE_MIN_SIDE_TRADES,
    }
    if side is None:
        status["allowed"] = False
        status["block_reason"] = "CANDIDATE_SIDE_INVALID"
        return status
    if total < DIRECTIONAL_COLLAPSE_MIN_CLOSED_TRADES:
        status["sample_status"] = "INSUFFICIENT_CLOSED_TRADE_SAMPLE"
        return status
    collapsed = (
        minority_count < DIRECTIONAL_COLLAPSE_MIN_SIDE_TRADES
        and majority_share is not None
        and majority_share >= DIRECTIONAL_COLLAPSE_MAJOR_SIDE_SHARE
    )
    status["directional_collapse_detected"] = collapsed
    if collapsed and side == majority_side:
        status["allowed"] = False
        status["block_reason"] = DIRECTIONAL_COLLAPSE_BLOCK_REASON
    return status


def _normalized_strategy_mode(value: Any) -> str | None:
    mode = str(value or "").strip()
    return mode if mode else None


def _paper_audit_strategy_mode(strategy_router: dict[str, Any]) -> str:
    selected_mode = str(strategy_router.get("selected_mode") or "UNKNOWN_STRATEGY")
    if selected_mode != "reduce_size_mode":
        return selected_mode
    labels = {str(label) for label in strategy_router.get("regime_labels") or []}
    if "BREAKOUT" in labels:
        return "breakout_mode"
    if "TREND" in labels:
        return "trend_mode"
    if "RANGE" in labels:
        return "mean_reversion_mode"
    if "HIGH_VOLATILITY" in labels:
        return "scalp_mode"
    return selected_mode


def _paper_strategy_size_adjustment_mode(strategy_router: dict[str, Any]) -> str | None:
    selected_mode = str(strategy_router.get("selected_mode") or "")
    if selected_mode == "reduce_size_mode":
        return selected_mode
    return None


def _closed_trade_rows(existing_ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in existing_ledger.get("closed_trades") or existing_ledger.get("closes") or []
        if isinstance(row, dict)
    ]


def _strategy_mode_counts_for_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        mode = _normalized_strategy_mode(
            _first_present(
                row.get("strategy_selected_mode"),
                row.get("strategy_id"),
                row.get("strategy_family"),
                "unknown",
            )
        )
        if not mode:
            continue
        counts[mode] = counts.get(mode, 0) + 1
    return counts


def _closed_trade_strategy_mode_counts(existing_ledger: dict[str, Any]) -> dict[str, int]:
    return _strategy_mode_counts_for_rows(_closed_trade_rows(existing_ledger))


def _paper_strategy_mode_collapse_guard(
    existing_ledger: dict[str, Any],
    candidate_mode: Any,
) -> dict[str, Any]:
    mode = _normalized_strategy_mode(candidate_mode)
    closed_rows = _closed_trade_rows(existing_ledger)
    historical_counts = _strategy_mode_counts_for_rows(closed_rows)
    active_policy_rows = [
        row
        for row in closed_rows
        if str(row.get("paper_exit_policy_version") or "") == PAPER_EXIT_POLICY_VERSION
    ]
    active_policy_counts = _strategy_mode_counts_for_rows(active_policy_rows)
    active_policy_sample_ready = (
        len(active_policy_rows) >= STRATEGY_MODE_COLLAPSE_MIN_CLOSED_TRADES
    )
    counts = active_policy_counts if active_policy_sample_ready else historical_counts
    evidence_scope = (
        "active_policy"
        if active_policy_sample_ready
        else (
            "all_history_until_active_policy_min_sample"
            if active_policy_rows
            else "all_history"
        )
    )
    total = sum(counts.values())
    top_mode = None
    top_count = 0
    if counts:
        top_mode, top_count = max(counts.items(), key=lambda item: item[1])
    top_share = (top_count / total) if total else None
    collapsed = (
        total >= STRATEGY_MODE_COLLAPSE_MIN_CLOSED_TRADES
        and top_share is not None
        and top_share >= STRATEGY_MODE_COLLAPSE_MAJOR_MODE_SHARE
    )
    status = {
        "guard": STRATEGY_MODE_COLLAPSE_GUARD_NAME,
        "candidate_mode": mode,
        "allowed": True,
        "block_reason": None,
        "closed_trade_count": total,
        "mode_counts": counts,
        "top_mode": top_mode,
        "top_mode_count": top_count,
        "top_mode_share": top_share,
        "evidence_scope": evidence_scope,
        "policy_version": PAPER_EXIT_POLICY_VERSION,
        "policy_version_filter_enabled": active_policy_sample_ready,
        "unfiltered_closed_trade_count": len(closed_rows),
        "filtered_out_closed_trade_count": (
            len(closed_rows) - len(active_policy_rows)
            if active_policy_sample_ready
            else 0
        ),
        "historical_mode_counts": historical_counts,
        "active_policy_closed_trade_count": len(active_policy_rows),
        "active_policy_mode_counts": active_policy_counts,
        "active_policy_sample_ready": active_policy_sample_ready,
        "minimum_closed_trades": STRATEGY_MODE_COLLAPSE_MIN_CLOSED_TRADES,
        "major_mode_share_threshold": STRATEGY_MODE_COLLAPSE_MAJOR_MODE_SHARE,
        "strategy_mode_collapse_detected": collapsed,
    }
    if mode is None:
        status["allowed"] = False
        status["block_reason"] = "CANDIDATE_STRATEGY_MODE_MISSING"
        return status
    if total < STRATEGY_MODE_COLLAPSE_MIN_CLOSED_TRADES:
        status["sample_status"] = "INSUFFICIENT_CLOSED_TRADE_SAMPLE"
        return status
    if collapsed and mode == top_mode:
        status["allowed"] = False
        status["block_reason"] = STRATEGY_MODE_COLLAPSE_BLOCK_REASON
    return status


def _paper_drawdown_recovery_router_result(
    *,
    existing_ledger: dict[str, Any],
    strategy_router: dict[str, Any],
    candidate_side: Any,
    current_position_state: str,
    paper_fill_allowed_upstream: bool,
    expected_move_after_cost_bps: float | None,
    confidence_calibrated: float | None,
    live_gate: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Paper-only recovery valve for minority-side audit evidence collection.

    The shared strategy router remains conservative under drawdown. This helper
    only affects the paper loop, only when the router block is exactly the
    drawdown limit, and only for a clean underrepresented side with no current
    open position for the symbol.
    """
    side = _normalized_directional_side(candidate_side)
    directional_guard = _paper_directional_collapse_guard(existing_ledger, side)
    current_state = str(current_position_state or "UNKNOWN").upper()
    reason_codes = {str(reason) for reason in strategy_router.get("reason_codes") or []}
    status: dict[str, Any] = {
        "guard": PAPER_DRAWDOWN_RECOVERY_GUARD_NAME,
        "paper_only": True,
        "candidate_side": side,
        "allowed": False,
        "recovered": False,
        "block_reason": None,
        "router_block_reason": strategy_router.get("block_reason"),
        "router_reason_codes": sorted(reason_codes),
        "current_position_state": current_state,
        "paper_fill_allowed_upstream": bool(paper_fill_allowed_upstream),
        "expected_move_after_cost_bps": expected_move_after_cost_bps,
        "confidence_calibrated": confidence_calibrated,
        "minimum_confidence": PAPER_DRAWDOWN_RECOVERY_MIN_CONFIDENCE,
        "live_gate": live_gate,
        "directional_guard": directional_guard,
    }

    if strategy_router.get("block_reason") != "DRAWDOWN_LIMIT_BLOCK":
        status["block_reason"] = "ROUTER_BLOCK_NOT_DRAWDOWN_LIMIT"
        return strategy_router, status
    if "DRAWDOWN_LIMIT_BLOCK" not in reason_codes:
        status["block_reason"] = "DRAWDOWN_REASON_CODE_MISSING"
        return strategy_router, status
    if live_gate != LIVE_GATE_BLOCKED:
        status["block_reason"] = "LIVE_GATE_NOT_BLOCKED_FOR_PAPER_RECOVERY"
        return strategy_router, status
    if side not in {"long", "short"}:
        status["block_reason"] = "CANDIDATE_SIDE_INVALID"
        return strategy_router, status
    if current_state != "FLAT":
        status["block_reason"] = "CURRENT_POSITION_NOT_FLAT"
        return strategy_router, status
    if paper_fill_allowed_upstream is not True:
        status["block_reason"] = "UPSTREAM_PAPER_FILL_NOT_ALLOWED"
        return strategy_router, status
    if directional_guard.get("directional_collapse_detected") is not True:
        status["block_reason"] = "DIRECTIONAL_COLLAPSE_NOT_DETECTED"
        return strategy_router, status
    if side != directional_guard.get("minority_side"):
        status["block_reason"] = "CANDIDATE_NOT_MINORITY_SIDE"
        return strategy_router, status
    status["expected_move_after_cost_favorable_for_side"] = expected_move_after_cost_favorable_for_side(
        side=side,
        expected_move_after_cost_bps=expected_move_after_cost_bps,
    )
    if not status["expected_move_after_cost_favorable_for_side"]:
        status["block_reason"] = "EXPECTED_MOVE_AFTER_COST_NOT_FAVORABLE_FOR_SIDE"
        return strategy_router, status
    if confidence_calibrated is None or confidence_calibrated < PAPER_DRAWDOWN_RECOVERY_MIN_CONFIDENCE:
        status["block_reason"] = "CONFIDENCE_BELOW_PAPER_RECOVERY_FLOOR"
        return strategy_router, status

    recovered = dict(strategy_router)
    recovered["selected_mode"] = "reduce_size_mode"
    recovered["block_reason"] = None
    recovered["size_multiplier"] = round(
        min(
            _coerce_float(strategy_router.get("size_multiplier")) or 1.0,
            PAPER_DRAWDOWN_RECOVERY_SIZE_MULTIPLIER,
        ),
        6,
    )
    action_mask = dict(recovered.get("action_mask") or {})
    action_mask.setdefault("hold", True)
    action_mask["long"] = side == "long"
    action_mask["short"] = side == "short"
    action_mask["close"] = False
    recovered["action_mask"] = action_mask
    recovered["allowed_actions"] = [name for name, allowed in action_mask.items() if allowed]
    recovered["reason_codes"] = sorted(reason_codes | {PAPER_DRAWDOWN_RECOVERY_REASON})
    recovered["regime_labels"] = sorted(
        {str(label) for label in recovered.get("regime_labels") or []}
        | {"paper_drawdown_recovery"}
    )
    explanation = dict(recovered.get("explanation") or {})
    explanation["paper_drawdown_recovery_guard"] = {
        "allowed": True,
        "guard": PAPER_DRAWDOWN_RECOVERY_GUARD_NAME,
        "reason": PAPER_DRAWDOWN_RECOVERY_REASON,
        "size_multiplier": recovered["size_multiplier"],
    }
    recovered["explanation"] = explanation
    status["allowed"] = True
    status["recovered"] = True
    status["recovery_reason"] = PAPER_DRAWDOWN_RECOVERY_REASON
    status["recovery_size_multiplier"] = recovered["size_multiplier"]
    return recovered, status


def _read_existing_ledger_payload(r) -> dict[str, Any]:
    if r is None:
        return {}
    try:
        raw = r.get(f"{V2_REDIS_PREFIX}paper:ledger")
    except Exception:
        raw = None
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_portfolio_state(r) -> dict[str, Any]:
    payload = _read_json_key(r, f"{V2_REDIS_PREFIX}portfolio:state")
    return payload if isinstance(payload, dict) else {}


def _portfolio_equity_context(r) -> dict[str, float]:
    portfolio = _read_portfolio_state(r)
    equity = _coerce_float(_first_present(portfolio.get("equity"), portfolio.get("current_session_equity")))
    cash = _coerce_float(portfolio.get("cash_balance"))
    wallet = _coerce_float(_first_present(portfolio.get("wallet_balance"), portfolio.get("initial_capital"), equity))
    if equity is None or equity <= 0:
        equity = _coerce_float(portfolio.get("initial_capital")) or 0.0
    if cash is None or cash <= 0:
        cash = equity
    if wallet is None or wallet <= 0:
        wallet = equity
    return {
        "equity": float(equity or 0.0),
        "available_margin": float(cash or 0.0),
        "wallet_balance": float(wallet or 0.0),
        "drawdown_bps": abs(_coerce_float(portfolio.get("current_drawdown_bps")) or 0.0),
    }


def _open_exposures_from_ledger(ledger: dict[str, Any]) -> tuple[dict[str, float], float]:
    symbol_exposures: dict[str, float] = {}
    total = 0.0
    for row in ledger.get("open_positions") or ledger.get("positions") or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        notional = _coerce_float(_first_present(row.get("notional"), row.get("gross_notional"), row.get("notional_usdt")))
        if not symbol or notional is None:
            continue
        symbol_exposures[symbol] = symbol_exposures.get(symbol, 0.0) + abs(notional)
        total += abs(notional)
    return symbol_exposures, total


def _read_json_any_key(r, key: str) -> Any:
    if r is None:
        return None
    try:
        raw = r.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _parse_epoch_ms(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        if parsed != parsed or parsed in (float("inf"), float("-inf")):
            return None
        return int(parsed * 1000) if abs(parsed) < 10_000_000_000 else int(parsed)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = float(stripped)
        except ValueError:
            parsed_dt = _parse_strategy_time(stripped)
            return int(parsed_dt.timestamp() * 1000) if parsed_dt else None
        return int(parsed * 1000) if abs(parsed) < 10_000_000_000 else int(parsed)
    return None


def _correlation_candle_rows_from_payload(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, (dict, list))]
    if not isinstance(payload, dict):
        return []
    for key in ("candles", "rows", "items", "data", "market_candles"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, (dict, list))]
    if any(key in payload for key in ("close", "close_time", "candle_close_time", "ohlcv")):
        return [dict(payload)]
    return []


def _closed_candle_flag_confirmed(row: dict[str, Any], *, source_key: str | None) -> bool:
    if "ohlcv_closed:" in str(source_key or ""):
        return (
            row.get("candle_closed_confirmed") is True
            or row.get("closed_candle") is True
            or row.get("is_closed") is True
            or row.get("feature_eligible") is True
        )
    explicit = _first_present(
        row.get("candle_closed_confirmed"),
        row.get("closed_candle"),
        row.get("is_closed"),
        row.get("feature_eligible"),
    )
    return explicit is not False


def _correlation_candle_point(
    row: Any,
    *,
    generated_ms: int,
    source_key: str | None,
) -> tuple[int, float] | str:
    available_ms: int | None = None
    if isinstance(row, list) and len(row) > 6:
        close_ms = _parse_epoch_ms(row[6])
        close_value = _coerce_float(row[4])
    elif isinstance(row, dict):
        close_ms = _parse_epoch_ms(_first_present(
            row.get("candle_close_time"),
            row.get("close_time"),
            row.get("event_time"),
            row.get("source_sequence_id"),
        ))
        ohlcv = row.get("ohlcv") if isinstance(row.get("ohlcv"), dict) else {}
        close_value = _coerce_float(_first_present(row.get("close"), ohlcv.get("close")))
        available_ms = _parse_epoch_ms(_first_present(row.get("available_at"), row.get("ingested_at")))
        if not _closed_candle_flag_confirmed(row, source_key=source_key):
            return "UNFINISHED_CANDLE"
    else:
        return "UNSUPPORTED_CANDLE_ROW"
    if close_ms is None:
        return "MISSING_CANDLE_CLOSE_TIME"
    if close_ms > generated_ms:
        return "CANDLE_CLOSE_TIME_AFTER_DECISION_TIME"
    if available_ms is not None and available_ms > generated_ms:
        return "AVAILABLE_AT_AFTER_DECISION_TIME"
    if close_value is None or close_value <= 0.0:
        return "MISSING_OR_NON_POSITIVE_CLOSE"
    return close_ms, close_value


def _correlation_returns_from_candles(
    rows: list[Any],
    *,
    generated_utc: str,
    source_key: str | None,
) -> tuple[dict[int, float], dict[str, Any]]:
    generated_dt = _parse_strategy_time(generated_utc)
    generated_ms = int(generated_dt.timestamp() * 1000) if generated_dt else 0
    points_by_time: dict[int, float] = {}
    rejects: dict[str, int] = {}
    for row in rows:
        point = _correlation_candle_point(row, generated_ms=generated_ms, source_key=source_key)
        if isinstance(point, str):
            rejects[point] = rejects.get(point, 0) + 1
            continue
        close_ms, close_value = point
        points_by_time[close_ms] = close_value
    ordered_points = sorted(points_by_time.items())
    returns: dict[int, float] = {}
    previous_close: float | None = None
    for close_ms, close_value in ordered_points:
        if previous_close and previous_close > 0.0:
            returns[close_ms] = (close_value / previous_close) - 1.0
        previous_close = close_value
    last_close_ms = ordered_points[-1][0] if ordered_points else None
    age_seconds = None
    if generated_ms and last_close_ms is not None:
        age_seconds = max(0.0, (generated_ms - last_close_ms) / 1000.0)
    diagnostics = {
        "source": source_key,
        "raw_candle_count": len(rows),
        "accepted_candle_count": len(ordered_points),
        "return_count": len(returns),
        "last_candle_age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "reject_counts": rejects,
    }
    return returns, diagnostics


def _pearson_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < CORRELATION_MIN_RETURN_POINTS:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    covariance = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_var = sum((x - left_mean) ** 2 for x in left)
    right_var = sum((y - right_mean) ** 2 for y in right)
    if left_var <= 0.0 or right_var <= 0.0:
        return None
    return covariance / ((left_var * right_var) ** 0.5)


def _read_symbol_correlation_returns(
    r,
    symbol: str,
    *,
    generated_utc: str,
) -> tuple[dict[int, float] | None, dict[str, Any]]:
    normalized = symbol.upper()
    candidate_keys = (
        f"{V2_REDIS_PREFIX}market:ohlcv:binance:{normalized}:{CORRELATION_CANDLE_TIMEFRAME}",
        f"{V2_REDIS_PREFIX}market:ohlcv_closed:binance:{normalized}:{CORRELATION_CANDLE_TIMEFRAME}",
    )
    for key in candidate_keys:
        rows = _correlation_candle_rows_from_payload(_read_json_any_key(r, key))
        if not rows:
            continue
        returns, diagnostics = _correlation_returns_from_candles(
            rows,
            generated_utc=generated_utc,
            source_key=key,
        )
        age = _coerce_float(diagnostics.get("last_candle_age_seconds"))
        if age is None:
            diagnostics["status"] = "MISSING_ACCEPTED_CANDLES"
            return None, diagnostics
        if age > CORRELATION_MAX_CANDLE_AGE_SECONDS:
            diagnostics["status"] = "STALE_LAST_CANDLE"
            return None, diagnostics
        if len(returns) < CORRELATION_MIN_RETURN_POINTS:
            diagnostics["status"] = "INSUFFICIENT_RETURN_POINTS"
            return None, diagnostics
        diagnostics["status"] = "READY"
        return returns, diagnostics
    return None, {
        "source": None,
        "status": "MISSING_MARKET_CANDLES",
        "raw_candle_count": 0,
        "accepted_candle_count": 0,
        "return_count": 0,
    }


def _derive_candidate_correlation_contexts(
    r,
    *,
    candidate_symbols: list[str],
    open_symbols: list[str],
    generated_utc: str,
) -> dict[str, dict[str, Any]]:
    unique_open_symbols = sorted({symbol.upper() for symbol in open_symbols if symbol})
    unique_candidate_symbols = sorted({symbol.upper() for symbol in candidate_symbols if symbol})
    if not unique_open_symbols:
        return {
            symbol: {
                "correlation_exposure_pct": 0.0,
                "correlation_input_status": "NO_OPEN_POSITIONS",
                "correlation_input_source": "NO_OPEN_POSITIONS",
                "correlation_pair_count": 0,
            }
            for symbol in unique_candidate_symbols
        }
    returns_by_symbol: dict[str, dict[int, float]] = {}
    diagnostics_by_symbol: dict[str, Any] = {}
    for symbol in sorted(set(unique_open_symbols) | set(unique_candidate_symbols)):
        returns, diagnostics = _read_symbol_correlation_returns(
            r,
            symbol,
            generated_utc=generated_utc,
        )
        diagnostics_by_symbol[symbol] = diagnostics
        if returns is not None:
            returns_by_symbol[symbol] = returns
    contexts: dict[str, dict[str, Any]] = {}
    for symbol in unique_candidate_symbols:
        candidate_returns = returns_by_symbol.get(symbol)
        if candidate_returns is None:
            contexts[symbol] = {
                "correlation_exposure_pct": CORRELATION_FAIL_CLOSED_EXPOSURE_PCT,
                "correlation_input_status": diagnostics_by_symbol.get(symbol, {}).get("status", "MISSING_MARKET_CANDLES"),
                "correlation_input_source": "MISSING_CANDIDATE_RETURNS_FAIL_CLOSED",
                "correlation_pair_count": 0,
                "correlation_diagnostics": diagnostics_by_symbol.get(symbol, {}),
            }
            continue
        max_abs_correlation: float | None = None
        pair_count = 0
        for open_symbol in unique_open_symbols:
            if open_symbol == symbol:
                continue
            open_returns = returns_by_symbol.get(open_symbol)
            if open_returns is None:
                continue
            common_times = sorted(set(candidate_returns) & set(open_returns))
            if len(common_times) < CORRELATION_MIN_RETURN_POINTS:
                continue
            correlation = _pearson_correlation(
                [candidate_returns[close_time] for close_time in common_times],
                [open_returns[close_time] for close_time in common_times],
            )
            if correlation is None:
                continue
            pair_count += 1
            abs_correlation = abs(correlation)
            max_abs_correlation = (
                abs_correlation
                if max_abs_correlation is None
                else max(max_abs_correlation, abs_correlation)
            )
        if max_abs_correlation is None:
            if len(unique_open_symbols) == 1 and unique_open_symbols[0] == symbol:
                contexts[symbol] = {
                    "correlation_exposure_pct": 0.0,
                    "correlation_input_status": "ONLY_SAME_SYMBOL_OPEN",
                    "correlation_input_source": "SYMBOL_EXPOSURE_BUDGET_HANDLES_SELF_EXPOSURE",
                    "correlation_pair_count": 0,
                    "correlation_diagnostics": diagnostics_by_symbol.get(symbol, {}),
                }
            else:
                contexts[symbol] = {
                    "correlation_exposure_pct": CORRELATION_FAIL_CLOSED_EXPOSURE_PCT,
                    "correlation_input_status": "INSUFFICIENT_ALIGNED_OPEN_RETURNS",
                    "correlation_input_source": "MISSING_PAIRWISE_RETURNS_FAIL_CLOSED",
                    "correlation_pair_count": pair_count,
                    "correlation_diagnostics": diagnostics_by_symbol.get(symbol, {}),
                }
            continue
        contexts[symbol] = {
            "correlation_exposure_pct": round(max_abs_correlation, 8),
            "correlation_input_status": "READY",
            "correlation_input_source": "MARKET_OHLCV_RETURN_CORRELATION",
            "correlation_pair_count": pair_count,
            "correlation_diagnostics": diagnostics_by_symbol.get(symbol, {}),
        }
    return contexts


def _derive_position_state(existing_ledger: dict[str, Any], symbol: str) -> str:
    """Return the current open position state for one symbol.

    The paper ledger intentionally keeps historical accepted fills for
    reconciliation and trainer feedback. Those historical rows must not be
    treated as current inventory when the strategy router checks whether a new
    long/short transition is valid.
    """
    wanted = symbol.upper()
    candidates: list[dict[str, Any]] = []
    for row in existing_ledger.get("open_positions") or existing_ledger.get("positions") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("symbol") or "").upper() != wanted:
            continue
        state = str(row.get("position_state") or "").upper()
        if state in {"CLOSED_POSITION", "CLOSED", "FLAT", "NO_OPEN_POSITION"}:
            continue
        quantity = _coerce_float(_first_present(row.get("net_quantity"), row.get("quantity")))
        if quantity is not None and abs(quantity) <= 1e-12:
            continue
        candidates.append(row)
    if not candidates:
        return "FLAT"
    sides = {
        str(_first_present(row.get("side"), row.get("selected_action")) or "").lower()
        for row in candidates
    }
    sides.discard("")
    if len(sides) > 1:
        return "INVALID_CONFLICTING_OPEN_POSITIONS"
    candidates.sort(
        key=lambda row: (
            _first_present(
                row.get("generated_utc"),
                row.get("fill_price_utc"),
                row.get("entry_price_utc"),
            )
            or "",
            row.get("signal_id") or "",
        )
    )
    latest = candidates[-1]
    state = str(latest.get("position_state") or "").upper()
    if state in {"LONG", "SHORT", "FLAT"}:
        return state
    side = str(_first_present(latest.get("side"), latest.get("selected_action")) or "").lower()
    if side == "long":
        return "LONG"
    if side == "short":
        return "SHORT"
    return "INVALID_OPEN_POSITION_SIDE_MISSING"


def _read_recent_execution_metrics(r) -> dict[str, Any]:
    ledger = _read_existing_ledger_payload(r)
    accepted = int(ledger.get("accepted_count") or 0)
    blocked = int(ledger.get("blocked_count") or 0)
    shadow = int(ledger.get("shadow_observation_count") or 0)
    raw_outcomes = [
        row
        for row in ledger.get("outcome_labels") or ledger.get("closed_trades") or []
        if isinstance(row, dict)
        and row.get("winner") is not None
        and row.get("realized_pnl_bps") is not None
    ]
    outcomes = [row for row in raw_outcomes if _closed_outcome_is_alpha_complete(row)]
    clean_outcome_ids = {id(row) for row in outcomes}
    dirty_outcomes = [row for row in raw_outcomes if id(row) not in clean_outcome_ids]
    if outcomes:
        wins = sum(1 for row in outcomes if row.get("winner") is True)
        attempts = len(outcomes)
        success_probability = wins / attempts
        metric_source = "V2_PAPER_CLOSED_TRADE_OUTCOMES_ALPHA_COMPLETE"
        sample_status = "ALPHA_COMPLETE_OUTCOME_SAMPLE"
    elif raw_outcomes:
        attempts = 0
        success_probability = None
        metric_source = "INSUFFICIENT_ALPHA_FEEDBACK_OUTCOMES"
        sample_status = "DIRTY_OUTCOMES_QUARANTINED"
    else:
        attempts = accepted + blocked + shadow
        success_probability = 1.0 if attempts <= 0 else accepted / attempts
        metric_source = "V2_PAPER_ACCEPTED_BLOCKED_FALLBACK"
        sample_status = "NO_CLOSED_OUTCOMES_FALLBACK"
    return {
        "accepted_count": accepted,
        "blocked_count": blocked,
        "shadow_observation_count": shadow,
        "closed_trade_outcome_count": len(outcomes),
        "clean_closed_trade_outcome_count": len(outcomes),
        "dirty_closed_trade_outcome_count": len(dirty_outcomes),
        "raw_closed_trade_outcome_count": len(raw_outcomes),
        "execution_success_probability": round(success_probability, 6)
        if success_probability is not None
        else None,
        "execution_success_metric_source": metric_source,
        "execution_success_sample_status": sample_status,
    }


def _closed_outcome_is_alpha_complete(row: dict[str, Any]) -> bool:
    if row.get("winner") is None or row.get("realized_pnl_bps") is None:
        return False
    return all(row.get(field) not in (None, "") for field in REQUIRED_FEEDBACK_FIELDS) and not audit_quality_rejection_reasons(row)


def _read_current_risk_state(r) -> dict[str, Any]:
    ledger = _read_existing_ledger_payload(r)
    portfolio = _read_portfolio_state(r)
    drawdowns: list[float] = []
    portfolio_drawdown = _coerce_float(portfolio.get("current_drawdown_bps"))
    if portfolio_drawdown is not None:
        drawdowns.append(abs(portfolio_drawdown))
    open_rows = [
        row for row in (ledger.get("open_positions") or ledger.get("positions") or [])
        if isinstance(row, dict)
    ]
    for row in open_rows:
        row_drawdown = _coerce_float(
            _first_present(row.get("drawdown_bps"), row.get("max_drawdown_bps"), row.get("mae_bps"))
        )
        if row_drawdown is not None:
            drawdowns.append(abs(row_drawdown))
        unrealized_bps = _coerce_float(row.get("unrealized_pnl_bps"))
        if unrealized_bps is not None and unrealized_bps < 0:
            drawdowns.append(abs(unrealized_bps))
    return {
        "current_drawdown_bps": max(drawdowns) if drawdowns else 0.0,
        "current_drawdown_source": "CURRENT_PORTFOLIO_AND_OPEN_POSITIONS",
        "open_position_count": len(open_rows),
    }


def _build_market_state_envelope(
    *,
    signal: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    return {
        "symbol": _first_present(signal.get("symbol"), prediction.get("symbol")),
        "exchange": _first_present(signal.get("exchange"), prediction.get("exchange"), "unknown"),
        "decision_time": _first_present(
            prediction.get("decision_time"),
            prediction.get("decision_cutoff"),
            prediction.get("feature_cutoff"),
            prediction.get("generated_utc"),
            prediction.get("generated_at"),
            signal.get("decision_time"),
            signal.get("decision_cutoff"),
            signal.get("generated_utc"),
        ),
        "event_time": _first_present(
            prediction.get("source_event_time_utc"),
            prediction.get("event_time"),
            prediction.get("generated_utc"),
        ),
        "available_at": _first_present(
            prediction.get("available_at"),
            prediction.get("generated_utc"),
            prediction.get("generated_at"),
        ),
        "ingested_at": _first_present(
            prediction.get("ingested_at"),
            prediction.get("generated_utc"),
            prediction.get("generated_at"),
        ),
        "feature_cutoff": _first_present(
            prediction.get("feature_cutoff"),
            prediction.get("generated_utc"),
            prediction.get("generated_at"),
        ),
        "prediction_id": _first_present(signal.get("prediction_id"), prediction.get("prediction_id")),
        "timeframe": _first_present(signal.get("timeframe"), prediction.get("timeframe")),
        "market_state_integrity_score": _first_present(
            signal.get("market_state_integrity_score"),
            prediction.get("market_state_integrity_score"),
        ),
        "data_quality_score": _first_present(
            signal.get("market_state_integrity_score"),
            prediction.get("market_state_integrity_score"),
        ),
        "data_quality_flags": list(
            signal.get("market_state_reject_reasons")
            or prediction.get("market_state_reject_reasons")
            or []
        ),
        "confidence_calibrated": _first_present(
            signal.get("confidence_calibrated"),
            prediction.get("confidence_calibrated"),
        ),
        "action_probabilities": _first_present(
            prediction.get("action_probabilities"),
            prediction.get("policy_action_probabilities"),
        ),
        "expected_move_after_cost_bps": _first_present(
            signal.get("expected_move_after_cost_bps"),
            prediction.get("expected_move_after_cost_bps"),
        ),
        "ppo_confidence": _first_present(
            signal.get("confidence_calibrated"),
            prediction.get("confidence_calibrated"),
        ),
        "paper_only": True,
        "mode": "paper",
        "live_allowed": False,
        "paper_major_move_candidate": bool(
            _first_present(
                signal.get("paper_major_move_candidate"),
                prediction.get("paper_major_move_candidate"),
                signal.get("major_move_signal_id"),
                prediction.get("major_move_signal_id"),
            )
        ),
        "major_move_signal_id": _first_present(signal.get("major_move_signal_id"), prediction.get("major_move_signal_id")),
        "major_move_direction": _first_present(
            signal.get("major_move_direction"),
            prediction.get("major_move_direction"),
            signal.get("side"),
            signal.get("selected_action"),
            prediction.get("selected_action"),
        ),
        "major_move_evidence_score": _first_present(
            signal.get("major_move_evidence_score"),
            prediction.get("major_move_evidence_score"),
            signal.get("squeeze_evidence_score"),
            prediction.get("squeeze_evidence_score"),
        ),
        "squeeze_evidence_score": _first_present(signal.get("squeeze_evidence_score"), prediction.get("squeeze_evidence_score")),
    }


def _parse_strategy_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        iso_value = _iso_from_epoch_ms(value)
        if iso_value is None:
            return None
        value = iso_value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        numeric_value = _coerce_float(value)
        if numeric_value is not None:
            iso_value = _iso_from_epoch_ms(numeric_value)
            if iso_value is not None:
                try:
                    parsed = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
                except ValueError:
                    return None
            else:
                return None
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _future_cutoff_offenders(
    *,
    market_state_envelope: dict[str, Any],
    timeframe_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    decision_time_raw = market_state_envelope.get("decision_time")
    decision_time = _parse_strategy_time(decision_time_raw)
    if decision_time is None:
        return []
    offenders: list[dict[str, Any]] = []
    for row in timeframe_rows:
        if not isinstance(row, dict):
            continue
        feature_cutoff_raw = _first_present(row.get("feature_cutoff"), row.get("generated_at"))
        feature_cutoff = _parse_strategy_time(feature_cutoff_raw)
        if feature_cutoff is None or feature_cutoff <= decision_time:
            continue
        offenders.append(
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "prediction_id": row.get("prediction_id"),
                "feature_cutoff": feature_cutoff_raw,
                "decision_time": decision_time_raw,
                "row_decision_time": row.get("decision_time"),
            }
        )
    return offenders


def _point_in_time_timeframe_rows(
    *,
    market_state_envelope: dict[str, Any],
    timeframe_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    decision_time = _parse_strategy_time(
        _first_present(
            market_state_envelope.get("decision_time"),
            market_state_envelope.get("available_at"),
            market_state_envelope.get("generated_utc"),
            market_state_envelope.get("generated_at"),
        )
    )
    if decision_time is None:
        return []
    rows: list[dict[str, Any]] = []
    for row in timeframe_rows:
        if not isinstance(row, dict):
            continue
        row_available_at = _parse_strategy_time(
            _first_present(
                row.get("available_at"),
                row.get("decision_time"),
                row.get("generated_utc"),
                row.get("generated_at"),
            )
        )
        if row_available_at is None:
            continue
        if row_available_at <= decision_time:
            rows.append(row)
    return rows


def _paper_signal_temporal_rejection_reasons(
    *,
    signal: dict[str, Any],
    prediction: dict[str, Any],
    now: datetime,
) -> list[str]:
    reasons: list[str] = []
    freshness = str(
        _first_present(
            signal.get("feature_freshness_state"),
            signal.get("prediction_freshness_state"),
            prediction.get("feature_freshness_state"),
            prediction.get("prediction_freshness_state"),
        )
        or ""
    ).upper()
    if freshness in {"STALE", "EXPIRED"}:
        reasons.append(f"{freshness}_PAPER_SIGNAL")

    signal_generated_raw = _first_present(
        signal.get("generated_utc"),
        signal.get("generated_at"),
        signal.get("available_at"),
        signal.get("generated_est"),
    )
    signal_generated = _parse_strategy_time(signal_generated_raw)
    if (
        signal_generated is not None
        and (now - signal_generated).total_seconds() > PAPER_SIGNAL_STALE_SECONDS
    ):
        reasons.append(f"STALE_SIGNAL_GT_{PAPER_SIGNAL_STALE_SECONDS}s")

    source_status = str(signal.get("source_prediction_status") or "").strip()
    if source_status and source_status not in CURRENT_PREDICTION_STATUSES:
        reasons.append(f"NON_CURRENT_SOURCE_PREDICTION_STATUS:{source_status}")

    source_status_current = source_status in CURRENT_PREDICTION_STATUSES
    signal_is_stale_or_expired = any(
        str(reason).startswith("STALE")
        or str(reason).startswith("EXPIRED")
        for reason in reasons
    )
    if (
        signal.get("prediction_id")
        and not prediction
        and (source_status or signal_generated is not None)
        and (not source_status_current or signal_is_stale_or_expired)
    ):
        reasons.append("SOURCE_PREDICTION_NOT_CURRENT_OR_MISSING")

    return sorted(set(reasons))


def _paper_runtime_market_evidence_rejection_reasons(intent: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if intent.get("entry_price_provenance_present") is not True:
        reasons.append(str(intent.get("entry_price_blocker") or ENTRY_PRICE_BLOCKER_MISSING_FILL))
    decision_time = _parse_strategy_time(_first_present(
        intent.get("entry_feature_decision_time"),
        intent.get("generated_utc"),
        intent.get("generated_at"),
    ))
    for field, reason in (
        ("entry_feature_available_at", "MISSING_ENTRY_FEATURE_AVAILABLE_AT"),
        ("entry_feature_generated_at", "MISSING_ENTRY_FEATURE_GENERATED_AT"),
        ("entry_feature_cutoff", "MISSING_ENTRY_FEATURE_CUTOFF"),
    ):
        parsed = _parse_strategy_time(intent.get(field))
        if parsed is None:
            reasons.append(reason)
        elif decision_time is not None and parsed > decision_time:
            reasons.append(f"{field.upper()}_AFTER_DECISION_TIME")
    if intent.get("entry_feature_candle_closed_confirmed") is not True:
        reasons.append("ENTRY_FEATURE_CANDLE_NOT_CONFIRMED_CLOSED")
    if _coerce_float(intent.get("actual_observed_spread_entry_bps")) is None:
        reasons.append(
            str(
                intent.get("bid_ask_spread_bps_unavailable_reason")
                or "MISSING_OBSERVED_SPREAD_AT_DECISION_TIME"
            )
        )
    expected_slippage_source = str(intent.get("expected_slippage_source") or "")
    if (
        _coerce_float(intent.get("expected_slippage_bps")) is None
        or expected_slippage_source == "CONSERVATIVE_MISSING_SLIPPAGE_BLOCKING_ESTIMATE"
    ):
        reasons.append(
            str(
                intent.get("expected_slippage_unavailable_reason")
                or "MISSING_OBSERVED_OR_MODELED_SLIPPAGE_AT_DECISION_TIME"
            )
        )
    if _coerce_float(intent.get("squeeze_evidence_score")) is None or not intent.get("squeeze_evidence_source"):
        reasons.append(
            str(
                intent.get("squeeze_evidence_unavailable_reason")
                or "MISSING_SOURCED_SQUEEZE_EVIDENCE"
            )
        )
    return sorted(set(reason for reason in reasons if reason))


def _build_volatility_liquidity_state(
    *,
    signal: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    features = prediction.get("features") if isinstance(prediction.get("features"), dict) else {}
    return {
        "timeframe": _first_present(signal.get("timeframe"), prediction.get("timeframe")),
        "volatility": _first_present(
            prediction.get("volatility"),
            prediction.get("volatility_pct"),
            features.get("volatility"),
            features.get("volatility_pct"),
            features.get("true_range_pct"),
        ),
        "bid_ask_spread_bps": _first_present(
            prediction.get("bid_ask_spread_bps"),
            features.get("bid_ask_spread_bps"),
        ),
        "liquidity_score": _first_present(
            prediction.get("coingecko_liquidity_score"),
            prediction.get("defillama_liquidity_score"),
            features.get("coingecko_liquidity_score"),
            features.get("defillama_liquidity_score"),
        ),
    }


def _source_labels_matching(prediction: dict[str, Any], *tokens: str) -> list[str]:
    labels = prediction.get("source_labels")
    if not isinstance(labels, list):
        return []
    lowered_tokens = tuple(token.lower() for token in tokens)
    return [
        str(label)
        for label in labels
        if any(token in str(label).lower() for token in lowered_tokens)
    ]


def _missing_features_matching(prediction: dict[str, Any], *tokens: str) -> list[str]:
    lineage = prediction.get("market_state_source_lineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    missing = lineage.get("missing_feature_names") or prediction.get("missing_feature_names")
    if not isinstance(missing, list):
        return []
    lowered_tokens = tuple(token.lower() for token in tokens)
    return [
        str(name)
        for name in missing
        if any(token in str(name).lower() for token in lowered_tokens)
    ]


def _score01(value: Any) -> float | None:
    parsed = _coerce_float(value)
    if parsed is None:
        return None
    if parsed > 1.0:
        parsed = parsed / 100.0
    return max(0.0, min(1.0, parsed))


def _first_numeric_from(*mappings: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        for key in keys:
            parsed = _coerce_float(mapping.get(key))
            if parsed is not None:
                return parsed
    return None


def _first_numeric_field_from(
    *sources: tuple[str, dict[str, Any]],
    keys: tuple[str, ...],
) -> tuple[float | None, str | None]:
    for source_name, mapping in sources:
        if not isinstance(mapping, dict):
            continue
        for key in keys:
            parsed = _coerce_float(mapping.get(key))
            if parsed is not None:
                return parsed, f"{source_name}.{key}" if source_name else key
    return None, None


def _attach_counterfactual_market_cost_evidence(intent: dict[str, Any]) -> None:
    depth_source = None
    if _coerce_float(intent.get("orderbook_depth_usd")) is not None:
        depth_source = "orderbook_depth_usd"
    elif _coerce_float(intent.get("entry_orderbook_depth_usd")) is not None:
        depth_side = intent.get("entry_orderbook_depth_side")
        depth_source = f"entry_orderbook_depth_usd.{depth_side}" if depth_side else "entry_orderbook_depth_usd"
    elif _coerce_float(intent.get("market_depth_usd")) is not None:
        depth_source = "market_depth_usd"
    elif _coerce_float(intent.get("top_of_book_depth_usd")) is not None:
        depth_source = "top_of_book_depth_usd"
    depth = _coerce_float(_first_present(
        intent.get("orderbook_depth_usd"),
        intent.get("entry_orderbook_depth_usd"),
        intent.get("market_depth_usd"),
        intent.get("top_of_book_depth_usd"),
    ))
    if intent.get("orderbook_depth_usd") in {None, ""} and depth is not None and depth > 0.0:
        intent["orderbook_depth_usd"] = depth
        if intent.get("orderbook_depth_source") in {None, ""} and depth_source is not None:
            intent["orderbook_depth_source"] = depth_source

    source_fields: dict[str, str] = {}
    source_candidates = {
        "actual_observed_spread_entry_bps": (
            intent.get("entry_spread_source"),
            "actual_observed_spread_entry_bps",
        ),
        "expected_slippage_bps": (
            intent.get("expected_slippage_source"),
            "expected_slippage_bps",
        ),
        "fee_bps": (
            intent.get("fee_bps_source"),
            "fee_bps",
        ),
        "expected_funding_bps": (
            intent.get("expected_funding_bps_source"),
            "expected_funding_bps",
        ),
        "orderbook_depth_usd": (
            intent.get("orderbook_depth_source"),
            depth_source,
        ),
    }
    missing: list[str] = []
    for field, missing_reason in COUNTERFACTUAL_MARKET_COST_REQUIREMENTS:
        value = _coerce_float(intent.get(field))
        if value is None or (field == "orderbook_depth_usd" and value <= 0.0):
            missing.append(missing_reason)
            continue
        source = _first_present(*source_candidates[field])
        source_fields[field] = str(source)

    intent["market_cost_evidence_status"] = (
        "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE"
        if not missing
        else "PARTIAL_EXPLICIT_MARKET_COST_EVIDENCE"
    )
    intent["market_cost_evidence_missing_fields"] = missing
    intent["market_cost_evidence_source_fields"] = source_fields
    intent["market_cost_evidence_pit_reject_reasons"] = []
    intent["market_cost_evidence_source_lineage"] = {
        "source": "paper_loop_decision_time_market_cost_capture",
        "decision_time": _first_present(
            intent.get("entry_spread_decision_time"),
            intent.get("entry_feature_decision_time"),
            intent.get("decision_time"),
            intent.get("generated_utc"),
        ),
        "signal_id": intent.get("signal_id"),
        "prediction_id": intent.get("prediction_id"),
        "feature_snapshot_id": intent.get("entry_feature_snapshot_id"),
        "feature_source": intent.get("entry_feature_source"),
        "feature_available_at": intent.get("entry_feature_available_at"),
        "feature_generated_at": intent.get("entry_feature_generated_at"),
        "feature_cutoff": intent.get("entry_feature_cutoff"),
        "entry_spread_available_at": intent.get("entry_spread_available_at"),
        "entry_spread_source": intent.get("entry_spread_source"),
        "orderbook_depth_source": intent.get("orderbook_depth_source"),
        "fee_bps_source": intent.get("fee_bps_source"),
        "expected_funding_bps_source": intent.get("expected_funding_bps_source"),
        "expected_slippage_source": intent.get("expected_slippage_source"),
    }


def _derive_squeeze_evidence(
    *,
    intent: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    features = prediction.get("features") if isinstance(prediction.get("features"), dict) else {}
    direct = _score01(
        _first_present(
            intent.get("squeeze_evidence_score"),
            intent.get("major_move_evidence_score"),
            prediction.get("squeeze_evidence_score"),
            prediction.get("major_move_evidence_score"),
            features.get("squeeze_evidence_score"),
            features.get("major_move_evidence_score"),
        )
    )
    if direct is not None:
        return {
            "score": round(direct, 6),
            "source": "DIRECT_SQUEEZE_OR_MAJOR_MOVE_EVIDENCE_SCORE",
            "components": {"direct_score": round(direct, 6)},
            "unavailable_reason": None,
        }

    liquidation_pressure = _score01(
        _first_numeric_from(
            intent,
            prediction,
            features,
            keys=(
                "liquidation_pressure",
                "liquidation_strength",
                "liquidation_cascade_risk",
                "liquidation_cluster_strength",
            ),
        )
    )
    last_liq_bps = _first_numeric_from(
        intent,
        prediction,
        features,
        keys=("last_liq_bps_24h", "last_liquidation_bps", "liquidation_distance_bps"),
    )
    oi_change_pct = _first_numeric_from(
        intent,
        prediction,
        features,
        keys=("oi_change_pct", "open_interest_change_pct", "open_interest_delta_pct"),
    )
    funding_rate = _first_numeric_from(intent, prediction, features, keys=("funding_rate", "last_funding_rate"))
    orderbook_imbalance = _first_numeric_from(
        intent,
        prediction,
        features,
        keys=("ob_imbalance", "orderbook_imbalance", "depth_imbalance"),
    )
    spread_bps = _first_numeric_from(
        intent,
        prediction,
        features,
        keys=("observed_bid_ask_spread_bps", "bid_ask_spread_bps", "ob_spread_bps", "spread_bps"),
    )

    components: dict[str, float] = {}
    if liquidation_pressure is not None:
        components["liquidation_pressure"] = liquidation_pressure
    if last_liq_bps is not None:
        components["liquidation_distance_or_recent_liq"] = max(0.0, min(1.0, abs(last_liq_bps) / 500.0))
    if oi_change_pct is not None:
        components["open_interest_change"] = max(0.0, min(1.0, abs(oi_change_pct) * 20.0))
    if funding_rate is not None:
        components["funding_extreme"] = max(0.0, min(1.0, abs(funding_rate) * 2500.0))
    if orderbook_imbalance is not None:
        components["orderbook_imbalance"] = max(0.0, min(1.0, abs(orderbook_imbalance) * 2.0))
    if spread_bps is not None:
        components["spread_stress"] = max(0.0, min(1.0, (abs(spread_bps) - 5.0) / 45.0))

    if not components:
        return {
            "score": None,
            "source": None,
            "components": components,
            "unavailable_reason": "MISSING_SQUEEZE_LIQUIDATION_OI_ORDERBOOK_EVIDENCE",
        }
    nonzero = {key: value for key, value in components.items() if value > 0.0}
    score = (
        nonzero.get("liquidation_pressure", 0.0) * 0.30
        + nonzero.get("liquidation_distance_or_recent_liq", 0.0) * 0.18
        + nonzero.get("open_interest_change", 0.0) * 0.16
        + nonzero.get("funding_extreme", 0.0) * 0.12
        + nonzero.get("orderbook_imbalance", 0.0) * 0.16
        + nonzero.get("spread_stress", 0.0) * 0.08
    )
    return {
        "score": round(max(0.0, min(1.0, score)), 6),
        "source": "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        "components": {key: round(value, 6) for key, value in components.items()},
        "unavailable_reason": None,
    }


def _model_expected_slippage_bps(
    *,
    spread_bps: float,
    volatility_bps: float | None,
    liquidity_score: float | None,
) -> float:
    volatility_component = max(0.0, float(volatility_bps or 0.0)) * 0.015
    modeled = max(0.25, abs(spread_bps) * 0.50 + volatility_component)
    if liquidity_score is not None:
        if liquidity_score < 0.25:
            modeled *= 2.0
        elif liquidity_score < 0.50:
            modeled *= 1.4
    return round(min(50.0, modeled), 6)


def _depth_liquidity_score(depth_usd: float | None) -> float | None:
    if depth_usd is None or depth_usd <= 0.0:
        return None
    if depth_usd >= 250_000.0:
        return 1.0
    if depth_usd >= 100_000.0:
        return 0.9
    if depth_usd >= 50_000.0:
        return 0.8
    if depth_usd >= 25_000.0:
        return 0.65
    if depth_usd >= 10_000.0:
        return 0.5
    if depth_usd >= 5_000.0:
        return 0.35
    return 0.2


def _spread_liquidity_score(spread_bps: float | None) -> float | None:
    if spread_bps is None:
        return None
    spread = max(0.0, abs(spread_bps))
    if spread <= 2.0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - ((spread - 2.0) / 48.0)))


def _derive_allocator_liquidity_score(
    *,
    intent: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    features: dict[str, Any],
    market_microstructure: dict[str, Any],
    spread_bps: float | None,
    feature_source_name: str,
) -> tuple[float, str, str]:
    explanation = intent.get("strategy_explanation")
    explanation = explanation if isinstance(explanation, dict) else {}
    explicit, explicit_source = _first_numeric_field_from(
        ("intent", intent),
        ("signal", signal),
        ("prediction", prediction),
        (feature_source_name, features),
        ("market_microstructure", market_microstructure),
        ("strategy_explanation", explanation),
        keys=(
            "liquidity_score",
            "market_liquidity_score",
            "coingecko_liquidity_score",
            "defillama_liquidity_score",
            "depth_liquidity_score",
        ),
    )
    explicit_score = _score01(explicit)
    if explicit_score is not None:
        return explicit_score, explicit_source or "explicit_liquidity_score", "EXPLICIT_LIQUIDITY_SCORE"
    depth, depth_source = _first_numeric_field_from(
        ("market_microstructure", market_microstructure),
        ("intent", intent),
        ("signal", signal),
        ("prediction", prediction),
        (feature_source_name, features),
        keys=(
            "entry_orderbook_depth_usd",
            "orderbook_depth_usd",
            "top_of_book_depth_usd",
            "market_depth_usd",
            "depth_usd",
            "available_depth_usd",
            "one_percent_depth_usd",
        ),
    )
    depth_score = _depth_liquidity_score(depth)
    spread_score = _spread_liquidity_score(spread_bps)
    if depth_score is not None and spread_score is not None:
        return (
            round(min(depth_score, spread_score), 8),
            f"{depth_source or 'orderbook_depth_usd'}+spread_bps",
            "DERIVED_FROM_ORDERBOOK_DEPTH_AND_SPREAD",
        )
    if depth_score is not None:
        return round(depth_score, 8), depth_source or "orderbook_depth_usd", "DERIVED_FROM_ORDERBOOK_DEPTH"
    if spread_score is not None:
        return round(spread_score, 8), "spread_bps", "DERIVED_FROM_SPREAD_ONLY"
    return 1.0, "DEFAULT_NO_LIQUIDITY_EVIDENCE", "DEFAULT_NEUTRAL_LIQUIDITY_SCORE"


def _normalize_regime_score(value: Any) -> float | None:
    parsed = _coerce_float(value)
    if parsed is None:
        return None
    if parsed > 2.0:
        parsed = parsed / 100.0
    return max(0.2, min(1.25, parsed))


def _derive_regime_score_from_labels(labels: list[Any], selected_mode: Any) -> tuple[float | None, str | None]:
    tokens = {str(label).strip().upper() for label in labels if str(label).strip()}
    mode = str(selected_mode or "").strip().lower()
    if "NO_TRADE" in tokens or "BLOCKED" in tokens or mode == "no_trade_mode":
        return 0.2, "REGIME_LABEL_NO_TRADE_OR_BLOCKED"
    if tokens.intersection({"CHOP", "CHOPPY", "SIDEWAYS", "RANGE_BOUND", "RANGE"}):
        return 0.75, "REGIME_LABEL_CHOP_RANGE"
    if tokens.intersection({"HIGH_VOL", "HIGH_VOLATILITY", "VOLATILE", "LIQUIDATION_RISK"}):
        return 0.85, "REGIME_LABEL_HIGH_VOLATILITY"
    if "MEAN_REVERSION" in tokens or "mean_reversion" in mode:
        return 0.9, "REGIME_LABEL_MEAN_REVERSION"
    if tokens.intersection({"TREND", "MOMENTUM", "BREAKOUT"}) or mode in {"trend_following", "breakout"}:
        return 1.0, "REGIME_LABEL_TREND_MOMENTUM"
    return None, None


def _derive_allocator_regime_score(
    *,
    intent: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    features: dict[str, Any],
    feature_source_name: str,
) -> tuple[float, str, str]:
    explanation = intent.get("strategy_explanation")
    explanation = explanation if isinstance(explanation, dict) else {}
    explicit, explicit_source = _first_numeric_field_from(
        ("intent", intent),
        ("signal", signal),
        ("prediction", prediction),
        (feature_source_name, features),
        ("strategy_explanation", explanation),
        keys=("regime_score", "market_regime_score", "strategy_regime_score"),
    )
    explicit_score = _normalize_regime_score(explicit)
    if explicit_score is not None:
        return explicit_score, explicit_source or "explicit_regime_score", "EXPLICIT_REGIME_SCORE"
    raw_labels = _first_present(
        intent.get("strategy_regime_labels"),
        signal.get("strategy_regime_labels"),
        prediction.get("strategy_regime_labels"),
        [],
    )
    if isinstance(raw_labels, str):
        labels = [item.strip() for item in raw_labels.split(",") if item.strip()]
    else:
        labels = list(raw_labels or [])
    derived, reason = _derive_regime_score_from_labels(
        labels,
        _first_present(
            intent.get("strategy_router_selected_mode"),
            intent.get("strategy_selected_mode"),
            signal.get("strategy_router_selected_mode"),
            signal.get("strategy_selected_mode"),
        ),
    )
    if derived is not None:
        return derived, "strategy_router_regime_labels", reason or "DERIVED_FROM_STRATEGY_REGIME"
    return 1.0, "DEFAULT_NO_REGIME_EVIDENCE", "DEFAULT_NEUTRAL_REGIME_SCORE"


def _attach_trainer_feedback_entry_context(
    *,
    intent: dict[str, Any],
    prediction: dict[str, Any],
    strategy_router: dict[str, Any],
    allocation: dict[str, Any],
    portfolio_context: dict[str, float],
) -> None:
    explanation = strategy_router.get("explanation")
    explanation = explanation if isinstance(explanation, dict) else {}
    allocation_inputs = allocation.get("model_inputs")
    allocation_inputs = allocation_inputs if isinstance(allocation_inputs, dict) else {}
    regime_labels = list(strategy_router.get("regime_labels") or [])
    regime = ",".join(str(item) for item in regime_labels) if regime_labels else str(
        strategy_router.get("selected_mode") or "UNKNOWN_REGIME"
    )
    selected_mode = str(strategy_router.get("selected_mode") or "UNKNOWN_STRATEGY")
    intent.setdefault("strategy_id", selected_mode)
    intent.setdefault("strategy_family", selected_mode)
    intent.setdefault("strategy_subtype", selected_mode)
    intent.setdefault("strategy_selected_mode", selected_mode)
    intent.setdefault("entry_reason", selected_mode)
    intent.setdefault("hedge_state", "NO_HEDGE")
    intent.setdefault("hedge_reason", "NO_HEDGE_CONTEXT")
    intent.setdefault("drawdown_at_entry", portfolio_context["drawdown_bps"])
    intent.setdefault("drawdown_bps", portfolio_context["drawdown_bps"])
    intent.setdefault("market_regime_at_entry", regime)
    intent.setdefault(
        "liquidity_zone_context",
        {
            "source": "V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
            "liquidity_score": _first_present(
                explanation.get("liquidity_score"),
                allocation_inputs.get("liquidity_score"),
            ),
            "source_labels": _source_labels_matching(prediction, "liquid", "orderbook"),
            "missing_feature_names": _missing_features_matching(prediction, "liquid", "wall"),
        },
    )
    intent.setdefault(
        "liquidation_distance_context",
        {
            "source": "V2_PREDICTION_SOURCE_LINEAGE",
            "source_labels": _source_labels_matching(prediction, "liquidation"),
            "missing_feature_names": _missing_features_matching(prediction, "liquidation"),
        },
    )
    intent.setdefault("liquidation_context", intent.get("liquidation_distance_context"))
    intent.setdefault(
        "microstructure_context",
        {
            "source": _first_present(
                intent.get("entry_spread_source"),
                "V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
            ),
            "bid_ask_spread_bps": _first_present(
                intent.get("observed_bid_ask_spread_bps"),
                explanation.get("bid_ask_spread_bps"),
            ),
            "orderbook_imbalance": intent.get("orderbook_imbalance"),
            "entry_spread_available_at": intent.get("entry_spread_available_at"),
            "entry_spread_decision_time": intent.get("entry_spread_decision_time"),
            "bid_ask_spread_bps_fallback": bool(intent.get("bid_ask_spread_bps_fallback")),
            "bid_ask_spread_bps_unavailable_reason": intent.get("bid_ask_spread_bps_unavailable_reason"),
            "volatility": explanation.get("volatility"),
            "source_labels": _source_labels_matching(prediction, "microstructure", "orderbook"),
            "missing_feature_names": _missing_features_matching(
                prediction,
                "microstructure",
                "order_flow",
                "tape",
                "spread",
            ),
        },
    )
    intent.setdefault(
        "oi_funding_context",
        {
            "source": "V2_PREDICTION_SOURCE_LINEAGE",
            "source_labels": _source_labels_matching(prediction, "open_interest", "funding", "long_short"),
            "missing_feature_names": _missing_features_matching(
                prediction,
                "open_interest",
                "funding",
                "long_short",
            ),
        },
    )
    intent.setdefault(
        "public_intel_context",
        {
            "source": "V2_PREDICTION_SOURCE_LINEAGE",
            "source_labels": _source_labels_matching(prediction, "public_intel", "news", "sentiment"),
            "missing_feature_names": _missing_features_matching(
                prediction,
                "public_intel",
                "news",
                "sentiment",
            ),
        },
    )
    if intent.get("major_move_signal_id") in (None, ""):
        intent["major_move_signal_id"] = prediction.get("major_move_signal_id")
    squeeze = _derive_squeeze_evidence(intent=intent, prediction=prediction)
    if intent.get("squeeze_evidence_score") in (None, ""):
        intent["squeeze_evidence_score"] = squeeze["score"]
    if intent.get("squeeze_evidence_source") in (None, ""):
        intent["squeeze_evidence_source"] = squeeze["source"]
    if intent.get("squeeze_evidence_components") in (None, ""):
        intent["squeeze_evidence_components"] = squeeze["components"]
    if intent.get("squeeze_evidence_unavailable_reason") in (None, ""):
        intent["squeeze_evidence_unavailable_reason"] = squeeze["unavailable_reason"]
    intent.setdefault("future_window_label_source", "closed_trade_outcome")


def _apply_strategy_size_multiplier(intent: dict[str, Any], multiplier: float | None) -> None:
    if intent.get("paper_allocation_block_reason") not in (None, ""):
        intent["strategy_size_multiplier_skipped_reason"] = "ADAPTIVE_ALLOCATION_BLOCKED_OR_INCOMPLETE"
        return
    if multiplier is None:
        return
    try:
        factor = float(multiplier)
    except (TypeError, ValueError):
        return
    if factor <= 0 or factor >= 0.999999:
        return
    for key in ("quantity", "notional", "notional_usdt"):
        value = _coerce_float(intent.get(key))
        if value is not None:
            intent[key] = round(value * factor, 10)
    intent["paper_sizing_complete"] = (
        _coerce_float(intent.get("quantity")) is not None
        and _coerce_float(intent.get("notional")) is not None
        and _coerce_float(intent.get("entry_price")) is not None
    )
    intent["strategy_size_multiplier_applied"] = round(factor, 6)
    source = str(intent.get("paper_sizing_source") or "")
    if source:
        intent["paper_sizing_source"] = f"{source}|STRATEGY_ROUTER"
    _rescale_adaptive_accounting_to_actual_notional(intent)


def _rescale_adaptive_accounting_to_actual_notional(intent: dict[str, Any]) -> None:
    if intent.get("paper_sizing_complete") is not True:
        return
    allocation = intent.get("adaptive_allocation") if isinstance(intent.get("adaptive_allocation"), dict) else {}
    actual_notional = _coerce_float(_first_present(intent.get("notional"), intent.get("notional_usdt")))
    planned_notional = _coerce_float(_first_present(intent.get("gross_notional_usd"), allocation.get("gross_notional_usd")))
    if actual_notional is None or planned_notional is None or actual_notional <= 0.0 or planned_notional <= 0.0:
        return
    ratio = actual_notional / planned_notional
    if ratio <= 0.0 or abs(ratio - 1.0) <= 1e-9:
        return

    intent["gross_notional_usd"] = round(actual_notional, 8)
    leverage = _coerce_float(
        _first_present(
            intent.get("effective_leverage"),
            allocation.get("effective_leverage"),
            intent.get("recommended_leverage"),
            allocation.get("recommended_leverage"),
        )
    )
    allocated_margin = None
    if leverage is not None and leverage > 0.0:
        allocated_margin = round(actual_notional / leverage, 8)
        intent["allocated_margin_usd"] = allocated_margin
    for field in (
        "risk_budget_usd",
        "expected_fees_usd",
        "expected_slippage_usd",
        "expected_funding_usd",
        "expected_net_pnl_usd",
        "expected_shortfall_usd",
        "hedge_budget_usd",
    ):
        value = _coerce_float(_first_present(intent.get(field), allocation.get(field)))
        if value is not None:
            intent[field] = round(value * ratio, 8)
    if allocation:
        allocation["target_notional_usdt"] = round(actual_notional, 8)
        allocation["gross_notional_usd"] = round(actual_notional, 8)
        quantity = _coerce_float(intent.get("quantity"))
        if quantity is not None and quantity > 0.0:
            allocation["target_quantity"] = round(quantity, 10)
        if allocated_margin is not None:
            allocation["allocated_margin_usd"] = allocated_margin
        for field in (
            "risk_budget_usd",
            "expected_fees_usd",
            "expected_slippage_usd",
            "expected_funding_usd",
            "expected_net_pnl_usd",
            "expected_shortfall_usd",
            "hedge_budget_usd",
            "risk_budget_pct",
            "risk_budget_pct_of_equity",
            "risk_budget_pct_of_available_margin",
        ):
            value = _coerce_float(allocation.get(field))
            if value is not None:
                allocation[field] = round(value * ratio, 8)
        model_inputs = allocation.get("model_inputs")
        if isinstance(model_inputs, dict) and allocated_margin is not None:
            model_inputs["selected_allocated_margin_usd"] = allocated_margin
    intent["adaptive_capital_accounting_adjusted_to_actual_notional"] = True
    intent["adaptive_capital_accounting_adjustment_ratio"] = round(ratio, 8)


def _lineage_ids(signal: dict[str, Any], symbol: str) -> dict[str, str]:
    prediction_id = str(_first_present(
        signal.get("prediction_id"),
        signal.get("source_prediction_id"),
        signal.get("winner_proposal_id"),
        f"v2_paper_prediction_{symbol}",
    ))
    signal_id = str(_first_present(signal.get("signal_id"), f"sig_{prediction_id}"))
    risk_decision_id = str(_first_present(signal.get("risk_decision_id"), f"paper_risk_{prediction_id}"))
    orchestrator_decision_id = str(_first_present(signal.get("orchestrator_decision_id"), f"paper_orch_{prediction_id}"))
    return {
        "signal_id": signal_id,
        "prediction_id": prediction_id,
        "risk_decision_id": risk_decision_id,
        "orchestrator_decision_id": orchestrator_decision_id,
    }


def _missing_adaptive_allocation_fields(allocation: dict[str, Any]) -> list[str]:
    missing_fields: list[str] = []
    for field in ADAPTIVE_PAPER_REQUIRED_ALLOCATION_FIELDS:
        value = allocation.get(field)
        if field == "capital_allocation_reason":
            value = _first_present(value, allocation.get("final_size_reason"))
        if value in (None, ""):
            missing_fields.append(field)
    model_inputs = allocation.get("model_inputs") if isinstance(allocation.get("model_inputs"), dict) else {}
    if not (
        model_inputs.get("selected_leverage") is not None
        or model_inputs.get("leverage_target") is not None
        or model_inputs.get("raw_leverage_target") is not None
        or model_inputs.get("leverage_selection_reason") not in (None, "")
    ):
        missing_fields.append("leverage_selection_model_input")
    if not (
        model_inputs.get("selected_margin_mode") not in (None, "")
        or model_inputs.get("margin_mode_selection_reason") not in (None, "")
    ):
        missing_fields.append("margin_mode_selection_model_input")
    if not (
        model_inputs.get("selected_hedge_budget_pct_of_risk") is not None
        or model_inputs.get("hedge_budget_selection_reason") not in (None, "")
    ):
        missing_fields.append("hedge_budget_selection_model_input")
    return missing_fields


def _default_margin_mode_selection_reason(margin_mode: Any) -> str:
    value = str(margin_mode or "")
    if value in {"cross", "cross_paper_simulated"}:
        return "paper_cross_margin_simulated_for_high_edge_low_portfolio_pressure"
    if value in {"isolated", "isolated_paper_simulated"}:
        return "isolated_limits_tail_contagion_for_current_risk"
    return "recommended_margin_mode_selected_by_adaptive_allocator"


def _ensure_margin_mode_selection_model_input(allocation: dict[str, Any]) -> None:
    model_inputs = allocation.get("model_inputs")
    if not isinstance(model_inputs, dict):
        return
    has_existing_selection_attribution = any(
        model_inputs.get(field) not in (None, "")
        for field in (
            "selected_leverage",
            "leverage_target",
            "raw_leverage_target",
            "leverage_selection_reason",
            "selected_hedge_budget_pct_of_risk",
            "hedge_budget_selection_reason",
        )
    )
    if not has_existing_selection_attribution:
        return
    margin_mode = _first_present(
        model_inputs.get("selected_margin_mode"),
        allocation.get("selected_margin_mode"),
        allocation.get("recommended_margin_mode"),
    )
    if margin_mode in (None, ""):
        return
    model_inputs.setdefault("selected_margin_mode", margin_mode)
    model_inputs.setdefault(
        "margin_mode_selection_reason",
        _first_present(
            allocation.get("margin_mode_selection_reason"),
            _default_margin_mode_selection_reason(margin_mode),
        ),
    )


def _set_allocation_default_from_intent(
    allocation: dict[str, Any],
    intent: dict[str, Any],
    target_field: str,
    *intent_fields: str,
) -> None:
    if allocation.get(target_field) not in (None, ""):
        return
    source_fields = intent_fields or (target_field,)
    for source_field in source_fields:
        value = intent.get(source_field)
        if value not in (None, ""):
            allocation[target_field] = value
            return


def _attach_paper_allocation_decision_context(
    intent: dict[str, Any],
    allocation: dict[str, Any],
) -> None:
    allocation.setdefault("selector_policy_fingerprint", OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT)
    allocation.setdefault("frozen_selector_fingerprint", OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT)
    allocation.setdefault("candidate_selected_before_outcome", True)
    allocation.setdefault("future_labels_used_as_features", False)
    allocation.setdefault("paper_only", True)
    allocation.setdefault("places_real_order", False)
    allocation.setdefault("live_order", False)
    allocation.setdefault("test_order", False)
    allocation.setdefault("leverage_mutation", False)
    allocation.setdefault("margin_mode_mutation", False)
    allocation.setdefault(
        "paper_allocation_decision_context_source",
        "paper_intent_decision_time_context_before_outcome",
    )

    for field in (
        "source_intent_id",
        "intent_id",
        "symbol",
        "timeframe",
        "side",
        "selected_action",
        "confidence_raw",
        "confidence_calibrated",
        "selected_action_probability",
        "expected_move_bps",
        "expected_move_after_cost_bps",
        "action_probabilities",
        "policy_value",
        "value_baseline",
        "prediction_score_source",
        "prediction_score_missing_reason",
        "decision_id",
        "signal_id",
        "source_prediction_id",
        "prediction_id",
        "risk_decision_id",
        "orchestrator_decision_id",
        "feature_snapshot_id",
        "mtf_snapshot_id",
        "feature_cutoff",
        "decision_time",
        "available_at",
        "entry_feature_snapshot_id",
        "entry_feature_available_at",
        "entry_feature_generated_at",
        "entry_feature_cutoff",
        "entry_feature_decision_time",
        "entry_feature_source",
        "entry_feature_candle_closed_confirmed",
        "model_version",
        "checkpoint_id",
        "source_hashes",
        "feature_vector_hash",
        "input_feature_hash",
        "trainer_source",
        "model_id",
        "strategy_id",
        "strategy_family",
        "strategy_subtype",
        "strategy_selected_mode",
        "strategy_router_selected_mode",
        "strategy_size_adjustment_mode",
        "strategy_regime_labels",
        "market_state_id",
        "market_state_integrity_score",
        "valid_for_paper",
        "market_state_reject_reasons",
        "entry_atr_bps",
        "atr_bps",
        "volatility_bps",
        "liquidity_score",
        "regime_score",
        "allocator_liquidity_score",
        "allocator_liquidity_score_source",
        "allocator_liquidity_score_reason",
        "allocator_regime_score",
        "allocator_regime_score_source",
        "allocator_regime_score_reason",
        "correlation_exposure_pct",
        "correlation_input_source",
        "correlation_input_status",
        "correlation_pair_count",
        "actual_observed_spread_entry_bps",
        "observed_bid_ask_spread_bps",
        "bid_ask_spread_bps",
        "entry_spread_source",
        "entry_spread_available_at",
        "entry_spread_decision_time",
        "expected_slippage_bps",
        "expected_slippage_source",
        "fee_bps",
        "fee_bps_source",
        "expected_funding_bps",
        "expected_funding_bps_source",
        "funding_rate",
        "funding_interval_seconds",
        "orderbook_depth_usd",
        "entry_orderbook_depth_usd",
        "entry_orderbook_depth_side",
        "bid_depth_usd",
        "ask_depth_usd",
        "top_of_book_depth_usd",
        "market_depth_usd",
        "orderbook_depth_source",
        "orderbook_imbalance",
        "price_target",
        "price_target_after_cost",
        "price_target_high",
        "price_target_low",
        "live_gate",
    ):
        _set_allocation_default_from_intent(allocation, intent, field)

    _set_allocation_default_from_intent(allocation, intent, "action", "selected_action", "side")
    _set_allocation_default_from_intent(allocation, intent, "strategy", "strategy_id", "strategy_family")
    _set_allocation_default_from_intent(
        allocation,
        intent,
        "generated_at",
        "generated_at",
        "entry_feature_generated_at",
    )
    _set_allocation_default_from_intent(
        allocation,
        intent,
        "entry_spread_bps",
        "entry_spread_bps",
        "actual_observed_spread_entry_bps",
        "observed_bid_ask_spread_bps",
        "bid_ask_spread_bps",
    )
    _set_allocation_default_from_intent(
        allocation,
        intent,
        "margin_mode",
        "margin_mode",
        "margin_mode_simulated",
    )
    if allocation.get("margin_mode") in (None, "") and allocation.get("recommended_margin_mode") not in (None, ""):
        allocation["margin_mode"] = allocation.get("recommended_margin_mode")


def _attach_paper_sizing(intent: dict[str, Any], allocation: dict[str, Any]) -> None:
    price = _coerce_float(_first_present(intent.get("fill_price"), intent.get("entry_price"), intent.get("price")))
    decision = str(allocation.get("allocator_decision") or "")
    notional = _coerce_float(allocation.get("target_notional_usdt"))
    quantity = _coerce_float(allocation.get("target_quantity"))
    _ensure_margin_mode_selection_model_input(allocation)
    _attach_paper_allocation_decision_context(intent, allocation)
    intent["adaptive_allocation"] = allocation
    intent["adaptive_capital_policy_version"] = allocation.get("adaptive_capital_policy_version")
    if intent["adaptive_capital_policy_version"]:
        policy_activated_at = _first_present(
            intent.get("policy_activated_at"),
            allocation.get("policy_activated_at"),
            intent.get("fill_price_utc"),
            intent.get("generated_utc"),
            intent.get("entry_price_utc"),
        )
        if policy_activated_at not in (None, ""):
            intent["policy_activated_at"] = policy_activated_at
            allocation["policy_activated_at"] = policy_activated_at
    model_inputs = allocation.get("model_inputs") if isinstance(allocation.get("model_inputs"), dict) else {}
    expected_funding_bps = _coerce_float(_first_present(
        intent.get("expected_funding_bps"),
        intent.get("funding_bps"),
        intent.get("funding_rate_bps"),
        allocation.get("expected_funding_bps"),
        model_inputs.get("expected_funding_bps"),
        model_inputs.get("funding_bps"),
        model_inputs.get("funding_rate_bps"),
    ))
    funding_rate = _coerce_float(_first_present(
        intent.get("funding_rate"),
        allocation.get("funding_rate"),
        model_inputs.get("funding_rate"),
    ))
    if funding_rate is None and expected_funding_bps is not None:
        funding_rate = expected_funding_bps / 10000.0
    if expected_funding_bps is None and funding_rate is not None:
        expected_funding_bps = funding_rate * 10000.0
    if expected_funding_bps is not None:
        intent["expected_funding_bps"] = expected_funding_bps
        allocation.setdefault("expected_funding_bps", expected_funding_bps)
        model_inputs.setdefault("expected_funding_bps", expected_funding_bps)
    if funding_rate is not None:
        intent["funding_rate"] = funding_rate
        model_inputs.setdefault("funding_rate", funding_rate)
    funding_interval_seconds = _coerce_float(_first_present(
        intent.get("funding_interval_seconds"),
        allocation.get("funding_interval_seconds"),
        model_inputs.get("funding_interval_seconds"),
    ))
    if funding_interval_seconds is not None and (funding_rate is not None or expected_funding_bps is not None):
        intent["funding_interval_seconds"] = funding_interval_seconds
        model_inputs.setdefault("funding_interval_seconds", funding_interval_seconds)
    for field in (
        "allocator_liquidity_score",
        "allocator_liquidity_score_source",
        "allocator_liquidity_score_reason",
        "allocator_regime_score",
        "allocator_regime_score_source",
        "allocator_regime_score_reason",
    ):
        value = intent.get(field)
        if value not in (None, ""):
            allocation.setdefault(field, value)
            model_inputs.setdefault(field, value)
    if model_inputs:
        allocation["model_inputs"] = model_inputs
    intent["allocation_id"] = allocation.get("allocation_id")
    intent["allocator_decision"] = decision
    intent["allocator_reason"] = allocation.get("final_size_reason")
    intent["capital_allocation_reason"] = allocation.get("capital_allocation_reason") or allocation.get("final_size_reason")
    for field in (
        "risk_budget_usd",
        "gross_notional_usd",
        "allocated_margin_usd",
        "recommended_leverage",
        "effective_leverage",
        "recommended_margin_mode",
        "stop_distance_bps",
        "liquidation_price_estimate",
        "liquidation_buffer_bps",
        "expected_fees_usd",
        "expected_slippage_usd",
        "expected_funding_usd",
        "expected_net_pnl_usd",
        "expected_shortfall_usd",
        "hedge_budget_usd",
    ):
        if field in allocation:
            intent[field] = allocation.get(field)
    if allocation.get("recommended_margin_mode") is not None:
        intent["margin_mode_simulated"] = allocation.get("recommended_margin_mode")
    if decision not in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}:
        intent["paper_sizing_source"] = "V2_ADAPTIVE_ALLOCATOR_BLOCKED"
        intent["paper_sizing_complete"] = False
        intent["paper_allocation_block_reason"] = decision or "ALLOCATOR_DECISION_MISSING"
        return
    missing_fields = _missing_adaptive_allocation_fields(allocation)
    if missing_fields:
        intent["paper_sizing_source"] = "V2_ADAPTIVE_ALLOCATOR_INCOMPLETE_ATTRIBUTION"
        intent["paper_sizing_complete"] = False
        intent["paper_allocation_block_reason"] = ADAPTIVE_ALLOCATION_ATTRIBUTION_BLOCK_REASON
        intent["paper_allocation_missing_fields"] = missing_fields
        return
    if quantity is None and notional is not None and price is not None and price > 0:
        quantity = abs(notional / price)
    elif notional is None and quantity is not None and price is not None and price > 0:
        notional = abs(quantity * price)
    intent["paper_sizing_source"] = PAPER_SIZING_SOURCE_ADAPTIVE
    if quantity is not None:
        intent["quantity"] = abs(float(quantity))
    if notional is not None:
        intent["notional"] = abs(float(notional))
        intent["notional_usdt"] = abs(float(notional))
    intent["paper_sizing_complete"] = (
        _coerce_float(intent.get("quantity")) is not None
        and _coerce_float(intent.get("notional")) is not None
        and price is not None
        and price > 0
    )


def _build_allocation_input(
    *,
    intent: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    portfolio_context: dict[str, float],
    symbol_exposures: dict[str, float],
    total_exposure: float,
    market_microstructure: dict[str, Any] | None = None,
    correlation_contexts_by_symbol: dict[str, dict[str, Any]] | None = None,
):
    from v2.backend.app.services.adaptive_capital_allocator import AllocationInput

    symbol = str(intent.get("symbol") or "").upper()
    price = _coerce_float(_first_present(intent.get("fill_price"), intent.get("entry_price"), signal.get("price_target")))
    confidence = _coerce_float(_first_present(
        intent.get("confidence_calibrated"),
        signal.get("confidence_calibrated"),
        signal.get("confidence"),
        prediction.get("confidence_calibrated"),
    ))
    expected_move = _coerce_float(_first_present(
        intent.get("expected_move_after_cost_bps"),
        signal.get("expected_move_after_cost_bps"),
        prediction.get("expected_move_after_cost_bps"),
    ))
    market_score = _coerce_float(_first_present(
        intent.get("market_state_integrity_score"),
        signal.get("market_state_integrity_score"),
        prediction.get("market_state_integrity_score"),
    ))
    features = prediction.get("features") if isinstance(prediction.get("features"), dict) else {}
    market_microstructure = market_microstructure if isinstance(market_microstructure, dict) else {}
    atr_bps = atr_bps_from_payloads(
        intent,
        prediction,
        signal,
        features,
        price=price,
    )
    if atr_bps is not None:
        intent["entry_atr_bps"] = atr_bps
        intent["atr_bps"] = atr_bps
    volatility = _coerce_float(_first_present(
        prediction.get("volatility_bps"),
        signal.get("volatility_bps"),
        atr_bps,
    ))
    if volatility is None:
        volatility_pct = _coerce_float(_first_present(
            prediction.get("volatility_pct"),
            features.get("volatility_pct"),
            features.get("true_range_pct"),
        ))
        volatility = (volatility_pct or 0.005) * 10000.0
    action = str(intent.get("side") or signal.get("side") or signal.get("action") or "long").lower()
    upstream_spread = _coerce_float(
        _first_present(
            prediction.get("bid_ask_spread_bps"),
            signal.get("bid_ask_spread_bps"),
            features.get("bid_ask_spread_bps"),
        )
    )
    orderbook_spread = _coerce_float(
        _first_present(
            market_microstructure.get("bid_ask_spread_bps"),
            market_microstructure.get("spread_bps"),
        )
    )
    if orderbook_spread is not None:
        spread = orderbook_spread
        spread_source = str(
            market_microstructure.get("source") or ENTRY_SPREAD_SOURCE_V2_ORDERBOOK
        )
        if upstream_spread is not None:
            intent["upstream_reported_spread_bps"] = upstream_spread
            intent["upstream_reported_spread_source"] = "V2_PREDICTION_OR_SIGNAL_MICROSTRUCTURE"
            intent["entry_spread_replaced_by_orderbook"] = True
    else:
        spread = upstream_spread
        spread_source = "V2_PREDICTION_OR_SIGNAL_MICROSTRUCTURE" if spread is not None else None
    if spread is None:
        intent["observed_bid_ask_spread_bps"] = None
        intent["actual_observed_spread_entry_bps"] = None
        intent["bid_ask_spread_bps_fallback"] = True
        intent["bid_ask_spread_bps_unavailable_reason"] = "MISSING_OBSERVED_SPREAD_AT_DECISION_TIME"
        spread_for_allocator = max(12.0, abs(float(expected_move or 0.0)) + 1.0)
    else:
        intent["observed_bid_ask_spread_bps"] = spread
        intent["actual_observed_spread_entry_bps"] = spread
        intent["bid_ask_spread_bps"] = spread
        intent["entry_spread_source"] = spread_source
        intent["entry_spread_available_at"] = market_microstructure.get("entry_spread_available_at")
        intent["entry_spread_decision_time"] = market_microstructure.get("entry_spread_decision_time") or _utc_iso()
        if market_microstructure.get("orderbook_imbalance") is not None:
            intent["orderbook_imbalance"] = market_microstructure.get("orderbook_imbalance")
        for depth_field in (
            "bid_depth_usd",
            "ask_depth_usd",
            "orderbook_depth_usd",
            "top_of_book_depth_usd",
            "market_depth_usd",
            "orderbook_depth_source",
        ):
            if market_microstructure.get(depth_field) is not None:
                intent[depth_field] = market_microstructure.get(depth_field)
        side_depth_field = "ask_depth_usd" if action == "long" else "bid_depth_usd"
        if market_microstructure.get(side_depth_field) is not None:
            intent["entry_orderbook_depth_usd"] = market_microstructure.get(side_depth_field)
            intent["entry_orderbook_depth_side"] = "ask" if action == "long" else "bid"
        intent["bid_ask_spread_bps_fallback"] = False
        intent["bid_ask_spread_bps_unavailable_reason"] = None
        spread_for_allocator = spread
    feature_source_name = str(intent.get("entry_feature_source") or "entry_features")
    liquidity, liquidity_source, liquidity_reason = _derive_allocator_liquidity_score(
        intent=intent,
        signal=signal,
        prediction=prediction,
        features=features,
        market_microstructure=market_microstructure,
        spread_bps=spread,
        feature_source_name=feature_source_name,
    )
    intent["allocator_liquidity_score"] = round(liquidity, 8)
    intent["allocator_liquidity_score_source"] = liquidity_source
    intent["allocator_liquidity_score_reason"] = liquidity_reason
    if intent.get("liquidity_score") in (None, ""):
        intent["liquidity_score"] = round(liquidity, 8)
    slippage, slippage_source = _first_numeric_field_from(
        ("signal", signal),
        ("prediction", prediction),
        (feature_source_name, features),
        keys=(
            "actual_observed_slippage_bps",
            "actual_slippage_bps",
            "realized_slippage_bps",
            "expected_slippage_bps",
            "slippage_bps",
            "estimated_slippage_bps",
        ),
    )
    if slippage is None:
        if spread is not None:
            slippage_for_allocator = _model_expected_slippage_bps(
                spread_bps=spread,
                volatility_bps=volatility,
                liquidity_score=liquidity,
            )
            intent["expected_slippage_bps_fallback"] = False
            intent["expected_slippage_modeled"] = True
            intent["expected_slippage_source"] = "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY"
            intent["expected_slippage_unavailable_reason"] = None
            intent["expected_slippage_bps"] = slippage_for_allocator
        else:
            intent["expected_slippage_bps_fallback"] = True
            intent["expected_slippage_modeled"] = False
            intent["expected_slippage_source"] = "CONSERVATIVE_MISSING_SLIPPAGE_BLOCKING_ESTIMATE"
            intent["expected_slippage_unavailable_reason"] = "MISSING_OBSERVED_OR_MODELED_SLIPPAGE_AT_DECISION_TIME"
            intent["expected_slippage_bps"] = None
            slippage_for_allocator = max(4.0, abs(float(expected_move or 0.0)) * 0.10)
    else:
        intent["expected_slippage_bps_fallback"] = False
        intent["expected_slippage_modeled"] = False
        intent["expected_slippage_source"] = slippage_source or "OBSERVED_OR_UPSTREAM_MODELED_SLIPPAGE_BPS"
        intent["expected_slippage_unavailable_reason"] = None
        intent["expected_slippage_bps"] = slippage
        slippage_for_allocator = slippage
    intent["slippage_bps_for_allocator"] = slippage_for_allocator
    fee_bps, fee_source = _first_numeric_field_from(
        ("intent", intent),
        ("signal", signal),
        ("prediction", prediction),
        (feature_source_name, features),
        ("market_microstructure", market_microstructure),
        keys=("actual_fee_bps", "fee_bps", "taker_fee_bps", "expected_fee_bps"),
    )
    if fee_bps is None:
        intent["fee_bps_fallback"] = True
        intent["fee_bps_for_allocator"] = None
        intent["fee_bps_unavailable_reason"] = "MISSING_EXPLICIT_FEE_BPS_AT_DECISION_TIME"
    else:
        intent["fee_bps"] = fee_bps
        intent["fee_bps_source"] = fee_source
        intent["fee_bps_fallback"] = False
        intent["fee_bps_for_allocator"] = fee_bps
        intent["fee_bps_unavailable_reason"] = None
    expected_funding_bps, expected_funding_source = _first_numeric_field_from(
        ("intent", intent),
        ("signal", signal),
        ("prediction", prediction),
        (feature_source_name, features),
        ("market_microstructure", market_microstructure),
        keys=("expected_funding_bps", "funding_bps", "funding_rate_bps", "actual_funding_bps"),
    )
    funding_rate_source = None
    if expected_funding_bps is None:
        funding_rate, funding_rate_source = _first_numeric_field_from(
            ("intent", intent),
            ("signal", signal),
            ("prediction", prediction),
            (feature_source_name, features),
            ("market_microstructure", market_microstructure),
            keys=("funding_rate",),
        )
        if funding_rate is not None:
            expected_funding_bps = funding_rate * 10000.0
            expected_funding_source = funding_rate_source
    if expected_funding_bps is None:
        intent["expected_funding_bps_fallback"] = True
        intent["expected_funding_bps_for_allocator"] = None
        intent["expected_funding_bps_unavailable_reason"] = "MISSING_EXPLICIT_FUNDING_BPS_AT_DECISION_TIME"
    else:
        intent["expected_funding_bps"] = expected_funding_bps
        intent["expected_funding_bps_source"] = expected_funding_source
        intent["expected_funding_bps_fallback"] = False
        intent["expected_funding_bps_for_allocator"] = expected_funding_bps
        intent["expected_funding_bps_unavailable_reason"] = None
        if funding_rate_source is not None:
            intent["expected_funding_bps_conversion"] = "funding_rate_to_bps"
    _attach_counterfactual_market_cost_evidence(intent)
    allocator_edge = float(expected_move or 0.0)
    if action == "short" and allocator_edge < 0.0:
        allocator_edge = abs(allocator_edge)
    if action == "long" and allocator_edge < 0.0:
        intent["paper_allocation_signed_edge_mismatch"] = True
    if action == "short" and expected_move is not None and expected_move < 0.0:
        intent["paper_allocation_signed_edge_normalized"] = True
        intent["paper_allocation_signed_expected_move_after_cost_bps"] = expected_move
    signal_correlation = _coerce_float(signal.get("correlation_exposure_pct"))
    derived_correlation_context = (correlation_contexts_by_symbol or {}).get(symbol, {})
    if signal_correlation is not None:
        correlation_exposure = signal_correlation
        intent["correlation_exposure_pct"] = round(max(0.0, abs(signal_correlation)), 8)
        intent["correlation_input_source"] = "SIGNAL_CORRELATION_EXPOSURE_PCT"
        intent["correlation_input_status"] = "READY"
    elif derived_correlation_context:
        correlation_exposure = _coerce_float(derived_correlation_context.get("correlation_exposure_pct")) or 0.0
        intent["correlation_exposure_pct"] = round(max(0.0, abs(correlation_exposure)), 8)
        intent["correlation_input_source"] = derived_correlation_context.get("correlation_input_source")
        intent["correlation_input_status"] = derived_correlation_context.get("correlation_input_status")
        intent["correlation_pair_count"] = derived_correlation_context.get("correlation_pair_count")
        if isinstance(derived_correlation_context.get("correlation_diagnostics"), dict):
            intent["correlation_diagnostics"] = derived_correlation_context.get("correlation_diagnostics")
    else:
        correlation_exposure = 0.0
        intent["correlation_exposure_pct"] = 0.0
        intent["correlation_input_source"] = "NO_CORRELATION_CONTEXT_AVAILABLE"
        intent["correlation_input_status"] = "MISSING_CORRELATION_CONTEXT"
    regime_score, regime_score_source, regime_score_reason = _derive_allocator_regime_score(
        intent=intent,
        signal=signal,
        prediction=prediction,
        features=features,
        feature_source_name=feature_source_name,
    )
    intent["allocator_regime_score"] = round(regime_score, 8)
    intent["allocator_regime_score_source"] = regime_score_source
    intent["allocator_regime_score_reason"] = regime_score_reason
    if intent.get("regime_score") in (None, ""):
        intent["regime_score"] = round(regime_score, 8)
    allocation_kwargs = {
        "symbol": symbol,
        "timeframe": str(intent.get("timeframe") or signal.get("timeframe") or "1m"),
        "action": action,
        "price": float(price or 0.0),
        "equity": portfolio_context["equity"],
        "available_margin": portfolio_context["available_margin"],
        "wallet_balance": portfolio_context["wallet_balance"],
        "confidence_calibrated": float(confidence or 0.0),
        "expected_move_after_cost_bps": allocator_edge,
        "market_state_integrity_score": float(market_score or 0.0),
        "volatility_bps": float(volatility or 50.0),
        "liquidity_score": float(liquidity),
        "spread_bps": float(spread_for_allocator),
        "slippage_bps": float(slippage_for_allocator),
        "drawdown_bps": portfolio_context["drawdown_bps"],
        "symbol_exposure_usdt": float(symbol_exposures.get(symbol, 0.0)),
        "total_exposure_usdt": float(total_exposure),
        "correlation_exposure_pct": float(max(0.0, abs(correlation_exposure))),
        "regime_score": float(regime_score),
        "min_qty": _coerce_float(signal.get("min_qty")),
        "step_size": _coerce_float(signal.get("step_size")),
        "min_notional": _coerce_float(signal.get("min_notional")),
        "ppo_action_probability": _coerce_float(signal.get("ppo_action_probability")),
        "masa_confidence": _coerce_float(signal.get("masa_confidence")),
        "lineage_ids": {
            "signal_id": intent.get("signal_id"),
            "prediction_id": intent.get("prediction_id"),
            "risk_decision_id": intent.get("risk_decision_id"),
            "orchestrator_decision_id": intent.get("orchestrator_decision_id"),
            "market_state_id": intent.get("market_state_id"),
        },
    }
    if fee_bps is not None:
        allocation_kwargs["fee_bps"] = float(fee_bps)
    if expected_funding_bps is not None:
        allocation_kwargs["expected_funding_bps"] = float(expected_funding_bps)
    return AllocationInput(**allocation_kwargs)


def _paper_signal_integrity_gate(signal: dict) -> dict:
    score = _coerce_float(signal.get("market_state_integrity_score"))
    reasons = list(signal.get("market_state_reject_reasons") or [])
    valid_for_paper = signal.get("valid_for_paper")
    if not signal.get("market_state_id"):
        reasons.append("MARKET_STATE_ID_MISSING")
    if score is None:
        reasons.append("MARKET_STATE_INTEGRITY_SCORE_MISSING")
    elif score < 70.0:
        reasons.append("MARKET_STATE_INTEGRITY_SCORE_BELOW_PAPER_MIN")
    if valid_for_paper is not True:
        reasons.append("VALID_FOR_PAPER_NOT_TRUE")
    allowed = not reasons
    return {
        "allowed": allowed,
        "market_state_id": signal.get("market_state_id"),
        "market_state_integrity_score": score,
        "valid_for_paper": valid_for_paper,
        "reasons": sorted(set(str(reason) for reason in reasons if reason)),
    }


def run_once() -> dict:
    from v2.backend.app.services.trade_management_paper.service import (
        TradeManagementPaperService, evaluate_fee_ratio_gate, churn_veto,
    )
    from v2.backend.app.services.paper_trade_management import (
        PaperLifecycleConfig,
        reconcile_paper_lifecycle,
    )
    from v2.backend.app.services.paper_trade_management.entry_gate import (
        PaperEntryGateConfig,
        evaluate_entry_gate,
    )
    _entry_gate_cfg = PaperEntryGateConfig(
        symbol_exclusion_list=PAPER_AUDIT_SYMBOL_EXCLUSION_LIST,
        allowed_entry_timeframes=PAPER_AUDIT_ALLOWED_ENTRY_TIMEFRAMES,
    )
    from v2.backend.app.services.adaptive_capital_allocator import allocate_paper_candidate
    started = _utc_iso()
    runtime_now = datetime.now(timezone.utc)
    r = _connect_redis()
    live_context = _live_context(r)
    signals = _read_paper_signals(r)
    held_by_gate = _read_held_by_paper_fill_gate(r)
    prediction_rows = _scan_prediction_rows(r)
    predictions_by_id = {
        str(row.get("prediction_id")): row
        for row in prediction_rows
        if row.get("prediction_id")
    }
    predictions_by_symbol = _group_predictions_by_symbol(prediction_rows)
    existing_ledger = _read_existing_ledger_payload(r)
    existing_accepted = _read_existing_accepted_fills(r)
    portfolio_context = _portfolio_equity_context(r)
    symbol_exposures, total_exposure = _open_exposures_from_ledger(existing_ledger)
    candidate_symbols = [
        str(signal.get("symbol") or "").upper()
        for signal in signals
        if isinstance(signal, dict) and signal.get("symbol")
    ]
    correlation_contexts_by_symbol = _derive_candidate_correlation_contexts(
        r,
        candidate_symbols=candidate_symbols,
        open_symbols=list(symbol_exposures),
        generated_utc=started,
    )
    execution_metrics = _read_recent_execution_metrics(r)
    current_risk_state = _read_current_risk_state(r)
    tm = TradeManagementPaperService()
    intents: list[dict] = []
    risk_decisions: list[dict] = []
    accepted: list[dict] = []
    blocked: list[dict] = []
    shadow_observations: list[dict] = []
    held_by_gate_intents: list[dict] = []
    directional_guard_evaluations: list[dict[str, Any]] = []
    strategy_mode_guard_evaluations: list[dict[str, Any]] = []
    drawdown_recovery_guard_evaluations: list[dict[str, Any]] = []
    for s in signals:
        symbol = str(s.get("symbol") or _runtime_default_symbol()).upper()
        side = _first_present(s.get("side"), s.get("action"), s.get("selected_action"), "long")
        lineage = _lineage_ids(s, symbol)
        prediction = predictions_by_id.get(lineage["prediction_id"], {})
        paper_signal_temporal_rejection_reasons = _paper_signal_temporal_rejection_reasons(
            signal=s,
            prediction=prediction,
            now=runtime_now,
        )
        em_after = _coerce_float(s.get("expected_move_after_cost_bps"))
        em_after = 0.0 if em_after is None else em_after
        confidence_calibrated = _first_present(s.get("confidence_calibrated"), s.get("confidence"))
        confidence_raw = _first_present(s.get("confidence_raw"), prediction.get("confidence_raw"))
        expected_move_bps = _first_present(
            s.get("expected_move_bps"),
            prediction.get("expected_move_bps"),
            s.get("price_target_bps"),
            prediction.get("price_target_bps"),
        )
        selected_action_probability = _first_present(
            s.get("selected_action_probability"),
            prediction.get("selected_action_probability"),
            s.get("action_probability"),
            prediction.get("action_probability"),
        )
        market_state_envelope = _build_market_state_envelope(signal=s, prediction=prediction)
        symbol_predictions = predictions_by_symbol.get(symbol, [])
        strategy_timeframe_rows = _point_in_time_timeframe_rows(
            market_state_envelope=market_state_envelope,
            timeframe_rows=symbol_predictions,
        )
        future_cutoff_offenders = _future_cutoff_offenders(
            market_state_envelope=market_state_envelope,
            timeframe_rows=strategy_timeframe_rows,
        )
        current_position_state = _derive_position_state(existing_ledger, symbol)
        strategy_router = route_strategy(
            market_state_envelope=market_state_envelope,
            masa_predictions=strategy_timeframe_rows,
            ppo_proposed_action=str(side),
            current_position_state=current_position_state,
            recent_execution_success_metrics=execution_metrics,
            volatility_liquidity_state=_build_volatility_liquidity_state(
                signal=s,
                prediction=prediction,
            ),
            data_quality_score=_coerce_float(
                _first_present(
                    s.get("market_state_integrity_score"),
                    prediction.get("market_state_integrity_score"),
                )
            ),
            current_drawdown_risk_state=current_risk_state,
        )
        paper_fill_allowed_upstream = bool(s.get("paper_fill_allowed", False))
        strategy_router, drawdown_recovery_guard = _paper_drawdown_recovery_router_result(
            existing_ledger=existing_ledger,
            strategy_router=strategy_router,
            candidate_side=side,
            current_position_state=current_position_state,
            paper_fill_allowed_upstream=paper_fill_allowed_upstream,
            expected_move_after_cost_bps=em_after,
            confidence_calibrated=_coerce_float(confidence_calibrated),
            live_gate=live_context["live_gate"],
        )
        drawdown_recovery_guard_evaluations.append(drawdown_recovery_guard)
        paper_strategy_selected_mode = _paper_audit_strategy_mode(strategy_router)
        paper_strategy_size_adjustment_mode = _paper_strategy_size_adjustment_mode(strategy_router)
        strategy_trade_allowed = (
            strategy_router["selected_mode"] != "no_trade_mode"
            and strategy_router.get("block_reason") is None
            and str(side).lower() in set(strategy_router.get("allowed_actions") or [])
        )
        # Pre-trade gates
        pre = tm.evaluate_pre_trade(
            seconds_since_last_close=3600,  # paper default: no recent close
            fee_bps=5.0,
            expected_move_after_cost_bps=em_after,
        )
        fee_gate = evaluate_fee_ratio_gate(
            fee_bps=5.0,
            expected_move_after_cost_bps=em_after,
            max_ratio=0.5,
        )
        churn = churn_veto(seconds_since_last_close=3600, minimum_hold_seconds=300)
        trust_lineage_source = _trust_lineage_source(s, prediction)
        trust_envelope = _trust_envelope_from_prediction(trust_lineage_source)
        trust_decision_id = _first_present(
            trust_envelope.get("decision_id"),
            lineage["orchestrator_decision_id"],
        )
        trust_selected_action = _first_present(trust_envelope.get("selected_action"), side)
        trust_checkpoint_id = _first_present(
            trust_envelope.get("checkpoint_id"),
            s.get("checkpoint_id"),
            prediction.get("checkpoint_id"),
        )
        trust_feature_snapshot_id = _first_present(
            trust_envelope.get("feature_snapshot_id"),
            s.get("feature_snapshot_id"),
            prediction.get("feature_snapshot_id"),
        )
        risk_decisions.append({
            "risk_decision_id": lineage["risk_decision_id"],
            "prediction_id": lineage["prediction_id"],
            "signal_id": lineage["signal_id"],
            "orchestrator_decision_id": lineage["orchestrator_decision_id"],
            "decision_id": trust_decision_id,
            "feature_snapshot_id": trust_feature_snapshot_id,
            "mtf_snapshot_id": trust_envelope.get("mtf_snapshot_id"),
            "feature_cutoff": trust_envelope.get("feature_cutoff"),
            "decision_time": trust_envelope.get("decision_time"),
            "available_at": trust_envelope.get("available_at"),
            "selected_action": trust_selected_action,
            "model_version": trust_envelope.get("model_version"),
            "checkpoint_id": trust_checkpoint_id,
            "source_hashes": trust_envelope.get("source_hashes"),
            "feature_vector_hash": trust_envelope.get("feature_vector_hash"),
            "input_feature_hash": trust_envelope.get("input_feature_hash"),
            "symbol": symbol,
            "timeframe": _first_present(s.get("timeframe"), prediction.get("timeframe")),
            "side": side,
            "expected_move_after_cost_bps": em_after,
            "expected_net_edge_bps": em_after,
            "expected_move_bps": expected_move_bps,
            "confidence_raw": confidence_raw,
            "confidence_calibrated": confidence_calibrated,
            "selected_action_probability": selected_action_probability,
            "pre_trade_allowed": pre["allowed"],
            "fee_gate_allowed": not fee_gate.blocked,
            "fee_gate_reason": fee_gate.reason,
            "churn_blocked": churn.blocked,
            "churn_reason": churn.reason,
            "strategy_selected_mode": paper_strategy_selected_mode,
            "strategy_router_selected_mode": strategy_router["selected_mode"],
            "strategy_size_adjustment_mode": paper_strategy_size_adjustment_mode,
            "strategy_allowed_actions": list(strategy_router["allowed_actions"]),
            "strategy_size_multiplier": strategy_router["size_multiplier"],
            "strategy_router_confidence": strategy_router["confidence"],
            "strategy_router_block_reason": strategy_router["block_reason"],
            "strategy_regime_labels": list(strategy_router["regime_labels"]),
            "execution_success_metric_source": execution_metrics.get("execution_success_metric_source"),
            "closed_trade_outcome_count": execution_metrics.get("closed_trade_outcome_count"),
            "clean_closed_trade_outcome_count": execution_metrics.get("clean_closed_trade_outcome_count"),
            "dirty_closed_trade_outcome_count": execution_metrics.get("dirty_closed_trade_outcome_count"),
            "raw_closed_trade_outcome_count": execution_metrics.get("raw_closed_trade_outcome_count"),
            "execution_success_sample_status": execution_metrics.get("execution_success_sample_status"),
            "strategy_decision_time": market_state_envelope.get("decision_time"),
            "strategy_feature_cutoff": market_state_envelope.get("feature_cutoff"),
            "strategy_future_cutoff_offender_count": len(future_cutoff_offenders),
            "strategy_future_cutoff_offenders": future_cutoff_offenders[:5],
            "paper_drawdown_recovery_guard": drawdown_recovery_guard,
            "paper_signal_temporal_rejection_reasons": paper_signal_temporal_rejection_reasons,
            "risk_manager_final_authority": True,
        })
        integrity_gate = _paper_signal_integrity_gate(s)
        intent_id = _first_present(
            s.get("winner_proposal_id"),
            lineage["signal_id"],
            lineage["prediction_id"],
            f"v2_paper_intent_{symbol}",
        )
        intent = {
            "intent_id": intent_id,
            "symbol": symbol,
            "side": side,
            "signal_id": s.get("signal_id"),
            "expected_move_after_cost_bps": em_after,
            "expected_move_bps": expected_move_bps,
            "confidence_raw": confidence_raw,
            "confidence_calibrated": confidence_calibrated,
            "selected_action_probability": selected_action_probability,
            "action_probabilities": _first_present(
                s.get("action_probabilities"),
                prediction.get("action_probabilities"),
                s.get("policy_action_probabilities"),
                prediction.get("policy_action_probabilities"),
            ),
            "policy_value": _first_present(
                s.get("policy_value"),
                prediction.get("policy_value"),
                s.get("value_estimate"),
                prediction.get("value_estimate"),
            ),
            "value_baseline": _first_present(
                s.get("value_baseline"),
                prediction.get("value_baseline"),
            ),
            "prediction_score_source": "PAPER_INTENT_ENTRY_PREDICTION_SCORE_FIELDS",
            "price_target": _first_present(s.get("price_target"), s.get("price_target_after_cost")),
            "timeframe": s.get("timeframe"),
            "data_coverage_percent": s.get("data_coverage_percent"),
            "strategy_selected_mode": paper_strategy_selected_mode,
            "strategy_id": paper_strategy_selected_mode,
            "strategy_family": paper_strategy_selected_mode,
            "strategy_subtype": paper_strategy_selected_mode,
            "strategy_router_selected_mode": strategy_router["selected_mode"],
            "strategy_size_adjustment_mode": paper_strategy_size_adjustment_mode,
            "strategy_allowed_actions": list(strategy_router["allowed_actions"]),
            "strategy_action_mask": dict(strategy_router["action_mask"]),
            "strategy_size_multiplier": strategy_router["size_multiplier"],
            "strategy_router_confidence": strategy_router["confidence"],
            "strategy_router_block_reason": strategy_router["block_reason"],
            "strategy_reason_codes": list(strategy_router["reason_codes"]),
            "strategy_regime_labels": list(strategy_router["regime_labels"]),
            "strategy_explanation": dict(strategy_router["explanation"]),
            "execution_success_metric_source": execution_metrics.get("execution_success_metric_source"),
            "closed_trade_outcome_count": execution_metrics.get("closed_trade_outcome_count"),
            "clean_closed_trade_outcome_count": execution_metrics.get("clean_closed_trade_outcome_count"),
            "dirty_closed_trade_outcome_count": execution_metrics.get("dirty_closed_trade_outcome_count"),
            "raw_closed_trade_outcome_count": execution_metrics.get("raw_closed_trade_outcome_count"),
            "execution_success_sample_status": execution_metrics.get("execution_success_sample_status"),
            "strategy_decision_time": market_state_envelope.get("decision_time"),
            "strategy_feature_cutoff": market_state_envelope.get("feature_cutoff"),
            "strategy_future_cutoff_offender_count": len(future_cutoff_offenders),
            "strategy_future_cutoff_offenders": future_cutoff_offenders[:5],
            "paper_drawdown_recovery_guard": drawdown_recovery_guard,
            "paper_signal_temporal_rejection_reasons": paper_signal_temporal_rejection_reasons,
            "strategy_router": strategy_router,
            "pre_trade_allowed": pre["allowed"],
            "fee_gate_allowed": not fee_gate.blocked,
            "churn_blocked": churn.blocked,
            "paper_only": True,
            "places_real_order": False,
            "generated_utc": _utc_iso(),
            "live_gate": live_context["live_gate"],
            "live_symbols": live_context["live_symbols"],
            "execution_live_symbols": live_context["execution_live_symbols"],
            "source_intent_id": intent_id,
            "signal_id": lineage["signal_id"],
            "source_prediction_id": lineage["prediction_id"],
            "prediction_id": lineage["prediction_id"],
            "risk_decision_id": lineage["risk_decision_id"],
            "orchestrator_decision_id": lineage["orchestrator_decision_id"],
            "decision_id": trust_decision_id,
            "feature_snapshot_id": trust_feature_snapshot_id,
            "mtf_snapshot_id": trust_envelope.get("mtf_snapshot_id"),
            "feature_cutoff": trust_envelope.get("feature_cutoff"),
            "decision_time": trust_envelope.get("decision_time"),
            "available_at": trust_envelope.get("available_at"),
            "selected_action": trust_selected_action,
            "model_version": trust_envelope.get("model_version"),
            "checkpoint_id": trust_checkpoint_id,
            "source_hashes": trust_envelope.get("source_hashes"),
            "feature_vector_hash": trust_envelope.get("feature_vector_hash"),
            "input_feature_hash": trust_envelope.get("input_feature_hash"),
            "paper_fill_allowed": paper_fill_allowed_upstream,
            "strict_paper_fill_allowed_upstream": paper_fill_allowed_upstream,
            "market_state_id": s.get("market_state_id"),
            "market_state_integrity_score": integrity_gate["market_state_integrity_score"],
            "valid_for_paper": integrity_gate["valid_for_paper"],
            "market_state_reject_reasons": integrity_gate["reasons"],
            "major_move_signal_id": s.get("major_move_signal_id"),
            "major_move_evidence_score": s.get("major_move_evidence_score"),
            "squeeze_evidence_score": s.get("squeeze_evidence_score"),
            "liquidation_pressure": s.get("liquidation_pressure"),
            "liquidation_strength": s.get("liquidation_strength"),
            "liquidation_cascade_risk": s.get("liquidation_cascade_risk"),
            "last_liq_bps_24h": s.get("last_liq_bps_24h"),
            "oi_change_pct": s.get("oi_change_pct"),
            "funding_rate": s.get("funding_rate"),
            "ob_imbalance": s.get("ob_imbalance"),
            "paper_fill_gate_status": s.get("paper_fill_gate_status"),
            "paper_fill_gate_block_reasons": list(s.get("paper_fill_gate_block_reasons") or []),
            "risk_state": s.get("risk_state"),
            "orchestrator_state": s.get("orchestrator_state"),
            "quantity": s.get("quantity"),
            "notional": _first_present(
                s.get("notional"),
                s.get("notional_usdt"),
                s.get("requested_notional_usdt"),
                s.get("notional_usd"),
            ),
            "trainer_source": s.get("trainer_source"),
            "model_id": s.get("model_id"),
            "paper_confidence_threshold_trial": bool(s.get("paper_confidence_threshold_trial")),
            "paper_confidence_trial_id": s.get("paper_confidence_trial_id"),
            "paper_confidence_trial_threshold": s.get("paper_confidence_trial_threshold"),
            "paper_confidence_trial_original_block_reasons": list(
                s.get("paper_confidence_trial_original_block_reasons") or []
            ),
            "paper_confidence_trial_promoted": bool(s.get("paper_confidence_trial_promoted")),
            "paper_confidence_trial_generated_est": s.get("paper_confidence_trial_generated_est"),
            "paper_confidence_trial_scope": s.get("paper_confidence_trial_scope"),
            "paper_confidence_trial_operator_acceptance": s.get(
                "paper_confidence_trial_operator_acceptance"
            ),
            "paper_confidence_trial_lineage": s.get("paper_confidence_trial_lineage"),
        }
        missing_score_fields = [
            field
            for field in ("confidence_calibrated", "expected_move_after_cost_bps")
            if intent.get(field) in (None, "")
        ]
        if missing_score_fields:
            intent["prediction_score_source"] = None
            intent["prediction_score_missing_reason"] = (
                "MISSING_PAPER_INTENT_ENTRY_PREDICTION_SCORE_FIELDS:"
                + ",".join(missing_score_fields)
            )
        # Attach V2-owned price provenance to every intent. The strict
        # paper-fill gate decides whether the intent becomes an accepted
        # paper fill; the provenance fields ride along regardless so
        # the recorder can quote MISSING markers when no price was
        # available, and never fabricate a price.
        px, px_source, px_source_utc = _read_v2_market_price(r, symbol)
        _attach_entry_price_provenance(intent, px, px_source, px_source_utc)
        entry_feature_decision_time = str(
            _first_present(
                intent.get("decision_time"),
                trust_envelope.get("decision_time"),
                intent.get("generated_utc"),
                started,
            )
        )
        entry_feature_snapshot = _read_v2_feature_snapshot_by_id(
            r,
            trust_feature_snapshot_id,
            decision_time=entry_feature_decision_time,
            symbol=symbol,
            timeframe=_first_present(intent.get("timeframe"), prediction.get("timeframe"), s.get("timeframe")),
        )
        entry_features = (
            entry_feature_snapshot.get("features")
            if isinstance(entry_feature_snapshot.get("features"), dict)
            else {}
        )
        if entry_features:
            intent["entry_feature_snapshot_id"] = entry_feature_snapshot.get("feature_snapshot_id")
            intent["entry_feature_available_at"] = entry_feature_snapshot.get("available_at")
            intent["entry_feature_generated_at"] = entry_feature_snapshot.get("generated_at")
            intent["entry_feature_cutoff"] = entry_feature_snapshot.get("feature_cutoff")
            intent["entry_feature_decision_time"] = entry_feature_decision_time
            intent["entry_feature_source"] = str(entry_feature_snapshot.get("redis_key") or "")
            intent["entry_feature_candle_closed_confirmed"] = entry_feature_snapshot.get(
                "candle_closed_confirmed"
            )
            snapshot_evidence = _entry_feature_snapshot_evidence(entry_feature_snapshot)
            if snapshot_evidence is not None:
                snapshot_evidence.setdefault("feature_snapshot_id", trust_feature_snapshot_id)
                snapshot_evidence.setdefault("symbol", symbol)
                snapshot_evidence.setdefault(
                    "timeframe",
                    _first_present(intent.get("timeframe"), prediction.get("timeframe"), s.get("timeframe")),
                )
                intent["entry_feature_snapshot"] = snapshot_evidence
        else:
            intent["entry_feature_unavailable_reason"] = entry_feature_snapshot.get(
                "unavailable_reason"
            )
        prediction_for_entry = prediction
        if entry_features and not isinstance(prediction.get("features"), dict):
            prediction_for_entry = dict(prediction)
            prediction_for_entry["features"] = entry_features
        market_microstructure = _read_v2_orderbook_microstructure(r, symbol)
        allocation_input = _build_allocation_input(
            intent=intent,
            signal=s,
            prediction=prediction_for_entry,
            portfolio_context=portfolio_context,
            symbol_exposures=symbol_exposures,
            total_exposure=total_exposure,
            market_microstructure=market_microstructure,
            correlation_contexts_by_symbol=correlation_contexts_by_symbol,
        )
        allocation = allocate_paper_candidate(allocation_input)
        allocation_payload = allocation.to_payload()
        _attach_paper_sizing(intent, allocation_payload)
        _attach_trainer_feedback_entry_context(
            intent=intent,
            prediction=prediction_for_entry,
            strategy_router=strategy_router,
            allocation=allocation_payload,
            portfolio_context=portfolio_context,
        )
        runtime_market_evidence_rejection_reasons = _paper_runtime_market_evidence_rejection_reasons(intent)
        intent["paper_runtime_market_evidence_rejection_reasons"] = runtime_market_evidence_rejection_reasons
        _apply_strategy_size_multiplier(intent, _coerce_float(strategy_router["size_multiplier"]))
        directional_guard = _paper_directional_collapse_guard(existing_ledger, side)
        intent["paper_directional_collapse_guard"] = directional_guard
        directional_guard_evaluations.append(directional_guard)
        strategy_mode_guard = _paper_strategy_mode_collapse_guard(
            existing_ledger,
            intent.get("strategy_selected_mode"),
        )
        intent["paper_strategy_mode_collapse_guard"] = strategy_mode_guard
        strategy_mode_guard_evaluations.append(strategy_mode_guard)
        intents.append(intent)
        # P0 entry gate: symbol exclusion, timeframe filter, strategy mode block.
        # Evidence-driven defaults from 2026-06-16 soak test (see entry_gate.py).
        _eg = evaluate_entry_gate(
            symbol=symbol,
            timeframe=intent.get("timeframe"),
            side=intent.get("side"),
            strategy_mode=intent.get("strategy_selected_mode"),
            confidence_calibrated=_coerce_float(intent.get("confidence_calibrated")),
            expected_move_after_cost_bps=_coerce_float(intent.get("expected_move_after_cost_bps")),
            redis_client=r,
            config=_entry_gate_cfg,
        )
        if not _eg["allowed"]:
            intent["paper_fill_block_reason"] = "P0_ENTRY_GATE_BLOCKED"
            intent["entry_gate_block_reasons"] = _eg["reasons"]
            intent["local_block_reasons"] = sorted(set(
                list(intent.get("local_block_reasons") or [])
                + [f"entry_gate:{r}" for r in _eg["reasons"]]
            ))
        local_trade_gates_pass = (
            _eg["allowed"]
            and pre["allowed"]
            and not fee_gate.blocked
            and not churn.blocked
            and integrity_gate["allowed"]
            and strategy_trade_allowed
            and strategy_mode_guard.get("allowed") is True
            and not paper_signal_temporal_rejection_reasons
            and not runtime_market_evidence_rejection_reasons
        )
        exploration_trade_gates_pass = (
            pre["allowed"]
            and not fee_gate.blocked
            and not churn.blocked
            and integrity_gate["allowed"]
            and not paper_signal_temporal_rejection_reasons
            and not runtime_market_evidence_rejection_reasons
        )
        if not integrity_gate["allowed"]:
            intent["paper_fill_block_reason"] = "MARKET_STATE_INTEGRITY_PAPER_GATE_BLOCKED"
            intent["paper_fill_gate_block_reasons"] = sorted(set(
                list(intent.get("paper_fill_gate_block_reasons") or [])
                + list(integrity_gate["reasons"])
            ))
        if not strategy_trade_allowed:
            intent["paper_fill_block_reason"] = intent.get("paper_fill_block_reason") or "STRATEGY_ROUTER_BLOCKED"
            local_reason = str(strategy_router.get("block_reason") or "ACTION_NOT_ALLOWED_BY_ROUTER")
            intent["local_block_reasons"] = sorted(set(
                list(intent.get("local_block_reasons") or [])
                + [f"strategy_router:{local_reason}"]
            ))
        if strategy_mode_guard.get("allowed") is not True:
            reason = str(strategy_mode_guard.get("block_reason") or STRATEGY_MODE_COLLAPSE_BLOCK_REASON)
            intent["paper_fill_block_reason"] = (
                intent.get("paper_fill_block_reason") or reason
            )
            intent["paper_fill_gate_block_reasons"] = sorted(set(
                list(intent.get("paper_fill_gate_block_reasons") or []) + [reason]
            ))
            intent["local_block_reasons"] = sorted(set(
                list(intent.get("local_block_reasons") or [])
                + [f"strategy_mode_collapse_guard:{reason}"]
            ))
        if paper_signal_temporal_rejection_reasons:
            intent["paper_fill_block_reason"] = (
                intent.get("paper_fill_block_reason") or "PAPER_SIGNAL_TEMPORAL_BLOCKED"
            )
            intent["paper_fill_gate_block_reasons"] = sorted(set(
                list(intent.get("paper_fill_gate_block_reasons") or [])
                + paper_signal_temporal_rejection_reasons
            ))
            intent["local_block_reasons"] = sorted(set(
                list(intent.get("local_block_reasons") or [])
                + [f"temporal:{reason}" for reason in paper_signal_temporal_rejection_reasons]
            ))
        if runtime_market_evidence_rejection_reasons:
            intent["paper_fill_block_reason"] = (
                intent.get("paper_fill_block_reason") or PAPER_RUNTIME_EVIDENCE_BLOCK_REASON
            )
            intent["paper_fill_gate_block_reasons"] = sorted(set(
                list(intent.get("paper_fill_gate_block_reasons") or [])
                + runtime_market_evidence_rejection_reasons
            ))
            intent["local_block_reasons"] = sorted(set(
                list(intent.get("local_block_reasons") or [])
                + [f"runtime_market_evidence:{reason}" for reason in runtime_market_evidence_rejection_reasons]
            ))
        tier_classification = _classify_paper_opportunity_tier(
            signal=s,
            intent=intent,
            allocation=allocation_payload,
            integrity_gate=integrity_gate,
            local_trade_gates_pass=local_trade_gates_pass,
            exploration_trade_gates_pass=exploration_trade_gates_pass,
            paper_fill_allowed_upstream=paper_fill_allowed_upstream,
            portfolio_drawdown_bps=portfolio_context["drawdown_bps"],
        )
        _apply_paper_tier_classification(
            intent=intent,
            allocation=allocation_payload,
            classification=tier_classification,
        )
        if intent.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION:
            _apply_b_grade_exploration_budget_cap(
                intent=intent,
                allocation=allocation_payload,
                risk_budget_fraction_of_normal_adaptive=tier_classification.get(
                    "risk_budget_fraction_of_normal_adaptive"
                ),
            )
            _attach_paper_sizing(intent, allocation_payload)
        paper_tier_local_fill_allowed = (
            intent.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
            or (
                not paper_fill_allowed_upstream
                and intent.get("paper_opportunity_tier") == PAPER_TIER_A_GRADE_EXECUTION
            )
        )
        b_grade_relaxed_strict_local_gate = (
            paper_tier_local_fill_allowed
            and intent.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
            and not local_trade_gates_pass
            and exploration_trade_gates_pass
        )
        if b_grade_relaxed_strict_local_gate:
            intent["b_grade_exploration_relaxed_strict_local_gate"] = True
            intent["b_grade_exploration_strict_local_gate_block_reasons"] = list(
                intent.get("local_block_reasons") or []
            )
            if intent.get("paper_fill_block_reason") == "P0_ENTRY_GATE_BLOCKED":
                intent["paper_fill_block_reason"] = None
        if not local_trade_gates_pass and not b_grade_relaxed_strict_local_gate:
            # Failed local pre-trade / fee / churn gates — not a fill,
            # not a shadow observation; tracked in blocked[] only.
            blocked.append(intent)
            continue
        if paper_tier_local_fill_allowed:
            intent["paper_fill_allowed"] = True
            intent["paper_tier_local_fill_allowed"] = True
            intent["paper_tier_local_fill_source"] = intent.get("paper_fill_allowed_source")
            intent["strict_paper_fill_allowed_upstream"] = False
            intent["places_real_order"] = False
            intent["paper_only"] = True
        if not paper_fill_allowed_upstream and not paper_tier_local_fill_allowed:
            # Local gates pass but the strict paper-fill gate did NOT
            # mark this intent as paper_fill_allowed=true, and no
            # calibrated paper-only A/B tier admitted it. This remains a
            # SHADOW OBSERVATION: provenance fields are useful for no-trade
            # outcome analysis but the row is NOT a fill.
            shadow_intent = dict(intent)
            shadow_intent["decision"] = "SHADOW_OBSERVATION_ONLY"
            shadow_intent["paper_fill_allowed"] = False
            shadow_intent["places_real_order"] = False
            shadow_intent["counted_as_accepted_position"] = False
            shadow_intent["counted_as_fill"] = False
            shadow_intent["counted_as_open_position"] = False
            shadow_intent["entry_price_provenance_observed"] = bool(
                intent.get("entry_price_provenance_present")
            )
            shadow_observations.append(shadow_intent)
            continue
        if directional_guard.get("allowed") is not True:
            reason = str(directional_guard.get("block_reason") or DIRECTIONAL_COLLAPSE_BLOCK_REASON)
            intent["paper_fill_block_reason"] = reason
            intent["paper_fill_gate_block_reasons"] = sorted(set(
                list(intent.get("paper_fill_gate_block_reasons") or []) + [reason]
            ))
            intent["local_block_reasons"] = sorted(set(
                list(intent.get("local_block_reasons") or [])
                + [f"directional_collapse_guard:{reason}"]
            ))
            blocked.append(intent)
            continue
        if intent.get("paper_sizing_complete") is not True:
            intent["paper_fill_block_reason"] = intent.get("paper_fill_block_reason") or "ADAPTIVE_ALLOCATOR_BLOCKED"
            allocator_reason = str(intent.get("paper_allocation_block_reason") or "ADAPTIVE_SIZE_INCOMPLETE")
            intent["local_block_reasons"] = sorted(set(
                list(intent.get("local_block_reasons") or [])
                + [f"adaptive_allocator:{allocator_reason}"]
            ))
            blocked.append(intent)
            continue
        # Accepted fill: passes both the local gates AND the
        # strict upstream paper-fill gate (P0.2F). Goes to
        # v2:paper:positions.
        accepted_intent = dict(intent)
        accepted_intent["decision"] = "ACCEPTED_PAPER_FILL"
        accepted_intent["entry_price_provenance_observed"] = bool(
            intent.get("entry_price_provenance_present")
        )
        accepted_intent["economic_fill_candidate"] = bool(intent.get("paper_sizing_complete"))
        if not accepted_intent["economic_fill_candidate"]:
            accepted_intent["paper_accounting_blocker"] = "PAPER_SIZING_OR_PRICE_INCOMPLETE"
        accepted.append(accepted_intent)
    # Held-by-gate passthrough: record each upstream-blocked symbol as a
    # non-fill intent that carries the strict gate's block reasons. These
    # do NOT pass pre-trade, fee-ratio, or churn gates and never become
    # paper positions.
    for held in held_by_gate:
        pred_id = _first_present(held.get("prediction_id"), held.get("source_prediction_id"))
        pred = predictions_by_id.get(str(pred_id or ""), {})
        held_trust_source = _trust_lineage_source(held, pred)
        held_trust_envelope = _trust_envelope_from_prediction(held_trust_source)
        held_by_gate_intents.append({
            "intent_id": f"v2_paper_intent_held_{held.get('symbol') or 'unknown'}",
            "symbol": _first_present(held.get("symbol"), pred.get("symbol")),
            "timeframe": _first_present(held.get("timeframe"), pred.get("timeframe")),
            "decision": "HELD_BY_PAPER_FILL_GATE",
            "places_real_order": False,
            "paper_only": True,
            "signal_id": held.get("signal_id"),
            "risk_decision_id": held.get("risk_decision_id"),
            "orchestrator_decision_id": held.get("orchestrator_decision_id"),
            "paper_fill_gate_status": _first_present(held.get("paper_fill_gate_status"), pred.get("paper_fill_gate_status")),
            "paper_fill_gate_block_reasons": list(
                held.get("paper_fill_gate_block_reasons")
                or pred.get("paper_fill_gate_block_reasons")
                or []
            ),
            "checkpoint_blocker": _first_present(held.get("checkpoint_blocker"), pred.get("checkpoint_blocker")),
            "selected_action_upstream": _first_present(held.get("selected_action"), pred.get("selected_action")),
            "source_prediction_id": pred_id,
            "prediction_id": pred_id,
            "decision_id": _first_present(
                held_trust_envelope.get("decision_id"),
                held.get("orchestrator_decision_id"),
            ),
            "feature_snapshot_id": _first_present(
                held_trust_envelope.get("feature_snapshot_id"),
                held.get("feature_snapshot_id"),
                pred.get("feature_snapshot_id"),
            ),
            "mtf_snapshot_id": held_trust_envelope.get("mtf_snapshot_id"),
            "feature_cutoff": held_trust_envelope.get("feature_cutoff"),
            "decision_time": held_trust_envelope.get("decision_time"),
            "available_at": held_trust_envelope.get("available_at"),
            "selected_action": held_trust_envelope.get("selected_action"),
            "model_version": held_trust_envelope.get("model_version"),
            "checkpoint_id": held_trust_envelope.get("checkpoint_id"),
            "source_hashes": held_trust_envelope.get("source_hashes"),
            "feature_vector_hash": held_trust_envelope.get("feature_vector_hash"),
            "input_feature_hash": held_trust_envelope.get("input_feature_hash"),
            "expected_move_after_cost_bps": pred.get("expected_move_after_cost_bps"),
            "confidence_calibrated": pred.get("confidence_calibrated"),
            "price_target": pred.get("price_target"),
            "data_coverage_percent": pred.get("data_coverage_percent"),
            "missing_feature_count": len(pred.get("missing_feature_flags") or []),
            "stale_feature_count": len(pred.get("stale_feature_flags") or []),
            "feature_freshness_state": pred.get("feature_freshness_state"),
            "market_state_id": _first_present(held.get("market_state_id"), pred.get("market_state_id")),
            "market_state_integrity_score": _first_present(held.get("market_state_integrity_score"), pred.get("market_state_integrity_score")),
            "valid_for_paper": _first_present(held.get("valid_for_paper"), pred.get("valid_for_paper")),
            "valid_for_live": _first_present(held.get("valid_for_live"), pred.get("valid_for_live")),
            "market_state_reject_reasons": list(held.get("market_state_reject_reasons") or pred.get("market_state_reject_reasons") or []),
            "trainer_source": pred.get("trainer_source"),
            "checkpoint_weight_status": pred.get("checkpoint_weight_status"),
            "paper_fill_allowed": False,
            "strict_paper_fill_allowed_upstream": False,
            "paper_opportunity_tier": PAPER_TIER_SHADOW_ONLY,
            "paper_opportunity_tier_reason": "HELD_BY_UPSTREAM_PAPER_FILL_GATE",
            "paper_fill_allowed_source": "UPSTREAM_HELD_BY_PAPER_FILL_GATE",
            "generated_utc": _utc_iso(),
            "live_gate": live_context["live_gate"],
            "live_symbols": live_context["live_symbols"],
            "execution_live_symbols": live_context["execution_live_symbols"],
        })
    keys_written: list[str] = []
    merged_accepted_fills = _merge_persistent_accepted_fills(existing_accepted, accepted)
    accepted_lineage_contexts = _lineage_context_by_prediction_id(merged_accepted_fills)
    accepted_replay_predictions = _read_replay_snapshot_predictions(r, accepted_lineage_contexts)
    for prediction_id, replay_prediction in accepted_replay_predictions.items():
        predictions_by_id.setdefault(prediction_id, replay_prediction)
    accepted_feature_snapshots_by_id = _read_feature_snapshots_by_id(r, accepted_lineage_contexts)
    accepted_feature_snapshots_by_id = {
        **_feature_snapshots_from_replay_predictions(accepted_replay_predictions),
        **accepted_feature_snapshots_by_id,
    }
    accepted_for_ledger = _backfill_fill_lineage_from_predictions(
        merged_accepted_fills,
        predictions_by_id,
        feature_snapshots_by_id=accepted_feature_snapshots_by_id,
        require_feature_snapshot_deref=True,
    )
    mark_prices: dict[str, dict[str, Any]] = {}
    for symbol in sorted({str(row.get("symbol") or "").upper() for row in accepted_for_ledger if row.get("symbol")}):
        px, px_source, px_source_utc = _read_v2_market_price(r, symbol)
        exit_microstructure = _read_v2_orderbook_microstructure(r, symbol)
        mark_prices[symbol] = {
            "price": px,
            "source": px_source,
            "source_utc": px_source_utc,
            "actual_observed_spread_exit_bps": exit_microstructure.get("bid_ask_spread_bps"),
            "exit_spread_source": exit_microstructure.get("source"),
            "exit_spread_available_at": exit_microstructure.get("entry_spread_available_at"),
            "microstructure_context": {
                "source": exit_microstructure.get("source"),
                "bid_ask_spread_bps": exit_microstructure.get("bid_ask_spread_bps"),
                "orderbook_imbalance": exit_microstructure.get("orderbook_imbalance"),
            },
        }
    lifecycle_result = reconcile_paper_lifecycle(
        existing_ledger=existing_ledger,
        accepted_fills=accepted_for_ledger,
        mark_prices=mark_prices,
        generated_utc=_utc_iso(),
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=portfolio_context["equity"],
            disable_trailing_on_negative_runtime_expectancy=True,
            trailing_expectancy_evidence_policy_version=PAPER_EXIT_POLICY_VERSION,
        ),
    )
    lifecycle_blocked = list(lifecycle_result["blocked_entries"])
    if lifecycle_blocked:
        blocked.extend(lifecycle_blocked)
    current_accepted_ids = {_accepted_fill_identity(row) for row in accepted}
    accepted_for_ledger = list(lifecycle_result["accepted_open_fills"])
    accepted = [
        row
        for row in accepted_for_ledger
        if _accepted_fill_identity(row) in current_accepted_ids
    ]
    strategy_router_report = summarize_strategy_router_performance(
        accepted_rows=accepted_for_ledger,
        blocked_rows=blocked,
        shadow_rows=shadow_observations,
        held_rows=held_by_gate_intents,
    )
    allocation_rows = [
        row.get("adaptive_allocation")
        for row in intents + blocked + accepted_for_ledger + shadow_observations
        if isinstance(row.get("adaptive_allocation"), dict)
    ]
    allocation_rows = [row for row in allocation_rows if isinstance(row, dict)]
    directional_collapse_guard_status = {
        "guard": DIRECTIONAL_COLLAPSE_GUARD_NAME,
        "enabled": True,
        "paper_only": True,
        "minimum_closed_trades": DIRECTIONAL_COLLAPSE_MIN_CLOSED_TRADES,
        "minimum_side_trades": DIRECTIONAL_COLLAPSE_MIN_SIDE_TRADES,
        "major_side_share_threshold": DIRECTIONAL_COLLAPSE_MAJOR_SIDE_SHARE,
        "evaluated_intent_count": len(directional_guard_evaluations),
        "blocked_majority_side_fill_count": sum(
            1
            for row in directional_guard_evaluations
            if row.get("allowed") is False and row.get("block_reason") == DIRECTIONAL_COLLAPSE_BLOCK_REASON
        ),
        "directional_collapse_detected": any(
            bool(row.get("directional_collapse_detected")) for row in directional_guard_evaluations
        ),
        "sample_evaluations": directional_guard_evaluations[:25],
        "generated_utc": _utc_iso(),
    }
    strategy_mode_collapse_guard_status = {
        "guard": STRATEGY_MODE_COLLAPSE_GUARD_NAME,
        "enabled": True,
        "paper_only": True,
        "minimum_closed_trades": STRATEGY_MODE_COLLAPSE_MIN_CLOSED_TRADES,
        "major_mode_share_threshold": STRATEGY_MODE_COLLAPSE_MAJOR_MODE_SHARE,
        "evaluated_intent_count": len(strategy_mode_guard_evaluations),
        "blocked_majority_mode_fill_count": sum(
            1
            for row in strategy_mode_guard_evaluations
            if row.get("allowed") is False
            and row.get("block_reason") == STRATEGY_MODE_COLLAPSE_BLOCK_REASON
        ),
        "strategy_mode_collapse_detected": any(
            bool(row.get("strategy_mode_collapse_detected"))
            for row in strategy_mode_guard_evaluations
        ),
        "top_mode": next(
            (
                row.get("top_mode")
                for row in strategy_mode_guard_evaluations
                if row.get("top_mode")
            ),
            None,
        ),
        "top_mode_share": next(
            (
                row.get("top_mode_share")
                for row in strategy_mode_guard_evaluations
                if row.get("top_mode_share") is not None
            ),
            None,
        ),
        "mode_counts": next(
            (
                row.get("mode_counts")
                for row in strategy_mode_guard_evaluations
                if isinstance(row.get("mode_counts"), dict)
            ),
            {},
        ),
        "evidence_scope": next(
            (
                row.get("evidence_scope")
                for row in strategy_mode_guard_evaluations
                if row.get("evidence_scope")
            ),
            None,
        ),
        "policy_version": PAPER_EXIT_POLICY_VERSION,
        "policy_version_filter_enabled": any(
            bool(row.get("policy_version_filter_enabled"))
            for row in strategy_mode_guard_evaluations
        ),
        "historical_mode_counts": next(
            (
                row.get("historical_mode_counts")
                for row in strategy_mode_guard_evaluations
                if isinstance(row.get("historical_mode_counts"), dict)
            ),
            {},
        ),
        "active_policy_closed_trade_count": next(
            (
                row.get("active_policy_closed_trade_count")
                for row in strategy_mode_guard_evaluations
                if row.get("active_policy_closed_trade_count") is not None
            ),
            0,
        ),
        "active_policy_mode_counts": next(
            (
                row.get("active_policy_mode_counts")
                for row in strategy_mode_guard_evaluations
                if isinstance(row.get("active_policy_mode_counts"), dict)
            ),
            {},
        ),
        "active_policy_sample_ready": any(
            bool(row.get("active_policy_sample_ready"))
            for row in strategy_mode_guard_evaluations
        ),
        "sample_evaluations": strategy_mode_guard_evaluations[:25],
        "generated_utc": _utc_iso(),
    }
    paper_drawdown_recovery_guard_status = {
        "guard": PAPER_DRAWDOWN_RECOVERY_GUARD_NAME,
        "enabled": True,
        "paper_only": True,
        "live_path_changed": False,
        "minimum_confidence": PAPER_DRAWDOWN_RECOVERY_MIN_CONFIDENCE,
        "recovery_size_multiplier": PAPER_DRAWDOWN_RECOVERY_SIZE_MULTIPLIER,
        "evaluated_intent_count": len(drawdown_recovery_guard_evaluations),
        "eligible_recovery_count": sum(
            1 for row in drawdown_recovery_guard_evaluations if row.get("allowed") is True
        ),
        "recovered_intent_count": sum(
            1 for row in drawdown_recovery_guard_evaluations if row.get("recovered") is True
        ),
        "blocked_reason_counts": _count_values(
            [
                {"block_reason": row.get("block_reason")}
                for row in drawdown_recovery_guard_evaluations
                if row.get("allowed") is not True
            ],
            "block_reason",
        ),
        "sample_evaluations": drawdown_recovery_guard_evaluations[:25],
        "generated_utc": _utc_iso(),
    }
    runtime_admission_rows = blocked + shadow_observations
    paper_runtime_admission_status = {
        "status": "ACTIVE",
        "paper_only": True,
        "intents_built": len(intents),
        "accepted_count": len(accepted),
        "persistent_accepted_fill_count": len(accepted_for_ledger),
        "blocked_count": len(blocked),
        "shadow_observation_count": len(shadow_observations),
        "paper_fill_block_reason_counts": _count_values(blocked, "paper_fill_block_reason"),
        "paper_signal_temporal_rejection_counts": _count_list_values(
            runtime_admission_rows,
            "paper_signal_temporal_rejection_reasons",
        ),
        "paper_runtime_market_evidence_rejection_counts": _count_list_values(
            runtime_admission_rows,
            "paper_runtime_market_evidence_rejection_reasons",
        ),
        "runtime_market_evidence_block_count": sum(
            1
            for row in runtime_admission_rows
            if row.get("paper_runtime_market_evidence_rejection_reasons")
        ),
        "temporal_block_count": sum(
            1 for row in blocked if row.get("paper_signal_temporal_rejection_reasons")
        ),
        "missing_entry_price_block_count": sum(
            1
            for row in blocked
            if row.get("entry_price_blocker") == ENTRY_PRICE_BLOCKER_MISSING_FILL
        ),
        "missing_observed_spread_block_count": sum(
            1
            for row in runtime_admission_rows
            if "MISSING_OBSERVED_SPREAD_AT_DECISION_TIME"
            in (row.get("paper_runtime_market_evidence_rejection_reasons") or [])
        ),
        "missing_expected_slippage_block_count": sum(
            1
            for row in runtime_admission_rows
            if any(
                reason in (row.get("paper_runtime_market_evidence_rejection_reasons") or [])
                for reason in (
                    "MISSING_OBSERVED_OR_MODELED_SLIPPAGE_AT_DECISION_TIME",
                    "MISSING_EXPECTED_SLIPPAGE_AT_DECISION_TIME",
                    "CONSERVATIVE_MISSING_SLIPPAGE_BLOCKING_ESTIMATE",
                )
            )
        ),
        "missing_squeeze_evidence_block_count": sum(
            1
            for row in runtime_admission_rows
            if any(
                reason in (row.get("paper_runtime_market_evidence_rejection_reasons") or [])
                for reason in (
                    "MISSING_SQUEEZE_EVIDENCE_AT_DECISION_TIME",
                    "MISSING_SOURCED_SQUEEZE_EVIDENCE",
                    "MISSING_SQUEEZE_LIQUIDATION_OI_ORDERBOOK_EVIDENCE",
                )
            )
        ),
        "side_counts": _count_values(runtime_admission_rows, "side"),
        "action_counts": _count_values(runtime_admission_rows, "action"),
        "generated_utc": _utc_iso(),
    }
    paper_exploration_tier_status = _paper_exploration_tier_status(
        accepted_rows=accepted_for_ledger,
        blocked_rows=blocked,
        shadow_rows=shadow_observations,
        held_rows=held_by_gate_intents,
    )
    paper_audit_entry_gate_status = {
        "guard": PAPER_AUDIT_ENTRY_GATE_NAME,
        "enabled": True,
        "paper_only": True,
        "blocked_entry_timeframes": sorted(PAPER_AUDIT_BLOCKED_ENTRY_TIMEFRAMES),
        "allowed_entry_timeframes": sorted(PAPER_AUDIT_ALLOWED_ENTRY_TIMEFRAMES),
        "symbol_exclusion_list": sorted(PAPER_AUDIT_SYMBOL_EXCLUSION_LIST),
        "entry_gate_block_count": sum(
            1 for row in blocked if row.get("paper_fill_block_reason") == "P0_ENTRY_GATE_BLOCKED"
        ),
        "audit_timeframe_block_count": sum(
            1
            for row in blocked
            if any(
                str(reason).startswith("TIMEFRAME_BLOCKED:")
                for reason in (row.get("entry_gate_block_reasons") or [])
            )
        ),
        "audit_symbol_block_count": sum(
            1
            for row in blocked
            if any(
                str(reason).startswith("SYMBOL_EXPLICITLY_EXCLUDED_BY_OPERATOR:")
                for reason in (row.get("entry_gate_block_reasons") or [])
            )
        ),
        "block_reason_counts": _count_list_values(blocked, "entry_gate_block_reasons"),
        "live_path_changed": False,
        "generated_utc": _utc_iso(),
    }
    paper_adaptive_sizing_runtime_status = _paper_adaptive_sizing_runtime_status(
        allocation_rows,
    )
    risk_envelope_dynamic_budget_status = {
        "operator_envelope_type": "PERCENTAGE_BASED_RISK_ENVELOPE",
        "equity_source": "v2:portfolio:state",
        "equity": portfolio_context["equity"],
        "available_margin": portfolio_context["available_margin"],
        "drawdown_bps": portfolio_context["drawdown_bps"],
        "static_trade_size_used": False,
        "fixed_200_usdt_runtime_sizing": False,
        "generated_utc": _utc_iso(),
    }
    adaptive_capital_allocator_status = {
        "status": "ACTIVE_FOR_PAPER_AND_LIVE_PRE_SUBMIT",
        "paper_allocator_active": True,
        "live_pre_submit_allocator_active": True,
        "live_submit_changed": False,
        "allocation_outputs": [
            "target_notional_usdt",
            "target_quantity",
            "risk_budget_pct_of_equity",
            "confidence_calibrated",
            "expected_move_after_cost_bps",
            "market_state_integrity_score",
            "volatility_adjustment",
            "liquidity_adjustment",
            "spread_slippage_adjustment",
            "drawdown_adjustment",
            "exposure_adjustment",
            "correlation_adjustment",
            "regime_adjustment",
            "exchange_min_order_adjustment",
            "final_size_reason",
        ],
        "generated_utc": _utc_iso(),
    }
    # Deduplicate by close_id before writing — prevents float-drift duplicates
    # from accumulating when the same close event is processed in multiple loop
    # iterations.  Keep first occurrence (matches portfolio publisher behaviour).
    # Use close_id (authoritative), then paper_close_id, then a composite key
    # of symbol+entry_time+exit_time+side — never bare position_id which is
    # not unique across multiple trades on the same symbol.
    _seen_close_ids: set[str] = set()
    _deduped: list[dict] = []
    for _ct in lifecycle_result["closed_trades"]:
        _cid = (
            _ct.get("close_id")
            or _ct.get("paper_close_id")
            or f"{_ct.get('symbol')}:{_ct.get('entry_time')}:{_ct.get('exit_time')}:{_ct.get('side')}"
        )
        if _cid not in _seen_close_ids:
            _seen_close_ids.add(_cid)
            _deduped.append(_ct)
    closes: list[dict] = _deduped
    open_positions: list[dict] = list(lifecycle_result["open_positions"])
    outcome_labels: list[dict] = list(lifecycle_result["outcome_labels"])
    feedback_lineage_contexts = _lineage_context_by_prediction_id(
        closes,
        outcome_labels,
        accepted_for_ledger,
    )
    feedback_replay_predictions = _read_replay_snapshot_predictions(r, feedback_lineage_contexts)
    for prediction_id, replay_prediction in feedback_replay_predictions.items():
        predictions_by_id.setdefault(prediction_id, replay_prediction)
    feature_snapshots_by_id = _read_feature_snapshots_by_id(r, feedback_lineage_contexts)
    feature_snapshots_by_id = {
        **_feature_snapshots_from_replay_predictions(feedback_replay_predictions),
        **feature_snapshots_by_id,
    }
    trainer_feedback_rows = _build_trainer_feedback_rows(
        close_events=closes,
        outcome_labels=outcome_labels,
        entry_context_rows=accepted_for_ledger,
        predictions_by_id=predictions_by_id,
        feature_snapshots_by_id=feature_snapshots_by_id,
    )
    trainer_feedback_consumable_rows = [
        row for row in trainer_feedback_rows if row.get("trainer_consumable") is True
    ]
    trainer_feedback_quarantine_rows = [
        row for row in trainer_feedback_rows if row.get("trainer_consumable") is not True
    ]
    trainer_strategy_hedge_feedback_status = feedback_status(trainer_feedback_rows)
    trainer_strategy_hedge_feedback_status["trainer_feedback_total_rows"] = len(trainer_feedback_rows)
    trainer_strategy_hedge_feedback_status["trainer_feedback_quarantined_rows"] = len(
        trainer_feedback_quarantine_rows
    )
    paper_closed_trade_outcome_label_status = dict(
        lifecycle_result["paper_closed_trade_outcome_label_status"]
    )
    paper_closed_trade_outcome_label_status.update(
        {
            "trainer_feedback_total_rows": len(trainer_feedback_rows),
            "trainer_feedback_rows_ready": len(trainer_feedback_consumable_rows),
            "trainer_feedback_consumable_rows": len(trainer_feedback_consumable_rows),
            "trainer_feedback_quarantined_rows": len(trainer_feedback_quarantine_rows),
        }
    )
    if r is not None:
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:intents",
            json.dumps(intents),
            ex=PAPER_RUNTIME_TRANSIENT_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:intents")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:intents_held_by_paper_fill_gate",
            json.dumps(held_by_gate_intents),
            ex=PAPER_RUNTIME_TRANSIENT_TTL_SECONDS,
        ):
            keys_written.append(
                f"{V2_REDIS_PREFIX}paper:intents_held_by_paper_fill_gate"
            )
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}risk:decisions",
            json.dumps(risk_decisions),
            ex=PAPER_RUNTIME_TRANSIENT_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}risk:decisions")
        if risk_decisions and _safe_write(
            r,
            f"{V2_REDIS_PREFIX}risk:decisions:latest",
            json.dumps(risk_decisions[0]),
            ex=PAPER_RUNTIME_TRANSIENT_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}risk:decisions:latest")
        ledger_payload = {
            "accepted_count": len(accepted_for_ledger),
            "current_cycle_accepted_count": len(accepted),
            "blocked_count": len(blocked),
            "held_by_paper_fill_gate_count": len(held_by_gate_intents),
            "shadow_observation_count": len(shadow_observations),
            "accepted_position_count": len(open_positions),
            "open_position_count": len(open_positions),
            "closed_trade_count": len(closes),
            "outcome_label_count": len(outcome_labels),
            "trainer_feedback_total_row_count": len(trainer_feedback_rows),
            "trainer_feedback_row_count": len(trainer_feedback_consumable_rows),
            "trainer_feedback_quarantined_row_count": len(trainer_feedback_quarantine_rows),
            "trainer_feedback_consumable_row_count": trainer_strategy_hedge_feedback_status[
                "trainer_consumable_rows"
            ],
            "trainer_strategy_hedge_feedback_status": trainer_strategy_hedge_feedback_status,
            "held_position_count": len(held_by_gate_intents),
            "accepted_intents": accepted_for_ledger,
            "accepted": accepted_for_ledger,
            "current_cycle_accepted": accepted,
            "blocked": blocked,
            "held_by_paper_fill_gate": held_by_gate_intents,
            "shadow_observations": shadow_observations,
            "closes": closes,
            "closed_trades": closes,
            "outcome_labels": outcome_labels,
            "trainer_feedback_outcomes": trainer_feedback_consumable_rows,
            "trainer_feedback_outcomes_quarantine": trainer_feedback_quarantine_rows,
            "open_positions": open_positions,
            "positions_by_symbol": lifecycle_result["positions_by_symbol"],
            "close_event_count": len(closes),
            "new_close_event_count": len(lifecycle_result["new_close_events"]),
            "realized_exit_blocker": None if closes else "NO_CLOSE_TRIGGERED_THIS_CYCLE",
            "realized_pnl_usd": lifecycle_result["realized_pnl_usd"],
            "realized_pnl_usdt": lifecycle_result["realized_pnl_usd"],
            "unrealized_pnl_usd": lifecycle_result["unrealized_pnl_usd"],
            "unrealized_pnl_usdt": lifecycle_result["unrealized_pnl_usd"],
            "total_open_notional": lifecycle_result["total_open_notional"],
            "paper_position_lifecycle_status": lifecycle_result["paper_position_lifecycle_status"],
            "paper_position_exposure_cap_status": lifecycle_result["paper_position_exposure_cap_status"],
            "paper_hedge_netting_status": lifecycle_result["paper_hedge_netting_status"],
            "paper_exit_coordinator_status": lifecycle_result["paper_exit_coordinator_status"],
            "paper_stop_takeprofit_trailing_status": lifecycle_result["paper_stop_takeprofit_trailing_status"],
            "paper_closed_trade_outcome_label_status": paper_closed_trade_outcome_label_status,
            "paper_directional_collapse_guard_status": directional_collapse_guard_status,
            "paper_strategy_mode_collapse_guard_status": strategy_mode_collapse_guard_status,
            "paper_drawdown_recovery_guard_status": paper_drawdown_recovery_guard_status,
            "paper_runtime_admission_status": paper_runtime_admission_status,
            "paper_exploration_tier_status": paper_exploration_tier_status,
            "paper_audit_entry_gate_status": paper_audit_entry_gate_status,
            "paper_adaptive_sizing_runtime_status": paper_adaptive_sizing_runtime_status,
            "risk_envelope_dynamic_budget_status": risk_envelope_dynamic_budget_status,
            "adaptive_capital_allocator_status": adaptive_capital_allocator_status,
            "schema_split": {
                "accepted_positions_must_have_paper_fill_allowed_true": True,
                "accepted_positions_preserve_strict_paper_fill_allowed_upstream": True,
                "b_grade_exploration_positions_are_paper_only": True,
                "b_grade_exploration_positions_have_fractional_normal_budget": True,
                "shadow_observations_have_paper_fill_allowed_false": True,
                "held_by_gate_have_paper_fill_allowed_false": True,
                "recorder_consumes_v2_paper_positions_only_for_accepted_mfe_mae_roe": True,
                "recorder_consumes_v2_paper_positions_only_for_open_net_positions": True,
            },
            "strategy_router_report": strategy_router_report,
            "exit_price_field_contract": {
                "exit_price": "float | null",
                "exit_price_source": "V2_MARKET_PRICES_TICKER_24HR_LAST_PRICE | V2_FEATURES_LATEST_FRESH_CLOSE_PRICE | MISSING_V2_MARKET_PRICE_FOR_EXIT",
                "exit_price_utc": "iso8601 | null",
                "realized_pnl_bps": "float | null (computable from V2-owned entry+exit)",
                "realized_pnl_usdt": "float | null (computable from V2-owned entry+exit+quantity)",
                "close_reason": "string",
                "source_position_id": "string",
                "places_real_order": False,
            },
            "live_gate": live_context["live_gate"],
            "live_symbols": live_context["live_symbols"],
            "execution_live_symbols": live_context["execution_live_symbols"],
            "places_real_order": False,
            "generated_utc": _utc_iso(),
        }
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:ledger",
            json.dumps(ledger_payload),
            ex=PAPER_TRAINING_EVIDENCE_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:ledger")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:positions",
            json.dumps(open_positions),
            ex=PAPER_TRAINING_EVIDENCE_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:positions")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:closed_trades",
            json.dumps(closes),
            ex=PAPER_TRAINING_EVIDENCE_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:closed_trades")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:outcome_labels",
            json.dumps(outcome_labels),
            ex=PAPER_TRAINING_EVIDENCE_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:outcome_labels")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}trainer:feedback:outcomes",
            json.dumps(trainer_feedback_consumable_rows),
            ex=PAPER_TRAINING_EVIDENCE_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}trainer:feedback:outcomes")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}trainer:feedback:outcomes:quarantine",
            json.dumps(trainer_feedback_quarantine_rows),
            ex=PAPER_TRAINING_EVIDENCE_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}trainer:feedback:outcomes:quarantine")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:trade_management:status",
            json.dumps({
                "paper_position_lifecycle_status": lifecycle_result["paper_position_lifecycle_status"],
                "paper_position_exposure_cap_status": lifecycle_result["paper_position_exposure_cap_status"],
                "paper_hedge_netting_status": lifecycle_result["paper_hedge_netting_status"],
                "paper_exit_coordinator_status": lifecycle_result["paper_exit_coordinator_status"],
                "paper_stop_takeprofit_trailing_status": lifecycle_result["paper_stop_takeprofit_trailing_status"],
                "paper_closed_trade_outcome_label_status": paper_closed_trade_outcome_label_status,
                "paper_directional_collapse_guard_status": directional_collapse_guard_status,
                "paper_strategy_mode_collapse_guard_status": strategy_mode_collapse_guard_status,
                "paper_drawdown_recovery_guard_status": paper_drawdown_recovery_guard_status,
                "paper_runtime_admission_status": paper_runtime_admission_status,
                "paper_exploration_tier_status": paper_exploration_tier_status,
                "paper_audit_entry_gate_status": paper_audit_entry_gate_status,
                "paper_adaptive_sizing_runtime_status": paper_adaptive_sizing_runtime_status,
                "risk_envelope_dynamic_budget_status": risk_envelope_dynamic_budget_status,
                "trade_lifecycle_guard_status": {
                    "shared_guard_available": True,
                    "paper_path_using_lifecycle_controls": True,
                    "live_path_changed": False,
                },
                "generated_utc": _utc_iso(),
            }),
            ex=PAPER_RUNTIME_TRANSIENT_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:trade_management:status")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:shadow_observations",
            json.dumps(shadow_observations),
            ex=PAPER_RUNTIME_TRANSIENT_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:shadow_observations")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:strategy_router_report",
            json.dumps(strategy_router_report),
            ex=PAPER_RUNTIME_TRANSIENT_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:strategy_router_report")

    status = {
        "worker_id": "v2_trade_management_paper_loop",
        "schema_version": "v2_trade_management_paper_live_v2",
        "started_at": started,
        "finished_at": _utc_iso(),
        "paper_signals_seen": len(signals),
        "intents_built": len(intents),
        "intents_accepted": len(accepted),
        "persistent_accepted_fill_count": len(accepted_for_ledger),
        "intents_blocked": len(blocked),
        "intents_held_by_paper_fill_gate": len(held_by_gate_intents),
        "shadow_observation_count": len(shadow_observations),
        "accepted_position_count": len(lifecycle_result["open_positions"]),
        "open_position_count": len(lifecycle_result["open_positions"]),
        "closed_trade_count": len(lifecycle_result["closed_trades"]),
        "outcome_label_count": len(lifecycle_result["outcome_labels"]),
        "trainer_feedback_total_row_count": len(trainer_feedback_rows) if r is not None else 0,
        "trainer_feedback_row_count": len(trainer_feedback_consumable_rows) if r is not None else 0,
        "trainer_feedback_quarantined_row_count": (
            len(trainer_feedback_quarantine_rows) if r is not None else 0
        ),
        "trainer_feedback_consumable_row_count": (
            trainer_strategy_hedge_feedback_status["trainer_consumable_rows"]
            if r is not None
            else 0
        ),
        "trainer_strategy_hedge_feedback_status": (
            trainer_strategy_hedge_feedback_status if r is not None else {}
        ),
        "realized_pnl_usd": lifecycle_result["realized_pnl_usd"],
        "unrealized_pnl_usd": lifecycle_result["unrealized_pnl_usd"],
        "total_open_notional": lifecycle_result["total_open_notional"],
        "paper_position_lifecycle_status": lifecycle_result["paper_position_lifecycle_status"],
        "paper_position_exposure_cap_status": lifecycle_result["paper_position_exposure_cap_status"],
        "paper_hedge_netting_status": lifecycle_result["paper_hedge_netting_status"],
        "paper_exit_coordinator_status": lifecycle_result["paper_exit_coordinator_status"],
        "paper_stop_takeprofit_trailing_status": lifecycle_result["paper_stop_takeprofit_trailing_status"],
        "paper_closed_trade_outcome_label_status": paper_closed_trade_outcome_label_status,
        "paper_directional_collapse_guard_status": directional_collapse_guard_status,
        "paper_strategy_mode_collapse_guard_status": strategy_mode_collapse_guard_status,
        "paper_drawdown_recovery_guard_status": paper_drawdown_recovery_guard_status,
        "paper_runtime_admission_status": paper_runtime_admission_status,
        "paper_exploration_tier_status": paper_exploration_tier_status,
        "paper_audit_entry_gate_status": paper_audit_entry_gate_status,
        "paper_adaptive_sizing_runtime_status": paper_adaptive_sizing_runtime_status,
        "risk_envelope_dynamic_budget_status": risk_envelope_dynamic_budget_status,
        "adaptive_capital_allocator_status": adaptive_capital_allocator_status,
        "trade_lifecycle_guard_status": {
            "shared_guard_available": True,
            "paper_path_using_lifecycle_controls": True,
            "live_path_changed": False,
        },
        "held_position_count": len(held_by_gate_intents),
        "strategy_router_report": strategy_router_report,
        "strategy_router_mode_counts": strategy_router_report["mode_counts"],
        "strategy_router_regime_counts": strategy_router_report["regime_counts"],
        "strategy_router_blocked_trade_count": strategy_router_report["blocked_trade_count"],
        "strategy_router_data_quality_block_count": strategy_router_report["data_quality_block_count"],
        "strategy_router_masa_ppo_disagreement_count": strategy_router_report["masa_ppo_disagreement_count"],
        "held_by_paper_fill_gate": held_by_gate_intents,
        "shadow_observations": shadow_observations,
        "v2_paper_keys_written": keys_written,
        "v2_paper_keys_written_count": len(keys_written),
        "classification": (
            "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK"
            if intents else
            ("BLOCKED_BY_REDIS_UNAVAILABLE" if r is None else "NO_PAPER_SIGNALS_PRESENT")
        ),
        "live_gate": live_context["live_gate"],
        "live_symbols": live_context["live_symbols"],
        "execution_live_symbols": live_context["execution_live_symbols"],
        "live_gate_runtime_context": live_context,
        "approves_live": False,
        "approves_legacy_shutdown": False,
        "places_real_order": False,
        "writes_legacy_redis": False,
    }
    if r is not None:
        _safe_write(r, f"{V2_REDIS_PREFIX}paper:heartbeat", json.dumps(status), ex=300)
    try:
        write_payload(
            lifecycle_result["paper_position_lifecycle_status"],
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_position_lifecycle_status.json",
        )
        write_payload(
            lifecycle_result["paper_position_exposure_cap_status"],
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_position_exposure_cap_status.json",
        )
        write_payload(
            lifecycle_result["paper_hedge_netting_status"],
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_hedge_netting_status.json",
        )
        write_payload(
            lifecycle_result["paper_exit_coordinator_status"],
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_exit_coordinator_status.json",
        )
        write_payload(
            lifecycle_result["paper_stop_takeprofit_trailing_status"],
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_stop_takeprofit_trailing_status.json",
        )
        write_payload(
            paper_closed_trade_outcome_label_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_closed_trade_outcome_label_status.json",
        )
        write_payload(
            directional_collapse_guard_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_directional_collapse_guard_status.json",
        )
        write_payload(
            paper_drawdown_recovery_guard_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_drawdown_recovery_guard_status.json",
        )
        write_payload(
            {
                "outcome_labels": lifecycle_result["outcome_labels"],
                "new_outcome_labels": lifecycle_result["new_outcome_labels"],
                "generated_utc": _utc_iso(),
                "paper_only": True,
            },
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_outcome_labels.json",
        )
        write_payload(
            {
                "trainer_feedback_outcomes": trainer_feedback_consumable_rows,
                "trainer_feedback_outcomes_quarantine": trainer_feedback_quarantine_rows,
                "trainer_strategy_hedge_feedback_status": trainer_strategy_hedge_feedback_status,
                "generated_utc": _utc_iso(),
                "paper_only": True,
                "places_real_order": False,
            },
            TRADE_MANAGEMENT_PUBLIC_DIR / "trainer_feedback_outcomes.json",
        )
        write_payload(
            {
                "shared_guard_available": True,
                "paper_path_using_lifecycle_controls": True,
                "live_path_changed": False,
                "generated_utc": _utc_iso(),
            },
            TRADE_MANAGEMENT_PUBLIC_DIR / "trade_lifecycle_guard_status.json",
        )
        write_payload(
            adaptive_capital_allocator_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "adaptive_capital_allocator_status.json",
        )
        write_payload(
            paper_adaptive_sizing_runtime_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_adaptive_sizing_runtime_status.json",
        )
        write_payload(
            paper_exploration_tier_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_exploration_tier_status.json",
        )
        write_payload(
            risk_envelope_dynamic_budget_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "risk_envelope_dynamic_budget_status.json",
        )
        write_payload(
            paper_audit_entry_gate_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_audit_entry_gate_status.json",
        )
    except OSError:
        status["public_status_write_error"] = True
    return status


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _try_acquire_loop_lock(path: Path = PAPER_LOOP_LOCK_PATH) -> TextIO | None:
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    handle = path.open("r+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    lock_payload = {
        "classification": "V2_TRADE_MANAGEMENT_PAPER_LOOP_LOCK_HELD",
        "acquired_utc": _utc_iso(),
        "pid": os.getpid(),
        "paper_only": True,
        "places_real_order": False,
        "writes_legacy_redis": False,
    }
    handle.seek(0)
    handle.truncate()
    handle.write(json.dumps(lock_payload, sort_keys=True) + "\n")
    handle.flush()
    return handle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_trade_management_paper_loop")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        loop_lock_handle = _try_acquire_loop_lock()
        if loop_lock_handle is None:
            print(json.dumps({
                "classification": "V2_TRADE_MANAGEMENT_PAPER_LOOP_ALREADY_RUNNING",
                "generated_utc": _utc_iso(),
                "pid": os.getpid(),
                "lock_path": str(PAPER_LOOP_LOCK_PATH),
                "out_path_not_written": str(args.out),
                "paper_only": True,
                "places_real_order": False,
                "writes_legacy_redis": False,
            }, sort_keys=True))
            return 0
        while True:
            hb = run_once()
            write_payload(hb, args.out)
            time.sleep(max(5, int(args.interval_seconds)))
    hb = run_once()
    write_payload(hb, args.out)
    print(json.dumps({
        "classification": hb["classification"],
        "intents_built": hb["intents_built"],
        "intents_accepted": hb["intents_accepted"],
        "v2_paper_keys_written_count": hb["v2_paper_keys_written_count"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
