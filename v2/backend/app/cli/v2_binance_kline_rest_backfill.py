"""Bounded Binance REST recovery for exact canonical closed-candle windows.

The Binance WebSocket cache remains primary.  A REST request is made only when
the exact canonical Redis value fails the feature-derived core-TA coverage
contract: the latest finalized candle must be present and the *full* latest
contiguous suffix must contain at least the derived minimum source rows.

This worker handles read-only public market data.  It never submits, changes,
or cancels an order.  A successful Redis publication is not trainer admission,
a provenance receipt, or live-execution authority.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from itertools import islice
from pathlib import Path
from typing import Any, Final, NoReturn, cast

_repo = Path(__file__).resolve().parents[4]
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

import redis  # noqa: E402

from v2.backend.app.services.binance_unified_websocket_transport import (  # noqa: E402
    REST_FALLBACK_ENV,
    binance_rest_fallback_allowed,
    report_binance_rest_response,
    require_binance_rest_fallback,
)
from v2.backend.app.services.market_state_integrity.canonical_candles import (  # noqa: E402
    TIMEFRAME_SECONDS,
    canonical_from_binance_rest,
    closed_candle_key,
)
from v2.backend.app.services.market_state_integrity.closed_window_redis_store import (  # noqa: E402
    CLOSED_WINDOW_MAX_ROWS,
    CLOSED_WINDOW_MAX_TTL_SECONDS,
    ClosedWindowRedisStoreError,
    ClosedWindowRedisWriteResult,
    atomic_merge_closed_window,
)
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (  # noqa: E402
    AtomicRedisSourceReadError,
    RawRedisSourceClient,
    read_atomic_redis_sources,
)
from v2.backend.app.services.native_trainer.feature_window_dependency_contract import (  # noqa: E402
    CORE_TA_MINIMUM_SOURCE_ROWS,
    FeatureWindowContractError,
    inspect_canonical_contiguous_suffix,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (  # noqa: E402
    MAX_OHLCV_CLOSED_PAYLOAD_BYTES,
    SUPPORTED_TRAINER_TIMEFRAMES,
    TIMEFRAME_DURATION_MS,
    OHLCVClosedWindowValidationError,
    ValidatedOHLCVClosedWindow,
    validate_ohlcv_closed_window,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (  # noqa: E402
    is_valid_runtime_symbol,
    resolve_symbols,
)

BINANCE_FAPI: Final = "https://fapi.binance.com"
BACKFILL_LIMIT: Final = 200
BACKFILL_TIMEFRAMES: Final = ("1h", "4h")
# Compatibility name retained for callers; this is derived from the actual
# feature-transform contract and is not a market-selection threshold.
MIN_CANDLES_THRESHOLD: Final = CORE_TA_MINIMUM_SOURCE_ROWS

# Fixed transport/resource bounds, never market or trading thresholds.
MAX_HTTP_RESPONSE_BYTES: Final = MAX_OHLCV_CLOSED_PAYLOAD_BYTES
MAX_HTTP_RETRIES: Final = 5
MAX_BINANCE_KLINE_LIMIT: Final = 1_000
MAX_DISCOVERED_CURRENT_KEYS: Final = 4096
MAX_EXPLICIT_BACKFILL_SYMBOLS: Final = 4096
MAX_BACKFILL_PAIRS_PER_RUN: Final = 4096
REDIS_SCAN_COUNT_HINT: Final = 256
ATOMIC_OVERLAP_REASSESS_ATTEMPTS: Final = 3
DEFAULT_CLOSED_WINDOW_TTL_FLOOR_SECONDS: Final = 86_400
CLOSED_WINDOW_TTL_FLOOR_ENV: Final = "V2_BACKFILL_CLOSED_WINDOW_TTL_FLOOR_SECONDS"
MAX_INTER_REQUEST_SLEEP_SECONDS: Final = 60.0

_MAX_SIGNED_64: Final = (1 << 63) - 1
_STABLE_ERROR_CODE_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,127}$")
TERMINAL_REST_RECOVERY_ERROR_CODES: Final = frozenset(
    {
        "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
        "REST_FALLBACK_BUDGET_EXHAUSTED_BAN_PROTECTION",
        "REST_FALLBACK_COOLDOWN_BAN_PROTECTION",
        "REST_FALLBACK_COOLDOWN_PERSISTENT_KEY_FAIL_CLOSED",
        "REST_FALLBACK_SHARED_BUDGET_UNAVAILABLE",
        "kline_backfill_http_rate_or_ban_limit",
        "kline_backfill_shared_rate_limit_cooldown_persistence_failed",
    }
)


class KlineBackfillRecoveryError(RuntimeError):
    """A stable, redacted recovery error safe for status publication."""


@dataclass(frozen=True, slots=True)
class ClosedWindowCacheAssessment:
    """Strict bounded evidence about one exact mutable Redis source value."""

    redis_key: str
    symbol: str
    timeframe: str
    status: str
    ready: bool
    consumer_observed_at_ms: int
    expected_latest_finalized_close_time: int
    exact_payload_byte_count: int
    exact_payload_sha256: str | None
    row_count: int
    contiguous_suffix_count: int
    tail_missing_interval_count: int | None
    existing_open_times: frozenset[int] = field(repr=False)
    error_code: str | None = None
    source_schema_validated: bool = False
    end_exclusive_finality_validated: bool = False
    core_ta_minimum_source_rows: int = field(
        default=CORE_TA_MINIMUM_SOURCE_ROWS,
        init=False,
    )
    market_selection_threshold: bool = field(default=False, init=False)
    trainer_admission_granted: bool = field(default=False, init=False)
    live_execution_authorized: bool = field(default=False, init=False)


def _fail(code: str) -> NoReturn:
    raise KlineBackfillRecoveryError(code) from None


def _stable_error_code(exc: BaseException) -> str:
    """Collapse arbitrary exception text to one allow-listed identifier."""

    text = str(exc).strip()
    known_prefixes = (
        "REST_FALLBACK_BUDGET_EXHAUSTED_BAN_PROTECTION",
        "REST_FALLBACK_COOLDOWN_BAN_PROTECTION",
        "REST_FALLBACK_COOLDOWN_PERSISTENT_KEY_FAIL_CLOSED",
        "REST_FALLBACK_SHARED_BUDGET_UNAVAILABLE",
        "REST_FALLBACK_REQUEST_WEIGHT_INVALID",
        "REST_FALLBACK_REASON_REQUIRED_WEBSOCKET_PRIMARY",
        "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
        "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
    )
    for prefix in known_prefixes:
        if text.startswith(prefix):
            if prefix == "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY":
                return "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY"
            return prefix
    candidate = text.split(":", 1)[0]
    stable_families = (
        "kline_backfill_",
        "closed_window_",
        "atomic_redis_",
        "ohlcv_closed_",
        "feature_window_",
    )
    if (
        candidate.startswith(stable_families)
        and _STABLE_ERROR_CODE_RE.fullmatch(candidate) is not None
    ):
        return candidate
    return "kline_backfill_internal_error"


def _raise_stable(exc: BaseException) -> NoReturn:
    code = _stable_error_code(exc)
    if isinstance(exc, KlineBackfillRecoveryError) and str(exc) == code:
        raise exc
    raise KlineBackfillRecoveryError(code) from exc


def _exact_int(
    value: object,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(f"kline_backfill_{field_name}_invalid")
    return value


def _validated_sleep_seconds(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        _fail("kline_backfill_sleep_seconds_invalid")
    resolved = float(value)
    if not math.isfinite(resolved) or not 0 <= resolved <= MAX_INTER_REQUEST_SLEEP_SECONDS:
        _fail("kline_backfill_sleep_seconds_invalid")
    return resolved


def _validated_symbol(value: object) -> str:
    if type(value) is not str:
        _fail("kline_backfill_symbol_invalid")
    symbol = value
    if symbol != symbol.upper() or not is_valid_runtime_symbol(symbol):
        _fail("kline_backfill_symbol_invalid")
    return symbol


def _validated_timeframe(value: object) -> str:
    if type(value) is not str or value not in SUPPORTED_TRAINER_TIMEFRAMES:
        _fail("kline_backfill_timeframe_invalid")
    return value


def _require_binary_client(client: object) -> RawRedisSourceClient:
    try:
        connection_kwargs = client.get_connection_kwargs()  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - untrusted client metadata
        raise KlineBackfillRecoveryError("kline_backfill_redis_client_raw_mode_unverified") from exc
    if (
        type(connection_kwargs) is not dict
        or connection_kwargs.get("decode_responses") is not False
    ):
        _fail("kline_backfill_redis_client_raw_mode_unverified")
    return cast(RawRedisSourceClient, client)


def _redis_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, decode_responses=False)


def _consumer_observed_at_ms() -> int:
    """Local instant immediately after exact bytes are possessed."""

    return time.time_ns() // 1_000_000


def _expected_latest_finalized_close_time(
    timeframe: str,
    consumer_observed_at_ms: int,
) -> int:
    duration_ms = TIMEFRAME_DURATION_MS[timeframe]
    return ((consumer_observed_at_ms // duration_ms) * duration_ms) - 1


def _empty_assessment(
    *,
    key: str,
    symbol: str,
    timeframe: str,
    status: str,
    observed_at_ms: int,
    error_code: str | None = None,
) -> ClosedWindowCacheAssessment:
    return ClosedWindowCacheAssessment(
        redis_key=key,
        symbol=symbol,
        timeframe=timeframe,
        status=status,
        ready=False,
        consumer_observed_at_ms=observed_at_ms,
        expected_latest_finalized_close_time=(
            _expected_latest_finalized_close_time(timeframe, observed_at_ms)
        ),
        exact_payload_byte_count=0,
        exact_payload_sha256=None,
        row_count=0,
        contiguous_suffix_count=0,
        tail_missing_interval_count=None,
        existing_open_times=frozenset(),
        error_code=error_code,
    )


def _inspection_projection(
    validated: ValidatedOHLCVClosedWindow,
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "symbol": row.symbol,
            "timeframe": row.timeframe,
            "candle_id": row.candle_id,
            "candle_open_time": row.candle_open_time,
            "candle_close_time": row.candle_close_time,
            "available_at": row.available_at,
        }
        for row in validated.rows
    )


def _assess_closed_window(
    client: object,
    symbol: str,
    timeframe: str,
) -> ClosedWindowCacheAssessment:
    """Read exact bounded bytes and assess the complete latest suffix."""

    bound_symbol = _validated_symbol(symbol)
    bound_timeframe = _validated_timeframe(timeframe)
    raw_client = _require_binary_client(client)
    key = closed_candle_key("binance", bound_symbol, bound_timeframe)
    try:
        batch = read_atomic_redis_sources(raw_client, (key,))
        # Redis TIME is not this clock.  This timestamp is captured only after
        # the client possesses the bounded transaction response.
        observed_at_ms = _consumer_observed_at_ms()
    except AtomicRedisSourceReadError as exc:
        observed_at_ms = _consumer_observed_at_ms()
        error_code = _stable_error_code(exc)
        status = (
            "cache_payload_oversized"
            if error_code == "atomic_redis_source_read_payload_bytes_exceeded"
            else "cache_assessment_unavailable"
        )
        return _empty_assessment(
            key=key,
            symbol=bound_symbol,
            timeframe=bound_timeframe,
            status=status,
            observed_at_ms=observed_at_ms,
            error_code=error_code,
        )

    result = batch.results[0]
    if not result.present:
        return _empty_assessment(
            key=key,
            symbol=bound_symbol,
            timeframe=bound_timeframe,
            status="cache_missing",
            observed_at_ms=observed_at_ms,
        )
    payload = result.exact_payload_bytes
    try:
        validated = validate_ohlcv_closed_window(
            payload,
            symbol=bound_symbol,
            timeframe=bound_timeframe,
        )
    except OHLCVClosedWindowValidationError as exc:
        assessment = _empty_assessment(
            key=key,
            symbol=bound_symbol,
            timeframe=bound_timeframe,
            status="cache_schema_invalid",
            observed_at_ms=observed_at_ms,
            error_code=_stable_error_code(exc),
        )
        return replace(
            assessment,
            exact_payload_byte_count=result.payload_byte_count,
            exact_payload_sha256=result.payload_sha256,
        )

    expected_latest = _expected_latest_finalized_close_time(
        bound_timeframe,
        observed_at_ms,
    )
    existing_open_times = frozenset(row.candle_open_time for row in validated.rows)
    try:
        inspection = inspect_canonical_contiguous_suffix(
            _inspection_projection(validated),
            expected_symbol=bound_symbol,
            timeframe=bound_timeframe,
            consumer_observed_at_ms=observed_at_ms,
            expected_latest_finalized_close_time=expected_latest,
        )
    except FeatureWindowContractError as exc:
        return ClosedWindowCacheAssessment(
            redis_key=key,
            symbol=bound_symbol,
            timeframe=bound_timeframe,
            status="cache_consumer_contract_invalid",
            ready=False,
            consumer_observed_at_ms=observed_at_ms,
            expected_latest_finalized_close_time=expected_latest,
            exact_payload_byte_count=validated.exact_payload_byte_count,
            exact_payload_sha256=validated.exact_payload_sha256,
            row_count=validated.row_count,
            contiguous_suffix_count=validated.contiguous_suffix_count,
            tail_missing_interval_count=None,
            existing_open_times=existing_open_times,
            error_code=_stable_error_code(exc),
            source_schema_validated=True,
        )

    ready = inspection.core_ta_minimum_coverage_ready
    if ready:
        status = "cache_ready"
    elif inspection.tail_missing_interval_count != 0:
        status = "cache_tail_stale"
    else:
        status = "cache_contiguous_suffix_short"
    return ClosedWindowCacheAssessment(
        redis_key=key,
        symbol=bound_symbol,
        timeframe=bound_timeframe,
        status=status,
        ready=ready,
        consumer_observed_at_ms=observed_at_ms,
        expected_latest_finalized_close_time=expected_latest,
        exact_payload_byte_count=validated.exact_payload_byte_count,
        exact_payload_sha256=validated.exact_payload_sha256,
        row_count=validated.row_count,
        contiguous_suffix_count=inspection.contiguous_suffix_count,
        tail_missing_interval_count=inspection.tail_missing_interval_count,
        existing_open_times=existing_open_times,
        source_schema_validated=True,
        end_exclusive_finality_validated=True,
    )


def _reject_json_constant(_value: str) -> NoReturn:
    _fail("kline_backfill_http_json_nonfinite")


def _fallback_policy_error(exc: RuntimeError) -> KlineBackfillRecoveryError:
    return KlineBackfillRecoveryError(_stable_error_code(exc))


def _retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    try:
        value = exc.headers.get("Retry-After")
        if value is None:
            return None
        parsed = float(value)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Make redirects terminal so one reservation means one exact request."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_RejectRedirectHandler())


def _open_exact_public_request(
    request: urllib.request.Request,
    *,
    timeout: float,
) -> Any:
    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)  # noqa: S310


def _binance_kline_request_weight(limit: object) -> int:
    """Return Binance USD-M's published request weight for one kline page."""

    bounded_limit = _exact_int(
        limit,
        field_name="limit",
        minimum=1,
        maximum=MAX_BINANCE_KLINE_LIMIT,
    )
    if bounded_limit < 100:
        return 1
    if bounded_limit < 500:
        return 2
    return 5


