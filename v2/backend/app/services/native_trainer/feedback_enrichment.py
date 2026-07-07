from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from v2.backend.app.services.paper_trade_management.position_validity import (
    validate_closed_trade,
)


REQUIRED_FEEDBACK_FIELDS: tuple[str, ...] = (
    "prediction_id",
    "signal_id",
    "feature_snapshot_id",
    "market_state_id",
    "timeframe",
    "symbol",
    "action",
    "entry_price",
    "exit_price",
    "realized_pnl",
    "strategy_id",
    "strategy_family",
    "strategy_subtype",
    "hedge_state",
    "hedge_reason",
    "entry_reason",
    "exit_reason",
    "realized_pnl_bps",
    "hold_time_seconds",
    "market_regime_at_entry",
    "market_regime_at_exit",
    "liquidity_zone_context",
    "liquidation_distance_context",
    "microstructure_context",
    "oi_funding_context",
    "public_intel_context",
    "liquidity_context",
    "major_move_context",
    "market_regime",
    "future_window_label_source",
    "drawdown_at_entry",
)

REQUIRED_TRUST_ENVELOPE_FIELDS: tuple[str, ...] = (
    "prediction_id",
    "signal_id",
    "decision_id",
    "feature_snapshot_id",
    "mtf_snapshot_id",
    "feature_cutoff",
    "decision_time",
    "available_at",
    "symbol",
    "timeframe",
    "selected_action",
    "model_version",
    "checkpoint_id",
    "source_hashes",
)

MISSING_FEEDBACK_CLASS_BY_FIELD: dict[str, str] = {
    "prediction_id": "missing_prediction_id",
    "signal_id": "missing_signal_id",
    "strategy_id": "missing_strategy_id",
    "entry_price": "missing_entry_price",
    "exit_price": "missing_exit_price",
    "realized_pnl": "missing_realized_pnl",
    "realized_pnl_bps": "missing_realized_pnl",
    "exit_reason": "missing_exit_reason",
    "feature_snapshot_id": "missing_feature_snapshot_id",
    "market_state_id": "missing_market_state_id",
    "timeframe": "missing_timeframe",
    "symbol": "missing_symbol",
    "action": "missing_action",
    "hedge_state": "missing_hedge_state",
    "liquidity_context": "missing_liquidity_context",
    "liquidity_zone_context": "missing_liquidity_context",
    "major_move_context": "missing_major_move_context",
}

AUDIT_QUALITY_FEEDBACK_FIELDS: tuple[str, ...] = (
    "actual_observed_spread_entry_bps",
    "actual_observed_spread_exit_bps",
    "observed_bid_ask_spread_bps",
    "bid_ask_spread_bps",
    "entry_spread_source",
    "exit_spread_source",
    "expected_slippage_bps",
    "expected_slippage_usd",
    "expected_slippage_source",
    "expected_slippage_modeled",
    "bid_depth_usd",
    "ask_depth_usd",
    "orderbook_depth_usd",
    "entry_orderbook_depth_usd",
    "entry_orderbook_depth_side",
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
    "realized_slippage_bps",
    "realized_slippage_usd",
    "implementation_shortfall_usd",
    "squeeze_evidence_source",
    "squeeze_evidence_components",
    "squeeze_evidence_unavailable_reason",
    "mfe_bps",
    "mfe_usd",
    "mae_bps",
    "mae_usd",
    "intra_trade_high_price",
    "intra_trade_low_price",
    "trailing_activation_price",
    "trailing_activation_time",
    "trailing_stop_price",
    "trailing_stop_history",
)

PAPER_EXECUTION_EVIDENCE_FIELDS: tuple[str, ...] = (
    "maker_probability",
    "taker_probability",
    "maker_taker_probability",
    "maker_taker_probabilities",
    "maker_taker_probability_source",
    "decision_latency_ms",
    "latency_ms",
    "latency_source",
    "paper_fill_latency_ms",
    "fill_latency_ms",
    "execution_latency_ms",
    "simulated_latency_ms",
    "selector_policy_fingerprint",
    "frozen_selector_fingerprint",
    "candidate_selected_before_outcome",
    "candidate_selected_after_outcome",
    "post_outcome_candidate_selection",
    "future_labels_used_as_features",
    "paper_opportunity_tier",
    "paper_opportunity_tier_reason",
    "explicit_paper_opportunity_tier",
    "paper_fill_allowed_source",
    "strict_paper_fill_allowed_upstream",
    "calibration_label_purpose",
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
    "observed_bid",
    "observed_ask",
    "observed_spread_bps",
    "order_size",
    "order_size_usd",
    "top_book_bid_depth_usd",
    "top_book_ask_depth_usd",
    "depth_derived_price_impact_bps",
    "maker_taker_assumption",
    "maker_taker_probability_detail",
    "fee_schedule",
    "fee_bps",
    "fee_bps_source",
    "fee_bps_configured_schedule",
    "holding_period_funding_bps",
    "holding_period_funding_source",
    "latency_reserve_bps",
    "latency_reserve_source",
    "partial_fill_estimate",
    "partial_fill_probability",
    "partial_fill_adjustment_bps",
    "execution_probability",
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
)

STATIC_SPREAD_PLACEHOLDER_SOURCES: frozenset[str] = frozenset(
    {
        "V2_ALLOCATOR",
        "V2_ENTRY_MICROSTRUCTURE_CONTEXT",
        "V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
        "V2_PREDICTION_OR_SIGNAL_MICROSTRUCTURE",
    }
)

DEFAULT_CONTEXT_SOURCES: frozenset[str] = frozenset(
    {
        "V2_FEEDBACK_ENRICHMENT_DEFAULT_LIQUIDITY",
        "V2_FEEDBACK_ENRICHMENT_DEFAULT_LIQUIDATION",
        "V2_FEEDBACK_ENRICHMENT_DEFAULT_MICROSTRUCTURE",
        "V2_FEEDBACK_ENRICHMENT_DEFAULT_OI_FUNDING",
        "V2_FEEDBACK_ENRICHMENT_DEFAULT_PUBLIC_INTEL",
    }
)

PREMIUM_CONTEXT_SOURCE = "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS"

_LIQUIDITY_CONTEXT_VALUE_FIELDS: tuple[str, ...] = (
    "liquidity_score",
    "orderbook_depth_usd",
    "bid_depth_usd",
    "ask_depth_usd",
    "depth_imbalance",
    "whale_bid_wall_notional_usd",
    "whale_ask_wall_notional_usd",
    "nearest_bid_wall_distance_bps",
    "nearest_ask_wall_distance_bps",
)

