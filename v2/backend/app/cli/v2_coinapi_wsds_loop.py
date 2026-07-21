"""V2 CoinAPI WSDS read-only ingestor loop.

This worker is intentionally V2-only and paper/shadow-only. It never
writes legacy ``msnap:*`` or ``metrics:*`` keys. It only connects when an
operator explicitly opts in with ``V2_COINAPI_WSDS_OPT_IN=true`` and a
CoinAPI key is available by env/local-secret file. Otherwise it runs as a
truthful blocked status publisher so supervision can see why WSDS is not
connected.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import random
import re
import sys
import tempfile
import time
import urllib.parse
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from math import isfinite
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_ingestors.coinapi_wsds import (
    DEFAULT_TIMEFRAMES,
    PROVIDER_IDENTITY_SCHEMA_VERSION,
    WSDS_RAW_QUARANTINE_FIELDS,
    WSDS_RAW_TRUST_BLOCK_REASONS,
    datetime_epoch_ns,
    iso_utc_ns,
    normalize_wsds_snapshot,
    parse_coinapi_symbol_id,
    parse_provider_timestamp,
    validate_wsds_quarantine_payload,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

websockets: Any
try:
    import websockets as _websockets

    websockets = _websockets
except Exception:  # pragma: no cover - surfaced in status payload
    websockets = None


WORKER_ID = "v2_coinapi_wsds_loop"
OPT_IN_ENV_VAR = "V2_COINAPI_WSDS_OPT_IN"
DEFAULT_WS_URL = "wss://ws.coinapi.io:443/v1/"
DEFAULT_STATUS_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_coinapi_wsds/latest/v2_coinapi_wsds_status.json"
)
DEFAULT_PUBLIC_PAYLOAD_PATH = Path(
    "v2/frontend/public/v2_coinapi_wsds/latest/operator_dashboard_payload.json"
)
DEFAULT_WORKLOG_PATH = Path(
    "claude_worklog/final_readiness/v2_coinapi_wsds_persistent_readonly_stream/latest/v2_coinapi_wsds_status.json"
)
DEFAULT_SECRET_PATHS = (
    Path(".local_secrets/legacy.env"),
    Path(".local_secrets/live_credentials.env"),
    Path("v2/.env.local"),
)
TERMINAL_PROVIDER_HTTP_STATUSES = frozenset({401, 403})
RATE_LIMITED_HTTP_STATUS = 429
TERMINAL_PROVIDER_ERROR_CLASSES = frozenset(
    {
        "AUTHENTICATION_REJECTED",
        "AUTHORIZATION_REJECTED",
        "ENTITLEMENT_REJECTED",
        "QUOTA_OR_SUBSCRIPTION_EXHAUSTED",
        "PROVIDER_POLICY_REJECTED",
    }
)
DURABLE_PROVIDER_ERROR_CLASSES = TERMINAL_PROVIDER_ERROR_CLASSES | {"RATE_LIMITED"}
DURABLE_NO_HTTP_ERROR_CLASSES = DURABLE_PROVIDER_ERROR_CLASSES | {
    "CONNECTED_NO_DATA",
    "TRANSIENT_UNAVAILABLE",
}
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
        "absence_blocks_trainer",
        "optional_enrichment",
        "required_for_trainer_admission",
        "system_availability_blocking",
        "trainer_consumable",
    }
)
TRANSIENT_BACKOFF_BASE_SECONDS = 1.0
TRANSIENT_BACKOFF_CAP_SECONDS = 60.0
TRANSIENT_BACKOFF_JITTER_FRACTION = 0.25
MAX_WS_MESSAGE_BYTES = 1_048_576
MAX_WS_JSON_DEPTH = 64
MAX_WS_JSON_ITEMS = 100_000
MAX_STATE_JSON_BYTES = 32 * 1024
MAX_STATE_IDENTITY_BYTES = 64
MAX_REDIS_QUARANTINE_JSON_BYTES = MAX_WS_MESSAGE_BYTES
UTF8_COUNT_CHUNK_CHARACTERS = 64 * 1024
MAX_WS_RUNTIME_SECONDS = 86_400.0
MAX_WS_HEARTBEAT_SECONDS = 3_600.0
MAX_WS_MESSAGES_PER_SESSION = 10_000_000
MAX_WS_SYMBOLS = 100_000
RUNTIME_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
OPTIONAL_SOURCE_FIELDS = {
    "optional_enrichment": True,
    "required_for_trainer_admission": False,
    "system_availability_blocking": False,
    "absence_blocks_trainer": False,
}
AUTH_LATCH_SCHEMA_VERSION = "v2_coinapi_optional_auth_backoff_v1"
AUTH_LATCH_RESET_ENV = "V2_COINAPI_AUTH_LATCH_RESET"
AUTH_BACKOFF_BASE_SECONDS = 60.0
AUTH_BACKOFF_MAX_SECONDS = 6 * 60 * 60.0
MIN_OPTIONAL_REPROBE_SECONDS = 30.0
AUTH_LATCH_KEY_PREFIX = "v2:quarantine:coinapi:wsds:auth_latch:v1:"
WS_QUARANTINE_HEARTBEAT_KEY = "v2:quarantine:coinapi:wsds:heartbeat"
WS_FENCE_KEY_TEMPLATE = "v2:quarantine:coinapi:wsds:fence:v4:{coinapi_symbol_id}:{symbol}"
WS_DATA_KEY_TEMPLATE = "v2:quarantine:coinapi:wsds:raw:v4:{coinapi_symbol_id}:{symbol}"
WS_CONFLICT_KEY_TEMPLATE = (
    "v2:quarantine:coinapi:wsds:conflict:v4:" "{coinapi_symbol_id}:{symbol}:{event_ns}:{digest}"
)
WS_CADENCE_KEY_TEMPLATE = (
    "v2:quarantine:coinapi:wsds:cadence:v4:" "{credential_fingerprint}:{coinapi_symbol_id}:{symbol}"
)
WS_CADENCE_SCHEMA_VERSION = "v2_coinapi_wsds_authenticated_cadence_v2"
WS_PROVISIONAL_CADENCE_KEY_TEMPLATE = (
    "v2:quarantine:coinapi:wsds:cadence_provisional:v3:"
    "{credential_fingerprint}:{coinapi_symbol_id}:{symbol}"
)
WS_PROVISIONAL_CADENCE_SCHEMA_VERSION = "v2_coinapi_wsds_authenticated_provisional_cadence_v2"
CADENCE_BOOTSTRAP_SAMPLE_COUNT = 3
_FENCE_COMMITTED = "COMMITTED_NEWER"
_FENCE_DUPLICATE = "DUPLICATE_NO_REFRESH"
_FENCE_OLDER = "REJECTED_OLDER_NO_REFRESH"
_FENCE_CONFLICT = "CONFLICT_QUARANTINED"
_FENCE_CONFLICT_DUPLICATE = "CONFLICT_DUPLICATE_NO_REFRESH"
_FENCE_ERROR = "REDIS_ACK_INVALID"
_CADENCE_COMMITTED = "CADENCE_COMMITTED_NEWER"
_CADENCE_CURRENT = "CADENCE_ALREADY_CURRENT"
_CADENCE_OLDER = "CADENCE_REJECTED_OLDER"
_CADENCE_CONFLICT = "CADENCE_EQUAL_EVENT_CONFLICT"
_CADENCE_ERROR = "CADENCE_REDIS_ACK_INVALID"
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
   or not payload_limit or payload_limit <= 0 or payload_limit > 1048576
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
_ATOMIC_CADENCE_LUA = r"""
-- COINAPI_ATOMIC_CADENCE_BOUNDED_V2
local key_type = redis.call('TYPE', KEYS[1])['ok']
if key_type ~= 'none' and key_type ~= 'hash' then
  return {'CADENCE_REDIS_ACK_INVALID', 0}
end

local incoming_event = ARGV[1]
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
if not incoming_event or not incoming_payload
   or not identity_limit or identity_limit <= 0 or identity_limit > 64
   or identity_limit ~= math.floor(identity_limit)
   or not payload_limit or payload_limit <= 0 or payload_limit > 32768
   or payload_limit ~= math.floor(payload_limit)
   or string.len(incoming_event) <= 0 or string.len(incoming_event) > identity_limit
   or string.len(incoming_payload) <= 0 or string.len(incoming_payload) > payload_limit
   or not is_decimal(incoming_event) then
  return {'CADENCE_REDIS_ACK_INVALID', 0}
end

local current_event = nil
local current_payload = nil
local current_payload_sha1 = nil
if key_type == 'hash' then
  current_event = bounded_hget(KEYS[1], 'last_event_ns', identity_limit)
  current_payload = bounded_hget(KEYS[1], 'payload', payload_limit)
  current_payload_sha1 = bounded_hget(KEYS[1], 'payload_sha1', identity_limit)
  if not current_event or not current_payload or not current_payload_sha1 then
    return {'CADENCE_REDIS_ACK_INVALID', 0}
  end
end
if (current_payload and redis.sha1hex(current_payload) ~= current_payload_sha1)
   or (current_event and not current_payload)
   or (current_payload and not current_event)
   or (current_event and not is_decimal(current_event)) then
  return {'CADENCE_REDIS_ACK_INVALID', 0}
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
    return {'CADENCE_REJECTED_OLDER', 0}
  end
  if ordering == 0 then
    if current_payload == incoming_payload then
      return {'CADENCE_ALREADY_CURRENT', 0}
    end
    return {'CADENCE_EQUAL_EVENT_CONFLICT', 0}
  end
end

redis.call(
  'HSET', KEYS[1],
  'last_event_ns', incoming_event,
  'payload', incoming_payload,
  'payload_sha1', redis.sha1hex(incoming_payload)
)
redis.call('PERSIST', KEYS[1])
local stored_event = bounded_hget(KEYS[1], 'last_event_ns', identity_limit)
local stored_payload = bounded_hget(KEYS[1], 'payload', payload_limit)
local stored_payload_sha1 = bounded_hget(KEYS[1], 'payload_sha1', identity_limit)
local stored_ttl = redis.call('TTL', KEYS[1])
if stored_event ~= incoming_event or stored_payload ~= incoming_payload
   or stored_payload_sha1 ~= redis.sha1hex(incoming_payload)
   or stored_ttl ~= -1 then
  return {'CADENCE_REDIS_ACK_INVALID', 0}
end
return {'CADENCE_COMMITTED_NEWER', 1}
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


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _read_secret_value(name: str) -> str:
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
                return value.strip().strip('"').strip("'")
    return ""


def _connect_redis() -> Any | None:
    try:
        import redis

        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        ping_ack = client.ping()
        return client if type(ping_ack) is bool and ping_ack is True else None
    except Exception:
        return None


def _validated_runtime_symbol(value: Any) -> str | None:
    if type(value) is not str or value != value.strip() or not value.isascii():
        return None
    return value if RUNTIME_SYMBOL_RE.fullmatch(value) is not None else None


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


def _runtime_config_error(args: argparse.Namespace) -> str | None:
    numeric_ranges = (
        (
            "heartbeat_interval_seconds",
            getattr(args, "heartbeat_interval_seconds", 30.0),
            0.001,
            MAX_WS_HEARTBEAT_SECONDS,
        ),
        (
            "max_seconds_per_session",
            getattr(args, "max_seconds_per_session", 600.0),
            0.001,
            MAX_WS_RUNTIME_SECONDS,
        ),
        (
            "total_seconds",
            getattr(args, "total_seconds", 20.0),
            0.001,
            MAX_WS_RUNTIME_SECONDS,
        ),
    )
    for name, value, minimum, maximum in numeric_ranges:
        if _validated_finite_range(value, minimum=minimum, maximum=maximum) is None:
            return f"INVALID_{name.upper()}"
    integer_ranges = (
        ("ttl_seconds", getattr(args, "ttl_seconds", 300), 1, 86_400),
        (
            "max_messages_per_session",
            getattr(args, "max_messages_per_session", 5_000),
            1,
            MAX_WS_MESSAGES_PER_SESSION,
        ),
        ("max_symbols", getattr(args, "max_symbols", 0), 0, MAX_WS_SYMBOLS),
    )
    for name, value, minimum, maximum in integer_ranges:
        if type(value) is not int or not (minimum <= value <= maximum):
            return f"INVALID_{name.upper()}"
    return None


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


def _safe_set_json(redis_client: Any, key: str, payload: Any, *, ex: int) -> bool:
    if redis_client is None:
        return False
    if not str(key).startswith("v2:"):
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
        max_depth=MAX_WS_JSON_DEPTH,
        max_items=MAX_WS_JSON_ITEMS,
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
        or not key.startswith("v2:")
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
        and payload.get("canonical_receipt_resolver_present") is False
        and payload.get("available_at") is None
        and payload.get("feature_cutoff") is None
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


def _expected_ws_quarantine_keys(
    payload: dict[str, Any],
) -> tuple[str, str, str, str] | None:
    symbol = _validated_runtime_symbol(payload.get("symbol"))
    coinapi_symbol_id = payload.get("coinapi_symbol_id")
    identity = parse_coinapi_symbol_id(coinapi_symbol_id)
    event_ns = payload.get("source_event_ts_ns")
    if (
        symbol is None
        or identity is None
        or identity[2] != symbol
        or set(payload) != WSDS_RAW_QUARANTINE_FIELDS
        or payload.get("schema_version") != "v2_coinapi_wsds_raw_quarantine_v3"
        or payload.get("provider_identity_schema_version") != PROVIDER_IDENTITY_SCHEMA_VERSION
        or payload.get("coinapi_exchange_id") != identity[0]
        or payload.get("coinapi_market_type") != identity[1]
        or payload.get("source") != "coinapi_wsds"
        or payload.get("producer") != "coinapi_wsds"
        or payload.get("trust_block_reasons") != list(WSDS_RAW_TRUST_BLOCK_REASONS)
        or _raw_payload_contains_forbidden_authority_field(payload)
        or not _raw_quarantine_authority_flags_valid(payload)
        or not validate_wsds_quarantine_payload(payload)
        or type(event_ns) is not int
        or event_ns < 0
    ):
        return None
    digest = _provider_content_digest(payload)
    if digest is None:
        return None
    return (
        WS_FENCE_KEY_TEMPLATE.format(
            coinapi_symbol_id=coinapi_symbol_id,
            symbol=symbol,
        ),
        WS_DATA_KEY_TEMPLATE.format(
            coinapi_symbol_id=coinapi_symbol_id,
            symbol=symbol,
        ),
        WS_CONFLICT_KEY_TEMPLATE.format(
            coinapi_symbol_id=coinapi_symbol_id,
            symbol=symbol,
            event_ns=event_ns,
            digest=digest,
        ),
        str(event_ns),
    )


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
    """Atomically enforce a decimal nanosecond fence without float conversion."""

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
    expected = _expected_ws_quarantine_keys(payload)
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
    if type(commit_payload) is not dict or _expected_ws_quarantine_keys(commit_payload) != expected:
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


