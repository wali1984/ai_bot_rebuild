# Coinank Live Ingestor - No venv guards, uses system Python
print(f"[COINANK START] Python executable: {__import__('sys').executable}")

import os, time, json, traceback, sys, math, asyncio, socket, threading, hashlib, random
import requests
from datetime import datetime
from pathlib import Path
from pathlib import Path

# System Python - no venv guards needed

# --- Path & Imports -----------------------------------------------------------------
# Path injection for WMA AI Bot
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent  # This should be 'c:\AI BOT'
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
try:
    from config import get_live_config
    _config = get_live_config()
    COINANK_API_KEY = _config.COINANK_API_KEY
    
    # Dynamic symbol loading - supports hot-reload without restart
    try:
        from utils.symbol_manager import get_symbols_cached
        SYMBOLS = get_symbols_cached()
    except ImportError:
        SYMBOLS = _config.SYMBOLS
    
    TRAINING_SYMBOLS = getattr(_config, 'TRAINING_SYMBOLS', SYMBOLS)
    from utils.logger import get_logger
    from utils.redis_client import get_redis
    
    # Import centralized normalizer (Phase 4 integration)
    try:
        from utils.data_normalizer import normalize_data
        NORMALIZER_AVAILABLE = True
        _enable_norm = getattr(_config, 'ENABLE_NORMALIZATION', True)
        ENABLE_NORMALIZATION = _enable_norm if _enable_norm is not None else True
    except ImportError as norm_err:
        print(f"[WARNING] Data normalizer not available: {norm_err}")
        NORMALIZER_AVAILABLE = False
        ENABLE_NORMALIZATION = False
except ImportError as e:
    raise ImportError(f"Import failure after path injection: {e}")

# Fail-fast Redis health check - must be reachable before starting ingestor
try:
    sys.path.insert(0, str(SCRIPT_DIR.parent.parent))  # Add root for tools
    from tools.health import assert_redis_up
    assert_redis_up()
except ImportError:
    print("[WARNING] Redis health check not available, proceeding...")
except SystemExit:
    raise  # Re-raise the Redis failure message

logger = get_logger("live_coinank")

# --- Diagnostic & Debug Enhancement System -------------------------------------------
DEBUG_MODE = os.getenv("RLBOT_DEBUG", "0") == "1"
# Allow explicit verbosity override via env
VERBOSE_MODE = (os.getenv("COINANK_VERBOSE", "0") == "1") or ("--verbose" in sys.argv) or DEBUG_MODE

# Safe debug mode for system stability (halved batch sizes, extra sleeps, reduced disk writes)
DEBUG_SAFE_MODE = os.getenv("RLBOT_DEBUG_SAFE", "0") == "1"
COOPERATIVE_YIELD_MODE = os.getenv("RLBOT_COOPERATIVE_YIELD", "0") == "1"

if DEBUG_SAFE_MODE:
    logger.info("🛡️ RLBOT_DEBUG_SAFE mode enabled - reduced batch sizes and extra yields for system stability")

# First-N sampler for debug output
FIRST_N_SAMPLE = 10 if DEBUG_MODE else 0
first_n_counter = 0

# Message counters for diagnostics
message_counters = {
    "api_calls": 0,
    "successful_fetches": 0,
    "failed_fetches": 0,
    "redis_writes": 0,
    "file_writes": 0,
    "errors": 0,
    "heartbeats": 0,
    "endpoints_processed": 0,
    "skipped_rate_limit": 0
}

def debug_log(msg: str):
    """Debug logging only when DEBUG_MODE is enabled"""
    if DEBUG_MODE:
        print(f"[DEBUG] {msg}")
        logger.debug(msg)

def verbose_log(msg: str):
    """Verbose logging for detailed output"""
    if VERBOSE_MODE:
        print(f"[VERBOSE] {msg}")

def update_counter(key: str, increment: int = 1):
    """Update diagnostic counters"""
    if DEBUG_MODE:
        message_counters[key] = message_counters.get(key, 0) + increment

def _now_ms() -> int:
    try:
        return int(time.time() * 1000)
    except Exception:
        return int(time.time() * 1000)

# --- CLI/env configuration -----------------------------------------------------------
HARD_ENDTIME_MS: int | None = None
BACKFILL_ENABLED = False
BACKFILL_MAX_EMPTY = int(os.getenv("COINANK_BACKFILL_MAX_EMPTY", "3"))
# Max length for the backfill queue (kept small to avoid memory pressure)
BACKFILL_QUEUE_MAX = int(os.getenv("COINANK_BACKFILL_QUEUE_MAX", "500"))
# Track consecutive empty responses per series (in-memory guard)
_backfill_empty_counts: dict[str, int] = {}

def _parse_cli_env_overrides():
    """Parse CLI flags and envs to set hard endtime and backfill mode."""
    global HARD_ENDTIME_MS, BACKFILL_ENABLED
    # Env first
    env_et = os.getenv("COINANK_HARD_ENDTIME_MS")
    if env_et:
        try:
            HARD_ENDTIME_MS = int(env_et)
        except Exception:
            HARD_ENDTIME_MS = None
    # CLI: --endtime-ms=<int> or --endtime-ms <int>
    try:
        if "--endtime-ms" in sys.argv:
            idx = sys.argv.index("--endtime-ms")
            if idx + 1 < len(sys.argv):
                HARD_ENDTIME_MS = int(sys.argv[idx+1])
        else:
            for arg in sys.argv:
                if arg.startswith("--endtime-ms="):
                    HARD_ENDTIME_MS = int(arg.split("=",1)[1])
                    break
    except Exception:
        pass
    # Backfill flag/env
    BACKFILL_ENABLED = os.getenv("COINANK_BACKFILL", "0") == "1" or ("--backfill" in sys.argv)

def _start_dual_heartbeat(r):
    """Background thread: emit JSON heartbeats to both canonical and alias keys every ~15s.
    Keys:
      - heartbeat:IngestCoinAnk
      - heartbeat:CoinAnkIngest
    Payload: {"ts_ms": <int>, "service": "IngestCoinAnk"}
    TTL: 300s
    """
    try:
        if not r:
            return
    except Exception:
        return

    def _loop():
        while True:
            try:
                ts = _now_ms()
                payload = json.dumps({"ts_ms": ts, "service": "coinank_ingestor"}, separators=(",", ":"))
                # Write both canonical and new required heartbeat keys
                # TTL policy: 300s (5m) expire so the heartbeat auto-clears if the ingestor stalls.
                r.set("heartbeat:IngestCoinAnk", payload, ex=300)
                r.set("heartbeat:CoinAnkIngest", payload, ex=300)
                r.set("heartbeat:writer:coinank", payload, ex=300)  # Required by live5.md
            except Exception:
                # Best-effort; avoid crashing the process on transient Redis errors
                pass
            # Refresh roughly every 15 seconds
            time.sleep(15)

    try:
        threading.Thread(target=_loop, daemon=True).start()
    except Exception:
        pass

def write_diagnostic_heartbeat():
    """Write heartbeat with diagnostic counters"""
    try:
        r = get_redis()
        if r:
            ts = _now_ms()
            heartbeat_data = {
                "ts_ms": ts,
                "service": "coinank_ingestor",
                "counters": message_counters.copy() if DEBUG_MODE else None
            }
            payload = json.dumps(heartbeat_data, separators=(",", ":"))
            # Emit to both alias and required canonical keys
            # TTL policy: 300s (5m) on all heartbeat keys.
            r.set("heartbeat:CoinAnkIngest", payload, ex=300)
            r.set("heartbeat:IngestCoinAnk", payload, ex=300)
            r.set("heartbeat:writer:coinank", payload, ex=300)  # Required by live5.md
            update_counter("heartbeats")
            if DEBUG_MODE:
                debug_status = {
                    "last_heartbeat": heartbeat_data["ts_ms"],
                    "counters": message_counters.copy(),
                    "debug_mode": DEBUG_MODE,
                    "verbose_mode": VERBOSE_MODE
                }
                r.set("debug:coinank_ingest:status", json.dumps(debug_status), ex=3600)
    except Exception as e:
        debug_log(f"Heartbeat write failed: {e}")

def first_n_sample(msg_type: str, msg_data):
    """Sample first N messages for debugging"""
    global first_n_counter
    if FIRST_N_SAMPLE > 0 and first_n_counter < FIRST_N_SAMPLE:
        first_n_counter += 1
        debug_log(f"SAMPLE #{first_n_counter} {msg_type}: {json.dumps(msg_data, default=str)}")

def _flatten_numeric_fields(data: dict, flattened: dict, prefix: str = ""):
    """Recursively flatten numeric fields from nested dict"""
    if not isinstance(data, dict):
        return
    
    for key, value in data.items():
        new_key = f"{prefix}{key}"
        
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            flattened[new_key] = float(value)
        elif isinstance(value, dict):
            # Recurse into nested dicts with depth limit
            if len(prefix.split('_')) < 3:  # Limit nesting depth
                _flatten_numeric_fields(value, flattened, f"{new_key}_")
        elif isinstance(value, list) and value:
            # For lists, try to extract numeric from first item or aggregate
            if isinstance(value[0], (int, float)) and not isinstance(value[0], bool):
                # List of numbers - take mean/first
                try:
                    flattened[f"{new_key}_mean"] = float(sum(value) / len(value))
                    flattened[f"{new_key}_first"] = float(value[0])
                except:
                    pass
            elif isinstance(value[0], (list, tuple)) and value[0]:
                # List of lists (e.g., timeseries arrays like [[ts, a, b], ...])
                # Extract per-column aggregates for numeric columns.
                try:
                    # Determine max column width across a small sample to avoid heavy scans
                    sample_rows = value[:200]  # cap work (responses are typically <= 100)
                    max_cols = max((len(row) for row in sample_rows if isinstance(row, (list, tuple))), default=0)
                    for col in range(max_cols):
                        col_vals = []
                        for row in sample_rows:
                            if not isinstance(row, (list, tuple)) or len(row) <= col:
                                continue
                            v = row[col]
                            if isinstance(v, (int, float)) and not isinstance(v, bool):
                                col_vals.append(float(v))
                        if not col_vals:
                            continue
                        flattened[f"{new_key}_col{col}_mean"] = float(sum(col_vals) / len(col_vals))
                        flattened[f"{new_key}_col{col}_first"] = float(col_vals[0])
                        flattened[f"{new_key}_col{col}_last"] = float(col_vals[-1])
                except Exception:
                    pass
            elif isinstance(value[0], dict):
                # List of objects - flatten first object
                _flatten_numeric_fields(value[0], flattened, f"{new_key}_0_")

async def _dns_preflight(host: str):
    """DNS preflight check to verify hostname resolution before API calls"""
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        ips = sorted({ai[4][0] for ai in infos})
        logger.info(f"[preflight] DNS OK for {host}: {ips}")
        debug_log(f"DNS preflight successful for {host}: {len(ips)} IPs resolved")
        return True
    except Exception as e:
        logger.error(f"[preflight] DNS failed for {host}: {e}")
        debug_log(f"DNS preflight failed for {host}: {e}")
        return False

def _test_coinank_connectivity():
    """Test CoinAnk API connectivity with DNS preflight"""
    debug_log("Testing CoinAnk API connectivity...")
    
    # Test CoinAnk API endpoints
    coinank_hosts = [
        "api.coinank.com",
        "api2.coinank.com"
    ]
    
    for host in coinank_hosts:
        try:
            import socket
            socket.setdefaulttimeout(5)
            result = socket.gethostbyname(host)
            debug_log(f"✅ DNS resolved {host} -> {result}")
        except Exception as e:
            logger.warning(f"❌ DNS resolution failed for {host}: {e}")
            verbose_log(f"DNS resolution failed for {host}: {e}")
            # Don't fail completely on DNS issues, CoinAnk might have multiple endpoints
            continue
    
    return True

# Startup diagnostics
if DEBUG_MODE:
    debug_log("CoinAnk ingestor starting in DEBUG mode")
else:
    verbose_log("CoinAnk ingestor starting in VERBOSE mode")

# --- Validator output config ---
VALIDATE_TO_REDIS = os.getenv("COINANK_VALIDATION_TO_REDIS", "1") == "1"
VAL_STREAM_KEY    = "coinank:validator:warn"      # stream of warnings
VAL_LATEST_HASH   = "coinank:validator:latest"    # last warning (for dashboards)

