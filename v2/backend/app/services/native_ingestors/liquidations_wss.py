"""V2-native paper/shadow Binance Futures liquidation WSS client.

Connects to the routed Binance Futures market stream
``wss://fstream.binance.com/market/ws/!forceOrder@arr`` (public, no
credentials), parses ``forceOrder`` events, maintains a time-windowed
in-memory observation buffer per symbol, and publishes:

- ``v2:market:liquidations:latest:{symbol}``   — last event
- ``v2:market:liquidations:aggregate:{symbol}`` — coverage-labelled observed aggregate
- ``v2:market:liquidations:heartbeat``          — client status

NEVER places, cancels, or modifies any order. NEVER writes any non-v2
Redis key. NEVER deserializes pickle. NEVER imports torch. NEVER
touches legacy filesystem. NEVER fabricates events: only events
received over the public WSS stream are written.

The default endpoint is the official Binance Futures public liquidation
WebSocket. The client can be re-pointed via constructor for testing,
which is how unit tests drive deterministic event streams without
network IO.
"""
from __future__ import annotations

import asyncio
from bisect import bisect_right
import dataclasses
import hashlib
import json
import math
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Deque, Iterable

DEFAULT_WSS_URL = os.getenv(
    "V2_LIQUIDATION_WSS_URL",
    "wss://fstream.binance.com/market/ws/!forceOrder@arr",
)

V2_REDIS_PREFIX = "v2:"
KEY_LATEST_TEMPLATE = "v2:market:liquidations:latest:{symbol}"
KEY_AGGREGATE_TEMPLATE = "v2:market:liquidations:aggregate:{symbol}"
KEY_OBSERVED_AGGREGATE_TEMPLATE = "v2:market:liquidations:observed_aggregate:{symbol}"
KEY_PER_SYMBOL_TEMPLATE = "v2:market:liquidations:{symbol}"
KEY_HEARTBEAT = "v2:market:liquidations:heartbeat"

# Canonical V2 liquidation events stream consumed by
# v2/legacy_owned_runtime/ingest/liquidation_levels_engine.py via
# xreadgroup. WSS forwards each REAL parsed forceOrder event into this
# stream so the levels engine can populate v2:unified_features:* hashes.
# We never synthesize events here; if WSS receives no events the stream
# stays empty.
KEY_EVENTS_STREAM = "v2:liquidations:events"
KEY_QUARANTINE_STREAM = "v2:liquidations:events:quarantine"
DEFAULT_EVENTS_STREAM_MAXLEN = int(
    os.getenv("V2_LIQUIDATION_EVENTS_STREAM_MAXLEN", "100000")
)
DEFAULT_QUARANTINE_MAXLEN = 2000
DEFAULT_QUARANTINE_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_DEDUPE_TTL_SECONDS = 48 * 3600

# Side mapping from WSS tape-side ("long"/"short") to the bridge/levels
# engine semantic side ("LONG_LIQ"/"SHORT_LIQ"). WSS uses tape-side
# (trade hit ask = "long"); bridge/levels use the LIQUIDATED-POSITION
# side. The two are inverted: a BUY counter-order liquidates a SHORT.
_TAPE_SIDE_TO_LIQ_SIDE = {
    "long": "SHORT_LIQ",
    "short": "LONG_LIQ",
}

DEFAULT_RETENTION_CAPACITY = max(
    100,
    int(os.getenv("V2_LIQUIDATION_RETENTION_MAX_EVENTS_PER_SYMBOL", "5000")),
)
DEFAULT_WINDOW_1H_MS = 60 * 60 * 1000
DEFAULT_WINDOW_24H_MS = 24 * 60 * 60 * 1000
MAX_EVENT_AGE_MS = DEFAULT_WINDOW_24H_MS
MAX_FUTURE_CLOCK_SKEW_MS = 0
DEFAULT_BACKOFF_INITIAL_SECONDS = 1.0
DEFAULT_BACKOFF_CAP_SECONDS = 30.0
OBSERVED_AGGREGATE_SEMANTIC_KIND = "observed_binance_force_order_snapshots"
SOURCE_CAPTURE_SEMANTICS = "latest_force_order_snapshot_per_symbol_per_1000ms"

OPT_IN_ENV_VAR = "V2_LIQUIDATION_WSS_OPT_IN"
STREAM_APPEND_WRITTEN = "written"
STREAM_APPEND_DUPLICATE = "duplicate"
STREAM_APPEND_ERROR = "error"
_ATOMIC_DEDUPE_XADD_LUA = """
if redis.call('EXISTS', KEYS[1]) == 1 then
    return 0
end
local args = {'MAXLEN', '~', ARGV[2], '*'}
for index = 3, #ARGV do
    table.insert(args, ARGV[index])
end
redis.call('XADD', KEYS[2], unpack(args))
redis.call('SET', KEYS[1], '1', 'EX', ARGV[1])
return 1
"""


