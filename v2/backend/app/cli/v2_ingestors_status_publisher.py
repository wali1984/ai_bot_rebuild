"""V2 ingestors status publisher — collects live ingestor heartbeats from Redis
and writes a single JSON payload to the public frontend path.

Writes V2 namespace ONLY. No legacy Redis writes. No exchange mutation.
Live gate remains blocked_human_only.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.cli.v2_dynamic_symbol_discovery_free_tier import (
    DEFAULT_REDIS_RETENTION_SECONDS as DYNAMIC_DISCOVERY_REDIS_RETENTION_SECONDS,
)
from v2.backend.app.cli.v2_public_intel_free_tier import (
    DEFAULT_REDIS_RETENTION_SECONDS as PUBLIC_INTEL_REDIS_RETENTION_SECONDS,
)

V2_REDIS_PREFIX = "v2:"
REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_ROOT = REPO_ROOT / "v2/frontend/public"
DEFAULT_PAYLOAD_PATH = (
    PUBLIC_ROOT / "operator_runtime/v2_ingestors_status/latest/v2_ingestors_status.json"
)
PUBLIC_STATUS_PATHS = {
    "kucoin": PUBLIC_ROOT
    / "operator_runtime/v2_kucoin_ingestor/latest/v2_kucoin_ingestor_status.json",
    "coinapi_rest": PUBLIC_ROOT
    / "operator_runtime/v2_coinapi_rest_ingestor/latest/v2_coinapi_rest_ingestor_status.json",
    "coinapi_wsds": PUBLIC_ROOT
    / "operator_runtime/v2_coinapi_wsds/latest/v2_coinapi_wsds_status.json",
    "binance_kline_wss": PUBLIC_ROOT
    / "operator_runtime/v2_binance_kline_wss/latest/v2_binance_kline_wss_status.json",
    "coinank": PUBLIC_ROOT
    / "operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json",
    "liquidation_wss": PUBLIC_ROOT
    / "operator_runtime/v2_liquidation_wss/latest/v2_liquidation_wss_status.json",
    "liquidation_levels": PUBLIC_ROOT
    / (
        "operator_runtime/v2_liquidation_levels_engine/latest/"
        "v2_liquidation_levels_engine_status.json"
    ),
    "liquidation_runtime": PUBLIC_ROOT
    / "operator_runtime/v2_liquidation_runtime_status/latest/v2_liquidation_runtime_status.json",
}

# Resource-integrity ceilings only.  These limits prevent an observability
# worker from loading an unbounded Redis/file payload; they do not select a
# market, feature, trade, leverage value, or trainer sample.
MAX_STATUS_JSON_BYTES: Final = 4 * 1024 * 1024
MAX_STATUS_TEXT_BYTES: Final = 64 * 1024
MAX_STATUS_JSON_DEPTH: Final = 32
MAX_STATUS_JSON_NODES: Final = 100_000
MAX_STATUS_SCAN_KEYS: Final = 3_000
MAX_STATUS_SCAN_ITERATIONS: Final = 8
MAX_STATUS_SCAN_ROWS_INSPECTED: Final = 10_000
MAX_STATUS_COUNT: Final = 2**63 - 1

JsonObject = dict[str, Any]

REQUIREMENT_CORE_DATA_PLANE: Final = "CORE_DATA_PLANE"
REQUIREMENT_OPTIONAL_ENRICHMENT: Final = "OPTIONAL_ENRICHMENT"
REQUIREMENT_DERIVED_OBSERVABILITY: Final = "DERIVED_OBSERVABILITY"

_BOUNDED_REDIS_STRING_READ_LUA: Final = r"""
local kind = redis.call('TYPE', KEYS[1])
kind = type(kind) == 'table' and kind['ok'] or kind
local ttl = redis.call('PTTL', KEYS[1])
if kind == 'none' then
  return {kind, ttl, 0, false}
end
if kind ~= 'string' then
  return {kind, ttl, 0, false}
end
local length = redis.call('STRLEN', KEYS[1])
if length > tonumber(ARGV[1]) then
  return {kind, ttl, length, false}
