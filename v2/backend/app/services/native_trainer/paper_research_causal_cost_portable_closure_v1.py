"""Restart-safe, authority-free closure for paper/research causal cost evidence.

The original cost factory intentionally retains process-sealed objects.  This
module publishes the complete immutable source inventory, the cost artifact,
the configured-fee Ed25519 public key, and a hash-bound notional-policy proof
into one portable CAS closure.  A fresh process can reopen the closure and
rederive every cost scalar without Redis, an exchange, or the original factory
objects.

The closure is research evidence only.  It grants no trainer, calibration,
prediction, serving, PAPER, live, exchange, order, execution, deployment, or
runtime authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer import causal_cost_evidence_v1 as _causal
from v2.backend.app.services.native_trainer import (
    causal_expected_notional_policy_v1 as _notional,
)
from v2.backend.app.services.native_trainer import (
    paper_research_causal_cost_evidence_v1 as _paper,
)
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    MAX_SOURCE_PAYLOAD_BYTES,
)
from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
    CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256,
    CAUSAL_COST_ORDERED_FEATURE_NAMES,
    CausalCostEvidenceV1Error,
)
from v2.backend.app.services.native_trainer.causal_expected_notional_policy_v1 import (
    CAUSAL_EXPECTED_NOTIONAL_CLASSIFICATION,
    CAUSAL_EXPECTED_NOTIONAL_DOWNSTREAM_STATUS,
    CAUSAL_EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256,
    CAUSAL_EXPECTED_NOTIONAL_POLICY_CONFIG_SHA256,
    CAUSAL_EXPECTED_NOTIONAL_POLICY_ID,
    CAUSAL_EXPECTED_NOTIONAL_POLICY_V1_SCHEMA_VERSION,
    CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
    CAUSAL_EXPECTED_NOTIONAL_SOURCE_RECEIPT_V1_SCHEMA_VERSION,
    CAUSAL_EXPECTED_NOTIONAL_SOURCE_TRANSPORT,
    CausalExpectedNotionalPolicyV1Error,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.paper_research_causal_cost_evidence_v1 import (
    PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION,
    PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS,
    PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
    PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256,
    PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION,
    PaperResearchCausalCostEvidenceV1Error,
    PaperResearchCausalCostEvidenceV1Result,
)

PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_SCHEMA_VERSION: Final = (
    "paper_research_causal_cost_portable_closure_v1"
)
PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_CLASSIFICATION: Final = (
    "COMPLETE_RESTART_REVALIDATABLE_RESEARCH_COST_SOURCE_CLOSURE_NO_AUTHORITY_V1"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)
_CONSTRUCTION_TOKEN = object()
_FACTORY_SEAL_KEY = secrets.token_bytes(32)
# Serialization/resource bounds only; never market or admission thresholds.
_MAX_CLOSURE_BYTES = 8 * 1024 * 1024
_EXPECTED_SOURCE_OBJECT_COUNT = 13
_EXPECTED_COMPLETE_OBJECT_COUNT = 15
_MAX_PREREQUISITE_OBJECT_BYTES = max(
    _MAX_CLOSURE_BYTES,
    MAX_SOURCE_PAYLOAD_BYTES,
)
_MAX_COMPLETE_CAS_BYTES = (
    _EXPECTED_COMPLETE_OBJECT_COUNT * _MAX_PREREQUISITE_OBJECT_BYTES
)

_AUTHORIZATION: Final = {
    "trainer_admission_authorized": False,
    "optimizer_execution_authorized": False,
    "checkpoint_write_authorized": False,
    "model_write_authorized": False,
    "calibration_input_authorized": False,
    "prediction_authorized": False,
    "serving_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "exchange_access_authorized": False,
    "deployment_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "runtime_wired": False,
}

_COST_AUTHORIZATION: Final = {
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

_NOTIONAL_CONTRACT_FIELDS: Final = frozenset(
    {
        "schema_version",
        "classification",
        "downstream_status",
        "policy_version_material",
        "source_read_receipt",
        "source_read_receipt_cas_address",
        "notional_artifact",
        "notional_artifact_cas_address",
        "notional_receipt",
        "notional_receipt_cas_address",
        "raw_status_cas_address",
        "read_only",
        "trainer_authority",
        "prediction_authority",
        "paper_authority",
        "live_authority",
        "order_authority",
        "fallback_used",
        "static_default_used",
    }
)

_MARKET_SOURCE_FIELDS: Final = frozenset(
    {
        "source_key",
        "source_key_sha256",
        "payload_sha256",
        "payload_byte_count",
        "payload_cas_address",
        "atomic_batch_id",
        "atomic_batch_material_sha256",
        "atomic_server_observed_at",
        "redis_pttl_ms",
        "redis_pttl_expiry_projection_at",
        "expiry_evidence_kind",
        "decision_within_persisted_expiry_evidence",
        "consumer_static_age_threshold_applied",
        "source_schema_version",
        "source_transport",
        "source_sequence_id",
        "source_sequence_gap",
        "clocks",
        "direct_read_receipt_sha256",
        "direct_read_receipt_cas_address",
    }
)

_MANIFEST_FIELDS: Final = frozenset(
    {
        "schema_version",
        "classification",
        "closure_module_code_sha256",
        "cost_evidence_artifact_sha256",
        "cost_evidence_artifact_cas_address",
        "cost_contract_material_sha256",
        "source_cas_object_count",
        "source_cas_object_inventory",
        "source_cas_object_inventory_sha256",
        "complete_cas_object_count",
        "complete_cas_object_inventory",
        "complete_cas_object_inventory_sha256",
        "registry_public_key_sha256",
        "registry_public_key_cas_address",
        "expected_fee_trust_anchor_id",
        "expected_fee_source_revision",
        "notional_policy_contract",
        "notional_policy_contract_sha256",
        "portable_source_closure_complete",
        "restart_reopen_supported",
        "research_only",
        "authorization",
        "closure_material_sha256",
    }
)


class PaperResearchCausalCostPortableClosureV1Error(RuntimeError):
    """Stable, payload-safe portable-closure error."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PaperResearchCausalCostPortableClosureV1ValidationError(
    PaperResearchCausalCostPortableClosureV1Error
):
    """Caller input is not an exact supported factory object or address."""


class PaperResearchCausalCostPortableClosureV1IntegrityError(
    PaperResearchCausalCostPortableClosureV1Error
):
    """A closure byte, signature, receipt, derivation, or CAS binding failed."""


def _validation(reason: str) -> NoReturn:
    raise PaperResearchCausalCostPortableClosureV1ValidationError(reason) from None


def _integrity(reason: str) -> NoReturn:
    raise PaperResearchCausalCostPortableClosureV1IntegrityError(reason) from None


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
    if not encoded or len(encoded) > _MAX_CLOSURE_BYTES:
        _validation(reason)
    return encoded


def _sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_bytes(value, reason="PORTABLE_COST_CLOSURE_CANONICAL_JSON_INVALID")
    ).hexdigest()


