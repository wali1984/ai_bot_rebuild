"""Unwired v4 ledger for incomplete native feature-artifact publication evidence.

This module is the deliberately narrow P0-D boundary after two existing,
independently fail-closed artifacts:

* :class:`TrainerSourceProvenanceLedgerV4` (P0-C) proves one atomic canonical
  closed-OHLCV suffix and its ordered source-read receipts; and
* :class:`FeatureSnapshotCasArtifact` proves the exact derived native snapshot
  bytes and its artifact binding were placed in an immutable CAS.

P0-D freshly reads the P0-C ledger, locates the caller-selected exact sequence
and entry hash, freshly verifies both P0-B-derived source evidence (through the
P0-C read) and both feature-artifact CAS objects, and then pins the artifact
bytes in a private ledger-owned immutable CAS.  It binds the artifact's latest
candle to the last row of the complete P0-C suffix and freezes an ordered
feature vector, masks, requirement classes, source-label placeholders, and
per-field receipt roots.

The current native snapshot ABI does *not* contain immutable per-field source
receipts, per-field truthful ``available_at`` clocks, producer code/config/
transform identities, or a truthful post-publication completion clock.  This
ledger therefore has exactly one evidence classification:
``SOURCE_SCOPE_INCOMPLETE_ARTIFACT_PUBLICATION``.  All publication, admission,
prediction, paper-trading, and live-execution properties are invariantly
false.  A durable append is audit evidence only; it is not a publication
receipt and must never be consumed as one.

Entries are canonical JSONL, SHA-256 chained, fsynced, and committed by a
separately fsynced head that binds the exact ledger prefix.  All filesystem
walks retain directory descriptors, refuse symlinks/hardlinks, require private
owner-only roots/files, and verify inode identity before and after I/O.  One
complete entry left ahead of the head by a crash can only be recovered by an
exact replay of the same authenticated P0-C/artifact material.

Nothing imports this module from an active feature worker, trainer, predictor,
paper loop, or live execution path.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import stat
import struct
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, cast

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_ABI_SCHEMA_VERSION,
    FEATURE_REQUIREMENT_POLICY_ID,
    MAX_FEATURE_SLOTS,
    FeatureSnapshotValidationError,
    feature_abi_contract,
    feature_requirement_classes_for_names,
)
from v2.backend.app.services.native_trainer.feature_snapshot_cas_publication import (
    CAS_ARTIFACT_BINDING_SCHEMA_VERSION,
    CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION,
    MAX_CANONICAL_FEATURE_SNAPSHOT_BYTES,
    NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION,
    NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
    FeatureSnapshotCasArtifact,
    FeatureSnapshotPublicationError,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FEATURE_SPEC,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    SOURCE_PAYLOAD_STORE_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadIntegrityError,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_NAMESPACE,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION,
    TrainerSourceProvenanceLedgerEntryV4,
    TrainerSourceProvenanceLedgerV4,
    TrainerSourceProvenanceLedgerV4Error,
)

FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION = (
    "feature_snapshot_publication_ledger_entry_v4"
)
FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_SCHEMA_VERSION = (
    "feature_snapshot_publication_ledger_head_v4"
)
FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_NAMESPACE = "trainer-feature-snapshot-publication-v4"
FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_EVIDENCE_CLASSIFICATION = (
    "SOURCE_SCOPE_INCOMPLETE_ARTIFACT_PUBLICATION"
)
FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_DOWNSTREAM_STATUS = (
    "AUDIT_ARTIFACT_ONLY_NO_PUBLICATION_RECEIPT_ADMISSION_OR_EXECUTION_AUTHORIZATION"
)
FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME = "feature_snapshot_publication_v4.jsonl"
FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_FILENAME = "feature_snapshot_publication_v4.head.json"
FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_LOCK_FILENAME = ".feature_snapshot_publication_v4.lock"
FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_SCHEMA_VERSION = (
    "feature_snapshot_publication_immutable_cas_v4"
)
FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_NAMESPACE = "trainer-feature-snapshot-publication-v4"
FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_ROOT_RELATIVE_PATH = (
    "feature_snapshot_publication_v4_cas"
)
FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_GENESIS_SHA256 = hashlib.sha256(
    b"feature_snapshot_publication_ledger_v4:genesis"
).hexdigest()

FEATURE_VECTOR_BINDING_SCHEMA_VERSION = "incomplete_feature_vector_binding_v4"
FEATURE_DERIVATION_BINDING_SCHEMA_VERSION = "incomplete_feature_derivation_binding_v4"
FEATURE_TEMPORAL_BINDING_SCHEMA_VERSION = "incomplete_feature_temporal_binding_v4"
FEATURE_SOURCE_PROVENANCE_BINDING_SCHEMA_VERSION = "p0c_source_provenance_binding_v4"
FEATURE_ARTIFACT_BINDING_SCHEMA_VERSION = "p0d_feature_artifact_binding_v4"
FEATURE_PUBLICATION_IDENTITY_SCHEMA_VERSION = "feature_publication_identity_v4"

UNRESOLVED_SOURCE_LABEL = "UNRESOLVED_NO_PER_FIELD_RECEIPT"
NATIVE_MODEL_ABI_ORIGIN = "TENSOR_BUILDER_FEATURE_SPEC_CODE_ORDER_WITH_EXACT_DECLARATIONS"
INCOMPLETE_FALLBACK_ABI_ORIGIN = "INCOMPLETE_NON_MODEL_ABI_SORTED_PRESENT_FEATURE_NAMES"
SOURCE_SCOPE_INCOMPLETENESS_REASONS = (
    "PER_FIELD_SOURCE_READ_RECEIPTS_ABSENT",
    "PER_FIELD_AVAILABLE_AT_ABSENT",
    "PRODUCER_CODE_IDENTITY_ABSENT",
    "PRODUCER_CONFIGURATION_IDENTITY_ABSENT",
    "FEATURE_TRANSFORM_IDENTITY_ABSENT",
    "TRUTHFUL_PUBLICATION_COMPLETION_CLOCK_ABSENT",
)

# Resource-integrity ceilings only.  These never select a market, feature,
# training row, leverage value, or risk outcome.
MAX_LEDGER_ENTRY_BYTES = 16 * 1024 * 1024
MAX_LEDGER_BYTES = 512 * 1024 * 1024
MAX_LEDGER_ENTRIES = 1_000_000
MAX_OPAQUE_ID_BYTES = 256
MAX_HEAD_BYTES = 64 * 1024

_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_MAX_PATH_COMPONENTS = 128
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$", re.ASCII)
_FEATURE_SNAPSHOT_ID_RE = re.compile(r"^v2_fsnap_[0-9a-f]{64}$", re.ASCII)
_ARTIFACT_RECORD_ID_RE = re.compile(r"^feature_snapshot_cas_artifact_v1_[0-9a-f]{64}$", re.ASCII)
_CONSTRUCTION_TOKEN = object()

_DOWNSTREAM_FLAG_FIELDS = (
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "source_scope_complete",
    "per_field_receipts_complete",
    "truthful_completion_clock_present",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)
_ENTRY_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "ledger_namespace",
        "ledger_sequence",
        "previous_entry_sha256",
        "publication_identity_sha256",
        "publication_replay_identity_sha256",
        "ledger_recorded_at",
        "ledger_owned_store",
        "source_provenance_binding",
        "feature_artifact_binding",
        "feature_vector_binding",
        "derivation_binding",
        "temporal_binding",
        "source_scope_incompleteness_reasons",
        *_DOWNSTREAM_FLAG_FIELDS,
        "entry_sha256",
    }
)
_HEAD_FIELDS = frozenset(
    {
        "schema_version",
        "ledger_schema_version",
        "ledger_filename",
        "ledger_sequence",
        "ledger_byte_count",
        "ledger_sha256",
        "entry_sha256",
        "head_sha256",
    }
)
_STORE_FIELDS = frozenset(
    {
        "schema_version",
        "namespace",
        "root_relative_path",
        "underlying_store_schema_version",
        "address_schema_version",
        "store_binding_sha256",
    }
)
_ADDRESS_FIELDS = frozenset(
    {"schema_version", "payload_sha256", "payload_byte_count", "relative_path"}
)
_SOURCE_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "source_ledger_schema_version",
        "source_ledger_namespace",
        "source_ledger_root",
        "source_ledger_root_sha256",
        "source_ledger_sequence",
        "source_ledger_entry_sha256",
        "source_ledger_entry_json_sha256",
        "source_replay_identity_sha256",
        "source_cycle_identity_sha256",
        "trainer_run_id",
        "trainer_cycle_id",
        "source_ledger_recorded_at",
        "source_key",
        "source_key_sha256",
        "source_key_version",
        "atomic_batch_id",
        "atomic_batch_material_sha256",
        "full_source_payload_cas_address",
        "suffix_manifest_sha256",
        "suffix_manifest_cas_address",
        "suffix_digest_sha256",
        "selected_row_count",
        "selected_candle_ids",
        "ordered_source_read_receipt_sha256s",
        "ordered_exact_row_payload_sha256s",
        "latest_candle",
        "complete_suffix_binding_sha256",
        "source_scope_binding_sha256",
    }
)
_LATEST_CANDLE_FIELDS = frozenset(
    {
        "selected_ordinal",
        "source_index",
        "candle_id",
        "candle_open_time_ms",
        "candle_close_time_ms",
        "producer_event_time_ms",
        "ingested_at_ms",
        "available_at_ms",
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
        "source",
        "source_sequence_id",
        "raw_payload_hash",
        "is_backfilled",
        "source_read_receipt_sha256",
        "exact_payload_sha256",
        "source_payload_cas_address",
    }
)
_ARTIFACT_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "source_artifact_binding_schema_version",
        "native_snapshot_schema_version",
        "artifact_serialization_schema_version",
        "artifact_record_id",
        "artifact_binding_sha256",
        "artifact_binding_json_sha256",
        "artifact_binding_json_byte_count",
        "feature_snapshot_id",
        "producer_worker_id",
        "symbol",
        "timeframe",
        "candle_open_time",
        "candle_close_time",
        "source_event_time",
        "source_ingested_at",
        "source_available_at",
        "feature_cutoff",
        "generated_at",
        "source",
        "is_backfilled",
        "source_sequence_id",
        "raw_payload_hash",
        "artifact_serialization_sha256",
        "artifact_serialization_byte_count",
        "source_artifact_store_root",
        "source_artifact_store_root_sha256",
        "source_artifact_content_cas_address",
        "source_artifact_binding_cas_address",
        "ledger_owned_artifact_content_cas_address",
        "ledger_owned_artifact_binding_cas_address",
        "artifact_binding_projection_sha256",
    }
)
_VECTOR_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "abi_origin",
        "feature_requirement_policy_id",
        "feature_count",
        "ordered_feature_names",
        "ordered_feature_values",
        "missing_mask",
        "stale_mask",
        "source_availability_mask",
        "ordered_feature_requirement_classes",
        "ordered_resolved_source_labels",
        "per_field_root_receipt_sha256s",
        "per_field_available_at",
        "feature_abi",
        "feature_abi_sha256",
        "ordered_values_sha256",
        "mask_vectors_sha256",
        "per_field_bindings_sha256",
        "native_snapshot_features_sha256",
        "native_snapshot_declared_missing_flags_sha256",
        "feature_source_evidence_complete",
        "feature_available_at_complete",
        "vector_binding_sha256",
    }
)
_DERIVATION_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "producer_worker_id",
        "feature_abi_schema_version",
        "feature_abi_sha256",
        "producer_code_sha256",
        "producer_configuration_sha256",
        "feature_transform_sha256",
        "derivation_identity_complete",
        "derivation_binding_sha256",
    }
)
_TEMPORAL_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "candle_open_time",
        "candle_close_time",
        "source_event_time",
        "source_ingested_at",
        "source_available_at",
        "feature_cutoff",
        "snapshot_generated_at",
        "source_consumer_observed_at",
        "source_ledger_recorded_at",
        "feature_available_at",
        "publication_completed_at",
        "decision_time",
        "execution_time",
        "available_at_feature_cutoff_decision_order_applicable",
        "available_at_feature_cutoff_decision_order_verified",
        "pit_order_status",
        "ledger_recorded_at",
        "temporal_binding_sha256",
    }
)


class FeatureSnapshotPublicationLedgerV4Error(RuntimeError):
    """Base fail-closed P0-D ledger error."""


class FeatureSnapshotPublicationLedgerV4ValidationError(FeatureSnapshotPublicationLedgerV4Error):
    """Caller input or upstream artifact selection is invalid."""


class FeatureSnapshotPublicationLedgerV4IntegrityError(FeatureSnapshotPublicationLedgerV4Error):
    """Persisted bytes, hash chain, CAS, or upstream binding is invalid."""


class FeatureSnapshotPublicationLedgerV4ConflictError(FeatureSnapshotPublicationLedgerV4Error):
    """An exact P0-C source entry was reused with different artifact material."""


class FeatureSnapshotPublicationLedgerV4DurabilityError(FeatureSnapshotPublicationLedgerV4Error):
    """Append, fsync, head publication, or durable readback failed."""


@dataclass(frozen=True, slots=True)
class FeatureSnapshotPublicationLedgerEntryV4:
    """Factory-authenticated entry backed by fresh source and CAS checks."""

    schema_version: str
    ledger_sequence: int
    previous_entry_sha256: str
    publication_identity_sha256: str
    publication_replay_identity_sha256: str
    source_ledger_sequence: int
    source_ledger_entry_sha256: str
    artifact_record_id: str
    feature_snapshot_id: str
    entry_sha256: str
    entry_json: str = field(repr=False)
    _source_ledger: TrainerSourceProvenanceLedgerV4 = field(
        repr=False,
        compare=False,
    )
    _owned_store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _expected_owned_store_root: Path = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)
    incomplete_artifact_publication_ledger_recorded: bool = field(default=True, init=False)
    durable_postcommit_readback_verified: bool = field(default=True, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    source_scope_complete: bool = field(default=False, init=False)
    per_field_receipts_complete: bool = field(default=False, init=False)
    truthful_completion_clock_present: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _integrity_error("feature_publication_v4_factory_construction_required")
        record = _parse_entry_line(self.entry_json.encode("ascii", errors="strict"))
        _verify_source_binding(record, self._source_ledger)
        _verify_record_owned_cas(
            record,
            self._owned_store,
            expected_store_root=self._expected_owned_store_root,
        )
        source_binding = cast(dict[str, Any], record["source_provenance_binding"])
        artifact_binding = cast(dict[str, Any], record["feature_artifact_binding"])
        if (
            self.schema_version != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION
            or self.ledger_sequence != record["ledger_sequence"]
            or self.previous_entry_sha256 != record["previous_entry_sha256"]
            or self.publication_identity_sha256 != record["publication_identity_sha256"]
            or self.publication_replay_identity_sha256
            != record["publication_replay_identity_sha256"]
            or self.source_ledger_sequence != source_binding["source_ledger_sequence"]
            or self.source_ledger_entry_sha256 != source_binding["source_ledger_entry_sha256"]
            or self.artifact_record_id != artifact_binding["artifact_record_id"]
            or self.feature_snapshot_id != artifact_binding["feature_snapshot_id"]
            or self.entry_sha256 != record["entry_sha256"]
            or any(getattr(self, name) is not False for name in _DOWNSTREAM_FLAG_FIELDS)
        ):
            _integrity_error("feature_publication_v4_entry_artifact_binding_invalid")

    @property
    def record(self) -> dict[str, Any]:
        """Return a fresh mapping only after rechecking P0-C and owned CAS."""

        record = _parse_entry_line(self.entry_json.encode("ascii", errors="strict"))
        _verify_source_binding(record, self._source_ledger)
        _verify_record_owned_cas(
            record,
            self._owned_store,
            expected_store_root=self._expected_owned_store_root,
        )
        return record


@dataclass(frozen=True, slots=True)
class FeatureSnapshotPublicationAppendResultV4:
    """Factory-authenticated durable append/replay result; never an admission receipt."""

    entry: FeatureSnapshotPublicationLedgerEntryV4
    disposition: str
    _construction_token: object = field(repr=False, compare=False)
    incomplete_artifact_publication_ledger_recorded: bool = field(default=True, init=False)
    durable_postcommit_readback_verified: bool = field(default=True, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    source_scope_complete: bool = field(default=False, init=False)
    per_field_receipts_complete: bool = field(default=False, init=False)
    truthful_completion_clock_present: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _CONSTRUCTION_TOKEN
            or type(self.entry) is not FeatureSnapshotPublicationLedgerEntryV4
            or self.disposition
            not in {"APPENDED", "EXACT_REPLAY", "RECOVERED_EXACT_PENDING_APPEND"}
            or any(getattr(self, name) is not False for name in _DOWNSTREAM_FLAG_FIELDS)
        ):
            _integrity_error("feature_publication_v4_result_factory_binding_invalid")
        # Force all upstream/CAS checks at result construction, not only when a
        # caller later asks for ``entry.record``.
        _verified_record = self.entry.record


@dataclass(frozen=True, slots=True)
class _LedgerState:
    raw_bytes: bytes
    records: tuple[dict[str, Any], ...]
    line_end_offsets: tuple[int, ...]
    committed_count: int

    @property
    def pending_record(self) -> dict[str, Any] | None:
        if len(self.records) == self.committed_count:
            return None
        return self.records[-1]


def _validation_error(reason: str) -> NoReturn:
    raise FeatureSnapshotPublicationLedgerV4ValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise FeatureSnapshotPublicationLedgerV4IntegrityError(reason) from None


def _conflict_error(reason: str) -> NoReturn:
    raise FeatureSnapshotPublicationLedgerV4ConflictError(reason) from None


def _durability_error(reason: str, *, cause: BaseException | None = None) -> NoReturn:
    error = FeatureSnapshotPublicationLedgerV4DurabilityError(reason)
    if cause is None:
        raise error from None
    raise error from cause


def _canonical_json(value: object, *, max_bytes: int = MAX_LEDGER_ENTRY_BYTES) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        raw = encoded.encode("ascii", errors="strict")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeEncodeError):
        _integrity_error("feature_publication_v4_material_not_strict_json")
    if not raw or len(raw) > max_bytes:
        _integrity_error("feature_publication_v4_material_size_invalid")
    return encoded


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable_sha256(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("ascii"))


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _integrity_error("feature_publication_v4_duplicate_json_key")
        result[key] = value
    return result


def _parse_json_object(raw: bytes, *, max_bytes: int) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > max_bytes:
        _integrity_error("feature_publication_v4_json_size_invalid")
    try:
        text = raw.decode("ascii", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=lambda _value: _integrity_error(
                "feature_publication_v4_json_constant_forbidden"
            ),
        )
    except FeatureSnapshotPublicationLedgerV4Error:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, TypeError, ValueError):
        _integrity_error("feature_publication_v4_json_invalid")
    if type(parsed) is not dict:
        _integrity_error("feature_publication_v4_json_object_required")
    typed = cast(dict[str, Any], parsed)
    if _canonical_json(typed, max_bytes=max_bytes).encode("ascii") != raw:
        _integrity_error("feature_publication_v4_json_not_canonical")
    return typed


def _exact_object(
    value: object,
    fields: frozenset[str],
    *,
    reason: str,
) -> dict[str, Any]:
    if type(value) is not dict or frozenset(cast(dict[object, object], value)) != fields:
        _integrity_error(reason)
    return cast(dict[str, Any], value)


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _required_sha256(value: object, *, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _integrity_error(reason)
    return value


def _required_label(value: object, *, reason: str) -> str:
    if (
        type(value) is not str
        or len(value.encode("utf-8")) > MAX_OPAQUE_ID_BYTES
        or _LABEL_RE.fullmatch(value) is None
    ):
        _integrity_error(reason)
    return value


def _parse_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _integrity_error(reason)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        _integrity_error(reason)
    if parsed < _EPOCH or parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        _integrity_error(reason)
    return parsed


def _ms_to_clock(value: object) -> str:
    if type(value) is not int or value < 0:
        _integrity_error("feature_publication_v4_millisecond_clock_invalid")
    try:
        seconds, milliseconds = divmod(value, 1_000)
        resolved = datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=milliseconds * 1_000)
    except (OverflowError, OSError, ValueError):
        _integrity_error("feature_publication_v4_millisecond_clock_invalid")
    return resolved.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _sample_ledger_clock(clock: object, *, not_before: Sequence[str]) -> str:
    if not callable(clock):
        _validation_error("feature_publication_v4_ledger_clock_not_callable")
    try:
        sampled = cast(Callable[[], object], clock)()
    except Exception:  # noqa: BLE001 - hostile clock details must not escape
        _validation_error("feature_publication_v4_ledger_clock_failed")
    if type(sampled) is not datetime or sampled.tzinfo is not UTC or sampled < _EPOCH:
        _validation_error("feature_publication_v4_ledger_clock_not_exact_utc_datetime")
    if any(
        sampled < _parse_clock(value, reason="feature_publication_v4_upstream_clock_invalid")
        for value in not_before
    ):
        _validation_error("feature_publication_v4_ledger_clock_before_upstream_evidence")
    return sampled.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _address_material(address: object) -> dict[str, object]:
    values = {
        "schema_version": getattr(address, "schema_version", None),
        "payload_sha256": getattr(address, "payload_sha256", None),
        "payload_byte_count": getattr(address, "payload_byte_count", None),
        "relative_path": getattr(address, "relative_path", None),
    }
    _validate_address(values)
    return values


def _validate_address(value: object) -> dict[str, Any]:
    address = _exact_object(
        value,
        _ADDRESS_FIELDS,
        reason="feature_publication_v4_cas_address_fields_invalid",
    )
    digest = address["payload_sha256"]
    if (
        address["schema_version"] != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or not _is_sha256(digest)
        or type(address["payload_byte_count"]) is not int
        or not 1 <= address["payload_byte_count"] <= 256 * 1024 * 1024
        or type(address["relative_path"]) is not str
        or address["relative_path"] != f"sha256/{cast(str, digest)[:2]}/{digest}"
    ):
        _integrity_error("feature_publication_v4_cas_address_invalid")
    return address


def _owned_store_material() -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_SCHEMA_VERSION,
        "namespace": FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_NAMESPACE,
        "root_relative_path": FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_ROOT_RELATIVE_PATH,
        "underlying_store_schema_version": SOURCE_PAYLOAD_STORE_SCHEMA_VERSION,
        "address_schema_version": SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    }
    material["store_binding_sha256"] = _stable_sha256(material)
    return material


def _validate_owned_store_material(value: object) -> None:
    material = _exact_object(
        value,
        _STORE_FIELDS,
        reason="feature_publication_v4_owned_store_fields_invalid",
    )
    if material != _owned_store_material():
        _integrity_error("feature_publication_v4_owned_store_binding_invalid")


def _owned_store_put(
    store: ImmutableSourcePayloadStore,
    payload: bytes,
) -> dict[str, object]:
    digest = _sha256_bytes(payload)
    try:
        address = store.put(
            payload,
            expected_sha256=digest,
            expected_byte_count=len(payload),
        )
        readback = store.get(digest, expected_byte_count=len(payload))
    except SourcePayloadIntegrityError as exc:
        raise FeatureSnapshotPublicationLedgerV4IntegrityError(
            "feature_publication_v4_owned_cas_integrity_failed"
        ) from exc
    except SourcePayloadStoreError as exc:
        raise FeatureSnapshotPublicationLedgerV4DurabilityError(
            "feature_publication_v4_owned_cas_put_or_readback_failed"
        ) from exc
    if not hmac.compare_digest(readback, payload):
        _integrity_error("feature_publication_v4_owned_cas_readback_mismatch")
    return _address_material(address)


def _owned_store_get(
    store: ImmutableSourcePayloadStore,
    address_value: object,
    *,
    reason: str,
) -> bytes:
    address = _validate_address(address_value)
    try:
        payload = store.get(
            cast(str, address["payload_sha256"]),
            expected_byte_count=cast(int, address["payload_byte_count"]),
        )
    except SourcePayloadStoreError as exc:
        raise FeatureSnapshotPublicationLedgerV4IntegrityError(reason) from exc
    if type(payload) is not bytes:
        _integrity_error(reason)
    if _sha256_bytes(payload) != address["payload_sha256"]:
        _integrity_error(reason)
    return payload


def _source_ledger_root_material(ledger: TrainerSourceProvenanceLedgerV4) -> tuple[str, str]:
    root = os.fspath(ledger.root)
    if (
        not os.path.isabs(root)
        or "\x00" in root
        or any(component == ".." for component in Path(root).parts)
    ):
        _integrity_error("feature_publication_v4_source_ledger_root_invalid")
    return root, _sha256_bytes(root.encode("utf-8", errors="strict"))


def _fresh_source_entry(
    source_ledger: TrainerSourceProvenanceLedgerV4,
    *,
    sequence: int,
    entry_sha256: str,
) -> TrainerSourceProvenanceLedgerEntryV4:
    if type(source_ledger) is not TrainerSourceProvenanceLedgerV4:
        _validation_error("feature_publication_v4_exact_p0c_ledger_required")
    if type(sequence) is not int or sequence <= 0 or sequence > MAX_LEDGER_ENTRIES:
        _validation_error("feature_publication_v4_source_sequence_invalid")
    if not _is_sha256(entry_sha256):
        _validation_error("feature_publication_v4_source_entry_sha256_invalid")
    try:
        entries = source_ledger.read_entries()
    except TrainerSourceProvenanceLedgerV4Error as exc:
        raise FeatureSnapshotPublicationLedgerV4IntegrityError(
            "feature_publication_v4_source_ledger_fresh_read_failed"
        ) from exc
    if sequence > len(entries):
        _validation_error("feature_publication_v4_source_entry_not_found")
    entry = entries[sequence - 1]
    if (
        type(entry) is not TrainerSourceProvenanceLedgerEntryV4
        or entry.ledger_sequence != sequence
        or entry.entry_sha256 != entry_sha256
    ):
        _conflict_error("feature_publication_v4_source_entry_identity_mismatch")
    # A second mapping access re-runs the P0-C artifact's own strict parser.
    _verified_record = entry.record
    return entry


def _source_binding_from_entry(
    source_ledger: TrainerSourceProvenanceLedgerV4,
    entry: TrainerSourceProvenanceLedgerEntryV4,
) -> dict[str, object]:
    record = entry.record
    source = cast(dict[str, Any], record["source_capture"])
    manifest = cast(dict[str, Any], record["suffix_manifest"])
    rows = cast(list[dict[str, Any]], record["ordered_rows"])
    if not rows or len(rows) > MAX_FEATURE_SLOTS:
        _integrity_error("feature_publication_v4_source_suffix_row_count_invalid")
    last = rows[-1]
    latest = {
        "selected_ordinal": last["selected_ordinal"],
        "source_index": last["source_index"],
        "candle_id": last["candle_id"],
        "candle_open_time_ms": last["candle_open_time_ms"],
        "candle_close_time_ms": last["candle_close_time_ms"],
        "producer_event_time_ms": last["producer_event_time_ms"],
        "ingested_at_ms": last["ingested_at_ms"],
        "available_at_ms": last["available_at_ms"],
        "economic_event_time": last["economic_event_time"],
        "producer_event_time": last["producer_event_time"],
        "ingested_at": last["ingested_at"],
        "available_at": last["available_at"],
        "consumer_observed_at": last["consumer_observed_at"],
        "feature_cutoff": last["feature_cutoff"],
        "source": last["source"],
        "source_sequence_id": last["source_sequence_id"],
        "raw_payload_hash": last["raw_payload_hash"],
        "is_backfilled": last["is_backfilled"],
        "source_read_receipt_sha256": last["source_read_receipt_sha256"],
        "exact_payload_sha256": last["exact_payload_sha256"],
        "source_payload_cas_address": last["source_payload_cas_address"],
    }
    root, root_sha256 = _source_ledger_root_material(source_ledger)
    complete_suffix_material = {
        "full_source_payload_cas_address": source["full_source_payload"],
        "suffix_manifest_sha256": manifest["exact_manifest_sha256"],
        "suffix_manifest_cas_address": manifest["manifest_cas_address"],
        "suffix_digest_sha256": manifest["suffix_digest_sha256"],
        "selected_candle_ids": manifest["selected_candle_ids"],
        "ordered_source_read_receipt_sha256s": [row["source_read_receipt_sha256"] for row in rows],
        "ordered_exact_row_payload_sha256s": [row["exact_payload_sha256"] for row in rows],
    }
    binding: dict[str, object] = {
        "schema_version": FEATURE_SOURCE_PROVENANCE_BINDING_SCHEMA_VERSION,
        "source_ledger_schema_version": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION,
        "source_ledger_namespace": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_NAMESPACE,
        "source_ledger_root": root,
        "source_ledger_root_sha256": root_sha256,
        "source_ledger_sequence": entry.ledger_sequence,
        "source_ledger_entry_sha256": entry.entry_sha256,
        "source_ledger_entry_json_sha256": _sha256_bytes(entry.entry_json.encode("ascii")),
        "source_replay_identity_sha256": entry.replay_identity_sha256,
        "source_cycle_identity_sha256": entry.cycle_identity_sha256,
        "trainer_run_id": entry.trainer_run_id,
        "trainer_cycle_id": entry.trainer_cycle_id,
        "source_ledger_recorded_at": record["ledger_recorded_at"],
        "source_key": source["source_key"],
        "source_key_sha256": source["source_key_sha256"],
        "source_key_version": source["source_key_version"],
        "atomic_batch_id": source["atomic_batch_id"],
        "atomic_batch_material_sha256": source["atomic_batch_material_sha256"],
        "full_source_payload_cas_address": source["full_source_payload"],
        "suffix_manifest_sha256": manifest["exact_manifest_sha256"],
        "suffix_manifest_cas_address": manifest["manifest_cas_address"],
        "suffix_digest_sha256": manifest["suffix_digest_sha256"],
        "selected_row_count": len(rows),
        "selected_candle_ids": list(manifest["selected_candle_ids"]),
        "ordered_source_read_receipt_sha256s": [row["source_read_receipt_sha256"] for row in rows],
        "ordered_exact_row_payload_sha256s": [row["exact_payload_sha256"] for row in rows],
        "latest_candle": latest,
        "complete_suffix_binding_sha256": _stable_sha256(complete_suffix_material),
    }
    binding["source_scope_binding_sha256"] = _stable_sha256(binding)
    return binding


def _verify_source_binding(
    record: Mapping[str, Any],
    source_ledger: TrainerSourceProvenanceLedgerV4,
) -> None:
    persisted = _exact_object(
        record["source_provenance_binding"],
        _SOURCE_BINDING_FIELDS,
        reason="feature_publication_v4_source_binding_fields_invalid",
    )
    sequence = persisted["source_ledger_sequence"]
    digest = persisted["source_ledger_entry_sha256"]
    if type(sequence) is not int or not _is_sha256(digest):
        _integrity_error("feature_publication_v4_source_binding_identity_invalid")
    entry = _fresh_source_entry(
        source_ledger,
        sequence=sequence,
        entry_sha256=cast(str, digest),
    )
    expected = _source_binding_from_entry(source_ledger, entry)
    if persisted != expected:
        _integrity_error("feature_publication_v4_source_binding_fresh_read_mismatch")


def _parse_native_snapshot_bytes(payload: bytes) -> dict[str, Any]:
    if (
        type(payload) is not bytes
        or not payload
        or len(payload) > MAX_CANONICAL_FEATURE_SNAPSHOT_BYTES
    ):
        _integrity_error("feature_publication_v4_native_snapshot_bytes_invalid")
    snapshot = _parse_json_object(payload, max_bytes=MAX_CANONICAL_FEATURE_SNAPSHOT_BYTES)
    if (
        snapshot.get("schema_version") != NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION
        or snapshot.get("worker_id") != NATIVE_FEATURE_SNAPSHOT_WORKER_ID
    ):
        _integrity_error("feature_publication_v4_native_snapshot_contract_invalid")
    return snapshot


def _canonical_float32(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        parsed = float(cast(int | float, value))
        if not math.isfinite(parsed):
            return None
        runtime = float(struct.unpack("!f", struct.pack("!f", parsed))[0])
    except (OverflowError, struct.error, TypeError, ValueError):
        return None
    if not math.isfinite(runtime) or (parsed != 0.0 and runtime == 0.0):
        return None
    return 0.0 if runtime == 0.0 else runtime


def _exact_feature_name_list(value: object, *, reason: str) -> list[str]:
    if type(value) is not list or not value or len(value) > MAX_FEATURE_SLOTS:
        _integrity_error(reason)
    names: list[str] = []
    for item in cast(list[object], value):
        names.append(_required_label(item, reason=reason))
    if len(names) != len(set(names)):
        _integrity_error(reason)
    return names


def _code_owned_native_model_contract() -> tuple[list[str], list[str], list[str]]:
    """Return the exact TensorBuilder order and its filtered declarations."""

    if type(FEATURE_SPEC) is not tuple or not 1 <= len(FEATURE_SPEC) <= MAX_FEATURE_SLOTS:
        _integrity_error("feature_publication_v4_code_owned_feature_spec_invalid")
    names: list[str] = []
    for item in FEATURE_SPEC:
        if type(item) is not tuple or len(item) != 2:
            _integrity_error("feature_publication_v4_code_owned_feature_spec_invalid")
        name, source = item
        names.append(
            _required_label(
                name,
                reason="feature_publication_v4_code_owned_feature_spec_invalid",
            )
        )
        _required_label(
            source,
            reason="feature_publication_v4_code_owned_feature_spec_invalid",
        )
    if len(names) != len(set(names)):
        _integrity_error("feature_publication_v4_code_owned_feature_spec_not_unique")
    try:
        requirements = feature_requirement_classes_for_names(names)
    except FeatureSnapshotValidationError as exc:
        raise FeatureSnapshotPublicationLedgerV4IntegrityError(
            "feature_publication_v4_code_owned_requirement_policy_invalid"
        ) from exc
    required = [
        name
        for name, requirement in zip(names, requirements, strict=True)
        if requirement == "REQUIRED"
    ]
    optional = [
        name
        for name, requirement in zip(names, requirements, strict=True)
        if requirement == "OPTIONAL_EVENT_DEPENDENT"
    ]
    if len(required) + len(optional) != len(names):
        _integrity_error("feature_publication_v4_code_owned_requirement_policy_invalid")
    return names, required, optional


def _declared_model_order(
    snapshot: dict[str, Any],
    features: dict[str, Any],
) -> tuple[list[str], str]:
    model_names, expected_required, expected_optional = _code_owned_native_model_contract()
    required_value = snapshot.get("required_model_feature_fields")
    optional_value = snapshot.get("optional_event_dependent_feature_fields")
    if required_value is None and optional_value is None:
        names = sorted(features)
        if not names:
            _integrity_error("feature_publication_v4_empty_feature_vector")
        if names == model_names:
            _integrity_error("feature_publication_v4_native_model_abi_declarations_required")
        return names, INCOMPLETE_FALLBACK_ABI_ORIGIN
    if required_value is None or optional_value is None:
        _integrity_error("feature_publication_v4_partial_requirement_declaration")
    required = _exact_feature_name_list(
        required_value,
        reason="feature_publication_v4_required_feature_names_invalid",
    )
    optional = _exact_feature_name_list(
        optional_value,
        reason="feature_publication_v4_optional_feature_names_invalid",
    )
    declared_names = required + optional
    if len(declared_names) != len(set(declared_names)):
        _integrity_error("feature_publication_v4_declared_feature_names_not_unique")
    if snapshot.get("feature_requirement_policy_id") != FEATURE_REQUIREMENT_POLICY_ID:
        _integrity_error("feature_publication_v4_requirement_policy_mismatch")
    if required != expected_required:
        _integrity_error("feature_publication_v4_required_feature_declaration_mismatch")
    if optional != expected_optional:
        _integrity_error("feature_publication_v4_optional_feature_declaration_mismatch")
    if snapshot.get("model_feature_abi_slot_count") != len(model_names):
        _integrity_error("feature_publication_v4_declared_abi_count_mismatch")
    if snapshot.get("required_model_feature_count") != len(expected_required):
        _integrity_error("feature_publication_v4_required_count_mismatch")
    if snapshot.get("optional_event_dependent_feature_count") != len(expected_optional):
        _integrity_error("feature_publication_v4_optional_count_mismatch")
    expected_requirements = feature_requirement_classes_for_names(model_names)
    if (
        len(expected_requirements) != len(model_names)
        or expected_requirements.count("REQUIRED") != len(expected_required)
        or expected_requirements.count("OPTIONAL_EVENT_DEPENDENT") != len(expected_optional)
    ):
        _integrity_error("feature_publication_v4_declared_requirement_policy_violation")
    return model_names, NATIVE_MODEL_ABI_ORIGIN


def _validate_native_missing_declarations(
    snapshot: dict[str, Any],
    *,
    names: list[str],
    values: list[float],
    missing: list[int],
    requirements: list[str],
) -> None:
    if snapshot.get("required_model_feature_fields") is None:
        return
    required_missing = sorted(
        name
        for name, mask, requirement in zip(names, missing, requirements, strict=True)
        if mask == 1 and requirement == "REQUIRED"
    )
    optional_missing = sorted(
        name
        for name, mask, requirement in zip(names, missing, requirements, strict=True)
        if mask == 1 and requirement == "OPTIONAL_EVENT_DEPENDENT"
    )
    optional_present = sorted(
        name
        for name, mask, requirement in zip(names, missing, requirements, strict=True)
        if mask == 0 and requirement == "OPTIONAL_EVENT_DEPENDENT"
    )
    if snapshot.get("required_model_feature_missing_fields") != required_missing:
        _integrity_error("feature_publication_v4_required_missing_declaration_mismatch")
    if snapshot.get("optional_event_dependent_feature_missing_fields") != optional_missing:
        _integrity_error("feature_publication_v4_optional_missing_declaration_mismatch")
    if snapshot.get("optional_event_dependent_feature_present_fields") != optional_present:
        _integrity_error("feature_publication_v4_optional_present_declaration_mismatch")
    if snapshot.get("required_model_feature_value_contract_valid") is not (not required_missing):
        _integrity_error("feature_publication_v4_required_value_validity_mismatch")
    if len(values) != len(names):
        _integrity_error("feature_publication_v4_vector_dimension_invalid")


def _vector_binding_from_snapshot(snapshot: dict[str, Any]) -> dict[str, object]:
    raw_features = snapshot.get("features")
    if type(raw_features) is not dict or not 1 <= len(raw_features) <= MAX_FEATURE_SLOTS:
        _integrity_error("feature_publication_v4_native_features_invalid")
    features: dict[str, Any] = {}
    for key, value in cast(dict[object, object], raw_features).items():
        name = _required_label(key, reason="feature_publication_v4_feature_name_invalid")
        features[name] = value
    names, abi_origin = _declared_model_order(snapshot, features)
    requirements = list(feature_requirement_classes_for_names(names))
    values: list[float] = []
    missing: list[int] = []
    for name in names:
        parsed = _canonical_float32(features.get(name))
        if parsed is None:
            values.append(0.0)
            missing.append(1)
        else:
            values.append(parsed)
            missing.append(0)
    stale_flags = snapshot.get("stale_feature_flags", [])
    if type(stale_flags) is not list or len(stale_flags) > MAX_FEATURE_SLOTS:
        _integrity_error("feature_publication_v4_stale_flags_invalid")
    for value in stale_flags:
        _required_label(value, reason="feature_publication_v4_stale_flag_invalid")
    stale = [1 if stale_flags else 0 for _ in names]
    availability = [0 for _ in names]
    source_labels = [UNRESOLVED_SOURCE_LABEL for _ in names]
    roots: list[None] = [None for _ in names]
    available_at: list[None] = [None for _ in names]
    _validate_native_missing_declarations(
        snapshot,
        names=names,
        values=values,
        missing=missing,
        requirements=requirements,
    )
    missing_flags = snapshot.get("missing_feature_flags", [])
    if type(missing_flags) is not list or len(missing_flags) > MAX_FEATURE_SLOTS * 2:
        _integrity_error("feature_publication_v4_missing_flags_invalid")
    for value in missing_flags:
        _required_label(value, reason="feature_publication_v4_missing_flag_invalid")
    try:
        abi = feature_abi_contract(
            names,
            feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
            ordered_feature_requirement_classes=requirements,
        )
    except FeatureSnapshotValidationError as exc:
        raise FeatureSnapshotPublicationLedgerV4IntegrityError(
            "feature_publication_v4_feature_abi_invalid"
        ) from exc
    material: dict[str, object] = {
        "schema_version": FEATURE_VECTOR_BINDING_SCHEMA_VERSION,
        "abi_origin": abi_origin,
        "feature_requirement_policy_id": FEATURE_REQUIREMENT_POLICY_ID,
        "feature_count": len(names),
        "ordered_feature_names": names,
        "ordered_feature_values": values,
        "missing_mask": missing,
        "stale_mask": stale,
        "source_availability_mask": availability,
        "ordered_feature_requirement_classes": requirements,
        "ordered_resolved_source_labels": source_labels,
        "per_field_root_receipt_sha256s": roots,
        "per_field_available_at": available_at,
        "feature_abi": abi,
        "feature_abi_sha256": _stable_sha256(abi),
        "ordered_values_sha256": _stable_sha256(
            {"ordered_feature_names": names, "ordered_feature_values": values}
        ),
        "mask_vectors_sha256": _stable_sha256(
            {
                "missing_mask": missing,
                "stale_mask": stale,
                "source_availability_mask": availability,
            }
        ),
        "per_field_bindings_sha256": _stable_sha256(
            {
                "ordered_resolved_source_labels": source_labels,
                "per_field_root_receipt_sha256s": roots,
                "per_field_available_at": available_at,
            }
        ),
        "native_snapshot_features_sha256": _stable_sha256(features),
        "native_snapshot_declared_missing_flags_sha256": _stable_sha256(missing_flags),
        "feature_source_evidence_complete": False,
        "feature_available_at_complete": False,
    }
    material["vector_binding_sha256"] = _stable_sha256(material)
    return material


def _derivation_binding(vector: Mapping[str, Any]) -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": FEATURE_DERIVATION_BINDING_SCHEMA_VERSION,
        "producer_worker_id": NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
        "feature_abi_schema_version": FEATURE_ABI_SCHEMA_VERSION,
        "feature_abi_sha256": vector["feature_abi_sha256"],
        "producer_code_sha256": None,
        "producer_configuration_sha256": None,
        "feature_transform_sha256": None,
        "derivation_identity_complete": False,
    }
    material["derivation_binding_sha256"] = _stable_sha256(material)
    return material


def _external_store_root(store: ImmutableSourcePayloadStore) -> tuple[str, str]:
    root = os.fspath(store.root_path)
    if (
        not os.path.isabs(root)
        or "\x00" in root
        or any(component == ".." for component in Path(root).parts)
    ):
        _integrity_error("feature_publication_v4_artifact_store_root_invalid")
    return root, _sha256_bytes(root.encode("utf-8", errors="strict"))


def _artifact_projection(
    *,
    artifact: FeatureSnapshotCasArtifact,
    binding: dict[str, Any],
    owned_content_address: dict[str, object],
    owned_binding_address: dict[str, object],
) -> dict[str, object]:
    store_root, store_root_sha256 = _external_store_root(artifact.source_payload_store)
    projection: dict[str, object] = {
        "schema_version": FEATURE_ARTIFACT_BINDING_SCHEMA_VERSION,
        "source_artifact_binding_schema_version": CAS_ARTIFACT_BINDING_SCHEMA_VERSION,
        "native_snapshot_schema_version": NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION,
        "artifact_serialization_schema_version": CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION,
        "artifact_record_id": binding["artifact_record_id"],
        "artifact_binding_sha256": binding["artifact_binding_sha256"],
        "artifact_binding_json_sha256": _sha256_bytes(
            artifact.artifact_binding_json.encode("ascii", errors="strict")
        ),
        "artifact_binding_json_byte_count": len(
            artifact.artifact_binding_json.encode("ascii", errors="strict")
        ),
        "feature_snapshot_id": binding["feature_snapshot_id"],
        "producer_worker_id": binding["producer_worker_id"],
        "symbol": binding["symbol"],
        "timeframe": binding["timeframe"],
        "candle_open_time": binding["candle_open_time"],
        "candle_close_time": binding["candle_close_time"],
        "source_event_time": binding["source_event_time"],
        "source_ingested_at": binding["source_ingested_at"],
        "source_available_at": binding["source_available_at"],
        "feature_cutoff": binding["feature_cutoff"],
        "generated_at": binding["generated_at"],
        "source": binding["source"],
        "is_backfilled": binding["is_backfilled"],
        "source_sequence_id": binding["source_sequence_id"],
        "raw_payload_hash": binding["raw_payload_hash"],
        "artifact_serialization_sha256": binding["artifact_serialization_sha256"],
        "artifact_serialization_byte_count": binding["artifact_serialization_byte_count"],
        "source_artifact_store_root": store_root,
        "source_artifact_store_root_sha256": store_root_sha256,
        "source_artifact_content_cas_address": _address_material(artifact.cas_address),
        "source_artifact_binding_cas_address": _address_material(
            artifact.artifact_binding_cas_address
        ),
        "ledger_owned_artifact_content_cas_address": owned_content_address,
        "ledger_owned_artifact_binding_cas_address": owned_binding_address,
    }
    projection["artifact_binding_projection_sha256"] = _stable_sha256(projection)
    return projection


def _artifact_material(
    artifact: object,
    store: ImmutableSourcePayloadStore,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, Any]]:
    if type(artifact) is not FeatureSnapshotCasArtifact:
        _validation_error("feature_publication_v4_exact_artifact_type_required")
    typed = artifact
    if type(typed.source_payload_store) is not ImmutableSourcePayloadStore:
        _validation_error("feature_publication_v4_exact_artifact_store_required")
    try:
        first_binding = typed.artifact_binding
    except FeatureSnapshotPublicationError as exc:
        raise FeatureSnapshotPublicationLedgerV4ValidationError(
            "feature_publication_v4_artifact_fresh_validation_failed"
        ) from exc
    snapshot_bytes = typed.artifact_snapshot_bytes
    binding_bytes = typed.artifact_binding_json.encode("ascii", errors="strict")
    snapshot = _parse_native_snapshot_bytes(snapshot_bytes)
    if (
        _sha256_bytes(snapshot_bytes) != first_binding["artifact_serialization_sha256"]
        or len(snapshot_bytes) != first_binding["artifact_serialization_byte_count"]
        or typed.artifact_record_id != first_binding["artifact_record_id"]
        or typed.artifact_binding_sha256 != first_binding["artifact_binding_sha256"]
    ):
        _integrity_error("feature_publication_v4_artifact_result_binding_invalid")
    owned_content = _owned_store_put(store, snapshot_bytes)
    owned_binding = _owned_store_put(store, binding_bytes)
    projection = _artifact_projection(
        artifact=typed,
        binding=first_binding,
        owned_content_address=owned_content,
        owned_binding_address=owned_binding,
    )
    vector = _vector_binding_from_snapshot(snapshot)
    derivation = _derivation_binding(vector)
    try:
        final_binding = typed.artifact_binding
    except FeatureSnapshotPublicationError as exc:
        raise FeatureSnapshotPublicationLedgerV4IntegrityError(
            "feature_publication_v4_artifact_changed_during_pin"
        ) from exc
    if first_binding != final_binding:
        _integrity_error("feature_publication_v4_artifact_changed_during_pin")
    return projection, vector, derivation, first_binding


def _match_artifact_to_source(
    artifact_binding: Mapping[str, Any],
    source_binding: Mapping[str, Any],
) -> None:
    latest = _exact_object(
        source_binding["latest_candle"],
        _LATEST_CANDLE_FIELDS,
        reason="feature_publication_v4_latest_candle_fields_invalid",
    )
    expected_source_key = (
        f"v2:market:ohlcv_closed:binance:{artifact_binding['symbol']}:"
        f"{artifact_binding['timeframe']}"
    )
    expected_clocks = {
        "candle_open_time": _ms_to_clock(latest["candle_open_time_ms"]),
        "candle_close_time": _ms_to_clock(latest["candle_close_time_ms"]),
        "source_event_time": _ms_to_clock(latest["producer_event_time_ms"]),
        "source_ingested_at": _ms_to_clock(latest["ingested_at_ms"]),
        "source_available_at": _ms_to_clock(latest["available_at_ms"]),
        "feature_cutoff": latest["feature_cutoff"],
    }
    if (
        source_binding["source_key"] != expected_source_key
        or any(artifact_binding.get(key) != value for key, value in expected_clocks.items())
        or artifact_binding.get("raw_payload_hash") != latest["raw_payload_hash"]
        or artifact_binding.get("source_sequence_id") != latest["source_sequence_id"]
        or artifact_binding.get("source") != latest["source"]
        or artifact_binding.get("is_backfilled") is not latest["is_backfilled"]
        or cast(list[Any], source_binding["selected_candle_ids"])[-1] != latest["candle_id"]
        or cast(list[Any], source_binding["ordered_source_read_receipt_sha256s"])[-1]
        != latest["source_read_receipt_sha256"]
    ):
        _validation_error("feature_publication_v4_artifact_latest_candle_not_exact_p0c_tail")


def _temporal_binding(
    *,
    artifact_binding: Mapping[str, Any],
    source_binding: Mapping[str, Any],
    ledger_recorded_at: str,
) -> dict[str, object]:
    source_available = _parse_clock(
        artifact_binding["source_available_at"],
        reason="feature_publication_v4_artifact_source_available_at_invalid",
    )
    cutoff = _parse_clock(
        artifact_binding["feature_cutoff"],
        reason="feature_publication_v4_artifact_feature_cutoff_invalid",
    )
    generated = _parse_clock(
        artifact_binding["generated_at"],
        reason="feature_publication_v4_artifact_generated_at_invalid",
    )
    observed = _parse_clock(
        source_binding["latest_candle"]["consumer_observed_at"],
        reason="feature_publication_v4_source_consumer_observed_at_invalid",
    )
    source_recorded = _parse_clock(
        source_binding["source_ledger_recorded_at"],
        reason="feature_publication_v4_source_ledger_recorded_at_invalid",
    )
    recorded = _parse_clock(
        ledger_recorded_at,
        reason="feature_publication_v4_ledger_recorded_at_invalid",
    )
    if not cutoff <= source_available <= observed <= source_recorded <= recorded:
        _integrity_error("feature_publication_v4_source_temporal_order_invalid")
    if not source_available <= generated <= recorded:
        _integrity_error("feature_publication_v4_artifact_generation_order_invalid")
    material: dict[str, object] = {
        "schema_version": FEATURE_TEMPORAL_BINDING_SCHEMA_VERSION,
        "candle_open_time": artifact_binding["candle_open_time"],
        "candle_close_time": artifact_binding["candle_close_time"],
        "source_event_time": artifact_binding["source_event_time"],
        "source_ingested_at": artifact_binding["source_ingested_at"],
        "source_available_at": artifact_binding["source_available_at"],
        "feature_cutoff": artifact_binding["feature_cutoff"],
        "snapshot_generated_at": artifact_binding["generated_at"],
        "source_consumer_observed_at": source_binding["latest_candle"]["consumer_observed_at"],
        "source_ledger_recorded_at": source_binding["source_ledger_recorded_at"],
        "feature_available_at": None,
        "publication_completed_at": None,
        "decision_time": None,
        "execution_time": None,
        "available_at_feature_cutoff_decision_order_applicable": False,
        "available_at_feature_cutoff_decision_order_verified": False,
        "pit_order_status": ("NOT_APPLICABLE_PER_FIELD_AVAILABLE_AT_AND_DECISION_TIME_ABSENT"),
        "ledger_recorded_at": ledger_recorded_at,
    }
    material["temporal_binding_sha256"] = _stable_sha256(material)
    return material


def _publication_identity(
    source: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> str:
    return _stable_sha256(
        {
            "schema_version": FEATURE_PUBLICATION_IDENTITY_SCHEMA_VERSION,
            "source_ledger_namespace": source["source_ledger_namespace"],
            "source_ledger_sequence": source["source_ledger_sequence"],
            "source_ledger_entry_sha256": source["source_ledger_entry_sha256"],
            "source_replay_identity_sha256": source["source_replay_identity_sha256"],
            "artifact_record_id": artifact["artifact_record_id"],
            "artifact_binding_sha256": artifact["artifact_binding_sha256"],
            "artifact_serialization_sha256": artifact["artifact_serialization_sha256"],
        }
    )


def _replay_material_from_record(record: Mapping[str, Any]) -> dict[str, object]:
    temporal = cast(Mapping[str, Any], record["temporal_binding"])
    temporal_replay_material = {
        key: item
        for key, item in temporal.items()
        if key not in {"ledger_recorded_at", "temporal_binding_sha256"}
    }
    return {
        "schema_version": "feature_snapshot_publication_replay_material_v4",
        "publication_identity_sha256": record["publication_identity_sha256"],
        "ledger_owned_store": record["ledger_owned_store"],
        "source_provenance_binding": record["source_provenance_binding"],
        "feature_artifact_binding": record["feature_artifact_binding"],
        "feature_vector_binding": record["feature_vector_binding"],
        "derivation_binding": record["derivation_binding"],
        "temporal_binding_without_ledger_record_clock": temporal_replay_material,
        "source_scope_incompleteness_reasons": record["source_scope_incompleteness_reasons"],
        **{name: record[name] for name in _DOWNSTREAM_FLAG_FIELDS},
    }


def _validate_vector_binding(value: object) -> dict[str, Any]:
    vector = _exact_object(
        value,
        _VECTOR_BINDING_FIELDS,
        reason="feature_publication_v4_vector_fields_invalid",
    )
    count = vector["feature_count"]
    sequence_fields = (
        "ordered_feature_names",
        "ordered_feature_values",
        "missing_mask",
        "stale_mask",
        "source_availability_mask",
        "ordered_feature_requirement_classes",
        "ordered_resolved_source_labels",
        "per_field_root_receipt_sha256s",
        "per_field_available_at",
    )
    if (
        vector["schema_version"] != FEATURE_VECTOR_BINDING_SCHEMA_VERSION
        or type(count) is not int
        or not 1 <= count <= MAX_FEATURE_SLOTS
        or any(type(vector[field_name]) is not list for field_name in sequence_fields)
        or any(len(vector[field_name]) != count for field_name in sequence_fields)
        or vector["feature_source_evidence_complete"] is not False
        or vector["feature_available_at_complete"] is not False
    ):
        _integrity_error("feature_publication_v4_vector_contract_invalid")
    names = cast(list[Any], vector["ordered_feature_names"])
    if any(type(name) is not str or _LABEL_RE.fullmatch(name) is None for name in names) or len(
        names
    ) != len(set(names)):
        _integrity_error("feature_publication_v4_vector_names_invalid")
    model_names, _model_required, _model_optional = _code_owned_native_model_contract()
    if vector["abi_origin"] == NATIVE_MODEL_ABI_ORIGIN:
        if names != model_names:
            _integrity_error("feature_publication_v4_native_model_abi_order_invalid")
    elif vector["abi_origin"] == INCOMPLETE_FALLBACK_ABI_ORIGIN:
        if names != sorted(names) or names == model_names:
            _integrity_error("feature_publication_v4_fallback_abi_origin_invalid")
    else:
        _integrity_error("feature_publication_v4_abi_origin_invalid")
    values = cast(list[Any], vector["ordered_feature_values"])
    if any(_canonical_float32(item) != item for item in values):
        _integrity_error("feature_publication_v4_vector_values_invalid")
    for field_name in ("missing_mask", "stale_mask", "source_availability_mask"):
        if any(type(item) is not int or item not in (0, 1) for item in vector[field_name]):
            _integrity_error("feature_publication_v4_vector_mask_invalid")
    if any(item != 0 for item in vector["source_availability_mask"]):
        _integrity_error("feature_publication_v4_source_availability_must_be_false")
    if any(item != UNRESOLVED_SOURCE_LABEL for item in vector["ordered_resolved_source_labels"]):
        _integrity_error("feature_publication_v4_source_labels_must_be_unresolved")
    if any(item is not None for item in vector["per_field_root_receipt_sha256s"]):
        _integrity_error("feature_publication_v4_per_field_roots_must_be_absent")
    if any(item is not None for item in vector["per_field_available_at"]):
        _integrity_error("feature_publication_v4_per_field_available_at_must_be_absent")
    requirements = list(feature_requirement_classes_for_names(cast(list[str], names)))
    if vector["ordered_feature_requirement_classes"] != requirements:
        _integrity_error("feature_publication_v4_requirement_classes_invalid")
    try:
        abi = feature_abi_contract(
            cast(list[str], names),
            feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
            ordered_feature_requirement_classes=requirements,
        )
    except FeatureSnapshotValidationError as exc:
        raise FeatureSnapshotPublicationLedgerV4IntegrityError(
            "feature_publication_v4_persisted_abi_invalid"
        ) from exc
    if (
        vector["feature_requirement_policy_id"] != FEATURE_REQUIREMENT_POLICY_ID
        or vector["feature_abi"] != abi
        or vector["feature_abi_sha256"] != _stable_sha256(abi)
        or vector["ordered_values_sha256"]
        != _stable_sha256({"ordered_feature_names": names, "ordered_feature_values": values})
        or vector["mask_vectors_sha256"]
        != _stable_sha256(
            {
                "missing_mask": vector["missing_mask"],
                "stale_mask": vector["stale_mask"],
                "source_availability_mask": vector["source_availability_mask"],
            }
        )
        or vector["per_field_bindings_sha256"]
        != _stable_sha256(
            {
                "ordered_resolved_source_labels": vector["ordered_resolved_source_labels"],
                "per_field_root_receipt_sha256s": vector["per_field_root_receipt_sha256s"],
                "per_field_available_at": vector["per_field_available_at"],
            }
        )
    ):
        _integrity_error("feature_publication_v4_vector_hash_binding_invalid")
    claimed = vector["vector_binding_sha256"]
    material = {key: item for key, item in vector.items() if key != "vector_binding_sha256"}
    if not _is_sha256(claimed) or claimed != _stable_sha256(material):
        _integrity_error("feature_publication_v4_vector_root_invalid")
    return vector


def _validate_derivation_binding(value: object, vector: Mapping[str, Any]) -> None:
    derivation = _exact_object(
        value,
        _DERIVATION_BINDING_FIELDS,
        reason="feature_publication_v4_derivation_fields_invalid",
    )
    expected = _derivation_binding(vector)
    if derivation != expected:
        _integrity_error("feature_publication_v4_derivation_binding_invalid")


def _validate_temporal_binding(
    value: object,
    *,
    source: Mapping[str, Any],
    artifact: Mapping[str, Any],
    ledger_recorded_at: str,
) -> None:
    temporal = _exact_object(
        value,
        _TEMPORAL_BINDING_FIELDS,
        reason="feature_publication_v4_temporal_fields_invalid",
    )
    expected = _temporal_binding(
        artifact_binding=artifact,
        source_binding=source,
        ledger_recorded_at=ledger_recorded_at,
    )
    if temporal != expected:
        _integrity_error("feature_publication_v4_temporal_binding_invalid")


def _validate_entry_record(record: dict[str, Any]) -> None:
    if frozenset(record) != _ENTRY_FIELDS:
        _integrity_error("feature_publication_v4_entry_fields_invalid")
    if (
        record["schema_version"] != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION
        or record["evidence_classification"]
        != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_EVIDENCE_CLASSIFICATION
        or record["downstream_status"] != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_DOWNSTREAM_STATUS
        or record["ledger_namespace"] != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_NAMESPACE
        or type(record["ledger_sequence"]) is not int
        or not 1 <= record["ledger_sequence"] <= MAX_LEDGER_ENTRIES
        or not _is_sha256(record["previous_entry_sha256"])
        or not _is_sha256(record["publication_identity_sha256"])
        or not _is_sha256(record["publication_replay_identity_sha256"])
        or record["source_scope_incompleteness_reasons"]
        != list(SOURCE_SCOPE_INCOMPLETENESS_REASONS)
        or any(record[name] is not False for name in _DOWNSTREAM_FLAG_FIELDS)
    ):
        _integrity_error("feature_publication_v4_entry_contract_invalid")
    _parse_clock(
        record["ledger_recorded_at"],
        reason="feature_publication_v4_ledger_recorded_at_invalid",
    )
    _validate_owned_store_material(record["ledger_owned_store"])
    source = _exact_object(
        record["source_provenance_binding"],
        _SOURCE_BINDING_FIELDS,
        reason="feature_publication_v4_source_binding_fields_invalid",
    )
    latest = _exact_object(
        source["latest_candle"],
        _LATEST_CANDLE_FIELDS,
        reason="feature_publication_v4_latest_candle_fields_invalid",
    )
    artifact = _exact_object(
        record["feature_artifact_binding"],
        _ARTIFACT_BINDING_FIELDS,
        reason="feature_publication_v4_artifact_binding_fields_invalid",
    )
    if (
        source["schema_version"] != FEATURE_SOURCE_PROVENANCE_BINDING_SCHEMA_VERSION
        or source["source_ledger_schema_version"]
        != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION
        or source["source_ledger_namespace"] != TRAINER_SOURCE_PROVENANCE_LEDGER_V4_NAMESPACE
        or type(source["source_ledger_sequence"]) is not int
        or source["source_ledger_sequence"] <= 0
        or type(source["selected_row_count"]) is not int
        or not 1 <= source["selected_row_count"] <= MAX_FEATURE_SLOTS
        or any(
            type(source[field_name]) is not list
            or len(source[field_name]) != source["selected_row_count"]
            for field_name in (
                "selected_candle_ids",
                "ordered_source_read_receipt_sha256s",
                "ordered_exact_row_payload_sha256s",
            )
        )
        or any(
            not _is_sha256(source[field_name])
            for field_name in (
                "source_ledger_root_sha256",
                "source_ledger_entry_sha256",
                "source_ledger_entry_json_sha256",
                "source_replay_identity_sha256",
                "source_cycle_identity_sha256",
                "source_key_sha256",
                "atomic_batch_material_sha256",
                "suffix_manifest_sha256",
                "suffix_digest_sha256",
                "complete_suffix_binding_sha256",
                "source_scope_binding_sha256",
            )
        )
        or not _is_sha256(latest["source_read_receipt_sha256"])
        or not _is_sha256(latest["exact_payload_sha256"])
        or not _is_sha256(latest["raw_payload_hash"])
    ):
        _integrity_error("feature_publication_v4_source_binding_contract_invalid")
    _validate_address(source["full_source_payload_cas_address"])
    _validate_address(source["suffix_manifest_cas_address"])
    _validate_address(latest["source_payload_cas_address"])
    source_without_hash = {
        key: item for key, item in source.items() if key != "source_scope_binding_sha256"
    }
    if source["source_scope_binding_sha256"] != _stable_sha256(source_without_hash):
        _integrity_error("feature_publication_v4_source_binding_root_invalid")
    if (
        artifact["schema_version"] != FEATURE_ARTIFACT_BINDING_SCHEMA_VERSION
        or artifact["source_artifact_binding_schema_version"] != CAS_ARTIFACT_BINDING_SCHEMA_VERSION
        or artifact["native_snapshot_schema_version"] != NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION
        or artifact["artifact_serialization_schema_version"]
        != CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION
        or artifact["producer_worker_id"] != NATIVE_FEATURE_SNAPSHOT_WORKER_ID
        or type(artifact["artifact_record_id"]) is not str
        or _ARTIFACT_RECORD_ID_RE.fullmatch(artifact["artifact_record_id"]) is None
        or type(artifact["feature_snapshot_id"]) is not str
        or _FEATURE_SNAPSHOT_ID_RE.fullmatch(artifact["feature_snapshot_id"]) is None
        or type(artifact["artifact_serialization_byte_count"]) is not int
        or not 1
        <= artifact["artifact_serialization_byte_count"]
        <= MAX_CANONICAL_FEATURE_SNAPSHOT_BYTES
        or type(artifact["artifact_binding_json_byte_count"]) is not int
        or not 1
        <= artifact["artifact_binding_json_byte_count"]
        <= MAX_CANONICAL_FEATURE_SNAPSHOT_BYTES
        or any(
            not _is_sha256(artifact[field_name])
            for field_name in (
                "artifact_binding_sha256",
                "artifact_binding_json_sha256",
                "artifact_serialization_sha256",
                "source_artifact_store_root_sha256",
                "artifact_binding_projection_sha256",
            )
        )
    ):
        _integrity_error("feature_publication_v4_artifact_binding_contract_invalid")
    for field_name in (
        "source_artifact_content_cas_address",
        "source_artifact_binding_cas_address",
        "ledger_owned_artifact_content_cas_address",
        "ledger_owned_artifact_binding_cas_address",
    ):
        _validate_address(artifact[field_name])
    artifact_without_hash = {
        key: item for key, item in artifact.items() if key != "artifact_binding_projection_sha256"
    }
    if artifact["artifact_binding_projection_sha256"] != _stable_sha256(artifact_without_hash):
        _integrity_error("feature_publication_v4_artifact_projection_root_invalid")
    vector = _validate_vector_binding(record["feature_vector_binding"])
    _validate_derivation_binding(record["derivation_binding"], vector)
    _match_artifact_to_source(artifact, source)
    _validate_temporal_binding(
        record["temporal_binding"],
        source=source,
        artifact=artifact,
        ledger_recorded_at=cast(str, record["ledger_recorded_at"]),
    )
    identity = _publication_identity(source, artifact)
    if record["publication_identity_sha256"] != identity or record[
        "publication_replay_identity_sha256"
    ] != _stable_sha256(_replay_material_from_record(record)):
        _integrity_error("feature_publication_v4_publication_identity_invalid")
    claimed_entry = _required_sha256(
        record["entry_sha256"],
        reason="feature_publication_v4_entry_sha256_invalid",
    )
    without_entry = {key: item for key, item in record.items() if key != "entry_sha256"}
    if claimed_entry != _stable_sha256(without_entry):
        _integrity_error("feature_publication_v4_entry_sha256_mismatch")


def _parse_entry_line(raw: bytes) -> dict[str, Any]:
    record = _parse_json_object(raw, max_bytes=MAX_LEDGER_ENTRY_BYTES)
    _validate_entry_record(record)
    return record


def _artifact(
    record: dict[str, Any],
    *,
    source_ledger: TrainerSourceProvenanceLedgerV4,
    store: ImmutableSourcePayloadStore,
    expected_store_root: Path,
) -> FeatureSnapshotPublicationLedgerEntryV4:
    source = cast(dict[str, Any], record["source_provenance_binding"])
    feature_artifact = cast(dict[str, Any], record["feature_artifact_binding"])
    return FeatureSnapshotPublicationLedgerEntryV4(
        schema_version=FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION,
        ledger_sequence=cast(int, record["ledger_sequence"]),
        previous_entry_sha256=cast(str, record["previous_entry_sha256"]),
        publication_identity_sha256=cast(str, record["publication_identity_sha256"]),
        publication_replay_identity_sha256=cast(str, record["publication_replay_identity_sha256"]),
        source_ledger_sequence=cast(int, source["source_ledger_sequence"]),
        source_ledger_entry_sha256=cast(str, source["source_ledger_entry_sha256"]),
        artifact_record_id=cast(str, feature_artifact["artifact_record_id"]),
        feature_snapshot_id=cast(str, feature_artifact["feature_snapshot_id"]),
        entry_sha256=cast(str, record["entry_sha256"]),
        entry_json=_canonical_json(record),
        _source_ledger=source_ledger,
        _owned_store=store,
        _expected_owned_store_root=expected_store_root,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def _verify_record_owned_cas(
    record: Mapping[str, Any],
    store: ImmutableSourcePayloadStore,
    *,
    expected_store_root: Path,
) -> None:
    if type(store) is not ImmutableSourcePayloadStore or store.root_path != expected_store_root:
        _integrity_error("feature_publication_v4_owned_store_instance_invalid")
    artifact = cast(dict[str, Any], record["feature_artifact_binding"])
    snapshot_bytes = _owned_store_get(
        store,
        artifact["ledger_owned_artifact_content_cas_address"],
        reason="feature_publication_v4_owned_artifact_content_invalid",
    )
    binding_bytes = _owned_store_get(
        store,
        artifact["ledger_owned_artifact_binding_cas_address"],
        reason="feature_publication_v4_owned_artifact_binding_invalid",
    )
    snapshot = _parse_native_snapshot_bytes(snapshot_bytes)
    binding = _parse_json_object(
        binding_bytes,
        max_bytes=MAX_CANONICAL_FEATURE_SNAPSHOT_BYTES,
    )
    if (
        _sha256_bytes(snapshot_bytes) != artifact["artifact_serialization_sha256"]
        or len(snapshot_bytes) != artifact["artifact_serialization_byte_count"]
        or _sha256_bytes(binding_bytes) != artifact["artifact_binding_json_sha256"]
        or len(binding_bytes) != artifact["artifact_binding_json_byte_count"]
        or binding.get("schema_version") != CAS_ARTIFACT_BINDING_SCHEMA_VERSION
        or binding.get("artifact_record_id") != artifact["artifact_record_id"]
        or binding.get("artifact_binding_sha256") != artifact["artifact_binding_sha256"]
        or binding.get("feature_snapshot_id") != artifact["feature_snapshot_id"]
        or binding.get("artifact_serialization_sha256") != artifact["artifact_serialization_sha256"]
        or binding.get("artifact_serialization_byte_count")
        != artifact["artifact_serialization_byte_count"]
        or binding.get("producer_worker_id") != artifact["producer_worker_id"]
        or binding.get("symbol") != artifact["symbol"]
        or binding.get("timeframe") != artifact["timeframe"]
        or snapshot.get("feature_snapshot_id") != artifact["feature_snapshot_id"]
        or snapshot.get("symbol") != artifact["symbol"]
        or snapshot.get("timeframe") != artifact["timeframe"]
    ):
        _integrity_error("feature_publication_v4_owned_artifact_cross_binding_invalid")
    for field_name in (
        "candle_open_time",
        "candle_close_time",
        "source_event_time",
        "source_ingested_at",
        "source_available_at",
        "feature_cutoff",
        "generated_at",
        "source",
        "is_backfilled",
        "source_sequence_id",
        "raw_payload_hash",
    ):
        if artifact[field_name] != binding.get(field_name):
            _integrity_error("feature_publication_v4_owned_artifact_projection_mismatch")
    external_root = artifact["source_artifact_store_root"]
    if (
        type(external_root) is not str
        or not os.path.isabs(external_root)
        or "\x00" in external_root
        or any(component == ".." for component in Path(external_root).parts)
        or _sha256_bytes(external_root.encode("utf-8"))
        != artifact["source_artifact_store_root_sha256"]
    ):
        _integrity_error("feature_publication_v4_external_store_root_binding_invalid")
    source_content_address = _validate_address(artifact["source_artifact_content_cas_address"])
    source_binding_address = _validate_address(artifact["source_artifact_binding_cas_address"])
    if (
        source_content_address["payload_sha256"] != _sha256_bytes(snapshot_bytes)
        or source_content_address["payload_byte_count"] != len(snapshot_bytes)
        or source_binding_address["payload_sha256"] != _sha256_bytes(binding_bytes)
        or source_binding_address["payload_byte_count"] != len(binding_bytes)
    ):
        _integrity_error("feature_publication_v4_external_cas_address_binding_invalid")
    binding_cas = binding.get("cas_address")
    if type(binding_cas) is not dict:
        _integrity_error("feature_publication_v4_source_artifact_cas_projection_invalid")
    expected_absolute = (
        Path(external_root) / cast(str, source_content_address["relative_path"])
    ).as_posix()
    if (
        binding_cas.get("payload_sha256") != source_content_address["payload_sha256"]
        or binding_cas.get("payload_byte_count") != source_content_address["payload_byte_count"]
        or binding_cas.get("relative_path") != source_content_address["relative_path"]
        or binding_cas.get("absolute_path") != expected_absolute
    ):
        _integrity_error("feature_publication_v4_source_artifact_cas_projection_invalid")
    vector = _vector_binding_from_snapshot(snapshot)
    if record["feature_vector_binding"] != vector:
        _integrity_error("feature_publication_v4_vector_not_exact_artifact_projection")
    if record["derivation_binding"] != _derivation_binding(vector):
        _integrity_error("feature_publication_v4_derivation_not_exact_artifact_projection")
    _match_artifact_to_source(binding, cast(dict[str, Any], record["source_provenance_binding"]))


def _head_material(*, raw_prefix: bytes, sequence: int, entry_sha256: str) -> dict[str, object]:
    material: dict[str, object] = {
        "schema_version": FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_SCHEMA_VERSION,
        "ledger_schema_version": FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION,
        "ledger_filename": FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME,
        "ledger_sequence": sequence,
        "ledger_byte_count": len(raw_prefix),
        "ledger_sha256": _sha256_bytes(raw_prefix),
        "entry_sha256": entry_sha256,
    }
    material["head_sha256"] = _stable_sha256(material)
    return material


def _validate_head(raw: bytes) -> dict[str, Any]:
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        _integrity_error("feature_publication_v4_head_framing_invalid")
    head = _parse_json_object(raw[:-1], max_bytes=MAX_HEAD_BYTES)
    if frozenset(head) != _HEAD_FIELDS:
        _integrity_error("feature_publication_v4_head_fields_invalid")
    if (
        head["schema_version"] != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_SCHEMA_VERSION
        or head["ledger_schema_version"] != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION
        or head["ledger_filename"] != FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME
        or type(head["ledger_sequence"]) is not int
        or head["ledger_sequence"] <= 0
        or type(head["ledger_byte_count"]) is not int
        or head["ledger_byte_count"] <= 0
        or not _is_sha256(head["ledger_sha256"])
        or not _is_sha256(head["entry_sha256"])
        or not _is_sha256(head["head_sha256"])
    ):
        _integrity_error("feature_publication_v4_head_contract_invalid")
    material = {key: item for key, item in head.items() if key != "head_sha256"}
    if head["head_sha256"] != _stable_sha256(material):
        _integrity_error("feature_publication_v4_head_sha256_invalid")
    return head


@dataclass(frozen=True, slots=True)
class _DirectoryBinding:
    parent_fd: int
    name: str
    child_fd: int
    identity: tuple[int, int]


class _VerifiedRootChain:
    """Descriptor-retained lexical root chain with no-follow verification."""

    __slots__ = ("_bindings", "_closed", "_descriptors", "path")

    def __init__(self, path: Path, anchor_fd: int) -> None:
        self.path = path
        self._descriptors = [anchor_fd]
        self._bindings: list[_DirectoryBinding] = []
        self._closed = False

    @property
    def final_fd(self) -> int:
        if self._closed:
            _integrity_error("feature_publication_v4_root_chain_closed")
        return self._descriptors[-1]

    @property
    def identity(self) -> tuple[int, int]:
        details = os.fstat(self.final_fd)
        return (int(details.st_dev), int(details.st_ino))

    def append(self, name: str, *, create: bool) -> None:
        if not name or name in {".", ".."} or "/" in name or "\x00" in name:
            _validation_error("feature_publication_v4_root_component_invalid")
        parent_fd = self.final_fd
        if create:
            try:
                os.mkdir(name, mode=_PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
            except FileExistsError:
                pass
            except OSError as exc:
                _durability_error("feature_publication_v4_root_create_failed", cause=exc)
            else:
                _fsync_directory_fd(parent_fd)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        try:
            child_fd = os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise FeatureSnapshotPublicationLedgerV4IntegrityError(
                "feature_publication_v4_root_ancestor_or_final_open_failed"
            ) from exc
        try:
            descriptor_stat = os.fstat(child_fd)
            path_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            identity = (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
            if (
                not stat.S_ISDIR(descriptor_stat.st_mode)
                or not stat.S_ISDIR(path_stat.st_mode)
                or identity != (int(path_stat.st_dev), int(path_stat.st_ino))
            ):
                _integrity_error("feature_publication_v4_root_directory_binding_invalid")
        except BaseException:
            os.close(child_fd)
            raise
        self._descriptors.append(child_fd)
        self._bindings.append(_DirectoryBinding(parent_fd, name, child_fd, identity))

    def require_private_final(self) -> None:
        if not self._bindings:
            _integrity_error("feature_publication_v4_root_binding_missing")
        details = os.fstat(self.final_fd)
        final = self._bindings[-1]
        path_details = os.stat(final.name, dir_fd=final.parent_fd, follow_symlinks=False)
        if (
            details.st_uid != os.geteuid()
            or path_details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) != _PRIVATE_DIRECTORY_MODE
            or stat.S_IMODE(path_details.st_mode) != _PRIVATE_DIRECTORY_MODE
        ):
            _integrity_error("feature_publication_v4_root_private_owner_mode_required")

    def verify(self) -> None:
        if self._closed:
            _integrity_error("feature_publication_v4_root_chain_closed")
        for binding in self._bindings:
            try:
                descriptor_stat = os.fstat(binding.child_fd)
                path_stat = os.stat(
                    binding.name,
                    dir_fd=binding.parent_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise FeatureSnapshotPublicationLedgerV4IntegrityError(
                    "feature_publication_v4_root_binding_missing"
                ) from exc
            if (
                not stat.S_ISDIR(descriptor_stat.st_mode)
                or not stat.S_ISDIR(path_stat.st_mode)
                or (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino)) != binding.identity
                or (int(path_stat.st_dev), int(path_stat.st_ino)) != binding.identity
            ):
                _integrity_error("feature_publication_v4_root_replaced")
        self.require_private_final()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for descriptor in reversed(self._descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self._descriptors.clear()
        self._bindings.clear()


def _lexical_absolute_root(path: Path) -> Path:
    if not isinstance(path, Path):
        _validation_error("feature_publication_v4_root_exact_path_required")
    raw = os.fspath(path)
    if (
        "\x00" in raw
        or not os.path.isabs(raw)
        or any(component == ".." for component in Path(raw).parts)
    ):
        _validation_error("feature_publication_v4_root_lexical_absolute_required")
    exact = Path(raw)
    if (
        exact == Path(exact.anchor)
        or exact.name in {"", ".", ".."}
        or len(exact.parts) - 1 > _MAX_PATH_COMPONENTS
    ):
        _validation_error("feature_publication_v4_root_path_invalid")
    return exact


def _open_verified_root(path: Path, *, create_final: bool) -> _VerifiedRootChain:
    exact = _lexical_absolute_root(path)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        anchor_fd = os.open(exact.anchor, flags)
    except OSError as exc:
        raise FeatureSnapshotPublicationLedgerV4IntegrityError(
            "feature_publication_v4_root_anchor_open_failed"
        ) from exc
    chain = _VerifiedRootChain(exact, anchor_fd)
    try:
        components = exact.parts[1:]
        for index, component in enumerate(components):
            chain.append(
                component,
                create=create_final and index == len(components) - 1,
            )
        chain.verify()
        return chain
    except BaseException:
        chain.close()
        raise


def _validate_regular_file(
    root_fd: int,
    name: str,
    descriptor: int,
    *,
    reason: str,
) -> os.stat_result:
    try:
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
    except OSError as exc:
        raise FeatureSnapshotPublicationLedgerV4IntegrityError(reason) from exc
    if (
        not stat.S_ISREG(descriptor_stat.st_mode)
        or not stat.S_ISREG(path_stat.st_mode)
        or descriptor_stat.st_nlink != 1
        or path_stat.st_nlink != 1
        or descriptor_stat.st_uid != os.geteuid()
        or path_stat.st_uid != os.geteuid()
        or stat.S_IMODE(descriptor_stat.st_mode) != _PRIVATE_FILE_MODE
        or stat.S_IMODE(path_stat.st_mode) != _PRIVATE_FILE_MODE
        or (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
        != (int(path_stat.st_dev), int(path_stat.st_ino))
    ):
        _integrity_error(reason)
    return descriptor_stat


def _read_regular_file(
    root: _VerifiedRootChain,
    name: str,
    *,
    max_bytes: int,
    required: bool,
) -> bytes | None:
    root.verify()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=root.final_fd)
    except FileNotFoundError:
        if required:
            _integrity_error("feature_publication_v4_file_missing")
        return None
    except OSError as exc:
        raise FeatureSnapshotPublicationLedgerV4IntegrityError(
            "feature_publication_v4_file_open_failed"
        ) from exc
    try:
        details = _validate_regular_file(
            root.final_fd,
            name,
            descriptor,
            reason="feature_publication_v4_file_identity_invalid",
        )
        if details.st_size < 0 or details.st_size > max_bytes:
            _integrity_error("feature_publication_v4_file_size_invalid")
        initial_change = (int(details.st_mtime_ns), int(details.st_ctime_ns))
        chunks: list[bytes] = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                _integrity_error("feature_publication_v4_file_truncated_during_read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            _integrity_error("feature_publication_v4_file_grew_during_read")
        final_details = _validate_regular_file(
            root.final_fd,
            name,
            descriptor,
            reason="feature_publication_v4_file_changed_during_read",
        )
        raw = b"".join(chunks)
        if (
            len(raw) != details.st_size
            or final_details.st_size != details.st_size
            or (int(final_details.st_mtime_ns), int(final_details.st_ctime_ns)) != initial_change
        ):
            _integrity_error("feature_publication_v4_file_changed_during_read")
        root.verify()
        return raw
    except OSError as exc:
        raise FeatureSnapshotPublicationLedgerV4IntegrityError(
            "feature_publication_v4_file_read_failed"
        ) from exc
    finally:
        os.close(descriptor)


def _load_state(
    root: _VerifiedRootChain,
    store: ImmutableSourcePayloadStore,
    source_ledger: TrainerSourceProvenanceLedgerV4,
    *,
    expected_store_root: Path,
) -> _LedgerState:
    raw = (
        _read_regular_file(
            root,
            FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME,
            max_bytes=MAX_LEDGER_BYTES,
            required=False,
        )
        or b""
    )
    head_raw = _read_regular_file(
        root,
        FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_FILENAME,
        max_bytes=MAX_HEAD_BYTES,
        required=False,
    )
    if not raw:
        if head_raw is not None:
            _integrity_error("feature_publication_v4_head_without_ledger")
        return _LedgerState(b"", (), (), 0)
    if not raw.endswith(b"\n"):
        _integrity_error("feature_publication_v4_ledger_truncated_or_partial_tail")
    lines = raw.splitlines(keepends=True)
    if not lines or len(lines) > MAX_LEDGER_ENTRIES:
        _integrity_error("feature_publication_v4_ledger_entry_count_invalid")
    records: list[dict[str, Any]] = []
    offsets: list[int] = []
    offset = 0
    previous = FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_GENESIS_SHA256
    for sequence, framed in enumerate(lines, start=1):
        if not framed.endswith(b"\n") or framed == b"\n" or b"\r" in framed:
            _integrity_error("feature_publication_v4_ledger_framing_invalid")
        record = _parse_entry_line(framed[:-1])
        _verify_source_binding(record, source_ledger)
        _verify_record_owned_cas(record, store, expected_store_root=expected_store_root)
        if record["ledger_sequence"] != sequence or record["previous_entry_sha256"] != previous:
            _integrity_error("feature_publication_v4_hash_chain_invalid")
        records.append(record)
        previous = cast(str, record["entry_sha256"])
        offset += len(framed)
        offsets.append(offset)
    if head_raw is None:
        if len(records) != 1:
            _integrity_error("feature_publication_v4_durable_head_missing")
        return _LedgerState(raw, tuple(records), tuple(offsets), 0)
    head = _validate_head(head_raw)
    committed = cast(int, head["ledger_sequence"])
    if committed > len(records) or len(records) - committed > 1:
        _integrity_error("feature_publication_v4_head_sequence_invalid")
    prefix_end = offsets[committed - 1]
    prefix = raw[:prefix_end]
    if (
        head["ledger_byte_count"] != len(prefix)
        or head["ledger_sha256"] != _sha256_bytes(prefix)
        or head["entry_sha256"] != records[committed - 1]["entry_sha256"]
    ):
        _integrity_error("feature_publication_v4_head_ledger_binding_invalid")
    return _LedgerState(raw, tuple(records), tuple(offsets), committed)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    written = 0
    while written < len(payload):
        count = os.write(descriptor, view[written:])
        if count <= 0:
            _durability_error("feature_publication_v4_write_made_no_progress")
        written += count


def _fsync_directory_fd(descriptor: int) -> None:
    try:
        os.fsync(descriptor)
    except OSError as exc:
        _durability_error("feature_publication_v4_directory_fsync_failed", cause=exc)


def _fsync_ledger(root: _VerifiedRootChain) -> None:
    root.verify()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(
            FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME,
            flags,
            dir_fd=root.final_fd,
        )
        try:
            _validate_regular_file(
                root.final_fd,
                FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME,
                descriptor,
                reason="feature_publication_v4_ledger_identity_invalid",
            )
            os.fsync(descriptor)
            _validate_regular_file(
                root.final_fd,
                FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME,
                descriptor,
                reason="feature_publication_v4_ledger_changed_during_fsync",
            )
        finally:
            os.close(descriptor)
        root.verify()
    except FeatureSnapshotPublicationLedgerV4Error:
        raise
    except OSError as exc:
        _durability_error("feature_publication_v4_ledger_fsync_failed", cause=exc)


def _append_fsync(root: _VerifiedRootChain, payload: bytes) -> None:
    root.verify()
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(
            FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME,
            flags,
            _PRIVATE_FILE_MODE,
            dir_fd=root.final_fd,
        )
        try:
            _validate_regular_file(
                root.final_fd,
                FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME,
                descriptor,
                reason="feature_publication_v4_ledger_identity_invalid",
            )
            with os.fdopen(descriptor, "ab", buffering=0, closefd=False) as stream:
                _write_all(stream.fileno(), payload)
                stream.flush()
                os.fsync(stream.fileno())
            _validate_regular_file(
                root.final_fd,
                FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME,
                descriptor,
                reason="feature_publication_v4_ledger_changed_during_append",
            )
        finally:
            os.close(descriptor)
        _fsync_directory_fd(root.final_fd)
        root.verify()
    except FeatureSnapshotPublicationLedgerV4Error:
        raise
    except OSError as exc:
        _durability_error("feature_publication_v4_ledger_append_or_fsync_failed", cause=exc)


def _write_head_atomic(root: _VerifiedRootChain, head: dict[str, object]) -> None:
    root.verify()
    payload = _canonical_json(head, max_bytes=MAX_HEAD_BYTES).encode("ascii") + b"\n"
    temporary = (
        f".{FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_FILENAME}."
        f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    replaced = False
    try:
        descriptor = os.open(temporary, flags, _PRIVATE_FILE_MODE, dir_fd=root.final_fd)
        try:
            _validate_regular_file(
                root.final_fd,
                temporary,
                descriptor,
                reason="feature_publication_v4_head_temp_identity_invalid",
            )
            with os.fdopen(descriptor, "wb", buffering=0, closefd=False) as stream:
                _write_all(stream.fileno(), payload)
                stream.flush()
                os.fsync(stream.fileno())
            _validate_regular_file(
                root.final_fd,
                temporary,
                descriptor,
                reason="feature_publication_v4_head_temp_changed",
            )
        finally:
            os.close(descriptor)
        root.verify()
        os.replace(
            temporary,
            FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_FILENAME,
            src_dir_fd=root.final_fd,
            dst_dir_fd=root.final_fd,
        )
        replaced = True
        _fsync_directory_fd(root.final_fd)
        _read_regular_file(
            root,
            FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_FILENAME,
            max_bytes=MAX_HEAD_BYTES,
            required=True,
        )
        root.verify()
    except FeatureSnapshotPublicationLedgerV4Error:
        raise
    except OSError as exc:
        _durability_error("feature_publication_v4_head_publish_failed", cause=exc)
    finally:
        if not replaced:
            try:
                os.unlink(temporary, dir_fd=root.final_fd)
            except (FileNotFoundError, OSError):
                pass


class FeatureSnapshotPublicationLedgerV4:
    """Private, unwired P0-D ledger rooted at an operator-supplied directory."""

    def __init__(
        self,
        root: Path,
        *,
        source_provenance_ledger: TrainerSourceProvenanceLedgerV4,
    ) -> None:
        self.root = _lexical_absolute_root(root)
        if type(source_provenance_ledger) is not TrainerSourceProvenanceLedgerV4:
            _validation_error("feature_publication_v4_exact_p0c_ledger_required")
        self.source_provenance_ledger = source_provenance_ledger
        self.path = self.root / FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME
        self.head_path = self.root / FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_FILENAME
        self.lock_path = self.root / FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_LOCK_FILENAME
        self.store_root = (
            self.root / FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_ROOT_RELATIVE_PATH
        )
        self._root_identity: tuple[int, int] | None = None
        self._root_identity_lock = threading.Lock()

    def _pin_root_identity(self, root: _VerifiedRootChain) -> None:
        root.verify()
        identity = root.identity
        with self._root_identity_lock:
            if self._root_identity is None:
                self._root_identity = identity
            elif self._root_identity != identity:
                _integrity_error("feature_publication_v4_root_instance_replaced")

    def _open_owned_store(self, root: _VerifiedRootChain) -> ImmutableSourcePayloadStore:
        root.verify()
        try:
            store = ImmutableSourcePayloadStore(self.store_root)
        except SourcePayloadIntegrityError as exc:
            raise FeatureSnapshotPublicationLedgerV4IntegrityError(
                "feature_publication_v4_owned_cas_root_integrity_invalid"
            ) from exc
        except SourcePayloadStoreError as exc:
            raise FeatureSnapshotPublicationLedgerV4DurabilityError(
                "feature_publication_v4_owned_cas_root_open_failed"
            ) from exc
        root.verify()
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(
                FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_ROOT_RELATIVE_PATH,
                flags,
                dir_fd=root.final_fd,
            )
        except OSError as exc:
            raise FeatureSnapshotPublicationLedgerV4IntegrityError(
                "feature_publication_v4_owned_cas_root_binding_missing"
            ) from exc
        try:
            descriptor_stat = os.fstat(descriptor)
            path_stat = os.stat(
                FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_ROOT_RELATIVE_PATH,
                dir_fd=root.final_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(descriptor_stat.st_mode)
                or not stat.S_ISDIR(path_stat.st_mode)
                or descriptor_stat.st_uid != os.geteuid()
                or path_stat.st_uid != os.geteuid()
                or stat.S_IMODE(descriptor_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
                or stat.S_IMODE(path_stat.st_mode) != _PRIVATE_DIRECTORY_MODE
                or (int(descriptor_stat.st_dev), int(descriptor_stat.st_ino))
                != (int(path_stat.st_dev), int(path_stat.st_ino))
            ):
                _integrity_error("feature_publication_v4_owned_cas_root_binding_invalid")
        finally:
            os.close(descriptor)
        if store.root_path != self.store_root:
            _integrity_error("feature_publication_v4_owned_cas_root_path_invalid")
        root.verify()
        return store

    @contextmanager
    def _exclusive_lock(self) -> Iterator[_VerifiedRootChain]:
        root = _open_verified_root(self.root, create_final=True)
        try:
            self._pin_root_identity(root)
        except BaseException:
            root.close()
            raise
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        created = False
        try:
            descriptor = os.open(
                FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_LOCK_FILENAME,
                flags,
                _PRIVATE_FILE_MODE,
                dir_fd=root.final_fd,
            )
            created = True
        except FileExistsError:
            try:
                descriptor = os.open(
                    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_LOCK_FILENAME,
                    os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=root.final_fd,
                )
            except OSError as exc:
                root.close()
                _durability_error("feature_publication_v4_lock_open_failed", cause=exc)
        except OSError as exc:
            root.close()
            _durability_error("feature_publication_v4_lock_open_failed", cause=exc)
        try:
            if created:
                _fsync_directory_fd(root.final_fd)
            _validate_regular_file(
                root.final_fd,
                FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_LOCK_FILENAME,
                descriptor,
                reason="feature_publication_v4_lock_identity_invalid",
            )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            except OSError as exc:
                _durability_error("feature_publication_v4_lock_acquire_failed", cause=exc)
            root.verify()
            _validate_regular_file(
                root.final_fd,
                FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_LOCK_FILENAME,
                descriptor,
                reason="feature_publication_v4_lock_changed",
            )
            yield root
            root.verify()
            _validate_regular_file(
                root.final_fd,
                FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_LOCK_FILENAME,
                descriptor,
                reason="feature_publication_v4_lock_changed",
            )
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
                root.close()

    def append_incomplete_artifact_publication(
        self,
        artifact: FeatureSnapshotCasArtifact,
        *,
        source_ledger_sequence: int,
        source_ledger_entry_sha256: str,
        ledger_clock: Callable[[], datetime] | object = lambda: datetime.now(UTC),
    ) -> FeatureSnapshotPublicationAppendResultV4:
        """Append one exact, necessarily non-consumable P0-C/artifact binding."""

        with self._exclusive_lock() as root:
            store = self._open_owned_store(root)
            source_entry = _fresh_source_entry(
                self.source_provenance_ledger,
                sequence=source_ledger_sequence,
                entry_sha256=source_ledger_entry_sha256,
            )
            source_binding = _source_binding_from_entry(
                self.source_provenance_ledger,
                source_entry,
            )
            artifact_binding, vector, derivation, raw_artifact_binding = _artifact_material(
                artifact,
                store,
            )
            _match_artifact_to_source(raw_artifact_binding, source_binding)
            identity = _publication_identity(source_binding, artifact_binding)
            recorded_at = _sample_ledger_clock(
                ledger_clock,
                not_before=(
                    cast(str, source_binding["source_ledger_recorded_at"]),
                    cast(str, raw_artifact_binding["generated_at"]),
                ),
            )
            temporal = _temporal_binding(
                artifact_binding=raw_artifact_binding,
                source_binding=source_binding,
                ledger_recorded_at=recorded_at,
            )
            state = _load_state(
                root,
                store,
                self.source_provenance_ledger,
                expected_store_root=self.store_root,
            )
            candidate_record_for_replay: dict[str, object] = {
                "schema_version": "feature_snapshot_publication_replay_material_v4",
                "publication_identity_sha256": identity,
                "ledger_owned_store": _owned_store_material(),
                "source_provenance_binding": source_binding,
                "feature_artifact_binding": artifact_binding,
                "feature_vector_binding": vector,
                "derivation_binding": derivation,
                "temporal_binding_without_ledger_record_clock": {
                    key: item
                    for key, item in temporal.items()
                    if key not in {"ledger_recorded_at", "temporal_binding_sha256"}
                },
                "source_scope_incompleteness_reasons": list(SOURCE_SCOPE_INCOMPLETENESS_REASONS),
                **{name: False for name in _DOWNSTREAM_FLAG_FIELDS},
            }
            replay_identity = _stable_sha256(candidate_record_for_replay)
            for index, existing in enumerate(state.records):
                existing_source = cast(dict[str, Any], existing["source_provenance_binding"])
                if (
                    existing_source["source_ledger_entry_sha256"]
                    != source_binding["source_ledger_entry_sha256"]
                ):
                    continue
                if (
                    existing["publication_identity_sha256"] != identity
                    or existing["publication_replay_identity_sha256"] != replay_identity
                ):
                    _conflict_error("feature_publication_v4_conflicting_source_publication")
                if index >= state.committed_count:
                    return self._recover_pending(root, store, state, existing)
                return self._finish_existing(
                    root,
                    store,
                    existing,
                    disposition="EXACT_REPLAY",
                )
            if state.pending_record is not None:
                _conflict_error("feature_publication_v4_uncommitted_tail_conflict")
            # Re-read P0-C after all artifact/vector work so a selected entry
            # cannot disappear or coherently change between lookup and append.
            _verify_source_binding(
                {"source_provenance_binding": source_binding},
                self.source_provenance_ledger,
            )
            sequence = len(state.records) + 1
            previous = (
                FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_GENESIS_SHA256
                if not state.records
                else cast(str, state.records[-1]["entry_sha256"])
            )
            record: dict[str, object] = {
                "schema_version": FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION,
                "evidence_classification": (
                    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_EVIDENCE_CLASSIFICATION
                ),
                "downstream_status": FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_DOWNSTREAM_STATUS,
                "ledger_namespace": FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_NAMESPACE,
                "ledger_sequence": sequence,
                "previous_entry_sha256": previous,
                "publication_identity_sha256": identity,
                "publication_replay_identity_sha256": replay_identity,
                "ledger_recorded_at": recorded_at,
                "ledger_owned_store": _owned_store_material(),
                "source_provenance_binding": source_binding,
                "feature_artifact_binding": artifact_binding,
                "feature_vector_binding": vector,
                "derivation_binding": derivation,
                "temporal_binding": temporal,
                "source_scope_incompleteness_reasons": list(SOURCE_SCOPE_INCOMPLETENESS_REASONS),
                **{name: False for name in _DOWNSTREAM_FLAG_FIELDS},
            }
            record["entry_sha256"] = _stable_sha256(record)
            entry_json = _canonical_json(record)
            validated = _parse_entry_line(entry_json.encode("ascii"))
            _verify_source_binding(validated, self.source_provenance_ledger)
            _verify_record_owned_cas(
                validated,
                store,
                expected_store_root=self.store_root,
            )
            framed = entry_json.encode("ascii") + b"\n"
            if len(state.raw_bytes) + len(framed) > MAX_LEDGER_BYTES:
                _durability_error("feature_publication_v4_ledger_size_limit_exceeded")
            _append_fsync(root, framed)
            committed_raw = state.raw_bytes + framed
            _write_head_atomic(
                root,
                _head_material(
                    raw_prefix=committed_raw,
                    sequence=sequence,
                    entry_sha256=cast(str, record["entry_sha256"]),
                ),
            )
            readback = self._postcommit_readback(
                root,
                store,
                expected_entry_json=entry_json,
                expected_sequence=sequence,
            )
            # The external artifact is freshly checked again after durable
            # readback.  Future ledger reads use the independently pinned CAS.
            try:
                final_external_binding = artifact.artifact_binding
            except FeatureSnapshotPublicationError as exc:
                raise FeatureSnapshotPublicationLedgerV4IntegrityError(
                    "feature_publication_v4_external_artifact_postcommit_readback_failed"
                ) from exc
            if final_external_binding != raw_artifact_binding:
                _integrity_error("feature_publication_v4_external_artifact_postcommit_changed")
            return self._result(readback, store, disposition="APPENDED")

    def _postcommit_readback(
        self,
        root: _VerifiedRootChain,
        store: ImmutableSourcePayloadStore,
        *,
        expected_entry_json: str,
        expected_sequence: int,
    ) -> dict[str, Any]:
        state = _load_state(
            root,
            store,
            self.source_provenance_ledger,
            expected_store_root=self.store_root,
        )
        if (
            state.pending_record is not None
            or state.committed_count != len(state.records)
            or state.committed_count != expected_sequence
            or not state.records
            or _canonical_json(state.records[-1]) != expected_entry_json
        ):
            _durability_error("feature_publication_v4_postcommit_readback_mismatch")
        return state.records[-1]

    def _recover_pending(
        self,
        root: _VerifiedRootChain,
        store: ImmutableSourcePayloadStore,
        state: _LedgerState,
        pending: dict[str, Any],
    ) -> FeatureSnapshotPublicationAppendResultV4:
        if state.pending_record is not pending or len(state.records) != state.committed_count + 1:
            _integrity_error("feature_publication_v4_pending_tail_shape_invalid")
        _verify_source_binding(pending, self.source_provenance_ledger)
        _verify_record_owned_cas(pending, store, expected_store_root=self.store_root)
        _fsync_ledger(root)
        _fsync_directory_fd(root.final_fd)
        _write_head_atomic(
            root,
            _head_material(
                raw_prefix=state.raw_bytes,
                sequence=len(state.records),
                entry_sha256=cast(str, pending["entry_sha256"]),
            ),
        )
        entry_json = _canonical_json(pending)
        readback = self._postcommit_readback(
            root,
            store,
            expected_entry_json=entry_json,
            expected_sequence=len(state.records),
        )
        return self._result(
            readback,
            store,
            disposition="RECOVERED_EXACT_PENDING_APPEND",
        )

    def _finish_existing(
        self,
        root: _VerifiedRootChain,
        store: ImmutableSourcePayloadStore,
        existing: dict[str, Any],
        *,
        disposition: str,
    ) -> FeatureSnapshotPublicationAppendResultV4:
        state = _load_state(
            root,
            store,
            self.source_provenance_ledger,
            expected_store_root=self.store_root,
        )
        if state.pending_record is not None or not state.records:
            _integrity_error("feature_publication_v4_exact_replay_state_invalid")
        _fsync_ledger(root)
        _write_head_atomic(
            root,
            _head_material(
                raw_prefix=state.raw_bytes,
                sequence=len(state.records),
                entry_sha256=cast(str, state.records[-1]["entry_sha256"]),
            ),
        )
        self._postcommit_readback(
            root,
            store,
            expected_entry_json=_canonical_json(state.records[-1]),
            expected_sequence=len(state.records),
        )
        return self._result(existing, store, disposition=disposition)

    def _result(
        self,
        record: dict[str, Any],
        store: ImmutableSourcePayloadStore,
        *,
        disposition: str,
    ) -> FeatureSnapshotPublicationAppendResultV4:
        return FeatureSnapshotPublicationAppendResultV4(
            entry=_artifact(
                record,
                source_ledger=self.source_provenance_ledger,
                store=store,
                expected_store_root=self.store_root,
            ),
            disposition=disposition,
            _construction_token=_CONSTRUCTION_TOKEN,
        )

    def read_entries(self) -> tuple[FeatureSnapshotPublicationLedgerEntryV4, ...]:
        """Freshly validate the full committed chain, P0-C entries, and owned CAS."""

        with self._exclusive_lock() as root:
            store = self._open_owned_store(root)
            state = _load_state(
                root,
                store,
                self.source_provenance_ledger,
                expected_store_root=self.store_root,
            )
            if state.pending_record is not None:
                _integrity_error("feature_publication_v4_uncommitted_tail_present")
            return tuple(
                _artifact(
                    record,
                    source_ledger=self.source_provenance_ledger,
                    store=store,
                    expected_store_root=self.store_root,
                )
                for record in state.records
            )


__all__ = [
    "FEATURE_ARTIFACT_BINDING_SCHEMA_VERSION",
    "FEATURE_DERIVATION_BINDING_SCHEMA_VERSION",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_DOWNSTREAM_STATUS",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_EVIDENCE_CLASSIFICATION",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_GENESIS_SHA256",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_FILENAME",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_SCHEMA_VERSION",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_LOCK_FILENAME",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_NAMESPACE",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_NAMESPACE",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_ROOT_RELATIVE_PATH",
    "FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_STORE_SCHEMA_VERSION",
    "FEATURE_SOURCE_PROVENANCE_BINDING_SCHEMA_VERSION",
    "FEATURE_TEMPORAL_BINDING_SCHEMA_VERSION",
    "FEATURE_VECTOR_BINDING_SCHEMA_VERSION",
    "MAX_LEDGER_BYTES",
    "MAX_LEDGER_ENTRIES",
    "MAX_LEDGER_ENTRY_BYTES",
    "SOURCE_SCOPE_INCOMPLETENESS_REASONS",
    "UNRESOLVED_SOURCE_LABEL",
    "FeatureSnapshotPublicationAppendResultV4",
    "FeatureSnapshotPublicationLedgerEntryV4",
    "FeatureSnapshotPublicationLedgerV4",
    "FeatureSnapshotPublicationLedgerV4ConflictError",
    "FeatureSnapshotPublicationLedgerV4DurabilityError",
    "FeatureSnapshotPublicationLedgerV4Error",
    "FeatureSnapshotPublicationLedgerV4IntegrityError",
    "FeatureSnapshotPublicationLedgerV4ValidationError",
]
