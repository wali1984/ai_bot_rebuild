from __future__ import annotations

from typing import Any

from .accounting import fee_and_slippage_usd, pnl_bps, pnl_usd
from .position_state import PaperNetPosition, first_present, seconds_between


FUNDING_PNL_ACCOUNTING_VERSION = "PAPER_FUNDING_ACCRUAL_V1"
FUNDING_PNL_ACCOUNTING_FORMULA = (
    "funding_notional_usd * funding_rate * "
    "(hold_time_seconds / funding_interval_seconds) * side_sign"
)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _first_number(*values: Any) -> float | None:
    for value in values:
        parsed = _as_float(value)
        if parsed is not None:
            return parsed
    return None


def _funding_accrual(
    *,
    position: PaperNetPosition,
    close_quantity: float,
    hold_time_seconds: int,
) -> dict[str, Any]:
    adaptive_allocation = (
        dict(position.adaptive_allocation)
        if isinstance(position.adaptive_allocation, dict)
        else {}
    )
    model_inputs = (
        adaptive_allocation.get("model_inputs")
        if isinstance(adaptive_allocation.get("model_inputs"), dict)
        else {}
    )
    oi_funding = (
        position.oi_funding_context
        if isinstance(position.oi_funding_context, dict)
        else {}
    )
    funding_bps = _first_number(
        position.expected_funding_bps,
        adaptive_allocation.get("expected_funding_bps"),
        model_inputs.get("expected_funding_bps"),
        model_inputs.get("funding_bps"),
        model_inputs.get("funding_rate_bps"),
        oi_funding.get("expected_funding_bps"),
        oi_funding.get("funding_bps"),
        oi_funding.get("funding_rate_bps"),
    )
    funding_rate = _first_number(
        position.funding_rate,
        model_inputs.get("funding_rate"),
        oi_funding.get("funding_rate"),
        oi_funding.get("last_funding_rate"),
        oi_funding.get("next_funding_rate"),
    )
    source = "MISSING_FUNDING_RATE"
    if funding_rate is not None:
        source = "FUNDING_RATE"
    elif funding_bps is not None:
        funding_rate = funding_bps / 10000.0
        source = "EXPECTED_FUNDING_BPS"
    if funding_bps is None and funding_rate is not None:
        funding_bps = funding_rate * 10000.0
    interval_seconds = _first_number(
        position.funding_interval_seconds,
        model_inputs.get("funding_interval_seconds"),
        oi_funding.get("funding_interval_seconds"),
        28800.0,
    )
    interval_seconds = max(1.0, interval_seconds or 28800.0)
    interval_count = max(0.0, float(hold_time_seconds)) / interval_seconds
    notional = abs(close_quantity * position.avg_entry_price)
    side_multiplier = -1.0 if position.side == "long" else 1.0
    funding_pnl = (
        0.0
        if funding_rate is None
        else notional * funding_rate * interval_count * side_multiplier
    )
    accounting_status = (
        "READY_FUNDING_PNL_ACCRUED"
        if funding_rate is not None
        else "MISSING_FUNDING_RATE_OR_BPS"
    )
    return {
        "funding_pnl_accounting_version": FUNDING_PNL_ACCOUNTING_VERSION,
        "funding_pnl_accounting_status": accounting_status,
        "funding_pnl_usd": funding_pnl,
        "funding_rate": funding_rate,
        "funding_bps": funding_bps,
        "funding_interval_seconds": interval_seconds,
        "funding_accrual_intervals": interval_count,
        "funding_notional_usd": notional,
        "funding_pnl_formula": FUNDING_PNL_ACCOUNTING_FORMULA,
        "funding_pnl_side_sign": side_multiplier,
        "funding_pnl_source": source,
    }


