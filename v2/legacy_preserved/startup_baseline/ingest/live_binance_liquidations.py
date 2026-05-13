"""Real-time Binance Futures forced liquidation (force order) ingestion & aggregation.


Captures events via websocket (!forceOrder@arr) and maintains:
 1. Raw recent events list (trimmed) at key: binance:force:raw
 2. Rolling aggregations (1m / 5m / 15m / 30m / 1h):
             binance:force:stats:1m | :5m | :15m | :30m | :1h each -> {
                     window_ms, updated, count_total, count_buy, count_sell,
                     notional_buy, notional_sell, net_imbalance, pressure,
                     symbols: {                            agg['symbols'] = sym_stats
                            try:
                                r.set(redis_key, json.dumps(agg))
                                update_counter("redis_writes")
                                # Log aggregation summary for this window
                                logger.info(f"[AGGREGATE] {w//60}min AGG: {agg['count_total']} liq ({agg['count_buy']} buy, {agg['count_sell']} sell), "
                                          f"${agg['notional_buy']:.0f} vs ${agg['notional_sell']:.0f}, pressure={agg['pressure']:.3f}")
                                verbose_log(f"Redis write: {redis_key} <- aggregation with {len(sym_stats)} symbols")
                                
                                # Write normalized liquidation aggregations
                                if normalizer and ENABLE_NORMALIZATION:
                                    try:
                                        # Map window seconds to timeframe string
                                        tf_map = {60: "1m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1h"}
                                        tf = tf_map.get(w, f"{w}s")
                                        
                                        # Write per-symbol normalized liquidation features
                                        for sym_s, sdata in sym_stats.items():
                                            if sym_s not in SYMBOLS:
                                                continue
                                            
                                            normalized_data = {
                                                "symbol": sym_s,
                                                "timeframe": tf,
                                                "timestamp": now_ms,
                                                "liq_count_total": sdata['buy'] + sdata['sell'],
                                                "liq_count_buy": sdata['buy'],
                                                "liq_count_sell": sdata['sell'],
                                                "liq_notional_buy": sdata['notional_buy'],
                                                "liq_notional_sell": sdata['notional_sell'],
                                                "liq_pressure": sdata.get('pressure', 0),
                                                "source": "binance_liquidations"
                                            }
                                            
                                            normalized = normalizer.normalize(normalized_data, source="binance_liquidations", enable_normalization=True)
                                            normalized_key = f"features:liquidations:{sym_s}:{tf}:normalized"
                                            r.setex(normalized_key, 300, json.dumps(normalized))
                                            
                                        logger.debug(f"✅ Normalized liquidations for {len([s for s in sym_stats.keys() if s in SYMBOLS])} symbols @ {tf}")
                                    except Exception as norm_err:
                                        logger.error(f"❌ Liquidations normalization error: {norm_err}")
                                
                                # Optional: publish additive V2 rollups under v2: prefixuy, sell, notional_buy, notional_sell, last_ts, pressure}}
             }

Pressure = (notional_sell - notional_buy) / total_notional. Positive => sell-side forced liquidation dominance.

Notes:
- Binance may return two message shapes for !forceOrder@arr:
        1) Combined stream envelope: {"stream":"!forceOrder@arr","data":[ {e:"forceOrder", o:{...}}, ... ]}
        2) Direct array when using /ws: [ {e:"forceOrder", o:{...}}, ... ]
    This ingestor supports both.
"""
import asyncio, json, os, sys, time, traceback, math, socket
import aiohttp
from aiohttp import resolver, TCPConnector
from collections import deque, defaultdict
from datetime import datetime, timezone
from pathlib import Path
try:
    from utils.interpreter_guard import ensure_correct_interpreter
    ensure_correct_interpreter(strict=False)
except Exception:
    pass

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from utils.redis_client import get_redis
    from utils.healthbeat import start_heartbeat, report_exit
    from utils.interrupt_lock import exit_if_already_running
    from utils.logger import get_logger
    from utils.redis_hardening import create_hardened_redis_client, safe_redis_operation
    from utils.websocket_limits import WebSocketLimiter, WebSocketLimitConfig
    from utils.data_normalizer import DataNormalizer
    from config import ENABLE_NORMALIZATION
    
    # Dynamic symbol loading - supports hot-reload without restart
    try:
        from utils.symbol_manager import get_symbols_cached
        SYMBOLS = get_symbols_cached()
    except ImportError:
        from config import SYMBOLS
    # Import Telegram alerts for service notifications
    try:
        from telegram_alerts import TelegramNotifier
        TELEGRAM_AVAILABLE = True
    except ImportError:
        TELEGRAM_AVAILABLE = False
        TelegramNotifier = None
    # V2 flags & settings (all default OFF; additive-only behavior)
    try:
        from config import (
            EXP_MODEL_V2,
            ENABLE_LL_1M5M_FEATURES,
            ENABLE_SPOOF_DETECT,
            REDIS_PREFIX_V2,
            DATA_WINDOWS,
        )
    except Exception:
        # Default fallbacks if config import shape changes
        EXP_MODEL_V2 = False
        ENABLE_LL_1M5M_FEATURES = False
        ENABLE_SPOOF_DETECT = False
        REDIS_PREFIX_V2 = "v2:"
        DATA_WINDOWS = {"liq_win_1m": 60, "liq_win_5m": 300}
