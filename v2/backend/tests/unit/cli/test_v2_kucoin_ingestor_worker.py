from __future__ import annotations

import pytest
from app.cli.v2_kucoin_ingestor_worker import (
    _futures_authority_match,
    _parse_contract,
    _parse_funding,
    _parse_kline,
    _parse_orderbook,
    _parse_spot_ticker,
    _runtime_ttl_assessment,
    _spot_authority_match,
    _update_component_success,
)


def test_parse_kucoin_futures_kline_uses_futures_field_order() -> None:
    parsed = _parse_kline(
        [[1_780_495_200, "0.0349", "0.0349", "0.03459", "0.03478", "1670", "581.4826"]],
        symbol="BANKUSDT",
        kucoin_symbol="BANKUSDTM",
        timeframe="1m",
        source="kucoin_futures_public_rest",
        observed_at_ms=1_780_495_260_000,
    )

    assert parsed is not None
    assert parsed["open"] == 0.0349
    assert parsed["high"] == 0.0349
    assert parsed["low"] == 0.03459
    assert parsed["close"] == 0.03478
    assert parsed["low"] <= parsed["open"] <= parsed["high"]
    assert parsed["low"] <= parsed["close"] <= parsed["high"]


def test_parse_kucoin_spot_kline_preserves_spot_field_order() -> None:
    parsed = _parse_kline(
        [[1_780_495_200, "100", "101", "102", "99", "10", "1000"]],
        symbol="BTCUSDT",
        kucoin_symbol="BTC-USDT",
        timeframe="1m",
        source="kucoin_spot_public_rest",
        observed_at_ms=1_780_495_260_000,
    )

    assert parsed is not None
    assert parsed["open"] == 100.0
    assert parsed["close"] == 101.0
    assert parsed["high"] == 102.0
    assert parsed["low"] == 99.0


def test_parse_kucoin_kline_rejects_malformed_ohlc() -> None:
    parsed = _parse_kline(
        [[1_780_495_200, "100", "101", "99", "102", "10", "1000"]],
        symbol="BTCUSDT",
        kucoin_symbol="BTC-USDT",
        timeframe="1m",
        source="kucoin_spot_public_rest",
    )

    assert parsed is None


def test_parse_kucoin_kline_skips_newest_unfinished_row() -> None:
    observed_ms = 1_800_000_050_000
    parsed = _parse_kline(
        [
            [1_800_000_000, "200", "201", "202", "199", "10", "2000"],
            [1_799_999_940, "100", "101", "102", "99", "8", "800"],
        ],
        symbol="BTCUSDT",
        kucoin_symbol="BTC-USDT",
        timeframe="1m",
        source="kucoin_spot_public_rest",
        observed_at_ms=observed_ms,
    )

    assert parsed is not None
    assert parsed["timestamp"] == 1_799_999_940_000
    assert parsed["close"] == 101.0
    assert parsed["bar_close_time_ms"] == 1_800_000_000_000
    assert parsed["is_final"] is True
    assert parsed["feature_cutoff_ms"] <= parsed["available_at_ms"]


def test_parse_kucoin_kline_fails_closed_when_only_row_is_unfinished() -> None:
    assert _parse_kline(
        [[1_800_000_000, "200", "201", "202", "199", "10", "2000"]],
        symbol="BTCUSDT",
        kucoin_symbol="BTC-USDT",
        timeframe="1m",
        source="kucoin_spot_public_rest",
        observed_at_ms=1_800_000_050_000,
    ) is None


def test_parse_kucoin_kline_fails_closed_when_latest_row_is_stale() -> None:
    assert _parse_kline(
        [[1_799_999_880, "100", "101", "102", "99", "10", "1000"]],
        symbol="BTCUSDT",
        kucoin_symbol="BTC-USDT",
        timeframe="1m",
        source="kucoin_spot_public_rest",
        observed_at_ms=1_800_000_050_000,
    ) is None


def test_parse_kucoin_funding_rejects_schedule_without_rate() -> None:
    assert _parse_funding(
        {"nextFundingRateDateTime": 1_800_010_000_000},
        symbol="BTCUSDT",
        futures_symbol="XBTUSDTM",
        source="kucoin_futures_contract_authority_snapshot",
        ingested_at_ms=1_800_000_000_000,
    ) is None


@pytest.mark.parametrize("interval_hours", [1, 4, 8])
def test_parse_kucoin_funding_normalizes_authority_interval_per_hour(
    interval_hours: int,
) -> None:
    interval_field = (
        "fundingRateGranularity"
        if interval_hours == 4
        else "currentFundingRateGranularity"
    )
    parsed = _parse_funding(
        {
            "fundingFeeRate": "0.0008",
            "predictedFundingFeeRate": "-0.0004",
            interval_field: interval_hours * 3_600_000,
            "fundingRateCap": "0.003",
            "fundingRateFloor": "-0.003",
        },
        symbol="BTCUSDT",
        futures_symbol="XBTUSDTM",
        source="kucoin_futures_contract_authority_snapshot",
        ingested_at_ms=1_800_000_000_000,
    )

    assert parsed is not None
    assert parsed["funding_interval_hours"] == interval_hours
    assert parsed["funding_interval_source_field"] == interval_field
    assert parsed["funding_interval_unit"] == "hours"
    assert parsed["funding_interval_source_unit"] == "milliseconds"
    assert parsed["rate_per_hour"] == pytest.approx(0.0008 / interval_hours)
    assert parsed["predicted_rate_per_hour"] == pytest.approx(
        -0.0004 / interval_hours
    )
    assert parsed["raw_interval_rates_comparable_across_contracts"] is False


