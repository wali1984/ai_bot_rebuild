"""Regime and strategy compatibility before entry."""

from __future__ import annotations

from typing import Any


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def assess_regime_compatibility(candidate: dict[str, Any]) -> dict[str, Any]:
    regime = str(
        candidate.get("strategy_market_regime")
        or candidate.get("market_regime_at_entry")
        or candidate.get("market_regime")
        or ""
    ).upper()
    strategy = str(
        candidate.get("strategy_selected_mode")
        or candidate.get("strategy_id")
        or candidate.get("strategy_mode")
        or ""
    ).lower()
    side = str(candidate.get("side") or candidate.get("action") or "").lower()
    confidence = _f(candidate.get("confidence_calibrated") or candidate.get("confidence"))
    tape = _f(candidate.get("trade_tape_confirmation_score"))
    cross_venue = _f(candidate.get("cross_venue_confirmation_score"))
    liquidation = _f(candidate.get("liquidation_strength") or candidate.get("liquidation_pressure"))
    oi_change = _f(candidate.get("open_interest_change") or candidate.get("oi_change_pct"))

    reasons: list[str] = []
    score = 0.75
    if not regime:
        score = min(score, 0.35)
        reasons.append("REGIME_MISSING")
    if not strategy:
        score = min(score, 0.35)
        reasons.append("STRATEGY_MISSING")
    if strategy and "mean_reversion" in strategy and "TREND" in regime:
        score = min(score, 0.45)
        reasons.append("MEAN_REVERSION_IN_TREND_REGIME")
    if side == "short" and any(token in regime for token in ("BREAKOUT", "TREND")):
        score = min(score, 0.45)
        reasons.append("SHORT_IN_BREAKOUT_TREND_REGIME_REQUIRES_CONFIRMATION")
    if confidence is not None and confidence >= 0.70:
        confirmations = [
            value for value in (tape, cross_venue, liquidation, oi_change) if value is not None
        ]
        if len(confirmations) < 2:
            score = min(score, 0.4)
            reasons.append("HIGH_CONFIDENCE_REGIME_SHIFT_CONFIRMATION_MISSING")

    return {
        "regime": regime or None,
        "strategy_id": strategy or None,
        "regime_compatibility_score": round(score, 8),
        "regime_compatibility_reasons": reasons,
        "trade_tape_confirmation_score": tape,
        "cross_venue_confirmation_score": cross_venue,
        "liquidity_sweep_risk": _f(candidate.get("liquidity_sweep_risk") or candidate.get("sweep_risk")),
    }
