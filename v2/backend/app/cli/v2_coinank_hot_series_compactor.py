#!/usr/bin/env python3
"""Bounded CoinAnk hot-series compaction overlay.

This one-shot maintenance worker scans only canonical CoinAnk ``:series`` keys
and resumes from bounded expiring V2 maintenance progress.
It never calls an exchange, selects a market, publishes trainer aliases, or
changes the authoritative ``:latest``/JSONL sources.  Redis writes use an
optimistic WATCH/MULTI/EXEC compare-and-set, preserve positive expiries, and
restore a fixed resource-control expiry when a legacy key is persistent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

import redis
from app.services.altdata.coinank_hot_series import (
    MAX_HOT_SERIES_SOURCE_BYTES,
    CoinAnkHotSeriesCompaction,
    CoinAnkHotSeriesValidationError,
    compact_coinank_hot_series,
    decode_coinank_hot_series_json,
)

SERVICE_ID: Final = "v2_coinank_hot_series_compactor"
STATUS_SCHEMA_VERSION: Final = "coinank_hot_series_compactor_status_v3"
SERIES_SCAN_MATCH: Final = b"features:coinank:*:series"
SCAN_STATE_KEY: Final = b"v2:maintenance:coinank:hot_series:scan_state:v1"
SCAN_STATE_SCHEMA_VERSION: Final = "coinank_hot_series_scan_progress_v1"
SCAN_STATE_ROLE: Final = "EXPIRING_NON_AUTHORITATIVE_MAINTENANCE_PROGRESS"
MAX_KEYS_PER_RUN: Final = 128
MAX_SCAN_RESULTS_PER_RUN: Final = 2_048
MAX_SCAN_PAGES_PER_RUN: Final = 64
MAX_SCAN_PAGE_KEYS: Final = 512
MAX_SCAN_STATE_BYTES: Final = 4 * 1024 * 1024
MAX_SCAN_STATE_SEEN_KEYS: Final = 4_096
MAX_SCAN_STATE_CURSOR_HISTORY: Final = 4_096
MAX_BYTES_READ_PER_RUN: Final = 64 * 1024 * 1024
MAX_RUNTIME_SECONDS: Final = 45.0
MAX_CAS_RETRIES: Final = 3
SCAN_COUNT: Final = 128
RESTORED_HOT_SERIES_TTL_MS: Final = 24 * 60 * 60 * 1_000
SCAN_STATE_TTL_MS: Final = 7 * 24 * 60 * 60 * 1_000
_MAX_UNSIGNED_64: Final = (1 << 64) - 1
_MAX_SIGNED_64: Final = (1 << 63) - 1
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
_KEY_PART = rb"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
_EXACT_SERIES_KEY_RE: Final = re.compile(
    rb"^features:coinank:"
    + _KEY_PART
    + rb":"
    + _KEY_PART
    + rb":"
    + _KEY_PART
    + rb":"
    + _KEY_PART
    + rb":series$"
)
_SCAN_STATE_FALSE_FIELDS: Final = (
    "publication_authority",
    "trainer_authority",
    "prediction_authority",
    "risk_authority",
    "orchestrator_authority",
    "allocator_authority",
    "paper_authority",
    "live_authority",
    "live_execution_authority",
    "actual_consumption",
    "trainer_consumption",
    "trainer_admission_granted",
)
_SCAN_STATE_FIELDS: Final = frozenset(
    {
        "schema_version",
        "role",
        "scan_pattern",
        "cursor",
        "pending_keys",
        "pending_offset",
        "seen_exact_keys",
        "seen_cursors",
        "dedupe_saturated",
        "cursor_history_saturated",
        "last_reset_reason",
        "available_at",
        "admitted_feature_count",
        "zero_filled_field_count",
        "no_zero_fill_for_unknown_fields",
        *_SCAN_STATE_FALSE_FIELDS,
    }
)


class CoinAnkHotSeriesCompactorError(RuntimeError):
    """A bounded read, validation, or Redis invariant failed."""


class _RunLimitReached(CoinAnkHotSeriesCompactorError):
    pass


@dataclass(frozen=True, slots=True)
class KeyCompactionStatus:
    key: str
    outcome: str
    reason: str | None
    prior_series_bytes: int
    bytes_read: int
    stored_bytes: int
    previous_pttl_ms: int
    attempts: int
    series_get_performed: bool
    latest_get_performed: bool
    exact_raw_cas_guarded: bool
    ttl_policy: str
    applied_ttl_ms: int | None
    output_expiring: bool
    publication_authority: bool = field(default=False, init=False)
    trainer_authority: bool = field(default=False, init=False)
    prediction_authority: bool = field(default=False, init=False)
    risk_authority: bool = field(default=False, init=False)
    orchestrator_authority: bool = field(default=False, init=False)
    allocator_authority: bool = field(default=False, init=False)
    paper_authority: bool = field(default=False, init=False)
    live_authority: bool = field(default=False, init=False)
    live_execution_authority: bool = field(default=False, init=False)
    actual_consumption: bool = field(default=False, init=False)
    trainer_consumption: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    admitted_feature_count: int = field(default=0, init=False)
    available_at: None = field(default=None, init=False)
    zero_filled_field_count: int = field(default=0, init=False)
    no_zero_fill_for_unknown_fields: bool = field(default=True, init=False)


@dataclass(frozen=True, slots=True)
class RunCompactionStatus:
    generated_at: str
    elapsed_seconds: float
    scan_page_count: int
    scanned_key_count: int
    exact_key_count: int
    compacted_key_count: int
    rebuilt_key_count: int
    skipped_key_count: int
    cas_conflict_count: int
    bytes_read: int
    bytes_written: int
    expiring_write_count: int
    stop_reason: str | None
    scan_start_cursor: int
    scan_end_cursor: int
    pending_start_key_count: int
    pending_end_key_count: int
    deduplicated_key_count: int
    scan_cycle_completed: bool
    scan_state_load_outcome: str
    scan_state_reset_reason: str | None
    scan_state_persisted: bool
    key_results: tuple[KeyCompactionStatus, ...]
    schema_version: str = field(default=STATUS_SCHEMA_VERSION, init=False)
    service: str = field(default=SERVICE_ID, init=False)
    scan_pattern: str = field(default=SERIES_SCAN_MATCH.decode("ascii"), init=False)
    scan_state_key: str = field(default=SCAN_STATE_KEY.decode("ascii"), init=False)
    scan_state_ttl_ms: int = field(default=SCAN_STATE_TTL_MS, init=False)
    publication_authority: bool = field(default=False, init=False)
    trainer_authority: bool = field(default=False, init=False)
    prediction_authority: bool = field(default=False, init=False)
    risk_authority: bool = field(default=False, init=False)
    orchestrator_authority: bool = field(default=False, init=False)
    allocator_authority: bool = field(default=False, init=False)
    paper_authority: bool = field(default=False, init=False)
    live_authority: bool = field(default=False, init=False)
    live_execution_authority: bool = field(default=False, init=False)
    actual_consumption: bool = field(default=False, init=False)
    trainer_consumption: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    admitted_feature_count: int = field(default=0, init=False)
    available_at: None = field(default=None, init=False)
    zero_filled_field_count: int = field(default=0, init=False)
    no_zero_fill_for_unknown_fields: bool = field(default=True, init=False)


@dataclass(slots=True)
class _RunBudget:
    maximum_bytes: int
    deadline: float
    clock: Callable[[], float]
    bytes_read: int = 0

    def check_time(self) -> None:
        if self.clock() >= self.deadline:
            raise _RunLimitReached("coinank_hot_series_runtime_budget_exhausted")

    def check_scan_boundary(self) -> None:
        self.check_time()
        if self.bytes_read >= self.maximum_bytes:
            raise _RunLimitReached("coinank_hot_series_byte_budget_exhausted")

    def reserve_read(self, byte_count: int) -> None:
        self.check_time()
        if byte_count < 0 or self.bytes_read + byte_count > self.maximum_bytes:
            raise _RunLimitReached("coinank_hot_series_byte_budget_exhausted")
        self.bytes_read += byte_count


@dataclass(frozen=True, slots=True)
class _PreparedWrite:
    compaction: CoinAnkHotSeriesCompaction
    outcome: str
    series_get_performed: bool
    latest_get_performed: bool


@dataclass(frozen=True, slots=True)
class _BoundedRedisRead:
    byte_count: int
    pttl_ms: int
    payload: bytes | None


@dataclass(frozen=True, slots=True)
class _ScanProgress:
    cursor: int
    pending_keys: tuple[bytes, ...]
    pending_offset: int
    seen_exact_keys: tuple[bytes, ...]
    seen_cursors: tuple[int, ...]
    dedupe_saturated: bool
    cursor_history_saturated: bool
    last_reset_reason: str | None


@dataclass(frozen=True, slots=True)
class _LoadedScanProgress:
    progress: _ScanProgress
    outcome: str
    reset_reason: str | None


def _invalid(reason: str) -> NoReturn:
    raise CoinAnkHotSeriesCompactorError(reason) from None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _exact_nonnegative_int(value: object, *, reason: str) -> int:
    if type(value) is not int or value < 0:
        _invalid(reason)
    return value


def _validated_pttl(value: object) -> int:
    if type(value) is not int or value < -2:
        _invalid("coinank_hot_series_pttl_invalid")
    return value


def _binary_value(value: object, *, expected_bytes: int, reason: str) -> bytes:
    if type(value) is not bytes or len(value) != expected_bytes:
        _invalid(reason)
    return value


def _redis_kind(value: object) -> str:
    if type(value) is not bytes:
        _invalid("coinank_hot_series_redis_client_requires_binary_responses")
    try:
        kind = value.decode("ascii", errors="strict")
    except UnicodeError:
        _invalid("coinank_hot_series_redis_type_invalid")
    if kind not in {"none", "string", "list", "set", "zset", "hash", "stream"}:
        _invalid("coinank_hot_series_redis_type_invalid")
    return kind


def _bounded_redis_read(
    pipe: Any,
    *,
    key: bytes,
    budget: _RunBudget,
) -> _BoundedRedisRead:
    """Atomically STRLEN before GETRANGE and never return an oversized value."""

    budget.check_time()
    remaining_bytes = budget.maximum_bytes - budget.bytes_read
    if remaining_bytes <= 0:
        raise _RunLimitReached("coinank_hot_series_byte_budget_exhausted")
    payload_cap = min(MAX_HOT_SERIES_SOURCE_BYTES, remaining_bytes)
    response = pipe.eval(_BOUNDED_READ_LUA, 1, key, payload_cap)
    if type(response) is not list or len(response) != 4:
        _invalid("coinank_hot_series_bounded_read_response_invalid")
    kind = _redis_kind(response[0])
    pttl_ms = _validated_pttl(response[1])
    byte_count = _exact_nonnegative_int(
        response[2],
        reason="coinank_hot_series_bounded_read_size_invalid",
    )
    raw = response[3]
    if kind == "none":
        if pttl_ms != -2 or byte_count != 0 or raw is not None:
            _invalid("coinank_hot_series_missing_read_inconsistent")
        return _BoundedRedisRead(byte_count=0, pttl_ms=-2, payload=None)
    if kind != "string":
        _invalid("coinank_hot_series_redis_type_not_string")
    if pttl_ms == -2:
        _invalid("coinank_hot_series_existing_pttl_inconsistent")
    if byte_count > MAX_HOT_SERIES_SOURCE_BYTES:
        if raw is not None:
            _invalid("coinank_hot_series_oversized_read_inconsistent")
        return _BoundedRedisRead(byte_count=byte_count, pttl_ms=pttl_ms, payload=None)
    if byte_count > remaining_bytes:
        if raw is not None:
            _invalid("coinank_hot_series_budgeted_read_inconsistent")
        raise _RunLimitReached("coinank_hot_series_byte_budget_exhausted")
    payload = _binary_value(
        raw,
        expected_bytes=byte_count,
        reason="coinank_hot_series_exact_read_invalid",
    )
    budget.reserve_read(byte_count)
    return _BoundedRedisRead(byte_count=byte_count, pttl_ms=pttl_ms, payload=payload)


def _exact_series_key(value: object) -> bytes | None:
    if type(value) is bytes:
        key = value
    elif type(value) is str:
        try:
            key = value.encode("ascii", errors="strict")
        except UnicodeError:
            return None
    else:
        return None
    return key if _EXACT_SERIES_KEY_RE.fullmatch(key) is not None else None


def _key_text(key: bytes) -> str:
    return key.decode("ascii", errors="strict")


def _latest_key(series_key: bytes) -> bytes:
    return series_key[: -len(b":series")] + b":latest"


def _key_identity(series_key: bytes) -> tuple[str, str, str, str]:
    parts = _key_text(series_key).split(":")
    if len(parts) != 7:
        _invalid("coinank_hot_series_key_identity_invalid")
    return parts[2], parts[3], parts[4], parts[5]


def _record_identity_matches(record: object, *, series_key: bytes) -> bool:
    if type(record) is not dict:
        return False
    mapping = cast(dict[str, object], record)
    family, base_coin, exchange, interval = _key_identity(series_key)
    return (
        mapping.get("family") == family
        and mapping.get("baseCoin") == base_coin
        and mapping.get("exchange") == exchange
        and mapping.get("interval") == interval
    )


def _series_reset_reason(records: list[object], *, series_key: bytes) -> str | None:
    if not records or not all(
        _record_identity_matches(record, series_key=series_key) for record in records
    ):
        return "IDENTITY_MISMATCH_HOT_CACHE_REBUILT_FROM_LATEST"
    previous = -1
    for record in records:
        assert type(record) is dict
        timestamp = cast(dict[str, object], record).get("ts_epoch_ms")
        if (
            type(timestamp) is not int
            or not 0 <= timestamp <= _MAX_SIGNED_64
            or timestamp <= previous
        ):
            return "NON_MONOTONIC_HOT_CACHE_REBUILT_FROM_LATEST"
        previous = timestamp
    return None


def _read_latest_record(
    pipe: Any,
    *,
    series_key: bytes,
    latest_key: bytes,
    budget: _RunBudget,
) -> dict[str, object]:
    bounded = _bounded_redis_read(pipe, key=latest_key, budget=budget)
    if bounded.pttl_ms == -2 or bounded.byte_count == 0 or bounded.payload is None:
        _invalid("coinank_hot_series_latest_unavailable_or_oversized")
    decoded = decode_coinank_hot_series_json(bounded.payload, max_bytes=bounded.byte_count)
    if type(decoded) is not dict:
        _invalid("coinank_hot_series_latest_shape_invalid")
    record = cast(dict[str, object], decoded)
    if not _record_identity_matches(record, series_key=series_key):
        _invalid("coinank_hot_series_latest_identity_mismatch")
    return record


def _prepare_write(
    pipe: Any,
    *,
    series_key: bytes,
    latest_key: bytes,
    series_read: _BoundedRedisRead,
    budget: _RunBudget,
) -> _PreparedWrite:
    series_size = series_read.byte_count
    if series_size > MAX_HOT_SERIES_SOURCE_BYTES:
        latest = _read_latest_record(
            pipe,
            series_key=series_key,
            latest_key=latest_key,
            budget=budget,
        )
        compaction = compact_coinank_hot_series(
            [],
            latest,
            reset_reason="OVERSIZED_LEGACY_HOT_CACHE_REBUILT_FROM_LATEST",
            prior_series_bytes=series_size,
        )
        if compaction is None:
            _invalid("coinank_hot_series_latest_projection_invalid")
        return _PreparedWrite(
            compaction=compaction,
            outcome="rebuilt_oversized",
            series_get_performed=False,
            latest_get_performed=True,
        )

    if series_read.payload is None:
        _invalid("coinank_hot_series_exact_read_invalid")
    series_raw = series_read.payload
    reset_reason: str | None = None
    try:
        decoded = decode_coinank_hot_series_json(series_raw, max_bytes=series_size)
    except CoinAnkHotSeriesValidationError:
        decoded = None
        reset_reason = "INVALID_LEGACY_HOT_CACHE_REBUILT_FROM_LATEST"
    if type(decoded) is list and decoded:
        records = cast(list[object], decoded)
        reset_reason = _series_reset_reason(records, series_key=series_key)
        if reset_reason is None:
            compaction = compact_coinank_hot_series(records[:-1], records[-1])
            if compaction is not None:
                return _PreparedWrite(
                    compaction=compaction,
                    outcome="compacted",
                    series_get_performed=True,
                    latest_get_performed=False,
                )
            reset_reason = "INVALID_LEGACY_HOT_CACHE_REBUILT_FROM_LATEST"
    elif reset_reason is None:
        reset_reason = "INVALID_LEGACY_HOT_CACHE_REBUILT_FROM_LATEST"

    latest = _read_latest_record(
        pipe,
        series_key=series_key,
        latest_key=latest_key,
        budget=budget,
    )
    compaction = compact_coinank_hot_series(
        [],
        latest,
        reset_reason=reset_reason,
        prior_series_bytes=series_size,
    )
    if compaction is None:
        _invalid("coinank_hot_series_latest_projection_invalid")
    return _PreparedWrite(
        compaction=compaction,
        outcome="rebuilt_invalid",
        series_get_performed=True,
        latest_get_performed=True,
    )


def compact_exact_series_key(
    client: object,
    *,
    series_key: bytes,
    budget: _RunBudget,
    max_retries: int = MAX_CAS_RETRIES,
) -> KeyCompactionStatus:
    """Compact one exact key with bounded reads and optimistic CAS."""

    if _exact_series_key(series_key) != series_key:
        _invalid("coinank_hot_series_key_invalid")
    if type(max_retries) is not int or not 1 <= max_retries <= MAX_CAS_RETRIES:
        _invalid("coinank_hot_series_retry_bound_invalid")
    redis_client = cast(Any, client)
    latest_key = _latest_key(series_key)
    starting_bytes = budget.bytes_read
    last_series_size = 0
    last_pttl = -2
    for attempt in range(1, max_retries + 1):
        budget.check_time()
        pipe = redis_client.pipeline(transaction=True)
        try:
            pipe.watch(series_key, latest_key)
            series_read = _bounded_redis_read(pipe, key=series_key, budget=budget)
            last_series_size = series_read.byte_count
            last_pttl = series_read.pttl_ms
            if last_pttl == -2 or last_series_size == 0:
                _invalid("coinank_hot_series_key_missing_or_empty")
            prepared = _prepare_write(
                pipe,
                series_key=series_key,
                latest_key=latest_key,
                series_read=series_read,
                budget=budget,
            )
            encoded = prepared.compaction.encoded_json.encode("ascii", errors="strict")
            budget.check_time()
            pipe.multi()
            if last_pttl > 0:
                ttl_policy = "PRESERVE_POSITIVE_EXPIRING_TTL"
                applied_ttl_ms = last_pttl
                pipe.set(series_key, encoded, keepttl=True)
            else:
                ttl_policy = "RESTORE_RESOURCE_CONTROL_EXPIRING_TTL"
                applied_ttl_ms = RESTORED_HOT_SERIES_TTL_MS
                pipe.set(series_key, encoded, px=RESTORED_HOT_SERIES_TTL_MS)
            acknowledgements = pipe.execute()
            if type(acknowledgements) is not list or acknowledgements != [True]:
                _invalid("coinank_hot_series_commit_not_acknowledged")
            return KeyCompactionStatus(
                key=_key_text(series_key),
                outcome=prepared.outcome,
                reason=None,
                prior_series_bytes=last_series_size,
                bytes_read=budget.bytes_read - starting_bytes,
                stored_bytes=len(encoded),
                previous_pttl_ms=last_pttl,
                attempts=attempt,
                series_get_performed=prepared.series_get_performed,
                latest_get_performed=prepared.latest_get_performed,
                exact_raw_cas_guarded=True,
                ttl_policy=ttl_policy,
                applied_ttl_ms=applied_ttl_ms,
                output_expiring=True,
            )
        except redis.WatchError:
            if attempt == max_retries:
                return KeyCompactionStatus(
                    key=_key_text(series_key),
                    outcome="cas_conflict",
                    reason="coinank_hot_series_concurrent_write_retry_exhausted",
                    prior_series_bytes=last_series_size,
                    bytes_read=budget.bytes_read - starting_bytes,
                    stored_bytes=0,
                    previous_pttl_ms=last_pttl,
                    attempts=attempt,
                    series_get_performed=last_series_size <= MAX_HOT_SERIES_SOURCE_BYTES,
                    latest_get_performed=last_series_size > MAX_HOT_SERIES_SOURCE_BYTES,
                    exact_raw_cas_guarded=True,
                    ttl_policy="NOT_WRITTEN_CAS_CONFLICT",
                    applied_ttl_ms=None,
                    output_expiring=False,
                )
        finally:
            with suppress(Exception):
                pipe.reset()
    _invalid("coinank_hot_series_retry_state_invalid")


def _skipped_status(
    *,
    key: bytes,
    reason: str,
    bytes_read: int,
) -> KeyCompactionStatus:
    return KeyCompactionStatus(
        key=_key_text(key),
        outcome="skipped",
        reason=reason,
        prior_series_bytes=0,
        bytes_read=bytes_read,
        stored_bytes=0,
        previous_pttl_ms=-2,
        attempts=0,
        series_get_performed=False,
        latest_get_performed=False,
        exact_raw_cas_guarded=False,
        ttl_policy="NOT_WRITTEN",
        applied_ttl_ms=None,
        output_expiring=False,
    )


def _fresh_scan_progress(*, reset_reason: str | None = None) -> _ScanProgress:
    return _ScanProgress(
        cursor=0,
        pending_keys=(),
        pending_offset=0,
        seen_exact_keys=(),
        seen_cursors=(),
        dedupe_saturated=False,
        cursor_history_saturated=False,
        last_reset_reason=reset_reason,
    )


def _scan_progress_payload(progress: _ScanProgress) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCAN_STATE_SCHEMA_VERSION,
        "role": SCAN_STATE_ROLE,
        "scan_pattern": SERIES_SCAN_MATCH.decode("ascii"),
        "cursor": progress.cursor,
        "pending_keys": [_key_text(key) for key in progress.pending_keys],
        "pending_offset": progress.pending_offset,
        "seen_exact_keys": [_key_text(key) for key in progress.seen_exact_keys],
        "seen_cursors": list(progress.seen_cursors),
        "dedupe_saturated": progress.dedupe_saturated,
        "cursor_history_saturated": progress.cursor_history_saturated,
        "last_reset_reason": progress.last_reset_reason,
        "available_at": None,
        "admitted_feature_count": 0,
        "zero_filled_field_count": 0,
        "no_zero_fill_for_unknown_fields": True,
    }
    payload.update({field_name: False for field_name in _SCAN_STATE_FALSE_FIELDS})
    return payload


def _encode_scan_progress(progress: _ScanProgress) -> bytes:
    try:
        encoded = json.dumps(
            _scan_progress_payload(progress),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii", errors="strict")
    except (TypeError, ValueError, OverflowError, UnicodeError):
        _invalid("coinank_hot_series_scan_state_encoding_invalid")
    if not encoded or len(encoded) > MAX_SCAN_STATE_BYTES:
        _invalid("coinank_hot_series_scan_state_size_bound_exceeded")
    return encoded


def _validated_scan_progress(candidate: object) -> _ScanProgress | None:
    if type(candidate) is not dict:
        return None
    state = cast(dict[str, object], candidate)
    if (
        set(state) != _SCAN_STATE_FIELDS
        or state.get("schema_version") != SCAN_STATE_SCHEMA_VERSION
        or state.get("role") != SCAN_STATE_ROLE
        or state.get("scan_pattern") != SERIES_SCAN_MATCH.decode("ascii")
        or state.get("available_at") is not None
        or state.get("admitted_feature_count") != 0
        or type(state.get("admitted_feature_count")) is not int
        or state.get("zero_filled_field_count") != 0
        or type(state.get("zero_filled_field_count")) is not int
        or state.get("no_zero_fill_for_unknown_fields") is not True
        or any(state.get(field_name) is not False for field_name in _SCAN_STATE_FALSE_FIELDS)
    ):
        return None
    cursor = state.get("cursor")
    pending_offset = state.get("pending_offset")
    pending_raw = state.get("pending_keys")
    seen_keys_raw = state.get("seen_exact_keys")
    seen_cursors_raw = state.get("seen_cursors")
    if (
        type(cursor) is not int
        or not 0 <= cursor <= _MAX_UNSIGNED_64
        or type(pending_offset) is not int
        or type(pending_raw) is not list
        or type(seen_keys_raw) is not list
        or type(seen_cursors_raw) is not list
        or type(state.get("dedupe_saturated")) is not bool
        or type(state.get("cursor_history_saturated")) is not bool
        or len(pending_raw) > MAX_SCAN_PAGE_KEYS
        or len(seen_keys_raw) > MAX_SCAN_STATE_SEEN_KEYS
        or len(seen_cursors_raw) > MAX_SCAN_STATE_CURSOR_HISTORY
        or not 0 <= pending_offset <= len(pending_raw)
    ):
        return None
    pending_keys = tuple(_exact_series_key(value) for value in pending_raw)
    seen_keys = tuple(_exact_series_key(value) for value in seen_keys_raw)
    if (
        any(key is None for key in pending_keys)
        or any(key is None for key in seen_keys)
        or len(set(pending_keys)) != len(pending_keys)
        or len(set(seen_keys)) != len(seen_keys)
    ):
        return None
    seen_cursors: list[int] = []
    for value in seen_cursors_raw:
        if type(value) is not int or not 0 <= value <= _MAX_UNSIGNED_64:
            return None
        seen_cursors.append(value)
    if len(set(seen_cursors)) != len(seen_cursors):
        return None
    reset_reason = state.get("last_reset_reason")
    if reset_reason is not None and (
        type(reset_reason) is not str
        or not reset_reason.isascii()
        or not 1 <= len(reset_reason) <= 160
    ):
        return None
    exact_pending = cast(tuple[bytes, ...], pending_keys)
    exact_seen = cast(tuple[bytes, ...], seen_keys)
    dedupe_saturated = cast(bool, state["dedupe_saturated"])
    if not dedupe_saturated and not set(exact_pending).issubset(set(exact_seen)):
        return None
    return _ScanProgress(
        cursor=cursor,
        pending_keys=exact_pending,
        pending_offset=pending_offset,
        seen_exact_keys=exact_seen,
        seen_cursors=tuple(seen_cursors),
        dedupe_saturated=dedupe_saturated,
        cursor_history_saturated=cast(bool, state["cursor_history_saturated"]),
        last_reset_reason=reset_reason,
    )


def _reset_loaded_scan_progress(reason: str) -> _LoadedScanProgress:
    return _LoadedScanProgress(
        progress=_fresh_scan_progress(reset_reason=reason),
        outcome="RESET_INVALID_STATE",
        reset_reason=reason,
    )


def _load_scan_progress(client: Any) -> _LoadedScanProgress:
    response = client.eval(_BOUNDED_READ_LUA, 1, SCAN_STATE_KEY, MAX_SCAN_STATE_BYTES)
    if type(response) is not list or len(response) != 4:
        _invalid("coinank_hot_series_scan_state_read_response_invalid")
    kind = _redis_kind(response[0])
    pttl_ms = _validated_pttl(response[1])
    byte_count = _exact_nonnegative_int(
        response[2],
        reason="coinank_hot_series_scan_state_size_invalid",
    )
    raw = response[3]
    if kind == "none":
        if pttl_ms != -2 or byte_count != 0 or raw is not None:
            _invalid("coinank_hot_series_scan_state_missing_read_inconsistent")
        return _LoadedScanProgress(
            progress=_fresh_scan_progress(),
            outcome="INITIALIZED_MISSING_STATE",
            reset_reason=None,
        )
    if kind != "string":
        return _reset_loaded_scan_progress("WRONG_TYPE_SCAN_STATE_RESET")
    if pttl_ms <= 0:
        return _reset_loaded_scan_progress("NONEXPIRING_SCAN_STATE_RESET")
    if byte_count > MAX_SCAN_STATE_BYTES:
        if raw is not None:
            _invalid("coinank_hot_series_scan_state_oversized_read_inconsistent")
        return _reset_loaded_scan_progress("OVERSIZED_SCAN_STATE_RESET")
    if type(raw) is not bytes or len(raw) != byte_count or byte_count == 0:
        return _reset_loaded_scan_progress("INVALID_SCAN_STATE_RESET")
    try:
        decoded = decode_coinank_hot_series_json(raw, max_bytes=byte_count)
    except CoinAnkHotSeriesValidationError:
        return _reset_loaded_scan_progress("INVALID_SCAN_STATE_RESET")
    progress = _validated_scan_progress(decoded)
    if progress is None:
        return _reset_loaded_scan_progress("INVALID_SCAN_STATE_RESET")
    return _LoadedScanProgress(
        progress=progress,
        outcome="LOADED_VALID_STATE",
        reset_reason=progress.last_reset_reason,
    )


def _persist_scan_progress(client: Any, progress: _ScanProgress) -> None:
    acknowledged = client.set(
        SCAN_STATE_KEY,
        _encode_scan_progress(progress),
        px=SCAN_STATE_TTL_MS,
    )
    if type(acknowledged) is not bool or acknowledged is not True:
        _invalid("coinank_hot_series_scan_state_write_not_acknowledged")


def _remaining_pending(progress: _ScanProgress) -> int:
    return len(progress.pending_keys) - progress.pending_offset


def _validated_scan_page(response: object) -> tuple[int, list[object]]:
    if type(response) not in {list, tuple}:
        _invalid("coinank_hot_series_scan_page_invalid")
    page = cast(list[object] | tuple[object, ...], response)
    if len(page) != 2:
        _invalid("coinank_hot_series_scan_page_invalid")
    next_cursor = page[0]
    raw_keys = page[1]
    if type(next_cursor) is not int or next_cursor < 0:
        _invalid("coinank_hot_series_scan_cursor_invalid")
    if type(raw_keys) not in {list, tuple}:
        _invalid("coinank_hot_series_scan_keys_invalid")
    keys = list(cast(list[object] | tuple[object, ...], raw_keys))
    if len(keys) > MAX_SCAN_PAGE_KEYS:
        _invalid("coinank_hot_series_scan_page_key_bound_exceeded")
    return next_cursor, keys


def run_compaction(
    client: object,
    *,
    max_keys: int = MAX_KEYS_PER_RUN,
    max_bytes_read: int = MAX_BYTES_READ_PER_RUN,
    max_runtime_seconds: float = MAX_RUNTIME_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> RunCompactionStatus:
    """Run one resumable bounded scan without touching latest/raw sources."""

    if type(max_keys) is not int or not 1 <= max_keys <= MAX_KEYS_PER_RUN:
        _invalid("coinank_hot_series_run_key_bound_invalid")
    if type(max_bytes_read) is not int or not 1 <= max_bytes_read <= MAX_BYTES_READ_PER_RUN:
        _invalid("coinank_hot_series_run_byte_bound_invalid")
    if (
        type(max_runtime_seconds) not in {int, float}
        or not 0 < max_runtime_seconds <= MAX_RUNTIME_SECONDS
    ):
        _invalid("coinank_hot_series_run_time_bound_invalid")

    started = clock()
    budget = _RunBudget(
        maximum_bytes=max_bytes_read,
        deadline=started + float(max_runtime_seconds),
        clock=clock,
    )
    redis_client = cast(Any, client)
    results: list[KeyCompactionStatus] = []
    scan_pages = 0
    scanned = 0
    exact = 0
    deduplicated = 0
    stop_reason: str | None = None
    progress = _fresh_scan_progress()
    scan_state_load_outcome = "SCAN_STATE_NOT_LOADED"
    scan_state_reset_reason: str | None = None
    scan_state_persisted = False
    scan_start_cursor = 0
    pending_start_key_count = 0
    scan_cycle_completed = False

    def persist_progress(candidate: _ScanProgress) -> None:
        nonlocal progress, scan_state_persisted
        scan_state_persisted = False
        _persist_scan_progress(redis_client, candidate)
        progress = candidate
        scan_state_persisted = True

    try:
        loaded = _load_scan_progress(redis_client)
        progress = loaded.progress
        scan_state_load_outcome = loaded.outcome
        scan_state_reset_reason = loaded.reset_reason
        scan_start_cursor = progress.cursor
        pending_start_key_count = _remaining_pending(progress)
        persist_progress(progress)
        stop_scanning = False
        while not stop_scanning:
            while progress.pending_offset < len(progress.pending_keys):
                budget.check_time()
                if exact >= max_keys:
                    stop_reason = "coinank_hot_series_key_budget_exhausted"
                    stop_scanning = True
                    break
                key = progress.pending_keys[progress.pending_offset]
                exact += 1
                before = budget.bytes_read
                advance_pending = True
                try:
                    result = compact_exact_series_key(
                        redis_client,
                        series_key=key,
                        budget=budget,
                    )
                except _RunLimitReached as exc:
                    results.append(
                        _skipped_status(
                            key=key,
                            reason=str(exc),
                            bytes_read=budget.bytes_read - before,
                        )
                    )
                    stop_reason = str(exc)
                    stop_scanning = True
                    advance_pending = False
                except (
                    CoinAnkHotSeriesCompactorError,
                    CoinAnkHotSeriesValidationError,
                ) as exc:
                    results.append(
                        _skipped_status(
                            key=key,
                            reason=str(exc),
                            bytes_read=budget.bytes_read - before,
                        )
                    )
                except redis.RedisError:
                    results.append(
                        _skipped_status(
                            key=key,
                            reason="coinank_hot_series_redis_error",
                            bytes_read=budget.bytes_read - before,
                        )
                    )
                    stop_reason = "coinank_hot_series_key_redis_error"
                    stop_scanning = True
                    advance_pending = False
                else:
                    results.append(result)
                if advance_pending:
                    persist_progress(replace(progress, pending_offset=progress.pending_offset + 1))
                if stop_scanning:
                    break
            if stop_scanning:
                break
            if progress.pending_keys:
                persist_progress(replace(progress, pending_keys=(), pending_offset=0))
            if progress.cursor == 0 and progress.seen_cursors:
                persist_progress(_fresh_scan_progress())
                scan_cycle_completed = True
                break
            budget.check_scan_boundary()
            if scan_pages >= MAX_SCAN_PAGES_PER_RUN:
                stop_reason = "coinank_hot_series_scan_page_bound_exhausted"
                break
            if scanned > MAX_SCAN_RESULTS_PER_RUN - MAX_SCAN_PAGE_KEYS:
                stop_reason = "coinank_hot_series_scan_result_bound_exhausted"
                break
            if progress.cursor in progress.seen_cursors:
                reset_reason = "SCAN_CURSOR_CYCLE_STATE_RESET"
                persist_progress(_fresh_scan_progress(reset_reason=reset_reason))
                scan_state_reset_reason = reset_reason
                stop_reason = "coinank_hot_series_scan_cursor_cycle"
                break
            response = redis_client.scan(
                cursor=progress.cursor,
                match=SERIES_SCAN_MATCH,
                count=SCAN_COUNT,
            )
            scan_pages += 1
            next_cursor, keys = _validated_scan_page(response)
            if scanned + len(keys) > MAX_SCAN_RESULTS_PER_RUN:
                stop_reason = "coinank_hot_series_scan_result_bound_exhausted"
                break
            scanned += len(keys)
            seen = set(progress.seen_exact_keys)
            seen_cursors = list(progress.seen_cursors)
            cursor_history_saturated = progress.cursor_history_saturated
            if len(seen_cursors) < MAX_SCAN_STATE_CURSOR_HISTORY:
                seen_cursors.append(progress.cursor)
            else:
                cursor_history_saturated = True
            pending: list[bytes] = []
            page_seen: set[bytes] = set()
            dedupe_saturated = progress.dedupe_saturated
            seen_ordered = list(progress.seen_exact_keys)
            for candidate in keys:
                candidate_key = _exact_series_key(candidate)
                if candidate_key is None:
                    continue
                if candidate_key in page_seen or candidate_key in seen:
                    deduplicated += 1
                    continue
                page_seen.add(candidate_key)
                pending.append(candidate_key)
                if len(seen_ordered) < MAX_SCAN_STATE_SEEN_KEYS:
                    seen_ordered.append(candidate_key)
                    seen.add(candidate_key)
                else:
                    dedupe_saturated = True
            persist_progress(
                _ScanProgress(
                    cursor=next_cursor,
                    pending_keys=tuple(pending),
                    pending_offset=0,
                    seen_exact_keys=tuple(seen_ordered),
                    seen_cursors=tuple(seen_cursors),
                    dedupe_saturated=dedupe_saturated,
                    cursor_history_saturated=cursor_history_saturated,
                    last_reset_reason=progress.last_reset_reason,
                )
            )
            budget.check_scan_boundary()
    except _RunLimitReached as exc:
        stop_reason = str(exc)
    except CoinAnkHotSeriesCompactorError as exc:
        stop_reason = str(exc)
    except redis.RedisError:
        stop_reason = "coinank_hot_series_scan_or_state_redis_error"

    elapsed = max(0.0, clock() - started)
    return RunCompactionStatus(
        generated_at=_utc_now(),
        elapsed_seconds=round(elapsed, 6),
        scan_page_count=scan_pages,
        scanned_key_count=scanned,
        exact_key_count=exact,
        compacted_key_count=sum(result.outcome == "compacted" for result in results),
        rebuilt_key_count=sum(result.outcome.startswith("rebuilt_") for result in results),
        skipped_key_count=sum(result.outcome == "skipped" for result in results),
        cas_conflict_count=sum(result.outcome == "cas_conflict" for result in results),
        bytes_read=budget.bytes_read,
        bytes_written=sum(result.stored_bytes for result in results),
        expiring_write_count=sum(result.output_expiring for result in results),
        stop_reason=stop_reason,
        scan_start_cursor=scan_start_cursor,
        scan_end_cursor=progress.cursor,
        pending_start_key_count=pending_start_key_count,
        pending_end_key_count=_remaining_pending(progress),
        deduplicated_key_count=deduplicated,
        scan_cycle_completed=scan_cycle_completed,
        scan_state_load_outcome=scan_state_load_outcome,
        scan_state_reset_reason=scan_state_reset_reason,
        scan_state_persisted=scan_state_persisted,
        key_results=tuple(results),
    )


def _redis_client(url: str) -> Any:
    return redis.Redis.from_url(
        url,
        decode_responses=False,
        socket_connect_timeout=2.0,
        socket_timeout=5.0,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
    )
    parser.add_argument("--max-keys", type=int, default=MAX_KEYS_PER_RUN)
    parser.add_argument("--max-bytes-read", type=int, default=MAX_BYTES_READ_PER_RUN)
    parser.add_argument("--max-runtime-seconds", type=float, default=MAX_RUNTIME_SECONDS)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    client = _redis_client(str(args.redis_url))
    try:
        client.ping()
        status = run_compaction(
            client,
            max_keys=int(args.max_keys),
            max_bytes_read=int(args.max_bytes_read),
            max_runtime_seconds=float(args.max_runtime_seconds),
        )
    except (CoinAnkHotSeriesCompactorError, redis.RedisError) as exc:
        payload = {
            "schema_version": STATUS_SCHEMA_VERSION,
            "service": SERVICE_ID,
            "status": "BLOCKED",
            "reason": (
                str(exc) if isinstance(exc, CoinAnkHotSeriesCompactorError) else "redis_error"
            ),
            "publication_authority": False,
            "trainer_authority": False,
            "prediction_authority": False,
            "risk_authority": False,
            "orchestrator_authority": False,
            "allocator_authority": False,
            "paper_authority": False,
            "live_authority": False,
            "live_execution_authority": False,
            "actual_consumption": False,
            "trainer_admission_granted": False,
            "admitted_feature_count": 0,
            "available_at": None,
            "zero_filled_field_count": 0,
            "no_zero_fill_for_unknown_fields": True,
        }
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 2
    payload = asdict(status)
    if args.as_json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"{SERVICE_ID}: exact={status.exact_key_count} "
            f"compacted={status.compacted_key_count} rebuilt={status.rebuilt_key_count} "
            f"skipped={status.skipped_key_count} conflicts={status.cas_conflict_count}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
