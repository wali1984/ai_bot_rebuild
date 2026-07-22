"""Factory-only causal expected-notional evidence for cost replay.

The paper loop publishes an operator status whose displayed allocation rows are
an intentionally truncated projection.  This module never derives a notional
from those rows.  It verifies the hash-bound canonical aggregate covering all
candidate rows and computes exactly::

    capital.numeric_sums.gross_notional_usd / capital.candidate_count

The resulting value is a decision-time label input used only to walk an order
book for counterfactual execution-cost estimation.  It is not a position-size,
order, paper-fill, prediction, or live-execution authority.

The outer Redis value is retained byte-for-byte in immutable CAS.  Its current
producer uses ordinary ``json.dumps`` rather than canonical serialization, so
outer whitespace and member order are deliberately not normalized or trusted.
JSON is nevertheless parsed strictly (duplicate members, non-finite numbers,
and malformed UTF-8 fail closed).  Only the embedded aggregate contract is
canonicalized and checked against its producer self-hash.
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

CAUSAL_EXPECTED_NOTIONAL_POLICY_V1_SCHEMA_VERSION: Final = (
    "causal_expected_notional_policy_factory_token_v1"
)
CAUSAL_EXPECTED_NOTIONAL_SOURCE_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "causal_expected_notional_atomic_source_read_receipt_v1"
)
CAUSAL_EXPECTED_NOTIONAL_POLICY_ID: Final = "paper-adaptive-sizing-canonical-aggregate-mean-v1"
CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY: Final = "v2:paper:adaptive_sizing_runtime_status"
CAUSAL_EXPECTED_NOTIONAL_SOURCE_ALLOCATOR: Final = "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR"
CAUSAL_EXPECTED_NOTIONAL_SOURCE_PRODUCER: Final = "v2_trade_management_paper_loop"
CAUSAL_EXPECTED_NOTIONAL_SOURCE_TRANSPORT: Final = "DURABLE_CAUSAL_POLICY_LEDGER"
CAUSAL_EXPECTED_NOTIONAL_CLASSIFICATION: Final = (
    "LABEL_ONLY_COUNTERFACTUAL_EXPECTED_ALLOCATOR_NOTIONAL_NO_EXECUTION_AUTHORITY"
)
CAUSAL_EXPECTED_NOTIONAL_DOWNSTREAM_STATUS: Final = (
    "FACTORY_ONLY_UNWIRED_NO_TRAINER_PREDICTION_PAPER_OR_LIVE_AUTHORITY"
)
CAUSAL_EXPECTED_NOTIONAL_ZERO_CANDIDATE_REASON: Final = (
    "EXPECTED_NOTIONAL_CANDIDATE_SUPPLY_ZERO_NO_POLICY_ARTIFACT"
)

_AGGREGATE_SCHEMA = "paper_candidate_canonical_aggregate_contract_v1"
_AGGREGATE_HASH_ALGORITHM = "sha256(canonical-json-v1)"
_FORMULA = "capital.numeric_sums.gross_notional_usd/capital.candidate_count"
_CONSTRUCTION_TOKEN = object()
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,511}$", re.ASCII)

_IMPLEMENTATION_CONTRACT: Final = {
    "schema_version": "causal_expected_notional_implementation_contract_v1",
    "policy_id": CAUSAL_EXPECTED_NOTIONAL_POLICY_ID,
    "source_key": CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
    "source_allocator": CAUSAL_EXPECTED_NOTIONAL_SOURCE_ALLOCATOR,
    "source_producer": CAUSAL_EXPECTED_NOTIONAL_SOURCE_PRODUCER,
    "source_transport": "ONE_ATOMIC_REDIS_GETRANGE_PTTL_TIME_BATCH",
    "source_outer_serialization": "EXACT_BYTES_STRICT_JSON_NOT_CANONICALIZED",
    "aggregate_schema": _AGGREGATE_SCHEMA,
    "aggregate_hash_algorithm": _AGGREGATE_HASH_ALGORITHM,
    "denominator": "capital.candidate_count_covering_all_contract_rows",
    "numerator": "capital.numeric_sums.gross_notional_usd_covering_all_contract_rows",
    "formula": _FORMULA,
    "operator_projection_used": False,
    "expiry": "redis_server_observed_at_plus_source_pttl",
    "consumer_age_threshold": None,
    "fallbacks": [],
    "static_defaults": [],
    "authority": "NONE_LABEL_ONLY",
}
_POLICY_CONFIG: Final = {
    "schema_version": "causal_expected_notional_policy_config_v1",
    "policy_id": CAUSAL_EXPECTED_NOTIONAL_POLICY_ID,
    "source_key": CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
    "aggregate_schema": _AGGREGATE_SCHEMA,
    "formula": _FORMULA,
    "projection_inputs": [],
    "fallback_values": [],
    "static_default_notional_usd": None,
}

_SOURCE_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_kind",
        "source_key",
        "source_transport",
        "atomic_batch_id",
        "atomic_batch_material_sha256",
        "raw_status_payload_sha256",
        "raw_status_payload_byte_count",
        "raw_status_cas_address",
        "source_pttl_ms",
        "source_generated_at",
        "server_observed_at",
        "available_at",
        "expires_at",
        "decision_time",
        "symbol",
        "feature_snapshot_identity",
        "embedded_aggregate_contract_hash",
        "aggregate_candidate_count",
        "aggregate_gross_notional_usd",
        "expected_notional_usd",
        "candidate_supply_status",
        "zero_candidate_handling",
        "derivation_formula",
        "policy_id",
        "implementation_contract_sha256",
        "policy_config_sha256",
        "module_code_sha256",
        "outer_status_canonical_serialization_required",
        "operator_projection_used",
        "fallback_used",
        "static_default_used",
        "read_only",
        "trainer_authority",
        "prediction_authority",
        "paper_authority",
        "live_authority",
        "order_authority",
        "receipt_sha256",
    }
)
CAUSAL_EXPECTED_NOTIONAL_SOURCE_RECEIPT_FIELDS: Final = _SOURCE_RECEIPT_FIELDS
_COMPATIBLE_ARTIFACT_FIELDS = frozenset(
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
_COMPATIBLE_RECEIPT_FIELDS = frozenset(
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


class CausalExpectedNotionalPolicyV1Error(RuntimeError):
    """Base fail-closed error with a stable, data-safe reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class CausalExpectedNotionalPolicyV1ValidationError(CausalExpectedNotionalPolicyV1Error):
    """Caller input or source content violates the policy contract."""


