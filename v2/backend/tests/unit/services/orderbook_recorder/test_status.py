from __future__ import annotations

from v2.backend.app.services.orderbook_recorder.status import (
    audit_configured_symbol_feed_coverage,
    default_universe_gap_status,
    summarize_direct_feed_coverage,
)


def test_summarize_direct_feed_coverage_reports_required_feeds() -> None:
    summary = summarize_direct_feed_coverage(
        {
            "binance:BTCUSDT": {
                "exchange": "binance",
                "symbol": "BTCUSDT",
                "depth_levels": [5, 10, 20],
                "feed_speeds_ms": [100, 250],
                "has_book_ticker": True,
                "has_diff_depth": True,
            },
            "kucoin:BTCUSDT": {
                "exchange": "kucoin",
                "symbol": "BTCUSDT",
                "depth_levels": [5, 50, "increment_best_500"],
                "feed_speeds_ms": [10, 100],
                "has_kucoin_increment_best_500": True,
            },
        }
    )

    assert summary["binance_book_ticker_persisted"] is True
    assert summary["binance_partial_depth_5_10_20_persisted"] is True
    assert summary["binance_diff_depth_persisted"] is True
    assert summary["binance_100ms_depth_persisted"] is True
    assert summary["binance_250ms_depth_persisted"] is True
    assert summary["kucoin_best_5_50_persisted"] is True
    assert summary["kucoin_increment_best_500_persisted"] is True
    assert summary["kucoin_10ms_increment_persisted"] is True


