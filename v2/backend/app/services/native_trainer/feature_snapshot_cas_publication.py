"""Non-consumable CAS artifact boundary for a native feature snapshot.

This module does one deliberately narrow job: it validates a parsed native
snapshot, serializes that mapping with a new compact canonical-JSON artifact
ABI, stores those *derived artifact bytes* in the immutable content-addressed
store, and verifies an exact CAS readback.

The artifact is not evidence of the bytes originally read from Redis or a
file.  It is not a point-in-time input receipt, a trainer admission receipt, a
feature availability receipt, or durable-ledger source evidence.  In
particular, creating this artifact cannot clear any of the producer's current
fail-closed PIT/publication holds and cannot make the snapshot consumable.

Retries are artifact-only, content-idempotent operations.  Equal derived bytes
retain the same stable artifact ID and artifact CAS address.  Within one
canonical CAS root they also retain the same binding CAS address; a different
root changes the binding because the canonical absolute artifact path is part
of that binding.  The binding makes no historical wall-clock claim: CAS
existence and fresh exact readback can be verified, but CAS cannot prove when a
clock was sampled.  No Redis key is read or written, no trainer is started, and
no exchange path is touched here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
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

CAS_ARTIFACT_BINDING_SCHEMA_VERSION = "feature_snapshot_cas_artifact_binding_v1"
CAS_ARTIFACT_IDENTITY_SCHEMA_VERSION = "feature_snapshot_cas_artifact_identity_v1"
CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION = "feature_snapshot_cas_artifact_canonical_json_v1"
CAS_ARTIFACT_EVIDENCE_CLASSIFICATION = "CAS_ARTIFACT_ONLY_NON_CONSUMABLE_NO_PIT_OR_SOURCE_RECEIPT"
CAS_ARTIFACT_RETRY_SEMANTICS = (
    "STABLE_CONTENT_ID_AND_ARTIFACT_ADDRESS_FOR_EQUAL_DERIVED_BYTES;"
    "STABLE_BINDING_ADDRESS_WITHIN_SAME_CANONICAL_CAS_ROOT"
)
NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION = "v2_native_feature_snapshot_v2"
NATIVE_FEATURE_SNAPSHOT_WORKER_ID = "v2_feature_pipeline_native_loop"
MAX_CANONICAL_FEATURE_SNAPSHOT_BYTES = 2 * 1024 * 1024

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}$")
_NATIVE_TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
}
_FEATURE_SNAPSHOT_ID_RE = re.compile(r"^v2_fsnap_[0-9a-f]{64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CAS_ARTIFACT_RECORD_ID_RE = re.compile(r"^feature_snapshot_cas_artifact_v1_[0-9a-f]{64}$")
_CAS_ARTIFACT_BINDING_KEYS = frozenset(
    {
        "schema_version",
        "artifact_record_id",
        "artifact_identity_sha256",
        "evidence_classification",
        "artifact_retry_semantics",
        "consumer_admission_eligible",
        "point_in_time_evidence",
        "trainer_evidence",
        "ledger_source_evidence",
        "source_transport_bytes_verified",
        "feature_snapshot_id",
        "native_snapshot_schema_version",
        "artifact_serialization_schema_version",
        "artifact_serialization_origin",
        "artifact_serialization_sha256",
        "artifact_serialization_byte_count",
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
        "cas_address",
        "cas_put_completed",
        "cas_exact_readback_verified",
        "cas_exact_readback_sha256",
        "cas_exact_readback_byte_count",
        "artifact_binding_sha256",
    }
)
_CAS_ARTIFACT_ADDRESS_KEYS = frozenset(
    {
        "store_schema_version",
        "address_schema_version",
        "payload_sha256",
        "payload_byte_count",
        "relative_path",
        "absolute_path",
    }
)
_SOURCE_CLOCK_FIELDS = (
    "candle_open_time",
    "candle_close_time",
    "event_time",
    "ingested_at",
    "source_available_at",
)
_LEGITIMATE_NATIVE_BINDING_OVERLAP_FIELDS = frozenset(
    {
        "schema_version",
        "feature_snapshot_id",
        "symbol",
        "timeframe",
        "candle_open_time",
        "candle_close_time",
        "source_available_at",
        "feature_cutoff",
        "generated_at",
        "source",
        "is_backfilled",
        "source_sequence_id",
        "raw_payload_hash",
    }
)
_RESERVED_NATIVE_SNAPSHOT_ARTIFACT_FIELDS = frozenset(
    (_CAS_ARTIFACT_BINDING_KEYS - _LEGITIMATE_NATIVE_BINDING_OVERLAP_FIELDS)
    | {
        "admission_eligible",
        "artifact_binding_cas_address",
        "artifact_binding_json",
        "artifact_snapshot_bytes",
        "binding_address",
        "binding_sha256",
        "identity_sha256",
        "postcommit_observed_at",
        "publication_binding_sha256",
        "publication_record_id",
        "retry_semantics",
        "source_payload_store",
        "source_read_receipt",
        "source_read_receipts",
    }
)
_RESERVED_NATIVE_SNAPSHOT_ARTIFACT_PREFIXES = (
    "admission_",
    "artifact_",
    "binding_",
    "binding_cas_",
    "cas_",
    "consumer_admission_",
    "evidence_",
    "identity_",
    "ledger_",
    "point_in_time_",
    "postcommit_",
    "publication_",
    "publication_binding_",
    "retry_",
    "source_payload_",
    "source_read_receipt",
    "source_transport_",
    "trainer_admission_",
    "trainer_evidence",
    "trainer_receipt_",
)


class FeatureSnapshotPublicationError(RuntimeError):
    """Base fail-closed publication bridge error."""


class FeatureSnapshotPublicationValidationError(FeatureSnapshotPublicationError):
    """The exact bytes or expected native identity violate the bridge ABI."""


class FeatureSnapshotPublicationIntegrityError(FeatureSnapshotPublicationError):
    """CAS publication/readback did not reproduce the exact supplied bytes."""


@dataclass(frozen=True, slots=True)
class FeatureSnapshotCasArtifact:
    """Immutable, explicitly non-consumable CAS artifact result.

    The result is artifact evidence only.  ``consumer_admission_eligible``,
    ``point_in_time_evidence``, ``trainer_evidence``, and
    ``ledger_source_evidence`` are invariantly false, including through
    ``dataclasses.replace``.  The exact derived artifact bytes and configured
    immutable store are retained so construction and every mapping access can
    rederive all snapshot fields, resolve the canonical absolute CAS path, and
    perform a fresh exact store readback.  Mapping access returns a fresh
    verified copy.
    """

    artifact_record_id: str
    artifact_binding_sha256: str
    artifact_binding_json: str
    cas_address: SourcePayloadAddress
    artifact_binding_cas_address: SourcePayloadAddress
    artifact_snapshot_bytes: bytes = dataclass_field(repr=False)
    source_payload_store: ImmutableSourcePayloadStore = dataclass_field(
        repr=False,
        compare=False,
    )
    evidence_classification: str = CAS_ARTIFACT_EVIDENCE_CLASSIFICATION
    consumer_admission_eligible: bool = False
    point_in_time_evidence: bool = False
    trainer_evidence: bool = False
    ledger_source_evidence: bool = False

    def __post_init__(self) -> None:
        if self.evidence_classification != CAS_ARTIFACT_EVIDENCE_CLASSIFICATION:
            raise FeatureSnapshotPublicationIntegrityError(
                "feature_snapshot_artifact_evidence_classification_invalid"
            )
        if any(
            value is not False
            for value in (
                self.consumer_admission_eligible,
                self.point_in_time_evidence,
                self.trainer_evidence,
                self.ledger_source_evidence,
            )
        ):
            raise FeatureSnapshotPublicationIntegrityError(
                "feature_snapshot_artifact_non_consumable_invariant_violated"
            )
        _validated_artifact_binding(self)

    @property
    def artifact_binding(self) -> dict[str, Any]:
        return _validated_artifact_binding(self)


def _validation_error(reason: str) -> NoReturn:
    raise FeatureSnapshotPublicationValidationError(reason)


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            _validation_error("feature_snapshot_duplicate_json_key")
        parsed[key] = value
    return parsed


def _reject_json_constant(value: str) -> NoReturn:
    _validation_error(f"feature_snapshot_non_finite_json_number:{value}")


def _parse_canonical_snapshot_bytes(payload: bytes) -> dict[str, Any]:
    if type(payload) is not bytes:
        _validation_error("feature_snapshot_exact_bytes_required")
    if not payload:
        _validation_error("feature_snapshot_empty_payload_forbidden")
    if len(payload) > MAX_CANONICAL_FEATURE_SNAPSHOT_BYTES:
        _validation_error("feature_snapshot_payload_bytes_exceeded")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise FeatureSnapshotPublicationValidationError("feature_snapshot_utf8_invalid") from exc
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_json_constant,
        )
    except FeatureSnapshotPublicationValidationError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        raise FeatureSnapshotPublicationValidationError("feature_snapshot_json_invalid") from exc
    if type(parsed) is not dict:
        _validation_error("feature_snapshot_top_level_object_required")
    try:
        expected = canonical_json(parsed).encode("ascii")
    except (FeatureSnapshotValidationError, UnicodeError) as exc:
        raise FeatureSnapshotPublicationValidationError(
            "feature_snapshot_strict_json_invalid"
        ) from exc
    if not hmac.compare_digest(payload, expected):
        _validation_error("feature_snapshot_bytes_not_canonical_json")
    return parsed


def _parse_canonical_json_object(
    value: str,
    *,
    maximum: int,
    reason: str,
) -> dict[str, Any]:
    if type(value) is not str:
        raise FeatureSnapshotPublicationIntegrityError(f"{reason}_not_exact_text")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise FeatureSnapshotPublicationIntegrityError(f"{reason}_not_canonical_ascii") from exc
    if not encoded or len(encoded) > maximum:
        raise FeatureSnapshotPublicationIntegrityError(f"{reason}_bytes_invalid")
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_json_constant,
        )
    except (FeatureSnapshotPublicationValidationError, json.JSONDecodeError) as exc:
        raise FeatureSnapshotPublicationIntegrityError(f"{reason}_json_invalid") from exc
    if type(parsed) is not dict:
        raise FeatureSnapshotPublicationIntegrityError(f"{reason}_not_object")
    try:
        if canonical_json(parsed) != value:
            raise FeatureSnapshotPublicationIntegrityError(f"{reason}_not_canonical")
    except FeatureSnapshotValidationError as exc:
        raise FeatureSnapshotPublicationIntegrityError(f"{reason}_strict_json_invalid") from exc
    return parsed


def _strict_text(value: Any, *, reason: str, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or value != value.strip() or pattern.fullmatch(value) is None:
        _validation_error(reason)
    return value


def _strict_native_timeframe(value: Any, *, reason: str) -> str:
    if type(value) is not str or value not in _NATIVE_TIMEFRAME_MS:
        _validation_error(reason)
    return value


def _strict_native_utc_ms(value: Any, *, field: str) -> tuple[str, datetime]:
    """Validate native ``.sssZ`` text and return lossless v3 ``.ssssssZ`` text."""

    if type(value) is not str or not value or value != value.strip():
        _validation_error(f"feature_snapshot_{field}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError) as exc:
        raise FeatureSnapshotPublicationValidationError(
            f"feature_snapshot_{field}_invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _validation_error(f"feature_snapshot_{field}_timezone_required")
    parsed_utc = parsed.astimezone(UTC)
    native_canonical = parsed_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if value != native_canonical or parsed_utc.microsecond % 1_000:
        _validation_error(f"feature_snapshot_{field}_not_canonical_utc")
    normalized = parsed_utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return normalized, parsed_utc


def _strict_v3_utc(value: Any, *, field: str) -> tuple[str, datetime]:
    if type(value) is not str or not value or value != value.strip():
        _validation_error(f"feature_snapshot_{field}_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError) as exc:
        raise FeatureSnapshotPublicationValidationError(
            f"feature_snapshot_{field}_invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _validation_error(f"feature_snapshot_{field}_timezone_required")
    parsed_utc = parsed.astimezone(UTC)
    canonical = parsed_utc.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if value != canonical:
        _validation_error(f"feature_snapshot_{field}_not_canonical_utc")
    return canonical, parsed_utc


def _epoch_us(value: datetime) -> int:
    delta = value - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _timeframe_ms(value: str) -> int:
    try:
        return _NATIVE_TIMEFRAME_MS[value]
    except KeyError as exc:
        raise FeatureSnapshotPublicationValidationError(
            "feature_snapshot_timeframe_invalid"
        ) from exc


def _artifact_integrity_error(reason: str) -> NoReturn:
    raise FeatureSnapshotPublicationIntegrityError(reason)


def _artifact_v3_clock(value: Any, *, field: str) -> tuple[str, datetime]:
    try:
        return _strict_v3_utc(value, field=field)
    except FeatureSnapshotPublicationValidationError as exc:
        raise FeatureSnapshotPublicationIntegrityError(
            f"feature_snapshot_artifact_{field}_invalid"
        ) from exc


def _artifact_exact_text(
    value: Any,
    *,
    reason: str,
    pattern: re.Pattern[str],
) -> str:
    if type(value) is not str or value != value.strip() or pattern.fullmatch(value) is None:
        _artifact_integrity_error(reason)
    return value


def _validated_artifact_binding(
    result: FeatureSnapshotCasArtifact,
) -> dict[str, Any]:
    if type(result.source_payload_store) is not ImmutableSourcePayloadStore:
        _artifact_integrity_error("artifact_result_cas_store_invalid")
    if type(result.artifact_snapshot_bytes) is not bytes:
        _artifact_integrity_error("artifact_result_exact_bytes_required")
    try:
        stored_snapshot = _parse_canonical_snapshot_bytes(result.artifact_snapshot_bytes)
        stored_feature_snapshot_id = stored_snapshot.get("feature_snapshot_id")
        stored_symbol = stored_snapshot.get("symbol")
        stored_timeframe = stored_snapshot.get("timeframe")
        if (
            type(stored_feature_snapshot_id) is not str
            or type(stored_symbol) is not str
            or type(stored_timeframe) is not str
        ):
            _artifact_integrity_error("artifact_result_stored_bytes_native_identity_invalid")
        bound_from_bytes = _validated_native_snapshot(
            stored_snapshot,
            expected_feature_snapshot_id=stored_feature_snapshot_id,
            expected_symbol=stored_symbol,
            expected_timeframe=stored_timeframe,
        )
    except FeatureSnapshotPublicationValidationError as exc:
        raise FeatureSnapshotPublicationIntegrityError(
            "artifact_result_stored_bytes_native_snapshot_invalid"
        ) from exc
    artifact_sha256_from_bytes = hashlib.sha256(result.artifact_snapshot_bytes).hexdigest()
    artifact_byte_count_from_bytes = len(result.artifact_snapshot_bytes)
    try:
        canonical_cas_path = result.source_payload_store.path_for(artifact_sha256_from_bytes)
        stored_readback = result.source_payload_store.get(
            artifact_sha256_from_bytes,
            expected_byte_count=artifact_byte_count_from_bytes,
        )
    except SourcePayloadStoreError as exc:
        raise FeatureSnapshotPublicationIntegrityError(
            "artifact_result_cas_readback_verification_failed"
        ) from exc
    if type(stored_readback) is not bytes or not hmac.compare_digest(
        stored_readback, result.artifact_snapshot_bytes
    ):
        _artifact_integrity_error("artifact_result_cas_readback_bytes_mismatch")

    if type(result.artifact_binding_json) is not str:
        _artifact_integrity_error("artifact_binding_not_exact_text")
    try:
        binding_bytes = result.artifact_binding_json.encode("ascii")
    except UnicodeEncodeError as exc:
        raise FeatureSnapshotPublicationIntegrityError(
            "artifact_binding_not_canonical_ascii"
        ) from exc
    if not binding_bytes or len(binding_bytes) > MAX_CANONICAL_FEATURE_SNAPSHOT_BYTES:
        _artifact_integrity_error("artifact_binding_bytes_invalid")
    binding_cas_sha256 = hashlib.sha256(binding_bytes).hexdigest()
    binding_cas_byte_count = len(binding_bytes)
    expected_binding_relative_path = f"sha256/{binding_cas_sha256[:2]}/{binding_cas_sha256}"
    binding_cas_address = result.artifact_binding_cas_address
    if (
        type(binding_cas_address) is not SourcePayloadAddress
        or binding_cas_address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or binding_cas_address.payload_sha256 != binding_cas_sha256
        or binding_cas_address.payload_byte_count != binding_cas_byte_count
        or binding_cas_address.relative_path != expected_binding_relative_path
    ):
        _artifact_integrity_error("artifact_binding_cas_address_mismatch")
    try:
        canonical_binding_cas_path = result.source_payload_store.path_for(binding_cas_sha256)
        if (
            canonical_binding_cas_path.relative_to(result.source_payload_store.root_path).as_posix()
            != expected_binding_relative_path
        ):
            _artifact_integrity_error("artifact_binding_cas_path_mismatch")
        binding_readback = result.source_payload_store.get(
            binding_cas_sha256,
            expected_byte_count=binding_cas_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise FeatureSnapshotPublicationIntegrityError(
            "artifact_binding_cas_readback_verification_failed"
        ) from exc
    if type(binding_readback) is not bytes or not hmac.compare_digest(
        binding_readback,
        binding_bytes,
    ):
        _artifact_integrity_error("artifact_binding_cas_readback_bytes_mismatch")

    binding = _parse_canonical_json_object(
        result.artifact_binding_json,
        maximum=MAX_CANONICAL_FEATURE_SNAPSHOT_BYTES,
        reason="artifact_binding",
    )
    if frozenset(binding) != _CAS_ARTIFACT_BINDING_KEYS:
        _artifact_integrity_error("artifact_binding_key_contract_mismatch")

    claimed_binding_hash = _artifact_exact_text(
        binding.get("artifact_binding_sha256"),
        reason="artifact_binding_sha256_invalid",
        pattern=_SHA256_RE,
    )
    binding_material = {
        key: value for key, value in binding.items() if key != "artifact_binding_sha256"
    }
    if (
        claimed_binding_hash != result.artifact_binding_sha256
        or claimed_binding_hash != stable_sha256(binding_material)
    ):
        _artifact_integrity_error("artifact_binding_identity_mismatch")

    fixed_literals = {
        "schema_version": CAS_ARTIFACT_BINDING_SCHEMA_VERSION,
        "evidence_classification": CAS_ARTIFACT_EVIDENCE_CLASSIFICATION,
        "artifact_retry_semantics": CAS_ARTIFACT_RETRY_SEMANTICS,
        "native_snapshot_schema_version": NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION,
        "artifact_serialization_schema_version": (CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION),
        "artifact_serialization_origin": (
            "DERIVED_FROM_PARSED_NATIVE_SNAPSHOT_MAPPING_NOT_SOURCE_TRANSPORT_BYTES"
        ),
        "producer_worker_id": NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
        "source": "binance_wss",
    }
    if any(binding.get(key) != value for key, value in fixed_literals.items()):
        _artifact_integrity_error("artifact_binding_fixed_literal_mismatch")
    for key in (
        "consumer_admission_eligible",
        "point_in_time_evidence",
        "trainer_evidence",
        "ledger_source_evidence",
        "source_transport_bytes_verified",
        "is_backfilled",
    ):
        if binding.get(key) is not False:
            _artifact_integrity_error("artifact_binding_non_consumable_literal_mismatch")
    for key in ("cas_put_completed", "cas_exact_readback_verified"):
        if binding.get(key) is not True:
            _artifact_integrity_error("artifact_binding_cas_verification_literal_mismatch")

    claimed_feature_snapshot_id = _artifact_exact_text(
        binding.get("feature_snapshot_id"),
        reason="artifact_binding_feature_snapshot_id_invalid",
        pattern=_FEATURE_SNAPSHOT_ID_RE,
    )
    claimed_symbol = _artifact_exact_text(
        binding.get("symbol"),
        reason="artifact_binding_symbol_invalid",
        pattern=_SYMBOL_RE,
    )
    claimed_timeframe = binding.get("timeframe")
    if type(claimed_timeframe) is not str or claimed_timeframe not in _NATIVE_TIMEFRAME_MS:
        _artifact_integrity_error("artifact_binding_timeframe_invalid")
    claimed_artifact_sha256 = _artifact_exact_text(
        binding.get("artifact_serialization_sha256"),
        reason="artifact_binding_serialization_sha256_invalid",
        pattern=_SHA256_RE,
    )
    claimed_artifact_byte_count = binding.get("artifact_serialization_byte_count")
    if (
        type(claimed_artifact_byte_count) is not int
        or claimed_artifact_byte_count <= 0
        or claimed_artifact_byte_count > MAX_CANONICAL_FEATURE_SNAPSHOT_BYTES
    ):
        _artifact_integrity_error("artifact_binding_serialization_byte_count_invalid")
    claimed_raw_payload_hash = _artifact_exact_text(
        binding.get("raw_payload_hash"),
        reason="artifact_binding_raw_payload_hash_invalid",
        pattern=_SHA256_RE,
    )
    if (
        claimed_feature_snapshot_id != bound_from_bytes["feature_snapshot_id"]
        or claimed_symbol != bound_from_bytes["symbol"]
        or claimed_timeframe != bound_from_bytes["timeframe"]
        or claimed_raw_payload_hash != bound_from_bytes["raw_payload_hash"]
        or claimed_artifact_sha256 != artifact_sha256_from_bytes
        or claimed_artifact_byte_count != artifact_byte_count_from_bytes
    ):
        _artifact_integrity_error("artifact_binding_stored_bytes_identity_mismatch")

    feature_snapshot_id = bound_from_bytes["feature_snapshot_id"]
    symbol = bound_from_bytes["symbol"]
    timeframe = bound_from_bytes["timeframe"]
    artifact_sha256 = artifact_sha256_from_bytes
    artifact_byte_count = artifact_byte_count_from_bytes

    artifact_identity = {
        "schema_version": CAS_ARTIFACT_IDENTITY_SCHEMA_VERSION,
        "feature_snapshot_id": feature_snapshot_id,
        "artifact_serialization_sha256": artifact_sha256,
        "artifact_serialization_byte_count": artifact_byte_count,
        "artifact_serialization_schema_version": (CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION),
        "producer_worker_id": NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
        "symbol": symbol,
        "timeframe": timeframe,
    }
    identity_sha256 = stable_sha256(artifact_identity)
    expected_record_id = "feature_snapshot_cas_artifact_v1_" + identity_sha256
    if (
        binding.get("artifact_identity_sha256") != identity_sha256
        or binding.get("artifact_record_id") != expected_record_id
        or result.artifact_record_id != expected_record_id
        or _CAS_ARTIFACT_RECORD_ID_RE.fullmatch(expected_record_id) is None
    ):
        _artifact_integrity_error("artifact_binding_record_identity_mismatch")

    cas_address = binding.get("cas_address")
    if type(cas_address) is not dict or frozenset(cas_address) != _CAS_ARTIFACT_ADDRESS_KEYS:
        _artifact_integrity_error("artifact_binding_cas_address_contract_mismatch")
    expected_relative_path = f"sha256/{artifact_sha256[:2]}/{artifact_sha256}"
    absolute_path_value = cas_address.get("absolute_path")
    if type(absolute_path_value) is not str or not absolute_path_value:
        _artifact_integrity_error("artifact_binding_cas_absolute_path_invalid")
    absolute_path = Path(absolute_path_value)
    if not absolute_path.is_absolute() or ".." in absolute_path.parts:
        _artifact_integrity_error("artifact_binding_cas_absolute_path_invalid")
    if absolute_path != canonical_cas_path:
        _artifact_integrity_error("artifact_binding_cas_absolute_path_mismatch")
    if (
        type(result.cas_address) is not SourcePayloadAddress
        or cas_address.get("store_schema_version") != SOURCE_PAYLOAD_STORE_SCHEMA_VERSION
        or cas_address.get("address_schema_version") != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or cas_address.get("address_schema_version") != result.cas_address.schema_version
        or cas_address.get("payload_sha256") != artifact_sha256
        or cas_address.get("payload_sha256") != result.cas_address.payload_sha256
        or cas_address.get("payload_byte_count") != artifact_byte_count
        or cas_address.get("payload_byte_count") != result.cas_address.payload_byte_count
        or cas_address.get("relative_path") != expected_relative_path
        or cas_address.get("relative_path") != result.cas_address.relative_path
        or binding.get("cas_exact_readback_sha256") != artifact_sha256
        or binding.get("cas_exact_readback_byte_count") != artifact_byte_count
    ):
        _artifact_integrity_error("artifact_binding_cas_content_crosslink_mismatch")

    source_lineage_from_bytes = {
        "candle_open_time": bound_from_bytes["candle_open_time"],
        "candle_close_time": bound_from_bytes["candle_close_time"],
        "source_event_time": bound_from_bytes["event_time"],
        "source_ingested_at": bound_from_bytes["ingested_at"],
        "source_available_at": bound_from_bytes["source_available_at"],
        "feature_cutoff": bound_from_bytes["feature_cutoff"],
        "generated_at": bound_from_bytes["generated_at"],
        "source_sequence_id": bound_from_bytes["source_sequence_id"],
        "raw_payload_hash": bound_from_bytes["raw_payload_hash"],
    }
    if any(binding.get(key) != expected for key, expected in source_lineage_from_bytes.items()):
        _artifact_integrity_error("artifact_binding_stored_bytes_source_lineage_mismatch")

    parsed_clocks: dict[str, datetime] = {}
    for field in (
        "candle_open_time",
        "candle_close_time",
        "source_event_time",
        "source_ingested_at",
        "source_available_at",
        "feature_cutoff",
        "generated_at",
    ):
        _canonical, parsed_clocks[field] = _artifact_v3_clock(
            binding.get(field),
            field=field,
        )
    native_epoch_us = tuple(
        _epoch_us(parsed_clocks[field])
        for field in (
            "candle_open_time",
            "candle_close_time",
            "source_event_time",
            "source_ingested_at",
            "source_available_at",
            "feature_cutoff",
            "generated_at",
        )
    )
    if any(value <= 0 or value % 1_000 for value in native_epoch_us):
        _artifact_integrity_error("artifact_binding_native_epoch_clock_invalid")
    candle_open_us = _epoch_us(parsed_clocks["candle_open_time"])
    candle_close_us = _epoch_us(parsed_clocks["candle_close_time"])
    event_us = _epoch_us(parsed_clocks["source_event_time"])
    ingested_us = _epoch_us(parsed_clocks["source_ingested_at"])
    source_available_us = _epoch_us(parsed_clocks["source_available_at"])
    feature_cutoff_us = _epoch_us(parsed_clocks["feature_cutoff"])
    generated_us = _epoch_us(parsed_clocks["generated_at"])
    timeframe_us = _NATIVE_TIMEFRAME_MS[timeframe] * 1_000
    if (
        candle_open_us % timeframe_us != 0
        or candle_close_us != candle_open_us + timeframe_us - 1_000
        or feature_cutoff_us != candle_close_us
        or not candle_close_us <= event_us <= ingested_us <= source_available_us
        or source_available_us != max(candle_close_us, event_us, ingested_us)
        or source_available_us > generated_us
    ):
        _artifact_integrity_error("artifact_binding_temporal_contract_mismatch")
    source_sequence_id = binding.get("source_sequence_id")
    if (
        type(source_sequence_id) is not str
        or not source_sequence_id.isdigit()
        or int(source_sequence_id) <= 0
        or source_sequence_id != str(event_us // 1_000)
    ):
        _artifact_integrity_error("artifact_binding_source_sequence_mismatch")
    return binding


def _expected_native_snapshot_id(snapshot: Mapping[str, Any]) -> str:
    material = dict(snapshot)
    material.pop("feature_snapshot_id", None)
    try:
        # This is the native producer's existing ID ABI.  The publication
        # content hash below separately covers the compact canonical bytes.
        encoded = json.dumps(
            material,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FeatureSnapshotPublicationValidationError(
            "feature_snapshot_id_material_invalid"
        ) from exc
    return f"v2_fsnap_{hashlib.sha256(encoded).hexdigest()}"


def _validated_native_snapshot(
    snapshot: dict[str, Any],
    *,
    expected_feature_snapshot_id: str,
    expected_symbol: str,
    expected_timeframe: str,
) -> dict[str, str]:
    feature_snapshot_id = _strict_text(
        snapshot.get("feature_snapshot_id"),
        reason="feature_snapshot_id_invalid",
        pattern=_FEATURE_SNAPSHOT_ID_RE,
    )
    external_snapshot_id = _strict_text(
        expected_feature_snapshot_id,
        reason="expected_feature_snapshot_id_invalid",
        pattern=_FEATURE_SNAPSHOT_ID_RE,
    )
    symbol = _strict_text(
        snapshot.get("symbol"),
        reason="feature_snapshot_symbol_invalid",
        pattern=_SYMBOL_RE,
    )
    external_symbol = _strict_text(
        expected_symbol,
        reason="expected_feature_snapshot_symbol_invalid",
        pattern=_SYMBOL_RE,
    )
    timeframe = _strict_native_timeframe(
        snapshot.get("timeframe"),
        reason="feature_snapshot_timeframe_invalid",
    )
    external_timeframe = _strict_native_timeframe(
        expected_timeframe,
        reason="expected_feature_snapshot_timeframe_invalid",
    )
    if snapshot.get("schema_version") != NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION:
        _validation_error("feature_snapshot_native_schema_mismatch")
    if snapshot.get("worker_id") != NATIVE_FEATURE_SNAPSHOT_WORKER_ID:
        _validation_error("feature_snapshot_native_worker_mismatch")
    if symbol != external_symbol:
        _validation_error("feature_snapshot_expected_symbol_mismatch")
    if timeframe != external_timeframe:
        _validation_error("feature_snapshot_expected_timeframe_mismatch")
    if feature_snapshot_id != external_snapshot_id:
        _validation_error("feature_snapshot_expected_id_mismatch")
    if feature_snapshot_id != _expected_native_snapshot_id(snapshot):
        _validation_error("feature_snapshot_content_id_mismatch")

    forbidden = sorted(
        key
        for key in snapshot
        if key in _RESERVED_NATIVE_SNAPSHOT_ARTIFACT_FIELDS
        or key.startswith(_RESERVED_NATIVE_SNAPSHOT_ARTIFACT_PREFIXES)
    )
    if forbidden:
        _validation_error("feature_snapshot_reserved_artifact_fields:" + ",".join(forbidden))
    if snapshot.get("available_at") is not None:
        _validation_error("feature_snapshot_available_at_self_attested")
    if snapshot.get("feature_available_at") is not None:
        _validation_error("feature_snapshot_feature_available_at_self_attested")
    if snapshot.get("exact_feature_availability_valid") is not False:
        _validation_error("feature_snapshot_exact_availability_self_attested")
    if snapshot.get("exact_feature_availability_rejection_reasons") != [
        "FEATURE_PUBLICATION_RECEIPT_REQUIRED"
    ]:
        _validation_error("feature_snapshot_publication_receipt_hold_missing")
    if snapshot.get("required_model_feature_pit_coverage_valid") is not False:
        _validation_error("feature_snapshot_required_feature_pit_hold_not_false")
    if snapshot.get("required_model_feature_pit_rejection_reasons") != [
        "REQUIRED_MODEL_FEATURE_PIT_LEDGER_REQUIRED"
    ]:
        _validation_error("feature_snapshot_required_feature_pit_hold_reason_invalid")
    if snapshot.get("ohlcv_history_payload_receipts_valid") is not False:
        _validation_error("feature_snapshot_ohlcv_receipt_hold_not_false")
    if snapshot.get("ohlcv_history_payload_receipt_rejection_reasons") != [
        "IMMUTABLE_OHLCV_HISTORY_PAYLOAD_RECEIPTS_REQUIRED"
    ]:
        _validation_error("feature_snapshot_ohlcv_receipt_hold_reason_invalid")
    for flag in ("trainer_consumable", "valid_for_prediction", "valid_for_paper"):
        if snapshot.get(flag) is not False:
            _validation_error(f"feature_snapshot_{flag}_self_attested")

    if snapshot.get("source") != "binance_wss":
        _validation_error("feature_snapshot_exact_source_invalid")
    if snapshot.get("is_backfilled") is not False:
        _validation_error("feature_snapshot_backfill_not_exact_observation")
    if snapshot.get("exact_source_clock_valid") is not True:
        _validation_error("feature_snapshot_exact_source_clock_not_valid")
    if snapshot.get("exact_source_clock_rejection_reasons") != []:
        _validation_error("feature_snapshot_exact_source_clock_rejections_present")
    raw_payload_hash = _strict_text(
        snapshot.get("raw_payload_hash"),
        reason="feature_snapshot_raw_payload_hash_invalid",
        pattern=_SHA256_RE,
    )

    clocks: dict[str, str] = {}
    parsed_clocks: dict[str, datetime] = {}
    for field in (*_SOURCE_CLOCK_FIELDS, "feature_cutoff", "generated_at"):
        canonical, parsed = _strict_native_utc_ms(snapshot.get(field), field=field)
        clocks[field] = canonical
        parsed_clocks[field] = parsed

    candle_open_us = _epoch_us(parsed_clocks["candle_open_time"])
    candle_close_us = _epoch_us(parsed_clocks["candle_close_time"])
    event_us = _epoch_us(parsed_clocks["event_time"])
    ingested_us = _epoch_us(parsed_clocks["ingested_at"])
    source_available_us = _epoch_us(parsed_clocks["source_available_at"])
    feature_cutoff_us = _epoch_us(parsed_clocks["feature_cutoff"])
    generated_us = _epoch_us(parsed_clocks["generated_at"])
    native_epoch_values = (
        candle_open_us,
        candle_close_us,
        event_us,
        ingested_us,
        source_available_us,
        feature_cutoff_us,
        generated_us,
    )
    if any(value <= 0 for value in native_epoch_values):
        _validation_error("feature_snapshot_native_epoch_clock_not_positive")
    if any(value % 1_000 for value in native_epoch_values):
        _validation_error("feature_snapshot_source_clock_not_exact_millisecond")
    timeframe_ms = _timeframe_ms(timeframe)
    candle_open_ms = candle_open_us // 1_000
    candle_close_ms = candle_close_us // 1_000
    if candle_open_ms % timeframe_ms != 0:
        _validation_error("feature_snapshot_candle_open_not_timeframe_aligned")
    if candle_close_ms != candle_open_ms + timeframe_ms - 1:
        _validation_error("feature_snapshot_candle_interval_invalid")
    if feature_cutoff_us != candle_close_us:
        _validation_error("feature_snapshot_feature_cutoff_not_candle_close")
    if not candle_close_us <= event_us <= ingested_us <= source_available_us:
        _validation_error("feature_snapshot_source_clock_order_invalid")
    if source_available_us != max(candle_close_us, event_us, ingested_us):
        _validation_error("feature_snapshot_source_available_not_canonical_max")
    if source_available_us > generated_us:
        _validation_error("feature_snapshot_source_available_after_generated_at")

    source_sequence_id = snapshot.get("source_sequence_id")
    if (
        type(source_sequence_id) is not str
        or not source_sequence_id.isdigit()
        or int(source_sequence_id) <= 0
        or source_sequence_id != str(event_us // 1_000)
    ):
        _validation_error("feature_snapshot_source_sequence_event_mismatch")
    return {
        "candle_open_time": clocks["candle_open_time"],
        "candle_close_time": clocks["candle_close_time"],
        "event_time": clocks["event_time"],
        "ingested_at": clocks["ingested_at"],
        "source_available_at": clocks["source_available_at"],
        "feature_cutoff": clocks["feature_cutoff"],
        "generated_at": clocks["generated_at"],
        "feature_snapshot_id": feature_snapshot_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "raw_payload_hash": raw_payload_hash,
        "source_sequence_id": source_sequence_id,
    }


def _exact_cas_address(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
    *,
    payload_sha256: str,
    payload_byte_count: int,
) -> tuple[str, str]:
    if type(address) is not SourcePayloadAddress:
        raise FeatureSnapshotPublicationIntegrityError("feature_snapshot_cas_address_type_invalid")
    expected_relative_path = f"sha256/{payload_sha256[:2]}/{payload_sha256}"
    if address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION:
        raise FeatureSnapshotPublicationIntegrityError(
            "feature_snapshot_cas_address_schema_mismatch"
        )
    if address.payload_sha256 != payload_sha256:
        raise FeatureSnapshotPublicationIntegrityError(
            "feature_snapshot_cas_address_sha256_mismatch"
        )
    if address.payload_byte_count != payload_byte_count:
        raise FeatureSnapshotPublicationIntegrityError(
            "feature_snapshot_cas_address_byte_count_mismatch"
        )
    if address.relative_path != expected_relative_path:
        raise FeatureSnapshotPublicationIntegrityError(
            "feature_snapshot_cas_address_relative_path_mismatch"
        )
    expected_absolute_path = store.path_for(payload_sha256)
    if not expected_absolute_path.is_absolute():
        raise FeatureSnapshotPublicationIntegrityError("feature_snapshot_cas_address_not_absolute")
    try:
        relative_from_root = expected_absolute_path.relative_to(store.root_path).as_posix()
    except ValueError as exc:
        raise FeatureSnapshotPublicationIntegrityError(
            "feature_snapshot_cas_address_outside_store_root"
        ) from exc
    if relative_from_root != expected_relative_path:
        raise FeatureSnapshotPublicationIntegrityError(
            "feature_snapshot_cas_address_store_path_mismatch"
        )
    return expected_relative_path, expected_absolute_path.as_posix()


def create_feature_snapshot_cas_artifact(
    *,
    source_payload_store: ImmutableSourcePayloadStore,
    artifact_snapshot_bytes: bytes,
    expected_feature_snapshot_id: str,
    expected_symbol: str,
    expected_timeframe: str,
) -> FeatureSnapshotCasArtifact:
    """Store and read back one derived, non-consumable snapshot artifact.

    ``artifact_snapshot_bytes`` are the new serialization produced by
    :func:`canonical_feature_snapshot_bytes`; they are not claimed to be the
    original Redis/file payload bytes.  The artifact and binding receive fresh
    exact CAS readbacks, but no historical observation timestamp is emitted
    because this local CAS cannot independently prove a wall-clock sample.
    Snapshot-provided availability and PIT claims are rejected, and this
    function emits no source receipt or trainer/ledger admission evidence.
    """

    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _validation_error("feature_snapshot_exact_cas_store_required")
    snapshot = _parse_canonical_snapshot_bytes(artifact_snapshot_bytes)
    bound = _validated_native_snapshot(
        snapshot,
        expected_feature_snapshot_id=expected_feature_snapshot_id,
        expected_symbol=expected_symbol,
        expected_timeframe=expected_timeframe,
    )
    content_sha256 = hashlib.sha256(artifact_snapshot_bytes).hexdigest()
    content_byte_count = len(artifact_snapshot_bytes)

    address = source_payload_store.put(
        artifact_snapshot_bytes,
        expected_sha256=content_sha256,
        expected_byte_count=content_byte_count,
    )
    relative_path, absolute_path = _exact_cas_address(
        source_payload_store,
        address,
        payload_sha256=content_sha256,
        payload_byte_count=content_byte_count,
    )
    readback = source_payload_store.get(
        content_sha256,
        expected_byte_count=content_byte_count,
    )
    if type(readback) is not bytes:
        raise FeatureSnapshotPublicationIntegrityError(
            "feature_snapshot_cas_readback_not_exact_bytes"
        )
    if len(readback) != content_byte_count:
        raise FeatureSnapshotPublicationIntegrityError("feature_snapshot_cas_readback_truncated")
    if hashlib.sha256(readback).hexdigest() != content_sha256:
        raise FeatureSnapshotPublicationIntegrityError(
            "feature_snapshot_cas_readback_sha256_mismatch"
        )
    if not hmac.compare_digest(readback, artifact_snapshot_bytes):
        raise FeatureSnapshotPublicationIntegrityError(
            "feature_snapshot_cas_readback_bytes_mismatch"
        )

    artifact_identity = {
        "schema_version": CAS_ARTIFACT_IDENTITY_SCHEMA_VERSION,
        "feature_snapshot_id": bound["feature_snapshot_id"],
        "artifact_serialization_sha256": content_sha256,
        "artifact_serialization_byte_count": content_byte_count,
        "artifact_serialization_schema_version": (CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION),
        "producer_worker_id": NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
        "symbol": bound["symbol"],
        "timeframe": bound["timeframe"],
    }
    artifact_record_id = "feature_snapshot_cas_artifact_v1_" + stable_sha256(artifact_identity)
    artifact_material: dict[str, Any] = {
        "schema_version": CAS_ARTIFACT_BINDING_SCHEMA_VERSION,
        "artifact_record_id": artifact_record_id,
        "artifact_identity_sha256": stable_sha256(artifact_identity),
        "evidence_classification": CAS_ARTIFACT_EVIDENCE_CLASSIFICATION,
        "artifact_retry_semantics": CAS_ARTIFACT_RETRY_SEMANTICS,
        "consumer_admission_eligible": False,
        "point_in_time_evidence": False,
        "trainer_evidence": False,
        "ledger_source_evidence": False,
        "source_transport_bytes_verified": False,
        "feature_snapshot_id": bound["feature_snapshot_id"],
        "native_snapshot_schema_version": NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION,
        "artifact_serialization_schema_version": (CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION),
        "artifact_serialization_origin": (
            "DERIVED_FROM_PARSED_NATIVE_SNAPSHOT_MAPPING_NOT_SOURCE_TRANSPORT_BYTES"
        ),
        "artifact_serialization_sha256": content_sha256,
        "artifact_serialization_byte_count": content_byte_count,
        "producer_worker_id": NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
        "symbol": bound["symbol"],
        "timeframe": bound["timeframe"],
        "candle_open_time": bound["candle_open_time"],
        "candle_close_time": bound["candle_close_time"],
        "source_event_time": bound["event_time"],
        "source_ingested_at": bound["ingested_at"],
        "source_available_at": bound["source_available_at"],
        "feature_cutoff": bound["feature_cutoff"],
        "generated_at": bound["generated_at"],
        "source": "binance_wss",
        "is_backfilled": False,
        "source_sequence_id": bound["source_sequence_id"],
        "raw_payload_hash": bound["raw_payload_hash"],
        "cas_address": {
            "store_schema_version": SOURCE_PAYLOAD_STORE_SCHEMA_VERSION,
            "address_schema_version": address.schema_version,
            "payload_sha256": address.payload_sha256,
            "payload_byte_count": address.payload_byte_count,
            "relative_path": relative_path,
            "absolute_path": absolute_path,
        },
        "cas_put_completed": True,
        "cas_exact_readback_verified": True,
        "cas_exact_readback_sha256": content_sha256,
        "cas_exact_readback_byte_count": content_byte_count,
    }
    artifact_binding_sha256 = stable_sha256(artifact_material)
    artifact_binding = {
        **artifact_material,
        "artifact_binding_sha256": artifact_binding_sha256,
    }
    if _CAS_ARTIFACT_RECORD_ID_RE.fullmatch(artifact_record_id) is None:
        raise FeatureSnapshotPublicationIntegrityError(
            "feature_snapshot_cas_artifact_record_id_invalid"
        )
    artifact_json = canonical_json(artifact_binding)
    artifact_binding_bytes = artifact_json.encode("ascii")
    artifact_binding_cas_sha256 = hashlib.sha256(artifact_binding_bytes).hexdigest()
    artifact_binding_cas_byte_count = len(artifact_binding_bytes)
    artifact_binding_cas_address = source_payload_store.put(
        artifact_binding_bytes,
        expected_sha256=artifact_binding_cas_sha256,
        expected_byte_count=artifact_binding_cas_byte_count,
    )
    _binding_relative_path, _binding_absolute_path = _exact_cas_address(
        source_payload_store,
        artifact_binding_cas_address,
        payload_sha256=artifact_binding_cas_sha256,
        payload_byte_count=artifact_binding_cas_byte_count,
    )
    artifact_binding_readback = source_payload_store.get(
        artifact_binding_cas_sha256,
        expected_byte_count=artifact_binding_cas_byte_count,
    )
    if type(artifact_binding_readback) is not bytes or not hmac.compare_digest(
        artifact_binding_readback,
        artifact_binding_bytes,
    ):
        raise FeatureSnapshotPublicationIntegrityError(
            "feature_snapshot_artifact_binding_cas_readback_mismatch"
        )
    return FeatureSnapshotCasArtifact(
        artifact_record_id=artifact_record_id,
        artifact_binding_sha256=artifact_binding_sha256,
        artifact_binding_json=artifact_json,
        cas_address=address,
        artifact_binding_cas_address=artifact_binding_cas_address,
        artifact_snapshot_bytes=artifact_snapshot_bytes,
        source_payload_store=source_payload_store,
    )


def canonical_feature_snapshot_bytes(snapshot: Mapping[str, Any]) -> bytes:
    """Create the CAS artifact's new canonical serialization.

    The returned bytes are derived from a parsed mapping.  They are not proof
    of the exact bytes originally stored in or read from Redis/a file, even if
    their decoded JSON values happen to be equivalent.  This helper does not
    attest source availability, PIT lineage, trainer eligibility, or ledger
    admission and does not publish anything.
    """

    if type(snapshot) is not dict:
        _validation_error("feature_snapshot_plain_dict_required")
    try:
        return canonical_json(snapshot).encode("ascii")
    except (FeatureSnapshotValidationError, UnicodeError) as exc:
        raise FeatureSnapshotPublicationValidationError(
            "feature_snapshot_strict_json_invalid"
        ) from exc
