from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from v2.backend.app.services.durable_paper_evidence_archive import (
    COUNTERFACTUAL_ARCHIVE_STREAM_ID,
    COUNTERFACTUAL_REPLACEMENT_INTENT_KIND,
    COUNTERFACTUAL_REPLACEMENT_INTENT_SCHEMA,
    COUNTERFACTUAL_REPLACEMENT_OUTCOME_KIND,
    COUNTERFACTUAL_REPLACEMENT_OUTCOME_SCHEMA,
    COUNTERFACTUAL_SOURCE_FINGERPRINT_CONTRACT,
    COUNTERFACTUAL_VERIFIED_LATEST_ROWS_MAX_BYTES,
    REDIS_SOURCE_COMPARE_ENDPOINT_CONTRACT,
    ArchiveCandidate,
    DurablePaperEvidenceArchive,
    canonical_json,
    counterfactual_archive_sort_key,
    ordered_rows_sha256,
)

STREAM_ID = "unit_durable_counterfactual_stream_v1"
SOURCE_KEY = "v2:trainer:feedback:counterfactuals"


def _candidate(
    record_id: str,
    sort_key: str,
    *,
    value: int,
    observed_at: str,
) -> ArchiveCandidate:
    payload = {
        "record_id": record_id,
        "sort_key": sort_key,
        "value": value,
        "observed_at": observed_at,
    }
    return ArchiveCandidate(
        record_id=record_id,
        sort_key=sort_key,
        payload=payload,
        semantic_payload={
            key: field_value
            for key, field_value in payload.items()
            if key != "observed_at"
        },
    )


def _identity(payload) -> str:
    return str(payload["record_id"])


def _sort_key(payload) -> str:
    return str(payload["sort_key"])


def _feedback_candidate(
    record_id: str,
    *,
    decision_time: str,
    ordinal: int,
) -> ArchiveCandidate:
    payload = {
        "trainer_feedback_id": record_id,
        "counterfactual_feedback_id": record_id,
        "decision_time": decision_time,
        "ordinal": ordinal,
    }
    return ArchiveCandidate(
        record_id=record_id,
        sort_key=counterfactual_archive_sort_key(payload),
        payload=payload,
    )


