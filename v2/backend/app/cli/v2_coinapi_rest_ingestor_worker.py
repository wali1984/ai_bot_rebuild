"""V2 CoinAPI REST fallback ingestor (paper-only, V2 Redis namespace).

Ports the safe subset of legacy ``ingest/live_coinapi_rest.py`` and
``ingest/live_coinapi_v1.py``:
- keyed REST GETs to CoinAPI orderbook snapshot endpoint
- keyed REST GETs to CoinAPI V1 latest OHLCV endpoint
- bounded/rate-limited polling
- microstructure snapshot normalization
- monotonic raw OHLCV quarantine snapshots
- V2-only quarantine and status writes

No exchange orders, no leverage/margin changes, no legacy Redis keys.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from math import isclose, isfinite
from pathlib import Path
from typing import Any

from v2.backend.app.services.market_state_integrity.trust import (
    ENFORCEMENT_EPOCH,
    TRUST_PRODUCER_VERSION,
    TRUST_SCHEMA_VERSION,
)
from v2.backend.app.services.native_ingestors.coinapi_wsds import (
    PROVIDER_IDENTITY_SCHEMA_VERSION,
    datetime_epoch_ns,
    iso_utc_ns,
    parse_coinapi_symbol_id,
    parse_provider_timestamp,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

WORKER_ID = "v2_coinapi_rest_ingestor"
V2_REDIS_PREFIX = "v2:"
COINAPI_REST_BASE = "https://rest.coinapi.io:443"
MAX_REST_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REST_JSON_DEPTH = 64
MAX_REST_JSON_ITEMS = 100_000
MAX_STATE_JSON_BYTES = 32 * 1024
MAX_STATE_IDENTITY_BYTES = 64
MAX_REDIS_QUARANTINE_JSON_BYTES = MAX_REST_RESPONSE_BYTES
UTF8_COUNT_CHUNK_CHARACTERS = 64 * 1024
MIN_REST_TIMEOUT_SECONDS = 0.1
MAX_REST_TIMEOUT_SECONDS = 120.0
MIN_REST_MAX_RPS = 0.05
MAX_REST_MAX_RPS = 10.0
RUNTIME_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
OPTIONAL_SOURCE_FIELDS = {
    "optional_enrichment": True,
    "required_for_trainer_admission": False,
    "system_availability_blocking": False,
    "absence_blocks_trainer": False,
}
RAW_TRUST_BLOCK_REASONS = (
    "RAW_PROVIDER_QUARANTINE",
    "MISSING_CANONICAL_POSTCOMMIT_RECEIPT",
)
RAW_AUTHORITY_FIELD_NAMES = frozenset(
    {
        "available_at",
        "canonical_receipt_resolver_present",
        "feature_cutoff",
        "feature_eligible",
        "live_gate",
        "live_symbols",
        "market_key",
        "microfeat_payloads",
        "postcommit_receipt_present",
        "prediction_eligible",
        "quarantine_only",
        "trainer_consumable",
        *OPTIONAL_SOURCE_FIELDS,
    }
)
AUTH_LATCH_SCHEMA_VERSION = "v2_coinapi_optional_auth_backoff_v1"
AUTH_LATCH_RESET_ENV = "V2_COINAPI_AUTH_LATCH_RESET"
AUTH_BACKOFF_BASE_SECONDS = 60.0
AUTH_BACKOFF_MAX_SECONDS = 6 * 60 * 60.0
MIN_OPTIONAL_REPROBE_SECONDS = 30.0
AUTH_LATCH_KEY_PREFIX = "v2:quarantine:coinapi:rest:auth_latch:v1:"
WS_CADENCE_KEY_TEMPLATE = (
    "v2:quarantine:coinapi:wsds:cadence:v4:" "{credential_fingerprint}:{coinapi_symbol_id}:{symbol}"
)
WS_CADENCE_SCHEMA_VERSION = "v2_coinapi_wsds_authenticated_cadence_v2"

DEFAULT_SECRET_PATHS = (
    Path(".local_secrets/legacy.env"),
    Path(".local_secrets/live_credentials.env"),
    Path("v2/.env.local"),
)


def _read_secret_value(name: str) -> str:
    """Read a secret from env var first, then from local secret files.
    Mirrors the pattern used by v2_coinapi_wsds_loop so both workers can
    find the API key from the same source.
    """
    if os.getenv(name):
        return str(os.getenv(name) or "")
    for path in DEFAULT_SECRET_PATHS:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export ") :].strip()
            if key == name:
                v = value.strip().strip('"').strip("'")
                if v:
                    return v
    return ""


COINAPI_PERIOD_MAP = {
    "1m": "1MIN",
    "5m": "5MIN",
    "15m": "15MIN",
    "1h": "1HRS",
    "4h": "4HRS",
    "1d": "1DAY",
}
COINAPI_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}
DEFAULT_OHLCV_TIMEFRAMES = ("1m", "5m")
DEFAULT_OHLCV_SYMBOL_LIMIT = 3
TERMINAL_PROVIDER_HTTP_STATUSES = frozenset({401, 403})
RATE_LIMITED_HTTP_STATUS = 429
DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_coinapi_rest_ingestor/latest/"
    "v2_coinapi_rest_ingestor_status.json"
)
REST_ORDERBOOK_CONFLICT_KEY_TEMPLATE = (
    "v2:quarantine:coinapi:rest:orderbook:conflict:v4:"
    "{coinapi_symbol_id}:{symbol}:{event_ns}:{digest}"
)
REST_ORDERBOOK_FENCE_KEY_TEMPLATE = (
    "v2:quarantine:coinapi:rest:orderbook:fence:v4:{coinapi_symbol_id}:{symbol}"
)
REST_ORDERBOOK_DATA_KEY_TEMPLATE = (
    "v2:quarantine:coinapi:rest:orderbook:raw:v4:{coinapi_symbol_id}:{symbol}"
)
REST_OHLCV_FENCE_KEY_TEMPLATE = (
    "v2:quarantine:coinapi:rest:ohlcv:fence:v4:" "{coinapi_symbol_id}:{symbol}:{timeframe}"
)
REST_OHLCV_DATA_KEY_TEMPLATE = (
    "v2:quarantine:coinapi:rest:ohlcv:raw:v4:" "{coinapi_symbol_id}:{symbol}:{timeframe}"
)
REST_OHLCV_CONFLICT_KEY_TEMPLATE = (
    "v2:quarantine:coinapi:rest:ohlcv:conflict:v4:"
    "{coinapi_symbol_id}:{symbol}:{timeframe}:{event_ns}:{digest}"
)
REST_ORDERBOOK_QUARANTINE_FIELDS = frozenset(
    {
        "schema_version",
        "provider_identity_schema_version",
        "trust_schema_version",
        "enforcement_epoch",
        "producer_version",
        "symbol",
        "coinapi_symbol_id",
        "coinapi_exchange_id",
        "coinapi_market_type",
        "source",
        "quarantine_only",
        "source_event_time",
        "source_event_ts_ms",
        "source_event_ts_ns",
        "provider_received_time",
        "observed_at",
        "ingested_at",
        "generated_at",
        "generated_utc",
        "available_at",
        "time_exchange",
        "time_coinapi",
        "best_bid_px",
        "best_ask_px",
        "best_bid_sz",
        "best_ask_sz",
        "mid_px",
        "spread_bps",
        "micro_price",
        "book_bid_sum_5",
        "book_ask_sum_5",
        "imbalance_5",
        "bids_top5",
        "asks_top5",
        "postcommit_receipt_present",
        "feature_eligible",
        "trainer_consumable",
        "prediction_eligible",
        "trust_block_reasons",
        "live_gate",
        "live_symbols",
        *OPTIONAL_SOURCE_FIELDS,
    }
)
REST_OHLCV_QUARANTINE_FIELDS = frozenset(
    {
        "schema_version",
        "provider_identity_schema_version",
        "trust_schema_version",
        "enforcement_epoch",
        "producer_version",
        "symbol",
        "coinapi_symbol_id",
        "coinapi_exchange_id",
        "coinapi_market_type",
        "timeframe",
        "period_id",
        "time_period_start",
        "time_period_end",
        "time_open",
        "time_close",
        "source_event_time",
        "feature_cutoff",
        "observed_at",
        "ingested_at",
        "generated_at",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trades_count",
        "event_ts_ms",
        "event_ts_ns",
        "ingested_ts_ms",
        "updated_ts_ms",
        "source",
        "native_worker_id",
        "quarantine_only",
        "postcommit_receipt_present",
        "feature_eligible",
        "trainer_consumable",
        "prediction_eligible",
        "trust_block_reasons",
        "live_gate",
        "live_symbols",
        *OPTIONAL_SOURCE_FIELDS,
    }
)
_FENCE_COMMITTED = "COMMITTED_NEWER"
_FENCE_DUPLICATE = "DUPLICATE_NO_REFRESH"
_FENCE_OLDER = "REJECTED_OLDER_NO_REFRESH"
_FENCE_CONFLICT = "CONFLICT_QUARANTINED"
_FENCE_CONFLICT_DUPLICATE = "CONFLICT_DUPLICATE_NO_REFRESH"
_FENCE_ERROR = "REDIS_ACK_INVALID"
_AUTH_STATE_COMMITTED = "AUTH_STATE_COMMITTED_NEWER"
_AUTH_STATE_CURRENT = "AUTH_STATE_ALREADY_CURRENT"
_AUTH_STATE_OLDER = "AUTH_STATE_REJECTED_OLDER"
_AUTH_STATE_CONFLICT = "AUTH_STATE_EQUAL_REVISION_CONFLICT"
_AUTH_STATE_ERROR = "AUTH_STATE_REDIS_ACK_INVALID"
_STATE_READ_OK = "STATE_READ_OK"
_STATE_READ_MISSING = "STATE_READ_MISSING"
_STATE_READ_INVALID = "STATE_READ_INVALID"
_STATE_READ_OVERSIZED = "STATE_READ_OVERSIZED"
_STATE_READ_ERROR = "STATE_READ_ERROR"
_ATOMIC_FENCE_LUA = r"""
-- COINAPI_ATOMIC_FENCE_BOUNDED_V2
local fence_type = redis.call('TYPE', KEYS[1])['ok']
local data_type = redis.call('TYPE', KEYS[2])['ok']
local conflict_type = redis.call('TYPE', KEYS[3])['ok']
if (fence_type ~= 'none' and fence_type ~= 'hash')
   or (data_type ~= 'none' and data_type ~= 'string')
   or (conflict_type ~= 'none' and conflict_type ~= 'string') then
  return {'REDIS_ACK_INVALID', 0, -2}
end

local incoming_event = ARGV[1]
local incoming_digest = ARGV[2]
local incoming_payload = ARGV[3]
local ttl = tonumber(ARGV[4])
local identity_limit = tonumber(ARGV[5])
local payload_limit = tonumber(ARGV[6])

local function bounded_hget(key, field, limit)
  local value_length = redis.call('HSTRLEN', key, field)
  if value_length <= 0 or value_length > limit then return nil end
  local value = redis.call('HGET', key, field)
  if not value or string.len(value) ~= value_length then return nil end
  return value
end

local function bounded_get(key, limit)
  local value_length = redis.call('STRLEN', key)
  if value_length <= 0 or value_length > limit then return nil end
  local value = redis.call('GET', key)
  if not value or string.len(value) ~= value_length then return nil end
  return value
end

local function is_decimal(value)
  return value and string.match(value, '^%d+$') ~= nil
end

local function is_digest(value)
  return value and string.len(value) == 64
    and string.match(value, '^[0-9a-f]+$') ~= nil
end

if not incoming_event or not incoming_digest or not incoming_payload
   or not identity_limit or identity_limit <= 0 or identity_limit > 64
   or identity_limit ~= math.floor(identity_limit)
   or not payload_limit or payload_limit <= 0 or payload_limit > 2097152
   or payload_limit ~= math.floor(payload_limit)
   or string.len(incoming_event) <= 0 or string.len(incoming_event) > identity_limit
   or string.len(incoming_payload) <= 0 or string.len(incoming_payload) > payload_limit
   or not is_decimal(incoming_event) or not is_digest(incoming_digest)
   or not ttl or ttl <= 0 then
  return {'REDIS_ACK_INVALID', 0, -2}
end

local current_event = nil
local current_digest = nil
local current_payload = nil
local current_payload_sha1 = nil
if fence_type == 'hash' then
  current_event = bounded_hget(KEYS[1], 'event_ns', identity_limit)
  current_digest = bounded_hget(KEYS[1], 'digest', identity_limit)
  current_payload = bounded_hget(KEYS[1], 'payload', payload_limit)
  current_payload_sha1 = bounded_hget(KEYS[1], 'payload_sha1', identity_limit)
  if not current_event or not current_digest or not current_payload
     or not current_payload_sha1 then
    return {'REDIS_ACK_INVALID', 0, -2}
  end
end

local baseline_payload = nil
if data_type == 'string' then
  baseline_payload = bounded_get(KEYS[2], payload_limit)
  if not baseline_payload then return {'REDIS_ACK_INVALID', 0, -2} end
end
if (current_event and (not is_decimal(current_event) or not is_digest(current_digest)))
   or (current_event and baseline_payload and baseline_payload ~= current_payload)
   or (current_payload and redis.sha1hex(current_payload) ~= current_payload_sha1)
   or (not current_event and data_type ~= 'none') then
  return {'REDIS_ACK_INVALID', 0, -2}
end

local function decimal_compare(left, right)
  left = string.gsub(left, '^0+', '')
  right = string.gsub(right, '^0+', '')
  if left == '' then left = '0' end
  if right == '' then right = '0' end
  if string.len(left) < string.len(right) then return -1 end
  if string.len(left) > string.len(right) then return 1 end
  if left < right then return -1 end
  if left > right then return 1 end
  return 0
end

if current_event then
  local ordering = decimal_compare(incoming_event, current_event)
  if ordering < 0 then
    return {'REJECTED_OLDER_NO_REFRESH', 0, redis.call('PTTL', KEYS[2])}
  end
  if ordering == 0 then
    if current_digest == incoming_digest then
      return {'DUPLICATE_NO_REFRESH', 0, redis.call('PTTL', KEYS[2])}
    end
    local existing_conflict = nil
    if conflict_type == 'string' then
      existing_conflict = bounded_get(KEYS[3], payload_limit)
      if not existing_conflict then
        return {'REDIS_ACK_INVALID', 0, redis.call('PTTL', KEYS[2])}
      end
    end
    if existing_conflict then
      if existing_conflict == incoming_payload then
        return {'CONFLICT_DUPLICATE_NO_REFRESH', 0, redis.call('PTTL', KEYS[2])}
      end
      return {'REDIS_ACK_INVALID', 0, redis.call('PTTL', KEYS[2])}
    end
    local conflict_ack = redis.call('SET', KEYS[3], incoming_payload, 'EX', ttl, 'NX')
    if conflict_ack then
      return {'CONFLICT_QUARANTINED', 1, redis.call('PTTL', KEYS[2])}
    end
    return {'CONFLICT_DUPLICATE_NO_REFRESH', 0, redis.call('PTTL', KEYS[2])}
  end
end