def _validated_http_kline_request(parsed_url: urllib.parse.ParseResult) -> int:
    """Validate the exact public request identity and return its weight."""

    if parsed_url.params or parsed_url.fragment or not parsed_url.query:
        _fail("kline_backfill_http_url_invalid")
    try:
        pairs = urllib.parse.parse_qsl(
            parsed_url.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError:
        _fail("kline_backfill_http_url_invalid")
    if len(pairs) != 3 or {name for name, _value in pairs} != {
        "symbol",
        "interval",
        "limit",
    }:
        _fail("kline_backfill_http_url_invalid")
    values = {name: value for name, value in pairs}
    _validated_symbol(values["symbol"])
    _validated_timeframe(values["interval"])
    raw_limit = values["limit"]
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError, OverflowError):
        _fail("kline_backfill_limit_invalid")
    if str(limit) != raw_limit:
        _fail("kline_backfill_limit_invalid")
    return _binance_kline_request_weight(limit)


def _http_get(
    url: str,
    *,
    retries: int = 3,
    backoff: float = 2.0,
) -> tuple[list[object], int, int]:
    """Fetch and decode at most one mebibyte of public response bytes."""

    attempts = _exact_int(
        retries,
        field_name="http_retries",
        minimum=1,
        maximum=MAX_HTTP_RETRIES,
    )
    if type(backoff) not in (int, float) or not math.isfinite(float(backoff)):
        _fail("kline_backfill_http_backoff_invalid")
    delay = float(backoff)
    if not 0 <= delay <= 30:
        _fail("kline_backfill_http_backoff_invalid")
    parsed_url = urllib.parse.urlparse(url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc != "fapi.binance.com"
        or parsed_url.path != "/fapi/v1/klines"
    ):
        _fail("kline_backfill_http_url_invalid")
    request_weight = _validated_http_kline_request(parsed_url)
    for attempt in range(attempts):
        try:
            # The shared counter is a reservation for one physical request,
            # so every retry must consume its own request weight.
            try:
                require_binance_rest_fallback(
                    endpoint=parsed_url.path or "binance_fapi_klines",
                    fallback_reason="operator_requested_kline_gap_backfill",
                    role="kline_gap_backfill_recovery",
                    request_weight=request_weight,
                    require_shared_budget=True,
                )
            except RuntimeError as exc:
                raise _fallback_policy_error(exc) from exc
            request = urllib.request.Request(  # noqa: S310 - exact HTTPS host checked above
                url,
                headers={"User-Agent": "v2-backfill/2.0"},
            )
            request_started_at_ms = _consumer_observed_at_ms()
            with _open_exact_public_request(
                request,
                timeout=15,
            ) as response:
                payload = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
                # This is the ingestion/availability receipt clock. Finality
                # remains bound to request_started_at_ms so neither transfer
                # nor JSON decoding can move the cutoff past a boundary.
                response_received_at_ms = _consumer_observed_at_ms()
            if response_received_at_ms < request_started_at_ms:
                _fail("kline_backfill_http_clock_order_invalid")
            if type(payload) is not bytes:
                _fail("kline_backfill_http_payload_type_invalid")
            if not payload:
                _fail("kline_backfill_http_payload_empty")
            if len(payload) > MAX_HTTP_RESPONSE_BYTES:
                _fail("kline_backfill_http_payload_oversized")
            try:
                decoded = json.loads(
                    payload.decode("utf-8", errors="strict"),
                    parse_constant=_reject_json_constant,
                )
            except KlineBackfillRecoveryError:
                raise
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                _fail("kline_backfill_http_json_invalid")
            if type(decoded) is not list:
                _fail("kline_backfill_http_response_type_invalid")
            if len(decoded) > CLOSED_WINDOW_MAX_ROWS:
                _fail("kline_backfill_http_response_row_count_invalid")
            return (
                cast(list[object], decoded),
                request_started_at_ms,
                response_received_at_ms,
            )
        except KlineBackfillRecoveryError:
            raise
        except urllib.error.HTTPError as exc:
            if (
                report_binance_rest_response(
                    status_code=int(exc.code),
                    retry_after_seconds=_retry_after_seconds(exc),
                )
                is not True
            ):
                _fail("kline_backfill_shared_rate_limit_cooldown_persistence_failed")
            if exc.code in (418, 429):
                _fail("kline_backfill_http_rate_or_ban_limit")
            if attempt == attempts - 1:
                _fail("kline_backfill_http_status_error")
        except (OSError, TimeoutError, urllib.error.URLError):
            if attempt == attempts - 1:
                _fail("kline_backfill_http_transport_error")
        except Exception as exc:  # noqa: BLE001 - transport implementation boundary
            if attempt == attempts - 1:
                raise KlineBackfillRecoveryError("kline_backfill_http_transport_error") from exc
        if delay:
            time.sleep(delay * (attempt + 1))
    _fail("kline_backfill_http_transport_error")


