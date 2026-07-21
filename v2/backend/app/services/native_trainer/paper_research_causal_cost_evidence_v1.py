"""Signed configured-fee causal cost evidence for paper/research analysis.

This module is a deliberately separate sibling of
``causal_cost_evidence_v1``.  The profiled publisher requires an
account-authenticated Binance USD-M commission response and accepts only its
exact factory result type.  This module never synthesizes that response and
never returns that type.  Instead, an independently configured Ed25519 trust
anchor signs one exact public/configured fee-schedule material object.  The
signature authenticates the configuration publisher and exact bytes; it does
not assert an account fee tier or an upstream Binance signature.

The remaining spread, impact, funding, and expected-notional inputs reuse the
same fail-closed point-in-time validators as the profiled causal-cost primitive:
one atomic Redis capture, persisted source expiry, direct order-book sequence
continuity, mark-price clocks, and a no-fallback causal expected-notional
artifact.  All exact bytes and receipts are stored in immutable CAS.

The result is cost-component evidence only.  It cannot be passed to the
profiled enrichment factory and grants no trainer admission, optimizer,
checkpoint, model, prediction, paper, live, order, execution, or runtime
authority.  A separately authenticated research ledger/manifest/admission
path is required before any optimizer may consume it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from v2.backend.app.services.native_trainer import causal_cost_evidence_v1 as _causal
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    AtomicRedisSourceReadBatch,
)
from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
    CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256,
    CAUSAL_COST_ORDERED_FEATURE_NAMES,
    CausalCostEvidenceV1Error,
    CausalCostEvidenceV1IntegrityError,
)
from v2.backend.app.services.native_trainer.causal_expected_notional_policy_v1 import (
    CausalExpectedNotionalPolicyTokenV1,
    CausalExpectedNotionalPolicyV1Error,
    CausalExpectedNotionalPolicyV1IntegrityError,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)

PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION: Final = (
    "paper_research_causal_cost_evidence_v1"
)
PAPER_RESEARCH_CAUSAL_COST_COMPOSITE_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "paper_research_causal_cost_composite_derivation_receipt_v1"
)
PAPER_RESEARCH_FEE_SCHEDULE_MATERIAL_V1_SCHEMA_VERSION: Final = (
    "paper_research_configured_public_fee_schedule_material_v1"
)
PAPER_RESEARCH_FEE_SCHEDULE_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "paper_research_configured_public_fee_schedule_receipt_v1"
)
PAPER_RESEARCH_FEE_SCHEDULE_ATTESTATION_V1_SCHEMA_VERSION: Final = (
    "paper_research_configured_public_fee_schedule_attestation_v1"
)
PAPER_RESEARCH_FEE_SCHEDULE_ATTESTATION_V1_DOMAIN: Final = (
    "v2/native-trainer/paper-research-configured-public-fee-schedule/v1"
)
PAPER_RESEARCH_FEE_SCHEDULE_ATTESTATION_V1_DOMAIN_SEPARATOR: Final = (
    PAPER_RESEARCH_FEE_SCHEDULE_ATTESTATION_V1_DOMAIN.encode("ascii") + b"\0"
)
PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID: Final = (
    "SIGNED_CONFIGURED_PUBLIC_FEE_PLUS_CAUSAL_MARKET_COST_TRANSFORM_V1"
)
PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION: Final = (
    "PAPER_RESEARCH_COST_COMPONENT_EVIDENCE_NOT_ACCOUNT_COMMISSION_OR_TRAINER_AUTHORITY"
)
PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS: Final = (
    "UNWIRED_SEPARATE_RESEARCH_LEDGER_MANIFEST_AND_ADMISSION_REQUIRED"
)
PAPER_RESEARCH_FEE_AUTHORITY_SCOPE: Final = (
    "PAPER_RESEARCH_CONFIGURED_PUBLIC_FEE_SCHEDULE_NOT_ACCOUNT_SPECIFIC"
)
PAPER_RESEARCH_FEE_CONFIGURATION_AUTHENTICITY_SCOPE: Final = (
    "TRUST_ANCHOR_SIGNATURE_AUTHENTICATES_CONFIGURATION_BYTES_NOT_EXCHANGE_TRUTH"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,511}$", re.ASCII)
_FEE_DECIMAL_RE = re.compile(r"^(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,12})?$", re.ASCII)
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{128}$", re.ASCII)
_CONSTRUCTION_TOKEN = object()
# Serialization/resource and Ed25519 wire-format invariants only. These are
# not market, edge, freshness, risk, leverage, margin, or admission thresholds.
_MAX_SOURCE_DOCUMENT_BYTES = 2 * 1024 * 1024
_MAX_FEE_ATTESTATION_BYTES = 64 * 1024
_ED25519_PUBLIC_KEY_BYTES = 32
_ED25519_SIGNATURE_BYTES = 64

_AUTHORIZATION: Final = {
    "trainer_admission_authorized": False,
    "optimizer_execution_authorized": False,
    "checkpoint_write_authorized": False,
    "model_write_authorized": False,
    "prediction_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "runtime_wired": False,
}
_FEE_ATTESTATION_FIELDS = frozenset(
    {
        "schema_version",
        "signature_algorithm",
        "signature_domain",
        "declared_trust_anchor_id",
        "declared_public_key_sha256",
        "fee_material_sha256",
        "fee_material",
        "audit_only",
        *_AUTHORIZATION,
        "signature_hex",
    }
)

_FEE_MATERIAL_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "venue",
        "market",
        "symbol",
        "liquidity_role",
        "fee_semantics",
        "fee_unit",
        "taker_fee_bps_per_side_decimal",
        "source_document_sha256",
        "source_document_byte_count",
        "source_document_media_type",
        "source_document_locator",
        "source_revision",
        "source_observed_at",
        "effective_at",
        "available_at",
        "expires_at",
        "authority_scope",
        "configuration_authenticity_scope",
        "account_specific_commission_authenticated",
        "upstream_exchange_signature_verified",
        "audit_only",
        *_AUTHORIZATION,
    }
)

_IMPLEMENTATION_CONTRACT: Final = {
    "schema_version": "paper_research_causal_cost_implementation_contract_v1",
    "implementation_id": PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
    "shared_causal_market_notional_dependency_sha256": (
        CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
    ),
    "source_inventory": [
        "v2:orderbook:depth:binance:{symbol}",
        "v2:orderbook:features:binance:{symbol}",
        "v2:market:mark_price:{symbol}",
        "signed_configured_public_fee_schedule_material_and_source_document",
        "causal_expected_notional_policy_artifact_and_receipt",
    ],
    "ordered_outputs": list(CAUSAL_COST_ORDERED_FEATURE_NAMES),
    "fee_formula": "signed_configured_public_taker_fee_bps_per_side",
    "fee_authority_scope": PAPER_RESEARCH_FEE_AUTHORITY_SCOPE,
    "account_specific_commission_authenticated": False,
    "spread_formula": "(best_ask-best_bid)/mid*10000",
    "impact_formula": ("max(adverse_buy_vwap_bps,adverse_sell_vwap_bps)_at_exact_notional"),
    "funding_formula": (
        "raw_binance_stream_r_rate*10000_iff_next_funding_time_in_"
        "(decision_time,decision_time+900s]_else_zero"
    ),
    "freshness": "EXPLICIT_SOURCE_EXPIRY_ONLY_NO_CONSUMER_AGE_THRESHOLD",
    "fallbacks": [],
    "authority": "NONE_COST_COMPONENT_EVIDENCE_ONLY",
}
PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256: Final = hashlib.sha256(
    json.dumps(
        _IMPLEMENTATION_CONTRACT,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
).hexdigest()


class PaperResearchCausalCostEvidenceV1Error(RuntimeError):
    """Base fail-closed research-cost error with stable, data-safe reasons."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PaperResearchCausalCostEvidenceV1ValidationError(PaperResearchCausalCostEvidenceV1Error):
    """An input is missing, future, expired, ambiguous, or semantically invalid."""


