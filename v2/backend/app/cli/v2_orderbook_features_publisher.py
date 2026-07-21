"""Canonical direct-orderbook feature-pair supervisor (paper-safe).

The direct recorder now atomically owns both
``v2:orderbook:depth:binance:{symbol}`` and
``v2:orderbook:features:binance:{symbol}``.  An older version of this worker
attempted to derive the feature key from generic market-book echoes.  That is
no longer safe: overwriting the direct feature half would break the exact
schema, sequence, clock, and source pairing required by authenticated cost
evidence.  This worker therefore validates the current pair and writes only a
bounded summary.  It never writes a per-symbol feature key.

Inputs (already-ingested raw books only; no exchange calls of any kind):
  * ``v2:orderbook:depth:binance:{symbol}`` (canonical direct recorder)
  * ``v2:orderbook:features:binance:{symbol}`` (same canonical recorder)

Safety:
  * writes only ``v2:orderbook:features:summary``
  * exact pair and clock checks keep a frozen or split update from being
    reported healthy
  * never places/cancels orders, never mutates leverage/margin,
    never touches legacy Redis
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Mapping

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

V2_PREFIX = "v2:"
SUMMARY_KEY = "v2:orderbook:features:summary"
LIVE_GATE = "blocked_human_only"
SCHEMA_VERSION = "v2_orderbook_features_v1"
WORKER_ID = "v2_orderbook_features_publisher"
DEFAULT_INTERVAL_SECONDS = 20
DEFAULT_TTL_SECONDS = 900
# Books for WSS-uncovered symbols refresh via the budget-rotated REST
# gap-fill (~every few minutes/symbol under the shared 120/min budget).
# ``update_age_ms`` in the payload carries the true age, so a wider admission
# gate stays honest — readers see exactly how old the book was.
DEFAULT_MAX_BOOK_AGE_SECONDS = 900.0
# Reference marketable notional for the price-impact estimate (USD).
IMPACT_REFERENCE_NOTIONAL_USD = 10_000.0
DIRECT_DEPTH_SCHEMA = "direct_orderbook_depth_v1"
DIRECT_FEATURES_SCHEMA = "direct_orderbook_features_v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _finite(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _redis_client() -> Any:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        url = os.environ.get("V2_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2.0, socket_timeout=5.0)
        client.ping()
        return client
    except Exception:
        return None


def _safe_get_json(client: Any, key: str) -> Any:
    if client is None or not key.startswith(V2_PREFIX):
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _safe_set_json(client: Any, key: str, payload: Mapping[str, Any], *, ttl_seconds: int) -> bool:
    if client is None or key != SUMMARY_KEY:
        return False
    try:
        client.set(key, json.dumps(dict(payload), separators=(",", ":"), default=str), ex=int(ttl_seconds))
        return True
    except Exception:
        return False


def _parse_levels(rows: Any, max_levels: int = 25) -> list[tuple[float, float]]:
    levels: list[tuple[float, float]] = []
    if not isinstance(rows, list):
        return levels
    for row in rows[:max_levels]:
        if isinstance(row, Mapping):
            px = _finite(row.get("price") or row.get("p"))
            qty = _finite(row.get("qty") or row.get("quantity") or row.get("size") or row.get("q"))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            px = _finite(row[0])
            qty = _finite(row[1])
        else:
            px = qty = None
        if px is not None and qty is not None and px > 0 and qty >= 0:
            levels.append((px, qty))
    return levels


def _timestamp_ms(value: Any) -> int | None:
    """Parse one finite UTC timestamp without conflating event/availability clocks."""

    numeric = _finite(value)
    if numeric is not None and numeric > 0:
        # Binance event clocks are normally epoch milliseconds.  Accept epoch
        # seconds from other already-ingested sources, but normalize once here.
        if numeric < 100_000_000_000:
            numeric *= 1000.0
        return int(numeric)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _book_event_ms(book: Mapping[str, Any]) -> int | None:
    for field in ("E", "event_time", "T", "transaction_time"):
        if (parsed := _timestamp_ms(book.get(field))) is not None:
            return parsed
    return None


def _received_ms(book: Mapping[str, Any]) -> int | None:
    for field in ("available_at", "received_at", "fetched_utc"):
        if (parsed := _timestamp_ms(book.get(field))) is not None:
            return parsed
    return None


def _depth_usd(levels: list[tuple[float, float]], count: int) -> float | None:
    if not levels:
        return None
    return sum(px * qty for px, qty in levels[:count])


def _price_impact_bps(levels: list[tuple[float, float]], mid: float, notional_usd: float) -> float | None:
    """Bps cost (vs mid) of walking one side of the book for ``notional_usd``.

    Honest-missing when the visible book cannot absorb the reference notional.
    """
    if not levels or mid <= 0 or notional_usd <= 0:
        return None
    remaining = notional_usd
    cost = 0.0
    filled = 0.0
    for px, qty in levels:
        level_notional = px * qty
        take = min(remaining, level_notional)
        if px > 0:
            filled += take / px
            cost += take
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0 or filled <= 0:
        return None
    vwap_fill = cost / filled
    return abs(vwap_fill - mid) / mid * 10_000.0


def derive_orderbook_features(symbol: str, book: Mapping[str, Any], *, source_key: str) -> dict[str, Any] | None:
    bids = _parse_levels(book.get("bids"))
    asks = _parse_levels(book.get("asks"))
    if not bids or not asks:
        return None
    best_bid_px, best_bid_qty = bids[0]
    best_ask_px, best_ask_qty = asks[0]
    if best_bid_px <= 0 or best_ask_px <= 0 or best_ask_px < best_bid_px:
        return None
    mid = (best_bid_px + best_ask_px) / 2.0
    spread_bps = (best_ask_px - best_bid_px) / mid * 10_000.0 if mid > 0 else None
    depth_5_bid = _depth_usd(bids, 5)
    depth_5_ask = _depth_usd(asks, 5)
    depth_20_bid = _depth_usd(bids, 20)
    depth_20_ask = _depth_usd(asks, 20)
    depth_total = None
    if depth_20_bid is not None and depth_20_ask is not None:
        depth_total = depth_20_bid + depth_20_ask
    depth_imbalance = None
    if depth_20_bid is not None and depth_20_ask is not None and (depth_20_bid + depth_20_ask) > 0:
        depth_imbalance = (depth_20_bid - depth_20_ask) / (depth_20_bid + depth_20_ask)
    # depth_slope: mean USD per level in the 6-20 band relative to the top-5
    # band. <1 means liquidity thins away from touch; >1 means it deepens.
    depth_slope = None
    depth_5_total = (depth_5_bid or 0.0) + (depth_5_ask or 0.0)
    if depth_total is not None and depth_5_total > 0:
        outer_levels = max(1, min(20, len(bids)) + min(20, len(asks)) - min(5, len(bids)) - min(5, len(asks)))
        inner_levels = min(5, len(bids)) + min(5, len(asks))
        outer_per_level = (depth_total - depth_5_total) / outer_levels
        inner_per_level = depth_5_total / max(1, inner_levels)
        if inner_per_level > 0:
            depth_slope = outer_per_level / inner_per_level
    impact_bid = _price_impact_bps(bids, mid, IMPACT_REFERENCE_NOTIONAL_USD)
    impact_ask = _price_impact_bps(asks, mid, IMPACT_REFERENCE_NOTIONAL_USD)
    impacts = [value for value in (impact_bid, impact_ask) if value is not None]
    estimated_price_impact_bps = (sum(impacts) / len(impacts)) if impacts else None
    # Size-weighted microprice + top-5 quantity imbalance: the tensor's
    # micro-family fallbacks (microprice/micro_price, |imbalance_5| toxicity
    # proxy) read these from the merged microstructure payload, which includes
    # this key.
    microprice = None
    if (best_bid_qty + best_ask_qty) > 0:
        microprice = (
            best_bid_px * best_ask_qty + best_ask_px * best_bid_qty
        ) / (best_bid_qty + best_ask_qty)
    bid_qty_5 = sum(qty for _, qty in bids[:5])
    ask_qty_5 = sum(qty for _, qty in asks[:5])
    imbalance_5 = None
    if (bid_qty_5 + ask_qty_5) > 0:
        imbalance_5 = (bid_qty_5 - ask_qty_5) / (bid_qty_5 + ask_qty_5)
    generated_at = _utc_now_iso()
    now_ms = _now_ms()
    event_ms = _book_event_ms(book)
    received_ms = _received_ms(book)
    update_age_ms = max(0, now_ms - event_ms) if event_ms is not None else None
    source_latency_ms = None
    if event_ms is not None and received_ms is not None and received_ms >= event_ms:
        source_latency_ms = received_ms - event_ms
    sequence_gap_raw = book.get("sequence_gap_flag") or book.get("sequence_gap")
    sequence_gap_flag = 1.0 if str(sequence_gap_raw).lower() in {"1", "true", "yes"} else 0.0
    return {
        "schema_version": SCHEMA_VERSION,
        "worker_id": WORKER_ID,
        "symbol": symbol,
        "exchange": "binance",
        "best_bid": best_bid_px,
        "best_ask": best_ask_px,
        "best_bid_size": best_bid_qty,
        "best_ask_size": best_ask_qty,
        "bid_ask_mid": mid,
        "mid_price": mid,
        "spread_bps": spread_bps,
        "bid_ask_spread_bps": spread_bps,
        "depth_5_bid_usd": depth_5_bid,
        "depth_5_ask_usd": depth_5_ask,
        "depth_20_bid_usd": depth_20_bid,
        "depth_20_ask_usd": depth_20_ask,
        "depth_total_usd": depth_total,
        "orderbook_depth_usd": depth_total,
        "depth_imbalance": depth_imbalance,
        "ob_imbalance": depth_imbalance,
        "depth_slope": depth_slope,
        "estimated_price_impact_bps": estimated_price_impact_bps,
        "impact_reference_notional_usd": IMPACT_REFERENCE_NOTIONAL_USD,
        "microprice": microprice,
        "micro_price": microprice,
        "imbalance_5": imbalance_5,
        "update_age_ms": update_age_ms,
        "source_latency_ms": source_latency_ms,
        "sequence_gap_flag": sequence_gap_flag,
        "bid_levels_used": len(bids),
        "ask_levels_used": len(asks),
        "book_source_key": source_key,
        "book_source": book.get("source"),
        "book_transport": book.get("transport"),
        "event_time": event_ms,
        "received_at": book.get("received_at"),
        "available_at": book.get("available_at") or book.get("received_at"),
        "generated_at": generated_at,
        "generated_utc": generated_at,
        "paper_only": True,
        "places_real_order": False,
        "writes_legacy_redis": False,
        "live_gate": LIVE_GATE,
    }


def _book_age_seconds(book: Mapping[str, Any]) -> float | None:
    """Return causal event age, rejecting missing or contradictory clocks."""

    event_ms = _book_event_ms(book)
    available_ms = _received_ms(book)
    now_ms = _now_ms()
    if (
        event_ms is None
        or available_ms is None
        or event_ms > available_ms
        or available_ms > now_ms
    ):
        return None
    return (now_ms - event_ms) / 1000.0


_PAIR_FIELDS = (
    "source",
    "exchange",
    "symbol",
    "sequence_id",
    "previous_sequence_id",
    "sequence_gap",
    "sequence_gap_flag",
    "event_time",
    "transaction_time",
    "received_at",
    "available_at",
    "generated_at",
    "update_type",
    "depth_level",
    "feed_speed_ms",
)


def _clock_chain_valid(payload: Mapping[str, Any]) -> bool:
    clocks = [
        _timestamp_ms(payload.get(name))
        for name in ("event_time", "received_at", "available_at", "generated_at")
    ]
    parsed = [value for value in clocks if value is not None]
    if len(parsed) != 4:
        return False
    event, received, available, generated = parsed
    return event <= received <= available <= generated <= _now_ms()


def _canonical_pair_reason(
    symbol: str,
    depth: Any,
    features: Any,
    *,
    max_book_age_seconds: float,
) -> str | None:
    if not isinstance(depth, Mapping) or not isinstance(features, Mapping):
        return "MISSING"
    if (
        depth.get("schema_version") != DIRECT_DEPTH_SCHEMA
        or features.get("schema_version") != DIRECT_FEATURES_SCHEMA
        or any(payload.get("source") != "direct_binance" for payload in (depth, features))
        or any(payload.get("exchange") != "binance" for payload in (depth, features))
        or any(payload.get("symbol") != symbol for payload in (depth, features))
    ):
        return "IDENTITY_INVALID"
    if not depth.get("bids") or not depth.get("asks"):
        return "DEPTH_SHAPE_INVALID"
    if not _clock_chain_valid(depth) or not _clock_chain_valid(features):
        return "CLOCK_INVALID"
    age = _book_age_seconds(depth)
    if age is None:
        return "CLOCK_INVALID"
    if age > max_book_age_seconds:
        return "STALE"
    if any(depth.get(name) != features.get(name) for name in _PAIR_FIELDS):
        return "PAIR_MISMATCH"
    depth_gap_flag = _finite(depth.get("sequence_gap_flag"))
    features_gap_flag = _finite(features.get("sequence_gap_flag"))
    if (
        depth.get("sequence_gap") is not False
        or features.get("sequence_gap") is not False
        or depth_gap_flag != 0.0
        or features_gap_flag != 0.0
    ):
        return "SEQUENCE_GAP"
    return None


def run_cycle(client: Any, *, symbols: list[str], ttl_seconds: int, max_book_age_seconds: float) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    healthy = 0
    for symbol in symbols:
        depth = _safe_get_json(client, f"v2:orderbook:depth:binance:{symbol}")
        features = _safe_get_json(client, f"v2:orderbook:features:binance:{symbol}")
        reason = _canonical_pair_reason(
            symbol,
            depth,
            features,
            max_book_age_seconds=max_book_age_seconds,
        )
        if reason is None:
            healthy += 1
        else:
            reasons[reason] = reasons.get(reason, 0) + 1
    summary = {
        "schema_version": "v2_orderbook_features_supervision_summary_v2",
        "worker_id": WORKER_ID,
        "generated_utc": _utc_now_iso(),
        "symbols_total": len(symbols),
        "canonical_pair_healthy": healthy,
        "canonical_pair_unhealthy": len(symbols) - healthy,
        "canonical_pair_reasons": dict(sorted(reasons.items())),
        "features_written": 0,
        "per_symbol_feature_write_authorized": False,
        "canonical_per_symbol_owner": "v2_direct_orderbook_recorder",
        "summary_only_supervision": True,
        "ttl_seconds": ttl_seconds,
        "max_book_age_seconds": max_book_age_seconds,
        "trainer_admission_authorized": False,
        "consumer_eligible": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "paper_only": True,
        "places_real_order": False,
        "writes_legacy_redis": False,
        "live_gate": LIVE_GATE,
    }
    _safe_set_json(client, SUMMARY_KEY, summary, ttl_seconds=max(ttl_seconds, 600))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--symbols", default=None, help="comma-separated; defaults to the dynamic runtime universe")
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--max-book-age-seconds", type=float, default=DEFAULT_MAX_BOOK_AGE_SECONDS)
    args = parser.parse_args(argv)
    client = _redis_client()
    while True:
        if client is None:
            # Boot-order safety: reconnect each cycle instead of publishing
            # nothing forever when Redis starts after this unit.
            client = _redis_client()
        symbols = resolve_symbols(explicit=args.symbols)
        summary = run_cycle(
            client,
            symbols=symbols,
            ttl_seconds=int(args.ttl_seconds),
            max_book_age_seconds=float(args.max_book_age_seconds),
        )
        print(json.dumps(summary, separators=(",", ":")), flush=True)
        if not args.loop:
            return 0
        time.sleep(max(5, int(args.interval_seconds)))


if __name__ == "__main__":
    sys.exit(main())