def _atomic_persist_authenticated_cadence_basis(
    redis_client: Any,
    *,
    key: str,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
    basis: dict[str, Any],
) -> str:
    if redis_client is None:
        return _CADENCE_ERROR
    if _validated_runtime_symbol(symbol) is None:
        return _CADENCE_ERROR
    expected_key = _cadence_state_key(
        symbol=symbol,
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
    )
    if expected_key is None or key != expected_key:
        raise ValueError("cadence basis key does not match the exact symbol namespace")
    validated = _validated_cadence_basis(
        basis,
        symbol=symbol,
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
    )
    if validated is None:
        return _CADENCE_ERROR
    existing = _exact_key_exists(redis_client, key)
    if (
        existing is True
        and _load_authenticated_cadence_basis(
            redis_client,
            symbol=symbol,
            coinapi_symbol_id=coinapi_symbol_id,
            api_key=api_key,
        )
        is None
    ):
        return _CADENCE_ERROR
    serialized = _canonical_json(validated)
    event_ns = validated.get("last_event_ns")
    if (
        serialized is None
        or not _utf8_length_within_limit(serialized, max_bytes=MAX_STATE_JSON_BYTES)
        or _exact_nonnegative_int(event_ns) is None
    ):
        return _CADENCE_ERROR
    try:
        result = redis_client.eval(
            _ATOMIC_CADENCE_LUA,
            1,
            key,
            str(event_ns),
            serialized,
            MAX_STATE_IDENTITY_BYTES,
            MAX_STATE_JSON_BYTES,
        )
    except Exception:
        return _CADENCE_ERROR
    if type(result) is not list or len(result) != 2:
        return _CADENCE_ERROR
    status = _decode_exact_text(result[0])
    count = result[1]
    expected_counts = {
        _CADENCE_COMMITTED: 1,
        _CADENCE_CURRENT: 0,
        _CADENCE_OLDER: 0,
        _CADENCE_CONFLICT: 0,
        _CADENCE_ERROR: 0,
    }
    if type(count) is not int or status not in expected_counts:
        return _CADENCE_ERROR
    if count != expected_counts[status]:
        return _CADENCE_ERROR
    return status


def _read_persistent_cadence_payload(redis_client: Any, key: str) -> Any | None:
    if redis_client is None:
        return None
    prefix = "v2:quarantine:coinapi:wsds:cadence:v4:"
    remainder = key.removeprefix(prefix) if type(key) is str else ""
    parts = remainder.split(":")
    fingerprint, coinapi_symbol_id, symbol = parts if len(parts) == 3 else ("", "", "")
    identity = parse_coinapi_symbol_id(coinapi_symbol_id)
    if (
        len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
        or _validated_runtime_symbol(symbol) is None
        or identity is None
        or identity[2] != symbol
        or key
        != WS_CADENCE_KEY_TEMPLATE.format(
            credential_fingerprint=fingerprint,
            coinapi_symbol_id=coinapi_symbol_id,
            symbol=symbol,
        )
    ):
        raise ValueError("cadence state reads require the exact quarantine namespace")
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
    if (
        not isinstance(candidate, dict)
        or _exact_nonnegative_int(candidate.get("last_event_ns")) is None
        or str(candidate["last_event_ns"]) != stored_event
    ):
        return None
    return candidate


def _safe_pttl_ms(redis_client: Any, key: str) -> int | None:
    if redis_client is None:
        return None
    if not key.startswith("v2:quarantine:coinapi:"):
        raise ValueError("CoinAPI TTL reads require the quarantine namespace")
    try:
        value = redis_client.pttl(key)
    except Exception:
        return None
    if type(value) is not int or value < -2:
        return None
    return value


def _exact_key_exists(redis_client: Any, key: str) -> bool | None:
    if redis_client is None or type(key) is not str or not key.startswith("v2:quarantine:coinapi:"):
        return None
    try:
        value = redis_client.exists(key)
    except Exception:
        return None
    return value == 1 if type(value) is int and value in {0, 1} else None


def _exact_nonnegative_int(value: Any, *, positive: bool = False) -> int | None:
    if type(value) is not int or value < 0 or (positive and value == 0):
        return None
    return value


def _cadence_signature(api_key: str, unsigned_basis: dict[str, Any]) -> str | None:
    if type(api_key) is not str or not api_key:
        return None
    serialized = _canonical_json(unsigned_basis)
    if serialized is None:
        return None
    material = b"coinapi-wsds-cadence-v1\x00" + serialized.encode("ascii")
    return hmac.new(api_key.encode("utf-8"), material, hashlib.sha256).hexdigest()


