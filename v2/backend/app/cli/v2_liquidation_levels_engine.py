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

from v2.backend.app.services.market_data.current_price_resolver import (
    resolve_current_price,
)
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
MAX_FUTURE_CLOCK_SKEW_MS = 0
CLEANUP_BATCH_INTERVAL = 50
PENDING_CLAIM_INTERVAL = 12
PENDING_MIN_IDLE_MS = 60 * 1000
CASCADE_HISTORY_SAMPLE_INTERVAL_MS = max(
    1000,
    int(os.getenv("V2_LIQ_LEVELS_CASCADE_SAMPLE_INTERVAL_MS", "60000")),
)
MAX_EVENTS_PER_SYMBOL_TIMEFRAME = max(
    100,
    int(os.getenv("V2_LIQ_LEVELS_MAX_EVENTS_PER_SYMBOL_TIMEFRAME", "20000")),
)
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
VALID_LIQUIDATION_SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
OBSERVATION_SEMANTIC_KIND = "observed_forced_liquidation_clusters"
OBSERVATION_SEMANTIC_TYPE = (
    "retrospective_observed_forced_liquidation_clusters_not_future_thresholds"
)
FUTURE_LIQUIDATION_ALIAS_FIELDS = frozenset({
    "liquidation_long_level",
    "liquidation_short_level",
    "nearest_liquidation_level_above",
    "nearest_liquidation_level_below",
    "liquidation_long_strength",
    "liquidation_short_strength",
    "liquidation_long_distance_pct",
    "liquidation_short_distance_pct",
    "distance_to_long_liq_bps",
    "distance_to_short_liq_bps",
    "liquidation_sweep_target_long",
    "liquidation_sweep_target_short",
    "liquidation_sweep_target_long_distance_bps",
    "liquidation_sweep_target_short_distance_bps",
    "liquidation_zones_count_long",
    "liquidation_zones_count_short",
    "liquidation_levels_count_long",
    "liquidation_levels_count_short",
    "liquidation_levels_json",
})
QUARANTINE_MAXLEN = 2000
QUARANTINE_TTL_SECONDS = 7 * 24 * 3600

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


QUARANTINE_STREAM = _v2_key("liquidations:events:quarantine")


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


