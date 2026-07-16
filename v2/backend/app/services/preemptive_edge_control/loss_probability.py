"""Pre-trade loss probability policy for canonical edge control."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Mapping

import redis

logger = logging.getLogger(__name__)
GATE_TUNING_KEY = "v2:orchestrator:adaptive_gate_tuning_state"


def _f(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _get_adaptive_gate_tuning() -> dict[str, Any]:
    """Read adaptive gate tuning state from Redis (enables B-grade, sets confidence threshold)."""
    try:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        redis_client = redis.from_url(redis_url, decode_responses=True)
        tuning_json = redis_client.get(GATE_TUNING_KEY)
        if tuning_json:
            return json.loads(tuning_json)
    except Exception as e:
        logger.warning(f"Failed to read adaptive gate tuning: {e}")
    return {}


def _trust_score(candidate: Mapping[str, Any]) -> float | None:
    trust = _f(
        _first_present(
            candidate.get("microstructure_trust_score"),
            candidate.get("composite_microstructure_trust_score"),
            candidate.get("market_state_integrity_score"),
        )
    )
    if trust is None:
        return None
    return trust / 100.0 if trust > 1.0 else trust


def evaluate_loss_probability(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return loss/profit probability plus hard block reasons.

    This module is intentionally standalone so tests and external verifiers can
    inspect the pre-trade risk policy without walking the paper-loop runtime.
    """

    # Read adaptive gate tuning state (enables B-grade, sets confidence threshold)
    adaptive_state = _get_adaptive_gate_tuning()
    enable_b_grade = adaptive_state.get("enable_b_grade", False)
    adaptive_confidence_threshold = adaptive_state.get("adaptive_confidence_threshold", 0.70)

    reasons: list[str] = []
    risk = 0.20
    expected_net = _f(
        _first_present(
            candidate.get("pre_trade_expected_net_pnl_usd"),
            candidate.get("expected_net_pnl_usd"),
        )
    )
    expected_bps = _f(
        _first_present(
            candidate.get("expected_move_after_cost_bps"),
            candidate.get("expected_edge_after_cost_bps"),
        )
    )
    if expected_net is None and expected_bps is None:
        risk = max(risk, 0.86)
        reasons.append("BLOCK_MISSING_COST")
    elif (expected_net is not None and expected_net <= 0) or (
        expected_bps is not None and expected_bps <= 0
    ):
        risk = max(risk, 0.92)
        reasons.append("BLOCK_NEGATIVE_EXPECTANCY")

    bucket_pf = _f(
        _first_present(
            candidate.get("bucket_pf_window"),
            candidate.get("bucket_profit_factor"),
        )
    )
    if bucket_pf is not None and bucket_pf < 1.0:
        risk = max(risk, 0.90)
        reasons.append("BLOCK_PF_BELOW_1")
    bucket_expectancy = _f(
        _first_present(
            candidate.get("bucket_expectancy_usd_window"),
            candidate.get("notional_weighted_bucket_expectancy"),
        )
    )
    if bucket_expectancy is not None and bucket_expectancy <= 0:
        risk = max(risk, 0.88)
        reasons.append("BLOCK_NEGATIVE_EXPECTANCY")

    confidence = _f(candidate.get("confidence_calibrated") or candidate.get("confidence_raw"))
    high_conf_loss_rate = _f(
        candidate.get("recent_high_confidence_loss_rate")
        or candidate.get("high_confidence_loss_rate")
    )
    # Use adaptive confidence threshold if B-grade is enabled; otherwise default to 0.70
    conf_threshold = adaptive_confidence_threshold if enable_b_grade else 0.70
    if confidence is not None and confidence >= conf_threshold and high_conf_loss_rate is not None and high_conf_loss_rate > 0.0:
        risk = max(risk, min(0.95, 0.72 + high_conf_loss_rate * 0.35))
        reasons.append("BLOCK_HIGH_CONFIDENCE_LOSS_CLUSTER")
    atr_stop_rate = _f(candidate.get("recent_ATR_stop_risk") or candidate.get("atr_stop_rate"))
    if atr_stop_rate is not None and atr_stop_rate >= 0.40:
        risk = max(risk, min(0.94, 0.68 + atr_stop_rate * 0.30))
        reasons.append("BLOCK_ATR_STOP_CLUSTER")
    trust = _trust_score(candidate)
    if trust is None:
        risk = max(risk, 0.74)
        reasons.append("BLOCK_MICROSTRUCTURE_UNSAFE")
    elif trust < 0.45:
        risk = max(risk, 0.82)
        reasons.append("BLOCK_MICROSTRUCTURE_UNSAFE")

    if candidate.get("cost_evidence_missing") is True:
        risk = max(risk, 0.90)
        reasons.append("BLOCK_MISSING_COST")
    if candidate.get("bucket_quarantine_active") is True:
        risk = max(risk, 0.92)
        reasons.append("BLOCK_BUCKET_QUARANTINE")

    risk = round(min(1.0, max(0.0, risk)), 8)
    # Use adaptive loss probability threshold (0.85 when B-grade enabled, 0.80 otherwise)
    # instead of hardcoded 0.80 to respect adaptive gate tuning
    adaptive_loss_prob_threshold = adaptive_state.get("adaptive_loss_probability_threshold", 0.80)
    effective_block_threshold = adaptive_loss_prob_threshold if enable_b_grade else 0.80
    return {
        "pre_trade_loss_probability": risk,
        "pre_trade_profit_probability": round(1.0 - risk, 8),
        "loss_probability_reason": reasons[0] if reasons else "LOSS_PROBABILITY_BASELINE_EDGE_OK",
        "loss_probability_reasons": list(dict.fromkeys(reasons)),
        "loss_probability_confidence": 0.85 if reasons else 0.65,
        "block": risk >= effective_block_threshold or any(reason.startswith("BLOCK_") for reason in reasons),
        "adaptive_gating_applied": enable_b_grade,
        "adaptive_confidence_threshold_used": conf_threshold if enable_b_grade else 0.70,
    }


calculate_loss_probability = evaluate_loss_probability
