"""Atomic, read-only Redis source transport for future trainer provenance.

This module performs one bounded ``MULTI``/``EXEC`` read of exact Redis
``bytes``.  It is deliberately unwired: the returned transport evidence is
paper-provenance-only and is neither a source-schema attestation nor a
finality proof, durable-ledger receipt, feature publication, or trainer
admission.

The batch order is fixed for every requested key: ``TYPE``, bounded
``GETRANGE``, ``PTTL``; ``TIME`` is queued exactly once as the final command.
The inclusive ``GETRANGE`` end requests at most the accepted cap plus one
sentinel byte.  Payloads are never decoded or re-serialized.  Fixed
byte/key/count limits are resource-integrity limits, not market-selection or
trading thresholds.

``TIME`` is Redis server time at the final queued command.  It is not the
client's post-response ``consumer_observed_at`` and must never be substituted
for that causal clock by a later adapter.  The exported frozen dataclasses are
Python-constructible immutable value carriers, not authenticity proofs.  This
nonconsumable transport boundary therefore grants no durable or cryptographic
verification of how an arbitrary instance was constructed.

An accepted value is returned byte-for-byte.  An oversized value returns only
the cap-plus-one prefix and fails closed, so even a malicious pre-existing
Redis string cannot force its full body into this Python process.  This remains
an unwired transport primitive; it does not attest source schema, finality, or
point-in-time eligibility.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import islice
from typing import Any, NoReturn, Protocol, cast

ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION = "trainer_atomic_redis_source_read_v2"
ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION = "trainer_atomic_redis_source_result_v2"
ATOMIC_REDIS_SOURCE_READ_EVIDENCE_CLASSIFICATION = (
    "ATOMIC_REDIS_TRANSPORT_READ_ONLY_PAPER_PROVENANCE_ONLY_NONCONSUMABLE"
)
ATOMIC_REDIS_SOURCE_READ_DOWNSTREAM_STATUS = (
    "UNWIRED_NO_LEDGER_RECEIPT_SOURCE_SCHEMA_AND_FINALITY_ADAPTER_REQUIRED"
)
REDIS_TIME_CLOCK_SEMANTICS = "REDIS_TIME_FINAL_QUEUED_COMMAND_NOT_CLIENT_CONSUMER_OBSERVED_AT"

# These are transport resource-integrity ceilings.  They do not select a
# market, symbol, feature, observation, position, risk level, or leverage.
MAX_SOURCE_KEYS_PER_BATCH = 64
MAX_SOURCE_KEY_BYTES = 512
MAX_REDIS_CONNECTION_METADATA_FIELDS = 64
MAX_AGGREGATE_PAYLOAD_BYTES = 64 * 1024 * 1024
MAX_SOURCE_PAYLOAD_BYTES = MAX_AGGREGATE_PAYLOAD_BYTES // MAX_SOURCE_KEYS_PER_BATCH
MAX_RANGE_REPLY_BYTES = MAX_SOURCE_PAYLOAD_BYTES + 1
MAX_BATCH_MATERIALIZED_PAYLOAD_BYTES = MAX_RANGE_REPLY_BYTES * MAX_SOURCE_KEYS_PER_BATCH
MAX_REDIS_PTTL_MS = (1 << 63) - 1

assert MAX_SOURCE_PAYLOAD_BYTES * MAX_SOURCE_KEYS_PER_BATCH <= MAX_AGGREGATE_PAYLOAD_BYTES
assert MAX_BATCH_MATERIALIZED_PAYLOAD_BYTES == (
    MAX_AGGREGATE_PAYLOAD_BYTES + MAX_SOURCE_KEYS_PER_BATCH
)

_SOURCE_KEY_RE = re.compile(r"^v2:[A-Za-z0-9][A-Za-z0-9:._/@-]*$")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class _RedisPipeline(Protocol):
    def type(self, key: str) -> Any: ...

    def getrange(self, key: str, start: int, end: int) -> Any: ...

    def pttl(self, key: str) -> Any: ...

    def time(self) -> Any: ...

    def execute(self) -> Any: ...


class RawRedisSourceClient(Protocol):
    """Minimum synchronous redis-py client surface accepted by this boundary."""

    def get_connection_kwargs(self) -> dict[str, Any]: ...

    def pipeline(self, *, transaction: bool) -> _RedisPipeline: ...


class AtomicRedisSourceReadError(RuntimeError):
    """Base fail-closed atomic Redis source-read error."""


class AtomicRedisSourceReadValidationError(AtomicRedisSourceReadError):
    """Caller input or client mode cannot satisfy the exact-read contract."""


class AtomicRedisSourceReadTransportError(AtomicRedisSourceReadError):
    """The single read-only Redis transaction could not be completed."""


class AtomicRedisSourceReadIntegrityError(AtomicRedisSourceReadError):
    """Redis responses violate the exact transport contract."""


@dataclass(frozen=True, slots=True)
class AtomicRedisSourceResult:
    """One exact source value and its metadata from the atomic batch."""

    schema_version: str
    source_key: str
    source_key_sha256: str
    redis_type: str
    present: bool
    exact_payload_bytes: bytes | None = field(repr=False)
    payload_sha256: str | None
    payload_byte_count: int
    pttl_ms: int
    server_observed_at: str
    read_only: bool = field(default=True, init=False)
    paper_provenance_only: bool = field(default=True, init=False)
    live_execution_authorized: bool = field(default=False, init=False)
    source_schema_attested: bool = field(default=False, init=False)
    source_finality_attested: bool = field(default=False, init=False)
    ledger_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    transport_authenticity_attested: bool = field(default=False, init=False)
    server_time_is_consumer_observed_at: bool = field(default=False, init=False)
    server_time_clock_semantics: str = field(default=REDIS_TIME_CLOCK_SEMANTICS, init=False)


@dataclass(frozen=True, slots=True)
class AtomicRedisSourceReadBatch:
    """Immutable result of one bounded read-only Redis transaction."""

    schema_version: str
    batch_id: str
    batch_material_sha256: str
    batch_material_json: str
    server_time_seconds: int
    server_time_microseconds: int
    server_observed_at: str
    total_payload_byte_count: int
    results: tuple[AtomicRedisSourceResult, ...]
    evidence_classification: str = field(
        default=ATOMIC_REDIS_SOURCE_READ_EVIDENCE_CLASSIFICATION,
        init=False,
    )
    downstream_status: str = field(
        default=ATOMIC_REDIS_SOURCE_READ_DOWNSTREAM_STATUS,
        init=False,
    )
    read_only: bool = field(default=True, init=False)
    paper_provenance_only: bool = field(default=True, init=False)
    live_execution_authorized: bool = field(default=False, init=False)
    source_schema_attested: bool = field(default=False, init=False)
    source_finality_attested: bool = field(default=False, init=False)
    ledger_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    transport_authenticity_attested: bool = field(default=False, init=False)
    server_time_is_consumer_observed_at: bool = field(default=False, init=False)
    server_time_clock_semantics: str = field(default=REDIS_TIME_CLOCK_SEMANTICS, init=False)


def _validation_error(reason: str) -> NoReturn:
    raise AtomicRedisSourceReadValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise AtomicRedisSourceReadIntegrityError(reason) from None


def _validated_source_keys(source_keys: object) -> tuple[str, ...]:
    if type(source_keys) is not tuple and type(source_keys) is not list:
        _validation_error("atomic_redis_source_keys_container_invalid")
    if type(source_keys) is list:
        # A caller-owned list can change between a count check and iteration.
        # Slice only cap+1 elements under the interpreter lock, then validate
        # and use this immutable bounded snapshot exclusively.
        snapshot = tuple(cast(list[object], source_keys)[: MAX_SOURCE_KEYS_PER_BATCH + 1])
    else:
        snapshot = cast(tuple[object, ...], source_keys)
    if not 1 <= len(snapshot) <= MAX_SOURCE_KEYS_PER_BATCH:
        _validation_error("atomic_redis_source_key_count_invalid")

    validated: list[str] = []
    seen: set[str] = set()
    for candidate in snapshot:
        if type(candidate) is not str:
            _validation_error("atomic_redis_source_key_invalid")
        key = candidate
        if (
            not key.isascii()
            or not 4 <= len(key) <= MAX_SOURCE_KEY_BYTES
            or _SOURCE_KEY_RE.fullmatch(key) is None
        ):
            _validation_error("atomic_redis_source_key_invalid")
        if key in seen:
            _validation_error("atomic_redis_source_keys_duplicate")
        seen.add(key)
        validated.append(key)
    return tuple(validated)


def _verify_raw_client(client: RawRedisSourceClient) -> None:
    connection_kwargs: object
    try:
        connection_kwargs = client.get_connection_kwargs()
    except Exception:  # noqa: BLE001 - untrusted transport is totalized below
        connection_kwargs = None
    if type(connection_kwargs) is not dict:
        _validation_error("atomic_redis_client_raw_mode_unverified")

    # Snapshot only a bounded prefix of exact built-in dictionary entries.
    # Mutation during iteration is totalized; mutation after this snapshot
    # cannot alter which metadata is validated below.
    try:
        metadata_snapshot = tuple(
            islice(
                connection_kwargs.items(),
                MAX_REDIS_CONNECTION_METADATA_FIELDS + 1,
            )
        )
    except Exception:  # noqa: BLE001 - untrusted metadata race is totalized
        _validation_error("atomic_redis_client_raw_mode_unverified")
    if len(metadata_snapshot) > MAX_REDIS_CONNECTION_METADATA_FIELDS:
        _validation_error("atomic_redis_client_raw_mode_unverified")

    decode_responses: object = None
    decode_responses_seen = False
    for key, value in metadata_snapshot:
        if type(key) is not str:
            _validation_error("atomic_redis_client_raw_mode_unverified")
        if key == "decode_responses":
            decode_responses = value
            decode_responses_seen = True
    if not decode_responses_seen:
        _validation_error("atomic_redis_client_raw_mode_unverified")
    if type(decode_responses) is not bool or decode_responses is not False:
        _validation_error("atomic_redis_client_raw_mode_unverified")


def _cleanup_pipeline(pipeline: object) -> bool:
    """Run every supported reset/close method and require all of them to succeed."""

    failed = False
    for method_name in ("reset", "close"):
        try:
            method = getattr(pipeline, method_name)
        except AttributeError:  # noqa: S112 - method is optional
            continue
        except Exception:  # noqa: BLE001 - hostile cleanup lookup is totalized
            failed = True
            continue
        if not callable(method):
            continue
        try:
            method()
        except Exception:  # noqa: BLE001 - preserve the primary failure
            failed = True
            continue
    return not failed


def _server_clock(raw_time: object) -> tuple[int, int, str]:
    if type(raw_time) is not tuple or len(cast(tuple[object, ...], raw_time)) != 2:
        _integrity_error("atomic_redis_source_read_time_invalid")
    raw_seconds, raw_microseconds = cast(tuple[object, object], raw_time)
    if type(raw_seconds) is not int or type(raw_microseconds) is not int:
        _integrity_error("atomic_redis_source_read_time_invalid")
    seconds = raw_seconds
    microseconds = raw_microseconds
    if seconds < 0 or not 0 <= microseconds < 1_000_000:
        _integrity_error("atomic_redis_source_read_time_invalid")
    try:
        observed = _EPOCH + timedelta(seconds=seconds, microseconds=microseconds)
        observed_at = observed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        _integrity_error("atomic_redis_source_read_time_invalid")
    return seconds, microseconds, observed_at


def _parse_results(
    *,
    source_keys: tuple[str, ...],
    responses: object,
) -> tuple[tuple[AtomicRedisSourceResult, ...], int, int, str, int]:
    if type(responses) is not list:
        _integrity_error("atomic_redis_source_read_response_container_invalid")
    response_list = cast(list[object], responses)
    if len(response_list) != (3 * len(source_keys)) + 1:
        _integrity_error("atomic_redis_source_read_response_arity_invalid")

    seconds, microseconds, observed_at = _server_clock(response_list[-1])
    partial: list[tuple[str, str, bool, bytes | None, str | None, int, int]] = []
    aggregate_bytes = 0

    for index, key in enumerate(source_keys):
        offset = index * 3
        raw_type = response_list[offset]
        raw_payload = response_list[offset + 1]
        raw_pttl = response_list[offset + 2]

        if type(raw_type) is not bytes or raw_type not in (b"string", b"none"):
            _integrity_error("atomic_redis_source_read_type_invalid")
        if type(raw_pttl) is not int:
            _integrity_error("atomic_redis_source_read_pttl_invalid")
        pttl_ms = raw_pttl

        if raw_type == b"none":
            if type(raw_payload) is not bytes or raw_payload != b"" or pttl_ms != -2:
                _integrity_error("atomic_redis_source_read_missing_inconsistent")
            partial.append((key, "none", False, None, None, 0, pttl_ms))
            continue

        if type(raw_payload) is not bytes:
            _integrity_error("atomic_redis_source_read_payload_invalid")
        payload = raw_payload
        payload_bytes = len(payload)
        if payload_bytes > MAX_RANGE_REPLY_BYTES:
            _integrity_error("atomic_redis_source_read_range_reply_bytes_invalid")
        if payload_bytes > MAX_SOURCE_PAYLOAD_BYTES:
            _integrity_error("atomic_redis_source_read_payload_bytes_exceeded")
        aggregate_bytes += payload_bytes
        if aggregate_bytes > MAX_AGGREGATE_PAYLOAD_BYTES:
            _integrity_error("atomic_redis_source_read_aggregate_bytes_exceeded")
        if not -1 <= pttl_ms <= MAX_REDIS_PTTL_MS:
            _integrity_error("atomic_redis_source_read_present_pttl_inconsistent")
        partial.append(
            (
                key,
                "string",
                True,
                payload,
                hashlib.sha256(payload).hexdigest(),
                payload_bytes,
                pttl_ms,
            )
        )

    results = tuple(
        AtomicRedisSourceResult(
            schema_version=ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION,
            source_key=key,
            source_key_sha256=hashlib.sha256(key.encode("ascii")).hexdigest(),
            redis_type=redis_type,
            present=present,
            exact_payload_bytes=payload,
            payload_sha256=payload_sha256,
            payload_byte_count=payload_byte_count,
            pttl_ms=pttl_ms,
            server_observed_at=observed_at,
        )
        for (
            key,
            redis_type,
            present,
            payload,
            payload_sha256,
            payload_byte_count,
            pttl_ms,
        ) in partial
    )
    return results, seconds, microseconds, observed_at, aggregate_bytes


def _batch_material(
    *,
    results: tuple[AtomicRedisSourceResult, ...],
    seconds: int,
    microseconds: int,
    observed_at: str,
    aggregate_bytes: int,
) -> tuple[str, str, str]:
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
                "transport_authenticity_attested": result.transport_authenticity_attested,
            }
            for result in results
        ],
        "schema_version": ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION,
        "server_observed_at": observed_at,
        "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
        "server_time_is_consumer_observed_at": False,
        "server_time_microseconds": microseconds,
        "server_time_seconds": seconds,
        "source_finality_attested": False,
        "source_schema_attested": False,
        "total_payload_byte_count": aggregate_bytes,
        "transport_authenticity_attested": False,
    }
    material_json = json.dumps(
        material,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    material_sha256 = hashlib.sha256(material_json.encode("ascii")).hexdigest()
    batch_id = f"trainer_atomic_redis_source_read_v2_{material_sha256}"
    return material_json, material_sha256, batch_id


def read_atomic_redis_sources(
    client: RawRedisSourceClient,
    source_keys: object,
) -> AtomicRedisSourceReadBatch:
    """Read exact Redis string values and PTTLs in one read-only transaction.

    This transport result is suitable as future input to a source-specific
    adapter and then ``exact_source_read_capture``.  This function deliberately
    does not import or invoke either boundary.
    """

    keys = _validated_source_keys(source_keys)
    _verify_raw_client(client)

    pipeline: _RedisPipeline | None = None
    responses: object = None
    transport_failed = False
    cleanup_succeeded = True
    try:
        pipeline = client.pipeline(transaction=True)
        for key in keys:
            pipeline.type(key)
            pipeline.getrange(key, 0, MAX_SOURCE_PAYLOAD_BYTES)
            pipeline.pttl(key)
        pipeline.time()
        executed_responses = pipeline.execute()
        # Detach the exact built-in response list before pipeline cleanup.  A
        # redis-py cleanup must not be able to change what this batch validates.
        responses = (
            list(executed_responses) if type(executed_responses) is list else executed_responses
        )
    except Exception:  # noqa: BLE001 - transport failures use fixed reasons only
        transport_failed = True
    finally:
        if pipeline is not None:
            cleanup_succeeded = _cleanup_pipeline(pipeline)

    if transport_failed:
        raise AtomicRedisSourceReadTransportError(
            "atomic_redis_source_read_transport_failed"
        ) from None
    if not cleanup_succeeded:
        raise AtomicRedisSourceReadTransportError(
            "atomic_redis_source_read_pipeline_cleanup_failed"
        ) from None

    results, seconds, microseconds, observed_at, aggregate_bytes = _parse_results(
        source_keys=keys,
        responses=responses,
    )
    material_json, material_sha256, batch_id = _batch_material(
        results=results,
        seconds=seconds,
        microseconds=microseconds,
        observed_at=observed_at,
        aggregate_bytes=aggregate_bytes,
    )
    return AtomicRedisSourceReadBatch(
        schema_version=ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION,
        batch_id=batch_id,
        batch_material_sha256=material_sha256,
        batch_material_json=material_json,
        server_time_seconds=seconds,
        server_time_microseconds=microseconds,
        server_observed_at=observed_at,
        total_payload_byte_count=aggregate_bytes,
        results=results,
    )


__all__ = [
    "ATOMIC_REDIS_SOURCE_READ_DOWNSTREAM_STATUS",
    "ATOMIC_REDIS_SOURCE_READ_EVIDENCE_CLASSIFICATION",
    "ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION",
    "ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION",
    "MAX_AGGREGATE_PAYLOAD_BYTES",
    "MAX_BATCH_MATERIALIZED_PAYLOAD_BYTES",
    "MAX_RANGE_REPLY_BYTES",
    "MAX_SOURCE_KEYS_PER_BATCH",
    "MAX_SOURCE_KEY_BYTES",
    "MAX_SOURCE_PAYLOAD_BYTES",
    "REDIS_TIME_CLOCK_SEMANTICS",
    "AtomicRedisSourceReadBatch",
    "AtomicRedisSourceReadError",
    "AtomicRedisSourceReadIntegrityError",
    "AtomicRedisSourceReadTransportError",
    "AtomicRedisSourceReadValidationError",
    "AtomicRedisSourceResult",
    "RawRedisSourceClient",
    "read_atomic_redis_sources",
]
