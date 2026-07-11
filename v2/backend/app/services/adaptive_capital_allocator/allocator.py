from __future__ import annotations

from dataclasses import replace
import hashlib
from typing import Any

from .contracts import ADAPTIVE_CAPITAL_POLICY_VERSION, AllocationInput, AllocationResult, RiskEnvelope
from .exchange_filters import min_order_notional, round_down_to_step
from .explanation import explain_allocation
from .risk_budget import available_margin_budget_usdt, risk_envelope_gross_notional_ceiling
from .sizing_model import (
    adaptive_budget_pct,
    correlation_adjustment,
    drawdown_adjustment,
    exposure_adjustment,
    liquidity_adjustment,
    market_state_adjustment,
    regime_adjustment,
    spread_slippage_adjustment,
    volatility_adjustment,
)
from v2.backend.app.services.hedge_engine import evaluate_hedge_intent, simulate_cross_margin_stress


MAX_DYNAMIC_HEDGE_BUDGET_PCT_OF_RISK = 0.35
PAPER_MIN_EDGE_BPS_FOR_DYNAMIC_LEVERAGE = 35.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _allocation_id(row: AllocationInput, mode: str) -> str:
    raw = "|".join(
        [
            mode,
            row.symbol,
            row.timeframe,
            row.action,
            str(row.lineage_ids.get("prediction_id") or ""),
            f"{row.confidence_calibrated:.8f}",
            f"{row.expected_move_after_cost_bps:.8f}",
        ]
    )
    return "alloc_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _paper_economic_edge_after_cost_bps(row: AllocationInput, *, mode: str) -> float:
    """Return positive economic edge for paper sizing without changing live behavior."""
    if mode != "paper":
        return max(0.0, float(row.expected_move_after_cost_bps or 0.0))
    action = str(row.action or "").strip().lower()
    signed_edge = float(row.expected_move_after_cost_bps or 0.0)
    if action == "short":
        if signed_edge < 0.0:
            return -signed_edge
        return 0.0
    if action == "long":
        return max(0.0, signed_edge)
    return 0.0


def _paper_sizing_row(row: AllocationInput, *, mode: str) -> AllocationInput:
    edge = _paper_economic_edge_after_cost_bps(row, mode=mode)
    if mode != "paper" or edge == row.expected_move_after_cost_bps:
        return row
    return replace(row, expected_move_after_cost_bps=edge)


def _adaptive_hedge_budget_selection(row: AllocationInput, envelope: RiskEnvelope) -> tuple[float, dict[str, float | str]]:
    operator_floor = _clamp(float(row.hedge_budget_pct_of_risk or 0.0), 0.0, MAX_DYNAMIC_HEDGE_BUDGET_PCT_OF_RISK)
    edge = max(0.0, float(row.expected_move_after_cost_bps or 0.0))
    cost_drag = (
        max(0.0, row.spread_bps)
        + max(0.0, row.slippage_bps)
        + max(0.0, row.fee_bps)
        + abs(row.expected_funding_bps)
    )
    correlation_pressure = _clamp(
        max(0.0, row.correlation_exposure_pct) / max(1e-9, envelope.max_correlation_exposure_pct),
        0.0,
        1.0,
    )
    drawdown_pressure = _clamp(
        max(0.0, row.drawdown_bps) / max(1.0, envelope.max_daily_drawdown_pct * 10000.0),
        0.0,
        1.0,
    )
    volatility_pressure = _clamp((max(0.0, row.volatility_bps) - 80.0) / 240.0, 0.0, 1.0)
    cost_pressure = _clamp(cost_drag / max(1.0, edge), 0.0, 1.0) if edge > 0.0 else 1.0
    risk_pressure = max(correlation_pressure, drawdown_pressure, volatility_pressure * 0.5, cost_pressure * 0.5)
    dynamic_pct = 0.0 if risk_pressure < 0.25 else _clamp(
        0.05 + (0.30 * risk_pressure),
        0.0,
        MAX_DYNAMIC_HEDGE_BUDGET_PCT_OF_RISK,
    )
    selected_pct = max(operator_floor, dynamic_pct)
    reason = "operator_hedge_budget_floor" if operator_floor >= dynamic_pct and operator_floor > 0.0 else (
        "correlation_drawdown_volatility_cost_pressure" if selected_pct > 0.0 else "hedge_budget_not_required_for_current_risk"
    )
    return selected_pct, {
        "operator_hedge_budget_pct_of_risk": round(operator_floor, 8),
        "selected_hedge_budget_pct_of_risk": round(selected_pct, 8),
        "hedge_budget_selection_reason": reason,
        "hedge_correlation_pressure": round(correlation_pressure, 8),
        "hedge_drawdown_pressure": round(drawdown_pressure, 8),
        "hedge_volatility_pressure": round(volatility_pressure, 8),
        "hedge_cost_pressure": round(cost_pressure, 8),
        "hedge_risk_pressure": round(risk_pressure, 8),
    }


