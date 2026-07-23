"""Canonical, non-authorizing frontier receipts over profiled research ledgers.

The ledger has two append-only event types.  A source-selection event fixes the
exact commitment/outcome heads and receives a postcommit boundary anchor before
terminal dispositions are evaluated.  Only a complete selection may create a
model-bound candidate event.  Both terminal dispositions and candidate rows are
paged in immutable CAS objects, so every valid 65,536-row source prefix remains
representable without weakening the 8 MiB object bound.

This module never authorizes optimization, checkpoint mutation, serving, paper
trading, live trading, exchange access, risk, allocation, or runtime wiring.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_HEAD_ACTIONS,
    CONFIDENCE_HEAD_SCHEMA_VERSION,
    CONFIDENCE_LABEL_SEMANTICS,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.profiled_research_finalized_outcome_ledger_v1 import (  # noqa: E501
    ProfiledResearchFinalizedOutcomeInventorySnapshotV1,
    ProfiledResearchFinalizedOutcomeLedgerV1,
)
from v2.backend.app.services.native_trainer.profiled_research_shadow_hypothesis_commitment_v1 import (  # noqa: E501
    ProfiledResearchShadowCommitmentInventorySnapshotV1,
    ProfiledResearchShadowHypothesisCommitmentLedgerV1,
)

PROFILED_RESEARCH_CANONICAL_FRONTIER_LEDGER_V1_SCHEMA_VERSION: Final = (
    "profiled_research_canonical_candidate_frontier_ledger_v1"
)
PROFILED_RESEARCH_CANONICAL_FRONTIER_SELECTION_V1_SCHEMA_VERSION: Final = (
    "profiled_research_canonical_frontier_source_selection_v1"
)
PROFILED_RESEARCH_CANONICAL_FRONTIER_SELECTION_V1_CLASSIFICATION: Final = (
    "CANONICAL_DURABLE_SOURCE_HEAD_SELECTION_NO_RUNTIME_AUTHORITY_V1"
)
PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_V1_SCHEMA_VERSION: Final = (
    "profiled_research_canonical_frontier_candidate_v1"
)
PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_V1_CLASSIFICATION: Final = (
    "CANONICAL_MODEL_SOURCE_PAIR_CANDIDATE_NO_RUNTIME_AUTHORITY_V1"
)
PROFILED_RESEARCH_CANONICAL_FRONTIER_ACCOUNTING_PAGE_V1_SCHEMA_VERSION: Final = (
    "profiled_research_canonical_frontier_accounting_page_v1"
)
PROFILED_RESEARCH_CANONICAL_FRONTIER_ACCOUNTING_ROOT_V1_SCHEMA_VERSION: Final = (
    "profiled_research_canonical_frontier_accounting_root_v1"
)
PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_PAGE_V1_SCHEMA_VERSION: Final = (
    "profiled_research_canonical_frontier_candidate_page_v1"
)
PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_ROOT_V1_SCHEMA_VERSION: Final = (
    "profiled_research_canonical_frontier_candidate_root_v1"
)
PROFILED_RESEARCH_CANONICAL_FRONTIER_APPEND_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "profiled_research_canonical_frontier_append_receipt_v1"
)
PROFILED_RESEARCH_CANONICAL_FRONTIER_POSTCOMMIT_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "profiled_research_canonical_frontier_postcommit_receipt_v1"
)
PROFILED_RESEARCH_CANONICAL_FRONTIER_HEAD_ANCHOR_V1_SCHEMA_VERSION: Final = (
    "profiled_research_canonical_frontier_head_anchor_v1"
)

_APPLICATION_ID = 0x5043464C
_USER_VERSION = 1
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_SOURCE_ROWS = 65_536
_PAGE_MAX_ROWS = 128
_MAX_PAGES = (_MAX_SOURCE_ROWS + _PAGE_MAX_ROWS - 1) // _PAGE_MAX_ROWS
_MAX_LEDGER_EVENTS = 8_192
_MAX_DATABASE_BYTES = 512 * 1024 * 1024
_BUSY_TIMEOUT_MS = 60_000
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$", re.ASCII)
_CANONICAL_MS_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$",
    re.ASCII,
)
_UTC_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_GENESIS_EVENT_CHAIN_SHA256 = hashlib.sha256(
    f"{PROFILED_RESEARCH_CANONICAL_FRONTIER_LEDGER_V1_SCHEMA_VERSION}:EVENT_GENESIS".encode()
).hexdigest()
_GENESIS_HEAD_ANCHOR_SHA256 = hashlib.sha256(
    f"{PROFILED_RESEARCH_CANONICAL_FRONTIER_HEAD_ANCHOR_V1_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()
_GENESIS_ACCOUNTING_PAGE_SHA256 = hashlib.sha256(
    f"{PROFILED_RESEARCH_CANONICAL_FRONTIER_ACCOUNTING_PAGE_V1_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()
_GENESIS_CANDIDATE_PAGE_SHA256 = hashlib.sha256(
    f"{PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_PAGE_V1_SCHEMA_VERSION}:GENESIS".encode()
).hexdigest()
_RESULT_TOKEN = object()
_RESULT_SEAL_KEY = secrets.token_bytes(32)

_AUTHORIZATION: Final = {
    "consumer_eligible": False,
    "calibration_input_authorized": False,
    "optimizer_execution_authorized": False,
    "optimizer_checkpoint_write_authorized": False,
    "calibration_only_checkpoint_write_authorized": False,
    "model_weight_mutation_authorized": False,
    "prediction_authorized": False,
    "serving_authorized": False,
    "serving_activation_authorized": False,
    "serving_promotion_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "exchange_access_authorized": False,
    "deployment_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "risk_authority": False,
    "allocator_authority": False,
    "runtime_wired": False,
}

_SELECTION_FIELDS: Final = frozenset(
    {
        "schema_version",
        "classification",
        "selection_key_sha256",
        "source_pair_binding",
        "event_binding",
        "authorization",
        "status",
        "selection_material_sha256",
    }
)
_SOURCE_PAIR_FIELDS: Final = frozenset(
    {
        "source_pair_sha256",
        "commitment_snapshot_cas_address",
        "commitment_ledger_binding",
        "commitment_inventory_sha256",
        "outcome_snapshot_cas_address",
        "outcome_ledger_binding",
        "outcome_inventory_sha256",
    }
)
_EVENT_BINDING_FIELDS: Final = frozenset(
    {
        "event_sequence",
        "event_type",
        "transaction_id",
        "previous_event_chain_sha256",
        "event_commit_observed_at",
        "event_commit_prepared_at",
    }
)
_SELECTION_STATUS: Final = {
    "source_heads_canonically_selected": True,
    "selection_boundary_postcommit_anchored": False,
    "terminal_accounting_complete": False,
    "candidate_key_consumed": False,
    "runtime_wired": False,
}
_CANDIDATE_FIELDS: Final = frozenset(
    {
        "schema_version",
        "classification",
        "candidate_key_sha256",
        "selection_binding",
        "model_binding",
        "terminal_accounting_root_cas_address",
        "candidate_inventory_root_cas_address",
        "event_binding",
        "authorization",
        "status",
        "candidate_material_sha256",
    }
)
_MODEL_FIELDS: Final = frozenset(
    {
        "checkpoint_id",
        "checkpoint_generation",
        "model_parameter_fingerprint",
        "model_binding_sha256",
        "confidence_head_schema_version",
        "confidence_head_actions",
        "label_semantics",
    }
)
_CANDIDATE_SELECTION_BINDING_FIELDS: Final = frozenset(
    {
        "selection_key_sha256",
        "selection_event_sequence",
        "selection_artifact_sha256",
        "source_pair_sha256",
        "selection_head_anchor_sha256",
        "selection_anchored_at",
        "terminal_cutoff_observed_at",
        "terminal_accounting_root_sha256",
    }
)
_CANDIDATE_STATUS: Final = {
    "canonical_source_selection_bound": True,
    "terminal_accounting_complete": True,
    "caller_selected_subset_used": False,
    "static_sample_threshold_used": False,
    "validation_roles_assigned": False,
    "v3_admission_authorized": False,
    "runtime_wired": False,
}
_PAGE_FIELDS: Final = frozenset(
    {
        "schema_version",
        "root_key_sha256",
        "page_index",
        "first_sequence",
        "last_sequence",
        "row_count",
        "previous_page_material_sha256",
        "ordered_rows",
        "page_material_sha256",
        "authorization",
    }
)
_PAGE_DESCRIPTOR_FIELDS: Final = frozenset(
    {
        "page_index",
        "first_sequence",
        "last_sequence",
        "row_count",
        "page_material_sha256",
        "page_cas_address",
    }
)
_ROOT_FIELDS: Final = frozenset(
    {
        "schema_version",
        "root_key_sha256",
        "total_rows",
        "ordered_page_descriptors",
        "page_descriptor_digest",
        "counts",
        "authorization",
        "root_material_sha256",
    }
)
_ACCOUNTING_ROW_FIELDS: Final = frozenset(
    {
        "sequence",
        "commitment_sequence",
        "hypothesis_identity_sha256",
        "hypothesis_artifact_sha256",
        "commitment_append_receipt_sha256",
        "commitment_postcommit_receipt_sha256",
        "commitment_record_chain_sha256",
        "decision_time",
        "label_earliest_available_at",
        "commitment_disposition",
        "terminal_disposition",
        "terminal_reason",
        "outcome_artifact_sha256",
        "outcome_material_sha256",
        "outcome_calibration_row_id",
        "outcome_calibration_eligible",
        "outcome_model_parameter_fingerprint",
    }
)
_CANDIDATE_ROW_FIELDS: Final = frozenset(
    {
        "sequence",
        "calibration_row_id",
        "hypothesis_identity_sha256",
        "hypothesis_artifact_sha256",
        "outcome_artifact_sha256",
        "outcome_material_sha256",
        "label_source_binding_sha256",
        "append_receipt_sha256",
        "postcommit_receipt_sha256",
        "record_chain_sha256",
        "decision_time",
        "actual_label_available_at",
        "maturation_observed_at",
        "postcommit_readback_at",
        "selected_action",
        "raw_probability",
        "observed_strictly_positive_net_pnl",
        "model_binding_sha256",
    }
)


class ProfiledResearchCanonicalFrontierV1Error(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ProfiledResearchCanonicalFrontierV1ValidationError(
    ProfiledResearchCanonicalFrontierV1Error
):
    pass


class ProfiledResearchCanonicalFrontierV1IntegrityError(
    ProfiledResearchCanonicalFrontierV1Error
):
    pass


class ProfiledResearchCanonicalFrontierV1ConflictError(
    ProfiledResearchCanonicalFrontierV1Error
):
    pass


def _validation(reason: str) -> NoReturn:
    raise ProfiledResearchCanonicalFrontierV1ValidationError(reason) from None


def _integrity(reason: str) -> NoReturn:
    raise ProfiledResearchCanonicalFrontierV1IntegrityError(reason) from None


def _canonical_bytes(value: object, *, reason: str) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeError, ValueError):
        _validation(reason)
    if not encoded or len(encoded) > _MAX_JSON_BYTES:
        _validation(reason)
    return encoded


def _canonical_json(value: object, *, reason: str) -> str:
    return _canonical_bytes(value, reason=reason).decode("ascii")


def _parse_exact_object(payload: object, *, reason: str) -> dict[str, Any]:
    if type(payload) not in (bytes, str):
        _integrity(reason)
    raw = payload.encode("ascii", errors="strict") if type(payload) is str else payload
    if type(raw) is not bytes or not raw or len(raw) > _MAX_JSON_BYTES:
        _integrity(reason)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        _integrity(reason)
    if type(value) is not dict or _canonical_bytes(value, reason=reason) != raw:
        _integrity(reason)
    return cast(dict[str, Any], value)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value, reason="FRONTIER_HASH_INPUT_INVALID")).hexdigest()


def _strict_sha256(value: object) -> str | None:
    if type(value) is str and _SHA256_RE.fullmatch(value) is not None:
        return value
    return None


def _strict_positive_int(value: object, *, maximum: int | None = None) -> int | None:
    if type(value) is not int or value <= 0:
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def _finite_float(value: object) -> float | None:
    if type(value) is not float or not (-float("inf") < value < float("inf")):
        return None
    return value


def _aware_clock(value: object) -> datetime | None:
    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _millisecond_clock(value: object) -> datetime | None:
    if type(value) is not str or _CANONICAL_MS_RE.fullmatch(value) is None:
        return None
    return _aware_clock(value)


def _format_microsecond(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _format_millisecond(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _ceil_millisecond(value: datetime) -> datetime:
    normalized = value.astimezone(UTC)
    floored = normalized.replace(microsecond=(normalized.microsecond // 1000) * 1000)
    if floored == normalized:
        return floored
    try:
        return floored + timedelta(milliseconds=1)
    except OverflowError:
        _integrity("FRONTIER_CLOCK_OVERFLOW")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _lexical_absolute_path(path: object) -> Path:
    if not isinstance(path, Path):
        _validation("FRONTIER_LEDGER_PATH_EXACT_PATH_REQUIRED")
    candidate = cast(Path, path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve(strict=False)


def _expected_address(payload: bytes) -> SourcePayloadAddress:
    digest = hashlib.sha256(payload).hexdigest()
    return SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=digest,
        payload_byte_count=len(payload),
        relative_path=f"sha256/{digest[:2]}/{digest}",
    )


def _address_mapping(address: SourcePayloadAddress) -> dict[str, object]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _address_from_mapping(value: object, *, reason: str) -> SourcePayloadAddress:
    if type(value) is not dict or set(value) != {
        "schema_version",
        "payload_sha256",
        "payload_byte_count",
        "relative_path",
    }:
        _integrity(reason)
    mapping = cast(dict[str, Any], value)
    digest = _strict_sha256(mapping.get("payload_sha256"))
    count = _strict_positive_int(mapping.get("payload_byte_count"), maximum=_MAX_JSON_BYTES)
    relative = mapping.get("relative_path")
    if (
        mapping.get("schema_version") != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or digest is None
        or count is None
        or type(relative) is not str
        or relative != f"sha256/{digest[:2]}/{digest}"
    ):
        _integrity(reason)
    return SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=digest,
        payload_byte_count=count,
        relative_path=cast(str, relative),
    )


def _put_exact(store: ImmutableSourcePayloadStore, payload: bytes) -> SourcePayloadAddress:
    expected = _expected_address(payload)
    try:
        address = store.put(
            payload,
            expected_sha256=expected.payload_sha256,
            expected_byte_count=expected.payload_byte_count,
        )
        readback = store.get(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledResearchCanonicalFrontierV1IntegrityError(
            "FRONTIER_CAS_PUBLICATION_FAILED"
        ) from exc
    if address != expected or not hmac.compare_digest(readback, payload):
        _integrity("FRONTIER_CAS_READBACK_INVALID")
    return address


def _get_exact(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
    *,
    reason: str,
) -> bytes:
    try:
        payload = store.get(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledResearchCanonicalFrontierV1IntegrityError(reason) from exc
    if _expected_address(payload) != address:
        _integrity(reason)
    return payload


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _head_catalog_root(path: Path) -> Path:
    return path.with_name(path.name + ".head-anchor-cas")


def _writer_lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".writer.lock")


@contextmanager
def _exclusive_writer_lock(path: Path) -> Iterator[None]:
    lock_path = _writer_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA journal_mode=DELETE")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA temp_store=MEMORY")


def _configure_readonly_connection(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA query_only=ON")


def _schema_script() -> str:
    return f"""
    PRAGMA application_id={_APPLICATION_ID};
    PRAGMA user_version={_USER_VERSION};
    CREATE TABLE frontier_metadata (
        metadata_key TEXT PRIMARY KEY,
        metadata_value TEXT NOT NULL
    );
    CREATE TABLE frontier_events (
        event_sequence INTEGER PRIMARY KEY,
        event_type TEXT NOT NULL CHECK(event_type IN ('SELECTION', 'CANDIDATE')),
        stable_key_sha256 TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL UNIQUE,
        artifact_byte_count INTEGER NOT NULL CHECK(
            artifact_byte_count > 0 AND artifact_byte_count <= {_MAX_JSON_BYTES}
        ),
        artifact_relative_path TEXT NOT NULL,
        artifact_json TEXT NOT NULL CHECK(
            length(CAST(artifact_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        material_sha256 TEXT NOT NULL UNIQUE,
        previous_event_chain_sha256 TEXT NOT NULL,
        record_chain_sha256 TEXT NOT NULL UNIQUE,
        transaction_id TEXT NOT NULL UNIQUE,
        commit_observed_at TEXT NOT NULL UNIQUE,
        commit_prepared_at TEXT NOT NULL UNIQUE,
        UNIQUE(event_type, stable_key_sha256)
    );
    CREATE TABLE frontier_selections (
        event_sequence INTEGER PRIMARY KEY REFERENCES frontier_events(event_sequence),
        selection_key_sha256 TEXT NOT NULL UNIQUE,
        source_pair_sha256 TEXT NOT NULL UNIQUE,
        commitment_snapshot_sha256 TEXT NOT NULL,
        outcome_snapshot_sha256 TEXT NOT NULL,
        commitment_total INTEGER NOT NULL CHECK(commitment_total >= 0),
        outcome_total INTEGER NOT NULL CHECK(outcome_total >= 0),
        commitment_chain_head_sha256 TEXT NOT NULL,
        outcome_chain_head_sha256 TEXT NOT NULL
    );
    CREATE TABLE frontier_candidates (
        event_sequence INTEGER PRIMARY KEY REFERENCES frontier_events(event_sequence),
        candidate_key_sha256 TEXT NOT NULL UNIQUE,
        selection_event_sequence INTEGER NOT NULL REFERENCES frontier_selections(event_sequence),
        model_parameter_fingerprint TEXT NOT NULL,
        model_binding_sha256 TEXT NOT NULL,
        accounting_root_sha256 TEXT NOT NULL,
        candidate_root_sha256 TEXT NOT NULL
    );
    CREATE TABLE frontier_append_receipts (
        transaction_id TEXT PRIMARY KEY REFERENCES frontier_events(transaction_id),
        event_sequence INTEGER NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL,
        record_chain_sha256 TEXT NOT NULL,
        receipt_sha256 TEXT NOT NULL UNIQUE,
        receipt_json TEXT NOT NULL CHECK(
            length(CAST(receipt_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        commit_observed_at TEXT NOT NULL,
        commit_prepared_at TEXT NOT NULL
    );
    CREATE TABLE frontier_postcommit_receipts (
        transaction_id TEXT PRIMARY KEY REFERENCES frontier_events(transaction_id),
        event_sequence INTEGER NOT NULL UNIQUE,
        append_receipt_sha256 TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL,
        record_chain_sha256 TEXT NOT NULL,
        event_status TEXT NOT NULL,
        accounting_root_sha256 TEXT,
        receipt_sha256 TEXT NOT NULL UNIQUE,
        receipt_json TEXT NOT NULL CHECK(
            length(CAST(receipt_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        postcommit_observed_at TEXT NOT NULL UNIQUE,
        postcommit_readback_at TEXT NOT NULL UNIQUE
    );
    CREATE TABLE frontier_head_anchors (
        event_sequence INTEGER PRIMARY KEY REFERENCES frontier_events(event_sequence),
        transaction_id TEXT NOT NULL UNIQUE,
        event_type TEXT NOT NULL,
        artifact_sha256 TEXT NOT NULL,
        record_chain_sha256 TEXT NOT NULL,
        append_receipt_sha256 TEXT NOT NULL,
        postcommit_receipt_sha256 TEXT NOT NULL,
        previous_head_anchor_sha256 TEXT NOT NULL,
        head_anchor_sha256 TEXT NOT NULL UNIQUE,
        head_anchor_byte_count INTEGER NOT NULL CHECK(
            head_anchor_byte_count > 0 AND head_anchor_byte_count <= {_MAX_JSON_BYTES}
        ),
        head_anchor_relative_path TEXT NOT NULL,
        head_anchor_json TEXT NOT NULL CHECK(
            length(CAST(head_anchor_json AS BLOB)) <= {_MAX_JSON_BYTES}
        ),
        anchored_at TEXT NOT NULL UNIQUE
    );
    """ + "\n".join(
        f"""
        CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table}
        BEGIN SELECT RAISE(ABORT, '{table}_rows_are_immutable'); END;
        CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
        BEGIN SELECT RAISE(ABORT, '{table}_rows_are_immutable'); END;
        """
        for table in (
            "frontier_metadata",
            "frontier_events",
            "frontier_selections",
            "frontier_candidates",
            "frontier_append_receipts",
            "frontier_postcommit_receipts",
            "frontier_head_anchors",
        )
    )


_METADATA: Final = {
    "ledger_schema_version": PROFILED_RESEARCH_CANONICAL_FRONTIER_LEDGER_V1_SCHEMA_VERSION,
    "retention_policy": "APPEND_ONLY_NO_AUTOMATIC_PRUNING",
    "automatic_pruning_enabled": "false",
    "runtime_wired": "false",
    "optimizer_authorized": "false",
}


@dataclass(frozen=True, slots=True)
class CanonicalFrontierSelectionResultV1:
    selection_key_sha256: str
    source_pair_sha256: str
    selection_event_sequence: int
    selection_artifact_sha256: str
    selection_anchored_at: str
    terminal_cutoff_observed_at: str
    terminal_accounting_root_sha256: str
    terminal_accounting_complete: bool
    terminal_commitment_count: int
    due_missing_outcome_count: int
    _ledger: ProfiledResearchCanonicalCandidateFrontierLedgerV1 = field(
        repr=False,
        compare=False,
    )
    _factory_seal: str = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    @property
    def runtime_wired(self) -> bool:
        self._ledger._validate_selection_result(self)  # noqa: SLF001
        return False


@dataclass(frozen=True, slots=True)
class CanonicalFrontierCandidateResultV1:
    candidate_key_sha256: str
    selection_key_sha256: str
    candidate_event_sequence: int
    candidate_artifact_sha256: str
    candidate_head_anchor_sha256: str
    candidate_anchored_at: str
    model_parameter_fingerprint: str
    calibration_candidate_row_count: int
    _ledger: ProfiledResearchCanonicalCandidateFrontierLedgerV1 = field(
        repr=False,
        compare=False,
    )
    _factory_seal: str = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    @property
    def runtime_wired(self) -> bool:
        self._ledger._validate_candidate_result(self)  # noqa: SLF001
        return False


def _source_pair_binding(
    commitment_snapshot: ProfiledResearchShadowCommitmentInventorySnapshotV1,
    outcome_snapshot: ProfiledResearchFinalizedOutcomeInventorySnapshotV1,
) -> dict[str, Any]:
    commitment_contract = commitment_snapshot.snapshot_contract
    outcome_contract = outcome_snapshot.snapshot_contract
    commitment_binding = commitment_contract.get("ledger_binding")
    outcome_binding = outcome_contract.get("ledger_binding")
    if type(commitment_binding) is not dict or type(outcome_binding) is not dict:
        _integrity("FRONTIER_SOURCE_LEDGER_BINDING_INVALID")
    stable = {
        "commitment_ledger_binding": commitment_binding,
        "commitment_inventory_sha256": commitment_contract.get("inventory_sha256"),
        "outcome_ledger_binding": outcome_binding,
        "outcome_inventory_sha256": outcome_contract.get("inventory_sha256"),
    }
    if any(
        _strict_sha256(stable[name]) is None
        for name in ("commitment_inventory_sha256", "outcome_inventory_sha256")
    ):
        _integrity("FRONTIER_SOURCE_INVENTORY_DIGEST_INVALID")
    source_pair_sha256 = _sha256(
        {"domain": "profiled-research-canonical-source-pair/v1", **stable}
    )
    return {
        "source_pair_sha256": source_pair_sha256,
        "commitment_snapshot_cas_address": _address_mapping(
            commitment_snapshot.snapshot_artifact_address
        ),
        "commitment_ledger_binding": commitment_binding,
        "commitment_inventory_sha256": stable["commitment_inventory_sha256"],
        "outcome_snapshot_cas_address": _address_mapping(
            outcome_snapshot.snapshot_artifact_address
        ),
        "outcome_ledger_binding": outcome_binding,
        "outcome_inventory_sha256": stable["outcome_inventory_sha256"],
    }


def _validate_source_pair_binding(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _SOURCE_PAIR_FIELDS:
        _integrity("FRONTIER_SOURCE_PAIR_FIELDS_INVALID")
    binding = cast(dict[str, Any], value)
    commitment_ledger = binding.get("commitment_ledger_binding")
    outcome_ledger = binding.get("outcome_ledger_binding")
    if (
        type(commitment_ledger) is not dict
        or type(outcome_ledger) is not dict
        or _strict_sha256(binding.get("commitment_inventory_sha256")) is None
        or _strict_sha256(binding.get("outcome_inventory_sha256")) is None
    ):
        _integrity("FRONTIER_SOURCE_PAIR_INVALID")
    _address_from_mapping(
        binding.get("commitment_snapshot_cas_address"),
        reason="FRONTIER_COMMITMENT_SNAPSHOT_ADDRESS_INVALID",
    )
    _address_from_mapping(
        binding.get("outcome_snapshot_cas_address"),
        reason="FRONTIER_OUTCOME_SNAPSHOT_ADDRESS_INVALID",
    )
    stable = {
        "commitment_ledger_binding": commitment_ledger,
        "commitment_inventory_sha256": binding["commitment_inventory_sha256"],
        "outcome_ledger_binding": outcome_ledger,
        "outcome_inventory_sha256": binding["outcome_inventory_sha256"],
    }
    expected = _sha256(
        {"domain": "profiled-research-canonical-source-pair/v1", **stable}
    )
    if binding.get("source_pair_sha256") != expected:
        _integrity("FRONTIER_SOURCE_PAIR_DIGEST_INVALID")
    return binding


def _validate_event_binding(value: object, *, expected_type: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _EVENT_BINDING_FIELDS:
        _integrity("FRONTIER_EVENT_BINDING_FIELDS_INVALID")
    binding = cast(dict[str, Any], value)
    observed = _aware_clock(binding.get("event_commit_observed_at"))
    prepared = _millisecond_clock(binding.get("event_commit_prepared_at"))
    if (
        type(binding.get("event_sequence")) is not int
        or cast(int, binding["event_sequence"]) <= 0
        or binding.get("event_type") != expected_type
        or _strict_sha256(binding.get("transaction_id")) is None
        or _strict_sha256(binding.get("previous_event_chain_sha256")) is None
        or observed is None
        or _format_microsecond(observed) != binding.get("event_commit_observed_at")
        or prepared is None
        or observed > prepared
    ):
        _integrity("FRONTIER_EVENT_BINDING_INVALID")
    return binding


def _prepare_selection_artifact(
    *,
    selection_key_sha256: str,
    source_pair_binding: dict[str, Any],
    event_binding: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "schema_version": PROFILED_RESEARCH_CANONICAL_FRONTIER_SELECTION_V1_SCHEMA_VERSION,
        "classification": PROFILED_RESEARCH_CANONICAL_FRONTIER_SELECTION_V1_CLASSIFICATION,
        "selection_key_sha256": selection_key_sha256,
        "source_pair_binding": source_pair_binding,
        "event_binding": event_binding,
        "authorization": dict(_AUTHORIZATION),
        "status": dict(_SELECTION_STATUS),
    }
    return {**base, "selection_material_sha256": _sha256(base)}


def validate_profiled_research_canonical_frontier_selection_v1(
    payload: object,
) -> dict[str, Any]:
    if type(payload) is not bytes:
        _validation("FRONTIER_SELECTION_EXACT_BYTES_REQUIRED")
    artifact = _parse_exact_object(payload, reason="FRONTIER_SELECTION_JSON_INVALID")
    if (
        set(artifact) != _SELECTION_FIELDS
        or artifact.get("schema_version")
        != PROFILED_RESEARCH_CANONICAL_FRONTIER_SELECTION_V1_SCHEMA_VERSION
        or artifact.get("classification")
        != PROFILED_RESEARCH_CANONICAL_FRONTIER_SELECTION_V1_CLASSIFICATION
        or artifact.get("authorization") != _AUTHORIZATION
        or artifact.get("status") != _SELECTION_STATUS
    ):
        _integrity("FRONTIER_SELECTION_ARTIFACT_INVALID")
    source = _validate_source_pair_binding(artifact.get("source_pair_binding"))
    event = _validate_event_binding(artifact.get("event_binding"), expected_type="SELECTION")
    expected_key = _sha256(
        {
            "domain": "profiled-research-canonical-selection-key/v1",
            "source_pair_sha256": source["source_pair_sha256"],
        }
    )
    expected_material = _sha256(
        {
            key: artifact[key]
            for key in artifact
            if key != "selection_material_sha256"
        }
    )
    if (
        artifact.get("selection_key_sha256") != expected_key
        or artifact.get("selection_material_sha256") != expected_material
        or event["event_sequence"] <= 0
    ):
        _integrity("FRONTIER_SELECTION_MATERIAL_INVALID")
    return artifact


def _model_binding_for_fingerprint(
    outcome_rows: Sequence[Mapping[str, Any]],
    *,
    model_parameter_fingerprint: str,
) -> dict[str, Any]:
    if _strict_sha256(model_parameter_fingerprint) is None:
        _validation("FRONTIER_MODEL_FINGERPRINT_INVALID")
    matches = [
        row
        for row in outcome_rows
        if row.get("model_parameter_fingerprint") == model_parameter_fingerprint
    ]
    if not matches:
        _validation("FRONTIER_MODEL_NOT_PRESENT_IN_OUTCOME_INVENTORY")
    identities = {
        (
            row.get("checkpoint_id"),
            row.get("checkpoint_generation"),
            row.get("model_parameter_fingerprint"),
            row.get("model_binding_sha256"),
        )
        for row in matches
    }
    if len(identities) != 1:
        _integrity("FRONTIER_MODEL_BINDING_AMBIGUOUS")
    checkpoint_id, generation, fingerprint, binding_sha = identities.pop()
    binding = {
        "checkpoint_id": checkpoint_id,
        "checkpoint_generation": generation,
        "model_parameter_fingerprint": fingerprint,
        "model_binding_sha256": binding_sha,
        "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
        "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
    }
    return _validate_model_binding(binding)


def _validate_model_binding(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _MODEL_FIELDS:
        _integrity("FRONTIER_MODEL_BINDING_FIELDS_INVALID")
    binding = cast(dict[str, Any], value)
    if (
        type(binding.get("checkpoint_id")) is not str
        or _IDENTIFIER_RE.fullmatch(cast(str, binding["checkpoint_id"])) is None
        or type(binding.get("checkpoint_generation")) is not int
        or cast(int, binding["checkpoint_generation"]) <= 0
        or _strict_sha256(binding.get("model_parameter_fingerprint")) is None
        or _strict_sha256(binding.get("model_binding_sha256")) is None
        or binding.get("confidence_head_schema_version")
        != CONFIDENCE_HEAD_SCHEMA_VERSION
        or binding.get("confidence_head_actions") != list(CONFIDENCE_HEAD_ACTIONS)
        or binding.get("label_semantics") != CONFIDENCE_LABEL_SEMANTICS
    ):
        _integrity("FRONTIER_MODEL_BINDING_INVALID")
    return binding


def _build_terminal_accounting(
    commitment_rows: Sequence[Mapping[str, Any]],
    outcome_rows: Sequence[Mapping[str, Any]],
    *,
    selection_anchored_at: str,
) -> tuple[list[dict[str, Any]], dict[str, int], bool]:
    anchor = _aware_clock(selection_anchored_at)
    if anchor is None:
        _integrity("FRONTIER_SELECTION_ANCHOR_INVALID")
    commitments: dict[str, Mapping[str, Any]] = {}
    for expected_sequence, row in enumerate(commitment_rows, start=1):
        identity = row.get("hypothesis_identity_sha256")
        if (
            row.get("sequence") != expected_sequence
            or _strict_sha256(identity) is None
            or identity in commitments
        ):
            _integrity("FRONTIER_COMMITMENT_INVENTORY_INVALID")
        commitments[cast(str, identity)] = row
    outcomes: dict[str, Mapping[str, Any]] = {}
    for expected_sequence, row in enumerate(outcome_rows, start=1):
        identity = row.get("hypothesis_identity_sha256")
        if (
            row.get("sequence") != expected_sequence
            or _strict_sha256(identity) is None
            or identity in outcomes
            or identity not in commitments
        ):
            _integrity("FRONTIER_OUTCOME_INVENTORY_INVALID")
        commitment = commitments[cast(str, identity)]
        if (
            commitment.get("disposition")
            != "EX_ANTE_VERIFIED_AWAITING_TERMINAL_ACCOUNTING"
            or row.get("hypothesis_artifact_sha256")
            != commitment.get("hypothesis_artifact_sha256")
            or row.get("commitment_append_receipt_sha256")
            != commitment.get("append_receipt_sha256")
            or row.get("commitment_postcommit_receipt_sha256")
            != commitment.get("postcommit_receipt_sha256")
            or row.get("commitment_record_chain_sha256")
            != commitment.get("record_chain_sha256")
            or row.get("decision_time") != commitment.get("decision_time")
            or row.get("checkpoint_id") != commitment.get("checkpoint_id")
            or row.get("checkpoint_generation")
            != commitment.get("checkpoint_generation")
            or row.get("model_parameter_fingerprint")
            != commitment.get("model_parameter_fingerprint")
        ):
            _integrity("FRONTIER_CROSS_LEDGER_BINDING_INVALID")
        outcomes[cast(str, identity)] = row
    accounting: list[dict[str, Any]] = []
    counts = {
        "finalized_calibration_eligible": 0,
        "finalized_calibration_ineligible": 0,
        "pending_label_not_available": 0,
        "quarantined_ex_ante_durability": 0,
        "due_outcome_missing": 0,
    }
    for sequence, commitment in enumerate(commitment_rows, start=1):
        identity = cast(str, commitment["hypothesis_identity_sha256"])
        outcome = outcomes.get(identity)
        disposition = commitment.get("disposition")
        outcome_artifact: str | None = None
        outcome_material: str | None = None
        calibration_row: str | None = None
        eligible: bool | None = None
        outcome_model: str | None = None
        if disposition == "QUARANTINED_EX_ANTE_DURABILITY_FAILED":
            if outcome is not None:
                _integrity("FRONTIER_QUARANTINED_COMMITMENT_HAS_OUTCOME")
            terminal = "QUARANTINED_EX_ANTE_DURABILITY"
            reason = "COMMITMENT_POSTCOMMIT_CAUSALITY_UNVERIFIED"
            counts["quarantined_ex_ante_durability"] += 1
        elif outcome is not None:
            outcome_artifact = cast(str, outcome["outcome_artifact_sha256"])
            outcome_material = cast(str, outcome["outcome_material_sha256"])
            calibration_row = cast(str, outcome["calibration_row_id"])
            eligible = cast(bool, outcome["calibration_eligible"])
            outcome_model = cast(str, outcome["model_parameter_fingerprint"])
            if eligible:
                terminal = "FINALIZED_CALIBRATION_ELIGIBLE"
                reason = "DIRECTIONAL_SELECTED_ACTION_OUTCOME_FINALIZED"
                counts["finalized_calibration_eligible"] += 1
            else:
                terminal = "FINALIZED_CALIBRATION_INELIGIBLE"
                reason = "HOLD_SELECTED_ACTION_NOT_DIRECTIONAL"
                counts["finalized_calibration_ineligible"] += 1
        else:
            label = _aware_clock(commitment.get("label_earliest_available_at"))
            if label is None:
                _integrity("FRONTIER_COMMITMENT_LABEL_CLOCK_INVALID")
            if anchor < label:
                terminal = "PENDING_LABEL_NOT_AVAILABLE_AT_FRONTIER"
                reason = "LABEL_EARLIEST_AVAILABLE_AFTER_SELECTION_ANCHOR"
                counts["pending_label_not_available"] += 1
            else:
                terminal = "DUE_OUTCOME_MISSING"
                reason = "LABEL_AVAILABLE_BY_SELECTION_ANCHOR_WITHOUT_OUTCOME"
                counts["due_outcome_missing"] += 1
        accounting.append(
            {
                "sequence": sequence,
                "commitment_sequence": commitment["sequence"],
                "hypothesis_identity_sha256": identity,
                "hypothesis_artifact_sha256": commitment[
                    "hypothesis_artifact_sha256"
                ],
                "commitment_append_receipt_sha256": commitment[
                    "append_receipt_sha256"
                ],
                "commitment_postcommit_receipt_sha256": commitment[
                    "postcommit_receipt_sha256"
                ],
                "commitment_record_chain_sha256": commitment[
                    "record_chain_sha256"
                ],
                "decision_time": commitment["decision_time"],
                "label_earliest_available_at": commitment[
                    "label_earliest_available_at"
                ],
                "commitment_disposition": disposition,
                "terminal_disposition": terminal,
                "terminal_reason": reason,
                "outcome_artifact_sha256": outcome_artifact,
                "outcome_material_sha256": outcome_material,
                "outcome_calibration_row_id": calibration_row,
                "outcome_calibration_eligible": eligible,
                "outcome_model_parameter_fingerprint": outcome_model,
            }
        )
    complete = counts["due_outcome_missing"] == 0
    return accounting, counts, complete


def _candidate_rows_for_model(
    outcome_rows: Sequence[Mapping[str, Any]],
    *,
    model_parameter_fingerprint: str,
) -> list[dict[str, Any]]:
    selected = [
        row
        for row in outcome_rows
        if row.get("model_parameter_fingerprint") == model_parameter_fingerprint
        and row.get("calibration_eligible") is True
    ]
    selected.sort(key=lambda row: (row["decision_time"], row["calibration_row_id"]))
    candidate_rows: list[dict[str, Any]] = []
    for sequence, row in enumerate(selected, start=1):
        candidate_rows.append(
            {
                "sequence": sequence,
                "calibration_row_id": row["calibration_row_id"],
                "hypothesis_identity_sha256": row["hypothesis_identity_sha256"],
                "hypothesis_artifact_sha256": row["hypothesis_artifact_sha256"],
                "outcome_artifact_sha256": row["outcome_artifact_sha256"],
                "outcome_material_sha256": row["outcome_material_sha256"],
                "label_source_binding_sha256": row["label_source_binding_sha256"],
                "append_receipt_sha256": row["append_receipt_sha256"],
                "postcommit_receipt_sha256": row["postcommit_receipt_sha256"],
                "record_chain_sha256": row["record_chain_sha256"],
                "decision_time": row["decision_time"],
                "actual_label_available_at": row["actual_label_available_at"],
                "maturation_observed_at": row["maturation_observed_at"],
                "postcommit_readback_at": row["postcommit_readback_at"],
                "selected_action": row["selected_action"],
                "raw_probability": row["raw_probability"],
                "observed_strictly_positive_net_pnl": row[
                    "observed_strictly_positive_net_pnl"
                ],
                "model_binding_sha256": row["model_binding_sha256"],
            }
        )
    return candidate_rows


def _validate_accounting_row(row: object, *, expected_sequence: int) -> dict[str, Any]:
    if type(row) is not dict or set(row) != _ACCOUNTING_ROW_FIELDS:
        _integrity("FRONTIER_ACCOUNTING_ROW_FIELDS_INVALID")
    value = cast(dict[str, Any], row)
    terminal = value.get("terminal_disposition")
    outcome_present = terminal in {
        "FINALIZED_CALIBRATION_ELIGIBLE",
        "FINALIZED_CALIBRATION_INELIGIBLE",
    }
    if (
        type(value.get("sequence")) is not int
        or value.get("sequence") != expected_sequence
        or type(value.get("commitment_sequence")) is not int
        or cast(int, value["commitment_sequence"]) <= 0
        or any(
            _strict_sha256(value.get(name)) is None
            for name in (
                "hypothesis_identity_sha256",
                "hypothesis_artifact_sha256",
                "commitment_append_receipt_sha256",
                "commitment_postcommit_receipt_sha256",
                "commitment_record_chain_sha256",
            )
        )
        or _aware_clock(value.get("decision_time")) is None
        or _aware_clock(value.get("label_earliest_available_at")) is None
        or value.get("commitment_disposition")
        not in {
            "EX_ANTE_VERIFIED_AWAITING_TERMINAL_ACCOUNTING",
            "QUARANTINED_EX_ANTE_DURABILITY_FAILED",
        }
        or terminal
        not in {
            "FINALIZED_CALIBRATION_ELIGIBLE",
            "FINALIZED_CALIBRATION_INELIGIBLE",
            "PENDING_LABEL_NOT_AVAILABLE_AT_FRONTIER",
            "QUARANTINED_EX_ANTE_DURABILITY",
            "DUE_OUTCOME_MISSING",
        }
        or type(value.get("terminal_reason")) is not str
        or not cast(str, value["terminal_reason"])
        or (
            outcome_present
            and (
                any(
                    _strict_sha256(value.get(name)) is None
                    for name in (
                        "outcome_artifact_sha256",
                        "outcome_material_sha256",
                        "outcome_calibration_row_id",
                        "outcome_model_parameter_fingerprint",
                    )
                )
                or type(value.get("outcome_calibration_eligible")) is not bool
            )
        )
        or (
            not outcome_present
            and any(
                value.get(name) is not None
                for name in (
                    "outcome_artifact_sha256",
                    "outcome_material_sha256",
                    "outcome_calibration_row_id",
                    "outcome_calibration_eligible",
                    "outcome_model_parameter_fingerprint",
                )
            )
        )
    ):
        _integrity("FRONTIER_ACCOUNTING_ROW_INVALID")
    return value


def _validate_candidate_row(row: object, *, expected_sequence: int) -> dict[str, Any]:
    if type(row) is not dict or set(row) != _CANDIDATE_ROW_FIELDS:
        _integrity("FRONTIER_CANDIDATE_ROW_FIELDS_INVALID")
    value = cast(dict[str, Any], row)
    probability = _finite_float(value.get("raw_probability"))
    if (
        type(value.get("sequence")) is not int
        or value.get("sequence") != expected_sequence
        or any(
            _strict_sha256(value.get(name)) is None
            for name in (
                "calibration_row_id",
                "hypothesis_identity_sha256",
                "hypothesis_artifact_sha256",
                "outcome_artifact_sha256",
                "outcome_material_sha256",
                "label_source_binding_sha256",
                "append_receipt_sha256",
                "postcommit_receipt_sha256",
                "record_chain_sha256",
                "model_binding_sha256",
            )
        )
        or any(
            _aware_clock(value.get(name)) is None
            for name in (
                "decision_time",
                "actual_label_available_at",
                "maturation_observed_at",
            )
        )
        or _millisecond_clock(value.get("postcommit_readback_at")) is None
        or value.get("selected_action") not in CONFIDENCE_HEAD_ACTIONS
        or probability is None
        or not 0.0 <= probability <= 1.0
        or type(value.get("observed_strictly_positive_net_pnl")) is not bool
    ):
        _integrity("FRONTIER_CANDIDATE_ROW_INVALID")
    return value


def _publish_paged_root(
    *,
    rows: list[dict[str, Any]],
    root_key_sha256: str,
    page_schema_version: str,
    root_schema_version: str,
    genesis_page_sha256: str,
    counts: Mapping[str, int],
    store: ImmutableSourcePayloadStore,
    row_kind: str,
) -> tuple[SourcePayloadAddress, dict[str, Any]]:
    if _strict_sha256(root_key_sha256) is None or len(rows) > _MAX_SOURCE_ROWS:
        _integrity("FRONTIER_PAGED_ROOT_INPUT_INVALID")
    descriptors: list[dict[str, Any]] = []
    previous_page_material = genesis_page_sha256
    for page_index, offset in enumerate(range(0, len(rows), _PAGE_MAX_ROWS)):
        page_rows = rows[offset : offset + _PAGE_MAX_ROWS]
        first_sequence = offset + 1
        if row_kind == "ACCOUNTING":
            for expected, row in enumerate(page_rows, start=first_sequence):
                _validate_accounting_row(row, expected_sequence=expected)
        elif row_kind == "CANDIDATE":
            for expected, row in enumerate(page_rows, start=first_sequence):
                _validate_candidate_row(row, expected_sequence=expected)
        else:
            _integrity("FRONTIER_PAGE_ROW_KIND_INVALID")
        base = {
            "schema_version": page_schema_version,
            "root_key_sha256": root_key_sha256,
            "page_index": page_index,
            "first_sequence": first_sequence,
            "last_sequence": first_sequence + len(page_rows) - 1,
            "row_count": len(page_rows),
            "previous_page_material_sha256": previous_page_material,
            "ordered_rows": page_rows,
            "authorization": dict(_AUTHORIZATION),
        }
        page = {**base, "page_material_sha256": _sha256(base)}
        payload = _canonical_bytes(page, reason="FRONTIER_PAGE_JSON_INVALID")
        address = _put_exact(store, payload)
        descriptors.append(
            {
                "page_index": page_index,
                "first_sequence": first_sequence,
                "last_sequence": first_sequence + len(page_rows) - 1,
                "row_count": len(page_rows),
                "page_material_sha256": page["page_material_sha256"],
                "page_cas_address": _address_mapping(address),
            }
        )
        previous_page_material = cast(str, page["page_material_sha256"])
    descriptor_digest = _sha256(
        {
            "domain": "profiled-research-canonical-frontier-page-descriptors/v1",
            "root_key_sha256": root_key_sha256,
            "total_rows": len(rows),
            "ordered_page_descriptors": descriptors,
        }
    )
    base_root = {
        "schema_version": root_schema_version,
        "root_key_sha256": root_key_sha256,
        "total_rows": len(rows),
        "ordered_page_descriptors": descriptors,
        "page_descriptor_digest": descriptor_digest,
        "counts": dict(counts),
        "authorization": dict(_AUTHORIZATION),
    }
    root = {**base_root, "root_material_sha256": _sha256(base_root)}
    return _put_exact(
        store,
        _canonical_bytes(root, reason="FRONTIER_ROOT_JSON_INVALID"),
    ), root


def _load_paged_root(
    *,
    root_address: SourcePayloadAddress,
    expected_root_key_sha256: str,
    page_schema_version: str,
    root_schema_version: str,
    genesis_page_sha256: str,
    store: ImmutableSourcePayloadStore,
    row_kind: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = _parse_exact_object(
        _get_exact(store, root_address, reason="FRONTIER_ROOT_CAS_REOPEN_FAILED"),
        reason="FRONTIER_ROOT_JSON_INVALID",
    )
    if (
        set(root) != _ROOT_FIELDS
        or root.get("schema_version") != root_schema_version
        or root.get("root_key_sha256") != expected_root_key_sha256
        or type(root.get("total_rows")) is not int
        or not 0 <= cast(int, root["total_rows"]) <= _MAX_SOURCE_ROWS
        or type(root.get("ordered_page_descriptors")) is not list
        or len(cast(list[Any], root["ordered_page_descriptors"])) > _MAX_PAGES
        or type(root.get("counts")) is not dict
        or root.get("authorization") != _AUTHORIZATION
    ):
        _integrity("FRONTIER_ROOT_INVALID")
    descriptors = cast(list[Any], root["ordered_page_descriptors"])
    expected_digest = _sha256(
        {
            "domain": "profiled-research-canonical-frontier-page-descriptors/v1",
            "root_key_sha256": expected_root_key_sha256,
            "total_rows": root["total_rows"],
            "ordered_page_descriptors": descriptors,
        }
    )
    expected_material = _sha256(
        {key: root[key] for key in root if key != "root_material_sha256"}
    )
    if (
        root.get("page_descriptor_digest") != expected_digest
        or root.get("root_material_sha256") != expected_material
    ):
        _integrity("FRONTIER_ROOT_MATERIAL_INVALID")
    rows: list[dict[str, Any]] = []
    previous_page_material = genesis_page_sha256
    expected_first = 1
    for expected_index, raw_descriptor in enumerate(descriptors):
        if (
            type(raw_descriptor) is not dict
            or set(raw_descriptor) != _PAGE_DESCRIPTOR_FIELDS
        ):
            _integrity("FRONTIER_PAGE_DESCRIPTOR_FIELDS_INVALID")
        descriptor = cast(dict[str, Any], raw_descriptor)
        address = _address_from_mapping(
            descriptor.get("page_cas_address"),
            reason="FRONTIER_PAGE_ADDRESS_INVALID",
        )
        page = _parse_exact_object(
            _get_exact(store, address, reason="FRONTIER_PAGE_CAS_REOPEN_FAILED"),
            reason="FRONTIER_PAGE_JSON_INVALID",
        )
        page_rows = page.get("ordered_rows")
        row_count = descriptor.get("row_count")
        if (
            set(page) != _PAGE_FIELDS
            or page.get("schema_version") != page_schema_version
            or page.get("root_key_sha256") != expected_root_key_sha256
            or type(page.get("page_index")) is not int
            or page.get("page_index") != expected_index
            or descriptor.get("page_index") != expected_index
            or type(row_count) is not int
            or not 0 < cast(int, row_count) <= _PAGE_MAX_ROWS
            or type(page_rows) is not list
            or len(cast(list[Any], page_rows)) != row_count
            or page.get("first_sequence") != expected_first
            or descriptor.get("first_sequence") != expected_first
            or page.get("last_sequence") != expected_first + cast(int, row_count) - 1
            or descriptor.get("last_sequence")
            != expected_first + cast(int, row_count) - 1
            or page.get("row_count") != row_count
            or page.get("previous_page_material_sha256") != previous_page_material
            or page.get("page_material_sha256")
            != descriptor.get("page_material_sha256")
            or page.get("authorization") != _AUTHORIZATION
        ):
            _integrity("FRONTIER_PAGE_REPLAY_MISMATCH")
        expected_page_material = _sha256(
            {key: page[key] for key in page if key != "page_material_sha256"}
        )
        if page.get("page_material_sha256") != expected_page_material:
            _integrity("FRONTIER_PAGE_MATERIAL_INVALID")
        for expected, row in enumerate(
            cast(list[Any], page_rows),
            start=expected_first,
        ):
            if row_kind == "ACCOUNTING":
                rows.append(_validate_accounting_row(row, expected_sequence=expected))
            elif row_kind == "CANDIDATE":
                rows.append(_validate_candidate_row(row, expected_sequence=expected))
            else:
                _integrity("FRONTIER_PAGE_ROW_KIND_INVALID")
        previous_page_material = cast(str, page["page_material_sha256"])
        expected_first += cast(int, row_count)
    if len(rows) != root["total_rows"] or (not rows) != (not descriptors):
        _integrity("FRONTIER_ROOT_CARDINALITY_INVALID")
    counts = cast(dict[str, Any], root["counts"])
    if any(
        type(key) is not str or type(value) is not int or value < 0
        for key, value in counts.items()
    ):
        _integrity("FRONTIER_ROOT_COUNTS_INVALID")
    if row_kind == "ACCOUNTING":
        expected_counts = {
            "finalized_calibration_eligible": 0,
            "finalized_calibration_ineligible": 0,
            "pending_label_not_available": 0,
            "quarantined_ex_ante_durability": 0,
            "due_outcome_missing": 0,
        }
        disposition_keys = {
            "FINALIZED_CALIBRATION_ELIGIBLE": "finalized_calibration_eligible",
            "FINALIZED_CALIBRATION_INELIGIBLE": "finalized_calibration_ineligible",
            "PENDING_LABEL_NOT_AVAILABLE_AT_FRONTIER": "pending_label_not_available",
            "QUARANTINED_EX_ANTE_DURABILITY": "quarantined_ex_ante_durability",
            "DUE_OUTCOME_MISSING": "due_outcome_missing",
        }
        for row in rows:
            expected_counts[disposition_keys[row["terminal_disposition"]]] += 1
        if counts != expected_counts:
            _integrity("FRONTIER_ACCOUNTING_COUNTS_INVALID")
    elif row_kind == "CANDIDATE" and counts != {
        "calibration_candidate_rows": len(rows)
    }:
        _integrity("FRONTIER_CANDIDATE_COUNTS_INVALID")
    return root, rows


def _prepare_candidate_artifact(
    *,
    candidate_key_sha256: str,
    selection_binding: dict[str, Any],
    model_binding: dict[str, Any],
    accounting_root_address: SourcePayloadAddress,
    candidate_root_address: SourcePayloadAddress,
    event_binding: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "schema_version": PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_V1_SCHEMA_VERSION,
        "classification": PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_V1_CLASSIFICATION,
        "candidate_key_sha256": candidate_key_sha256,
        "selection_binding": selection_binding,
        "model_binding": model_binding,
        "terminal_accounting_root_cas_address": _address_mapping(
            accounting_root_address
        ),
        "candidate_inventory_root_cas_address": _address_mapping(
            candidate_root_address
        ),
        "event_binding": event_binding,
        "authorization": dict(_AUTHORIZATION),
        "status": dict(_CANDIDATE_STATUS),
    }
    return {**base, "candidate_material_sha256": _sha256(base)}


def validate_profiled_research_canonical_frontier_candidate_v1(
    payload: object,
) -> dict[str, Any]:
    if type(payload) is not bytes:
        _validation("FRONTIER_CANDIDATE_EXACT_BYTES_REQUIRED")
    artifact = _parse_exact_object(payload, reason="FRONTIER_CANDIDATE_JSON_INVALID")
    if (
        set(artifact) != _CANDIDATE_FIELDS
        or artifact.get("schema_version")
        != PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_V1_SCHEMA_VERSION
        or artifact.get("classification")
        != PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_V1_CLASSIFICATION
        or artifact.get("authorization") != _AUTHORIZATION
        or artifact.get("status") != _CANDIDATE_STATUS
    ):
        _integrity("FRONTIER_CANDIDATE_ARTIFACT_INVALID")
    selection = artifact.get("selection_binding")
    if (
        type(selection) is not dict
        or set(selection) != _CANDIDATE_SELECTION_BINDING_FIELDS
        or type(selection.get("selection_event_sequence")) is not int
        or cast(int, selection["selection_event_sequence"]) <= 0
        or any(
            _strict_sha256(selection.get(name)) is None
            for name in (
                "selection_key_sha256",
                "selection_artifact_sha256",
                "source_pair_sha256",
                "selection_head_anchor_sha256",
                "terminal_accounting_root_sha256",
            )
        )
        or _millisecond_clock(selection.get("selection_anchored_at")) is None
        or _aware_clock(selection.get("terminal_cutoff_observed_at")) is None
    ):
        _integrity("FRONTIER_CANDIDATE_SELECTION_BINDING_INVALID")
    model = _validate_model_binding(artifact.get("model_binding"))
    _address_from_mapping(
        artifact.get("terminal_accounting_root_cas_address"),
        reason="FRONTIER_ACCOUNTING_ROOT_ADDRESS_INVALID",
    )
    _address_from_mapping(
        artifact.get("candidate_inventory_root_cas_address"),
        reason="FRONTIER_CANDIDATE_ROOT_ADDRESS_INVALID",
    )
    _validate_event_binding(artifact.get("event_binding"), expected_type="CANDIDATE")
    expected_key = _sha256(
        {
            "domain": "profiled-research-canonical-candidate-key/v1",
            "selection_key_sha256": selection["selection_key_sha256"],
            "model_binding": model,
        }
    )
    expected_material = _sha256(
        {
            key: artifact[key]
            for key in artifact
            if key != "candidate_material_sha256"
        }
    )
    if (
        artifact.get("candidate_key_sha256") != expected_key
        or artifact.get("candidate_material_sha256") != expected_material
    ):
        _integrity("FRONTIER_CANDIDATE_MATERIAL_INVALID")
    return artifact


def _append_receipt_contract(
    *,
    event_sequence: int,
    event_type: str,
    transaction_id: str,
    artifact_sha256: str,
    record_chain_sha256: str,
    total_events: int,
    commit_observed_at: str,
    commit_prepared_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": PROFILED_RESEARCH_CANONICAL_FRONTIER_APPEND_RECEIPT_V1_SCHEMA_VERSION,
        "event_sequence": event_sequence,
        "event_type": event_type,
        "transaction_id": transaction_id,
        "artifact_sha256": artifact_sha256,
        "record_chain_sha256": record_chain_sha256,
        "total_events": total_events,
        "commit_observed_at": commit_observed_at,
        "commit_prepared_at": commit_prepared_at,
        "precommit_readback_verified": True,
        "authorization": dict(_AUTHORIZATION),
    }


def _postcommit_receipt_contract(
    *,
    event_sequence: int,
    event_type: str,
    transaction_id: str,
    artifact_sha256: str,
    record_chain_sha256: str,
    append_receipt_sha256: str,
    event_status: str,
    accounting_root_address: SourcePayloadAddress | None,
    postcommit_observed_at: str,
    postcommit_readback_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": PROFILED_RESEARCH_CANONICAL_FRONTIER_POSTCOMMIT_RECEIPT_V1_SCHEMA_VERSION,
        "event_sequence": event_sequence,
        "event_type": event_type,
        "transaction_id": transaction_id,
        "artifact_sha256": artifact_sha256,
        "record_chain_sha256": record_chain_sha256,
        "append_receipt_sha256": append_receipt_sha256,
        "event_status": event_status,
        "terminal_accounting_root_cas_address": (
            _address_mapping(accounting_root_address)
            if accounting_root_address is not None
            else None
        ),
        "postcommit_observed_at": postcommit_observed_at,
        "postcommit_readback_at": postcommit_readback_at,
        "postcommit_readback_verified": True,
        "authorization": dict(_AUTHORIZATION),
    }


def _head_anchor_contract(
    *,
    event_sequence: int,
    event_type: str,
    transaction_id: str,
    artifact_sha256: str,
    record_chain_sha256: str,
    append_receipt_sha256: str,
    postcommit_receipt_sha256: str,
    previous_head_anchor_sha256: str,
    anchored_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": PROFILED_RESEARCH_CANONICAL_FRONTIER_HEAD_ANCHOR_V1_SCHEMA_VERSION,
        "event_sequence": event_sequence,
        "event_type": event_type,
        "transaction_id": transaction_id,
        "artifact_sha256": artifact_sha256,
        "record_chain_sha256": record_chain_sha256,
        "append_receipt_sha256": append_receipt_sha256,
        "postcommit_receipt_sha256": postcommit_receipt_sha256,
        "previous_head_anchor_sha256": previous_head_anchor_sha256,
        "anchored_at": anchored_at,
        "authorization": dict(_AUTHORIZATION),
    }


class ProfiledResearchCanonicalCandidateFrontierLedgerV1:
    def __init__(self, path: Path, *, store: ImmutableSourcePayloadStore) -> None:
        if type(store) is not ImmutableSourcePayloadStore:
            _validation("FRONTIER_EXACT_IMMUTABLE_STORE_REQUIRED")
        self.path = _lexical_absolute_path(path)
        self.store = store

    def _connect_write(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(str(self.path), timeout=60.0)
            _configure_connection(connection)
            return connection
        except sqlite3.Error as exc:
            raise ProfiledResearchCanonicalFrontierV1IntegrityError(
                "FRONTIER_WRITE_CONNECTION_FAILED"
            ) from exc

    def _connect_readonly(self) -> sqlite3.Connection:
        if not self.path.is_file():
            _integrity("FRONTIER_LEDGER_MISSING")
        try:
            path_stat = os.stat(self.path, follow_symlinks=False)
            if not stat.S_ISREG(path_stat.st_mode):
                _integrity("FRONTIER_LEDGER_FILE_TYPE_INVALID")
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=ro",
                uri=True,
                timeout=60.0,
            )
            _configure_readonly_connection(connection)
            return connection
        except (OSError, sqlite3.Error) as exc:
            raise ProfiledResearchCanonicalFrontierV1IntegrityError(
                "FRONTIER_READONLY_CONNECTION_FAILED"
            ) from exc

    def _ensure_initialized(self) -> None:
        connection = self._connect_write()
        existing = False
        try:
            objects = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' LIMIT 1
                """
            ).fetchone()
            if objects is not None:
                existing = True
            else:
                connection.executescript("BEGIN IMMEDIATE;\n" + _schema_script())
                connection.executemany(
                    "INSERT INTO frontier_metadata VALUES (?, ?)",
                    sorted(_METADATA.items()),
                )
                connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        if existing:
            self._validate_schema()
            return
        _fsync_parent(self.path)
        self._validate_schema()

    def _validate_schema(self) -> None:
        connection = self._connect_readonly()
        try:
            application_id = connection.execute("PRAGMA application_id").fetchone()[0]
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
            metadata = dict(
                connection.execute(
                    "SELECT metadata_key, metadata_value FROM frontier_metadata"
                ).fetchall()
            )
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
            trigger_sql = {
                row[0]: row[1]
                for row in connection.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type='trigger'"
                ).fetchall()
            }
        finally:
            connection.close()
        expected_tables = {
            "frontier_metadata",
            "frontier_events",
            "frontier_selections",
            "frontier_candidates",
            "frontier_append_receipts",
            "frontier_postcommit_receipts",
            "frontier_head_anchors",
        }
        expected_trigger_sql = {
            f"{table}_no_{operation}": " ".join(
                (
                    f"CREATE TRIGGER {table}_no_{operation} BEFORE "
                    f"{operation.upper()} ON {table} BEGIN SELECT RAISE(ABORT, "
                    f"'{table}_rows_are_immutable'); END"
                ).split()
            )
            for table in expected_tables
            for operation in ("update", "delete")
        }
        normalized_trigger_sql = {
            name: " ".join(cast(str, sql).split())
            for name, sql in trigger_sql.items()
            if type(sql) is str
        }
        if (
            application_id != _APPLICATION_ID
            or user_version != _USER_VERSION
            or metadata != _METADATA
            or tables != expected_tables
            or normalized_trigger_sql != expected_trigger_sql
        ):
            _integrity("FRONTIER_SCHEMA_INVALID")

    @staticmethod
    def _joined_rows(connection: sqlite3.Connection) -> list[sqlite3.Row]:
        rows = connection.execute(
            """
            SELECT e.*,
              s.selection_key_sha256, s.source_pair_sha256,
              s.commitment_snapshot_sha256, s.outcome_snapshot_sha256,
              s.commitment_total, s.outcome_total,
              s.commitment_chain_head_sha256, s.outcome_chain_head_sha256,
              c.candidate_key_sha256, c.selection_event_sequence,
              c.model_parameter_fingerprint, c.model_binding_sha256,
              c.accounting_root_sha256, c.candidate_root_sha256,
              a.event_sequence AS append_event_sequence,
              a.event_type AS append_event_type,
              a.artifact_sha256 AS append_artifact_sha256,
              a.record_chain_sha256 AS append_record_chain_sha256,
              a.commit_observed_at AS append_commit_observed_at,
              a.commit_prepared_at AS append_commit_prepared_at,
              a.receipt_sha256 AS append_receipt_sha256,
              a.receipt_json AS append_receipt_json,
              p.event_sequence AS post_event_sequence,
              p.append_receipt_sha256 AS post_append_receipt_sha256,
              p.artifact_sha256 AS post_artifact_sha256,
              p.record_chain_sha256 AS post_record_chain_sha256,
              p.event_status, p.accounting_root_sha256 AS post_accounting_root_sha256,
              p.receipt_sha256 AS postcommit_receipt_sha256,
              p.receipt_json AS postcommit_receipt_json,
              p.postcommit_observed_at, p.postcommit_readback_at,
              h.transaction_id AS head_transaction_id,
              h.event_type AS head_event_type,
              h.artifact_sha256 AS head_artifact_sha256,
              h.record_chain_sha256 AS head_record_chain_sha256,
              h.append_receipt_sha256 AS head_append_receipt_sha256,
              h.postcommit_receipt_sha256 AS head_postcommit_receipt_sha256,
              h.previous_head_anchor_sha256, h.head_anchor_sha256,
              h.head_anchor_byte_count, h.head_anchor_relative_path,
              h.head_anchor_json, h.anchored_at
            FROM frontier_events AS e
            LEFT JOIN frontier_selections AS s USING(event_sequence)
            LEFT JOIN frontier_candidates AS c USING(event_sequence)
            LEFT JOIN frontier_append_receipts AS a USING(transaction_id)
            LEFT JOIN frontier_postcommit_receipts AS p USING(transaction_id)
            LEFT JOIN frontier_head_anchors AS h USING(event_sequence)
            ORDER BY e.event_sequence ASC
            LIMIT ?
            """,
            (_MAX_LEDGER_EVENTS + 1,),
        ).fetchall()
        if len(rows) > _MAX_LEDGER_EVENTS:
            _integrity("FRONTIER_LEDGER_RESOURCE_BOUND_EXCEEDED")
        return rows

    @staticmethod
    def _event_chain(
        *,
        event_sequence: int,
        event_type: str,
        stable_key_sha256: str,
        artifact_sha256: str,
        material_sha256: str,
        previous_event_chain_sha256: str,
        transaction_id: str,
        commit_observed_at: str,
        commit_prepared_at: str,
    ) -> str:
        return _sha256(
            {
                "domain": "profiled-research-canonical-frontier-event-chain/v1",
                "event_sequence": event_sequence,
                "event_type": event_type,
                "stable_key_sha256": stable_key_sha256,
                "artifact_sha256": artifact_sha256,
                "material_sha256": material_sha256,
                "previous_event_chain_sha256": previous_event_chain_sha256,
                "transaction_id": transaction_id,
                "commit_observed_at": commit_observed_at,
                "commit_prepared_at": commit_prepared_at,
            }
        )

    @staticmethod
    def _next_commit_clock(
        rows: Sequence[sqlite3.Row],
    ) -> tuple[str, str]:
        observed = _utc_now().astimezone(UTC)
        if observed.tzinfo is None or observed.utcoffset() is None:
            _integrity("FRONTIER_INTERNAL_COMMIT_CLOCK_INVALID")
        if rows:
            prior_observed = _aware_clock(rows[-1]["commit_observed_at"])
            if prior_observed is None or observed <= prior_observed:
                _validation("FRONTIER_INTERNAL_COMMIT_CLOCK_NOT_MONOTONIC")
        prepared = _ceil_millisecond(observed)
        if rows:
            prior_prepared = _millisecond_clock(rows[-1]["commit_prepared_at"])
            prior_post = _millisecond_clock(rows[-1]["postcommit_readback_at"])
            if prior_prepared is None:
                _integrity("FRONTIER_PRIOR_COMMIT_CLOCK_INVALID")
            lower = max(
                value for value in (prior_prepared, prior_post) if value is not None
            )
            if prepared <= lower:
                prepared = lower + timedelta(milliseconds=1)
        return _format_microsecond(observed), _format_millisecond(prepared)

    @staticmethod
    def _next_postcommit_clock(
        rows: Sequence[sqlite3.Row], *, row: sqlite3.Row
    ) -> tuple[str, str]:
        observed = _utc_now().astimezone(UTC)
        commit_observed = _aware_clock(row["commit_observed_at"])
        commit_prepared = _millisecond_clock(row["commit_prepared_at"])
        if (
            commit_observed is None
            or commit_prepared is None
            or observed <= commit_observed
        ):
            _validation("FRONTIER_POSTCOMMIT_CLOCK_NOT_AFTER_COMMIT")
        prior_posts = [
            item
            for item in rows
            if item["postcommit_readback_at"] is not None
        ]
        if prior_posts:
            prior_observed = _aware_clock(prior_posts[-1]["postcommit_observed_at"])
            if prior_observed is None or observed <= prior_observed:
                _validation("FRONTIER_POSTCOMMIT_CLOCK_NOT_MONOTONIC")
        readback = _ceil_millisecond(observed)
        lower = commit_prepared
        if prior_posts:
            prior_readback = _millisecond_clock(
                prior_posts[-1]["postcommit_readback_at"]
            )
            if prior_readback is None:
                _integrity("FRONTIER_PRIOR_POSTCOMMIT_CLOCK_INVALID")
            lower = max(lower, prior_readback)
        if readback <= lower:
            readback = lower + timedelta(milliseconds=1)
        return _format_microsecond(observed), _format_millisecond(readback)

    def _verify_database(
        self,
        connection: sqlite3.Connection,
        *,
        require_postcommit: bool,
    ) -> list[sqlite3.Row]:
        rows = self._joined_rows(connection)
        event_count = len(rows)
        counts = {
            table: cast(
                int,
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],  # noqa: S608
            )
            for table in (
                "frontier_events",
                "frontier_selections",
                "frontier_candidates",
                "frontier_append_receipts",
                "frontier_postcommit_receipts",
                "frontier_head_anchors",
            )
        }
        post_count = counts["frontier_postcommit_receipts"]
        if (
            counts["frontier_events"] != event_count
            or counts["frontier_append_receipts"] != event_count
            or counts["frontier_selections"] + counts["frontier_candidates"]
            != event_count
            or post_count
            not in ({event_count} if require_postcommit else {event_count, event_count - 1})
            or counts["frontier_head_anchors"] != post_count
        ):
            _integrity("FRONTIER_LEDGER_CARDINALITY_INVALID")
        previous_chain = _GENESIS_EVENT_CHAIN_SHA256
        previous_head = _GENESIS_HEAD_ANCHOR_SHA256
        previous_commit_observed: datetime | None = None
        previous_commit: datetime | None = None
        previous_post_observed: datetime | None = None
        previous_post: datetime | None = None
        for sequence, row in enumerate(rows, start=1):
            if row["event_sequence"] != sequence:
                _integrity("FRONTIER_EVENT_SEQUENCE_INVALID")
            if any(
                _strict_sha256(row[name]) is None
                for name in (
                    "stable_key_sha256",
                    "artifact_sha256",
                    "material_sha256",
                    "previous_event_chain_sha256",
                    "record_chain_sha256",
                    "transaction_id",
                    "append_receipt_sha256",
                )
            ):
                _integrity("FRONTIER_EVENT_HASH_FIELD_INVALID")
            commit_observed = _aware_clock(row["commit_observed_at"])
            commit_prepared = _millisecond_clock(row["commit_prepared_at"])
            if (
                commit_observed is None
                or commit_prepared is None
                or _format_microsecond(commit_observed) != row["commit_observed_at"]
                or commit_observed > commit_prepared
                or (
                    previous_commit_observed is not None
                    and commit_observed <= previous_commit_observed
                )
                or (previous_commit is not None and commit_prepared <= previous_commit)
                or (
                    previous_post_observed is not None
                    and commit_observed <= previous_post_observed
                )
                or (previous_post is not None and commit_prepared <= previous_post)
            ):
                _integrity("FRONTIER_EVENT_CLOCK_CAUSALITY_INVALID")
            artifact_json = cast(str, row["artifact_json"])
            artifact_bytes = artifact_json.encode("ascii")
            artifact_address = SourcePayloadAddress(
                schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
                payload_sha256=cast(str, row["artifact_sha256"]),
                payload_byte_count=cast(int, row["artifact_byte_count"]),
                relative_path=cast(str, row["artifact_relative_path"]),
            )
            if artifact_address != _expected_address(artifact_bytes):
                _integrity("FRONTIER_EVENT_ARTIFACT_ADDRESS_INVALID")
            if row["event_type"] == "SELECTION":
                artifact = validate_profiled_research_canonical_frontier_selection_v1(
                    artifact_bytes
                )
                source = cast(dict[str, Any], artifact["source_pair_binding"])
                commitment_binding = cast(
                    dict[str, Any], source["commitment_ledger_binding"]
                )
                outcome_binding = cast(
                    dict[str, Any], source["outcome_ledger_binding"]
                )
                commitment_address = _address_from_mapping(
                    source["commitment_snapshot_cas_address"],
                    reason="FRONTIER_COMMITMENT_SNAPSHOT_ADDRESS_INVALID",
                )
                outcome_address = _address_from_mapping(
                    source["outcome_snapshot_cas_address"],
                    reason="FRONTIER_OUTCOME_SNAPSHOT_ADDRESS_INVALID",
                )
                if (
                    row["selection_key_sha256"] != row["stable_key_sha256"]
                    or row["source_pair_sha256"]
                    != source["source_pair_sha256"]
                    or row["commitment_snapshot_sha256"]
                    != commitment_address.payload_sha256
                    or row["outcome_snapshot_sha256"]
                    != outcome_address.payload_sha256
                    or row["commitment_total"]
                    != commitment_binding.get("total_committed_hypotheses")
                    or row["outcome_total"]
                    != outcome_binding.get("total_finalized_outcomes")
                    or row["commitment_chain_head_sha256"]
                    != commitment_binding.get("chain_head_sha256")
                    or row["outcome_chain_head_sha256"]
                    != outcome_binding.get("chain_head_sha256")
                    or row["candidate_key_sha256"] is not None
                ):
                    _integrity("FRONTIER_SELECTION_LEDGER_BINDING_INVALID")
            elif row["event_type"] == "CANDIDATE":
                artifact = validate_profiled_research_canonical_frontier_candidate_v1(
                    artifact_bytes
                )
                selection_binding = cast(
                    dict[str, Any], artifact["selection_binding"]
                )
                model_binding = cast(dict[str, Any], artifact["model_binding"])
                accounting_address = _address_from_mapping(
                    artifact["terminal_accounting_root_cas_address"],
                    reason="FRONTIER_ACCOUNTING_ROOT_ADDRESS_INVALID",
                )
                candidate_address = _address_from_mapping(
                    artifact["candidate_inventory_root_cas_address"],
                    reason="FRONTIER_CANDIDATE_ROOT_ADDRESS_INVALID",
                )
                if (
                    row["candidate_key_sha256"] != row["stable_key_sha256"]
                    or row["selection_key_sha256"] is not None
                    or row["selection_event_sequence"]
                    != selection_binding["selection_event_sequence"]
                    or row["model_parameter_fingerprint"]
                    != artifact["model_binding"]["model_parameter_fingerprint"]
                    or row["model_binding_sha256"]
                    != model_binding["model_binding_sha256"]
                    or row["accounting_root_sha256"]
                    != accounting_address.payload_sha256
                    or row["candidate_root_sha256"]
                    != candidate_address.payload_sha256
                ):
                    _integrity("FRONTIER_CANDIDATE_LEDGER_BINDING_INVALID")
            else:
                _integrity("FRONTIER_EVENT_TYPE_INVALID")
            event_binding = cast(dict[str, Any], artifact["event_binding"])
            material_field = (
                "selection_material_sha256"
                if row["event_type"] == "SELECTION"
                else "candidate_material_sha256"
            )
            expected_chain = self._event_chain(
                event_sequence=sequence,
                event_type=cast(str, row["event_type"]),
                stable_key_sha256=cast(str, row["stable_key_sha256"]),
                artifact_sha256=cast(str, row["artifact_sha256"]),
                material_sha256=cast(str, row["material_sha256"]),
                previous_event_chain_sha256=previous_chain,
                transaction_id=cast(str, row["transaction_id"]),
                commit_observed_at=cast(str, row["commit_observed_at"]),
                commit_prepared_at=cast(str, row["commit_prepared_at"]),
            )
            if (
                event_binding["event_sequence"] != sequence
                or event_binding["transaction_id"] != row["transaction_id"]
                or event_binding["previous_event_chain_sha256"] != previous_chain
                or event_binding["event_commit_observed_at"]
                != row["commit_observed_at"]
                or event_binding["event_commit_prepared_at"]
                != row["commit_prepared_at"]
                or artifact[material_field] != row["material_sha256"]
                or row["previous_event_chain_sha256"] != previous_chain
                or row["record_chain_sha256"] != expected_chain
            ):
                _integrity("FRONTIER_EVENT_CHAIN_INVALID")
            append = _append_receipt_contract(
                event_sequence=sequence,
                event_type=cast(str, row["event_type"]),
                transaction_id=cast(str, row["transaction_id"]),
                artifact_sha256=cast(str, row["artifact_sha256"]),
                record_chain_sha256=cast(str, row["record_chain_sha256"]),
                total_events=sequence,
                commit_observed_at=cast(str, row["commit_observed_at"]),
                commit_prepared_at=cast(str, row["commit_prepared_at"]),
            )
            append_json = _canonical_json(
                append, reason="FRONTIER_APPEND_RECEIPT_JSON_INVALID"
            )
            if (
                row["append_event_sequence"] != sequence
                or row["append_event_type"] != row["event_type"]
                or row["append_artifact_sha256"] != row["artifact_sha256"]
                or row["append_record_chain_sha256"]
                != row["record_chain_sha256"]
                or row["append_commit_observed_at"] != row["commit_observed_at"]
                or row["append_commit_prepared_at"] != row["commit_prepared_at"]
                or row["append_receipt_json"] != append_json
                or row["append_receipt_sha256"]
                != hashlib.sha256(append_json.encode("ascii")).hexdigest()
            ):
                _integrity("FRONTIER_APPEND_RECEIPT_INVALID")
            if row["postcommit_readback_at"] is None:
                if require_postcommit or sequence != event_count:
                    _integrity("FRONTIER_POSTCOMMIT_RECEIPT_MISSING")
            else:
                post = _parse_exact_object(
                    row["postcommit_receipt_json"],
                    reason="FRONTIER_POSTCOMMIT_RECEIPT_JSON_INVALID",
                )
                post_observed = _aware_clock(row["postcommit_observed_at"])
                post_readback = _millisecond_clock(row["postcommit_readback_at"])
                if (
                    post.get("schema_version")
                    != PROFILED_RESEARCH_CANONICAL_FRONTIER_POSTCOMMIT_RECEIPT_V1_SCHEMA_VERSION
                    or post.get("event_sequence") != sequence
                    or row["post_event_sequence"] != sequence
                    or post.get("event_type") != row["event_type"]
                    or post.get("transaction_id") != row["transaction_id"]
                    or post.get("artifact_sha256") != row["artifact_sha256"]
                    or row["post_artifact_sha256"] != row["artifact_sha256"]
                    or post.get("record_chain_sha256") != row["record_chain_sha256"]
                    or row["post_record_chain_sha256"]
                    != row["record_chain_sha256"]
                    or post.get("append_receipt_sha256")
                    != row["append_receipt_sha256"]
                    or row["post_append_receipt_sha256"]
                    != row["append_receipt_sha256"]
                    or post.get("event_status") != row["event_status"]
                    or post.get("postcommit_observed_at")
                    != row["postcommit_observed_at"]
                    or post.get("postcommit_readback_at")
                    != row["postcommit_readback_at"]
                    or post.get("postcommit_readback_verified") is not True
                    or post.get("authorization") != _AUTHORIZATION
                    or row["post_accounting_root_sha256"]
                    != cast(
                        dict[str, Any],
                        post["terminal_accounting_root_cas_address"],
                    ).get("payload_sha256")
                    or post_observed is None
                    or post_readback is None
                    or post_observed <= commit_observed
                    or post_readback < post_observed
                    or post_readback <= commit_prepared
                    or (
                        previous_post_observed is not None
                        and post_observed <= previous_post_observed
                    )
                    or (previous_post is not None and post_readback <= previous_post)
                    or row["postcommit_receipt_sha256"]
                    != hashlib.sha256(
                        cast(str, row["postcommit_receipt_json"]).encode("ascii")
                    ).hexdigest()
                ):
                    _integrity("FRONTIER_POSTCOMMIT_RECEIPT_INVALID")
                head = _parse_exact_object(
                    row["head_anchor_json"],
                    reason="FRONTIER_HEAD_ANCHOR_JSON_INVALID",
                )
                head_address = SourcePayloadAddress(
                    schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
                    payload_sha256=cast(str, row["head_anchor_sha256"]),
                    payload_byte_count=cast(int, row["head_anchor_byte_count"]),
                    relative_path=cast(str, row["head_anchor_relative_path"]),
                )
                expected_head = _head_anchor_contract(
                    event_sequence=sequence,
                    event_type=cast(str, row["event_type"]),
                    transaction_id=cast(str, row["transaction_id"]),
                    artifact_sha256=cast(str, row["artifact_sha256"]),
                    record_chain_sha256=cast(str, row["record_chain_sha256"]),
                    append_receipt_sha256=cast(str, row["append_receipt_sha256"]),
                    postcommit_receipt_sha256=cast(
                        str, row["postcommit_receipt_sha256"]
                    ),
                    previous_head_anchor_sha256=previous_head,
                    anchored_at=cast(str, row["postcommit_readback_at"]),
                )
                if (
                    head != expected_head
                    or row["head_transaction_id"] != row["transaction_id"]
                    or row["head_event_type"] != row["event_type"]
                    or row["head_artifact_sha256"] != row["artifact_sha256"]
                    or row["head_record_chain_sha256"]
                    != row["record_chain_sha256"]
                    or row["head_append_receipt_sha256"]
                    != row["append_receipt_sha256"]
                    or row["head_postcommit_receipt_sha256"]
                    != row["postcommit_receipt_sha256"]
                    or row["previous_head_anchor_sha256"] != previous_head
                    or row["anchored_at"] != row["postcommit_readback_at"]
                    or head_address
                    != _expected_address(cast(str, row["head_anchor_json"]).encode("ascii"))
                ):
                    _integrity("FRONTIER_HEAD_ANCHOR_INVALID")
                previous_head = cast(str, row["head_anchor_sha256"])
                previous_post_observed = post_observed
                previous_post = post_readback
            previous_chain = cast(str, row["record_chain_sha256"])
            previous_commit_observed = commit_observed
            previous_commit = commit_prepared
        return rows

    def _publish_head_catalog(self, row: sqlite3.Row) -> None:
        if row["head_anchor_sha256"] is None:
            _integrity("FRONTIER_HEAD_ANCHOR_MISSING")
        catalog = ImmutableSourcePayloadStore(_head_catalog_root(self.path))
        published = _put_exact(
            catalog,
            cast(str, row["head_anchor_json"]).encode("ascii"),
        )
        if published.payload_sha256 != row["head_anchor_sha256"]:
            _integrity("FRONTIER_HEAD_CATALOG_PUBLICATION_INVALID")

    def _observed_head_catalog_digests(self) -> set[str]:
        root = _head_catalog_root(self.path) / "sha256"
        if not root.exists():
            return set()
        observed: set[str] = set()
        for shard in root.iterdir():
            if not shard.is_dir() or len(shard.name) != 2:
                _integrity("FRONTIER_HEAD_CATALOG_LAYOUT_INVALID")
            for payload in shard.iterdir():
                if (
                    len(observed) >= _MAX_LEDGER_EVENTS
                    or not payload.is_file()
                    or _strict_sha256(payload.name) is None
                    or payload.name[:2] != shard.name
                ):
                    _integrity("FRONTIER_HEAD_CATALOG_LAYOUT_INVALID")
                observed.add(payload.name)
        return observed

    def _repair_and_verify_head_catalog(self, rows: Sequence[sqlite3.Row]) -> None:
        for row in rows:
            if row["head_anchor_sha256"] is not None:
                self._publish_head_catalog(row)
        expected = {
            cast(str, row["head_anchor_sha256"])
            for row in rows
            if row["head_anchor_sha256"] is not None
        }
        if self._observed_head_catalog_digests() != expected:
            _integrity("FRONTIER_HEAD_CATALOG_MEMBERSHIP_INVALID")

    def _verify_head_catalog(self, rows: Sequence[sqlite3.Row]) -> None:
        expected = {
            cast(str, row["head_anchor_sha256"])
            for row in rows
            if row["head_anchor_sha256"] is not None
        }
        if self._observed_head_catalog_digests() != expected:
            _integrity("FRONTIER_HEAD_CATALOG_MEMBERSHIP_INVALID")
        catalog = ImmutableSourcePayloadStore(_head_catalog_root(self.path))
        for row in rows:
            if row["head_anchor_sha256"] is None:
                continue
            address = SourcePayloadAddress(
                schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
                payload_sha256=cast(str, row["head_anchor_sha256"]),
                payload_byte_count=cast(int, row["head_anchor_byte_count"]),
                relative_path=cast(str, row["head_anchor_relative_path"]),
            )
            payload = _get_exact(
                catalog,
                address,
                reason="FRONTIER_HEAD_CATALOG_REOPEN_FAILED",
            )
            if payload != cast(str, row["head_anchor_json"]).encode("ascii"):
                _integrity("FRONTIER_HEAD_CATALOG_MISMATCH")

    def _append_selection_initial(
        self,
        *,
        source_pair: dict[str, Any],
        commitment_snapshot: ProfiledResearchShadowCommitmentInventorySnapshotV1,
        outcome_snapshot: ProfiledResearchFinalizedOutcomeInventorySnapshotV1,
    ) -> str:
        connection = self._connect_write()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = self._verify_database(connection, require_postcommit=False)
            if rows and rows[-1]["postcommit_readback_at"] is None:
                _integrity("FRONTIER_PENDING_TAIL_MUST_RECOVER_FIRST")
            sequence = len(rows) + 1
            previous_chain = (
                _GENESIS_EVENT_CHAIN_SHA256
                if not rows
                else cast(str, rows[-1]["record_chain_sha256"])
            )
            commit_observed, commit_prepared = self._next_commit_clock(rows)
            source_observed = [
                _aware_clock(commitment_snapshot.snapshot_observed_at),
                _aware_clock(outcome_snapshot.snapshot_observed_at),
            ]
            commit_clock = _aware_clock(commit_observed)
            if (
                commit_clock is None
                or any(value is None for value in source_observed)
                or any(commit_clock <= cast(datetime, value) for value in source_observed)
            ):
                _validation("FRONTIER_SELECTION_COMMIT_NOT_AFTER_SOURCE_SNAPSHOTS")
            selection_key = _sha256(
                {
                    "domain": "profiled-research-canonical-selection-key/v1",
                    "source_pair_sha256": source_pair["source_pair_sha256"],
                }
            )
            transaction_id = _sha256(
                {
                    "domain": "profiled-research-canonical-frontier-transaction/v1",
                    "event_sequence": sequence,
                    "stable_key_sha256": selection_key,
                    "commit_observed_at": commit_observed,
                    "nonce": secrets.token_hex(32),
                }
            )
            artifact = _prepare_selection_artifact(
                selection_key_sha256=selection_key,
                source_pair_binding=source_pair,
                event_binding={
                    "event_sequence": sequence,
                    "event_type": "SELECTION",
                    "transaction_id": transaction_id,
                    "previous_event_chain_sha256": previous_chain,
                    "event_commit_observed_at": commit_observed,
                    "event_commit_prepared_at": commit_prepared,
                },
            )
            artifact_bytes = _canonical_bytes(
                artifact, reason="FRONTIER_SELECTION_JSON_INVALID"
            )
            artifact_address = _put_exact(self.store, artifact_bytes)
            material = cast(str, artifact["selection_material_sha256"])
            chain = self._event_chain(
                event_sequence=sequence,
                event_type="SELECTION",
                stable_key_sha256=selection_key,
                artifact_sha256=artifact_address.payload_sha256,
                material_sha256=material,
                previous_event_chain_sha256=previous_chain,
                transaction_id=transaction_id,
                commit_observed_at=commit_observed,
                commit_prepared_at=commit_prepared,
            )
            append = _append_receipt_contract(
                event_sequence=sequence,
                event_type="SELECTION",
                transaction_id=transaction_id,
                artifact_sha256=artifact_address.payload_sha256,
                record_chain_sha256=chain,
                total_events=sequence,
                commit_observed_at=commit_observed,
                commit_prepared_at=commit_prepared,
            )
            append_json = _canonical_json(
                append, reason="FRONTIER_APPEND_RECEIPT_JSON_INVALID"
            )
            append_sha = hashlib.sha256(append_json.encode("ascii")).hexdigest()
            connection.execute(
                "INSERT INTO frontier_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sequence,
                    "SELECTION",
                    selection_key,
                    artifact_address.payload_sha256,
                    artifact_address.payload_byte_count,
                    artifact_address.relative_path,
                    artifact_bytes.decode("ascii"),
                    material,
                    previous_chain,
                    chain,
                    transaction_id,
                    commit_observed,
                    commit_prepared,
                ),
            )
            commitment_binding = cast(
                dict[str, Any], commitment_snapshot.snapshot_contract["ledger_binding"]
            )
            outcome_binding = cast(
                dict[str, Any], outcome_snapshot.snapshot_contract["ledger_binding"]
            )
            connection.execute(
                "INSERT INTO frontier_selections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sequence,
                    selection_key,
                    source_pair["source_pair_sha256"],
                    commitment_snapshot.snapshot_artifact_sha256,
                    outcome_snapshot.snapshot_artifact_sha256,
                    commitment_snapshot.total_committed_hypotheses,
                    outcome_snapshot.total_finalized_outcomes,
                    commitment_binding["chain_head_sha256"],
                    outcome_binding["chain_head_sha256"],
                ),
            )
            connection.execute(
                "INSERT INTO frontier_append_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    transaction_id,
                    sequence,
                    "SELECTION",
                    artifact_address.payload_sha256,
                    chain,
                    append_sha,
                    append_json,
                    commit_observed,
                    commit_prepared,
                ),
            )
            self._verify_database(connection, require_postcommit=False)
            connection.commit()
        except sqlite3.IntegrityError as exc:
            if connection.in_transaction:
                connection.rollback()
            raise ProfiledResearchCanonicalFrontierV1ConflictError(
                "FRONTIER_SELECTION_CONFLICT"
            ) from exc
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        _fsync_file(self.path)
        _fsync_parent(self.path)
        return transaction_id

    def _validate_candidate_evidence(
        self,
        *,
        row: sqlite3.Row,
        rows: Sequence[sqlite3.Row],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        event_address = SourcePayloadAddress(
            schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
            payload_sha256=cast(str, row["artifact_sha256"]),
            payload_byte_count=cast(int, row["artifact_byte_count"]),
            relative_path=cast(str, row["artifact_relative_path"]),
        )
        if _get_exact(
            self.store,
            event_address,
            reason="FRONTIER_CANDIDATE_ARTIFACT_REOPEN_FAILED",
        ) != cast(str, row["artifact_json"]).encode("ascii"):
            _integrity("FRONTIER_CANDIDATE_ARTIFACT_CAS_MISMATCH")
        artifact = validate_profiled_research_canonical_frontier_candidate_v1(
            cast(str, row["artifact_json"]).encode("ascii")
        )
        selection_binding = cast(dict[str, Any], artifact["selection_binding"])
        matches = [
            source
            for source in rows
            if source["event_sequence"]
            == selection_binding["selection_event_sequence"]
            and source["event_type"] == "SELECTION"
        ]
        if len(matches) != 1:
            _integrity("FRONTIER_CANDIDATE_SELECTION_MISSING")
        selection = matches[0]
        if (
            selection["event_status"] != "READY_FOR_MODEL_CANDIDATE"
            or selection_binding["selection_key_sha256"]
            != selection["selection_key_sha256"]
            or selection_binding["selection_artifact_sha256"]
            != selection["artifact_sha256"]
            or selection_binding["source_pair_sha256"]
            != selection["source_pair_sha256"]
            or selection_binding["selection_head_anchor_sha256"]
            != selection["head_anchor_sha256"]
            or selection_binding["selection_anchored_at"]
            != selection["anchored_at"]
            or selection_binding["terminal_cutoff_observed_at"]
            != selection["postcommit_observed_at"]
        ):
            _integrity("FRONTIER_CANDIDATE_SELECTION_MISMATCH")
        accounting_address = _address_from_mapping(
            artifact["terminal_accounting_root_cas_address"],
            reason="FRONTIER_ACCOUNTING_ROOT_ADDRESS_INVALID",
        )
        if (
            selection_binding["terminal_accounting_root_sha256"]
            != accounting_address.payload_sha256
            or selection["post_accounting_root_sha256"]
            != accounting_address.payload_sha256
        ):
            _integrity("FRONTIER_CANDIDATE_ACCOUNTING_BINDING_MISMATCH")
        accounting_root_key = _sha256(
            {
                "domain": "profiled-research-canonical-accounting-root-key/v1",
                "selection_key_sha256": selection["selection_key_sha256"],
                "selection_anchored_at": selection["anchored_at"],
                "terminal_cutoff_observed_at": selection[
                    "postcommit_observed_at"
                ],
            }
        )
        _load_paged_root(
            root_address=accounting_address,
            expected_root_key_sha256=accounting_root_key,
            page_schema_version=(
                PROFILED_RESEARCH_CANONICAL_FRONTIER_ACCOUNTING_PAGE_V1_SCHEMA_VERSION
            ),
            root_schema_version=(
                PROFILED_RESEARCH_CANONICAL_FRONTIER_ACCOUNTING_ROOT_V1_SCHEMA_VERSION
            ),
            genesis_page_sha256=_GENESIS_ACCOUNTING_PAGE_SHA256,
            store=self.store,
            row_kind="ACCOUNTING",
        )
        candidate_address = _address_from_mapping(
            artifact["candidate_inventory_root_cas_address"],
            reason="FRONTIER_CANDIDATE_ROOT_ADDRESS_INVALID",
        )
        root, candidate_rows = _load_paged_root(
            root_address=candidate_address,
            expected_root_key_sha256=cast(str, row["candidate_key_sha256"]),
            page_schema_version=(
                PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_PAGE_V1_SCHEMA_VERSION
            ),
            root_schema_version=(
                PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_ROOT_V1_SCHEMA_VERSION
            ),
            genesis_page_sha256=_GENESIS_CANDIDATE_PAGE_SHA256,
            store=self.store,
            row_kind="CANDIDATE",
        )
        model_binding = cast(dict[str, Any], artifact["model_binding"])
        if any(
            candidate["model_binding_sha256"]
            != model_binding["model_binding_sha256"]
            for candidate in candidate_rows
        ):
            _integrity("FRONTIER_CANDIDATE_ROW_MODEL_BINDING_MISMATCH")
        return root, candidate_rows

    def _write_postcommit(
        self,
        *,
        transaction_id: str,
        accounting_sources: tuple[
            Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]
        ]
        | None,
    ) -> None:
        connection = self._connect_write()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = self._verify_database(connection, require_postcommit=False)
            matches = [row for row in rows if row["transaction_id"] == transaction_id]
            if len(matches) != 1:
                _integrity("FRONTIER_POSTCOMMIT_TRANSACTION_MISSING")
            row = matches[0]
            if row["postcommit_readback_at"] is not None:
                connection.commit()
                return
            if row["event_sequence"] != len(rows):
                _integrity("FRONTIER_POSTCOMMIT_TAIL_REQUIRED")
            observed_at, readback_at = self._next_postcommit_clock(rows, row=row)
            accounting_address: SourcePayloadAddress | None
            if row["event_type"] == "SELECTION":
                if accounting_sources is None:
                    _integrity("FRONTIER_SELECTION_ACCOUNTING_REQUIRED")
                accounting_rows, accounting_counts, accounting_complete = (
                    _build_terminal_accounting(
                        accounting_sources[0],
                        accounting_sources[1],
                        selection_anchored_at=observed_at,
                    )
                )
                root_key = _sha256(
                    {
                        "domain": "profiled-research-canonical-accounting-root-key/v1",
                        "selection_key_sha256": row["selection_key_sha256"],
                        "selection_anchored_at": readback_at,
                        "terminal_cutoff_observed_at": observed_at,
                    }
                )
                accounting_address, root = _publish_paged_root(
                    rows=accounting_rows,
                    root_key_sha256=root_key,
                    page_schema_version=(
                        PROFILED_RESEARCH_CANONICAL_FRONTIER_ACCOUNTING_PAGE_V1_SCHEMA_VERSION
                    ),
                    root_schema_version=(
                        PROFILED_RESEARCH_CANONICAL_FRONTIER_ACCOUNTING_ROOT_V1_SCHEMA_VERSION
                    ),
                    genesis_page_sha256=_GENESIS_ACCOUNTING_PAGE_SHA256,
                    counts=accounting_counts,
                    store=self.store,
                    row_kind="ACCOUNTING",
                )
                if root["total_rows"] != row["commitment_total"]:
                    _integrity("FRONTIER_ACCOUNTING_SOURCE_CARDINALITY_INVALID")
                status = (
                    "READY_FOR_MODEL_CANDIDATE"
                    if accounting_complete
                    else "WAITING_FOR_FORWARD_COHORT_COMPLETENESS"
                )
            else:
                if accounting_sources is not None:
                    _integrity("FRONTIER_CANDIDATE_ACCOUNTING_ARGUMENT_INVALID")
                artifact = validate_profiled_research_canonical_frontier_candidate_v1(
                    cast(str, row["artifact_json"]).encode("ascii")
                )
                self._validate_candidate_evidence(row=row, rows=rows)
                accounting_address = _address_from_mapping(
                    artifact["terminal_accounting_root_cas_address"],
                    reason="FRONTIER_CANDIDATE_ACCOUNTING_ADDRESS_INVALID",
                )
                status = "CANONICAL_MODEL_CANDIDATE_READY"
            post = _postcommit_receipt_contract(
                event_sequence=cast(int, row["event_sequence"]),
                event_type=cast(str, row["event_type"]),
                transaction_id=transaction_id,
                artifact_sha256=cast(str, row["artifact_sha256"]),
                record_chain_sha256=cast(str, row["record_chain_sha256"]),
                append_receipt_sha256=cast(str, row["append_receipt_sha256"]),
                event_status=status,
                accounting_root_address=accounting_address,
                postcommit_observed_at=observed_at,
                postcommit_readback_at=readback_at,
            )
            post_json = _canonical_json(
                post, reason="FRONTIER_POSTCOMMIT_RECEIPT_JSON_INVALID"
            )
            post_sha = hashlib.sha256(post_json.encode("ascii")).hexdigest()
            connection.execute(
                "INSERT INTO frontier_postcommit_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    transaction_id,
                    row["event_sequence"],
                    row["append_receipt_sha256"],
                    row["artifact_sha256"],
                    row["record_chain_sha256"],
                    status,
                    (
                        accounting_address.payload_sha256
                        if accounting_address is not None
                        else None
                    ),
                    post_sha,
                    post_json,
                    observed_at,
                    readback_at,
                ),
            )
            prior = connection.execute(
                """
                SELECT event_sequence, head_anchor_sha256
                FROM frontier_head_anchors
                ORDER BY event_sequence DESC LIMIT 1
                """
            ).fetchone()
            sequence = cast(int, row["event_sequence"])
            if sequence == 1:
                if prior is not None:
                    _integrity("FRONTIER_HEAD_ORDER_INVALID")
                previous_head = _GENESIS_HEAD_ANCHOR_SHA256
            else:
                if prior is None or prior["event_sequence"] != sequence - 1:
                    _integrity("FRONTIER_HEAD_ORDER_INVALID")
                previous_head = cast(str, prior["head_anchor_sha256"])
            head = _head_anchor_contract(
                event_sequence=sequence,
                event_type=cast(str, row["event_type"]),
                transaction_id=transaction_id,
                artifact_sha256=cast(str, row["artifact_sha256"]),
                record_chain_sha256=cast(str, row["record_chain_sha256"]),
                append_receipt_sha256=cast(str, row["append_receipt_sha256"]),
                postcommit_receipt_sha256=post_sha,
                previous_head_anchor_sha256=previous_head,
                anchored_at=readback_at,
            )
            head_json = _canonical_json(
                head, reason="FRONTIER_HEAD_ANCHOR_JSON_INVALID"
            )
            head_address = _expected_address(head_json.encode("ascii"))
            connection.execute(
                "INSERT INTO frontier_head_anchors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sequence,
                    transaction_id,
                    row["event_type"],
                    row["artifact_sha256"],
                    row["record_chain_sha256"],
                    row["append_receipt_sha256"],
                    post_sha,
                    previous_head,
                    head_address.payload_sha256,
                    head_address.payload_byte_count,
                    head_address.relative_path,
                    head_json,
                    readback_at,
                ),
            )
            final_rows = self._verify_database(connection, require_postcommit=True)
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        _fsync_file(self.path)
        _fsync_parent(self.path)
        self._publish_head_catalog(final_rows[-1])

    def _append_candidate_initial(
        self,
        *,
        selection_row: sqlite3.Row,
        accounting_address: SourcePayloadAddress,
        model_binding: dict[str, Any],
        candidate_rows: list[dict[str, Any]],
    ) -> str:
        candidate_key = _sha256(
            {
                "domain": "profiled-research-canonical-candidate-key/v1",
                "selection_key_sha256": selection_row["selection_key_sha256"],
                "model_binding": model_binding,
            }
        )
        candidate_address, candidate_root = _publish_paged_root(
            rows=candidate_rows,
            root_key_sha256=candidate_key,
            page_schema_version=(
                PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_PAGE_V1_SCHEMA_VERSION
            ),
            root_schema_version=(
                PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_ROOT_V1_SCHEMA_VERSION
            ),
            genesis_page_sha256=_GENESIS_CANDIDATE_PAGE_SHA256,
            counts={"calibration_candidate_rows": len(candidate_rows)},
            store=self.store,
            row_kind="CANDIDATE",
        )
        if candidate_root["total_rows"] != len(candidate_rows):
            _integrity("FRONTIER_CANDIDATE_CARDINALITY_INVALID")
        connection = self._connect_write()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = self._verify_database(connection, require_postcommit=True)
            current = next(
                (
                    row
                    for row in rows
                    if row["event_sequence"] == selection_row["event_sequence"]
                ),
                None,
            )
            if (
                current is None
                or current["event_status"] != "READY_FOR_MODEL_CANDIDATE"
                or current["head_anchor_sha256"]
                != selection_row["head_anchor_sha256"]
            ):
                _integrity("FRONTIER_SELECTION_CHANGED_DURING_CANDIDATE_APPEND")
            sequence = len(rows) + 1
            previous_chain = cast(str, rows[-1]["record_chain_sha256"])
            commit_observed, commit_prepared = self._next_commit_clock(rows)
            transaction_id = _sha256(
                {
                    "domain": "profiled-research-canonical-frontier-transaction/v1",
                    "event_sequence": sequence,
                    "stable_key_sha256": candidate_key,
                    "commit_observed_at": commit_observed,
                    "nonce": secrets.token_hex(32),
                }
            )
            selection_binding = {
                "selection_key_sha256": selection_row["selection_key_sha256"],
                "selection_event_sequence": selection_row["event_sequence"],
                "selection_artifact_sha256": selection_row["artifact_sha256"],
                "source_pair_sha256": selection_row["source_pair_sha256"],
                "selection_head_anchor_sha256": selection_row[
                    "head_anchor_sha256"
                ],
                "selection_anchored_at": selection_row["anchored_at"],
                "terminal_cutoff_observed_at": selection_row[
                    "postcommit_observed_at"
                ],
                "terminal_accounting_root_sha256": accounting_address.payload_sha256,
            }
            artifact = _prepare_candidate_artifact(
                candidate_key_sha256=candidate_key,
                selection_binding=selection_binding,
                model_binding=model_binding,
                accounting_root_address=accounting_address,
                candidate_root_address=candidate_address,
                event_binding={
                    "event_sequence": sequence,
                    "event_type": "CANDIDATE",
                    "transaction_id": transaction_id,
                    "previous_event_chain_sha256": previous_chain,
                    "event_commit_observed_at": commit_observed,
                    "event_commit_prepared_at": commit_prepared,
                },
            )
            artifact_bytes = _canonical_bytes(
                artifact, reason="FRONTIER_CANDIDATE_JSON_INVALID"
            )
            artifact_address = _put_exact(self.store, artifact_bytes)
            material = cast(str, artifact["candidate_material_sha256"])
            chain = self._event_chain(
                event_sequence=sequence,
                event_type="CANDIDATE",
                stable_key_sha256=candidate_key,
                artifact_sha256=artifact_address.payload_sha256,
                material_sha256=material,
                previous_event_chain_sha256=previous_chain,
                transaction_id=transaction_id,
                commit_observed_at=commit_observed,
                commit_prepared_at=commit_prepared,
            )
            append = _append_receipt_contract(
                event_sequence=sequence,
                event_type="CANDIDATE",
                transaction_id=transaction_id,
                artifact_sha256=artifact_address.payload_sha256,
                record_chain_sha256=chain,
                total_events=sequence,
                commit_observed_at=commit_observed,
                commit_prepared_at=commit_prepared,
            )
            append_json = _canonical_json(
                append, reason="FRONTIER_APPEND_RECEIPT_JSON_INVALID"
            )
            append_sha = hashlib.sha256(append_json.encode("ascii")).hexdigest()
            connection.execute(
                "INSERT INTO frontier_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sequence,
                    "CANDIDATE",
                    candidate_key,
                    artifact_address.payload_sha256,
                    artifact_address.payload_byte_count,
                    artifact_address.relative_path,
                    artifact_bytes.decode("ascii"),
                    material,
                    previous_chain,
                    chain,
                    transaction_id,
                    commit_observed,
                    commit_prepared,
                ),
            )
            connection.execute(
                "INSERT INTO frontier_candidates VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    sequence,
                    candidate_key,
                    selection_row["event_sequence"],
                    model_binding["model_parameter_fingerprint"],
                    model_binding["model_binding_sha256"],
                    accounting_address.payload_sha256,
                    candidate_address.payload_sha256,
                ),
            )
            connection.execute(
                "INSERT INTO frontier_append_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    transaction_id,
                    sequence,
                    "CANDIDATE",
                    artifact_address.payload_sha256,
                    chain,
                    append_sha,
                    append_json,
                    commit_observed,
                    commit_prepared,
                ),
            )
            self._verify_database(connection, require_postcommit=False)
            connection.commit()
        except sqlite3.IntegrityError as exc:
            if connection.in_transaction:
                connection.rollback()
            raise ProfiledResearchCanonicalFrontierV1ConflictError(
                "FRONTIER_CANDIDATE_CONFLICT"
            ) from exc
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        _fsync_file(self.path)
        _fsync_parent(self.path)
        return transaction_id

    def _all_rows(self, *, require_postcommit: bool) -> list[sqlite3.Row]:
        try:
            if os.stat(self.path, follow_symlinks=False).st_size > _MAX_DATABASE_BYTES:
                _integrity("FRONTIER_DATABASE_RESOURCE_BOUND_EXCEEDED")
        except OSError as exc:
            raise ProfiledResearchCanonicalFrontierV1IntegrityError(
                "FRONTIER_DATABASE_STAT_FAILED"
            ) from exc
        connection = self._connect_readonly()
        try:
            connection.execute("BEGIN")
            rows = self._verify_database(
                connection, require_postcommit=require_postcommit
            )
            connection.commit()
            return rows
        finally:
            connection.close()

    @staticmethod
    def _post_accounting_address(row: sqlite3.Row) -> SourcePayloadAddress:
        post = _parse_exact_object(
            row["postcommit_receipt_json"],
            reason="FRONTIER_POSTCOMMIT_RECEIPT_JSON_INVALID",
        )
        return _address_from_mapping(
            post.get("terminal_accounting_root_cas_address"),
            reason="FRONTIER_ACCOUNTING_ROOT_ADDRESS_INVALID",
        )

    def _recover_pending_tail(
        self,
        *,
        commitments: ProfiledResearchShadowHypothesisCommitmentLedgerV1,
        outcomes: ProfiledResearchFinalizedOutcomeLedgerV1,
    ) -> int:
        rows = self._all_rows(require_postcommit=False)
        pending = [row for row in rows if row["postcommit_readback_at"] is None]
        if not pending:
            return 0
        if len(pending) != 1 or pending[0]["event_sequence"] != len(rows):
            _integrity("FRONTIER_PENDING_TAIL_INVALID")
        row = pending[0]
        if row["event_type"] == "CANDIDATE":
            self._write_postcommit(
                transaction_id=cast(str, row["transaction_id"]),
                accounting_sources=None,
            )
            return 1
        artifact = validate_profiled_research_canonical_frontier_selection_v1(
            cast(str, row["artifact_json"]).encode("ascii")
        )
        source = cast(dict[str, Any], artifact["source_pair_binding"])
        commitment_address = _address_from_mapping(
            source["commitment_snapshot_cas_address"],
            reason="FRONTIER_COMMITMENT_SNAPSHOT_ADDRESS_INVALID",
        )
        outcome_address = _address_from_mapping(
            source["outcome_snapshot_cas_address"],
            reason="FRONTIER_OUTCOME_SNAPSHOT_ADDRESS_INVALID",
        )
        commitment_payload = _get_exact(
            self.store,
            commitment_address,
            reason="FRONTIER_COMMITMENT_SNAPSHOT_REOPEN_FAILED",
        )
        outcome_payload = _get_exact(
            self.store,
            outcome_address,
            reason="FRONTIER_OUTCOME_SNAPSHOT_REOPEN_FAILED",
        )
        commitment_rows = commitments.verified_inventory_snapshot_rows(
            snapshot_artifact=commitment_payload,
            store=self.store,
        )
        outcome_rows = outcomes.verified_inventory_snapshot_rows(
            snapshot_artifact=outcome_payload,
            store=self.store,
        )
        self._write_postcommit(
            transaction_id=cast(str, row["transaction_id"]),
            accounting_sources=(commitment_rows, outcome_rows),
        )
        return 1

    def _selection_result(self, row: sqlite3.Row) -> CanonicalFrontierSelectionResultV1:
        accounting_address = self._post_accounting_address(row)
        root_key = _sha256(
            {
                "domain": "profiled-research-canonical-accounting-root-key/v1",
                "selection_key_sha256": row["selection_key_sha256"],
                "selection_anchored_at": row["anchored_at"],
                "terminal_cutoff_observed_at": row["postcommit_observed_at"],
            }
        )
        root, accounting = _load_paged_root(
            root_address=accounting_address,
            expected_root_key_sha256=root_key,
            page_schema_version=(
                PROFILED_RESEARCH_CANONICAL_FRONTIER_ACCOUNTING_PAGE_V1_SCHEMA_VERSION
            ),
            root_schema_version=(
                PROFILED_RESEARCH_CANONICAL_FRONTIER_ACCOUNTING_ROOT_V1_SCHEMA_VERSION
            ),
            genesis_page_sha256=_GENESIS_ACCOUNTING_PAGE_SHA256,
            store=self.store,
            row_kind="ACCOUNTING",
        )
        counts = cast(dict[str, int], root["counts"])
        public = {
            "selection_key_sha256": row["selection_key_sha256"],
            "source_pair_sha256": row["source_pair_sha256"],
            "selection_event_sequence": row["event_sequence"],
            "selection_artifact_sha256": row["artifact_sha256"],
            "selection_anchored_at": row["anchored_at"],
            "terminal_cutoff_observed_at": row["postcommit_observed_at"],
            "terminal_accounting_root_sha256": accounting_address.payload_sha256,
            "terminal_accounting_complete": row["event_status"]
            == "READY_FOR_MODEL_CANDIDATE",
            "terminal_commitment_count": len(accounting),
            "due_missing_outcome_count": counts["due_outcome_missing"],
        }
        return CanonicalFrontierSelectionResultV1(
            **public,
            _ledger=self,
            _factory_seal=self._result_seal("SELECTION", public),
            _construction_token=_RESULT_TOKEN,
        )

    def _candidate_result(self, row: sqlite3.Row) -> CanonicalFrontierCandidateResultV1:
        artifact = validate_profiled_research_canonical_frontier_candidate_v1(
            cast(str, row["artifact_json"]).encode("ascii")
        )
        candidate_address = _address_from_mapping(
            artifact["candidate_inventory_root_cas_address"],
            reason="FRONTIER_CANDIDATE_ROOT_ADDRESS_INVALID",
        )
        root, candidate_rows = _load_paged_root(
            root_address=candidate_address,
            expected_root_key_sha256=cast(str, row["candidate_key_sha256"]),
            page_schema_version=(
                PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_PAGE_V1_SCHEMA_VERSION
            ),
            root_schema_version=(
                PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_ROOT_V1_SCHEMA_VERSION
            ),
            genesis_page_sha256=_GENESIS_CANDIDATE_PAGE_SHA256,
            store=self.store,
            row_kind="CANDIDATE",
        )
        if root["total_rows"] != len(candidate_rows):
            _integrity("FRONTIER_CANDIDATE_ROOT_CARDINALITY_INVALID")
        selection = cast(dict[str, Any], artifact["selection_binding"])
        public = {
            "candidate_key_sha256": row["candidate_key_sha256"],
            "selection_key_sha256": selection["selection_key_sha256"],
            "candidate_event_sequence": row["event_sequence"],
            "candidate_artifact_sha256": row["artifact_sha256"],
            "candidate_head_anchor_sha256": row["head_anchor_sha256"],
            "candidate_anchored_at": row["anchored_at"],
            "model_parameter_fingerprint": row["model_parameter_fingerprint"],
            "calibration_candidate_row_count": len(candidate_rows),
        }
        return CanonicalFrontierCandidateResultV1(
            **public,
            _ledger=self,
            _factory_seal=self._result_seal("CANDIDATE", public),
            _construction_token=_RESULT_TOKEN,
        )

    def _verify_completed_cas_closure(
        self,
        *,
        rows: Sequence[sqlite3.Row],
        commitments: ProfiledResearchShadowHypothesisCommitmentLedgerV1,
        outcomes: ProfiledResearchFinalizedOutcomeLedgerV1,
    ) -> None:
        for row in rows:
            event_address = SourcePayloadAddress(
                schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
                payload_sha256=cast(str, row["artifact_sha256"]),
                payload_byte_count=cast(int, row["artifact_byte_count"]),
                relative_path=cast(str, row["artifact_relative_path"]),
            )
            event_payload = _get_exact(
                self.store,
                event_address,
                reason="FRONTIER_EVENT_ARTIFACT_REOPEN_FAILED",
            )
            if event_payload != cast(str, row["artifact_json"]).encode("ascii"):
                _integrity("FRONTIER_EVENT_ARTIFACT_CAS_MISMATCH")
            if row["event_type"] == "CANDIDATE":
                self._validate_candidate_evidence(row=row, rows=rows)
                continue
            artifact = validate_profiled_research_canonical_frontier_selection_v1(
                event_payload
            )
            source = cast(dict[str, Any], artifact["source_pair_binding"])
            commitment_address = _address_from_mapping(
                source["commitment_snapshot_cas_address"],
                reason="FRONTIER_COMMITMENT_SNAPSHOT_ADDRESS_INVALID",
            )
            outcome_address = _address_from_mapping(
                source["outcome_snapshot_cas_address"],
                reason="FRONTIER_OUTCOME_SNAPSHOT_ADDRESS_INVALID",
            )
            commitment_inventory = commitments.verified_inventory_snapshot_rows(
                snapshot_artifact=_get_exact(
                    self.store,
                    commitment_address,
                    reason="FRONTIER_COMMITMENT_SNAPSHOT_REOPEN_FAILED",
                ),
                store=self.store,
            )
            outcome_inventory = outcomes.verified_inventory_snapshot_rows(
                snapshot_artifact=_get_exact(
                    self.store,
                    outcome_address,
                    reason="FRONTIER_OUTCOME_SNAPSHOT_REOPEN_FAILED",
                ),
                store=self.store,
            )
            if (
                len(commitment_inventory) != row["commitment_total"]
                or len(outcome_inventory) != row["outcome_total"]
            ):
                _integrity("FRONTIER_SOURCE_SNAPSHOT_CARDINALITY_MISMATCH")

    def _result_seal(self, kind: str, public: Mapping[str, Any]) -> str:
        return hmac.new(
            _RESULT_SEAL_KEY,
            _canonical_bytes(
                {
                    "domain": "profiled-research-canonical-frontier-result/v1",
                    "kind": kind,
                    "public": dict(public),
                    "ledger_path": str(self.path),
                    "store_root_path": str(self.store.root_path),
                    "ledger_process_identity": id(self),
                    "store_process_identity": id(self.store),
                },
                reason="FRONTIER_RESULT_SEAL_INVALID",
            ),
            hashlib.sha256,
        ).hexdigest()

    def _validate_selection_result(
        self, result: CanonicalFrontierSelectionResultV1
    ) -> None:
        if (
            type(result) is not CanonicalFrontierSelectionResultV1
            or result._construction_token is not _RESULT_TOKEN  # noqa: SLF001
            or result._ledger is not self  # noqa: SLF001
        ):
            _integrity("FRONTIER_SELECTION_RESULT_FACTORY_REQUIRED")
        public = {
            name: getattr(result, name)
            for name in (
                "selection_key_sha256",
                "source_pair_sha256",
                "selection_event_sequence",
                "selection_artifact_sha256",
                "selection_anchored_at",
                "terminal_cutoff_observed_at",
                "terminal_accounting_root_sha256",
                "terminal_accounting_complete",
                "terminal_commitment_count",
                "due_missing_outcome_count",
            )
        }
        if not hmac.compare_digest(
            result._factory_seal, self._result_seal("SELECTION", public)  # noqa: SLF001
        ):
            _integrity("FRONTIER_SELECTION_RESULT_SEAL_INVALID")
        rows = self._all_rows(require_postcommit=True)
        matches = [
            row
            for row in rows
            if row["event_sequence"] == result.selection_event_sequence
            and row["selection_key_sha256"] == result.selection_key_sha256
        ]
        if len(matches) != 1:
            _integrity("FRONTIER_SELECTION_RESULT_REOPEN_FAILED")
        reopened = self._selection_result(matches[0])
        if any(getattr(reopened, name) != value for name, value in public.items()):
            _integrity("FRONTIER_SELECTION_RESULT_REOPEN_MISMATCH")

    def _validate_candidate_result(
        self, result: CanonicalFrontierCandidateResultV1
    ) -> None:
        if (
            type(result) is not CanonicalFrontierCandidateResultV1
            or result._construction_token is not _RESULT_TOKEN  # noqa: SLF001
            or result._ledger is not self  # noqa: SLF001
        ):
            _integrity("FRONTIER_CANDIDATE_RESULT_FACTORY_REQUIRED")
        public = {
            name: getattr(result, name)
            for name in (
                "candidate_key_sha256",
                "selection_key_sha256",
                "candidate_event_sequence",
                "candidate_artifact_sha256",
                "candidate_head_anchor_sha256",
                "candidate_anchored_at",
                "model_parameter_fingerprint",
                "calibration_candidate_row_count",
            )
        }
        if not hmac.compare_digest(
            result._factory_seal, self._result_seal("CANDIDATE", public)  # noqa: SLF001
        ):
            _integrity("FRONTIER_CANDIDATE_RESULT_SEAL_INVALID")
        rows = self._all_rows(require_postcommit=True)
        matches = [
            row
            for row in rows
            if row["event_sequence"] == result.candidate_event_sequence
            and row["candidate_key_sha256"] == result.candidate_key_sha256
        ]
        if len(matches) != 1:
            _integrity("FRONTIER_CANDIDATE_RESULT_REOPEN_FAILED")
        reopened = self._candidate_result(matches[0])
        if any(getattr(reopened, name) != value for name, value in public.items()):
            _integrity("FRONTIER_CANDIDATE_RESULT_REOPEN_MISMATCH")

    def seal_canonical_candidate(
        self,
        *,
        commitment_ledger: object,
        outcome_ledger: object,
        model_parameter_fingerprint: object,
    ) -> CanonicalFrontierSelectionResultV1 | CanonicalFrontierCandidateResultV1:
        if type(commitment_ledger) is not ProfiledResearchShadowHypothesisCommitmentLedgerV1:
            _validation("FRONTIER_EXACT_COMMITMENT_LEDGER_REQUIRED")
        if type(outcome_ledger) is not ProfiledResearchFinalizedOutcomeLedgerV1:
            _validation("FRONTIER_EXACT_OUTCOME_LEDGER_REQUIRED")
        if _strict_sha256(model_parameter_fingerprint) is None:
            _validation("FRONTIER_MODEL_FINGERPRINT_INVALID")
        commitments = cast(
            ProfiledResearchShadowHypothesisCommitmentLedgerV1, commitment_ledger
        )
        outcomes = cast(ProfiledResearchFinalizedOutcomeLedgerV1, outcome_ledger)
        if len({str(self.path), str(commitments.path), str(outcomes.path)}) != 3:
            _validation("FRONTIER_DISTINCT_LEDGER_PATHS_REQUIRED")
        with _exclusive_writer_lock(self.path):
            self._ensure_initialized()
            initial = self._all_rows(require_postcommit=False)
            self._repair_and_verify_head_catalog(initial)
            self._recover_pending_tail(commitments=commitments, outcomes=outcomes)
            recovered = self._all_rows(require_postcommit=True)
            self._repair_and_verify_head_catalog(recovered)
            with ExitStack() as stack:
                ledgers: list[
                    ProfiledResearchShadowHypothesisCommitmentLedgerV1
                    | ProfiledResearchFinalizedOutcomeLedgerV1
                ] = [commitments, outcomes]
                for source in sorted(ledgers, key=lambda item: str(item.path)):
                    stack.enter_context(source.hold_inventory_snapshot_lease())
                commitment_snapshot = commitments.capture_inventory_snapshot(
                    store=self.store
                )
                outcome_snapshot = outcomes.capture_inventory_snapshot(store=self.store)
                commitment_rows = commitment_snapshot.ordered_inventory
                outcome_rows = outcome_snapshot.ordered_inventory
            if (
                len(commitment_rows)
                != commitment_snapshot.total_committed_hypotheses
                or len(outcome_rows) != outcome_snapshot.total_finalized_outcomes
            ):
                _integrity("FRONTIER_SOURCE_INVENTORY_CARDINALITY_INVALID")
            source_pair = _source_pair_binding(commitment_snapshot, outcome_snapshot)
            rows = self._all_rows(require_postcommit=False)
            selection_matches = [
                row
                for row in rows
                if row["source_pair_sha256"] == source_pair["source_pair_sha256"]
            ]
            if len(selection_matches) > 1:
                _integrity("FRONTIER_DUPLICATE_SOURCE_PAIR_SELECTION")
            if not selection_matches:
                transaction_id = self._append_selection_initial(
                    source_pair=source_pair,
                    commitment_snapshot=commitment_snapshot,
                    outcome_snapshot=outcome_snapshot,
                )
            else:
                transaction_id = cast(str, selection_matches[0]["transaction_id"])
            rows = self._all_rows(require_postcommit=False)
            selection_row = next(
                row for row in rows if row["transaction_id"] == transaction_id
            )
            if selection_row["postcommit_readback_at"] is None:
                self._write_postcommit(
                    transaction_id=transaction_id,
                    accounting_sources=(commitment_rows, outcome_rows),
                )
            rows = self._all_rows(require_postcommit=True)
            self._repair_and_verify_head_catalog(rows)
            selection_row = next(
                row for row in rows if row["transaction_id"] == transaction_id
            )
            selection_result = self._selection_result(selection_row)
            if not selection_result.terminal_accounting_complete:
                return selection_result
            exact_fingerprint = cast(str, model_parameter_fingerprint)
            if not any(
                row.get("model_parameter_fingerprint") == exact_fingerprint
                for row in outcome_rows
            ):
                if any(
                    row.get("model_parameter_fingerprint") == exact_fingerprint
                    for row in commitment_rows
                ):
                    return selection_result
                _validation("FRONTIER_MODEL_NOT_PRESENT_IN_SOURCE_SELECTION")
            model_binding = _model_binding_for_fingerprint(
                outcome_rows,
                model_parameter_fingerprint=exact_fingerprint,
            )
            candidate_rows = _candidate_rows_for_model(
                outcome_rows,
                model_parameter_fingerprint=exact_fingerprint,
            )
            candidate_key = _sha256(
                {
                    "domain": "profiled-research-canonical-candidate-key/v1",
                    "selection_key_sha256": selection_row["selection_key_sha256"],
                    "model_binding": model_binding,
                }
            )
            candidate_matches = [
                row for row in rows if row["candidate_key_sha256"] == candidate_key
            ]
            if len(candidate_matches) > 1:
                _integrity("FRONTIER_DUPLICATE_CANDIDATE_KEY")
            if not candidate_matches:
                accounting_address = self._post_accounting_address(selection_row)
                candidate_transaction = self._append_candidate_initial(
                    selection_row=selection_row,
                    accounting_address=accounting_address,
                    model_binding=model_binding,
                    candidate_rows=candidate_rows,
                )
            else:
                candidate_transaction = cast(
                    str, candidate_matches[0]["transaction_id"]
                )
            rows = self._all_rows(require_postcommit=False)
            candidate_row = next(
                row for row in rows if row["transaction_id"] == candidate_transaction
            )
            if candidate_row["postcommit_readback_at"] is None:
                self._write_postcommit(
                    transaction_id=candidate_transaction,
                    accounting_sources=None,
                )
            rows = self._all_rows(require_postcommit=True)
            self._repair_and_verify_head_catalog(rows)
            candidate_row = next(
                row for row in rows if row["transaction_id"] == candidate_transaction
            )
            return self._candidate_result(candidate_row)

    def verify_integrity(
        self,
        *,
        commitment_ledger: object,
        outcome_ledger: object,
    ) -> dict[str, int | bool | str]:
        if type(commitment_ledger) is not ProfiledResearchShadowHypothesisCommitmentLedgerV1:
            _validation("FRONTIER_EXACT_COMMITMENT_LEDGER_REQUIRED")
        if type(outcome_ledger) is not ProfiledResearchFinalizedOutcomeLedgerV1:
            _validation("FRONTIER_EXACT_OUTCOME_LEDGER_REQUIRED")
        commitments = cast(
            ProfiledResearchShadowHypothesisCommitmentLedgerV1, commitment_ledger
        )
        outcomes = cast(ProfiledResearchFinalizedOutcomeLedgerV1, outcome_ledger)
        with _exclusive_writer_lock(self.path):
            self._ensure_initialized()
            rows = self._all_rows(require_postcommit=True)
            self._verify_head_catalog(rows)
            self._verify_completed_cas_closure(
                rows=rows,
                commitments=commitments,
                outcomes=outcomes,
            )
            selections = [row for row in rows if row["event_type"] == "SELECTION"]
            candidates = [row for row in rows if row["event_type"] == "CANDIDATE"]
            for row in selections:
                self._selection_result(row)
            for row in candidates:
                self._candidate_result(row)
            return {
                "status": "CANONICAL_FRONTIER_INTEGRITY_VERIFIED",
                "events_verified": len(rows),
                "selections_verified": len(selections),
                "candidates_verified": len(candidates),
                "head_anchors_verified": len(rows),
                "runtime_wired": False,
            }
