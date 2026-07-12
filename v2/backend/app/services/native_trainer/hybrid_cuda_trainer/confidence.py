"""Confidence calibration for V2 hybrid trainer outputs."""
from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from pathlib import Path

DEFAULT_CONFIDENCE_TEMPERATURE = 1.4
# Fitted-temperature state (WI-3). A separate offline job fits the temperature
# from realised outcomes and writes it here; the model reads it live so an
# overconfident policy gets its high-confidence losers down-weighted (which
# makes the confidence-floor gate STRICTER, never looser).
CONFIDENCE_TEMPERATURE_STATE_PATH = Path(
    os.getenv(
        "V2_CONFIDENCE_TEMPERATURE_STATE_PATH",
        "claude_worklog/trainer_atlas/confidence_temperature.json",
    )
)
_TEMPERATURE_CACHE: dict[str, float | None] = {"mtime": None, "value": None}


def _clamp_prob(p: float) -> float:
    return max(1e-6, min(1.0 - 1e-6, p))


def _temperature_scaled(raw: float, temperature: float) -> float:
    r = _clamp_prob(raw)
    logit = math.log(r / (1.0 - r))
    temp = max(0.05, float(temperature))
    return 1.0 / (1.0 + math.exp(-(logit / temp)))


def _nll(raw_probs: Sequence[float], wins: Sequence[int], temperature: float) -> float:
    total = 0.0
    n = 0
    for raw, y in zip(raw_probs, wins, strict=False):
        p = _clamp_prob(_temperature_scaled(float(raw), temperature))
        total += -(y * math.log(p) + (1 - y) * math.log(1.0 - p))
        n += 1
    return total / n if n else float("inf")