except ImportError as e:
    raise ImportError(f"Import failure: {e}")

# Fail-fast Redis health check - must be reachable before starting ingestor
try:
    sys.path.insert(0, str(ROOT_DIR.parent))  # Add root for tools
    from tools.health import assert_redis_up
    assert_redis_up()
except ImportError:
    print("[WARNING] Redis health check not available, proceeding...")
except SystemExit:
    raise  # Re-raise the Redis failure message

logger = get_logger("binance_liquidations")

# Initialize data normalizer for schema standardization
try:
    normalizer = DataNormalizer()
except Exception as e:
    normalizer = None
    logger.warning(f"DataNormalizer not available - normalization disabled: {e}")

MAX_WS_STREAMS = int(os.getenv("BINANCE_MAX_STREAMS", "1024"))
MAX_WS_CONNECTIONS = int(os.getenv("BINANCE_MAX_CONNECTIONS", "300"))
WS_CONNECTION_WINDOW_SECONDS = int(os.getenv("BINANCE_WS_CONNECTION_WINDOW_SECONDS", "300"))

_ws_limit_config = WebSocketLimitConfig(
    max_streams=MAX_WS_STREAMS,
    max_connections=MAX_WS_CONNECTIONS,
    window_seconds=WS_CONNECTION_WINDOW_SECONDS,
)
WS_LIMITER = WebSocketLimiter(_ws_limit_config, logger=logger)

# Diagnostic logging and debug configuration
DEBUG_MODE = os.getenv("RLBOT_DEBUG", "0") == "1"
VERBOSE_MODE = "--verbose" in sys.argv or DEBUG_MODE

# Message counters and sampling for diagnostics
message_counters = {
    "total_received": 0,
    "processed_events": 0,
    "redis_writes": 0,
    "errors": 0,
    "heartbeats": 0
}

# First-N sampler configuration
FIRST_N_SAMPLE = 10 if DEBUG_MODE else 0
first_n_counter = 0

def debug_log(msg: str):
    """Log debug messages only when debug mode is enabled"""
    if DEBUG_MODE:
        logger.info(f"[DEBUG] {msg}")

def verbose_log(msg: str):
    """Log verbose messages when verbose mode is enabled"""
    if VERBOSE_MODE:
        logger.info(f"[VERBOSE] {msg}")

def update_counter(key: str, increment: int = 1):
    """Update message counter and optionally write to Redis"""
    message_counters[key] += increment
    if DEBUG_MODE:
        r = get_redis()
        if r:
            try:
                r.hincrby("debug:binance_liquidations:counters", key, increment)
            except Exception:
                pass

def write_diagnostic_heartbeat():
    """Write enhanced heartbeat with diagnostic info"""
    r = get_redis()
    if r:
        try:
            heartbeat_data = {
                "timestamp": int(time.time() * 1000),
                "counters": message_counters.copy() if DEBUG_MODE else None
            }
            r.set('heartbeat:IngestLiquidations', json.dumps(heartbeat_data))
            update_counter("heartbeats")
            if DEBUG_MODE:
                r.set("debug:binance_liquidations:status", json.dumps({
                    "last_heartbeat": heartbeat_data["timestamp"],
                    "counters": message_counters,
                    "debug_mode": DEBUG_MODE,
                    "verbose_mode": VERBOSE_MODE
                }))
        except Exception as e:
            debug_log(f"Heartbeat write failed: {e}")

def sample_first_n_message(msg_data: dict, msg_type: str = "liquidation"):
    """Log first N messages for diagnostic sampling"""
    global first_n_counter
    if FIRST_N_SAMPLE > 0 and first_n_counter < FIRST_N_SAMPLE:
        first_n_counter += 1
        debug_log(f"SAMPLE #{first_n_counter} {msg_type}: {json.dumps(msg_data, default=str)}")

# Startup diagnostic log
if DEBUG_MODE:
    debug_log("Binance liquidations ingestor starting in DEBUG mode")