def _warn(ep: str, msg: str, params: dict | None = None):
    # always print (harmless)
    try:
        print(f"[Validator] ⚠️ {ep}: {msg} :: {params or {}}")
    except Exception:
        pass
    # optionally mirror to Redis (non-fatal)
    if VALIDATE_TO_REDIS:
        try:
            r = get_redis()
            if r:
                now = int(time.time() * 1000)
                payload = {"t": now, "ep": ep, "msg": msg, "params": json.dumps(params or {}, ensure_ascii=False)}
                # append to stream (bounded), update latest hash
                r.xadd(VAL_STREAM_KEY, payload, maxlen=5000)
                r.hset(VAL_LATEST_HASH, mapping=payload)
        except Exception:
            pass

# --- Allowed sets (tight on purpose) ---
_ALLOWED_SYMBOLS = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "UNIUSDT", "LTCUSDT",
    "ASTERUSDT", "WIFUSDT", "1000SHIBUSDT",
    # New listings / expanded universe (keep validator warnings quiet for live symbols)
    "AVNTUSDT", "PIPPINUSDT",
    "1000PEPEUSDT", "1000BONKUSDT", "FARTCOINUSDT", "1000FLOKIUSDT",
    "RIVERUSDT", "RAVEUSDT", "HIGHUSDT", "PENGUUSDT",
    "BARDUSDT", "BANKUSDT", "AUCTIONUSDT", "ALICEUSDT",
}
_ALLOWED_EXCHANGES = {"Binance"}  # extend if needed

# interval -> ms
_INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "4h": 14_400_000, "8h": 28_800_000, "1d": 86_400_000,
}

def _tf_seconds(iv: str | None) -> int:
    if not iv:
        return 300  # default 5 minutes
    m = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
        "12h": 43200, "1d": 86400, "1w": 604800, "1M": 2592000,
        # Uppercase variants used by some endpoints
        "1H": 3600, "4H": 14400, "12H": 43200, "24H": 86400
    }
    return m.get(str(iv), 300)

def _validate_params(ep: str, params: dict):
    """Harmless checks: endTime alignment, allowed symbol/exchange. Logs only."""
    try:
        sym = params.get("symbol")
        if sym and sym not in _ALLOWED_SYMBOLS:
            _warn(ep, f"symbol not in allowed set: {sym}", params)

        ex = params.get("exchange")
        if ex and ex not in _ALLOWED_EXCHANGES:
            _warn(ep, f"exchange not in allowed set: {ex}", params)

        exs = params.get("exchanges")
        if exs:
            parts = [p.strip() for p in str(exs).split(",") if p.strip()]
            bad = [p for p in parts if p not in _ALLOWED_EXCHANGES]
            if bad:
                _warn(ep, f"exchanges contain non-allowed entries: {bad}", params)

        iv = params.get("interval")
        et = params.get("endTime")
        if iv and et is not None:
            try:
                et = int(et)
                span = _INTERVAL_MS.get(iv)
                if not span:
                    _warn(ep, f"unknown interval '{iv}' for alignment check", params)
                else:
                    if et % span != 0:
                        _warn(ep, f"endTime {et} not aligned to {iv} ({span} ms)", params)
                    # Optional: future guard (+1s tolerance)
                    now_ms = int(time.time() * 1000) + 1000
                    if et > now_ms:
                        _warn(ep, f"endTime {et} appears in the future", params)
            except Exception:
                _warn(ep, "endTime not an int (ms) or parse failed", params)
    except Exception:
        # never fail the caller
        pass

# --- Working Endpoints (all enabled) ---------------------------------------------------
# SINGLE SOURCE OF TRUTH: This is the authoritative registry for all CoinAnk endpoints.
# Each entry: path, params, and generation mode understood by build_param_sets.
# Do not duplicate these definitions in config.py or elsewhere to avoid drift.
WORKING_COINANK_ENDPOINTS = {
    # Discovery & base
    "baseCoin_list": {"path": "/api/baseCoin/list", "params": ["productType"], "mode": "product_type_only"},
    "baseCoin_symbols": {"path": "/api/baseCoin/symbols", "params": ["exchange", "productType"], "mode": "exchange"},

    # Liquidations & heatmap
    "liquidation_orders": {"path": "/api/liquidation/orders", "params": ["baseCoin", "exchange", "side", "amount", "endTime"], "mode": "liquidation_orders"},
    "liquidation_allExchange_intervals": {"path": "/api/liquidation/allExchange/intervals", "params": ["baseCoin"], "mode": "base"},
    "liquidation_aggregated_history": {"path": "/api/liquidation/aggregated-history", "params": ["baseCoin", "interval", "endTime", "size"], "mode": "fund_history_base_interval_end"},
    "liquidation_history": {"path": "/api/liquidation/history", "params": ["exchange", "symbol", "interval", "endTime", "size"], "mode": "symbol_exchange_interval_end"},
    "liqMap_getLiqHeatMapSymbol": {"path": "/api/liqMap/getLiqHeatMapSymbol", "params": [], "mode": "static"},

    # Instruments
    "instruments_getLastPrice": {"path": "/api/instruments/getLastPrice", "params": ["symbol", "exchange", "productType"], "mode": "symbol_exchange"},
    "instruments_getCoinMarketCap": {"path": "/api/instruments/getCoinMarketCap", "params": ["baseCoin"], "mode": "base"},
    "instruments_oiVsMc": {"path": "/api/instruments/oiVsMc", "params": ["baseCoin", "interval", "size", "endTime"], "mode": "base_interval_end"},

    # Open Interest variants
    "openInterest_all": {"path": "/api/openInterest/all", "params": ["baseCoin"], "mode": "base"},
    "openInterest_v2_chart": {"path": "/api/openInterest/v2/chart", "params": ["baseCoin", "interval", "size"], "mode": "base_interval"},
    "openInterest_aggKline": {"path": "/api/openInterest/aggKline", "params": ["baseCoin", "interval", "endTime", "size"], "mode": "agg_market_base_interval_end"},
    "openInterest_symbol_Chart": {"path": "/api/openInterest/symbol/Chart", "params": ["symbol", "exchange", "interval", "endTime", "size"], "mode": "symbol_exchange_interval_end"},
    "openInterest_kline": {"path": "/api/openInterest/kline", "params": ["exchange", "symbol", "interval", "endTime", "size"], "mode": "symbol_exchange_interval_end"},

    # Market Order Flow (all enabled; upstream errors handled gracefully)
    "marketOrder_getBuySellCount": {"path": "/api/marketOrder/getBuySellCount", "params": ["exchange", "symbol", "interval", "endTime", "size", "productType"], "mode": "symbol_exchange_interval_end"},
    "marketOrder_getBuySellValue": {"path": "/api/marketOrder/getBuySellValue", "params": ["exchange", "symbol", "interval", "endTime", "size", "productType"], "mode": "symbol_exchange_interval_end"},
    "marketOrder_getBuySellVolume": {"path": "/api/marketOrder/getBuySellVolume", "params": ["exchange", "symbol", "interval", "endTime", "size", "productType"], "mode": "symbol_exchange_interval_end"},
    "marketOrder_getAggCvd": {"path": "/api/marketOrder/getAggCvd", "params": ["exchange", "symbol", "interval", "endTime", "size", "productType"], "mode": "symbol_exchange_interval_end"},

    # -------- Market-Order Aggregates (Plan3) --------
    "marketOrder_getAggBuySellCount": {
        "path": "/api/marketOrder/getAggBuySellCount",
        "params": ["exchanges", "baseCoin", "interval", "endTime", "size", "productType"],
        "mode": "exchanges_base_interval_end"
    },
    "marketOrder_getAggBuySellValue": {
        "path": "/api/marketOrder/getAggBuySellValue",
        "params": ["exchanges", "baseCoin", "interval", "endTime", "size", "productType"],
        "mode": "exchanges_base_interval_end"
    },
    "marketOrder_getAggBuySellVolume": {
        "path": "/api/marketOrder/getAggBuySellVolume",
        "params": ["exchanges", "baseCoin", "interval", "endTime", "size", "productType"],
        "mode": "exchanges_base_interval_end"
    },

    # Funding
    "fundingRate_accumulated": {"path": "/api/fundingRate/accumulated", "params": ["type"], "mode": "funding_accumulated"},
    "fundingRate_indicator": {"path": "/api/fundingRate/indicator", "params": ["exchange", "symbol", "interval", "endTime", "size"], "mode": "symbol_exchange_interval_end_no_producttype"},
    "fundingRate_frHeatmap": {"path": "/api/fundingRate/frHeatmap", "params": ["type", "interval"], "mode": "funding_heatmap"},

    # Order Book - DISABLED: Only Binance and KuCoin should handle OHLCV data
    # "orderBook_v2_bySymbol": {"path": "/api/orderBook/v2/bySymbol", "params": ["symbol", "exchange", "rate", "productType", "interval", "endTime", "size"], "mode": "orderbook_symbol"},

    # Indicators
    "indicator_getAltcoinSeason": {"path": "/api/indicator/getAltcoinSeason", "params": ["symbol"], "mode": "base"},

    # Hyper
    "hyper_topPosition": {"path": "/api/hyper/topPosition", "params": ["sortBy", "sortType", "page", "size"], "mode": "hyper_position"},
    "hyper_topAction": {"path": "/api/hyper/topAction", "params": [], "mode": "static"},

    # Fundflow (new endpoints following playbook)
    "fund_fundReal": {"path": "/api/fund/fundReal", "params": ["productType", "sortBy", "sortType", "size", "page"], "mode": "fundflow_realtime"},
    "fund_getFundHisList": {"path": "/api/fund/getFundHisList", "params": ["baseCoin", "interval", "endTime", "size", "productType"], "mode": "base_interval_end_with_producttype"},

    # -------- FundingRate (Plan1) --------
    "fundingRate_history": {"path": "/api/fundingRate/hist", "params": ["baseCoin", "exchangeType", "endTime", "size"], "mode": "funding_hist_base_end"},
    "fundingRate_current": {"path": "/api/fundingRate/current", "params": ["type"], "mode": "funding_current"},
    "fundingRate_kline": {"path": "/api/fundingRate/kline", "params": ["exchange", "symbol", "interval", "endTime", "size"], "mode": "symbol_exchange_interval_end_no_producttype"},

    # -------- Long/Short (Plan1) --------
    "ls_exchange_realtimeAll": {"path": "/api/longshort/realtimeAll", "params": ["baseCoin", "interval"], "mode": "longshort_realtime_all"},
    "ls_global_account_ratio": {"path": "/api/longshort/person", "params": ["exchange", "symbol", "interval", "endTime", "size"], "mode": "symbol_exchange_interval_end_no_producttype"},
    "ls_toptrader_accounts": {"path": "/api/longshort/account", "params": ["exchange", "symbol", "interval", "endTime", "size"], "mode": "symbol_exchange_interval_end_no_producttype"},
    "ls_kline": {"path": "/api/longshort/kline", "params": ["exchange", "symbol", "endTime", "interval", "size", "type"], "mode": "longshort_kline_type"},

    # Advanced new categories
    "netPositions_getNetPositions": {"path": "/api/netPositions/getNetPositions", "params": ["exchange", "symbol", "interval", "endTime", "size"], "mode": "net_positions_symbol_exchange_interval_end"},
    "orderFlow_lists": {"path": "/api/orderFlow/lists", "params": ["exchange", "symbol", "interval", "endTime", "size", "productType", "tickCount"], "mode": "order_flow_lists"},
    "rsiMap_list": {"path": "/api/rsiMap/list", "params": ["interval", "exchange"], "mode": "rsi_map"},
    "bigOrder_queryOrderList": {"path": "/api/bigOrder/queryOrderList", "params": ["exchange", "symbol", "exchangeType", "amount", "side", "isHistory", "startTime", "size"], "mode": "big_order_query"},
    "trades_largeTrades": {"path": "/api/trades/largeTrades", "params": ["exchange", "symbol", "productType", "amount", "size", "endTime"], "mode": "large_trades"},
}

# Pre-seed metrics & registry so UI can show endpoints before first response
_PRESEEDED = False

PLAN3_INTERVAL_LIMITS = {  # Maximum days back allowed per interval from current time
    '1m': 7, '3m': 15, '5m': 30, '15m': 60, '30m': 120,
    '1h': 180, '2h': 180, '4h': 360, '6h': 360, '8h': 360,
    '12h': 360, '1d': 360, '1w': 360, '1M': 360
}

