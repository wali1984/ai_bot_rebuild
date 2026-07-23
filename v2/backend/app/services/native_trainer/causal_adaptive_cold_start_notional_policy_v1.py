"""Causal adaptive cost-probe notional for a zero-candidate cold start.

This policy exists only to break the trainer/paper-candidate bootstrap cycle.
It intersects trusted paper free margin *after the producer's adaptive buffer*
with the smaller side of the exact visible Binance order book::

    min(free_margin_after_buffer_usd,
        total_visible_bid_notional_usd,
        total_visible_ask_notional_usd)

There is no dollar default, ratio, percentile, market threshold, candidate,
position-size, leverage, prediction, paper-fill, or live authority in this
factory.  Once genuine candidate allocation evidence exists, the primary
candidate-derived policy remains authoritative.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer import causal_cost_evidence_v1 as _causal
from v2.backend.app.services.native_trainer import (
    causal_expected_notional_policy_v1 as _candidate,
)
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
from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
    CAUSAL_COST_NOTIONAL_RECEIPT_V1_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)

CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_V1_SCHEMA_VERSION: Final = (
    "causal_adaptive_cold_start_notional_policy_factory_token_v1"
)
CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_SOURCE_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "causal_adaptive_cold_start_notional_source_receipt_v1"
)
CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY: Final = (
    "v2:paper:account_margin_status"
)
CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_SOURCE_KEY_TEMPLATE: Final = (
    "v2:paper:adaptive_sizing_runtime_status+v2:paper:account_margin_status+"
    "v2:orderbook:depth:binance:{symbol}+"
    "v2:orderbook:features:binance:{symbol}+v2:market:mark_price:{symbol}"
)
CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_ID: Final = (
    "adaptive-paper-capital-symmetric-visible-depth-cold-start-v1"
)
CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_SOURCE_TRANSPORT: Final = (
    "DURABLE_CAUSAL_POLICY_LEDGER"
)
CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_CLASSIFICATION: Final = (
    "LABEL_ONLY_ADAPTIVE_CAPITAL_LIQUIDITY_COST_PROBE_NO_EXECUTION_AUTHORITY"
)

_FORMULA: Final = (
    "min(free_margin_after_buffer_usd,total_visible_bid_notional_usd,"
    "total_visible_ask_notional_usd)"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_USD_SERIALIZATION_QUANTUM = Decimal("0.00000001")
_CONSTRUCTION_TOKEN = object()
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,511}$", re.ASCII)

_IMPLEMENTATION_CONTRACT: Final = {
    "schema_version": "causal_adaptive_cold_start_notional_implementation_v1",
    "policy_id": CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_ID,
    "margin_source_key": CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY,
    "zero_candidate_source_key": _candidate.CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
    "policy_source_key_template": (
        CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_SOURCE_KEY_TEMPLATE
    ),
    "market_source_keys": [
        "v2:orderbook:depth:binance:{symbol}",
        "v2:orderbook:features:binance:{symbol}",
        "v2:market:mark_price:{symbol}",
    ],
    "source_transport": "TWO_ATOMIC_REDIS_GETRANGE_PTTL_TIME_BATCHES",
    "derivation_formula": _FORMULA,
    "capital_input": "trusted_paper_free_margin_after_adaptive_buffer",
    "liquidity_input": "smaller_exact_visible_binance_book_side",
    "candidate_rows_required": False,
    "candidate_or_position_fabrication": False,
    "operator_projection_used": False,
    "fallback_values": [],
    "static_defaults": [],
    "market_thresholds": [],
    "authority": "NONE_LABEL_ONLY",
}
_POLICY_CONFIG: Final = {
    "schema_version": "causal_adaptive_cold_start_notional_policy_config_v1",
    "policy_id": CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_ID,
    "derivation_formula": _FORMULA,
    "numeric_constants": [],
    "fallback_values": [],
    "static_default_notional_usd": None,
    "leverage_assumption": None,
}
CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_SOURCE_RECEIPT_FIELDS: Final = frozenset(
    """
    schema_version receipt_kind policy_id policy_source_key source_transport
    source_bindings symbol feature_snapshot_identity producer_cycle_generated_at
    producer_cycle_id source_generated_at server_observed_at available_at expires_at
    decision_time
    free_margin_after_buffer_usd total_visible_bid_notional_usd
    total_visible_ask_notional_usd expected_notional_usd derivation_formula
    candidate_supply_status candidate_rows_consumed candidate_fabricated
    leverage_assumption operator_projection_used implementation_contract_sha256
    policy_config_sha256 module_code_sha256 causal_cost_module_code_sha256
    candidate_notional_module_code_sha256 fallback_used static_default_used
    read_only trainer_authority prediction_authority paper_authority live_authority
    order_authority receipt_sha256
    """.split()
)


class CausalAdaptiveColdStartNotionalPolicyV1Error(RuntimeError):
    """Base fail-closed error with a stable reason string."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class CausalAdaptiveColdStartNotionalPolicyV1ValidationError(
    CausalAdaptiveColdStartNotionalPolicyV1Error
):
    """Source content or caller input violates the policy contract."""


class CausalAdaptiveColdStartNotionalPolicyV1IntegrityError(
    CausalAdaptiveColdStartNotionalPolicyV1Error
):
    """An exact-byte, batch, CAS, or factory binding changed."""


@dataclass(frozen=True, slots=True)
class CausalAdaptiveColdStartNotionalPolicyTokenV1:
    """Factory-sealed cost-evidence-compatible cold-start token."""

    schema_version: str
    symbol: str
    feature_snapshot_identity: str
    expected_notional_usd: float
    policy_version: str
    source_generated_at: str
    server_observed_at: str
    available_at: str
    expires_at: str
    decision_time: str
    free_margin_after_buffer_usd: float
    total_visible_bid_notional_usd: float
    total_visible_ask_notional_usd: float
    source_read_receipt_bytes: bytes = field(repr=False)
    source_read_receipt_address: SourcePayloadAddress
    source_read_receipt_sha256: str
    notional_artifact_bytes: bytes = field(repr=False)
    notional_artifact_address: SourcePayloadAddress
    notional_receipt_bytes: bytes = field(repr=False)
    notional_receipt_address: SourcePayloadAddress
    notional_receipt_sha256: str
    implementation_contract_sha256: str
    policy_config_sha256: str
    module_code_sha256: str
    read_only: bool = field(default=True, init=False)
    trainer_authority: bool = field(default=False, init=False)
    prediction_authority: bool = field(default=False, init=False)
    paper_authority: bool = field(default=False, init=False)
    live_authority: bool = field(default=False, init=False)
    order_authority: bool = field(default=False, init=False)
    fallback_used: bool = field(default=False, init=False)
    static_default_used: bool = field(default=False, init=False)
    _control_capture: AtomicRedisSourceReadBatch = field(
        repr=False,
        compare=False,
    )
    _market_capture: AtomicRedisSourceReadBatch = field(repr=False, compare=False)
    _source_objects: tuple[tuple[SourcePayloadAddress, bytes], ...] = field(
        repr=False,
        compare=False,
    )
    _store: ImmutableSourcePayloadStore = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    @property
    def source_read_receipt(self) -> dict[str, Any]:
        return cast(dict[str, Any], _validate_token(self)["source_read_receipt"])

    @property
    def notional_artifact(self) -> dict[str, Any]:
        return cast(dict[str, Any], _validate_token(self)["notional_artifact"])

    @property
    def notional_receipt(self) -> dict[str, Any]:
        return cast(dict[str, Any], _validate_token(self)["notional_receipt"])

    @property
    def contract(self) -> dict[str, Any]:
        return _validate_token(self)