def _parse_exact_object(payload: bytes, *, reason: str) -> dict[str, Any]:
    if type(payload) is not bytes or not payload or len(payload) > _MAX_CLOSURE_BYTES:
        _integrity(reason)

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, value in pairs:
            if key in parsed:
                _integrity(reason)
            parsed[key] = value
        return parsed

    def reject_constant(_: str) -> NoReturn:
        _integrity(reason)

    try:
        parsed = json.loads(
            payload.decode("ascii", errors="strict"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except PaperResearchCausalCostPortableClosureV1Error:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeError, ValueError):
        _integrity(reason)
    if type(parsed) is not dict:
        _integrity(reason)
    parsed = cast(dict[str, Any], parsed)
    try:
        canonical = _canonical_bytes(parsed, reason=reason)
    except PaperResearchCausalCostPortableClosureV1ValidationError as exc:
        raise PaperResearchCausalCostPortableClosureV1IntegrityError(reason) from exc
    if not hmac.compare_digest(canonical, payload):
        _integrity(reason)
    return parsed


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _has_exact_values(
    supplied: dict[str, Any],
    expected: dict[str, Any],
) -> bool:
    return all(
        type(supplied.get(key)) is type(value) and supplied.get(key) == value
        for key, value in expected.items()
    )


def _address_mapping(address: SourcePayloadAddress) -> dict[str, Any]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _address_from_mapping(value: object, *, reason: str) -> SourcePayloadAddress:
    if type(value) is not dict:
        _integrity(reason)
    mapping = cast(dict[str, Any], value)
    if set(mapping) != {
        "schema_version",
        "payload_sha256",
        "payload_byte_count",
        "relative_path",
    }:
        _integrity(reason)
    digest = mapping.get("payload_sha256")
    byte_count = mapping.get("payload_byte_count")
    if (
        mapping.get("schema_version") != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or not _valid_sha256(digest)
        or type(byte_count) is not int
        or byte_count <= 0
        or mapping.get("relative_path") != f"sha256/{digest[:2]}/{digest}"
    ):
        _integrity(reason)
    return SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=cast(str, digest),
        payload_byte_count=cast(int, byte_count),
        relative_path=cast(str, mapping["relative_path"]),
    )


def _expected_address(payload: bytes) -> SourcePayloadAddress:
    digest = hashlib.sha256(payload).hexdigest()
    return SourcePayloadAddress(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=digest,
        payload_byte_count=len(payload),
        relative_path=f"sha256/{digest[:2]}/{digest}",
    )


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
        raise PaperResearchCausalCostPortableClosureV1IntegrityError(reason) from exc
    if (
        len(payload) != address.payload_byte_count
        or hashlib.sha256(payload).hexdigest() != address.payload_sha256
    ):
        _integrity(reason)
    return payload