# Maximum data points per interval to avoid error code 7
MAX_SIZE_LIMITS = {
    '1m': 10080,   # 7 days * 24 hours * 60 minutes
    '3m': 7200,    # 15 days * 24 hours * 20 intervals per hour  
    '5m': 8640,    # 30 days * 24 hours * 12 intervals per hour
    '15m': 5760,   # 60 days * 24 hours * 4 intervals per hour
    '30m': 5760,   # 120 days * 24 hours * 2 intervals per hour
    '1h': 4320,    # 180 days * 24 hours
    '2h': 2160,    # 180 days * 12 intervals per day
    '4h': 2160,    # 360 days * 6 intervals per day
    '6h': 1440,    # 360 days * 4 intervals per day
    '8h': 1080,    # 360 days * 3 intervals per day
    '12h': 720,    # 360 days * 2 intervals per day
    '1d': 360,     # 360 days
    '1w': 51,      # 360 days / 7 days per week
    '1M': 12       # 360 days / 30 days per month
}

EXCHANGES = ["Binance"]  # Keep lean for rate limits; expand if needed
PRODUCT_TYPE = "SWAP"
DEFAULT_SIZES = {"small": 50, "medium": 200}
INTERVALS_PRIORITY = ["1m", "5m", "15m", "1h", "4h", "30m", "8h", "1d"]  # Core timeframes first: 1m,5m,15m,1h,4h

# --- Use SYMBOLS from config.py as source of truth ------------
COINANK_SYMBOLS = SYMBOLS[:]  # Use imported SYMBOLS from config.py
BASE_COINS = sorted({s.replace("USDT", "") for s in COINANK_SYMBOLS})

# Expand CoinAnk per-symbol endpoints beyond BTC/ETH.
# Source of truth is config.py (env override supported there).
try:
    import config as _cfg_mod
    EXPAND_ALL = bool(getattr(_cfg_mod, "COINANK_EXPAND_ALL", True))
except Exception:
    EXPAND_ALL = os.getenv("COINANK_EXPAND_ALL", "true").lower() in ("1", "true", "yes", "on")

# --- Token bucket to respect RPM hard cap (env configurable)
RATE_LIMIT_RPM = int(os.getenv("COINANK_GLOBAL_RPM", "280"))  # target under 300 to leave headroom
TOKENS_PER_SEC = RATE_LIMIT_RPM / 60.0
_bucket = {"tokens": RATE_LIMIT_RPM, "last": time.time()}
_last_request_ts = 0.0  # enforce smoother pacing between requests

def _rate_gate():
    global _last_request_ts
    now = time.time()
    # refill tokens
    elapsed = now - _bucket["last"]
    _bucket["last"] = now
    _bucket["tokens"] = min(RATE_LIMIT_RPM, _bucket["tokens"] + elapsed * TOKENS_PER_SEC)
    # wait until we have 1 token
    min_sleep = float(os.getenv("COINANK_MIN_SLEEP_SEC", "0.05"))
    while True:
        # Token availability
        if _bucket["tokens"] >= 1.0:
            # Smooth out bursts (avoid hitting provider short-window bans).
            # NOTE: REQUEST_SPACING is already derived from COINANK_GLOBAL_RPM.
            now = time.time()
            if _last_request_ts and (now - _last_request_ts) < REQUEST_SPACING:
                time.sleep(max(0.0, REQUEST_SPACING - (now - _last_request_ts)))
                continue
            _bucket["tokens"] -= 1.0
            _last_request_ts = time.time()
            return

        # Not enough tokens yet: sleep briefly and refill.
        time.sleep(min_sleep)
        time.sleep(0.01)  # cooperative yield
        now = time.time()
        elapsed = now - _bucket["last"]
        _bucket["last"] = now
        _bucket["tokens"] = min(RATE_LIMIT_RPM, _bucket["tokens"] + elapsed * TOKENS_PER_SEC)

REQUEST_SPACING = max(0.25, 60.0 / RATE_LIMIT_RPM)

SESSION = requests.Session()
SESSION.headers.update({"accept": "application/json", "apikey": COINANK_API_KEY or ""})

# Add connection pooling and retry logic for improved reliability
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

retry = Retry(
    total=4, connect=2, read=2, backoff_factor=0.4,
    status_forcelist=(429, 500, 502, 503, 504),
    respect_retry_after_header=True,
)
adapter = HTTPAdapter(max_retries=retry, pool_connections=100, pool_maxsize=100)
SESSION.mount("https://", adapter)
SESSION.mount("http://", adapter)

BASE_URL = "https://open-api.coinank.com"

# Printing control: set COINANK_PRINT=1 to force printing each successful API result
PRINT_OUTPUT = os.getenv("COINANK_PRINT", "0") == "1" or sys.stdout.isatty()
MAX_FULL_PRINTS = 2  # per-endpoint full prints before switching to delta

# Base + per-endpoint minimum intervals (seconds). Use your live Age table to tune.
_endpoint_min_interval = {
    # Hot signals: keep tight
    "liquidation_orders": 5,
    "liquidation_aggregated_history": 10,
    "openInterest_symbol_Chart": 15,
    "openInterest_kline": 15,
    "marketOrder_getBuySellCount": 15,
    "marketOrder_getBuySellValue": 15,
    "marketOrder_getBuySellVolume": 15,
    "marketOrder_getAggBuySellCount": 30,
    "marketOrder_getAggBuySellValue": 30,
    "marketOrder_getAggBuySellVolume": 30,
    "fundingRate_indicator": 30,
    "orderFlow_lists": 15,

    # Funding
    "fundingRate_history": 60,
    "fundingRate_current": 30,
    "fundingRate_kline": 60,

    # Long/Short
    "ls_exchange_realtimeAll": 30,
    "ls_global_account_ratio": 60,
    "ls_toptrader_accounts": 60,
    "ls_kline": 60,

    # Fundflow endpoints (following playbook)
    "fund_fundReal": 60,  # realtime, but not too aggressive
    "fund_getFundHisList": 90,  # historical, slower pace

    # Medium cadence - reduced from 60-120s to 30-45s for more frequent updates
    "openInterest_v2_chart": 30,
    "openInterest_aggKline": 30,
    # "orderBook_v2_bySymbol": 45,  # DISABLED: Only Binance/KuCoin handle OHLCV
    "netPositions_getNetPositions": 45,
    "openInterest_all": 60,
    "instruments_oiVsMc": 90,

    # Slower cadence - reduced from 180s to 60-90s for better coverage
    "instruments_getLastPrice": 60,
    "instruments_getCoinMarketCap": 90,
    "indicator_getAltcoinSeason": 120,
    "hyper_topPosition": 60,
    "hyper_topAction": 90,

    # Moderate pace for specialized endpoints
    "rsiMap_list": 90,
    "liquidation_allExchange_intervals": 30,
    "liquidation_history": 45,
    "liqMap_getLiqHeatMapSymbol": 45,
}
_BASE_MIN_INTERVAL = 5.0

# Metrics & adaptive backoff state
_metrics = {}
_last_payload_hash = {}
_repeat_counts = {}
_endpoint_param_cursor = {}  # endpoint -> next param-set index (prevents long blocking loops)
_MAX_MIN_INTERVAL = 120.0
try:
    _MAX_MIN_INTERVAL = float(os.getenv("COINANK_MAX_MIN_INTERVAL_SEC", str(_MAX_MIN_INTERVAL)))
except Exception:
    pass
_REPEAT_INCREASE_THRESHOLD = 5
_HASH_TRUNCATE = 16

# --- Category scheduling & base-coin rotation ---------------------------------------
# Map endpoints to categories for paced execution (10s pause between categories)
CATEGORY_OF = {
    # Instruments
    "instruments_getLastPrice": "instruments",
    "instruments_getCoinMarketCap": "instruments",
    "instruments_oiVsMc": "instruments",

    # Open Interest
    "openInterest_all": "open_interest",
    "openInterest_v2_chart": "open_interest",
    "openInterest_aggKline": "open_interest",
    "openInterest_symbol_Chart": "open_interest",
    "openInterest_kline": "open_interest",

    # Market Order Flow
    "marketOrder_getBuySellCount": "market_order_flow",
    "marketOrder_getBuySellValue": "market_order_flow",
    "marketOrder_getBuySellVolume": "market_order_flow",
    "marketOrder_getAggCvd": "market_order_flow",
    "marketOrder_getAggBuySellCount": "market_order_flow",
    "marketOrder_getAggBuySellValue": "market_order_flow",
    "marketOrder_getAggBuySellVolume": "market_order_flow",
    "marketOrder_getAggCvd": "market_order_flow",

    # Funding
    "fundingRate_accumulated": "funding",
    "fundingRate_indicator": "funding",
    "fundingRate_frHeatmap": "funding",

    # Order Book - DISABLED
    # "orderBook_v2_bySymbol": "order_book",

    # Indicators
    "indicator_getAltcoinSeason": "indicators",
    "rsiMap_list": "indicators",

    # Hyper
    "hyper_topPosition": "hyper",
    "hyper_topAction": "hyper",

    # Advanced
    "netPositions_getNetPositions": "advanced",
    "orderFlow_lists": "advanced",
    "bigOrder_queryOrderList": "advanced",
    "trades_largeTrades": "advanced",

    # Liquidations & heatmaps
    "liquidation_orders": "liquidations",
    "liquidation_allExchange_intervals": "liquidations",
    "liquidation_aggregated_history": "liquidations",
    "liquidation_history": "liquidations",
    "liqMap_getLiqHeatMapSymbol": "liquidations",

    # Funding
    "fundingRate_history": "funding",
    "fundingRate_current": "funding",
    "fundingRate_kline": "funding",

    # Long/Short
    "ls_exchange_realtimeAll": "long_short",
    "ls_global_account_ratio": "long_short",
    "ls_toptrader_accounts": "long_short",
    "ls_kline": "long_short",

    # Fundflow
    "fund_fundReal": "fundflow",
    "fund_getFundHisList": "fundflow",

    # Base discovery
    "baseCoin_list": "discovery",
    "baseCoin_symbols": "discovery",
}

# Category execution order (start from 'instruments')
CATEGORY_ORDER = [
    "instruments",
    "open_interest",
    "market_order_flow",
    "funding",
    "long_short",
    "fundflow",
    # "order_book",  # DISABLED: Only Binance/KuCoin handle OHLCV
    "indicators",
    "hyper",
    "advanced",
    "liquidations",
    "discovery",
    "misc",
]

# Limit base-coin endpoints to one base symbol per full pass; rotate each pass
SINGLE_BASE_PER_RUN = True
_base_coin_cursor = 0

def _selected_base_coins():
    if SINGLE_BASE_PER_RUN and BASE_COINS:
        try:
            return [BASE_COINS[_base_coin_cursor % len(BASE_COINS)]]
        except Exception:
            return [BASE_COINS[0]]
    return BASE_COINS

def _now_ms() -> int:
    return int(time.time() * 1000)

def _end_time() -> str:
    return str(_now_ms())

def _plan3_historical_endtime() -> str:
    """
    Calculate endTime for Plan 3 to get maximum historical data.
    Plan 3 limits: 7-day for 1min, 15-day for 3min, 30-day for 5min, 60-day for 15min,
    120-day for 30min, 180-day for 1h+. Since liquidation_orders doesn't specify intervals,
    we'll use 30 days back to capture meaningful recent liquidation history while staying
    within reasonable API limits.
    """
    import time
    now_ms = _now_ms()
    # 30 days back in milliseconds (30 * 24 * 60 * 60 * 1000)
    thirty_days_ms = 30 * 24 * 60 * 60 * 1000
    return str(now_ms - thirty_days_ms)

