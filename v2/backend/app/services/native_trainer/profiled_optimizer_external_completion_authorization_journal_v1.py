"""Crash-safe journal for profiled optimizer completion authorization.

The journal is a local durability boundary only.  It performs no network I/O
and grants no optimizer, checkpoint, model, prediction, paper, live, order, or
execution authority.  Exact one-time challenge, claim-template, request,
completion, final-page, witness-key, and signed-envelope bytes are persisted in
immutable SHA-256 CAS.  SQLite records only append-only identities and a
globally chained PREPARED/ANCHORED lifecycle.
"""

from __future__ import annotations

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

from .profiled_optimizer_external_completion_request_v1 import (
    PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256,
    ProfiledOptimizerExternalCompletionPreparedRequestV1,
    ProfiledOptimizerExternalCompletionRequestV1Error,
    VerifiedProfiledOptimizerExternalCompletionResponseV1,
    rehydrate_profiled_optimizer_external_completion_prepared_request_v1,
    verify_profiled_optimizer_external_completion_response_v1,
)

PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_JOURNAL_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_completion_authorization_journal_v1"
)
PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_OPERATION_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_completion_authorization_journal_operation_v1"
)
PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_TRANSITION_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_completion_authorization_journal_transition_v1"
)
PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RECORD_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_completion_authorization_journal_record_v1"
)
PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_INTEGRITY_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_completion_authorization_journal_integrity_v1"
)
PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_CHAIN_HEAD_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_completion_authorization_chain_head_v1"
)

REQUEST_PREPARED: Final = "REQUEST_PREPARED"
AUTHORIZATION_ANCHORED: Final = "AUTHORIZATION_ANCHORED"
AUTHORIZATION_JOURNAL_OPERATION_ID_DOMAIN: Final = (
    "v2/native-trainer/profiled-optimizer-completion-authorization-journal-operation/v1"
)
AUTHORIZATION_JOURNAL_TRANSITION_DOMAIN: Final = (
    "v2/native-trainer/profiled-optimizer-completion-authorization-journal-transition/v1"
)
AUTHORIZATION_JOURNAL_GENESIS_TRANSITION_SHA256: Final = (
    "ab21467c225651410727e11e28b67bc74e616564c133da96d1bd9051fb2dd732"
)

# Storage/integrity limits only; these do not select markets, samples, risk,
# leverage, margin, or optimizer behavior.
AUTHORIZATION_JOURNAL_APPLICATION_ID: Final = 0x43414A31  # ASCII ``CAJ1``.
AUTHORIZATION_JOURNAL_USER_VERSION: Final = 1
MAX_AUTHORIZATION_JOURNAL_TRANSITIONS: Final = 100_000
MAX_AUTHORIZATION_JOURNAL_MATERIAL_BYTES: Final = 2 * 1024 * 1024
MAX_AUTHORIZATION_JOURNAL_JSON_NODES: Final = 100_000
MAX_AUTHORIZATION_JOURNAL_JSON_DEPTH: Final = 64
SQLITE_BUSY_TIMEOUT_MILLISECONDS: Final = 60_000
ED25519_PUBLIC_KEY_BYTES: Final = 32

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_RECORD_TOKEN = object()
_REPORT_TOKEN = object()
_CHAIN_HEAD_TOKEN = object()

_PREPARED_AUTHORITY_FIELDS: Final = (
    "external_monotonic_manifest_head_verified",
    "full_consumption_external_ack_verified",
    "profiled_optimizer_admission_authorized",
    "optimizer_execution_authorized",
    "checkpoint_write_authorized",
    "model_write_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "order_submission_authorized",
    "execution_authorized",
    "runtime_wired",
)


