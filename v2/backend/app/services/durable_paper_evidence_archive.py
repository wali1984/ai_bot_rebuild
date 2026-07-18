"""Durable, content-verified archive for bounded PAPER Redis working sets.

Redis is used as a bounded hot cache by the callers of this module.  The
SQLite archive is the durable source of truth.  This module contains no
market-admission logic and does not read from or write to an exchange.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARCHIVE_SCHEMA_VERSION = "durable_paper_evidence_archive_v2"


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
                        f"{chain_hash}|{record_id}|{content_hash}".encode("utf-8")
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

    def latest_rows(self, limit: int) -> list[dict[str, Any]]:
        bounded_limit = max(0, int(limit))
        if bounded_limit == 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record_id, semantic_sha256, content_sha256,
                       payload_json, semantic_payload_json
                FROM evidence_records
                WHERE stream_id = ?
                ORDER BY sort_key DESC, record_id DESC
                LIMIT ?
                """,
                (self.stream_id, bounded_limit),
            ).fetchall()
        # The Redis working set is chronological even though SQLite selects the
        # newest rows in descending order to make LIMIT efficient.
        decoded: list[dict[str, Any]] = []
        for row in reversed(rows):
            self._verify_stored_row_hashes(
                record_id=str(row[0]),
                semantic_sha256=str(row[1]),
                content_sha256=str(row[2]),
                payload_json=str(row[3]),
                semantic_payload_json=None if row[4] is None else str(row[4]),
            )
            payload = json.loads(str(row[3]))
            if not isinstance(payload, dict):
                raise ValueError("durable_archive_payload_not_object")
            decoded.append(payload)
        return decoded

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

    def verify_integrity(self) -> dict[str, Any]:
        """Recompute every stored hash, chain, count, and schema marker."""

        expected_chain = hashlib.sha256(b"").hexdigest()
        unique_rows = 0
        total_occurrences = 0
        with self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT record_id, content_sha256, semantic_sha256, payload_json,
                       semantic_payload_json, occurrence_count
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
                    content_sha256=str(row[1]),
                    semantic_sha256=str(row[2]),
                    payload_json=str(row[3]),
                    semantic_payload_json=None if row[4] is None else str(row[4]),
                )
                occurrence_count = int(row[5])
                if occurrence_count < 0:
                    raise ValueError(
                        f"durable_archive_negative_occurrence_count:{record_id}"
                    )
                unique_rows += 1
                total_occurrences += occurrence_count
                expected_chain = hashlib.sha256(
                    f"{expected_chain}|{record_id}|{row[1]}".encode("utf-8")
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