def _align_end_time(end_time_ms: int, interval: str) -> int:
    """Align endTime to the start of the current interval for consistency"""
    # Convert to seconds for calculation
    end_time_s = end_time_ms // 1000
    
    # Interval to seconds mapping
    interval_seconds = {
        '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800,
        '1h': 3600, '2h': 7200, '4h': 14400, '6h': 21600, '8h': 28800,
        '12h': 43200, '1d': 86400, '1w': 604800, '1M': 2592000  # Approximate for month
    }
    
    seconds_per_interval = interval_seconds.get(interval, 3600)
    
    # Align to interval boundary (floor to interval start)
    aligned_time_s = (end_time_s // seconds_per_interval) * seconds_per_interval
    
    return aligned_time_s * 1000  # Convert back to milliseconds

def _effective_end_time(interval: str | None, proposed_end_ms: int | None) -> str:
    """Apply hard endTime override and align to TF boundaries consistently."""
    try:
        end_ms = int(proposed_end_ms) if proposed_end_ms is not None else _now_ms()
    except Exception:
        end_ms = _now_ms()
    # Clamp to hard end-time if provided (avoid overshoot)
    if HARD_ENDTIME_MS is not None:
        end_ms = min(end_ms, HARD_ENDTIME_MS)
    # Align if interval known
    if interval:
        try:
            end_ms = _align_end_time(end_ms, interval)
        except Exception:
            pass
    return str(end_ms)

def _get_max_size(interval: str, requested_size: int = 100) -> int:
    """Get maximum allowed size for interval to avoid error code 7"""
    max_allowed = MAX_SIZE_LIMITS.get(interval, 100)
    return min(requested_size, max_allowed)

def _plan3_endtime_for_interval(interval: str) -> str:
    """
    Calculate endTime based on Plan 3 historical limits for different intervals.
    Updated with correct time alignment and safety margins to prevent time errors.
    """
    now_ms = _now_ms()
    
    # Get maximum days back for this interval
    max_days = PLAN3_INTERVAL_LIMITS.get(interval, 7)  # Default to 7 days for safety
    
    # Use a safe recent time (1 hour ago) to avoid edge cases with very recent data
    safe_end_time_ms = now_ms - (60 * 60 * 1000)  # 1 hour ago
    
    # Ensure we don't exceed historical limits
    max_lookback_ms = max_days * 24 * 60 * 60 * 1000
    earliest_allowed_ms = now_ms - max_lookback_ms
    
    # Choose the more recent time (but not too recent)
    final_end_time_ms = max(safe_end_time_ms, earliest_allowed_ms + (60 * 60 * 1000))
    
    # Align to interval boundary
    aligned_end_time_ms = _align_end_time(final_end_time_ms, interval)
    
    return str(aligned_end_time_ms)

# --- Backfill helpers --------------------------------------------------------------
def _stable_param_sig(params: dict) -> str:
    try:
        # Keep only stable keys to avoid frequent key churn
        keys = [k for k in ("symbol","baseCoin","exchange","exchanges","interval","timeframe","productType","rate","type","side","amount","size") if k in params]
        core = {k: params[k] for k in keys}
        blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
        return hashlib.md5(blob.encode()).hexdigest()[:10]
    except Exception:
        return "unknown"

def _series_cursor_key(endpoint_key: str, params: dict) -> str:
    # Prefer feature-oriented identity where possible
    try:
        family = CATEGORY_OF.get(endpoint_key, 'misc')
        base_coin = None
        if 'baseCoin' in params:
            base_coin = str(params['baseCoin'])
        elif 'symbol' in params:
            sym = str(params['symbol'])
            base_coin = sym.replace('USDT','') if sym.endswith('USDT') else sym
        exchange = None
        if 'exchange' in params:
            exchange = str(params['exchange'])
        elif 'exchanges' in params:
            exs = str(params['exchanges'])
            exchange = exs.split(',')[0].strip() if ',' in exs else exs
        interval_param = None
        if 'interval' in params:
            interval_param = str(params['interval'])
        elif 'timeframe' in params:
            interval_param = str(params['timeframe'])
        if base_coin and exchange and interval_param:
            return f"cursor:coinank:{family}:{base_coin}:{exchange}:{interval_param}:{endpoint_key}"
    except Exception:
        pass
    # Fallback to param signature
    sig = _stable_param_sig(params)
    return f"cursor:coinank:{endpoint_key}:{sig}"

def _enqueue_backfill(r, endpoint_key: str, params: dict, end_ms: int, step_ms: int):
    try:
        if not BACKFILL_ENABLED:
            return
        if not r:
            return
        prev_end = int(end_ms) - int(step_ms)
        if prev_end <= 0:
            return
        task = {"endpoint": endpoint_key, "params": {**params, "endTime": prev_end}}
        sig = hashlib.md5(json.dumps(task, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        seen_key = f"backfill:coinank:seen:{sig}"
        # Dedup for 24h
        if not r.set(seen_key, 1, nx=True, ex=86400):
            return
        # Enqueue to small todo list (right-pop consumer)
        qkey = "backfill:coinank:todo"
        r.lpush(qkey, json.dumps(task))
        try:
            if r.llen(qkey) > BACKFILL_QUEUE_MAX:
                r.ltrim(qkey, 0, BACKFILL_QUEUE_MAX-1)
        except Exception:
            pass
    except Exception:
        pass

ONE_TIME_BASIC_KEYS = {"baseCoin_list", "baseCoin_symbols"}  # run once per start
_one_time_cache = {}

def build_param_sets(key: str):
    spec = WORKING_COINANK_ENDPOINTS[key]
    mode = spec["mode"]
    params_list = []
    if mode == "static":
        params_list.append({})
    elif mode == "exchange":
        for ex in EXCHANGES:
            params_list.append({"exchange": ex, "productType": PRODUCT_TYPE})
    elif mode == "symbol_exchange":
        for ex in EXCHANGES:
            for sym in COINANK_SYMBOLS:
                params_list.append({"exchange": ex, "symbol": sym, "productType": PRODUCT_TYPE})
    elif mode == "base":
        for bc in _selected_base_coins():
            params_list.append({"baseCoin": bc})
    elif mode == "base_interval":
        for bc in _selected_base_coins():
            for iv in INTERVALS_PRIORITY:
                params_list.append({"baseCoin": bc, "interval": iv, "size": 100})
    elif mode == "base_interval_end":
        for bc in _selected_base_coins():
            for iv in INTERVALS_PRIORITY:
                params_list.append({
                    "baseCoin": bc, 
                    "interval": iv, 
                    "endTime": _effective_end_time(iv, int(_plan3_endtime_for_interval(iv))), 
                    "size": _get_max_size(iv, 100)  # Respect size limits
                })
    elif mode == "symbol_exchange_interval_end":
        for ex in EXCHANGES:
            hot_syms = [s for s in COINANK_SYMBOLS if s in ("BTCUSDT","ETHUSDT")]
            rest_syms = [s for s in COINANK_SYMBOLS if s not in ("BTCUSDT","ETHUSDT")]
            for iv in INTERVALS_PRIORITY:
                syms = hot_syms if iv in ("1m","5m") else (hot_syms + rest_syms[:8])  # cap breadth on slower TFs
                for sym in syms:
                    params_list.append({
                        "exchange": ex,
                        "symbol": sym,
                        "interval": iv,
                        "endTime": _effective_end_time(iv, int(_plan3_endtime_for_interval(iv))),
                        "size": _get_max_size(iv, 100),  # Respect size limits
                        "productType": PRODUCT_TYPE
                    })
    elif mode == "symbol_exchange_interval_end_no_producttype":
        for ex in EXCHANGES:
            for sym in COINANK_SYMBOLS:
                for iv in INTERVALS_PRIORITY:
                    params_list.append({
                        "exchange": ex,
                        "symbol": sym,
                        "interval": iv,
                        "endTime": _effective_end_time(iv, int(_plan3_endtime_for_interval(iv))),
                        "size": _get_max_size(iv, 100)  # Respect size limits, no productType
                    })
                    _validate_params(key, params_list[-1])
    elif mode == "exchanges_base_interval_end":
        # supports multi-exchange via comma list; we'll call per-exchange for clean metrics
        for ex in EXCHANGES:                     # e.g., ["Binance","OKX","Bybit","Huobi"]
            for bc in _selected_base_coins():    # derived from your fixed top-10
                for iv in INTERVALS_PRIORITY:    # your global interval priority list
                    d = {
                        "exchanges": ex,
                        "baseCoin": bc,
                        "interval": iv,
                        "endTime": _effective_end_time(iv, int(_plan3_endtime_for_interval(iv))),   # Plan‑3-aligned
                        "size": 10,                                   # per your screenshots
                        "productType": PRODUCT_TYPE                    # "SWAP" by default
                    }
                    params_list.append(d)
                    _validate_params(key, d)  # harmless log-only check
    elif mode == "funding_accumulated":
        for t in ["ALL", "PERPETUAL"]:
            params_list.append({"type": t})
    # elif mode == "orderbook_symbol":  # DISABLED: Only Binance/KuCoin handle OHLCV
    #     for ex in EXCHANGES:
    #         for sym in COINANK_SYMBOLS:
    #             params_list.append({
    #                 "symbol": sym,
    #                 "exchange": ex,
    #                 "rate": 0.5,
    #                 "productType": PRODUCT_TYPE,
    #                 "interval": "1h",
    #                 "endTime": _effective_end_time("1h", int(_plan3_endtime_for_interval("1h"))),
    #                 "size": 50
    #             })
    elif mode == "hyper_position":
        params_list.append({"sortBy": "volume", "sortType": "desc", "page": 1, "size": 50})
    elif mode == "liquidation_orders":  # Query historical liquidation orders (limit to selected base coins per run)
        # Use Plan 3 historical endTime to get maximum allowed historical data (30 days back)
        ends = _effective_end_time("1h", int(_plan3_historical_endtime()))
        # Query for selected base coins this pass
        selected_coins = _selected_base_coins()
        for bc in selected_coins:
            # Only query Binance for now to reduce load
            for side in ["long", "short"]:
                params_list.append({
                    "baseCoin": bc,
                    "exchange": "Binance",
                    "side": side,
                    "amount": "1000",  # Minimum turnover threshold
                    "endTime": ends
                })
            # All sides (combined)
            params_list.append({
                "baseCoin": bc,
                "exchange": "Binance",
                "endTime": ends
            })
        # Additional broad queries for overall market liquidation analysis
        for ex in EXCHANGES:
            params_list.append({"exchange": ex, "endTime": ends})  # All coins on exchange
            params_list.append({"exchange": ex, "side": "long", "endTime": ends})  # All long liq on exchange
            params_list.append({"exchange": ex, "side": "short", "endTime": ends})  # All short liq on exchange
    elif mode == "agg_market_base_interval_end":
        for bc in _selected_base_coins():
            for iv in ["1m", "5m", "30m", "1h"]:
                params_list.append({
                    "exchanges": ",".join(EXCHANGES),
                    "baseCoin": bc,
                    "interval": iv,
                    "endTime": _effective_end_time(iv, int(_plan3_endtime_for_interval(iv))),
                    "size": _get_max_size(iv, 100)  # Respect size limits
                })
    elif mode == "fund_history_base_interval_end":
        for bc in _selected_base_coins():
            for iv in ["5m", "30m", "1h", "4h", "1d"]:  # typical granular + broader
                params_list.append({
                    "baseCoin": bc,
                    "interval": iv,
                    "endTime": _effective_end_time(iv, int(_plan3_endtime_for_interval(iv))),
                    "size": _get_max_size(iv, 100)  # Respect size limits
                })
    elif mode == "fund_real":
        # Real-time fund flow spot + swap, prefer different sort fields
        for ptype in ["SPOT", "SWAP"]:
            for sortBy in ["h1net", "h4net", "d1net"]:
                params_list.append({
                    "productType": ptype,
                    "sortBy": sortBy,
                    "sortType": "desc",
                    "size": 500,  # keep under 1000 for safety
                    "page": 1
                })
    elif mode == "fundflow_realtime":
        # Real-time fund flow (following playbook pattern)
        for ptype in ["SPOT", "SWAP"]:
            params_list.append({
                "productType": ptype,
                "sortBy": "h1net",
                "sortType": "desc",
                "size": 1000,
                "page": 1
            })
    elif mode == "base_interval_end_with_producttype":
        # Historical fund flow (with aligned endTime)
        for bc in _selected_base_coins():
            for iv in ["1h", "4h", "1d"]:  # typical intervals for fund flow
                params_list.append({
                    "baseCoin": bc,
                    "interval": iv,
                    "endTime": _effective_end_time(iv, int(_plan3_endtime_for_interval(iv))),
                    "size": _get_max_size(iv, 100),
                    "productType": PRODUCT_TYPE
                })
    elif mode == "product_type_only":
        params_list.append({"productType": PRODUCT_TYPE})
    # New test-only modes
    elif mode == "net_positions_symbol_exchange_interval_end":
        symbols_iter = COINANK_SYMBOLS if EXPAND_ALL else [s for s in COINANK_SYMBOLS if s in ("BTCUSDT", "ETHUSDT")]
        for sym in symbols_iter:
            for iv in ["1m", "5m", "1h", "4h"]:
                params_list.append({
                    "exchange": "Binance",
                    "symbol": sym,
                    "interval": iv,
                    "endTime": _effective_end_time(iv, int(_plan3_endtime_for_interval(iv))),
                    "size": _get_max_size(iv, 100)  # Respect size limits
                })
    elif mode == "order_flow_lists":
        symbols_iter = COINANK_SYMBOLS if EXPAND_ALL else [s for s in COINANK_SYMBOLS if s in ("BTCUSDT", "ETHUSDT")]
        for sym in symbols_iter:
            for iv in ["1m", "5m", "1h"]:
                params_list.append({
                    "exchange": "Binance",
                    "symbol": sym,
                    "interval": iv,
                    "endTime": _effective_end_time(iv, int(_plan3_endtime_for_interval(iv))),
                    "size": min(_get_max_size(iv, 100), 500),  # Max 500 as per API docs
                    "productType": PRODUCT_TYPE,
                    "tickCount": 2  # Default 1, range 1-50, multiple of step size
                })
    elif mode == "rsi_map":
        # Use uppercase intervals required by API: map from lower list
        for iv in ["1H", "4H", "12H", "24H"]:
            params_list.append({"interval": iv, "exchange": "Binance"})
    elif mode == "big_order_query":
        # Large limit orders historical snapshot
        start = _now_ms()
        symbols_iter = COINANK_SYMBOLS if EXPAND_ALL else ["BTCUSDT", "ETHUSDT"]
        for sym in symbols_iter:
            params_list.append({
                "exchange": "Binance",
                "symbol": sym,
                "exchangeType": "SWAP",
                "amount": "1000000",
                "side": "ask",
                "isHistory": "true",
                "startTime": start,
                "size": 50
            })
    elif mode == "large_trades":
        symbols_iter = COINANK_SYMBOLS if EXPAND_ALL else ["BTCUSDT", "ETHUSDT"]
        for sym in symbols_iter:
            params_list.append({
                "exchange": "Binance",
                "symbol": sym,
                "productType": "SWAP",
                "amount": "500000",
                "size": 100,
                "endTime": _effective_end_time("1h", int(_plan3_historical_endtime()))  # 30d lookback aligned
            })
    elif mode == "funding_heatmap":
        # Heatmap supports type=marketCap|openInterest; interval example: 1M (monthly)
        # Keep conservative combinations to limit load.
        for t in ["marketCap", "openInterest"]:
            for iv in ["1M"]:  # documented example; extend if API supports more (e.g., 1W, 3M, 6M)
                params_list.append({"type": t, "interval": iv})
    elif mode == "funding_hist_base_end":
        # No interval in this API; align endTime using a representative interval boundary (1h)
        for bc in _selected_base_coins():
            params_list.append({
                "baseCoin": bc,
                "exchangeType": "USDT",
                "endTime": _effective_end_time("1h", int(_plan3_endtime_for_interval("1h"))),
                "size": 20  # per your example; safe <= 500
            })
    elif mode == "funding_current":
        params_list.append({"type": "current"})
    elif mode == "longshort_realtime_all":
        # Realtime by base coin; interval optional—query a couple of sensible cadences
        for bc in _selected_base_coins():
            for iv in ["5m", "1h"]:
                params_list.append({"baseCoin": bc, "interval": iv})
    elif mode == "longshort_kline_type":
        # Long/short kline requires type; keep minimal set (extend if needed)
        for ex in EXCHANGES:
            for sym in COINANK_SYMBOLS:
                for iv in ["1h", "4h"]:
                    for t in ["longShortPerson"]:  # add "longShortPosition","longShortAccount" if desired
                        params_list.append({
                            "exchange": ex,
                            "symbol": sym,
                            "interval": iv,
                            "endTime": _effective_end_time(iv, int(_plan3_endtime_for_interval(iv))),
                            "size": 10,
                            "type": t
                        })
    
    # Validate all generated parameters (harmless warnings only)
    for params in params_list:
        _validate_params(key, params)
    
    return params_list[:50]  # safety cap

def fetch_endpoint(key: str, path: str, params: dict):
    _validate_params(key, params)  # harmless log-only check
    url = BASE_URL + path
    update_counter("api_calls")
    
    try:
        # Small jitter to spread calls (kept tiny; pacing is primarily enforced by _rate_gate)
        base_sleep = float(os.getenv("COINANK_MIN_SLEEP_SEC", "0.05"))
        time.sleep(random.uniform(0.0, min(0.02, base_sleep)))
        _rate_gate()  # <--- NEW: enforce global RPM
        # Use longer timeout for liquidation orders endpoint due to heavy processing
        timeout = 30 if 'liquidation' in key.lower() else 12
        
        verbose_log(f"Fetching {key} with params: {list(params.keys())}")
        first_n_sample(f"API_CALL", {"endpoint": key, "url": url, "params": params})
        
        resp = SESSION.get(url, params=params, timeout=timeout)
        
        if resp.status_code == 429:
            # Handle rate limit: bump endpoint's min_iv with Retry-After when present
            global _endpoint_min_interval
            ra = resp.headers.get("Retry-After")
            if ra:
                try:
                    retry_after = float(ra)
                    _endpoint_min_interval[key] = min(max(_endpoint_min_interval.get(key, _BASE_MIN_INTERVAL), retry_after), _MAX_MIN_INTERVAL)
                except Exception:
                    _endpoint_min_interval[key] = min(_endpoint_min_interval.get(key, _BASE_MIN_INTERVAL) * 1.5, _MAX_MIN_INTERVAL)
            else:
                _endpoint_min_interval[key] = min(_endpoint_min_interval.get(key, _BASE_MIN_INTERVAL) * 1.5, _MAX_MIN_INTERVAL)
            logger.warning(f"{key} rate limited (429), adjusted min_iv to {_endpoint_min_interval[key]:.1f}s")
            update_counter("failed_fetches")
            update_counter("skipped_rate_limit")
            return None
            
        if resp.status_code != 200:
            logger.warning(f"{key} status {resp.status_code} {resp.text[:90]}")
            update_counter("failed_fetches")
            return None
            
        data = resp.json()
        update_counter("successful_fetches")
        debug_log(f"Successfully fetched {key}: {len(str(data))} bytes")
        first_n_sample(f"API_RESPONSE", {"endpoint": key, "data_size": len(str(data)), "status": resp.status_code})
        
        return data
        
    except Exception as e:
        logger.warning(f"{key} request error: {e}")
        update_counter("failed_fetches")
        update_counter("errors")
        return None

def persist(key: str, params: dict, data: dict, r, session_stats=None):
    WRITE_FILES = os.getenv("COINANK_WRITE_FILES", "1") == "1"  # default ON for data collection
    ts = _now_ms()
    safe_key = key.replace('/', '_')
    
    # Extract interval/timeframe from parameters for file organization
    interval = None
    if isinstance(params, dict):
        # Check for interval parameter in different formats
        interval = params.get('interval') or params.get('timeframe')
        if interval:
            interval = str(interval).upper()
    
    # Create the record
    rec = {"ts": ts, "endpoint": key, "params": params, "data": data}
    
    # Write to file only if enabled (to reduce I/O overhead)
    if WRITE_FILES:
        # Create timeframe-specific filename structure
        if interval:
            # Endpoints with timeframes: store in separate files per timeframe
            timeframe_dir = ROOT_DIR / 'data' / 'live' / 'timeframes' / interval
            timeframe_dir.mkdir(parents=True, exist_ok=True)
            fn = timeframe_dir / f"coinank_{safe_key}_{interval}.jsonl"
            
            # Update safe_key for Redis to include timeframe
            safe_key = f"{safe_key}_{interval}"
        else:
            # Endpoints without timeframes: store in general directory
            # Distinguish RSI map per interval so aggregator can access each timeframe's snapshot
            if key == 'rsiMap_list' and isinstance(params, dict) and params.get('interval'):
                iv = str(params.get('interval')).upper()
                safe_key = f"{safe_key}_{iv}"
                
            # Create general directory for non-timeframe endpoints
            general_dir = ROOT_DIR / 'data' / 'live' / 'general'
            general_dir.mkdir(parents=True, exist_ok=True)
            fn = general_dir / f"coinank_{safe_key}.jsonl"
        
        # Write to file (always append)
        try:
            with open(fn, 'a') as f:
                f.write(json.dumps(rec) + "\n")
            # Log the file structure for debugging
            if interval:
                logger.debug(f"Stored {key} [{interval}] -> {fn.relative_to(ROOT_DIR)}")
            else:
                logger.debug(f"Stored {key} [no-timeframe] -> {fn.relative_to(ROOT_DIR)}")
        except Exception as e:
            logger.warning(f"file write fail {fn.name}: {e}")
    
    # Store in Redis for real-time access
    if r:
        try:
            # Keep existing behavior (may include timeframe-suffixed safe_key)
            r.set(f"coinank:{safe_key}:last", json.dumps(rec))
            try:
                min_ttl = max(300, _tf_seconds(interval) * 2)
                r.expire(f"coinank:{safe_key}:last", min_ttl)
            except Exception:
                pass
            if session_stats:
                session_stats["redis_writes"] += 1
            # Also publish to unsuffixed endpoint key expected by aggregators
            # This is append-only and non-breaking (duplicates latest cache under canonical name)
            try:
                r.set(f"coinank:{key}:last", json.dumps(rec))
                try:
                    r.expire(f"coinank:{key}:last", max(300, _tf_seconds(interval) * 2))
                except Exception:
                    pass
                if session_stats:
                    session_stats["redis_writes"] += 1
            except Exception:
                pass
            
            # --- TRAINER FEATURE KEYS: features:coinank:<family>:<baseCoin>:<exchange>:<interval> ---
            try:
                # Map endpoint to family using existing CATEGORY_OF
                family = CATEGORY_OF.get(key, 'misc')
                
                # Extract baseCoin, exchange, interval from params
                base_coin = None
                exchange = None
                interval_param = None
                
                # Check if this is a global endpoint (no specific symbol/baseCoin)
                is_global_endpoint = not any(k in params for k in ['baseCoin', 'symbol'])
                
                if is_global_endpoint:
                    # Handle global endpoints - write to global features keys
                    global_raw_key = f"raw:coinank:{key}:global"
                    global_features_key = f"features:global_coinank:{key}:latest"
                    
                    # Flatten numeric fields from global data
                    flattened_features = {}
                    if isinstance(data, dict):
                        # First check if there's a nested 'data' field with the actual metrics
                        if 'data' in data and isinstance(data['data'], dict):
                            # Use the nested data field for flattening (contains the actual metrics)
                            _flatten_numeric_fields(data['data'], flattened_features, prefix=f"global_coinank_{key}_")
                            # Also flatten top-level numeric fields (like timestamp)
                            _flatten_numeric_fields(data, flattened_features, prefix=f"global_coinank_{key}_")
                        else:
                            # No nested data, flatten the entire dict
                            _flatten_numeric_fields(data, flattened_features, prefix=f"global_coinank_{key}_")
                    elif isinstance(data, list) and data:
                        # For list data, aggregate or take first item
                        if isinstance(data[0], dict):
                            first_item = data[0]
                            if 'data' in first_item and isinstance(first_item['data'], dict):
                                _flatten_numeric_fields(first_item['data'], flattened_features, prefix=f"global_coinank_{key}_")
                                _flatten_numeric_fields(first_item, flattened_features, prefix=f"global_coinank_{key}_")
                            else:
                                _flatten_numeric_fields(first_item, flattened_features, prefix=f"global_coinank_{key}_")
                    
                    # Add metadata
                    flattened_features.update({
                        "ts_epoch_ms": ts,
                        "timestamp": ts,
                        "endpoint": key,
                        "family": family,
                        "source": "coinank_global"
                    })
                    
                    # Write global raw data
                    r.set(global_raw_key, json.dumps({"ts": ts, "endpoint": key, "data": data}))
                    
                    # Write global features
                    r.set(global_features_key, json.dumps(flattened_features))
                    r.set(f"meta:coinank:last_update", ts)
                    
                    if session_stats:
                        session_stats["redis_writes"] += 2
                    
                else:
                    # Handle symbol-specific endpoints (existing logic)
                    # Get baseCoin - normalize to full symbol format expected by correlator
                    if 'baseCoin' in params:
                        base_coin_raw = str(params['baseCoin'])
                        # Convert base coin to full symbol format (ETH -> ETHUSDT)
                        if not base_coin_raw.endswith('USDT'):
                            base_coin = f"{base_coin_raw}USDT"
                        else:
                            base_coin = base_coin_raw
                    elif 'symbol' in params:
                        # Use symbol directly if provided
                        base_coin = str(params['symbol'])
                    else:
                        base_coin = None
                    
                    # Get exchange - prefer explicit exchange, fallback to default
                    if 'exchange' in params:
                        exchange = str(params['exchange'])
                    elif 'exchanges' in params:
                        # For aggregate endpoints, use first exchange or single exchange
                        exchanges = str(params['exchanges'])
                        exchange = exchanges.split(',')[0].strip() if ',' in exchanges else exchanges
                    else:
                        exchange = 'Binance'  # Default exchange
                    
                    # Get interval
                    if 'interval' in params:
                        interval_param = str(params['interval'])
                    elif 'timeframe' in params:
                        interval_param = str(params['timeframe'])
                    else:
                        interval_param = 'spot'  # Default for non-timeframe endpoints
                
                    # Only create feature keys if we have the required components
                    if base_coin and exchange and interval_param and family:
                        feature_key_base = f"features:coinank:{family}:{base_coin}:{exchange}:{interval_param}"
                        
                        # Flatten all numeric fields from data (NO FIELD FILTERING)
                        flattened_features = {}
                        if isinstance(data, dict):
                            # First check if there's a nested 'data' field with the actual metrics
                            if 'data' in data and isinstance(data['data'], dict):
                                # Use the nested data field for flattening (contains the actual metrics)
                                _flatten_numeric_fields(data['data'], flattened_features, prefix=f"coinank_{key}_")
                                # Also flatten top-level numeric fields (like timestamp)
                                _flatten_numeric_fields(data, flattened_features, prefix=f"coinank_{key}_")
                            else:
                                # No nested data, flatten the entire dict
                                _flatten_numeric_fields(data, flattened_features, prefix=f"coinank_{key}_")
                        elif isinstance(data, list) and data:
                            if isinstance(data[0], dict):
                                # Check if list items have nested 'data' field
                                first_item = data[0]
                                if 'data' in first_item and isinstance(first_item['data'], dict):
                                    _flatten_numeric_fields(first_item['data'], flattened_features, prefix=f"coinank_{key}_")
                                    _flatten_numeric_fields(first_item, flattened_features, prefix=f"coinank_{key}_")
                                else:
                                    _flatten_numeric_fields(first_item, flattened_features, prefix=f"coinank_{key}_")
                        
                        # Extract source timestamp from API response if available
                        source_ts_ms = ts  # fallback to request time
                        if isinstance(data, dict):
                            # Look for common timestamp fields in CoinAnk responses
                            for ts_field in ['timestamp', 'ts', 'time', 'server_time', 'data_time']:
                                if ts_field in data and isinstance(data[ts_field], (int, float)):
                                    candidate = int(data[ts_field])
                                    # Validate timestamp is reasonable (not too old/future)
                                    if candidate > 1600000000000 and candidate < (ts + 300000):  # within 5 min of now
                                        source_ts_ms = candidate
                                        break
                        
                        # Create feature record with normalized structure including ALL fields
                        feature_record = {
                            "ts_epoch_ms": ts,  # Required by live4.md (request time)
                            "source_ts_ms": source_ts_ms,  # API server time if available
                            "timestamp": source_ts_ms,  # Use source timestamp for freshness
                            "ts_ms": source_ts_ms,
                            "family": family,
                            "baseCoin": base_coin,
                            "exchange": exchange,
                            "interval": interval_param,
                            "endpoint": key,
                            "source": "coinank",
                            "raw_data": data,  # Keep raw for debugging
                            **flattened_features  # Include all flattened numeric fields
                        }
                        
                        # Write to features:coinank:<family>:<symbol>:<tf>:latest
                        latest_key = f"{feature_key_base}:latest"
                        r.set(latest_key, json.dumps(feature_record))
                        try:
                            r.expire(latest_key, max(300, _tf_seconds(interval_param) * 2))
                        except Exception:
                            pass
                        if session_stats:
                            session_stats["redis_writes"] += 1

                        # ------------------------------------------------------------------
                        # ALSO write endpoint-specific keys to prevent family-level collisions.
                        #
                        # Example: market_order_flow family is overwritten by marketOrder_getAggCvd
                        # returning {"success":false,"msg":"system error!"}. Storing per-endpoint
                        # allows trainer/modules to reliably consume the good endpoints without
                        # being clobbered by a failing sibling endpoint.
                        # ------------------------------------------------------------------
                        try:
                            ep_feature_key_base = f"features:coinank_endpoint:{key}:{base_coin}:{exchange}:{interval_param}"
                            ep_latest_key = f"{ep_feature_key_base}:latest"
                            r.set(ep_latest_key, json.dumps(feature_record))
                            try:
                                r.expire(ep_latest_key, max(300, _tf_seconds(interval_param) * 2))
                            except Exception:
                                pass
                            if session_stats:
                                session_stats["redis_writes"] += 1

                            # Endpoint-specific normalization mirror (best-effort)
                            if NORMALIZER_AVAILABLE and ENABLE_NORMALIZATION:
                                try:
                                    ep_normalized_features = normalize_data(feature_record, source="coinank")
                                    ep_normalized_key = f"{ep_feature_key_base}:normalized"
                                    r.set(ep_normalized_key, json.dumps(ep_normalized_features))
                                    try:
                                        r.expire(ep_normalized_key, max(300, _tf_seconds(interval_param) * 2))
                                    except Exception:
                                        pass
                                    if session_stats:
                                        session_stats["redis_writes"] += 1
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        
                        # Apply normalization (Phase 4 integration) - TRAINER ACCESS
                        if NORMALIZER_AVAILABLE and ENABLE_NORMALIZATION:
                            try:
                                normalized_features = normalize_data(feature_record, source='coinank')
                                normalized_key = f"{feature_key_base}:normalized"
                                r.set(normalized_key, json.dumps(normalized_features))
                                try:
                                    r.expire(normalized_key, max(300, _tf_seconds(interval_param) * 2))
                                except Exception:
                                    pass
                                if session_stats:
                                    session_stats["redis_writes"] += 1
                            except Exception as norm_ex:
                                logger.debug(f"Normalization failed for {latest_key}: {norm_ex}")
                    
                    # Also mirror to flat `latest:coinank:{family}:{SYMBOL}:{INTERVAL}` for snapshot/trainer gates
                    try:
                        flat_sym = f"{base_coin}USDT" if not str(base_coin).endswith("USDT") else str(base_coin)
                        flat_key = f"latest:coinank:{family}:{flat_sym}:{interval_param}"
                        r.set(flat_key, json.dumps({
                            "ts_ms": ts,
                            "symbol": flat_sym,
                            "exchange": exchange,
                            "family": family,
                            "endpoint": key,
                            "interval": interval_param,
                            "data": data
                        }))
                        try:
                            r.expire(flat_key, max(300, _tf_seconds(interval_param) * 2))
                        except Exception:
                            pass
                        if session_stats:
                            session_stats["redis_writes"] += 1

                        # Endpoint-specific flat snapshot (no collisions across endpoints)
                        try:
                            ep_flat_key = f"latest:coinank_endpoint:{key}:{flat_sym}:{interval_param}"
                            r.set(ep_flat_key, json.dumps({
                                "ts_ms": ts,
                                "timestamp": ts,
                                "symbol": flat_sym,
                                "exchange": exchange,
                                "family": family,
                                "endpoint": key,
                                "interval": interval_param,
                                "data": data if isinstance(data, (dict, list)) else {"value": data},
                            }))
                            try:
                                r.expire(ep_flat_key, max(300, _tf_seconds(interval_param) * 2))
                            except Exception:
                                pass
                            if session_stats:
                                session_stats["redis_writes"] += 1
                        except Exception:
                            pass
                    except Exception:
                        pass
                    
                    # Append to timeseries with cap of 500
                    series_key = f"{feature_key_base}:series"
                    try:
                        raw_series = r.get(series_key)
                        series_arr = json.loads(raw_series) if raw_series else []
                        series_arr.append(feature_record)
                        if len(series_arr) > 500:
                            series_arr = series_arr[-500:]
                        r.set(series_key, json.dumps(series_arr))
                        if session_stats:
                            session_stats["redis_writes"] += 1
                    except Exception:
                        # If series fails, at least we have latest
                        pass

                    # Also mirror into flat latest namespace for snapshot/trainer checks
                    try:
                        # Prefer full symbol if present; fallback to baseCoin+USDT
                        sym_for_key = None
                        if isinstance(params, dict) and params.get('symbol'):
                            sym_for_key = str(params.get('symbol'))
                        else:
                            sym_for_key = f"{base_coin}USDT"
                        tf_for_key = str(interval_param)
                        flat_key = f"latest:coinank:{family}:{sym_for_key}:{tf_for_key}"
                        flat_payload = {
                            "ts_ms": ts,
                            "timestamp": ts,
                            "family": family,
                            "symbol": sym_for_key,
                            "timeframe": tf_for_key,
                            "exchange": exchange,
                            "endpoint": key,
                            # keep numeric-rich content to aid field counting; cap to primary data blob
                            "data": data if isinstance(data, (dict, list)) else {"value": data}
                        }
                        r.set(flat_key, json.dumps(flat_payload))
                        if session_stats:
                            session_stats["redis_writes"] += 1
                    except Exception:
                        pass
                        
            except Exception as e:
                # Feature key writing is non-critical, don't fail the main persist
                logger.debug(f"Feature key write failed for {key}: {e}")
                pass
            
            # Build lightweight numeric time-series for selected endpoints (per symbol) for dashboard charts
            try:
                sym = params.get('symbol') or params.get('baseCoin')
                if sym:
                    base_coin = None
                    try:
                        base_coin = sym.replace('USDT', '') if isinstance(sym, str) else str(sym)
                    except Exception:
                        base_coin = str(sym)
                    series_key_base = None
                    value_payload = None
                    # Helper to safely pick numeric fields
                    def _extract_numeric(obj: dict, prefs):
                        for p in prefs:
                            if isinstance(obj, dict) and p in obj:
                                try:
                                    return float(obj[p])
                                except Exception:
                                    continue
                        # fallback: first numeric
                        if isinstance(obj, dict):
                            for k,v in obj.items():
                                try:
                                    if isinstance(v,(int,float)):
                                        return float(v)
                                except Exception:
                                    continue
                        return None
                    if safe_key == 'openInterest_symbol_Chart':
                        # Expect data structure maybe {'data': [...]} choose last
                        last_entry = None
                        try:
                            arr = data.get('data') or data.get('list') or []
                            if isinstance(arr, list) and arr:
                                last_entry = arr[-1]
                        except Exception:
                            pass
                        oi_val = _extract_numeric(last_entry or {}, ['openInterest','oi','value']) if last_entry else None
                        if oi_val is not None:
                            series_key_base = f'coinank:series:oi:{base_coin}'
                            value_payload = {'t': ts, 'v': oi_val}
                    elif safe_key == 'fundingRate_indicator':
                        last_entry = None
                        try:
                            arr = data.get('data') or data.get('list') or []
                            if isinstance(arr, list) and arr:
                                last_entry = arr[-1]
                        except Exception:
                            pass
                        fr_val = _extract_numeric(last_entry or {}, ['fundingRate','rate','value']) if last_entry else None
                        if fr_val is not None:
                            series_key_base = f'coinank:series:funding:{base_coin}'
                            value_payload = {'t': ts, 'v': fr_val}
                    elif safe_key == 'marketOrder_getBuySellVolume':
                        # Aggregate buy/sell volume from nested data structure
                        try:
                            # Extract the nested data: data.data.data is the list
                            actual_data = data.get('data', {}).get('data', [])
                            if isinstance(actual_data, list) and actual_data:
                                latest_entry = actual_data[-1]  # [timestamp, buy_volume, sell_volume]
                                if isinstance(latest_entry, list) and len(latest_entry) >= 3:
                                    timestamp = latest_entry[0]
                                    buy_v = float(latest_entry[1]) if latest_entry[1] is not None else None
                                    sell_v = float(latest_entry[2]) if latest_entry[2] is not None else None
                                    
                                    if buy_v is not None:
                                        series_key_base = f'coinank:series:buyVol:{base_coin}'
                                        value_payload = {'t': timestamp, 'v': buy_v}
                                        raw = r.get(series_key_base)
                                        arr = json.loads(raw) if raw else []
                                        arr.append(value_payload)
                                        if len(arr) > 500: arr = arr[-500:]
                                        r.set(series_key_base, json.dumps(arr))
                                    
                                    if sell_v is not None:
                                        series_key_base = f'coinank:series:sellVol:{base_coin}'
                                        value_payload = {'t': timestamp, 'v': sell_v}
                                        raw = r.get(series_key_base)
                                        arr = json.loads(raw) if raw else []
                                        arr.append(value_payload)
                                        if len(arr) > 500: arr = arr[-500:]
                                        # Persist sell volume series to its own key (bugfix: previously used undefined combo_key)
                                        r.set(series_key_base, json.dumps(arr))

                                    # Combined buy/sell volume series for dashboards
                                    if buy_v is not None or sell_v is not None:
                                        combo_key = f'coinank:series:buysell_volume:{base_coin}'
                                        combo_payload = {'t': timestamp, 'buy': buy_v or 0, 'sell': sell_v or 0}
                                        raw = r.get(combo_key)
                                        arr = json.loads(raw) if raw else []
                                        arr.append(combo_payload)
                                        if len(arr) > 500: arr = arr[-500:]
                                        r.set(combo_key, json.dumps(arr))
                            series_key_base = None  # prevent generic handling below since done
                        except Exception as e:
                            logger.warning(f"marketOrder_getBuySellVolume persist error: {e}")
                            pass
                    elif safe_key == 'marketOrder_getBuySellValue':
                        # Aggregate buy/sell value from nested data structure
                        try:
                            # Extract the nested data: data.data.data is the list
                            actual_data = data.get('data', {}).get('data', [])
                            if isinstance(actual_data, list) and actual_data:
                                latest_entry = actual_data[-1]  # [timestamp, buy_value, sell_value]
                                if isinstance(latest_entry, list) and len(latest_entry) >= 3:
                                    timestamp = latest_entry[0]
                                    buy_val = float(latest_entry[1]) if latest_entry[1] is not None else None
                                    sell_val = float(latest_entry[2]) if latest_entry[2] is not None else None
                                    
                                    if buy_val is not None or sell_val is not None:
                                        series_key_base = f'coinank:series:buysell_value:{base_coin}'
                                        value_payload = {'t': timestamp, 'buy': buy_val or 0, 'sell': sell_val or 0}
                                        raw = r.get(series_key_base)
                                        arr = json.loads(raw) if raw else []
                                        arr.append(value_payload)
                                        if len(arr) > 500: arr = arr[-500:]
                                        r.set(series_key_base, json.dumps(arr))
                                        series_key_base = None
                        except Exception as e:
                            logger.warning(f"marketOrder_getBuySellValue persist error: {e}")
                            pass
                    elif safe_key == 'marketOrder_getAggCvd':
                        # Aggregate CVD (Cumulative Volume Delta) from nested data structure
                        try:
                            # Note: This endpoint returns system error, but keeping logic for when it works
                            # Extract the nested data: data.data.data is the list  
                            actual_data = data.get('data', {}).get('data', [])
                            if isinstance(actual_data, list) and actual_data:
                                latest_entry = actual_data[-1]  # Assuming similar structure [timestamp, cvd_value]
                                cvd_val = None
                                if isinstance(latest_entry, list) and len(latest_entry) >= 2:
                                    timestamp = latest_entry[0]
                                    cvd_val = float(latest_entry[1]) if latest_entry[1] is not None else None
                                elif isinstance(latest_entry, dict):
                                    timestamp = latest_entry.get('ts') or ts
                                    cvd_val = _extract_numeric(latest_entry, ['cvd', 'cumulativeVolumeData', 'value'])
                                
                                if cvd_val is not None:
                                    series_key_base = f'coinank:series:agg_cvd:{base_coin}'
                                    value_payload = {'t': timestamp, 'v': cvd_val}
                                    raw = r.get(series_key_base)
                                    arr = json.loads(raw) if raw else []
                                    arr.append(value_payload)
                                    if len(arr) > 500: arr = arr[-500:]
                                    r.set(series_key_base, json.dumps(arr))
                                    series_key_base = None
                        except Exception as e:
                            logger.warning(f"marketOrder_getAggCvd persist error: {e}")
                            pass
                    elif safe_key == 'liquidation_orders':
                        # Extract liquidation data for comprehensive analysis
                        try:
                            liq_data = data.get('data') or data.get('list') or []
                            if isinstance(liq_data, list) and liq_data:
                                # Aggregate liquidation metrics
                                total_liquidated = 0
                                long_liq_sum = 0
                                short_liq_sum = 0
                                liq_count = len(liq_data)
                                
                                for liq_entry in liq_data:
                                    if isinstance(liq_entry, dict):
                                        amount = _extract_numeric(liq_entry, ['amount', 'value', 'turnover', 'notional']) or 0
                                        side = liq_entry.get('side', '').lower()
                                        total_liquidated += amount
                                        
                                        if 'long' in side or 'buy' in side:
                                            long_liq_sum += amount
                                        elif 'short' in side or 'sell' in side:
                                            short_liq_sum += amount
                                
                                # Store liquidation pressure metrics
                                if total_liquidated > 0:
                                    # Total liquidation pressure
                                    series_key_base = f'coinank:series:liquidations:{base_coin}'
                                    value_payload = {'t': ts, 'v': total_liquidated, 'count': liq_count}
                                    
                                    # Also store long/short breakdown
                                    liq_breakdown = {
                                        't': ts,
                                        'total': total_liquidated,
                                        'long': long_liq_sum,
                                        'short': short_liq_sum,
                                        'count': liq_count,
                                        'long_ratio': long_liq_sum / total_liquidated if total_liquidated > 0 else 0,
                                        'short_ratio': short_liq_sum / total_liquidated if total_liquidated > 0 else 0
                                    }
                                    
                                    # Store detailed breakdown
                                    liq_breakdown_key = f'coinank:series:liq_breakdown:{base_coin}'
                                    raw_breakdown = r.get(liq_breakdown_key)
                                    breakdown_arr = json.loads(raw_breakdown) if raw_breakdown else []
                                    breakdown_arr.append(liq_breakdown)
                                    if len(breakdown_arr) > 200: breakdown_arr = breakdown_arr[-200:]
                                    r.set(liq_breakdown_key, json.dumps(breakdown_arr))
                        except Exception:
                            pass
                    # Generic append if set
                    if series_key_base and value_payload is not None:
                        try:
                            raw = r.get(series_key_base)
                            arr = json.loads(raw) if raw else []
                            arr.append(value_payload)
                            if len(arr) > 500:
                                arr = arr[-500:]
                            r.set(series_key_base, json.dumps(arr))
                        except Exception:
                            pass
            except Exception:
                pass
        except Exception as e:
            # Outer Redis write guard to ensure persist() never raises
            logger.debug(f"Redis persist outer block failed for {key}: {e}")
            pass
    # ----------------- Always-on repeat detection + adaptive cooldown -----------------
    # This used to be gated by PRINT_OUTPUT, which disabled the adaptive logic in production.
    try:
        # PERF: repeat detection only needs within-process stability; avoid sort_keys (expensive on large payloads)
        payload_str = json.dumps(data, separators=(",", ":"))
    except Exception:
        payload_str = str(data)
    h = hex(abs(hash(payload_str)))[2:2+_HASH_TRUNCATE]
    prev = _last_payload_hash.get(key)
    _last_payload_hash[key] = h
    rep = _repeat_counts.get(key, 0)
    if prev == h:
        rep += 1
    else:
        rep = 0
    _repeat_counts[key] = rep

    # Ensure metrics entry exists and keep last_ts fresh for scheduler/admission logic.
    metrics = _metrics.setdefault(key, {"succ": 0, "err": 0, "empty": 0, "last_ts": ts, "full_prints": 0})
    metrics["last_ts"] = ts

    # If payload repeats too often, gently slow this endpoint (reduces wasted RPM).
    if rep and rep % _REPEAT_INCREASE_THRESHOLD == 0:
        cur_iv = _endpoint_min_interval.get(key, _BASE_MIN_INTERVAL)
        _endpoint_min_interval[key] = min(cur_iv * 2, _MAX_MIN_INTERVAL)

    # Optional console printing (debug/interactive only)
    if PRINT_OUTPUT:
        if metrics["full_prints"] < MAX_FULL_PRINTS:
            metrics["full_prints"] += 1
            snippet = payload_str[:400]
            print(f"[CoinAnk] {key} FULL params={{{', '.join(f'{k}={v}' for k,v in list(params.items())[:6])}}} size_hint={len(payload_str)} hash={h} repeats={rep} snippet={snippet}")
        else:
            core = {k: params[k] for k in list(params)[:4]}
            print(f"[CoinAnk] {key} DELTA params={core} hash={h} repeats={rep} succ={metrics['succ']} empty={metrics['empty']} min_iv={_endpoint_min_interval.get(key, _BASE_MIN_INTERVAL)}s")

def loop():
    debug_log("Starting CoinAnk ingestor with safe preflights")
    
    # Parse CLI/env overrides once at loop start
    try:
        _parse_cli_env_overrides()
    except Exception:
        pass

    # Safe preflight: Test Redis connectivity
    r = get_redis()
    if not r:
        logger.error("Redis connection failed; CoinAnk ingestion inactive")
        update_counter("errors")
        # Idle loop writing heartbeat so orchestrator doesn't restart endlessly
        for _ in range(60):  # ~60*5s = 5 minutes idle before function returns for retry
            try:
                write_diagnostic_heartbeat()
            except Exception:
                pass
            time.sleep(5)
        return
    
    verbose_log("Redis connection successful")
    debug_log(f"Redis connection established: {type(r)}")
    
    # Safe preflight: Test API key availability
    if not COINANK_API_KEY:
        logger.error("COINANK_API_KEY missing; CoinAnk ingestion inactive")
        update_counter("errors")
        # Idle loop writing heartbeat
        while True:
            try:
                write_diagnostic_heartbeat()
            except Exception:
                pass
            time.sleep(60)
            # Cooperative yield to prevent OS freeze
            time.sleep(0.01)
    
    verbose_log("CoinAnk API key configured")
    debug_log(f"API key present: {bool(COINANK_API_KEY)}")
    
    # Safe preflight: Test requests library
    try:
        import requests
        verbose_log("requests library import successful")
    except ImportError:
        logger.error("requests library not available; CoinAnk ingestion inactive")
        update_counter("errors")
        # Idle loop writing heartbeat
        for _ in range(60):
            try:
                write_diagnostic_heartbeat()
            except Exception:
                pass
            time.sleep(5)
        return
    
    # Safe preflight: Test SESSION configuration
    try:
        debug_log(f"Session headers: {dict(SESSION.headers)}")
        debug_log(f"Base URL: {BASE_URL}")
        verbose_log("Session configuration validated")
    except Exception as e:
        logger.error(f"Session configuration failed: {e}")
        update_counter("errors")
    
    # Single-instance guard (optional via env COINANK_SINGLETON=1)
    try:
        if r and os.getenv("COINANK_SINGLETON", "1") == "1":
            lock_key = "lock:live_coinank"
            # Acquire lock with 2 minutes TTL; auto-refresh later via heartbeat
            got = r.set(lock_key, str(_now_ms()), nx=True, ex=120)
            if not got:
                logger.warning("Another live_coinank instance holds the lock; exiting.")
                return
            debug_log("Singleton lock acquired successfully")
    except Exception as e:
        debug_log(f"Singleton lock check failed: {e}")
        pass
    # Order endpoints by category (start from 'instruments'), preserving original order within category
    original_order = {k:i for i,k in enumerate(WORKING_COINANK_ENDPOINTS.keys())}
    def _cat_rank(k: str) -> int:
        c = CATEGORY_OF.get(k, 'misc')
        try:
            return CATEGORY_ORDER.index(c)
        except ValueError:
            return CATEGORY_ORDER.index('misc')
    endpoint_cycle = sorted(WORKING_COINANK_ENDPOINTS.items(), key=lambda kv: (_cat_rank(kv[0]), original_order.get(kv[0], 0)))
    idx = 0
    prev_category = None
    _last_decay = time.time()
    _writer_stats = {"last_t": time.time(), "last_writes": message_counters.get("redis_writes", 0)}
    # Opportunistic backfill worker (best-effort, single-thread within loop)
    def _drain_backfill_once(r):
        if not BACKFILL_ENABLED:
            return
        if not r:
            return
        try:
            task_raw = r.rpop("backfill:coinank:todo")
            if not task_raw:
                return
            task = json.loads(task_raw)
            ep = task.get("endpoint")
            p = task.get("params", {})
            if not ep or not isinstance(p, dict):
                return
            # Respect existing rate gates
            data = fetch_endpoint(ep, WORKING_COINANK_ENDPOINTS.get(ep, {}).get('path', ''), p)
            # Update cursor regardless of content to avoid endless retry
            try:
                end_ms = int(p.get("endTime")) if p.get("endTime") else None
                if end_ms:
                    r.set(_series_cursor_key(ep, p), end_ms)
            except Exception:
                pass
            if data and isinstance(data, dict) and data.get("success"):
                try:
                    persist(ep, p, data, r, message_counters)
                except Exception:
                    pass
        except Exception:
            pass

    while True:
        global _PRESEEDED
        if r and not _PRESEEDED:
            try:
                # Registry list used by dashboard for auto-discovery
                r.set('coinank:endpoints', json.dumps(list(WORKING_COINANK_ENDPOINTS.keys())))
                # Seed metrics structure so brand-new endpoints appear immediately
                for _ek in WORKING_COINANK_ENDPOINTS.keys():
                    _metrics.setdefault(_ek, {"succ":0,"err":0,"empty":0,"last_ts":None,"full_prints":0})
                r.set('coinank:metrics', json.dumps({k:{**v, 'min_iv': _endpoint_min_interval.get(k, _BASE_MIN_INTERVAL)} for k,v in _metrics.items()}))
                _PRESEEDED = True
            except Exception:
                pass
        start_cycle = time.time()

        # ------------------------------------------------------------------
        # Scheduler: pick the next endpoint that is actually due, instead of
        # looping with fixed pauses between endpoints.
        #
        # This makes polling near-real-time while still respecting:
        # - per-endpoint min intervals (_endpoint_min_interval)
        # - global RPM gate (_rate_gate)
        # ------------------------------------------------------------------
        now_s = time.time()
        selected = None
        soonest_due = None
        wrapped = False

        scanned = 0
        while scanned < len(endpoint_cycle):
            cand_key, cand_spec = endpoint_cycle[idx]
            idx = (idx + 1) % len(endpoint_cycle)
            if idx == 0:
                wrapped = True
            scanned += 1

            # Skip one-time endpoints after cached
            if cand_key in ONE_TIME_BASIC_KEYS and cand_key in _one_time_cache:
                continue

            last_ts = _metrics.get(cand_key, {}).get("last_ts")
            min_iv = _endpoint_min_interval.get(cand_key, _BASE_MIN_INTERVAL)

            if not last_ts:
                selected = (cand_key, cand_spec)
                break

            try:
                age = now_s - (float(last_ts) / 1000.0)
            except Exception:
                age = 999999.0

            if age >= min_iv:
                selected = (cand_key, cand_spec)
                break

            due_in = max(0.0, float(min_iv) - float(age))
            if soonest_due is None or due_in < soonest_due:
                soonest_due = due_in

        if selected is None:
            # Nothing due right now. Drain one backfill task and sleep until the earliest due.
            try:
                _drain_backfill_once(r)
            except Exception:
                pass

            sleep_for = soonest_due if soonest_due is not None else 0.25
            # Cap to keep heartbeats/lock refresh responsive.
            sleep_for = max(0.05, min(float(sleep_for), 2.0))
            time.sleep(sleep_for)
            continue

        key, spec = selected

        # Cooperative yield to prevent OS freeze
        time.sleep(0.01)

        # Category transition pause (configurable; default 0 for near-real-time)
        current_category = CATEGORY_OF.get(key, 'misc')
        if prev_category is not None and current_category != prev_category:
            try:
                pause_s = float(os.getenv("COINANK_CATEGORY_SWITCH_PAUSE_SEC", "0"))
            except Exception:
                pause_s = 0.0
            if pause_s > 0:
                if PRINT_OUTPUT:
                    print(f"[CoinAnk] === Category switch: {prev_category} -> {current_category}; pausing {pause_s:.2f}s ===")
                time.sleep(pause_s)
        prev_category = current_category
        # Periodic decay of per-endpoint cooldowns
        try:
            if time.time() - _last_decay > 60:
                for _ek in list(_endpoint_min_interval.keys()):
                    _endpoint_min_interval[_ek] = max(_BASE_MIN_INTERVAL, _endpoint_min_interval[_ek] * 0.85)
                _last_decay = time.time()
        except Exception:
            pass
        params_list = build_param_sets(key)
        if not params_list:
            continue

        # Limit per-iteration work for any single endpoint to keep the system responsive.
        # This prevents multi-param endpoints (e.g., multi-interval histories) from blocking
        # hot endpoints like liquidation_orders.
        try:
            max_spend_sec = float(os.getenv("COINANK_ENDPOINT_MAX_SPEND_SEC", "6"))
        except Exception:
            max_spend_sec = 6.0
        try:
            max_calls_per_tick = int(os.getenv("COINANK_MAX_CALLS_PER_ENDPOINT_TICK", "4"))
        except Exception:
            max_calls_per_tick = 4
        max_calls_per_tick = max(1, min(max_calls_per_tick, 50))

        # Resume from previous cursor so we eventually cover all param-sets.
        start_i = int(_endpoint_param_cursor.get(key, 0) or 0) % max(1, len(params_list))
        calls_made = 0
        for off in range(len(params_list)):
            p = params_list[(start_i + off) % len(params_list)]
            data = fetch_endpoint(key, spec['path'], p)
            time.sleep(0.01)
            if data is None:
                metrics = _metrics.setdefault(key, {"succ": 0, "err": 0, "empty": 0, "last_ts": _now_ms(), "full_prints": 0})
                metrics["err"] += 1
                metrics["last_ts"] = _now_ms()
                if r:
                    try:
                        r.lpush('coinank:call_log', json.dumps({'ts': _now_ms(), 'endpoint': key, 'status': 'error', 'params': {k:p[k] for k in list(p)[:4]}, 'code': 'non_200'}))
                        r.ltrim('coinank:call_log', 0, 499)
                    except Exception:
                        pass
            else:
                success_flag = data.get("success") if isinstance(data, dict) else None
                if success_flag is False and "no data" in str(data).lower():
                    metrics = _metrics.setdefault(key, {"succ": 0, "err": 0, "empty": 0, "last_ts": _now_ms(), "full_prints": 0})
                    metrics["empty"] += 1
                    metrics["last_ts"] = _now_ms()
                    _last_payload_hash[key] = None
                    try:
                        sid = _series_cursor_key(key, p)
                        _backfill_empty_counts[sid] = _backfill_empty_counts.get(sid, 0) + 1
                        if _backfill_empty_counts[sid] >= BACKFILL_MAX_EMPTY:
                            if r and p.get('endTime'):
                                r.set(sid, int(p['endTime']))
                    except Exception:
                        pass
                    if PRINT_OUTPUT:
                        print(f"[CoinAnk] {key} EMPTY params={p}")
                    if r:
                        try:
                            r.lpush('coinank:call_log', json.dumps({'ts': _now_ms(), 'endpoint': key, 'status': 'empty', 'params': {k:p[k] for k in list(p)[:4]}}))
                            r.ltrim('coinank:call_log', 0, 499)
                        except Exception:
                            pass
                else:
                    persist(key, p, data, r, message_counters)
                    time.sleep(0.01)
                    metrics = _metrics.setdefault(key, {"succ": 0, "err": 0, "empty": 0, "last_ts": _now_ms(), "full_prints": 0})
                    metrics['succ'] += 1
                    metrics["last_ts"] = _now_ms()
                    try:
                        iv = str(p.get('interval') or p.get('timeframe') or '').lower()
                        step_ms = _tf_seconds(iv) * 1000 if iv else 0
                        end_ms = int(p['endTime']) if p.get('endTime') else None
                        if r and end_ms and step_ms:
                            r.set(_series_cursor_key(key, p), end_ms)
                            _enqueue_backfill(r, key, p, end_ms, step_ms)
                        sid = _series_cursor_key(key, p)
                        if sid in _backfill_empty_counts:
                            del _backfill_empty_counts[sid]
                    except Exception:
                        pass
                    if r:
                        try:
                            r.lpush('coinank:call_log', json.dumps({'ts': _now_ms(), 'endpoint': key, 'status': 'success', 'params': {k:p[k] for k in list(p)[:4]}}))
                            r.ltrim('coinank:call_log', 0, 499)
                        except Exception:
                            pass
            if key in ONE_TIME_BASIC_KEYS:
                _one_time_cache[key] = True
                if r:
                    try:
                        r.set(f"coinank:basic:{key}", json.dumps({"fetched_at": _now_ms(), "data": data}))
                    except Exception:
                        pass
            calls_made += 1
            if calls_made >= max_calls_per_tick:
                break
            if time.time() - start_cycle > max_spend_sec:
                break

        # Advance cursor for next tick (prevents starvation across param sets)
        try:
            _endpoint_param_cursor[key] = (start_i + calls_made) % max(1, len(params_list))
        except Exception:
            _endpoint_param_cursor[key] = 0

        try:
            _drain_backfill_once(r)
        except Exception:
            pass

        if r:
            try:
                now = _now_ms()
                r.set('ingest:coinank:last_ts', now)
                r.set(f'coinank:last_endpoint', key)
                r.set('heartbeat:IngestCoinAnk', json.dumps({"ts_ms": now, "service": "coinank_ingestor"}, separators=(",", ":")), ex=300)
                try:
                    if os.getenv("COINANK_SINGLETON", "1") == "1":
                        r.expire('lock:live_coinank', 120)
                except Exception:
                    pass
            except Exception:
                pass

        if int(time.time()) % 10 == 0:
            try:
                export = {}
                for _k, _m in _metrics.items():
                    export[_k] = dict(_m)
                    export[_k]['min_iv'] = _endpoint_min_interval.get(_k, _BASE_MIN_INTERVAL)
                r.set('coinank:metrics', json.dumps(export))
                now_t = time.time()
                dt = max(0.1, now_t - _writer_stats["last_t"])
                writes = message_counters.get("redis_writes", 0)
                dw = max(0, writes - _writer_stats["last_writes"])
                rate = dw / dt
                stats = {"write_rate_hz": round(rate, 3), "series_count": writes, "last_error": None, "t": _now_ms()}
                r.hset('stats:coinank:writer', mapping=stats)
                _writer_stats["last_t"] = now_t
                _writer_stats["last_writes"] = writes
            except Exception:
                pass

        # No fixed sleep between endpoints: pacing is handled by _rate_gate + per-endpoint min intervals.
        time.sleep(0.01)

        if idx == 0 and SINGLE_BASE_PER_RUN and BASE_COINS:
            global _base_coin_cursor
            _base_coin_cursor = (_base_coin_cursor + 1) % len(BASE_COINS)

def main():
    """Supervisor to keep CoinAnk ingestion alive (restart on errors)."""
    backoff = 5
    while True:
        try:
            loop()
            # loop() is designed to run forever; if it returns, honor normal exit
            break
        except KeyboardInterrupt:
            logger.info("CoinAnk ingestion stopped by user")
            break
        except Exception:
            logger.error("Fatal coinank loop error:\n" + traceback.format_exc())
            try:
                r = get_redis()
                if r:
                    r.set('proc:last_error:IngestCoinAnk', traceback.format_exc())
            except Exception:
                pass
            time.sleep(min(backoff, 180))
            backoff = min(backoff * 2, 180)
            # Cooperative yield to prevent OS freeze
            time.sleep(0.01)
        finally:
            # Best-effort lock release when exiting this supervisor cycle
            try:
                r = get_redis()
                if r and os.getenv("COINANK_SINGLETON", "1") == "1":
                    r.delete('lock:live_coinank')
            except Exception:
                pass

if __name__ == "__main__":
    try:
        from utils.interrupt_lock import exit_if_already_running
        exit_if_already_running(name="live_coinank", ttl_if_stale_seconds=600)
    except Exception:
        pass
    # Heartbeat + exit reporting
    try:
        from utils.healthbeat import start_heartbeat, report_exit
    except Exception:
        start_heartbeat = report_exit = None  # type: ignore
    r = None
    try:
        from utils.redis_client import get_redis
        r = get_redis()
    except Exception:
        r = None
    # Start dual heartbeats early and emit an immediate seed so dashboards don't show MISSING
    try:
        if r:
            _start_dual_heartbeat(r)
            _seed = json.dumps({"ts_ms": _now_ms(), "service": "coinank_ingestor"}, separators=(",", ":"))
            r.set("heartbeat:IngestCoinAnk", _seed, ex=300)
            r.set("heartbeat:CoinAnkIngest", _seed, ex=300)
    except Exception:
        pass
    try:
        if start_heartbeat:
            start_heartbeat(r, "IngestCoinAnk")
    except Exception:
        pass
    try:
        main()
        try:
            if report_exit:
                report_exit(r, "IngestCoinAnk", "ok", "completed")
        except Exception:
            pass
    except Exception as e:
        try:
            if report_exit:
                report_exit(r, "IngestCoinAnk", "error", repr(e))
        except Exception:
            pass
        raise