def _fetch_rest_klines(
    symbol: str,
    interval: str,
    limit: int = BACKFILL_LIMIT,
) -> tuple[list[object], int, int]:
    bound_symbol = _validated_symbol(symbol)
    bound_timeframe = _validated_timeframe(interval)
    bounded_limit = _exact_int(
        limit,
        field_name="limit",
        minimum=1,
        maximum=MAX_BINANCE_KLINE_LIMIT,
    )
    query = urllib.parse.urlencode(
        {
            "symbol": bound_symbol,
            "interval": bound_timeframe,
            "limit": bounded_limit,
        }
    )
    rows, request_started_at_ms, response_received_at_ms = _http_get(
        f"{BINANCE_FAPI}/fapi/v1/klines?{query}"
    )
    if len(rows) > bounded_limit:
        _fail("kline_backfill_rest_row_count_exceeds_request")
    for row in rows:
        if type(row) is not list or not 11 <= len(row) <= 12:
            _fail("kline_backfill_rest_row_shape_invalid")
    return rows, request_started_at_ms, response_received_at_ms


def _fetch_klines(
    client: object,
    symbol: str,
    interval: str,
    limit: int = BACKFILL_LIMIT,
) -> tuple[list[object], str]:
    """Compatibility wrapper: use cache only when it is contract-ready."""

    assessment = _assess_closed_window(client, symbol, interval)
    if assessment.ready:
        return [], "websocket_cache_primary"
    rows, _request_started_at_ms, _response_received_at_ms = _fetch_rest_klines(
        symbol,
        interval,
        limit,
    )
    return rows, "rest_fallback"