end
return {kind, ttl, length, redis.call('GET', KEYS[1])}
"""


class _StatusJsonError(ValueError):
    """A status artifact is invalid or exceeds its observability boundary."""


def _invalid_status_json(reason: str) -> NoReturn:
    raise _StatusJsonError(reason) from None


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis() -> Any | None:
    try:
        import redis
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _bounded_direct_string_utf8_length(value: str, *, maximum_bytes: int) -> int:
    """Count UTF-8 bytes incrementally without first allocating one full copy."""

    total = 0
    for character in value:
        codepoint = ord(character)
        if codepoint <= 0x7F:
            total += 1
        elif codepoint <= 0x7FF:
            total += 2
        elif codepoint <= 0xFFFF:
            if 0xD800 <= codepoint <= 0xDFFF:
                _invalid_status_json("status_json_utf8_invalid")
            total += 3
        else:
            total += 4
        if total > maximum_bytes:
            _invalid_status_json("status_json_byte_limit_exceeded")
    return total


def _parse_json_int(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 19:
        _invalid_status_json("status_json_integer_out_of_range")
    try:
        parsed = int(value)
    except (ValueError, OverflowError):
        _invalid_status_json("status_json_integer_out_of_range")
    if not -(2**63) <= parsed <= 2**63 - 1:
        _invalid_status_json("status_json_integer_out_of_range")
    return parsed


def _parse_json_float(value: str) -> float:
    if len(value) > 64:
        _invalid_status_json("status_json_float_invalid")
    try:
        parsed = float(value)
    except (ValueError, OverflowError):
        _invalid_status_json("status_json_float_invalid")
    if not math.isfinite(parsed):
        _invalid_status_json("status_json_float_invalid")
    return parsed


def _reject_json_constant(_value: str) -> NoReturn:
    _invalid_status_json("status_json_constant_forbidden")


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _invalid_status_json("status_json_duplicate_key")
        result[key] = value
    return result


def _validate_json_tree(value: object) -> None:
    remaining = MAX_STATUS_JSON_NODES
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        remaining -= 1
        if remaining < 0:
            _invalid_status_json("status_json_node_limit_exceeded")
        if depth > MAX_STATUS_JSON_DEPTH:
            _invalid_status_json("status_json_depth_limit_exceeded")
        if item is None or type(item) in {bool, int, str}:
            continue
        if type(item) is float:
            if not math.isfinite(item):
                _invalid_status_json("status_json_float_invalid")
            continue
        if type(item) is list:
            stack.extend((child, depth + 1) for child in cast(list[object], item))
            continue
        if type(item) is dict:
            mapping = cast(dict[object, object], item)
            if any(type(key) is not str for key in mapping):
                _invalid_status_json("status_json_key_invalid")
            stack.extend((child, depth + 1) for child in mapping.values())
            continue
        _invalid_status_json("status_json_type_invalid")


def _decode_status_json(
    raw: object,
    *,
    maximum_bytes: int = MAX_STATUS_JSON_BYTES,
) -> JsonObject | None:
    if type(raw) is bytes:
        encoded = raw
        if not encoded or len(encoded) > maximum_bytes:
            return None
        try:
            text = encoded.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
    elif type(raw) is str:
        text = raw
        if not text:
            return None
        try:
            _bounded_direct_string_utf8_length(text, maximum_bytes=maximum_bytes)
        except _StatusJsonError:
            return None
    else:
        return None
    try:
        decoded: object = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_int=_parse_json_int,
            parse_float=_parse_json_float,
            parse_constant=_reject_json_constant,
        )
        if type(decoded) is not dict:
            return None
        _validate_json_tree(decoded)
    except (_StatusJsonError, json.JSONDecodeError, RecursionError, MemoryError):
        return None
    return cast(JsonObject, decoded)


def _bounded_redis_string(r: Any, key: str, *, maximum_bytes: int) -> tuple[object, int]:
    try:
        response = r.eval(_BOUNDED_REDIS_STRING_READ_LUA, 1, key, maximum_bytes)
    except Exception:
        return None, -2
    if type(response) not in {list, tuple} or len(response) != 4:
        return None, -2
    kind, raw_ttl, raw_length, raw = response
    if type(kind) is bytes:
        try:
            kind = kind.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            return None, -2
    if type(raw_ttl) is not int or type(raw_length) is not int:
        return None, -2
    ttl_ms = raw_ttl
    byte_count = raw_length
    if kind == "none":
        return None, -2
    if kind != "string" or byte_count < 0 or byte_count > maximum_bytes or raw is None:
        return None, ttl_ms
    if type(raw) is bytes:
        if len(raw) != byte_count:
            return None, ttl_ms
    elif type(raw) is str:
        try:
            if _bounded_direct_string_utf8_length(raw, maximum_bytes=maximum_bytes) != byte_count:
                return None, ttl_ms
        except _StatusJsonError:
            return None, ttl_ms
    else:
        return None, ttl_ms
    return raw, ttl_ms


def _get_json(r: Any, key: str) -> JsonObject | None:
    try:
        raw, _ttl_ms = _bounded_redis_string(
            r,
            key,
            maximum_bytes=MAX_STATUS_JSON_BYTES,
        )
        return _decode_status_json(raw)
    except Exception:
        return None


def _get_json_with_pttl(r: Any, key: str) -> tuple[JsonObject | None, int]:
    """Read one JSON string and its PTTL from the same bounded Redis script."""

    try:
        raw, ttl_ms = _bounded_redis_string(
            r,
            key,
            maximum_bytes=MAX_STATUS_JSON_BYTES,
        )
        return _decode_status_json(raw), ttl_ms
    except Exception:
        return None, -2


def _get_text(r: Any, key: str) -> str | None:
    raw, _ttl_ms = _bounded_redis_string(
        r,
        key,
        maximum_bytes=MAX_STATUS_TEXT_BYTES,
    )
    if type(raw) is bytes:
        try:
            raw = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
    return raw.strip() if type(raw) is str and raw.strip() else None


def _read_public_status(name: str) -> JsonObject | None:
    path = PUBLIC_STATUS_PATHS.get(name)
    if path is None:
        return None
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not 0 < before.st_size <= MAX_STATUS_JSON_BYTES:
                return None
            raw = handle.read(MAX_STATUS_JSON_BYTES + 1)
            after = os.fstat(handle.fileno())
        if (
            len(raw) != before.st_size
            or len(raw) > MAX_STATUS_JSON_BYTES
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            return None
        return _decode_status_json(raw)
    except (OSError, ValueError):
        return None


def _mapping(payload: JsonObject | None, key: str) -> JsonObject:
    value = payload.get(key) if payload is not None else None
    return value if isinstance(value, dict) else {}


def _number(value: object) -> int | None:
    if type(value) is bool or value is None:
        return None
    if type(value) is list:
        return len(value)
    if type(value) is int:
        return value if 0 <= value <= MAX_STATUS_COUNT else None
    if type(value) is float:
        return (
            int(value)
            if math.isfinite(value) and value.is_integer() and 0 <= value <= MAX_STATUS_COUNT
            else None
        )
    if type(value) is not str:
        return None
    stripped = value.strip()
    if not stripped or not stripped.isascii() or not stripped.isdecimal() or len(stripped) > 19:
        return None
    try:
        parsed = int(stripped)
    except (ValueError, OverflowError):
        return None
    return parsed if parsed <= MAX_STATUS_COUNT else None


def _max_number(*values: object) -> int:
    nums = [number for number in (_number(value) for value in values) if number is not None]
    return max(nums) if nums else 0


def _first_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _payload_symbols_count(payload: JsonObject | None) -> int:
    if not isinstance(payload, dict):
        return 0
    fetch = _mapping(payload, "fetch")
    public_rest_fetch = _mapping(payload, "public_rest_fetch")
    feature_input = _mapping(payload, "v2_redis_feature_input")
    aggregate = _mapping(payload, "global_aggregate_result")
    return _max_number(
        payload.get("symbols"),
        payload.get("symbols_v2"),
        payload.get("symbol_count"),
        payload.get("symbols_count"),
        fetch.get("symbols_requested"),
        fetch.get("symbols_fetched"),
        public_rest_fetch.get("symbols_requested"),
        public_rest_fetch.get("symbols_fetched"),
        feature_input.get("symbols_requested"),
        feature_input.get("symbols_with_any_input"),
        aggregate.get("n_symbols_observed"),
    )


def _payload_keys_written_count(payload: JsonObject | None) -> int:
    if not isinstance(payload, dict):
        return 0
    stats = _mapping(payload, "stats")
    aggregate = _mapping(payload, "global_aggregate_result")
    return _max_number(
        payload.get("v2_market_keys_written"),
        payload.get("v2_features_keys_written"),
        payload.get("v2_redis_keys_written"),
        payload.get("v2_redis_global_keys_written"),
        payload.get("keys_written"),
        payload.get("successful_symbol_count"),
        payload.get("v2_market_keys_written_count"),
        payload.get("v2_features_keys_written_count"),
        payload.get("v2_redis_keys_written_count"),
        payload.get("v2_redis_global_keys_written_count"),
        payload.get("keys_written_count"),
        stats.get("snapshots_written"),
        stats.get("microfeatures_written"),
        stats.get("ohlcv_keys_written"),
        stats.get("source_keys_written"),
        stats.get("messages_received"),
        aggregate.get("v2_keys_written"),
    )


def _payload_generated_utc(payload: JsonObject | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    fetch = _mapping(payload, "fetch")
    public_rest_fetch = _mapping(payload, "public_rest_fetch")
    return _first_text(
        payload.get("generated_utc"),
        payload.get("generated_at"),
        payload.get("heartbeat_at"),
        payload.get("last_run_ts"),
        payload.get("finished_at"),
        payload.get("finished_utc"),
        payload.get("started_at"),
        payload.get("started_utc"),
        fetch.get("finished_utc"),
        public_rest_fetch.get("finished_utc"),
    )


def _parse_utc(value: object) -> datetime | None:
    if type(value) is not str or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    try:
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def _payload_age_seconds(
    payload: JsonObject | None,
    *,
    now: datetime | None = None,
) -> float | None:
    generated = _payload_generated_utc(payload)
    parsed = _parse_utc(generated)
    if parsed is None:
        return None
    observed_now = now or datetime.now(UTC)
    return (observed_now - parsed).total_seconds()


def _payload_is_recent(
    payload: JsonObject | None,
    *,
    max_age_seconds: int,
    now: datetime | None = None,
) -> bool:
    age_seconds = _payload_age_seconds(payload, now=now)
    return age_seconds is not None and -60.0 <= age_seconds <= float(max_age_seconds)


def _payload_source_event_utc(payload: JsonObject | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    stats = _mapping(payload, "stats")
    source = _mapping(payload, "source")
    fetch = _mapping(payload, "fetch")
    return _first_text(
        payload.get("source_available_at"),
        payload.get("available_at"),
        payload.get("feature_cutoff"),
        payload.get("event_time"),
        payload.get("last_message_utc"),
        payload.get("last_snapshot_utc"),
        stats.get("last_message_utc"),
        stats.get("last_snapshot_utc"),
        source.get("available_at"),
        source.get("event_time"),
        fetch.get("source_available_at"),
    )


def _payload_source_freshness(
    payload: JsonObject | None,
    *,
    now: datetime,
) -> tuple[str, float | None]:
    """Report source-event freshness without treating TTL/generation as event time."""

    event_at = _parse_utc(_payload_source_event_utc(payload))
    if event_at is None:
        return "UNKNOWN_NO_SOURCE_EVENT_CLOCK", None
    age = (now - event_at).total_seconds()
    if age < -60.0:
        return "INVALID_FUTURE_SOURCE_EVENT_CLOCK", age
    expires_at = _parse_utc(
        _first_text(
            payload.get("expires_at") if isinstance(payload, dict) else None,
            payload.get("valid_until") if isinstance(payload, dict) else None,
            payload.get("fresh_until") if isinstance(payload, dict) else None,
        )
    )
    if expires_at is not None:
        return (
            "CURRENT_BY_EXPLICIT_EXPIRY" if now <= expires_at else "STALE_BY_EXPLICIT_EXPIRY"
        ), age
    if isinstance(payload, dict) and any(
        payload.get(field) is True
        for field in ("source_fresh", "data_fresh", "current_data", "event_current")
    ):
        return "PRODUCER_DECLARED_CURRENT_NO_INDEPENDENT_EXPIRY", age
    return "OBSERVED_EVENT_CLOCK_NO_FRESHNESS_ENVELOPE", age


def _latest_payload_generated_utc(payloads: list[JsonObject]) -> str | None:
    candidates: list[tuple[datetime, str]] = []
    for payload in payloads:
        value = _payload_generated_utc(payload)
        parsed = _parse_utc(value)
        if parsed is not None and value is not None:
            candidates.append((parsed, value))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def _payload_status(payload: JsonObject | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    if str(payload.get("runtime_mode") or "").startswith("DIRECT_LEGACY_OWNED_COINANK"):
        return _first_text(payload.get("classification"), payload.get("status"))
    if isinstance(payload.get("global_aggregate_result"), dict):
        blockers = payload.get("missing_api_blockers")
        return (
            "V2_COINANK_GLOBAL_AGGREGATE_PARTIAL" if blockers else "V2_COINANK_GLOBAL_AGGREGATE_OK"
        )
    source_counts = payload.get("source_status_counts")
    if isinstance(source_counts, dict) and source_counts:
        source_status = next((str(key) for key in source_counts.keys() if key), "")
        if source_status.startswith("API_PAYMENT_REQUIRED"):
            return f"PROVIDER_PLAN_REQUIRED_{source_status}"
        if source_status.startswith("API_FORBIDDEN"):
            return f"PROVIDER_AUTH_FORBIDDEN_{source_status}"
        if source_status.startswith("API_RATE_LIMIT") or source_status.startswith("API_429"):
            return f"PROVIDER_RATE_LIMITED_{source_status}"
        if source_status:
            return f"PROVIDER_CURRENT_{source_status}"
    return _first_text(
        payload.get("classification"),
        payload.get("status"),
        payload.get("source"),
        payload.get("current_gate_state"),
    )


def _explicit_false_health_fields(payloads: list[JsonObject]) -> list[str]:
    """Return explicit producer health claims that currently report false."""

    health_fields = ("live_data_enabled", "redis_ok", "service_active", "stream_connected")
    return sorted(
        {
            field
            for payload in payloads
            for field in health_fields
            if field in payload and payload.get(field) is False
        }
    )


def _ingestor_entry(
    name: str,
    service: str,
    heartbeat_key: str,
    status_key: str | None,
    r: Any | None,
    *,
    control_enabled: bool = True,
    control_group: str = "market_data_ingestor",
    evidence_payloads: list[JsonObject | None] | None = None,
    requirement_class: str = REQUIREMENT_OPTIONAL_ENRICHMENT,
    heartbeat_max_age_seconds: int = 900,
    now: datetime | None = None,
) -> JsonObject:
    observed_now = now or datetime.now(UTC)
    hb, heartbeat_pttl_ms = _get_json_with_pttl(r, heartbeat_key) if r else (None, -2)
    public_evidence = [
        payload for payload in (evidence_payloads or []) if isinstance(payload, dict)
    ]
    evidence = [payload for payload in ([hb] + public_evidence) if isinstance(payload, dict)]
    current_evidence = [
        payload
        for payload in evidence
        if _payload_is_recent(
            payload,
            max_age_seconds=heartbeat_max_age_seconds,
            now=observed_now,
        )
    ]
    stale_evidence_count = len(evidence) - len(current_evidence)
    heartbeat_age_seconds = _payload_age_seconds(hb, now=observed_now)
    heartbeat_current = bool(
        isinstance(hb, dict)
        and _payload_is_recent(
            hb,
            max_age_seconds=heartbeat_max_age_seconds,
            now=observed_now,
        )
    )
    artifact_current = any(
        _payload_is_recent(
            payload,
            max_age_seconds=heartbeat_max_age_seconds,
            now=observed_now,
        )
        for payload in public_evidence
    )
    active = heartbeat_current or artifact_current
    explicit_false_health_fields = _explicit_false_health_fields(current_evidence)
    reported_data_available = bool(active and not explicit_false_health_fields)
    heartbeat_healthy = bool(heartbeat_current and reported_data_available)
    status_val = _get_text(r, status_key) if (r and status_key and heartbeat_current) else None
    # PTTL is storage-retention evidence only.  Persistent values and positive
    # TTLs never make a stale/missing producer clock current.
    heartbeat_ttl_seconds = (
        heartbeat_pttl_ms // 1000 if heartbeat_pttl_ms >= 0 else heartbeat_pttl_ms
    )
    last_generated = _latest_payload_generated_utc(evidence)
    keys_written_count = 0
    for payload in current_evidence:
        for field in (
            "v2_market_keys_written",
            "v2_features_keys_written",
            "v2_redis_keys_written",
            "v2_redis_global_keys_written",
            "keys_written",
        ):
            value = payload.get(field)
            if isinstance(value, list):
                keys_written_count = max(keys_written_count, len(value))
        for field in (
            "v2_market_keys_written_count",
            "v2_features_keys_written_count",
            "v2_redis_keys_written_count",
            "v2_redis_global_keys_written_count",
            "keys_written_count",
        ):
            count = _number(payload.get(field))
            if count is not None:
                keys_written_count = max(keys_written_count, count)
        keys_written_count = max(keys_written_count, _payload_keys_written_count(payload))
    symbols_count = max(
        (_payload_symbols_count(payload) for payload in current_evidence),
        default=0,
    )
    worker_id = None
    for payload in current_evidence:
        worker_id = worker_id or payload.get("worker_id")
    payload_status = None
    status_evidence = list(current_evidence)
    for payload in status_evidence:
        payload_status = payload_status or _payload_status(payload)
    source_freshness_rows = [
        _payload_source_freshness(payload, now=observed_now) for payload in current_evidence
    ]
    source_clock_rows = [row for row in source_freshness_rows if row[1] is not None]
    if source_clock_rows:
        source_freshness_status, source_event_age_seconds = min(
            source_clock_rows,
            key=lambda row: cast(float, row[1]),
        )
    else:
        source_freshness_status = "UNKNOWN_NO_SOURCE_EVENT_CLOCK"
        source_event_age_seconds = None
    if not active:
        reported_status = "STALE_OR_MISSING"
    else:
        reported_status = status_val or payload_status or "HEARTBEAT_CURRENT_STATUS_UNSPECIFIED"
    return {
        "name": name,
        "service": service,
        "heartbeat_key": heartbeat_key,
        "status": reported_status,
        "active": active,
        "active_semantics": "CURRENT_HEARTBEAT_OR_STATUS_ARTIFACT_NOT_PROCESS_STATE",
        "process_state_observed": False,
        "process_active": None,
        "heartbeat_current": heartbeat_current,
        "heartbeat_healthy": heartbeat_healthy,
        "status_artifact_current": artifact_current,
        "reported_data_available": reported_data_available,
        "reported_data_available_semantics": (
            "CURRENT_OPERATIONAL_EVIDENCE_WITH_NO_EXPLICIT_FALSE_HEALTH_FIELD"
        ),
        "explicit_false_health_fields": explicit_false_health_fields,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "heartbeat_max_age_seconds": heartbeat_max_age_seconds,
        "heartbeat_ttl_seconds": heartbeat_ttl_seconds,
        "heartbeat_ttl_is_storage_retention_only": True,
        "persistent_heartbeat_is_never_current_by_presence": True,
        "last_generated_utc": last_generated,
        "stale_evidence_ignored_count": stale_evidence_count,
        "source_event_freshness_status": source_freshness_status,
        "source_event_age_seconds": source_event_age_seconds,
        "source_event_freshness_authorizes_trainer": False,
        "symbols_count": symbols_count,
        "keys_written_count": keys_written_count,
        "worker_id": worker_id,
        "requirement_class": requirement_class,
        "core_data_plane_required": requirement_class == REQUIREMENT_CORE_DATA_PLANE,
        "optional_source": requirement_class == REQUIREMENT_OPTIONAL_ENRICHMENT,
        "required_for_trainer_admission": False,
        "absence_blocks_trainer": False,
        "trainer_consumable": False,
        "prediction_eligible": False,
        "control_enabled": bool(control_enabled),
        "control_group": control_group,
        "allowed_control_actions": ["start", "stop", "restart"] if control_enabled else [],
        "control_endpoint": f"/api/v1/ingestors/{service}/control" if control_enabled else None,
        "runtime_mode": "OBSERVABILITY_ONLY_NO_DECISION_OR_EXECUTION_AUTHORITY",
        "live_data_observation_only": True,
        "live_decision_input_enabled": False,
        "trader_execution_enabled": False,
        "dynamic_symbol_refresh_enabled": True,
    }


def run_once() -> JsonObject:
    r = _connect_redis()
    public_status = {name: _read_public_status(name) for name in PUBLIC_STATUS_PATHS}

    ingestors = [
        _ingestor_entry(
            "Native Ingestors (Binance USDM)",
            "ai-bot-v2-native-ingestors-live-loop.service",
            f"{V2_REDIS_PREFIX}market:ingestor:heartbeat",
            f"{V2_REDIS_PREFIX}market:ingestor:status",
            r,
            requirement_class=REQUIREMENT_CORE_DATA_PLANE,
            heartbeat_max_age_seconds=180,
        ),
        _ingestor_entry(
            "Feature Pipeline (TA + Features)",
            "ai-bot-v2-feature-pipeline-native-loop.service",
            f"{V2_REDIS_PREFIX}features:pipeline:heartbeat",
            None,
            r,
            requirement_class=REQUIREMENT_CORE_DATA_PLANE,
            heartbeat_max_age_seconds=300,
        ),
        _ingestor_entry(
            "Full TA-Lib Compatibility",
            "ai-bot-v2-full-talib-ta-loop.service",
            f"{V2_REDIS_PREFIX}features:ta:heartbeat",
            None,
            r,
            requirement_class=REQUIREMENT_CORE_DATA_PLANE,
            heartbeat_max_age_seconds=300,
        ),
        _ingestor_entry(
            "KuCoin Native Public REST",
            "ai-bot-v2-kucoin-public-rest-loop.service",
            f"{V2_REDIS_PREFIX}market:kucoin:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["kucoin"]],
            heartbeat_max_age_seconds=900,
        ),
        _ingestor_entry(
            "CoinAPI Native OHLCV",
            "ai-bot-v2-coinapi-rest-fallback-loop.service",
            f"{V2_REDIS_PREFIX}market:coinapi:ohlcv:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["coinapi_rest"]],
            heartbeat_max_age_seconds=900,
        ),
        _ingestor_entry(
            "CoinAPI Native REST Orderbook",
            "ai-bot-v2-coinapi-rest-fallback-loop.service",
            f"{V2_REDIS_PREFIX}market:coinapi:rest:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["coinapi_rest"]],
            heartbeat_max_age_seconds=900,
        ),
        _ingestor_entry(
            "CoinAPI Native WSDS",
            "ai-bot-v2-coinapi-wsds-loop.service",
            f"{V2_REDIS_PREFIX}market:coinapi:wsds:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["coinapi_wsds"]],
            heartbeat_max_age_seconds=180,
        ),
        _ingestor_entry(
            "Binance USD-M Kline WSS",
            "ai-bot-v2-binance-kline-wss-loop.service",
            f"{V2_REDIS_PREFIX}market:ohlcv:binance:kline_wss:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["binance_kline_wss"]],
            requirement_class=REQUIREMENT_CORE_DATA_PLANE,
            heartbeat_max_age_seconds=180,
        ),
        _ingestor_entry(
            "CoinAnk Direct Live Ingestor",
            "ai-bot-v2-coinank-live-direct.service",
            "heartbeat:IngestCoinAnk",
            None,
            r,
            evidence_payloads=[public_status["coinank"]],
            heartbeat_max_age_seconds=900,
        ),
        _ingestor_entry(
            "CoinAnk Direct Global Aggregator",
            "ai-bot-v2-coinank-global-aggregator-direct.service",
            "meta:coinank_global:last_update",
            None,
            r,
            evidence_payloads=[public_status["coinank"]],
            heartbeat_max_age_seconds=900,
        ),
        _ingestor_entry(
            "Liquidation WSS Client",
            "ai-bot-v2-liquidation-wss-paper-shadow.service",
            f"{V2_REDIS_PREFIX}market:liquidations:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["liquidation_wss"]],
            heartbeat_max_age_seconds=180,
        ),
        _ingestor_entry(
            "Native Liquidation Levels Engine",
            "ai-bot-v2-liquidation-levels-engine.service",
            f"{V2_REDIS_PREFIX}liquidations:levels:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["liquidation_levels"]],
            heartbeat_max_age_seconds=300,
        ),
        _ingestor_entry(
            "Liquidation Runtime Status Publisher",
            "ai-bot-v2-liquidation-runtime-status-publisher.service",
            f"{V2_REDIS_PREFIX}liquidations:levels:heartbeat",
            None,
            r,
            control_group="runtime_status",
            evidence_payloads=[public_status["liquidation_runtime"]],
            requirement_class=REQUIREMENT_DERIVED_OBSERVABILITY,
            heartbeat_max_age_seconds=300,
        ),
        _ingestor_entry(
            "Public Intel Free-Tier",
            "ai-bot-v2-public-intel-free-tier-loop.service",
            f"{V2_REDIS_PREFIX}altdata:public_intel:status",
            None,
            r,
            control_group="altdata_ingestor",
            # The provider-safe producer cadence is hourly. Align operational
            # availability with its source-owned retention headroom without
            # interpreting Redis retention as source-event freshness.
            heartbeat_max_age_seconds=PUBLIC_INTEL_REDIS_RETENTION_SECONDS,
        ),
        _ingestor_entry(
            "Alt-Data Symbol Scoring",
            "ai-bot-v2-alt-data-symbol-scoring-loop.service",
            f"{V2_REDIS_PREFIX}symbol_universe:altdata_candidates",
            None,
            r,
            control_group="altdata_scoring",
            requirement_class=REQUIREMENT_DERIVED_OBSERVABILITY,
            heartbeat_max_age_seconds=900,
        ),
        _ingestor_entry(
            "Alt-Data Candidate Publisher",
            "ai-bot-v2-alt-data-candidate-publisher-loop.service",
            f"{V2_REDIS_PREFIX}altdata:candidate_publisher:status",
            None,
            r,
            control_group="altdata_scoring",
            requirement_class=REQUIREMENT_DERIVED_OBSERVABILITY,
            heartbeat_max_age_seconds=900,
        ),
        _ingestor_entry(
            "Alternative-Data Provider Registry Status",
            "ai-bot-v2-alternative-data-status-loop.service",
            f"{V2_REDIS_PREFIX}altdata:provider_status",
            None,
            r,
            control_group="altdata_status",
            requirement_class=REQUIREMENT_DERIVED_OBSERVABILITY,
            heartbeat_max_age_seconds=900,
        ),
        _ingestor_entry(
            "Dynamic Symbol Discovery",
            "ai-bot-v2-dynamic-symbol-discovery-loop.service",
            f"{V2_REDIS_PREFIX}symbol_universe:dynamic_discovery_status",
            None,
            r,
            control_group="symbol_universe",
            requirement_class=REQUIREMENT_DERIVED_OBSERVABILITY,
            # This source intentionally refreshes on the provider-safe six-hour
            # cadence.  Its source-owned Redis availability contract retains
            # one-third-cadence fetch headroom; a generic 15-minute heartbeat
            # envelope falsely reported it dead for most of every healthy
            # cycle.  PTTL remains storage evidence only and never becomes an
            # event-time freshness assertion.
            heartbeat_max_age_seconds=DYNAMIC_DISCOVERY_REDIS_RETENTION_SECONDS,
        ),
    ]

    # Redis market data freshness summary
    freshness: dict[str, JsonObject] = {}
    if r:
        for pat, label in [
            (f"{V2_REDIS_PREFIX}market:prices:*", "prices"),
            (f"{V2_REDIS_PREFIX}market:ohlcv:*", "ohlcv"),
            (f"{V2_REDIS_PREFIX}market:ohlcv:binance:*:source", "ohlcv_binance_kline_wss_sources"),
            (f"{V2_REDIS_PREFIX}market:orderbook:*", "orderbook"),
            (f"{V2_REDIS_PREFIX}features:latest:*", "features_latest"),
            (f"{V2_REDIS_PREFIX}technical_analysis:*", "technical_analysis"),
            (f"{V2_REDIS_PREFIX}market:kucoin:*", "kucoin_market"),
            (f"{V2_REDIS_PREFIX}features:kucoin:*", "kucoin_features"),
            (f"{V2_REDIS_PREFIX}market:coinapi:rest:*", "coinapi_rest"),
            (f"{V2_REDIS_PREFIX}market:coinapi:ohlcv:*", "coinapi_ohlcv"),
            (f"{V2_REDIS_PREFIX}market:coinapi:wsds:*", "coinapi_wsds"),
            (f"{V2_REDIS_PREFIX}features:microfeat:*", "coinapi_wsds_microfeatures"),
            (f"{V2_REDIS_PREFIX}latest:coinapi:ohlcv:*", "coinapi_ohlcv_latest"),
            (f"{V2_REDIS_PREFIX}liquidations:levels:*", "liquidation_levels"),
            (f"{V2_REDIS_PREFIX}market:liquidations:*", "liquidation_market"),
            (f"{V2_REDIS_PREFIX}altdata:public_intel:*", "public_intel_altdata"),
            (f"{V2_REDIS_PREFIX}altdata:whale_walls:*", "whale_wall_altdata"),
            (f"{V2_REDIS_PREFIX}altdata:symbol_score:*", "altdata_symbol_scores"),
            (f"{V2_REDIS_PREFIX}symbol_universe:altdata_candidates", "altdata_candidates"),
            (f"{V2_REDIS_PREFIX}symbol_universe:dynamic_*", "dynamic_symbol_universe"),
        ]:
            try:
                # Bound calls, returned rows inspected, unique matches, and the
                # one pipelined PTTL batch.  Redis SCAN's count is only a hint,
                # so a key limit alone is not a work bound.
                keys: list[str] = []
                seen_keys: set[str] = set()
                seen_nonzero_cursors: set[int] = set()
                cursor = 0
                scan_iterations = 0
                scan_rows_inspected = 0
                scan_stop_reason = "COMPLETE"
                while scan_iterations < MAX_STATUS_SCAN_ITERATIONS:
                    next_cursor, batch = r.scan(cursor=cursor, match=pat, count=1000)
                    scan_iterations += 1
                    if type(next_cursor) is not int or next_cursor < 0:
                        raise ValueError("invalid Redis SCAN cursor")
                    cursor = next_cursor
                    for key in batch:
                        if scan_rows_inspected >= MAX_STATUS_SCAN_ROWS_INSPECTED:
                            scan_stop_reason = "ROW_INSPECTION_LIMIT"
                            break
                        scan_rows_inspected += 1
                        if type(key) is bytes:
                            if len(key) > MAX_STATUS_TEXT_BYTES:
                                continue
                            normalized_key = key.decode("utf-8", errors="strict")
                        elif type(key) is str:
                            try:
                                _bounded_direct_string_utf8_length(
                                    key,
                                    maximum_bytes=MAX_STATUS_TEXT_BYTES,
                                )
                            except _StatusJsonError:
                                continue
                            normalized_key = key
                        else:
                            continue
                        if type(normalized_key) is not str or normalized_key in seen_keys:
                            continue
                        seen_keys.add(normalized_key)
                        keys.append(normalized_key)
                        if len(keys) >= MAX_STATUS_SCAN_KEYS:
                            scan_stop_reason = "KEY_LIMIT"
                            break
                    if cursor == 0:
                        break
                    if (
                        len(keys) >= MAX_STATUS_SCAN_KEYS
                        or scan_rows_inspected >= MAX_STATUS_SCAN_ROWS_INSPECTED
                    ):
                        if (
                            scan_rows_inspected >= MAX_STATUS_SCAN_ROWS_INSPECTED
                            and scan_stop_reason == "COMPLETE"
                        ):
                            scan_stop_reason = "ROW_INSPECTION_LIMIT"
                        break
                    if cursor in seen_nonzero_cursors:
                        scan_stop_reason = "CURSOR_CYCLE"
                        break
                    seen_nonzero_cursors.add(cursor)
                else:
                    scan_stop_reason = "ITERATION_LIMIT"
                ttl_positive = 0
                persistent = 0
                missing_during_check = 0
                if keys:
                    _pipe = r.pipeline()
                    for _k in keys:
                        _pipe.pttl(_k)
                    ttl_rows = _pipe.execute()
                    ttl_positive = sum(1 for ttl in ttl_rows if type(ttl) is int and ttl > 0)
                    persistent = sum(1 for ttl in ttl_rows if ttl == -1)
                    missing_during_check = sum(1 for ttl in ttl_rows if ttl == -2)
                freshness[label] = {
                    "observed_key_count": len(keys),
                    "storage_ttl_positive_count": ttl_positive,
                    "persistent_key_count": persistent,
                    "missing_during_check_count": missing_during_check,
                    "scan_complete": cursor == 0 and scan_stop_reason == "COMPLETE",
                    "scan_cursor": cursor,
                    "scan_key_limit": MAX_STATUS_SCAN_KEYS,
                    "scan_iteration_count": scan_iterations,
                    "scan_iteration_limit": MAX_STATUS_SCAN_ITERATIONS,
                    "scan_rows_inspected": scan_rows_inspected,
                    "scan_row_inspection_limit": MAX_STATUS_SCAN_ROWS_INSPECTED,
                    "scan_stop_reason": scan_stop_reason,
                    "source_event_freshness_inferred_from_ttl": False,
                    "trainer_admission_authorized": False,
                }
            except Exception:
                freshness[label] = {
                    "observed_key_count": 0,
                    "storage_ttl_positive_count": 0,
                    "persistent_key_count": 0,
                    "missing_during_check_count": 0,
                    "scan_complete": False,
                    "scan_cursor": None,
                    "scan_key_limit": MAX_STATUS_SCAN_KEYS,
                    "scan_iteration_count": 0,
                    "scan_iteration_limit": MAX_STATUS_SCAN_ITERATIONS,
                    "scan_rows_inspected": 0,
                    "scan_row_inspection_limit": MAX_STATUS_SCAN_ROWS_INSPECTED,
                    "scan_stop_reason": "OBSERVATION_ERROR",
                    "source_event_freshness_inferred_from_ttl": False,
                    "trainer_admission_authorized": False,
                    "observation_error": True,
                }

    active_count = sum(1 for i in ingestors if i["active"])
    core_ingestors = [
        entry for entry in ingestors if entry["requirement_class"] == REQUIREMENT_CORE_DATA_PLANE
    ]
    optional_ingestors = [
        entry
        for entry in ingestors
        if entry["requirement_class"] == REQUIREMENT_OPTIONAL_ENRICHMENT
    ]
    core_heartbeat_current_count = sum(1 for entry in core_ingestors if entry["heartbeat_current"])
    core_data_plane_current_count = sum(1 for entry in core_ingestors if entry["heartbeat_healthy"])
    optional_current_count = sum(1 for entry in optional_ingestors if entry["active"])
    optional_heartbeat_current_count = sum(
        1 for entry in optional_ingestors if entry["heartbeat_current"]
    )
    redis_observation_available = r is not None
    core_heartbeats_current = bool(
        redis_observation_available
        and core_ingestors
        and core_heartbeat_current_count == len(core_ingestors)
    )
    core_data_plane_current = bool(
        core_heartbeats_current and core_data_plane_current_count == len(core_ingestors)
    )
    if not redis_observation_available:
        classification = "INGESTOR_OBSERVABILITY_UNAVAILABLE"
    elif not core_heartbeats_current:
        classification = "INGESTOR_CORE_HEARTBEATS_DEGRADED"
    elif not core_data_plane_current:
        classification = "INGESTOR_CORE_HEALTH_DEGRADED"
    elif optional_current_count < len(optional_ingestors):
        classification = "INGESTOR_CORE_HEARTBEATS_CURRENT_OPTIONAL_EVIDENCE_DEGRADED"
    else:
        classification = "INGESTOR_CORE_HEARTBEATS_CURRENT_OPTIONAL_EVIDENCE_CURRENT"
    payload = {
        "schema_version": "v2_ingestors_status_v2",
        "worker_id": "v2_ingestors_status_publisher",
        "generated_utc": _utc_iso(),
        "runtime_mode": "OBSERVABILITY_ONLY_PROCESS_AND_TRAINER_AUTHORITY_NOT_INFERRED",
        "redis_observation_available": redis_observation_available,
        "live_data_enabled": core_data_plane_current,
        "live_data_enabled_semantics": (
            "ALL_CORE_REDIS_HEARTBEATS_CURRENT_AND_NO_CURRENT_CORE_EVIDENCE_"
            "EXPLICITLY_REPORTS_FALSE_HEALTH; OBSERVATION_ONLY"
        ),
        "live_decision_input_enabled": False,
        "trainer_orchestrator_risk_path_enabled": False,
        "trainer_admission_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "trader_execution_enabled": False,
        "execution_live_symbols": [],
        "live_gate": "blocked_human_only",
        "dynamic_symbol_universe_enabled": True,
        "dynamic_symbol_refresh_without_restart": True,
        "symbol_universe_source": "v2_symbol_runtime_universe.resolve_symbols",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
        "exchange_action_taken": False,
        "adapter_runtime_allowed": False,
        "legacy_ingest_runtime_allowed": True,
        "legacy_ingest_runtime_mode": (
            "DIRECT_LEGACY_OWNED_INGESTOR_PATHS_ONLY_NO_V2_BRIDGE_WRAPPERS"
        ),
        "website_control_surface": {
            "enabled": True,
            "endpoint_prefix": "/api/v1/ingestors",
            "allowed_actions": ["start", "stop", "restart", "status"],
            "blocked_actions": [
                "place_order",
                "cancel_order",
                "enable_trader",
                "enable_canary",
                "change_leverage",
                "change_margin",
                "modify_trainer",
            ],
        },
        "ingestors": ingestors,
        "active_count": active_count,
        "total_count": len(ingestors),
        "active_count_semantics": "CURRENT_HEARTBEAT_OR_STATUS_ARTIFACT_NOT_PROCESS_STATE",
        "process_state_observed": False,
        "core_data_plane_count": len(core_ingestors),
        "core_heartbeat_current_count": core_heartbeat_current_count,
        "core_heartbeats_current": core_heartbeats_current,
        "core_data_plane_current_count": core_data_plane_current_count,
        "core_data_plane_current": core_data_plane_current,
        "optional_enrichment_count": len(optional_ingestors),
        "optional_enrichment_heartbeat_current_count": optional_heartbeat_current_count,
        "optional_enrichment_current_count": optional_current_count,
        "optional_enrichment_current_count_semantics": (
            "CURRENT_REDIS_HEARTBEAT_OR_PUBLIC_STATUS_ARTIFACT; NOT_PROCESS_STATE"
        ),
        "optional_source_absence_blocks_core": False,
        "optional_source_absence_blocks_trainer": False,
        "redis_freshness": freshness,
        "redis_freshness_semantics": (
            "BOUNDED_KEY_AND_STORAGE_TTL_CENSUS_NO_SOURCE_EVENT_FRESHNESS_INFERENCE"
        ),
        "classification": classification,
    }
    return payload


def write_payload(payload: JsonObject, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_ingestors_status_publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            payload = run_once()
            write_payload(payload, args.out)
            time.sleep(max(5, args.interval_seconds))
    payload = run_once()
    write_payload(payload, args.out)
    print(
        json.dumps(
            {"classification": payload["classification"], "active_count": payload["active_count"]}
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