_LIQUIDATION_CONTEXT_VALUE_FIELDS: tuple[str, ...] = (
    "nearest_liquidation_level_above",
    "nearest_liquidation_level_below",
    "liquidation_long_distance_pct",
    "liquidation_short_distance_pct",
    "liquidation_sweep_target_long_distance_bps",
    "liquidation_sweep_target_short_distance_bps",
    "liquidation_cascade_risk",
    "liquidation_pressure_direction",
    "liquidation_levels_count_long",
    "liquidation_levels_count_short",
    "liquidation_zones_count_long",
    "liquidation_zones_count_short",
    "liquidation_long_strength",
    "liquidation_short_strength",
    "liquidation_volume",
)

_MICROSTRUCTURE_CONTEXT_VALUE_FIELDS: tuple[str, ...] = (
    "bid_ask_spread_bps",
    "spread_bps",
    "ob_spread_bps",
    "micro_price",
    "orderbook_imbalance",
    "depth_imbalance",
    "bid_depth_usd",
    "ask_depth_usd",
    "orderbook_depth_usd",
)

_OI_FUNDING_CONTEXT_VALUE_FIELDS: tuple[str, ...] = (
    "funding_rate",
    "expected_funding_bps",
    "funding_bps",
    "open_interest",
    "oi_change_pct",
    "open_interest_change_pct",
    "long_short_ratio",
    "long_account_ratio",
    "short_account_ratio",
)

_PUBLIC_INTEL_CONTEXT_VALUE_FIELDS: tuple[str, ...] = (
    "public_intel_score",
    "news_attention_score",
    "news_sentiment_score",
    "sentiment_score",
    "fear_greed_score",
    "market_breadth_score",
    "social_momentum_score",
    "social_volume_velocity",
)

_PREMIUM_CONTEXT_REQUIREMENTS: tuple[tuple[str, tuple[str, ...], str, bool], ...] = (
    ("liquidity_context", _LIQUIDITY_CONTEXT_VALUE_FIELDS, "LIQUIDITY", True),
    ("liquidity_zone_context", _LIQUIDITY_CONTEXT_VALUE_FIELDS, "LIQUIDITY_ZONE", True),
    ("liquidation_distance_context", _LIQUIDATION_CONTEXT_VALUE_FIELDS, "LIQUIDATION", True),
    ("liquidation_context", _LIQUIDATION_CONTEXT_VALUE_FIELDS, "LIQUIDATION", True),
    ("microstructure_context", _MICROSTRUCTURE_CONTEXT_VALUE_FIELDS, "MICROSTRUCTURE", True),
    ("oi_funding_context", _OI_FUNDING_CONTEXT_VALUE_FIELDS, "OI_FUNDING", True),
    ("public_intel_context", _PUBLIC_INTEL_CONTEXT_VALUE_FIELDS, "PUBLIC_INTEL", False),
)


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _default_context(source: str) -> dict[str, Any]:
    return {"source": source, "status": "not_provided"}


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _context_source(context: dict[str, Any]) -> str:
    return str(context.get("source") or "").strip()


def _context_is_default_placeholder(context: Any) -> bool:
    if not isinstance(context, dict) or not context:
        return True
    source = _context_source(context)
    if source in DEFAULT_CONTEXT_SOURCES:
        return True
    return str(context.get("status") or "").strip().lower() in {"not_provided", "missing_silent_default"}


def _context_has_real_values(context: Any, value_fields: tuple[str, ...]) -> bool:
    if not isinstance(context, dict):
        return False
    for field in value_fields:
        if _coerce_float(context.get(field)) is not None:
            return True
    return False


def _context_has_explicit_missing_mask(context: Any) -> bool:
    if not isinstance(context, dict):
        return False
    if context.get("missing_mask_applied") is True:
        return True
    for field in ("missing_feature_names", "missing_features", "unavailable_reason", "missing_reason"):
        value = context.get(field)
        if value not in (None, "", [], {}):
            return True
    return False