def _adaptive_leverage_target_selection(
    row: AllocationInput,
    envelope: RiskEnvelope,
    *,
    mode: str,
) -> tuple[float, dict[str, Any]]:
    cost_drag_bps = (
        max(0.0, row.spread_bps)
        + max(0.0, row.slippage_bps)
        + max(0.0, row.fee_bps)
        + abs(row.expected_funding_bps)
    )
    edge_bps = max(0.0, row.expected_move_after_cost_bps)
    correlation_pressure = _clamp(
        max(0.0, row.correlation_exposure_pct) / max(1e-9, envelope.max_correlation_exposure_pct),
        0.0,
        1.0,
    )
    drawdown_pressure = _clamp(
        max(0.0, row.drawdown_bps) / max(1.0, envelope.max_daily_drawdown_pct * 10000.0),
        0.0,
        1.0,
    )
    edge_cost_ratio = edge_bps / max(1.0, cost_drag_bps)
    diagnostics: dict[str, Any] = {
        "leverage_selection_mode": mode,
        "leverage_cost_drag_bps": round(cost_drag_bps, 8),
        "leverage_edge_cost_ratio": round(edge_cost_ratio, 8),
        "leverage_correlation_pressure": round(correlation_pressure, 8),
        "leverage_drawdown_pressure": round(drawdown_pressure, 8),
        "leverage_live_mutation_allowed": False,
    }
    if mode != "paper":
        diagnostics.update({
            "leverage_target": 1.0,
            "leverage_selection_reason": "live_mode_requires_operator_approval_for_dynamic_leverage_change",
        })
        return 1.0, diagnostics

    from v2.backend.app.services.paper_trade_management.leverage_recommendation import (  # noqa: PLC0415
        recommend_leverage_for_signal,
        validate_leverage_recommendation,
    )

    recommendation = recommend_leverage_for_signal(
        symbol=row.symbol,
        timeframe=row.timeframe,
        signal_id=str(row.lineage_ids.get("signal_id") or row.lineage_ids.get("prediction_id") or row.symbol),
        direction=row.action,
        confidence_calibrated=row.confidence_calibrated,
        expected_move_after_cost_bps=row.expected_move_after_cost_bps,
        atr_bps=row.volatility_bps,
        equity_usd=row.equity,
    )
    violations = validate_leverage_recommendation(recommendation)
    raw_target = float(recommendation.get("recommended_leverage") or 1.0)
    target = raw_target
    reason = str(recommendation.get("reason_tier") or "paper_phase8_leverage_recommendation")
    if violations:
        target = 1.0
        reason = "phase8_leverage_recommendation_invariant_violation"
    elif edge_bps < max(PAPER_MIN_EDGE_BPS_FOR_DYNAMIC_LEVERAGE, cost_drag_bps * 1.5):
        target = 1.0
        reason = "after_cost_edge_too_small_for_dynamic_leverage"
    elif drawdown_pressure >= 0.50:
        target = 1.0
        reason = "drawdown_pressure_caps_leverage_at_1x"
    elif correlation_pressure >= 0.75:
        target = 1.0
        reason = "correlation_pressure_caps_leverage_at_1x"
    elif drawdown_pressure >= 0.25 or correlation_pressure >= 0.50:
        target = min(target, 2.0)
        reason = f"{reason}|risk_pressure_caps_leverage_at_2x"
    target = _clamp(target, 1.0, max(1.0, envelope.max_effective_leverage))
    diagnostics.update({
        "phase8_leverage_recommendation": recommendation,
        "phase8_leverage_recommendation_violations": violations,
        "raw_leverage_target": round(raw_target, 8),
        "leverage_target": round(target, 8),
        "leverage_selection_reason": reason,
    })
    return target, diagnostics


