"""Native V2 liquidation levels engine.

Consumes the canonical V2 liquidation event stream and publishes
liquidation_* fields into V2 unified feature hashes. This replaces the
direct runtime dependency on ``v2/legacy_owned_runtime/ingest`` while
preserving the downstream Redis contract used by feature/trainer paths.

No exchange orders, no legacy Redis keys, no legacy filesystem writes.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import socket
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover - import failure surfaced by main
    redis = None  # type: ignore


WORKER_ID = "v2_liquidation_levels_engine"
V2_REDIS_PREFIX = os.getenv("V2_REDIS_PREFIX", "v2:")
DEFAULT_REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
DEFAULT_STREAM_NAME = os.getenv("LIQ_EVENTS_STREAM", "v2:liquidations:events")
GROUP_NAME = os.getenv("V2_LIQ_LEVELS_GROUP", "v2_liq_levels_native")
CONSUMER_NAME = f"{socket.gethostname()}-{int(time.time())}"
DEFAULT_BLOCK_MS = 5000
DEFAULT_BATCH_SIZE = 2000
DEFAULT_MAX_RETENTION_SECONDS = 7 * 24 * 3600
DEFAULT_PUBLISH_HEARTBEAT_SEC = 60
DEFAULT_SYMBOL_REFRESH_SEC = 60
DEFAULT_TTL_SECONDS = 900
STALENESS_STALE_MS = 15 * 60 * 1000
CLEANUP_BATCH_INTERVAL = 50
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
VALID_LIQUIDATION_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")

BUCKET_WIDTH_PCT = {
    "1m": 0.0010,
    "5m": 0.0010,
    "15m": 0.0015,
    "1h": 0.0020,
    "4h": 0.0020,
    "1d": 0.0025,
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _v2_key(key: str) -> str:
    key = str(key)
    if key.startswith(V2_REDIS_PREFIX):
        return key
    return f"{V2_REDIS_PREFIX}{key}"


def _parse_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return default
    parsed = tuple(part.strip() for part in value.split(",") if part.strip())
    return parsed or default


def _valid_liquidation_symbol(symbol: str) -> bool:
    return bool(VALID_LIQUIDATION_SYMBOL_RE.fullmatch(str(symbol or "").upper()))


def _connect_redis(redis_url: str):
    if redis is None:
        raise RuntimeError("redis package is unavailable")
    client = redis.from_url(redis_url, decode_responses=True)
    client.ping()
    return client


def tf_to_seconds(tf: str) -> int:
    tf = tf.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    if tf.endswith("h"):
        return int(tf[:-1]) * 3600
    if tf.endswith("d"):
        return int(tf[:-1]) * 86400
    raise ValueError(f"Unknown timeframe: {tf}")


def _bucket_step(price: float, tf: str) -> float:
    pct = BUCKET_WIDTH_PCT.get(tf, 0.002)
    step = price * pct
    return max(step, 1e-8)


def _decay_weight(notional: float, age_ms: float, window_ms: float) -> float:
    tau = max(window_ms / 2.0, 1.0)
    return notional * math.exp(-age_ms / tau)


@dataclass(frozen=True)
class EngineConfig:
    redis_url: str
    stream_name: str
    timeframes: tuple[str, ...]
    block_ms: int
    batch_size: int
    ttl_seconds: int
    publish_heartbeat_sec: int
    symbol_refresh_sec: int
    max_retention_seconds: int
    explicit_symbols: tuple[str, ...] | None
    smoke_test: bool


class LevelEngine:
    def __init__(self, config: EngineConfig):
        self.config = config
        self.redis = _connect_redis(config.redis_url)
        self.stream_name = _v2_key(config.stream_name)
        self.symbols: tuple[str, ...] = ()
        self.state: dict[str, dict[str, Deque[dict[str, Any]]]] = {}
        self.ewma_price: dict[str, float | None] = {}
        # Rolling per-symbol×tf intensity samples (decay-weighted total
        # liquidation strength). cascade_risk v2 ranks the current sample
        # against this history so the value means "how extreme is this
        # symbol's liquidation activity vs its own recent past" — near 0 in
        # normal activity, high only in genuine cascades. (The v1 metric was
        # the long-side SHARE of strength: neutral at 0.5, ≥0.5 on nearly
        # every symbol during any directional market, which made the regime
        # gate classify ~half of all cycles as LIQUIDITY_SWEEP.)
        self.intensity_history: dict[str, dict[str, Deque[float]]] = {}
        self.last_publish: dict[tuple[str, str], int] = {}
        self.last_log = 0.0
        self.last_symbol_refresh = 0.0
        self.iteration_count = 0
        self.events_processed = 0
        self.events_ignored = 0
        self._last_publish_ts = 0.0
        self.refresh_symbols(force=True)
        self.ensure_group()
        self.reset_consumer_group_to_recent_tail()

    def refresh_symbols(self, *, force: bool = False) -> None:
        now = time.time()
        if not force and now - self.last_symbol_refresh < self.config.symbol_refresh_sec:
            return
        resolved = tuple(
            resolve_symbols(
                explicit=self.config.explicit_symbols,
                smoke_test=self.config.smoke_test,
                include_baseline=True,
            )
        )
        if not resolved:
            resolved = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
        new_symbols = tuple(
            dict.fromkeys(
                sym.upper()
                for sym in resolved
                if _valid_liquidation_symbol(sym)
            )
        )
        for symbol in new_symbols:
            self.state.setdefault(symbol, {tf: deque() for tf in self.config.timeframes})
            self.intensity_history.setdefault(
                symbol, {tf: deque(maxlen=720) for tf in self.config.timeframes}
            )
            for tf in self.config.timeframes:
                self.state[symbol].setdefault(tf, deque())
                self.intensity_history[symbol].setdefault(tf, deque(maxlen=720))
            self.ewma_price.setdefault(symbol, None)
        stale_symbols = set(self.state) - set(new_symbols)
        for symbol in stale_symbols:
            self.state.pop(symbol, None)
            self.ewma_price.pop(symbol, None)
            self.intensity_history.pop(symbol, None)
        self.symbols = new_symbols
        self.last_symbol_refresh = now

    def ensure_group(self) -> None:
        try:
            self.redis.xgroup_create(self.stream_name, GROUP_NAME, id="0", mkstream=True)
        except redis.exceptions.ResponseError as exc:  # type: ignore[union-attr]
            if "BUSYGROUP" not in str(exc):
                raise

    def reset_consumer_group_to_recent_tail(self) -> None:
        try:
            info = self.redis.xinfo_stream(self.stream_name)
            stream_len = int(info.get("length", 0) or 0)
            if stream_len < 10000:
                return
            target_ms = int(time.time() * 1000) - 2 * 3600 * 1000
            entries = self.redis.xrange(self.stream_name, min=f"{target_ms}-0", count=1)
            seek_id = entries[0][0] if entries else info.get("last-generated-id", "$")
            self.redis.xgroup_setid(self.stream_name, GROUP_NAME, seek_id)
        except Exception as exc:
            print(f"[{WORKER_ID}] recent-tail reset skipped: {exc}")

    def _get_latest_price(self, symbol: str) -> float:
        cached = self.ewma_price.get(symbol)
        if cached is not None and cached > 0:
            return float(cached)

        for key in (f"v2:features:latest:{symbol}:1m",):
            try:
                raw = self.redis.get(key)
                if raw:
                    payload = json.loads(raw)
                    features = payload.get("features") if isinstance(payload, dict) else {}
                    if isinstance(features, dict):
                        for field in ("micro_price", "ema_12", "ema_26"):
                            value = features.get(field)
                            if value is not None and float(value) > 0:
                                return float(value)
            except Exception:
                pass

        try:
            raw = self.redis.get(f"v2:market:prices:{symbol}")
            if raw:
                payload = json.loads(raw)
                ticker = payload.get("ticker_24hr") if isinstance(payload, dict) else {}
                if isinstance(ticker, dict):
                    for field in ("lastPrice", "weightedAvgPrice", "openPrice"):
                        value = ticker.get(field)
                        if value is not None and float(value) > 0:
                            return float(value)
        except Exception:
            pass

        for key in (f"v2:market:orderbook:binance:{symbol}", f"v2:market:orderbook:{symbol}"):
            try:
                raw = self.redis.get(key)
                if not raw:
                    continue
                payload = json.loads(raw)
                bids = payload.get("bids") if isinstance(payload, dict) else []
                asks = payload.get("asks") if isinstance(payload, dict) else []
                if bids and asks:
                    bid = float(bids[0][0])
                    ask = float(asks[0][0])
                    if bid > 0 and ask > 0:
                        return (bid + ask) / 2.0
            except Exception:
                pass

        try:
            raw = self.redis.get(f"v2:market:liquidations:latest:{symbol}")
            if raw:
                payload = json.loads(raw)
                value = payload.get("price") if isinstance(payload, dict) else None
                if value is not None and float(value) > 0:
                    return float(value)
        except Exception:
            pass
        return 0.0

    def _parse_event(self, fields: dict[str, str]) -> dict[str, Any]:
        try:
            symbol = str(fields.get("symbol", "")).upper()
            if symbol not in self.state:
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
            ts = ingest_ts
        if ts <= 0 or price <= 0 or qty <= 0 or notional <= 0:
            return {}
        if side not in {"LONG_LIQ", "SHORT_LIQ"}:
            return {}
        return {
            "ts": ts,
            "price": price,
            "qty": qty,
            "notional": notional,
            "side": side,
            "symbol": symbol,
        }

    def _extract_levels(
        self,
        heat: dict[int, float],
        step: float,
        *,
        max_levels: int = 20,
        min_strength_ratio: float = 0.04,
    ) -> list[dict[str, Any]]:
        """Return up to max_levels significant buckets sorted by strength descending.

        Only buckets with strength >= min_strength_ratio * max_strength are returned.
        This gives a full picture of where liquidation pressure accumulates for
        sweep-target and zone analysis, rather than just the top 3.
        """
        if not heat:
            return []
        items = sorted(heat.items(), key=lambda kv: kv[1], reverse=True)
        if not items:
            return []
        max_strength = items[0][1]
        threshold = max_strength * min_strength_ratio
        significant = [(b, v) for b, v in items if v >= threshold][:max_levels]
        return [{"price": round(b * step, 8), "strength": round(v, 4)} for b, v in significant]

    def _compute_zones(
        self,
        levels: list[dict[str, Any]],
        step: float,
        *,
        zone_merge_buckets: int = 3,
    ) -> list[dict[str, Any]]:
        """Merge nearby price levels into zones.

        Two levels are in the same zone if their prices are within
        zone_merge_buckets * step of each other. Returns zones sorted by
        total strength descending — strongest zone first = most likely
        sweep target.
        """
        if not levels:
            return []
        sorted_by_price = sorted(levels, key=lambda lv: lv["price"])
        merge_gap = zone_merge_buckets * step
        zones: list[dict[str, Any]] = []
        current: list[dict[str, Any]] = [sorted_by_price[0]]

        for lv in sorted_by_price[1:]:
            if lv["price"] - current[-1]["price"] <= merge_gap:
                current.append(lv)
            else:
                zones.append(current)
                current = [lv]
        zones.append(current)

        result = []
        for zone_levels in zones:
            prices = [lv["price"] for lv in zone_levels]
            strengths = [lv["strength"] for lv in zone_levels]
            total = sum(strengths)
            center = sum(p * s for p, s in zip(prices, strengths)) / total if total else prices[0]
            result.append({
                "zone_center": round(center, 8),
                "zone_low": round(min(prices), 8),
                "zone_high": round(max(prices), 8),
                "total_strength": round(total, 4),
                "level_count": len(zone_levels),
            })
        return sorted(result, key=lambda z: z["total_strength"], reverse=True)

    def _compute_mapping(self, symbol: str, tf: str, now_ms: int) -> dict[str, Any] | None:
        window_seconds = max(tf_to_seconds(tf) * 20, 2 * 3600)
        window_seconds = min(window_seconds, self.config.max_retention_seconds)
        window_ms = window_seconds * 1000
        dq = self.state[symbol][tf]
        while dq and (now_ms - int(dq[0]["ts"])) > window_ms:
            dq.popleft()

        current_price = self._get_latest_price(symbol)
        if not dq:
            if current_price <= 0:
                return None
            step = _bucket_step(current_price, tf)
            empty_levels = json.dumps({
                "step": step,
                "top_long": [], "top_short": [],
                "levels_long": [], "levels_short": [],
                "zones_long": [], "zones_short": [],
                "sweep_target_long": None, "sweep_target_short": None,
                "current_price": current_price,
                "no_events_reason": "no_liquidation_events_in_window",
            })
            return {
                "liquidation_long_level": 0.0,
                "liquidation_short_level": 0.0,
                "nearest_liquidation_level_above": 0.0,
                "nearest_liquidation_level_below": 0.0,
                "liquidation_long_strength": 0.0,
                "liquidation_short_strength": 0.0,
                "liquidation_long_distance_pct": 100.0,
                "liquidation_short_distance_pct": 100.0,
                # No events in window = no cascade evidence. Mask missing
                # (None) rather than synthesizing a value; the v1 default of
                # 0.5 sat exactly on the regime gate's >=0.5 sweep condition.
                "liquidation_cascade_risk": None,
                "liquidation_cascade_risk_semantics": "intensity_percentile_v2",
                "distance_to_long_liq_bps": None,
                "distance_to_short_liq_bps": None,
                "liquidation_pressure_direction": 0.0,
                "liquidation_count_5m": 0,
                "last_liq_bps_proxy": 0.0,
                "liquidation_sweep_target_long": None,
                "liquidation_sweep_target_short": None,
                "liquidation_sweep_target_long_distance_bps": None,
                "liquidation_sweep_target_short_distance_bps": None,
                "liquidation_zones_count_long": 0,
                "liquidation_zones_count_short": 0,
                "liquidation_levels_count_long": 0,
                "liquidation_levels_count_short": 0,
                "liquidation_volume": 0.0,
                "liquidation_levels_json": empty_levels,
                "liquidation_updated_ts": now_ms,
                "liquidation_last_event_ts": 0,
                "liquidation_staleness_ms": self.config.max_retention_seconds * 1000,
                "liquidation_is_stale": 1,
                "liquidation_no_events": 1,
                "liquidation_current_price": current_price,
                "liquidation_source": "binance",
                "native_worker_id": WORKER_ID,
            }

        mid_price = self.ewma_price.get(symbol) or float(dq[-1]["price"])
        self.ewma_price[symbol] = 0.9 * mid_price + 0.1 * float(dq[-1]["price"])
        ref_price = current_price if current_price > 0 else self.ewma_price[symbol]
        step = _bucket_step(float(self.ewma_price[symbol] or mid_price), tf)
        heat_long: dict[int, float] = defaultdict(float)
        heat_short: dict[int, float] = defaultdict(float)
        liq_volume = 0.0

        for event in dq:
            age_ms = max(0, now_ms - int(event["ts"]))
            weight = _decay_weight(float(event["notional"]), age_ms, window_ms)
            bucket = int(float(event["price"]) / step)
            if event["side"] == "LONG_LIQ":
                heat_long[bucket] += weight
            else:
                heat_short[bucket] += weight
            liq_volume += float(event["notional"])

        # Full level arrays (up to 20 significant levels per side)
        levels_long = self._extract_levels(heat_long, step)
        levels_short = self._extract_levels(heat_short, step)

        # Backward-compat top-3 fields
        top_long = levels_long[:3]
        top_short = levels_short[:3]
        long_level = levels_long[0]["price"] if levels_long else 0.0
        short_level = levels_short[0]["price"] if levels_short else 0.0
        long_strength = levels_long[0]["strength"] if levels_long else 0.0
        short_strength = levels_short[0]["strength"] if levels_short else 0.0

        # Zone clustering — merges nearby levels into sweep-target zones
        zones_long = self._compute_zones(levels_long, step)
        zones_short = self._compute_zones(levels_short, step)

        # Sweep targets: strongest zone MEANINGFULLY AWAY from the reference
        # price. Liquidations fire AT market price, so the strongest zone of
        # past events is almost always a few bps from ref_price — publishing
        # that as a "target" is a tautological echo (it kept every symbol
        # inside the regime gate's 35bps sweep-proximity condition). A real
        # target must sit beyond the zone's own half-width plus one bucket.
        def _sweep_target(zones: list[dict[str, Any]]) -> float | None:
            for zone in zones:
                center = float(zone.get("zone_center") or 0.0)
                if center <= 0 or ref_price <= 0:
                    continue
                half_width = (
                    float(zone.get("zone_high") or center)
                    - float(zone.get("zone_low") or center)
                ) / 2.0
                if abs(center - ref_price) > half_width + step:
                    return center
            return None

        sweep_target_long = _sweep_target(zones_long)
        sweep_target_short = _sweep_target(zones_short)

        last_event_ts = int(dq[-1]["ts"])
        long_distance_pct = abs(ref_price - long_level) / ref_price * 100 if long_level > 0 and ref_price else 100.0
        short_distance_pct = abs(short_level - ref_price) / ref_price * 100 if short_level > 0 and ref_price else 100.0
        staleness_ms = now_ms - last_event_ts

        # --- Derived scalar features for trainer tensor ---

        # Nearest level above / below current price (combined long + short)
        all_prices = sorted(
            [lv["price"] for lv in levels_long] + [lv["price"] for lv in levels_short]
        )
        nearest_above = next((p for p in all_prices if p > ref_price), 0.0)
        nearest_below = next((p for p in reversed(all_prices) if p < ref_price), 0.0)

        # Cascade risk v2: INTENSITY, not balance. The current decay-weighted
        # total liquidation strength ranked as a percentile of this
        # symbol×timeframe's own rolling history (self-adaptive: no static
        # notional thresholds, tail symbols rank against themselves). ~0 in
        # normal activity, ~1 only when this symbol's liquidation activity is
        # extreme by its own standards. None while the history is warming
        # (<20 samples) — honest missing, never guessed. The v1 value was
        # long_strength/total (a balance ratio, ≥0.5 on nearly every symbol
        # in any directional market) which made LIQUIDITY_SWEEP fire on ~half
        # of all regime classifications system-wide.
        total_strength = long_strength + short_strength
        intensity_now = float(sum(heat_long.values()) + sum(heat_short.values()))
        _hist = self.intensity_history.setdefault(symbol, {}).setdefault(
            tf, deque(maxlen=720)
        )
        if len(_hist) >= 20:
            cascade_risk = round(
                sum(1 for sample in _hist if sample < intensity_now) / len(_hist), 6
            )
        else:
            cascade_risk = None
        _hist.append(intensity_now)

        # Pressure direction: signed balance of long vs short strength, in [-1, +1].
        # +1 = massive long liquidation pressure (bears dominate); -1 = short liquidation pressure.
        pressure_direction = round((long_strength - short_strength) / (total_strength + 1e-9), 6) if total_strength > 0 else 0.0

        # Events in the last 5 minutes (using the deque, which already holds the retention window)
        five_min_ms = 5 * 60 * 1000
        count_5m = sum(1 for e in dq if (now_ms - int(e["ts"])) <= five_min_ms)

        # Sweep-target distances in basis points (bps = pct * 100)
        sweep_long_dist_bps: float | None = None
        sweep_short_dist_bps: float | None = None
        if sweep_target_long is not None and ref_price > 0:
            sweep_long_dist_bps = round(abs(sweep_target_long - ref_price) / ref_price * 10000, 2)
        if sweep_target_short is not None and ref_price > 0:
            sweep_short_dist_bps = round(abs(sweep_target_short - ref_price) / ref_price * 10000, 2)

        # Last-liquidation bps proxy: price deviation of the most recent event from
        # current price, signed by side. LONG_LIQ = longs hit below (-), SHORT_LIQ = shorts hit above (+).
        last_event = dq[-1]
        last_liq_bps_proxy: float = 0.0
        if ref_price > 0:
            raw_bps = (float(last_event["price"]) - ref_price) / ref_price * 10000
            last_liq_bps_proxy = round(raw_bps if last_event["side"] == "SHORT_LIQ" else -abs(raw_bps), 2)

        levels_json = json.dumps({
            "step": step,
            "current_price": ref_price,
            "top_long": top_long,
            "top_short": top_short,
            "levels_long": levels_long,
            "levels_short": levels_short,
            "zones_long": zones_long,
            "zones_short": zones_short,
            "sweep_target_long": sweep_target_long,
            "sweep_target_short": sweep_target_short,
            "event_count": len(dq),
            "staleness_ms": staleness_ms,
        })

        return {
            # Core level prices
            "liquidation_long_level": long_level,
            "liquidation_short_level": short_level,
            # Nearest level scalars for tensor
            "nearest_liquidation_level_above": nearest_above,
            "nearest_liquidation_level_below": nearest_below,
            # Strength per side
            "liquidation_long_strength": long_strength,
            "liquidation_short_strength": short_strength,
            # Distance from current price
            "liquidation_long_distance_pct": round(long_distance_pct, 4),
            "liquidation_short_distance_pct": round(short_distance_pct, 4),
            # Bps aliases under the field names the microstructure sweep
            # detector actually reads (its proximity inputs were silently
            # dead against the *_pct names).
            "distance_to_long_liq_bps": round(long_distance_pct * 100.0, 2),
            "distance_to_short_liq_bps": round(short_distance_pct * 100.0, 2),
            # Derived risk scalars (cascade = intensity percentile, see above)
            "liquidation_cascade_risk": cascade_risk,
            "liquidation_cascade_risk_semantics": "intensity_percentile_v2",
            "liquidation_intensity_decayed": round(intensity_now, 4),
            "liquidation_pressure_direction": pressure_direction,
            # 5m event count (computable from in-memory deque)
            "liquidation_count_5m": count_5m,
            # Last-event bps proxy (signed by liquidation side)
            "last_liq_bps_proxy": last_liq_bps_proxy,
            # Sweep targets
            "liquidation_sweep_target_long": sweep_target_long,
            "liquidation_sweep_target_short": sweep_target_short,
            "liquidation_sweep_target_long_distance_bps": sweep_long_dist_bps,
            "liquidation_sweep_target_short_distance_bps": sweep_short_dist_bps,
            # Zone / level counts
            "liquidation_zones_count_long": len(zones_long),
            "liquidation_zones_count_short": len(zones_short),
            "liquidation_levels_count_long": len(levels_long),
            "liquidation_levels_count_short": len(levels_short),
            # Aggregate notional
            "liquidation_volume": liq_volume,
            # JSON blob for heatmap visualization
            "liquidation_levels_json": levels_json,
            # Timestamps / staleness
            "liquidation_updated_ts": now_ms,
            "liquidation_last_event_ts": last_event_ts,
            "liquidation_staleness_ms": staleness_ms,
            "liquidation_is_stale": 1 if staleness_ms > STALENESS_STALE_MS else 0,
            "liquidation_no_events": 0,
            "liquidation_current_price": ref_price,
            "liquidation_source": "binance",
            "native_worker_id": WORKER_ID,
        }

    def _publish_mapping(self, symbol: str, tf: str, mapping: dict[str, Any], now_ms: int) -> None:
        unified_key = _v2_key(f"unified_features:{symbol}:{tf}")
        latest_key = f"{unified_key}:latest"
        level_key = _v2_key(f"liquidations:levels:{symbol}:{tf}")
        # Redis hset rejects None values — convert them to empty string so the
        # unified_features hash always stores a valid type. The JSON artifact
        # in level_key preserves the real None via json.dumps.
        hset_mapping = {k: ("" if v is None else v) for k, v in mapping.items()}
        pipe = self.redis.pipeline()
        pipe.hset(unified_key, mapping=hset_mapping)
        pipe.hset(latest_key, mapping=hset_mapping)
        pipe.set(level_key, json.dumps(mapping, sort_keys=True, default=str), ex=self.config.ttl_seconds)
        pipe.expire(unified_key, self.config.ttl_seconds)
        pipe.expire(latest_key, self.config.ttl_seconds)
        pipe.execute()
        self.last_publish[(symbol, tf)] = now_ms

    def _publish_updates(self, dirty: list[tuple[str, str]]) -> None:
        now_ms = int(time.time() * 1000)
        seen: set[tuple[str, str]] = set()
        for symbol, tf in dirty:
            key = (symbol, tf)
            if key in seen or symbol not in self.state:
                continue
            seen.add(key)
            mapping = self._compute_mapping(symbol, tf, now_ms)
            if mapping:
                self._publish_mapping(symbol, tf, mapping, now_ms)

    def _heartbeat_publish(self) -> None:
        now_ms = int(time.time() * 1000)
        published = 0
        for symbol in self.symbols:
            for tf in self.config.timeframes:
                last_pub = self.last_publish.get((symbol, tf), 0)
                if (now_ms - last_pub) < self.config.publish_heartbeat_sec * 1000:
                    continue
                mapping = self._compute_mapping(symbol, tf, now_ms)
                if mapping:
                    self._publish_mapping(symbol, tf, mapping, now_ms)
                    published += 1
        live_context = self._live_runtime_context()
        heartbeat = {
            "worker_id": WORKER_ID,
            "schema_version": "v2_liquidation_levels_engine_heartbeat_v1",
            "generated_utc": _utc_iso(),
            "stream_name": self.stream_name,
            "group_name": GROUP_NAME,
            "symbols_count": len(self.symbols),
            "timeframes": list(self.config.timeframes),
            "events_processed": self.events_processed,
            "events_ignored": self.events_ignored,
            "mappings_published_this_heartbeat": published,
            "dynamic_symbol_refresh_enabled": True,
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
            "runtime_mode": "LIVE_DATA_AND_LIVE_DECISION_INPUTS_TRADER_EXECUTION_DISABLED",
            "live_gate": live_context["live_gate"],
            "live_data_enabled": True,
            "live_decision_input_enabled": True,
            "trader_execution_enabled": live_context["trader_execution_enabled"],
            "execution_live_symbols": live_context["execution_live_symbols"],
            "approves_live": False,
            "approves_canary": False,
        }
        self.redis.set(_v2_key("liquidations:levels:heartbeat"), json.dumps(heartbeat), ex=self.config.ttl_seconds)

    def _live_runtime_context(self) -> dict[str, Any]:
        try:
            raw = self.redis.get(_v2_key("live_gate:state"))
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {}
        return {
            "live_gate": str(payload.get("live_gate") or "blocked_human_only"),
            "trader_execution_enabled": payload.get("trader_execution_enabled") is True,
            "execution_live_symbols": [
                str(symbol)
                for symbol in payload.get("execution_live_symbols") or payload.get("live_symbols") or []
                if _valid_liquidation_symbol(str(symbol))
            ],
        }

    def _cleanup_deques(self, now_ms: int) -> None:
        for symbol in self.symbols:
            for tf in self.config.timeframes:
                window_seconds = max(tf_to_seconds(tf) * 20, 2 * 3600)
                window_seconds = min(window_seconds, self.config.max_retention_seconds)
                window_ms = window_seconds * 1000
                dq = self.state[symbol][tf]
                while dq and (now_ms - int(dq[0]["ts"])) > window_ms:
                    dq.popleft()

    def _maybe_log(self) -> None:
        now = time.time()
        if now - self.last_log < 60:
            return
        self.last_log = now
        total_events = sum(len(self.state[s][tf]) for s in self.symbols for tf in self.config.timeframes)
        print(
            f"[{WORKER_ID}] heartbeat ok symbols={len(self.symbols)} "
            f"events_in_memory={total_events} processed={self.events_processed}",
            flush=True,
        )

    def run_once(self) -> None:
        self.refresh_symbols()
        self._heartbeat_publish()

    def run(self) -> None:
        print(
            f"[{WORKER_ID}] start stream={self.stream_name} group={GROUP_NAME} "
            f"consumer={CONSUMER_NAME}",
            flush=True,
        )
        while True:
            self.iteration_count += 1
            now_ms = int(time.time() * 1000)
            self.refresh_symbols()
            if self.iteration_count % CLEANUP_BATCH_INTERVAL == 0:
                self._cleanup_deques(now_ms)
            messages = self.redis.xreadgroup(
                groupname=GROUP_NAME,
                consumername=CONSUMER_NAME,
                streams={self.stream_name: ">"},
                count=self.config.batch_size,
                block=self.config.block_ms,
            )
            if not messages:
                self._heartbeat_publish()
                self._maybe_log()
                continue

            dirty: list[tuple[str, str]] = []
            for _, items in messages:
                for msg_id, fields in items:
                    try:
                        event = self._parse_event(dict(fields))
                        if not event:
                            self.events_ignored += 1
                            self.redis.xack(self.stream_name, GROUP_NAME, msg_id)
                            continue
                        symbol = str(event["symbol"])
                        for tf in self.config.timeframes:
                            self.state[symbol][tf].append(event)
                            dirty.append((symbol, tf))
                        self.events_processed += 1
                    finally:
                        self.redis.xack(self.stream_name, GROUP_NAME, msg_id)
            if time.time() - self._last_publish_ts >= 2.0 or len(dirty) < self.config.batch_size:
                self._publish_updates(dirty)
                self._heartbeat_publish()
                self._last_publish_ts = time.time()
            self._maybe_log()


def build_config(args: argparse.Namespace) -> EngineConfig:
    explicit = (
        tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        if args.symbols
        else None
    )
    return EngineConfig(
        redis_url=args.redis_url,
        stream_name=args.stream_name,
        timeframes=_parse_csv(args.timeframes, DEFAULT_TIMEFRAMES),
        block_ms=max(250, int(args.block_ms)),
        batch_size=max(1, int(args.batch_size)),
        ttl_seconds=max(60, int(args.ttl_seconds)),
        publish_heartbeat_sec=max(5, int(args.publish_heartbeat_sec)),
        symbol_refresh_sec=max(5, int(args.symbol_refresh_sec)),
        max_retention_seconds=max(3600, int(args.max_retention_seconds)),
        explicit_symbols=explicit,
        smoke_test=bool(args.smoke_test),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--redis-url", default=DEFAULT_REDIS_URL)
    parser.add_argument("--stream-name", default=DEFAULT_STREAM_NAME)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--block-ms", type=int, default=DEFAULT_BLOCK_MS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--publish-heartbeat-sec", type=int, default=DEFAULT_PUBLISH_HEARTBEAT_SEC)
    parser.add_argument("--symbol-refresh-sec", type=int, default=DEFAULT_SYMBOL_REFRESH_SEC)
    parser.add_argument("--max-retention-seconds", type=int, default=DEFAULT_MAX_RETENTION_SECONDS)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        engine = LevelEngine(build_config(args))
        if args.once:
            engine.run_once()
            print(json.dumps({"classification": "V2_LIQUIDATION_LEVELS_ENGINE_OK", "symbols_count": len(engine.symbols)}))
            return 0
        engine.run()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(json.dumps({"classification": "V2_LIQUIDATION_LEVELS_ENGINE_BLOCKED", "error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