class CausalExpectedNotionalPolicyV1IntegrityError(CausalExpectedNotionalPolicyV1Error):
    """A transport binding, CAS object, receipt, or factory token changed."""


@dataclass(frozen=True, slots=True)
class CausalExpectedNotionalPolicyTokenV1:
    """Factory-sealed expected-notional artifact compatible with cost evidence."""

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
    embedded_aggregate_contract_hash: str
    aggregate_candidate_count: int
    aggregate_gross_notional_usd: float
    raw_status_bytes: bytes = field(repr=False)
    raw_status_address: SourcePayloadAddress
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
    _atomic_capture: AtomicRedisSourceReadBatch = field(repr=False, compare=False)
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


def _validation(reason: str) -> NoReturn:
    raise CausalExpectedNotionalPolicyV1ValidationError(reason) from None


def _integrity(reason: str) -> NoReturn:
    raise CausalExpectedNotionalPolicyV1IntegrityError(reason) from None


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


CAUSAL_EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256: Final = _canonical_sha256(
    _IMPLEMENTATION_CONTRACT,
    reason="EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_INVALID",
)
CAUSAL_EXPECTED_NOTIONAL_POLICY_CONFIG_SHA256: Final = _canonical_sha256(
    _POLICY_CONFIG,
    reason="EXPECTED_NOTIONAL_POLICY_CONFIG_INVALID",
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
        raise CausalExpectedNotionalPolicyV1IntegrityError(reason) from exc
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
    address: object,
    expected: object,
    *,
    reason: str,
) -> None:
    if type(address) is not SourcePayloadAddress or type(expected) is not bytes:
        _integrity(reason)
    typed_address = cast(SourcePayloadAddress, address)
    payload = cast(bytes, expected)
    digest = hashlib.sha256(payload).hexdigest()
    try:
        readback = store.get(digest, expected_byte_count=len(payload))
    except SourcePayloadStoreError as exc:
        raise CausalExpectedNotionalPolicyV1IntegrityError(reason) from exc
    if (
        typed_address.schema_version != SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION
        or typed_address.payload_sha256 != digest
        or typed_address.payload_byte_count != len(payload)
        or not hmac.compare_digest(readback, payload)
    ):
        _integrity(reason)


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