def expected_calibration_error(
    raw_probs: Sequence[float], wins: Sequence[int], temperature: float = 1.0, bins: int = 10
) -> float:
    """Binned |confidence - accuracy| (ECE) after temperature scaling."""
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    n = 0
    for raw, y in zip(raw_probs, wins, strict=False):
        p = _temperature_scaled(float(raw), temperature)
        idx = min(bins - 1, max(0, int(p * bins)))
        buckets[idx].append((p, int(y)))
        n += 1
    if not n:
        return 0.0
    ece = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        conf = sum(p for p, _ in bucket) / len(bucket)
        acc = sum(y for _, y in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(conf - acc)
    return ece


def fit_temperature(
    raw_probs: Sequence[float],
    wins: Sequence[int],
    *,
    lo: float = 0.25,
    hi: float = 6.0,
) -> dict:
    """Temperature scaling (Guo et al.): fit T minimising NLL of raw_probs vs wins.

    T>1 spreads an overconfident policy's probabilities toward 0.5 (its high-
    confidence losers lose confidence); T<1 sharpens an underconfident one. Pure
    1-D search (coarse grid + golden-section refine), no scipy. Returns the
    fitted temperature plus ECE/NLL before (T=default) and after, and the sample
    size, so a gate can refuse to adopt a fit from too few outcomes.
    """
    xs = [(float(r), int(bool(y))) for r, y in zip(raw_probs, wins, strict=False)]
    n = len(xs)
    if n < 50:
        return {
            "fitted": False,
            "reason": "INSUFFICIENT_OUTCOME_SAMPLE",
            "sample": n,
            "temperature": DEFAULT_CONFIDENCE_TEMPERATURE,
        }
    probs = [r for r, _ in xs]
    ys = [y for _, y in xs]
    # Coarse grid, then golden-section refine around the best grid point.
    grid = [lo + (hi - lo) * i / 40.0 for i in range(41)]
    best_t = min(grid, key=lambda t: _nll(probs, ys, t))
    a, b = max(lo, best_t - (hi - lo) / 40.0), min(hi, best_t + (hi - lo) / 40.0)
    gr = (math.sqrt(5) - 1) / 2
    c, d = b - gr * (b - a), a + gr * (b - a)
    for _ in range(40):
        if _nll(probs, ys, c) < _nll(probs, ys, d):
            b = d
        else:
            a = c
        c, d = b - gr * (b - a), a + gr * (b - a)
    fitted_t = (a + b) / 2.0
    ece_before = expected_calibration_error(probs, ys, DEFAULT_CONFIDENCE_TEMPERATURE)
    ece_after = expected_calibration_error(probs, ys, fitted_t)
    return {
        "fitted": True,
        "temperature": float(round(fitted_t, 4)),
        "sample": n,
        "win_rate": round(sum(ys) / n, 4),
        "nll_before": round(_nll(probs, ys, DEFAULT_CONFIDENCE_TEMPERATURE), 6),
        "nll_after": round(_nll(probs, ys, fitted_t), 6),
        "ece_before": round(ece_before, 6),
        "ece_after": round(ece_after, 6),
    }


def resolve_confidence_temperature() -> float:
    """Live confidence temperature: fitted-state file, else env, else default.

    Read from the state file with an mtime cache so a fresh fit is picked up
    without a restart. Always falls back to the fixed default, so the disabled
    path is byte-identical to the historical behaviour.
    """
    env_override = os.getenv("V2_TRAINER_CONFIDENCE_TEMPERATURE")
    if env_override:
        try:
            return max(0.05, float(env_override))
        except (TypeError, ValueError):
            pass
    try:
        mtime = CONFIDENCE_TEMPERATURE_STATE_PATH.stat().st_mtime
    except OSError:
        return DEFAULT_CONFIDENCE_TEMPERATURE
    if _TEMPERATURE_CACHE["mtime"] != mtime:
        try:
            data = json.loads(CONFIDENCE_TEMPERATURE_STATE_PATH.read_text())
            value = float(data.get("temperature"))
            _TEMPERATURE_CACHE["value"] = max(0.05, value) if math.isfinite(value) else None
        except (OSError, ValueError, TypeError):
            _TEMPERATURE_CACHE["value"] = None
        _TEMPERATURE_CACHE["mtime"] = mtime
    cached = _TEMPERATURE_CACHE["value"]
    return float(cached) if cached else DEFAULT_CONFIDENCE_TEMPERATURE


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
    total_feature_count: int | None = None,
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
    try:
        total = int(total_feature_count) if total_feature_count is not None else None
    except (TypeError, ValueError):
        total = None
    if total is not None and total > 0:
        # Proportional data-quality downrating. The legacy absolute penalty
        # (1 - 0.015 * missing_count) saturated to 0 at 67 missing features;
        # after the A+ feature-spec expansion to 238 features typical live
        # tensors carry 40-70 masked optional/alt-data fields, which collapsed
        # EVERY calibrated confidence to exactly the 0.5 neutral point (F013)
        # and deadlocked all confidence-floor gates. The proportional form
        # keeps the same intent (missing data degrades confidence toward 0.5)
        # without total signal erasure; coverage_factor already scales by
        # gross missingness, so the floor here stays conservative at 0.25.
        missing_fraction = max(0.0, min(1.0, int(missing_feature_count) / total))
        stale_fraction = max(0.0, min(1.0, int(stale_feature_count) / total))
        missing_penalty = max(0.25, 1.0 - 0.75 * missing_fraction)
        stale_penalty = max(0.25, 1.0 - 0.5 * stale_fraction)
        calibration_source = "temperature_plus_proportional_data_quality_downrating"
    else:
        missing_penalty = max(0.0, 1.0 - 0.015 * int(missing_feature_count))
        stale_penalty = max(0.0, 1.0 - 0.01 * int(stale_feature_count))
        calibration_source = "temperature_plus_data_quality_downrating"
    calibrated = 0.5 + (scaled - 0.5) * coverage_factor * missing_penalty * stale_penalty
    return {
        "confidence_raw": float(raw_input),
        "confidence_calibrated": float(max(0.0, min(1.0, calibrated))),
        "temperature": float(temp),
        "coverage_factor": float(coverage_factor),
        "missing_penalty": float(missing_penalty),
        "stale_penalty": float(stale_penalty),
        "used_calibration": True,
        "calibration_source": calibration_source,
    }
