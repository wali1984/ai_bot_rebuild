from __future__ import annotations

from .contracts import AllocationInput, RiskEnvelope


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def confidence_adjustment(
    row: AllocationInput,
    *,
    continuous_from_zero: bool = False,
) -> float:
    """Scale confidence while preserving the legacy live transform by default."""
    ppo = (
        row.ppo_action_probability
        if row.ppo_action_probability is not None
        else row.confidence_calibrated
    )
    masa = (
        row.masa_confidence
        if row.masa_confidence is not None
        else row.confidence_calibrated
    )
    blended = (row.confidence_calibrated * 0.6) + (ppo * 0.25) + (masa * 0.15)
    if continuous_from_zero:
        return clamp(blended, 0.0, 1.0)
    return clamp((blended - 0.50) / 0.25, 0.0, 1.0)


def edge_adjustment(row: AllocationInput) -> float:
    return clamp(row.expected_move_after_cost_bps / 80.0, 0.0, 1.25)


def market_state_adjustment(row: AllocationInput) -> float:
    return clamp(row.market_state_integrity_score / 100.0, 0.0, 1.0)


def volatility_adjustment(row: AllocationInput) -> float:
    return clamp(80.0 / max(20.0, row.volatility_bps), 0.20, 1.25)


def liquidity_adjustment(row: AllocationInput) -> float:
    return clamp(row.liquidity_score, 0.0, 1.0)


def spread_slippage_adjustment(row: AllocationInput) -> float:
    drag = max(0.0, row.spread_bps + row.slippage_bps)
    return clamp(1.0 - (drag / max(1.0, row.expected_move_after_cost_bps + drag)), 0.0, 1.0)


def drawdown_adjustment(row: AllocationInput, envelope: RiskEnvelope) -> float:
    max_drawdown_bps = max(1.0, envelope.max_daily_drawdown_pct * 10000.0)
    return clamp(1.0 - (max(0.0, row.drawdown_bps) / max_drawdown_bps), 0.0, 1.0)


def exposure_adjustment(row: AllocationInput, envelope: RiskEnvelope) -> float:
    max_total = max(1e-9, row.equity * envelope.max_total_portfolio_risk_pct)
    return clamp(1.0 - (max(0.0, row.total_exposure_usdt) / max_total), 0.0, 1.0)


def correlation_adjustment(row: AllocationInput, envelope: RiskEnvelope) -> float:
    max_corr = max(1e-9, envelope.max_correlation_exposure_pct)
    return clamp(1.0 - (max(0.0, row.correlation_exposure_pct) / max_corr), 0.0, 1.0)


def regime_adjustment(row: AllocationInput) -> float:
    return clamp(row.regime_score, 0.2, 1.25)


def adaptive_budget_pct(
    row: AllocationInput,
    envelope: RiskEnvelope,
    *,
    continuous_confidence_from_zero: bool = False,
    policy_factor_floor: float | None = None,
) -> float:
    # Factor split (final paper directive 2026-07-31): confidence, edge,
    # cost-preference and regime are TRADING_POLICY inputs — in paper mode
    # they scale size continuously but may never zero it (that would be a
    # policy veto dressed as capacity).  The hard capacity factors (market
    # integrity, volatility, liquidity, drawdown, exposure, correlation)
    # retain full authority to zero the budget: their exhaustion is the only
    # legitimate capacity-based REMAIN_FLAT.
    policy_product = (
        confidence_adjustment(
            row,
            continuous_from_zero=continuous_confidence_from_zero,
        )
        * edge_adjustment(row)
        * spread_slippage_adjustment(row)
        * regime_adjustment(row)
    )
    if policy_factor_floor is not None:
        policy_product = max(policy_product, policy_factor_floor)
    raw = (
        envelope.max_loss_per_trade_pct
        * policy_product
        * market_state_adjustment(row)
        * volatility_adjustment(row)
        * liquidity_adjustment(row)
        * drawdown_adjustment(row, envelope)
        * exposure_adjustment(row, envelope)
        * correlation_adjustment(row, envelope)
    )
    return clamp(raw, 0.0, envelope.max_single_symbol_exposure_pct)
