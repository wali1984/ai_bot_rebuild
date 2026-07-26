from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from v2.backend.app.cli import v2_paper_provisional_prediction_publisher as publisher


def test_current_feature_snapshot_binds_postcommit_availability_receipt() -> None:
    snapshot = {
        "feature_snapshot_id": "snapshot-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "feature_cutoff": "2026-07-26T19:39:59.999Z",
        "features": {"close": 1.0},
    }
    raw = json.dumps(snapshot, separators=(",", ":"))
    receipt = {
        "schema_version": "native_feature_publication_postcommit_receipt_v1",
        "publication_binding_authenticated": True,
        "publication_binding_complete": True,
        "temporal_invariants_valid": True,
        "feature_snapshot_id": "snapshot-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "feature_cutoff": snapshot["feature_cutoff"],
        "snapshot_archive_key": "v2:features:snapshot:snapshot-1",
        "snapshot_payload_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "receipt_sha256": "a" * 64,
        "available_at": "2026-07-26T19:40:00.123456Z",
    }

    class Client:
        def get(self, key: str) -> str | None:
            if key == "v2:features:latest:BTCUSDT:5m":
                return raw
            if key == "v2:features:publication_receipt:snapshot-1":
                return json.dumps(receipt)
            return None

    result = publisher.read_current_feature_snapshot(Client(), "BTCUSDT", "5m")

    assert result is not None
    assert result["record_available_at"] == receipt["available_at"]
    assert result["feature_publication_receipt_verified"] is True


def test_current_feature_snapshot_rejects_receipt_payload_hash_mismatch() -> None:
    snapshot = {
        "feature_snapshot_id": "snapshot-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "feature_cutoff": "2026-07-26T19:39:59.999Z",
        "features": {"close": 1.0},
    }
    raw = json.dumps(snapshot)
    receipt = {
        "schema_version": "native_feature_publication_postcommit_receipt_v1",
        "publication_binding_authenticated": True,
        "publication_binding_complete": True,
        "temporal_invariants_valid": True,
        "feature_snapshot_id": "snapshot-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "feature_cutoff": snapshot["feature_cutoff"],
        "snapshot_archive_key": "v2:features:snapshot:snapshot-1",
        "snapshot_payload_sha256": "b" * 64,
        "receipt_sha256": "a" * 64,
        "available_at": "2026-07-26T19:40:00.123456Z",
    }

    class Client:
        def get(self, key: str) -> str | None:
            if key == "v2:features:latest:BTCUSDT:5m":
                return raw
            if key == "v2:features:publication_receipt:snapshot-1":
                return json.dumps(receipt)
            return None

    assert publisher.read_current_feature_snapshot(Client(), "BTCUSDT", "5m") is None


def test_build_trust_row_transports_mtf_clocks_as_strict_utc() -> None:
    tensor = SimpleNamespace(
        tensor_id="tensor-1",
        feature_snapshot_id="snapshot-1",
        feature_names=("f0",),
        values=(1.0,),
    )
    snapshot = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "feature_cutoff": "2026-07-26T19:39:59.999Z",
        "available_at": "2026-07-26T19:40:00.100Z",
        "latest_unclosed_kline_excluded": True,
        "latest_unclosed_exclusion_method": "CLOSED_ONLY",
        "latest_unclosed_exclusion_decision_time_ms": 1785094801000,
        "latest_closed_kline_close_time_ms": 1785094799999,
    }
    mtf = {
        "feature_cutoff": 1785094799999,
        "all_tf_candle_timestamps": [1785094799999, 1785094499999],
        "all_source_event_times": [1785094800001, 1785094500001],
        "decision_id": "decision-1",
        "mtf_snapshot_id": "mtf-1",
        "valid": True,
        "reject_reasons": [],
    }
    candle = {
        "candle_open_time": 1785094500000,
        "candle_close_time": 1785094799999,
        "event_time": 1785094800001,
        "available_at": 1785094800100,
    }

    row = publisher.build_trust_row(
        tensor=tensor,
        snapshot=snapshot,
        mtf=mtf,
        candle=candle,
        decision_time_iso="2026-07-26T19:40:01.000000Z",
        generated_at="2026-07-26T19:40:01.000100Z",
    )

    assert row["all_tf_candle_timestamps"] == [
        "2026-07-26T19:39:59.999Z",
        "2026-07-26T19:34:59.999Z",
    ]
    assert row["all_source_event_times"] == [
        "2026-07-26T19:40:00.001Z",
        "2026-07-26T19:35:00.001Z",
    ]


def test_publish_one_bounds_mtf_selection_to_feature_cutoff(monkeypatch) -> None:
    cutoff_ms = 1785094799999
    snapshot = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "feature_cutoff": "2026-07-26T19:39:59.999Z",
        "latest_unclosed_kline_excluded": True,
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(publisher, "read_current_feature_snapshot", lambda *_args: snapshot)
    monkeypatch.setattr(
        publisher,
        "build_cost_provenance",
        lambda *_args: (10.0, {"valid": True}, {"round_trip_cost_bps": 10.0}),
    )
    monkeypatch.setattr(publisher, "read_json_key", lambda *_args: {})

    def _mtf(**kwargs):
        captured.update(kwargs)
        return {"valid": False, "reject_reasons": ["fixture_stop"]}

    monkeypatch.setattr(publisher, "build_multi_timeframe_decision_snapshot", _mtf)
    result = publisher.publish_one(
        client=object(),
        io=object(),
        publisher=object(),
        ckpt=SimpleNamespace(checkpoint_id="checkpoint-1"),
        cohort={"checkpoint_id": "checkpoint-1"},
        symbol="BTCUSDT",
        timeframe="5m",
    )

    assert result["status"] == "MTF_SNAPSHOT_INVALID"
    assert captured["decision_time"] == cutoff_ms