def observation_window_seconds(tf: str, max_retention_seconds: int) -> int:
    """Return a distinct, bounded observation window for each timeframe.

    A one-hour floor keeps the 1m view useful for sparse symbols without
    making 1m and 5m aliases of the same two-hour sample.
    """
    return min(max(tf_to_seconds(tf) * 20, 3600), max_retention_seconds)


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
        self.state_truncated: dict[str, dict[str, bool]] = {}
        self.seen_src_ids: dict[str, set[str]] = {}
        self.seen_src_id_order: dict[str, Deque[str]] = {}
        self.liquidation_event_price_ewma: dict[str, float | None] = {}
        # Rolling per-symbol×tf intensity samples (decay-weighted total
        # liquidation strength). cascade_risk v2 ranks the current sample
        # against this history so the value means "how extreme is this
        # symbol's liquidation activity vs its own recent past" — near 0 in
        # normal activity, high only in genuine cascades. (The v1 metric was
        # the long-side SHARE of strength: neutral at 0.5, ≥0.5 on nearly
        # every symbol during any directional market, which made the regime
        # gate classify ~half of all cycles as LIQUIDITY_SWEEP.)
        self.intensity_history: dict[str, dict[str, Deque[float]]] = {}
        self.intensity_history_last_sample_ms: dict[str, dict[str, int]] = {}
        self.last_publish: dict[tuple[str, str], int] = {}
        self.last_log = 0.0
        self.last_symbol_refresh = 0.0
        self.iteration_count = 0
        self.events_processed = 0
        self.events_ignored = 0
        self.events_deduplicated = 0
        self.events_quarantined = 0
        self.reject_reasons: dict[str, int] = defaultdict(int)
        self.pending_messages_recovered = 0
        self.pending_recovery_supported: bool | None = None
        self.capture_start_ms = int(time.time() * 1000)
        self.capture_start_ms_by_symbol: dict[str, int] = {}
        self.capture_observed_through_ms = 0
        self.capture_caught_up = False
        self.capture_gap_detected = False
        self.capture_group_lag: int | None = None
        self.capture_pending_count: int | None = None
        self.capture_status_error: str | None = None
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
            is_new_symbol = symbol not in self.state
            self.state.setdefault(
                symbol,
                {
                    tf: deque(maxlen=MAX_EVENTS_PER_SYMBOL_TIMEFRAME)
                    for tf in self.config.timeframes
                },
            )
            self.state_truncated.setdefault(
                symbol, {tf: False for tf in self.config.timeframes}
            )
            self.seen_src_ids.setdefault(symbol, set())
            self.seen_src_id_order.setdefault(symbol, deque())
            self.intensity_history.setdefault(
                symbol, {tf: deque(maxlen=720) for tf in self.config.timeframes}
            )
            self.intensity_history_last_sample_ms.setdefault(
                symbol, {tf: 0 for tf in self.config.timeframes}
            )
            for tf in self.config.timeframes:
                self.state[symbol].setdefault(
                    tf, deque(maxlen=MAX_EVENTS_PER_SYMBOL_TIMEFRAME)
                )
                self.state_truncated[symbol].setdefault(tf, False)
                self.intensity_history[symbol].setdefault(tf, deque(maxlen=720))
                self.intensity_history_last_sample_ms[symbol].setdefault(tf, 0)
            self.liquidation_event_price_ewma.setdefault(symbol, None)
            if is_new_symbol:
                self.capture_start_ms_by_symbol[symbol] = int(now * 1000)
        stale_symbols = set(self.state) - set(new_symbols)
        for symbol in stale_symbols:
            self.state.pop(symbol, None)
            self.state_truncated.pop(symbol, None)
            self.seen_src_ids.pop(symbol, None)
            self.seen_src_id_order.pop(symbol, None)
            self.liquidation_event_price_ewma.pop(symbol, None)
            self.intensity_history.pop(symbol, None)
            self.intensity_history_last_sample_ms.pop(symbol, None)
            self.capture_start_ms_by_symbol.pop(symbol, None)
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
            longest_window_seconds = max(
                observation_window_seconds(tf, self.config.max_retention_seconds)
                for tf in self.config.timeframes
            )
            observed_now_ms = int(time.time() * 1000)
            target_ms = observed_now_ms - longest_window_seconds * 1000
            first_entries = self.redis.xrange(
                self.stream_name, min="-", max="+", count=1
            )
            if first_entries:
                first_stream_ms = int(str(first_entries[0][0]).split("-", 1)[0])
                self.capture_start_ms = max(target_ms, first_stream_ms)
            else:
                self.capture_start_ms = observed_now_ms
            for symbol in self.symbols:
                self.capture_start_ms_by_symbol[symbol] = self.capture_start_ms
            self.redis.xgroup_setid(self.stream_name, GROUP_NAME, f"{target_ms}-0")
        except Exception as exc:
            self.capture_gap_detected = True
            print(f"[{WORKER_ID}] recent-tail reset skipped: {exc}")

    def _append_event(self, symbol: str, tf: str, event: dict[str, Any]) -> None:
        dq = self.state[symbol][tf]
        if dq.maxlen is not None and len(dq) >= dq.maxlen:
            self.state_truncated[symbol][tf] = True
        dq.append(event)

    def _remember_src_id(self, symbol: str, src_id: str) -> bool:
        """Return False for an already-seen ID; retain a bounded ID window."""
        if not src_id:
            return True
        seen = self.seen_src_ids[symbol]
        if src_id in seen:
            return False
        order = self.seen_src_id_order[symbol]
        while len(order) >= MAX_EVENTS_PER_SYMBOL_TIMEFRAME:
            seen.discard(order.popleft())
        order.append(src_id)
        seen.add(src_id)
        return True

    def _observation_coverage(
        self,
        symbol: str,
        tf: str,
        *,
        now_ms: int,
        window_ms: int,
    ) -> tuple[int, float, bool, bool]:
        capture_start_ms = int(
            self.capture_start_ms_by_symbol.get(symbol, self.capture_start_ms)
        )
        coverage_ms = max(0, now_ms - capture_start_ms)
        coverage_ratio = min(1.0, coverage_ms / window_ms) if window_ms > 0 else 0.0
        truncated = bool(self.state_truncated.get(symbol, {}).get(tf, False))
        complete = (
            coverage_ratio >= 1.0
            and self.capture_caught_up
            and not self.capture_gap_detected
            and not truncated
        )
        return capture_start_ms, coverage_ratio, complete, truncated

    @staticmethod
    def _redis_field(row: dict[Any, Any], name: str) -> Any:
        return row.get(name, row.get(name.encode("utf-8")))

    def _refresh_capture_status(self, *, now_ms: int | None = None) -> bool:
        """Prove the group has neither unread stream lag nor pending work."""
        observed_now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        try:
            group_rows = self.redis.xinfo_groups(self.stream_name)
            matching_group = next(
                (
                    row for row in group_rows
                    if str(self._redis_field(row, "name")).removeprefix("b'").rstrip("'")
                    == GROUP_NAME
                ),
                None,
            )
            if matching_group is None:
                raise RuntimeError("consumer_group_missing")
            raw_lag = self._redis_field(matching_group, "lag")
            if raw_lag is None:
                raise RuntimeError("consumer_group_lag_unavailable")
            group_lag = int(raw_lag)
            pending_summary = self.redis.xpending(self.stream_name, GROUP_NAME)
            if isinstance(pending_summary, dict):
                raw_pending = pending_summary.get(
                    "pending", pending_summary.get(b"pending")
                )
            elif isinstance(pending_summary, (tuple, list)) and pending_summary:
                raw_pending = pending_summary[0]
            else:
                raw_pending = pending_summary
            if raw_pending is None:
                raise RuntimeError("consumer_group_pending_unavailable")
            pending_count = int(raw_pending)
            self.capture_group_lag = group_lag
            self.capture_pending_count = pending_count
            self.capture_caught_up = group_lag == 0 and pending_count == 0
            self.capture_status_error = None
            if self.capture_caught_up:
                self.capture_observed_through_ms = observed_now_ms
            return self.capture_caught_up
        except Exception as exc:
            self.capture_caught_up = False
            self.capture_group_lag = None
            self.capture_pending_count = None
            self.capture_status_error = f"{type(exc).__name__}:{exc}"
            return False

    def _cascade_intensity_percentile(
        self,
        symbol: str,
        tf: str,
        *,
        intensity_now: float,
        now_ms: int,
        coverage_complete: bool,
    ) -> float | None:
        """Rank fixed-cadence intensity samples once PIT coverage is proven."""
        history = self.intensity_history.setdefault(symbol, {}).setdefault(
            tf, deque(maxlen=720)
        )
        risk: float | None = None
        if coverage_complete and len(history) >= 20:
            risk = round(
                sum(1 for sample in history if sample < intensity_now) / len(history),
                6,
            )
        last_samples = self.intensity_history_last_sample_ms.setdefault(
            symbol, {}
        )
        last_sample_ms = int(last_samples.get(tf) or 0)
        if (
            coverage_complete
            and (
                last_sample_ms <= 0
                or now_ms - last_sample_ms >= CASCADE_HISTORY_SAMPLE_INTERVAL_MS
            )
        ):
            history.append(float(intensity_now))
            last_samples[tf] = int(now_ms)
        return risk

    def _get_latest_price(self, symbol: str) -> dict[str, Any]:
        """Resolve an execution-grade market reference before event EWMA."""
        try:
            resolved = resolve_current_price(self.redis, symbol)
        except Exception as exc:
            resolved = {"reason_if_missing": f"resolver_error:{type(exc).__name__}"}
        try:
            resolved_price = float(resolved.get("price"))
        except (TypeError, ValueError):
            resolved_price = 0.0
        if (
            math.isfinite(resolved_price)
            and resolved_price > 0
            and resolved.get("execution_grade") is True
            and resolved.get("fallback_used") is not True
        ):
            return {
                "price": resolved_price,
                "source": f"current_price_resolver:{resolved.get('source') or 'unknown'}",
                "staleness_seconds": resolved.get("staleness_seconds"),
                "execution_grade": True,
                "resolver_reason": None,
            }

        fallback = self.liquidation_event_price_ewma.get(symbol)
        if fallback is not None and fallback > 0:
            return {
                "price": float(fallback),
                "source": "liquidation_event_price_ewma_fallback",
                "staleness_seconds": None,
                "execution_grade": False,
                "resolver_reason": resolved.get("reason_if_missing") or "no_fresh_market_price",
            }
        return {
            "price": 0.0,
            "source": "unavailable",
            "staleness_seconds": None,
            "execution_grade": False,
            "resolver_reason": resolved.get("reason_if_missing") or "no_fresh_market_price",
        }

    def _update_liquidation_event_price_ewma(self, event: dict[str, Any]) -> None:
        symbol = str(event["symbol"])
        price = float(event["price"])
        previous = self.liquidation_event_price_ewma.get(symbol)
        self.liquidation_event_price_ewma[symbol] = (
            price if previous is None else 0.9 * float(previous) + 0.1 * price
        )

    def _parse_event(
        self,
        fields: dict[str, str],
        *,
        now_ms: int | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        try:
            symbol = str(fields.get("symbol", "")).upper()
            if symbol not in self.state:
                return {}, "symbol_out_of_scope"
            event_time = int(fields.get("event_time") or fields.get("ts") or 0)
            ingested_at = int(fields.get("ingested_at") or fields.get("ingest_ts") or 0)
            available_at = int(fields.get("available_at") or 0)
            generated_at = int(fields.get("generated_at") or 0)
            feature_cutoff = int(fields.get("feature_cutoff") or 0)
            price = float(fields.get("price") or 0)
            qty = float(fields.get("qty") or 0)
            notional = float(fields.get("notional") or 0)
            side = str(fields.get("side", "")).upper()
            source = str(fields.get("source") or "")
            src_id = str(fields.get("src_id") or "")
        except Exception:
            return {}, "malformed_event"

        observed_now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        oldest_allowed_ms = observed_now_ms - self.config.max_retention_seconds * 1000
        if min(event_time, ingested_at, available_at, generated_at, feature_cutoff) <= 0:
            return {}, "missing_clock_lineage"
        if event_time < oldest_allowed_ms:
            return {}, "event_time_too_old"
        if event_time > observed_now_ms + MAX_FUTURE_CLOCK_SKEW_MS:
            return {}, "event_time_in_future"
        if ingested_at > observed_now_ms + MAX_FUTURE_CLOCK_SKEW_MS:
            return {}, "ingested_at_in_future"
        if available_at > observed_now_ms + MAX_FUTURE_CLOCK_SKEW_MS:
            return {}, "available_at_in_future"
        if generated_at > observed_now_ms + MAX_FUTURE_CLOCK_SKEW_MS:
            return {}, "generated_at_in_future"
        if ingested_at + MAX_FUTURE_CLOCK_SKEW_MS < event_time:
            return {}, "ingested_before_event"
        if available_at < ingested_at:
            return {}, "available_before_ingest"
        if generated_at < ingested_at:
            return {}, "generated_before_ingest"
        if generated_at > available_at:
            return {}, "generated_after_available"
        if feature_cutoff < event_time:
            return {}, "feature_cutoff_before_event"
        if feature_cutoff > available_at:
            return {}, "feature_cutoff_after_available"
        if (
            not all(math.isfinite(value) for value in (price, qty, notional))
            or price <= 0
            or qty <= 0
            or notional <= 0
        ):
            return {}, "invalid_numeric_value"
        if side not in {"LONG_LIQ", "SHORT_LIQ"}:
            return {}, "invalid_liquidation_side"
        if not source or not src_id:
            return {}, "missing_source_lineage"
        return {
            "ts": event_time,
            "event_time": event_time,
            "ingested_at": ingested_at,
            "available_at": available_at,
            "source_generated_at": generated_at,
            "feature_cutoff": feature_cutoff,
            "price": price,
            "qty": qty,
            "notional": notional,
            "side": side,
            "symbol": symbol,
            "source": source,
            "src_id": src_id,
        }, None

    def _quarantine_event(
        self,
        *,
        msg_id: str,
        fields: dict[str, str],
        reason: str,
        now_ms: int,
    ) -> None:
        if reason == "symbol_out_of_scope":
            return
        try:
            self.redis.xadd(
                QUARANTINE_STREAM,
                {
                    "source_stream": self.stream_name,
                    "source_message_id": str(msg_id),
                    "reason": reason,
                    "quarantined_at": str(now_ms),
                    "event": json.dumps(fields, sort_keys=True, default=str)[:8000],
                },
                maxlen=QUARANTINE_MAXLEN,
                approximate=True,
            )
            self.redis.expire(QUARANTINE_STREAM, QUARANTINE_TTL_SECONDS)
            self.events_quarantined += 1
        except Exception as exc:
            print(f"[{WORKER_ID}] quarantine write skipped: {exc}")

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
        return [
            {"price": round((b + 0.5) * step, 8), "strength": round(v, 4)}
            for b, v in significant
        ]

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
        window_seconds = observation_window_seconds(tf, self.config.max_retention_seconds)
        window_ms = window_seconds * 1000
        dq = self.state[symbol][tf]
        retained = [
            event for event in dq
            if 0 <= now_ms - int(event["ts"]) <= window_ms
        ]
        if len(retained) != len(dq):
            dq.clear()
            dq.extend(sorted(retained, key=lambda event: int(event["ts"])))

        price_reference = self._get_latest_price(symbol)
        current_price = float(price_reference["price"])
        current_price_source = str(price_reference["source"])
        current_price_staleness_seconds = price_reference.get("staleness_seconds")
        current_price_execution_grade = bool(price_reference.get("execution_grade"))
        current_price_resolver_reason = price_reference.get("resolver_reason")
        (
            coverage_start_ts,
            coverage_ratio,
            coverage_complete,
            observation_truncated,
        ) = self._observation_coverage(
            symbol,
            tf,
            now_ms=now_ms,
            window_ms=window_ms,
        )
        intensity_now = float(sum(
            _decay_weight(
                float(event["notional"]),
                max(0, now_ms - int(event["ts"])),
                window_ms,
            )
            for event in dq
        ))
        cascade_risk = self._cascade_intensity_percentile(
            symbol,
            tf,
            intensity_now=intensity_now,
            now_ms=now_ms,
            coverage_complete=coverage_complete,
        )
        if not dq or not current_price_execution_grade:
            has_events = bool(dq)
            if has_events:
                last_event = max(dq, key=lambda event: int(event["ts"]))
                last_event_ts = int(last_event["ts"])
                last_ingested_at = max(
                    int(event.get("ingested_at") or 0) for event in dq
                )
                staleness_ms = max(0, now_ms - last_event_ts)
                liq_volume = sum(float(event["notional"]) for event in dq)
                count_5m = sum(
                    1 for event in dq
                    if now_ms - int(event["ts"]) <= 5 * 60 * 1000
                )
            else:
                last_event_ts = 0
                last_ingested_at = 0
                staleness_ms = self.config.max_retention_seconds * 1000
                liq_volume = 0.0
                count_5m = 0
            no_fresh_reference = not current_price_execution_grade
            evidence_reason = (
                "no_fresh_market_price_reference"
                if no_fresh_reference
                else "no_liquidation_events_in_window"
            )
            step = _bucket_step(current_price, tf) if current_price > 0 else 0.0
            empty_levels = json.dumps({
                "step": step,
                "observed_top_long_clusters": [],
                "observed_top_short_clusters": [],
                "observed_clusters_long": [],
                "observed_clusters_short": [],
                "observed_cluster_zones_long": [],
                "observed_cluster_zones_short": [],
                "current_price": current_price,
                "current_price_source": current_price_source,
                "current_price_staleness_seconds": current_price_staleness_seconds,
                "current_price_execution_grade": current_price_execution_grade,
                "current_price_resolver_reason": current_price_resolver_reason,
                "semantic_kind": OBSERVATION_SEMANTIC_KIND,
                "semantic_type": OBSERVATION_SEMANTIC_TYPE,
                "window_seconds": window_seconds,
                "coverage_start_ts": coverage_start_ts,
                "coverage_ratio": round(coverage_ratio, 6),
                "coverage_complete": coverage_complete,
                "observation_truncated": observation_truncated,
                "evidence_unavailable_reason": evidence_reason,
                "event_count": len(dq),
                "event_time": last_event_ts,
                "ingested_at": last_ingested_at,
                "available_at": now_ms,
                "generated_at": now_ms,
                "feature_cutoff": last_event_ts,
            })
            return {
                "observed_forced_liquidation_cluster_long_price": None,
                "observed_forced_liquidation_cluster_short_price": None,
                "observed_forced_liquidation_cluster_nearest_above": None,
                "observed_forced_liquidation_cluster_nearest_below": None,
                "observed_forced_liquidation_cluster_long_strength": 0.0,
                "observed_forced_liquidation_cluster_short_strength": 0.0,
                "observed_forced_liquidation_cluster_long_distance_bps": None,
                "observed_forced_liquidation_cluster_short_distance_bps": None,
                # Fixed-cadence zero-activity observations become a real 0th
                # percentile only after full PIT coverage and warmup.
                "liquidation_cascade_risk": cascade_risk,
                "liquidation_cascade_risk_semantics": "intensity_percentile_v2",
                "liquidation_intensity_decayed": round(intensity_now, 4),
                "liquidation_pressure_direction": 0.0,
                "liquidation_count_5m": count_5m,
                "last_liq_bps_proxy": None,
                "observed_forced_liquidation_cluster_zones_count_long": 0,
                "observed_forced_liquidation_cluster_zones_count_short": 0,
                "observed_forced_liquidation_clusters_count_long": 0,
                "observed_forced_liquidation_clusters_count_short": 0,
                "liquidation_volume": liq_volume,
                "observed_forced_liquidation_clusters_json": empty_levels,
                "liquidation_updated_ts": now_ms,
                "liquidation_last_event_ts": last_event_ts,
                "liquidation_staleness_ms": staleness_ms,
                "liquidation_is_stale": 1,
                "liquidation_no_events": 0 if has_events else 1,
                "liquidation_no_fresh_market_reference": 1 if no_fresh_reference else 0,
                "liquidation_evidence_unavailable_reason": evidence_reason,
                "liquidation_current_price": current_price,
                "liquidation_current_price_source": current_price_source,
                "liquidation_current_price_staleness_seconds": current_price_staleness_seconds,
                "liquidation_current_price_execution_grade": 1 if current_price_execution_grade else 0,
                "liquidation_current_price_resolver_reason": current_price_resolver_reason,
                "liquidation_event_price_ewma": self.liquidation_event_price_ewma.get(symbol),
                "liquidation_semantic_kind": OBSERVATION_SEMANTIC_KIND,
                "liquidation_semantic_type": OBSERVATION_SEMANTIC_TYPE,
                "liquidation_observation_window_seconds": window_seconds,
                "liquidation_observation_coverage_start_ts": coverage_start_ts,
                "liquidation_observation_coverage_ratio": round(coverage_ratio, 6),
                "liquidation_observation_coverage_complete": 1 if coverage_complete else 0,
                "liquidation_observation_truncated": 1 if observation_truncated else 0,
                "event_time": last_event_ts,
                "ingested_at": last_ingested_at,
                "available_at": now_ms,
                "generated_at": now_ms,
                "feature_cutoff": last_event_ts,
                "liquidation_source": "binance",
                "native_worker_id": WORKER_ID,
            }

        ref_price = current_price
        step = _bucket_step(ref_price, tf)
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

        # Filter direction before strength truncation so >20 stronger
        # wrong-side buckets cannot hide a valid directional cluster.
        directional_long = {
            bucket: strength for bucket, strength in heat_long.items()
            if (bucket + 0.5) * step < ref_price
        }
        directional_short = {
            bucket: strength for bucket, strength in heat_short.items()
            if (bucket + 0.5) * step > ref_price
        }
        levels_long = self._extract_levels(directional_long, step)
        levels_short = self._extract_levels(directional_short, step)

        # Top observed clusters for the retrospective JSON contract.
        top_long = levels_long[:3]
        top_short = levels_short[:3]
        long_level = levels_long[0]["price"] if levels_long else 0.0
        short_level = levels_short[0]["price"] if levels_short else 0.0
        long_strength = levels_long[0]["strength"] if levels_long else 0.0
        short_strength = levels_short[0]["strength"] if levels_short else 0.0

        # Retrospective zone clustering for heatmap/diagnostic use only.
        zones_long = self._compute_zones(levels_long, step)
        zones_short = self._compute_zones(levels_short, step)

        last_event = max(dq, key=lambda event: int(event["ts"]))
        last_event_ts = int(last_event["ts"])
        last_ingested_at = max(int(event.get("ingested_at") or 0) for event in dq)
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
        # Pressure direction: signed balance of long vs short strength, in [-1, +1].
        # +1 = massive long liquidation pressure (bears dominate); -1 = short liquidation pressure.
        pressure_direction = round((long_strength - short_strength) / (total_strength + 1e-9), 6) if total_strength > 0 else 0.0

        # Events in the last 5 minutes (using the deque, which already holds the retention window)
        five_min_ms = 5 * 60 * 1000
        count_5m = sum(1 for e in dq if (now_ms - int(e["ts"])) <= five_min_ms)

        # Last-liquidation bps proxy: price deviation of the most recent event from
        # current price, signed by side. LONG_LIQ = longs hit below (-), SHORT_LIQ = shorts hit above (+).
        last_liq_bps_proxy: float = 0.0
        if ref_price > 0:
            raw_bps = (float(last_event["price"]) - ref_price) / ref_price * 10000
            last_liq_bps_proxy = round(raw_bps if last_event["side"] == "SHORT_LIQ" else -abs(raw_bps), 2)

        levels_json = json.dumps({
            "step": step,
            "current_price": ref_price,
            "current_price_source": current_price_source,
            "current_price_staleness_seconds": current_price_staleness_seconds,
            "current_price_execution_grade": current_price_execution_grade,
            "current_price_resolver_reason": current_price_resolver_reason,
            "liquidation_event_price_ewma": self.liquidation_event_price_ewma.get(symbol),
            "semantic_kind": OBSERVATION_SEMANTIC_KIND,
            "semantic_type": OBSERVATION_SEMANTIC_TYPE,
            "observed_top_long_clusters": top_long,
            "observed_top_short_clusters": top_short,
            "observed_clusters_long": levels_long,
            "observed_clusters_short": levels_short,
            "observed_cluster_zones_long": zones_long,
            "observed_cluster_zones_short": zones_short,
            "event_count": len(dq),
            "staleness_ms": staleness_ms,
            "window_seconds": window_seconds,
            "coverage_start_ts": coverage_start_ts,
            "coverage_ratio": round(coverage_ratio, 6),
            "coverage_complete": coverage_complete,
            "observation_truncated": observation_truncated,
            "event_time": last_event_ts,
            "ingested_at": last_ingested_at,
            "available_at": now_ms,
            "generated_at": now_ms,
            "feature_cutoff": last_event_ts,
        })

        return {
            # Explicit retrospective cluster fields. These are observed past
            # forced executions, never open-position liquidation thresholds.
            "observed_forced_liquidation_cluster_long_price": long_level or None,
            "observed_forced_liquidation_cluster_short_price": short_level or None,
            "observed_forced_liquidation_cluster_nearest_above": nearest_above or None,
            "observed_forced_liquidation_cluster_nearest_below": nearest_below or None,
            "observed_forced_liquidation_cluster_long_strength": long_strength,
            "observed_forced_liquidation_cluster_short_strength": short_strength,
            "observed_forced_liquidation_cluster_long_distance_bps": (
                round(long_distance_pct * 100.0, 2) if long_level > 0 else None
            ),
            "observed_forced_liquidation_cluster_short_distance_bps": (
                round(short_distance_pct * 100.0, 2) if short_level > 0 else None
            ),
            # Derived risk scalars (cascade = intensity percentile, see above)
            "liquidation_cascade_risk": cascade_risk,
            "liquidation_cascade_risk_semantics": "intensity_percentile_v2",
            "liquidation_intensity_decayed": round(intensity_now, 4),
            "liquidation_pressure_direction": pressure_direction,
            # 5m event count (computable from in-memory deque)
            "liquidation_count_5m": count_5m,
            # Last-event bps proxy (signed by liquidation side)
            "last_liq_bps_proxy": last_liq_bps_proxy,
            "observed_forced_liquidation_cluster_zones_count_long": len(zones_long),
            "observed_forced_liquidation_cluster_zones_count_short": len(zones_short),
            "observed_forced_liquidation_clusters_count_long": len(levels_long),
            "observed_forced_liquidation_clusters_count_short": len(levels_short),
            # Aggregate notional
            "liquidation_volume": liq_volume,
            # JSON blob for heatmap visualization
            "observed_forced_liquidation_clusters_json": levels_json,
            # Timestamps / staleness
            "liquidation_updated_ts": now_ms,
            "liquidation_last_event_ts": last_event_ts,
            "liquidation_staleness_ms": staleness_ms,
            "liquidation_is_stale": 1 if staleness_ms > STALENESS_STALE_MS else 0,
            "liquidation_no_events": 0,
            "liquidation_no_fresh_market_reference": 0,
            "liquidation_evidence_unavailable_reason": None,
            "liquidation_current_price": ref_price,
            "liquidation_current_price_source": current_price_source,
            "liquidation_current_price_staleness_seconds": current_price_staleness_seconds,
            "liquidation_current_price_execution_grade": 1 if current_price_execution_grade else 0,
            "liquidation_current_price_resolver_reason": current_price_resolver_reason,
            "liquidation_event_price_ewma": self.liquidation_event_price_ewma.get(symbol),
            "liquidation_semantic_kind": OBSERVATION_SEMANTIC_KIND,
            "liquidation_semantic_type": OBSERVATION_SEMANTIC_TYPE,
            "liquidation_observation_window_seconds": window_seconds,
            "liquidation_observation_coverage_start_ts": coverage_start_ts,
            "liquidation_observation_coverage_ratio": round(coverage_ratio, 6),
            "liquidation_observation_coverage_complete": 1 if coverage_complete else 0,
            "liquidation_observation_truncated": 1 if observation_truncated else 0,
            "event_time": last_event_ts,
            "ingested_at": last_ingested_at,
            "available_at": now_ms,
            "generated_at": now_ms,
            "feature_cutoff": last_event_ts,
            "liquidation_source": "binance",
            "native_worker_id": WORKER_ID,
        }

    def _publish_mapping(self, symbol: str, tf: str, mapping: dict[str, Any], now_ms: int) -> None:
        unified_key = _v2_key(f"unified_features:{symbol}:{tf}")
        latest_key = f"{unified_key}:latest"
        level_key = _v2_key(f"liquidations:levels:{symbol}:{tf}")
        dedicated_mapping = dict(mapping)
        for legacy_alias in FUTURE_LIQUIDATION_ALIAS_FIELDS:
            dedicated_mapping.pop(legacy_alias, None)
        for generic_clock in (
            "event_time",
            "ingested_at",
            "available_at",
            "generated_at",
            "feature_cutoff",
        ):
            if generic_clock in dedicated_mapping:
                dedicated_mapping.setdefault(
                    f"liquidation_{generic_clock}",
                    dedicated_mapping[generic_clock],
                )
        generic_clocks = {
            "event_time", "ingested_at", "available_at",
            "generated_at", "feature_cutoff",
        }
        hset_mapping = {
            key: value
            for key, value in dedicated_mapping.items()
            if key not in generic_clocks and value is not None
        }
        fields_to_delete = sorted(
            FUTURE_LIQUIDATION_ALIAS_FIELDS
            | {
                key for key, value in dedicated_mapping.items()
                if key not in generic_clocks and value is None
            }
        )
        pipe = self.redis.pipeline()
        if fields_to_delete:
            pipe.hdel(unified_key, *fields_to_delete)
            pipe.hdel(latest_key, *fields_to_delete)
        pipe.hset(unified_key, mapping=hset_mapping)
        pipe.hset(latest_key, mapping=hset_mapping)
        pipe.set(
            level_key,
            json.dumps(dedicated_mapping, sort_keys=True, default=str),
            ex=self.config.ttl_seconds,
        )
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

    def _claim_stale_pending(self) -> list[tuple[str, dict[str, str]]]:
        """Claim one bounded batch left pending by a failed/dead consumer."""
        try:
            response = self.redis.xautoclaim(
                self.stream_name,
                GROUP_NAME,
                CONSUMER_NAME,
                min_idle_time=PENDING_MIN_IDLE_MS,
                start_id="0-0",
                count=self.config.batch_size,
            )
            self.pending_recovery_supported = True
            items = list(response[1] if response and len(response) > 1 else [])
            self.pending_messages_recovered += len(items)
            return items
        except Exception as exc:
            if self.pending_recovery_supported is not False:
                print(f"[{WORKER_ID}] stale-pending recovery unavailable: {exc}")
            self.pending_recovery_supported = False
            self.capture_gap_detected = True
            return []

    def _process_stream_items(
        self,
        items: list[tuple[str, dict[str, str]]],
        *,
        now_ms: int | None = None,
    ) -> list[tuple[str, str]]:
        """Publish accepted events before ACK; rejected events are quarantined."""
        dirty: list[tuple[str, str]] = []
        accepted_message_ids: list[str] = []
        for msg_id, fields in items:
            observed_now_ms = (
                int(time.time() * 1000) if now_ms is None else int(now_ms)
            )
            event, reject_reason = self._parse_event(
                dict(fields), now_ms=observed_now_ms
            )
            if not event:
                self.events_ignored += 1
                reason = reject_reason or "unknown_rejection"
                self.reject_reasons[reason] += 1
                self._quarantine_event(
                    msg_id=str(msg_id),
                    fields=dict(fields),
                    reason=reason,
                    now_ms=observed_now_ms,
                )
                self.redis.xack(self.stream_name, GROUP_NAME, msg_id)
                continue
            symbol = str(event["symbol"])
            if not self._remember_src_id(symbol, str(event.get("src_id") or "")):
                self.events_deduplicated += 1
                self.redis.xack(self.stream_name, GROUP_NAME, msg_id)
                continue
            self._update_liquidation_event_price_ewma(event)
            for tf in self.config.timeframes:
                self._append_event(symbol, tf, event)
                dirty.append((symbol, tf))
            self.events_processed += 1
            accepted_message_ids.append(str(msg_id))

        if accepted_message_ids:
            # Any exception here leaves every accepted ID pending. On restart
            # XAUTOCLAIM replays it into clean in-memory state; no observation
            # is ACKed before its derived Redis mappings exist.
            self._publish_updates(dirty)
            self.redis.xack(
                self.stream_name,
                GROUP_NAME,
                *accepted_message_ids,
            )
        return dirty

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
            "events_deduplicated": self.events_deduplicated,
            "events_quarantined": self.events_quarantined,
            "reject_reasons": dict(self.reject_reasons),
            "pending_messages_recovered": self.pending_messages_recovered,
            "pending_recovery_supported": self.pending_recovery_supported,
            "ack_after_derived_publish": True,
            "capture_start_ms": self.capture_start_ms,
            "capture_start_ms_by_symbol": dict(self.capture_start_ms_by_symbol),
            "capture_observed_through_ms": self.capture_observed_through_ms,
            "capture_caught_up": self.capture_caught_up,
            "capture_gap_detected": self.capture_gap_detected,
            "capture_group_lag": self.capture_group_lag,
            "capture_pending_count": self.capture_pending_count,
            "capture_status_error": self.capture_status_error,
            "max_events_per_symbol_timeframe": MAX_EVENTS_PER_SYMBOL_TIMEFRAME,
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
                window_seconds = observation_window_seconds(
                    tf, self.config.max_retention_seconds
                )
                window_ms = window_seconds * 1000
                dq = self.state[symbol][tf]
                retained = [
                    event for event in dq
                    if 0 <= now_ms - int(event["ts"]) <= window_ms
                ]
                if len(retained) != len(dq):
                    dq.clear()
                    dq.extend(sorted(retained, key=lambda event: int(event["ts"])))

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
            if (
                self.iteration_count == 1
                or self.iteration_count % PENDING_CLAIM_INTERVAL == 0
            ):
                pending_items = self._claim_stale_pending()
                if pending_items:
                    self._process_stream_items(
                        pending_items,
                    )
            messages = self.redis.xreadgroup(
                groupname=GROUP_NAME,
                consumername=CONSUMER_NAME,
                streams={self.stream_name: ">"},
                count=self.config.batch_size,
                block=self.config.block_ms,
            )
            if not messages:
                self._refresh_capture_status()
                self._heartbeat_publish()
                self._maybe_log()
                continue

            dirty: list[tuple[str, str]] = []
            for _, items in messages:
                dirty.extend(
                    self._process_stream_items(
                        list(items),
                    )
                )
            self._refresh_capture_status()
            if time.time() - self._last_publish_ts >= 2.0 or len(dirty) < self.config.batch_size:
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