class PaperResearchCausalCostEvidenceV1IntegrityError(PaperResearchCausalCostEvidenceV1Error):
    """A signature, exact-byte binding, CAS object, or result changed."""


def _validation(reason: str) -> NoReturn:
    raise PaperResearchCausalCostEvidenceV1ValidationError(reason) from None


def _integrity(reason: str) -> NoReturn:
    raise PaperResearchCausalCostEvidenceV1IntegrityError(reason) from None


def _module_code_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise PaperResearchCausalCostEvidenceV1IntegrityError(
            "PAPER_RESEARCH_COST_IMPLEMENTATION_BYTES_UNAVAILABLE"
        ) from exc


def _canonical_bytes(value: object, *, reason: str) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _validation(reason)
    if not encoded:
        _validation(reason)
    return encoded


def _sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_bytes(value, reason="PAPER_RESEARCH_COST_CANONICAL_JSON_INVALID")
    ).hexdigest()


def _clock(value: object, *, reason: str) -> tuple[str, datetime]:
    try:
        canonical, parsed = _causal._clock(value, reason=reason)  # noqa: SLF001
    except CausalCostEvidenceV1Error as exc:
        raise PaperResearchCausalCostEvidenceV1ValidationError(reason) from exc
    if value != canonical:
        _validation(reason)
    return canonical, parsed


def _label(value: object, *, reason: str, pattern: re.Pattern[str] = _LABEL_RE) -> str:
    if type(value) is not str or value != value.strip() or pattern.fullmatch(value) is None:
        _validation(reason)
    return value


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _address_mapping(address: SourcePayloadAddress) -> dict[str, Any]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _valid_address_mapping(value: object) -> bool:
    if type(value) is not dict:
        return False
    binding = cast(dict[str, Any], value)
    byte_count = binding.get("payload_byte_count")
    return (
        set(binding)
        == {
            "schema_version",
            "payload_sha256",
            "payload_byte_count",
            "relative_path",
        }
        and _valid_sha256(binding.get("payload_sha256"))
        and type(byte_count) is int
        and byte_count > 0
        and type(binding.get("relative_path")) is str
        and bool(binding.get("relative_path"))
    )


def _put_exact(
    store: ImmutableSourcePayloadStore,
    payload: bytes,
    *,
    reason: str,
) -> SourcePayloadAddress:
    digest = hashlib.sha256(payload).hexdigest()
    try:
        address = store.put(
            payload,
            expected_sha256=digest,
            expected_byte_count=len(payload),
        )
        readback = store.get(digest, expected_byte_count=len(payload))
    except SourcePayloadStoreError as exc:
        raise PaperResearchCausalCostEvidenceV1IntegrityError(reason) from exc
    if (
        address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or address.payload_sha256 != digest
        or address.payload_byte_count != len(payload)
        or not hmac.compare_digest(readback, payload)
    ):
        _integrity(reason)
    return address


def _fee_decimal(value: object) -> tuple[str, float]:
    if type(value) is not str or _FEE_DECIMAL_RE.fullmatch(value) is None:
        _validation("PAPER_RESEARCH_FEE_DECIMAL_INVALID")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        _validation("PAPER_RESEARCH_FEE_DECIMAL_INVALID")
    if not parsed.is_finite() or parsed < 0:
        _validation("PAPER_RESEARCH_FEE_DECIMAL_INVALID")
    resolved = float(parsed)
    if not math.isfinite(resolved) or (parsed != 0 and resolved == 0.0):
        _validation("PAPER_RESEARCH_FEE_DECIMAL_INVALID")
    return value, (0.0 if resolved == 0.0 else resolved)