def _adaptive_margin_mode_selection(
    row: AllocationInput,
    envelope: RiskEnvelope,
    *,
    mode: str,
    leverage: float,
    liquidation_buffer_bps: float | None,
) -> tuple[str, dict[str, Any]]:
    cost_drag_bps = (
        max(0.0, row.spread_bps)
        + max(0.0, row.slippage_bps)
        + max(0.0, row.fee_bps)
        + abs(row.expected_funding_bps)
    )
    edge_bps = max(0.0, row.expected_move_after_cost_bps)
    edge_cost_ratio = edge_bps / max(1.0, cost_drag_bps)
    correlation_pressure = _clamp(
        max(0.0, row.correlation_exposure_pct) / max(1e-9, envelope.max_correlation_exposure_pct),
        0.0,
        1.0,
    )
    drawdown_pressure = _clamp(
        max(0.0, row.drawdown_bps) / max(1.0, envelope.max_daily_drawdown_pct * 10000.0),
        0.0,
        1.0,
    )
    volatility_pressure = _clamp((max(0.0, row.volatility_bps) - 80.0) / 240.0, 0.0, 1.0)
    diagnostics: dict[str, Any] = {
        "margin_mode_selection_mode": mode,
        "margin_mode_live_mutation_allowed": False,
        "margin_mode_edge_cost_ratio": round(edge_cost_ratio, 8),
        "margin_mode_correlation_pressure": round(correlation_pressure, 8),
        "margin_mode_drawdown_pressure": round(drawdown_pressure, 8),
        "margin_mode_volatility_pressure": round(volatility_pressure, 8),
        "margin_mode_liquidation_buffer_bps": (
            round(liquidation_buffer_bps, 8)
            if liquidation_buffer_bps is not None else None
        ),
    }
    if mode != "paper":
        diagnostics.update({
            "selected_margin_mode": "isolated",
            "margin_mode_selection_reason": "live_mode_requires_operator_approval_for_margin_mode_change",
        })
        return "isolated", diagnostics

    low_portfolio_pressure = max(correlation_pressure, drawdown_pressure, volatility_pressure) <= 0.20
    liquidation_buffer = liquidation_buffer_bps if liquidation_buffer_bps is not None else 0.0
    high_edge_low_pressure = (
        row.confidence_calibrated >= 0.85
        and edge_bps >= 120.0
        and edge_cost_ratio >= 20.0
        and leverage >= 2.0
        and liquidation_buffer >= envelope.min_liquidation_buffer_bps * 3.0
        and low_portfolio_pressure
    )
    if high_edge_low_pressure:
        diagnostics.update({
            "selected_margin_mode": "cross_paper_simulated",
            "margin_mode_selection_reason": "paper_cross_margin_simulated_for_high_edge_low_portfolio_pressure",
        })
        return "cross_paper_simulated", diagnostics
    diagnostics.update({
        "selected_margin_mode": "isolated_paper_simulated",
        "margin_mode_selection_reason": "isolated_limits_tail_contagion_for_current_risk",
    })
    return "isolated_paper_simulated", diagnostics


def _block(row: AllocationInput, *, mode: str, decision: str, reason: str, envelope: RiskEnvelope) -> AllocationResult:
    leverage_selection = {
        "leverage_selection_mode": mode,
        "leverage_cost_drag_bps": round(
            max(0.0, row.spread_bps)
            + max(0.0, row.slippage_bps)
            + max(0.0, row.fee_bps)
            + abs(row.expected_funding_bps),
            8,
        ),
        "leverage_edge_cost_ratio": 0.0,
        "leverage_correlation_pressure": round(
            _clamp(
                max(0.0, row.correlation_exposure_pct) / max(1e-9, envelope.max_correlation_exposure_pct),
                0.0,
                1.0,
            ),
            8,
        ),
        "leverage_drawdown_pressure": round(
            _clamp(
                max(0.0, row.drawdown_bps) / max(1.0, envelope.max_daily_drawdown_pct * 10000.0),
                0.0,
                1.0,
            ),
            8,
        ),
        "leverage_live_mutation_allowed": False,
        "raw_leverage_target": 1.0,
        "leverage_target": 1.0,
        "selected_leverage": 1.0,
        "leverage_selection_reason": f"blocked_allocation_uses_1x_leverage:{reason}",
    }
    return _result(
        row,
        mode=mode,
        envelope=envelope,
        sizing_row=_paper_sizing_row(row, mode=mode),
        decision=decision,
        target_notional=0.0,
        target_quantity=0.0,
        risk_budget_usd=0.0,
        allocated_margin=0.0,
        leverage=1.0,
        stop_distance_bps=_stop_distance_bps(row),
        liquidation_price=None,
        liquidation_buffer_bps=None,
        final_size_reason=reason,
        risk_veto_reason=row.risk_veto_reason if row.risk_veto else reason,
        leverage_selection=leverage_selection,
        margin_mode="isolated_paper_simulated" if mode == "paper" else "isolated",
        margin_mode_selection={
            "margin_mode_selection_mode": mode,
            "margin_mode_live_mutation_allowed": False,
            "selected_margin_mode": "isolated_paper_simulated" if mode == "paper" else "isolated",
            "margin_mode_selection_reason": "blocked_allocation_uses_isolated_margin_mode",
        },
    )