def _validated_cadence_basis(
    candidate: Any,
    *,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
) -> dict[str, Any] | None:
    identity = parse_coinapi_symbol_id(coinapi_symbol_id)
    if (
        not isinstance(candidate, dict)
        or _validated_runtime_symbol(symbol) is None
        or identity is None
        or identity[2] != symbol
    ):
        return None
    required_keys = {
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
    if set(candidate) != required_keys:
        return None
    if (
        candidate.get("schema_version") != WS_CADENCE_SCHEMA_VERSION
        or candidate.get("provider_identity_schema_version") != PROVIDER_IDENTITY_SCHEMA_VERSION
        or candidate.get("symbol") != symbol
        or candidate.get("coinapi_symbol_id") != coinapi_symbol_id
        or candidate.get("coinapi_exchange_id") != identity[0]
        or candidate.get("coinapi_market_type") != identity[1]
        or type(candidate.get("generated_at")) is not str
        or parse_provider_timestamp(candidate.get("generated_at")) is None
    ):
        return None
    positive_fields = (
        "sample_count",
        "event_cadence_ns",
        "provider_cadence_ns",
        "arrival_cadence_ns",
    )
    nonnegative_fields = (
        "max_source_lag_ns",
        "max_arrival_lag_ns",
        "last_event_ns",
        "last_provider_received_ns",
        "last_observed_ns",
    )
    if any(
        _exact_nonnegative_int(candidate.get(field), positive=True) is None
        for field in positive_fields
    ) or any(_exact_nonnegative_int(candidate.get(field)) is None for field in nonnegative_fields):
        return None
    if candidate["sample_count"] < CADENCE_BOOTSTRAP_SAMPLE_COUNT:
        return None
    if not (
        candidate["last_event_ns"]
        <= candidate["last_provider_received_ns"]
        <= candidate["last_observed_ns"]
    ):
        return None
    signature = candidate.get("signature")
    if (
        type(signature) is not str
        or len(signature) != 64
        or not signature.isascii()
        or any(character not in "0123456789abcdef" for character in signature)
    ):
        return None
    unsigned = {key: value for key, value in candidate.items() if key != "signature"}
    expected = _cadence_signature(api_key, unsigned)
    if expected is None or not hmac.compare_digest(signature, expected):
        return None
    return dict(candidate)


def _load_authenticated_cadence_basis(
    redis_client: Any,
    *,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
) -> dict[str, Any] | None:
    key = _cadence_state_key(
        symbol=symbol,
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
    )
    if key is None:
        return None
    return _validated_cadence_basis(
        _read_persistent_cadence_payload(redis_client, key),
        symbol=symbol,
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
    )


def _build_authenticated_cadence_basis(
    samples: list[tuple[int, int, int]],
    *,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
) -> dict[str, Any] | None:
    identity = parse_coinapi_symbol_id(coinapi_symbol_id)
    if (
        len(samples) < CADENCE_BOOTSTRAP_SAMPLE_COUNT
        or _validated_runtime_symbol(symbol) is None
        or identity is None
        or identity[2] != symbol
    ):
        return None
    if any(type(value) is not int or value < 0 for sample in samples for value in sample):
        return None
    if any(not (event <= received <= observed) for event, received, observed in samples):
        return None
    pairs = zip(samples, samples[1:], strict=False)
    deltas = [
        (
            right[0] - left[0],
            right[1] - left[1],
            right[2] - left[2],
        )
        for left, right in pairs
    ]
    event_deltas = [delta[0] for delta in deltas]
    provider_deltas = [delta[1] for delta in deltas]
    arrival_deltas = [delta[2] for delta in deltas]
    if any(delta <= 0 for delta in (*event_deltas, *provider_deltas, *arrival_deltas)):
        return None
    source_lags = [received - event for event, received, _ in samples]
    arrival_lags = [observed - received for _, received, observed in samples]

    def upper_median(values: list[int]) -> int:
        ordered = sorted(values)
        return ordered[len(ordered) // 2]

    unsigned: dict[str, Any] = {
        "schema_version": WS_CADENCE_SCHEMA_VERSION,
        "provider_identity_schema_version": PROVIDER_IDENTITY_SCHEMA_VERSION,
        "symbol": symbol,
        "coinapi_symbol_id": coinapi_symbol_id,
        "coinapi_exchange_id": identity[0],
        "coinapi_market_type": identity[1],
        "sample_count": len(samples),
        "event_cadence_ns": upper_median(event_deltas),
        "provider_cadence_ns": upper_median(provider_deltas),
        "arrival_cadence_ns": upper_median(arrival_deltas),
        "max_source_lag_ns": max(source_lags),
        "max_arrival_lag_ns": max(arrival_lags),
        "last_event_ns": samples[-1][0],
        "last_provider_received_ns": samples[-1][1],
        "last_observed_ns": samples[-1][2],
        "generated_at": _utc_iso(),
    }
    signature = _cadence_signature(api_key, unsigned)
    if signature is None:
        return None
    return {**unsigned, "signature": signature}


def _provisional_cadence_signature(
    api_key: str,
    unsigned: dict[str, Any],
) -> str | None:
    if type(api_key) is not str or not api_key:
        return None
    serialized = _canonical_json(unsigned)
    if serialized is None:
        return None
    material = b"coinapi-wsds-provisional-cadence-v1\x00" + serialized.encode("ascii")
    return hmac.new(api_key.encode("utf-8"), material, hashlib.sha256).hexdigest()


def _build_provisional_cadence_payload(
    samples: list[tuple[int, int, int]],
    *,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
) -> dict[str, Any] | None:
    identity = parse_coinapi_symbol_id(coinapi_symbol_id)
    if (
        _validated_runtime_symbol(symbol) is None
        or identity is None
        or identity[2] != symbol
        or not samples
        or len(samples) > CADENCE_BOOTSTRAP_SAMPLE_COUNT
        or any(type(value) is not int or value < 0 for sample in samples for value in sample)
        or any(not (event <= received <= observed) for event, received, observed in samples)
        or any(
            not all(
                right_value > left_value
                for left_value, right_value in zip(left, right, strict=True)
            )
            for left, right in zip(samples, samples[1:], strict=False)
        )
    ):
        return None
    unsigned: dict[str, Any] = {
        "schema_version": WS_PROVISIONAL_CADENCE_SCHEMA_VERSION,
        "provider_identity_schema_version": PROVIDER_IDENTITY_SCHEMA_VERSION,
        "symbol": symbol,
        "coinapi_symbol_id": coinapi_symbol_id,
        "coinapi_exchange_id": identity[0],
        "coinapi_market_type": identity[1],
        "sample_count": len(samples),
        "samples": [list(sample) for sample in samples],
        "last_event_ns": samples[-1][0],
        "generated_at": _utc_iso(),
    }
    signature = _provisional_cadence_signature(api_key, unsigned)
    return {**unsigned, "signature": signature} if signature is not None else None


def _validated_provisional_cadence_payload(
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
        "samples",
        "last_event_ns",
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
        or candidate.get("schema_version") != WS_PROVISIONAL_CADENCE_SCHEMA_VERSION
        or candidate.get("provider_identity_schema_version") != PROVIDER_IDENTITY_SCHEMA_VERSION
        or candidate.get("symbol") != symbol
        or candidate.get("coinapi_symbol_id") != coinapi_symbol_id
        or candidate.get("coinapi_exchange_id") != identity[0]
        or candidate.get("coinapi_market_type") != identity[1]
        or type(candidate.get("sample_count")) is not int
        or not (1 <= candidate["sample_count"] <= CADENCE_BOOTSTRAP_SAMPLE_COUNT)
        or type(candidate.get("samples")) is not list
        or len(candidate["samples"]) != candidate["sample_count"]
        or type(candidate.get("generated_at")) is not str
        or parse_provider_timestamp(candidate.get("generated_at")) is None
    ):
        return None
    samples: list[tuple[int, int, int]] = []
    for sample in candidate["samples"]:
        if (
            type(sample) is not list
            or len(sample) != 3
            or any(type(value) is not int or value < 0 for value in sample)
            or not (sample[0] <= sample[1] <= sample[2])
        ):
            return None
        samples.append((sample[0], sample[1], sample[2]))
    if any(
        not all(
            right_value > left_value for left_value, right_value in zip(left, right, strict=True)
        )
        for left, right in zip(samples, samples[1:], strict=False)
    ):
        return None
    if candidate.get("last_event_ns") != samples[-1][0]:
        return None
    signature = candidate.get("signature")
    if (
        type(signature) is not str
        or len(signature) != 64
        or any(character not in "0123456789abcdef" for character in signature)
    ):
        return None
    unsigned = {key: value for key, value in candidate.items() if key != "signature"}
    expected = _provisional_cadence_signature(api_key, unsigned)
    if expected is None or not hmac.compare_digest(signature, expected):
        return None
    return dict(candidate)


def _read_provisional_cadence_payload(
    redis_client: Any,
    *,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
) -> dict[str, Any] | None:
    if redis_client is None or _validated_runtime_symbol(symbol) is None:
        return None
    key = _cadence_state_key(
        symbol=symbol,
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
        provisional=True,
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
    validated = _validated_provisional_cadence_payload(
        candidate,
        symbol=symbol,
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
    )
    if validated is None or str(validated["last_event_ns"]) != stored_event:
        return None
    return validated


def _persist_provisional_cadence_payload(
    redis_client: Any,
    *,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
    payload: dict[str, Any],
) -> str:
    validated = _validated_provisional_cadence_payload(
        payload,
        symbol=symbol,
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
    )
    if redis_client is None or validated is None:
        return _CADENCE_ERROR
    key = _cadence_state_key(
        symbol=symbol,
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
        provisional=True,
    )
    if key is None:
        return _CADENCE_ERROR
    existing = _exact_key_exists(redis_client, key)
    if (
        existing is True
        and _read_provisional_cadence_payload(
            redis_client,
            symbol=symbol,
            coinapi_symbol_id=coinapi_symbol_id,
            api_key=api_key,
        )
        is None
    ):
        return _CADENCE_ERROR
    serialized = _canonical_json(validated)
    if serialized is None or len(serialized.encode("ascii")) > MAX_STATE_JSON_BYTES:
        return _CADENCE_ERROR
    try:
        result = redis_client.eval(
            _ATOMIC_CADENCE_LUA,
            1,
            key,
            str(validated["last_event_ns"]),
            serialized,
            MAX_STATE_IDENTITY_BYTES,
            MAX_STATE_JSON_BYTES,
        )
    except Exception:
        return _CADENCE_ERROR
    if type(result) is not list or len(result) != 2:
        return _CADENCE_ERROR
    status = _decode_exact_text(result[0])
    count = result[1]
    expected_counts = {
        _CADENCE_COMMITTED: 1,
        _CADENCE_CURRENT: 0,
        _CADENCE_OLDER: 0,
        _CADENCE_CONFLICT: 0,
        _CADENCE_ERROR: 0,
    }
    if type(count) is not int or status not in expected_counts:
        return _CADENCE_ERROR
    return status if count == expected_counts[status] else _CADENCE_ERROR


def _delete_provisional_cadence(
    redis_client: Any,
    *,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
) -> bool:
    if redis_client is None or _validated_runtime_symbol(symbol) is None:
        return False
    key = _cadence_state_key(
        symbol=symbol,
        coinapi_symbol_id=coinapi_symbol_id,
        api_key=api_key,
        provisional=True,
    )
    if key is None:
        return False
    try:
        acknowledged = redis_client.delete(key)
    except Exception:
        return False
    return type(acknowledged) is int and acknowledged in {0, 1}


def _cadence_freshness_budget_ns(basis: dict[str, Any]) -> int | None:
    values = [
        _exact_nonnegative_int(basis.get("event_cadence_ns"), positive=True),
        _exact_nonnegative_int(basis.get("provider_cadence_ns"), positive=True),
        _exact_nonnegative_int(basis.get("arrival_cadence_ns"), positive=True),
        _exact_nonnegative_int(basis.get("max_source_lag_ns")),
        _exact_nonnegative_int(basis.get("max_arrival_lag_ns")),
    ]
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _sample_fresh_against_basis(
    basis: dict[str, Any],
    *,
    session_anchor_ns: int,
    event_ns: int,
    provider_received_ns: int,
    observed_ns: int,
) -> tuple[bool, int | None]:
    budget = _cadence_freshness_budget_ns(basis)
    if budget is None or budget <= 0:
        return False, budget
    last_event = _exact_nonnegative_int(basis.get("last_event_ns"))
    last_received = _exact_nonnegative_int(basis.get("last_provider_received_ns"))
    last_observed = _exact_nonnegative_int(basis.get("last_observed_ns"))
    if last_event is None or last_received is None or last_observed is None:
        return False, budget
    if not (
        event_ns >= session_anchor_ns
        and provider_received_ns >= session_anchor_ns
        and event_ns <= provider_received_ns <= observed_ns
        and event_ns > last_event
        and provider_received_ns > last_received
        and observed_ns > last_observed
    ):
        return False, budget
    event_delta = event_ns - last_event
    provider_delta = provider_received_ns - last_received
    arrival_delta = observed_ns - last_observed
    source_lag = provider_received_ns - event_ns
    arrival_lag = observed_ns - provider_received_ns
    source_budget = max(basis["max_source_lag_ns"], basis["event_cadence_ns"])
    arrival_budget = max(basis["max_arrival_lag_ns"], basis["arrival_cadence_ns"])
    return (
        source_lag <= source_budget
        and arrival_lag <= arrival_budget
        and observed_ns - event_ns <= budget
        and abs(provider_delta - event_delta) <= source_budget
        and abs(arrival_delta - provider_delta) <= arrival_budget,
        budget,
    )


def _validate_ws_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid CoinAPI WS endpoint") from exc
    if (
        parsed.scheme != "wss"
        or parsed.hostname != "ws.coinapi.io"
        or port != 443
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/v1/"
        or parsed.query
        or parsed.fragment
        or parsed.netloc.lower() != "ws.coinapi.io:443"
    ):
        raise ValueError("CoinAPI WS endpoint is not the production allowlisted endpoint")
    return DEFAULT_WS_URL


def _sanitize_ws_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
    except (TypeError, ValueError):
        return "REDACTED_PROVIDER_ENDPOINT"
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
        return "REDACTED_PROVIDER_ENDPOINT"
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        return "REDACTED_PROVIDER_ENDPOINT"
    netloc = f"{host}:{port}" if port is not None else host
    return urllib.parse.urlunsplit((parsed.scheme, netloc, "", "", ""))


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
) -> dict[str, int | float]:
    metadata: dict[str, int | float] = {}
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


def _provider_retry_delay_seconds(
    quota_metadata: dict[str, Any] | None,
    *,
    now_epoch: float | None = None,
) -> float | None:
    metadata = quota_metadata or {}
    candidates: list[float] = []
    for key in ("retry_after_seconds", "rate_limit_reset_after_seconds"):
        value = _finite_nonnegative_number(metadata.get(key))
        if value is not None:
            candidates.append(float(value))
    reset = _finite_nonnegative_number(metadata.get("rate_limit_reset"))
    if reset is not None:
        reset_value = float(reset)
        try:
            now = time.time() if now_epoch is None else float(now_epoch)
        except (TypeError, ValueError, OverflowError):
            return None
        candidates.append(max(0.0, reset_value - now))
    if not candidates:
        return None
    # Treat provider retry headers as advisory input.  The durable state must
    # always retain a bounded sparse re-probe window so credential recovery is
    # eventually observed even if a header is malformed or absurdly large.
    return min(AUTH_BACKOFF_MAX_SECONDS, max(candidates))


def _credential_fingerprint(api_key: str) -> str | None:
    if type(api_key) is not str or not api_key:
        return None
    material = b"coinapi-optional-credential-fingerprint-v1\x00wsds\x00" + api_key.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _cadence_state_key(
    *,
    symbol: str,
    coinapi_symbol_id: str,
    api_key: str,
    provisional: bool = False,
) -> str | None:
    identity = parse_coinapi_symbol_id(coinapi_symbol_id)
    if _validated_runtime_symbol(symbol) is None or identity is None or identity[2] != symbol:
        return None
    fingerprint = _credential_fingerprint(api_key)
    if fingerprint is None:
        return None
    template = WS_PROVISIONAL_CADENCE_KEY_TEMPLATE if provisional else WS_CADENCE_KEY_TEMPLATE
    return template.format(
        credential_fingerprint=fingerprint,
        coinapi_symbol_id=coinapi_symbol_id,
        symbol=symbol,
    )


def _auth_latch_key(api_key: str) -> str | None:
    fingerprint = _credential_fingerprint(api_key)
    return f"{AUTH_LATCH_KEY_PREFIX}{fingerprint}" if fingerprint is not None else None


def _auth_state_signature(api_key: str, unsigned: dict[str, Any]) -> str | None:
    if type(api_key) is not str or not api_key:
        return None
    serialized = _canonical_json(unsigned)
    if serialized is None:
        return None
    material = b"coinapi-optional-auth-backoff-v1\x00wsds\x00" + serialized.encode("ascii")
    return hmac.new(api_key.encode("utf-8"), material, hashlib.sha256).hexdigest()


def _validated_auth_state(candidate: Any, *, api_key: str) -> dict[str, Any] | None:
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
    fingerprint = _credential_fingerprint(api_key)
    if not isinstance(candidate, dict) or set(candidate) != required or fingerprint is None:
        return None
    if (
        candidate.get("schema_version") != AUTH_LATCH_SCHEMA_VERSION
        or candidate.get("provider") != "coinapi"
        or candidate.get("transport") != "wsds"
        or candidate.get("endpoint_identity") != "ws.coinapi.io:443/v1/"
        or candidate.get("credential_fingerprint") != fingerprint
        or type(candidate.get("failure_count")) is not int
        or candidate["failure_count"] <= 0
        or type(candidate.get("last_error_class")) is not str
        or not candidate["last_error_class"].isidentifier()
        or len(candidate["last_error_class"]) > 80
        or type(candidate.get("retry_after_honored")) is not bool
    ):
        return None
    last_http_status = candidate.get("last_http_status")
    if last_http_status is not None and (
        type(last_http_status) is not int
        or last_http_status not in TERMINAL_PROVIDER_HTTP_STATUSES | {RATE_LIMITED_HTTP_STATUS}
    ):
        return None
    if (
        last_http_status is None
        and candidate["last_error_class"] not in DURABLE_NO_HTTP_ERROR_CLASSES
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
    if (
        type(signature) is not str
        or len(signature) != 64
        or any(character not in "0123456789abcdef" for character in signature)
    ):
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
        f"coinapi-wsds-auth-backoff-v1:{fingerprint}:{failure_count}".encode("ascii")
    ).digest()
    unit = int.from_bytes(digest[:8], "big") / ((1 << 64) - 1)
    jittered = base * (0.75 + (0.5 * unit))
    return float(min(AUTH_BACKOFF_MAX_SECONDS, max(AUTH_BACKOFF_BASE_SECONDS, jittered)))


def _build_auth_state(
    *,
    api_key: str,
    http_status: int | None,
    error_class: str,
    prior_state: dict[str, Any] | None,
    quota_metadata: dict[str, Any] | None,
    now_ns: int | None = None,
) -> dict[str, Any] | None:
    fingerprint = _credential_fingerprint(api_key)
    if fingerprint is None or type(error_class) is not str or not error_class.isidentifier():
        return None
    if http_status is not None and (
        type(http_status) is not int
        or http_status not in TERMINAL_PROVIDER_HTTP_STATUSES | {RATE_LIMITED_HTTP_STATUS}
    ):
        return None
    if http_status is None and error_class not in DURABLE_NO_HTTP_ERROR_CLASSES:
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
    unsigned: dict[str, Any] = {
        "schema_version": AUTH_LATCH_SCHEMA_VERSION,
        "provider": "coinapi",
        "transport": "wsds",
        "endpoint_identity": "ws.coinapi.io:443/v1/",
        "credential_fingerprint": fingerprint,
        "failure_count": failure_count,
        "last_http_status": http_status,
        "last_error_class": error_class[:80],
        "next_probe_at_ns": revision_ns + max(1, int(delay_seconds * 1_000_000_000)),
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
    existing = _exact_key_exists(redis_client, key)
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
    return status if count == expected_counts[status] else _AUTH_STATE_ERROR


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


def _auth_state_record_exists(redis_client: Any, *, api_key: str) -> bool | None:
    key = _auth_latch_key(api_key)
    if redis_client is None or key is None:
        return None
    return _exact_key_exists(redis_client, key)


def _clear_auth_state(redis_client: Any, *, api_key: str) -> bool:
    key = _auth_latch_key(api_key)
    if redis_client is None or key is None:
        return False
    try:
        acknowledged = redis_client.delete(key)
    except Exception:
        return False
    return type(acknowledged) is int and acknowledged in {0, 1}


def _sanitized_reason_class(reason: Any, *, close_code: int | None = None) -> str:
    if close_code in {1000, 1001}:
        return "NORMAL_CLOSE"
    text = str(reason or "")[:512].lower()
    if any(token in text for token in ("quota", "usage credit", "subscription")):
        return "QUOTA_OR_SUBSCRIPTION_EXHAUSTED"
    if any(token in text for token in ("rate limit", "too many request")):
        return "RATE_LIMITED"
    if any(token in text for token in ("api key", "authentication", "unauthorized")):
        return "AUTHENTICATION_REJECTED"
    if any(token in text for token in ("entitlement", "permission", "forbidden", "plan")):
        return "ENTITLEMENT_REJECTED"
    if close_code == 1008:
        return "PROVIDER_POLICY_REJECTED"
    return "PROVIDER_REASON_REDACTED" if text else "NO_REASON_PROVIDED"


def _provider_error_class(http_status: int | None, reason_class: str) -> str | None:
    if http_status == 401:
        return "AUTHENTICATION_REJECTED"
    if http_status == 403:
        if reason_class in {
            "QUOTA_OR_SUBSCRIPTION_EXHAUSTED",
            "ENTITLEMENT_REJECTED",
        }:
            return reason_class
        return "AUTHORIZATION_REJECTED"
    if http_status == RATE_LIMITED_HTTP_STATUS or reason_class == "RATE_LIMITED":
        return "RATE_LIMITED"
    if reason_class in {
        "AUTHENTICATION_REJECTED",
        "ENTITLEMENT_REJECTED",
        "QUOTA_OR_SUBSCRIPTION_EXHAUSTED",
        "PROVIDER_POLICY_REJECTED",
    }:
        return reason_class
    return None


def _exception_http_response(exc: Exception) -> tuple[int | None, Any]:
    response = getattr(exc, "response", None)
    for source in (response, exc):
        if source is None:
            continue
        for attr in ("status_code", "status"):
            value = _finite_nonnegative_number(getattr(source, attr, None))
            if type(value) is int:
                return value, getattr(source, "headers", None)
    return None, getattr(response, "headers", None)


def _ws_exception_metadata(exc: Exception) -> dict[str, Any]:
    close = getattr(exc, "rcvd", None) or getattr(exc, "sent", None) or exc
    close_code_value = _finite_nonnegative_number(getattr(close, "code", None))
    close_code = close_code_value if type(close_code_value) is int else None
    reason_class = _sanitized_reason_class(
        getattr(close, "reason", None),
        close_code=close_code,
    )
    http_status, headers = _exception_http_response(exc)
    quota_metadata = _sanitize_quota_metadata(headers)
    error_class = _provider_error_class(http_status, reason_class)
    error_type = type(exc).__name__
    if not error_type.isidentifier():
        error_type = "Exception"
    return {
        "last_error_type": error_type[:80],
        "last_close_code": close_code,
        "last_close_reason_class": reason_class,
        "provider_http_status": http_status,
        "provider_error_class": error_class,
        "quota_metadata": quota_metadata,
        "raw_provider_reason_recorded": False,
        "raw_provider_body_recorded": False,
    }


def _provider_message_error(message: dict[str, Any]) -> dict[str, Any] | None:
    message_type = str(message.get("type") or "").lower()
    if message_type not in {"error", "fault"}:
        return None
    status_value = _finite_nonnegative_number(
        message.get("status_code", message.get("http_status"))
    )
    http_status = status_value if type(status_value) is int else None
    reason = message.get("message", message.get("error", message.get("detail")))
    reason_class = _sanitized_reason_class(reason)
    error_class = _provider_error_class(http_status, reason_class) or "PROVIDER_ERROR_MESSAGE"
    return {
        "last_error_type": "ProviderErrorMessage",
        "last_close_code": None,
        "last_close_reason_class": reason_class,
        "provider_http_status": http_status,
        "provider_error_class": error_class,
        "quota_metadata": {},
        "raw_provider_reason_recorded": False,
        "raw_provider_body_recorded": False,
    }


def _next_backoff(
    consecutive_failures: int,
    *,
    committed_messages: int,
    provider_retry_delay_seconds: float | None = None,
    random_unit: float | None = None,
) -> tuple[int, float | None]:
    if committed_messages > 0:
        return 0, provider_retry_delay_seconds
    failures = max(0, int(consecutive_failures)) + 1
    exponential = TRANSIENT_BACKOFF_BASE_SECONDS
    for _ in range(failures - 1):
        exponential = min(TRANSIENT_BACKOFF_CAP_SECONDS, exponential * 2.0)
        if exponential >= TRANSIENT_BACKOFF_CAP_SECONDS:
            break
    unit = (
        random.SystemRandom().random() if random_unit is None else min(1.0, max(0.0, random_unit))
    )
    jittered = exponential * (1.0 + ((unit * 2.0) - 1.0) * TRANSIENT_BACKOFF_JITTER_FRACTION)
    transient_delay = min(TRANSIENT_BACKOFF_CAP_SECONDS, max(0.0, jittered))
    if provider_retry_delay_seconds is not None:
        transient_delay = max(transient_delay, max(0.0, provider_retry_delay_seconds))
    return failures, transient_delay


def _coinapi_symbol_id(symbol: str, *, exchange_id: str) -> str:
    validated_symbol = _validated_runtime_symbol(symbol)
    validated_exchange = _validated_exchange_id(exchange_id)
    if validated_symbol is None:
        raise ValueError("symbol must exactly match uppercase [A-Z0-9]+USDT")
    if validated_exchange is None:
        raise ValueError("exchange_id must be exact uppercase ASCII alphanumeric")
    base = validated_symbol
    if base.endswith("USDT"):
        base = base[:-4]
    market_type = "PERP" if validated_exchange == "BINANCEFTS" else "SPOT"
    return f"{validated_exchange}_{market_type}_{base}_USDT"


def _parse_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return default
    parsed = tuple(part.strip() for part in value.split(",") if part.strip())
    return parsed or default


def _allowed_subscription_data_types() -> frozenset[str]:
    allowed = {"quote", "book5"}
    if _env_bool("COINAPI_ALLOW_TRADE", False):
        allowed.add("trade")
    if _env_bool("COINAPI_ALLOW_FULL_BOOK", False):
        allowed.add("book")
    return frozenset(allowed)


def _validated_subscription_data_types(candidate: Any) -> list[str] | None:
    allowed = _allowed_subscription_data_types()
    if (
        type(candidate) is not list
        or not candidate
        or any(
            type(item) is not str or item != item.strip() or item not in allowed
            for item in candidate
        )
    ):
        return None
    output: list[str] = []
    for item in candidate:
        if item not in output:
            output.append(item)
    if "quote" not in output:
        output.insert(0, "quote")
    return output


def _subscribe_data_types() -> list[str] | None:
    raw = list(
        _parse_csv(
            os.getenv("COINAPI_SUBSCRIBE_DATA_TYPES"),
            ("quote", "book5"),
        )
    )
    return _validated_subscription_data_types(raw)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
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


def _write_status(payload: dict[str, Any], paths: tuple[Path, ...]) -> bool:
    payload["status_file_write_healthy"] = True
    payload["status_file_write_failure_count"] = 0
    payload["status_file_write_error_classes"] = []
    payload["raw_status_file_error_recorded"] = False
    successful_paths: list[Path] = []
    error_classes: list[str] = []
    for path in paths:
        try:
            _write_json(path, payload)
            successful_paths.append(path)
        except OSError as exc:
            error_class = type(exc).__name__
            error_classes.append(error_class[:80] if error_class.isidentifier() else "OSError")
    if not error_classes:
        return True
    payload["status_file_write_healthy"] = False
    payload["status_file_write_failure_count"] = len(error_classes)
    payload["status_file_write_error_classes"] = sorted(set(error_classes))
    payload["raw_status_file_error_recorded"] = False
    for path in successful_paths:
        try:
            _write_json(path, payload)
        except OSError:
            continue
    return False


def _publish_status(
    payload: dict[str, Any],
    paths: tuple[Path, ...],
    *,
    redis_client: Any,
    ttl_seconds: int,
    stats: dict[str, Any] | None,
) -> bool:
    data_commit_acked = bool(payload.get("current_data_commit_acked"))
    payload["redis_ok"] = False
    payload["publication_healthy"] = False
    payload["status_publication_healthy"] = False
    payload["service_healthy"] = False
    initial_status_files_healthy = _write_status(payload, paths)
    redis_payload = dict(payload)
    redis_payload["redis_ok"] = True
    redis_payload["status_publication_healthy"] = initial_status_files_healthy
    redis_payload["publication_healthy"] = data_commit_acked and initial_status_files_healthy
    redis_payload["service_healthy"] = initial_status_files_healthy
    acknowledged = _safe_set_json(
        redis_client,
        WS_QUARANTINE_HEARTBEAT_KEY,
        redis_payload,
        ex=ttl_seconds,
    )
    if not acknowledged:
        if stats is not None:
            stats["redis_write_failures"] = int(stats.get("redis_write_failures") or 0) + 1
        payload_stats = dict(payload.get("stats") or {})
        payload_stats["redis_write_failures"] = (
            int(payload_stats.get("redis_write_failures") or 0) + 1
        )
        payload["stats"] = payload_stats
        payload["redis_ok"] = False
        payload["publication_healthy"] = False
        payload["status_publication_healthy"] = False
        payload["service_healthy"] = False
        _write_status(payload, paths)
        return False
    payload["redis_ok"] = True
    payload["status_publication_healthy"] = True
    payload["publication_healthy"] = data_commit_acked
    payload["service_healthy"] = True
    final_status_files_healthy = _write_status(payload, paths)
    if not final_status_files_healthy:
        payload["publication_healthy"] = False
        payload["status_publication_healthy"] = False
        payload["service_healthy"] = False
    return final_status_files_healthy


def _base_status(
    *,
    symbols: tuple[str, ...],
    subscribed_symbols: tuple[str, ...] | None = None,
    max_symbols: int | None = None,
    opt_in: bool,
    credential_present: bool,
    redis_ok: bool,
    stream_connected: bool,
    classification: str,
    blocker: str | None,
    stats: dict[str, Any],
    data_types: list[str],
    ws_url: str,
    provider_health: dict[str, Any] | None = None,
    symbol_health: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    subscribed = symbols if subscribed_symbols is None else subscribed_symbols
    coverage_symbols = symbols if symbol_health is not None else subscribed
    coverage = {
        symbol: dict(
            (symbol_health or {}).get(
                symbol,
                {
                    "observed": False,
                    "schema_valid": False,
                    "coverage": False,
                    "fresh": False,
                    "committed": False,
                    "receipt_present": False,
                    "cadence_ready": False,
                },
            )
        )
        for symbol in coverage_symbols
    }
    stream_admission_ready = (
        bool(stream_connected)
        and bool(subscribed)
        and all(
            bool(coverage[symbol].get("observed"))
            and bool(coverage[symbol].get("schema_valid"))
            and bool(coverage[symbol].get("fresh"))
            and bool(coverage[symbol].get("committed"))
            and bool(coverage[symbol].get("cadence_ready"))
            for symbol in subscribed
        )
    )
    publication_healthy = bool(redis_ok)
    return {
        "worker_id": WORKER_ID,
        "schema_version": "v2_coinapi_wsds_status_v3",
        "provider_identity_schema_version": PROVIDER_IDENTITY_SCHEMA_VERSION,
        "quarantine_namespace_version": "v4",
        "cadence_namespace_version": "v4",
        "provisional_cadence_namespace_version": "v3",
        "legacy_namespace_reads_enabled": False,
        "legacy_namespace_migration_mode": "COLD_BOOTSTRAP_REQUIRED",
        "classification": classification,
        "generated_utc": _utc_iso(),
        "heartbeat_at": _utc_iso(),
        "service_active": True,
        "service_healthy": publication_healthy,
        "stream_connected": bool(stream_connected),
        "stream_admission_ready": stream_admission_ready,
        "provider_data_usable": False,
        "raw_quarantine_current": stream_admission_ready,
        "publication_healthy": stream_admission_ready and publication_healthy,
        "status_publication_healthy": publication_healthy,
        "status_file_write_healthy": True,
        "status_file_write_failure_count": 0,
        "status_file_write_error_classes": [],
        "raw_status_file_error_recorded": False,
        "blocked_reason": blocker,
        "provider_health": {
            **dict(provider_health or {}),
            **OPTIONAL_SOURCE_FIELDS,
        },
        "trainer_consumable": False,
        "typed_missing": not stream_admission_ready,
        "raw_provider_body_recorded": False,
        "raw_provider_reason_recorded": False,
        "operator_opt_in_env_var": OPT_IN_ENV_VAR,
        "operator_opt_in_enabled": bool(opt_in),
        "credential_env_names": ["COINAPI_API_KEY", "COINAPI_KEY"],
        "credential_present": bool(credential_present),
        "credential_value_emitted": False,
        "raw_secret_values_recorded": False,
        "ws_url": _sanitize_ws_url(ws_url),
        "subscribe_data_types": data_types,
        "symbols": list(symbols),
        "symbols_count": len(symbols),
        "subscribed_symbols": list(subscribed),
        "subscribed_symbols_count": len(subscribed),
        "per_symbol_health": coverage,
        "all_subscribed_symbols_covered": bool(subscribed)
        and all(bool(coverage[symbol].get("coverage")) for symbol in subscribed),
        "all_subscribed_symbols_fresh": bool(subscribed)
        and all(bool(coverage[symbol].get("fresh")) for symbol in subscribed),
        "all_subscribed_symbols_committed": bool(subscribed)
        and all(bool(coverage[symbol].get("committed")) for symbol in subscribed),
        "all_subscribed_symbols_receipted": False,
        "max_symbols": max_symbols,
        "current_data_commit_acked": stream_admission_ready and bool(redis_ok),
        "redis_ok": bool(redis_ok),
        "stats": dict(stats),
        "heartbeat_key": WS_QUARANTINE_HEARTBEAT_KEY,
        "target_redis_key_patterns": [
            WS_FENCE_KEY_TEMPLATE,
            WS_DATA_KEY_TEMPLATE,
            WS_CONFLICT_KEY_TEMPLATE,
            WS_CADENCE_KEY_TEMPLATE,
            WS_PROVISIONAL_CADENCE_KEY_TEMPLATE,
            f"{AUTH_LATCH_KEY_PREFIX}{{credential_fingerprint}}",
            WS_QUARANTINE_HEARTBEAT_KEY,
        ],
        "canonical_receipt_resolver_present": False,
        "freshness_policy": "AUTHENTICATED_PRIOR_SESSION_CAUSAL_ADAPTIVE_CADENCE",
        "static_market_freshness_threshold_used": False,
        "runtime_mode": "LIVE_RAW_DATA_QUARANTINE_ONLY",
        "live_data_enabled": bool(opt_in and credential_present and subscribed),
        "live_decision_input_enabled": False,
        "trader_execution_enabled": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "places_exchange_orders": False,
        "calls_test_order_endpoint": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "redis_trim_performed": False,
        **OPTIONAL_SOURCE_FIELDS,
    }


def _blocked_status(
    *,
    symbols: tuple[str, ...],
    opt_in: bool,
    credential_present: bool,
    redis_ok: bool,
    data_types: list[str],
    ws_url: str,
    endpoint_valid: bool = True,
    exchange_id_valid: bool = True,
    redis_available: bool = True,
    subscription_types_valid: bool = True,
    runtime_config_error: str | None = None,
) -> dict[str, Any]:
    provider_error_class: str | None = None
    if not endpoint_valid:
        blocker = "COINAPI_WSDS_URL is not the production allowlisted endpoint."
        classification = "V2_COINAPI_WSDS_OPTIONAL_CONFIGURATION_INVALID"
        provider_state = "OPTIONAL_CONFIGURATION_INVALID"
        provider_error_class = "INVALID_WSDS_ENDPOINT"
    elif not exchange_id_valid:
        blocker = "COINAPI_PRIMARY_EXCHANGE_ID is not exact uppercase ASCII alphanumeric."
        classification = "V2_COINAPI_WSDS_OPTIONAL_CONFIGURATION_INVALID"
        provider_state = "OPTIONAL_CONFIGURATION_INVALID"
        provider_error_class = "INVALID_PRIMARY_EXCHANGE_ID"
    elif not subscription_types_valid:
        blocker = "COINAPI_SUBSCRIBE_DATA_TYPES contains a non-allowlisted exact value."
        classification = "V2_COINAPI_WSDS_OPTIONAL_CONFIGURATION_INVALID"
        provider_state = "OPTIONAL_CONFIGURATION_INVALID"
        provider_error_class = "INVALID_SUBSCRIPTION_DATA_TYPES"
    elif runtime_config_error is not None:
        blocker = "CoinAPI WSDS numeric runtime configuration is outside safe finite bounds."
        classification = "V2_COINAPI_WSDS_OPTIONAL_CONFIGURATION_INVALID"
        provider_state = "OPTIONAL_CONFIGURATION_INVALID"
        provider_error_class = runtime_config_error
    elif not opt_in:
        blocker = f"{OPT_IN_ENV_VAR} is not true; WSDS connection not opened."
        classification = "V2_COINAPI_WSDS_OPTIONAL_DORMANT_NOT_OPTED_IN"
        provider_state = "OPTIONAL_DORMANT_NOT_OPTED_IN"
    elif not credential_present:
        blocker = "COINAPI_API_KEY/COINAPI_KEY not available; WSDS connection not opened."
        classification = "V2_COINAPI_WSDS_OPTIONAL_NOT_CONFIGURED"
        provider_state = "OPTIONAL_NOT_CONFIGURED"
    elif websockets is None:
        blocker = "websockets package unavailable; WSDS connection not opened."
        classification = "V2_COINAPI_WSDS_OPTIONAL_DEPENDENCY_UNAVAILABLE"
        provider_state = "OPTIONAL_DEPENDENCY_UNAVAILABLE"
    elif not redis_available:
        blocker = "Redis unavailable; durable retry state cannot be verified."
        classification = "V2_COINAPI_WSDS_OPTIONAL_RETRY_STATE_UNAVAILABLE"
        provider_state = "OPTIONAL_RETRY_STATE_UNAVAILABLE"
        provider_error_class = "DURABLE_RETRY_STATE_UNAVAILABLE"
    else:
        blocker = "WSDS blocked before connection."
        classification = "V2_COINAPI_WSDS_OPTIONAL_UNAVAILABLE"
        provider_state = "OPTIONAL_UNAVAILABLE"
    return _base_status(
        symbols=symbols,
        subscribed_symbols=(),
        opt_in=opt_in,
        credential_present=credential_present,
        redis_ok=redis_ok,
        stream_connected=False,
        classification=classification,
        blocker=blocker,
        stats={},
        data_types=data_types,
        ws_url=ws_url,
        provider_health={
            "state": provider_state,
            "provider_error_class": provider_error_class,
            "typed_missing": True,
            "trainer_consumable": False,
        },
        symbol_health=_initial_symbol_health(symbols),
    )


def _message_symbol_id(message: dict[str, Any]) -> str:
    if "symbol_id_exchange" in message:
        return ""
    value = message.get("symbol_id")
    return value if type(value) is str else ""


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _observation_time(value: datetime | None) -> datetime:
    observed_at = datetime.now(UTC) if value is None else value
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return observed_at.astimezone(UTC)


def _message_clocks(
    message: dict[str, Any],
    *,
    observed_at: datetime | None,
) -> dict[str, Any] | None:
    observed = _observation_time(observed_at)
    provider_event = parse_provider_timestamp(message.get("time_exchange"))
    provider_received = parse_provider_timestamp(message.get("time_coinapi"))
    if provider_event is None or provider_received is None:
        return None
    observed_ns = datetime_epoch_ns(observed)
    if not (provider_event[1] <= provider_received[1] <= observed_ns):
        return None
    ingested = max(datetime.now(UTC), observed + timedelta(microseconds=1))
    generated = max(datetime.now(UTC), ingested + timedelta(microseconds=1))
    return {
        "source_event_time": iso_utc_ns(provider_event[1]),
        "source_event_ts_ms": provider_event[1] // 1_000_000,
        "source_event_ts_ns": provider_event[1],
        "provider_received_time": iso_utc_ns(provider_received[1]),
        "observed_at": _iso_utc(observed),
        "ingested_at": _iso_utc(ingested),
        "generated_at": _iso_utc(generated),
        "available_at": None,
    }


def _snapshot_from_message(
    message: dict[str, Any],
    *,
    observed_at: datetime | None = None,
    expected_symbol_id: str | None = None,
) -> dict[str, Any] | None:
    msg_type = str(message.get("type") or "").lower()
    message_symbol_id = _message_symbol_id(message)
    provider_identity = parse_coinapi_symbol_id(message_symbol_id)
    if (
        not message_symbol_id
        or (expected_symbol_id is not None and message_symbol_id != expected_symbol_id)
        or provider_identity is None
    ):
        return None
    clocks = _message_clocks(message, observed_at=observed_at)
    if clocks is None:
        return None
    clocks.update(
        {
            "provider_identity_schema_version": PROVIDER_IDENTITY_SCHEMA_VERSION,
            "coinapi_symbol_id": message_symbol_id,
            "coinapi_exchange_id": provider_identity[0],
            "coinapi_market_type": provider_identity[1],
        }
    )
    if msg_type == "quote":
        bid_f = _float(message.get("bid_price"))
        ask_f = _float(message.get("ask_price"))
        bid_sz = _float(message.get("bid_size"))
        ask_sz = _float(message.get("ask_size"))
        if bid_f is None or ask_f is None or bid_sz is None or ask_sz is None:
            return None
        if bid_f <= 0 or ask_f <= 0 or ask_f < bid_f or bid_sz < 0 or ask_sz < 0:
            return None
        mid = (bid_f + ask_f) / 2.0
        total = bid_sz + ask_sz
        return {
            **clocks,
            "updated_ts_ms": clocks["source_event_ts_ms"],
            "best_bid_px": bid_f,
            "best_ask_px": ask_f,
            "best_bid_sz": bid_sz,
            "best_ask_sz": ask_sz,
            "mid_px": mid,
            "spread_bps": ((ask_f - bid_f) / mid * 10_000.0) if mid else None,
            "microprice": (((bid_f * ask_sz) + (ask_f * bid_sz)) / total if total > 0 else None),
            "book_bid_sum_5": bid_sz,
            "book_ask_sum_5": ask_sz,
            "imbalance_5": ((bid_sz - ask_sz) / total) if total > 0 else None,
        }
    if msg_type.startswith("book") or msg_type in {"orderbook", "orderbooks"}:
        bids = message.get("bids") if isinstance(message.get("bids"), list) else []
        asks = message.get("asks") if isinstance(message.get("asks"), list) else []
        if not bids or not asks:
            return None

        def price_size(item: Any) -> tuple[float | None, float | None]:
            if isinstance(item, dict):
                return _float(item.get("price")), _float(item.get("size"))
            if isinstance(item, list | tuple) and len(item) >= 2:
                return _float(item[0]), _float(item[1])
            return None, None

        parsed_bids = [price_size(item) for item in bids[:5]]
        parsed_asks = [price_size(item) for item in asks[:5]]
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
        book_bid, book_bid_sz = parsed_bids[0]
        book_ask, book_ask_sz = parsed_asks[0]
        assert book_bid is not None and book_bid_sz is not None
        assert book_ask is not None and book_ask_sz is not None
        if book_ask < book_bid:
            return None
        mid = (book_bid + book_ask) / 2.0
        bid_sum = sum(size for _, size in parsed_bids if size is not None)
        ask_sum = sum(size for _, size in parsed_asks if size is not None)
        total = bid_sum + ask_sum
        top_total = book_bid_sz + book_ask_sz
        return {
            **clocks,
            "updated_ts_ms": clocks["source_event_ts_ms"],
            "best_bid_px": book_bid,
            "best_ask_px": book_ask,
            "best_bid_sz": book_bid_sz,
            "best_ask_sz": book_ask_sz,
            "mid_px": mid,
            "spread_bps": ((book_ask - book_bid) / mid * 10_000.0) if mid else None,
            "microprice": (
                ((book_bid * book_ask_sz) + (book_ask * book_bid_sz)) / top_total
                if top_total > 0
                else None
            ),
            "book_bid_sum_5": bid_sum,
            "book_ask_sum_5": ask_sum,
            "imbalance_5": ((bid_sum - ask_sum) / total) if total > 0 else None,
        }
    return None


def _combined_session_stats(
    aggregate_stats: dict[str, Any] | None,
    session_stats: dict[str, Any],
) -> dict[str, Any]:
    base = dict(aggregate_stats or {})
    counters = (
        "sessions",
        "messages_received",
        "selected_messages_observed",
        "schema_valid_messages",
        "fresh_messages",
        "committed_messages",
        "receipt_accepted_messages",
        "older_messages_rejected",
        "duplicate_messages_rejected",
        "conflicting_messages_quarantined",
        "real_messages_received",
        "messages_parsed",
        "snapshots_written",
        "microfeatures_written",
        "parse_errors",
        "redis_write_failures",
        "authenticated_cadence_bases_loaded",
        "cadence_bases_persisted",
        "cadence_basis_write_rejections",
        "provisional_cadence_records_loaded",
        "provisional_cadence_records_persisted",
        "provisional_cadence_write_rejections",
    )
    for key in counters:
        base[key] = int(base.get(key) or 0) + int(session_stats.get(key) or 0)
    for key in (
        "last_message_utc",
        "last_snapshot_utc",
        "last_error_type",
        "last_close_code",
        "last_close_reason_class",
        "provider_http_status",
        "provider_error_class",
        "quota_metadata",
    ):
        base[key] = session_stats.get(key) or base.get(key)
    base["transport_connected"] = bool(base.get("transport_connected")) or bool(
        session_stats.get("transport_connected")
    )
    base["authenticated_transport_succeeded"] = bool(
        base.get("authenticated_transport_succeeded")
    ) or bool(session_stats.get("authenticated_transport_succeeded"))
    return base


def _initial_symbol_health(
    selected: tuple[str, ...],
    cadence_bases: dict[str, dict[str, Any] | None] | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        symbol: {
            "observed": False,
            "schema_valid": False,
            "coverage": False,
            "fresh": False,
            "committed": False,
            "receipt_present": False,
            "cadence_ready": isinstance((cadence_bases or {}).get(symbol), dict),
            "cadence_basis_authenticated": isinstance((cadence_bases or {}).get(symbol), dict),
            "cadence_basis_persisted": False,
            "cadence_basis_write_final": False,
            "cadence_basis_write_state": None,
            "observed_count": 0,
            "schema_valid_count": 0,
            "fresh_count": 0,
            "committed_count": 0,
            "receipt_count": 0,
            "last_event_ns": ((cadence_bases or {}).get(symbol) or {}).get("last_event_ns"),
            "last_provider_received_ns": ((cadence_bases or {}).get(symbol) or {}).get(
                "last_provider_received_ns"
            ),
            "last_observed_ns": ((cadence_bases or {}).get(symbol) or {}).get("last_observed_ns"),
            "adaptive_cadence_ns": ((cadence_bases or {}).get(symbol) or {}).get(
                "event_cadence_ns"
            ),
            "adaptive_provider_cadence_ns": ((cadence_bases or {}).get(symbol) or {}).get(
                "provider_cadence_ns"
            ),
            "adaptive_arrival_cadence_ns": ((cadence_bases or {}).get(symbol) or {}).get(
                "arrival_cadence_ns"
            ),
            "adaptive_source_lag_ns": ((cadence_bases or {}).get(symbol) or {}).get(
                "max_source_lag_ns"
            ),
            "adaptive_arrival_lag_ns": ((cadence_bases or {}).get(symbol) or {}).get(
                "max_arrival_lag_ns"
            ),
            "freshness_budget_ns": _cadence_freshness_budget_ns(
                (cadence_bases or {}).get(symbol) or {}
            ),
            "current_event_ns": None,
            "current_provider_received_ns": None,
            "current_observed_ns": None,
            "current_payload_ttl_ms": None,
            "current_data_key": None,
            "current_candidate_fresh": False,
            "current_health_reason": "AWAITING_CURRENT_ACCEPTED_SAMPLE",
            "provisional_cadence_loaded": False,
            "provisional_cadence_sample_count": 0,
            **OPTIONAL_SOURCE_FIELDS,
        }
        for symbol in selected
    }


def _clear_current_health(state: dict[str, Any], reason: str) -> None:
    state["fresh"] = False
    state["committed"] = False
    state["current_candidate_fresh"] = False
    state["current_payload_ttl_ms"] = None
    state["current_data_key"] = None
    state["current_event_ns"] = None
    state["current_provider_received_ns"] = None
    state["current_observed_ns"] = None
    state["current_health_reason"] = reason


def _record_committed_event(
    state: dict[str, Any],
    *,
    cadence_basis: dict[str, Any] | None,
    session_anchor_ns: int,
    event_ns: int,
    provider_received_ns: int,
    observed_ns: int,
    data_key: str,
    payload_ttl_ms: int,
) -> bool:
    state["coverage"] = True
    state["committed_count"] = int(state.get("committed_count") or 0) + 1
    state["last_event_ns"] = event_ns
    state["last_provider_received_ns"] = provider_received_ns
    state["last_observed_ns"] = observed_ns
    fresh, budget = (
        _sample_fresh_against_basis(
            cadence_basis,
            session_anchor_ns=session_anchor_ns,
            event_ns=event_ns,
            provider_received_ns=provider_received_ns,
            observed_ns=observed_ns,
        )
        if isinstance(cadence_basis, dict)
        else (False, None)
    )
    state["freshness_budget_ns"] = budget
    if not fresh or payload_ttl_ms <= 0:
        _clear_current_health(
            state,
            "NO_AUTHENTICATED_PRIOR_BASIS"
            if cadence_basis is None
            else "CURRENT_SAMPLE_OUTSIDE_AUTHENTICATED_CADENCE",
        )
        return False
    state["fresh"] = True
    state["committed"] = True
    state["current_candidate_fresh"] = True
    state["current_payload_ttl_ms"] = payload_ttl_ms
    state["current_data_key"] = data_key
    state["current_event_ns"] = event_ns
    state["current_provider_received_ns"] = provider_received_ns
    state["current_observed_ns"] = observed_ns
    state["current_health_reason"] = "AUTHENTICATED_CADENCE_AND_CURRENT_COMMIT"
    state["fresh_count"] = int(state.get("fresh_count") or 0) + 1
    return True


def _append_bootstrap_sample(
    samples: list[tuple[int, int, int]],
    *,
    session_anchor_ns: int,
    event_ns: int,
    provider_received_ns: int,
    observed_ns: int,
) -> bool:
    if event_ns < session_anchor_ns or provider_received_ns < session_anchor_ns:
        return False
    sample = (event_ns, provider_received_ns, observed_ns)
    if samples and not all(right > left for left, right in zip(samples[-1], sample, strict=True)):
        samples.clear()
    samples.append(sample)
    if len(samples) > CADENCE_BOOTSTRAP_SAMPLE_COUNT:
        del samples[:-CADENCE_BOOTSTRAP_SAMPLE_COUNT]
    return True


def _refresh_current_health(
    selected: tuple[str, ...],
    symbol_health: dict[str, dict[str, Any]],
    redis_client: Any,
    *,
    now_ns: int,
) -> bool:
    for symbol in selected:
        state = symbol_health[symbol]
        if state.get("current_candidate_fresh") is not True:
            state["fresh"] = False
            state["committed"] = False
            continue
        data_key = state.get("current_data_key")
        event_ns = state.get("current_event_ns")
        budget = state.get("freshness_budget_ns")
        if (
            type(data_key) is not str
            or type(event_ns) is not int
            or type(budget) is not int
            or budget <= 0
            or now_ns < event_ns
            or now_ns - event_ns > budget
        ):
            _clear_current_health(state, "CURRENT_SAMPLE_AGE_EXCEEDED_ADAPTIVE_BASIS")
            continue
        payload_ttl_ms = _safe_pttl_ms(redis_client, data_key)
        state["current_payload_ttl_ms"] = payload_ttl_ms
        if payload_ttl_ms is None or payload_ttl_ms <= 0:
            _clear_current_health(state, "CURRENT_PAYLOAD_TTL_NOT_POSITIVE")
            continue
        state["fresh"] = True
        state["committed"] = True
    return _session_admission_ready(selected, symbol_health)


def _adaptive_receive_timeout_seconds(
    selected: tuple[str, ...],
    symbol_health: dict[str, dict[str, Any]],
    *,
    heartbeat_interval_seconds: float,
    now_ns: int,
) -> float:
    try:
        timeout_seconds = float(heartbeat_interval_seconds)
    except (TypeError, ValueError):
        raise ValueError("heartbeat interval must be finite and positive") from None
    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("heartbeat interval must be finite and positive")
    for symbol in selected:
        state = symbol_health[symbol]
        if state.get("current_candidate_fresh") is not True:
            continue
        event_ns = state.get("current_event_ns")
        budget_ns = state.get("freshness_budget_ns")
        payload_ttl_ms = state.get("current_payload_ttl_ms")
        if type(event_ns) is int and type(budget_ns) is int:
            remaining_age_ns = budget_ns - (now_ns - event_ns)
            timeout_seconds = min(timeout_seconds, remaining_age_ns / 1_000_000_000)
        if type(payload_ttl_ms) is int:
            timeout_seconds = min(timeout_seconds, payload_ttl_ms / 1000)
    return max(timeout_seconds, sys.float_info.epsilon)


def _session_admission_ready(
    selected: tuple[str, ...],
    symbol_health: dict[str, dict[str, Any]],
) -> bool:
    return bool(selected) and all(
        bool(symbol_health[symbol].get("coverage"))
        and bool(symbol_health[symbol].get("fresh"))
        and bool(symbol_health[symbol].get("committed"))
        and bool(symbol_health[symbol].get("cadence_ready"))
        for symbol in selected
    )


def _open_ws_without_redirects(
    ws_url: str,
    *,
    connect_factory: Any | None = None,
) -> Any:
    validated_url = _validate_ws_url(ws_url)
    factory = connect_factory
    if factory is None:
        if websockets is None:
            raise RuntimeError("websockets package unavailable")
        factory = websockets.connect
    connector = factory(
        validated_url,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=10,
        max_size=MAX_WS_MESSAGE_BYTES,
    )
    process_redirect = getattr(connector, "process_redirect", None)
    if callable(process_redirect):
        connector.process_redirect = lambda exc: exc
    elif connect_factory is None:
        raise RuntimeError("websocket transport cannot prove redirects are disabled")
    return connector


def _float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) else None


async def _run_session(
    *,
    symbols: tuple[str, ...],
    api_key: str,
    redis_client: Any,
    ttl_seconds: int,
    ws_url: str,
    data_types: list[str],
    max_symbols: int,
    max_seconds_per_session: float,
    max_messages_per_session: int,
    heartbeat_interval_seconds: float,
    status_paths: tuple[Path, ...],
    aggregate_stats: dict[str, Any] | None = None,
    connect_factory: Any | None = None,
) -> dict[str, Any]:
    _validate_ws_url(ws_url)
    validated_data_types = _validated_subscription_data_types(data_types)
    if validated_data_types is None or validated_data_types != data_types:
        raise ValueError("CoinAPI WSDS subscription types must match the exact allowlist")
    if (
        type(ttl_seconds) is not int
        or not (1 <= ttl_seconds <= 86_400)
        or type(max_symbols) is not int
        or not (0 <= max_symbols <= MAX_WS_SYMBOLS)
        or type(max_messages_per_session) is not int
        or not (1 <= max_messages_per_session <= MAX_WS_MESSAGES_PER_SESSION)
        or _validated_finite_range(
            max_seconds_per_session,
            minimum=0.001,
            maximum=MAX_WS_RUNTIME_SECONDS,
        )
        is None
        or _validated_finite_range(
            heartbeat_interval_seconds,
            minimum=0.001,
            maximum=MAX_WS_HEARTBEAT_SECONDS,
        )
        is None
    ):
        raise ValueError("CoinAPI WSDS session configuration is outside safe finite bounds")
    if any(_validated_runtime_symbol(symbol) is None for symbol in symbols):
        raise ValueError("all CoinAPI symbols must exactly match uppercase [A-Z0-9]+USDT")
    session_anchor_ns = datetime_epoch_ns(datetime.now(UTC))
    selected = symbols if int(max_symbols) <= 0 else symbols[: max(1, int(max_symbols))]
    exchange_id = os.getenv("COINAPI_PRIMARY_EXCHANGE_ID", "BINANCEFTS")
    coinapi_symbol_ids = {
        symbol: _coinapi_symbol_id(symbol, exchange_id=exchange_id) for symbol in selected
    }
    symbol_map = {
        coinapi_symbol_id: symbol for symbol, coinapi_symbol_id in coinapi_symbol_ids.items()
    }
    stats: dict[str, Any] = {
        "sessions": 0,
        "messages_received": 0,
        "selected_messages_observed": 0,
        "schema_valid_messages": 0,
        "schema_rejected_messages": 0,
        "fresh_messages": 0,
        "committed_messages": 0,
        "receipt_accepted_messages": 0,
        "older_messages_rejected": 0,
        "duplicate_messages_rejected": 0,
        "conflicting_messages_quarantined": 0,
        "real_messages_received": 0,
        "messages_parsed": 0,
        "snapshots_written": 0,
        "microfeatures_written": 0,
        "parse_errors": 0,
        "redis_write_failures": 0,
        "authenticated_cadence_bases_loaded": 0,
        "cadence_bases_persisted": 0,
        "cadence_basis_write_rejections": 0,
        "provisional_cadence_records_loaded": 0,
        "provisional_cadence_records_persisted": 0,
        "provisional_cadence_write_rejections": 0,
        "transport_connected": False,
        "authenticated_transport_succeeded": False,
        "last_message_utc": None,
        "last_snapshot_utc": None,
        "provider_health": None,
        "cadence_bootstrap_session_rotation_requested": False,
    }
    cadence_bases = {
        symbol: _load_authenticated_cadence_basis(
            redis_client,
            symbol=symbol,
            coinapi_symbol_id=coinapi_symbol_ids[symbol],
            api_key=api_key,
        )
        for symbol in selected
    }
    stats["authenticated_cadence_bases_loaded"] = sum(
        1 for basis in cadence_bases.values() if isinstance(basis, dict)
    )
    provisional_payloads = {
        symbol: (
            _read_provisional_cadence_payload(
                redis_client,
                symbol=symbol,
                coinapi_symbol_id=coinapi_symbol_ids[symbol],
                api_key=api_key,
            )
            if cadence_bases[symbol] is None
            else None
        )
        for symbol in selected
    }
    bootstrap_samples: dict[str, list[tuple[int, int, int]]] = {
        symbol: [
            (sample[0], sample[1], sample[2])
            for sample in (provisional_payloads[symbol] or {}).get("samples", [])
        ]
        for symbol in selected
    }
    stats["provisional_cadence_records_loaded"] = sum(
        1 for payload in provisional_payloads.values() if isinstance(payload, dict)
    )
    symbol_health = _initial_symbol_health(selected, cadence_bases)
    for symbol in selected:
        symbol_health[symbol]["provisional_cadence_loaded"] = isinstance(
            provisional_payloads[symbol],
            dict,
        )
        symbol_health[symbol]["provisional_cadence_sample_count"] = len(bootstrap_samples[symbol])
    current_data_redis_ack = False
    hello = {
        "type": "hello",
        "apikey": api_key,
        "heartbeat": True,
        "subscribe_data_type": data_types,
        "subscribe_filter_symbol_id": list(symbol_map.keys()),
    }
    started = time.monotonic()
    last_status = 0.0
    try:
        async with _open_ws_without_redirects(
            ws_url,
            connect_factory=connect_factory,
        ) as ws:
            stats["sessions"] = 1
            stats["transport_connected"] = True
            await ws.send(json.dumps(hello))
            while time.monotonic() - started < max_seconds_per_session:
                if int(stats["messages_received"]) >= max_messages_per_session:
                    break
                if time.monotonic() - last_status >= heartbeat_interval_seconds:
                    admission_ready = _refresh_current_health(
                        selected,
                        symbol_health,
                        redis_client,
                        now_ns=datetime_epoch_ns(datetime.now(UTC)),
                    )
                    current_data_redis_ack = admission_ready
                    provider_health = {
                        "state": (
                            "RAW_QUARANTINE_STREAM_READY"
                            if admission_ready
                            else "OPTIONAL_CONNECTED_NO_CURRENT_DATA"
                        ),
                        "trainer_consumable": False,
                        "typed_missing": not admission_ready,
                    }
                    payload = _base_status(
                        symbols=symbols,
                        subscribed_symbols=selected,
                        max_symbols=int(max_symbols),
                        opt_in=True,
                        credential_present=True,
                        redis_ok=current_data_redis_ack,
                        stream_connected=True,
                        classification=(
                            "V2_COINAPI_WSDS_RAW_QUARANTINE_READY"
                            if admission_ready
                            else "V2_COINAPI_WSDS_OPTIONAL_CONNECTED_NO_DATA"
                        ),
                        blocker=(
                            None
                            if admission_ready
                            else "AWAITING_NON_POISONABLE_PER_SYMBOL_CADENCE_BASIS"
                        ),
                        stats=_combined_session_stats(aggregate_stats, stats),
                        data_types=data_types,
                        ws_url=ws_url,
                        provider_health=provider_health,
                        symbol_health=symbol_health,
                    )
                    _publish_status(
                        payload,
                        status_paths,
                        redis_client=redis_client,
                        ttl_seconds=ttl_seconds,
                        stats=stats,
                    )
                    last_status = time.monotonic()
                receive_timeout_seconds = _adaptive_receive_timeout_seconds(
                    selected,
                    symbol_health,
                    heartbeat_interval_seconds=heartbeat_interval_seconds,
                    now_ns=datetime_epoch_ns(datetime.now(UTC)),
                )
                try:
                    raw = await asyncio.wait_for(
                        ws.recv(),
                        timeout=receive_timeout_seconds,
                    )
                except TimeoutError:
                    current_data_redis_ack = _refresh_current_health(
                        selected,
                        symbol_health,
                        redis_client,
                        now_ns=datetime_epoch_ns(datetime.now(UTC)),
                    )
                    bootstrap_symbols = tuple(
                        candidate for candidate in selected if cadence_bases[candidate] is None
                    )
                    if bootstrap_symbols and all(
                        symbol_health[candidate].get("cadence_basis_write_final") is True
                        for candidate in bootstrap_symbols
                    ):
                        stats["cadence_bootstrap_session_rotation_requested"] = True
                        break
                    last_status = 0.0
                    continue
                observed_at = datetime.now(UTC)
                stats["messages_received"] += 1
                stats["last_message_utc"] = _utc_iso()
                try:
                    message = _loads_bounded_json(
                        raw,
                        max_bytes=MAX_WS_MESSAGE_BYTES,
                        max_depth=MAX_WS_JSON_DEPTH,
                        max_items=MAX_WS_JSON_ITEMS,
                    )
                    if not isinstance(message, dict):
                        stats["parse_errors"] += 1
                        continue
                    stats["messages_parsed"] += 1
                    message_error = _provider_message_error(message)
                    if message_error is not None:
                        stats.update(message_error)
                        stats["provider_health"] = message_error
                        for state in symbol_health.values():
                            _clear_current_health(state, "PROVIDER_ERROR_MESSAGE")
                        current_data_redis_ack = False
                        break
                    stats["authenticated_transport_succeeded"] = True
                    matched_symbol = symbol_map.get(_message_symbol_id(message))
                    if matched_symbol is None:
                        continue
                    state = symbol_health[matched_symbol]
                    _clear_current_health(state, "AWAITING_CURRENT_ACCEPTED_SAMPLE")
                    current_data_redis_ack = False
                    state["observed"] = True
                    state["observed_count"] = int(state["observed_count"]) + 1
                    stats["selected_messages_observed"] += 1
                    snapshot = _snapshot_from_message(
                        message,
                        observed_at=observed_at,
                        expected_symbol_id=_message_symbol_id(message),
                    )
                    if snapshot is None:
                        stats["schema_rejected_messages"] += 1
                        continue
                    try:
                        normalized = normalize_wsds_snapshot(
                            symbol=matched_symbol,
                            snapshot=snapshot,
                            timeframes=DEFAULT_TIMEFRAMES,
                        )
                    except ValueError:
                        stats["schema_rejected_messages"] += 1
                        continue
                    state["schema_valid"] = True
                    state["schema_valid_count"] = int(state["schema_valid_count"]) + 1
                    stats["schema_valid_messages"] += 1
                    stats["real_messages_received"] += 1
                    quarantine_payload = normalized.get("quarantine_payload")
                    event_identity = normalized.get("event_identity_ns")
                    quarantine_key = normalized.get("quarantine_key")
                    coinapi_symbol_id = coinapi_symbol_ids[matched_symbol]
                    expected_data_key = WS_DATA_KEY_TEMPLATE.format(
                        coinapi_symbol_id=coinapi_symbol_id,
                        symbol=matched_symbol,
                    )
                    if (
                        not isinstance(quarantine_payload, dict)
                        or not isinstance(event_identity, str)
                        or not isinstance(quarantine_key, str)
                        or quarantine_key != expected_data_key
                    ):
                        stats["schema_rejected_messages"] += 1
                        continue
                    serialized = _canonical_json(quarantine_payload)
                    if serialized is None:
                        stats["schema_rejected_messages"] += 1
                        continue
                    provider_received_identity = parse_provider_timestamp(
                        quarantine_payload.get("provider_received_time")
                    )
                    observed_identity = parse_provider_timestamp(
                        quarantine_payload.get("observed_at")
                    )
                    if provider_received_identity is None or observed_identity is None:
                        stats["schema_rejected_messages"] += 1
                        continue
                    digest = _provider_content_digest(quarantine_payload)
                    if digest is None:
                        stats["schema_rejected_messages"] += 1
                        continue
                    conflict_key = WS_CONFLICT_KEY_TEMPLATE.format(
                        coinapi_symbol_id=coinapi_symbol_id,
                        symbol=matched_symbol,
                        event_ns=event_identity,
                        digest=digest,
                    )
                    fence_key = WS_FENCE_KEY_TEMPLATE.format(
                        coinapi_symbol_id=coinapi_symbol_id,
                        symbol=matched_symbol,
                    )
                    fence_result, payload_ttl_ms = _atomic_fenced_quarantine_write(
                        redis_client,
                        fence_key=fence_key,
                        data_key=quarantine_key,
                        conflict_key=conflict_key,
                        event_identity_ns=event_identity,
                        payload=quarantine_payload,
                        ex=ttl_seconds,
                    )
                    stats["last_fence_result"] = fence_result
                    stats["last_payload_ttl_ms"] = payload_ttl_ms
                    if fence_result == _FENCE_COMMITTED:
                        event_ns = int(event_identity)
                        sample_fresh = _record_committed_event(
                            state,
                            cadence_basis=cadence_bases[matched_symbol],
                            session_anchor_ns=session_anchor_ns,
                            event_ns=event_ns,
                            provider_received_ns=provider_received_identity[1],
                            observed_ns=observed_identity[1],
                            data_key=quarantine_key,
                            payload_ttl_ms=payload_ttl_ms,
                        )
                        sample_added = _append_bootstrap_sample(
                            bootstrap_samples[matched_symbol],
                            session_anchor_ns=session_anchor_ns,
                            event_ns=event_ns,
                            provider_received_ns=provider_received_identity[1],
                            observed_ns=observed_identity[1],
                        )
                        state["provisional_cadence_sample_count"] = len(
                            bootstrap_samples[matched_symbol]
                        )
                        if sample_added and cadence_bases[matched_symbol] is None:
                            provisional_payload = _build_provisional_cadence_payload(
                                bootstrap_samples[matched_symbol],
                                symbol=matched_symbol,
                                coinapi_symbol_id=coinapi_symbol_id,
                                api_key=api_key,
                            )
                            provisional_write_state = (
                                _persist_provisional_cadence_payload(
                                    redis_client,
                                    symbol=matched_symbol,
                                    coinapi_symbol_id=coinapi_symbol_id,
                                    api_key=api_key,
                                    payload=provisional_payload,
                                )
                                if provisional_payload is not None
                                else _CADENCE_ERROR
                            )
                            state["provisional_cadence_write_state"] = provisional_write_state
                            if provisional_write_state in {
                                _CADENCE_COMMITTED,
                                _CADENCE_CURRENT,
                            }:
                                stats["provisional_cadence_records_persisted"] += 1
                            elif provisional_write_state in {
                                _CADENCE_OLDER,
                                _CADENCE_CONFLICT,
                            }:
                                stats["provisional_cadence_write_rejections"] += 1
                            else:
                                stats["redis_write_failures"] += 1
                        if (
                            len(bootstrap_samples[matched_symbol]) >= CADENCE_BOOTSTRAP_SAMPLE_COUNT
                            and state.get("cadence_basis_write_final") is not True
                        ):
                            learned_basis = _build_authenticated_cadence_basis(
                                bootstrap_samples[matched_symbol],
                                symbol=matched_symbol,
                                coinapi_symbol_id=coinapi_symbol_id,
                                api_key=api_key,
                            )
                            cadence_key = _cadence_state_key(
                                symbol=matched_symbol,
                                coinapi_symbol_id=coinapi_symbol_id,
                                api_key=api_key,
                            )
                            cadence_write_state = (
                                _atomic_persist_authenticated_cadence_basis(
                                    redis_client,
                                    key=cadence_key,
                                    symbol=matched_symbol,
                                    coinapi_symbol_id=coinapi_symbol_id,
                                    api_key=api_key,
                                    basis=learned_basis,
                                )
                                if learned_basis is not None and cadence_key is not None
                                else _CADENCE_ERROR
                            )
                            persisted = cadence_write_state in {
                                _CADENCE_COMMITTED,
                                _CADENCE_CURRENT,
                            }
                            state["cadence_basis_write_state"] = cadence_write_state
                            state["cadence_basis_persisted"] = persisted
                            state["cadence_basis_write_final"] = (
                                cadence_write_state != _CADENCE_ERROR
                            )
                            if persisted:
                                stats["cadence_bases_persisted"] += 1
                                if not _delete_provisional_cadence(
                                    redis_client,
                                    symbol=matched_symbol,
                                    coinapi_symbol_id=coinapi_symbol_id,
                                    api_key=api_key,
                                ):
                                    stats["redis_write_failures"] += 1
                            elif cadence_write_state in {
                                _CADENCE_OLDER,
                                _CADENCE_CONFLICT,
                            }:
                                stats["cadence_basis_write_rejections"] += 1
                            else:
                                stats["redis_write_failures"] += 1
                        if sample_fresh:
                            stats["fresh_messages"] += 1
                        stats["committed_messages"] += 1
                        stats["snapshots_written"] += 1
                        stats["last_snapshot_utc"] = _utc_iso()
                    elif fence_result == _FENCE_OLDER:
                        stats["older_messages_rejected"] += 1
                    elif fence_result in {_FENCE_DUPLICATE, _FENCE_CONFLICT_DUPLICATE}:
                        stats["duplicate_messages_rejected"] += 1
                    elif fence_result == _FENCE_CONFLICT:
                        stats["conflicting_messages_quarantined"] += 1
                    else:
                        stats["redis_write_failures"] += 1
                    current_data_redis_ack = _refresh_current_health(
                        selected,
                        symbol_health,
                        redis_client,
                        now_ns=datetime_epoch_ns(datetime.now(UTC)),
                    )
                    bootstrap_symbols = tuple(
                        candidate for candidate in selected if cadence_bases[candidate] is None
                    )
                    if bootstrap_symbols and all(
                        symbol_health[candidate].get("cadence_basis_write_final") is True
                        for candidate in bootstrap_symbols
                    ):
                        stats["cadence_bootstrap_session_rotation_requested"] = True
                        break
                except Exception:
                    stats["parse_errors"] += 1
    except Exception as exc:
        error_metadata = _ws_exception_metadata(exc)
        stats.update(error_metadata)
        stats["provider_health"] = error_metadata
    admission_ready = _refresh_current_health(
        selected,
        symbol_health,
        redis_client,
        now_ns=datetime_epoch_ns(datetime.now(UTC)),
    )
    current_data_redis_ack = admission_ready
    stats["symbol_health"] = symbol_health
    stats["stream_admission_ready"] = admission_ready
    stats["current_data_redis_ack"] = current_data_redis_ack
    stats["closed_without_real_messages"] = int(stats["schema_valid_messages"]) == 0
    stats["closed_without_committed_messages"] = int(stats["committed_messages"]) == 0
    session_provider_health = stats.get("provider_health")
    if not isinstance(session_provider_health, dict):
        session_provider_health = {
            "state": (
                "RAW_QUARANTINE_STREAM_READY" if admission_ready else "OPTIONAL_NO_CURRENT_DATA"
            ),
            "trainer_consumable": False,
            "typed_missing": not admission_ready,
        }
    terminal_error = session_provider_health.get("provider_error_class")
    if terminal_error:
        final_classification = "V2_COINAPI_WSDS_OPTIONAL_AUTH_UNAVAILABLE"
        final_blocker = f"PROVIDER_{terminal_error}"
        final_admission = False
    elif admission_ready and current_data_redis_ack:
        final_classification = "V2_COINAPI_WSDS_RAW_QUARANTINE_READY"
        final_blocker = None
        final_admission = True
    else:
        final_classification = "V2_COINAPI_WSDS_OPTIONAL_NO_CURRENT_DATA"
        final_blocker = "AWAITING_NON_POISONABLE_PER_SYMBOL_CADENCE_BASIS"
        final_admission = False
    final_payload = _base_status(
        symbols=symbols,
        subscribed_symbols=selected,
        max_symbols=int(max_symbols),
        opt_in=True,
        credential_present=True,
        redis_ok=current_data_redis_ack,
        stream_connected=final_admission,
        classification=final_classification,
        blocker=final_blocker,
        stats=_combined_session_stats(aggregate_stats, stats),
        data_types=data_types,
        ws_url=ws_url,
        provider_health=session_provider_health,
        symbol_health=symbol_health,
    )
    _publish_status(
        final_payload,
        status_paths,
        redis_client=redis_client,
        ttl_seconds=ttl_seconds,
        stats=stats,
    )
    return stats


async def _run_connected_loop(
    args: argparse.Namespace,
    symbols: tuple[str, ...],
    api_key: str,
    redis_client: Any,
) -> dict[str, Any]:
    configured_data_types = _subscribe_data_types()
    data_types = configured_data_types or []
    runtime_config_error = _runtime_config_error(args)
    configured_ws_url = os.getenv("COINAPI_WSDS_URL", DEFAULT_WS_URL)
    try:
        ws_url = _validate_ws_url(configured_ws_url)
        endpoint_valid = True
    except ValueError:
        ws_url = DEFAULT_WS_URL
        endpoint_valid = False
    exchange_id_valid = (
        _validated_exchange_id(os.getenv("COINAPI_PRIMARY_EXCHANGE_ID", "BINANCEFTS")) is not None
    )
    status_paths = (args.out, args.out_public, args.out_worklog)
    total_started = time.monotonic()
    aggregate: dict[str, Any] = {
        "sessions": 0,
        "messages_received": 0,
        "selected_messages_observed": 0,
        "schema_valid_messages": 0,
        "schema_rejected_messages": 0,
        "fresh_messages": 0,
        "committed_messages": 0,
        "receipt_accepted_messages": 0,
        "older_messages_rejected": 0,
        "duplicate_messages_rejected": 0,
        "conflicting_messages_quarantined": 0,
        "real_messages_received": 0,
        "messages_parsed": 0,
        "snapshots_written": 0,
        "microfeatures_written": 0,
        "parse_errors": 0,
        "redis_write_failures": 0,
        "authenticated_cadence_bases_loaded": 0,
        "cadence_bases_persisted": 0,
        "cadence_basis_write_rejections": 0,
        "provisional_cadence_records_loaded": 0,
        "provisional_cadence_records_persisted": 0,
        "provisional_cadence_write_rejections": 0,
        "transport_connected": False,
        "authenticated_transport_succeeded": False,
        "reconnect_count": 0,
        "last_message_utc": None,
        "last_snapshot_utc": None,
        "consecutive_zero_message_failures": 0,
        "last_backoff_seconds": None,
    }
    if (
        not endpoint_valid
        or not exchange_id_valid
        or configured_data_types is None
        or runtime_config_error is not None
    ):
        payload = _blocked_status(
            symbols=symbols,
            opt_in=True,
            credential_present=True,
            redis_ok=False,
            data_types=data_types,
            ws_url=ws_url,
            endpoint_valid=endpoint_valid,
            exchange_id_valid=exchange_id_valid,
            redis_available=redis_client is not None,
            subscription_types_valid=configured_data_types is not None,
            runtime_config_error=runtime_config_error,
        )
        _publish_status(
            payload,
            status_paths,
            redis_client=redis_client,
            ttl_seconds=args.ttl_seconds,
            stats=aggregate,
        )
        aggregate["configuration_valid"] = False
        return aggregate
    if redis_client is None:
        payload = _base_status(
            symbols=symbols,
            subscribed_symbols=(),
            max_symbols=int(args.max_symbols),
            opt_in=True,
            credential_present=True,
            redis_ok=False,
            stream_connected=False,
            classification="V2_COINAPI_WSDS_OPTIONAL_RETRY_STATE_UNAVAILABLE",
            blocker="DURABLE_RETRY_STATE_UNAVAILABLE",
            stats=aggregate,
            data_types=data_types,
            ws_url=ws_url,
            provider_health={
                "state": "OPTIONAL_RETRY_STATE_UNAVAILABLE",
                "provider_error_class": "DURABLE_RETRY_STATE_UNAVAILABLE",
                "typed_missing": True,
                "trainer_consumable": False,
            },
            symbol_health=_initial_symbol_health(symbols),
        )
        _publish_status(
            payload,
            status_paths,
            redis_client=redis_client,
            ttl_seconds=args.ttl_seconds,
            stats=aggregate,
        )
        return aggregate
    if _env_bool(AUTH_LATCH_RESET_ENV, False):
        reset_healthy = _clear_auth_state(redis_client, api_key=api_key)
        os.environ.pop(AUTH_LATCH_RESET_ENV, None)
        if not reset_healthy:
            aggregate["durable_auth_retry_state_healthy"] = False
            return aggregate
    auth_state_exists = _auth_state_record_exists(redis_client, api_key=api_key)
    auth_state = _load_auth_state(redis_client, api_key=api_key)
    if auth_state_exists is None or (auth_state_exists is False and auth_state is not None):
        payload = _base_status(
            symbols=symbols,
            subscribed_symbols=(),
            max_symbols=int(args.max_symbols),
            opt_in=True,
            credential_present=True,
            redis_ok=False,
            stream_connected=False,
            classification="V2_COINAPI_WSDS_OPTIONAL_RETRY_STATE_UNAVAILABLE",
            blocker="DURABLE_RETRY_STATE_UNAVAILABLE",
            stats=aggregate,
            data_types=data_types,
            ws_url=ws_url,
            provider_health={
                "state": "OPTIONAL_RETRY_STATE_UNAVAILABLE",
                "provider_error_class": "DURABLE_RETRY_STATE_UNAVAILABLE",
                "typed_missing": True,
                "trainer_consumable": False,
            },
            symbol_health=_initial_symbol_health(symbols),
        )
        _publish_status(
            payload,
            status_paths,
            redis_client=redis_client,
            ttl_seconds=args.ttl_seconds,
            stats=aggregate,
        )
        aggregate["durable_auth_retry_state_healthy"] = False
        return aggregate
    if auth_state_exists is True and auth_state is None:
        payload = _base_status(
            symbols=symbols,
            subscribed_symbols=(),
            max_symbols=int(args.max_symbols),
            opt_in=True,
            credential_present=True,
            redis_ok=False,
            stream_connected=False,
            classification="V2_COINAPI_WSDS_OPTIONAL_RETRY_STATE_UNAVAILABLE",
            blocker="DURABLE_RETRY_STATE_INVALID",
            stats=aggregate,
            data_types=data_types,
            ws_url=ws_url,
            provider_health={
                "state": "OPTIONAL_RETRY_STATE_INVALID",
                "provider_error_class": "DURABLE_RETRY_STATE_INVALID",
                "typed_missing": True,
                "trainer_consumable": False,
            },
            symbol_health=_initial_symbol_health(symbols),
        )
        _publish_status(
            payload,
            status_paths,
            redis_client=redis_client,
            ttl_seconds=args.ttl_seconds,
            stats=aggregate,
        )
        aggregate["durable_auth_retry_state_healthy"] = False
        return aggregate
    aggregate["durable_auth_retry_state_healthy"] = True
    consecutive_failures = 0
    while time.monotonic() - total_started < args.total_seconds:
        now_ns = time.time_ns()
        if auth_state is not None and now_ns < auth_state["next_probe_at_ns"]:
            remaining_backoff = (auth_state["next_probe_at_ns"] - now_ns) / 1_000_000_000
            aggregate["last_backoff_seconds"] = remaining_backoff
            prior_error = auth_state["last_error_class"]
            prior_was_no_data = prior_error == "CONNECTED_NO_DATA"
            payload = _base_status(
                symbols=symbols,
                subscribed_symbols=(),
                max_symbols=int(args.max_symbols),
                opt_in=True,
                credential_present=True,
                redis_ok=False,
                stream_connected=False,
                classification=(
                    "V2_COINAPI_WSDS_OPTIONAL_CONNECTED_NO_DATA"
                    if prior_was_no_data
                    else "V2_COINAPI_WSDS_OPTIONAL_UNAVAILABLE"
                ),
                blocker="AWAITING_DURABLE_OPTIONAL_REPROBE_WINDOW",
                stats=aggregate,
                data_types=data_types,
                ws_url=ws_url,
                provider_health={
                    "state": (
                        "CONNECTED_NO_DATA" if prior_was_no_data else "OPTIONAL_UNAVAILABLE_BACKOFF"
                    ),
                    "provider_error_class": prior_error,
                    "http_status": auth_state["last_http_status"],
                    "failure_count": auth_state["failure_count"],
                    "next_probe_at_ns": auth_state["next_probe_at_ns"],
                    "retry_after_honored": auth_state["retry_after_honored"],
                    "credential_fingerprint_emitted": False,
                    "signature_emitted": False,
                    "typed_missing": True,
                    "trainer_consumable": False,
                },
                symbol_health=_initial_symbol_health(symbols),
            )
            _publish_status(
                payload,
                status_paths,
                redis_client=redis_client,
                ttl_seconds=args.ttl_seconds,
                stats=aggregate,
            )
            total_remaining = float(args.total_seconds) - (time.monotonic() - total_started)
            if total_remaining <= 0:
                return aggregate
            await asyncio.sleep(
                min(
                    remaining_backoff,
                    max(0.001, float(args.heartbeat_interval_seconds)),
                    total_remaining,
                )
            )
            continue
        try:
            stats = await _run_session(
                symbols=symbols,
                api_key=api_key,
                redis_client=redis_client,
                ttl_seconds=args.ttl_seconds,
                ws_url=ws_url,
                data_types=data_types,
                max_symbols=args.max_symbols,
                max_seconds_per_session=args.max_seconds_per_session,
                max_messages_per_session=args.max_messages_per_session,
                heartbeat_interval_seconds=args.heartbeat_interval_seconds,
                status_paths=status_paths,
                aggregate_stats=aggregate,
            )
        except Exception as exc:
            stats = {
                "sessions": 0,
                "messages_received": 0,
                "selected_messages_observed": 0,
                "schema_valid_messages": 0,
                "schema_rejected_messages": 0,
                "fresh_messages": 0,
                "committed_messages": 0,
                "receipt_accepted_messages": 0,
                "older_messages_rejected": 0,
                "duplicate_messages_rejected": 0,
                "conflicting_messages_quarantined": 0,
                "real_messages_received": 0,
                "messages_parsed": 0,
                "snapshots_written": 0,
                "microfeatures_written": 0,
                "parse_errors": 0,
                "redis_write_failures": 0,
                "closed_without_real_messages": True,
                **_ws_exception_metadata(exc),
            }
            stats["provider_health"] = dict(stats)
        for key in (
            "sessions",
            "messages_received",
            "selected_messages_observed",
            "schema_valid_messages",
            "schema_rejected_messages",
            "fresh_messages",
            "committed_messages",
            "receipt_accepted_messages",
            "older_messages_rejected",
            "duplicate_messages_rejected",
            "conflicting_messages_quarantined",
            "real_messages_received",
            "messages_parsed",
            "snapshots_written",
            "microfeatures_written",
            "parse_errors",
            "redis_write_failures",
            "authenticated_cadence_bases_loaded",
            "cadence_bases_persisted",
            "cadence_basis_write_rejections",
            "provisional_cadence_records_loaded",
            "provisional_cadence_records_persisted",
            "provisional_cadence_write_rejections",
        ):
            aggregate[key] += int(stats.get(key) or 0)
        aggregate["transport_connected"] = bool(aggregate.get("transport_connected")) or bool(
            stats.get("transport_connected")
        )
        aggregate["authenticated_transport_succeeded"] = bool(
            aggregate.get("authenticated_transport_succeeded")
        ) or bool(stats.get("authenticated_transport_succeeded"))
        for key in (
            "last_message_utc",
            "last_snapshot_utc",
            "last_error_type",
            "last_close_code",
            "last_close_reason_class",
            "provider_http_status",
            "provider_error_class",
            "quota_metadata",
        ):
            if stats.get(key) is not None:
                aggregate[key] = stats.get(key)
        committed_messages = int(stats.get("committed_messages") or 0)
        admission_commits = committed_messages if stats.get("stream_admission_ready") is True else 0
        session_health = stats.get("provider_health")
        if not isinstance(session_health, dict):
            session_health = {}
        provider_error = session_health.get("provider_error_class")
        provider_http_status = session_health.get("provider_http_status")
        terminal_provider_block = (
            provider_http_status in TERMINAL_PROVIDER_HTTP_STATUSES
            or provider_error in TERMINAL_PROVIDER_ERROR_CLASSES
        )
        quota_metadata = session_health.get("quota_metadata")
        provider_retry_delay = _provider_retry_delay_seconds(
            quota_metadata if isinstance(quota_metadata, dict) else None
        )
        real_messages = int(stats.get("real_messages_received") or 0)
        transport_connected = stats.get("transport_connected") is True
        durable_unavailable_error: str | None = None
        if provider_error is None and real_messages == 0:
            durable_unavailable_error = (
                "CONNECTED_NO_DATA" if transport_connected else "TRANSIENT_UNAVAILABLE"
            )
        auth_state_write_result: str | None = None
        durable_provider_failure = type(provider_error) is str and (
            provider_error in DURABLE_PROVIDER_ERROR_CLASSES
            or provider_http_status in TERMINAL_PROVIDER_HTTP_STATUSES | {RATE_LIMITED_HTTP_STATUS}
        )
        if durable_provider_failure or durable_unavailable_error is not None:
            next_auth_state = _build_auth_state(
                api_key=api_key,
                http_status=(provider_http_status if type(provider_http_status) is int else None),
                error_class=(
                    provider_error
                    if type(provider_error) is str
                    else durable_unavailable_error or "TRANSIENT_UNAVAILABLE"
                ),
                prior_state=auth_state,
                quota_metadata=quota_metadata if isinstance(quota_metadata, dict) else None,
            )
            auth_state_write_result = (
                _persist_auth_state(
                    redis_client,
                    api_key=api_key,
                    state=next_auth_state,
                )
                if next_auth_state is not None
                else _AUTH_STATE_ERROR
            )
            aggregate["durable_auth_retry_write_state"] = auth_state_write_result
            if auth_state_write_result in {
                _AUTH_STATE_COMMITTED,
                _AUTH_STATE_CURRENT,
            }:
                auth_state = next_auth_state
                aggregate["durable_auth_retry_state_healthy"] = True
            else:
                aggregate["durable_auth_retry_state_healthy"] = False
        elif (
            stats.get("authenticated_transport_succeeded") is True
            and provider_error is None
            and real_messages > 0
        ):
            aggregate["durable_auth_retry_state_healthy"] = _clear_auth_state(
                redis_client,
                api_key=api_key,
            )
            auth_state = None
        consecutive_failures, backoff_seconds = _next_backoff(
            consecutive_failures,
            committed_messages=admission_commits,
            provider_retry_delay_seconds=provider_retry_delay,
        )
        if admission_commits == 0:
            aggregate["reconnect_count"] += 1
        aggregate["consecutive_zero_message_failures"] = consecutive_failures
        aggregate["last_backoff_seconds"] = backoff_seconds
        blocker: str | None
        if aggregate.get("durable_auth_retry_state_healthy") is False:
            backoff_seconds = None
            aggregate["last_backoff_seconds"] = None
            classification = "V2_COINAPI_WSDS_OPTIONAL_RETRY_STATE_UNAVAILABLE"
            blocker = "DURABLE_RETRY_STATE_WRITE_FAILED"
            provider_state = "OPTIONAL_RETRY_STATE_UNAVAILABLE"
        elif terminal_provider_block:
            classification = "V2_COINAPI_WSDS_OPTIONAL_AUTH_UNAVAILABLE"
            blocker = f"PROVIDER_{provider_error or 'AUTHORIZATION_REJECTED'}"
            provider_state = "OPTIONAL_AUTH_BACKOFF"
            if auth_state is not None:
                backoff_seconds = max(
                    0.0,
                    (auth_state["next_probe_at_ns"] - time.time_ns()) / 1_000_000_000,
                )
                aggregate["last_backoff_seconds"] = backoff_seconds
        elif provider_error == "RATE_LIMITED":
            classification = "V2_COINAPI_WSDS_OPTIONAL_RATE_LIMITED"
            blocker = "AWAITING_PROVIDER_RETRY_WINDOW"
            provider_state = "OPTIONAL_RATE_LIMITED"
            if auth_state is not None:
                backoff_seconds = max(
                    0.0,
                    (auth_state["next_probe_at_ns"] - time.time_ns()) / 1_000_000_000,
                )
                aggregate["last_backoff_seconds"] = backoff_seconds
        elif durable_unavailable_error is not None:
            classification = (
                "V2_COINAPI_WSDS_OPTIONAL_CONNECTED_NO_DATA"
                if durable_unavailable_error == "CONNECTED_NO_DATA"
                else "V2_COINAPI_WSDS_OPTIONAL_TRANSIENT_UNAVAILABLE"
            )
            blocker = "AWAITING_DURABLE_OPTIONAL_REPROBE_WINDOW"
            provider_state = durable_unavailable_error
            if auth_state is not None:
                backoff_seconds = max(
                    0.0,
                    (auth_state["next_probe_at_ns"] - time.time_ns()) / 1_000_000_000,
                )
                aggregate["last_backoff_seconds"] = backoff_seconds
        else:
            classification = "V2_COINAPI_WSDS_OPTIONAL_RECONNECTING"
            blocker = "NO_ALL_SYMBOL_ADMISSION_SESSION" if admission_commits == 0 else None
            provider_state = "TRANSIENT_UNAVAILABLE"
        public_provider_health = {
            "state": provider_state,
            "provider_error_class": provider_error or durable_unavailable_error,
            "http_status": provider_http_status,
            "close_code": session_health.get("last_close_code"),
            "close_reason_class": session_health.get("last_close_reason_class"),
            "quota_metadata": quota_metadata if isinstance(quota_metadata, dict) else {},
            "raw_provider_reason_recorded": False,
            "raw_provider_body_recorded": False,
            "trainer_consumable": False,
            "typed_missing": True,
            "durable_auth_retry_write_state": auth_state_write_result,
            "credential_fingerprint_emitted": False,
            "signature_emitted": False,
            **OPTIONAL_SOURCE_FIELDS,
        }
        payload = _base_status(
            symbols=symbols,
            subscribed_symbols=(),
            max_symbols=int(args.max_symbols),
            opt_in=True,
            credential_present=True,
            redis_ok=bool(stats.get("current_data_redis_ack")),
            stream_connected=False,
            classification=classification,
            blocker=blocker,
            stats=aggregate,
            data_types=data_types,
            ws_url=ws_url,
            provider_health=public_provider_health,
            symbol_health=(
                stats.get("symbol_health")
                if isinstance(stats.get("symbol_health"), dict)
                else _initial_symbol_health(symbols)
            ),
        )
        _publish_status(
            payload,
            status_paths,
            redis_client=redis_client,
            ttl_seconds=args.ttl_seconds,
            stats=aggregate,
        )
        if aggregate.get("durable_auth_retry_state_healthy") is False:
            return aggregate
        if backoff_seconds is not None:
            remaining = float(args.total_seconds) - (time.monotonic() - total_started)
            if remaining > 0:
                await asyncio.sleep(min(backoff_seconds, remaining))
    return aggregate


def _run_blocked_loop(
    args: argparse.Namespace,
    symbols: tuple[str, ...],
) -> dict[str, Any] | None:
    """Supervise dormant prerequisites and transition in place when they recover."""

    while True:
        configured_data_types = _subscribe_data_types()
        data_types = configured_data_types or []
        runtime_config_error = _runtime_config_error(args)
        opt_in = _env_bool(OPT_IN_ENV_VAR, False)
        api_key = _read_secret_value("COINAPI_API_KEY") or _read_secret_value("COINAPI_KEY")
        redis_client = _connect_redis()
        configured_ws_url = os.getenv("COINAPI_WSDS_URL", DEFAULT_WS_URL)
        try:
            ws_url = _validate_ws_url(configured_ws_url)
            endpoint_valid = True
        except ValueError:
            ws_url = DEFAULT_WS_URL
            endpoint_valid = False
        exchange_id_valid = (
            _validated_exchange_id(os.getenv("COINAPI_PRIMARY_EXCHANGE_ID", "BINANCEFTS"))
            is not None
        )
        prerequisites_ready = (
            opt_in
            and bool(api_key)
            and websockets is not None
            and endpoint_valid
            and exchange_id_valid
            and configured_data_types is not None
            and runtime_config_error is None
            and redis_client is not None
        )
        if prerequisites_ready:
            assert api_key is not None
            aggregate = asyncio.run(_run_connected_loop(args, symbols, api_key, redis_client))
            if not args.loop:
                return aggregate
            print(json.dumps({"classification": "V2_COINAPI_WSDS_PHASE_EXITED", **aggregate}))
            sys.stdout.flush()
            time.sleep(max(30, int(args.interval_seconds)))
            continue
        payload = _blocked_status(
            symbols=symbols,
            opt_in=opt_in,
            credential_present=bool(api_key),
            redis_ok=False,
            data_types=data_types,
            ws_url=ws_url,
            endpoint_valid=endpoint_valid,
            exchange_id_valid=exchange_id_valid,
            redis_available=redis_client is not None,
            subscription_types_valid=configured_data_types is not None,
            runtime_config_error=runtime_config_error,
        )
        paths = (args.out, args.out_public, args.out_worklog)
        _publish_status(
            payload,
            paths,
            redis_client=redis_client,
            ttl_seconds=args.ttl_seconds,
            stats=None,
        )
        print(
            json.dumps(
                {
                    "classification": payload["classification"],
                    "blocked_reason": payload["blocked_reason"],
                }
            )
        )
        sys.stdout.flush()
        if not args.loop:
            return None
        time.sleep(max(30, int(args.interval_seconds)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=0,
        help=(
            "Maximum symbols to subscribe per WSDS session; " "0 means the full V2 symbol universe."
        ),
    )
    parser.add_argument("--ttl-seconds", type=int, default=300)
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=30.0)
    parser.add_argument("--max-seconds-per-session", type=float, default=600.0)
    parser.add_argument("--max-messages-per-session", type=int, default=5000)
    parser.add_argument("--total-seconds", type=float, default=20.0)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--out", type=Path, default=DEFAULT_STATUS_PATH)
    parser.add_argument("--out-public", type=Path, default=DEFAULT_PUBLIC_PAYLOAD_PATH)
    parser.add_argument("--out-worklog", type=Path, default=DEFAULT_WORKLOG_PATH)
    args = parser.parse_args(argv)
    if args.loop and args.once:
        print("ERROR: --loop and --once are mutually exclusive", file=sys.stderr)
        return 2
    symbols = tuple(
        resolve_symbols(
            explicit=args.symbols,
            smoke_test=bool(args.smoke_test),
            include_baseline=True,
        )
    )
    aggregate = _run_blocked_loop(args, symbols)
    if aggregate is not None:
        print(json.dumps({"classification": "V2_COINAPI_WSDS_LOOP_EXITED", **aggregate}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
