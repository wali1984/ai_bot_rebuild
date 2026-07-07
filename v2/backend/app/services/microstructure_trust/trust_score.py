"""Final microstructure trust score and action classification."""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from .feed_quality import iso_now


class MicrostructureAction(StrEnum):
    ALLOW = "ALLOW"
    REDUCE_SIZE = "REDUCE_SIZE"
    SHADOW_ONLY = "SHADOW_ONLY"
    NO_TRADE = "NO_TRADE"
    CLOSE_OR_REDUCE_ONLY = "CLOSE_OR_REDUCE_ONLY"


def _float(payload: Mapping[str, Any] | None, *keys: str, default: float | None = None) -> float | None:
    if not isinstance(payload, Mapping):
        return default
    for key in keys:
        value = payload.get(key)
        try:
            if value is None:
                continue
            out = float(value)
        except (TypeError, ValueError):
            continue
        if out == out and out not in (float("inf"), float("-inf")):
            return out
    return default


def classify_microstructure_trust(score: float | None, *, position_open: bool = False) -> tuple[str, MicrostructureAction]:
    if score is None:
        return "UNTRUSTED_NO_TRADE", MicrostructureAction.NO_TRADE
    score = max(0.0, min(1.0, float(score)))
    if score < 0.25:
        return "UNTRUSTED_NO_TRADE", MicrostructureAction.CLOSE_OR_REDUCE_ONLY if position_open else MicrostructureAction.NO_TRADE
    if score < 0.45:
        return "SHADOW_ONLY", MicrostructureAction.SHADOW_ONLY
    if score < 0.65:
        return "REDUCED_SIZE", MicrostructureAction.REDUCE_SIZE
    if score < 0.80:
        return "NORMAL_SIZE_ALLOWED", MicrostructureAction.ALLOW
    return "HIGH_TRUST", MicrostructureAction.ALLOW


def score_microstructure_trust(
    *,
    symbol: str,
    timeframe: str,
    feed_quality: Mapping[str, Any] | None = None,
    adversarial_features: Mapping[str, Any] | None = None,
    trade_tape: Mapping[str, Any] | None = None,
    cross_venue: Mapping[str, Any] | None = None,
    sweep_risk: Mapping[str, Any] | None = None,
    realized_slippage_error: float | None = None,
    historical_bucket_performance: float | None = None,
    adaptive_minimum: float = 0.65,
    position_open: bool = False,
) -> dict[str, Any]:
    missing_components = [
        name
        for name, payload in (
            ("feed_quality", feed_quality),
            ("adversarial_features", adversarial_features),
            ("trade_tape_confirmation", trade_tape),
            ("cross_venue_confirmation", cross_venue),
            ("sweep_risk", sweep_risk),
        )
        if not isinstance(payload, Mapping)
    ]
    feed_score = _float(feed_quality, "feed_quality_score", default=0.0) or 0.0
    persistence = min(1.0, (_float(adversarial_features, "depth_persistence_ms", default=0.0) or 0.0) / 5000.0)
    cancel_pressure = _float(adversarial_features, "cancel_burst_score", default=1.0) or 1.0
    stuffing = _float(adversarial_features, "quote_stuffing_score", default=1.0) or 1.0
    pull = _float(adversarial_features, "top_book_pull_rate", default=1.0) or 1.0
    divergence = _float(adversarial_features, "book_trade_divergence_score", default=1.0) or 1.0
    tape_score = _float(trade_tape, "trade_tape_confirmation_score", default=0.0) or 0.0
    cross_score = _float(cross_venue, "cross_venue_confirmation_score", default=0.0) or 0.0
    sweep = _float(sweep_risk, "sweep_risk", default=1.0) or 1.0
    cascade = _float(sweep_risk, "cascade_risk", default=1.0) or 1.0
    slippage_penalty = min(1.0, abs(realized_slippage_error or 0.0) / 15.0)
    bucket_score = max(0.0, min(1.0, historical_bucket_performance if historical_bucket_performance is not None else 0.5))
    adversarial_score = max(0.0, 1.0 - ((cancel_pressure * 0.25) + (stuffing * 0.15) + (pull * 0.2) + (divergence * 0.25)))
    score = (
        feed_score * 0.18
        + persistence * 0.12
        + adversarial_score * 0.18
        + tape_score * 0.16
        + cross_score * 0.14
        + (1.0 - max(sweep, cascade)) * 0.14
        + (1.0 - slippage_penalty) * 0.04
        + bucket_score * 0.04
    )
    if missing_components:
        score = min(score, 0.44)
    if isinstance(feed_quality, Mapping) and feed_quality.get("fail_closed") is True:
        score = min(score, 0.24)
    if isinstance(sweep_risk, Mapping) and sweep_risk.get("direction_uncertain") is True:
        score = min(score, 0.24)
    score = max(0.0, min(1.0, score))
    tier, action = classify_microstructure_trust(score, position_open=position_open)
    if score < adaptive_minimum and action == MicrostructureAction.ALLOW:
        action = MicrostructureAction.REDUCE_SIZE
        tier = "REDUCED_SIZE"
    return {
        "schema_version": "microstructure_trust_score_v1",
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "public_orderbook_default_trust": "LOW",
        "public_book_can_approve_trade_alone": False,
        "decision_requires_cross_validation": True,
        "microstructure_trust_score": round(score, 8),
        "orderbook_trust_score": round(score, 8),
        "orderbook_trust_tier": tier,
        "microstructure_action": str(action),
        "adaptive_minimum": float(adaptive_minimum),
        "eligible_for_a_grade": bool(score >= adaptive_minimum and action == MicrostructureAction.ALLOW),
        "missing_components": missing_components,
        "feed_latency_ms": _float(feed_quality, "latency_ms", "local_latency_ms"),
        "sequence_gap_flag": 1 if (feed_quality or {}).get("sequence_gap_count", 0) else 0,
        "spread_instability": _float(adversarial_features, "spread_expansion_rate"),
        "depth_persistence": persistence,
        "cancel_pressure": cancel_pressure,
        "book_trade_divergence": max(divergence, _float(trade_tape, "book_trade_divergence_score", default=0.0) or 0.0),
        "cross_venue_confirmation": cross_score,
        "sweep_risk": sweep,
        "post_sweep_reversal_probability": _float(sweep_risk, "post_sweep_reversal_probability"),
        "liquidation_cascade_risk": cascade,
        "realized_slippage_error": realized_slippage_error,
        "generated_at": iso_now(),
    }
