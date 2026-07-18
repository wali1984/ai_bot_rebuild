"""Crash-safe exact-payload outbox for live canonical finalized 5m labels.

The Binance websocket producer coalesces a close wave in memory, commits the
exact canonical JSON bytes here once, and only then invokes the immutable label
archive.  A process crash after the archive commit but before acknowledgement
is safe: the pending bytes remain and the archive accepts their exact replay as
an idempotent duplicate.

This module owns no sockets, Redis keys, service lifecycle, or exchange action.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    MAX_APPEND_PAYLOAD_BYTES,
    MAX_APPEND_ROWS,
    MAX_CANONICAL_CANDLE_PAYLOAD_BYTES,
    Canonical5mAppendResult,
    DurableCanonical5mLabelArchive,
    canonical_json,
    stable_sha256,
    validate_canonical_finalized_5m_candle,
)

OUTBOX_SCHEMA_VERSION = "canonical_finalized_5m_label_outbox_v2"
DEFAULT_OUTBOX_REL = Path(
    ".local_data/v2_native_trainer/canonical_finalized_5m_label_outbox.sqlite3"
)
# Compatibility name retained for callers; this is the archive's immutable
# bounded append resource limit, never today's adaptive symbol-universe size.
MAX_CLOSE_WAVE_ROWS = MAX_APPEND_ROWS
DEFAULT_MAX_PENDING_ROWS = 8_192
MAX_PENDING_ROWS_LIMIT = 65_536


class Canonical5mLabelOutboxError(RuntimeError):
    """Base fail-closed producer outbox error."""


class Canonical5mLabelOutboxConflictError(Canonical5mLabelOutboxError):
    """A live slot was observed with bytes different from its frozen bytes."""


class Canonical5mLabelOutboxOverflowError(Canonical5mLabelOutboxError):
    """The bounded durable pending set cannot accept another close wave."""


@dataclass(frozen=True)
class OutboxEnqueueResult:
    transaction_id: str
    attempted_rows: int
    inserted_rows: int
    duplicate_rows: int
    pending_rows: int
    batch_sha256: str
    durable_readback_verified: bool


@dataclass(frozen=True)
class OutboxedCanonical5mRow:
    symbol: str
    candle_close_time_ms: int
    candle_id: str
    source_sequence_id: str
    raw_payload_hash: str
    market_fact_sha256: str
    content_sha256: str
    payload_json: str


@dataclass(frozen=True)
class OutboxDeliveryResult:
    attempted_rows: int
    inserted_rows: int
    duplicate_rows: int
    pending_rows: int
    archive_transaction_id: str
    archive_append_receipt_sha256: str


def default_outbox_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[5]
    return root / DEFAULT_OUTBOX_REL


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _sha256_bytes(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _archive_batch_sha256(
    rows: Sequence[OutboxedCanonical5mRow],
) -> str:
    """Reproduce the archive's exact ordered append-batch identity seal."""

    return stable_sha256(
        [
            {
                "symbol": row.symbol,
                "candle_close_time_ms": row.candle_close_time_ms,
                "candle_id": row.candle_id,
                "content_sha256": row.content_sha256,
                "market_fact_sha256": row.market_fact_sha256,
            }
            for row in rows
        ]
    )


