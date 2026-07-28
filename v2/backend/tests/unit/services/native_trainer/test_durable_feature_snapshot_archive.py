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
    verify_record,
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


def test_immutable_v1_record_preserves_distinct_source_and_producer_clocks(
    tmp_path: Path,
) -> None:
    """Legacy v1 blobs use available_at for source availability and
    created_at for producer/archive generation; they must not be rewritten or
    rejected merely because production happened after source availability.
    """

    record = _record("legacy-v1-distinct-clocks")
    record["created_at"] = "2026-06-22T00:00:45Z"
    record["content_sha256"] = content_sha256(record)

    assert record["schema_version"] == "durable_feature_snapshot_archive_record_v1"
    assert record["available_at"] == AVAILABLE_AT
    assert record["created_at"] == "2026-06-22T00:00:45Z"
    assert record["available_at"] < record["created_at"] < record["decision_time"]
    assert verify_record(record) == []

    written = append_snapshot(record, root=tmp_path)
    loaded = load_snapshot(record["snapshot_id"], root=tmp_path)

    assert loaded == record
    assert written.content_sha256 == record["content_sha256"]


def test_prediction_payload_archive_record_does_not_collapse_source_availability(
) -> None:
    payload = {
        "feature_snapshot_id": "snapshot-distinct-clocks",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_cutoff": FEATURE_CUTOFF,
        "available_at": AVAILABLE_AT,
        "generated_utc": "2026-06-22T00:00:45Z",
        "decision_time": DECISION_TIME,
        "mtf_snapshot_id": "mtf-distinct-clocks",
        "replay_snapshot": {
            "feature_snapshot": {
                "features": {"close": 101.0},
                "available_at": AVAILABLE_AT,
            },
        },
    }

    record = build_archive_record_from_prediction_payload(payload)

    assert record is not None
    assert record["available_at"] == AVAILABLE_AT
    assert record["created_at"] == "2026-06-22T00:00:45Z"
    assert record["decision_time"] == DECISION_TIME
    assert record["available_at"] < record["created_at"] < record["decision_time"]
    assert verify_record(record) == []


def test_prediction_payload_archive_record_publishes_explicit_clock_contract() -> None:
    payload = {
        "feature_snapshot_id": "snapshot-explicit-clock-contract",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_cutoff": FEATURE_CUTOFF,
        "available_at": AVAILABLE_AT,
        "generated_utc": "2026-06-22T00:00:45Z",
        "decision_time": DECISION_TIME,
        "mtf_snapshot_id": "mtf-explicit-clocks",
        "replay_snapshot": {
            "feature_snapshot": {
                "features": {"close": 101.0},
                "generated_at": "2026-06-22T00:00:20Z",
                "available_at": AVAILABLE_AT,
            },
        },
    }

    record = build_archive_record_from_prediction_payload(payload)

    assert record is not None
    assert record["clock_contract_version"] == (
        "durable_feature_snapshot_clock_contract_v2"
    )
    assert record["source_generated_at"] == "2026-06-22T00:00:20Z"
    assert record["source_available_at"] == AVAILABLE_AT
    assert record["producer_generated_at"] == "2026-06-22T00:00:45Z"
    assert record["record_available_at"] == "2026-06-22T00:00:45Z"
    assert record["available_at"] == record["source_available_at"]
    assert record["created_at"] == record["producer_generated_at"]
    assert verify_record(record) == []


def test_explicit_clock_enrichment_does_not_rewrite_immutable_v1_blob(
    tmp_path: Path,
) -> None:
    legacy = _record("immutable-v1-enrichment")
    legacy["created_at"] = "2026-06-22T00:00:45Z"
    legacy["content_sha256"] = content_sha256(legacy)
    first = append_snapshot(legacy, root=tmp_path)

    enriched = dict(legacy)
    enriched.update(
        {
            "clock_contract_version": "durable_feature_snapshot_clock_contract_v2",
            "source_generated_at": "2026-06-22T00:00:20Z",
            "source_available_at": AVAILABLE_AT,
            "producer_generated_at": "2026-06-22T00:00:45Z",
            "record_available_at": "2026-06-22T00:00:45Z",
        }
    )
    enriched["content_sha256"] = content_sha256(enriched)

    second = append_snapshot(enriched, root=tmp_path)
    loaded = load_snapshot(legacy["snapshot_id"], root=tmp_path)

    assert second.already_present is True
    assert second.content_sha256 == legacy["content_sha256"]
    assert second.blob_path == first.blob_path
    assert loaded == legacy
    assert "clock_contract_version" not in loaded

    conflicting = dict(enriched)
    conflicting["features"] = {**conflicting["features"], "close": 999.0}
    conflicting["content_sha256"] = content_sha256(conflicting)
    with pytest.raises(SnapshotArchiveError, match="SNAPSHOT_ID_CONTENT_HASH_CHANGED"):
        append_snapshot(conflicting, root=tmp_path)


def test_clock_contract_version_without_explicit_clocks_fails_closed() -> None:
    record = _record("clock-version-only")
    record["clock_contract_version"] = "durable_feature_snapshot_clock_contract_v2"
    record["content_sha256"] = content_sha256(record)

    assert "CLOCK_CONTRACT_FIELDS_INCOMPLETE" in verify_record(record)


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
