from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    CanonicalCandle,
    canonical_candle_id,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    ARCHIVE_SCHEMA_VERSION,
    LABEL_SLOT_MILLISECONDS,
    MAX_CANONICAL_CANDLE_PAYLOAD_BYTES,
    MAX_QUERY_ROWS,
    RETENTION_POLICY,
    Canonical5mArchiveError,
    Canonical5mArchiveReadbackError,
    Canonical5mIdentityConflictError,
    Canonical5mValidationError,
    DurableCanonical5mLabelArchive,
    validate_canonical_finalized_5m_candle,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    canonical_5m_label_evidence,
)


BASE = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)
OBSERVED = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)


def _candle(
    slot: int,
    *,
    symbol: str = "BTCUSDT",
    available_at: datetime | None = None,
    raw_suffix: str = "base",
) -> dict[str, object]:
    open_time = BASE + timedelta(minutes=5 * slot)
    close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
    ingested = available_at or close_time + timedelta(milliseconds=1)
    close = 100.0 + slot * 0.1
    raw_hash = hashlib.sha256(
        f"{symbol}:{slot}:{raw_suffix}".encode()
    ).hexdigest()
    return CanonicalCandle(
        symbol=symbol,
        exchange="binance",
        timeframe="5m",
        candle_open_time=int(open_time.timestamp() * 1000),
        candle_close_time=int(close_time.timestamp() * 1000),
        event_time=int(close_time.timestamp() * 1000),
        ingested_at=int(ingested.timestamp() * 1000),
        available_at=int(ingested.timestamp() * 1000),
        is_closed=True,
        source="binance_wss",
        source_sequence_id=f"unit:{symbol}:{slot}",
        raw_payload_hash=raw_hash,
        ohlcv={
            "open": 100.0,
            "high": max(101.0, close),
            "low": 99.0,
            "close": close,
            "volume": 1_000.0 + slot,
            "quote_volume": 100_000.0 + slot,
            "num_trades": 100 + slot,
        },
        is_backfilled=False,
        feature_eligible=True,
    ).to_dict()


def _path(rows: int = 49) -> list[dict[str, object]]:
    return [_candle(slot) for slot in range(rows)]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        (lambda row: row.update(timeframe="15m"), "LABEL_CANDLE_NOT_CANONICAL_5M"),
        (lambda row: row.update(is_closed=False), "LABEL_CANDLE_NOT_FINAL"),
        (
            lambda row: row.update(candle_open_time="2026-07-18T00:00:00Z"),
            "LABEL_CANDLE_OPEN_TIME_MISSING_OR_INVALID",
        ),
        (
            lambda row: row.update(open_time=int(row["open_time"]) + 1),
            "LABEL_CANDLE_OPEN_TIME_CANONICAL_COPY_MISMATCH",
        ),
        (
            lambda row: row.update(available_at=int(row["available_at"]) + 1),
            "LABEL_CANDLE_AVAILABLE_AT_NOT_CANONICAL_MAX_CLOCK",
        ),
    ),
)
def test_strict_canonical_validation_rejects_noncanonical_payloads(
    mutation,
    reason: str,
) -> None:
    row = _candle(0)
    mutation(row)

    with pytest.raises(Canonical5mValidationError) as captured:
        validate_canonical_finalized_5m_candle(row)

    assert reason in captured.value.reasons


