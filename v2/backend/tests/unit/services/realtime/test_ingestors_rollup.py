"""Consolidated ingestor / provider-health roll-up on the system_health snapshot."""
from __future__ import annotations

import fnmatch
import json
from datetime import datetime, timezone

from app.services.realtime.operator_snapshot import _ingestors_payload, _system_health_payload


class _FakeRedis:
    def __init__(self, data: dict[str, object]) -> None:
        self._d = data

    def scan_iter(self, match: str = "*", count: int = 64):
        for k in list(self._d):
            if fnmatch.fnmatch(k, match):
                yield k

    def get(self, key: str):
        v = self._d.get(key)
        return None if v is None else (v if isinstance(v, str) else json.dumps(v))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _healthy_data() -> dict[str, object]:
    return {
        "v2:market:kline_current:binance:BTCUSDT:1m": "[]",
        "v2:features:ta_full:BTCUSDT:5m": json.dumps({"classification": "V2_FULL_TALIB_TA_OK"}),
        "v2:features:snapshot:abc": json.dumps({"features": {}}),
        "v2:orderbook:features:BTCUSDT": "{}",
        "v2:market:trade_tape_features:BTCUSDT": "{}",
        "v2:coinank:funding:BTCUSDT": "{}",
        "v2:liquidations:levels:BTCUSDT:1m": "{}",
        "v2:provider:coinglass:health": json.dumps({"status": "ACTIVE", "generated_utc": _now_iso()}),
        "v2:provider:portfolio_publisher:health": json.dumps({"status": "ACTIVE", "generated_utc": _now_iso()}),
    }


def test_ingestor_rollup_healthy_when_core_streams_present_and_providers_fresh() -> None:
    out = _ingestors_payload(_FakeRedis(_healthy_data()))
    assert out["overall_status"] == "HEALTHY"
    assert out["all_core_streams_present"] is True
    assert out["stream_present"]["candles"] is True
    assert out["stream_present"]["ta_full"] is True
    assert out["stream_present"]["liquidation_levels"] is True
    assert out["active_provider_count"] == 2
    assert out["stale_provider_count"] == 0


def test_ingestor_rollup_flags_stale_provider() -> None:
    data = _healthy_data()
    data["v2:provider:coinglass:health"] = json.dumps(
        {"status": "ACTIVE", "generated_utc": "2020-01-01T00:00:00Z"}  # very stale
    )
    out = _ingestors_payload(_FakeRedis(data))
    assert out["overall_status"] == "SOME_PROVIDERS_STALE"
    assert "coinglass" in out["stale_providers"]


def test_ingestor_rollup_degraded_when_core_stream_missing() -> None:
    data = _healthy_data()
    del data["v2:features:ta_full:BTCUSDT:5m"]  # remove a core stream
    out = _ingestors_payload(_FakeRedis(data))
    assert out["overall_status"] == "DEGRADED_MISSING_CORE_STREAM"
    assert out["stream_present"]["ta_full"] is False


def test_system_health_includes_ingestor_rollup() -> None:
    out = _system_health_payload(_FakeRedis(_healthy_data()))
    assert "ingestors" in out
    assert out["ingestors"]["overall_status"] == "HEALTHY"


def test_ingestor_rollup_safe_without_redis() -> None:
    out = _ingestors_payload(None)
    assert out["all_core_streams_present"] is False
    assert out["overall_status"] == "DEGRADED_MISSING_CORE_STREAM"
