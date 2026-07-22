from __future__ import annotations

import json

from v2.backend.app.cli import v2_binance_mark_price_wss_seeder as seeder


class FakeRedis:
    def __init__(self) -> None:
        self.writes: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.writes[key] = value
        self.ttls[key] = int(ex or 0)


def test_process_mark_price_message_writes_requested_symbols_only() -> None:
    redis = FakeRedis()
    raw = [
        {
            "e": "markPriceUpdate",
            "E": 1780000000000,
            "s": "BTCUSDT",
            "p": "60000.5",
            "i": "60001.0",
            "r": "0.0001",
            "T": 1780003600000,
        },
        {"e": "markPriceUpdate", "E": 1780000000001, "s": "ETHUSDT", "p": "3000.25", "i": "3000.5"},
    ]

    result = seeder.process_mark_price_message(
        raw,
        symbols={"BTCUSDT"},
        redis_client=redis,
        ttl_seconds=77,
    )

    assert result["observed_count"] == 1
    assert result["symbols_observed"] == ["BTCUSDT"]
    assert result["redis_keys_written"] == ["v2:market:mark_price:BTCUSDT"]
    assert redis.ttls["v2:market:mark_price:BTCUSDT"] == 77
    payload = json.loads(redis.writes["v2:market:mark_price:BTCUSDT"])
    assert payload["mark_price"] == 60000.5
    assert payload["index_price"] == 60001.0
    assert payload["source"] == "binance_usdm_wss_mark_price_all_symbols"
    assert payload["transport"] == "websocket_primary"
    assert payload["event_time"] == "2026-05-28T20:26:40.000Z"
    assert payload["generated_at"] == payload["available_at"]
    assert payload["received_at"] == payload["available_at"]
    assert payload["expected_update_interval_seconds"] == 1.0
    assert payload["places_real_order"] is False
    assert payload["test_orders"] is False
    assert payload["leverage_mutation"] is False
    assert payload["margin_mode_mutation"] is False
    assert payload["transfer_or_withdrawal"] is False
    assert payload["raw_credentials_exposed"] is False


def test_process_combined_stream_payload() -> None:
    result = seeder.process_mark_price_message(
        json.dumps(
            {
                "stream": "!markPrice@arr",
                "data": [
                    {"E": 1780000000000, "s": "SOLUSDT", "p": "150.0", "i": "150.1"},
                ],
            }
        ),
        symbols={"SOLUSDT"},
        redis_client=None,
    )

    assert result["observed_count"] == 1
    assert result["symbols_observed"] == ["SOLUSDT"]
    assert result["redis_keys_written"] == []


def test_safe_set_rejects_non_market_keys() -> None:
    redis = FakeRedis()

    try:
        seeder._safe_set(redis, "v2:orders:bad", {"x": 1}, ttl_seconds=1)
    except ValueError as exc:
        assert "refused_non_market_key" in str(exc)
    else:
        raise AssertionError("expected non-market key to be rejected")


def test_safe_set_rejects_non_finite_json() -> None:
    redis = FakeRedis()

    try:
        seeder._safe_set(
            redis,
            "v2:market:mark_price:BTCUSDT",
            {"mark_price": float("nan")},
            ttl_seconds=1,
        )
    except ValueError as exc:
        assert "Out of range float values" in str(exc)
    else:
        raise AssertionError("expected non-finite JSON to be rejected")

    assert redis.writes == {}
