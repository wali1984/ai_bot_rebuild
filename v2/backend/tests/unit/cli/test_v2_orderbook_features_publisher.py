from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from v2.backend.app.cli import v2_orderbook_features_publisher as supervisor


class _Redis:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = {
            key: json.dumps(value, separators=(",", ":")) for key, value in values.items()
        }
        self.set_keys: list[str] = []

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, *, ex: int) -> bool:
        assert ex > 0
        self.set_keys.append(key)
        self.values[key] = value
        return True


def _clock(offset_seconds: float = 0.0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _pair(
    *,
    event_offset: float = -0.2,
    available_offset: float = -0.1,
) -> tuple[dict[str, object], dict[str, object]]:
    common: dict[str, object] = {
        "source": "direct_binance",
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "sequence_id": 10,
        "previous_sequence_id": 9,
        "sequence_gap": False,
        "sequence_gap_flag": 0.0,
        "event_time": _clock(event_offset),
        "transaction_time": _clock(event_offset - 0.01),
        "received_at": _clock(available_offset - 0.01),
        "available_at": _clock(available_offset),
        "generated_at": _clock(available_offset + 0.01),
        "update_type": "partial_depth",
        "depth_level": 20,
        "feed_speed_ms": 250,
    }
    depth = {
        **common,
        "schema_version": supervisor.DIRECT_DEPTH_SCHEMA,
        "bids": [{"price": 100.0, "quantity": 2.0}],
        "asks": [{"price": 101.0, "quantity": 2.0}],
    }
    features = {**common, "schema_version": supervisor.DIRECT_FEATURES_SCHEMA}
    return depth, features


def _client(depth: object, features: object) -> _Redis:
    return _Redis(
        {
            "v2:orderbook:depth:binance:BTCUSDT": depth,
            "v2:orderbook:features:binance:BTCUSDT": features,
        }
    )


def _cycle(client: _Redis) -> dict[str, object]:
    return supervisor.run_cycle(
        client,
        symbols=["BTCUSDT"],
        ttl_seconds=60,
        max_book_age_seconds=30.0,
    )


def test_supervisor_accepts_exact_direct_pair_and_writes_summary_only() -> None:
    client = _client(*_pair())

    summary = _cycle(client)

    assert summary["canonical_pair_healthy"] == 1
    assert summary["canonical_pair_unhealthy"] == 0
    assert summary["features_written"] == 0
    assert summary["per_symbol_feature_write_authorized"] is False
    assert summary["trainer_admission_authorized"] is False
    assert summary["paper_trading_authorized"] is False
    assert summary["live_execution_authorized"] is False
    assert client.set_keys == [supervisor.SUMMARY_KEY]


def test_supervisor_rejects_future_or_reordered_availability_clock() -> None:
    for depth, features in (
        _pair(event_offset=-0.2, available_offset=10.0),
        _pair(event_offset=-0.05, available_offset=-0.2),
    ):
        summary = _cycle(_client(depth, features))
        assert summary["canonical_pair_healthy"] == 0
        assert summary["canonical_pair_reasons"] == {"CLOCK_INVALID": 1}


def test_supervisor_rejects_stale_pair_without_overwriting_it() -> None:
    client = _client(*_pair(event_offset=-120.0, available_offset=-119.9))

    summary = _cycle(client)

    assert summary["canonical_pair_reasons"] == {"STALE": 1}
    assert client.set_keys == [supervisor.SUMMARY_KEY]


def test_supervisor_rejects_split_sequence_even_when_each_payload_looks_valid() -> None:
    depth, features = _pair()
    features["sequence_id"] = 11

    summary = _cycle(_client(depth, features))

    assert summary["canonical_pair_reasons"] == {"PAIR_MISMATCH": 1}


def test_supervisor_classifies_malformed_gap_flag_without_crashing() -> None:
    depth, features = _pair()
    depth["sequence_gap_flag"] = "not-a-number"
    features["sequence_gap_flag"] = "not-a-number"

    summary = _cycle(_client(depth, features))

    assert summary["canonical_pair_reasons"] == {"SEQUENCE_GAP": 1}


def test_supervisor_rejects_wrong_schema_source_or_depth_shape() -> None:
    for mutate in ("schema", "source", "shape"):
        depth, features = _pair()
        if mutate == "schema":
            features["schema_version"] = "v2_orderbook_features_v1"
        elif mutate == "source":
            depth["source"] = "generic_cache"
        else:
            depth["bids"] = []
        summary = _cycle(_client(depth, features))
        expected = "DEPTH_SHAPE_INVALID" if mutate == "shape" else "IDENTITY_INVALID"
        assert summary["canonical_pair_reasons"] == {expected: 1}


def test_summary_writer_cannot_write_per_symbol_feature_key() -> None:
    client = _Redis({})
    assert (
        supervisor._safe_set_json(
            client,
            "v2:orderbook:features:binance:BTCUSDT",
            {"forged": True},
            ttl_seconds=60,
        )
        is False
    )
    assert client.set_keys == []


def test_naive_iso_timestamp_is_not_treated_as_utc() -> None:
    assert supervisor._timestamp_ms("2026-07-21T12:00:00") is None
