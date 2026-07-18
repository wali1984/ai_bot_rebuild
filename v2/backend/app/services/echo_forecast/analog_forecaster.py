"""Echo analog forecaster — per-timeframe k-NN pattern-analog forecast.

Operator directive (2026-07-18): build a LuxAlgo-"Echo"-style multi-timeframe
predictor. Echo, mechanically, is an ANALOG / pattern-matching forecaster: it
finds the most similar historical windows to the current one and projects their
realized forward path as the forecast. This module is the rigorous in-house
version.

DESIGN INVARIANTS
- PURE + no I/O + deterministic: a pure function of the arrays you pass in, so it
  is trivially testable and can be wired into the trainer, a publisher, or the
  UI without side effects.
- STRICT NO-LOOKAHEAD: the caller supplies ONLY historical windows whose forward
  outcome is ALREADY realized (i.e., decided strictly before the current window's
  decision time). The module never sees the future; it only ranks the past.
- DISTRIBUTION, NOT AN ORACLE: returns expected move + DISPERSION (disagreement =
  uncertainty) + hit-rate + analog count. When analogs disagree or are few,
  confidence is low. This is ONE feature into the calibrated P(after-cost profit)
  head — never a standalone sizing/entry signal.
- TIMEFRAME-AGNOSTIC: run it per TF (1m..4h..1d..1w..1M) by passing that TF's
  windows + forward returns. The forecast horizon is whatever horizon the
  supplied `forward_return_bps` was measured over.

This module does NOT place orders, mutate state, or read Redis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

SCHEMA_VERSION = "echo_analog_forecast_v1"


@dataclass(frozen=True)
class AnalogForecast:
    """Forecast distribution assembled from the k nearest historical analogs."""

    expected_move_bps: float          # similarity-weighted mean of analog forward returns
    dispersion_bps: float             # similarity-weighted std (uncertainty; higher = less certain)
    direction: str                    # "long" | "short" | "flat"
    hit_rate: float                   # weighted fraction of analogs agreeing with `direction` [0,1]
    n_analogs: int                    # analogs actually used (<= k)
    mean_distance: float              # mean normalized distance of the used analogs (lower = better match)
    confidence: float                 # [0,1]: rises with agreement + count + closeness, falls with dispersion
    insufficient_data: bool           # True if fewer than min_analogs usable analogs
    schema_version: str = SCHEMA_VERSION


def _finite(x: object) -> float | None:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _column_stats(rows: Sequence[Sequence[float]], dims: int) -> tuple[list[float], list[float]]:
    """Per-dimension mean and (population) std over the historical window vectors,
    used to z-score features so no single dimension dominates the distance."""
    means = [0.0] * dims
    for r in rows:
        for j in range(dims):
            means[j] += r[j]
    n = max(1, len(rows))
    means = [m / n for m in means]
    var = [0.0] * dims
    for r in rows:
        for j in range(dims):
            d = r[j] - means[j]
            var[j] += d * d
    stds = [math.sqrt(v / n) for v in var]
    # Guard zero-variance dimensions (constant feature) -> unit scale, no divide-by-zero.
    stds = [s if s > 1e-12 else 1.0 for s in stds]
    return means, stds


def _z(vec: Sequence[float], means: Sequence[float], stds: Sequence[float]) -> list[float]:
    return [(vec[j] - means[j]) / stds[j] for j in range(len(vec))]


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Euclidean distance over z-scored vectors, normalized by sqrt(dims) so the
    scale is comparable across different feature-vector lengths."""
    dims = len(a)
    if dims == 0:
        return 0.0
    s = 0.0
    for j in range(dims):
        d = a[j] - b[j]
        s += d * d
    return math.sqrt(s / dims)