def _result(
    row: AllocationInput,
    *,
    mode: str,
    envelope: RiskEnvelope,
    sizing_row: AllocationInput | None = None,
    decision: str,
    target_notional: float,
    target_quantity: float,
    risk_budget_usd: float,
    allocated_margin: float,
    leverage: float,
    stop_distance_bps: float | None,
    liquidation_price: float | None,
    liquidation_buffer_bps: float | None,
    final_size_reason: str,
    risk_veto_reason: str | None = None,
    leverage_selection: dict[str, Any] | None = None,
    margin_mode: str | None = None,
    margin_mode_selection: dict[str, Any] | None = None,
) -> AllocationResult:
    sizing_row = sizing_row or row
    available_margin = row.available_margin if row.available_margin > 0 else 1.0
    hedge_budget_pct, hedge_selection = _adaptive_hedge_budget_selection(sizing_row, envelope)
    model_inputs: dict[str, Any] = {
        "mode": mode,
        "price": row.price,
        "equity": row.equity,
        "available_margin": row.available_margin,
        "wallet_balance": row.wallet_balance,
        "volatility_bps": row.volatility_bps,
        "liquidity_score": row.liquidity_score,
        "spread_bps": row.spread_bps,
        "slippage_bps": row.slippage_bps,
        "fee_bps": row.fee_bps,
        "expected_funding_bps": row.expected_funding_bps,
        "stop_distance_bps": stop_distance_bps,
        "maintenance_margin_rate": row.maintenance_margin_rate,
        "permitted_leverage_values": list(row.permitted_leverage_values),
        "hedge_budget_pct_of_risk": row.hedge_budget_pct_of_risk,
        "drawdown_bps": row.drawdown_bps,
        "symbol_exposure_usdt": row.symbol_exposure_usdt,
        "total_exposure_usdt": row.total_exposure_usdt,
        "correlation_exposure_pct": row.correlation_exposure_pct,
        "regime_score": row.regime_score,
        "signed_expected_move_after_cost_bps": row.expected_move_after_cost_bps,
        "allocator_economic_edge_after_cost_bps": _paper_economic_edge_after_cost_bps(
            row,
            mode=mode,
        ),
        "allocator_edge_sign_convention": (
            "paper_short_negative_signed_move_is_positive_economic_edge"
            if mode == "paper" else "live_existing_positive_edge_semantics"
        ),
        "min_qty": row.min_qty,
        "step_size": row.step_size,
        "min_notional": row.min_notional,
        "risk_envelope": {
            "max_total_portfolio_risk_pct": envelope.max_total_portfolio_risk_pct,
            "max_single_symbol_exposure_pct": envelope.max_single_symbol_exposure_pct,
            "max_daily_drawdown_pct": envelope.max_daily_drawdown_pct,
            "max_loss_per_trade_pct": envelope.max_loss_per_trade_pct,
            "min_available_margin_buffer_pct": envelope.min_available_margin_buffer_pct,
            "max_correlation_exposure_pct": envelope.max_correlation_exposure_pct,
            "min_liquidation_buffer_bps": envelope.min_liquidation_buffer_bps,
            "max_effective_leverage": envelope.max_effective_leverage,
            "tail_loss_multiplier": envelope.tail_loss_multiplier,
            "emergency_absolute_cap_usdt": envelope.emergency_absolute_cap_usdt,
        },
    }
    provider_context = (
        row.lineage_ids.get("provider_context")
        if isinstance(row.lineage_ids.get("provider_context"), dict)
        else None
    )
    if provider_context is not None:
        model_inputs["provider_context"] = provider_context
        model_inputs["optional_provider_failures_core_blocking"] = False
    model_inputs.update(hedge_selection)
    if leverage_selection:
        model_inputs.update(leverage_selection)
    if margin_mode_selection:
        model_inputs.update(margin_mode_selection)
    gross_notional = max(0.0, target_notional)
    fee_bps = max(0.0, row.fee_bps)
    slippage_bps = max(0.0, row.slippage_bps)
    funding_bps = abs(row.expected_funding_bps)
    expected_fees_usd = gross_notional * fee_bps / 10000.0
    expected_slippage_usd = gross_notional * slippage_bps / 10000.0
    expected_funding_usd = gross_notional * funding_bps / 10000.0
    expected_net_pnl_usd = gross_notional * sizing_row.expected_move_after_cost_bps / 10000.0
    expected_gross_pnl_usd = expected_net_pnl_usd + expected_fees_usd + expected_slippage_usd + expected_funding_usd
    expected_shortfall_usd = risk_budget_usd * max(0.0, envelope.tail_loss_multiplier)
    hedge_budget_usd = risk_budget_usd * hedge_budget_pct
    modeled_stop_loss_usd = (
        None
        if stop_distance_bps is None
        else gross_notional * max(0.0, stop_distance_bps) / 10000.0
    )
    max_loss_if_stop_hit = (
        None
        if modeled_stop_loss_usd is None
        else modeled_stop_loss_usd + expected_fees_usd + expected_slippage_usd + expected_funding_usd
    )
    risk_reward = (
        None
        if max_loss_if_stop_hit is None or max_loss_if_stop_hit <= 0.0
        else expected_net_pnl_usd / max_loss_if_stop_hit
    )
    portfolio_exposure_after_trade = max(0.0, row.total_exposure_usdt) + gross_notional
    correlation_exposure_after_trade = _clamp(
        max(0.0, row.correlation_exposure_pct)
        + (0.0 if row.equity <= 0.0 else gross_notional / row.equity),
        0.0,
        1.0,
    )
    risk_of_ruin_contribution = _clamp(
        0.0
        if row.equity <= 0.0 or max_loss_if_stop_hit is None
        else (
            (max_loss_if_stop_hit / row.equity)
            * (1.0 + max(0.0, row.drawdown_bps) / max(1.0, envelope.max_daily_drawdown_pct * 10000.0))
            * (1.0 + max(0.0, row.correlation_exposure_pct) / max(1e-9, envelope.max_correlation_exposure_pct))
        ),
        0.0,
        1.0,
    )
    liquidation_distance_usd = (
        None
        if liquidation_buffer_bps is None
        else gross_notional * max(0.0, liquidation_buffer_bps) / 10000.0
    )
    hedge_plan = evaluate_hedge_intent(
        candidate={
            "symbol": row.symbol,
            "action": row.action,
            "side": row.action,
            "target_notional_usd": gross_notional,
            "gross_notional_usd": gross_notional,
        },
        positions=(),
        equity_usd=row.equity,
        risk_budget_usd=risk_budget_usd,
        hedge_budget_usd=hedge_budget_usd,
        max_loss_usd=max_loss_if_stop_hit,
        expected_net_pnl_usd=expected_net_pnl_usd,
        spread_bps=row.spread_bps,
        slippage_bps=row.slippage_bps,
        fee_bps=row.fee_bps,
        funding_bps=row.expected_funding_bps,
        correlation_exposure_pct=correlation_exposure_after_trade,
        liquidation_buffer_usd=liquidation_distance_usd,
        edge_remains=expected_net_pnl_usd > 0.0 and gross_notional > 0.0,
    )
    cross_margin = simulate_cross_margin_stress(
        equity_usd=row.equity,
        available_margin_usd=row.available_margin,
        target_notional_usd=gross_notional,
        allocated_margin_usd=allocated_margin,
        recommended_leverage=leverage,
        max_loss_usd=max_loss_if_stop_hit,
        hedge_plan=hedge_plan,
        requested_margin_mode=margin_mode or ("isolated_paper_simulated" if mode == "paper" else "isolated"),
        maintenance_margin_rate=row.maintenance_margin_rate,
        expectancy_usd=expected_net_pnl_usd,
    )
    recommended_margin_mode = str(cross_margin.get("recommended_margin_mode") or margin_mode or "isolated_paper_simulated")
    model_inputs.update({
        "hedge_engine": hedge_plan,
        "cross_margin_stress": cross_margin,
        "liquidation_distance_usd": None if liquidation_distance_usd is None else round(liquidation_distance_usd, 8),
        "expected_gross_pnl_usd": round(expected_gross_pnl_usd, 8),
        "max_loss_usd": None if max_loss_if_stop_hit is None else round(max_loss_if_stop_hit, 8),
        "stop_loss_usd": None if modeled_stop_loss_usd is None else round(modeled_stop_loss_usd, 8),
        "take_profit_usd": round(max(0.0, expected_gross_pnl_usd), 8),
    })
    return AllocationResult(
        adaptive_capital_policy_version=ADAPTIVE_CAPITAL_POLICY_VERSION,
        allocation_id=_allocation_id(row, mode),
        symbol=row.symbol,
        timeframe=row.timeframe,
        action=row.action,
        decision=decision,  # type: ignore[arg-type]
        target_notional_usdt=round(gross_notional, 8),
        target_quantity=round(max(0.0, target_quantity), 12),
        risk_budget_usd=round(max(0.0, risk_budget_usd), 8),
        gross_notional_usd=round(gross_notional, 8),
        allocated_margin_usd=round(max(0.0, allocated_margin), 8),
        recommended_leverage=round(max(1.0, leverage), 8),
        effective_leverage=round(max(1.0, leverage), 8),
        recommended_margin_mode=recommended_margin_mode,
        stop_distance_bps=None if stop_distance_bps is None else round(max(0.0, stop_distance_bps), 8),
        liquidation_price_estimate=None if liquidation_price is None else round(max(0.0, liquidation_price), 12),
        liquidation_buffer_bps=None if liquidation_buffer_bps is None else round(liquidation_buffer_bps, 8),
        max_loss_if_stop_hit=None if max_loss_if_stop_hit is None else round(max_loss_if_stop_hit, 8),
        risk_reward=None if risk_reward is None else round(risk_reward, 8),
        risk_of_ruin_contribution=round(risk_of_ruin_contribution, 8),
        portfolio_exposure_after_trade=round(portfolio_exposure_after_trade, 8),
        correlation_exposure_after_trade=round(correlation_exposure_after_trade, 8),
        expected_fees_usd=round(expected_fees_usd, 8),
        expected_slippage_usd=round(expected_slippage_usd, 8),
        expected_funding_usd=round(expected_funding_usd, 8),
        expected_gross_pnl_usd=round(expected_gross_pnl_usd, 8),
        expected_net_pnl_usd=round(expected_net_pnl_usd, 8),
        expected_shortfall_usd=round(expected_shortfall_usd, 8),
        max_loss_usd=None if max_loss_if_stop_hit is None else round(max_loss_if_stop_hit, 8),
        stop_loss_usd=None if modeled_stop_loss_usd is None else round(modeled_stop_loss_usd, 8),
        take_profit_usd=round(max(0.0, expected_gross_pnl_usd), 8),
        mfe_usd=round(max(0.0, expected_gross_pnl_usd), 8),
        mae_usd=None if modeled_stop_loss_usd is None else round(modeled_stop_loss_usd, 8),
        liquidation_distance_usd=None if liquidation_distance_usd is None else round(liquidation_distance_usd, 8),
        hedge_budget_usd=round(hedge_budget_usd, 8),
        net_delta_usd=round(float(hedge_plan.get("net_delta_usd") or 0.0), 8),
        gross_exposure_usd=round(float(hedge_plan.get("gross_exposure_usd") or 0.0), 8),
        long_exposure_usd=round(float(hedge_plan.get("long_exposure_usd") or 0.0), 8),
        short_exposure_usd=round(float(hedge_plan.get("short_exposure_usd") or 0.0), 8),
        btc_beta_exposure_usd=round(float(hedge_plan.get("btc_beta_exposure_usd") or 0.0), 8),
        eth_beta_exposure_usd=round(float(hedge_plan.get("eth_beta_exposure_usd") or 0.0), 8),
        sector_exposure_usd=dict(hedge_plan.get("sector_exposure_usd") or {}),
        correlation_exposure_usd=round(float(hedge_plan.get("correlation_exposure_usd") or 0.0), 8),
        hedge_required=bool(hedge_plan.get("hedge_required")),
        hedge_action=str(hedge_plan.get("hedge_action") or "NO_HEDGE"),
        hedge_reason=str(hedge_plan.get("hedge_reason") or ""),
        hedge_symbol=hedge_plan.get("hedge_symbol"),
        hedge_side=hedge_plan.get("hedge_side"),
        hedge_notional_usd=round(float(hedge_plan.get("hedge_notional_usd") or 0.0), 8),
        hedge_margin_usd=round(float(hedge_plan.get("hedge_margin_usd") or 0.0), 8),
        hedge_leverage=round(float(hedge_plan.get("hedge_leverage") or 1.0), 8),
        hedge_cost_usd=round(float(hedge_plan.get("hedge_cost_usd") or 0.0), 8),
        hedge_expected_risk_reduction_usd=round(float(hedge_plan.get("hedge_expected_risk_reduction_usd") or 0.0), 8),
        hedge_net_benefit_usd=round(float(hedge_plan.get("hedge_net_benefit_usd") or 0.0), 8),
        hedge_exit_plan=dict(hedge_plan.get("hedge_exit_plan") or {}),
        isolated_margin_required_usd=round(float(cross_margin.get("isolated_margin_required_usd") or 0.0), 8),
        cross_margin_stress_used_usd=round(float(cross_margin.get("cross_margin_stress_used_usd") or 0.0), 8),
        cross_margin_available_buffer_usd=round(float(cross_margin.get("cross_margin_available_buffer_usd") or 0.0), 8),
        portfolio_liquidation_buffer_usd=round(float(cross_margin.get("portfolio_liquidation_buffer_usd") or 0.0), 8),
        worst_case_portfolio_loss_usd=round(float(cross_margin.get("worst_case_portfolio_loss_usd") or 0.0), 8),
        maintenance_margin_estimate_usd=round(float(cross_margin.get("maintenance_margin_estimate_usd") or 0.0), 8),
        margin_call_risk=str(cross_margin.get("margin_call_risk") or "UNKNOWN"),
        cross_margin_safe=bool(cross_margin.get("cross_margin_safe")),
        why_cross_margin_or_isolated=str(cross_margin.get("why_cross_margin_or_isolated") or ""),
        capital_allocation_reason=final_size_reason,
        risk_budget_pct_of_equity=0.0 if row.equity <= 0 else round(risk_budget_usd / row.equity, 8),
        risk_budget_pct_of_available_margin=round(risk_budget_usd / available_margin, 8),
        confidence_calibrated=row.confidence_calibrated,
        expected_move_after_cost_bps=row.expected_move_after_cost_bps,
        market_state_integrity_score=row.market_state_integrity_score,
        volatility_adjustment=round(volatility_adjustment(sizing_row), 8),
        liquidity_adjustment=round(liquidity_adjustment(sizing_row), 8),
        spread_slippage_adjustment=round(spread_slippage_adjustment(sizing_row), 8),
        drawdown_adjustment=round(drawdown_adjustment(sizing_row, envelope), 8),
        exposure_adjustment=round(exposure_adjustment(sizing_row, envelope), 8),
        correlation_adjustment=round(correlation_adjustment(sizing_row, envelope), 8),
        regime_adjustment=round(regime_adjustment(sizing_row), 8),
        exchange_min_order_adjustment=round(min_order_notional(min_qty=row.min_qty, min_notional=row.min_notional, price=row.price), 8),
        final_size_reason=final_size_reason,
        risk_veto_reason_if_blocked=risk_veto_reason,
        model_inputs=model_inputs,
        lineage_ids=dict(row.lineage_ids),
    )


