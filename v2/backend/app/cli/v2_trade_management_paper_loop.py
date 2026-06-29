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
import math
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
PAPER_ACCEPTED_FILLS_STATE_PATH = TRADE_MANAGEMENT_PUBLIC_DIR / "paper_accepted_fills_state.json"
PAPER_LIFECYCLE_STATE_PATH = TRADE_MANAGEMENT_PUBLIC_DIR / "paper_lifecycle_state.json"
PAPER_FORWARD_CANARY_CLOSED_OUTCOME_ARCHIVE_PATH = (
    TRADE_MANAGEMENT_PUBLIC_DIR / "paper_forward_canary_closed_outcome_archive.json"
)
PAPER_FORWARD_CANARY_CUTOVER_MARKER_PATH = (
    TRADE_MANAGEMENT_PUBLIC_DIR / "paper_forward_canary_cutover_marker.json"
)
PAPER_B_GRADE_BUCKET_PROMOTION_READINESS_STATUS_PATH = (
    TRADE_MANAGEMENT_PUBLIC_DIR / "paper_b_grade_bucket_promotion_readiness_status.json"
)
PAPER_TRAINER_MODEL_QUALITY_RUNTIME_STATUS_PATH = (
    TRADE_MANAGEMENT_PUBLIC_DIR / "trainer_model_quality_runtime_status.json"
)
PREDICTION_STALE_SECONDS = 900
PAPER_SIGNAL_STALE_SECONDS = PREDICTION_STALE_SECONDS
PAPER_SIGNAL_ADAPTIVE_STALE_OPERATOR_MIN_SECONDS = 120
PAPER_SIGNAL_ADAPTIVE_STALE_CANDLE_MULTIPLIER = 3
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
MISSING_THESIS_TIMEFRAME_BLOCK_REASON = "MISSING_THESIS_TIMEFRAME"
UNKNOWN_THESIS_TIMEFRAME = "UNKNOWN"
PAPER_EXECUTION_TIMING_TIMEFRAME = "1m"
PAPER_STANDALONE_1M_BLOCK_REASON = "standalone_1m_thesis_requires_dedicated_strategy_bucket"
PAPER_STANDALONE_1M_GATE_BLOCK_REASON = "PAPER_STANDALONE_1M_ELIGIBILITY_BLOCKED"
PAPER_REENTRY_DEDUP_GATE_BLOCK_REASON = "PAPER_REENTRY_DEDUP_BLOCKED"
PAPER_REENTRY_DEDUP_RUNTIME_LOOKBACK_ROWS = 1500
PAPER_CONFIGURED_FEE_SCHEDULE_SOURCE = (
    "CONFIGURED_PAPER_FEE_SCHEDULE:"
    "adaptive_capital_allocator.AllocationInput.fee_bps"
)
PAPER_RUNTIME_TRANSIENT_TTL_SECONDS = 10 * 60
PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS = 60 * 60
SHADOW_OBSERVATION_HISTORY_TTL_SECONDS = 2 * 60 * 60
SHADOW_OBSERVATION_HISTORY_MAX_ROWS = 1500
PAPER_TRAINING_EVIDENCE_TTL_SECONDS = 30 * 24 * 60 * 60
PAPER_REDIS_LEDGER_ROW_SAMPLE_LIMIT = 50
PAPER_STATE_FULL_FILE_READ_MAX_BYTES = int(os.getenv("PAPER_STATE_FULL_FILE_READ_MAX_BYTES", "25000000"))
PAPER_REDIS_HISTORY_READ_MAX_BYTES = int(os.getenv("PAPER_REDIS_HISTORY_READ_MAX_BYTES", "75000000"))
PAPER_AUDIT_ENTRY_GATE_NAME = "PAPER_ONLY_2026_06_19_AUDIT_ENTRY_GATE"
PAPER_AUDIT_TIMEFRAME_POLICY = "DYNAMIC_OUTCOME_MEMORY_NATIVE_TIMEFRAMES"
PAPER_AUDIT_DEPRECATED_STATIC_BLOCKED_ENTRY_TIMEFRAMES = frozenset({"5m", "4h"})
PAPER_AUDIT_BLOCKED_ENTRY_TIMEFRAMES = frozenset()
PAPER_AUDIT_ALLOWED_ENTRY_TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h", "4h"})
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
CHALLENGER_V2_FROZEN_CANDIDATE_ID = "challenger_v2_338f76bd071ba8ddfadb5d38"
CHALLENGER_V2_PREVIOUS_ACTIVE_CUDA_CANDIDATE_ID = "challenger_v2_cuda_c4b8fb1ed12aabcb87224723"
CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID = "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e"
CHALLENGER_V2_MODEL_SOURCE = "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"
PAPER_POLICY_OWNER_CHALLENGER_V2 = "challenger_v2"
PAPER_POLICY_OWNER_OLD_POLICY = "old_policy"
PAPER_POLICY_OWNER_SHADOW_ONLY = "shadow_only"
PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER = "unattributed_pre_owner_cutover"
PAPER_RUNTIME_OWNER_BLOCK_REASON = "PAPER_RUNTIME_OWNER_NOT_ACTIVE_CHALLENGER_V2"
UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID = "unattributed_pre_owner_cutover"
UNATTRIBUTED_PRE_CUTOVER_POLICY_FINGERPRINT = "UNATTRIBUTED_PRE_OWNER_CUTOVER"
UNATTRIBUTED_PRE_CUTOVER_MODEL_SOURCE = "unknown_pre_owner_cutover"
CHALLENGER_B_GRADE_PAPER_CANARY = "CHALLENGER_B_GRADE_PAPER_CANARY"
NON_EXECUTABLE_PAPER_TIERS = {
    PAPER_TIER_SHADOW_ONLY,
    PAPER_TIER_NO_TRADE,
}
CONTINUOUS_EDGE_GUARDIAN_GATE_REDIS_KEY = "v2:continuous_edge_guardian:a_grade_execution_gate"
CONTINUOUS_EDGE_GUARDIAN_STATUS_REDIS_KEY = "v2:continuous_edge_guardian:status"
CONTINUOUS_EDGE_GUARDIAN_GATE_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_continuous_edge_guardian/latest/a_grade_execution_gate.json"
)
OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT = (
    "c4b8fb1ed12aabcb87224723f1758563eefff10de90288be09866d2bf3fa74b5"
)
CHALLENGER_V2_PREVIOUS_ACTIVE_CUDA_POLICY_FINGERPRINT = OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT
CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT = (
    "83d35e31eea385da1a283b8efab3102ac292be2904724d11777f2b7a32e68630"
)
PAPER_OWNER_ATTRIBUTION_REQUIRED_FIELDS = (
    "candidate_id",
    "policy_id",
    "paper_policy_owner",
    "policy_fingerprint",
    "model_source",
)
PAPER_OWNER_ATTRIBUTION_METADATA_FIELDS = (
    "paper_owner_attribution_status",
    "paper_owner_attribution_missing_fields",
    "paper_owner_attribution_complete",
    "paper_owner_attribution_blocks_challenger_credit",
    "current_allowed_paper_owner",
)
RUNTIME_COST_CAPTURE_CONTRACT_FIELDS = (
    "candidate_id",
    "policy_id",
    "paper_policy_owner",
    "policy_fingerprint",
    "selector_policy_fingerprint",
    "frozen_selector_fingerprint",
    "model_source",
    "snapshot_id",
    "predicted_direction",
    "predicted_move",
    "predicted_move_bps",
    "score",
    "challenger_canary_id",
    "challenger_canary_profile",
    "paper_canary_profile",
    "paper_canary_adaptive_sizing_required",
    "paper_canary_fixed_notional_allowed",
    "paper_canary_live_routing_allowed",
    "paper_policy_owner_open_allowed",
    "paper_policy_owner_open_block_reason",
    "order_size",
    "order_size_usd",
    "gross_notional_usd",
    "allocated_margin_usd",
    "recommended_leverage",
    "recommended_margin_mode",
    "observed_bid",
    "observed_ask",
    "observed_spread_bps",
    "actual_observed_spread_entry_bps",
    "top_book_bid_depth_usd",
    "top_book_ask_depth_usd",
    "market_depth_usd",
    "orderbook_depth_usd",
    "depth_derived_price_impact_bps",
    "depth_price_impact_bps",
    "maker_taker_assumption",
    "maker_taker_probability",
    "maker_taker_probability_detail",
    "maker_probability",
    "taker_probability",
    "fee_schedule",
    "fee_bps",
    "fee_bps_source",
    "fee_bps_readonly_schedule",
    "fee_bps_configured_schedule",
    "funding_rate",
    "funding_interval_seconds",
    "expected_funding_bps",
    "expected_funding_bps_source",
    "holding_period_funding_bps",
    "holding_period_funding_source",
    "expected_slippage_bps",
    "expected_slippage_source",
    "latency_reserve_bps",
    "latency_reserve_source",
    "latency_ms",
    "partial_fill_estimate",
    "partial_fill_probability",
    "partial_fill_adjustment_bps",
    "execution_probability",
    "mark_price",
    "index_price",
    "mark_index_divergence_bps",
    "mark_index_source",
    "cost_source",
    "cost_source_timestamp",
    "source_timestamp",
    "cost_evidence_freshness_ms",
    "cost_evidence_source_fields",
    "runtime_cost_capture_source",
    "runtime_cost_capture_status",
    "runtime_cost_capture_required_fields",
    "runtime_cost_capture_missing_fields",
    "runtime_cost_capture_explained_missing_fields",
    "runtime_cost_capture_unexplained_missing_fields",
    "runtime_cost_capture_order_cost_applicable",
    "runtime_cost_capture_no_order_reason",
    "runtime_cost_capture_temporal_reject_reasons",
    "fallback_cost_flag",
    "fallback",
    "production_grade_cost_flag",
    "production_grade_cost_evidence",
    "estimated_production_cost",
    "estimated_production_cost_bps",
    "counts_as_production_grade_training_evidence",
    "routes_to_live",
    "counts_as_a_grade_evidence",
    "a_grade_promotion_allowed",
    "paper_only",
    "places_real_order",
    "live_order",
    "test_order",
)
DEPTH_PRICE_IMPACT_EVIDENCE_FIELDS = (
    "depth_derived_price_impact_bps",
    "depth_price_impact_bps",
    "depth_price_impact_source",
    "depth_price_impact_model",
    "depth_price_impact_side",
    "depth_price_impact_quantity",
    "depth_price_impact_filled_quantity",
    "depth_price_impact_fill_complete",
    "depth_price_impact_vwap",
    "depth_price_impact_touch_price",
    "depth_utilization_pct",
)
PAPER_OPPORTUNITY_TIERS = (
    PAPER_TIER_A_GRADE_EXECUTION,
    PAPER_TIER_B_GRADE_EXPLORATION,
    PAPER_TIER_SHADOW_ONLY,
    PAPER_TIER_NO_TRADE,
)
PAPER_STRICT_A_CONFIDENCE_THRESHOLD = 0.75
B_GRADE_EXPLORATION_MIN_CONFIDENCE = 0.50
B_GRADE_EXPLORATION_ADAPTIVE_CONFIDENCE_FLOOR_MAX = 0.74
B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL = 0.25
B_GRADE_EXPLORATION_DRAWDOWN_STOP_BPS = 500.0
B_GRADE_MODEL_QUALITY_BUCKET_LIMIT = 250
B_GRADE_BUCKET_PROMOTION_MIN_SAMPLE_COUNT = 30
B_GRADE_BUCKET_PROMOTION_MIN_WIN_RATE = 0.90
B_GRADE_BUCKET_PROMOTION_MIN_WIN_RATE_LCB = 0.90
B_GRADE_BUCKET_PROMOTION_MIN_EXPECTANCY_LCB_BPS = 0.0
B_GRADE_BUCKET_PROMOTION_MIN_PROFIT_FACTOR = 2.0
FORWARD_CANARY_REQUIRED_ECONOMIC_OUTCOMES = 100
FORWARD_CANARY_REQUIRED_SYMBOLS = 20
PAPER_ONLY_LABEL_COLLECTION_PRIORITY_FIELDS = (
    "paper_only_label_collection_priority",
    "paper_only_label_collection_priority_reason",
    "paper_only_label_collection_priority_rank",
    "paper_only_label_collection_priority_bucket_key",
    "paper_only_label_collection_priority_bucket",
    "paper_only_label_collection_priority_sample_count_deficit_to_minimum",
    "paper_only_label_collection_priority_closed_economic_outcome_count",
    "paper_only_label_collection_priority_source_generated_utc",
)
PAPER_STANDALONE_1M_ELIGIBILITY_FIELDS = (
    "paper_standalone_1m_eligibility",
    "paper_standalone_1m_eligibility_blocked",
    "paper_standalone_1m_eligibility_blockers",
)
LONG_SHORT_RATIO_CONTEXT_FIELDS = (
    "long_short_ratio",
    "long_account_ratio",
    "short_account_ratio",
    "long_short_period",
    "long_short_source",
    "long_short_event_time",
    "long_short_available_at",
    "long_short_captured_at",
    "long_short_decision_time",
    "long_short_ratio_status",
    "long_short_ratio_decision_effect",
    "rejected_long_short_period",
    "rejected_long_short_source",
    "rejected_long_short_event_time",
    "rejected_long_short_available_at",
    "rejected_long_short_captured_at",
    "rejected_long_short_decision_time",
)
PAPER_SOURCE_TIER_GUARDIAN_CONTEXT_FIELDS = (
    "source_tier",
    "policy_tier",
    "capital_class",
    "pre_guardian_source_tier",
    "pre_guardian_policy_tier",
    "guardian_status",
    "guardian_new_entries_allowed",
    "guardian_block_reasons",
    "guardian_allowed_runtime_actions",
    "continuous_edge_guardian_status",
    "continuous_edge_guardian_new_entries_allowed",
    "continuous_edge_guardian_block_reasons",
    "continuous_edge_guardian_allowed_runtime_actions",
)
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
RARE_EVENT_STRESS_SCENARIOS = (
    "gap_shock",
    "spread_explosion",
    "depth_collapse",
    "funding_spike",
    "correlated_portfolio_shock",
    "long_squeeze",
    "short_squeeze",
    "double_sided_liquidation_cascade",
    "mark_index_divergence",
    "exchange_api_delay",
)
RARE_EVENT_BUFFER_COMPONENT_FIELDS = (
    "execution_uncertainty_bps",
    "correlation_stress_bps",
    "maintenance_margin_uncertainty_bps",
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


def _configured_paper_fee_bps() -> float:
    from v2.backend.app.services.adaptive_capital_allocator import AllocationInput

    return float(AllocationInput.__dataclass_fields__["fee_bps"].default)


def _fee_bps_from_readonly_schedule(
    schedule: dict[str, Any] | None,
) -> tuple[float | None, str | None]:
    if not isinstance(schedule, dict):
        return None, None
    source = str(
        _first_present(
            schedule.get("source"),
            schedule.get("redis_key"),
            schedule.get("fee_schedule_source"),
            "READ_ONLY_FEE_SCHEDULE",
        )
    )
    for key in (
        "taker_fee_bps",
        "fee_bps",
        "expected_fee_bps",
        "actual_fee_bps",
        "commission_bps",
    ):
        parsed = _coerce_float(schedule.get(key))
        if parsed is not None:
            return parsed, f"{source}.{key}"
    for key in ("taker_fee_rate", "fee_rate", "commission_rate"):
        parsed = _coerce_float(schedule.get(key))
        if parsed is not None:
            return parsed * 10000.0, f"{source}.{key}:rate_to_bps"
    return None, None


def _read_readonly_fee_schedule_context(
    redis_client: Any | None,
    *,
    symbol: str,
) -> dict[str, Any]:
    if redis_client is None:
        return {}
    sym = str(symbol or "").upper().strip()
    keys = [
        f"{V2_REDIS_PREFIX}account:fee_schedule:{sym}",
        f"{V2_REDIS_PREFIX}exchange:fee_schedule:{sym}",
        f"{V2_REDIS_PREFIX}market:fee_schedule:{sym}",
        f"{V2_REDIS_PREFIX}fee_schedule:{sym}",
        f"{V2_REDIS_PREFIX}account:fee_schedule",
        f"{V2_REDIS_PREFIX}exchange:fee_schedule",
        f"{V2_REDIS_PREFIX}market:fee_schedule",
        f"{V2_REDIS_PREFIX}fee_schedule",
    ]
    for key in keys:
        if not sym and key.endswith(":"):
            continue
        try:
            raw = redis_client.get(key)
        except Exception:  # noqa: BLE001
            continue
        if not raw:
            continue
        try:
            decoded = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        candidates: list[dict[str, Any]] = []
        if isinstance(decoded, dict):
            if isinstance(decoded.get(sym), dict):
                candidates.append(decoded[sym])
            for container_key in ("symbols", "fees", "fee_schedules", "data"):
                container = decoded.get(container_key)
                if isinstance(container, dict) and isinstance(container.get(sym), dict):
                    candidates.append(container[sym])
            candidates.append(decoded)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            payload = dict(candidate)
            payload.setdefault("source", f"READ_ONLY_FEE_SCHEDULE_REDIS:{key}")
            if _fee_bps_from_readonly_schedule(payload)[0] is not None:
                return payload
    return {}


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
    "pre_guardian_paper_opportunity_tier",
    "pre_guardian_paper_opportunity_tier_reason",
    "pre_guardian_paper_fill_allowed_source",
    "continuous_edge_guardian_forced_shadow_only",
    "counts_as_a_grade_evidence",
    "a_grade_promotion_allowed",
    "live_ready_implication",
    "paper_only_label_collection_priority",
    "paper_only_label_collection_priority_reason",
    "paper_only_label_collection_priority_rank",
    "paper_only_label_collection_priority_bucket_key",
    "paper_only_label_collection_priority_bucket",
    "paper_only_label_collection_priority_sample_count_deficit_to_minimum",
    "paper_only_label_collection_priority_closed_economic_outcome_count",
    "paper_only_label_collection_priority_source_generated_utc",
    *PAPER_STANDALONE_1M_ELIGIBILITY_FIELDS,
    *LONG_SHORT_RATIO_CONTEXT_FIELDS,
    *PAPER_SOURCE_TIER_GUARDIAN_CONTEXT_FIELDS,
    "selector_policy_fingerprint",
    "frozen_selector_fingerprint",
    "candidate_selected_before_outcome",
    "candidate_selected_after_outcome",
    "post_outcome_candidate_selection",
    "future_labels_used_as_features",
    "paper_fill_allowed_source",
    "strict_paper_fill_allowed_upstream",
    "b_grade_exploration_budget_cap_applied",
    "risk_budget_fraction_of_normal_adaptive",
    "b_grade_exploration_static_confidence_floor",
    "b_grade_exploration_adaptive_confidence_floor",
    "b_grade_exploration_floor_mode",
    "b_grade_exploration_confidence_floor_pass",
    "normal_adaptive_risk_budget_usd",
    "normal_adaptive_gross_notional_usd",
    "calibration_label_purpose",
    "original_fill_utc",
    "fill_price_utc",
    "lineage_backfilled_from_prediction_id",
    *RUNTIME_COST_CAPTURE_CONTRACT_FIELDS,
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


def _paper_runtime_owner_identity() -> dict[str, Any]:
    return {
        "candidate_id": CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "policy_id": CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "paper_policy_owner": PAPER_POLICY_OWNER_CHALLENGER_V2,
        "policy_fingerprint": CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "selector_policy_fingerprint": OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
        "frozen_selector_fingerprint": OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
        "model_source": CHALLENGER_V2_MODEL_SOURCE,
        "current_allowed_paper_owner": PAPER_POLICY_OWNER_CHALLENGER_V2,
    }


def _write_paper_runtime_heartbeat(
    r,
    *,
    started_at: str,
    cycle_state: str,
    extra: dict[str, Any] | None = None,
) -> bool:
    payload: dict[str, Any] = {
        "worker_id": "v2_trade_management_paper_loop",
        "schema_version": "v2_trade_management_paper_heartbeat_v2",
        "started_at": started_at,
        "finished_at": None,
        "heartbeat_generated_at": _utc_iso(),
        "cycle_state": cycle_state,
        "heartbeat_ttl_seconds": PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS,
        "classification": "V2_TRADE_MANAGEMENT_PAPER_CYCLE_RUNNING",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "writes_legacy_redis": False,
        **_paper_runtime_owner_identity(),
    }
    if extra:
        payload.update(extra)
    return _safe_write(
        r,
        f"{V2_REDIS_PREFIX}paper:heartbeat",
        json.dumps(payload),
        ex=PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS,
    )


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


def _read_json_list_key(r, key: str) -> list[dict[str, Any]]:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return []
    try:
        raw = r.get(key)
    except Exception:
        return []
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [dict(row) for row in payload if isinstance(row, dict)]


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


def _paper_signal_timeframe_duration_seconds(timeframe: Any) -> int | None:
    value = str(timeframe or "").strip().lower()
    if len(value) < 2:
        return None
    unit = value[-1]
    raw_amount = value[:-1]
    try:
        amount = float(raw_amount)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    unit_seconds = {
        "m": 60,
        "h": 60 * 60,
        "d": 24 * 60 * 60,
    }.get(unit)
    if unit_seconds is None:
        return None
    return int(amount * unit_seconds)


def _paper_signal_adaptive_stale_policy(
    signal: dict[str, Any],
    prediction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prediction = prediction if isinstance(prediction, dict) else {}
    timeframe = _paper_thesis_timeframe(signal, prediction)
    timeframe_seconds = _paper_signal_timeframe_duration_seconds(timeframe)
    static_max_seconds = int(PAPER_SIGNAL_STALE_SECONDS)
    if timeframe_seconds is None:
        adaptive_seconds = static_max_seconds
        mode = "STATIC_OPERATOR_MAX_WHEN_TIMEFRAME_UNKNOWN"
    else:
        raw_seconds = timeframe_seconds * PAPER_SIGNAL_ADAPTIVE_STALE_CANDLE_MULTIPLIER
        adaptive_seconds = int(min(static_max_seconds, raw_seconds))
        adaptive_seconds = max(
            PAPER_SIGNAL_ADAPTIVE_STALE_OPERATOR_MIN_SECONDS,
            adaptive_seconds,
        )
        adaptive_seconds = min(static_max_seconds, adaptive_seconds)
        mode = "TIMEFRAME_CONTEXTUAL_FAIL_CLOSED_NEVER_ABOVE_STATIC"
    return {
        "threshold_id": "paper_signal_stale_seconds",
        "static_operator_max_seconds": static_max_seconds,
        "operator_min_seconds": PAPER_SIGNAL_ADAPTIVE_STALE_OPERATOR_MIN_SECONDS,
        "timeframe": timeframe,
        "timeframe_seconds": timeframe_seconds,
        "adaptive_stale_seconds": adaptive_seconds,
        "adaptive_never_above_static": adaptive_seconds <= static_max_seconds,
        "adaptive_stricter_than_static": adaptive_seconds < static_max_seconds,
        "threshold_lowering_to_force_trades": False,
        "mode": mode,
    }


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
        stale_policy = _paper_signal_adaptive_stale_policy(row)
        stale_seconds = int(stale_policy["adaptive_stale_seconds"])
        if generated is not None and (now - generated).total_seconds() > stale_seconds:
            return f"STALE_SIGNAL_GT_{stale_seconds}s_ADAPTIVE_EXCLUDED_FROM_PAPER_ADMISSION"
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
MARK_INDEX_SOURCE_V2_FUNDING = "V2_MARKET_FUNDING_PREMIUM_INDEX"
PAPER_IMMEDIATE_FILL_TAKER_SOURCE = "PAPER_MARKETABLE_SINGLE_FILL_FROM_OBSERVED_SPREAD_AND_V2_PRICE"


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


def _level_price_quantity(row: Any) -> tuple[float | None, float | None]:
    if isinstance(row, (list, tuple)) and len(row) > 1:
        return _coerce_float(row[0]), _coerce_float(row[1])
    if isinstance(row, dict):
        return (
            _coerce_float(row.get("price") or row.get("p")),
            _coerce_float(row.get("quantity") or row.get("qty") or row.get("q")),
        )
    return None, None


def _top_depth_levels(levels: Any, *, depth: int = 5) -> list[dict[str, float]]:
    if not isinstance(levels, list) or not levels:
        return []
    normalized: list[dict[str, float]] = []
    for row in levels[:depth]:
        price, quantity = _level_price_quantity(row)
        if price is None or quantity is None or price <= 0.0 or quantity <= 0.0:
            continue
        normalized.append({"price": float(price), "quantity": float(quantity)})
    return normalized


def _top_depth_quantity(levels: Any, *, depth: int = 5) -> float | None:
    if not isinstance(levels, list) or not levels:
        return None
    total = 0.0
    seen = 0
    for row in levels[:depth]:
        _price, qty = _level_price_quantity(row)
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
        price, qty = _level_price_quantity(row)
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
        bid_levels_top5 = _top_depth_levels(bids)
        ask_levels_top5 = _top_depth_levels(asks)
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
        captured_at = _utc_iso()
        return {
            "source": f"{ENTRY_SPREAD_SOURCE_V2_ORDERBOOK}:{key}",
            "bid_ask_spread_bps": round(float(spread_bps), 8),
            "best_bid": bid,
            "best_ask": ask,
            "mid_price": mid,
            "bid_levels_top5": bid_levels_top5,
            "ask_levels_top5": ask_levels_top5,
            "orderbook_imbalance": imbalance,
            "bid_depth_usd": round(float(bid_depth_usd), 8) if bid_depth_usd is not None else None,
            "ask_depth_usd": round(float(ask_depth_usd), 8) if ask_depth_usd is not None else None,
            "orderbook_depth_usd": round(float(top_depth_usd), 8) if top_depth_usd is not None else None,
            "top_of_book_depth_usd": round(float(top_depth_usd), 8) if top_depth_usd is not None else None,
            "market_depth_usd": round(float(top_depth_usd), 8) if top_depth_usd is not None else None,
            "orderbook_depth_source": f"{key}:top5_notional_usd" if top_depth_usd is not None else None,
            "entry_spread_available_at": available_at,
            "entry_spread_captured_at": captured_at,
            "entry_spread_decision_time": captured_at,
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


def _timestamp_to_utc_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    parsed_epoch = _iso_from_epoch_ms(value)
    if parsed_epoch is not None:
        return parsed_epoch
    parsed = _parse_strategy_time(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_v2_mark_index_evidence(r, symbol: str) -> dict[str, Any]:
    """Read Binance premium-index mark/index evidence from V2-owned keys."""
    if r is None or not symbol:
        return {}
    normalized = str(symbol).upper()
    for key in (
        f"{V2_REDIS_PREFIX}market:funding:{normalized}",
        f"{V2_REDIS_PREFIX}market:prices:{normalized}",
    ):
        payload = _read_json_key(r, key)
        if not payload:
            continue
        source_payload = (
            payload.get("funding")
            if isinstance(payload.get("funding"), dict)
            else payload
        )
        if not isinstance(source_payload, dict):
            continue
        mark = _coerce_float(_first_present(source_payload.get("markPrice"), source_payload.get("mark_price")))
        index = _coerce_float(_first_present(source_payload.get("indexPrice"), source_payload.get("index_price")))
        if mark is None or index is None or mark <= 0.0 or index <= 0.0:
            continue
        divergence = (mark - index) / index
        available_at = _timestamp_to_utc_iso(
            _first_present(
                source_payload.get("time"),
                source_payload.get("timestamp"),
                source_payload.get("E"),
                source_payload.get("event_time"),
                payload.get("fetched_utc"),
                payload.get("generated_at"),
            )
        )
        return {
            "mark_price": mark,
            "index_price": index,
            "mark_index_divergence": round(divergence, 12),
            "mark_index_divergence_bps": round(divergence * 10_000.0, 8),
            "mark_index_source": f"{MARK_INDEX_SOURCE_V2_FUNDING}:{key}",
            "mark_index_available_at": available_at,
        }
    return {}


def _read_v2_long_short_ratio_evidence(r, symbol: str) -> dict[str, Any]:
    """Read V2-owned global long/short account-ratio telemetry."""
    if r is None or not symbol:
        return {}
    normalized = str(symbol).upper()
    key = f"{V2_REDIS_PREFIX}market:long_short:{normalized}"
    payload = _read_json_key(r, key)
    if not payload:
        return {}
    ratio = _coerce_float(_first_present(payload.get("long_short_ratio"), payload.get("longShortRatio")))
    if ratio is None or ratio <= 0.0:
        return {}
    long_account = _coerce_float(_first_present(payload.get("long_account_ratio"), payload.get("longAccount")))
    short_account = _coerce_float(_first_present(payload.get("short_account_ratio"), payload.get("shortAccount")))
    source_event_time = _timestamp_to_utc_iso(
        _first_present(
            payload.get("timestamp"),
            payload.get("time"),
            payload.get("event_time"),
            payload.get("E"),
        )
    )
    available_at = _timestamp_to_utc_iso(
        _first_present(
            payload.get("fetched_utc"),
            payload.get("available_at"),
            payload.get("generated_at"),
            source_event_time,
        )
    )
    return {
        "long_short_ratio": ratio,
        "long_account_ratio": long_account,
        "short_account_ratio": short_account,
        "long_short_period": payload.get("period"),
        "long_short_source": f"{payload.get('source') or 'v2_market_long_short'}:{key}",
        "long_short_event_time": source_event_time,
        "long_short_available_at": available_at,
        "long_short_captured_at": _utc_iso(),
    }


def _attach_long_short_ratio_context(intent: dict[str, Any], evidence: dict[str, Any] | None) -> None:
    """Attach long/short telemetry without changing paper admission behavior."""
    if not isinstance(evidence, dict) or evidence.get("long_short_ratio") in (None, ""):
        intent["long_short_ratio_status"] = "MISSING_V2_LONG_SHORT_RATIO"
        return

    decision_time = _first_present(
        intent.get("paper_admission_decision_time"),
        intent.get("runtime_cost_capture_decision_time"),
        intent.get("entry_feature_decision_time"),
        intent.get("decision_time"),
        intent.get("model_decision_time"),
    )
    available_at = evidence.get("long_short_available_at")
    decision_dt = _parse_strategy_time(decision_time)
    available_dt = _parse_strategy_time(available_at)

    def _record_rejected_long_short_evidence() -> None:
        intent["long_short_ratio_decision_effect"] = (
            "REJECTED_PIT_TELEMETRY_ONLY_NO_ADMISSION_CHANGE"
        )
        for source_field, rejected_field in (
            ("long_short_period", "rejected_long_short_period"),
            ("long_short_source", "rejected_long_short_source"),
            ("long_short_event_time", "rejected_long_short_event_time"),
            ("long_short_available_at", "rejected_long_short_available_at"),
            ("long_short_captured_at", "rejected_long_short_captured_at"),
        ):
            value = evidence.get(source_field)
            if value not in (None, ""):
                intent[rejected_field] = value
        if decision_time not in (None, ""):
            intent["rejected_long_short_decision_time"] = decision_time

    if decision_dt is None:
        intent["long_short_ratio_status"] = "REJECTED_LONG_SHORT_DECISION_TIME_UNPROVEN"
        _record_rejected_long_short_evidence()
        return
    if available_dt is None:
        intent["long_short_ratio_status"] = "REJECTED_LONG_SHORT_AVAILABLE_AT_UNPROVEN"
        _record_rejected_long_short_evidence()
        return
    if available_dt > decision_dt:
        intent["long_short_ratio_status"] = "REJECTED_LONG_SHORT_AVAILABLE_AFTER_DECISION"
        _record_rejected_long_short_evidence()
        return
    for field in (
        "long_short_ratio",
        "long_account_ratio",
        "short_account_ratio",
        "long_short_period",
        "long_short_source",
        "long_short_event_time",
        "long_short_available_at",
        "long_short_captured_at",
    ):
        if evidence.get(field) not in (None, ""):
            intent[field] = evidence.get(field)
    intent["long_short_decision_time"] = decision_time
    intent["long_short_ratio_status"] = "V2_LONG_SHORT_RATIO_ATTACHED"
    intent["long_short_ratio_decision_effect"] = "TELEMETRY_ONLY_NO_ADMISSION_CHANGE"


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
    if timeframe in (None, ""):
        return {
            "features": {},
            "unavailable_reason": MISSING_THESIS_TIMEFRAME_BLOCK_REASON,
            "symbol": normalized_symbol,
        }
    normalized_timeframe = str(timeframe).strip()
    if not normalized_timeframe:
        return {
            "features": {},
            "unavailable_reason": MISSING_THESIS_TIMEFRAME_BLOCK_REASON,
            "symbol": normalized_symbol,
        }
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


def _attach_paper_execution_evidence(
    intent: dict[str, Any],
    mark_index: dict[str, Any] | None = None,
) -> None:
    """Attach paper-only execution evidence known before any outcome label."""
    fill_time = _first_present(intent.get("fill_price_utc"), intent.get("entry_price_utc"), intent.get("generated_utc"))
    fill_dt = _parse_strategy_time(fill_time)
    decision_time = None
    decision_dt = None
    for candidate_time in (
        intent.get("entry_feature_decision_time"),
        intent.get("decision_time"),
        intent.get("entry_spread_decision_time"),
        intent.get("generated_at"),
        intent.get("generated_utc"),
    ):
        parsed = _parse_strategy_time(candidate_time)
        if parsed is None:
            continue
        if fill_dt is not None and parsed > fill_dt:
            continue
        decision_time = candidate_time
        decision_dt = parsed
        break
    if (
        intent.get("latency_ms") in (None, "")
        and fill_dt is not None
        and decision_dt is not None
        and fill_dt >= decision_dt
    ):
        latency_ms = round((fill_dt - decision_dt).total_seconds() * 1000.0, 3)
        intent["latency_ms"] = latency_ms
        intent["decision_latency_ms"] = latency_ms
        intent["paper_fill_latency_ms"] = latency_ms
        intent["fill_latency_ms"] = latency_ms
        intent["execution_latency_ms"] = latency_ms
        intent["simulated_latency_ms"] = latency_ms
        intent["latency_source"] = "PAPER_DECISION_TO_FILL_RUNTIME_TIMESTAMPS"

    spread = _coerce_float(intent.get("actual_observed_spread_entry_bps"))
    fill_price = _coerce_float(_first_present(intent.get("fill_price"), intent.get("entry_price")))
    if (
        intent.get("maker_probability") in (None, "")
        and intent.get("taker_probability") in (None, "")
        and intent.get("entry_price_provenance_present") is True
        and spread is not None
        and fill_price is not None
        and fill_price > 0.0
    ):
        intent["maker_probability"] = 0.0
        intent["taker_probability"] = 1.0
        intent["maker_taker_probability"] = 1.0
        intent["maker_taker_probabilities"] = {"maker": 0.0, "taker": 1.0}
        intent["maker_taker_probability_source"] = PAPER_IMMEDIATE_FILL_TAKER_SOURCE

    quantity = _coerce_float(_first_present(intent.get("quantity"), intent.get("target_quantity")))
    notional = _coerce_float(
        _first_present(
            intent.get("notional"),
            intent.get("notional_usdt"),
            intent.get("gross_notional_usd"),
            intent.get("target_notional_usdt"),
        )
    )
    if notional is None and quantity is not None and fill_price is not None:
        notional = quantity * fill_price
    partial_rows = intent.get("partial_fills") if isinstance(intent.get("partial_fills"), list) else []
    existing_partial = partial_rows[0] if partial_rows and isinstance(partial_rows[0], dict) else {}
    existing_partial_quantity = _coerce_float(existing_partial.get("quantity"))
    existing_partial_price = _coerce_float(existing_partial.get("price"))
    existing_partial_notional = _coerce_float(existing_partial.get("notional_usd"))
    quantity_changed = (
        quantity is not None
        and (
            existing_partial_quantity is None
            or abs(existing_partial_quantity - quantity) > max(1e-12, abs(quantity) * 1e-9)
        )
    )
    price_changed = (
        fill_price is not None
        and (
            existing_partial_price is None
            or abs(existing_partial_price - fill_price) > max(1e-12, abs(fill_price) * 1e-9)
        )
    )
    notional_changed = (
        notional is not None
        and (
            existing_partial_notional is None
            or abs(existing_partial_notional - notional) > max(1e-8, abs(notional) * 1e-9)
        )
    )
    if (
        quantity is not None
        and quantity > 0.0
        and fill_price is not None
        and fill_price > 0.0
        and (
            intent.get("partial_fill_count") in (None, "")
            or not partial_rows
            or quantity_changed
            or price_changed
            or notional_changed
        )
    ):
        partial = {
            "fill_sequence": 1,
            "quantity": quantity,
            "price": fill_price,
            "notional_usd": round(float(notional), 8) if notional is not None else None,
            "fill_time": fill_time,
            "source": "PAPER_SINGLE_FILL_LEDGER_RECORD",
            "paper_only": True,
            "places_real_order": False,
        }
        intent["partial_fill_count"] = 1
        intent["fill_count"] = 1
        intent["partial_fills"] = [partial]
        intent["all_partial_fills"] = [partial]
        intent["partial_fill_plan"] = {
            "model": "PAPER_SINGLE_IMMEDIATE_FILL",
            "expected_fill_count": 1,
            "source": "PAPER_LEDGER_ACCEPTED_FILL",
        }

    mark_index = mark_index if isinstance(mark_index, dict) else {}
    mark = _coerce_float(mark_index.get("mark_price"))
    index = _coerce_float(mark_index.get("index_price"))
    if mark is not None and index is not None and mark > 0.0 and index > 0.0:
        intent["mark_price"] = mark
        intent["index_price"] = index
        intent["mark_index_divergence"] = mark_index.get("mark_index_divergence")
        intent["mark_index_divergence_bps"] = mark_index.get("mark_index_divergence_bps")
        intent["mark_index_source"] = mark_index.get("mark_index_source")
        intent["mark_index_available_at"] = mark_index.get("mark_index_available_at")


def _depth_vwap_for_quantity(
    levels: list[dict[str, float]],
    quantity: float,
) -> tuple[float | None, float, bool]:
    if quantity <= 0.0:
        return None, 0.0, False
    remaining = float(quantity)
    filled = 0.0
    notional = 0.0
    for level in levels:
        price = _coerce_float(level.get("price"))
        available = _coerce_float(level.get("quantity"))
        if price is None or available is None or price <= 0.0 or available <= 0.0:
            continue
        take = min(remaining, available)
        filled += take
        notional += take * price
        remaining -= take
        if remaining <= 1e-12:
            break
    if filled <= 0.0:
        return None, 0.0, False
    return notional / filled, filled, remaining <= 1e-12


def _attach_depth_price_impact_evidence(
    intent: dict[str, Any],
    market_microstructure: dict[str, Any] | None,
) -> None:
    if intent.get("depth_price_impact_bps") not in (None, ""):
        return
    market_microstructure = market_microstructure if isinstance(market_microstructure, dict) else {}
    side = str(_first_present(intent.get("side"), intent.get("selected_action")) or "").lower()
    if side not in {"long", "short"}:
        return
    quantity = _coerce_float(_first_present(intent.get("quantity"), intent.get("target_quantity")))
    fill_price = _coerce_float(_first_present(intent.get("fill_price"), intent.get("entry_price")))
    notional = _coerce_float(
        _first_present(
            intent.get("notional"),
            intent.get("notional_usdt"),
            intent.get("gross_notional_usd"),
            intent.get("target_notional_usdt"),
        )
    )
    if quantity is None and notional is not None and fill_price is not None and fill_price > 0.0:
        quantity = abs(notional / fill_price)
    if notional is None and quantity is not None and fill_price is not None and fill_price > 0.0:
        notional = abs(quantity * fill_price)
    if quantity is None or quantity <= 0.0:
        return

    levels_key = "ask_levels_top5" if side == "long" else "bid_levels_top5"
    levels = market_microstructure.get(levels_key)
    if not isinstance(levels, list):
        levels = []
    levels = [
        {"price": float(level["price"]), "quantity": float(level["quantity"])}
        for level in levels
        if isinstance(level, dict)
        and _coerce_float(level.get("price")) is not None
        and _coerce_float(level.get("quantity")) is not None
        and float(level["price"]) > 0.0
        and float(level["quantity"]) > 0.0
    ]
    if not levels:
        return
    vwap, filled_quantity, fill_complete = _depth_vwap_for_quantity(levels, quantity)
    if vwap is None or filled_quantity <= 0.0:
        return
    touch = _coerce_float(
        market_microstructure.get("best_ask" if side == "long" else "best_bid")
    )
    if touch is None:
        touch = levels[0]["price"]
    mid = _coerce_float(market_microstructure.get("mid_price"))
    if mid is None or mid <= 0.0:
        best_bid = _coerce_float(market_microstructure.get("best_bid"))
        best_ask = _coerce_float(market_microstructure.get("best_ask"))
        if best_bid is not None and best_ask is not None and best_bid > 0.0 and best_ask > 0.0:
            mid = (best_bid + best_ask) / 2.0
    if mid is None or mid <= 0.0 or touch <= 0.0:
        return

    if side == "long":
        impact_bps = max(0.0, ((vwap - touch) / mid) * 10_000.0)
    else:
        impact_bps = max(0.0, ((touch - vwap) / mid) * 10_000.0)
    side_depth_field = "ask_depth_usd" if side == "long" else "bid_depth_usd"
    side_depth = _coerce_float(market_microstructure.get(side_depth_field))
    if side_depth is not None and side_depth > 0.0:
        intent.setdefault("entry_orderbook_depth_usd", round(float(side_depth), 8))
        intent.setdefault("entry_orderbook_depth_side", "ask" if side == "long" else "bid")
    if notional is not None and side_depth is not None and side_depth > 0.0:
        intent["depth_utilization_pct"] = round(float(notional) / float(side_depth), 10)
    intent["depth_price_impact_bps"] = round(float(impact_bps), 8)
    intent["depth_price_impact_source"] = (
        f"{market_microstructure.get('source') or ENTRY_SPREAD_SOURCE_V2_ORDERBOOK}:"
        f"{levels_key}:top5_vwap_vs_touch"
    )
    intent["depth_price_impact_model"] = "ORDERBOOK_TOP5_VWAP_VS_TOUCH"
    intent["depth_price_impact_side"] = "ask" if side == "long" else "bid"
    intent["depth_price_impact_quantity"] = round(float(quantity), 12)
    intent["depth_price_impact_filled_quantity"] = round(float(filled_quantity), 12)
    intent["depth_price_impact_fill_complete"] = bool(fill_complete)
    intent["depth_price_impact_vwap"] = round(float(vwap), 12)
    intent["depth_price_impact_touch_price"] = round(float(touch), 12)


def _runtime_cost_capture_no_order_reason(intent: dict[str, Any]) -> str | None:
    size = _coerce_float(
        _first_present(
            intent.get("order_size"),
            intent.get("order_size_usd"),
            intent.get("gross_notional_usd"),
            intent.get("target_notional_usdt"),
            intent.get("notional_usdt"),
            intent.get("notional"),
        )
    )
    if size is not None and size > 0.0:
        return None

    tier = str(
        _first_present(
            intent.get("paper_opportunity_tier"),
            intent.get("paper_execution_tier"),
            intent.get("opportunity_tier"),
            intent.get("candidate_tier"),
        )
        or ""
    ).strip().upper()
    allocator_decision = str(intent.get("allocator_decision") or "").strip().upper()
    paper_fill_allowed = intent.get("paper_fill_allowed")

    if tier == PAPER_TIER_NO_TRADE:
        return "NO_TRADE_ZERO_SIZE_PAPER_INTENT"
    if tier in NON_EXECUTABLE_PAPER_TIERS:
        return f"{tier}_ZERO_SIZE_NON_EXECUTABLE_PAPER_INTENT"
    if allocator_decision.startswith("BLOCK_"):
        return "ADAPTIVE_ALLOCATOR_ZERO_SIZE_BLOCKED_PAPER_INTENT"
    if paper_fill_allowed is False:
        return "PAPER_FILL_NOT_ALLOWED_ZERO_SIZE_INTENT"
    return None


def _attach_runtime_cost_capture_contract(
    intent: dict[str, Any],
    market_microstructure: dict[str, Any] | None = None,
    *,
    signal: dict[str, Any] | None = None,
    prediction: dict[str, Any] | None = None,
) -> None:
    """Attach the pre-outcome challenger paper cost-capture contract."""
    market_microstructure = market_microstructure if isinstance(market_microstructure, dict) else {}
    signal = signal if isinstance(signal, dict) else {}
    prediction = prediction if isinstance(prediction, dict) else {}

    candidate_id = _first_present(
        intent.get("candidate_id"),
        prediction.get("candidate_id"),
        signal.get("candidate_id"),
        CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
    )
    policy_fingerprint = _first_present(
        intent.get("policy_fingerprint"),
        intent.get("selector_policy_fingerprint"),
        prediction.get("policy_fingerprint"),
        prediction.get("selector_policy_fingerprint"),
        signal.get("policy_fingerprint"),
        CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
    )
    model_source = _first_present(
        intent.get("model_source"),
        prediction.get("model_source"),
        signal.get("model_source"),
        CHALLENGER_V2_MODEL_SOURCE,
    )
    policy_owner = str(
        _first_present(
            intent.get("paper_policy_owner"),
            prediction.get("paper_policy_owner"),
            signal.get("paper_policy_owner"),
            PAPER_POLICY_OWNER_CHALLENGER_V2,
        )
    )
    policy_id = _first_present(
        intent.get("policy_id"),
        prediction.get("policy_id"),
        signal.get("policy_id"),
        candidate_id,
    )
    if policy_owner == PAPER_POLICY_OWNER_CHALLENGER_V2:
        deprecated_candidate_ids = {
            CHALLENGER_V2_FROZEN_CANDIDATE_ID,
            CHALLENGER_V2_PREVIOUS_ACTIVE_CUDA_CANDIDATE_ID,
        }
        if candidate_id in deprecated_candidate_ids:
            candidate_id = CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
        if policy_id in deprecated_candidate_ids:
            policy_id = CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
        if policy_fingerprint in (
            None,
            "",
            OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
            CHALLENGER_V2_PREVIOUS_ACTIVE_CUDA_POLICY_FINGERPRINT,
        ):
            policy_fingerprint = CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT
    intent["candidate_id"] = candidate_id
    intent["policy_id"] = policy_id
    intent["paper_policy_owner"] = policy_owner
    intent["policy_fingerprint"] = policy_fingerprint
    intent.setdefault("selector_policy_fingerprint", OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT)
    intent.setdefault("frozen_selector_fingerprint", OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT)
    intent["model_source"] = model_source
    model_decision_time = _first_present(
        intent.get("model_decision_time"),
        intent.get("entry_feature_decision_time"),
        intent.get("decision_time"),
        prediction.get("decision_time"),
        signal.get("decision_time"),
    )
    if model_decision_time is not None:
        intent["model_decision_time"] = model_decision_time
    intent["snapshot_id"] = _first_present(
        intent.get("snapshot_id"),
        intent.get("entry_feature_snapshot_id"),
        intent.get("feature_snapshot_id"),
        intent.get("mtf_snapshot_id"),
        prediction.get("feature_snapshot_id"),
    )
    intent["predicted_direction"] = _first_present(
        intent.get("predicted_direction"),
        intent.get("side"),
        intent.get("selected_action"),
        prediction.get("selected_action"),
        signal.get("selected_action"),
    )
    predicted_move = _first_present(
        intent.get("predicted_move"),
        intent.get("predicted_move_bps"),
        intent.get("expected_move_bps"),
        prediction.get("expected_move_bps"),
        signal.get("expected_move_bps"),
    )
    intent["predicted_move"] = predicted_move
    intent["predicted_move_bps"] = predicted_move
    intent["score"] = _first_present(
        intent.get("score"),
        intent.get("selected_action_probability"),
        intent.get("confidence_calibrated"),
        prediction.get("score"),
        prediction.get("selected_action_probability"),
        prediction.get("confidence_calibrated"),
        signal.get("score"),
        signal.get("confidence_calibrated"),
    )
    intent["challenger_canary_id"] = CHALLENGER_B_GRADE_PAPER_CANARY
    intent["challenger_canary_profile"] = CHALLENGER_B_GRADE_PAPER_CANARY
    intent["paper_canary_profile"] = CHALLENGER_B_GRADE_PAPER_CANARY
    intent["paper_canary_adaptive_sizing_required"] = True
    intent["paper_canary_fixed_notional_allowed"] = False
    intent["paper_canary_live_routing_allowed"] = False
    intent["routes_to_live"] = False
    intent["paper_only"] = True
    intent["places_real_order"] = False
    intent["live_order"] = False
    intent["test_order"] = False
    intent["counts_as_a_grade_evidence"] = False
    intent["a_grade_promotion_allowed"] = False

    order_size = _coerce_float(
        _first_present(
            intent.get("notional_usdt"),
            intent.get("notional"),
            intent.get("gross_notional_usd"),
            intent.get("target_notional_usdt"),
            intent.get("order_size"),
            intent.get("order_size_usd"),
        )
    )
    if order_size is not None:
        order_size = abs(float(order_size))
        intent["order_size"] = order_size
        intent["order_size_usd"] = order_size
        intent.setdefault("gross_notional_usd", order_size)

    observed_bid = _coerce_float(
        _first_present(
            intent.get("observed_bid"),
            intent.get("best_bid"),
            market_microstructure.get("best_bid"),
        )
    )
    observed_ask = _coerce_float(
        _first_present(
            intent.get("observed_ask"),
            intent.get("best_ask"),
            market_microstructure.get("best_ask"),
        )
    )
    observed_spread = _coerce_float(
        _first_present(
            intent.get("observed_spread_bps"),
            intent.get("actual_observed_spread_entry_bps"),
            intent.get("observed_bid_ask_spread_bps"),
            market_microstructure.get("bid_ask_spread_bps"),
        )
    )
    if observed_spread is None and observed_bid and observed_ask and observed_bid > 0 and observed_ask > 0:
        mid = (observed_bid + observed_ask) / 2.0
        if mid > 0.0:
            observed_spread = abs(observed_ask - observed_bid) / mid * 10_000.0
    if observed_bid is not None:
        intent["observed_bid"] = observed_bid
        intent.setdefault("best_bid", observed_bid)
    if observed_ask is not None:
        intent["observed_ask"] = observed_ask
        intent.setdefault("best_ask", observed_ask)
    if observed_spread is not None:
        intent["observed_spread_bps"] = observed_spread
        intent["actual_observed_spread_entry_bps"] = observed_spread
        intent.setdefault("observed_bid_ask_spread_bps", observed_spread)

    top_bid_depth = _coerce_float(
        _first_present(
            intent.get("top_book_bid_depth_usd"),
            intent.get("bid_depth_usd"),
            market_microstructure.get("bid_depth_usd"),
        )
    )
    top_ask_depth = _coerce_float(
        _first_present(
            intent.get("top_book_ask_depth_usd"),
            intent.get("ask_depth_usd"),
            market_microstructure.get("ask_depth_usd"),
        )
    )
    market_depth = _coerce_float(
        _first_present(
            intent.get("market_depth_usd"),
            intent.get("orderbook_depth_usd"),
            market_microstructure.get("market_depth_usd"),
            market_microstructure.get("orderbook_depth_usd"),
            min(top_bid_depth, top_ask_depth)
            if top_bid_depth is not None and top_ask_depth is not None
            else None,
        )
    )
    if top_bid_depth is not None:
        intent["top_book_bid_depth_usd"] = top_bid_depth
        intent.setdefault("bid_depth_usd", top_bid_depth)
    if top_ask_depth is not None:
        intent["top_book_ask_depth_usd"] = top_ask_depth
        intent.setdefault("ask_depth_usd", top_ask_depth)
    if market_depth is not None:
        intent["market_depth_usd"] = market_depth
        intent.setdefault("orderbook_depth_usd", market_depth)
        intent.setdefault("top_of_book_depth_usd", market_depth)

    no_order_reason = _runtime_cost_capture_no_order_reason(intent)
    if no_order_reason is not None and order_size is None:
        order_size = 0.0
        intent["order_size"] = 0.0
        intent["order_size_usd"] = 0.0
        intent.setdefault("gross_notional_usd", 0.0)

    depth_impact = _coerce_float(
        _first_present(
            intent.get("depth_derived_price_impact_bps"),
            intent.get("depth_price_impact_bps"),
        )
    )
    if depth_impact is None and no_order_reason is not None:
        depth_impact = 0.0
        intent["depth_price_impact_source"] = "NO_ORDER_ZERO_SIZE_NO_MARKET_IMPACT"
        intent["depth_price_impact_model"] = "EXPLICIT_ZERO_SIZE_NO_ORDER"
    if depth_impact is not None:
        intent["depth_derived_price_impact_bps"] = depth_impact
        intent["depth_price_impact_bps"] = depth_impact

    maker_probability = _coerce_float(intent.get("maker_probability"))
    taker_probability = _coerce_float(intent.get("taker_probability"))
    maker_taker_probability = _coerce_float(intent.get("maker_taker_probability"))
    maker_taker_assumption = _first_present(intent.get("maker_taker_assumption"))
    if maker_taker_assumption is None and maker_probability is not None and taker_probability is not None:
        maker_taker_assumption = "maker" if maker_probability > taker_probability else "taker"
    if maker_taker_probability is None and maker_taker_assumption == "maker":
        maker_taker_probability = maker_probability
    if maker_taker_probability is None and maker_taker_assumption == "taker":
        maker_taker_probability = taker_probability
    if maker_taker_assumption is not None:
        intent["maker_taker_assumption"] = str(maker_taker_assumption)
    if maker_taker_probability is not None:
        intent["maker_taker_probability"] = maker_taker_probability
    if maker_probability is not None or taker_probability is not None:
        intent["maker_taker_probability_detail"] = {
            "maker": maker_probability,
            "taker": taker_probability,
        }

    fee_bps = _coerce_float(intent.get("fee_bps"))
    fee_source = _first_present(intent.get("fee_bps_source"), intent.get("fee_schedule_source"))
    if fee_bps is not None:
        intent["fee_schedule"] = {
            "fee_bps": fee_bps,
            "source": fee_source,
            "maker_taker_assumption": intent.get("maker_taker_assumption"),
            "readonly_schedule": bool(intent.get("fee_bps_readonly_schedule")),
            "configured_schedule": bool(intent.get("fee_bps_configured_schedule")),
        }

    expected_funding_bps = _coerce_float(intent.get("expected_funding_bps"))
    funding_rate = _coerce_float(intent.get("funding_rate"))
    if funding_rate is None and expected_funding_bps is not None:
        funding_rate = expected_funding_bps / 10_000.0
        intent["funding_rate"] = funding_rate
    if expected_funding_bps is None and funding_rate is not None:
        expected_funding_bps = funding_rate * 10_000.0
        intent["expected_funding_bps"] = expected_funding_bps
    if expected_funding_bps is not None:
        intent["holding_period_funding_bps"] = expected_funding_bps
        intent["holding_period_funding_source"] = _first_present(
            intent.get("expected_funding_bps_source"),
            intent.get("funding_rate_source"),
            "expected_funding_bps",
        )

    latency_ms = _coerce_float(intent.get("latency_ms"))
    latency_reserve = _coerce_float(
        _first_present(intent.get("latency_reserve_bps"), intent.get("execution_uncertainty_bps"))
    )
    if latency_reserve is None and latency_ms is not None:
        latency_reserve = 0.0
        intent["latency_reserve_source"] = "PAPER_IMMEDIATE_FILL_OBSERVED_LATENCY_ZERO_LIVE_RESERVE"
    elif latency_reserve is not None:
        intent["latency_reserve_source"] = _first_present(
            intent.get("latency_reserve_source"),
            "ADAPTIVE_ALLOCATOR_EXECUTION_UNCERTAINTY_BPS",
        )
    if latency_reserve is not None:
        intent["latency_reserve_bps"] = latency_reserve

    partial_fill_count = _coerce_float(intent.get("partial_fill_count"))
    if partial_fill_count is not None and partial_fill_count > 0:
        expected_fill_count = int(partial_fill_count)
    else:
        expected_fill_count = 1
    if intent.get("partial_fill_estimate") in (None, ""):
        intent["partial_fill_estimate"] = {
            "model": "PAPER_SINGLE_IMMEDIATE_FILL",
            "expected_fill_count": expected_fill_count,
            "expected_fill_probability": 1.0,
            "partial_fill_adjustment_bps": 0.0,
            "source": "PAPER_RUNTIME_FILL_LEDGER_ESTIMATE",
        }
    intent.setdefault("partial_fill_probability", 1.0)
    intent.setdefault("execution_probability", 1.0)
    intent.setdefault("partial_fill_adjustment_bps", 0.0)

    cost_source = _first_present(
        intent.get("cost_source"),
        intent.get("entry_spread_source"),
        market_microstructure.get("source"),
    )
    source_timestamp = _first_present(
        intent.get("cost_source_timestamp"),
        intent.get("source_timestamp"),
        intent.get("entry_spread_available_at"),
        market_microstructure.get("entry_spread_available_at"),
    )
    decision_timestamp = _first_present(
        intent.get("entry_feature_decision_time"),
        intent.get("decision_time"),
        intent.get("generated_at"),
        intent.get("generated_utc"),
    )
    if cost_source is not None:
        intent["cost_source"] = cost_source
    if source_timestamp is not None:
        intent["cost_source_timestamp"] = source_timestamp
        intent["source_timestamp"] = source_timestamp

    temporal_reject_reasons: list[str] = []
    source_dt = _parse_strategy_time(source_timestamp)
    runtime_decision_timestamp = _first_present(
        intent.get("paper_admission_decision_time"),
        intent.get("runtime_cost_capture_decision_time"),
        decision_timestamp,
    )
    decision_dt = _parse_strategy_time(runtime_decision_timestamp)
    if source_timestamp is not None and source_dt is None:
        temporal_reject_reasons.append("UNPARSEABLE_COST_SOURCE_TIMESTAMP")
    if source_dt is not None and decision_dt is not None:
        freshness_ms = round((decision_dt - source_dt).total_seconds() * 1000.0, 3)
        intent["cost_evidence_freshness_ms"] = freshness_ms
        if freshness_ms < 0:
            temporal_reject_reasons.append("COST_SOURCE_TIMESTAMP_AFTER_DECISION_TIME")
    if decision_timestamp is not None:
        intent["model_decision_time"] = decision_timestamp
    if runtime_decision_timestamp is not None:
        intent["runtime_cost_capture_decision_time"] = runtime_decision_timestamp

    expected_slippage_bps = _coerce_float(intent.get("expected_slippage_bps"))
    estimated_cost_components = [
        fee_bps,
        expected_slippage_bps,
        expected_funding_bps,
        depth_impact,
        latency_reserve,
        _coerce_float(intent.get("partial_fill_adjustment_bps")),
    ]
    if all(component is not None for component in estimated_cost_components):
        estimated_production_cost_bps = round(
            float(sum(component for component in estimated_cost_components if component is not None)),
            8,
        )
        intent["estimated_production_cost_bps"] = estimated_production_cost_bps
        intent["estimated_production_cost"] = estimated_production_cost_bps

    required_fields = (
        "observed_bid",
        "observed_ask",
        "observed_spread_bps",
        "order_size",
        "top_book_bid_depth_usd",
        "top_book_ask_depth_usd",
        "market_depth_usd",
        "depth_derived_price_impact_bps",
        "maker_taker_assumption",
        "maker_taker_probability",
        "fee_schedule",
        "fee_bps",
        "funding_rate",
        "holding_period_funding_bps",
        "expected_slippage_bps",
        "latency_reserve_bps",
        "partial_fill_estimate",
        "mark_index_divergence_bps",
        "cost_source",
        "cost_source_timestamp",
        "cost_evidence_freshness_ms",
    )
    positive_fields = {
        "observed_bid",
        "observed_ask",
        "order_size",
        "top_book_bid_depth_usd",
        "top_book_ask_depth_usd",
        "market_depth_usd",
    }
    missing: list[str] = []
    for field in required_fields:
        value = intent.get(field)
        if field == "fee_schedule":
            if not isinstance(value, dict) or _coerce_float(value.get("fee_bps")) is None or not value.get("source"):
                missing.append(field)
            continue
        if field == "partial_fill_estimate":
            if not isinstance(value, dict):
                missing.append(field)
            continue
        numeric = _coerce_float(value)
        if field in positive_fields:
            if field == "order_size" and no_order_reason is not None and numeric == 0.0:
                continue
            if numeric is None or numeric <= 0.0:
                missing.append(field)
        elif field in {
            "observed_spread_bps",
            "depth_derived_price_impact_bps",
            "maker_taker_probability",
            "fee_bps",
            "funding_rate",
            "holding_period_funding_bps",
            "expected_slippage_bps",
            "latency_reserve_bps",
            "mark_index_divergence_bps",
            "cost_evidence_freshness_ms",
        }:
            if numeric is None:
                missing.append(field)
        elif value in (None, ""):
            missing.append(field)

    explained_missing_fields: list[str] = []
    if no_order_reason is not None:
        explained_missing_fields = list(missing)
    unexplained_missing_fields = [
        field for field in missing if field not in set(explained_missing_fields)
    ]

    component_fallback = any(
        intent.get(field) is True
        for field in (
            "bid_ask_spread_bps_fallback",
            "expected_slippage_bps_fallback",
            "fee_bps_fallback",
            "expected_funding_bps_fallback",
        )
    )
    fallback = bool(missing or temporal_reject_reasons or component_fallback)
    intent["runtime_cost_capture_required_fields"] = list(required_fields)
    intent["runtime_cost_capture_missing_fields"] = sorted(set(missing))
    intent["runtime_cost_capture_explained_missing_fields"] = sorted(set(explained_missing_fields))
    intent["runtime_cost_capture_unexplained_missing_fields"] = sorted(set(unexplained_missing_fields))
    intent["runtime_cost_capture_order_cost_applicable"] = no_order_reason is None
    intent["runtime_cost_capture_no_order_reason"] = no_order_reason
    intent["runtime_cost_capture_temporal_reject_reasons"] = sorted(set(temporal_reject_reasons))
    intent["runtime_cost_capture_source"] = "V2_PAPER_RUNTIME_DECISION_TIME_COST_CAPTURE"
    intent["runtime_cost_capture_status"] = (
        "PRODUCTION_GRADE_COST_CAPTURE"
        if not fallback
        else "FALLBACK_OR_INCOMPLETE_COST_CAPTURE"
    )
    intent["fallback_cost_flag"] = fallback
    intent["fallback"] = fallback
    intent["production_grade_cost_flag"] = not fallback
    intent["production_grade_cost_evidence"] = not fallback
    intent["counts_as_production_grade_training_evidence"] = bool(not fallback and no_order_reason is None)
    intent["cost_evidence_source_fields"] = {
        "spread": intent.get("entry_spread_source"),
        "depth": intent.get("orderbook_depth_source"),
        "depth_impact": intent.get("depth_price_impact_source"),
        "fee": intent.get("fee_bps_source"),
        "funding": intent.get("expected_funding_bps_source"),
        "latency": intent.get("latency_reserve_source"),
        "partial_fill": (
            intent.get("partial_fill_estimate", {}).get("source")
            if isinstance(intent.get("partial_fill_estimate"), dict)
            else None
        ),
        "mark_index": intent.get("mark_index_source"),
    }

    allocation = intent.get("adaptive_allocation")
    if isinstance(allocation, dict):
        for field in RUNTIME_COST_CAPTURE_CONTRACT_FIELDS:
            if intent.get(field) is not None:
                allocation[field] = intent.get(field)


def _active_challenger_runtime_owner_rejection_reasons(intent: dict[str, Any]) -> list[str]:
    expected_fields = (
        ("paper_policy_owner", PAPER_POLICY_OWNER_CHALLENGER_V2),
        ("candidate_id", CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID),
        ("policy_id", CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID),
        ("policy_fingerprint", CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT),
        ("model_source", CHALLENGER_V2_MODEL_SOURCE),
    )
    reasons: list[str] = []
    for field, expected in expected_fields:
        value = intent.get(field)
        if value in (None, ""):
            reasons.append(f"{field}_missing")
        elif str(value) != str(expected):
            reasons.append(f"{field}_mismatch:{value}")
    if intent.get("routes_to_live") is not False:
        reasons.append("routes_to_live_not_false")
    if intent.get("places_real_order") is not False:
        reasons.append("places_real_order_not_false")
    return reasons


def _paper_policy_owner_open_rejection_reasons(intent: dict[str, Any]) -> list[str]:
    owner = str(intent.get("paper_policy_owner") or "")
    if owner == PAPER_POLICY_OWNER_OLD_POLICY:
        intent["paper_policy_owner_open_allowed"] = False
        intent["paper_policy_owner_open_block_reason"] = "OLD_POLICY_NEW_ECONOMIC_PAPER_OPENS_DISABLED"
        intent["paper_runtime_owner_rejection_reasons"] = ["paper_policy_owner_old_policy"]
        return ["OLD_POLICY_NEW_ECONOMIC_PAPER_OPENS_DISABLED"]
    if owner == PAPER_POLICY_OWNER_SHADOW_ONLY:
        intent["paper_policy_owner_open_allowed"] = False
        intent["paper_policy_owner_open_block_reason"] = "SHADOW_ONLY_POLICY_OWNER_NOT_ECONOMIC_FILL"
        intent["paper_runtime_owner_rejection_reasons"] = ["paper_policy_owner_shadow_only"]
        return ["SHADOW_ONLY_POLICY_OWNER_NOT_ECONOMIC_FILL"]
    owner_reasons = _active_challenger_runtime_owner_rejection_reasons(intent)
    intent["paper_runtime_owner_rejection_reasons"] = owner_reasons
    if owner_reasons:
        intent["paper_policy_owner_open_allowed"] = False
        intent["paper_policy_owner_open_block_reason"] = PAPER_RUNTIME_OWNER_BLOCK_REASON
        return [PAPER_RUNTIME_OWNER_BLOCK_REASON, *owner_reasons]
    if owner == PAPER_POLICY_OWNER_CHALLENGER_V2 and intent.get("production_grade_cost_flag") is not True:
        missing = [
            f"missing:{field}"
            for field in (intent.get("runtime_cost_capture_missing_fields") or [])
        ]
        temporal = [
            f"temporal:{reason}"
            for reason in (intent.get("runtime_cost_capture_temporal_reject_reasons") or [])
        ]
        intent["paper_policy_owner_open_allowed"] = False
        intent["paper_policy_owner_open_block_reason"] = "CHALLENGER_COST_CAPTURE_NOT_PRODUCTION_GRADE"
        return ["CHALLENGER_COST_CAPTURE_NOT_PRODUCTION_GRADE", *missing, *temporal]
    intent["paper_policy_owner_open_allowed"] = True
    intent["paper_policy_owner_open_block_reason"] = None
    return []


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
    *RUNTIME_COST_CAPTURE_CONTRACT_FIELDS,
    *PAPER_OWNER_ATTRIBUTION_METADATA_FIELDS,
    "adaptive_capital_policy_version",
    "policy_activated_at",
    "paper_opportunity_tier",
    "paper_opportunity_tier_reason",
    "pre_guardian_paper_opportunity_tier",
    "pre_guardian_paper_opportunity_tier_reason",
    "pre_guardian_paper_fill_allowed_source",
    "continuous_edge_guardian_forced_shadow_only",
    "counts_as_a_grade_evidence",
    "a_grade_promotion_allowed",
    "live_ready_implication",
    "paper_only_label_collection_priority",
    "paper_only_label_collection_priority_reason",
    "paper_only_label_collection_priority_rank",
    "paper_only_label_collection_priority_bucket_key",
    "paper_only_label_collection_priority_bucket",
    "paper_only_label_collection_priority_sample_count_deficit_to_minimum",
    "paper_only_label_collection_priority_closed_economic_outcome_count",
    "paper_only_label_collection_priority_source_generated_utc",
    *PAPER_STANDALONE_1M_ELIGIBILITY_FIELDS,
    *LONG_SHORT_RATIO_CONTEXT_FIELDS,
    *PAPER_SOURCE_TIER_GUARDIAN_CONTEXT_FIELDS,
    "pre_non_executable_paper_tier",
    "pre_non_executable_paper_tier_reason",
    "non_executable_paper_tier_block_reason",
    "paper_fill_allowed_source",
    "strict_paper_fill_allowed_upstream",
    "b_grade_exploration_budget_cap_applied",
    "risk_budget_fraction_of_normal_adaptive",
    "normal_adaptive_risk_budget_usd",
    "normal_adaptive_gross_notional_usd",
    "normal_adaptive_allocated_margin_usd",
    "normal_adaptive_expected_net_pnl_usd",
    "b_grade_exploration_static_confidence_floor",
    "b_grade_exploration_adaptive_confidence_floor",
    "b_grade_exploration_floor_mode",
    "b_grade_exploration_confidence_floor_pass",
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
    "pre_entry_stress_tests",
    "rare_event_stress_suite",
    "rare_event_stress_status",
    "rare_event_stress_missing_inputs",
    "rare_event_required_liquidation_buffer_bps",
    "modeled_999_adverse_move_bps",
    "execution_uncertainty_bps",
    "correlation_stress_bps",
    "maintenance_margin_uncertainty_bps",
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
    "selector_policy_fingerprint",
    "frozen_selector_fingerprint",
    "candidate_selected_before_outcome",
    "candidate_selected_after_outcome",
    "post_outcome_candidate_selection",
    "future_labels_used_as_features",
    "maker_probability",
    "taker_probability",
    "maker_taker_probability",
    "maker_taker_probabilities",
    "maker_taker_probability_source",
    "latency_ms",
    "latency_source",
    "paper_fill_latency_ms",
    "fill_latency_ms",
    "execution_latency_ms",
    "simulated_latency_ms",
    "partial_fill_count",
    "partial_fills",
    "fill_count",
    "all_partial_fills",
    "partial_fill_plan",
    "mark_index_divergence_bps",
    "mark_index_divergence",
    "mark_index_source",
    "mark_index_available_at",
    "mark_price",
    "index_price",
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
CANDIDATE_ALLOCATION_PUBLICATION_INTENT_FIELDS = tuple(
    dict.fromkeys(
        PERSISTENT_ACCEPTED_FILL_METADATA_FIELDS
        + (
            "intent_id",
            "source_intent_id",
            "symbol",
            "timeframe",
            "side",
            "action",
            "selected_action",
            "decision",
            "prediction_id",
            "signal_id",
            "risk_decision_id",
            "orchestrator_decision_id",
            "decision_id",
            "feature_snapshot_id",
            "entry_feature_snapshot_id",
            "mtf_snapshot_id",
            "model_version",
            "checkpoint_id",
            "source_hashes",
            "feature_cutoff",
            "decision_time",
            "available_at",
            "generated_at",
            "generated_utc",
            "entry_feature_available_at",
            "entry_feature_generated_at",
            "entry_feature_cutoff",
            "entry_feature_decision_time",
            "entry_feature_candle_closed_confirmed",
            "entry_price_provenance_present",
            "entry_price_blocker",
            "entry_price",
            "entry_price_source",
            "entry_price_utc",
            "fill_price",
            "fill_price_source",
            "fill_price_utc",
            "quantity",
            "notional",
            "notional_usdt",
            "paper_fill_allowed",
            "paper_tier_local_fill_allowed",
            "paper_tier_local_fill_source",
            "paper_fill_block_reason",
            "paper_fill_gate_block_reasons",
            "local_block_reasons",
            "lifecycle_or_no_trade_strategy_reasons",
            "no_trade_strategy_reasons",
            "paper_runtime_market_evidence_rejection_reasons",
            "paper_signal_temporal_rejection_reasons",
            "paper_sizing_complete",
            "paper_sizing_source",
            "paper_allocation_block_reason",
            "market_cost_evidence_status",
            "market_cost_evidence_missing_fields",
            "market_cost_evidence_source_fields",
            "market_cost_evidence_pit_reject_reasons",
            "market_cost_evidence_source_lineage",
            "observed_bid_ask_spread_bps",
            "actual_observed_spread_entry_bps",
            "bid_ask_spread_bps",
            "bid_ask_spread_bps_fallback",
            "bid_ask_spread_bps_unavailable_reason",
            "entry_spread_source",
            "entry_spread_available_at",
            "entry_spread_decision_time",
            "expected_slippage_bps",
            "expected_slippage_source",
            "expected_slippage_bps_fallback",
            "expected_slippage_modeled",
            "expected_slippage_unavailable_reason",
            "fee_bps",
            "fee_bps_source",
            "fee_bps_fallback",
            "fee_bps_readonly_schedule",
            "fee_bps_configured_schedule",
            "fee_bps_unavailable_reason",
            "expected_funding_bps",
            "expected_funding_bps_source",
            "expected_funding_bps_fallback",
            "expected_funding_bps_unavailable_reason",
            "orderbook_depth_usd",
            "entry_orderbook_depth_usd",
            "entry_orderbook_depth_side",
            "orderbook_depth_source",
            "depth_utilization_pct",
            "depth_price_impact_bps",
            "depth_price_impact_source",
            "depth_price_impact_model",
            "depth_price_impact_fill_complete",
            "squeeze_evidence_score",
            "squeeze_evidence_source",
            "squeeze_evidence_unavailable_reason",
            "candidate_selected_before_outcome",
            "candidate_selected_after_outcome",
            "post_outcome_candidate_selection",
            "future_labels_used_as_features",
            "paper_only",
            "places_real_order",
            "live_order",
            "test_order",
            "leverage_mutation",
            "margin_mode_mutation",
        )
    )
)

COMPACT_ACCEPTED_FILL_FIELDS = tuple(
    dict.fromkeys(
        (
            "fill_id",
            "ledger_row_id",
            "intent_id",
            "source_intent_id",
            "symbol",
            "timeframe",
            "side",
            "action",
            "selected_action",
            "decision",
            "paper_only",
            "places_real_order",
            "paper_fill_allowed",
            "paper_fill_allowed_source",
            "strict_paper_fill_allowed_upstream",
            "paper_tier_local_fill_allowed",
            "paper_tier_local_fill_source",
            "signal_id",
            "source_signal_id",
            "entry_signal_id",
            "prediction_id",
            "source_prediction_id",
            "entry_prediction_id",
            "risk_decision_id",
            "orchestrator_decision_id",
            "decision_id",
            "feature_snapshot_id",
            "entry_feature_snapshot_id",
            "mtf_snapshot_id",
            "feature_cutoff",
            "decision_time",
            "available_at",
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
            "prediction_hash",
            "source_lineage_hash",
            "generated_utc",
            "accepted_at",
            "opened_at",
            "original_fill_utc",
            "latest_price",
            "latest_price_source",
            "latest_price_utc",
            "entry_price_provenance_present",
            "entry_price_provenance_observed",
            "entry_price_blocker",
            "entry_spread_source",
            "entry_spread_available_at",
            "entry_spread_decision_time",
            "actual_observed_spread_entry_bps",
            "observed_bid_ask_spread_bps",
            "bid_ask_spread_bps",
            "expected_slippage_bps",
            "expected_slippage_source",
            "fee_bps",
            "fee_bps_source",
            "fee_bps_readonly_schedule",
            "fee_bps_configured_schedule",
            "bid_depth_usd",
            "ask_depth_usd",
            "orderbook_depth_usd",
            "entry_orderbook_depth_usd",
            "entry_orderbook_depth_side",
            "top_of_book_depth_usd",
            "market_depth_usd",
            "orderbook_depth_source",
            "orderbook_imbalance",
            "depth_price_impact_bps",
            "depth_price_impact_source",
            "depth_price_impact_model",
            "depth_price_impact_side",
            "depth_price_impact_quantity",
            "depth_price_impact_filled_quantity",
            "depth_price_impact_fill_complete",
            "depth_price_impact_vwap",
            "depth_price_impact_touch_price",
            "depth_utilization_pct",
            "market_state_id",
            "market_state_integrity_score",
            "valid_for_paper",
            "market_state_reject_reasons",
            "strategy_id",
            "strategy_family",
            "strategy_subtype",
            "strategy_selected_mode",
            "strategy_router_selected_mode",
            "strategy_size_adjustment_mode",
            "strategy_regime_labels",
            "entry_reason",
            "hedge_state",
            "hedge_reason",
            "drawdown_at_entry",
            "drawdown_bps",
            "market_regime_at_entry",
            "liquidity_zone_context",
            "liquidity_context",
            "liquidation_distance_context",
            "liquidation_context",
            "microstructure_context",
            "oi_funding_context",
            "public_intel_context",
            "major_move_signal_id",
            "major_move_evidence_score",
            "squeeze_evidence_score",
            "squeeze_evidence_source",
            "squeeze_evidence_components",
            "liquidation_pressure",
            "liquidation_strength",
            "liquidation_cascade_risk",
            "last_liq_bps_24h",
            "oi_change_pct",
            "funding_rate",
            "ob_imbalance",
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
            "selector_policy_fingerprint",
            "frozen_selector_fingerprint",
            "candidate_selected_before_outcome",
            "candidate_selected_after_outcome",
            "post_outcome_candidate_selection",
            "future_labels_used_as_features",
            "paper_sizing_complete",
            "paper_sizing_source",
            "paper_accounting_blocker",
            "paper_allocation_block_reason",
            "paper_runtime_market_evidence_rejection_reasons",
            "paper_signal_temporal_rejection_reasons",
            "lifecycle_or_no_trade_strategy_reasons",
            "no_trade_strategy_reasons",
            "entry_gate_block_reasons",
            "paper_fill_gate_status",
            "paper_fill_gate_block_reasons",
            "paper_fill_block_reason",
            "strategy_router_block_reason",
            "paper_strategy_mode_collapse_guard",
            "paper_directional_collapse_guard",
            "local_block_reasons",
            "fill_price_immutable",
            "paper_fill_persistence_status",
            "lineage_backfilled_from_prediction_id",
            *IMMUTABLE_ACCEPTED_FILL_FIELDS,
            *PERSISTENT_ACCEPTED_FILL_METADATA_FIELDS,
            *AUDIT_QUALITY_FEEDBACK_FIELDS,
        )
    )
)
COMPACT_ACCEPTED_FILL_ALLOCATION_FIELDS = tuple(
    dict.fromkeys(
        (
            "allocation_id",
            "allocator_decision",
            "allocator_reason",
            "adaptive_capital_policy_version",
            "policy_activated_at",
            "paper_only",
            "places_real_order",
            "live_order",
            "test_order",
            "leverage_mutation",
            "margin_mode_mutation",
            "selector_policy_fingerprint",
            "frozen_selector_fingerprint",
            "candidate_selected_before_outcome",
            "candidate_selected_after_outcome",
            "post_outcome_candidate_selection",
            "future_labels_used_as_features",
            "symbol",
            "timeframe",
            "side",
            "selected_action",
            "prediction_id",
            "signal_id",
            "decision_id",
            "risk_decision_id",
            "orchestrator_decision_id",
            "feature_snapshot_id",
            "entry_feature_snapshot_id",
            "feature_cutoff",
            "decision_time",
            "available_at",
            "entry_feature_available_at",
            "entry_feature_cutoff",
            "entry_feature_decision_time",
            "model_version",
            "checkpoint_id",
            "source_hashes",
            "confidence_raw",
            "confidence_calibrated",
            "selected_action_probability",
            "expected_move_bps",
            "expected_move_after_cost_bps",
            "policy_value",
            "value_baseline",
            "action_probabilities",
            "risk_budget_usd",
            "gross_notional_usd",
            "target_notional_usdt",
            "normal_adaptive_gross_notional_usd",
            "allocated_margin_usd",
            "normal_adaptive_allocated_margin_usd",
            "recommended_leverage",
            "effective_leverage",
            "recommended_margin_mode",
            "margin_mode",
            "stop_distance_bps",
            "liquidation_price_estimate",
            "liquidation_buffer_bps",
            "pre_entry_stress_tests",
            "rare_event_stress_suite",
            "rare_event_stress_status",
            "rare_event_stress_missing_inputs",
            "rare_event_required_liquidation_buffer_bps",
            "modeled_999_adverse_move_bps",
            "execution_uncertainty_bps",
            "correlation_stress_bps",
            "maintenance_margin_uncertainty_bps",
            "expected_fees_usd",
            "expected_slippage_usd",
            "expected_funding_usd",
            "expected_funding_bps",
            "funding_rate",
            "funding_interval_seconds",
            "expected_net_pnl_usd",
            "normal_adaptive_expected_net_pnl_usd",
            "expected_shortfall_usd",
            "hedge_budget_usd",
            "hedge_enabled",
            "hedge_parent_id",
            "hedge_child_id",
            "hedge_intent",
            "hedge_ratio",
            "hedge_expected_shortfall_reduction_usd",
            "expected_shortfall_before",
            "expected_shortfall_after",
            "maximum_duration",
            "unwind_plan",
            "hedge_cost_usd",
            "take_profit_structure",
            "take_profit_price",
            "take_profit_reference",
            "capital_allocation_reason",
            "paper_opportunity_tier",
            *PAPER_SOURCE_TIER_GUARDIAN_CONTEXT_FIELDS,
            "risk_budget_fraction_of_normal_adaptive",
            "observed_spread_bps",
            "entry_spread_bps",
            "actual_observed_spread_entry_bps",
            "depth_impact_bps",
            "expected_slippage_bps",
            "depth_price_impact_bps",
            "depth_price_impact_source",
            "depth_price_impact_model",
            "depth_price_impact_side",
            "depth_price_impact_fill_complete",
            "depth_utilization_pct",
            "maker_probability",
            "taker_probability",
            "maker_taker_probability",
            "maker_taker_probabilities",
            "maker_taker_probability_source",
            "latency_ms",
            "latency_source",
            "partial_fill_count",
            "partial_fills",
            "fill_count",
            "all_partial_fills",
            "partial_fill_plan",
            "mark_price",
            "index_price",
            "mark_index_source",
            "mark_index_available_at",
            "mark_index_divergence",
            "mark_index_divergence_bps",
        )
    )
)


COMPACT_ACCEPTED_FILL_OMITTED_FIELDS = frozenset(
    {
        "entry_feature_snapshot",
        "action_probabilities",
        "all_partial_fills",
        "cost_evidence_source_fields",
        "fee_schedule",
        "liquidation_context",
        "liquidation_distance_context",
        "liquidity_zone_context",
        "microstructure_context",
        "oi_funding_context",
        "paper_directional_collapse_guard",
        "paper_strategy_mode_collapse_guard",
        "partial_fill_estimate",
        "partial_fill_plan",
        "partial_fills",
        "pre_entry_stress_tests",
        "production_grade_cost_evidence",
        "public_intel_context",
        "rare_event_stress_missing_inputs",
        "rare_event_stress_suite",
        "source_hashes",
        "squeeze_evidence_components",
    }
)


def _copy_present_fields(source: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        field: source[field]
        for field in fields
        if field not in COMPACT_ACCEPTED_FILL_OMITTED_FIELDS and source.get(field) not in (None, "")
    }


def _compact_adaptive_allocation_for_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compact = _copy_present_fields(value, COMPACT_ACCEPTED_FILL_ALLOCATION_FIELDS)
    model_inputs = value.get("model_inputs") if isinstance(value.get("model_inputs"), dict) else {}
    compact_model_inputs = _copy_present_fields(
        model_inputs,
        tuple(
            dict.fromkeys(
                (
                    *PERSISTENT_ACCEPTED_FILL_MODEL_INPUT_FIELDS,
                    "selected_leverage",
                    "leverage_target",
                    "raw_leverage_target",
                    "leverage_selection_reason",
                    "selected_margin_mode",
                    "margin_mode_selection_reason",
                    "selected_hedge_budget_pct_of_risk",
                    "hedge_budget_selection_reason",
                    "paper_opportunity_tier",
                    "expected_slippage_bps",
                    "observed_spread_bps",
                    "depth_price_impact_bps",
                )
            )
        ),
    )
    if compact_model_inputs:
        compact["model_inputs"] = compact_model_inputs
    return compact


def _compact_accepted_fill_for_state(row: dict[str, Any]) -> dict[str, Any]:
    compact = _copy_present_fields(row, COMPACT_ACCEPTED_FILL_FIELDS)
    allocation = _compact_adaptive_allocation_for_state(row.get("adaptive_allocation"))
    if allocation:
        compact["adaptive_allocation"] = allocation
    compact["accepted_fill_state_compacted"] = True
    compact["entry_feature_snapshot_omitted_from_state"] = bool(row.get("entry_feature_snapshot"))
    return compact


def _compact_rows_for_state(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_compact_accepted_fill_for_state(row) for row in rows if isinstance(row, dict)]


def _sample_rows(rows: list[dict[str, Any]], limit: int = PAPER_REDIS_LEDGER_ROW_SAMPLE_LIMIT) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    if len(rows) <= limit:
        return rows
    return rows[-limit:]


HEAVY_REDIS_STATUS_ROW_KEYS = frozenset(
    {
        "buckets",
        "candidate_allocations",
        "closed_outcomes",
        "held_by_paper_fill_gate",
        "persistent_shadow_observations",
        "sample_a_grade_rows",
        "sample_allocations",
        "sample_b_grade_exploration_fills",
        "sample_blocked_fills",
        "sample_canary_candidates",
        "sample_canary_intents",
        "sample_canary_pending_rows",
        "sample_near_a_grade_rows",
        "sample_paper_only_label_collection_priority_fills",
        "sample_rejected_forward_canary_outcomes",
        "sample_valid_forward_canary_outcomes",
        "shadow_observations",
    }
)


def _compact_status_for_redis(value: Any) -> Any:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        omitted: list[str] = []
        for key, item in value.items():
            if key in HEAVY_REDIS_STATUS_ROW_KEYS and isinstance(item, list):
                compact[f"{key}_count"] = len(item)
                omitted.append(key)
                continue
            compact[key] = _compact_status_for_redis(item)
        if omitted:
            compact["sample_rows_omitted_from_redis_status"] = True
            compact["omitted_redis_status_row_fields"] = sorted(omitted)
        return compact
    if isinstance(value, list):
        return [_compact_status_for_redis(item) for item in value]
    return value


def _paper_runtime_cost_capture_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    intent_rows = [row for row in rows if isinstance(row, dict)]
    order_applicable_rows = [
        row
        for row in intent_rows
        if row.get("runtime_cost_capture_order_cost_applicable") is not False
    ]
    production_grade_cost_rows = sum(
        1
        for row in intent_rows
        if row.get("production_grade_cost_flag") is True
        or row.get("production_grade_cost_evidence") is True
    )
    production_grade_cost_order_applicable_rows = sum(
        1
        for row in order_applicable_rows
        if row.get("production_grade_cost_flag") is True
        or row.get("production_grade_cost_evidence") is True
    )
    no_order_explained_rows = sum(
        1
        for row in intent_rows
        if row.get("runtime_cost_capture_order_cost_applicable") is False
    )
    unexplained_missing_cost_rows = sum(
        1
        for row in order_applicable_rows
        if len(row.get("runtime_cost_capture_unexplained_missing_fields") or []) > 0
    )
    no_order_missing_cost_rows = sum(
        1
        for row in intent_rows
        if row.get("runtime_cost_capture_order_cost_applicable") is False
        and (
            len(row.get("runtime_cost_capture_missing_fields") or []) > 0
            or len(row.get("runtime_cost_capture_unexplained_missing_fields") or []) > 0
        )
    )
    paper_fill_allowed_rows = sum(1 for row in intent_rows if row.get("paper_fill_allowed") is True)
    routes_to_live_rows = sum(1 for row in intent_rows if row.get("routes_to_live") is True)
    places_real_order_rows = sum(1 for row in intent_rows if row.get("places_real_order") is True)
    total_row_cost_coverage = (
        production_grade_cost_rows / len(intent_rows)
        if intent_rows
        else 0.0
    )
    if order_applicable_rows:
        cost_coverage = production_grade_cost_order_applicable_rows / len(order_applicable_rows)
        cost_coverage_basis = "order_applicable_rows"
    else:
        cost_coverage = total_row_cost_coverage
        cost_coverage_basis = "all_intent_rows_no_order_applicable"
    return {
        "schema_version": "v2_paper_runtime_cost_capture_summary_v1",
        "source": "v2_trade_management_paper_loop:intents",
        "paper_intent_rows": len(intent_rows),
        "order_cost_applicable_rows": len(order_applicable_rows),
        "production_grade_cost_rows": production_grade_cost_rows,
        "production_grade_cost_order_applicable_rows": production_grade_cost_order_applicable_rows,
        "production_grade_cost_coverage": cost_coverage,
        "production_grade_cost_coverage_basis": cost_coverage_basis,
        "production_grade_cost_total_row_coverage": total_row_cost_coverage,
        "no_order_explained_rows": no_order_explained_rows,
        "unexplained_missing_cost_rows": unexplained_missing_cost_rows,
        "no_order_missing_cost_rows": no_order_missing_cost_rows,
        "paper_fill_allowed_rows": paper_fill_allowed_rows,
        "routes_to_live_rows": routes_to_live_rows,
        "places_real_order_rows": places_real_order_rows,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


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


def _index_accepted_fill_rows(rows: list[Any]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        identity = _accepted_fill_identity(row)
        if identity:
            out[identity] = row
    return out


def _file_size_bytes(path: Path) -> int | None:
    try:
        return int(path.stat().st_size)
    except OSError:
        return None


def _state_file_skip_status(path: Path, *, max_bytes: int) -> dict[str, Any] | None:
    size = _file_size_bytes(path)
    if size is None or size <= max_bytes:
        return None
    return {
        "path": str(path),
        "size_bytes": size,
        "max_bytes": int(max_bytes),
        "skipped_reason": "STATE_FILE_EXCEEDS_BOUNDED_RUNTIME_READ_CAP",
    }


def _read_json_file_payload(path: Path, *, max_bytes: int | None = None) -> dict[str, Any]:
    if max_bytes is not None and _state_file_skip_status(path, max_bytes=max_bytes):
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _redis_string_length(r, key: str) -> int | None:
    strlen = getattr(r, "strlen", None)
    if callable(strlen):
        try:
            return int(strlen(key))
        except Exception:
            return None
    return None


def _read_json_redis_key_if_small(
    r,
    key: str,
    *,
    max_bytes: int | None = PAPER_REDIS_HISTORY_READ_MAX_BYTES,
) -> dict[str, Any]:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return {}
    size = _redis_string_length(r, key)
    if max_bytes is not None and size is not None and size > max_bytes:
        return {}
    try:
        raw = r.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    if max_bytes is not None and size is None:
        try:
            raw_size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
        except Exception:
            raw_size = None
        if raw_size is not None and raw_size > max_bytes:
            return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json_list_redis_key_if_small(
    r,
    key: str,
    *,
    max_bytes: int | None = PAPER_REDIS_HISTORY_READ_MAX_BYTES,
) -> list[dict[str, Any]]:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return []
    size = _redis_string_length(r, key)
    if max_bytes is not None and size is not None and size > max_bytes:
        return []
    try:
        raw = r.get(key)
    except Exception:
        return []
    if not raw:
        return []
    if max_bytes is not None and size is None:
        try:
            raw_size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
        except Exception:
            raw_size = None
        if raw_size is not None and raw_size > max_bytes:
            return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [dict(row) for row in payload if isinstance(row, dict)]


def _accepted_fill_from_open_position(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    source_fill_ids = row.get("source_fill_ids") if isinstance(row.get("source_fill_ids"), list) else []
    fill_id = _first_present(
        row.get("fill_id"),
        row.get("ledger_row_id"),
        row.get("position_id"),
        source_fill_ids[0] if source_fill_ids else None,
        f"{row.get('symbol')}:{row.get('timeframe')}:{row.get('side')}",
    )
    if fill_id:
        item.setdefault("fill_id", str(fill_id))
        item.setdefault("ledger_row_id", str(fill_id))
    quantity = _coerce_float(
        _first_present(row.get("quantity"), row.get("net_quantity"), row.get("order_size"))
    )
    if quantity is not None and quantity > 0:
        item.setdefault("quantity", abs(quantity))
        item.setdefault("order_size", abs(quantity))
    price = _coerce_float(
        _first_present(row.get("fill_price"), row.get("entry_price"), row.get("avg_entry_price"))
    )
    if price is not None and price > 0:
        item.setdefault("fill_price", price)
        item.setdefault("entry_price", price)
        item.setdefault("mark_price_at_fill", price)
    notional = _coerce_float(
        _first_present(row.get("notional"), row.get("notional_usdt"), row.get("gross_notional_usd"))
    )
    if notional is None and quantity is not None and price is not None:
        notional = abs(quantity * price)
    if notional is not None and notional > 0:
        item.setdefault("notional", abs(notional))
        item.setdefault("notional_usdt", abs(notional))
        item.setdefault("gross_notional_usd", abs(notional))
    item.setdefault("paper_fill_persistence_status", "OPEN_POSITION_COMPACT_STATE_REPLAY")
    item.setdefault("fill_price_immutable", True)
    item.setdefault("paper_only", True)
    item.setdefault("places_real_order", False)
    return item


def _accepted_fill_rows_from_open_positions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _accepted_fill_from_open_position(row)
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    ]


def _read_accepted_fill_state_file(path: Path | None = None) -> dict[str, dict]:
    path = path or PAPER_ACCEPTED_FILLS_STATE_PATH
    payload = _read_json_file_payload(path, max_bytes=PAPER_STATE_FULL_FILE_READ_MAX_BYTES)
    rows = (
        payload.get("accepted_fills")
        or payload.get("accepted_open_fills")
        or payload.get("accepted")
        or payload.get("accepted_intents")
        or []
    )
    if not isinstance(rows, list):
        return {}
    return _index_accepted_fill_rows(rows)


def _read_lifecycle_state_file(path: Path | None = None) -> dict[str, Any]:
    path = path or PAPER_LIFECYCLE_STATE_PATH
    return _read_json_file_payload(path, max_bytes=PAPER_STATE_FULL_FILE_READ_MAX_BYTES)


def _read_existing_accepted_fills(r) -> dict[str, dict]:
    if r is not None:
        open_positions = _read_json_list_redis_key_if_small(
            r,
            f"{V2_REDIS_PREFIX}paper:positions",
        )
        position_rows = _accepted_fill_rows_from_open_positions(open_positions)
        if position_rows:
            return _index_accepted_fill_rows(position_rows)
        ledger_payload = _read_json_redis_key_if_small(
            r,
            f"{V2_REDIS_PREFIX}paper:ledger",
        )
        if isinstance(ledger_payload.get("open_positions"), list):
            position_rows = _accepted_fill_rows_from_open_positions(ledger_payload["open_positions"])
            if position_rows:
                return _index_accepted_fill_rows(position_rows)
    file_rows = _read_accepted_fill_state_file()
    if file_rows:
        return file_rows
    if r is None:
        return {}
    payload = _read_json_redis_key_if_small(r, f"{V2_REDIS_PREFIX}paper:ledger")
    rows = payload.get("accepted") or payload.get("accepted_intents") or []
    return _index_accepted_fill_rows(rows)



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


def _normalize_paper_owner_attribution(row: dict[str, Any]) -> dict[str, Any]:
    """Make paper owner attribution explicit without crediting old rows."""
    normalized = dict(row)
    owner = _first_present(normalized.get("paper_policy_owner"))
    candidate_id = _first_present(normalized.get("candidate_id"))
    policy_id = _first_present(normalized.get("policy_id"))
    policy_fingerprint = _first_present(
        normalized.get("policy_fingerprint"),
        normalized.get("selector_policy_fingerprint"),
        normalized.get("frozen_selector_fingerprint"),
    )
    model_source = _first_present(
        normalized.get("model_source"),
        normalized.get("model_version"),
        normalized.get("model_id"),
    )

    missing = [
        field
        for field, value in (
            ("candidate_id", candidate_id),
            ("policy_id", policy_id),
            ("paper_policy_owner", owner),
            ("policy_fingerprint", policy_fingerprint),
            ("model_source", model_source),
        )
        if value in (None, "")
    ]
    if owner == PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER:
        missing.append("pre_cutover_owner_attribution")
    elif owner not in (None, "", PAPER_POLICY_OWNER_CHALLENGER_V2):
        missing.append("non_challenger_paper_policy_owner")

    if owner == PAPER_POLICY_OWNER_CHALLENGER_V2:
        candidate_id = _first_present(candidate_id, CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID)
        policy_id = _first_present(policy_id, candidate_id)
        policy_fingerprint = _first_present(
            policy_fingerprint,
            CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        )
        model_source = _first_present(model_source, CHALLENGER_V2_MODEL_SOURCE)
        if policy_fingerprint == OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT:
            policy_fingerprint = CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT
        if (
            policy_fingerprint == CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT
            and model_source == CHALLENGER_V2_MODEL_SOURCE
        ):
            if candidate_id == CHALLENGER_V2_FROZEN_CANDIDATE_ID:
                candidate_id = CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
            if policy_id == CHALLENGER_V2_FROZEN_CANDIDATE_ID:
                policy_id = CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID

    if missing:
        owner = _first_present(owner, PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER)
        candidate_id = _first_present(candidate_id, UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID)
        policy_id = _first_present(policy_id, candidate_id)
        policy_fingerprint = _first_present(
            policy_fingerprint,
            UNATTRIBUTED_PRE_CUTOVER_POLICY_FINGERPRINT,
        )
        model_source = _first_present(model_source, UNATTRIBUTED_PRE_CUTOVER_MODEL_SOURCE)
    if owner == PAPER_POLICY_OWNER_UNATTRIBUTED_PRE_CUTOVER:
        candidate_id = UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
        policy_id = UNATTRIBUTED_PRE_CUTOVER_CANDIDATE_ID
        policy_fingerprint = UNATTRIBUTED_PRE_CUTOVER_POLICY_FINGERPRINT
        model_source = UNATTRIBUTED_PRE_CUTOVER_MODEL_SOURCE

    normalized["candidate_id"] = candidate_id
    normalized["policy_id"] = policy_id
    normalized["paper_policy_owner"] = owner
    normalized["policy_fingerprint"] = policy_fingerprint
    normalized["selector_policy_fingerprint"] = _first_present(
        normalized.get("selector_policy_fingerprint"),
        OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
    )
    normalized["frozen_selector_fingerprint"] = _first_present(
        normalized.get("frozen_selector_fingerprint"),
        OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
    )
    normalized["model_source"] = model_source
    normalized["current_allowed_paper_owner"] = PAPER_POLICY_OWNER_CHALLENGER_V2
    missing = sorted(set(missing))
    complete = (
        not missing
        and owner == PAPER_POLICY_OWNER_CHALLENGER_V2
        and candidate_id == CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
        and policy_id == CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
        and policy_fingerprint == CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT
        and model_source == CHALLENGER_V2_MODEL_SOURCE
    )
    normalized["paper_owner_attribution_complete"] = complete
    normalized["paper_owner_attribution_missing_fields"] = missing
    normalized["paper_owner_attribution_status"] = (
        "COMPLETE_CHALLENGER_V2_OWNER_ATTRIBUTION"
        if complete
        else "INCOMPLETE_OR_PRE_CUTOVER_OWNER_ATTRIBUTION"
    )
    normalized["paper_owner_attribution_blocks_challenger_credit"] = not complete
    if not complete:
        normalized["counts_as_a_grade_evidence"] = False
        normalized["a_grade_promotion_allowed"] = False
        normalized["counts_as_challenger_evidence"] = False
        normalized["challenger_credit_allowed"] = False
    return normalized


def _normalize_paper_owner_attribution_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _normalize_paper_owner_attribution(row)
        for row in rows
        if isinstance(row, dict)
    ]


def _paper_owner_attribution_status(
    accepted_rows: list[dict[str, Any]],
    *,
    current_accepted_rows: list[dict[str, Any]] | None = None,
    current_runtime_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current_accepted_rows = current_accepted_rows if current_accepted_rows is not None else accepted_rows
    current_runtime_rows = current_runtime_rows if current_runtime_rows is not None else current_accepted_rows
    persistent_rows = [_normalize_paper_owner_attribution(row) for row in accepted_rows if isinstance(row, dict)]
    current_rows = [_normalize_paper_owner_attribution(row) for row in current_accepted_rows if isinstance(row, dict)]
    runtime_rows = [_normalize_paper_owner_attribution(row) for row in current_runtime_rows if isinstance(row, dict)]
    incomplete_persistent = [
        row for row in persistent_rows if row.get("paper_owner_attribution_complete") is not True
    ]
    incomplete_current = [
        row for row in current_rows if row.get("paper_owner_attribution_complete") is not True
    ]
    incomplete_runtime = [
        row for row in runtime_rows if row.get("paper_owner_attribution_complete") is not True
    ]
    return {
        "schema_version": "paper_owner_attribution_status_v1",
        "status": (
            "PASS_CURRENT_ACCEPTED_OWNER_ATTRIBUTION"
            if current_rows and not incomplete_current
            else "NO_GO_CURRENT_ACCEPTED_OWNER_ATTRIBUTION_INCOMPLETE"
            if current_rows
            else "PASS_CURRENT_RUNTIME_OWNER_ATTRIBUTION_NO_ACCEPTED_FILLS"
            if runtime_rows and not incomplete_runtime
            else "NO_GO_CURRENT_RUNTIME_OWNER_ATTRIBUTION_INCOMPLETE"
            if runtime_rows
            else "NO_CURRENT_RUNTIME_ROWS_TO_VERIFY"
        ),
        "accepted_fill_status": (
            "NO_CURRENT_ACCEPTED_ROWS_TO_VERIFY"
            if not current_rows
            else "PASS_CURRENT_ACCEPTED_OWNER_ATTRIBUTION"
            if not incomplete_current
            else "NO_GO_CURRENT_ACCEPTED_OWNER_ATTRIBUTION_INCOMPLETE"
        ),
        "current_allowed_paper_owner": PAPER_POLICY_OWNER_CHALLENGER_V2,
        "current_candidate_id": CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "current_policy_fingerprint": CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "current_model_source": CHALLENGER_V2_MODEL_SOURCE,
        "current_accepted_count": len(current_rows),
        "current_complete_count": len(current_rows) - len(incomplete_current),
        "current_incomplete_count": len(incomplete_current),
        "current_runtime_row_count": len(runtime_rows),
        "current_runtime_complete_count": len(runtime_rows) - len(incomplete_runtime),
        "current_runtime_incomplete_count": len(incomplete_runtime),
        "persistent_accepted_count": len(persistent_rows),
        "persistent_complete_count": len(persistent_rows) - len(incomplete_persistent),
        "persistent_incomplete_or_pre_cutover_count": len(incomplete_persistent),
        "current_owner_counts": _count_values(current_rows, "paper_policy_owner"),
        "current_runtime_owner_counts": _count_values(runtime_rows, "paper_policy_owner"),
        "persistent_owner_counts": _count_values(persistent_rows, "paper_policy_owner"),
        "current_candidate_counts": _count_values(current_rows, "candidate_id"),
        "current_runtime_candidate_counts": _count_values(runtime_rows, "candidate_id"),
        "persistent_candidate_counts": _count_values(persistent_rows, "candidate_id"),
        "current_missing_field_counts": _count_list_values(
            current_rows,
            "paper_owner_attribution_missing_fields",
        ),
        "current_runtime_missing_field_counts": _count_list_values(
            runtime_rows,
            "paper_owner_attribution_missing_fields",
        ),
        "persistent_missing_field_counts": _count_list_values(
            persistent_rows,
            "paper_owner_attribution_missing_fields",
        ),
        "pre_cutover_rows_block_challenger_credit": all(
            row.get("paper_owner_attribution_blocks_challenger_credit") is True
            and row.get("counts_as_a_grade_evidence") is False
            for row in incomplete_persistent
        ),
        "current_runtime_owner_contract_passed": bool(runtime_rows) and not incomplete_runtime,
        "sample_incomplete_or_pre_cutover_rows": _sample_rows(
            [
                {
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "decision": row.get("decision"),
                    "candidate_id": row.get("candidate_id"),
                    "paper_policy_owner": row.get("paper_policy_owner"),
                    "policy_fingerprint": row.get("policy_fingerprint"),
                    "model_source": row.get("model_source"),
                    "paper_owner_attribution_missing_fields": row.get(
                        "paper_owner_attribution_missing_fields"
                    ),
                    "counts_as_a_grade_evidence": row.get("counts_as_a_grade_evidence"),
                }
                for row in incomplete_persistent
            ],
            10,
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _paper_thesis_timeframe(*sources: dict[str, Any]) -> str | None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        value = _first_present(
            source.get("thesis_timeframe"),
            source.get("prediction_timeframe"),
            source.get("expected_move_timeframe"),
            source.get("timeframe"),
        )
        if value not in (None, ""):
            return str(value).strip() or None
    return None


def _paper_execution_timeframe(*sources: dict[str, Any]) -> str:
    for source in sources:
        if not isinstance(source, dict):
            continue
        value = _first_present(
            source.get("execution_timeframe"),
            source.get("feature_timeframe"),
            source.get("timeframe"),
        )
        if value not in (None, ""):
            parsed = str(value).strip()
            if parsed:
                return parsed
    return PAPER_EXECUTION_TIMING_TIMEFRAME


def _paper_bool_flag(*sources: dict[str, Any], names: tuple[str, ...]) -> bool:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for name in names:
            if source.get(name) is True:
                return True
    return False


def _paper_1m_strategy_id(
    *,
    intent: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    strategy_router: dict[str, Any] | None = None,
) -> str:
    router = strategy_router if isinstance(strategy_router, dict) else {}
    return str(
        _first_present(
            intent.get("strategy_id"),
            intent.get("strategy_mode"),
            intent.get("strategy_selected_mode"),
            signal.get("strategy_id"),
            signal.get("strategy_mode"),
            prediction.get("strategy_id"),
            prediction.get("strategy_mode"),
            router.get("strategy_id"),
            router.get("selected_mode"),
            "paper_runtime_momentum",
        )
    )


def _paper_standalone_1m_strategy_eligible(
    *,
    strategy_id: str,
    intent: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    feature_snapshot: dict[str, Any],
    risk: dict[str, Any] | None = None,
) -> bool:
    features = feature_snapshot.get("features") if isinstance(feature_snapshot.get("features"), dict) else {}
    explicit_flag = _paper_bool_flag(
        risk or {},
        intent,
        signal,
        prediction,
        features,
        names=(
            "standalone_1m_strategy_eligible",
            "eligible_1m_strategy",
            "dedicated_1m_strategy_bucket",
            "one_minute_strategy_eligible",
            "one_minute_scalp_strategy_eligible",
        ),
    )
    strategy_text = str(strategy_id or "").lower()
    named_bucket = (
        ("1m" in strategy_text or "one_minute" in strategy_text)
        and any(token in strategy_text for token in ("scalp", "standalone", "micro"))
    )
    return explicit_flag or named_bucket


def _paper_standalone_1m_eligibility_gate(
    *,
    symbol: str,
    thesis_timeframe: str | None,
    side: str,
    intent: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    feature_snapshot: dict[str, Any],
    risk: dict[str, Any] | None = None,
    strategy_router: dict[str, Any] | None = None,
    paper_only_label_collection_priority_index: dict[tuple[str, ...], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_thesis_timeframe = str(thesis_timeframe or UNKNOWN_THESIS_TIMEFRAME)
    execution_timeframe = _paper_execution_timeframe(feature_snapshot, prediction, signal, intent)
    strategy_id = _paper_1m_strategy_id(
        intent=intent,
        signal=signal,
        prediction=prediction,
        strategy_router=strategy_router,
    )
    standalone_1m_thesis = normalized_thesis_timeframe == "1m"
    higher_timeframe_timing_role_allowed = execution_timeframe == "1m" and normalized_thesis_timeframe != "1m"
    dedicated_strategy_bucket = _paper_standalone_1m_strategy_eligible(
        strategy_id=strategy_id,
        intent=intent,
        signal=signal,
        prediction=prediction,
        feature_snapshot=feature_snapshot,
        risk=risk,
    )
    priority_payload = _paper_only_label_collection_priority_payload(
        intent,
        paper_only_label_collection_priority_index or {},
    )
    priority_bucket_allows_paper_collection = (
        standalone_1m_thesis and priority_payload is not None
    )
    blockers: list[str] = []
    if (
        standalone_1m_thesis
        and not dedicated_strategy_bucket
        and not priority_bucket_allows_paper_collection
    ):
        blockers.append(PAPER_STANDALONE_1M_BLOCK_REASON)
    allowed = not blockers
    return {
        "schema_version": "paper_standalone_1m_eligibility_gate_v1",
        "status": "PASS_PAPER_STANDALONE_1M_ELIGIBILITY" if allowed else "BLOCKED_PAPER_STANDALONE_1M_ELIGIBILITY",
        "allowed": allowed,
        "symbol": symbol,
        "side": str(side).upper(),
        "thesis_timeframe": normalized_thesis_timeframe,
        "execution_timeframe": execution_timeframe,
        "strategy_id": strategy_id,
        "standalone_1m_thesis": standalone_1m_thesis,
        "dedicated_strategy_bucket": dedicated_strategy_bucket,
        "paper_only_label_collection_priority_allowed": (
            priority_bucket_allows_paper_collection
        ),
        "paper_only_label_collection_priority_bucket_key": (
            None
            if priority_payload is None
            else priority_payload.get("paper_only_label_collection_priority_bucket_key")
        ),
        "paper_only_label_collection_priority_reason": (
            None
            if priority_payload is None
            else priority_payload.get("paper_only_label_collection_priority_reason")
        ),
        "standalone_1m_adaptive_policy": (
            "PAPER_ONLY_PRIORITY_BUCKET_LABEL_COLLECTION"
            if priority_bucket_allows_paper_collection
            else "EXPLICIT_OR_NAMED_DEDICATED_1M_BUCKET"
            if dedicated_strategy_bucket
            else "FAIL_CLOSED_REQUIRES_DEDICATED_OR_PRIORITY_BUCKET_EVIDENCE"
        ),
        "counts_as_a_grade_evidence": False,
        "a_grade_promotion_allowed": False,
        "live_ready_implication": False,
        "standalone_execution_allowed": allowed if standalone_1m_thesis else True,
        "higher_timeframe_timing_role_allowed": higher_timeframe_timing_role_allowed,
        "blockers": blockers,
        "runtime_wired_to_entry_gate": True,
        "paper_only": True,
        "paper_fill_allowed": allowed,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _apply_paper_standalone_1m_gate(intent: dict[str, Any], gate: dict[str, Any]) -> None:
    intent["paper_standalone_1m_eligibility"] = gate
    if gate.get("allowed") is True:
        return
    blockers = [str(reason) for reason in gate.get("blockers") or [] if reason]
    intent["paper_fill_allowed"] = False
    intent["paper_standalone_1m_eligibility_blocked"] = True
    intent["paper_standalone_1m_eligibility_blockers"] = blockers
    intent["paper_fill_block_reason"] = intent.get("paper_fill_block_reason") or PAPER_STANDALONE_1M_GATE_BLOCK_REASON
    intent["paper_fill_gate_block_reasons"] = sorted(set(
        list(intent.get("paper_fill_gate_block_reasons") or []) + blockers
    ))
    intent["local_block_reasons"] = sorted(set(
        list(intent.get("local_block_reasons") or [])
        + [f"standalone_1m_eligibility:{reason}" for reason in blockers]
    ))


def _paper_dedup_identity_part(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    text = str(value).strip()
    return text or None


def _paper_first_identity(*values: Any) -> str | None:
    for value in values:
        parsed = _paper_dedup_identity_part(value)
        if parsed is not None:
            return parsed
    return None


def _paper_reentry_source_rows(existing_ledger: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in (
        "accepted",
        "accepted_intents",
        "accepted_open_fills",
        "open_positions",
        "positions",
        "closed_trades",
        "closes",
        "outcome_labels",
    ):
        value = existing_ledger.get(key)
        if isinstance(value, list):
            rows.extend(dict(row) for row in value if isinstance(row, dict))
    return rows[-PAPER_REENTRY_DEDUP_RUNTIME_LOOKBACK_ROWS:]


def _paper_reentry_strategy_id(
    *,
    row: dict[str, Any] | None = None,
    intent: dict[str, Any] | None = None,
    signal: dict[str, Any] | None = None,
    prediction: dict[str, Any] | None = None,
    strategy_router: dict[str, Any] | None = None,
) -> str:
    row = row or {}
    intent = intent or {}
    signal = signal or {}
    prediction = prediction or {}
    strategy_router = strategy_router or {}
    return _paper_first_identity(
        row.get("strategy_id"),
        row.get("strategy_mode"),
        row.get("strategy_selected_mode"),
        row.get("strategy_family"),
        intent.get("strategy_id"),
        intent.get("strategy_mode"),
        intent.get("strategy_selected_mode"),
        signal.get("strategy_id"),
        signal.get("strategy_mode"),
        prediction.get("strategy_id"),
        prediction.get("strategy_mode"),
        strategy_router.get("strategy_id"),
        strategy_router.get("selected_mode"),
        "paper_runtime_momentum",
    ) or "paper_runtime_momentum"


def _paper_reentry_thesis_candle(*sources: dict[str, Any]) -> str | None:
    for source in sources:
        if not isinstance(source, dict):
            continue
        parsed = _paper_first_identity(
            source.get("thesis_candle_close_time"),
            source.get("entry_feature_cutoff"),
            source.get("feature_cutoff"),
            source.get("candle_close_time"),
            source.get("finalized_candle_close_time"),
        )
        if parsed is not None:
            return parsed
    return None


def _paper_reentry_row_side(row: dict[str, Any]) -> str:
    return str(_first_present(row.get("side"), row.get("paper_action"), row.get("selected_action")) or "").upper()


def _paper_reentry_identity(row: dict[str, Any]) -> dict[str, str | None]:
    symbol = str(row.get("symbol") or "").upper()
    timeframe = str(_first_present(row.get("thesis_timeframe"), row.get("timeframe")) or "").strip()
    candle = _paper_reentry_thesis_candle(row) or ""
    strategy = _paper_reentry_strategy_id(row=row)
    side = _paper_reentry_row_side(row)
    return {
        "prediction_id": _paper_first_identity(row.get("entry_prediction_id"), row.get("prediction_id"), row.get("source_prediction_id")),
        "decision_id": _paper_first_identity(row.get("decision_id"), row.get("orchestrator_decision_id"), row.get("risk_decision_id")),
        "signal_id": _paper_first_identity(row.get("entry_signal_id"), row.get("signal_id")),
        "feature_snapshot_id": _paper_first_identity(row.get("entry_feature_snapshot_id"), row.get("feature_snapshot_id")),
        "same_candle_same_thesis": "|".join([symbol, timeframe, candle, strategy, side]),
    }


def _paper_reentry_partial_close(row: dict[str, Any]) -> bool:
    reason = str(_first_present(row.get("close_reason"), row.get("exit_reason"), row.get("ledger_action")) or "").lower()
    return bool(row.get("is_partial_close") is True or row.get("is_partial_reduce") is True or "partial" in reason)


def _paper_reentry_entry_time(row: dict[str, Any]) -> datetime | None:
    return _parse_strategy_time(
        _first_present(
            row.get("entry_time"),
            row.get("opened_at"),
            row.get("entry_feature_decision_time"),
            row.get("generated_at"),
            row.get("generated_utc"),
        )
    )


def _paper_reentry_exit_time(row: dict[str, Any]) -> datetime | None:
    return _parse_strategy_time(
        _first_present(
            row.get("exit_time"),
            row.get("closed_at"),
            row.get("exit_price_utc"),
            row.get("generated_at") if row.get("paper_result") == "POSITION_CLOSED_PAPER_ONLY" else None,
            row.get("generated_utc") if row.get("paper_result") == "POSITION_CLOSED_PAPER_ONLY" else None,
        )
    )


def _paper_reentry_material_change_reasons(previous: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    previous_candle = _paper_reentry_thesis_candle(previous)
    candidate_candle = _paper_reentry_thesis_candle(candidate)
    if previous_candle and candidate_candle and previous_candle != candidate_candle:
        reasons.append("new_finalized_thesis_candle")
    previous_regime = _paper_first_identity(previous.get("market_regime_at_entry"), previous.get("market_regime"))
    candidate_regime = _paper_first_identity(candidate.get("market_regime_at_entry"), candidate.get("market_regime"))
    if previous_regime and candidate_regime and previous_regime != "UNKNOWN" and candidate_regime != "UNKNOWN" and previous_regime != candidate_regime:
        reasons.append("market_regime_change")
    if _paper_reentry_strategy_id(row=previous) != _paper_reentry_strategy_id(row=candidate):
        reasons.append("strategy_change")
    if _paper_reentry_row_side(previous) != _paper_reentry_row_side(candidate):
        reasons.append("direction_change")
    previous_edge = _coerce_float(_first_present(previous.get("expected_move_after_cost_bps"), previous.get("expected_net_edge_bps"), previous.get("expected_move_bps")))
    candidate_edge = _coerce_float(_first_present(candidate.get("expected_move_after_cost_bps"), candidate.get("expected_net_edge_bps"), candidate.get("expected_move_bps")))
    if previous_edge is not None and candidate_edge is not None and candidate_edge > previous_edge:
        reasons.append("expected_edge_improvement")
    previous_context = _paper_first_identity(previous.get("liquidation_context"), previous.get("microstructure_context"), previous.get("market_state_id"))
    candidate_context = _paper_first_identity(candidate.get("liquidation_context"), candidate.get("microstructure_context"), candidate.get("market_state_id"))
    if previous_context and candidate_context and previous_context != "UNKNOWN" and candidate_context != "UNKNOWN" and previous_context != candidate_context:
        reasons.append("liquidation_or_microstructure_state_change")
    previous_exit = _paper_reentry_exit_time(previous)
    candidate_entry = _paper_reentry_entry_time(candidate)
    cooldown_seconds = _coerce_float(candidate.get("reentry_cooldown_seconds") or candidate.get("cooldown_seconds")) or 300.0
    previous_snapshot = _paper_reentry_identity(previous).get("feature_snapshot_id")
    candidate_snapshot = _paper_reentry_identity(candidate).get("feature_snapshot_id")
    if (
        previous_exit is not None
        and candidate_entry is not None
        and (candidate_entry - previous_exit).total_seconds() >= cooldown_seconds
        and previous_snapshot
        and candidate_snapshot
        and previous_snapshot != candidate_snapshot
    ):
        reasons.append("cooldown_elapsed_with_fresh_independent_evidence")
    return reasons


def _paper_reentry_dedup_candidate_row(
    *,
    symbol: str,
    thesis_timeframe: str | None,
    side: str,
    intent: dict[str, Any],
    signal: dict[str, Any],
    prediction: dict[str, Any],
    feature_snapshot: dict[str, Any],
    risk: dict[str, Any] | None = None,
    strategy_router: dict[str, Any] | None = None,
) -> dict[str, Any]:
    risk = risk or {}
    features = feature_snapshot.get("features") if isinstance(feature_snapshot.get("features"), dict) else {}
    entry_time = _paper_first_identity(
        intent.get("generated_utc"),
        risk.get("generated_at"),
        signal.get("generated_at"),
        prediction.get("generated_at"),
        feature_snapshot.get("generated_at"),
    )
    return {
        "symbol": symbol,
        "timeframe": thesis_timeframe,
        "thesis_timeframe": thesis_timeframe,
        "side": str(side).upper(),
        "prediction_id": _paper_first_identity(prediction.get("prediction_id"), signal.get("prediction_id"), intent.get("prediction_id"), risk.get("prediction_id")),
        "decision_id": _paper_first_identity(intent.get("decision_id"), risk.get("decision_id"), risk.get("orchestrator_decision_id"), risk.get("risk_decision_id")),
        "risk_decision_id": _paper_first_identity(risk.get("risk_decision_id"), intent.get("risk_decision_id")),
        "signal_id": _paper_first_identity(signal.get("signal_id"), intent.get("signal_id"), risk.get("signal_id")),
        "feature_snapshot_id": _paper_first_identity(
            feature_snapshot.get("feature_snapshot_id"),
            intent.get("entry_feature_snapshot_id"),
            intent.get("feature_snapshot_id"),
            prediction.get("feature_snapshot_id"),
            risk.get("feature_snapshot_id"),
        ),
        "entry_feature_snapshot_id": _paper_first_identity(
            intent.get("entry_feature_snapshot_id"),
            feature_snapshot.get("feature_snapshot_id"),
            prediction.get("feature_snapshot_id"),
        ),
        "strategy_id": _paper_reentry_strategy_id(
            intent=intent,
            signal=signal,
            prediction=prediction,
            strategy_router=strategy_router,
        ),
        "thesis_candle_close_time": _paper_reentry_thesis_candle(intent, risk, signal, prediction, feature_snapshot),
        "entry_time": entry_time,
        "generated_at": entry_time,
        "expected_move_after_cost_bps": _first_present(intent.get("expected_move_after_cost_bps"), risk.get("expected_move_after_cost_bps")),
        "market_regime_at_entry": _paper_first_identity(features.get("market_regime"), risk.get("market_regime_at_entry"), signal.get("market_regime_at_entry")) or "UNKNOWN",
        "microstructure_context": _paper_first_identity(features.get("microstructure_context"), risk.get("microstructure_context"), signal.get("microstructure_context")) or "UNKNOWN",
        "liquidation_context": _paper_first_identity(features.get("liquidation_context"), risk.get("liquidation_context"), signal.get("liquidation_context")) or "UNKNOWN",
    }


def _paper_reentry_dedup_gate(previous_rows: list[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    duplicate_fields: list[str] = []
    duplicate_samples: list[dict[str, Any]] = []
    permitted_reasons: set[str] = set()
    candidate_identity = _paper_reentry_identity(candidate)
    exact_blocker_by_field = {
        "prediction_id": "same_prediction_id",
        "decision_id": "same_decision_id",
        "signal_id": "same_signal_id",
        "feature_snapshot_id": "same_feature_snapshot_id",
    }
    for index, previous in enumerate(previous_rows):
        previous_identity = _paper_reentry_identity(previous)
        for field, blocker in exact_blocker_by_field.items():
            candidate_value = candidate_identity.get(field)
            previous_value = previous_identity.get(field)
            if candidate_value and previous_value and candidate_value == previous_value:
                if blocker not in blockers:
                    blockers.append(blocker)
                if field not in duplicate_fields:
                    duplicate_fields.append(field)
                if len(duplicate_samples) < 10:
                    duplicate_samples.append(
                        {
                            "duplicate_field": field,
                            "duplicate_value": candidate_value,
                            "previous_index": index,
                            "previous_paper_result": previous.get("paper_result"),
                        }
                    )

        same_bucket = (
            str(previous.get("symbol") or "").upper() == str(candidate.get("symbol") or "").upper()
            and str(_first_present(previous.get("thesis_timeframe"), previous.get("timeframe")) or "") == str(candidate.get("thesis_timeframe") or "")
            and _paper_reentry_strategy_id(row=previous) == _paper_reentry_strategy_id(row=candidate)
            and _paper_reentry_row_side(previous) == _paper_reentry_row_side(candidate)
        )
        if not same_bucket:
            continue
        material_reasons = _paper_reentry_material_change_reasons(previous, candidate)
        if material_reasons:
            permitted_reasons.update(material_reasons)
            continue
        previous_candle_key = previous_identity.get("same_candle_same_thesis")
        candidate_candle_key = candidate_identity.get("same_candle_same_thesis")
        if previous_candle_key and candidate_candle_key and previous_candle_key == candidate_candle_key:
            if "same_candle_same_thesis" not in blockers:
                blockers.append("same_candle_same_thesis")
            if "same_candle_same_thesis" not in duplicate_fields:
                duplicate_fields.append("same_candle_same_thesis")
        if _paper_reentry_partial_close(previous) and "partial_close_reentry_without_material_change" not in blockers:
            blockers.append("partial_close_reentry_without_material_change")
        if "same_symbol_side_strategy_without_material_change" not in blockers:
            blockers.append("same_symbol_side_strategy_without_material_change")
        if len(duplicate_samples) < 10:
            duplicate_samples.append(
                {
                    "duplicate_field": "same_symbol_side_strategy_without_material_change",
                    "duplicate_value": candidate_candle_key,
                    "previous_index": index,
                    "previous_paper_result": previous.get("paper_result"),
                }
            )

    allowed = not blockers
    return {
        "schema_version": "paper_reentry_dedup_runtime_gate_v1",
        "status": "PASS_PAPER_REENTRY_DEDUP_GATE" if allowed else "BLOCKED_PAPER_REENTRY_DEDUP_GATE",
        "allowed": allowed,
        "blockers": blockers,
        "duplicate_identity_fields": duplicate_fields,
        "duplicate_identity_samples": duplicate_samples,
        "candidate_identity": candidate_identity,
        "previous_rows_examined": len(previous_rows),
        "permitted_reentry_reasons": sorted(permitted_reasons),
        "allowed_reentry_reasons": [
            "new_finalized_thesis_candle",
            "market_regime_change",
            "strategy_change",
            "direction_change",
            "expected_edge_improvement",
            "liquidation_or_microstructure_state_change",
            "cooldown_elapsed_with_fresh_independent_evidence",
        ],
        "runtime_wired_to_entry_gate": True,
        "paper_only": True,
        "paper_fill_allowed": allowed,
        "routes_to_live": False,
        "places_real_order": False,
    }


def _apply_paper_reentry_dedup_gate(intent: dict[str, Any], gate: dict[str, Any]) -> None:
    intent["paper_reentry_dedup_gate"] = gate
    if gate.get("allowed") is True:
        return
    blockers = [str(reason) for reason in gate.get("blockers") or [] if reason]
    intent["paper_fill_allowed"] = False
    intent["paper_reentry_dedup_blocked"] = True
    intent["paper_fill_block_reason"] = intent.get("paper_fill_block_reason") or PAPER_REENTRY_DEDUP_GATE_BLOCK_REASON
    intent["paper_fill_gate_block_reasons"] = sorted(set(
        list(intent.get("paper_fill_gate_block_reasons") or []) + blockers
    ))
    intent["local_block_reasons"] = sorted(set(
        list(intent.get("local_block_reasons") or [])
        + [f"paper_reentry_dedup:{reason}" for reason in blockers]
    ))


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


def _paper_quality_selected_direction(row: dict[str, Any]) -> str | None:
    raw = str(
        _first_present(
            row.get("selected_action"),
            row.get("side"),
            row.get("action"),
        )
        or ""
    ).strip().lower()
    if raw in {"long", "buy", "open_long", "proceed_long"} or raw.endswith("_long"):
        return "UP"
    if raw in {"short", "sell", "open_short", "proceed_short"} or raw.endswith("_short"):
        return "DOWN"
    if raw in {"hold", "no_trade", "none", "flat"}:
        return "FLAT"
    return None


def _paper_quality_actual_direction(row: dict[str, Any]) -> str | None:
    directional = str(row.get("directional_outcome") or "").strip().upper()
    if directional in {"UP", "DOWN", "FLAT"}:
        return directional
    realized = _coerce_float(_first_present(row.get("realized_net_pnl_bps"), row.get("realized_pnl_bps")))
    if realized is None:
        return None
    if abs(realized) < 1e-9:
        return "FLAT"
    selected = _paper_quality_selected_direction(row)
    if selected == "DOWN":
        return "DOWN" if realized > 0.0 else "UP"
    if selected == "UP":
        return "UP" if realized > 0.0 else "DOWN"
    return None


def _paper_quality_confidence_bucket(value: Any) -> str:
    confidence = _coerce_float(value)
    if confidence is None:
        return "MISSING"
    bounded = _clamp_float(confidence, 0.0, 1.0)
    low_index = min(9, max(0, int(bounded * 10.0)))
    low = low_index / 10.0
    high = 1.0 if low_index == 9 else (low_index + 1) / 10.0
    return f"{low:.1f}-{high:.1f}"


PAPER_QUALITY_CONTEXT_BUCKET_FIELDS = (
    "symbol",
    "timeframe",
    "side",
    "strategy",
    "regime",
    "confidence_bucket",
)


def _paper_quality_regime_from_labels(value: Any) -> str | None:
    if isinstance(value, str):
        labels = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        labels = [str(item).strip() for item in value if str(item).strip()]
    else:
        labels = []
    normalized = [label.upper() for label in labels if label]
    if not normalized:
        return None
    non_no_trade = [label for label in normalized if label != "NO_TRADE"]
    return ",".join(non_no_trade or normalized)


def _paper_quality_regime_value(row: dict[str, Any]) -> str:
    raw_regime = _first_present(
        row.get("market_regime_at_entry"),
        row.get("market_regime"),
        row.get("market_regime_at_exit"),
    )
    if raw_regime not in (None, ""):
        if isinstance(raw_regime, (list, tuple, set)):
            derived = _paper_quality_regime_from_labels(raw_regime)
            if derived:
                return derived
        return str(raw_regime)
    derived = _paper_quality_regime_from_labels(row.get("strategy_regime_labels"))
    return derived or "UNKNOWN"


def _paper_quality_context_bucket(row: dict[str, Any]) -> dict[str, str]:
    return {
        "symbol": str(row.get("symbol") or "UNKNOWN"),
        "timeframe": str(row.get("timeframe") or "UNKNOWN"),
        "side": str(
            _first_present(row.get("side"), row.get("selected_action"), row.get("action"))
            or "UNKNOWN"
        ).lower(),
        "strategy": str(
            _first_present(
                row.get("strategy_id"),
                row.get("strategy_family"),
                row.get("strategy_subtype"),
                row.get("strategy_selected_mode"),
                row.get("strategy_router_selected_mode"),
            )
            or "UNKNOWN"
        ),
        "regime": _paper_quality_regime_value(row),
        "confidence_bucket": _paper_quality_confidence_bucket(
            _first_present(
                row.get("confidence_calibrated"),
                row.get("selected_action_probability"),
                row.get("confidence_raw"),
            )
        ),
    }


def _paper_quality_context_bucket_key(bucket: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(bucket.get(field) or "") for field in PAPER_QUALITY_CONTEXT_BUCKET_FIELDS)


def _paper_quality_context_key(row: dict[str, Any]) -> tuple[str, ...]:
    return _paper_quality_context_bucket_key(_paper_quality_context_bucket(row))


def _paper_quality_context_key_public(key: tuple[str, ...]) -> str:
    return "|".join(key)


def _new_paper_quality_accumulator() -> dict[str, Any]:
    return {
        "sample_count": 0,
        "wins": 0,
        "losses": 0,
        "breakeven": 0,
        "realized_sum_bps": 0.0,
        "realized_values_bps": [],
        "profit_bps": 0.0,
        "loss_bps_abs": 0.0,
        "direction_total": 0,
        "direction_correct": 0,
        "expected_move_error_sum": 0.0,
        "expected_move_sample_count": 0,
        "calibration_rows": [],
        "up_tp": 0,
        "up_fp": 0,
        "up_fn": 0,
        "up_tn": 0,
    }


def _paper_quality_add_row(acc: dict[str, Any], row: dict[str, Any]) -> None:
    realized = _coerce_float(_first_present(row.get("realized_net_pnl_bps"), row.get("realized_pnl_bps")))
    if realized is None:
        return
    acc["sample_count"] += 1
    acc["realized_sum_bps"] += realized
    acc["realized_values_bps"].append(realized)
    if realized > 0.0:
        acc["wins"] += 1
        acc["profit_bps"] += realized
    elif realized < 0.0:
        acc["losses"] += 1
        acc["loss_bps_abs"] += abs(realized)
    else:
        acc["breakeven"] += 1

    predicted_direction = _paper_quality_selected_direction(row)
    actual_direction = _paper_quality_actual_direction(row)
    if predicted_direction in {"UP", "DOWN", "FLAT"} and actual_direction in {"UP", "DOWN", "FLAT"}:
        acc["direction_total"] += 1
        if predicted_direction == actual_direction:
            acc["direction_correct"] += 1
        if predicted_direction == "UP" and actual_direction == "UP":
            acc["up_tp"] += 1
        elif predicted_direction == "UP" and actual_direction != "UP":
            acc["up_fp"] += 1
        elif predicted_direction != "UP" and actual_direction == "UP":
            acc["up_fn"] += 1
        else:
            acc["up_tn"] += 1

    expected = _coerce_float(row.get("expected_move_after_cost_bps"))
    if expected is not None:
        acc["expected_move_error_sum"] += abs(expected - realized)
        acc["expected_move_sample_count"] += 1

    confidence = _coerce_float(
        _first_present(
            row.get("confidence_calibrated"),
            row.get("selected_action_probability"),
            row.get("confidence_raw"),
        )
    )
    profitable = row.get("action_was_profitable")
    if profitable is None:
        profitable = realized > 0.0
    if confidence is not None and isinstance(profitable, bool):
        acc["calibration_rows"].append(
            {
                "confidence": _clamp_float(confidence, 0.0, 1.0),
                "outcome": 1.0 if profitable else 0.0,
            }
        )


def _paper_quality_brier(rows: list[dict[str, float]]) -> float | None:
    if not rows:
        return None
    return sum((row["confidence"] - row["outcome"]) ** 2 for row in rows) / len(rows)


def _paper_quality_wilson_lower_bound(
    successes: int,
    total: int,
    *,
    z: float = 1.959963984540054,
) -> float | None:
    if total <= 0:
        return None
    p = successes / total
    denom = 1.0 + (z * z / total)
    centre = p + (z * z / (2.0 * total))
    margin = z * math.sqrt((p * (1.0 - p) + (z * z / (4.0 * total))) / total)
    return (centre - margin) / denom


def _paper_quality_mean_lower_confidence_bound(
    values: list[float],
    *,
    z: float = 1.959963984540054,
) -> float | None:
    if not values:
        return None
    mean = sum(values) / len(values)
    if len(values) == 1:
        return mean
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean - z * (math.sqrt(variance) / math.sqrt(len(values)))


def _paper_quality_profit_factor_payload(
    profit_bps: float,
    loss_bps_abs: float,
) -> tuple[float | str | None, float | None, bool]:
    if loss_bps_abs > 0.0:
        numeric = profit_bps / loss_bps_abs
        return numeric, numeric, False
    if profit_bps > 0.0:
        return "inf", math.inf, True
    return None, None, False


def _paper_quality_ece(
    rows: list[dict[str, float]],
    *,
    bucket_count: int = 10,
) -> tuple[float | None, list[dict[str, Any]]]:
    if not rows:
        return None, []
    total = len(rows)
    weighted_error = 0.0
    buckets: list[dict[str, Any]] = []
    for index in range(bucket_count):
        low = index / bucket_count
        high = (index + 1) / bucket_count
        if index == bucket_count - 1:
            bucket_rows = [row for row in rows if low <= row["confidence"] <= high]
        else:
            bucket_rows = [row for row in rows if low <= row["confidence"] < high]
        if not bucket_rows:
            continue
        avg_confidence = sum(row["confidence"] for row in bucket_rows) / len(bucket_rows)
        empirical = sum(row["outcome"] for row in bucket_rows) / len(bucket_rows)
        error = abs(avg_confidence - empirical)
        weighted_error += (len(bucket_rows) / total) * error
        buckets.append(
            {
                "bucket_min": low,
                "bucket_max": high,
                "sample_count": len(bucket_rows),
                "avg_confidence": avg_confidence,
                "empirical_success_rate": empirical,
                "absolute_calibration_error": error,
                "brier_score": _paper_quality_brier(bucket_rows),
            }
        )
    return weighted_error, buckets


def _paper_quality_finalize_accumulator(acc: dict[str, Any]) -> dict[str, Any]:
    sample_count = int(acc["sample_count"])
    calibration_rows = list(acc["calibration_rows"])
    ece, calibration_buckets = _paper_quality_ece(calibration_rows)
    direction_total = int(acc["direction_total"])
    trade_classified = int(acc["wins"]) + int(acc["losses"])
    realized_values = list(acc["realized_values_bps"])
    win_rate_after_cost = acc["wins"] / sample_count if sample_count else None
    win_rate_lcb = _paper_quality_wilson_lower_bound(int(acc["wins"]), sample_count)
    expectancy_lcb = _paper_quality_mean_lower_confidence_bound(realized_values)
    profit_factor, profit_factor_numeric, profit_factor_is_infinite = (
        _paper_quality_profit_factor_payload(float(acc["profit_bps"]), float(acc["loss_bps_abs"]))
    )
    up_precision_denominator = int(acc["up_tp"]) + int(acc["up_fp"])
    up_recall_denominator = int(acc["up_tp"]) + int(acc["up_fn"])
    up_fpr_denominator = int(acc["up_fp"]) + int(acc["up_tn"])
    up_fnr_denominator = int(acc["up_fn"]) + int(acc["up_tp"])
    return {
        "sample_count": sample_count,
        "directional_accuracy": (
            acc["direction_correct"] / direction_total if direction_total else None
        ),
        "directional_sample_count": direction_total,
        "expected_move_mae": (
            acc["expected_move_error_sum"] / acc["expected_move_sample_count"]
            if acc["expected_move_sample_count"]
            else None
        ),
        "expected_move_mae_sample_count": int(acc["expected_move_sample_count"]),
        "brier_score": _paper_quality_brier(calibration_rows),
        "ece": ece,
        "calibration_sample_count": len(calibration_rows),
        "confidence_reliability_buckets": calibration_buckets,
        "precision": acc["wins"] / trade_classified if trade_classified else None,
        "recall": None,
        "recall_unavailable_reason": (
            "closed executed paper outcomes do not include unexecuted profitable opportunities"
        ),
        "false_positive_rate": acc["losses"] / trade_classified if trade_classified else None,
        "false_negative_rate": None,
        "false_negative_rate_unavailable_reason": (
            "closed executed paper outcomes do not include abstained positive opportunities"
        ),
        "directional_up_precision": (
            acc["up_tp"] / up_precision_denominator if up_precision_denominator else None
        ),
        "directional_up_recall": (
            acc["up_tp"] / up_recall_denominator if up_recall_denominator else None
        ),
        "directional_up_false_positive_rate": (
            acc["up_fp"] / up_fpr_denominator if up_fpr_denominator else None
        ),
        "directional_up_false_negative_rate": (
            acc["up_fn"] / up_fnr_denominator if up_fnr_denominator else None
        ),
        "after_cost_expectancy_bps": (
            acc["realized_sum_bps"] / sample_count if sample_count else None
        ),
        "expectancy_95pct_lower_confidence_bound_bps": expectancy_lcb,
        "win_rate_after_cost": win_rate_after_cost,
        "win_rate_95pct_lower_confidence_bound": win_rate_lcb,
        "profit_factor": profit_factor,
        "profit_factor_numeric": (
            profit_factor_numeric
            if profit_factor_numeric is not None and math.isfinite(profit_factor_numeric)
            else None
        ),
        "profit_factor_is_infinite": profit_factor_is_infinite,
        "trade_outcome_counts": {
            "WIN": int(acc["wins"]),
            "LOSS": int(acc["losses"]),
            "BREAKEVEN": int(acc["breakeven"]),
        },
    }


def _paper_b_grade_model_quality_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source_rows: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            rejected["NON_OBJECT_ROW"] = rejected.get("NON_OBJECT_ROW", 0) + 1
            continue
        if not (
            row.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
            or row.get("calibration_label_purpose") == "B_GRADE_EXPLORATION_OUTCOME_LABEL"
        ):
            rejected["NOT_B_GRADE_EXPLORATION_OUTCOME"] = rejected.get(
                "NOT_B_GRADE_EXPLORATION_OUTCOME", 0
            ) + 1
            continue
        if row.get("paper_only") is not True:
            rejected["NOT_PAPER_ONLY"] = rejected.get("NOT_PAPER_ONLY", 0) + 1
            continue
        if _coerce_float(_first_present(row.get("realized_net_pnl_bps"), row.get("realized_pnl_bps"))) is None:
            rejected["MISSING_REALIZED_AFTER_COST_PNL_BPS"] = rejected.get(
                "MISSING_REALIZED_AFTER_COST_PNL_BPS", 0
            ) + 1
            continue
        source_rows.append(row)

    overall_acc = _new_paper_quality_accumulator()
    buckets: dict[str, dict[str, Any]] = {}
    bucket_dims: dict[str, dict[str, str]] = {}
    for row in source_rows:
        _paper_quality_add_row(overall_acc, row)
        dims = _paper_quality_context_bucket(row)
        key = "|".join(dims[field] for field in (
            "symbol",
            "timeframe",
            "side",
            "strategy",
            "regime",
            "confidence_bucket",
        ))
        bucket_dims.setdefault(key, dims)
        _paper_quality_add_row(buckets.setdefault(key, _new_paper_quality_accumulator()), row)

    by_bucket: list[dict[str, Any]] = []
    for key, acc in buckets.items():
        finalized = _paper_quality_finalize_accumulator(acc)
        finalized.update(bucket_dims[key])
        by_bucket.append(finalized)
    by_bucket.sort(
        key=lambda item: (
            -int(item.get("sample_count") or 0),
            str(item.get("symbol") or ""),
            str(item.get("timeframe") or ""),
            str(item.get("side") or ""),
            str(item.get("strategy") or ""),
            str(item.get("regime") or ""),
            str(item.get("confidence_bucket") or ""),
        )
    )

    overall = _paper_quality_finalize_accumulator(overall_acc)
    sample_count = int(overall["sample_count"])
    published_buckets = by_bucket[:B_GRADE_MODEL_QUALITY_BUCKET_LIMIT]
    return {
        "schema_version": "paper_b_grade_model_quality_status_v1",
        "generated_utc": _utc_iso(),
        "status": (
            "ACTIVE_B_GRADE_REALIZED_QUALITY_METRICS"
            if sample_count
            else "BLOCKED_NO_B_GRADE_REALIZED_OUTCOMES"
        ),
        "paper_only": True,
        "places_real_order": False,
        "scope": "B_GRADE_EXPLORATION_PAPER_CLOSED_OUTCOMES_ONLY",
        "counts_as_a_grade_evidence": False,
        "a_grade_promotion_allowed": False,
        "live_ready_implication": False,
        "source_feedback_row_count": len(rows),
        "b_grade_closed_outcome_count": len(source_rows),
        "rows_rejected_by_reason": rejected,
        **overall,
        "metric_summary": {
            "sample_count": sample_count,
            "bucket_count": len(by_bucket),
            "published_bucket_count": len(published_buckets),
            "directional_accuracy": overall.get("directional_accuracy"),
            "expected_move_mae": overall.get("expected_move_mae"),
            "brier_score": overall.get("brier_score"),
            "ece": overall.get("ece"),
            "precision": overall.get("precision"),
            "recall": overall.get("recall"),
            "false_positive_rate": overall.get("false_positive_rate"),
            "false_negative_rate": overall.get("false_negative_rate"),
            "after_cost_expectancy_bps": overall.get("after_cost_expectancy_bps"),
            "win_rate_after_cost": overall.get("win_rate_after_cost"),
            "profit_factor": overall.get("profit_factor"),
        },
        "bucket_count": len(by_bucket),
        "published_bucket_count": len(published_buckets),
        "metrics_by_bucket": published_buckets,
        "metrics_by_symbol_timeframe_side_strategy_regime_confidence_bucket": (
            published_buckets
        ),
        "bucket_limit": B_GRADE_MODEL_QUALITY_BUCKET_LIMIT,
    }


def _paper_quality_metric_breakdown(
    bucket_rows: list[dict[str, Any]],
    dimension: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in bucket_rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get(dimension) or "unknown")
        acc = grouped.setdefault(
            key,
            {
                dimension: key,
                "bucket_count": 0,
                "sample_count": 0,
                "directional_sample_count": 0,
                "expected_move_mae_sample_count": 0,
                "calibration_sample_count": 0,
                "trade_outcome_counts": {"WIN": 0, "LOSS": 0, "BREAKEVEN": 0},
                "_directional_accuracy_sum": 0.0,
                "_expected_move_mae_sum": 0.0,
                "_brier_sum": 0.0,
                "_ece_sum": 0.0,
                "_false_positive_rate_sum": 0.0,
                "_after_cost_expectancy_sum": 0.0,
            },
        )
        acc["bucket_count"] += 1
        sample_count = int(_coerce_float(row.get("sample_count")) or 0)
        directional_count = int(_coerce_float(row.get("directional_sample_count")) or 0)
        mae_count = int(_coerce_float(row.get("expected_move_mae_sample_count")) or 0)
        calibration_count = int(_coerce_float(row.get("calibration_sample_count")) or 0)
        acc["sample_count"] += sample_count
        acc["directional_sample_count"] += directional_count
        acc["expected_move_mae_sample_count"] += mae_count
        acc["calibration_sample_count"] += calibration_count
        for outcome, count in (row.get("trade_outcome_counts") or {}).items():
            if outcome in acc["trade_outcome_counts"]:
                acc["trade_outcome_counts"][outcome] += int(_coerce_float(count) or 0)
        directional_accuracy = _coerce_float(row.get("directional_accuracy"))
        if directional_accuracy is not None and directional_count:
            acc["_directional_accuracy_sum"] += directional_accuracy * directional_count
        expected_move_mae = _coerce_float(row.get("expected_move_mae"))
        if expected_move_mae is not None and mae_count:
            acc["_expected_move_mae_sum"] += expected_move_mae * mae_count
        brier_score = _coerce_float(row.get("brier_score"))
        if brier_score is not None and calibration_count:
            acc["_brier_sum"] += brier_score * calibration_count
        ece = _coerce_float(row.get("ece"))
        if ece is not None and calibration_count:
            acc["_ece_sum"] += ece * calibration_count
        false_positive_rate = _coerce_float(row.get("false_positive_rate"))
        if false_positive_rate is not None and directional_count:
            acc["_false_positive_rate_sum"] += false_positive_rate * directional_count
        expectancy = _coerce_float(row.get("after_cost_expectancy_bps"))
        if expectancy is not None and sample_count:
            acc["_after_cost_expectancy_sum"] += expectancy * sample_count

    rows: list[dict[str, Any]] = []
    for acc in grouped.values():
        sample_count = int(acc["sample_count"])
        directional_count = int(acc["directional_sample_count"])
        mae_count = int(acc["expected_move_mae_sample_count"])
        calibration_count = int(acc["calibration_sample_count"])
        rows.append({
            dimension: acc[dimension],
            "bucket_count": acc["bucket_count"],
            "sample_count": sample_count,
            "directional_sample_count": directional_count,
            "directional_accuracy": (
                acc["_directional_accuracy_sum"] / directional_count
                if directional_count
                else None
            ),
            "expected_move_mae_bps": (
                acc["_expected_move_mae_sum"] / mae_count if mae_count else None
            ),
            "brier_score": (
                acc["_brier_sum"] / calibration_count if calibration_count else None
            ),
            "ece": acc["_ece_sum"] / calibration_count if calibration_count else None,
            "false_positive_rate": (
                acc["_false_positive_rate_sum"] / directional_count
                if directional_count
                else None
            ),
            "after_cost_expectancy_bps": (
                acc["_after_cost_expectancy_sum"] / sample_count if sample_count else None
            ),
            "trade_outcome_counts": acc["trade_outcome_counts"],
        })
    rows.sort(key=lambda row: (-int(row.get("sample_count") or 0), str(row.get(dimension) or "")))
    return rows


def _paper_trainer_model_quality_runtime_status(
    model_quality_status: dict[str, Any],
    trainer_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    trainer_metrics = trainer_metrics if isinstance(trainer_metrics, dict) else {}
    training = trainer_metrics.get("training")
    training = training if isinstance(training, dict) else {}
    training_metrics = training.get("metrics")
    training_metrics = training_metrics if isinstance(training_metrics, dict) else {}
    checkpoint = trainer_metrics.get("checkpoint")
    checkpoint = checkpoint if isinstance(checkpoint, dict) else {}
    checkpoint_reload = trainer_metrics.get("checkpoint_reload")
    checkpoint_reload = checkpoint_reload if isinstance(checkpoint_reload, dict) else {}

    trusted_rows_loaded = int(
        _coerce_float(
            _first_present(
                training_metrics.get("trusted_rows_loaded"),
                training.get("trusted_rows_loaded"),
                training_metrics.get("accepted_training_rows"),
            )
        )
        or 0
    )
    optimizer_steps_last_hour = int(
        _coerce_float(
            _first_present(
                training_metrics.get("optimizer_steps_last_hour"),
                training_metrics.get("optimizer_steps_this_cycle"),
                training_metrics.get("optimizer_steps_total"),
            )
        )
        or 0
    )
    parameter_hash_before = _first_present(
        training_metrics.get("parameter_hash_before"),
        training.get("parameter_hash_before"),
    )
    parameter_hash_after = _first_present(
        training_metrics.get("parameter_hash_after"),
        training.get("parameter_hash_after"),
    )
    parameter_hash_changed = bool(training_metrics.get("parameter_hash_changed"))
    if not parameter_hash_changed and parameter_hash_before and parameter_hash_after:
        parameter_hash_changed = str(parameter_hash_before) != str(parameter_hash_after)
    checkpoint_written = bool(
        _first_present(
            training_metrics.get("checkpoint_written"),
            checkpoint.get("weight_blob_written"),
            checkpoint_reload.get("weight_blob_written"),
        )
    )
    checkpoint_reload_verified = bool(
        _first_present(
            training_metrics.get("checkpoint_reload_verified"),
            trainer_metrics.get("checkpoint_reload_verified"),
            checkpoint_reload.get("latest_checkpoint_loadable")
            and checkpoint_reload.get("model_state_restored"),
        )
    )
    weights_update = optimizer_steps_last_hour > 0 and parameter_hash_changed

    bucket_rows = model_quality_status.get(
        "metrics_by_symbol_timeframe_side_strategy_regime_confidence_bucket"
    )
    bucket_rows = bucket_rows if isinstance(bucket_rows, list) else []
    directional_accuracy = _coerce_float(model_quality_status.get("directional_accuracy"))
    after_cost_expectancy_bps = _coerce_float(
        model_quality_status.get("after_cost_expectancy_bps")
    )
    quality_metrics_current = (
        model_quality_status.get("status") == "ACTIVE_B_GRADE_REALIZED_QUALITY_METRICS"
        and int(_coerce_float(model_quality_status.get("sample_count")) or 0) > 0
    )
    accuracy_gt_baseline = directional_accuracy is not None and directional_accuracy > 0.5
    after_cost_expectancy_positive = (
        after_cost_expectancy_bps is not None and after_cost_expectancy_bps > 0.0
    )
    pass_conditions = {
        "weights_update": weights_update,
        "quality_metrics_current": quality_metrics_current,
        "accuracy_gt_baseline": accuracy_gt_baseline,
        "after_cost_expectancy_positive": after_cost_expectancy_positive,
        "checkpoint_written": checkpoint_written,
        "checkpoint_reload_verified": checkpoint_reload_verified,
    }
    status = (
        "PASSED_CURRENT_MODEL_QUALITY_PUBLISHED_A_GRADE_BLOCKED"
        if all(pass_conditions.values())
        else "BLOCKED_MODEL_QUALITY_OR_TRAINER_UPDATE_INCOMPLETE"
    )
    return {
        "schema_version": "paper_trainer_model_quality_runtime_status_v1",
        "generated_utc": _utc_iso(),
        "status": status,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "a_grade_promotion_allowed": False,
        "live_ready_implication": False,
        "ready_allowed": False,
        "weights_update": weights_update,
        "quality_metrics_current": quality_metrics_current,
        "trusted_rows_loaded": trusted_rows_loaded,
        "optimizer_steps_last_hour": optimizer_steps_last_hour,
        "parameter_hash_changed": parameter_hash_changed,
        "parameter_hash_before": parameter_hash_before,
        "parameter_hash_after": parameter_hash_after,
        "checkpoint_written": checkpoint_written,
        "checkpoint_reload_verified": checkpoint_reload_verified,
        "checkpoint_id": _first_present(
            checkpoint.get("checkpoint_id"),
            checkpoint_reload.get("checkpoint_id"),
        ),
        "directional_accuracy": directional_accuracy,
        "directional_baseline": 0.5,
        "expected_move_mae_bps": _coerce_float(model_quality_status.get("expected_move_mae")),
        "Brier": _coerce_float(model_quality_status.get("brier_score")),
        "brier_score": _coerce_float(model_quality_status.get("brier_score")),
        "ECE": _coerce_float(model_quality_status.get("ece")),
        "ece": _coerce_float(model_quality_status.get("ece")),
        "false_positive_rate": _coerce_float(model_quality_status.get("false_positive_rate")),
        "after_cost_expectancy_bps": after_cost_expectancy_bps,
        "accuracy_by_symbol": _paper_quality_metric_breakdown(bucket_rows, "symbol"),
        "accuracy_by_tf": _paper_quality_metric_breakdown(bucket_rows, "timeframe"),
        "accuracy_by_side": _paper_quality_metric_breakdown(bucket_rows, "side"),
        "accuracy_by_strategy": _paper_quality_metric_breakdown(bucket_rows, "strategy"),
        "pass_conditions": pass_conditions,
        "source": {
            "model_quality_status": "paper_b_grade_model_quality_status",
            "trainer_metrics": "redis:v2:trainer:hybrid_cuda:metrics",
        },
        "a_grade_blocker": "B_GRADE_OUTCOMES_ARE_LEARNING_ONLY_NOT_A_GRADE_EVIDENCE",
    }


def _paper_quality_profit_factor_numeric(value: Any) -> float | None:
    if isinstance(value, str) and value.strip().lower() == "inf":
        return math.inf
    return _coerce_float(value)


def _paper_b_grade_bucket_promotion_readiness_status(
    model_quality_status: dict[str, Any],
) -> dict[str, Any]:
    bucket_rows = model_quality_status.get(
        "metrics_by_symbol_timeframe_side_strategy_regime_confidence_bucket"
    )
    if not isinstance(bucket_rows, list):
        bucket_rows = []

    evaluated: list[dict[str, Any]] = []
    blocker_counts: dict[str, int] = {}
    metric_ready_count = 0
    for bucket in bucket_rows:
        if not isinstance(bucket, dict):
            blocker_counts["NON_OBJECT_BUCKET"] = blocker_counts.get("NON_OBJECT_BUCKET", 0) + 1
            continue
        sample_count = int(_coerce_float(bucket.get("sample_count")) or 0)
        outcome_counts = bucket.get("trade_outcome_counts")
        outcome_counts = outcome_counts if isinstance(outcome_counts, dict) else {}
        win_count = int(_coerce_float(outcome_counts.get("WIN")) or 0)
        loss_count = int(_coerce_float(outcome_counts.get("LOSS")) or 0)
        breakeven_count = int(_coerce_float(outcome_counts.get("BREAKEVEN")) or 0)
        point_win_rate = win_count / sample_count if sample_count else None
        win_rate_lcb = _paper_quality_wilson_lower_bound(win_count, sample_count)
        expectancy = _coerce_float(bucket.get("after_cost_expectancy_bps"))
        expectancy_lcb = _coerce_float(bucket.get("expectancy_95pct_lower_confidence_bound_bps"))
        profit_factor_numeric = _paper_quality_profit_factor_numeric(bucket.get("profit_factor"))

        sample_count_passes = sample_count >= B_GRADE_BUCKET_PROMOTION_MIN_SAMPLE_COUNT
        point_win_rate_passes = (
            point_win_rate is not None
            and point_win_rate >= B_GRADE_BUCKET_PROMOTION_MIN_WIN_RATE
        )
        win_rate_lcb_passes = (
            win_rate_lcb is not None
            and win_rate_lcb >= B_GRADE_BUCKET_PROMOTION_MIN_WIN_RATE_LCB
        )
        expectancy_passes = expectancy is not None and expectancy > 0.0
        expectancy_lcb_passes = (
            expectancy_lcb is not None
            and expectancy_lcb > B_GRADE_BUCKET_PROMOTION_MIN_EXPECTANCY_LCB_BPS
        )
        profit_factor_passes = (
            profit_factor_numeric is not None
            and profit_factor_numeric >= B_GRADE_BUCKET_PROMOTION_MIN_PROFIT_FACTOR
        )

        metric_blockers: list[str] = []
        if not sample_count_passes:
            metric_blockers.append("INSUFFICIENT_BUCKET_SAMPLE_COUNT")
        if not point_win_rate_passes:
            metric_blockers.append("POINT_WIN_RATE_BELOW_90P")
        if not win_rate_lcb_passes:
            metric_blockers.append("WIN_RATE_95PCT_LCB_BELOW_90P")
        if not expectancy_passes:
            metric_blockers.append("NON_POSITIVE_AFTER_COST_EXPECTANCY")
        if not expectancy_lcb_passes:
            metric_blockers.append("NON_POSITIVE_EXPECTANCY_LOWER_CONFIDENCE_BOUND")
        if not profit_factor_passes:
            metric_blockers.append("PROFIT_FACTOR_BELOW_2")

        metric_conditions_pass = not metric_blockers
        if metric_conditions_pass:
            metric_ready_count += 1

        promotion_blockers = [
            *metric_blockers,
            "B_GRADE_OUTCOMES_ARE_LEARNING_ONLY_NOT_A_GRADE_EVIDENCE",
            "UNTOUCHED_HOLDOUT_AND_FROZEN_POLICY_NOT_VERIFIED_FOR_BUCKET",
            "REALTIME_A_GRADE_ECONOMIC_OUTCOME_CONTRACT_NOT_SATISFIED",
        ]
        for reason in promotion_blockers:
            blocker_counts[reason] = blocker_counts.get(reason, 0) + 1

        evaluated.append(
            {
                "symbol": bucket.get("symbol"),
                "timeframe": bucket.get("timeframe"),
                "side": bucket.get("side"),
                "strategy": bucket.get("strategy"),
                "regime": bucket.get("regime"),
                "confidence_bucket": bucket.get("confidence_bucket"),
                "closed_economic_outcome_count": sample_count,
                "win_count": win_count,
                "loss_count": loss_count,
                "breakeven_count": breakeven_count,
                "point_win_rate_after_cost": point_win_rate,
                "win_rate_95pct_lower_confidence_bound": win_rate_lcb,
                "after_cost_expectancy_bps": expectancy,
                "expectancy_95pct_lower_confidence_bound_bps": expectancy_lcb,
                "profit_factor": bucket.get("profit_factor"),
                "profit_factor_numeric": (
                    profit_factor_numeric
                    if profit_factor_numeric is not None and math.isfinite(profit_factor_numeric)
                    else None
                ),
                "profit_factor_is_infinite": profit_factor_numeric == math.inf,
                "sample_count_passes": sample_count_passes,
                "point_win_rate_passes": point_win_rate_passes,
                "win_rate_lcb_passes": win_rate_lcb_passes,
                "expectancy_after_cost_passes": expectancy_passes,
                "expectancy_lcb_passes": expectancy_lcb_passes,
                "profit_factor_passes": profit_factor_passes,
                "bucket_metric_conditions_pass": metric_conditions_pass,
                "metric_blocker_reasons": metric_blockers,
                "promotion_blocker_reasons": promotion_blockers,
                "counts_as_a_grade_evidence": False,
                "a_grade_promotion_allowed": False,
                "a_grade_execution_tier_if_candidate_now": PAPER_TIER_SHADOW_ONLY,
                "allowed_learning_tier": PAPER_TIER_B_GRADE_EXPLORATION,
            }
        )

    evaluated.sort(
        key=lambda item: (
            len(item.get("promotion_blocker_reasons") or []),
            -int(item.get("closed_economic_outcome_count") or 0),
            str(item.get("symbol") or ""),
            str(item.get("timeframe") or ""),
            str(item.get("side") or ""),
            str(item.get("strategy") or ""),
            str(item.get("regime") or ""),
            str(item.get("confidence_bucket") or ""),
        )
    )

    bucket_count = len(evaluated)
    insufficient_sample_bucket_count = 0
    buckets_at_or_above_minimum_count = 0
    sample_count_deficit_total = 0
    sample_count_distribution = {
        "0": 0,
        "1": 0,
        "2_to_4": 0,
        "5_to_9": 0,
        "10_to_19": 0,
        "20_to_29": 0,
        "30_or_more": 0,
    }
    label_collection_priority: list[dict[str, Any]] = []
    for bucket in evaluated:
        sample_count = int(bucket.get("closed_economic_outcome_count") or 0)
        if sample_count <= 0:
            sample_count_distribution["0"] += 1
        elif sample_count == 1:
            sample_count_distribution["1"] += 1
        elif sample_count <= 4:
            sample_count_distribution["2_to_4"] += 1
        elif sample_count <= 9:
            sample_count_distribution["5_to_9"] += 1
        elif sample_count <= 19:
            sample_count_distribution["10_to_19"] += 1
        elif sample_count < B_GRADE_BUCKET_PROMOTION_MIN_SAMPLE_COUNT:
            sample_count_distribution["20_to_29"] += 1
        else:
            sample_count_distribution["30_or_more"] += 1

        deficit = max(0, B_GRADE_BUCKET_PROMOTION_MIN_SAMPLE_COUNT - sample_count)
        if deficit:
            insufficient_sample_bucket_count += 1
            sample_count_deficit_total += deficit
        else:
            buckets_at_or_above_minimum_count += 1

        metric_blockers = set(bucket.get("metric_blocker_reasons") or [])
        only_sample_depth_blocked = metric_blockers.issubset({
            "INSUFFICIENT_BUCKET_SAMPLE_COUNT",
            "WIN_RATE_95PCT_LCB_BELOW_90P",
        })
        if (
            deficit
            and only_sample_depth_blocked
            and bucket.get("point_win_rate_passes") is True
            and bucket.get("expectancy_after_cost_passes") is True
            and bucket.get("expectancy_lcb_passes") is True
            and bucket.get("profit_factor_passes") is True
        ):
            priority_bucket = {
                "symbol": bucket.get("symbol"),
                "timeframe": bucket.get("timeframe"),
                "side": bucket.get("side"),
                "strategy": bucket.get("strategy"),
                "regime": bucket.get("regime"),
                "confidence_bucket": bucket.get("confidence_bucket"),
                "closed_economic_outcome_count": sample_count,
                "sample_count_deficit_to_minimum": deficit,
                "point_win_rate_after_cost": bucket.get("point_win_rate_after_cost"),
                "win_rate_95pct_lower_confidence_bound": (
                    bucket.get("win_rate_95pct_lower_confidence_bound")
                ),
                "after_cost_expectancy_bps": bucket.get("after_cost_expectancy_bps"),
                "expectancy_95pct_lower_confidence_bound_bps": (
                    bucket.get("expectancy_95pct_lower_confidence_bound_bps")
                ),
                "profit_factor": bucket.get("profit_factor"),
                "priority_reason": (
                    "PAPER_ONLY_COLLECT_MORE_B_GRADE_LABELS_FOR_PROMISING_UNDERPOWERED_BUCKET"
                ),
                "paper_only": True,
                "places_real_order": False,
                "counts_as_a_grade_evidence": False,
                "a_grade_promotion_allowed": False,
                "live_ready_implication": False,
            }
            label_collection_priority.append(priority_bucket)

    label_collection_priority.sort(
        key=lambda item: (
            int(item.get("sample_count_deficit_to_minimum") or 0),
            -float(item.get("closed_economic_outcome_count") or 0),
            -float(item.get("win_rate_95pct_lower_confidence_bound") or 0.0),
            -float(item.get("expectancy_95pct_lower_confidence_bound_bps") or 0.0),
            str(item.get("symbol") or ""),
            str(item.get("timeframe") or ""),
            str(item.get("side") or ""),
        )
    )
    if not bucket_count:
        fragmentation_status = "BLOCKED_NO_B_GRADE_REALIZED_BUCKETS"
    elif insufficient_sample_bucket_count:
        fragmentation_status = "BLOCKED_FRAGMENTED_B_GRADE_EVIDENCE"
    else:
        fragmentation_status = "READY_B_GRADE_BUCKET_SAMPLE_COVERAGE"
    evidence_fragmentation = {
        "schema_version": "paper_b_grade_evidence_fragmentation_status_v1",
        "status": fragmentation_status,
        "paper_only": True,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "a_grade_promotion_allowed": False,
        "live_ready_implication": False,
        "bucket_count": bucket_count,
        "minimum_bucket_sample_count": B_GRADE_BUCKET_PROMOTION_MIN_SAMPLE_COUNT,
        "insufficient_sample_bucket_count": insufficient_sample_bucket_count,
        "buckets_at_or_above_minimum_count": buckets_at_or_above_minimum_count,
        "sample_count_deficit_to_minimum_total": sample_count_deficit_total,
        "sample_count_distribution": sample_count_distribution,
        "paper_only_label_collection_priority_bucket_count": len(label_collection_priority),
        "diagnostic_policy": (
            "Ranks underpowered B-grade buckets for paper-only label collection. "
            "It never promotes B-grade outcomes, opens live routing, or counts "
            "NO_TRADE as an economic win."
        ),
    }
    return {
        "schema_version": "paper_b_grade_bucket_promotion_readiness_status_v1",
        "generated_utc": _utc_iso(),
        "status": (
            "BLOCKED_B_GRADE_BUCKETS_NOT_A_GRADE_READY"
            if bucket_count
            else "BLOCKED_NO_B_GRADE_REALIZED_BUCKETS"
        ),
        "scope": "B_GRADE_EXPLORATION_PAPER_BUCKETS_ONLY",
        "paper_only": True,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "a_grade_promotion_allowed": False,
        "live_ready_implication": False,
        "source_schema_version": model_quality_status.get("schema_version"),
        "source_b_grade_closed_outcome_count": model_quality_status.get(
            "b_grade_closed_outcome_count"
        ),
        "source_bucket_count": bucket_count,
        "metric_ready_bucket_count": metric_ready_count,
        "a_grade_promotable_bucket_count": 0,
        "thresholds": {
            "minimum_bucket_sample_count": B_GRADE_BUCKET_PROMOTION_MIN_SAMPLE_COUNT,
            "point_win_rate_min": B_GRADE_BUCKET_PROMOTION_MIN_WIN_RATE,
            "win_rate_95pct_lcb_min": B_GRADE_BUCKET_PROMOTION_MIN_WIN_RATE_LCB,
            "expectancy_95pct_lcb_bps_min_exclusive": (
                B_GRADE_BUCKET_PROMOTION_MIN_EXPECTANCY_LCB_BPS
            ),
            "profit_factor_min": B_GRADE_BUCKET_PROMOTION_MIN_PROFIT_FACTOR,
        },
        "non_promotion_contract": {
            "b_grade_outcomes_are_learning_only": True,
            "requires_frozen_policy_untouched_holdout": True,
            "requires_new_realtime_a_grade_economic_outcomes": True,
            "failing_bucket_execution_tier": PAPER_TIER_SHADOW_ONLY,
            "does_not_change_live_execution": True,
        },
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "evidence_fragmentation_status": evidence_fragmentation,
        "paper_only_label_collection_priority_buckets": (
            label_collection_priority[:B_GRADE_MODEL_QUALITY_BUCKET_LIMIT]
        ),
        "buckets": evaluated[:B_GRADE_MODEL_QUALITY_BUCKET_LIMIT],
        "bucket_limit": B_GRADE_MODEL_QUALITY_BUCKET_LIMIT,
    }


def _paper_only_label_collection_priority_index(
    readiness_status: dict[str, Any],
) -> dict[tuple[str, ...], dict[str, Any]]:
    rows = readiness_status.get("paper_only_label_collection_priority_buckets")
    if not isinstance(rows, list):
        return {}
    source_generated_utc = readiness_status.get("generated_utc")
    index: dict[tuple[str, ...], dict[str, Any]] = {}
    for rank, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        key = _paper_quality_context_bucket_key(row)
        if not all(key):
            continue
        bucket = dict(row)
        bucket["paper_only_label_collection_priority_rank"] = rank
        bucket["paper_only_label_collection_priority_bucket_key"] = (
            _paper_quality_context_key_public(key)
        )
        bucket["paper_only_label_collection_priority_source_generated_utc"] = (
            source_generated_utc
        )
        bucket["paper_only"] = True
        bucket["places_real_order"] = False
        bucket["counts_as_a_grade_evidence"] = False
        bucket["a_grade_promotion_allowed"] = False
        bucket["live_ready_implication"] = False
        index.setdefault(key, bucket)
    return index


def _read_paper_only_label_collection_priority_index() -> dict[tuple[str, ...], dict[str, Any]]:
    try:
        decoded = json.loads(
            PAPER_B_GRADE_BUCKET_PROMOTION_READINESS_STATUS_PATH.read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return _paper_only_label_collection_priority_index(decoded)


def _paper_only_label_collection_priority_payload(
    row: dict[str, Any],
    priority_index: dict[tuple[str, ...], dict[str, Any]],
) -> dict[str, Any] | None:
    if not priority_index:
        return None
    key = _paper_quality_context_key(row)
    bucket = priority_index.get(key)
    if bucket is None:
        return None
    return {
        "paper_only_label_collection_priority": True,
        "paper_only_label_collection_priority_reason": str(
            bucket.get("priority_reason")
            or "PAPER_ONLY_COLLECT_MORE_B_GRADE_LABELS_FOR_PROMISING_UNDERPOWERED_BUCKET"
        ),
        "paper_only_label_collection_priority_rank": bucket.get(
            "paper_only_label_collection_priority_rank"
        ),
        "paper_only_label_collection_priority_bucket_key": bucket.get(
            "paper_only_label_collection_priority_bucket_key"
        ),
        "paper_only_label_collection_priority_bucket": {
            field: bucket.get(field) for field in PAPER_QUALITY_CONTEXT_BUCKET_FIELDS
        },
        "paper_only_label_collection_priority_sample_count_deficit_to_minimum": (
            bucket.get("sample_count_deficit_to_minimum")
        ),
        "paper_only_label_collection_priority_closed_economic_outcome_count": (
            bucket.get("closed_economic_outcome_count")
        ),
        "paper_only_label_collection_priority_source_generated_utc": bucket.get(
            "paper_only_label_collection_priority_source_generated_utc"
        ),
        "counts_as_a_grade_evidence": False,
        "a_grade_promotion_allowed": False,
        "live_ready_implication": False,
    }


def _attach_paper_only_label_collection_priority(
    *,
    intent: dict[str, Any],
    allocation: dict[str, Any],
    priority_index: dict[tuple[str, ...], dict[str, Any]],
) -> dict[str, Any] | None:
    payload = _paper_only_label_collection_priority_payload(intent, priority_index)
    if payload is None:
        return None
    for target in (intent, allocation):
        target.update(payload)
    model_inputs = allocation.get("model_inputs")
    if not isinstance(model_inputs, dict):
        model_inputs = {}
        allocation["model_inputs"] = model_inputs
    for field in PAPER_ONLY_LABEL_COLLECTION_PRIORITY_FIELDS:
        if field in payload:
            model_inputs[field] = payload[field]
    return payload


def _paper_candidate_allocation_publication_row(row: dict[str, Any]) -> dict[str, Any]:
    published = dict(row)
    _normalize_paper_candidate_accounting_publication(published)
    published.setdefault("paper_only", True)
    published.setdefault("places_real_order", False)
    published.setdefault("live_order", False)
    published.setdefault("test_order", False)
    published.setdefault("leverage_mutation", False)
    published.setdefault("margin_mode_mutation", False)
    tier = _explicit_paper_opportunity_tier(published)
    if tier in {PAPER_TIER_A_GRADE_EXECUTION, PAPER_TIER_B_GRADE_EXPLORATION}:
        return published

    raw_tier = _first_present(
        published.get("paper_opportunity_tier"),
        published.get("paper_execution_tier"),
        published.get("opportunity_tier"),
        published.get("calibrated_opportunity_tier"),
        published.get("candidate_selection_tier"),
        published.get("explicit_paper_opportunity_tier"),
        published.get("admission_tier"),
        published.get("candidate_tier"),
    )
    normalized_raw_tier = str(raw_tier or "").strip().upper()
    original_tier_reason = published.get("paper_opportunity_tier_reason")
    if normalized_raw_tier in NON_EXECUTABLE_PAPER_TIERS:
        publication_tier = normalized_raw_tier
        block_reason = f"NON_EXECUTABLE_PAPER_TIER:{publication_tier}"
    else:
        publication_tier = PAPER_TIER_SHADOW_ONLY
        block_reason = "MISSING_OR_INVALID_EXPLICIT_PAPER_OPPORTUNITY_TIER"
        published["original_paper_opportunity_tier_before_publication_block"] = raw_tier
    if original_tier_reason not in {None, ""} and original_tier_reason != block_reason:
        published.setdefault("pre_non_executable_paper_tier", raw_tier)
        published.setdefault("pre_non_executable_paper_tier_reason", original_tier_reason)
    published["non_executable_paper_tier_block_reason"] = block_reason

    original_decision = published.get("allocator_decision")
    if original_decision not in {None, ""}:
        published.setdefault(
            "original_allocator_decision_before_paper_tier_block",
            original_decision,
        )
    for field in (
        "risk_budget_usd",
        "gross_notional_usd",
        "allocated_margin_usd",
        "target_notional_usdt",
        "target_quantity",
        "expected_net_pnl_usd",
        "expected_shortfall_usd",
        "hedge_budget_usd",
        "hedge_expected_shortfall_reduction_usd",
        "expected_shortfall_before",
        "expected_shortfall_after",
        "hedge_cost_usd",
    ):
        value = published.get(field)
        if value not in {None, ""}:
            published.setdefault(f"pre_paper_tier_block_{field}", value)
        published[field] = 0.0

    published["paper_opportunity_tier"] = publication_tier
    published["paper_opportunity_tier_reason"] = block_reason
    published["allocator_decision"] = "BLOCK_NON_EXECUTABLE_PAPER_TIER"
    published["final_size_reason"] = block_reason
    published["capital_allocation_reason"] = block_reason
    published["paper_allocation_block_reason"] = block_reason
    published["non_executable_paper_tier_blocked"] = True
    published["candidate_allocation_publication_blocked"] = True
    published["paper_only"] = True
    published["places_real_order"] = False
    published["live_order"] = False
    return published


def _record_paper_accounting_normalization(
    row: dict[str, Any],
    *,
    target_field: str,
    source_field: str,
    normalization: str,
) -> None:
    records = row.setdefault("paper_accounting_normalized_fields", [])
    if not isinstance(records, list):
        return
    records.append({
        "target_field": target_field,
        "source_field": source_field,
        "normalization": normalization,
    })


def _set_paper_accounting_field_if_missing(
    row: dict[str, Any],
    target_field: str,
    value: Any,
    *,
    source_field: str,
    normalization: str,
) -> bool:
    if row.get(target_field) not in (None, "") or value in (None, ""):
        return False
    row[target_field] = value
    _record_paper_accounting_normalization(
        row,
        target_field=target_field,
        source_field=source_field,
        normalization=normalization,
    )
    return True


def _paper_take_profit_price_from_expected_move(row: dict[str, Any]) -> tuple[float | None, str | None]:
    entry_price = _coerce_float(_first_present(
        row.get("fill_price"),
        row.get("entry_price"),
        row.get("price"),
        row.get("mark_price"),
    ))
    move_bps = _coerce_float(_first_present(
        row.get("expected_move_after_cost_bps"),
        row.get("expected_net_edge_bps"),
        row.get("expected_move_bps"),
    ))
    side = _normalized_directional_side(_first_present(
        row.get("side"),
        row.get("selected_action"),
        row.get("action"),
    ))
    if entry_price is None or entry_price <= 0.0 or move_bps is None or move_bps == 0.0 or side is None:
        return None, None
    distance = abs(move_bps) / 10_000.0
    if side == "long":
        target = entry_price * (1.0 + distance)
    else:
        target = entry_price * max(0.0, 1.0 - distance)
    if target <= 0.0:
        return None, None
    return round(target, 12), "expected_move_after_cost_bps"


def _paper_timeframe_seconds(timeframe: Any) -> int:
    value = str(timeframe or "").strip().lower()
    mapping = {
        "1m": 300,
        "5m": 900,
        "15m": 1800,
        "1h": 7200,
        "4h": 21600,
    }
    return mapping.get(value, 3600)


def _paper_hedge_cost_usd(row: dict[str, Any], hedge_ratio: float | None) -> float:
    explicit_cost = _coerce_float(row.get("hedge_cost_usd"))
    if explicit_cost is not None:
        return round(abs(explicit_cost), 8)
    parent_cost = 0.0
    for field in ("expected_fees_usd", "expected_slippage_usd", "expected_funding_usd"):
        value = _coerce_float(row.get(field))
        if value is not None:
            parent_cost += abs(value)
    ratio = hedge_ratio if hedge_ratio is not None and hedge_ratio > 0.0 else 1.0
    return round(parent_cost * min(ratio, 1.0), 8)


def _block_paper_hedge_admission(
    row: dict[str, Any],
    *,
    reason: str,
    hedge_budget: float,
    hedge_cost: float,
    shortfall_reduction: float,
    expected_shortfall_before: float | None,
) -> None:
    row.setdefault("pre_hedge_admission_block_hedge_budget_usd", round(hedge_budget, 8))
    row.setdefault(
        "pre_hedge_admission_block_hedge_expected_shortfall_reduction_usd",
        round(shortfall_reduction, 8),
    )
    row["hedge_admission_status"] = "NO_HEDGE"
    row["hedge_admission_block_reason"] = reason
    row["hedge_enabled"] = False
    row["hedge_budget_usd"] = 0.0
    row["hedge_expected_shortfall_reduction_usd"] = 0.0
    row["hedge_cost_usd"] = round(hedge_cost, 8)
    if expected_shortfall_before is not None:
        row["expected_shortfall_before"] = round(expected_shortfall_before, 8)
        row["expected_shortfall_after"] = round(expected_shortfall_before, 8)
    for field in (
        "hedge_parent_id",
        "hedge_child_id",
        "hedge_intent",
        "hedge_ratio",
        "maximum_duration",
        "unwind_plan",
    ):
        row.pop(field, None)
    _record_paper_accounting_normalization(
        row,
        target_field="hedge_enabled",
        source_field="hedge_expected_shortfall_reduction_usd:hedge_cost_usd",
        normalization=reason,
    )


def _paper_stress_abs(value: Any) -> float | None:
    parsed = _coerce_float(value)
    if parsed is None:
        return None
    return abs(float(parsed))


def _paper_stress_source(
    row: dict[str, Any],
    model_inputs: dict[str, Any],
    *fields: str,
) -> tuple[float | None, str | None]:
    for field in fields:
        value = _paper_stress_abs(row.get(field))
        if value is not None:
            return value, field
        value = _paper_stress_abs(model_inputs.get(field))
        if value is not None:
            return value, f"model_inputs.{field}"
    return None, None


def _paper_depth_collapse_bps(
    *,
    depth_impact_bps: float | None,
    depth_utilization_pct: float | None,
    liquidity_score: float | None,
) -> tuple[float | None, str | None]:
    values: list[float] = []
    sources: list[str] = []
    if depth_impact_bps is not None:
        values.append(depth_impact_bps * 3.0)
        sources.append("depth_price_impact_bps")
    if depth_utilization_pct is not None:
        utilization = depth_utilization_pct
        if utilization <= 1.0:
            utilization *= 100.0
        values.append(max(0.0, utilization) * 2.0)
        sources.append("depth_utilization_pct")
    if liquidity_score is not None:
        values.append(max(0.0, 1.0 - max(0.0, min(1.0, liquidity_score))) * 250.0)
        sources.append("allocator_liquidity_score")
    if not values:
        return None, None
    return round(max(values), 8), "+".join(sources)


def _derive_paper_rare_event_stress_suite(row: dict[str, Any]) -> dict[str, Any]:
    model_inputs = row.get("model_inputs") if isinstance(row.get("model_inputs"), dict) else {}
    missing_inputs: list[str] = []
    scenario_sources: dict[str, str] = {}
    scenarios: dict[str, dict[str, Any]] = {}

    atr_bps, atr_source = _paper_stress_source(row, model_inputs, "entry_atr_bps", "atr_bps", "volatility_bps")
    expected_move_bps, expected_move_source = _paper_stress_source(
        row,
        model_inputs,
        "expected_move_after_cost_bps",
        "expected_move_bps",
    )
    spread_bps, spread_source = _paper_stress_source(
        row,
        model_inputs,
        "actual_observed_spread_entry_bps",
        "observed_bid_ask_spread_bps",
        "bid_ask_spread_bps",
        "entry_spread_bps",
    )
    if row.get("bid_ask_spread_bps_fallback") is True:
        spread_bps = None
        spread_source = None
        missing_inputs.append("observed_non_fallback_spread_bps")
    depth_impact_bps, depth_impact_source = _paper_stress_source(
        row,
        model_inputs,
        "depth_price_impact_bps",
        "depth_impact_bps",
    )
    depth_utilization_pct, depth_utilization_source = _paper_stress_source(row, model_inputs, "depth_utilization_pct")
    liquidity_score, liquidity_source = _paper_stress_source(
        row,
        model_inputs,
        "allocator_liquidity_score",
        "liquidity_score",
    )
    funding_bps, funding_source = _paper_stress_source(
        row,
        model_inputs,
        "expected_funding_bps",
        "funding_bps",
        "funding_rate_bps",
    )
    funding_rate, funding_rate_source = _paper_stress_source(row, model_inputs, "funding_rate")
    if funding_bps is None and funding_rate is not None:
        funding_bps = funding_rate * 10000.0
        funding_source = funding_rate_source or "funding_rate"
    correlation_pct, correlation_source = _paper_stress_source(
        row,
        model_inputs,
        "correlation_exposure_pct",
        "portfolio_correlation_pct",
    )
    liquidation_pressure, liquidation_source = _paper_stress_source(
        row,
        model_inputs,
        "liquidation_pressure",
        "liquidation_strength",
        "liquidation_cascade_risk",
        "squeeze_evidence_score",
    )
    mark_index_bps, mark_index_source = _paper_stress_source(
        row,
        model_inputs,
        "mark_index_divergence_bps",
        "mark_index_divergence",
    )
    latency_ms, latency_source = _paper_stress_source(
        row,
        model_inputs,
        "latency_ms",
        "paper_fill_latency_ms",
        "fill_latency_ms",
        "execution_latency_ms",
        "simulated_latency_ms",
    )
    leverage, leverage_source = _paper_stress_source(
        row,
        model_inputs,
        "recommended_leverage",
        "effective_leverage",
        "selected_leverage",
    )

    def set_scenario(name: str, value: float | None, source: str | None) -> None:
        if value is None:
            missing_inputs.append(name)
            return
        scenarios[name] = {
            "adverse_move_bps": round(max(0.0, value), 8),
            "source": source or "derived_from_candidate_context",
        }
        scenario_sources[name] = source or "derived_from_candidate_context"

    gap_value = None
    gap_sources: list[str] = []
    if atr_bps is not None:
        gap_value = max(gap_value or 0.0, atr_bps * 2.5)
        gap_sources.append(atr_source or "atr_bps")
    if expected_move_bps is not None:
        gap_value = max(gap_value or 0.0, expected_move_bps * 2.0)
        gap_sources.append(expected_move_source or "expected_move_bps")
    set_scenario("gap_shock", gap_value, "+".join(gap_sources) or None)

    set_scenario(
        "spread_explosion",
        spread_bps * 5.0 if spread_bps is not None else None,
        spread_source,
    )
    depth_collapse, depth_source = _paper_depth_collapse_bps(
        depth_impact_bps=depth_impact_bps,
        depth_utilization_pct=depth_utilization_pct,
        liquidity_score=liquidity_score,
    )
    if depth_source is None:
        depth_source = "+".join(
            source
            for source in (depth_impact_source, depth_utilization_source, liquidity_source)
            if source
        ) or None
    set_scenario("depth_collapse", depth_collapse, depth_source)
    set_scenario(
        "funding_spike",
        funding_bps * 10.0 if funding_bps is not None else None,
        funding_source,
    )
    set_scenario(
        "correlated_portfolio_shock",
        correlation_pct * 100.0 if correlation_pct is not None else None,
        correlation_source,
    )
    squeeze_value = None
    if liquidation_pressure is not None:
        pressure = liquidation_pressure if liquidation_pressure <= 1.0 else liquidation_pressure / 100.0
        squeeze_value = max(0.0, min(1.0, pressure)) * 500.0
    set_scenario("long_squeeze", squeeze_value, liquidation_source)
    set_scenario("short_squeeze", squeeze_value, liquidation_source)
    cascade_value = None
    cascade_sources: list[str] = []
    if squeeze_value is not None:
        cascade_value = max(cascade_value or 0.0, squeeze_value * 1.25)
        cascade_sources.append(liquidation_source or "liquidation_pressure")
    if correlation_pct is not None:
        cascade_value = max(cascade_value or 0.0, correlation_pct * 125.0)
        cascade_sources.append(correlation_source or "correlation_exposure_pct")
    set_scenario("double_sided_liquidation_cascade", cascade_value, "+".join(cascade_sources) or None)
    set_scenario("mark_index_divergence", mark_index_bps, mark_index_source)
    set_scenario(
        "exchange_api_delay",
        (latency_ms / 1000.0) * max(atr_bps or 0.0, 1.0) if latency_ms is not None else None,
        latency_source,
    )

    execution_uncertainty = None
    execution_sources: list[str] = []
    if spread_bps is not None:
        execution_uncertainty = max(execution_uncertainty or 0.0, spread_bps)
        execution_sources.append(spread_source or "spread_bps")
    if depth_impact_bps is not None:
        execution_uncertainty = max(execution_uncertainty or 0.0, depth_impact_bps)
        execution_sources.append(depth_impact_source or "depth_price_impact_bps")
    if latency_ms is not None and atr_bps is not None:
        execution_uncertainty = max(execution_uncertainty or 0.0, (latency_ms / 1000.0) * atr_bps)
        execution_sources.append(latency_source or "latency_ms")
    correlation_stress = correlation_pct * 100.0 if correlation_pct is not None else None
    maintenance_margin_uncertainty = None
    if leverage is not None and leverage > 0.0:
        maintenance_margin_uncertainty = 100.0 / leverage

    components: dict[str, float] = {}
    component_sources: dict[str, str] = {}
    if execution_uncertainty is None:
        missing_inputs.append("execution_uncertainty_bps")
    else:
        components["execution_uncertainty_bps"] = round(execution_uncertainty, 8)
        component_sources["execution_uncertainty_bps"] = "+".join(execution_sources) or "execution_context"
    if correlation_stress is None:
        missing_inputs.append("correlation_stress_bps")
    else:
        components["correlation_stress_bps"] = round(correlation_stress, 8)
        component_sources["correlation_stress_bps"] = correlation_source or "correlation_exposure_pct"
    if maintenance_margin_uncertainty is None:
        missing_inputs.append("maintenance_margin_uncertainty_bps")
    else:
        components["maintenance_margin_uncertainty_bps"] = round(maintenance_margin_uncertainty, 8)
        component_sources["maintenance_margin_uncertainty_bps"] = leverage_source or "recommended_leverage"

    modeled_adverse = max(
        (scenario["adverse_move_bps"] for scenario in scenarios.values()),
        default=None,
    )
    required_buffer = None
    if modeled_adverse is not None and len(components) == len(RARE_EVENT_BUFFER_COMPONENT_FIELDS):
        required_buffer = modeled_adverse + sum(components.values())
    liquidation_buffer = _coerce_float(row.get("liquidation_buffer_bps"))
    buffer_passed = (
        liquidation_buffer is not None
        and required_buffer is not None
        and liquidation_buffer >= required_buffer
    )
    if liquidation_buffer is None:
        missing_inputs.append("liquidation_buffer_bps")

    status = (
        "COMPLETE_RARE_EVENT_STRESS_SUITE"
        if len(scenarios) == len(RARE_EVENT_STRESS_SCENARIOS)
        and len(components) == len(RARE_EVENT_BUFFER_COMPONENT_FIELDS)
        else "PARTIAL_RARE_EVENT_STRESS_SUITE"
    )
    return {
        "status": status,
        "scenarios": scenarios,
        "components": components,
        "scenario_sources": scenario_sources,
        "component_sources": component_sources,
        "missing_inputs": sorted(set(missing_inputs)),
        "modeled_999_adverse_move_bps": modeled_adverse,
        "required_liquidation_buffer_bps": round(required_buffer, 8) if required_buffer is not None else None,
        "liquidation_buffer_bps": liquidation_buffer,
        "liquidation_buffer_covers_required": buffer_passed,
    }


def _ensure_paper_rare_event_stress_fields(row: dict[str, Any]) -> None:
    existing = row.get("pre_entry_stress_tests")
    if isinstance(existing, dict) and row.get("rare_event_stress_status") not in (None, ""):
        return
    stress = _derive_paper_rare_event_stress_suite(row)
    row["pre_entry_stress_tests"] = {
        **stress["scenarios"],
        **stress["components"],
        "status": stress["status"],
        "missing_inputs": stress["missing_inputs"],
        "modeled_999_adverse_move_bps": stress["modeled_999_adverse_move_bps"],
        "required_liquidation_buffer_bps": stress["required_liquidation_buffer_bps"],
        "liquidation_buffer_bps": stress["liquidation_buffer_bps"],
        "liquidation_buffer_covers_required": stress["liquidation_buffer_covers_required"],
        "scenario_sources": stress["scenario_sources"],
        "component_sources": stress["component_sources"],
    }
    row["rare_event_stress_suite"] = row["pre_entry_stress_tests"]
    row["rare_event_stress_status"] = stress["status"]
    row["rare_event_stress_missing_inputs"] = stress["missing_inputs"]
    if stress["required_liquidation_buffer_bps"] is not None:
        row["rare_event_required_liquidation_buffer_bps"] = stress["required_liquidation_buffer_bps"]
    if stress["modeled_999_adverse_move_bps"] is not None:
        row["modeled_999_adverse_move_bps"] = stress["modeled_999_adverse_move_bps"]
    for field in RARE_EVENT_BUFFER_COMPONENT_FIELDS:
        value = stress["components"].get(field)
        if value is not None:
            row[field] = value
    _record_paper_accounting_normalization(
        row,
        target_field="pre_entry_stress_tests",
        source_field="decision_time_candidate_market_risk_context",
        normalization="paper_zero_liquidation_rare_event_stress_suite",
    )


def _ensure_paper_hedge_contract_fields(row: dict[str, Any]) -> None:
    hedge_budget = _coerce_float(row.get("hedge_budget_usd"))
    if hedge_budget is None or hedge_budget <= 0.0:
        return
    model_inputs = row.get("model_inputs") if isinstance(row.get("model_inputs"), dict) else {}
    risk_budget = _coerce_float(_first_present(row.get("risk_budget_usd"), model_inputs.get("risk_budget_usd")))
    selected_ratio = _coerce_float(_first_present(
        row.get("hedge_ratio"),
        model_inputs.get("hedge_ratio"),
        model_inputs.get("selected_hedge_budget_pct_of_risk"),
    ))
    if selected_ratio is None and risk_budget is not None and risk_budget > 0.0:
        selected_ratio = hedge_budget / risk_budget
    if selected_ratio is not None and selected_ratio > 0.0:
        selected_ratio = max(0.0, min(float(selected_ratio), 1.0))
    hedge_cost = _paper_hedge_cost_usd(row, selected_ratio)

    expected_shortfall_before = _coerce_float(_first_present(
        row.get("expected_shortfall_before"),
        row.get("expected_shortfall_usd"),
        row.get("pre_paper_tier_block_expected_shortfall_usd"),
        model_inputs.get("expected_shortfall_usd"),
        risk_budget,
    ))
    reduction = None
    if expected_shortfall_before is not None and expected_shortfall_before > 0.0:
        reduction = _coerce_float(row.get("hedge_expected_shortfall_reduction_usd"))
        if reduction is None or reduction <= 0.0:
            reduction = min(hedge_budget, expected_shortfall_before)
        if reduction <= hedge_cost:
            _block_paper_hedge_admission(
                row,
                reason="paper_bounded_hedge_expected_shortfall_reduction_not_greater_than_costs",
                hedge_budget=hedge_budget,
                hedge_cost=hedge_cost,
                shortfall_reduction=reduction,
                expected_shortfall_before=expected_shortfall_before,
            )
            return

    parent_id = _first_present(
        row.get("hedge_parent_id"),
        row.get("source_intent_id"),
        row.get("intent_id"),
        row.get("allocation_id"),
        row.get("prediction_id"),
        row.get("signal_id"),
    )
    if parent_id not in (None, ""):
        _set_paper_accounting_field_if_missing(
            row,
            "hedge_parent_id",
            str(parent_id),
            source_field="allocation_or_prediction_id",
            normalization="paper_bounded_hedge_parent_id",
        )
        _set_paper_accounting_field_if_missing(
            row,
            "hedge_child_id",
            f"{parent_id}:paper_hedge",
            source_field="hedge_parent_id",
            normalization="paper_bounded_hedge_child_id",
        )
    _set_paper_accounting_field_if_missing(
        row,
        "hedge_intent",
        "expected_shortfall_reduction",
        source_field="hedge_budget_usd",
        normalization="paper_bounded_hedge_intent",
    )
    if selected_ratio is not None and selected_ratio > 0.0:
        _set_paper_accounting_field_if_missing(
            row,
            "hedge_ratio",
            round(selected_ratio, 8),
            source_field="selected_hedge_budget_pct_of_risk_or_budget_over_risk",
            normalization="paper_bounded_hedge_ratio",
        )

    if expected_shortfall_before is not None and expected_shortfall_before > 0.0:
        _set_paper_accounting_field_if_missing(
            row,
            "expected_shortfall_before",
            round(expected_shortfall_before, 8),
            source_field="expected_shortfall_usd",
            normalization="paper_bounded_hedge_expected_shortfall_before",
        )
        _set_paper_accounting_field_if_missing(
            row,
            "hedge_expected_shortfall_reduction_usd",
            round(reduction, 8),
            source_field="hedge_budget_usd",
            normalization="paper_bounded_hedge_shortfall_reduction",
        )
        _set_paper_accounting_field_if_missing(
            row,
            "expected_shortfall_after",
            round(max(0.0, expected_shortfall_before - reduction), 8),
            source_field="expected_shortfall_before:hedge_expected_shortfall_reduction_usd",
            normalization="paper_bounded_hedge_expected_shortfall_after",
        )

    duration = _coerce_float(_first_present(
        row.get("maximum_duration"),
        row.get("maximum_duration_seconds"),
        row.get("hedge_maximum_duration_seconds"),
    ))
    if duration is None or duration <= 0.0:
        duration = _paper_timeframe_seconds(row.get("timeframe"))
    _set_paper_accounting_field_if_missing(
        row,
        "maximum_duration",
        int(duration),
        source_field="timeframe",
        normalization="paper_bounded_hedge_maximum_duration",
    )
    _set_paper_accounting_field_if_missing(
        row,
        "unwind_plan",
        "close_with_parent_or_timeout",
        source_field="maximum_duration",
        normalization="paper_bounded_hedge_unwind_plan",
    )
    _set_paper_accounting_field_if_missing(
        row,
        "hedge_cost_usd",
        hedge_cost,
        source_field="expected_costs_scaled_by_hedge_ratio",
        normalization="paper_bounded_hedge_cost",
    )


def _normalize_paper_candidate_accounting_publication(row: dict[str, Any]) -> None:
    model_inputs = row.get("model_inputs") if isinstance(row.get("model_inputs"), dict) else {}
    _ensure_paper_rare_event_stress_fields(row)
    for source_field, value in (
        ("depth_price_impact_bps", row.get("depth_price_impact_bps")),
        ("model_inputs.depth_price_impact_bps", model_inputs.get("depth_price_impact_bps")),
    ):
        if _set_paper_accounting_field_if_missing(
            row,
            "depth_impact_bps",
            value,
            source_field=source_field,
            normalization="paper_depth_price_impact_alias",
        ):
            break

    for source_field, value in (
        ("take_profit_reference", row.get("take_profit_reference")),
        ("price_target_after_cost", row.get("price_target_after_cost")),
        ("price_target", row.get("price_target")),
        ("price_target_high", row.get("price_target_high")),
        ("price_target_low", row.get("price_target_low")),
    ):
        if _set_paper_accounting_field_if_missing(
            row,
            "take_profit_price",
            value,
            source_field=source_field,
            normalization="paper_decision_time_take_profit_price_alias",
        ):
            break
    derived_take_profit_price, derived_source = _paper_take_profit_price_from_expected_move(row)
    if derived_source is not None:
        _set_paper_accounting_field_if_missing(
            row,
            "take_profit_price",
            derived_take_profit_price,
            source_field=derived_source,
            normalization="paper_expected_move_take_profit_price",
        )

    if row.get("take_profit_structure") in (None, "") and row.get("take_profit_price") not in (None, ""):
        source = (
            "take_profit_price"
            if derived_source is None
            else f"take_profit_price:{derived_source}"
        )
        _set_paper_accounting_field_if_missing(
            row,
            "take_profit_structure",
            "decision_time_expected_move_or_price_target",
            source_field=source,
            normalization="paper_take_profit_structure_from_decision_time_target",
        )

    hedge_budget = _coerce_float(row.get("hedge_budget_usd"))
    if hedge_budget is not None:
        _set_paper_accounting_field_if_missing(
            row,
            "hedge_enabled",
            hedge_budget > 0.0,
            source_field="hedge_budget_usd",
            normalization="paper_hedge_enabled_from_reserved_budget",
        )
    _ensure_paper_hedge_contract_fields(row)


def _current_cycle_candidate_allocation_rows(
    *,
    intents: list[dict[str, Any]],
    historical_accepted_rows: list[dict[str, Any]] | None = None,
    lifecycle_blocked_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    _ = historical_accepted_rows, lifecycle_blocked_rows
    rows: list[dict[str, Any]] = []
    for intent in intents:
        allocation = intent.get("adaptive_allocation")
        if not isinstance(allocation, dict):
            continue
        published = dict(allocation)
        for field in CANDIDATE_ALLOCATION_PUBLICATION_INTENT_FIELDS:
            if field not in intent:
                continue
            value = intent.get(field)
            if value is not None:
                published[field] = value
            elif field not in published:
                published[field] = None
        rows.append(published)
    return rows


def _paper_adaptive_sizing_runtime_status(
    allocation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    published_rows = [
        _paper_candidate_allocation_publication_row(row)
        for row in allocation_rows
        if isinstance(row, dict)
    ]
    accepted_count = sum(
        1
        for row in published_rows
        if row.get("allocator_decision") in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    )
    blocked_count = sum(
        1
        for row in published_rows
        if str(row.get("allocator_decision") or "").startswith("BLOCK_")
    )
    a_grade_rows = [
        row
        for row in published_rows
        if str(
            _first_present(row.get("source_tier"), row.get("paper_opportunity_tier"))
            or ""
        ).strip().upper()
        == PAPER_TIER_A_GRADE_EXECUTION
    ]
    allocator_pass_not_a_grade_rows = [
        row
        for row in published_rows
        if row.get("allocator_decision") in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
        and str(
            _first_present(row.get("source_tier"), row.get("paper_opportunity_tier"))
            or ""
        ).strip().upper()
        != PAPER_TIER_A_GRADE_EXECUTION
    ]
    guardian_status_counts = _count_values(published_rows, "guardian_status")
    guardian_status = None
    non_missing_guardian_statuses = [
        status for status in guardian_status_counts if status != "missing"
    ]
    if len(non_missing_guardian_statuses) == 1:
        guardian_status = non_missing_guardian_statuses[0]
    guardian_allowed_values = {
        row.get("guardian_new_entries_allowed")
        for row in published_rows
        if row.get("guardian_new_entries_allowed") is not None
    }
    guardian_new_entries_allowed = (
        next(iter(guardian_allowed_values))
        if len(guardian_allowed_values) == 1
        else None
    )
    source_tier_counts = _count_values(published_rows, "source_tier")
    source_tier_a_grade_execution_rows = source_tier_counts.get(
        PAPER_TIER_A_GRADE_EXECUTION,
        0,
    )
    runtime_status_api_blockers: list[str] = []
    if not a_grade_rows:
        runtime_status_api_blockers.append("A_GRADE_SUPPLY_ZERO")
    if source_tier_a_grade_execution_rows <= 0:
        runtime_status_api_blockers.append("SOURCE_TIER_A_GRADE_EXECUTION_ZERO")
    if guardian_new_entries_allowed is False:
        runtime_status_api_blockers.append("GUARDIAN_NEW_ENTRIES_DISABLED")
    return {
        "allocator": "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR",
        "fixed_runtime_notional_removed": True,
        "paper_candidates_with_allocation": len(published_rows),
        "candidate_allocation_count": len(published_rows),
        "candidate_allocations": published_rows,
        "candidate_allocations_complete": True,
        "candidate_allocations_source": (
            "paper_loop_allocation_rows_before_sample_truncation"
        ),
        "candidate_allocations_selected_before_outcome": True,
        "candidate_allocations_future_labels_used_as_features": False,
        "allocator_decision_counts": _count_values(published_rows, "allocator_decision"),
        "accepted_allocation_count": accepted_count,
        "allocator_pass_rows": accepted_count,
        "blocked_allocation_count": blocked_count,
        "a_grade_rows": len(a_grade_rows),
        "A_grade_rows": len(a_grade_rows),
        "near_a_grade_rows": len(allocator_pass_not_a_grade_rows),
        "near_A_grade_rows": len(allocator_pass_not_a_grade_rows),
        "source_tier_counts": source_tier_counts,
        "source_tier_a_grade_execution_rows": source_tier_a_grade_execution_rows,
        "guardian_status": guardian_status,
        "guardian_status_counts": guardian_status_counts,
        "guardian_new_entries_allowed": guardian_new_entries_allowed,
        "runtime_status_api_blockers": runtime_status_api_blockers,
        "source_tier_or_guardian_blocked_allocator_pass_rows": len(
            allocator_pass_not_a_grade_rows
        ),
        "unclassified_allocation_publication_block_count": sum(
            1
            for row in published_rows
            if row.get("paper_opportunity_tier_reason")
            == "MISSING_OR_INVALID_EXPLICIT_PAPER_OPPORTUNITY_TIER"
        ),
        "non_executable_tier_publication_block_count": sum(
            1
            for row in published_rows
            if row.get("non_executable_paper_tier_blocked") is True
        ),
        "rare_event_stress_complete_candidate_count": sum(
            1
            for row in published_rows
            if row.get("rare_event_stress_status") == "COMPLETE_RARE_EVENT_STRESS_SUITE"
        ),
        "rare_event_stress_partial_candidate_count": sum(
            1
            for row in published_rows
            if row.get("rare_event_stress_status") == "PARTIAL_RARE_EVENT_STRESS_SUITE"
        ),
        "sample_allocations": published_rows[:25],
        "generated_utc": _utc_iso(),
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
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


def _count_first_present_values(
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = _first_present(*(row.get(field) for field in fields))
        label = str(value or "missing")
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


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


def _read_continuous_edge_guardian_gate(r) -> dict[str, Any]:
    payload = None
    if r is not None:
        try:
            payload = r.get(CONTINUOUS_EDGE_GUARDIAN_GATE_REDIS_KEY)
        except Exception:
            payload = None
    if payload:
        try:
            decoded = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            decoded = None
        if isinstance(decoded, dict):
            return decoded
    try:
        decoded = json.loads(CONTINUOUS_EDGE_GUARDIAN_GATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _continuous_edge_guardian_gate_context(gate: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(gate, dict) or not gate:
        return {}
    context: dict[str, Any] = {}
    if gate.get("status") not in (None, ""):
        context["continuous_edge_guardian_status"] = gate.get("status")
    if gate.get("a_grade_new_entries_allowed") is not None:
        context["continuous_edge_guardian_new_entries_allowed"] = gate.get(
            "a_grade_new_entries_allowed"
        )
    if gate.get("failure_reasons") not in (None, ""):
        context["continuous_edge_guardian_block_reasons"] = gate.get("failure_reasons")
    if gate.get("allowed_runtime_actions") not in (None, ""):
        context["continuous_edge_guardian_allowed_runtime_actions"] = gate.get(
            "allowed_runtime_actions"
        )
    return context


def _apply_continuous_edge_guardian_gate(
    classification: dict[str, Any],
    gate: dict[str, Any] | None,
) -> dict[str, Any]:
    if classification.get("paper_opportunity_tier") != PAPER_TIER_A_GRADE_EXECUTION:
        return classification
    if not isinstance(gate, dict) or not gate:
        return classification
    if gate.get("a_grade_new_entries_allowed") is not False:
        return classification
    blocked = dict(classification)
    blocked["pre_guardian_paper_opportunity_tier"] = PAPER_TIER_A_GRADE_EXECUTION
    blocked["pre_guardian_paper_opportunity_tier_reason"] = classification.get(
        "paper_opportunity_tier_reason"
    )
    blocked["pre_guardian_paper_fill_allowed_source"] = classification.get(
        "paper_fill_allowed_source"
    )
    blocked["continuous_edge_guardian_forced_shadow_only"] = True
    blocked["counts_as_a_grade_evidence"] = False
    blocked["paper_opportunity_tier"] = PAPER_TIER_SHADOW_ONLY
    blocked["paper_opportunity_tier_reason"] = "CONTINUOUS_EDGE_GUARDIAN_A_GRADE_HALTED"
    blocked["paper_fill_allowed_source"] = "CONTINUOUS_EDGE_GUARDIAN_BLOCKED_NEW_A_GRADE_ENTRIES"
    blocked["continuous_edge_guardian_status"] = gate.get("status")
    blocked["continuous_edge_guardian_new_entries_allowed"] = gate.get(
        "a_grade_new_entries_allowed"
    )
    blocked["continuous_edge_guardian_block_reasons"] = gate.get("failure_reasons") or []
    blocked["continuous_edge_guardian_allowed_runtime_actions"] = (
        gate.get("allowed_runtime_actions") or ["reduce", "close"]
    )
    blocked["paper_only"] = True
    blocked["places_real_order"] = False
    return blocked


def _paper_capital_class_for_tier(tier: Any) -> str | None:
    normalized = str(tier or "").strip().upper()
    if normalized == PAPER_TIER_A_GRADE_EXECUTION:
        return "A_GRADE_EXECUTION_FULL_BUDGET"
    if normalized == PAPER_TIER_B_GRADE_EXPLORATION:
        return "B_GRADE_EXPLORATION_FRACTIONAL_BUDGET"
    if normalized == PAPER_TIER_SHADOW_ONLY:
        return "SHADOW_ONLY_ZERO_SIZE"
    if normalized == PAPER_TIER_NO_TRADE:
        return "NO_TRADE_ZERO_SIZE"
    return None


def _paper_source_tier_guardian_context(classification: dict[str, Any]) -> dict[str, Any]:
    tier = str(classification.get("paper_opportunity_tier") or "").strip().upper()
    context: dict[str, Any] = {}
    if tier in PAPER_OPPORTUNITY_TIERS:
        context["source_tier"] = tier
        context["policy_tier"] = tier
        capital_class = _paper_capital_class_for_tier(tier)
        if capital_class is not None:
            context["capital_class"] = capital_class

    pre_guardian_tier = str(
        classification.get("pre_guardian_paper_opportunity_tier") or ""
    ).strip().upper()
    if pre_guardian_tier in PAPER_OPPORTUNITY_TIERS:
        context["pre_guardian_source_tier"] = pre_guardian_tier
        context["pre_guardian_policy_tier"] = pre_guardian_tier

    guardian_status = classification.get("continuous_edge_guardian_status")
    if guardian_status not in (None, ""):
        context["guardian_status"] = guardian_status
    guardian_new_entries_allowed = classification.get(
        "continuous_edge_guardian_new_entries_allowed"
    )
    if guardian_new_entries_allowed is not None:
        context["guardian_new_entries_allowed"] = guardian_new_entries_allowed
    guardian_block_reasons = classification.get("continuous_edge_guardian_block_reasons")
    if guardian_block_reasons not in (None, ""):
        context["guardian_block_reasons"] = guardian_block_reasons
    guardian_allowed_actions = classification.get(
        "continuous_edge_guardian_allowed_runtime_actions"
    )
    if guardian_allowed_actions not in (None, ""):
        context["guardian_allowed_runtime_actions"] = guardian_allowed_actions
    return context


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


def _b_grade_exploration_adaptive_confidence_floor(
    *,
    drawdown_bps: Any,
    expected_move_after_cost_bps: Any = None,
    observed_spread_bps: Any = None,
    expected_slippage_bps: Any = None,
    fee_bps: Any = None,
    depth_utilization_pct: Any = None,
    long_short_ratio_status: Any = None,
) -> dict[str, Any]:
    static_floor = B_GRADE_EXPLORATION_MIN_CONFIDENCE
    max_floor = min(
        B_GRADE_EXPLORATION_ADAPTIVE_CONFIDENCE_FLOOR_MAX,
        PAPER_STRICT_A_CONFIDENCE_THRESHOLD - 0.01,
    )
    drawdown = max(0.0, _coerce_float(drawdown_bps) or 0.0)
    drawdown_pressure = _clamp_float(
        drawdown / B_GRADE_EXPLORATION_DRAWDOWN_STOP_BPS,
        0.0,
        1.0,
    )
    penalties: dict[str, float] = {
        "drawdown_pressure": round(0.10 * drawdown_pressure, 8),
        "cost_edge_pressure": 0.0,
        "depth_pressure": 0.0,
        "long_short_point_in_time_pressure": 0.0,
    }

    edge_abs = _coerce_float(expected_move_after_cost_bps)
    if edge_abs is not None:
        edge_abs = abs(edge_abs)
    cost_components = [
        max(0.0, value)
        for value in (
            _coerce_float(observed_spread_bps),
            _coerce_float(expected_slippage_bps),
            _coerce_float(fee_bps),
        )
        if value is not None
    ]
    cost_drag_bps = sum(cost_components) if cost_components else None
    edge_to_cost_ratio = None
    if cost_drag_bps is not None and cost_drag_bps > 0.0:
        if edge_abs is None or edge_abs <= 0.0:
            penalties["cost_edge_pressure"] = 0.08
        else:
            edge_to_cost_ratio = edge_abs / cost_drag_bps
            penalties["cost_edge_pressure"] = round(
                0.08 * _clamp_float((3.0 - edge_to_cost_ratio) / 3.0, 0.0, 1.0),
                8,
            )

    depth_utilization = _coerce_float(depth_utilization_pct)
    if depth_utilization is not None:
        if depth_utilization <= 1.0:
            depth_utilization *= 100.0
        penalties["depth_pressure"] = round(
            0.06 * _clamp_float(depth_utilization / 100.0, 0.0, 1.0),
            8,
        )

    long_short_status = str(long_short_ratio_status or "").strip().upper()
    if long_short_status.startswith("REJECTED_LONG_SHORT"):
        penalties["long_short_point_in_time_pressure"] = 0.04
    elif long_short_status in {"MISSING_V2_LONG_SHORT_RATIO", "REJECTED_LONG_SHORT_AVAILABLE_AT_UNPROVEN"}:
        penalties["long_short_point_in_time_pressure"] = 0.02

    raw_floor = static_floor + sum(penalties.values())
    adaptive_floor = _clamp_float(raw_floor, static_floor, max_floor)
    return {
        "b_grade_exploration_static_confidence_floor": static_floor,
        "b_grade_exploration_adaptive_confidence_floor": round(adaptive_floor, 8),
        "b_grade_exploration_adaptive_confidence_floor_max": max_floor,
        "b_grade_exploration_floor_never_below_static": adaptive_floor >= static_floor,
        "b_grade_exploration_floor_mode": (
            "ADAPTIVE_FAIL_CLOSED_CONTEXTUAL_FLOOR_NEVER_BELOW_STATIC"
        ),
        "b_grade_exploration_floor_penalties": penalties,
        "b_grade_exploration_floor_context": {
            "drawdown_bps": round(drawdown, 8),
            "drawdown_pressure": round(drawdown_pressure, 8),
            "expected_move_after_cost_bps_abs": (
                round(edge_abs, 8) if edge_abs is not None else None
            ),
            "observed_cost_drag_bps": (
                round(cost_drag_bps, 8) if cost_drag_bps is not None else None
            ),
            "edge_to_cost_ratio": (
                round(edge_to_cost_ratio, 8) if edge_to_cost_ratio is not None else None
            ),
            "depth_utilization_pct": (
                round(depth_utilization, 8) if depth_utilization is not None else None
            ),
            "long_short_ratio_status": long_short_status or None,
        },
    }


def _b_grade_exploration_budget_fraction(
    *,
    confidence_calibrated: Any,
    drawdown_bps: Any,
    expected_move_after_cost_bps: Any = None,
    observed_spread_bps: Any = None,
    expected_slippage_bps: Any = None,
    fee_bps: Any = None,
    depth_utilization_pct: Any = None,
    long_short_ratio_status: Any = None,
) -> dict[str, Any]:
    confidence = _coerce_float(confidence_calibrated)
    floor = _b_grade_exploration_adaptive_confidence_floor(
        drawdown_bps=drawdown_bps,
        expected_move_after_cost_bps=expected_move_after_cost_bps,
        observed_spread_bps=observed_spread_bps,
        expected_slippage_bps=expected_slippage_bps,
        fee_bps=fee_bps,
        depth_utilization_pct=depth_utilization_pct,
        long_short_ratio_status=long_short_ratio_status,
    )
    adaptive_floor = float(floor["b_grade_exploration_adaptive_confidence_floor"])
    drawdown = _coerce_float(drawdown_bps) or 0.0
    if confidence is None or confidence < adaptive_floor:
        return {
            **floor,
            "risk_budget_fraction_of_normal_adaptive": 0.0,
            "b_grade_exploration_uncertainty_factor": 0.0,
            "b_grade_exploration_drawdown_factor": 0.0,
            "b_grade_exploration_confidence_floor_pass": False,
            "b_grade_exploration_budget_formula": (
                "confidence_below_adaptive_b_grade_exploration_floor"
            ),
        }
    confidence_span = max(
        1e-9,
        PAPER_STRICT_A_CONFIDENCE_THRESHOLD - adaptive_floor,
    )
    confidence_progress = _clamp_float(
        (confidence - adaptive_floor) / confidence_span,
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
        **floor,
        "risk_budget_fraction_of_normal_adaptive": round(max(0.0, fraction), 8),
        "b_grade_exploration_uncertainty_factor": round(uncertainty_factor, 8),
        "b_grade_exploration_drawdown_factor": round(drawdown_factor, 8),
        "b_grade_exploration_confidence_floor_pass": True,
        "b_grade_exploration_budget_formula": (
            "max_fraction_of_normal_adaptive"
            "*confidence_uncertainty_factor*drawdown_guard_factor"
        ),
    }


def _allocation_allows_economic_paper_fill(allocation: dict[str, Any]) -> bool:
    return allocation.get("allocator_decision") in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}


def _is_paper_size_adjusted_entry_context(
    *,
    signal: dict[str, Any],
    intent: dict[str, Any],
) -> bool:
    size_adjustment_mode = str(
        _first_present(
            intent.get("strategy_size_adjustment_mode"),
            signal.get("strategy_size_adjustment_mode"),
        )
        or ""
    ).strip().lower()
    if size_adjustment_mode != "reduce_size_mode":
        return False
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
    if side not in {"long", "short"}:
        return False
    entry_mode = str(
        _first_present(
            intent.get("strategy_selected_mode"),
            signal.get("strategy_selected_mode"),
            intent.get("strategy_id"),
            signal.get("strategy_id"),
            intent.get("strategy_family"),
            signal.get("strategy_family"),
            intent.get("strategy_subtype"),
            signal.get("strategy_subtype"),
        )
        or ""
    ).strip().lower()
    if not entry_mode or entry_mode in {"no_trade", "no_trade_mode", "no_trade_expert"}:
        return False
    return not any(token in entry_mode for token in ("reduce", "close", "exit"))


def _paper_lifecycle_or_no_trade_strategy_reasons(
    *,
    signal: dict[str, Any],
    intent: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    size_adjusted_entry_context = _is_paper_size_adjusted_entry_context(
        signal=signal,
        intent=intent,
    )
    mode_fields = (
        "strategy_selected_mode",
        "strategy_router_selected_mode",
        "strategy_id",
        "strategy_family",
        "strategy_subtype",
        "entry_reason",
    )
    for field in mode_fields:
        for source_name, source in (("intent", intent), ("signal", signal)):
            raw = source.get(field)
            normalized = str(raw or "").strip().lower()
            if normalized in {"no_trade", "no_trade_mode", "no_trade_expert"}:
                reasons.append(f"{source_name}.{field}=NO_TRADE")
            elif any(token in normalized for token in ("reduce", "close", "exit")):
                if (
                    size_adjusted_entry_context
                    and field in {"strategy_router_selected_mode", "entry_reason"}
                    and normalized == "reduce_size_mode"
                ):
                    continue
                reasons.append(f"{source_name}.{field}=LIFECYCLE_ACTION")

    label_values: list[Any] = []
    for field in (
        "strategy_regime_labels",
        "market_regime_at_entry",
        "market_regime",
        "market_regime_at_exit",
    ):
        for source in (intent, signal):
            raw = source.get(field)
            if isinstance(raw, str):
                label_values.extend(item.strip() for item in raw.split(",") if item.strip())
            elif isinstance(raw, (list, tuple, set)):
                label_values.extend(raw)
    tokens = {str(value).strip().upper() for value in label_values if str(value).strip()}
    if "NO_TRADE" in tokens:
        reasons.append("strategy_regime_labels_include_NO_TRADE")
    return sorted(set(reasons))


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
    continuous_edge_guardian_gate: dict[str, Any] | None = None,
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
        **_continuous_edge_guardian_gate_context(continuous_edge_guardian_gate),
    }
    b_grade_learning_contract = {
        "counts_as_a_grade_evidence": False,
        "a_grade_promotion_allowed": False,
        "live_ready_implication": False,
    }
    priority_label_collection_fields = {
        field: intent[field]
        for field in PAPER_ONLY_LABEL_COLLECTION_PRIORITY_FIELDS
        if field in intent
    }
    lifecycle_or_no_trade_strategy_reasons = (
        _paper_lifecycle_or_no_trade_strategy_reasons(signal=signal, intent=intent)
    )
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
    if lifecycle_or_no_trade_strategy_reasons:
        return {
            **base,
            "paper_opportunity_tier": PAPER_TIER_NO_TRADE,
            "paper_opportunity_tier_reason": (
                "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE"
            ),
            "lifecycle_or_no_trade_strategy_reasons": lifecycle_or_no_trade_strategy_reasons,
            "no_trade_strategy_reasons": lifecycle_or_no_trade_strategy_reasons,
        }
    if paper_fill_allowed_upstream and local_trade_gates_pass:
        return _apply_continuous_edge_guardian_gate({
            **base,
            "paper_opportunity_tier": PAPER_TIER_A_GRADE_EXECUTION,
            "paper_opportunity_tier_reason": "STRICT_UPSTREAM_PAPER_FILL_GATE_ALLOWED",
            "paper_fill_allowed_source": "STRICT_UPSTREAM_PAPER_FILL_GATE",
        }, continuous_edge_guardian_gate)
    if explicit_tier == PAPER_TIER_A_GRADE_EXECUTION and local_trade_gates_pass:
        return _apply_continuous_edge_guardian_gate({
            **base,
            "paper_opportunity_tier": PAPER_TIER_A_GRADE_EXECUTION,
            "paper_opportunity_tier_reason": "DYNAMIC_A_GRADE_SIGNAL_TAG_ALLOWED_PAPER_ONLY",
            "paper_fill_allowed_source": "DYNAMIC_A_GRADE_PAPER_TAG",
        }, continuous_edge_guardian_gate)
    b_grade_source = None
    if (
        intent.get("paper_only_label_collection_priority") is True
        and exploration_trade_gates_allowed
    ):
        b_grade_source = "PAPER_ONLY_PRIORITY_BUCKET_LABEL_COLLECTION"
    elif explicit_tier == PAPER_TIER_B_GRADE_EXPLORATION:
        b_grade_source = "EXPLICIT_B_GRADE_PAPER_TAG"
    elif _is_paper_confidence_trial_row(signal):
        b_grade_source = "PAPER_CONFIDENCE_THRESHOLD_TRIAL"
    elif exploration_trade_gates_allowed:
        b_grade_source = "DYNAMIC_POSITIVE_EDGE_BELOW_A_GRADE_EXPLORATION"
    if b_grade_source:
        budget = _b_grade_exploration_budget_fraction(
            confidence_calibrated=confidence,
            drawdown_bps=portfolio_drawdown_bps,
            expected_move_after_cost_bps=expected_edge,
            observed_spread_bps=_first_present(
                intent.get("actual_observed_spread_entry_bps"),
                intent.get("observed_spread_bps"),
                intent.get("bid_ask_spread_bps"),
            ),
            expected_slippage_bps=intent.get("expected_slippage_bps"),
            fee_bps=intent.get("fee_bps"),
            depth_utilization_pct=intent.get("depth_utilization_pct"),
            long_short_ratio_status=intent.get("long_short_ratio_status"),
        )
        if budget["risk_budget_fraction_of_normal_adaptive"] > 0.0:
            return {
                **base,
                **b_grade_learning_contract,
                **priority_label_collection_fields,
                **budget,
                "paper_opportunity_tier": PAPER_TIER_B_GRADE_EXPLORATION,
                "paper_opportunity_tier_reason": b_grade_source,
                "paper_fill_allowed_source": "B_GRADE_EXPLORATION_PAPER_LOCAL_GATE",
                "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
            }
        return {
            **base,
            **b_grade_learning_contract,
            **priority_label_collection_fields,
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
    classification = {
        **classification,
        **_paper_source_tier_guardian_context(classification),
    }
    for field in (
        "paper_opportunity_tier",
        "paper_opportunity_tier_reason",
        "paper_fill_allowed_source",
        "strict_paper_fill_allowed_upstream",
        "explicit_paper_opportunity_tier",
        "pre_guardian_paper_opportunity_tier",
        "pre_guardian_paper_opportunity_tier_reason",
        "pre_guardian_paper_fill_allowed_source",
        "continuous_edge_guardian_forced_shadow_only",
        "counts_as_a_grade_evidence",
        "a_grade_promotion_allowed",
        "live_ready_implication",
        *PAPER_ONLY_LABEL_COLLECTION_PRIORITY_FIELDS,
        "risk_budget_fraction_of_normal_adaptive",
        "b_grade_exploration_uncertainty_factor",
        "b_grade_exploration_drawdown_factor",
        "b_grade_exploration_static_confidence_floor",
        "b_grade_exploration_adaptive_confidence_floor",
        "b_grade_exploration_adaptive_confidence_floor_max",
        "b_grade_exploration_floor_never_below_static",
        "b_grade_exploration_floor_mode",
        "b_grade_exploration_floor_penalties",
        "b_grade_exploration_floor_context",
        "b_grade_exploration_confidence_floor_pass",
        "b_grade_exploration_budget_formula",
        "calibration_label_purpose",
        "expected_move_side",
        "lifecycle_or_no_trade_strategy_reasons",
        "no_trade_strategy_reasons",
        *PAPER_SOURCE_TIER_GUARDIAN_CONTEXT_FIELDS,
        "continuous_edge_guardian_status",
        "continuous_edge_guardian_block_reasons",
        "continuous_edge_guardian_allowed_runtime_actions",
    ):
        if field in classification:
            intent[field] = classification[field]
            allocation[field] = classification[field]
    model_inputs = allocation.get("model_inputs") if isinstance(allocation.get("model_inputs"), dict) else {}
    if model_inputs is not allocation.get("model_inputs"):
        allocation["model_inputs"] = model_inputs
    for field in (
        "paper_opportunity_tier",
        "pre_guardian_paper_opportunity_tier",
        "continuous_edge_guardian_forced_shadow_only",
        "counts_as_a_grade_evidence",
        "a_grade_promotion_allowed",
        "live_ready_implication",
        *PAPER_ONLY_LABEL_COLLECTION_PRIORITY_FIELDS,
        "risk_budget_fraction_of_normal_adaptive",
        "b_grade_exploration_uncertainty_factor",
        "b_grade_exploration_drawdown_factor",
        "b_grade_exploration_static_confidence_floor",
        "b_grade_exploration_adaptive_confidence_floor",
        "b_grade_exploration_adaptive_confidence_floor_max",
        "b_grade_exploration_floor_never_below_static",
        "b_grade_exploration_floor_mode",
        "b_grade_exploration_floor_penalties",
        "b_grade_exploration_floor_context",
        "b_grade_exploration_confidence_floor_pass",
        "b_grade_exploration_budget_formula",
        *PAPER_SOURCE_TIER_GUARDIAN_CONTEXT_FIELDS,
    ):
        if field in classification:
            model_inputs[field] = classification[field]


def _block_non_executable_paper_tier(
    *,
    intent: dict[str, Any],
    allocation: dict[str, Any],
) -> bool:
    tier = str(intent.get("paper_opportunity_tier") or "").strip().upper()
    if tier not in NON_EXECUTABLE_PAPER_TIERS:
        return False

    original_tier_reason = _first_present(
        intent.get("paper_opportunity_tier_reason"),
        allocation.get("paper_opportunity_tier_reason"),
    )
    block_reason = f"NON_EXECUTABLE_PAPER_TIER:{tier}"
    for target in (allocation, intent):
        target["non_executable_paper_tier_block_reason"] = block_reason
    if original_tier_reason not in {None, ""} and original_tier_reason != block_reason:
        for target in (allocation, intent):
            target.setdefault("pre_non_executable_paper_tier", tier)
            target.setdefault("pre_non_executable_paper_tier_reason", original_tier_reason)

    original_decision = allocation.get("allocator_decision")
    if original_decision not in {None, ""}:
        allocation.setdefault(
            "original_allocator_decision_before_paper_tier_block",
            original_decision,
        )
        intent.setdefault(
            "original_allocator_decision_before_paper_tier_block",
            original_decision,
        )

    for field in (
        "risk_budget_usd",
        "gross_notional_usd",
        "allocated_margin_usd",
        "target_notional_usdt",
        "target_quantity",
        "expected_net_pnl_usd",
        "expected_shortfall_usd",
        "hedge_budget_usd",
    ):
        value = allocation.get(field)
        if value not in {None, ""}:
            allocation.setdefault(f"pre_paper_tier_block_{field}", value)
            intent.setdefault(f"pre_paper_tier_block_{field}", value)
        allocation[field] = 0.0
        if field in intent:
            intent[field] = 0.0

    allocation["allocator_decision"] = "BLOCK_NON_EXECUTABLE_PAPER_TIER"
    allocation["final_size_reason"] = block_reason
    allocation["capital_allocation_reason"] = block_reason
    allocation["non_executable_paper_tier_blocked"] = True
    allocation["paper_only"] = True
    allocation["places_real_order"] = False
    allocation["live_order"] = False
    intent["allocator_decision"] = "BLOCK_NON_EXECUTABLE_PAPER_TIER"
    intent["allocator_reason"] = block_reason
    intent["capital_allocation_reason"] = block_reason
    intent["paper_allocation_block_reason"] = block_reason
    # Preserve earlier high-priority block reasons (P0 gate, strategy mode collapse, etc.).
    intent["paper_fill_block_reason"] = intent.get("paper_fill_block_reason") or block_reason
    intent["paper_sizing_source"] = "NON_EXECUTABLE_PAPER_TIER_BLOCK"
    intent["paper_sizing_complete"] = False
    intent["paper_fill_allowed"] = False
    intent["paper_tier_local_fill_allowed"] = False
    intent["strict_paper_fill_allowed_upstream"] = False
    intent["places_real_order"] = False
    intent["live_order"] = False
    intent["paper_only"] = True
    intent["local_block_reasons"] = sorted(set(
        list(intent.get("local_block_reasons") or []) + [f"paper_tier:{block_reason}"]
    ))
    intent["paper_fill_gate_block_reasons"] = sorted(set(
        list(intent.get("paper_fill_gate_block_reasons") or []) + [block_reason]
    ))
    return True


def _shadow_observation_from_blocked_directional_candidate(
    *,
    intent: dict[str, Any],
    signal: dict[str, Any] | None = None,
    integrity_gate: dict[str, Any] | None = None,
    observation_source: str,
    observation_reason: Any,
) -> dict[str, Any] | None:
    """Build a non-fill shadow observation for a valid blocked candidate.

    This is only for counterfactual no-trade outcome analysis. It must not
    change paper admission, accepted fills, PnL, A-grade evidence, or live
    routing.
    """
    signal = signal if isinstance(signal, dict) else {}
    side = _normalized_directional_side(
        _first_present(
            intent.get("side"),
            intent.get("selected_action"),
            intent.get("action"),
            signal.get("side"),
            signal.get("selected_action"),
            signal.get("action"),
        )
    )
    if side not in {"long", "short"}:
        return None
    if intent.get("paper_only") is not True:
        return None
    if intent.get("places_real_order") is True or intent.get("live_order") is True:
        return None
    if intent.get("entry_price_provenance_present") is not True:
        return None
    entry_price = _coerce_float(intent.get("entry_price"))
    if entry_price is None or entry_price <= 0.0:
        return None
    if integrity_gate is not None and integrity_gate.get("allowed") is not True:
        return None
    if intent.get("valid_for_paper") is False:
        return None
    if intent.get("market_state_reject_reasons"):
        return None
    if intent.get("paper_signal_temporal_rejection_reasons"):
        return None
    if intent.get("paper_pre_fill_market_evidence_rejection_reasons"):
        return None
    if _paper_lifecycle_or_no_trade_strategy_reasons(signal=signal, intent=intent):
        return None

    shadow_intent = dict(intent)
    shadow_intent["decision"] = "SHADOW_OBSERVATION_ONLY"
    shadow_intent["side"] = side
    shadow_intent["shadow_observation_source"] = observation_source
    shadow_intent["shadow_observation_reason"] = str(
        observation_reason or intent.get("paper_fill_block_reason") or "BLOCKED_DIRECTIONAL_CANDIDATE"
    )
    shadow_intent["shadow_observation_selected_before_outcome"] = True
    shadow_intent["shadow_outcome_observation_only"] = True
    shadow_intent["paper_fill_allowed"] = False
    shadow_intent["paper_tier_local_fill_allowed"] = False
    shadow_intent["strict_paper_fill_allowed_upstream"] = False
    shadow_intent["places_real_order"] = False
    shadow_intent["live_order"] = False
    shadow_intent["counted_as_accepted_position"] = False
    shadow_intent["counted_as_fill"] = False
    shadow_intent["counted_as_open_position"] = False
    shadow_intent["affects_pnl_ledger"] = False
    shadow_intent["counts_as_a_grade_evidence"] = False
    shadow_intent["a_grade_promotion_allowed"] = False
    shadow_intent["live_ready_implication"] = False
    shadow_intent["entry_price_provenance_observed"] = True
    shadow_intent["candidate_selected_after_outcome"] = False
    shadow_intent["future_labels_used_as_features"] = False
    return shadow_intent


SHADOW_OBSERVATION_ENTRY_FIELDS = (
    "entry_price",
    "entry_price_source",
    "entry_price_utc",
    "entry_price_source_generated_utc",
    "fill_price",
    "fill_price_source",
    "fill_price_utc",
    "latest_price",
    "latest_price_source",
    "latest_price_utc",
)


def _shadow_observation_history_key(row: dict[str, Any]) -> str:
    stable_id = _first_present(
        row.get("prediction_id"),
        row.get("source_prediction_id"),
        row.get("signal_id"),
        row.get("intent_id"),
        row.get("source_intent_id"),
    )
    symbol = str(row.get("symbol") or "").upper()
    side = str(row.get("side") or row.get("selected_action") or "").lower()
    timeframe = str(row.get("timeframe") or "")
    source = str(row.get("shadow_observation_source") or "")
    reason = str(
        _first_present(
            row.get("shadow_observation_reason"),
            row.get("paper_fill_block_reason"),
            row.get("paper_opportunity_tier_reason"),
        )
        or ""
    )
    if stable_id not in (None, ""):
        return "|".join(("id", str(stable_id), symbol, side, timeframe, source, reason))
    return "|".join(
        (
            "fallback",
            symbol,
            side,
            timeframe,
            source,
            reason,
            str(row.get("entry_price_utc") or row.get("generated_utc") or ""),
        )
    )


def _shadow_observation_entry_time(row: dict[str, Any]) -> datetime | None:
    return _parse_strategy_time(
        _first_present(
            row.get("entry_price_utc"),
            row.get("shadow_observation_first_seen_utc"),
            row.get("generated_utc"),
        )
    )


def _normalize_shadow_observation_history_row(
    row: dict[str, Any],
    *,
    now_utc: str,
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    if row.get("decision") != "SHADOW_OBSERVATION_ONLY":
        return None
    normalized = dict(row)
    normalized["decision"] = "SHADOW_OBSERVATION_ONLY"
    normalized["paper_fill_allowed"] = False
    normalized["paper_tier_local_fill_allowed"] = False
    normalized["strict_paper_fill_allowed_upstream"] = False
    normalized["places_real_order"] = False
    normalized["live_order"] = False
    normalized["counted_as_accepted_position"] = False
    normalized["counted_as_fill"] = False
    normalized["counted_as_open_position"] = False
    normalized["affects_pnl_ledger"] = False
    normalized["counts_as_a_grade_evidence"] = False
    normalized["a_grade_promotion_allowed"] = False
    normalized["live_ready_implication"] = False
    normalized["shadow_observation_history_persisted"] = True
    normalized["shadow_observation_first_seen_utc"] = _first_present(
        normalized.get("shadow_observation_first_seen_utc"),
        normalized.get("entry_price_utc"),
        now_utc,
    )
    normalized["shadow_observation_last_seen_utc"] = _first_present(
        normalized.get("shadow_observation_last_seen_utc"),
        normalized.get("generated_utc"),
        now_utc,
    )
    seen_count = int(_coerce_float(normalized.get("shadow_observation_seen_count")) or 1)
    normalized["shadow_observation_seen_count"] = max(1, seen_count)
    return normalized


def _merge_shadow_observation_history(
    existing_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    *,
    now_utc: str | None = None,
    max_rows: int = SHADOW_OBSERVATION_HISTORY_MAX_ROWS,
) -> list[dict[str, Any]]:
    """Merge current-cycle shadow rows with prior V2 shadow history.

    The current paper loop rebuilds intents every cycle. Without this bounded
    merge, each non-fill shadow entry receives a new timestamp and can never
    mature to the counterfactual outcome horizon.
    """
    now_utc = now_utc or _utc_iso()
    now_dt = _parse_strategy_time(now_utc) or datetime.now(timezone.utc)
    by_key: dict[str, dict[str, Any]] = {}

    for raw in existing_rows:
        row = _normalize_shadow_observation_history_row(raw, now_utc=now_utc)
        if row is None:
            continue
        entry_dt = _shadow_observation_entry_time(row)
        if (
            entry_dt is not None
            and (now_dt - entry_dt).total_seconds() > SHADOW_OBSERVATION_HISTORY_TTL_SECONDS
        ):
            continue
        by_key[_shadow_observation_history_key(row)] = row

    for raw in current_rows:
        row = _normalize_shadow_observation_history_row(raw, now_utc=now_utc)
        if row is None:
            continue
        key = _shadow_observation_history_key(row)
        existing = by_key.get(key)
        if existing is not None:
            merged = dict(row)
            for field in SHADOW_OBSERVATION_ENTRY_FIELDS:
                if existing.get(field) not in (None, ""):
                    merged[field] = existing[field]
            merged["shadow_observation_first_seen_utc"] = _first_present(
                existing.get("shadow_observation_first_seen_utc"),
                existing.get("entry_price_utc"),
                row.get("entry_price_utc"),
                now_utc,
            )
            merged["shadow_observation_seen_count"] = int(
                _coerce_float(existing.get("shadow_observation_seen_count")) or 1
            ) + 1
        else:
            merged = row
        merged["shadow_observation_last_seen_utc"] = now_utc
        merged["shadow_observation_history_persisted"] = True
        by_key[key] = merged

    rows = list(by_key.values())
    rows.sort(
        key=lambda row: (
            _shadow_observation_entry_time(row) or datetime.min.replace(tzinfo=timezone.utc),
            _shadow_observation_history_key(row),
        )
    )
    if max_rows > 0 and len(rows) > max_rows:
        rows = rows[-max_rows:]
    return rows


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
    current_accepted_rows: list[dict[str, Any]] | None = None,
    blocked_rows: list[dict[str, Any]],
    shadow_rows: list[dict[str, Any]],
    held_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    persistent_accepted_rows = accepted_rows
    current_accepted_rows = current_accepted_rows if current_accepted_rows is not None else accepted_rows
    rows = current_accepted_rows + blocked_rows + shadow_rows + held_rows
    b_grade_accepted = [
        row
        for row in current_accepted_rows
        if row.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
    ]
    persistent_b_grade_accepted = [
        row
        for row in persistent_accepted_rows
        if row.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
    ]
    priority_rows = [
        row for row in rows if row.get("paper_only_label_collection_priority") is True
    ]
    priority_b_grade_accepted = [
        row
        for row in b_grade_accepted
        if row.get("paper_only_label_collection_priority") is True
    ]
    persistent_priority_b_grade_accepted = [
        row
        for row in persistent_b_grade_accepted
        if row.get("paper_only_label_collection_priority") is True
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
        "accepted_tier_counts": _count_paper_opportunity_tiers(current_accepted_rows),
        "accepted_tier_counts_scope": "current_cycle_accepted_fills_only",
        "persistent_accepted_fill_count": len(persistent_accepted_rows),
        "persistent_accepted_tier_counts": _count_paper_opportunity_tiers(persistent_accepted_rows),
        "blocked_tier_counts": _count_paper_opportunity_tiers(blocked_rows),
        "blocked_final_reason_counts": _count_first_present_values(
            blocked_rows,
            (
                "non_executable_paper_tier_block_reason",
                "paper_fill_block_reason",
                "paper_allocation_block_reason",
                "allocator_reason",
                "paper_opportunity_tier_reason",
            ),
        ),
        "blocked_upstream_tier_reason_counts": _count_first_present_values(
            blocked_rows,
            (
                "pre_non_executable_paper_tier_reason",
                "original_paper_opportunity_tier_reason_before_publication_block",
            ),
        ),
        "blocked_local_block_reason_counts": _count_list_values(blocked_rows, "local_block_reasons"),
        "blocked_fill_gate_reason_counts": _count_list_values(blocked_rows, "paper_fill_gate_block_reasons"),
        "blocked_runtime_market_evidence_rejection_counts": _count_list_values(
            blocked_rows,
            "paper_runtime_market_evidence_rejection_reasons",
        ),
        "blocked_pre_fill_market_evidence_rejection_counts": _count_list_values(
            blocked_rows,
            "paper_pre_fill_market_evidence_rejection_reasons",
        ),
        "blocked_post_fill_market_evidence_rejection_counts": _count_list_values(
            blocked_rows,
            "paper_post_fill_market_evidence_rejection_reasons",
        ),
        "blocked_lifecycle_or_no_trade_strategy_reason_counts": _count_list_values(
            blocked_rows,
            "lifecycle_or_no_trade_strategy_reasons",
        ),
        "shadow_tier_counts": _count_paper_opportunity_tiers(shadow_rows),
        "held_tier_counts": _count_paper_opportunity_tiers(held_rows),
        "legacy_unclassified_tier_count": _missing_paper_opportunity_tier_count(rows),
        "legacy_accepted_without_tier_count": _missing_paper_opportunity_tier_count(current_accepted_rows),
        "persistent_legacy_accepted_without_tier_count": _missing_paper_opportunity_tier_count(
            persistent_accepted_rows
        ),
        "blocked_without_tier_count": _missing_paper_opportunity_tier_count(blocked_rows),
        "shadow_without_tier_count": _missing_paper_opportunity_tier_count(shadow_rows),
        "held_without_tier_count": _missing_paper_opportunity_tier_count(held_rows),
        "b_grade_exploration_accepted_count": len(b_grade_accepted),
        "b_grade_exploration_accepted_count_scope": "current_cycle_accepted_fills_only",
        "persistent_b_grade_exploration_accepted_count": len(persistent_b_grade_accepted),
        "b_grade_exploration_max_risk_fraction_of_normal_adaptive": (
            B_GRADE_EXPLORATION_MAX_RISK_FRACTION_OF_NORMAL
        ),
        "b_grade_exploration_observed_max_risk_fraction": (
            round(max(fractions), 8) if fractions else 0.0
        ),
        "b_grade_exploration_budget_cap_applied_count": sum(
            1 for row in b_grade_accepted if row.get("b_grade_exploration_budget_cap_applied") is True
        ),
        "paper_only_label_collection_priority_candidate_count": len(priority_rows),
        "paper_only_label_collection_priority_b_grade_accepted_count": (
            len(priority_b_grade_accepted)
        ),
        "persistent_paper_only_label_collection_priority_b_grade_accepted_count": (
            len(persistent_priority_b_grade_accepted)
        ),
        "paper_only_label_collection_priority_reason_counts": _count_first_present_values(
            priority_rows,
            (
                "paper_opportunity_tier_reason",
                "paper_only_label_collection_priority_reason",
            ),
        ),
        "paper_only_label_collection_priority_live_routing_blocked": all(
            row.get("paper_only") is True
            and row.get("places_real_order") is False
            and row.get("counts_as_a_grade_evidence") is False
            for row in priority_rows
        ),
        "b_grade_exploration_live_routing_blocked": all(
            row.get("paper_only") is True and row.get("places_real_order") is False
            for row in b_grade_accepted
        ),
        "calibration_label_purpose": "B_GRADE_EXPLORATION_OUTCOME_LABEL",
        "sample_b_grade_exploration_fills": b_grade_accepted[:25],
        "sample_paper_only_label_collection_priority_fills": (
            priority_b_grade_accepted[:25]
        ),
        "sample_blocked_fills": _compact_rows_for_state(_sample_rows(blocked_rows, 25)),
        "generated_utc": _utc_iso(),
    }


def _paper_canary_score(row: dict[str, Any]) -> float | None:
    return _coerce_float(
        _first_present(
            row.get("confidence_calibrated"),
            row.get("score"),
            row.get("selected_action_probability"),
            row.get("confidence_raw"),
            row.get("strategy_router_confidence"),
        )
    )


def _paper_canary_edge_favorable(row: dict[str, Any]) -> bool:
    side = _normalized_directional_side(
        _first_present(row.get("side"), row.get("selected_action"), row.get("action"))
    )
    edge = _coerce_float(
        _first_present(
            row.get("expected_move_after_cost_bps"),
            row.get("expected_net_edge_bps"),
            row.get("paper_allocation_signed_expected_move_after_cost_bps"),
        )
    )
    if side not in {"long", "short"} or edge is None:
        return False
    return expected_move_after_cost_favorable_for_side(
        side=side,
        expected_move_after_cost_bps=edge,
    )


def _paper_canary_liquidity_pass(row: dict[str, Any]) -> bool:
    reason_text = " ".join(
        str(value or "")
        for value in (
            row.get("paper_opportunity_tier_reason"),
            row.get("paper_fill_block_reason"),
            row.get("paper_allocation_block_reason"),
            row.get("allocator_reason"),
        )
    ).upper()
    list_reasons = " ".join(
        str(reason or "")
        for field in (
            "paper_fill_gate_block_reasons",
            "local_block_reasons",
            "paper_runtime_market_evidence_rejection_reasons",
            "paper_pre_fill_market_evidence_rejection_reasons",
            "paper_post_fill_market_evidence_rejection_reasons",
        )
        for reason in (row.get(field) or [])
    ).upper()
    return not any(
        token in f"{reason_text} {list_reasons}"
        for token in ("SPREAD", "SLIPPAGE", "LIQUIDITY", "LIQUIDATION")
    )


def _paper_canary_integrity_pass(row: dict[str, Any]) -> bool:
    if row.get("valid_for_paper") is False:
        return False
    reason = str(row.get("paper_opportunity_tier_reason") or "").upper()
    if "INTEGRITY" in reason:
        return False
    if row.get("market_state_reject_reasons"):
        return False
    return True


def _paper_canary_risk_pass(row: dict[str, Any]) -> bool:
    if not row.get("risk_decision_id"):
        return False
    joined = " ".join(
        str(reason or "")
        for field in ("paper_fill_gate_block_reasons", "local_block_reasons")
        for reason in (row.get(field) or [])
    ).upper()
    return not any(
        token in joined
        for token in ("RISK", "DRAWDOWN", "EXPOSURE", "CAP", "LIQUIDATION")
    )


def _paper_canary_pre_tier_allocator_pass(row: dict[str, Any]) -> bool:
    gross_notional = _coerce_float(
        _first_present(
            row.get("pre_paper_tier_block_gross_notional_usd"),
            row.get("normal_adaptive_gross_notional_usd"),
            row.get("gross_notional_usd"),
            row.get("target_notional_usdt"),
        )
    )
    risk_budget = _coerce_float(
        _first_present(
            row.get("pre_paper_tier_block_risk_budget_usd"),
            row.get("normal_adaptive_risk_budget_usd"),
            row.get("risk_budget_usd"),
        )
    )
    return (
        gross_notional is not None
        and gross_notional > 0.0
        and risk_budget is not None
        and risk_budget > 0.0
    )


def _paper_canary_adaptive_sizing_pass(row: dict[str, Any]) -> bool:
    if row.get("paper_canary_fixed_notional_allowed") is True:
        return False
    if row.get("paper_canary_live_routing_allowed") is True:
        return False
    allocation = row.get("adaptive_allocation")
    adaptive_policy = str(row.get("adaptive_capital_policy_version") or "")
    has_adaptive_allocator_evidence = (
        adaptive_policy.startswith("ADAPTIVE_CAPITAL_ALLOCATOR")
        or isinstance(allocation, dict)
        or row.get("paper_canary_adaptive_sizing_required") is True
    )
    return has_adaptive_allocator_evidence and _paper_canary_pre_tier_allocator_pass(row)


def _paper_b_grade_lifecycle_canary_row(row: dict[str, Any]) -> bool:
    return (
        row.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
        and _paper_forward_canary_challenger_owned(row)
        and row.get("paper_fill_allowed") is True
        and row.get("paper_only") is True
        and not _paper_forward_canary_live_route_unsafe(row)
        and row.get("counts_as_a_grade_evidence") is not True
        and _paper_forward_canary_production_cost_pass(row)
        and _paper_canary_score(row) is not None
        and _paper_canary_edge_favorable(row)
        and _paper_canary_liquidity_pass(row)
        and _paper_canary_integrity_pass(row)
        and _paper_canary_risk_pass(row)
        and bool(row.get("orchestrator_decision_id"))
        and _paper_canary_adaptive_sizing_pass(row)
    )


def _paper_b_grade_canary_supply_status(
    rows: list[dict[str, Any]],
    *,
    accepted_rows: list[dict[str, Any]] | None = None,
    open_position_rows: list[dict[str, Any]] | None = None,
    closed_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize current paper-only B-grade canary supply without admitting fills."""
    accepted_rows = list(accepted_rows or [])
    open_position_rows = list(open_position_rows or [])
    closed_rows = list(closed_rows or [])
    canary_intent_rows = [
        row
        for row in rows
        if row.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
    ]
    canary_pending_rows = [
        row
        for row in canary_intent_rows
        if row.get("paper_fill_allowed") is True
        and row.get("paper_only") is True
        and row.get("places_real_order") is not True
    ]

    predicate_rows: list[dict[str, Any]] = []
    near_miss_strategy_rows: list[dict[str, Any]] = []
    root_causes = {
        "score_below_threshold": 0,
        "expected_edge_below_cost": 0,
        "production_grade_cost_missing": 0,
        "liquidity_failed": 0,
        "integrity_failed": 0,
        "risk_failed": 0,
        "orchestrator_failed": 0,
        "strategy_failed": 0,
        "allocator_failed": 0,
        "distribution_drift": 0,
        "point_in_time_long_short_unavailable": 0,
        "unsafe_live_route_flags": 0,
    }
    predicate_counts = {
        "score_threshold_pass_rows": 0,
        "expected_edge_after_cost_favorable_rows": 0,
        "production_grade_cost_rows": 0,
        "liquidity_pass_rows": 0,
        "integrity_pass_rows": 0,
        "risk_gateway_decision_rows": 0,
        "risk_pass_rows": 0,
        "orchestrator_rows": 0,
        "strategy_entry_evidence_rows": 0,
        "allocator_pre_tier_size_rows": 0,
        "long_short_point_in_time_rows": 0,
        "paper_only_safety_rows": 0,
    }

    for row in rows:
        score = _paper_canary_score(row)
        score_pass = score is not None and score >= B_GRADE_EXPLORATION_MIN_CONFIDENCE
        edge_pass = _paper_canary_edge_favorable(row)
        production_cost_pass = row.get("production_grade_cost_flag") is True
        liquidity_pass = _paper_canary_liquidity_pass(row)
        integrity_pass = _paper_canary_integrity_pass(row)
        risk_gateway_decision = bool(row.get("risk_decision_id"))
        risk_pass = _paper_canary_risk_pass(row)
        orchestrator_pass = bool(row.get("orchestrator_decision_id"))
        strategy_reasons = _paper_lifecycle_or_no_trade_strategy_reasons(
            signal={},
            intent=row,
        )
        strategy_pass = not strategy_reasons
        allocator_pass = _paper_canary_pre_tier_allocator_pass(row)
        long_short_status = str(row.get("long_short_ratio_status") or "")
        long_short_pass = (
            long_short_status == "V2_LONG_SHORT_RATIO_ATTACHED"
            or row.get("long_short_ratio") not in (None, "")
        )
        paper_only_safety = (
            row.get("paper_only") is True
            and row.get("routes_to_live") is not True
            and row.get("places_real_order") is not True
            and row.get("live_order") is not True
            and row.get("test_order") is not True
            and row.get("counts_as_a_grade_evidence") is not True
            and row.get("paper_canary_adaptive_sizing_required") is True
            and row.get("paper_canary_fixed_notional_allowed") is False
            and row.get("paper_canary_live_routing_allowed") is False
        )

        predicate_counts["score_threshold_pass_rows"] += int(score_pass)
        predicate_counts["expected_edge_after_cost_favorable_rows"] += int(edge_pass)
        predicate_counts["production_grade_cost_rows"] += int(production_cost_pass)
        predicate_counts["liquidity_pass_rows"] += int(liquidity_pass)
        predicate_counts["integrity_pass_rows"] += int(integrity_pass)
        predicate_counts["risk_gateway_decision_rows"] += int(risk_gateway_decision)
        predicate_counts["risk_pass_rows"] += int(risk_pass)
        predicate_counts["orchestrator_rows"] += int(orchestrator_pass)
        predicate_counts["strategy_entry_evidence_rows"] += int(strategy_pass)
        predicate_counts["allocator_pre_tier_size_rows"] += int(allocator_pass)
        predicate_counts["long_short_point_in_time_rows"] += int(long_short_pass)
        predicate_counts["paper_only_safety_rows"] += int(paper_only_safety)

        if not score_pass:
            root_causes["score_below_threshold"] += 1
        if not edge_pass:
            root_causes["expected_edge_below_cost"] += 1
        if not production_cost_pass:
            root_causes["production_grade_cost_missing"] += 1
        if not liquidity_pass:
            root_causes["liquidity_failed"] += 1
        if not integrity_pass:
            root_causes["integrity_failed"] += 1
        if not risk_pass:
            root_causes["risk_failed"] += 1
        if not orchestrator_pass:
            root_causes["orchestrator_failed"] += 1
        if not strategy_pass:
            root_causes["strategy_failed"] += 1
        if not allocator_pass:
            root_causes["allocator_failed"] += 1
        drift_reasons = row.get("paper_signal_temporal_rejection_reasons") or []
        if row.get("distribution_drift") or any("DRIFT" in str(reason).upper() for reason in drift_reasons):
            root_causes["distribution_drift"] += 1
        if long_short_status.startswith("REJECTED_LONG_SHORT"):
            root_causes["point_in_time_long_short_unavailable"] += 1
        if not paper_only_safety:
            root_causes["unsafe_live_route_flags"] += 1

        candidate_predicates_pass = all(
            (
                score_pass,
                edge_pass,
                production_cost_pass,
                liquidity_pass,
                integrity_pass,
                risk_pass,
                orchestrator_pass,
                strategy_pass,
                allocator_pass,
                paper_only_safety,
            )
        )
        if candidate_predicates_pass:
            predicate_rows.append(row)
        elif all(
            (
                score_pass,
                edge_pass,
                production_cost_pass,
                liquidity_pass,
                integrity_pass,
                risk_pass,
                orchestrator_pass,
                allocator_pass,
                paper_only_safety,
            )
        ) and not strategy_pass:
            near_miss_strategy_rows.append(row)

    lifecycle_accepted_rows = [
        row for row in accepted_rows if _paper_b_grade_lifecycle_canary_row(row)
    ]
    lifecycle_open_rows = [
        row for row in open_position_rows if _paper_b_grade_lifecycle_canary_row(row)
    ]
    lifecycle_closed_outcome_rows = [
        row
        for row in closed_rows
        if row.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
        and not _paper_forward_canary_row_rejection_reasons(row)
    ]
    combined_canary_candidates = len(predicate_rows) or len(lifecycle_accepted_rows)
    combined_canary_intents = len(canary_intent_rows) or len(lifecycle_accepted_rows)
    combined_canary_pending_rows = len(canary_pending_rows) or len(lifecycle_open_rows)
    if canary_pending_rows:
        status = "B_GRADE_CANARY_PENDING_SUPPLY_PRESENT"
    elif lifecycle_open_rows:
        status = "B_GRADE_CANARY_LIFECYCLE_SUPPLY_PRESENT_CURRENT_CYCLE_BLOCKED"
    else:
        status = "BLOCKED_ZERO_B_GRADE_CANARY_SUPPLY"

    return {
        "schema_version": "paper_b_grade_canary_supply_status_v1",
        "status": status,
        "canary_id": CHALLENGER_B_GRADE_PAPER_CANARY,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "adaptive_sizing_required": True,
        "production_grade_cost_required": True,
        "risk_gateway_required": True,
        "orchestrator_required": True,
        "market_integrity_required": True,
        "liquidity_pass_required": True,
        "rows": len(rows),
        "canary_candidates": combined_canary_candidates,
        "canary_intents": combined_canary_intents,
        "canary_pending_rows": combined_canary_pending_rows,
        "current_cycle_canary_candidates": len(predicate_rows),
        "current_cycle_canary_intents": len(canary_intent_rows),
        "current_cycle_canary_pending_rows": len(canary_pending_rows),
        "lifecycle_accepted_canary_rows": len(lifecycle_accepted_rows),
        "lifecycle_open_canary_rows": len(lifecycle_open_rows),
        "lifecycle_closed_canary_outcome_rows": len(lifecycle_closed_outcome_rows),
        "near_miss_strategy_blocked_rows": len(near_miss_strategy_rows),
        "predicate_counts": predicate_counts,
        "root_cause_counts": root_causes,
        "dominant_runtime_reasons": _count_first_present_values(
            rows,
            (
                "pre_non_executable_paper_tier_reason",
                "paper_opportunity_tier_reason",
                "paper_fill_block_reason",
                "paper_allocation_block_reason",
                "allocator_reason",
            ),
        ),
        "pass_conditions": {
            "canary_candidates_gt_zero": combined_canary_candidates > 0,
            "canary_intents_gt_zero": combined_canary_intents > 0,
            "canary_pending_rows_gt_zero": combined_canary_pending_rows > 0,
        },
        "current_cycle_pass_conditions": {
            "canary_candidates_gt_zero": len(predicate_rows) > 0,
            "canary_intents_gt_zero": len(canary_intent_rows) > 0,
            "canary_pending_rows_gt_zero": len(canary_pending_rows) > 0,
        },
        "sample_canary_candidates": _compact_rows_for_state(
            _sample_rows(predicate_rows or lifecycle_accepted_rows, 10)
        ),
        "sample_canary_pending_rows": _compact_rows_for_state(
            _sample_rows(canary_pending_rows or lifecycle_open_rows, 10)
        ),
        "sample_lifecycle_closed_canary_outcomes": _paper_forward_canary_compact_sample(
            _sample_rows(lifecycle_closed_outcome_rows, 10)
        ),
        "sample_near_miss_strategy_blocked_rows": _compact_rows_for_state(
            _sample_rows(near_miss_strategy_rows, 10)
        ),
        "live_path_changed": False,
        "generated_utc": _utc_iso(),
    }


def _paper_adaptive_threshold_runtime_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    floor_rows: list[dict[str, Any]] = []
    evaluated_rows = 0
    static_pass_rows = 0
    adaptive_pass_rows = 0
    adaptive_block_rows = 0
    raised_floor_rows = 0
    never_below_static_rows = 0
    floor_values: list[float] = []
    penalty_counts = {
        "drawdown_pressure": 0,
        "cost_edge_pressure": 0,
        "depth_pressure": 0,
        "long_short_point_in_time_pressure": 0,
    }
    signal_stale_policy_rows = 0
    signal_stale_never_above_static_rows = 0
    signal_stale_stricter_rows = 0
    signal_stale_threshold_values: list[int] = []
    for row in rows:
        stale_policy = row.get("paper_signal_adaptive_stale_policy")
        if not isinstance(stale_policy, dict):
            stale_policy = _paper_signal_adaptive_stale_policy(row)
        signal_stale_policy_rows += 1
        adaptive_stale_seconds = _coerce_float(stale_policy.get("adaptive_stale_seconds"))
        static_stale_seconds = _coerce_float(stale_policy.get("static_operator_max_seconds"))
        if adaptive_stale_seconds is not None and static_stale_seconds is not None:
            signal_stale_threshold_values.append(int(adaptive_stale_seconds))
            signal_stale_never_above_static_rows += int(
                adaptive_stale_seconds <= static_stale_seconds
            )
            signal_stale_stricter_rows += int(
                adaptive_stale_seconds < static_stale_seconds
            )

        confidence = _paper_canary_score(row)
        if confidence is None:
            continue
        evaluated_rows += 1
        budget = _b_grade_exploration_budget_fraction(
            confidence_calibrated=confidence,
            drawdown_bps=_first_present(
                row.get("drawdown_bps"),
                row.get("drawdown_at_entry"),
                row.get("portfolio_drawdown_bps"),
            ),
            expected_move_after_cost_bps=_first_present(
                row.get("expected_move_after_cost_bps"),
                row.get("expected_net_edge_bps"),
                row.get("paper_allocation_signed_expected_move_after_cost_bps"),
            ),
            observed_spread_bps=_first_present(
                row.get("actual_observed_spread_entry_bps"),
                row.get("observed_spread_bps"),
                row.get("bid_ask_spread_bps"),
            ),
            expected_slippage_bps=row.get("expected_slippage_bps"),
            fee_bps=row.get("fee_bps"),
            depth_utilization_pct=row.get("depth_utilization_pct"),
            long_short_ratio_status=row.get("long_short_ratio_status"),
        )
        static_floor = _coerce_float(budget.get("b_grade_exploration_static_confidence_floor"))
        adaptive_floor = _coerce_float(budget.get("b_grade_exploration_adaptive_confidence_floor"))
        if static_floor is None or adaptive_floor is None:
            continue
        floor_values.append(adaptive_floor)
        static_pass = confidence >= static_floor
        adaptive_pass = confidence >= adaptive_floor
        static_pass_rows += int(static_pass)
        adaptive_pass_rows += int(adaptive_pass)
        adaptive_block_rows += int(static_pass and not adaptive_pass)
        raised_floor_rows += int(adaptive_floor > static_floor)
        never_below_static_rows += int(adaptive_floor >= static_floor)
        penalties = budget.get("b_grade_exploration_floor_penalties")
        if isinstance(penalties, dict):
            for key in penalty_counts:
                penalty_counts[key] += int((_coerce_float(penalties.get(key)) or 0.0) > 0.0)
        floor_rows.append({
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "side": row.get("side"),
            "paper_opportunity_tier": row.get("paper_opportunity_tier"),
            "confidence_calibrated": round(float(confidence), 8),
            "static_floor": round(float(static_floor), 8),
            "adaptive_floor": round(float(adaptive_floor), 8),
            "static_floor_pass": static_pass,
            "adaptive_floor_pass": adaptive_pass,
            "long_short_ratio_status": row.get("long_short_ratio_status"),
            "paper_only": row.get("paper_only"),
            "routes_to_live": row.get("routes_to_live"),
            "places_real_order": row.get("places_real_order"),
        })
    floor_min = min(floor_values) if floor_values else None
    floor_max = max(floor_values) if floor_values else None
    floor_avg = sum(floor_values) / len(floor_values) if floor_values else None
    stale_min = min(signal_stale_threshold_values) if signal_stale_threshold_values else None
    stale_max = max(signal_stale_threshold_values) if signal_stale_threshold_values else None
    return {
        "schema_version": "paper_adaptive_threshold_runtime_status_v1",
        "status": (
            "PARTIAL_B_GRADE_CONFIDENCE_FLOOR_AND_SIGNAL_STALENESS_ADAPTIVE_FAIL_CLOSED_"
            "STATIC_THRESHOLDS_REMAIN"
        ),
        "adaptive_threshold_id": "b_grade_confidence_floor,paper_signal_stale_seconds",
        "adaptive_threshold_scope": "paper_only_b_grade_exploration_admission_and_signal_freshness",
        "runtime_behavior_changed": True,
        "strategy_or_risk_logic_changed": False,
        "paper_admission_changed": True,
        "threshold_lowering_to_force_trades": False,
        "static_confidence_floor": B_GRADE_EXPLORATION_MIN_CONFIDENCE,
        "adaptive_confidence_floor_max": B_GRADE_EXPLORATION_ADAPTIVE_CONFIDENCE_FLOOR_MAX,
        "evaluated_rows": evaluated_rows,
        "static_floor_pass_rows": static_pass_rows,
        "adaptive_floor_pass_rows": adaptive_pass_rows,
        "adaptive_floor_block_rows": adaptive_block_rows,
        "raised_floor_rows": raised_floor_rows,
        "adaptive_floor_never_below_static_rows": never_below_static_rows,
        "floor_stats": {
            "min": round(floor_min, 8) if floor_min is not None else None,
            "max": round(floor_max, 8) if floor_max is not None else None,
            "avg": round(floor_avg, 8) if floor_avg is not None else None,
        },
        "penalty_counts": penalty_counts,
        "adaptive_signal_stale_threshold": {
            "threshold_id": "paper_signal_stale_seconds",
            "operator_min_seconds": PAPER_SIGNAL_ADAPTIVE_STALE_OPERATOR_MIN_SECONDS,
            "operator_max_seconds": PAPER_SIGNAL_STALE_SECONDS,
            "timeframe_candle_multiplier": PAPER_SIGNAL_ADAPTIVE_STALE_CANDLE_MULTIPLIER,
            "evaluated_rows": signal_stale_policy_rows,
            "adaptive_never_above_static_rows": signal_stale_never_above_static_rows,
            "adaptive_stricter_than_static_rows": signal_stale_stricter_rows,
            "threshold_seconds_min": stale_min,
            "threshold_seconds_max": stale_max,
            "threshold_lowering_to_force_trades": False,
            "mode": "TIMEFRAME_CONTEXTUAL_FAIL_CLOSED_NEVER_ABOVE_STATIC",
        },
        "remaining_static_threshold_blockers": [
            "directional_collapse_guard",
            "strategy_mode_collapse_guard",
            "paper_drawdown_recovery_min_confidence",
            "standalone_1m_gate",
            "audit_blocked_allowed_entry_timeframes",
            "outcome_memory_degradation_thresholds",
            "leverage_recommendation_tiers",
            "alpha_liquidity_risk_config",
            "microstructure_toxicity_threshold",
        ],
        "pass_conditions": {
            "adaptive_floor_evaluated_rows_gt_zero": evaluated_rows > 0,
            "adaptive_floor_never_below_static": never_below_static_rows == evaluated_rows,
            "adaptive_signal_stale_threshold_evaluated_rows_gt_zero": signal_stale_policy_rows > 0,
            "adaptive_signal_stale_threshold_never_above_static": (
                signal_stale_never_above_static_rows == signal_stale_policy_rows
            ),
            "threshold_not_lowered_to_force_trades": True,
            "paper_only": True,
            "routes_to_live_false": True,
            "places_real_order_false": True,
            "ready_allowed": False,
        },
        "sample_rows": _sample_rows(floor_rows, 10),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "live_path_changed": False,
        "generated_utc": _utc_iso(),
    }


def _paper_a_grade_gate_burndown_status(
    rows: list[dict[str, Any]],
    *,
    accepted_rows: list[dict[str, Any]],
    open_position_rows: list[dict[str, Any]],
    closed_rows: list[dict[str, Any]],
    guardian_gate: dict[str, Any] | None,
    guardian_status: dict[str, Any] | None,
    b_grade_canary_supply_status: dict[str, Any],
) -> dict[str, Any]:
    guardian_gate = guardian_gate if isinstance(guardian_gate, dict) else {}
    guardian_status = guardian_status if isinstance(guardian_status, dict) else {}
    predicate_counts = {
        "score_threshold_pass_rows": 0,
        "expected_edge_after_cost_favorable_rows": 0,
        "production_grade_cost_rows": 0,
        "liquidity_pass_rows": 0,
        "integrity_pass_rows": 0,
        "risk_pass_rows": 0,
        "orchestrator_rows": 0,
        "strategy_pass_rows": 0,
        "allocator_pass_rows": 0,
        "paper_only_safety_rows": 0,
    }
    a_grade_rows: list[dict[str, Any]] = []
    near_a_grade_rows: list[dict[str, Any]] = []
    root_causes = {
        "score_below_threshold": 0,
        "expected_edge_below_cost": 0,
        "production_grade_cost_missing": 0,
        "liquidity_failed": 0,
        "integrity_failed": 0,
        "risk_failed": 0,
        "orchestrator_failed": 0,
        "strategy_failed": 0,
        "allocator_failed": 0,
        "unsafe_live_route_flags": 0,
        "guardian_halted": 0,
    }

    guardian_halted = guardian_gate.get("a_grade_new_entries_allowed") is False
    for row in rows:
        score = _paper_canary_score(row)
        score_pass = score is not None and score >= B_GRADE_EXPLORATION_MIN_CONFIDENCE
        edge_pass = _paper_canary_edge_favorable(row)
        production_cost_pass = _paper_forward_canary_production_cost_pass(row)
        liquidity_pass = _paper_canary_liquidity_pass(row)
        integrity_pass = _paper_canary_integrity_pass(row)
        risk_pass = _paper_canary_risk_pass(row)
        orchestrator_pass = bool(row.get("orchestrator_decision_id"))
        strategy_pass = not _paper_lifecycle_or_no_trade_strategy_reasons(
            signal={},
            intent=row,
        )
        allocator_pass = _paper_canary_pre_tier_allocator_pass(row)
        paper_only_safety = (
            row.get("paper_only") is True
            and not _paper_forward_canary_live_route_unsafe(row)
            and row.get("counts_as_a_grade_evidence") is not True
        )

        predicate_counts["score_threshold_pass_rows"] += int(score_pass)
        predicate_counts["expected_edge_after_cost_favorable_rows"] += int(edge_pass)
        predicate_counts["production_grade_cost_rows"] += int(production_cost_pass)
        predicate_counts["liquidity_pass_rows"] += int(liquidity_pass)
        predicate_counts["integrity_pass_rows"] += int(integrity_pass)
        predicate_counts["risk_pass_rows"] += int(risk_pass)
        predicate_counts["orchestrator_rows"] += int(orchestrator_pass)
        predicate_counts["strategy_pass_rows"] += int(strategy_pass)
        predicate_counts["allocator_pass_rows"] += int(allocator_pass)
        predicate_counts["paper_only_safety_rows"] += int(paper_only_safety)

        if not score_pass:
            root_causes["score_below_threshold"] += 1
        if not edge_pass:
            root_causes["expected_edge_below_cost"] += 1
        if not production_cost_pass:
            root_causes["production_grade_cost_missing"] += 1
        if not liquidity_pass:
            root_causes["liquidity_failed"] += 1
        if not integrity_pass:
            root_causes["integrity_failed"] += 1
        if not risk_pass:
            root_causes["risk_failed"] += 1
        if not orchestrator_pass:
            root_causes["orchestrator_failed"] += 1
        if not strategy_pass:
            root_causes["strategy_failed"] += 1
        if not allocator_pass:
            root_causes["allocator_failed"] += 1
        if not paper_only_safety:
            root_causes["unsafe_live_route_flags"] += 1
        if guardian_halted:
            root_causes["guardian_halted"] += 1

        a_grade_tier = row.get("paper_opportunity_tier") == PAPER_TIER_A_GRADE_EXECUTION
        base_predicates_pass = all(
            (
                score_pass,
                edge_pass,
                production_cost_pass,
                liquidity_pass,
                integrity_pass,
                risk_pass,
                orchestrator_pass,
                strategy_pass,
                allocator_pass,
                paper_only_safety,
            )
        )
        if a_grade_tier and row.get("paper_fill_allowed") is True and base_predicates_pass:
            a_grade_rows.append(row)
        elif base_predicates_pass:
            near_a_grade_rows.append(row)

    guardian_reasons = [
        reason
        for reason in (guardian_gate.get("failure_reasons") or [])
        if isinstance(reason, dict)
    ]
    dominant_current_reasons = _count_first_present_values(
        rows,
        (
            "pre_non_executable_paper_tier_reason",
            "paper_opportunity_tier_reason",
            "paper_fill_block_reason",
            "paper_allocation_block_reason",
            "allocator_reason",
        ),
    )
    top_current_reason = (
        max(dominant_current_reasons.items(), key=lambda item: item[1])[0]
        if dominant_current_reasons
        else None
    )
    top_guardian_reason = guardian_reasons[0] if guardian_reasons else None
    if a_grade_rows:
        closest_gap_reason = "A_GRADE_ROWS_PRESENT"
    elif near_a_grade_rows:
        closest_gap_reason = (
            "BASE_A_GRADE_PREDICATES_PRESENT_BUT_SOURCE_TIER_OR_GUARDIAN_NOT_A_GRADE_READY"
        )
    elif top_current_reason:
        closest_gap_reason = str(top_current_reason or "CURRENT_RUNTIME_GATE_BLOCKED")
    elif top_guardian_reason:
        closest_gap_reason = str(top_guardian_reason.get("reason") or "GUARDIAN_GATE_BLOCKED")
    else:
        closest_gap_reason = "NO_A_GRADE_RUNTIME_SUPPLY"

    strategy_brain = guardian_status.get("strategy_brain_status")
    strategy_brain = strategy_brain if isinstance(strategy_brain, dict) else {}
    zero_liquidation = guardian_status.get("zero_liquidation_status")
    zero_liquidation = zero_liquidation if isinstance(zero_liquidation, dict) else {}
    performance = guardian_status.get("realtime_a_grade_performance_status")
    performance = performance if isinstance(performance, dict) else {}
    b_grade_lifecycle_supply_present = all(
        bool(value)
        for value in (b_grade_canary_supply_status.get("pass_conditions") or {}).values()
    )
    current_cycle_supply_present = all(
        bool(value)
        for value in (b_grade_canary_supply_status.get("current_cycle_pass_conditions") or {}).values()
    )

    return {
        "schema_version": "paper_a_grade_gate_burndown_status_v1",
        "status": "A_GRADE_GATE_ACTIVE_BLOCKED_SOURCE_OWNED",
        "prediction_rows": len(rows),
        "candidate_rows": len(rows),
        "production_grade_cost_rows": predicate_counts["production_grade_cost_rows"],
        "liquidity_pass_rows": predicate_counts["liquidity_pass_rows"],
        "risk_pass_rows": predicate_counts["risk_pass_rows"],
        "strategy_pass_rows": predicate_counts["strategy_pass_rows"],
        "allocator_pass_rows": predicate_counts["allocator_pass_rows"],
        "A_grade_rows": len(a_grade_rows),
        "near_A_grade_rows": len(near_a_grade_rows),
        "accepted_b_grade_lifecycle_rows": int(
            b_grade_canary_supply_status.get("lifecycle_accepted_canary_rows") or 0
        ),
        "open_b_grade_lifecycle_rows": int(
            b_grade_canary_supply_status.get("lifecycle_open_canary_rows") or 0
        ),
        "closed_b_grade_lifecycle_outcome_rows": int(
            b_grade_canary_supply_status.get("lifecycle_closed_canary_outcome_rows") or 0
        ),
        "b_grade_lifecycle_supply_present": b_grade_lifecycle_supply_present,
        "current_cycle_b_grade_supply_present": current_cycle_supply_present,
        "current_cycle_b_grade_supply_counts": {
            "canary_candidates": b_grade_canary_supply_status.get("current_cycle_canary_candidates"),
            "canary_intents": b_grade_canary_supply_status.get("current_cycle_canary_intents"),
            "canary_pending_rows": b_grade_canary_supply_status.get("current_cycle_canary_pending_rows"),
        },
        "predicate_counts": predicate_counts,
        "root_cause_counts": root_causes,
        "dominant_current_runtime_reasons": dominant_current_reasons,
        "guardian_gate_status": {
            "status": guardian_gate.get("status"),
            "a_grade_new_entries_allowed": guardian_gate.get("a_grade_new_entries_allowed"),
            "block_all_new_a_grade_entries": guardian_gate.get("block_all_new_a_grade_entries"),
            "new_candidate_tier_override": guardian_gate.get("new_candidate_tier_override"),
            "allowed_runtime_actions": guardian_gate.get("allowed_runtime_actions") or [],
            "failure_reasons": guardian_reasons,
            "generated_utc": guardian_gate.get("generated_utc"),
        },
        "guardian_strategy_brain_status": {
            "status": strategy_brain.get("status"),
            "a_grade_active_bucket_count": strategy_brain.get("a_grade_active_bucket_count"),
            "bucket_count": strategy_brain.get("bucket_count"),
            "blocker_counts": strategy_brain.get("blocker_counts") or {},
        },
        "guardian_zero_liquidation_status": {
            "status": zero_liquidation.get("status"),
            "a_grade_candidate_count": zero_liquidation.get("a_grade_candidate_count"),
            "passed_a_grade_candidate_count": zero_liquidation.get("passed_a_grade_candidate_count"),
        },
        "guardian_realtime_performance_status": {
            "status": performance.get("status"),
            "closed_economic_trade_count": performance.get("closed_economic_trade_count"),
            "symbol_count": performance.get("symbol_count"),
            "long_outcomes": performance.get("long_outcomes"),
            "short_outcomes": performance.get("short_outcomes"),
        },
        "closest_gap_reason": closest_gap_reason,
        "pass_conditions": {
            "A_grade_rows_gt_zero": len(a_grade_rows) > 0,
            "source_owned_zero_supply_root_cause_mapped": bool(
                root_causes or guardian_reasons or dominant_current_reasons
            ),
            "a_grade_new_entries_allowed": guardian_gate.get("a_grade_new_entries_allowed") is True,
            "ready_allowed": False,
        },
        "sample_a_grade_rows": _compact_rows_for_state(_sample_rows(a_grade_rows, 10)),
        "sample_near_a_grade_rows": _compact_rows_for_state(_sample_rows(near_a_grade_rows, 10)),
        "source_rows": {
            "intent_rows": len(rows),
            "accepted_rows": len(accepted_rows),
            "open_position_rows": len(open_position_rows),
            "closed_rows": len(closed_rows),
        },
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "live_path_changed": False,
        "generated_utc": _utc_iso(),
    }


def _paper_forward_canary_production_cost_pass(row: dict[str, Any]) -> bool:
    return (
        row.get("production_grade_cost_flag") is True
        or row.get("production_grade_cost_evidence") is True
        or row.get("runtime_cost_capture_status") == "PRODUCTION_GRADE_COST_CAPTURE"
    )


def _paper_forward_canary_challenger_owned(row: dict[str, Any]) -> bool:
    return (
        row.get("paper_policy_owner") == PAPER_POLICY_OWNER_CHALLENGER_V2
        or row.get("candidate_id") == CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
        or row.get("policy_id") == CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID
        or row.get("policy_fingerprint") == CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT
    )


def _paper_forward_canary_has_realized_outcome(row: dict[str, Any]) -> bool:
    return (
        _coerce_float(
            _first_present(
                row.get("realized_net_pnl_bps"),
                row.get("realized_pnl_bps"),
                row.get("paper_exit_pnl_bps"),
            )
        )
        is not None
        or _coerce_float(
            _first_present(
                row.get("realized_net_pnl_usd"),
                row.get("realized_pnl_usd"),
                row.get("realized_pnl_usdt"),
            )
        )
        is not None
    )


def _paper_forward_canary_live_route_unsafe(row: dict[str, Any]) -> bool:
    return any(
        row.get(field) is True
        for field in (
            "routes_to_live",
            "places_real_order",
            "live_order",
            "test_order",
            "leverage_mutation",
            "margin_mode_mutation",
        )
    )


def _paper_forward_canary_liquidation_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if any(
        row.get(field) is True
        for field in (
            "liquidation",
            "liquidated",
            "liquidation_event",
            "paper_liquidation_event",
        )
    ):
        reasons.append("LIQUIDATION_FLAG_TRUE")
    close_reason = str(_first_present(row.get("close_reason"), row.get("exit_reason"), "")).upper()
    if "LIQUIDATION" in close_reason:
        reasons.append("LIQUIDATION_CLOSE_REASON")
    return reasons


def _paper_forward_canary_accounting_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if any(
        row.get(field) is True
        for field in (
            "accounting_mismatch",
            "paper_accounting_mismatch",
            "pnl_accounting_mismatch",
            "cost_accounting_mismatch",
            "position_accounting_mismatch",
        )
    ):
        reasons.append("ACCOUNTING_MISMATCH_FLAG_TRUE")
    for field in (
        "accounting_status",
        "pnl_accounting_status",
        "funding_pnl_accounting_status",
        "pnl_reconciliation_status",
    ):
        value = str(row.get(field) or "").upper()
        if "MISMATCH" in value or value.startswith("INVALID"):
            reasons.append(f"{field.upper()}_{value}")
    return reasons


def _paper_forward_canary_point_in_time_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    decision_raw = _first_present(row.get("decision_time"), row.get("entry_feature_decision_time"))
    decision_time = _parse_strategy_time(decision_raw)
    if decision_time is None:
        reasons.append("MISSING_DECISION_TIME")
    available_raw = _first_present(row.get("available_at"), row.get("entry_feature_available_at"))
    available_at = _parse_strategy_time(available_raw)
    if available_at is None:
        reasons.append("MISSING_AVAILABLE_AT")
    elif decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    feature_cutoff_raw = _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff"))
    feature_cutoff = _parse_strategy_time(feature_cutoff_raw)
    if feature_cutoff is None:
        reasons.append("MISSING_FEATURE_CUTOFF")
    elif decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if row.get("future_labels_used_as_features") is True:
        reasons.append("FUTURE_LABELS_USED_AS_FEATURES")
    return reasons


def _paper_forward_canary_row_rejection_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("paper_opportunity_tier") != PAPER_TIER_B_GRADE_EXPLORATION:
        reasons.append("NOT_B_GRADE_EXPLORATION_PAPER")
    if not _paper_forward_canary_challenger_owned(row):
        reasons.append("NOT_CHALLENGER_V2_POLICY")
    if row.get("paper_only") is not True:
        reasons.append("NOT_PAPER_ONLY")
    if _paper_forward_canary_live_route_unsafe(row):
        reasons.append("UNSAFE_LIVE_ROUTE_FLAG")
    if not _paper_forward_canary_has_realized_outcome(row):
        reasons.append("MISSING_REALIZED_ECONOMIC_OUTCOME")
    side = _normalized_directional_side(_first_present(row.get("side"), row.get("action")))
    if side not in {"long", "short"}:
        reasons.append("MISSING_OR_INVALID_SIDE")
    if not _paper_forward_canary_production_cost_pass(row):
        reasons.append("MISSING_PRODUCTION_GRADE_COST_EVIDENCE_ON_CLOSED_OUTCOME")
    reasons.extend(_paper_forward_canary_point_in_time_reasons(row))
    reasons.extend(_paper_forward_canary_accounting_reasons(row))
    reasons.extend(_paper_forward_canary_liquidation_reasons(row))
    return reasons


FORWARD_CANARY_SAMPLE_FIELDS = (
    "symbol",
    "timeframe",
    "side",
    "paper_opportunity_tier",
    "paper_policy_owner",
    "candidate_id",
    "policy_fingerprint",
    "paper_only",
    "routes_to_live",
    "places_real_order",
    "counts_as_a_grade_evidence",
    "production_grade_cost_flag",
    "production_grade_cost_evidence",
    "runtime_cost_capture_status",
    "realized_pnl_bps",
    "realized_pnl_usd",
    "realized_pnl_usdt",
    "decision_time",
    "feature_cutoff",
    "available_at",
    "close_reason",
    "trainer_feedback_id",
    "forward_canary_rejection_reasons",
)


def _paper_forward_canary_compact_sample(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for row in rows:
        compacted.append(
            {
                field: row.get(field)
                for field in FORWARD_CANARY_SAMPLE_FIELDS
                if row.get(field) not in (None, "", [], {})
            }
        )
    return compacted


def _paper_backfill_closed_outcome_entry_context_rows(
    rows: list[dict[str, Any]],
    *,
    entry_context_by_fill_id: dict[str, dict[str, Any]],
    row_kind: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    repaired_rows: list[dict[str, Any]] = []
    sample_repaired: list[dict[str, Any]] = []
    matched_entry_context_rows = 0
    production_grade_cost_repaired_rows = 0
    policy_identity_repaired_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        before_cost = _paper_forward_canary_production_cost_pass(row)
        before_identity = _paper_forward_canary_challenger_owned(row)
        source_context = _source_entry_context_for_close(
            close_event=row,
            entry_context_by_fill_id=entry_context_by_fill_id,
        )
        if source_context:
            matched_entry_context_rows += 1
            enriched = _with_feedback_context_fallback(row, source_context)
            after_cost = _paper_forward_canary_production_cost_pass(enriched)
            after_identity = _paper_forward_canary_challenger_owned(enriched)
            if after_cost and not before_cost:
                production_grade_cost_repaired_rows += 1
            if after_identity and not before_identity:
                policy_identity_repaired_rows += 1
            if (after_cost and not before_cost) or (after_identity and not before_identity):
                enriched["closed_outcome_entry_context_backfilled"] = True
                enriched["closed_outcome_entry_context_backfill_source"] = (
                    "accepted_fill_entry_context"
                )
                if len(sample_repaired) < 10:
                    sample_repaired.append(enriched)
            repaired_rows.append(enriched)
        else:
            repaired_rows.append(dict(row))

    unmatched_b_grade_challenger_rows = sum(
        1
        for row in repaired_rows
        if row.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
        and _paper_forward_canary_challenger_owned(row)
        and not row.get("closed_outcome_entry_context_backfilled")
        and not _paper_forward_canary_production_cost_pass(row)
    )
    status = {
        "schema_version": "paper_closed_outcome_entry_context_backfill_status_v1",
        "row_kind": row_kind,
        "source_rows": len(rows),
        "entry_context_index_rows": len(entry_context_by_fill_id),
        "matched_entry_context_rows": matched_entry_context_rows,
        "production_grade_cost_repaired_rows": production_grade_cost_repaired_rows,
        "policy_identity_repaired_rows": policy_identity_repaired_rows,
        "unmatched_b_grade_challenger_missing_cost_rows": unmatched_b_grade_challenger_rows,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "live_path_changed": False,
        "sample_repaired_rows": _paper_forward_canary_compact_sample(sample_repaired),
        "generated_utc": _utc_iso(),
    }
    return repaired_rows, status


def _paper_forward_canary_evidence_status(
    *,
    closed_rows: list[dict[str, Any]],
    accepted_rows: list[dict[str, Any]],
    cutover_completed_at: str | None = None,
) -> dict[str, Any]:
    """Summarize Phase 11 forward canary evidence from actual paper lifecycle rows."""
    source_closed_rows = [row for row in closed_rows if isinstance(row, dict)]
    source_accepted_rows = [row for row in accepted_rows if isinstance(row, dict)]
    b_grade_closed_rows = [
        row
        for row in source_closed_rows
        if row.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
        and _paper_forward_canary_challenger_owned(row)
    ]
    cutover_dt = _parse_strategy_time(cutover_completed_at)
    cutover_marker_valid = cutover_completed_at in (None, "") or cutover_dt is not None

    def _closed_event_time(row: dict[str, Any]) -> datetime | None:
        return _parse_strategy_time(
            _first_present(
                row.get("exit_price_utc"),
                row.get("exit_time"),
                row.get("closed_at"),
                row.get("execution_time"),
                row.get("generated_utc"),
                row.get("decision_time"),
                row.get("available_at"),
            )
        )

    if cutover_dt is None:
        evidence_rows = b_grade_closed_rows
    else:
        evidence_rows = [
            row
            for row in b_grade_closed_rows
            if (_closed_event_time(row) is not None and _closed_event_time(row) >= cutover_dt)
        ]
    pre_cutover_rows = max(0, len(b_grade_closed_rows) - len(evidence_rows))
    accepted_b_grade_rows = [
        row
        for row in source_accepted_rows
        if row.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION
        and _paper_forward_canary_challenger_owned(row)
    ]
    production_cost_rows = [
        row for row in evidence_rows if _paper_forward_canary_production_cost_pass(row)
    ]
    rows_rejected_by_reason: dict[str, int] = {}
    valid_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    for row in evidence_rows:
        reasons = _paper_forward_canary_row_rejection_reasons(row)
        if reasons:
            rejected = dict(row)
            rejected["forward_canary_rejection_reasons"] = reasons
            rejected_rows.append(rejected)
            for reason in reasons:
                rows_rejected_by_reason[reason] = rows_rejected_by_reason.get(reason, 0) + 1
        else:
            valid_rows.append(row)

    valid_symbols = sorted({str(row.get("symbol") or "").upper() for row in valid_rows if row.get("symbol")})
    source_symbols = sorted({str(row.get("symbol") or "").upper() for row in evidence_rows if row.get("symbol")})
    valid_side_counts = {
        "long": sum(
            1
            for row in valid_rows
            if _normalized_directional_side(_first_present(row.get("side"), row.get("action"))) == "long"
        ),
        "short": sum(
            1
            for row in valid_rows
            if _normalized_directional_side(_first_present(row.get("side"), row.get("action"))) == "short"
        ),
    }
    source_side_counts = {
        "long": sum(
            1
            for row in evidence_rows
            if _normalized_directional_side(_first_present(row.get("side"), row.get("action"))) == "long"
        ),
        "short": sum(
            1
            for row in evidence_rows
            if _normalized_directional_side(_first_present(row.get("side"), row.get("action"))) == "short"
        ),
    }
    production_cost_coverage = (
        len(production_cost_rows) / len(evidence_rows)
        if evidence_rows
        else 0.0
    )
    accounting_mismatch_rows = sum(
        1 for row in evidence_rows if _paper_forward_canary_accounting_reasons(row)
    )
    liquidation_rows = sum(
        1 for row in evidence_rows if _paper_forward_canary_liquidation_reasons(row)
    )
    point_in_time_invalid_rows = sum(
        1 for row in evidence_rows if _paper_forward_canary_point_in_time_reasons(row)
    )
    unsafe_live_route_rows = sum(
        1 for row in evidence_rows if _paper_forward_canary_live_route_unsafe(row)
    )
    accepted_production_cost_rows = sum(
        1 for row in accepted_b_grade_rows if _paper_forward_canary_production_cost_pass(row)
    )
    pass_conditions = {
        "valid_forward_canary_outcomes_gte_100": (
            len(valid_rows) >= FORWARD_CANARY_REQUIRED_ECONOMIC_OUTCOMES
        ),
        "valid_symbol_count_gte_20": len(valid_symbols) >= FORWARD_CANARY_REQUIRED_SYMBOLS,
        "long_outcomes_gt_zero": valid_side_counts["long"] > 0,
        "short_outcomes_gt_zero": valid_side_counts["short"] > 0,
        "production_grade_cost_coverage_gte_95pct": production_cost_coverage >= 0.95,
        "no_accounting_mismatch": accounting_mismatch_rows == 0,
        "no_liquidation": liquidation_rows == 0,
        "no_point_in_time_violation": point_in_time_invalid_rows == 0,
        "no_live_route_flags": unsafe_live_route_rows == 0,
    }
    if cutover_completed_at not in (None, "") and not cutover_marker_valid:
        status = "BLOCKED_FORWARD_CANARY_CUTOVER_MARKER_INVALID"
    elif all(pass_conditions.values()):
        status = "FORWARD_CANARY_EVIDENCE_REQUIREMENTS_MET"
    elif valid_rows:
        status = "BLOCKED_FORWARD_CANARY_EVIDENCE_INCOMPLETE"
    else:
        status = "BLOCKED_NO_VALID_FORWARD_CANARY_OUTCOMES"
    return {
        "schema_version": "paper_forward_canary_evidence_status_v1",
        "status": status,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "live_path_changed": False,
        "required_forward_canary_economic_outcomes": FORWARD_CANARY_REQUIRED_ECONOMIC_OUTCOMES,
        "required_initial_symbols": FORWARD_CANARY_REQUIRED_SYMBOLS,
        "source_closed_trade_rows": len(source_closed_rows),
        "source_accepted_rows": len(source_accepted_rows),
        "archived_b_grade_challenger_closed_outcome_rows": len(b_grade_closed_rows),
        "b_grade_challenger_closed_outcome_rows": len(evidence_rows),
        "pre_cutover_b_grade_challenger_closed_outcome_rows": pre_cutover_rows,
        "cutover_completed_at": cutover_completed_at,
        "cutover_marker_present": cutover_completed_at not in (None, ""),
        "cutover_marker_valid": cutover_marker_valid,
        "valid_forward_canary_economic_outcomes": len(valid_rows),
        "post_cutover_valid_forward_canary_economic_outcomes": len(valid_rows),
        "production_grade_cost_closed_outcome_rows": len(production_cost_rows),
        "production_grade_cost_coverage": production_cost_coverage,
        "accepted_b_grade_canary_rows": len(accepted_b_grade_rows),
        "accepted_b_grade_production_grade_cost_rows": accepted_production_cost_rows,
        "valid_symbol_count": len(valid_symbols),
        "source_symbol_count": len(source_symbols),
        "valid_side_counts": valid_side_counts,
        "source_side_counts": source_side_counts,
        "accounting_mismatch_rows": accounting_mismatch_rows,
        "liquidation_rows": liquidation_rows,
        "point_in_time_invalid_rows": point_in_time_invalid_rows,
        "unsafe_live_route_rows": unsafe_live_route_rows,
        "rows_rejected_by_reason": rows_rejected_by_reason,
        "pass_conditions": pass_conditions,
        "sample_valid_forward_canary_outcomes": _paper_forward_canary_compact_sample(
            _sample_rows(valid_rows, 10)
        ),
        "sample_rejected_forward_canary_outcomes": _paper_forward_canary_compact_sample(
            _sample_rows(rejected_rows, 10)
        ),
        "generated_utc": _utc_iso(),
    }


def _paper_forward_canary_closed_outcome_identity(row: dict[str, Any]) -> str | None:
    for field in (
        "close_id",
        "paper_close_id",
        "close_event_id",
        "outcome_label_id",
        "paper_trade_id",
        "paper_fill_id",
    ):
        value = row.get(field)
        if value not in (None, ""):
            return f"{field}:{value}"
    symbol = str(row.get("symbol") or "").upper()
    side = _normalized_directional_side(_first_present(row.get("side"), row.get("action")))
    event_time = _first_present(
        row.get("exit_time"),
        row.get("closed_at"),
        row.get("execution_time"),
        row.get("decision_time"),
        row.get("available_at"),
    )
    lineage = _first_present(
        row.get("entry_signal_id"),
        row.get("signal_id"),
        row.get("entry_prediction_id"),
        row.get("prediction_id"),
        row.get("position_id"),
    )
    if not symbol or not side or not event_time:
        return None
    return f"composite:{symbol}:{side}:{event_time}:{lineage or ''}"


def _paper_forward_canary_archive_row_score(row: dict[str, Any]) -> tuple[int, int]:
    populated_fields = sum(1 for value in row.values() if value not in (None, "", [], {}))
    production_cost = 1 if _paper_forward_canary_production_cost_pass(row) else 0
    return production_cost, populated_fields


def _read_paper_forward_canary_closed_outcome_archive(
    path: Path | None = None,
) -> list[dict[str, Any]]:
    path = path or PAPER_FORWARD_CANARY_CLOSED_OUTCOME_ARCHIVE_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    rows = (
        payload.get("closed_outcomes")
        or payload.get("closed_trades")
        or payload.get("rows")
        or []
    )
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _read_paper_forward_canary_cutover_marker(
    path: Path | None = None,
) -> dict[str, Any]:
    path = path or PAPER_FORWARD_CANARY_CUTOVER_MARKER_PATH
    return _read_json_file_payload(path)


def _paper_forward_canary_closed_outcome_archive_status(
    current_closed_rows: list[dict[str, Any]],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    path = path or PAPER_FORWARD_CANARY_CLOSED_OUTCOME_ARCHIVE_PATH
    existing_rows = _read_paper_forward_canary_closed_outcome_archive(path)
    archive_by_id: dict[str, dict[str, Any]] = {}
    duplicate_rows = 0
    rows_without_identity = 0

    def merge_row(row: dict[str, Any]) -> None:
        nonlocal duplicate_rows, rows_without_identity
        if row.get("paper_opportunity_tier") != PAPER_TIER_B_GRADE_EXPLORATION:
            return
        if not _paper_forward_canary_challenger_owned(row):
            return
        identity = _paper_forward_canary_closed_outcome_identity(row)
        if identity is None:
            rows_without_identity += 1
            return
        existing = archive_by_id.get(identity)
        if existing is not None:
            duplicate_rows += 1
            if _paper_forward_canary_archive_row_score(row) <= _paper_forward_canary_archive_row_score(existing):
                return
        archived = dict(row)
        archived["forward_canary_archive_identity"] = identity
        archive_by_id[identity] = archived

    for row in existing_rows:
        merge_row(row)
    existing_unique_count = len(archive_by_id)
    for row in current_closed_rows:
        merge_row(row)

    archived_rows = sorted(
        archive_by_id.values(),
        key=lambda row: str(
            _first_present(
                row.get("exit_time"),
                row.get("closed_at"),
                row.get("execution_time"),
                row.get("decision_time"),
                row.get("available_at"),
                row.get("close_id"),
            )
            or ""
        ),
    )
    return {
        "schema_version": "paper_forward_canary_closed_outcome_archive_v1",
        "status": "ACTIVE_FORWARD_CANARY_CLOSED_OUTCOME_ARCHIVE",
        "source": str(path),
        "existing_archived_closed_outcome_rows": len(existing_rows),
        "existing_unique_closed_outcome_rows": existing_unique_count,
        "current_closed_rows_seen": len(current_closed_rows),
        "archived_closed_outcome_rows": len(archived_rows),
        "new_archived_closed_outcome_rows": max(0, len(archived_rows) - existing_unique_count),
        "duplicate_closed_outcome_rows": duplicate_rows,
        "rows_without_archive_identity": rows_without_identity,
        "closed_outcomes": archived_rows,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "live_path_changed": False,
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
    payload: dict[str, Any] = {}
    if r is None:
        lifecycle_state = _read_lifecycle_state_file()
        if lifecycle_state:
            lifecycle_state["lifecycle_state_source"] = str(PAPER_LIFECYCLE_STATE_PATH)
        return lifecycle_state

    open_positions = _read_json_list_redis_key_if_small(
        r,
        f"{V2_REDIS_PREFIX}paper:positions",
    )
    if open_positions:
        payload["open_positions"] = open_positions
        payload["positions_by_symbol"] = {
            str(row["symbol"]).upper(): row
            for row in open_positions
            if isinstance(row, dict) and row.get("symbol")
        }
        payload["open_position_count"] = len(open_positions)

    closed_trades = _read_json_list_redis_key_if_small(
        r,
        f"{V2_REDIS_PREFIX}paper:closed_trades",
    )
    if closed_trades:
        payload["closed_trades"] = closed_trades
        payload["closes"] = closed_trades
        payload["closed_trade_count"] = len(closed_trades)

    outcome_labels = _read_json_list_redis_key_if_small(
        r,
        f"{V2_REDIS_PREFIX}paper:outcome_labels",
    )
    if outcome_labels:
        payload["outcome_labels"] = outcome_labels
        payload["outcome_label_count"] = len(outcome_labels)

    if not payload:
        redis_ledger = _read_json_redis_key_if_small(
            r,
            f"{V2_REDIS_PREFIX}paper:ledger",
        )
        if redis_ledger:
            payload = redis_ledger

    lifecycle_state = _read_lifecycle_state_file()
    if not lifecycle_state:
        lifecycle_skip = _state_file_skip_status(
            PAPER_LIFECYCLE_STATE_PATH,
            max_bytes=PAPER_STATE_FULL_FILE_READ_MAX_BYTES,
        )
        if lifecycle_skip:
            payload["lifecycle_state_file_skipped"] = lifecycle_skip
        if payload:
            payload.setdefault(
                "lifecycle_state_source",
                "v2:paper:positions+v2:paper:closed_trades+v2:paper:outcome_labels",
            )
        return payload
    merged = dict(payload)
    accepted_fills = lifecycle_state.get("accepted_fills")
    if isinstance(accepted_fills, list):
        merged["accepted"] = accepted_fills
        merged["accepted_intents"] = accepted_fills
        merged["accepted_count"] = len(accepted_fills)
        merged["accepted_fill_state_row_count"] = len(accepted_fills)
    for key in (
        "open_positions",
        "positions_by_symbol",
        "closed_trades",
        "closes",
        "outcome_labels",
        "trainer_feedback_outcomes",
        "trainer_feedback_outcomes_quarantine",
    ):
        value = lifecycle_state.get(key)
        if value not in (None, ""):
            merged[key] = value
    for source_key, count_key in (
        ("open_positions", "open_position_count"),
        ("closed_trades", "closed_trade_count"),
        ("outcome_labels", "outcome_label_count"),
        ("trainer_feedback_outcomes", "trainer_feedback_row_count"),
        ("trainer_feedback_outcomes_quarantine", "trainer_feedback_quarantined_row_count"),
    ):
        value = merged.get(source_key)
        if isinstance(value, list):
            merged[count_key] = len(value)
    merged["lifecycle_state_source"] = str(PAPER_LIFECYCLE_STATE_PATH)
    return merged


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
    portfolio_drawdown = _coerce_float(portfolio.get("current_drawdown_bps"))
    open_position_drawdowns: list[float] = []
    open_rows = [
        row for row in (ledger.get("open_positions") or ledger.get("positions") or [])
        if isinstance(row, dict)
    ]
    for row in open_rows:
        row_drawdown = _coerce_float(
            _first_present(row.get("drawdown_bps"), row.get("max_drawdown_bps"), row.get("mae_bps"))
        )
        if row_drawdown is not None:
            open_position_drawdowns.append(abs(row_drawdown))
        unrealized_bps = _coerce_float(row.get("unrealized_pnl_bps"))
        if unrealized_bps is not None and unrealized_bps < 0:
            open_position_drawdowns.append(abs(unrealized_bps))
    worst_open_position_drawdown = max(open_position_drawdowns) if open_position_drawdowns else 0.0
    current_drawdown = (
        abs(portfolio_drawdown)
        if portfolio_drawdown is not None
        else worst_open_position_drawdown
    )
    return {
        "current_drawdown_bps": current_drawdown,
        "current_drawdown_source": (
            "CURRENT_PORTFOLIO_STATE"
            if portfolio_drawdown is not None
            else "OPEN_POSITION_DRAWDOWN_FALLBACK"
        ),
        "worst_open_position_drawdown_bps": worst_open_position_drawdown,
        "open_position_drawdown_source": "OPEN_POSITION_MAE_AND_UNREALIZED_LOSS",
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
    stale_policy: dict[str, Any] | None = None,
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
    stale_policy = stale_policy or _paper_signal_adaptive_stale_policy(signal, prediction)
    stale_seconds = int(stale_policy["adaptive_stale_seconds"])
    if (
        signal_generated is not None
        and (now - signal_generated).total_seconds() > stale_seconds
    ):
        reasons.append(f"STALE_SIGNAL_GT_{stale_seconds}s_ADAPTIVE")

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


def _paper_runtime_market_evidence_rejection_reasons(
    intent: dict[str, Any],
    *,
    require_fill_ledger: bool = True,
) -> list[str]:
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
    if (
        _coerce_float(intent.get("actual_observed_spread_entry_bps")) is None
        or intent.get("bid_ask_spread_bps_fallback") is True
    ):
        reasons.append(
            str(
                intent.get("bid_ask_spread_bps_unavailable_reason")
                or "MISSING_OBSERVED_SPREAD_AT_DECISION_TIME"
            )
        )
    expected_slippage_source = str(intent.get("expected_slippage_source") or "")
    if (
        _coerce_float(intent.get("expected_slippage_bps")) is None
        or intent.get("expected_slippage_bps_fallback") is True
        or expected_slippage_source == "CONSERVATIVE_MISSING_SLIPPAGE_BLOCKING_ESTIMATE"
    ):
        reasons.append(
            str(
                intent.get("expected_slippage_unavailable_reason")
                or "MISSING_OBSERVED_OR_MODELED_SLIPPAGE_AT_DECISION_TIME"
            )
        )
    # Fee / funding / depth checks are gated on whether those keys are present in the intent.
    # Intents produced before _build_allocation_input (e.g. in unit tests that probe only
    # temporal-label completeness) legitimately lack these fields; the gate prevents false
    # rejections in those contexts while preserving the full check in the production path
    # where _build_allocation_input always writes fee_bps_fallback before this runs.
    if "fee_bps" in intent or "fee_bps_fallback" in intent or "fee_bps_source" in intent:
        if (
            _coerce_float(intent.get("fee_bps")) is None
            or intent.get("fee_bps_fallback") is True
            or not intent.get("fee_bps_source")
        ):
            reasons.append(
                str(
                    intent.get("fee_bps_unavailable_reason")
                    or "MISSING_EXPLICIT_FEE_BPS_AT_DECISION_TIME"
                )
            )
    if (
        "expected_funding_bps" in intent
        or "expected_funding_bps_fallback" in intent
        or "expected_funding_bps_source" in intent
    ):
        if (
            _coerce_float(intent.get("expected_funding_bps")) is None
            or intent.get("expected_funding_bps_fallback") is True
            or not intent.get("expected_funding_bps_source")
        ):
            reasons.append(
                str(
                    intent.get("expected_funding_bps_unavailable_reason")
                    or "MISSING_EXPLICIT_FUNDING_BPS_AT_DECISION_TIME"
                )
            )
    orderbook_depth = _coerce_float(intent.get("orderbook_depth_usd"))
    if "orderbook_depth_usd" in intent or "orderbook_depth_source" in intent:
        if orderbook_depth is None or orderbook_depth <= 0.0 or not intent.get("orderbook_depth_source"):
            reasons.append("MISSING_MARKET_DEPTH_EVIDENCE")
    if _coerce_float(intent.get("squeeze_evidence_score")) is None or not intent.get("squeeze_evidence_source"):
        reasons.append(
            str(
                intent.get("squeeze_evidence_unavailable_reason")
                or "MISSING_SOURCED_SQUEEZE_EVIDENCE"
            )
        )
    if "latency_ms" in intent:
        if _coerce_float(intent.get("latency_ms")) is None:
            reasons.append("MISSING_PAPER_FILL_LATENCY_EVIDENCE")
    maker = _coerce_float(intent.get("maker_probability"))
    taker = _coerce_float(intent.get("taker_probability"))
    if (
        "maker_probability" in intent
        or "taker_probability" in intent
        or "maker_taker_probability_source" in intent
    ):
        if maker is None or taker is None or not intent.get("maker_taker_probability_source"):
            reasons.append("MISSING_MAKER_TAKER_PROBABILITY_EVIDENCE")
    partial_count = _coerce_float(intent.get("partial_fill_count"))
    # Gate partial-fill check on the intent carrying *any* post-execution evidence
    # (latency, mark price, or explicit fill fields), not just on partial_fill_count
    # being present. Intents from temporal-label-only contexts (no fill fields at all)
    # skip this check; fully-processed post-fill intents trigger it.
    _has_post_fill_context = (
        "partial_fill_count" in intent
        or "partial_fills" in intent
        or "latency_ms" in intent
        or "mark_price" in intent
        or "index_price" in intent
    )
    if (
        require_fill_ledger
        and _has_post_fill_context
        and (partial_count is None or partial_count <= 0 or not isinstance(intent.get("partial_fills"), list))
    ):
        reasons.append("MISSING_PARTIAL_FILL_LEDGER_EVIDENCE")
    mark = _coerce_float(intent.get("mark_price"))
    index = _coerce_float(intent.get("index_price"))
    if "mark_price" in intent or "index_price" in intent:
        if mark is None or index is None or mark <= 0.0 or index <= 0.0:
            reasons.append("MISSING_MARK_INDEX_DIVERGENCE_EVIDENCE")
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
            intent.get("paper_admission_decision_time"),
            intent.get("runtime_cost_capture_decision_time"),
            intent.get("entry_feature_decision_time"),
            intent.get("decision_time"),
            intent.get("generated_utc"),
        ),
        "model_decision_time": _first_present(
            intent.get("model_decision_time"),
            intent.get("entry_feature_decision_time"),
            intent.get("decision_time"),
        ),
        "signal_id": intent.get("signal_id"),
        "prediction_id": intent.get("prediction_id"),
        "feature_snapshot_id": intent.get("entry_feature_snapshot_id"),
        "feature_source": intent.get("entry_feature_source"),
        "feature_available_at": intent.get("entry_feature_available_at"),
        "feature_generated_at": intent.get("entry_feature_generated_at"),
        "feature_cutoff": intent.get("entry_feature_cutoff"),
        "entry_spread_available_at": intent.get("entry_spread_available_at"),
        "entry_spread_captured_at": intent.get("entry_spread_captured_at"),
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
    audited_entry_mode = str(
        _first_present(
            intent.get("strategy_selected_mode"),
            intent.get("strategy_id"),
            intent.get("strategy_family"),
            intent.get("strategy_subtype"),
            selected_mode,
        )
        or selected_mode
    )
    intent.setdefault("strategy_id", selected_mode)
    intent.setdefault("strategy_family", selected_mode)
    intent.setdefault("strategy_subtype", selected_mode)
    intent.setdefault("strategy_selected_mode", selected_mode)
    intent.setdefault("entry_reason", audited_entry_mode)
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
            "hedge_expected_shortfall_reduction_usd",
            "expected_shortfall_before",
            "expected_shortfall_after",
            "hedge_cost_usd",
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


PRE_OUTCOME_CANDIDATE_PROVENANCE_DEFAULTS: dict[str, Any] = {
    "selector_policy_fingerprint": OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
    "frozen_selector_fingerprint": OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
    "candidate_selected_before_outcome": True,
    "candidate_selected_after_outcome": False,
    "post_outcome_candidate_selection": False,
    "future_labels_used_as_features": False,
}


def _attach_pre_outcome_candidate_provenance(
    *,
    intent: dict[str, Any],
    allocation: dict[str, Any],
) -> None:
    for field, default in PRE_OUTCOME_CANDIDATE_PROVENANCE_DEFAULTS.items():
        if allocation.get(field) in (None, ""):
            allocation[field] = default
        if intent.get(field) in (None, ""):
            intent[field] = allocation[field]


def _attach_paper_allocation_decision_context(
    intent: dict[str, Any],
    allocation: dict[str, Any],
) -> None:
    _attach_pre_outcome_candidate_provenance(intent=intent, allocation=allocation)
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
        *RUNTIME_COST_CAPTURE_CONTRACT_FIELDS,
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
        "depth_utilization_pct",
        "depth_price_impact_bps",
        "depth_price_impact_source",
        "depth_price_impact_model",
        "depth_price_impact_side",
        "depth_price_impact_quantity",
        "depth_price_impact_filled_quantity",
        "depth_price_impact_fill_complete",
        "depth_price_impact_vwap",
        "depth_price_impact_touch_price",
        "orderbook_imbalance",
        "maker_probability",
        "taker_probability",
        "maker_taker_probability",
        "maker_taker_probabilities",
        "maker_taker_probability_source",
        "latency_ms",
        "latency_source",
        "paper_fill_latency_ms",
        "fill_latency_ms",
        "execution_latency_ms",
        "simulated_latency_ms",
        "partial_fill_count",
        "partial_fills",
        "fill_count",
        "all_partial_fills",
        "partial_fill_plan",
        "mark_index_divergence_bps",
        "mark_index_divergence",
        "mark_index_source",
        "mark_index_available_at",
        "mark_price",
        "index_price",
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
    _ensure_paper_rare_event_stress_fields(allocation)
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
        "target_notional_usdt",
        "target_quantity",
        "allocated_margin_usd",
        "recommended_leverage",
        "effective_leverage",
        "recommended_margin_mode",
        "stop_distance_bps",
        "liquidation_price_estimate",
        "liquidation_buffer_bps",
        "pre_entry_stress_tests",
        "rare_event_stress_suite",
        "rare_event_stress_status",
        "rare_event_stress_missing_inputs",
        "rare_event_required_liquidation_buffer_bps",
        "modeled_999_adverse_move_bps",
        "execution_uncertainty_bps",
        "correlation_stress_bps",
        "maintenance_margin_uncertainty_bps",
        "expected_fees_usd",
        "expected_slippage_usd",
        "expected_funding_usd",
        "expected_net_pnl_usd",
        "expected_shortfall_usd",
        "hedge_budget_usd",
        "hedge_parent_id",
        "hedge_child_id",
        "hedge_intent",
        "hedge_ratio",
        "hedge_expected_shortfall_reduction_usd",
        "expected_shortfall_before",
        "expected_shortfall_after",
        "maximum_duration",
        "unwind_plan",
        "hedge_cost_usd",
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
    if quantity is None and notional is not None and price is not None and price > 0:
        quantity = abs(notional / price)
    elif notional is None and quantity is not None and price is not None and price > 0:
        notional = abs(quantity * price)
    if quantity is not None:
        intent["quantity"] = abs(float(quantity))
    if notional is not None:
        intent["notional"] = abs(float(notional))
        intent["notional_usdt"] = abs(float(notional))
    missing_fields = _missing_adaptive_allocation_fields(allocation)
    if missing_fields:
        intent["paper_sizing_source"] = "V2_ADAPTIVE_ALLOCATOR_INCOMPLETE_ATTRIBUTION"
        intent["paper_sizing_complete"] = False
        intent["paper_allocation_block_reason"] = ADAPTIVE_ALLOCATION_ATTRIBUTION_BLOCK_REASON
        intent["paper_allocation_missing_fields"] = missing_fields
        return
    intent["paper_sizing_source"] = PAPER_SIZING_SOURCE_ADAPTIVE
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
    fee_schedule_context: dict[str, Any] | None = None,
):
    from v2.backend.app.services.adaptive_capital_allocator import AllocationInput

    symbol = str(intent.get("symbol") or "").upper()
    thesis_timeframe = _paper_thesis_timeframe(intent, signal, prediction)
    if thesis_timeframe is None:
        intent["timeframe_attribution_status"] = "MISSING_THESIS_TIMEFRAME"
        intent["timeframe_attribution_rejection_reason"] = MISSING_THESIS_TIMEFRAME_BLOCK_REASON
    else:
        intent["timeframe_attribution_status"] = "EXPLICIT_THESIS_TIMEFRAME"
        intent["thesis_timeframe"] = thesis_timeframe
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
        spread_captured_at = market_microstructure.get("entry_spread_captured_at") or _utc_iso()
        intent["entry_spread_captured_at"] = spread_captured_at
        model_decision_time = _first_present(
            intent.get("entry_feature_decision_time"),
            intent.get("decision_time"),
            intent.get("generated_at"),
            intent.get("generated_utc"),
            market_microstructure.get("entry_spread_decision_time"),
        )
        if model_decision_time is not None:
            intent["entry_spread_decision_time"] = model_decision_time
            intent.setdefault("model_decision_time", model_decision_time)
        paper_admission_decision_time = _first_present(
            intent.get("paper_admission_decision_time"),
            intent.get("runtime_cost_capture_decision_time"),
            spread_captured_at,
        )
        if paper_admission_decision_time is not None:
            intent["paper_admission_decision_time"] = paper_admission_decision_time
            intent["runtime_cost_capture_decision_time"] = paper_admission_decision_time
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
    readonly_fee_bps, readonly_fee_source = _fee_bps_from_readonly_schedule(
        fee_schedule_context,
    )
    if fee_bps is None:
        if readonly_fee_bps is not None:
            fee_bps = readonly_fee_bps
            fee_source = readonly_fee_source
            intent["fee_bps_readonly_schedule"] = True
            intent["fee_bps_configured_schedule"] = False
        else:
            # Use the configured paper fee schedule when no explicit/read-only
            # venue or account fee evidence is available.
            fee_bps = _configured_paper_fee_bps()
            fee_source = PAPER_CONFIGURED_FEE_SCHEDULE_SOURCE
            intent["fee_bps_readonly_schedule"] = False
            intent["fee_bps_configured_schedule"] = True
        intent["fee_bps"] = fee_bps
        intent["fee_bps_source"] = fee_source
        intent["fee_bps_fallback"] = False
        intent["fee_bps_for_allocator"] = fee_bps
        intent["fee_bps_unavailable_reason"] = None
    else:
        intent["fee_bps"] = fee_bps
        intent["fee_bps_source"] = fee_source
        intent["fee_bps_fallback"] = False
        intent["fee_bps_configured_schedule"] = False
        intent["fee_bps_readonly_schedule"] = False
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
        "timeframe": str(thesis_timeframe or UNKNOWN_THESIS_TIMEFRAME),
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
    from v2.backend.app.services.paper_trade_management.exits import PaperExitConfig
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
    _write_paper_runtime_heartbeat(
        r,
        started_at=started,
        cycle_state="RUNNING_CYCLE",
    )
    continuous_edge_guardian_gate = _read_continuous_edge_guardian_gate(r)
    continuous_edge_guardian_status = _read_json_key(
        r,
        CONTINUOUS_EDGE_GUARDIAN_STATUS_REDIS_KEY,
    )
    paper_only_label_collection_priority_index = (
        _read_paper_only_label_collection_priority_index()
    )
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
        paper_thesis_timeframe = _paper_thesis_timeframe(s, prediction)
        missing_thesis_timeframe = paper_thesis_timeframe in (None, "")
        paper_signal_adaptive_stale_policy = _paper_signal_adaptive_stale_policy(
            s,
            prediction,
        )
        paper_signal_temporal_rejection_reasons = _paper_signal_temporal_rejection_reasons(
            signal=s,
            prediction=prediction,
            now=runtime_now,
            stale_policy=paper_signal_adaptive_stale_policy,
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
            "paper_signal_static_stale_seconds": paper_signal_adaptive_stale_policy[
                "static_operator_max_seconds"
            ],
            "paper_signal_adaptive_stale_seconds": paper_signal_adaptive_stale_policy[
                "adaptive_stale_seconds"
            ],
            "paper_signal_adaptive_stale_policy": paper_signal_adaptive_stale_policy,
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
            "timeframe": paper_thesis_timeframe,
            "thesis_timeframe": paper_thesis_timeframe,
            "timeframe_attribution_status": (
                "MISSING_THESIS_TIMEFRAME"
                if missing_thesis_timeframe
                else "EXPLICIT_THESIS_TIMEFRAME"
            ),
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
            "paper_signal_static_stale_seconds": paper_signal_adaptive_stale_policy[
                "static_operator_max_seconds"
            ],
            "paper_signal_adaptive_stale_seconds": paper_signal_adaptive_stale_policy[
                "adaptive_stale_seconds"
            ],
            "paper_signal_adaptive_stale_policy": paper_signal_adaptive_stale_policy,
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
        if missing_thesis_timeframe:
            intent["timeframe_attribution_rejection_reason"] = MISSING_THESIS_TIMEFRAME_BLOCK_REASON
            intent["paper_fill_block_reason"] = MISSING_THESIS_TIMEFRAME_BLOCK_REASON
            intent["paper_fill_gate_block_reasons"] = sorted(set(
                list(intent.get("paper_fill_gate_block_reasons") or [])
                + [MISSING_THESIS_TIMEFRAME_BLOCK_REASON]
            ))
            intent["local_block_reasons"] = sorted(set(
                list(intent.get("local_block_reasons") or [])
                + [f"timeframe_attribution:{MISSING_THESIS_TIMEFRAME_BLOCK_REASON}"]
            ))
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
            timeframe=paper_thesis_timeframe,
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
                snapshot_evidence.setdefault("timeframe", paper_thesis_timeframe)
                intent["entry_feature_snapshot"] = snapshot_evidence
        else:
            intent["entry_feature_unavailable_reason"] = entry_feature_snapshot.get(
                "unavailable_reason"
            )
        prediction_for_entry = prediction
        if entry_features and not isinstance(prediction.get("features"), dict):
            prediction_for_entry = dict(prediction)
            prediction_for_entry["features"] = entry_features
        one_minute_result = _paper_standalone_1m_eligibility_gate(
            symbol=symbol,
            thesis_timeframe=paper_thesis_timeframe,
            side=str(side),
            intent=intent,
            signal=s,
            prediction=prediction_for_entry,
            feature_snapshot=entry_feature_snapshot,
            risk=risk_decisions[-1] if risk_decisions else None,
            strategy_router=strategy_router,
            paper_only_label_collection_priority_index=(
                paper_only_label_collection_priority_index
            ),
        )
        if risk_decisions:
            risk_decisions[-1]["paper_standalone_1m_eligibility"] = one_minute_result
            risk_decisions[-1]["paper_standalone_1m_eligibility_blockers"] = list(
                one_minute_result.get("blockers") or []
            )
        _apply_paper_standalone_1m_gate(intent, one_minute_result)
        reentry_dedup_result = _paper_reentry_dedup_gate(
            _paper_reentry_source_rows(existing_ledger),
            _paper_reentry_dedup_candidate_row(
                symbol=symbol,
                thesis_timeframe=paper_thesis_timeframe,
                side=str(side),
                intent=intent,
                signal=s,
                prediction=prediction_for_entry,
                feature_snapshot=entry_feature_snapshot,
                risk=risk_decisions[-1] if risk_decisions else None,
                strategy_router=strategy_router,
            ),
        )
        if risk_decisions:
            risk_decisions[-1]["paper_reentry_dedup_gate"] = reentry_dedup_result
            risk_decisions[-1]["paper_reentry_dedup_blockers"] = list(
                reentry_dedup_result.get("blockers") or []
            )
        _apply_paper_reentry_dedup_gate(intent, reentry_dedup_result)
        market_microstructure = _read_v2_orderbook_microstructure(r, symbol)
        long_short_evidence = _read_v2_long_short_ratio_evidence(r, symbol)
        _attach_long_short_ratio_context(intent, long_short_evidence)
        fee_schedule_context = _read_readonly_fee_schedule_context(
            r,
            symbol=symbol,
        )
        allocation_input = _build_allocation_input(
            intent=intent,
            signal=s,
            prediction=prediction_for_entry,
            portfolio_context=portfolio_context,
            symbol_exposures=symbol_exposures,
            total_exposure=total_exposure,
            market_microstructure=market_microstructure,
            correlation_contexts_by_symbol=correlation_contexts_by_symbol,
            fee_schedule_context=fee_schedule_context,
        )
        allocation = allocate_paper_candidate(allocation_input)
        allocation_payload = allocation.to_payload()
        _attach_paper_sizing(intent, allocation_payload)
        mark_index_evidence = _read_v2_mark_index_evidence(r, symbol)
        _attach_depth_price_impact_evidence(intent, market_microstructure)
        _attach_paper_execution_evidence(
            intent,
            mark_index_evidence,
        )
        _attach_runtime_cost_capture_contract(
            intent,
            market_microstructure,
            signal=s,
            prediction=prediction_for_entry,
        )
        _attach_paper_allocation_decision_context(intent, allocation_payload)
        _attach_trainer_feedback_entry_context(
            intent=intent,
            prediction=prediction_for_entry,
            strategy_router=strategy_router,
            allocation=allocation_payload,
            portfolio_context=portfolio_context,
        )
        _attach_paper_only_label_collection_priority(
            intent=intent,
            allocation=allocation_payload,
            priority_index=paper_only_label_collection_priority_index,
        )
        intent["paper_fill_ledger_evidence_required_at"] = "POST_PAPER_FILL_SIZING"
        _apply_strategy_size_multiplier(intent, _coerce_float(strategy_router["size_multiplier"]))
        if intent.get("strategy_size_multiplier_applied") is not None:
            for field in DEPTH_PRICE_IMPACT_EVIDENCE_FIELDS:
                intent.pop(field, None)
            _attach_depth_price_impact_evidence(intent, market_microstructure)
            _attach_paper_execution_evidence(
                intent,
                mark_index_evidence,
            )
            _attach_runtime_cost_capture_contract(
                intent,
                market_microstructure,
                signal=s,
                prediction=prediction_for_entry,
            )
            _attach_paper_allocation_decision_context(intent, allocation_payload)
        policy_owner_reasons = _paper_policy_owner_open_rejection_reasons(intent)
        runtime_market_evidence_rejection_reasons = sorted(set(
            _paper_runtime_market_evidence_rejection_reasons(
                intent,
                require_fill_ledger=False,
            )
        ))
        intent["paper_pre_fill_market_evidence_rejection_reasons"] = sorted(set(
            runtime_market_evidence_rejection_reasons + policy_owner_reasons
        ))
        intent["paper_runtime_market_evidence_rejection_reasons"] = runtime_market_evidence_rejection_reasons
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
        one_minute_strict_local_gate_allowed = (
            one_minute_result["allowed"]
            and one_minute_result.get("paper_only_label_collection_priority_allowed") is not True
        )
        local_trade_gates_pass = (
            _eg["allowed"]
            and pre["allowed"]
            and not fee_gate.blocked
            and not churn.blocked
            and integrity_gate["allowed"]
            and strategy_trade_allowed
            and strategy_mode_guard.get("allowed") is True
            and one_minute_strict_local_gate_allowed
            and reentry_dedup_result["allowed"]
            and not missing_thesis_timeframe
            and not paper_signal_temporal_rejection_reasons
            and not runtime_market_evidence_rejection_reasons
        )
        exploration_trade_gates_pass = (
            pre["allowed"]
            and not fee_gate.blocked
            and not churn.blocked
            and integrity_gate["allowed"]
            and one_minute_result["allowed"]
            and reentry_dedup_result["allowed"]
            and not missing_thesis_timeframe
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
            continuous_edge_guardian_gate=continuous_edge_guardian_gate,
        )
        _apply_paper_tier_classification(
            intent=intent,
            allocation=allocation_payload,
            classification=tier_classification,
        )
        non_executable_shadow = _shadow_observation_from_blocked_directional_candidate(
            intent=intent,
            signal=s,
            integrity_gate=integrity_gate,
            observation_source="NON_EXECUTABLE_PAPER_TIER_PRE_BLOCK",
            observation_reason=intent.get("paper_opportunity_tier_reason"),
        )
        if non_executable_shadow is not None:
            shadow_observations.append(non_executable_shadow)
        if _block_non_executable_paper_tier(
            intent=intent,
            allocation=allocation_payload,
        ):
            blocked.append(intent)
            continue
        if intent.get("paper_opportunity_tier") == PAPER_TIER_B_GRADE_EXPLORATION:
            _apply_b_grade_exploration_budget_cap(
                intent=intent,
                allocation=allocation_payload,
                risk_budget_fraction_of_normal_adaptive=tier_classification.get(
                    "risk_budget_fraction_of_normal_adaptive"
                ),
            )
            _attach_paper_sizing(intent, allocation_payload)
            for field in DEPTH_PRICE_IMPACT_EVIDENCE_FIELDS:
                intent.pop(field, None)
            _attach_depth_price_impact_evidence(intent, market_microstructure)
            _attach_paper_execution_evidence(intent, mark_index_evidence)
            _attach_runtime_cost_capture_contract(
                intent,
                market_microstructure,
                signal=s,
                prediction=prediction_for_entry,
            )
            _attach_paper_allocation_decision_context(intent, allocation_payload)
        post_fill_policy_owner_reasons = _paper_policy_owner_open_rejection_reasons(intent)
        post_fill_market_evidence_rejection_reasons = sorted(set(
            _paper_runtime_market_evidence_rejection_reasons(
                intent,
                require_fill_ledger=True,
            )
        ))
        intent["paper_post_fill_market_evidence_rejection_reasons"] = sorted(set(
            post_fill_market_evidence_rejection_reasons + post_fill_policy_owner_reasons
        ))
        intent["paper_runtime_market_evidence_rejection_reasons"] = post_fill_market_evidence_rejection_reasons
        if post_fill_market_evidence_rejection_reasons:
            intent["paper_fill_block_reason"] = (
                intent.get("paper_fill_block_reason") or PAPER_RUNTIME_EVIDENCE_BLOCK_REASON
            )
            intent["paper_fill_gate_block_reasons"] = sorted(set(
                list(intent.get("paper_fill_gate_block_reasons") or [])
                + post_fill_market_evidence_rejection_reasons
            ))
            intent["local_block_reasons"] = sorted(set(
                list(intent.get("local_block_reasons") or [])
                + [
                    f"post_fill_market_evidence:{reason}"
                    for reason in post_fill_market_evidence_rejection_reasons
                ]
            ))
            blocked.append(intent)
            continue
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
            # not a fill. Clean directional candidates are also mirrored
            # to shadow_observations for no-trade outcome analysis.
            local_gate_shadow = _shadow_observation_from_blocked_directional_candidate(
                intent=intent,
                signal=s,
                integrity_gate=integrity_gate,
                observation_source="LOCAL_PAPER_TRADE_GATES_FAILED",
                observation_reason=";".join(str(r) for r in intent.get("local_block_reasons") or [])
                or "LOCAL_PAPER_TRADE_GATES_FAILED",
            )
            if local_gate_shadow is not None:
                shadow_observations.append(local_gate_shadow)
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
    accepted_for_ledger = _normalize_paper_owner_attribution_rows(accepted_for_ledger)
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
            exit_config=PaperExitConfig(
                static_stop_loss_enabled=False,
                static_take_profit_enabled=False,
                static_profit_lock_enabled=False,
                static_profit_bank_enabled=False,
                static_max_hold_enabled=False,
            ),
            disable_trailing_on_negative_runtime_expectancy=True,
            trailing_expectancy_evidence_policy_version=PAPER_EXIT_POLICY_VERSION,
        ),
    )
    lifecycle_blocked = list(lifecycle_result["blocked_entries"])
    if lifecycle_blocked:
        blocked.extend(lifecycle_blocked)
    current_accepted_ids = {_accepted_fill_identity(row) for row in accepted}
    accepted_for_ledger = _normalize_paper_owner_attribution_rows(
        list(lifecycle_result["accepted_open_fills"])
    )
    accepted = [
        row
        for row in accepted_for_ledger
        if _accepted_fill_identity(row) in current_accepted_ids
    ]
    current_cycle_shadow_observations = list(shadow_observations)
    persisted_shadow_observations = _merge_shadow_observation_history(
        _read_json_list_key(r, f"{V2_REDIS_PREFIX}paper:shadow_observations"),
        current_cycle_shadow_observations,
        now_utc=_utc_iso(),
    )
    strategy_router_report = summarize_strategy_router_performance(
        accepted_rows=accepted_for_ledger,
        blocked_rows=blocked,
        shadow_rows=current_cycle_shadow_observations,
        held_rows=held_by_gate_intents,
    )
    allocation_rows = _current_cycle_candidate_allocation_rows(
        intents=intents,
        historical_accepted_rows=accepted_for_ledger,
        lifecycle_blocked_rows=lifecycle_blocked,
    )
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
    runtime_admission_rows = blocked + current_cycle_shadow_observations
    paper_runtime_admission_status = {
        "status": "ACTIVE",
        "paper_only": True,
        "intents_built": len(intents),
        "accepted_count": len(accepted),
        "persistent_accepted_fill_count": len(accepted_for_ledger),
        "blocked_count": len(blocked),
        "shadow_observation_count": len(current_cycle_shadow_observations),
        "persistent_shadow_observation_count": len(persisted_shadow_observations),
        "shadow_observation_history_max_rows": SHADOW_OBSERVATION_HISTORY_MAX_ROWS,
        "shadow_observation_history_ttl_seconds": SHADOW_OBSERVATION_HISTORY_TTL_SECONDS,
        "paper_fill_block_reason_counts": _count_values(blocked, "paper_fill_block_reason"),
        "paper_signal_temporal_rejection_counts": _count_list_values(
            runtime_admission_rows,
            "paper_signal_temporal_rejection_reasons",
        ),
        "paper_runtime_market_evidence_rejection_counts": _count_list_values(
            runtime_admission_rows,
            "paper_runtime_market_evidence_rejection_reasons",
        ),
        "paper_pre_fill_market_evidence_rejection_counts": _count_list_values(
            runtime_admission_rows,
            "paper_pre_fill_market_evidence_rejection_reasons",
        ),
        "paper_post_fill_market_evidence_rejection_counts": _count_list_values(
            runtime_admission_rows,
            "paper_post_fill_market_evidence_rejection_reasons",
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
    paper_runtime_cost_capture_status = _paper_runtime_cost_capture_summary(intents)
    paper_exploration_tier_status = _paper_exploration_tier_status(
        accepted_rows=accepted_for_ledger,
        current_accepted_rows=accepted,
        blocked_rows=blocked,
        shadow_rows=current_cycle_shadow_observations,
        held_rows=held_by_gate_intents,
    )
    paper_owner_attribution_status = _paper_owner_attribution_status(
        accepted_for_ledger,
        current_accepted_rows=accepted,
        current_runtime_rows=intents,
    )
    paper_audit_entry_gate_status = {
        "guard": PAPER_AUDIT_ENTRY_GATE_NAME,
        "enabled": True,
        "paper_only": True,
        "timeframe_policy": PAPER_AUDIT_TIMEFRAME_POLICY,
        "deprecated_static_blocked_entry_timeframes": sorted(
            PAPER_AUDIT_DEPRECATED_STATIC_BLOCKED_ENTRY_TIMEFRAMES
        ),
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
    entry_context_by_fill_id = _entry_feedback_context_by_fill_id(accepted_for_ledger)
    closes, paper_closed_outcome_entry_context_backfill_status = (
        _paper_backfill_closed_outcome_entry_context_rows(
            closes,
            entry_context_by_fill_id=entry_context_by_fill_id,
            row_kind="closed_trades",
        )
    )
    outcome_labels, paper_outcome_label_entry_context_backfill_status = (
        _paper_backfill_closed_outcome_entry_context_rows(
            outcome_labels,
            entry_context_by_fill_id=entry_context_by_fill_id,
            row_kind="outcome_labels",
        )
    )
    paper_b_grade_canary_supply_status = _paper_b_grade_canary_supply_status(
        intents,
        accepted_rows=accepted_for_ledger,
        open_position_rows=open_positions,
        closed_rows=closes,
    )
    paper_a_grade_gate_burndown_status = _paper_a_grade_gate_burndown_status(
        intents,
        accepted_rows=accepted_for_ledger,
        open_position_rows=open_positions,
        closed_rows=closes,
        guardian_gate=continuous_edge_guardian_gate,
        guardian_status=continuous_edge_guardian_status,
        b_grade_canary_supply_status=paper_b_grade_canary_supply_status,
    )
    paper_adaptive_threshold_runtime_status = _paper_adaptive_threshold_runtime_status(
        intents,
    )
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
    paper_b_grade_model_quality_status = _paper_b_grade_model_quality_status(
        trainer_feedback_consumable_rows
    )
    trainer_cuda_metrics = (
        _read_json_key(r, "v2:trainer:hybrid_cuda:metrics") if r is not None else {}
    )
    paper_trainer_model_quality_runtime_status = (
        _paper_trainer_model_quality_runtime_status(
            paper_b_grade_model_quality_status,
            trainer_cuda_metrics,
        )
    )
    paper_b_grade_bucket_promotion_readiness_status = (
        _paper_b_grade_bucket_promotion_readiness_status(
            paper_b_grade_model_quality_status
        )
    )
    paper_forward_canary_closed_outcome_archive_status = (
        _paper_forward_canary_closed_outcome_archive_status(closes)
    )
    paper_forward_canary_cutover_marker = _read_paper_forward_canary_cutover_marker()
    paper_forward_canary_cutover_completed_at = _first_present(
        paper_forward_canary_cutover_marker.get("cutover_completed_at"),
        paper_forward_canary_cutover_marker.get("controlled_one_shot_finished_at"),
    )
    paper_forward_canary_evidence_status = _paper_forward_canary_evidence_status(
        closed_rows=paper_forward_canary_closed_outcome_archive_status["closed_outcomes"],
        accepted_rows=accepted_for_ledger,
        cutover_completed_at=paper_forward_canary_cutover_completed_at,
    )
    if paper_forward_canary_cutover_marker:
        paper_forward_canary_evidence_status["cutover_marker_schema_version"] = (
            paper_forward_canary_cutover_marker.get("schema_version")
        )
        paper_forward_canary_evidence_status["cutover_marker_one_shot_completed"] = (
            paper_forward_canary_cutover_marker.get("one_shot_completed") is True
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
    accepted_state_rows = _compact_rows_for_state(accepted_for_ledger)
    current_accepted_state_rows = _compact_rows_for_state(accepted)
    blocked_state_sample = _sample_rows(_compact_rows_for_state(blocked))
    shadow_state_sample = _sample_rows(_compact_rows_for_state(current_cycle_shadow_observations))
    persistent_shadow_state_sample = _sample_rows(
        _compact_rows_for_state(persisted_shadow_observations)
    )
    held_state_sample = _sample_rows(_compact_rows_for_state(held_by_gate_intents))
    close_state_sample = _sample_rows(_compact_rows_for_state(closes))
    outcome_state_sample = _sample_rows(_compact_rows_for_state(outcome_labels))
    feedback_state_sample = _sample_rows(_compact_rows_for_state(trainer_feedback_consumable_rows))
    feedback_quarantine_state_sample = _sample_rows(
        _compact_rows_for_state(trainer_feedback_quarantine_rows)
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
            "shadow_observation_count": len(current_cycle_shadow_observations),
            "persistent_shadow_observation_count": len(persisted_shadow_observations),
            "shadow_observation_history_max_rows": SHADOW_OBSERVATION_HISTORY_MAX_ROWS,
            "shadow_observation_history_ttl_seconds": SHADOW_OBSERVATION_HISTORY_TTL_SECONDS,
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
            "candidate_id": CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
            "policy_id": CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
            "paper_policy_owner": PAPER_POLICY_OWNER_CHALLENGER_V2,
            "policy_fingerprint": CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
            "selector_policy_fingerprint": OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
            "frozen_selector_fingerprint": OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
            "model_source": CHALLENGER_V2_MODEL_SOURCE,
            "current_allowed_paper_owner": PAPER_POLICY_OWNER_CHALLENGER_V2,
            "paper_owner_attribution_status": paper_owner_attribution_status,
            "held_position_count": len(held_by_gate_intents),
            "redis_ledger_compacted": True,
            "redis_ledger_sample_limit": PAPER_REDIS_LEDGER_ROW_SAMPLE_LIMIT,
            "accepted_fill_state_source": str(PAPER_ACCEPTED_FILLS_STATE_PATH),
            "accepted_fill_state_row_count": len(accepted_state_rows),
            "accepted_intents": _sample_rows(accepted_state_rows),
            "accepted": _sample_rows(accepted_state_rows),
            "current_cycle_accepted": current_accepted_state_rows,
            "blocked": blocked_state_sample,
            "held_by_paper_fill_gate": held_state_sample,
            "shadow_observations": shadow_state_sample,
            "persistent_shadow_observations": persistent_shadow_state_sample,
            "closes": close_state_sample,
            "closed_trades": close_state_sample,
            "outcome_labels": outcome_state_sample,
            "trainer_feedback_outcomes": feedback_state_sample,
            "trainer_feedback_outcomes_quarantine": feedback_quarantine_state_sample,
            "paper_b_grade_model_quality_status": paper_b_grade_model_quality_status,
            "paper_trainer_model_quality_runtime_status": (
                paper_trainer_model_quality_runtime_status
            ),
            "paper_b_grade_bucket_promotion_readiness_status": (
                paper_b_grade_bucket_promotion_readiness_status
            ),
            "paper_forward_canary_evidence_status": paper_forward_canary_evidence_status,
            "paper_forward_canary_closed_outcome_archive_status": (
                paper_forward_canary_closed_outcome_archive_status
            ),
            "paper_closed_outcome_entry_context_backfill_status": (
                paper_closed_outcome_entry_context_backfill_status
            ),
            "paper_outcome_label_entry_context_backfill_status": (
                paper_outcome_label_entry_context_backfill_status
            ),
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
            "paper_b_grade_canary_supply_status": paper_b_grade_canary_supply_status,
            "paper_a_grade_gate_burndown_status": paper_a_grade_gate_burndown_status,
            "paper_adaptive_threshold_runtime_status": paper_adaptive_threshold_runtime_status,
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
        # Write closed_trades before ledger so that the portfolio state publisher
        # always sees the full standalone list before the ledger sample — this
        # eliminates the G08 race where ledger sample has a new close but the
        # standalone list hasn't been updated yet, causing a transient sum gap.
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:closed_trades",
            json.dumps(closes),
            ex=PAPER_TRAINING_EVIDENCE_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:closed_trades")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:positions",
            json.dumps(open_positions),
            ex=PAPER_TRAINING_EVIDENCE_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:positions")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:ledger",
            json.dumps(ledger_payload),
            ex=PAPER_TRAINING_EVIDENCE_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:ledger")
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
            json.dumps(_compact_status_for_redis({
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
                "paper_runtime_cost_capture_status": paper_runtime_cost_capture_status,
                "paper_exploration_tier_status": paper_exploration_tier_status,
                "paper_b_grade_canary_supply_status": paper_b_grade_canary_supply_status,
                "paper_a_grade_gate_burndown_status": paper_a_grade_gate_burndown_status,
                "paper_adaptive_threshold_runtime_status": paper_adaptive_threshold_runtime_status,
                "paper_forward_canary_evidence_status": paper_forward_canary_evidence_status,
                "paper_forward_canary_closed_outcome_archive_status": (
                    paper_forward_canary_closed_outcome_archive_status
                ),
                "paper_closed_outcome_entry_context_backfill_status": (
                    paper_closed_outcome_entry_context_backfill_status
                ),
                "paper_outcome_label_entry_context_backfill_status": (
                    paper_outcome_label_entry_context_backfill_status
                ),
                "paper_owner_attribution_status": paper_owner_attribution_status,
                "paper_b_grade_bucket_promotion_readiness_status": (
                    paper_b_grade_bucket_promotion_readiness_status
                ),
                "paper_trainer_model_quality_runtime_status": (
                    paper_trainer_model_quality_runtime_status
                ),
                "paper_audit_entry_gate_status": paper_audit_entry_gate_status,
                "paper_adaptive_sizing_runtime_status": paper_adaptive_sizing_runtime_status,
                "risk_envelope_dynamic_budget_status": risk_envelope_dynamic_budget_status,
                "cycle_state": "COMPLETED_CYCLE",
                "heartbeat_ttl_seconds": PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS,
                **_paper_runtime_owner_identity(),
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
                "writes_legacy_redis": False,
                "trade_lifecycle_guard_status": {
                    "shared_guard_available": True,
                    "paper_path_using_lifecycle_controls": True,
                    "live_path_changed": False,
                },
                "generated_utc": _utc_iso(),
            })),
            ex=PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:trade_management:status")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:b_grade_canary_supply_status",
            json.dumps(paper_b_grade_canary_supply_status),
            ex=PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:b_grade_canary_supply_status")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:a_grade_gate_burndown_status",
            json.dumps(paper_a_grade_gate_burndown_status),
            ex=PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:a_grade_gate_burndown_status")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:adaptive_threshold_runtime_status",
            json.dumps(paper_adaptive_threshold_runtime_status),
            ex=PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:adaptive_threshold_runtime_status")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:trainer_model_quality_runtime_status",
            json.dumps(paper_trainer_model_quality_runtime_status),
            ex=PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS,
        ):
            keys_written.append(
                f"{V2_REDIS_PREFIX}paper:trainer_model_quality_runtime_status"
            )
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:forward_canary_evidence_status",
            json.dumps(paper_forward_canary_evidence_status),
            ex=PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}paper:forward_canary_evidence_status")
        if _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:shadow_observations",
            json.dumps(persisted_shadow_observations),
            ex=SHADOW_OBSERVATION_HISTORY_TTL_SECONDS,
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
        "heartbeat_generated_at": _utc_iso(),
        "cycle_state": "COMPLETED_CYCLE",
        "heartbeat_ttl_seconds": PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS,
        "paper_signals_seen": len(signals),
        "intents_built": len(intents),
        "intents_accepted": len(accepted),
        "persistent_accepted_fill_count": len(accepted_for_ledger),
        "accepted_fill_state_row_count": len(accepted_state_rows),
        "accepted_fill_state_path": str(PAPER_ACCEPTED_FILLS_STATE_PATH),
        "lifecycle_state_path": str(PAPER_LIFECYCLE_STATE_PATH),
        "redis_ledger_compacted": True,
        "redis_ledger_sample_limit": PAPER_REDIS_LEDGER_ROW_SAMPLE_LIMIT,
        "intents_blocked": len(blocked),
        "intents_held_by_paper_fill_gate": len(held_by_gate_intents),
        "shadow_observation_count": len(current_cycle_shadow_observations),
        "persistent_shadow_observation_count": len(persisted_shadow_observations),
        "shadow_observation_history_max_rows": SHADOW_OBSERVATION_HISTORY_MAX_ROWS,
        "shadow_observation_history_ttl_seconds": SHADOW_OBSERVATION_HISTORY_TTL_SECONDS,
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
        "candidate_id": CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "policy_id": CHALLENGER_V2_ACTIVE_CUDA_CANDIDATE_ID,
        "paper_policy_owner": PAPER_POLICY_OWNER_CHALLENGER_V2,
        "policy_fingerprint": CHALLENGER_V2_ACTIVE_CUDA_POLICY_FINGERPRINT,
        "selector_policy_fingerprint": OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
        "frozen_selector_fingerprint": OUT_OF_SAMPLE_REVERIFY_SELECTOR_POLICY_FINGERPRINT,
        "model_source": CHALLENGER_V2_MODEL_SOURCE,
        "current_allowed_paper_owner": PAPER_POLICY_OWNER_CHALLENGER_V2,
        "paper_owner_attribution_status": paper_owner_attribution_status,
        "paper_b_grade_model_quality_status": (
            paper_b_grade_model_quality_status if r is not None else {}
        ),
        "paper_trainer_model_quality_runtime_status": (
            paper_trainer_model_quality_runtime_status if r is not None else {}
        ),
        "paper_b_grade_bucket_promotion_readiness_status": (
            paper_b_grade_bucket_promotion_readiness_status if r is not None else {}
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
        "paper_runtime_cost_capture_status": paper_runtime_cost_capture_status,
        "paper_exploration_tier_status": paper_exploration_tier_status,
        "paper_b_grade_canary_supply_status": paper_b_grade_canary_supply_status,
        "paper_a_grade_gate_burndown_status": paper_a_grade_gate_burndown_status,
        "paper_adaptive_threshold_runtime_status": paper_adaptive_threshold_runtime_status,
        "paper_forward_canary_evidence_status": paper_forward_canary_evidence_status,
        "paper_forward_canary_closed_outcome_archive_status": (
            paper_forward_canary_closed_outcome_archive_status
        ),
        "paper_closed_outcome_entry_context_backfill_status": (
            paper_closed_outcome_entry_context_backfill_status
        ),
        "paper_outcome_label_entry_context_backfill_status": (
            paper_outcome_label_entry_context_backfill_status
        ),
        "paper_owner_attribution_status": paper_owner_attribution_status,
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
        "shadow_observations": current_cycle_shadow_observations,
        "persistent_shadow_observations": persisted_shadow_observations,
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
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "writes_legacy_redis": False,
    }
    if r is not None:
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}paper:heartbeat",
            json.dumps(_compact_status_for_redis(status)),
            ex=PAPER_RUNTIME_HEARTBEAT_TTL_SECONDS,
        )
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
                "accepted_fill_state_schema_version": "v2_compact_accepted_fill_state_v1",
                "accepted_fill_state_compacted": True,
                "accepted_fill_state_row_count": len(accepted_state_rows),
                "accepted_fills": accepted_state_rows,
                "current_cycle_accepted": current_accepted_state_rows,
                "paper_owner_attribution_status": paper_owner_attribution_status,
                "omitted_fields": sorted(COMPACT_ACCEPTED_FILL_OMITTED_FIELDS),
                "generated_utc": _utc_iso(),
                "paper_only": True,
                "places_real_order": False,
                "writes_legacy_redis": False,
            },
            PAPER_ACCEPTED_FILLS_STATE_PATH,
        )
        write_payload(
            {
                "paper_lifecycle_state_schema_version": "v2_paper_lifecycle_state_v1",
                "accepted_fills": accepted_state_rows,
                "current_cycle_accepted": current_accepted_state_rows,
                "open_positions": open_positions,
                "positions_by_symbol": lifecycle_result["positions_by_symbol"],
                "closed_trades": closes,
                "closes": closes,
                "outcome_labels": outcome_labels,
                "trainer_feedback_outcomes": trainer_feedback_consumable_rows,
                "trainer_feedback_outcomes_quarantine": trainer_feedback_quarantine_rows,
                "accepted_count": len(accepted_state_rows),
                "current_cycle_accepted_count": len(current_accepted_state_rows),
                "open_position_count": len(open_positions),
                "closed_trade_count": len(closes),
                "outcome_label_count": len(outcome_labels),
                "trainer_feedback_row_count": len(trainer_feedback_consumable_rows),
                "trainer_feedback_quarantined_row_count": len(trainer_feedback_quarantine_rows),
                "paper_owner_attribution_status": paper_owner_attribution_status,
                "paper_closed_outcome_entry_context_backfill_status": (
                    paper_closed_outcome_entry_context_backfill_status
                ),
                "paper_outcome_label_entry_context_backfill_status": (
                    paper_outcome_label_entry_context_backfill_status
                ),
                "generated_utc": _utc_iso(),
                "paper_only": True,
                "places_real_order": False,
                "writes_legacy_redis": False,
            },
            PAPER_LIFECYCLE_STATE_PATH,
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
                "paper_b_grade_model_quality_status": paper_b_grade_model_quality_status,
                "paper_b_grade_bucket_promotion_readiness_status": (
                    paper_b_grade_bucket_promotion_readiness_status
                ),
                "paper_trainer_model_quality_runtime_status": (
                    paper_trainer_model_quality_runtime_status
                ),
                "generated_utc": _utc_iso(),
                "paper_only": True,
                "places_real_order": False,
            },
            TRADE_MANAGEMENT_PUBLIC_DIR / "trainer_feedback_outcomes.json",
        )
        write_payload(
            paper_b_grade_model_quality_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_b_grade_model_quality_status.json",
        )
        write_payload(
            paper_trainer_model_quality_runtime_status,
            PAPER_TRAINER_MODEL_QUALITY_RUNTIME_STATUS_PATH,
        )
        write_payload(
            paper_b_grade_bucket_promotion_readiness_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_b_grade_bucket_promotion_readiness_status.json",
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
            paper_b_grade_canary_supply_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_b_grade_canary_supply_status.json",
        )
        write_payload(
            paper_a_grade_gate_burndown_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_a_grade_gate_burndown_status.json",
        )
        write_payload(
            paper_adaptive_threshold_runtime_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_adaptive_threshold_runtime_status.json",
        )
        write_payload(
            paper_forward_canary_evidence_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_forward_canary_evidence_status.json",
        )
        write_payload(
            paper_forward_canary_closed_outcome_archive_status,
            PAPER_FORWARD_CANARY_CLOSED_OUTCOME_ARCHIVE_PATH,
        )
        write_payload(
            paper_closed_outcome_entry_context_backfill_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_closed_outcome_entry_context_backfill_status.json",
        )
        write_payload(
            paper_outcome_label_entry_context_backfill_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_outcome_label_entry_context_backfill_status.json",
        )
        write_payload(
            paper_owner_attribution_status,
            TRADE_MANAGEMENT_PUBLIC_DIR / "paper_owner_attribution_status.json",
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
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


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
