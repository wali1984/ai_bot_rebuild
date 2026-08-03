"""Audit-only candidate for a future authenticated 446-slot capture.

This module closes a structural gap without claiming that the gap is already
authenticated.  It binds the pinned feature-source registry, one complete
``feature_resolution_trace_v4`` artifact, and caller-supplied identities for
the exact CAS object, receipt, and attestation associated with every model
slot.  Slot leaves are bound in ABI order by a domain-separated hash chain.

The current source-evidence profiles cannot authenticate all 40 configured
source families or replay every transform.  Consequently this v4 artifact is
explicitly an *unauthenticated capture candidate*.  Receipt, attestation, and
trust-anchor values in it are declarations only.  No CAS object is opened, no
signature is verified, and no source or transform semantics are replayed.
Every publication, trainer, prediction, paper, and live authority is frozen
false in both the object and its canonical JSON.

Typed-negative observations are allowed only for ABI slots classified as
``OPTIONAL_EVENT_DEPENDENT``.  They carry ``None`` for the selected value; a
numeric zero is never represented as negative source evidence.  Required
slots must always have a resolved observation.  These rules are structural
and do not make an optional negative authenticated.

There is no I/O, clock read, mutable registry lookup, freshness window,
market threshold, service wiring, or execution behavior in this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.feature_resolution_observation_v4 import (
    RESOLUTION_STATUS_RESOLVED,
    RESOLUTION_STATUS_TYPED_NEGATIVE,
)
from v2.backend.app.services.native_trainer.feature_resolution_trace_v4 import (
    FeatureResolutionTraceArtifactV4,
    FeatureResolutionTraceV4ValidationError,
    validate_feature_resolution_trace_v4,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT,
    FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT,
    FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
    REQUIREMENT_OPTIONAL_EVENT_DEPENDENT,
    FeatureSourceRegistryV4,
    FeatureSourceRegistryV4ValidationError,
    feature_source_registry_v4_contract,
)

AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SCHEMA_VERSION: Final = (
    "trainer_authenticated_feature_resolution_capture_candidate_v4"
)
AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SLOT_SCHEMA_VERSION: Final = (
    "trainer_authenticated_feature_resolution_slot_candidate_v4"
)
AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_EVIDENCE_CLASSIFICATION: Final = (
    "AUDIT_ONLY_UNAUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_CANDIDATE_UNWIRED"
)
AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_DOWNSTREAM_STATUS: Final = (
    "NON_CONSUMABLE_NO_AUTHENTICATED_SOURCE_SCOPE_FEATURE_PUBLICATION_TRAINER_"
    "PREDICTION_PAPER_OR_LIVE_AUTHORIZATION"
)
AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CHAIN_DOMAIN: Final = (
    "v2/native-trainer/authenticated-feature-resolution-capture-candidate/v4"
)

SOURCE_EVIDENCE_CAS_NAMESPACE_V4: Final = "trainer-source-payload-cas-v1"
POSITIVE_SOURCE_READ_RECEIPT_KIND_V4: Final = "POSITIVE_SOURCE_READ_RECEIPT"
OPTIONAL_TYPED_NEGATIVE_RECEIPT_KIND_V4: Final = "OPTIONAL_TYPED_NEGATIVE_RECEIPT"

# Resource-integrity ceilings only.  They do not select data or alter market,
# risk, leverage, margin, freshness, or trainer-admission behavior.
MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_BYTES: Final = 8 * 1024 * 1024
MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_DEPTH: Final = 16
MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_NODES: Final = 100_000
MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CONTAINER_ITEMS: Final = 2_048
MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_STRING_BYTES: Final = 2 * 1024 * 1024
MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_KEY_BYTES: Final = 256
MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_TOTAL_TEXT_BYTES: Final = 8 * 1024 * 1024
MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_PAYLOAD_BYTES: Final = 256 * 1024 * 1024

_MIN_JSON_INTEGER = -(2**63)
_MAX_JSON_INTEGER = 2**63 - 1
_CONSTRUCTION_TOKEN = object()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_FLOAT32_HEX_RE = re.compile(r"^[0-9a-f]{8}$", re.ASCII)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,255}$", re.ASCII)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_CAS_ADDRESS_RE = re.compile(r"^sha256/[0-9a-f]{2}/[0-9a-f]{64}$", re.ASCII)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_FIXED_FALSE_FIELDS = (
    "runtime_source_reads_performed",
    "source_registry_authenticated",
    "resolver_branch_capture_authenticated",
    "source_receipts_authenticated",
    "source_attestations_authenticated",
    "raw_cas_payloads_reopened_and_verified",
    "source_semantics_replayed",
    "transform_registry_authenticated",
    "authenticated_optional_typed_negative_complete",
    "source_scope_complete",
    "per_field_receipts_complete",
    "authentication_complete",
    "feature_snapshot_published",
    "feature_publication_authorized",
    "consumer_eligible",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_wired",
)

_RESOLVER_BRANCH_FIELDS = frozenset(
    {
        "resolved_source_label",
        "selected_payload",
        "selected_key",
        "selected_path",
        "selected_alias",
        "resolver_version",
        "resolver_code_sha256",
        "resolver_config_sha256",
    }
)
_TRANSFORM_FIELDS = frozenset(
    {
        "transform_id",
        "transform_version",
        "transform_code_sha256",
        "transform_config_sha256",
        "resolved_value_float32_be_hex",
    }
)
_SOURCE_EVIDENCE_FIELDS = frozenset(
    {
        "raw_cas_namespace",
        "raw_cas_address",
        "raw_payload_sha256",
        "raw_payload_byte_count",
        "source_evidence_receipt_kind",
        "source_evidence_receipt_schema_version",
        "source_evidence_receipt_sha256",
        "source_attestation_schema_version",
        "source_attestation_sha256",
        "attested_material_sha256",
        "declared_trust_anchor_id",
        "declared_public_key_sha256",
        "source_receipt_authentication_verified",
        "source_attestation_authentication_verified",
        "raw_cas_payload_verified",
        "source_semantics_verified",
    }
)
_CLOCK_FIELDS = frozenset(
    {
        "event_time",
        "ingested_at",
        "available_at",
        "generated_at",
        "feature_cutoff",
        "decision_time",
        "masa_feature_cutoff",
        "execution_time",
        "consumer_observed_at",
        "candle_close_time",
        "candle_final",
    }
)
_SLOT_FIELDS = frozenset(
    {
        "schema_version",
        "ordinal",
        "feature_name",
        "configured_source_label",
        "requirement_class",
        "resolution_status",
        "negative_reason",
        "resolver_branch",
        "transform",
        "source_evidence",
        "clocks",
        "trace_slot_observation_sha256",
        "optional_typed_negative_authentication_verified",
        "slot_capture_sha256",
    }
)
_CAPTURE_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "feature_abi_sha256",
        "feature_requirement_policy_id",
        "feature_source_registry_sha256",
        "feature_resolution_trace_sha256",
        "feature_slot_count",
        "required_slot_count",
        "optional_slot_count",
        "resolution_trace",
        "slot_captures",
        "ordered_slot_capture_chain_sha256",
        "resolved_slot_count",
        "declared_optional_typed_negative_slot_count",
        "required_typed_negative_slot_count",
        "complete_slot_capture_set",
        "declared_point_in_time_order_valid",
        "required_value_contract_valid",
        "capture_candidate_only",
        "audit_only",
        *_FIXED_FALSE_FIELDS,
        "capture_sha256",
    }
)


class AuthenticatedFeatureResolutionCaptureV4ValidationError(ValueError):
    """A capture candidate is malformed, incomplete, or overclaims trust."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise AuthenticatedFeatureResolutionCaptureV4ValidationError(*reasons) from None


