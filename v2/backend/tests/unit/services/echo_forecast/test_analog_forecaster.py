"""Tests for the Echo analog (k-NN) forecaster.

Validates: analog projection correctness, distribution semantics (dispersion ->
uncertainty), direction, hit-rate, insufficient-data handling, no-lookahead
purity, and robustness to bad input.
"""
from __future__ import annotations

import math

import pytest

from app.services.echo_forecast import AnalogForecast, compute_analog_forecast


def _hist(pattern, fwd, n=12, jitter=0.0):
    """n copies of `pattern` (optionally jittered) each labelled with forward `fwd`."""
    rows, fwds = [], []
    for i in range(n):
        rows.append([p + (jitter if (i % 2 == 0) else -jitter) for p in pattern])
        fwds.append(fwd)
    return rows, fwds


def test_identical_pattern_projects_its_forward_return() -> None:
    # All historical analogs identical to current and moved +80 bps -> forecast ~+80,
    # long, ~zero dispersion, high confidence.
    cur = [1.0, 2.0, 3.0]
    rows, fwds = _hist(cur, 80.0, n=30)  # >= default k=25 so count_term reaches 1.0
    f = compute_analog_forecast(current_window=cur, historical_windows=rows, forward_return_bps=fwds)
    assert not f.insufficient_data
    assert f.direction == "long"
    assert abs(f.expected_move_bps - 80.0) < 1e-6
    assert f.dispersion_bps < 1e-6
    assert f.hit_rate == pytest.approx(1.0)
    assert f.confidence > 0.8


def test_disagreeing_analogs_kill_confidence() -> None:
    # Same pattern but half went +100 and half went -100: expected ~0, huge
    # dispersion, hit-rate ~0.5 -> confidence ~0 even though analogs are close.
    cur = [0.5, -0.5, 0.25]
    rows = [list(cur) for _ in range(20)]
    fwds = [100.0 if i % 2 == 0 else -100.0 for i in range(20)]
    f = compute_analog_forecast(current_window=cur, historical_windows=rows, forward_return_bps=fwds)
    assert abs(f.expected_move_bps) < 10.0        # bimodal -> expected ~0 -> "flat"
    assert f.dispersion_bps > 50.0                # wide disagreement
    assert f.direction == "flat"
    assert f.hit_rate < 0.1                       # none of the +/-100 analogs are actually flat
    assert f.confidence < 0.1                     # correctly refuses to commit


def test_nearest_analogs_dominate_over_far_ones() -> None:
    # Near analogs (close to current) moved +60; far analogs (very different) moved
    # -300. The forecast must follow the NEAR analogs.
    cur = [1.0, 1.0, 1.0]
    near_rows, near_fwd = _hist([1.01, 0.99, 1.0], 60.0, n=15)
    far_rows, far_fwd = _hist([50.0, -50.0, 30.0], -300.0, n=15)
    rows = near_rows + far_rows
    fwds = near_fwd + far_fwd
    f = compute_analog_forecast(current_window=cur, historical_windows=rows, forward_return_bps=fwds, k=15)
    assert f.direction == "long"
    assert f.expected_move_bps > 30.0  # pulled toward the near +60, not the far -300


def test_short_direction() -> None:
    cur = [2.0, -1.0]
    rows, fwds = _hist(cur, -45.0, n=16)
    f = compute_analog_forecast(current_window=cur, historical_windows=rows, forward_return_bps=fwds)
    assert f.direction == "short"
    assert f.expected_move_bps < 0
    assert f.hit_rate == pytest.approx(1.0)


def test_flat_band() -> None:
    cur = [1.0, 1.0]
    rows, fwds = _hist(cur, 2.0, n=16)  # +2 bps within default flat_band 5 bps
    f = compute_analog_forecast(current_window=cur, historical_windows=rows, forward_return_bps=fwds)
    assert f.direction == "flat"


def test_insufficient_data() -> None:
    cur = [1.0, 2.0]
    rows, fwds = _hist(cur, 50.0, n=3)  # below default min_analogs=8
    f = compute_analog_forecast(current_window=cur, historical_windows=rows, forward_return_bps=fwds)
    assert f.insufficient_data
    assert f.confidence == 0.0
    assert f.direction == "flat"


def test_bad_rows_are_dropped_not_raised() -> None:
    cur = [1.0, 2.0, 3.0]
    good_rows, good_fwd = _hist(cur, 70.0, n=10)
    # wrong-width row, NaN feature, NaN forward — all must be dropped silently.
    bad_rows = [[1.0, 2.0], [float("nan"), 2.0, 3.0], [1.0, 2.0, 3.0]]
    bad_fwd = [10.0, 20.0, float("nan")]
    f = compute_analog_forecast(
        current_window=cur,
        historical_windows=good_rows + bad_rows,
        forward_return_bps=good_fwd + bad_fwd,
    )
    assert not f.insufficient_data
    assert f.direction == "long"
    assert f.n_analogs == 10  # only the 10 good rows survived


def test_no_lookahead_current_forward_not_required() -> None:
    # The forecast is computed WITHOUT any knowledge of the current window's own
    # future — only historical windows carry realized forward returns. (Purely by
    # signature: there is no current-forward argument.) Sanity: result is stable.
    cur = [0.3, 0.7, -0.2, 0.5]
    rows, fwds = _hist(cur, 55.0, n=30)
    f1 = compute_analog_forecast(current_window=cur, historical_windows=rows, forward_return_bps=fwds)
    f2 = compute_analog_forecast(current_window=cur, historical_windows=rows, forward_return_bps=fwds)
    assert isinstance(f1, AnalogForecast)
    assert f1 == f2  # deterministic


def test_zero_variance_dimension_does_not_crash() -> None:
    # A constant feature column (std 0) must be handled (unit-scaled), not divide-by-zero.
    cur = [5.0, 1.0]
    rows = [[5.0, 1.0 + i * 0.01] for i in range(12)]  # first column constant
    fwds = [40.0] * 12
    f = compute_analog_forecast(current_window=cur, historical_windows=rows, forward_return_bps=fwds)
    assert not f.insufficient_data
    assert f.direction == "long"