@pytest.mark.parametrize(
    "authority",
    [
        {
            "fundingFeeRate": "0.0031",
            "currentFundingRateGranularity": 28_800_000,
            "fundingRateCap": "0.003",
            "fundingRateFloor": "-0.003",
        },
        {
            "fundingFeeRate": "0.001",
            "predictedFundingFeeRate": "-0.0031",
            "currentFundingRateGranularity": 28_800_000,
            "fundingRateCap": "0.003",
            "fundingRateFloor": "-0.003",
        },
        {
            "fundingFeeRate": "0.001",
            "currentFundingRateGranularity": 7_200_000,
            "fundingRateCap": "0.003",
            "fundingRateFloor": "-0.003",
        },
        {
            "fundingFeeRate": "0.5",
            "currentFundingRateGranularity": 28_800_000,
        },
        {
            "fundingFeeRate": "0.001",
            "currentFundingRateGranularity": 28_800_000,
            "fundingRateCap": "-0.003",
            "fundingRateFloor": "-0.004",
        },
        {
            "fundingFeeRate": "-0.001",
            "currentFundingRateGranularity": 28_800_000,
            "fundingRateCap": "0.004",
            "fundingRateFloor": "0.003",
        },
    ],
)
def test_parse_kucoin_funding_rejects_out_of_domain_authority(
    authority: dict[str, object],
) -> None:
    assert _parse_funding(
        authority,
        symbol="BTCUSDT",
        futures_symbol="XBTUSDTM",
        source="kucoin_futures_contract_authority_snapshot",
        ingested_at_ms=1_800_000_000_000,
    ) is None


def test_product_authority_requires_exact_provider_identity() -> None:
    assert _spot_authority_match(
        "BONKUSDT",
        "BONK-USDT",
        {
            "symbol": "BONK-USDT",
            "baseCurrency": "BONK",
            "quoteCurrency": "USDT",
            "enableTrading": True,
        },
    ) is True
    assert _spot_authority_match(
        "1000BONKUSDT",
        "1000BONK-USDT",
        {
            "symbol": "BONK-USDT",
            "baseCurrency": "BONK",
            "quoteCurrency": "USDT",
            "enableTrading": True,
        },
    ) is False
    assert _futures_authority_match(
        "BTCUSDT",
        "XBTUSDTM",
        {
            "symbol": "XBTUSDTM",
            "baseCurrency": "XBT",
            "quoteCurrency": "USDT",
            "settleCurrency": "USDT",
            "isInverse": False,
            "marketStage": "NORMAL",
            "status": "Open",
        },
    ) is True
    assert _futures_authority_match(
        "BTCUSDT",
        "XBTUSDTM",
        {
            "symbol": "XBTUSDTM",
            "baseCurrency": "XBT",
            "quoteCurrency": "USDT",
            "settleCurrency": "USDT",
            "isInverse": False,
            "marketStage": "NORMAL",
        },
    ) is False
    assert _futures_authority_match(
        "BTCUSDT",
        "XBTUSDTM",
        {
            "symbol": "XBTUSDTM",
            "baseCurrency": "XBT",
            "quoteCurrency": "USDT",
            "isInverse": False,
            "marketStage": "NORMAL",
            "status": "Open",
        },
    ) is False
    assert _futures_authority_match(
        "BTCUSDT",
        "XBTUSDTM",
        {
            "symbol": "XBTUSDTM",
            "baseCurrency": "XBT",
            "quoteCurrency": "USDT",
            "settleCurrency": "USDT",
            "isInverse": True,
            "marketStage": "NORMAL",
            "status": "Open",
        },
    ) is False


def test_contract_without_provider_event_clock_does_not_invent_one() -> None:
    parsed = _parse_contract(
        {
            "openInterest": "123",
            "markPrice": "10",
            "indexPrice": "9.9",
            "multiplier": "0.01",
            "baseCurrency": "TEST",
            "quoteCurrency": "USDT",
            "settleCurrency": "USDT",
        },
        symbol="TESTUSDT",
        futures_symbol="TESTUSDTM",
        ingested_at_ms=1_800_000_000_000,
    )

    assert parsed is not None
    assert parsed["event_time"] is None
    assert parsed["timestamp_semantics"] == "local_observation_time_ms"
    assert parsed["available_at_ms"] == 1_800_000_000_000
    assert parsed["feature_cutoff_ms"] == 1_800_000_000_000
    assert parsed["contract_multiplier_unit"] == "base_asset_per_contract"


