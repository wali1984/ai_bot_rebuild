"""Audit-only authentication primitive for future source-evidence adapters.

This module authenticates one exact, bounded adapter-output context with a
domain-separated HMAC-SHA256 tag.  It is intentionally independent from the
future positive-source and typed-negative evidence unions: those contracts may
embed their schema and classification identities in this material, but this
module does not decide whether either union is semantically complete.

Security boundary
-----------------

* A :class:`SourceEvidenceAuthenticatorV4` holds one dedicated provenance key
  and signs an exact adapter-output context.
* A :class:`SourceEvidenceVerifierV4` resolves a retained key selected by the
  caller's expected key ID, authenticates the tag with
  :func:`hmac.compare_digest`, and compares the artifact with the caller's
  complete expected replay context.
* The artifact cannot select its own expected key, environment, namespace,
  source, symbol, timeframe, CAS address, run, cycle, or decision context.
* ``adapter_attestation_verified`` is a hash-bound adapter declaration, not a
  Python capability.  A parsed or signed artifact alone is not a verification
  result.  Consumers must invoke ``verify`` at the point of use and must not
  cache a nominally "verified" object as admission or execution authority.
* A successful verification returns only a detached, flat, read-only mapping.
  It has no authority-bearing type or cached authorization attributes.

Non-goals
---------

This primitive does not authenticate the upstream producer, validate a typed
negative, prove a complete per-slot dependency graph, append a ledger, publish
a feature snapshot, admit trainer input, authorize prediction/paper/live
execution, read Redis, call a provider, inspect a service, or wire itself into
runtime.  Those non-authorizations are exact fields in the authenticated
material and are required to remain false.

The factory token on the parsed artifact is only a local construction integrity
guard.  It is reachable Python state and is never described or treated as
authentication.  Possessing it cannot bypass the verifier's fresh HMAC and
exact expected-context checks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, NoReturn, SupportsIndex, cast

SOURCE_EVIDENCE_ATTESTATION_V4_SCHEMA_VERSION = "trainer_source_evidence_adapter_attestation_v4"
SOURCE_EVIDENCE_ATTESTATION_MATERIAL_V4_CONTRACT_VERSION = (
    "trainer_source_evidence_adapter_attestation_material_v4"
)
SOURCE_EVIDENCE_AUTH_ALGORITHM = "HMAC-SHA256"
SOURCE_EVIDENCE_AUTH_DOMAIN = "v2/native-trainer/source-evidence-adapter-attestation/v4"
SOURCE_EVIDENCE_AUTH_DOMAIN_SEPARATOR = SOURCE_EVIDENCE_AUTH_DOMAIN.encode("ascii") + b"\0"
POSITIVE_SOURCE_READ_EVIDENCE_KIND = "POSITIVE_SOURCE_READ"

# Cryptographic and parser resource bounds.  These are security invariants,
# not market, feature, risk, leverage, or trading thresholds.
MIN_SOURCE_EVIDENCE_PROVENANCE_KEY_BYTES = 32
MAX_SOURCE_EVIDENCE_PROVENANCE_KEY_BYTES = 4 * 1024
MAX_SOURCE_EVIDENCE_ATTESTATION_BYTES = 64 * 1024
MAX_SOURCE_EVIDENCE_PAYLOAD_BYTES = 256 * 1024 * 1024
MAX_SOURCE_EVIDENCE_JSON_DEPTH = 4
MAX_SOURCE_EVIDENCE_JSON_NODES = 128
MAX_SOURCE_EVIDENCE_TOTAL_TEXT_BYTES = 32 * 1024
MAX_SOURCE_EVIDENCE_ID_BYTES = 256
MAX_SOURCE_EVIDENCE_KEY_BYTES = 512
MAX_SOURCE_EVIDENCE_LOCATOR_BYTES = 4 * 1024

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$",
    re.ASCII,
)
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$", re.ASCII)
_SAFE_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,32}$", re.ASCII)
_TIMEFRAME_RE = re.compile(r"^[1-9][0-9]{0,5}[mhdw]$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_AUTH_TAG_RE = _SHA256_RE
_VISIBLE_ASCII_RE = re.compile(r"^[\x21-\x7e]+$", re.ASCII)
_CONSTRUCTION_TOKEN = object()

_FIXED_FALSE_AUTHORIZATION_FIELDS = (
    "upstream_producer_authenticated",
    "typed_negative_authenticated",
    "per_slot_dependency_complete",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "durable_ledger_appended",
    "feature_snapshot_published",
    "consumer_eligible",
    "runtime_wired",
)
_SOURCE_CLOCK_FIELDS = (
    "economic_event_time",
    "producer_event_time",
    "ingested_at",
    "source_available_at",
    "source_read_completed_at",
)
_MATERIAL_FIELDS = frozenset(
    {
        "contract_version",
        "source_evidence_schema_version",
        "environment",
        "namespace",
        "adapter_id",
        "adapter_code_sha256",
        "adapter_config_sha256",
        "evidence_kind",
        "evidence_class",
        "upstream_producer_identity_claim",
        "source_key",
        "source_locator",
        "source_schema_version",
        "symbol",
        "timeframe",
        "run_id",
        "cycle_id",
        "decision_id",
        "exact_payload_sha256",
        "exact_payload_byte_count",
        "cas_namespace",
        "cas_address",
        *_SOURCE_CLOCK_FIELDS,
        "decision_time",
        "finality_kind",
        "finality_result",
        "branch_identity",
        "negative_type_identity",
        "exact_atomic_read_verified",
        "source_schema_adapter_verified",
        "source_finality_verified",
        "adapter_attestation_verified",
        *_FIXED_FALSE_AUTHORIZATION_FIELDS,
        "audit_only",
    }
)
_ATTESTATION_FIELDS = frozenset(
    {
        "schema_version",
        "auth_algorithm",
        "auth_domain",
        "auth_key_id",
        "attestation_material",
        "auth_tag",
    }
)

RetainedSourceEvidenceKeyResolver = Callable[[str], bytes]


class SourceEvidenceAuthenticatorV4Error(RuntimeError):
    """Base error whose message never includes source or secret material."""


class SourceEvidenceAuthenticatorV4ValidationError(SourceEvidenceAuthenticatorV4Error):
    """The key, material, artifact, or expected context is invalid."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


