"""Exact causal cost evidence for the profiled trainer bootstrap.

This is an intentionally unwired evidence primitive.  It validates one exact
atomic Redis read of the direct Binance order-book recorder's depth/features
keys and the direct Binance mark-price key, durably stores every exact source
byte string, and derives four label-only cost scalars.  It does not build a
39-slot physical feature record, append to a feature ledger, admit a training
sample, publish a prediction, or authorize paper/live execution.

The caller must supply authoritative, time-bounded fee-schedule bytes plus a
self-hashed source receipt and equally explicit expected-notional policy bytes
plus a self-hashed causal source receipt.  There is no configured fee,
notional, spread, impact, funding, or freshness fallback in this module.
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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    ATOMIC_REDIS_SOURCE_READ_DOWNSTREAM_STATUS,
    ATOMIC_REDIS_SOURCE_READ_EVIDENCE_CLASSIFICATION,
    ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION,
    ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION,
    MAX_AGGREGATE_PAYLOAD_BYTES,
    MAX_BATCH_MATERIALIZED_PAYLOAD_BYTES,
    MAX_RANGE_REPLY_BYTES,
    MAX_SOURCE_KEYS_PER_BATCH,
    MAX_SOURCE_PAYLOAD_BYTES,
    REDIS_TIME_CLOCK_SEMANTICS,
    AtomicRedisSourceReadBatch,
    AtomicRedisSourceResult,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)

CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION: Final = "causal_cost_evidence_v1"
CAUSAL_COST_SOURCE_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "causal_cost_atomic_source_read_receipt_v1"
)
CAUSAL_COST_COMPOSITE_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "causal_cost_composite_derivation_receipt_v1"
)
CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION: Final = (
    "causal_cost_authoritative_fee_schedule_artifact_v1"
)
CAUSAL_COST_FEE_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "causal_cost_authoritative_fee_schedule_receipt_v1"
)
CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION: Final = (
    "causal_cost_expected_notional_policy_artifact_v1"
)
CAUSAL_COST_NOTIONAL_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "causal_cost_expected_notional_policy_receipt_v1"
)
CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID: Final = (
    "DIRECT_BINANCE_DEPTH_MARK_EXACT_COST_TRANSFORM_V1"
)
CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION: Final = (
    "AUDIT_ONLY_LABEL_AUXILIARY_EVIDENCE_NO_PROFILED_RECORD_AUTHORITY"
)
CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS: Final = (
    "UNWIRED_NO_39_RECORD_NO_TRAINER_PREDICTION_PAPER_OR_LIVE_AUTHORITY"
)
CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS: Final = 15 * 60
CAUSAL_COST_ORDERED_FEATURE_NAMES: Final = (
    "fee_bps",
    "spread_bps",
    "expected_slippage_bps",
    "expected_funding_bps",
)

_DEPTH_SCHEMA = "direct_orderbook_depth_v1"
_FEATURES_SCHEMA = "direct_orderbook_features_v1"
_MARK_SCHEMA = "binance_usdm_mark_price_wss_v1"
_FEE_SOURCE_TRANSPORT = "DETACHED_SIGNED_BINANCE_USDM_COMMISSION_RESPONSE_UNWIRED"
_NOTIONAL_SOURCE_TRANSPORT = "DURABLE_CAUSAL_POLICY_LEDGER"
_CLOCK_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,511}$", re.ASCII)
_CONSTRUCTION_TOKEN = object()
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_JSON_BYTES = 2 * 1024 * 1024

_FEE_ARTIFACT_FIELDS = frozenset(
    {
        "schema_version",
        "capture_classification",
        "venue",
        "market",
        "symbol",
        "liquidity_role",
        "fee_semantics",
        "fee_unit",
        "taker_fee_bps_per_side",
        "effective_at",
        "available_at",
        "expires_at",
        "source_key",
        "authority_scope",
        "source_revision",
        "raw_response_sha256",
        "raw_response_byte_count",
        "raw_response_cas_address",
        "sanitized_request_identity_sha256",
        "credential_binding_fingerprint_sha256",
        "http_status",
        "request_method",
        "request_path",
        "response_observed_at",
        "rpi_commission_rate_decimal",
        "rpi_commission_bps",
    }
)
_FEE_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_kind",
        "artifact_payload_sha256",
        "artifact_payload_byte_count",
        "source_key",
        "source_schema_version",
        "source_transport",
        "symbol",
        "effective_at",
        "available_at",
        "expires_at",
        "authority_scope",
        "capture_classification",
        "raw_response_sha256",
        "raw_response_byte_count",
        "raw_response_cas_address",
        "sanitized_request_identity_sha256",
        "credential_binding_fingerprint_sha256",
        "http_status",
        "request_method",
        "request_path",
        "response_observed_at",
        "rpi_commission_rate_decimal",
        "rpi_commission_bps",
        "receipt_sha256",
    }
)
_NOTIONAL_ARTIFACT_FIELDS = frozenset(
    {
        "schema_version",
        "symbol",
        "feature_snapshot_identity",
        "value_unit",
        "expected_notional_usd",
        "policy_id",
        "policy_version",
        "policy_source_key",
        "effective_at",
        "available_at",
        "expires_at",
        "causality_scope",
        "fallback_used",
        "static_default_used",
    }
)
_NOTIONAL_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_kind",
        "artifact_payload_sha256",
        "artifact_payload_byte_count",
        "policy_source_key",
        "source_schema_version",
        "source_transport",
        "symbol",
        "feature_snapshot_identity",
        "effective_at",
        "available_at",
        "expires_at",
        "authority_scope",
        "receipt_sha256",
    }
)

_IMPLEMENTATION_CONTRACT: Final = {
    "schema_version": "causal_cost_implementation_contract_v1",
    "implementation_id": CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
    "source_inventory": [
        "v2:orderbook:depth:binance:{symbol}",
        "v2:orderbook:features:binance:{symbol}",
        "v2:market:mark_price:{symbol}",
        "authoritative_fee_schedule_artifact_and_receipt",
        "causal_expected_notional_policy_artifact_and_receipt",
    ],
    "holding_horizon_seconds": CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS,
    "ordered_outputs": list(CAUSAL_COST_ORDERED_FEATURE_NAMES),
    "output_encoding": "IEEE754_BINARY32_BIG_ENDIAN",
    "fee_formula": "authoritative_taker_fee_bps_per_side",
    "spread_formula": "(best_ask-best_bid)/mid*10000",
    "impact_formula": "max(adverse_buy_vwap_bps,adverse_sell_vwap_bps)_at_exact_notional",
    "funding_formula": (
        "raw_binance_stream_r_rate*10000_iff_next_funding_time_in_"
        "(decision_time,decision_time+900s]_else_zero"
    ),
    "funding_sign": "VENUE_RATE_SIGN_PRESERVED_NOT_POSITION_PNL_SIGN",
    "freshness": "EXPLICIT_SOURCE_EXPIRY_ONLY_NO_CONSUMER_AGE_THRESHOLD",
    "fallbacks": [],
    "authority": "NONE_AUDIT_ONLY",
}
CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256: Final = hashlib.sha256(
    json.dumps(
        _IMPLEMENTATION_CONTRACT,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
).hexdigest()


class CausalCostEvidenceV1Error(RuntimeError):
    """Base fail-closed causal-cost evidence error with a stable reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class CausalCostEvidenceV1ValidationError(CausalCostEvidenceV1Error):
    """An input is missing, stale, ambiguous, future, or semantically invalid."""


class CausalCostEvidenceV1IntegrityError(CausalCostEvidenceV1Error):
    """An atomic binding, hash, CAS object, or returned artifact was changed."""


@dataclass(frozen=True, slots=True)
class CausalCostEvidenceV1Result:
    """Factory-built audit artifact; every property performs fresh CAS readback."""

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
    _construction_token: object = field(repr=False, compare=False)

    @property
    def contract(self) -> dict[str, Any]:
        return _validated_result(self)

    @property
    def ordered_receipts(self) -> tuple[dict[str, Any], ...]:
        contract = _validated_result(self)
        return tuple(cast(dict[str, Any], item) for item in contract["ordered_receipts"])


def _validation(reason: str) -> NoReturn:
    raise CausalCostEvidenceV1ValidationError(reason) from None


def _integrity(reason: str) -> NoReturn:
    raise CausalCostEvidenceV1IntegrityError(reason) from None


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
    if not encoded or len(encoded) > _MAX_JSON_BYTES:
        _validation(reason)
    return encoded


def _sha256(value: object) -> str:
    encoded = _canonical_bytes(
        value,
        reason="CAUSAL_COST_CANONICAL_JSON_INVALID",
    )
    return hashlib.sha256(encoded).hexdigest()


