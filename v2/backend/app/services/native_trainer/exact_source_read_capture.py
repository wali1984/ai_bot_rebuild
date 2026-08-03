"""Exact, nonconsumable source-read capture for trainer provenance.

This module is an intentionally unwired boundary between a future atomic
source reader and the durable feature-snapshot ledger.  It accepts the exact
``bytes`` returned by that reader, validates typed source identity and causal
clocks, stores the bytes in :class:`ImmutableSourcePayloadStore`, performs a
fresh exact readback, and emits a deliberately ledger-incompatible future
source-adapter candidate after an immutable capture binding.

The boundary deliberately does *not* read Redis, parse source payloads, sample
wall clocks, append to the durable ledger, publish a feature snapshot, or
admit a trainer input.  In particular:

* ``consumer_observed_at`` is a caller-supplied source-read clock.  It is never
  synthesized from CAS publication and is not a postcommit clock.
* source-specific adapters must prove that producer clocks and finality fields
  were extracted from the exact captured bytes (or atomic transport metadata);
  this generic byte boundary cannot make that schema-specific claim.
* the future-adapter candidate has its own non-ledger schema, no receipt hash
  or v3 read/finality-evidence objects, and is mechanically rejected by the
  existing ledger.  A source-specific adapter must attest the exact source
  schema before separately building any ledger-v3 receipt.

Equal payload bytes retain the same payload content address.  Equal complete
capture inputs retain the same record ID.  The binding contains the canonical
absolute CAS path, so its bytes/address are stable only within the same
canonical CAS root.  Existing content is accepted only after the immutable
store's durable exact-byte verification; address collisions fail closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from typing import Any, NoReturn

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    SOURCE_READ_RECEIPT_SCHEMA_VERSION,
    FeatureSnapshotValidationError,
    canonical_json,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    SOURCE_PAYLOAD_STORE_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)

EXACT_SOURCE_CAPTURE_SCHEMA_VERSION = "trainer_exact_source_read_capture_v1"
EXACT_SOURCE_CAPTURE_IDENTITY_SCHEMA_VERSION = "trainer_exact_source_read_capture_identity_v1"
EXACT_SOURCE_CAPTURE_ADDRESS_SCHEMA_VERSION = "trainer_exact_source_read_capture_cas_address_v1"
SOURCE_ADAPTER_CANDIDATE_SCHEMA_VERSION = "trainer_source_specific_adapter_candidate_v1"
SOURCE_ADAPTER_CANDIDATE_IDENTITY_SCHEMA_VERSION = (
    "trainer_source_specific_adapter_candidate_identity_v1"
)
SOURCE_ADAPTER_CANDIDATE_EVIDENCE_CLASSIFICATION = (
    "FUTURE_SOURCE_ADAPTER_INPUT_ONLY_NONCONSUMABLE_NOT_LEDGER_RECEIPT"
)
SOURCE_ADAPTER_ATTESTATION_STATUS = "SOURCE_SPECIFIC_ADAPTER_ATTESTATION_REQUIRED"
SOURCE_ADAPTER_CLOCK_STATUS = "DECLARED_CLOCKS_NOT_SOURCE_SCHEMA_ATTESTED"
EXACT_SOURCE_CAPTURE_EVIDENCE_CLASSIFICATION = (
    "EXACT_SOURCE_BYTES_AND_RECEIPT_CANDIDATE_ONLY_NONCONSUMABLE"
)
EXACT_SOURCE_CAPTURE_RETRY_SEMANTICS = (
    "STABLE_PAYLOAD_ADDRESS_FOR_EQUAL_BYTES;"
    "STABLE_RECORD_ID_FOR_EQUAL_COMPLETE_CAPTURE_INPUTS;"
    "STABLE_BINDING_ADDRESS_WITHIN_SAME_CANONICAL_CAS_ROOT"
)
EXACT_SOURCE_CAPTURE_COLLISION_SEMANTICS = (
    "EXISTING_ADDRESS_ACCEPTED_ONLY_AFTER_DURABLE_EXACT_BYTE_VERIFICATION;" "MISMATCH_FAILS_CLOSED"
)
EXACT_SOURCE_CAPTURE_DOWNSTREAM_STATUS = (
    "UNWIRED_REQUIRES_SOURCE_SCHEMA_ADAPTER_AND_DURABLE_LEDGER_APPEND_READBACK"
)

SOURCE_KIND_OHLCV_CLOSED_INTERVAL = "OHLCV_CLOSED_INTERVAL"
SOURCE_KIND_ORDERBOOK_SNAPSHOT = "ORDERBOOK_VERSIONED_SNAPSHOT"
SOURCE_KIND_FUNDING_SNAPSHOT = "FUNDING_VERSIONED_SNAPSHOT"
SOURCE_KIND_OPEN_INTEREST_SNAPSHOT = "OPEN_INTEREST_VERSIONED_SNAPSHOT"
SOURCE_KIND_LIQUIDATION_EVENT = "LIQUIDATION_IMMUTABLE_EVENT"
SOURCE_KIND_LIQUIDATION_AGGREGATE = "LIQUIDATION_VERSIONED_AGGREGATE"
SOURCE_KIND_PAPER_POSITION_STATE = "PAPER_POSITION_VERSIONED_STATE"

EXACT_SOURCE_KINDS = frozenset(
    {
        SOURCE_KIND_OHLCV_CLOSED_INTERVAL,
        SOURCE_KIND_ORDERBOOK_SNAPSHOT,
        SOURCE_KIND_FUNDING_SNAPSHOT,
        SOURCE_KIND_OPEN_INTEREST_SNAPSHOT,
        SOURCE_KIND_LIQUIDATION_EVENT,
        SOURCE_KIND_LIQUIDATION_AGGREGATE,
        SOURCE_KIND_PAPER_POSITION_STATE,
    }
)

_SOURCE_KIND_FINALITY_TYPES = {
    SOURCE_KIND_OHLCV_CLOSED_INTERVAL: "CLOSED_INTERVAL",
    SOURCE_KIND_ORDERBOOK_SNAPSHOT: "VERSIONED_SNAPSHOT",
    SOURCE_KIND_FUNDING_SNAPSHOT: "VERSIONED_SNAPSHOT",
    SOURCE_KIND_OPEN_INTEREST_SNAPSHOT: "VERSIONED_SNAPSHOT",
    SOURCE_KIND_LIQUIDATION_EVENT: "IMMUTABLE_EVENT",
    SOURCE_KIND_LIQUIDATION_AGGREGATE: "VERSIONED_SNAPSHOT",
    SOURCE_KIND_PAPER_POSITION_STATE: "VERSIONED_SNAPSHOT",
}

_SOURCE_KIND_PAYLOAD_TYPES = {
    SOURCE_KIND_OHLCV_CLOSED_INTERVAL: "EXACT_OHLCV_SOURCE_BYTES",
    SOURCE_KIND_ORDERBOOK_SNAPSHOT: "EXACT_ORDERBOOK_SOURCE_BYTES",
    SOURCE_KIND_FUNDING_SNAPSHOT: "EXACT_FUNDING_SOURCE_BYTES",
    SOURCE_KIND_OPEN_INTEREST_SNAPSHOT: "EXACT_OPEN_INTEREST_SOURCE_BYTES",
    SOURCE_KIND_LIQUIDATION_EVENT: "EXACT_LIQUIDATION_EVENT_SOURCE_BYTES",
    SOURCE_KIND_LIQUIDATION_AGGREGATE: ("EXACT_LIQUIDATION_AGGREGATE_SOURCE_BYTES"),
    SOURCE_KIND_PAPER_POSITION_STATE: "EXACT_PAPER_POSITION_STATE_BYTES",
}

_READ_LOCATOR_TYPES = frozenset(
    {
        "FILE_CONTENT_ADDRESS",
        "HTTP_RESPONSE_DIGEST",
        "IN_MEMORY_IMMUTABLE_OBJECT",
        "REDIS_VERSIONED_VALUE",
        "SQLITE_IMMUTABLE_ROW",
        "WEBSOCKET_EVENT_DIGEST",
    }
)
_TIMEFRAME_US = {
    "1m": 60_000_000,
    "5m": 300_000_000,
    "15m": 900_000_000,
    "1h": 3_600_000_000,
    "4h": 14_400_000_000,
}

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@-]{0,255}$")
_LOCATOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@-]{0,511}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RECORD_ID_RE = re.compile(r"^trainer_exact_source_read_v1_[0-9a-f]{64}$")
_ADAPTER_CANDIDATE_ID_RE = re.compile(r"^trainer_source_adapter_candidate_v1_[0-9a-f]{64}$")

_ADDRESS_FIELDS = frozenset(
    {
        "schema_version",
        "store_schema_version",
        "address_schema_version",
        "payload_sha256",
        "payload_byte_count",
        "relative_path",
        "absolute_path",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "capture_record_id",
        "capture_identity_sha256",
        "binding_sha256",
        "evidence_classification",
        "downstream_status",
        "retry_semantics",
        "collision_semantics",
        "exact_byte_semantics",
        "source_kind",
        "source_label",
        "payload_type",
        "symbol",
        "timeframe",
        "payload_sha256",
        "payload_byte_count",
        "event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
        "decision_time",
        "interval_open_time",
        "interval_close_time",
        "source_finality_confirmed",
        "read_locator_type",
        "read_locator",
        "read_locator_version",
        "finality_type",
        "finality_cutoff",
        "finality_verified_at",
        "finality_verifier",
        "source_payload_cas_address",
        "source_payload_cas_put_completed",
        "source_payload_cas_exact_readback_verified",
        "source_adapter_attestation_status",
        "future_adapter_candidate_schema_version",
        "target_ledger_receipt_schema_version",
    }
)
_ADAPTER_CANDIDATE_FIELDS = frozenset(
    {
        "schema_version",
        "adapter_candidate_id",
        "adapter_candidate_identity_sha256",
        "adapter_candidate_binding_sha256",
        "evidence_classification",
        "adapter_attestation_status",
        "source_clock_status",
        "target_ledger_receipt_schema_version",
        "target_ledger_receipt_kind",
        "capture_record_id",
        "capture_binding_sha256",
        "capture_binding_cas_address",
        "source_payload_cas_address",
        "source_kind",
        "source_label",
        "payload_type",
        "symbol",
        "timeframe",
        "payload_sha256",
        "payload_byte_count",
        "event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
        "decision_time",
        "interval_open_time",
        "interval_close_time",
        "source_finality_confirmed",
        "read_locator_type",
        "read_locator",
        "read_locator_version",
        "finality_type",
        "finality_cutoff",
        "finality_verified_at",
        "finality_verifier",
    }
)
_CLOCK_FIELDS = (
    "event_time",
    "ingested_at",
    "available_at",
    "consumer_observed_at",
    "feature_cutoff",
    "decision_time",
    "finality_cutoff",
    "finality_verified_at",
)


class ExactSourceReadCaptureError(RuntimeError):
    """Base fail-closed exact-source capture error."""


class ExactSourceReadCaptureValidationError(ExactSourceReadCaptureError):
    """Capture inputs violate the typed byte/identity/temporal contract."""


class ExactSourceReadCaptureIntegrityError(ExactSourceReadCaptureError):
    """Stored payload, binding, or returned typed result is inconsistent."""


@dataclass(frozen=True, slots=True)
class ExactSourceReadCaptureArtifact:
    """Typed result for exact source bytes plus a nonconsumable binding.

    The exact source bytes and exact immutable-store object are retained so
    construction and every property access can perform fresh CAS readbacks and
    rederive the binding.  Properties return fresh copies rather than exposing
    mutable internal mappings.
    """

    capture_record_id: str
    binding_sha256: str
    binding_json: str
    source_payload_address: SourcePayloadAddress
    binding_address: SourcePayloadAddress
    adapter_candidate_id: str
    adapter_candidate_binding_sha256: str
    adapter_candidate_json: str
    adapter_candidate_address: SourcePayloadAddress
    exact_source_payload_bytes: bytes = dataclass_field(repr=False)
    source_payload_store: ImmutableSourcePayloadStore = dataclass_field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _validated_binding(self)

    @property
    def evidence_classification(self) -> str:
        return EXACT_SOURCE_CAPTURE_EVIDENCE_CLASSIFICATION

    @property
    def artifact_binding(self) -> dict[str, Any]:
        return _validated_binding(self)

    @property
    def future_source_adapter_candidate(self) -> dict[str, Any]:
        _validated_binding(self)
        candidate = _parse_binding_json(
            self.adapter_candidate_json,
            reason_prefix="exact_source_adapter_candidate",
        )
        return _strict_json_copy(candidate)


def _validation_error(reason: str) -> NoReturn:
    raise ExactSourceReadCaptureValidationError(reason)


def _integrity_error(reason: str) -> NoReturn:
    raise ExactSourceReadCaptureIntegrityError(reason)


def _strict_json_copy(value: Any) -> Any:
    try:
        return json.loads(canonical_json(value))
    except (FeatureSnapshotValidationError, json.JSONDecodeError) as exc:
        raise ExactSourceReadCaptureIntegrityError("exact_source_binding_not_strict_json") from exc


def _parse_binding_json(
    value: Any,
    *,
    reason_prefix: str = "exact_source_binding",
) -> dict[str, Any]:
    def duplicate_rejecting_object(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                _integrity_error(f"{reason_prefix}_duplicate_json_key")
            result[key] = item
        return result

    def reject_json_constant(constant: str) -> NoReturn:
        _integrity_error(f"{reason_prefix}_non_finite_json_number:{constant}")

    if type(value) is not str or not value or len(value) > 2 * 1024 * 1024:
        _integrity_error(f"{reason_prefix}_json_invalid")
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=duplicate_rejecting_object,
            parse_constant=reject_json_constant,
        )
    except ExactSourceReadCaptureIntegrityError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        raise ExactSourceReadCaptureIntegrityError(f"{reason_prefix}_json_invalid") from exc
    if type(parsed) is not dict:
        _integrity_error(f"{reason_prefix}_top_level_object_required")
    try:
        canonical = canonical_json(parsed)
    except FeatureSnapshotValidationError as exc:
        raise ExactSourceReadCaptureIntegrityError(f"{reason_prefix}_not_strict_json") from exc
    if value != canonical:
        _integrity_error(f"{reason_prefix}_json_not_canonical")
    return parsed


def _exact_text(
    value: Any,
    *,
    field: str,
    pattern: re.Pattern[str] = _LABEL_RE,
) -> str:
    if (
        type(value) is not str
        or value != value.strip()
        or not value.isascii()
        or pattern.fullmatch(value) is None
    ):
        _validation_error(f"exact_source_{field}_invalid")
    return value


def _canonical_clock(value: Any, *, field: str) -> tuple[str, datetime]:
    if type(value) is not str or not value or value != value.strip():
        _validation_error(f"exact_source_{field}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError) as exc:
        raise ExactSourceReadCaptureValidationError(f"exact_source_{field}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _validation_error(f"exact_source_{field}_timezone_required")
    try:
        parsed_utc = parsed.astimezone(UTC)
        canonical = parsed_utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, ValueError) as exc:
        raise ExactSourceReadCaptureValidationError(f"exact_source_{field}_invalid") from exc
    if value != canonical:
        _validation_error(f"exact_source_{field}_not_canonical_utc")
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    if parsed_utc <= epoch:
        _validation_error(f"exact_source_{field}_not_positive_epoch")
    return canonical, parsed_utc


def _epoch_microseconds(value: datetime) -> int:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = value - epoch
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _validated_metadata(
    *,
    source_kind: Any,
    source_label: Any,
    symbol: Any,
    timeframe: Any,
    event_time: Any,
    ingested_at: Any,
    available_at: Any,
    consumer_observed_at: Any,
    feature_cutoff: Any,
    decision_time: Any,
    interval_open_time: Any,
    interval_close_time: Any,
    source_finality_confirmed: Any,
    read_locator_type: Any,
    read_locator: Any,
    read_locator_version: Any,
    finality_type: Any,
    finality_cutoff: Any,
    finality_verified_at: Any,
    finality_verifier: Any,
) -> dict[str, Any]:
    if type(source_kind) is not str or source_kind not in EXACT_SOURCE_KINDS:
        _validation_error("exact_source_kind_invalid")
    label = _exact_text(source_label, field="label")
    exact_symbol = _exact_text(symbol, field="symbol", pattern=_SYMBOL_RE)
    if type(timeframe) is not str or timeframe not in _TIMEFRAME_US:
        _validation_error("exact_source_timeframe_invalid")
    if type(source_finality_confirmed) is not bool:
        _validation_error("exact_source_finality_confirmation_not_exact_bool")
    if source_finality_confirmed is not True:
        _validation_error("exact_source_not_final")
    if type(read_locator_type) is not str or read_locator_type not in _READ_LOCATOR_TYPES:
        _validation_error("exact_source_read_locator_type_invalid")
    locator = _exact_text(
        read_locator,
        field="read_locator",
        pattern=_LOCATOR_RE,
    )
    locator_version = _exact_text(
        read_locator_version,
        field="read_locator_version",
    )
    verifier = _exact_text(finality_verifier, field="finality_verifier")
    expected_finality_type = _SOURCE_KIND_FINALITY_TYPES[source_kind]
    if type(finality_type) is not str or finality_type != expected_finality_type:
        _validation_error("exact_source_kind_finality_type_mismatch")

    clocks: dict[str, str] = {}
    parsed: dict[str, datetime] = {}
    for field, value in (
        ("event_time", event_time),
        ("ingested_at", ingested_at),
        ("available_at", available_at),
        ("consumer_observed_at", consumer_observed_at),
        ("feature_cutoff", feature_cutoff),
        ("decision_time", decision_time),
        ("finality_cutoff", finality_cutoff),
        ("finality_verified_at", finality_verified_at),
    ):
        clocks[field], parsed[field] = _canonical_clock(value, field=field)

    ordered_pairs = (
        ("event_time", "ingested_at"),
        ("ingested_at", "available_at"),
        ("event_time", "finality_cutoff"),
        ("finality_cutoff", "available_at"),
        ("available_at", "finality_verified_at"),
        ("finality_verified_at", "consumer_observed_at"),
        ("event_time", "feature_cutoff"),
        ("feature_cutoff", "decision_time"),
        ("consumer_observed_at", "decision_time"),
    )
    interval_open: str | None = None
    interval_close: str | None = None
    if source_kind == SOURCE_KIND_OHLCV_CLOSED_INTERVAL:
        interval_open, parsed_open = _canonical_clock(
            interval_open_time,
            field="interval_open_time",
        )
        interval_close, parsed_close = _canonical_clock(
            interval_close_time,
            field="interval_close_time",
        )
        duration_us = _TIMEFRAME_US[timeframe]
        open_us = _epoch_microseconds(parsed_open)
        close_us = _epoch_microseconds(parsed_close)
        if open_us % duration_us != 0:
            _validation_error("exact_source_candle_open_not_timeframe_aligned")
        if close_us != open_us + duration_us - 1_000:
            _validation_error("exact_source_candle_interval_invalid")
        if parsed_close != parsed["event_time"]:
            _validation_error("exact_source_candle_event_time_not_interval_close")
        if parsed_close != parsed["finality_cutoff"]:
            _validation_error("exact_source_candle_finality_cutoff_not_interval_close")
        if parsed_close > parsed["decision_time"]:
            _validation_error("exact_source_unfinished_candle_forbidden")
        if parsed["finality_verified_at"] <= parsed_close:
            _validation_error("exact_source_candle_finality_verified_at_not_post_close")
        if parsed["available_at"] <= parsed_close:
            _validation_error("exact_source_candle_available_at_not_post_close")
        if parsed["consumer_observed_at"] <= parsed_close:
            _validation_error("exact_source_candle_consumer_observed_at_not_post_close")
    elif interval_open_time is not None or interval_close_time is not None:
        _validation_error("exact_source_non_interval_has_interval_clocks")

    for earlier, later in ordered_pairs:
        if parsed[earlier] > parsed[later]:
            _validation_error(f"exact_source_clock_order_invalid:{earlier}_after_{later}")

    return {
        "source_kind": source_kind,
        "source_label": label,
        "payload_type": _SOURCE_KIND_PAYLOAD_TYPES[source_kind],
        "symbol": exact_symbol,
        "timeframe": timeframe,
        **clocks,
        "interval_open_time": interval_open,
        "interval_close_time": interval_close,
        "source_finality_confirmed": True,
        "read_locator_type": read_locator_type,
        "read_locator": locator,
        "read_locator_version": locator_version,
        "finality_type": expected_finality_type,
        "finality_verifier": verifier,
    }


def _address_mapping(
    *,
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
    payload_sha256: str,
    payload_byte_count: int,
) -> dict[str, Any]:
    if type(address) is not SourcePayloadAddress:
        _integrity_error("exact_source_cas_address_type_invalid")
    expected_relative_path = f"sha256/{payload_sha256[:2]}/{payload_sha256}"
    expected_absolute_path = store.path_for(payload_sha256)
    try:
        relative_from_root = expected_absolute_path.relative_to(store.root_path).as_posix()
    except ValueError as exc:
        raise ExactSourceReadCaptureIntegrityError(
            "exact_source_cas_address_outside_store_root"
        ) from exc
    if (
        address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or address.payload_sha256 != payload_sha256
        or address.payload_byte_count != payload_byte_count
        or address.relative_path != expected_relative_path
        or relative_from_root != expected_relative_path
        or not expected_absolute_path.is_absolute()
        or ".." in expected_absolute_path.parts
    ):
        _integrity_error("exact_source_cas_address_mismatch")
    return {
        "schema_version": EXACT_SOURCE_CAPTURE_ADDRESS_SCHEMA_VERSION,
        "store_schema_version": SOURCE_PAYLOAD_STORE_SCHEMA_VERSION,
        "address_schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
        "absolute_path": expected_absolute_path.as_posix(),
    }


def _identity_material(
    *,
    metadata: Mapping[str, Any],
    payload_sha256: str,
    payload_byte_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": EXACT_SOURCE_CAPTURE_IDENTITY_SCHEMA_VERSION,
        "source_kind": metadata["source_kind"],
        "source_label": metadata["source_label"],
        "payload_type": metadata["payload_type"],
        "symbol": metadata["symbol"],
        "timeframe": metadata["timeframe"],
        "payload_sha256": payload_sha256,
        "payload_byte_count": payload_byte_count,
        "event_time": metadata["event_time"],
        "ingested_at": metadata["ingested_at"],
        "available_at": metadata["available_at"],
        "consumer_observed_at": metadata["consumer_observed_at"],
        "feature_cutoff": metadata["feature_cutoff"],
        "decision_time": metadata["decision_time"],
        "interval_open_time": metadata["interval_open_time"],
        "interval_close_time": metadata["interval_close_time"],
        "source_finality_confirmed": metadata["source_finality_confirmed"],
        "read_locator_type": metadata["read_locator_type"],
        "read_locator": metadata["read_locator"],
        "read_locator_version": metadata["read_locator_version"],
        "finality_type": metadata["finality_type"],
        "finality_cutoff": metadata["finality_cutoff"],
        "finality_verified_at": metadata["finality_verified_at"],
        "finality_verifier": metadata["finality_verifier"],
    }


def _adapter_candidate(
    *,
    metadata: Mapping[str, Any],
    payload_sha256: str,
    payload_byte_count: int,
    capture_record_id: str,
    capture_binding_sha256: str,
    source_payload_cas_address: Mapping[str, Any],
    capture_binding_cas_address: Mapping[str, Any],
) -> dict[str, Any]:
    identity = {
        "schema_version": SOURCE_ADAPTER_CANDIDATE_IDENTITY_SCHEMA_VERSION,
        "capture_record_id": capture_record_id,
        "capture_binding_sha256": capture_binding_sha256,
        "capture_binding_cas_address": dict(capture_binding_cas_address),
        "source_payload_cas_address": dict(source_payload_cas_address),
        "source_kind": metadata["source_kind"],
        "source_label": metadata["source_label"],
        "payload_type": metadata["payload_type"],
        "symbol": metadata["symbol"],
        "timeframe": metadata["timeframe"],
        "payload_sha256": payload_sha256,
        "payload_byte_count": payload_byte_count,
        "event_time": metadata["event_time"],
        "ingested_at": metadata["ingested_at"],
        "available_at": metadata["available_at"],
        "consumer_observed_at": metadata["consumer_observed_at"],
        "feature_cutoff": metadata["feature_cutoff"],
        "decision_time": metadata["decision_time"],
        "interval_open_time": metadata["interval_open_time"],
        "interval_close_time": metadata["interval_close_time"],
        "source_finality_confirmed": metadata["source_finality_confirmed"],
        "read_locator_type": metadata["read_locator_type"],
        "read_locator": metadata["read_locator"],
        "read_locator_version": metadata["read_locator_version"],
        "finality_type": metadata["finality_type"],
        "finality_cutoff": metadata["finality_cutoff"],
        "finality_verified_at": metadata["finality_verified_at"],
        "finality_verifier": metadata["finality_verifier"],
    }
    identity_sha256 = stable_sha256(identity)
    candidate_id = f"trainer_source_adapter_candidate_v1_{identity_sha256}"
    material = {
        "schema_version": SOURCE_ADAPTER_CANDIDATE_SCHEMA_VERSION,
        "adapter_candidate_id": candidate_id,
        "adapter_candidate_identity_sha256": identity_sha256,
        "evidence_classification": (SOURCE_ADAPTER_CANDIDATE_EVIDENCE_CLASSIFICATION),
        "adapter_attestation_status": SOURCE_ADAPTER_ATTESTATION_STATUS,
        "source_clock_status": SOURCE_ADAPTER_CLOCK_STATUS,
        "target_ledger_receipt_schema_version": (SOURCE_READ_RECEIPT_SCHEMA_VERSION),
        "target_ledger_receipt_kind": "DIRECT_READ_AFTER_ADAPTER_ATTESTATION",
        **{key: value for key, value in identity.items() if key != "schema_version"},
    }
    return {
        **material,
        "adapter_candidate_binding_sha256": stable_sha256(material),
    }


def _metadata_from_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: binding[key]
        for key in (
            "source_kind",
            "source_label",
            "payload_type",
            "symbol",
            "timeframe",
            *_CLOCK_FIELDS,
            "interval_open_time",
            "interval_close_time",
            "source_finality_confirmed",
            "read_locator_type",
            "read_locator",
            "read_locator_version",
            "finality_type",
            "finality_verifier",
        )
    }


def _validated_binding(result: ExactSourceReadCaptureArtifact) -> dict[str, Any]:
    if type(result.source_payload_store) is not ImmutableSourcePayloadStore:
        _integrity_error("exact_source_result_store_invalid")
    if type(result.exact_source_payload_bytes) is not bytes:
        _integrity_error("exact_source_result_exact_bytes_required")
    payload = result.exact_source_payload_bytes
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    payload_byte_count = len(payload)
    if (
        payload_byte_count <= 0
        or payload_byte_count > result.source_payload_store.max_payload_bytes
    ):
        _integrity_error("exact_source_result_payload_size_invalid")

    _address_mapping(
        store=result.source_payload_store,
        address=result.source_payload_address,
        payload_sha256=payload_sha256,
        payload_byte_count=payload_byte_count,
    )
    try:
        payload_readback = result.source_payload_store.get(
            payload_sha256,
            expected_byte_count=payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ExactSourceReadCaptureIntegrityError(
            "exact_source_result_payload_cas_readback_failed"
        ) from exc
    if type(payload_readback) is not bytes or not hmac.compare_digest(
        payload_readback,
        payload,
    ):
        _integrity_error("exact_source_result_payload_cas_readback_mismatch")

    binding = _parse_binding_json(result.binding_json)
    if frozenset(binding) != _BINDING_FIELDS:
        _integrity_error("exact_source_binding_field_set_mismatch")
    fixed = {
        "schema_version": EXACT_SOURCE_CAPTURE_SCHEMA_VERSION,
        "evidence_classification": EXACT_SOURCE_CAPTURE_EVIDENCE_CLASSIFICATION,
        "downstream_status": EXACT_SOURCE_CAPTURE_DOWNSTREAM_STATUS,
        "retry_semantics": EXACT_SOURCE_CAPTURE_RETRY_SEMANTICS,
        "collision_semantics": EXACT_SOURCE_CAPTURE_COLLISION_SEMANTICS,
        "exact_byte_semantics": (
            "OPAQUE_EXACT_BYTES_SUPPLIED_BY_SOURCE_READER_NO_PARSE_OR_RESERIALIZE"
        ),
        "source_payload_cas_put_completed": True,
        "source_payload_cas_exact_readback_verified": True,
        "source_adapter_attestation_status": SOURCE_ADAPTER_ATTESTATION_STATUS,
        "future_adapter_candidate_schema_version": (SOURCE_ADAPTER_CANDIDATE_SCHEMA_VERSION),
        "target_ledger_receipt_schema_version": SOURCE_READ_RECEIPT_SCHEMA_VERSION,
    }
    if any(binding.get(key) != value for key, value in fixed.items()):
        _integrity_error("exact_source_binding_fixed_literal_mismatch")
    forbidden_ready_fields = {
        key
        for key in binding
        if "consumer_ready" in key or "admission_eligible" in key or key.startswith("trainer_ready")
    }
    if forbidden_ready_fields:
        _integrity_error("exact_source_binding_consumer_ready_flag_forbidden")
    if binding.get("payload_sha256") != payload_sha256:
        _integrity_error("exact_source_binding_payload_sha256_mismatch")
    if binding.get("payload_byte_count") != payload_byte_count:
        _integrity_error("exact_source_binding_payload_byte_count_mismatch")

    try:
        metadata = _validated_metadata(
            source_kind=binding.get("source_kind"),
            source_label=binding.get("source_label"),
            symbol=binding.get("symbol"),
            timeframe=binding.get("timeframe"),
            event_time=binding.get("event_time"),
            ingested_at=binding.get("ingested_at"),
            available_at=binding.get("available_at"),
            consumer_observed_at=binding.get("consumer_observed_at"),
            feature_cutoff=binding.get("feature_cutoff"),
            decision_time=binding.get("decision_time"),
            interval_open_time=binding.get("interval_open_time"),
            interval_close_time=binding.get("interval_close_time"),
            source_finality_confirmed=binding.get("source_finality_confirmed"),
            read_locator_type=binding.get("read_locator_type"),
            read_locator=binding.get("read_locator"),
            read_locator_version=binding.get("read_locator_version"),
            finality_type=binding.get("finality_type"),
            finality_cutoff=binding.get("finality_cutoff"),
            finality_verified_at=binding.get("finality_verified_at"),
            finality_verifier=binding.get("finality_verifier"),
        )
    except ExactSourceReadCaptureValidationError as exc:
        raise ExactSourceReadCaptureIntegrityError("exact_source_binding_metadata_invalid") from exc
    if _metadata_from_binding(binding) != metadata:
        _integrity_error("exact_source_binding_metadata_not_canonical")

    identity = _identity_material(
        metadata=metadata,
        payload_sha256=payload_sha256,
        payload_byte_count=payload_byte_count,
    )
    identity_sha256 = stable_sha256(identity)
    expected_record_id = f"trainer_exact_source_read_v1_{identity_sha256}"
    if (
        binding.get("capture_identity_sha256") != identity_sha256
        or binding.get("capture_record_id") != expected_record_id
        or result.capture_record_id != expected_record_id
        or _RECORD_ID_RE.fullmatch(expected_record_id) is None
    ):
        _integrity_error("exact_source_binding_record_identity_mismatch")

    address_mapping = binding.get("source_payload_cas_address")
    if type(address_mapping) is not dict or frozenset(address_mapping) != _ADDRESS_FIELDS:
        _integrity_error("exact_source_binding_payload_address_invalid")
    expected_address_mapping = _address_mapping(
        store=result.source_payload_store,
        address=result.source_payload_address,
        payload_sha256=payload_sha256,
        payload_byte_count=payload_byte_count,
    )
    if address_mapping != expected_address_mapping:
        _integrity_error("exact_source_binding_payload_address_mismatch")

    material_without_hash = {
        key: value for key, value in binding.items() if key != "binding_sha256"
    }
    expected_binding_sha256 = stable_sha256(material_without_hash)
    if (
        binding.get("binding_sha256") != expected_binding_sha256
        or result.binding_sha256 != expected_binding_sha256
    ):
        _integrity_error("exact_source_binding_sha256_mismatch")

    try:
        binding_bytes = result.binding_json.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ExactSourceReadCaptureIntegrityError(
            "exact_source_binding_not_canonical_ascii"
        ) from exc
    binding_cas_sha256 = hashlib.sha256(binding_bytes).hexdigest()
    binding_cas_byte_count = len(binding_bytes)
    expected_binding_cas_address = _address_mapping(
        store=result.source_payload_store,
        address=result.binding_address,
        payload_sha256=binding_cas_sha256,
        payload_byte_count=binding_cas_byte_count,
    )
    try:
        binding_readback = result.source_payload_store.get(
            binding_cas_sha256,
            expected_byte_count=binding_cas_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ExactSourceReadCaptureIntegrityError(
            "exact_source_result_binding_cas_readback_failed"
        ) from exc
    if type(binding_readback) is not bytes or not hmac.compare_digest(
        binding_readback,
        binding_bytes,
    ):
        _integrity_error("exact_source_result_binding_cas_readback_mismatch")

    candidate = _parse_binding_json(
        result.adapter_candidate_json,
        reason_prefix="exact_source_adapter_candidate",
    )
    if frozenset(candidate) != _ADAPTER_CANDIDATE_FIELDS:
        _integrity_error("exact_source_adapter_candidate_field_set_mismatch")
    forbidden_ledger_receipt_fields = {
        "receipt_sha256",
        "read_evidence",
        "read_evidence_sha256",
        "read_locator_sha256",
        "finality_evidence",
        "finality_evidence_sha256",
        "receipt_kind",
        "child_read_bindings",
        "derivation_material",
        "derivation_sha256",
    }
    if forbidden_ledger_receipt_fields.intersection(candidate):
        _integrity_error("exact_source_adapter_candidate_exposes_ledger_receipt")
    candidate_fixed = {
        "schema_version": SOURCE_ADAPTER_CANDIDATE_SCHEMA_VERSION,
        "evidence_classification": (SOURCE_ADAPTER_CANDIDATE_EVIDENCE_CLASSIFICATION),
        "adapter_attestation_status": SOURCE_ADAPTER_ATTESTATION_STATUS,
        "source_clock_status": SOURCE_ADAPTER_CLOCK_STATUS,
        "target_ledger_receipt_schema_version": (SOURCE_READ_RECEIPT_SCHEMA_VERSION),
        "target_ledger_receipt_kind": "DIRECT_READ_AFTER_ADAPTER_ATTESTATION",
    }
    if any(candidate.get(key) != value for key, value in candidate_fixed.items()):
        _integrity_error("exact_source_adapter_candidate_fixed_literal_mismatch")
    expected_candidate = _adapter_candidate(
        metadata=metadata,
        payload_sha256=payload_sha256,
        payload_byte_count=payload_byte_count,
        capture_record_id=expected_record_id,
        capture_binding_sha256=expected_binding_sha256,
        source_payload_cas_address=expected_address_mapping,
        capture_binding_cas_address=expected_binding_cas_address,
    )
    if candidate != expected_candidate:
        _integrity_error("exact_source_adapter_candidate_capture_binding_mismatch")
    candidate_id = candidate.get("adapter_candidate_id")
    candidate_binding_sha256 = candidate.get("adapter_candidate_binding_sha256")
    if (
        type(candidate_id) is not str
        or _ADAPTER_CANDIDATE_ID_RE.fullmatch(candidate_id) is None
        or result.adapter_candidate_id != candidate_id
        or type(candidate_binding_sha256) is not str
        or _SHA256_RE.fullmatch(candidate_binding_sha256) is None
        or result.adapter_candidate_binding_sha256 != candidate_binding_sha256
    ):
        _integrity_error("exact_source_adapter_candidate_identity_mismatch")
    try:
        candidate_bytes = result.adapter_candidate_json.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ExactSourceReadCaptureIntegrityError(
            "exact_source_adapter_candidate_not_canonical_ascii"
        ) from exc
    candidate_cas_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
    candidate_cas_byte_count = len(candidate_bytes)
    _address_mapping(
        store=result.source_payload_store,
        address=result.adapter_candidate_address,
        payload_sha256=candidate_cas_sha256,
        payload_byte_count=candidate_cas_byte_count,
    )
    try:
        candidate_readback = result.source_payload_store.get(
            candidate_cas_sha256,
            expected_byte_count=candidate_cas_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ExactSourceReadCaptureIntegrityError(
            "exact_source_result_adapter_candidate_cas_readback_failed"
        ) from exc
    if type(candidate_readback) is not bytes or not hmac.compare_digest(
        candidate_readback,
        candidate_bytes,
    ):
        _integrity_error("exact_source_result_adapter_candidate_cas_readback_mismatch")
    return binding


def capture_exact_source_read(
    *,
    source_payload_store: ImmutableSourcePayloadStore,
    exact_source_payload_bytes: bytes,
    source_kind: str,
    source_label: str,
    symbol: str,
    timeframe: str,
    event_time: str,
    ingested_at: str,
    available_at: str,
    consumer_observed_at: str,
    feature_cutoff: str,
    decision_time: str,
    source_finality_confirmed: bool,
    read_locator_type: str,
    read_locator: str,
    read_locator_version: str,
    finality_type: str,
    finality_cutoff: str,
    finality_verified_at: str,
    finality_verifier: str,
    interval_open_time: str | None = None,
    interval_close_time: str | None = None,
) -> ExactSourceReadCaptureArtifact:
    """Capture one exact source read without making it consumer-eligible.

    All metadata is validated before CAS publication.  The caller must sample
    ``consumer_observed_at`` at the source-read boundary and must pass a
    ``decision_time`` no earlier than that observation.  This function never
    calls a wall clock and cannot turn CAS completion into an observation.
    """

    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _validation_error("exact_source_authentic_store_required")
    if type(exact_source_payload_bytes) is not bytes:
        _validation_error("exact_source_payload_exact_bytes_required")
    payload_byte_count = len(exact_source_payload_bytes)
    if payload_byte_count <= 0:
        _validation_error("exact_source_payload_empty_forbidden")
    if payload_byte_count > source_payload_store.max_payload_bytes:
        _validation_error("exact_source_payload_size_limit_exceeded")

    metadata = _validated_metadata(
        source_kind=source_kind,
        source_label=source_label,
        symbol=symbol,
        timeframe=timeframe,
        event_time=event_time,
        ingested_at=ingested_at,
        available_at=available_at,
        consumer_observed_at=consumer_observed_at,
        feature_cutoff=feature_cutoff,
        decision_time=decision_time,
        interval_open_time=interval_open_time,
        interval_close_time=interval_close_time,
        source_finality_confirmed=source_finality_confirmed,
        read_locator_type=read_locator_type,
        read_locator=read_locator,
        read_locator_version=read_locator_version,
        finality_type=finality_type,
        finality_cutoff=finality_cutoff,
        finality_verified_at=finality_verified_at,
        finality_verifier=finality_verifier,
    )
    payload_sha256 = hashlib.sha256(exact_source_payload_bytes).hexdigest()
    identity = _identity_material(
        metadata=metadata,
        payload_sha256=payload_sha256,
        payload_byte_count=payload_byte_count,
    )
    identity_sha256 = stable_sha256(identity)
    capture_record_id = f"trainer_exact_source_read_v1_{identity_sha256}"

    # Compute the canonical address mapping before publication so every
    # metadata/serialization error fails without creating an immutable object.
    predicted_address = SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=payload_sha256,
        payload_byte_count=payload_byte_count,
        relative_path=f"sha256/{payload_sha256[:2]}/{payload_sha256}",
    )
    source_address_mapping = _address_mapping(
        store=source_payload_store,
        address=predicted_address,
        payload_sha256=payload_sha256,
        payload_byte_count=payload_byte_count,
    )
    binding_material: dict[str, Any] = {
        "schema_version": EXACT_SOURCE_CAPTURE_SCHEMA_VERSION,
        "capture_record_id": capture_record_id,
        "capture_identity_sha256": identity_sha256,
        "evidence_classification": EXACT_SOURCE_CAPTURE_EVIDENCE_CLASSIFICATION,
        "downstream_status": EXACT_SOURCE_CAPTURE_DOWNSTREAM_STATUS,
        "retry_semantics": EXACT_SOURCE_CAPTURE_RETRY_SEMANTICS,
        "collision_semantics": EXACT_SOURCE_CAPTURE_COLLISION_SEMANTICS,
        "exact_byte_semantics": (
            "OPAQUE_EXACT_BYTES_SUPPLIED_BY_SOURCE_READER_NO_PARSE_OR_RESERIALIZE"
        ),
        **metadata,
        "payload_sha256": payload_sha256,
        "payload_byte_count": payload_byte_count,
        "source_payload_cas_address": source_address_mapping,
        "source_payload_cas_put_completed": True,
        "source_payload_cas_exact_readback_verified": True,
        "source_adapter_attestation_status": SOURCE_ADAPTER_ATTESTATION_STATUS,
        "future_adapter_candidate_schema_version": (SOURCE_ADAPTER_CANDIDATE_SCHEMA_VERSION),
        "target_ledger_receipt_schema_version": SOURCE_READ_RECEIPT_SCHEMA_VERSION,
    }
    binding_sha256 = stable_sha256(binding_material)
    binding = {**binding_material, "binding_sha256": binding_sha256}
    binding_json = canonical_json(binding)
    binding_bytes = binding_json.encode("ascii")
    if len(binding_bytes) > source_payload_store.max_payload_bytes:
        _validation_error("exact_source_binding_size_limit_exceeded")
    binding_cas_sha256 = hashlib.sha256(binding_bytes).hexdigest()
    binding_cas_byte_count = len(binding_bytes)
    predicted_binding_address = SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=binding_cas_sha256,
        payload_byte_count=binding_cas_byte_count,
        relative_path=(f"sha256/{binding_cas_sha256[:2]}/{binding_cas_sha256}"),
    )
    binding_address_mapping = _address_mapping(
        store=source_payload_store,
        address=predicted_binding_address,
        payload_sha256=binding_cas_sha256,
        payload_byte_count=binding_cas_byte_count,
    )
    adapter_candidate = _adapter_candidate(
        metadata=metadata,
        payload_sha256=payload_sha256,
        payload_byte_count=payload_byte_count,
        capture_record_id=capture_record_id,
        capture_binding_sha256=binding_sha256,
        source_payload_cas_address=source_address_mapping,
        capture_binding_cas_address=binding_address_mapping,
    )
    adapter_candidate_id = adapter_candidate["adapter_candidate_id"]
    adapter_candidate_binding_sha256 = adapter_candidate["adapter_candidate_binding_sha256"]
    adapter_candidate_json = canonical_json(adapter_candidate)
    adapter_candidate_bytes = adapter_candidate_json.encode("ascii")
    if len(adapter_candidate_bytes) > source_payload_store.max_payload_bytes:
        _validation_error("exact_source_adapter_candidate_size_limit_exceeded")

    try:
        source_payload_address = source_payload_store.put(
            exact_source_payload_bytes,
            expected_sha256=payload_sha256,
            expected_byte_count=payload_byte_count,
        )
        source_readback = source_payload_store.get(
            payload_sha256,
            expected_byte_count=payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ExactSourceReadCaptureIntegrityError(
            "exact_source_payload_cas_publication_failed"
        ) from exc
    _address_mapping(
        store=source_payload_store,
        address=source_payload_address,
        payload_sha256=payload_sha256,
        payload_byte_count=payload_byte_count,
    )
    if type(source_readback) is not bytes or not hmac.compare_digest(
        source_readback,
        exact_source_payload_bytes,
    ):
        _integrity_error("exact_source_payload_cas_exact_readback_mismatch")

    try:
        binding_address = source_payload_store.put(
            binding_bytes,
            expected_sha256=binding_cas_sha256,
            expected_byte_count=binding_cas_byte_count,
        )
        binding_readback = source_payload_store.get(
            binding_cas_sha256,
            expected_byte_count=binding_cas_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ExactSourceReadCaptureIntegrityError(
            "exact_source_binding_cas_publication_failed"
        ) from exc
    _address_mapping(
        store=source_payload_store,
        address=binding_address,
        payload_sha256=binding_cas_sha256,
        payload_byte_count=binding_cas_byte_count,
    )
    if type(binding_readback) is not bytes or not hmac.compare_digest(
        binding_readback,
        binding_bytes,
    ):
        _integrity_error("exact_source_binding_cas_exact_readback_mismatch")

    adapter_candidate_cas_sha256 = hashlib.sha256(adapter_candidate_bytes).hexdigest()
    adapter_candidate_cas_byte_count = len(adapter_candidate_bytes)
    try:
        adapter_candidate_address = source_payload_store.put(
            adapter_candidate_bytes,
            expected_sha256=adapter_candidate_cas_sha256,
            expected_byte_count=adapter_candidate_cas_byte_count,
        )
        adapter_candidate_readback = source_payload_store.get(
            adapter_candidate_cas_sha256,
            expected_byte_count=adapter_candidate_cas_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ExactSourceReadCaptureIntegrityError(
            "exact_source_adapter_candidate_cas_publication_failed"
        ) from exc
    _address_mapping(
        store=source_payload_store,
        address=adapter_candidate_address,
        payload_sha256=adapter_candidate_cas_sha256,
        payload_byte_count=adapter_candidate_cas_byte_count,
    )
    if type(adapter_candidate_readback) is not bytes or not hmac.compare_digest(
        adapter_candidate_readback,
        adapter_candidate_bytes,
    ):
        _integrity_error("exact_source_adapter_candidate_cas_exact_readback_mismatch")

    return ExactSourceReadCaptureArtifact(
        capture_record_id=capture_record_id,
        binding_sha256=binding_sha256,
        binding_json=binding_json,
        source_payload_address=source_payload_address,
        binding_address=binding_address,
        adapter_candidate_id=adapter_candidate_id,
        adapter_candidate_binding_sha256=(adapter_candidate_binding_sha256),
        adapter_candidate_json=adapter_candidate_json,
        adapter_candidate_address=adapter_candidate_address,
        exact_source_payload_bytes=exact_source_payload_bytes,
        source_payload_store=source_payload_store,
    )


__all__ = [
    "EXACT_SOURCE_CAPTURE_COLLISION_SEMANTICS",
    "EXACT_SOURCE_CAPTURE_DOWNSTREAM_STATUS",
    "EXACT_SOURCE_CAPTURE_EVIDENCE_CLASSIFICATION",
    "EXACT_SOURCE_CAPTURE_RETRY_SEMANTICS",
    "EXACT_SOURCE_CAPTURE_SCHEMA_VERSION",
    "EXACT_SOURCE_KINDS",
    "SOURCE_ADAPTER_ATTESTATION_STATUS",
    "SOURCE_ADAPTER_CANDIDATE_EVIDENCE_CLASSIFICATION",
    "SOURCE_ADAPTER_CANDIDATE_IDENTITY_SCHEMA_VERSION",
    "SOURCE_ADAPTER_CANDIDATE_SCHEMA_VERSION",
    "SOURCE_ADAPTER_CLOCK_STATUS",
    "ExactSourceReadCaptureArtifact",
    "ExactSourceReadCaptureError",
    "ExactSourceReadCaptureIntegrityError",
    "ExactSourceReadCaptureValidationError",
    "SOURCE_KIND_FUNDING_SNAPSHOT",
    "SOURCE_KIND_LIQUIDATION_AGGREGATE",
    "SOURCE_KIND_LIQUIDATION_EVENT",
    "SOURCE_KIND_OHLCV_CLOSED_INTERVAL",
    "SOURCE_KIND_OPEN_INTEREST_SNAPSHOT",
    "SOURCE_KIND_ORDERBOOK_SNAPSHOT",
    "SOURCE_KIND_PAPER_POSITION_STATE",
    "capture_exact_source_read",
]