def _valid_label(value: object) -> bool:
    return type(value) is str and value.isascii() and _LABEL_RE.fullmatch(value) is not None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _parse_clock(value: object, *, field_name: str) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _fail(f"AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_{field_name.upper()}_INVALID")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        _fail(f"AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_{field_name.upper()}_INVALID")
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if parsed < _EPOCH or canonical != value:
        _fail(f"AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_{field_name.upper()}_INVALID")
    return parsed


def _parse_json_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 19:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_INTEGER_OUT_OF_RANGE")
    try:
        parsed = int(value)
    except ValueError:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_INTEGER_OUT_OF_RANGE")
    if not _MIN_JSON_INTEGER <= parsed <= _MAX_JSON_INTEGER:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_INTEGER_OUT_OF_RANGE")
    return parsed


def _parse_json_float(value: str) -> float:
    if len(value) > 64:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_FLOAT_INVALID")
    try:
        parsed = float(value)
    except ValueError:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_FLOAT_INVALID")
    if not math.isfinite(parsed):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_FLOAT_INVALID")
    return parsed


def _reject_json_constant(_value: str) -> NoReturn:
    _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_CONSTANT_FORBIDDEN")


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _bounded_snapshot(value: object) -> object:
    nodes = 0
    text_bytes = 0

    def visit(item: object, depth: int) -> object:
        nonlocal nodes, text_bytes
        nodes += 1
        if nodes > MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_NODES:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_NODE_LIMIT_EXCEEDED")
        if depth > MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_DEPTH:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_DEPTH_LIMIT_EXCEEDED")
        if item is None or type(item) is bool:
            return item
        if type(item) is int:
            integer = item
            if not _MIN_JSON_INTEGER <= integer <= _MAX_JSON_INTEGER:
                _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_INTEGER_OUT_OF_RANGE")
            return integer
        if type(item) is float:
            number = item
            if not math.isfinite(number):
                _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_FLOAT_INVALID")
            return number
        if type(item) is str:
            text = item
            try:
                encoded = text.encode("ascii", errors="strict")
            except UnicodeEncodeError:
                _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_TEXT_INVALID")
            if len(encoded) > MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_STRING_BYTES:
                _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_STRING_LIMIT_EXCEEDED")
            text_bytes += len(encoded)
            if text_bytes > MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_TOTAL_TEXT_BYTES:
                _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_TEXT_LIMIT_EXCEEDED")
            return text
        if type(item) is list:
            values = cast(list[object], item)
            if len(values) > MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CONTAINER_ITEMS:
                _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_CONTAINER_LIMIT_EXCEEDED")
            return [visit(child, depth + 1) for child in values]
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            if len(mapping) > MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CONTAINER_ITEMS:
                _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_CONTAINER_LIMIT_EXCEEDED")
            detached: dict[str, object] = {}
            for key, child in mapping.items():
                if type(key) is not str:
                    _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_KEY_INVALID")
                try:
                    encoded_key = key.encode("ascii", errors="strict")
                except UnicodeEncodeError:
                    _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_KEY_INVALID")
                if not encoded_key or len(encoded_key) > (
                    MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_KEY_BYTES
                ):
                    _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_KEY_INVALID")
                text_bytes += len(encoded_key)
                if text_bytes > MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_TOTAL_TEXT_BYTES:
                    _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_TEXT_LIMIT_EXCEEDED")
                detached[key] = visit(child, depth + 1)
            return detached
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_TYPE_INVALID")

    try:
        return visit(value, 0)
    except RecursionError:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_DEPTH_LIMIT_EXCEEDED")


