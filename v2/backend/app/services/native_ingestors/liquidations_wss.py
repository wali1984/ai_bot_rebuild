"""V2-native paper/shadow Binance Futures liquidation WSS client.

Connects to the routed Binance Futures market stream
``wss://fstream.binance.com/market/ws/!forceOrder@arr`` (public, no
credentials), parses ``forceOrder`` events, maintains a bounded
in-memory retention ring per symbol, and publishes:

- ``v2:market:liquidations:latest:{symbol}``   — last event
- ``v2:market:liquidations:aggregate:{symbol}`` — rolling 1h/24h aggregate
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
import dataclasses
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
KEY_PER_SYMBOL_TEMPLATE = "v2:market:liquidations:{symbol}"
KEY_HEARTBEAT = "v2:market:liquidations:heartbeat"

# Canonical V2 liquidation events stream consumed by
# v2/legacy_owned_runtime/ingest/liquidation_levels_engine.py via
# xreadgroup. WSS forwards each REAL parsed forceOrder event into this
# stream so the levels engine can populate v2:unified_features:* hashes.
# We never synthesize events here; if WSS receives no events the stream
# stays empty.
KEY_EVENTS_STREAM = "v2:liquidations:events"
DEFAULT_EVENTS_STREAM_MAXLEN = 10000

# Side mapping from WSS tape-side ("long"/"short") to the bridge/levels
# engine semantic side ("LONG_LIQ"/"SHORT_LIQ"). WSS uses tape-side
# (trade hit ask = "long"); bridge/levels use the LIQUIDATED-POSITION
# side. The two are inverted: a BUY counter-order liquidates a SHORT.
_TAPE_SIDE_TO_LIQ_SIDE = {
    "long": "SHORT_LIQ",
    "short": "LONG_LIQ",
}

DEFAULT_RETENTION_CAPACITY = 200  # max events kept per symbol in memory
DEFAULT_WINDOW_1H_MS = 60 * 60 * 1000
DEFAULT_WINDOW_24H_MS = 24 * 60 * 60 * 1000
DEFAULT_BACKOFF_INITIAL_SECONDS = 1.0
DEFAULT_BACKOFF_CAP_SECONDS = 30.0

OPT_IN_ENV_VAR = "V2_LIQUIDATION_WSS_OPT_IN"


@dataclasses.dataclass(frozen=True)
class ParsedLiquidation:
    symbol: str
    side: str  # 'long' (BUY counter-order = short liquidation) or 'short'
    notional: float
    price: float
    quantity: float
    event_time_ms: int


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def parse_force_order_event(raw: str | bytes) -> ParsedLiquidation | None:
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
            return None
    if not isinstance(raw, str) or not raw:
        return None
    try:
        d = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    if d.get("e") != "forceOrder":
        return None
    o = d.get("o") or {}
    if not isinstance(o, dict):
        return None
    symbol = o.get("s")
    side_raw = (o.get("S") or "").upper()
    price = _coerce_float(o.get("ap") or o.get("p"))
    qty = _coerce_float(o.get("q"))
    event_time = d.get("E") or o.get("T")
    if not symbol or side_raw not in ("BUY", "SELL"):
        return None
    if price is None or qty is None or event_time is None:
        return None
    try:
        event_time_ms = int(event_time)
    except (TypeError, ValueError):
        return None
    notional = price * qty
    side = "long" if side_raw == "BUY" else "short"
    return ParsedLiquidation(
        symbol=symbol.upper(),
        side=side,
        notional=notional,
        price=price,
        quantity=qty,
        event_time_ms=event_time_ms,
    )


class RetentionRing:
    """Bounded in-memory ring of liquidation events per symbol.

    - Drops oldest events when capacity exceeded.
    - Drops events older than ``max_age_ms`` from windowed aggregates.
    """

    def __init__(
        self,
        capacity: int = DEFAULT_RETENTION_CAPACITY,
        window_24h_ms: int = DEFAULT_WINDOW_24H_MS,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.window_24h_ms = window_24h_ms
        self.events: Deque[ParsedLiquidation] = deque(maxlen=capacity)

    def append(self, event: ParsedLiquidation) -> None:
        self.events.append(event)

    def latest(self) -> ParsedLiquidation | None:
        return self.events[-1] if self.events else None

    def aggregate(
        self,
        *,
        now_ms: int,
        window_1h_ms: int = DEFAULT_WINDOW_1H_MS,
        window_24h_ms: int | None = None,
    ) -> dict[str, Any]:
        """Compute notional aggregates over rolling windows."""
        if window_24h_ms is None:
            window_24h_ms = self.window_24h_ms
        notional_1h = 0.0
        count_1h = 0
        notional_24h = 0.0
        count_24h = 0
        long_count_1h = 0
        short_count_1h = 0
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
                notional_24h += ev.notional
                count_24h += 1
        direction_bias_1h = None
        total_1h_with_side = long_count_1h + short_count_1h
        if total_1h_with_side > 0:
            direction_bias_1h = (long_count_1h - short_count_1h) / total_1h_with_side
        return {
            "notional_1h": notional_1h,
            "count_1h": count_1h,
            "notional_24h": notional_24h,
            "count_24h": count_24h,
            "long_count_1h": long_count_1h,
            "short_count_1h": short_count_1h,
            "direction_bias_1h": direction_bias_1h,
            "as_of_ms": now_ms,
            "window_1h_ms": window_1h_ms,
            "window_24h_ms": window_24h_ms,
            "event_count_in_ring": len(self.events),
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


def write_event_to_stream(
    redis_client: Any,
    *,
    symbol: str,
    latest_event: ParsedLiquidation,
    source: str = "binance_wss_forceOrder",
    maxlen: int = DEFAULT_EVENTS_STREAM_MAXLEN,
) -> bool:
    """XADD a single REAL parsed event into the canonical V2 stream.

    Fields match the contract the bridge/levels engine consumes:
    ``symbol``, ``ts`` (ms), ``ingest_ts`` (ms), ``side``
    (LONG_LIQ/SHORT_LIQ), ``price``, ``qty``, ``notional``, ``source``,
    ``src_key``, ``src_id``. We forward only events that the WSS parser
    already accepted; we never synthesize an event here.
    """
    if redis_client is None:
        return False
    liq_side = _TAPE_SIDE_TO_LIQ_SIDE.get((latest_event.side or "").lower())
    if liq_side is None:
        return False
    src_id = (
        f"wss:{latest_event.symbol}:{int(latest_event.event_time_ms)}"
        f":{liq_side}:{latest_event.price}:{latest_event.quantity}"
    )
    fields = {
        "symbol": latest_event.symbol,
        "ts": str(int(latest_event.event_time_ms)),
        "ingest_ts": str(int(time.time() * 1000)),
        "side": liq_side,
        "price": str(latest_event.price),
        "qty": str(latest_event.quantity),
        "notional": str(latest_event.notional),
        "source": source,
        "src_key": KEY_PER_SYMBOL_TEMPLATE.format(symbol=symbol),
        "src_id": src_id,
    }
    try:
        redis_client.xadd(
            KEY_EVENTS_STREAM,
            fields,
            maxlen=int(maxlen),
            approximate=True,
        )
        return True
    except Exception:
        return False


def write_event_to_redis(
    redis_client: Any,
    *,
    symbol: str,
    latest_event: ParsedLiquidation,
    aggregate: dict[str, Any],
    ttl_seconds: int = 3600,
) -> dict[str, bool]:
    """Write the per-symbol latest event + aggregate to V2 Redis only.

    Also XADDs the same parsed event into ``v2:liquidations:events`` so
    the levels engine (which xreadgroups that stream) populates the
    ``v2:unified_features:*`` liquidation fields without a separate
    bridge step.
    """
    _ = write_event_to_stream(
        redis_client,
        symbol=symbol,
        latest_event=latest_event,
    )
    latest_payload = {
        "symbol": latest_event.symbol,
        "side": latest_event.side,
        "notional": latest_event.notional,
        "price": latest_event.price,
        "quantity": latest_event.quantity,
        "event_time_ms": latest_event.event_time_ms,
        "generated_utc": _utc_iso(),
    }
    aggregate_payload = {
        **aggregate,
        "symbol": latest_event.symbol,
        "generated_utc": _utc_iso(),
    }
    return {
        KEY_LATEST_TEMPLATE.format(symbol=symbol): _safe_redis_set(
            redis_client,
            KEY_LATEST_TEMPLATE.format(symbol=symbol),
            json.dumps(latest_payload),
            ex=ttl_seconds,
        ),
        KEY_AGGREGATE_TEMPLATE.format(symbol=symbol): _safe_redis_set(
            redis_client,
            KEY_AGGREGATE_TEMPLATE.format(symbol=symbol),
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
        parsed = parse_force_order_event(raw)
        if parsed is None:
            stats.parse_errors += 1
            continue
        stats.events_parsed += 1
        if parsed.symbol not in accepted_symbols:
            stats.events_filtered_by_symbol += 1
            continue
        ring = rings.setdefault(parsed.symbol, RetentionRing())
        ring.append(parsed)
        agg = ring.aggregate(now_ms=now_ms_func())
        result = write_event_to_redis(
            redis_client,
            symbol=parsed.symbol,
            latest_event=parsed,
            aggregate=agg,
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
            parsed = parse_force_order_event(raw)
            if parsed is None:
                stats.parse_errors += 1
                _publish_session_stats(stats_sink_current, stats)
                continue
            stats.events_parsed += 1
            if parsed.symbol not in accepted_symbols:
                stats.events_filtered_by_symbol += 1
                _publish_session_stats(stats_sink_current, stats)
                continue
            ring = rings.setdefault(parsed.symbol, RetentionRing())
            ring.append(parsed)
            agg = ring.aggregate(now_ms=int(time.time() * 1000))
            result = write_event_to_redis(
                redis_client,
                symbol=parsed.symbol,
                latest_event=parsed,
                aggregate=agg,
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