def _replacement_proof(
    path: Path,
    *,
    complete_snapshot: bool = True,
    write_receipts: bool = True,
    readback_verified: bool = True,
) -> DurablePaperEvidenceArchive:
    archive = DurablePaperEvidenceArchive(
        path,
        stream_id=COUNTERFACTUAL_ARCHIVE_STREAM_ID,
    )
    candidate = _feedback_candidate(
        "feedback-1",
        decision_time="2026-07-18T00:00:00Z",
        ordinal=1,
    )
    appended = archive.append_unique([candidate])
    snapshot_id = "replacement-snapshot-1"
    archive.begin_source_snapshot(snapshot_id=snapshot_id, source_key=SOURCE_KEY)
    occurrence = archive.append_source_snapshot_occurrences(
        snapshot_id=snapshot_id,
        expected_start_index=0,
        candidates=[candidate],
    )
    raw_source = canonical_json([dict(candidate.payload)]).encode("utf-8")
    raw_sha256 = hashlib.sha256(raw_source).hexdigest()
    snapshot = {
        "snapshot_id": snapshot_id,
        "occurrence_count": 1,
        "ordered_occurrence_sha256": occurrence[
            "ordered_occurrence_sha256"
        ],
        "observed_source_byte_length": len(raw_source),
        "observed_source_sha256": raw_sha256,
        "canonical_json_byte_length": len(raw_source),
        "canonical_json_sha256": raw_sha256,
    }
    if complete_snapshot:
        snapshot = archive.finalize_source_snapshot(
            snapshot_id=snapshot_id,
            expected_occurrence_count=1,
            expected_ordered_occurrence_sha256=occurrence[
                "ordered_occurrence_sha256"
            ],
            observed_source_byte_length=len(raw_source),
            observed_source_sha256=raw_sha256,
        )
    if not write_receipts:
        return archive

    target_rows = [dict(candidate.payload)]
    target_digest = ordered_rows_sha256(target_rows)
    target_payload_bytes = sum(
        len(canonical_json(row).encode("utf-8")) for row in target_rows
    )
    intent_id = "replacement-1:intent"
    intent = {
        "schema_version": COUNTERFACTUAL_REPLACEMENT_INTENT_SCHEMA,
        "operation_id": intent_id,
        "redis_key": SOURCE_KEY,
        "source_guard_acquired_before_stream": True,
        "source_snapshot_id": snapshot_id,
        "source_snapshot_occurrence_count": 1,
        "source_snapshot_ordered_occurrence_sha256": snapshot[
            "ordered_occurrence_sha256"
        ],
        "source_snapshot_observed_redis_byte_length": len(raw_source),
        "source_snapshot_canonical_json_byte_length": len(raw_source),
        "source_snapshot_canonical_json_sha256": snapshot[
            "canonical_json_sha256"
        ],
        "source_snapshot_observed_source_sha256": raw_sha256,
        "source_snapshot_fingerprint_contract": (
            COUNTERFACTUAL_SOURCE_FINGERPRINT_CONTRACT
        ),
        "source_snapshot_rollback_reconstruction_verified": True,
        "archive_chain_sha256": appended.archive_chain_sha256,
        "archive_total_unique_rows": appended.total_unique_rows,
        "archive_integrity_verified": True,
        "all_input_rows_accounted_for": True,
        "target_hot_rows": 1,
        "target_hot_max_rows": 8,
        "target_hot_payload_bytes": target_payload_bytes,
        "target_hot_max_payload_bytes": (
            COUNTERFACTUAL_VERIFIED_LATEST_ROWS_MAX_BYTES
        ),
        "target_hot_ordered_rows_sha256": target_digest,
        "archive_first_before_redis_replace": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    intent_result = archive.append_operation_receipt(
        operation_id=intent_id,
        operation_kind=COUNTERFACTUAL_REPLACEMENT_INTENT_KIND,
        receipt=intent,
        expected_archive_chain_sha256=appended.archive_chain_sha256,
        expected_total_unique_rows=appended.total_unique_rows,
    )
    atomic_replace = {
        "source_guard_supported": True,
        "source_guard_acquired": True,
        "source_compare_atomic_with_write": True,
        "source_compare_performed_immediately_before_write": True,
        "source_compare_endpoint_contract": (
            REDIS_SOURCE_COMPARE_ENDPOINT_CONTRACT
        ),
        "source_unchanged_at_replace": True,
        "source_concurrency_conflict": False,
        "write_attempted": True,
        "write_succeeded": True,
        "redis_state_after_attempt_known": True,
        "observed_source_byte_length": len(raw_source),
        "observed_source_sha256": raw_sha256,
    }
    outcome = {
        "schema_version": COUNTERFACTUAL_REPLACEMENT_OUTCOME_SCHEMA,
        "operation_id": "replacement-1:outcome",
        "intent_operation_id": intent_id,
        "intent_receipt_sha256": intent_result["receipt_sha256"],
        "redis_key": SOURCE_KEY,
        "source_snapshot_id": snapshot_id,
        "source_snapshot_occurrence_count": 1,
        "source_snapshot_ordered_occurrence_sha256": snapshot[
            "ordered_occurrence_sha256"
        ],
        "source_snapshot_canonical_json_sha256": snapshot[
            "canonical_json_sha256"
        ],
        "source_snapshot_observed_source_sha256": raw_sha256,
        "source_snapshot_fingerprint_contract": (
            COUNTERFACTUAL_SOURCE_FINGERPRINT_CONTRACT
        ),
        "source_snapshot_rollback_reconstruction_verified": True,
        "archive_chain_sha256": appended.archive_chain_sha256,
        "archive_total_unique_rows": appended.total_unique_rows,
        "target_hot_rows": 1,
        "target_hot_payload_bytes": target_payload_bytes,
        "target_hot_max_payload_bytes": (
            COUNTERFACTUAL_VERIFIED_LATEST_ROWS_MAX_BYTES
        ),
        "target_hot_ordered_rows_sha256": target_digest,
        "atomic_replace": atomic_replace,
        "hot_cache_readback_rows": 1,
        "hot_cache_readback_ordered_rows_sha256": (
            target_digest if readback_verified else None
        ),
        "hot_cache_readback_digest_verified": readback_verified,
        "hot_cache_replace_verified": readback_verified,
        "rollback_status": (
            "NOT_REQUIRED_REPLACEMENT_VERIFIED"
            if readback_verified
            else "ROLLBACK_AVAILABLE_FROM_DURABLE_ORDERED_SOURCE_SNAPSHOT"
        ),
        "no_data_loss_proven": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    archive.append_operation_receipt(
        operation_id="replacement-1:outcome",
        operation_kind=COUNTERFACTUAL_REPLACEMENT_OUTCOME_KIND,
        receipt=outcome,
        expected_archive_chain_sha256=appended.archive_chain_sha256,
        expected_total_unique_rows=appended.total_unique_rows,
    )
    return archive


def test_latest_rows_is_query_bounded_and_verifies_payload_bindings(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.sqlite3"
    archive = DurablePaperEvidenceArchive(path, stream_id=STREAM_ID)
    archive.append_unique(
        [
            _candidate(
                f"row-{index}",
                f"2026-07-18T00:0{index}:00Z|row-{index}",
                value=index,
                observed_at="2026-07-18T01:00:00Z",
            )
            for index in range(4)
        ]
    )

    rows = archive.latest_rows(
        2,
        identity_resolver=_identity,
        sort_key_resolver=_sort_key,
    )

    assert [row["record_id"] for row in rows] == ["row-2", "row-3"]
    assert archive.latest_rows(0) == []
    newest_two = archive.latest_rows(2)
    newest_two_bytes = sum(
        len(canonical_json(row).encode("utf-8")) for row in newest_two
    )
    assert archive.latest_rows(
        4,
        max_payload_bytes=newest_two_bytes,
    ) == newest_two
    newest_row_bytes = len(
        canonical_json(newest_two[-1]).encode("utf-8")
    )
    with pytest.raises(
        ValueError,
        match="durable_archive_latest_row_exceeds_payload_byte_bound",
    ):
        archive.latest_rows(
            4,
            max_payload_bytes=newest_row_bytes - 1,
        )

    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE evidence_records
            SET sort_key = '9999-12-31T23:59:59Z|row-0'
            WHERE stream_id = ? AND record_id = 'row-0'
            """,
            (STREAM_ID,),
        )
        connection.commit()

    with pytest.raises(ValueError, match="durable_archive_sort_key_mismatch:row-0"):
        archive.verify_integrity(
            identity_resolver=_identity,
            sort_key_resolver=_sort_key,
        )


def test_source_snapshot_preserves_duplicate_order_and_exact_occurrence_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.sqlite3"
    archive = DurablePaperEvidenceArchive(path, stream_id=STREAM_ID)
    occurrences = [
        _candidate(
            "row-a",
            "2026-07-18T00:00:00Z|row-a",
            value=1,
            observed_at="2026-07-18T01:00:00Z",
        ),
        _candidate(
            "row-a",
            "2026-07-18T00:00:00Z|row-a",
            value=1,
            observed_at="2026-07-18T02:00:00Z",
        ),
        _candidate(
            "row-a",
            "2026-07-18T00:00:00Z|row-a",
            value=1,
            observed_at="2026-07-18T01:00:00Z",
        ),
        _candidate(
            "row-b",
            "2026-07-18T00:01:00Z|row-b",
            value=2,
            observed_at="2026-07-18T03:00:00Z",
        ),
    ]
    archive.append_unique(occurrences)
    archive.begin_source_snapshot(
        snapshot_id="snapshot-1",
        source_key="v2:test:source",
    )
    first = archive.append_source_snapshot_occurrences(
        snapshot_id="snapshot-1",
        expected_start_index=0,
        candidates=occurrences[:2],
    )
    second = archive.append_source_snapshot_occurrences(
        snapshot_id="snapshot-1",
        expected_start_index=2,
        candidates=occurrences[2:],
    )
    expected_payloads = [dict(candidate.payload) for candidate in occurrences]
    expected_json = canonical_json(expected_payloads).encode("utf-8")

    sealed = archive.finalize_source_snapshot(
        snapshot_id="snapshot-1",
        expected_occurrence_count=4,
        expected_ordered_occurrence_sha256=second[
            "ordered_occurrence_sha256"
        ],
        observed_source_byte_length=len(expected_json),
    )
    verified = archive.verify_source_snapshot("snapshot-1")
    reconstructed = b"".join(
        archive.source_snapshot_json_chunks("snapshot-1")
    )

    assert first["occurrence_count"] == 2
    assert sealed["snapshot_status"] == "COMPLETE_VERIFIED"
    assert verified["occurrence_count"] == 4
    assert verified["canonical_json_sha256"] == hashlib.sha256(
        expected_json
    ).hexdigest()
    assert reconstructed == expected_json
    assert canonical_json(expected_payloads[0]) in reconstructed.decode("utf-8")
    assert canonical_json(expected_payloads[1]) in reconstructed.decode("utf-8")
    with sqlite3.connect(path) as connection:
        occurrence_count = connection.execute(
            "SELECT COUNT(*) FROM archive_source_snapshot_occurrences"
        ).fetchone()[0]
        distinct_payload_count = connection.execute(
            "SELECT COUNT(*) FROM archive_source_occurrence_payloads"
        ).fetchone()[0]
    assert occurrence_count == 4
    assert distinct_payload_count == 3


def test_aborted_snapshot_removes_incomplete_occurrences_and_payloads(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.sqlite3"
    archive = DurablePaperEvidenceArchive(path, stream_id=STREAM_ID)
    candidate = _candidate(
        "row-a",
        "2026-07-18T00:00:00Z|row-a",
        value=1,
        observed_at="2026-07-18T01:00:00Z",
    )
    archive.append_unique([candidate])
    archive.begin_source_snapshot(
        snapshot_id="snapshot-abort",
        source_key="v2:test:source",
    )
    archive.append_source_snapshot_occurrences(
        snapshot_id="snapshot-abort",
        expected_start_index=0,
        candidates=[candidate],
    )

    archive.abort_source_snapshot("snapshot-abort", reason="UNIT_FAILURE")

    with sqlite3.connect(path) as connection:
        occurrence_count = connection.execute(
            "SELECT COUNT(*) FROM archive_source_snapshot_occurrences"
        ).fetchone()[0]
        payload_count = connection.execute(
            "SELECT COUNT(*) FROM archive_source_occurrence_payloads"
        ).fetchone()[0]
        snapshot = connection.execute(
            """
            SELECT snapshot_status, occurrence_count
            FROM archive_source_snapshots
            WHERE snapshot_id = 'snapshot-abort'
            """
        ).fetchone()
    assert occurrence_count == 0
    assert payload_count == 0
    assert snapshot == ("ABORTED:UNIT_FAILURE", 0)


def test_exclusive_worker_recovery_removes_crash_left_in_progress_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.sqlite3"
    archive = DurablePaperEvidenceArchive(path, stream_id=STREAM_ID)
    candidate = _candidate(
        "row-a",
        "2026-07-18T00:00:00Z|row-a",
        value=1,
        observed_at="2026-07-18T01:00:00Z",
    )
    archive.append_unique([candidate])
    archive.begin_source_snapshot(
        snapshot_id="crash-left-snapshot",
        source_key="v2:test:source",
    )
    archive.append_source_snapshot_occurrences(
        snapshot_id="crash-left-snapshot",
        expected_start_index=0,
        candidates=[candidate],
    )

    recovery = archive.abort_in_progress_source_snapshots(
        source_key="v2:test:source",
        reason="UNIT_LOCK_REACQUIRED",
    )

    assert recovery["recovered_snapshot_ids"] == ["crash-left-snapshot"]
    assert recovery["removed_incomplete_occurrence_mappings"] == 1
    with sqlite3.connect(path) as connection:
        snapshot = connection.execute(
            """
            SELECT snapshot_status, occurrence_count
            FROM archive_source_snapshots
            WHERE snapshot_id = 'crash-left-snapshot'
            """
        ).fetchone()
        payload_count = connection.execute(
            "SELECT COUNT(*) FROM archive_source_occurrence_payloads"
        ).fetchone()[0]
    assert snapshot == ("ABORTED:UNIT_LOCK_REACQUIRED", 0)
    assert payload_count == 0


def test_snapshot_retention_keeps_exact_initial_and_latest_rollbacks(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.sqlite3"
    archive = DurablePaperEvidenceArchive(path, stream_id=STREAM_ID)
    candidate = _candidate(
        "row-a",
        "2026-07-18T00:00:00Z|row-a",
        value=1,
        observed_at="2026-07-18T01:00:00Z",
    )
    archive.append_unique([candidate])
    expected_json = canonical_json([dict(candidate.payload)]).encode("utf-8")
    for index in range(3):
        snapshot_id = f"snapshot-{index}"
        archive.begin_source_snapshot(
            snapshot_id=snapshot_id,
            source_key="v2:test:source",
        )
        occurrence = archive.append_source_snapshot_occurrences(
            snapshot_id=snapshot_id,
            expected_start_index=0,
            candidates=[candidate],
        )
        archive.finalize_source_snapshot(
            snapshot_id=snapshot_id,
            expected_occurrence_count=1,
            expected_ordered_occurrence_sha256=occurrence[
                "ordered_occurrence_sha256"
            ],
            observed_source_byte_length=len(expected_json),
        )

    retention = archive.prune_verified_source_snapshots(
        source_key="v2:test:source",
    )

    assert retention["retained_snapshot_ids"] == ["snapshot-0", "snapshot-2"]
    assert retention["pruned_snapshot_ids"] == ["snapshot-1"]
    assert retention["retained_occurrence_mappings"] == 2
    assert retention["retained_distinct_payloads"] == 1
    assert b"".join(
        archive.source_snapshot_json_chunks("snapshot-0")
    ) == expected_json
    assert b"".join(
        archive.source_snapshot_json_chunks("snapshot-2")
    ) == expected_json
    with pytest.raises(ValueError, match="archive_source_snapshot_status_mismatch"):
        archive.verify_source_snapshot("snapshot-1")


def test_connect_migrates_legacy_inline_occurrence_payload_before_transaction(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.sqlite3"
    legacy_payload = canonical_json({"record_id": "legacy-row", "value": 1})
    legacy_hash = hashlib.sha256(legacy_payload.encode("utf-8")).hexdigest()
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE archive_source_snapshot_occurrences (
                stream_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                occurrence_index INTEGER NOT NULL,
                record_id TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(stream_id, snapshot_id, occurrence_index)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO archive_source_snapshot_occurrences(
                stream_id, snapshot_id, occurrence_index, record_id,
                content_sha256, payload_json
            ) VALUES (?, 'legacy-snapshot', 0, 'legacy-row', ?, ?)
            """,
            (STREAM_ID, legacy_hash, legacy_payload),
        )
        connection.commit()

    archive = DurablePaperEvidenceArchive(path, stream_id=STREAM_ID)
    archive.begin_source_snapshot(
        snapshot_id="new-snapshot",
        source_key="v2:test:source",
    )

    with sqlite3.connect(path) as connection:
        occurrence_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(archive_source_snapshot_occurrences)"
            ).fetchall()
        }
        migrated_payload = connection.execute(
            """
            SELECT payload_json
            FROM archive_source_occurrence_payloads
            WHERE stream_id = ? AND content_sha256 = ?
            """,
            (STREAM_ID, legacy_hash),
        ).fetchone()
    assert "payload_json" not in occurrence_columns
    assert migrated_payload == (legacy_payload,)


