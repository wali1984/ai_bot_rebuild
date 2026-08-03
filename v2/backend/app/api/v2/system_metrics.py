"""Read-only system + ingestor metrics for Monitor Center, System Health, and Markets ingestor pages.

All routes are READ-ONLY. They sample local host metrics (psutil/nvidia-smi)
and V2 Redis keys. They never write to Redis, never mutate any runtime, and
never touch the legacy bot. Every payload is streamable in realtime through
the existing ``/api/v2/ws/resource`` WebSocket by passing the route path.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.api.v2._common import get_redis

router = APIRouter(tags=["v2-system-metrics"])

DISPLAY_TZ = ZoneInfo("America/New_York")
_GPU_CACHE_TTL_SECONDS = 2.0
_HISTORY_MAX_SAMPLES = 180
_HISTORY_MIN_INTERVAL_SECONDS = 2.0

_lock = threading.Lock()
_gpu_cache: tuple[float, list[dict[str, Any]]] | None = None
_net_prev: tuple[float, int, int] | None = None
_history: deque[dict[str, Any]] = deque(maxlen=_HISTORY_MAX_SAMPLES)
_history_last_at = 0.0


def _prime_samplers() -> None:
    """Prime the psutil CPU reference and the network counter baseline at import.

    ``psutil.cpu_percent(interval=None)`` returns 0.0 on its first call per
    process (no prior reference), and ``_net_prev`` is None until the first
    sample — so a freshly-(re)started backend served cpu_total=0 and
    recv/sent_bytes_per_sec=null on the FIRST System Health load. Priming here
    means the first real request already computes a delta against this baseline.
    """
    global _net_prev
    try:
        import psutil

        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)
        net = psutil.net_io_counters()
        _net_prev = (time.monotonic(), net.bytes_recv, net.bytes_sent)
    except Exception:
        pass


_prime_samplers()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _nvidia_smi_gpus() -> list[dict[str, Any]]:
    global _gpu_cache
    now = time.monotonic()
    with _lock:
        if _gpu_cache is not None and now - _gpu_cache[0] <= _GPU_CACHE_TTL_SECONDS:
            return _gpu_cache[1]
    gpus: list[dict[str, Any]] = []
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 8:
                continue

            def _num(value: str) -> float | None:
                try:
                    return float(value)
                except ValueError:
                    return None

            gpus.append(
                {
                    "index": int(parts[0]) if parts[0].isdigit() else 0,
                    "name": parts[1],
                    "utilization_pct": _num(parts[2]),
                    "vram_used_mb": _num(parts[3]),
                    "vram_total_mb": _num(parts[4]),
                    "temperature_c": _num(parts[5]),
                    "power_draw_w": _num(parts[6]),
                    "power_limit_w": _num(parts[7]),
                    "source": "nvidia-smi",
                }
            )
    except Exception:
        gpus = []
    with _lock:
        _gpu_cache = (time.monotonic(), gpus)
    return gpus


def _trainer_gpu_view(r: Any) -> dict[str, Any] | None:
    """Trainer-published GPU view (same Redis source the mobile API uses)."""
    if r is None:
        return None
    try:
        raw = r.get("v2:trainer:hybrid_cuda:metrics")
        metrics = json.loads(raw) if raw else {}
    except Exception:
        return None
    if not isinstance(metrics, dict):
        return None
    training = metrics.get("training") or {}
    util = metrics.get("cuda_cpu_resource_utilization") or {}
    if not training and not util:
        return None
    return {
        "gpu_name": training.get("gpu_name") or util.get("gpu_name"),
        "device": training.get("device"),
        "cuda_active": bool(training.get("cuda_active") or util.get("cuda_available")),
        "utilization_pct": util.get("current_gpu_utilization"),
        "vram_used_mb": training.get("vram_allocated_mb") or util.get("current_vram_used_mb"),
        "training_steps_per_minute": util.get("training_steps_per_minute"),
        "source": "redis:v2:trainer:hybrid_cuda:metrics",
    }


def _sample_system(r: Any) -> dict[str, Any]:
    global _net_prev
    import psutil

    cpu_total = psutil.cpu_percent(interval=None)
    per_core = psutil.cpu_percent(interval=None, percpu=True)
    load1, load5, load15 = psutil.getloadavg()
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    du = shutil.disk_usage("/")
    net = psutil.net_io_counters()
    now = time.monotonic()
    rx_rate = tx_rate = None
    with _lock:
        if _net_prev is not None:
            dt = max(0.001, now - _net_prev[0])
            rx_rate = (net.bytes_recv - _net_prev[1]) / dt
            tx_rate = (net.bytes_sent - _net_prev[2]) / dt
        _net_prev = (now, net.bytes_recv, net.bytes_sent)
    gpus = _nvidia_smi_gpus()
    return {
        "cpu": {
            "total_pct": cpu_total,
            "per_core_pct": per_core,
            "core_count": len(per_core),
            "load_1m": load1,
            "load_5m": load5,
            "load_15m": load15,
        },
        "memory": {
            "used_mb": round(vm.used / 1048576),
            "total_mb": round(vm.total / 1048576),
            "percent": vm.percent,
            "swap_used_mb": round(swap.used / 1048576),
            "swap_total_mb": round(swap.total / 1048576),
        },
        "disk": {
            "mount": "/",
            "used_gb": round(du.used / 1073741824, 1),
            "total_gb": round(du.total / 1073741824, 1),
            "percent": round(du.used / du.total * 100, 1) if du.total else None,
        },
        "network": {
            "bytes_recv_total": net.bytes_recv,
            "bytes_sent_total": net.bytes_sent,
            "recv_bytes_per_sec": rx_rate,
            "sent_bytes_per_sec": tx_rate,
        },
        "gpus": gpus,
        "trainer_gpu_view": _trainer_gpu_view(r),
    }


@router.get("/system/metrics")
async def get_system_metrics() -> dict[str, Any]:
    """Host CPU/GPU/memory/disk/network utilization with a short history ring.

    Stream this in realtime via
    ``/api/v2/ws/resource?path=/api/v2/system/metrics&interval_ms=2000``.
    """
    global _history_last_at
    r = get_redis()
    sample = _sample_system(r)
    ts = _utc_now()
    now = time.monotonic()
    with _lock:
        if now - _history_last_at >= _HISTORY_MIN_INTERVAL_SECONDS:
            _history.append(
                {
                    "timestamp": ts,
                    "cpu_pct": sample["cpu"]["total_pct"],
                    "memory_pct": sample["memory"]["percent"],
                    "gpu_pct": (sample["gpus"][0]["utilization_pct"] if sample["gpus"] else None),
                    "gpu_vram_used_mb": (sample["gpus"][0]["vram_used_mb"] if sample["gpus"] else None),
                    "recv_bytes_per_sec": sample["network"]["recv_bytes_per_sec"],
                    "sent_bytes_per_sec": sample["network"]["sent_bytes_per_sec"],
                }
            )
            _history_last_at = now
        history = list(_history)
    return {
        "data": {**sample, "history": history},
        "source": "psutil + nvidia-smi + redis:v2:trainer",
        "source_type": "api",
        "endpoint": "/api/v2/system/metrics",
        "timestamp": ts,
        "received_at": ts,
        "lag_ms": 0,
        "stale": False,
        "missing_fields": [] if sample["gpus"] else ["gpus"],
        "warnings": [],
        "mode": "read_only",
    }


@router.get("/system/health")
async def get_system_health() -> dict[str, Any]:
    """Minimal JSON health contract for frontend/mobile runtime truth checks."""
    r = get_redis()
    redis_available = False
    if r is not None:
        try:
            redis_available = bool(r.ping())
        except Exception:
            redis_available = False
    ts = _utc_now()
    missing = [] if redis_available else ["redis"]
    return {
        "data": {
            "status": "ok" if redis_available else "degraded",
            "service": "ai-bot-v2-public-website-backend",
            "redis_available": redis_available,
            "live_gate": "blocked_human_only",
            "live_submit_allowed": False,
            "places_real_order": False,
            "exchange_mutation_enabled": False,
        },
        "source": "fastapi:system_health + redis:ping",
        "source_type": "redis_live" if redis_available else "unavailable",
        "endpoint": "/api/v2/system/health",
        "timestamp": ts,
        "received_at": ts,
        "lag_ms": 0,
        "stale": not redis_available,
        "missing_fields": missing,
        "warnings": [] if redis_available else ["Redis ping failed; health is degraded"],
        "mode": "read_only",
    }


# ---------------------------------------------------------------------------
# Ingestor status + per-ingestor chart metrics
# ---------------------------------------------------------------------------

# Maps every registry ingestor to the V2 Redis namespaces it feeds, plus how
# to extract a chart-ready numeric value from each per-symbol payload.
INGESTOR_FEEDS: dict[str, dict[str, Any]] = {
    "live_binance": {
        "title": "Binance USD-M Market Data",
        "pattern": "v2:market:prices:*",
        "ts_field": "fetched_utc",
        "value_fields": {
            "last_price": ("ticker_24hr", "lastPrice"),
            "volume_24h_quote": ("ticker_24hr", "quoteVolume"),
            "price_change_pct": ("ticker_24hr", "priceChangePercent"),
        },
    },
    "live_binance_liquidations": {
        "title": "Binance Liquidation Stream",
        "pattern": "v2:liquidations:levels:*",
        "ts_field": None,
        "value_fields": {},
    },
    "live_binance_mark_price": {
        # Read-only all-symbol mark/index price WS producer (hardened 2026-07-24
        # with restart resilience). ~159 TTL'd keys prove liveness.
        "title": "Binance USD-M Mark/Index Price WS",
        "pattern": "v2:market:mark_price:*",
        "ts_field": None,
        "value_fields": {},
    },
    "live_coinank": {
        "title": "CoinAnk Alt Data",
        "pattern": "v2:altdata:public_intel:symbol:*",
        # Paid direct feed (plan 3, 300 req/min). The scanned public-intel
        # namespace is refreshed hourly by the free-tier intel job, so trust the
        # direct ingestor's fresh liveness heartbeat for status instead.
        "heartbeat_key": "heartbeat:IngestCoinAnk",
        "ts_field": None,
        "value_fields": {},
    },
    "live_coinank_global_aggregator": {
        "title": "CoinAnk Global Aggregate Scores",
        "pattern": "v2:altdata:symbol_score:*",
        "heartbeat_key": "meta:coinank_global:last_update",
        "ts_field": None,
        "value_fields": {},
    },
    "live_kucoin": {
        "title": "KuCoin Spot Cross-Venue",
        "pattern": "v2:market:kucoin:latest:*",
        "ts_field": None,
        "value_fields": {"last_price": ("last",), "bid": ("bid",), "ask": ("ask",)},
    },
    "live_coinapi_v1": {
        "title": "CoinAPI REST",
        "pattern": "v2:market:coinapi:rest:status:*",
        "ts_field": None,
        "value_fields": {},
    },
    "live_coinapi_wsds": {
        "title": "CoinAPI Streaming OHLCV",
        "pattern": "v2:market:coinapi:ohlcv:*",
        "ts_field": None,
        "value_fields": {},
    },
    "live_technical_analysis": {
        "title": "Technical Analysis Engine",
        "pattern": "v2:technical_analysis:*",
        "ts_field": None,
        "value_fields": {},
    },
    "realtime_price_provider": {
        "title": "Realtime Price Provider",
        "pattern": "v2:orderbook:top:binance:*",
        "ts_field": None,
        "value_fields": {},
    },
    "liquidation_bridge": {
        "title": "Liquidation Bridge",
        "pattern": "v2:liquidations:*",
        "ts_field": None,
        "value_fields": {},
    },
    "liquidation_levels_engine": {
        "title": "Liquidation Levels Engine",
        "pattern": "v2:liquidations:levels:*",
        "ts_field": None,
        "value_fields": {},
    },
    "ccxt_historical": {
        "title": "CCXT Historical Backfill",
        "pattern": "v2:market:ccxt:*",
        "ts_field": None,
        "value_fields": {},
    },
    "moralis": {
        "title": "Moralis Smart-Money Flow",
        # Raw on-chain payload namespace the provider loop actually writes
        # (token_transfers/swaps/token_holders/token_price/metadata per contract) —
        # small (~19 keys). The legacy `v2:market:moralis:*` symbol-keyed bridge
        # namespace is not yet populated, so the ingestor read from an empty
        # pattern and falsely showed offline; point it at the live raw namespace so
        # status reflects genuine ingestion. Because this namespace is SPARSE, the
        # amortized deadline-bounded v2:* key-map scan can intermittently miss it
        # (flapping live->offline); the provider health key below is re-stamped
        # every loop cycle and acts as the authoritative liveness heartbeat, same
        # mechanism as CoinAnk. Downstream feature-bridge/consumer state
        # (whether these payloads become trainer features) is the authoritative
        # /api/v2/providers/status provider card (never green from heartbeat alone).
        "pattern": "v2:moralis:*",
        "heartbeat_key": "v2:provider:moralis:health",
        # Loop cadence is 300s (v2_moralis_provider_loop --sleep-seconds default);
        # 2 cycles + stamp latency before the feed stops reading "live".
        "live_within_seconds": 660,
        "ts_field": None,
        "value_fields": {},
    },
}

_MS_THRESHOLD = 10**12  # epoch ms vs s discriminator


def _extract_epoch_seconds(payload: Any) -> float | None:
    """Best-effort newest event time from a payload (ms or s epoch, or ISO).

    Timestamps more than 60s in the future (e.g. next-funding times or
    validity windows) are ignored so freshness ages stay meaningful.
    """
    if not isinstance(payload, dict):
        return None
    future_cutoff = time.time() + 60
    best: float | None = None
    for key in (
        "time",
        "timestamp",
        "T",
        "E",
        "closeTime",
        "fetched_at_ms",
        "updated_ms",
        "liquidation_last_event_ts",
        # Direct-ingestor heartbeat timestamps (epoch ms/s). CoinAnk's paid
        # direct feed writes {"ts_ms": ...}; other heartbeats use these fields.
        "ts_ms",
        "heartbeat_ts_ms",
        "heartbeat_at",
        "last_update",
        "last_update_ms",
        "last_run_ts",
        "last_snapshot_ms",
        # Derived records can represent an older source event while being
        # freshly recomputed from a current reference price.  Their numeric
        # lifecycle clocks are legitimate liveness evidence and must not be
        # discarded merely because they are epoch milliseconds rather than
        # ISO strings.
        "event_time",
        "ingested_at",
        "available_at",
        "generated_at",
        "feature_cutoff",
    ):
        value = payload.get(key)
        if isinstance(value, (int, float)) and value > 0:
            seconds = value / 1000 if value > _MS_THRESHOLD else value
            if seconds <= future_cutoff and (best is None or seconds > best):
                best = seconds
    for key in (
        "fetched_utc",
        "generated_utc",
        "updated_at",
        "as_of",
        "generated_at",
        "received_at",
        "event_time",
        "available_at",
    ):
        value = payload.get(key)
        if isinstance(value, str) and len(value) >= 19:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if parsed <= future_cutoff and (best is None or parsed > best):
                best = parsed
    return best


def _dig(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = payload
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if isinstance(node, str):
        try:
            return float(node)
        except ValueError:
            return None
    return node if isinstance(node, (int, float)) else None


_KEY_CACHE_TTL_SECONDS = 45.0
_key_cache: tuple[float, dict[str, list[str]]] | None = None
_key_cache_lock = threading.Lock()
_KEY_CACHE_PER_PATTERN_LIMIT = 120
_KEY_CACHE_BUILD_BUDGET_SECONDS = 0.25

# The V2 Redis holds >1M keys (feature snapshots, replay archives). One SCAN
# pass shared by all ingestor patterns — refreshed on a TTL — keeps these
# endpoints fast instead of running a full keyspace walk per pattern.
_SCAN_PREFIXES = tuple(
    {feed["pattern"].split("*", 1)[0] for feed in INGESTOR_FEEDS.values()}
)


def _pattern_key_map(r: Any) -> dict[str, list[str]]:
    global _key_cache
    now = time.monotonic()
    with _key_cache_lock:
        if _key_cache is not None and now - _key_cache[0] <= _KEY_CACHE_TTL_SECONDS:
            return _key_cache[1]
    import fnmatch

    buckets: dict[str, list[str]] = {name: [] for name in INGESTOR_FEEDS}
    cursor: int | str = 0
    deadline = time.monotonic() + _KEY_CACHE_BUILD_BUDGET_SECONDS
    try:
        while True:
            cursor, keys = r.scan(cursor=cursor, match="v2:*", count=1000)
            for key in keys:
                key_name = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key)
                for name, feed in INGESTOR_FEEDS.items():
                    bucket = buckets[name]
                    if len(bucket) >= _KEY_CACHE_PER_PATTERN_LIMIT:
                        continue
                    pattern = feed["pattern"]
                    prefix = pattern.split("*", 1)[0]
                    if key_name.startswith(prefix) and fnmatch.fnmatch(key_name, pattern):
                        bucket.append(key_name)
            if int(cursor) == 0:
                break
            if time.monotonic() >= deadline:
                break
            if all(len(bucket) >= _KEY_CACHE_PER_PATTERN_LIMIT for bucket in buckets.values()):
                break
    except Exception:
        return buckets
    with _key_cache_lock:
        _key_cache = (time.monotonic(), buckets)
    return buckets


def _scan_keys(r: Any, pattern: str, limit: int = 400) -> list[str]:
    for name, feed in INGESTOR_FEEDS.items():
        if feed["pattern"] == pattern:
            return _pattern_key_map(r).get(name, [])[:limit]
    keys: list[str] = []
    try:
        for key in r.scan_iter(match=pattern, count=5000):
            keys.append(key)
            if len(keys) >= limit:
                break
    except Exception:
        return []
    return keys


def _ingestor_row(r: Any, name: str, feed: dict[str, Any], now: float) -> dict[str, Any]:
    keys = _scan_keys(r, feed["pattern"]) if r is not None else []
    newest: float | None = None
    sampled = 0
    upstream_errors = 0
    if keys:
        try:
            pipe = r.pipeline()
            probe_keys = keys[:12]
            for key in probe_keys:
                pipe.get(key)
            for raw in pipe.execute():
                if raw is None:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                sampled += 1
                if isinstance(payload, dict):
                    http_status = payload.get("http_status")
                    if isinstance(http_status, int) and http_status >= 400:
                        upstream_errors += 1
                seconds = _extract_epoch_seconds(payload)
                if seconds is not None and (newest is None or seconds > newest):
                    newest = seconds
        except Exception:
            pass
    # Authoritative liveness heartbeat (e.g. CoinAnk's paid direct ingestor writes
    # heartbeat:IngestCoinAnk = {"ts_ms": ...}). The scanned data namespace can lag
    # (hourly free-tier refresh) while the ingestor is genuinely fresh — trust the
    # heartbeat when it is newer than the sampled payloads.
    hb_key = feed.get("heartbeat_key")
    if r is not None and hb_key:
        try:
            hb_raw = r.get(hb_key)
        except Exception:
            hb_raw = None
        if hb_raw is not None:
            hb_seconds: float | None = None
            try:
                hb_payload = json.loads(hb_raw)
                if isinstance(hb_payload, dict):
                    hb_seconds = _extract_epoch_seconds(hb_payload)
            except Exception:
                hb_payload = None
            if hb_seconds is None:
                # Bare epoch (ms or s) stored as a raw string, e.g.
                # meta:coinank_global:last_update = "1783819634817".
                try:
                    raw_num = float(str(hb_raw).strip())
                    if raw_num > 0:
                        candidate = raw_num / 1000 if raw_num > _MS_THRESHOLD else raw_num
                        if candidate <= now + 60:
                            hb_seconds = candidate
                except (TypeError, ValueError):
                    hb_seconds = None
            if hb_seconds is not None and (newest is None or hb_seconds > newest):
                newest = hb_seconds
    age = max(0.0, now - newest) if newest is not None else None
    # Liveness threshold is per-feed: slow-cadence feeds (Moralis polls every
    # 300s under its CU budget) would otherwise spend most of every healthy
    # cycle mislabeled "stale". Default 120s covers streaming feeds; a feed
    # override should be ~2x its real write cadence so one missed cycle still
    # reads live and two missed cycles honestly degrade to stale.
    live_within = float(feed.get("live_within_seconds") or 120)
    stale_within = max(3600.0, live_within * 4)
    if not keys:
        status = "not_started" if name == "ccxt_historical" else "offline"
    elif sampled and upstream_errors >= max(1, sampled // 2):
        status = "upstream_error"
    elif age is None:
        status = "unknown_freshness"
    elif age <= live_within:
        status = "live"
    elif age <= stale_within:
        status = "stale"
    else:
        status = "offline"
    provider_current = status == "live"
    provider_usable = provider_current
    provider_reason = None
    # Requirement classification (mirrors v2_ingestors_status_publisher):
    # CoinAPI is reclassified as OPTIONAL_ENRICHMENT / not a current source,
    # so consumers can render a calm "optional" state instead of an alarming
    # red OFFLINE for a provider the data plane does not depend on.
    optional_source = False
    requirement_class = feed.get("requirement_class")
    if name.startswith("live_coinapi"):
        optional_source = True
        requirement_class = "OPTIONAL_ENRICHMENT"
        if upstream_errors > 0:
            provider_usable = False
            provider_current = False
            provider_reason = "COINAPI_HTTP_FORBIDDEN_OR_EXPIRED_NOT_CURRENT_SOURCE"
        elif status != "live":
            provider_usable = False
            provider_current = False
            provider_reason = "COINAPI_NOT_LIVE_NOT_CURRENT_SOURCE"
    return {
        "name": name,
        "title": feed["title"],
        "redis_pattern": feed["pattern"],
        "key_count": len(keys),
        "sampled_payloads": sampled,
        "upstream_error_payloads": upstream_errors,
        "newest_event_age_seconds": round(age, 1) if age is not None else None,
        # Per-feed liveness threshold so UIs grade freshness against the feed's
        # real write cadence instead of a hardcoded 60s (moralis polls every 300s).
        "live_within_seconds": live_within,
        "stale_within_seconds": stale_within,
        "status": status,
        "provider_current": provider_current,
        "provider_usable": provider_usable,
        "provider_unusable_reason": provider_reason,
        "must_not_label_as_current_source": bool(provider_reason),
        "optional_source": optional_source,
        # None = not yet classified in this API (only the publisher payload
        # classifies every feed); never guessed here.
        "requirement_class": requirement_class,
        "core_data_plane_required": (
            requirement_class == "CORE_DATA_PLANE" if requirement_class else None
        ),
    }


_CANDLE_FINALITY_SAMPLE_KEY = "v2:market:ohlcv:binance:BTCUSDT:1m"


def _candle_finality_sample(r: Any, now: float) -> dict[str, Any] | None:
    """Causal candle-finality flags from the newest binance 1m OHLCV rows.

    Bounded: one exact-key GET on the canonical BTCUSDT 1m history (~100 rows).
    Surfaces the Codex causal-finality contract (candle_closed_confirmed /
    is_closed / feature_eligible, plus finality_cutoff_* when present) so
    consumers can see that feature inputs use closed candles only.
    """
    if r is None:
        return None
    try:
        raw = r.get(_CANDLE_FINALITY_SAMPLE_KEY)
    except Exception:
        return None
    if not raw:
        return None
    try:
        rows = json.loads(raw)
    except Exception:
        return None
    if not isinstance(rows, list) or not rows:
        return None
    dict_rows = [row for row in rows if isinstance(row, dict)]
    if not dict_rows:
        return None
    newest = dict_rows[-1]
    close_time = newest.get("candle_close_time") or newest.get("close_time")
    close_age = (
        round(max(0.0, now - float(close_time) / 1000.0), 1)
        if isinstance(close_time, (int, float)) and close_time > 0
        else None
    )
    return {
        "sample_key": _CANDLE_FINALITY_SAMPLE_KEY,
        "sample_symbol": newest.get("symbol") or "BTCUSDT",
        "timeframe": newest.get("timeframe") or "1m",
        "row_count": len(dict_rows),
        "closed_confirmed_row_count": sum(
            1 for row in dict_rows if row.get("candle_closed_confirmed") is True
        ),
        "feature_eligible_row_count": sum(
            1 for row in dict_rows if row.get("feature_eligible") is True
        ),
        "newest_candle_closed_confirmed": newest.get("candle_closed_confirmed"),
        "newest_is_closed": newest.get("is_closed"),
        "newest_feature_eligible": newest.get("feature_eligible"),
        "newest_candle_open_time_ms": newest.get("candle_open_time") or newest.get("open_time"),
        "newest_candle_close_time_ms": close_time,
        "newest_candle_close_age_seconds": close_age,
        "newest_source": newest.get("source"),
        # Present on feeds that stamp an explicit causal cutoff (e.g. the
        # CoinAnk OI backup rows); binance WSS rows carry closed-candle flags
        # instead — both are surfaced honestly, absent fields stay null.
        "finality_cutoff_ms": newest.get("finality_cutoff_ms"),
        "finality_cutoff_source_field": newest.get("finality_cutoff_source_field"),
        "policy": "FEATURE_INPUTS_MUST_USE_CLOSED_CANDLES",
    }


@router.get("/ingestors/status")
async def get_ingestors_status() -> dict[str, Any]:
    """Freshness/status of every registered ingestor, derived from live Redis keys.

    Stream via ``/api/v2/ws/resource?path=/api/v2/ingestors/status``.
    """
    r = get_redis()
    now = time.time()
    rows = [_ingestor_row(r, name, feed, now) for name, feed in INGESTOR_FEEDS.items()]
    finality = _candle_finality_sample(r, now)
    if finality is not None:
        for row in rows:
            if row.get("name") == "live_binance":
                row["candle_finality"] = finality
                break
    live = sum(1 for row in rows if row["status"] == "live")
    ts = _utc_now()
    return {
        "schema_version": "api_v2_ingestors_status_v1",
        "data": {
            "ingestors": rows,
            "counts": {
                "total": len(rows),
                "live": live,
                "stale": sum(1 for row in rows if row["status"] == "stale"),
                "offline": sum(1 for row in rows if row["status"] == "offline"),
                "not_started": sum(1 for row in rows if row["status"] == "not_started"),
                # Previously omitted buckets: the chip row summed to fewer than
                # `total` whenever a row was unknown_freshness/upstream_error.
                "unknown_freshness": sum(1 for row in rows if row["status"] == "unknown_freshness"),
                "upstream_error": sum(1 for row in rows if row["status"] == "upstream_error"),
                "other": sum(
                    1
                    for row in rows
                    if row["status"]
                    not in ("live", "stale", "offline", "not_started", "unknown_freshness", "upstream_error")
                ),
            },
        },
        "source": "redis:v2:* key freshness scan",
        "source_type": "redis_live" if r is not None else "unavailable",
        "endpoint": "/api/v2/ingestors/status",
        "timestamp": ts,
        "generated_at_utc": ts,
        "generated_at_et": datetime.now(DISPLAY_TZ).isoformat(timespec="seconds"),
        "received_at": ts,
        "lag_ms": 0,
        "staleness_seconds": 0,
        "freshness_status": "fresh" if r is not None else "unavailable",
        "canonical_owner": "/api/v2/ingestors/status",
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
        "data_quality_status": "fresh" if r is not None else "unavailable",
        "stale": r is None,
        "missing_fields": [] if r is not None else ["redis"],
        "warnings": [] if r is not None else ["Redis unavailable"],
        "mode": "read_only",
    }


def _symbol_from_key(key: str, pattern: str) -> str:
    prefix = pattern.rstrip("*")
    remainder = key[len(prefix):] if key.startswith(prefix) else key
    return remainder


@router.get("/ingestors/{name}/metrics")
async def get_ingestor_metrics(name: str, limit: int = 60) -> dict[str, Any]:
    """Chart-ready per-symbol values and freshness series for one ingestor.

    Stream via ``/api/v2/ws/resource?path=/api/v2/ingestors/{name}/metrics``.
    """
    feed = INGESTOR_FEEDS.get(name)
    endpoint = f"/api/v2/ingestors/{name}/metrics"
    if feed is None:
        return {
            "data": None,
            "source": "ingestor_registry",
            "source_type": "unavailable",
            "endpoint": endpoint,
            "timestamp": _utc_now(),
            "received_at": _utc_now(),
            "lag_ms": None,
            "stale": True,
            "missing_fields": ["ingestor"],
            "warnings": [f"Unknown ingestor '{name}'"],
            "mode": "read_only",
        }
    r = get_redis()
    limit = max(1, min(200, limit))
    rows: list[dict[str, Any]] = []
    now = time.time()
    if r is not None:
        keys = _scan_keys(r, feed["pattern"], limit=limit * 2)
        try:
            pipe = r.pipeline()
            probe_keys = keys[:limit]
            for key in probe_keys:
                pipe.get(key)
            raws = pipe.execute()
        except Exception:
            probe_keys, raws = [], []
        for key, raw in zip(probe_keys, raws):
            if raw is None:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            seconds = _extract_epoch_seconds(payload)
            row: dict[str, Any] = {
                "key": key,
                "symbol": _symbol_from_key(key, feed["pattern"]),
                "age_seconds": round(max(0.0, now - seconds), 1) if seconds is not None else None,
            }
            for label, path in feed["value_fields"].items():
                row[label] = _dig(payload, path)
            # Generic numeric surface: include top-level numeric fields so the
            # frontend can chart any feed without a bespoke extractor.
            numeric = {
                key_name: value
                for key_name, value in payload.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
            row["numeric_fields"] = dict(list(numeric.items())[:12])
            rows.append(row)
    rows.sort(key=lambda row: (row["age_seconds"] is None, row["age_seconds"] or 0))
    return {
        "data": {
            "ingestor": name,
            "title": feed["title"],
            "redis_pattern": feed["pattern"],
            "rows": rows,
            "row_count": len(rows),
        },
        "source": f"redis:{feed['pattern']}",
        "source_type": "redis_live" if r is not None else "unavailable",
        "endpoint": endpoint,
        "timestamp": _utc_now(),
        "received_at": _utc_now(),
        "lag_ms": 0,
        "stale": r is None,
        "missing_fields": [] if rows else ["rows"],
        "warnings": [] if r is not None else ["Redis unavailable"],
        "mode": "read_only",
    }