if VERBOSE_MODE:
    verbose_log("Binance liquidations ingestor starting in VERBOSE mode")

RAW_KEY = "binance:force:raw"
PER_SYMBOL_RAW_PREFIX = "binance:force:raw:"  # binance:force:raw:BTCUSDT
AGG_WINDOWS = {
    60: "binance:force:stats:1m",
    300: "binance:force:stats:5m",
    900: "binance:force:stats:15m",
    1800: "binance:force:stats:30m",
    3600: "binance:force:stats:1h",
}
MAX_RAW = 2000
ERROR_KEY = "proc:last_error:IngestLiquidations"

# Running stats (Welford) for per-symbol 1m pressure & notional to derive z-scores
# MEMORY FIX: Pre-initialize only for configured symbols to prevent unbounded growth
_sym_running = {
    sym: {
        'n': 0,
        'mean_pressure': 0.0,
        'M2_pressure': 0.0,
        'mean_notional': 0.0,
        'M2_notional': 0.0,
    }
    for sym in SYMBOLS
}

def _welford_update(stats: dict, key_mean: str, key_M2: str, new_value: float):
    # stats must have 'n'
    stats['n'] += 1
    n = stats['n']
    delta = new_value - stats[key_mean]
    stats[key_mean] += delta / n
    delta2 = new_value - stats[key_mean]
    stats[key_M2] += delta * delta2

def _welford_get_z(stats: dict, key_mean: str, key_M2: str, value: float) -> float:
    n = stats.get('n', 0)
    if n < 30:  # wait for some history
        return 0.0
    var = stats[key_M2] / (n - 1) if n > 1 else 0.0
    if var <= 1e-12:
        return 0.0
    sd = math.sqrt(var)
    return (value - stats[key_mean]) / sd

_shutdown = False

def _now_ms():
    return int(time.time() * 1000)

async def _dns_preflight(host: str):
    """DNS preflight check to verify hostname resolution before websocket connection"""
    try:
        loop = asyncio.get_running_loop()
        # Try IPv4 first (more reliable on Windows)
        try:
            infos = await loop.getaddrinfo(host, 443, family=socket.AF_INET, proto=socket.IPPROTO_TCP)
            ips = sorted({ai[4][0] for ai in infos})
            logger.info(f"[preflight] DNS OK for {host} (IPv4): {ips}")
            return True
        except Exception as ipv4_error:
            logger.info(f"IPv4 DNS failed for {host}: {ipv4_error}, trying fallback...")
            # Fallback to any family
            infos = await loop.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
            ips = sorted({ai[4][0] for ai in infos})
            logger.info(f"[preflight] DNS OK for {host} (fallback): {ips}")
            return True
    except Exception as e:
        logger.error(f"[preflight] DNS failed for {host}: {e}")
        # Try synchronous fallback
        try:
            result = socket.gethostbyname(host)
            logger.info(f"[preflight] Sync DNS OK for {host}: {result}")
            return True
        except Exception as sync_error:
            logger.error(f"[preflight] Sync DNS also failed for {host}: {sync_error}")
            return False

def _create_session():
    """Create aiohttp ClientSession with system DNS resolver (no aiodns/pycares)"""
    force_system = os.getenv("AIOHTTP_FORCE_SYSTEM_RESOLVER", "1") == "1"
    if force_system:
        # Force system resolver to avoid aiodns/pycares issues on Windows
        _dns_resolver = resolver.DefaultResolver()
        _connector = TCPConnector(
            resolver=_dns_resolver,
            ttl_dns_cache=60,
            family=socket.AF_INET  # prefer IPv4 on Windows
        )
        return aiohttp.ClientSession(connector=_connector)
    else:
        return aiohttp.ClientSession()

