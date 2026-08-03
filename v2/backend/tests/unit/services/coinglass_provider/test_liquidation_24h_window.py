"""Authenticated CoinGlass rolling-24h liquidation-notional aggregation.

These tests pin the integrity contract for ``last_liq_bps_24h``: the 24h
notional is admitted ONLY when 24 consecutive, closed, fresh 1h bars are
present.  Every gap / shortfall / staleness path must fail closed with
``notional_usd=None`` so the downstream RL trust gate never receives a
fabricated or incomplete aggregate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.coinglass_provider.normalizer import (
    aggregate_liquidation_notional_24h,
)

_OBSERVED = datetime(2026, 7, 24, 15, 0, 0, tzinfo=UTC)
_MAX_AGE = 3660


def _bars(
    count: int,
    *,
    long_usd: float = 1000.0,
    short_usd: float = 500.0,
    gap_at: int | None = None,
    missing_at: int | None = None,
) -> list[dict]:
    """``count`` consecutive 1h bars; the last closes exactly at ``_OBSERVED``."""
    rows: list[dict] = []
    for index in range(count):
        opens = _OBSERVED - timedelta(hours=(count - index))
        if gap_at is not None and index >= gap_at:
            opens = opens + timedelta(hours=1)
        row: dict = {"time": int(opens.timestamp() * 1000)}
        if missing_at is None or index != missing_at:
            row["aggregated_long_liquidation_usd"] = long_usd
            row["aggregated_short_liquidation_usd"] = short_usd
        rows.append(row)
    return rows


def _agg(rows, observed=_OBSERVED, max_age=_MAX_AGE):
    return aggregate_liquidation_notional_24h(
        rows, observed_at=observed, max_source_age_seconds=max_age
    )


def test_exactly_24_consecutive_bars_admitted() -> None:
    result = _agg(_bars(24))
    assert result["complete"] is True
    assert result["reason"] == "AUTHENTICATED_ROLLING_24H_WINDOW"
    assert result["notional_usd"] == 24 * 1500.0
    assert result["bar_count"] == 24
    assert result["feature_cutoff"] == _OBSERVED


def test_break_even_zero_bar_is_authoritative_not_dropped() -> None:
    # A genuine zero-liquidation hour (0 long + 0 short) is a real value.
    rows = _bars(24)
    rows[5]["aggregated_long_liquidation_usd"] = 0.0
    rows[5]["aggregated_short_liquidation_usd"] = 0.0
    result = _agg(rows)
    assert result["complete"] is True
    assert result["notional_usd"] == 23 * 1500.0


def test_twenty_three_bars_fails_closed() -> None:
    result = _agg(_bars(23))
    assert result["complete"] is False
    assert result["reason"] == "INSUFFICIENT_BARS"
    assert result["notional_usd"] is None


def test_more_than_24_uses_latest_24() -> None:
    result = _agg(_bars(30))
    assert result["complete"] is True
    assert result["bar_count"] == 24
    assert result["notional_usd"] == 24 * 1500.0


def test_gap_in_window_fails_closed() -> None:
    result = _agg(_bars(25, gap_at=20))
    assert result["complete"] is False
    assert result["reason"] == "NON_CONSECUTIVE_WINDOW"
    assert result["notional_usd"] is None


def test_missing_liquidation_fields_bar_is_dropped() -> None:
    # A bar missing its long/short fields cannot be admitted; the window then
    # has only 23 real bars and must fail closed (never bridge the hole).
    result = _agg(_bars(24, missing_at=10))
    assert result["complete"] is False
    assert result["notional_usd"] is None


def test_stale_latest_bar_fails_closed() -> None:
    result = _agg(_bars(24), observed=_OBSERVED + timedelta(hours=10))
    assert result["complete"] is False
    assert result["reason"] == "LATEST_BAR_TOO_OLD"
    assert result["notional_usd"] is None


def test_non_list_and_empty_fail_closed() -> None:
    assert aggregate_liquidation_notional_24h(
        None, observed_at=_OBSERVED, max_source_age_seconds=_MAX_AGE
    )["complete"] is False
    assert _agg([])["complete"] is False


def test_invalid_max_age_fails_closed() -> None:
    result = _agg(_bars(24), max_age=0)
    assert result["complete"] is False
    assert result["reason"] == "SOURCE_AGE_CONTRACT_INVALID"
