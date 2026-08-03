"""Generic audit-only Ed25519 attestation for exact source-evidence material.

This module supplies one deliberately narrow cryptographic primitive.  A
producer can sign one exact, bounded canonical-JSON object.  A verifier must
provide the registry-owned raw Ed25519 public key, its independently retained
SHA-256 fingerprint, the independently expected trust-anchor ID, and the
complete expected material.  Nothing in an artifact resolves or selects a
trust anchor.

The artifact contains only declarations of the trust-anchor ID and public-key
fingerprint so that those declarations are covered by the signature.  It does
not contain a public key, key resolver, certificate, URL, or private key.  The
verifier compares the declarations with its explicit registry inputs and
recomputes the fingerprint from the registry public-key bytes before verifying
the signature.

Successful verification proves possession of the corresponding signing key
for the exact expected bytes in this domain.  It does not prove source payload
semantics, finality, upstream-producer identity, dependency completeness, or
any trainer/trading authorization.  The returned result is detached, flat,
read-only audit data containing only immutable scalar values.  This module has
no runtime wiring or I/O.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, NoReturn, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SOURCE_EVIDENCE_ED25519_ATTESTATION_V4_SCHEMA_VERSION = (
    "trainer_source_evidence_ed25519_attestation_v4"
)
SOURCE_EVIDENCE_ED25519_VERIFICATION_V4_SCHEMA_VERSION = (
    "trainer_source_evidence_ed25519_verification_v4"
)
SOURCE_EVIDENCE_ED25519_ALGORITHM = "Ed25519"
SOURCE_EVIDENCE_ED25519_DOMAIN = "v2/native-trainer/source-evidence-ed25519-attestation/v4"
SOURCE_EVIDENCE_ED25519_DOMAIN_SEPARATOR = SOURCE_EVIDENCE_ED25519_DOMAIN.encode("ascii") + b"\0"

# These are parser/cryptographic safety invariants, not market, risk, sizing,
# leverage, margin, or trainer-admission thresholds.
ED25519_PRIVATE_KEY_BYTES = 32
ED25519_PUBLIC_KEY_BYTES = 32
ED25519_SIGNATURE_BYTES = 64
MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES = 64 * 1024
MAX_SOURCE_EVIDENCE_ED25519_MATERIAL_BYTES = 48 * 1024
MAX_SOURCE_EVIDENCE_ED25519_JSON_DEPTH = 10
MAX_SOURCE_EVIDENCE_ED25519_JSON_NODES = 512
MAX_SOURCE_EVIDENCE_ED25519_CONTAINER_ITEMS = 128
MAX_SOURCE_EVIDENCE_ED25519_KEY_BYTES = 256
MAX_SOURCE_EVIDENCE_ED25519_STRING_BYTES = 8 * 1024
MAX_SOURCE_EVIDENCE_ED25519_TOTAL_TEXT_BYTES = 32 * 1024
MIN_SOURCE_EVIDENCE_ED25519_INTEGER = -(2**63)
MAX_SOURCE_EVIDENCE_ED25519_INTEGER = 2**63 - 1

_TRUST_ANCHOR_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$",
    re.ASCII,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SIGNATURE_HEX_RE = re.compile(r"^[0-9a-f]{128}$", re.ASCII)
_CONSTRUCTION_TOKEN = object()

_FIXED_FALSE_DOWNSTREAM_FIELDS = (
    "upstream_producer_authenticated",
    "source_payload_semantics_verified",
    "source_finality_recomputed",
    "dependency_manifest_bound",
    "per_field_receipt_bound",
    "feature_snapshot_published",
    "consumer_eligible",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_wired",
)
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "signature_algorithm",
        "signature_domain",
        "declared_trust_anchor_id",
        "declared_public_key_sha256",
        "attested_material_sha256",
        "attested_material",
        "audit_only",
        *_FIXED_FALSE_DOWNSTREAM_FIELDS,
        "signature_hex",
    }
)
_VERIFIER_ONLY_MATERIAL_FIELDS = frozenset(
    {
        "cryptographic_signature_verified",
        "registry_trust_anchor_binding_verified",
        "expected_material_exact_match_verified",
    }
)


class SourceEvidenceEd25519AttestationV4Error(RuntimeError):
    """Base failure that never includes key, signature, or source material."""


class SourceEvidenceEd25519AttestationV4ValidationError(SourceEvidenceEd25519AttestationV4Error):
    """Caller input or serialized structure violates the bounded contract."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