@dataclass(frozen=True, slots=True)
class _DerivedInputs:
    symbol: str
    snapshot_identity: str
    decision_iso: str
    decision_at: datetime
    producer_cycle_generated_at: str
    producer_cycle_id: str
    source_generated_at: str
    server_observed_at: str
    available_at: str
    expires_at: str
    free_margin_after_buffer_usd: float
    total_visible_bid_notional_usd: float
    total_visible_ask_notional_usd: float
    expected_notional_usd: float
    portfolio_batch: AtomicRedisSourceReadBatch
    zero_candidate_batch: AtomicRedisSourceReadBatch
    market_batch: AtomicRedisSourceReadBatch
    source_objects: tuple[tuple[SourcePayloadAddress, bytes], ...]


def _validation(reason: str) -> NoReturn:
    raise CausalAdaptiveColdStartNotionalPolicyV1ValidationError(reason) from None


def _integrity(reason: str) -> NoReturn:
    raise CausalAdaptiveColdStartNotionalPolicyV1IntegrityError(reason) from None


def _canonical_bytes(value: object, *, reason: str) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _validation(reason)


def _canonical_sha256(value: object, *, reason: str) -> str:
    return hashlib.sha256(_canonical_bytes(value, reason=reason)).hexdigest()


CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256: Final = (
    _canonical_sha256(
        _IMPLEMENTATION_CONTRACT,
        reason="COLD_START_NOTIONAL_IMPLEMENTATION_CONTRACT_INVALID",
    )
)
CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_CONFIG_SHA256: Final = (
    _canonical_sha256(
        _POLICY_CONFIG,
        reason="COLD_START_NOTIONAL_POLICY_CONFIG_INVALID",
    )
)


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _symbol(value: object) -> str:
    if type(value) is not str or _SYMBOL_RE.fullmatch(value) is None:
        _validation("COLD_START_NOTIONAL_SYMBOL_INVALID")
    return value


def _snapshot_identity(value: object) -> str:
    if type(value) is not str or value != value.strip() or _LABEL_RE.fullmatch(value) is None:
        _validation("COLD_START_NOTIONAL_FEATURE_SNAPSHOT_IDENTITY_INVALID")
    return value


def _required_producer_cycle_id(value: object) -> str:
    if (
        type(value) is not str
        or not value.startswith("paper_cycle:")
        or not _valid_sha256(value.removeprefix("paper_cycle:"))
    ):
        _validation("COLD_START_NOTIONAL_PRODUCER_CYCLE_ID_INVALID")
    return value


def causal_adaptive_cold_start_notional_policy_source_key_v1(symbol: object) -> str:
    """Return the exact five-key policy source identity for one symbol."""

    return CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_SOURCE_KEY_TEMPLATE.format(
        symbol=_symbol(symbol)
    )


def _clock(value: object, *, reason: str) -> tuple[str, datetime]:
    if type(value) is not str or value != value.strip() or not value.endswith("Z"):
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


def _decision_clock(value: object) -> tuple[str, datetime]:
    if type(value) is not datetime:
        _validation("COLD_START_NOTIONAL_DECISION_TIME_INVALID")
    parsed = cast(datetime, value)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        _validation("COLD_START_NOTIONAL_DECISION_TIME_INVALID")
    parsed = parsed.astimezone(UTC)
    if parsed <= _EPOCH:
        _validation("COLD_START_NOTIONAL_DECISION_TIME_INVALID")
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z"), parsed


class _StrictJSONError(ValueError):
    pass


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJSONError("duplicate")
        result[key] = value
    return result


def _strict_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _StrictJSONError("nonfinite")
    return parsed


def _reject_json_constant(_value: str) -> NoReturn:
    raise _StrictJSONError("nonfinite")


def _parse_strict_json(payload: bytes, *, reason: str) -> dict[str, Any]:
    try:
        parsed = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
            parse_float=_strict_float,
        )
    except (
        OverflowError,
        RecursionError,
        UnicodeDecodeError,
        _StrictJSONError,
        ValueError,
    ):
        _validation(reason)
    if type(parsed) is not dict:
        _validation(reason)
    return cast(dict[str, Any], parsed)


def _finite(value: object, *, reason: str, positive: bool = False) -> float:
    if type(value) not in {int, float}:
        _validation(reason)
    parsed = float(cast(int | float, value))
    if not math.isfinite(parsed) or (positive and parsed <= 0.0):
        _validation(reason)
    return parsed


def _decimal(value: object, *, reason: str) -> Decimal:
    if type(value) not in {int, float}:
        _validation(reason)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _validation(reason)
    if not parsed.is_finite() or parsed < 0:
        _validation(reason)
    return parsed


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
        raise CausalAdaptiveColdStartNotionalPolicyV1IntegrityError(reason) from exc
    if (
        address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or address.payload_sha256 != digest
        or address.payload_byte_count != len(payload)
        or not hmac.compare_digest(readback, payload)
    ):
        _integrity(reason)
    return address


def _readback_exact(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
    payload: bytes,
    *,
    reason: str,
) -> None:
    digest = hashlib.sha256(payload).hexdigest()
    try:
        readback = store.get(digest, expected_byte_count=len(payload))
    except SourcePayloadStoreError as exc:
        raise CausalAdaptiveColdStartNotionalPolicyV1IntegrityError(reason) from exc
    if (
        address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or address.payload_sha256 != digest
        or address.payload_byte_count != len(payload)
        or not hmac.compare_digest(readback, payload)
    ):
        _integrity(reason)


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
                "server_time_is_consumer_observed_at": (
                    result.server_time_is_consumer_observed_at
                ),
                "source_finality_attested": result.source_finality_attested,
                "source_key": result.source_key,
                "source_key_sha256": result.source_key_sha256,
                "source_schema_attested": result.source_schema_attested,
                "transport_authenticity_attested": (
                    result.transport_authenticity_attested
                ),
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


