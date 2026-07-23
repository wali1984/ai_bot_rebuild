"""Independent consumer proof for canonical closed-OHLCV writer receipts.

The canonical writer contract and the consumer contract deliberately live in
different modules.  This boundary first discovers the current revision, then
uses one ordered read-only ``MULTI``/``EXEC`` batch to reopen the canonical
value, immutable archive, writer receipt, and latest pointer together.  It
independently re-derives every writer-receipt field and requires an explicit
operator/deployment allow-list of exact writer role and code hashes.

Exact canonical, receipt, pointer, and consumer-manifest bytes are durably
captured in ``ImmutableSourcePayloadStore`` and freshly read back.  The result
proves only current writer publication integrity and producer-code identity.
It is an input to the later per-candle read/CAS and transform boundaries; it
does not itself authorize a generic consumer, trainer, prediction, paper
trade, or live execution.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import islice
from typing import Any, NoReturn, cast

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
    AtomicRedisSourceReadIntegrityError,
    AtomicRedisSourceReadTransportError,
    AtomicRedisSourceReadValidationError,
    AtomicRedisSourceResult,
    RawRedisSourceClient,
    read_atomic_redis_sources,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    OHLCV_CLOSED_WINDOW_SCHEMA_VERSION,
    SUPPORTED_TRAINER_TIMEFRAMES,
    TIMEFRAME_DURATION_MS,
    OHLCVClosedWindowValidationError,
    ValidatedOHLCVClosedWindow,
    validate_ohlcv_closed_window,
)

CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_SCHEMA_VERSION = (
    "canonical_ohlcv_writer_receipt_consumer_v1"
)
CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_MANIFEST_SCHEMA_VERSION = (
    "canonical_ohlcv_writer_receipt_consumer_manifest_v1"
)
CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_EVIDENCE_CLASSIFICATION = (
    "INDEPENDENT_WRITER_RECEIPT_AND_ATOMIC_FOUR_KEY_REOPEN_CAS_VERIFIED"
)
CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_DOWNSTREAM_STATUS = (
    "WRITER_PUBLICATION_INPUT_ONLY_TRANSFORM_AND_OUTPUT_AUTHORITY_HELD"
)

WRITER_RECEIPT_SCHEMA_VERSION = (
    "canonical_closed_ohlcv_publication_postcommit_receipt_v1"
)
WRITER_RECEIPT_EVIDENCE_CLASSIFICATION = (
    "POSTCOMMIT_REOPEN_VERIFIED_CANONICAL_CLOSED_OHLCV_PUBLICATION_ONLY"
)
WRITER_RECEIPT_DOWNSTREAM_STATUS = (
    "NO_TRAINER_PREDICTION_PAPER_OR_LIVE_AUTHORITY"
)
WRITER_PUBLICATION_REVISION_DOMAIN = (
    "v2/canonical-closed-ohlcv/publication-revision/v1"
)
WRITER_PUBLICATION_AVAILABLE_AT_CLOCK_SOURCE = (
    "REDIS_TIME_FINAL_COMMAND_AFTER_ATOMIC_ARCHIVE_AND_CANONICAL_SET"
)

BINANCE_WSS_WRITER_ROLE = "BINANCE_USDM_KLINE_WSS_CANONICAL_CLOSED_WINDOW_V1"
BINANCE_REST_WRITER_ROLE = "BINANCE_USDM_KLINE_REST_CANONICAL_CLOSED_WINDOW_V1"
EXISTING_PAYLOAD_ADOPTER_ROLE = "CANONICAL_CLOSED_WINDOW_EXISTING_PAYLOAD_ADOPTER_V1"
TRUSTED_WRITER_ROLES = frozenset(
    {BINANCE_WSS_WRITER_ROLE, BINANCE_REST_WRITER_ROLE}
)

CANONICAL_KEY_PREFIX = "v2:market:ohlcv_closed:"
ARCHIVE_KEY_PREFIX = "v2:market:ohlcv_closed:archive:"
RECEIPT_KEY_PREFIX = "v2:market:ohlcv_closed:publication_receipt:"
LATEST_POINTER_KEY_PREFIX = (
    "v2:market:ohlcv_closed:publication_receipt:latest:"
)

RECEIPT_CADENCE_COUNT = 3
ARCHIVE_CADENCE_COUNT = 4
MAX_RECEIPT_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_WRITER_HASHES_PER_ROLE = 8
MAX_READ_ATTEMPTS = 4
MAX_MUTABLE_TTL_SECONDS = 366 * 24 * 60 * 60
MAX_ARCHIVE_TTL_SECONDS = 2 * MAX_MUTABLE_TTL_SECONDS

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_REVISION_RE = re.compile(r"^v2_ohlcv_closed_[0-9a-f]{64}$", re.ASCII)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$", re.ASCII)
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\."
    r"[0-9]{6}Z$",
    re.ASCII,
)
_CONSTRUCTION_TOKEN = object()

_WRITER_AUTHORITY_FIELDS = (
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)
_CONSUMER_AUTHORITY_FIELDS = (
    "durable_ledger_appended",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)
_WRITER_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_classification",
        "downstream_status",
        "revision_id",
        "canonical_redis_key",
        "archive_key",
        "receipt_key",
        "latest_receipt_pointer_key",
        "exchange",
        "symbol",
        "timeframe",
        "source_payload_schema_version",
        "exact_payload_sha256",
        "exact_payload_byte_count",
        "row_count",
        "first_candle_id",
        "first_candle_open_time",
        "first_candle_close_time",
        "latest_candle_id",
        "latest_candle_open_time",
        "latest_candle_close_time",
        "max_producer_event_time",
        "max_ingested_at",
        "max_source_available_at",
        "finality_validated",
        "producer_role",
        "producer_code_sha256",
        "producer_config_sha256",
        "ttl_policy",
        "mutable_ttl_seconds",
        "receipt_ttl_seconds",
        "archive_ttl_seconds",
        "publication_available_at",
        "publication_available_at_clock_source",
        *_WRITER_AUTHORITY_FIELDS,
        "receipt_sha256",
    }
)


class CanonicalOhlcvWriterReceiptConsumerError(RuntimeError):
    """Base fail-closed writer-receipt consumer error."""


class CanonicalOhlcvWriterReceiptConsumerValidationError(
    CanonicalOhlcvWriterReceiptConsumerError
):
    """Caller input, source schema, freshness, or clock ordering is invalid."""


class CanonicalOhlcvWriterReceiptConsumerIntegrityError(
    CanonicalOhlcvWriterReceiptConsumerError
):
    """Exact bytes, writer identity, receipt, CAS, or manifest did not bind."""


class CanonicalOhlcvWriterReceiptConsumerTransportError(
    CanonicalOhlcvWriterReceiptConsumerError
):
    """The bounded read-only Redis transport could not complete."""


@dataclass(frozen=True, slots=True)
class CanonicalOhlcvWriterReceiptConsumerCapture:
    """Factory-authenticated current writer publication and consumer receipt."""

    schema_version: str
    evidence_classification: str
    downstream_status: str
    source_key: str
    archive_key: str
    receipt_key: str
    latest_pointer_key: str
    revision_id: str
    producer_role: str
    producer_code_sha256: str
    producer_config_sha256: str
    writer_receipt_sha256: str
    writer_publication_available_at: str
    discovery_batch_id: str
    discovery_batch_material_sha256: str
    discovery_batch_material_json: str = field(repr=False)
    discovery_server_observed_at: str
    discovery_pointer_pttl_ms: int
    authoritative_batch_id: str
    authoritative_batch_material_sha256: str
    authoritative_batch_material_json: str = field(repr=False)
    authoritative_server_observed_at: str
    consumer_observed_at: str
    consumer_observed_at_ms: int
    canonical_pttl_ms: int
    archive_pttl_ms: int
    receipt_pttl_ms: int
    pointer_pttl_ms: int
    exact_payload_sha256: str
    exact_payload_byte_count: int
    row_count: int
    validated_window: ValidatedOHLCVClosedWindow
    canonical_payload_address: SourcePayloadAddress
    receipt_payload_address: SourcePayloadAddress
    pointer_payload_address: SourcePayloadAddress
    tuple_manifest_sha256: str
    tuple_manifest_json: str = field(repr=False)
    tuple_manifest_address: SourcePayloadAddress
    trusted_allowlist_sha256: str
    trusted_allowlist_material_json: str = field(repr=False)
    _canonical_payload_bytes: bytes = field(repr=False)
    _receipt_payload_bytes: bytes = field(repr=False)
    _pointer_payload_bytes: bytes = field(repr=False)
    _source_payload_store: ImmutableSourcePayloadStore = field(
        repr=False,
        compare=False,
    )
    _construction_token: object = field(repr=False, compare=False)
    writer_publication_receipt_verified: bool = field(default=True, init=False)
    producer_identity_allowlisted: bool = field(default=True, init=False)
    current_pointer_verified: bool = field(default=True, init=False)
    canonical_archive_exact_match: bool = field(default=True, init=False)
    atomic_four_key_reopen_verified: bool = field(default=True, init=False)
    immutable_cas_captured: bool = field(default=True, init=False)
    durable_ledger_appended: bool = field(default=False, init=False)
    feature_snapshot_published: bool = field(default=False, init=False)
    feature_publication_receipt_emitted: bool = field(default=False, init=False)
    consumer_eligible: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _validate_capture(self)

    @property
    def exact_canonical_payload_bytes(self) -> bytes:
        _validate_capture(self)
        return self._canonical_payload_bytes

    @property
    def exact_writer_receipt_bytes(self) -> bytes:
        _validate_capture(self)
        return self._receipt_payload_bytes

    @property
    def writer_receipt(self) -> dict[str, Any]:
        _validate_capture(self)
        return _parse_receipt(self._receipt_payload_bytes)

    @property
    def tuple_manifest(self) -> dict[str, Any]:
        _validate_capture(self)
        return cast(dict[str, Any], json.loads(self.tuple_manifest_json))


def _validation_error(reason: str) -> NoReturn:
    raise CanonicalOhlcvWriterReceiptConsumerValidationError(reason) from None


def _integrity_error(reason: str) -> NoReturn:
    raise CanonicalOhlcvWriterReceiptConsumerIntegrityError(reason) from None


def _canonical_json_bytes(
    value: object,
    *,
    maximum: int,
    reason: str,
) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _integrity_error(reason)
    if not encoded or len(encoded) > maximum:
        _integrity_error(reason)
    return encoded


def _stable_sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(
            value,
            maximum=MAX_MANIFEST_BYTES,
            reason="canonical_ohlcv_consumer_canonical_json_invalid",
        )
    ).hexdigest()


def _parse_clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _validation_error(reason)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        _validation_error(reason)
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        _validation_error(reason)
    return parsed


def _sample_consumer_clock(
    consumer_clock: Callable[[], datetime],
) -> tuple[datetime, str, int]:
    try:
        observed = consumer_clock()
    except Exception:
        _validation_error("canonical_ohlcv_consumer_clock_failed")
    if type(observed) is not datetime or observed.tzinfo is None:
        _validation_error("canonical_ohlcv_consumer_clock_invalid")
    normalized = observed.astimezone(UTC)
    text = normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    reparsed = _parse_clock(text, reason="canonical_ohlcv_consumer_clock_invalid")
    return reparsed, text, int(reparsed.timestamp() * 1000)


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _integrity_error("canonical_ohlcv_writer_receipt_duplicate_field")
        value[key] = item
    return value


def _parse_receipt(payload: object) -> dict[str, Any]:
    if type(payload) is not bytes or not payload or len(payload) > MAX_RECEIPT_BYTES:
        _integrity_error("canonical_ohlcv_writer_receipt_size_invalid")
    try:
        parsed = json.loads(
            payload,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=lambda _value: _integrity_error(
                "canonical_ohlcv_writer_receipt_nonfinite"
            ),
        )
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError):
        _integrity_error("canonical_ohlcv_writer_receipt_json_invalid")
    if type(parsed) is not dict:
        _integrity_error("canonical_ohlcv_writer_receipt_object_required")
    receipt = cast(dict[str, Any], parsed)
    if frozenset(receipt) != _WRITER_RECEIPT_FIELDS:
        _integrity_error("canonical_ohlcv_writer_receipt_fields_invalid")
    canonical = _canonical_json_bytes(
        receipt,
        maximum=MAX_RECEIPT_BYTES,
        reason="canonical_ohlcv_writer_receipt_canonical_json_invalid",
    )
    if not hmac.compare_digest(canonical, payload):
        _integrity_error("canonical_ohlcv_writer_receipt_encoding_noncanonical")
    return receipt


def _validated_symbol_timeframe(
    symbol: object,
    timeframe: object,
) -> tuple[str, str]:
    if type(symbol) is not str or _SYMBOL_RE.fullmatch(symbol) is None:
        _validation_error("canonical_ohlcv_consumer_symbol_invalid")
    if type(timeframe) is not str or timeframe not in SUPPORTED_TRAINER_TIMEFRAMES:
        _validation_error("canonical_ohlcv_consumer_timeframe_invalid")
    return symbol, timeframe


def _validated_allowlist(
    value: object,
) -> tuple[dict[str, frozenset[str]], str, str]:
    if not isinstance(value, Mapping):
        _validation_error("canonical_ohlcv_writer_allowlist_mapping_required")
    try:
        item_snapshot = tuple(
            islice(value.items(), len(TRUSTED_WRITER_ROLES) + 1)
        )
    except (RuntimeError, TypeError, ValueError):
        _validation_error("canonical_ohlcv_writer_allowlist_invalid")
    if len(item_snapshot) != len(TRUSTED_WRITER_ROLES):
        _validation_error("canonical_ohlcv_writer_allowlist_roles_invalid")
    snapshot: dict[str, object] = {}
    for role, candidates in item_snapshot:
        if type(role) is not str or role in snapshot:
            _validation_error("canonical_ohlcv_writer_allowlist_roles_invalid")
        snapshot[role] = candidates
    if set(snapshot) != set(TRUSTED_WRITER_ROLES):
        _validation_error("canonical_ohlcv_writer_allowlist_roles_invalid")
    normalized: dict[str, frozenset[str]] = {}
    all_hashes: set[str] = set()
    for role in sorted(TRUSTED_WRITER_ROLES):
        candidates = snapshot.get(role)
        if (
            not isinstance(candidates, Collection)
            or isinstance(candidates, str | bytes | bytearray | Mapping)
        ):
            _validation_error("canonical_ohlcv_writer_allowlist_hashes_invalid")
        try:
            hashes = tuple(
                islice(candidates, MAX_WRITER_HASHES_PER_ROLE + 1)
            )
        except (RuntimeError, TypeError, ValueError):
            _validation_error("canonical_ohlcv_writer_allowlist_hashes_invalid")
        if not 1 <= len(hashes) <= MAX_WRITER_HASHES_PER_ROLE:
            _validation_error("canonical_ohlcv_writer_allowlist_hash_count_invalid")
        if any(type(item) is not str or _SHA256_RE.fullmatch(item) is None for item in hashes):
            _validation_error("canonical_ohlcv_writer_allowlist_hash_invalid")
        frozen = frozenset(cast(tuple[str, ...], hashes))
        if len(frozen) != len(hashes) or all_hashes.intersection(frozen):
            _validation_error("canonical_ohlcv_writer_allowlist_hash_collision")
        normalized[role] = frozen
        all_hashes.update(frozen)
    material = {
        "schema_version": "canonical_ohlcv_writer_role_code_allowlist_v1",
        "role_code_sha256": {
            role: sorted(hashes) for role, hashes in sorted(normalized.items())
        },
        "adopter_role_explicitly_rejected": EXISTING_PAYLOAD_ADOPTER_ROLE,
        "unknown_roles_rejected": True,
        "cross_role_code_hashes_rejected": True,
    }
    material_bytes = _canonical_json_bytes(
        material,
        maximum=MAX_RECEIPT_BYTES,
        reason="canonical_ohlcv_writer_allowlist_material_invalid",
    )
    material_json = material_bytes.decode("ascii")
    return normalized, material_json, hashlib.sha256(material_bytes).hexdigest()


def _required_result(
    result: AtomicRedisSourceResult,
    *,
    expected_key: str,
    reason: str,
) -> bytes:
    if (
        type(result) is not AtomicRedisSourceResult
        or result.source_key != expected_key
        or result.redis_type != "string"
        or result.present is not True
        or type(result.exact_payload_bytes) is not bytes
        or not result.exact_payload_bytes
        or type(result.payload_sha256) is not str
        or _SHA256_RE.fullmatch(result.payload_sha256) is None
        or result.payload_byte_count != len(result.exact_payload_bytes)
        or not hmac.compare_digest(
            result.payload_sha256,
            hashlib.sha256(result.exact_payload_bytes).hexdigest(),
        )
        or type(result.pttl_ms) is not int
        or result.pttl_ms <= 0
    ):
        _integrity_error(reason)
    return result.exact_payload_bytes


def _read_atomic(
    client: RawRedisSourceClient,
    keys: tuple[str, ...],
) -> AtomicRedisSourceReadBatch:
    try:
        return read_atomic_redis_sources(client, keys)
    except AtomicRedisSourceReadTransportError:
        raise CanonicalOhlcvWriterReceiptConsumerTransportError(
            "canonical_ohlcv_consumer_atomic_read_transport_failed"
        ) from None
    except AtomicRedisSourceReadValidationError:
        raise CanonicalOhlcvWriterReceiptConsumerValidationError(
            "canonical_ohlcv_consumer_atomic_read_validation_failed"
        ) from None
    except AtomicRedisSourceReadIntegrityError:
        raise CanonicalOhlcvWriterReceiptConsumerIntegrityError(
            "canonical_ohlcv_consumer_atomic_read_integrity_failed"
        ) from None


def _discover_revision(
    client: RawRedisSourceClient,
    *,
    pointer_key: str,
) -> tuple[str, bytes, AtomicRedisSourceReadBatch]:
    batch = _read_atomic(client, (pointer_key,))
    if type(batch) is not AtomicRedisSourceReadBatch or len(batch.results) != 1:
        _integrity_error("canonical_ohlcv_pointer_discovery_batch_invalid")
    pointer_bytes = _required_result(
        batch.results[0],
        expected_key=pointer_key,
        reason="canonical_ohlcv_latest_pointer_unavailable",
    )
    try:
        revision_id = pointer_bytes.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        _integrity_error("canonical_ohlcv_latest_pointer_encoding_invalid")
    if _REVISION_RE.fullmatch(revision_id) is None:
        _integrity_error("canonical_ohlcv_latest_pointer_revision_invalid")
    return revision_id, pointer_bytes, batch


def _writer_revision_id(
    *,
    canonical_key: str,
    payload_sha256: str,
    payload_byte_count: int,
    producer_role: str,
    producer_code_sha256: str,
    producer_config_sha256: str,
    ttl_policy: str,
    mutable_ttl_seconds: int,
    receipt_ttl_seconds: int,
    archive_ttl_seconds: int,
) -> str:
    digest = _stable_sha256(
        {
            "domain": WRITER_PUBLICATION_REVISION_DOMAIN,
            "canonical_redis_key": canonical_key,
            "source_payload_schema_version": OHLCV_CLOSED_WINDOW_SCHEMA_VERSION,
            "exact_payload_sha256": payload_sha256,
            "exact_payload_byte_count": payload_byte_count,
            "producer_role": producer_role,
            "producer_code_sha256": producer_code_sha256,
            "producer_config_sha256": producer_config_sha256,
            "ttl_policy": ttl_policy,
            "mutable_ttl_seconds": mutable_ttl_seconds,
            "receipt_ttl_seconds": receipt_ttl_seconds,
            "archive_ttl_seconds": archive_ttl_seconds,
        }
    )
    return f"v2_ohlcv_closed_{digest}"


def _exact_int(
    value: object,
    *,
    minimum: int,
    maximum: int,
    reason: str,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _integrity_error(reason)
    return value


def _validate_writer_receipt(
    *,
    receipt_bytes: bytes,
    canonical_bytes: bytes,
    canonical_key: str,
    archive_key: str,
    receipt_key: str,
    pointer_key: str,
    revision_id: str,
    symbol: str,
    timeframe: str,
    trusted_allowlist: Mapping[str, frozenset[str]],
    discovery_server_observed_at: str,
    authoritative_server_observed_at: str,
    consumer_observed_at: str,
    discovery_pointer_pttl_ms: int,
    canonical_pttl_ms: int,
    archive_pttl_ms: int,
    receipt_pttl_ms: int,
    pointer_pttl_ms: int,
) -> tuple[dict[str, Any], ValidatedOHLCVClosedWindow]:
    receipt = _parse_receipt(receipt_bytes)
    producer_role = receipt.get("producer_role")
    producer_code_sha256 = receipt.get("producer_code_sha256")
    producer_config_sha256 = receipt.get("producer_config_sha256")
    if producer_role == EXISTING_PAYLOAD_ADOPTER_ROLE:
        _integrity_error("canonical_ohlcv_adopter_receipt_not_trusted")
    if type(producer_role) is not str or producer_role not in TRUSTED_WRITER_ROLES:
        _integrity_error("canonical_ohlcv_writer_role_not_trusted")
    if (
        type(producer_code_sha256) is not str
        or _SHA256_RE.fullmatch(producer_code_sha256) is None
        or producer_code_sha256 not in trusted_allowlist[producer_role]
    ):
        _integrity_error("canonical_ohlcv_writer_code_not_allowlisted_for_role")
    if (
        type(producer_config_sha256) is not str
        or _SHA256_RE.fullmatch(producer_config_sha256) is None
    ):
        _integrity_error("canonical_ohlcv_writer_config_hash_invalid")
    try:
        validated = validate_ohlcv_closed_window(
            canonical_bytes,
            symbol=symbol,
            timeframe=timeframe,
        )
    except OHLCVClosedWindowValidationError as exc:
        raise CanonicalOhlcvWriterReceiptConsumerValidationError(
            f"canonical_ohlcv_writer_payload_invalid:{exc}"
        ) from None

    mutable_ttl = _exact_int(
        receipt.get("mutable_ttl_seconds"),
        minimum=1,
        maximum=MAX_MUTABLE_TTL_SECONDS,
        reason="canonical_ohlcv_writer_mutable_ttl_invalid",
    )
    receipt_ttl = _exact_int(
        receipt.get("receipt_ttl_seconds"),
        minimum=1,
        maximum=MAX_MUTABLE_TTL_SECONDS,
        reason="canonical_ohlcv_writer_receipt_ttl_invalid",
    )
    archive_ttl = _exact_int(
        receipt.get("archive_ttl_seconds"),
        minimum=2,
        maximum=MAX_ARCHIVE_TTL_SECONDS,
        reason="canonical_ohlcv_writer_archive_ttl_invalid",
    )
    cadence_seconds = TIMEFRAME_DURATION_MS[timeframe] // 1000
    if (
        receipt.get("ttl_policy") != "set"
        or receipt_ttl != cadence_seconds * RECEIPT_CADENCE_COUNT
        or archive_ttl != cadence_seconds * ARCHIVE_CADENCE_COUNT
        or archive_ttl <= receipt_ttl
    ):
        _integrity_error("canonical_ohlcv_writer_cadence_ttl_contract_invalid")
    if (
        not 0 < discovery_pointer_pttl_ms <= receipt_ttl * 1000
        or not 0 < canonical_pttl_ms <= mutable_ttl * 1000
        or not 0 < receipt_pttl_ms <= receipt_ttl * 1000
        or not 0 < pointer_pttl_ms <= receipt_ttl * 1000
        or not 0 < archive_pttl_ms <= archive_ttl * 1000
        or archive_pttl_ms <= max(receipt_pttl_ms, pointer_pttl_ms)
    ):
        _integrity_error("canonical_ohlcv_writer_runtime_ttl_order_invalid")

    publication_clock = _parse_clock(
        receipt.get("publication_available_at"),
        reason="canonical_ohlcv_writer_publication_clock_invalid",
    )
    discovery_clock = _parse_clock(
        discovery_server_observed_at,
        reason="canonical_ohlcv_consumer_discovery_redis_clock_invalid",
    )
    authoritative_clock = _parse_clock(
        authoritative_server_observed_at,
        reason="canonical_ohlcv_consumer_redis_clock_invalid",
    )
    consumer_clock = _parse_clock(
        consumer_observed_at,
        reason="canonical_ohlcv_consumer_clock_invalid",
    )
    publication_ms = int(publication_clock.timestamp() * 1000)
    authoritative_ms = int(authoritative_clock.timestamp() * 1000)
    if not (
        publication_clock
        <= discovery_clock
        <= authoritative_clock
        <= consumer_clock
    ):
        _validation_error("canonical_ohlcv_writer_consumer_clock_order_invalid")
    if (
        validated.max_available_at > publication_ms
        or validated.latest_economic_close_time > publication_ms
    ):
        _validation_error("canonical_ohlcv_writer_publication_precedes_source")
    expected_latest_close_ms = (
        authoritative_ms // TIMEFRAME_DURATION_MS[timeframe]
    ) * TIMEFRAME_DURATION_MS[timeframe] - 1
    if validated.latest_economic_close_time != expected_latest_close_ms:
        _validation_error("canonical_ohlcv_writer_latest_completed_interval_mismatch")

    payload_sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    expected_revision = _writer_revision_id(
        canonical_key=canonical_key,
        payload_sha256=payload_sha256,
        payload_byte_count=len(canonical_bytes),
        producer_role=producer_role,
        producer_code_sha256=producer_code_sha256,
        producer_config_sha256=producer_config_sha256,
        ttl_policy="set",
        mutable_ttl_seconds=mutable_ttl,
        receipt_ttl_seconds=receipt_ttl,
        archive_ttl_seconds=archive_ttl,
    )
    if expected_revision != revision_id:
        _integrity_error("canonical_ohlcv_writer_revision_rederivation_mismatch")
    first = validated.rows[0]
    latest = validated.rows[-1]
    unsigned: dict[str, Any] = {
        "schema_version": WRITER_RECEIPT_SCHEMA_VERSION,
        "evidence_classification": WRITER_RECEIPT_EVIDENCE_CLASSIFICATION,
        "downstream_status": WRITER_RECEIPT_DOWNSTREAM_STATUS,
        "revision_id": revision_id,
        "canonical_redis_key": canonical_key,
        "archive_key": archive_key,
        "receipt_key": receipt_key,
        "latest_receipt_pointer_key": pointer_key,
        "exchange": "binance",
        "symbol": symbol,
        "timeframe": timeframe,
        "source_payload_schema_version": OHLCV_CLOSED_WINDOW_SCHEMA_VERSION,
        "exact_payload_sha256": payload_sha256,
        "exact_payload_byte_count": len(canonical_bytes),
        "row_count": validated.row_count,
        "first_candle_id": first.candle_id,
        "first_candle_open_time": first.candle_open_time,
        "first_candle_close_time": first.candle_close_time,
        "latest_candle_id": latest.candle_id,
        "latest_candle_open_time": latest.candle_open_time,
        "latest_candle_close_time": latest.candle_close_time,
        "max_producer_event_time": validated.latest_producer_event_time,
        "max_ingested_at": validated.max_ingested_at,
        "max_source_available_at": validated.max_available_at,
        "finality_validated": True,
        "producer_role": producer_role,
        "producer_code_sha256": producer_code_sha256,
        "producer_config_sha256": producer_config_sha256,
        "ttl_policy": "set",
        "mutable_ttl_seconds": mutable_ttl,
        "receipt_ttl_seconds": receipt_ttl,
        "archive_ttl_seconds": archive_ttl,
        "publication_available_at": receipt["publication_available_at"],
        "publication_available_at_clock_source": (
            WRITER_PUBLICATION_AVAILABLE_AT_CLOCK_SOURCE
        ),
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }
    expected = {**unsigned, "receipt_sha256": _stable_sha256(unsigned)}
    if receipt != expected:
        _integrity_error("canonical_ohlcv_writer_receipt_rederivation_mismatch")
    return receipt, validated


def _address_material(address: SourcePayloadAddress) -> dict[str, object]:
    return cast(dict[str, object], asdict(address))


def _fresh_exact_readback(
    store: ImmutableSourcePayloadStore,
    address: SourcePayloadAddress,
    expected: bytes,
    *,
    reason: str,
) -> None:
    try:
        reopened = store.get(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise CanonicalOhlcvWriterReceiptConsumerIntegrityError(reason) from exc
    if not hmac.compare_digest(reopened, expected):
        _integrity_error(reason)


def _manifest_material(
    *,
    source_key: str,
    archive_key: str,
    receipt_key: str,
    pointer_key: str,
    revision_id: str,
    receipt: Mapping[str, Any],
    discovery_batch: AtomicRedisSourceReadBatch,
    authoritative_batch: AtomicRedisSourceReadBatch,
    consumer_observed_at: str,
    canonical_address: SourcePayloadAddress,
    receipt_address: SourcePayloadAddress,
    pointer_address: SourcePayloadAddress,
    trusted_allowlist_material_json: str,
    trusted_allowlist_sha256: str,
) -> dict[str, Any]:
    ordered_results = []
    for result in authoritative_batch.results:
        ordered_results.append(
            {
                "source_key": result.source_key,
                "source_key_sha256": result.source_key_sha256,
                "payload_sha256": result.payload_sha256,
                "payload_byte_count": result.payload_byte_count,
                "pttl_ms": result.pttl_ms,
                "redis_type": result.redis_type,
                "present": result.present,
            }
        )
    return {
        "schema_version": (
            CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_MANIFEST_SCHEMA_VERSION
        ),
        "evidence_classification": (
            CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_EVIDENCE_CLASSIFICATION
        ),
        "downstream_status": (
            CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_DOWNSTREAM_STATUS
        ),
        "source_key": source_key,
        "archive_key": archive_key,
        "receipt_key": receipt_key,
        "latest_pointer_key": pointer_key,
        "revision_id": revision_id,
        "producer_role": receipt["producer_role"],
        "producer_code_sha256": receipt["producer_code_sha256"],
        "producer_config_sha256": receipt["producer_config_sha256"],
        "writer_receipt_sha256": receipt["receipt_sha256"],
        "writer_publication_available_at": receipt["publication_available_at"],
        "discovery_batch_id": discovery_batch.batch_id,
        "discovery_batch_material_sha256": (
            discovery_batch.batch_material_sha256
        ),
        "discovery_batch_material_json": discovery_batch.batch_material_json,
        "discovery_server_observed_at": discovery_batch.server_observed_at,
        "discovery_pointer_pttl_ms": discovery_batch.results[0].pttl_ms,
        "authoritative_batch_id": authoritative_batch.batch_id,
        "authoritative_batch_material_sha256": (
            authoritative_batch.batch_material_sha256
        ),
        "authoritative_batch_material_json": authoritative_batch.batch_material_json,
        "authoritative_server_observed_at": authoritative_batch.server_observed_at,
        "consumer_observed_at": consumer_observed_at,
        "ordered_atomic_source_results": ordered_results,
        "canonical_archive_exact_match": True,
        "current_pointer_verified": True,
        "writer_publication_receipt_verified": True,
        "producer_identity_allowlisted": True,
        "trusted_allowlist_material_json": trusted_allowlist_material_json,
        "trusted_allowlist_sha256": trusted_allowlist_sha256,
        "canonical_payload_address": _address_material(canonical_address),
        "receipt_payload_address": _address_material(receipt_address),
        "pointer_payload_address": _address_material(pointer_address),
        "durable_ledger_appended": False,
        "feature_snapshot_published": False,
        "feature_publication_receipt_emitted": False,
        "consumer_eligible": False,
        "trainer_admission_granted": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }


def _validate_batch_identity(
    *,
    batch_id: str,
    material_sha256: str,
    material_json: str,
    server_observed_at: str,
    sources: tuple[tuple[str, bytes, int], ...],
) -> None:
    observed = _parse_clock(
        server_observed_at,
        reason="canonical_ohlcv_consumer_redis_clock_invalid",
    )
    server_time_seconds = int(observed.timestamp())
    server_time_microseconds = observed.microsecond
    result_material = [
        {
            "consumer_eligible": False,
            "ledger_receipt_emitted": False,
            "live_execution_authorized": False,
            "payload_byte_count": len(payload),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "paper_provenance_only": True,
            "present": True,
            "pttl_ms": pttl_ms,
            "read_only": True,
            "redis_type": "string",
            "schema_version": ATOMIC_REDIS_SOURCE_RESULT_SCHEMA_VERSION,
            "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
            "server_time_is_consumer_observed_at": False,
            "source_finality_attested": False,
            "source_key": source_key,
            "source_key_sha256": hashlib.sha256(
                source_key.encode("ascii")
            ).hexdigest(),
            "source_schema_attested": False,
            "transport_authenticity_attested": False,
        }
        for source_key, payload, pttl_ms in sources
    ]
    expected_material = {
        "consumer_eligible": False,
        "downstream_status": ATOMIC_REDIS_SOURCE_READ_DOWNSTREAM_STATUS,
        "evidence_classification": (
            ATOMIC_REDIS_SOURCE_READ_EVIDENCE_CLASSIFICATION
        ),
        "ledger_receipt_emitted": False,
        "live_execution_authorized": False,
        "paper_provenance_only": True,
        "read_only": True,
        "redis_payload_read_operation": "GETRANGE_INCLUSIVE_CAP_PLUS_ONE",
        "redis_transaction_command_order_per_key": ["TYPE", "GETRANGE", "PTTL"],
        "max_aggregate_payload_bytes": MAX_AGGREGATE_PAYLOAD_BYTES,
        "max_batch_materialized_payload_bytes": (
            MAX_BATCH_MATERIALIZED_PAYLOAD_BYTES
        ),
        "max_range_reply_bytes": MAX_RANGE_REPLY_BYTES,
        "max_source_keys_per_batch": MAX_SOURCE_KEYS_PER_BATCH,
        "max_source_payload_bytes": MAX_SOURCE_PAYLOAD_BYTES,
        "results": result_material,
        "schema_version": ATOMIC_REDIS_SOURCE_READ_SCHEMA_VERSION,
        "server_observed_at": server_observed_at,
        "server_time_clock_semantics": REDIS_TIME_CLOCK_SEMANTICS,
        "server_time_is_consumer_observed_at": False,
        "server_time_microseconds": server_time_microseconds,
        "server_time_seconds": server_time_seconds,
        "source_finality_attested": False,
        "source_schema_attested": False,
        "total_payload_byte_count": sum(len(payload) for _, payload, _ in sources),
        "transport_authenticity_attested": False,
    }
    expected_material_json = _canonical_json_bytes(
        expected_material,
        maximum=MAX_MANIFEST_BYTES,
        reason="canonical_ohlcv_consumer_atomic_batch_material_invalid",
    ).decode("ascii")
    try:
        material_bytes = material_json.encode("ascii")
    except (AttributeError, UnicodeEncodeError):
        _integrity_error("canonical_ohlcv_consumer_atomic_batch_identity_invalid")
    if (
        type(material_json) is not str
        or type(material_sha256) is not str
        or _SHA256_RE.fullmatch(material_sha256) is None
        or not hmac.compare_digest(material_json, expected_material_json)
        or not hmac.compare_digest(
            hashlib.sha256(material_bytes).hexdigest(),
            material_sha256,
        )
        or batch_id != f"trainer_atomic_redis_source_read_v2_{material_sha256}"
    ):
        _integrity_error("canonical_ohlcv_consumer_atomic_batch_identity_invalid")


def _trusted_allowlist_from_material(
    *,
    material_json: str,
    material_sha256: str,
) -> dict[str, frozenset[str]]:
    if type(material_json) is not str:
        _integrity_error("canonical_ohlcv_consumer_allowlist_material_invalid")
    try:
        encoded = material_json.encode("ascii")
    except (
        AttributeError,
        UnicodeEncodeError,
    ):
        _integrity_error("canonical_ohlcv_consumer_allowlist_material_invalid")
    if not encoded or len(encoded) > MAX_RECEIPT_BYTES:
        _integrity_error("canonical_ohlcv_consumer_allowlist_material_invalid")
    try:
        parsed = json.loads(material_json)
    except (json.JSONDecodeError, RecursionError, ValueError):
        _integrity_error("canonical_ohlcv_consumer_allowlist_material_invalid")
    if (
        type(parsed) is not dict
        or type(material_sha256) is not str
        or _SHA256_RE.fullmatch(material_sha256) is None
        or not hmac.compare_digest(
            hashlib.sha256(encoded).hexdigest(),
            material_sha256,
        )
    ):
        _integrity_error("canonical_ohlcv_consumer_allowlist_material_invalid")
    role_code_sha256 = parsed.get("role_code_sha256")
    try:
        normalized, expected_json, expected_sha256 = _validated_allowlist(
            role_code_sha256
        )
    except CanonicalOhlcvWriterReceiptConsumerValidationError as exc:
        raise CanonicalOhlcvWriterReceiptConsumerIntegrityError(
            "canonical_ohlcv_consumer_allowlist_material_invalid"
        ) from exc
    if (
        not hmac.compare_digest(material_json, expected_json)
        or not hmac.compare_digest(material_sha256, expected_sha256)
    ):
        _integrity_error("canonical_ohlcv_consumer_allowlist_material_invalid")
    return normalized


def _manifest_result_material(
    *,
    source_key: str,
    payload: bytes,
    pttl_ms: int,
) -> dict[str, object]:
    return {
        "source_key": source_key,
        "source_key_sha256": hashlib.sha256(source_key.encode("ascii")).hexdigest(),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload_byte_count": len(payload),
        "pttl_ms": pttl_ms,
        "redis_type": "string",
        "present": True,
    }


def _capture_manifest_material(
    capture: CanonicalOhlcvWriterReceiptConsumerCapture,
) -> dict[str, Any]:
    return {
        "schema_version": (
            CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_MANIFEST_SCHEMA_VERSION
        ),
        "evidence_classification": (
            CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_EVIDENCE_CLASSIFICATION
        ),
        "downstream_status": (
            CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_DOWNSTREAM_STATUS
        ),
        "source_key": capture.source_key,
        "archive_key": capture.archive_key,
        "receipt_key": capture.receipt_key,
        "latest_pointer_key": capture.latest_pointer_key,
        "revision_id": capture.revision_id,
        "producer_role": capture.producer_role,
        "producer_code_sha256": capture.producer_code_sha256,
        "producer_config_sha256": capture.producer_config_sha256,
        "writer_receipt_sha256": capture.writer_receipt_sha256,
        "writer_publication_available_at": (
            capture.writer_publication_available_at
        ),
        "discovery_batch_id": capture.discovery_batch_id,
        "discovery_batch_material_sha256": (
            capture.discovery_batch_material_sha256
        ),
        "discovery_batch_material_json": capture.discovery_batch_material_json,
        "discovery_server_observed_at": capture.discovery_server_observed_at,
        "discovery_pointer_pttl_ms": capture.discovery_pointer_pttl_ms,
        "authoritative_batch_id": capture.authoritative_batch_id,
        "authoritative_batch_material_sha256": (
            capture.authoritative_batch_material_sha256
        ),
        "authoritative_batch_material_json": (
            capture.authoritative_batch_material_json
        ),
        "authoritative_server_observed_at": (
            capture.authoritative_server_observed_at
        ),
        "consumer_observed_at": capture.consumer_observed_at,
        "ordered_atomic_source_results": [
            _manifest_result_material(
                source_key=capture.source_key,
                payload=capture._canonical_payload_bytes,
                pttl_ms=capture.canonical_pttl_ms,
            ),
            _manifest_result_material(
                source_key=capture.archive_key,
                payload=capture._canonical_payload_bytes,
                pttl_ms=capture.archive_pttl_ms,
            ),
            _manifest_result_material(
                source_key=capture.receipt_key,
                payload=capture._receipt_payload_bytes,
                pttl_ms=capture.receipt_pttl_ms,
            ),
            _manifest_result_material(
                source_key=capture.latest_pointer_key,
                payload=capture._pointer_payload_bytes,
                pttl_ms=capture.pointer_pttl_ms,
            ),
        ],
        "canonical_archive_exact_match": True,
        "current_pointer_verified": True,
        "writer_publication_receipt_verified": True,
        "producer_identity_allowlisted": True,
        "trusted_allowlist_material_json": capture.trusted_allowlist_material_json,
        "trusted_allowlist_sha256": capture.trusted_allowlist_sha256,
        "canonical_payload_address": _address_material(
            capture.canonical_payload_address
        ),
        "receipt_payload_address": _address_material(capture.receipt_payload_address),
        "pointer_payload_address": _address_material(capture.pointer_payload_address),
        **{field_name: False for field_name in _CONSUMER_AUTHORITY_FIELDS},
    }


def _validate_capture(capture: CanonicalOhlcvWriterReceiptConsumerCapture) -> None:
    if capture._construction_token is not _CONSTRUCTION_TOKEN:
        _integrity_error("canonical_ohlcv_consumer_factory_construction_required")
    if (
        capture.schema_version
        != CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_SCHEMA_VERSION
        or capture.evidence_classification
        != CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_EVIDENCE_CLASSIFICATION
        or capture.downstream_status
        != CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_DOWNSTREAM_STATUS
        or any(
            getattr(capture, field_name) is not False
            for field_name in _CONSUMER_AUTHORITY_FIELDS
        )
        or capture.writer_publication_receipt_verified is not True
        or capture.producer_identity_allowlisted is not True
        or capture.current_pointer_verified is not True
        or capture.canonical_archive_exact_match is not True
        or capture.atomic_four_key_reopen_verified is not True
        or capture.immutable_cas_captured is not True
        or type(capture._source_payload_store) is not ImmutableSourcePayloadStore
        or type(capture._canonical_payload_bytes) is not bytes
        or type(capture._receipt_payload_bytes) is not bytes
        or type(capture._pointer_payload_bytes) is not bytes
        or type(capture.validated_window) is not ValidatedOHLCVClosedWindow
        or any(
            type(value) is not str
            for value in (
                capture.source_key,
                capture.archive_key,
                capture.receipt_key,
                capture.latest_pointer_key,
                capture.revision_id,
                capture.producer_role,
                capture.producer_code_sha256,
                capture.producer_config_sha256,
                capture.writer_receipt_sha256,
                capture.writer_publication_available_at,
                capture.discovery_batch_id,
                capture.discovery_batch_material_sha256,
                capture.discovery_batch_material_json,
                capture.discovery_server_observed_at,
                capture.authoritative_batch_id,
                capture.authoritative_batch_material_sha256,
                capture.authoritative_batch_material_json,
                capture.authoritative_server_observed_at,
                capture.consumer_observed_at,
                capture.tuple_manifest_sha256,
                capture.tuple_manifest_json,
                capture.trusted_allowlist_sha256,
                capture.trusted_allowlist_material_json,
            )
        )
        or any(
            type(value) is not int or value <= 0
            for value in (
                capture.consumer_observed_at_ms,
                capture.discovery_pointer_pttl_ms,
                capture.canonical_pttl_ms,
                capture.archive_pttl_ms,
                capture.receipt_pttl_ms,
                capture.pointer_pttl_ms,
                capture.exact_payload_byte_count,
                capture.row_count,
            )
        )
        or any(
            type(address) is not SourcePayloadAddress
            for address in (
                capture.canonical_payload_address,
                capture.receipt_payload_address,
                capture.pointer_payload_address,
                capture.tuple_manifest_address,
            )
        )
    ):
        _integrity_error("canonical_ohlcv_consumer_capture_flags_invalid")
    receipt = _parse_receipt(capture._receipt_payload_bytes)
    try:
        symbol, timeframe = _validated_symbol_timeframe(
            receipt.get("symbol"),
            receipt.get("timeframe"),
        )
    except CanonicalOhlcvWriterReceiptConsumerValidationError as exc:
        raise CanonicalOhlcvWriterReceiptConsumerIntegrityError(
            "canonical_ohlcv_consumer_capture_receipt_binding_invalid"
        ) from exc
    revision_id = receipt.get("revision_id")
    if type(revision_id) is not str or _REVISION_RE.fullmatch(revision_id) is None:
        _integrity_error("canonical_ohlcv_consumer_capture_receipt_binding_invalid")
    expected_source_key = f"{CANONICAL_KEY_PREFIX}binance:{symbol}:{timeframe}"
    expected_archive_key = (
        f"{ARCHIVE_KEY_PREFIX}binance:{symbol}:{timeframe}:{revision_id}"
    )
    expected_receipt_key = f"{RECEIPT_KEY_PREFIX}{revision_id}"
    expected_pointer_key = (
        f"{LATEST_POINTER_KEY_PREFIX}binance:{symbol}:{timeframe}"
    )
    if (
        capture.source_key != expected_source_key
        or capture.archive_key != expected_archive_key
        or capture.receipt_key != expected_receipt_key
        or capture.latest_pointer_key != expected_pointer_key
        or capture.revision_id != revision_id
        or hashlib.sha256(capture._canonical_payload_bytes).hexdigest()
        != capture.exact_payload_sha256
        or len(capture._canonical_payload_bytes) != capture.exact_payload_byte_count
        or capture._pointer_payload_bytes != capture.revision_id.encode("ascii")
    ):
        _integrity_error("canonical_ohlcv_consumer_capture_exact_bytes_invalid")
    trusted_allowlist = _trusted_allowlist_from_material(
        material_json=capture.trusted_allowlist_material_json,
        material_sha256=capture.trusted_allowlist_sha256,
    )
    consumer_clock = _parse_clock(
        capture.consumer_observed_at,
        reason="canonical_ohlcv_consumer_clock_invalid",
    )
    if int(consumer_clock.timestamp() * 1000) != capture.consumer_observed_at_ms:
        _integrity_error("canonical_ohlcv_consumer_capture_clock_binding_invalid")
    rederived_receipt, revalidated_window = _validate_writer_receipt(
        receipt_bytes=capture._receipt_payload_bytes,
        canonical_bytes=capture._canonical_payload_bytes,
        canonical_key=capture.source_key,
        archive_key=capture.archive_key,
        receipt_key=capture.receipt_key,
        pointer_key=capture.latest_pointer_key,
        revision_id=capture.revision_id,
        symbol=symbol,
        timeframe=timeframe,
        trusted_allowlist=trusted_allowlist,
        discovery_server_observed_at=capture.discovery_server_observed_at,
        authoritative_server_observed_at=(
            capture.authoritative_server_observed_at
        ),
        consumer_observed_at=capture.consumer_observed_at,
        discovery_pointer_pttl_ms=capture.discovery_pointer_pttl_ms,
        canonical_pttl_ms=capture.canonical_pttl_ms,
        archive_pttl_ms=capture.archive_pttl_ms,
        receipt_pttl_ms=capture.receipt_pttl_ms,
        pointer_pttl_ms=capture.pointer_pttl_ms,
    )
    if (
        rederived_receipt != receipt
        or revalidated_window != capture.validated_window
        or capture.row_count != revalidated_window.row_count
        or capture.exact_payload_sha256
        != revalidated_window.exact_payload_sha256
        or capture.exact_payload_byte_count
        != revalidated_window.exact_payload_byte_count
        or capture.producer_role != receipt["producer_role"]
        or capture.producer_code_sha256 != receipt["producer_code_sha256"]
        or capture.producer_config_sha256 != receipt["producer_config_sha256"]
        or capture.writer_receipt_sha256 != receipt["receipt_sha256"]
        or capture.writer_publication_available_at
        != receipt["publication_available_at"]
    ):
        _integrity_error("canonical_ohlcv_consumer_capture_receipt_binding_invalid")
    _validate_batch_identity(
        batch_id=capture.discovery_batch_id,
        material_sha256=capture.discovery_batch_material_sha256,
        material_json=capture.discovery_batch_material_json,
        server_observed_at=capture.discovery_server_observed_at,
        sources=(
            (
                capture.latest_pointer_key,
                capture._pointer_payload_bytes,
                capture.discovery_pointer_pttl_ms,
            ),
        ),
    )
    _validate_batch_identity(
        batch_id=capture.authoritative_batch_id,
        material_sha256=capture.authoritative_batch_material_sha256,
        material_json=capture.authoritative_batch_material_json,
        server_observed_at=capture.authoritative_server_observed_at,
        sources=(
            (
                capture.source_key,
                capture._canonical_payload_bytes,
                capture.canonical_pttl_ms,
            ),
            (
                capture.archive_key,
                capture._canonical_payload_bytes,
                capture.archive_pttl_ms,
            ),
            (
                capture.receipt_key,
                capture._receipt_payload_bytes,
                capture.receipt_pttl_ms,
            ),
            (
                capture.latest_pointer_key,
                capture._pointer_payload_bytes,
                capture.pointer_pttl_ms,
            ),
        ),
    )
    expected_manifest_bytes = _canonical_json_bytes(
        _capture_manifest_material(capture),
        maximum=MAX_MANIFEST_BYTES,
        reason="canonical_ohlcv_consumer_manifest_binding_invalid",
    )
    try:
        manifest_bytes = capture.tuple_manifest_json.encode("ascii")
    except (AttributeError, UnicodeEncodeError):
        _integrity_error("canonical_ohlcv_consumer_manifest_json_invalid")
    if (
        not hmac.compare_digest(manifest_bytes, expected_manifest_bytes)
        or hashlib.sha256(manifest_bytes).hexdigest()
        != capture.tuple_manifest_sha256
    ):
        _integrity_error("canonical_ohlcv_consumer_manifest_binding_invalid")
    for address, expected, reason in (
        (
            capture.canonical_payload_address,
            capture._canonical_payload_bytes,
            "canonical_ohlcv_consumer_canonical_cas_readback_failed",
        ),
        (
            capture.receipt_payload_address,
            capture._receipt_payload_bytes,
            "canonical_ohlcv_consumer_receipt_cas_readback_failed",
        ),
        (
            capture.pointer_payload_address,
            capture._pointer_payload_bytes,
            "canonical_ohlcv_consumer_pointer_cas_readback_failed",
        ),
        (
            capture.tuple_manifest_address,
            manifest_bytes,
            "canonical_ohlcv_consumer_manifest_cas_readback_failed",
        ),
    ):
        _fresh_exact_readback(
            capture._source_payload_store,
            address,
            expected,
            reason=reason,
        )


def consume_current_canonical_ohlcv_writer_receipt(
    redis_client: RawRedisSourceClient,
    source_payload_store: ImmutableSourcePayloadStore,
    *,
    expected_symbol: str,
    expected_timeframe: str,
    trusted_writer_code_sha256_by_role: Mapping[str, Collection[str]],
    consumer_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    max_attempts: int = MAX_READ_ATTEMPTS,
) -> CanonicalOhlcvWriterReceiptConsumerCapture:
    """Verify and retain the current genuine writer publication fail closed."""

    symbol, timeframe = _validated_symbol_timeframe(
        expected_symbol,
        expected_timeframe,
    )
    if type(source_payload_store) is not ImmutableSourcePayloadStore:
        _validation_error("canonical_ohlcv_consumer_authentic_cas_store_required")
    if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_READ_ATTEMPTS:
        _validation_error("canonical_ohlcv_consumer_read_attempts_invalid")
    trusted_allowlist, allowlist_json, allowlist_sha256 = _validated_allowlist(
        trusted_writer_code_sha256_by_role
    )
    source_key = f"{CANONICAL_KEY_PREFIX}binance:{symbol}:{timeframe}"
    pointer_key = f"{LATEST_POINTER_KEY_PREFIX}binance:{symbol}:{timeframe}"

    for attempt in range(1, max_attempts + 1):
        revision_id, discovered_pointer_bytes, discovery_batch = _discover_revision(
            redis_client,
            pointer_key=pointer_key,
        )
        archive_key = (
            f"{ARCHIVE_KEY_PREFIX}binance:{symbol}:{timeframe}:{revision_id}"
        )
        receipt_key = f"{RECEIPT_KEY_PREFIX}{revision_id}"
        authoritative_keys = (source_key, archive_key, receipt_key, pointer_key)
        authoritative_batch = _read_atomic(redis_client, authoritative_keys)
        if (
            type(authoritative_batch) is not AtomicRedisSourceReadBatch
            or len(authoritative_batch.results) != len(authoritative_keys)
        ):
            _integrity_error("canonical_ohlcv_consumer_authoritative_batch_invalid")
        canonical_result, archive_result, receipt_result, pointer_result = (
            authoritative_batch.results
        )
        canonical_bytes = _required_result(
            canonical_result,
            expected_key=source_key,
            reason="canonical_ohlcv_consumer_canonical_unavailable",
        )
        archive_bytes = _required_result(
            archive_result,
            expected_key=archive_key,
            reason="canonical_ohlcv_consumer_archive_unavailable",
        )
        receipt_bytes = _required_result(
            receipt_result,
            expected_key=receipt_key,
            reason="canonical_ohlcv_consumer_receipt_unavailable",
        )
        pointer_bytes = _required_result(
            pointer_result,
            expected_key=pointer_key,
            reason="canonical_ohlcv_consumer_pointer_unavailable",
        )
        if pointer_bytes != discovered_pointer_bytes:
            if attempt < max_attempts:
                continue
            _integrity_error("canonical_ohlcv_consumer_pointer_race_retry_exhausted")
        if not hmac.compare_digest(canonical_bytes, archive_bytes):
            if attempt < max_attempts:
                continue
            _integrity_error("canonical_ohlcv_consumer_prepare_race_retry_exhausted")

        _consumer_datetime, consumer_observed_at, consumer_observed_at_ms = (
            _sample_consumer_clock(consumer_clock)
        )
        receipt, validated = _validate_writer_receipt(
            receipt_bytes=receipt_bytes,
            canonical_bytes=canonical_bytes,
            canonical_key=source_key,
            archive_key=archive_key,
            receipt_key=receipt_key,
            pointer_key=pointer_key,
            revision_id=revision_id,
            symbol=symbol,
            timeframe=timeframe,
            trusted_allowlist=trusted_allowlist,
            discovery_server_observed_at=discovery_batch.server_observed_at,
            authoritative_server_observed_at=(
                authoritative_batch.server_observed_at
            ),
            consumer_observed_at=consumer_observed_at,
            discovery_pointer_pttl_ms=discovery_batch.results[0].pttl_ms,
            canonical_pttl_ms=canonical_result.pttl_ms,
            archive_pttl_ms=archive_result.pttl_ms,
            receipt_pttl_ms=receipt_result.pttl_ms,
            pointer_pttl_ms=pointer_result.pttl_ms,
        )

        try:
            canonical_address = source_payload_store.put(
                canonical_bytes,
                expected_sha256=validated.exact_payload_sha256,
                expected_byte_count=validated.exact_payload_byte_count,
            )
            receipt_address = source_payload_store.put(
                receipt_bytes,
                expected_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
                expected_byte_count=len(receipt_bytes),
            )
            pointer_address = source_payload_store.put(
                pointer_bytes,
                expected_sha256=hashlib.sha256(pointer_bytes).hexdigest(),
                expected_byte_count=len(pointer_bytes),
            )
        except SourcePayloadStoreError as exc:
            raise CanonicalOhlcvWriterReceiptConsumerIntegrityError(
                "canonical_ohlcv_consumer_tuple_cas_capture_failed"
            ) from exc
        for address, expected, reason in (
            (
                canonical_address,
                canonical_bytes,
                "canonical_ohlcv_consumer_canonical_cas_readback_failed",
            ),
            (
                receipt_address,
                receipt_bytes,
                "canonical_ohlcv_consumer_receipt_cas_readback_failed",
            ),
            (
                pointer_address,
                pointer_bytes,
                "canonical_ohlcv_consumer_pointer_cas_readback_failed",
            ),
        ):
            _fresh_exact_readback(
                source_payload_store,
                address,
                expected,
                reason=reason,
            )
        manifest = _manifest_material(
            source_key=source_key,
            archive_key=archive_key,
            receipt_key=receipt_key,
            pointer_key=pointer_key,
            revision_id=revision_id,
            receipt=receipt,
            discovery_batch=discovery_batch,
            authoritative_batch=authoritative_batch,
            consumer_observed_at=consumer_observed_at,
            canonical_address=canonical_address,
            receipt_address=receipt_address,
            pointer_address=pointer_address,
            trusted_allowlist_material_json=allowlist_json,
            trusted_allowlist_sha256=allowlist_sha256,
        )
        manifest_bytes = _canonical_json_bytes(
            manifest,
            maximum=MAX_MANIFEST_BYTES,
            reason="canonical_ohlcv_consumer_manifest_invalid",
        )
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        try:
            manifest_address = source_payload_store.put(
                manifest_bytes,
                expected_sha256=manifest_sha256,
                expected_byte_count=len(manifest_bytes),
            )
        except SourcePayloadStoreError as exc:
            raise CanonicalOhlcvWriterReceiptConsumerIntegrityError(
                "canonical_ohlcv_consumer_manifest_cas_capture_failed"
            ) from exc
        _fresh_exact_readback(
            source_payload_store,
            manifest_address,
            manifest_bytes,
            reason="canonical_ohlcv_consumer_manifest_cas_readback_failed",
        )
        return CanonicalOhlcvWriterReceiptConsumerCapture(
            schema_version=CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_SCHEMA_VERSION,
            evidence_classification=(
                CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_EVIDENCE_CLASSIFICATION
            ),
            downstream_status=(
                CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_DOWNSTREAM_STATUS
            ),
            source_key=source_key,
            archive_key=archive_key,
            receipt_key=receipt_key,
            latest_pointer_key=pointer_key,
            revision_id=revision_id,
            producer_role=cast(str, receipt["producer_role"]),
            producer_code_sha256=cast(str, receipt["producer_code_sha256"]),
            producer_config_sha256=cast(str, receipt["producer_config_sha256"]),
            writer_receipt_sha256=cast(str, receipt["receipt_sha256"]),
            writer_publication_available_at=cast(
                str,
                receipt["publication_available_at"],
            ),
            discovery_batch_id=discovery_batch.batch_id,
            discovery_batch_material_sha256=(
                discovery_batch.batch_material_sha256
            ),
            discovery_batch_material_json=(
                discovery_batch.batch_material_json
            ),
            discovery_server_observed_at=discovery_batch.server_observed_at,
            discovery_pointer_pttl_ms=discovery_batch.results[0].pttl_ms,
            authoritative_batch_id=authoritative_batch.batch_id,
            authoritative_batch_material_sha256=(
                authoritative_batch.batch_material_sha256
            ),
            authoritative_batch_material_json=(
                authoritative_batch.batch_material_json
            ),
            authoritative_server_observed_at=(
                authoritative_batch.server_observed_at
            ),
            consumer_observed_at=consumer_observed_at,
            consumer_observed_at_ms=consumer_observed_at_ms,
            canonical_pttl_ms=canonical_result.pttl_ms,
            archive_pttl_ms=archive_result.pttl_ms,
            receipt_pttl_ms=receipt_result.pttl_ms,
            pointer_pttl_ms=pointer_result.pttl_ms,
            exact_payload_sha256=validated.exact_payload_sha256,
            exact_payload_byte_count=validated.exact_payload_byte_count,
            row_count=validated.row_count,
            validated_window=validated,
            canonical_payload_address=canonical_address,
            receipt_payload_address=receipt_address,
            pointer_payload_address=pointer_address,
            tuple_manifest_sha256=manifest_sha256,
            tuple_manifest_json=manifest_bytes.decode("ascii"),
            tuple_manifest_address=manifest_address,
            trusted_allowlist_sha256=allowlist_sha256,
            trusted_allowlist_material_json=allowlist_json,
            _canonical_payload_bytes=canonical_bytes,
            _receipt_payload_bytes=receipt_bytes,
            _pointer_payload_bytes=pointer_bytes,
            _source_payload_store=source_payload_store,
            _construction_token=_CONSTRUCTION_TOKEN,
        )
    _integrity_error("canonical_ohlcv_consumer_read_retry_exhausted")


__all__ = [
    "BINANCE_REST_WRITER_ROLE",
    "BINANCE_WSS_WRITER_ROLE",
    "CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_DOWNSTREAM_STATUS",
    "CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_EVIDENCE_CLASSIFICATION",
    "CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_MANIFEST_SCHEMA_VERSION",
    "CANONICAL_OHLCV_WRITER_RECEIPT_CONSUMER_SCHEMA_VERSION",
    "EXISTING_PAYLOAD_ADOPTER_ROLE",
    "CanonicalOhlcvWriterReceiptConsumerCapture",
    "CanonicalOhlcvWriterReceiptConsumerError",
    "CanonicalOhlcvWriterReceiptConsumerIntegrityError",
    "CanonicalOhlcvWriterReceiptConsumerTransportError",
    "CanonicalOhlcvWriterReceiptConsumerValidationError",
    "consume_current_canonical_ohlcv_writer_receipt",
]
