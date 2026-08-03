"""Natural-language explanations for major-move paper candidates."""
from __future__ import annotations

from .contracts import BreakoutSqueezeSignal

_REASON_TEXT = {
    "closed_candle_directional_impulse": "the latest closed candle moved far enough to matter after costs",
    "volume_acceleration": "volume accelerated versus the recent closed-candle baseline",
    "atr_or_range_expansion": "the latest closed-candle range expanded versus recent volatility",
    "btc_eth_sol_correlated_regime": "BTC, ETH, and SOL were moving in the same regime",
    "orderbook_imbalance": "order book pressure supported the move",
    "liquidation_pressure": "liquidation pressure increased continuation risk",
    "open_interest_expansion": "open interest expansion showed derivatives participation",
    "public_intel_confirmation": "public-intelligence context supported attention or sentiment",
}


def explain_signal(signal: BreakoutSqueezeSignal) -> str:
    if signal.reject_reasons:
        return (
            f"{signal.symbol} {signal.timeframe} did not create a paper candidate because "
            f"{', '.join(signal.reject_reasons)}."
        )
    reasons = [_REASON_TEXT.get(reason, reason.replace("_", " ")) for reason in signal.reasons]
    reason_text = "; ".join(reasons) if reasons else "the evidence score cleared the detector threshold"
    return (
        f"{signal.symbol} {signal.timeframe} produced a paper-only {signal.direction} major-move "
        f"candidate because {reason_text}. Evidence score {signal.evidence_score:.2f}, "
        f"confidence {signal.confidence:.2f}, expected after-cost move "
        f"{signal.expected_move_after_cost_bps:.2f} bps."
    )