def test_verified_replacement_readiness_accepts_one_complete_current_proof(
    tmp_path: Path,
) -> None:
    archive = _replacement_proof(tmp_path / "archive.sqlite3")

    readiness = archive.verified_replacement_readiness(source_key=SOURCE_KEY)

    assert readiness["readiness_verified"] is True
    assert readiness["rejection_reasons"] == []
    assert readiness["archive_integrity_verified"] is True
    assert readiness["source_snapshot"]["snapshot_status"] == (
        "COMPLETE_VERIFIED"
    )
    assert readiness["atomic_replace_succeeded"] is True
    assert readiness["redis_readback_digest_verified"] is True
    assert readiness["no_data_loss_proven"] is True
    assert readiness["rollback_reconstruction_verified"] is True


def test_verified_latest_rows_returns_only_rows_covered_by_readiness_tokens(
    tmp_path: Path,
) -> None:
    archive = _replacement_proof(tmp_path / "archive.sqlite3")

    rows, readiness = archive.verified_latest_rows(
        source_key=SOURCE_KEY,
        limit=1,
    )

    assert [row["trainer_feedback_id"] for row in rows] == ["feedback-1"]
    assert readiness["readiness_verified"] is True
    assert readiness["bounded_rows_loaded"] == 1
    assert readiness["bounded_rows_loaded_payload_bytes"] <= readiness[
        "bounded_rows_max_payload_bytes"
    ]
    assert readiness["bounded_rows_snapshot_compare_verified"] is True


