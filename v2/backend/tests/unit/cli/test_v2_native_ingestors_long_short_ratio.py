from __future__ import annotations

import json

import pytest

from v2.backend.app.cli import v2_native_ingestors_live_loop as loop


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


def test_fetch_long_short_ratio_normalizes_binance_row(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str):
        assert "globalLongShortAccountRatio" in url
        return [
            {
                "symbol": "BTCUSDT",
                "longShortRatio": "1.25",
                "longAccount": "0.555",
                "shortAccount": "0.445",
                "timestamp": "1715500120000",
            }
        ]

    monkeypatch.setattr(loop, "_http_get_json", fake_get)

    payload = loop._fetch_long_short_ratio("BTCUSDT")

    assert payload is not None
    assert payload["long_short_ratio"] == 1.25
    assert payload["long_account_ratio"] == 0.555
    assert payload["short_account_ratio"] == 0.445
    assert payload["source"] == "binance_global_long_short_account_ratio"


def test_fetch_long_short_ratio_restricted_binance_payload_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        loop,
        "_http_get_json",
        lambda _url: {
            "code": 0,
            "msg": "Service unavailable from a restricted location.",
        },
    )

    assert loop._fetch_long_short_ratio("BTCUSDT") is None


def test_write_symbol_bundle_adds_orderbook_temporal_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    keys_written: list[str] = []
    monkeypatch.setattr(loop, "_utc_iso", lambda: "2026-07-05T23:44:00Z")

    loop._write_symbol_bundle(
        fake,
        "BTCUSDT",
        {
            "orderbook": {
                "lastUpdateId": 123,
                "bids": [["100", "2"]],
                "asks": [["101", "3"]],
            },
        },
        keys_written,
    )

    assert f"{loop.V2_REDIS_PREFIX}market:orderbook:BTCUSDT" in keys_written
    assert f"{loop.V2_REDIS_PREFIX}market:orderbook:binance:BTCUSDT" in keys_written
    payload = json.loads(fake.store[f"{loop.V2_REDIS_PREFIX}market:orderbook:BTCUSDT"])
    assert payload["source"] == "binance_public_rest_depth_snapshot"
    assert payload["exchange"] == "binance"
    assert payload["transaction_time"] == "2026-07-05T23:44:00Z"
    assert payload["received_at"] == "2026-07-05T23:44:00Z"
    assert payload["available_at"] == "2026-07-05T23:44:00Z"
    assert payload["event_time"] is None
    assert payload["event_time_missing_reason"] == (
        "BINANCE_REST_DEPTH_SNAPSHOT_HAS_NO_EXCHANGE_EVENT_TIME"
    )