def _stop_distance_bps(row: AllocationInput) -> float:
    explicit = row.stop_distance_bps if row.stop_distance_bps is not None else None
    if explicit is not None and explicit > 0:
        return float(explicit)
    cost_floor = max(1.0, row.spread_bps + row.slippage_bps + row.fee_bps)
    volatility_floor = max(10.0, row.volatility_bps * 1.5)
    return max(cost_floor * 2.0, volatility_floor)


def _liquidation_distance_bps(*, leverage: float, maintenance_margin_rate: float) -> float:
    if leverage <= 0:
        return 0.0
    return max(0.0, (1.0 / leverage - max(0.0, maintenance_margin_rate)) * 10000.0)


def _liquidation_price(*, side: str, price: float, leverage: float, maintenance_margin_rate: float) -> float | None:
    if price <= 0 or leverage <= 0:
        return None
    distance = 1.0 / leverage - max(0.0, maintenance_margin_rate)
    if side == "short":
        return price * (1.0 + max(0.0, distance))
    return max(0.0, price * (1.0 - max(0.0, distance)))


def _select_margin_configuration(
    row: AllocationInput,
    *,
    gross_notional: float,
    stop_distance_bps: float,
    envelope: RiskEnvelope,
    target_leverage: float = 1.0,
) -> tuple[float, float, float | None, float | None] | None:
    usable_margin = available_margin_budget_usdt(row, envelope)
    reserve_bps = max(0.0, row.fee_bps) + max(0.0, row.slippage_bps) + abs(row.expected_funding_bps)
    permitted = sorted(
        {
            float(value)
            for value in row.permitted_leverage_values
            if value is not None and float(value) >= 1.0 and float(value) <= max(1.0, envelope.max_effective_leverage)
        }
    )
    if not permitted:
        permitted = [1.0]
    leverage_floor = max(1.0, target_leverage)
    preferred = sorted([value for value in permitted if value <= leverage_floor], reverse=True)
    fallback = sorted([value for value in permitted if value > leverage_floor])
    for leverage in [*preferred, *fallback]:
        allocated_margin = gross_notional / leverage if leverage > 0 else gross_notional
        if allocated_margin > usable_margin:
            continue
        liquidation_distance = _liquidation_distance_bps(
            leverage=leverage,
            maintenance_margin_rate=row.maintenance_margin_rate,
        )
        liquidation_buffer = liquidation_distance - stop_distance_bps - reserve_bps
        if liquidation_buffer < envelope.min_liquidation_buffer_bps:
            continue
        return (
            leverage,
            allocated_margin,
            _liquidation_price(
                side=row.action,
                price=row.price,
                leverage=leverage,
                maintenance_margin_rate=row.maintenance_margin_rate,
            ),
            liquidation_buffer,
        )
    return None