def test_verified_latest_rows_rejects_concurrent_archive_commit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive = _replacement_proof(tmp_path / "archive.sqlite3")
    original_readiness = archive.verified_replacement_readiness

    def readiness_then_concurrent_append(*, source_key: str):
        readiness = original_readiness(source_key=source_key)
        archive.append_unique(
            [
                _feedback_candidate(
                    "feedback-race",
                    decision_time="2026-07-18T00:01:00Z",
                    ordinal=2,
                )
            ]
        )
        return readiness

    monkeypatch.setattr(
        archive,
        "verified_replacement_readiness",
        readiness_then_concurrent_append,
    )

    rows, readiness = archive.verified_latest_rows(
        source_key=SOURCE_KEY,
        limit=2,
    )

    assert rows == []
    assert readiness["readiness_verified"] is False
    assert any(
        "durable_archive_latest_rows_chain_compare_failed" in reason
        for reason in readiness["rejection_reasons"]
    )


def test_verified_replacement_readiness_rejects_missing_receipts(
    tmp_path: Path,
) -> None:
    archive = _replacement_proof(
        tmp_path / "archive.sqlite3",
        write_receipts=False,
    )

    readiness = archive.verified_replacement_readiness(source_key=SOURCE_KEY)

    assert readiness["readiness_verified"] is False
    assert "OUTCOME_RECEIPT_MISSING" in readiness["rejection_reasons"]


