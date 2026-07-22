"""Crash-safe local journal for externally witnessed profiled-training heads.

The external witness client intentionally owns no durable state.  This module
supplies the caller-side durability boundary required before that client may
perform network I/O:

* exact event and request bytes are durably placed in immutable SHA-256 CAS;
* an append-only SQLite journal commits ``APPEND_PREPARED`` before dispatch;
* ambiguous delivery is recovered by replaying the exact request and
  idempotency key;
* exact signed receipt and signed-head envelopes are reverified and durably
  anchored by a second append-only ``HEAD_ANCHORED`` transition;
* every transition is globally ordered and SHA-256 chained;
* one authentic single-writer capability pins the database path and inode;
* optimizer, checkpoint, model, prediction, paper, live, order, execution, and
  runtime authority remain false throughout this journal.

This is not an optimizer admission journal and it never contacts a witness on
its own.  A production caller must explicitly invoke the client's dispatch
method only after :meth:`persist_prepared_append` returns successfully.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FeatureSnapshotLedgerError,
    FeatureSnapshotWriterLease,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_client_v1 import (
    MAX_PROFILED_WITNESS_WIRE_BYTES,
    PROFILED_WITNESS_COMPARE_APPEND_REQUEST_DOMAIN,
    PROFILED_WITNESS_COMPARE_APPEND_REQUEST_V1_SCHEMA_VERSION,
    PinnedProfiledTrainingExternalWitnessClientV1,
    ProfiledTrainingExternalWitnessClientV1Error,
    ProfiledTrainingExternalWitnessPreparedAppendV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    MAX_PROFILED_OBSERVATION_HEAD_EVENT_BYTES,
    PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256,
    PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
    LocalProfiledTrainingObservationHeadCandidateV1,
    ProfiledTrainingObservationExternalWitnessAppendReceiptV1,
)

PROFILED_WITNESS_JOURNAL_V1_SCHEMA_VERSION: Final = "profiled_training_external_witness_journal_v1"
PROFILED_WITNESS_JOURNAL_OPERATION_V1_SCHEMA_VERSION: Final = (
    "profiled_training_external_witness_journal_operation_v1"
)
PROFILED_WITNESS_JOURNAL_TRANSITION_V1_SCHEMA_VERSION: Final = (
    "profiled_training_external_witness_journal_transition_v1"
)
PROFILED_WITNESS_JOURNAL_RECORD_V1_SCHEMA_VERSION: Final = (
    "profiled_training_external_witness_journal_record_v1"
)
PROFILED_WITNESS_JOURNAL_INTEGRITY_REPORT_V1_SCHEMA_VERSION: Final = (
    "profiled_training_external_witness_journal_integrity_report_v1"
)

PROFILED_WITNESS_JOURNAL_APPEND_PREPARED: Final = "APPEND_PREPARED"
PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED: Final = "HEAD_ANCHORED"
PROFILED_WITNESS_JOURNAL_OPERATION_ID_DOMAIN: Final = (
    "v2/native-trainer/profiled-external-witness-journal-operation/v1"
)
PROFILED_WITNESS_JOURNAL_TRANSITION_DOMAIN: Final = (
    "v2/native-trainer/profiled-external-witness-journal-transition/v1"
)
PROFILED_WITNESS_JOURNAL_GENESIS_TRANSITION_SHA256: Final = (
    "7023c3c077beb935ec59bc815bf0e96757796c1ec34469379b19b586107e0411"
)

# SQLite identity and resource-safety limits only.  They do not select markets,
# samples, regimes, leverage, margin, risk, or optimizer parameters.
PROFILED_WITNESS_JOURNAL_APPLICATION_ID: Final = 0x57544A31  # ASCII ``WTJ1``.
PROFILED_WITNESS_JOURNAL_USER_VERSION: Final = 1
MAX_PROFILED_WITNESS_JOURNAL_TRANSITIONS: Final = 100_000
MAX_PROFILED_WITNESS_JOURNAL_MATERIAL_BYTES: Final = 512 * 1024
SQLITE_BUSY_TIMEOUT_MILLISECONDS: Final = 60_000

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_RECORD_TOKEN = object()

_AUTHORITY_FIELDS: Final = (
    "external_monotonic_manifest_head_verified",
    "full_consumption_external_ack_verified",
    "optimizer_admission_authorized",
    "checkpoint_write_authorized",
    "model_write_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "order_submission_authorized",
    "execution_authorized",
    "runtime_wired",
)

_REQUEST_FIELDS: Final = {
    "schema_version",
    "request_domain",
    "witness_id",
    "witness_public_key_sha256",
    "namespace",
    "expected_sequence",
    "expected_event_sha256",
    "event_sha256",
    "event_byte_count",
    "event_base64",
    "idempotency_key",
    *_AUTHORITY_FIELDS,
}


class ProfiledTrainingExternalWitnessJournalV1Error(RuntimeError):
    """The durable witness journal failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledTrainingExternalWitnessJournalV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _sha256(value: object, *, reason: str) -> str:
    if not _valid_sha256(value):
        _fail(reason)
    return cast(str, value)