@dataclasses.dataclass(frozen=True)
class ParsedLiquidation:
    symbol: str
    side: str  # 'long' (BUY counter-order = short liquidation) or 'short'
    notional: float
    price: float
    quantity: float
    event_time_ms: int
    raw_order_quantity: float | None = None
    last_filled_quantity: float | None = None
    accumulated_filled_quantity: float | None = None
    order_status: str = ""
    execution_quantity_source: str = ""
    product_type: str = "USD_M_USDT_ASSUMED_FROM_ENDPOINT"
    exchange_event_time_ms: int | None = None


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, str):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _parse_force_order_event_detailed(
    raw: str | bytes,
) -> tuple[ParsedLiquidation | None, str | None]:
    """Parse a single Binance Futures forceOrder WSS event.

    The forceOrder@arr payload shape:
        {
          "e": "forceOrder",
          "E": <event_time_ms>,
          "o": {
              "s": "BTCUSDT",
              "S": "SELL"  | "BUY",
              "q": "<quantity>",
              "p": "<price>",
              "ap": "<avg_price>",
              "X": "FILLED",
              "T": <trade_time_ms>,
              ...
          }
        }

    Returns ``None`` for non-forceOrder events or malformed JSON.

    Side convention:
      - Binance ``S=SELL`` is a forced sell — the liquidated position
        was LONG. We map this to side ``"short"`` (the *liquidation*
        side is short on the book, but the *liquidated trader* held
        long). To avoid ambiguity, we use the *liquidation tape side*:
        ``S=SELL  -> side="short"`` (the trade hits the bid).
        ``S=BUY   -> side="long"``  (the trade hits the ask).
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", errors="replace")
        except Exception:
            return None, "invalid_encoding"
    if not isinstance(raw, str) or not raw:
        return None, "empty_payload"
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return None, "invalid_json"
    if not isinstance(d, dict):
        return None, "invalid_payload_type"
    if d.get("e") != "forceOrder":
        return None, "not_force_order"
    o = d.get("o") or {}
    if not isinstance(o, dict):
        return None, "invalid_order_payload"
    for numeric_field in ("p", "ap", "q", "l", "z"):
        if numeric_field in o and _coerce_float(o.get(numeric_field)) is None:
            return None, f"invalid_numeric_field:{numeric_field}"
    symbol = str(o.get("s") or "").upper()
    side_raw = (o.get("S") or "").upper()
    price = _coerce_float(o.get("ap") or o.get("p"))
    raw_qty = _coerce_float(o.get("q"))
    last_filled_qty = _coerce_float(o.get("l"))
    accumulated_filled_qty = _coerce_float(o.get("z"))
    order_status = str(o.get("X") or "").upper()
    event_time = o.get("T") or d.get("E")
    exchange_event_time = d.get("E") or event_time
    product_type_raw = str(
        o.get("st") or d.get("st") or o.get("contractType") or ""
    ).upper()
    if not symbol or side_raw not in ("BUY", "SELL"):
        return None, "invalid_symbol_or_side"
    if not symbol.endswith("USDT") or product_type_raw in {
        "CM", "COIN_M", "COIN-M", "COINM", "DELIVERY",
    }:
        return None, "unsupported_coin_m_quantity_semantics"
    if order_status not in {"FILLED", "PARTIALLY_FILLED"}:
        return None, "non_executed_or_unknown_status"
    if price is None or raw_qty is None or event_time is None:
        return None, "missing_price_quantity_or_time"
    if price <= 0 or raw_qty <= 0:
        return None, "invalid_numeric_value"
    if last_filled_qty is not None and last_filled_qty < 0:
        return None, "invalid_last_filled_quantity"
    if accumulated_filled_qty is not None and accumulated_filled_qty < 0:
        return None, "invalid_accumulated_filled_quantity"
    if (
        last_filled_qty is not None
        and accumulated_filled_qty is not None
        and last_filled_qty > accumulated_filled_qty
    ):
        return None, "last_filled_quantity_exceeds_accumulated"
    if accumulated_filled_qty is not None and accumulated_filled_qty > raw_qty:
        return None, "accumulated_filled_quantity_exceeds_order"
    if order_status == "PARTIALLY_FILLED":
        if accumulated_filled_qty is None:
            return None, "missing_partial_fill_accumulated_quantity"
        if accumulated_filled_qty >= raw_qty:
            return None, "partial_fill_has_terminal_accumulated_quantity"
    elif accumulated_filled_qty is not None and not math.isclose(
        accumulated_filled_qty,
        raw_qty,
        rel_tol=1e-9,
        abs_tol=1e-12,
    ):
        return None, "filled_status_without_full_accumulated_quantity"
    execution_quantity: float | None
    execution_quantity_source: str
    # ``l`` is the incremental execution represented by this snapshot;
    # ``z`` is cumulative for the order. Counting z after an earlier partial
    # snapshot would count the partial fill twice, so prefer l for every
    # status and retain z solely as raw lineage. A FILLED snapshot may fall
    # back to z only when Binance omits l entirely.
    if last_filled_qty is not None and last_filled_qty > 0:
        execution_quantity = last_filled_qty
        execution_quantity_source = "last_filled_quantity_l"
    elif (
        last_filled_qty is None
        and order_status == "FILLED"
        and accumulated_filled_qty is not None
    ):
        execution_quantity = accumulated_filled_qty
        execution_quantity_source = "accumulated_filled_quantity_z_fallback"
    else:
        execution_quantity = None
        execution_quantity_source = ""
    if execution_quantity is None or execution_quantity <= 0:
        return None, "missing_executed_quantity"
    try:
        event_time_ms = int(event_time)
        exchange_event_time_ms = int(exchange_event_time)
    except (TypeError, ValueError):
        return None, "invalid_event_time"
    notional = price * execution_quantity
    if not math.isfinite(notional) or notional <= 0:
        return None, "invalid_notional"
    side = "long" if side_raw == "BUY" else "short"
    return ParsedLiquidation(
        symbol=symbol.upper(),
        side=side,
        notional=notional,
        price=price,
        quantity=execution_quantity,
        event_time_ms=event_time_ms,
        raw_order_quantity=raw_qty,
        last_filled_quantity=last_filled_qty,
        accumulated_filled_quantity=accumulated_filled_qty,
        order_status=order_status,
        execution_quantity_source=execution_quantity_source,
        product_type=product_type_raw or "USD_M_USDT_ASSUMED_FROM_ENDPOINT",
        exchange_event_time_ms=exchange_event_time_ms,
    ), None


def parse_force_order_event(raw: str | bytes) -> ParsedLiquidation | None:
    """Parse one executed USD-M force-order snapshot, failing closed."""
    parsed, _reason = _parse_force_order_event_detailed(raw)
    return parsed


def _event_clock_rejection(event: ParsedLiquidation, *, now_ms: int) -> str | None:
    if event.event_time_ms <= 0:
        return "missing_event_time"
    if event.event_time_ms > now_ms + MAX_FUTURE_CLOCK_SKEW_MS:
        return "event_time_in_future"
    if (
        event.exchange_event_time_ms is not None
        and event.exchange_event_time_ms > now_ms + MAX_FUTURE_CLOCK_SKEW_MS
    ):
        return "exchange_event_time_in_future"
    if event.event_time_ms < now_ms - MAX_EVENT_AGE_MS:
        return "event_time_too_old"
    return None


class RetentionRing:
    """Time-windowed observed-event buffer with explicit retention coverage."""

    def __init__(
        self,
        capacity: int | None = DEFAULT_RETENTION_CAPACITY,
        window_24h_ms: int = DEFAULT_WINDOW_24H_MS,
        coverage_start_ms: int | None = None,
    ) -> None:
        if capacity is not None and capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.window_24h_ms = window_24h_ms
        self.events: Deque[ParsedLiquidation] = deque()
        self.coverage_start_ms = (
            int(time.time() * 1000) if coverage_start_ms is None else coverage_start_ms
        )
        self.retention_truncated = False
        self.hydrated = False

    def mark_hydrated(self, *, coverage_start_ms: int) -> None:
        self.coverage_start_ms = min(self.coverage_start_ms, int(coverage_start_ms))
        self.hydrated = True

    def append(self, event: ParsedLiquidation) -> None:
        if not self.events or event.event_time_ms >= self.events[-1].event_time_ms:
            # Normal WSS and XRANGE hydration path: O(1), already ordered.
            self.events.append(event)
        else:
            # Rare late frame: preserve event-time ordering without making
            # every chronological append sort the full retention window.
            ordered = list(self.events)
            insertion_index = bisect_right(
                [item.event_time_ms for item in ordered], event.event_time_ms
            )
            ordered.insert(insertion_index, event)
            self.events = deque(ordered)
        newest_event_time_ms = self.events[-1].event_time_ms
        cutoff = newest_event_time_ms - self.window_24h_ms
        while self.events and self.events[0].event_time_ms < cutoff:
            self.events.popleft()
        if self.capacity is not None:
            while len(self.events) > self.capacity:
                self.events.popleft()
                self.retention_truncated = True

    def latest(self) -> ParsedLiquidation | None:
        return self.events[-1] if self.events else None

    def aggregate(
        self,
        *,
        now_ms: int,
        window_1h_ms: int = DEFAULT_WINDOW_1H_MS,
        window_24h_ms: int | None = None,
    ) -> dict[str, Any]:
        """Compute observed aggregates without claiming complete exchange volume."""
        if window_24h_ms is None:
            window_24h_ms = self.window_24h_ms
        cutoff = now_ms - window_24h_ms
        while self.events and self.events[0].event_time_ms < cutoff:
            self.events.popleft()
        notional_1h = 0.0
        count_1h = 0
        observed_notional_window = 0.0
        observed_count_window = 0
        long_count_1h = 0
        short_count_1h = 0
        observed_long_count_window = 0
        observed_short_count_window = 0
        for ev in self.events:
            age_ms = now_ms - ev.event_time_ms
            if 0 <= age_ms <= window_1h_ms:
                notional_1h += ev.notional
                count_1h += 1
                if ev.side == "long":
                    long_count_1h += 1
                elif ev.side == "short":
                    short_count_1h += 1
            if 0 <= age_ms <= window_24h_ms:
                observed_notional_window += ev.notional
                observed_count_window += 1
                if ev.side == "long":
                    observed_long_count_window += 1
                elif ev.side == "short":
                    observed_short_count_window += 1
        direction_bias_1h = None
        total_1h_with_side = long_count_1h + short_count_1h
        if total_1h_with_side > 0:
            direction_bias_1h = (long_count_1h - short_count_1h) / total_1h_with_side
        coverage_ms = max(0, now_ms - self.coverage_start_ms)
        retention_window_complete = (
            coverage_ms >= window_24h_ms and not self.retention_truncated
        )
        one_hour_retention_complete = (
            coverage_ms >= window_1h_ms and not self.retention_truncated
        )
        # Binance's all-market feed intentionally emits at most the latest
        # snapshot per symbol each second, so complete exchange liquidation
        # volume cannot be proven even with complete local retention.
        source_capture_complete = False
        aggregate_complete = retention_window_complete and source_capture_complete
        feature_cutoff = max(
            (event.event_time_ms for event in self.events),
            default=0,
        )
        result: dict[str, Any] = {
            "semantic_kind": OBSERVED_AGGREGATE_SEMANTIC_KIND,
            "source_capture_semantics": SOURCE_CAPTURE_SEMANTICS,
            "source_capture_complete": source_capture_complete,
            "aggregate_complete": aggregate_complete,
            "downstream_contract_status": (
                "OBSERVED_ONLY_KEY_REQUIRES_COVERAGE_AWARE_CONSUMER"
            ),
            "trainer_feature_wiring_status": "NOT_WIRED_FAIL_CLOSED",
            "legacy_complete_aggregate_published": aggregate_complete,
            "observed_notional_window": observed_notional_window,
            "observed_count_window": observed_count_window,
            "observed_long_count_window": observed_long_count_window,
            "observed_short_count_window": observed_short_count_window,
            "observed_notional_1h": notional_1h,
            "observed_count_1h": count_1h,
            "observed_long_count_1h": long_count_1h,
            "observed_short_count_1h": short_count_1h,
            "observed_direction_bias_1h": direction_bias_1h,
            "as_of_ms": now_ms,
            "window_1h_ms": window_1h_ms,
            "window_duration_ms": window_24h_ms,
            "window_start_ms": now_ms - window_24h_ms,
            "window_coverage_start_ms": self.coverage_start_ms,
            "window_coverage_ms": coverage_ms,
            "one_hour_retention_complete": one_hour_retention_complete,
            "retention_window_complete": retention_window_complete,
            "retention_truncated": self.retention_truncated,
            "event_count_in_window": len(self.events),
            "event_time": feature_cutoff,
            "feature_cutoff": feature_cutoff,
        }
        if aggregate_complete:
            result.update({
                "notional_24h": observed_notional_window,
                "count_24h": observed_count_window,
            })
        return result


def liquidation_src_id(
    event: ParsedLiquidation,
    *,
    source: str = "binance_wss_forceOrder",
) -> str:
    """Stable fingerprint for one observed execution snapshot."""
    liq_side = _TAPE_SIDE_TO_LIQ_SIDE.get((event.side or "").lower(), "UNKNOWN")
    canonical = "|".join(
        str(value)
        for value in (
            source,
            event.symbol,
            event.event_time_ms,
            event.exchange_event_time_ms,
            liq_side,
            event.price,
            event.raw_order_quantity,
            event.last_filled_quantity,
            event.accumulated_filled_quantity,
            event.order_status,
            event.product_type,
        )
    )
    return f"wss:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _dedupe_key(src_id: str) -> str:
    return f"v2:liquidations:dedupe:{src_id.removeprefix('wss:')}"


def quarantine_raw_event(
    redis_client: Any,
    *,
    raw: str | bytes,
    reason: str,
    now_ms: int,
) -> bool:
    """Write a bounded, expiring diagnostic record for rejected input."""
    if redis_client is None:
        return False
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        redis_client.xadd(
            KEY_QUARANTINE_STREAM,
            {
                "reason": str(reason),
                "quarantined_at": str(int(now_ms)),
                "source": "binance_wss_forceOrder",
                "raw": str(raw)[:8000],
            },
            maxlen=DEFAULT_QUARANTINE_MAXLEN,
            approximate=True,
        )
        redis_client.expire(
            KEY_QUARANTINE_STREAM, DEFAULT_QUARANTINE_TTL_SECONDS
        )
        return True
    except Exception:
        return False


def _event_from_stream_fields(
    fields: dict[str, Any],
    *,
    now_ms: int | None = None,
) -> ParsedLiquidation | None:
    try:
        symbol = str(fields.get("symbol") or "").upper()
        liq_side = str(fields.get("side") or "").upper()
        tape_side = {"LONG_LIQ": "short", "SHORT_LIQ": "long"}.get(liq_side)
        if not symbol.endswith("USDT") or tape_side is None:
            return None
        if str(fields.get("source") or "") != "binance_wss_forceOrder":
            return None
        if str(fields.get("semantic_kind") or "") != OBSERVED_AGGREGATE_SEMANTIC_KIND:
            return None
        product_type = str(fields.get("product_type") or "").upper()
        if not product_type.startswith("USD_M"):
            return None
        event_time_ms = int(fields.get("event_time") or fields.get("ts") or 0)
        exchange_event_time_ms = int(
            fields.get("exchange_event_time") or event_time_ms
        )
        feature_cutoff_ms = int(fields.get("feature_cutoff") or 0)
        ingested_at_ms = int(fields.get("ingested_at") or fields.get("ingest_ts") or 0)
        available_at_ms = int(fields.get("available_at") or 0)
        generated_at_ms = int(fields.get("generated_at") or 0)
        price = _coerce_float(fields.get("price"))
        quantity = _coerce_float(fields.get("qty"))
        notional = _coerce_float(fields.get("notional"))
        if price is None or quantity is None or notional is None:
            return None
        if min(event_time_ms, exchange_event_time_ms, price, quantity, notional) <= 0:
            return None
        if not (
            event_time_ms <= feature_cutoff_ms <= ingested_at_ms <= available_at_ms
            and generated_at_ms >= ingested_at_ms
        ):
            return None
        if now_ms is not None and max(available_at_ms, generated_at_ms) > int(now_ms):
            return None
        raw_order_quantity = _coerce_float(fields.get("raw_order_qty"))
        last_filled_quantity = _coerce_float(fields.get("last_filled_qty"))
        accumulated_filled_quantity = _coerce_float(
            fields.get("accumulated_filled_qty")
        )
        optional_quantities = (
            raw_order_quantity,
            last_filled_quantity,
            accumulated_filled_quantity,
        )
        if any(value is not None and value < 0 for value in optional_quantities):
            return None
        if not math.isclose(notional, price * quantity, rel_tol=1e-9, abs_tol=1e-8):
            return None
        return ParsedLiquidation(
            symbol=symbol,
            side=tape_side,
            notional=notional,
            price=price,
            quantity=quantity,
            event_time_ms=event_time_ms,
            raw_order_quantity=raw_order_quantity,
            last_filled_quantity=last_filled_quantity,
            accumulated_filled_quantity=accumulated_filled_quantity,
            order_status=str(fields.get("order_status") or "HYDRATED_OBSERVED"),
            execution_quantity_source=str(
                fields.get("execution_quantity_source") or "canonical_stream_qty"
            ),
            product_type=product_type,
            exchange_event_time_ms=exchange_event_time_ms,
        )
    except (TypeError, ValueError):
        return None


def hydrate_retention_rings(
    redis_client: Any,
    *,
    rings: dict[str, RetentionRing],
    symbols: tuple[str, ...],
    now_ms: int | None = None,
) -> dict[str, int | bool]:
    """Hydrate the rolling aggregate from retained canonical observations."""
    observed_now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    cutoff_ms = observed_now_ms - DEFAULT_WINDOW_24H_MS
    accepted_symbols = {symbol.upper() for symbol in symbols}
    for symbol in accepted_symbols:
        rings.setdefault(symbol, RetentionRing(coverage_start_ms=observed_now_ms))
    if redis_client is None:
        return {"hydrated": False, "events_loaded": 0}
    try:
        first_entries = redis_client.xrange(
            KEY_EVENTS_STREAM, min="-", max="+", count=1
        )
        coverage_start_ms = observed_now_ms
        if first_entries:
            coverage_start_ms = int(str(first_entries[0][0]).split("-", 1)[0])
        entries = redis_client.xrange(
            KEY_EVENTS_STREAM, min=f"{cutoff_ms}-0", max="+"
        )
    except Exception:
        for ring in rings.values():
            ring.hydrated = True
        return {"hydrated": False, "events_loaded": 0}

    for ring in rings.values():
        ring.mark_hydrated(coverage_start_ms=coverage_start_ms)
    seen: set[str] = set()
    loaded = 0
    for _stream_id, raw_fields in entries:
        fields = dict(raw_fields)
        event = _event_from_stream_fields(fields, now_ms=observed_now_ms)
        if event is None or event.symbol not in accepted_symbols:
            continue
        fingerprint = str(fields.get("src_id") or liquidation_src_id(event))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        rings[event.symbol].append(event)
        loaded += 1
    return {
        "hydrated": True,
        "events_loaded": loaded,
        "retention_window_complete": coverage_start_ms <= cutoff_ms,
    }


def _safe_redis_set(redis_client: Any, key: str, value: str, ex: int | None = None) -> bool:
    """Refuse any write whose key does not start with v2: prefix."""
    if redis_client is None:
        return False
    if not isinstance(key, str) or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        if ex is not None:
            redis_client.set(key, value, ex=int(ex))
        else:
            redis_client.set(key, value)
        return True
    except Exception:
        return False


def append_event_to_stream_once(
    redis_client: Any,
    *,
    symbol: str,
    latest_event: ParsedLiquidation,
    source: str = "binance_wss_forceOrder",
    maxlen: int = DEFAULT_EVENTS_STREAM_MAXLEN,
    ingest_ts_ms: int | None = None,
    dedupe_ttl_seconds: int = DEFAULT_DEDUPE_TTL_SECONDS,
) -> str:
    """Atomically deduplicate and XADD one real parsed observation.

    Fields match the contract the bridge/levels engine consumes:
    ``symbol``, ``ts`` (ms), ``ingest_ts`` (ms), ``side``
    (LONG_LIQ/SHORT_LIQ), ``price``, ``qty``, ``notional``, ``source``,
    ``src_key``, ``src_id``. We forward only events that the WSS parser
    already accepted; we never synthesize an event here.
    """
    if redis_client is None:
        return STREAM_APPEND_ERROR
    liq_side = _TAPE_SIDE_TO_LIQ_SIDE.get((latest_event.side or "").lower())
    if liq_side is None:
        return STREAM_APPEND_ERROR
    src_id = liquidation_src_id(latest_event, source=source)
    observed_ingest_ts = (
        int(time.time() * 1000) if ingest_ts_ms is None else int(ingest_ts_ms)
    )
    fields = {
        "symbol": latest_event.symbol,
        "ts": str(int(latest_event.event_time_ms)),
        "event_time": str(int(latest_event.event_time_ms)),
        "ingest_ts": str(observed_ingest_ts),
        "ingested_at": str(observed_ingest_ts),
        "available_at": str(observed_ingest_ts),
        "generated_at": str(observed_ingest_ts),
        "feature_cutoff": str(int(latest_event.event_time_ms)),
        "side": liq_side,
        "price": str(latest_event.price),
        "qty": str(latest_event.quantity),
        "raw_order_qty": (
            "" if latest_event.raw_order_quantity is None
            else str(latest_event.raw_order_quantity)
        ),
        "last_filled_qty": (
            "" if latest_event.last_filled_quantity is None
            else str(latest_event.last_filled_quantity)
        ),
        "accumulated_filled_qty": str(
            "" if latest_event.accumulated_filled_quantity is None
            else latest_event.accumulated_filled_quantity
        ),
        "order_status": latest_event.order_status,
        "execution_quantity_source": latest_event.execution_quantity_source,
        "product_type": latest_event.product_type,
        "exchange_event_time": str(
            latest_event.exchange_event_time_ms or latest_event.event_time_ms
        ),
        "notional": str(latest_event.notional),
        "source": source,
        "semantic_kind": OBSERVED_AGGREGATE_SEMANTIC_KIND,
        "source_capture_semantics": SOURCE_CAPTURE_SEMANTICS,
        "source_capture_complete": "false",
        "src_key": KEY_PER_SYMBOL_TEMPLATE.format(symbol=symbol),
        "src_id": src_id,
    }
    flat_fields: list[str] = []
    for key, value in fields.items():
        flat_fields.extend((str(key), str(value)))
    try:
        result = redis_client.eval(
            _ATOMIC_DEDUPE_XADD_LUA,
            2,
            _dedupe_key(src_id),
            KEY_EVENTS_STREAM,
            str(int(dedupe_ttl_seconds)),
            str(int(maxlen)),
            *flat_fields,
        )
        return STREAM_APPEND_WRITTEN if int(result) == 1 else STREAM_APPEND_DUPLICATE
    except Exception:
        return STREAM_APPEND_ERROR


def write_event_to_stream(
    redis_client: Any,
    *,
    symbol: str,
    latest_event: ParsedLiquidation,
    source: str = "binance_wss_forceOrder",
    maxlen: int = DEFAULT_EVENTS_STREAM_MAXLEN,
    ingest_ts_ms: int | None = None,
) -> bool:
    return append_event_to_stream_once(
        redis_client,
        symbol=symbol,
        latest_event=latest_event,
        source=source,
        maxlen=maxlen,
        ingest_ts_ms=ingest_ts_ms,
    ) == STREAM_APPEND_WRITTEN


def write_event_to_redis(
    redis_client: Any,
    *,
    symbol: str,
    latest_event: ParsedLiquidation,
    aggregate: dict[str, Any],
    ttl_seconds: int = 3600,
    ingest_ts_ms: int | None = None,
    stream_already_written: bool = False,
) -> dict[str, bool]:
    """Write the per-symbol latest event + aggregate to V2 Redis only.

    Also XADDs the same parsed event into ``v2:liquidations:events`` so
    the levels engine (which xreadgroups that stream) populates the
    ``v2:unified_features:*`` liquidation fields without a separate
    bridge step.
    """
    observed_ingest_ts = (
        int(time.time() * 1000) if ingest_ts_ms is None else int(ingest_ts_ms)
    )
    stream_written = stream_already_written or write_event_to_stream(
        redis_client,
        symbol=symbol,
        latest_event=latest_event,
        ingest_ts_ms=observed_ingest_ts,
    )
    latest_payload = {
        "symbol": latest_event.symbol,
        "side": latest_event.side,
        "notional": latest_event.notional,
        "price": latest_event.price,
        "quantity": latest_event.quantity,
        "raw_order_quantity": latest_event.raw_order_quantity,
        "last_filled_quantity": latest_event.last_filled_quantity,
        "accumulated_filled_quantity": latest_event.accumulated_filled_quantity,
        "order_status": latest_event.order_status,
        "execution_quantity_source": latest_event.execution_quantity_source,
        "product_type": latest_event.product_type,
        "exchange_event_time_ms": latest_event.exchange_event_time_ms,
        "event_time_ms": latest_event.event_time_ms,
        "event_time": latest_event.event_time_ms,
        "ingested_at": observed_ingest_ts,
        "available_at": observed_ingest_ts,
        "generated_at": observed_ingest_ts,
        "feature_cutoff": latest_event.event_time_ms,
        "semantic_kind": OBSERVED_AGGREGATE_SEMANTIC_KIND,
        "source_capture_semantics": SOURCE_CAPTURE_SEMANTICS,
        "source_capture_complete": False,
        "generated_utc": _utc_iso(),
    }
    aggregate_feature_cutoff = int(
        aggregate.get("feature_cutoff") or latest_event.event_time_ms
    )
    aggregate_payload = {
        **aggregate,
        "symbol": latest_event.symbol,
        "event_time": aggregate_feature_cutoff,
        "ingested_at": observed_ingest_ts,
        "available_at": observed_ingest_ts,
        "generated_at": observed_ingest_ts,
        "feature_cutoff": aggregate_feature_cutoff,
        "generated_utc": _utc_iso(),
    }
    writes = {
        KEY_EVENTS_STREAM: stream_written,
        KEY_LATEST_TEMPLATE.format(symbol=symbol): _safe_redis_set(
            redis_client,
            KEY_LATEST_TEMPLATE.format(symbol=symbol),
            json.dumps(latest_payload),
            ex=ttl_seconds,
        ),
        KEY_OBSERVED_AGGREGATE_TEMPLATE.format(symbol=symbol): _safe_redis_set(
            redis_client,
            KEY_OBSERVED_AGGREGATE_TEMPLATE.format(symbol=symbol),
            json.dumps(aggregate_payload),
            ex=ttl_seconds,
        ),
        KEY_PER_SYMBOL_TEMPLATE.format(symbol=symbol): _safe_redis_set(
            redis_client,
            KEY_PER_SYMBOL_TEMPLATE.format(symbol=symbol),
            json.dumps(latest_payload),
            ex=ttl_seconds,
        ),
    }
    if aggregate_payload.get("aggregate_complete") is True:
        writes[KEY_AGGREGATE_TEMPLATE.format(symbol=symbol)] = _safe_redis_set(
            redis_client,
            KEY_AGGREGATE_TEMPLATE.format(symbol=symbol),
            json.dumps(aggregate_payload),
            ex=ttl_seconds,
        )
    return writes


DEFAULT_HEARTBEAT_TTL_SECONDS = 180
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60


def write_heartbeat(
    redis_client: Any,
    payload: dict[str, Any],
    *,
    ttl_seconds: int = DEFAULT_HEARTBEAT_TTL_SECONDS,
) -> bool:
    return _safe_redis_set(
        redis_client, KEY_HEARTBEAT, json.dumps(payload), ex=int(ttl_seconds)
    )


def opt_in_enabled() -> bool:
    return os.environ.get(OPT_IN_ENV_VAR) == "true"


def compute_backoff_seconds(
    attempt: int,
    *,
    initial: float = DEFAULT_BACKOFF_INITIAL_SECONDS,
    cap: float = DEFAULT_BACKOFF_CAP_SECONDS,
) -> float:
    """Exponential backoff with cap. attempt=1 -> initial; doubles each
    subsequent attempt up to cap.
    """
    if attempt < 1:
        return 0.0
    if initial <= 0:
        return min(1.0, cap)
    # Once the delay has reached the cap, do not keep exponentiating. Long
    # network outages can produce hundreds of attempts; 2**attempt eventually
    # overflows float conversion even though the result would be capped.
    capped_after = int(math.ceil(math.log(cap / initial, 2))) + 1 if cap > initial else 1
    if attempt >= capped_after:
        return cap
    delay = initial * (2 ** (attempt - 1))
    return min(delay, cap)


@dataclasses.dataclass
class ConsumeStats:
    events_received: int = 0
    events_parsed: int = 0
    events_filtered_by_symbol: int = 0
    events_written: int = 0
    events_deduplicated: int = 0
    events_quarantined: int = 0
    parse_errors: int = 0
    redis_write_failures: int = 0
    reconnect_count: int = 0
    last_event_utc: str | None = None


def _publish_session_stats(stats_sink: dict[str, Any] | None, stats: ConsumeStats) -> None:
    if stats_sink is None:
        return
    stats_sink["stream_connected"] = True
    stats_sink["current_session_events_received"] = stats.events_received
    stats_sink["current_session_events_parsed"] = stats.events_parsed
    stats_sink["current_session_events_filtered_by_symbol"] = (
        stats.events_filtered_by_symbol
    )
    stats_sink["current_session_events_written"] = stats.events_written
    stats_sink["current_session_events_deduplicated"] = stats.events_deduplicated
    stats_sink["current_session_events_quarantined"] = stats.events_quarantined
    stats_sink["current_session_parse_errors"] = stats.parse_errors
    stats_sink["current_session_redis_write_failures"] = stats.redis_write_failures
    if stats.last_event_utc:
        stats_sink["last_event_utc"] = stats.last_event_utc


async def consume_events(
    *,
    event_source: Callable[[], Awaitable[Iterable[str]]],
    redis_client: Any,
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    max_events: int | None = None,
    now_ms_func: Callable[[], int] = lambda: int(time.time() * 1000),
    rings: dict[str, RetentionRing] | None = None,
) -> ConsumeStats:
    """Consume events from a single pulled batch (no reconnect loop here).

    Reconnect/backoff lives in the WSS connection wrapper; this function
    is exposed as the deterministic, testable inner loop.
    """
    if rings is None:
        rings = {s.upper(): RetentionRing() for s in symbols}
    stats = ConsumeStats()
    raw_events = await event_source()
    accepted_symbols = {s.upper() for s in symbols}
    for raw in raw_events:
        stats.events_received += 1
        if max_events is not None and stats.events_written >= max_events:
            break
        parsed, rejection = _parse_force_order_event_detailed(raw)
        if parsed is None:
            stats.parse_errors += 1
            if quarantine_raw_event(
                redis_client,
                raw=raw,
                reason=rejection or "unknown_parse_rejection",
                now_ms=now_ms_func(),
            ):
                stats.events_quarantined += 1
            continue
        stats.events_parsed += 1
        if parsed.symbol not in accepted_symbols:
            stats.events_filtered_by_symbol += 1
            continue
        observed_now_ms = now_ms_func()
        clock_rejection = _event_clock_rejection(parsed, now_ms=observed_now_ms)
        if clock_rejection is not None:
            stats.parse_errors += 1
            if quarantine_raw_event(
                redis_client,
                raw=raw,
                reason=clock_rejection,
                now_ms=observed_now_ms,
            ):
                stats.events_quarantined += 1
            continue
        append_status = append_event_to_stream_once(
            redis_client,
            symbol=parsed.symbol,
            latest_event=parsed,
            ingest_ts_ms=observed_now_ms,
        )
        if append_status == STREAM_APPEND_ERROR:
            stats.redis_write_failures += 1
            continue
        if append_status == STREAM_APPEND_DUPLICATE:
            stats.events_deduplicated += 1
            continue
        ring = rings.setdefault(parsed.symbol, RetentionRing())
        ring.append(parsed)
        agg = ring.aggregate(now_ms=observed_now_ms)
        latest_for_payload = ring.latest() or parsed
        result = write_event_to_redis(
            redis_client,
            symbol=parsed.symbol,
            latest_event=latest_for_payload,
            aggregate=agg,
            ingest_ts_ms=observed_now_ms,
            stream_already_written=True,
        )
        if all(result.values()):
            stats.events_written += 1
            stats.last_event_utc = _utc_iso()
        else:
            stats.redis_write_failures += 1
    return stats


async def open_wss_connection(url: str):  # pragma: no cover - thin wrapper
    """Real WSS open. Wrapped here so tests can monkey-patch."""
    import websockets  # type: ignore

    return await websockets.connect(url)


async def run_wss_session(
    *,
    url: str = DEFAULT_WSS_URL,
    redis_client: Any,
    symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
    max_seconds: float | None = None,
    max_events: int | None = None,
    rings: dict[str, RetentionRing] | None = None,
    open_connection: Callable[[str], Awaitable[Any]] | None = None,
    stats_sink: dict[str, Any] | None = None,
) -> ConsumeStats:  # pragma: no cover - integration path; tested via consume_events
    """One bounded WSS session. Yields after either ``max_seconds`` or
    ``max_events`` whichever comes first. Returns the consume stats.
    """
    if rings is None:
        rings = {s.upper(): RetentionRing() for s in symbols}
    if any(not ring.hydrated for ring in rings.values()):
        hydrate_retention_rings(
            redis_client,
            rings=rings,
            symbols=symbols,
        )
    if open_connection is None:
        open_connection = open_wss_connection
    accepted_symbols = {s.upper() for s in symbols}
    stats = ConsumeStats()
    start_ts = time.monotonic()
    ws = await open_connection(url)
    stats_sink_current = stats_sink
    if stats_sink_current is not None:
        stats_sink_current["current_session_started_utc"] = _utc_iso()
        stats_sink_current["last_frame_utc"] = None
    _publish_session_stats(stats_sink_current, stats)
    try:
        while True:
            if max_seconds is not None and (time.monotonic() - start_ts) >= max_seconds:
                break
            if max_events is not None and stats.events_written >= max_events:
                break
            try:
                if max_seconds is not None:
                    remaining = max_seconds - (time.monotonic() - start_ts)
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, remaining))
                else:
                    raw = await ws.recv()
            except asyncio.TimeoutError:
                break
            stats.events_received += 1
            if stats_sink_current is not None:
                stats_sink_current["last_frame_utc"] = _utc_iso()
            parsed, rejection = _parse_force_order_event_detailed(raw)
            if parsed is None:
                stats.parse_errors += 1
                if quarantine_raw_event(
                    redis_client,
                    raw=raw,
                    reason=rejection or "unknown_parse_rejection",
                    now_ms=int(time.time() * 1000),
                ):
                    stats.events_quarantined += 1
                _publish_session_stats(stats_sink_current, stats)
                continue
            stats.events_parsed += 1
            if parsed.symbol not in accepted_symbols:
                stats.events_filtered_by_symbol += 1
                _publish_session_stats(stats_sink_current, stats)
                continue
            observed_now_ms = int(time.time() * 1000)
            clock_rejection = _event_clock_rejection(
                parsed, now_ms=observed_now_ms
            )
            if clock_rejection is not None:
                stats.parse_errors += 1
                if quarantine_raw_event(
                    redis_client,
                    raw=raw,
                    reason=clock_rejection,
                    now_ms=observed_now_ms,
                ):
                    stats.events_quarantined += 1
                _publish_session_stats(stats_sink_current, stats)
                continue
            append_status = append_event_to_stream_once(
                redis_client,
                symbol=parsed.symbol,
                latest_event=parsed,
                ingest_ts_ms=observed_now_ms,
            )
            if append_status == STREAM_APPEND_ERROR:
                stats.redis_write_failures += 1
                _publish_session_stats(stats_sink_current, stats)
                continue
            if append_status == STREAM_APPEND_DUPLICATE:
                stats.events_deduplicated += 1
                _publish_session_stats(stats_sink_current, stats)
                continue
            ring = rings.setdefault(parsed.symbol, RetentionRing())
            ring.append(parsed)
            agg = ring.aggregate(now_ms=observed_now_ms)
            latest_for_payload = ring.latest() or parsed
            result = write_event_to_redis(
                redis_client,
                symbol=parsed.symbol,
                latest_event=latest_for_payload,
                aggregate=agg,
                ingest_ts_ms=observed_now_ms,
                stream_already_written=True,
            )
            if all(result.values()):
                stats.events_written += 1
                stats.last_event_utc = _utc_iso()
            else:
                stats.redis_write_failures += 1
            _publish_session_stats(stats_sink_current, stats)
    finally:
        if stats_sink_current is not None:
            stats_sink_current["stream_connected"] = False
        try:
            await ws.close()
        except Exception:
            pass
    return stats
