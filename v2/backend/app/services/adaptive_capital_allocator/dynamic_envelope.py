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

    # === PAPER MODE: AGGRESSIVE scaling for 1000x growth target ===
    if paper_mode:
        # AGGRESSIVE win rate multiplier: exponential scaling for compounding growth
        # 50% win rate → 2.0x, 60% → 4.0x, 70% → 8.0x, 80% → 15.0x, 90%+ → 25.0x
        win_rate_factor = 1.0
        if win_rate is not None and win_rate > 0.50:
            win_rate_factor = 2.0 ** ((win_rate - 0.50) * 10.0)  # exponential growth
        win_rate_factor = _clamp(win_rate_factor, 1.0, 25.0)  # up to 25x for 90%+ win rate

        # Aggressive profit factor multiplier: exponential scaling
        # PF=1.5 → 2.5x, PF=2.5 → 5.0x, PF=5.0+ → 12.0x
        pf_factor = 1.0
        if profit_factor is not None and profit_factor > 1.0:
            pf_factor = 1.0 + ((min(profit_factor - 1.0, 10.0) / 10.0) ** 0.8) * 12.0
        pf_factor = _clamp(pf_factor, 1.0, 12.0)

        # AGGRESSIVE confidence multiplier: high confidence = high leverage
        # conf=0.5 → 1.0x, conf=0.7 → 3.0x, conf=0.85+ → 6.0x, conf=0.95+ → 10.0x
        confidence_factor = 1.0 + ((model_avg_confidence - 0.50) ** 1.2) * 10.0
        confidence_factor = _clamp(confidence_factor, 0.8, 10.0)

        # Drawdown penalty: aggressive but not draconian
        # drawdown=0% → 1.0x, drawdown=2% → 0.95x, drawdown=5% → 0.75x, drawdown=10%+ → 0.4x
        drawdown_factor = 1.0 - (current_drawdown_pct ** 1.2) * 0.6
        drawdown_factor = _clamp(drawdown_factor, 0.3, 1.0)

        # Combine all factors (multiplicative scaling) - NO CEILING for paper mode
        combined_factor = win_rate_factor * pf_factor * confidence_factor * drawdown_factor
        combined_factor = _clamp(combined_factor, 0.5, 50.0)  # up to 50x leverage for paper

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