redis.call(
  'HSET', KEYS[1],
  'event_ns', incoming_event,
  'digest', incoming_digest,
  'payload', incoming_payload,
  'payload_sha1', redis.sha1hex(incoming_payload)
)
redis.call('PERSIST', KEYS[1])
local data_ack = redis.call('SET', KEYS[2], incoming_payload, 'EX', ttl)
local stored_event = bounded_hget(KEYS[1], 'event_ns', identity_limit)
local stored_digest = bounded_hget(KEYS[1], 'digest', identity_limit)
local stored_fence_payload = bounded_hget(KEYS[1], 'payload', payload_limit)
local stored_payload_sha1 = bounded_hget(KEYS[1], 'payload_sha1', identity_limit)
local stored_payload = bounded_get(KEYS[2], payload_limit)
local payload_ttl = redis.call('PTTL', KEYS[2])
local fence_ttl = redis.call('TTL', KEYS[1])
local data_ack_ok = type(data_ack) == 'table' and data_ack['ok'] == 'OK'
if stored_event ~= incoming_event or stored_digest ~= incoming_digest
   or stored_fence_payload ~= incoming_payload
   or stored_payload_sha1 ~= redis.sha1hex(incoming_payload)
   or stored_payload ~= incoming_payload or not data_ack_ok
   or payload_ttl <= 0 or fence_ttl ~= -1 then
  return {'REDIS_ACK_INVALID', 0, payload_ttl}
end
return {'COMMITTED_NEWER', 1, payload_ttl}
"""
_ATOMIC_AUTH_STATE_LUA = r"""
-- COINAPI_ATOMIC_AUTH_STATE_BOUNDED_V2
local key_type = redis.call('TYPE', KEYS[1])['ok']
if key_type ~= 'none' and key_type ~= 'hash' then
  return {'AUTH_STATE_REDIS_ACK_INVALID', 0}
end

local incoming_revision = ARGV[1]
local incoming_payload = ARGV[2]
local identity_limit = tonumber(ARGV[3])
local payload_limit = tonumber(ARGV[4])

local function bounded_hget(key, field, limit)
  local value_length = redis.call('HSTRLEN', key, field)
  if value_length <= 0 or value_length > limit then return nil end
  local value = redis.call('HGET', key, field)
  if not value or string.len(value) ~= value_length then return nil end
  return value
end

local function is_decimal(value)
  return value and string.match(value, '^%d+$') ~= nil
end
local function decimal_compare(left, right)
  left = string.gsub(left, '^0+', '')
  right = string.gsub(right, '^0+', '')
  if left == '' then left = '0' end
  if right == '' then right = '0' end
  if string.len(left) < string.len(right) then return -1 end
  if string.len(left) > string.len(right) then return 1 end
  if left < right then return -1 end
  if left > right then return 1 end
  return 0
end

if not incoming_revision or not incoming_payload
   or not identity_limit or identity_limit <= 0 or identity_limit > 64
   or identity_limit ~= math.floor(identity_limit)
   or not payload_limit or payload_limit <= 0 or payload_limit > 32768
   or payload_limit ~= math.floor(payload_limit)
   or string.len(incoming_revision) <= 0
   or string.len(incoming_revision) > identity_limit
   or string.len(incoming_payload) <= 0 or string.len(incoming_payload) > payload_limit
   or not is_decimal(incoming_revision) then
  return {'AUTH_STATE_REDIS_ACK_INVALID', 0}
end

local current_revision = nil
local current_payload = nil
local current_payload_sha1 = nil
if key_type == 'hash' then
  current_revision = bounded_hget(KEYS[1], 'revision_ns', identity_limit)
  current_payload = bounded_hget(KEYS[1], 'payload', payload_limit)
  current_payload_sha1 = bounded_hget(KEYS[1], 'payload_sha1', identity_limit)
  if not current_revision or not current_payload or not current_payload_sha1 then
    return {'AUTH_STATE_REDIS_ACK_INVALID', 0}
  end
end
if (current_payload and redis.sha1hex(current_payload) ~= current_payload_sha1)
   or (current_revision and not current_payload)
   or (current_payload and not current_revision)
   or (current_revision and not is_decimal(current_revision)) then
  return {'AUTH_STATE_REDIS_ACK_INVALID', 0}
end
if current_revision then
  local ordering = decimal_compare(incoming_revision, current_revision)
  if ordering < 0 then return {'AUTH_STATE_REJECTED_OLDER', 0} end
  if ordering == 0 then
    if current_payload == incoming_payload then
      return {'AUTH_STATE_ALREADY_CURRENT', 0}
    end
    return {'AUTH_STATE_EQUAL_REVISION_CONFLICT', 0}
  end
end

redis.call(
  'HSET', KEYS[1],
  'revision_ns', incoming_revision,
  'payload', incoming_payload,
  'payload_sha1', redis.sha1hex(incoming_payload)
)
redis.call('PERSIST', KEYS[1])
local stored_revision = bounded_hget(KEYS[1], 'revision_ns', identity_limit)
local stored_payload = bounded_hget(KEYS[1], 'payload', payload_limit)
local stored_payload_sha1 = bounded_hget(KEYS[1], 'payload_sha1', identity_limit)
local stored_ttl = redis.call('TTL', KEYS[1])
if stored_revision ~= incoming_revision or stored_payload ~= incoming_payload
   or stored_payload_sha1 ~= redis.sha1hex(incoming_payload)
   or stored_ttl ~= -1 then
  return {'AUTH_STATE_REDIS_ACK_INVALID', 0}
end
return {'AUTH_STATE_COMMITTED_NEWER', 1}
"""
_BOUNDED_PERSISTENT_HASH_READ_LUA = r"""
-- COINAPI_BOUNDED_PERSISTENT_HASH_READ_V1
local key_type = redis.call('TYPE', KEYS[1])['ok']
if key_type == 'none' then
  return {'STATE_READ_MISSING', '', ''}
end
if key_type ~= 'hash' then
  return {'STATE_READ_INVALID', '', ''}
end

local ttl = redis.call('PTTL', KEYS[1])
local identity_field = ARGV[1]
local payload_field = ARGV[2]
local identity_limit = tonumber(ARGV[3])
local payload_limit = tonumber(ARGV[4])
if ttl ~= -1 or not identity_limit or identity_limit <= 0
   or not payload_limit or payload_limit <= 0 then
  return {'STATE_READ_INVALID', '', ''}
end
if redis.call('HEXISTS', KEYS[1], identity_field) ~= 1
   or redis.call('HEXISTS', KEYS[1], payload_field) ~= 1 then
  return {'STATE_READ_INVALID', '', ''}
end

local identity_length = redis.call('HSTRLEN', KEYS[1], identity_field)
local payload_length = redis.call('HSTRLEN', KEYS[1], payload_field)
if identity_length <= 0 or payload_length <= 0 then
  return {'STATE_READ_INVALID', '', ''}
end
if identity_length > identity_limit or payload_length > payload_limit then
  return {'STATE_READ_OVERSIZED', identity_length, payload_length}
end

local identity = redis.call('HGET', KEYS[1], identity_field)
local payload = redis.call('HGET', KEYS[1], payload_field)
if not identity or not payload or string.len(identity) ~= identity_length
   or string.len(payload) ~= payload_length then
  return {'STATE_READ_INVALID', '', ''}