def test_verified_replacement_readiness_rejects_tampered_receipt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.sqlite3"
    archive = _replacement_proof(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE archive_operation_receipts
            SET receipt_json = replace(
                receipt_json,
                '"hot_cache_replace_verified":true',
                '"hot_cache_replace_verified":false'
            )
            WHERE operation_kind = ?
            """,
            (COUNTERFACTUAL_REPLACEMENT_OUTCOME_KIND,),
        )
        connection.commit()

    readiness = archive.verified_replacement_readiness(source_key=SOURCE_KEY)

    assert readiness["readiness_verified"] is False
    assert any(
        reason.startswith("ARCHIVE_VERIFICATION_ERROR:ValueError:")
        and "archive_operation_receipt_hash_mismatch" in reason
        for reason in readiness["rejection_reasons"]
    )


def test_verified_replacement_readiness_rejects_stale_archive_chain(
    tmp_path: Path,
) -> None:
    archive = _replacement_proof(tmp_path / "archive.sqlite3")
    archive.append_unique(
        [
            _feedback_candidate(
                "feedback-2",
                decision_time="2026-07-18T00:01:00Z",
                ordinal=2,
            )
        ]
    )

    readiness = archive.verified_replacement_readiness(source_key=SOURCE_KEY)

    assert readiness["readiness_verified"] is False
    assert "INTENT_ARCHIVE_CHAIN_STALE" in readiness["rejection_reasons"]
    assert "OUTCOME_ARCHIVE_CHAIN_STALE" in readiness["rejection_reasons"]


def test_verified_replacement_readiness_rejects_incomplete_snapshot(
    tmp_path: Path,
) -> None:
    archive = _replacement_proof(
        tmp_path / "archive.sqlite3",
        complete_snapshot=False,
    )

    readiness = archive.verified_replacement_readiness(source_key=SOURCE_KEY)

    assert readiness["readiness_verified"] is False
    assert "COMPLETE_SOURCE_SNAPSHOT_MISSING" in readiness["rejection_reasons"]


def test_verified_replacement_readiness_rejects_failed_redis_readback(
    tmp_path: Path,
) -> None:
    archive = _replacement_proof(
        tmp_path / "archive.sqlite3",
        readback_verified=False,
    )

    readiness = archive.verified_replacement_readiness(source_key=SOURCE_KEY)

    assert readiness["readiness_verified"] is False
    assert "OUTCOME_REDIS_READBACK_UNVERIFIED" in readiness[
        "rejection_reasons"
    ]
    assert "OUTCOME_READBACK_DIGEST_MISMATCH" in readiness[
        "rejection_reasons"
    ]


def test_operation_receipt_is_chain_bound_and_content_verified(tmp_path: Path) -> None:
    path = tmp_path / "archive.sqlite3"
    archive = DurablePaperEvidenceArchive(path, stream_id=STREAM_ID)
    appended = archive.append_unique(
        [
            _candidate(
                "row-a",
                "2026-07-18T00:00:00Z|row-a",
                value=1,
                observed_at="2026-07-18T01:00:00Z",
            )
        ]
    )
    receipt = {
        "schema_version": "unit_operation_receipt_v1",
        "archive_chain_sha256": appended.archive_chain_sha256,
        "archive_total_unique_rows": appended.total_unique_rows,
        "no_data_loss_proven": True,
    }

    written = archive.append_operation_receipt(
        operation_id="operation-1",
        operation_kind="UNIT_REPLACEMENT_OUTCOME",
        receipt=receipt,
        expected_archive_chain_sha256=appended.archive_chain_sha256,
        expected_total_unique_rows=appended.total_unique_rows,
    )
    loaded = archive.latest_operation_receipt(
        operation_kind="UNIT_REPLACEMENT_OUTCOME"
    )

    assert written["durable"] is True
    assert loaded is not None
    assert loaded["receipt"] == receipt
    assert loaded["receipt_sha256"] == written["receipt_sha256"]

    with pytest.raises(
        ValueError,
        match="archive_operation_receipt_chain_compare_failed",
    ):
        archive.append_operation_receipt(
            operation_id="operation-2",
            operation_kind="UNIT_REPLACEMENT_OUTCOME",
            receipt=receipt,
            expected_archive_chain_sha256="0" * 64,
            expected_total_unique_rows=appended.total_unique_rows,
        )
