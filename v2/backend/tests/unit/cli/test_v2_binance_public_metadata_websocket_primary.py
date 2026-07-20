from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

import pytest

from v2.backend.app.cli import v2_binance_public_metadata_ingestor as metadata
from v2.backend.app.cli import v2_native_ingestors_live_loop as native_loop


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    producer_available_at = _now_iso()
    redis_client = FakeRedis(
        {
            "v2:market:mark_price:BTCUSDT": {
                "symbol": "BTCUSDT",
                "mark_price": 62840.2,
                "index_price": 62864.8,
                "funding_rate": 0.00006873,
                "event_time": producer_available_at,
                "generated_at": producer_available_at,
                "available_at": producer_available_at,
                "expected_update_interval_seconds": 1.0,
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:market:open_interest:BTCUSDT": {
                "symbol": "BTCUSDT",
                "openInterest": "99398.552",
                # Cache-echo freshness gate: an undated or stale payload must
                # fail through to REST, so a fresh timestamp is required for
                # the cache-primary path to be taken.
                "time": _now_ms(),
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:orderbook:top:binance:BTCUSDT": {
                "symbol": "BTCUSDT",
                "best_bid": 62877.8,
                "best_ask": 62877.9,
                "available_at": _now_iso(),
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
    assert premium["generated_at"] == producer_available_at
    assert premium["available_at"] == producer_available_at
    assert premium["consumer_observed_at"] == premium["republished_at"]
    assert premium["expected_update_interval_seconds"] == 1.0
    assert premium["binance_time_ms"] is None
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
                "time": _now_ms(),
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:market:open_interest:BTCUSDT": {
                "symbol": "BTCUSDT",
                "openInterest": "99398.552",
                "time": _now_ms(),
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:orderbook:top:binance:BTCUSDT": {
                "symbol": "BTCUSDT",
                "best_bid": 62877.8,
                "best_ask": 62877.9,
                "available_at": _now_iso(),
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
    producer_available_at = _now_iso()
    redis_client = FakeRedis(
        {
            "v2:market:prices:BTCUSDT": {
                "symbol": "BTCUSDT",
                # closeTime + quoteVolume required: a stale/undated or
                # price-only (no 24h stats) cache echo must fail through
                # instead of masquerading as a live 24hr ticker.
                "ticker_24hr": {
                    "lastPrice": "62840.2",
                    "quoteVolume": "1234567890.12",
                    "closeTime": _now_ms(),
                },
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:market:funding:BTCUSDT": {
                "symbol": "BTCUSDT",
                "funding_rate": 0.00006873,
                "time": _now_ms(),
                "generated_at": producer_available_at,
                "available_at": producer_available_at,
                "expected_update_interval_seconds": 1.0,
                "source": "binance_public_websocket_cache_primary",
            },
            "v2:market:open_interest:BTCUSDT": {
                "symbol": "BTCUSDT",
                "openInterest": "99398.552",
                "time": _now_ms(),
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
    # Deterministic regardless of ambient env: with a fresh cache no REST is
    # needed, and _fail_rest still guards any accidental REST attempt.
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)
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
    assert bundle["funding"]["generated_at"] == producer_available_at
    assert bundle["funding"]["available_at"] == producer_available_at
    assert bundle["funding"]["consumer_observed_at"] == bundle["funding"]["republished_at"]
    assert bundle["funding"]["expected_update_interval_seconds"] == 1.0
    assert bundle["klines_by_timeframe"]["1m"][0]["source"] == "binance_wss"


def test_public_metadata_rejects_stale_self_echo_and_uses_fresh_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_ms = _now_ms() - 60 * 60 * 1000
    fresh_ms = _now_ms()
    redis_client = FakeRedis(
        {
            "v2:market:mark_price:BTCUSDT": {
                "symbol": "BTCUSDT",
                "mark_price": 1.0,
                "index_price": 1.0,
                "binance_time_ms": stale_ms,
                "source": "binance_public_rest_premium_index_fallback",
            },
            "v2:market:funding:BTCUSDT": {
                "symbol": "BTCUSDT",
                "markPrice": "1.0",
                "indexPrice": "1.0",
                "time": stale_ms,
                "source": "binance_public_websocket_cache_primary",
            },
        }
    )
    monkeypatch.setattr(
        metadata,
        "_http_get_json",
        lambda _url: {
            "symbol": "BTCUSDT",
            "markPrice": "2.0",
            "indexPrice": "1.9",
            "lastFundingRate": "0.0001",
            "time": fresh_ms,
        },
    )

    premium = metadata.fetch_premium_index("BTCUSDT", redis_client=redis_client)

    assert premium["mark_price"] == 2.0
    assert premium["index_price"] == 1.9
    assert premium["binance_time_ms"] == fresh_ms
    assert premium["source"] == "binance_public_rest_premium_index_fallback"
    assert premium["transport"] == "rest_fallback"
    assert premium["generated_at"] == premium["available_at"]


def test_native_ingestor_rejects_stale_funding_echo_and_uses_fresh_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_ms = _now_ms() - 60 * 60 * 1000
    fresh_ms = _now_ms()
    redis_client = FakeRedis(
        {
            "v2:market:funding:BTCUSDT": {
                "symbol": "BTCUSDT",
                "markPrice": "1.0",
                "indexPrice": "1.0",
                "time": stale_ms,
                "source": "binance_public_websocket_cache_primary",
            }
        }
    )
    monkeypatch.setenv("BINANCE_REST_FALLBACK_ALLOWED", "true")
    monkeypatch.setattr(
        native_loop,
        "_http_get_json",
        lambda _url, *, fallback_reason: {
            "symbol": "BTCUSDT",
            "markPrice": "2.0",
            "indexPrice": "1.9",
            "lastFundingRate": "0.0001",
            "time": fresh_ms,
        },
    )

    funding = native_loop._fetch_funding("BTCUSDT", redis_client=redis_client)

    assert funding is not None
    assert funding["markPrice"] == "2.0"
    assert funding["time"] == fresh_ms
    assert funding["source"] == "binance_public_rest_premium_index_fallback"
    assert funding["transport"] == "rest_fallback"
    assert funding["generated_at"] == funding["available_at"]


def test_premium_index_cache_age_rejects_future_event_time() -> None:
    future_ms = _now_ms() + 60_000

    assert metadata._premium_index_cache_age_seconds({"event_time": future_ms}) is None
    assert native_loop._funding_cache_age_seconds({"event_time": future_ms}) is None


def test_premium_index_selects_freshest_valid_candidate_then_websocket() -> None:
    now_ms = _now_ms()
    producer_available_at = _now_iso()
    redis_client = FakeRedis(
        {
            "v2:market:mark_price:BTCUSDT": {
                "mark_price": 1.0,
                "index_price": 1.0,
                "event_time": now_ms - 10_000,
                "source": "binance",
                "transport": "rest_fallback",
            },
            "v2:market:funding:BTCUSDT": {
                "mark_price": 2.0,
                "index_price": 1.9,
                "event_time": now_ms - 1_000,
                "source": "binance",
                "transport": "rest_fallback_cache",
            },
            "v2:market:prices:BTCUSDT": {
                "funding": {
                    "mark_price": 3.0,
                    "index_price": 2.9,
                    "event_time": now_ms - 1_000,
                    "generated_at": producer_available_at,
                    "available_at": producer_available_at,
                    "expected_update_interval_seconds": 1.0,
                    "source": "binance_usdm_wss_mark_price_all_symbols",
                    "transport": "websocket_primary",
                },
                "generated_at": producer_available_at,
                "available_at": producer_available_at,
            },
        }
    )

    premium = metadata.fetch_premium_index("BTCUSDT", redis_client=redis_client)
    funding = native_loop._fetch_funding("BTCUSDT", redis_client=redis_client)

    assert premium["mark_price"] == 3.0
    assert premium["source_key"] == "v2:market:prices:BTCUSDT.funding"
    assert funding is not None
    assert funding["markPrice"] == 3.0
    assert funding["source_key"] == "v2:market:prices:BTCUSDT.funding"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "NaN", "Inf"])
def test_market_numeric_parser_rejects_nonfinite_values(value: object) -> None:
    assert metadata._safe_float(value) is None
    assert native_loop._safe_float(value) is None


def test_cache_transport_uses_both_source_and_transport_fields() -> None:
    conflicting = {"source": "binance", "transport": "rest_fallback"}

    assert metadata._cache_transport(conflicting) == "rest_fallback_cache"
    assert native_loop._cache_transport(conflicting) == "rest_fallback_cache"
    assert native_loop._is_websocket_cache_payload(conflicting) is False


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