def compute_analog_forecast(
    *,
    current_window: Sequence[float],
    historical_windows: Sequence[Sequence[float]],
    forward_return_bps: Sequence[float],
    k: int = 25,
    min_analogs: int = 8,
    dispersion_ref_bps: float = 120.0,
    flat_band_bps: float = 5.0,
) -> AnalogForecast:
    """Compute a k-NN analog forecast for `current_window`.

    Args:
        current_window: the current feature vector (e.g., recent normalized returns
            / TA features) whose forward move we want to forecast.
        historical_windows: past feature vectors, SAME dimensionality as
            current_window, each with an ALREADY-REALIZED forward return.
        forward_return_bps: forward return (bps) that followed each historical
            window over the target horizon. len == len(historical_windows).
        k: number of nearest analogs to aggregate.
        min_analogs: below this many usable analogs -> insufficient_data, confidence 0.
        dispersion_ref_bps: dispersion at which the dispersion-confidence term ~ 0.37
            (exp(-1)); tunes how quickly disagreement kills confidence.
        flat_band_bps: |expected_move| below this -> direction "flat".

    Returns:
        AnalogForecast (distribution, not a point oracle). Never raises on bad input;
        returns insufficient_data instead.
    """
    dims = len(current_window)
    # Sanitize: keep only historical rows that are finite, correct-width, and have
    # a finite realized forward return.
    clean: list[tuple[list[float], float]] = []
    for row, fwd in zip(historical_windows, forward_return_bps):
        if row is None or len(row) != dims:
            continue
        fv = _finite(fwd)
        if fv is None:
            continue
        vec = [_finite(x) for x in row]
        if any(v is None for v in vec):
            continue
        clean.append(([float(v) for v in vec], fv))  # type: ignore[arg-type]

    cur = [_finite(x) for x in current_window]
    if dims == 0 or any(v is None for v in cur) or len(clean) < min_analogs:
        return AnalogForecast(
            expected_move_bps=0.0, dispersion_bps=0.0, direction="flat", hit_rate=0.0,
            n_analogs=len(clean), mean_distance=0.0, confidence=0.0, insufficient_data=True,
        )
    cur_f: list[float] = [float(v) for v in cur]  # type: ignore[arg-type]

    # Z-score all vectors on the HISTORICAL distribution (no lookahead: current is
    # scored with the same historical stats, not the other way around).
    means, stds = _column_stats([c[0] for c in clean], dims)
    cur_z = _z(cur_f, means, stds)
    scored = [(_distance(cur_z, _z(vec, means, stds)), fwd) for vec, fwd in clean]
    scored.sort(key=lambda t: t[0])
    nn = scored[: max(1, int(k))]

    # Similarity weights: exp(-dist / scale), scale = mean distance of the neighbours
    # (adaptive), so weighting is robust to the absolute distance scale.
    mean_dist = sum(d for d, _ in nn) / len(nn)
    scale = mean_dist if mean_dist > 1e-9 else 1.0
    weights = [math.exp(-d / scale) for d, _ in nn]
    wsum = sum(weights) or 1.0

    exp_move = sum(w * fwd for w, (_, fwd) in zip(weights, nn)) / wsum
    var = sum(w * (fwd - exp_move) ** 2 for w, (_, fwd) in zip(weights, nn)) / wsum
    dispersion = math.sqrt(max(0.0, var))

    if exp_move > flat_band_bps:
        direction = "long"
    elif exp_move < -flat_band_bps:
        direction = "short"
    else:
        direction = "flat"

    # Hit rate: weighted fraction of analogs whose forward return agrees with the
    # expected direction (for "flat", agreement = within the flat band).
    def _agrees(fwd: float) -> bool:
        if direction == "long":
            return fwd > 0.0
        if direction == "short":
            return fwd < 0.0
        return abs(fwd) <= flat_band_bps

    hit_rate = sum(w for w, (_, fwd) in zip(weights, nn) if _agrees(fwd)) / wsum

    # Confidence in [0,1] = agreement x closeness x dispersion-decay x count-adequacy.
    dispersion_term = math.exp(-dispersion / max(1e-6, dispersion_ref_bps))
    closeness_term = 1.0 / (1.0 + mean_dist)                      # nearer analogs -> higher
    count_term = min(1.0, len(nn) / max(1, k))                    # full neighbourhood -> 1.0
    agreement_term = max(0.0, (hit_rate - 0.5) * 2.0)             # 50% hit -> 0, 100% -> 1
    confidence = max(0.0, min(1.0, agreement_term * dispersion_term * closeness_term * count_term))

    return AnalogForecast(
        expected_move_bps=round(exp_move, 4),
        dispersion_bps=round(dispersion, 4),
        direction=direction,
        hit_rate=round(hit_rate, 4),
        n_analogs=len(nn),
        mean_distance=round(mean_dist, 6),
        confidence=round(confidence, 4),
        insufficient_data=False,
    )
