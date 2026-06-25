from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


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
)

STATIC_SPREAD_PLACEHOLDER_SOURCES: frozenset[str] = frozenset(
    {
        "V2_ALLOCATOR",
        "V2_ENTRY_MICROSTRUCTURE_CONTEXT",
        "V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
        "V2_PREDICTION_OR_SIGNAL_MICROSTRUCTURE",
    }
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


def _trust_envelope_rejection_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in REQUIRED_TRUST_ENVELOPE_FIELDS:
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
    if row.get("prediction_id") and not row.get("mtf_snapshot_id") and not row.get("feature_cutoff"):
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
    audit_quality_classes = [f"audit_quality:{reason.lower()}" for reason in audit_quality_reasons]
    trust_classes = [f"trust:{reason.lower()}" for reason in trust_reasons]
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
    row["trainer_consumable"] = not missing and not audit_quality_reasons and not trust_reasons
    row["missing_feedback_fields"] = missing
    row["missing_trust_fields"] = [
        reason.removeprefix("MISSING_TRUST_").lower()
        for reason in trust_reasons
        if reason.startswith("MISSING_TRUST_")
    ]
    row["missing_feedback_classifications"] = sorted(set(missing_classes + audit_quality_classes + trust_classes))
    row["quarantine_reason"] = (
        "NONE"
        if not row["missing_feedback_classifications"]
        else (
            f"stale_lineage:{row['non_critical_quarantine_reason']}"
            if row.get("quarantine_non_critical") and not audit_quality_reasons
            else ",".join(row["missing_feedback_classifications"])
        )
    )
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
        "audit_quality_clean_rows": sum(1 for row in rows if not row.get("audit_quality_rejection_reasons")),
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
