"""Confidence overstatement risk: is the model's confidence trustworthy here?

Derived from the 2026-07 high-confidence loss cluster evidence: raw confidence
saturated near 1.0, global calibration mapped it to 0.70-0.79 without
side/regime conditioning, and the cohort's realized win-rate at >=0.70
confidence was 0/6.
"""

from __future__ import annotations

from typing import Any

RAW_SATURATION_BOUND = 0.999
HIGH_CONFIDENCE_FLOOR = 0.70


def _f(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def assess_confidence_overstatement(
    *,
    confidence_raw: Any,
    confidence_calibrated: Any,
    bucket_high_confidence_loss_rate: float | None,
    bucket_profit_factor: float | None,
    microstructure_trust_score: float | None,
) -> dict[str, Any]:
    raw = _f(confidence_raw)
    cal = _f(confidence_calibrated)
    reasons: list[str] = []
    risk = 0.0

    if cal is None and raw is None:
        return {
            "confidence_overstatement_risk": 1.0,
            "confidence_overstatement_reasons": ["CONFIDENCE_EVIDENCE_MISSING_FAIL_CLOSED"],
            "raw_confidence": None,
            "calibrated_confidence": None,
            "admission_confidence": None,
        }

    if raw is not None and raw >= RAW_SATURATION_BOUND:
        risk = max(risk, 0.6)
        reasons.append("RAW_CONFIDENCE_SATURATED")
    if raw is not None and cal is not None and (raw - cal) > 0.15:
        risk = max(risk, 0.4)
        reasons.append("LARGE_RAW_TO_CALIBRATED_SHRINK")
    effective = cal if cal is not None else raw
    if (
        effective is not None
        and effective >= HIGH_CONFIDENCE_FLOOR
        and bucket_high_confidence_loss_rate is not None
        and bucket_high_confidence_loss_rate > 0.4
    ):
        risk = max(risk, 0.8)
        reasons.append("BUCKET_HIGH_CONFIDENCE_LOSS_RATE_ELEVATED")
    if (
        effective is not None
        and effective >= 0.90
        and bucket_profit_factor is not None
        and bucket_profit_factor < 1.0
    ):
        risk = max(risk, 0.9)
        reasons.append("VERY_HIGH_CONFIDENCE_IN_NEGATIVE_PF_BUCKET")
    if (
        effective is not None
        and effective >= HIGH_CONFIDENCE_FLOOR
        and microstructure_trust_score is None
    ):
        risk = max(risk, 0.5)
        reasons.append("HIGH_CONFIDENCE_WITHOUT_MICROSTRUCTURE_TRUST_EVIDENCE")

    # Admission confidence: calibrated confidence penalized by overstatement
    # risk. Raw confidence is never hidden; admission never uses raw directly.
    admission = None
    if effective is not None:
        admission = max(0.0, effective * (1.0 - 0.5 * risk))

    return {
        "confidence_overstatement_risk": risk,
        "confidence_overstatement_reasons": reasons,
        "raw_confidence": raw,
        "calibrated_confidence": cal,
        "admission_confidence": admission,
    }
