#!/usr/bin/env python3
"""Compute liquidation price levels from canonical liquidation events stream.

ENHANCED VERSION (Jan 2026):
- Adds liquidation_long_distance_pct / liquidation_short_distance_pct
- Adds staleness gating (liquidation_staleness_ms, liquidation_is_stale)
- Optimized CPU usage with batch deque cleanup
- Binance-first priority support (prepares for CoinAnk merge)

Consumes:
- Redis stream liquidations:events (config.LIQ_EVENTS_STREAM)

Produces per (symbol, timeframe) hashes:
- unified_features:{symbol}:{tf}
- unified_features:{symbol}:{tf}:latest
with liquidation_* fields populated for trainer/feature consumers.
"""
import json
import math
import socket
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque, Dict, List, Tuple, Optional

import redis

# Ensure project root on sys.path when run as script
import sys
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import config

STREAM_NAME = config.LIQ_EVENTS_STREAM
GROUP_NAME = "liq_levels"
CONSUMER_NAME = f"{socket.gethostname()}-{int(time.time())}"
BLOCK_MS = 5000
BATCH_SIZE = 2000
MAX_RETENTION_SECONDS = 7 * 24 * 3600  # 7 days safety cap
PUBLISH_HEARTBEAT_SEC = 60

# Staleness thresholds (milliseconds)
STALENESS_WARNING_MS = 5 * 60 * 1000   # 5 minutes = warning
STALENESS_STALE_MS = 15 * 60 * 1000    # 15 minutes = stale

# Batch cleanup optimization: clean deques every N iterations
CLEANUP_BATCH_INTERVAL = 50

BUCKET_WIDTH_PCT = {
    "1m": 0.0010,
    "5m": 0.0010,
    "15m": 0.0015,
    "1h": 0.0020,
    "4h": 0.0020,
    "1d": 0.0025,
}

r = redis.from_url(config.REDIS_URL, decode_responses=True)


