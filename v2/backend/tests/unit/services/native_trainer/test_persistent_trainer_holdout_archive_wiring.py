from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    CanonicalCandle,
)
from v2.backend.app.services.native_trainer import (
    persistent_cuda_trainer_runtime as runtime,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    default_archive_path as default_label_archive_path,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    PROVENANCE_CANONICAL_V3,
    DurableFeatureSnapshotLedger,
    build_feature_snapshot_record,
    build_source_read_receipt,
    default_ledger_path,
    feature_requirement_classes_for_names,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_state import (
    training_partition_digest,
)

BASE = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)
DECISION = BASE + timedelta(microseconds=1)
HOLDOUT_END = DECISION + timedelta(microseconds=50)
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
}


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _feature_record(
    snapshot_id: str = "holdout-snapshot-1",
    *,
    decision_time: datetime = DECISION,
    unfinished_timeframe: str | None = None,
    non_interval_timeframe: str | None = None,
    inexact_interval_timeframe: str | None = None,
    optional_event_missing: bool = False,
) -> dict[str, object]:
    receipts: list[dict[str, object]] = []
    finality_by_timeframe: dict[str, dict[str, object]] = {}
    for timeframe in runtime.DEFAULT_TIMEFRAMES:
        source_label = f"canonical_ohlcv:{timeframe}"
        open_time = BASE - timedelta(
            seconds=TIMEFRAME_SECONDS[timeframe]
        ) + timedelta(milliseconds=1)
        if timeframe == inexact_interval_timeframe:
            open_time += timedelta(microseconds=1)
        payload_sha256 = hashlib.sha256(
            f"{snapshot_id}:{timeframe}:closed-candle".encode()
        ).hexdigest()
        receipt = build_source_read_receipt(
            source_label=source_label,
            payload_type="canonical_candle",
            payload_sha256=payload_sha256,
            payload_byte_count=128,
            event_time=_iso(BASE),
            available_at=_iso(BASE),
            consumer_observed_at=_iso(BASE),
            feature_cutoff=_iso(BASE),
            read_locator_type="IN_MEMORY_IMMUTABLE_OBJECT",
            read_locator=f"unit-fixture:{snapshot_id}:{timeframe}",
            read_locator_version="unit_v1",
            finality_type=(
                "IMMUTABLE_EVENT"
                if timeframe == non_interval_timeframe
                else "CLOSED_INTERVAL"
            ),
            finality_cutoff=_iso(BASE),
            finality_verified_at=_iso(BASE),
            finality_verifier="unit_test",
        )
        receipts.append(receipt)
        finality = receipt["finality_evidence"]
        assert isinstance(finality, dict)
        finality_by_timeframe[timeframe] = {
            "timeframe": timeframe,
            "source_label": source_label,
            "source_read_receipt_sha256": receipt["receipt_sha256"],
            "candle_id": f"BTCUSDT:{timeframe}:{_iso(open_time)}",
            "candle_open_time": _iso(open_time),
            "candle_close_time": _iso(BASE),
            "event_time": receipt["event_time"],
            "available_at": receipt["available_at"],
            "consumer_observed_at": receipt["consumer_observed_at"],
            "feature_cutoff": receipt["feature_cutoff"],
            "finality_cutoff": finality["finality_cutoff"],
            "finality_verified_at": finality["finality_verified_at"],
            "candle_closed_confirmed": timeframe != unfinished_timeframe,
        }

    features = {
        "close": 100.0,
        "fee_bps": 1.0,
        "actual_observed_spread_entry_bps": 0.5,
        "expected_slippage_bps": 0.25,
        "expected_funding_bps": 0.25,
        "closed_5m_source_value": 100.0,
        "closed_15m_source_value": 100.0,
        "closed_1h_source_value": 100.0,
        "closed_4h_source_value": 100.0,
    }
    if optional_event_missing:
        missing_payload = json.dumps(
            {
                "reason": "NO_OPEN_PAPER_POSITION",
                "symbol": "BTCUSDT",
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        receipts.append(
            build_source_read_receipt(
                source_label="v2:paper:positions",
                payload_type="declared_typed_missing_paper_position",
                payload_sha256=hashlib.sha256(missing_payload).hexdigest(),
                payload_byte_count=len(missing_payload),
                event_time=_iso(BASE),
                available_at=_iso(BASE),
                consumer_observed_at=_iso(BASE),
                feature_cutoff=_iso(BASE),
                read_locator_type="IN_MEMORY_IMMUTABLE_OBJECT",
                read_locator=(
                    f"unit-fixture:{snapshot_id}:paper-position-typed-missing"
                ),
                read_locator_version="unit_declared_typed_missing_v1",
                finality_type="VERSIONED_SNAPSHOT",
                finality_cutoff=_iso(BASE),
                finality_verified_at=_iso(BASE),
                finality_verifier="unit_test",
            )
        )
        features["paper_position_present"] = 0.0
    feature_names = list(features)
    receipt_by_label = {
        str(receipt["source_label"]): receipt for receipt in receipts
    }
    source_labels = [
        "canonical_ohlcv:1m",
        "canonical_ohlcv:1m",
        "canonical_ohlcv:1m",
        "canonical_ohlcv:1m",
        "canonical_ohlcv:1m",
        "canonical_ohlcv:5m",
        "canonical_ohlcv:15m",
        "canonical_ohlcv:1h",
        "canonical_ohlcv:4h",
    ]
    if optional_event_missing:
        source_labels.append("v2:paper:positions")
    missing_mask = [
        int(name == "paper_position_present" and optional_event_missing)
        for name in feature_names
    ]
    source_availability_mask = [1 - flag for flag in missing_mask]
    return build_feature_snapshot_record(
        provenance_classification=PROVENANCE_CANONICAL_V3,
        legacy_v1_snapshot_id=None,
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id=f"feature-snapshot:{snapshot_id}",
        tensor_decision_time=_iso(decision_time),
        temporal_rejection_reasons=[],
        ordered_feature_names=feature_names,
        feature_values=list(features.values()),
        missing_mask=missing_mask,
        stale_mask=[0] * len(feature_names),
        source_availability_mask=source_availability_mask,
        ordered_feature_source_labels=source_labels,
        feature_source_receipt_sha256s=[
            str(receipt_by_label[source_label]["receipt_sha256"])
            for source_label in source_labels
        ],
        source_read_receipts=receipts,
        feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
        ordered_feature_requirement_classes=list(
            feature_requirement_classes_for_names(feature_names)
        ),
        original_tensor_id=f"tensor:{snapshot_id}",
        source_lineage_material={
            "lineage_schema": "authenticated_holdout_fixture_v1",
            "mtf_snapshot_id": f"mtf:{snapshot_id}",
            "timeframe_finality": finality_by_timeframe,
        },
        feature_cutoff=_iso(BASE),
        masa_feature_cutoff=_iso(BASE),
        ppo_feature_cutoff=_iso(BASE),
        ppo_decision_time=_iso(decision_time),
        generated_at=_iso(BASE),
    )


def _candles(
    *,
    omit_slot: int | None = None,
    future_available_slot: int | None = None,
    future_available_at: datetime | None = None,
    start_slot: int = 0,
    count: int = 49,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for slot in range(start_slot, start_slot + count):
        if slot == omit_slot:
            continue
        open_time = BASE + timedelta(minutes=5 * slot)
        close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
        available_at = close_time + timedelta(milliseconds=1)
        if slot == future_available_slot:
            assert future_available_at is not None
            available_at = future_available_at
        close = 100.0 + slot * 0.1
        rows.append(
            CanonicalCandle(
                symbol="BTCUSDT",
                exchange="binance",
                timeframe="5m",
                candle_open_time=int(open_time.timestamp() * 1000),
                candle_close_time=int(close_time.timestamp() * 1000),
                event_time=int(close_time.timestamp() * 1000),
                ingested_at=int(available_at.timestamp() * 1000),
                available_at=int(available_at.timestamp() * 1000),
                is_closed=True,
                source="binance_wss",
                source_sequence_id=f"unit:{slot}",
                raw_payload_hash=hashlib.sha256(
                    f"BTCUSDT:{slot}".encode()
                ).hexdigest(),
                ohlcv={
                    "open": 100.0,
                    "high": max(101.0, close),
                    "low": 99.0,
                    "close": close,
                    "volume": 1_000.0 + slot,
                },
                is_backfilled=False,
                feature_eligible=True,
            ).to_dict()
        )
    return rows


def _append_sources(
    repo_root: Path,
    *,
    records: list[dict[str, object]] | None = None,
    candles: list[dict[str, object]] | None = None,
) -> tuple[DurableFeatureSnapshotLedger, DurableCanonical5mLabelArchive]:
    ledger = DurableFeatureSnapshotLedger(default_ledger_path(repo_root))
    ledger.append_snapshots(records or [_feature_record()])
    archive = DurableCanonical5mLabelArchive(default_label_archive_path(repo_root))
    archive.append_candles(_candles() if candles is None else candles)
    return ledger, archive


def _manifest(
    repo_root: Path,
    *,
    ledger: DurableFeatureSnapshotLedger,
    archive: DurableCanonical5mLabelArchive,
    observation: datetime,
    proof_scan_limit: int = 100,
) -> dict[str, object]:
    feature_integrity = ledger.verify_integrity_streaming()
    feature_high_water, feature_reasons = (
        runtime._feature_ledger_integrity_checkpoint(  # noqa: SLF001
            ledger=ledger,
            report=feature_integrity,
            observation_cutoff=observation,
            scan_limit=proof_scan_limit,
        )
    )
    assert feature_reasons == []
    assert feature_high_water is not None
    label_integrity = archive.verify_integrity()
    label_high_water, label_reasons = (
        runtime._label_archive_integrity_checkpoint(  # noqa: SLF001
            archive=archive,
            integrity=label_integrity,
            observation_cutoff=observation,
            scan_limit=proof_scan_limit,
        )
    )
    assert label_reasons == []
    assert label_high_water is not None
    items = ledger.query_fixed_cutoff(
        decision_time_cutoff=_iso(HOLDOUT_END),
        training_observed_at=_iso(observation),
        limit=proof_scan_limit,
    )
    holdout_identities = [
        runtime._holdout_feature_sample_identity(item)[1]  # noqa: SLF001
        for item in items
        if DECISION
        <= runtime.parse_runtime_time(
            item.record["frozen_envelope"]["ppo_decision_time"]
        )
        <= HOLDOUT_END
    ]
    empty_training_partition_digest = training_partition_digest([])
    payload: dict[str, object] = {
        "schema_version": runtime.HOLDOUT_MANIFEST_SCHEMA_VERSION,
        "generated_utc": _iso(observation),
        "split_method": "STRICT_TEMPORAL_ORDER_NO_RANDOM_ROW_SPLIT",
        "temporal_overlap": False,
        "training_window": {"rows": 0},
        "validation_window": {"rows": 0},
        "holdout_window": {
            "rows": len(holdout_identities),
            "start_decision_time": _iso(DECISION),
            "end_decision_time": _iso(HOLDOUT_END),
        },
        "feature_ledger_high_water": feature_high_water,
        "label_archive_high_water": label_high_water,
        "partition_evidence": {
            "schema_version": runtime.HOLDOUT_PARTITION_SCHEMA_VERSION,
            "identity_domain": runtime.HOLDOUT_SAMPLE_IDENTITY_DOMAIN,
            "training_partition_digest": empty_training_partition_digest,
            "training_sample_count": 0,
            "training_sample_identity_set_sha256": (
                runtime._sample_identity_set_sha256([])  # noqa: SLF001
            ),
            "holdout_sample_count": len(holdout_identities),
            "holdout_sample_identity_set_sha256": (
                runtime._sample_identity_set_sha256(  # noqa: SLF001
                    holdout_identities
                )
            ),
            "training_holdout_disjoint": True,
        },
    }
    path = repo_root / "trusted_replay_train_validation_holdout_manifest.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return {**payload, "manifest_path": str(path)}


def _scenario(
    repo_root: Path,
    *,
    records: list[dict[str, object]] | None = None,
    candles: list[dict[str, object]] | None = None,
    observation: datetime | None = None,
) -> tuple[
    dict[str, object],
    DurableFeatureSnapshotLedger,
    DurableCanonical5mLabelArchive,
]:
    ledger, archive = _append_sources(
        repo_root,
        records=records,
        candles=candles,
    )
    cutoff = observation or datetime.now(UTC)
    manifest = _manifest(
        repo_root,
        ledger=ledger,
        archive=archive,
        observation=cutoff,
    )
    return manifest, ledger, archive


def _evaluate(
    repo_root: Path,
    manifest: dict[str, object],
    *,
    scan_limit: int = 100,
    eval_limit: int = 8,
) -> dict[str, object]:
    return runtime._trusted_replay_holdout_examples(  # noqa: SLF001
        repo_root=repo_root,
        manifest=manifest,
        scan_limit=scan_limit,
        eval_limit=eval_limit,
    )


def test_authenticated_holdout_is_exact_deterministic_and_cursor_free(
    tmp_path: Path,
) -> None:
    manifest, _ledger, _archive = _scenario(tmp_path)
    cursor = tmp_path / "trusted_replay_cursor.json"
    cursor.write_text('{"manifest_offset":123}', encoding="utf-8")
    cursor_before = cursor.read_bytes()

    first = _evaluate(tmp_path, manifest)
    second = _evaluate(tmp_path, manifest)

    assert first["status"] == "VERIFIED_CURSOR_FREE_TRUSTED_REPLAY_HOLDOUT_EXAMPLES"
    assert len(first["examples"]) == 1
    example = first["examples"][0]
    assert example.decision_time == "2026-07-18T00:00:00.000001Z"
    assert example.trust_row["trusted_replay_label_policy_version"] == (
        runtime.TRUSTED_REPLAY_LABEL_POLICY_VERSION
    )
    assert example.trust_row["static_action_threshold_used"] is False
    assert example.trust_row["future_labels_not_in_feature_tensor"] is True
    assert first["archive_integrity_proof_current_at_completion"] is True
    assert first["feature_ledger_integrity_proof_current_at_completion"] is True
    assert first["holdout_manifest_current_at_completion"] is True
    assert first["legacy_v1_feature_snapshot_admitted"] is False
    assert first["mutable_redis_history_used_for_historical_labels"] is False
    assert first["network_label_fallback_used"] is False
    assert first["production_replay_cursor_read"] is False
    assert first["production_replay_cursor_written"] is False
    for field in (
        "selected_holdout_sample_order_sha256",
        "evaluated_example_order_sha256",
        "durable_label_path_identity_sha256",
        "holdout_sample_identity_hash",
    ):
        assert first[field] == second[field]
        assert len(str(first[field])) == 64
    assert cursor.read_bytes() == cursor_before


def test_receipt_bound_declared_optional_event_absence_remains_trainable(
    tmp_path: Path,
) -> None:
    manifest, _ledger, _archive = _scenario(
        tmp_path,
        records=[_feature_record(optional_event_missing=True)],
    )

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == (
        "VERIFIED_CURSOR_FREE_TRUSTED_REPLAY_HOLDOUT_EXAMPLES"
    )
    assert len(result["examples"]) == 1
    example = result["examples"][0]
    optional_index = example.tensor.feature_names.index(
        "paper_position_present"
    )
    assert example.tensor.values[optional_index] == 0.0
    assert example.tensor.missing_mask[optional_index] == 1
    assert example.tensor.stale_mask[optional_index] == 0
    assert example.tensor.source_availability[optional_index] == 0
    assert example.tensor.source_availability_vector[optional_index] == 0
    assert example.tensor.missing_feature_names == (
        "paper_position_present",
    )
    assert example.tensor.data_coverage_percent < 100.0
    assert example.trust_row["missing_feature_names"] == [
        "paper_position_present"
    ]
    assert example.trust_row["missing_feature_count"] == 1
    assert example.trust_row["stale_feature_names"] == []
    assert example.trust_row["stale_feature_count"] == 0


def test_holdout_consumer_rejects_attacker_reclassification_of_required_slot() -> None:
    record = _feature_record(optional_event_missing=True)
    envelope = record["frozen_envelope"]
    assert isinstance(envelope, dict)
    forged_abi = json.loads(json.dumps(envelope["feature_abi"]))
    close_index = envelope["ordered_feature_names"].index("close")
    forged_abi["ordered_feature_requirement_classes"][close_index] = (
        "OPTIONAL_EVENT_DEPENDENT"
    )

    contract, reasons = runtime._exact_feature_requirement_contract(  # noqa: SLF001
        ordered_feature_names=envelope["ordered_feature_names"],
        missing_mask=envelope["missing_mask"],
        stale_mask=envelope["stale_mask"],
        source_availability_mask=envelope["source_availability_mask"],
        feature_abi=forged_abi,
        feature_source_receipt_sha256s=envelope[
            "feature_source_receipt_sha256s"
        ],
    )

    assert contract is None
    assert "FEATURE_REQUIREMENT_CLASSES_POLICY_MISMATCH" in reasons


def test_holdout_rejects_label_path_gap(tmp_path: Path) -> None:
    manifest, _ledger, _archive = _scenario(
        tmp_path,
        candles=_candles(omit_slot=20),
    )

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == "BLOCKED_NO_USABLE_HOLDOUT_EXAMPLES"
    assert result["examples"] == []
    assert any(
        "GAP" in reason or "ROW_COUNT_MISMATCH" in reason
        for reason in result["rows_rejected_by_reason"]
    )


def test_holdout_rejects_future_available_label(tmp_path: Path) -> None:
    future_available_at = datetime.now(UTC) + timedelta(hours=1)
    manifest, _ledger, _archive = _scenario(
        tmp_path,
        candles=_candles(
            future_available_slot=48,
            future_available_at=future_available_at,
        ),
    )

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == "BLOCKED_NO_USABLE_HOLDOUT_EXAMPLES"
    assert result["examples"] == []
    assert result["rows_rejected_by_reason"]


def test_holdout_rejects_future_manifest_observation_clock(
    tmp_path: Path,
) -> None:
    manifest, _ledger, _archive = _scenario(
        tmp_path,
        observation=datetime.now(UTC) + timedelta(hours=1),
    )

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == "BLOCKED_HOLDOUT_OBSERVATION_CUTOFF_INVALID"
    assert result["examples"] == []
    assert result["rows_rejected_by_reason"] == {
        "MANIFEST_GENERATED_UTC_IN_FUTURE": 1
    }


def test_holdout_rejects_corrupt_full_label_archive(tmp_path: Path) -> None:
    manifest, _ledger, archive = _scenario(tmp_path)
    with sqlite3.connect(archive.path) as connection:
        connection.execute("DROP TRIGGER canonical_5m_candles_no_update")
        connection.execute(
            "UPDATE canonical_5m_candles SET payload_json = '{}' WHERE sequence = 1"
        )
        connection.commit()

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == (
        "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_INTEGRITY_UNVERIFIED"
    )
    assert result["examples"] == []
    assert result["rows_rejected_by_reason"]


def test_holdout_rejects_stale_label_proof_at_completion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest, _ledger, _archive = _scenario(tmp_path)
    monkeypatch.setattr(
        runtime.DurableCanonical5mLabelArchive,
        "integrity_proof_is_current",
        lambda _self, _proof: False,
    )

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == (
        "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_PROOF_STALE"
    )
    assert result["examples"] == []
    assert result["rows_rejected_by_reason"] == {
        "LABEL_ARCHIVE_HIGH_WATER_CHANGED_DURING_EVALUATION": 1
    }


def test_holdout_rejects_unfinished_higher_timeframe(tmp_path: Path) -> None:
    manifest, _ledger, _archive = _scenario(
        tmp_path,
        records=[_feature_record(unfinished_timeframe="4h")],
    )

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == "BLOCKED_AUTHENTICATED_HOLDOUT_PARTITION_UNVERIFIED"
    assert result["examples"] == []
    assert result["rows_rejected_by_reason"]["TIMEFRAME_FINALITY_4H_NOT_CLOSED"] == 1


def test_holdout_rejects_non_interval_higher_timeframe_finality(
    tmp_path: Path,
) -> None:
    manifest, _ledger, _archive = _scenario(
        tmp_path,
        records=[_feature_record(non_interval_timeframe="4h")],
    )

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == "BLOCKED_AUTHENTICATED_HOLDOUT_PARTITION_UNVERIFIED"
    assert result["examples"] == []
    assert result["rows_rejected_by_reason"]["TIMEFRAME_FINALITY_4H_TYPE_INVALID"] == 1


def test_holdout_rejects_one_microsecond_timeframe_interval_error(
    tmp_path: Path,
) -> None:
    manifest, _ledger, _archive = _scenario(
        tmp_path,
        records=[_feature_record(inexact_interval_timeframe="4h")],
    )

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == "BLOCKED_AUTHENTICATED_HOLDOUT_PARTITION_UNVERIFIED"
    assert result["examples"] == []
    assert result["rows_rejected_by_reason"]["TIMEFRAME_FINALITY_4H_INTERVAL_INVALID"] == 1


def test_holdout_rejects_feature_append_after_manifest_cutoff(
    tmp_path: Path,
) -> None:
    manifest, ledger, _archive = _scenario(tmp_path)
    ledger.append_snapshot(
        _feature_record(
            "post-cutoff-feature",
            decision_time=DECISION + timedelta(microseconds=2),
        )
    )

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == "BLOCKED_FEATURE_LEDGER_HIGH_WATER_UNVERIFIED"
    assert result["examples"] == []
    assert result["rows_rejected_by_reason"] == {
        "FEATURE_LEDGER_POSTCOMMIT_AFTER_OBSERVATION_CUTOFF": 1
    }


def test_holdout_rejects_label_append_after_manifest_cutoff(
    tmp_path: Path,
) -> None:
    manifest, _ledger, archive = _scenario(tmp_path)
    archive.append_candles(_candles(start_slot=49, count=1))

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == "BLOCKED_LABEL_ARCHIVE_HIGH_WATER_UNVERIFIED"
    assert result["examples"] == []
    assert result["rows_rejected_by_reason"] == {
        "LABEL_ARCHIVE_POSTCOMMIT_AFTER_OBSERVATION_CUTOFF": 1
    }


def test_label_path_requires_receipt_before_exact_observation(
    tmp_path: Path,
) -> None:
    _ledger, archive = _append_sources(tmp_path)
    integrity = archive.verify_integrity()
    high_water, reasons = runtime._label_archive_integrity_checkpoint(  # noqa: SLF001
        archive=archive,
        integrity=integrity,
        observation_cutoff=datetime.now(UTC),
        scan_limit=100,
    )
    assert reasons == []
    assert high_water is not None
    postcommit = runtime.parse_runtime_time(
        high_water["max_postcommit_readback_at"]
    )
    assert postcommit is not None

    rows, proof = archive.verified_label_path(
        symbol="BTCUSDT",
        decision_time=DECISION,
        training_observed_at=postcommit - timedelta(microseconds=1),
        horizon_seconds=4 * 60 * 60,
        archive_integrity_proof=integrity,
        require_receipt_committed_by_observation=True,
    )

    assert rows is None
    assert (
        "LABEL_ARCHIVE_POSTCOMMIT_READBACK_AFTER_TRAINING_OBSERVED_AT"
        in proof["rejection_reasons"]
    )


def test_holdout_rejects_scan_truncation_without_prefix_admission(
    tmp_path: Path,
) -> None:
    manifest, _ledger, _archive = _scenario(
        tmp_path,
        records=[
            _feature_record("candidate-1"),
            _feature_record(
                "candidate-2",
                decision_time=DECISION + timedelta(microseconds=2),
            ),
        ],
    )

    result = _evaluate(tmp_path, manifest, scan_limit=1)

    assert result["status"] == "BLOCKED_FEATURE_LEDGER_HIGH_WATER_UNVERIFIED"
    assert result["examples"] == []
    assert result["rows_rejected_by_reason"] == {
        "FEATURE_LEDGER_HIGH_WATER_SCAN_TRUNCATED": 1
    }


def test_holdout_rejects_manifest_candidate_set_digest_mismatch(
    tmp_path: Path,
) -> None:
    manifest, _ledger, _archive = _scenario(tmp_path)
    manifest["partition_evidence"][
        "holdout_sample_identity_set_sha256"
    ] = "0" * 64
    manifest_path = Path(str(manifest["manifest_path"]))
    manifest_path.write_text(
        json.dumps(
            {
                key: value
                for key, value in manifest.items()
                if key != "manifest_path"
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == "BLOCKED_AUTHENTICATED_HOLDOUT_PARTITION_UNVERIFIED"
    assert result["examples"] == []
    assert result["rows_rejected_by_reason"] == {
        "HOLDOUT_PARTITION_SAMPLE_IDENTITY_SET_MISMATCH": 1
    }


def test_holdout_does_not_create_missing_label_storage(tmp_path: Path) -> None:
    label_path = default_label_archive_path(tmp_path)
    manifest_path = tmp_path / "trusted_replay_train_validation_holdout_manifest.json"
    payload = {
        "schema_version": runtime.HOLDOUT_MANIFEST_SCHEMA_VERSION,
        "generated_utc": _iso(datetime.now(UTC)),
        "split_method": "STRICT_TEMPORAL_ORDER_NO_RANDOM_ROW_SPLIT",
        "temporal_overlap": False,
        "training_window": {"rows": 0},
        "validation_window": {"rows": 0},
        "holdout_window": {
            "rows": 0,
            "start_decision_time": _iso(DECISION),
            "end_decision_time": _iso(HOLDOUT_END),
        },
        "feature_ledger_high_water": {},
        "label_archive_high_water": {},
        "partition_evidence": {},
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    manifest = {**payload, "manifest_path": str(manifest_path)}

    result = _evaluate(tmp_path, manifest)

    assert result["status"] == "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED"
    assert result["examples"] == []
    assert not label_path.exists()
