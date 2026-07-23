"""Bounded receipted Redis publication for canonical closed-candle windows.

The Binance WebSocket publisher and the REST recovery worker both update the
same ``v2:market:ohlcv_closed:*`` keys. A plain client-side GET/merge/SET can
lose a concurrent writer's candle. This module provides one narrowly scoped
WATCH/MULTI/EXEC boundary so every cooperating publisher retries against the
newest committed value.

The one-mebibyte payload ceiling, strict canonical ABI validation, bounded
Redis reads, and retry/row limits are resource and source-integrity invariants.
Every successful write also creates or adopts an immutable revision, commits a
canonical receipt while both the revision and compatibility key still contain
the exact prepared bytes, and atomically reopens the revision, receipt, and
latest pointer.  This proves publication integrity only.  It does not select
markets, grant feature/trainer admission, or authorize paper/live trading.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

import redis

from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    MAX_OHLCV_CLOSED_PAYLOAD_BYTES,
    MAX_OHLCV_CLOSED_ROWS,
    OHLCV_CLOSED_WINDOW_SCHEMA_VERSION,
    SUPPORTED_TRAINER_TIMEFRAMES,
    TIMEFRAME_DURATION_MS,
    OHLCVClosedWindowValidationError,
    ValidatedOHLCVClosedWindow,
    validate_ohlcv_closed_window,
)

CLOSED_WINDOW_MAX_PAYLOAD_BYTES: Final = MAX_OHLCV_CLOSED_PAYLOAD_BYTES
CLOSED_WINDOW_MAX_ROWS: Final = MAX_OHLCV_CLOSED_ROWS
CLOSED_WINDOW_MAX_NEW_ROWS_PER_WRITE: Final = MAX_OHLCV_CLOSED_ROWS
CLOSED_WINDOW_MAX_WRITE_RETRIES: Final = 32
CLOSED_WINDOW_MAX_TTL_SECONDS: Final = 366 * 24 * 60 * 60
CLOSED_WINDOW_MAX_ARCHIVE_TTL_SECONDS: Final = 2 * CLOSED_WINDOW_MAX_TTL_SECONDS
CLOSED_WINDOW_MAX_RECEIPT_BYTES: Final = 64 * 1024
CLOSED_WINDOW_MAX_JSON_STRING_BYTES: Final = 512
CLOSED_WINDOW_MAX_ROW_FIELDS: Final = 64
CLOSED_WINDOW_MAX_NESTED_FIELDS: Final = 64
CLOSED_WINDOW_TTL_POLICIES: Final = ("preserve", "set", "persist")
CLOSED_WINDOW_RECEIPT_CADENCE_COUNT: Final = 3
CLOSED_WINDOW_ARCHIVE_CADENCE_COUNT: Final = 4

_MAX_SIGNED_64 = (1 << 63) - 1
_CANDLE_ID_RE = re.compile(r"^[0-9a-f]{24}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRODUCER_ROLE_RE = re.compile(r"^[A-Z][A-Z0-9_]{7,127}$")
_REVISION_ID_RE = re.compile(r"^v2_ohlcv_closed_[0-9a-f]{64}$")
_CLOCK_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\."
    r"[0-9]{6}Z$"
)

CLOSED_WINDOW_PUBLICATION_RECEIPT_SCHEMA_VERSION: Final = (
    "canonical_closed_ohlcv_publication_postcommit_receipt_v1"
)
CLOSED_WINDOW_PUBLICATION_EVIDENCE_CLASSIFICATION: Final = (
    "POSTCOMMIT_REOPEN_VERIFIED_CANONICAL_CLOSED_OHLCV_PUBLICATION_ONLY"
)
CLOSED_WINDOW_PUBLICATION_DOWNSTREAM_STATUS: Final = (
    "NO_TRAINER_PREDICTION_PAPER_OR_LIVE_AUTHORITY"
)
CLOSED_WINDOW_PUBLICATION_REVISION_DOMAIN: Final = (
    "v2/canonical-closed-ohlcv/publication-revision/v1"
)
CLOSED_WINDOW_ARCHIVE_KEY_PREFIX: Final = "v2:market:ohlcv_closed:archive:"
CLOSED_WINDOW_RECEIPT_KEY_PREFIX: Final = (
    "v2:market:ohlcv_closed:publication_receipt:"
)
CLOSED_WINDOW_RECEIPT_LATEST_KEY_PREFIX: Final = (
    "v2:market:ohlcv_closed:publication_receipt:latest:"
)

BINANCE_WSS_CLOSED_WINDOW_PRODUCER_ROLE: Final = (
    "BINANCE_USDM_KLINE_WSS_CANONICAL_CLOSED_WINDOW_V1"
)
BINANCE_REST_CLOSED_WINDOW_PRODUCER_ROLE: Final = (
    "BINANCE_USDM_KLINE_REST_CANONICAL_CLOSED_WINDOW_V1"
)
EXISTING_CLOSED_WINDOW_ADOPTER_ROLE: Final = (
    "CANONICAL_CLOSED_WINDOW_EXISTING_PAYLOAD_ADOPTER_V1"
)
_KNOWN_PUBLICATION_ROLES: Final = frozenset(
    {
        BINANCE_WSS_CLOSED_WINDOW_PRODUCER_ROLE,
        BINANCE_REST_CLOSED_WINDOW_PRODUCER_ROLE,
        EXISTING_CLOSED_WINDOW_ADOPTER_ROLE,
    }
)

_AUTHORITY_FIELDS: Final = (
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
)

_RECEIPT_FIELDS: Final = frozenset(
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
        *_AUTHORITY_FIELDS,
        "receipt_sha256",
    }
)
_BOUNDED_READ_LUA: Final = """
local kind_reply = redis.call('TYPE', KEYS[1])
local kind = kind_reply['ok']
local ttl = redis.call('PTTL', KEYS[1])
if kind ~= 'string' then
    return {kind, ttl, 0, false}
end
local byte_count = redis.call('STRLEN', KEYS[1])
if byte_count > tonumber(ARGV[1]) then
    return {kind, ttl, byte_count, false}
end
local payload = redis.call('GETRANGE', KEYS[1], 0, byte_count - 1)
return {kind, ttl, byte_count, payload}
""".strip()

_ADOPTION_BOUNDED_READ_LUA: Final = """
-- canonical_closed_ohlcv_adoption_bounded_read_v1
local kind_reply = redis.call('TYPE', KEYS[1])
local kind = kind_reply['ok']
local ttl = redis.call('PTTL', KEYS[1])
local observed = redis.call('TIME')
if kind ~= 'string' then
    return {kind, ttl, 0, false, observed[1], observed[2]}
end
local byte_count = redis.call('STRLEN', KEYS[1])
if byte_count > tonumber(ARGV[1]) then
    return {kind, ttl, byte_count, false, observed[1], observed[2]}
end
local payload = redis.call('GETRANGE', KEYS[1], 0, byte_count - 1)
return {kind, ttl, byte_count, payload, observed[1], observed[2]}
""".strip()

_PREPARE_PUBLICATION_LUA: Final = r"""
-- canonical_closed_ohlcv_publication_prepare_v1
local canonical_key = KEYS[1]
local archive_key = KEYS[2]
local receipt_key = KEYS[3]
local payload = ARGV[1]
local archive_ttl = tonumber(ARGV[2])
local receipt_ttl = tonumber(ARGV[3])
local mutable_ttl = tonumber(ARGV[4])
local ttl_policy = ARGV[5]
local max_payload = tonumber(ARGV[6])
local max_receipt = tonumber(ARGV[7])

if not archive_ttl or not receipt_ttl
   or archive_ttl ~= math.floor(archive_ttl)
   or receipt_ttl ~= math.floor(receipt_ttl)
   or archive_ttl <= receipt_ttl then
  return {"ERROR", "ARCHIVE_TTL_MUST_EXCEED_RECEIPT_TTL"}
end
if string.len(payload) == 0 or string.len(payload) > max_payload then
  return {"ERROR", "PAYLOAD_ARGUMENT_SIZE_INVALID"}
end
local archive_type = redis.call("TYPE", archive_key)["ok"]
if archive_type ~= "none" and archive_type ~= "string" then
  return {"ERROR", "ARCHIVE_TYPE_INVALID"}
end
if archive_type == "string" then
  local archive_len = redis.call("STRLEN", archive_key)
  if archive_len == 0 or archive_len > max_payload then
    return {"ERROR", "ARCHIVE_SIZE_INVALID"}
  end
  if redis.call("GET", archive_key) ~= payload then
    return {"ERROR", "ARCHIVE_IDENTITY_CONFLICT"}
  end
else
  redis.call("SET", archive_key, payload, "EX", archive_ttl)
end
if redis.call("EXPIRE", archive_key, archive_ttl) ~= 1 then
  return {"ERROR", "ARCHIVE_TTL_REFRESH_FAILED"}
end

local existing_receipt = false
local receipt_type = redis.call("TYPE", receipt_key)["ok"]
if receipt_type ~= "none" and receipt_type ~= "string" then
  return {"ERROR", "RECEIPT_TYPE_INVALID"}
end
if receipt_type == "string" then
  local receipt_len = redis.call("STRLEN", receipt_key)
  if receipt_len == 0 or receipt_len > max_receipt then
    return {"ERROR", "RECEIPT_SIZE_INVALID"}
  end
  existing_receipt = redis.call("GET", receipt_key)
end

if ttl_policy == "set" then
  if not mutable_ttl or mutable_ttl ~= math.floor(mutable_ttl)
     or mutable_ttl <= 0 then
    return {"ERROR", "MUTABLE_TTL_INVALID"}
  end
  redis.call("SET", canonical_key, payload, "EX", mutable_ttl)
elseif ttl_policy == "preserve" then
  redis.call("SET", canonical_key, payload, "KEEPTTL")
elseif ttl_policy == "persist" then
  redis.call("SET", canonical_key, payload)
else
  return {"ERROR", "TTL_POLICY_INVALID"}
end
if redis.call("PTTL", archive_key) <= receipt_ttl * 1000 then
  return {"ERROR", "ARCHIVE_TTL_NOT_LONGER_THAN_RECEIPT"}
end
local observed = redis.call("TIME")
return {
  existing_receipt and "IDEMPOTENT_PREPARED" or "PREPARED",
  observed[1],
  observed[2],
  existing_receipt
}
""".strip()

_COMMIT_PUBLICATION_RECEIPT_LUA: Final = r"""
-- canonical_closed_ohlcv_publication_commit_v1
local canonical_key = KEYS[1]
local archive_key = KEYS[2]
local receipt_key = KEYS[3]
local pointer_key = KEYS[4]
local payload = ARGV[1]
local receipt_payload = ARGV[2]
local revision_id = ARGV[3]
local receipt_ttl = tonumber(ARGV[4])
local max_payload = tonumber(ARGV[5])
local max_receipt = tonumber(ARGV[6])

