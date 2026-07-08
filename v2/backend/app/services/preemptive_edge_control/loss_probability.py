"""Pre-trade loss probability policy for canonical edge control."""

from __future__ import annotations

from typing import Any, Mapping


def _f(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_loss_probability(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return loss/profit probability plus hard block reasons.

    This module is intentionally standalone so tests and external verifiers can
    inspect the pre-trade risk policy without walking the paper-loop runtime.
    """

    reasons: list[str] = []
    risk = 0.20
    expected_net = _f(
        candidate.get("pre_trade_expected_net_pnl_usd")
        or candidate.get("expected_net_pnl_usd")
    )
    expected_bps = _f(
        candidate.get("expected_move_after_cost_bps")
        or candidate.get("expected_edge_after_cost_bps")
    )
    if expected_net is None and expected_bps is None:
        risk = max(risk, 0.86)
        reasons.append("BLOCK_MISSING_COST")
    elif (expected_net is not None and expected_net <= 0) or (
        expected_bps is not None and expected_bps <= 0
    ):
        risk = max(risk, 0.92)
        reasons.append("BLOCK_NEGATIVE_EXPECTANCY")

    bucket_pf = _f(candidate.get("bucket_pf_window") or candidate.get("bucket_profit_factor"))
    if bucket_pf is not None and bucket_pf < 1.0:
        risk = max(risk, 0.90)
        reasons.append("BLOCK_PF_BELOW_1")
    bucket_expectancy = _f(
        candidate.get("bucket_expectancy_usd_window")
        or candidate.get("notional_weighted_bucket_expectancy")
    )
    if bucket_expectancy is not None and bucket_expectancy <= 0:
        risk = max(risk, 0.88)
        reasons.append("BLOCK_NEGATIVE_EXPECTANCY")

    confidence = _f(candidate.get("confidence_calibrated") or candidate.get("confidence_raw"))
    high_conf_loss_rate = _f(
        candidate.get("recent_high_confidence_loss_rate")
        or candidate.get("high_confidence_loss_rate")
    )
    if confidence is not None and confidence >= 0.70 and high_conf_loss_rate is not None and high_conf_loss_rate > 0.0:
        risk = max(risk, min(0.95, 0.72 + high_conf_loss_rate * 0.35))
        reasons.append("BLOCK_HIGH_CONFIDENCE_LOSS_CLUSTER")
    atr_stop_rate = _f(candidate.get("recent_ATR_stop_risk") or candidate.get("atr_stop_rate"))
    if atr_stop_rate is not None and atr_stop_rate >= 0.40:
        risk = max(risk, min(0.94, 0.68 + atr_stop_rate * 0.30))
        reasons.append("BLOCK_ATR_STOP_CLUSTER")
    trust = _f(
        candidate.get("microstructure_trust_score")
        or candidate.get("composite_microstructure_trust_score")
    )
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
    return {
        "pre_trade_loss_probability": risk,
        "pre_trade_profit_probability": round(1.0 - risk, 8),
        "loss_probability_reason": reasons[0] if reasons else "LOSS_PROBABILITY_BASELINE_EDGE_OK",
        "loss_probability_reasons": list(dict.fromkeys(reasons)),
        "loss_probability_confidence": 0.85 if reasons else 0.65,
        "block": risk >= 0.80 or any(reason.startswith("BLOCK_") for reason in reasons),
    }


calculate_loss_probability = evaluate_loss_probability