def test_configured_symbol_feed_coverage_flags_missing_symbols() -> None:
    audit = audit_configured_symbol_feed_coverage(
        feed_coverage={
            "binance:BTCUSDT": {
                "exchange": "binance",
                "depth_levels": [5, 10, 20],
                "feed_speeds_ms": [100, 250],
                "has_book_ticker": True,
                "has_diff_depth": True,
            },
            "kucoin:BTCUSDT": {
                "exchange": "kucoin",
                "depth_levels": [5, 50],
                "feed_speeds_ms": [100],
                "has_kucoin_increment_best_500": False,
            },
        },
        configured_symbols=["BTCUSDT", "ETHUSDT"],
    )

    assert audit["complete_symbols"] == ["BTCUSDT"]
    assert audit["incomplete_symbols"] == ["ETHUSDT"]
    assert audit["all_configured_symbols_have_required_direct_feed_coverage"] is False
    assert audit["active_direct_orderbook_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert audit["active_direct_orderbook_symbols_without_required_coverage"] == ["ETHUSDT"]
    assert audit["all_active_direct_orderbook_symbols_have_required_direct_feed_coverage"] is False
    assert audit["non_blocking_symbols_missing_kucoin_increment_best_500"] == ["BTCUSDT"]
    assert audit["by_symbol"]["BTCUSDT"]["kucoin_increment_best_500_status"] == "not_observed_or_not_supported_in_capture_window"


def test_default_universe_gap_status_emits_remaining_shards() -> None:
    status = default_universe_gap_status(
        feed_coverage={
            "binance:BTCUSDT": {
                "exchange": "binance",
                "depth_levels": [5, 10, 20],
                "feed_speeds_ms": [100, 250],
                "has_book_ticker": True,
                "has_diff_depth": True,
            },
            "kucoin:BTCUSDT": {
                "exchange": "kucoin",
                "depth_levels": [5, 50, "increment_best_500"],
                "feed_speeds_ms": [10, 100],
                "has_kucoin_increment_best_500": True,
            },
        },
        default_symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        shard_size=2,
    )

    assert status["default_universe_symbol_count"] == 3
    assert status["default_universe_complete_symbol_count"] == 1
    assert status["default_universe_incomplete_symbol_count"] == 2
    assert status["all_default_universe_symbols_have_required_direct_feed_coverage"] is False
    assert status["all_active_direct_orderbook_symbols_have_required_direct_feed_coverage"] is False
    assert status["remaining_shards"][0]["symbols"] == ["ETHUSDT", "SOLUSDT"]
    assert "--exchange binance" in status["remaining_shards"][0]["binance_250ms_command"]
    assert "where observed/supported" in status["coverage_requirement"]["kucoin"]


def test_provider_support_gaps_are_non_retryable_recorder_gaps() -> None:
    audit = audit_configured_symbol_feed_coverage(
        feed_coverage={
            "binance:BICOUSDT": {
                "exchange": "binance",
                "depth_levels": [5, 10, 20],
                "feed_speeds_ms": [100, 250],
                "has_book_ticker": True,
                "has_diff_depth": True,
            },
        },
        configured_symbols=["BICOUSDT"],
        provider_symbol_support={
            "binance": {"BICOUSDT": {"orderbook_supported": True}},
            "kucoin": {
                "BICOUSDT": {
                    "provider_symbol": "BICOUSDTM",
                    "listed": False,
                    "status": "MISSING",
                    "orderbook_supported": False,
                }
            },
        },
    )

    row = audit["by_symbol"]["BICOUSDT"]
    assert row["provider_supported_complete"] is True
    assert row["any_supported_direct_provider"] is True
    assert row["active_direct_orderbook_symbol"] is True
    assert row["direct_live_orderbook_available"] is True
    assert row["multi_exchange_orderbook_available"] is False
    assert row["missing"] == []
    assert row["provider_support_gaps"] == ["kucoin_futures_contract_not_open_or_not_listed"]
    assert audit["retryable_incomplete_symbols"] == []
    assert audit["non_retryable_provider_gap_symbols"] == ["BICOUSDT"]
    assert audit["symbols_without_any_supported_direct_provider"] == []
    assert audit["active_direct_orderbook_symbols"] == ["BICOUSDT"]
    assert audit["single_venue_direct_orderbook_symbols"] == ["BICOUSDT"]
    assert audit["all_active_direct_orderbook_symbols_have_required_direct_feed_coverage"] is True
    assert audit["all_provider_supported_required_direct_feeds_have_coverage"] is True


def test_default_universe_gap_status_only_shards_retryable_symbols_with_support_metadata() -> None:
    status = default_universe_gap_status(
        feed_coverage={
            "binance:BICOUSDT": {
                "exchange": "binance",
                "depth_levels": [5, 10, 20],
                "feed_speeds_ms": [100, 250],
                "has_book_ticker": True,
                "has_diff_depth": True,
            },
            "kucoin:SUNUSDT": {
                "exchange": "kucoin",
                "depth_levels": [5, 50],
                "feed_speeds_ms": [100],
            },
        },
        default_symbols=["BICOUSDT", "SUNUSDT"],
        provider_symbol_support={
            "binance": {
                "BICOUSDT": {"orderbook_supported": True},
                "SUNUSDT": {"orderbook_supported": True},
            },
            "kucoin": {
                "BICOUSDT": {"orderbook_supported": False},
                "SUNUSDT": {"orderbook_supported": True},
            },
        },
    )

    audit = status["default_universe_audit"]
    assert audit["incomplete_symbols"] == ["BICOUSDT", "SUNUSDT"]
    assert audit["retryable_incomplete_symbols"] == ["SUNUSDT"]
    assert audit["non_retryable_provider_gap_symbols"] == ["BICOUSDT"]
    assert audit["active_direct_orderbook_symbols"] == ["BICOUSDT", "SUNUSDT"]
    assert audit["active_direct_orderbook_symbols_without_required_coverage"] == []
    assert audit["all_active_direct_orderbook_symbols_have_required_direct_feed_coverage"] is True
    assert audit["all_provider_supported_required_direct_feeds_have_coverage"] is False
    assert status["active_direct_orderbook_symbol_count"] == 2
    assert status["all_active_direct_orderbook_symbols_have_required_direct_feed_coverage"] is True
    assert status["all_supported_provider_feeds_have_required_direct_feed_coverage"] is False
    assert status["single_venue_direct_orderbook_symbols"] == ["BICOUSDT", "SUNUSDT"]
    assert status["unsupported_symbols_excluded_from_active_orderbook_universe"] == []
    assert status["remaining_shards"][0]["symbols"] == ["SUNUSDT"]


def test_no_supported_provider_symbol_is_excluded_from_active_orderbook_universe() -> None:
    audit = audit_configured_symbol_feed_coverage(
        feed_coverage={},
        configured_symbols=["IPUSDT"],
        provider_symbol_support={
            "binance": {"IPUSDT": {"status": "SETTLING", "orderbook_supported": False}},
            "kucoin": {"IPUSDT": {"status": "MISSING", "orderbook_supported": False}},
        },
    )

    row = audit["by_symbol"]["IPUSDT"]
    assert row["any_supported_direct_provider"] is False
    assert row["active_direct_orderbook_symbol"] is False
    assert row["direct_live_orderbook_available"] is False
    assert row["provider_supported_complete"] is False
    assert row["missing"] == []
    assert row["provider_support_gaps"] == [
        "binance_contract_not_trading_or_not_listed",
        "kucoin_futures_contract_not_open_or_not_listed",
    ]
    assert audit["active_direct_orderbook_symbols"] == []
    assert audit["symbols_without_any_supported_direct_provider"] == ["IPUSDT"]
    assert audit["all_active_direct_orderbook_symbols_have_required_direct_feed_coverage"] is False