async def consume_force_orders():
    debug_log("Starting Binance liquidations consumer with safe preflights")
    
    # Safe preflight: Check aiohttp availability
    try:
        import aiohttp  # type: ignore
        verbose_log("aiohttp import successful")
    except ImportError:
        logger.error("aiohttp not installed; liquidation stream inactive. Install aiohttp to enable.")
        update_counter("errors")
        # Idle loop writing heartbeat so orchestrator doesn't restart endlessly
        r = get_redis()
        for _ in range(60):  # ~60*5s = 5 minutes idle before function returns for retry
            if r:
                try:
                    write_diagnostic_heartbeat()
                except Exception:
                    pass
            await asyncio.sleep(5)
        return
    
    # Safe preflight: Validate Redis connectivity
    r = get_redis()
    if not r:
        logger.error("Redis connection unavailable; liquidation stream cannot persist data")
        update_counter("errors")
        return
    else:
        verbose_log("Redis connectivity confirmed")
    
    # Safe preflight: Test Redis write capability
    try:
        test_key = "test:binance_liquidations:startup"
        r.set(test_key, "startup_test", ex=10)
        debug_log("Redis write capability confirmed")
    except Exception as e:
        logger.error(f"Redis write test failed: {e}")
        update_counter("errors")
    
    # Prefer combined stream endpoint; fallback to legacy /ws form
    STREAM_URLS = [
        os.getenv("BINANCE_FORCE_WS_URL", "wss://fstream.binance.com/stream?streams=!forceOrder@arr"),
        "wss://fstream.binance.com/ws/!forceOrder@arr",
    ]

    WS_LIMITER.validate_stream_count(1, context="force_order")
    
    debug_log(f"Configured stream URLs: {STREAM_URLS}")
    
    # Optional single-instance guard for liquidation ingestor
    try:
        if r and os.getenv("LIQ_SINGLETON", "1") == "1":
            _lock_key = "lock:live_binance_liq"
            got = r.set(_lock_key, str(_now_ms()), nx=True, ex=180)
            if not got:
                logger.warning("Another live_binance_liquidations instance holds the lock; exiting consume loop.")
                # keep a short idle to let supervisor backoff
                for _ in range(6):
                    try:
                        if r:
                            write_diagnostic_heartbeat()
                    except Exception:
                        pass
                    await asyncio.sleep(5)
                return
            else:
                debug_log("Acquired singleton lock for liquidations ingestor")
    except Exception as e:
        debug_log(f"Lock acquisition failed: {e}")
        pass
    # Use bounded deque to prevent unbounded memory growth
    # Keep latest 4000 events (typically covers 1-hour window at reasonable volume)
    events = deque(maxlen=4000)

    # Helper to persist heartbeat with diagnostics
    async def _hb():
        if not r:
            return
        try:
            write_diagnostic_heartbeat()
        except Exception as e:
            debug_log(f"Heartbeat failed: {e}")
            pass

    # Iterate over endpoints until one works; on drop, retry outer loop
    for STREAM_URL in STREAM_URLS:
        session = None
        try:
            # DNS preflight check
            if "fstream.binance.com" in STREAM_URL:
                if not await _dns_preflight("fstream.binance.com"):
                    logger.warning("DNS preflight failed for fstream.binance.com, trying next URL...")
                    continue
            elif "dstream.binance.com" in STREAM_URL:
                if not await _dns_preflight("dstream.binance.com"):
                    logger.warning("DNS preflight failed for dstream.binance.com, trying next URL...")
                    continue
            
            session = _create_session()
            await WS_LIMITER.acquire_async()
            async with session.ws_connect(STREAM_URL, heartbeat=30, ssl=True) as ws:
                print(f"🔗 Connected to Binance liquidations websocket: {STREAM_URL}")
                logger.info(f"🔗 Connected to Binance liquidations websocket: {STREAM_URL}")
                print(f"📡 Listening for forced liquidation events...")
                logger.info(f"📡 Listening for forced liquidation events...")
                # small heartbeat to mark connection
                await _hb()
                while not _shutdown:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=65)
                    except asyncio.TimeoutError:
                        logger.warning("forceOrder socket timeout; sending ping")
                        try:
                            await ws.ping()
                        except Exception:
                            break
                        # still maintain heartbeat even if no data
                        await _hb()
                        continue
                    except Exception as e:
                        logger.error(f"Websocket receive error: {e}")
                        update_counter("errors")
                        if r:
                            try:
                                r.set(ERROR_KEY, f"recv_error: {e}")
                            except Exception:
                                pass
                        break
                    if msg.type == aiohttp.WSMsgType.CLOSED:
                        logger.warning("Websocket closed by server")
                        break
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        await _hb()
                        continue
                    try:
                        payload = json.loads(msg.data)
                        update_counter("total_received")
                        
                        # First-N diagnostic sampling of raw messages
                        if DEBUG_MODE:
                            sample_first_n_message(payload, "raw_websocket")
                            
                    except Exception as e:
                        update_counter("errors")
                        debug_log(f"JSON decode failed: {e}")
                        await _hb()
                        continue

                    # Normalize message to a list of event dicts containing 'o' or direct fields
                    norm_events = []
                    if isinstance(payload, list):
                        norm_events = payload
                        verbose_log(f"Received direct array payload with {len(payload)} items")
                    elif isinstance(payload, dict):
                        if 'data' in payload:  # combined stream envelope
                            inner = payload.get('data')
                            if isinstance(inner, list):
                                norm_events = inner
                                verbose_log(f"Received combined stream envelope with {len(inner)} items")
                            elif isinstance(inner, dict):
                                norm_events = [inner]
                                verbose_log("Received combined stream envelope with single item")
                        else:
                            norm_events = [payload]
                            verbose_log("Received direct payload object")

                    debug_log(f"Normalized to {len(norm_events)} events for processing")

                    for item in norm_events:
                        evt = item.get('o') if isinstance(item, dict) else None
                        # Some variants may not wrap in 'o'; use the item itself
                        if not evt and isinstance(item, dict):
                            evt = item
                        if not isinstance(evt, dict):
                            continue
                        try:
                            symbol = evt.get('s')
                            side = evt.get('S')
                            # Price and qty can be found under different keys; prefer executed values
                            price = float(evt.get('ap') or evt.get('p') or 0)
                            qty = float(evt.get('z') or evt.get('q') or 0)
                            ts = int(evt.get('T') or item.get('E') or _now_ms())
                            notional = price * qty
                            if not symbol or not side:
                                continue
                            
                            # CRITICAL: Filter to only process top 10 symbols from config
                            if symbol not in SYMBOLS:
                                continue  # Skip symbols not in our target list
                                
                        except Exception as e:
                            update_counter("errors")
                            debug_log(f"Event parsing failed: {e}")
                            continue
                        
                        rec = {"ts": ts, "symbol": symbol, "side": side, "qty": qty, "price": price, "notional": notional}
                        events.append(rec)
                        update_counter("processed_events")
                        
                        # First-N diagnostic sampling of processed events
                        sample_first_n_message(rec, "processed_liquidation")
                        
                        # Log each liquidation event as it comes in (both print and log)
                        print(f"💥 [LIQUIDATION] {symbol} {side} {qty:.4f} @ ${price:.4f} = ${notional:.2f}")
                        logger.info(f"[LIQUIDATION] {symbol} {side} {qty:.4f} @ ${price:.4f} = ${notional:.2f}")

                    # Log batch summary if events were processed
                    if norm_events and len(norm_events) > 0:
                        processed_count = len([e for e in norm_events if isinstance(e, dict)])
                        print(f"📊 [PROCESSED] Processed {processed_count} liquidation events from websocket")
                        logger.info(f"[PROCESSED] Processed {processed_count} liquidation events from websocket")
                        verbose_log(f"Batch processing: {processed_count} events, current queue size: {len(events)}")

                    # Trim
                    if events:
                        latest_ts = events[-1]['ts']
                        cutoff_global = latest_ts - (max(AGG_WINDOWS.keys()) + 5) * 1000
                        trimmed_count = 0
                        while events and events[0]['ts'] < cutoff_global:
                            events.popleft()
                            trimmed_count += 1
                        if trimmed_count > 0:
                            verbose_log(f"Trimmed {trimmed_count} old events from queue")

                    # Persist last batch (only last rec globally and per-symbol queue)
                    if r and events:
                        try:
                            last_evt = events[-1]
                            r.lpush(RAW_KEY, json.dumps(last_evt))
                            r.ltrim(RAW_KEY, 0, MAX_RAW - 1)
                            update_counter("redis_writes")
                            logger.info(f"[STORED] Stored liquidation event in Redis: {last_evt['symbol']} {last_evt['side']}")
                            verbose_log(f"Redis write: {RAW_KEY} <- {json.dumps(last_evt)}")
                            
                            # Per-symbol rings (smaller) - only for top 10 symbols
                            sym = last_evt.get('symbol')
                            if sym and sym in SYMBOLS:
                                pk = PER_SYMBOL_RAW_PREFIX + sym
                                r.lpush(pk, json.dumps(last_evt))
                                r.ltrim(pk, 0, 499)
                                update_counter("redis_writes")
                                verbose_log(f"Redis write: {pk} <- symbol-specific event")
                        except Exception as e:
                            update_counter("errors")
                            debug_log(f"Redis persistence failed: {e}")
                            pass

                    # Aggregations
                    now_ms = _now_ms()
                    if r and events:
                        for w, redis_key in AGG_WINDOWS.items():
                            cutoff = now_ms - w * 1000
                            agg = {"window_ms": w * 1000, "updated": now_ms, "count_total": 0, "count_buy": 0, "count_sell": 0,
                                   "notional_buy": 0.0, "notional_sell": 0.0, "net_imbalance": 0.0, "pressure": 0.0, "symbols": {}}
                            sym_stats = defaultdict(lambda: {"buy": 0, "sell": 0, "notional_buy": 0.0, "notional_sell": 0.0, "last_ts": 0, "pressure": 0.0})
                            for e in events:
                                if e['ts'] < cutoff:
                                    continue
                                agg['count_total'] += 1
                                sstat = sym_stats[e['symbol']]
                                if e['side'] == 'BUY':
                                    agg['count_buy'] += 1
                                    agg['notional_buy'] += e['notional']
                                    sstat['buy'] += 1
                                    sstat['notional_buy'] += e['notional']
                                else:
                                    agg['count_sell'] += 1
                                    agg['notional_sell'] += e['notional']
                                    sstat['sell'] += 1
                                    sstat['notional_sell'] += e['notional']
                                sstat['last_ts'] = e['ts']
                            total_notional = agg['notional_buy'] + agg['notional_sell']
                            if total_notional > 0:
                                agg['net_imbalance'] = (agg['notional_sell'] - agg['notional_buy']) / total_notional
                                agg['pressure'] = agg['net_imbalance']
                            for sym, sstat in sym_stats.items():
                                tn = sstat['notional_buy'] + sstat['notional_sell']
                                if tn > 0:
                                    sstat['pressure'] = (sstat['notional_sell'] - sstat['notional_buy']) / tn
                            agg['symbols'] = sym_stats
                            try:
                                r.set(redis_key, json.dumps(agg))
                                update_counter("redis_writes")
                                # Log aggregation summary for this window
                                logger.info(f"[AGGREGATE] {w//60}min AGG: {agg['count_total']} liq ({agg['count_buy']} buy, {agg['count_sell']} sell), "
                                          f"${agg['notional_buy']:.0f} vs ${agg['notional_sell']:.0f}, pressure={agg['pressure']:.3f}")
                                verbose_log(f"Redis write: {redis_key} <- aggregation with {len(sym_stats)} symbols")
                                
                                # Optional: publish additive V2 rollups under v2: prefix
                                try:
                                    if EXP_MODEL_V2 and ENABLE_LL_1M5M_FEATURES:
                                        # Build compact v2 payloads for 1m and 5m windows only
                                        if w in (DATA_WINDOWS.get("liq_win_1m", 60), DATA_WINDOWS.get("liq_win_5m", 300)):
                                            v2_payload = {
                                                'ts': now_ms,
                                                'window_s': w,
                                                'n': agg['count_total'],
                                                'nb': agg['count_buy'],
                                                'ns': agg['count_sell'],
                                                'nb_not': round(agg['notional_buy'], 6),
                                                'ns_not': round(agg['notional_sell'], 6),
                                                'imb': round(agg['net_imbalance'], 6),
                                                'p': round(agg['pressure'], 6),
                                            }
                                            r.set(f"{REDIS_PREFIX_V2}liq:agg:{w}s", json.dumps(v2_payload))
                                except Exception:
                                    pass
                                # Also publish per-symbol projection for convenience: binance:force:stats:1m:BTCUSDT
                                # Filter to only store stats for top 10 symbols from config
                                for sym_s, sdata in sym_stats.items():
                                    if sym_s not in SYMBOLS:
                                        continue  # Skip symbols not in our target list
                                    try:
                                        r.set(f"{redis_key}:{sym_s}", json.dumps(sdata))
                                        # For 1m window build enriched per-symbol feature snapshot with normalization
                                        if w == 60:  # 1m window chosen as base for high-frequency normalization
                                            # MEMORY FIX: Only track stats for configured symbols
                                            if sym_s not in SYMBOLS:
                                                continue
                                                
                                            total_notional_1m = sdata['notional_buy'] + sdata['notional_sell']
                                            pressure_1m = sdata['pressure']
                                            rec_key = f"binance:force:feat:{sym_s}"
                                            # Get pre-initialized running stats (guaranteed to exist for SYMBOLS)
                                            rs = _sym_running.get(sym_s)
                                            if rs is None:
                                                # Defensive fallback - should never happen with pre-init
                                                logger.warning(f"Missing running stats for {sym_s} - skipping")
                                                continue
                                            # Update running stats
                                            _welford_update(rs, 'mean_pressure', 'M2_pressure', pressure_1m)
                                            _welford_update(rs, 'mean_notional', 'M2_notional', total_notional_1m)
                                            z_pressure = _welford_get_z(rs, 'mean_pressure', 'M2_pressure', pressure_1m)
                                            z_notional = _welford_get_z(rs, 'mean_notional', 'M2_notional', total_notional_1m)
                                            feat_payload = {
                                                'ts': now_ms,
                                                'symbol': sym_s,
                                                'pressure_1m': pressure_1m,
                                                'notional_1m': total_notional_1m,
                                                'z_pressure_1m': z_pressure,
                                                'z_notional_1m': z_notional,
                                                'count_1m': sdata['buy'] + sdata['sell'],
                                                'buy_notional_1m': sdata['notional_buy'],
                                                'sell_notional_1m': sdata['notional_sell'],
                                            }
                                            try:
                                                r.set(rec_key, json.dumps(feat_payload))
                                            except Exception:
                                                pass
                                        # Publish compact per-symbol v2 snapshot (1m only)
                                        try:
                                            if EXP_MODEL_V2 and ENABLE_LL_1M5M_FEATURES and w == DATA_WINDOWS.get("liq_win_1m", 60):
                                                r.set(
                                                    f"{REDIS_PREFIX_V2}liq:feat:1m:{sym_s}",
                                                    json.dumps({
                                                        'ts': now_ms,
                                                        'p': round(pressure_1m, 6),
                                                        'n': int(sdata['buy'] + sdata['sell']),
                                                        'nb': int(sdata['buy']),
                                                        'ns': int(sdata['sell']),
                                                        'nb_not': round(sdata['notional_buy'], 6),
                                                        'ns_not': round(sdata['notional_sell'], 6),
                                                        'zp': round(z_pressure, 4),
                                                        'zn': round(z_notional, 4),
                                                    })
                                                )
                                        except Exception:
                                            pass
                                    except Exception:
                                        pass
                            except Exception:
                                pass

                    # Lightweight spoof-detect heuristic (additive; v2-only)
                    try:
                        if r and EXP_MODEL_V2 and ENABLE_SPOOF_DETECT:
                            # Evaluate last ~N events over short horizon for abrupt notional spikes and quick reversals
                            N = 50
                            # Use deque indexing instead of converting full deque to list (avoid O(n) copy)
                            evts_count = len(events)
                            if evts_count >= 10:
                                # Sample from end without copying whole deque
                                start_idx = max(0, evts_count - N)
                                S = [events[i] for i in range(start_idx, evts_count)]
                                tot = sum(e['notional'] for e in S)
                                if tot > 0:
                                    sell_not = sum(e['notional'] for e in S if e['side'] == 'SELL')
                                    buy_not = tot - sell_not
                                    imb = (sell_not - buy_not) / tot
                                    # Quick reversal if last K differ in side majority within the sample
                                    K = min(10, len(S))
                                    last_side = 1 if sum(1 for e in S[-K:] if e['side'] == 'SELL') > K/2 else -1
                                    early_side = 1 if sum(1 for e in S[:K] if e['side'] == 'SELL') > K/2 else -1
                                    reversal = (last_side * early_side) < 0
                                    # Heuristic: potential spoof when strong one-sided notional followed by reversal in short window
                                    spoof_score = max(0.0, abs(imb) - 0.6) * (1.5 if reversal else 1.0)
                                    payload = {
                                        'ts': now_ms,
                                        'sample': len(S),
                                        'imb': round(imb, 4),
                                        'rev': bool(reversal),
                                        'score': round(spoof_score, 4),
                                    }
                                    r.set(f"{REDIS_PREFIX_V2}spoof:score", json.dumps(payload))
                    except Exception:
                        pass

                    # Always update heartbeat even if no events parsed in this iteration
                    await _hb()
                    # Refresh lock TTL
                    try:
                        if r and os.getenv("LIQ_SINGLETON", "1") == "1":
                            r.expire('lock:live_binance_liq', 180)
                    except Exception:
                        pass
                    # Cooperative yield at end of websocket loop iteration
                    await asyncio.sleep(0.01)

        except Exception as e:
            logger.error("Fatal in consume_force_orders:\n" + traceback.format_exc())
            update_counter("errors")
            debug_log(f"Fatal error in websocket consumer: {e}")
            if r:
                try:
                    r.set(ERROR_KEY, traceback.format_exc())
                except Exception:
                    pass
        finally:
            try:
                if session:
                    await session.close()
                    debug_log("Websocket session closed")
            except Exception:
                pass
        # If we reached here, try next URL or outer retry
    # End for STREAM_URLS
    
    # Session diagnostics summary
    debug_log(f"Websocket session ended. Final counters: {message_counters}")
    if DEBUG_MODE and r:
        try:
            r.set("debug:binance_liquidations:last_session", json.dumps({
                "ended_at": _now_ms(),
                "final_counters": message_counters,
                "first_n_samples": first_n_counter
            }))
        except Exception:
            pass