def _canonical_json(value: object) -> str:
    snapshot = _bounded_snapshot(value)
    try:
        encoded = json.dumps(
            snapshot,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_NOT_STRICT_JSON")
    if len(encoded.encode("ascii")) > MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_BYTES:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SIZE_LIMIT_EXCEEDED")
    return encoded


def _parse_json(value: object) -> dict[str, Any]:
    if type(value) is bytes:
        raw = bytes(value)
        try:
            text = raw.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_INVALID")
    elif type(value) is str:
        text = value
        try:
            raw = text.encode("ascii", errors="strict")
        except UnicodeEncodeError:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_INVALID")
    else:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_INVALID")
    if not raw or len(raw) > MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_BYTES:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_INVALID")
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_int=_parse_json_int,
            parse_float=_parse_json_float,
            parse_constant=_reject_json_constant,
        )
    except AuthenticatedFeatureResolutionCaptureV4ValidationError:
        raise
    except (json.JSONDecodeError, OverflowError, RecursionError, TypeError, ValueError):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_INVALID")
    if type(parsed) is not dict:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_NOT_EXACT_OBJECT")
    detached = cast(dict[str, Any], _bounded_snapshot(parsed))
    if _canonical_json(detached) != text:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_NOT_CANONICAL")
    return detached


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _exact_dict(value: object, fields: frozenset[str], reason: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(reason)
    mapping = cast(dict[object, object], value)
    if any(type(key) is not str for key in mapping) or frozenset(mapping) != fields:
        _fail(reason)
    return cast(dict[str, Any], dict(mapping))


def _float32_be_hex(value: object) -> str:
    if type(value) is not float or not math.isfinite(value):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RESOLVED_VALUE_INVALID")
    try:
        packed = struct.pack("!f", value)
        runtime = float(struct.unpack("!f", packed)[0])
    except (OverflowError, struct.error, TypeError, ValueError):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RESOLVED_VALUE_INVALID")
    if runtime != value or (value == 0.0 and math.copysign(1.0, value) < 0.0):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RESOLVED_VALUE_INVALID")
    return packed.hex()


@dataclass(frozen=True, slots=True)
class FeatureResolutionEvidenceReferenceV4:
    """Factory-only declared identity bundle; no field is authenticated here."""

    ordinal: int
    feature_name: str
    raw_cas_namespace: str
    raw_cas_address: str
    raw_payload_sha256: str
    raw_payload_byte_count: int
    source_evidence_receipt_kind: str
    source_evidence_receipt_schema_version: str
    source_evidence_receipt_sha256: str
    source_attestation_schema_version: str
    source_attestation_sha256: str
    attested_material_sha256: str
    declared_trust_anchor_id: str
    declared_public_key_sha256: str
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_FACTORY_CONSTRUCTION_REQUIRED")
        _validate_evidence_reference(self)


def _validate_evidence_reference(reference: FeatureResolutionEvidenceReferenceV4) -> None:
    if (
        type(reference.ordinal) is not int
        or not 0 <= reference.ordinal < FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
    ):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_EVIDENCE_ORDINAL_INVALID")
    for value, reason in (
        (reference.feature_name, "EVIDENCE_FEATURE_NAME_INVALID"),
        (reference.raw_cas_namespace, "CAS_NAMESPACE_INVALID"),
        (reference.source_evidence_receipt_schema_version, "RECEIPT_SCHEMA_INVALID"),
        (reference.source_attestation_schema_version, "ATTESTATION_SCHEMA_INVALID"),
        (reference.declared_trust_anchor_id, "TRUST_ANCHOR_ID_INVALID"),
    ):
        if not _valid_label(value):
            _fail(f"AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_{reason}")
    if reference.raw_cas_namespace != SOURCE_EVIDENCE_CAS_NAMESPACE_V4:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CAS_NAMESPACE_INVALID")
    if type(
        reference.source_evidence_receipt_kind
    ) is not str or reference.source_evidence_receipt_kind not in (
        POSITIVE_SOURCE_READ_RECEIPT_KIND_V4,
        OPTIONAL_TYPED_NEGATIVE_RECEIPT_KIND_V4,
    ):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RECEIPT_KIND_INVALID")
    for value, reason in (
        (reference.raw_payload_sha256, "RAW_PAYLOAD_SHA256_INVALID"),
        (reference.source_evidence_receipt_sha256, "RECEIPT_SHA256_INVALID"),
        (reference.source_attestation_sha256, "ATTESTATION_SHA256_INVALID"),
        (reference.attested_material_sha256, "ATTESTED_MATERIAL_SHA256_INVALID"),
        (reference.declared_public_key_sha256, "PUBLIC_KEY_SHA256_INVALID"),
    ):
        if not _valid_sha256(value):
            _fail(f"AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_{reason}")
    if (
        type(reference.raw_payload_byte_count) is not int
        or not 1
        <= reference.raw_payload_byte_count
        <= MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_PAYLOAD_BYTES
    ):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RAW_PAYLOAD_BYTE_COUNT_INVALID")
    expected_address = f"sha256/{reference.raw_payload_sha256[:2]}/{reference.raw_payload_sha256}"
    if (
        type(reference.raw_cas_address) is not str
        or _CAS_ADDRESS_RE.fullmatch(reference.raw_cas_address) is None
        or reference.raw_cas_address != expected_address
    ):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CAS_ADDRESS_INVALID")


def build_feature_resolution_evidence_reference_v4(
    *,
    ordinal: int,
    feature_name: str,
    raw_cas_namespace: str,
    raw_cas_address: str,
    raw_payload_sha256: str,
    raw_payload_byte_count: int,
    source_evidence_receipt_kind: str,
    source_evidence_receipt_schema_version: str,
    source_evidence_receipt_sha256: str,
    source_attestation_schema_version: str,
    source_attestation_sha256: str,
    attested_material_sha256: str,
    declared_trust_anchor_id: str,
    declared_public_key_sha256: str,
) -> FeatureResolutionEvidenceReferenceV4:
    """Freeze one declared evidence identity without verifying its contents."""

    return FeatureResolutionEvidenceReferenceV4(
        ordinal=ordinal,
        feature_name=feature_name,
        raw_cas_namespace=raw_cas_namespace,
        raw_cas_address=raw_cas_address,
        raw_payload_sha256=raw_payload_sha256,
        raw_payload_byte_count=raw_payload_byte_count,
        source_evidence_receipt_kind=source_evidence_receipt_kind,
        source_evidence_receipt_schema_version=source_evidence_receipt_schema_version,
        source_evidence_receipt_sha256=source_evidence_receipt_sha256,
        source_attestation_schema_version=source_attestation_schema_version,
        source_attestation_sha256=source_attestation_sha256,
        attested_material_sha256=attested_material_sha256,
        declared_trust_anchor_id=declared_trust_anchor_id,
        declared_public_key_sha256=declared_public_key_sha256,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


@dataclass(frozen=True, slots=True)
class AuthenticatedFeatureResolutionCaptureCandidateV4:
    """Canonical immutable candidate with every authority frozen false."""

    schema_version: str
    capture_sha256: str
    capture_json: str = field(repr=False)
    _construction_token: object = field(repr=False, compare=False)
    audit_only: bool = field(default=True, init=False)
    capture_candidate_only: bool = field(default=True, init=False)
    runtime_source_reads_performed: bool = field(default=False, init=False)
    source_registry_authenticated: bool = field(default=False, init=False)
    resolver_branch_capture_authenticated: bool = field(default=False, init=False)
    source_receipts_authenticated: bool = field(default=False, init=False)
    source_attestations_authenticated: bool = field(default=False, init=False)
    raw_cas_payloads_reopened_and_verified: bool = field(default=False, init=False)
    source_semantics_replayed: bool = field(default=False, init=False)
    transform_registry_authenticated: bool = field(default=False, init=False)
    authenticated_optional_typed_negative_complete: bool = field(default=False, init=False)
    source_scope_complete: bool = field(default=False, init=False)
    per_field_receipts_complete: bool = field(default=False, init=False)
    authentication_complete: bool = field(default=False, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_authorized: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_authorized: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)
    runtime_wired: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_FACTORY_CONSTRUCTION_REQUIRED")
        validated = _validate_capture_mapping(_parse_json(self.capture_json))
        if (
            self.schema_version != AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SCHEMA_VERSION
            or self.capture_sha256 != validated["capture_sha256"]
            or self.capture_json != _canonical_json(validated)
        ):
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_ARTIFACT_BINDING_MISMATCH")

    @property
    def capture(self) -> dict[str, Any]:
        """Return a fresh parsed and fully revalidated mapping."""

        return _validate_capture_mapping(_parse_json(self.capture_json))


def _evidence_mapping(reference: FeatureResolutionEvidenceReferenceV4) -> dict[str, Any]:
    _validate_evidence_reference(reference)
    return {
        "raw_cas_namespace": reference.raw_cas_namespace,
        "raw_cas_address": reference.raw_cas_address,
        "raw_payload_sha256": reference.raw_payload_sha256,
        "raw_payload_byte_count": reference.raw_payload_byte_count,
        "source_evidence_receipt_kind": reference.source_evidence_receipt_kind,
        "source_evidence_receipt_schema_version": (
            reference.source_evidence_receipt_schema_version
        ),
        "source_evidence_receipt_sha256": reference.source_evidence_receipt_sha256,
        "source_attestation_schema_version": reference.source_attestation_schema_version,
        "source_attestation_sha256": reference.source_attestation_sha256,
        "attested_material_sha256": reference.attested_material_sha256,
        "declared_trust_anchor_id": reference.declared_trust_anchor_id,
        "declared_public_key_sha256": reference.declared_public_key_sha256,
        "source_receipt_authentication_verified": False,
        "source_attestation_authentication_verified": False,
        "raw_cas_payload_verified": False,
        "source_semantics_verified": False,
    }


def _chain_sha256(*, trace_sha256: str, slot_sha256s: Sequence[str]) -> str:
    genesis = _sha256(
        {
            "chain_domain": AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CHAIN_DOMAIN,
            "feature_source_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
            "feature_resolution_trace_sha256": trace_sha256,
            "feature_slot_count": FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
        }
    )
    previous = bytes.fromhex(genesis)
    domain = AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CHAIN_DOMAIN.encode("ascii") + b"\0"
    for ordinal, slot_sha256 in enumerate(slot_sha256s):
        if not _valid_sha256(slot_sha256):
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SLOT_SHA256_INVALID")
        previous = hashlib.sha256(
            domain
            + ordinal.to_bytes(4, byteorder="big", signed=False)
            + previous
            + bytes.fromhex(slot_sha256)
        ).digest()
    return previous.hex()


def _slot_mapping(
    *,
    ordinal: int,
    observation: dict[str, Any],
    reference: FeatureResolutionEvidenceReferenceV4,
) -> dict[str, Any]:
    registry_slot = FEATURE_SOURCE_REGISTRY_V4.slots[ordinal]
    if reference.ordinal != ordinal or reference.feature_name != registry_slot.feature_name:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_EVIDENCE_ORDER_MISMATCH")
    status = observation["resolution_status"]
    if status == RESOLUTION_STATUS_RESOLVED:
        expected_receipt_kind = POSITIVE_SOURCE_READ_RECEIPT_KIND_V4
        value_hex: str | None = _float32_be_hex(observation["resolved_value"])
        expected_payload_sha256 = observation["source_root_sha256"]
        negative_reason = None
    elif status == RESOLUTION_STATUS_TYPED_NEGATIVE:
        if registry_slot.requirement_class != REQUIREMENT_OPTIONAL_EVENT_DEPENDENT:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_REQUIRED_TYPED_NEGATIVE_FORBIDDEN")
        expected_receipt_kind = OPTIONAL_TYPED_NEGATIVE_RECEIPT_KIND_V4
        value_hex = None
        expected_payload_sha256 = observation["negative_evidence_sha256"]
        negative_reason = observation["negative_reason"]
    else:  # pragma: no cover - upstream trace validator owns the enum
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RESOLUTION_STATUS_INVALID")
    if reference.source_evidence_receipt_kind != expected_receipt_kind:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RECEIPT_KIND_STATUS_MISMATCH")
    if reference.raw_payload_sha256 != expected_payload_sha256:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RAW_PAYLOAD_TRACE_MISMATCH")

    required_clock_names = (
        "event_time",
        "ingested_at",
        "available_at",
        "generated_at",
        "feature_cutoff",
        "decision_time",
        "consumer_observed_at",
    )
    parsed_clocks = {
        name: _parse_clock(observation[name], field_name=name) for name in required_clock_names
    }
    if not (
        parsed_clocks["event_time"]
        <= parsed_clocks["ingested_at"]
        <= parsed_clocks["generated_at"]
        <= parsed_clocks["available_at"]
        <= parsed_clocks["decision_time"]
        <= parsed_clocks["consumer_observed_at"]
    ) or not (
        parsed_clocks["event_time"]
        <= parsed_clocks["feature_cutoff"]
        <= parsed_clocks["decision_time"]
    ):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CLOCK_ORDER_INVALID")

    path = observation["selected_path"]
    if path is not None and type(path) is not list:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SELECTED_PATH_INVALID")
    resolver_branch = {
        "resolved_source_label": observation["resolved_source_label"],
        "selected_payload": observation["selected_payload"],
        "selected_key": observation["selected_key"],
        "selected_path": None if path is None else list(path),
        "selected_alias": observation["selected_alias"],
        "resolver_version": observation["resolver_version"],
        "resolver_code_sha256": observation["resolver_code_sha256"],
        "resolver_config_sha256": observation["resolver_config_sha256"],
    }
    transform = {
        "transform_id": observation["transform_id"],
        "transform_version": observation["transform_version"],
        "transform_code_sha256": observation["transform_code_sha256"],
        "transform_config_sha256": observation["transform_config_sha256"],
        "resolved_value_float32_be_hex": value_hex,
    }
    clocks = {name: observation[name] for name in _CLOCK_FIELDS}
    slot: dict[str, Any] = {
        "schema_version": AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SLOT_SCHEMA_VERSION,
        "ordinal": ordinal,
        "feature_name": registry_slot.feature_name,
        "configured_source_label": registry_slot.configured_source_label,
        "requirement_class": registry_slot.requirement_class,
        "resolution_status": status,
        "negative_reason": negative_reason,
        "resolver_branch": resolver_branch,
        "transform": transform,
        "source_evidence": _evidence_mapping(reference),
        "clocks": clocks,
        "trace_slot_observation_sha256": observation["slot_observation_sha256"],
        "optional_typed_negative_authentication_verified": False,
    }
    slot["slot_capture_sha256"] = _sha256(slot)
    return slot


def _reference_from_mapping(
    *, ordinal: int, feature_name: str, source_evidence: dict[str, Any]
) -> FeatureResolutionEvidenceReferenceV4:
    return build_feature_resolution_evidence_reference_v4(
        ordinal=ordinal,
        feature_name=feature_name,
        raw_cas_namespace=source_evidence["raw_cas_namespace"],
        raw_cas_address=source_evidence["raw_cas_address"],
        raw_payload_sha256=source_evidence["raw_payload_sha256"],
        raw_payload_byte_count=source_evidence["raw_payload_byte_count"],
        source_evidence_receipt_kind=source_evidence["source_evidence_receipt_kind"],
        source_evidence_receipt_schema_version=(
            source_evidence["source_evidence_receipt_schema_version"]
        ),
        source_evidence_receipt_sha256=source_evidence["source_evidence_receipt_sha256"],
        source_attestation_schema_version=source_evidence["source_attestation_schema_version"],
        source_attestation_sha256=source_evidence["source_attestation_sha256"],
        attested_material_sha256=source_evidence["attested_material_sha256"],
        declared_trust_anchor_id=source_evidence["declared_trust_anchor_id"],
        declared_public_key_sha256=source_evidence["declared_public_key_sha256"],
    )


def _validate_cross_slot_identity_consistency(slots: Sequence[dict[str, Any]]) -> None:
    """Reject one declared cryptographic identity describing different material."""

    raw_objects: dict[str, tuple[object, ...]] = {}
    receipts: dict[str, tuple[object, ...]] = {}
    attested_materials: dict[str, tuple[object, ...]] = {}
    attestations: dict[str, tuple[object, ...]] = {}
    trust_anchors: dict[str, str] = {}
    for slot in slots:
        evidence = cast(dict[str, Any], slot["source_evidence"])
        clocks = cast(dict[str, Any], slot["clocks"])
        raw_payload_sha256 = cast(str, evidence["raw_payload_sha256"])
        raw_material = (
            evidence["raw_cas_namespace"],
            evidence["raw_cas_address"],
            evidence["raw_payload_byte_count"],
        )
        if raw_payload_sha256 in raw_objects and raw_objects[raw_payload_sha256] != raw_material:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CAS_IDENTITY_CONTRADICTION")
        raw_objects[raw_payload_sha256] = raw_material

        receipt_sha256 = cast(str, evidence["source_evidence_receipt_sha256"])
        receipt_material = (
            evidence["source_evidence_receipt_schema_version"],
            evidence["source_evidence_receipt_kind"],
            slot["resolution_status"],
            slot["negative_reason"],
            evidence["raw_cas_namespace"],
            evidence["raw_cas_address"],
            raw_payload_sha256,
            evidence["raw_payload_byte_count"],
            clocks["event_time"],
            clocks["ingested_at"],
            clocks["available_at"],
            clocks["feature_cutoff"],
            clocks["decision_time"],
            clocks["consumer_observed_at"],
        )
        if receipt_sha256 in receipts and receipts[receipt_sha256] != receipt_material:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RECEIPT_IDENTITY_CONTRADICTION")
        receipts[receipt_sha256] = receipt_material

        attested_material_sha256 = cast(str, evidence["attested_material_sha256"])
        attested_material = (receipt_sha256, *receipt_material)
        if (
            attested_material_sha256 in attested_materials
            and attested_materials[attested_material_sha256] != attested_material
        ):
            _fail(
                "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_"
                "ATTESTED_MATERIAL_IDENTITY_CONTRADICTION"
            )
        attested_materials[attested_material_sha256] = attested_material

        attestation_sha256 = cast(str, evidence["source_attestation_sha256"])
        attestation_material = (
            evidence["source_attestation_schema_version"],
            attested_material_sha256,
            evidence["declared_trust_anchor_id"],
            evidence["declared_public_key_sha256"],
        )
        if (
            attestation_sha256 in attestations
            and attestations[attestation_sha256] != attestation_material
        ):
            _fail(
                "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_" "ATTESTATION_IDENTITY_CONTRADICTION"
            )
        attestations[attestation_sha256] = attestation_material

        trust_anchor_id = cast(str, evidence["declared_trust_anchor_id"])
        public_key_sha256 = cast(str, evidence["declared_public_key_sha256"])
        if trust_anchor_id in trust_anchors and trust_anchors[trust_anchor_id] != public_key_sha256:
            _fail(
                "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_" "TRUST_ANCHOR_IDENTITY_CONTRADICTION"
            )
        trust_anchors[trust_anchor_id] = public_key_sha256


def _validate_capture_mapping(value: object) -> dict[str, Any]:
    capture = _exact_dict(
        value,
        _CAPTURE_FIELDS,
        "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_FIELDS_INVALID",
    )
    expected_constants: dict[str, object] = {
        "schema_version": AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SCHEMA_VERSION,
        "evidence_classification": (
            AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_EVIDENCE_CLASSIFICATION
        ),
        "downstream_status": AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_DOWNSTREAM_STATUS,
        "feature_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "feature_requirement_policy_id": FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
        "feature_source_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "feature_slot_count": FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
        "required_slot_count": FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT,
        "optional_slot_count": FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT,
        "required_typed_negative_slot_count": 0,
        "complete_slot_capture_set": True,
        "declared_point_in_time_order_valid": True,
        "required_value_contract_valid": True,
        "capture_candidate_only": True,
        "audit_only": True,
        **{name: False for name in _FIXED_FALSE_FIELDS},
    }
    if any(
        type(capture.get(name)) is not type(expected) or capture.get(name) != expected
        for name, expected in expected_constants.items()
    ):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CONSTANT_OR_FLAG_MISMATCH")
    try:
        registry_contract = feature_source_registry_v4_contract(FEATURE_SOURCE_REGISTRY_V4)
    except FeatureSourceRegistryV4ValidationError as exc:  # pragma: no cover - pinned invariant
        raise AuthenticatedFeatureResolutionCaptureV4ValidationError(
            "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_REGISTRY_INVALID"
        ) from exc
    if registry_contract["registry_sha256"] != capture["feature_source_registry_sha256"]:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_REGISTRY_SHA256_MISMATCH")

    try:
        trace_artifact = validate_feature_resolution_trace_v4(capture["resolution_trace"])
    except FeatureResolutionTraceV4ValidationError as exc:
        raise AuthenticatedFeatureResolutionCaptureV4ValidationError(
            "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_TRACE_INVALID"
        ) from exc
    trace = trace_artifact.trace
    if (
        not _valid_sha256(capture["feature_resolution_trace_sha256"])
        or capture["feature_resolution_trace_sha256"] != trace_artifact.trace_sha256
    ):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_TRACE_SHA256_MISMATCH")
    if trace["required_typed_negative_feature_names"]:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_REQUIRED_TYPED_NEGATIVE_FORBIDDEN")

    raw_slots = capture["slot_captures"]
    observations = trace["slot_observations"]
    if type(raw_slots) is not list or len(raw_slots) != FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SLOT_SET_INCOMPLETE")
    normalized_slots: list[dict[str, Any]] = []
    slot_sha256s: list[str] = []
    for ordinal, (raw_slot, observation) in enumerate(zip(raw_slots, observations, strict=True)):
        slot = _exact_dict(
            raw_slot,
            _SLOT_FIELDS,
            "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SLOT_FIELDS_INVALID",
        )
        resolver_branch = _exact_dict(
            slot["resolver_branch"],
            _RESOLVER_BRANCH_FIELDS,
            "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_RESOLVER_BRANCH_FIELDS_INVALID",
        )
        transform = _exact_dict(
            slot["transform"],
            _TRANSFORM_FIELDS,
            "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_TRANSFORM_FIELDS_INVALID",
        )
        source_evidence = _exact_dict(
            slot["source_evidence"],
            _SOURCE_EVIDENCE_FIELDS,
            "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SOURCE_EVIDENCE_FIELDS_INVALID",
        )
        clocks = _exact_dict(
            slot["clocks"],
            _CLOCK_FIELDS,
            "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CLOCK_FIELDS_INVALID",
        )
        for flag_name in (
            "source_receipt_authentication_verified",
            "source_attestation_authentication_verified",
            "raw_cas_payload_verified",
            "source_semantics_verified",
        ):
            if source_evidence[flag_name] is not False:
                _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_AUTHENTICATION_CLAIM_FORBIDDEN")
        if slot["optional_typed_negative_authentication_verified"] is not False:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_AUTHENTICATION_CLAIM_FORBIDDEN")
        reference = _reference_from_mapping(
            ordinal=ordinal,
            feature_name=FEATURE_SOURCE_REGISTRY_V4.slots[ordinal].feature_name,
            source_evidence=source_evidence,
        )
        expected_slot = _slot_mapping(
            ordinal=ordinal,
            observation=observation,
            reference=reference,
        )
        normalized_slot = {
            **slot,
            "resolver_branch": resolver_branch,
            "transform": transform,
            "source_evidence": source_evidence,
            "clocks": clocks,
        }
        if normalized_slot != expected_slot:
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SLOT_TRACE_BINDING_MISMATCH")
        slot_sha256 = slot["slot_capture_sha256"]
        if not _valid_sha256(slot_sha256):
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SLOT_SHA256_INVALID")
        material = {
            key: item for key, item in normalized_slot.items() if key != "slot_capture_sha256"
        }
        if slot_sha256 != _sha256(material):
            _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SLOT_SHA256_MISMATCH")
        normalized_slots.append(normalized_slot)
        slot_sha256s.append(slot_sha256)

    _validate_cross_slot_identity_consistency(normalized_slots)
    expected_chain = _chain_sha256(
        trace_sha256=trace_artifact.trace_sha256,
        slot_sha256s=slot_sha256s,
    )
    if capture["ordered_slot_capture_chain_sha256"] != expected_chain:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_ORDERED_CHAIN_MISMATCH")
    resolved_count = sum(
        slot["resolution_status"] == RESOLUTION_STATUS_RESOLVED for slot in normalized_slots
    )
    optional_negative_count = len(normalized_slots) - resolved_count
    if (
        type(capture["resolved_slot_count"]) is not int
        or capture["resolved_slot_count"] != resolved_count
        or type(capture["declared_optional_typed_negative_slot_count"]) is not int
        or capture["declared_optional_typed_negative_slot_count"] != optional_negative_count
        or capture["resolved_slot_count"] != trace["resolved_slot_count"]
        or capture["declared_optional_typed_negative_slot_count"]
        != trace["typed_negative_slot_count"]
    ):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SUMMARY_MISMATCH")
    normalized = {
        **capture,
        "resolution_trace": trace,
        "slot_captures": normalized_slots,
    }
    material = {key: item for key, item in normalized.items() if key != "capture_sha256"}
    if not _valid_sha256(capture["capture_sha256"]) or capture["capture_sha256"] != _sha256(
        material
    ):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SHA256_MISMATCH")
    return normalized


def build_authenticated_feature_resolution_capture_candidate_v4(
    *,
    registry: FeatureSourceRegistryV4,
    resolution_trace: FeatureResolutionTraceArtifactV4,
    evidence_references: Sequence[FeatureResolutionEvidenceReferenceV4],
) -> AuthenticatedFeatureResolutionCaptureCandidateV4:
    """Build a complete, immutable, still-unauthenticated capture candidate."""

    if type(registry) is not FeatureSourceRegistryV4:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_REGISTRY_TYPE_INVALID")
    try:
        registry_contract = feature_source_registry_v4_contract(registry)
    except FeatureSourceRegistryV4ValidationError as exc:
        raise AuthenticatedFeatureResolutionCaptureV4ValidationError(
            "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_REGISTRY_INVALID"
        ) from exc
    if registry_contract["registry_sha256"] != FEATURE_SOURCE_REGISTRY_V4_SHA256:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_REGISTRY_SHA256_MISMATCH")
    if type(resolution_trace) is not FeatureResolutionTraceArtifactV4:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_TRACE_TYPE_INVALID")
    try:
        trace_artifact = validate_feature_resolution_trace_v4(resolution_trace.trace)
    except FeatureResolutionTraceV4ValidationError as exc:
        raise AuthenticatedFeatureResolutionCaptureV4ValidationError(
            "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_TRACE_INVALID"
        ) from exc
    trace = trace_artifact.trace
    if trace["required_typed_negative_feature_names"]:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_REQUIRED_TYPED_NEGATIVE_FORBIDDEN")
    if type(evidence_references) not in (tuple, list) or len(evidence_references) != (
        FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
    ):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_EVIDENCE_SET_INCOMPLETE")
    if any(
        type(reference) is not FeatureResolutionEvidenceReferenceV4
        for reference in evidence_references
    ):
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_EVIDENCE_TYPE_INVALID")

    slots = [
        _slot_mapping(
            ordinal=ordinal,
            observation=observation,
            reference=reference,
        )
        for ordinal, (observation, reference) in enumerate(
            zip(trace["slot_observations"], evidence_references, strict=True)
        )
    ]
    slot_sha256s = [cast(str, slot["slot_capture_sha256"]) for slot in slots]
    resolved_count = cast(int, trace["resolved_slot_count"])
    capture: dict[str, Any] = {
        "schema_version": AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SCHEMA_VERSION,
        "evidence_classification": (
            AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_EVIDENCE_CLASSIFICATION
        ),
        "downstream_status": AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_DOWNSTREAM_STATUS,
        "feature_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "feature_requirement_policy_id": FEATURE_SOURCE_REGISTRY_V4_REQUIREMENT_POLICY_ID,
        "feature_source_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "feature_resolution_trace_sha256": trace_artifact.trace_sha256,
        "feature_slot_count": FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
        "required_slot_count": FEATURE_SOURCE_REGISTRY_V4_REQUIRED_SLOT_COUNT,
        "optional_slot_count": FEATURE_SOURCE_REGISTRY_V4_OPTIONAL_SLOT_COUNT,
        "resolution_trace": trace,
        "slot_captures": slots,
        "ordered_slot_capture_chain_sha256": _chain_sha256(
            trace_sha256=trace_artifact.trace_sha256,
            slot_sha256s=slot_sha256s,
        ),
        "resolved_slot_count": resolved_count,
        "declared_optional_typed_negative_slot_count": (
            FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT - resolved_count
        ),
        "required_typed_negative_slot_count": 0,
        "complete_slot_capture_set": True,
        "declared_point_in_time_order_valid": True,
        "required_value_contract_valid": True,
        "capture_candidate_only": True,
        "audit_only": True,
        **{name: False for name in _FIXED_FALSE_FIELDS},
    }
    capture["capture_sha256"] = _sha256(capture)
    return validate_authenticated_feature_resolution_capture_candidate_v4(capture)


def validate_authenticated_feature_resolution_capture_candidate_v4(
    value: object,
) -> AuthenticatedFeatureResolutionCaptureCandidateV4:
    """Validate a mapping and freeze it as a canonical candidate artifact."""

    if type(value) is not dict:
        _fail("AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_NOT_EXACT_OBJECT")
    detached = cast(dict[str, Any], _bounded_snapshot(value))
    validated = _validate_capture_mapping(detached)
    return AuthenticatedFeatureResolutionCaptureCandidateV4(
        schema_version=AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SCHEMA_VERSION,
        capture_sha256=cast(str, validated["capture_sha256"]),
        capture_json=_canonical_json(validated),
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def parse_authenticated_feature_resolution_capture_candidate_v4(
    value: str | bytes,
) -> AuthenticatedFeatureResolutionCaptureCandidateV4:
    """Parse exact canonical JSON; duplicate keys and non-canonical bytes fail."""

    validated = _validate_capture_mapping(_parse_json(value))
    return AuthenticatedFeatureResolutionCaptureCandidateV4(
        schema_version=AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SCHEMA_VERSION,
        capture_sha256=cast(str, validated["capture_sha256"]),
        capture_json=_canonical_json(validated),
        _construction_token=_CONSTRUCTION_TOKEN,
    )


__all__ = [
    "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CHAIN_DOMAIN",
    "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_DOWNSTREAM_STATUS",
    "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_EVIDENCE_CLASSIFICATION",
    "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SCHEMA_VERSION",
    "AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_SLOT_SCHEMA_VERSION",
    "AuthenticatedFeatureResolutionCaptureCandidateV4",
    "AuthenticatedFeatureResolutionCaptureV4ValidationError",
    "FeatureResolutionEvidenceReferenceV4",
    "MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_BYTES",
    "MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_CONTAINER_ITEMS",
    "MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_DEPTH",
    "MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_JSON_NODES",
    "MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_KEY_BYTES",
    "MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_PAYLOAD_BYTES",
    "MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_STRING_BYTES",
    "MAX_AUTHENTICATED_FEATURE_RESOLUTION_CAPTURE_V4_TOTAL_TEXT_BYTES",
    "OPTIONAL_TYPED_NEGATIVE_RECEIPT_KIND_V4",
    "POSITIVE_SOURCE_READ_RECEIPT_KIND_V4",
    "SOURCE_EVIDENCE_CAS_NAMESPACE_V4",
    "build_authenticated_feature_resolution_capture_candidate_v4",
    "build_feature_resolution_evidence_reference_v4",
    "parse_authenticated_feature_resolution_capture_candidate_v4",
    "validate_authenticated_feature_resolution_capture_candidate_v4",
]