def _validated_portfolio_capture(
    capture: object,
    *,
    store: ImmutableSourcePayloadStore,
    decision_at: datetime,
) -> tuple[
    AtomicRedisSourceReadBatch,
    AtomicRedisSourceResult,
    dict[str, Any],
    SourcePayloadAddress,
    bytes,
    datetime,
    datetime,
]:
    if type(capture) is not AtomicRedisSourceReadBatch:
        _validation("COLD_START_NOTIONAL_PORTFOLIO_ATOMIC_CAPTURE_TYPE_INVALID")
    batch = cast(AtomicRedisSourceReadBatch, capture)
    if (
        batch.schema_version != ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION
        or type(batch.results) is not tuple
        or len(batch.results) != 2
        or any(type(item) is not AtomicRedisSourceResult for item in batch.results)
    ):
        _integrity("COLD_START_NOTIONAL_PORTFOLIO_ATOMIC_CAPTURE_SHAPE_INVALID")
    result = batch.results[1]
    try:
        server_at = _EPOCH + timedelta(
            seconds=batch.server_time_seconds,
            microseconds=batch.server_time_microseconds,
        )
    except (OverflowError, TypeError, ValueError):
        _integrity("COLD_START_NOTIONAL_PORTFOLIO_SERVER_CLOCK_INVALID")
    server_iso = server_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if server_iso != batch.server_observed_at or server_at > decision_at:
        _validation("COLD_START_NOTIONAL_PORTFOLIO_CAPTURE_AFTER_DECISION")
    material = _expected_atomic_batch_material(batch)
    material_sha256 = hashlib.sha256(material.encode("ascii")).hexdigest()
    if (
        batch.batch_material_json != material
        or batch.batch_material_sha256 != material_sha256
        or batch.batch_id != f"trainer_atomic_redis_source_read_v2_{material_sha256}"
    ):
        _integrity("COLD_START_NOTIONAL_PORTFOLIO_ATOMIC_BINDING_INVALID")
    payload = result.exact_payload_bytes
    expected_key = CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY
    if (
        result.schema_version != ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION
        or result.source_key != expected_key
        or result.source_key_sha256
        != hashlib.sha256(expected_key.encode("ascii")).hexdigest()
    ):
        _integrity("COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY_BINDING_INVALID")
    if (
        result.redis_type != "string"
        or result.present is not True
        or type(payload) is not bytes
        or not payload
    ):
        _validation("COLD_START_NOTIONAL_PORTFOLIO_SOURCE_MISSING")
    payload = cast(bytes, payload)
    if (
        result.payload_sha256 != hashlib.sha256(payload).hexdigest()
        or result.payload_byte_count != len(payload)
        or batch.total_payload_byte_count
        != sum(item.payload_byte_count for item in batch.results)
        or result.server_observed_at != batch.server_observed_at
    ):
        _integrity("COLD_START_NOTIONAL_PORTFOLIO_PAYLOAD_BINDING_INVALID")
    if type(result.pttl_ms) is not int or result.pttl_ms <= 0:
        _validation("COLD_START_NOTIONAL_PORTFOLIO_PERSISTED_EXPIRY_MISSING")
    expires_at = server_at + timedelta(milliseconds=result.pttl_ms)
    if decision_at >= expires_at:
        _validation("COLD_START_NOTIONAL_PORTFOLIO_EXPIRED_AT_DECISION")
    if any(
        (
            batch.read_only is not True,
            batch.paper_provenance_only is not True,
            batch.live_execution_authorized is not False,
            batch.source_schema_attested is not False,
            batch.source_finality_attested is not False,
            batch.ledger_receipt_emitted is not False,
            batch.consumer_eligible is not False,
            batch.transport_authenticity_attested is not False,
            batch.server_time_is_consumer_observed_at is not False,
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
            batch.server_time_clock_semantics != REDIS_TIME_CLOCK_SEMANTICS,
        )
    ):
        _integrity("COLD_START_NOTIONAL_PORTFOLIO_ATOMIC_FLAGS_INVALID")
    parsed = _parse_strict_json(
        payload,
        reason="COLD_START_NOTIONAL_PORTFOLIO_SOURCE_JSON_INVALID",
    )
    address = _put_exact(
        store,
        payload,
        reason="COLD_START_NOTIONAL_PORTFOLIO_SOURCE_CAS_FAILED",
    )
    return batch, result, parsed, address, payload, server_at, expires_at