class SourceEvidenceEd25519AttestationV4VerificationError(SourceEvidenceEd25519AttestationV4Error):
    """Cryptographic or exact expected-context verification failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(reasons))
        super().__init__(";".join(self.reasons))


def _validation_error(reason: str) -> NoReturn:
    raise SourceEvidenceEd25519AttestationV4ValidationError(reason) from None


def _verification_error(reason: str) -> NoReturn:
    raise SourceEvidenceEd25519AttestationV4VerificationError(reason) from None


def _reject_json_constant(_value: str) -> NoReturn:
    _validation_error("source_evidence_ed25519_json_constant_forbidden")


def _reject_json_float(_value: str) -> NoReturn:
    _validation_error("source_evidence_ed25519_json_float_forbidden")


def _parse_json_int(value: str) -> int:
    # The lexical bound prevents Python's integer conversion from receiving an
    # attacker-sized decimal before the numeric range check can run.
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 19:
        _validation_error("source_evidence_ed25519_json_integer_out_of_range")
    try:
        parsed = int(value)
    except ValueError:
        _validation_error("source_evidence_ed25519_json_integer_out_of_range")
    if not MIN_SOURCE_EVIDENCE_ED25519_INTEGER <= parsed <= MAX_SOURCE_EVIDENCE_ED25519_INTEGER:
        _validation_error("source_evidence_ed25519_json_integer_out_of_range")
    return parsed


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _validation_error("source_evidence_ed25519_duplicate_json_key")
        result[key] = value
    return result


def _ascii_text_bytes(value: str, *, reason: str) -> bytes:
    try:
        return value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _validation_error(reason)


def _bounded_json_snapshot(value: object) -> object:
    """Create a detached JSON tree while enforcing every resource bound."""

    nodes = 0
    total_text_bytes = 0

    def snapshot(item: object, *, depth: int) -> object:
        nonlocal nodes, total_text_bytes
        nodes += 1
        if nodes > MAX_SOURCE_EVIDENCE_ED25519_JSON_NODES:
            _validation_error("source_evidence_ed25519_json_node_limit_exceeded")
        if depth > MAX_SOURCE_EVIDENCE_ED25519_JSON_DEPTH:
            _validation_error("source_evidence_ed25519_json_depth_limit_exceeded")

        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            try:
                pairs = tuple(mapping.items())
            except RuntimeError:
                _validation_error("source_evidence_ed25519_json_mutated_during_snapshot")
            if len(pairs) != len(mapping):
                _validation_error("source_evidence_ed25519_json_mutated_during_snapshot")
            if len(pairs) > MAX_SOURCE_EVIDENCE_ED25519_CONTAINER_ITEMS:
                _validation_error("source_evidence_ed25519_json_container_limit_exceeded")
            detached: dict[str, object] = {}
            for key, child in pairs:
                if type(key) is not str:
                    _validation_error("source_evidence_ed25519_json_key_invalid")
                key_bytes = _ascii_text_bytes(
                    key,
                    reason="source_evidence_ed25519_non_ascii_text_forbidden",
                )
                if not key_bytes or len(key_bytes) > MAX_SOURCE_EVIDENCE_ED25519_KEY_BYTES:
                    _validation_error("source_evidence_ed25519_json_key_invalid")
                total_text_bytes += len(key_bytes)
                if total_text_bytes > MAX_SOURCE_EVIDENCE_ED25519_TOTAL_TEXT_BYTES:
                    _validation_error("source_evidence_ed25519_json_text_limit_exceeded")
                detached[key] = snapshot(child, depth=depth + 1)
            return detached

        if type(item) is list:
            sequence = cast(list[object], item)
            try:
                children = tuple(sequence)
            except RuntimeError:
                _validation_error("source_evidence_ed25519_json_mutated_during_snapshot")
            if len(children) != len(sequence):
                _validation_error("source_evidence_ed25519_json_mutated_during_snapshot")
            if len(children) > MAX_SOURCE_EVIDENCE_ED25519_CONTAINER_ITEMS:
                _validation_error("source_evidence_ed25519_json_container_limit_exceeded")
            return [snapshot(child, depth=depth + 1) for child in children]

        if type(item) is str:
            item_bytes = _ascii_text_bytes(
                item,
                reason="source_evidence_ed25519_non_ascii_text_forbidden",
            )
            if len(item_bytes) > MAX_SOURCE_EVIDENCE_ED25519_STRING_BYTES:
                _validation_error("source_evidence_ed25519_json_string_limit_exceeded")
            total_text_bytes += len(item_bytes)
            if total_text_bytes > MAX_SOURCE_EVIDENCE_ED25519_TOTAL_TEXT_BYTES:
                _validation_error("source_evidence_ed25519_json_text_limit_exceeded")
            return item

        if item is None or type(item) is bool:
            return item
        if type(item) is int:
            number = item
            if not (
                MIN_SOURCE_EVIDENCE_ED25519_INTEGER <= number <= MAX_SOURCE_EVIDENCE_ED25519_INTEGER
            ):
                _validation_error("source_evidence_ed25519_json_integer_out_of_range")
            return number
        _validation_error("source_evidence_ed25519_json_value_type_invalid")

    return snapshot(value, depth=1)


def _canonical_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    snapshot = _bounded_json_snapshot(value)
    try:
        encoded = json.dumps(
            snapshot,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _validation_error("source_evidence_ed25519_not_strict_ascii_json")
    if not encoded or len(encoded) > maximum_bytes:
        _validation_error("source_evidence_ed25519_json_size_limit_exceeded")
    return encoded


def _parse_exact_json_object(value: object) -> dict[str, object]:
    if type(value) is bytes:
        raw = bytes(value)
    elif type(value) is str:
        if not value or len(value) > MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES:
            _validation_error("source_evidence_ed25519_json_input_invalid")
        raw = _ascii_text_bytes(
            value,
            reason="source_evidence_ed25519_json_input_invalid",
        )
    else:
        _validation_error("source_evidence_ed25519_json_input_invalid")
    if not raw or len(raw) > MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES:
        _validation_error("source_evidence_ed25519_json_input_invalid")
    try:
        text = raw.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        _validation_error("source_evidence_ed25519_json_input_invalid")
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_json_constant,
            parse_float=_reject_json_float,
            parse_int=_parse_json_int,
        )
    except SourceEvidenceEd25519AttestationV4ValidationError:
        raise
    except (json.JSONDecodeError, OverflowError, RecursionError, TypeError, ValueError):
        _validation_error("source_evidence_ed25519_json_input_invalid")
    if type(parsed) is not dict:
        _validation_error("source_evidence_ed25519_json_not_exact_object")
    detached = cast(
        dict[str, object],
        _bounded_json_snapshot(cast(dict[str, object], parsed)),
    )
    canonical = _canonical_json_bytes(
        detached,
        maximum_bytes=MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES,
    )
    if not hmac.compare_digest(canonical, raw):
        _validation_error("source_evidence_ed25519_json_not_exact_canonical")
    return detached


def _validate_material_non_authority(value: dict[str, object]) -> None:
    stack: list[object] = [value]
    while stack:
        item = stack.pop()
        if type(item) is dict:
            mapping = cast(dict[str, object], item)
            for key, child in mapping.items():
                if key in _FIXED_FALSE_DOWNSTREAM_FIELDS and child is not False:
                    _validation_error("source_evidence_ed25519_material_authority_forbidden")
                if key == "audit_only" and child is not True:
                    _validation_error("source_evidence_ed25519_material_authority_forbidden")
                if key in _VERIFIER_ONLY_MATERIAL_FIELDS:
                    _validation_error("source_evidence_ed25519_material_verifier_claim_forbidden")
                stack.append(child)
        elif type(item) is list:
            stack.extend(cast(list[object], item))


def _snapshot_material(value: object) -> tuple[dict[str, object], bytes]:
    if type(value) is not dict:
        _validation_error("source_evidence_ed25519_material_not_exact_object")
    snapshot = cast(dict[str, object], _bounded_json_snapshot(value))
    if not snapshot:
        _validation_error("source_evidence_ed25519_material_empty")
    canonical = _canonical_json_bytes(
        snapshot,
        maximum_bytes=MAX_SOURCE_EVIDENCE_ED25519_MATERIAL_BYTES,
    )
    # Round-trip through the strict parser to detach aliases and hold Python
    # inputs to the same representation accepted from serialized artifacts.
    parsed = _parse_exact_json_object(canonical)
    _validate_material_non_authority(parsed)
    return parsed, canonical


def _safe_trust_anchor_id(value: object) -> str:
    if type(value) is not str:
        _validation_error("source_evidence_ed25519_trust_anchor_id_invalid")
    text = value
    if not text.isascii() or _TRUST_ANCHOR_ID_RE.fullmatch(text) is None:
        _validation_error("source_evidence_ed25519_trust_anchor_id_invalid")
    return text


def _lower_sha256(value: object, *, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _validation_error(reason)
    return value


def _validated_public_key_bytes(value: object) -> bytes:
    if type(value) is not bytes or len(value) != ED25519_PUBLIC_KEY_BYTES:
        _validation_error("source_evidence_ed25519_registry_public_key_invalid")
    return bytes(value)


def source_evidence_ed25519_public_key_sha256_v4(public_key_bytes: bytes) -> str:
    """Return the lowercase fingerprint of exact raw Ed25519 public-key bytes."""

    key = _validated_public_key_bytes(public_key_bytes)
    return hashlib.sha256(key).hexdigest()


def _unsigned_envelope(
    *,
    trust_anchor_id: str,
    public_key_sha256: str,
    material: dict[str, object],
    material_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": SOURCE_EVIDENCE_ED25519_ATTESTATION_V4_SCHEMA_VERSION,
        "signature_algorithm": SOURCE_EVIDENCE_ED25519_ALGORITHM,
        "signature_domain": SOURCE_EVIDENCE_ED25519_DOMAIN,
        "declared_trust_anchor_id": trust_anchor_id,
        "declared_public_key_sha256": public_key_sha256,
        "attested_material_sha256": material_sha256,
        "attested_material": material,
        "audit_only": True,
        **{field_name: False for field_name in _FIXED_FALSE_DOWNSTREAM_FIELDS},
    }


def _validate_envelope(value: dict[str, object]) -> dict[str, object]:
    if set(value) != _ENVELOPE_FIELDS:
        _validation_error("source_evidence_ed25519_envelope_field_set_mismatch")
    constants: dict[str, object] = {
        "schema_version": SOURCE_EVIDENCE_ED25519_ATTESTATION_V4_SCHEMA_VERSION,
        "signature_algorithm": SOURCE_EVIDENCE_ED25519_ALGORITHM,
        "signature_domain": SOURCE_EVIDENCE_ED25519_DOMAIN,
        "audit_only": True,
        **{field_name: False for field_name in _FIXED_FALSE_DOWNSTREAM_FIELDS},
    }
    for field_name, expected in constants.items():
        supplied = value[field_name]
        if type(supplied) is not type(expected) or supplied != expected:
            _validation_error("source_evidence_ed25519_envelope_constant_mismatch")

    trust_anchor_id = _safe_trust_anchor_id(value["declared_trust_anchor_id"])
    public_key_sha256 = _lower_sha256(
        value["declared_public_key_sha256"],
        reason="source_evidence_ed25519_declared_public_key_fingerprint_invalid",
    )
    material_sha256 = _lower_sha256(
        value["attested_material_sha256"],
        reason="source_evidence_ed25519_material_digest_invalid",
    )
    material, material_bytes = _snapshot_material(value["attested_material"])
    if not hmac.compare_digest(hashlib.sha256(material_bytes).hexdigest(), material_sha256):
        _validation_error("source_evidence_ed25519_material_digest_mismatch")
    signature = value["signature_hex"]
    if type(signature) is not str or _SIGNATURE_HEX_RE.fullmatch(signature) is None:
        _validation_error("source_evidence_ed25519_signature_encoding_invalid")

    return {
        **_unsigned_envelope(
            trust_anchor_id=trust_anchor_id,
            public_key_sha256=public_key_sha256,
            material=material,
            material_sha256=material_sha256,
        ),
        "signature_hex": signature,
    }


def _parse_and_validate_envelope(value: object) -> tuple[dict[str, object], str]:
    parsed = _parse_exact_json_object(value)
    validated = _validate_envelope(parsed)
    canonical_bytes = _canonical_json_bytes(
        validated,
        maximum_bytes=MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES,
    )
    return validated, canonical_bytes.decode("ascii")


@dataclass(frozen=True, slots=True, repr=False)
class SourceEvidenceEd25519AttestationV4:
    """Canonical signed artifact; construction or parsing is not verification."""

    schema_version: str
    declared_trust_anchor_id: str
    declared_public_key_sha256: str
    attested_material_sha256: str
    signature_hex: str = field(repr=False)
    attestation_json: str = field(repr=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._construction_token is not _CONSTRUCTION_TOKEN:
            _validation_error("source_evidence_ed25519_factory_construction_required")
        parsed, canonical = _parse_and_validate_envelope(self.attestation_json)
        if (
            self.schema_version != parsed["schema_version"]
            or self.declared_trust_anchor_id != parsed["declared_trust_anchor_id"]
            or self.declared_public_key_sha256 != parsed["declared_public_key_sha256"]
            or self.attested_material_sha256 != parsed["attested_material_sha256"]
            or self.signature_hex != parsed["signature_hex"]
            or self.attestation_json != canonical
        ):
            _validation_error("source_evidence_ed25519_artifact_binding_mismatch")

    def __repr__(self) -> str:
        return (
            "SourceEvidenceEd25519AttestationV4("
            f"schema_version={self.schema_version!r}, "
            f"declared_trust_anchor_id={self.declared_trust_anchor_id!r}, "
            f"declared_public_key_sha256={self.declared_public_key_sha256!r}, "
            "attested_material_sha256=<redacted>, signature_hex=<redacted>, "
            "attestation_json=<redacted>)"
        )


def parse_source_evidence_ed25519_attestation_v4(
    value: str | bytes,
) -> SourceEvidenceEd25519AttestationV4:
    """Parse one canonical artifact without treating its declarations as trusted."""

    parsed, canonical = _parse_and_validate_envelope(value)
    return SourceEvidenceEd25519AttestationV4(
        schema_version=cast(str, parsed["schema_version"]),
        declared_trust_anchor_id=cast(str, parsed["declared_trust_anchor_id"]),
        declared_public_key_sha256=cast(str, parsed["declared_public_key_sha256"]),
        attested_material_sha256=cast(str, parsed["attested_material_sha256"]),
        signature_hex=cast(str, parsed["signature_hex"]),
        attestation_json=canonical,
        _construction_token=_CONSTRUCTION_TOKEN,
    )


def sign_source_evidence_ed25519_attestation_v4_for_producer(
    *,
    private_key_bytes: bytes,
    declared_trust_anchor_id: str,
    attested_material: dict[str, object],
) -> SourceEvidenceEd25519AttestationV4:
    """Create an audit artifact for a producer or test harness.

    This helper accepts a private key solely to create the signature.  It is
    not a verifier, registry, authorization capability, runtime integration,
    or source-semantics assertion.  The private key remains caller-owned and
    is neither retained nor serialized.
    """

    trust_anchor_id = _safe_trust_anchor_id(declared_trust_anchor_id)
    if type(private_key_bytes) is not bytes or len(private_key_bytes) != ED25519_PRIVATE_KEY_BYTES:
        _validation_error("source_evidence_ed25519_private_key_invalid")
    private_bytes = bytes(private_key_bytes)
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(private_bytes)
        public_key_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    except (TypeError, ValueError):
        _validation_error("source_evidence_ed25519_private_key_invalid")

    material, material_bytes = _snapshot_material(attested_material)
    material_sha256 = hashlib.sha256(material_bytes).hexdigest()
    unsigned = _unsigned_envelope(
        trust_anchor_id=trust_anchor_id,
        public_key_sha256=hashlib.sha256(public_key_bytes).hexdigest(),
        material=material,
        material_sha256=material_sha256,
    )
    signature = private_key.sign(
        SOURCE_EVIDENCE_ED25519_DOMAIN_SEPARATOR
        + _canonical_json_bytes(
            unsigned,
            maximum_bytes=MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES,
        )
    )
    if len(signature) != ED25519_SIGNATURE_BYTES:  # pragma: no cover - backend invariant
        _validation_error("source_evidence_ed25519_signature_size_invalid")
    envelope = {**unsigned, "signature_hex": signature.hex()}
    return parse_source_evidence_ed25519_attestation_v4(
        _canonical_json_bytes(
            envelope,
            maximum_bytes=MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES,
        )
    )


def verify_source_evidence_ed25519_attestation_v4(
    artifact: SourceEvidenceEd25519AttestationV4 | str | bytes,
    *,
    registry_public_key_bytes: bytes,
    registry_public_key_sha256: str,
    expected_trust_anchor_id: str,
    expected_material: dict[str, object],
) -> MappingProxyType[str, object]:
    """Verify against explicit registry inputs and complete expected material.

    No artifact field is used to find a public key.  Callers must obtain all
    ``registry_*`` and ``expected_*`` inputs from their own trusted registry
    and point-in-time replay context.
    """

    try:
        trust_anchor_id = _safe_trust_anchor_id(expected_trust_anchor_id)
        public_key_bytes = _validated_public_key_bytes(registry_public_key_bytes)
        expected_public_key_sha256 = _lower_sha256(
            registry_public_key_sha256,
            reason="source_evidence_ed25519_registry_public_key_fingerprint_invalid",
        )
        material, material_bytes = _snapshot_material(expected_material)
    except SourceEvidenceEd25519AttestationV4ValidationError:
        _verification_error("source_evidence_ed25519_expected_registry_context_invalid")

    computed_public_key_sha256 = hashlib.sha256(public_key_bytes).hexdigest()
    if not hmac.compare_digest(computed_public_key_sha256, expected_public_key_sha256):
        _verification_error("source_evidence_ed25519_registry_public_key_fingerprint_mismatch")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    except (TypeError, ValueError):
        _verification_error("source_evidence_ed25519_registry_public_key_invalid")

    try:
        if type(artifact) is SourceEvidenceEd25519AttestationV4:
            parsed, canonical = _parse_and_validate_envelope(artifact.attestation_json)
        elif type(artifact) in (str, bytes):
            parsed, canonical = _parse_and_validate_envelope(artifact)
        else:
            _verification_error("source_evidence_ed25519_attestation_verification_failed")
    except SourceEvidenceEd25519AttestationV4ValidationError:
        _verification_error("source_evidence_ed25519_attestation_verification_failed")

    artifact_material = cast(dict[str, object], parsed["attested_material"])
    artifact_material_bytes = _canonical_json_bytes(
        artifact_material,
        maximum_bytes=MAX_SOURCE_EVIDENCE_ED25519_MATERIAL_BYTES,
    )
    unsigned = {key: item for key, item in parsed.items() if key != "signature_hex"}
    signature = bytes.fromhex(cast(str, parsed["signature_hex"]))
    try:
        public_key.verify(
            signature,
            SOURCE_EVIDENCE_ED25519_DOMAIN_SEPARATOR
            + _canonical_json_bytes(
                unsigned,
                maximum_bytes=MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES,
            ),
        )
        signature_valid = True
    except (InvalidSignature, TypeError, ValueError):
        signature_valid = False

    material_sha256 = hashlib.sha256(material_bytes).hexdigest()
    metadata_matches = (
        parsed["declared_trust_anchor_id"] == trust_anchor_id
        and hmac.compare_digest(
            cast(str, parsed["declared_public_key_sha256"]),
            expected_public_key_sha256,
        )
        and hmac.compare_digest(
            cast(str, parsed["attested_material_sha256"]),
            material_sha256,
        )
    )
    material_matches = hmac.compare_digest(artifact_material_bytes, material_bytes)
    if not signature_valid or not metadata_matches or not material_matches:
        _verification_error("source_evidence_ed25519_attestation_verification_failed")

    # Scalar-only values make the result deeply immutable as well as detached:
    # no artifact or caller-owned dict/list is returned through the mapping.
    result: dict[str, object] = {
        "schema_version": SOURCE_EVIDENCE_ED25519_VERIFICATION_V4_SCHEMA_VERSION,
        "signature_algorithm": SOURCE_EVIDENCE_ED25519_ALGORITHM,
        "signature_domain": SOURCE_EVIDENCE_ED25519_DOMAIN,
        "trust_anchor_id": trust_anchor_id,
        "registry_public_key_sha256": expected_public_key_sha256,
        "attested_material_sha256": material_sha256,
        "attested_material_canonical_json": material_bytes.decode("ascii"),
        "artifact_sha256": hashlib.sha256(canonical.encode("ascii")).hexdigest(),
        "cryptographic_signature_verified": True,
        "registry_trust_anchor_binding_verified": True,
        "expected_material_exact_match_verified": True,
        "audit_only": True,
        **{field_name: False for field_name in _FIXED_FALSE_DOWNSTREAM_FIELDS},
    }
    return MappingProxyType(result)


__all__ = [
    "ED25519_PRIVATE_KEY_BYTES",
    "ED25519_PUBLIC_KEY_BYTES",
    "ED25519_SIGNATURE_BYTES",
    "MAX_SOURCE_EVIDENCE_ED25519_ATTESTATION_BYTES",
    "MAX_SOURCE_EVIDENCE_ED25519_CONTAINER_ITEMS",
    "MAX_SOURCE_EVIDENCE_ED25519_JSON_DEPTH",
    "MAX_SOURCE_EVIDENCE_ED25519_JSON_NODES",
    "MAX_SOURCE_EVIDENCE_ED25519_KEY_BYTES",
    "MAX_SOURCE_EVIDENCE_ED25519_MATERIAL_BYTES",
    "MAX_SOURCE_EVIDENCE_ED25519_STRING_BYTES",
    "MAX_SOURCE_EVIDENCE_ED25519_TOTAL_TEXT_BYTES",
    "SOURCE_EVIDENCE_ED25519_ALGORITHM",
    "SOURCE_EVIDENCE_ED25519_ATTESTATION_V4_SCHEMA_VERSION",
    "SOURCE_EVIDENCE_ED25519_DOMAIN",
    "SOURCE_EVIDENCE_ED25519_DOMAIN_SEPARATOR",
    "SOURCE_EVIDENCE_ED25519_VERIFICATION_V4_SCHEMA_VERSION",
    "SourceEvidenceEd25519AttestationV4",
    "SourceEvidenceEd25519AttestationV4Error",
    "SourceEvidenceEd25519AttestationV4ValidationError",
    "SourceEvidenceEd25519AttestationV4VerificationError",
    "parse_source_evidence_ed25519_attestation_v4",
    "sign_source_evidence_ed25519_attestation_v4_for_producer",
    "source_evidence_ed25519_public_key_sha256_v4",
    "verify_source_evidence_ed25519_attestation_v4",
]
