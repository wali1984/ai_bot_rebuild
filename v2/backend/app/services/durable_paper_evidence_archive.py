"""Durable, content-verified archive for bounded PAPER Redis working sets.

Redis is used as a bounded hot cache by the callers of this module.  The
SQLite archive is the durable source of truth.  This module contains no
market-admission logic and does not read from or write to an exchange.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARCHIVE_SCHEMA_VERSION = "durable_paper_evidence_archive_v2"
# The readiness proof is O(total archive bytes). It is reused only while the
# archive's on-disk content identity is unchanged, so a cache hit is provably
# equivalent to recomputing it. Set to 0 to always recompute.
DURABLE_ARCHIVE_READINESS_PROOF_CACHE = (
    os.getenv("DURABLE_ARCHIVE_READINESS_PROOF_CACHE", "1").strip().lower()
    not in {"0", "false", "no", "off"}
)
_READINESS_PROOF_CACHE: dict[tuple[Any, ...], tuple[tuple[Any, ...], dict[str, Any]]] = {}
_READINESS_PROOF_CACHE_MAX_ENTRIES = 32
COUNTERFACTUAL_ARCHIVE_STREAM_ID = (
    "v2_trainer_feedback_counterfactuals_unique_v1"
)
COUNTERFACTUAL_REPLACEMENT_INTENT_KIND = (
    "COUNTERFACTUAL_HOT_CACHE_REPLACEMENT_INTENT"
)
COUNTERFACTUAL_REPLACEMENT_OUTCOME_KIND = (
    "COUNTERFACTUAL_HOT_CACHE_REPLACEMENT_OUTCOME"
)
COUNTERFACTUAL_REPLACEMENT_INTENT_SCHEMA = (
    "edge_factory_counterfactual_hot_cache_replacement_intent_v1"
)
COUNTERFACTUAL_REPLACEMENT_OUTCOME_SCHEMA = (
    "edge_factory_counterfactual_hot_cache_replacement_outcome_v1"
)
COUNTERFACTUAL_SOURCE_FINGERPRINT_CONTRACT = (
    "REDIS_STRLEN_PLUS_STREAMED_RAW_SHA256_WITH_WATCH_MULTI_EXEC_CAS"
)
REDIS_SOURCE_COMPARE_ENDPOINT_CONTRACT = (
    "SHARED_EXPLICIT_REDIS_URL_FOR_WATCH_STREAM_AND_WRITE"
)
VERIFIED_REPLACEMENT_READINESS_SCHEMA = (
    "durable_paper_evidence_verified_replacement_readiness_v1"
)
COUNTERFACTUAL_VERIFIED_LATEST_ROWS_MAX_BYTES = 64 * 1024 * 1024

ArchivePayloadResolver = Callable[[Mapping[str, Any]], str]


class ArchiveIdentityConflictError(ValueError):
    def __init__(self, record_ids: Iterable[str]) -> None:
        self.record_ids = tuple(str(record_id) for record_id in record_ids)
        super().__init__(
            "durable_archive_identity_conflict:"
            + ",".join(self.record_ids[:20])
        )


def canonical_json(value: Any) -> str:
    """Return strict, deterministic JSON or raise on non-finite numbers."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def counterfactual_archive_identity(payload: Mapping[str, Any]) -> str:
    """Return the one canonical immutable identity for trainer feedback."""

    trainer_id = str(payload.get("trainer_feedback_id") or "").strip()
    counterfactual_id = str(
        payload.get("counterfactual_feedback_id") or ""
    ).strip()
    if trainer_id and counterfactual_id and trainer_id != counterfactual_id:
        raise ValueError("counterfactual_identity_fields_conflict")
    identity = trainer_id or counterfactual_id
    if not identity:
        raise ValueError("counterfactual_explicit_identity_required")
    return identity


