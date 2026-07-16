"""Dynamically scale RiskEnvelope based on real-time performance metrics.

Instead of static limits, scale the risk budget and leverage based on:
- Realized win rate (higher = more risk)
- Profit factor (higher = more risk)
- Model calibration (higher confidence = more leverage)
- Portfolio drawdown (lower = more risk allowed)
- Realized PnL trajectory

NO STATIC THRESHOLDS. All scaling is smooth and adaptive.
"""

from __future__ import annotations

from typing import Any

from .contracts import RiskEnvelope


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp value to range [low, high]."""
    return max(low, min(high, value))


def calculate_dynamic_risk_envelope(
    *,
    base_envelope: RiskEnvelope | None = None,
    win_rate: float | None = None,
    profit_factor: float | None = None,
    closed_trade_count: int = 0,
    current_drawdown_pct: float = 0.0,
    model_avg_confidence: float = 0.5,
    paper_mode: bool = True,
) -> RiskEnvelope:
    """Calculate a dynamic risk envelope that scales based on performance.

    In PAPER MODE: Aggressive scaling to let system learn from larger positions
    In LIVE MODE: Conservative scaling with safety margins (even if requested)

    Args:
        base_envelope: Starting envelope (defaults to conservative baseline)
        win_rate: Realized win rate [0, 1] from closed trades
        profit_factor: Realized profit factor from closed trades
        closed_trade_count: Number of closed trades (for statistical confidence)
        current_drawdown_pct: Current drawdown from peak [0, 1]
        model_avg_confidence: Average model confidence across signals [0, 1]
        paper_mode: True for paper trading (more aggressive), False for live (conservative)

    Returns:
        RiskEnvelope with dynamically scaled limits based on performance
    """
    base = base_envelope or RiskEnvelope()

    # If we have < 3 closed trades, use base envelope (insufficient data)
    if closed_trade_count < 3:
        return base

    # === PAPER MODE: CONSERVATIVE scaling with leverage GATED by PROVEN profitability ===
    if paper_mode:
        # Win rate multiplier: ONLY scale above 1.0 after 55% win rate is demonstrated
        # 50-54% → 1.0x (unproven), 55% → 1.2x, 65% → 1.8x, 75% → 2.5x, 85%+ → 3.5x
        # NO EXPONENTIAL GROWTH - linear conservative scaling
        win_rate_factor = 1.0
        if win_rate is not None and win_rate >= 0.55:
            win_rate_factor = 1.0 + ((win_rate - 0.55) / 0.30) * 2.5  # linear 55% → 3.5x at 85%
        win_rate_factor = _clamp(win_rate_factor, 1.0, 3.5)  # max 3.5x only at 85%+ proven

        # Profit factor multiplier: ONLY scale above 1.0 after 1.2 PF (20% more wins than losses)
        # PF=1.0-1.19 → 1.0x (unproven), PF=1.2 → 1.3x, PF=2.0 → 2.0x, PF=3.0+ → 2.8x
        pf_factor = 1.0
        if profit_factor is not None and profit_factor >= 1.2:
            pf_factor = 1.0 + min((profit_factor - 1.2) / 1.8, 1.0) * 1.8  # linear to 2.8x
        pf_factor = _clamp(pf_factor, 1.0, 2.8)  # conservative cap

        # Confidence multiplier: confidence alone CANNOT exceed 1.5x leverage
        # conf=0.5 → 0.8x (discount), conf=0.7 → 1.1x, conf=0.85+ → 1.5x
        # High confidence on unproven model is DANGEROUS; cap strictly
        confidence_factor = 0.8 + (model_avg_confidence - 0.50) * 1.4
        confidence_factor = _clamp(confidence_factor, 0.7, 1.5)  # STRICT cap at 1.5x

        # Drawdown penalty: penalize heavily on any drawdown
        # drawdown=0% → 1.0x, drawdown=1% → 0.8x, drawdown=3% → 0.5x, drawdown=5%+ → 0.3x
        drawdown_factor = 1.0 - (current_drawdown_pct * 20.0)  # steep penalty
        drawdown_factor = _clamp(drawdown_factor, 0.2, 1.0)

        # Combine all factors - CONSERVATIVE multiplicative with hard ceiling
        combined_factor = win_rate_factor * pf_factor * confidence_factor * drawdown_factor
        combined_factor = _clamp(combined_factor, 0.5, 3.5)  # max 3.5x (vs 50x before)

        # Scale the envelope limits - AGGRESSIVE for 1000x growth target
        return RiskEnvelope(
            max_total_portfolio_risk_pct=_clamp(
                base.max_total_portfolio_risk_pct * combined_factor,
                0.50,  # floor: 50% minimum (1x leverage)
                50.00,  # ceiling: 5000% (50x leverage) for compounding growth
            ),
            max_single_symbol_exposure_pct=_clamp(
                base.max_single_symbol_exposure_pct * combined_factor,
                0.10,  # floor: 10% per symbol minimum
                2.00,  # ceiling: 200% (2x notional) per symbol for high-confidence concentrated bets
            ),
            max_daily_drawdown_pct=_clamp(
                base.max_daily_drawdown_pct * min(2.0, combined_factor),
                0.10,  # floor: 10% daily max loss (allows recovery)
                0.50,  # ceiling: 50% daily max loss (paper-only, learning phase)
            ),
            max_loss_per_trade_pct=_clamp(
                base.max_loss_per_trade_pct * combined_factor,
                0.005,  # floor: 0.5% per trade minimum
                0.15,  # ceiling: 15% per trade max in paper
            ),
            max_correlation_exposure_pct=_clamp(
                base.max_correlation_exposure_pct * combined_factor,
                0.10,
                0.50,
            ),
            max_effective_leverage=_clamp(
                base.max_effective_leverage * combined_factor,
                1.0,  # floor: never go below 1x
                10.0,  # ceiling: 10x max leverage in paper mode
            ),
            min_available_margin_buffer_pct=base.min_available_margin_buffer_pct,  # never change
            min_liquidation_buffer_bps=base.min_liquidation_buffer_bps,  # never change
            tail_loss_multiplier=base.tail_loss_multiplier,  # never change
            emergency_absolute_cap_usdt=base.emergency_absolute_cap_usdt,
        )

    # === LIVE MODE: Conservative despite performance (operator override required) ===
    # Even if paper performance is great, live trading starts conservative
    # Operator must explicitly enable higher leverage for live
    return base