if string.len(payload) == 0 or string.len(payload) > max_payload then
  return {"ERROR", "PAYLOAD_ARGUMENT_SIZE_INVALID"}
end
if string.len(receipt_payload) == 0 or string.len(receipt_payload) > max_receipt then
  return {"ERROR", "RECEIPT_ARGUMENT_SIZE_INVALID"}
end
if redis.call("TYPE", canonical_key)["ok"] ~= "string" then
  return {"RETRY", "CANONICAL_KEY_CHANGED_BEFORE_RECEIPT_COMMIT"}
end
if redis.call("STRLEN", canonical_key) > max_payload
   or redis.call("GET", canonical_key) ~= payload then
  return {"RETRY", "CANONICAL_KEY_CHANGED_BEFORE_RECEIPT_COMMIT"}
end
if redis.call("TYPE", archive_key)["ok"] ~= "string" then
  return {"ERROR", "ARCHIVE_MISSING"}
end
if redis.call("STRLEN", archive_key) > max_payload
   or redis.call("GET", archive_key) ~= payload then
  return {"ERROR", "ARCHIVE_CHANGED_BEFORE_RECEIPT_COMMIT"}
end
if redis.call("PTTL", archive_key) <= receipt_ttl * 1000 then
  return {"ERROR", "ARCHIVE_TTL_NOT_LONGER_THAN_RECEIPT"}
end
local receipt_type = redis.call("TYPE", receipt_key)["ok"]
if receipt_type ~= "none" and receipt_type ~= "string" then
  return {"ERROR", "RECEIPT_TYPE_INVALID"}
end
local committed_receipt = receipt_payload
local commit_status = "COMMITTED"
if receipt_type == "string" then
  local receipt_len = redis.call("STRLEN", receipt_key)
  if receipt_len == 0 or receipt_len > max_receipt then
    return {"ERROR", "RECEIPT_SIZE_INVALID"}
  end
  committed_receipt = redis.call("GET", receipt_key)
  commit_status = committed_receipt == receipt_payload and "IDEMPOTENT" or "ADOPTED"
  if redis.call("EXPIRE", receipt_key, receipt_ttl) ~= 1 then
    return {"ERROR", "RECEIPT_TTL_REFRESH_FAILED"}
  end
else
  redis.call("SET", receipt_key, receipt_payload, "EX", receipt_ttl)
end
local pointer_type = redis.call("TYPE", pointer_key)["ok"]
if pointer_type ~= "none" and pointer_type ~= "string" then
  return {"ERROR", "POINTER_TYPE_INVALID"}
end
redis.call("SET", pointer_key, revision_id, "EX", receipt_ttl)
local observed = redis.call("TIME")
return {commit_status, observed[1], observed[2], committed_receipt}
""".strip()

_COMMIT_ADOPTED_PUBLICATION_RECEIPT_LUA: Final = r"""
-- canonical_closed_ohlcv_adoption_commit_v1
local canonical_key = KEYS[1]
local archive_key = KEYS[2]
local receipt_key = KEYS[3]
local pointer_key = KEYS[4]
local payload = ARGV[1]
local receipt_payload = ARGV[2]
local revision_id = ARGV[3]
local receipt_ttl = tonumber(ARGV[4])
local max_payload = tonumber(ARGV[5])
local max_receipt = tonumber(ARGV[6])

-- Adoption is a migration bridge, never a source-writer replacement. If a
-- writer publishes any pointer after the adoption WATCH/PREPARE boundary,
-- retry and validate that writer's exact receipt instead of overwriting it.
if redis.call("TYPE", pointer_key)["ok"] ~= "none" then
  return {"RETRY", "LATEST_POINTER_APPEARED_BEFORE_ADOPTION_COMMIT"}
end
if string.len(payload) == 0 or string.len(payload) > max_payload then
  return {"ERROR", "PAYLOAD_ARGUMENT_SIZE_INVALID"}
end
if string.len(receipt_payload) == 0 or string.len(receipt_payload) > max_receipt then
  return {"ERROR", "RECEIPT_ARGUMENT_SIZE_INVALID"}
end
if redis.call("TYPE", canonical_key)["ok"] ~= "string"
   or redis.call("STRLEN", canonical_key) > max_payload
   or redis.call("GET", canonical_key) ~= payload then
  return {"RETRY", "CANONICAL_KEY_CHANGED_BEFORE_ADOPTION_COMMIT"}
end
if redis.call("TYPE", archive_key)["ok"] ~= "string"
   or redis.call("STRLEN", archive_key) > max_payload
   or redis.call("GET", archive_key) ~= payload then
  return {"ERROR", "ADOPTION_ARCHIVE_CHANGED_BEFORE_RECEIPT_COMMIT"}
end
if redis.call("PTTL", archive_key) <= receipt_ttl * 1000 then
  return {"ERROR", "ARCHIVE_TTL_NOT_LONGER_THAN_RECEIPT"}
end
local receipt_type = redis.call("TYPE", receipt_key)["ok"]
if receipt_type ~= "none" and receipt_type ~= "string" then
  return {"ERROR", "RECEIPT_TYPE_INVALID"}
end
local committed_receipt = receipt_payload
local commit_status = "COMMITTED"
if receipt_type == "string" then
  local receipt_len = redis.call("STRLEN", receipt_key)
  if receipt_len == 0 or receipt_len > max_receipt then
    return {"ERROR", "RECEIPT_SIZE_INVALID"}
  end
  committed_receipt = redis.call("GET", receipt_key)
  if committed_receipt ~= receipt_payload then
    return {"ERROR", "ADOPTION_RECEIPT_IDENTITY_CONFLICT"}
  end
  commit_status = "IDEMPOTENT"
  if redis.call("EXPIRE", receipt_key, receipt_ttl) ~= 1 then
    return {"ERROR", "RECEIPT_TTL_REFRESH_FAILED"}
  end
else
  redis.call("SET", receipt_key, receipt_payload, "EX", receipt_ttl)
end
redis.call("SET", pointer_key, revision_id, "EX", receipt_ttl)
local observed = redis.call("TIME")
return {commit_status, observed[1], observed[2], committed_receipt}
""".strip()

_REOPEN_PUBLICATION_LUA: Final = r"""
-- canonical_closed_ohlcv_publication_reopen_v1
local canonical_key = KEYS[1]
local archive_key = KEYS[2]
local receipt_key = KEYS[3]
local pointer_key = KEYS[4]
local payload = ARGV[1]
local revision_id = ARGV[2]
local max_payload = tonumber(ARGV[3])
local max_receipt = tonumber(ARGV[4])

if redis.call("TYPE", canonical_key)["ok"] ~= "string"
   or redis.call("STRLEN", canonical_key) > max_payload
   or redis.call("GET", canonical_key) ~= payload then
  return {"RETRY", "CANONICAL_KEY_CHANGED_BEFORE_REOPEN"}
end
if redis.call("TYPE", archive_key)["ok"] ~= "string" then
  return {"ERROR", "ARCHIVE_MISSING"}
end
local archive_len = redis.call("STRLEN", archive_key)
if archive_len == 0 or archive_len > max_payload then
  return {"ERROR", "ARCHIVE_SIZE_INVALID"}
end
local archive_payload = redis.call("GET", archive_key)
if archive_payload ~= payload then
  return {"ERROR", "ARCHIVE_REOPEN_MISMATCH"}
end
if redis.call("TYPE", receipt_key)["ok"] ~= "string" then
  return {"ERROR", "RECEIPT_MISSING"}
end
local receipt_len = redis.call("STRLEN", receipt_key)
if receipt_len == 0 or receipt_len > max_receipt then
  return {"ERROR", "RECEIPT_SIZE_INVALID"}
end
local receipt_payload = redis.call("GET", receipt_key)
if redis.call("TYPE", pointer_key)["ok"] ~= "string" then
  return {"ERROR", "POINTER_MISSING"}
end
local pointer = redis.call("GET", pointer_key)
if pointer ~= revision_id then
  return {"RETRY", "LATEST_POINTER_CHANGED_BEFORE_REOPEN"}
end
local archive_pttl = redis.call("PTTL", archive_key)
local receipt_pttl = redis.call("PTTL", receipt_key)
local pointer_pttl = redis.call("PTTL", pointer_key)
if archive_pttl <= receipt_pttl or archive_pttl <= pointer_pttl
   or receipt_pttl <= 0 or pointer_pttl <= 0 then
  return {"ERROR", "PUBLICATION_TTL_ORDER_INVALID"}