def _parse_strict_outer_json(payload: bytes) -> dict[str, Any]:
    try:
        decoded = payload.decode("utf-8", errors="strict")
        parsed = json.loads(
            decoded,
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
        _validation("EXPECTED_NOTIONAL_SOURCE_JSON_INVALID")
    if type(parsed) is not dict:
        _validation("EXPECTED_NOTIONAL_SOURCE_JSON_ROOT_INVALID")
    return cast(dict[str, Any], parsed)


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
        _validation("EXPECTED_NOTIONAL_DECISION_TIME_INVALID")
    parsed = cast(datetime, value)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        _validation("EXPECTED_NOTIONAL_DECISION_TIME_INVALID")
    parsed = parsed.astimezone(UTC)
    if parsed <= _EPOCH:
        _validation("EXPECTED_NOTIONAL_DECISION_TIME_INVALID")
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z"), parsed


def _symbol(value: object) -> str:
    if type(value) is not str or _SYMBOL_RE.fullmatch(value) is None:
        _validation("EXPECTED_NOTIONAL_SYMBOL_INVALID")
    return value


def _snapshot_identity(value: object) -> str:
    if type(value) is not str or value != value.strip() or _LABEL_RE.fullmatch(value) is None:
        _validation("EXPECTED_NOTIONAL_FEATURE_SNAPSHOT_IDENTITY_INVALID")
    return value


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


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
                "server_time_is_consumer_observed_at": (result.server_time_is_consumer_observed_at),
                "source_finality_attested": result.source_finality_attested,
                "source_key": result.source_key,
                "source_key_sha256": result.source_key_sha256,
                "source_schema_attested": result.source_schema_attested,
                "transport_authenticity_attested": (result.transport_authenticity_attested),
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


def _validated_atomic_source(
    batch_input: object,
    *,
    decision_at: datetime,
) -> tuple[AtomicRedisSourceReadBatch, AtomicRedisSourceResult, bytes, datetime, str]:
    if type(batch_input) is not AtomicRedisSourceReadBatch:
        _validation("EXPECTED_NOTIONAL_ATOMIC_CAPTURE_TYPE_INVALID")
    batch = cast(AtomicRedisSourceReadBatch, batch_input)
    if (
        batch.schema_version != ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION
        or type(batch.results) is not tuple
        or len(batch.results) != 1
        or type(batch.results[0]) is not AtomicRedisSourceResult
    ):
        _integrity("EXPECTED_NOTIONAL_ATOMIC_CAPTURE_SHAPE_INVALID")
    result = batch.results[0]
    try:
        server_at = _EPOCH + timedelta(
            seconds=batch.server_time_seconds,
            microseconds=batch.server_time_microseconds,
        )
    except (OverflowError, TypeError, ValueError):
        _integrity("EXPECTED_NOTIONAL_ATOMIC_SERVER_CLOCK_INVALID")
    server_iso = server_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if server_iso != batch.server_observed_at:
        _integrity("EXPECTED_NOTIONAL_ATOMIC_SERVER_CLOCK_INVALID")
    if server_at > decision_at:
        _validation("EXPECTED_NOTIONAL_ATOMIC_CAPTURE_AFTER_DECISION")

    expected_material = _expected_atomic_batch_material(batch)
    expected_hash = hashlib.sha256(expected_material.encode("ascii")).hexdigest()
    if (
        batch.batch_material_json != expected_material
        or batch.batch_material_sha256 != expected_hash
        or batch.batch_id != f"trainer_atomic_redis_source_read_v2_{expected_hash}"
    ):
        _integrity("EXPECTED_NOTIONAL_ATOMIC_CAPTURE_BINDING_INVALID")

    payload = result.exact_payload_bytes
    if (
        result.schema_version != ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION
        or result.source_key != CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY
        or result.source_key_sha256
        != hashlib.sha256(CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY.encode("ascii")).hexdigest()
    ):
        _integrity("EXPECTED_NOTIONAL_ATOMIC_SOURCE_KEY_BINDING_INVALID")
    if (
        result.redis_type != "string"
        or result.present is not True
        or type(payload) is not bytes
        or not payload
    ):
        _validation("EXPECTED_NOTIONAL_SOURCE_MISSING")
    payload = cast(bytes, payload)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    if (
        result.payload_sha256 != payload_sha256
        or result.payload_byte_count != len(payload)
        or batch.total_payload_byte_count != len(payload)
        or result.server_observed_at != batch.server_observed_at
    ):
        _integrity("EXPECTED_NOTIONAL_ATOMIC_SOURCE_PAYLOAD_BINDING_INVALID")
    if type(result.pttl_ms) is not int or result.pttl_ms <= 0:
        _validation("EXPECTED_NOTIONAL_SOURCE_PERSISTED_EXPIRY_MISSING")
    try:
        expires_at = server_at + timedelta(milliseconds=result.pttl_ms)
    except (OverflowError, TypeError, ValueError):
        _validation("EXPECTED_NOTIONAL_SOURCE_EXPIRY_INVALID")
    if decision_at >= expires_at:
        _validation("EXPECTED_NOTIONAL_SOURCE_EXPIRED_AT_DECISION")
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
        _integrity("EXPECTED_NOTIONAL_ATOMIC_SOURCE_FLAGS_INVALID")
    expires_iso = expires_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return batch, result, payload, server_at, expires_iso


def _verified_status_aggregate(
    status: Mapping[str, Any],
) -> tuple[str, int, float, float, str]:
    if (
        status.get("allocator") != CAUSAL_EXPECTED_NOTIONAL_SOURCE_ALLOCATOR
        or status.get("candidate_allocations_complete") is not False
    ):
        _validation("EXPECTED_NOTIONAL_SOURCE_IDENTITY_INVALID")
    contract = status.get("candidate_allocations_canonical_aggregate_contract")
    if type(contract) is not dict:
        _validation("EXPECTED_NOTIONAL_CANONICAL_AGGREGATE_MISSING")
    contract = cast(dict[str, Any], contract)
    embedded_hash = contract.get("contract_hash")
    if not _valid_sha256(embedded_hash):
        _validation("EXPECTED_NOTIONAL_CANONICAL_AGGREGATE_HASH_INVALID")
    material = dict(contract)
    material.pop("contract_hash")
    recomputed_hash = _canonical_sha256(
        material,
        reason="EXPECTED_NOTIONAL_CANONICAL_AGGREGATE_MATERIAL_INVALID",
    )
    if not hmac.compare_digest(cast(str, embedded_hash), recomputed_hash):
        _integrity("EXPECTED_NOTIONAL_CANONICAL_AGGREGATE_HASH_MISMATCH")
    if (
        contract.get("schema_version") != _AGGREGATE_SCHEMA
        or contract.get("producer") != CAUSAL_EXPECTED_NOTIONAL_SOURCE_PRODUCER
        or contract.get("paper_only") is not True
        or contract.get("contract_hash_algorithm") != _AGGREGATE_HASH_ALGORITHM
        or contract.get("operator_projection_is_canonical_evidence") is not False
        or contract.get("source_rows_all_hashable") is not True
        or contract.get("contract_fact_hashes_all_hashable") is not True
    ):
        _validation("EXPECTED_NOTIONAL_CANONICAL_AGGREGATE_CONTRACT_INVALID")

    raw_count = contract.get("source_row_count")
    if type(raw_count) is not int or raw_count < 0:
        _validation("EXPECTED_NOTIONAL_CANDIDATE_COUNT_INVALID")
    if raw_count == 0:
        _validation(CAUSAL_EXPECTED_NOTIONAL_ZERO_CANDIDATE_REASON)
    count = raw_count
    count_fields = (
        status.get("paper_candidates_with_allocation"),
        status.get("candidate_allocation_count"),
        status.get("candidate_allocations_source_row_count"),
        contract.get("contract_evaluated_row_count"),
    )
    if any(type(value) is not int or value != count for value in count_fields):
        _integrity("EXPECTED_NOTIONAL_SOURCE_COUNT_MISMATCH")

    source_entries = status.get("candidate_allocations_source_hashes")
    if type(source_entries) is not list or len(source_entries) != count:
        _integrity("EXPECTED_NOTIONAL_SOURCE_HASH_COUNT_MISMATCH")
    source_hashes: list[str] = []
    for index, entry in enumerate(source_entries):
        if (
            type(entry) is not dict
            or entry.get("source_row_index") != index
            or not _valid_sha256(entry.get("source_row_canonical_sha256"))
        ):
            _integrity("EXPECTED_NOTIONAL_SOURCE_HASH_BINDING_INVALID")
        source_hashes.append(cast(str, entry["source_row_canonical_sha256"]))
    source_aggregate = _canonical_sha256(
        source_hashes,
        reason="EXPECTED_NOTIONAL_SOURCE_HASH_AGGREGATE_INVALID",
    )
    if (
        status.get("candidate_allocations_all_source_rows_hashable") is not True
        or status.get("candidate_allocations_unhashable_source_row_count") != 0
        or status.get("candidate_allocations_aggregate_sha256") != source_aggregate
        or contract.get("source_rows_aggregate_sha256") != source_aggregate
    ):
        _integrity("EXPECTED_NOTIONAL_SOURCE_HASH_AGGREGATE_MISMATCH")

    fact_hashes = contract.get("contract_fact_hashes")
    if (
        type(fact_hashes) is not list
        or len(fact_hashes) != count
        or not all(_valid_sha256(value) for value in fact_hashes)
        or contract.get("contract_fact_hashes_aggregate_sha256")
        != _canonical_sha256(
            fact_hashes,
            reason="EXPECTED_NOTIONAL_FACT_HASH_AGGREGATE_INVALID",
        )
    ):
        _integrity("EXPECTED_NOTIONAL_FACT_HASH_AGGREGATE_MISMATCH")

    capital = contract.get("capital")
    if type(capital) is not dict:
        _validation("EXPECTED_NOTIONAL_CAPITAL_AGGREGATE_MISSING")
    capital = cast(dict[str, Any], capital)
    if type(capital.get("candidate_count")) is not int or capital.get("candidate_count") != count:
        _integrity("EXPECTED_NOTIONAL_CAPITAL_CANDIDATE_COUNT_MISMATCH")
    numeric_sums = capital.get("numeric_sums")
    if type(numeric_sums) is not dict:
        _validation("EXPECTED_NOTIONAL_CAPITAL_NUMERIC_SUMS_MISSING")
    raw_gross_notional = cast(dict[str, Any], numeric_sums).get("gross_notional_usd")
    if type(raw_gross_notional) not in {int, float}:
        _validation("EXPECTED_NOTIONAL_AGGREGATE_GROSS_NOTIONAL_INVALID")
    gross_notional = float(cast(int | float, raw_gross_notional))
    if not math.isfinite(gross_notional) or gross_notional < 0.0:
        _validation("EXPECTED_NOTIONAL_AGGREGATE_GROSS_NOTIONAL_INVALID")
    if gross_notional == 0.0:
        _validation("EXPECTED_NOTIONAL_AGGREGATE_GROSS_NOTIONAL_ZERO_NO_POLICY_ARTIFACT")
    expected_notional = gross_notional / count
    if not math.isfinite(expected_notional) or expected_notional <= 0.0:
        _validation("EXPECTED_NOTIONAL_DERIVATION_INVALID")
    if (
        status.get("fixed_runtime_notional_removed") is not True
        or status.get("candidate_allocations_projection_only") is not True
        or status.get("candidate_allocations_selected_before_outcome") is not True
        or status.get("candidate_allocations_future_labels_used_as_features") is not False
        or status.get("paper_only") is not True
        or status.get("places_real_order") is not False
        or status.get("test_orders") is not False
        or status.get("leverage_mutation") is not False
        or status.get("margin_mode_mutation") is not False
        or status.get("old_redis_writes") is not False
    ):
        _validation("EXPECTED_NOTIONAL_SOURCE_AUTHORITY_OR_ADAPTIVITY_INVALID")
    generated_iso, _ = _clock(
        status.get("generated_utc"),
        reason="EXPECTED_NOTIONAL_SOURCE_GENERATED_TIME_INVALID",
    )
    return recomputed_hash, count, gross_notional, expected_notional, generated_iso


def _module_code_sha256() -> str:
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError as exc:
        raise CausalExpectedNotionalPolicyV1IntegrityError(
            "EXPECTED_NOTIONAL_MODULE_BYTES_UNAVAILABLE"
        ) from exc


def _self_hashed(value: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    detached = dict(value)
    supplied = detached.pop("receipt_sha256", None)
    if not _valid_sha256(supplied):
        _integrity(reason)
    expected = _canonical_sha256(detached, reason=reason)
    if not hmac.compare_digest(cast(str, supplied), expected):
        _integrity(reason)
    return {**detached, "receipt_sha256": supplied}


def _build_material(
    *,
    batch: AtomicRedisSourceReadBatch,
    result: AtomicRedisSourceResult,
    raw_address: SourcePayloadAddress,
    symbol: str,
    feature_snapshot_identity: str,
    decision_iso: str,
    source_generated_at: str,
    server_observed_at: str,
    expires_at: str,
    embedded_hash: str,
    candidate_count: int,
    gross_notional: float,
    expected_notional: float,
    module_code_sha256: str,
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
    source_receipt_material = {
        "schema_version": CAUSAL_EXPECTED_NOTIONAL_SOURCE_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "ATOMIC_REDIS_EXACT_READ_DERIVATION",
        "source_key": CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
        "source_transport": "ATOMIC_REDIS_GETRANGE_PTTL_TIME_AND_IMMUTABLE_CAS",
        "atomic_batch_id": batch.batch_id,
        "atomic_batch_material_sha256": batch.batch_material_sha256,
        "raw_status_payload_sha256": raw_address.payload_sha256,
        "raw_status_payload_byte_count": raw_address.payload_byte_count,
        "raw_status_cas_address": _address_mapping(raw_address),
        "source_pttl_ms": result.pttl_ms,
        "source_generated_at": source_generated_at,
        "server_observed_at": server_observed_at,
        "available_at": server_observed_at,
        "expires_at": expires_at,
        "decision_time": decision_iso,
        "symbol": symbol,
        "feature_snapshot_identity": feature_snapshot_identity,
        "embedded_aggregate_contract_hash": embedded_hash,
        "aggregate_candidate_count": candidate_count,
        "aggregate_gross_notional_usd": gross_notional,
        "expected_notional_usd": expected_notional,
        "candidate_supply_status": "POSITIVE_HASH_BOUND_AGGREGATE_AVAILABLE",
        "zero_candidate_handling": "FAIL_CLOSED_NO_ARTIFACT_NO_DEFAULT",
        "derivation_formula": _FORMULA,
        "policy_id": CAUSAL_EXPECTED_NOTIONAL_POLICY_ID,
        "implementation_contract_sha256": (CAUSAL_EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256),
        "policy_config_sha256": CAUSAL_EXPECTED_NOTIONAL_POLICY_CONFIG_SHA256,
        "module_code_sha256": module_code_sha256,
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
    source_receipt_sha256 = _canonical_sha256(
        source_receipt_material,
        reason="EXPECTED_NOTIONAL_SOURCE_RECEIPT_INVALID",
    )
    source_receipt = {
        **source_receipt_material,
        "receipt_sha256": source_receipt_sha256,
    }
    version_material = {
        "schema_version": "causal_expected_notional_policy_version_material_v1",
        "source_read_receipt_sha256": source_receipt_sha256,
        "implementation_contract_sha256": (CAUSAL_EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256),
        "policy_config_sha256": CAUSAL_EXPECTED_NOTIONAL_POLICY_CONFIG_SHA256,
        "module_code_sha256": module_code_sha256,
    }
    policy_version = "sha256:" + _canonical_sha256(
        version_material,
        reason="EXPECTED_NOTIONAL_POLICY_VERSION_INVALID",
    )
    artifact = {
        "schema_version": CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
        "symbol": symbol,
        "feature_snapshot_identity": feature_snapshot_identity,
        "value_unit": "USD",
        "expected_notional_usd": expected_notional,
        "policy_id": CAUSAL_EXPECTED_NOTIONAL_POLICY_ID,
        "policy_version": policy_version,
        "policy_source_key": CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
        "effective_at": source_generated_at,
        "available_at": server_observed_at,
        "expires_at": expires_at,
        "causality_scope": "FEATURE_SNAPSHOT_DECISION_EXPECTED_EXECUTION_NOTIONAL",
        "fallback_used": False,
        "static_default_used": False,
    }
    return source_receipt, policy_version, artifact, version_material


def build_causal_expected_notional_policy_v1(
    *,
    atomic_capture: object,
    source_payload_store: object,
    symbol: object,
    feature_snapshot_identity: object,
    feature_snapshot_decision_time: object,
) -> CausalExpectedNotionalPolicyTokenV1:
    """Build one no-fallback expected-notional artifact from exact Redis bytes."""

    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _validation("EXPECTED_NOTIONAL_IMMUTABLE_SOURCE_PAYLOAD_STORE_REQUIRED")
    store = cast(ImmutableSourcePayloadStore, source_payload_store)
    resolved_symbol = _symbol(symbol)
    snapshot_identity = _snapshot_identity(feature_snapshot_identity)
    decision_iso, decision_at = _decision_clock(feature_snapshot_decision_time)
    batch, result, raw_bytes, server_at, expires_iso = _validated_atomic_source(
        atomic_capture,
        decision_at=decision_at,
    )

    # Preserve the exact operational status before attempting semantic parsing.
    raw_address = _put_exact(
        store,
        raw_bytes,
        reason="EXPECTED_NOTIONAL_RAW_STATUS_CAS_FAILED",
    )
    status = _parse_strict_outer_json(raw_bytes)
    embedded_hash, count, gross_notional, expected_notional, generated_iso = (
        _verified_status_aggregate(status)
    )
    _, generated_at = _clock(
        generated_iso,
        reason="EXPECTED_NOTIONAL_SOURCE_GENERATED_TIME_INVALID",
    )
    if generated_at > server_at or generated_at > decision_at:
        _validation("EXPECTED_NOTIONAL_SOURCE_GENERATED_AFTER_OBSERVATION_OR_DECISION")

    module_hash = _module_code_sha256()
    source_receipt, policy_version, artifact, _ = _build_material(
        batch=batch,
        result=result,
        raw_address=raw_address,
        symbol=resolved_symbol,
        feature_snapshot_identity=snapshot_identity,
        decision_iso=decision_iso,
        source_generated_at=generated_iso,
        server_observed_at=batch.server_observed_at,
        expires_at=expires_iso,
        embedded_hash=embedded_hash,
        candidate_count=count,
        gross_notional=gross_notional,
        expected_notional=expected_notional,
        module_code_sha256=module_hash,
    )
    source_receipt_bytes = _canonical_bytes(
        source_receipt,
        reason="EXPECTED_NOTIONAL_SOURCE_RECEIPT_INVALID",
    )
    source_receipt_address = _put_exact(
        store,
        source_receipt_bytes,
        reason="EXPECTED_NOTIONAL_SOURCE_RECEIPT_CAS_FAILED",
    )
    artifact_bytes = _canonical_bytes(
        artifact,
        reason="EXPECTED_NOTIONAL_ARTIFACT_INVALID",
    )
    artifact_address = _put_exact(
        store,
        artifact_bytes,
        reason="EXPECTED_NOTIONAL_ARTIFACT_CAS_FAILED",
    )
    compatible_receipt_material = {
        "schema_version": CAUSAL_COST_NOTIONAL_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "DIRECT_READ",
        "artifact_payload_sha256": artifact_address.payload_sha256,
        "artifact_payload_byte_count": artifact_address.payload_byte_count,
        "policy_source_key": CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
        "source_schema_version": CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
        "source_transport": CAUSAL_EXPECTED_NOTIONAL_SOURCE_TRANSPORT,
        "symbol": resolved_symbol,
        "feature_snapshot_identity": snapshot_identity,
        "effective_at": generated_iso,
        "available_at": batch.server_observed_at,
        "expires_at": expires_iso,
        "authority_scope": "FEATURE_SNAPSHOT_CAUSAL_EXPECTED_NOTIONAL",
    }
    compatible_receipt_sha256 = _canonical_sha256(
        compatible_receipt_material,
        reason="EXPECTED_NOTIONAL_COMPATIBLE_RECEIPT_INVALID",
    )
    compatible_receipt = {
        **compatible_receipt_material,
        "receipt_sha256": compatible_receipt_sha256,
    }
    compatible_receipt_bytes = _canonical_bytes(
        compatible_receipt,
        reason="EXPECTED_NOTIONAL_COMPATIBLE_RECEIPT_INVALID",
    )
    compatible_receipt_address = _put_exact(
        store,
        compatible_receipt_bytes,
        reason="EXPECTED_NOTIONAL_COMPATIBLE_RECEIPT_CAS_FAILED",
    )

    token = CausalExpectedNotionalPolicyTokenV1(
        schema_version=CAUSAL_EXPECTED_NOTIONAL_POLICY_V1_SCHEMA_VERSION,
        symbol=resolved_symbol,
        feature_snapshot_identity=snapshot_identity,
        expected_notional_usd=expected_notional,
        policy_version=policy_version,
        source_generated_at=generated_iso,
        server_observed_at=batch.server_observed_at,
        available_at=batch.server_observed_at,
        expires_at=expires_iso,
        decision_time=decision_iso,
        embedded_aggregate_contract_hash=embedded_hash,
        aggregate_candidate_count=count,
        aggregate_gross_notional_usd=gross_notional,
        raw_status_bytes=raw_bytes,
        raw_status_address=raw_address,
        source_read_receipt_bytes=source_receipt_bytes,
        source_read_receipt_address=source_receipt_address,
        source_read_receipt_sha256=source_receipt["receipt_sha256"],
        notional_artifact_bytes=artifact_bytes,
        notional_artifact_address=artifact_address,
        notional_receipt_bytes=compatible_receipt_bytes,
        notional_receipt_address=compatible_receipt_address,
        notional_receipt_sha256=compatible_receipt_sha256,
        implementation_contract_sha256=(CAUSAL_EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256),
        policy_config_sha256=CAUSAL_EXPECTED_NOTIONAL_POLICY_CONFIG_SHA256,
        module_code_sha256=module_hash,
        _atomic_capture=batch,
        _store=store,
        _construction_token=_CONSTRUCTION_TOKEN,
    )
    _validate_token(token)
    return token


def _validate_token(token: object) -> dict[str, Any]:
    if type(token) is not CausalExpectedNotionalPolicyTokenV1:
        _integrity("EXPECTED_NOTIONAL_FACTORY_TOKEN_TYPE_INVALID")
    typed = cast(CausalExpectedNotionalPolicyTokenV1, token)
    if (
        typed._construction_token is not _CONSTRUCTION_TOKEN
        or type(typed._store) is not ImmutableSourcePayloadStore
        or typed.schema_version != CAUSAL_EXPECTED_NOTIONAL_POLICY_V1_SCHEMA_VERSION
        or typed.read_only is not True
        or typed.trainer_authority is not False
        or typed.prediction_authority is not False
        or typed.paper_authority is not False
        or typed.live_authority is not False
        or typed.order_authority is not False
        or typed.fallback_used is not False
        or typed.static_default_used is not False
    ):
        _integrity("EXPECTED_NOTIONAL_FACTORY_TOKEN_FLAGS_INVALID")
    resolved_symbol = _symbol(typed.symbol)
    snapshot_identity = _snapshot_identity(typed.feature_snapshot_identity)
    decision_iso, decision_at = _clock(
        typed.decision_time,
        reason="EXPECTED_NOTIONAL_TOKEN_DECISION_TIME_INVALID",
    )
    batch, result, raw_bytes, server_at, expires_iso = _validated_atomic_source(
        typed._atomic_capture,
        decision_at=decision_at,
    )
    _readback_exact(
        typed._store,
        typed.raw_status_address,
        typed.raw_status_bytes,
        reason="EXPECTED_NOTIONAL_RAW_STATUS_READBACK_FAILED",
    )
    if not hmac.compare_digest(raw_bytes, typed.raw_status_bytes):
        _integrity("EXPECTED_NOTIONAL_RAW_STATUS_TOKEN_BINDING_INVALID")
    status = _parse_strict_outer_json(raw_bytes)
    embedded_hash, count, gross_notional, expected_notional, generated_iso = (
        _verified_status_aggregate(status)
    )
    _, generated_at = _clock(
        generated_iso,
        reason="EXPECTED_NOTIONAL_SOURCE_GENERATED_TIME_INVALID",
    )
    if generated_at > server_at or generated_at > decision_at:
        _validation("EXPECTED_NOTIONAL_SOURCE_GENERATED_AFTER_OBSERVATION_OR_DECISION")
    module_hash = _module_code_sha256()
    source_receipt, policy_version, artifact, version_material = _build_material(
        batch=batch,
        result=result,
        raw_address=typed.raw_status_address,
        symbol=resolved_symbol,
        feature_snapshot_identity=snapshot_identity,
        decision_iso=decision_iso,
        source_generated_at=generated_iso,
        server_observed_at=batch.server_observed_at,
        expires_at=expires_iso,
        embedded_hash=embedded_hash,
        candidate_count=count,
        gross_notional=gross_notional,
        expected_notional=expected_notional,
        module_code_sha256=module_hash,
    )
    if frozenset(source_receipt) != _SOURCE_RECEIPT_FIELDS:
        _integrity("EXPECTED_NOTIONAL_SOURCE_RECEIPT_FIELDS_INVALID")
    _self_hashed(
        source_receipt,
        reason="EXPECTED_NOTIONAL_SOURCE_RECEIPT_SELF_HASH_INVALID",
    )
    expected_source_receipt_bytes = _canonical_bytes(
        source_receipt,
        reason="EXPECTED_NOTIONAL_SOURCE_RECEIPT_INVALID",
    )
    if not hmac.compare_digest(
        expected_source_receipt_bytes,
        typed.source_read_receipt_bytes,
    ):
        _integrity("EXPECTED_NOTIONAL_SOURCE_RECEIPT_TOKEN_BINDING_INVALID")
    _readback_exact(
        typed._store,
        typed.source_read_receipt_address,
        typed.source_read_receipt_bytes,
        reason="EXPECTED_NOTIONAL_SOURCE_RECEIPT_READBACK_FAILED",
    )

    if frozenset(artifact) != _COMPATIBLE_ARTIFACT_FIELDS:
        _integrity("EXPECTED_NOTIONAL_ARTIFACT_FIELDS_INVALID")
    expected_artifact_bytes = _canonical_bytes(
        artifact,
        reason="EXPECTED_NOTIONAL_ARTIFACT_INVALID",
    )
    if not hmac.compare_digest(expected_artifact_bytes, typed.notional_artifact_bytes):
        _integrity("EXPECTED_NOTIONAL_ARTIFACT_TOKEN_BINDING_INVALID")
    _readback_exact(
        typed._store,
        typed.notional_artifact_address,
        typed.notional_artifact_bytes,
        reason="EXPECTED_NOTIONAL_ARTIFACT_READBACK_FAILED",
    )
    compatible_receipt_material = {
        "schema_version": CAUSAL_COST_NOTIONAL_RECEIPT_V1_SCHEMA_VERSION,
        "receipt_kind": "DIRECT_READ",
        "artifact_payload_sha256": typed.notional_artifact_address.payload_sha256,
        "artifact_payload_byte_count": typed.notional_artifact_address.payload_byte_count,
        "policy_source_key": CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
        "source_schema_version": CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
        "source_transport": CAUSAL_EXPECTED_NOTIONAL_SOURCE_TRANSPORT,
        "symbol": resolved_symbol,
        "feature_snapshot_identity": snapshot_identity,
        "effective_at": generated_iso,
        "available_at": batch.server_observed_at,
        "expires_at": expires_iso,
        "authority_scope": "FEATURE_SNAPSHOT_CAUSAL_EXPECTED_NOTIONAL",
    }
    compatible_receipt = {
        **compatible_receipt_material,
        "receipt_sha256": _canonical_sha256(
            compatible_receipt_material,
            reason="EXPECTED_NOTIONAL_COMPATIBLE_RECEIPT_INVALID",
        ),
    }
    if frozenset(compatible_receipt) != _COMPATIBLE_RECEIPT_FIELDS:
        _integrity("EXPECTED_NOTIONAL_COMPATIBLE_RECEIPT_FIELDS_INVALID")
    expected_compatible_receipt_bytes = _canonical_bytes(
        compatible_receipt,
        reason="EXPECTED_NOTIONAL_COMPATIBLE_RECEIPT_INVALID",
    )
    if not hmac.compare_digest(
        expected_compatible_receipt_bytes,
        typed.notional_receipt_bytes,
    ):
        _integrity("EXPECTED_NOTIONAL_COMPATIBLE_RECEIPT_TOKEN_BINDING_INVALID")
    _readback_exact(
        typed._store,
        typed.notional_receipt_address,
        typed.notional_receipt_bytes,
        reason="EXPECTED_NOTIONAL_COMPATIBLE_RECEIPT_READBACK_FAILED",
    )

    exact_scalars = (
        typed.expected_notional_usd == expected_notional,
        typed.aggregate_candidate_count == count,
        typed.aggregate_gross_notional_usd == gross_notional,
    )
    if (
        not all(exact_scalars)
        or typed.policy_version != policy_version
        or typed.source_generated_at != generated_iso
        or typed.server_observed_at != batch.server_observed_at
        or typed.available_at != batch.server_observed_at
        or typed.expires_at != expires_iso
        or typed.decision_time != decision_iso
        or typed.embedded_aggregate_contract_hash != embedded_hash
        or typed.source_read_receipt_sha256 != source_receipt["receipt_sha256"]
        or typed.notional_receipt_sha256 != compatible_receipt["receipt_sha256"]
        or typed.implementation_contract_sha256
        != CAUSAL_EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256
        or typed.policy_config_sha256 != CAUSAL_EXPECTED_NOTIONAL_POLICY_CONFIG_SHA256
        or typed.module_code_sha256 != module_hash
    ):
        _integrity("EXPECTED_NOTIONAL_FACTORY_TOKEN_BINDING_INVALID")
    return {
        "schema_version": typed.schema_version,
        "classification": CAUSAL_EXPECTED_NOTIONAL_CLASSIFICATION,
        "downstream_status": CAUSAL_EXPECTED_NOTIONAL_DOWNSTREAM_STATUS,
        "policy_version_material": version_material,
        "source_read_receipt": dict(source_receipt),
        "source_read_receipt_cas_address": _address_mapping(typed.source_read_receipt_address),
        "notional_artifact": dict(artifact),
        "notional_artifact_cas_address": _address_mapping(typed.notional_artifact_address),
        "notional_receipt": dict(compatible_receipt),
        "notional_receipt_cas_address": _address_mapping(typed.notional_receipt_address),
        "raw_status_cas_address": _address_mapping(typed.raw_status_address),
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
    "CAUSAL_EXPECTED_NOTIONAL_CLASSIFICATION",
    "CAUSAL_EXPECTED_NOTIONAL_DOWNSTREAM_STATUS",
    "CAUSAL_EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256",
    "CAUSAL_EXPECTED_NOTIONAL_POLICY_CONFIG_SHA256",
    "CAUSAL_EXPECTED_NOTIONAL_POLICY_ID",
    "CAUSAL_EXPECTED_NOTIONAL_SOURCE_ALLOCATOR",
    "CAUSAL_EXPECTED_NOTIONAL_POLICY_V1_SCHEMA_VERSION",
    "CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY",
    "CAUSAL_EXPECTED_NOTIONAL_SOURCE_PRODUCER",
    "CAUSAL_EXPECTED_NOTIONAL_SOURCE_RECEIPT_FIELDS",
    "CAUSAL_EXPECTED_NOTIONAL_SOURCE_RECEIPT_V1_SCHEMA_VERSION",
    "CAUSAL_EXPECTED_NOTIONAL_SOURCE_TRANSPORT",
    "CAUSAL_EXPECTED_NOTIONAL_ZERO_CANDIDATE_REASON",
    "CausalExpectedNotionalPolicyTokenV1",
    "CausalExpectedNotionalPolicyV1Error",
    "CausalExpectedNotionalPolicyV1IntegrityError",
    "CausalExpectedNotionalPolicyV1ValidationError",
    "build_causal_expected_notional_policy_v1",
]