end
return {'STATE_READ_OK', identity, payload}
"""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _observation_time(value: datetime | None) -> datetime:
    observed_at = datetime.now(UTC) if value is None else value
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return observed_at.astimezone(UTC)


def _strict_local_clocks(observed: datetime) -> tuple[datetime, datetime]:
    ingested = max(datetime.now(UTC), observed + timedelta(microseconds=1))
    generated = max(datetime.now(UTC), ingested + timedelta(microseconds=1))
    return ingested, generated


def _validated_runtime_symbol(value: Any) -> str | None:
    if type(value) is not str or value != value.strip() or not value.isascii():
        return None
    if RUNTIME_SYMBOL_RE.fullmatch(value) is None:
        return None
    return value


def _validated_exchange_id(value: Any) -> str | None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.isascii()
        or not value.isalnum()
        or value != value.upper()
    ):
        return None
    return value


def _validated_finite_range(
    value: Any,
    *,
    minimum: float,
    maximum: float,
) -> float | None:
    if isinstance(value, bool) or type(value) not in {int, float}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(parsed) or parsed < minimum or parsed > maximum:
        return None
    return parsed


def _json_shape_within_bounds(
    value: Any,
    *,
    max_depth: int,
    max_items: int,
) -> bool:
    if type(max_depth) is not int or max_depth < 0:
        return False
    if type(max_items) is not int or max_items <= 0:
        return False
    stack: list[tuple[Any, int]] = [(value, 0)]
    visited = 0
    while stack:
        current, depth = stack.pop()
        visited += 1
        if visited > max_items or depth > max_depth:
            return False
        if isinstance(current, dict):
            if any(type(key) is not str for key in current):
                return False
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
        elif type(current) is float and not isfinite(current):
            return False
    return True


def _reject_nonstandard_json_constant(value: str) -> None:
    raise ValueError(f"nonstandard JSON constant rejected: {value}")


def _utf8_length_within_limit(value: str, *, max_bytes: int) -> bool:
    if type(value) is not str or type(max_bytes) is not int or max_bytes < 0:
        return False
    if len(value) > max_bytes:
        return False
    encoded_length = 0
    for start in range(0, len(value), UTF8_COUNT_CHUNK_CHARACTERS):
        chunk = value[start : start + UTF8_COUNT_CHUNK_CHARACTERS]
        try:
            encoded_length += len(chunk.encode("utf-8"))
        except (UnicodeEncodeError, OverflowError):
            return False
        if encoded_length > max_bytes:
            return False
    return True


def _loads_bounded_json(
    raw: Any,
    *,
    max_bytes: int,
    max_depth: int,
    max_items: int,
) -> Any | None:
    if type(raw) is bytes:
        if len(raw) > max_bytes:
            return None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    elif type(raw) is str:
        if not _utf8_length_within_limit(raw, max_bytes=max_bytes):
            return None
        text = raw
    else:
        return None
    try:
        candidate = json.loads(
            text,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        TypeError,
        ValueError,
        RecursionError,
        OverflowError,
    ):
        return None
    if not _json_shape_within_bounds(
        candidate,
        max_depth=max_depth,
        max_items=max_items,
    ):
        return None
    return candidate


def _coinapi_symbol_id(symbol: str, *, exchange_id: str = "BINANCEFTS") -> str:
    validated_symbol = _validated_runtime_symbol(symbol)
    if validated_symbol is None:
        raise ValueError("symbol must exactly match uppercase [A-Z0-9]+USDT")
    validated_exchange_id = _validated_exchange_id(exchange_id)
    if validated_exchange_id is None:
        raise ValueError("exchange_id must be exact uppercase ASCII alphanumeric")
    base = validated_symbol
    if base.endswith("USDT"):
        base = base[:-4]
    market_type = "PERP" if validated_exchange_id == "BINANCEFTS" else "SPOT"
    return f"{validated_exchange_id}_{market_type}_{base}_USDT"


def _validate_rest_base_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid CoinAPI REST endpoint") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "rest.coinapi.io"
        or port != 443
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.netloc.lower() != "rest.coinapi.io:443"
    ):
        raise ValueError("CoinAPI REST endpoint is not the production allowlisted endpoint")
    return COINAPI_REST_BASE


def _read_bounded_response(response: Any) -> bytes | None:
    raw = response.read(MAX_REST_RESPONSE_BYTES + 1)
    if not isinstance(raw, bytes) or len(raw) > MAX_REST_RESPONSE_BYTES:
        return None
    return raw


def _http_get_json(
    base_url: str,
    path: str,
    *,
    api_key: str,
    params: dict[str, Any],
    timeout_seconds: float,
    opener: Any | None = None,
) -> tuple[int, Any, dict[str, int | float | str]]:
    validated_base = _validate_rest_base_url(base_url)
    validated_timeout = _validated_finite_range(
        timeout_seconds,
        minimum=MIN_REST_TIMEOUT_SECONDS,
        maximum=MAX_REST_TIMEOUT_SECONDS,
    )
    if validated_timeout is None:
        raise ValueError("CoinAPI REST timeout_seconds is outside the finite safe range")
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("CoinAPI REST path must be an absolute provider path")
    transport = opener or urllib.request.build_opener(_NoRedirectHandler())
    query = urllib.parse.urlencode(params)
    url = f"{validated_base}{path}"
    if query:
        url = f"{url}?{query}"
    req = urllib.request.Request(  # noqa: S310 -- URL scheme is allowlisted above.
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "ai-bot-v2-coinapi-rest-readonly",
            "X-CoinAPI-Key": api_key,
        },
    )
    try:
        with transport.open(
            req,
            timeout=validated_timeout,
        ) as resp:
            raw_bytes = _read_bounded_response(resp)
            if raw_bytes is None:
                return 598, None, {}
            raw = raw_bytes.decode("utf-8")
            status_value = getattr(resp, "status", None)
            if type(status_value) is not int:
                return 599, None, {}
            status = status_value
            quota_metadata = _sanitize_quota_metadata(resp.headers)
    except urllib.error.HTTPError as exc:
        quota_metadata = _sanitize_quota_metadata(exc.headers)
        try:
            raw_bytes = _read_bounded_response(exc)
            if raw_bytes is None:
                return 598, None, quota_metadata
            raw = raw_bytes.decode("utf-8")
            data = (
                _loads_bounded_json(
                    raw,
                    max_bytes=MAX_REST_RESPONSE_BYTES,
                    max_depth=MAX_REST_JSON_DEPTH,
                    max_items=MAX_REST_JSON_ITEMS,
                )
                if raw
                else None
            )
        except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
            data = None
        return exc.code if type(exc.code) is int else 599, data, quota_metadata
    except Exception:
        return 599, None, {}
    try:
        return (
            status,
            _loads_bounded_json(
                raw,
                max_bytes=MAX_REST_RESPONSE_BYTES,
                max_depth=MAX_REST_JSON_DEPTH,
                max_items=MAX_REST_JSON_ITEMS,
            )
            if raw
            else None,
            quota_metadata,
        )
    except (TypeError, ValueError, RecursionError, OverflowError):
        return status, None, quota_metadata


def _header_value(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except (AttributeError, TypeError):
        return None
    if value is None:
        return None
    return str(value).strip() or None


def _finite_nonnegative_number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(parsed) or parsed < 0:
        return None
    return int(parsed) if parsed.is_integer() else parsed


def _retry_after_seconds(
    value: str | None,
    *,
    now_epoch: float | None = None,
) -> int | float | None:
    numeric = _finite_nonnegative_number(value)
    if numeric is not None:
        return numeric
    if value is None:
        return None
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        delay = max(0.0, retry_at.timestamp() - (time.time() if now_epoch is None else now_epoch))
    except (TypeError, ValueError, OverflowError):
        return None
    return int(delay) if delay.is_integer() else delay


def _sanitize_quota_metadata(
    headers: Any,
    *,
    now_epoch: float | None = None,
) -> dict[str, int | float | str]:
    """Return only numeric provider quota/retry fields from an explicit allowlist."""

    metadata: dict[str, int | float | str] = {}
    retry_after = _retry_after_seconds(
        _header_value(headers, "Retry-After"),
        now_epoch=now_epoch,
    )
    if retry_after is not None:
        metadata["retry_after_seconds"] = retry_after
    allowed_numeric_headers = {
        "X-RateLimit-Limit": "rate_limit_limit",
        "X-RateLimit-Remaining": "rate_limit_remaining",
        "X-RateLimit-Reset": "rate_limit_reset",
        "X-RateLimit-Reset-After": "rate_limit_reset_after_seconds",
    }
    for header_name, output_name in allowed_numeric_headers.items():
        value = _finite_nonnegative_number(_header_value(headers, header_name))
        if value is not None:
            metadata[output_name] = value
    return metadata


def _provider_error_class(http_status: int, body: Any) -> str | None:
    """Classify provider rejection without returning provider-controlled text."""

    if type(http_status) is not int:
        return "INVALID_HTTP_STATUS"
    if 200 <= http_status < 300:
        return None
    if http_status == 401:
        return "AUTHENTICATION_REJECTED"
    if http_status == RATE_LIMITED_HTTP_STATUS:
        return "RATE_LIMITED"
    if http_status == 403:
        fragments: list[str] = []
        if isinstance(body, dict):
            for key in ("error", "message", "detail"):
                value = body.get(key)
                if isinstance(value, str):
                    fragments.append(value[:512].lower())
        elif isinstance(body, str):
            fragments.append(body[:512].lower())
        text = " ".join(fragments)
        if any(token in text for token in ("quota", "usage credit", "subscription")):
            return "QUOTA_OR_SUBSCRIPTION_EXHAUSTED"
        if any(token in text for token in ("entitlement", "permission", "plan")):
            return "ENTITLEMENT_REJECTED"
        return "AUTHORIZATION_REJECTED"
    if 300 <= http_status < 400:
        return "HTTP_REDIRECT_REJECTED"
    if 400 <= http_status < 500:
        return "PROVIDER_HTTP_CLIENT_ERROR"
    if http_status in {598, 599}:
        return "PROVIDER_TRANSPORT_OR_RESPONSE_ERROR"
    if 500 <= http_status < 600:
        return "PROVIDER_HTTP_SERVER_ERROR"
    return "INVALID_HTTP_STATUS"


def _provider_health(
    *,
    http_status: int,
    error_class: str,
    quota_metadata: dict[str, int | float | str],
) -> dict[str, Any]:
    rate_limited = http_status == RATE_LIMITED_HTTP_STATUS
    authorization_unavailable = http_status in TERMINAL_PROVIDER_HTTP_STATUSES
    if rate_limited:
        state = "RATE_LIMITED"
    elif authorization_unavailable:
        state = "PROVIDER_BLOCKED"
    else:
        state = "PROVIDER_HTTP_FAILURE"
    return {
        "state": state,
        "provider_error_class": error_class,
        "http_status": int(http_status),
        "terminal_for_cycle": authorization_unavailable or rate_limited,
        "authorization_unavailable": authorization_unavailable,
        "sparse_reprobe_required": authorization_unavailable or rate_limited,
        "quota_metadata": dict(quota_metadata),
        "raw_provider_body_recorded": False,
        "trainer_consumable": False,
        "typed_missing": True,
        **OPTIONAL_SOURCE_FIELDS,
    }


def _provider_retry_delay_seconds(
    quota_metadata: dict[str, Any] | None,
    *,
    now_epoch: float | None = None,
) -> float | None:
    metadata = quota_metadata or {}
    candidates: list[float] = []
    for key in ("retry_after_seconds", "rate_limit_reset_after_seconds"):
        value = _finite_nonnegative_number(str(metadata.get(key)))
        if value is not None:
            candidates.append(float(value))
    reset = _finite_nonnegative_number(str(metadata.get("rate_limit_reset")))
    if reset is not None:
        reset_value = float(reset)
        try:
            now = time.time() if now_epoch is None else float(now_epoch)
        except (TypeError, ValueError, OverflowError):
            return None
        candidates.append(max(0.0, reset_value - now))
    if not candidates:
        return None
    # Provider headers are advisory and untrusted.  Honor the longest valid
    # retry signal, but never allow one malformed value to turn the optional
    # source into an effectively permanent latch.
    return min(AUTH_BACKOFF_MAX_SECONDS, max(candidates))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        parsed = float(value)
    except Exception:
        return None
    return parsed if isfinite(parsed) else None


def _safe_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0 or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _exact_nonnegative_int(value: Any, *, positive: bool = False) -> int | None:
    if type(value) is not int or value < 0 or (positive and value == 0):
        return None
    return value


def _normalize_orderbook(
    symbol: str,
    coinapi_symbol: str,
    body: Any,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any] | None:
    if _validated_runtime_symbol(symbol) is None:
        return None
    try:
        if coinapi_symbol != _coinapi_symbol_id(
            symbol,
            exchange_id=coinapi_symbol.split("_", 1)[0],
        ):
            return None
    except (ValueError, IndexError):
        return None
    provider_identity = parse_coinapi_symbol_id(coinapi_symbol)
    if provider_identity is None or provider_identity[2] != symbol:
        return None
    coinapi_exchange_id, coinapi_market_type, _ = provider_identity
    row = body[0] if isinstance(body, list) and body else body
    if not isinstance(row, dict):
        return None
    if "symbol_id_exchange" in row:
        return None
    if type(row.get("symbol_id")) is not str or row.get("symbol_id") != coinapi_symbol:
        return None
    bids = row.get("bids") if isinstance(row.get("bids"), list) else []
    asks = row.get("asks") if isinstance(row.get("asks"), list) else []
    if not bids or not asks:
        return None

    def _price_size(item: Any) -> tuple[float | None, float | None]:
        if isinstance(item, dict):
            return _safe_float(item.get("price")), _safe_float(item.get("size"))
        if isinstance(item, list | tuple) and len(item) >= 2:
            return _safe_float(item[0]), _safe_float(item[1])
        return None, None

    parsed_bids = [_price_size(item) for item in bids[:5]]
    parsed_asks = [_price_size(item) for item in asks[:5]]
    if any(
        price is None or size is None or price <= 0 or size < 0
        for price, size in (*parsed_bids, *parsed_asks)
    ):
        return None
    bid_prices = [price for price, _ in parsed_bids if price is not None]
    ask_prices = [price for price, _ in parsed_asks if price is not None]
    if any(left < right for left, right in zip(bid_prices, bid_prices[1:], strict=False)):
        return None
    if any(left > right for left, right in zip(ask_prices, ask_prices[1:], strict=False)):
        return None
    bid_px, bid_sz = parsed_bids[0]
    ask_px, ask_sz = parsed_asks[0]
    assert bid_px is not None and bid_sz is not None
    assert ask_px is not None and ask_sz is not None
    if ask_px < bid_px:
        return None
    mid_px = (bid_px + ask_px) / 2.0
    spread_bps = ((ask_px - bid_px) / mid_px * 10_000.0) if mid_px else None
    bid_sum_5 = sum(size for _, size in parsed_bids if size is not None)
    ask_sum_5 = sum(size for _, size in parsed_asks if size is not None)
    total_5 = bid_sum_5 + ask_sum_5
    imbalance_5 = ((bid_sum_5 - ask_sum_5) / total_5) if total_5 > 0 else None
    total_top = bid_sz + ask_sz
    micro_price = ((bid_px * ask_sz) + (ask_px * bid_sz)) / total_top if total_top > 0 else None
    observed = _observation_time(observed_at)
    provider_event = parse_provider_timestamp(row.get("time_exchange"))
    provider_received = parse_provider_timestamp(row.get("time_coinapi"))
    observed_ns = datetime_epoch_ns(observed)
    if (
        provider_event is None
        or provider_received is None
        or not (provider_event[1] <= provider_received[1] <= observed_ns)
    ):
        return None
    ingested, generated = _strict_local_clocks(observed)
    source_event_time = iso_utc_ns(provider_event[1])
    provider_received_time = iso_utc_ns(provider_received[1])
    return {
        "schema_version": "v2_coinapi_rest_orderbook_quarantine_v3",
        "provider_identity_schema_version": PROVIDER_IDENTITY_SCHEMA_VERSION,
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "enforcement_epoch": ENFORCEMENT_EPOCH,
        "producer_version": TRUST_PRODUCER_VERSION,
        "symbol": symbol,
        "coinapi_symbol_id": coinapi_symbol,
        "coinapi_exchange_id": coinapi_exchange_id,
        "coinapi_market_type": coinapi_market_type,
        "source": "coinapi_rest_orderbooks3_current",
        "quarantine_only": True,
        "source_event_time": source_event_time,
        "source_event_ts_ms": provider_event[1] // 1_000_000,
        "source_event_ts_ns": provider_event[1],
        "provider_received_time": provider_received_time,
        "observed_at": _iso_utc(observed),
        "ingested_at": _iso_utc(ingested),
        "generated_at": _iso_utc(generated),
        "generated_utc": _iso_utc(generated),
        "available_at": None,
        "time_exchange": source_event_time,
        "time_coinapi": provider_received_time,
        "best_bid_px": bid_px,
        "best_ask_px": ask_px,
        "best_bid_sz": bid_sz,
        "best_ask_sz": ask_sz,
        "mid_px": mid_px,
        "spread_bps": spread_bps,
        "micro_price": micro_price,
        "book_bid_sum_5": bid_sum_5,
        "book_ask_sum_5": ask_sum_5,
        "imbalance_5": imbalance_5,
        "bids_top5": [{"price": price, "size": size} for price, size in parsed_bids],
        "asks_top5": [{"price": price, "size": size} for price, size in parsed_asks],
        "postcommit_receipt_present": False,
        "feature_eligible": False,
        "trainer_consumable": False,
        "prediction_eligible": False,
        "trust_block_reasons": list(RAW_TRUST_BLOCK_REASONS),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        **OPTIONAL_SOURCE_FIELDS,
    }


def _normalize_ohlcv(
    symbol: str,
    coinapi_symbol: str,
    timeframe: str,
    period_id: str,
    body: Any,
    *,
    observed_at: datetime | None = None,
) -> dict[str, Any] | None:
    if (
        _validated_runtime_symbol(symbol) is None
        or timeframe not in COINAPI_PERIOD_MAP
        or period_id != COINAPI_PERIOD_MAP.get(timeframe)
    ):
        return None
    try:
        if coinapi_symbol != _coinapi_symbol_id(
            symbol,
            exchange_id=coinapi_symbol.split("_", 1)[0],
        ):
            return None
    except (ValueError, IndexError):
        return None
    provider_identity = parse_coinapi_symbol_id(coinapi_symbol)
    if provider_identity is None or provider_identity[2] != symbol:
        return None
    coinapi_exchange_id, coinapi_market_type, _ = provider_identity
    row = body[0] if isinstance(body, list) and body else body
    if not isinstance(row, dict):
        return None
    if "symbol_id_exchange" in row or any(
        alias in row for alias in ("open", "high", "low", "close", "volume")
    ):
        return None
    if type(row.get("symbol_id")) is not str or row.get("symbol_id") != coinapi_symbol:
        return None
    if type(row.get("period_id")) is not str or row.get("period_id") != period_id:
        return None
    open_px = _safe_float(row.get("price_open"))
    high_px = _safe_float(row.get("price_high"))
    low_px = _safe_float(row.get("price_low"))
    close_px = _safe_float(row.get("price_close"))
    volume = _safe_float(row.get("volume_traded"))
    trades_count = _safe_int(row.get("trades_count"))
    period_start = parse_provider_timestamp(row.get("time_period_start"))
    period_end = parse_provider_timestamp(row.get("time_period_end"))
    time_open = parse_provider_timestamp(row.get("time_open"))
    time_close = parse_provider_timestamp(row.get("time_close"))
    observed = _observation_time(observed_at)
    expected_period_id = COINAPI_PERIOD_MAP.get(timeframe)
    expected_duration_seconds = COINAPI_TIMEFRAME_SECONDS.get(timeframe)
    if (
        open_px is None
        or high_px is None
        or low_px is None
        or close_px is None
        or volume is None
        or trades_count is None
        or period_start is None
        or period_end is None
        or time_open is None
        or time_close is None
        or expected_period_id is None
        or expected_duration_seconds is None
        or period_id != expected_period_id
    ):
        return None
    if (
        min(open_px, high_px, low_px, close_px) <= 0
        or volume < 0
        or trades_count < 0
        or high_px < max(open_px, close_px)
        or low_px > min(open_px, close_px)
        or high_px < low_px
    ):
        return None
    duration_ns = expected_duration_seconds * 1_000_000_000
    observed_ns = datetime_epoch_ns(observed)
    latest_completed_boundary_ns = ((observed_ns - 1) // duration_ns) * duration_ns
    if (
        period_start[1] >= period_end[1]
        or period_start[1] % 1_000_000_000 != 0
        or period_end[1] % 1_000_000_000 != 0
        or period_end[1] - period_start[1] != duration_ns
        or period_start[1] % duration_ns != 0
        or period_end[1] != latest_completed_boundary_ns
        or not (period_start[1] <= time_open[1] <= time_close[1] < period_end[1] < observed_ns)
    ):
        return None
    ingested, generated = _strict_local_clocks(observed)
    event_ts_ms = period_end[1] // 1_000_000
    event_ts_ns = period_end[1]
    ingested_ts_ms = datetime_epoch_ns(ingested) // 1_000_000
    period_start_utc = iso_utc_ns(period_start[1])
    period_end_utc = iso_utc_ns(period_end[1])
    return {
        "schema_version": "v2_coinapi_rest_ohlcv_quarantine_v3",
        "provider_identity_schema_version": PROVIDER_IDENTITY_SCHEMA_VERSION,
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "enforcement_epoch": ENFORCEMENT_EPOCH,
        "producer_version": TRUST_PRODUCER_VERSION,
        "symbol": symbol,
        "coinapi_symbol_id": coinapi_symbol,
        "coinapi_exchange_id": coinapi_exchange_id,
        "coinapi_market_type": coinapi_market_type,
        "timeframe": timeframe,
        "period_id": period_id,
        "time_period_start": period_start_utc,
        "time_period_end": period_end_utc,
        "time_open": iso_utc_ns(time_open[1]),
        "time_close": iso_utc_ns(time_close[1]),
        "source_event_time": period_end_utc,
        "feature_cutoff": period_end_utc,
        "observed_at": _iso_utc(observed),
        "ingested_at": _iso_utc(ingested),
        "generated_at": _iso_utc(generated),
        "available_at": None,
        "open": open_px,
        "high": high_px,
        "low": low_px,
        "close": close_px,
        "volume": volume,
        "trades_count": trades_count,
        "event_ts_ms": event_ts_ms,
        "event_ts_ns": event_ts_ns,
        "ingested_ts_ms": ingested_ts_ms,
        "updated_ts_ms": event_ts_ms,
        "source": "coinapi_v1",
        "native_worker_id": WORKER_ID,
        "quarantine_only": True,
        "postcommit_receipt_present": False,
        "feature_eligible": False,
        "trainer_consumable": False,
        "prediction_eligible": False,
        "trust_block_reasons": list(RAW_TRUST_BLOCK_REASONS),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        **OPTIONAL_SOURCE_FIELDS,
    }


def _connect_redis() -> Any | None:
    try:
        import redis
    except Exception:
        return None
    try:
        r = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        ping_ack = r.ping()
        return r if type(ping_ack) is bool and ping_ack is True else None
    except Exception:
        return None


def _safe_set_json(redis_client: Any, key: str, payload: Any, *, ex: int) -> bool:
    if redis_client is None:
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        raise ValueError(f"refused non-V2 Redis key: {key!r}")
    serialized = _canonical_json(payload)
    if serialized is None or type(ex) is not int or ex <= 0:
        return False
    try:
        acknowledged = redis_client.set(
            key,
            serialized,
            ex=ex,
        )
    except Exception:
        return False
    return type(acknowledged) is bool and acknowledged is True


def _canonical_json(payload: Any) -> str | None:
    if not _json_shape_within_bounds(
        payload,
        max_depth=MAX_REST_JSON_DEPTH,
        max_items=MAX_REST_JSON_ITEMS,
    ):
        return None
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None


def _decode_exact_text(value: Any) -> str | None:
    if type(value) is str:
        return value
    if type(value) is bytes:
        try:
            return value.decode("ascii")
        except UnicodeDecodeError:
            return None
    return None


def _decode_bounded_exact_text(value: Any, *, max_bytes: int) -> str | None:
    if type(value) is bytes:
        if len(value) > max_bytes:
            return None
    elif type(value) is str:
        if not _utf8_length_within_limit(value, max_bytes=max_bytes):
            return None
    else:
        return None
    return _decode_exact_text(value)


def _bounded_persistent_hash_read(
    redis_client: Any,
    *,
    key: str,
    identity_field: str,
) -> tuple[str, str | None, str | None]:
    if (
        redis_client is None
        or type(key) is not str
        or not key.startswith(V2_REDIS_PREFIX)
        or identity_field not in {"revision_ns", "last_event_ns"}
    ):
        return _STATE_READ_ERROR, None, None
    try:
        result = redis_client.eval(
            _BOUNDED_PERSISTENT_HASH_READ_LUA,
            1,
            key,
            identity_field,
            "payload",
            MAX_STATE_IDENTITY_BYTES,
            MAX_STATE_JSON_BYTES,
        )
    except Exception:
        return _STATE_READ_ERROR, None, None
    if type(result) is not list or len(result) != 3:
        return _STATE_READ_ERROR, None, None
    status = _decode_bounded_exact_text(result[0], max_bytes=MAX_STATE_IDENTITY_BYTES)
    if status == _STATE_READ_OK:
        identity = _decode_bounded_exact_text(
            result[1],
            max_bytes=MAX_STATE_IDENTITY_BYTES,
        )
        payload = _decode_bounded_exact_text(
            result[2],
            max_bytes=MAX_STATE_JSON_BYTES,
        )
        if (
            identity is None
            or not identity.isascii()
            or not identity.isdecimal()
            or payload is None
        ):
            return _STATE_READ_ERROR, None, None
        return status, identity, payload
    if status in {_STATE_READ_MISSING, _STATE_READ_INVALID, _STATE_READ_OVERSIZED}:
        return status, None, None
    return _STATE_READ_ERROR, None, None


def _provider_content_digest(payload: dict[str, Any]) -> str | None:
    provider_content = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "observed_at",
            "ingested_at",
            "ingested_ts_ms",
            "generated_at",
            "generated_utc",
        }
    }
    serialized = _canonical_json(provider_content)
    if serialized is None:
        return None
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _raw_quarantine_authority_flags_valid(payload: dict[str, Any]) -> bool:
    """Require every authority-bearing field to remain fail-closed at commit."""

    return (
        payload.get("quarantine_only") is True
        and payload.get("available_at") is None
        and payload.get("postcommit_receipt_present") is False
        and payload.get("feature_eligible") is False
        and payload.get("trainer_consumable") is False
        and payload.get("prediction_eligible") is False
        and payload.get("live_gate") == "blocked_human_only"
        and payload.get("live_symbols") == []
        and all(payload.get(key) is value for key, value in OPTIONAL_SOURCE_FIELDS.items())
    )


def _raw_payload_contains_forbidden_authority_field(payload: dict[str, Any]) -> bool:
    """Reject authority/grant/order aliases anywhere below the exact raw root."""

    stack: list[tuple[Any, bool]] = [(payload, True)]
    while stack:
        current, is_root = stack.pop()
        if isinstance(current, dict):
            for key, value in current.items():
                if type(key) is not str:
                    return True
                normalized = key.casefold()
                root_authority_field = is_root and key in RAW_AUTHORITY_FIELD_NAMES
                if (
                    (key in RAW_AUTHORITY_FIELD_NAMES and not root_authority_field)
                    or "authority" in normalized
                    or "grant" in normalized
                    or "order" in normalized
                    or "execution" in normalized
                    or "execute" in normalized
                    or "approve" in normalized
                    or "approval" in normalized
                    or "permission" in normalized
                    or "position" in normalized
                    or "trading" in normalized
                    or normalized in {"can_trade", "exchange_action_taken", "trade_enabled"}
                    or ("live" in normalized and not root_authority_field)
                ):
                    return True
                stack.append((value, False))
        elif isinstance(current, list):
            stack.extend((value, False) for value in current)
    return False


def _canonical_timestamp_ns(value: Any, *, local_clock: bool = False) -> int | None:
    if type(value) is not str:
        return None
    parsed = parse_provider_timestamp(value)
    if parsed is None:
        return None
    canonical = _iso_utc(parsed[0]) if local_clock else iso_utc_ns(parsed[1])
    if value != canonical:
        return None
    event_ns = parsed[1]
    return event_ns if type(event_ns) is int else None


def _exact_finite_number(value: Any) -> float | None:
    if type(value) not in {int, float}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) else None


def _derived_number_matches(actual: float, expected: float) -> bool:
    return isfinite(expected) and isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def _validated_orderbook_levels(value: Any) -> list[tuple[float, float]] | None:
    if type(value) is not list or not (1 <= len(value) <= 5):
        return None
    parsed: list[tuple[float, float]] = []
    for level in value:
        if type(level) is not dict or set(level) != {"price", "size"}:
            return None
        price = _exact_finite_number(level.get("price"))
        size = _exact_finite_number(level.get("size"))
        if price is None or price <= 0 or size is None or size < 0:
            return None
        parsed.append((price, size))
    return parsed


def _rest_quarantine_constants_valid(payload: dict[str, Any]) -> bool:
    return (
        payload.get("provider_identity_schema_version") == PROVIDER_IDENTITY_SCHEMA_VERSION
        and payload.get("trust_schema_version") == TRUST_SCHEMA_VERSION
        and payload.get("enforcement_epoch") == ENFORCEMENT_EPOCH
        and payload.get("producer_version") == TRUST_PRODUCER_VERSION
        and payload.get("trust_block_reasons") == list(RAW_TRUST_BLOCK_REASONS)
        and _raw_quarantine_authority_flags_valid(payload)
    )


def _rest_orderbook_quarantine_payload_valid(payload: dict[str, Any]) -> bool:
    if (
        set(payload) != REST_ORDERBOOK_QUARANTINE_FIELDS
        or payload.get("schema_version") != "v2_coinapi_rest_orderbook_quarantine_v3"
        or payload.get("source") != "coinapi_rest_orderbooks3_current"
        or not _rest_quarantine_constants_valid(payload)
    ):
        return False

    source_event_ns = _canonical_timestamp_ns(payload.get("source_event_time"))
    provider_received_ns = _canonical_timestamp_ns(payload.get("provider_received_time"))
    observed_ns = _canonical_timestamp_ns(payload.get("observed_at"), local_clock=True)
    ingested_ns = _canonical_timestamp_ns(payload.get("ingested_at"), local_clock=True)
    generated_ns = _canonical_timestamp_ns(payload.get("generated_at"), local_clock=True)
    source_event_ts_ns = payload.get("source_event_ts_ns")
    source_event_ts_ms = payload.get("source_event_ts_ms")
    if (
        source_event_ns is None
        or provider_received_ns is None
        or observed_ns is None
        or ingested_ns is None
        or generated_ns is None
        or type(source_event_ts_ns) is not int
        or source_event_ts_ns < 0
        or type(source_event_ts_ms) is not int
        or source_event_ts_ns != source_event_ns
        or source_event_ts_ms != source_event_ns // 1_000_000
        or payload.get("time_exchange") != payload.get("source_event_time")
        or payload.get("time_coinapi") != payload.get("provider_received_time")
        or payload.get("generated_utc") != payload.get("generated_at")
        or not (source_event_ns <= provider_received_ns <= observed_ns < ingested_ns < generated_ns)
    ):
        return False

    best_bid_px = _exact_finite_number(payload.get("best_bid_px"))
    best_ask_px = _exact_finite_number(payload.get("best_ask_px"))
    best_bid_sz = _exact_finite_number(payload.get("best_bid_sz"))
    best_ask_sz = _exact_finite_number(payload.get("best_ask_sz"))
    mid_px = _exact_finite_number(payload.get("mid_px"))
    spread_bps = _exact_finite_number(payload.get("spread_bps"))
    book_bid_sum = _exact_finite_number(payload.get("book_bid_sum_5"))
    book_ask_sum = _exact_finite_number(payload.get("book_ask_sum_5"))
    bids = _validated_orderbook_levels(payload.get("bids_top5"))
    asks = _validated_orderbook_levels(payload.get("asks_top5"))
    if (
        best_bid_px is None
        or best_ask_px is None
        or best_bid_sz is None
        or best_ask_sz is None
        or mid_px is None
        or spread_bps is None
        or book_bid_sum is None
        or book_ask_sum is None
        or bids is None
        or asks is None
        or best_bid_px <= 0
        or best_ask_px <= 0
        or best_ask_px < best_bid_px
        or best_bid_sz < 0
        or best_ask_sz < 0
        or book_bid_sum < 0
        or book_ask_sum < 0
        or any(left[0] < right[0] for left, right in zip(bids, bids[1:], strict=False))
        or any(left[0] > right[0] for left, right in zip(asks, asks[1:], strict=False))
        or not _derived_number_matches(best_bid_px, bids[0][0])
        or not _derived_number_matches(best_bid_sz, bids[0][1])
        or not _derived_number_matches(best_ask_px, asks[0][0])
        or not _derived_number_matches(best_ask_sz, asks[0][1])
        or not _derived_number_matches(book_bid_sum, sum(size for _, size in bids))
        or not _derived_number_matches(book_ask_sum, sum(size for _, size in asks))
    ):
        return False

    expected_mid = (best_bid_px + best_ask_px) / 2.0
    expected_spread_bps = (best_ask_px - best_bid_px) / expected_mid * 10_000.0
    if (
        not _derived_number_matches(mid_px, expected_mid)
        or not (best_bid_px <= mid_px <= best_ask_px)
        or spread_bps < 0
        or not _derived_number_matches(spread_bps, expected_spread_bps)
    ):
        return False

    micro_price_value = payload.get("micro_price")
    micro_price = None if micro_price_value is None else _exact_finite_number(micro_price_value)
    top_total = best_bid_sz + best_ask_sz
    if micro_price_value is not None and micro_price is None:
        return False
    if top_total == 0:
        if micro_price is not None:
            return False
    else:
        expected_micro_price = (
            (best_bid_px * best_ask_sz) + (best_ask_px * best_bid_sz)
        ) / top_total
        if (
            micro_price is None
            or not (best_bid_px <= micro_price <= best_ask_px)
            or not _derived_number_matches(micro_price, expected_micro_price)
        ):
            return False

    imbalance_value = payload.get("imbalance_5")
    imbalance = None if imbalance_value is None else _exact_finite_number(imbalance_value)
    book_total = book_bid_sum + book_ask_sum
    if imbalance_value is not None and imbalance is None:
        return False
    if book_total == 0:
        return imbalance is None
    expected_imbalance = (book_bid_sum - book_ask_sum) / book_total
    return (
        imbalance is not None
        and -1.0 <= imbalance <= 1.0
        and _derived_number_matches(imbalance, expected_imbalance)
    )


def _rest_ohlcv_quarantine_payload_valid(payload: dict[str, Any]) -> bool:
    timeframe = payload.get("timeframe")
    if (
        set(payload) != REST_OHLCV_QUARANTINE_FIELDS
        or payload.get("schema_version") != "v2_coinapi_rest_ohlcv_quarantine_v3"
        or payload.get("source") != "coinapi_v1"
        or payload.get("native_worker_id") != WORKER_ID
        or type(timeframe) is not str
        or timeframe not in COINAPI_PERIOD_MAP
        or payload.get("period_id") != COINAPI_PERIOD_MAP[timeframe]
        or not _rest_quarantine_constants_valid(payload)
    ):
        return False

    period_start_ns = _canonical_timestamp_ns(payload.get("time_period_start"))
    period_end_ns = _canonical_timestamp_ns(payload.get("time_period_end"))
    time_open_ns = _canonical_timestamp_ns(payload.get("time_open"))
    time_close_ns = _canonical_timestamp_ns(payload.get("time_close"))
    source_event_ns = _canonical_timestamp_ns(payload.get("source_event_time"))
    feature_cutoff_ns = _canonical_timestamp_ns(payload.get("feature_cutoff"))
    observed_ns = _canonical_timestamp_ns(payload.get("observed_at"), local_clock=True)
    ingested_ns = _canonical_timestamp_ns(payload.get("ingested_at"), local_clock=True)
    generated_ns = _canonical_timestamp_ns(payload.get("generated_at"), local_clock=True)
    event_ts_ns = payload.get("event_ts_ns")
    event_ts_ms = payload.get("event_ts_ms")
    ingested_ts_ms = payload.get("ingested_ts_ms")
    updated_ts_ms = payload.get("updated_ts_ms")
    if (
        period_start_ns is None
        or period_end_ns is None
        or time_open_ns is None
        or time_close_ns is None
        or source_event_ns is None
        or feature_cutoff_ns is None
        or observed_ns is None
        or ingested_ns is None
        or generated_ns is None
        or type(event_ts_ns) is not int
        or event_ts_ns < 0
        or type(event_ts_ms) is not int
        or type(ingested_ts_ms) is not int
        or type(updated_ts_ms) is not int
        or source_event_ns != period_end_ns
        or feature_cutoff_ns != period_end_ns
        or event_ts_ns != period_end_ns
        or event_ts_ms != period_end_ns // 1_000_000
        or updated_ts_ms != event_ts_ms
        or ingested_ts_ms != ingested_ns // 1_000_000
    ):
        return False

    duration_ns = COINAPI_TIMEFRAME_SECONDS[timeframe] * 1_000_000_000
    latest_completed_boundary_ns = ((observed_ns - 1) // duration_ns) * duration_ns
    if (
        period_start_ns >= period_end_ns
        or period_start_ns % 1_000_000_000 != 0
        or period_end_ns % 1_000_000_000 != 0
        or period_end_ns - period_start_ns != duration_ns
        or period_start_ns % duration_ns != 0
        or period_end_ns != latest_completed_boundary_ns
        or not (
            period_start_ns
            <= time_open_ns
            <= time_close_ns
            < period_end_ns
            < observed_ns
            < ingested_ns
            < generated_ns
        )
    ):
        return False

    open_px = _exact_finite_number(payload.get("open"))
    high_px = _exact_finite_number(payload.get("high"))
    low_px = _exact_finite_number(payload.get("low"))
    close_px = _exact_finite_number(payload.get("close"))
    volume = _exact_finite_number(payload.get("volume"))
    trades_count = payload.get("trades_count")
    return (
        open_px is not None
        and high_px is not None
        and low_px is not None
        and close_px is not None
        and volume is not None
        and min(open_px, high_px, low_px, close_px) > 0
        and volume >= 0
        and type(trades_count) is int
        and trades_count >= 0
        and high_px >= max(open_px, close_px)
        and low_px <= min(open_px, close_px)
        and high_px >= low_px
    )


def _expected_quarantine_keys(
    payload: dict[str, Any],
) -> tuple[str, str, str, str] | None:
    schema = payload.get("schema_version")
    if type(schema) is not str:
        return None
    expected_fields = {
        "v2_coinapi_rest_orderbook_quarantine_v3": REST_ORDERBOOK_QUARANTINE_FIELDS,
        "v2_coinapi_rest_ohlcv_quarantine_v3": REST_OHLCV_QUARANTINE_FIELDS,
    }.get(schema)
    symbol = _validated_runtime_symbol(payload.get("symbol"))
    if (
        symbol is None
        or expected_fields is None
        or set(payload) != expected_fields
        or payload.get("trust_block_reasons") != list(RAW_TRUST_BLOCK_REASONS)
        or _raw_payload_contains_forbidden_authority_field(payload)
    ):
        return None
    coinapi_symbol = payload.get("coinapi_symbol_id")
    if type(coinapi_symbol) is not str or "_" not in coinapi_symbol:
        return None
    provider_identity = parse_coinapi_symbol_id(coinapi_symbol)
    if (
        provider_identity is None
        or provider_identity[2] != symbol
        or payload.get("provider_identity_schema_version") != PROVIDER_IDENTITY_SCHEMA_VERSION
        or payload.get("coinapi_exchange_id") != provider_identity[0]
        or payload.get("coinapi_market_type") != provider_identity[1]
    ):
        return None
    if not _raw_quarantine_authority_flags_valid(payload):
        return None
    try:
        expected_coinapi_symbol = _coinapi_symbol_id(
            symbol,
            exchange_id=coinapi_symbol.split("_", 1)[0],
        )
    except ValueError:
        return None
    if coinapi_symbol != expected_coinapi_symbol:
        return None
    if schema == "v2_coinapi_rest_orderbook_quarantine_v3":
        if not _rest_orderbook_quarantine_payload_valid(payload):
            return None
        digest = _provider_content_digest(payload)
        if digest is None:
            return None
        event_ns = payload.get("source_event_ts_ns")
        if type(event_ns) is not int or event_ns < 0:
            return None
        return (
            REST_ORDERBOOK_FENCE_KEY_TEMPLATE.format(
                coinapi_symbol_id=coinapi_symbol,
                symbol=symbol,
            ),
            REST_ORDERBOOK_DATA_KEY_TEMPLATE.format(
                coinapi_symbol_id=coinapi_symbol,
                symbol=symbol,
            ),
            REST_ORDERBOOK_CONFLICT_KEY_TEMPLATE.format(
                coinapi_symbol_id=coinapi_symbol,
                symbol=symbol,
                event_ns=event_ns,
                digest=digest,
            ),
            str(event_ns),
        )
    if schema == "v2_coinapi_rest_ohlcv_quarantine_v3":
        if not _rest_ohlcv_quarantine_payload_valid(payload):
            return None
        digest = _provider_content_digest(payload)
        if digest is None:
            return None
        timeframe = payload.get("timeframe")
        event_ns = payload.get("event_ts_ns")
        if (
            type(timeframe) is not str
            or timeframe not in COINAPI_PERIOD_MAP
            or payload.get("period_id") != COINAPI_PERIOD_MAP[timeframe]
            or type(event_ns) is not int
            or event_ns < 0
        ):
            return None
        return (
            REST_OHLCV_FENCE_KEY_TEMPLATE.format(
                coinapi_symbol_id=coinapi_symbol,
                symbol=symbol,
                timeframe=timeframe,
            ),
            REST_OHLCV_DATA_KEY_TEMPLATE.format(
                coinapi_symbol_id=coinapi_symbol,
                symbol=symbol,
                timeframe=timeframe,
            ),
            REST_OHLCV_CONFLICT_KEY_TEMPLATE.format(
                coinapi_symbol_id=coinapi_symbol,
                symbol=symbol,
                timeframe=timeframe,
                event_ns=event_ns,
                digest=digest,
            ),
            str(event_ns),
        )
    return None


def _atomic_fenced_quarantine_write(
    redis_client: Any,
    *,
    fence_key: str,
    data_key: str,
    conflict_key: str,
    event_identity_ns: str,
    payload: dict[str, Any],
    ex: int,
) -> tuple[str, int]:
    if redis_client is None:
        return _FENCE_ERROR, -2
    if (
        not isinstance(event_identity_ns, str)
        or not event_identity_ns.isascii()
        or not event_identity_ns.isdecimal()
        or type(ex) is not int
        or ex <= 0
    ):
        return _FENCE_ERROR, -2
    expected = _expected_quarantine_keys(payload)
    if expected is None:
        return _FENCE_ERROR, -2
    if (fence_key, data_key, conflict_key, event_identity_ns) != expected:
        raise ValueError("CoinAPI fenced write keys do not exactly bind the payload")
    serialized = _canonical_json(payload)
    if serialized is None or not _utf8_length_within_limit(
        serialized,
        max_bytes=MAX_REDIS_QUARANTINE_JSON_BYTES,
    ):
        return _FENCE_ERROR, -2
    try:
        commit_payload = json.loads(serialized)
    except (json.JSONDecodeError, TypeError):
        return _FENCE_ERROR, -2
    if type(commit_payload) is not dict or _expected_quarantine_keys(commit_payload) != expected:
        return _FENCE_ERROR, -2
    digest = _provider_content_digest(commit_payload)
    if digest is None:
        return _FENCE_ERROR, -2
    try:
        result = redis_client.eval(
            _ATOMIC_FENCE_LUA,
            3,
            fence_key,
            data_key,
            conflict_key,
            event_identity_ns,
            digest,
            serialized,
            ex,
            MAX_STATE_IDENTITY_BYTES,
            MAX_REDIS_QUARANTINE_JSON_BYTES,
        )
    except Exception:
        return _FENCE_ERROR, -2
    if type(result) is not list or len(result) != 3:
        return _FENCE_ERROR, -2
    status = _decode_exact_text(result[0])
    count = result[1]
    payload_ttl_ms = result[2]
    if type(count) is not int or type(payload_ttl_ms) is not int:
        return _FENCE_ERROR, -2
    expected_counts = {
        _FENCE_COMMITTED: 1,
        _FENCE_DUPLICATE: 0,
        _FENCE_OLDER: 0,
        _FENCE_CONFLICT: 1,
        _FENCE_CONFLICT_DUPLICATE: 0,
        _FENCE_ERROR: 0,
    }
    if status not in expected_counts or count != expected_counts[status]:
        return _FENCE_ERROR, -2
    if status == _FENCE_COMMITTED and payload_ttl_ms <= 0:
        return _FENCE_ERROR, -2
    if payload_ttl_ms < -2:
        return _FENCE_ERROR, -2
    return status, payload_ttl_ms


def _credential_fingerprint(api_key: str, *, transport: str) -> str | None:
    if type(api_key) is not str or not api_key or transport not in {"rest", "wsds"}:
        return None
    material = (
        b"coinapi-optional-credential-fingerprint-v1\x00"
        + transport.encode("ascii")
        + b"\x00"
        + api_key.encode("utf-8")
    )
    return hashlib.sha256(material).hexdigest()


def _auth_latch_key(api_key: str) -> str | None:
    fingerprint = _credential_fingerprint(api_key, transport="rest")
    return f"{AUTH_LATCH_KEY_PREFIX}{fingerprint}" if fingerprint is not None else None


def _ws_cadence_key(
    *,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
) -> str | None:
    identity = parse_coinapi_symbol_id(coinapi_symbol_id)
    if _validated_runtime_symbol(symbol) is None or identity is None or identity[2] != symbol:
        return None
    fingerprint = _credential_fingerprint(api_key, transport="wsds")
    if fingerprint is None:
        return None
    return WS_CADENCE_KEY_TEMPLATE.format(
        credential_fingerprint=fingerprint,
        coinapi_symbol_id=coinapi_symbol_id,
        symbol=symbol,
    )


def _auth_state_signature(api_key: str, unsigned: dict[str, Any]) -> str | None:
    if type(api_key) is not str or not api_key:
        return None
    serialized = _canonical_json(unsigned)
    if serialized is None:
        return None
    material = b"coinapi-optional-auth-backoff-v1\x00rest\x00" + serialized.encode("ascii")
    return hmac.new(api_key.encode("utf-8"), material, hashlib.sha256).hexdigest()


def _validated_auth_state(
    candidate: Any,
    *,
    api_key: str,
) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    required = {
        "schema_version",
        "provider",
        "transport",
        "endpoint_identity",
        "credential_fingerprint",
        "failure_count",
        "last_http_status",
        "last_error_class",
        "next_probe_at_ns",
        "retry_after_honored",
        "revision_ns",
        "signature",
    }
    fingerprint = _credential_fingerprint(api_key, transport="rest")
    if set(candidate) != required or fingerprint is None:
        return None
    if (
        candidate.get("schema_version") != AUTH_LATCH_SCHEMA_VERSION
        or candidate.get("provider") != "coinapi"
        or candidate.get("transport") != "rest"
        or candidate.get("endpoint_identity") != "rest.coinapi.io:443"
        or candidate.get("credential_fingerprint") != fingerprint
        or type(candidate.get("failure_count")) is not int
        or candidate["failure_count"] <= 0
        or type(candidate.get("last_http_status")) is not int
        or candidate["last_http_status"]
        not in TERMINAL_PROVIDER_HTTP_STATUSES | {RATE_LIMITED_HTTP_STATUS}
        or type(candidate.get("last_error_class")) is not str
        or not candidate["last_error_class"].isidentifier()
        or len(candidate["last_error_class"]) > 80
        or type(candidate.get("retry_after_honored")) is not bool
    ):
        return None
    revision_ns = candidate.get("revision_ns")
    next_probe_at_ns = candidate.get("next_probe_at_ns")
    if (
        type(revision_ns) is not int
        or revision_ns < 0
        or type(next_probe_at_ns) is not int
        or next_probe_at_ns <= revision_ns
        or next_probe_at_ns - revision_ns < int(MIN_OPTIONAL_REPROBE_SECONDS * 1_000_000_000)
        or next_probe_at_ns - revision_ns > int(AUTH_BACKOFF_MAX_SECONDS * 1_000_000_000)
    ):
        return None
    signature = candidate.get("signature")
    if type(signature) is not str or len(signature) != 64 or not signature.isascii():
        return None
    unsigned = {key: value for key, value in candidate.items() if key != "signature"}
    expected = _auth_state_signature(api_key, unsigned)
    if expected is None or not hmac.compare_digest(signature, expected):
        return None
    return dict(candidate)


def _deterministic_auth_backoff_seconds(
    *,
    fingerprint: str,
    failure_count: int,
) -> float:
    exponent = min(max(0, failure_count - 1), 30)
    base = min(
        AUTH_BACKOFF_MAX_SECONDS,
        AUTH_BACKOFF_BASE_SECONDS * (2**exponent),
    )
    digest = hashlib.sha256(
        f"coinapi-rest-auth-backoff-v1:{fingerprint}:{failure_count}".encode("ascii")
    ).digest()
    unit = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
    jittered = base * (0.75 + (0.5 * unit))
    return float(min(AUTH_BACKOFF_MAX_SECONDS, max(AUTH_BACKOFF_BASE_SECONDS, jittered)))


def _build_auth_state(
    *,
    api_key: str,
    http_status: int,
    error_class: str,
    prior_state: dict[str, Any] | None,
    quota_metadata: dict[str, Any] | None,
    now_ns: int | None = None,
) -> dict[str, Any] | None:
    if (
        type(http_status) is not int
        or http_status not in TERMINAL_PROVIDER_HTTP_STATUSES | {RATE_LIMITED_HTTP_STATUS}
        or type(error_class) is not str
        or not error_class.isidentifier()
    ):
        return None
    fingerprint = _credential_fingerprint(api_key, transport="rest")
    if fingerprint is None:
        return None
    revision_ns = time.time_ns() if now_ns is None else now_ns
    if type(revision_ns) is not int or revision_ns < 0:
        return None
    validated_prior = _validated_auth_state(prior_state, api_key=api_key)
    failure_count = int(validated_prior["failure_count"]) + 1 if validated_prior is not None else 1
    retry_delay = _provider_retry_delay_seconds(quota_metadata)
    retry_after_honored = retry_delay is not None and retry_delay > 0
    if retry_delay is not None and retry_delay > 0:
        delay_seconds = min(
            AUTH_BACKOFF_MAX_SECONDS,
            max(MIN_OPTIONAL_REPROBE_SECONDS, float(retry_delay)),
        )
    else:
        delay_seconds = max(
            MIN_OPTIONAL_REPROBE_SECONDS,
            _deterministic_auth_backoff_seconds(
                fingerprint=fingerprint,
                failure_count=failure_count,
            ),
        )
    next_probe_at_ns = revision_ns + max(1, int(delay_seconds * 1_000_000_000))
    unsigned: dict[str, Any] = {
        "schema_version": AUTH_LATCH_SCHEMA_VERSION,
        "provider": "coinapi",
        "transport": "rest",
        "endpoint_identity": "rest.coinapi.io:443",
        "credential_fingerprint": fingerprint,
        "failure_count": failure_count,
        "last_http_status": http_status,
        "last_error_class": error_class[:80],
        "next_probe_at_ns": next_probe_at_ns,
        "retry_after_honored": retry_after_honored,
        "revision_ns": revision_ns,
    }
    signature = _auth_state_signature(api_key, unsigned)
    return {**unsigned, "signature": signature} if signature is not None else None


def _persist_auth_state(
    redis_client: Any,
    *,
    api_key: str,
    state: dict[str, Any],
) -> str:
    key = _auth_latch_key(api_key)
    validated = _validated_auth_state(state, api_key=api_key)
    if redis_client is None or key is None or validated is None:
        return _AUTH_STATE_ERROR
    existing = _auth_state_record_exists(redis_client, api_key=api_key)
    if existing is None or (
        existing is True and _load_auth_state(redis_client, api_key=api_key) is None
    ):
        return _AUTH_STATE_ERROR
    serialized = _canonical_json(validated)
    if serialized is None or len(serialized.encode("ascii")) > MAX_STATE_JSON_BYTES:
        return _AUTH_STATE_ERROR
    try:
        result = redis_client.eval(
            _ATOMIC_AUTH_STATE_LUA,
            1,
            key,
            str(validated["revision_ns"]),
            serialized,
            MAX_STATE_IDENTITY_BYTES,
            MAX_STATE_JSON_BYTES,
        )
    except Exception:
        return _AUTH_STATE_ERROR
    if type(result) is not list or len(result) != 2:
        return _AUTH_STATE_ERROR
    status = _decode_exact_text(result[0])
    count = result[1]
    expected_counts = {
        _AUTH_STATE_COMMITTED: 1,
        _AUTH_STATE_CURRENT: 0,
        _AUTH_STATE_OLDER: 0,
        _AUTH_STATE_CONFLICT: 0,
        _AUTH_STATE_ERROR: 0,
    }
    if type(count) is not int or status not in expected_counts:
        return _AUTH_STATE_ERROR
    if count != expected_counts[status]:
        return _AUTH_STATE_ERROR
    return status


def _load_auth_state(redis_client: Any, *, api_key: str) -> dict[str, Any] | None:
    key = _auth_latch_key(api_key)
    if redis_client is None or key is None:
        return None
    read_status, revision, serialized = _bounded_persistent_hash_read(
        redis_client,
        key=key,
        identity_field="revision_ns",
    )
    if read_status != _STATE_READ_OK or revision is None or serialized is None:
        return None
    candidate = _loads_bounded_json(
        serialized,
        max_bytes=MAX_STATE_JSON_BYTES,
        max_depth=16,
        max_items=64,
    )
    validated = _validated_auth_state(candidate, api_key=api_key)
    if validated is None or str(validated["revision_ns"]) != revision:
        return None
    return validated


def _clear_auth_state(redis_client: Any, *, api_key: str) -> bool:
    key = _auth_latch_key(api_key)
    if redis_client is None or key is None:
        return False
    try:
        acknowledged = redis_client.delete(key)
    except Exception:
        return False
    return type(acknowledged) is int and acknowledged in {0, 1}


def _ws_cadence_signature(api_key: str, unsigned: dict[str, Any]) -> str | None:
    if type(api_key) is not str or not api_key:
        return None
    serialized = _canonical_json(unsigned)
    if serialized is None:
        return None
    material = b"coinapi-wsds-cadence-v1\x00" + serialized.encode("ascii")
    return hmac.new(api_key.encode("utf-8"), material, hashlib.sha256).hexdigest()


def _validated_ws_cadence_basis(
    candidate: Any,
    *,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
) -> dict[str, Any] | None:
    required = {
        "schema_version",
        "provider_identity_schema_version",
        "symbol",
        "coinapi_symbol_id",
        "coinapi_exchange_id",
        "coinapi_market_type",
        "sample_count",
        "event_cadence_ns",
        "provider_cadence_ns",
        "arrival_cadence_ns",
        "max_source_lag_ns",
        "max_arrival_lag_ns",
        "last_event_ns",
        "last_provider_received_ns",
        "last_observed_ns",
        "generated_at",
        "signature",
    }
    identity = parse_coinapi_symbol_id(coinapi_symbol_id)
    if (
        not isinstance(candidate, dict)
        or set(candidate) != required
        or _validated_runtime_symbol(symbol) is None
        or identity is None
        or identity[2] != symbol
        or candidate.get("schema_version") != WS_CADENCE_SCHEMA_VERSION
        or candidate.get("provider_identity_schema_version") != PROVIDER_IDENTITY_SCHEMA_VERSION
        or candidate.get("symbol") != symbol
        or candidate.get("coinapi_symbol_id") != coinapi_symbol_id
        or candidate.get("coinapi_exchange_id") != identity[0]
        or candidate.get("coinapi_market_type") != identity[1]
        or type(candidate.get("generated_at")) is not str
        or parse_provider_timestamp(candidate.get("generated_at")) is None
    ):
        return None
    positive = (
        "sample_count",
        "event_cadence_ns",
        "provider_cadence_ns",
        "arrival_cadence_ns",
    )
    nonnegative = (
        "max_source_lag_ns",
        "max_arrival_lag_ns",
        "last_event_ns",
        "last_provider_received_ns",
        "last_observed_ns",
    )
    if any(
        type(candidate.get(field)) is not int or candidate[field] <= 0 for field in positive
    ) or any(
        type(candidate.get(field)) is not int or candidate[field] < 0 for field in nonnegative
    ):
        return None
    if candidate["sample_count"] < 3 or not (
        candidate["last_event_ns"]
        <= candidate["last_provider_received_ns"]
        <= candidate["last_observed_ns"]
    ):
        return None
    signature = candidate.get("signature")
    if type(signature) is not str or len(signature) != 64:
        return None
    unsigned = {key: value for key, value in candidate.items() if key != "signature"}
    expected = _ws_cadence_signature(api_key, unsigned)
    if expected is None or not hmac.compare_digest(signature, expected):
        return None
    return dict(candidate)


def _load_ws_cadence_basis(
    redis_client: Any,
    *,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
) -> dict[str, Any] | None:
    if (
        redis_client is None
        or _validated_runtime_symbol(symbol) is None
        or parse_coinapi_symbol_id(coinapi_symbol_id) is None
    ):
        return None
    key = _ws_cadence_key(
        symbol=symbol,
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
    )
    if key is None:
        return None
    read_status, stored_event, serialized = _bounded_persistent_hash_read(
        redis_client,
        key=key,
        identity_field="last_event_ns",
    )
    if read_status != _STATE_READ_OK or stored_event is None or serialized is None:
        return None
    candidate = _loads_bounded_json(
        serialized,
        max_bytes=MAX_STATE_JSON_BYTES,
        max_depth=16,
        max_items=64,
    )
    validated = _validated_ws_cadence_basis(
        candidate,
        symbol=symbol,
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
    )
    if validated is None or str(validated["last_event_ns"]) != stored_event:
        return None
    return validated


def _orderbook_fresh_against_prior_cadence(
    orderbook: dict[str, Any],
    basis: dict[str, Any] | None,
) -> tuple[bool, int | None]:
    if not isinstance(basis, dict):
        return False, None
    event_cadence = _exact_nonnegative_int(basis.get("event_cadence_ns"), positive=True)
    provider_cadence = _exact_nonnegative_int(basis.get("provider_cadence_ns"), positive=True)
    arrival_cadence = _exact_nonnegative_int(basis.get("arrival_cadence_ns"), positive=True)
    max_source_lag = _exact_nonnegative_int(basis.get("max_source_lag_ns"))
    max_arrival_lag = _exact_nonnegative_int(basis.get("max_arrival_lag_ns"))
    cadence_values = (
        event_cadence,
        provider_cadence,
        arrival_cadence,
        max_source_lag,
        max_arrival_lag,
    )
    if any(value is None for value in cadence_values):
        return False, None
    assert all(value is not None for value in cadence_values)
    event = parse_provider_timestamp(orderbook.get("source_event_time"))
    received = parse_provider_timestamp(orderbook.get("provider_received_time"))
    observed = parse_provider_timestamp(orderbook.get("observed_at"))
    if event is None or received is None or observed is None:
        return False, None
    event_ns, received_ns, observed_ns = event[1], received[1], observed[1]
    last_event = _exact_nonnegative_int(basis.get("last_event_ns"))
    last_received = _exact_nonnegative_int(basis.get("last_provider_received_ns"))
    last_observed = _exact_nonnegative_int(basis.get("last_observed_ns"))
    if last_event is None or last_received is None or last_observed is None:
        return False, None
    budget = sum(value for value in cadence_values if value is not None)
    if not (
        event_ns <= received_ns <= observed_ns
        and event_ns > last_event
        and received_ns > last_received
        and observed_ns > last_observed
    ):
        return False, budget
    event_delta = event_ns - last_event
    provider_delta = received_ns - last_received
    arrival_delta = observed_ns - last_observed
    source_lag = received_ns - event_ns
    arrival_lag = observed_ns - received_ns
    assert event_cadence is not None and arrival_cadence is not None
    assert max_source_lag is not None and max_arrival_lag is not None
    source_budget = max(max_source_lag, event_cadence)
    arrival_budget = max(max_arrival_lag, arrival_cadence)
    fresh = (
        source_lag <= source_budget
        and arrival_lag <= arrival_budget
        and observed_ns - event_ns <= budget
        and abs(provider_delta - event_delta) <= source_budget
        and abs(arrival_delta - provider_delta) <= arrival_budget
    )
    return fresh, budget


def _rate_limit_sleep(last_request: float, min_delay: float) -> None:
    if not isfinite(last_request) or not isfinite(min_delay) or min_delay <= 0:
        raise ValueError("CoinAPI REST rate delay must be finite and positive")
    wait = min_delay - (time.monotonic() - last_request)
    if wait > 0:
        time.sleep(wait)


def fetch_for_symbols(
    symbols: tuple[str, ...],
    *,
    api_key: str,
    rest_base_url: str,
    exchange_id: str,
    fetch_symbol_limit: int | None,
    fetch_ohlcv: bool,
    ohlcv_timeframes: tuple[str, ...],
    ohlcv_symbol_limit: int | None,
    timeout_seconds: float,
    max_rps: float,
) -> dict[str, Any]:
    if any(_validated_runtime_symbol(symbol) is None for symbol in symbols):
        raise ValueError("all CoinAPI symbols must exactly match uppercase [A-Z0-9]+USDT")
    if any(timeframe not in COINAPI_PERIOD_MAP for timeframe in ohlcv_timeframes):
        raise ValueError("all CoinAPI OHLCV timeframes must be approved")
    validated_timeout = _validated_finite_range(
        timeout_seconds,
        minimum=MIN_REST_TIMEOUT_SECONDS,
        maximum=MAX_REST_TIMEOUT_SECONDS,
    )
    validated_max_rps = _validated_finite_range(
        max_rps,
        minimum=MIN_REST_MAX_RPS,
        maximum=MAX_REST_MAX_RPS,
    )
    if validated_timeout is None or validated_max_rps is None:
        raise ValueError("CoinAPI REST timeout/max_rps must be within finite safe ranges")
    started = _utc_iso()
    selected = tuple(symbols[:fetch_symbol_limit]) if fetch_symbol_limit else tuple(symbols)
    ohlcv_selected = (
        tuple(symbols[:ohlcv_symbol_limit])
        if ohlcv_symbol_limit and ohlcv_symbol_limit > 0
        else selected
    )
    ohlcv_selected_set = set(ohlcv_selected)
    rows: list[dict[str, Any]] = []
    min_delay = 1.0 / validated_max_rps
    last_request = 0.0
    requests_attempted = 0
    ohlcv_symbols_probed: set[str] = set()
    provider_health: dict[str, Any] | None = None
    fanout_stopped_early = False
    authenticated_http_successes = 0
    for symbol in selected:
        _rate_limit_sleep(last_request, min_delay)
        coinapi_symbol = _coinapi_symbol_id(symbol, exchange_id=exchange_id)
        status, body, quota_metadata = _http_get_json(
            rest_base_url,
            "/v1/orderbooks3/current",
            api_key=api_key,
            params={"filter_symbol_id": coinapi_symbol},
            timeout_seconds=validated_timeout,
        )
        requests_attempted += 1
        last_request = time.monotonic()
        error_class = _provider_error_class(status, body)
        if error_class is None:
            authenticated_http_successes += 1
        normalized = (
            _normalize_orderbook(symbol, coinapi_symbol, body) if error_class is None else None
        )
        ohlcv_rows: dict[str, Any] = {}
        ohlcv_statuses: dict[str, int] = {}
        ohlcv_failures: dict[str, dict[str, Any]] = {}
        row_provider_health: dict[str, Any] | None = None
        stop_after_row = False
        if error_class is not None:
            row_provider_health = _provider_health(
                http_status=status,
                error_class=error_class,
                quota_metadata=quota_metadata,
            )
            provider_health = row_provider_health
            stop_after_row = row_provider_health["terminal_for_cycle"] is True
            fanout_stopped_early = stop_after_row
        elif fetch_ohlcv and symbol in ohlcv_selected_set:
            ohlcv_symbols_probed.add(symbol)
            for timeframe in ohlcv_timeframes:
                period_id = COINAPI_PERIOD_MAP.get(timeframe)
                if not period_id:
                    ohlcv_statuses[timeframe] = 0
                    continue
                _rate_limit_sleep(last_request, min_delay)
                tf_status, tf_body, tf_quota_metadata = _http_get_json(
                    rest_base_url,
                    f"/v1/ohlcv/{urllib.parse.quote(coinapi_symbol, safe='')}/latest",
                    api_key=api_key,
                    params={"period_id": period_id, "limit": 1},
                    timeout_seconds=validated_timeout,
                )
                requests_attempted += 1
                last_request = time.monotonic()
                ohlcv_statuses[timeframe] = tf_status
                tf_error_class = _provider_error_class(tf_status, tf_body)
                if tf_error_class is None:
                    authenticated_http_successes += 1
                if tf_error_class is not None:
                    timeframe_health = _provider_health(
                        http_status=tf_status,
                        error_class=tf_error_class,
                        quota_metadata=tf_quota_metadata,
                    )
                    ohlcv_failures[timeframe] = timeframe_health
                    row_provider_health = timeframe_health
                    provider_health = timeframe_health
                    if timeframe_health["terminal_for_cycle"] is True:
                        stop_after_row = True
                        fanout_stopped_early = True
                        break
                    continue
                tf_normalized = _normalize_ohlcv(
                    symbol,
                    coinapi_symbol,
                    timeframe,
                    period_id,
                    tf_body,
                )
                if tf_normalized is not None:
                    ohlcv_rows[timeframe] = tf_normalized
        rows.append(
            {
                "symbol": symbol,
                "coinapi_symbol_id": coinapi_symbol,
                "http_status": status,
                "orderbook": normalized,
                "orderbook_present": normalized is not None,
                "ohlcv_http_statuses": ohlcv_statuses,
                "ohlcv_failures": ohlcv_failures,
                "ohlcv": ohlcv_rows,
                "ohlcv_present_timeframes": sorted(ohlcv_rows.keys()),
                "ohlcv_typed_missing_timeframes": sorted(
                    timeframe
                    for timeframe, response_status in ohlcv_statuses.items()
                    if not (200 <= response_status < 300) or timeframe not in ohlcv_rows
                ),
                "orderbook_failure": (row_provider_health if error_class is not None else None),
                "provider_health": row_provider_health,
                "trainer_consumable": False,
                "typed_missing": (
                    row_provider_health is not None
                    or normalized is None
                    or any(
                        not (200 <= response_status < 300) or timeframe not in ohlcv_rows
                        for timeframe, response_status in ohlcv_statuses.items()
                    )
                ),
                **OPTIONAL_SOURCE_FIELDS,
            }
        )
        if stop_after_row:
            break
    provider_retry_delay = _provider_retry_delay_seconds(
        provider_health.get("quota_metadata") if provider_health else None
    )
    per_symbol_health = {
        str(row.get("symbol")): {
            "observed": True,
            "orderbook_schema_valid": bool(row.get("orderbook_present")),
            "ohlcv_schema_valid_timeframes": list(row.get("ohlcv_present_timeframes") or []),
            "typed_missing": bool(row.get("typed_missing")),
            "fresh": False,
            "committed": False,
            "receipt_present": False,
        }
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("symbol"), str)
    }
    for symbol in selected:
        per_symbol_health.setdefault(
            symbol,
            {
                "observed": False,
                "orderbook_schema_valid": False,
                "ohlcv_schema_valid_timeframes": [],
                "typed_missing": True,
                "fresh": False,
                "committed": False,
                "receipt_present": False,
            },
        )
    return {
        "started_utc": started,
        "finished_utc": _utc_iso(),
        "symbols_requested": len(symbols),
        "symbols_selected": len(selected),
        "symbols_fetched": len(rows),
        "symbols_unprobed": max(0, len(selected) - len(rows)),
        "requests_attempted": requests_attempted,
        "authenticated_http_successes": authenticated_http_successes,
        "fanout_stopped_early": fanout_stopped_early,
        "ohlcv_fetch_enabled": bool(fetch_ohlcv),
        "ohlcv_symbols_fetched": len(ohlcv_symbols_probed),
        "ohlcv_timeframes": list(ohlcv_timeframes) if fetch_ohlcv else [],
        "provider_health": provider_health,
        "provider_retry_delay_seconds": provider_retry_delay,
        "samples_observed": requests_attempted,
        "schema_valid_orderbooks": sum(
            1 for row in rows if isinstance(row, dict) and row.get("orderbook_present")
        ),
        "schema_valid_ohlcv": sum(
            len(row.get("ohlcv_present_timeframes") or []) for row in rows if isinstance(row, dict)
        ),
        "fresh_samples": 0,
        "committed_samples": 0,
        "receipt_accepted_samples": 0,
        "per_symbol_health": per_symbol_health,
        "trainer_consumable": False,
        "typed_missing_rows": sum(
            1 for row in rows if isinstance(row, dict) and row.get("typed_missing")
        ),
        "rows": rows,
        **OPTIONAL_SOURCE_FIELDS,
    }


def persist_to_v2_redis(
    redis_client: Any,
    fetch: dict[str, Any],
    *,
    ttl_seconds: int,
    api_key: str = "",
) -> list[str]:
    written: list[str] = []
    publication_stats: dict[str, int] = {
        "observed": 0,
        "schema_valid": 0,
        "orderbook_schema_valid": 0,
        "ohlcv_schema_valid": 0,
        "fresh": 0,
        "committed": 0,
        "orderbook_committed": 0,
        "ohlcv_committed": 0,
        "receipt_accepted": 0,
        "older_rejected": 0,
        "duplicate_rejected": 0,
        "conflicts_quarantined": 0,
        "redis_ack_failures": 0,
    }

    def record_result(
        result: str,
        *,
        fence_key: str,
        data_key: str,
        conflict_key: str,
        kind: str,
        fresh: bool,
    ) -> None:
        if result == _FENCE_COMMITTED:
            written.extend((fence_key, data_key))
            publication_stats["committed"] += 1
            publication_stats[f"{kind}_committed"] += 1
            if fresh:
                publication_stats["fresh"] += 1
        elif result == _FENCE_OLDER:
            publication_stats["older_rejected"] += 1
        elif result in {_FENCE_DUPLICATE, _FENCE_CONFLICT_DUPLICATE}:
            publication_stats["duplicate_rejected"] += 1
        elif result == _FENCE_CONFLICT:
            publication_stats["conflicts_quarantined"] += 1
            written.append(conflict_key)
        else:
            publication_stats["redis_ack_failures"] += 1

    for row in fetch.get("rows", []):
        if not isinstance(row, dict):
            continue
        symbol = _validated_runtime_symbol(row.get("symbol"))
        if symbol is None:
            publication_stats["redis_ack_failures"] += 1
            continue
        publication_stats["observed"] += 1
        orderbook = row.get("orderbook")
        if isinstance(orderbook, dict) and orderbook.get("symbol") == symbol:
            publication_stats["schema_valid"] += 1
            publication_stats["orderbook_schema_valid"] += 1
            event_ns = orderbook.get("source_event_ts_ns")
            coinapi_symbol_id = orderbook.get("coinapi_symbol_id")
            if type(coinapi_symbol_id) is not str:
                publication_stats["redis_ack_failures"] += 1
                continue
            digest = _provider_content_digest(orderbook) or "invalid"
            fence_key = REST_ORDERBOOK_FENCE_KEY_TEMPLATE.format(
                coinapi_symbol_id=coinapi_symbol_id,
                symbol=symbol,
            )
            data_key = REST_ORDERBOOK_DATA_KEY_TEMPLATE.format(
                coinapi_symbol_id=coinapi_symbol_id,
                symbol=symbol,
            )
            conflict_key = REST_ORDERBOOK_CONFLICT_KEY_TEMPLATE.format(
                coinapi_symbol_id=coinapi_symbol_id,
                symbol=symbol,
                event_ns=event_ns,
                digest=digest,
            )
            fence_result = _atomic_fenced_quarantine_write(
                redis_client,
                fence_key=fence_key,
                data_key=data_key,
                conflict_key=conflict_key,
                event_identity_ns=str(event_ns),
                payload=orderbook,
                ex=ttl_seconds,
            )
            row["orderbook_commit_state"], row["orderbook_payload_ttl_ms"] = fence_result
            prior_basis = (
                _load_ws_cadence_basis(
                    redis_client,
                    symbol=symbol,
                    coinapi_symbol_id=coinapi_symbol_id,
                    api_key=api_key,
                )
                if api_key
                else None
            )
            cadence_fresh, freshness_budget_ns = _orderbook_fresh_against_prior_cadence(
                orderbook,
                prior_basis,
            )
            orderbook_fresh = (
                fence_result[0] == _FENCE_COMMITTED and fence_result[1] > 0 and cadence_fresh
            )
            row["orderbook_prior_cadence_authenticated"] = isinstance(prior_basis, dict)
            row["orderbook_freshness_budget_ns"] = freshness_budget_ns
            row["orderbook_fresh"] = orderbook_fresh
            record_result(
                fence_result[0],
                fence_key=fence_key,
                data_key=data_key,
                conflict_key=conflict_key,
                kind="orderbook",
                fresh=orderbook_fresh,
            )
        ohlcv_by_tf = row.get("ohlcv")
        if isinstance(ohlcv_by_tf, dict):
            commit_states: dict[str, str] = {}
            payload_ttls: dict[str, int] = {}
            for timeframe, candle in ohlcv_by_tf.items():
                if (
                    not isinstance(timeframe, str)
                    or timeframe not in COINAPI_PERIOD_MAP
                    or not isinstance(candle, dict)
                    or candle.get("symbol") != symbol
                    or candle.get("timeframe") != timeframe
                ):
                    publication_stats["redis_ack_failures"] += 1
                    continue
                publication_stats["schema_valid"] += 1
                publication_stats["ohlcv_schema_valid"] += 1
                event_ns = candle.get("event_ts_ns")
                coinapi_symbol_id = candle.get("coinapi_symbol_id")
                if type(coinapi_symbol_id) is not str:
                    publication_stats["redis_ack_failures"] += 1
                    continue
                digest = _provider_content_digest(candle) or "invalid"
                fence_key = REST_OHLCV_FENCE_KEY_TEMPLATE.format(
                    coinapi_symbol_id=coinapi_symbol_id,
                    symbol=symbol,
                    timeframe=timeframe,
                )
                data_key = REST_OHLCV_DATA_KEY_TEMPLATE.format(
                    coinapi_symbol_id=coinapi_symbol_id,
                    symbol=symbol,
                    timeframe=timeframe,
                )
                conflict_key = REST_OHLCV_CONFLICT_KEY_TEMPLATE.format(
                    coinapi_symbol_id=coinapi_symbol_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    event_ns=event_ns,
                    digest=digest,
                )
                result, payload_ttl_ms = _atomic_fenced_quarantine_write(
                    redis_client,
                    fence_key=fence_key,
                    data_key=data_key,
                    conflict_key=conflict_key,
                    event_identity_ns=str(event_ns),
                    payload=candle,
                    ex=ttl_seconds,
                )
                commit_states[timeframe] = result
                payload_ttls[timeframe] = payload_ttl_ms
                record_result(
                    result,
                    fence_key=fence_key,
                    data_key=data_key,
                    conflict_key=conflict_key,
                    kind="ohlcv",
                    fresh=result == _FENCE_COMMITTED and payload_ttl_ms > 0,
                )
            row["ohlcv_commit_states"] = commit_states
            row["ohlcv_payload_ttl_ms"] = payload_ttls
    fetch["publication_stats"] = publication_stats
    fetch["fresh_samples"] = publication_stats["fresh"]
    fetch["committed_samples"] = publication_stats["committed"]
    fetch["receipt_accepted_samples"] = publication_stats["receipt_accepted"]
    per_symbol_health = fetch.get("per_symbol_health")
    if isinstance(per_symbol_health, dict):
        for row in fetch.get("rows", []):
            if not isinstance(row, dict):
                continue
            health_symbol = row.get("symbol")
            if not isinstance(health_symbol, str):
                continue
            state = per_symbol_health.get(health_symbol)
            if not isinstance(state, dict):
                continue
            orderbook_committed = (
                row.get("orderbook_commit_state") == _FENCE_COMMITTED
                and type(row.get("orderbook_payload_ttl_ms")) is int
                and row["orderbook_payload_ttl_ms"] > 0
            )
            orderbook_fresh = orderbook_committed and row.get("orderbook_fresh") is True
            ohlcv_states = row.get("ohlcv_commit_states")
            ohlcv_ttls = row.get("ohlcv_payload_ttl_ms")
            committed_timeframes = sorted(
                timeframe
                for timeframe, result in (
                    ohlcv_states.items() if isinstance(ohlcv_states, dict) else []
                )
                if result == _FENCE_COMMITTED
                and isinstance(ohlcv_ttls, dict)
                and type(ohlcv_ttls.get(timeframe)) is int
                and ohlcv_ttls[timeframe] > 0
            )
            ohlcv_current = not isinstance(ohlcv_states, dict) or all(
                result == _FENCE_COMMITTED
                and isinstance(ohlcv_ttls, dict)
                and type(ohlcv_ttls.get(timeframe)) is int
                and ohlcv_ttls[timeframe] > 0
                for timeframe, result in ohlcv_states.items()
            )
            state["orderbook_fresh"] = orderbook_fresh
            state["orderbook_committed"] = orderbook_committed
            state["ohlcv_fresh_timeframes"] = committed_timeframes
            state["ohlcv_committed_timeframes"] = committed_timeframes
            state["fresh"] = (
                orderbook_fresh and ohlcv_current and not bool(row.get("typed_missing"))
            )
            state["committed"] = orderbook_committed and ohlcv_current
    heartbeat: dict[str, Any] = {
        "worker_id": WORKER_ID,
        "source": "coinapi_rest",
        "finished_utc": fetch.get("finished_utc"),
        "keys_written_count": len(written),
        "provider_health": fetch.get("provider_health"),
        "publication_stats": dict(publication_stats),
        "trainer_consumable": False,
        "typed_missing": (
            fetch.get("provider_health") is not None
            or (_safe_int(fetch.get("typed_missing_rows")) or 0) > 0
            or publication_stats["redis_ack_failures"] > 0
            or publication_stats["fresh"] != publication_stats["schema_valid"]
        ),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "current_data_commit_acked": publication_stats["fresh"] > 0,
        "raw_quarantine_commit_acked": publication_stats["committed"] > 0,
        **OPTIONAL_SOURCE_FIELDS,
    }
    rest_heartbeat_key = "v2:quarantine:coinapi:rest:heartbeat"
    ohlcv_heartbeat_key = "v2:quarantine:coinapi:rest:ohlcv:heartbeat"
    if _safe_set_json(redis_client, rest_heartbeat_key, heartbeat, ex=ttl_seconds):
        written.append(rest_heartbeat_key)
    else:
        publication_stats["redis_ack_failures"] += 1
    if _safe_set_json(redis_client, ohlcv_heartbeat_key, heartbeat, ex=ttl_seconds):
        written.append(ohlcv_heartbeat_key)
    else:
        publication_stats["redis_ack_failures"] += 1
    return written


def _auth_state_record_exists(redis_client: Any, *, api_key: str) -> bool | None:
    key = _auth_latch_key(api_key)
    if redis_client is None or key is None:
        return None
    try:
        value = redis_client.exists(key)
    except Exception:
        return None
    if type(value) is not int or value not in {0, 1}:
        return None
    return value == 1


def _optional_unavailable_fetch(
    symbols: tuple[str, ...],
    *,
    provider_health: dict[str, Any],
    authorization_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    public_auth_state = None
    if isinstance(authorization_state, dict):
        public_auth_state = {
            "failure_count": authorization_state.get("failure_count"),
            "last_http_status": authorization_state.get("last_http_status"),
            "last_error_class": authorization_state.get("last_error_class"),
            "next_probe_at_ns": authorization_state.get("next_probe_at_ns"),
            "retry_after_honored": authorization_state.get("retry_after_honored"),
            "credential_fingerprint_emitted": False,
            "signature_emitted": False,
        }
    return {
        "started_utc": _utc_iso(),
        "finished_utc": _utc_iso(),
        "symbols_requested": len(symbols),
        "symbols_selected": len(symbols),
        "symbols_fetched": 0,
        "symbols_unprobed": len(symbols),
        "requests_attempted": 0,
        "authenticated_http_successes": 0,
        "fanout_stopped_early": True,
        "provider_health": {**provider_health, **OPTIONAL_SOURCE_FIELDS},
        "provider_retry_delay_seconds": None,
        "trainer_consumable": False,
        "typed_missing_rows": len(symbols),
        "per_symbol_health": {
            symbol: {
                "observed": False,
                "orderbook_schema_valid": False,
                "ohlcv_schema_valid_timeframes": [],
                "typed_missing": True,
                "fresh": False,
                "committed": False,
                "receipt_present": False,
                **OPTIONAL_SOURCE_FIELDS,
            }
            for symbol in symbols
            if _validated_runtime_symbol(symbol) is not None
        },
        "rows": [],
        "durable_authorization_backoff": public_auth_state,
        **OPTIONAL_SOURCE_FIELDS,
    }


def build_payload(
    symbols: tuple[str, ...],
    *,
    fetch_symbol_limit: int | None,
    fetch_ohlcv: bool = True,
    ohlcv_timeframes: tuple[str, ...] = DEFAULT_OHLCV_TIMEFRAMES,
    ohlcv_symbol_limit: int | None = DEFAULT_OHLCV_SYMBOL_LIMIT,
    write_v2_redis: bool,
    ttl_seconds: int,
    timeout_seconds: float,
    max_rps: float,
    authorization_latch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del authorization_latch  # compatibility-only; durable Redis state is authoritative.
    api_key = _read_secret_value("COINAPI_API_KEY") or _read_secret_value("COINAPI_KEY")
    configured_rest_url = os.getenv("COINAPI_REST_URL", COINAPI_REST_BASE)
    try:
        rest_base_url = _validate_rest_base_url(configured_rest_url)
        endpoint_allowed = True
    except ValueError:
        rest_base_url = COINAPI_REST_BASE
        endpoint_allowed = False
    configured_exchange_id = os.getenv("COINAPI_PRIMARY_EXCHANGE_ID", "BINANCEFTS")
    exchange_id = _validated_exchange_id(configured_exchange_id)
    validated_timeout_seconds = _validated_finite_range(
        timeout_seconds,
        minimum=MIN_REST_TIMEOUT_SECONDS,
        maximum=MAX_REST_TIMEOUT_SECONDS,
    )
    validated_max_rps = _validated_finite_range(
        max_rps,
        minimum=MIN_REST_MAX_RPS,
        maximum=MAX_REST_MAX_RPS,
    )
    redis_client = _connect_redis() if write_v2_redis else None
    fetch: dict[str, Any] | None = None
    invalid_symbols = tuple(
        symbol for symbol in symbols if _validated_runtime_symbol(symbol) is None
    )
    auth_state: dict[str, Any] | None = None
    auth_state_exists: bool | None = None
    auth_state_write_result: str | None = None
    durable_auth_state_healthy: bool | None = None
    now_ns = time.time_ns()
    if api_key and write_v2_redis and redis_client is not None:
        if _env_bool(AUTH_LATCH_RESET_ENV, False):
            durable_auth_state_healthy = _clear_auth_state(
                redis_client,
                api_key=api_key,
            )
            os.environ.pop(AUTH_LATCH_RESET_ENV, None)
        auth_state_exists = _auth_state_record_exists(redis_client, api_key=api_key)
        auth_state = _load_auth_state(redis_client, api_key=api_key)
        if auth_state_exists is None:
            durable_auth_state_healthy = False
        elif auth_state_exists is True and auth_state is None:
            durable_auth_state_healthy = False
        elif durable_auth_state_healthy is None:
            durable_auth_state_healthy = True
    if invalid_symbols:
        fetch = _optional_unavailable_fetch(
            symbols,
            provider_health={
                "state": "OPTIONAL_CONFIGURATION_INVALID",
                "provider_error_class": "INVALID_RUNTIME_SYMBOL",
                "typed_missing": True,
                "trainer_consumable": False,
            },
        )
    elif not endpoint_allowed:
        fetch = _optional_unavailable_fetch(
            symbols,
            provider_health={
                "state": "OPTIONAL_CONFIGURATION_INVALID",
                "provider_error_class": "NON_ALLOWLISTED_ENDPOINT",
                "typed_missing": True,
                "trainer_consumable": False,
            },
        )
    elif exchange_id is None:
        fetch = _optional_unavailable_fetch(
            symbols,
            provider_health={
                "state": "OPTIONAL_CONFIGURATION_INVALID",
                "provider_error_class": "INVALID_PRIMARY_EXCHANGE_ID",
                "typed_missing": True,
                "trainer_consumable": False,
            },
        )
    elif validated_timeout_seconds is None:
        fetch = _optional_unavailable_fetch(
            symbols,
            provider_health={
                "state": "OPTIONAL_CONFIGURATION_INVALID",
                "provider_error_class": "INVALID_TIMEOUT_SECONDS",
                "typed_missing": True,
                "trainer_consumable": False,
            },
        )
    elif validated_max_rps is None:
        fetch = _optional_unavailable_fetch(
            symbols,
            provider_health={
                "state": "OPTIONAL_CONFIGURATION_INVALID",
                "provider_error_class": "INVALID_MAX_RPS",
                "typed_missing": True,
                "trainer_consumable": False,
            },
        )
    elif not api_key:
        fetch = _optional_unavailable_fetch(
            symbols,
            provider_health={
                "state": "OPTIONAL_NOT_CONFIGURED",
                "provider_error_class": "CREDENTIAL_NOT_CONFIGURED",
                "typed_missing": True,
                "trainer_consumable": False,
            },
        )
    elif write_v2_redis and redis_client is None:
        fetch = _optional_unavailable_fetch(
            symbols,
            provider_health={
                "state": "OPTIONAL_RETRY_STATE_UNAVAILABLE",
                "provider_error_class": "DURABLE_RETRY_STATE_UNAVAILABLE",
                "typed_missing": True,
                "trainer_consumable": False,
            },
        )
        durable_auth_state_healthy = False
    elif durable_auth_state_healthy is False:
        fetch = _optional_unavailable_fetch(
            symbols,
            provider_health={
                "state": "OPTIONAL_RETRY_STATE_INVALID",
                "provider_error_class": "DURABLE_RETRY_STATE_INVALID",
                "typed_missing": True,
                "trainer_consumable": False,
            },
        )
    elif auth_state is not None and now_ns < auth_state["next_probe_at_ns"]:
        fetch = _optional_unavailable_fetch(
            symbols,
            provider_health={
                "state": "OPTIONAL_AUTH_BACKOFF",
                "provider_error_class": auth_state["last_error_class"],
                "http_status": auth_state["last_http_status"],
                "typed_missing": True,
                "trainer_consumable": False,
            },
            authorization_state=auth_state,
        )
    else:
        fetch = fetch_for_symbols(
            symbols,
            api_key=api_key,
            rest_base_url=rest_base_url,
            exchange_id=exchange_id,
            fetch_symbol_limit=fetch_symbol_limit,
            fetch_ohlcv=fetch_ohlcv,
            ohlcv_timeframes=ohlcv_timeframes,
            ohlcv_symbol_limit=ohlcv_symbol_limit,
            timeout_seconds=validated_timeout_seconds,
            max_rps=validated_max_rps,
        )
        provider_health = fetch.get("provider_health")
        if isinstance(provider_health, dict):
            http_status = provider_health.get("http_status")
            error_class = provider_health.get("provider_error_class")
            if (
                type(http_status) is int
                and http_status in TERMINAL_PROVIDER_HTTP_STATUSES | {RATE_LIMITED_HTTP_STATUS}
                and type(error_class) is str
            ):
                next_state = _build_auth_state(
                    api_key=api_key,
                    http_status=http_status,
                    error_class=error_class,
                    prior_state=auth_state,
                    quota_metadata=provider_health.get("quota_metadata")
                    if isinstance(provider_health.get("quota_metadata"), dict)
                    else None,
                    now_ns=now_ns,
                )
                auth_state_write_result = (
                    _persist_auth_state(
                        redis_client,
                        api_key=api_key,
                        state=next_state,
                    )
                    if write_v2_redis and next_state is not None
                    else None
                )
                durable_auth_state_healthy = (
                    auth_state_write_result in {_AUTH_STATE_COMMITTED, _AUTH_STATE_CURRENT}
                    if write_v2_redis
                    else None
                )
                if next_state is not None:
                    fetch["durable_authorization_backoff"] = {
                        "failure_count": next_state["failure_count"],
                        "next_probe_at_ns": next_state["next_probe_at_ns"],
                        "retry_after_honored": next_state["retry_after_honored"],
                        "credential_fingerprint_emitted": False,
                        "signature_emitted": False,
                    }
        retry_state_required = (
            isinstance(provider_health, dict)
            and type(provider_health.get("http_status")) is int
            and provider_health["http_status"]
            in TERMINAL_PROVIDER_HTTP_STATUSES | {RATE_LIMITED_HTTP_STATUS}
        )
        if (
            _safe_int(fetch.get("authenticated_http_successes")) or 0
        ) > 0 and not retry_state_required:
            durable_auth_state_healthy = (
                _clear_auth_state(redis_client, api_key=api_key) if write_v2_redis else None
            )
    keys_written: list[str] = []
    if fetch is not None and write_v2_redis:
        keys_written = persist_to_v2_redis(
            redis_client,
            fetch,
            ttl_seconds=ttl_seconds,
            api_key=api_key,
        )
    rows_value = fetch.get("rows", []) if isinstance(fetch, dict) else []
    rows: list[Any] = rows_value if isinstance(rows_value, list) else []
    ok_count = 0
    ohlcv_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("orderbook_present") is True:
            ok_count += 1
        present_timeframes = row.get("ohlcv_present_timeframes")
        if isinstance(present_timeframes, list):
            ohlcv_count += len(present_timeframes)
    provider_health = fetch.get("provider_health") if isinstance(fetch, dict) else None
    has_provider_data = bool(ok_count or ohlcv_count)
    symbols_unprobed = (
        _safe_int(fetch.get("symbols_unprobed")) or 0 if isinstance(fetch, dict) else 0
    )
    typed_missing_rows = (
        _safe_int(fetch.get("typed_missing_rows")) or 0 if isinstance(fetch, dict) else 0
    )
    publication_stats = fetch.get("publication_stats") if isinstance(fetch, dict) else None
    redis_ack_failures = (
        int(publication_stats.get("redis_ack_failures") or 0)
        if isinstance(publication_stats, dict)
        else 0
    )
    integrity_rejections = (
        (_safe_int(publication_stats.get("older_rejected")) or 0)
        + (_safe_int(publication_stats.get("conflicts_quarantined")) or 0)
        if isinstance(publication_stats, dict)
        else 0
    )
    partial = bool(
        symbols_unprobed or typed_missing_rows or redis_ack_failures or integrity_rejections
    )
    fresh_samples = (
        _safe_int(publication_stats.get("fresh")) or 0 if isinstance(publication_stats, dict) else 0
    )
    committed_samples = (
        _safe_int(publication_stats.get("committed")) or 0
        if isinstance(publication_stats, dict)
        else 0
    )
    if isinstance(provider_health, dict) and not has_provider_data:
        provider_state = provider_health.get("state")
        if provider_state in {"PROVIDER_BLOCKED", "OPTIONAL_AUTH_BACKOFF"}:
            classification = "V2_COINAPI_REST_OPTIONAL_AUTH_UNAVAILABLE"
        elif provider_state == "RATE_LIMITED":
            classification = "V2_COINAPI_REST_OPTIONAL_RATE_LIMITED"
        elif provider_state == "OPTIONAL_NOT_CONFIGURED":
            classification = "V2_COINAPI_REST_OPTIONAL_NOT_CONFIGURED"
        elif provider_state in {
            "OPTIONAL_RETRY_STATE_UNAVAILABLE",
            "OPTIONAL_RETRY_STATE_INVALID",
        }:
            classification = "V2_COINAPI_REST_OPTIONAL_RETRY_STATE_UNAVAILABLE"
        elif provider_state == "OPTIONAL_CONFIGURATION_INVALID":
            classification = "V2_COINAPI_REST_OPTIONAL_CONFIGURATION_INVALID"
        else:
            classification = "V2_COINAPI_REST_OPTIONAL_TRANSIENT_UNAVAILABLE"
    elif has_provider_data and (partial or isinstance(provider_health, dict)):
        classification = "V2_COINAPI_REST_OPTIONAL_DEGRADED_PARTIAL"
    elif has_provider_data and fresh_samples > 0:
        classification = "V2_COINAPI_REST_OPTIONAL_CURRENT_RAW_QUARANTINE_AVAILABLE"
    elif has_provider_data:
        classification = "V2_COINAPI_REST_OPTIONAL_RAW_QUARANTINE_ONLY"
    else:
        classification = "V2_COINAPI_REST_OPTIONAL_TYPED_MISSING"
    heartbeat_keys = {
        "v2:quarantine:coinapi:rest:heartbeat",
        "v2:quarantine:coinapi:rest:ohlcv:heartbeat",
    }
    redis_status_healthy = heartbeat_keys.issubset(keys_written)
    raw_quarantine_publication_healthy = committed_samples > 0 and redis_ack_failures == 0
    current_data_publication_healthy = fresh_samples > 0 and redis_ack_failures == 0
    return {
        "worker_id": WORKER_ID,
        "schema_version": "v2_coinapi_rest_ingestor_status_v3",
        "classification": classification,
        "scope": "PAPER_ONLY_KEYED_MARKET_DATA",
        "generated_utc": _utc_iso(),
        "service_active": True,
        "service_healthy": redis_status_healthy if write_v2_redis else True,
        "source_data_healthy": current_data_publication_healthy,
        "symbols": list(symbols),
        "coinapi_exchange_id": exchange_id,
        "provider_identity_schema_version": PROVIDER_IDENTITY_SCHEMA_VERSION,
        "quarantine_namespace_version": "v4",
        "cadence_namespace_version": "v4",
        "legacy_namespace_reads_enabled": False,
        "legacy_namespace_migration_mode": "COLD_BOOTSTRAP_REQUIRED",
        "fetch_symbol_limit": fetch_symbol_limit,
        "fetch_ohlcv": bool(fetch_ohlcv),
        "ohlcv_timeframes": list(ohlcv_timeframes),
        "ohlcv_symbol_limit": ohlcv_symbol_limit,
        "fetch": fetch,
        "orderbooks_present_count": ok_count,
        "ohlcv_present_count": ohlcv_count,
        "provider_health": provider_health,
        "provider_data_available": has_provider_data,
        "provider_data_usable": False,
        "freshness_policy": (
            "ORDERBOOK_AUTHENTICATED_PRIOR_WS_CADENCE_AND_COMPLETED_BOUNDARY_OHLCV"
        ),
        "static_market_freshness_threshold_used": False,
        "per_symbol_health": (fetch.get("per_symbol_health") if isinstance(fetch, dict) else {}),
        "degraded_partial": classification == "V2_COINAPI_REST_OPTIONAL_DEGRADED_PARTIAL",
        "trainer_consumable": False,
        "typed_missing": (
            partial or not has_provider_data or bool(provider_health) or fresh_samples == 0
        ),
        "raw_provider_body_recorded": False,
        "v2_redis_write_enabled": bool(write_v2_redis),
        "redis_ok": redis_status_healthy if write_v2_redis else None,
        "status_publication_healthy": redis_status_healthy if write_v2_redis else None,
        "raw_quarantine_publication_healthy": (
            raw_quarantine_publication_healthy if write_v2_redis else None
        ),
        "publication_healthy": (current_data_publication_healthy if write_v2_redis else None),
        "current_data_commit_acked": (current_data_publication_healthy if write_v2_redis else None),
        "raw_quarantine_commit_acked": (
            raw_quarantine_publication_healthy if write_v2_redis else None
        ),
        "durable_auth_retry_state_healthy": durable_auth_state_healthy,
        "durable_auth_retry_write_state": auth_state_write_result,
        "credential_fingerprint_emitted": False,
        "auth_state_signature_emitted": False,
        "v2_redis_keys_written": keys_written,
        "v2_redis_keys_written_count": len(keys_written),
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "live_gate": "blocked_human_only",
        "runtime_mode": "LIVE_RAW_DATA_QUARANTINE_ONLY",
        "live_data_enabled": has_provider_data and endpoint_allowed,
        "live_decision_input_enabled": False,
        "trader_execution_enabled": False,
        "execution_live_symbols": [],
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        **OPTIONAL_SOURCE_FIELDS,
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def write_payload(payload: dict[str, Any], path: Path) -> bool:
    payload["status_file_write_healthy"] = True
    payload["status_file_write_failure_count"] = 0
    payload["status_file_write_error_classes"] = []
    payload["raw_status_file_error_recorded"] = False
    try:
        _atomic_write_json(path, payload)
    except OSError as exc:
        error_class = type(exc).__name__
        payload["status_file_write_healthy"] = False
        payload["status_file_write_failure_count"] = 1
        payload["status_file_write_error_classes"] = [
            error_class[:80] if error_class.isidentifier() else "OSError"
        ]
        payload["raw_status_file_error_recorded"] = False
        print(
            json.dumps(
                {
                    "status_file_write_healthy": False,
                    "status_file_write_error_class": payload["status_file_write_error_classes"][0],
                    "raw_status_file_error_recorded": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--fetch-symbol-limit", type=int, default=None)
    parser.add_argument("--fetch-ohlcv", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--ohlcv-timeframes", default=",".join(DEFAULT_OHLCV_TIMEFRAMES))
    parser.add_argument("--ohlcv-symbol-limit", type=int, default=DEFAULT_OHLCV_SYMBOL_LIMIT)
    parser.add_argument("--write-v2-redis", action="store_true")
    parser.add_argument("--v2-redis-ttl-seconds", type=int, default=900)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--max-rps", type=float, default=0.5)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    symbols = tuple(
        resolve_symbols(
            explicit=args.symbols,
            smoke_test=bool(args.smoke_test),
            include_baseline=True,
        )
    )
    if args.loop and args.once:
        print("ERROR: --loop and --once are mutually exclusive", file=sys.stderr)
        return 2
    ohlcv_timeframes = tuple(
        tf.strip()
        for tf in str(args.ohlcv_timeframes or "").split(",")
        if tf.strip() and tf.strip() in COINAPI_PERIOD_MAP
    )
    while True:
        payload = build_payload(
            symbols,
            fetch_symbol_limit=args.fetch_symbol_limit,
            fetch_ohlcv=bool(args.fetch_ohlcv),
            ohlcv_timeframes=ohlcv_timeframes or DEFAULT_OHLCV_TIMEFRAMES,
            ohlcv_symbol_limit=args.ohlcv_symbol_limit,
            write_v2_redis=bool(args.write_v2_redis),
            ttl_seconds=max(60, int(args.v2_redis_ttl_seconds)),
            timeout_seconds=args.timeout_seconds,
            max_rps=args.max_rps,
        )
        write_payload(payload, args.out)
        sys.stdout.write(
            json.dumps(
                {
                    "classification": payload["classification"],
                    "orderbooks_present_count": payload["orderbooks_present_count"],
                    "ohlcv_present_count": payload["ohlcv_present_count"],
                    "v2_redis_keys_written_count": payload["v2_redis_keys_written_count"],
                    "redis_ok": payload["redis_ok"],
                }
            )
            + "\n"
        )
        sys.stdout.flush()
        if not args.loop:
            return 0
        provider_delay = None
        fetch = payload.get("fetch")
        if isinstance(fetch, dict):
            provider_delay = _safe_float(fetch.get("provider_retry_delay_seconds"))
        time.sleep(max(30.0, float(args.interval_seconds), provider_delay or 0.0))


if __name__ == "__main__":
    raise SystemExit(main())
