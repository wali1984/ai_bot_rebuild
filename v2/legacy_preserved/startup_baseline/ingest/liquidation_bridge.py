#!/usr/bin/env python3
"""Bridge existing liquidation sources into a canonical Redis stream.

Sources:
- binance:force:raw (list of per-event dicts with price/qty/side)
- raw:coinank:liquidation_orders:global (string JSON with list under data.data)

Output stream:
- liquidations:events (config.LIQ_EVENTS_STREAM)

Fields published:
- ts, symbol, side (LONG_LIQ/SHORT_LIQ), price, qty, notional, source,
  src_key, src_id, ingest_ts

Deduplication:
- Per event fingerprint stored with NX + TTL to avoid duplicate publishes.
"""
import json
import time
from pathlib import Path
from typing import Dict, Any

import redis

# Ensure project root on sys.path for config import when executed directly
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config


STREAM = config.LIQ_EVENTS_STREAM
BINANCE_KEY = config.LIQ_SOURCE_BINANCE_FORCE_KEY
COINANK_KEY = config.LIQ_SOURCE_COINANK_ORDERS_KEY
POLL_INTERVAL = config.LIQ_BRIDGE_POLL_INTERVAL_SEC
MAX_BATCH = config.LIQ_BRIDGE_MAX_BATCH
DEDUP_TTL = config.LIQ_BRIDGE_DEDUP_TTL_SEC
ENABLED = config.LIQ_BRIDGE_ENABLED

SYMBOLS = set(config.SYMBOLS)

r = redis.from_url(config.REDIS_URL, decode_responses=True)


def _dedup_key(source: str, src_id: str) -> str:
    return f"dedup:liq:{source}:{src_id}"


def _set_dedup(source: str, src_id: str) -> bool:
    key = _dedup_key(source, src_id)
    return r.set(key, 1, ex=DEDUP_TTL, nx=True) is True


def publish(event: Dict[str, Any]) -> None:
    try:
        r.xadd(STREAM, event)
    except Exception as exc:
        print(f"[liq_bridge] publish error: {exc} | event={event}")


def process_binance_force() -> int:
    """Consume binance:force:raw list using an index cursor."""
    cursor_key = "cursor:liq_bridge:binance_force_raw"
    start = int(r.get(cursor_key) or 0)
    length = r.llen(BINANCE_KEY)
    if length <= 0:
        return 0

    if start >= length:
        # List was rotated or trimmed; reset cursor to tail window to avoid stalling.
        start = max(0, length - MAX_BATCH)

    end = min(start + MAX_BATCH - 1, length - 1)
    if end < start:
        r.set(cursor_key, start)
        return 0
    items = r.lrange(BINANCE_KEY, start, end)
    if not items:
        return 0

    processed = 0
    for idx, raw in enumerate(items, start=start):
        try:
            data = json.loads(raw)
        except Exception:
            continue

        symbol = str(data.get("symbol", "")).upper()
        if symbol not in SYMBOLS:
            continue

        ts = int(data.get("ts") or 0)
        price = float(data.get("price") or 0)
        qty = float(data.get("qty") or 0)
        side_raw = str(data.get("side", "")).upper()
        if ts <= 0 or price <= 0 or qty <= 0:
            continue

        side = "SHORT_LIQ" if side_raw == "BUY" else "LONG_LIQ" if side_raw == "SELL" else None
        if side is None:
            continue

        notional = float(data.get("notional") or price * qty)
        src_id = f"idx:{idx}:{symbol}:{ts}:{side_raw}:{price}:{qty}"
        if not _set_dedup("binance", src_id):
            continue

        event = {
            "ts": ts,
            "symbol": symbol,
            "side": side,
            "price": price,
            "qty": qty,
            "notional": notional,
            "source": "binance",
            "src_key": BINANCE_KEY,
            "src_id": src_id,
            "ingest_ts": int(time.time() * 1000),
        }
        publish(event)
        processed += 1

    r.set(cursor_key, end + 1)
    return processed


def process_coinank_orders() -> int:
    """Poll raw:coinank:liquidation_orders:global (string JSON)."""
    raw = r.get(COINANK_KEY)
    if not raw:
        return 0

    try:
        obj = json.loads(raw)
    except Exception:
        return 0

    items = obj.get("data", {}).get("data") or []
    if not isinstance(items, list):
        return 0

    last_ts_key = "cursor:liq_bridge:coinank_orders_last_ts"
    last_ts = int(r.get(last_ts_key) or 0)
    new_max_ts = last_ts
    processed = 0

    for item in items:
        ts = int(item.get("ts") or 0)
        if ts <= last_ts:
            continue

        symbol = str(item.get("contractCode") or item.get("baseCoin") or "").upper()
        if symbol not in SYMBOLS:
            continue

        pos_side = str(item.get("posSide", "")).lower()
        if pos_side == "long":
            side = "LONG_LIQ"
        elif pos_side == "short":
            side = "SHORT_LIQ"
        else:
            continue

        price = float(item.get("price") or 0)
        qty = float(item.get("amount") or 0)
        if price <= 0 or qty <= 0:
            continue

        notional = float(item.get("tradeTurnover") or price * qty)

        src_id = f"{symbol}:{ts}:{side}:{price}:{qty}"
        if not _set_dedup("coinank", src_id):
            continue

        event = {
            "ts": ts,
            "symbol": symbol,
            "side": side,
            "price": price,
            "qty": qty,
            "notional": notional,
            "source": "coinank",
            "src_key": COINANK_KEY,
            "src_id": src_id,
            "ingest_ts": int(time.time() * 1000),
        }
        publish(event)
        processed += 1
        if ts > new_max_ts:
            new_max_ts = ts

    if new_max_ts > last_ts:
        r.set(last_ts_key, new_max_ts)
    return processed


def main() -> None:
    if not ENABLED:
        print("[liq_bridge] Bridge disabled via LIQ_BRIDGE_ENABLED")
        return

    print(f"[liq_bridge] Starting bridge -> {STREAM}")
    print(f"[liq_bridge] Sources: binance={BINANCE_KEY}, coinank={COINANK_KEY}")
    print(f"[liq_bridge] Poll interval={POLL_INTERVAL}s, max_batch={MAX_BATCH}, dedup_ttl={DEDUP_TTL}s")

    while True:
        published = 0
        try:
            published += process_binance_force()
        except Exception as exc:
            print(f"[liq_bridge] binance processing error: {exc}")

        try:
            published += process_coinank_orders()
        except Exception as exc:
            print(f"[liq_bridge] coinank processing error: {exc}")

        if published:
            print(f"[liq_bridge] published {published} events")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