def _counterfactual_sort_time(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
        if number <= 0:
            return None
        if number >= 1e12:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.isdigit():
        return _counterfactual_sort_time(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def counterfactual_archive_sort_key(payload: Mapping[str, Any]) -> str:
    """Derive the outcome-blind ordering used by producer and consumers."""

    decision_value = next(
        (
            value
            for value in (
                payload.get("decision_time"),
                payload.get("entry_time"),
                payload.get("feature_cutoff"),
            )
            if value not in (None, "", [], {})
        ),
        None,
    )
    decision_time = _counterfactual_sort_time(decision_value)
    decision_key = (
        decision_time.isoformat(timespec="milliseconds").replace(
            "+00:00",
            "Z",
        )
        if decision_time is not None
        else "0000-00-00T00:00:00.000Z"
    )
    return f"{decision_key}|{counterfactual_archive_identity(payload)}"


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class ArchiveCandidate:
    """One immutable logical evidence record.

    ``semantic_payload`` may omit explicitly operational fields such as the
    time at which an idempotent replay was re-run.  The complete ``payload``
    is still preserved verbatim in canonical JSON.
    """

    record_id: str
    sort_key: str
    payload: Mapping[str, Any]
    semantic_payload: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ArchiveAppendResult:
    attempted_rows: int
    inserted_rows: int
    duplicate_rows: int
    identity_conflicts: int
    identity_conflict_ids: tuple[str, ...]
    total_unique_rows: int
    occurrence_rows_recorded: int
    total_occurrences: int
    archive_chain_sha256: str
    inserted_record_ids: tuple[str, ...]
    queued_hot_cache_deliveries: int
    pending_hot_cache_deliveries: int


class DurablePaperEvidenceArchive:
    """Small SQLite wrapper with immutable record identities and exact counts."""

    def __init__(self, path: Path, *, stream_id: str) -> None:
        self.path = Path(path)
        self.stream_id = str(stream_id)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=60.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=60000")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS evidence_records (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                sort_key TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                semantic_sha256 TEXT NOT NULL,
                semantic_payload_json TEXT,
                payload_json TEXT NOT NULL,
                archived_at TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(stream_id, record_id)
            );
            CREATE INDEX IF NOT EXISTS evidence_records_stream_sort
                ON evidence_records(stream_id, sort_key, record_id);
            CREATE TABLE IF NOT EXISTS archive_metadata (
                stream_id TEXT NOT NULL,
                metadata_key TEXT NOT NULL,
                metadata_value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(stream_id, metadata_key)
            );
            CREATE TABLE IF NOT EXISTS hot_cache_delivery_outbox (
                stream_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                PRIMARY KEY(stream_id, record_id)
            );
            CREATE TABLE IF NOT EXISTS archive_source_snapshots (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                source_key TEXT NOT NULL,
                snapshot_status TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL DEFAULT 0,
                ordered_occurrence_sha256 TEXT NOT NULL,
                observed_source_byte_length INTEGER,
                observed_source_sha256 TEXT,
                canonical_json_byte_length INTEGER,
                canonical_json_sha256 TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(stream_id, snapshot_id)
            );
            CREATE TABLE IF NOT EXISTS archive_source_snapshot_occurrences (
                stream_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                occurrence_index INTEGER NOT NULL,
                record_id TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                PRIMARY KEY(stream_id, snapshot_id, occurrence_index)
            );
            CREATE TABLE IF NOT EXISTS archive_source_occurrence_payloads (
                stream_id TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY(stream_id, content_sha256)
            );
            CREATE INDEX IF NOT EXISTS archive_source_snapshot_occurrence_record
                ON archive_source_snapshot_occurrences(
                    stream_id, snapshot_id, record_id, occurrence_index
                );
            CREATE TABLE IF NOT EXISTS archive_operation_receipts (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                stream_id TEXT NOT NULL,
                operation_id TEXT NOT NULL,
                operation_kind TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                UNIQUE(stream_id, operation_id)
            );
            CREATE INDEX IF NOT EXISTS archive_operation_receipts_kind
                ON archive_operation_receipts(stream_id, operation_kind, sequence);
            """
        )
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(evidence_records)").fetchall()
        }
        if "occurrence_count" not in columns:
            connection.execute(
                "ALTER TABLE evidence_records "
                "ADD COLUMN occurrence_count INTEGER NOT NULL DEFAULT 0"
            )
        if "semantic_payload_json" not in columns:
            connection.execute(
                "ALTER TABLE evidence_records ADD COLUMN semantic_payload_json TEXT"
            )
        occurrence_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(archive_source_snapshot_occurrences)"
            ).fetchall()
        }
        if "payload_json" in occurrence_columns:
            connection.execute(
                """
                INSERT OR IGNORE INTO archive_source_occurrence_payloads(
                    stream_id, content_sha256, payload_json
                )
                SELECT stream_id, content_sha256, payload_json
                FROM archive_source_snapshot_occurrences
                """
            )
            connection.execute(
                """
                ALTER TABLE archive_source_snapshot_occurrences
                DROP COLUMN payload_json
                """
            )
            # Callers commonly start an IMMEDIATE transaction as their first
            # operation.  Seal this one-time table migration first so those
            # transactions cannot fail with "cannot start a transaction within
            # a transaction" on an archive created by the earlier schema.
            connection.commit()
        schema_row = connection.execute(
            """
            SELECT metadata_value
            FROM archive_metadata
            WHERE stream_id = ? AND metadata_key = 'archive_schema_version'
            """,
            (self.stream_id,),
        ).fetchone()
        if schema_row is None:
            self._set_metadata_on_connection(
                connection,
                "archive_schema_version",
                ARCHIVE_SCHEMA_VERSION,
            )
            connection.commit()
        elif str(schema_row[0]) != ARCHIVE_SCHEMA_VERSION:
            connection.close()
            raise ValueError(
                "durable_archive_schema_version_mismatch:"
                f"{schema_row[0]}!={ARCHIVE_SCHEMA_VERSION}"
            )
        return connection

    def append_unique(
        self,
        candidates: Iterable[ArchiveCandidate],
        *,
        count_occurrences: bool = False,
        queue_hot_cache_delivery: bool = False,
    ) -> ArchiveAppendResult:
        attempted = 0
        inserted_ids: list[str] = []
        duplicate_rows = 0
        occurrence_rows_recorded = 0
        queued_hot_cache_deliveries = 0
        conflict_ids: list[str] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            chain_hash = self._metadata_from_connection(
                connection,
                "archive_chain_sha256",
                hashlib.sha256(b"").hexdigest(),
            )
            total_unique_rows = self._metadata_int_from_connection(
                connection,
                "archive_total_unique_rows",
                fallback_query=(
                    "SELECT COUNT(*) FROM evidence_records WHERE stream_id = ?",
                    (self.stream_id,),
                ),
            )
            total_occurrences = self._metadata_int_from_connection(
                connection,
                "archive_total_occurrences",
                fallback_query=(
                    """
                    SELECT COALESCE(SUM(occurrence_count), 0)
                    FROM evidence_records
                    WHERE stream_id = ?
                    """,
                    (self.stream_id,),
                ),
            )
            for candidate in candidates:
                attempted += 1
                record_id = str(candidate.record_id).strip()
                if not record_id:
                    raise ValueError("archive_record_id_required")
                payload_json = canonical_json(dict(candidate.payload))
                content_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
                semantic_payload_json = canonical_json(
                    dict(candidate.semantic_payload)
                    if candidate.semantic_payload is not None
                    else dict(candidate.payload)
                )
                semantic_hash = hashlib.sha256(
                    semantic_payload_json.encode("utf-8")
                ).hexdigest()
                existing = connection.execute(
                    """
                    SELECT semantic_sha256, content_sha256, payload_json,
                           semantic_payload_json
                    FROM evidence_records
                    WHERE stream_id = ? AND record_id = ?
                    """,
                    (self.stream_id, record_id),
                ).fetchone()
                if existing is not None:
                    self._verify_stored_row_hashes(
                        record_id=record_id,
                        semantic_sha256=str(existing[0]),
                        content_sha256=str(existing[1]),
                        payload_json=str(existing[2]),
                        semantic_payload_json=(
                            None if existing[3] is None else str(existing[3])
                        ),
                    )
                    if str(existing[0]) == semantic_hash:
                        duplicate_rows += 1
                        if count_occurrences:
                            connection.execute(
                                """
                                UPDATE evidence_records
                                SET occurrence_count = occurrence_count + 1
                                WHERE stream_id = ? AND record_id = ?
                                """,
                                (self.stream_id, record_id),
                            )
                            occurrence_rows_recorded += 1
                            total_occurrences += 1
                    else:
                        conflict_ids.append(record_id)
                    continue
                connection.execute(
                    """
                    INSERT INTO evidence_records(
                        stream_id, record_id, sort_key, content_sha256,
                        semantic_sha256, semantic_payload_json, payload_json,
                        archived_at, occurrence_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.stream_id,
                        record_id,
                        str(candidate.sort_key),
                        content_hash,
                        semantic_hash,
                        semantic_payload_json,
                        payload_json,
                        utc_now(),
                        1 if count_occurrences else 0,
                    ),
                )
                if queue_hot_cache_delivery:
                    queued = connection.execute(
                        """
                        INSERT OR IGNORE INTO hot_cache_delivery_outbox(
                            stream_id, record_id, queued_at
                        ) VALUES (?, ?, ?)
                        """,
                        (self.stream_id, record_id, utc_now()),
                    )
                    queued_hot_cache_deliveries += max(0, int(queued.rowcount))
                if count_occurrences:
                    occurrence_rows_recorded += 1
                    total_occurrences += 1
                total_unique_rows += 1
                chain_hash = hashlib.sha256(
                    f"{chain_hash}|{record_id}|{content_hash}".encode()
                ).hexdigest()
                inserted_ids.append(record_id)
            self._set_metadata_on_connection(connection, "archive_chain_sha256", chain_hash)
            self._set_metadata_on_connection(
                connection,
                "archive_total_unique_rows",
                str(total_unique_rows),
            )
            self._set_metadata_on_connection(
                connection,
                "archive_total_occurrences",
                str(total_occurrences),
            )
            pending_hot_cache_deliveries = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM hot_cache_delivery_outbox
                    WHERE stream_id = ?
                    """,
                    (self.stream_id,),
                ).fetchone()[0]
            )
            connection.commit()
        return ArchiveAppendResult(
            attempted_rows=attempted,
            inserted_rows=len(inserted_ids),
            duplicate_rows=duplicate_rows,
            identity_conflicts=len(conflict_ids),
            identity_conflict_ids=tuple(conflict_ids[:20]),
            total_unique_rows=total_unique_rows,
            occurrence_rows_recorded=occurrence_rows_recorded,
            total_occurrences=total_occurrences,
            archive_chain_sha256=chain_hash,
            inserted_record_ids=tuple(inserted_ids),
            queued_hot_cache_deliveries=queued_hot_cache_deliveries,
            pending_hot_cache_deliveries=pending_hot_cache_deliveries,
        )

    def append_migration_batch(
        self,
        candidates: Iterable[ArchiveCandidate],
        *,
        expected_cursor: int,
        new_cursor: int,
        observed_redis_length: int,
    ) -> tuple[ArchiveAppendResult, bool]:
        """Archive one legacy Redis slice and advance its cursor atomically.

        Every identity is prevalidated before occurrence counts, records, or
        cursor metadata are mutated.  A conflict, crash, or compare-and-swap
        failure therefore leaves the whole batch unchanged and retryable.
        """

        expected = int(expected_cursor)
        target = int(new_cursor)
        observed_length = int(observed_redis_length)
        if expected < 0 or target < expected or observed_length < target:
            raise ValueError("archive_migration_cursor_bounds_invalid")
        candidate_rows = list(candidates)
        if target != expected + len(candidate_rows):
            raise ValueError("archive_migration_cursor_row_count_mismatch")

        inserted_ids: list[str] = []
        duplicate_rows = 0
        conflicts: list[str] = []
        materials: list[tuple[str, str, str, str, str, str]] = []
        batch_semantics: dict[str, str] = {}
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            actual_cursor = self._metadata_int_from_connection(
                connection,
                "redis_legacy_migration_cursor",
                fallback_query=("SELECT 0", ()),
            )
            migration_complete_before = (
                self._metadata_from_connection(
                    connection,
                    "redis_legacy_migration_complete",
                    "false",
                )
                == "true"
            )
            if migration_complete_before or actual_cursor != expected:
                connection.rollback()
                raise ValueError("archive_migration_cursor_compare_and_swap_failed")

            chain_hash = self._metadata_from_connection(
                connection,
                "archive_chain_sha256",
                hashlib.sha256(b"").hexdigest(),
            )
            total_unique_rows = self._metadata_int_from_connection(
                connection,
                "archive_total_unique_rows",
                fallback_query=(
                    "SELECT COUNT(*) FROM evidence_records WHERE stream_id = ?",
                    (self.stream_id,),
                ),
            )
            total_occurrences = self._metadata_int_from_connection(
                connection,
                "archive_total_occurrences",
                fallback_query=(
                    """
                    SELECT COALESCE(SUM(occurrence_count), 0)
                    FROM evidence_records
                    WHERE stream_id = ?
                    """,
                    (self.stream_id,),
                ),
            )

            for candidate in candidate_rows:
                record_id = str(candidate.record_id).strip()
                if not record_id:
                    connection.rollback()
                    raise ValueError("archive_record_id_required")
                payload_json = canonical_json(dict(candidate.payload))
                content_hash = hashlib.sha256(
                    payload_json.encode("utf-8")
                ).hexdigest()
                semantic_payload_json = canonical_json(
                    dict(candidate.semantic_payload)
                    if candidate.semantic_payload is not None
                    else dict(candidate.payload)
                )
                semantic_hash = hashlib.sha256(
                    semantic_payload_json.encode("utf-8")
                ).hexdigest()
                prior_batch_semantic = batch_semantics.get(record_id)
                if (
                    prior_batch_semantic is not None
                    and prior_batch_semantic != semantic_hash
                ):
                    conflicts.append(record_id)
                batch_semantics.setdefault(record_id, semantic_hash)
                existing = connection.execute(
                    """
                    SELECT semantic_sha256, content_sha256, payload_json,
                           semantic_payload_json
                    FROM evidence_records
                    WHERE stream_id = ? AND record_id = ?
                    """,
                    (self.stream_id, record_id),
                ).fetchone()
                if existing is not None:
                    self._verify_stored_row_hashes(
                        record_id=record_id,
                        semantic_sha256=str(existing[0]),
                        content_sha256=str(existing[1]),
                        payload_json=str(existing[2]),
                        semantic_payload_json=(
                            None if existing[3] is None else str(existing[3])
                        ),
                    )
                    if str(existing[0]) != semantic_hash:
                        conflicts.append(record_id)
                materials.append(
                    (
                        record_id,
                        str(candidate.sort_key),
                        content_hash,
                        semantic_hash,
                        semantic_payload_json,
                        payload_json,
                    )
                )
            if conflicts:
                connection.rollback()
                raise ArchiveIdentityConflictError(dict.fromkeys(conflicts))

            for (
                record_id,
                sort_key,
                content_hash,
                semantic_hash,
                semantic_payload_json,
                payload_json,
            ) in materials:
                existing = connection.execute(
                    """
                    SELECT semantic_sha256
                    FROM evidence_records
                    WHERE stream_id = ? AND record_id = ?
                    """,
                    (self.stream_id, record_id),
                ).fetchone()
                if existing is not None:
                    # Prevalidation proved identity equality.  A duplicate list
                    # occurrence is still counted exactly once.
                    connection.execute(
                        """
                        UPDATE evidence_records
                        SET occurrence_count = occurrence_count + 1
                        WHERE stream_id = ? AND record_id = ?
                        """,
                        (self.stream_id, record_id),
                    )
                    duplicate_rows += 1
                else:
                    connection.execute(
                        """
                        INSERT INTO evidence_records(
                            stream_id, record_id, sort_key, content_sha256,
                            semantic_sha256, semantic_payload_json, payload_json,
                            archived_at, occurrence_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            self.stream_id,
                            record_id,
                            sort_key,
                            content_hash,
                            semantic_hash,
                            semantic_payload_json,
                            payload_json,
                            utc_now(),
                        ),
                    )
                    total_unique_rows += 1
                    inserted_ids.append(record_id)
                    chain_hash = hashlib.sha256(
                        f"{chain_hash}|{record_id}|{content_hash}".encode()
                    ).hexdigest()
                total_occurrences += 1

            migration_complete = target >= observed_length
            self._set_metadata_on_connection(
                connection,
                "archive_chain_sha256",
                chain_hash,
            )
            self._set_metadata_on_connection(
                connection,
                "archive_total_unique_rows",
                str(total_unique_rows),
            )
            self._set_metadata_on_connection(
                connection,
                "archive_total_occurrences",
                str(total_occurrences),
            )
            self._set_metadata_on_connection(
                connection,
                "redis_legacy_migration_cursor",
                str(target),
            )
            self._set_metadata_on_connection(
                connection,
                "redis_legacy_migration_observed_length",
                str(observed_length),
            )
            if migration_complete:
                self._set_metadata_on_connection(
                    connection,
                    "redis_legacy_migration_complete",
                    "true",
                )
            pending_deliveries = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM hot_cache_delivery_outbox
                    WHERE stream_id = ?
                    """,
                    (self.stream_id,),
                ).fetchone()[0]
            )
            connection.commit()

        return (
            ArchiveAppendResult(
                attempted_rows=len(materials),
                inserted_rows=len(inserted_ids),
                duplicate_rows=duplicate_rows,
                identity_conflicts=0,
                identity_conflict_ids=(),
                total_unique_rows=total_unique_rows,
                occurrence_rows_recorded=len(materials),
                total_occurrences=total_occurrences,
                archive_chain_sha256=chain_hash,
                inserted_record_ids=tuple(inserted_ids),
                queued_hot_cache_deliveries=0,
                pending_hot_cache_deliveries=pending_deliveries,
            ),
            migration_complete,
        )

    def begin_source_snapshot(
        self,
        *,
        snapshot_id: str,
        source_key: str,
    ) -> None:
        """Begin an ordered, duplicate-preserving source snapshot.

        The immutable evidence table stores one semantic row per logical
        identity.  That is insufficient for an exact rollback because a legacy
        JSON array may contain repeated identities in a meaningful order.  A
        source snapshot records every occurrence and its complete canonical
        payload before the caller is allowed to replace the source.
        """

        normalized_snapshot_id = str(snapshot_id).strip()
        normalized_source_key = str(source_key).strip()
        if not normalized_snapshot_id:
            raise ValueError("archive_source_snapshot_id_required")
        if not normalized_source_key:
            raise ValueError("archive_source_snapshot_key_required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT source_key, snapshot_status
                FROM archive_source_snapshots
                WHERE stream_id = ? AND snapshot_id = ?
                """,
                (self.stream_id, normalized_snapshot_id),
            ).fetchone()
            if existing is not None:
                connection.rollback()
                raise ValueError(
                    "archive_source_snapshot_identity_already_exists:"
                    f"{normalized_snapshot_id}:{existing[1]}"
                )
            connection.execute(
                """
                INSERT INTO archive_source_snapshots(
                    stream_id, snapshot_id, source_key, snapshot_status,
                    occurrence_count, ordered_occurrence_sha256, created_at
                ) VALUES (?, ?, ?, 'IN_PROGRESS', 0, ?, ?)
                """,
                (
                    self.stream_id,
                    normalized_snapshot_id,
                    normalized_source_key,
                    hashlib.sha256(b"").hexdigest(),
                    utc_now(),
                ),
            )
            connection.commit()

    def append_source_snapshot_occurrences(
        self,
        *,
        snapshot_id: str,
        expected_start_index: int,
        candidates: Iterable[ArchiveCandidate],
    ) -> dict[str, Any]:
        """Append one bounded occurrence batch with a cursor compare-and-swap."""

        normalized_snapshot_id = str(snapshot_id).strip()
        expected_index = int(expected_start_index)
        if not normalized_snapshot_id:
            raise ValueError("archive_source_snapshot_id_required")
        if expected_index < 0:
            raise ValueError("archive_source_snapshot_cursor_invalid")
        candidate_rows = list(candidates)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = connection.execute(
                """
                SELECT snapshot_status, occurrence_count,
                       ordered_occurrence_sha256
                FROM archive_source_snapshots
                WHERE stream_id = ? AND snapshot_id = ?
                """,
                (self.stream_id, normalized_snapshot_id),
            ).fetchone()
            if snapshot is None:
                connection.rollback()
                raise ValueError("archive_source_snapshot_missing")
            if str(snapshot[0]) != "IN_PROGRESS":
                connection.rollback()
                raise ValueError("archive_source_snapshot_not_in_progress")
            actual_index = int(snapshot[1])
            if actual_index != expected_index:
                connection.rollback()
                raise ValueError(
                    "archive_source_snapshot_cursor_compare_and_swap_failed"
                )
            ordered_digest = str(snapshot[2])
            materials: list[tuple[int, str, str, str]] = []
            conflicts: list[str] = []
            for offset, candidate in enumerate(candidate_rows):
                occurrence_index = expected_index + offset
                record_id = str(candidate.record_id).strip()
                if not record_id:
                    connection.rollback()
                    raise ValueError("archive_record_id_required")
                payload_json = canonical_json(dict(candidate.payload))
                content_hash = hashlib.sha256(
                    payload_json.encode("utf-8")
                ).hexdigest()
                semantic_payload_json = canonical_json(
                    dict(candidate.semantic_payload)
                    if candidate.semantic_payload is not None
                    else dict(candidate.payload)
                )
                semantic_hash = hashlib.sha256(
                    semantic_payload_json.encode("utf-8")
                ).hexdigest()
                archived = connection.execute(
                    """
                    SELECT semantic_sha256, content_sha256, payload_json,
                           semantic_payload_json
                    FROM evidence_records
                    WHERE stream_id = ? AND record_id = ?
                    """,
                    (self.stream_id, record_id),
                ).fetchone()
                if archived is None:
                    connection.rollback()
                    raise ValueError(
                        f"archive_source_occurrence_record_missing:{record_id}"
                    )
                self._verify_stored_row_hashes(
                    record_id=record_id,
                    semantic_sha256=str(archived[0]),
                    content_sha256=str(archived[1]),
                    payload_json=str(archived[2]),
                    semantic_payload_json=(
                        None if archived[3] is None else str(archived[3])
                    ),
                )
                if str(archived[0]) != semantic_hash:
                    conflicts.append(record_id)
                materials.append(
                    (occurrence_index, record_id, content_hash, payload_json)
                )
            if conflicts:
                connection.rollback()
                raise ArchiveIdentityConflictError(dict.fromkeys(conflicts))

            for occurrence_index, record_id, content_hash, payload_json in materials:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO archive_source_occurrence_payloads(
                        stream_id, content_sha256, payload_json
                    ) VALUES (?, ?, ?)
                    """,
                    (self.stream_id, content_hash, payload_json),
                )
                stored_payload = connection.execute(
                    """
                    SELECT payload_json
                    FROM archive_source_occurrence_payloads
                    WHERE stream_id = ? AND content_sha256 = ?
                    """,
                    (self.stream_id, content_hash),
                ).fetchone()
                if stored_payload is None or str(stored_payload[0]) != payload_json:
                    connection.rollback()
                    raise ValueError(
                        "archive_source_occurrence_content_identity_conflict:"
                        f"{record_id}"
                    )
                self._verify_occurrence_payload(
                    record_id=record_id,
                    content_sha256=content_hash,
                    payload_json=str(stored_payload[0]),
                )
                connection.execute(
                    """
                    INSERT INTO archive_source_snapshot_occurrences(
                        stream_id, snapshot_id, occurrence_index, record_id,
                        content_sha256
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        self.stream_id,
                        normalized_snapshot_id,
                        occurrence_index,
                        record_id,
                        content_hash,
                    ),
                )
                ordered_digest = hashlib.sha256(
                    (
                        f"{ordered_digest}|{occurrence_index}|{record_id}|"
                        f"{content_hash}"
                    ).encode()
                ).hexdigest()
            next_index = expected_index + len(materials)
            connection.execute(
                """
                UPDATE archive_source_snapshots
                SET occurrence_count = ?, ordered_occurrence_sha256 = ?
                WHERE stream_id = ? AND snapshot_id = ?
                """,
                (
                    next_index,
                    ordered_digest,
                    self.stream_id,
                    normalized_snapshot_id,
                ),
            )
            connection.commit()
        return {
            "snapshot_id": normalized_snapshot_id,
            "appended_occurrences": len(materials),
            "occurrence_count": next_index,
            "ordered_occurrence_sha256": ordered_digest,
        }

    def finalize_source_snapshot(
        self,
        *,
        snapshot_id: str,
        expected_occurrence_count: int,
        expected_ordered_occurrence_sha256: str,
        observed_source_byte_length: int,
        observed_source_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Verify and seal a reconstructable source snapshot atomically."""

        normalized_snapshot_id = str(snapshot_id).strip()
        expected_count = int(expected_occurrence_count)
        source_byte_length = int(observed_source_byte_length)
        if not normalized_snapshot_id:
            raise ValueError("archive_source_snapshot_id_required")
        if expected_count < 0 or source_byte_length < 0:
            raise ValueError("archive_source_snapshot_bounds_invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot = connection.execute(
                """
                SELECT source_key, snapshot_status, occurrence_count,
                       ordered_occurrence_sha256
                FROM archive_source_snapshots
                WHERE stream_id = ? AND snapshot_id = ?
                """,
                (self.stream_id, normalized_snapshot_id),
            ).fetchone()
            if snapshot is None:
                connection.rollback()
                raise ValueError("archive_source_snapshot_missing")
            if str(snapshot[1]) != "IN_PROGRESS":
                connection.rollback()
                raise ValueError("archive_source_snapshot_not_in_progress")
            if int(snapshot[2]) != expected_count:
                connection.rollback()
                raise ValueError("archive_source_snapshot_occurrence_count_mismatch")
            if str(snapshot[3]) != str(expected_ordered_occurrence_sha256):
                connection.rollback()
                raise ValueError("archive_source_snapshot_ordered_digest_mismatch")
            verification = self._verify_source_snapshot_on_connection(
                connection,
                snapshot_id=normalized_snapshot_id,
                expected_status="IN_PROGRESS",
            )
            if verification["occurrence_count"] != expected_count:
                connection.rollback()
                raise ValueError("archive_source_snapshot_occurrence_count_mismatch")
            if (
                verification["ordered_occurrence_sha256"]
                != str(expected_ordered_occurrence_sha256)
            ):
                connection.rollback()
                raise ValueError("archive_source_snapshot_ordered_digest_mismatch")
            source_digest = str(
                observed_source_sha256
                or verification["canonical_json_sha256"]
            ).lower()
            if len(source_digest) != 64 or any(
                character not in "0123456789abcdef"
                for character in source_digest
            ):
                connection.rollback()
                raise ValueError("archive_source_snapshot_source_digest_invalid")
            completed_at = utc_now()
            connection.execute(
                """
                UPDATE archive_source_snapshots
                SET snapshot_status = 'COMPLETE_VERIFIED',
                    observed_source_byte_length = ?,
                    observed_source_sha256 = ?,
                    canonical_json_byte_length = ?,
                    canonical_json_sha256 = ?,
                    completed_at = ?
                WHERE stream_id = ? AND snapshot_id = ?
                """,
                (
                    source_byte_length,
                    source_digest,
                    verification["canonical_json_byte_length"],
                    verification["canonical_json_sha256"],
                    completed_at,
                    self.stream_id,
                    normalized_snapshot_id,
                ),
            )
            connection.commit()
        return {
            **verification,
            "source_key": str(snapshot[0]),
            "snapshot_status": "COMPLETE_VERIFIED",
            "observed_source_byte_length": source_byte_length,
            "observed_source_sha256": source_digest,
            "completed_at": completed_at,
        }

    def abort_source_snapshot(self, snapshot_id: str, *, reason: str) -> None:
        normalized_snapshot_id = str(snapshot_id).strip()
        normalized_reason = str(reason).strip()
        if not normalized_snapshot_id or not normalized_reason:
            raise ValueError("archive_source_snapshot_abort_identity_required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                DELETE FROM archive_source_snapshot_occurrences
                WHERE stream_id = ? AND snapshot_id = ?
                """,
                (self.stream_id, normalized_snapshot_id),
            )
            connection.execute(
                """
                DELETE FROM archive_source_occurrence_payloads
                WHERE stream_id = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM archive_source_snapshot_occurrences AS occurrence
                      WHERE occurrence.stream_id =
                                archive_source_occurrence_payloads.stream_id
                        AND occurrence.content_sha256 =
                                archive_source_occurrence_payloads.content_sha256
                  )
                """,
                (self.stream_id,),
            )
            updated = connection.execute(
                """
                UPDATE archive_source_snapshots
                SET snapshot_status = ?, occurrence_count = 0,
                    ordered_occurrence_sha256 = ?, completed_at = ?
                WHERE stream_id = ? AND snapshot_id = ?
                  AND snapshot_status = 'IN_PROGRESS'
                """,
                (
                    f"ABORTED:{normalized_reason[:160]}",
                    hashlib.sha256(b"").hexdigest(),
                    utc_now(),
                    self.stream_id,
                    normalized_snapshot_id,
                ),
            )
            if int(updated.rowcount) != 1:
                connection.rollback()
                raise ValueError("archive_source_snapshot_abort_state_invalid")
            connection.commit()

    def abort_in_progress_source_snapshots(
        self,
        *,
        source_key: str,
        reason: str,
    ) -> dict[str, Any]:
        """Recover partial snapshots after the exclusive worker lock is held."""

        normalized_source_key = str(source_key).strip()
        normalized_reason = str(reason).strip()
        if not normalized_source_key or not normalized_reason:
            raise ValueError("archive_source_snapshot_recovery_identity_required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            stale_rows = connection.execute(
                """
                SELECT snapshot_id, occurrence_count
                FROM archive_source_snapshots
                WHERE stream_id = ? AND source_key = ?
                  AND snapshot_status = 'IN_PROGRESS'
                ORDER BY sequence ASC
                """,
                (self.stream_id, normalized_source_key),
            ).fetchall()
            stale_ids = [str(row[0]) for row in stale_rows]
            removed_occurrences = sum(int(row[1]) for row in stale_rows)
            for snapshot_id in stale_ids:
                connection.execute(
                    """
                    DELETE FROM archive_source_snapshot_occurrences
                    WHERE stream_id = ? AND snapshot_id = ?
                    """,
                    (self.stream_id, snapshot_id),
                )
                updated = connection.execute(
                    """
                    UPDATE archive_source_snapshots
                    SET snapshot_status = ?, occurrence_count = 0,
                        ordered_occurrence_sha256 = ?, completed_at = ?
                    WHERE stream_id = ? AND snapshot_id = ?
                      AND snapshot_status = 'IN_PROGRESS'
                    """,
                    (
                        f"ABORTED:{normalized_reason[:160]}",
                        hashlib.sha256(b"").hexdigest(),
                        utc_now(),
                        self.stream_id,
                        snapshot_id,
                    ),
                )
                if int(updated.rowcount) != 1:
                    connection.rollback()
                    raise ValueError(
                        "archive_source_snapshot_recovery_state_changed"
                    )
            connection.execute(
                """
                DELETE FROM archive_source_occurrence_payloads
                WHERE stream_id = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM archive_source_snapshot_occurrences AS occurrence
                      WHERE occurrence.stream_id =
                                archive_source_occurrence_payloads.stream_id
                        AND occurrence.content_sha256 =
                                archive_source_occurrence_payloads.content_sha256
                  )
                """,
                (self.stream_id,),
            )
            connection.commit()
        return {
            "source_key": normalized_source_key,
            "recovered_snapshot_ids": stale_ids,
            "recovered_snapshot_count": len(stale_ids),
            "removed_incomplete_occurrence_mappings": removed_occurrences,
            "recovery_reason": normalized_reason,
        }

    def prune_verified_source_snapshots(
        self,
        *,
        source_key: str,
    ) -> dict[str, Any]:
        """Keep exact initial/current rollback maps and prune intermediates.

        Every factory cycle takes a source snapshot.  Retaining every ordered
        occurrence map would grow without bound even though the payload store
        itself is content deduplicated.  Once a replacement has a verified
        outcome, callers may retain the first COMPLETE snapshot (the legacy
        pre-migration source) and the latest COMPLETE snapshot (the current
        rollback point), while preserving headers/digests for intermediate
        audit history.
        """

        normalized_source_key = str(source_key).strip()
        if not normalized_source_key:
            raise ValueError("archive_source_snapshot_key_required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshots = connection.execute(
                """
                SELECT snapshot_id, occurrence_count
                FROM archive_source_snapshots
                WHERE stream_id = ? AND source_key = ?
                  AND snapshot_status = 'COMPLETE_VERIFIED'
                ORDER BY sequence ASC
                """,
                (self.stream_id, normalized_source_key),
            ).fetchall()
            retained_ids = (
                []
                if not snapshots
                else list(dict.fromkeys((str(snapshots[0][0]), str(snapshots[-1][0]))))
            )
            pruned_ids = [
                str(snapshot[0])
                for snapshot in snapshots
                if str(snapshot[0]) not in retained_ids
            ]
            pruned_occurrences = sum(
                int(snapshot[1])
                for snapshot in snapshots
                if str(snapshot[0]) in pruned_ids
            )
            for snapshot_id in pruned_ids:
                connection.execute(
                    """
                    DELETE FROM archive_source_snapshot_occurrences
                    WHERE stream_id = ? AND snapshot_id = ?
                    """,
                    (self.stream_id, snapshot_id),
                )
                updated = connection.execute(
                    """
                    UPDATE archive_source_snapshots
                    SET snapshot_status = 'PRUNED_AFTER_VERIFIED_REPLACEMENT'
                    WHERE stream_id = ? AND snapshot_id = ?
                      AND snapshot_status = 'COMPLETE_VERIFIED'
                    """,
                    (self.stream_id, snapshot_id),
                )
                if int(updated.rowcount) != 1:
                    connection.rollback()
                    raise ValueError(
                        "archive_source_snapshot_prune_state_changed"
                    )
            connection.execute(
                """
                DELETE FROM archive_source_occurrence_payloads
                WHERE stream_id = ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM archive_source_snapshot_occurrences AS occurrence
                      WHERE occurrence.stream_id =
                                archive_source_occurrence_payloads.stream_id
                        AND occurrence.content_sha256 =
                                archive_source_occurrence_payloads.content_sha256
                  )
                """,
                (self.stream_id,),
            )
            retained_occurrences = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM archive_source_snapshot_occurrences
                    WHERE stream_id = ?
                    """,
                    (self.stream_id,),
                ).fetchone()[0]
            )
            retained_payloads = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM archive_source_occurrence_payloads
                    WHERE stream_id = ?
                    """,
                    (self.stream_id,),
                ).fetchone()[0]
            )
            connection.commit()
        return {
            "source_key": normalized_source_key,
            "retained_snapshot_ids": retained_ids,
            "pruned_snapshot_ids": pruned_ids,
            "pruned_snapshot_count": len(pruned_ids),
            "pruned_occurrence_mappings": pruned_occurrences,
            "retained_occurrence_mappings": retained_occurrences,
            "retained_distinct_payloads": retained_payloads,
            "initial_legacy_source_snapshot_retained": bool(retained_ids),
            "latest_source_snapshot_retained": bool(retained_ids),
        }

    def verify_source_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        normalized_snapshot_id = str(snapshot_id).strip()
        if not normalized_snapshot_id:
            raise ValueError("archive_source_snapshot_id_required")
        with self._connect() as connection:
            return self._verified_source_snapshot_on_connection(
                connection,
                snapshot_id=normalized_snapshot_id,
            )

    def _verified_source_snapshot_on_connection(
        self,
        connection: sqlite3.Connection,
        *,
        snapshot_id: str,
    ) -> dict[str, Any]:
        verification = self._verify_source_snapshot_on_connection(
            connection,
            snapshot_id=snapshot_id,
            expected_status="COMPLETE_VERIFIED",
        )
        snapshot = connection.execute(
            """
            SELECT source_key, observed_source_byte_length,
                   observed_source_sha256, canonical_json_byte_length,
                   canonical_json_sha256, completed_at
            FROM archive_source_snapshots
            WHERE stream_id = ? AND snapshot_id = ?
            """,
            (self.stream_id, snapshot_id),
        ).fetchone()
        if snapshot is None:
            raise ValueError("archive_source_snapshot_missing")
        if int(snapshot[3]) != verification["canonical_json_byte_length"]:
            raise ValueError("archive_source_snapshot_canonical_length_mismatch")
        if str(snapshot[4]) != verification["canonical_json_sha256"]:
            raise ValueError("archive_source_snapshot_canonical_digest_mismatch")
        observed_source_digest = str(snapshot[2]).lower()
        if len(observed_source_digest) != 64 or any(
            character not in "0123456789abcdef"
            for character in observed_source_digest
        ):
            raise ValueError("archive_source_snapshot_source_digest_invalid")
        return {
            **verification,
            "source_key": str(snapshot[0]),
            "snapshot_status": "COMPLETE_VERIFIED",
            "observed_source_byte_length": int(snapshot[1]),
            "observed_source_sha256": observed_source_digest,
            "completed_at": str(snapshot[5]),
        }

    def source_snapshot_json_chunks(self, snapshot_id: str) -> Iterator[bytes]:
        """Yield the exact canonical source array in bounded rollback chunks."""

        verification = self.verify_source_snapshot(snapshot_id)
        normalized_snapshot_id = str(snapshot_id).strip()

        def chunks() -> Iterator[bytes]:
            digest = hashlib.sha256()
            byte_length = 0

            def emit(value: bytes) -> bytes:
                nonlocal byte_length
                digest.update(value)
                byte_length += len(value)
                return value

            yield emit(b"[")
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    SELECT occurrence.occurrence_index,
                           occurrence.record_id,
                           occurrence.content_sha256,
                           payload.payload_json
                    FROM archive_source_snapshot_occurrences AS occurrence
                    JOIN archive_source_occurrence_payloads AS payload
                      ON payload.stream_id = occurrence.stream_id
                     AND payload.content_sha256 = occurrence.content_sha256
                    WHERE occurrence.stream_id = ?
                      AND occurrence.snapshot_id = ?
                    ORDER BY occurrence.occurrence_index ASC
                    """,
                    (self.stream_id, normalized_snapshot_id),
                )
                for row_index, row in enumerate(cursor):
                    if int(row[0]) != row_index:
                        raise ValueError(
                            "archive_source_snapshot_occurrence_index_gap"
                        )
                    payload_json = str(row[3])
                    self._verify_occurrence_payload(
                        record_id=str(row[1]),
                        content_sha256=str(row[2]),
                        payload_json=payload_json,
                    )
                    if row_index:
                        yield emit(b",")
                    yield emit(payload_json.encode("utf-8"))
            yield emit(b"]")
            if byte_length != verification["canonical_json_byte_length"]:
                raise ValueError("archive_source_snapshot_rollback_length_mismatch")
            if digest.hexdigest() != verification["canonical_json_sha256"]:
                raise ValueError("archive_source_snapshot_rollback_digest_mismatch")

        return chunks()

    def append_operation_receipt(
        self,
        *,
        operation_id: str,
        operation_kind: str,
        receipt: Mapping[str, Any],
        expected_archive_chain_sha256: str,
        expected_total_unique_rows: int,
    ) -> dict[str, Any]:
        """Durably bind an archive-first mutation intent or outcome receipt."""

        normalized_id = str(operation_id).strip()
        normalized_kind = str(operation_kind).strip()
        if not normalized_id or not normalized_kind:
            raise ValueError("archive_operation_receipt_identity_required")
        receipt_json = canonical_json(dict(receipt))
        receipt_hash = hashlib.sha256(receipt_json.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current_chain = self._metadata_from_connection(
                connection,
                "archive_chain_sha256",
                hashlib.sha256(b"").hexdigest(),
            )
            current_rows = self._metadata_int_from_connection(
                connection,
                "archive_total_unique_rows",
                fallback_query=(
                    "SELECT COUNT(*) FROM evidence_records WHERE stream_id = ?",
                    (self.stream_id,),
                ),
            )
            if current_chain != str(expected_archive_chain_sha256):
                connection.rollback()
                raise ValueError("archive_operation_receipt_chain_compare_failed")
            if current_rows != int(expected_total_unique_rows):
                connection.rollback()
                raise ValueError("archive_operation_receipt_row_count_compare_failed")
            existing = connection.execute(
                """
                SELECT operation_kind, receipt_sha256, receipt_json
                FROM archive_operation_receipts
                WHERE stream_id = ? AND operation_id = ?
                """,
                (self.stream_id, normalized_id),
            ).fetchone()
            inserted = False
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO archive_operation_receipts(
                        stream_id, operation_id, operation_kind,
                        receipt_sha256, receipt_json, recorded_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.stream_id,
                        normalized_id,
                        normalized_kind,
                        receipt_hash,
                        receipt_json,
                        utc_now(),
                    ),
                )
                inserted = True
            else:
                self._verify_operation_receipt(
                    operation_id=normalized_id,
                    operation_kind=str(existing[0]),
                    receipt_sha256=str(existing[1]),
                    receipt_json=str(existing[2]),
                )
                if (
                    str(existing[0]) != normalized_kind
                    or str(existing[1]) != receipt_hash
                    or str(existing[2]) != receipt_json
                ):
                    connection.rollback()
                    raise ValueError("archive_operation_receipt_identity_conflict")
            connection.commit()
        return {
            "operation_id": normalized_id,
            "operation_kind": normalized_kind,
            "receipt_sha256": receipt_hash,
            "inserted": inserted,
            "durable": True,
        }

    def latest_operation_receipt(
        self,
        *,
        operation_kind: str,
    ) -> dict[str, Any] | None:
        normalized_kind = str(operation_kind).strip()
        if not normalized_kind:
            raise ValueError("archive_operation_receipt_kind_required")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT operation_id, operation_kind, receipt_sha256,
                       receipt_json, recorded_at
                FROM archive_operation_receipts
                WHERE stream_id = ? AND operation_kind = ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (self.stream_id, normalized_kind),
            ).fetchone()
        if row is None:
            return None
        return self._decode_operation_receipt_row(row)

    def _decode_operation_receipt_row(
        self,
        row: tuple[Any, ...] | sqlite3.Row,
    ) -> dict[str, Any]:
        self._verify_operation_receipt(
            operation_id=str(row[0]),
            operation_kind=str(row[1]),
            receipt_sha256=str(row[2]),
            receipt_json=str(row[3]),
        )
        payload = json.loads(str(row[3]))
        if not isinstance(payload, dict):
            raise ValueError("archive_operation_receipt_payload_not_object")
        return {
            "operation_id": str(row[0]),
            "operation_kind": str(row[1]),
            "receipt_sha256": str(row[2]),
            "receipt": payload,
            "recorded_at": str(row[4]),
        }

    def _archive_content_fingerprint(self) -> tuple[Any, ...] | None:
        """Identity of the exact on-disk archive content, or None if unknowable.

        The archive runs in WAL mode, so every producer commit changes the
        ``-wal`` sidecar (and a checkpoint changes both files).  Size plus
        nanosecond mtime of the database and its sidecars therefore changes on
        any write.  Returning None forces a full recomputation, so an
        unreadable or unstat-able archive never reuses a proof.
        """

        parts: list[Any] = []
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            try:
                stat = candidate.stat()
            except OSError:
                parts.append((suffix, None))
                continue
            parts.append((suffix, stat.st_size, stat.st_mtime_ns, stat.st_ino))
        return tuple(parts)

    def verified_replacement_readiness(
        self,
        *,
        source_key: str,
        intent_operation_kind: str = COUNTERFACTUAL_REPLACEMENT_INTENT_KIND,
        outcome_operation_kind: str = COUNTERFACTUAL_REPLACEMENT_OUTCOME_KIND,
    ) -> dict[str, Any]:
        """Full proof, reused only while the archive is provably unwritten.

        The underlying proof is O(total archive bytes) and the trainer calls it
        every cycle, which made data assembly -- not gradient work -- dominate
        the trainer's wall clock (measured: ~51.5k 4 KiB page reads per second,
        re-reading the whole archive roughly every 7 seconds, with the GPU idle
        throughout).

        Caching here is integrity-preserving rather than integrity-reducing: the
        proof is returned from cache only when the archive's on-disk content
        identity is byte-for-byte unchanged, in which case recomputing it could
        not produce a different answer.  Any producer commit, checkpoint,
        truncation or replacement changes the fingerprint and forces the full
        proof to run again.  Set
        DURABLE_ARCHIVE_READINESS_PROOF_CACHE=0 to always recompute.
        """

        fingerprint = (
            self._archive_content_fingerprint()
            if DURABLE_ARCHIVE_READINESS_PROOF_CACHE
            else None
        )
        cache_key = (
            str(self.path),
            self.stream_id,
            str(source_key),
            str(intent_operation_kind),
            str(outcome_operation_kind),
        )
        if fingerprint is not None:
            cached = _READINESS_PROOF_CACHE.get(cache_key)
            if cached is not None and cached[0] == fingerprint:
                result = copy.deepcopy(cached[1])
                result["readiness_proof_served_from_cache"] = True
                result["readiness_proof_cache_fingerprint_verified"] = True
                return result
            # Consumers are re-executed as fresh processes, so an in-process
            # cache alone is always cold. The proof is durable evidence bound to
            # an exact archive fingerprint, so it is also persisted on disk and
            # only reused when that fingerprint still matches byte-for-byte.
            persisted = self._load_persisted_proof(cache_key, fingerprint)
            if persisted is not None:
                _READINESS_PROOF_CACHE[cache_key] = (fingerprint, copy.deepcopy(persisted))
                persisted["readiness_proof_served_from_cache"] = True
                persisted["readiness_proof_cache_fingerprint_verified"] = True
                return persisted

        result = self._verified_replacement_readiness_uncached(
            source_key=source_key,
            intent_operation_kind=intent_operation_kind,
            outcome_operation_kind=outcome_operation_kind,
        )

        if fingerprint is not None:
            # Re-read the fingerprint: a commit that landed *while* the proof was
            # being computed must not be cached against the pre-commit identity.
            if self._archive_content_fingerprint() == fingerprint:
                if len(_READINESS_PROOF_CACHE) >= _READINESS_PROOF_CACHE_MAX_ENTRIES:
                    _READINESS_PROOF_CACHE.clear()
                _READINESS_PROOF_CACHE[cache_key] = (fingerprint, copy.deepcopy(result))
                self._persist_proof(cache_key, fingerprint, result)
        result["readiness_proof_served_from_cache"] = False
        return result

    def _proof_cache_path(self) -> Path:
        return Path(str(self.path) + ".readiness_proof_cache.json")

    def _load_persisted_proof(
        self, cache_key: tuple[Any, ...], fingerprint: tuple[Any, ...]
    ) -> dict[str, Any] | None:
        """Return a persisted proof only when its fingerprint still matches."""
        try:
            raw = json.loads(self._proof_cache_path().read_text("utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        if raw.get("cache_key") != list(cache_key):
            return None
        # json round-trips tuples to lists, so compare in a list-normalised form.
        if raw.get("fingerprint") != json.loads(json.dumps(fingerprint)):
            return None
        proof = raw.get("proof")
        return dict(proof) if isinstance(proof, dict) else None

    def _persist_proof(
        self,
        cache_key: tuple[Any, ...],
        fingerprint: tuple[Any, ...],
        proof: dict[str, Any],
    ) -> None:
        """Persist a proof atomically; a failure here is never fatal."""
        path = self._proof_cache_path()
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "cache_key": list(cache_key),
                        "fingerprint": fingerprint,
                        "proof": proof,
                    },
                    sort_keys=True,
                    default=str,
                ),
                "utf-8",
            )
            os.replace(temporary, path)
        except (OSError, TypeError, ValueError):
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _verified_replacement_readiness_uncached(
        self,
        *,
        source_key: str,
        intent_operation_kind: str = COUNTERFACTUAL_REPLACEMENT_INTENT_KIND,
        outcome_operation_kind: str = COUNTERFACTUAL_REPLACEMENT_OUTCOME_KIND,
    ) -> dict[str, Any]:
        """Return one fail-closed proof for bounded archive consumption.

        This is deliberately producer-owned: consumers do not interpret
        receipt payloads or recreate identity/sort rules.  Verification is
        memory bounded but scans the complete immutable archive and the exact
        referenced source snapshot, so its cost is O(total archive bytes plus
        source-snapshot bytes).
        """

        normalized_source_key = str(source_key).strip()
        normalized_intent_kind = str(intent_operation_kind).strip()
        normalized_outcome_kind = str(outcome_operation_kind).strip()
        rejection_reasons: list[str] = []
        result: dict[str, Any] = {
            "schema_version": VERIFIED_REPLACEMENT_READINESS_SCHEMA,
            "stream_id": self.stream_id,
            "source_key": normalized_source_key,
            "readiness_verified": False,
            "rejection_reasons": rejection_reasons,
            "archive_integrity_verified": False,
            "archive_chain_sha256": None,
            "archive_total_unique_rows": None,
            "archive_total_occurrences": None,
            "source_snapshot": None,
            "intent_receipt": None,
            "outcome_receipt": None,
            "atomic_replace_succeeded": False,
            "redis_readback_digest_verified": False,
            "no_data_loss_proven": False,
            "rollback_reconstruction_verified": False,
            "identity_and_sort_policy": None,
            "verification_memory_bound": "STREAMING_ROWS_PLUS_ONE_ROW",
            "verification_cost": (
                "O_TOTAL_ARCHIVE_BYTES_PLUS_SOURCE_SNAPSHOT_BYTES"
            ),
        }

        def reject(reason: str) -> None:
            if reason not in rejection_reasons:
                rejection_reasons.append(reason)

        def matches_int(
            payload: Mapping[str, Any],
            key: str,
            expected: int,
            reason: str,
        ) -> None:
            try:
                actual = int(payload.get(key))
            except (TypeError, ValueError):
                reject(reason)
                return
            if actual != int(expected):
                reject(reason)

        if not normalized_source_key:
            reject("SOURCE_KEY_REQUIRED")
            return result
        if not normalized_intent_kind or not normalized_outcome_kind:
            reject("REPLACEMENT_OPERATION_KIND_REQUIRED")
            return result
        if self.stream_id != COUNTERFACTUAL_ARCHIVE_STREAM_ID:
            reject("CANONICAL_STREAM_IDENTITY_POLICY_UNAVAILABLE")
            return result

        result["identity_and_sort_policy"] = (
            "COUNTERFACTUAL_EXPLICIT_FEEDBACK_ID_AND_DECISION_TIME_V1"
        )
        try:
            with self._connect() as connection:
                # Hold one SQLite read snapshot across archive, receipt, and
                # rollback verification so the proof cannot mix two commits.
                connection.execute("BEGIN")
                integrity = self._verify_integrity_on_connection(
                    connection,
                    identity_resolver=counterfactual_archive_identity,
                    sort_key_resolver=counterfactual_archive_sort_key,
                )
                result.update(
                    {
                        "archive_integrity_verified": True,
                        "archive_chain_sha256": integrity[
                            "archive_chain_sha256"
                        ],
                        "archive_total_unique_rows": integrity[
                            "total_unique_rows"
                        ],
                        "archive_total_occurrences": integrity[
                            "total_occurrences"
                        ],
                        "archive_operation_receipts_verified": integrity[
                            "operation_receipts_verified"
                        ],
                    }
                )

                outcome_row = connection.execute(
                    """
                    SELECT operation_id, operation_kind, receipt_sha256,
                           receipt_json, recorded_at
                    FROM archive_operation_receipts
                    WHERE stream_id = ? AND operation_kind = ?
                    ORDER BY sequence DESC
                    LIMIT 1
                    """,
                    (self.stream_id, normalized_outcome_kind),
                ).fetchone()
                if outcome_row is None:
                    reject("OUTCOME_RECEIPT_MISSING")
                    connection.rollback()
                    return result
                outcome = self._decode_operation_receipt_row(outcome_row)
                outcome_payload = outcome["receipt"]
                result["outcome_receipt"] = {
                    "operation_id": outcome["operation_id"],
                    "operation_kind": outcome["operation_kind"],
                    "receipt_sha256": outcome["receipt_sha256"],
                    "recorded_at": outcome["recorded_at"],
                }

                intent_id = str(
                    outcome_payload.get("intent_operation_id") or ""
                ).strip()
                intent_row = connection.execute(
                    """
                    SELECT operation_id, operation_kind, receipt_sha256,
                           receipt_json, recorded_at
                    FROM archive_operation_receipts
                    WHERE stream_id = ? AND operation_id = ?
                    LIMIT 1
                    """,
                    (self.stream_id, intent_id),
                ).fetchone()
                if not intent_id:
                    reject("OUTCOME_INTENT_OPERATION_ID_MISSING")
                if intent_row is None:
                    reject("LINKED_INTENT_RECEIPT_MISSING")
                    connection.rollback()
                    return result
                intent = self._decode_operation_receipt_row(intent_row)
                intent_payload = intent["receipt"]
                result["intent_receipt"] = {
                    "operation_id": intent["operation_id"],
                    "operation_kind": intent["operation_kind"],
                    "receipt_sha256": intent["receipt_sha256"],
                    "recorded_at": intent["recorded_at"],
                }

                latest_snapshot = connection.execute(
                    """
                    SELECT snapshot_id
                    FROM archive_source_snapshots
                    WHERE stream_id = ? AND source_key = ?
                      AND snapshot_status = 'COMPLETE_VERIFIED'
                    ORDER BY sequence DESC
                    LIMIT 1
                    """,
                    (self.stream_id, normalized_source_key),
                ).fetchone()
                if latest_snapshot is None:
                    reject("COMPLETE_SOURCE_SNAPSHOT_MISSING")
                    connection.rollback()
                    return result
                latest_snapshot_id = str(latest_snapshot[0])
                outcome_snapshot_id = str(
                    outcome_payload.get("source_snapshot_id") or ""
                ).strip()
                if outcome_snapshot_id != latest_snapshot_id:
                    reject("OUTCOME_NOT_BOUND_TO_LATEST_COMPLETE_SNAPSHOT")
                snapshot = self._verified_source_snapshot_on_connection(
                    connection,
                    snapshot_id=latest_snapshot_id,
                )
                result["source_snapshot"] = snapshot
                result["rollback_reconstruction_verified"] = (
                    snapshot.get("rollback_reconstruction_verified") is True
                )

                archive_chain = str(integrity["archive_chain_sha256"])
                archive_rows = int(integrity["total_unique_rows"])
                if intent["operation_kind"] != normalized_intent_kind:
                    reject("LINKED_INTENT_OPERATION_KIND_MISMATCH")
                if (
                    str(intent_payload.get("operation_id") or "")
                    != intent["operation_id"]
                ):
                    reject("INTENT_EMBEDDED_OPERATION_ID_MISMATCH")
                if (
                    str(outcome_payload.get("operation_id") or "")
                    != outcome["operation_id"]
                ):
                    reject("OUTCOME_EMBEDDED_OPERATION_ID_MISMATCH")
                if (
                    intent_payload.get("schema_version")
                    != COUNTERFACTUAL_REPLACEMENT_INTENT_SCHEMA
                ):
                    reject("INTENT_SCHEMA_MISMATCH")
                if (
                    outcome_payload.get("schema_version")
                    != COUNTERFACTUAL_REPLACEMENT_OUTCOME_SCHEMA
                ):
                    reject("OUTCOME_SCHEMA_MISMATCH")
                if (
                    outcome_payload.get("intent_receipt_sha256")
                    != intent["receipt_sha256"]
                ):
                    reject("OUTCOME_INTENT_RECEIPT_HASH_MISMATCH")
                if intent_payload.get("redis_key") != normalized_source_key:
                    reject("INTENT_SOURCE_KEY_MISMATCH")
                if outcome_payload.get("redis_key") != normalized_source_key:
                    reject("OUTCOME_SOURCE_KEY_MISMATCH")

                for receipt_name, payload in (
                    ("INTENT", intent_payload),
                    ("OUTCOME", outcome_payload),
                ):
                    if payload.get("source_snapshot_id") != latest_snapshot_id:
                        reject(f"{receipt_name}_SOURCE_SNAPSHOT_ID_MISMATCH")
                    if payload.get("archive_chain_sha256") != archive_chain:
                        reject(f"{receipt_name}_ARCHIVE_CHAIN_STALE")
                    matches_int(
                        payload,
                        "archive_total_unique_rows",
                        archive_rows,
                        f"{receipt_name}_ARCHIVE_ROW_COUNT_STALE",
                    )
                    matches_int(
                        payload,
                        "source_snapshot_occurrence_count",
                        int(snapshot["occurrence_count"]),
                        f"{receipt_name}_SNAPSHOT_OCCURRENCE_COUNT_MISMATCH",
                    )
                    if (
                        payload.get(
                            "source_snapshot_ordered_occurrence_sha256"
                        )
                        != snapshot["ordered_occurrence_sha256"]
                    ):
                        reject(f"{receipt_name}_SNAPSHOT_ORDER_DIGEST_MISMATCH")
                    if (
                        payload.get("source_snapshot_canonical_json_sha256")
                        != snapshot["canonical_json_sha256"]
                    ):
                        reject(
                            f"{receipt_name}_SNAPSHOT_CANONICAL_DIGEST_MISMATCH"
                        )
                    if (
                        payload.get("source_snapshot_observed_source_sha256")
                        != snapshot["observed_source_sha256"]
                    ):
                        reject(f"{receipt_name}_SNAPSHOT_RAW_DIGEST_MISMATCH")
                    if (
                        payload.get("source_snapshot_fingerprint_contract")
                        != COUNTERFACTUAL_SOURCE_FINGERPRINT_CONTRACT
                    ):
                        reject(f"{receipt_name}_FINGERPRINT_CONTRACT_MISMATCH")
                    if (
                        payload.get(
                            "source_snapshot_rollback_reconstruction_verified"
                        )
                        is not True
                    ):
                        reject(f"{receipt_name}_ROLLBACK_PROOF_MISSING")

                matches_int(
                    intent_payload,
                    "source_snapshot_observed_redis_byte_length",
                    int(snapshot["observed_source_byte_length"]),
                    "INTENT_SNAPSHOT_RAW_LENGTH_MISMATCH",
                )
                matches_int(
                    intent_payload,
                    "source_snapshot_canonical_json_byte_length",
                    int(snapshot["canonical_json_byte_length"]),
                    "INTENT_SNAPSHOT_CANONICAL_LENGTH_MISMATCH",
                )
                if intent_payload.get("source_guard_acquired_before_stream") is not True:
                    reject("INTENT_SOURCE_GUARD_PROOF_MISSING")
                if intent_payload.get("archive_integrity_verified") is not True:
                    reject("INTENT_ARCHIVE_INTEGRITY_PROOF_MISSING")
                if intent_payload.get("all_input_rows_accounted_for") is not True:
                    reject("INTENT_ARCHIVE_INPUT_ACCOUNTING_PROOF_MISSING")
                if intent_payload.get("archive_first_before_redis_replace") is not True:
                    reject("INTENT_ARCHIVE_FIRST_PROOF_MISSING")

                intent_target_digest = str(
                    intent_payload.get("target_hot_ordered_rows_sha256") or ""
                )
                outcome_target_digest = str(
                    outcome_payload.get("target_hot_ordered_rows_sha256") or ""
                )
                if (
                    len(intent_target_digest) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in intent_target_digest.lower()
                    )
                ):
                    reject("INTENT_TARGET_HOT_DIGEST_INVALID")
                if outcome_target_digest != intent_target_digest:
                    reject("OUTCOME_TARGET_HOT_DIGEST_MISMATCH")
                try:
                    target_rows = int(intent_payload.get("target_hot_rows"))
                    target_max_rows = int(
                        intent_payload.get("target_hot_max_rows")
                    )
                except (TypeError, ValueError):
                    target_rows = -1
                    target_max_rows = -1
                    reject("INTENT_TARGET_HOT_ROW_BOUNDS_INVALID")
                if target_rows < 0 or target_max_rows < 1 or target_rows > target_max_rows:
                    reject("INTENT_TARGET_HOT_ROW_BOUNDS_INVALID")
                try:
                    target_payload_bytes = int(
                        intent_payload.get("target_hot_payload_bytes")
                    )
                    target_max_payload_bytes = int(
                        intent_payload.get("target_hot_max_payload_bytes")
                    )
                except (TypeError, ValueError):
                    target_payload_bytes = -1
                    target_max_payload_bytes = -1
                    reject("INTENT_TARGET_HOT_PAYLOAD_BOUNDS_INVALID")
                if (
                    target_payload_bytes < 0
                    or target_max_payload_bytes
                    != COUNTERFACTUAL_VERIFIED_LATEST_ROWS_MAX_BYTES
                    or target_payload_bytes > target_max_payload_bytes
                ):
                    reject("INTENT_TARGET_HOT_PAYLOAD_BOUNDS_INVALID")
                matches_int(
                    outcome_payload,
                    "target_hot_rows",
                    target_rows,
                    "OUTCOME_TARGET_HOT_ROW_COUNT_MISMATCH",
                )
                matches_int(
                    outcome_payload,
                    "target_hot_payload_bytes",
                    target_payload_bytes,
                    "OUTCOME_TARGET_HOT_PAYLOAD_BYTES_MISMATCH",
                )
                matches_int(
                    outcome_payload,
                    "target_hot_max_payload_bytes",
                    target_max_payload_bytes,
                    "OUTCOME_TARGET_HOT_PAYLOAD_BOUND_MISMATCH",
                )
                matches_int(
                    outcome_payload,
                    "hot_cache_readback_rows",
                    target_rows,
                    "OUTCOME_READBACK_ROW_COUNT_MISMATCH",
                )
                if (
                    outcome_payload.get(
                        "hot_cache_readback_ordered_rows_sha256"
                    )
                    != intent_target_digest
                ):
                    reject("OUTCOME_READBACK_DIGEST_MISMATCH")

                atomic_replace = outcome_payload.get("atomic_replace")
                if not isinstance(atomic_replace, Mapping):
                    reject("OUTCOME_ATOMIC_REPLACE_RECEIPT_MISSING")
                    atomic_replace = {}
                required_atomic_true = (
                    "source_guard_supported",
                    "source_guard_acquired",
                    "source_compare_atomic_with_write",
                    "source_compare_performed_immediately_before_write",
                    "source_unchanged_at_replace",
                    "write_attempted",
                    "write_succeeded",
                    "redis_state_after_attempt_known",
                )
                for field in required_atomic_true:
                    if atomic_replace.get(field) is not True:
                        reject(f"OUTCOME_ATOMIC_{field.upper()}_UNPROVEN")
                if atomic_replace.get("source_concurrency_conflict") is not False:
                    reject("OUTCOME_ATOMIC_SOURCE_CONCURRENCY_STATE_INVALID")
                if (
                    atomic_replace.get("source_compare_endpoint_contract")
                    != REDIS_SOURCE_COMPARE_ENDPOINT_CONTRACT
                ):
                    reject("OUTCOME_ATOMIC_SOURCE_ENDPOINT_CONTRACT_MISMATCH")
                matches_int(
                    atomic_replace,
                    "observed_source_byte_length",
                    int(snapshot["observed_source_byte_length"]),
                    "OUTCOME_ATOMIC_SOURCE_LENGTH_MISMATCH",
                )
                if (
                    atomic_replace.get("observed_source_sha256")
                    != snapshot["observed_source_sha256"]
                ):
                    reject("OUTCOME_ATOMIC_SOURCE_DIGEST_MISMATCH")

                result["atomic_replace_succeeded"] = (
                    atomic_replace.get("write_succeeded") is True
                    and atomic_replace.get("source_unchanged_at_replace") is True
                )
                result["redis_readback_digest_verified"] = (
                    outcome_payload.get("hot_cache_readback_digest_verified")
                    is True
                )
                result["no_data_loss_proven"] = (
                    outcome_payload.get("no_data_loss_proven") is True
                )
                if outcome_payload.get("hot_cache_replace_verified") is not True:
                    reject("OUTCOME_HOT_CACHE_REPLACEMENT_UNVERIFIED")
                if not result["redis_readback_digest_verified"]:
                    reject("OUTCOME_REDIS_READBACK_UNVERIFIED")
                if not result["no_data_loss_proven"]:
                    reject("OUTCOME_NO_DATA_LOSS_PROOF_MISSING")
                if (
                    outcome_payload.get("rollback_status")
                    != "NOT_REQUIRED_REPLACEMENT_VERIFIED"
                ):
                    reject("OUTCOME_ROLLBACK_STATUS_NOT_VERIFIED")
                if outcome_payload.get("paper_only") is not True:
                    reject("OUTCOME_PAPER_ONLY_PROOF_MISSING")
                if outcome_payload.get("routes_to_live") is not False:
                    reject("OUTCOME_LIVE_ROUTE_STATE_INVALID")
                if outcome_payload.get("places_real_order") is not False:
                    reject("OUTCOME_REAL_ORDER_STATE_INVALID")
                connection.rollback()
        except (json.JSONDecodeError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
            reject(f"ARCHIVE_VERIFICATION_ERROR:{type(exc).__name__}:{str(exc)[:240]}")

        result["rejection_reasons"] = sorted(rejection_reasons)
        result["readiness_verified"] = not rejection_reasons
        return result

    def verified_latest_rows(
        self,
        *,
        source_key: str,
        limit: int,
        max_payload_bytes: int = COUNTERFACTUAL_VERIFIED_LATEST_ROWS_MAX_BYTES,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Return a bounded tail covered by an unchanged readiness proof.

        The complete proof is computed first.  The bounded read then starts a
        new SQLite read snapshot and compare-and-selects the exact archive
        chain/count, latest outcome receipt, and latest complete source
        snapshot from that proof before selecting any payload.  A producer
        commit in between fails closed instead of returning unproven rows.
        """

        bounded_limit = max(0, int(limit))
        bounded_payload_bytes = max(1, int(max_payload_bytes))
        readiness = self.verified_replacement_readiness(source_key=source_key)
        readiness["bounded_rows_requested"] = bounded_limit
        readiness["bounded_rows_max_payload_bytes"] = bounded_payload_bytes
        readiness["bounded_rows_loaded"] = 0
        readiness["bounded_rows_loaded_payload_bytes"] = 0
        readiness["bounded_rows_snapshot_compare_verified"] = False
        if readiness.get("readiness_verified") is not True:
            return [], readiness
        snapshot = readiness.get("source_snapshot")
        outcome = readiness.get("outcome_receipt")
        if not isinstance(snapshot, Mapping) or not isinstance(outcome, Mapping):
            readiness["readiness_verified"] = False
            readiness["rejection_reasons"] = [
                *readiness.get("rejection_reasons", []),
                "VERIFIED_ROWS_READINESS_TOKEN_MISSING",
            ]
            return [], readiness
        try:
            rows = self.latest_rows(
                bounded_limit,
                identity_resolver=counterfactual_archive_identity,
                sort_key_resolver=counterfactual_archive_sort_key,
                expected_archive_chain_sha256=str(
                    readiness["archive_chain_sha256"]
                ),
                expected_total_unique_rows=int(
                    readiness["archive_total_unique_rows"]
                ),
                expected_replacement_outcome_sha256=str(
                    outcome["receipt_sha256"]
                ),
                expected_source_snapshot_id=str(snapshot["snapshot_id"]),
                expected_source_key=str(source_key),
                max_payload_bytes=bounded_payload_bytes,
            )
        except (json.JSONDecodeError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
            readiness["readiness_verified"] = False
            reasons = list(readiness.get("rejection_reasons", []))
            reasons.append(
                "VERIFIED_ROWS_COMPARE_OR_DECODE_ERROR:"
                f"{type(exc).__name__}:{str(exc)[:240]}"
            )
            readiness["rejection_reasons"] = sorted(set(reasons))
            return [], readiness
        readiness["bounded_rows_loaded"] = len(rows)
        readiness["bounded_rows_loaded_payload_bytes"] = sum(
            len(canonical_json(row).encode("utf-8")) for row in rows
        )
        readiness["bounded_rows_snapshot_compare_verified"] = True
        return rows, readiness

    def pending_hot_cache_deliveries(self, limit: int) -> list[dict[str, Any]]:
        """Return a bounded, stable batch that remains pending until acknowledged.

        SQLite and Redis cannot share one transaction.  The outbox therefore
        provides at-least-once delivery: a crash after ``RPUSH`` but before the
        acknowledgement can duplicate a hot-cache row, which is safe for the
        Guardian consumer because it deduplicates by prediction identity.  A
        crash or Redis failure before ``RPUSH`` cannot lose the row.
        """

        bounded_limit = max(0, int(limit))
        if bounded_limit == 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT outbox.record_id, records.payload_json
                FROM hot_cache_delivery_outbox AS outbox
                JOIN evidence_records AS records
                  ON records.stream_id = outbox.stream_id
                 AND records.record_id = outbox.record_id
                WHERE outbox.stream_id = ?
                ORDER BY records.sort_key ASC, outbox.record_id ASC
                LIMIT ?
                """,
                (self.stream_id, bounded_limit),
            ).fetchall()
        return [
            {"record_id": str(record_id), "payload": json.loads(str(payload_json))}
            for record_id, payload_json in rows
        ]

    def acknowledge_hot_cache_deliveries(self, record_ids: Iterable[str]) -> int:
        """Atomically remove only deliveries confirmed written to Redis."""

        normalized = [str(record_id).strip() for record_id in record_ids]
        normalized = [record_id for record_id in normalized if record_id]
        if not normalized:
            return 0
        deleted = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for record_id in normalized:
                cursor = connection.execute(
                    """
                    DELETE FROM hot_cache_delivery_outbox
                    WHERE stream_id = ? AND record_id = ?
                    """,
                    (self.stream_id, record_id),
                )
                deleted += max(0, int(cursor.rowcount))
            connection.commit()
        return deleted

    def pending_hot_cache_delivery_count(self) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM hot_cache_delivery_outbox
                    WHERE stream_id = ?
                    """,
                    (self.stream_id,),
                ).fetchone()[0]
            )

    def latest_rows(
        self,
        limit: int,
        *,
        identity_resolver: ArchivePayloadResolver | None = None,
        sort_key_resolver: ArchivePayloadResolver | None = None,
        expected_archive_chain_sha256: str | None = None,
        expected_total_unique_rows: int | None = None,
        expected_replacement_outcome_sha256: str | None = None,
        expected_source_snapshot_id: str | None = None,
        expected_source_key: str | None = None,
        max_payload_bytes: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return at most ``limit`` newest verified rows in chronological order.

        Optional resolvers let a stream owner prove that SQLite identity and
        ordering metadata are exact functions of the immutable payload.  The
        query and decode set are both bounded by ``limit``.
        """

        bounded_limit = max(0, int(limit))
        if bounded_limit == 0:
            return []
        payload_byte_limit = (
            None
            if max_payload_bytes is None
            else max(1, int(max_payload_bytes))
        )
        with self._connect() as connection:
            # When readiness tokens are supplied, pin all compare-and-select
            # reads to one SQLite snapshot.  A concurrent producer commit then
            # either predates every check and row or is invisible to all of
            # them; it cannot produce a mixed proof/data view.
            connection.execute("BEGIN")
            if expected_archive_chain_sha256 is not None:
                current_chain = self._metadata_from_connection(
                    connection,
                    "archive_chain_sha256",
                    hashlib.sha256(b"").hexdigest(),
                )
                if current_chain != str(expected_archive_chain_sha256):
                    raise ValueError(
                        "durable_archive_latest_rows_chain_compare_failed"
                    )
            if expected_total_unique_rows is not None:
                current_rows = self._metadata_int_from_connection(
                    connection,
                    "archive_total_unique_rows",
                    fallback_query=(
                        "SELECT COUNT(*) FROM evidence_records WHERE stream_id = ?",
                        (self.stream_id,),
                    ),
                )
                if current_rows != int(expected_total_unique_rows):
                    raise ValueError(
                        "durable_archive_latest_rows_count_compare_failed"
                    )
            if expected_replacement_outcome_sha256 is not None:
                receipt = connection.execute(
                    """
                    SELECT operation_id, operation_kind, receipt_sha256,
                           receipt_json
                    FROM archive_operation_receipts
                    WHERE stream_id = ? AND operation_kind = ?
                    ORDER BY sequence DESC
                    LIMIT 1
                    """,
                    (
                        self.stream_id,
                        COUNTERFACTUAL_REPLACEMENT_OUTCOME_KIND,
                    ),
                ).fetchone()
                if receipt is None:
                    raise ValueError(
                        "durable_archive_latest_rows_outcome_missing"
                    )
                self._verify_operation_receipt(
                    operation_id=str(receipt[0]),
                    operation_kind=str(receipt[1]),
                    receipt_sha256=str(receipt[2]),
                    receipt_json=str(receipt[3]),
                )
                if str(receipt[2]) != str(
                    expected_replacement_outcome_sha256
                ):
                    raise ValueError(
                        "durable_archive_latest_rows_outcome_compare_failed"
                    )
            if expected_source_snapshot_id is not None:
                latest_snapshot = connection.execute(
                    """
                    SELECT snapshot_id
                    FROM archive_source_snapshots
                    WHERE stream_id = ? AND source_key = ?
                      AND snapshot_status = 'COMPLETE_VERIFIED'
                    ORDER BY sequence DESC
                    LIMIT 1
                    """,
                    (self.stream_id, str(expected_source_key or "")),
                ).fetchone()
                if (
                    latest_snapshot is None
                    or str(latest_snapshot[0])
                    != str(expected_source_snapshot_id)
                ):
                    raise ValueError(
                        "durable_archive_latest_rows_snapshot_compare_failed"
                    )
            rows = connection.execute(
                """
                SELECT record_id, sort_key, semantic_sha256, content_sha256,
                       payload_json, semantic_payload_json
                FROM evidence_records
                WHERE stream_id = ?
                ORDER BY sort_key DESC, record_id DESC
                LIMIT ?
                """,
                (self.stream_id, bounded_limit),
            )
            # SQLite selects newest-first for an efficient LIMIT.  Decode one
            # row at a time and stop before the aggregate payload byte bound;
            # reverse only the bounded result for chronological consumption.
            decoded_descending: list[dict[str, Any]] = []
            decoded_payload_bytes = 0
            for row in rows:
                payload_json = str(row[4])
                payload_bytes = len(payload_json.encode("utf-8"))
                if (
                    payload_byte_limit is not None
                    and decoded_payload_bytes + payload_bytes
                    > payload_byte_limit
                ):
                    if not decoded_descending:
                        raise ValueError(
                            "durable_archive_latest_row_exceeds_payload_byte_bound"
                        )
                    break
                self._verify_stored_row_hashes(
                    record_id=str(row[0]),
                    semantic_sha256=str(row[2]),
                    content_sha256=str(row[3]),
                    payload_json=payload_json,
                    semantic_payload_json=(
                        None if row[5] is None else str(row[5])
                    ),
                )
                payload = json.loads(payload_json)
                if not isinstance(payload, dict):
                    raise ValueError("durable_archive_payload_not_object")
                self._verify_payload_bindings(
                    record_id=str(row[0]),
                    sort_key=str(row[1]),
                    payload=payload,
                    identity_resolver=identity_resolver,
                    sort_key_resolver=sort_key_resolver,
                )
                decoded_descending.append(payload)
                decoded_payload_bytes += payload_bytes
        return list(reversed(decoded_descending))

    @staticmethod
    def _verify_payload_bindings(
        *,
        record_id: str,
        sort_key: str,
        payload: Mapping[str, Any],
        identity_resolver: ArchivePayloadResolver | None,
        sort_key_resolver: ArchivePayloadResolver | None,
    ) -> None:
        if identity_resolver is not None:
            resolved_identity = str(identity_resolver(payload))
            if resolved_identity != record_id:
                raise ValueError(
                    f"durable_archive_record_identity_mismatch:{record_id}"
                )
        if sort_key_resolver is not None:
            resolved_sort_key = str(sort_key_resolver(payload))
            if resolved_sort_key != sort_key:
                raise ValueError(
                    f"durable_archive_sort_key_mismatch:{record_id}"
                )

    @staticmethod
    def _verify_stored_row_hashes(
        *,
        record_id: str,
        semantic_sha256: str,
        content_sha256: str,
        payload_json: str,
        semantic_payload_json: str | None,
    ) -> None:
        actual_content = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if actual_content != content_sha256:
            raise ValueError(
                f"durable_archive_content_hash_mismatch:{record_id}"
            )
        if semantic_payload_json is None:
            raise ValueError(
                f"durable_archive_semantic_payload_missing:{record_id}"
            )
        actual_semantic = hashlib.sha256(
            semantic_payload_json.encode("utf-8")
        ).hexdigest()
        if actual_semantic != semantic_sha256:
            raise ValueError(
                f"durable_archive_semantic_hash_mismatch:{record_id}"
            )
        # Parsing plus canonical re-encoding rejects non-finite constants and
        # ensures the stored bytes obey the declared deterministic JSON form.
        payload = json.loads(payload_json)
        semantic_payload = json.loads(semantic_payload_json)
        if canonical_json(payload) != payload_json:
            raise ValueError(f"durable_archive_payload_not_canonical:{record_id}")
        if canonical_json(semantic_payload) != semantic_payload_json:
            raise ValueError(
                f"durable_archive_semantic_payload_not_canonical:{record_id}"
            )

    @staticmethod
    def _verify_occurrence_payload(
        *,
        record_id: str,
        content_sha256: str,
        payload_json: str,
    ) -> None:
        actual_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if actual_hash != content_sha256:
            raise ValueError(
                f"archive_source_occurrence_content_hash_mismatch:{record_id}"
            )
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            raise ValueError("archive_source_occurrence_payload_not_object")
        if canonical_json(payload) != payload_json:
            raise ValueError(
                f"archive_source_occurrence_payload_not_canonical:{record_id}"
            )

    def _verify_source_snapshot_on_connection(
        self,
        connection: sqlite3.Connection,
        *,
        snapshot_id: str,
        expected_status: str,
    ) -> dict[str, Any]:
        snapshot = connection.execute(
            """
            SELECT snapshot_status, occurrence_count,
                   ordered_occurrence_sha256
            FROM archive_source_snapshots
            WHERE stream_id = ? AND snapshot_id = ?
            """,
            (self.stream_id, snapshot_id),
        ).fetchone()
        if snapshot is None:
            raise ValueError("archive_source_snapshot_missing")
        if str(snapshot[0]) != expected_status:
            raise ValueError("archive_source_snapshot_status_mismatch")
        expected_count = int(snapshot[1])
        expected_ordered_digest = str(snapshot[2])
        ordered_digest = hashlib.sha256(b"").hexdigest()
        canonical_digest = hashlib.sha256()
        canonical_length = 0
        occurrence_count = 0

        def consume(value: bytes) -> None:
            nonlocal canonical_length
            canonical_digest.update(value)
            canonical_length += len(value)

        consume(b"[")
        cursor = connection.execute(
            """
            SELECT occurrence.occurrence_index,
                   occurrence.record_id,
                   occurrence.content_sha256,
                   payload.payload_json
            FROM archive_source_snapshot_occurrences AS occurrence
            JOIN archive_source_occurrence_payloads AS payload
              ON payload.stream_id = occurrence.stream_id
             AND payload.content_sha256 = occurrence.content_sha256
            WHERE occurrence.stream_id = ? AND occurrence.snapshot_id = ?
            ORDER BY occurrence.occurrence_index ASC
            """,
            (self.stream_id, snapshot_id),
        )
        for row in cursor:
            occurrence_index = int(row[0])
            record_id = str(row[1])
            content_hash = str(row[2])
            payload_json = str(row[3])
            if occurrence_index != occurrence_count:
                raise ValueError("archive_source_snapshot_occurrence_index_gap")
            self._verify_occurrence_payload(
                record_id=record_id,
                content_sha256=content_hash,
                payload_json=payload_json,
            )
            archived = connection.execute(
                """
                SELECT semantic_sha256, content_sha256, payload_json,
                       semantic_payload_json
                FROM evidence_records
                WHERE stream_id = ? AND record_id = ?
                """,
                (self.stream_id, record_id),
            ).fetchone()
            if archived is None:
                raise ValueError(
                    f"archive_source_occurrence_record_missing:{record_id}"
                )
            self._verify_stored_row_hashes(
                record_id=record_id,
                semantic_sha256=str(archived[0]),
                content_sha256=str(archived[1]),
                payload_json=str(archived[2]),
                semantic_payload_json=(
                    None if archived[3] is None else str(archived[3])
                ),
            )
            occurrence_semantic = json.loads(payload_json)
            archived_semantic = json.loads(str(archived[3]))
            # Operational fields may differ between occurrences, so the generic
            # archive cannot rederive stream-specific semantics here.  The
            # append transaction already required the caller-provided semantic
            # digest to match the immutable record; exact occurrence bytes and
            # their ordered digest remain independently verified.
            if not isinstance(occurrence_semantic, dict) or not isinstance(
                archived_semantic, dict
            ):
                raise ValueError("archive_source_occurrence_semantic_not_object")
            ordered_digest = hashlib.sha256(
                (
                    f"{ordered_digest}|{occurrence_index}|{record_id}|"
                    f"{content_hash}"
                ).encode()
            ).hexdigest()
            if occurrence_count:
                consume(b",")
            consume(payload_json.encode("utf-8"))
            occurrence_count += 1
        consume(b"]")
        if occurrence_count != expected_count:
            raise ValueError("archive_source_snapshot_occurrence_count_mismatch")
        if ordered_digest != expected_ordered_digest:
            raise ValueError("archive_source_snapshot_ordered_digest_mismatch")
        return {
            "snapshot_id": snapshot_id,
            "occurrence_count": occurrence_count,
            "ordered_occurrence_sha256": ordered_digest,
            "canonical_json_byte_length": canonical_length,
            "canonical_json_sha256": canonical_digest.hexdigest(),
            "rollback_reconstruction_verified": True,
        }

    @staticmethod
    def _verify_operation_receipt(
        *,
        operation_id: str,
        operation_kind: str,
        receipt_sha256: str,
        receipt_json: str,
    ) -> None:
        if not operation_id or not operation_kind:
            raise ValueError("archive_operation_receipt_identity_missing")
        actual_hash = hashlib.sha256(receipt_json.encode("utf-8")).hexdigest()
        if actual_hash != receipt_sha256:
            raise ValueError(
                f"archive_operation_receipt_hash_mismatch:{operation_id}"
            )
        payload = json.loads(receipt_json)
        if not isinstance(payload, dict):
            raise ValueError("archive_operation_receipt_payload_not_object")
        if canonical_json(payload) != receipt_json:
            raise ValueError(
                f"archive_operation_receipt_not_canonical:{operation_id}"
            )

    def verify_integrity(
        self,
        *,
        identity_resolver: ArchivePayloadResolver | None = None,
        sort_key_resolver: ArchivePayloadResolver | None = None,
    ) -> dict[str, Any]:
        """Recompute every stored hash, chain, count, and schema marker."""

        with self._connect() as connection:
            return self._verify_integrity_on_connection(
                connection,
                identity_resolver=identity_resolver,
                sort_key_resolver=sort_key_resolver,
            )

    def _verify_integrity_on_connection(
        self,
        connection: sqlite3.Connection,
        *,
        identity_resolver: ArchivePayloadResolver | None,
        sort_key_resolver: ArchivePayloadResolver | None,
    ) -> dict[str, Any]:
        expected_chain = hashlib.sha256(b"").hexdigest()
        unique_rows = 0
        total_occurrences = 0
        cursor = connection.execute(
            """
            SELECT record_id, sort_key, content_sha256, semantic_sha256,
                   payload_json, semantic_payload_json, occurrence_count
            FROM evidence_records
            WHERE stream_id = ?
            ORDER BY sequence ASC
            """,
            (self.stream_id,),
        )
        for row in cursor:
            record_id = str(row[0])
            self._verify_stored_row_hashes(
                record_id=record_id,
                content_sha256=str(row[2]),
                semantic_sha256=str(row[3]),
                payload_json=str(row[4]),
                semantic_payload_json=None if row[5] is None else str(row[5]),
            )
            payload = json.loads(str(row[4]))
            if not isinstance(payload, dict):
                raise ValueError("durable_archive_payload_not_object")
            self._verify_payload_bindings(
                record_id=record_id,
                sort_key=str(row[1]),
                payload=payload,
                identity_resolver=identity_resolver,
                sort_key_resolver=sort_key_resolver,
            )
            occurrence_count = int(row[6])
            if occurrence_count < 0:
                raise ValueError(
                    f"durable_archive_negative_occurrence_count:{record_id}"
                )
            unique_rows += 1
            total_occurrences += occurrence_count
            expected_chain = hashlib.sha256(
                f"{expected_chain}|{record_id}|{row[2]}".encode()
            ).hexdigest()
        stored_chain = self._metadata_from_connection(
            connection,
            "archive_chain_sha256",
            hashlib.sha256(b"").hexdigest(),
        )
        stored_unique = self._metadata_int_from_connection(
            connection,
            "archive_total_unique_rows",
            fallback_query=("SELECT 0", ()),
        )
        stored_occurrences = self._metadata_int_from_connection(
            connection,
            "archive_total_occurrences",
            fallback_query=("SELECT 0", ()),
        )
        operation_receipts = 0
        for receipt in connection.execute(
            """
            SELECT operation_id, operation_kind, receipt_sha256,
                   receipt_json
            FROM archive_operation_receipts
            WHERE stream_id = ?
            ORDER BY sequence ASC
            """,
            (self.stream_id,),
        ):
            self._verify_operation_receipt(
                operation_id=str(receipt[0]),
                operation_kind=str(receipt[1]),
                receipt_sha256=str(receipt[2]),
                receipt_json=str(receipt[3]),
            )
            operation_receipts += 1
        if expected_chain != stored_chain:
            raise ValueError("durable_archive_chain_hash_mismatch")
        if unique_rows != stored_unique:
            raise ValueError("durable_archive_unique_count_mismatch")
        if total_occurrences != stored_occurrences:
            raise ValueError("durable_archive_occurrence_count_mismatch")
        return {
            "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
            "stream_id": self.stream_id,
            "integrity_verified": True,
            "total_unique_rows": unique_rows,
            "total_occurrences": total_occurrences,
            "archive_chain_sha256": expected_chain,
            "operation_receipts_verified": operation_receipts,
        }

    def total_unique_rows(self) -> int:
        with self._connect() as connection:
            return self._metadata_int_from_connection(
                connection,
                "archive_total_unique_rows",
                fallback_query=(
                    "SELECT COUNT(*) FROM evidence_records WHERE stream_id = ?",
                    (self.stream_id,),
                ),
            )

    def metadata(self, key: str, default: str = "") -> str:
        with self._connect() as connection:
            return self._metadata_from_connection(connection, key, default)

    def set_metadata(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._set_metadata_on_connection(connection, key, value)
            connection.commit()

    def _metadata_from_connection(
        self,
        connection: sqlite3.Connection,
        key: str,
        default: str,
    ) -> str:
        row = connection.execute(
            """
            SELECT metadata_value
            FROM archive_metadata
            WHERE stream_id = ? AND metadata_key = ?
            """,
            (self.stream_id, key),
        ).fetchone()
        return default if row is None else str(row[0])

    def _metadata_int_from_connection(
        self,
        connection: sqlite3.Connection,
        key: str,
        *,
        fallback_query: tuple[str, tuple[Any, ...]],
    ) -> int:
        value = self._metadata_from_connection(connection, key, "")
        if value:
            try:
                return int(value)
            except ValueError:
                pass
        query, parameters = fallback_query
        return int(connection.execute(query, parameters).fetchone()[0])

    def _set_metadata_on_connection(
        self,
        connection: sqlite3.Connection,
        key: str,
        value: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO archive_metadata(stream_id, metadata_key, metadata_value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(stream_id, metadata_key) DO UPDATE SET
                metadata_value = excluded.metadata_value,
                updated_at = excluded.updated_at
            """,
            (self.stream_id, str(key), str(value), utc_now()),
        )


def ordered_rows_sha256(rows: Iterable[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        encoded = canonical_json(dict(row)).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()
