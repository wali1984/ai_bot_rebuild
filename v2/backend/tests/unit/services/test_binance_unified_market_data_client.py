from __future__ import annotations

import json
from typing import Any

from v2.backend.app.services.binance_unified_websocket_transport import (
    BinanceUnifiedMarketDataClient,
)
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    closed_candle_key,
    current_candle_key,
)


class FakeRedis:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads

    def get(self, key: str) -> str | None:
        value = self.payloads.get(key)
        return json.dumps(value) if value is not None else None


def _closed_row(symbol: str, open_ms: int, close: float) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "exchange": "binance",
        "timeframe": "1m",
        "candle_open_time": open_ms,
        "candle_close_time": open_ms + 59_999,
        "event_time": open_ms + 59_999,
        "available_at": open_ms + 59_999,
        "is_closed": True,
        "source": "binance_wss",
        "open": close - 1.0,
        "high": close + 1.0,
        "low": close - 2.0,
        "close": close,
        "volume": 10.0,
    }


def _rest_kline(open_ms: int, close: float) -> list[Any]:
    return [
        open_ms,
        str(close - 1.0),
        str(close + 1.0),
        str(close - 2.0),
        str(close),
        "10",
        open_ms + 59_999,
        "1000",
        10,
        "5",
        "500",
        "0",
    ]


def test_wss_cache_is_primary_and_rest_is_not_called() -> None:
    symbol = "BTCUSDT"
    now_ms = 1_781_545_600_000
    closed_rows = [
        _closed_row(symbol, now_ms - (index + 1) * 60_000, 100.0 + index)
        for index in range(6)
    ]
    current = {
        "symbol": symbol,
        "exchange": "binance",
        "timeframe": "1m",
        "candle_open_time": now_ms - 30_000,
        "candle_close_time": now_ms + 29_999,
        "event_time": now_ms - 5_000,
        "available_at": now_ms - 5_000,
        "is_closed": False,
        "source": "binance_wss",
        "close": 106.5,
    }
    redis = FakeRedis(
        {
            current_candle_key("binance", symbol, "1m"): current,
            closed_candle_key("binance", symbol, "1m"): closed_rows,
        }
    )

    def fail_rest(_path: str, _params: dict[str, str]) -> Any:
        raise AssertionError("REST backup should not be called when WSS cache is current")

    snapshot = BinanceUnifiedMarketDataClient(
        redis_client=redis,
        rest_get_json=fail_rest,
        clock_ms=lambda: now_ms,
    ).fetch_snapshot(symbol, timeframe="1m", limit=6)

    assert snapshot.source == "binance_usdm_wss_cache_primary"
    assert snapshot.wss_cache_used is True
    assert snapshot.rest_backup_used is False
    assert snapshot.price == 106.5
    assert snapshot.freshness_state == "CURRENT"
    assert snapshot.generated_at.endswith("-04:00")
    assert snapshot.last_event_at and snapshot.last_event_at.endswith("-04:00")
    assert len(snapshot.candles) == 6


def test_fresh_non_wss_cache_uses_labeled_cache_backup_before_rest() -> None:
    symbol = "ETHUSDT"
    now_ms = 1_781_545_600_000
    redis = FakeRedis(
        {
            current_candle_key("binance", symbol, "1m"): {
                "source": "binance_rest",
                "event_time": now_ms - 5_000,
                "close": 100.0,
            },
            closed_candle_key("binance", symbol, "1m"): [
                {
                    **_closed_row(symbol, now_ms - (index + 1) * 60_000, 100.0 + index),
                    "source": "binance_rest",
                }
                for index in range(6)
            ],
        }
    )

    def fail_rest(_path: str, _params: dict[str, str]) -> Any:
        raise AssertionError("fresh cache backup should prevent direct REST call")

    snapshot = BinanceUnifiedMarketDataClient(
        redis_client=redis,
        rest_get_json=fail_rest,
        clock_ms=lambda: now_ms,
    ).fetch_snapshot(symbol, timeframe="1m", limit=6)

    assert snapshot.source == "binance_redis_market_cache_backup"
    assert snapshot.wss_cache_used is False
    assert snapshot.cache_backup_used is True
    assert snapshot.rest_backup_used is False
    assert snapshot.price == 100.0
    assert "cache_backup_sources:binance_rest" in snapshot.errors
    assert snapshot.generated_at.endswith("-04:00")
    assert snapshot.last_event_at and snapshot.last_event_at.endswith("-04:00")


def test_stale_non_wss_cache_uses_labeled_rest_backup() -> None:
    symbol = "SOLUSDT"
    now_ms = 1_781_545_600_000
    redis = FakeRedis(
        {
            current_candle_key("binance", symbol, "1m"): {
                "source": "binance_rest",
                "event_time": now_ms - 600_000,
                "close": 100.0,
            },
            closed_candle_key("binance", symbol, "1m"): [
                {
                    **_closed_row(symbol, now_ms - (index + 11) * 60_000, 100.0 + index),
                    "source": "binance_rest",
                }
                for index in range(6)
            ],
        }
    )
    calls: list[tuple[str, dict[str, str]]] = []

    def rest(path: str, params: dict[str, str]) -> Any:
        calls.append((path, dict(params)))
        if path == "/fapi/v1/ticker/price":
            return {"symbol": symbol, "price": "206.5", "time": str(now_ms - 20_000)}
        if path == "/fapi/v1/klines":
            return [_rest_kline(now_ms - (index + 1) * 60_000, 200.0 + index) for index in range(6)]
        raise AssertionError(path)

    snapshot = BinanceUnifiedMarketDataClient(
        redis_client=redis,
        rest_get_json=rest,
        clock_ms=lambda: now_ms,
    ).fetch_snapshot(symbol, timeframe="1m", limit=6)

    assert snapshot.source == "binance_usdm_rest_backup"
    assert snapshot.cache_backup_used is False
    assert snapshot.rest_backup_used is True
    assert snapshot.rest_backup_reason
    assert snapshot.rest_backup_reason.startswith("WSS_CACHE_SOURCE_NOT_WSS")
    assert snapshot.price == 206.5
    assert [path for path, _params in calls] == ["/fapi/v1/ticker/price", "/fapi/v1/klines"]