def _put_exact(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
    payload: bytes,
    *,
    reason: str,
) -> None:
    if _expected_address(payload) != address:
        _integrity(reason)
    try:
        published = store.put(
            payload,
            expected_sha256=address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise PaperResearchCausalCostPortableClosureV1IntegrityError(reason) from exc
    if published != address or not hmac.compare_digest(
        _get_exact(store, address, reason=reason), payload
    ):
        _integrity(reason)


def _clock(value: object, *, reason: str):  # noqa: ANN202
    try:
        canonical, parsed = _causal._clock(value, reason=reason)  # noqa: SLF001
    except CausalCostEvidenceV1Error as exc:
        raise PaperResearchCausalCostPortableClosureV1IntegrityError(reason) from exc
    if value != canonical:
        _integrity(reason)
    return canonical, parsed


def _portable_notional_contract(
    value: object,
    *,
    store: ImmutableSourcePayloadStore,
) -> dict[str, Any]:
    reason = "PORTABLE_COST_CLOSURE_NOTIONAL_CONTRACT_INVALID"
    if type(value) is not dict or frozenset(cast(dict[str, Any], value)) != (
        _NOTIONAL_CONTRACT_FIELDS
    ):
        _integrity(reason)
    contract = cast(dict[str, Any], value)
    if (
        contract.get("schema_version")
        != CAUSAL_EXPECTED_NOTIONAL_POLICY_V1_SCHEMA_VERSION
        or contract.get("classification") != CAUSAL_EXPECTED_NOTIONAL_CLASSIFICATION
        or contract.get("downstream_status")
        != CAUSAL_EXPECTED_NOTIONAL_DOWNSTREAM_STATUS
        or contract.get("read_only") is not True
        or contract.get("fallback_used") is not False
        or contract.get("static_default_used") is not False
        or any(
            contract.get(name) is not False
            for name in (
                "trainer_authority",
                "prediction_authority",
                "paper_authority",
                "live_authority",
                "order_authority",
            )
        )
    ):
        _integrity(reason)

    source_receipt_value = contract.get("source_read_receipt")
    if (
        type(source_receipt_value) is not dict
        or frozenset(source_receipt_value)
        != _notional.CAUSAL_EXPECTED_NOTIONAL_SOURCE_RECEIPT_FIELDS
    ):
        _integrity(reason)
    source_receipt = cast(dict[str, Any], source_receipt_value)
    detached_receipt = dict(source_receipt)
    supplied_receipt_sha256 = detached_receipt.pop("receipt_sha256", None)
    if (
        not _valid_sha256(supplied_receipt_sha256)
        or _sha256(detached_receipt) != supplied_receipt_sha256
    ):
        _integrity(reason)
    source_receipt_bytes = _canonical_bytes(source_receipt, reason=reason)
    source_receipt_address = _address_from_mapping(
        contract.get("source_read_receipt_cas_address"), reason=reason
    )
    if not hmac.compare_digest(
        _get_exact(store, source_receipt_address, reason=reason),
        source_receipt_bytes,
    ):
        _integrity(reason)

    raw_address = _address_from_mapping(
        contract.get("raw_status_cas_address"), reason=reason
    )
    if (
        source_receipt.get("raw_status_cas_address") != _address_mapping(raw_address)
        or source_receipt.get("raw_status_payload_sha256")
        != raw_address.payload_sha256
        or source_receipt.get("raw_status_payload_byte_count")
        != raw_address.payload_byte_count
    ):
        _integrity(reason)
    raw_status_bytes = _get_exact(store, raw_address, reason=reason)
    try:
        status = _notional._parse_strict_outer_json(raw_status_bytes)  # noqa: SLF001
        embedded_hash, count, gross, expected, generated_iso = (
            _notional._verified_status_aggregate(status)  # noqa: SLF001
        )
        current_module_sha256 = _notional._module_code_sha256()  # noqa: SLF001
    except CausalExpectedNotionalPolicyV1Error as exc:
        raise PaperResearchCausalCostPortableClosureV1IntegrityError(reason) from exc

    generated_iso, generated_at = _clock(generated_iso, reason=reason)
    server_iso, server_at = _clock(
        source_receipt.get("server_observed_at"), reason=reason
    )
    decision_iso, decision_at = _clock(
        source_receipt.get("decision_time"), reason=reason
    )
    expires_iso, expires_at = _clock(source_receipt.get("expires_at"), reason=reason)
    pttl_ms = source_receipt.get("source_pttl_ms")
    batch_material_sha256 = source_receipt.get("atomic_batch_material_sha256")
    try:
        expected_expiry_at = server_at + timedelta(milliseconds=pttl_ms)
    except (OverflowError, TypeError):
        _integrity(reason)
    if (
        type(pttl_ms) is not int
        or pttl_ms <= 0
        or expected_expiry_at != expires_at
        or not generated_at <= server_at <= decision_at < expires_at
        or math.ceil((decision_at - server_at).total_seconds() * 1000.0)
        >= pttl_ms
        or not _valid_sha256(batch_material_sha256)
        or source_receipt.get("atomic_batch_id")
        != f"trainer_atomic_redis_source_read_v2_{batch_material_sha256}"
    ):
        _integrity(reason)
    expected_source_literals = {
        "schema_version": CAUSAL_EXPECTED_NOTIONAL_SOURCE_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "ATOMIC_REDIS_EXACT_READ_DERIVATION",
        "source_key": CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
        "source_transport": "ATOMIC_REDIS_GETRANGE_PTTL_TIME_AND_IMMUTABLE_CAS",
        "source_generated_at": generated_iso,
        "server_observed_at": server_iso,
        "available_at": server_iso,
        "expires_at": expires_iso,
        "decision_time": decision_iso,
        "embedded_aggregate_contract_hash": embedded_hash,
        "aggregate_candidate_count": count,
        "aggregate_gross_notional_usd": gross,
        "expected_notional_usd": expected,
        "candidate_supply_status": "POSITIVE_HASH_BOUND_AGGREGATE_AVAILABLE",
        "zero_candidate_handling": "FAIL_CLOSED_NO_ARTIFACT_NO_DEFAULT",
        "derivation_formula": (
            "capital.numeric_sums.gross_notional_usd/capital.candidate_count"
        ),
        "policy_id": CAUSAL_EXPECTED_NOTIONAL_POLICY_ID,
        "implementation_contract_sha256": (
            CAUSAL_EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256
        ),
        "policy_config_sha256": CAUSAL_EXPECTED_NOTIONAL_POLICY_CONFIG_SHA256,
        "module_code_sha256": current_module_sha256,
        "outer_status_canonical_serialization_required": False,
        "operator_projection_used": False,
        "fallback_used": False,
        "static_default_used": False,
        "read_only": True,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "order_authority": False,
    }
    if not _has_exact_values(source_receipt, expected_source_literals):
        _integrity(reason)
    symbol = source_receipt.get("symbol")
    snapshot_identity = source_receipt.get("feature_snapshot_identity")
    if (
        type(symbol) is not str
        or _SYMBOL_RE.fullmatch(symbol) is None
        or type(snapshot_identity) is not str
        or not snapshot_identity
    ):
        _integrity(reason)

    version_material = {
        "schema_version": "causal_expected_notional_policy_version_material_v1",
        "source_read_receipt_sha256": supplied_receipt_sha256,
        "implementation_contract_sha256": (
            CAUSAL_EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256
        ),
        "policy_config_sha256": CAUSAL_EXPECTED_NOTIONAL_POLICY_CONFIG_SHA256,
        "module_code_sha256": current_module_sha256,
    }
    policy_version = f"sha256:{_sha256(version_material)}"
    artifact = {
        "schema_version": _causal.CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
        "symbol": symbol,
        "feature_snapshot_identity": snapshot_identity,
        "value_unit": "USD",
        "expected_notional_usd": expected,
        "policy_id": CAUSAL_EXPECTED_NOTIONAL_POLICY_ID,
        "policy_version": policy_version,
        "policy_source_key": CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
        "effective_at": generated_iso,
        "available_at": server_iso,
        "expires_at": expires_iso,
        "causality_scope": "FEATURE_SNAPSHOT_DECISION_EXPECTED_EXECUTION_NOTIONAL",
        "fallback_used": False,
        "static_default_used": False,
    }
    artifact_address = _address_from_mapping(
        contract.get("notional_artifact_cas_address"), reason=reason
    )
    artifact_bytes = _canonical_bytes(artifact, reason=reason)
    if (
        contract.get("policy_version_material") != version_material
        or contract.get("notional_artifact") != artifact
        or artifact_address != _expected_address(artifact_bytes)
        or not hmac.compare_digest(
            _get_exact(store, artifact_address, reason=reason), artifact_bytes
        )
    ):
        _integrity(reason)

    receipt_material = {
        "schema_version": _causal.CAUSAL_COST_NOTIONAL_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "DIRECT_READ",
        "artifact_payload_sha256": artifact_address.payload_sha256,
        "artifact_payload_byte_count": artifact_address.payload_byte_count,
        "policy_source_key": CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
        "source_schema_version": (
            _causal.CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION
        ),
        "source_transport": CAUSAL_EXPECTED_NOTIONAL_SOURCE_TRANSPORT,
        "symbol": symbol,
        "feature_snapshot_identity": snapshot_identity,
        "effective_at": generated_iso,
        "available_at": server_iso,
        "expires_at": expires_iso,
        "authority_scope": "FEATURE_SNAPSHOT_CAUSAL_EXPECTED_NOTIONAL",
    }
    receipt = {**receipt_material, "receipt_sha256": _sha256(receipt_material)}
    receipt_address = _address_from_mapping(
        contract.get("notional_receipt_cas_address"), reason=reason
    )
    receipt_bytes = _canonical_bytes(receipt, reason=reason)
    if (
        contract.get("notional_receipt") != receipt
        or receipt_address != _expected_address(receipt_bytes)
        or not hmac.compare_digest(
            _get_exact(store, receipt_address, reason=reason), receipt_bytes
        )
    ):
        _integrity(reason)
    expected_contract = {
        "schema_version": CAUSAL_EXPECTED_NOTIONAL_POLICY_V1_SCHEMA_VERSION,
        "classification": CAUSAL_EXPECTED_NOTIONAL_CLASSIFICATION,
        "downstream_status": CAUSAL_EXPECTED_NOTIONAL_DOWNSTREAM_STATUS,
        "policy_version_material": version_material,
        "source_read_receipt": source_receipt,
        "source_read_receipt_cas_address": _address_mapping(
            source_receipt_address
        ),
        "notional_artifact": artifact,
        "notional_artifact_cas_address": _address_mapping(artifact_address),
        "notional_receipt": receipt,
        "notional_receipt_cas_address": _address_mapping(receipt_address),
        "raw_status_cas_address": _address_mapping(raw_address),
        "read_only": True,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "order_authority": False,
        "fallback_used": False,
        "static_default_used": False,
    }
    if _canonical_bytes(contract, reason=reason) != _canonical_bytes(
        expected_contract, reason=reason
    ):
        _integrity(reason)
    return expected_contract


def _portable_market_derivations(
    cost_contract: dict[str, Any],
    *,
    store: ImmutableSourcePayloadStore,
    symbol: str,
    snapshot_identity: str,
    decision_iso: str,
    decision_at: Any,
    expected_notional: float,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    tuple[tuple[SourcePayloadAddress, bytes], ...],
    tuple[tuple[SourcePayloadAddress, bytes], ...],
    float,
    float,
    dict[str, Any],
    float,
    dict[str, Any],
]:
    reason = "PORTABLE_COST_CLOSURE_MARKET_SOURCE_INVALID"
    sources_value = cost_contract.get("market_sources")
    if type(sources_value) is not dict or set(sources_value) != {
        "orderbook_depth",
        "orderbook_features",
        "mark_price",
    }:
        _integrity(reason)
    sources = cast(dict[str, dict[str, Any]], sources_value)
    rebuilt = cast(
        dict[str, dict[str, Any]],
        json.loads(_canonical_bytes(sources, reason=reason)),
    )
    roles = ("orderbook_depth", "orderbook_features", "mark_price")
    expected_keys = {
        "orderbook_depth": f"v2:orderbook:depth:binance:{symbol}",
        "orderbook_features": f"v2:orderbook:features:binance:{symbol}",
        "mark_price": f"v2:market:mark_price:{symbol}",
    }
    payloads: dict[str, dict[str, Any]] = {}
    payload_objects: list[tuple[SourcePayloadAddress, bytes]] = []
    common_batch: tuple[str, str, str] | None = None
    for role in roles:
        source = rebuilt.get(role)
        if type(source) is not dict or frozenset(source) != _MARKET_SOURCE_FIELDS:
            _integrity(reason)
        payload_address = _address_from_mapping(
            source.get("payload_cas_address"), reason=reason
        )
        source_key = expected_keys[role]
        server_iso, server_at = _clock(
            source.get("atomic_server_observed_at"), reason=reason
        )
        projected_iso, projected_at = _clock(
            source.get("redis_pttl_expiry_projection_at"), reason=reason
        )
        pttl_ms = source.get("redis_pttl_ms")
        batch_id = source.get("atomic_batch_id")
        batch_sha256 = source.get("atomic_batch_material_sha256")
        current_batch = (cast(str, batch_id), cast(str, batch_sha256), server_iso)
        if common_batch is None:
            common_batch = current_batch
        try:
            expected_expiry_at = server_at + timedelta(milliseconds=pttl_ms)
        except (OverflowError, TypeError):
            _integrity(reason)
        if (
            source.get("source_key") != source_key
            or source.get("source_key_sha256")
            != hashlib.sha256(source_key.encode("ascii")).hexdigest()
            or source.get("payload_sha256") != payload_address.payload_sha256
            or source.get("payload_byte_count") != payload_address.payload_byte_count
            or type(pttl_ms) is not int
            or pttl_ms <= 0
            or projected_at != expected_expiry_at
            or math.ceil((decision_at - server_at).total_seconds() * 1000.0)
            >= pttl_ms
            or server_at > decision_at
            or source.get("expiry_evidence_kind")
            != "REDIS_PTTL_IN_SAME_ATOMIC_READ_TRANSACTION"
            or source.get("decision_within_persisted_expiry_evidence") is not True
            or source.get("consumer_static_age_threshold_applied") is not False
            or source.get("source_sequence_gap") is not False
            or not _valid_sha256(batch_sha256)
            or batch_id != f"trainer_atomic_redis_source_read_v2_{batch_sha256}"
            or current_batch != common_batch
            or projected_iso
            != expected_expiry_at.isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z")
        ):
            _integrity(reason)
        payload = _get_exact(store, payload_address, reason=reason)
        try:
            parsed = _causal._parse_exact_json_bytes(  # noqa: SLF001
                payload,
                reason=reason,
            )
        except CausalCostEvidenceV1Error as exc:
            raise PaperResearchCausalCostPortableClosureV1IntegrityError(
                reason
            ) from exc
        payloads[role] = parsed
        payload_objects.append((payload_address, payload))

    try:
        spread, impact, orderbook_derivation = _causal._validate_orderbook_sources(  # noqa: SLF001
            depth=payloads["orderbook_depth"],
            features=payloads["orderbook_features"],
            evidence=rebuilt,
            symbol=symbol,
            decision_at=decision_at,
            expected_notional_usd=expected_notional,
        )
        funding, funding_derivation = _causal._validate_mark_source(  # noqa: SLF001
            mark=payloads["mark_price"],
            evidence=rebuilt,
            symbol=symbol,
            decision_at=decision_at,
        )
    except CausalCostEvidenceV1Error as exc:
        raise PaperResearchCausalCostPortableClosureV1IntegrityError(reason) from exc
    if rebuilt != sources:
        _integrity(reason)

    receipt_contract_value = cost_contract.get("market_source_read_receipts")
    if type(receipt_contract_value) is not dict or set(receipt_contract_value) != set(
        roles
    ):
        _integrity(reason)
    receipt_contract = cast(dict[str, dict[str, Any]], receipt_contract_value)
    receipt_objects: list[tuple[SourcePayloadAddress, bytes]] = []
    expected_receipts: dict[str, dict[str, Any]] = {}
    for role in roles:
        source = rebuilt[role]
        try:
            expected_receipt = _causal._market_source_receipt(  # noqa: SLF001
                role=role,
                source=source,
                symbol=symbol,
                feature_snapshot_identity=snapshot_identity,
                decision_time=decision_iso,
            )
        except CausalCostEvidenceV1Error as exc:
            raise PaperResearchCausalCostPortableClosureV1IntegrityError(
                reason
            ) from exc
        receipt_address = _address_from_mapping(
            source.get("direct_read_receipt_cas_address"), reason=reason
        )
        receipt_bytes = _get_exact(store, receipt_address, reason=reason)
        receipt = _parse_exact_object(receipt_bytes, reason=reason)
        if (
            receipt != expected_receipt
            or receipt_contract.get(role) != expected_receipt
            or source.get("direct_read_receipt_sha256")
            != expected_receipt["receipt_sha256"]
            or receipt_address != _expected_address(
                _canonical_bytes(expected_receipt, reason=reason)
            )
        ):
            _integrity(reason)
        expected_receipts[role] = expected_receipt
        receipt_objects.append((receipt_address, receipt_bytes))
    return (
        rebuilt,
        expected_receipts,
        tuple(payload_objects),
        tuple(receipt_objects),
        spread,
        impact,
        orderbook_derivation,
        funding,
        funding_derivation,
    )


def _revalidated_cost_contract(
    *,
    cost_contract: dict[str, Any],
    notional_contract: dict[str, Any],
    registry_public_key_bytes: bytes,
    store: ImmutableSourcePayloadStore,
) -> tuple[dict[str, Any], tuple[tuple[SourcePayloadAddress, bytes], ...]]:
    reason = "PORTABLE_COST_CLOSURE_COST_REVALIDATION_FAILED"
    try:
        symbol = cost_contract.get("symbol")
        snapshot_identity = cost_contract.get("feature_snapshot_identity")
        if (
            type(symbol) is not str
            or _SYMBOL_RE.fullmatch(symbol) is None
            or type(snapshot_identity) is not str
            or not snapshot_identity
        ):
            _integrity(reason)
        decision_iso, decision_at = _clock(
            cost_contract.get("decision_time"), reason=reason
        )
        if (
            cost_contract.get("schema_version")
            != PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION
            or cost_contract.get("evidence_classification")
            != PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION
            or cost_contract.get("downstream_status")
            != PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS
            or cost_contract.get("counterfactual_holding_horizon_seconds")
            != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        ):
            _integrity(reason)

        portable_notional = _portable_notional_contract(
            notional_contract,
            store=store,
        )
        source_receipt = cast(
            dict[str, Any], portable_notional["source_read_receipt"]
        )
        notional_artifact = cast(
            dict[str, Any], portable_notional["notional_artifact"]
        )
        if (
            source_receipt.get("symbol") != symbol
            or source_receipt.get("feature_snapshot_identity") != snapshot_identity
            or source_receipt.get("decision_time") != decision_iso
            or notional_artifact.get("symbol") != symbol
            or notional_artifact.get("feature_snapshot_identity")
            != snapshot_identity
        ):
            _integrity(reason)
        expected_notional_value = notional_artifact.get("expected_notional_usd")
        if type(expected_notional_value) not in {int, float}:
            _integrity(reason)
        try:
            expected_notional = float(cast(int | float, expected_notional_value))
        except (OverflowError, TypeError, ValueError):
            _integrity(reason)
        if not math.isfinite(expected_notional) or expected_notional <= 0.0:
            _integrity(reason)

        notional_artifact_address = _address_from_mapping(
            portable_notional.get("notional_artifact_cas_address"), reason=reason
        )
        notional_receipt_address = _address_from_mapping(
            portable_notional.get("notional_receipt_cas_address"), reason=reason
        )
        notional_artifact_bytes = _get_exact(
            store, notional_artifact_address, reason=reason
        )
        notional_receipt = cast(
            dict[str, Any], portable_notional["notional_receipt"]
        )
        try:
            notional_source, validated_notional_receipt, notional_objects = (
                _causal._validate_notional_evidence(  # noqa: SLF001
                    store=store,
                    artifact_bytes=notional_artifact_bytes,
                    receipt=notional_receipt,
                    expected_notional_usd=expected_notional,
                    symbol=symbol,
                    feature_snapshot_identity=snapshot_identity,
                    decision_at=decision_at,
                )
            )
        except CausalCostEvidenceV1Error as exc:
            raise PaperResearchCausalCostPortableClosureV1IntegrityError(
                reason
            ) from exc
        if (
            notional_objects[0][0] != notional_artifact_address
            or notional_objects[1][0] != notional_receipt_address
            or validated_notional_receipt != notional_receipt
        ):
            _integrity(reason)
        raw_status_address = _address_from_mapping(
            portable_notional.get("raw_status_cas_address"), reason=reason
        )
        source_receipt_address = _address_from_mapping(
            portable_notional.get("source_read_receipt_cas_address"), reason=reason
        )
        raw_status_bytes = _get_exact(store, raw_status_address, reason=reason)
        source_receipt_bytes = _get_exact(
            store, source_receipt_address, reason=reason
        )
        notional_source.update(
            {
                "factory_token_schema_version": portable_notional["schema_version"],
                "factory_token_policy_version": notional_artifact["policy_version"],
                "factory_token_source_read_receipt_sha256": source_receipt[
                    "receipt_sha256"
                ],
                "factory_token_source_read_receipt_cas_address": (
                    _address_mapping(source_receipt_address)
                ),
                "factory_token_raw_status_sha256": raw_status_address.payload_sha256,
                "factory_token_raw_status_cas_address": _address_mapping(
                    raw_status_address
                ),
                "factory_token_reauthenticated": True,
            }
        )
        if cost_contract.get("notional_source") != notional_source:
            _integrity(reason)

        fee_source_value = cost_contract.get("fee_source")
        if type(fee_source_value) is not dict:
            _integrity(reason)
        fee_source_contract = cast(dict[str, Any], fee_source_value)
        fee_document_address = _address_from_mapping(
            fee_source_contract.get("source_document_cas_address"), reason=reason
        )
        fee_attestation_address = _address_from_mapping(
            fee_source_contract.get("artifact_cas_address"), reason=reason
        )
        fee_receipt_value = cost_contract.get("fee_schedule_receipt")
        if type(fee_receipt_value) is not dict:
            _integrity(reason)
        try:
            (
                fee_value,
                fee_source,
                fee_receipt,
                fee_objects,
                _fee_material_json,
            ) = _paper._validate_fee_evidence(  # noqa: SLF001
                store=store,
                source_document_bytes=_get_exact(
                    store, fee_document_address, reason=reason
                ),
                signed_attestation=_get_exact(
                    store, fee_attestation_address, reason=reason
                ),
                material=_parse_exact_object(
                    _get_exact(store, fee_attestation_address, reason=reason),
                    reason=reason,
                ).get("fee_material"),
                registry_public_key_bytes=registry_public_key_bytes,
                registry_public_key_sha256=fee_source_contract.get(
                    "registry_public_key_sha256"
                ),
                expected_trust_anchor_id=fee_source_contract.get("trust_anchor_id"),
                expected_source_revision=fee_source_contract.get(
                    "independently_expected_source_revision"
                ),
                symbol=symbol,
                decision_at=decision_at,
            )
        except PaperResearchCausalCostEvidenceV1Error as exc:
            raise PaperResearchCausalCostPortableClosureV1IntegrityError(
                reason
            ) from exc
        if (
            fee_source != fee_source_contract
            or fee_receipt != fee_receipt_value
            or fee_objects[0][0] != fee_document_address
            or fee_objects[1][0] != fee_attestation_address
        ):
            _integrity(reason)

        (
            market_sources,
            market_receipts,
            market_payload_objects,
            market_receipt_objects,
            spread_value,
            impact_value,
            orderbook_derivation,
            funding_value,
            funding_derivation,
        ) = _portable_market_derivations(
            cost_contract,
            store=store,
            symbol=symbol,
            snapshot_identity=snapshot_identity,
            decision_iso=decision_iso,
            decision_at=decision_at,
            expected_notional=expected_notional,
        )

        module_sha256 = _paper._module_code_sha256()  # noqa: SLF001
        shared_module_sha256 = _causal._module_code_sha256()  # noqa: SLF001
        exact_bindings = {
            "symbol": symbol,
            "feature_snapshot_identity": snapshot_identity,
            "feature_snapshot_identity_sha256": hashlib.sha256(
                snapshot_identity.encode("ascii")
            ).hexdigest(),
            "decision_time": decision_iso,
            "counterfactual_holding_horizon_seconds": (
                CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
            ),
            "expected_notional_usd": expected_notional,
            "expected_notional_float64_hex": expected_notional.hex(),
            "notional_policy_receipt_sha256": validated_notional_receipt[
                "receipt_sha256"
            ],
            "configured_public_fee_schedule_receipt_sha256": fee_receipt[
                "receipt_sha256"
            ],
            "configured_public_fee_attested_material_sha256": fee_source[
                "attested_material_sha256"
            ],
            "configured_public_fee_registry_public_key_sha256": fee_source[
                "registry_public_key_sha256"
            ],
            "configured_public_fee_expected_source_revision": fee_source[
                "independently_expected_source_revision"
            ],
            "atomic_batch_id": market_sources["orderbook_depth"]["atomic_batch_id"],
            "atomic_batch_material_sha256": market_sources["orderbook_depth"][
                "atomic_batch_material_sha256"
            ],
            "profiled_39_record_id": None,
            "research_training_record_id": None,
        }
        specs = (
            (
                "fee_bps",
                fee_value,
                {
                    "component_semantics": (
                        "CONFIGURED_PUBLIC_TAKER_FEE_BPS_PER_SIDE"
                    ),
                    "formula": "SIGNED_DECIMAL_STRING_TAKER_FEE_BPS_PER_SIDE",
                    "required_child_roles": [
                        "signed_configured_public_fee_schedule"
                    ],
                    "account_specific_commission_authenticated": False,
                },
                (
                    {
                        "input_role": "signed_configured_public_fee_schedule",
                        "receipt_sha256": fee_receipt["receipt_sha256"],
                    },
                ),
                {
                    "taker_fee_bps_per_side_decimal": fee_source[
                        "taker_fee_bps_per_side_decimal"
                    ],
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
                    "component_semantics": (
                        "FULL_BID_ASK_SPREAD_ONE_ROUND_TRIP_CROSS"
                    ),
                    "formula": "(BEST_ASK-BEST_BID)/MID*10000",
                    "required_child_roles": [
                        "orderbook_depth",
                        "orderbook_features",
                    ],
                },
                tuple(
                    {
                        "input_role": role,
                        "receipt_sha256": market_receipts[role]["receipt_sha256"],
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
                    "formula": (
                        "MAX_BUY_SELL_RAW_DEPTH_VWAP_IMPACT_AT_EXACT_NOTIONAL"
                    ),
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
                            "receipt_sha256": market_receipts[role][
                                "receipt_sha256"
                            ],
                        }
                        for role in ("orderbook_depth", "orderbook_features")
                    ),
                    {
                        "input_role": "expected_notional_policy",
                        "receipt_sha256": validated_notional_receipt[
                            "receipt_sha256"
                        ],
                    },
                ),
                orderbook_derivation,
            ),
            (
                "expected_funding_bps",
                funding_value,
                {
                    "component_semantics": (
                        "SIGNED_VENUE_RATE_OVER_PINNED_HORIZON"
                    ),
                    "formula": _paper._IMPLEMENTATION_CONTRACT[  # noqa: SLF001
                        "funding_formula"
                    ],
                    "required_child_roles": ["mark_price"],
                },
                (
                    {
                        "input_role": "mark_price",
                        "receipt_sha256": market_receipts["mark_price"][
                            "receipt_sha256"
                        ],
                    },
                ),
                funding_derivation,
            ),
        )
        values: list[float] = []
        receipts: list[dict[str, Any]] = []
        for feature_name, raw_value, configuration, children, derivation in specs:
            resolved, value_hex = _paper._float32(  # noqa: SLF001
                raw_value,
                reason=reason,
            )
            values.append(resolved)
            receipts.append(
                _paper._research_composite_receipt(  # noqa: SLF001
                    feature_name=feature_name,
                    value=resolved,
                    value_hex=value_hex,
                    configuration=configuration,
                    child_bindings=children,
                    exact_bindings=exact_bindings,
                    derivation=derivation,
                    module_code_sha256=module_sha256,
                    shared_causal_module_code_sha256=shared_module_sha256,
                )
            )

        expected_source_objects = (
            *market_payload_objects,
            *notional_objects,
            (raw_status_address, raw_status_bytes),
            (source_receipt_address, source_receipt_bytes),
            *fee_objects,
            *market_receipt_objects,
        )
        expected_source_inventory = [
            _address_mapping(address) for address, _payload in expected_source_objects
        ]
        contract_material = {
            "schema_version": PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION,
            "evidence_classification": (
                PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION
            ),
            "downstream_status": (
                PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS
            ),
            "implementation_id": PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
            "implementation_sha256": (
                PAPER_RESEARCH_CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
            ),
            "shared_causal_market_notional_dependency_sha256": (
                CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
            ),
            "shared_causal_market_notional_module_code_sha256": shared_module_sha256,
            "module_code_sha256": module_sha256,
            "symbol": symbol,
            "feature_snapshot_identity": snapshot_identity,
            "decision_time": decision_iso,
            "counterfactual_holding_horizon_seconds": (
                CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
            ),
            "ordered_feature_names": list(CAUSAL_COST_ORDERED_FEATURE_NAMES),
            "ordered_values": values,
            "ordered_receipt_sha256s": [
                item["receipt_sha256"] for item in receipts
            ],
            "ordered_receipts": receipts,
            "market_sources": market_sources,
            "market_source_read_receipts": market_receipts,
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
            "source_cas_object_count": len(expected_source_inventory),
            "source_cas_object_inventory": expected_source_inventory,
            "source_cas_object_inventory_sha256": _sha256(
                expected_source_inventory
            ),
            "research_training_admission_status": (
                "NOT_AUTHORIZED_SEPARATE_LEDGER_MANIFEST_WITNESS_AND_ADMISSION_REQUIRED"
            ),
            "no_static_fallback_or_floor": True,
            "optional_provider_dependencies": [],
            "authorization": dict(_COST_AUTHORIZATION),
        }
        material_sha256 = _sha256(contract_material)
        expected_contract = {
            **contract_material,
            "evidence_id": (
                f"paper_research_causal_cost_evidence_v1_{material_sha256}"
            ),
            "contract_material_sha256": material_sha256,
        }
    except PaperResearchCausalCostPortableClosureV1Error:
        raise
    except (
        CausalCostEvidenceV1Error,
        CausalExpectedNotionalPolicyV1Error,
        PaperResearchCausalCostEvidenceV1Error,
        AttributeError,
        KeyError,
        OverflowError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise PaperResearchCausalCostPortableClosureV1IntegrityError(reason) from exc
    if _canonical_bytes(cost_contract, reason=reason) != _canonical_bytes(
        expected_contract, reason=reason
    ):
        _integrity(reason)
    return expected_contract, expected_source_objects


def _module_code_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise PaperResearchCausalCostPortableClosureV1IntegrityError(
            "PORTABLE_COST_CLOSURE_IMPLEMENTATION_BYTES_UNAVAILABLE"
        ) from exc


def _factory_seal(
    *,
    closure_address: SourcePayloadAddress,
    closure_bytes: bytes,
    store: ImmutableSourcePayloadStore,
) -> str:
    material = {
        "domain": "v2/native-trainer/paper-research-cost-portable-closure/v1",
        "closure_address": _address_mapping(closure_address),
        "closure_bytes_sha256": hashlib.sha256(closure_bytes).hexdigest(),
        "closure_byte_count": len(closure_bytes),
        "store_process_identity": id(store),
    }
    return hmac.new(
        _FACTORY_SEAL_KEY,
        _canonical_bytes(material, reason="PORTABLE_COST_CLOSURE_FACTORY_SEAL_INVALID"),
        hashlib.sha256,
    ).hexdigest()


def _validated_closure_bytes(
    *,
    store: ImmutableSourcePayloadStore,
    closure_address: SourcePayloadAddress,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reason = "PORTABLE_COST_CLOSURE_REOPEN_FAILED"
    closure_bytes = _get_exact(store, closure_address, reason=reason)
    manifest = _parse_exact_object(closure_bytes, reason=reason)
    if frozenset(manifest) != _MANIFEST_FIELDS:
        _integrity("PORTABLE_COST_CLOSURE_MANIFEST_FIELDS_INVALID")
    material = {
        key: value
        for key, value in manifest.items()
        if key != "closure_material_sha256"
    }
    source_inventory_value = manifest.get("source_cas_object_inventory")
    complete_inventory_value = manifest.get("complete_cas_object_inventory")
    if (
        manifest.get("schema_version")
        != PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_SCHEMA_VERSION
        or manifest.get("classification")
        != PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_CLASSIFICATION
        or manifest.get("closure_module_code_sha256") != _module_code_sha256()
        or manifest.get("closure_material_sha256") != _sha256(material)
        or manifest.get("portable_source_closure_complete") is not True
        or manifest.get("restart_reopen_supported") is not True
        or manifest.get("research_only") is not True
        or type(source_inventory_value) is not list
        or type(complete_inventory_value) is not list
    ):
        _integrity(reason)
    authorization = manifest.get("authorization")
    if (
        type(authorization) is not dict
        or set(authorization) != set(_AUTHORIZATION)
        or any(
            type(authorization.get(name)) is not bool
            or authorization.get(name) is not False
            for name in _AUTHORIZATION
        )
    ):
        _integrity("PORTABLE_COST_CLOSURE_MANIFEST_AUTHORIZATION_INVALID")
    source_inventory = cast(list[dict[str, Any]], source_inventory_value)
    complete_inventory = cast(list[dict[str, Any]], complete_inventory_value)
    if (
        not source_inventory
        or len(source_inventory) != _EXPECTED_SOURCE_OBJECT_COUNT
        or type(manifest.get("source_cas_object_count")) is not int
        or manifest.get("source_cas_object_count")
        != _EXPECTED_SOURCE_OBJECT_COUNT
        or manifest.get("source_cas_object_inventory_sha256")
        != _sha256(source_inventory)
        or len(complete_inventory) != _EXPECTED_COMPLETE_OBJECT_COUNT
        or type(manifest.get("complete_cas_object_count")) is not int
        or manifest.get("complete_cas_object_count")
        != _EXPECTED_COMPLETE_OBJECT_COUNT
        or manifest.get("complete_cas_object_inventory_sha256")
        != _sha256(complete_inventory)
        or len(complete_inventory) != len(source_inventory) + 2
    ):
        _integrity("PORTABLE_COST_CLOSURE_OBJECT_COUNT_INVALID")
    source_addresses = tuple(
        _address_from_mapping(item, reason=reason) for item in source_inventory
    )
    complete_addresses = tuple(
        _address_from_mapping(item, reason=reason) for item in complete_inventory
    )
    if (
        len({address.payload_sha256 for address in complete_addresses})
        != len(complete_addresses)
        or complete_addresses[: len(source_addresses)] != source_addresses
    ):
        _integrity(reason)
    if (
        any(
            address.payload_byte_count > _MAX_PREREQUISITE_OBJECT_BYTES
            for address in complete_addresses
        )
        or sum(address.payload_byte_count for address in complete_addresses)
        > _MAX_COMPLETE_CAS_BYTES
    ):
        _integrity("PORTABLE_COST_CLOSURE_OBJECT_SIZE_INVALID")
    cost_address = _address_from_mapping(
        manifest.get("cost_evidence_artifact_cas_address"), reason=reason
    )
    public_key_address = _address_from_mapping(
        manifest.get("registry_public_key_cas_address"), reason=reason
    )
    if complete_addresses[-2:] != (cost_address, public_key_address):
        _integrity(reason)
    if (
        cost_address.payload_byte_count > _MAX_CLOSURE_BYTES
        or public_key_address.payload_byte_count != 32
    ):
        _integrity("PORTABLE_COST_CLOSURE_OBJECT_SIZE_INVALID")
    for address in complete_addresses:
        _get_exact(store, address, reason=reason)

    public_key_bytes = _get_exact(store, public_key_address, reason=reason)
    registry_public_key_sha256 = manifest.get("registry_public_key_sha256")
    if (
        len(public_key_bytes) != 32
        or not _valid_sha256(registry_public_key_sha256)
        or hashlib.sha256(public_key_bytes).hexdigest()
        != registry_public_key_sha256
    ):
        _integrity("PORTABLE_COST_CLOSURE_FEE_TRUST_KEY_INVALID")
    cost_bytes = _get_exact(store, cost_address, reason=reason)
    cost_contract = _parse_exact_object(cost_bytes, reason=reason)
    fee_source = cost_contract.get("fee_source")
    if type(fee_source) is not dict:
        _integrity(reason)
    if (
        fee_source.get("registry_public_key_sha256")
        != registry_public_key_sha256
        or fee_source.get("trust_anchor_id")
        != manifest.get("expected_fee_trust_anchor_id")
        or fee_source.get("independently_expected_source_revision")
        != manifest.get("expected_fee_source_revision")
    ):
        _integrity("PORTABLE_COST_CLOSURE_FEE_TRUST_BINDING_INVALID")
    if (
        cost_contract.get("contract_material_sha256")
        != manifest.get("cost_contract_material_sha256")
        or cost_address.payload_sha256
        != manifest.get("cost_evidence_artifact_sha256")
    ):
        _integrity("PORTABLE_COST_CLOSURE_COST_ARTIFACT_BINDING_INVALID")
    notional_contract_value = manifest.get("notional_policy_contract")
    if (
        type(notional_contract_value) is not dict
        or manifest.get("notional_policy_contract_sha256")
        != _sha256(notional_contract_value)
    ):
        _integrity(reason)
    revalidated_contract, exact_source_objects = _revalidated_cost_contract(
        cost_contract=cost_contract,
        notional_contract=cast(dict[str, Any], notional_contract_value),
        registry_public_key_bytes=public_key_bytes,
        store=store,
    )
    if (
        [_address_mapping(address) for address, _payload in exact_source_objects]
        != source_inventory
    ):
        _integrity("PORTABLE_COST_CLOSURE_SOURCE_INVENTORY_MISMATCH")
    if _canonical_bytes(revalidated_contract, reason=reason) != cost_bytes:
        _integrity("PORTABLE_COST_CLOSURE_COST_ARTIFACT_BINDING_INVALID")
    return manifest, revalidated_contract


@dataclass(frozen=True, slots=True)
class PaperResearchCausalCostPortableClosureV1:
    """Factory-opened closure that revalidates every durable byte on access."""

    closure_sha256: str
    closure_byte_count: int
    closure_json: str = field(repr=False)
    closure_address: SourcePayloadAddress
    cost_evidence_artifact_sha256: str
    source_cas_object_count: int
    complete_cas_object_count: int
    ordered_values: tuple[float, float, float, float]
    ordered_receipt_sha256s: tuple[str, str, str, str]
    _store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _closure_bytes: bytes = field(repr=False, compare=False)
    _factory_seal: str = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    @property
    def manifest(self) -> dict[str, Any]:
        return _validated_result(self)[0]

    @property
    def cost_contract(self) -> dict[str, Any]:
        return _validated_result(self)[1]

    @property
    def ordered_receipts(self) -> tuple[dict[str, Any], ...]:
        contract = self.cost_contract
        return tuple(
            cast(dict[str, Any], receipt)
            for receipt in cast(list[object], contract["ordered_receipts"])
        )


def _validated_result(
    result: PaperResearchCausalCostPortableClosureV1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        type(result) is not PaperResearchCausalCostPortableClosureV1
        or result._construction_token is not _CONSTRUCTION_TOKEN
        or type(result._store) is not ImmutableSourcePayloadStore
        or type(result._closure_bytes) is not bytes
        or not _valid_sha256(result.closure_sha256)
        or type(result.closure_byte_count) is not int
        or result.closure_byte_count <= 0
        or type(result.closure_json) is not str
        or type(result.closure_address) is not SourcePayloadAddress
        or not _valid_sha256(result.cost_evidence_artifact_sha256)
        or type(result.source_cas_object_count) is not int
        or type(result.complete_cas_object_count) is not int
        or type(result.ordered_values) is not tuple
        or len(result.ordered_values) != 4
        or any(type(value) is not float for value in result.ordered_values)
        or type(result.ordered_receipt_sha256s) is not tuple
        or len(result.ordered_receipt_sha256s) != 4
        or any(
            not _valid_sha256(value) for value in result.ordered_receipt_sha256s
        )
        or type(result._factory_seal) is not str
        or _SHA256_RE.fullmatch(result._factory_seal) is None
    ):
        _integrity("PORTABLE_COST_CLOSURE_FACTORY_CONSTRUCTION_REQUIRED")
    expected_seal = _factory_seal(
        closure_address=result.closure_address,
        closure_bytes=result._closure_bytes,
        store=result._store,
    )
    try:
        closure_json_bytes = result.closure_json.encode("ascii", errors="strict")
    except (AttributeError, UnicodeError) as exc:
        raise PaperResearchCausalCostPortableClosureV1IntegrityError(
            "PORTABLE_COST_CLOSURE_RESULT_BINDING_INVALID"
        ) from exc
    if (
        not hmac.compare_digest(result._factory_seal, expected_seal)
        or closure_json_bytes != result._closure_bytes
        or result.closure_sha256 != hashlib.sha256(result._closure_bytes).hexdigest()
        or result.closure_byte_count != len(result._closure_bytes)
        or result.closure_address != _expected_address(result._closure_bytes)
    ):
        _integrity("PORTABLE_COST_CLOSURE_RESULT_BINDING_INVALID")
    manifest, cost_contract = _validated_closure_bytes(
        store=result._store,
        closure_address=result.closure_address,
    )
    values = tuple(cost_contract.get("ordered_values") or ())
    receipts = tuple(cost_contract.get("ordered_receipt_sha256s") or ())
    if (
        manifest.get("cost_evidence_artifact_sha256")
        != result.cost_evidence_artifact_sha256
        or manifest.get("source_cas_object_count")
        != result.source_cas_object_count
        or manifest.get("complete_cas_object_count")
        != result.complete_cas_object_count
        or _canonical_bytes(list(values), reason="PORTABLE_COST_CLOSURE_RESULT_INVALID")
        != _canonical_bytes(
            list(result.ordered_values),
            reason="PORTABLE_COST_CLOSURE_RESULT_INVALID",
        )
        or receipts != result.ordered_receipt_sha256s
        or len(values) != 4
        or len(receipts) != 4
    ):
        _integrity("PORTABLE_COST_CLOSURE_RESULT_BINDING_INVALID")
    return manifest, cost_contract


def open_paper_research_causal_cost_portable_closure_v1(
    *,
    store: object,
    closure_address: object,
) -> PaperResearchCausalCostPortableClosureV1:
    """Reopen one complete closure without an original factory result."""

    if type(store) is not ImmutableSourcePayloadStore:
        _validation("PORTABLE_COST_CLOSURE_IMMUTABLE_STORE_REQUIRED")
    if type(closure_address) is not SourcePayloadAddress:
        _validation("PORTABLE_COST_CLOSURE_EXACT_ADDRESS_REQUIRED")
    target_store = cast(ImmutableSourcePayloadStore, store)
    address = cast(SourcePayloadAddress, closure_address)
    closure_bytes = _get_exact(
        target_store,
        address,
        reason="PORTABLE_COST_CLOSURE_REOPEN_FAILED",
    )
    if address != _expected_address(closure_bytes):
        _integrity("PORTABLE_COST_CLOSURE_REOPEN_FAILED")
    manifest, cost_contract = _validated_closure_bytes(
        store=target_store,
        closure_address=address,
    )
    values = cast(
        tuple[float, float, float, float],
        tuple(cost_contract["ordered_values"]),
    )
    receipt_sha256s = cast(
        tuple[str, str, str, str],
        tuple(cost_contract["ordered_receipt_sha256s"]),
    )
    result = PaperResearchCausalCostPortableClosureV1(
        closure_sha256=address.payload_sha256,
        closure_byte_count=address.payload_byte_count,
        closure_json=closure_bytes.decode("ascii"),
        closure_address=address,
        cost_evidence_artifact_sha256=manifest["cost_evidence_artifact_sha256"],
        source_cas_object_count=manifest["source_cas_object_count"],
        complete_cas_object_count=manifest["complete_cas_object_count"],
        ordered_values=values,
        ordered_receipt_sha256s=receipt_sha256s,
        _store=target_store,
        _closure_bytes=closure_bytes,
        _factory_seal=_factory_seal(
            closure_address=address,
            closure_bytes=closure_bytes,
            store=target_store,
        ),
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    _validated_result(result)
    return result


def publish_paper_research_causal_cost_portable_closure_v1(
    *,
    cost_evidence: object,
    store: object,
) -> PaperResearchCausalCostPortableClosureV1:
    """Publish a complete closure only after all final bytes validate."""

    if type(cost_evidence) is not PaperResearchCausalCostEvidenceV1Result:
        _validation("PORTABLE_COST_CLOSURE_EXACT_COST_RESULT_REQUIRED")
    if type(store) is not ImmutableSourcePayloadStore:
        _validation("PORTABLE_COST_CLOSURE_IMMUTABLE_STORE_REQUIRED")
    cost = cast(PaperResearchCausalCostEvidenceV1Result, cost_evidence)
    target_store = cast(ImmutableSourcePayloadStore, store)
    try:
        # These package-private fields are read only after the original factory
        # seal, signature, notional token, and complete source CAS are rechecked.
        cost_contract = _paper._validated_result(cost)  # noqa: SLF001
        notional_contract = cost._notional_policy_token.contract  # noqa: SLF001
        exact_objects = cost._exact_objects  # noqa: SLF001
        source_store = cost._store  # noqa: SLF001
        registry_public_key_bytes = cost._registry_public_key_bytes  # noqa: SLF001
        expected_trust_anchor_id = cost._expected_trust_anchor_id  # noqa: SLF001
        expected_source_revision = cost._expected_fee_source_revision  # noqa: SLF001
    except (
        PaperResearchCausalCostEvidenceV1Error,
        CausalExpectedNotionalPolicyV1Error,
        AttributeError,
        TypeError,
    ) as exc:
        raise PaperResearchCausalCostPortableClosureV1IntegrityError(
            "PORTABLE_COST_CLOSURE_SOURCE_RESULT_REVALIDATION_FAILED"
        ) from exc
    if (
        type(exact_objects) is not tuple
        or len(exact_objects) < 2
        or type(source_store) is not ImmutableSourcePayloadStore
        or type(registry_public_key_bytes) is not bytes
        or len(registry_public_key_bytes) != 32
    ):
        _integrity("PORTABLE_COST_CLOSURE_SOURCE_RESULT_REVALIDATION_FAILED")
    exact_inventory: list[dict[str, Any]] = []
    validated_objects: list[tuple[SourcePayloadAddress, bytes]] = []
    for pair in exact_objects:
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[0]) is not SourcePayloadAddress
            or type(pair[1]) is not bytes
            or pair[0] != _expected_address(pair[1])
        ):
            _integrity("PORTABLE_COST_CLOSURE_SOURCE_OBJECT_INVALID")
        address = cast(SourcePayloadAddress, pair[0])
        payload = cast(bytes, pair[1])
        exact_inventory.append(_address_mapping(address))
        validated_objects.append((address, payload))
    source_inventory = cost_contract.get("source_cas_object_inventory")
    cost_address = cost.artifact_address
    cost_bytes = cost.artifact_json.encode("ascii", errors="strict")
    if (
        type(source_inventory) is not list
        or exact_inventory[:-1] != source_inventory
        or exact_inventory[-1] != _address_mapping(cost_address)
        or validated_objects[-1] != (cost_address, cost_bytes)
        or len(source_inventory) != _EXPECTED_SOURCE_OBJECT_COUNT
        or cost_contract.get("source_cas_object_count")
        != _EXPECTED_SOURCE_OBJECT_COUNT
    ):
        _integrity("PORTABLE_COST_CLOSURE_SOURCE_INVENTORY_INVALID")
    public_key_address = _expected_address(registry_public_key_bytes)
    if public_key_address.payload_sha256 in {
        address.payload_sha256 for address, _payload in validated_objects
    }:
        _integrity("PORTABLE_COST_CLOSURE_PUBLIC_KEY_ADDRESS_COLLISION")
    complete_inventory = [
        *exact_inventory,
        _address_mapping(public_key_address),
    ]
    registry_public_key_sha256 = hashlib.sha256(
        registry_public_key_bytes
    ).hexdigest()
    fee_source = cost_contract.get("fee_source")
    if (
        type(fee_source) is not dict
        or fee_source.get("registry_public_key_sha256")
        != registry_public_key_sha256
        or fee_source.get("trust_anchor_id") != expected_trust_anchor_id
        or fee_source.get("independently_expected_source_revision")
        != expected_source_revision
    ):
        _integrity("PORTABLE_COST_CLOSURE_FEE_TRUST_BINDING_INVALID")
    material = {
        "schema_version": (
            PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_SCHEMA_VERSION
        ),
        "classification": (
            PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_CLASSIFICATION
        ),
        "closure_module_code_sha256": _module_code_sha256(),
        "cost_evidence_artifact_sha256": cost.artifact_sha256,
        "cost_evidence_artifact_cas_address": _address_mapping(cost_address),
        "cost_contract_material_sha256": cost_contract[
            "contract_material_sha256"
        ],
        "source_cas_object_count": len(cast(list[object], source_inventory)),
        "source_cas_object_inventory": source_inventory,
        "source_cas_object_inventory_sha256": _sha256(source_inventory),
        "complete_cas_object_count": len(complete_inventory),
        "complete_cas_object_inventory": complete_inventory,
        "complete_cas_object_inventory_sha256": _sha256(complete_inventory),
        "registry_public_key_sha256": registry_public_key_sha256,
        "registry_public_key_cas_address": _address_mapping(public_key_address),
        "expected_fee_trust_anchor_id": expected_trust_anchor_id,
        "expected_fee_source_revision": expected_source_revision,
        "notional_policy_contract": notional_contract,
        "notional_policy_contract_sha256": _sha256(notional_contract),
        "portable_source_closure_complete": True,
        "restart_reopen_supported": True,
        "research_only": True,
        "authorization": dict(_AUTHORIZATION),
    }
    manifest = {**material, "closure_material_sha256": _sha256(material)}
    closure_bytes = _canonical_bytes(
        manifest,
        reason="PORTABLE_COST_CLOSURE_MANIFEST_INVALID",
    )
    closure_address = _expected_address(closure_bytes)

    preflight_contract, preflight_source_objects = _revalidated_cost_contract(
        cost_contract=cost_contract,
        notional_contract=notional_contract,
        registry_public_key_bytes=registry_public_key_bytes,
        store=source_store,
    )
    if (
        _canonical_bytes(
            preflight_contract,
            reason="PORTABLE_COST_CLOSURE_PREFLIGHT_REVALIDATION_FAILED",
        )
        != _canonical_bytes(
            cost_contract,
            reason="PORTABLE_COST_CLOSURE_PREFLIGHT_REVALIDATION_FAILED",
        )
        or preflight_source_objects != tuple(validated_objects[:-1])
    ):
        _integrity("PORTABLE_COST_CLOSURE_PREFLIGHT_REVALIDATION_FAILED")

    # No target-store mutation occurs until every final byte and binding above
    # has been constructed and validated. The manifest is published last.
    for address, payload in validated_objects:
        _put_exact(
            target_store,
            address,
            payload,
            reason="PORTABLE_COST_CLOSURE_SOURCE_COPY_FAILED",
        )
    _put_exact(
        target_store,
        public_key_address,
        registry_public_key_bytes,
        reason="PORTABLE_COST_CLOSURE_PUBLIC_KEY_COPY_FAILED",
    )
    _put_exact(
        target_store,
        closure_address,
        closure_bytes,
        reason="PORTABLE_COST_CLOSURE_MANIFEST_PUBLICATION_FAILED",
    )
    return open_paper_research_causal_cost_portable_closure_v1(
        store=target_store,
        closure_address=closure_address,
    )


__all__ = (
    "PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_CLASSIFICATION",
    "PAPER_RESEARCH_CAUSAL_COST_PORTABLE_CLOSURE_V1_SCHEMA_VERSION",
    "PaperResearchCausalCostPortableClosureV1",
    "PaperResearchCausalCostPortableClosureV1Error",
    "PaperResearchCausalCostPortableClosureV1IntegrityError",
    "PaperResearchCausalCostPortableClosureV1ValidationError",
    "open_paper_research_causal_cost_portable_closure_v1",
    "publish_paper_research_causal_cost_portable_closure_v1",
)