def _identifier(value: object, *, reason: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail(reason)
    return value


def _positive_integer(
    value: object,
    *,
    reason: str,
    allow_zero: bool = False,
) -> int:
    if type(value) is not int or value < (0 if allow_zero else 1) or value > 2**63 - 1:
        _fail(reason)
    return value


def _clock(value: object, *, reason: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != value:
        _fail(reason)
    return value


def _journal_wall_clock_now() -> datetime:
    return datetime.now(UTC)


def _journaled_at() -> str:
    return (
        _journal_wall_clock_now()
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _canonical_json_bytes(
    value: object,
    *,
    reason: str,
    maximum_bytes: int = MAX_PROFILED_WITNESS_JOURNAL_MATERIAL_BYTES,
) -> bytes:
    if type(maximum_bytes) is not int or maximum_bytes <= 0:
        _fail(reason)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ProfiledTrainingExternalWitnessJournalV1Error(reason) from exc
    if not encoded or len(encoded) > maximum_bytes:
        _fail(reason)
    return encoded


def _strict_json(
    raw: bytes,
    *,
    reason: str,
    maximum_bytes: int = MAX_PROFILED_WITNESS_JOURNAL_MATERIAL_BYTES,
) -> dict[str, Any]:
    if (
        type(raw) is not bytes
        or not raw
        or type(maximum_bytes) is not int
        or maximum_bytes <= 0
        or len(raw) > maximum_bytes
    ):
        _fail(reason)

    def reject_constant(value: str) -> NoReturn:
        _fail(f"{reason}:NONFINITE:{value}")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if type(key) is not str or key in result:
                _fail(f"{reason}:DUPLICATE_OR_INVALID_KEY")
            result[key] = value
        return result

    try:
        decoded = raw.decode("ascii")
        value = json.loads(
            decoded,
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProfiledTrainingExternalWitnessJournalV1Error(reason) from exc
    if (
        type(value) is not dict
        or _canonical_json_bytes(
            value,
            reason=reason,
            maximum_bytes=maximum_bytes,
        )
        != raw
    ):
        _fail(reason)
    return cast(dict[str, Any], value)


def _absolute_path(value: Path, *, reason: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute() or ".." in value.parts:
        _fail(reason)
    return value


def _authority_false_from_prepared(
    prepared: ProfiledTrainingExternalWitnessPreparedAppendV1,
) -> dict[str, bool]:
    result = {name: getattr(prepared, name) for name in _AUTHORITY_FIELDS}
    if any(type(value) is not bool or value for value in result.values()):
        _fail("PROFILED_WITNESS_JOURNAL_AUTHORITY_MUST_REMAIN_FALSE")
    return cast(dict[str, bool], result)


def _sqlite_integer_false(row: sqlite3.Row, name: str) -> bool:
    value = row[name]
    return type(value) is int and value == 0


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        os.fsync(descriptor)
    except OSError as exc:
        raise ProfiledTrainingExternalWitnessJournalV1Error(
            "PROFILED_WITNESS_JOURNAL_DIRECTORY_FSYNC_FAILED"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


_SCHEMA_DDL: Final = (
    """
    CREATE TABLE witness_journal_metadata (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version TEXT NOT NULL,
        genesis_transition_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE witness_journal_operations (
        operation_id TEXT PRIMARY KEY,
        witness_id TEXT NOT NULL,
        witness_public_key_sha256 TEXT NOT NULL,
        namespace TEXT NOT NULL,
        manifest_id TEXT NOT NULL,
        observation_time TEXT NOT NULL,
        head_revision INTEGER NOT NULL CHECK (head_revision > 0),
        candidate_id TEXT NOT NULL,
        candidate_event_sha256 TEXT NOT NULL,
        candidate_event_byte_count INTEGER NOT NULL CHECK (candidate_event_byte_count > 0),
        previous_head_event_sha256 TEXT NOT NULL,
        previous_completion_candidate_sha256 TEXT NOT NULL,
        local_staging_store_root TEXT NOT NULL,
        manifest_auth_key_id TEXT NOT NULL,
        head_auth_key_id TEXT NOT NULL,
        epoch_auth_key_id TEXT NOT NULL,
        epoch_auth_key_commitment_sha256 TEXT NOT NULL,
        allowed_consumer_lane TEXT NOT NULL,
        expected_sequence INTEGER NOT NULL CHECK (expected_sequence >= 0),
        expected_event_sha256 TEXT NOT NULL,
        event_cas_sha256 TEXT NOT NULL,
        event_byte_count INTEGER NOT NULL CHECK (event_byte_count > 0),
        request_cas_sha256 TEXT NOT NULL,
        request_byte_count INTEGER NOT NULL CHECK (request_byte_count > 0),
        request_sha256 TEXT NOT NULL UNIQUE,
        idempotency_key TEXT NOT NULL UNIQUE,
        prior_signed_head_envelope_sha256 TEXT,
        prior_signed_head_envelope_byte_count INTEGER,
        external_monotonic_manifest_head_verified INTEGER NOT NULL
            CHECK (external_monotonic_manifest_head_verified = 0),
        full_consumption_external_ack_verified INTEGER NOT NULL
            CHECK (full_consumption_external_ack_verified = 0),
        optimizer_admission_authorized INTEGER NOT NULL CHECK (optimizer_admission_authorized = 0),
        checkpoint_write_authorized INTEGER NOT NULL CHECK (checkpoint_write_authorized = 0),
        model_write_authorized INTEGER NOT NULL CHECK (model_write_authorized = 0),
        prediction_authorized INTEGER NOT NULL CHECK (prediction_authorized = 0),
        paper_trading_authorized INTEGER NOT NULL CHECK (paper_trading_authorized = 0),
        live_execution_authorized INTEGER NOT NULL CHECK (live_execution_authorized = 0),
        order_submission_authorized INTEGER NOT NULL CHECK (order_submission_authorized = 0),
        execution_authorized INTEGER NOT NULL CHECK (execution_authorized = 0),
        runtime_wired INTEGER NOT NULL CHECK (runtime_wired = 0),
        operation_material_json TEXT NOT NULL,
        CHECK (
            (expected_sequence = 0
             AND prior_signed_head_envelope_sha256 IS NULL
             AND prior_signed_head_envelope_byte_count IS NULL)
            OR
            (expected_sequence > 0
             AND prior_signed_head_envelope_sha256 IS NOT NULL
             AND prior_signed_head_envelope_byte_count > 0)
        )
    ) STRICT
    """,
    """
    CREATE TABLE witness_journal_transitions (
        transition_sequence INTEGER PRIMARY KEY CHECK (transition_sequence > 0),
        previous_transition_sha256 TEXT NOT NULL,
        transition_sha256 TEXT NOT NULL UNIQUE,
        operation_id TEXT NOT NULL REFERENCES witness_journal_operations(operation_id),
        state TEXT NOT NULL CHECK (state IN ('APPEND_PREPARED', 'HEAD_ANCHORED')),
        receipt_sequence INTEGER,
        receipt_previous_event_sha256 TEXT,
        receipt_event_sha256 TEXT,
        receipt_accepted_at TEXT,
        signed_receipt_envelope_sha256 TEXT,
        signed_receipt_envelope_byte_count INTEGER,
        signed_head_envelope_sha256 TEXT,
        signed_head_envelope_byte_count INTEGER,
        journaled_at TEXT NOT NULL,
        transition_material_json TEXT NOT NULL,
        UNIQUE (operation_id, state),
        CHECK (
            (state = 'APPEND_PREPARED'
             AND receipt_sequence IS NULL
             AND receipt_previous_event_sha256 IS NULL
             AND receipt_event_sha256 IS NULL
             AND receipt_accepted_at IS NULL
             AND signed_receipt_envelope_sha256 IS NULL
             AND signed_receipt_envelope_byte_count IS NULL
             AND signed_head_envelope_sha256 IS NULL
             AND signed_head_envelope_byte_count IS NULL)
            OR
            (state = 'HEAD_ANCHORED'
             AND receipt_sequence > 0
             AND receipt_previous_event_sha256 IS NOT NULL
             AND receipt_event_sha256 IS NOT NULL
             AND receipt_accepted_at IS NOT NULL
             AND signed_receipt_envelope_sha256 IS NOT NULL
             AND signed_receipt_envelope_byte_count > 0
             AND signed_head_envelope_sha256 IS NOT NULL
             AND signed_head_envelope_byte_count > 0)
        )
    ) STRICT
    """,
    """
    CREATE INDEX witness_journal_operations_namespace_idx
    ON witness_journal_operations(namespace, expected_sequence)
    """,
    """
    CREATE INDEX witness_journal_transitions_operation_idx
    ON witness_journal_transitions(operation_id, transition_sequence)
    """,
    """
    CREATE TRIGGER witness_journal_metadata_update_forbidden
    BEFORE UPDATE ON witness_journal_metadata
    BEGIN SELECT RAISE(ABORT, 'witness_journal_metadata_update_forbidden'); END
    """,
    """
    CREATE TRIGGER witness_journal_metadata_delete_forbidden
    BEFORE DELETE ON witness_journal_metadata
    BEGIN SELECT RAISE(ABORT, 'witness_journal_metadata_delete_forbidden'); END
    """,
    """
    CREATE TRIGGER witness_journal_operations_update_forbidden
    BEFORE UPDATE ON witness_journal_operations
    BEGIN SELECT RAISE(ABORT, 'witness_journal_operations_update_forbidden'); END
    """,
    """
    CREATE TRIGGER witness_journal_operations_delete_forbidden
    BEFORE DELETE ON witness_journal_operations
    BEGIN SELECT RAISE(ABORT, 'witness_journal_operations_delete_forbidden'); END
    """,
    """
    CREATE TRIGGER witness_journal_transitions_update_forbidden
    BEFORE UPDATE ON witness_journal_transitions
    BEGIN SELECT RAISE(ABORT, 'witness_journal_transitions_update_forbidden'); END
    """,
    """
    CREATE TRIGGER witness_journal_transitions_delete_forbidden
    BEFORE DELETE ON witness_journal_transitions
    BEGIN SELECT RAISE(ABORT, 'witness_journal_transitions_delete_forbidden'); END
    """,
    """
    CREATE TRIGGER witness_journal_one_pending_per_namespace
    BEFORE INSERT ON witness_journal_operations
    WHEN EXISTS (
        SELECT 1
        FROM witness_journal_operations AS operation
        WHERE operation.namespace = NEW.namespace
          AND NOT EXISTS (
              SELECT 1
              FROM witness_journal_transitions AS transition
              WHERE transition.operation_id = operation.operation_id
                AND transition.state = 'HEAD_ANCHORED'
          )
    )
    BEGIN SELECT RAISE(ABORT, 'witness_journal_namespace_pending_append_exists'); END
    """,
    """
    CREATE TRIGGER witness_journal_transition_chain_required
    BEFORE INSERT ON witness_journal_transitions
    WHEN NEW.transition_sequence != COALESCE(
             (SELECT MAX(transition_sequence) + 1 FROM witness_journal_transitions),
             1
         )
      OR NEW.previous_transition_sha256 != COALESCE(
             (SELECT transition_sha256
              FROM witness_journal_transitions
              ORDER BY transition_sequence DESC
              LIMIT 1),
             '7023c3c077beb935ec59bc815bf0e96757796c1ec34469379b19b586107e0411'
         )
    BEGIN SELECT RAISE(ABORT, 'witness_journal_transition_chain_invalid'); END
    """,
    """
    CREATE TRIGGER witness_journal_transition_lifecycle_required
    BEFORE INSERT ON witness_journal_transitions
    WHEN (
        NEW.state = 'APPEND_PREPARED'
        AND EXISTS (
            SELECT 1 FROM witness_journal_transitions
            WHERE operation_id = NEW.operation_id
        )
    ) OR (
        NEW.state = 'HEAD_ANCHORED'
        AND (
            NOT EXISTS (
                SELECT 1 FROM witness_journal_transitions
                WHERE operation_id = NEW.operation_id
                  AND state = 'APPEND_PREPARED'
            )
            OR EXISTS (
                SELECT 1 FROM witness_journal_transitions
                WHERE operation_id = NEW.operation_id
                  AND state = 'HEAD_ANCHORED'
            )
        )
    )
    BEGIN SELECT RAISE(ABORT, 'witness_journal_transition_lifecycle_invalid'); END
    """,
    """
    CREATE TRIGGER witness_journal_anchor_binding_required
    BEFORE INSERT ON witness_journal_transitions
    WHEN NEW.state = 'HEAD_ANCHORED'
      AND NOT EXISTS (
          SELECT 1
          FROM witness_journal_operations AS operation
          WHERE operation.operation_id = NEW.operation_id
            AND NEW.receipt_sequence = operation.expected_sequence + 1
            AND NEW.receipt_previous_event_sha256 = operation.expected_event_sha256
            AND NEW.receipt_event_sha256 = operation.event_cas_sha256
      )
    BEGIN SELECT RAISE(ABORT, 'witness_journal_anchor_binding_invalid'); END
    """,
)


def _schema_signature(connection: sqlite3.Connection) -> tuple[tuple[str, str, str, str], ...]:
    rows = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_schema
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    return tuple((str(row[0]), str(row[1]), str(row[2]), str(row[3])) for row in rows)


@lru_cache(maxsize=1)
def _expected_schema_signature() -> tuple[tuple[str, str, str, str], ...]:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        for statement in _SCHEMA_DDL:
            connection.execute(statement)
        return _schema_signature(connection)
    finally:
        connection.close()


def _operation_id(material_json: bytes) -> str:
    return hashlib.sha256(
        PROFILED_WITNESS_JOURNAL_OPERATION_ID_DOMAIN.encode("ascii") + b"\0" + material_json
    ).hexdigest()


def _transition_sha256(material_json: bytes) -> str:
    return hashlib.sha256(
        PROFILED_WITNESS_JOURNAL_TRANSITION_DOMAIN.encode("ascii") + b"\0" + material_json
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ProfiledTrainingExternalWitnessJournalRecordV1:
    """Reauthenticated durable append state returned to the runtime caller."""

    schema_version: str
    operation_id: str
    state: str
    manifest_id: str
    observation_time: str
    head_revision: int
    candidate_id: str
    candidate_event_sha256: str
    candidate_event_byte_count: int
    previous_completion_candidate_sha256: str
    local_staging_store_root: Path
    allowed_consumer_lane: str
    prepared_transition_sequence: int
    prepared_transition_sha256: str
    anchored_transition_sequence: int | None
    anchored_transition_sha256: str | None
    prepared: ProfiledTrainingExternalWitnessPreparedAppendV1 = field(repr=False)
    append_receipt: ProfiledTrainingObservationExternalWitnessAppendReceiptV1 | None = field(
        default=None, repr=False
    )
    signed_head_envelope_bytes: bytes | None = field(default=None, repr=False)
    _construction_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        anchored = self.state == PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED
        if (
            self._construction_token is not _RECORD_TOKEN
            or self.schema_version != PROFILED_WITNESS_JOURNAL_RECORD_V1_SCHEMA_VERSION
            or not _valid_sha256(self.operation_id)
            or self.state
            not in {
                PROFILED_WITNESS_JOURNAL_APPEND_PREPARED,
                PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED,
            }
            or not _valid_sha256(self.manifest_id)
            or not _valid_sha256(self.candidate_id)
            or not _valid_sha256(self.candidate_event_sha256)
            or not _valid_sha256(self.previous_completion_candidate_sha256)
            or type(self.head_revision) is not int
            or self.head_revision <= 0
            or type(self.candidate_event_byte_count) is not int
            or self.candidate_event_byte_count <= 0
            or not isinstance(self.local_staging_store_root, Path)
            or not self.local_staging_store_root.is_absolute()
            or ".." in self.local_staging_store_root.parts
            or _IDENTIFIER_RE.fullmatch(self.allowed_consumer_lane) is None
            or type(self.prepared) is not ProfiledTrainingExternalWitnessPreparedAppendV1
            or self.prepared.event_sha256 != self.candidate_event_sha256
            or self.prepared.event_byte_count != self.candidate_event_byte_count
            or type(self.prepared_transition_sequence) is not int
            or self.prepared_transition_sequence <= 0
            or not _valid_sha256(self.prepared_transition_sha256)
            or anchored
            != (
                self.anchored_transition_sequence is not None
                and self.anchored_transition_sha256 is not None
                and self.append_receipt is not None
                and self.signed_head_envelope_bytes is not None
            )
            or (
                anchored
                and (
                    type(self.anchored_transition_sequence) is not int
                    or self.anchored_transition_sequence <= self.prepared_transition_sequence
                    or not _valid_sha256(self.anchored_transition_sha256)
                    or type(self.signed_head_envelope_bytes) is not bytes
                    or not self.signed_head_envelope_bytes
                )
            )
        ):
            _fail("PROFILED_WITNESS_JOURNAL_RECORD_CONTRACT_INVALID")
        _clock(
            self.observation_time,
            reason="PROFILED_WITNESS_JOURNAL_OBSERVATION_TIME_INVALID",
        )


@dataclass(frozen=True, slots=True)
class ProfiledTrainingExternalWitnessJournalIntegrityReportV1:
    schema_version: str
    operation_count: int
    transition_count: int
    prepared_count: int
    anchored_count: int
    pending_count: int
    namespace_count: int
    terminal_transition_sha256: str
    optimizer_admission_authorized: bool = False
    checkpoint_write_authorized: bool = False
    model_write_authorized: bool = False
    prediction_authorized: bool = False
    paper_trading_authorized: bool = False
    live_execution_authorized: bool = False
    order_submission_authorized: bool = False
    execution_authorized: bool = False
    runtime_wired: bool = False

    def __post_init__(self) -> None:
        if (
            self.schema_version != PROFILED_WITNESS_JOURNAL_INTEGRITY_REPORT_V1_SCHEMA_VERSION
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.operation_count,
                    self.transition_count,
                    self.prepared_count,
                    self.anchored_count,
                    self.pending_count,
                    self.namespace_count,
                )
            )
            or self.prepared_count != self.operation_count
            or self.anchored_count + self.pending_count != self.operation_count
            or self.transition_count != self.prepared_count + self.anchored_count
            or not _valid_sha256(self.terminal_transition_sha256)
            or any(
                type(value) is not bool or value
                for value in (
                    self.optimizer_admission_authorized,
                    self.checkpoint_write_authorized,
                    self.model_write_authorized,
                    self.prediction_authorized,
                    self.paper_trading_authorized,
                    self.live_execution_authorized,
                    self.order_submission_authorized,
                    self.execution_authorized,
                    self.runtime_wired,
                )
            )
        ):
            _fail("PROFILED_WITNESS_JOURNAL_INTEGRITY_REPORT_INVALID")


class ProfiledTrainingExternalWitnessJournalV1:
    """Append-only prepared/anchored journal with immutable CAS evidence."""

    __slots__ = ("_cas", "_path", "_writer_lease")

    def __init__(
        self,
        path: Path,
        *,
        immutable_store: ImmutableSourcePayloadStore,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> None:
        self._path = _absolute_path(
            path,
            reason="PROFILED_WITNESS_JOURNAL_PATH_INVALID",
        )
        if type(immutable_store) is not ImmutableSourcePayloadStore:
            _fail("PROFILED_WITNESS_JOURNAL_IMMUTABLE_STORE_EXACT_TYPE_REQUIRED")
        self._cas = immutable_store
        if writer_lease is not None:
            try:
                FeatureSnapshotWriterLease.require_exact(writer_lease, self._path)
            except FeatureSnapshotLedgerError as exc:
                raise ProfiledTrainingExternalWitnessJournalV1Error(
                    f"PROFILED_WITNESS_JOURNAL_WRITER_LEASE_INVALID:{exc}"
                ) from exc
        self._writer_lease = writer_lease

    @property
    def path(self) -> Path:
        return self._path

    @property
    def immutable_store(self) -> ImmutableSourcePayloadStore:
        return self._cas

    @contextmanager
    def writer_lease(
        self,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> Iterator[FeatureSnapshotWriterLease]:
        held = writer_lease if writer_lease is not None else self._writer_lease
        acquired_here = held is None
        try:
            if held is None:
                held = FeatureSnapshotWriterLease.acquire(self._path)
            FeatureSnapshotWriterLease.require_exact(held, self._path)
            yield held
            FeatureSnapshotWriterLease.require_exact(held, self._path)
        except FeatureSnapshotLedgerError as exc:
            raise ProfiledTrainingExternalWitnessJournalV1Error(
                f"PROFILED_WITNESS_JOURNAL_WRITER_LEASE_INVALID:{exc}"
            ) from exc
        finally:
            if acquired_here and held is not None:
                held.release()

    def _open_connection(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> sqlite3.Connection:
        try:
            held = FeatureSnapshotWriterLease.require_exact(writer_lease, self._path)
            held.bind_ledger_inode_for_write(self._path)
            connection = sqlite3.connect(
                str(self._path),
                timeout=60.0,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            FeatureSnapshotWriterLease.require_exact(held, self._path)
            connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MILLISECONDS}")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA trusted_schema=OFF")
            mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
            if mode != "wal":
                _fail("PROFILED_WITNESS_JOURNAL_WAL_REQUIRED")
            connection.execute("PRAGMA synchronous=FULL")
            if int(connection.execute("PRAGMA synchronous").fetchone()[0]) != 2:
                _fail("PROFILED_WITNESS_JOURNAL_SYNCHRONOUS_FULL_REQUIRED")
            if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
                _fail("PROFILED_WITNESS_JOURNAL_FOREIGN_KEYS_REQUIRED")
            FeatureSnapshotWriterLease.require_exact(held, self._path)
            return connection
        except ProfiledTrainingExternalWitnessJournalV1Error:
            if "connection" in locals():
                connection.close()
            raise
        except (FeatureSnapshotLedgerError, sqlite3.Error) as exc:
            if "connection" in locals():
                connection.close()
            raise ProfiledTrainingExternalWitnessJournalV1Error(
                "PROFILED_WITNESS_JOURNAL_CONNECTION_FAILED"
            ) from exc

    def _close_connection(
        self,
        connection: sqlite3.Connection,
        *,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> None:
        close_error: BaseException | None = None
        try:
            connection.close()
        except BaseException as exc:
            close_error = exc
        try:
            FeatureSnapshotWriterLease.require_exact(writer_lease, self._path)
        except FeatureSnapshotLedgerError as exc:
            if close_error is None:
                close_error = exc
        if close_error is not None:
            raise ProfiledTrainingExternalWitnessJournalV1Error(
                "PROFILED_WITNESS_JOURNAL_CONNECTION_CLOSE_FAILED"
            ) from close_error

    def _initialize_or_verify_schema(self, connection: sqlite3.Connection) -> bool:
        signature = _schema_signature(connection)
        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        created = False
        if not signature and application_id == 0 and user_version == 0:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in _SCHEMA_DDL:
                    connection.execute(statement)
                connection.execute(
                    """
                    INSERT INTO witness_journal_metadata (
                        singleton, schema_version, genesis_transition_sha256, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        1,
                        PROFILED_WITNESS_JOURNAL_V1_SCHEMA_VERSION,
                        PROFILED_WITNESS_JOURNAL_GENESIS_TRANSITION_SHA256,
                        _journaled_at(),
                    ),
                )
                connection.execute(
                    f"PRAGMA application_id={PROFILED_WITNESS_JOURNAL_APPLICATION_ID}"
                )
                connection.execute(f"PRAGMA user_version={PROFILED_WITNESS_JOURNAL_USER_VERSION}")
                connection.execute("COMMIT")
                created = True
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        self._verify_schema(connection)
        return created

    @staticmethod
    def _verify_schema(connection: sqlite3.Connection) -> None:
        if (
            int(connection.execute("PRAGMA application_id").fetchone()[0])
            != PROFILED_WITNESS_JOURNAL_APPLICATION_ID
            or int(connection.execute("PRAGMA user_version").fetchone()[0])
            != PROFILED_WITNESS_JOURNAL_USER_VERSION
            or _schema_signature(connection) != _expected_schema_signature()
        ):
            _fail("PROFILED_WITNESS_JOURNAL_SCHEMA_IDENTITY_INVALID")
        rows = connection.execute(
            """
            SELECT singleton, schema_version, genesis_transition_sha256, created_at
            FROM witness_journal_metadata
            """
        ).fetchall()
        if len(rows) != 1:
            _fail("PROFILED_WITNESS_JOURNAL_METADATA_INVALID")
        row = rows[0]
        if (
            row["singleton"] != 1
            or row["schema_version"] != PROFILED_WITNESS_JOURNAL_V1_SCHEMA_VERSION
            or row["genesis_transition_sha256"]
            != PROFILED_WITNESS_JOURNAL_GENESIS_TRANSITION_SHA256
        ):
            _fail("PROFILED_WITNESS_JOURNAL_METADATA_INVALID")
        _clock(
            row["created_at"],
            reason="PROFILED_WITNESS_JOURNAL_METADATA_CLOCK_INVALID",
        )

    def initialize(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> None:
        with self.writer_lease(writer_lease) as held:
            connection = self._open_connection(writer_lease=held)
            created = False
            try:
                created = self._initialize_or_verify_schema(connection)
                self._verify_integrity_connection(connection)
            except sqlite3.Error as exc:
                raise ProfiledTrainingExternalWitnessJournalV1Error(
                    "PROFILED_WITNESS_JOURNAL_INITIALIZATION_FAILED"
                ) from exc
            finally:
                self._close_connection(connection, writer_lease=held)
            if created:
                _fsync_directory(self._path.parent)

    @staticmethod
    def _validated_candidate_and_prepared(
        *,
        client: PinnedProfiledTrainingExternalWitnessClientV1,
        prepared: ProfiledTrainingExternalWitnessPreparedAppendV1,
        head_candidate: LocalProfiledTrainingObservationHeadCandidateV1,
    ) -> None:
        if type(client) is not PinnedProfiledTrainingExternalWitnessClientV1:
            _fail("PROFILED_WITNESS_JOURNAL_CLIENT_EXACT_TYPE_REQUIRED")
        if type(prepared) is not ProfiledTrainingExternalWitnessPreparedAppendV1:
            _fail("PROFILED_WITNESS_JOURNAL_PREPARED_EXACT_TYPE_REQUIRED")
        if type(head_candidate) is not LocalProfiledTrainingObservationHeadCandidateV1:
            _fail("PROFILED_WITNESS_JOURNAL_HEAD_CANDIDATE_EXACT_TYPE_REQUIRED")
        prepared.__post_init__()
        head_candidate.__post_init__()
        try:
            local_staging_store = ImmutableSourcePayloadStore(head_candidate.staging_store_root)
            local_event_bytes = local_staging_store.get(
                head_candidate.candidate_event_sha256,
                expected_byte_count=head_candidate.candidate_event_byte_count,
            )
        except SourcePayloadStoreError as exc:
            raise ProfiledTrainingExternalWitnessJournalV1Error(
                "PROFILED_WITNESS_JOURNAL_LOCAL_HEAD_CAS_INVALID"
            ) from exc
        candidate_material_bytes = _canonical_json_bytes(
            head_candidate._material,
            reason="PROFILED_WITNESS_JOURNAL_LOCAL_HEAD_MATERIAL_INVALID",
            maximum_bytes=MAX_PROFILED_OBSERVATION_HEAD_EVENT_BYTES,
        )
        rederived = client.prepare_compare_and_append(
            namespace=prepared.namespace,
            expected_sequence=prepared.expected_sequence,
            expected_event_sha256=prepared.expected_event_sha256,
            event_bytes=prepared.event_bytes,
        )
        if prepared != rederived or not hmac.compare_digest(
            prepared.request_bytes,
            rederived.request_bytes,
        ):
            _fail("PROFILED_WITNESS_JOURNAL_PREPARED_REAUTHENTICATION_FAILED")
        if (
            prepared.witness_id != client.witness_id
            or prepared.witness_public_key_sha256 != client.witness_public_key_sha256
            or head_candidate.namespace != prepared.namespace
            or head_candidate.revision != prepared.expected_sequence + 1
            or head_candidate.previous_head_event_sha256 != prepared.expected_event_sha256
            or head_candidate.candidate_event_sha256 != prepared.event_sha256
            or head_candidate.candidate_event_byte_count != prepared.event_byte_count
            or not hmac.compare_digest(local_event_bytes, prepared.event_bytes)
            or not hmac.compare_digest(candidate_material_bytes, prepared.event_bytes)
            or any(getattr(head_candidate, name) is not False for name in _AUTHORITY_FIELDS)
        ):
            _fail("PROFILED_WITNESS_JOURNAL_HEAD_PREPARED_BINDING_INVALID")
        _authority_false_from_prepared(prepared)

    @staticmethod
    def _operation_material(
        *,
        prepared: ProfiledTrainingExternalWitnessPreparedAppendV1,
        head_candidate: LocalProfiledTrainingObservationHeadCandidateV1,
        prior_head_sha256: str | None,
        prior_head_byte_count: int | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": PROFILED_WITNESS_JOURNAL_OPERATION_V1_SCHEMA_VERSION,
            "witness_id": prepared.witness_id,
            "witness_public_key_sha256": prepared.witness_public_key_sha256,
            "namespace": prepared.namespace,
            "manifest_id": head_candidate.manifest_id,
            "observation_time": head_candidate.observation_time,
            "head_revision": head_candidate.revision,
            "candidate_id": head_candidate.candidate_id,
            "candidate_event_sha256": head_candidate.candidate_event_sha256,
            "candidate_event_byte_count": head_candidate.candidate_event_byte_count,
            "previous_head_event_sha256": head_candidate.previous_head_event_sha256,
            "previous_completion_candidate_sha256": (
                head_candidate.previous_completion_candidate_sha256
            ),
            "local_staging_store_root": str(head_candidate.staging_store_root),
            "manifest_auth_key_id": head_candidate.manifest_auth_key_id,
            "head_auth_key_id": head_candidate.head_auth_key_id,
            "epoch_auth_key_id": head_candidate.epoch_auth_key_id,
            "epoch_auth_key_commitment_sha256": (head_candidate.epoch_auth_key_commitment_sha256),
            "allowed_consumer_lane": head_candidate.allowed_consumer_lane,
            "expected_sequence": prepared.expected_sequence,
            "expected_event_sha256": prepared.expected_event_sha256,
            "event_cas_sha256": prepared.event_sha256,
            "event_byte_count": prepared.event_byte_count,
            "request_cas_sha256": prepared.request_sha256,
            "request_byte_count": prepared.request_byte_count,
            "request_sha256": prepared.request_sha256,
            "idempotency_key": prepared.idempotency_key,
            "prior_signed_head_envelope_sha256": prior_head_sha256,
            "prior_signed_head_envelope_byte_count": prior_head_byte_count,
            **_authority_false_from_prepared(prepared),
        }

    @staticmethod
    def _transition_material(
        *,
        transition_sequence: int,
        previous_transition_sha256: str,
        operation_id: str,
        state: str,
        journaled_at: str,
        receipt_sequence: int | None = None,
        receipt_previous_event_sha256: str | None = None,
        receipt_event_sha256: str | None = None,
        receipt_accepted_at: str | None = None,
        signed_receipt_envelope_sha256: str | None = None,
        signed_receipt_envelope_byte_count: int | None = None,
        signed_head_envelope_sha256: str | None = None,
        signed_head_envelope_byte_count: int | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": PROFILED_WITNESS_JOURNAL_TRANSITION_V1_SCHEMA_VERSION,
            "transition_sequence": transition_sequence,
            "previous_transition_sha256": previous_transition_sha256,
            "operation_id": operation_id,
            "state": state,
            "journaled_at": journaled_at,
            "receipt": (
                None
                if state == PROFILED_WITNESS_JOURNAL_APPEND_PREPARED
                else {
                    "sequence": receipt_sequence,
                    "previous_event_sha256": receipt_previous_event_sha256,
                    "event_sha256": receipt_event_sha256,
                    "accepted_at": receipt_accepted_at,
                    "signed_receipt_envelope_sha256": (signed_receipt_envelope_sha256),
                    "signed_receipt_envelope_byte_count": (signed_receipt_envelope_byte_count),
                    "signed_head_envelope_sha256": signed_head_envelope_sha256,
                    "signed_head_envelope_byte_count": (signed_head_envelope_byte_count),
                }
            ),
        }

    def _verify_request_and_event(self, row: sqlite3.Row) -> tuple[bytes, bytes]:
        try:
            event_bytes = self._cas.get(
                row["event_cas_sha256"],
                expected_byte_count=row["event_byte_count"],
            )
            request_bytes = self._cas.get(
                row["request_cas_sha256"],
                expected_byte_count=row["request_byte_count"],
            )
        except SourcePayloadStoreError as exc:
            raise ProfiledTrainingExternalWitnessJournalV1Error(
                "PROFILED_WITNESS_JOURNAL_CAS_EVIDENCE_INVALID"
            ) from exc
        if (
            hashlib.sha256(event_bytes).hexdigest() != row["candidate_event_sha256"]
            or hashlib.sha256(request_bytes).hexdigest() != row["request_sha256"]
            or row["request_cas_sha256"] != row["request_sha256"]
        ):
            _fail("PROFILED_WITNESS_JOURNAL_CAS_BINDING_INVALID")
        request = _strict_json(
            request_bytes,
            reason="PROFILED_WITNESS_JOURNAL_REQUEST_JSON_INVALID",
            maximum_bytes=MAX_PROFILED_WITNESS_WIRE_BYTES,
        )
        if set(request) != _REQUEST_FIELDS:
            _fail("PROFILED_WITNESS_JOURNAL_REQUEST_FIELD_SET_INVALID")
        try:
            request_event = base64.b64decode(
                request.get("event_base64"),
                validate=True,
            )
        except (TypeError, ValueError) as exc:
            raise ProfiledTrainingExternalWitnessJournalV1Error(
                "PROFILED_WITNESS_JOURNAL_REQUEST_EVENT_INVALID"
            ) from exc
        base_request = {key: value for key, value in request.items() if key != "idempotency_key"}
        derived_idempotency = hashlib.sha256(
            PROFILED_WITNESS_COMPARE_APPEND_REQUEST_DOMAIN.encode("ascii")
            + b"\0"
            + _canonical_json_bytes(
                base_request,
                reason="PROFILED_WITNESS_JOURNAL_REQUEST_JSON_INVALID",
                maximum_bytes=MAX_PROFILED_WITNESS_WIRE_BYTES,
            )
        ).hexdigest()
        if (
            request.get("schema_version")
            != PROFILED_WITNESS_COMPARE_APPEND_REQUEST_V1_SCHEMA_VERSION
            or request.get("request_domain") != PROFILED_WITNESS_COMPARE_APPEND_REQUEST_DOMAIN
            or request.get("witness_id") != row["witness_id"]
            or request.get("witness_public_key_sha256") != row["witness_public_key_sha256"]
            or request.get("namespace") != row["namespace"]
            or request.get("expected_sequence") != row["expected_sequence"]
            or request.get("expected_event_sha256") != row["expected_event_sha256"]
            or request.get("event_sha256") != row["event_cas_sha256"]
            or request.get("event_byte_count") != row["event_byte_count"]
            or not hmac.compare_digest(request_event, event_bytes)
            or request.get("idempotency_key") != row["idempotency_key"]
            or derived_idempotency != row["idempotency_key"]
            or any(request.get(name) is not False for name in _AUTHORITY_FIELDS)
        ):
            _fail("PROFILED_WITNESS_JOURNAL_REQUEST_BINDING_INVALID")
        return event_bytes, request_bytes

    @staticmethod
    def _operation_material_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "schema_version": PROFILED_WITNESS_JOURNAL_OPERATION_V1_SCHEMA_VERSION,
            "witness_id": row["witness_id"],
            "witness_public_key_sha256": row["witness_public_key_sha256"],
            "namespace": row["namespace"],
            "manifest_id": row["manifest_id"],
            "observation_time": row["observation_time"],
            "head_revision": row["head_revision"],
            "candidate_id": row["candidate_id"],
            "candidate_event_sha256": row["candidate_event_sha256"],
            "candidate_event_byte_count": row["candidate_event_byte_count"],
            "previous_head_event_sha256": row["previous_head_event_sha256"],
            "previous_completion_candidate_sha256": row["previous_completion_candidate_sha256"],
            "local_staging_store_root": row["local_staging_store_root"],
            "manifest_auth_key_id": row["manifest_auth_key_id"],
            "head_auth_key_id": row["head_auth_key_id"],
            "epoch_auth_key_id": row["epoch_auth_key_id"],
            "epoch_auth_key_commitment_sha256": row["epoch_auth_key_commitment_sha256"],
            "allowed_consumer_lane": row["allowed_consumer_lane"],
            "expected_sequence": row["expected_sequence"],
            "expected_event_sha256": row["expected_event_sha256"],
            "event_cas_sha256": row["event_cas_sha256"],
            "event_byte_count": row["event_byte_count"],
            "request_cas_sha256": row["request_cas_sha256"],
            "request_byte_count": row["request_byte_count"],
            "request_sha256": row["request_sha256"],
            "idempotency_key": row["idempotency_key"],
            "prior_signed_head_envelope_sha256": row["prior_signed_head_envelope_sha256"],
            "prior_signed_head_envelope_byte_count": row["prior_signed_head_envelope_byte_count"],
            **{name: False for name in _AUTHORITY_FIELDS},
        }

    def _verify_operation_row(self, row: sqlite3.Row) -> None:
        for field_name in (
            "operation_id",
            "witness_public_key_sha256",
            "manifest_id",
            "candidate_id",
            "candidate_event_sha256",
            "previous_head_event_sha256",
            "previous_completion_candidate_sha256",
            "epoch_auth_key_commitment_sha256",
            "expected_event_sha256",
            "event_cas_sha256",
            "request_cas_sha256",
            "request_sha256",
            "idempotency_key",
        ):
            _sha256(
                row[field_name],
                reason=f"PROFILED_WITNESS_JOURNAL_OPERATION_{field_name.upper()}_INVALID",
            )
        for field_name in (
            "witness_id",
            "namespace",
            "manifest_auth_key_id",
            "head_auth_key_id",
            "epoch_auth_key_id",
            "allowed_consumer_lane",
        ):
            _identifier(
                row[field_name],
                reason=f"PROFILED_WITNESS_JOURNAL_OPERATION_{field_name.upper()}_INVALID",
            )
        _clock(
            row["observation_time"],
            reason="PROFILED_WITNESS_JOURNAL_OBSERVATION_TIME_INVALID",
        )
        _positive_integer(
            row["head_revision"],
            reason="PROFILED_WITNESS_JOURNAL_HEAD_REVISION_INVALID",
        )
        _positive_integer(
            row["candidate_event_byte_count"],
            reason="PROFILED_WITNESS_JOURNAL_EVENT_COUNT_INVALID",
        )
        _positive_integer(
            row["expected_sequence"],
            reason="PROFILED_WITNESS_JOURNAL_EXPECTED_SEQUENCE_INVALID",
            allow_zero=True,
        )
        _positive_integer(
            row["event_byte_count"],
            reason="PROFILED_WITNESS_JOURNAL_EVENT_COUNT_INVALID",
        )
        _positive_integer(
            row["request_byte_count"],
            reason="PROFILED_WITNESS_JOURNAL_REQUEST_COUNT_INVALID",
        )
        _absolute_path(
            Path(row["local_staging_store_root"]),
            reason="PROFILED_WITNESS_JOURNAL_STAGING_ROOT_INVALID",
        )
        if (
            row["expected_sequence"] > 2**63 - 2
            or row["candidate_event_byte_count"] > MAX_PROFILED_OBSERVATION_HEAD_EVENT_BYTES
            or row["event_byte_count"] > MAX_PROFILED_OBSERVATION_HEAD_EVENT_BYTES
            or row["request_byte_count"] > MAX_PROFILED_WITNESS_WIRE_BYTES
            or row["head_revision"] != row["expected_sequence"] + 1
            or row["candidate_event_sha256"] != row["event_cas_sha256"]
            or row["candidate_event_byte_count"] != row["event_byte_count"]
            or row["previous_head_event_sha256"] != row["expected_event_sha256"]
            or any(not _sqlite_integer_false(row, name) for name in _AUTHORITY_FIELDS)
        ):
            _fail("PROFILED_WITNESS_JOURNAL_OPERATION_BINDING_INVALID")
        if row["expected_sequence"] == 0:
            if (
                row["expected_event_sha256"] != PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256
                or row["prior_signed_head_envelope_sha256"] is not None
                or row["prior_signed_head_envelope_byte_count"] is not None
            ):
                _fail("PROFILED_WITNESS_JOURNAL_GENESIS_BINDING_INVALID")
        else:
            _sha256(
                row["prior_signed_head_envelope_sha256"],
                reason="PROFILED_WITNESS_JOURNAL_PRIOR_HEAD_SHA256_INVALID",
            )
            _positive_integer(
                row["prior_signed_head_envelope_byte_count"],
                reason="PROFILED_WITNESS_JOURNAL_PRIOR_HEAD_COUNT_INVALID",
            )
            try:
                self._cas.verify(
                    row["prior_signed_head_envelope_sha256"],
                    expected_byte_count=row["prior_signed_head_envelope_byte_count"],
                )
            except SourcePayloadStoreError as exc:
                raise ProfiledTrainingExternalWitnessJournalV1Error(
                    "PROFILED_WITNESS_JOURNAL_PRIOR_HEAD_CAS_INVALID"
                ) from exc
        material = self._operation_material_from_row(row)
        material_bytes = _canonical_json_bytes(
            material,
            reason="PROFILED_WITNESS_JOURNAL_OPERATION_MATERIAL_INVALID",
        )
        if row["operation_material_json"] != material_bytes.decode("ascii") or row[
            "operation_id"
        ] != _operation_id(material_bytes):
            _fail("PROFILED_WITNESS_JOURNAL_OPERATION_HASH_INVALID")
        self._verify_request_and_event(row)

    @staticmethod
    def _transition_material_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return ProfiledTrainingExternalWitnessJournalV1._transition_material(
            transition_sequence=row["transition_sequence"],
            previous_transition_sha256=row["previous_transition_sha256"],
            operation_id=row["operation_id"],
            state=row["state"],
            journaled_at=row["journaled_at"],
            receipt_sequence=row["receipt_sequence"],
            receipt_previous_event_sha256=row["receipt_previous_event_sha256"],
            receipt_event_sha256=row["receipt_event_sha256"],
            receipt_accepted_at=row["receipt_accepted_at"],
            signed_receipt_envelope_sha256=row["signed_receipt_envelope_sha256"],
            signed_receipt_envelope_byte_count=row["signed_receipt_envelope_byte_count"],
            signed_head_envelope_sha256=row["signed_head_envelope_sha256"],
            signed_head_envelope_byte_count=row["signed_head_envelope_byte_count"],
        )

    def _verify_integrity_connection(
        self,
        connection: sqlite3.Connection,
    ) -> ProfiledTrainingExternalWitnessJournalIntegrityReportV1:
        self._verify_schema(connection)
        operation_count = int(
            connection.execute("SELECT COUNT(*) FROM witness_journal_operations").fetchone()[0]
        )
        transition_count = int(
            connection.execute("SELECT COUNT(*) FROM witness_journal_transitions").fetchone()[0]
        )
        if transition_count > MAX_PROFILED_WITNESS_JOURNAL_TRANSITIONS:
            _fail("PROFILED_WITNESS_JOURNAL_TRANSITION_RESOURCE_LIMIT_EXCEEDED")
        if operation_count > MAX_PROFILED_WITNESS_JOURNAL_TRANSITIONS:
            _fail("PROFILED_WITNESS_JOURNAL_OPERATION_RESOURCE_LIMIT_EXCEEDED")
        operation_by_id: dict[str, tuple[int, str, str]] = {}
        for row in connection.execute(
            "SELECT * FROM witness_journal_operations ORDER BY operation_id"
        ):
            self._verify_operation_row(row)
            operation_by_id[row["operation_id"]] = (
                int(row["expected_sequence"]),
                str(row["expected_event_sha256"]),
                str(row["event_cas_sha256"]),
            )

        expected_previous = PROFILED_WITNESS_JOURNAL_GENESIS_TRANSITION_SHA256
        # Retain only the lifecycle fields needed by the namespace pass.  The
        # count gate above bounds these compact maps before SQLite rows or CAS
        # payloads are inspected; retaining full sqlite3.Row objects here would
        # otherwise make the integrity verifier itself a memory-exhaustion path.
        states_by_operation: dict[str, list[tuple[str, str | None, int | None]]] = {
            operation_id: [] for operation_id in operation_by_id
        }
        transition_rows = connection.execute(
            "SELECT * FROM witness_journal_transitions ORDER BY transition_sequence"
        )
        for index, row in enumerate(transition_rows, start=1):
            if (
                row["transition_sequence"] != index
                or row["previous_transition_sha256"] != expected_previous
                or row["operation_id"] not in operation_by_id
                or row["state"]
                not in {
                    PROFILED_WITNESS_JOURNAL_APPEND_PREPARED,
                    PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED,
                }
            ):
                _fail("PROFILED_WITNESS_JOURNAL_TRANSITION_CHAIN_INVALID")
            _clock(
                row["journaled_at"],
                reason="PROFILED_WITNESS_JOURNAL_TRANSITION_CLOCK_INVALID",
            )
            material = self._transition_material_from_row(row)
            material_bytes = _canonical_json_bytes(
                material,
                reason="PROFILED_WITNESS_JOURNAL_TRANSITION_MATERIAL_INVALID",
            )
            if row["transition_material_json"] != material_bytes.decode("ascii") or row[
                "transition_sha256"
            ] != _transition_sha256(material_bytes):
                _fail("PROFILED_WITNESS_JOURNAL_TRANSITION_HASH_INVALID")
            if row["state"] == PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED:
                operation = operation_by_id[row["operation_id"]]
                if (
                    row["receipt_sequence"] != operation[0] + 1
                    or row["receipt_previous_event_sha256"] != operation[1]
                    or row["receipt_event_sha256"] != operation[2]
                ):
                    _fail("PROFILED_WITNESS_JOURNAL_ANCHOR_BINDING_INVALID")
                _clock(
                    row["receipt_accepted_at"],
                    reason="PROFILED_WITNESS_JOURNAL_RECEIPT_CLOCK_INVALID",
                )
                try:
                    self._cas.verify(
                        row["signed_receipt_envelope_sha256"],
                        expected_byte_count=row["signed_receipt_envelope_byte_count"],
                    )
                    self._cas.verify(
                        row["signed_head_envelope_sha256"],
                        expected_byte_count=row["signed_head_envelope_byte_count"],
                    )
                except SourcePayloadStoreError as exc:
                    raise ProfiledTrainingExternalWitnessJournalV1Error(
                        "PROFILED_WITNESS_JOURNAL_ANCHOR_CAS_INVALID"
                    ) from exc
            states_by_operation[row["operation_id"]].append(
                (
                    str(row["state"]),
                    (
                        str(row["signed_head_envelope_sha256"])
                        if row["signed_head_envelope_sha256"] is not None
                        else None
                    ),
                    (
                        int(row["signed_head_envelope_byte_count"])
                        if row["signed_head_envelope_byte_count"] is not None
                        else None
                    ),
                )
            )
            expected_previous = row["transition_sha256"]

        anchored_count = 0
        pending_count = 0
        prior_by_namespace: dict[
            str,
            tuple[str, int, str, str, str, str, str],
        ] = {}
        operation_rows = connection.execute(
            "SELECT * FROM witness_journal_operations ORDER BY namespace, expected_sequence"
        )
        for operation in operation_rows:
            states = states_by_operation[operation["operation_id"]]
            if (
                not states
                or states[0][0] != PROFILED_WITNESS_JOURNAL_APPEND_PREPARED
                or len(states) not in {1, 2}
                or (len(states) == 2 and states[1][0] != PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED)
            ):
                _fail("PROFILED_WITNESS_JOURNAL_OPERATION_LIFECYCLE_INVALID")
            namespace = operation["namespace"]
            prior = prior_by_namespace.get(namespace)
            if prior is None:
                if (
                    operation["expected_sequence"] != 0
                    or operation["previous_completion_candidate_sha256"]
                    != PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256
                ):
                    _fail("PROFILED_WITNESS_JOURNAL_NAMESPACE_GENESIS_MISSING")
            else:
                prior_states = states_by_operation[prior[0]]
                if len(prior_states) != 2:
                    _fail("PROFILED_WITNESS_JOURNAL_NAMESPACE_PENDING_NOT_TERMINAL")
                prior_anchor = prior_states[1]
                if (
                    operation["expected_sequence"] != prior[1] + 1
                    or operation["expected_event_sha256"] != prior[2]
                    or operation["prior_signed_head_envelope_sha256"] != prior_anchor[1]
                    or operation["prior_signed_head_envelope_byte_count"] != prior_anchor[2]
                    or operation["observation_time"] <= prior[3]
                    or operation["manifest_id"] == prior[4]
                    or operation["candidate_id"] == prior[5]
                    or operation["previous_completion_candidate_sha256"]
                    == PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256
                ):
                    _fail("PROFILED_WITNESS_JOURNAL_NAMESPACE_CHAIN_INVALID")
            prior_by_namespace[namespace] = (
                str(operation["operation_id"]),
                int(operation["expected_sequence"]),
                str(operation["event_cas_sha256"]),
                str(operation["observation_time"]),
                str(operation["manifest_id"]),
                str(operation["candidate_id"]),
                str(operation["previous_completion_candidate_sha256"]),
            )
            if len(states) == 2:
                anchored_count += 1
            else:
                pending_count += 1

        # A pending operation always needs one future HEAD_ANCHORED transition.
        # Count that already-promised slot as occupied so a valid pending append
        # can never become unanchorable merely because the journal reached its
        # resource ceiling between prepare and receipt persistence.
        if transition_count + pending_count > MAX_PROFILED_WITNESS_JOURNAL_TRANSITIONS:
            _fail("PROFILED_WITNESS_JOURNAL_ANCHOR_CAPACITY_NOT_RESERVED")

        return ProfiledTrainingExternalWitnessJournalIntegrityReportV1(
            schema_version=(PROFILED_WITNESS_JOURNAL_INTEGRITY_REPORT_V1_SCHEMA_VERSION),
            operation_count=operation_count,
            transition_count=transition_count,
            prepared_count=operation_count,
            anchored_count=anchored_count,
            pending_count=pending_count,
            namespace_count=len(prior_by_namespace),
            terminal_transition_sha256=expected_previous,
        )

    def verify_integrity(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingExternalWitnessJournalIntegrityReportV1:
        with self.writer_lease(writer_lease) as held:
            connection = self._open_connection(writer_lease=held)
            try:
                return self._verify_integrity_connection(connection)
            except sqlite3.Error as exc:
                raise ProfiledTrainingExternalWitnessJournalV1Error(
                    "PROFILED_WITNESS_JOURNAL_INTEGRITY_VERIFICATION_FAILED"
                ) from exc
            finally:
                self._close_connection(connection, writer_lease=held)

    @staticmethod
    def _latest_transition_identity(
        connection: sqlite3.Connection,
    ) -> tuple[int, str]:
        row = connection.execute(
            """
            SELECT transition_sequence, transition_sha256
            FROM witness_journal_transitions
            ORDER BY transition_sequence DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return 0, PROFILED_WITNESS_JOURNAL_GENESIS_TRANSITION_SHA256
        return int(row["transition_sequence"]), str(row["transition_sha256"])

    @staticmethod
    def _latest_anchor_for_namespace(
        connection: sqlite3.Connection,
        namespace: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT operation.*, transition.signed_head_envelope_sha256,
                   transition.signed_head_envelope_byte_count
            FROM witness_journal_operations AS operation
            JOIN witness_journal_transitions AS transition
              ON transition.operation_id = operation.operation_id
             AND transition.state = 'HEAD_ANCHORED'
            WHERE operation.namespace = ?
            ORDER BY operation.expected_sequence DESC
            LIMIT 1
            """,
            (namespace,),
        ).fetchone()

    def _verify_client_prior_anchor(
        self,
        connection: sqlite3.Connection,
        *,
        namespace: str,
        expected_sequence: int,
        client: PinnedProfiledTrainingExternalWitnessClientV1,
        pending_operation: sqlite3.Row | None = None,
    ) -> None:
        try:
            client_head = client.trusted_head_envelope_bytes(namespace=namespace)
        except ProfiledTrainingExternalWitnessClientV1Error as exc:
            if (
                exc.reasons == ("PROFILED_WITNESS_TRUSTED_HEAD_UNAVAILABLE",)
                and expected_sequence == 0
            ):
                return
            raise ProfiledTrainingExternalWitnessJournalV1Error(
                "PROFILED_WITNESS_JOURNAL_CLIENT_PRIOR_HEAD_INVALID"
            ) from exc

        # After the witness accepted a request but before the local anchor
        # committed, the same live client legitimately holds the exact pending
        # event as its head.  Accept only that fully reverified state or the
        # previously persisted head; any third state is a fork/rollback.
        if pending_operation is not None:
            if (
                pending_operation["namespace"] != namespace
                or pending_operation["expected_sequence"] != expected_sequence
            ):
                _fail("PROFILED_WITNESS_JOURNAL_PENDING_OPERATION_BINDING_INVALID")
            try:
                pending_event = self._cas.get(
                    pending_operation["event_cas_sha256"],
                    expected_byte_count=pending_operation["event_byte_count"],
                )
                client.verify_signed_head_envelope(
                    signed_head_envelope_bytes=client_head,
                    expected_namespace=namespace,
                    expected_sequence=expected_sequence + 1,
                    expected_previous_event_sha256=pending_operation["expected_event_sha256"],
                    expected_event_sha256=pending_operation["event_cas_sha256"],
                    expected_event_bytes=pending_event,
                )
            except SourcePayloadStoreError as exc:
                raise ProfiledTrainingExternalWitnessJournalV1Error(
                    "PROFILED_WITNESS_JOURNAL_PENDING_EVENT_CAS_INVALID"
                ) from exc
            except ProfiledTrainingExternalWitnessClientV1Error:
                # The client may still be at the prior durable head.  That
                # exact state is verified below for non-genesis operations.
                pass
            else:
                return

        if expected_sequence == 0:
            _fail("PROFILED_WITNESS_JOURNAL_CLIENT_GENESIS_ROLLBACK")

        prior = connection.execute(
            """
            SELECT prior.*, anchor.signed_head_envelope_sha256,
                   anchor.signed_head_envelope_byte_count
            FROM witness_journal_operations AS prior
            JOIN witness_journal_transitions AS anchor
              ON anchor.operation_id = prior.operation_id
             AND anchor.state = 'HEAD_ANCHORED'
            WHERE prior.namespace = ?
              AND prior.expected_sequence = ?
            """,
            (namespace, expected_sequence - 1),
        ).fetchone()
        if prior is None:
            _fail("PROFILED_WITNESS_JOURNAL_CLIENT_PRIOR_HEAD_MISSING")
        try:
            persisted_head = self._cas.get(
                prior["signed_head_envelope_sha256"],
                expected_byte_count=prior["signed_head_envelope_byte_count"],
            )
            prior_event = self._cas.get(
                prior["event_cas_sha256"],
                expected_byte_count=prior["event_byte_count"],
            )
            if not hmac.compare_digest(persisted_head, client_head):
                _fail("PROFILED_WITNESS_JOURNAL_CLIENT_PRIOR_HEAD_MISMATCH")
            client.verify_signed_head_envelope(
                signed_head_envelope_bytes=persisted_head,
                expected_namespace=namespace,
                expected_sequence=expected_sequence,
                expected_previous_event_sha256=prior["expected_event_sha256"],
                expected_event_sha256=prior["event_cas_sha256"],
                expected_event_bytes=prior_event,
            )
        except SourcePayloadStoreError as exc:
            raise ProfiledTrainingExternalWitnessJournalV1Error(
                "PROFILED_WITNESS_JOURNAL_CLIENT_PRIOR_HEAD_CAS_INVALID"
            ) from exc
        except ProfiledTrainingExternalWitnessClientV1Error as exc:
            raise ProfiledTrainingExternalWitnessJournalV1Error(
                "PROFILED_WITNESS_JOURNAL_CLIENT_PRIOR_HEAD_INVALID"
            ) from exc

    @staticmethod
    def _insert_transition(
        connection: sqlite3.Connection,
        *,
        material: Mapping[str, Any],
    ) -> None:
        encoded = _canonical_json_bytes(
            dict(material),
            reason="PROFILED_WITNESS_JOURNAL_TRANSITION_MATERIAL_INVALID",
        )
        receipt = material["receipt"]
        receipt_mapping = cast(Mapping[str, Any], receipt) if isinstance(receipt, Mapping) else {}
        connection.execute(
            """
            INSERT INTO witness_journal_transitions (
                transition_sequence, previous_transition_sha256,
                transition_sha256, operation_id, state,
                receipt_sequence, receipt_previous_event_sha256,
                receipt_event_sha256, receipt_accepted_at,
                signed_receipt_envelope_sha256,
                signed_receipt_envelope_byte_count,
                signed_head_envelope_sha256,
                signed_head_envelope_byte_count,
                journaled_at, transition_material_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                material["transition_sequence"],
                material["previous_transition_sha256"],
                _transition_sha256(encoded),
                material["operation_id"],
                material["state"],
                receipt_mapping.get("sequence"),
                receipt_mapping.get("previous_event_sha256"),
                receipt_mapping.get("event_sha256"),
                receipt_mapping.get("accepted_at"),
                receipt_mapping.get("signed_receipt_envelope_sha256"),
                receipt_mapping.get("signed_receipt_envelope_byte_count"),
                receipt_mapping.get("signed_head_envelope_sha256"),
                receipt_mapping.get("signed_head_envelope_byte_count"),
                material["journaled_at"],
                encoded.decode("ascii"),
            ),
        )

    @staticmethod
    def _operation_values(
        *,
        operation_id: str,
        material: Mapping[str, Any],
        material_json: str,
    ) -> tuple[Any, ...]:
        ordered_fields = (
            "witness_id",
            "witness_public_key_sha256",
            "namespace",
            "manifest_id",
            "observation_time",
            "head_revision",
            "candidate_id",
            "candidate_event_sha256",
            "candidate_event_byte_count",
            "previous_head_event_sha256",
            "previous_completion_candidate_sha256",
            "local_staging_store_root",
            "manifest_auth_key_id",
            "head_auth_key_id",
            "epoch_auth_key_id",
            "epoch_auth_key_commitment_sha256",
            "allowed_consumer_lane",
            "expected_sequence",
            "expected_event_sha256",
            "event_cas_sha256",
            "event_byte_count",
            "request_cas_sha256",
            "request_byte_count",
            "request_sha256",
            "idempotency_key",
            "prior_signed_head_envelope_sha256",
            "prior_signed_head_envelope_byte_count",
            *_AUTHORITY_FIELDS,
        )
        return (
            operation_id,
            *(material[name] for name in ordered_fields),
            material_json,
        )

    def persist_prepared_append(
        self,
        *,
        client: PinnedProfiledTrainingExternalWitnessClientV1,
        prepared: ProfiledTrainingExternalWitnessPreparedAppendV1,
        head_candidate: LocalProfiledTrainingObservationHeadCandidateV1,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingExternalWitnessJournalRecordV1:
        """Durably commit exact append material before any caller dispatch."""

        self._validated_candidate_and_prepared(
            client=client,
            prepared=prepared,
            head_candidate=head_candidate,
        )

        with self.writer_lease(writer_lease) as held:
            connection: sqlite3.Connection | None = self._open_connection(writer_lease=held)
            created = False
            operation_id: str | None = None
            try:
                created = self._initialize_or_verify_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                integrity_before = self._verify_integrity_connection(connection)
                existing = connection.execute(
                    """
                    SELECT * FROM witness_journal_operations
                    WHERE request_sha256 = ? OR idempotency_key = ?
                    """,
                    (prepared.request_sha256, prepared.idempotency_key),
                ).fetchall()
                if existing:
                    if len(existing) != 1:
                        _fail("PROFILED_WITNESS_JOURNAL_PREPARED_IDENTITY_CONFLICT")
                    row = existing[0]
                    operation_id = row["operation_id"]
                    self._verify_operation_row(row)
                    expected_material = self._operation_material(
                        prepared=prepared,
                        head_candidate=head_candidate,
                        prior_head_sha256=row["prior_signed_head_envelope_sha256"],
                        prior_head_byte_count=row["prior_signed_head_envelope_byte_count"],
                    )
                    expected_bytes = _canonical_json_bytes(
                        expected_material,
                        reason="PROFILED_WITNESS_JOURNAL_OPERATION_MATERIAL_INVALID",
                    )
                    if row["operation_id"] != _operation_id(expected_bytes) or row[
                        "operation_material_json"
                    ] != expected_bytes.decode("ascii"):
                        _fail("PROFILED_WITNESS_JOURNAL_PREPARED_REPLAY_CONFLICT")
                    connection.execute("COMMIT")
                else:
                    # A new operation consumes one APPEND_PREPARED transition
                    # now and reserves one HEAD_ANCHORED transition for the
                    # eventual authenticated receipt.  Exact replay above does
                    # not consume capacity and remains available at the limit.
                    if (
                        integrity_before.transition_count + integrity_before.pending_count + 2
                        > MAX_PROFILED_WITNESS_JOURNAL_TRANSITIONS
                    ):
                        _fail("PROFILED_WITNESS_JOURNAL_TRANSITION_CAPACITY_RESERVED")
                    pending = connection.execute(
                        """
                        SELECT operation.operation_id
                        FROM witness_journal_operations AS operation
                        WHERE operation.namespace = ?
                          AND NOT EXISTS (
                              SELECT 1 FROM witness_journal_transitions AS transition
                              WHERE transition.operation_id = operation.operation_id
                                AND transition.state = 'HEAD_ANCHORED'
                          )
                        """,
                        (prepared.namespace,),
                    ).fetchall()
                    if pending:
                        _fail("PROFILED_WITNESS_JOURNAL_NAMESPACE_PENDING_APPEND_EXISTS")
                    prior_anchor = self._latest_anchor_for_namespace(
                        connection,
                        prepared.namespace,
                    )
                    prior_head_sha256: str | None = None
                    prior_head_byte_count: int | None = None
                    if prior_anchor is None:
                        if (
                            prepared.expected_sequence != 0
                            or prepared.expected_event_sha256
                            != PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256
                        ):
                            _fail("PROFILED_WITNESS_JOURNAL_EXPECTED_HEAD_MISMATCH")
                    else:
                        if (
                            prepared.expected_sequence != prior_anchor["expected_sequence"] + 1
                            or prepared.expected_event_sha256 != prior_anchor["event_cas_sha256"]
                        ):
                            _fail("PROFILED_WITNESS_JOURNAL_EXPECTED_HEAD_MISMATCH")
                        prior_head_sha256 = prior_anchor["signed_head_envelope_sha256"]
                        prior_head_byte_count = prior_anchor["signed_head_envelope_byte_count"]
                    self._verify_client_prior_anchor(
                        connection,
                        namespace=prepared.namespace,
                        expected_sequence=prepared.expected_sequence,
                        client=client,
                    )
                    material = self._operation_material(
                        prepared=prepared,
                        head_candidate=head_candidate,
                        prior_head_sha256=prior_head_sha256,
                        prior_head_byte_count=prior_head_byte_count,
                    )
                    material_bytes = _canonical_json_bytes(
                        material,
                        reason="PROFILED_WITNESS_JOURNAL_OPERATION_MATERIAL_INVALID",
                    )
                    operation_id = _operation_id(material_bytes)
                    # Persist immutable payloads only after every journal
                    # admission check above has passed under the same writer
                    # lease and transaction.  In particular, a capacity- or
                    # namespace-rejected request must not consume unreferenced
                    # CAS storage.
                    try:
                        self._cas.put(
                            prepared.event_bytes,
                            expected_sha256=prepared.event_sha256,
                            expected_byte_count=prepared.event_byte_count,
                        )
                        self._cas.put(
                            prepared.request_bytes,
                            expected_sha256=prepared.request_sha256,
                            expected_byte_count=prepared.request_byte_count,
                        )
                    except SourcePayloadStoreError as exc:
                        raise ProfiledTrainingExternalWitnessJournalV1Error(
                            "PROFILED_WITNESS_JOURNAL_PREPARED_CAS_PERSIST_FAILED"
                        ) from exc
                    connection.execute(
                        """
                        INSERT INTO witness_journal_operations (
                            operation_id, witness_id, witness_public_key_sha256,
                            namespace, manifest_id, observation_time, head_revision,
                            candidate_id, candidate_event_sha256,
                            candidate_event_byte_count, previous_head_event_sha256,
                            previous_completion_candidate_sha256,
                            local_staging_store_root, manifest_auth_key_id,
                            head_auth_key_id, epoch_auth_key_id,
                            epoch_auth_key_commitment_sha256, allowed_consumer_lane,
                            expected_sequence, expected_event_sha256,
                            event_cas_sha256, event_byte_count,
                            request_cas_sha256, request_byte_count, request_sha256,
                            idempotency_key, prior_signed_head_envelope_sha256,
                            prior_signed_head_envelope_byte_count,
                            external_monotonic_manifest_head_verified,
                            full_consumption_external_ack_verified,
                            optimizer_admission_authorized,
                            checkpoint_write_authorized, model_write_authorized,
                            prediction_authorized, paper_trading_authorized,
                            live_execution_authorized, order_submission_authorized,
                            execution_authorized, runtime_wired,
                            operation_material_json
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?
                        )
                        """,
                        self._operation_values(
                            operation_id=operation_id,
                            material=material,
                            material_json=material_bytes.decode("ascii"),
                        ),
                    )
                    inserted_operation = connection.execute(
                        "SELECT * FROM witness_journal_operations WHERE operation_id = ?",
                        (operation_id,),
                    ).fetchone()
                    if inserted_operation is None:
                        _fail("PROFILED_WITNESS_JOURNAL_OPERATION_POSTINSERT_MISSING")
                    prior_sequence, prior_transition_sha = self._latest_transition_identity(
                        connection
                    )
                    transition = self._transition_material(
                        transition_sequence=prior_sequence + 1,
                        previous_transition_sha256=prior_transition_sha,
                        operation_id=operation_id,
                        state=PROFILED_WITNESS_JOURNAL_APPEND_PREPARED,
                        journaled_at=_journaled_at(),
                    )
                    self._insert_transition(connection, material=transition)
                    self._verify_integrity_connection(connection)
                    connection.execute("COMMIT")
                committed_connection = connection
                connection = None
                self._close_connection(committed_connection, writer_lease=held)
                connection = self._open_connection(writer_lease=held)
                self._verify_integrity_connection(connection)
                if operation_id is None:
                    _fail("PROFILED_WITNESS_JOURNAL_OPERATION_ID_UNAVAILABLE")
                return self._load_record_connection(
                    connection,
                    operation_id=operation_id,
                    client=client,
                )
            except ProfiledTrainingExternalWitnessJournalV1Error:
                if connection is not None:
                    try:
                        if connection.in_transaction:
                            connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                raise
            except sqlite3.Error as exc:
                if connection is not None:
                    try:
                        if connection.in_transaction:
                            connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                raise ProfiledTrainingExternalWitnessJournalV1Error(
                    "PROFILED_WITNESS_JOURNAL_PREPARED_COMMIT_FAILED"
                ) from exc
            finally:
                if connection is not None:
                    self._close_connection(connection, writer_lease=held)
                if created:
                    _fsync_directory(self._path.parent)

    def _load_record_connection(
        self,
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        client: PinnedProfiledTrainingExternalWitnessClientV1,
        require_pending_prior_head: bool = True,
    ) -> ProfiledTrainingExternalWitnessJournalRecordV1:
        if type(client) is not PinnedProfiledTrainingExternalWitnessClientV1:
            _fail("PROFILED_WITNESS_JOURNAL_CLIENT_EXACT_TYPE_REQUIRED")
        row = connection.execute(
            "SELECT * FROM witness_journal_operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if row is None:
            _fail("PROFILED_WITNESS_JOURNAL_OPERATION_NOT_FOUND")
        self._verify_operation_row(row)
        event_bytes, request_bytes = self._verify_request_and_event(row)
        prepared = client.prepare_compare_and_append(
            namespace=row["namespace"],
            expected_sequence=row["expected_sequence"],
            expected_event_sha256=row["expected_event_sha256"],
            event_bytes=event_bytes,
        )
        if (
            prepared.witness_id != row["witness_id"]
            or prepared.witness_public_key_sha256 != row["witness_public_key_sha256"]
            or prepared.request_sha256 != row["request_sha256"]
            or prepared.request_byte_count != row["request_byte_count"]
            or prepared.idempotency_key != row["idempotency_key"]
            or not hmac.compare_digest(prepared.request_bytes, request_bytes)
        ):
            _fail("PROFILED_WITNESS_JOURNAL_CLIENT_REAUTHENTICATION_FAILED")
        transitions = connection.execute(
            """
            SELECT * FROM witness_journal_transitions
            WHERE operation_id = ?
            ORDER BY transition_sequence
            """,
            (operation_id,),
        ).fetchall()
        if not transitions or len(transitions) not in {1, 2}:
            _fail("PROFILED_WITNESS_JOURNAL_OPERATION_LIFECYCLE_INVALID")
        prepared_transition = transitions[0]
        anchored_transition = transitions[1] if len(transitions) == 2 else None
        if anchored_transition is None and require_pending_prior_head:
            self._verify_client_prior_anchor(
                connection,
                namespace=str(row["namespace"]),
                expected_sequence=int(row["expected_sequence"]),
                client=client,
                pending_operation=row,
            )
        receipt: ProfiledTrainingObservationExternalWitnessAppendReceiptV1 | None = None
        head_bytes: bytes | None = None
        if anchored_transition is not None:
            try:
                receipt_bytes = self._cas.get(
                    anchored_transition["signed_receipt_envelope_sha256"],
                    expected_byte_count=anchored_transition["signed_receipt_envelope_byte_count"],
                )
                head_bytes = self._cas.get(
                    anchored_transition["signed_head_envelope_sha256"],
                    expected_byte_count=anchored_transition["signed_head_envelope_byte_count"],
                )
            except SourcePayloadStoreError as exc:
                raise ProfiledTrainingExternalWitnessJournalV1Error(
                    "PROFILED_WITNESS_JOURNAL_ANCHOR_CAS_INVALID"
                ) from exc
            receipt = client.verify_append_receipt_envelope(
                signed_receipt_envelope_bytes=receipt_bytes,
                expected_namespace=prepared.namespace,
                expected_sequence=prepared.expected_sequence + 1,
                expected_previous_event_sha256=prepared.expected_event_sha256,
                expected_event_sha256=prepared.event_sha256,
                expected_request_sha256=prepared.request_sha256,
                expected_idempotency_key=prepared.idempotency_key,
            )
            client.verify_signed_head_envelope(
                signed_head_envelope_bytes=head_bytes,
                expected_namespace=prepared.namespace,
                expected_sequence=receipt.sequence,
                expected_previous_event_sha256=prepared.expected_event_sha256,
                expected_event_sha256=prepared.event_sha256,
                expected_event_bytes=prepared.event_bytes,
            )
            if receipt.accepted_at != anchored_transition["receipt_accepted_at"]:
                _fail("PROFILED_WITNESS_JOURNAL_RECEIPT_CLOCK_BINDING_INVALID")
        return ProfiledTrainingExternalWitnessJournalRecordV1(
            schema_version=PROFILED_WITNESS_JOURNAL_RECORD_V1_SCHEMA_VERSION,
            operation_id=row["operation_id"],
            state=(
                PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED
                if anchored_transition is not None
                else PROFILED_WITNESS_JOURNAL_APPEND_PREPARED
            ),
            manifest_id=row["manifest_id"],
            observation_time=row["observation_time"],
            head_revision=row["head_revision"],
            candidate_id=row["candidate_id"],
            candidate_event_sha256=row["candidate_event_sha256"],
            candidate_event_byte_count=row["candidate_event_byte_count"],
            previous_completion_candidate_sha256=row["previous_completion_candidate_sha256"],
            local_staging_store_root=Path(row["local_staging_store_root"]),
            allowed_consumer_lane=row["allowed_consumer_lane"],
            prepared_transition_sequence=prepared_transition["transition_sequence"],
            prepared_transition_sha256=prepared_transition["transition_sha256"],
            anchored_transition_sequence=(
                anchored_transition["transition_sequence"]
                if anchored_transition is not None
                else None
            ),
            anchored_transition_sha256=(
                anchored_transition["transition_sha256"]
                if anchored_transition is not None
                else None
            ),
            prepared=prepared,
            append_receipt=receipt,
            signed_head_envelope_bytes=head_bytes,
            _construction_token=_RECORD_TOKEN,
        )

    def load_pending_appends(
        self,
        *,
        client: PinnedProfiledTrainingExternalWitnessClientV1,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> tuple[ProfiledTrainingExternalWitnessJournalRecordV1, ...]:
        """Return exact restart-replay material without performing network I/O."""

        with self.writer_lease(writer_lease) as held:
            connection = self._open_connection(writer_lease=held)
            try:
                self._verify_integrity_connection(connection)
                rows = connection.execute(
                    """
                    SELECT operation.operation_id
                    FROM witness_journal_operations AS operation
                    WHERE NOT EXISTS (
                        SELECT 1 FROM witness_journal_transitions AS transition
                        WHERE transition.operation_id = operation.operation_id
                          AND transition.state = 'HEAD_ANCHORED'
                    )
                    ORDER BY operation.namespace, operation.expected_sequence
                    """
                ).fetchall()
                return tuple(
                    self._load_record_connection(
                        connection,
                        operation_id=row["operation_id"],
                        client=client,
                    )
                    for row in rows
                )
            except sqlite3.Error as exc:
                raise ProfiledTrainingExternalWitnessJournalV1Error(
                    "PROFILED_WITNESS_JOURNAL_PENDING_LOAD_FAILED"
                ) from exc
            finally:
                self._close_connection(connection, writer_lease=held)

    def persisted_signed_head_envelopes_by_namespace(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> dict[str, bytes]:
        """Return CAS-verified latest envelopes for client constructor restore.

        The bytes become trusted only when the pinned client constructor verifies
        their Ed25519 signatures and bindings.
        """

        with self.writer_lease(writer_lease) as held:
            connection = self._open_connection(writer_lease=held)
            try:
                self._verify_integrity_connection(connection)
                rows = connection.execute(
                    """
                    SELECT operation.namespace,
                           transition.signed_head_envelope_sha256,
                           transition.signed_head_envelope_byte_count
                    FROM witness_journal_operations AS operation
                    JOIN witness_journal_transitions AS transition
                      ON transition.operation_id = operation.operation_id
                     AND transition.state = 'HEAD_ANCHORED'
                    WHERE operation.expected_sequence = (
                        SELECT MAX(latest.expected_sequence)
                        FROM witness_journal_operations AS latest
                        JOIN witness_journal_transitions AS latest_transition
                          ON latest_transition.operation_id = latest.operation_id
                         AND latest_transition.state = 'HEAD_ANCHORED'
                        WHERE latest.namespace = operation.namespace
                    )
                    ORDER BY operation.namespace
                    """
                ).fetchall()
                result: dict[str, bytes] = {}
                for row in rows:
                    try:
                        result[row["namespace"]] = self._cas.get(
                            row["signed_head_envelope_sha256"],
                            expected_byte_count=row["signed_head_envelope_byte_count"],
                        )
                    except SourcePayloadStoreError as exc:
                        raise ProfiledTrainingExternalWitnessJournalV1Error(
                            "PROFILED_WITNESS_JOURNAL_ANCHOR_CAS_INVALID"
                        ) from exc
                return result
            finally:
                self._close_connection(connection, writer_lease=held)

    def commit_head_anchored(
        self,
        *,
        client: PinnedProfiledTrainingExternalWitnessClientV1,
        operation_id: str,
        append_receipt: ProfiledTrainingObservationExternalWitnessAppendReceiptV1,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingExternalWitnessJournalRecordV1:
        """Reverify and append the exact signed receipt/head durability proof."""

        operation_sha = _sha256(
            operation_id,
            reason="PROFILED_WITNESS_JOURNAL_OPERATION_ID_INVALID",
        )
        if type(client) is not PinnedProfiledTrainingExternalWitnessClientV1:
            _fail("PROFILED_WITNESS_JOURNAL_CLIENT_EXACT_TYPE_REQUIRED")
        if type(append_receipt) is not ProfiledTrainingObservationExternalWitnessAppendReceiptV1:
            _fail("PROFILED_WITNESS_JOURNAL_RECEIPT_EXACT_TYPE_REQUIRED")
        append_receipt.__post_init__()

        with self.writer_lease(writer_lease) as held:
            connection: sqlite3.Connection | None = self._open_connection(writer_lease=held)
            try:
                self._verify_integrity_connection(connection)
                pending_record = self._load_record_connection(
                    connection,
                    operation_id=operation_sha,
                    client=client,
                    require_pending_prior_head=False,
                )
                if pending_record.state == PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED:
                    if pending_record.append_receipt != append_receipt:
                        _fail("PROFILED_WITNESS_JOURNAL_ANCHOR_REPLAY_CONFLICT")
                    return pending_record
                prepared = pending_record.prepared
                verified_receipt = client.verify_append_receipt_envelope(
                    signed_receipt_envelope_bytes=append_receipt.receipt_bytes,
                    expected_namespace=prepared.namespace,
                    expected_sequence=prepared.expected_sequence + 1,
                    expected_previous_event_sha256=prepared.expected_event_sha256,
                    expected_event_sha256=prepared.event_sha256,
                    expected_request_sha256=prepared.request_sha256,
                    expected_idempotency_key=prepared.idempotency_key,
                )
                if verified_receipt != append_receipt or not hmac.compare_digest(
                    verified_receipt.receipt_bytes,
                    append_receipt.receipt_bytes,
                ):
                    _fail("PROFILED_WITNESS_JOURNAL_RECEIPT_REAUTHENTICATION_FAILED")
                head_bytes = client.trusted_head_envelope_bytes(namespace=prepared.namespace)
                client.verify_signed_head_envelope(
                    signed_head_envelope_bytes=head_bytes,
                    expected_namespace=prepared.namespace,
                    expected_sequence=append_receipt.sequence,
                    expected_previous_event_sha256=prepared.expected_event_sha256,
                    expected_event_sha256=prepared.event_sha256,
                    expected_event_bytes=prepared.event_bytes,
                )
                try:
                    receipt_address = self._cas.put(
                        append_receipt.receipt_bytes,
                        expected_sha256=append_receipt.receipt_sha256,
                        expected_byte_count=len(append_receipt.receipt_bytes),
                    )
                    head_address = self._cas.put(head_bytes)
                except SourcePayloadStoreError as exc:
                    raise ProfiledTrainingExternalWitnessJournalV1Error(
                        "PROFILED_WITNESS_JOURNAL_ANCHOR_CAS_PERSIST_FAILED"
                    ) from exc

                connection.execute("BEGIN IMMEDIATE")
                self._verify_integrity_connection(connection)
                existing = connection.execute(
                    """
                    SELECT * FROM witness_journal_transitions
                    WHERE operation_id = ? AND state = 'HEAD_ANCHORED'
                    """,
                    (operation_sha,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["signed_receipt_envelope_sha256"] != receipt_address.payload_sha256
                        or existing["signed_head_envelope_sha256"] != head_address.payload_sha256
                    ):
                        _fail("PROFILED_WITNESS_JOURNAL_ANCHOR_REPLAY_CONFLICT")
                    connection.execute("COMMIT")
                else:
                    prior_sequence, prior_transition_sha = self._latest_transition_identity(
                        connection
                    )
                    transition = self._transition_material(
                        transition_sequence=prior_sequence + 1,
                        previous_transition_sha256=prior_transition_sha,
                        operation_id=operation_sha,
                        state=PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED,
                        journaled_at=_journaled_at(),
                        receipt_sequence=append_receipt.sequence,
                        receipt_previous_event_sha256=(append_receipt.previous_event_sha256),
                        receipt_event_sha256=append_receipt.event_sha256,
                        receipt_accepted_at=append_receipt.accepted_at,
                        signed_receipt_envelope_sha256=(receipt_address.payload_sha256),
                        signed_receipt_envelope_byte_count=(receipt_address.payload_byte_count),
                        signed_head_envelope_sha256=head_address.payload_sha256,
                        signed_head_envelope_byte_count=head_address.payload_byte_count,
                    )
                    self._insert_transition(connection, material=transition)
                    self._verify_integrity_connection(connection)
                    connection.execute("COMMIT")
                committed_connection = connection
                connection = None
                self._close_connection(committed_connection, writer_lease=held)
                connection = self._open_connection(writer_lease=held)
                self._verify_integrity_connection(connection)
                return self._load_record_connection(
                    connection,
                    operation_id=operation_sha,
                    client=client,
                )
            except ProfiledTrainingExternalWitnessJournalV1Error:
                if connection is not None:
                    try:
                        if connection.in_transaction:
                            connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                raise
            except sqlite3.Error as exc:
                if connection is not None:
                    try:
                        if connection.in_transaction:
                            connection.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
                raise ProfiledTrainingExternalWitnessJournalV1Error(
                    "PROFILED_WITNESS_JOURNAL_ANCHOR_COMMIT_FAILED"
                ) from exc
            finally:
                if connection is not None:
                    self._close_connection(connection, writer_lease=held)


__all__ = (
    "MAX_PROFILED_WITNESS_JOURNAL_MATERIAL_BYTES",
    "MAX_PROFILED_WITNESS_JOURNAL_TRANSITIONS",
    "PROFILED_WITNESS_JOURNAL_APPEND_PREPARED",
    "PROFILED_WITNESS_JOURNAL_GENESIS_TRANSITION_SHA256",
    "PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED",
    "PROFILED_WITNESS_JOURNAL_INTEGRITY_REPORT_V1_SCHEMA_VERSION",
    "PROFILED_WITNESS_JOURNAL_OPERATION_V1_SCHEMA_VERSION",
    "PROFILED_WITNESS_JOURNAL_RECORD_V1_SCHEMA_VERSION",
    "PROFILED_WITNESS_JOURNAL_TRANSITION_V1_SCHEMA_VERSION",
    "PROFILED_WITNESS_JOURNAL_V1_SCHEMA_VERSION",
    "ProfiledTrainingExternalWitnessJournalIntegrityReportV1",
    "ProfiledTrainingExternalWitnessJournalRecordV1",
    "ProfiledTrainingExternalWitnessJournalV1",
    "ProfiledTrainingExternalWitnessJournalV1Error",
)
