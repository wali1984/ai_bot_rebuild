"""ADX must be a real Wilder ADX, and must fail closed without history.

The adaptive regime classifier scores trend strength from `ta_ADX` and fails
closed when it is absent -- which is why every regime gate reported
MISSING_REGIME_INPUT:ta_ADX and `regime_aligned` failed 100% of candidates.
"""

from __future__ import annotations

import pytest

from v2.backend.app.services.feature_pipeline_and_ta.service import _adx


def _bars(closes: list[float], spread: float = 0.3):
    return [c + spread for c in closes], [c - spread for c in closes], closes


def test_strong_trend_scores_high() -> None:
    highs, lows, closes = _bars([100 + i * 0.5 for i in range(120)])
    value = _adx(highs, lows, closes, 14)
    assert value is not None
    assert value > 40


def test_choppy_market_scores_low() -> None:
    highs, lows, closes = _bars([100 + (1 if i % 2 else -1) * 0.4 for i in range(120)])
    value = _adx(highs, lows, closes, 14)
    assert value is not None
    assert value < 25


def test_downtrend_is_also_strong_trend() -> None:
    """ADX measures trend strength, not direction."""
    highs, lows, closes = _bars([160 - i * 0.5 for i in range(120)])
    value = _adx(highs, lows, closes, 14)
    assert value is not None
    assert value > 40


def test_output_is_always_bounded_percent() -> None:
    highs, lows, closes = _bars([100 + i * 0.5 for i in range(120)])
    value = _adx(highs, lows, closes, 14)
    assert 0.0 <= value <= 100.0


@pytest.mark.parametrize("bars", [0, 1, 10, 28])
def test_insufficient_history_returns_none_not_a_partial_value(bars: int) -> None:
    highs, lows, closes = _bars([100 + i * 0.5 for i in range(bars)])
    assert _adx(highs, lows, closes, 14) is None


@pytest.mark.parametrize("period", [0, -1])
def test_invalid_period_returns_none(period: int) -> None:
    highs, lows, closes = _bars([100 + i * 0.5 for i in range(120)])
    assert _adx(highs, lows, closes, period) is None


def test_flat_market_does_not_divide_by_zero() -> None:
    closes = [100.0] * 120
    assert _adx(closes, closes, closes, 14) is None


def test_ragged_series_uses_the_common_length() -> None:
    highs, lows, closes = _bars([100 + i * 0.5 for i in range(120)])
    # Truncating one leg below the requirement must fail closed, not crash.
    assert _adx(highs[:20], lows, closes, 14) is None