async def main_async():
    backoff = 5
    while not _shutdown:
        try:
            await consume_force_orders()
        finally:
            # Best-effort lock release
            try:
                r = get_redis()
                if r and os.getenv("LIQ_SINGLETON", "1") == "1":
                    r.delete('lock:live_binance_liq')
            except Exception:
                pass
        await asyncio.sleep(backoff)
        # Cap reconnect backoff at 180 seconds (3 minutes)
        backoff = min(backoff * 2, 180)
        # Cooperative yield in supervisor loop
        await asyncio.sleep(0.01)

def main():
    debug_log(f"Binance liquidations main() starting. DEBUG_MODE={DEBUG_MODE}, VERBOSE_MODE={VERBOSE_MODE}")
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        global _shutdown
        _shutdown = True
        logger.info("Shutdown requested by user")
        debug_log("Clean shutdown via KeyboardInterrupt")
    except Exception as e:
        logger.error("Fatal top-level liquidation ingestor error:\n" + traceback.format_exc())
        update_counter("errors")
        debug_log(f"Fatal top-level error: {e}")
    finally:
        debug_log(f"Final diagnostic counters: {message_counters}")

if __name__ == "__main__":
    # Always log startup
    print(f"[{datetime.now()}] Binance Liquidations Ingestor starting...")
    print(f"🎯 Target symbols: {SYMBOLS}")
    print(f"🔧 Debug mode: {DEBUG_MODE}, Verbose mode: {VERBOSE_MODE}")
    
    # Initialize Telegram notifier
    telegram_notifier = None
    if TELEGRAM_AVAILABLE:
        try:
            telegram_notifier = TelegramNotifier()
        except Exception:
            pass
    
    # Send startup notification
    if telegram_notifier:
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(telegram_notifier.send_message(
                f"⚡ <b>LIQUIDATIONS MONITOR STARTED</b>\n\n"
                f"Service: Binance Forced Orders\n"
                f"Symbols: {len(SYMBOLS)} pairs\n"
                f"Debug: {'ON' if DEBUG_MODE else 'OFF'}\n"
                f"Status: MONITORING LIQUIDATIONS",
                parse_mode="HTML",
                forward_to_private=True
            ))
            loop.close()
        except Exception as e:
            debug_log(f"Failed to send startup notification: {e}")
    
    # CLI argument check for verbose mode
    if "--verbose" in sys.argv:
        verbose_log("Verbose mode enabled via CLI argument")
    
    debug_log("Starting Binance liquidations ingestor")
    
    try:
        exit_if_already_running(name="live_binance_liq", ttl_if_stale_seconds=600)
        debug_log("Instance check passed - no other liquidations ingestor running")
    except Exception as e:
        debug_log(f"Instance check failed: {e}")
        pass
    # Start health heartbeat (best-effort)
    r = None
    try:
        r = get_redis()
        debug_log("Redis connection established for heartbeat")
    except Exception as e:
        debug_log(f"Redis connection failed: {e}")
        r = None
    try:
        start_heartbeat(r, "IngestLiquidations")
        debug_log("Heartbeat service started")
    except Exception as e:
        debug_log(f"Heartbeat service failed: {e}")
        pass
    try:
        main()
        try:
            report_exit(r, "IngestLiquidations", "ok", "completed")
            debug_log("Clean exit reported")
            # Send normal shutdown notification
            if telegram_notifier:
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(telegram_notifier.send_message(
                        "🛑 <b>LIQUIDATIONS MONITOR STOPPED</b>\n\n"
                        "Service: Binance Forced Orders\n"
                        "Status: STOPPED NORMALLY",
                        parse_mode="HTML",
                        forward_to_private=True
                    ))
                    loop.close()
                except Exception as e:
                    debug_log(f"Failed to send shutdown notification: {e}")
        except Exception:
            pass
    except KeyboardInterrupt:
        debug_log("Liquidations ingestor stopped by user")
        if telegram_notifier:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(telegram_notifier.send_message(
                    "🛑 <b>LIQUIDATIONS MONITOR STOPPED</b>\n\n"
                    "Service: Binance Forced Orders\n"
                    "Status: STOPPED BY USER",
                    parse_mode="HTML",
                    forward_to_private=True
                ))
                loop.close()
            except Exception as e:
                debug_log(f"Failed to send shutdown notification: {e}")
    except Exception as e:
        try:
            report_exit(r, "IngestLiquidations", "error", repr(e))
            debug_log(f"Error exit reported: {e}")
            # Send error notification
            if telegram_notifier:
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(telegram_notifier.send_message(
                        f"❌ <b>LIQUIDATIONS MONITOR ERROR</b>\n\n"
                        f"Service: Binance Forced Orders\n"
                        f"Status: CRASHED\n"
                        f"Error: {str(e)[:200]}...",
                        parse_mode="HTML",
                        forward_to_private=True
                    ))
                    loop.close()
                except Exception as alert_e:
                    debug_log(f"Failed to send error notification: {alert_e}")
        except Exception:
            pass
        raise