class ProfiledOptimizerCompletionAuthorizationJournalV1Error(RuntimeError):
    """The completion-authorization journal failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _valid_identifier(value: object) -> bool:
    return type(value) is str and _IDENTIFIER_RE.fullmatch(value) is not None


def _clock(value: object, *, reason: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    if value != canonical:
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


def _bounded_json_tree(value: object, *, reason: str) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    node_count = 0
    text_bytes = 0
    while stack:
        item, depth = stack.pop()
        node_count += 1
        if (
            node_count > MAX_AUTHORIZATION_JOURNAL_JSON_NODES
            or depth > MAX_AUTHORIZATION_JOURNAL_JSON_DEPTH
        ):
            _fail(reason)
        if type(item) is dict:
            for key, child in cast(dict[object, object], item).items():
                if type(key) is not str or not key or not key.isascii():
                    _fail(reason)
                text_bytes += len(key.encode("ascii"))
                stack.append((child, depth + 1))
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in cast(list[object], item))
        elif type(item) is str:
            if not item.isascii():
                _fail(reason)
            text_bytes += len(item.encode("ascii"))
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            if not -(2**63) <= item <= 2**63 - 1:
                _fail(reason)
        else:
            _fail(reason)
        if text_bytes > MAX_AUTHORIZATION_JOURNAL_MATERIAL_BYTES:
            _fail(reason)


def _canonical_json_bytes(value: object, *, reason: str) -> bytes:
    _bounded_json_tree(value, reason=reason)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(reason) from exc
    if not encoded or len(encoded) > MAX_AUTHORIZATION_JOURNAL_MATERIAL_BYTES:
        _fail(reason)
    return encoded


def _strict_json(raw: bytes, *, reason: str) -> dict[str, Any]:
    if (
        type(raw) is not bytes
        or not raw
        or len(raw) > MAX_AUTHORIZATION_JOURNAL_MATERIAL_BYTES
    ):
        _fail(reason)

    def reject_constant(_value: str) -> NoReturn:
        _fail(reason)

    def reject_float(_value: str) -> NoReturn:
        _fail(reason)

    def parse_integer(value: str) -> int:
        digits = value[1:] if value.startswith("-") else value
        if not digits or len(digits) > 19:
            _fail(reason)
        parsed = int(value)
        if not -(2**63) <= parsed <= 2**63 - 1:
            _fail(reason)
        return parsed

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if type(key) is not str or key in result:
                _fail(reason)
            result[key] = item
        return result

    try:
        value = json.loads(
            raw.decode("ascii", errors="strict"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
            parse_float=reject_float,
            parse_int=parse_integer,
        )
    except ProfiledOptimizerCompletionAuthorizationJournalV1Error:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(reason) from exc
    if type(value) is not dict:
        _fail(reason)
    material = cast(dict[str, Any], value)
    _bounded_json_tree(material, reason=reason)
    if not hmac.compare_digest(_canonical_json_bytes(material, reason=reason), raw):
        _fail(reason)
    return material


def _absolute_path(value: Path, *, reason: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute() or ".." in value.parts:
        _fail(reason)
    return value


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        os.fsync(descriptor)
    except OSError as exc:
        raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_DIRECTORY_FSYNC_FAILED"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _operation_id(material_bytes: bytes) -> str:
    return hashlib.sha256(
        AUTHORIZATION_JOURNAL_OPERATION_ID_DOMAIN.encode("ascii")
        + b"\0"
        + material_bytes
    ).hexdigest()


def _transition_sha256(material_bytes: bytes) -> str:
    return hashlib.sha256(
        AUTHORIZATION_JOURNAL_TRANSITION_DOMAIN.encode("ascii")
        + b"\0"
        + material_bytes
    ).hexdigest()


def _prepared_authority_false(
    prepared: ProfiledOptimizerExternalCompletionPreparedRequestV1,
) -> dict[str, bool]:
    result = {name: getattr(prepared, name) for name in _PREPARED_AUTHORITY_FIELDS}
    if any(type(value) is not bool or value for value in result.values()):
        _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_AUTHORITY_MUST_REMAIN_FALSE")
    return cast(dict[str, bool], result)


_SCHEMA_DDL: Final = (
    """
    CREATE TABLE authorization_journal_metadata (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version TEXT NOT NULL,
        genesis_transition_sha256 TEXT NOT NULL,
        created_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE authorization_journal_operations (
        operation_id TEXT PRIMARY KEY,
        witness_id TEXT NOT NULL,
        witness_public_key_sha256 TEXT NOT NULL,
        namespace TEXT NOT NULL,
        expected_authorization_sequence INTEGER NOT NULL
            CHECK (expected_authorization_sequence >= 0),
        expected_previous_authorization_event_sha256 TEXT NOT NULL,
        authorization_sequence INTEGER NOT NULL CHECK (authorization_sequence > 0),
        manifest_id TEXT NOT NULL,
        completion_event_sha256 TEXT NOT NULL,
        completion_event_byte_count INTEGER NOT NULL CHECK (completion_event_byte_count > 0),
        final_page_receipt_event_sha256 TEXT NOT NULL,
        final_page_receipt_event_byte_count INTEGER NOT NULL
            CHECK (final_page_receipt_event_byte_count > 0),
        manifest_head_namespace TEXT NOT NULL,
        manifest_head_sequence INTEGER NOT NULL CHECK (manifest_head_sequence > 0),
        manifest_head_event_sha256 TEXT NOT NULL,
        manifest_head_operation_id TEXT NOT NULL,
        authorization_challenge_cas_sha256 TEXT NOT NULL UNIQUE,
        authorization_challenge_byte_count INTEGER NOT NULL
            CHECK (authorization_challenge_byte_count = 32),
        authorization_claim_template_cas_sha256 TEXT NOT NULL,
        authorization_claim_template_byte_count INTEGER NOT NULL
            CHECK (authorization_claim_template_byte_count > 0),
        request_cas_sha256 TEXT NOT NULL UNIQUE,
        request_byte_count INTEGER NOT NULL CHECK (request_byte_count > 0),
        request_sha256 TEXT NOT NULL UNIQUE,
        idempotency_key TEXT NOT NULL UNIQUE,
        completion_event_cas_sha256 TEXT NOT NULL,
        final_page_receipt_event_cas_sha256 TEXT NOT NULL,
        witness_public_key_cas_sha256 TEXT NOT NULL,
        witness_public_key_byte_count INTEGER NOT NULL
            CHECK (witness_public_key_byte_count = 32),
        external_monotonic_manifest_head_verified INTEGER NOT NULL
            CHECK (external_monotonic_manifest_head_verified = 0),
        full_consumption_external_ack_verified INTEGER NOT NULL
            CHECK (full_consumption_external_ack_verified = 0),
        profiled_optimizer_admission_authorized INTEGER NOT NULL
            CHECK (profiled_optimizer_admission_authorized = 0),
        optimizer_execution_authorized INTEGER NOT NULL
            CHECK (optimizer_execution_authorized = 0),
        checkpoint_write_authorized INTEGER NOT NULL
            CHECK (checkpoint_write_authorized = 0),
        model_write_authorized INTEGER NOT NULL CHECK (model_write_authorized = 0),
        prediction_authorized INTEGER NOT NULL CHECK (prediction_authorized = 0),
        paper_trading_authorized INTEGER NOT NULL CHECK (paper_trading_authorized = 0),
        live_execution_authorized INTEGER NOT NULL CHECK (live_execution_authorized = 0),
        order_submission_authorized INTEGER NOT NULL
            CHECK (order_submission_authorized = 0),
        execution_authorized INTEGER NOT NULL CHECK (execution_authorized = 0),
        runtime_wired INTEGER NOT NULL CHECK (runtime_wired = 0),
        operation_material_json TEXT NOT NULL,
        UNIQUE (witness_id, namespace, completion_event_sha256),
        UNIQUE (witness_id, namespace, authorization_sequence),
        CHECK (authorization_sequence = expected_authorization_sequence + 1)
    ) STRICT
    """,
    """
    CREATE TABLE authorization_journal_transitions (
        transition_sequence INTEGER PRIMARY KEY CHECK (transition_sequence > 0),
        previous_transition_sha256 TEXT NOT NULL,
        transition_sha256 TEXT NOT NULL UNIQUE,
        operation_id TEXT NOT NULL REFERENCES authorization_journal_operations(operation_id),
        state TEXT NOT NULL
            CHECK (state IN ('REQUEST_PREPARED', 'AUTHORIZATION_ANCHORED')),
        authorization_sequence INTEGER,
        authorization_previous_event_sha256 TEXT,
        authorization_accepted_at TEXT,
        authorization_envelope_sha256 TEXT,
        authorization_envelope_byte_count INTEGER,
        external_monotonic_manifest_head_verified INTEGER,
        full_consumption_external_ack_verified INTEGER,
        profiled_optimizer_admission_authorized INTEGER,
        optimizer_execution_authorized INTEGER,
        checkpoint_write_authorized INTEGER,
        model_write_authorized INTEGER,
        prediction_authorized INTEGER,
        paper_trading_authorized INTEGER,
        live_execution_authorized INTEGER,
        order_submission_authorized INTEGER,
        execution_authorized INTEGER,
        runtime_wired INTEGER,
        journaled_at TEXT NOT NULL,
        transition_material_json TEXT NOT NULL,
        UNIQUE (operation_id, state),
        CHECK (
            (state = 'REQUEST_PREPARED'
             AND authorization_sequence IS NULL
             AND authorization_previous_event_sha256 IS NULL
             AND authorization_accepted_at IS NULL
             AND authorization_envelope_sha256 IS NULL
             AND authorization_envelope_byte_count IS NULL
             AND external_monotonic_manifest_head_verified IS NULL
             AND full_consumption_external_ack_verified IS NULL
             AND profiled_optimizer_admission_authorized IS NULL
             AND optimizer_execution_authorized IS NULL
             AND checkpoint_write_authorized IS NULL
             AND model_write_authorized IS NULL
             AND prediction_authorized IS NULL
             AND paper_trading_authorized IS NULL
             AND live_execution_authorized IS NULL
             AND order_submission_authorized IS NULL
             AND execution_authorized IS NULL
             AND runtime_wired IS NULL)
            OR
            (state = 'AUTHORIZATION_ANCHORED'
             AND authorization_sequence > 0
             AND authorization_previous_event_sha256 IS NOT NULL
             AND authorization_accepted_at IS NOT NULL
             AND authorization_envelope_sha256 IS NOT NULL
             AND authorization_envelope_byte_count > 0
             AND external_monotonic_manifest_head_verified = 1
             AND full_consumption_external_ack_verified = 1
             AND profiled_optimizer_admission_authorized = 1
             AND optimizer_execution_authorized = 0
             AND checkpoint_write_authorized = 0
             AND model_write_authorized = 0
             AND prediction_authorized = 0
             AND paper_trading_authorized = 0
             AND live_execution_authorized = 0
             AND order_submission_authorized = 0
             AND execution_authorized = 0
             AND runtime_wired = 0)
        )
    ) STRICT
    """,
    """
    CREATE INDEX authorization_journal_operations_namespace_idx
    ON authorization_journal_operations(namespace, authorization_sequence)
    """,
    """
    CREATE INDEX authorization_journal_transitions_operation_idx
    ON authorization_journal_transitions(operation_id, transition_sequence)
    """,
    """
    CREATE TRIGGER authorization_journal_metadata_update_forbidden
    BEFORE UPDATE ON authorization_journal_metadata
    BEGIN SELECT RAISE(ABORT, 'authorization_journal_metadata_update_forbidden'); END
    """,
    """
    CREATE TRIGGER authorization_journal_metadata_delete_forbidden
    BEFORE DELETE ON authorization_journal_metadata
    BEGIN SELECT RAISE(ABORT, 'authorization_journal_metadata_delete_forbidden'); END
    """,
    """
    CREATE TRIGGER authorization_journal_operations_update_forbidden
    BEFORE UPDATE ON authorization_journal_operations
    BEGIN SELECT RAISE(ABORT, 'authorization_journal_operations_update_forbidden'); END
    """,
    """
    CREATE TRIGGER authorization_journal_operations_delete_forbidden
    BEFORE DELETE ON authorization_journal_operations
    BEGIN SELECT RAISE(ABORT, 'authorization_journal_operations_delete_forbidden'); END
    """,
    """
    CREATE TRIGGER authorization_journal_transitions_update_forbidden
    BEFORE UPDATE ON authorization_journal_transitions
    BEGIN SELECT RAISE(ABORT, 'authorization_journal_transitions_update_forbidden'); END
    """,
    """
    CREATE TRIGGER authorization_journal_transitions_delete_forbidden
    BEFORE DELETE ON authorization_journal_transitions
    BEGIN SELECT RAISE(ABORT, 'authorization_journal_transitions_delete_forbidden'); END
    """,
    """
    CREATE TRIGGER authorization_journal_one_pending_per_namespace
    BEFORE INSERT ON authorization_journal_operations
    WHEN EXISTS (
        SELECT 1
        FROM authorization_journal_operations AS operation
        WHERE operation.namespace = NEW.namespace
          AND NOT EXISTS (
              SELECT 1 FROM authorization_journal_transitions AS transition
              WHERE transition.operation_id = operation.operation_id
                AND transition.state = 'AUTHORIZATION_ANCHORED'
          )
    )
    BEGIN SELECT RAISE(ABORT, 'authorization_journal_namespace_pending_exists'); END
    """,
    """
    CREATE TRIGGER authorization_journal_operation_predecessor_required
    BEFORE INSERT ON authorization_journal_operations
    WHEN (
        NOT EXISTS (
            SELECT 1
            FROM authorization_journal_operations AS prior_operation
            JOIN authorization_journal_transitions AS prior_anchor
              ON prior_anchor.operation_id = prior_operation.operation_id
             AND prior_anchor.state = 'AUTHORIZATION_ANCHORED'
            WHERE prior_operation.namespace = NEW.namespace
        )
        AND (
            NEW.expected_authorization_sequence != 0
            OR NEW.expected_previous_authorization_event_sha256 !=
               'd9de4814347b6c7b99ee7956ba32f7ad6d023fd49040edb8b0dfced051339e75'
        )
    ) OR (
        EXISTS (
            SELECT 1
            FROM authorization_journal_operations AS prior_operation
            JOIN authorization_journal_transitions AS prior_anchor
              ON prior_anchor.operation_id = prior_operation.operation_id
             AND prior_anchor.state = 'AUTHORIZATION_ANCHORED'
            WHERE prior_operation.namespace = NEW.namespace
        )
        AND NOT EXISTS (
            SELECT 1
            FROM authorization_journal_operations AS prior_operation
            JOIN authorization_journal_transitions AS prior_anchor
              ON prior_anchor.operation_id = prior_operation.operation_id
             AND prior_anchor.state = 'AUTHORIZATION_ANCHORED'
            WHERE prior_operation.namespace = NEW.namespace
              AND prior_operation.authorization_sequence =
                  NEW.expected_authorization_sequence
              AND prior_anchor.authorization_envelope_sha256 =
                  NEW.expected_previous_authorization_event_sha256
              AND prior_operation.witness_id = NEW.witness_id
              AND prior_operation.witness_public_key_sha256 =
                  NEW.witness_public_key_sha256
              AND NOT EXISTS (
                  SELECT 1
                  FROM authorization_journal_operations AS later_operation
                  JOIN authorization_journal_transitions AS later_anchor
                    ON later_anchor.operation_id = later_operation.operation_id
                   AND later_anchor.state = 'AUTHORIZATION_ANCHORED'
                  WHERE later_operation.namespace = NEW.namespace
                    AND later_operation.authorization_sequence >
                        prior_operation.authorization_sequence
              )
        )
    )
    BEGIN SELECT RAISE(ABORT, 'authorization_journal_predecessor_invalid'); END
    """,
    """
    CREATE TRIGGER authorization_journal_transition_chain_required
    BEFORE INSERT ON authorization_journal_transitions
    WHEN NEW.transition_sequence != COALESCE(
             (SELECT MAX(transition_sequence) + 1 FROM authorization_journal_transitions),
             1
         )
      OR NEW.previous_transition_sha256 != COALESCE(
             (SELECT transition_sha256
              FROM authorization_journal_transitions
              ORDER BY transition_sequence DESC LIMIT 1),
             'ab21467c225651410727e11e28b67bc74e616564c133da96d1bd9051fb2dd732'
         )
    BEGIN SELECT RAISE(ABORT, 'authorization_journal_transition_chain_invalid'); END
    """,
    """
    CREATE TRIGGER authorization_journal_transition_lifecycle_required
    BEFORE INSERT ON authorization_journal_transitions
    WHEN (
        NEW.state = 'REQUEST_PREPARED'
        AND EXISTS (
            SELECT 1 FROM authorization_journal_transitions
            WHERE operation_id = NEW.operation_id
        )
    ) OR (
        NEW.state = 'AUTHORIZATION_ANCHORED'
        AND (
            NOT EXISTS (
                SELECT 1 FROM authorization_journal_transitions
                WHERE operation_id = NEW.operation_id
                  AND state = 'REQUEST_PREPARED'
            )
            OR EXISTS (
                SELECT 1 FROM authorization_journal_transitions
                WHERE operation_id = NEW.operation_id
                  AND state = 'AUTHORIZATION_ANCHORED'
            )
        )
    )
    BEGIN SELECT RAISE(ABORT, 'authorization_journal_transition_lifecycle_invalid'); END
    """,
    """
    CREATE TRIGGER authorization_journal_anchor_binding_required
    BEFORE INSERT ON authorization_journal_transitions
    WHEN NEW.state = 'AUTHORIZATION_ANCHORED'
      AND NOT EXISTS (
          SELECT 1 FROM authorization_journal_operations AS operation
          WHERE operation.operation_id = NEW.operation_id
            AND NEW.authorization_sequence = operation.authorization_sequence
            AND NEW.authorization_previous_event_sha256 =
                operation.expected_previous_authorization_event_sha256
      )
    BEGIN SELECT RAISE(ABORT, 'authorization_journal_anchor_binding_invalid'); END
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


@dataclass(frozen=True, slots=True)
class ProfiledOptimizerCompletionAuthorizationJournalRecordV1:
    schema_version: str
    operation_id: str
    state: str
    prepared_transition_sequence: int
    prepared_transition_sha256: str
    anchored_transition_sequence: int | None
    anchored_transition_sha256: str | None
    prepared: ProfiledOptimizerExternalCompletionPreparedRequestV1 = field(repr=False)
    verified: VerifiedProfiledOptimizerExternalCompletionResponseV1 | None = field(
        default=None,
        repr=False,
    )
    _construction_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        anchored = self.state == AUTHORIZATION_ANCHORED
        if (
            self._construction_token is not _RECORD_TOKEN
            or self.schema_version
            != PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RECORD_V1_SCHEMA_VERSION
            or not _valid_sha256(self.operation_id)
            or self.state not in {REQUEST_PREPARED, AUTHORIZATION_ANCHORED}
            or type(self.prepared) is not ProfiledOptimizerExternalCompletionPreparedRequestV1
            or type(self.prepared_transition_sequence) is not int
            or self.prepared_transition_sequence <= 0
            or not _valid_sha256(self.prepared_transition_sha256)
            or anchored
            != (
                self.anchored_transition_sequence is not None
                and self.anchored_transition_sha256 is not None
                and self.verified is not None
            )
            or (
                anchored
                and (
                    type(self.anchored_transition_sequence) is not int
                    or self.anchored_transition_sequence <= self.prepared_transition_sequence
                    or not _valid_sha256(self.anchored_transition_sha256)
                    or type(self.verified)
                    is not VerifiedProfiledOptimizerExternalCompletionResponseV1
                    or self.verified.request_sha256 != self.prepared.request_sha256
                )
            )
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_RECORD_INVALID")
        self.prepared.__post_init__()
        if self.verified is not None:
            self.verified.__post_init__()


@dataclass(frozen=True, slots=True)
class ProfiledOptimizerCompletionAuthorizationJournalIntegrityV1:
    schema_version: str
    operation_count: int
    transition_count: int
    prepared_count: int
    anchored_count: int
    pending_count: int
    namespace_count: int
    terminal_transition_sha256: str
    optimizer_execution_authorized: bool = False
    checkpoint_write_authorized: bool = False
    model_write_authorized: bool = False
    prediction_authorized: bool = False
    paper_trading_authorized: bool = False
    live_execution_authorized: bool = False
    order_submission_authorized: bool = False
    execution_authorized: bool = False
    runtime_wired: bool = False
    _construction_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _REPORT_TOKEN
            or self.schema_version
            != PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_INTEGRITY_V1_SCHEMA_VERSION
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
                    self.optimizer_execution_authorized,
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
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_INTEGRITY_INVALID")


@dataclass(frozen=True, slots=True)
class ProfiledOptimizerCompletionAuthorizationChainHeadV1:
    schema_version: str
    witness_id: str
    witness_public_key_sha256: str
    namespace: str
    expected_authorization_sequence: int
    expected_previous_authorization_event_sha256: str
    pending_operation_id: str | None
    _construction_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _CHAIN_HEAD_TOKEN
            or self.schema_version
            != PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_CHAIN_HEAD_V1_SCHEMA_VERSION
            or not _valid_identifier(self.witness_id)
            or not _valid_sha256(self.witness_public_key_sha256)
            or not _valid_identifier(self.namespace)
            or type(self.expected_authorization_sequence) is not int
            or not 0 <= self.expected_authorization_sequence <= 2**63 - 2
            or not _valid_sha256(self.expected_previous_authorization_event_sha256)
            or (
                self.expected_authorization_sequence == 0
                and self.expected_previous_authorization_event_sha256
                != PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
            )
            or (
                self.expected_authorization_sequence > 0
                and self.expected_previous_authorization_event_sha256
                == PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
            )
            or (
                self.pending_operation_id is not None
                and not _valid_sha256(self.pending_operation_id)
            )
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_CHAIN_HEAD_INVALID")


class ProfiledOptimizerCompletionAuthorizationJournalV1:
    """Append-only PREPARED/ANCHORED journal with immutable CAS evidence."""

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
            reason="PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PATH_INVALID",
        )
        if type(immutable_store) is not ImmutableSourcePayloadStore:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_CAS_EXACT_TYPE_REQUIRED")
        self._cas = immutable_store
        if writer_lease is not None:
            try:
                FeatureSnapshotWriterLease.require_exact(writer_lease, self._path)
            except FeatureSnapshotLedgerError as exc:
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    f"PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_LEASE_INVALID:{exc}"
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
            raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                f"PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_LEASE_INVALID:{exc}"
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
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_WAL_REQUIRED")
            connection.execute("PRAGMA synchronous=FULL")
            if int(connection.execute("PRAGMA synchronous").fetchone()[0]) != 2:
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_SYNC_FULL_REQUIRED")
            if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_FOREIGN_KEYS_REQUIRED")
            FeatureSnapshotWriterLease.require_exact(held, self._path)
            return connection
        except ProfiledOptimizerCompletionAuthorizationJournalV1Error:
            if "connection" in locals():
                connection.close()
            raise
        except (FeatureSnapshotLedgerError, sqlite3.Error) as exc:
            if "connection" in locals():
                connection.close()
            raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_CONNECTION_FAILED"
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
            raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_CONNECTION_CLOSE_FAILED"
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
                    INSERT INTO authorization_journal_metadata (
                        singleton, schema_version, genesis_transition_sha256, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        1,
                        PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_JOURNAL_V1_SCHEMA_VERSION,
                        AUTHORIZATION_JOURNAL_GENESIS_TRANSITION_SHA256,
                        _journaled_at(),
                    ),
                )
                connection.execute(
                    f"PRAGMA application_id={AUTHORIZATION_JOURNAL_APPLICATION_ID}"
                )
                connection.execute(f"PRAGMA user_version={AUTHORIZATION_JOURNAL_USER_VERSION}")
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
            != AUTHORIZATION_JOURNAL_APPLICATION_ID
            or int(connection.execute("PRAGMA user_version").fetchone()[0])
            != AUTHORIZATION_JOURNAL_USER_VERSION
            or _schema_signature(connection) != _expected_schema_signature()
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_SCHEMA_INVALID")
        rows = connection.execute(
            """
            SELECT singleton, schema_version, genesis_transition_sha256, created_at
            FROM authorization_journal_metadata
            """
        ).fetchall()
        if len(rows) != 1:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_METADATA_INVALID")
        row = rows[0]
        if (
            row["singleton"] != 1
            or row["schema_version"]
            != PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_JOURNAL_V1_SCHEMA_VERSION
            or row["genesis_transition_sha256"]
            != AUTHORIZATION_JOURNAL_GENESIS_TRANSITION_SHA256
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_METADATA_INVALID")
        _clock(
            row["created_at"],
            reason="PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_METADATA_CLOCK_INVALID",
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
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_INITIALIZE_FAILED"
                ) from exc
            finally:
                self._close_connection(connection, writer_lease=held)
            if created:
                _fsync_directory(self._path.parent)

    @staticmethod
    def _validate_prepared_and_key(
        *,
        prepared: ProfiledOptimizerExternalCompletionPreparedRequestV1,
        witness_public_key_bytes: bytes,
    ) -> None:
        if type(prepared) is not ProfiledOptimizerExternalCompletionPreparedRequestV1:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PREPARED_EXACT_TYPE_REQUIRED")
        prepared.__post_init__()
        if (
            type(witness_public_key_bytes) is not bytes
            or len(witness_public_key_bytes) != ED25519_PUBLIC_KEY_BYTES
            or hashlib.sha256(witness_public_key_bytes).hexdigest()
            != prepared.witness_public_key_sha256
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_WITNESS_KEY_INVALID")
        _prepared_authority_false(prepared)

    @staticmethod
    def _operation_material(
        *,
        prepared: ProfiledOptimizerExternalCompletionPreparedRequestV1,
        witness_public_key_bytes: bytes,
    ) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_OPERATION_V1_SCHEMA_VERSION
            ),
            "witness_id": prepared.witness_id,
            "witness_public_key_sha256": prepared.witness_public_key_sha256,
            "namespace": prepared.authorization_namespace,
            "expected_authorization_sequence": prepared.expected_authorization_sequence,
            "expected_previous_authorization_event_sha256": (
                prepared.expected_previous_authorization_event_sha256
            ),
            "authorization_sequence": prepared.expected_authorization_sequence + 1,
            "manifest_id": prepared.manifest_id,
            "completion_event_sha256": prepared.completion_event_sha256,
            "completion_event_byte_count": prepared.completion_event_byte_count,
            "final_page_receipt_event_sha256": (
                prepared.final_page_receipt_event_sha256
            ),
            "final_page_receipt_event_byte_count": (
                prepared.final_page_receipt_event_byte_count
            ),
            "manifest_head_namespace": prepared.manifest_head_namespace,
            "manifest_head_sequence": prepared.manifest_head_sequence,
            "manifest_head_event_sha256": prepared.manifest_head_event_sha256,
            "manifest_head_operation_id": prepared.manifest_head_operation_id,
            "authorization_challenge_cas_sha256": (
                prepared.authorization_challenge_sha256
            ),
            "authorization_challenge_byte_count": len(prepared.authorization_challenge),
            "authorization_claim_template_cas_sha256": (
                prepared.authorization_claim_template_sha256
            ),
            "authorization_claim_template_byte_count": len(
                prepared.authorization_claim_template
            ),
            "request_cas_sha256": prepared.request_sha256,
            "request_byte_count": prepared.request_byte_count,
            "request_sha256": prepared.request_sha256,
            "idempotency_key": prepared.idempotency_key,
            "completion_event_cas_sha256": prepared.completion_event_sha256,
            "final_page_receipt_event_cas_sha256": (
                prepared.final_page_receipt_event_sha256
            ),
            "witness_public_key_cas_sha256": hashlib.sha256(
                witness_public_key_bytes
            ).hexdigest(),
            "witness_public_key_byte_count": len(witness_public_key_bytes),
            **_prepared_authority_false(prepared),
        }

    @staticmethod
    def _operation_material_from_row(row: sqlite3.Row) -> dict[str, Any]:
        names = (
            "witness_id",
            "witness_public_key_sha256",
            "namespace",
            "expected_authorization_sequence",
            "expected_previous_authorization_event_sha256",
            "authorization_sequence",
            "manifest_id",
            "completion_event_sha256",
            "completion_event_byte_count",
            "final_page_receipt_event_sha256",
            "final_page_receipt_event_byte_count",
            "manifest_head_namespace",
            "manifest_head_sequence",
            "manifest_head_event_sha256",
            "manifest_head_operation_id",
            "authorization_challenge_cas_sha256",
            "authorization_challenge_byte_count",
            "authorization_claim_template_cas_sha256",
            "authorization_claim_template_byte_count",
            "request_cas_sha256",
            "request_byte_count",
            "request_sha256",
            "idempotency_key",
            "completion_event_cas_sha256",
            "final_page_receipt_event_cas_sha256",
            "witness_public_key_cas_sha256",
            "witness_public_key_byte_count",
        )
        authority: dict[str, bool] = {}
        for name in _PREPARED_AUTHORITY_FIELDS:
            if type(row[name]) is not int or row[name] != 0:
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_AUTHORITY_ROW_INVALID")
            authority[name] = False
        return {
            "schema_version": (
                PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_OPERATION_V1_SCHEMA_VERSION
            ),
            **{name: row[name] for name in names},
            **authority,
        }

    @staticmethod
    def _transition_material(
        *,
        transition_sequence: int,
        previous_transition_sha256: str,
        operation_id: str,
        state: str,
        journaled_at: str,
        authorization_sequence: int | None = None,
        authorization_previous_event_sha256: str | None = None,
        authorization_accepted_at: str | None = None,
        authorization_envelope_sha256: str | None = None,
        authorization_envelope_byte_count: int | None = None,
        authorization_authority: Mapping[str, bool] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": (
                PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_TRANSITION_V1_SCHEMA_VERSION
            ),
            "transition_sequence": transition_sequence,
            "previous_transition_sha256": previous_transition_sha256,
            "operation_id": operation_id,
            "state": state,
            "journaled_at": journaled_at,
            "authorization": (
                None
                if state == REQUEST_PREPARED
                else {
                    "sequence": authorization_sequence,
                    "previous_event_sha256": authorization_previous_event_sha256,
                    "accepted_at": authorization_accepted_at,
                    "envelope_sha256": authorization_envelope_sha256,
                    "envelope_byte_count": authorization_envelope_byte_count,
                    "external_monotonic_manifest_head_verified": (
                        None
                        if authorization_authority is None
                        else authorization_authority[
                            "external_monotonic_manifest_head_verified"
                        ]
                    ),
                    "full_consumption_external_ack_verified": (
                        None
                        if authorization_authority is None
                        else authorization_authority[
                            "full_consumption_external_ack_verified"
                        ]
                    ),
                    "profiled_optimizer_admission_authorized": (
                        None
                        if authorization_authority is None
                        else authorization_authority[
                            "profiled_optimizer_admission_authorized"
                        ]
                    ),
                    **{
                        name: (
                            None
                            if authorization_authority is None
                            else authorization_authority[name]
                        )
                        for name in _PREPARED_AUTHORITY_FIELDS[3:]
                    },
                }
            ),
        }

    @classmethod
    def _transition_material_from_row(cls, row: sqlite3.Row) -> dict[str, Any]:
        return cls._transition_material(
            transition_sequence=row["transition_sequence"],
            previous_transition_sha256=row["previous_transition_sha256"],
            operation_id=row["operation_id"],
            state=row["state"],
            journaled_at=row["journaled_at"],
            authorization_sequence=row["authorization_sequence"],
            authorization_previous_event_sha256=row[
                "authorization_previous_event_sha256"
            ],
            authorization_accepted_at=row["authorization_accepted_at"],
            authorization_envelope_sha256=row["authorization_envelope_sha256"],
            authorization_envelope_byte_count=row[
                "authorization_envelope_byte_count"
            ],
            authorization_authority=(
                None
                if row["state"] == REQUEST_PREPARED
                else {
                    name: bool(row[name])
                    for name in _PREPARED_AUTHORITY_FIELDS
                }
            ),
        )

    def _prepared_and_key_from_row(
        self,
        row: sqlite3.Row,
    ) -> tuple[ProfiledOptimizerExternalCompletionPreparedRequestV1, bytes]:
        try:
            request_bytes = self._cas.get(
                row["request_cas_sha256"],
                expected_byte_count=row["request_byte_count"],
            )
            challenge = self._cas.get(
                row["authorization_challenge_cas_sha256"],
                expected_byte_count=row["authorization_challenge_byte_count"],
            )
            claim_template = self._cas.get(
                row["authorization_claim_template_cas_sha256"],
                expected_byte_count=row["authorization_claim_template_byte_count"],
            )
            completion_event = self._cas.get(
                row["completion_event_cas_sha256"],
                expected_byte_count=row["completion_event_byte_count"],
            )
            final_page_event = self._cas.get(
                row["final_page_receipt_event_cas_sha256"],
                expected_byte_count=row["final_page_receipt_event_byte_count"],
            )
            witness_public_key = self._cas.get(
                row["witness_public_key_cas_sha256"],
                expected_byte_count=row["witness_public_key_byte_count"],
            )
        except SourcePayloadStoreError as exc:
            raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_CAS_REOPEN_FAILED"
            ) from exc
        try:
            prepared = rehydrate_profiled_optimizer_external_completion_prepared_request_v1(
                request_bytes=request_bytes,
            )
        except ProfiledOptimizerExternalCompletionRequestV1Error as exc:
            raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_REQUEST_REHYDRATE_FAILED"
            ) from exc
        expected_material = self._operation_material(
            prepared=prepared,
            witness_public_key_bytes=witness_public_key,
        )
        material_bytes = _canonical_json_bytes(
            expected_material,
            reason="PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_MATERIAL_INVALID",
        )
        stored_material = str(row["operation_material_json"]).encode("ascii")
        if (
            row["operation_id"] != _operation_id(material_bytes)
            or not hmac.compare_digest(stored_material, material_bytes)
            or not hmac.compare_digest(challenge, prepared.authorization_challenge)
            or not hmac.compare_digest(
                claim_template,
                prepared.authorization_claim_template,
            )
            or not hmac.compare_digest(completion_event, prepared.completion_event_bytes)
            or not hmac.compare_digest(
                final_page_event,
                prepared.final_page_receipt_event_bytes,
            )
            or any(
                row[name] != 0 or type(row[name]) is not int
                for name in _PREPARED_AUTHORITY_FIELDS
            )
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_BINDING_INVALID")
        return prepared, witness_public_key

    @staticmethod
    def _latest_transition_identity(connection: sqlite3.Connection) -> tuple[int, str]:
        row = connection.execute(
            """
            SELECT transition_sequence, transition_sha256
            FROM authorization_journal_transitions
            ORDER BY transition_sequence DESC LIMIT 1
            """
        ).fetchone()
        if row is None:
            return 0, AUTHORIZATION_JOURNAL_GENESIS_TRANSITION_SHA256
        return int(row["transition_sequence"]), str(row["transition_sha256"])

    @staticmethod
    def _insert_transition(
        connection: sqlite3.Connection,
        *,
        material: dict[str, Any],
    ) -> tuple[int, str]:
        material_bytes = _canonical_json_bytes(
            material,
            reason="PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_MATERIAL_INVALID",
        )
        transition_sha = _transition_sha256(material_bytes)
        authorization = material["authorization"]
        connection.execute(
            """
            INSERT INTO authorization_journal_transitions (
                transition_sequence, previous_transition_sha256, transition_sha256,
                operation_id, state, authorization_sequence,
                authorization_previous_event_sha256, authorization_accepted_at,
                authorization_envelope_sha256, authorization_envelope_byte_count,
                external_monotonic_manifest_head_verified,
                full_consumption_external_ack_verified,
                profiled_optimizer_admission_authorized,
                optimizer_execution_authorized, checkpoint_write_authorized,
                model_write_authorized, prediction_authorized,
                paper_trading_authorized, live_execution_authorized,
                order_submission_authorized, execution_authorized, runtime_wired,
                journaled_at, transition_material_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                material["transition_sequence"],
                material["previous_transition_sha256"],
                transition_sha,
                material["operation_id"],
                material["state"],
                None if authorization is None else authorization["sequence"],
                None if authorization is None else authorization["previous_event_sha256"],
                None if authorization is None else authorization["accepted_at"],
                None if authorization is None else authorization["envelope_sha256"],
                None if authorization is None else authorization["envelope_byte_count"],
                *(
                    (None,) * len(_PREPARED_AUTHORITY_FIELDS)
                    if authorization is None
                    else tuple(
                        int(authorization[name])
                        for name in _PREPARED_AUTHORITY_FIELDS
                    )
                ),
                material["journaled_at"],
                material_bytes.decode("ascii"),
            ),
        )
        return cast(int, material["transition_sequence"]), transition_sha

    def _verify_integrity_connection(
        self,
        connection: sqlite3.Connection,
    ) -> ProfiledOptimizerCompletionAuthorizationJournalIntegrityV1:
        self._verify_schema(connection)
        operation_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM authorization_journal_operations"
            ).fetchone()[0]
        )
        transition_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM authorization_journal_transitions"
            ).fetchone()[0]
        )
        if (
            operation_count < 0
            or transition_count < 0
            or transition_count > MAX_AUTHORIZATION_JOURNAL_TRANSITIONS
            or operation_count > MAX_AUTHORIZATION_JOURNAL_TRANSITIONS
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_RESOURCE_LIMIT")

        operation_rows = connection.execute(
            "SELECT * FROM authorization_journal_operations ORDER BY operation_id"
        ).fetchall()
        if len(operation_rows) != operation_count:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_COUNT_INVALID")
        operations: dict[str, tuple[sqlite3.Row, Any, bytes]] = {}
        for row in operation_rows:
            operation_id = row["operation_id"]
            if not _valid_sha256(operation_id) or operation_id in operations:
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_ID_INVALID")
            try:
                stored_material_bytes = str(row["operation_material_json"]).encode(
                    "ascii",
                    errors="strict",
                )
            except UnicodeEncodeError as exc:
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_MATERIAL_INVALID"
                ) from exc
            stored_material = _strict_json(
                stored_material_bytes,
                reason="PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_MATERIAL_INVALID",
            )
            expected_material = self._operation_material_from_row(row)
            expected_material_bytes = _canonical_json_bytes(
                expected_material,
                reason="PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_MATERIAL_INVALID",
            )
            if (
                stored_material != expected_material
                or not hmac.compare_digest(stored_material_bytes, expected_material_bytes)
                or operation_id != _operation_id(expected_material_bytes)
            ):
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_MATERIAL_INVALID")
            prepared, witness_key = self._prepared_and_key_from_row(row)
            operations[operation_id] = (row, prepared, witness_key)

        transition_rows = connection.execute(
            """
            SELECT * FROM authorization_journal_transitions
            ORDER BY transition_sequence
            """
        ).fetchall()
        if len(transition_rows) != transition_count:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_COUNT_INVALID")
        prior_transition_sha = AUTHORIZATION_JOURNAL_GENESIS_TRANSITION_SHA256
        lifecycle: dict[str, list[sqlite3.Row]] = {operation_id: [] for operation_id in operations}
        anchored_envelope_sha_by_operation: dict[str, str] = {}
        for expected_sequence, row in enumerate(transition_rows, start=1):
            operation_id = row["operation_id"]
            if operation_id not in operations:
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_ORPHANED")
            if (
                type(row["transition_sequence"]) is not int
                or row["transition_sequence"] != expected_sequence
                or row["previous_transition_sha256"] != prior_transition_sha
                or not _valid_sha256(row["transition_sha256"])
                or row["state"] not in {REQUEST_PREPARED, AUTHORIZATION_ANCHORED}
            ):
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_CHAIN_INVALID")
            _clock(
                row["journaled_at"],
                reason="PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_CLOCK_INVALID",
            )
            if row["state"] == REQUEST_PREPARED:
                if any(row[name] is not None for name in _PREPARED_AUTHORITY_FIELDS):
                    _fail(
                        "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_AUTHORITY_INVALID"
                    )
            else:
                expected_authority = {
                    name: int(index < 3)
                    for index, name in enumerate(_PREPARED_AUTHORITY_FIELDS)
                }
                if any(
                    type(row[name]) is not int or row[name] != expected
                    for name, expected in expected_authority.items()
                ):
                    _fail(
                        "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_AUTHORITY_INVALID"
                    )
            material = self._transition_material_from_row(row)
            material_bytes = _canonical_json_bytes(
                material,
                reason="PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_MATERIAL_INVALID",
            )
            try:
                stored_transition_bytes = str(row["transition_material_json"]).encode(
                    "ascii",
                    errors="strict",
                )
            except UnicodeEncodeError as exc:
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_MATERIAL_INVALID"
                ) from exc
            if (
                row["transition_sha256"] != _transition_sha256(material_bytes)
                or not hmac.compare_digest(stored_transition_bytes, material_bytes)
                or _strict_json(
                    stored_transition_bytes,
                    reason=(
                        "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_MATERIAL_INVALID"
                    ),
                )
                != material
            ):
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_MATERIAL_INVALID")
            lifecycle[operation_id].append(row)
            if row["state"] == AUTHORIZATION_ANCHORED:
                operation_row, prepared, witness_key = operations[operation_id]
                try:
                    envelope = self._cas.get(
                        row["authorization_envelope_sha256"],
                        expected_byte_count=row["authorization_envelope_byte_count"],
                    )
                    verified = verify_profiled_optimizer_external_completion_response_v1(
                        prepared=prepared,
                        authorization_envelope_bytes=envelope,
                        witness_public_key_bytes=witness_key,
                    )
                except (
                    ProfiledOptimizerExternalCompletionRequestV1Error,
                    SourcePayloadStoreError,
                ) as exc:
                    raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                        "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_ANCHOR_REVERIFY_FAILED"
                    ) from exc
                if (
                    row["authorization_sequence"] != verified.authorization_sequence
                    or row["authorization_sequence"]
                    != operation_row["authorization_sequence"]
                    or row["authorization_previous_event_sha256"]
                    != verified.previous_authorization_event_sha256
                    or row["authorization_accepted_at"] != verified.accepted_at
                    or row["authorization_envelope_sha256"]
                    != verified.authorization_envelope_sha256
                    or any(
                        bool(row[name]) is not getattr(verified, name)
                        for name in _PREPARED_AUTHORITY_FIELDS
                    )
                ):
                    _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_ANCHOR_BINDING_INVALID")
                anchored_envelope_sha_by_operation[operation_id] = (
                    verified.authorization_envelope_sha256
                )
            prior_transition_sha = row["transition_sha256"]

        prepared_count = 0
        anchored_count = 0
        pending_count = 0
        for operation_id, rows in lifecycle.items():
            if (
                not rows
                or rows[0]["state"] != REQUEST_PREPARED
                or sum(row["state"] == REQUEST_PREPARED for row in rows) != 1
                or sum(row["state"] == AUTHORIZATION_ANCHORED for row in rows) > 1
                or len(rows) not in {1, 2}
                or (len(rows) == 2 and rows[1]["state"] != AUTHORIZATION_ANCHORED)
            ):
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_LIFECYCLE_INVALID")
            prepared_count += 1
            if operation_id in anchored_envelope_sha_by_operation:
                anchored_count += 1
            else:
                pending_count += 1

        namespaces = {str(row["namespace"]) for row in operation_rows}
        for namespace in namespaces:
            rows = connection.execute(
                """
                SELECT operation.*,
                       anchor.authorization_envelope_sha256 AS anchored_envelope_sha256
                FROM authorization_journal_operations AS operation
                LEFT JOIN authorization_journal_transitions AS anchor
                  ON anchor.operation_id = operation.operation_id
                 AND anchor.state = 'AUTHORIZATION_ANCHORED'
                WHERE operation.namespace = ?
                ORDER BY operation.authorization_sequence
                """,
                (namespace,),
            ).fetchall()
            expected_authorization_sequence = 0
            expected_predecessor = (
                PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
            )
            witness_identity: tuple[str, str] | None = None
            pending_seen = False
            for row in rows:
                identity = (row["witness_id"], row["witness_public_key_sha256"])
                if witness_identity is None:
                    witness_identity = identity
                if (
                    identity != witness_identity
                    or pending_seen
                    or row["expected_authorization_sequence"]
                    != expected_authorization_sequence
                    or row["expected_previous_authorization_event_sha256"]
                    != expected_predecessor
                    or row["authorization_sequence"]
                    != expected_authorization_sequence + 1
                ):
                    _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_NAMESPACE_CHAIN_INVALID")
                anchored_envelope_sha = row["anchored_envelope_sha256"]
                if anchored_envelope_sha is None:
                    pending_seen = True
                else:
                    if not _valid_sha256(anchored_envelope_sha):
                        _fail(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_NAMESPACE_CHAIN_INVALID"
                        )
                    expected_authorization_sequence = row["authorization_sequence"]
                    expected_predecessor = anchored_envelope_sha

        return ProfiledOptimizerCompletionAuthorizationJournalIntegrityV1(
            schema_version=(
                PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_INTEGRITY_V1_SCHEMA_VERSION
            ),
            operation_count=operation_count,
            transition_count=transition_count,
            prepared_count=prepared_count,
            anchored_count=anchored_count,
            pending_count=pending_count,
            namespace_count=len(namespaces),
            terminal_transition_sha256=prior_transition_sha,
            _construction_token=_REPORT_TOKEN,
        )

    def verify_integrity(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledOptimizerCompletionAuthorizationJournalIntegrityV1:
        with self.writer_lease(writer_lease) as held:
            connection = self._open_connection(writer_lease=held)
            try:
                self._initialize_or_verify_schema(connection)
                return self._verify_integrity_connection(connection)
            except sqlite3.Error as exc:
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_VERIFY_FAILED"
                ) from exc
            finally:
                self._close_connection(connection, writer_lease=held)

    def _load_record_connection(
        self,
        connection: sqlite3.Connection,
        *,
        operation_id: str,
    ) -> ProfiledOptimizerCompletionAuthorizationJournalRecordV1:
        row = connection.execute(
            "SELECT * FROM authorization_journal_operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if row is None:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_NOT_FOUND")
        prepared, witness_key = self._prepared_and_key_from_row(row)
        transitions = connection.execute(
            """
            SELECT * FROM authorization_journal_transitions
            WHERE operation_id = ? ORDER BY transition_sequence
            """,
            (operation_id,),
        ).fetchall()
        if not transitions or transitions[0]["state"] != REQUEST_PREPARED:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_RECORD_LIFECYCLE_INVALID")
        prepared_transition = transitions[0]
        anchored_transition = transitions[1] if len(transitions) == 2 else None
        verified: VerifiedProfiledOptimizerExternalCompletionResponseV1 | None = None
        state = REQUEST_PREPARED
        if anchored_transition is not None:
            if anchored_transition["state"] != AUTHORIZATION_ANCHORED:
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_RECORD_LIFECYCLE_INVALID")
            try:
                envelope = self._cas.get(
                    anchored_transition["authorization_envelope_sha256"],
                    expected_byte_count=anchored_transition[
                        "authorization_envelope_byte_count"
                    ],
                )
                verified = verify_profiled_optimizer_external_completion_response_v1(
                    prepared=prepared,
                    authorization_envelope_bytes=envelope,
                    witness_public_key_bytes=witness_key,
                )
            except (
                ProfiledOptimizerExternalCompletionRequestV1Error,
                SourcePayloadStoreError,
            ) as exc:
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_RECORD_REVERIFY_FAILED"
                ) from exc
            state = AUTHORIZATION_ANCHORED
        return ProfiledOptimizerCompletionAuthorizationJournalRecordV1(
            schema_version=(
                PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RECORD_V1_SCHEMA_VERSION
            ),
            operation_id=operation_id,
            state=state,
            prepared_transition_sequence=prepared_transition["transition_sequence"],
            prepared_transition_sha256=prepared_transition["transition_sha256"],
            anchored_transition_sequence=(
                None
                if anchored_transition is None
                else anchored_transition["transition_sequence"]
            ),
            anchored_transition_sha256=(
                None if anchored_transition is None else anchored_transition["transition_sha256"]
            ),
            prepared=prepared,
            verified=verified,
            _construction_token=_RECORD_TOKEN,
        )

    def latest_authorization_head(
        self,
        *,
        witness_id: str,
        authorization_namespace: str,
        witness_public_key_bytes: bytes,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledOptimizerCompletionAuthorizationChainHeadV1:
        if not _valid_identifier(witness_id) or not _valid_identifier(
            authorization_namespace
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_HEAD_IDENTITY_INVALID")
        if (
            type(witness_public_key_bytes) is not bytes
            or len(witness_public_key_bytes) != ED25519_PUBLIC_KEY_BYTES
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_HEAD_KEY_INVALID")
        key_sha = hashlib.sha256(witness_public_key_bytes).hexdigest()
        with self.writer_lease(writer_lease) as held:
            connection = self._open_connection(writer_lease=held)
            try:
                self._initialize_or_verify_schema(connection)
                self._verify_integrity_connection(connection)
                rows = connection.execute(
                    """
                    SELECT operation.*,
                           anchor.authorization_envelope_sha256 AS anchored_envelope_sha256
                    FROM authorization_journal_operations AS operation
                    LEFT JOIN authorization_journal_transitions AS anchor
                      ON anchor.operation_id = operation.operation_id
                     AND anchor.state = 'AUTHORIZATION_ANCHORED'
                    WHERE operation.namespace = ?
                    ORDER BY operation.authorization_sequence
                    """,
                    (authorization_namespace,),
                ).fetchall()
                expected_sequence = 0
                expected_predecessor = (
                    PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
                )
                pending_operation_id: str | None = None
                for row in rows:
                    if (
                        row["witness_id"] != witness_id
                        or row["witness_public_key_sha256"] != key_sha
                    ):
                        _fail(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_HEAD_WITNESS_MISMATCH"
                        )
                    if row["anchored_envelope_sha256"] is None:
                        pending_operation_id = row["operation_id"]
                    else:
                        expected_sequence = row["authorization_sequence"]
                        expected_predecessor = row["anchored_envelope_sha256"]
                return ProfiledOptimizerCompletionAuthorizationChainHeadV1(
                    schema_version=(
                        PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_CHAIN_HEAD_V1_SCHEMA_VERSION
                    ),
                    witness_id=witness_id,
                    witness_public_key_sha256=key_sha,
                    namespace=authorization_namespace,
                    expected_authorization_sequence=expected_sequence,
                    expected_previous_authorization_event_sha256=expected_predecessor,
                    pending_operation_id=pending_operation_id,
                    _construction_token=_CHAIN_HEAD_TOKEN,
                )
            except sqlite3.Error as exc:
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_HEAD_LOAD_FAILED"
                ) from exc
            finally:
                self._close_connection(connection, writer_lease=held)

    def persist_prepared_request(
        self,
        *,
        prepared: ProfiledOptimizerExternalCompletionPreparedRequestV1,
        witness_public_key_bytes: bytes,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledOptimizerCompletionAuthorizationJournalRecordV1:
        """Durably commit exact request material before any caller dispatch."""

        self._validate_prepared_and_key(
            prepared=prepared,
            witness_public_key_bytes=witness_public_key_bytes,
        )
        with self.writer_lease(writer_lease) as held:
            connection: sqlite3.Connection | None = self._open_connection(
                writer_lease=held
            )
            created = False
            operation_id: str | None = None
            try:
                created = self._initialize_or_verify_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                integrity_before = self._verify_integrity_connection(connection)
                existing = connection.execute(
                    """
                    SELECT * FROM authorization_journal_operations
                    WHERE request_sha256 = ?
                       OR idempotency_key = ?
                       OR authorization_challenge_cas_sha256 = ?
                       OR (
                            witness_id = ? AND namespace = ?
                            AND completion_event_sha256 = ?
                       )
                    """,
                    (
                        prepared.request_sha256,
                        prepared.idempotency_key,
                        prepared.authorization_challenge_sha256,
                        prepared.witness_id,
                        prepared.authorization_namespace,
                        prepared.completion_event_sha256,
                    ),
                ).fetchall()
                if existing:
                    if len(existing) != 1:
                        _fail(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PREPARED_IDENTITY_CONFLICT"
                        )
                    row = existing[0]
                    stored_prepared, stored_key = self._prepared_and_key_from_row(row)
                    if (
                        stored_prepared != prepared
                        or not hmac.compare_digest(
                            stored_prepared.request_bytes,
                            prepared.request_bytes,
                        )
                        or not hmac.compare_digest(stored_key, witness_public_key_bytes)
                    ):
                        _fail(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PREPARED_REPLAY_CONFLICT"
                        )
                    operation_id = row["operation_id"]
                    connection.execute("COMMIT")
                else:
                    if (
                        integrity_before.transition_count
                        + integrity_before.pending_count
                        + 2
                        > MAX_AUTHORIZATION_JOURNAL_TRANSITIONS
                    ):
                        _fail(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_CAPACITY_RESERVED"
                        )
                    pending = connection.execute(
                        """
                        SELECT operation.operation_id
                        FROM authorization_journal_operations AS operation
                        WHERE operation.namespace = ?
                          AND NOT EXISTS (
                              SELECT 1 FROM authorization_journal_transitions AS transition
                              WHERE transition.operation_id = operation.operation_id
                                AND transition.state = 'AUTHORIZATION_ANCHORED'
                          )
                        """,
                        (prepared.authorization_namespace,),
                    ).fetchall()
                    if pending:
                        _fail(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_NAMESPACE_PENDING_EXISTS"
                        )
                    latest_anchor = connection.execute(
                        """
                        SELECT operation.*, anchor.authorization_envelope_sha256
                        FROM authorization_journal_operations AS operation
                        JOIN authorization_journal_transitions AS anchor
                          ON anchor.operation_id = operation.operation_id
                         AND anchor.state = 'AUTHORIZATION_ANCHORED'
                        WHERE operation.namespace = ?
                        ORDER BY operation.authorization_sequence DESC LIMIT 1
                        """,
                        (prepared.authorization_namespace,),
                    ).fetchone()
                    if latest_anchor is None:
                        if (
                            prepared.expected_authorization_sequence != 0
                            or prepared.expected_previous_authorization_event_sha256
                            != PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
                        ):
                            _fail(
                                "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PREDECESSOR_MISMATCH"
                            )
                    elif (
                        latest_anchor["witness_id"] != prepared.witness_id
                        or latest_anchor["witness_public_key_sha256"]
                        != prepared.witness_public_key_sha256
                        or prepared.expected_authorization_sequence
                        != latest_anchor["authorization_sequence"]
                        or prepared.expected_previous_authorization_event_sha256
                        != latest_anchor["authorization_envelope_sha256"]
                    ):
                        _fail(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PREDECESSOR_MISMATCH"
                        )
                    material = self._operation_material(
                        prepared=prepared,
                        witness_public_key_bytes=witness_public_key_bytes,
                    )
                    material_bytes = _canonical_json_bytes(
                        material,
                        reason=(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_MATERIAL_INVALID"
                        ),
                    )
                    operation_id = _operation_id(material_bytes)
                    try:
                        for payload, expected_sha256, expected_count in (
                            (
                                prepared.authorization_challenge,
                                prepared.authorization_challenge_sha256,
                                len(prepared.authorization_challenge),
                            ),
                            (
                                prepared.authorization_claim_template,
                                prepared.authorization_claim_template_sha256,
                                len(prepared.authorization_claim_template),
                            ),
                            (
                                prepared.request_bytes,
                                prepared.request_sha256,
                                prepared.request_byte_count,
                            ),
                            (
                                prepared.completion_event_bytes,
                                prepared.completion_event_sha256,
                                prepared.completion_event_byte_count,
                            ),
                            (
                                prepared.final_page_receipt_event_bytes,
                                prepared.final_page_receipt_event_sha256,
                                prepared.final_page_receipt_event_byte_count,
                            ),
                            (
                                witness_public_key_bytes,
                                prepared.witness_public_key_sha256,
                                len(witness_public_key_bytes),
                            ),
                        ):
                            self._cas.put(
                                payload,
                                expected_sha256=expected_sha256,
                                expected_byte_count=expected_count,
                            )
                    except SourcePayloadStoreError as exc:
                        raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PREPARED_CAS_FAILED"
                        ) from exc
                    ordered_names = (
                        "witness_id",
                        "witness_public_key_sha256",
                        "namespace",
                        "expected_authorization_sequence",
                        "expected_previous_authorization_event_sha256",
                        "authorization_sequence",
                        "manifest_id",
                        "completion_event_sha256",
                        "completion_event_byte_count",
                        "final_page_receipt_event_sha256",
                        "final_page_receipt_event_byte_count",
                        "manifest_head_namespace",
                        "manifest_head_sequence",
                        "manifest_head_event_sha256",
                        "manifest_head_operation_id",
                        "authorization_challenge_cas_sha256",
                        "authorization_challenge_byte_count",
                        "authorization_claim_template_cas_sha256",
                        "authorization_claim_template_byte_count",
                        "request_cas_sha256",
                        "request_byte_count",
                        "request_sha256",
                        "idempotency_key",
                        "completion_event_cas_sha256",
                        "final_page_receipt_event_cas_sha256",
                        "witness_public_key_cas_sha256",
                        "witness_public_key_byte_count",
                        *_PREPARED_AUTHORITY_FIELDS,
                    )
                    operation_values: dict[str, Any] = {
                        "operation_id": operation_id,
                        **{
                            name: (
                                int(material[name])
                                if name in _PREPARED_AUTHORITY_FIELDS
                                else material[name]
                            )
                            for name in ordered_names
                        },
                        "operation_material_json": material_bytes.decode("ascii"),
                    }
                    connection.execute(
                        """
                        INSERT INTO authorization_journal_operations (
                            operation_id, witness_id, witness_public_key_sha256,
                            namespace, expected_authorization_sequence,
                            expected_previous_authorization_event_sha256,
                            authorization_sequence, manifest_id,
                            completion_event_sha256, completion_event_byte_count,
                            final_page_receipt_event_sha256,
                            final_page_receipt_event_byte_count,
                            manifest_head_namespace, manifest_head_sequence,
                            manifest_head_event_sha256, manifest_head_operation_id,
                            authorization_challenge_cas_sha256,
                            authorization_challenge_byte_count,
                            authorization_claim_template_cas_sha256,
                            authorization_claim_template_byte_count,
                            request_cas_sha256, request_byte_count, request_sha256,
                            idempotency_key, completion_event_cas_sha256,
                            final_page_receipt_event_cas_sha256,
                            witness_public_key_cas_sha256,
                            witness_public_key_byte_count,
                            external_monotonic_manifest_head_verified,
                            full_consumption_external_ack_verified,
                            profiled_optimizer_admission_authorized,
                            optimizer_execution_authorized,
                            checkpoint_write_authorized, model_write_authorized,
                            prediction_authorized, paper_trading_authorized,
                            live_execution_authorized, order_submission_authorized,
                            execution_authorized, runtime_wired,
                            operation_material_json
                        ) VALUES (
                            :operation_id, :witness_id, :witness_public_key_sha256,
                            :namespace, :expected_authorization_sequence,
                            :expected_previous_authorization_event_sha256,
                            :authorization_sequence, :manifest_id,
                            :completion_event_sha256, :completion_event_byte_count,
                            :final_page_receipt_event_sha256,
                            :final_page_receipt_event_byte_count,
                            :manifest_head_namespace, :manifest_head_sequence,
                            :manifest_head_event_sha256, :manifest_head_operation_id,
                            :authorization_challenge_cas_sha256,
                            :authorization_challenge_byte_count,
                            :authorization_claim_template_cas_sha256,
                            :authorization_claim_template_byte_count,
                            :request_cas_sha256, :request_byte_count, :request_sha256,
                            :idempotency_key, :completion_event_cas_sha256,
                            :final_page_receipt_event_cas_sha256,
                            :witness_public_key_cas_sha256,
                            :witness_public_key_byte_count,
                            :external_monotonic_manifest_head_verified,
                            :full_consumption_external_ack_verified,
                            :profiled_optimizer_admission_authorized,
                            :optimizer_execution_authorized,
                            :checkpoint_write_authorized, :model_write_authorized,
                            :prediction_authorized, :paper_trading_authorized,
                            :live_execution_authorized, :order_submission_authorized,
                            :execution_authorized, :runtime_wired,
                            :operation_material_json
                        )
                        """,
                        operation_values,
                    )
                    prior_sequence, prior_transition_sha = self._latest_transition_identity(
                        connection
                    )
                    transition = self._transition_material(
                        transition_sequence=prior_sequence + 1,
                        previous_transition_sha256=prior_transition_sha,
                        operation_id=operation_id,
                        state=REQUEST_PREPARED,
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
                    _fail(
                        "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_ID_UNAVAILABLE"
                    )
                return self._load_record_connection(
                    connection,
                    operation_id=operation_id,
                )
            except ProfiledOptimizerCompletionAuthorizationJournalV1Error:
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
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PREPARED_COMMIT_FAILED"
                ) from exc
            finally:
                if connection is not None:
                    self._close_connection(connection, writer_lease=held)
                if created:
                    _fsync_directory(self._path.parent)

    def load_request_for_completion(
        self,
        *,
        witness_id: str,
        authorization_namespace: str,
        completion_event_sha256: str,
        witness_public_key_bytes: bytes,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledOptimizerCompletionAuthorizationJournalRecordV1 | None:
        """Load the one exact durable request already bound to a completion."""

        if (
            not _valid_identifier(witness_id)
            or not _valid_identifier(authorization_namespace)
            or not _valid_sha256(completion_event_sha256)
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_COMPLETION_LOOKUP_INVALID")
        if (
            type(witness_public_key_bytes) is not bytes
            or len(witness_public_key_bytes) != ED25519_PUBLIC_KEY_BYTES
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_COMPLETION_LOOKUP_KEY_INVALID")
        key_sha = hashlib.sha256(witness_public_key_bytes).hexdigest()
        with self.writer_lease(writer_lease) as held:
            connection = self._open_connection(writer_lease=held)
            try:
                self._initialize_or_verify_schema(connection)
                self._verify_integrity_connection(connection)
                rows = connection.execute(
                    """
                    SELECT * FROM authorization_journal_operations
                    WHERE namespace = ? AND completion_event_sha256 = ?
                    ORDER BY authorization_sequence
                    """,
                    (authorization_namespace, completion_event_sha256),
                ).fetchall()
                if not rows:
                    return None
                if len(rows) != 1:
                    _fail(
                        "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_COMPLETION_LOOKUP_CONFLICT"
                    )
                row = rows[0]
                if (
                    row["witness_id"] != witness_id
                    or row["witness_public_key_sha256"] != key_sha
                ):
                    _fail(
                        "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_COMPLETION_LOOKUP_WITNESS_MISMATCH"
                    )
                _, stored_key = self._prepared_and_key_from_row(row)
                if not hmac.compare_digest(stored_key, witness_public_key_bytes):
                    _fail(
                        "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_COMPLETION_LOOKUP_KEY_MISMATCH"
                    )
                return self._load_record_connection(
                    connection,
                    operation_id=row["operation_id"],
                )
            except sqlite3.Error as exc:
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_COMPLETION_LOOKUP_FAILED"
                ) from exc
            finally:
                self._close_connection(connection, writer_lease=held)

    def load_pending_requests(
        self,
        *,
        witness_id: str,
        witness_public_key_bytes: bytes,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> tuple[ProfiledOptimizerCompletionAuthorizationJournalRecordV1, ...]:
        if not _valid_identifier(witness_id):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PENDING_WITNESS_INVALID")
        if (
            type(witness_public_key_bytes) is not bytes
            or len(witness_public_key_bytes) != ED25519_PUBLIC_KEY_BYTES
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PENDING_KEY_INVALID")
        key_sha = hashlib.sha256(witness_public_key_bytes).hexdigest()
        with self.writer_lease(writer_lease) as held:
            connection = self._open_connection(writer_lease=held)
            try:
                self._initialize_or_verify_schema(connection)
                self._verify_integrity_connection(connection)
                rows = connection.execute(
                    """
                    SELECT operation.operation_id, operation.witness_public_key_sha256
                    FROM authorization_journal_operations AS operation
                    WHERE operation.witness_id = ?
                      AND NOT EXISTS (
                          SELECT 1 FROM authorization_journal_transitions AS transition
                          WHERE transition.operation_id = operation.operation_id
                            AND transition.state = 'AUTHORIZATION_ANCHORED'
                      )
                    ORDER BY operation.namespace
                    """,
                    (witness_id,),
                ).fetchall()
                records: list[ProfiledOptimizerCompletionAuthorizationJournalRecordV1] = []
                for row in rows:
                    if row["witness_public_key_sha256"] != key_sha:
                        _fail(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PENDING_KEY_MISMATCH"
                        )
                    record = self._load_record_connection(
                        connection,
                        operation_id=row["operation_id"],
                    )
                    _, stored_key = self._prepared_and_key_from_row(
                        connection.execute(
                            """
                            SELECT * FROM authorization_journal_operations
                            WHERE operation_id = ?
                            """,
                            (row["operation_id"],),
                        ).fetchone()
                    )
                    if not hmac.compare_digest(stored_key, witness_public_key_bytes):
                        _fail(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PENDING_KEY_MISMATCH"
                        )
                    records.append(record)
                return tuple(records)
            except sqlite3.Error as exc:
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_PENDING_LOAD_FAILED"
                ) from exc
            finally:
                self._close_connection(connection, writer_lease=held)

    def commit_authorization_anchored(
        self,
        *,
        operation_id: str,
        authorization_envelope_bytes: bytes,
        witness_public_key_bytes: bytes,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledOptimizerCompletionAuthorizationJournalRecordV1:
        """Independently verify and durably anchor an exact signed response."""

        if not _valid_sha256(operation_id):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_ID_INVALID")
        if type(authorization_envelope_bytes) is not bytes or not authorization_envelope_bytes:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_ENVELOPE_INVALID")
        if (
            type(witness_public_key_bytes) is not bytes
            or len(witness_public_key_bytes) != ED25519_PUBLIC_KEY_BYTES
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_ANCHOR_KEY_INVALID")
        with self.writer_lease(writer_lease) as held:
            connection: sqlite3.Connection | None = self._open_connection(
                writer_lease=held
            )
            try:
                self._initialize_or_verify_schema(connection)
                connection.execute("BEGIN IMMEDIATE")
                integrity_before = self._verify_integrity_connection(connection)
                row = connection.execute(
                    "SELECT * FROM authorization_journal_operations WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
                if row is None:
                    _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_OPERATION_NOT_FOUND")
                prepared, stored_key = self._prepared_and_key_from_row(row)
                if not hmac.compare_digest(stored_key, witness_public_key_bytes):
                    _fail("PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_ANCHOR_KEY_MISMATCH")
                try:
                    verified = verify_profiled_optimizer_external_completion_response_v1(
                        prepared=prepared,
                        authorization_envelope_bytes=authorization_envelope_bytes,
                        witness_public_key_bytes=witness_public_key_bytes,
                    )
                except ProfiledOptimizerExternalCompletionRequestV1Error as exc:
                    raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                        "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_RESPONSE_UNVERIFIED"
                    ) from exc
                existing_anchor = connection.execute(
                    """
                    SELECT * FROM authorization_journal_transitions
                    WHERE operation_id = ? AND state = 'AUTHORIZATION_ANCHORED'
                    """,
                    (operation_id,),
                ).fetchone()
                if existing_anchor is not None:
                    if (
                        existing_anchor["authorization_envelope_sha256"]
                        != verified.authorization_envelope_sha256
                        or existing_anchor["authorization_envelope_byte_count"]
                        != len(authorization_envelope_bytes)
                    ):
                        _fail(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_ANCHOR_REPLAY_CONFLICT"
                        )
                    connection.execute("COMMIT")
                else:
                    if integrity_before.transition_count >= MAX_AUTHORIZATION_JOURNAL_TRANSITIONS:
                        _fail(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_TRANSITION_CAPACITY_EXHAUSTED"
                        )
                    try:
                        self._cas.put(
                            authorization_envelope_bytes,
                            expected_sha256=verified.authorization_envelope_sha256,
                            expected_byte_count=len(authorization_envelope_bytes),
                        )
                    except SourcePayloadStoreError as exc:
                        raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_ENVELOPE_CAS_FAILED"
                        ) from exc
                    prior_sequence, prior_transition_sha = self._latest_transition_identity(
                        connection
                    )
                    transition = self._transition_material(
                        transition_sequence=prior_sequence + 1,
                        previous_transition_sha256=prior_transition_sha,
                        operation_id=operation_id,
                        state=AUTHORIZATION_ANCHORED,
                        journaled_at=_journaled_at(),
                        authorization_sequence=verified.authorization_sequence,
                        authorization_previous_event_sha256=(
                            verified.previous_authorization_event_sha256
                        ),
                        authorization_accepted_at=verified.accepted_at,
                        authorization_envelope_sha256=(
                            verified.authorization_envelope_sha256
                        ),
                        authorization_envelope_byte_count=len(
                            authorization_envelope_bytes
                        ),
                        authorization_authority={
                            name: getattr(verified, name)
                            for name in _PREPARED_AUTHORITY_FIELDS
                        },
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
                    operation_id=operation_id,
                )
            except ProfiledOptimizerCompletionAuthorizationJournalV1Error:
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
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_ANCHOR_COMMIT_FAILED"
                ) from exc
            finally:
                if connection is not None:
                    self._close_connection(connection, writer_lease=held)

    def persisted_authorization_envelopes_by_namespace(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> Mapping[str, tuple[bytes, ...]]:
        with self.writer_lease(writer_lease) as held:
            connection = self._open_connection(writer_lease=held)
            try:
                self._initialize_or_verify_schema(connection)
                self._verify_integrity_connection(connection)
                rows = connection.execute(
                    """
                    SELECT operation.namespace, transition.authorization_envelope_sha256,
                           transition.authorization_envelope_byte_count
                    FROM authorization_journal_transitions AS transition
                    JOIN authorization_journal_operations AS operation
                      ON operation.operation_id = transition.operation_id
                    WHERE transition.state = 'AUTHORIZATION_ANCHORED'
                    ORDER BY operation.namespace, operation.authorization_sequence
                    """
                ).fetchall()
                result: dict[str, list[bytes]] = {}
                for row in rows:
                    try:
                        envelope = self._cas.get(
                            row["authorization_envelope_sha256"],
                            expected_byte_count=row["authorization_envelope_byte_count"],
                        )
                    except SourcePayloadStoreError as exc:
                        raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_ENVELOPE_REOPEN_FAILED"
                        ) from exc
                    result.setdefault(row["namespace"], []).append(envelope)
                return {namespace: tuple(values) for namespace, values in result.items()}
            except sqlite3.Error as exc:
                raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_ENVELOPE_LOAD_FAILED"
                ) from exc
            finally:
                self._close_connection(connection, writer_lease=held)


__all__ = (
    "AUTHORIZATION_ANCHORED",
    "AUTHORIZATION_JOURNAL_GENESIS_TRANSITION_SHA256",
    "MAX_AUTHORIZATION_JOURNAL_TRANSITIONS",
    "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_CHAIN_HEAD_V1_SCHEMA_VERSION",
    "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_INTEGRITY_V1_SCHEMA_VERSION",
    "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_JOURNAL_V1_SCHEMA_VERSION",
    "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RECORD_V1_SCHEMA_VERSION",
    "REQUEST_PREPARED",
    "ProfiledOptimizerCompletionAuthorizationChainHeadV1",
    "ProfiledOptimizerCompletionAuthorizationJournalIntegrityV1",
    "ProfiledOptimizerCompletionAuthorizationJournalRecordV1",
    "ProfiledOptimizerCompletionAuthorizationJournalV1",
    "ProfiledOptimizerCompletionAuthorizationJournalV1Error",
)