def tf_to_seconds(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    if tf.endswith("h"):
        return int(tf[:-1]) * 3600
    if tf.endswith("d"):
        return int(tf[:-1]) * 86400
    raise ValueError(f"Unknown timeframe: {tf}")


def ensure_group() -> None:
    try:
        r.xgroup_create(STREAM_NAME, GROUP_NAME, id="0", mkstream=True)
    except redis.exceptions.ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            return


def reset_consumer_group_to_tail() -> None:
    """Skip backlog by advancing the group cursor to a recent position.

    The stream can have tens of millions of entries. Processing them all
    on startup would take hours and produce stale data. Instead, seek to
    the entry ~2 hours ago so the engine starts with a warm window.
    """
    try:
        info = r.xinfo_stream(STREAM_NAME)
        last_id = info.get("last-generated-id", "$")
        stream_len = info.get("length", 0)
        if stream_len < 10000:
            return

        target_ms = int(time.time() * 1000) - 2 * 3600 * 1000
        target_id = f"{target_ms}-0"
        entries = r.xrange(STREAM_NAME, min=target_id, count=1)
        if entries:
            seek_id = entries[0][0]
        else:
            seek_id = last_id

        r.xgroup_setid(STREAM_NAME, GROUP_NAME, seek_id)
        print(f"[liq_levels] RESET consumer group cursor → {seek_id}  (stream len={stream_len})")

        try:
            consumers = r.xinfo_consumers(STREAM_NAME, GROUP_NAME)
            for c in consumers:
                if c.get("pending", 0) == 0 and c["name"] != CONSUMER_NAME:
                    r.xgroup_delconsumer(STREAM_NAME, GROUP_NAME, c["name"])
            print(f"[liq_levels] Cleaned up zombie consumers")
        except Exception:
            pass
    except Exception as exc:
        print(f"[liq_levels] reset_consumer_group_to_tail failed: {exc}")
        raise


def _bucket_step(price: float, tf: str) -> float:
    pct = BUCKET_WIDTH_PCT.get(tf, 0.002)
    step = price * pct
    return max(step, 1e-8)


def _decay_weight(notional: float, age_ms: float, window_ms: float) -> float:
    tau = max(window_ms / 2.0, 1.0)
    return notional * math.exp(-age_ms / tau)


class LevelEngine:
    def __init__(self):
        self.state: Dict[str, Dict[str, Deque[Dict]]] = {
            sym: {tf: deque() for tf in config.TIMEFRAMES} for sym in config.SYMBOLS
        }
        self.ewma_price: Dict[str, float] = {sym: None for sym in config.SYMBOLS}
        self.last_log = 0
        self.last_publish: Dict[Tuple[str, str], int] = {}
        self.iteration_count = 0  # For batch cleanup optimization
        self.last_cleanup_time = time.time()
        ensure_group()
        reset_consumer_group_to_tail()

    def _get_latest_price(self, symbol: str) -> float:
        """Best-effort latest price for a symbol from live feeds.

        Used to emit zero/liquidation-default mappings even when no events exist yet
        (so downstream feature consumers always have liquidation_* keys).
        """
        # Prefer cached EWMA if we have one
        p = self.ewma_price.get(symbol)
        if p is not None and p > 0:
            return float(p)

        # 1) price:{symbol} - Real-time mark price from WebSocket
        try:
            raw = r.get(f"price:{symbol}")
            if raw:
                data = json.loads(raw) if raw.startswith('{') else {"price": raw}
                if isinstance(data, dict) and data.get("price"):
                    return float(data["price"])
                elif isinstance(raw, str) and raw.replace('.', '').isdigit():
                    return float(raw)
        except Exception:
            pass

        # 2) market:{symbol}:1m (JSON string written by Binance/CoinAPI ingestors)
        try:
            raw = r.get(f"market:{symbol}:1m")
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    close = data.get("close")
                    if close is not None:
                        return float(close)
        except Exception:
            pass

        # 3) latest:binance:ohlcv:{symbol}:1m (JSON string; may contain 'close' or 'price')
        try:
            raw = r.get(f"latest:binance:ohlcv:{symbol}:1m")
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    if data.get("close") is not None:
                        return float(data["close"])
                    if data.get("price") is not None:
                        return float(data["price"])
        except Exception:
            pass

        # 4) CoinAPI V1 hash (close as string)
        try:
            h = r.hgetall(f"latest:coinapi:ohlcv:{symbol}:1m")
            if h and h.get("close") is not None:
                return float(h["close"])
        except Exception:
            pass

        return 0.0

    def _batch_cleanup_deques(self, now_ms: int) -> None:
        """
        Batch cleanup of all deques to reduce per-iteration overhead.
        
        Called every CLEANUP_BATCH_INTERVAL iterations instead of every loop.
        """
        for symbol in config.SYMBOLS:
            for tf in config.TIMEFRAMES:
                window_seconds = max(tf_to_seconds(tf) * 20, 2 * 3600)
                window_seconds = min(window_seconds, MAX_RETENTION_SECONDS)
                window_ms = window_seconds * 1000
                
                dq = self.state[symbol][tf]
                # Batch remove old entries
                while dq and (now_ms - dq[0]["ts"]) > window_ms:
                    dq.popleft()

    def run(self) -> None:
        print(f"[liq_levels] Starting consumer {CONSUMER_NAME} group={GROUP_NAME} stream={STREAM_NAME}")
        print(f"[liq_levels] ENHANCED: distance_pct, staleness gating, batch cleanup enabled")
        self._last_publish_ts = 0.0
        while True:
            self.iteration_count += 1
            now_ms = int(time.time() * 1000)

            if self.iteration_count % CLEANUP_BATCH_INTERVAL == 0:
                self._batch_cleanup_deques(now_ms)

            messages = r.xreadgroup(
                groupname=GROUP_NAME,
                consumername=CONSUMER_NAME,
                streams={STREAM_NAME: ">"},
                count=BATCH_SIZE,
                block=BLOCK_MS,
            )
            if not messages:
                self._heartbeat_publish()
                self._maybe_log()
                continue

            dirty: List[Tuple[str, str]] = []
            for _, items in messages:
                for msg_id, fields in items:
                    try:
                        event = self._parse_event(fields)
                        if not event:
                            r.xack(STREAM_NAME, GROUP_NAME, msg_id)
                            continue
                        symbol = event["symbol"]
                        for tf in config.TIMEFRAMES:
                            self.state[symbol][tf].append(event)
                            dirty.append((symbol, tf))
                        r.xack(STREAM_NAME, GROUP_NAME, msg_id)
                    except Exception as exc:
                        print(f"[liq_levels] Error processing message {msg_id}: {exc}")
                        r.xack(STREAM_NAME, GROUP_NAME, msg_id)
                        continue

            now_sec = time.time()
            if now_sec - self._last_publish_ts >= 2.0 or len(dirty) < BATCH_SIZE:
                self._publish_updates(dirty)
                self._heartbeat_publish()
                self._last_publish_ts = now_sec
            self._maybe_log()

    def _parse_event(self, fields: Dict[str, str]) -> Dict:
        try:
            symbol = str(fields.get("symbol", "")).upper()
            if symbol not in config.SYMBOLS:
                return {}
            ts = int(fields.get("ts") or 0)
            ingest_ts = int(fields.get("ingest_ts") or 0)
            price = float(fields.get("price") or 0)
            qty = float(fields.get("qty") or 0)
            notional = float(fields.get("notional") or 0)
            side = str(fields.get("side", "")).upper()
        except Exception:
            return {}

        now_ms = int(time.time() * 1000)
        if ts > 0 and (now_ms - ts) > 24 * 3600 * 1000 and ingest_ts > 0:
            ts = ingest_ts  # fallback to ingest time when source ts is stale

        if ts <= 0 or price <= 0 or qty <= 0 or notional <= 0 or side not in {"LONG_LIQ", "SHORT_LIQ"}:
            return {}

        return {
            "ts": ts,
            "price": price,
            "qty": qty,
            "notional": notional,
            "side": side,
            "symbol": symbol,
        }

    def _publish_updates(self, dirty: List[Tuple[str, str]]) -> None:
        now_ms = int(time.time() * 1000)
        seen = set()
        for symbol, tf in dirty:
            key = (symbol, tf)
            if key in seen:
                continue
            seen.add(key)

            mapping = self._compute_mapping(symbol, tf, now_ms)
            if not mapping:
                continue

            unified_key = f"unified_features:{symbol}:{tf}"
            latest_key = f"{unified_key}:latest"
            pipe = r.pipeline()
            pipe.hset(unified_key, mapping=mapping)
            pipe.hset(latest_key, mapping=mapping)
            pipe.expire(unified_key, 900)
            pipe.expire(latest_key, 900)
            pipe.execute()
            self.last_publish[key] = now_ms

    def _heartbeat_publish(self) -> None:
        now_ms = int(time.time() * 1000)
        for symbol in config.SYMBOLS:
            for tf in config.TIMEFRAMES:
                key = (symbol, tf)
                last_pub = self.last_publish.get(key, 0)
                if (now_ms - last_pub) < PUBLISH_HEARTBEAT_SEC * 1000:
                    continue
                mapping = self._compute_mapping(symbol, tf, now_ms)
                if not mapping:
                    continue
                unified_key = f"unified_features:{symbol}:{tf}"
                latest_key = f"{unified_key}:latest"
                pipe = r.pipeline()
                pipe.hset(unified_key, mapping=mapping)
                pipe.hset(latest_key, mapping=mapping)
                pipe.expire(unified_key, 900)
                pipe.expire(latest_key, 900)
                pipe.execute()
                self.last_publish[key] = now_ms

    def _compute_mapping(self, symbol: str, tf: str, now_ms: int):
        """
        Compute liquidation levels mapping with ENHANCED features:
        - liquidation_long_distance_pct / liquidation_short_distance_pct
        - liquidation_staleness_ms / liquidation_is_stale
        - liquidation_current_price (for downstream distance calculations)
        """
        window_seconds = max(tf_to_seconds(tf) * 20, 2 * 3600)
        window_seconds = min(window_seconds, MAX_RETENTION_SECONDS)
        window_ms = window_seconds * 1000

        dq = self.state[symbol][tf]
        # Note: batch cleanup handles most removals, but do a quick check here
        while dq and (now_ms - dq[0]["ts"]) > window_ms:
            dq.popleft()
        
        # Get current price for distance calculations
        current_price = self._get_latest_price(symbol)
        
        if not dq:
            # No events yet: still publish stable defaults so all symbols/timeframes
            # have liquidation_* keys (prevents missing-feature issues).
            if current_price <= 0:
                return None
            step = _bucket_step(current_price, tf)
            levels_json = json.dumps({
                "step": step,
                "top_long": [],
                "top_short": [],
            })
            return {
                "liquidation_long_level": 0.0,
                "liquidation_short_level": 0.0,
                "liquidation_long_strength": 0.0,
                "liquidation_short_strength": 0.0,
                "liquidation_long_distance_pct": 100.0,  # No level = max distance
                "liquidation_short_distance_pct": 100.0,
                "liquidation_volume": 0.0,
                "liquidation_levels_json": levels_json,
                "liquidation_updated_ts": now_ms,
                "liquidation_last_event_ts": 0,
                "liquidation_staleness_ms": MAX_RETENTION_SECONDS * 1000,
                "liquidation_is_stale": 1,  # Boolean: 1 = stale, 0 = fresh
                "liquidation_current_price": current_price,
                "liquidation_source": "binance",
            }

        mid_price = dq[-1]["price"] if self.ewma_price.get(symbol) is None else self.ewma_price[symbol]
        mid_price = mid_price if mid_price > 0 else dq[-1]["price"]
        self.ewma_price[symbol] = 0.9 * mid_price + 0.1 * dq[-1]["price"]

        # Use current price for distance if available, else use EWMA
        ref_price = current_price if current_price > 0 else mid_price

        step = _bucket_step(mid_price, tf)
        heat_long: Dict[int, float] = defaultdict(float)
        heat_short: Dict[int, float] = defaultdict(float)
        liq_volume = 0.0

        for ev in dq:
            age_ms = max(0, now_ms - ev["ts"])
            weight = _decay_weight(ev["notional"], age_ms, window_ms)
            bucket = int(ev["price"] / step)
            if ev["side"] == "LONG_LIQ":
                heat_long[bucket] += weight
            else:
                heat_short[bucket] += weight
            liq_volume += ev["notional"]

        long_bucket, long_strength, long_top = self._top_bucket(heat_long)
        short_bucket, short_strength, short_top = self._top_bucket(heat_short)

        long_level = (long_bucket * step) if long_bucket is not None else 0.0
        short_level = (short_bucket * step) if short_bucket is not None else 0.0
        last_event_ts = dq[-1]["ts"]
        
        # === NEW: Distance percentage calculations ===
        # Distance from current price to liquidation level (as % of price)
        if long_level > 0 and ref_price > 0:
            long_distance_pct = abs(ref_price - long_level) / ref_price * 100
        else:
            long_distance_pct = 100.0  # No level = max distance (safe)
            
        if short_level > 0 and ref_price > 0:
            short_distance_pct = abs(short_level - ref_price) / ref_price * 100
        else:
            short_distance_pct = 100.0  # No level = max distance (safe)
        
        # === NEW: Staleness gating ===
        staleness_ms = now_ms - last_event_ts
        is_stale = 1 if staleness_ms > STALENESS_STALE_MS else 0

        levels_json = json.dumps({
            "step": step,
            "top_long": [
                {"price": b * step, "strength": v}
                for b, v in long_top
            ],
            "top_short": [
                {"price": b * step, "strength": v}
                for b, v in short_top
            ],
        })

        return {
            "liquidation_long_level": long_level,
            "liquidation_short_level": short_level,
            "liquidation_long_strength": long_strength or 0.0,
            "liquidation_short_strength": short_strength or 0.0,
            "liquidation_long_distance_pct": round(long_distance_pct, 4),
            "liquidation_short_distance_pct": round(short_distance_pct, 4),
            "liquidation_volume": liq_volume,
            "liquidation_levels_json": levels_json,
            "liquidation_updated_ts": now_ms,
            "liquidation_last_event_ts": last_event_ts,
            "liquidation_staleness_ms": staleness_ms,
            "liquidation_is_stale": is_stale,
            "liquidation_current_price": ref_price,
            "liquidation_source": "binance",
        }

    @staticmethod
    def _top_bucket(heat: Dict[int, float]) -> Tuple[int, float, List[Tuple[int, float]]]:
        if not heat:
            return None, 0.0, []
        top_items = sorted(heat.items(), key=lambda kv: kv[1], reverse=True)
        bucket, strength = top_items[0]
        return bucket, strength, top_items[:3]

    def _maybe_log(self) -> None:
        now = time.time()
        if now - self.last_log < 60:
            return
        self.last_log = now
        # Log some stats for monitoring
        total_events = sum(
            len(self.state[sym][tf]) 
            for sym in config.SYMBOLS 
            for tf in config.TIMEFRAMES
        )
        print(f"[liq_levels] heartbeat ok; iterations={self.iteration_count}, total_events_in_memory={total_events}")


def main() -> None:
    if not config.LIQ_BRIDGE_ENABLED:
        print("[liq_levels] WARNING: LIQ_BRIDGE_ENABLED is false; upstream bridge may be offline")
    engine = LevelEngine()
    engine.run()


if __name__ == "__main__":
    main()