def test_append_and_indexed_range_read_are_transaction_and_pit_verified(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candles = _path()

    appended = archive.append_candles(candles)
    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=int(candles[0]["candle_close_time"]),
        end_close_time_ms=int(candles[-1]["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=49,
    )

    assert appended.attempted_rows == 49
    assert appended.inserted_rows == 49
    assert appended.duplicate_rows == 0
    assert appended.transaction_committed is True
    assert appended.transaction_readback_verified is True
    assert rows is not None
    assert [row["candle_id"] for row in rows] == [
        row["candle_id"] for row in candles
    ]
    assert proof["status"] == "VERIFIED_CANONICAL_5M_LABEL_RANGE"
    assert proof["symbol_close_time_index_used"] is True
    assert proof["canonical_payloads_verified"] is True
    assert proof["content_sha256_verified"] is True
    assert proof["append_transaction_readback_receipts_verified"] is True
    assert proof["pit_available_at_verified"] is True
    assert proof["contiguous_path_verified"] is True
    assert proof["loaded_rows"] == 49
    assert proof["range_sha256"]


def test_exact_tail_transaction_attestation_binds_one_all_inserted_batch(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candles = [_candle(0), _candle(1), _candle(2)]
    appended = archive.append_candles(candles)

    proof = archive.attest_exact_tail_transaction(candles)

    assert proof["status"] == (
        "VERIFIED_CANONICAL_5M_EXACT_TAIL_TRANSACTION"
    )
    assert proof["transaction_scope_verified"] is True
    assert proof["archive_integrity_verified"] is False
    assert proof["terminal_full_integrity_verification_required"] is True
    assert proof["transaction_id"] == appended.transaction_id
    assert proof["attempted_rows"] == 3
    assert proof["inserted_rows"] == 3
    assert proof["duplicate_rows"] == 0
    assert proof["expected_batch_sha256"] == appended.batch_sha256
    assert proof["append_receipt_sha256"] == (
        appended.append_receipt_sha256
    )
    assert proof["postcommit_readback_receipt_sha256"]
    assert proof["transaction_attestation_sha256"]
    assert [row["candle_id"] for row in proof["transaction_bindings"]] == [
        row["candle_id"] for row in candles
    ]
    assert proof["rejection_reasons"] == []
    attestation_keys = (
        "schema_version",
        "archive_schema_version",
        "archive_path",
        "status",
        "transaction_scope_verified",
        "archive_integrity_verified",
        "transaction_id",
        "expected_batch_sha256",
        "expected_bindings_sha256",
        "transaction_bindings",
        "attempted_rows",
        "inserted_rows",
        "duplicate_rows",
        "append_receipt_sha256",
        "postcommit_readback_receipt_sha256",
        "archive_total_unique_rows",
        "archive_chain_sha256",
        "transaction_is_current_tail",
        "terminal_full_integrity_verification_required",
        "rejection_reasons",
    )
    attestation_material = {key: proof[key] for key in attestation_keys}
    assert hashlib.sha256(
        json.dumps(
            attestation_material,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest() == proof["transaction_attestation_sha256"]


def test_exact_tail_transaction_attestation_rejects_mixed_or_stale_scope(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    first = _candle(0)
    second = _candle(1)
    archive.append_candles([first])
    archive.append_candles([second])

    mixed = archive.attest_exact_tail_transaction([first, second])
    stale = archive.attest_exact_tail_transaction([first])

    assert mixed["transaction_scope_verified"] is False
    assert "LABEL_ARCHIVE_EXACT_TAIL_TRANSACTION_ROW_COUNT_MISMATCH" in (
        mixed["rejection_reasons"]
    )
    assert stale["transaction_scope_verified"] is False
    assert "LABEL_ARCHIVE_EXACT_TRANSACTION_NOT_CURRENT_TAIL" in stale[
        "rejection_reasons"
    ]


def test_exact_tail_transaction_attestation_rejects_later_duplicate_receipt(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candle = _candle(0)
    archive.append_candles([candle])
    archive.append_candles([candle])

    proof = archive.attest_exact_tail_transaction([candle])

    assert proof["transaction_scope_verified"] is False
    assert "LABEL_ARCHIVE_EXACT_TRANSACTION_NOT_LATEST_RECEIPT" in proof[
        "rejection_reasons"
    ]


def test_exact_tail_transaction_attestation_rejects_changed_expected_bytes(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    stored = _candle(0)
    changed = _candle(0, raw_suffix="changed-provenance")
    archive.append_candles([stored])

    proof = archive.attest_exact_tail_transaction([changed])

    assert proof["transaction_scope_verified"] is False
    assert "LABEL_ARCHIVE_EXACT_TRANSACTION_PAYLOAD_MISMATCH" in proof[
        "rejection_reasons"
    ]
    assert "LABEL_ARCHIVE_EXACT_TRANSACTION_BATCH_MISMATCH" in proof[
        "rejection_reasons"
    ]


@pytest.mark.parametrize(
    ("trigger", "statement", "expected_reason"),
    (
        (
            "canonical_5m_receipts_no_update",
            "UPDATE canonical_5m_append_receipts "
            "SET batch_sha256 = '" + ("0" * 64) + "'",
            "LABEL_ARCHIVE_EXACT_TRANSACTION_BATCH_MISMATCH",
        ),
        (
            "canonical_5m_postcommit_receipts_no_update",
            "UPDATE canonical_5m_postcommit_readback_receipts "
            "SET inserted_identities_sha256 = '" + ("0" * 64) + "'",
            "LABEL_ARCHIVE_EXACT_TRANSACTION_POSTCOMMIT_BINDING_MISMATCH",
        ),
        (
            "canonical_5m_candles_no_update",
            "UPDATE canonical_5m_candles "
            "SET record_chain_sha256 = '" + ("0" * 64) + "'",
            "LABEL_ARCHIVE_EXACT_TRANSACTION_FINAL_CHAIN_MISMATCH",
        ),
    ),
)
def test_exact_tail_transaction_attestation_rejects_tampered_evidence(
    tmp_path: Path,
    trigger: str,
    statement: str,
    expected_reason: str,
) -> None:
    path = tmp_path / "labels.sqlite3"
    archive = DurableCanonical5mLabelArchive(path)
    candle = _candle(0)
    archive.append_candles([candle])
    with sqlite3.connect(path) as connection:
        connection.execute(f"DROP TRIGGER {trigger}")
        connection.execute(statement)
        connection.commit()

    proof = archive.attest_exact_tail_transaction([candle])

    assert proof["transaction_scope_verified"] is False
    assert expected_reason in proof["rejection_reasons"]


def test_exact_tail_transaction_attestation_recovers_postcommit_crash_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candles = [_candle(0), _candle(1)]

    def crash_after_transaction_a(**_kwargs: object) -> None:
        raise RuntimeError("injected_exact_tail_transaction_crash")

    monkeypatch.setattr(
        archive,
        "_verify_committed_transaction",
        crash_after_transaction_a,
    )
    with pytest.raises(RuntimeError, match="exact_tail_transaction_crash"):
        archive.append_candles(candles)
    monkeypatch.undo()

    proof = archive.attest_exact_tail_transaction(candles)

    assert proof["status"] == (
        "VERIFIED_CANONICAL_5M_EXACT_TAIL_TRANSACTION"
    )
    assert proof["postcommit_recovery"]["recovered_transactions"] == 1
    assert proof["transaction_scope_verified"] is True
    assert archive.verify_integrity()["archive_integrity_verified"] is True


def test_exact_tail_transaction_attestation_rejects_empty_input(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")

    with pytest.raises(
        Canonical5mArchiveError,
        match="exact_tail_transaction_attestation_rows_empty",
    ):
        archive.attest_exact_tail_transaction([])


def test_empty_archive_initialization_is_deterministic_and_crash_retry_safe(
    tmp_path: Path,
) -> None:
    path = tmp_path / "labels.sqlite3"
    archive = DurableCanonical5mLabelArchive(path)

    created = archive.initialize_empty_archive(
        initialization_intent_id="unit:historical-cutoff:2026-07-18",
    )
    retried = archive.initialize_empty_archive(
        initialization_intent_id="unit:historical-cutoff:2026-07-18",
    )

    assert created["status"] == (
        "CREATED_AND_VERIFIED_EMPTY_CANONICAL_5M_ARCHIVE"
    )
    assert retried["status"] == (
        "VERIFIED_EXISTING_EMPTY_CANONICAL_5M_ARCHIVE"
    )
    assert created["initialization_receipt_sha256"] == retried[
        "initialization_receipt_sha256"
    ]
    assert created["initialization_receipt_json"] == retried[
        "initialization_receipt_json"
    ]
    integrity = retried["archive_integrity_proof"]
    assert integrity["archive_integrity_verified"] is True
    assert integrity["verified_rows"] == 0
    assert integrity["verified_append_receipts"] == 0
    assert integrity["verified_postcommit_readback_receipts"] == 0


def test_empty_archive_initialization_rejects_invalid_intent_or_nonempty_state(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    with pytest.raises(
        Canonical5mArchiveError,
        match="initialization_intent_id_invalid",
    ):
        archive.initialize_empty_archive(initialization_intent_id=" bad ")

    archive.append_candles([_candle(0)])
    with pytest.raises(
        Canonical5mArchiveReadbackError,
        match="not_pristine_genesis",
    ):
        archive.initialize_empty_archive(
            initialization_intent_id="unit:nonempty-retry",
        )


def test_duplicate_identical_append_is_idempotent(tmp_path: Path) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candle = _candle(0)

    first = archive.append_candles([candle])
    second = archive.append_candles([candle])

    assert first.inserted_rows == 1
    assert second.inserted_rows == 0
    assert second.duplicate_rows == 1
    assert second.total_unique_rows == 1
    assert second.archive_chain_sha256 == first.archive_chain_sha256
    assert archive.verify_integrity()["archive_integrity_verified"] is True


def test_same_market_facts_with_changed_provenance_fail_closed(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    first = _candle(0)
    later = _candle(0, raw_suffix="later-observation")
    later["ingested_at"] = int(later["ingested_at"]) + 1_000
    later["available_at"] = int(later["available_at"]) + 1_000
    later["candle_id"] = canonical_candle_id(later)

    initial = archive.append_candles([first])
    with pytest.raises(Canonical5mIdentityConflictError):
        archive.append_candles([later])

    assert initial.inserted_rows == 1
    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=int(first["candle_close_time"]),
        end_close_time_ms=int(first["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=1,
    )
    assert rows == [first]
    assert proof["postcommit_readback_receipts_verified"] is True


def test_duplicate_close_with_different_content_fails_closed_and_rolls_back(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    first = _candle(0)
    archive.append_candles([first])
    conflict = _candle(0, raw_suffix="conflict")
    conflict["close"] = float(conflict["close"]) + 1.0
    assert isinstance(conflict["ohlcv"], dict)
    conflict["ohlcv"]["close"] = conflict["close"]
    conflict["candle_id"] = canonical_candle_id(conflict)

    with pytest.raises(Canonical5mIdentityConflictError):
        archive.append_candles([_candle(1), conflict])

    integrity = archive.verify_integrity()
    assert integrity["archive_integrity_verified"] is True
    assert integrity["verified_rows"] == 1
    start = int(_candle(1)["candle_close_time"])
    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=start,
        end_close_time_ms=start,
        training_observed_at=OBSERVED,
        limit=1,
    )
    assert rows is None
    assert "LABEL_ARCHIVE_RANGE_ROW_COUNT_MISMATCH" in proof[
        "rejection_reasons"
    ]


def test_future_available_row_is_retrieved_then_rejected_not_filtered(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    future = _candle(0, available_at=OBSERVED + timedelta(seconds=1))
    archive.append_candles([future])

    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=int(future["candle_close_time"]),
        end_close_time_ms=int(future["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=1,
    )

    assert rows is None
    assert proof["loaded_rows"] == 1
    assert proof["pit_available_at_verified"] is False
    assert proof["rejection_reasons"] == [
        "CANONICAL_5M_LABEL_AVAILABLE_AFTER_TRAINING_OBSERVED_AT"
    ]


def test_missing_middle_slot_fails_contiguous_range_proof(tmp_path: Path) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candles = [_candle(0), _candle(2)]
    archive.append_candles(candles)

    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=int(candles[0]["candle_close_time"]),
        end_close_time_ms=int(candles[-1]["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=3,
    )

    assert rows is None
    assert proof["contiguous_path_verified"] is False
    assert "LABEL_ARCHIVE_RANGE_ROW_COUNT_MISMATCH" in proof[
        "rejection_reasons"
    ]
    assert "CANONICAL_5M_LABEL_PATH_GAP" in proof["rejection_reasons"]


def test_sparse_coverage_proves_occupied_and_absent_slots_under_full_proof(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    first = _candle(0)
    missing = _candle(1)
    final = _candle(2)
    archive.append_candles([first, final])
    integrity = archive.verify_integrity()

    rows, proof = archive.verified_coverage(
        symbol="BTCUSDT",
        start_close_time_ms=int(first["candle_close_time"]),
        end_close_time_ms=int(final["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=3,
        archive_integrity_proof=integrity,
    )

    assert rows == [first, final]
    assert proof["status"] == "VERIFIED_CANONICAL_5M_SPARSE_COVERAGE"
    assert proof["expected_rows"] == 3
    assert proof["occupied_rows"] == 2
    assert proof["proven_absent_rows"] == 1
    assert proof["proven_absent_close_time_ms"] == [
        missing["candle_close_time"]
    ]
    assert proof["coverage_partition_complete"] is True
    assert proof["indexed_snapshot_verified"] is True
    assert proof["coverage_sha256"]
    assert [row["source"] for row in proof["occupied_identities"]] == [
        "binance_wss",
        "binance_wss",
    ]
    range_proof = proof["range_proof"]
    assert range_proof["archive_integrity_proof_current"] is True
    assert range_proof["symbol_close_time_index_used"] is True
    assert range_proof["append_transaction_readback_receipts_verified"] is True


def test_sparse_coverage_requires_current_full_integrity_proof(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    first = _candle(0)
    second = _candle(1)
    archive.append_candles([first])
    stale = archive.verify_integrity()
    archive.append_candles([second])

    missing_rows, missing_proof = archive.verified_coverage(
        symbol="BTCUSDT",
        start_close_time_ms=int(first["candle_close_time"]),
        end_close_time_ms=int(second["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=2,
        archive_integrity_proof=None,
    )
    stale_rows, stale_proof = archive.verified_coverage(
        symbol="BTCUSDT",
        start_close_time_ms=int(first["candle_close_time"]),
        end_close_time_ms=int(second["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=2,
        archive_integrity_proof=stale,
    )

    assert missing_rows is None
    assert missing_proof["status"].endswith("INTEGRITY_PROOF_REQUIRED")
    assert stale_rows is None
    assert stale_proof["status"].endswith("UNVERIFIED")
    assert any(
        reason.endswith("_STALE")
        for reason in stale_proof["rejection_reasons"]
    )


def test_query_never_silently_truncates_past_explicit_limit(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candles = _path(rows=3)
    archive.append_candles(candles)

    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=int(candles[0]["candle_close_time"]),
        end_close_time_ms=int(candles[-1]["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=2,
    )

    assert rows is None
    assert proof["loaded_rows"] == 0
    assert proof["rejection_reasons"] == [
        "LABEL_ARCHIVE_QUERY_LIMIT_INSUFFICIENT"
    ]
    assert proof["maximum_query_rows"] == MAX_QUERY_ROWS


def test_retention_is_explicit_and_candle_rows_are_immutable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "labels.sqlite3"
    archive = DurableCanonical5mLabelArchive(path)
    archive.append_candles([_candle(0)])

    retention = archive.retention_status()

    assert retention["schema_version"] == ARCHIVE_SCHEMA_VERSION
    assert retention["retention_policy"] == RETENTION_POLICY
    assert retention["automatic_pruning_enabled"] is False
    assert retention["silent_pruning_used"] is False
    assert retention["delete_api_exposed"] is False
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM canonical_5m_candles")


def test_payload_tamper_fails_content_and_full_integrity_proofs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "labels.sqlite3"
    archive = DurableCanonical5mLabelArchive(path)
    candle = _candle(0)
    archive.append_candles([candle])
    tampered = dict(candle)
    tampered["close"] = 999.0
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER canonical_5m_candles_no_update")
        connection.execute(
            "UPDATE canonical_5m_candles SET payload_json = ?",
            (json.dumps(tampered, sort_keys=True, separators=(",", ":")),),
        )
        connection.commit()

    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=int(candle["candle_close_time"]),
        end_close_time_ms=int(candle["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=1,
    )
    integrity = archive.verify_integrity()

    assert rows is None
    assert "LABEL_ARCHIVE_CONTENT_SHA256_MISMATCH" in proof[
        "rejection_reasons"
    ]
    assert integrity["archive_integrity_verified"] is False
    assert "LABEL_ARCHIVE_CONTENT_SHA256_MISMATCH" in integrity[
        "rejection_reasons"
    ]


def test_slot_constant_matches_protocol_five_minutes() -> None:
    assert LABEL_SLOT_MILLISECONDS == 300_000


def test_append_batch_is_strictly_memory_bounded(tmp_path: Path) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")

    with pytest.raises(
        Canonical5mArchiveError,
        match="canonical_5m_append_row_limit_exceeded",
    ):
        archive.append_candles(
            _candle(slot, symbol="ETHUSDT") for slot in range(4_097)
        )


def test_conflicting_candle_id_copy_is_rejected_by_canonical_validator() -> None:
    row = _candle(0)
    row["raw_payload_hash"] = hashlib.sha256(b"different").hexdigest()
    assert row["candle_id"] != canonical_candle_id(row)

    with pytest.raises(Canonical5mValidationError) as captured:
        validate_canonical_finalized_5m_candle(row)

    assert captured.value.reasons == ("LABEL_CANDLE_ID_MISMATCH",)


def test_trainer_label_path_derives_exact_intra_slot_query_bounds(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candles = _path(rows=49)
    archive.append_candles(candles)
    decision_time = BASE + timedelta(minutes=2, seconds=30)

    rows, proof = archive.verified_label_path(
        symbol="BTCUSDT",
        decision_time=decision_time,
        training_observed_at=OBSERVED,
        horizon_seconds=4 * 60 * 60,
    )

    assert rows is not None
    assert len(rows) == 49
    assert rows[0]["candle_id"] == candles[0]["candle_id"]
    assert rows[-1]["candle_id"] == candles[-1]["candle_id"]
    assert proof["status"] == "VERIFIED_CANONICAL_5M_TRAINER_LABEL_PATH"
    assert proof["start_close_time_ms"] == candles[0]["candle_close_time"]
    assert proof["end_close_time_ms"] == candles[-1]["candle_close_time"]
    assert proof["first_candle_overlaps_decision"] is True
    assert proof["strictly_after_decision_verified"] is True
    assert proof["horizon_endpoint_verified"] is True
    assert proof["horizon_lateness_ms"] == 149_999
    assert proof["range_proof"]["contiguous_path_verified"] is True
    assert proof["range_proof"]["pit_available_at_verified"] is True


def test_trainer_label_path_at_exact_close_starts_with_next_slot(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candles = _path(rows=49)
    archive.append_candles(candles)
    decision_close_ms = int(candles[0]["candle_close_time"])

    rows, proof = archive.verified_label_path(
        symbol="BTCUSDT",
        decision_time=decision_close_ms,
        training_observed_at=OBSERVED,
        horizon_seconds=4 * 60 * 60,
    )

    assert rows is not None
    assert len(rows) == 48
    assert rows[0]["candle_id"] == candles[1]["candle_id"]
    assert rows[-1]["candle_id"] == candles[-1]["candle_id"]
    assert proof["first_candle_overlaps_decision"] is False
    assert proof["horizon_lateness_ms"] == 0


def test_microsecond_decision_uses_strict_start_and_ceil_horizon_endpoint(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candles = _path(rows=50)
    archive.append_candles(candles)
    first_close = datetime.fromtimestamp(
        int(candles[0]["candle_close_time"]) / 1_000.0,
        tz=UTC,
    )
    decision_time = first_close + timedelta(microseconds=600)

    rows, proof = archive.verified_label_path(
        symbol="BTCUSDT",
        decision_time=decision_time,
        training_observed_at=OBSERVED,
        horizon_seconds=4 * 60 * 60,
    )

    assert rows is not None
    assert len(rows) == 49
    assert rows[0]["candle_id"] == candles[1]["candle_id"]
    assert rows[-1]["candle_id"] == candles[49]["candle_id"]
    assert proof["decision_time_epoch_us"] % 1_000 == 600
    assert proof["horizon_target_time_epoch_us"] % 1_000 == 600
    assert proof["horizon_lateness_us"] == 299_999_400

    evidence, reasons = canonical_5m_label_evidence(
        candles=rows,
        symbol="BTCUSDT",
        decision_time=decision_time,
        training_observed_at=OBSERVED,
    )
    assert reasons == []
    assert evidence is not None
    assert evidence["horizon_candle_ids"]["4h"] == candles[49]["candle_id"]
    assert evidence["decision_time_epoch_us"] == proof["decision_time_epoch_us"]


def test_dataset_pit_floor_rejects_submillisecond_future_availability() -> None:
    candles = _path(rows=49)
    decision_time = BASE + timedelta(minutes=2, seconds=30)
    final_available_ms = int(candles[-1]["available_at"])
    observed_400us_before = datetime.fromtimestamp(
        final_available_ms / 1_000.0,
        tz=UTC,
    ) - timedelta(microseconds=400)

    evidence, reasons = canonical_5m_label_evidence(
        candles=candles,
        symbol="BTCUSDT",
        decision_time=decision_time,
        training_observed_at=observed_400us_before,
    )

    assert evidence is None
    assert reasons == [
        "CANONICAL_5M_LABEL_AVAILABLE_AFTER_TRAINING_OBSERVED_AT"
    ]


@pytest.mark.parametrize(
    ("decision_time", "observed_at", "horizon_seconds", "reason"),
    (
        (
            datetime(2026, 7, 18, 0, 0),
            OBSERVED,
            4 * 60 * 60,
            "DECISION_TIME_MISSING_OR_INVALID",
        ),
        (
            BASE,
            BASE,
            4 * 60 * 60,
            "TRAINING_OBSERVED_AT_NOT_AFTER_DECISION_TIME",
        ),
        (
            BASE,
            OBSERVED,
            True,
            "LABEL_HORIZON_SECONDS_MISSING_OR_INVALID",
        ),
    ),
)
def test_trainer_label_path_rejects_ambiguous_or_invalid_time_contract(
    tmp_path: Path,
    decision_time: datetime,
    observed_at: datetime,
    horizon_seconds: int,
    reason: str,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")

    rows, proof = archive.verified_label_path(
        symbol="BTCUSDT",
        decision_time=decision_time,
        training_observed_at=observed_at,
        horizon_seconds=horizon_seconds,
    )

    assert rows is None
    assert reason in proof["rejection_reasons"]


def test_range_limit_requires_strict_integer_not_coercible_value(
    tmp_path: Path,
) -> None:
    candle = _candle(0)
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    archive.append_candles([candle])

    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=int(candle["candle_close_time"]),
        end_close_time_ms=int(candle["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=True,
    )

    assert rows is None
    assert proof["rejection_reasons"] == [
        "LABEL_ARCHIVE_QUERY_LIMIT_INVALID"
    ]


def test_crash_gap_blocks_reads_until_bounded_postcommit_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "labels.sqlite3"
    archive = DurableCanonical5mLabelArchive(path)
    candle = _candle(0)
    original = archive._verify_committed_transaction

    def crash_after_transaction_a(**_kwargs: object) -> None:
        raise RuntimeError("injected_after_transaction_a_commit")

    monkeypatch.setattr(
        archive,
        "_verify_committed_transaction",
        crash_after_transaction_a,
    )
    with pytest.raises(RuntimeError, match="injected_after_transaction_a"):
        archive.append_candles([candle])
    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=int(candle["candle_close_time"]),
        end_close_time_ms=int(candle["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=1,
    )
    assert rows is None
    assert "LABEL_ARCHIVE_POSTCOMMIT_READBACK_RECEIPT_MISSING" in proof[
        "rejection_reasons"
    ]
    assert proof["postcommit_readback_receipts_verified"] is False
    assert archive.verify_integrity()["archive_integrity_verified"] is False

    monkeypatch.setattr(archive, "_verify_committed_transaction", original)
    recovered = archive.recover_pending_postcommit_readbacks()
    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=int(candle["candle_close_time"]),
        end_close_time_ms=int(candle["candle_close_time"]),
        training_observed_at=OBSERVED,
        limit=1,
    )

    assert recovered["recovered_transactions"] == 1
    assert rows == [candle]
    assert proof["postcommit_readback_receipts_verified"] is True
    assert archive.verify_integrity()["archive_integrity_verified"] is True


def test_cached_integrity_proof_stales_on_duplicate_only_crash_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candle = _candle(0)
    archive.append_candles([candle])
    cached_proof = archive.verify_integrity()
    original = archive._verify_committed_transaction

    def crash_after_duplicate_receipt_commit(**_kwargs: object) -> None:
        raise RuntimeError("injected_duplicate_only_transaction_a_crash")

    monkeypatch.setattr(
        archive,
        "_verify_committed_transaction",
        crash_after_duplicate_receipt_commit,
    )
    with pytest.raises(RuntimeError, match="duplicate_only_transaction_a"):
        archive.append_candles([candle])

    assert archive.integrity_proof_is_current(cached_proof) is False
    failed = archive.verify_integrity()
    assert failed["archive_integrity_verified"] is False
    assert "LABEL_ARCHIVE_POSTCOMMIT_READBACK_RECEIPT_MISSING" in failed[
        "rejection_reasons"
    ]

    monkeypatch.setattr(archive, "_verify_committed_transaction", original)
    archive.recover_pending_postcommit_readbacks()
    refreshed = archive.verify_integrity()
    assert refreshed["archive_integrity_verified"] is True
    assert refreshed["verified_append_receipts"] == 2
    assert refreshed["verified_postcommit_readback_receipts"] == 2


def test_missing_archive_integrity_check_does_not_create_storage(
    tmp_path: Path,
) -> None:
    path = tmp_path / "missing.sqlite3"
    archive = DurableCanonical5mLabelArchive(path)

    integrity = archive.verify_integrity()

    assert integrity["archive_integrity_verified"] is False
    assert integrity["status"] == "BLOCKED_CANONICAL_5M_LABEL_ARCHIVE_MISSING"
    assert path.exists() is False


def test_append_rejects_oversized_single_candle_before_sqlite_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "labels.sqlite3"
    archive = DurableCanonical5mLabelArchive(path)
    candle = _candle(0)
    candle["source_sequence_id"] = "x" * (
        MAX_CANONICAL_CANDLE_PAYLOAD_BYTES + 1
    )

    with pytest.raises(
        Canonical5mArchiveError,
        match="canonical_5m_candle_payload_bytes_exceeded",
    ):
        archive.append_candles([candle])

    assert path.exists() is False


def test_submillisecond_observation_before_available_at_fails_pit(
    tmp_path: Path,
) -> None:
    archive = DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3")
    candle = _candle(0)
    archive.append_candles([candle])
    available_ms = int(candle["available_at"])
    observed_400us_before = datetime.fromtimestamp(
        available_ms / 1000.0,
        tz=UTC,
    ) - timedelta(microseconds=400)

    rows, proof = archive.verified_range(
        symbol="BTCUSDT",
        start_close_time_ms=int(candle["candle_close_time"]),
        end_close_time_ms=int(candle["candle_close_time"]),
        training_observed_at=observed_400us_before,
        limit=1,
    )

    assert rows is None
    assert proof["pit_available_at_verified"] is False
    assert "CANONICAL_5M_LABEL_AVAILABLE_AFTER_TRAINING_OBSERVED_AT" in proof[
        "rejection_reasons"
    ]


def test_strict_validator_rejects_numeric_strings_and_unknown_fields() -> None:
    numeric_string = _candle(0)
    numeric_string["close"] = str(numeric_string["close"])
    unknown = _candle(0)
    unknown["unmodeled_extension"] = 1

    with pytest.raises(Canonical5mValidationError) as numeric_error:
        validate_canonical_finalized_5m_candle(numeric_string)
    with pytest.raises(Canonical5mValidationError) as unknown_error:
        validate_canonical_finalized_5m_candle(unknown)

    assert "LABEL_CANDLE_CLOSE_MISSING_OR_INVALID" in numeric_error.value.reasons
    assert "LABEL_CANDLE_UNKNOWN_TOP_LEVEL_FIELDS" in unknown_error.value.reasons


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        (
            lambda row: row.update(taker_buy_base_vol=123.0),
            "LABEL_CANDLE_OHLCV_CANONICAL_COPY_MISMATCH",
        ),
        (
            lambda row: row.update(is_backfilled=True),
            "LABEL_CANDLE_WSS_BACKFILL_STATE_INVALID",
        ),
        (
            lambda row: row.update(source="binance_rest"),
            "LABEL_CANDLE_REST_BACKFILL_STATE_INVALID",
        ),
        (
            lambda row: row.update({1: "non-string-field"}),
            "LABEL_CANDLE_UNKNOWN_TOP_LEVEL_FIELDS",
        ),
    ),
)
def test_strict_validator_rejects_copy_and_source_provenance_mismatches(
    mutation,
    reason: str,
) -> None:
    row = _candle(0)
    mutation(row)

    with pytest.raises(Canonical5mValidationError) as captured:
        validate_canonical_finalized_5m_candle(row)

    assert reason in captured.value.reasons


def test_strict_validator_rejects_identity_whitespace_and_rest_clock_lies() -> None:
    spaced_symbol = _candle(0)
    spaced_symbol["symbol"] = " BTCUSDT "
    spaced_symbol["candle_id"] = canonical_candle_id(spaced_symbol)
    spaced_candle_id = _candle(0)
    spaced_candle_id["candle_id"] = f"{spaced_candle_id['candle_id']} "
    spaced_sequence = _candle(0)
    spaced_sequence["source_sequence_id"] = " unit:BTCUSDT:0 "
    false_rest = _candle(0)
    false_rest["source"] = "binance_rest"
    false_rest["is_backfilled"] = True

    cases = (
        (spaced_symbol, "LABEL_CANDLE_SYMBOL_NOT_CANONICAL_UPPERCASE"),
        (spaced_candle_id, "LABEL_CANDLE_ID_NOT_CANONICAL"),
        (
            spaced_sequence,
            "LABEL_CANDLE_SOURCE_SEQUENCE_ID_NOT_CANONICAL",
        ),
        (false_rest, "LABEL_CANDLE_REST_SOURCE_SEQUENCE_ID_INVALID"),
    )
    for row, reason in cases:
        with pytest.raises(Canonical5mValidationError) as captured:
            validate_canonical_finalized_5m_candle(row)
        assert reason in captured.value.reasons
