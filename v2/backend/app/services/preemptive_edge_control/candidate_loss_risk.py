"""Candidate loss probability before entry."""

from __future__ import annotations

import json
import os
from typing import Any

import redis


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_adaptive_microstructure_trust_threshold() -> float:
    """Get adaptive microstructure trust threshold from Redis.

    Returns adaptive threshold based on market conditions and model quality.
    Defaults to 0.45 if adaptive state unavailable.
    """
    try:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        client = redis.from_url(redis_url, decode_responses=True)
        tuning_state = client.get("v2:orchestrator:adaptive_gate_tuning_state")
        if tuning_state:
            data = json.loads(tuning_state)
            # When B-grade enabled, we can accept slightly lower trust scores
            # because we have more historical data to learn from
            if data.get("enable_b_grade") is True:
                return 0.35  # Adaptive lower threshold when confidence in outcomes is high
            # When B-grade disabled, keep stricter threshold
            return 0.40
    except Exception:
        pass
    return 0.45  # Conservative default


def assess_candidate_loss_risk(
    *,
    cost_edge: dict[str, Any],
    confidence: dict[str, Any],
    bucket: dict[str, Any],
    regime: dict[str, Any],
    exit_plan: dict[str, Any],
    microstructure_trust_score: float | None,
) -> dict[str, Any]:
    risk = 0.20
    reasons: list[str] = []
    expected_edge = _f(cost_edge.get("expected_edge_after_cost_bps"))
    if expected_edge is None:
        risk = max(risk, 0.85)
        reasons.append("EXPECTED_EDGE_MISSING")
    elif expected_edge <= 0:
        risk = max(risk, 0.90)
        reasons.append("EXPECTED_EDGE_NON_POSITIVE")
    elif expected_edge < 5:
        risk = max(risk, 0.60)
        reasons.append("EXPECTED_EDGE_THIN")

    if bucket.get("bucket_negative") is True:
        risk = max(risk, 0.92)
        reasons.append("NEGATIVE_BUCKET_HEALTH")
    hc_rate = _f(bucket.get("recent_high_confidence_loss_rate"))
    if hc_rate is not None and hc_rate > 0.4:
        risk = max(risk, 0.88)
        reasons.append("HIGH_CONFIDENCE_LOSS_RATE_FORMING")
    atr_risk = _f(bucket.get("recent_ATR_stop_risk"))
    if atr_risk is not None and atr_risk >= 0.4:
        risk = max(risk, 0.72)
        reasons.append("ATR_STOP_RISK_FORMING")

    confidence_risk = _f(confidence.get("confidence_overstatement_risk")) or 0.0
    if confidence_risk >= 0.75:
        risk = max(risk, 0.80)
        reasons.append("CONFIDENCE_OVERSTATEMENT_HIGH")
    elif confidence_risk >= 0.5:
        risk = max(risk, 0.65)
        reasons.append("CONFIDENCE_OVERSTATEMENT_ELEVATED")

    regime_score = _f(regime.get("regime_compatibility_score"))
    if regime_score is None or regime_score < 0.5:
        risk = max(risk, 0.70)
        reasons.append("REGIME_COMPATIBILITY_LOW")
    exit_score = _f(exit_plan.get("exit_feasibility_score"))
    if exit_score is None or exit_score < 0.35:
        risk = max(risk, 0.85)
        reasons.append("EXIT_FEASIBILITY_LOW")
    elif exit_score < 0.55:
        risk = max(risk, 0.65)
        reasons.append("EXIT_FEASIBILITY_WEAK")

    adaptive_trust_threshold = _get_adaptive_microstructure_trust_threshold()
    if microstructure_trust_score is None:
        risk = max(risk, 0.70)
        reasons.append("MICROSTRUCTURE_TRUST_MISSING")
    elif microstructure_trust_score < adaptive_trust_threshold:
        risk = max(risk, 0.75)
        reasons.append("MICROSTRUCTURE_TRUST_LOW")

    return {
        "pre_trade_loss_probability": round(min(1.0, risk), 8),
        "pre_trade_loss_risk_reasons": reasons,
    }