def _allocate(row: AllocationInput, *, mode: str, envelope: RiskEnvelope) -> AllocationResult:
    sizing_row = _paper_sizing_row(row, mode=mode)
    economic_edge_bps = sizing_row.expected_move_after_cost_bps
    if row.risk_veto:
        return _block(row, mode=mode, decision="BLOCK_EXPOSURE_BUDGET", reason=row.risk_veto_reason or "risk_envelope_veto", envelope=envelope)
    if row.market_state_integrity_score < 70.0:
        return _block(row, mode=mode, decision="BLOCK_BAD_MARKET_STATE", reason="market_state_integrity_score_below_minimum", envelope=envelope)
    if row.confidence_calibrated < 0.50:
        return _block(row, mode=mode, decision="BLOCK_LOW_CONFIDENCE", reason="confidence_below_adaptive_minimum", envelope=envelope)
    if economic_edge_bps <= 0.0:
        return _block(row, mode=mode, decision="BLOCK_NO_EDGE", reason="expected_move_after_cost_not_positive", envelope=envelope)
    if row.liquidity_score <= 0.05:
        return _block(row, mode=mode, decision="BLOCK_INSUFFICIENT_LIQUIDITY", reason="liquidity_score_too_low", envelope=envelope)
    if row.spread_bps + row.slippage_bps >= max(1.0, economic_edge_bps):
        return _block(row, mode=mode, decision="BLOCK_SPREAD_SLIPPAGE", reason="spread_plus_slippage_exceeds_expected_edge", envelope=envelope)
    if row.drawdown_bps >= envelope.max_daily_drawdown_pct * 10000.0:
        return _block(row, mode=mode, decision="BLOCK_DRAWDOWN_GUARD", reason="drawdown_guard_breached", envelope=envelope)
    if mode == "live" and row.available_margin <= 0:
        return _block(row, mode=mode, decision="BLOCK_INSUFFICIENT_MARGIN", reason="available_margin_missing_or_zero", envelope=envelope)

    ceiling = risk_envelope_gross_notional_ceiling(row, envelope)
    if ceiling <= 0:
        return _block(row, mode=mode, decision="BLOCK_EXPOSURE_BUDGET", reason="risk_envelope_budget_exhausted", envelope=envelope)

    budget_pct = adaptive_budget_pct(sizing_row, envelope)
    risk_budget_usd = row.equity * budget_pct
    stop_distance_bps = _stop_distance_bps(row)
    if risk_budget_usd <= 0:
        return _block(row, mode=mode, decision="BLOCK_NO_EDGE", reason="risk_budget_after_adjustments_is_zero", envelope=envelope)
    target_notional = min(risk_budget_usd / (stop_distance_bps / 10000.0), ceiling)
    min_notional = min_order_notional(min_qty=row.min_qty, min_notional=row.min_notional, price=row.price)
    if min_notional > 0 and target_notional < min_notional:
        if ceiling >= min_notional:
            target_notional = min_notional
        else:
            return _block(row, mode=mode, decision="BLOCK_EXCHANGE_MIN_ORDER", reason="adaptive_size_below_exchange_min_order", envelope=envelope)
    target_leverage, leverage_selection = _adaptive_leverage_target_selection(sizing_row, envelope, mode=mode)
    margin_config = _select_margin_configuration(
        sizing_row,
        gross_notional=target_notional,
        stop_distance_bps=stop_distance_bps,
        envelope=envelope,
        target_leverage=target_leverage,
    )
    if margin_config is None:
        return _block(row, mode=mode, decision="BLOCK_LIQUIDATION_RISK", reason="no_safe_leverage_margin_configuration", envelope=envelope)
    leverage, allocated_margin, liquidation_price, liquidation_buffer_bps = margin_config
    margin_mode, margin_mode_selection = _adaptive_margin_mode_selection(
        row,
        envelope,
        mode=mode,
        leverage=leverage,
        liquidation_buffer_bps=liquidation_buffer_bps,
    )
    if mode == "live" and allocated_margin > available_margin_budget_usdt(row, envelope):
        return _block(row, mode=mode, decision="BLOCK_INSUFFICIENT_MARGIN", reason="adaptive_margin_exceeds_available_margin_after_buffer", envelope=envelope)
    quantity = 0.0 if row.price <= 0 else target_notional / row.price
    quantity = round_down_to_step(quantity, row.step_size)
    if quantity <= 0:
        return _block(row, mode=mode, decision="BLOCK_EXCHANGE_MIN_ORDER", reason="quantity_rounds_to_zero", envelope=envelope)
    adjusted_notional = quantity * row.price
    decision = "ALLOW_WITH_SIZE" if adjusted_notional >= target_notional * 0.95 else "REDUCE_SIZE"
    result = _result(
        row,
        mode=mode,
        envelope=envelope,
        sizing_row=sizing_row,
        decision=decision,
        target_notional=adjusted_notional,
        target_quantity=quantity,
        risk_budget_usd=risk_budget_usd,
        allocated_margin=allocated_margin,
        leverage=leverage,
        stop_distance_bps=stop_distance_bps,
        liquidation_price=liquidation_price,
        liquidation_buffer_bps=liquidation_buffer_bps,
        final_size_reason="adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
        leverage_selection={
            **leverage_selection,
            "selected_leverage": round(leverage, 8),
            "selected_allocated_margin_usd": round(allocated_margin, 8),
        },
        margin_mode=margin_mode,
        margin_mode_selection=margin_mode_selection,
    )
    return result


def allocate_paper_candidate(row: AllocationInput, envelope: RiskEnvelope | None = None) -> AllocationResult:
    return _allocate(row, mode="paper", envelope=envelope or RiskEnvelope())


def allocate_live_candidate(row: AllocationInput, envelope: RiskEnvelope | None = None) -> AllocationResult:
    return _allocate(row, mode="live", envelope=envelope or RiskEnvelope())


__all__ = [
    "allocate_paper_candidate",
    "allocate_live_candidate",
    "explain_allocation",
]
