"""V2 native ingestors live loop (paper/shadow, V2-namespace only).

Public market data only. Writes to v2:* Redis namespace ONLY.
No exchange mutation. No legacy Redis writes.

Default behavior:
- reads Binance WebSocket-backed Redis/cache data first for the configured
  symbol set, writes v2:market:prices:* / v2:market:funding:* /
  v2:market:open_interest:*
- public REST is fallback-only and requires BINANCE_REST_FALLBACK_ALLOWED=true
- when WebSocket/cache data and explicit fallback are unavailable, writes the
  heartbeat with a BLOCKED_BY_NETWORK_OR_API status and no price data
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import partial
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import urlencode

from v2.backend.app.services.binance_unified_websocket_transport import (
    REST_FALLBACK_ENV,
    binance_rest_fallback_allowed,
    report_binance_rest_response,
    require_binance_rest_fallback,
)
from v2.backend.app.services.market_data.current_price_resolver import resolve_current_price
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
    closed_candle_key,
    current_candle_key,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (
    is_valid_runtime_symbol,
    resolve_symbols,
)

V2_REDIS_PREFIX = "v2:"
DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_native_ingestors/live/latest/v2_native_ingestors_live_status.json"
)
BINANCE_PUBLIC = "https://api.binance.com"
BINANCE_FAPI = "https://fapi.binance.com"
HTTP_TIMEOUT_S = 2.0
MAX_FETCH_WORKERS = 12
DEFAULT_KLINE_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")

# Source-event freshness bound for the premium-index cache. This is a market
# publication safety contract, not a strategy/admission threshold. The loop
# reads keys it also writes, so an event-time check is required to prevent a
# dead row from acquiring a fresh Redis TTL forever.
FUNDING_CACHE_MAX_AGE_SECONDS = 120.0


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number rejected: {value}")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_iso_precise() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _http_get_json(url: str, *, fallback_reason: str) -> Any:
    if "binance.com" in url:
        require_binance_rest_fallback(
            endpoint=urllib.parse.urlparse(url).path or url,
            fallback_reason=fallback_reason,
            role="native_ingestor_public_market_data_recovery",
        )
    req = urllib.request.Request(url, headers={"User-Agent": "v2-native-ingestor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            return json.loads(
                resp.read().decode("utf-8"),
                parse_constant=_reject_nonfinite_json,
            )
    except urllib.error.HTTPError as exc:
        # Ban protection: 429/418 arms the shared cross-process cooldown so
        # ALL fallback traffic on this host stops before Binance escalates.
        if "binance.com" in url:
            try:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
            except Exception:
                retry_after = None
            report_binance_rest_response(
                status_code=int(exc.code),
                retry_after_seconds=float(retry_after) if retry_after else None,
            )
        raise


def _rest_fallback_disabled() -> bool:
    return not binance_rest_fallback_allowed()


def _read_json(r: Any, key: str) -> Any:
    if r is None:
        return None
    try:
        raw = r.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(
            raw if isinstance(raw, str) else raw.decode("utf-8", errors="ignore"),
            parse_constant=_reject_nonfinite_json,
        )
    except (TypeError, ValueError):
        return None


def _cache_payload_source(payload: dict | None, *, default: str) -> str:
    if not isinstance(payload, dict):
        return default
    provenance = " ".join(
        str(payload.get(field) or "") for field in ("source", "transport")
    ).lower()
    if "rest" in provenance:
        return "binance_public_cache_rest_fallback"
    return "binance_public_websocket_cache_primary"


def _cache_transport(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return "websocket_cache_primary"
    provenance = " ".join(
        str(payload.get(field) or "") for field in ("source", "transport")
    ).lower()
    return "rest_fallback_cache" if "rest" in provenance else "websocket_cache_primary"


def _combined_cache_transport(*payloads: dict | None) -> str:
    return (
        "rest_fallback_cache"
        if any(_cache_transport(payload) == "rest_fallback_cache" for payload in payloads)
        else "websocket_cache_primary"
    )


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value not in (None, "")), None)


def _is_websocket_cache_payload(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    provenance = " ".join(
        str(payload.get(field) or "") for field in ("source", "transport")
    ).lower()
    if "rest" in provenance:
        return False
    return any(
        token in provenance
        for token in ("wss", "websocket", "ws_cache", "stream", "cache_primary")
    )


def _connect_redis():
    """Lazy redis import. Returns None when redis is unavailable."""
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _safe_write(r, key: str, value: str, ex: int | None = None) -> bool:
    if r is None:
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        raise ValueError(f"refused: non-V2 namespace key {key!r}")
    try:
        if ex is not None:
            r.set(key, value, ex=int(ex))
        else:
            r.set(key, value)
        return True
    except Exception:
        return False


def _write_symbol_bundle(r: Any, sym: str, bundle: dict, keys_written: list[str]) -> None:
    if r is None:
        return
    ticker = bundle.get("ticker")
    funding = bundle.get("funding")
    oi = bundle.get("open_interest")
    long_short = bundle.get("long_short")
    klines_by_timeframe = bundle.get("klines_by_timeframe") or {}
    orderbook = bundle.get("orderbook")
    oi_hist = bundle.get("open_interest_hist")
    fetched_utc = _utc_iso()
    payload: dict[str, Any] = {
        "symbol": sym,
        "source": bundle.get("source") or "binance_public_websocket_cache_primary",
        "transport": bundle.get("transport") or "websocket_cache_primary",
        "rest_fallback_used": bool(bundle.get("rest_fallback_used")),
        "ticker_24hr": ticker,
        "funding": funding,
        "open_interest": oi,
        "long_short": long_short,
        "fetched_utc": fetched_utc,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    writes: list[tuple[str, Any]] = [
        (f"{V2_REDIS_PREFIX}market:prices:{sym}", payload),
    ]
    if funding is not None:
        writes.append((f"{V2_REDIS_PREFIX}market:funding:{sym}", funding))
    if oi is not None:
        writes.append((f"{V2_REDIS_PREFIX}market:open_interest:{sym}", oi))
    if long_short is not None:
        writes.append((f"{V2_REDIS_PREFIX}market:long_short:{sym}", long_short))
    for timeframe, rows in sorted(klines_by_timeframe.items()):
        if rows is not None:
            writes.append((f"{V2_REDIS_PREFIX}market:ohlcv:binance:{sym}:{timeframe}", rows))
    if orderbook is not None:
        orderbook = {
            **orderbook,
            "symbol": sym,
            "source": orderbook.get("source") or _cache_payload_source(
                orderbook,
                default="binance_public_websocket_orderbook_cache_primary",
            ),
            "exchange": "binance",
            "transaction_time": orderbook.get("transaction_time") or fetched_utc,
            "received_at": orderbook.get("received_at") or fetched_utc,
            "available_at": orderbook.get("available_at") or fetched_utc,
            "fetched_utc": orderbook.get("fetched_utc") or fetched_utc,
            "event_time": orderbook.get("event_time"),
            "event_time_missing_reason": (
                orderbook.get("event_time_missing_reason")
                or (
                    "BINANCE_ORDERBOOK_CACHE_EVENT_TIME_MISSING"
                    if not str(orderbook.get("source") or "").lower().startswith("binance_public_rest")
                    else "BINANCE_REST_DEPTH_SNAPSHOT_HAS_NO_EXCHANGE_EVENT_TIME"
                )
            ),
        }
        writes.extend(
            [
                (f"{V2_REDIS_PREFIX}market:orderbook:{sym}", orderbook),
                (f"{V2_REDIS_PREFIX}market:orderbook:binance:{sym}", orderbook),
            ]
        )
    if oi_hist is not None:
        writes.append((f"{V2_REDIS_PREFIX}market:open_interest_hist:{sym}:5m", oi_hist))

    for key, value in writes:
        if _safe_write(r, key, json.dumps(value), ex=600):
            keys_written.append(key)


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _observed_epoch_ms() -> int:
    """Return the local observation clock used only as a causal cutoff."""

    return int(time.time() * 1_000)


def _strict_positive_epoch_ms(value: Any) -> int | None:
    """Parse exact integral milliseconds without binary-float rounding."""

    if value in (None, "") or isinstance(value, bool | float):
        return None
    if type(value) is int:
        return value if value > 0 else None
    if not isinstance(value, str | Decimal):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed <= 0 or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


# Fixed values below are evidence-integrity/resource bounds, never market
# thresholds. Freshness is computed from exact producer event intervals.
SOURCE_CADENCE_MIN_INTERVALS = 3
SOURCE_CADENCE_MAX_CLOCKS = 32
SOURCE_CACHE_MAX_BYTES = 256 * 1024
SOURCE_CACHE_MAX_JSON_DEPTH = 64
SOURCE_CACHE_MAX_JSON_NODES = 65_536
SOURCE_CACHE_MAX_JSON_CONTAINER_ITEMS = 16_384
SOURCE_CACHE_MAX_JSON_STRING_BYTES = 64 * 1024
# Numerical normalization tolerance only; never a market/freshness threshold.
SOURCE_CADENCE_INTERVAL_ABS_TOLERANCE_SECONDS = 0.001
OPTIONAL_DERIVATIVE_REST_ENV = "BINANCE_OPTIONAL_DERIVATIVE_REST_FALLBACK_ALLOWED"
HEARTBEAT_SCHEMA_VERSION = "v2_native_ingestors_live_v2"
HEARTBEAT_PREVIOUS_SCHEMA_VERSION = "v2_native_ingestors_live_v1"

OPEN_INTEREST_HISTORY_SOURCE_TRANSPORTS = {
    "binance_open_interest_history_rest_fallback": "rest_fallback",
    "coinank_open_interest_kline_backup": "provider_backup_cache",
}
LONG_SHORT_SOURCE_TRANSPORTS = {
    "binance_global_long_short_account_ratio_rest_fallback": "rest_fallback",
}


def _optional_derivative_rest_allowed() -> bool:
    """Explicit priority gate; false preserves budget for canonical OHLCV repair."""

    return os.environ.get(OPTIONAL_DERIVATIVE_REST_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _heartbeat_schema_compatibility() -> dict[str, Any]:
    return {
        "previous_version": HEARTBEAT_PREVIOUS_SCHEMA_VERSION,
        "legacy_field_names_preserved": True,
        "read_compatibility": "FIELD_COMPATIBLE_SEMANTICS_FAIL_CLOSED",
        "changed_semantic_fields": [
            "classification",
            "live_data_enabled",
            "live_decision_input_enabled",
        ],
    }


def _strict_epoch_seconds(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    number = _safe_float(value)
    if number is not None:
        if number <= 0.0:
            return None
        divisor = 1_000_000_000.0 if number > 10**17 else (
            1_000_000.0 if number > 10**14 else (1_000.0 if number > 10**11 else 1.0)
        )
        return number / divisor
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.timestamp()


def _period_seconds(period: str) -> float | None:
    text = str(period or "").strip().lower()
    units = {"s": 1.0, "m": 60.0, "h": 3_600.0, "d": 86_400.0, "w": 604_800.0}
    amount = _safe_float(text[:-1]) if len(text) > 1 else None
    return amount * units[text[-1]] if amount and text[-1] in units else None


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in pairs:
        if key in decoded:
            raise ValueError("SOURCE_CACHE_JSON_DUPLICATE_KEY")
        decoded[key] = value
    return decoded


def _source_cache_json_shape_valid(value: Any) -> bool:
    stack: list[tuple[Any, int]] = [(value, 0)]
    node_count = 0
    while stack:
        current, depth = stack.pop()
        node_count += 1
        if depth > SOURCE_CACHE_MAX_JSON_DEPTH or node_count > SOURCE_CACHE_MAX_JSON_NODES:
            return False
        if isinstance(current, dict):
            if len(current) > SOURCE_CACHE_MAX_JSON_CONTAINER_ITEMS:
                return False
            for key, child in current.items():
                if type(key) is not str:
                    return False
                try:
                    if (
                        len(key.encode("utf-8", errors="strict"))
                        > SOURCE_CACHE_MAX_JSON_STRING_BYTES
                    ):
                        return False
                except UnicodeError:
                    return False
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            if len(current) > SOURCE_CACHE_MAX_JSON_CONTAINER_ITEMS:
                return False
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, str):
            try:
                if (
                    len(current.encode("utf-8", errors="strict"))
                    > SOURCE_CACHE_MAX_JSON_STRING_BYTES
                ):
                    return False
            except UnicodeError:
                return False
        elif type(current) in (int, float):
            try:
                if not math.isfinite(float(current)):
                    return False
            except (OverflowError, ValueError):
                return False
        elif current is not None and type(current) is not bool:
            return False
    return True


def _read_bounded_source_cache_json(
    redis_client: Any,
    key: str,
) -> tuple[Any, str | None]:
    """Read source cache JSON only after enforcing a raw-byte resource cap."""

    if redis_client is None:
        return None, "SOURCE_CACHE_MISSING"
    try:
        raw = redis_client.get(key)
    except Exception:
        return None, "SOURCE_CACHE_READ_FAILED"
    if not raw:
        return None, "SOURCE_CACHE_MISSING"
    if isinstance(raw, bytes):
        if len(raw) > SOURCE_CACHE_MAX_BYTES:
            return None, "SOURCE_CACHE_PAYLOAD_BYTES_EXCEEDED"
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None, "SOURCE_CACHE_JSON_INVALID"
    elif isinstance(raw, str):
        # Character count is a no-allocation lower bound on UTF-8 byte size.
        if len(raw) > SOURCE_CACHE_MAX_BYTES:
            return None, "SOURCE_CACHE_PAYLOAD_BYTES_EXCEEDED"
        try:
            encoded = raw.encode("utf-8")
        except UnicodeEncodeError:
            return None, "SOURCE_CACHE_JSON_INVALID"
        if len(encoded) > SOURCE_CACHE_MAX_BYTES:
            return None, "SOURCE_CACHE_PAYLOAD_BYTES_EXCEEDED"
        text = raw
    else:
        return None, "SOURCE_CACHE_PAYLOAD_TYPE_INVALID"
    try:
        decoded = json.loads(
            text,
            parse_constant=_reject_nonfinite_json,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, TypeError, ValueError, RecursionError):
        return None, "SOURCE_CACHE_JSON_INVALID"
    return (
        (decoded, None)
        if _source_cache_json_shape_valid(decoded)
        else (None, "SOURCE_CACHE_JSON_INVALID")
    )


def _source_clock_state(
    payload: dict[str, Any],
    *,
    now: float,
) -> tuple[float | None, str]:
    raw_event = _first_present(payload.get("event_time"), payload.get("timestamp"))
    event = _strict_epoch_seconds(raw_event)
    if raw_event in (None, ""):
        return None, "SOURCE_EVENT_TIME_MISSING"
    if event is None:
        return None, "SOURCE_EVENT_TIME_INVALID"
    if event > now:
        return event, "SOURCE_EVENT_TIME_IN_FUTURE"

    parsed: dict[str, float | None] = {}
    for field in ("ingested_at", "available_at", "generated_at"):
        raw = payload.get(field)
        parsed_clock = None if raw in (None, "") else _strict_epoch_seconds(raw)
        parsed[field] = parsed_clock
        if raw not in (None, "") and parsed_clock is None:
            return event, f"SOURCE_{field.upper()}_INVALID"
        if parsed_clock is not None and parsed_clock > now:
            return event, f"SOURCE_{field.upper()}_IN_FUTURE"

    ingested = parsed.get("ingested_at")
    available = parsed.get("available_at")
    generated = parsed.get("generated_at")
    if ingested is None:
        return event, "SOURCE_INGESTED_AT_MISSING"
    if available is None:
        return event, "SOURCE_AVAILABLE_AT_MISSING"
    if ingested < event:
        return event, "SOURCE_EVENT_AFTER_INGESTION"
    if available < ingested:
        return event, "SOURCE_AVAILABLE_AT_ORDER_INVALID"
    if generated is not None and not event <= generated <= ingested:
        return event, "SOURCE_GENERATED_AT_ORDER_INVALID"
    return event, "SOURCE_CLOCKS_VALID"


def _source_identity_reason(
    payload: dict[str, Any],
    *,
    expected_symbol: str,
    expected_period: str,
    source_transports: dict[str, str],
) -> str | None:
    raw_symbol = payload.get("symbol")
    if raw_symbol in (None, ""):
        return "SOURCE_SYMBOL_MISSING"
    if type(raw_symbol) is not str or raw_symbol != expected_symbol:
        return "SOURCE_SYMBOL_MISMATCH"
    raw_period = payload.get("period")
    if raw_period in (None, ""):
        return "SOURCE_PERIOD_MISSING"
    if type(raw_period) is not str or raw_period != expected_period:
        return "SOURCE_PERIOD_MISMATCH"
    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        return "SOURCE_IDENTITY_MISSING"
    if source != source.strip():
        return "SOURCE_IDENTITY_UNEXPECTED"
    expected_transport = source_transports.get(source)
    if expected_transport is None:
        return "SOURCE_IDENTITY_UNEXPECTED"
    transport = payload.get("transport")
    if transport != expected_transport:
        return "SOURCE_TRANSPORT_IDENTITY_MISMATCH"
    return None


def _strict_decimal(value: Any) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_quantum(value: Decimal) -> Decimal:
    """Return the producer-reported last-place resolution."""

    exponent = value.as_tuple().exponent
    return Decimal(1).scaleb(exponent if isinstance(exponent, int) else 0)


def _long_short_feature_contract(
    payload: dict[str, Any],
) -> tuple[dict[str, float] | None, dict[str, dict[str, Any]], str | None]:
    """Validate the complete source triplet without inventing neutral values."""

    raw_fields = {
        "long_short_ratio": _first_present(
            payload.get("longShortRatio"), payload.get("long_short_ratio")
        ),
        "long_account_ratio": _first_present(
            payload.get("longAccount"), payload.get("long_account_ratio")
        ),
        "short_account_ratio": _first_present(
            payload.get("shortAccount"), payload.get("short_account_ratio")
        ),
    }
    decimals: dict[str, Decimal] = {}
    availability: dict[str, dict[str, Any]] = {}
    first_reason: str | None = None
    reason_prefixes = {
        "long_short_ratio": "LONG_SHORT_RATIO",
        "long_account_ratio": "LONG_ACCOUNT_RATIO",
        "short_account_ratio": "SHORT_ACCOUNT_RATIO",
    }
    for field, raw in raw_fields.items():
        reason_prefix = reason_prefixes[field]
        value = _strict_decimal(raw)
        if raw in (None, ""):
            field_reason = f"{reason_prefix}_MISSING"
        elif value is None:
            field_reason = f"{reason_prefix}_INVALID"
        elif field == "long_short_ratio" and value <= 0:
            field_reason = f"{reason_prefix}_OUT_OF_DOMAIN"
        elif field != "long_short_ratio" and not Decimal(0) < value < Decimal(1):
            field_reason = f"{reason_prefix}_OUT_OF_DOMAIN"
        else:
            decimals[field] = value
            availability[field] = {
                "status": "AVAILABLE",
                "reason": "SOURCE_FIELD_VALUE_VALID",
                "readiness_eligible": False,
            }
            continue
        availability[field] = {
            "status": "UNAVAILABLE",
            "reason": field_reason,
            "readiness_eligible": False,
        }
        if first_reason is None:
            first_reason = field_reason

    if first_reason is not None:
        return None, availability, first_reason

    ratio = decimals["long_short_ratio"]
    long_account = decimals["long_account_ratio"]
    short_account = decimals["short_account_ratio"]
    long_half_step = _decimal_quantum(long_account) / 2
    short_half_step = _decimal_quantum(short_account) / 2
    account_sum_tolerance = max(long_half_step, short_half_step)
    if abs((long_account + short_account) - Decimal(1)) > account_sum_tolerance:
        reason = "LONG_SHORT_ACCOUNT_RATIOS_SUM_INCONSISTENT"
        for field in ("long_account_ratio", "short_account_ratio"):
            availability[field] = {
                "status": "UNAVAILABLE",
                "reason": reason,
                "readiness_eligible": False,
            }
        return None, availability, reason

    ratio_half_step = _decimal_quantum(ratio) / 2
    ratio_low = max(Decimal(0), ratio - ratio_half_step)
    ratio_high = ratio + ratio_half_step
    long_low = max(Decimal(0), long_account - long_half_step)
    long_high = min(Decimal(1), long_account + long_half_step)
    short_low = max(Decimal(0), short_account - short_half_step)
    short_high = min(Decimal(1), short_account + short_half_step)
    implied_low = long_low / short_high
    implied_high = Decimal("Infinity") if short_low == 0 else long_high / short_low
    if ratio_high < implied_low or ratio_low > implied_high:
        reason = "LONG_SHORT_RATIO_INCONSISTENT_WITH_ACCOUNTS"
        availability["long_short_ratio"] = {
            "status": "UNAVAILABLE",
            "reason": reason,
            "readiness_eligible": False,
        }
        return None, availability, reason

    return (
        {
            "long_short_ratio": float(ratio),
            "long_account_ratio": float(long_account),
            "short_account_ratio": float(short_account),
        },
        availability,
        None,
    )


def _source_freshness(
    payload: dict[str, Any], event_clocks: list[Any], *, period: str
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    """Validate immutable clocks, then derive age from observed cadence."""

    now = time.time()
    event, reason = _source_clock_state(payload, now=now)
    clocks: list[float] = []
    cadence_reason = "AWAITING_OBSERVED_PRODUCER_CADENCE"
    if len(event_clocks) > SOURCE_CADENCE_MAX_CLOCKS:
        cadence_reason = "SOURCE_CADENCE_EVIDENCE_TOO_LARGE"
    elif len(event_clocks) >= SOURCE_CADENCE_MIN_INTERVALS + 1:
        cadence_reason = "SOURCE_CADENCE_CLOCKS_VALID"
        previous: float | None = None
        for raw_clock in event_clocks:
            clock = _strict_epoch_seconds(raw_clock)
            if clock is None:
                cadence_reason = "SOURCE_CADENCE_CLOCK_INVALID"
                break
            if clock > now:
                cadence_reason = "SOURCE_CADENCE_CLOCK_IN_FUTURE"
                break
            if previous is not None and clock == previous:
                cadence_reason = "SOURCE_CADENCE_CLOCK_DUPLICATE"
                break
            if previous is not None and clock < previous:
                cadence_reason = "SOURCE_CADENCE_CLOCK_ORDER_INVALID"
                break
            clocks.append(clock)
            previous = clock
        if (
            cadence_reason == "SOURCE_CADENCE_CLOCKS_VALID"
            and (event is None or clocks[-1] != event)
        ):
            cadence_reason = "SOURCE_EVENT_NOT_BOUND_TO_NEWEST_CADENCE_CLOCK"

    intervals = [b - a for a, b in zip(clocks, clocks[1:], strict=False)]
    recent = intervals[-SOURCE_CADENCE_MIN_INTERVALS :]
    declared = _period_seconds(period)
    cadence_proven = False
    if cadence_reason == "SOURCE_CADENCE_CLOCKS_VALID":
        if declared is None:
            cadence_reason = "SOURCE_PERIOD_INVALID"
        elif any(
            not math.isclose(
                value,
                declared,
                rel_tol=0.0,
                abs_tol=SOURCE_CADENCE_INTERVAL_ABS_TOLERANCE_SECONDS,
            )
            for value in recent
        ):
            cadence_reason = "SOURCE_CADENCE_GAP_OR_PERIOD_MISMATCH"
        else:
            cadence_proven = True
            cadence_reason = "RECENT_DISTINCT_PRODUCER_INTERVAL_MEDIAN"
    if reason == "SOURCE_CLOCKS_VALID" and not cadence_proven:
        reason = cadence_reason
    budget = max(recent) if cadence_proven else None
    age = now - event if event is not None else None
    fresh = False
    if reason == "SOURCE_CLOCKS_VALID" and age is not None and budget is not None:
        fresh = 0.0 <= age <= budget
    if reason == "SOURCE_CLOCKS_VALID" and not fresh:
        reason = "SOURCE_EVENT_STALE_BY_OBSERVED_CADENCE"
    cadence = {
        "proven": cadence_proven,
        "reason": cadence_reason,
        "sample_count": len(recent),
        "observed_cadence_seconds": median(recent) if cadence_proven else None,
        "adaptive_max_age_seconds": budget,
        "event_times_epoch_seconds": clocks,
        "cadence_basis": "EXACT_SOURCE_EVENT_INTERVALS_MATCH_DECLARED_PERIOD",
        "cadence_basis_transport": payload.get("transport"),
        "cadence_basis_transport_authenticated": False,
        "source_receipt_authority": False,
    }
    freshness = {
        "status": "FRESH" if fresh else "UNAVAILABLE",
        "reason": "FRESH_BY_OBSERVED_PRODUCER_CADENCE" if fresh else reason,
        "event_age_seconds": age,
        "adaptive_max_age_seconds": budget,
        "cadence_sample_count": len(recent),
        "cadence_proven": cadence_proven,
        "readiness_eligible": fresh,
        "republish_time_authoritative": False,
        "redis_ttl_authoritative": False,
        "source_receipt_authority": False,
        "trainer_authority": False,
    }
    return fresh, freshness, cadence


def _set_availability(diagnostics: dict[str, Any] | None, freshness: dict[str, Any]) -> None:
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics.update(
            status="AVAILABLE" if freshness.get("readiness_eligible") else "UNAVAILABLE",
            reason=freshness.get("reason"),
            source_freshness=freshness,
            source_receipt_authority=False,
            trainer_authority=False,
        )


def _readiness_eligible(payload: Any) -> bool:
    row = payload[-1] if isinstance(payload, list) and payload else payload
    return bool(
        isinstance(row, dict)
        and isinstance(row.get("source_freshness"), dict)
        and row["source_freshness"].get("readiness_eligible") is True
    )


def _ticker_cache_age_seconds(ticker: dict) -> float | None:
    close_time = ticker.get("closeTime")
    close_time_ms = _safe_float(close_time)
    if close_time_ms is not None and close_time_ms > 0:
        return max(0.0, time.time() - close_time_ms / 1000.0)
    # Resolver-written payloads carry ISO-8601 closeTime strings.
    # NOTE: ``from datetime import datetime`` (module shadowed) — the class,
    # not the module, is in scope here.
    if isinstance(close_time, str) and close_time:
        try:
            parsed = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, time.time() - parsed.timestamp())
    return None


# A cached ticker older than this must NOT be re-emitted: the cache read below
# targets this ingestor's OWN output key, so without a freshness gate a stale
# ticker echoes forever and the resolver/REST fallbacks are unreachable
# (2026-07-16 incident: v2:market:prices:* frozen for 2h, all paper marks and
# unrealized PnL frozen with it).
TICKER_CACHE_MAX_AGE_SECONDS = 120.0


def _fetch_ticker_24hr(symbol: str, *, redis_client: Any = None) -> dict | None:
    cached = _read_json(redis_client, f"{V2_REDIS_PREFIX}market:prices:{symbol}")
    if isinstance(cached, dict):
        ticker = cached.get("ticker_24hr") if isinstance(cached.get("ticker_24hr"), dict) else cached
        cache_age = _ticker_cache_age_seconds(ticker) if isinstance(ticker, dict) else None
        cache_fresh = cache_age is not None and cache_age <= TICKER_CACHE_MAX_AGE_SECONDS
        last_price = _safe_float(
            ticker.get("lastPrice")
            if isinstance(ticker, dict)
            else None
        )
        if last_price is None:
            try:
                resolved = resolve_current_price(redis_client, symbol)
            except Exception:
                resolved = {}
            last_price = _safe_float(resolved.get("price")) if isinstance(resolved, dict) else None
        # A price-only payload (the current-price-resolver fallback used
        # during the 2026-07-16 WSS outage) carries no 24h stats; quoteVolume
        # is the marker. Echoing it as a "24hr ticker" starves every 24h
        # feature downstream (last_liq_bps_24h = notional / quoteVolume).
        has_24h_stats = (
            isinstance(ticker, dict) and _safe_float(ticker.get("quoteVolume")) is not None
        )
        if isinstance(ticker, dict) and last_price is not None and cache_fresh and has_24h_stats:
            return {
                **ticker,
                "symbol": symbol,
                "lastPrice": ticker.get("lastPrice") or last_price,
                "source": _cache_payload_source(cached, default="binance_public_websocket_cache_primary"),
                "transport": _combined_cache_transport(cached, ticker),
            }
    # Cache stale, undated, or missing the 24h stats: the public REST 24hr
    # ticker is the only remaining source of quoteVolume/high/low once the
    # WSS-backed cache is gone, so prefer it (when explicitly allowed) before
    # degrading to the price-only resolver payload. The freshness gate above
    # bounds this to at most one REST call per symbol per cache window.
    if not _rest_fallback_disabled():
        try:
            data = _http_get_json(
                f"{BINANCE_FAPI}/fapi/v1/ticker/24hr?symbol={symbol}",
                fallback_reason="ticker_websocket_cache_missing_stale_or_price_only",
            )
        # RuntimeError covers REST_FALLBACK_BUDGET_EXHAUSTED / ban-protection
        # cooldowns from require_binance_rest_fallback: treat as "fallback
        # unavailable this cycle" and degrade to the resolver price below.
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError, RuntimeError):
            data = None
        if isinstance(data, dict):
            data["source"] = "binance_public_rest_ticker_fallback"
            data["transport"] = "rest_fallback"
            return data
    try:
        resolved = resolve_current_price(redis_client, symbol) if redis_client is not None else {}
    except Exception:
        resolved = {}
    if isinstance(resolved, dict) and _safe_float(resolved.get("price")) is not None:
        price = _safe_float(resolved.get("price"))
        return {
            "symbol": symbol,
            "lastPrice": price,
            "bidPrice": resolved.get("bid"),
            "askPrice": resolved.get("ask"),
            "closeTime": resolved.get("available_at"),
            "source": resolved.get("source") or "binance_public_websocket_cache_primary",
            "transport": _cache_transport(resolved),
        }
    return None


def _funding_cache_event_epoch_seconds(payload: dict) -> float | None:
    event_value = _first_present(
        payload.get("event_time"),
        payload.get("time"),
        payload.get("timestamp"),
        payload.get("binance_time_ms"),
        payload.get("E"),
    )
    event_number = _safe_float(event_value)
    if event_number is not None and event_number > 0:
        epoch_seconds = event_number / 1000.0 if event_number > 10_000_000_000 else event_number
    elif isinstance(event_value, str) and event_value:
        try:
            parsed = datetime.fromisoformat(event_value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        epoch_seconds = parsed.timestamp()
    else:
        return None
    return epoch_seconds if epoch_seconds <= time.time() else None


def _funding_cache_age_seconds(payload: dict) -> float | None:
    event_epoch_seconds = _funding_cache_event_epoch_seconds(payload)
    return (
        time.time() - event_epoch_seconds
        if event_epoch_seconds is not None
        else None
    )


def _fresh_funding_cache_candidates(symbol: str, *, redis_client: Any) -> list[tuple[str, dict]]:
    candidates: list[tuple[str, dict]] = []
    for key in (
        f"{V2_REDIS_PREFIX}market:mark_price:{symbol}",
        f"{V2_REDIS_PREFIX}market:funding:{symbol}",
        f"{V2_REDIS_PREFIX}market:prices:{symbol}",
    ):
        payload = _read_json(redis_client, key)
        if not isinstance(payload, dict):
            continue
        if key.endswith(f"prices:{symbol}") and isinstance(payload.get("funding"), dict):
            candidates.append((f"{key}.funding", payload["funding"]))
        candidates.append((key, payload))
    return candidates


def _fetch_funding(symbol: str, *, redis_client: Any = None) -> dict | None:
    valid_candidates: list[
        tuple[float, bool, str, dict, float | None, float | None, float | None]
    ] = []
    for source_key, cached in _fresh_funding_cache_candidates(
        symbol,
        redis_client=redis_client,
    ):
        event_epoch_seconds = _funding_cache_event_epoch_seconds(cached)
        if event_epoch_seconds is None:
            continue
        if time.time() - event_epoch_seconds > FUNDING_CACHE_MAX_AGE_SECONDS:
            continue
        mark_price = _safe_float(_first_present(cached.get("markPrice"), cached.get("mark_price")))
        index_price = _safe_float(_first_present(cached.get("indexPrice"), cached.get("index_price")))
        funding_rate = _safe_float(
            _first_present(
                cached.get("lastFundingRate"),
                cached.get("last_funding_rate"),
                cached.get("funding_rate"),
            )
        )
        if not (
            (mark_price is not None and mark_price > 0.0 and index_price is not None and index_price > 0.0)
            or funding_rate is not None
        ):
            continue
        valid_candidates.append(
            (
                event_epoch_seconds,
                _cache_transport(cached) == "websocket_cache_primary",
                source_key,
                cached,
                mark_price,
                index_price,
                funding_rate,
            )
        )
    if valid_candidates:
        (
            _,
            _,
            source_key,
            cached,
            mark_price,
            index_price,
            funding_rate,
        ) = max(valid_candidates, key=lambda candidate: (candidate[0], candidate[1]))
        observed_at = _utc_iso_precise()
        event_time = _first_present(
            cached.get("event_time"),
            cached.get("time"),
            cached.get("timestamp"),
            cached.get("binance_time_ms"),
            cached.get("E"),
        )
        source_update_interval = _safe_float(
            cached.get("expected_update_interval_seconds")
        )
        if source_update_interval is not None and source_update_interval <= 0.0:
            source_update_interval = None
        return {
            **cached,
            "symbol": cached.get("symbol") or symbol,
            "markPrice": mark_price,
            "indexPrice": index_price,
            "lastFundingRate": funding_rate,
            "funding_rate": funding_rate,
            "event_time": event_time,
            "generated_at": cached.get("generated_at"),
            "available_at": cached.get("available_at") or cached.get("received_at"),
            "consumer_observed_at": observed_at,
            "republished_at": observed_at,
            "expected_update_interval_seconds": source_update_interval,
            "source_key": source_key,
            "source": cached.get("source")
            or _cache_payload_source(
                cached,
                default="binance_public_websocket_cache_primary",
            ),
            "transport": _cache_transport(cached),
        }
    if _rest_fallback_disabled():
        return None
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/fapi/v1/premiumIndex?symbol={symbol}",
            fallback_reason="funding_websocket_cache_missing",
        )
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    observed_at = _utc_iso_precise()
    data["source"] = "binance_public_rest_premium_index_fallback"
    data["transport"] = "rest_fallback"
    data["event_time"] = _first_present(data.get("time"), data.get("E"))
    data["generated_at"] = observed_at
    data["available_at"] = observed_at
    data["consumer_observed_at"] = observed_at
    data["republished_at"] = observed_at
    data["expected_update_interval_seconds"] = 60.0
    return data


# Same cache-echo bug class as the ticker/orderbook fixes: this fetch reads
# its OWN output key (v2:market:open_interest:*), so an undated or stale
# payload would otherwise echo forever between this loop and the public
# metadata ingestor while REST stays unreachable (2026-07-16 incident: BTC OI
# frozen with NO timestamp anywhere in the payload for >5h after the 18:03Z
# WSS transport death).
OPEN_INTEREST_CACHE_MAX_AGE_SECONDS = 120.0
# openInterestHist freshness is intentionally not a fixed number of seconds.
# The newest event is admitted only through the exact period plus observed
# producer-cadence proof assembled by ``_source_freshness``.

# Alternative-provider backup tier (operator directive 2026-07-16): CoinAnk
# publishes Binance openInterest klines in CONTRACTS — the same unit as
# /fapi/v1/openInterest and sumOpenInterest, verified against live values —
# under latest:coinank:open_interest:{symbol}:{tf} (read-only legacy keys).
# Tier order per OI fetch:
#   1. own v2 cache (fresh, <=120s)
#   2. CoinAnk rows when as fresh as the cache bar (saves REST budget)
#   3. Binance REST (budgeted by ban protection)
#   4. CoinAnk rescue within a bounded staleness window when REST is
#      unavailable (budget exhausted / cooldown / disabled) — honestly dated
#      with the provider's own row time, provenance labeled, never re-stamped.
# CoinGlass OI is deliberately NOT mapped: its open-interest USD figure does
# not reconcile with Binance contract*price values (unit/scope unverifiable).
COINANK_OI_KEY_TEMPLATES = (
    "latest:coinank:open_interest:{symbol}:5m",
    "latest:coinank:open_interest:{symbol}:1h",
)
COINANK_OI_BUCKET_MS = {"5m": 300_000, "1h": 3_600_000}
PROVIDER_OI_RESCUE_MAX_AGE_SECONDS = 3600.0


def _coinank_oi_hist_rows(symbol: str, *, redis_client: Any = None) -> list[dict] | None:
    """CoinAnk openInterest klines mapped to the Binance hist row schema.

    Returns ascending rows of ``{symbol, sumOpenInterest, timestamp, source}``
    (contracts + ms bucket-close time) or None. Rows without a verifiable
    numeric ``begin``/``close`` are skipped (some symbols use a different
    row schema), so unverifiable data can never masquerade as real OI.
    """
    for template in COINANK_OI_KEY_TEMPLATES:
        tf = template.rsplit(":", 1)[-1].replace("{symbol}", "")
        payload, _ = _read_bounded_source_cache_json(
            redis_client,
            template.format(symbol=symbol),
        )
        if not isinstance(payload, dict):
            continue
        fetched_ms = _strict_positive_epoch_ms(
            payload.get("ts_ms") or payload.get("timestamp")
        )
        # CoinAnk's payload clock is the only source-availability cutoff for
        # these rows.  A missing, fractional, or future cutoff cannot prove
        # that any bucket was final when the payload became observable.
        if fetched_ms is None or fetched_ms > _observed_epoch_ms():
            continue
        request_started_at_ms = _strict_positive_epoch_ms(
            payload.get("request_started_at_ms")
        )
        # ``ts_ms`` is written after response parsing by the legacy producer;
        # it cannot prove a row was final when the request snapshot began.
        # Until the producer carries this pre-request cutoff, CoinAnk remains
        # optional/unavailable rather than promoting a boundary-straddling row.
        if (
            request_started_at_ms is None
            or request_started_at_ms > fetched_ms
        ):
            continue
        inner = payload.get("data")
        rows = inner.get("data") if isinstance(inner, dict) else None
        if (
            not isinstance(rows, list)
            or not rows
            or len(rows) > SOURCE_CADENCE_MAX_CLOCKS
        ):
            continue
        bucket_ms = COINANK_OI_BUCKET_MS.get(tf, 300_000)
        mapped: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            begin = _strict_positive_epoch_ms(row.get("begin"))
            close = _safe_float(row.get("close"))
            if begin is None or close is None or close <= 0:
                continue
            # ``begin`` is the bucket-open clock and the derived row clock is
            # its exact close boundary.  Never truncate an unfinished bucket
            # to the fetch time: that turns a partial value into a fake final.
            row_ms = begin + bucket_ms
            if row_ms >= request_started_at_ms:
                continue
            mapped.append(
                {
                    "symbol": symbol,
                    "sumOpenInterest": close,
                    "timestamp": int(row_ms),
                    "event_time": int(row_ms),
                    "ingested_at": fetched_ms,
                    "available_at": fetched_ms,
                    "finality_cutoff_ms": request_started_at_ms,
                    "finality_cutoff_source_field": "request_started_at_ms",
                    "generated_at": payload.get("generated_at"),
                    "period": tf,
                    "source": "coinank_open_interest_kline_backup",
                    "transport": "provider_backup_cache",
                    "source_receipt_authority": False,
                    "trainer_authority": False,
                }
            )
        if mapped:
            mapped.sort(key=lambda r: r["timestamp"])
            return mapped
    return None


def _coinank_point_open_interest(symbol: str, *, redis_client: Any = None) -> dict | None:
    """Newest CoinAnk OI row as a point open-interest payload (contracts)."""
    rows = _coinank_oi_hist_rows(symbol, redis_client=redis_client)
    if not rows:
        return None
    last = rows[-1]
    return {
        "symbol": symbol,
        "open_interest": last["sumOpenInterest"],
        "openInterest": last["sumOpenInterest"],
        "time": last["timestamp"],
        "finality_cutoff_ms": last["finality_cutoff_ms"],
        "finality_cutoff_source_field": last["finality_cutoff_source_field"],
        "fetched_utc": _utc_iso(),
        "unit": "contracts",
        "source": "coinank_open_interest_kline_backup",
        "transport": "provider_backup_cache",
        "source_receipt_authority": False,
        "trainer_authority": False,
    }


def _open_interest_cache_age_seconds(payload: dict) -> float | None:
    """Age of an open-interest cache payload, or None when it is undated."""
    event_ms = _strict_positive_epoch_ms(
        payload.get("time") or payload.get("timestamp") or payload.get("binance_time_ms")
    )
    if event_ms is not None:
        age = time.time() - event_ms / 1000.0
        return age if age >= 0.0 else None
    for field in ("fetched_utc", "available_at"):
        value = payload.get(field)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age = time.time() - parsed.timestamp()
            return age if age >= 0.0 else None
    return None


def _fetch_open_interest(symbol: str, *, redis_client: Any = None) -> dict | None:
    cached = _read_json(redis_client, f"{V2_REDIS_PREFIX}market:open_interest:{symbol}")
    if isinstance(cached, dict) and cached:
        cache_age = _open_interest_cache_age_seconds(cached)
        if cache_age is not None and cache_age <= OPEN_INTEREST_CACHE_MAX_AGE_SECONDS:
            # Fresh, dated payload: echo it while PRESERVING its original
            # timestamps (never re-stamp an echo, or staleness is laundered).
            return {
                **cached,
                "symbol": cached.get("symbol") or symbol,
                "source": _cache_payload_source(cached, default="binance_public_websocket_cache_primary"),
                "transport": _cache_transport(cached),
            }
        # Stale or undated cache payload: fail closed on the echo and fall
        # through to the provider-backup / public REST tiers.
    provider = _coinank_point_open_interest(symbol, redis_client=redis_client)
    provider_age = _open_interest_cache_age_seconds(provider) if provider else None
    if (
        provider is not None
        and provider_age is not None
        and provider_age <= OPEN_INTEREST_CACHE_MAX_AGE_SECONDS
    ):
        # Provider data as fresh as the cache bar: prefer it over REST to
        # conserve the shared Binance fallback budget.
        return provider
    if not _rest_fallback_disabled():
        try:
            data = _http_get_json(
                f"{BINANCE_FAPI}/fapi/v1/openInterest?symbol={symbol}",
                fallback_reason="open_interest_websocket_cache_missing_or_stale",
            )
        except Exception:
            data = None
        if isinstance(data, dict):
            # Canonical field alias + wall-clock stamp so the written payload
            # is always dated and readable by the feature pipeline
            # (open_interest/openInterest/sumOpenInterest).
            data["open_interest"] = _safe_float(data.get("openInterest"))
            data["fetched_utc"] = _utc_iso()
            data["source"] = "binance_public_rest_open_interest_fallback"
            data["transport"] = "rest_fallback"
            return data
    # Degraded rescue tier: REST unavailable (disabled / budget exhausted /
    # error) — bounded-staleness CoinAnk value beats no OI at all, and its
    # honest row time keeps downstream freshness gates authoritative.
    if (
        provider is not None
        and provider_age is not None
        and provider_age <= PROVIDER_OI_RESCUE_MAX_AGE_SECONDS
    ):
        return {**provider, "degraded_staleness_seconds": round(provider_age, 1)}
    return None


def _contains_unverified_publication_claim(value: Any) -> bool:
    """Reject inherited receipt/authority claims this loop cannot verify."""

    stack: list[tuple[Any, int]] = [(value, 0)]
    seen: set[int] = set()
    nodes = 0
    while stack:
        current, depth = stack.pop()
        if not isinstance(current, dict | list | tuple):
            continue
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)
        nodes += 1
        if depth > SOURCE_CACHE_MAX_JSON_DEPTH or nodes > SOURCE_CACHE_MAX_JSON_NODES:
            return True
        if isinstance(current, dict):
            for raw_key, nested in current.items():
                key = str(raw_key).strip().lower()
                if key == "authority" or key.endswith("_authority"):
                    if nested is not False:
                        return True
                    continue
                if "receipt" in key or "postcommit" in key or "readback" in key:
                    return True
                if isinstance(nested, dict | list | tuple):
                    stack.append((nested, depth + 1))
        else:
            stack.extend(
                (nested, depth + 1)
                for nested in current
                if isinstance(nested, dict | list | tuple)
            )
    return False


def _finalized_cached_websocket_kline(
    row: Any,
    *,
    observed_at_ms: int,
) -> dict[str, Any] | None:
    """Return one explicitly final, causally observable WSS cache row."""

    if (
        not isinstance(row, dict)
        or _contains_unverified_publication_claim(row)
        or not _is_websocket_cache_payload(row)
    ):
        return None
    if row.get("is_closed") is not True:
        return None
    for alias in ("closed_candle", "candle_closed_confirmed", "feature_eligible"):
        if alias in row and row.get(alias) is not True:
            return None
    close_ms = _strict_positive_epoch_ms(
        _first_present(
            row.get("candle_close_time"),
            row.get("close_time"),
            row.get("closeTime"),
            row.get("T"),
        )
    )
    # Binance close clocks are inclusive: equality with the observation clock
    # is not yet final.  A producer boolean alone is never sufficient.
    if close_ms is None or close_ms >= observed_at_ms:
        return None
    raw_available = row.get("available_at")
    if raw_available not in (None, ""):
        available_ms = _strict_positive_epoch_ms(raw_available)
        if (
            available_ms is None
            or available_ms <= close_ms
            or available_ms > observed_at_ms
        ):
            return None
    return {
        **row,
        "source_receipt_authority": False,
        "trainer_authority": False,
    }


def _fetch_klines(
    symbol: str,
    interval: str = "1m",
    limit: int = 100,
    *,
    redis_client: Any = None,
) -> list | None:
    """Fetch a small OHLCV history from WebSocket cache, with REST fallback.

    WSS-backed closed-candle Redis keys are primary. Public REST is only used
    when the explicit fallback env flag is enabled.
    """
    for key in (
        closed_candle_key("binance", symbol, interval),
        f"{V2_REDIS_PREFIX}market:ohlcv:binance:{symbol}:{interval}",
    ):
        cached = _read_json(redis_client, key)
        if isinstance(cached, list) and cached:
            observed_at_ms = _observed_epoch_ms()
            websocket_rows = [
                finalized
                for row in cached
                if (
                    finalized := _finalized_cached_websocket_kline(
                        row,
                        observed_at_ms=observed_at_ms,
                    )
                )
                is not None
            ]
            if websocket_rows:
                return websocket_rows[-max(1, min(int(limit), len(websocket_rows))) :]
    current = _read_json(redis_client, current_candle_key("binance", symbol, interval))
    if isinstance(current, dict):
        finalized_current = _finalized_cached_websocket_kline(
            current,
            observed_at_ms=_observed_epoch_ms(),
        )
        if finalized_current is not None:
            return [finalized_current]
    if _rest_fallback_disabled():
        return None
    request_started_at_ms = _observed_epoch_ms()
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={int(limit)}",
            fallback_reason="closed_kline_websocket_cache_missing_or_stale",
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None
    response_received_at_ms = _observed_epoch_ms()
    if response_received_at_ms < request_started_at_ms or not isinstance(data, list):
        return None
    canonical_rows: list[dict[str, Any]] = []
    for raw_row in data:
        if type(raw_row) is not list or not 11 <= len(raw_row) <= 12:
            return None
        try:
            candle = canonical_from_binance_rest(
                raw_row,
                symbol=symbol,
                timeframe=interval,
                ingested_at=response_received_at_ms,
            )
        except (TypeError, ValueError, OverflowError):
            return None
        # Request start is the immutable finality cutoff.  A response that
        # straddles a close must not promote the row that was still forming
        # when the request began.
        if not candle.is_closed or candle.candle_close_time >= request_started_at_ms:
            continue
        canonical_rows.append(
            {
                **candle.to_dict(),
                "source_receipt_authority": False,
                "trainer_authority": False,
            }
        )
    canonical_rows.sort(key=lambda row: int(row["candle_open_time"]))
    return canonical_rows[-max(1, min(int(limit), len(canonical_rows))) :] or None


def _normalize_open_interest_hist_rows(
    rows: list[Any],
    *,
    symbol: str,
    period: str,
    source: str,
    transport: str,
    observed_at: str,
) -> list[dict[str, Any]] | None:
    if not rows or len(rows) > SOURCE_CADENCE_MAX_CLOCKS:
        return None
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            return None
        event_time = _first_present(raw.get("event_time"), raw.get("timestamp"))
        row = {
            **raw,
            # Binance returns symbol; a missing/mismatched symbol must remain
            # visible to the identity gate rather than inherit the request.
            "symbol": raw.get("symbol"),
            # Period/source/transport are bound by this exact request context
            # only when Binance omitted those metadata fields.
            "period": raw["period"] if "period" in raw else period,
            "sumOpenInterest": raw.get("sumOpenInterest"),
            "event_time": event_time,
            # These are this ingestor's own clocks only when the upstream row
            # omitted the fields.  A present-but-invalid upstream clock must
            # survive normalization so the strict clock gate can reject it.
            "ingested_at": (
                raw["ingested_at"] if "ingested_at" in raw else observed_at
            ),
            "available_at": (
                raw["available_at"] if "available_at" in raw else observed_at
            ),
            "source": raw["source"] if "source" in raw else source,
            "transport": raw["transport"] if "transport" in raw else transport,
        }
        # ``generated_at`` is intentionally never synthesized from ingestion
        # or availability time.  Preserve it only when the producer supplied
        # that distinct clock.
        if raw.get("generated_at") in (None, ""):
            row.pop("generated_at", None)
        normalized.append(row)
    return normalized or None


def _validated_open_interest_hist_candidate(
    rows: list[Any],
    *,
    expected_symbol: str,
    period: str,
    diagnostics: dict[str, Any] | None,
) -> list[dict[str, Any]] | None:
    if len(rows) > SOURCE_CADENCE_MAX_CLOCKS:
        _set_availability(
            diagnostics,
            {"reason": "OPEN_INTEREST_HISTORY_ROW_COUNT_EXCEEDED"},
        )
        return None
    copied = [dict(row) for row in rows if isinstance(row, dict)]
    if len(copied) != len(rows) or not copied:
        _set_availability(diagnostics, {"reason": "OPEN_INTEREST_HISTORY_SCHEMA_INVALID"})
        return None
    event_clocks = [
        _first_present(row.get("event_time"), row.get("timestamp")) for row in copied
    ]
    newest_freshness: dict[str, Any] = {"reason": "SOURCE_EVENT_TIME_MISSING"}
    cadence: dict[str, Any] = {}
    now = time.time()
    history_source: str | None = None
    history_transport: str | None = None
    for index, row in enumerate(copied):
        identity_reason = _source_identity_reason(
            row,
            expected_symbol=expected_symbol,
            expected_period=period,
            source_transports=OPEN_INTEREST_HISTORY_SOURCE_TRANSPORTS,
        )
        if identity_reason is not None:
            _set_availability(diagnostics, {"reason": identity_reason})
            return None
        row_source = str(row["source"])
        row_transport = str(row["transport"])
        if history_source is None:
            history_source = row_source
            history_transport = row_transport
        elif row_source != history_source or row_transport != history_transport:
            _set_availability(
                diagnostics,
                {"reason": "SOURCE_IDENTITY_INCONSISTENT_WITHIN_HISTORY"},
            )
            return None
        open_interest = _safe_float(row.get("sumOpenInterest"))
        if open_interest is None or open_interest <= 0.0:
            newest_freshness = {"reason": "OPEN_INTEREST_HISTORY_VALUE_INVALID"}
            _set_availability(diagnostics, newest_freshness)
            return None
        _, clock_reason = _source_clock_state(row, now=now)
        if clock_reason != "SOURCE_CLOCKS_VALID":
            _set_availability(diagnostics, {"reason": clock_reason})
            return None
        if index < len(copied) - 1:
            continue
        fresh, newest_freshness, cadence = _source_freshness(
            row,
            event_clocks,
            period=period,
        )
        if not fresh:
            _set_availability(diagnostics, newest_freshness)
            return None
    copied[-1] = {
        **copied[-1],
        "cadence_evidence": cadence,
        "source_freshness": newest_freshness,
    }
    _set_availability(diagnostics, newest_freshness)
    return copied


def _fetch_open_interest_hist(
    symbol: str,
    period: str = "5m",
    limit: int = 13,
    *,
    redis_client: Any = None,
    diagnostics: dict[str, Any] | None = None,
) -> list | None:
    """Fetch recent open-interest history from Binance Futures public data.

    Returns a list of rows, each: {symbol, sumOpenInterest, sumOpenInterestValue,
    timestamp}. Public endpoint (``/futures/data/openInterestHist``), no key.
    Used by the feature pipeline to compute real ``oi_change_pct`` instead of a
    silent zero. ``limit=13`` at 5m spans ~1h.
    """
    last_rejection: dict[str, Any] = {}

    def accepted(rows: Any) -> list[dict[str, Any]] | None:
        nonlocal last_rejection
        if not isinstance(rows, list) or not rows:
            return None
        candidate_diagnostics: dict[str, Any] = {}
        candidate = _validated_open_interest_hist_candidate(
            rows,
            expected_symbol=symbol,
            period=period,
            diagnostics=candidate_diagnostics,
        )
        if candidate is None:
            last_rejection = candidate_diagnostics
            return None
        if diagnostics is not None:
            diagnostics.clear()
            diagnostics.update(candidate_diagnostics)
        return candidate[-max(1, min(int(limit), len(candidate))) :]

    cached, cache_read_reason = _read_bounded_source_cache_json(
        redis_client,
        f"{V2_REDIS_PREFIX}market:open_interest_hist:{symbol}:{period}",
    )
    if cache_read_reason not in (None, "SOURCE_CACHE_MISSING"):
        cache_diagnostics: dict[str, Any] = {}
        _set_availability(cache_diagnostics, {"reason": cache_read_reason})
        last_rejection = cache_diagnostics
    # Own-output cache entries are accepted only through producer clocks;
    # Redis TTL and this loop's bundle-write time are never consulted.
    cache_candidate = accepted(cached)
    if cache_candidate is not None:
        return cache_candidate
    provider_candidate = accepted(
        _coinank_oi_hist_rows(symbol, redis_client=redis_client)
    )
    if provider_candidate is not None:
        return provider_candidate
    if not _optional_derivative_rest_allowed():
        if diagnostics is not None:
            if last_rejection:
                diagnostics.clear()
                diagnostics.update(last_rejection)
            else:
                _set_availability(
                    diagnostics,
                    {"reason": "OPTIONAL_DERIVATIVE_REST_DEFERRED_FOR_CANONICAL_OHLCV"},
                )
            diagnostics["rest_fallback_deferred_reason"] = (
                "CANONICAL_OHLCV_SHARED_BUDGET_PRIORITY"
            )
        return None
    if not _rest_fallback_disabled():
        try:
            data = _http_get_json(
                f"{BINANCE_FAPI}/futures/data/openInterestHist"
                f"?symbol={symbol}&period={period}"
                f"&limit={min(SOURCE_CADENCE_MAX_CLOCKS, max(1, int(limit)))}",
                fallback_reason="open_interest_history_cache_missing_or_stale",
            )
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            OSError,
            ValueError,
            RuntimeError,
        ):
            data = None
        if isinstance(data, list) and len(data) > SOURCE_CADENCE_MAX_CLOCKS:
            last_rejection = {}
            _set_availability(
                last_rejection,
                {"reason": "OPEN_INTEREST_HISTORY_ROW_COUNT_EXCEEDED"},
            )
        elif isinstance(data, list) and data:
            normalized = _normalize_open_interest_hist_rows(
                data,
                symbol=symbol,
                period=period,
                source="binance_open_interest_history_rest_fallback",
                transport="rest_fallback",
                observed_at=_utc_iso_precise(),
            )
            rest_candidate = accepted(normalized)
            if rest_candidate is not None:
                return rest_candidate
            if normalized is None:
                last_rejection = {"reason": "OPEN_INTEREST_HISTORY_REST_SCHEMA_INVALID"}
    if diagnostics is not None:
        if last_rejection:
            diagnostics.clear()
            diagnostics.update(last_rejection)
        else:
            _set_availability(
                diagnostics,
                {"reason": "OPEN_INTEREST_HISTORY_SOURCE_MISSING_OR_FALLBACK_UNAVAILABLE"},
            )
    return None


def _validated_long_short_candidate(
    payload: dict[str, Any],
    *,
    expected_symbol: str,
    period: str,
    event_clock_values: list[Any],
    diagnostics: dict[str, Any] | None,
) -> dict[str, Any] | None:
    features, feature_availability, feature_reason = _long_short_feature_contract(
        payload
    )
    if feature_reason is not None:
        _set_availability(diagnostics, {"reason": feature_reason})
        if diagnostics is not None:
            diagnostics["feature_availability"] = feature_availability
            diagnostics["all_required_features_available"] = False
        return None
    identity_reason = _source_identity_reason(
        payload,
        expected_symbol=expected_symbol,
        expected_period=period,
        source_transports=LONG_SHORT_SOURCE_TRANSPORTS,
    )
    if identity_reason is not None:
        _set_availability(diagnostics, {"reason": identity_reason})
        if diagnostics is not None:
            diagnostics["feature_availability"] = feature_availability
            diagnostics["all_required_features_available"] = False
        return None
    fresh, freshness, cadence = _source_freshness(
        payload, event_clock_values, period=period
    )
    for availability in feature_availability.values():
        availability["readiness_eligible"] = fresh
    _set_availability(diagnostics, freshness)
    if diagnostics is not None:
        diagnostics["feature_availability"] = feature_availability
        diagnostics["all_required_features_available"] = fresh
    if not fresh:
        return None
    assert features is not None
    return {
        **payload,
        **features,
        "cadence_evidence": cadence,
        "source_freshness": freshness,
    }


def _fetch_long_short_ratio(
    symbol: str,
    period: str = "5m",
    limit: int = 1,
    *,
    redis_client: Any = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict | None:
    """Fetch Binance Futures global long/short account ratio.

    Endpoint is public and keyless, but may be unavailable from restricted
    jurisdictions. Non-list Binance error payloads intentionally return None so
    downstream code sees a missing source instead of a fabricated neutral value.
    """
    cache_rejection: dict[str, Any] = {}

    def publish_diagnostics(source: dict[str, Any]) -> None:
        if diagnostics is not None:
            diagnostics.clear()
            diagnostics.update(source)

    def reject(reason: str) -> None:
        _set_availability(diagnostics, {"reason": reason})

    cached, cache_read_reason = _read_bounded_source_cache_json(
        redis_client,
        f"{V2_REDIS_PREFIX}market:long_short:{symbol}",
    )
    if cache_read_reason not in (None, "SOURCE_CACHE_MISSING"):
        _set_availability(cache_rejection, {"reason": cache_read_reason})
    if isinstance(cached, dict) and cached:
        cached_evidence = cached.get("cadence_evidence")
        cache_diagnostics: dict[str, Any] = {}
        cached_event_clocks: list[Any] = []
        raw_event_clocks = (
            cached_evidence.get("event_times_epoch_seconds")
            if isinstance(cached_evidence, dict)
            else None
        )
        if isinstance(raw_event_clocks, list):
            if len(raw_event_clocks) > SOURCE_CADENCE_MAX_CLOCKS:
                _set_availability(
                    cache_diagnostics,
                    {"reason": "SOURCE_CADENCE_EVIDENCE_TOO_LARGE"},
                )
            else:
                cached_event_clocks = raw_event_clocks
        accepted_cache = None
        if not cache_diagnostics:
            # Raw bytes and nested evidence count are bounded before copying
            # the cache payload into the candidate admission path.
            cached_payload = dict(cached)
            accepted_cache = _validated_long_short_candidate(
                cached_payload,
                expected_symbol=symbol,
                period=period,
                event_clock_values=cached_event_clocks,
                diagnostics=cache_diagnostics,
            )
        if accepted_cache is not None:
            publish_diagnostics(cache_diagnostics)
            return accepted_cache
        cache_rejection = cache_diagnostics
    if not _optional_derivative_rest_allowed():
        if cache_rejection:
            publish_diagnostics(cache_rejection)
        else:
            reject("OPTIONAL_DERIVATIVE_REST_DEFERRED_FOR_CANONICAL_OHLCV")
        if diagnostics is not None:
            diagnostics["rest_fallback_deferred_reason"] = (
                "CANONICAL_OHLCV_SHARED_BUDGET_PRIORITY"
            )
        return None
    if _rest_fallback_disabled():
        if cache_rejection:
            publish_diagnostics(cache_rejection)
        else:
            reject("LONG_SHORT_RATIO_SOURCE_MISSING_REST_FALLBACK_DISABLED")
        return None
    try:
        evidence_row_count = SOURCE_CADENCE_MIN_INTERVALS + 1
        data = _http_get_json(
            f"{BINANCE_FAPI}/futures/data/globalLongShortAccountRatio?"
            + urlencode(
                {
                    "symbol": symbol,
                    "period": period,
                    "limit": min(
                        SOURCE_CADENCE_MAX_CLOCKS,
                        max(int(limit), evidence_row_count),
                    ),
                }
            ),
            fallback_reason="long_short_ratio_cache_missing_stale_or_clock_invalid",
        )
    except Exception:
        reject("LONG_SHORT_RATIO_REST_REQUEST_FAILED")
        return None
    if not isinstance(data, list) or not data:
        reject("LONG_SHORT_RATIO_REST_SCHEMA_INVALID")
        return None
    if len(data) > SOURCE_CADENCE_MAX_CLOCKS:
        reject("LONG_SHORT_RATIO_REST_ROW_COUNT_EXCEEDED")
        return None
    normalized_rows: list[dict[str, Any]] = []
    for raw_row in data:
        if not isinstance(raw_row, dict):
            reject("LONG_SHORT_RATIO_REST_ROW_INVALID")
            return None
        normalized_row = {
            **raw_row,
            "symbol": raw_row.get("symbol"),
            "period": raw_row["period"] if "period" in raw_row else period,
            "source": (
                raw_row["source"]
                if "source" in raw_row
                else "binance_global_long_short_account_ratio_rest_fallback"
            ),
            "transport": raw_row["transport"] if "transport" in raw_row else "rest_fallback",
            "event_time": _first_present(
                raw_row.get("event_time"),
                raw_row.get("timestamp"),
            ),
        }
        identity_reason = _source_identity_reason(
            normalized_row,
            expected_symbol=symbol,
            expected_period=period,
            source_transports=LONG_SHORT_SOURCE_TRANSPORTS,
        )
        if identity_reason is not None:
            reject(identity_reason)
            return None
        normalized_rows.append(normalized_row)
    row = normalized_rows[-1]
    observed_at = _utc_iso_precise()
    payload = {
        **row,
        "longShortRatio": row.get("longShortRatio"),
        "longAccount": row.get("longAccount"),
        "shortAccount": row.get("shortAccount"),
        "timestamp": row.get("timestamp"),
        "long_short_ratio": _safe_float(row.get("longShortRatio")),
        "long_account_ratio": _safe_float(row.get("longAccount")),
        "short_account_ratio": _safe_float(row.get("shortAccount")),
        "ingested_at": row["ingested_at"] if "ingested_at" in row else observed_at,
        "available_at": row["available_at"] if "available_at" in row else observed_at,
        "fetched_utc": observed_at,
    }
    rest_diagnostics: dict[str, Any] = {}
    accepted_rest = _validated_long_short_candidate(
        payload,
        expected_symbol=symbol,
        period=period,
        event_clock_values=[
            _first_present(item.get("event_time"), item.get("timestamp"))
            for item in normalized_rows
        ],
        diagnostics=rest_diagnostics,
    )
    if accepted_rest is None:
        publish_diagnostics(rest_diagnostics)
        return None
    publish_diagnostics(rest_diagnostics)
    return accepted_rest


# A cached order book older than this must NOT be re-emitted: two of the
# cache keys below are this ingestor's OWN output keys, so without a
# freshness gate a stale book echoes forever (each cycle re-reads the frozen
# snapshot and rewrites it with a fresh TTL) and the REST depth fallback is
# unreachable (2026-07-16 incident: v2:market:orderbook:BTCUSDT frozen at
# 18:03:18Z for 4.5h after the WSS transport died, freezing microstructure
# trust / A+ supply with it). Same bug class as TICKER_CACHE_MAX_AGE_SECONDS.
ORDERBOOK_CACHE_MAX_AGE_SECONDS = 120.0


def _orderbook_cache_age_seconds(book: dict) -> float | None:
    for field in ("available_at", "received_at", "generated_at", "fetched_utc"):
        value = book.get(field)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, time.time() - parsed.timestamp())
    # REST depth snapshots carry Binance ms timestamps (E = message output
    # time, T = transaction time) and no ISO fields.
    event_ms = _safe_float(book.get("E") or book.get("T"))
    if event_ms is not None and event_ms > 0:
        return max(0.0, time.time() - event_ms / 1000.0)
    return None


def _fetch_orderbook_top(symbol: str, depth: int = 20, *, redis_client: Any = None) -> dict | None:
    """Fetch public order-book top from WebSocket cache, with REST fallback.

    Returns dict with ``bids`` and ``asks`` lists of [price, qty]. Used by the
    feature pipeline for real ``depth_imbalance``.
    """
    for key in (
        f"{V2_REDIS_PREFIX}orderbook:top:binance:{symbol}",
        f"{V2_REDIS_PREFIX}market:orderbook:binance:{symbol}",
        f"{V2_REDIS_PREFIX}market:orderbook:{symbol}",
    ):
        cached = _read_json(redis_client, key)
        if isinstance(cached, dict) and (
            cached.get("bids")
            or cached.get("asks")
            or cached.get("best_bid")
            or cached.get("best_ask")
        ):
            cache_age = _orderbook_cache_age_seconds(cached)
            if cache_age is None or cache_age > ORDERBOOK_CACHE_MAX_AGE_SECONDS:
                # Stale or undated cache payload: fail closed on the echo and
                # fall through to the next source / REST depth snapshot.
                continue
            return {
                **cached,
                "symbol": cached.get("symbol") or symbol,
                "source": _cache_payload_source(cached, default="binance_public_websocket_orderbook_cache_primary"),
                "transport": _cache_transport(cached),
            }
    if _rest_fallback_disabled():
        return None
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/fapi/v1/depth?symbol={symbol}&limit={int(depth)}",
            fallback_reason="orderbook_websocket_cache_missing_or_stale",
        )
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data["source"] = "binance_public_rest_depth_snapshot_fallback"
    data["transport"] = "rest_fallback"
    return data


def _fetch_symbol_bundle(
    symbol: str,
    *,
    kline_timeframes: tuple[str, ...] = DEFAULT_KLINE_TIMEFRAMES,
    redis_client: Any = None,
) -> dict:
    fetch_errors: dict[str, str] = {}

    def fetch_component(name: str, fetch: Callable[[], Any]) -> Any:
        try:
            value = fetch()
        except Exception as exc:  # One unavailable family must not erase the others.
            detail = " ".join(str(exc).split())[:240] or "NO_DETAIL"
            fetch_errors[name] = f"{type(exc).__name__}:{detail}"
            return None
        if value is None or (isinstance(value, (dict, list)) and not value):
            fetch_errors[name] = "UNAVAILABLE_OR_REJECTED_BY_SOURCE_GATE"
            return None
        return value

    ticker = fetch_component(
        "ticker_24hr",
        lambda: _fetch_ticker_24hr(symbol, redis_client=redis_client),
    )
    funding = fetch_component(
        "funding",
        lambda: _fetch_funding(symbol, redis_client=redis_client),
    )
    oi = fetch_component(
        "open_interest",
        lambda: _fetch_open_interest(symbol, redis_client=redis_client),
    )
    klines_by_timeframe: dict[str, Any] = {}
    for timeframe in kline_timeframes:
        rows = fetch_component(
            f"klines:{timeframe}",
            partial(
                _fetch_klines,
                symbol,
                interval=timeframe,
                limit=100,
                redis_client=redis_client,
            ),
        )
        if rows is not None:
            klines_by_timeframe[timeframe] = rows
    klines = klines_by_timeframe.get("1m")
    orderbook = fetch_component(
        "orderbook",
        lambda: _fetch_orderbook_top(symbol, depth=20, redis_client=redis_client),
    )
    oi_hist_availability: dict[str, Any] = {}
    oi_hist = fetch_component(
        "open_interest_hist",
        lambda: _fetch_open_interest_hist(
            symbol,
            period="5m",
            limit=13,
            redis_client=redis_client,
            diagnostics=oi_hist_availability,
        ),
    )
    if oi_hist is None and oi_hist_availability.get("reason"):
        fetch_errors["open_interest_hist"] = str(oi_hist_availability["reason"])
    elif oi_hist is not None and not _readiness_eligible(oi_hist):
        fetch_errors["open_interest_hist"] = "SOURCE_CADENCE_WARMUP_NOT_READINESS_ELIGIBLE"
    long_short_availability: dict[str, Any] = {}
    long_short = fetch_component(
        "long_short",
        lambda: _fetch_long_short_ratio(
            symbol,
            period="5m",
            limit=1,
            redis_client=redis_client,
            diagnostics=long_short_availability,
        ),
    )
    if long_short is None and long_short_availability.get("reason"):
        fetch_errors["long_short"] = str(long_short_availability["reason"])
    elif long_short is not None and not _readiness_eligible(long_short):
        fetch_errors["long_short"] = "SOURCE_CADENCE_WARMUP_NOT_READINESS_ELIGIBLE"
    long_short_ready = _readiness_eligible(long_short)
    oi_hist_ready = _readiness_eligible(oi_hist)
    kline_cache_primary_count = sum(
        any(isinstance(row, dict) and _is_websocket_cache_payload(row) for row in rows)
        for rows in klines_by_timeframe.values()
        if isinstance(rows, list)
    )
    kline_rest_fallback_count = len(klines_by_timeframe) - kline_cache_primary_count
    cache_primary_count = sum(
        1
        for payload in (ticker, funding, oi, orderbook)
        if isinstance(payload, dict)
        and _cache_transport(payload) == "websocket_cache_primary"
    ) + kline_cache_primary_count + (
        1
        if long_short_ready
        and isinstance(long_short, dict)
        and _cache_transport(long_short) == "websocket_cache_primary"
        else 0
    )
    rest_fallback_count = sum(
        1
        for payload in (ticker, funding, oi, orderbook)
        if isinstance(payload, dict)
        and _cache_transport(payload) == "rest_fallback_cache"
    ) + kline_rest_fallback_count + (
        1
        if long_short_ready
        and isinstance(long_short, dict)
        and _cache_transport(long_short) == "rest_fallback_cache"
        else 0
    )
    accepted_source_field_count = sum(
        (
            ticker is not None,
            funding is not None,
            oi is not None,
            orderbook is not None,
            long_short_ready,
            oi_hist_ready,
        )
    ) + len(klines_by_timeframe)
    return {
        "symbol": symbol,
        "source": "binance_public_websocket_cache_primary",
        "transport": "websocket_cache_primary",
        "rest_fallback_used": rest_fallback_count > 0,
        "ticker": ticker,
        "funding": funding,
        "open_interest": oi,
        "long_short": long_short,
        "klines": klines,
        "klines_by_timeframe": klines_by_timeframe,
        "orderbook": orderbook,
        "open_interest_hist": oi_hist,
        "source_availability": {
            "open_interest_hist": oi_hist_availability,
            "long_short": long_short_availability,
        },
        "fetch_errors": fetch_errors,
        "partial_bundle": bool(fetch_errors),
        "symbol_info": {
            "symbol": symbol,
            "ticker_present": ticker is not None,
            "funding_present": funding is not None,
            "open_interest_present": oi is not None,
            "long_short_present": long_short is not None,
            "long_short_readiness_eligible": long_short_ready,
            "long_short_availability": long_short_availability,
            "open_interest_hist_present": oi_hist is not None,
            "open_interest_hist_readiness_eligible": oi_hist_ready,
            "open_interest_hist_availability": oi_hist_availability,
            "klines_present": klines is not None,
            "kline_timeframes_present": sorted(klines_by_timeframe),
            "orderbook_present": orderbook is not None,
            "cache_primary_field_count": cache_primary_count,
            "rest_fallback_field_count": rest_fallback_count,
            "accepted_source_field_count": accepted_source_field_count,
            "source_bundle_available": accepted_source_field_count > 0,
            "all_requested_source_fields_available": not fetch_errors,
            "trainer_authority": False,
            "source_receipt_authority": False,
            "fetch_errors": fetch_errors,
            "partial_bundle": bool(fetch_errors),
        },
    }


def run_once(
    symbols: tuple[str, ...],
    *,
    kline_timeframes: tuple[str, ...] = DEFAULT_KLINE_TIMEFRAMES,
) -> dict:
    started_at = _utc_iso()
    symbols = tuple(
        symbol
        for symbol in (str(s or "").strip().upper() for s in symbols)
        if is_valid_runtime_symbol(symbol)
    )
    r = _connect_redis()
    redis_ok = r is not None
    keys_written: list[str] = []
    symbol_results: list[dict] = []
    fetched_by_symbol: dict[str, dict] = {}
    max_workers = max(1, min(MAX_FETCH_WORKERS, len(symbols) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_symbol_bundle, sym, kline_timeframes=kline_timeframes, redis_client=r): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            sym = futures[future]
            try:
                fetched_by_symbol[sym] = future.result()
            except Exception as exc:
                detail = " ".join(str(exc).split())[:240] or "NO_DETAIL"
                fetched_by_symbol[sym] = {
                    "symbol": sym,
                    "ticker": None,
                    "funding": None,
                    "open_interest": None,
                    "klines": None,
                    "klines_by_timeframe": {},
                    "orderbook": None,
                    "open_interest_hist": None,
                    "long_short": None,
                    "fetch_errors": {
                        "symbol_bundle": f"{type(exc).__name__}:{detail}",
                    },
                    "partial_bundle": True,
                    "symbol_info": {
                        "symbol": sym,
                        "ticker_present": False,
                        "funding_present": False,
                        "open_interest_present": False,
                        "long_short_present": False,
                        "open_interest_hist_present": False,
                        "klines_present": False,
                        "kline_timeframes_present": [],
                        "orderbook_present": False,
                        "fetch_errors": {
                            "symbol_bundle": f"{type(exc).__name__}:{detail}",
                        },
                        "partial_bundle": True,
                    },
                }
            _write_symbol_bundle(r, sym, fetched_by_symbol[sym], keys_written)
    for sym in symbols:
        bundle = fetched_by_symbol.get(sym) or _fetch_symbol_bundle(sym, redis_client=r)
        sym_info = bundle.get("symbol_info") or {"symbol": sym}
        if redis_ok and sym not in fetched_by_symbol:
            _write_symbol_bundle(r, sym, bundle, keys_written)
        symbol_results.append(sym_info)
    accepted_source_field_count = sum(
        int(result.get("accepted_source_field_count") or 0)
        for result in symbol_results
    )
    source_data_available = bool(redis_ok and accepted_source_field_count > 0)
    partial_symbol_count = sum(
        1 for result in symbol_results if result.get("partial_bundle") is True
    )
    fully_available_symbol_count = sum(
        1
        for result in symbol_results
        if result.get("all_requested_source_fields_available") is True
    )
    cache_primary_available = any(
        int(result.get("cache_primary_field_count") or 0) > 0
        for result in symbol_results
    )
    rest_fallback_available = any(
        int(result.get("rest_fallback_field_count") or 0) > 0
        for result in symbol_results
    )
    if not redis_ok:
        classification = "BLOCKED_BY_REDIS_UNAVAILABLE"
    elif not source_data_available:
        classification = "BLOCKED_BY_NETWORK_OR_API"
    elif cache_primary_available:
        classification = (
            "NATIVE_V2_PUBLIC_WEBSOCKET_CACHE_PARTIAL"
            if partial_symbol_count
            else "NATIVE_V2_PUBLIC_WEBSOCKET_CACHE_OK"
        )
    elif rest_fallback_available:
        classification = (
            "NATIVE_V2_PUBLIC_REST_FALLBACK_PARTIAL"
            if partial_symbol_count
            else "NATIVE_V2_PUBLIC_REST_FALLBACK_OK"
        )
    else:
        classification = "NATIVE_V2_PUBLIC_ALTERNATIVE_SOURCE_PARTIAL"
    heartbeat = {
        "worker_id": "v2_native_ingestors_live_loop",
        "schema_version": HEARTBEAT_SCHEMA_VERSION,
        "schema_compatibility": _heartbeat_schema_compatibility(),
        "started_at": started_at,
        "finished_at": _utc_iso(),
        "symbols": list(symbols),
        "kline_timeframes": list(kline_timeframes),
        "redis_ok": redis_ok,
        "v2_market_keys_written": keys_written,
        "v2_market_keys_written_count": len(keys_written),
        "symbol_results": symbol_results,
        "classification": classification,
        "accepted_source_field_count": accepted_source_field_count,
        "source_data_available": source_data_available,
        "partial_symbol_count": partial_symbol_count,
        "fully_available_symbol_count": fully_available_symbol_count,
        "transport_policy": "binance_public_websocket_cache_primary_rest_fallback_only",
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "rest_fallback_env": REST_FALLBACK_ENV,
        "optional_derivative_rest_fallback_allowed": _optional_derivative_rest_allowed(),
        "optional_derivative_rest_fallback_env": OPTIONAL_DERIVATIVE_REST_ENV,
        "optional_derivative_rest_priority": "DEFER_TO_CANONICAL_OHLCV_BY_DEFAULT",
        "runtime_mode": "LIVE_MARKET_DATA_PAPER_EXECUTION_DISABLED",
        "live_data_enabled": source_data_available,
        # This source heartbeat is observability, never a decision/trainer
        # admission receipt.  Downstream PIT publication must authorize use.
        "live_decision_input_enabled": False,
        "live_decision_input_block_reason": "SOURCE_HEARTBEAT_IS_NOT_A_PIT_PUBLICATION_RECEIPT",
        "trainer_input_enabled": False,
        "trainer_authority": False,
        "source_receipt_authority": False,
        "trader_execution_enabled": False,
        "execution_live_symbols": [],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
    }
    if redis_ok:
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}market:ingestor:heartbeat",
            json.dumps(heartbeat),
            ex=300,
        )
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}market:ohlcv:binance:heartbeat",
            json.dumps(heartbeat),
            ex=300,
        )
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}market:orderbook:binance:heartbeat",
            json.dumps(heartbeat),
            ex=300,
        )
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}market:ingestor:status",
            heartbeat["classification"],
            ex=300,
        )
    return heartbeat


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        # Disk full (errno 28) or other IO error — log and continue rather than crash
        import errno as _errno
        print(
            f"[write_payload] WARNING: could not write {path}: {exc}"
            + (" (disk full — check available space)" if exc.errno == _errno.ENOSPC else ""),
            file=sys.stderr,
        )


def _build_fetch_in_progress_payload(symbols: tuple[str, ...]) -> dict:
    return {
        "worker_id": "v2_native_ingestors_live_loop",
        "schema_version": HEARTBEAT_SCHEMA_VERSION,
        "schema_compatibility": _heartbeat_schema_compatibility(),
        "started_at": _utc_iso(),
        "finished_at": None,
        "symbols": list(symbols),
        "kline_timeframes": list(DEFAULT_KLINE_TIMEFRAMES),
        "redis_ok": None,
        "v2_market_keys_written": [],
        "v2_market_keys_written_count": 0,
        "symbol_results": [],
        "classification": "NATIVE_V2_PUBLIC_WEBSOCKET_CACHE_FETCH_IN_PROGRESS",
        "transport_policy": "binance_public_websocket_cache_primary_rest_fallback_only",
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "rest_fallback_env": REST_FALLBACK_ENV,
        "optional_derivative_rest_fallback_allowed": _optional_derivative_rest_allowed(),
        "optional_derivative_rest_fallback_env": OPTIONAL_DERIVATIVE_REST_ENV,
        "optional_derivative_rest_priority": "DEFER_TO_CANONICAL_OHLCV_BY_DEFAULT",
        "runtime_mode": "LIVE_MARKET_DATA_PAPER_EXECUTION_DISABLED",
        "live_data_enabled": False,
        "live_decision_input_enabled": False,
        "live_decision_input_block_reason": "SOURCE_FETCH_IN_PROGRESS_NO_PIT_PUBLICATION_RECEIPT",
        "trainer_input_enabled": False,
        "trainer_authority": False,
        "source_receipt_authority": False,
        "trader_execution_enabled": False,
        "execution_live_symbols": [],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
    }


def _resolve_runtime_symbols(raw_symbols: str | None, *, smoke_test: bool) -> tuple[str, ...]:
    return tuple(
        symbol
        for symbol in resolve_symbols(
            explicit=raw_symbols,
            smoke_test=smoke_test,
            include_baseline=True,
        )
        if is_valid_runtime_symbol(symbol)
    )


def _parse_csv_timeframes(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_KLINE_TIMEFRAMES
    out: list[str] = []
    for part in raw.split(","):
        tf = part.strip()
        if tf and tf not in out:
            out.append(tf)
    return tuple(out) or DEFAULT_KLINE_TIMEFRAMES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_native_ingestors_live_loop")
    parser.add_argument(
        "--symbols",
        default=None,
        help="Explicit comma-separated symbols. Omit for dynamic universe plus 25-symbol baseline.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use the BTC/ETH/SOL smoke-test set; never the default.",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument(
        "--fetch-timeframes",
        default=",".join(DEFAULT_KLINE_TIMEFRAMES),
        help="Comma-separated Binance kline timeframes to fetch for V2 OHLCV/TA.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop and args.once:
        print("ERROR: --loop and --once are mutually exclusive", file=sys.stderr)
        return 2
    if args.loop:
        while True:
            symbols = _resolve_runtime_symbols(args.symbols, smoke_test=args.smoke_test)
            write_payload(_build_fetch_in_progress_payload(symbols), args.out)
            hb = run_once(symbols, kline_timeframes=_parse_csv_timeframes(args.fetch_timeframes))
            write_payload(hb, args.out)
            time.sleep(max(5, int(args.interval_seconds)))
    symbols = _resolve_runtime_symbols(args.symbols, smoke_test=args.smoke_test)
    hb = run_once(symbols, kline_timeframes=_parse_csv_timeframes(args.fetch_timeframes))
    write_payload(hb, args.out)
    print(json.dumps({
        "classification": hb["classification"],
        "v2_market_keys_written_count": hb["v2_market_keys_written_count"],
        "redis_ok": hb["redis_ok"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
