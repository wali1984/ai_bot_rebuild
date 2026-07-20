from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from v2.backend.app.cli import v2_ingestors_status_publisher as publisher


def test_default_output_and_evidence_paths_are_repo_rooted(
    monkeypatch, tmp_path: Path
) -> None:
    """The systemd unit may start outside the repository."""

    monkeypatch.chdir(tmp_path)
    expected_root = Path(publisher.__file__).resolve().parents[4]
    expected_public_root = expected_root / "v2/frontend/public"

    assert publisher.REPO_ROOT == expected_root
    assert publisher.PUBLIC_ROOT == expected_public_root
    assert publisher.DEFAULT_PAYLOAD_PATH == (
        expected_public_root
        / "operator_runtime/v2_ingestors_status/latest/v2_ingestors_status.json"
    )
    assert all(path.is_absolute() for path in publisher.PUBLIC_STATUS_PATHS.values())
    assert all(
        path.is_relative_to(expected_public_root)
        for path in publisher.PUBLIC_STATUS_PATHS.values()
    )


class FakeRedis:
    def __init__(self, store: dict[str, Any]) -> None:
        self.store = store

    def get(self, key: str) -> str | None:
        value = self.store.get(key)
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def ttl(self, key: str) -> int:
        return 300 if key in self.store else -2

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    def keys(self, _pattern: str) -> list[str]:
        return []


def test_ingestors_status_merges_public_provider_payload_counts(monkeypatch) -> None:
    redis = FakeRedis(
        {
            "v2:market:kucoin:heartbeat": {"worker_id": "v2_kucoin_ingestor", "generated_utc": "2026-06-05T01:00:00Z"},
            "v2:market:coinapi:ohlcv:heartbeat": {"worker_id": "v2_coinapi_rest_ingestor"},
            "v2:market:coinapi:rest:heartbeat": {"worker_id": "v2_coinapi_rest_ingestor"},
            "v2:market:coinapi:wsds:heartbeat": {"worker_id": "v2_coinapi_wsds_loop"},
            "v2:coinank:global:last_update": {"worker_id": "v2_coinank_and_liquidation_bridge"},
        }
    )
    statuses = {
        "kucoin": {
            "classification": "NATIVE_V2_PUBLIC_REST_OK",
            "generated_utc": "2026-06-05T01:01:00Z",
            "symbols_v2": ["BTCUSDT", "ETHUSDT"],
            "v2_redis_keys_written_count": 8,
        },
        "coinapi_rest": {
            "classification": "V2_COINAPI_REST_OK",
            "generated_utc": "2026-06-05T01:02:00Z",
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "fetch": {"symbols_fetched": 2, "symbols_requested": 2},
            "v2_redis_keys_written_count": 9,
        },
        "coinapi_wsds": {
            "classification": "V2_COINAPI_WSDS_CONNECTED",
            "generated_utc": "2026-06-05T01:03:00Z",
            "symbols_count": 2,
            "stats": {"snapshots_written": 10, "microfeatures_written": 30},
        },
        "coinank": {
            "generated_utc": "2026-06-05T01:04:00Z",
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "v2_redis_feature_input": {"symbols_with_any_input": 2},
            "v2_redis_global_keys_written_count": 11,
            "global_aggregate_result": {"n_symbols_observed": 2, "total_oi": 1000.0},
        },
    }
    monkeypatch.setattr(publisher, "_connect_redis", lambda: redis)
    monkeypatch.setattr(publisher, "_read_public_status", lambda name: statuses.get(name))

    payload = publisher.run_once()
    entries = {entry["name"]: entry for entry in payload["ingestors"]}

    assert entries["KuCoin Native Public REST"]["symbols_count"] == 2
    assert entries["KuCoin Native Public REST"]["keys_written_count"] == 8
    assert entries["CoinAPI Native REST Orderbook"]["symbols_count"] == 2
    assert entries["CoinAPI Native REST Orderbook"]["keys_written_count"] == 9
    assert entries["CoinAPI Native WSDS"]["symbols_count"] == 2
    assert entries["CoinAPI Native WSDS"]["keys_written_count"] == 30
    assert entries["CoinAnk Direct Global Aggregator"]["symbols_count"] == 2
    assert entries["CoinAnk Direct Global Aggregator"]["keys_written_count"] == 11
    assert entries["CoinAnk Direct Global Aggregator"]["status"] == "V2_COINANK_GLOBAL_AGGREGATE_OK"
    assert payload["live_gate"] == "enabled_operator_approved"
    assert payload["live_symbols"] == []