def _validated_zero_candidate_capture(
    capture: object,
    *,
    store: ImmutableSourcePayloadStore,
    decision_at: datetime,
) -> tuple[
    AtomicRedisSourceReadBatch,
    AtomicRedisSourceResult,
    SourcePayloadAddress,
    bytes,
    str,
    datetime,
    datetime,
]:
    if type(capture) is not AtomicRedisSourceReadBatch:
        _validation("COLD_START_NOTIONAL_CONTROL_ATOMIC_CAPTURE_TYPE_INVALID")
    batch = cast(AtomicRedisSourceReadBatch, capture)
    if (
        batch.schema_version != ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION
        or type(batch.results) is not tuple
        or len(batch.results) != 2
        or any(type(item) is not AtomicRedisSourceResult for item in batch.results)
    ):
        _integrity("COLD_START_NOTIONAL_CONTROL_ATOMIC_CAPTURE_SHAPE_INVALID")
    result = batch.results[0]
    try:
        server_at = _EPOCH + timedelta(
            seconds=batch.server_time_seconds,
            microseconds=batch.server_time_microseconds,
        )
    except (OverflowError, TypeError, ValueError):
        _integrity("COLD_START_NOTIONAL_CONTROL_SERVER_CLOCK_INVALID")
    server_iso = server_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if server_iso != batch.server_observed_at or server_at > decision_at:
        _validation("COLD_START_NOTIONAL_CONTROL_CAPTURE_AFTER_DECISION")
    material = _expected_atomic_batch_material(batch)
    material_sha256 = hashlib.sha256(material.encode("ascii")).hexdigest()
    if (
        batch.batch_material_json != material
        or batch.batch_material_sha256 != material_sha256
        or batch.batch_id != f"trainer_atomic_redis_source_read_v2_{material_sha256}"
    ):
        _integrity("COLD_START_NOTIONAL_CONTROL_ATOMIC_BINDING_INVALID")
    payload = result.exact_payload_bytes
    expected_key = _candidate.CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY
    if (
        result.schema_version != ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION
        or result.source_key != expected_key
        or result.source_key_sha256
        != hashlib.sha256(expected_key.encode("ascii")).hexdigest()
    ):
        _integrity("COLD_START_NOTIONAL_ZERO_CANDIDATE_SOURCE_KEY_BINDING_INVALID")
    if (
        result.redis_type != "string"
        or result.present is not True
        or type(payload) is not bytes
        or not payload
    ):
        _validation("COLD_START_NOTIONAL_ZERO_CANDIDATE_SOURCE_MISSING")
    payload = cast(bytes, payload)
    if (
        result.payload_sha256 != hashlib.sha256(payload).hexdigest()
        or result.payload_byte_count != len(payload)
        or batch.total_payload_byte_count
        != sum(item.payload_byte_count for item in batch.results)
        or result.server_observed_at != batch.server_observed_at
    ):
        _integrity("COLD_START_NOTIONAL_ZERO_CANDIDATE_PAYLOAD_BINDING_INVALID")
    if type(result.pttl_ms) is not int or result.pttl_ms <= 0:
        _validation("COLD_START_NOTIONAL_ZERO_CANDIDATE_EXPIRY_MISSING")
    expires_at = server_at + timedelta(milliseconds=result.pttl_ms)
    if decision_at >= expires_at:
        _validation("COLD_START_NOTIONAL_ZERO_CANDIDATE_EXPIRED_AT_DECISION")
    if any(
        (
            batch.read_only is not True,
            batch.paper_provenance_only is not True,
            batch.live_execution_authorized is not False,
            batch.source_schema_attested is not False,
            batch.source_finality_attested is not False,
            batch.ledger_receipt_emitted is not False,
            batch.consumer_eligible is not False,
            batch.transport_authenticity_attested is not False,
            batch.server_time_is_consumer_observed_at is not False,
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
            batch.server_time_clock_semantics != REDIS_TIME_CLOCK_SEMANTICS,
        )
    ):
        _integrity("COLD_START_NOTIONAL_ZERO_CANDIDATE_ATOMIC_FLAGS_INVALID")
    try:
        status = _candidate._parse_strict_outer_json(  # noqa: SLF001 - shared exact ABI
            payload
        )
    except _candidate.CausalExpectedNotionalPolicyV1Error as exc:
        raise CausalAdaptiveColdStartNotionalPolicyV1ValidationError(
            exc.reason
        ) from None
    address = _put_exact(
        store,
        payload,
        reason="COLD_START_NOTIONAL_ZERO_CANDIDATE_SOURCE_CAS_FAILED",
    )
    contract = status.get("candidate_allocations_canonical_aggregate_contract")
    if type(contract) is not dict:
        _validation("COLD_START_NOTIONAL_ZERO_CANDIDATE_AGGREGATE_MISSING")
    contract = cast(dict[str, Any], contract)
    embedded_hash = contract.get("contract_hash")
    if not _valid_sha256(embedded_hash):
        _validation("COLD_START_NOTIONAL_ZERO_CANDIDATE_AGGREGATE_HASH_INVALID")
    contract_material = dict(contract)
    contract_material.pop("contract_hash")
    recomputed_hash = _canonical_sha256(
        contract_material,
        reason="COLD_START_NOTIONAL_ZERO_CANDIDATE_AGGREGATE_INVALID",
    )
    if not hmac.compare_digest(cast(str, embedded_hash), recomputed_hash):
        _integrity("COLD_START_NOTIONAL_ZERO_CANDIDATE_AGGREGATE_HASH_MISMATCH")
    required_status = {
        "allocator": _candidate.CAUSAL_EXPECTED_NOTIONAL_SOURCE_ALLOCATOR,
        "fixed_runtime_notional_removed": True,
        "paper_candidates_with_allocation": 0,
        "candidate_allocation_count": 0,
        "candidate_allocations": [],
        "candidate_allocations_complete": False,
        "candidate_allocations_projection_only": True,
        "candidate_allocations_source_row_count": 0,
        "candidate_allocations_source_hashes": [],
        "candidate_allocations_all_source_rows_hashable": True,
        "candidate_allocations_unhashable_source_row_count": 0,
        "candidate_allocations_selected_before_outcome": True,
        "candidate_allocations_future_labels_used_as_features": False,
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }
    if any(status.get(key) != value for key, value in required_status.items()):
        _validation("COLD_START_NOTIONAL_ZERO_CANDIDATE_STATUS_INVALID")
    empty_aggregate_sha256 = _canonical_sha256(
        [],
        reason="COLD_START_NOTIONAL_ZERO_CANDIDATE_EMPTY_AGGREGATE_INVALID",
    )
    if status.get("candidate_allocations_aggregate_sha256") != empty_aggregate_sha256:
        _integrity("COLD_START_NOTIONAL_ZERO_CANDIDATE_SOURCE_HASH_INVALID")
    required_contract = {
        "schema_version": "paper_candidate_canonical_aggregate_contract_v1",
        "producer": _candidate.CAUSAL_EXPECTED_NOTIONAL_SOURCE_PRODUCER,
        "paper_only": True,
        "contract_hash_algorithm": "sha256(canonical-json-v1)",
        "operator_projection_is_canonical_evidence": False,
        "source_row_count": 0,
        "source_rows_all_hashable": True,
        "source_rows_aggregate_sha256": empty_aggregate_sha256,
        "contract_evaluated_row_count": 0,
        "contract_fact_hashes": [],
        "contract_fact_hashes_all_hashable": True,
        "contract_fact_hashes_aggregate_sha256": empty_aggregate_sha256,
    }
    if any(contract.get(key) != value for key, value in required_contract.items()):
        _validation("COLD_START_NOTIONAL_ZERO_CANDIDATE_CONTRACT_INVALID")
    expected_zero_liquidation = {
        "a_grade_candidate_count": 0,
        "all_a_grade_candidates_pass": False,
        "blocker_counts": {},
        "failed_a_grade_candidate_count": 0,
        "passed_a_grade_candidate_count": 0,
    }
    expected_hedge = {
        "active_hedge_candidate_count": 0,
        "all_active_hedge_candidates_pass": True,
        "blocker_counts": {},
        "failed_active_hedge_candidate_count": 0,
        "hedge_enabled_candidate_count": 0,
        "passed_active_hedge_candidate_count": 0,
        "positive_hedge_budget_candidate_count": 0,
    }
    expected_capital = {
        "a_grade_candidate_count": 0,
        "accepted_a_grade_candidate_count": 0,
        "account_context": {},
        "allocator_decision_counts": {},
        "allowed_before_non_executable_tier_block_count": 0,
        "candidate_count": 0,
        "classification_counts": {},
        "numeric_sums": {},
        "original_allocator_decision_counts": {},
        "paper_opportunity_tier_counts": {},
        "recommended_leverage_counts": {},
        "recommended_margin_mode_counts": {},
        "underfunded_a_grade_candidate_count": 0,
    }
    expected_contract_fields = frozenset(
        {
            *required_contract,
            "contract_hash",
            "zero_liquidation",
            "hedge",
            "capital",
        }
    )
    if (
        frozenset(contract) != expected_contract_fields
        or contract.get("zero_liquidation") != expected_zero_liquidation
        or contract.get("hedge") != expected_hedge
        or contract.get("capital") != expected_capital
    ):
        _validation("COLD_START_NOTIONAL_ZERO_CANDIDATE_CONTRACT_NOT_EXACT_ZERO")
    outer_zero_counts = (
        "A_grade_rows",
        "a_grade_rows",
        "accepted_allocation_count",
        "blocked_allocation_count",
        "candidate_allocations_projection_count",
        "hold_with_directional_expected_move_bps_count",
        "hold_zero_after_cost_with_directional_expected_move_bps_count",
        "missing_microstructure_trust_candidate_count",
        "near_A_grade_rows",
        "near_a_grade_rows",
        "non_executable_tier_publication_block_count",
        "rare_event_stress_complete_candidate_count",
        "rare_event_stress_partial_candidate_count",
        "sample_allocations_projection_count",
        "source_tier_a_grade_execution_rows",
        "source_tier_or_guardian_blocked_allocator_pass_rows",
        "unclassified_allocation_publication_block_count",
    )
    outer_empty_maps = (
        "allocator_decision_counts",
        "allocator_microstructure_block_reason_counts",
        "guardian_status_counts",
        "local_block_reason_counts",
        "microstructure_trust_status_counts",
        "paper_allocation_block_reason_counts",
        "paper_fill_block_reason_counts",
        "paper_opportunity_tier_counts",
        "paper_opportunity_tier_reason_counts",
        "selected_action_counts",
        "selected_action_expected_move_bps_sign_counts",
        "source_tier_counts",
        "strategy_router_block_reason_counts",
        "strategy_router_selected_mode_counts",
    )
    if (
        any(status.get(field) != 0 for field in outer_zero_counts)
        or any(status.get(field) != {} for field in outer_empty_maps)
        or status.get("sample_allocations") != []
    ):
        _validation("COLD_START_NOTIONAL_ZERO_CANDIDATE_OUTER_COUNTS_INVALID")
    capital = contract.get("capital")
    if type(capital) is not dict or capital != expected_capital:
        _validation("COLD_START_NOTIONAL_ZERO_CANDIDATE_CAPITAL_INVALID")
    generated_iso, generated_at = _clock(
        status.get("generated_utc"),
        reason="COLD_START_NOTIONAL_ZERO_CANDIDATE_GENERATED_TIME_INVALID",
    )
    if not generated_at <= server_at <= decision_at < expires_at:
        _validation("COLD_START_NOTIONAL_ZERO_CANDIDATE_CLOCK_ORDER_INVALID")
    return (
        batch,
        result,
        address,
        payload,
        generated_iso,
        server_at,
        expires_at,
    )


