"""Bounded optimistic Redis publication for canonical closed-candle windows.

The Binance WebSocket publisher and the REST recovery worker both update the
same ``v2:market:ohlcv_closed:*`` keys. A plain client-side GET/merge/SET can
lose a concurrent writer's candle. This module provides one narrowly scoped
WATCH/MULTI/EXEC boundary so every cooperating publisher retries against the
newest committed value.

The one-mebibyte payload ceiling, strict canonical ABI validation, bounded
Redis reads, and retry/row limits are resource and source-integrity invariants.
They do not select markets, grant feature/trainer admission, or authorize
trading. Publication is not a provenance receipt or immutable CAS capture.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Final, NoReturn, cast

import redis

from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    MAX_OHLCV_CLOSED_PAYLOAD_BYTES,
    MAX_OHLCV_CLOSED_ROWS,
    SUPPORTED_TRAINER_TIMEFRAMES,
    OHLCVClosedWindowValidationError,
    validate_ohlcv_closed_window,
)

CLOSED_WINDOW_MAX_PAYLOAD_BYTES: Final = MAX_OHLCV_CLOSED_PAYLOAD_BYTES
CLOSED_WINDOW_MAX_ROWS: Final = MAX_OHLCV_CLOSED_ROWS
CLOSED_WINDOW_MAX_NEW_ROWS_PER_WRITE: Final = MAX_OHLCV_CLOSED_ROWS
CLOSED_WINDOW_MAX_WRITE_RETRIES: Final = 32
CLOSED_WINDOW_MAX_TTL_SECONDS: Final = 366 * 24 * 60 * 60
CLOSED_WINDOW_MAX_JSON_STRING_BYTES: Final = 512
CLOSED_WINDOW_MAX_ROW_FIELDS: Final = 64
CLOSED_WINDOW_MAX_NESTED_FIELDS: Final = 64
CLOSED_WINDOW_TTL_POLICIES: Final = ("preserve", "set", "persist")

_MAX_SIGNED_64 = (1 << 63) - 1
_CANDLE_ID_RE = re.compile(r"^[0-9a-f]{24}$")
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,32}$")
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
    """One successfully acknowledged optimistic window update."""

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
    exact_source_schema_validated: bool = field(default=True, init=False)
    immutable_cas_captured: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)


def _invalid(reason: str) -> NoReturn:
    raise ClosedWindowRedisStoreError(reason) from None


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
                if id_match is not open_match or incumbent is None or incumbent[1] != row_json:
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
    row_limit: object = CLOSED_WINDOW_MAX_ROWS,
    max_payload_bytes: object = CLOSED_WINDOW_MAX_PAYLOAD_BYTES,
    minimum_rows_to_preserve: object = 1,
    ttl_policy: object = "preserve",
    ttl_seconds: object = None,
    max_retries: object = 8,
    replace_invalid_existing: object = False,
) -> ClosedWindowRedisWriteResult:
    """WATCH/merge/SET one closed window without losing cooperating writers."""

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
    if client is None or not callable(getattr(client, "pipeline", None)):
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
            _validated_schema_rows(
                bounded.payload_json.encode("ascii"),
                symbol=symbol,
                timeframe=timeframe,
                error_prefix="merged",
            )

            pipe.multi()
            if resolved_ttl_policy == "preserve":
                pipe.set(key, bounded.payload_json, keepttl=True)
            elif resolved_ttl_policy == "set":
                pipe.set(key, bounded.payload_json, ex=ttl)
            else:
                pipe.set(key, bounded.payload_json)
            outcome = pipe.execute()
            if type(outcome) is not list or outcome != [True]:
                _invalid("closed_window_redis_commit_not_acknowledged")
            return ClosedWindowRedisWriteResult(
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
            )
        except redis.WatchError:
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