def _strict_fee_material(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _validation("PAPER_RESEARCH_FEE_MATERIAL_OBJECT_REQUIRED")
    try:
        raw = _canonical_bytes(value, reason="PAPER_RESEARCH_FEE_MATERIAL_JSON_INVALID")
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PaperResearchCausalCostEvidenceV1ValidationError(
            "PAPER_RESEARCH_FEE_MATERIAL_JSON_INVALID"
        ) from exc
    if type(parsed) is not dict or frozenset(parsed) != _FEE_MATERIAL_FIELDS:
        _validation("PAPER_RESEARCH_FEE_MATERIAL_FIELDS_INVALID")
    return cast(dict[str, object], parsed)


def _parse_exact_attestation_bytes(value: object) -> dict[str, object]:
    if type(value) is not bytes or not value or len(value) > _MAX_FEE_ATTESTATION_BYTES:
        _validation("PAPER_RESEARCH_FEE_ATTESTATION_BYTES_INVALID")
    raw = value

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, item in pairs:
            if key in parsed:
                _validation("PAPER_RESEARCH_FEE_ATTESTATION_JSON_INVALID")
            parsed[key] = item
        return parsed

    def reject_constant(_value: str) -> NoReturn:
        _validation("PAPER_RESEARCH_FEE_ATTESTATION_JSON_INVALID")

    try:
        parsed = json.loads(
            raw.decode("ascii", errors="strict"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except PaperResearchCausalCostEvidenceV1Error:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeError, ValueError):
        _validation("PAPER_RESEARCH_FEE_ATTESTATION_JSON_INVALID")
    if type(parsed) is not dict or frozenset(parsed) != _FEE_ATTESTATION_FIELDS:
        _validation("PAPER_RESEARCH_FEE_ATTESTATION_FIELDS_INVALID")
    canonical = _canonical_bytes(
        parsed,
        reason="PAPER_RESEARCH_FEE_ATTESTATION_JSON_INVALID",
    )
    if len(canonical) > _MAX_FEE_ATTESTATION_BYTES or not hmac.compare_digest(
        canonical,
        raw,
    ):
        _validation("PAPER_RESEARCH_FEE_ATTESTATION_NOT_EXACT_CANONICAL_JSON")
    return cast(dict[str, object], parsed)


def _fee_attestation_unsigned_material(
    *,
    fee_material: dict[str, object],
    declared_trust_anchor_id: str,
    declared_public_key_sha256: str,
) -> dict[str, object]:
    material_sha256 = _sha256(fee_material)
    return {
        "schema_version": PAPER_RESEARCH_FEE_SCHEDULE_ATTESTATION_V1_SCHEMA_VERSION,
        "signature_algorithm": "Ed25519",
        "signature_domain": PAPER_RESEARCH_FEE_SCHEDULE_ATTESTATION_V1_DOMAIN,
        "declared_trust_anchor_id": declared_trust_anchor_id,
        "declared_public_key_sha256": declared_public_key_sha256,
        "fee_material_sha256": material_sha256,
        "fee_material": fee_material,
        "audit_only": True,
        **_AUTHORIZATION,
    }


def paper_research_fee_schedule_attestation_signing_bytes_v1(
    *,
    fee_schedule_material: object,
    declared_trust_anchor_id: object,
    declared_public_key_sha256: object,
) -> bytes:
    """Return domain-separated bytes for an offline configuration signer."""

    material = _strict_fee_material(fee_schedule_material)
    trust_anchor = _label(
        declared_trust_anchor_id,
        reason="PAPER_RESEARCH_FEE_TRUST_ANCHOR_ID_INVALID",
    )
    if not _valid_sha256(declared_public_key_sha256):
        _validation("PAPER_RESEARCH_FEE_PUBLIC_KEY_FINGERPRINT_INVALID")
    unsigned = _fee_attestation_unsigned_material(
        fee_material=material,
        declared_trust_anchor_id=trust_anchor,
        declared_public_key_sha256=cast(str, declared_public_key_sha256),
    )
    return PAPER_RESEARCH_FEE_SCHEDULE_ATTESTATION_V1_DOMAIN_SEPARATOR + _canonical_bytes(
        unsigned,
        reason="PAPER_RESEARCH_FEE_ATTESTATION_JSON_INVALID",
    )


def assemble_paper_research_fee_schedule_attestation_v1(
    *,
    fee_schedule_material: object,
    declared_trust_anchor_id: object,
    declared_public_key_sha256: object,
    signature_bytes: object,
) -> bytes:
    """Assemble canonical signed bytes without accepting or retaining a private key."""

    if type(signature_bytes) is not bytes or len(signature_bytes) != _ED25519_SIGNATURE_BYTES:
        _validation("PAPER_RESEARCH_FEE_ATTESTATION_SIGNATURE_INVALID")
    material = _strict_fee_material(fee_schedule_material)
    trust_anchor = _label(
        declared_trust_anchor_id,
        reason="PAPER_RESEARCH_FEE_TRUST_ANCHOR_ID_INVALID",
    )
    if not _valid_sha256(declared_public_key_sha256):
        _validation("PAPER_RESEARCH_FEE_PUBLIC_KEY_FINGERPRINT_INVALID")
    envelope = {
        **_fee_attestation_unsigned_material(
            fee_material=material,
            declared_trust_anchor_id=trust_anchor,
            declared_public_key_sha256=cast(str, declared_public_key_sha256),
        ),
        "signature_hex": signature_bytes.hex(),
    }
    encoded = _canonical_bytes(
        envelope,
        reason="PAPER_RESEARCH_FEE_ATTESTATION_JSON_INVALID",
    )
    if len(encoded) > _MAX_FEE_ATTESTATION_BYTES:
        _validation("PAPER_RESEARCH_FEE_ATTESTATION_BYTES_INVALID")
    return encoded


def _verify_fee_attestation(
    *,
    attestation_bytes: object,
    expected_material: dict[str, object],
    registry_public_key_bytes: object,
    registry_public_key_sha256: object,
    expected_trust_anchor_id: object,
) -> dict[str, object]:
    if (
        type(registry_public_key_bytes) is not bytes
        or len(registry_public_key_bytes) != _ED25519_PUBLIC_KEY_BYTES
    ):
        _validation("PAPER_RESEARCH_FEE_REGISTRY_PUBLIC_KEY_INVALID")
    public_key_bytes = registry_public_key_bytes
    if not _valid_sha256(registry_public_key_sha256):
        _validation("PAPER_RESEARCH_FEE_REGISTRY_PUBLIC_KEY_FINGERPRINT_INVALID")
    public_key_sha256 = hashlib.sha256(public_key_bytes).hexdigest()
    if not hmac.compare_digest(
        public_key_sha256,
        cast(str, registry_public_key_sha256),
    ):
        _integrity("PAPER_RESEARCH_FEE_REGISTRY_PUBLIC_KEY_FINGERPRINT_MISMATCH")
    trust_anchor = _label(
        expected_trust_anchor_id,
        reason="PAPER_RESEARCH_FEE_TRUST_ANCHOR_ID_INVALID",
    )
    parsed = _parse_exact_attestation_bytes(attestation_bytes)
    signature_hex = parsed.get("signature_hex")
    if type(signature_hex) is not str or _SIGNATURE_RE.fullmatch(signature_hex) is None:
        _validation("PAPER_RESEARCH_FEE_ATTESTATION_SIGNATURE_INVALID")
    unsigned = _fee_attestation_unsigned_material(
        fee_material=expected_material,
        declared_trust_anchor_id=trust_anchor,
        declared_public_key_sha256=public_key_sha256,
    )
    supplied_unsigned = {key: item for key, item in parsed.items() if key != "signature_hex"}
    if supplied_unsigned != unsigned:
        _integrity("PAPER_RESEARCH_FEE_ATTESTATION_EXPECTED_CONTEXT_MISMATCH")
    try:
        verifier = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        verifier.verify(
            bytes.fromhex(signature_hex),
            PAPER_RESEARCH_FEE_SCHEDULE_ATTESTATION_V1_DOMAIN_SEPARATOR
            + _canonical_bytes(
                unsigned,
                reason="PAPER_RESEARCH_FEE_ATTESTATION_JSON_INVALID",
            ),
        )
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise PaperResearchCausalCostEvidenceV1IntegrityError(
            "PAPER_RESEARCH_FEE_ATTESTATION_UNVERIFIED"
        ) from exc
    exact = cast(bytes, attestation_bytes)
    return {
        "attestation_sha256": hashlib.sha256(exact).hexdigest(),
        "fee_material_sha256": _sha256(expected_material),
        "fee_material_canonical_json": _canonical_bytes(
            expected_material,
            reason="PAPER_RESEARCH_FEE_MATERIAL_JSON_INVALID",
        ).decode("ascii"),
        "trust_anchor_id": trust_anchor,
        "registry_public_key_sha256": public_key_sha256,
        "cryptographic_signature_verified": True,
        "registry_trust_anchor_binding_verified": True,
        "expected_material_exact_match_verified": True,
        "audit_only": True,
        **_AUTHORIZATION,
    }


def _validate_fee_evidence(
    *,
    store: ImmutableSourcePayloadStore,
    source_document_bytes: object,
    signed_attestation: object,
    material: object,
    registry_public_key_bytes: object,
    registry_public_key_sha256: object,
    expected_trust_anchor_id: object,
    expected_source_revision: object,
    symbol: str,
    decision_at: datetime,
) -> tuple[
    float,
    dict[str, Any],
    dict[str, Any],
    tuple[tuple[SourcePayloadAddress, bytes], ...],
    str,
]:
    if (
        type(source_document_bytes) is not bytes
        or not source_document_bytes
        or len(source_document_bytes) > _MAX_SOURCE_DOCUMENT_BYTES
    ):
        _validation("PAPER_RESEARCH_FEE_SOURCE_DOCUMENT_BYTES_INVALID")
    source_bytes = source_document_bytes
    source_address = _put_exact(
        store,
        source_bytes,
        reason="PAPER_RESEARCH_FEE_SOURCE_DOCUMENT_CAS_FAILED",
    )
    fee_material = _strict_fee_material(material)
    if not _valid_sha256(expected_source_revision):
        _validation("PAPER_RESEARCH_FEE_EXPECTED_SOURCE_REVISION_INVALID")
    expected_literals: dict[str, object] = {
        "schema_version": PAPER_RESEARCH_FEE_SCHEDULE_MATERIAL_V1_SCHEMA_VERSION,
        "evidence_classification": (
            "SIGNED_OPERATOR_CONFIGURED_PUBLIC_FEE_SCHEDULE_NOT_ACCOUNT_COMMISSION"
        ),
        "venue": "BINANCE",
        "market": "USD_M_PERPETUAL",
        "symbol": symbol,
        "liquidity_role": "TAKER",
        "fee_semantics": "PER_SIDE_EXECUTION_FEE_NOT_ROUND_TRIP",
        "fee_unit": "BASIS_POINTS_DECIMAL_STRING",
        "authority_scope": PAPER_RESEARCH_FEE_AUTHORITY_SCOPE,
        "configuration_authenticity_scope": (PAPER_RESEARCH_FEE_CONFIGURATION_AUTHENTICITY_SCOPE),
        "account_specific_commission_authenticated": False,
        "upstream_exchange_signature_verified": False,
        "audit_only": True,
        **_AUTHORIZATION,
    }
    if any(
        type(fee_material.get(name)) is not type(expected) or fee_material.get(name) != expected
        for name, expected in expected_literals.items()
    ):
        _validation("PAPER_RESEARCH_FEE_MATERIAL_IDENTITY_OR_AUTHORITY_INVALID")
    if (
        type(fee_material.get("source_document_byte_count")) is not int
        or cast(int, fee_material["source_document_byte_count"]) <= 0
        or fee_material.get("source_document_sha256") != source_address.payload_sha256
        or fee_material.get("source_document_byte_count") != source_address.payload_byte_count
        or fee_material.get("source_revision") != source_address.payload_sha256
        or fee_material.get("source_revision") != expected_source_revision
    ):
        _validation("PAPER_RESEARCH_FEE_SOURCE_DOCUMENT_BINDING_INVALID")
    for name in ("source_document_sha256", "source_revision"):
        if not _valid_sha256(fee_material.get(name)):
            _validation(f"PAPER_RESEARCH_FEE_{name.upper()}_INVALID")
    _label(
        fee_material.get("source_document_media_type"),
        reason="PAPER_RESEARCH_FEE_SOURCE_DOCUMENT_MEDIA_TYPE_INVALID",
    )
    _label(
        fee_material.get("source_document_locator"),
        reason="PAPER_RESEARCH_FEE_SOURCE_DOCUMENT_LOCATOR_INVALID",
    )
    fee_decimal, fee_value = _fee_decimal(fee_material.get("taker_fee_bps_per_side_decimal"))
    observed_iso, observed_at = _clock(
        fee_material.get("source_observed_at"),
        reason="PAPER_RESEARCH_FEE_SOURCE_OBSERVED_AT_INVALID",
    )
    effective_iso, effective_at = _clock(
        fee_material.get("effective_at"),
        reason="PAPER_RESEARCH_FEE_EFFECTIVE_AT_INVALID",
    )
    available_iso, available_at = _clock(
        fee_material.get("available_at"),
        reason="PAPER_RESEARCH_FEE_AVAILABLE_AT_INVALID",
    )
    expires_iso, expires_at = _clock(
        fee_material.get("expires_at"),
        reason="PAPER_RESEARCH_FEE_EXPIRES_AT_INVALID",
    )
    if not max(observed_at, effective_at) <= available_at <= decision_at < expires_at:
        _validation("PAPER_RESEARCH_FEE_CLOCK_OR_EXPIRY_INVALID")
    trust_anchor = _label(
        expected_trust_anchor_id,
        reason="PAPER_RESEARCH_FEE_TRUST_ANCHOR_ID_INVALID",
    )
    verification = _verify_fee_attestation(
        attestation_bytes=signed_attestation,
        expected_material=fee_material,
        registry_public_key_bytes=registry_public_key_bytes,
        registry_public_key_sha256=registry_public_key_sha256,
        expected_trust_anchor_id=trust_anchor,
    )
    if (
        verification.get("cryptographic_signature_verified") is not True
        or verification.get("registry_trust_anchor_binding_verified") is not True
        or verification.get("expected_material_exact_match_verified") is not True
        or verification.get("audit_only") is not True
        or any(verification.get(name) is not False for name in _AUTHORIZATION)
    ):
        _integrity("PAPER_RESEARCH_FEE_ATTESTATION_VERIFICATION_CONTRACT_INVALID")
    attestation_bytes = cast(bytes, signed_attestation)
    attestation_address = _put_exact(
        store,
        attestation_bytes,
        reason="PAPER_RESEARCH_FEE_ATTESTATION_CAS_FAILED",
    )
    receipt_material = {
        "schema_version": PAPER_RESEARCH_FEE_SCHEDULE_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "SIGNED_CONFIGURED_PUBLIC_FEE_SCHEDULE_READ",
        "source_role": "signed_configured_public_fee_schedule",
        "source_document_sha256": source_address.payload_sha256,
        "source_document_byte_count": source_address.payload_byte_count,
        "source_document_cas_address": _address_mapping(source_address),
        "signed_attestation_sha256": attestation_address.payload_sha256,
        "signed_attestation_byte_count": attestation_address.payload_byte_count,
        "signed_attestation_cas_address": _address_mapping(attestation_address),
        "attested_material_sha256": verification["fee_material_sha256"],
        "trust_anchor_id": trust_anchor,
        "registry_public_key_sha256": registry_public_key_sha256,
        "independently_expected_source_revision": expected_source_revision,
        "symbol": symbol,
        "effective_at": effective_iso,
        "source_observed_at": observed_iso,
        "available_at": available_iso,
        "expires_at": expires_iso,
        "authority_scope": PAPER_RESEARCH_FEE_AUTHORITY_SCOPE,
        "configuration_authenticity_verified": True,
        "account_specific_commission_authenticated": False,
        "upstream_exchange_signature_verified": False,
        **_AUTHORIZATION,
    }
    receipt = {**receipt_material, "receipt_sha256": _sha256(receipt_material)}
    receipt_bytes = _canonical_bytes(
        receipt,
        reason="PAPER_RESEARCH_FEE_RECEIPT_JSON_INVALID",
    )
    receipt_address = _put_exact(
        store,
        receipt_bytes,
        reason="PAPER_RESEARCH_FEE_RECEIPT_CAS_FAILED",
    )
    source = {
        "source_key": f"paper-research:configured-public-fee-schedule:{symbol}",
        "source_schema_version": PAPER_RESEARCH_FEE_SCHEDULE_MATERIAL_V1_SCHEMA_VERSION,
        "source_transport": "DETACHED_ED25519_SIGNED_CONFIGURATION_AND_EXACT_SOURCE_BYTES",
        "capture_classification": expected_literals["evidence_classification"],
        "artifact_payload_sha256": attestation_address.payload_sha256,
        "artifact_payload_byte_count": attestation_address.payload_byte_count,
        "artifact_cas_address": _address_mapping(attestation_address),
        "source_document_sha256": source_address.payload_sha256,
        "source_document_byte_count": source_address.payload_byte_count,
        "source_document_cas_address": _address_mapping(source_address),
        "input_receipt_sha256": receipt["receipt_sha256"],
        "input_receipt_cas_address": _address_mapping(receipt_address),
        "attested_material_sha256": verification["fee_material_sha256"],
        "trust_anchor_id": trust_anchor,
        "registry_public_key_sha256": registry_public_key_sha256,
        "independently_expected_source_revision": expected_source_revision,
        "effective_at": effective_iso,
        "source_observed_at": observed_iso,
        "available_at": available_iso,
        "expires_at": expires_iso,
        "fee_semantics": expected_literals["fee_semantics"],
        "fee_unit": "BASIS_POINTS",
        "taker_fee_bps_per_side_decimal": fee_decimal,
        "configuration_authenticity_verified": True,
        "account_specific_commission_authenticated": False,
        "upstream_exchange_signature_verified": False,
        "external_monotonic_source_revision_verified": False,
        "fallback_used": False,
    }
    return (
        fee_value,
        source,
        receipt,
        (
            (source_address, source_bytes),
            (attestation_address, attestation_bytes),
            (receipt_address, receipt_bytes),
        ),
        cast(str, verification["fee_material_canonical_json"]),
    )


def _float32(value: object, *, reason: str) -> tuple[float, str]:
    if type(value) not in {int, float}:
        _validation(reason)
    parsed = float(cast(int | float, value))
    try:
        packed = struct.pack("!f", parsed)
        resolved = float(struct.unpack("!f", packed)[0])
    except (OverflowError, struct.error):
        _validation(reason)
    if not math.isfinite(parsed) or not math.isfinite(resolved):
        _validation(reason)
    if parsed != 0.0 and resolved == 0.0:
        _validation(reason)
    return (0.0 if resolved == 0.0 else resolved), packed.hex()


def _research_composite_receipt(
    *,
    feature_name: str,
    value: float,
    value_hex: str,
    configuration: Mapping[str, Any],
    child_bindings: Sequence[Mapping[str, Any]],
    exact_bindings: Mapping[str, Any],
    derivation: Mapping[str, Any],
    module_code_sha256: str,
    shared_causal_module_code_sha256: str,
) -> dict[str, Any]:
    configuration_material = {
        "schema_version": "paper_research_cost_scalar_configuration_v1",
        "global_implementation_sha256": (
            PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
        ),
        **dict(configuration),
    }
    configuration_sha256 = _sha256(configuration_material)
    transform_contract = {
        "schema_version": "paper_research_cost_scalar_transform_contract_v1",
        "implementation_id": PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
        "implementation_sha256": (PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256),
        "module_code_sha256": module_code_sha256,
        "shared_causal_market_notional_dependency_sha256": (
            CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
        ),
        "shared_causal_market_notional_module_code_sha256": (shared_causal_module_code_sha256),
        "configuration_sha256": configuration_sha256,
        "configuration": configuration_material,
    }
    transform_sha256 = _sha256(transform_contract)
    scalar_bytes = bytes.fromhex(value_hex)
    material = {
        "schema_version": (PAPER_RESEARCH_CAUSAL_COST_COMPOSITE_RECEIPT_V1_SCHEMA_VERSION),
        "receipt_kind": "COMPOSITE_DERIVATION",
        "feature_name": feature_name,
        "feature_role": "RESEARCH_LABEL_ONLY_AUXILIARY_NOT_MODEL_INPUT",
        "payload_type": "IEEE754_BINARY32_SCALAR",
        "payload_sha256": hashlib.sha256(scalar_bytes).hexdigest(),
        "payload_byte_count": len(scalar_bytes),
        "value_float32_be_hex": value_hex,
        "value": value,
        "value_unit": "BASIS_POINTS",
        "child_read_bindings": [dict(item) for item in child_bindings],
        "derivation_material": {
            "schema_version": "paper_research_cost_derivation_material_v1",
            "producer_id": "paper_research_causal_cost_evidence_v1",
            "implementation_id": (PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID),
            "implementation_sha256": (PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256),
            "module_code_sha256": module_code_sha256,
            "configuration_sha256": configuration_sha256,
            "transform_sha256": transform_sha256,
            "exact_rederivation": dict(derivation),
        },
        "exact_bindings": dict(exact_bindings),
        "authorization": dict(_AUTHORIZATION),
    }
    return {**material, "receipt_sha256": _sha256(material)}


@dataclass(frozen=True, slots=True)
class PaperResearchCausalCostEvidenceV1Result:
    """Factory-built research artifact; every property reopens CAS and signature."""

    artifact_sha256: str
    artifact_json: str = field(repr=False)
    artifact_address: SourcePayloadAddress
    ordered_values: tuple[float, float, float, float]
    ordered_receipt_sha256s: tuple[str, str, str, str]
    _store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _exact_objects: tuple[tuple[SourcePayloadAddress, bytes], ...] = field(
        repr=False,
        compare=False,
    )
    _fee_attestation_bytes: bytes = field(repr=False, compare=False)
    _fee_material_json: str = field(repr=False, compare=False)
    _registry_public_key_bytes: bytes = field(repr=False, compare=False)
    _registry_public_key_sha256: str = field(repr=False, compare=False)
    _expected_trust_anchor_id: str = field(repr=False, compare=False)
    _expected_fee_source_revision: str = field(repr=False, compare=False)
    _notional_policy_token: CausalExpectedNotionalPolicyTokenV1 = field(
        repr=False,
        compare=False,
    )
    _construction_token: object = field(repr=False, compare=False)

    @property
    def contract(self) -> dict[str, Any]:
        return _validated_result(self)

    @property
    def ordered_receipts(self) -> tuple[dict[str, Any], ...]:
        contract = _validated_result(self)
        return tuple(cast(dict[str, Any], item) for item in contract["ordered_receipts"])


def build_paper_research_causal_cost_evidence_v1(
    *,
    atomic_capture: object,
    source_payload_store: object,
    fee_schedule_source_document_bytes: object,
    fee_schedule_signed_attestation: object,
    fee_schedule_material: object,
    fee_schedule_registry_public_key_bytes: object,
    fee_schedule_registry_public_key_sha256: object,
    fee_schedule_expected_trust_anchor_id: object,
    fee_schedule_expected_source_revision: object,
    expected_notional_policy: object,
    symbol: object,
    feature_snapshot_identity: object,
    decision_time: object,
    counterfactual_holding_horizon_seconds: object,
) -> PaperResearchCausalCostEvidenceV1Result:
    """Build four research-only cost scalars from complete causal evidence."""

    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _validation("PAPER_RESEARCH_COST_IMMUTABLE_SOURCE_PAYLOAD_STORE_REQUIRED")
    store = source_payload_store
    normalized_symbol = _label(
        symbol,
        reason="PAPER_RESEARCH_COST_SYMBOL_INVALID",
        pattern=_SYMBOL_RE,
    )
    snapshot_identity = _label(
        feature_snapshot_identity,
        reason="PAPER_RESEARCH_COST_FEATURE_SNAPSHOT_IDENTITY_INVALID",
    )
    decision_iso, decision_at = _clock(
        decision_time,
        reason="PAPER_RESEARCH_COST_DECISION_TIME_INVALID",
    )
    if (
        type(counterfactual_holding_horizon_seconds) is not int
        or counterfactual_holding_horizon_seconds != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
    ):
        _validation("PAPER_RESEARCH_COST_COUNTERFACTUAL_HORIZON_NOT_PINNED_900_SECONDS")
    if type(expected_notional_policy) is not CausalExpectedNotionalPolicyTokenV1:
        _validation("PAPER_RESEARCH_COST_CAUSAL_NOTIONAL_FACTORY_TOKEN_REQUIRED")
    notional_token = expected_notional_policy
    try:
        notional_contract = notional_token.contract
    except CausalExpectedNotionalPolicyV1IntegrityError as exc:
        raise PaperResearchCausalCostEvidenceV1IntegrityError(
            f"PAPER_RESEARCH_CAUSAL_NOTIONAL_TOKEN_INTEGRITY_INVALID:{exc.reason}"
        ) from exc
    except CausalExpectedNotionalPolicyV1Error as exc:
        raise PaperResearchCausalCostEvidenceV1ValidationError(
            f"PAPER_RESEARCH_CAUSAL_NOTIONAL_TOKEN_INVALID:{exc.reason}"
        ) from exc
    if (
        notional_token.symbol != normalized_symbol
        or notional_token.feature_snapshot_identity != snapshot_identity
        or notional_token.decision_time != decision_iso
        or notional_contract.get("read_only") is not True
        or notional_contract.get("fallback_used") is not False
        or notional_contract.get("static_default_used") is not False
        or any(
            notional_contract.get(name) is not False
            for name in (
                "trainer_authority",
                "prediction_authority",
                "paper_authority",
                "live_authority",
                "order_authority",
            )
        )
    ):
        _validation("PAPER_RESEARCH_COST_CAUSAL_NOTIONAL_TOKEN_SCOPE_INVALID")
    notional = notional_token.expected_notional_usd
    if not math.isfinite(notional) or notional <= 0.0:
        _validation("PAPER_RESEARCH_COST_EXPECTED_NOTIONAL_INVALID")
    try:
        payloads, market_sources, market_objects = _causal._validated_atomic_sources(  # noqa: SLF001
            atomic_capture=atomic_capture,
            store=store,
            symbol=normalized_symbol,
            decision_at=decision_at,
        )
        notional_source, notional_receipt, notional_objects = _causal._validate_notional_evidence(  # noqa: SLF001
            store=store,
            artifact_bytes=notional_token.notional_artifact_bytes,
            receipt=notional_token.notional_receipt,
            expected_notional_usd=notional,
            symbol=normalized_symbol,
            feature_snapshot_identity=snapshot_identity,
            decision_at=decision_at,
        )
        spread_value, impact_value, orderbook_derivation = _causal._validate_orderbook_sources(  # noqa: SLF001
            depth=payloads["orderbook_depth"],
            features=payloads["orderbook_features"],
            evidence=market_sources,
            symbol=normalized_symbol,
            decision_at=decision_at,
            expected_notional_usd=notional,
        )
        funding_value, funding_derivation = _causal._validate_mark_source(  # noqa: SLF001
            mark=payloads["mark_price"],
            evidence=market_sources,
            symbol=normalized_symbol,
            decision_at=decision_at,
        )
    except CausalCostEvidenceV1IntegrityError as exc:
        raise PaperResearchCausalCostEvidenceV1IntegrityError(
            f"PAPER_RESEARCH_SHARED_CAUSAL_INTEGRITY_INVALID:{exc.reason}"
        ) from exc
    except CausalCostEvidenceV1Error as exc:
        raise PaperResearchCausalCostEvidenceV1ValidationError(
            f"PAPER_RESEARCH_SHARED_CAUSAL_INPUT_INVALID:{exc.reason}"
        ) from exc

    notional_raw_status_address = _put_exact(
        store,
        notional_token.raw_status_bytes,
        reason="PAPER_RESEARCH_COST_NOTIONAL_RAW_STATUS_CAS_FAILED",
    )
    notional_source_receipt_address = _put_exact(
        store,
        notional_token.source_read_receipt_bytes,
        reason="PAPER_RESEARCH_COST_NOTIONAL_SOURCE_RECEIPT_CAS_FAILED",
    )
    notional_source.update(
        {
            "factory_token_schema_version": notional_token.schema_version,
            "factory_token_policy_version": notional_token.policy_version,
            "factory_token_source_read_receipt_sha256": (notional_token.source_read_receipt_sha256),
            "factory_token_source_read_receipt_cas_address": _address_mapping(
                notional_source_receipt_address
            ),
            "factory_token_raw_status_sha256": (notional_raw_status_address.payload_sha256),
            "factory_token_raw_status_cas_address": _address_mapping(notional_raw_status_address),
            "factory_token_reauthenticated": True,
        }
    )

    (
        fee_value,
        fee_source,
        fee_receipt,
        fee_objects,
        fee_material_json,
    ) = _validate_fee_evidence(
        store=store,
        source_document_bytes=fee_schedule_source_document_bytes,
        signed_attestation=fee_schedule_signed_attestation,
        material=fee_schedule_material,
        registry_public_key_bytes=fee_schedule_registry_public_key_bytes,
        registry_public_key_sha256=fee_schedule_registry_public_key_sha256,
        expected_trust_anchor_id=fee_schedule_expected_trust_anchor_id,
        expected_source_revision=fee_schedule_expected_source_revision,
        symbol=normalized_symbol,
        decision_at=decision_at,
    )

    source_receipts = {
        role: _causal._market_source_receipt(  # noqa: SLF001
            role=role,
            source=market_sources[role],
            symbol=normalized_symbol,
            feature_snapshot_identity=snapshot_identity,
            decision_time=decision_iso,
        )
        for role in ("orderbook_depth", "orderbook_features", "mark_price")
    }
    source_receipt_objects: list[tuple[SourcePayloadAddress, bytes]] = []
    for role, receipt_value in source_receipts.items():
        receipt_bytes = _canonical_bytes(
            receipt_value,
            reason="PAPER_RESEARCH_COST_MARKET_RECEIPT_JSON_INVALID",
        )
        receipt_address = _put_exact(
            store,
            receipt_bytes,
            reason=f"PAPER_RESEARCH_COST_{role.upper()}_RECEIPT_CAS_FAILED",
        )
        market_sources[role]["direct_read_receipt_sha256"] = receipt_value["receipt_sha256"]
        market_sources[role]["direct_read_receipt_cas_address"] = _address_mapping(receipt_address)
        source_receipt_objects.append((receipt_address, receipt_bytes))

    exact_bindings = {
        "symbol": normalized_symbol,
        "feature_snapshot_identity": snapshot_identity,
        "feature_snapshot_identity_sha256": hashlib.sha256(
            snapshot_identity.encode("ascii")
        ).hexdigest(),
        "decision_time": decision_iso,
        "counterfactual_holding_horizon_seconds": (CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS),
        "expected_notional_usd": notional,
        "expected_notional_float64_hex": notional.hex(),
        "notional_policy_receipt_sha256": notional_receipt["receipt_sha256"],
        "configured_public_fee_schedule_receipt_sha256": fee_receipt["receipt_sha256"],
        "configured_public_fee_attested_material_sha256": fee_source["attested_material_sha256"],
        "configured_public_fee_registry_public_key_sha256": fee_source[
            "registry_public_key_sha256"
        ],
        "configured_public_fee_expected_source_revision": fee_source[
            "independently_expected_source_revision"
        ],
        "atomic_batch_id": cast(AtomicRedisSourceReadBatch, atomic_capture).batch_id,
        "atomic_batch_material_sha256": cast(
            AtomicRedisSourceReadBatch, atomic_capture
        ).batch_material_sha256,
        "profiled_39_record_id": None,
        "research_training_record_id": None,
    }
    module_sha256 = _module_code_sha256()
    try:
        shared_causal_module_sha256 = _causal._module_code_sha256()  # noqa: SLF001
    except CausalCostEvidenceV1Error as exc:
        raise PaperResearchCausalCostEvidenceV1IntegrityError(
            "PAPER_RESEARCH_SHARED_CAUSAL_IMPLEMENTATION_BYTES_UNAVAILABLE"
        ) from exc
    specs = (
        (
            "fee_bps",
            fee_value,
            {
                "component_semantics": "CONFIGURED_PUBLIC_TAKER_FEE_BPS_PER_SIDE",
                "formula": "SIGNED_DECIMAL_STRING_TAKER_FEE_BPS_PER_SIDE",
                "required_child_roles": ["signed_configured_public_fee_schedule"],
                "account_specific_commission_authenticated": False,
            },
            (
                {
                    "input_role": "signed_configured_public_fee_schedule",
                    "receipt_sha256": fee_receipt["receipt_sha256"],
                },
            ),
            {
                "taker_fee_bps_per_side_decimal": fee_source["taker_fee_bps_per_side_decimal"],
                "fee_bps_per_side_float64_hex": fee_value.hex(),
                "configuration_authenticity_verified": True,
                "account_specific_commission_authenticated": False,
                "fallback_used": False,
            },
        ),
        (
            "spread_bps",
            spread_value,
            {
                "component_semantics": "FULL_BID_ASK_SPREAD_ONE_ROUND_TRIP_CROSS",
                "formula": "(BEST_ASK-BEST_BID)/MID*10000",
                "required_child_roles": ["orderbook_depth", "orderbook_features"],
            },
            tuple(
                {
                    "input_role": role,
                    "receipt_sha256": source_receipts[role]["receipt_sha256"],
                }
                for role in ("orderbook_depth", "orderbook_features")
            ),
            orderbook_derivation,
        ),
        (
            "expected_slippage_bps",
            impact_value,
            {
                "component_semantics": "EXPECTED_ADVERSE_IMPACT_BPS_PER_SIDE",
                "formula": "MAX_BUY_SELL_RAW_DEPTH_VWAP_IMPACT_AT_EXACT_NOTIONAL",
                "required_child_roles": [
                    "orderbook_depth",
                    "orderbook_features",
                    "expected_notional_policy",
                ],
            },
            (
                *tuple(
                    {
                        "input_role": role,
                        "receipt_sha256": source_receipts[role]["receipt_sha256"],
                    }
                    for role in ("orderbook_depth", "orderbook_features")
                ),
                {
                    "input_role": "expected_notional_policy",
                    "receipt_sha256": notional_receipt["receipt_sha256"],
                },
            ),
            orderbook_derivation,
        ),
        (
            "expected_funding_bps",
            funding_value,
            {
                "component_semantics": "SIGNED_VENUE_RATE_OVER_PINNED_HORIZON",
                "formula": _IMPLEMENTATION_CONTRACT["funding_formula"],
                "required_child_roles": ["mark_price"],
            },
            (
                {
                    "input_role": "mark_price",
                    "receipt_sha256": source_receipts["mark_price"]["receipt_sha256"],
                },
            ),
            funding_derivation,
        ),
    )
    values: list[float] = []
    receipts: list[dict[str, Any]] = []
    for feature_name, raw_value, configuration, children, derivation in specs:
        value, value_hex = _float32(
            raw_value,
            reason=f"PAPER_RESEARCH_COST_{feature_name.upper()}_FLOAT32_INVALID",
        )
        values.append(value)
        receipts.append(
            _research_composite_receipt(
                feature_name=feature_name,
                value=value,
                value_hex=value_hex,
                configuration=configuration,
                child_bindings=children,
                exact_bindings=exact_bindings,
                derivation=derivation,
                module_code_sha256=module_sha256,
                shared_causal_module_code_sha256=shared_causal_module_sha256,
            )
        )

    source_exact_objects = (
        *market_objects,
        *notional_objects,
        (notional_raw_status_address, notional_token.raw_status_bytes),
        (
            notional_source_receipt_address,
            notional_token.source_read_receipt_bytes,
        ),
        *fee_objects,
        *source_receipt_objects,
    )
    source_cas_object_inventory = [
        _address_mapping(address) for address, _payload in source_exact_objects
    ]
    contract_material = {
        "schema_version": PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION,
        "evidence_classification": (PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION),
        "downstream_status": PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS,
        "implementation_id": PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
        "implementation_sha256": (PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256),
        "shared_causal_market_notional_dependency_sha256": (
            CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
        ),
        "shared_causal_market_notional_module_code_sha256": (shared_causal_module_sha256),
        "module_code_sha256": module_sha256,
        "symbol": normalized_symbol,
        "feature_snapshot_identity": snapshot_identity,
        "decision_time": decision_iso,
        "counterfactual_holding_horizon_seconds": (CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS),
        "ordered_feature_names": list(CAUSAL_COST_ORDERED_FEATURE_NAMES),
        "ordered_values": values,
        "ordered_receipt_sha256s": [item["receipt_sha256"] for item in receipts],
        "ordered_receipts": receipts,
        "market_sources": market_sources,
        "market_source_read_receipts": source_receipts,
        "fee_source": fee_source,
        "fee_schedule_receipt": fee_receipt,
        "notional_source": notional_source,
        "funding_settlement_contract": funding_derivation,
        "fee_source_authenticity_status": (
            "CONFIGURATION_SIGNATURE_VERIFIED_ACCOUNT_AND_EXCHANGE_AUTHORITY_NOT_CLAIMED"
        ),
        "market_source_authenticity_status": (
            "RECORDER_KEY_SCHEMA_TRANSPORT_SEMANTICS_REDERIVED_NO_UPSTREAM_SIGNATURE"
        ),
        "account_specific_commission_authenticated": False,
        "external_monotonic_fee_revision_verified": False,
        "profiled_account_lane_compatible": False,
        "research_cost_components_complete": True,
        "source_cas_object_count": len(source_cas_object_inventory),
        "source_cas_object_inventory": source_cas_object_inventory,
        "source_cas_object_inventory_sha256": _sha256(source_cas_object_inventory),
        "research_training_admission_status": (
            "NOT_AUTHORIZED_SEPARATE_LEDGER_MANIFEST_WITNESS_AND_ADMISSION_REQUIRED"
        ),
        "no_static_fallback_or_floor": True,
        "optional_provider_dependencies": [],
        "authorization": dict(_AUTHORIZATION),
    }
    contract_material_sha256 = _sha256(contract_material)
    contract = {
        **contract_material,
        "evidence_id": f"paper_research_causal_cost_evidence_v1_{contract_material_sha256}",
        "contract_material_sha256": contract_material_sha256,
    }
    artifact_bytes = _canonical_bytes(
        contract,
        reason="PAPER_RESEARCH_COST_ARTIFACT_JSON_INVALID",
    )
    artifact_address = _put_exact(
        store,
        artifact_bytes,
        reason="PAPER_RESEARCH_COST_ARTIFACT_CAS_FAILED",
    )
    result = PaperResearchCausalCostEvidenceV1Result(
        artifact_sha256=artifact_address.payload_sha256,
        artifact_json=artifact_bytes.decode("ascii"),
        artifact_address=artifact_address,
        ordered_values=cast(tuple[float, float, float, float], tuple(values)),
        ordered_receipt_sha256s=cast(
            tuple[str, str, str, str],
            tuple(item["receipt_sha256"] for item in receipts),
        ),
        _store=store,
        _exact_objects=(*source_exact_objects, (artifact_address, artifact_bytes)),
        _fee_attestation_bytes=cast(bytes, fee_schedule_signed_attestation),
        _fee_material_json=fee_material_json,
        _registry_public_key_bytes=cast(bytes, fee_schedule_registry_public_key_bytes),
        _registry_public_key_sha256=cast(str, fee_schedule_registry_public_key_sha256),
        _expected_trust_anchor_id=cast(str, fee_schedule_expected_trust_anchor_id),
        _expected_fee_source_revision=cast(
            str,
            fee_schedule_expected_source_revision,
        ),
        _notional_policy_token=notional_token,
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    _validated_result(result)
    return result


def _validated_result(
    result: PaperResearchCausalCostEvidenceV1Result,
) -> dict[str, Any]:
    if (
        type(result) is not PaperResearchCausalCostEvidenceV1Result
        or result._construction_token is not _CONSTRUCTION_TOKEN
        or type(result._store) is not ImmutableSourcePayloadStore
        or type(result._notional_policy_token) is not CausalExpectedNotionalPolicyTokenV1
        or type(result._exact_objects) is not tuple
        or not result._exact_objects
    ):
        _integrity("PAPER_RESEARCH_COST_RESULT_FACTORY_CONSTRUCTION_REQUIRED")
    for address, payload in result._exact_objects:
        if type(address) is not SourcePayloadAddress or type(payload) is not bytes:
            _integrity("PAPER_RESEARCH_COST_RESULT_CAS_OBJECT_BINDING_INVALID")
        if address.payload_sha256 != hashlib.sha256(
            payload
        ).hexdigest() or address.payload_byte_count != len(payload):
            _integrity("PAPER_RESEARCH_COST_RESULT_CAS_OBJECT_BINDING_INVALID")
        try:
            readback = result._store.get(
                address.payload_sha256,
                expected_byte_count=address.payload_byte_count,
            )
        except SourcePayloadStoreError as exc:
            raise PaperResearchCausalCostEvidenceV1IntegrityError(
                "PAPER_RESEARCH_COST_RESULT_CAS_READBACK_FAILED"
            ) from exc
        if not hmac.compare_digest(readback, payload):
            _integrity("PAPER_RESEARCH_COST_RESULT_CAS_READBACK_MISMATCH")
    try:
        notional_contract = result._notional_policy_token.contract
    except CausalExpectedNotionalPolicyV1Error as exc:
        raise PaperResearchCausalCostEvidenceV1IntegrityError(
            "PAPER_RESEARCH_COST_RESULT_NOTIONAL_TOKEN_REVERIFICATION_FAILED"
        ) from exc
    if (
        notional_contract.get("read_only") is not True
        or notional_contract.get("fallback_used") is not False
        or notional_contract.get("static_default_used") is not False
        or any(
            notional_contract.get(name) is not False
            for name in (
                "trainer_authority",
                "prediction_authority",
                "paper_authority",
                "live_authority",
                "order_authority",
            )
        )
    ):
        _integrity("PAPER_RESEARCH_COST_RESULT_NOTIONAL_TOKEN_AUTHORITY_INVALID")
    try:
        fee_material = json.loads(result._fee_material_json)
        if (
            not _valid_sha256(result._expected_fee_source_revision)
            or fee_material.get("source_revision") != result._expected_fee_source_revision
        ):
            _integrity("PAPER_RESEARCH_COST_RESULT_FEE_SOURCE_REVISION_MISMATCH")
        _verify_fee_attestation(
            attestation_bytes=result._fee_attestation_bytes,
            expected_material=fee_material,
            registry_public_key_bytes=result._registry_public_key_bytes,
            registry_public_key_sha256=result._registry_public_key_sha256,
            expected_trust_anchor_id=result._expected_trust_anchor_id,
        )
    except (
        json.JSONDecodeError,
        PaperResearchCausalCostEvidenceV1Error,
        TypeError,
        ValueError,
    ) as exc:
        raise PaperResearchCausalCostEvidenceV1IntegrityError(
            "PAPER_RESEARCH_COST_RESULT_FEE_ATTESTATION_REVERIFICATION_FAILED"
        ) from exc
    try:
        artifact_bytes = result.artifact_json.encode("ascii", errors="strict")
        contract = json.loads(artifact_bytes)
    except (UnicodeEncodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PaperResearchCausalCostEvidenceV1IntegrityError(
            "PAPER_RESEARCH_COST_RESULT_ARTIFACT_JSON_INVALID"
        ) from exc
    if type(contract) is not dict:
        _integrity("PAPER_RESEARCH_COST_RESULT_ARTIFACT_JSON_INVALID")
    if not hmac.compare_digest(
        _canonical_bytes(
            contract,
            reason="PAPER_RESEARCH_COST_RESULT_ARTIFACT_JSON_INVALID",
        ),
        artifact_bytes,
    ):
        _integrity("PAPER_RESEARCH_COST_RESULT_ARTIFACT_NOT_EXACT_CANONICAL_JSON")
    try:
        shared_causal_module_sha256 = _causal._module_code_sha256()  # noqa: SLF001
    except CausalCostEvidenceV1Error as exc:
        raise PaperResearchCausalCostEvidenceV1IntegrityError(
            "PAPER_RESEARCH_COST_RESULT_SHARED_CAUSAL_IMPLEMENTATION_UNAVAILABLE"
        ) from exc
    material = {
        key: value
        for key, value in cast(dict[str, Any], contract).items()
        if key not in {"evidence_id", "contract_material_sha256"}
    }
    material_sha256 = _sha256(material)
    source_inventory = contract.get("source_cas_object_inventory")
    if (
        type(source_inventory) is not list
        or not source_inventory
        or contract.get("source_cas_object_count") != len(source_inventory)
        or contract.get("source_cas_object_inventory_sha256") != _sha256(source_inventory)
        or any(not _valid_address_mapping(binding) for binding in source_inventory)
    ):
        _integrity("PAPER_RESEARCH_COST_RESULT_CAS_INVENTORY_INVALID")
    retained_source_objects = result._exact_objects[:-1]
    retained_artifact_object = result._exact_objects[-1]
    if (
        [_address_mapping(address) for address, _payload in retained_source_objects]
        != source_inventory
        or retained_artifact_object[0] != result.artifact_address
        or not hmac.compare_digest(retained_artifact_object[1], artifact_bytes)
    ):
        _integrity("PAPER_RESEARCH_COST_RESULT_CAS_INVENTORY_MISMATCH")
    if (
        hashlib.sha256(artifact_bytes).hexdigest() != result.artifact_sha256
        or result.artifact_address.payload_sha256 != result.artifact_sha256
        or result.artifact_address.payload_byte_count != len(artifact_bytes)
        or contract.get("contract_material_sha256") != material_sha256
        or contract.get("evidence_id")
        != f"paper_research_causal_cost_evidence_v1_{material_sha256}"
        or contract.get("implementation_sha256")
        != PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
        or contract.get("module_code_sha256") != _module_code_sha256()
        or contract.get("shared_causal_market_notional_module_code_sha256")
        != shared_causal_module_sha256
        or contract.get("ordered_feature_names") != list(CAUSAL_COST_ORDERED_FEATURE_NAMES)
        or tuple(contract.get("ordered_values") or ()) != result.ordered_values
        or tuple(contract.get("ordered_receipt_sha256s") or ()) != result.ordered_receipt_sha256s
        or contract.get("account_specific_commission_authenticated") is not False
        or contract.get("external_monotonic_fee_revision_verified") is not False
        or contract.get("profiled_account_lane_compatible") is not False
        or contract.get("authorization") != _AUTHORIZATION
    ):
        _integrity("PAPER_RESEARCH_COST_RESULT_CONTRACT_BINDING_INVALID")
    receipts = contract.get("ordered_receipts")
    if type(receipts) is not list or len(receipts) != 4:
        _integrity("PAPER_RESEARCH_COST_RESULT_RECEIPT_INVENTORY_INVALID")
    for index, receipt_value in enumerate(cast(list[object], receipts)):
        if type(receipt_value) is not dict:
            _integrity("PAPER_RESEARCH_COST_RESULT_RECEIPT_INVALID")
        receipt = cast(dict[str, Any], receipt_value)
        supplied = receipt.get("receipt_sha256")
        receipt_material = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        if (
            supplied != _sha256(receipt_material)
            or supplied != result.ordered_receipt_sha256s[index]
            or receipt.get("schema_version")
            != PAPER_RESEARCH_CAUSAL_COST_COMPOSITE_RECEIPT_V1_SCHEMA_VERSION
            or receipt.get("feature_name") != CAUSAL_COST_ORDERED_FEATURE_NAMES[index]
            or receipt.get("value") != result.ordered_values[index]
            or receipt.get("authorization") != _AUTHORIZATION
        ):
            _integrity("PAPER_RESEARCH_COST_RESULT_RECEIPT_BINDING_INVALID")
    return cast(dict[str, Any], contract)


__all__ = [
    "PAPER_RESEARCH_CAUSAL_COST_COMPOSITE_RECEIPT_V1_SCHEMA_VERSION",
    "PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION",
    "PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS",
    "PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID",
    "PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256",
    "PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION",
    "PAPER_RESEARCH_FEE_AUTHORITY_SCOPE",
    "PAPER_RESEARCH_FEE_CONFIGURATION_AUTHENTICITY_SCOPE",
    "PAPER_RESEARCH_FEE_SCHEDULE_ATTESTATION_V1_DOMAIN",
    "PAPER_RESEARCH_FEE_SCHEDULE_ATTESTATION_V1_DOMAIN_SEPARATOR",
    "PAPER_RESEARCH_FEE_SCHEDULE_ATTESTATION_V1_SCHEMA_VERSION",
    "PAPER_RESEARCH_FEE_SCHEDULE_MATERIAL_V1_SCHEMA_VERSION",
    "PAPER_RESEARCH_FEE_SCHEDULE_RECEIPT_V1_SCHEMA_VERSION",
    "PaperResearchCausalCostEvidenceV1Error",
    "PaperResearchCausalCostEvidenceV1IntegrityError",
    "PaperResearchCausalCostEvidenceV1Result",
    "PaperResearchCausalCostEvidenceV1ValidationError",
    "assemble_paper_research_fee_schedule_attestation_v1",
    "build_paper_research_causal_cost_evidence_v1",
    "paper_research_fee_schedule_attestation_signing_bytes_v1",
]