def _parse_exact_json_bytes(payload: object, *, reason: str) -> dict[str, Any]:
    if type(payload) is not bytes or not payload or len(payload) > _MAX_JSON_BYTES:
        _validation(reason)

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                _validation(reason)
            out[key] = value
        return out

    def reject_constant(_: str) -> NoReturn:
        _validation(reason)

    try:
        parsed = json.loads(
            cast(bytes, payload).decode("ascii", errors="strict"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except CausalCostEvidenceV1Error:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeError, ValueError):
        _validation(reason)
    if type(parsed) is not dict:
        _validation(reason)
    if not hmac.compare_digest(
        _canonical_bytes(parsed, reason=reason),
        cast(bytes, payload),
    ):
        _validation(reason)
    return cast(dict[str, Any], parsed)


def _clock(value: object, *, reason: str) -> tuple[str, datetime]:
    if type(value) is not str or not value.endswith("Z") or value != value.strip():
        _validation(reason)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (OverflowError, ValueError):
        _validation(reason)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        _validation(reason)
    parsed = parsed.astimezone(UTC)
    if parsed <= _EPOCH:
        _validation(reason)
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z"), parsed


def _label(value: object, *, reason: str, pattern: re.Pattern[str] = _LABEL_RE) -> str:
    if type(value) is not str or value != value.strip() or pattern.fullmatch(value) is None:
        _validation(reason)
    return value


def _finite(
    value: object,
    *,
    reason: str,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    if type(value) not in {int, float}:
        _validation(reason)
    parsed = float(cast(int | float, value))
    if not math.isfinite(parsed):
        _validation(reason)
    if positive and parsed <= 0.0:
        _validation(reason)
    if nonnegative and parsed < 0.0:
        _validation(reason)
    if parsed == 0.0:
        parsed = 0.0
    return parsed


def _float32(value: object, *, reason: str) -> tuple[float, str]:
    parsed = _finite(value, reason=reason)
    try:
        packed = struct.pack("!f", parsed)
        resolved = float(struct.unpack("!f", packed)[0])
    except (OverflowError, struct.error):
        _validation(reason)
    if not math.isfinite(resolved) or (parsed != 0.0 and resolved == 0.0):
        _validation(reason)
    return (0.0 if resolved == 0.0 else resolved), packed.hex()


def _numbers_equal(left: object, right: object) -> bool:
    if type(left) not in {int, float} or type(right) not in {int, float}:
        return False
    left_value = float(cast(int | float, left))
    right_value = float(cast(int | float, right))
    return bool(
        math.isfinite(left_value)
        and math.isfinite(right_value)
        and math.isclose(left_value, right_value, rel_tol=1e-12, abs_tol=1e-12)
    )


def _address_mapping(address: SourcePayloadAddress) -> dict[str, Any]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _put_exact(
    store: ImmutableSourcePayloadStore,
    payload: bytes,
    *,
    failure_reason: str,
) -> SourcePayloadAddress:
    digest = hashlib.sha256(payload).hexdigest()
    try:
        address = store.put(payload, expected_sha256=digest, expected_byte_count=len(payload))
        readback = store.get(digest, expected_byte_count=len(payload))
    except SourcePayloadStoreError as exc:
        raise CausalCostEvidenceV1IntegrityError(failure_reason) from exc
    if (
        address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or address.payload_sha256 != digest
        or address.payload_byte_count != len(payload)
        or not hmac.compare_digest(readback, payload)
    ):
        _integrity(failure_reason)
    return address


def _self_hashed_receipt(
    value: object,
    *,
    fields: frozenset[str],
    reason: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _validation(reason)
    detached = dict(value)
    if frozenset(detached) != fields:
        _validation(reason)
    supplied = detached.pop("receipt_sha256", None)
    if type(supplied) is not str or _SHA256_RE.fullmatch(supplied) is None:
        _validation(reason)
    if not hmac.compare_digest(supplied, _sha256(detached)):
        _validation(reason)
    return {**detached, "receipt_sha256": supplied}


def _module_code_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise CausalCostEvidenceV1IntegrityError(
            "CAUSAL_COST_IMPLEMENTATION_BYTES_UNAVAILABLE"
        ) from exc


def _expected_atomic_batch_material(batch: AtomicRedisSourceReadBatch) -> str:
    material = {
        "consumer_eligible": False,
        "downstream_status": ATOMIC_REDIS_SOURCE_READ_DOWNSTREAM_STATUS,
        "evidence_classification": ATOMIC_REDIS_SOURCE_READ_EVIDENCE_CLASSIFICATION,
        "ledger_receipt_emitted": False,
        "live_execution_authorized": False,
        "paper_provenance_only": True,
        "read_only": True,
        "redis_payload_read_operation": "GETRANGE_INCLUSIVE_CAP_PLUS_ONE",
        "redis_transaction_command_order_per_key": ["TYPE", "GETRANGE", "PTTL"],
        "max_aggregate_payload_bytes": MAX_AGGREGATE_PAYLOAD_BYTES,
        "max_batch_materialized_payload_bytes": MAX_BATCH_MATERIALIZED_PAYLOAD_BYTES,
        "max_range_reply_bytes": MAX_RANGE_REPLY_BYTES,
        "max_source_keys_per_batch": MAX_SOURCE_KEYS_PER_BATCH,
        "max_source_payload_bytes": MAX_SOURCE_PAYLOAD_BYTES,
        "results": [
            {
                "consumer_eligible": result.consumer_eligible,
                "ledger_receipt_emitted": result.ledger_receipt_emitted,
                "live_execution_authorized": result.live_execution_authorized,
                "payload_byte_count": result.payload_byte_count,
                "payload_sha256": result.payload_sha256,
                "paper_provenance_only": result.paper_provenance_only,
                "present": result.present,
                "pttl_ms": result.pttl_ms,
                "read_only": result.read_only,
                "redis_type": result.redis_type,
                "schema_version": result.schema_version,
                "server_time_clock_semantics": result.server_time_clock_semantics,
                "server_time_is_consumer_observed_at": result.server_time_is_consumer_observed_at,
                "source_finality_attested": result.source_finality_attested,
                "source_key": result.source_key,
                "source_key_sha256": result.source_key_sha256,
                "source_schema_attested": result.source_schema_attested,
                "transport_authenticity_attested": result.transport_authenticity_attested,
            }
            for result in batch.results
        ],
        "schema_version": ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION,
        "server_observed_at": batch.server_observed_at,
        "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
        "server_time_is_consumer_observed_at": False,
        "server_time_microseconds": batch.server_time_microseconds,
        "server_time_seconds": batch.server_time_seconds,
        "source_finality_attested": False,
        "source_schema_attested": False,
        "total_payload_byte_count": batch.total_payload_byte_count,
        "transport_authenticity_attested": False,
    }
    return json.dumps(
        material,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _validated_atomic_sources(
    *,
    atomic_capture: object,
    store: ImmutableSourcePayloadStore,
    symbol: str,
    decision_at: datetime,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    tuple[tuple[SourcePayloadAddress, bytes], ...],
]:
    if type(atomic_capture) is not AtomicRedisSourceReadBatch:
        _validation("CAUSAL_COST_ATOMIC_CAPTURE_TYPE_INVALID")
    batch = cast(AtomicRedisSourceReadBatch, atomic_capture)
    expected_keys = (
        f"v2:orderbook:depth:binance:{symbol}",
        f"v2:orderbook:features:binance:{symbol}",
        f"v2:market:mark_price:{symbol}",
    )
    if (
        batch.schema_version != ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION
        or type(batch.results) is not tuple
        or len(batch.results) != len(expected_keys)
        or any(type(result) is not AtomicRedisSourceResult for result in batch.results)
    ):
        _integrity("CAUSAL_COST_ATOMIC_CAPTURE_SHAPE_INVALID")

    try:
        server_at = _EPOCH + timedelta(
            seconds=batch.server_time_seconds,
            microseconds=batch.server_time_microseconds,
        )
    except (OverflowError, TypeError, ValueError):
        _integrity("CAUSAL_COST_ATOMIC_SERVER_CLOCK_INVALID")
    server_iso = server_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if server_iso != batch.server_observed_at or server_at > decision_at:
        _validation("CAUSAL_COST_ATOMIC_CAPTURE_AFTER_DECISION")

    expected_material = _expected_atomic_batch_material(batch)
    expected_material_sha256 = hashlib.sha256(expected_material.encode("ascii")).hexdigest()
    if (
        batch.batch_material_json != expected_material
        or batch.batch_material_sha256 != expected_material_sha256
        or batch.batch_id != f"trainer_atomic_redis_source_read_v2_{expected_material_sha256}"
    ):
        _integrity("CAUSAL_COST_ATOMIC_CAPTURE_BINDING_INVALID")

    elapsed_ms = math.ceil((decision_at - server_at).total_seconds() * 1000.0)
    payloads: dict[str, dict[str, Any]] = {}
    source_evidence: dict[str, dict[str, Any]] = {}
    exact_objects: list[tuple[SourcePayloadAddress, bytes]] = []
    total_bytes = 0
    for role, expected_key, result in zip(
        ("orderbook_depth", "orderbook_features", "mark_price"),
        expected_keys,
        batch.results,
        strict=True,
    ):
        payload = result.exact_payload_bytes
        if (
            result.schema_version != ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION
            or result.source_key != expected_key
            or result.source_key_sha256
            != hashlib.sha256(expected_key.encode("ascii")).hexdigest()
        ):
            _integrity("CAUSAL_COST_ATOMIC_SOURCE_KEY_BINDING_INVALID")
        if (
            result.redis_type != "string"
            or result.present is not True
            or type(payload) is not bytes
            or not payload
        ):
            _validation(f"CAUSAL_COST_{role.upper()}_SOURCE_MISSING")
        payload = cast(bytes, payload)
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        if (
            result.payload_sha256 != payload_sha256
            or result.payload_byte_count != len(payload)
            or result.server_observed_at != batch.server_observed_at
        ):
            _integrity("CAUSAL_COST_ATOMIC_SOURCE_PAYLOAD_BINDING_INVALID")
        if type(result.pttl_ms) is not int or result.pttl_ms <= 0:
            _validation(f"CAUSAL_COST_{role.upper()}_PERSISTED_EXPIRY_MISSING")
        if elapsed_ms >= result.pttl_ms:
            _validation(f"CAUSAL_COST_{role.upper()}_SOURCE_EXPIRED_AT_DECISION")
        if any(
            (
                result.read_only is not True,
                result.paper_provenance_only is not True,
                result.live_execution_authorized is not False,
                result.source_schema_attested is not False,
                result.source_finality_attested is not False,
                result.ledger_receipt_emitted is not False,
                result.consumer_eligible is not False,
                result.transport_authenticity_attested is not False,
                result.server_time_is_consumer_observed_at is not False,
                result.server_time_clock_semantics != REDIS_TIME_CLOCK_SEMANTICS,
            )
        ):
            _integrity("CAUSAL_COST_ATOMIC_SOURCE_FIXED_CONTRACT_INVALID")
        parsed = _parse_exact_json_bytes(
            payload,
            reason=f"CAUSAL_COST_{role.upper()}_SOURCE_JSON_INVALID",
        )
        address = _put_exact(
            store,
            payload,
            failure_reason=f"CAUSAL_COST_{role.upper()}_SOURCE_CAS_FAILED",
        )
        projected_expiry_at = server_at + timedelta(milliseconds=result.pttl_ms)
        payloads[role] = parsed
        source_evidence[role] = {
            "source_key": expected_key,
            "source_key_sha256": result.source_key_sha256,
            "payload_sha256": payload_sha256,
            "payload_byte_count": len(payload),
            "payload_cas_address": _address_mapping(address),
            "atomic_batch_id": batch.batch_id,
            "atomic_batch_material_sha256": batch.batch_material_sha256,
            "atomic_server_observed_at": server_iso,
            "redis_pttl_ms": result.pttl_ms,
            "redis_pttl_expiry_projection_at": projected_expiry_at.isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
            "expiry_evidence_kind": "REDIS_PTTL_IN_SAME_ATOMIC_READ_TRANSACTION",
            "decision_within_persisted_expiry_evidence": True,
            "consumer_static_age_threshold_applied": False,
        }
        exact_objects.append((address, payload))
        total_bytes += len(payload)
    if total_bytes != batch.total_payload_byte_count:
        _integrity("CAUSAL_COST_ATOMIC_TOTAL_PAYLOAD_BYTES_INVALID")
    return payloads, source_evidence, tuple(exact_objects)


def _source_clock_chain(
    payload: Mapping[str, Any],
    *,
    role: str,
    decision_at: datetime,
    atomic_server_at: datetime,
) -> dict[str, str]:
    clocks: dict[str, str] = {}
    parsed: dict[str, datetime] = {}
    for name in ("event_time", "received_at", "available_at", "generated_at"):
        clocks[name], parsed[name] = _clock(
            payload.get(name),
            reason=f"CAUSAL_COST_{role.upper()}_{name.upper()}_INVALID",
        )
    if not (
        parsed["event_time"]
        <= parsed["received_at"]
        <= parsed["available_at"]
        <= parsed["generated_at"]
        <= atomic_server_at
        <= decision_at
    ):
        _validation(f"CAUSAL_COST_{role.upper()}_CLOCK_ORDER_INVALID")
    return clocks


def _levels(value: object, *, side: str) -> tuple[tuple[float, float], ...]:
    if type(value) is not list or not 1 <= len(cast(list[object], value)) <= 500:
        _validation(f"CAUSAL_COST_ORDERBOOK_{side.upper()}_LEVELS_INVALID")
    resolved: list[tuple[float, float]] = []
    for row in cast(list[object], value):
        if type(row) is not dict or frozenset(cast(dict[str, Any], row)) != {
            "price",
            "quantity",
        }:
            _validation(f"CAUSAL_COST_ORDERBOOK_{side.upper()}_LEVEL_INVALID")
        typed = cast(dict[str, Any], row)
        price = _finite(
            typed.get("price"),
            reason=f"CAUSAL_COST_ORDERBOOK_{side.upper()}_PRICE_INVALID",
            positive=True,
        )
        quantity = _finite(
            typed.get("quantity"),
            reason=f"CAUSAL_COST_ORDERBOOK_{side.upper()}_QUANTITY_INVALID",
            positive=True,
        )
        resolved.append((price, quantity))
    prices = [price for price, _ in resolved]
    expected = sorted(prices, reverse=side == "bids")
    if prices != expected or len(set(prices)) != len(prices):
        _validation(f"CAUSAL_COST_ORDERBOOK_{side.upper()}_ORDER_INVALID")
    return tuple(resolved)


def _depth_usd(levels: Sequence[tuple[float, float]], count: int) -> float:
    return float(sum(price * quantity for price, quantity in levels[:count]))


def _walk_adverse_bps(
    levels: Sequence[tuple[float, float]],
    *,
    notional_usd: float,
    mid: float,
    side: str,
) -> float:
    remaining = notional_usd
    cost = 0.0
    quantity = 0.0
    for price, available_quantity in levels:
        level_notional = price * available_quantity
        take = min(remaining, level_notional)
        cost += take
        quantity += take / price
        remaining -= take
        if remaining <= 1e-9:
            break
    if remaining > 1e-6 or quantity <= 0.0:
        _validation(f"CAUSAL_COST_ORDERBOOK_{side.upper()}_NOTIONAL_DEPTH_INSUFFICIENT")
    vwap = cost / quantity
    adverse = (vwap - mid) if side == "buy" else (mid - vwap)
    if adverse < -1e-12:
        _validation(f"CAUSAL_COST_ORDERBOOK_{side.upper()}_VWAP_DIRECTION_INVALID")
    return max(0.0, adverse) / mid * 10_000.0


def _validate_sequence_value(value: object, *, reason: str) -> int:
    if type(value) is not int or value <= 0:
        _validation(reason)
    return value


def _validate_orderbook_sources(
    *,
    depth: Mapping[str, Any],
    features: Mapping[str, Any],
    evidence: dict[str, dict[str, Any]],
    symbol: str,
    decision_at: datetime,
    expected_notional_usd: float,
) -> tuple[float, float, dict[str, Any]]:
    atomic_server_iso = evidence["orderbook_depth"]["atomic_server_observed_at"]
    _, atomic_server_at = _clock(
        atomic_server_iso,
        reason="CAUSAL_COST_ATOMIC_SERVER_CLOCK_INVALID",
    )
    required_literals = {
        "schema_version": _DEPTH_SCHEMA,
        "source": "direct_binance",
        "exchange": "binance",
        "symbol": symbol,
    }
    if any(depth.get(key) != value for key, value in required_literals.items()):
        _validation("CAUSAL_COST_ORDERBOOK_DEPTH_SOURCE_IDENTITY_INVALID")
    feature_literals = {**required_literals, "schema_version": _FEATURES_SCHEMA}
    if any(features.get(key) != value for key, value in feature_literals.items()):
        _validation("CAUSAL_COST_ORDERBOOK_FEATURE_SOURCE_IDENTITY_INVALID")
    allowed_update_types = {"book_ticker", "partial_depth", "diff_depth"}
    if depth.get("update_type") not in allowed_update_types:
        _validation("CAUSAL_COST_ORDERBOOK_TRANSPORT_NOT_DIRECT_WEBSOCKET")
    if features.get("update_type") != depth.get("update_type"):
        _validation("CAUSAL_COST_ORDERBOOK_UPDATE_TYPE_MISMATCH")
    for payload, role in ((depth, "orderbook_depth"), (features, "orderbook_features")):
        if payload.get("sequence_gap") is not False:
            _validation(f"CAUSAL_COST_{role.upper()}_SEQUENCE_GAP")
        gap_flag = payload.get("sequence_gap_flag")
        if type(gap_flag) not in {int, float} or float(cast(int | float, gap_flag)) != 0.0:
            _validation(f"CAUSAL_COST_{role.upper()}_SEQUENCE_GAP_FLAG_INVALID")
    sequence_id = _validate_sequence_value(
        depth.get("sequence_id"),
        reason="CAUSAL_COST_ORDERBOOK_SEQUENCE_ID_INVALID",
    )
    if features.get("sequence_id") != sequence_id:
        _validation("CAUSAL_COST_ORDERBOOK_SEQUENCE_ID_MISMATCH")
    for name in (
        "previous_sequence_id",
        "update_type",
        "depth_level",
        "feed_speed_ms",
        "event_time",
        "transaction_time",
        "received_at",
        "available_at",
        "generated_at",
    ):
        if features.get(name) != depth.get(name):
            _validation(f"CAUSAL_COST_ORDERBOOK_PAIR_{name.upper()}_MISMATCH")
    depth_clocks = _source_clock_chain(
        depth,
        role="orderbook_depth",
        decision_at=decision_at,
        atomic_server_at=atomic_server_at,
    )
    feature_clocks = _source_clock_chain(
        features,
        role="orderbook_features",
        decision_at=decision_at,
        atomic_server_at=atomic_server_at,
    )
    if depth_clocks != feature_clocks:
        _validation("CAUSAL_COST_ORDERBOOK_CLOCK_PAIR_MISMATCH")

    bids = _levels(depth.get("bids"), side="bids")
    asks = _levels(depth.get("asks"), side="asks")
    best_bid = bids[0][0]
    best_ask = asks[0][0]
    if best_ask <= best_bid:
        _validation("CAUSAL_COST_ORDERBOOK_CROSSED_OR_ZERO_SPREAD")
    mid = (best_bid + best_ask) / 2.0
    full_spread_bps = (best_ask - best_bid) / mid * 10_000.0
    derived_claims = {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "best_bid_size": bids[0][1],
        "best_ask_size": asks[0][1],
        "bid": best_bid,
        "ask": best_ask,
        "bid_size": bids[0][1],
        "ask_size": asks[0][1],
        "mid": mid,
        "bid_ask_mid": mid,
        "spread_bps": full_spread_bps,
        "depth_5_bid_usd": _depth_usd(bids, 5),
        "depth_5_ask_usd": _depth_usd(asks, 5),
        "depth_20_bid_usd": _depth_usd(bids, 20),
        "depth_20_ask_usd": _depth_usd(asks, 20),
        "depth_50_bid_usd": _depth_usd(bids, 50),
        "depth_50_ask_usd": _depth_usd(asks, 50),
        "depth_500_bid_usd": _depth_usd(bids, 500),
        "depth_500_ask_usd": _depth_usd(asks, 500),
    }
    for name, expected in derived_claims.items():
        if not _numbers_equal(features.get(name), expected):
            _validation(f"CAUSAL_COST_ORDERBOOK_FEATURE_{name.upper()}_SUBSTITUTION")
        if name in depth and not _numbers_equal(depth.get(name), expected):
            _validation(f"CAUSAL_COST_ORDERBOOK_DEPTH_{name.upper()}_SUBSTITUTION")
    if features.get("bid_levels") not in (None, len(bids)) or features.get("ask_levels") not in (
        None,
        len(asks),
    ):
        _validation("CAUSAL_COST_ORDERBOOK_LEVEL_COUNT_MISMATCH")
    if depth.get("bid_levels") != len(bids) or depth.get("ask_levels") != len(asks):
        _validation("CAUSAL_COST_ORDERBOOK_DEPTH_LEVEL_COUNT_MISMATCH")

    reference_notional = _finite(
        features.get("price_impact_notional_usd"),
        reason="CAUSAL_COST_ORDERBOOK_FEATURE_REFERENCE_NOTIONAL_INVALID",
        positive=True,
    )
    reference_buy = _walk_adverse_bps(
        asks,
        notional_usd=reference_notional,
        mid=mid,
        side="buy",
    )
    reference_sell = _walk_adverse_bps(
        bids,
        notional_usd=reference_notional,
        mid=mid,
        side="sell",
    )
    if not _numbers_equal(
        features.get("estimated_price_impact_bps"),
        max(reference_buy, reference_sell),
    ):
        _validation("CAUSAL_COST_ORDERBOOK_FEATURE_IMPACT_SUBSTITUTION")
    expected_buy = _walk_adverse_bps(
        asks,
        notional_usd=expected_notional_usd,
        mid=mid,
        side="buy",
    )
    expected_sell = _walk_adverse_bps(
        bids,
        notional_usd=expected_notional_usd,
        mid=mid,
        side="sell",
    )
    expected_impact = max(expected_buy, expected_sell)
    evidence["orderbook_depth"].update(
        {
            "source_schema_version": _DEPTH_SCHEMA,
            "source_transport": "DIRECT_BINANCE_PUBLIC_WEBSOCKET_RECORDER",
            "source_sequence_id": sequence_id,
            "source_sequence_gap": False,
            "clocks": depth_clocks,
        }
    )
    evidence["orderbook_features"].update(
        {
            "source_schema_version": _FEATURES_SCHEMA,
            "source_transport": "DIRECT_BINANCE_PUBLIC_WEBSOCKET_RECORDER",
            "source_sequence_id": sequence_id,
            "source_sequence_gap": False,
            "clocks": feature_clocks,
        }
    )
    derivation = {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "full_spread_bps_float64_hex": full_spread_bps.hex(),
        "expected_notional_usd": expected_notional_usd,
        "adverse_buy_vwap_impact_bps_float64_hex": expected_buy.hex(),
        "adverse_sell_vwap_impact_bps_float64_hex": expected_sell.hex(),
        "selected_side_agnostic_impact": "MAX_OF_BUY_AND_SELL_ADVERSE_VWAP_BPS",
        "expected_impact_per_side_bps_float64_hex": expected_impact.hex(),
    }
    return full_spread_bps, expected_impact, derivation


def _funding_time_ms(value: object) -> int:
    if type(value) is int:
        parsed = value
    elif type(value) is str and value.isascii() and value.isdigit():
        parsed = int(value)
    else:
        _validation("CAUSAL_COST_FUNDING_NEXT_SETTLEMENT_INVALID")
    if parsed <= 0:
        _validation("CAUSAL_COST_FUNDING_NEXT_SETTLEMENT_INVALID")
    return parsed


def _validate_mark_source(
    *,
    mark: Mapping[str, Any],
    evidence: dict[str, dict[str, Any]],
    symbol: str,
    decision_at: datetime,
) -> tuple[float, dict[str, Any]]:
    expected_literals = {
        "schema_version": _MARK_SCHEMA,
        "symbol": symbol,
        "source": "binance_usdm_wss_mark_price_all_symbols",
        "transport": "websocket_primary",
    }
    if any(mark.get(name) != value for name, value in expected_literals.items()):
        _validation("CAUSAL_COST_MARK_SOURCE_IDENTITY_OR_TRANSPORT_INVALID")
    _, atomic_server_at = _clock(
        evidence["mark_price"]["atomic_server_observed_at"],
        reason="CAUSAL_COST_ATOMIC_SERVER_CLOCK_INVALID",
    )
    clocks = _source_clock_chain(
        mark,
        role="mark_price",
        decision_at=decision_at,
        atomic_server_at=atomic_server_at,
    )
    mark_price = _finite(
        mark.get("mark_price"),
        reason="CAUSAL_COST_MARK_PRICE_INVALID",
        positive=True,
    )
    if not _numbers_equal(mark.get("markPrice"), mark_price):
        _validation("CAUSAL_COST_MARK_PRICE_ALIAS_CONFLICT")
    rate = _finite(
        mark.get("last_funding_rate"),
        reason="CAUSAL_COST_FUNDING_RATE_MISSING_OR_NONFINITE",
    )
    if rate == 0.0 and math.copysign(1.0, float(mark.get("last_funding_rate"))) < 0.0:
        _validation("CAUSAL_COST_FUNDING_RATE_NEGATIVE_ZERO_AMBIGUOUS")
    next_ms = _funding_time_ms(mark.get("next_funding_time_ms"))
    try:
        next_at = _EPOCH + timedelta(milliseconds=next_ms)
    except (OverflowError, ValueError):
        _validation("CAUSAL_COST_FUNDING_NEXT_SETTLEMENT_INVALID")
    horizon_end = decision_at + timedelta(seconds=CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS)
    if next_at <= decision_at:
        _validation("CAUSAL_COST_FUNDING_NEXT_SETTLEMENT_NOT_PROSPECTIVE")
    settlement_in_horizon = next_at <= horizon_end
    signed_bps = rate * 10_000.0 if settlement_in_horizon else 0.0
    evidence["mark_price"].update(
        {
            "source_schema_version": _MARK_SCHEMA,
            "source_transport": "BINANCE_USDM_PUBLIC_MARK_PRICE_WEBSOCKET",
            "source_sequence_id": None,
            "source_sequence_gap": False,
            "clocks": clocks,
        }
    )
    derivation = {
        "raw_binance_funding_rate_float64_hex": rate.hex(),
        "raw_rate_unit": "DECIMAL_RATE_PER_SETTLEMENT_NOT_PERCENT_NOT_BPS",
        "bps_conversion": "RAW_DECIMAL_RATE_MULTIPLIED_BY_10000",
        "sign_semantics": "VENUE_RATE_SIGN_PRESERVED_NOT_POSITION_PNL_SIGN",
        "next_funding_time_ms": next_ms,
        "next_funding_time": next_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "settlement_interval": "(decision_time,decision_time_plus_900_seconds]",
        "settlement_in_horizon": settlement_in_horizon,
        "zero_semantics": (
            "NEXT_SETTLEMENT_PROVEN_OUTSIDE_PINNED_HORIZON"
            if not settlement_in_horizon
            else "SOURCE_RATE_WAS_EXACT_ZERO"
            if rate == 0.0
            else "NOT_ZERO"
        ),
        "signed_expected_funding_bps_float64_hex": signed_bps.hex(),
    }
    return signed_bps, derivation


def _parse_detached_response_bytes(payload: object) -> dict[str, Any]:
    if type(payload) is not bytes or not payload or len(payload) > _MAX_JSON_BYTES:
        _validation("CAUSAL_COST_FEE_RAW_RESPONSE_BYTES_INVALID")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                _validation("CAUSAL_COST_FEE_RAW_RESPONSE_JSON_INVALID")
            out[key] = value
        return out

    def reject_constant(_: str) -> NoReturn:
        _validation("CAUSAL_COST_FEE_RAW_RESPONSE_JSON_INVALID")

    try:
        parsed = json.loads(
            cast(bytes, payload).decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except CausalCostEvidenceV1Error:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeError, ValueError):
        _validation("CAUSAL_COST_FEE_RAW_RESPONSE_JSON_INVALID")
    if type(parsed) is not dict:
        _validation("CAUSAL_COST_FEE_RAW_RESPONSE_JSON_INVALID")
    return cast(dict[str, Any], parsed)


def _decimal_rate_to_bps(value: object, *, reason: str) -> float:
    if type(value) is not str or not value or value != value.strip():
        _validation(reason)
    try:
        parsed = float(value)
    except ValueError:
        _validation(reason)
    if not math.isfinite(parsed) or parsed < 0.0:
        _validation(reason)
    return parsed * 10_000.0


def _validate_fee_evidence(
    *,
    store: ImmutableSourcePayloadStore,
    artifact_bytes: object,
    raw_response_bytes: object,
    receipt: object,
    symbol: str,
    decision_at: datetime,
) -> tuple[
    float,
    dict[str, Any],
    dict[str, Any],
    tuple[tuple[SourcePayloadAddress, bytes], ...],
]:
    if type(raw_response_bytes) is not bytes:
        _validation("CAUSAL_COST_FEE_RAW_RESPONSE_BYTES_INVALID")
    raw_bytes = cast(bytes, raw_response_bytes)
    raw_payload = _parse_detached_response_bytes(raw_bytes)
    raw_address = _put_exact(
        store,
        raw_bytes,
        failure_reason="CAUSAL_COST_FEE_RAW_RESPONSE_CAS_FAILED",
    )
    if type(artifact_bytes) is not bytes:
        _validation("CAUSAL_COST_FEE_ARTIFACT_BYTES_INVALID")
    typed_artifact_bytes = cast(bytes, artifact_bytes)
    artifact = _parse_exact_json_bytes(
        typed_artifact_bytes,
        reason="CAUSAL_COST_FEE_ARTIFACT_JSON_INVALID",
    )
    if frozenset(artifact) != _FEE_ARTIFACT_FIELDS:
        _validation("CAUSAL_COST_FEE_ARTIFACT_FIELDS_INVALID")
    classification = "STRUCTURALLY_VALIDATED_DETACHED_SIGNED_COMMISSION_RESPONSE_UNWIRED"
    expected_literals = {
        "schema_version": CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
        "capture_classification": classification,
        "venue": "BINANCE",
        "market": "USD_M_PERPETUAL",
        "symbol": symbol,
        "liquidity_role": "TAKER",
        "fee_semantics": "PER_SIDE_EXECUTION_FEE_NOT_ROUND_TRIP",
        "fee_unit": "BASIS_POINTS",
        "source_key": f"v2:account:fee_schedule:{symbol}",
        "authority_scope": "BINANCE_USDM_ACCOUNT_COMMISSION_RATE",
        "http_status": 200,
        "request_method": "GET",
        "request_path": "/fapi/v1/commissionRate",
    }
    if any(artifact.get(name) != value for name, value in expected_literals.items()):
        _validation("CAUSAL_COST_FEE_ARTIFACT_IDENTITY_INVALID")
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if (
        artifact.get("source_revision") != raw_sha256
        or artifact.get("raw_response_sha256") != raw_sha256
        or artifact.get("raw_response_byte_count") != len(raw_bytes)
        or artifact.get("raw_response_cas_address") != _address_mapping(raw_address)
    ):
        _validation("CAUSAL_COST_FEE_RAW_RESPONSE_BINDING_INVALID")
    for name in (
        "source_revision",
        "sanitized_request_identity_sha256",
        "credential_binding_fingerprint_sha256",
    ):
        if type(artifact.get(name)) is not str or _SHA256_RE.fullmatch(
            cast(str, artifact.get(name))
        ) is None:
            _validation(f"CAUSAL_COST_FEE_{name.upper()}_INVALID")
    if raw_payload.get("symbol") != symbol:
        _validation("CAUSAL_COST_FEE_RAW_RESPONSE_SYMBOL_INVALID")
    if frozenset(raw_payload) != {
        "symbol",
        "makerCommissionRate",
        "takerCommissionRate",
        "rpiCommissionRate",
    }:
        _validation("CAUSAL_COST_FEE_RAW_RESPONSE_FIELDS_INVALID")
    taker_bps = _decimal_rate_to_bps(
        raw_payload.get("takerCommissionRate"),
        reason="CAUSAL_COST_FEE_RAW_TAKER_RATE_INVALID",
    )
    _decimal_rate_to_bps(
        raw_payload.get("makerCommissionRate"),
        reason="CAUSAL_COST_FEE_RAW_MAKER_RATE_INVALID",
    )
    rpi_rate_decimal = raw_payload.get("rpiCommissionRate")
    rpi_bps = _decimal_rate_to_bps(
        rpi_rate_decimal,
        reason="CAUSAL_COST_FEE_RAW_RPI_RATE_INVALID",
    )
    if (
        artifact.get("rpi_commission_rate_decimal") != rpi_rate_decimal
        or not _numbers_equal(artifact.get("rpi_commission_bps"), rpi_bps)
    ):
        _validation("CAUSAL_COST_FEE_RPI_RATE_SUBSTITUTION")
    artifact_fee = _finite(
        artifact.get("taker_fee_bps_per_side"),
        reason="CAUSAL_COST_FEE_PER_SIDE_VALUE_INVALID",
        nonnegative=True,
    )
    if not _numbers_equal(artifact_fee, taker_bps):
        _validation("CAUSAL_COST_FEE_CALLER_SCALAR_SUBSTITUTION")
    effective_iso, effective_at = _clock(
        artifact.get("effective_at"), reason="CAUSAL_COST_FEE_EFFECTIVE_AT_INVALID"
    )
    observed_iso, observed_at = _clock(
        artifact.get("response_observed_at"),
        reason="CAUSAL_COST_FEE_RESPONSE_OBSERVED_AT_INVALID",
    )
    available_iso, available_at = _clock(
        artifact.get("available_at"), reason="CAUSAL_COST_FEE_AVAILABLE_AT_INVALID"
    )
    expires_iso, expires_at = _clock(
        artifact.get("expires_at"), reason="CAUSAL_COST_FEE_EXPIRES_AT_INVALID"
    )
    if effective_at != available_at or not observed_at <= available_at <= decision_at < expires_at:
        _validation("CAUSAL_COST_FEE_CLOCK_OR_EXPIRY_INVALID")

    artifact_address = _put_exact(
        store,
        typed_artifact_bytes,
        failure_reason="CAUSAL_COST_FEE_ARTIFACT_CAS_FAILED",
    )
    validated_receipt = _self_hashed_receipt(
        receipt,
        fields=_FEE_RECEIPT_FIELDS,
        reason="CAUSAL_COST_FEE_RECEIPT_INVALID",
    )
    expected_receipt = {
        "schema_version": CAUSAL_COST_FEE_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "DIRECT_READ",
        "artifact_payload_sha256": artifact_address.payload_sha256,
        "artifact_payload_byte_count": artifact_address.payload_byte_count,
        "source_key": expected_literals["source_key"],
        "source_schema_version": CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
        "source_transport": _FEE_SOURCE_TRANSPORT,
        "symbol": symbol,
        "effective_at": effective_iso,
        "available_at": available_iso,
        "expires_at": expires_iso,
        "authority_scope": expected_literals["authority_scope"],
        "capture_classification": classification,
        "raw_response_sha256": raw_sha256,
        "raw_response_byte_count": len(raw_bytes),
        "raw_response_cas_address": _address_mapping(raw_address),
        "sanitized_request_identity_sha256": artifact[
            "sanitized_request_identity_sha256"
        ],
        "credential_binding_fingerprint_sha256": artifact[
            "credential_binding_fingerprint_sha256"
        ],
        "http_status": 200,
        "request_method": "GET",
        "request_path": "/fapi/v1/commissionRate",
        "response_observed_at": observed_iso,
        "rpi_commission_rate_decimal": rpi_rate_decimal,
        "rpi_commission_bps": rpi_bps,
    }
    if any(validated_receipt.get(name) != value for name, value in expected_receipt.items()):
        _validation("CAUSAL_COST_FEE_RECEIPT_ARTIFACT_BINDING_INVALID")
    receipt_bytes = _canonical_bytes(
        validated_receipt,
        reason="CAUSAL_COST_FEE_RECEIPT_JSON_INVALID",
    )
    receipt_address = _put_exact(
        store,
        receipt_bytes,
        failure_reason="CAUSAL_COST_FEE_RECEIPT_CAS_FAILED",
    )
    source = {
        "source_key": expected_literals["source_key"],
        "source_schema_version": CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
        "source_transport": _FEE_SOURCE_TRANSPORT,
        "capture_classification": classification,
        "artifact_payload_sha256": artifact_address.payload_sha256,
        "artifact_payload_byte_count": artifact_address.payload_byte_count,
        "artifact_cas_address": _address_mapping(artifact_address),
        "input_receipt_sha256": validated_receipt["receipt_sha256"],
        "input_receipt_cas_address": _address_mapping(receipt_address),
        "raw_response_sha256": raw_sha256,
        "raw_response_byte_count": len(raw_bytes),
        "raw_response_cas_address": _address_mapping(raw_address),
        "effective_at": effective_iso,
        "response_observed_at": observed_iso,
        "available_at": available_iso,
        "expires_at": expires_iso,
        "fee_semantics": expected_literals["fee_semantics"],
        "fee_unit": "BASIS_POINTS",
        "rpi_commission_rate_decimal": rpi_rate_decimal,
        "rpi_commission_bps": rpi_bps,
        "rpi_rate_used_for_cost_scalar": False,
        "fallback_used": False,
    }
    return (
        artifact_fee,
        source,
        validated_receipt,
        (
            (raw_address, raw_bytes),
            (artifact_address, typed_artifact_bytes),
            (receipt_address, receipt_bytes),
        ),
    )


def _validate_notional_evidence(
    *,
    store: ImmutableSourcePayloadStore,
    artifact_bytes: object,
    receipt: object,
    expected_notional_usd: float,
    symbol: str,
    feature_snapshot_identity: str,
    decision_at: datetime,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    tuple[tuple[SourcePayloadAddress, bytes], ...],
]:
    if type(artifact_bytes) is not bytes:
        _validation("CAUSAL_COST_NOTIONAL_ARTIFACT_BYTES_INVALID")
    typed_artifact_bytes = cast(bytes, artifact_bytes)
    artifact = _parse_exact_json_bytes(
        typed_artifact_bytes,
        reason="CAUSAL_COST_NOTIONAL_ARTIFACT_JSON_INVALID",
    )
    if frozenset(artifact) != _NOTIONAL_ARTIFACT_FIELDS:
        _validation("CAUSAL_COST_NOTIONAL_ARTIFACT_FIELDS_INVALID")
    expected_literals = {
        "schema_version": CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
        "symbol": symbol,
        "feature_snapshot_identity": feature_snapshot_identity,
        "value_unit": "USD",
        "causality_scope": "FEATURE_SNAPSHOT_DECISION_EXPECTED_EXECUTION_NOTIONAL",
        "fallback_used": False,
        "static_default_used": False,
    }
    if any(artifact.get(name) != value for name, value in expected_literals.items()):
        _validation("CAUSAL_COST_NOTIONAL_ARTIFACT_IDENTITY_INVALID")
    artifact_notional = _finite(
        artifact.get("expected_notional_usd"),
        reason="CAUSAL_COST_NOTIONAL_ARTIFACT_VALUE_INVALID",
        positive=True,
    )
    if artifact_notional != expected_notional_usd:
        _validation("CAUSAL_COST_NOTIONAL_CALLER_VALUE_SUBSTITUTION")
    policy_id = _label(
        artifact.get("policy_id"), reason="CAUSAL_COST_NOTIONAL_POLICY_ID_INVALID"
    )
    policy_version = _label(
        artifact.get("policy_version"),
        reason="CAUSAL_COST_NOTIONAL_POLICY_VERSION_INVALID",
    )
    policy_source_key = _label(
        artifact.get("policy_source_key"),
        reason="CAUSAL_COST_NOTIONAL_POLICY_SOURCE_KEY_INVALID",
    )
    effective_iso, effective_at = _clock(
        artifact.get("effective_at"),
        reason="CAUSAL_COST_NOTIONAL_EFFECTIVE_AT_INVALID",
    )
    available_iso, available_at = _clock(
        artifact.get("available_at"),
        reason="CAUSAL_COST_NOTIONAL_AVAILABLE_AT_INVALID",
    )
    expires_iso, expires_at = _clock(
        artifact.get("expires_at"),
        reason="CAUSAL_COST_NOTIONAL_EXPIRES_AT_INVALID",
    )
    if not effective_at <= available_at <= decision_at < expires_at:
        _validation("CAUSAL_COST_NOTIONAL_CLOCK_OR_EXPIRY_INVALID")
    artifact_address = _put_exact(
        store,
        typed_artifact_bytes,
        failure_reason="CAUSAL_COST_NOTIONAL_ARTIFACT_CAS_FAILED",
    )
    validated_receipt = _self_hashed_receipt(
        receipt,
        fields=_NOTIONAL_RECEIPT_FIELDS,
        reason="CAUSAL_COST_NOTIONAL_RECEIPT_INVALID",
    )
    expected_receipt = {
        "schema_version": CAUSAL_COST_NOTIONAL_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "DIRECT_READ",
        "artifact_payload_sha256": artifact_address.payload_sha256,
        "artifact_payload_byte_count": artifact_address.payload_byte_count,
        "policy_source_key": policy_source_key,
        "source_schema_version": CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
        "source_transport": _NOTIONAL_SOURCE_TRANSPORT,
        "symbol": symbol,
        "feature_snapshot_identity": feature_snapshot_identity,
        "effective_at": effective_iso,
        "available_at": available_iso,
        "expires_at": expires_iso,
        "authority_scope": "FEATURE_SNAPSHOT_CAUSAL_EXPECTED_NOTIONAL",
    }
    if any(validated_receipt.get(name) != value for name, value in expected_receipt.items()):
        _validation("CAUSAL_COST_NOTIONAL_RECEIPT_ARTIFACT_BINDING_INVALID")
    receipt_bytes = _canonical_bytes(
        validated_receipt,
        reason="CAUSAL_COST_NOTIONAL_RECEIPT_JSON_INVALID",
    )
    receipt_address = _put_exact(
        store,
        receipt_bytes,
        failure_reason="CAUSAL_COST_NOTIONAL_RECEIPT_CAS_FAILED",
    )
    source = {
        "policy_id": policy_id,
        "policy_version": policy_version,
        "policy_source_key": policy_source_key,
        "source_schema_version": CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
        "source_transport": _NOTIONAL_SOURCE_TRANSPORT,
        "artifact_payload_sha256": artifact_address.payload_sha256,
        "artifact_payload_byte_count": artifact_address.payload_byte_count,
        "artifact_cas_address": _address_mapping(artifact_address),
        "input_receipt_sha256": validated_receipt["receipt_sha256"],
        "input_receipt_cas_address": _address_mapping(receipt_address),
        "effective_at": effective_iso,
        "available_at": available_iso,
        "expires_at": expires_iso,
        "expected_notional_usd": expected_notional_usd,
        "expected_notional_float64_hex": expected_notional_usd.hex(),
        "fallback_used": False,
        "static_default_used": False,
    }
    return (
        source,
        validated_receipt,
        (
            (artifact_address, typed_artifact_bytes),
            (receipt_address, receipt_bytes),
        ),
    )


def _market_source_receipt(
    *,
    role: str,
    source: Mapping[str, Any],
    symbol: str,
    feature_snapshot_identity: str,
    decision_time: str,
) -> dict[str, Any]:
    clocks = source.get("clocks")
    if not isinstance(clocks, Mapping):
        _integrity("CAUSAL_COST_MARKET_SOURCE_CLOCKS_MISSING")
    material = {
        "schema_version": CAUSAL_COST_SOURCE_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "DIRECT_READ",
        "source_role": role,
        "source_key": source["source_key"],
        "source_key_sha256": source["source_key_sha256"],
        "source_schema_version": source["source_schema_version"],
        "source_transport": source["source_transport"],
        "symbol": symbol,
        "feature_snapshot_identity": feature_snapshot_identity,
        "payload_sha256": source["payload_sha256"],
        "payload_byte_count": source["payload_byte_count"],
        "payload_cas_address": source["payload_cas_address"],
        "atomic_batch_id": source["atomic_batch_id"],
        "atomic_batch_material_sha256": source["atomic_batch_material_sha256"],
        "atomic_server_observed_at": source["atomic_server_observed_at"],
        "redis_pttl_ms": source["redis_pttl_ms"],
        "redis_pttl_expiry_projection_at": source[
            "redis_pttl_expiry_projection_at"
        ],
        "expiry_evidence_kind": source["expiry_evidence_kind"],
        "consumer_static_age_threshold_applied": False,
        "source_sequence_id": source["source_sequence_id"],
        "source_sequence_gap": source["source_sequence_gap"],
        "event_time": clocks["event_time"],
        "received_at": clocks["received_at"],
        "available_at": clocks["available_at"],
        "generated_at": clocks["generated_at"],
        "decision_time": decision_time,
        "available_at_not_after_decision": True,
        "producer_schema_semantics_rederived": True,
        "upstream_transport_cryptographic_authenticity_attested": False,
        "authorization": {
            "profiled_39_record_built": False,
            "trainer_admission_authorized": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        },
    }
    return {**material, "receipt_sha256": _sha256(material)}


def _composite_receipt(
    *,
    feature_name: str,
    value: float,
    value_hex: str,
    configuration: Mapping[str, Any],
    child_bindings: Sequence[Mapping[str, Any]],
    exact_bindings: Mapping[str, Any],
    derivation: Mapping[str, Any],
    module_code_sha256: str,
) -> dict[str, Any]:
    configuration_material = {
        "schema_version": "causal_cost_scalar_configuration_v1",
        "global_implementation_sha256": CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256,
        **dict(configuration),
    }
    configuration_sha256 = _sha256(configuration_material)
    transform_contract = {
        "schema_version": "causal_cost_scalar_transform_contract_v1",
        "implementation_id": CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
        "implementation_sha256": CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256,
        "module_code_sha256": module_code_sha256,
        "configuration_sha256": configuration_sha256,
        "configuration": configuration_material,
    }
    transform_sha256 = _sha256(transform_contract)
    scalar_bytes = bytes.fromhex(value_hex)
    material = {
        "schema_version": CAUSAL_COST_COMPOSITE_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "COMPOSITE_DERIVATION",
        "feature_name": feature_name,
        "feature_role": "LABEL_ONLY_AUXILIARY_NOT_MODEL_INPUT",
        "payload_type": "IEEE754_BINARY32_SCALAR",
        "payload_sha256": hashlib.sha256(scalar_bytes).hexdigest(),
        "payload_byte_count": len(scalar_bytes),
        "value_float32_be_hex": value_hex,
        "value": value,
        "value_unit": "BASIS_POINTS",
        "child_read_bindings": [dict(item) for item in child_bindings],
        "derivation_material": {
            "schema_version": "causal_cost_derivation_material_v1",
            "producer_id": "causal_cost_evidence_v1",
            "implementation_id": CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
            "implementation_sha256": CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256,
            "module_code_sha256": module_code_sha256,
            "configuration_sha256": configuration_sha256,
            "transform_sha256": transform_sha256,
            "exact_rederivation": dict(derivation),
        },
        "exact_bindings": dict(exact_bindings),
        "authorization": {
            "profiled_39_record_built": False,
            "trainer_admission_authorized": False,
            "prediction_authorized": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        },
    }
    return {**material, "receipt_sha256": _sha256(material)}


def build_causal_cost_evidence_v1(
    *,
    atomic_capture: object,
    source_payload_store: object,
    fee_schedule_artifact_bytes: object,
    fee_schedule_raw_response_bytes: object,
    fee_schedule_receipt: object,
    expected_notional_usd: object,
    expected_notional_policy_artifact_bytes: object,
    expected_notional_policy_receipt: object,
    symbol: object,
    feature_snapshot_identity: object,
    decision_time: object,
    counterfactual_holding_horizon_seconds: object,
) -> CausalCostEvidenceV1Result:
    """Build four audit-only float32 scalars from complete causal evidence.

    The 900-second horizon is an explicit pinned ABI input.  It is required,
    has no default, and any other value fails closed.
    """

    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _validation("CAUSAL_COST_IMMUTABLE_SOURCE_PAYLOAD_STORE_REQUIRED")
    store = cast(ImmutableSourcePayloadStore, source_payload_store)
    normalized_symbol = _label(
        symbol,
        reason="CAUSAL_COST_SYMBOL_INVALID",
        pattern=_SYMBOL_RE,
    )
    snapshot_identity = _label(
        feature_snapshot_identity,
        reason="CAUSAL_COST_FEATURE_SNAPSHOT_IDENTITY_INVALID",
    )
    decision_iso, decision_at = _clock(
        decision_time,
        reason="CAUSAL_COST_DECISION_TIME_INVALID",
    )
    if (
        type(counterfactual_holding_horizon_seconds) is not int
        or counterfactual_holding_horizon_seconds
        != CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
    ):
        _validation("CAUSAL_COST_COUNTERFACTUAL_HORIZON_NOT_PINNED_900_SECONDS")
    notional = _finite(
        expected_notional_usd,
        reason="CAUSAL_COST_EXPECTED_NOTIONAL_INVALID",
        positive=True,
    )
    payloads, market_sources, market_objects = _validated_atomic_sources(
        atomic_capture=atomic_capture,
        store=store,
        symbol=normalized_symbol,
        decision_at=decision_at,
    )
    notional_source, notional_receipt, notional_objects = _validate_notional_evidence(
        store=store,
        artifact_bytes=expected_notional_policy_artifact_bytes,
        receipt=expected_notional_policy_receipt,
        expected_notional_usd=notional,
        symbol=normalized_symbol,
        feature_snapshot_identity=snapshot_identity,
        decision_at=decision_at,
    )
    fee_value, fee_source, fee_receipt, fee_objects = _validate_fee_evidence(
        store=store,
        artifact_bytes=fee_schedule_artifact_bytes,
        raw_response_bytes=fee_schedule_raw_response_bytes,
        receipt=fee_schedule_receipt,
        symbol=normalized_symbol,
        decision_at=decision_at,
    )
    spread_value, impact_value, orderbook_derivation = _validate_orderbook_sources(
        depth=payloads["orderbook_depth"],
        features=payloads["orderbook_features"],
        evidence=market_sources,
        symbol=normalized_symbol,
        decision_at=decision_at,
        expected_notional_usd=notional,
    )
    funding_value, funding_derivation = _validate_mark_source(
        mark=payloads["mark_price"],
        evidence=market_sources,
        symbol=normalized_symbol,
        decision_at=decision_at,
    )

    source_receipts = {
        role: _market_source_receipt(
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
            reason="CAUSAL_COST_MARKET_RECEIPT_JSON_INVALID",
        )
        receipt_address = _put_exact(
            store,
            receipt_bytes,
            failure_reason=f"CAUSAL_COST_{role.upper()}_RECEIPT_CAS_FAILED",
        )
        market_sources[role]["direct_read_receipt_sha256"] = receipt_value[
            "receipt_sha256"
        ]
        market_sources[role]["direct_read_receipt_cas_address"] = _address_mapping(
            receipt_address
        )
        source_receipt_objects.append((receipt_address, receipt_bytes))

    horizon_end = decision_at + timedelta(
        seconds=CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
    )
    exact_bindings = {
        "symbol": normalized_symbol,
        "feature_snapshot_identity": snapshot_identity,
        "feature_snapshot_identity_sha256": hashlib.sha256(
            snapshot_identity.encode("ascii")
        ).hexdigest(),
        "decision_time": decision_iso,
        "counterfactual_holding_horizon_seconds": (
            CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        ),
        "counterfactual_horizon_end": horizon_end.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        "expected_notional_usd": notional,
        "expected_notional_float64_hex": notional.hex(),
        "notional_policy_receipt_sha256": notional_receipt["receipt_sha256"],
        "fee_schedule_receipt_sha256": fee_receipt["receipt_sha256"],
        "atomic_batch_id": cast(AtomicRedisSourceReadBatch, atomic_capture).batch_id,
        "atomic_batch_material_sha256": cast(
            AtomicRedisSourceReadBatch, atomic_capture
        ).batch_material_sha256,
        "profiled_39_record_id": None,
    }
    module_sha256 = _module_code_sha256()
    specs = (
        (
            "fee_bps",
            fee_value,
            {
                "component_semantics": "TAKER_FEE_BPS_PER_SIDE",
                "formula": "RAW_TAKER_COMMISSION_RATE_TIMES_10000",
                "required_child_roles": ["authoritative_fee_schedule"],
            },
            (
                {
                    "input_role": "authoritative_fee_schedule",
                    "receipt_sha256": fee_receipt["receipt_sha256"],
                },
            ),
            {
                "raw_taker_commission_rate": _parse_detached_response_bytes(
                    cast(bytes, fee_schedule_raw_response_bytes)
                )["takerCommissionRate"],
                "fee_bps_per_side_float64_hex": fee_value.hex(),
                "effective_at_equals_available_at": True,
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
                    "receipt_sha256": source_receipts["mark_price"][
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
        value, value_hex = _float32(
            raw_value,
            reason=f"CAUSAL_COST_{feature_name.upper()}_FLOAT32_INVALID",
        )
        values.append(value)
        receipts.append(
            _composite_receipt(
                feature_name=feature_name,
                value=value,
                value_hex=value_hex,
                configuration=configuration,
                child_bindings=children,
                exact_bindings=exact_bindings,
                derivation=derivation,
                module_code_sha256=module_sha256,
            )
        )

    contract_material = {
        "schema_version": CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION,
        "evidence_classification": CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION,
        "downstream_status": CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS,
        "implementation_id": CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID,
        "implementation_sha256": CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256,
        "module_code_sha256": module_sha256,
        "symbol": normalized_symbol,
        "feature_snapshot_identity": snapshot_identity,
        "decision_time": decision_iso,
        "counterfactual_holding_horizon_seconds": (
            CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS
        ),
        "counterfactual_horizon_end": exact_bindings[
            "counterfactual_horizon_end"
        ],
        "ordered_feature_names": list(CAUSAL_COST_ORDERED_FEATURE_NAMES),
        "ordered_values": values,
        "ordered_receipt_sha256s": [
            receipt_value["receipt_sha256"] for receipt_value in receipts
        ],
        "ordered_receipts": receipts,
        "market_sources": market_sources,
        "market_source_read_receipts": source_receipts,
        "fee_source": fee_source,
        "notional_source": notional_source,
        "funding_settlement_contract": funding_derivation,
        "market_source_authenticity_status": (
            "RECORDER_KEY_SCHEMA_TRANSPORT_SEMANTICS_REDERIVED_NO_UPSTREAM_SIGNATURE"
        ),
        "fee_source_authenticity_status": (
            "DETACHED_STRUCTURAL_VALIDATION_ONLY_FACTORY_SIGNED_CAPTURE_PENDING"
        ),
        "no_static_fallback_or_floor": True,
        "optional_provider_dependencies": [],
        "authorization": {
            "profiled_39_record_built": False,
            "feature_snapshot_published": False,
            "trainer_admission_authorized": False,
            "prediction_authorized": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        },
    }
    contract_material_sha256 = _sha256(contract_material)
    contract = {
        **contract_material,
        "evidence_id": f"causal_cost_evidence_v1_{contract_material_sha256}",
        "contract_material_sha256": contract_material_sha256,
    }
    artifact_bytes = _canonical_bytes(
        contract,
        reason="CAUSAL_COST_ARTIFACT_JSON_INVALID",
    )
    artifact_address = _put_exact(
        store,
        artifact_bytes,
        failure_reason="CAUSAL_COST_ARTIFACT_CAS_FAILED",
    )
    result = CausalCostEvidenceV1Result(
        artifact_sha256=artifact_address.payload_sha256,
        artifact_json=artifact_bytes.decode("ascii"),
        artifact_address=artifact_address,
        ordered_values=cast(tuple[float, float, float, float], tuple(values)),
        ordered_receipt_sha256s=cast(
            tuple[str, str, str, str],
            tuple(receipt_value["receipt_sha256"] for receipt_value in receipts),
        ),
        _store=store,
        _exact_objects=(
            *market_objects,
            *notional_objects,
            *fee_objects,
            *source_receipt_objects,
            (artifact_address, artifact_bytes),
        ),
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    _validated_result(result)
    return result


def _validated_result(result: CausalCostEvidenceV1Result) -> dict[str, Any]:
    if (
        type(result) is not CausalCostEvidenceV1Result
        or result._construction_token is not _CONSTRUCTION_TOKEN
        or type(result._store) is not ImmutableSourcePayloadStore
        or type(result._exact_objects) is not tuple
        or not result._exact_objects
    ):
        _integrity("CAUSAL_COST_RESULT_FACTORY_CONSTRUCTION_REQUIRED")
    for address, payload in result._exact_objects:
        if type(address) is not SourcePayloadAddress or type(payload) is not bytes:
            _integrity("CAUSAL_COST_RESULT_CAS_OBJECT_BINDING_INVALID")
        if (
            address.payload_sha256 != hashlib.sha256(payload).hexdigest()
            or address.payload_byte_count != len(payload)
        ):
            _integrity("CAUSAL_COST_RESULT_CAS_OBJECT_BINDING_INVALID")
        try:
            readback = result._store.get(
                address.payload_sha256,
                expected_byte_count=address.payload_byte_count,
            )
        except SourcePayloadStoreError as exc:
            raise CausalCostEvidenceV1IntegrityError(
                "CAUSAL_COST_RESULT_CAS_READBACK_FAILED"
            ) from exc
        if not hmac.compare_digest(readback, payload):
            _integrity("CAUSAL_COST_RESULT_CAS_READBACK_MISMATCH")
    try:
        artifact_bytes = result.artifact_json.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _integrity("CAUSAL_COST_RESULT_ARTIFACT_JSON_INVALID")
    if (
        hashlib.sha256(artifact_bytes).hexdigest() != result.artifact_sha256
        or result.artifact_address.payload_sha256 != result.artifact_sha256
        or result.artifact_address.payload_byte_count != len(artifact_bytes)
    ):
        _integrity("CAUSAL_COST_RESULT_ARTIFACT_BINDING_INVALID")
    contract = _parse_exact_json_bytes(
        artifact_bytes,
        reason="CAUSAL_COST_RESULT_ARTIFACT_JSON_INVALID",
    )
    material = {
        key: value
        for key, value in contract.items()
        if key not in {"evidence_id", "contract_material_sha256"}
    }
    material_sha256 = _sha256(material)
    if (
        contract.get("contract_material_sha256") != material_sha256
        or contract.get("evidence_id") != f"causal_cost_evidence_v1_{material_sha256}"
        or contract.get("implementation_sha256")
        != CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256
        or contract.get("module_code_sha256") != _module_code_sha256()
        or contract.get("ordered_feature_names")
        != list(CAUSAL_COST_ORDERED_FEATURE_NAMES)
        or tuple(contract.get("ordered_values") or ()) != result.ordered_values
        or tuple(contract.get("ordered_receipt_sha256s") or ())
        != result.ordered_receipt_sha256s
    ):
        _integrity("CAUSAL_COST_RESULT_CONTRACT_BINDING_INVALID")
    receipts = contract.get("ordered_receipts")
    if type(receipts) is not list or len(receipts) != 4:
        _integrity("CAUSAL_COST_RESULT_RECEIPT_INVENTORY_INVALID")
    for index, receipt_value in enumerate(cast(list[object], receipts)):
        if type(receipt_value) is not dict:
            _integrity("CAUSAL_COST_RESULT_RECEIPT_INVALID")
        receipt = cast(dict[str, Any], receipt_value)
        supplied = receipt.get("receipt_sha256")
        receipt_material = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        if (
            supplied != _sha256(receipt_material)
            or supplied != result.ordered_receipt_sha256s[index]
            or receipt.get("receipt_kind") != "COMPOSITE_DERIVATION"
            or receipt.get("feature_name") != CAUSAL_COST_ORDERED_FEATURE_NAMES[index]
            or receipt.get("value") != result.ordered_values[index]
            or receipt.get("authorization")
            != {
                "live_execution_authorized": False,
                "paper_execution_authorized": False,
                "prediction_authorized": False,
                "profiled_39_record_built": False,
                "trainer_admission_authorized": False,
            }
        ):
            _integrity("CAUSAL_COST_RESULT_RECEIPT_BINDING_INVALID")
    return cast(dict[str, Any], json.loads(result.artifact_json))


__all__ = [
    "CAUSAL_COST_COMPOSITE_RECEIPT_V1_SCHEMA_VERSION",
    "CAUSAL_COST_COUNTERFACTUAL_HORIZON_SECONDS",
    "CAUSAL_COST_EVIDENCE_V1_CLASSIFICATION",
    "CAUSAL_COST_EVIDENCE_V1_DOWNSTREAM_STATUS",
    "CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_ID",
    "CAUSAL_COST_EVIDENCE_V1_IMPLEMENTATION_SHA256",
    "CAUSAL_COST_EVIDENCE_V1_SCHEMA_VERSION",
    "CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION",
    "CAUSAL_COST_FEE_RECEIPT_V1_SCHEMA_VERSION",
    "CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION",
    "CAUSAL_COST_NOTIONAL_RECEIPT_V1_SCHEMA_VERSION",
    "CAUSAL_COST_ORDERED_FEATURE_NAMES",
    "CAUSAL_COST_SOURCE_RECEIPT_V1_SCHEMA_VERSION",
    "CausalCostEvidenceV1Error",
    "CausalCostEvidenceV1IntegrityError",
    "CausalCostEvidenceV1Result",
    "CausalCostEvidenceV1ValidationError",
    "build_causal_cost_evidence_v1",
]