def _squeeze_from_close_context(
    *,
    position: PaperNetPosition,
    exit_spread_bps: float | None,
) -> tuple[float | None, str | None, dict[str, float] | None, str | None]:
    if position.squeeze_evidence_score is not None:
        return (
            position.squeeze_evidence_score,
            position.squeeze_evidence_source,
            position.squeeze_evidence_components,
            position.squeeze_evidence_unavailable_reason,
        )
    micro = position.microstructure_context if isinstance(position.microstructure_context, dict) else {}
    liquidation = (
        position.liquidation_distance_context
        if isinstance(position.liquidation_distance_context, dict)
        else {}
    )
    oi_funding = position.oi_funding_context if isinstance(position.oi_funding_context, dict) else {}
    components: dict[str, float] = {}
    spread = _first_number(exit_spread_bps, micro.get("bid_ask_spread_bps"), micro.get("spread_bps"), micro.get("ob_spread_bps"))
    if spread is not None:
        components["spread_stress"] = max(0.0, min(1.0, (abs(spread) - 5.0) / 45.0))
    imbalance = _first_number(micro.get("orderbook_imbalance"), micro.get("ob_imbalance"), micro.get("depth_imbalance"))
    if imbalance is not None:
        components["orderbook_imbalance"] = max(0.0, min(1.0, abs(imbalance) * 2.0))
    pressure = _first_number(
        liquidation.get("liquidation_pressure"),
        liquidation.get("liquidation_strength"),
        liquidation.get("liquidation_cascade_risk"),
    )
    if pressure is not None:
        components["liquidation_pressure"] = max(0.0, min(1.0, pressure if pressure <= 1.0 else pressure / 100.0))
    funding = _first_number(oi_funding.get("funding_rate"), oi_funding.get("last_funding_rate"))
    if funding is not None:
        components["funding_extreme"] = max(0.0, min(1.0, abs(funding) * 2500.0))
    if not components:
        return (
            None,
            None,
            None,
            position.squeeze_evidence_unavailable_reason or "MISSING_SQUEEZE_LIQUIDATION_OI_ORDERBOOK_EVIDENCE",
        )
    nonzero = {key: value for key, value in components.items() if value > 0.0}
    score = (
        nonzero.get("liquidation_pressure", 0.0) * 0.30
        + nonzero.get("funding_extreme", 0.0) * 0.12
        + nonzero.get("orderbook_imbalance", 0.0) * 0.16
        + nonzero.get("spread_stress", 0.0) * 0.08
    )
    return (
        round(max(0.0, min(1.0, score)), 6),
        "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        {key: round(value, 6) for key, value in components.items()},
        None,
    )