class SourceEvidenceAuthenticatorV4VerificationError(SourceEvidenceAuthenticatorV4Error):
    """Authentication or exact expected-context verification failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _validation_error(reason: str) -> NoReturn:
    raise SourceEvidenceAuthenticatorV4ValidationError(reason) from None


def _verification_error(reason: str) -> NoReturn:
    raise SourceEvidenceAuthenticatorV4VerificationError(reason) from None


def _reject_json_constant(_value: str) -> NoReturn:
    _validation_error("source_evidence_attestation_json_constant_forbidden")


def _reject_json_float(_value: str) -> NoReturn:
    _validation_error("source_evidence_attestation_json_float_forbidden")


def _parse_json_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 10:
        _validation_error("source_evidence_attestation_json_integer_invalid")
    try:
        return int(value)
    except ValueError:
        _validation_error("source_evidence_attestation_json_integer_invalid")


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _validation_error("source_evidence_attestation_duplicate_json_key")
        result[key] = value
    return result


def _canonical_json_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _validation_error("source_evidence_attestation_not_strict_ascii_json")
    if len(encoded) > MAX_SOURCE_EVIDENCE_ATTESTATION_BYTES:
        _validation_error("source_evidence_attestation_size_limit_exceeded")
    return encoded


def _validate_json_tree_limits(value: object) -> None:
    nodes = 0
    text_bytes = 0
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_SOURCE_EVIDENCE_JSON_NODES:
            _validation_error("source_evidence_attestation_json_node_limit_exceeded")
        if depth > MAX_SOURCE_EVIDENCE_JSON_DEPTH:
            _validation_error("source_evidence_attestation_json_depth_limit_exceeded")
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            for key, child in mapping.items():
                if type(key) is not str:
                    _validation_error("source_evidence_attestation_json_key_invalid")
                try:
                    text_bytes += len(key.encode("ascii", errors="strict"))
                except UnicodeEncodeError:
                    _validation_error("source_evidence_attestation_non_ascii_text")
                stack.append((child, depth + 1))
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in cast(list[object], item))
        elif type(item) is str:
            try:
                text_bytes += len(item.encode("ascii", errors="strict"))
            except UnicodeEncodeError:
                _validation_error("source_evidence_attestation_non_ascii_text")
        elif item is None or type(item) in (bool, int):
            pass
        else:
            _validation_error("source_evidence_attestation_json_value_type_invalid")
        if text_bytes > MAX_SOURCE_EVIDENCE_TOTAL_TEXT_BYTES:
            _validation_error("source_evidence_attestation_text_limit_exceeded")


def _parse_exact_json(value: object) -> dict[str, object]:
    if type(value) is bytes:
        raw = value
        if not raw or len(raw) > MAX_SOURCE_EVIDENCE_ATTESTATION_BYTES:
            _validation_error("source_evidence_attestation_json_invalid")
        try:
            text = raw.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            _validation_error("source_evidence_attestation_json_invalid")
    elif type(value) is str:
        text = value
        if not text:
            _validation_error("source_evidence_attestation_json_invalid")
        try:
            raw = text.encode("ascii", errors="strict")
        except UnicodeEncodeError:
            _validation_error("source_evidence_attestation_json_invalid")
        if len(raw) > MAX_SOURCE_EVIDENCE_ATTESTATION_BYTES:
            _validation_error("source_evidence_attestation_json_invalid")
    else:
        _validation_error("source_evidence_attestation_json_invalid")
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_json_constant,
            parse_float=_reject_json_float,
            parse_int=_parse_json_int,
        )
    except SourceEvidenceAuthenticatorV4ValidationError:
        raise
    except (json.JSONDecodeError, OverflowError, RecursionError, TypeError, ValueError):
        _validation_error("source_evidence_attestation_json_invalid")
    if type(decoded) is not dict:
        _validation_error("source_evidence_attestation_not_exact_object")
    _validate_json_tree_limits(decoded)
    result = cast(dict[str, object], decoded)
    if not hmac.compare_digest(_canonical_json_bytes(result), raw):
        _validation_error("source_evidence_attestation_json_not_canonical")
    return result


def _safe_ascii_text(value: object, *, maximum_bytes: int, reason: str) -> str:
    if type(value) is not str:
        _validation_error(reason)
    text = value
    try:
        encoded = text.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _validation_error(reason)
    if not encoded or len(encoded) > maximum_bytes or _VISIBLE_ASCII_RE.fullmatch(text) is None:
        _validation_error(reason)
    return text


def _safe_id(value: object, *, reason: str) -> str:
    if type(value) is not str:
        _validation_error(reason)
    text = value
    if (
        len(text) > MAX_SOURCE_EVIDENCE_ID_BYTES
        or not text.isascii()
        or _SAFE_ID_RE.fullmatch(text) is None
    ):
        _validation_error(reason)
    return text


def _safe_key_id(value: object) -> str:
    if type(value) is not str:
        _validation_error("source_evidence_attestation_auth_key_id_invalid")
    text = value
    if not text.isascii() or _SAFE_KEY_ID_RE.fullmatch(text) is None:
        _validation_error("source_evidence_attestation_auth_key_id_invalid")
    return text


def _sha256(value: object, *, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _validation_error(reason)
    return value


def _clock(value: object, *, field_name: str, nullable: bool) -> datetime | None:
    if value is None and nullable:
        return None
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _validation_error(f"source_evidence_attestation_{field_name}_invalid")
    text = value
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        _validation_error(f"source_evidence_attestation_{field_name}_invalid")
    if parsed < _EPOCH or parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != text:
        _validation_error(f"source_evidence_attestation_{field_name}_invalid")
    return parsed


def _exact_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        _validation_error(f"source_evidence_attestation_{field_name}_invalid")
    return value


def _validate_material_clocks(material: dict[str, object]) -> None:
    decision_time = _clock(material["decision_time"], field_name="decision_time", nullable=False)
    assert decision_time is not None
    source_clocks = {
        name: _clock(material[name], field_name=name, nullable=True)
        for name in _SOURCE_CLOCK_FIELDS
    }
    supplied = tuple(value is not None for value in source_clocks.values())
    positive_read = material["evidence_kind"] == POSITIVE_SOURCE_READ_EVIDENCE_KIND
    if positive_read and not all(supplied):
        _validation_error("source_evidence_attestation_positive_read_clocks_required")
    if any(supplied) and not all(supplied):
        _validation_error("source_evidence_attestation_source_clock_set_partial")
    if not all(supplied):
        return
    ordered = [cast(datetime, source_clocks[name]) for name in _SOURCE_CLOCK_FIELDS]
    ordered.append(decision_time)
    if any(earlier > later for earlier, later in zip(ordered, ordered[1:], strict=False)):
        _validation_error("source_evidence_attestation_causal_clock_order_invalid")


def _snapshot_and_validate_material(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _validation_error("source_evidence_attestation_material_not_exact_object")
    source = cast(dict[object, object], value)
    try:
        pairs = tuple(source.items())
    except RuntimeError:
        _validation_error("source_evidence_attestation_material_mutated")
    if len(pairs) != len(source):
        _validation_error("source_evidence_attestation_material_mutated")
    material: dict[str, object] = {}
    for key, item in pairs:
        if type(key) is not str:
            _validation_error("source_evidence_attestation_material_field_invalid")
        material[key] = item
    if set(material) != _MATERIAL_FIELDS:
        _validation_error("source_evidence_attestation_material_field_set_mismatch")
    if material["contract_version"] != SOURCE_EVIDENCE_ATTESTATION_MATERIAL_V4_CONTRACT_VERSION:
        _validation_error("source_evidence_attestation_material_contract_invalid")

    for field_name in (
        "source_evidence_schema_version",
        "environment",
        "namespace",
        "adapter_id",
        "evidence_kind",
        "evidence_class",
        "upstream_producer_identity_claim",
        "source_schema_version",
        "run_id",
        "cycle_id",
        "decision_id",
        "cas_namespace",
        "finality_kind",
        "branch_identity",
    ):
        _safe_id(material[field_name], reason=f"source_evidence_attestation_{field_name}_invalid")
    negative_type_identity = material["negative_type_identity"]
    if negative_type_identity is not None:
        _safe_id(
            negative_type_identity,
            reason="source_evidence_attestation_negative_type_identity_invalid",
        )
    _safe_ascii_text(
        material["source_key"],
        maximum_bytes=MAX_SOURCE_EVIDENCE_KEY_BYTES,
        reason="source_evidence_attestation_source_key_invalid",
    )
    for field_name in ("source_locator", "cas_address"):
        _safe_ascii_text(
            material[field_name],
            maximum_bytes=MAX_SOURCE_EVIDENCE_LOCATOR_BYTES,
            reason=f"source_evidence_attestation_{field_name}_invalid",
        )
    symbol = material["symbol"]
    if type(symbol) is not str or _SYMBOL_RE.fullmatch(symbol) is None:
        _validation_error("source_evidence_attestation_symbol_invalid")
    timeframe = material["timeframe"]
    if type(timeframe) is not str or _TIMEFRAME_RE.fullmatch(timeframe) is None:
        _validation_error("source_evidence_attestation_timeframe_invalid")
    for field_name in (
        "adapter_code_sha256",
        "adapter_config_sha256",
        "exact_payload_sha256",
    ):
        _sha256(
            material[field_name],
            reason=f"source_evidence_attestation_{field_name}_invalid",
        )
    payload_byte_count = material["exact_payload_byte_count"]
    if (
        type(payload_byte_count) is not int
        or not 0 <= payload_byte_count <= MAX_SOURCE_EVIDENCE_PAYLOAD_BYTES
    ):
        _validation_error("source_evidence_attestation_payload_byte_count_invalid")
    _exact_bool(material["finality_result"], field_name="finality_result")
    for field_name in (
        "exact_atomic_read_verified",
        "source_schema_adapter_verified",
        "source_finality_verified",
        "adapter_attestation_verified",
        *_FIXED_FALSE_AUTHORIZATION_FIELDS,
        "audit_only",
    ):
        _exact_bool(material[field_name], field_name=field_name)
    if material["adapter_attestation_verified"] is not True:
        _validation_error("source_evidence_attestation_adapter_attestation_not_hash_bound_true")
    if material["audit_only"] is not True:
        _validation_error("source_evidence_attestation_audit_only_not_hash_bound_true")
    if any(material[field_name] is not False for field_name in _FIXED_FALSE_AUTHORIZATION_FIELDS):
        _validation_error("source_evidence_attestation_forbidden_authorization")
    if material["source_finality_verified"] is True and material["finality_result"] is not True:
        _validation_error("source_evidence_attestation_finality_claim_inconsistent")
    _validate_material_clocks(material)

    _validate_json_tree_limits(material)
    canonical = _canonical_json_bytes(material)
    detached = _parse_exact_json(canonical)
    if set(detached) != _MATERIAL_FIELDS:
        _validation_error("source_evidence_attestation_material_field_set_mismatch")
    return detached


def validate_source_evidence_attestation_material_v4(value: object) -> dict[str, object]:
    """Return a detached canonical copy of one exact adapter-output context."""

    return _snapshot_and_validate_material(value)


def _validate_attestation_mapping(value: dict[str, object]) -> dict[str, object]:
    if set(value) != _ATTESTATION_FIELDS:
        _validation_error("source_evidence_attestation_field_set_mismatch")
    if value["schema_version"] != SOURCE_EVIDENCE_ATTESTATION_V4_SCHEMA_VERSION:
        _validation_error("source_evidence_attestation_schema_invalid")
    if value["auth_algorithm"] != SOURCE_EVIDENCE_AUTH_ALGORITHM:
        _validation_error("source_evidence_attestation_auth_algorithm_invalid")
    if value["auth_domain"] != SOURCE_EVIDENCE_AUTH_DOMAIN:
        _validation_error("source_evidence_attestation_auth_domain_invalid")
    _safe_key_id(value["auth_key_id"])
    supplied_tag = value["auth_tag"]
    if type(supplied_tag) is not str:
        _validation_error("source_evidence_attestation_auth_tag_invalid")
    tag_text = supplied_tag
    if not tag_text.isascii() or not 1 <= len(tag_text) <= 128:
        _validation_error("source_evidence_attestation_auth_tag_invalid")
    material = _snapshot_and_validate_material(value["attestation_material"])
    detached: dict[str, object] = {
        "schema_version": value["schema_version"],
        "auth_algorithm": value["auth_algorithm"],
        "auth_domain": value["auth_domain"],
        "auth_key_id": value["auth_key_id"],
        "attestation_material": material,
        "auth_tag": supplied_tag,
    }
    return detached


def _parse_attestation(value: object) -> tuple[dict[str, object], str]:
    parsed = _parse_exact_json(value)
    validated = _validate_attestation_mapping(parsed)
    canonical = _canonical_json_bytes(validated).decode("ascii")
    return validated, canonical


def _validated_provenance_key(value: object) -> bytes:
    if (
        type(value) is not bytes
        or not MIN_SOURCE_EVIDENCE_PROVENANCE_KEY_BYTES
        <= len(value)
        <= MAX_SOURCE_EVIDENCE_PROVENANCE_KEY_BYTES
    ):
        _validation_error("source_evidence_provenance_key_invalid")
    return bytes(value)


def _unsigned_attestation_material(
    *,
    auth_key_id: str,
    material: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": SOURCE_EVIDENCE_ATTESTATION_V4_SCHEMA_VERSION,
        "auth_algorithm": SOURCE_EVIDENCE_AUTH_ALGORITHM,
        "auth_domain": SOURCE_EVIDENCE_AUTH_DOMAIN,
        "auth_key_id": auth_key_id,
        "attestation_material": material,
    }


@dataclass(frozen=True, slots=True, repr=False)
class SourceEvidenceAdapterAttestationV4:
    """Immutable serialized attestation; parsing alone does not authenticate it."""

    schema_version: str
    auth_key_id: str
    auth_tag: str
    attestation_json: str = field(repr=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _validation_error("source_evidence_attestation_factory_construction_required")
        parsed, canonical = _parse_attestation(self.attestation_json)
        if (
            self.schema_version != parsed["schema_version"]
            or self.auth_key_id != parsed["auth_key_id"]
            or self.auth_tag != parsed["auth_tag"]
            or self.attestation_json != canonical
        ):
            _validation_error("source_evidence_attestation_artifact_binding_mismatch")

    @property
    def material(self) -> dict[str, object]:
        """Return a fresh untrusted declaration copy; use the verifier for trust."""

        parsed, _canonical = _parse_attestation(self.attestation_json)
        return cast(dict[str, object], parsed["attestation_material"])

    def __repr__(self) -> str:
        return (
            "SourceEvidenceAdapterAttestationV4("
            f"schema_version={self.schema_version!r}, auth_key_id={self.auth_key_id!r}, "
            "attestation_json=<redacted-context>, auth_tag=<redacted>)"
        )


def parse_source_evidence_adapter_attestation_v4(
    value: str | bytes,
) -> SourceEvidenceAdapterAttestationV4:
    """Parse one canonical artifact without claiming that its tag is valid."""

    parsed, canonical = _parse_attestation(value)
    return SourceEvidenceAdapterAttestationV4(
        schema_version=cast(str, parsed["schema_version"]),
        auth_key_id=cast(str, parsed["auth_key_id"]),
        auth_tag=cast(str, parsed["auth_tag"]),
        attestation_json=canonical,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


class SourceEvidenceAuthenticatorV4:
    """Immutable signer holding one opaque dedicated provenance key."""

    __slots__ = ("__auth_key_id", "__provenance_key")
    __auth_key_id: str
    __provenance_key: bytes

    def __init__(self, *, auth_key_id: str, provenance_key: bytes) -> None:
        validated_key_id = _safe_key_id(auth_key_id)
        validated_key = _validated_provenance_key(provenance_key)
        object.__setattr__(self, "_SourceEvidenceAuthenticatorV4__auth_key_id", validated_key_id)
        object.__setattr__(self, "_SourceEvidenceAuthenticatorV4__provenance_key", validated_key)

    def __setattr__(self, _name: str, _value: object) -> NoReturn:
        raise AttributeError("source_evidence_authenticator_is_immutable")

    def __repr__(self) -> str:
        return (
            "SourceEvidenceAuthenticatorV4("
            f"auth_key_id={self.__auth_key_id!r}, provenance_key=<redacted>)"
        )

    def __getstate__(self) -> NoReturn:
        raise TypeError("source_evidence_authenticator_not_serializable")

    def __reduce__(self) -> NoReturn:
        raise TypeError("source_evidence_authenticator_not_serializable")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> NoReturn:
        raise TypeError("source_evidence_authenticator_not_serializable")

    @property
    def auth_key_id(self) -> str:
        """Return only the non-secret identifier written into new artifacts."""

        return self.__auth_key_id

    def sign(self, material: dict[str, object]) -> SourceEvidenceAdapterAttestationV4:
        """Authenticate one exact adapter-output context without granting admission."""

        validated_material = _snapshot_and_validate_material(material)
        unsigned = _unsigned_attestation_material(
            auth_key_id=self.__auth_key_id,
            material=validated_material,
        )
        auth_tag = hmac.new(
            self.__provenance_key,
            SOURCE_EVIDENCE_AUTH_DOMAIN_SEPARATOR + _canonical_json_bytes(unsigned),
            hashlib.sha256,
        ).hexdigest()
        envelope = {**unsigned, "auth_tag": auth_tag}
        return parse_source_evidence_adapter_attestation_v4(_canonical_json_bytes(envelope))


class SourceEvidenceVerifierV4:
    """Verifier using caller-owned expected context and retained-key resolver."""

    __slots__ = ("__retained_key_resolver",)
    __retained_key_resolver: RetainedSourceEvidenceKeyResolver

    def __init__(self, *, retained_key_resolver: RetainedSourceEvidenceKeyResolver) -> None:
        if not callable(retained_key_resolver):
            _validation_error("source_evidence_retained_key_resolver_invalid")
        object.__setattr__(
            self,
            "_SourceEvidenceVerifierV4__retained_key_resolver",
            retained_key_resolver,
        )

    def __setattr__(self, _name: str, _value: object) -> NoReturn:
        raise AttributeError("source_evidence_verifier_is_immutable")

    def __repr__(self) -> str:
        return "SourceEvidenceVerifierV4(retained_key_resolver=<redacted>)"

    def __getstate__(self) -> NoReturn:
        raise TypeError("source_evidence_verifier_not_serializable")

    def __reduce__(self) -> NoReturn:
        raise TypeError("source_evidence_verifier_not_serializable")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> NoReturn:
        raise TypeError("source_evidence_verifier_not_serializable")

    def verify(
        self,
        artifact: SourceEvidenceAdapterAttestationV4 | str | bytes,
        *,
        expected_auth_key_id: str,
        expected_material: dict[str, object],
    ) -> Mapping[str, object]:
        """Freshly authenticate and return detached read-only material.

        The return value is data, not a transferable authentication capability.
        Every consumer must call this method at its trust boundary with its own
        complete expected context; parsed artifact fields and prior successful
        calls must never substitute for a fresh verification.
        """

        expected_key_id = _safe_key_id(expected_auth_key_id)
        validated_expected = _snapshot_and_validate_material(expected_material)
        if type(artifact) is SourceEvidenceAdapterAttestationV4:
            parsed_artifact, _canonical = _parse_attestation(artifact.attestation_json)
        elif type(artifact) in (str, bytes):
            parsed_artifact, _canonical = _parse_attestation(artifact)
        else:
            _verification_error("source_evidence_attestation_verification_failed")

        try:
            resolved_key = self.__retained_key_resolver(expected_key_id)
        except Exception:
            _verification_error("source_evidence_retained_key_unavailable")
        try:
            key = _validated_provenance_key(resolved_key)
        except SourceEvidenceAuthenticatorV4ValidationError:
            _verification_error("source_evidence_retained_key_unavailable")

        supplied_tag = cast(str, parsed_artifact["auth_tag"])
        unsigned = {
            key_name: field_value
            for key_name, field_value in parsed_artifact.items()
            if key_name != "auth_tag"
        }
        expected_tag = hmac.new(
            key,
            SOURCE_EVIDENCE_AUTH_DOMAIN_SEPARATOR + _canonical_json_bytes(unsigned),
            hashlib.sha256,
        ).hexdigest()
        # Both comparisons use compare_digest.  The tag comparison is executed
        # for every structurally accepted tag, including malformed-but-bounded
        # text, before its hexadecimal form is considered.
        tag_matches = hmac.compare_digest(expected_tag, supplied_tag)
        artifact_material = cast(dict[str, object], parsed_artifact["attestation_material"])
        context_matches = hmac.compare_digest(
            _canonical_json_bytes(artifact_material),
            _canonical_json_bytes(validated_expected),
        )
        metadata_matches = (
            parsed_artifact["schema_version"] == SOURCE_EVIDENCE_ATTESTATION_V4_SCHEMA_VERSION
            and parsed_artifact["auth_algorithm"] == SOURCE_EVIDENCE_AUTH_ALGORITHM
            and parsed_artifact["auth_domain"] == SOURCE_EVIDENCE_AUTH_DOMAIN
            and parsed_artifact["auth_key_id"] == expected_key_id
        )
        if (
            _AUTH_TAG_RE.fullmatch(supplied_tag) is None
            or not tag_matches
            or not context_matches
            or not metadata_matches
        ):
            _verification_error("source_evidence_attestation_verification_failed")
        # The contract is deliberately flat and scalar-only.  Copy the exact
        # authenticated artifact material and expose it through a read-only
        # mapping without any nominal "verified" type or cached authority.
        return MappingProxyType(dict(artifact_material))


__all__ = [
    "MAX_SOURCE_EVIDENCE_ATTESTATION_BYTES",
    "MAX_SOURCE_EVIDENCE_JSON_DEPTH",
    "MAX_SOURCE_EVIDENCE_JSON_NODES",
    "MAX_SOURCE_EVIDENCE_PAYLOAD_BYTES",
    "MAX_SOURCE_EVIDENCE_PROVENANCE_KEY_BYTES",
    "MAX_SOURCE_EVIDENCE_TOTAL_TEXT_BYTES",
    "MIN_SOURCE_EVIDENCE_PROVENANCE_KEY_BYTES",
    "POSITIVE_SOURCE_READ_EVIDENCE_KIND",
    "SOURCE_EVIDENCE_ATTESTATION_MATERIAL_V4_CONTRACT_VERSION",
    "SOURCE_EVIDENCE_ATTESTATION_V4_SCHEMA_VERSION",
    "SOURCE_EVIDENCE_AUTH_ALGORITHM",
    "SOURCE_EVIDENCE_AUTH_DOMAIN",
    "SOURCE_EVIDENCE_AUTH_DOMAIN_SEPARATOR",
    "RetainedSourceEvidenceKeyResolver",
    "SourceEvidenceAdapterAttestationV4",
    "SourceEvidenceAuthenticatorV4",
    "SourceEvidenceAuthenticatorV4Error",
    "SourceEvidenceAuthenticatorV4ValidationError",
    "SourceEvidenceAuthenticatorV4VerificationError",
    "SourceEvidenceVerifierV4",
    "parse_source_evidence_adapter_attestation_v4",
    "validate_source_evidence_attestation_material_v4",
]