def _canonicalize_finalized_rest_rows(
    rows: list[object],
    *,
    symbol: str,
    timeframe: str,
    request_started_at_ms: int,
    response_received_at_ms: int,
) -> tuple[dict[str, Any], ...]:
    """Convert only candles already final when the request began."""

    request_at_ms = _exact_int(
        request_started_at_ms,
        field_name="request_started_at_ms",
        minimum=1,
        maximum=_MAX_SIGNED_64,
    )
    received_at_ms = _exact_int(
        response_received_at_ms,
        field_name="response_received_at_ms",
        minimum=1,
        maximum=_MAX_SIGNED_64,
    )
    if received_at_ms < request_at_ms:
        _fail("kline_backfill_http_clock_order_invalid")
    canonical: list[dict[str, Any]] = []
    for raw_row in rows:
        if type(raw_row) is not list or not 11 <= len(raw_row) <= 12:
            _fail("kline_backfill_rest_row_shape_invalid")
        try:
            candle = canonical_from_binance_rest(
                raw_row,
                symbol=symbol,
                timeframe=timeframe,
                ingested_at=received_at_ms,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise KlineBackfillRecoveryError(
                "kline_backfill_rest_row_canonicalization_invalid"
            ) from exc
        # Binance close time is inclusive. Request-start is the conservative
        # finality cutoff: a response that straddles a close cannot promote the
        # row serialized while it was still the current candle.
        if not candle.is_closed or candle.candle_close_time >= request_at_ms:
            continue
        canonical.append(candle.to_dict())

    canonical.sort(key=lambda row: cast(int, row["candle_open_time"]))
    if not canonical:
        return ()
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    try:
        validate_ohlcv_closed_window(
            encoded,
            symbol=symbol,
            timeframe=timeframe,
        )
    except OHLCVClosedWindowValidationError as exc:
        raise KlineBackfillRecoveryError("kline_backfill_rest_canonical_schema_invalid") from exc
    return tuple(canonical)


def _adaptive_closed_window_ttl_seconds(
    timeframe: str,
    configured_floor_seconds: int | None = None,
) -> int:
    """Scale expiry with cadence while preserving the deployment floor."""

    bound_timeframe = _validated_timeframe(timeframe)
    if configured_floor_seconds is None:
        raw_floor = os.environ.get(CLOSED_WINDOW_TTL_FLOOR_ENV)
        if raw_floor is None or not raw_floor.strip():
            floor = DEFAULT_CLOSED_WINDOW_TTL_FLOOR_SECONDS
        else:
            try:
                floor = int(raw_floor)
            except (TypeError, ValueError, OverflowError):
                _fail("kline_backfill_ttl_floor_invalid")
    else:
        floor = configured_floor_seconds
    floor = _exact_int(
        floor,
        field_name="ttl_floor",
        minimum=1,
        maximum=CLOSED_WINDOW_MAX_TTL_SECONDS,
    )
    cadence_seconds = TIMEFRAME_SECONDS[bound_timeframe]
    ttl_seconds = max(floor, cadence_seconds * 3)
    if ttl_seconds > CLOSED_WINDOW_MAX_TTL_SECONDS:
        _fail("kline_backfill_ttl_invalid")
    return ttl_seconds


def _scan_current_symbols(client: object) -> tuple[str, ...]:
    raw_client = _require_binary_client(client)
    try:
        iterator = raw_client.scan_iter(  # type: ignore[attr-defined]
            match="v2:market:kline_current:binance:*",
            count=REDIS_SCAN_COUNT_HINT,
        )
        symbols: set[str] = set()
        seen_keys = 0
        for raw_key in iterator:
            seen_keys += 1
            if seen_keys > MAX_DISCOVERED_CURRENT_KEYS:
                _fail("kline_backfill_scan_key_limit_exceeded")
            if type(raw_key) is not bytes:
                _fail("kline_backfill_scan_key_type_invalid")
            try:
                key = raw_key.decode("ascii", errors="strict")
            except UnicodeDecodeError:
                _fail("kline_backfill_scan_key_invalid")
            parts = key.split(":")
            if len(parts) != 6 or parts[:4] != ["v2", "market", "kline_current", "binance"]:
                continue
            symbol = parts[4]
            if is_valid_runtime_symbol(symbol):
                symbols.add(symbol)
        return tuple(sorted(symbols))
    except KlineBackfillRecoveryError:
        raise
    except Exception as exc:  # noqa: BLE001 - Redis SCAN transport boundary
        raise KlineBackfillRecoveryError("kline_backfill_scan_failed") from exc


def _missing_symbols(
    client: object,
    timeframes: tuple[str, ...],
) -> dict[str, list[str]]:
    """Return symbols whose exact closed window is not core-TA ready."""

    bound_timeframes = tuple(_validated_timeframe(tf) for tf in timeframes)
    missing: dict[str, list[str]] = {}
    discovered_symbols = _scan_current_symbols(client)
    if not discovered_symbols:
        _fail("kline_backfill_no_current_symbols_discovered")
    for symbol in discovered_symbols:
        missing_timeframes = [
            timeframe
            for timeframe in bound_timeframes
            if not _assess_closed_window(client, symbol, timeframe).ready
        ]
        if missing_timeframes:
            missing[symbol] = missing_timeframes
    return missing


def _validated_target_plan(
    targets: dict[str, list[str]],
) -> dict[str, list[str]]:
    pair_count = 0
    for symbol, timeframes in targets.items():
        _validated_symbol(symbol)
        if type(timeframes) is not list or not timeframes:
            _fail("kline_backfill_target_timeframes_invalid")
        validated_timeframes = tuple(_validated_timeframe(tf) for tf in timeframes)
        if len(set(validated_timeframes)) != len(validated_timeframes):
            _fail("kline_backfill_target_timeframes_duplicate")
        pair_count += len(validated_timeframes)
        if pair_count > MAX_BACKFILL_PAIRS_PER_RUN:
            _fail("kline_backfill_target_pair_count_resource_limit")
    return targets


def _outcome(
    *,
    symbol: str,
    timeframe: str,
    rows_fetched: int,
    rows_submitted: int,
    transport: str,
    write_result: ClosedWindowRedisWriteResult | None,
    assessment_before: ClosedWindowCacheAssessment,
    assessment_after: ClosedWindowCacheAssessment,
    recovery_status: str,
) -> dict[str, Any]:
    committed = write_result is not None
    stored_rows = (
        write_result.stored_row_count if write_result is not None else assessment_after.row_count
    )
    stored_row_growth = (
        max(0, write_result.stored_row_count - write_result.existing_row_count)
        if write_result is not None
        else 0
    )
    return {
        "symbol": symbol,
        "tf": timeframe,
        "rows_fetched": rows_fetched,
        "rows_submitted": rows_submitted,
        # Compatibility fields retained, with exact meanings constrained by the
        # accompanying write acknowledgement and strict post-assessment.
        "closed_ingested": stored_row_growth,
        "closed_ingested_semantics": "NET_STORED_ROW_COUNT_GROWTH_CONSERVATIVE",
        "stored_row_growth": stored_row_growth,
        "total_in_key": stored_rows,
        "transport": transport,
        "rest_fallback_used": transport == "rest_fallback",
        "write_committed": committed,
        "write_acknowledged": committed,
        "write_attempts": write_result.attempts if write_result is not None else 0,
        "write_payload_sha256": (write_result.payload_sha256 if write_result is not None else None),
        "write_payload_byte_count": (
            write_result.payload_byte_count if write_result is not None else None
        ),
        "invalid_existing_replaced": (
            write_result.invalid_existing_replaced if write_result is not None else False
        ),
        "cache_status_before": assessment_before.status,
        "cache_status_after": assessment_after.status,
        "cache_ready_before": assessment_before.ready,
        "cache_ready_after": assessment_after.ready,
        "contiguous_suffix_count_after": assessment_after.contiguous_suffix_count,
        "tail_missing_interval_count_after": (assessment_after.tail_missing_interval_count),
        "core_ta_minimum_source_rows": CORE_TA_MINIMUM_SOURCE_ROWS,
        "recovery_status": recovery_status,
        "trainer_admission_granted": False,
        "live_execution_authorized": False,
    }


def _backfill_symbol_tf(
    client: object,
    symbol: str,
    tf: str,
    *,
    replace_invalid_existing: bool = False,
) -> dict[str, Any]:
    """Recover one window with bounded REST data and an atomic Redis merge."""

    try:
        bound_symbol = _validated_symbol(symbol)
        bound_timeframe = _validated_timeframe(tf)
        if type(replace_invalid_existing) is not bool:
            _fail("kline_backfill_replace_invalid_existing_invalid")
        _require_binary_client(client)
        assessment_before = _assess_closed_window(
            client,
            bound_symbol,
            bound_timeframe,
        )
        if assessment_before.ready:
            return _outcome(
                symbol=bound_symbol,
                timeframe=bound_timeframe,
                rows_fetched=0,
                rows_submitted=0,
                transport="websocket_cache_primary",
                write_result=None,
                assessment_before=assessment_before,
                assessment_after=assessment_before,
                recovery_status="cache_ready_no_write",
            )
        if assessment_before.status == "cache_assessment_unavailable":
            _fail("kline_backfill_cache_assessment_unavailable")
        if (
            assessment_before.status
            in {
                "cache_payload_oversized",
                "cache_schema_invalid",
                "cache_consumer_contract_invalid",
            }
            and not replace_invalid_existing
        ):
            _fail("kline_backfill_invalid_existing_repair_not_authorized")

        # The cache was proven nonready.  REST fallback is therefore forced;
        # stale, shallow, invalid, or current-candle cache values cannot short
        # circuit recovery.
        (
            rest_rows,
            request_started_at_ms,
            response_received_at_ms,
        ) = _fetch_rest_klines(
            bound_symbol,
            bound_timeframe,
            BACKFILL_LIMIT,
        )
        canonical_rows = _canonicalize_finalized_rest_rows(
            rest_rows,
            symbol=bound_symbol,
            timeframe=bound_timeframe,
            request_started_at_ms=request_started_at_ms,
            response_received_at_ms=response_received_at_ms,
        )

        latest_assessment = assessment_before
        write_result: ClosedWindowRedisWriteResult | None = None
        rows_submitted = 0
        for attempt in range(ATOMIC_OVERLAP_REASSESS_ATTEMPTS):
            if attempt:
                latest_assessment = _assess_closed_window(
                    client,
                    bound_symbol,
                    bound_timeframe,
                )
            if latest_assessment.ready:
                return _outcome(
                    symbol=bound_symbol,
                    timeframe=bound_timeframe,
                    rows_fetched=len(rest_rows),
                    rows_submitted=0,
                    transport="rest_fallback",
                    write_result=None,
                    assessment_before=assessment_before,
                    assessment_after=latest_assessment,
                    recovery_status="cache_became_ready_no_write",
                )

            additions = tuple(
                row
                for row in canonical_rows
                if cast(int, row["candle_open_time"]) not in latest_assessment.existing_open_times
            )
            rows_submitted = len(additions)
            if not additions:
                assessment_after = _assess_closed_window(
                    client,
                    bound_symbol,
                    bound_timeframe,
                )
                return _outcome(
                    symbol=bound_symbol,
                    timeframe=bound_timeframe,
                    rows_fetched=len(rest_rows),
                    rows_submitted=0,
                    transport="rest_fallback",
                    write_result=None,
                    assessment_before=assessment_before,
                    assessment_after=assessment_after,
                    recovery_status="unresolved_no_nonoverlap_finalized_rows",
                )

            try:
                write_result = atomic_merge_closed_window(
                    client,
                    redis_key=latest_assessment.redis_key,
                    new_rows=additions,
                    row_limit=CLOSED_WINDOW_MAX_ROWS,
                    minimum_rows_to_preserve=min(
                        CORE_TA_MINIMUM_SOURCE_ROWS,
                        latest_assessment.row_count + len(additions),
                    ),
                    ttl_policy="set",
                    ttl_seconds=_adaptive_closed_window_ttl_seconds(bound_timeframe),
                    replace_invalid_existing=replace_invalid_existing,
                )
                break
            except ClosedWindowRedisStoreError as exc:
                if (
                    str(exc) == "closed_window_conflicting_candle_identity"
                    and attempt + 1 < ATOMIC_OVERLAP_REASSESS_ATTEMPTS
                ):
                    continue
                raise
        if write_result is None:
            _fail("kline_backfill_atomic_overlap_retry_exhausted")

        assessment_after = _assess_closed_window(
            client,
            bound_symbol,
            bound_timeframe,
        )
        recovery_status = (
            "write_committed_cache_ready"
            if assessment_after.ready
            else "write_committed_cache_still_nonready"
        )
        return _outcome(
            symbol=bound_symbol,
            timeframe=bound_timeframe,
            rows_fetched=len(rest_rows),
            rows_submitted=rows_submitted,
            transport="rest_fallback",
            write_result=write_result,
            assessment_before=assessment_before,
            assessment_after=assessment_after,
            recovery_status=recovery_status,
        )
    except Exception as exc:  # noqa: BLE001 - public result boundary is redacted
        _raise_stable(exc)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        default=None,
        help=(
            "Comma-separated symbols, or 'auto' for the resolved runtime "
            "universe. Default: discover current-kline symbols with Redis SCAN "
            "and recover only nonready exact closed windows."
        ),
    )
    parser.add_argument(
        "--timeframes",
        default=",".join(BACKFILL_TIMEFRAMES),
        help="Comma-separated trainer timeframes (default: %(default)s).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.15,
        help="Sleep between symbol/timeframe requests (rate-limit friendly).",
    )
    parser.add_argument(
        "--replace-invalid-existing",
        action="store_true",
        help=(
            "Explicitly authorize replacement of an invalid existing closed "
            "window. Default is fail closed; valid windows are always merged."
        ),
    )
    return parser.parse_args(argv)


