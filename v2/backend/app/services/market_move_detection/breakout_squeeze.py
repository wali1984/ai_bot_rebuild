"""Production-equivalent major-move candidate detector (runs in paper execution mode).

Architecture principle:
    This detector uses the full production feature context — the same inputs that
    would be required for live execution. No simplified paper-only subset.
    BTC/ETH/SOL are correlation anchors, not the only trading universe.
"""
from __future__ import annotations

import hashlib
import statistics
from typing import Iterable

from .contracts import BreakoutSqueezeSignal, CandleInput, DetectionContext


def _mean(values: Iterable[float]) -> float:
    items = [float(value) for value in values]
    return statistics.fmean(items) if items else 0.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _stable_id(symbol: str, timeframe: str, close_time_ms: int, direction: str) -> str:
    digest = hashlib.sha256(f"{symbol}|{timeframe}|{close_time_ms}|{direction}".encode()).hexdigest()[:24]
    return f"major_move_{digest}"


def _reject_if_not_point_in_time(candles: list[CandleInput], context: DetectionContext) -> list[str]:
    rejects: list[str] = []
    for candle in candles:
        if candle.closed is not True:
            rejects.append("UNCLOSED_CANDLE")
        if candle.available_at_ms > context.decision_time_ms:
            rejects.append("AVAILABLE_AT_AFTER_DECISION_TIME")
        if candle.close_time_ms > context.decision_time_ms:
            rejects.append("CANDLE_CLOSE_AFTER_DECISION_TIME")
    return sorted(set(rejects))


def detect_breakout_squeeze(
    *,
    symbol: str,
    timeframe: str,
    candles: list[CandleInput],
    context: DetectionContext,
    min_evidence_score: float = 0.50,
) -> BreakoutSqueezeSignal:
    """Return a paper-only major-move signal or a blocked diagnostic signal.

    The detector intentionally operates on closed candles only and does not use
    realized future returns. It is a candidate generator for paper routing, not
    a live execution approval.
    """
    ordered = sorted(candles, key=lambda item: item.close_time_ms)
    rejects = _reject_if_not_point_in_time(ordered, context)
    if len(ordered) < 4:
        rejects.append("INSUFFICIENT_CLOSED_CANDLE_HISTORY")
    if not context.feature_coverage_sufficient():
        missing = context.missing_feature_families()
        rejects.append(f"FEATURE_COVERAGE_INSUFFICIENT:{','.join(missing)}")

    if rejects:
        last = ordered[-1] if ordered else None
        return BreakoutSqueezeSignal(
            major_move_signal_id=_stable_id(symbol, timeframe, last.close_time_ms if last else 0, "blocked"),
            symbol=symbol,
            timeframe=timeframe,
            direction="blocked",
            move_probability=0.0,
            expected_move_after_cost_bps=0.0,
            confidence=0.0,
            evidence_score=0.0,
            regime="blocked_invalid_point_in_time",
            reasons=(),
            reject_reasons=tuple(sorted(set(rejects))),
        )

    last = ordered[-1]
    prev = ordered[-2]
    baseline = ordered[:-1]
    move_bps = ((last.close - prev.close) / max(abs(prev.close), 1e-12)) * 10_000.0
    candle_range_bps = ((last.high - last.low) / max(abs(prev.close), 1e-12)) * 10_000.0
    avg_range_bps = _mean(((row.high - row.low) / max(abs(row.close), 1e-12)) * 10_000.0 for row in baseline)
    avg_volume = _mean(row.volume for row in baseline)
    volume_accel = last.volume / max(avg_volume, 1e-12)
    volatility_expansion = candle_range_bps / max(avg_range_bps, 1e-12)
    direction = "long" if move_bps > 0 else "short"

    reasons: list[str] = []
    score = 0.0
    if abs(move_bps) >= 8.0:
        score += 0.20
        reasons.append("closed_candle_directional_impulse")
    if volume_accel >= 1.35:
        score += 0.18
        reasons.append("volume_acceleration")
    if volatility_expansion >= 1.25:
        score += 0.16
        reasons.append("atr_or_range_expansion")
    if context.correlated_regime_confirmed:
        score += 0.16
        reasons.append("btc_eth_sol_correlated_regime")
    if context.orderbook_imbalance is not None and abs(context.orderbook_imbalance) >= 0.12:
        score += 0.10
        reasons.append("orderbook_imbalance")
    if context.liquidation_pressure is not None and context.liquidation_pressure >= 0.35:
        score += 0.08
        reasons.append("liquidation_pressure")
    if context.oi_change_pct is not None and abs(context.oi_change_pct) >= 0.005:
        score += 0.06
        reasons.append("open_interest_expansion")
    if context.public_intel_score is not None and context.public_intel_score >= 0.55:
        score += 0.04
        reasons.append("public_intel_confirmation")

    spread = abs(context.spread_bps or 0.0)
    slippage = abs(context.slippage_bps or 0.0)
    expected_after_cost = abs(move_bps) - spread - slippage
    if expected_after_cost >= 10.0:
        score += 0.14
        reasons.append("positive_after_cost_impulse")
    score = _clamp(score)
    confidence = _clamp(0.35 + score * 0.55)
    probability = _clamp(0.30 + score * 0.60)
    reject_reasons: list[str] = []
    if score < min_evidence_score:
        reject_reasons.append("EVIDENCE_SCORE_BELOW_THRESHOLD")
    if expected_after_cost <= 0:
        reject_reasons.append("EXPECTED_MOVE_AFTER_COST_NOT_POSITIVE")

    return BreakoutSqueezeSignal(
        major_move_signal_id=_stable_id(symbol, timeframe, last.close_time_ms, direction),
        symbol=symbol,
        timeframe=timeframe,
        direction=direction if not reject_reasons else "blocked",
        move_probability=round(probability, 6),
        expected_move_after_cost_bps=round(expected_after_cost, 6),
        confidence=round(confidence, 6),
        evidence_score=round(score, 6),
        regime="correlated_breakout_squeeze" if context.correlated_regime_confirmed else "single_symbol_breakout",
        reasons=tuple(reasons),
        reject_reasons=tuple(reject_reasons),
    )