def _bounded_limit(value: int, *, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise Canonical5mLabelOutboxError(f"{name}_must_be_positive_integer")
    if value > maximum:
        raise Canonical5mLabelOutboxError(f"{name}_exceeds_limit:{maximum}")
    return value


class Canonical5mLabelOutbox:
    """SQLite exact-byte pending journal with compact delivery receipts."""

    def __init__(
        self,
        path: Path,
        *,
        max_pending_rows: int = DEFAULT_MAX_PENDING_ROWS,
    ) -> None:
        self.path = Path(path)
        self.max_pending_rows = _bounded_limit(
            max_pending_rows,
            name="canonical_5m_outbox_max_pending_rows",
            maximum=MAX_PENDING_ROWS_LIMIT,
        )
        self._initialize()

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=60000")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=60.0)
        self._configure(connection)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _connect_readonly(self) -> sqlite3.Connection:
        uri = self.path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=60.0)
        self._configure(connection)
        connection.execute("PRAGMA query_only=ON")
        return connection

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS canonical_5m_outbox_pending (
                    symbol TEXT NOT NULL,
                    candle_close_time_ms INTEGER NOT NULL,
                    candle_id TEXT NOT NULL UNIQUE,
                    source_sequence_id TEXT NOT NULL,
                    raw_payload_hash TEXT NOT NULL,
                    market_fact_sha256 TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    outbox_transaction_id TEXT NOT NULL,
                    outboxed_at TEXT NOT NULL,
                    PRIMARY KEY(symbol, candle_close_time_ms)
                );
                CREATE INDEX IF NOT EXISTS canonical_5m_outbox_pending_order
                    ON canonical_5m_outbox_pending(
                        candle_close_time_ms, symbol
                    );
                CREATE TABLE IF NOT EXISTS canonical_5m_outbox_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    attempted_rows INTEGER NOT NULL,
                    inserted_rows INTEGER NOT NULL,
                    duplicate_rows INTEGER NOT NULL,
                    batch_sha256 TEXT NOT NULL,
                    committed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS canonical_5m_outbox_deliveries (
                    symbol TEXT NOT NULL,
                    candle_close_time_ms INTEGER NOT NULL,
                    candle_id TEXT NOT NULL UNIQUE,
                    source_sequence_id TEXT NOT NULL,
                    raw_payload_hash TEXT NOT NULL,
                    market_fact_sha256 TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    archive_transaction_id TEXT NOT NULL,
                    archive_batch_sha256 TEXT NOT NULL,
                    archive_append_receipt_sha256 TEXT NOT NULL,
                    delivered_at TEXT NOT NULL,
                    PRIMARY KEY(symbol, candle_close_time_ms)
                );
                CREATE TABLE IF NOT EXISTS canonical_5m_outbox_metadata (
                    metadata_key TEXT PRIMARY KEY,
                    metadata_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS canonical_5m_outbox_pending_no_update
                BEFORE UPDATE ON canonical_5m_outbox_pending
                BEGIN
                    SELECT RAISE(ABORT, 'canonical_5m_outbox_pending_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS canonical_5m_outbox_transaction_no_update
                BEFORE UPDATE ON canonical_5m_outbox_transactions
                BEGIN
                    SELECT RAISE(ABORT, 'canonical_5m_outbox_transaction_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS canonical_5m_outbox_transaction_no_delete
                BEFORE DELETE ON canonical_5m_outbox_transactions
                BEGIN
                    SELECT RAISE(ABORT, 'canonical_5m_outbox_transaction_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS canonical_5m_outbox_delivery_no_update
                BEFORE UPDATE ON canonical_5m_outbox_deliveries
                BEGIN
                    SELECT RAISE(ABORT, 'canonical_5m_outbox_delivery_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS canonical_5m_outbox_delivery_no_delete
                BEFORE DELETE ON canonical_5m_outbox_deliveries
                BEGIN
                    SELECT RAISE(ABORT, 'canonical_5m_outbox_delivery_immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS canonical_5m_outbox_pending_delete_guard
                BEFORE DELETE ON canonical_5m_outbox_pending
                WHEN NOT EXISTS (
                    SELECT 1 FROM canonical_5m_outbox_deliveries delivered
                    WHERE delivered.symbol = OLD.symbol
                      AND delivered.candle_close_time_ms =
                          OLD.candle_close_time_ms
                      AND delivered.candle_id = OLD.candle_id
                      AND delivered.content_sha256 = OLD.content_sha256
                )
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'canonical_5m_outbox_pending_delete_without_delivery'
                    );
                END;
                """
            )
            now = _utc_now()
            for key, value in (
                ("schema_version", OUTBOX_SCHEMA_VERSION),
                ("max_pending_rows", str(self.max_pending_rows)),
                ("integrity_blocker", ""),
            ):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO canonical_5m_outbox_metadata(
                        metadata_key, metadata_value, updated_at
                    ) VALUES (?, ?, ?)
                    """,
                    (key, value, now),
                )
            metadata = {
                str(row["metadata_key"]): str(row["metadata_value"])
                for row in connection.execute(
                    "SELECT metadata_key, metadata_value "
                    "FROM canonical_5m_outbox_metadata"
                )
            }
            if metadata.get("schema_version") != OUTBOX_SCHEMA_VERSION:
                raise Canonical5mLabelOutboxError(
                    "canonical_5m_outbox_schema_version_mismatch"
                )
            if metadata.get("max_pending_rows") != str(self.max_pending_rows):
                raise Canonical5mLabelOutboxError(
                    "canonical_5m_outbox_max_pending_rows_changed"
                )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _require_live_wss_authority(validated: Mapping[str, Any]) -> None:
        payload = validated.get("payload")
        if (
            not isinstance(payload, Mapping)
            or payload.get("source") != "binance_wss"
            or payload.get("is_backfilled") is not False
        ):
            raise Canonical5mLabelOutboxError(
                "canonical_5m_outbox_requires_primary_live_wss_fact"
            )

    @staticmethod
    def _validated_payload_json(payload_json: str) -> dict[str, Any]:
        if not isinstance(payload_json, str) or not payload_json:
            raise Canonical5mLabelOutboxError(
                "canonical_5m_outbox_payload_bytes_missing"
            )
        payload_bytes = len(payload_json.encode("utf-8"))
        if payload_bytes > MAX_CANONICAL_CANDLE_PAYLOAD_BYTES:
            raise Canonical5mLabelOutboxError(
                "canonical_5m_outbox_payload_bytes_exceeded:"
                f"{MAX_CANONICAL_CANDLE_PAYLOAD_BYTES}"
            )
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError) as exc:
            raise Canonical5mLabelOutboxError(
                "canonical_5m_outbox_payload_json_invalid"
            ) from exc
        if not isinstance(payload, Mapping):
            raise Canonical5mLabelOutboxError(
                "canonical_5m_outbox_payload_not_object"
            )
        validated = validate_canonical_finalized_5m_candle(payload)
        Canonical5mLabelOutbox._require_live_wss_authority(validated)
        if validated["payload_json"] != payload_json:
            raise Canonical5mLabelOutboxError(
                "canonical_5m_outbox_payload_not_exact_canonical_json"
            )
        if validated["content_sha256"] != _sha256_bytes(payload_json):
            raise Canonical5mLabelOutboxError(
                "canonical_5m_outbox_payload_sha256_mismatch"
            )
        return validated

    @staticmethod
    def exact_payload_json(payload: Mapping[str, Any]) -> str:
        """Freeze and validate bytes before they enter the memory queue."""

        validated = validate_canonical_finalized_5m_candle(payload)
        Canonical5mLabelOutbox._require_live_wss_authority(validated)
        payload_json = str(validated["payload_json"])
        if len(payload_json.encode("utf-8")) > MAX_CANONICAL_CANDLE_PAYLOAD_BYTES:
            raise Canonical5mLabelOutboxError(
                "canonical_5m_outbox_payload_bytes_exceeded:"
                f"{MAX_CANONICAL_CANDLE_PAYLOAD_BYTES}"
            )
        return payload_json

    def _record_blocker_locked(
        self,
        connection: sqlite3.Connection,
        reason: str,
    ) -> None:
        normalized = str(reason).strip()[:500]
        prior = connection.execute(
            """
            SELECT metadata_value FROM canonical_5m_outbox_metadata
            WHERE metadata_key = 'integrity_blocker'
            """
        ).fetchone()
        if prior is not None and str(prior["metadata_value"]).strip():
            return
        connection.execute(
            """
            INSERT INTO canonical_5m_outbox_metadata(
                metadata_key, metadata_value, updated_at
            ) VALUES ('integrity_blocker', ?, ?)
            ON CONFLICT(metadata_key) DO UPDATE SET
                metadata_value=excluded.metadata_value,
                updated_at=excluded.updated_at
            """,
            (normalized, _utc_now()),
        )

    def record_integrity_blocker(self, reason: str) -> None:
        """Persist the first loss/conflict blocker; no automatic clearing."""

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._record_blocker_locked(connection, reason)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def enqueue_payloads(
        self,
        payload_jsons: Sequence[str],
    ) -> OutboxEnqueueResult:
        if not payload_jsons:
            raise Canonical5mLabelOutboxError(
                "canonical_5m_outbox_close_wave_empty"
            )
        if len(payload_jsons) > MAX_CLOSE_WAVE_ROWS:
            raise Canonical5mLabelOutboxError(
                "canonical_5m_outbox_close_wave_exceeded:"
                f"{MAX_CLOSE_WAVE_ROWS}"
            )
        validated_by_identity: dict[tuple[str, int], dict[str, Any]] = {}
        duplicate_input_rows = 0
        total_payload_bytes = 0
        for payload_json in payload_jsons:
            validated = self._validated_payload_json(payload_json)
            total_payload_bytes += len(payload_json.encode("utf-8"))
            if total_payload_bytes > MAX_APPEND_PAYLOAD_BYTES:
                raise Canonical5mLabelOutboxError(
                    "canonical_5m_outbox_close_wave_payload_bytes_exceeded:"
                    f"{MAX_APPEND_PAYLOAD_BYTES}"
                )
            identity = (
                str(validated["symbol"]),
                int(validated["close_time_ms"]),
            )
            prior = validated_by_identity.get(identity)
            if prior is not None:
                same_primary_source_fact = (
                    prior["candle_id"] == validated["candle_id"]
                    and prior["raw_payload_hash"]
                    == validated["raw_payload_hash"]
                    and prior["market_fact_sha256"]
                    == validated["market_fact_sha256"]
                    and prior["payload"]["source_sequence_id"]
                    == validated["payload"]["source_sequence_id"]
                )
                if not same_primary_source_fact:
                    raise Canonical5mLabelOutboxConflictError(
                        "canonical_5m_outbox_batch_identity_conflict:"
                        f"{identity[0]}:{identity[1]}"
                    )
                # A reconnect can deliver the exact same primary WSS event
                # after the local ingestion clock advances. Freeze the first
                # exact canonical bytes in queue order; the later observation
                # is a duplicate, not a changed market/source fact.
                duplicate_input_rows += 1
                continue
            validated_by_identity[identity] = validated

        rows = sorted(
            validated_by_identity.values(),
            key=lambda row: (int(row["close_time_ms"]), str(row["symbol"])),
        )
        attempted_rows = len(payload_jsons)
        transaction_id = f"canonical_5m_outbox_{uuid.uuid4().hex}"
        batch_sha256 = hashlib.sha256(
            canonical_json(
                [
                    {
                        "symbol": row["symbol"],
                        "candle_close_time_ms": row["close_time_ms"],
                        "content_sha256": row["content_sha256"],
                    }
                    for row in rows
                ]
            ).encode("utf-8")
        ).hexdigest()
        inserted_rows = 0
        duplicate_rows = duplicate_input_rows
        inserted_identities: list[tuple[str, int, str]] = []
        overflow_error: str | None = None
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            pending_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM canonical_5m_outbox_pending"
                ).fetchone()[0]
            )
            candidates: list[dict[str, Any]] = []
            for row in rows:
                identity_args = (row["symbol"], row["close_time_ms"])
                pending = connection.execute(
                    """
                    SELECT candle_id, source_sequence_id, raw_payload_hash,
                           market_fact_sha256, content_sha256, payload_json
                    FROM canonical_5m_outbox_pending
                    WHERE symbol = ? AND candle_close_time_ms = ?
                    """,
                    identity_args,
                ).fetchone()
                delivered = connection.execute(
                    """
                    SELECT candle_id, source_sequence_id, raw_payload_hash,
                           market_fact_sha256, content_sha256
                    FROM canonical_5m_outbox_deliveries
                    WHERE symbol = ? AND candle_close_time_ms = ?
                    """,
                    identity_args,
                ).fetchone()
                existing = pending or delivered
                if existing is not None:
                    same_primary_source_fact = (
                        str(existing["candle_id"]) == row["candle_id"]
                        and str(existing["source_sequence_id"])
                        == row["payload"]["source_sequence_id"]
                        and str(existing["raw_payload_hash"])
                        == row["raw_payload_hash"]
                        and str(existing["market_fact_sha256"])
                        == row["market_fact_sha256"]
                    )
                    exact = same_primary_source_fact
                    if pending is not None:
                        # A network replay of the same primary WSS fact may be
                        # re-ingested later. Keep/retry the first frozen bytes;
                        # never replace them with recomputed provenance clocks.
                        exact = exact and _sha256_bytes(
                            str(pending["payload_json"])
                        ) == str(pending["content_sha256"])
                    if not exact:
                        reason = (
                            "CANONICAL_5M_WSS_SLOT_IDENTITY_CONFLICT:"
                            f"{row['symbol']}:{row['close_time_ms']}"
                        )
                        self._record_blocker_locked(connection, reason)
                        connection.commit()
                        raise Canonical5mLabelOutboxConflictError(reason)
                    duplicate_rows += 1
                    continue
                candidates.append(row)

            if pending_count + len(candidates) > self.max_pending_rows:
                overflow_error = (
                    "CANONICAL_5M_LABEL_OUTBOX_PENDING_OVERFLOW:"
                    f"{pending_count}+{len(candidates)}>{self.max_pending_rows}"
                )
                self._record_blocker_locked(connection, overflow_error)
                connection.commit()
            else:
                outboxed_at = _utc_now()
                for row in candidates:
                    connection.execute(
                        """
                        INSERT INTO canonical_5m_outbox_pending(
                            symbol, candle_close_time_ms, candle_id,
                            source_sequence_id,
                            raw_payload_hash, market_fact_sha256,
                            content_sha256, payload_json,
                            outbox_transaction_id, outboxed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["symbol"],
                            row["close_time_ms"],
                            row["candle_id"],
                            row["payload"]["source_sequence_id"],
                            row["raw_payload_hash"],
                            row["market_fact_sha256"],
                            row["content_sha256"],
                            row["payload_json"],
                            transaction_id,
                            outboxed_at,
                        ),
                    )
                    inserted_rows += 1
                    inserted_identities.append(
                        (
                            str(row["symbol"]),
                            int(row["close_time_ms"]),
                            str(row["content_sha256"]),
                        )
                    )
                connection.execute(
                    """
                    INSERT INTO canonical_5m_outbox_transactions(
                        transaction_id, attempted_rows, inserted_rows,
                        duplicate_rows, batch_sha256, committed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        transaction_id,
                        attempted_rows,
                        inserted_rows,
                        duplicate_rows,
                        batch_sha256,
                        outboxed_at,
                    ),
                )
                connection.commit()
                pending_count += inserted_rows
        except Canonical5mLabelOutboxConflictError:
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if overflow_error is not None:
            raise Canonical5mLabelOutboxOverflowError(overflow_error)

        readback = self._connect_readonly()
        try:
            receipt = readback.execute(
                """
                SELECT attempted_rows, inserted_rows, duplicate_rows,
                       batch_sha256
                FROM canonical_5m_outbox_transactions
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()
            if (
                receipt is None
                or int(receipt["attempted_rows"]) != attempted_rows
                or int(receipt["inserted_rows"]) != inserted_rows
                or int(receipt["duplicate_rows"]) != duplicate_rows
                or str(receipt["batch_sha256"]) != batch_sha256
            ):
                raise Canonical5mLabelOutboxError(
                    "canonical_5m_outbox_transaction_readback_failed"
                )
            for symbol, close_ms, expected_sha in inserted_identities:
                persisted = readback.execute(
                    """
                    SELECT content_sha256 FROM canonical_5m_outbox_pending
                    WHERE symbol = ? AND candle_close_time_ms = ?
                    """,
                    (symbol, close_ms),
                ).fetchone()
                if (
                    persisted is None
                    or str(persisted["content_sha256"]) != expected_sha
                ):
                    raise Canonical5mLabelOutboxError(
                        "canonical_5m_outbox_payload_readback_failed"
                    )
        finally:
            readback.close()
        return OutboxEnqueueResult(
            transaction_id=transaction_id,
            attempted_rows=attempted_rows,
            inserted_rows=inserted_rows,
            duplicate_rows=duplicate_rows,
            pending_rows=pending_count,
            batch_sha256=batch_sha256,
            durable_readback_verified=True,
        )

    def read_pending(self, *, limit: int) -> tuple[OutboxedCanonical5mRow, ...]:
        bounded = _bounded_limit(
            limit,
            name="canonical_5m_outbox_delivery_batch_rows",
            maximum=MAX_CLOSE_WAVE_ROWS,
        )
        connection = self._connect_readonly()
        try:
            records = connection.execute(
                """
                SELECT symbol, candle_close_time_ms, candle_id,
                       source_sequence_id, raw_payload_hash, market_fact_sha256,
                       content_sha256, payload_json
                FROM canonical_5m_outbox_pending
                ORDER BY candle_close_time_ms, symbol
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
        finally:
            connection.close()
        rows: list[OutboxedCanonical5mRow] = []
        for record in records:
            payload_json = str(record["payload_json"])
            validated = self._validated_payload_json(payload_json)
            if (
                str(record["symbol"]) != validated["symbol"]
                or int(record["candle_close_time_ms"])
                != validated["close_time_ms"]
                or str(record["candle_id"]) != validated["candle_id"]
                or str(record["source_sequence_id"])
                != validated["payload"]["source_sequence_id"]
                or str(record["raw_payload_hash"])
                != validated["raw_payload_hash"]
                or str(record["market_fact_sha256"])
                != validated["market_fact_sha256"]
                or str(record["content_sha256"])
                != validated["content_sha256"]
            ):
                raise Canonical5mLabelOutboxError(
                    "canonical_5m_outbox_pending_row_corrupt"
                )
            rows.append(
                OutboxedCanonical5mRow(
                    symbol=str(record["symbol"]),
                    candle_close_time_ms=int(
                        record["candle_close_time_ms"]
                    ),
                    candle_id=str(record["candle_id"]),
                    source_sequence_id=str(record["source_sequence_id"]),
                    raw_payload_hash=str(record["raw_payload_hash"]),
                    market_fact_sha256=str(record["market_fact_sha256"]),
                    content_sha256=str(record["content_sha256"]),
                    payload_json=payload_json,
                )
            )
        return tuple(rows)

    def acknowledge_delivery(
        self,
        rows: Sequence[OutboxedCanonical5mRow],
        result: Canonical5mAppendResult,
    ) -> int:
        expected_batch_sha256 = _archive_batch_sha256(rows)
        if (
            result.transaction_committed is not True
            or result.transaction_readback_verified is not True
            or result.attempted_rows != len(rows)
            or result.inserted_rows + result.duplicate_rows != len(rows)
            or result.batch_sha256 != expected_batch_sha256
            or not _is_sha256(result.append_receipt_sha256)
        ):
            raise Canonical5mLabelOutboxError(
                "canonical_5m_archive_append_result_unverified"
            )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            delivered_at = _utc_now()
            for row in rows:
                pending = connection.execute(
                    """
                    SELECT candle_id, source_sequence_id, raw_payload_hash,
                           market_fact_sha256, content_sha256, payload_json
                    FROM canonical_5m_outbox_pending
                    WHERE symbol = ? AND candle_close_time_ms = ?
                    """,
                    (row.symbol, row.candle_close_time_ms),
                ).fetchone()
                if pending is None:
                    already_delivered = connection.execute(
                        """
                        SELECT candle_id, source_sequence_id, raw_payload_hash,
                               market_fact_sha256, content_sha256
                        FROM canonical_5m_outbox_deliveries
                        WHERE symbol = ? AND candle_close_time_ms = ?
                        """,
                        (row.symbol, row.candle_close_time_ms),
                    ).fetchone()
                    if (
                        already_delivered is not None
                        and str(already_delivered["candle_id"])
                        == row.candle_id
                        and str(already_delivered["source_sequence_id"])
                        == row.source_sequence_id
                        and str(already_delivered["raw_payload_hash"])
                        == row.raw_payload_hash
                        and str(already_delivered["market_fact_sha256"])
                        == row.market_fact_sha256
                        and str(already_delivered["content_sha256"])
                        == row.content_sha256
                    ):
                        continue
                    raise Canonical5mLabelOutboxError(
                        "canonical_5m_outbox_ack_pending_readback_failed"
                    )
                if (
                    str(pending["candle_id"]) != row.candle_id
                    or str(pending["source_sequence_id"])
                    != row.source_sequence_id
                    or str(pending["raw_payload_hash"])
                    != row.raw_payload_hash
                    or str(pending["market_fact_sha256"])
                    != row.market_fact_sha256
                    or str(pending["content_sha256"])
                    != row.content_sha256
                    or str(pending["payload_json"]) != row.payload_json
                ):
                    raise Canonical5mLabelOutboxError(
                        "canonical_5m_outbox_ack_pending_readback_failed"
                    )
                connection.execute(
                    """
                    INSERT INTO canonical_5m_outbox_deliveries(
                        symbol, candle_close_time_ms, candle_id,
                        source_sequence_id,
                        raw_payload_hash, market_fact_sha256,
                        content_sha256, archive_transaction_id,
                        archive_batch_sha256,
                        archive_append_receipt_sha256, delivered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.symbol,
                        row.candle_close_time_ms,
                        row.candle_id,
                        row.source_sequence_id,
                        row.raw_payload_hash,
                        row.market_fact_sha256,
                        row.content_sha256,
                        result.transaction_id,
                        result.batch_sha256,
                        result.append_receipt_sha256,
                        delivered_at,
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM canonical_5m_outbox_pending
                    WHERE symbol = ? AND candle_close_time_ms = ?
                    """,
                    (row.symbol, row.candle_close_time_ms),
                )
            pending_rows = int(
                connection.execute(
                    "SELECT COUNT(*) FROM canonical_5m_outbox_pending"
                ).fetchone()[0]
            )
            connection.commit()
            return pending_rows
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def status_snapshot(self) -> dict[str, Any]:
        connection = self._connect_readonly()
        try:
            metadata = {
                str(row["metadata_key"]): str(row["metadata_value"])
                for row in connection.execute(
                    "SELECT metadata_key, metadata_value "
                    "FROM canonical_5m_outbox_metadata"
                )
            }
            pending_rows = int(
                connection.execute(
                    "SELECT COUNT(*) FROM canonical_5m_outbox_pending"
                ).fetchone()[0]
            )
            delivered_rows = int(
                connection.execute(
                    "SELECT COUNT(*) FROM canonical_5m_outbox_deliveries"
                ).fetchone()[0]
            )
            outbox_transactions = int(
                connection.execute(
                    "SELECT COUNT(*) FROM canonical_5m_outbox_transactions"
                ).fetchone()[0]
            )
        finally:
            connection.close()
        blocker = str(metadata.get("integrity_blocker") or "").strip() or None
        return {
            "schema_version": OUTBOX_SCHEMA_VERSION,
            "outbox_path": str(self.path),
            "pending_rows": pending_rows,
            "delivered_rows": delivered_rows,
            "outbox_transactions": outbox_transactions,
            "max_pending_rows": self.max_pending_rows,
            "integrity_blocker": blocker,
            "integrity_ok": blocker is None,
        }


def deliver_pending_once(
    *,
    outbox: Canonical5mLabelOutbox,
    archive: DurableCanonical5mLabelArchive,
    limit: int = MAX_CLOSE_WAVE_ROWS,
) -> OutboxDeliveryResult | None:
    """Deliver one bounded exact-byte batch after durable outbox readback."""

    rows = outbox.read_pending(limit=limit)
    if not rows:
        return None
    payloads: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row.payload_json)
        if canonical_json(payload) != row.payload_json:
            raise Canonical5mLabelOutboxError(
                "canonical_5m_outbox_retry_bytes_changed"
            )
        payloads.append(payload)
    result = archive.append_candles(payloads)
    pending_rows = outbox.acknowledge_delivery(rows, result)
    return OutboxDeliveryResult(
        attempted_rows=result.attempted_rows,
        inserted_rows=result.inserted_rows,
        duplicate_rows=result.duplicate_rows,
        pending_rows=pending_rows,
        archive_transaction_id=result.transaction_id,
        archive_append_receipt_sha256=result.append_receipt_sha256,
    )