def _snapshot_features(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    features = snapshot.get("features")
    return features if isinstance(features, dict) else {}


def _snapshot_missing_features(snapshot: Any, *tokens: str) -> list[str]:
    if not isinstance(snapshot, dict):
        return []
    raw_missing = snapshot.get("missing_feature_flags")
    if not isinstance(raw_missing, list):
        return []
    lowered = tuple(token.lower() for token in tokens)
    return [
        str(item)
        for item in raw_missing
        if any(token in str(item).lower() for token in lowered)
    ]


def _snapshot_context(
    *,
    snapshot: Any,
    fields: tuple[str, ...],
    context_type: str,
    missing_tokens: tuple[str, ...],
) -> dict[str, Any]:
    features = _snapshot_features(snapshot)
    values = {field: features.get(field) for field in fields if features.get(field) is not None}
    missing = _snapshot_missing_features(snapshot, *missing_tokens)
    if not values and not missing:
        missing = list(fields)
    context: dict[str, Any] = {
        "source": PREMIUM_CONTEXT_SOURCE,
        "context_type": context_type,
        "feature_snapshot_id": snapshot.get("feature_snapshot_id") if isinstance(snapshot, dict) else None,
        "available_at": snapshot.get("available_at") if isinstance(snapshot, dict) else None,
        "feature_cutoff": snapshot.get("feature_cutoff") if isinstance(snapshot, dict) else None,
        "feature_freshness_state": snapshot.get("feature_freshness_state") if isinstance(snapshot, dict) else None,
        "source_categories": snapshot.get("categories_present") if isinstance(snapshot, dict) else None,
        "external_sources_present": snapshot.get("external_v2_sources_present") if isinstance(snapshot, dict) else None,
        "missing_feature_names": missing,
        "missing_mask_applied": bool(missing),
    }
    context.update(values)
    if values:
        context["status"] = "provided_by_entry_feature_snapshot"
    else:
        context["status"] = "explicitly_missing_from_entry_feature_snapshot" if missing else "not_provided"
        context.setdefault("unavailable_reason", f"MISSING_{context_type}_FEATURES")
    return {key: value for key, value in context.items() if value not in (None, "", [], {})}


def _premium_contexts_from_entry_snapshot(snapshot: Any) -> dict[str, dict[str, Any]]:
    features = _snapshot_features(snapshot)
    if not features:
        return {}
    liquidity = _snapshot_context(
        snapshot=snapshot,
        fields=_LIQUIDITY_CONTEXT_VALUE_FIELDS,
        context_type="LIQUIDITY",
        missing_tokens=("liquid", "depth", "wall", "orderbook"),
    )
    liquidation = _snapshot_context(
        snapshot=snapshot,
        fields=_LIQUIDATION_CONTEXT_VALUE_FIELDS,
        context_type="LIQUIDATION",
        missing_tokens=("liquidation", "liq"),
    )
    microstructure = _snapshot_context(
        snapshot=snapshot,
        fields=_MICROSTRUCTURE_CONTEXT_VALUE_FIELDS,
        context_type="MICROSTRUCTURE",
        missing_tokens=("microstructure", "orderbook", "spread", "depth"),
    )
    oi_funding = _snapshot_context(
        snapshot=snapshot,
        fields=_OI_FUNDING_CONTEXT_VALUE_FIELDS,
        context_type="OI_FUNDING",
        missing_tokens=("funding", "open_interest", "long_short", "oi_"),
    )
    public_intel = _snapshot_context(
        snapshot=snapshot,
        fields=_PUBLIC_INTEL_CONTEXT_VALUE_FIELDS,
        context_type="PUBLIC_INTEL",
        missing_tokens=("public", "news", "sentiment", "breadth", "social", "fear_greed"),
    )
    return {
        "liquidity_context": liquidity,
        "liquidity_zone_context": liquidity,
        "liquidation_distance_context": liquidation,
        "liquidation_context": liquidation,
        "microstructure_context": microstructure,
        "oi_funding_context": oi_funding,
        "public_intel_context": public_intel,
    }


def _merge_premium_contexts_from_snapshot(row: dict[str, Any]) -> None:
    snapshot = _first_present(
        row.get("entry_feature_snapshot") if isinstance(row.get("entry_feature_snapshot"), dict) else None,
        row.get("feature_snapshot") if isinstance(row.get("feature_snapshot"), dict) else None,
    )
    contexts = _premium_contexts_from_entry_snapshot(snapshot)
    if not contexts:
        row["premium_ingestor_context_status"] = "ENTRY_FEATURE_SNAPSHOT_CONTEXT_UNAVAILABLE"
        return
    sources: dict[str, str] = {}
    missing_contexts: list[str] = []
    for field, value_fields, _label, _required_real_values in _PREMIUM_CONTEXT_REQUIREMENTS:
        candidate = contexts.get(field)
        current = row.get(field)
        if _context_is_default_placeholder(current) or not _context_has_real_values(current, value_fields):
            if candidate:
                row[field] = candidate
        context = row.get(field)
        if _context_has_real_values(context, value_fields):
            sources[field] = _context_source(context)
        elif _context_has_explicit_missing_mask(context):
            sources[field] = f"{_context_source(context)}:explicit_missing_mask"
        else:
            missing_contexts.append(field)
    row["premium_ingestor_context_sources"] = sources
    row["premium_ingestor_missing_contexts"] = sorted(set(missing_contexts))
    row["premium_ingestor_context_status"] = (
        "PREMIUM_CONTEXT_READY"
        if not missing_contexts
        else "PREMIUM_CONTEXT_PARTIAL_WITH_EXPLICIT_MASKS"
    )
    liquidation = row.get("liquidation_distance_context")
    row["liquidation_engine_context_status"] = (
        "LIQUIDATION_ENGINE_CONTEXT_READY"
        if _context_has_real_values(liquidation, _LIQUIDATION_CONTEXT_VALUE_FIELDS)
        else "LIQUIDATION_ENGINE_CONTEXT_MISSING"
    )


def _premium_ingestor_rejection_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field, value_fields, label, required_real_values in _PREMIUM_CONTEXT_REQUIREMENTS:
        context = row.get(field)
        if _context_is_default_placeholder(context):
            reasons.append(f"MISSING_PREMIUM_INGESTOR_{label}_CONTEXT")
            continue
        has_values = _context_has_real_values(context, value_fields)
        if has_values:
            continue
        if required_real_values:
            reasons.append(f"MISSING_PREMIUM_INGESTOR_{label}_VALUES")
        elif not _context_has_explicit_missing_mask(context):
            reasons.append(f"MISSING_PREMIUM_INGESTOR_{label}_MASK")
    return sorted(set(reasons))


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = _coerce_float(value)
        if parsed is not None:
            return parsed
    return None


def _parse_utc(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            parsed_epoch = float(value)
        except (TypeError, ValueError):
            return None
        if parsed_epoch <= 0 or parsed_epoch != parsed_epoch:
            return None
        if parsed_epoch > 10_000_000_000:
            parsed_epoch /= 1000.0
        try:
            return datetime.fromtimestamp(parsed_epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_epoch = float(text)
        except (TypeError, ValueError):
            return None
        if parsed_epoch <= 0 or parsed_epoch != parsed_epoch:
            return None
        if parsed_epoch > 10_000_000_000:
            parsed_epoch /= 1000.0
        try:
            return datetime.fromtimestamp(parsed_epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _directional_outcome(*, entry_price: Any, exit_price: Any) -> str:
    entry = _coerce_float(entry_price)
    exit_ = _coerce_float(exit_price)
    if entry is None or exit_ is None:
        return "FLAT"
    if exit_ > entry:
        return "UP"
    if exit_ < entry:
        return "DOWN"
    return "FLAT"


def _trade_outcome(realized_net_pnl_usd: Any) -> str:
    value = _coerce_float(realized_net_pnl_usd)
    if value is None or abs(value) <= 1e-12:
        return "BREAKEVEN"
    return "WIN" if value > 0.0 else "LOSS"


def _action_was_profitable(*, selected_action: Any, directional_outcome: str, realized_net_pnl_usd: Any) -> bool:
    realized = _coerce_float(realized_net_pnl_usd)
    if realized is not None:
        return realized > 0.0
    action = str(selected_action or "").strip().lower()
    if action == "long":
        return directional_outcome == "UP"
    if action == "short":
        return directional_outcome == "DOWN"
    return False


_REPLAY_LABEL_SOURCES: frozenset[str] = frozenset({
    "closed_candle_replay_label",
    "replay_label",
    "future_window_replay_label",
    "REPLAY",
})

_MODEL_PROVENANCE_FIELDS: frozenset[str] = frozenset({
    "decision_id",
    "mtf_snapshot_id",
    "feature_cutoff",
    "decision_time",
    "available_at",
    "checkpoint_id",
    "model_version",
    "source_hashes",
    "selected_action",
})


def _trust_envelope_rejection_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    # Replay-sourced rows (e.g. major-move replay feedback) don't go through the
    # live model pipeline, so model-provenance fields are not applicable to them.
    is_replay_row = str(row.get("future_window_label_source") or "").strip() in _REPLAY_LABEL_SOURCES
    for field in REQUIRED_TRUST_ENVELOPE_FIELDS:
        if is_replay_row and field in _MODEL_PROVENANCE_FIELDS:
            continue
        value = row.get(field)
        if value in (None, "") or (field == "source_hashes" and (not isinstance(value, dict) or not value)):
            reasons.append(f"MISSING_TRUST_{field.upper()}")
    decision_time = _parse_utc(row.get("decision_time"))
    available_at = _parse_utc(row.get("available_at"))
    feature_cutoff = _parse_utc(row.get("feature_cutoff"))
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if row.get("trust_reconstructed") is True and not row.get("trust_source_ids"):
        reasons.append("TRUST_RECONSTRUCTED_WITHOUT_SOURCE_IDS")
    for reason in row.get("trust_reconstruction_rejection_reasons") or []:
        reasons.append(f"TRUST_RECONSTRUCTION:{reason}")
    if not is_replay_row and row.get("prediction_id") and not row.get("mtf_snapshot_id") and not row.get("feature_cutoff"):
        reasons.append("PREDICTION_ID_ALONE_NOT_TRUST_EVIDENCE")
    return sorted(set(reasons))


def _spread_evidence(row: dict[str, Any]) -> tuple[float | None, str | None]:
    micro = _mapping(row.get("microstructure_context"))
    candidates = (
        (row.get("actual_observed_spread_entry_bps"), row.get("entry_spread_source")),
        (row.get("actual_observed_spread_exit_bps"), row.get("exit_spread_source")),
        (
            row.get("observed_bid_ask_spread_bps"),
            _first_present(row.get("exit_spread_source"), row.get("entry_spread_source"), micro.get("source")),
        ),
        (
            row.get("bid_ask_spread_bps"),
            _first_present(row.get("exit_spread_source"), row.get("entry_spread_source"), micro.get("source")),
        ),
        (micro.get("bid_ask_spread_bps"), micro.get("source")),
        (micro.get("spread_bps"), micro.get("source")),
        (micro.get("ob_spread_bps"), micro.get("source")),
    )
    parsed_candidates: list[tuple[float, str | None]] = []
    for spread_value, source_value in candidates:
        spread = _coerce_float(spread_value)
        if spread is None:
            continue
        source = str(source_value) if source_value else None
        parsed_candidates.append((spread, source))
    for spread, source in parsed_candidates:
        if _spread_source_is_observed(source):
            return spread, source
    return parsed_candidates[0] if parsed_candidates else (None, None)


def _spread_source_is_observed(source: str | None) -> bool:
    if not source:
        return False
    normalized = source.upper()
    if normalized in STATIC_SPREAD_PLACEHOLDER_SOURCES:
        return False
    return any(marker in normalized for marker in ("ORDERBOOK", "OBSERVED", "TOP_OF_BOOK"))


def _lifecycle_or_no_trade_strategy_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in (
        "strategy",
        "strategy_id",
        "strategy_family",
        "strategy_subtype",
        "strategy_selected_mode",
        "strategy_router_selected_mode",
        "entry_reason",
    ):
        normalized = str(row.get(field) or "").strip().lower()
        if normalized in {"no_trade", "no_trade_mode", "no_trade_expert"}:
            reasons.append(f"{field}=NO_TRADE")
        elif any(token in normalized for token in ("reduce", "close", "exit")):
            reasons.append(f"{field}=LIFECYCLE_ACTION")

    label_values: list[Any] = []
    for field in (
        "strategy_regime_labels",
        "market_regime_at_entry",
        "market_regime",
        "market_regime_at_exit",
    ):
        raw = row.get(field)
        if isinstance(raw, str):
            label_values.extend(item.strip() for item in raw.split(",") if item.strip())
        elif isinstance(raw, (list, tuple, set)):
            label_values.extend(raw)
    tokens = {str(value).strip().upper() for value in label_values if str(value).strip()}
    if "NO_TRADE" in tokens:
        reasons.append("strategy_regime_labels_include_NO_TRADE")
    return sorted(set(reasons))


def audit_quality_rejection_reasons(row: dict[str, Any]) -> list[str]:
    """Return reasons a closed-trade feedback row must stay out of training."""

    reasons: list[str] = []
    if _lifecycle_or_no_trade_strategy_reasons(row):
        reasons.append("LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE")

    squeeze_score = _coerce_float(row.get("squeeze_evidence_score"))
    if squeeze_score is None or not _first_present(row.get("squeeze_evidence_source")):
        reasons.append("MISSING_SOURCED_SQUEEZE_EVIDENCE")

    spread_bps, spread_source = _spread_evidence(row)
    if spread_bps is None:
        reasons.append("MISSING_OBSERVED_SPREAD_EVIDENCE")
    elif not _spread_source_is_observed(spread_source):
        reasons.append("UNSOURCED_OBSERVED_SPREAD_EVIDENCE")
    elif abs(spread_bps - 2.0) <= 1e-9 and str(spread_source).upper() in STATIC_SPREAD_PLACEHOLDER_SOURCES:
        reasons.append("STATIC_2BPS_SPREAD_PLACEHOLDER")

    if _coerce_float(row.get("expected_slippage_bps")) is None:
        reasons.append("MISSING_EXPECTED_SLIPPAGE_BPS")
    if not _first_present(row.get("expected_slippage_source")):
        reasons.append("MISSING_EXPECTED_SLIPPAGE_SOURCE")
    if _coerce_float(row.get("implementation_shortfall_usd")) is None:
        reasons.append("MISSING_IMPLEMENTATION_SHORTFALL")

    for field in ("mfe_bps", "mae_bps", "intra_trade_high_price", "intra_trade_low_price"):
        if _coerce_float(row.get(field)) is None:
            reasons.append(f"MISSING_{field.upper()}")

    exit_reason = str(_first_present(row.get("exit_reason"), row.get("close_reason")) or "").upper()
    if "TRAILING" in exit_reason and not row.get("trailing_stop_history"):
        reasons.append("MISSING_TRAILING_STOP_HISTORY_FOR_TRAILING_EXIT")
    reasons.extend(_premium_ingestor_rejection_reasons(row))
    return reasons


def _major_move_context(*, close_event: dict[str, Any], outcome_label: dict[str, Any]) -> dict[str, Any]:
    signal_id = _first_present(close_event.get("major_move_signal_id"), outcome_label.get("major_move_signal_id"))
    evidence_score = _first_present(
        close_event.get("squeeze_evidence_score"),
        outcome_label.get("squeeze_evidence_score"),
        close_event.get("major_move_evidence_score"),
        outcome_label.get("major_move_evidence_score"),
    )
    return {
        "source": "V2_PAPER_MAJOR_MOVE_CONTEXT",
        "major_move_signal_id": signal_id,
        "squeeze_evidence_score": evidence_score,
        "regime": _first_present(
            close_event.get("market_regime_at_entry"),
            outcome_label.get("market_regime_at_entry"),
            close_event.get("market_regime"),
            outcome_label.get("market_regime"),
        ),
        "status": "provided" if signal_id or evidence_score is not None else "not_major_move_trade",
    }


def _is_pre_remediation_stale_lineage(row: dict[str, Any], missing: list[str]) -> bool:
    if set(missing) != {"feature_snapshot_id"}:
        return False
    persistence_status = str(row.get("paper_fill_persistence_status") or "")
    if not (
        persistence_status.startswith("EXISTING_FILL_")
        or row.get("original_fill_utc")
    ):
        return False
    return bool(
        row.get("prediction_id")
        and row.get("signal_id")
        and row.get("market_state_id")
        and row.get("symbol")
        and row.get("timeframe")
    )


def build_strategy_hedge_exit_feedback(
    *,
    close_event: dict[str, Any],
    outcome_label: dict[str, Any],
) -> dict[str, Any]:
    liquidity_context = _first_present(
        close_event.get("liquidity_context"),
        outcome_label.get("liquidity_context"),
        close_event.get("liquidity_zone_context"),
        outcome_label.get("liquidity_zone_context"),
        _default_context("V2_FEEDBACK_ENRICHMENT_DEFAULT_LIQUIDITY"),
    )
    liquidation_context = _first_present(
        close_event.get("liquidation_context"),
        outcome_label.get("liquidation_context"),
        close_event.get("liquidation_distance_context"),
        outcome_label.get("liquidation_distance_context"),
        _default_context("V2_FEEDBACK_ENRICHMENT_DEFAULT_LIQUIDATION"),
    )
    microstructure_context = _first_present(
        close_event.get("microstructure_context"),
        outcome_label.get("microstructure_context"),
        _default_context("V2_FEEDBACK_ENRICHMENT_DEFAULT_MICROSTRUCTURE"),
    )
    oi_funding_context = _first_present(
        close_event.get("oi_funding_context"),
        outcome_label.get("oi_funding_context"),
        _default_context("V2_FEEDBACK_ENRICHMENT_DEFAULT_OI_FUNDING"),
    )
    public_intel_context = _first_present(
        close_event.get("public_intel_context"),
        outcome_label.get("public_intel_context"),
        _default_context("V2_FEEDBACK_ENRICHMENT_DEFAULT_PUBLIC_INTEL"),
    )
    market_regime = _first_present(
        close_event.get("market_regime"),
        outcome_label.get("market_regime"),
        close_event.get("market_regime_at_entry"),
        outcome_label.get("market_regime_at_entry"),
        close_event.get("market_regime_at_exit"),
        outcome_label.get("market_regime_at_exit"),
    )
    row: dict[str, Any] = {
        "trainer_feedback_source": "V2_PAPER_TRADE_MANAGEMENT_CLOSED_TRADE",
        "trainer_feedback_id": close_event.get("trainer_feedback_id") or outcome_label.get("trainer_feedback_id"),
        "outcome_label_id": close_event.get("outcome_label_id") or outcome_label.get("outcome_label_id"),
        "position_id": close_event.get("position_id") or outcome_label.get("position_id"),
        "symbol": close_event.get("symbol") or outcome_label.get("symbol"),
        "prediction_id": _first_present(
            close_event.get("prediction_id"),
            outcome_label.get("prediction_id"),
            close_event.get("entry_prediction_id"),
            outcome_label.get("entry_prediction_id"),
            close_event.get("source_prediction_id"),
            outcome_label.get("source_prediction_id"),
        ),
        "entry_prediction_id": _first_present(
            close_event.get("entry_prediction_id"),
            outcome_label.get("entry_prediction_id"),
            close_event.get("prediction_id"),
            outcome_label.get("prediction_id"),
        ),
        "exit_prediction_id": _first_present(close_event.get("exit_prediction_id"), outcome_label.get("exit_prediction_id")),
        "signal_id": _first_present(
            close_event.get("signal_id"),
            outcome_label.get("signal_id"),
            close_event.get("entry_signal_id"),
            outcome_label.get("entry_signal_id"),
            close_event.get("source_signal_id"),
            outcome_label.get("source_signal_id"),
        ),
        "entry_signal_id": _first_present(
            close_event.get("entry_signal_id"),
            outcome_label.get("entry_signal_id"),
            close_event.get("signal_id"),
            outcome_label.get("signal_id"),
        ),
        "exit_signal_id": _first_present(close_event.get("exit_signal_id"), outcome_label.get("exit_signal_id")),
        "feature_snapshot_id": _first_present(
            close_event.get("feature_snapshot_id"),
            outcome_label.get("feature_snapshot_id"),
            close_event.get("entry_feature_snapshot_id"),
            outcome_label.get("entry_feature_snapshot_id"),
        ),
        "entry_feature_snapshot_id": _first_present(
            close_event.get("entry_feature_snapshot_id"),
            outcome_label.get("entry_feature_snapshot_id"),
            close_event.get("feature_snapshot_id"),
            outcome_label.get("feature_snapshot_id"),
        ),
        "entry_feature_snapshot": _first_present(
            close_event.get("entry_feature_snapshot")
            if isinstance(close_event.get("entry_feature_snapshot"), dict)
            else None,
            outcome_label.get("entry_feature_snapshot")
            if isinstance(outcome_label.get("entry_feature_snapshot"), dict)
            else None,
            close_event.get("feature_snapshot")
            if isinstance(close_event.get("feature_snapshot"), dict)
            else None,
            outcome_label.get("feature_snapshot")
            if isinstance(outcome_label.get("feature_snapshot"), dict)
            else None,
        ),
        "market_state_id": _first_present(
            close_event.get("market_state_id"),
            outcome_label.get("market_state_id"),
            close_event.get("entry_market_state_id"),
            outcome_label.get("entry_market_state_id"),
        ),
        "entry_market_state_id": _first_present(
            close_event.get("entry_market_state_id"),
            outcome_label.get("entry_market_state_id"),
            close_event.get("market_state_id"),
            outcome_label.get("market_state_id"),
        ),
        "timeframe": _first_present(close_event.get("timeframe"), outcome_label.get("timeframe")),
        "action": _first_present(close_event.get("action"), outcome_label.get("action"), close_event.get("side"), outcome_label.get("side")),
        "selected_action": _first_present(
            close_event.get("selected_action"),
            outcome_label.get("selected_action"),
            close_event.get("action"),
            outcome_label.get("action"),
            close_event.get("side"),
            outcome_label.get("side"),
        ),
        "entry_price": _first_present(close_event.get("entry_price"), outcome_label.get("entry_price")),
        "exit_price": _first_present(close_event.get("exit_price"), outcome_label.get("exit_price")),
        "strategy_id": _first_present(close_event.get("strategy_id"), outcome_label.get("strategy_id")),
        "strategy_family": _first_present(close_event.get("strategy_family"), outcome_label.get("strategy_family")),
        "strategy_subtype": _first_present(
            close_event.get("strategy_subtype"),
            outcome_label.get("strategy_subtype"),
            close_event.get("strategy_selected_mode"),
            outcome_label.get("strategy_selected_mode"),
        ),
        "hedge_state": _first_present(close_event.get("hedge_state"), outcome_label.get("hedge_state"), "NO_HEDGE"),
        "hedge_reason": _first_present(
            close_event.get("hedge_reason"),
            outcome_label.get("hedge_reason"),
            "NO_HEDGE_CONTEXT",
        ),
        "entry_reason": _first_present(
            close_event.get("entry_reason"),
            outcome_label.get("entry_reason"),
            close_event.get("strategy_id"),
            outcome_label.get("strategy_id"),
        ),
        "exit_reason": _first_present(
            close_event.get("exit_reason"),
            close_event.get("close_reason"),
            outcome_label.get("exit_reason"),
        ),
        "realized_pnl_bps": _first_present(close_event.get("realized_pnl_bps"), outcome_label.get("realized_pnl_bps")),
        "realized_net_pnl_bps": _first_present(
            close_event.get("realized_net_pnl_bps"),
            outcome_label.get("realized_net_pnl_bps"),
            close_event.get("realized_after_cost_pnl_bps"),
            outcome_label.get("realized_after_cost_pnl_bps"),
        ),
        "realized_net_pnl_usd": _first_present(
            close_event.get("realized_net_pnl_usd"),
            outcome_label.get("realized_net_pnl_usd"),
            close_event.get("realized_pnl_usd"),
            outcome_label.get("realized_pnl_usd"),
            close_event.get("realized_pnl_usdt"),
            outcome_label.get("realized_pnl_usdt"),
        ),
        "realized_pnl": _first_present(
            close_event.get("realized_pnl"),
            outcome_label.get("realized_pnl"),
            close_event.get("realized_pnl_usd"),
            outcome_label.get("realized_pnl_usd"),
            close_event.get("realized_pnl_usdt"),
            outcome_label.get("realized_pnl_usdt"),
        ),
        "hold_time_seconds": _first_present(close_event.get("hold_time_seconds"), outcome_label.get("hold_time_seconds")),
        "holding_period": _first_present(
            close_event.get("holding_period"),
            outcome_label.get("holding_period"),
            close_event.get("hold_time_seconds"),
            outcome_label.get("hold_time_seconds"),
        ),
        "exit_time": _first_present(close_event.get("exit_time"), outcome_label.get("exit_time"), close_event.get("exit_price_utc")),
        "market_regime": market_regime,
        "market_regime_at_entry": _first_present(
            close_event.get("market_regime_at_entry"),
            outcome_label.get("market_regime_at_entry"),
            market_regime,
        ),
        "market_regime_at_exit": _first_present(
            close_event.get("market_regime_at_exit"),
            outcome_label.get("market_regime_at_exit"),
            market_regime,
        ),
        "liquidity_zone_context": _first_present(
            close_event.get("liquidity_zone_context"),
            outcome_label.get("liquidity_zone_context"),
            liquidity_context,
        ),
        "liquidity_context": liquidity_context,
        "liquidation_distance_context": _first_present(
            close_event.get("liquidation_distance_context"),
            outcome_label.get("liquidation_distance_context"),
            liquidation_context,
        ),
        "liquidation_context": liquidation_context,
        "microstructure_context": microstructure_context,
        "oi_funding_context": oi_funding_context,
        "public_intel_context": public_intel_context,
        "major_move_signal_id": _first_present(
            close_event.get("major_move_signal_id"),
            outcome_label.get("major_move_signal_id"),
        ),
        "squeeze_evidence_score": _first_present(
            close_event.get("squeeze_evidence_score"),
            outcome_label.get("squeeze_evidence_score"),
        ),
        "future_window_label_source": _first_present(
            close_event.get("future_window_label_source"),
            outcome_label.get("future_window_label_source"),
            "closed_trade_outcome",
        ),
        "drawdown_at_entry": _first_present(
            close_event.get("drawdown_at_entry"),
            outcome_label.get("drawdown_at_entry"),
            0.0,
        ),
        "paper_fill_persistence_status": _first_present(
            close_event.get("paper_fill_persistence_status"),
            outcome_label.get("paper_fill_persistence_status"),
        ),
        "original_fill_utc": _first_present(
            close_event.get("original_fill_utc"),
            outcome_label.get("original_fill_utc"),
        ),
        "fill_price_utc": _first_present(
            close_event.get("fill_price_utc"),
            outcome_label.get("fill_price_utc"),
        ),
        "decision_id": _first_present(close_event.get("decision_id"), outcome_label.get("decision_id")),
        "mtf_snapshot_id": _first_present(close_event.get("mtf_snapshot_id"), outcome_label.get("mtf_snapshot_id")),
        "feature_cutoff": _first_present(
            close_event.get("feature_cutoff"),
            outcome_label.get("feature_cutoff"),
            close_event.get("entry_feature_cutoff"),
            outcome_label.get("entry_feature_cutoff"),
        ),
        "decision_time": _first_present(
            close_event.get("decision_time"),
            outcome_label.get("decision_time"),
            close_event.get("entry_feature_decision_time"),
            outcome_label.get("entry_feature_decision_time"),
        ),
        "available_at": _first_present(
            close_event.get("available_at"),
            outcome_label.get("available_at"),
            close_event.get("entry_feature_available_at"),
            outcome_label.get("entry_feature_available_at"),
        ),
        "model_version": _first_present(
            close_event.get("model_version"),
            outcome_label.get("model_version"),
            close_event.get("model_source"),
            outcome_label.get("model_source"),
            close_event.get("model_id"),
            outcome_label.get("model_id"),
        ),
        "checkpoint_id": _first_present(close_event.get("checkpoint_id"), outcome_label.get("checkpoint_id")),
        "source_hashes": _first_present(
            close_event.get("source_hashes"),
            outcome_label.get("source_hashes"),
            {
                key: value
                for key, value in {
                    "feature_vector_hash": _first_present(
                        close_event.get("feature_vector_hash"),
                        outcome_label.get("feature_vector_hash"),
                        close_event.get("input_feature_hash"),
                        outcome_label.get("input_feature_hash"),
                    ),
                    "prediction_hash": _first_present(
                        close_event.get("prediction_hash"),
                        outcome_label.get("prediction_hash"),
                    ),
                    "source_lineage_hash": _first_present(
                        close_event.get("source_lineage_hash"),
                        outcome_label.get("source_lineage_hash"),
                    ),
                }.items()
                if value not in (None, "")
            },
        ),
        "confidence_raw": _first_present(
            close_event.get("confidence_raw"),
            outcome_label.get("confidence_raw"),
        ),
        "confidence_calibrated": _first_present(
            close_event.get("confidence_calibrated"),
            outcome_label.get("confidence_calibrated"),
        ),
        "selected_action_probability": _first_present(
            close_event.get("selected_action_probability"),
            outcome_label.get("selected_action_probability"),
        ),
        "expected_move_bps": _first_present(
            close_event.get("expected_move_bps"),
            outcome_label.get("expected_move_bps"),
        ),
        "expected_move_after_cost_bps": _first_present(
            close_event.get("expected_move_after_cost_bps"),
            outcome_label.get("expected_move_after_cost_bps"),
        ),
        "action_probabilities": _first_present(
            close_event.get("action_probabilities"),
            outcome_label.get("action_probabilities"),
        ),
        "policy_value": _first_present(
            close_event.get("policy_value"),
            outcome_label.get("policy_value"),
        ),
        "value_baseline": _first_present(
            close_event.get("value_baseline"),
            outcome_label.get("value_baseline"),
        ),
        "prediction_score_source": _first_present(
            close_event.get("prediction_score_source"),
            outcome_label.get("prediction_score_source"),
        ),
        "prediction_score_missing_reason": _first_present(
            close_event.get("prediction_score_missing_reason"),
            outcome_label.get("prediction_score_missing_reason"),
        ),
        "trust_reconstructed": _first_present(close_event.get("trust_reconstructed"), outcome_label.get("trust_reconstructed"), False),
        "trust_source_ids": _first_present(close_event.get("trust_source_ids"), outcome_label.get("trust_source_ids")),
        "trust_reconstruction_rejection_reasons": _first_present(
            close_event.get("trust_reconstruction_rejection_reasons"),
            outcome_label.get("trust_reconstruction_rejection_reasons"),
            [],
        ),
        "lineage_backfilled_from_prediction_id": _first_present(
            close_event.get("lineage_backfilled_from_prediction_id"),
            outcome_label.get("lineage_backfilled_from_prediction_id"),
        ),
        "source_quarantine_reason": _first_present(
            close_event.get("quarantine_reason"),
            outcome_label.get("quarantine_reason"),
            close_event.get("reason_if_untrusted"),
            outcome_label.get("reason_if_untrusted"),
        ),
        "source_quarantine_reasons": _first_present(
            close_event.get("quarantine_reasons"),
            outcome_label.get("quarantine_reasons"),
            close_event.get("quarantine_rejection_reasons"),
            outcome_label.get("quarantine_rejection_reasons"),
        ),
        "account_scope": _first_present(close_event.get("account_scope"), outcome_label.get("account_scope")),
        "position_validity_status": _first_present(
            close_event.get("position_validity_status"),
            outcome_label.get("position_validity_status"),
            close_event.get("validity_status"),
            outcome_label.get("validity_status"),
        ),
        "source_fill_ids": _first_present(
            close_event.get("source_fill_ids"),
            outcome_label.get("source_fill_ids"),
        ),
        "entry_fill_id": _first_present(
            close_event.get("entry_fill_id"),
            outcome_label.get("entry_fill_id"),
            close_event.get("fill_id"),
            outcome_label.get("fill_id"),
        ),
        "paper_only": True,
        "places_real_order": False,
    }
    for field in AUDIT_QUALITY_FEEDBACK_FIELDS:
        row[field] = _first_present(close_event.get(field), outcome_label.get(field))
    for field in PAPER_EXECUTION_EVIDENCE_FIELDS:
        row[field] = _first_present(close_event.get(field), outcome_label.get(field))
    if row.get("latency_ms") in (None, ""):
        row["latency_ms"] = _first_present(
            row.get("decision_latency_ms"),
            close_event.get("decision_latency_ms"),
            outcome_label.get("decision_latency_ms"),
        )
    latency_value = _first_present(row.get("latency_ms"), row.get("decision_latency_ms"))
    if latency_value not in (None, ""):
        for latency_field in (
            "paper_fill_latency_ms",
            "fill_latency_ms",
            "execution_latency_ms",
            "simulated_latency_ms",
        ):
            if row.get(latency_field) in (None, ""):
                row[latency_field] = latency_value
    _merge_premium_contexts_from_snapshot(row)
    row["major_move_context"] = _first_present(
        close_event.get("major_move_context"),
        outcome_label.get("major_move_context"),
        _major_move_context(close_event=close_event, outcome_label=outcome_label),
    )
    if row.get("realized_net_pnl_bps") in (None, ""):
        row["realized_net_pnl_bps"] = row.get("realized_pnl_bps")
    directional_outcome = _first_present(
        close_event.get("directional_outcome"),
        outcome_label.get("directional_outcome"),
        _directional_outcome(entry_price=row.get("entry_price"), exit_price=row.get("exit_price")),
    )
    trade_outcome = _first_present(
        close_event.get("trade_outcome"),
        outcome_label.get("trade_outcome"),
        _trade_outcome(row.get("realized_net_pnl_usd")),
    )
    row["directional_outcome"] = directional_outcome
    row["trade_outcome"] = trade_outcome
    row["action_was_profitable"] = _first_present(
        close_event.get("action_was_profitable"),
        outcome_label.get("action_was_profitable"),
        _action_was_profitable(
            selected_action=row.get("selected_action"),
            directional_outcome=str(directional_outcome),
            realized_net_pnl_usd=row.get("realized_net_pnl_usd"),
        ),
    )
    row["fees"] = _first_present(close_event.get("fees"), outcome_label.get("fees"), close_event.get("fees_usd"), outcome_label.get("fees_usd"))
    row["slippage"] = _first_present(close_event.get("slippage"), outcome_label.get("slippage"), close_event.get("realized_slippage_usd"), outcome_label.get("realized_slippage_usd"))
    row["funding"] = _first_present(close_event.get("funding"), outcome_label.get("funding"), close_event.get("funding_pnl_usd"), outcome_label.get("funding_pnl_usd"))
    row["MFE"] = _first_present(close_event.get("MFE"), outcome_label.get("MFE"), close_event.get("mfe_bps"), outcome_label.get("mfe_bps"))
    row["MAE"] = _first_present(close_event.get("MAE"), outcome_label.get("MAE"), close_event.get("mae_bps"), outcome_label.get("mae_bps"))
    row["outcome_targets"] = _first_present(
        close_event.get("outcome_targets"),
        outcome_label.get("outcome_targets"),
        {
            "realized_net_pnl_bps": row.get("realized_net_pnl_bps"),
            "realized_net_pnl_usd": row.get("realized_net_pnl_usd"),
            "directional_outcome": row.get("directional_outcome"),
            "trade_outcome": row.get("trade_outcome"),
            "selected_action": row.get("selected_action"),
            "action_was_profitable": row.get("action_was_profitable"),
            "holding_period": row.get("holding_period"),
            "fees": row.get("fees"),
            "slippage": row.get("slippage"),
            "funding": row.get("funding"),
            "MFE": row.get("MFE"),
            "MAE": row.get("MAE"),
            "exit_reason": row.get("exit_reason"),
        },
    )
    if not row.get("entry_feature_snapshot_id"):
        row["entry_feature_snapshot_id"] = row.get("feature_snapshot_id")
    missing = [field for field in REQUIRED_FEEDBACK_FIELDS if row.get(field) in (None, "")]
    missing_classes = sorted({MISSING_FEEDBACK_CLASS_BY_FIELD.get(field, "schema_mismatch") for field in missing})
    audit_quality_reasons = audit_quality_rejection_reasons(row)
    trust_reasons = _trust_envelope_rejection_reasons(row)
    closed_trade_validity = validate_closed_trade(row)
    closed_trade_reasons = list(closed_trade_validity.get("reasons") or [])
    audit_quality_classes = [f"audit_quality:{reason.lower()}" for reason in audit_quality_reasons]
    trust_classes = [f"trust:{reason.lower()}" for reason in trust_reasons]
    closed_trade_classes = [f"closed_trade_validity:{reason.lower()}" for reason in closed_trade_reasons]
    stale_lineage = _is_pre_remediation_stale_lineage(row, missing)
    if stale_lineage:
        missing_classes = ["stale_lineage"]
    if stale_lineage and not audit_quality_reasons and not trust_reasons:
        row["quarantine_non_critical"] = True
        row["non_critical_quarantine_reason"] = (
            "PRE_REMEDIATION_ACCEPTED_FILL_MISSING_ENTRY_FEATURE_SNAPSHOT_ID"
        )
    else:
        row["quarantine_non_critical"] = False
        row["non_critical_quarantine_reason"] = None
    row["feedback_schema_version"] = "strategy_hedge_exit_feedback_v1"
    row["trust_envelope_schema_version"] = "paper_feedback_trust_envelope_v1"
    row["audit_quality_contract_version"] = "paper_closed_trade_audit_quality_v1"
    row["audit_quality_rejection_reasons"] = audit_quality_reasons
    row["trust_envelope_rejection_reasons"] = trust_reasons
    row["closed_trade_validity_status"] = closed_trade_validity.get("status")
    row["closed_trade_validity_rejection_reasons"] = closed_trade_reasons
    row["trainer_consumable"] = (
        not missing
        and not audit_quality_reasons
        and not trust_reasons
        and not closed_trade_reasons
    )
    row["missing_feedback_fields"] = missing
    row["missing_trust_fields"] = [
        reason.removeprefix("MISSING_TRUST_").lower()
        for reason in trust_reasons
        if reason.startswith("MISSING_TRUST_")
    ]
    row["missing_feedback_classifications"] = sorted(
        set(missing_classes + audit_quality_classes + trust_classes + closed_trade_classes)
    )
    row["quarantine_reason"] = (
        "NONE"
        if not row["missing_feedback_classifications"]
        else (
            f"stale_lineage:{row['non_critical_quarantine_reason']}"
            if row.get("quarantine_non_critical") and not audit_quality_reasons
            else ",".join(row["missing_feedback_classifications"])
        )
    )
    apply_trainer_feedback_field_contract(row)
    return row


TRAINER_FEEDBACK_CONTRACT_FIELDS = (
    "paper_session_id",
    "prediction_id",
    "feature_snapshot_id",
    "mtf_snapshot_id",
    "feature_cutoff",
    "available_at",
    "decision_time",
    "side",
    "action",
    "strategy_id",
    "expected_move_after_cost_bps",
    "realized_pnl_bps",
    "realized_pnl_usd",
    "fees",
    "slippage",
    "funding",
    "mfe",
    "mae",
    "exit_reason",
    "outcome_label",
)


def apply_trainer_feedback_field_contract(row: dict[str, Any]) -> dict[str, Any]:
    """Guarantee the canonical trainer-consumable field names exist on a row.

    Values are aliases of evidence already carried by the row; no value is
    fabricated. Missing evidence stays None so contract checks can fail loudly.
    """
    action = row.get("action") or row.get("selected_action") or row.get("side")
    if row.get("side") in (None, ""):
        normalized = str(action or "").strip().upper()
        row["side"] = normalized if normalized in {"LONG", "SHORT"} else (normalized or None)
    if row.get("realized_pnl_usd") is None:
        row["realized_pnl_usd"] = _first_present(
            row.get("realized_net_pnl_usd"),
            row.get("realized_pnl_usdt"),
        )
    if row.get("mfe") is None:
        row["mfe"] = _first_present(row.get("MFE"), row.get("mfe_bps"))
    if row.get("mae") is None:
        row["mae"] = _first_present(row.get("MAE"), row.get("mae_bps"))
    if row.get("outcome_label") in (None, ""):
        row["outcome_label"] = _first_present(
            row.get("trade_outcome"),
            row.get("directional_outcome"),
            row.get("outcome_label_id"),
        )
    missing_contract_fields = [
        name for name in TRAINER_FEEDBACK_CONTRACT_FIELDS if row.get(name) in (None, "")
    ]
    row["trainer_feedback_contract_version"] = "trainer_feedback_field_contract_v1"
    row["trainer_feedback_contract_missing_fields"] = missing_contract_fields
    row["trainer_feedback_contract_complete"] = not missing_contract_fields
    return row


def feedback_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "trainer_feedback_rows": len(rows),
        "strategy_fields_present": all(row.get("strategy_id") and row.get("strategy_family") for row in rows),
        "hedge_fields_present": all(row.get("hedge_state") and row.get("hedge_reason") for row in rows),
        "exit_fields_present": all(row.get("exit_reason") for row in rows),
        "liquidity_fields_present": all(row.get("liquidity_zone_context") and row.get("liquidation_distance_context") for row in rows),
        "liquidity_context_present": all(row.get("liquidity_context") for row in rows),
        "microstructure_fields_present": all(row.get("microstructure_context") for row in rows),
        "oi_funding_fields_present": all(row.get("oi_funding_context") for row in rows),
        "public_intel_fields_present": all(row.get("public_intel_context") for row in rows),
        "future_window_label_fields_present": all(row.get("future_window_label_source") for row in rows),
        "major_move_fields_present": all(
            row.get("strategy_subtype")
            and row.get("entry_reason")
            and row.get("future_window_label_source")
            and row.get("major_move_context")
            for row in rows
        ),
        "missing_feedback_classification_counts": {
            classification: sum(
                1
                for row in rows
                if classification in (row.get("missing_feedback_classifications") or [])
            )
            for classification in sorted(
                {
                    str(classification)
                    for row in rows
                    for classification in (row.get("missing_feedback_classifications") or [])
                }
            )
        },
        "audit_quality_rejection_counts": {
            reason: sum(
                1
                for row in rows
                if reason in (row.get("audit_quality_rejection_reasons") or [])
            )
            for reason in sorted(
                {
                    str(reason)
                    for row in rows
                    for reason in (row.get("audit_quality_rejection_reasons") or [])
                }
            )
        },
        "closed_trade_validity_rejection_counts": {
            reason: sum(
                1
                for row in rows
                if reason in (row.get("closed_trade_validity_rejection_reasons") or [])
            )
            for reason in sorted(
                {
                    str(reason)
                    for row in rows
                    for reason in (row.get("closed_trade_validity_rejection_reasons") or [])
                }
            )
        },
        "audit_quality_clean_rows": sum(1 for row in rows if not row.get("audit_quality_rejection_reasons")),
        "closed_trade_validity_clean_rows": sum(1 for row in rows if not row.get("closed_trade_validity_rejection_reasons")),
        "trainer_consumable_rows": sum(1 for row in rows if row.get("trainer_consumable") is True),
    }


__all__ = [
    "MISSING_FEEDBACK_CLASS_BY_FIELD",
    "REQUIRED_FEEDBACK_FIELDS",
    "AUDIT_QUALITY_FEEDBACK_FIELDS",
    "audit_quality_rejection_reasons",
    "build_strategy_hedge_exit_feedback",
    "feedback_status",
]
