from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
    append_snapshot,
    build_archive_record,
    build_archive_record_from_prediction_payload,
    build_reference_retention_status,
    content_sha256,
    iter_index_records,
    load_snapshot,
    rollover_archive,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)


FEATURE_CUTOFF = "2026-06-22T00:00:00Z"
AVAILABLE_AT = "2026-06-22T00:00:30Z"
DECISION_TIME = "2026-06-22T00:01:00Z"


def _record(snapshot_id: str = "snapshot-1", *, payload: str = "small") -> dict[str, object]:
    features = {
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "last_price": 100.5,
        "payload": payload,
    }
    return build_archive_record(
        snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        timeframe="1m",
        feature_cutoff=FEATURE_CUTOFF,
        decision_time=DECISION_TIME,
        available_at=AVAILABLE_AT,
        mtf_snapshot_id="mtf-1",
        features=features,
        missing_mask={name: False for name in features},
        stale_mask={name: False for name in features},
        source_availability={"ohlcv": True},
        source_hashes={"feature_payload_hash": "hash-1"},
        created_at=AVAILABLE_AT,
        extra={"candle_closed_confirmed": True},
    )


def test_snapshot_archive_roundtrip(tmp_path: Path) -> None:
    record = _record()
    result = append_snapshot(record, root=tmp_path)

    loaded = load_snapshot("snapshot-1", root=tmp_path)

    assert result.already_present is False
    assert loaded is not None
    assert loaded["snapshot_id"] == "snapshot-1"
    assert loaded["content_sha256"] == record["content_sha256"]


def test_snapshot_content_hash_verification(tmp_path: Path) -> None:
    result = append_snapshot(_record(), root=tmp_path)
    payload = json.loads(result.blob_path.read_text(encoding="utf-8"))
    payload["features"]["close"] = 999.0
    result.blob_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SnapshotArchiveError, match="CONTENT_SHA256_MISMATCH"):
        load_snapshot("snapshot-1", root=tmp_path)


def test_referenced_snapshot_not_deleted(tmp_path: Path) -> None:
    append_snapshot(_record("pinned", payload="x" * 2048), root=tmp_path)
    append_snapshot(_record("unpinned", payload="y" * 2048), root=tmp_path)

    rollover_archive(root=tmp_path, max_bytes=1, referenced_snapshot_ids=["pinned"])
    retention = build_reference_retention_status(root=tmp_path, referenced_snapshot_ids=["pinned"])

    assert load_snapshot("pinned", root=tmp_path) is not None
    assert retention["referenced_snapshot_not_deleted"] is True


def test_unreferenced_snapshot_rollover(tmp_path: Path) -> None:
    append_snapshot(_record("old", payload="x" * 2048), root=tmp_path)
    append_snapshot(_record("keep", payload="y" * 2048), root=tmp_path)

    status = rollover_archive(root=tmp_path, max_bytes=1, referenced_snapshot_ids=["keep"])

    assert "old" in status["removed_snapshot_ids"]
    assert load_snapshot("keep", root=tmp_path) is not None
    assert load_snapshot("old", root=tmp_path, verify=False) is None


def test_index_iteration_prefers_newest_snapshot(tmp_path: Path) -> None:
    older = append_snapshot(_record("older"), root=tmp_path)
    newer = append_snapshot(_record("newer"), root=tmp_path)
    os.utime(older.index_path, (2, 2))
    os.utime(newer.index_path, (1, 1))

    records = list(iter_index_records(root=tmp_path, newest_first=True, limit=1))

    assert [record["snapshot_id"] for record in records] == ["newer"]


def test_feedback_can_resolve_archived_snapshot(tmp_path: Path) -> None:
    append_snapshot(_record("feedback-snapshot"), root=tmp_path)
    loader = V2HybridTrainerDataLoader(trusted_replay_archive_root=tmp_path)

    snapshot, source = loader._closed_trade_feature_snapshot(  # noqa: SLF001
        row={},
        feature_snapshot_id="feedback-snapshot",
    )

    assert snapshot is not None
    assert snapshot["snapshot_id"] == "feedback-snapshot"
    assert source == "durable_feature_snapshot_archive:feedback-snapshot"


def test_prediction_payload_archive_record_accepts_flattened_replay_snapshot() -> None:
    payload = {
        "prediction_id": "pred-1",
        "signal_id": "sig-1",
        "decision_id": "decision-1",
        "feature_snapshot_id": "snapshot-flat",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_cutoff": FEATURE_CUTOFF,
        "decision_time": DECISION_TIME,
        "feature_decision_time": DECISION_TIME,
        "available_at": AVAILABLE_AT,
        "mtf_snapshot_id": "mtf-1",
        "generated_utc": AVAILABLE_AT,
        "model_version": "v2_native_hybrid",
        "checkpoint_id": "ckpt-1",
        "feature_names": ["open", "close", "open_interest"],
        "missing_feature_names": [],
        "stale_feature_names": [],
        "source_availability_vector": [1.0, 1.0, 1.0],
        "source_hashes": {"feature_vector_hash": "hash-1"},
        "replay_snapshot": {
            "feature_snapshot": {
                "feature_snapshot_id": "snapshot-flat",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "feature_cutoff": FEATURE_CUTOFF,
                "available_at": AVAILABLE_AT,
                "candle_closed_confirmed": True,
                "features": {
                    "open": 100.0,
                    "close": 101.0,
                    "open_interest": 123.0,
                },
            },
        },
    }

    record = build_archive_record_from_prediction_payload(payload)

    assert record is not None
    assert record["snapshot_id"] == "snapshot-flat"
    assert record["features"]["open_interest"] == 123.0
    assert record["feature_cutoff"] == FEATURE_CUTOFF
    assert record["decision_time"] == DECISION_TIME
    assert record["available_at"] == AVAILABLE_AT
    assert record["candle_closed_confirmed"] is True
    assert content_sha256(record) == record["content_sha256"]


def test_prediction_payload_archive_record_never_derives_producer_admission() -> None:
    payload = {
        "feature_snapshot_id": "snapshot-no-claim",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_cutoff": FEATURE_CUTOFF,
        "decision_time": DECISION_TIME,
        "available_at": AVAILABLE_AT,
        "mtf_snapshot_id": "mtf-1",
        "replay_snapshot": {
            "feature_snapshot": {
                "features": {"close": 101.0},
                "candle_closed_confirmed": True,
                "latest_unclosed_kline_excluded": True,
            },
        },
    }

    record = build_archive_record_from_prediction_payload(payload)

    assert record is not None
    assert "trainer_consumable" not in record


@pytest.mark.parametrize("claim", [True, False])
def test_prediction_payload_archive_record_preserves_explicit_producer_admission(
    claim: bool,
) -> None:
    payload = {
        "feature_snapshot_id": f"snapshot-claim-{claim}",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_cutoff": FEATURE_CUTOFF,
        "decision_time": DECISION_TIME,
        "available_at": AVAILABLE_AT,
        "mtf_snapshot_id": "mtf-1",
        "trainer_consumable": claim,
        "replay_snapshot": {"feature_snapshot": {"features": {"close": 101.0}}},
    }

    record = build_archive_record_from_prediction_payload(payload)

    assert record is not None
    assert record["trainer_consumable"] is claim
