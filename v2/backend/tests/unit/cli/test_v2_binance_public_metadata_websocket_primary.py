from __future__ import annotations

import json
from typing import Any

import pytest

from v2.backend.app.cli import v2_binance_public_metadata_ingestor as metadata
from v2.backend.app.cli import v2_native_ingestors_live_loop as native_loop


class FakeRedis:
    def __init__(self, initial: dict[str, Any]) -> None:
        self.store = {
            key: json.dumps(value, separators=(",", ":"))
            for key, value in initial.items()
        }

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


def _fail_rest(_url: str) -> Any:
    raise AssertionError("REST fallback must not be called when WSS/cache data is present")


def test_public_metadata_fetches_websocket_cache_before_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_client = FakeRedis(
        {
            "v2:market:funding:BTCUSDT": {
                "symbol": "BTCUSDT",
                "mark_price": 62840.2,
                "index_price": 62864.8,
                "funding_rate": 0.00006873,
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:market:open_interest:BTCUSDT": {
                "symbol": "BTCUSDT",
                "openInterest": "99398.552",
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:orderbook:top:binance:BTCUSDT": {
                "symbol": "BTCUSDT",
                "best_bid": 62877.8,
                "best_ask": 62877.9,
                "source": "direct_binance",
            },
        }
    )
    monkeypatch.setattr(metadata, "_http_get_json", _fail_rest)

    premium = metadata.fetch_premium_index("BTCUSDT", redis_client=redis_client)
    open_interest = metadata.fetch_open_interest("BTCUSDT", redis_client=redis_client)
    orderbook = metadata.fetch_orderbook("BTCUSDT", redis_client=redis_client)

    assert premium["transport"] == "websocket_cache_primary"
    assert premium["mark_price"] == 62840.2
    assert open_interest["transport"] == "websocket_cache_primary"
    assert open_interest["open_interest_contracts"] == 99398.552
    assert orderbook["transport"] == "websocket_cache_primary"
    assert orderbook["best_bid"] == 62877.8


def test_public_metadata_report_records_no_rest_when_cache_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_client = FakeRedis(
        {
            "v2:market:funding:BTCUSDT": {
                "symbol": "BTCUSDT",
                "mark_price": 62840.2,
                "index_price": 62864.8,
                "funding_rate": 0.00006873,
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:market:open_interest:BTCUSDT": {
                "symbol": "BTCUSDT",
                "openInterest": "99398.552",
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:orderbook:top:binance:BTCUSDT": {
                "symbol": "BTCUSDT",
                "best_bid": 62877.8,
                "best_ask": 62877.9,
                "source": "direct_binance",
            },
        }
    )
    monkeypatch.setattr(metadata, "_redis_client", lambda: redis_client)
    monkeypatch.setattr(metadata, "_http_get_json", _fail_rest)

    report = metadata.run_once(["BTCUSDT"], ttl_s=30)

    assert report["transport_policy"] == "binance_public_websocket_cache_primary_rest_fallback_only"
    assert report["rest_used_as_primary"] is False
    assert report["endpoints_used_this_cycle"] == []
    assert report["rest_fallback_blocked_count"] == 0


def test_public_metadata_blocks_rest_when_cache_missing_and_fallback_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)
    monkeypatch.setattr(metadata, "_redis_client", lambda: FakeRedis({}))

    report = metadata.run_once(["BTCUSDT"], ttl_s=30)

    assert report["rest_fallback_allowed"] is False
    assert report["rest_used_as_primary"] is False
    assert report["endpoints_used_this_cycle"] == []
    assert report["rest_fallback_blocked_count"] == 3
    assert report["errors"] == 3


def test_native_ingestor_bundle_uses_websocket_cache_before_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_client = FakeRedis(
        {
            "v2:market:prices:BTCUSDT": {
                "symbol": "BTCUSDT",
                "ticker_24hr": {"lastPrice": "62840.2"},
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:market:funding:BTCUSDT": {
                "symbol": "BTCUSDT",
                "funding_rate": 0.00006873,
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:market:open_interest:BTCUSDT": {
                "symbol": "BTCUSDT",
                "openInterest": "99398.552",
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:orderbook:top:binance:BTCUSDT": {
                "symbol": "BTCUSDT",
                "best_bid": 62877.8,
                "best_ask": 62877.9,
                "source": "direct_binance",
            },
            "v2:market:ohlcv_closed:binance:BTCUSDT:1m": [
                {
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "open": 1,
                    "high": 2,
                    "low": 1,
                    "close": 2,
                    "volume": 10,
                    "candle_close_time": 1783589160000,
                    "is_closed": True,
                    "source": "binance_wss",
                }
            ],
        }
    )
    monkeypatch.setattr(native_loop, "_http_get_json", _fail_rest)

    bundle = native_loop._fetch_symbol_bundle(
        "BTCUSDT",
        kline_timeframes=("1m",),
        redis_client=redis_client,
    )

    assert bundle["transport"] == "websocket_cache_primary"
    assert bundle["rest_fallback_used"] is False
    assert bundle["symbol_info"]["cache_primary_field_count"] >= 4
    assert bundle["ticker"]["transport"] == "websocket_cache_primary"
    assert bundle["klines_by_timeframe"]["1m"][0]["source"] == "binance_wss"


def test_native_ingestor_does_not_treat_rest_kline_cache_as_websocket_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis(
        {
            "v2:market:ohlcv_closed:binance:BTCUSDT:1m": [
                {
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "open": 1,
                    "high": 2,
                    "low": 1,
                    "close": 2,
                    "volume": 10,
                    "candle_close_time": 1783589160000,
                    "is_closed": True,
                    "source": "binance_rest",
                }
            ],
        }
    )
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)
    monkeypatch.setattr(native_loop, "_http_get_json", _fail_rest)

    rows = native_loop._fetch_klines("BTCUSDT", interval="1m", limit=10, redis_client=redis_client)

    assert rows is None
