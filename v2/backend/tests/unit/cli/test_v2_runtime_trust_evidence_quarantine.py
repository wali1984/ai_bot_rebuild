from __future__ import annotations

import json

from v2.backend.app.cli.v2_runtime_trust_evidence_quarantine import (
    quarantine_runtime_evidence,
)


class _FakeRedis:
    def __init__(self, store: dict[str, str]) -> None:
        self.store = dict(store)
        self.expired: dict[str, int] = {}

    def scan_iter(self, match: str | None = None, count: int = 250):  # noqa: ARG002
        keys = list(self.store.keys())
        if match is None:
            for key in keys:
                yield key
            return
        prefix = match.rstrip("*")
        for key in keys:
            if match.endswith("*"):
                if key.startswith(prefix):
                    yield key
            elif key == match:
                yield key

    def type(self, key: str) -> str:
        return "string" if key in self.store else "none"

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:  # noqa: ARG002
        self.store[key] = value
        return True

    def expire(self, key: str, ttl: int) -> bool:
        self.expired[key] = ttl
        return True


def test_quarantine_expires_malformed_kucoin_rows_and_missing_microfeatures() -> None:
    client = _FakeRedis(
        {
            "v2:market:kucoin:kline:BTCUSDT:1m": json.dumps(
                {"open": 10.0, "high": 8.0, "low": 9.0, "close": 7.0}
            ),
            "v2:features:microfeat:BTCUSDT:1m": json.dumps(
                {"symbol": "BTCUSDT", "timeframe": "1m", "available_at": None, "feature_cutoff": None}
            ),
            "v2:live_gate:state": json.dumps({"live_gate": "blocked_human_only"}),
        }
    )

    result = quarantine_runtime_evidence(
        client=client,
        expire_seconds=30,
        quarantine_ttl_seconds=3600,
        dry_run=False,
    )

    assert result["quarantined_count"] == 2
    assert client.expired["v2:market:kucoin:kline:BTCUSDT:1m"] == 30
    assert client.expired["v2:features:microfeat:BTCUSDT:1m"] == 30
    assert "v2:live_gate:state" not in client.expired
    assert any(key.startswith("v2:quarantine:runtime_trust:") for key in client.store)


def test_quarantine_expires_snapshotless_prediction_records() -> None:
    client = _FakeRedis(
        {
            "v2:prediction:BTCUSDT:1m": json.dumps(
                {
                    "prediction_id": "pred-1",
                    "symbol": "BTCUSDT",
                    "selected_action": "long",
                    "paper_fill_allowed": True,
                    "feature_cutoff": "2026-06-11T00:01:00Z",
                    "mtf_snapshot_id": None,
                    "mtf_snapshot_valid": None,
                    "replay_snapshot_id": None,
                    "input_feature_hash": None,
                    "all_tf_candle_timestamps": [],
                }
            ),
            "v2:trainer:hybrid_cuda:signals:paper:BTCUSDT:1m": json.dumps(
                {
                    "prediction_id": "pred-2",
                    "symbol": "BTCUSDT",
                    "selected_action": "long",
                    "paper_fill_allowed": True,
                    "feature_cutoff": "2026-06-11T00:01:00Z",
                    "mtf_snapshot_id": None,
                    "mtf_snapshot_valid": None,
                    "replay_snapshot_id": None,
                    "input_feature_hash": None,
                    "all_tf_candle_timestamps": [],
                }
            ),
            "v2:trainer:hybrid_cuda:paper_signal_lineage_preview": json.dumps(
                {
                    "prediction_id": "pred-3",
                    "symbol": "BTCUSDT",
                    "selected_action": "long",
                    "paper_fill_allowed": True,
                    "feature_cutoff": "2026-06-11T00:01:00Z",
                    "mtf_snapshot_id": None,
                    "mtf_snapshot_valid": None,
                    "replay_snapshot_id": None,
                    "input_feature_hash": None,
                    "all_tf_candle_timestamps": [],
                }
            )
        }
    )

    result = quarantine_runtime_evidence(
        client=client,
        expire_seconds=15,
        quarantine_ttl_seconds=3600,
        dry_run=False,
    )

    assert result["quarantined_count"] == 3
    assert client.expired["v2:prediction:BTCUSDT:1m"] == 15
    assert client.expired["v2:trainer:hybrid_cuda:signals:paper:BTCUSDT:1m"] == 15
    assert client.expired["v2:trainer:hybrid_cuda:paper_signal_lineage_preview"] == 15