def _resolve_backfill_targets(
    client: object,
    args: argparse.Namespace,
) -> dict[str, list[str]]:
    raw_timeframes = str(args.timeframes or "")
    timeframe_parts = raw_timeframes.split(",", len(SUPPORTED_TRAINER_TIMEFRAMES))
    if len(timeframe_parts) > len(SUPPORTED_TRAINER_TIMEFRAMES):
        _fail("kline_backfill_timeframe_count_invalid")
    deduplicated_timeframes: list[str] = []
    seen_timeframes: set[str] = set()
    for part in timeframe_parts:
        timeframe = part.strip()
        if not timeframe or timeframe in seen_timeframes:
            continue
        seen_timeframes.add(timeframe)
        deduplicated_timeframes.append(timeframe)
    timeframes = tuple(deduplicated_timeframes) or BACKFILL_TIMEFRAMES
    unknown = [tf for tf in timeframes if tf not in SUPPORTED_TRAINER_TIMEFRAMES]
    if unknown:
        raise SystemExit(
            f"[backfill] unknown timeframes {unknown}; "
            f"allowed: {sorted(SUPPORTED_TRAINER_TIMEFRAMES)}"
        )
    raw = (args.symbols or "").strip()
    if not raw:
        return _validated_target_plan(_missing_symbols(client, timeframes))
    if raw.lower() in {"auto", "all", "universe"}:
        symbols = list(
            islice(
                resolve_symbols(),
                MAX_EXPLICIT_BACKFILL_SYMBOLS + 1,
            )
        )
        if len(symbols) > MAX_EXPLICIT_BACKFILL_SYMBOLS:
            _fail("kline_backfill_explicit_symbol_count_invalid")
    else:
        symbols = []
        seen: set[str] = set()
        symbol_parts = raw.split(",", MAX_EXPLICIT_BACKFILL_SYMBOLS)
        if len(symbol_parts) > MAX_EXPLICIT_BACKFILL_SYMBOLS:
            _fail("kline_backfill_explicit_symbol_count_invalid")
        for part in symbol_parts:
            text = part.strip().upper()
            if not text or text in seen:
                continue
            if not is_valid_runtime_symbol(text):
                _fail("kline_backfill_explicit_symbol_invalid")
            seen.add(text)
            symbols.append(text)
    if not symbols:
        _fail("kline_backfill_explicit_symbols_empty")
    if len(set(symbols)) != len(symbols) or any(
        type(symbol) is not str or not is_valid_runtime_symbol(symbol) for symbol in symbols
    ):
        _fail("kline_backfill_resolved_symbol_identity_invalid")
    return _validated_target_plan({symbol: list(timeframes) for symbol in symbols})


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    client = _redis_client()
    print(
        "[backfill] Connected to binary Redis. "
        f"transport=websocket_cache_primary "
        f"rest_fallback_allowed={binance_rest_fallback_allowed()} "
        f"required_env={REST_FALLBACK_ENV}=true"
    )
    targets = _resolve_backfill_targets(client, args)
    print(f"[backfill] {len(targets)} symbols to assess/recover:")
    for symbol, timeframes in sorted(targets.items()):
        print(f"  {symbol}: {timeframes}")

    results: list[dict[str, Any]] = []
    terminal_error_code: str | None = None
    sleep_seconds = _validated_sleep_seconds(args.sleep_seconds)
    total_symbols = len(targets)
    for index, (symbol, timeframes) in enumerate(sorted(targets.items()), 1):
        for timeframe in timeframes:
            try:
                result = _backfill_symbol_tf(
                    client,
                    symbol,
                    timeframe,
                    replace_invalid_existing=bool(args.replace_invalid_existing),
                )
                results.append(result)
                print(
                    f"[{index}/{total_symbols}] {symbol}/{timeframe}: "
                    f"{result['recovery_status']} "
                    f"write_committed={result['write_committed']} "
                    f"cache_ready_after={result['cache_ready_after']} "
                    f"rows_submitted={result['rows_submitted']} "
                    f"total={result['total_in_key']} "
                    f"transport={result['transport']}"
                )
            except Exception as exc:  # noqa: BLE001 - one pair cannot hide others
                error_code = _stable_error_code(exc)
                results.append(
                    {
                        "symbol": symbol,
                        "tf": timeframe,
                        "recovery_status": "error",
                        "write_committed": False,
                        "error_code": error_code,
                    }
                )
                print(f"[{index}/{total_symbols}] {symbol}/{timeframe}: ERROR {error_code}")
                if error_code in TERMINAL_REST_RECOVERY_ERROR_CODES:
                    terminal_error_code = error_code
                    break
            time.sleep(sleep_seconds)
        if terminal_error_code is not None:
            break

    committed = sum(result.get("write_committed") is True for result in results)
    ready_no_write = sum(
        result.get("write_committed") is False and result.get("cache_ready_after") is True
        for result in results
    )
    unresolved = sum(
        result.get("recovery_status") != "error" and result.get("cache_ready_after") is False
        for result in results
    )
    errors = sum(result.get("recovery_status") == "error" for result in results)
    print(
        "\n[backfill] Done. "
        f"writes_committed={committed}, ready_no_write={ready_no_write}, "
        f"unresolved={unresolved}, errors={errors}."
    )
    return 1 if errors or unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
