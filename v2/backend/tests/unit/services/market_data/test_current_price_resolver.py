"""Current price resolver invariants: priority order, staleness, exact reasons."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from v2.backend.app.services.market_data.current_price_resolver import (
    resolve_current_price,
)


class FakeRedis:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = {k: json.dumps(v) for k, v in data.items()}

    def get(self, key: str):
        return self._data.get(key)


def _fresh() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()


def test_orderbook_is_top_priority():
    r = FakeRedis({
        "v2:orderbook:top:binance:BTCUSDT": {
            "best_bid": 60000.0, "best_ask": 60010.0, "event_time": _fresh(),
        },
        "v2:market:prices:BTCUSDT": {"ticker_24hr": {"lastPrice": "59000"}},
    })
    out = resolve_current_price(r, "BTCUSDT")
    assert out["source"] == "orderbook_top_binance"
    assert out["price"] == 60005.0
    assert out["spread_usd"] == 10.0
    assert out["can_size_trade"] is True
    assert out["fallback_used"] is False


def test_stale_orderbook_falls_through_to_kline():
    r = FakeRedis({
        "v2:orderbook:top:binance:ETHUSDT": {
            "best_bid": 3000.0, "best_ask": 3001.0, "event_time": _stale(),
        },
        "v2:market:ohlcv_closed:binance:ETHUSDT:1m": [
            {"close": 3005.5, "close_time": _fresh()},
        ],
    })
    out = resolve_current_price(r, "ETHUSDT")
    assert out["source"] == "closed_kline_1m_binance"
    assert out["price"] == 3005.5
    assert out["can_size_trade"] is True


def test_nested_mark_price_from_market_prices_is_execution_grade():
    r = FakeRedis({
        "v2:market:prices:BTCUSDT": {
            "funding": {
                "markPrice": "62462.5",
                "indexPrice": "62485.2",
                "time": int(datetime.now(timezone.utc).timestamp() * 1000),
            },
        },
    })
    out = resolve_current_price(r, "BTCUSDT")
    assert out["source"] == "mark_price"
    assert out["source_priority"] == 2
    assert out["price"] == 62462.5
    assert out["fallback_used"] is False
    assert out["can_size_trade"] is True


def test_metadata_orderbook_top_cache_is_execution_grade():
    r = FakeRedis({
        "v2:market:orderbook_top:BNBUSDT": {
            "best_bid": "610.1",
            "best_ask": "610.3",
            "available_at": _fresh(),
            "source": "binance_public_websocket_orderbook_cache_primary",
            "transport": "websocket_cache_primary",
        },
    })
    out = resolve_current_price(r, "BNBUSDT")
    assert out["source"] == "orderbook_top_binance"
    assert out["source_priority"] == 1
    assert out["price"] == 610.2
    assert out["fallback_used"] is False
    assert out["execution_grade"] is True
    assert out["can_size_trade"] is True


def test_metadata_orderbook_top_rest_tagged_cache_is_fallback_not_execution_grade():
    r = FakeRedis({
        "v2:market:orderbook_top:BNBUSDT": {
            "best_bid": "610.1",
            "best_ask": "610.3",
            "available_at": _fresh(),
            "source": "binance_public_rest_depth_snapshot_fallback",
            "transport": "rest_fallback",
        },
    })
    out = resolve_current_price(r, "BNBUSDT")
    assert out["source"] == "orderbook_top_binance"
    assert out["fallback_used"] is True
    assert out["execution_grade"] is False
    assert out["can_size_trade"] is False


def test_metadata_mark_price_cache_is_execution_grade():
    r = FakeRedis({
        "v2:market:mark_price:SOLUSDT": {
            "symbol": "SOLUSDT",
            "mark_price": "143.25",
            "index_price": "143.30",
            "binance_time_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "source": "binance_public_websocket_cache_primary",
            "transport": "websocket_cache_primary",
        },
    })
    out = resolve_current_price(r, "SOLUSDT")
    assert out["source"] == "mark_price"
    assert out["source_priority"] == 2
    assert out["price"] == 143.25
    assert out["fallback_used"] is False
    assert out["can_size_trade"] is True


def test_current_kline_can_supply_fresh_current_price():
    r = FakeRedis({
        "v2:market:kline_current:binance:ETHUSDT:1m": {
            "close": 3001.25,
            "event_time": _fresh(),
            "closed_candle": False,
        },
    })
    out = resolve_current_price(r, "ETHUSDT")
    assert out["source"] == "current_kline_1m_binance"
    assert out["source_priority"] == 4
    assert out["price"] == 3001.25
    assert out["can_size_trade"] is True


def test_rest_orderbook_array_is_timestamped_fallback_not_execution_grade():
    r = FakeRedis({
        "v2:market:orderbook:binance:XRPUSDT": {
            "bids": [["0.50", "100"]],
            "asks": [["0.51", "120"]],
            "available_at": _fresh(),
            "source": "binance_public_rest_depth_snapshot",
        },
    })
    out = resolve_current_price(r, "XRPUSDT")
    assert out["source"] == "rest_orderbook_binance_fallback"
    assert out["source_priority"] == 6
    assert out["price"] == 0.505
    assert out["fallback_used"] is True
    assert out["execution_grade"] is False
    assert out["can_size_trade"] is False


def test_totally_unknown_symbol_gets_no_exchange_market():
    out = resolve_current_price(FakeRedis({}), "GHOSTUSDT")
    assert out["price"] is None
    assert out["can_size_trade"] is False
    assert out["reason_if_missing"] == "NO_EXCHANGE_MARKET"


def test_only_stale_data_gets_feed_stale():
    r = FakeRedis({
        "v2:market:prices:OLDUSDT": {
            "ticker_24hr": {"lastPrice": "1.23", "closeTime": 1600000000000},
        },
    })
    out = resolve_current_price(r, "OLDUSDT")
    assert out["price"] is None
    assert out["reason_if_missing"] == "FEED_STALE"


def test_rest_fallback_is_marked_and_timestamped():
    r = FakeRedis({
        "v2:market:prices:SOLUSDT": {
            "ticker_24hr": {
                "lastPrice": "150.5", "bidPrice": "150.4", "askPrice": "150.6",
                "closeTime": int(datetime.now(timezone.utc).timestamp() * 1000) - 300_000,
            },
        },
    })
    out = resolve_current_price(r, "SOLUSDT")
    assert out["source"] == "rest_ticker_24hr_fallback"
    assert out["fallback_used"] is True
    assert out["can_size_trade"] is False
    assert out["available_at"] is not None
    assert out["staleness_seconds"] > 120