def test_ttl_recovery_uses_recent_window_without_erasing_lifetime_maximum() -> None:
    component = {
        "last_success_at_ms": 1_000_000,
        "successful_observation_count": 2,
        "observed_revisit_seconds": 1_200.0,
        "max_observed_revisit_seconds": 1_200.0,
    }

    initial = _runtime_ttl_assessment(
        redis_ttl_seconds=900,
        rotating_universe_size=1,
        actual_rotating_rows_covered=1,
        elapsed_seconds=1.0,
        expected_cycle_sleep_seconds=300,
        interval_history=[300.0],
        coverage_history=[1.0],
        wrap_count=1,
        universe_changed=False,
        coverage_summary={
            "ledger_truncated": False,
            "oldest_success_age_seconds": 0.0,
            "max_recent_observed_component_revisit_seconds": 1_200.0,
            "missing_component_count": 0,
            "components_with_observed_revisit": 1,
            "expected_component_count": 1,
        },
    )
    assert initial == {
        "status": "unsafe",
        "reason": "recent_observed_component_revisit_not_below_configured_ttl",
        "configured_redis_ttl_seconds": 900,
        "scheduled_cycle_period_seconds": 301.0,
        "scheduled_worst_case_revisit_seconds": 301.0,
        "conservative_rotating_rows_per_cycle": 1,
    }

    success_at_ms = 1_000_000
    for _ in range(12):
        success_at_ms += 500_000
        component = _update_component_success(
            component,
            success_at_ms=success_at_ms,
        )

    assert component["max_observed_revisit_seconds"] == 1_200.0
    assert component["recent_observed_revisit_seconds"] == [500.0] * 12
    recovered = _runtime_ttl_assessment(
        redis_ttl_seconds=900,
        rotating_universe_size=1,
        actual_rotating_rows_covered=1,
        elapsed_seconds=1.0,
        expected_cycle_sleep_seconds=300,
        interval_history=[300.0],
        coverage_history=[1.0],
        wrap_count=1,
        universe_changed=False,
        coverage_summary={
            "ledger_truncated": False,
            "oldest_success_age_seconds": 0.0,
            "max_recent_observed_component_revisit_seconds": max(
                component["recent_observed_revisit_seconds"]
            ),
            "missing_component_count": 0,
            "components_with_observed_revisit": 1,
            "expected_component_count": 1,
        },
    )
    assert recovered["status"] == "safe"
    assert recovered["reason"] == "observed_and_scheduled_revisit_within_configured_ttl"


def test_ticker_and_orderbook_fail_closed_on_crossed_or_one_sided_market() -> None:
    assert _parse_spot_ticker(
        {"time": 1_800_000_000_000, "price": "10", "bestBid": "11", "bestAsk": "10"},
        symbol="TESTUSDT",
        spot_symbol="TEST-USDT",
        ingested_at_ms=1_800_000_000_100,
    ) is None
    assert _parse_orderbook(
        {"time": 1_800_000_000_000, "bids": [["9", "1"]], "asks": []},
        symbol="TESTUSDT",
        kucoin_symbol="TEST-USDT",
        source="kucoin_spot_public_rest",
        ingested_at_ms=1_800_000_000_100,
    ) is None
    assert _parse_spot_ticker(
        {"time": 1_800_000_000_000, "price": "10", "bestBid": "9"},
        symbol="TESTUSDT",
        spot_symbol="TEST-USDT",
        ingested_at_ms=1_800_000_000_100,
    ) is None
    assert _parse_spot_ticker(
        {"time": 1_800_000_000_000, "price": "10"},
        symbol="TESTUSDT",
        spot_symbol="TEST-USDT",
        ingested_at_ms=1_800_000_000_100,
    ) is not None


@pytest.mark.parametrize(
    "field,value",
    [
        ("openInterest", "-1"),
        ("markPrice", "0"),
        ("indexPrice", "nan"),
        ("multiplier", "-0.1"),
    ],
)
def test_parse_kucoin_contract_rejects_invalid_domains(
    field: str,
    value: str,
) -> None:
    authority = {
        "openInterest": "1",
        "markPrice": "10",
        "indexPrice": "10",
        "multiplier": "0.01",
    }
    authority[field] = value
    assert _parse_contract(
        authority,
        symbol="TESTUSDT",
        futures_symbol="TESTUSDTM",
        ingested_at_ms=1_800_000_000_000,
    ) is None


@pytest.mark.parametrize(
    "missing_field",
    ["openInterest", "markPrice", "indexPrice", "multiplier"],
)
def test_parse_kucoin_contract_rejects_incomplete_authority_snapshot(
    missing_field: str,
) -> None:
    authority = {
        "openInterest": "1",
        "markPrice": "10",
        "indexPrice": "10",
        "multiplier": "0.01",
    }
    del authority[missing_field]
    assert _parse_contract(
        authority,
        symbol="TESTUSDT",
        futures_symbol="TESTUSDTM",
        ingested_at_ms=1_800_000_000_000,
    ) is None