def build_close_event(
    *,
    position: PaperNetPosition,
    close_quantity: float,
    exit_price: float,
    exit_time: str,
    close_reason: str,
    exit_signal_id: str | None = None,
    exit_prediction_id: str | None = None,
    fee_bps: float = 4.0,
    slippage_bps: float = 2.0,
    exit_spread_bps: float | None = None,
    exit_spread_source: str | None = None,
    exit_spread_available_at: str | None = None,
    exit_audit_context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    notional = abs(close_quantity * exit_price)
    hold_time = seconds_between(position.opened_est, exit_time)
    funding_accrual = _funding_accrual(
        position=position,
        close_quantity=close_quantity,
        hold_time_seconds=hold_time,
    )
    funding_pnl_usd = float(funding_accrual["funding_pnl_usd"])
    gross_pnl = pnl_usd(
        side=position.side,
        entry_price=position.avg_entry_price,
        exit_price=exit_price,
        quantity=close_quantity,
    )
    fees, slippage = fee_and_slippage_usd(
        notional_usdt=notional,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    realized = gross_pnl - fees - slippage + funding_pnl_usd
    realized_bps = pnl_bps(
        side=position.side,
        entry_price=position.avg_entry_price,
        exit_price=exit_price,
    )
    entry_notional = abs(close_quantity * position.avg_entry_price)
    realized_net_pnl_bps = (realized / entry_notional * 10000.0) if entry_notional > 0 else 0.0
    close_id = f"paper_close_{position.position_id}_{len(position.fill_ids)}_{int(abs(realized) * 1000000)}"
    outcome_label_id = f"paper_outcome_{close_id}"
    trainer_feedback_id = f"trainer_feedback_{close_id}"
    spread_exit_bps = exit_spread_bps if exit_spread_bps is not None else position.entry_observed_spread_bps
    # CG-F010 fix: realized_slippage_bps must reflect actual observed spread, not a
    # hardcoded constant. When exit spread is known, model it as half-spread (the
    # taker cost for crossing the bid-ask). Fall back to the default only when no
    # spread evidence exists at all.
    if spread_exit_bps is not None:
        realized_slippage_bps_actual = max(0.25, abs(spread_exit_bps) * 0.50)
        fees, slippage = fee_and_slippage_usd(
            notional_usdt=notional,
            fee_bps=fee_bps,
            slippage_bps=realized_slippage_bps_actual,
        )
        realized = gross_pnl - fees - slippage + funding_pnl_usd
        slippage_bps = realized_slippage_bps_actual
        realized_net_pnl_bps = (realized / entry_notional * 10000.0) if entry_notional > 0 else 0.0
    expected_slippage_bps = (
        position.expected_slippage_bps
        if position.expected_slippage_bps is not None
        else (
            max(0.25, abs(spread_exit_bps) * 0.50)
            if spread_exit_bps is not None
            else slippage_bps
        )
    )
    expected_slippage_usd = (
        position.expected_slippage_usd
        if position.expected_slippage_usd is not None
        else abs(notional) * max(0.0, expected_slippage_bps) / 10000.0
    )
    expected_slippage_source = position.expected_slippage_source
    expected_slippage_modeled = position.expected_slippage_modeled
    expected_slippage_unavailable_reason = position.expected_slippage_unavailable_reason
    if expected_slippage_source in (None, "") and spread_exit_bps is not None:
        expected_slippage_source = "MODELED_FROM_OBSERVED_EXIT_SPREAD"
        expected_slippage_modeled = True
        expected_slippage_unavailable_reason = None
    implementation_shortfall_usd = slippage - expected_slippage_usd
    squeeze_score, squeeze_source, squeeze_components, squeeze_unavailable = _squeeze_from_close_context(
        position=position,
        exit_spread_bps=spread_exit_bps,
    )
    audit_context = dict(exit_audit_context or {})
    exit_price_source = str(
        audit_context.get("paper_exit_price_source") or "V2_MARKET_PRICE_MARK_TO_MARKET"
    )
    adaptive_allocation = (
        dict(position.adaptive_allocation)
        if isinstance(position.adaptive_allocation, dict)
        else None
    )
    adaptive_capital_policy_version = first_present(
        position.adaptive_capital_policy_version,
        adaptive_allocation.get("adaptive_capital_policy_version") if adaptive_allocation else None,
    )
    policy_activated_at = first_present(
        position.policy_activated_at,
        adaptive_allocation.get("policy_activated_at") if adaptive_allocation else None,
    )
    telemetry = {
        "adaptive_allocation": adaptive_allocation,
        "adaptive_capital_policy_version": adaptive_capital_policy_version,
        "policy_activated_at": policy_activated_at,
        "gross_notional_usd": position.gross_notional_usd if position.gross_notional_usd is not None else notional,
        "allocated_margin_usd": position.allocated_margin_usd,
        "effective_leverage": position.effective_leverage,
        "expected_move_after_cost_bps": position.expected_move_after_cost_bps,
        "recommended_leverage": position.recommended_leverage,
        "recommended_margin_mode": position.recommended_margin_mode,
        "margin_mode_simulated": position.margin_mode_simulated,
        "maintenance_margin_estimate": position.maintenance_margin_estimate,
        "liquidation_price_estimate": position.liquidation_price_estimate,
        "liquidation_buffer_bps": position.liquidation_buffer_bps,
        "risk_budget_usd": position.risk_budget_usd,
        "risk_budget_source": position.risk_budget_source,
        "stop_distance_bps": position.stop_distance_bps,
        "expected_fees_usd": position.expected_fees_usd,
        "expected_funding_bps": position.expected_funding_bps,
        "expected_funding_usd": position.expected_funding_usd,
        **funding_accrual,
        "expected_net_pnl_usd": position.expected_net_pnl_usd,
        "expected_shortfall_usd": position.expected_shortfall_usd,
        "hedge_budget_usd": position.hedge_budget_usd,
        "capital_allocation_reason": position.capital_allocation_reason,
        "entry_atr_bps": position.entry_atr_bps,
        "atr_bps": position.entry_atr_bps,
        "entry_feature_available_at": position.entry_feature_available_at,
        "entry_feature_generated_at": position.entry_feature_generated_at,
        "entry_feature_cutoff": position.entry_feature_cutoff,
        "entry_feature_decision_time": position.entry_feature_decision_time,
        "entry_feature_source": position.entry_feature_source,
        "entry_feature_candle_closed_confirmed": position.entry_feature_candle_closed_confirmed,
        "entry_feature_unavailable_reason": position.entry_feature_unavailable_reason,
        "entry_feature_snapshot": position.entry_feature_snapshot
        if isinstance(position.entry_feature_snapshot, dict)
        else None,
        "mfe_bps": position.mfe_bps,
        "mfe_usd": position.mfe_usd,
        "mae_bps": position.mae_bps,
        "mae_usd": position.mae_usd,
        "intra_trade_high_price": position.intra_trade_high_price,
        "intra_trade_low_price": position.intra_trade_low_price,
        "trailing_activation_price": position.trailing_activation_price,
        "trailing_activation_time": position.trailing_activation_time,
        "trailing_stop_price": position.trailing_stop_price,
        "trailing_stop_history": list(position.trailing_stop_history),
        "actual_observed_spread_entry_bps": position.entry_observed_spread_bps,
        "observed_bid": position.observed_bid,
        "observed_ask": position.observed_ask,
        "observed_spread_bps": position.observed_spread_bps,
        "order_size": position.order_size,
        "order_size_usd": position.order_size_usd,
        "actual_observed_spread_exit_bps": spread_exit_bps,
        "entry_spread_source": position.entry_spread_source,
        "entry_spread_unavailable_reason": position.entry_spread_unavailable_reason,
        "exit_spread_source": exit_spread_source or position.entry_spread_source,
        "exit_spread_available_at": exit_spread_available_at,
        "exit_spread_unavailable_reason": (
            None if spread_exit_bps is not None else "MISSING_EXIT_OBSERVED_SPREAD_BPS"
        ),
        "expected_slippage_bps": expected_slippage_bps,
        "expected_slippage_usd": expected_slippage_usd,
        "realized_slippage_bps": slippage_bps,
        "realized_slippage_usd": slippage,
        "implementation_shortfall_usd": implementation_shortfall_usd,
        "decision_latency_ms": position.decision_latency_ms,
        "latency_ms": position.decision_latency_ms,
        "paper_fill_latency_ms": position.decision_latency_ms,
        "fill_latency_ms": position.decision_latency_ms,
        "execution_latency_ms": position.decision_latency_ms,
        "simulated_latency_ms": position.decision_latency_ms,
        "latency_source": position.latency_source,
        "selector_policy_fingerprint": position.selector_policy_fingerprint,
        "frozen_selector_fingerprint": position.frozen_selector_fingerprint,
        "candidate_selected_before_outcome": position.candidate_selected_before_outcome,
        "candidate_selected_after_outcome": position.candidate_selected_after_outcome,
        "post_outcome_candidate_selection": position.post_outcome_candidate_selection,
        "future_labels_used_as_features": position.future_labels_used_as_features,
        "paper_opportunity_tier": position.paper_opportunity_tier,
        "paper_opportunity_tier_reason": position.paper_opportunity_tier_reason,
        "explicit_paper_opportunity_tier": position.explicit_paper_opportunity_tier,
        "paper_fill_allowed_source": position.paper_fill_allowed_source,
        "strict_paper_fill_allowed_upstream": position.strict_paper_fill_allowed_upstream,
        "calibration_label_purpose": position.calibration_label_purpose,
        "top_book_bid_depth_usd": position.top_book_bid_depth_usd,
        "top_book_ask_depth_usd": position.top_book_ask_depth_usd,
        "bid_depth_usd": position.bid_depth_usd,
        "ask_depth_usd": position.ask_depth_usd,
        "orderbook_depth_usd": position.orderbook_depth_usd,
        "entry_orderbook_depth_usd": position.entry_orderbook_depth_usd,
        "entry_orderbook_depth_side": position.entry_orderbook_depth_side,
        "top_of_book_depth_usd": position.top_of_book_depth_usd,
        "market_depth_usd": position.market_depth_usd,
        "orderbook_depth_source": position.orderbook_depth_source,
        "depth_utilization_pct": position.depth_utilization_pct,
        "depth_price_impact_bps": position.depth_price_impact_bps,
        "depth_derived_price_impact_bps": position.depth_derived_price_impact_bps,
        "depth_price_impact_source": position.depth_price_impact_source,
        "depth_price_impact_model": position.depth_price_impact_model,
        "depth_price_impact_side": position.depth_price_impact_side,
        "depth_price_impact_quantity": position.depth_price_impact_quantity,
        "depth_price_impact_filled_quantity": position.depth_price_impact_filled_quantity,
        "depth_price_impact_fill_complete": position.depth_price_impact_fill_complete,
        "depth_price_impact_vwap": position.depth_price_impact_vwap,
        "depth_price_impact_touch_price": position.depth_price_impact_touch_price,
        "maker_probability": position.maker_probability,
        "taker_probability": position.taker_probability,
        "maker_taker_probability": position.maker_taker_probability,
        "maker_taker_probabilities": position.maker_taker_probabilities,
        "maker_taker_probability_source": position.maker_taker_probability_source,
        "partial_fill_count": position.partial_fill_count,
        "partial_fills": position.partial_fills,
        "fill_count": position.fill_count,
        "all_partial_fills": position.all_partial_fills,
        "partial_fill_plan": position.partial_fill_plan,
        "mark_index_divergence_bps": position.mark_index_divergence_bps,
        "mark_index_divergence": position.mark_index_divergence,
        "mark_index_source": position.mark_index_source,
        "mark_index_available_at": position.mark_index_available_at,
        "mark_price": position.mark_price,
        "index_price": position.index_price,
        "squeeze_evidence_source": squeeze_source,
        "squeeze_evidence_components": squeeze_components,
        "squeeze_evidence_unavailable_reason": squeeze_unavailable,
        "maker_taker_assumption": position.maker_taker_assumption,
        "maker_taker_probability_detail": position.maker_taker_probability_detail,
        "fee_schedule": position.fee_schedule,
        "fee_bps": position.fee_bps,
        "fee_bps_source": position.fee_bps_source,
        "fee_bps_configured_schedule": position.fee_bps_configured_schedule,
        "holding_period_funding_bps": position.holding_period_funding_bps,
        "holding_period_funding_source": position.holding_period_funding_source,
        "expected_slippage_source": expected_slippage_source,
        "expected_slippage_modeled": expected_slippage_modeled,
        "expected_slippage_unavailable_reason": expected_slippage_unavailable_reason,
        "latency_reserve_bps": position.latency_reserve_bps,
        "latency_reserve_source": position.latency_reserve_source,
        "partial_fill_estimate": position.partial_fill_estimate,
        "partial_fill_probability": position.partial_fill_probability,
        "partial_fill_adjustment_bps": position.partial_fill_adjustment_bps,
        "execution_probability": position.execution_probability,
        "cost_source": position.cost_source,
        "cost_source_timestamp": position.cost_source_timestamp,
        "source_timestamp": position.source_timestamp,
        "cost_evidence_freshness_ms": position.cost_evidence_freshness_ms,
        "cost_evidence_source_fields": position.cost_evidence_source_fields,
        "runtime_cost_capture_source": position.runtime_cost_capture_source,
        "runtime_cost_capture_status": position.runtime_cost_capture_status,
        "runtime_cost_capture_required_fields": position.runtime_cost_capture_required_fields,
        "runtime_cost_capture_missing_fields": position.runtime_cost_capture_missing_fields,
        "runtime_cost_capture_explained_missing_fields": position.runtime_cost_capture_explained_missing_fields,
        "runtime_cost_capture_unexplained_missing_fields": position.runtime_cost_capture_unexplained_missing_fields,
        "runtime_cost_capture_order_cost_applicable": position.runtime_cost_capture_order_cost_applicable,
        "runtime_cost_capture_no_order_reason": position.runtime_cost_capture_no_order_reason,
        "runtime_cost_capture_temporal_reject_reasons": position.runtime_cost_capture_temporal_reject_reasons,
        "fallback_cost_flag": position.fallback_cost_flag,
        "fallback": position.fallback,
        "production_grade_cost_flag": position.production_grade_cost_flag,
        "production_grade_cost_evidence": position.production_grade_cost_evidence,
        "estimated_production_cost": position.estimated_production_cost,
        "estimated_production_cost_bps": position.estimated_production_cost_bps,
        "counts_as_production_grade_training_evidence": position.counts_as_production_grade_training_evidence,
        "correlation_exposure_pct": position.correlation_exposure_pct,
        "correlation_input_source": position.correlation_input_source,
        "correlation_input_status": position.correlation_input_status,
        "correlation_pair_count": position.correlation_pair_count,
        "correlation_diagnostics": (
            dict(position.correlation_diagnostics)
            if isinstance(position.correlation_diagnostics, dict)
            else None
        ),
        **audit_context,
    }
    directional_outcome = "UP" if exit_price > position.avg_entry_price else "DOWN" if exit_price < position.avg_entry_price else "FLAT"
    trade_outcome = "WIN" if realized > 0.0 else "LOSS" if realized < 0.0 else "BREAKEVEN"
    action_was_profitable = realized > 0.0
    trust_envelope = {
        "candidate_id": position.candidate_id,
        "paper_policy_owner": position.paper_policy_owner,
        "policy_fingerprint": position.policy_fingerprint
        or position.selector_policy_fingerprint
        or position.frozen_selector_fingerprint,
        "model_source": position.model_source or position.model_version,
        "prediction_id": position.prediction_id,
        "signal_id": position.source_signal_id,
        "risk_decision_id": position.risk_decision_id,
        "orchestrator_decision_id": position.orchestrator_decision_id,
        "decision_id": position.decision_id,
        "mtf_snapshot_id": position.mtf_snapshot_id,
        "feature_cutoff": position.feature_cutoff or position.entry_feature_cutoff,
        "decision_time": position.decision_time or position.entry_feature_decision_time,
        "available_at": position.available_at or position.entry_feature_available_at,
        "selected_action": position.selected_action or position.side,
        "model_version": position.model_version,
        "checkpoint_id": position.checkpoint_id,
        "source_hashes": position.source_hashes,
    }
    missing_score_fields = [
        field
        for field, value in (
            ("confidence_calibrated", position.confidence_calibrated),
            ("expected_move_after_cost_bps", position.expected_move_after_cost_bps),
        )
        if value is None
    ]
    prediction_score_envelope = {
        "confidence_raw": position.confidence_raw,
        "confidence_calibrated": position.confidence_calibrated,
        "selected_action_probability": position.selected_action_probability,
        "expected_move_bps": position.expected_move_bps,
        "expected_move_after_cost_bps": position.expected_move_after_cost_bps,
        "action_probabilities": position.action_probabilities,
        "policy_value": position.policy_value,
        "value_baseline": position.value_baseline,
        "prediction_score_source": position.prediction_score_source
        or (
            "ENTRY_FILL_VERIFIED_PREDICTION_SCORE_FIELDS"
            if not missing_score_fields
            else None
        ),
        "prediction_score_missing_reason": position.prediction_score_missing_reason
        or (
            None
            if not missing_score_fields
            else "MISSING_ENTRY_PREDICTION_SCORE_FIELDS:" + ",".join(missing_score_fields)
        ),
    }
    outcome_targets = {
        "realized_net_pnl_bps": realized_net_pnl_bps,
        "realized_net_pnl_usd": realized,
        "directional_outcome": directional_outcome,
        "trade_outcome": trade_outcome,
        "selected_action": position.selected_action or position.side,
        "action_was_profitable": action_was_profitable,
        "holding_period": hold_time,
        "fees": fees,
        "slippage": slippage,
        "funding": funding_pnl_usd,
        "MFE": position.mfe_bps,
        "MAE": position.mae_bps,
        "exit_reason": close_reason,
    }
    close_event = {
        "close_id": close_id,
        "position_id": position.position_id,
        "symbol": position.symbol,
        "side": position.side,
        "closed_quantity": close_quantity,
        "entry_price": position.avg_entry_price,
        "exit_price": exit_price,
        "exit_price_source": exit_price_source,
        "exit_price_utc": exit_time,
        "realized_pnl_usd": realized,
        "realized_pnl_usdt": realized,
        "realized_pnl_bps": realized_bps,
        "realized_net_pnl_bps": realized_net_pnl_bps,
        "realized_net_pnl_usd": realized,
        "directional_outcome": directional_outcome,
        "trade_outcome": trade_outcome,
        "selected_action": position.selected_action or position.side,
        "action_was_profitable": action_was_profitable,
        "holding_period": hold_time,
        "gross_realized_pnl_usd": gross_pnl,
        "funding_pnl_usd": funding_pnl_usd,
        "fees": fees,
        "slippage": slippage,
        "slippage_bps": slippage_bps,
        "hold_time_seconds": hold_time,
        "signal_id": position.source_signal_id,
        "entry_signal_id": position.source_signal_id,
        "exit_signal_id": exit_signal_id,
        "prediction_id": position.prediction_id,
        "entry_prediction_id": position.prediction_id,
        "exit_prediction_id": exit_prediction_id,
        "risk_decision_id": position.risk_decision_id,
        "orchestrator_decision_id": position.orchestrator_decision_id,
        "entry_feature_snapshot_id": position.feature_snapshot_id,
        "entry_feature_snapshot": position.entry_feature_snapshot
        if isinstance(position.entry_feature_snapshot, dict)
        else None,
        "entry_market_state_id": position.entry_market_state_id or position.market_state_id,
        "market_state_id": position.entry_market_state_id or position.market_state_id,
        "feature_snapshot_id": position.feature_snapshot_id,
        "timeframe": position.timeframe,
        "action": position.side,
        "close_reason": close_reason,
        "exit_reason": close_reason,
        "strategy_id": position.strategy_id,
        "strategy_family": position.strategy_family,
        "strategy_subtype": position.strategy_selected_mode,
        "strategy_selected_mode": position.strategy_selected_mode,
        "entry_reason": position.strategy_id or position.strategy_selected_mode,
        "hedge_state": position.hedge_state or "NO_HEDGE",
        "hedge_reason": position.hedge_reason or "NO_HEDGE_CONTEXT",
        "drawdown_at_entry": position.drawdown_at_entry,
        "market_regime_at_entry": position.market_regime_at_entry,
        "market_regime_at_exit": position.market_regime_at_entry,
        "winner": realized > 0.0,
        "outcome_label_id": outcome_label_id,
        "trainer_feedback_id": trainer_feedback_id,
        "liquidity_zone_context": position.liquidity_zone_context,
        "liquidation_distance_context": position.liquidation_distance_context,
        "liquidation_context": position.liquidation_distance_context,
        "microstructure_context": position.microstructure_context,
        "oi_funding_context": position.oi_funding_context
        or {
            "source": "V2_PAPER_POSITION_ENTRY_CONTEXT",
            "status": "not_provided" if position.strategy_id is None else "provided_by_strategy_context",
        },
        "public_intel_context": position.public_intel_context
        or {
            "source": "V2_PAPER_POSITION_ENTRY_CONTEXT",
            "status": "not_provided" if position.strategy_id is None else "provided_by_strategy_context",
        },
        "major_move_signal_id": position.major_move_signal_id,
        "squeeze_evidence_score": squeeze_score,
        "future_window_label_source": position.future_window_label_source or "closed_trade_outcome",
        "source_fill_ids": list(position.fill_ids),
        "paper_only": True,
        "places_real_order": False,
        **trust_envelope,
        **prediction_score_envelope,
        **outcome_targets,
        "outcome_targets": outcome_targets,
        **telemetry,
    }
    outcome = {
        "outcome_label_id": outcome_label_id,
        "trainer_feedback_id": trainer_feedback_id,
        "position_id": position.position_id,
        "symbol": position.symbol,
        "timeframe": position.timeframe,
        "side": position.side,
        "entry_feature_snapshot_id": position.feature_snapshot_id,
        "entry_feature_snapshot": position.entry_feature_snapshot
        if isinstance(position.entry_feature_snapshot, dict)
        else None,
        "entry_market_state_id": position.entry_market_state_id or position.market_state_id,
        "market_state_id": position.entry_market_state_id or position.market_state_id,
        "feature_snapshot_id": position.feature_snapshot_id,
        "entry_prediction_id": position.prediction_id,
        "prediction_id": position.prediction_id,
        "entry_signal_id": position.source_signal_id,
        "signal_id": position.source_signal_id,
        "exit_time": exit_time,
        "entry_price": position.avg_entry_price,
        "exit_price": exit_price,
        "realized_pnl_bps": realized_bps,
        "realized_net_pnl_bps": realized_net_pnl_bps,
        "realized_net_pnl_usd": realized,
        "directional_outcome": directional_outcome,
        "trade_outcome": trade_outcome,
        "selected_action": position.selected_action or position.side,
        "action_was_profitable": action_was_profitable,
        "holding_period": hold_time,
        "realized_pnl": realized,
        "realized_pnl_usd": realized,
        "winner": realized > 0.0,
        "close_reason": close_reason,
        "exit_reason": close_reason,
        "hold_time_seconds": hold_time,
        "funding_pnl_usd": funding_pnl_usd,
        "fees": fees,
        "slippage": slippage,
        "slippage_bps": slippage_bps,
        "strategy_id": position.strategy_id,
        "strategy_family": position.strategy_family,
        "strategy_subtype": position.strategy_selected_mode,
        "strategy_selected_mode": position.strategy_selected_mode,
        "entry_reason": position.strategy_id or position.strategy_selected_mode,
        "hedge_state": position.hedge_state or "NO_HEDGE",
        "hedge_reason": position.hedge_reason or "NO_HEDGE_CONTEXT",
        "drawdown_at_entry": position.drawdown_at_entry,
        "market_regime_at_entry": position.market_regime_at_entry,
        "market_regime_at_exit": position.market_regime_at_entry,
        "liquidity_zone_context": position.liquidity_zone_context,
        "liquidation_distance_context": position.liquidation_distance_context,
        "liquidation_context": position.liquidation_distance_context,
        "microstructure_context": position.microstructure_context,
        "oi_funding_context": position.oi_funding_context
        or {
            "source": "V2_PAPER_POSITION_ENTRY_CONTEXT",
            "status": "not_provided" if position.strategy_id is None else "provided_by_strategy_context",
        },
        "public_intel_context": position.public_intel_context
        or {
            "source": "V2_PAPER_POSITION_ENTRY_CONTEXT",
            "status": "not_provided" if position.strategy_id is None else "provided_by_strategy_context",
        },
        "major_move_signal_id": position.major_move_signal_id,
        "squeeze_evidence_score": squeeze_score,
        "future_window_label_source": position.future_window_label_source or "closed_trade_outcome",
        "trainer_feedback_source": "V2_PAPER_TRADE_MANAGEMENT_CLOSED_TRADE",
        "paper_only": True,
        "places_real_order": False,
        **trust_envelope,
        **prediction_score_envelope,
        **outcome_targets,
        "outcome_targets": outcome_targets,
        **telemetry,
    }
    return close_event, outcome