def _validated_portfolio(
    payload: Mapping[str, Any],
    *,
    server_at: datetime,
    decision_at: datetime,
) -> tuple[str, float]:
    required_margin = {
        "schema_version": "paper_account_margin_v1",
        "status": "PASS",
        "source": "POST_LIFECYCLE_CANONICAL_OPEN_POSITIONS",
        "accounting_complete": True,
        "control_inputs_valid": True,
        "admission_inputs_valid": True,
        "margin_buffer_input_valid": True,
        "newly_reserved_margin_input_valid": True,
        "reservations_included_in_open_positions_input_valid": True,
        "margin_buffer_invariant_holds": True,
        "no_negative_free_margin": True,
        "invariant": True,
        "invariant_holds": True,
        "numeric_invariant_holds": True,
        "margin_base_available": True,
        "used_margin_aggregation_valid": True,
        "projected_used_margin_aggregation_valid": True,
        "open_position_collection_complete": True,
        "open_position_canonical_identities_unique": True,
        "newly_reserved_included_in_used_margin": True,
        "pre_lifecycle_reservation_invariant_holds": True,
        "cycle_reserved_candidate_count": 0,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    if any(payload.get(key) != value for key, value in required_margin.items()):
        _validation("COLD_START_NOTIONAL_PORTFOLIO_MARGIN_CONTRACT_INVALID")
    if (
        payload.get("failure_reasons") != []
        or payload.get("invalid_open_position_margin_rows") != []
        or payload.get("invalid_open_position_margin_count") != 0
        or payload.get("duplicate_open_position_identity_group_count") != 0
        or payload.get("duplicate_open_position_identity_row_count") != 0
        or payload.get("open_position_collection_iteration_invalid_reason") is not None
        or payload.get("newly_reserved_margin_usd") != 0.0
        or payload.get("newly_reserved_margin_unrounded_usd") != 0.0
    ):
        _validation("COLD_START_NOTIONAL_PORTFOLIO_MARGIN_FAILURE_REASONS_PRESENT")
    margin_base = _decimal(
        payload.get("margin_base_usd"),
        reason="COLD_START_NOTIONAL_MARGIN_BASE_INVALID",
    )
    used_margin = _decimal(
        payload.get("used_margin_usd"),
        reason="COLD_START_NOTIONAL_USED_MARGIN_INVALID",
    )
    free_margin = _decimal(
        payload.get("free_margin_usd"),
        reason="COLD_START_NOTIONAL_FREE_MARGIN_INVALID",
    )
    buffer = _decimal(
        payload.get("margin_buffer_usd"),
        reason="COLD_START_NOTIONAL_MARGIN_BUFFER_INVALID",
    )
    after_buffer = _decimal(
        payload.get("free_margin_after_buffer_usd"),
        reason="COLD_START_NOTIONAL_FREE_MARGIN_AFTER_BUFFER_INVALID",
    )
    if (
        abs(margin_base - (used_margin + free_margin))
        > _USD_SERIALIZATION_QUANTUM
        or abs(after_buffer - (free_margin - buffer))
        > _USD_SERIALIZATION_QUANTUM
        or after_buffer <= 0
        or abs(
            _decimal(
                payload.get("usable_margin_after_buffer_before_reservations_usd"),
                reason="COLD_START_NOTIONAL_USABLE_MARGIN_AFTER_BUFFER_INVALID",
            )
            - after_buffer
        )
        > _USD_SERIALIZATION_QUANTUM
    ):
        _validation("COLD_START_NOTIONAL_PORTFOLIO_MARGIN_RECONCILIATION_INVALID")
    generated_iso, generated_at = _clock(
        payload.get("generated_utc"),
        reason="COLD_START_NOTIONAL_PORTFOLIO_GENERATED_TIME_INVALID",
    )
    if not generated_at <= server_at <= decision_at:
        _validation("COLD_START_NOTIONAL_PORTFOLIO_CLOCK_ORDER_INVALID")
    return generated_iso, float(after_buffer)


def _market_expiry(
    batch: AtomicRedisSourceReadBatch,
    *,
    decision_at: datetime,
) -> tuple[datetime, datetime]:
    _, server_at = _clock(
        batch.server_observed_at,
        reason="COLD_START_NOTIONAL_MARKET_SERVER_TIME_INVALID",
    )
    if server_at > decision_at:
        _validation("COLD_START_NOTIONAL_MARKET_CAPTURE_AFTER_DECISION")
    expiries: list[datetime] = []
    for result in batch.results:
        if type(result.pttl_ms) is not int or result.pttl_ms <= 0:
            _validation("COLD_START_NOTIONAL_MARKET_PERSISTED_EXPIRY_MISSING")
        expiries.append(server_at + timedelta(milliseconds=result.pttl_ms))
    expires_at = min(expiries)
    if decision_at >= expires_at:
        _validation("COLD_START_NOTIONAL_MARKET_EXPIRED_AT_DECISION")
    return server_at, expires_at


def _derive_inputs(
    *,
    control_atomic_capture: object,
    market_atomic_capture: object,
    store: ImmutableSourcePayloadStore,
    symbol: object,
    feature_snapshot_identity: object,
    feature_snapshot_decision_time: object,
) -> _DerivedInputs:
    resolved_symbol = _symbol(symbol)
    snapshot_identity = _snapshot_identity(feature_snapshot_identity)
    decision_iso, decision_at = _decision_clock(feature_snapshot_decision_time)
    (
        zero_candidate_batch,
        _zero_candidate_result,
        zero_candidate_address,
        zero_candidate_bytes,
        zero_candidate_generated_iso,
        zero_candidate_server_at,
        zero_candidate_expires_at,
    ) = _validated_zero_candidate_capture(
        control_atomic_capture,
        store=store,
        decision_at=decision_at,
    )
    (
        portfolio_batch,
        _portfolio_result,
        portfolio_payload,
        portfolio_address,
        portfolio_bytes,
        portfolio_server_at,
        portfolio_expires_at,
    ) = _validated_portfolio_capture(
        control_atomic_capture,
        store=store,
        decision_at=decision_at,
    )
    margin_generated_iso, free_margin_after_buffer = _validated_portfolio(
        portfolio_payload,
        server_at=portfolio_server_at,
        decision_at=decision_at,
    )
    if margin_generated_iso != zero_candidate_generated_iso:
        _validation("COLD_START_NOTIONAL_CANDIDATE_MARGIN_CYCLE_MISMATCH")
    zero_candidate_payload = _parse_strict_json(
        zero_candidate_bytes,
        reason="COLD_START_NOTIONAL_ZERO_CANDIDATE_SOURCE_JSON_INVALID",
    )
    zero_candidate_cycle_id = _required_producer_cycle_id(
        zero_candidate_payload.get("paper_cycle_id")
    )
    margin_cycle_id = _required_producer_cycle_id(
        portfolio_payload.get("paper_cycle_id")
    )
    if zero_candidate_cycle_id != margin_cycle_id:
        _validation("COLD_START_NOTIONAL_CANDIDATE_MARGIN_CYCLE_ID_MISMATCH")
    try:
        market_payloads, market_evidence, market_objects = (
            _causal._validated_atomic_sources(  # noqa: SLF001 - shared exact ABI
                atomic_capture=market_atomic_capture,
                store=store,
                symbol=resolved_symbol,
                decision_at=decision_at,
            )
        )
    except _causal.CausalCostEvidenceV1Error as exc:
        raise CausalAdaptiveColdStartNotionalPolicyV1ValidationError(
            exc.reason
        ) from None
    market_batch = cast(AtomicRedisSourceReadBatch, market_atomic_capture)
    market_server_at, market_expires_at = _market_expiry(
        market_batch,
        decision_at=decision_at,
    )
    try:
        bids = _causal._levels(  # noqa: SLF001 - same validator used by cost evidence
            market_payloads["orderbook_depth"].get("bids"),
            side="bids",
        )
        asks = _causal._levels(  # noqa: SLF001 - same validator used by cost evidence
            market_payloads["orderbook_depth"].get("asks"),
            side="asks",
        )
    except _causal.CausalCostEvidenceV1Error as exc:
        raise CausalAdaptiveColdStartNotionalPolicyV1ValidationError(
            exc.reason
        ) from None
    bid_total = float(sum(price * quantity for price, quantity in bids))
    ask_total = float(sum(price * quantity for price, quantity in asks))
    if (
        not math.isfinite(bid_total)
        or not math.isfinite(ask_total)
        or bid_total <= 0.0
        or ask_total <= 0.0
    ):
        _validation("COLD_START_NOTIONAL_VISIBLE_BOOK_CAPACITY_INVALID")
    expected_notional = min(free_margin_after_buffer, bid_total, ask_total)
    if not math.isfinite(expected_notional) or expected_notional <= 0.0:
        _validation("COLD_START_NOTIONAL_DERIVATION_INVALID")
    try:
        _causal._validate_orderbook_sources(  # noqa: SLF001 - shared exact ABI
            depth=market_payloads["orderbook_depth"],
            features=market_payloads["orderbook_features"],
            evidence=market_evidence,
            symbol=resolved_symbol,
            decision_at=decision_at,
            expected_notional_usd=expected_notional,
        )
        _causal._validate_mark_source(  # noqa: SLF001 - shared exact ABI
            mark=market_payloads["mark_price"],
            evidence=market_evidence,
            symbol=resolved_symbol,
            decision_at=decision_at,
        )
    except _causal.CausalCostEvidenceV1Error as exc:
        raise CausalAdaptiveColdStartNotionalPolicyV1ValidationError(
            exc.reason
        ) from None
    market_generated_times = [
        _clock(
            market_evidence[role]["clocks"]["generated_at"],
            reason="COLD_START_NOTIONAL_MARKET_GENERATED_TIME_INVALID",
        )[1]
        for role in ("orderbook_depth", "orderbook_features", "mark_price")
    ]
    _, zero_candidate_generated_at = _clock(
        zero_candidate_generated_iso,
        reason="COLD_START_NOTIONAL_ZERO_CANDIDATE_GENERATED_TIME_INVALID",
    )
    derived_generated_at = max(zero_candidate_generated_at, *market_generated_times)
    available_at = max(
        zero_candidate_server_at,
        portfolio_server_at,
        market_server_at,
    )
    expires_at = min(
        zero_candidate_expires_at,
        portfolio_expires_at,
        market_expires_at,
    )
    return _DerivedInputs(
        symbol=resolved_symbol,
        snapshot_identity=snapshot_identity,
        decision_iso=decision_iso,
        decision_at=decision_at,
        producer_cycle_generated_at=zero_candidate_generated_iso,
        producer_cycle_id=zero_candidate_cycle_id,
        source_generated_at=derived_generated_at.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        server_observed_at=available_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        available_at=available_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        expires_at=expires_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        free_margin_after_buffer_usd=free_margin_after_buffer,
        total_visible_bid_notional_usd=bid_total,
        total_visible_ask_notional_usd=ask_total,
        expected_notional_usd=expected_notional,
        portfolio_batch=portfolio_batch,
        zero_candidate_batch=zero_candidate_batch,
        market_batch=market_batch,
        source_objects=(
            (zero_candidate_address, zero_candidate_bytes),
            (portfolio_address, portfolio_bytes),
            *market_objects,
        ),
    )


def _module_code_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise CausalAdaptiveColdStartNotionalPolicyV1IntegrityError(
            "COLD_START_NOTIONAL_MODULE_BYTES_UNAVAILABLE"
        ) from exc


def _self_hashed(value: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    material = dict(value)
    supplied = material.pop("receipt_sha256", None)
    if not _valid_sha256(supplied):
        _integrity(reason)
    expected = _canonical_sha256(material, reason=reason)
    if not hmac.compare_digest(cast(str, supplied), expected):
        _integrity(reason)
    return {**material, "receipt_sha256": supplied}


def _source_bindings(inputs: _DerivedInputs) -> list[dict[str, Any]]:
    roles = (
        "zero_candidate_status",
        "paper_account_margin_status",
        "orderbook_depth",
        "orderbook_features",
        "mark_price",
    )
    batches = (
        inputs.zero_candidate_batch,
        inputs.portfolio_batch,
        inputs.market_batch,
        inputs.market_batch,
        inputs.market_batch,
    )
    results = (
        inputs.zero_candidate_batch.results[0],
        inputs.portfolio_batch.results[1],
        *inputs.market_batch.results,
    )
    return [
        {
            "role": role,
            "source_key": result.source_key,
            "payload_sha256": address.payload_sha256,
            "payload_byte_count": address.payload_byte_count,
            "payload_cas_address": _address_mapping(address),
            "atomic_batch_id": batch.batch_id,
            "atomic_batch_material_sha256": batch.batch_material_sha256,
            "source_pttl_ms": result.pttl_ms,
        }
        for role, batch, result, (address, _payload) in zip(
            roles,
            batches,
            results,
            inputs.source_objects,
            strict=True,
        )
    ]


def _build_material(
    inputs: _DerivedInputs,
    *,
    module_code_sha256: str,
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    policy_source_key = causal_adaptive_cold_start_notional_policy_source_key_v1(
        inputs.symbol
    )
    try:
        causal_cost_module_code_sha256 = hashlib.sha256(
            Path(_causal.__file__).read_bytes()
        ).hexdigest()
        candidate_notional_module_code_sha256 = hashlib.sha256(
            Path(_candidate.__file__).read_bytes()
        ).hexdigest()
    except OSError as exc:
        raise CausalAdaptiveColdStartNotionalPolicyV1IntegrityError(
            "COLD_START_NOTIONAL_DEPENDENCY_MODULE_BYTES_UNAVAILABLE"
        ) from exc
    source_receipt_material = {
        "schema_version": (
            CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_SOURCE_RECEIPT_V1_SCHEMA_VERSION
        ),
        "receipt_kind": "TWO_ATOMIC_REDIS_EXACT_READ_DERIVATION",
        "policy_id": CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_ID,
        "policy_source_key": policy_source_key,
        "source_transport": "ATOMIC_REDIS_GETRANGE_PTTL_TIME_AND_IMMUTABLE_CAS",
        "source_bindings": _source_bindings(inputs),
        "symbol": inputs.symbol,
        "feature_snapshot_identity": inputs.snapshot_identity,
        "producer_cycle_generated_at": inputs.producer_cycle_generated_at,
        "producer_cycle_id": inputs.producer_cycle_id,
        "source_generated_at": inputs.source_generated_at,
        "server_observed_at": inputs.server_observed_at,
        "available_at": inputs.available_at,
        "expires_at": inputs.expires_at,
        "decision_time": inputs.decision_iso,
        "free_margin_after_buffer_usd": inputs.free_margin_after_buffer_usd,
        "total_visible_bid_notional_usd": (
            inputs.total_visible_bid_notional_usd
        ),
        "total_visible_ask_notional_usd": (
            inputs.total_visible_ask_notional_usd
        ),
        "expected_notional_usd": inputs.expected_notional_usd,
        "derivation_formula": _FORMULA,
        "candidate_supply_status": "ZERO_CANDIDATE_HASH_BOUND_COLD_START_BRANCH",
        "candidate_rows_consumed": 0,
        "candidate_fabricated": False,
        "leverage_assumption": None,
        "operator_projection_used": False,
        "implementation_contract_sha256": (
            CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256
        ),
        "policy_config_sha256": (
            CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_CONFIG_SHA256
        ),
        "module_code_sha256": module_code_sha256,
        "causal_cost_module_code_sha256": causal_cost_module_code_sha256,
        "candidate_notional_module_code_sha256": (
            candidate_notional_module_code_sha256
        ),
        "fallback_used": False,
        "static_default_used": False,
        "read_only": True,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "order_authority": False,
    }
    source_receipt = {
        **source_receipt_material,
        "receipt_sha256": _canonical_sha256(
            source_receipt_material,
            reason="COLD_START_NOTIONAL_SOURCE_RECEIPT_INVALID",
        ),
    }
    version_material = {
        "schema_version": "causal_adaptive_cold_start_notional_version_material_v1",
        "source_read_receipt_sha256": source_receipt["receipt_sha256"],
        "implementation_contract_sha256": (
            CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256
        ),
        "policy_config_sha256": (
            CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_CONFIG_SHA256
        ),
        "module_code_sha256": module_code_sha256,
        "causal_cost_module_code_sha256": causal_cost_module_code_sha256,
        "candidate_notional_module_code_sha256": (
            candidate_notional_module_code_sha256
        ),
    }
    policy_version = "sha256:" + _canonical_sha256(
        version_material,
        reason="COLD_START_NOTIONAL_POLICY_VERSION_INVALID",
    )
    artifact = {
        "schema_version": CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
        "symbol": inputs.symbol,
        "feature_snapshot_identity": inputs.snapshot_identity,
        "value_unit": "USD",
        "expected_notional_usd": inputs.expected_notional_usd,
        "policy_id": CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_ID,
        "policy_version": policy_version,
        "policy_source_key": policy_source_key,
        "effective_at": inputs.source_generated_at,
        "available_at": inputs.available_at,
        "expires_at": inputs.expires_at,
        "causality_scope": "FEATURE_SNAPSHOT_DECISION_EXPECTED_EXECUTION_NOTIONAL",
        "fallback_used": False,
        "static_default_used": False,
    }
    return source_receipt, policy_version, artifact, version_material


def _compatible_receipt(
    *,
    artifact_address: SourcePayloadAddress,
    inputs: _DerivedInputs,
) -> dict[str, Any]:
    policy_source_key = causal_adaptive_cold_start_notional_policy_source_key_v1(
        inputs.symbol
    )
    material = {
        "schema_version": CAUSAL_COST_NOTIONAL_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "DIRECT_READ",
        "artifact_payload_sha256": artifact_address.payload_sha256,
        "artifact_payload_byte_count": artifact_address.payload_byte_count,
        "policy_source_key": policy_source_key,
        "source_schema_version": CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
        "source_transport": CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_SOURCE_TRANSPORT,
        "symbol": inputs.symbol,
        "feature_snapshot_identity": inputs.snapshot_identity,
        "effective_at": inputs.source_generated_at,
        "available_at": inputs.available_at,
        "expires_at": inputs.expires_at,
        "authority_scope": "FEATURE_SNAPSHOT_CAUSAL_EXPECTED_NOTIONAL",
    }
    return {
        **material,
        "receipt_sha256": _canonical_sha256(
            material,
            reason="COLD_START_NOTIONAL_COMPATIBLE_RECEIPT_INVALID",
        ),
    }


def build_causal_adaptive_cold_start_notional_policy_v1(
    *,
    control_atomic_capture: object,
    market_atomic_capture: object,
    source_payload_store: object,
    symbol: object,
    feature_snapshot_identity: object,
    feature_snapshot_decision_time: object,
) -> CausalAdaptiveColdStartNotionalPolicyTokenV1:
    """Build one adaptive no-default cold-start cost-probe artifact."""

    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _validation("COLD_START_NOTIONAL_IMMUTABLE_SOURCE_PAYLOAD_STORE_REQUIRED")
    store = cast(ImmutableSourcePayloadStore, source_payload_store)
    inputs = _derive_inputs(
        control_atomic_capture=control_atomic_capture,
        market_atomic_capture=market_atomic_capture,
        store=store,
        symbol=symbol,
        feature_snapshot_identity=feature_snapshot_identity,
        feature_snapshot_decision_time=feature_snapshot_decision_time,
    )
    module_hash = _module_code_sha256()
    source_receipt, policy_version, artifact, _version_material = _build_material(
        inputs,
        module_code_sha256=module_hash,
    )
    source_receipt_bytes = _canonical_bytes(
        source_receipt,
        reason="COLD_START_NOTIONAL_SOURCE_RECEIPT_INVALID",
    )
    source_receipt_address = _put_exact(
        store,
        source_receipt_bytes,
        reason="COLD_START_NOTIONAL_SOURCE_RECEIPT_CAS_FAILED",
    )
    artifact_bytes = _canonical_bytes(
        artifact,
        reason="COLD_START_NOTIONAL_ARTIFACT_INVALID",
    )
    artifact_address = _put_exact(
        store,
        artifact_bytes,
        reason="COLD_START_NOTIONAL_ARTIFACT_CAS_FAILED",
    )
    compatible_receipt = _compatible_receipt(
        artifact_address=artifact_address,
        inputs=inputs,
    )
    compatible_receipt_bytes = _canonical_bytes(
        compatible_receipt,
        reason="COLD_START_NOTIONAL_COMPATIBLE_RECEIPT_INVALID",
    )
    compatible_receipt_address = _put_exact(
        store,
        compatible_receipt_bytes,
        reason="COLD_START_NOTIONAL_COMPATIBLE_RECEIPT_CAS_FAILED",
    )
    token = CausalAdaptiveColdStartNotionalPolicyTokenV1(
        schema_version=CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_V1_SCHEMA_VERSION,
        symbol=inputs.symbol,
        feature_snapshot_identity=inputs.snapshot_identity,
        expected_notional_usd=inputs.expected_notional_usd,
        policy_version=policy_version,
        source_generated_at=inputs.source_generated_at,
        server_observed_at=inputs.server_observed_at,
        available_at=inputs.available_at,
        expires_at=inputs.expires_at,
        decision_time=inputs.decision_iso,
        free_margin_after_buffer_usd=inputs.free_margin_after_buffer_usd,
        total_visible_bid_notional_usd=inputs.total_visible_bid_notional_usd,
        total_visible_ask_notional_usd=inputs.total_visible_ask_notional_usd,
        source_read_receipt_bytes=source_receipt_bytes,
        source_read_receipt_address=source_receipt_address,
        source_read_receipt_sha256=source_receipt["receipt_sha256"],
        notional_artifact_bytes=artifact_bytes,
        notional_artifact_address=artifact_address,
        notional_receipt_bytes=compatible_receipt_bytes,
        notional_receipt_address=compatible_receipt_address,
        notional_receipt_sha256=compatible_receipt["receipt_sha256"],
        implementation_contract_sha256=(
            CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256
        ),
        policy_config_sha256=(
            CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_CONFIG_SHA256
        ),
        module_code_sha256=module_hash,
        _control_capture=inputs.zero_candidate_batch,
        _market_capture=inputs.market_batch,
        _source_objects=inputs.source_objects,
        _store=store,
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    _validate_token(token)
    return token


def _validate_token(token: object) -> dict[str, Any]:
    if type(token) is not CausalAdaptiveColdStartNotionalPolicyTokenV1:
        _integrity("COLD_START_NOTIONAL_FACTORY_TOKEN_TYPE_INVALID")
    typed = cast(CausalAdaptiveColdStartNotionalPolicyTokenV1, token)
    if (
        typed._construction_token is not _CONSTRUCTION_TOKEN
        or type(typed._store) is not ImmutableSourcePayloadStore
        or typed.schema_version
        != CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_V1_SCHEMA_VERSION
        or typed.read_only is not True
        or typed.trainer_authority is not False
        or typed.prediction_authority is not False
        or typed.paper_authority is not False
        or typed.live_authority is not False
        or typed.order_authority is not False
        or typed.fallback_used is not False
        or typed.static_default_used is not False
    ):
        _integrity("COLD_START_NOTIONAL_FACTORY_TOKEN_FLAGS_INVALID")
    _, decision_at = _clock(
        typed.decision_time,
        reason="COLD_START_NOTIONAL_DECISION_TIME_INVALID",
    )
    inputs = _derive_inputs(
        control_atomic_capture=typed._control_capture,
        market_atomic_capture=typed._market_capture,
        store=typed._store,
        symbol=typed.symbol,
        feature_snapshot_identity=typed.feature_snapshot_identity,
        feature_snapshot_decision_time=decision_at,
    )
    if len(inputs.source_objects) != len(typed._source_objects):
        _integrity("COLD_START_NOTIONAL_SOURCE_OBJECT_COUNT_INVALID")
    for (expected_address, expected_payload), (address, payload) in zip(
        inputs.source_objects,
        typed._source_objects,
        strict=True,
    ):
        if expected_address != address or not hmac.compare_digest(
            expected_payload, payload
        ):
            _integrity("COLD_START_NOTIONAL_SOURCE_OBJECT_BINDING_INVALID")
        _readback_exact(
            typed._store,
            address,
            payload,
            reason="COLD_START_NOTIONAL_SOURCE_OBJECT_READBACK_FAILED",
        )
    module_hash = _module_code_sha256()
    source_receipt, policy_version, artifact, version_material = _build_material(
        inputs,
        module_code_sha256=module_hash,
    )
    if (
        frozenset(source_receipt)
        != CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_SOURCE_RECEIPT_FIELDS
    ):
        _integrity("COLD_START_NOTIONAL_SOURCE_RECEIPT_FIELDS_INVALID")
    _self_hashed(
        source_receipt,
        reason="COLD_START_NOTIONAL_SOURCE_RECEIPT_SELF_HASH_INVALID",
    )
    source_receipt_bytes = _canonical_bytes(
        source_receipt,
        reason="COLD_START_NOTIONAL_SOURCE_RECEIPT_INVALID",
    )
    if not hmac.compare_digest(
        source_receipt_bytes, typed.source_read_receipt_bytes
    ):
        _integrity("COLD_START_NOTIONAL_SOURCE_RECEIPT_TOKEN_BINDING_INVALID")
    _readback_exact(
        typed._store,
        typed.source_read_receipt_address,
        typed.source_read_receipt_bytes,
        reason="COLD_START_NOTIONAL_SOURCE_RECEIPT_READBACK_FAILED",
    )
    artifact_bytes = _canonical_bytes(
        artifact,
        reason="COLD_START_NOTIONAL_ARTIFACT_INVALID",
    )
    if not hmac.compare_digest(artifact_bytes, typed.notional_artifact_bytes):
        _integrity("COLD_START_NOTIONAL_ARTIFACT_TOKEN_BINDING_INVALID")
    _readback_exact(
        typed._store,
        typed.notional_artifact_address,
        typed.notional_artifact_bytes,
        reason="COLD_START_NOTIONAL_ARTIFACT_READBACK_FAILED",
    )
    compatible_receipt = _compatible_receipt(
        artifact_address=typed.notional_artifact_address,
        inputs=inputs,
    )
    _self_hashed(
        compatible_receipt,
        reason="COLD_START_NOTIONAL_COMPATIBLE_RECEIPT_SELF_HASH_INVALID",
    )
    compatible_receipt_bytes = _canonical_bytes(
        compatible_receipt,
        reason="COLD_START_NOTIONAL_COMPATIBLE_RECEIPT_INVALID",
    )
    if not hmac.compare_digest(
        compatible_receipt_bytes, typed.notional_receipt_bytes
    ):
        _integrity("COLD_START_NOTIONAL_COMPATIBLE_RECEIPT_TOKEN_BINDING_INVALID")
    _readback_exact(
        typed._store,
        typed.notional_receipt_address,
        typed.notional_receipt_bytes,
        reason="COLD_START_NOTIONAL_COMPATIBLE_RECEIPT_READBACK_FAILED",
    )
    if (
        typed.expected_notional_usd != inputs.expected_notional_usd
        or typed.policy_version != policy_version
        or typed.source_generated_at != inputs.source_generated_at
        or typed.server_observed_at != inputs.server_observed_at
        or typed.available_at != inputs.available_at
        or typed.expires_at != inputs.expires_at
        or typed.decision_time != inputs.decision_iso
        or typed.free_margin_after_buffer_usd
        != inputs.free_margin_after_buffer_usd
        or typed.total_visible_bid_notional_usd
        != inputs.total_visible_bid_notional_usd
        or typed.total_visible_ask_notional_usd
        != inputs.total_visible_ask_notional_usd
        or typed.source_read_receipt_sha256 != source_receipt["receipt_sha256"]
        or typed.notional_receipt_sha256 != compatible_receipt["receipt_sha256"]
        or typed.implementation_contract_sha256
        != CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256
        or typed.policy_config_sha256
        != CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_CONFIG_SHA256
        or typed.module_code_sha256 != module_hash
    ):
        _integrity("COLD_START_NOTIONAL_FACTORY_TOKEN_BINDING_INVALID")
    return {
        "schema_version": typed.schema_version,
        "classification": CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_CLASSIFICATION,
        "policy_version_material": version_material,
        "source_read_receipt": dict(source_receipt),
        "source_read_receipt_cas_address": _address_mapping(
            typed.source_read_receipt_address
        ),
        "notional_artifact": dict(artifact),
        "notional_artifact_cas_address": _address_mapping(
            typed.notional_artifact_address
        ),
        "notional_receipt": dict(compatible_receipt),
        "notional_receipt_cas_address": _address_mapping(
            typed.notional_receipt_address
        ),
        "read_only": True,
        "trainer_authority": False,
        "prediction_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "order_authority": False,
        "fallback_used": False,
        "static_default_used": False,
    }


__all__ = [
    "CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_CLASSIFICATION",
    "CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256",
    "CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_CONFIG_SHA256",
    "CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_ID",
    "CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_SOURCE_KEY_TEMPLATE",
    "CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_SOURCE_RECEIPT_FIELDS",
    "CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_V1_SCHEMA_VERSION",
    "CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY",
    "CausalAdaptiveColdStartNotionalPolicyTokenV1",
    "CausalAdaptiveColdStartNotionalPolicyV1Error",
    "CausalAdaptiveColdStartNotionalPolicyV1IntegrityError",
    "CausalAdaptiveColdStartNotionalPolicyV1ValidationError",
    "build_causal_adaptive_cold_start_notional_policy_v1",
    "causal_adaptive_cold_start_notional_policy_source_key_v1",
]
