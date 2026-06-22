"""Confidence calibration for V2 hybrid trainer outputs."""
from __future__ import annotations

import math


def softmax(xs: list[float] | tuple[float, ...]) -> tuple[float, ...]:
    if not xs:
        return ()
    cleaned: list[float] = []
    for value in xs:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        cleaned.append(number if math.isfinite(number) else 0.0)
    m = max(cleaned)
    exps = [math.exp(max(-700.0, min(700.0, float(x) - m))) for x in cleaned]
    s = sum(exps)
    if not math.isfinite(s) or s <= 0:
        return tuple(1.0 / len(xs) for _ in xs)
    return tuple(float(e / s) for e in exps)


def calibrate_confidence(
    *,
    raw_probability: float,
    data_coverage_percent: float,
    missing_feature_count: int,
    stale_feature_count: int,
    temperature: float = 1.4,
) -> dict:
    try:
        raw_input = float(raw_probability)
    except (TypeError, ValueError):
        raw_input = 0.0
    if not math.isfinite(raw_input):
        raw_input = 0.0
    raw = max(1e-6, min(1.0 - 1e-6, raw_input))
    logit = math.log(raw / (1.0 - raw))
    try:
        temp_input = float(temperature)
    except (TypeError, ValueError):
        temp_input = 1.4
    if not math.isfinite(temp_input):
        temp_input = 1.4
    temp = max(0.05, temp_input)
    scaled = 1.0 / (1.0 + math.exp(-(logit / temp)))
    try:
        coverage_input = float(data_coverage_percent)
    except (TypeError, ValueError):
        coverage_input = 0.0
    if not math.isfinite(coverage_input):
        coverage_input = 0.0
    coverage_factor = max(0.0, min(1.0, coverage_input / 100.0))
    missing_penalty = max(0.0, 1.0 - 0.015 * int(missing_feature_count))
    stale_penalty = max(0.0, 1.0 - 0.01 * int(stale_feature_count))
    calibrated = 0.5 + (scaled - 0.5) * coverage_factor * missing_penalty * stale_penalty
    return {
        "confidence_raw": float(raw_input),
        "confidence_calibrated": float(max(0.0, min(1.0, calibrated))),
        "temperature": float(temp),
        "coverage_factor": float(coverage_factor),
        "used_calibration": True,
        "calibration_source": "temperature_plus_data_quality_downrating",
    }