end
local observed = redis.call("TIME")
return {
  "REOPENED",
  archive_payload,
  receipt_payload,
  pointer,
  archive_pttl,
  receipt_pttl,
  pointer_pttl,
  observed[1],
  observed[2]
}
""".strip()


class ClosedWindowRedisStoreError(RuntimeError):
    """A resource, serialization, Redis, or concurrency invariant failed."""


@dataclass(frozen=True, slots=True)
class BoundedClosedWindowPayload:
    """Deterministic JSON suffix that fits the consumer transport boundary."""

    payload_json: str
    payload_sha256: str
    payload_byte_count: int
    row_count: int
    rows_trimmed_for_bytes: int


@dataclass(frozen=True, slots=True)
class ClosedWindowRedisWriteResult:
    """One exact publication after receipt commit and consumer reopen."""

    redis_key: str
    attempts: int
    existing_row_count: int
    submitted_row_count: int
    stored_row_count: int
    rows_deduplicated_or_trimmed_for_row_limit: int
    rows_trimmed_for_bytes: int
    payload_sha256: str
    payload_byte_count: int
    ttl_policy: str
    ttl_seconds: int | None
    previous_pttl_ms: int
    invalid_existing_replaced: bool
    revision_id: str | None = None
    archive_key: str | None = None
    receipt_key: str | None = None
    latest_receipt_pointer_key: str | None = None
    publication_available_at: str | None = None
    prepare_observed_at: str | None = None
    receipt_postcommit_observed_at: str | None = None
    consumer_reopened_at: str | None = None
    receipt_sha256: str | None = None
    producer_role: str | None = None
    producer_code_sha256: str | None = None
    producer_config_sha256: str | None = None
    receipt_ttl_seconds: int | None = None
    archive_ttl_seconds: int | None = None
    receipt: Mapping[str, Any] | None = field(default=None, repr=False)
    exact_source_schema_validated: bool = field(default=True, init=False)
    immutable_cas_captured: bool = field(default=False, init=False)
    publication_receipt_verified: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class ClosedWindowRedisAdoptionResult:
    """Verified migration result without a legacy source-authenticity claim."""

    redis_key: str
    status: str
    attempts: int
    row_count: int
    payload_sha256: str
    payload_byte_count: int
    previous_pttl_ms: int
    revision_id: str
    archive_key: str
    receipt_key: str
    latest_receipt_pointer_key: str
    producer_role: str
    receipt: Mapping[str, Any] = field(repr=False)
    exact_source_schema_validated: bool = field(default=True, init=False)
    immutable_cas_captured: bool = field(default=True, init=False)
    publication_receipt_verified: bool = field(default=True, init=False)
    producer_authenticity_verified: bool = field(default=False, init=False)
    legacy_source_authenticity_verified: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    prediction_authorized: bool = field(default=False, init=False)
    paper_trading_authorized: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)


class _ClosedWindowConcurrentMutation(RuntimeError):
    """Internal bounded-retry signal for a cooperating later publication."""


def _invalid(reason: str) -> NoReturn:
    raise ClosedWindowRedisStoreError(reason) from None


def _canonical_json_bytes(value: object, *, maximum: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _invalid("closed_window_publication_canonical_json_invalid")
    if not encoded or len(encoded) > maximum:
        _invalid("closed_window_publication_canonical_json_size_invalid")
    return encoded


def _stable_sha256(value: object) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(value, maximum=CLOSED_WINDOW_MAX_RECEIPT_BYTES)
    ).hexdigest()


def _validated_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _invalid(f"closed_window_{field_name}_invalid")
    return value


def _validated_producer_role(value: object) -> str:
    if type(value) is not str or _PRODUCER_ROLE_RE.fullmatch(value) is None:
        _invalid("closed_window_producer_role_invalid")
    return value


def _validated_publication_ttls(
    *,
    ttl_policy: str,
    mutable_ttl_seconds: int | None,
    receipt_ttl_seconds: object,
    archive_ttl_seconds: object,
) -> tuple[int, int]:
    receipt_ttl = _exact_int(
        receipt_ttl_seconds,
        field_name="receipt_ttl_seconds",
        minimum=1,
        maximum=CLOSED_WINDOW_MAX_TTL_SECONDS,
    )
    archive_ttl = _exact_int(
        archive_ttl_seconds,
        field_name="archive_ttl_seconds",
        minimum=2,
        maximum=CLOSED_WINDOW_MAX_ARCHIVE_TTL_SECONDS,
    )
    if archive_ttl <= receipt_ttl:
        _invalid("closed_window_archive_ttl_must_exceed_receipt_ttl")
    # Evidence freshness is deliberately independent of cache residency. A
    # canonical compatibility key may remain available for recovery after its
    # proof expires; consumers must then fail closed until a writer publishes
    # and reopens a fresh receipt. Requiring evidence to live as long as the
    # mutable cache would retain one full immutable window per close for the
    # whole cache TTL and can exhaust Redis memory.
    return receipt_ttl, archive_ttl


def cadence_bounded_publication_ttls(timeframe: object) -> tuple[int, int]:
    """Derive bounded receipt/archive retention from the source cadence.

    Three expected close intervals tolerate ordinary reconnect jitter. The
    immutable archive remains available for one additional interval so it
    always outlives its receipt and latest pointer. These horizons are proof
    freshness bounds, not market-selection or trading thresholds.
    """

    if type(timeframe) is not str or timeframe not in SUPPORTED_TRAINER_TIMEFRAMES:
        _invalid("closed_window_timeframe_unsupported")
    cadence_seconds = TIMEFRAME_DURATION_MS[timeframe] // 1000
    receipt_ttl = cadence_seconds * CLOSED_WINDOW_RECEIPT_CADENCE_COUNT
    archive_ttl = cadence_seconds * CLOSED_WINDOW_ARCHIVE_CADENCE_COUNT
    if (
        receipt_ttl <= 0
        or receipt_ttl > CLOSED_WINDOW_MAX_TTL_SECONDS
        or archive_ttl <= receipt_ttl
        or archive_ttl > CLOSED_WINDOW_MAX_ARCHIVE_TTL_SECONDS
    ):
        _invalid("closed_window_publication_cadence_ttl_invalid")
    return receipt_ttl, archive_ttl


def _redis_clock(seconds: object, microseconds: object) -> str:
    try:
        if type(seconds) is bytes:
            seconds = seconds.decode("ascii", errors="strict")
        if type(microseconds) is bytes:
            microseconds = microseconds.decode("ascii", errors="strict")
        if type(seconds) not in (str, int) or type(microseconds) not in (str, int):
            raise ValueError
        seconds_int = int(cast(str | int, seconds))
        microseconds_int = int(cast(str | int, microseconds))
        if (
            str(seconds_int) != str(seconds)
            or str(microseconds_int) != str(microseconds)
            or seconds_int < 0
            or not 0 <= microseconds_int <= 999_999
        ):
            raise ValueError
        observed = datetime.fromtimestamp(
            seconds_int + microseconds_int / 1_000_000,
            tz=UTC,
        )
    except (OSError, OverflowError, UnicodeDecodeError, ValueError):
        _invalid("closed_window_publication_redis_time_invalid")
    return observed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_clock(value: object) -> datetime:
    if type(value) is not str or _CLOCK_RE.fullmatch(value) is None:
        _invalid("closed_window_publication_clock_invalid")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        _invalid("closed_window_publication_clock_invalid")
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        _invalid("closed_window_publication_clock_invalid")
    return parsed


def _response_text(value: object) -> str:
    if type(value) is bytes:
        try:
            return value.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            _invalid("closed_window_publication_redis_response_invalid")
    if type(value) is str:
        return value
    _invalid("closed_window_publication_redis_response_invalid")


def _publication_response(
    value: object,
    *,
    expected_size: int,
    expected_statuses: tuple[str, ...],
) -> list[object]:
    if type(value) not in (list, tuple):
        _invalid("closed_window_publication_redis_response_invalid")
    response = list(cast(Sequence[object], value))
    if len(response) == 2 and _response_text(response[0]) in {"ERROR", "RETRY"}:
        status = _response_text(response[0])
        reason = _response_text(response[1])
        if status == "RETRY":
            raise _ClosedWindowConcurrentMutation(reason)
        _invalid(f"closed_window_publication_{reason.lower()}")
    if len(response) != expected_size:
        _invalid("closed_window_publication_redis_response_invalid")
    status = _response_text(response[0])
    if status not in expected_statuses:
        _invalid("closed_window_publication_redis_status_invalid")
    return response


def _redis_eval(
    client: object,
    script: str,
    keys: Sequence[str],
    arguments: Sequence[object],
) -> object:
    evaluate = getattr(client, "eval", None)
    if not callable(evaluate):
        _invalid("closed_window_redis_client_eval_required")
    try:
        return evaluate(script, len(keys), *keys, *arguments)
    except (ClosedWindowRedisStoreError, _ClosedWindowConcurrentMutation):
        raise
    except Exception as exc:
        raise ClosedWindowRedisStoreError(
            f"closed_window_redis_operation_failed:{type(exc).__name__}"
        ) from exc


def _exact_int(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid(f"closed_window_{field_name}_invalid")
    return value


def _bounded_utf8(value: str, *, field_name: str, maximum: int) -> None:
    try:
        byte_count = len(value.encode("utf-8", errors="strict"))
    except UnicodeError:
        _invalid(f"closed_window_{field_name}_invalid")
    if byte_count > maximum:
        _invalid(f"closed_window_{field_name}_invalid")


def _preflight_json_value(value: object, *, depth: int) -> None:
    """Reject structures that could make JSON encoding unbounded or recursive."""

    if type(value) is str:
        _bounded_utf8(
            value,
            field_name="row_string",
            maximum=CLOSED_WINDOW_MAX_JSON_STRING_BYTES,
        )
        return
    if type(value) is bool:
        return
    if type(value) is int:
        if not -_MAX_SIGNED_64 - 1 <= value <= _MAX_SIGNED_64:
            _invalid("closed_window_row_integer_invalid")
        return
    if type(value) is float:
        if not math.isfinite(value):
            _invalid("closed_window_row_number_nonfinite")
        return
    if type(value) is not dict or depth >= 1:
        _invalid("closed_window_row_json_shape_invalid")

    nested = cast(dict[object, object], value)
    if len(nested) > CLOSED_WINDOW_MAX_NESTED_FIELDS:
        _invalid("closed_window_row_nested_field_count_invalid")
    try:
        pairs = tuple(nested.items())
    except RuntimeError:
        _invalid("closed_window_row_mutated_during_preflight")
    if len(pairs) != len(nested):
        _invalid("closed_window_row_mutated_during_preflight")
    for key, nested_value in pairs:
        if type(key) is not str:
            _invalid("closed_window_row_key_invalid")
        _bounded_utf8(key, field_name="row_key", maximum=128)
        _preflight_json_value(nested_value, depth=depth + 1)


def _snapshot_rows(
    rows: object,
    *,
    field_name: str,
    maximum: int,
    allow_empty: bool,
) -> tuple[dict[str, Any], ...]:
    if type(rows) is list:
        # Snapshot at most one element beyond the bound before validation. A
        # concurrently appended caller list can neither extend this iteration
        # nor keep the writer busy without limit.
        source = tuple(cast(list[object], rows)[: maximum + 1])
    elif type(rows) is tuple:
        source = cast(tuple[object, ...], rows)
    else:
        _invalid(f"closed_window_{field_name}_container_invalid")
    if len(source) > maximum or (not allow_empty and not source):
        _invalid(f"closed_window_{field_name}_count_invalid")

    snapshot: list[dict[str, Any]] = []
    for row in source:
        if type(row) is not dict:
            _invalid(f"closed_window_{field_name}_row_invalid")
        raw_row = cast(dict[object, object], row)
        if len(raw_row) > CLOSED_WINDOW_MAX_ROW_FIELDS:
            _invalid(f"closed_window_{field_name}_row_field_count_invalid")
        try:
            copied = dict(raw_row)
        except RuntimeError:
            _invalid(f"closed_window_{field_name}_row_mutated_during_snapshot")
        if len(copied) != len(raw_row):
            _invalid(f"closed_window_{field_name}_row_mutated_during_snapshot")
        for key, value in copied.items():
            if type(key) is not str:
                _invalid("closed_window_row_key_invalid")
            _bounded_utf8(key, field_name="row_key", maximum=128)
            _preflight_json_value(value, depth=0)
        snapshot.append(cast(dict[str, Any], copied))
    return tuple(snapshot)


def _try_encode_rows(
    rows: tuple[dict[str, Any], ...],
    *,
    payload_cap: int,
) -> tuple[str, int] | None:
    """Stream deterministic ASCII JSON and stop immediately after the cap."""

    encoder = json.JSONEncoder(
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    chunks: list[str] = []
    byte_count = 0
    try:
        for chunk in encoder.iterencode(rows):
            chunk_bytes = chunk.encode("ascii", errors="strict")
            byte_count += len(chunk_bytes)
            if byte_count > payload_cap:
                return None
            chunks.append(chunk)
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        _invalid("closed_window_payload_json_invalid")
    return "".join(chunks), byte_count


def serialize_bounded_closed_window(
    rows: object,
    *,
    max_payload_bytes: object = CLOSED_WINDOW_MAX_PAYLOAD_BYTES,
    minimum_rows_to_preserve: object = 1,
) -> BoundedClosedWindowPayload:
    """Serialize the newest possible suffix without crossing the byte cap."""

    payload_cap = _exact_int(
        max_payload_bytes,
        field_name="max_payload_bytes",
        minimum=2,
        maximum=CLOSED_WINDOW_MAX_PAYLOAD_BYTES,
    )
    snapshot = _snapshot_rows(
        rows,
        field_name="rows",
        maximum=CLOSED_WINDOW_MAX_ROWS,
        allow_empty=False,
    )
    minimum_rows = _exact_int(
        minimum_rows_to_preserve,
        field_name="minimum_rows_to_preserve",
        minimum=1,
        maximum=len(snapshot),
    )

    encoded = _try_encode_rows(snapshot, payload_cap=payload_cap)
    trim_count = 0
    if encoded is None:
        # Suffix size is monotonic as older rows are removed. Find the smallest
        # trim that fits, preserving the maximum amount of recent history.
        low = 1
        high = len(snapshot) - minimum_rows
        fitting: tuple[int, str, int] | None = None
        while low <= high:
            middle = (low + high) // 2
            candidate = _try_encode_rows(
                snapshot[middle:],
                payload_cap=payload_cap,
            )
            if candidate is not None:
                fitting = (middle, candidate[0], candidate[1])
                high = middle - 1
            else:
                low = middle + 1
        if fitting is None:
            _invalid("closed_window_minimum_rows_exceed_payload_cap")
        trim_count, payload, byte_count = fitting
    else:
        payload, byte_count = encoded

    return BoundedClosedWindowPayload(
        payload_json=payload,
        payload_sha256=hashlib.sha256(payload.encode("ascii")).hexdigest(),
        payload_byte_count=byte_count,
        row_count=len(snapshot) - trim_count,
        rows_trimmed_for_bytes=trim_count,
    )


def _validated_key(value: object) -> tuple[str, str, str, str]:
    if type(value) is not str:
        _invalid("closed_window_redis_key_invalid")
    _bounded_utf8(value, field_name="redis_key", maximum=512)
    parts = value.split(":")
    if (
        len(parts) != 6
        or parts[:4] != ["v2", "market", "ohlcv_closed", "binance"]
        or _SYMBOL_RE.fullmatch(parts[4]) is None
        or parts[5] not in SUPPORTED_TRAINER_TIMEFRAMES
    ):
        _invalid("closed_window_redis_key_invalid")
    return value, parts[3], parts[4], parts[5]


def _validated_ttl_policy(
    policy: object,
    ttl_seconds: object,
) -> tuple[str, int | None]:
    if type(policy) is not str or policy not in CLOSED_WINDOW_TTL_POLICIES:
        _invalid("closed_window_ttl_policy_invalid")
    if policy == "set":
        ttl = _exact_int(
            ttl_seconds,
            field_name="ttl_seconds",
            minimum=1,
            maximum=CLOSED_WINDOW_MAX_TTL_SECONDS,
        )
    else:
        if ttl_seconds is not None:
            _invalid("closed_window_ttl_seconds_for_policy_invalid")
        ttl = None
    return policy, ttl


def _validated_pttl(value: object, *, redis_type: str) -> int:
    if type(value) is not int or not -2 <= value <= _MAX_SIGNED_64:
        _invalid("closed_window_existing_pttl_invalid")
    if redis_type == "none" and value != -2:
        _invalid("closed_window_missing_key_pttl_inconsistent")
    if redis_type != "none" and value == -2:
        _invalid("closed_window_existing_key_pttl_inconsistent")
    return value


def _redis_type(value: object) -> str:
    # This API intentionally requires decode_responses=False. Otherwise
    # redis-py may try to decode corrupt existing bytes before explicit repair
    # authority can inspect and replace them.
    if type(value) is not bytes:
        _invalid("closed_window_redis_client_requires_binary_responses")
    try:
        decoded = value.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        _invalid("closed_window_existing_redis_type_invalid")
    if decoded not in {"none", "string", "list", "set", "zset", "hash", "stream"}:
        _invalid("closed_window_existing_redis_type_invalid")
    return decoded


def _exact_payload_bytes(raw: object, *, expected_byte_count: int) -> bytes:
    if type(raw) is not bytes:
        _invalid("closed_window_existing_payload_type_invalid")
    payload = raw
    if len(payload) != expected_byte_count:
        _invalid("closed_window_existing_payload_length_changed")
    return payload


def _validated_schema_rows(
    payload: bytes,
    *,
    symbol: str,
    timeframe: str,
    error_prefix: str,
) -> list[dict[str, Any]]:
    try:
        validate_ohlcv_closed_window(
            payload,
            symbol=symbol,
            timeframe=timeframe,
        )
    except OHLCVClosedWindowValidationError as exc:
        _invalid(f"closed_window_{error_prefix}_schema_invalid:{exc}")
    # The preceding strict decoder rejects duplicate keys, nonfinite constants,
    # invalid UTF-8, wrong field sets, and every canonical row invariant.
    decoded = json.loads(payload)
    return cast(list[dict[str, Any]], decoded)


def _validated_schema_artifact(
    payload: bytes,
    *,
    symbol: str,
    timeframe: str,
    error_prefix: str,
) -> ValidatedOHLCVClosedWindow:
    try:
        return validate_ohlcv_closed_window(
            payload,
            symbol=symbol,
            timeframe=timeframe,
        )
    except OHLCVClosedWindowValidationError as exc:
        _invalid(f"closed_window_{error_prefix}_schema_invalid:{exc}")


def _publication_revision_id(
    *,
    canonical_key: str,
    payload_sha256: str,
    payload_byte_count: int,
    producer_role: str,
    producer_code_sha256: str,
    producer_config_sha256: str,
    ttl_policy: str,
    mutable_ttl_seconds: int | None,
    receipt_ttl_seconds: int,
    archive_ttl_seconds: int,
) -> str:
    digest = _stable_sha256(
        {
            "domain": CLOSED_WINDOW_PUBLICATION_REVISION_DOMAIN,
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


def _publication_keys(
    *,
    revision_id: str,
    symbol: str,
    timeframe: str,
) -> tuple[str, str, str]:
    if _REVISION_ID_RE.fullmatch(revision_id) is None:
        _invalid("closed_window_revision_id_invalid")
    archive_key = (
        f"{CLOSED_WINDOW_ARCHIVE_KEY_PREFIX}binance:{symbol}:{timeframe}:{revision_id}"
    )
    receipt_key = f"{CLOSED_WINDOW_RECEIPT_KEY_PREFIX}{revision_id}"
    pointer_key = (
        f"{CLOSED_WINDOW_RECEIPT_LATEST_KEY_PREFIX}binance:{symbol}:{timeframe}"
    )
    return archive_key, receipt_key, pointer_key


def _build_publication_receipt(
    *,
    artifact: ValidatedOHLCVClosedWindow,
    canonical_key: str,
    archive_key: str,
    receipt_key: str,
    pointer_key: str,
    revision_id: str,
    publication_available_at: str,
    producer_role: str,
    producer_code_sha256: str,
    producer_config_sha256: str,
    ttl_policy: str,
    mutable_ttl_seconds: int | None,
    receipt_ttl_seconds: int,
    archive_ttl_seconds: int,
) -> dict[str, Any]:
    publication_clock = _parse_clock(publication_available_at)
    publication_ms = int(publication_clock.timestamp() * 1000)
    if artifact.max_available_at > publication_ms:
        _invalid("closed_window_publication_precedes_source_availability")
    first = artifact.rows[0]
    latest = artifact.rows[-1]
    unsigned: dict[str, Any] = {
        "schema_version": CLOSED_WINDOW_PUBLICATION_RECEIPT_SCHEMA_VERSION,
        "evidence_classification": CLOSED_WINDOW_PUBLICATION_EVIDENCE_CLASSIFICATION,
        "downstream_status": CLOSED_WINDOW_PUBLICATION_DOWNSTREAM_STATUS,
        "revision_id": revision_id,
        "canonical_redis_key": canonical_key,
        "archive_key": archive_key,
        "receipt_key": receipt_key,
        "latest_receipt_pointer_key": pointer_key,
        "exchange": artifact.exchange,
        "symbol": artifact.symbol,
        "timeframe": artifact.timeframe,
        "source_payload_schema_version": artifact.schema_version,
        "exact_payload_sha256": artifact.exact_payload_sha256,
        "exact_payload_byte_count": artifact.exact_payload_byte_count,
        "row_count": artifact.row_count,
        "first_candle_id": first.candle_id,
        "first_candle_open_time": first.candle_open_time,
        "first_candle_close_time": first.candle_close_time,
        "latest_candle_id": latest.candle_id,
        "latest_candle_open_time": latest.candle_open_time,
        "latest_candle_close_time": latest.candle_close_time,
        "max_producer_event_time": artifact.latest_producer_event_time,
        "max_ingested_at": artifact.max_ingested_at,
        "max_source_available_at": artifact.max_available_at,
        "finality_validated": True,
        "producer_role": producer_role,
        "producer_code_sha256": producer_code_sha256,
        "producer_config_sha256": producer_config_sha256,
        "ttl_policy": ttl_policy,
        "mutable_ttl_seconds": mutable_ttl_seconds,
        "receipt_ttl_seconds": receipt_ttl_seconds,
        "archive_ttl_seconds": archive_ttl_seconds,
        "publication_available_at": publication_available_at,
        "publication_available_at_clock_source": (
            "REDIS_TIME_FINAL_COMMAND_AFTER_ATOMIC_ARCHIVE_AND_CANONICAL_SET"
        ),
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }
    return {**unsigned, "receipt_sha256": _stable_sha256(unsigned)}


def _duplicate_rejecting_object(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _invalid("closed_window_publication_receipt_duplicate_key")
        value[key] = item
    return value


def _parse_receipt(payload: object) -> dict[str, Any]:
    if type(payload) is not bytes:
        _invalid("closed_window_redis_client_requires_binary_responses")
    raw = payload
    if not raw or len(raw) > CLOSED_WINDOW_MAX_RECEIPT_BYTES:
        _invalid("closed_window_publication_receipt_size_invalid")
    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=lambda _value: _invalid(
                "closed_window_publication_receipt_nonfinite"
            ),
        )
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError):
        _invalid("closed_window_publication_receipt_json_invalid")
    if type(parsed) is not dict:
        _invalid("closed_window_publication_receipt_object_required")
    return cast(dict[str, Any], parsed)


def _validate_publication_receipt(
    *,
    receipt: Mapping[str, Any],
    artifact: ValidatedOHLCVClosedWindow,
    canonical_key: str,
    archive_key: str,
    receipt_key: str,
    pointer_key: str,
    revision_id: str,
    producer_role: str,
    producer_code_sha256: str,
    producer_config_sha256: str,
    ttl_policy: str,
    mutable_ttl_seconds: int | None,
    receipt_ttl_seconds: int,
    archive_ttl_seconds: int,
) -> dict[str, Any]:
    if frozenset(receipt) != _RECEIPT_FIELDS:
        _invalid("closed_window_publication_receipt_fields_invalid")
    if any(receipt.get(field_name) is not False for field_name in _AUTHORITY_FIELDS):
        _invalid("closed_window_publication_receipt_authority_invalid")
    available_at = receipt.get("publication_available_at")
    if type(available_at) is not str:
        _invalid("closed_window_publication_receipt_available_at_invalid")
    expected = _build_publication_receipt(
        artifact=artifact,
        canonical_key=canonical_key,
        archive_key=archive_key,
        receipt_key=receipt_key,
        pointer_key=pointer_key,
        revision_id=revision_id,
        publication_available_at=available_at,
        producer_role=producer_role,
        producer_code_sha256=producer_code_sha256,
        producer_config_sha256=producer_config_sha256,
        ttl_policy=ttl_policy,
        mutable_ttl_seconds=mutable_ttl_seconds,
        receipt_ttl_seconds=receipt_ttl_seconds,
        archive_ttl_seconds=archive_ttl_seconds,
    )
    if dict(receipt) != expected:
        _invalid("closed_window_publication_receipt_rederivation_mismatch")
    return expected


def _read_adoption_source_bounded(
    pipe: Any,
    *,
    key: str,
    symbol: str,
    timeframe: str,
    payload_cap: int,
) -> tuple[bytes, ValidatedOHLCVClosedWindow, int, str]:
    """Read one exact legacy window without decoding it through redis-py."""

    response = pipe.eval(_ADOPTION_BOUNDED_READ_LUA, 1, key, payload_cap)
    if type(response) is not list or len(response) != 6:
        _invalid("closed_window_adoption_bounded_read_response_invalid")
    redis_type = _redis_type(response[0])
    previous_pttl_ms = _validated_pttl(response[1], redis_type=redis_type)
    byte_count = response[2]
    payload_response = response[3]
    source_observed_at = _redis_clock(response[4], response[5])
    if type(byte_count) is not int or not 0 <= byte_count <= _MAX_SIGNED_64:
        _invalid("closed_window_adoption_payload_size_response_invalid")
    if redis_type == "none":
        if byte_count != 0 or payload_response is not None:
            _invalid("closed_window_adoption_missing_key_read_inconsistent")
        _invalid("closed_window_adoption_source_missing")
    if redis_type != "string":
        _invalid("closed_window_adoption_source_type_invalid")
    if byte_count == 0 or byte_count > payload_cap:
        _invalid("closed_window_adoption_payload_size_invalid")
    payload = _exact_payload_bytes(
        payload_response,
        expected_byte_count=byte_count,
    )
    artifact = _validated_schema_artifact(
        payload,
        symbol=symbol,
        timeframe=timeframe,
        error_prefix="adoption_source",
    )
    observed_ms = int(_parse_clock(source_observed_at).timestamp() * 1000)
    expected_latest_close = (
        observed_ms // TIMEFRAME_DURATION_MS[timeframe]
    ) * TIMEFRAME_DURATION_MS[timeframe] - 1
    if (
        artifact.max_available_at > observed_ms
        or artifact.latest_economic_close_time > observed_ms
    ):
        _invalid("closed_window_adoption_source_not_yet_available")
    if artifact.latest_economic_close_time != expected_latest_close:
        _invalid("closed_window_adoption_source_latest_finalized_close_missing")
    return payload, artifact, previous_pttl_ms, source_observed_at


def _read_latest_pointer_bounded(pipe: Any, *, pointer_key: str) -> str | None:
    response = pipe.eval(
        _BOUNDED_READ_LUA,
        1,
        pointer_key,
        len("v2_ohlcv_closed_") + 64,
    )
    if type(response) is not list or len(response) != 4:
        _invalid("closed_window_adoption_pointer_read_response_invalid")
    redis_type = _redis_type(response[0])
    _validated_pttl(response[1], redis_type=redis_type)
    byte_count = response[2]
    raw = response[3]
    if type(byte_count) is not int or not 0 <= byte_count <= _MAX_SIGNED_64:
        _invalid("closed_window_adoption_pointer_size_response_invalid")
    if redis_type == "none":
        if byte_count != 0 or raw is not None:
            _invalid("closed_window_adoption_missing_pointer_read_inconsistent")
        return None
    if redis_type != "string":
        _invalid("closed_window_adoption_pointer_type_invalid")
    if byte_count != len("v2_ohlcv_closed_") + 64:
        _invalid("closed_window_adoption_pointer_size_invalid")
    pointer_raw = _exact_payload_bytes(raw, expected_byte_count=byte_count)
    try:
        revision_id = pointer_raw.decode("ascii", errors="strict")
    except UnicodeDecodeError:
        _invalid("closed_window_adoption_pointer_invalid")
    if _REVISION_ID_RE.fullmatch(revision_id) is None:
        _invalid("closed_window_adoption_pointer_invalid")
    return revision_id


def _rederive_existing_publication_receipt(
    *,
    receipt: Mapping[str, Any],
    artifact: ValidatedOHLCVClosedWindow,
    canonical_key: str,
    archive_key: str,
    receipt_key: str,
    pointer_key: str,
    revision_id: str,
) -> tuple[dict[str, Any], str]:
    """Fully rederive a Redis receipt; its own fields are never trusted alone."""

    if frozenset(receipt) != _RECEIPT_FIELDS:
        _invalid("closed_window_publication_receipt_fields_invalid")
    producer_role = _validated_producer_role(receipt.get("producer_role"))
    if producer_role not in _KNOWN_PUBLICATION_ROLES:
        _invalid("closed_window_publication_receipt_producer_role_unrecognized")
    producer_code_sha256 = _validated_sha256(
        receipt.get("producer_code_sha256"),
        field_name="producer_code_sha256",
    )
    producer_config_sha256 = _validated_sha256(
        receipt.get("producer_config_sha256"),
        field_name="producer_config_sha256",
    )
    ttl_policy, mutable_ttl_seconds = _validated_ttl_policy(
        receipt.get("ttl_policy"),
        receipt.get("mutable_ttl_seconds"),
    )
    receipt_ttl_seconds, archive_ttl_seconds = _validated_publication_ttls(
        ttl_policy=ttl_policy,
        mutable_ttl_seconds=mutable_ttl_seconds,
        receipt_ttl_seconds=receipt.get("receipt_ttl_seconds"),
        archive_ttl_seconds=receipt.get("archive_ttl_seconds"),
    )
    rederived_revision_id = _publication_revision_id(
        canonical_key=canonical_key,
        payload_sha256=artifact.exact_payload_sha256,
        payload_byte_count=artifact.exact_payload_byte_count,
        producer_role=producer_role,
        producer_code_sha256=producer_code_sha256,
        producer_config_sha256=producer_config_sha256,
        ttl_policy=ttl_policy,
        mutable_ttl_seconds=mutable_ttl_seconds,
        receipt_ttl_seconds=receipt_ttl_seconds,
        archive_ttl_seconds=archive_ttl_seconds,
    )
    if rederived_revision_id != revision_id:
        _invalid("closed_window_publication_receipt_revision_rederivation_mismatch")
    return (
        _validate_publication_receipt(
            receipt=receipt,
            artifact=artifact,
            canonical_key=canonical_key,
            archive_key=archive_key,
            receipt_key=receipt_key,
            pointer_key=pointer_key,
            revision_id=revision_id,
            producer_role=producer_role,
            producer_code_sha256=producer_code_sha256,
            producer_config_sha256=producer_config_sha256,
            ttl_policy=ttl_policy,
            mutable_ttl_seconds=mutable_ttl_seconds,
            receipt_ttl_seconds=receipt_ttl_seconds,
            archive_ttl_seconds=archive_ttl_seconds,
        ),
        producer_role,
    )


def _reopen_existing_publication(
    client: object,
    *,
    canonical_key: str,
    payload: bytes,
    artifact: ValidatedOHLCVClosedWindow,
    symbol: str,
    timeframe: str,
    revision_id: str,
    payload_cap: int,
) -> tuple[dict[str, Any], str, str]:
    archive_key, receipt_key, pointer_key = _publication_keys(
        revision_id=revision_id,
        symbol=symbol,
        timeframe=timeframe,
    )
    reopened = _publication_response(
        _redis_eval(
            client,
            _REOPEN_PUBLICATION_LUA,
            (canonical_key, archive_key, receipt_key, pointer_key),
            (
                payload,
                revision_id,
                payload_cap,
                CLOSED_WINDOW_MAX_RECEIPT_BYTES,
            ),
        ),
        expected_size=9,
        expected_statuses=("REOPENED",),
    )
    reopened_payload = _exact_payload_bytes(
        reopened[1],
        expected_byte_count=artifact.exact_payload_byte_count,
    )
    if reopened_payload != payload:
        _invalid("closed_window_adoption_archive_reopen_mismatch")
    reopened_artifact = _validated_schema_artifact(
        reopened_payload,
        symbol=symbol,
        timeframe=timeframe,
        error_prefix="adoption_reopened",
    )
    if reopened_artifact != artifact:
        _invalid("closed_window_adoption_artifact_reopen_mismatch")
    receipt, producer_role = _rederive_existing_publication_receipt(
        receipt=_parse_receipt(reopened[2]),
        artifact=reopened_artifact,
        canonical_key=canonical_key,
        archive_key=archive_key,
        receipt_key=receipt_key,
        pointer_key=pointer_key,
        revision_id=revision_id,
    )
    if _response_text(reopened[3]) != revision_id:
        _invalid("closed_window_adoption_pointer_reopen_mismatch")
    for value in reopened[4:7]:
        if type(value) is not int or value <= 0:
            _invalid("closed_window_adoption_ttl_response_invalid")
    if reopened[4] <= reopened[5] or reopened[4] <= reopened[6]:
        _invalid("closed_window_adoption_ttl_order_invalid")
    reopened_at = _redis_clock(reopened[7], reopened[8])
    if _parse_clock(receipt["publication_available_at"]) > _parse_clock(reopened_at):
        _invalid("closed_window_adoption_receipt_from_future")
    return receipt, producer_role, reopened_at


def _read_existing_bounded(
    pipe: Any,
    *,
    key: str,
    symbol: str,
    timeframe: str,
    replace_invalid_existing: bool,
) -> tuple[list[dict[str, Any]], bool, int]:
    """Atomically inspect metadata and fetch at most one bounded exact value."""

    response = pipe.eval(
        _BOUNDED_READ_LUA,
        1,
        key,
        CLOSED_WINDOW_MAX_PAYLOAD_BYTES,
    )
    if type(response) is not list or len(response) != 4:
        _invalid("closed_window_bounded_read_response_invalid")
    redis_type = _redis_type(response[0])
    previous_pttl_ms = _validated_pttl(response[1], redis_type=redis_type)
    byte_count = response[2]
    payload_response = response[3]
    if type(byte_count) is not int or not 0 <= byte_count <= _MAX_SIGNED_64:
        _invalid("closed_window_existing_payload_size_response_invalid")
    if redis_type == "none":
        if byte_count != 0 or payload_response is not None:
            _invalid("closed_window_missing_key_bounded_read_inconsistent")
        return [], False, previous_pttl_ms
    if redis_type != "string":
        if byte_count != 0 or payload_response is not None:
            _invalid("closed_window_nonstring_bounded_read_inconsistent")
        if replace_invalid_existing:
            return [], True, previous_pttl_ms
        _invalid("closed_window_existing_redis_type_not_string")

    if byte_count == 0:
        if payload_response != b"":
            _invalid("closed_window_empty_bounded_read_inconsistent")
        if replace_invalid_existing:
            return [], True, previous_pttl_ms
        _invalid("closed_window_existing_payload_size_invalid")
    if byte_count > CLOSED_WINDOW_MAX_PAYLOAD_BYTES:
        if payload_response is not None:
            _invalid("closed_window_oversized_bounded_read_inconsistent")
        if replace_invalid_existing:
            return [], True, previous_pttl_ms
        _invalid("closed_window_existing_payload_size_invalid")

    payload = _exact_payload_bytes(
        payload_response,
        expected_byte_count=byte_count,
    )
    try:
        rows = _validated_schema_rows(
            payload,
            symbol=symbol,
            timeframe=timeframe,
            error_prefix="existing",
        )
    except ClosedWindowRedisStoreError:
        if replace_invalid_existing:
            return [], True, previous_pttl_ms
        raise
    return rows, False, previous_pttl_ms


def _row_identity(row: dict[str, Any], *, field_name: str) -> tuple[str, int]:
    candle_id = row.get("candle_id")
    candle_open_time = row.get("candle_open_time")
    candle_close_time = row.get("candle_close_time")
    if (
        type(candle_id) is not str
        or _CANDLE_ID_RE.fullmatch(candle_id) is None
        or type(candle_open_time) is not int
        or not 0 <= candle_open_time <= _MAX_SIGNED_64
        or type(candle_close_time) is not int
        or not candle_open_time < candle_close_time <= _MAX_SIGNED_64
    ):
        _invalid(f"closed_window_{field_name}_identity_invalid")
    return candle_id, candle_open_time


def _exact_row_json(row: dict[str, Any]) -> str:
    encoded = _try_encode_rows((row,), payload_cap=CLOSED_WINDOW_MAX_PAYLOAD_BYTES)
    if encoded is None:
        _invalid("closed_window_row_payload_size_invalid")
    return encoded[0]


def _is_same_source_fact_reobservation(
    incumbent: dict[str, Any],
    candidate: dict[str, Any],
) -> bool:
    """Recognize a later receipt of the exact same producer payload.

    ``ingested_at`` and ``available_at`` are local observation clocks. Binance
    can replay an identical finalized packet after reconnect, so those clocks
    may differ even though the producer event, raw payload, candle identity,
    and economic values are byte-for-byte identical. Retaining the incumbent
    preserves the first observed point-in-time fact. Any other difference is a
    conflicting revision and remains fail-closed.
    """

    local_clock_fields = ("ingested_at", "available_at")
    for field_name in local_clock_fields:
        incumbent_clock = incumbent.get(field_name)
        candidate_clock = candidate.get(field_name)
        if (
            type(incumbent_clock) is not int
            or type(candidate_clock) is not int
            or incumbent_clock < 0
            or candidate_clock < 0
        ):
            return False
    incumbent_source_fact = dict(incumbent)
    candidate_source_fact = dict(candidate)
    for field_name in local_clock_fields:
        incumbent_source_fact.pop(field_name, None)
        candidate_source_fact.pop(field_name, None)
    return _exact_row_json(incumbent_source_fact) == _exact_row_json(candidate_source_fact)


def merge_closed_window_rows(
    existing_rows: object,
    new_rows: object,
    *,
    row_limit: object = CLOSED_WINDOW_MAX_ROWS,
) -> tuple[list[dict[str, Any]], int]:
    """Pure merge that rejects ambiguous candle-ID/open-time replacements."""

    limit = _exact_int(
        row_limit,
        field_name="row_limit",
        minimum=1,
        maximum=CLOSED_WINDOW_MAX_ROWS,
    )
    existing = _snapshot_rows(
        existing_rows,
        field_name="existing_rows",
        maximum=CLOSED_WINDOW_MAX_ROWS,
        allow_empty=True,
    )
    additions = _snapshot_rows(
        new_rows,
        field_name="new_rows",
        maximum=CLOSED_WINDOW_MAX_NEW_ROWS_PER_WRITE,
        allow_empty=False,
    )

    merged: list[dict[str, Any]] = []
    by_id: dict[str, tuple[dict[str, Any], str]] = {}
    by_open: dict[int, tuple[dict[str, Any], str]] = {}
    deduplicated = 0
    for field_name, rows in (("existing_row", existing), ("new_row", additions)):
        for row in rows:
            candle_id, candle_open_time = _row_identity(row, field_name=field_name)
            row_json = _exact_row_json(row)
            id_match = by_id.get(candle_id)
            open_match = by_open.get(candle_open_time)
            if id_match is not None or open_match is not None:
                incumbent = id_match if id_match is not None else open_match
                if (
                    id_match is not open_match
                    or incumbent is None
                    or (
                        incumbent[1] != row_json
                        and not _is_same_source_fact_reobservation(
                            incumbent[0],
                            row,
                        )
                    )
                ):
                    _invalid("closed_window_conflicting_candle_identity")
                deduplicated += 1
                continue
            record = (row, row_json)
            by_id[candle_id] = record
            by_open[candle_open_time] = record
            merged.append(row)

    merged.sort(key=lambda row: cast(int, row["candle_open_time"]))
    trimmed_for_limit = max(0, len(merged) - limit)
    if trimmed_for_limit:
        merged = merged[trimmed_for_limit:]
    return merged, deduplicated + trimmed_for_limit


def _validate_submitted_rows(
    rows: tuple[dict[str, Any], ...],
    *,
    symbol: str,
    timeframe: str,
) -> None:
    encoded = _try_encode_rows(rows, payload_cap=CLOSED_WINDOW_MAX_PAYLOAD_BYTES)
    if encoded is None:
        _invalid("closed_window_submitted_payload_size_invalid")
    _validated_schema_rows(
        encoded[0].encode("ascii"),
        symbol=symbol,
        timeframe=timeframe,
        error_prefix="submitted",
    )


def atomic_merge_closed_window(
    client: object,
    *,
    redis_key: object,
    new_rows: object,
    producer_role: object = None,
    producer_code_sha256: object = None,
    producer_config_sha256: object = None,
    receipt_ttl_seconds: object = None,
    archive_ttl_seconds: object = None,
    row_limit: object = CLOSED_WINDOW_MAX_ROWS,
    max_payload_bytes: object = CLOSED_WINDOW_MAX_PAYLOAD_BYTES,
    minimum_rows_to_preserve: object = 1,
    ttl_policy: object = "preserve",
    ttl_seconds: object = None,
    max_retries: object = 8,
    replace_invalid_existing: object = False,
) -> ClosedWindowRedisWriteResult:
    """Merge, publish, receipt, and reopen one exact closed-window revision."""

    key, _exchange, symbol, timeframe = _validated_key(redis_key)
    limit = _exact_int(
        row_limit,
        field_name="row_limit",
        minimum=1,
        maximum=CLOSED_WINDOW_MAX_ROWS,
    )
    payload_cap = _exact_int(
        max_payload_bytes,
        field_name="max_payload_bytes",
        minimum=2,
        maximum=CLOSED_WINDOW_MAX_PAYLOAD_BYTES,
    )
    retries = _exact_int(
        max_retries,
        field_name="max_retries",
        minimum=1,
        maximum=CLOSED_WINDOW_MAX_WRITE_RETRIES,
    )
    resolved_ttl_policy, ttl = _validated_ttl_policy(ttl_policy, ttl_seconds)
    resolved_receipt_ttl, resolved_archive_ttl = _validated_publication_ttls(
        ttl_policy=resolved_ttl_policy,
        mutable_ttl_seconds=ttl,
        receipt_ttl_seconds=receipt_ttl_seconds,
        archive_ttl_seconds=archive_ttl_seconds,
    )
    resolved_producer_role = _validated_producer_role(producer_role)
    resolved_producer_code_sha256 = _validated_sha256(
        producer_code_sha256,
        field_name="producer_code_sha256",
    )
    resolved_producer_config_sha256 = _validated_sha256(
        producer_config_sha256,
        field_name="producer_config_sha256",
    )
    if type(replace_invalid_existing) is not bool:
        _invalid("closed_window_replace_invalid_existing_invalid")
    additions = _snapshot_rows(
        new_rows,
        field_name="new_rows",
        maximum=CLOSED_WINDOW_MAX_NEW_ROWS_PER_WRITE,
        allow_empty=False,
    )
    _validate_submitted_rows(
        additions,
        symbol=symbol,
        timeframe=timeframe,
    )
    if (
        client is None
        or not callable(getattr(client, "pipeline", None))
        or not callable(getattr(client, "eval", None))
    ):
        _invalid("closed_window_redis_client_invalid")

    for attempt in range(1, retries + 1):
        pipe: Any = None
        try:
            pipe = cast(Any, client).pipeline(transaction=True)
            pipe.watch(key)
            existing, invalid_replaced, previous_pttl_ms = _read_existing_bounded(
                pipe,
                key=key,
                symbol=symbol,
                timeframe=timeframe,
                replace_invalid_existing=replace_invalid_existing,
            )
            merged, rows_deduplicated_or_trimmed = merge_closed_window_rows(
                existing,
                additions,
                row_limit=limit,
            )
            bounded = serialize_bounded_closed_window(
                merged,
                max_payload_bytes=payload_cap,
                minimum_rows_to_preserve=minimum_rows_to_preserve,
            )
            payload_raw = bounded.payload_json.encode("ascii")
            artifact = _validated_schema_artifact(
                payload_raw,
                symbol=symbol,
                timeframe=timeframe,
                error_prefix="merged",
            )

            revision_id = _publication_revision_id(
                canonical_key=key,
                payload_sha256=bounded.payload_sha256,
                payload_byte_count=bounded.payload_byte_count,
                producer_role=resolved_producer_role,
                producer_code_sha256=resolved_producer_code_sha256,
                producer_config_sha256=resolved_producer_config_sha256,
                ttl_policy=resolved_ttl_policy,
                mutable_ttl_seconds=ttl,
                receipt_ttl_seconds=resolved_receipt_ttl,
                archive_ttl_seconds=resolved_archive_ttl,
            )
            archive_key, receipt_key, pointer_key = _publication_keys(
                revision_id=revision_id,
                symbol=symbol,
                timeframe=timeframe,
            )

            pipe.multi()
            pipe.eval(
                _PREPARE_PUBLICATION_LUA,
                3,
                key,
                archive_key,
                receipt_key,
                payload_raw,
                resolved_archive_ttl,
                resolved_receipt_ttl,
                ttl or 0,
                resolved_ttl_policy,
                payload_cap,
                CLOSED_WINDOW_MAX_RECEIPT_BYTES,
            )
            outcome = pipe.execute()
            if type(outcome) is not list or len(outcome) != 1:
                _invalid("closed_window_redis_commit_not_acknowledged")
            prepared = _publication_response(
                outcome[0],
                expected_size=4,
                expected_statuses=("PREPARED", "IDEMPOTENT_PREPARED"),
            )
            prepare_status = _response_text(prepared[0])
            prepare_observed_at = _redis_clock(prepared[1], prepared[2])

            if prepare_status == "PREPARED":
                if prepared[3] is not None:
                    _invalid("closed_window_publication_prepare_response_invalid")
                publication_available_at = prepare_observed_at
                receipt = _build_publication_receipt(
                    artifact=artifact,
                    canonical_key=key,
                    archive_key=archive_key,
                    receipt_key=receipt_key,
                    pointer_key=pointer_key,
                    revision_id=revision_id,
                    publication_available_at=publication_available_at,
                    producer_role=resolved_producer_role,
                    producer_code_sha256=resolved_producer_code_sha256,
                    producer_config_sha256=resolved_producer_config_sha256,
                    ttl_policy=resolved_ttl_policy,
                    mutable_ttl_seconds=ttl,
                    receipt_ttl_seconds=resolved_receipt_ttl,
                    archive_ttl_seconds=resolved_archive_ttl,
                )
            else:
                receipt = _parse_receipt(prepared[3])
                receipt = _validate_publication_receipt(
                    receipt=receipt,
                    artifact=artifact,
                    canonical_key=key,
                    archive_key=archive_key,
                    receipt_key=receipt_key,
                    pointer_key=pointer_key,
                    revision_id=revision_id,
                    producer_role=resolved_producer_role,
                    producer_code_sha256=resolved_producer_code_sha256,
                    producer_config_sha256=resolved_producer_config_sha256,
                    ttl_policy=resolved_ttl_policy,
                    mutable_ttl_seconds=ttl,
                    receipt_ttl_seconds=resolved_receipt_ttl,
                    archive_ttl_seconds=resolved_archive_ttl,
                )
                publication_available_at = cast(
                    str,
                    receipt["publication_available_at"],
                )
            receipt_raw = _canonical_json_bytes(
                receipt,
                maximum=CLOSED_WINDOW_MAX_RECEIPT_BYTES,
            )

            committed = _publication_response(
                _redis_eval(
                    client,
                    _COMMIT_PUBLICATION_RECEIPT_LUA,
                    (key, archive_key, receipt_key, pointer_key),
                    (
                        payload_raw,
                        receipt_raw,
                        revision_id,
                        resolved_receipt_ttl,
                        payload_cap,
                        CLOSED_WINDOW_MAX_RECEIPT_BYTES,
                    ),
                ),
                expected_size=4,
                expected_statuses=("COMMITTED", "IDEMPOTENT", "ADOPTED"),
            )
            receipt_postcommit_at = _redis_clock(committed[1], committed[2])
            committed_receipt = _validate_publication_receipt(
                receipt=_parse_receipt(committed[3]),
                artifact=artifact,
                canonical_key=key,
                archive_key=archive_key,
                receipt_key=receipt_key,
                pointer_key=pointer_key,
                revision_id=revision_id,
                producer_role=resolved_producer_role,
                producer_code_sha256=resolved_producer_code_sha256,
                producer_config_sha256=resolved_producer_config_sha256,
                ttl_policy=resolved_ttl_policy,
                mutable_ttl_seconds=ttl,
                receipt_ttl_seconds=resolved_receipt_ttl,
                archive_ttl_seconds=resolved_archive_ttl,
            )
            receipt = committed_receipt
            publication_available_at = cast(
                str,
                receipt["publication_available_at"],
            )

            reopened = _publication_response(
                _redis_eval(
                    client,
                    _REOPEN_PUBLICATION_LUA,
                    (key, archive_key, receipt_key, pointer_key),
                    (
                        payload_raw,
                        revision_id,
                        payload_cap,
                        CLOSED_WINDOW_MAX_RECEIPT_BYTES,
                    ),
                ),
                expected_size=9,
                expected_statuses=("REOPENED",),
            )
            reopened_payload = _exact_payload_bytes(
                reopened[1],
                expected_byte_count=bounded.payload_byte_count,
            )
            if reopened_payload != payload_raw:
                _invalid("closed_window_publication_archive_reopen_mismatch")
            reopened_artifact = _validated_schema_artifact(
                reopened_payload,
                symbol=symbol,
                timeframe=timeframe,
                error_prefix="reopened",
            )
            if reopened_artifact != artifact:
                _invalid("closed_window_publication_artifact_reopen_mismatch")
            reopened_receipt = _parse_receipt(reopened[2])
            validated_receipt = _validate_publication_receipt(
                receipt=reopened_receipt,
                artifact=reopened_artifact,
                canonical_key=key,
                archive_key=archive_key,
                receipt_key=receipt_key,
                pointer_key=pointer_key,
                revision_id=revision_id,
                producer_role=resolved_producer_role,
                producer_code_sha256=resolved_producer_code_sha256,
                producer_config_sha256=resolved_producer_config_sha256,
                ttl_policy=resolved_ttl_policy,
                mutable_ttl_seconds=ttl,
                receipt_ttl_seconds=resolved_receipt_ttl,
                archive_ttl_seconds=resolved_archive_ttl,
            )
            if validated_receipt != receipt:
                _invalid("closed_window_publication_receipt_reopen_mismatch")
            if _response_text(reopened[3]) != revision_id:
                _invalid("closed_window_publication_pointer_reopen_mismatch")
            for value in reopened[4:7]:
                if type(value) is not int or value <= 0:
                    _invalid("closed_window_publication_ttl_response_invalid")
            if reopened[4] <= reopened[5] or reopened[4] <= reopened[6]:
                _invalid("closed_window_publication_ttl_order_invalid")
            consumer_reopened_at = _redis_clock(reopened[7], reopened[8])

            available_clock = _parse_clock(publication_available_at)
            invocation_prepare_clock = _parse_clock(prepare_observed_at)
            commit_clock = _parse_clock(receipt_postcommit_at)
            reopen_clock = _parse_clock(consumer_reopened_at)
            if (
                not available_clock <= commit_clock <= reopen_clock
                or invocation_prepare_clock > commit_clock
            ):
                _invalid("closed_window_publication_clock_order_invalid")

            result = ClosedWindowRedisWriteResult(
                redis_key=key,
                attempts=attempt,
                existing_row_count=len(existing),
                submitted_row_count=len(additions),
                stored_row_count=bounded.row_count,
                rows_deduplicated_or_trimmed_for_row_limit=(rows_deduplicated_or_trimmed),
                rows_trimmed_for_bytes=bounded.rows_trimmed_for_bytes,
                payload_sha256=bounded.payload_sha256,
                payload_byte_count=bounded.payload_byte_count,
                ttl_policy=resolved_ttl_policy,
                ttl_seconds=ttl,
                previous_pttl_ms=previous_pttl_ms,
                invalid_existing_replaced=invalid_replaced,
                revision_id=revision_id,
                archive_key=archive_key,
                receipt_key=receipt_key,
                latest_receipt_pointer_key=pointer_key,
                publication_available_at=publication_available_at,
                prepare_observed_at=publication_available_at,
                receipt_postcommit_observed_at=receipt_postcommit_at,
                consumer_reopened_at=consumer_reopened_at,
                receipt_sha256=cast(str, receipt["receipt_sha256"]),
                producer_role=resolved_producer_role,
                producer_code_sha256=resolved_producer_code_sha256,
                producer_config_sha256=resolved_producer_config_sha256,
                receipt_ttl_seconds=resolved_receipt_ttl,
                archive_ttl_seconds=resolved_archive_ttl,
                receipt=validated_receipt,
            )
            object.__setattr__(result, "immutable_cas_captured", True)
            object.__setattr__(result, "publication_receipt_verified", True)
            return result
        except (redis.WatchError, _ClosedWindowConcurrentMutation):
            if attempt >= retries:
                _invalid("closed_window_concurrent_write_retry_exhausted")
        except ClosedWindowRedisStoreError:
            raise
        except Exception as exc:
            raise ClosedWindowRedisStoreError(
                f"closed_window_redis_operation_failed:{type(exc).__name__}"
            ) from exc
        finally:
            if pipe is not None:
                with suppress(Exception):
                    pipe.reset()
    _invalid("closed_window_concurrent_write_retry_exhausted")


def adopt_existing_closed_window_publication(
    client: object,
    *,
    redis_key: object,
    adopter_code_sha256: object,
    adopter_config_sha256: object,
    max_payload_bytes: object = CLOSED_WINDOW_MAX_PAYLOAD_BYTES,
    max_retries: object = 8,
) -> ClosedWindowRedisAdoptionResult:
    """Receipt exact existing bytes without asserting their legacy origin.

    The compatibility key and latest pointer are watched together. A valid
    current WSS, REST, or prior adopter receipt is atomically reopened and
    retained. Only a missing pointer permits adoption, and the adoption commit
    independently refuses a pointer that appears after PREPARE.
    """

    key, _exchange, symbol, timeframe = _validated_key(redis_key)
    payload_cap = _exact_int(
        max_payload_bytes,
        field_name="max_payload_bytes",
        minimum=2,
        maximum=CLOSED_WINDOW_MAX_PAYLOAD_BYTES,
    )
    retries = _exact_int(
        max_retries,
        field_name="max_retries",
        minimum=1,
        maximum=CLOSED_WINDOW_MAX_WRITE_RETRIES,
    )
    code_sha256 = _validated_sha256(
        adopter_code_sha256,
        field_name="producer_code_sha256",
    )
    config_sha256 = _validated_sha256(
        adopter_config_sha256,
        field_name="producer_config_sha256",
    )
    receipt_ttl_seconds, archive_ttl_seconds = (
        cadence_bounded_publication_ttls(timeframe)
    )
    if (
        client is None
        or not callable(getattr(client, "pipeline", None))
        or not callable(getattr(client, "eval", None))
    ):
        _invalid("closed_window_redis_client_invalid")
    pointer_key = (
        f"{CLOSED_WINDOW_RECEIPT_LATEST_KEY_PREFIX}binance:{symbol}:{timeframe}"
    )

    for attempt in range(1, retries + 1):
        pipe: Any = None
        try:
            pipe = cast(Any, client).pipeline(transaction=True)
            pipe.watch(key, pointer_key)
            (
                payload,
                artifact,
                previous_pttl_ms,
                _source_observed_at,
            ) = _read_adoption_source_bounded(
                pipe,
                key=key,
                symbol=symbol,
                timeframe=timeframe,
                payload_cap=payload_cap,
            )
            existing_revision_id = _read_latest_pointer_bounded(
                pipe,
                pointer_key=pointer_key,
            )
            if existing_revision_id is not None:
                receipt, producer_role, _reopened_at = (
                    _reopen_existing_publication(
                        client,
                        canonical_key=key,
                        payload=payload,
                        artifact=artifact,
                        symbol=symbol,
                        timeframe=timeframe,
                        revision_id=existing_revision_id,
                        payload_cap=payload_cap,
                    )
                )
                archive_key, receipt_key, exact_pointer_key = _publication_keys(
                    revision_id=existing_revision_id,
                    symbol=symbol,
                    timeframe=timeframe,
                )
                return ClosedWindowRedisAdoptionResult(
                    redis_key=key,
                    status="ALREADY_RECEIPTED",
                    attempts=attempt,
                    row_count=artifact.row_count,
                    payload_sha256=artifact.exact_payload_sha256,
                    payload_byte_count=artifact.exact_payload_byte_count,
                    previous_pttl_ms=previous_pttl_ms,
                    revision_id=existing_revision_id,
                    archive_key=archive_key,
                    receipt_key=receipt_key,
                    latest_receipt_pointer_key=exact_pointer_key,
                    producer_role=producer_role,
                    receipt=receipt,
                )

            revision_id = _publication_revision_id(
                canonical_key=key,
                payload_sha256=artifact.exact_payload_sha256,
                payload_byte_count=artifact.exact_payload_byte_count,
                producer_role=EXISTING_CLOSED_WINDOW_ADOPTER_ROLE,
                producer_code_sha256=code_sha256,
                producer_config_sha256=config_sha256,
                ttl_policy="preserve",
                mutable_ttl_seconds=None,
                receipt_ttl_seconds=receipt_ttl_seconds,
                archive_ttl_seconds=archive_ttl_seconds,
            )
            archive_key, receipt_key, exact_pointer_key = _publication_keys(
                revision_id=revision_id,
                symbol=symbol,
                timeframe=timeframe,
            )
            if exact_pointer_key != pointer_key:
                _invalid("closed_window_adoption_pointer_derivation_mismatch")

            pipe.multi()
            pipe.eval(
                _PREPARE_PUBLICATION_LUA,
                3,
                key,
                archive_key,
                receipt_key,
                payload,
                archive_ttl_seconds,
                receipt_ttl_seconds,
                0,
                "preserve",
                payload_cap,
                CLOSED_WINDOW_MAX_RECEIPT_BYTES,
            )
            outcome = pipe.execute()
            if type(outcome) is not list or len(outcome) != 1:
                _invalid("closed_window_adoption_prepare_not_acknowledged")
            prepared = _publication_response(
                outcome[0],
                expected_size=4,
                expected_statuses=("PREPARED", "IDEMPOTENT_PREPARED"),
            )
            prepare_status = _response_text(prepared[0])
            prepare_observed_at = _redis_clock(prepared[1], prepared[2])
            if prepare_status == "PREPARED":
                if prepared[3] is not None:
                    _invalid("closed_window_adoption_prepare_response_invalid")
                receipt = _build_publication_receipt(
                    artifact=artifact,
                    canonical_key=key,
                    archive_key=archive_key,
                    receipt_key=receipt_key,
                    pointer_key=pointer_key,
                    revision_id=revision_id,
                    publication_available_at=prepare_observed_at,
                    producer_role=EXISTING_CLOSED_WINDOW_ADOPTER_ROLE,
                    producer_code_sha256=code_sha256,
                    producer_config_sha256=config_sha256,
                    ttl_policy="preserve",
                    mutable_ttl_seconds=None,
                    receipt_ttl_seconds=receipt_ttl_seconds,
                    archive_ttl_seconds=archive_ttl_seconds,
                )
            else:
                receipt = _validate_publication_receipt(
                    receipt=_parse_receipt(prepared[3]),
                    artifact=artifact,
                    canonical_key=key,
                    archive_key=archive_key,
                    receipt_key=receipt_key,
                    pointer_key=pointer_key,
                    revision_id=revision_id,
                    producer_role=EXISTING_CLOSED_WINDOW_ADOPTER_ROLE,
                    producer_code_sha256=code_sha256,
                    producer_config_sha256=config_sha256,
                    ttl_policy="preserve",
                    mutable_ttl_seconds=None,
                    receipt_ttl_seconds=receipt_ttl_seconds,
                    archive_ttl_seconds=archive_ttl_seconds,
                )
            receipt_raw = _canonical_json_bytes(
                receipt,
                maximum=CLOSED_WINDOW_MAX_RECEIPT_BYTES,
            )
            committed = _publication_response(
                _redis_eval(
                    client,
                    _COMMIT_ADOPTED_PUBLICATION_RECEIPT_LUA,
                    (key, archive_key, receipt_key, pointer_key),
                    (
                        payload,
                        receipt_raw,
                        revision_id,
                        receipt_ttl_seconds,
                        payload_cap,
                        CLOSED_WINDOW_MAX_RECEIPT_BYTES,
                    ),
                ),
                expected_size=4,
                expected_statuses=("COMMITTED", "IDEMPOTENT"),
            )
            receipt_postcommit_at = _redis_clock(committed[1], committed[2])
            committed_receipt = _validate_publication_receipt(
                receipt=_parse_receipt(committed[3]),
                artifact=artifact,
                canonical_key=key,
                archive_key=archive_key,
                receipt_key=receipt_key,
                pointer_key=pointer_key,
                revision_id=revision_id,
                producer_role=EXISTING_CLOSED_WINDOW_ADOPTER_ROLE,
                producer_code_sha256=code_sha256,
                producer_config_sha256=config_sha256,
                ttl_policy="preserve",
                mutable_ttl_seconds=None,
                receipt_ttl_seconds=receipt_ttl_seconds,
                archive_ttl_seconds=archive_ttl_seconds,
            )
            reopened_receipt, producer_role, reopened_at = (
                _reopen_existing_publication(
                    client,
                    canonical_key=key,
                    payload=payload,
                    artifact=artifact,
                    symbol=symbol,
                    timeframe=timeframe,
                    revision_id=revision_id,
                    payload_cap=payload_cap,
                )
            )
            if (
                reopened_receipt != committed_receipt
                or producer_role != EXISTING_CLOSED_WINDOW_ADOPTER_ROLE
            ):
                _invalid("closed_window_adoption_receipt_reopen_mismatch")
            prepare_clock = _parse_clock(prepare_observed_at)
            commit_clock = _parse_clock(receipt_postcommit_at)
            reopen_clock = _parse_clock(reopened_at)
            if not prepare_clock <= commit_clock <= reopen_clock:
                _invalid("closed_window_adoption_clock_order_invalid")
            return ClosedWindowRedisAdoptionResult(
                redis_key=key,
                status="ADOPTED_EXISTING_PAYLOAD",
                attempts=attempt,
                row_count=artifact.row_count,
                payload_sha256=artifact.exact_payload_sha256,
                payload_byte_count=artifact.exact_payload_byte_count,
                previous_pttl_ms=previous_pttl_ms,
                revision_id=revision_id,
                archive_key=archive_key,
                receipt_key=receipt_key,
                latest_receipt_pointer_key=pointer_key,
                producer_role=producer_role,
                receipt=reopened_receipt,
            )
        except (redis.WatchError, _ClosedWindowConcurrentMutation):
            if attempt >= retries:
                _invalid("closed_window_adoption_concurrent_write_retry_exhausted")
        except ClosedWindowRedisStoreError:
            raise
        except Exception as exc:
            raise ClosedWindowRedisStoreError(
                f"closed_window_redis_operation_failed:{type(exc).__name__}"
            ) from exc
        finally:
            if pipe is not None:
                with suppress(Exception):
                    pipe.reset()
    _invalid("closed_window_adoption_concurrent_write_retry_exhausted")


def require_verified_closed_window_publication(
    result: object,
    *,
    expected_redis_key: object,
    expected_producer_role: object,
) -> ClosedWindowRedisWriteResult:
    """Reject legacy or mocked write acknowledgements without the exact receipt."""

    if type(result) is not ClosedWindowRedisWriteResult:
        _invalid("closed_window_verified_publication_result_invalid")
    expected_key, _exchange, _symbol, _timeframe = _validated_key(expected_redis_key)
    producer_role = _validated_producer_role(expected_producer_role)
    verified = result
    if (
        verified.redis_key != expected_key
        or verified.producer_role != producer_role
        or verified.publication_receipt_verified is not True
        or verified.immutable_cas_captured is not True
        or type(verified.receipt) is not dict
        or type(verified.revision_id) is not str
        or _REVISION_ID_RE.fullmatch(verified.revision_id) is None
        or not all(
            type(value) is str
            for value in (
                verified.archive_key,
                verified.receipt_key,
                verified.latest_receipt_pointer_key,
                verified.publication_available_at,
                verified.prepare_observed_at,
                verified.receipt_postcommit_observed_at,
                verified.consumer_reopened_at,
                verified.receipt_sha256,
            )
        )
        or any(
            value is not False
            for value in (
                verified.trainer_admission_granted,
                verified.prediction_authorized,
                verified.paper_trading_authorized,
                verified.live_execution_authorized,
            )
        )
    ):
        _invalid("closed_window_publication_receipt_required")
    return verified
