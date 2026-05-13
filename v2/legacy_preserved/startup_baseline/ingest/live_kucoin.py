# -*- coding: utf-8 -*-
"""
KuCoin public-market ingestor (read-only) -> Redis
- Spot L1 (best bid/ask/last)
- OHLCV klines for multiple TFs
- Futures funding rate (current + next funding time) & open interest/mark/index via symbol detail
- Optional: partial L2 orderbook (20 levels)

Writes Redis keys (non-breaking, new namespaces):
  kc:latest:<SYMBOL>                       -> JSON {last,bid,ask,vol24h,ts,ex:"KUCOIN"}
  kc:kline:<SYMBOL>:<TF>                   -> JSON {ts, o,h,l,c,v, type}
  kc:funding:<SYMBOL>                      -> JSON {rate,predicted,nextTime,ts,contract}
  kc:open_interest:<SYMBOL>                -> float (OI)
  kc:mark_index:<SYMBOL>                   -> JSON {mark,index,premium,ts}
  kc:orderbook20:<SYMBOL>                  -> JSON {bids,asks,ts} (optional)
Plus heartbeat: "heartbeat:KuCoin" (ms epoch)

Safe defaults & feature flag via config.KUCOIN_ENABLED
"""
import os, time, json, math, logging, threading, sys, asyncio, socket, argparse
import websockets
import aiohttp
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
from pathlib import Path

# System Python - no interpreter guard needed

# Path injection for WMA AI Bot
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent  # This should be '/home/wali/Desktop/AI BOT'
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    import redis  # redis-py
except Exception:
    redis = None
import requests

# --- local imports (fall back if not present) ---
try:
    # TODO: At top – import config and set REDIS_URL
    from config import REDIS_URL, TIMEFRAMES, get_live_config, ENABLE_NORMALIZATION
    from utils.data_manager import DataManager
    from utils.data_normalizer import DataNormalizer
    
    # Dynamic symbol loading - supports hot-reload without restart
    try:
        from utils.symbol_manager import get_symbols_cached
        SYMBOLS = get_symbols_cached()
    except ImportError:
        from config import SYMBOLS
    
    _config = get_live_config()
    KUCOIN_ENABLED = _config.KUCOIN_ENABLED
    # Fallback config for KuCoin specific settings
    KUCOIN = {
        "BASE_SPOT": "https://api.kucoin.com",
        "BASE_FUTURES": "https://api-futures.kucoin.com",
        "TICKER_SEC": 3, "KLINES_SEC": 60, "FUNDING_SEC": 60, "ORDERBOOK_SEC": 30,
        "TIMEFRAMES": _config.TIMEFRAMES,
        "UNIVERSE": SYMBOLS,  # Use dynamic symbols
    }
except Exception as e:
    print(f"[DEBUG] Config import FAILED: {e}")
    # minimal fallback for standalone tests
    KUCOIN_ENABLED = 0
    KUCOIN = {
        "BASE_SPOT": "https://api.kucoin.com",
        "BASE_FUTURES": "https://api-futures.kucoin.com",
        "TICKER_SEC": 3, "KLINES_SEC": 60, "FUNDING_SEC": 60, "ORDERBOOK_SEC": 30,
        "TIMEFRAMES": ["1m","5m","15m","1h","4h"],
        "UNIVERSE": ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","UNIUSDT","LTCUSDT"],
    }

# --- logging ---
logging.basicConfig(level=logging.INFO, format='[KuCoin] %(asctime)s %(levelname)s: %(message)s')
log = logging.getLogger("live_kucoin")

# Initialize data normalizer for schema standardization
try:
    normalizer = DataNormalizer()
except Exception:
    normalizer = None
    log.warning("DataNormalizer not available - normalization disabled")

# Diagnostic flags and settings
DEBUG_MODE = os.getenv("RLBOT_DEBUG", "0") == "1"
VERBOSE_MODE = False  # Set by CLI args

# WebSocket configuration for low-latency data
WEBSOCKET_ENABLED = os.getenv("KUCOIN_WEBSOCKET", "1") == "1"
WEBSOCKET_URL = "wss://ws-api.kucoin.com/endpoint"
WEBSOCKET_FUTURES_URL = "wss://ws-api-futures.kucoin.com/endpoint"

# Circuit breaker for freeze detection
circuit_breaker_active = False
last_data_timestamp = {}
LATENCY_THRESHOLD_MS = 500  # Warn if processing takes > 500ms

def debug_log(msg: str):
    """Log debug messages only if debug mode is enabled."""
    if DEBUG_MODE or VERBOSE_MODE:
        print(f"[DEBUG live_kucoin] {msg}")
        log.debug(msg)

def increment_counter(redis_client, counter_name: str):
    """Increment a Redis counter for diagnostics."""
    if DEBUG_MODE or VERBOSE_MODE:
        try:
            if redis_client:
                key = f"counter:live_kucoin:{counter_name}"
                redis_client.incr(key)
                debug_log(f"Counter {counter_name} incremented")
        except Exception as e:
            debug_log(f"Failed to increment counter {counter_name}: {e}")

async def _dns_preflight(host: str):
    """DNS preflight check to verify hostname resolution before API calls"""
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        ips = sorted({ai[4][0] for ai in infos})
        log.info(f"[preflight] DNS OK for {host}: {ips}")
        debug_log(f"DNS preflight successful for {host}: {len(ips)} IPs resolved")
        return True
    except Exception as e:
        log.error(f"[preflight] DNS failed for {host}: {e}")
        debug_log(f"DNS preflight failed for {host}: {e}")
        return False

def _test_kucoin_connectivity():
    """Test KuCoin API connectivity with DNS preflight"""
    debug_log("Testing KuCoin API connectivity...")
    
    # Test KuCoin API endpoints
    kucoin_hosts = [
        "api.kucoin.com",
        "api-futures.kucoin.com"
    ]
    
    for host in kucoin_hosts:
        try:
            import socket
            socket.setdefaulttimeout(5)
            result = socket.gethostbyname(host)
            debug_log(f"✅ DNS resolved {host} -> {result}")
        except Exception as e:
            log.warning(f"❌ DNS resolution failed for {host}: {e}")
            return False
    
    return True

def safe_preflight_checks():
    """Perform safe preflight checks before starting."""
    debug_log("Starting preflight checks...")
    
    # Test KuCoin API DNS connectivity
    if not _test_kucoin_connectivity():
        log.error("KuCoin API DNS connectivity failed")
        return False
    
    # Check Redis connection
    try:
        r = get_redis()
        if r:
            r.ping()
            debug_log("✓ Redis connection verified")
        else:
            debug_log("✗ Redis connection failed")
            return False
    except Exception as e:
        debug_log(f"✗ Redis preflight failed: {e}")
        return False
    
    # Check KuCoin configuration
    try:
        debug_log(f"✓ KuCoin enabled: {KUCOIN_ENABLED}")
        debug_log(f"✓ Universe: {len(KUCOIN.get('UNIVERSE', []))} symbols")
        debug_log(f"✓ Timeframes: {KUCOIN.get('TIMEFRAMES', [])}")
    except Exception as e:
        debug_log(f"✗ KuCoin config check failed: {e}")
        return False
    
    debug_log("✓ Preflight checks completed successfully")
    return True

# --- Redis client ---
def get_redis():
    # TODO: Use REDIS_URL from config first, then env fallback
    try:
        if redis is None:
            raise RuntimeError("redis-py not available")
        
        # Use config REDIS_URL first, then env fallback
        url = REDIS_URL if 'REDIS_URL' in globals() else os.getenv("REDIS_URL", "")
        if url:
            r = redis.from_url(url, decode_responses=True)
        else:
            r = redis.Redis(host=os.getenv("REDIS_HOST","127.0.0.1"),
                            port=int(os.getenv("REDIS_PORT","6379")),
                            db=int(os.getenv("REDIS_DB","0")),
                            decode_responses=True)
        # ping test
        r.ping()
        return r
    except Exception as e:
        log.error(f"Redis unavailable: {e}")
        return None

R = get_redis()

# --- symbol normalization (uses unified symbol manager) ---
try:
    from utils.symbol_manager import normalize_symbol, convert_symbol
    _has_symbol_manager = True
except ImportError:
    _has_symbol_manager = False

def sym_spot_kucoin(symbol_ccxt: str) -> str:
    """Convert canonical symbol to KuCoin spot format: BTCUSDT -> BTC-USDT"""
    if _has_symbol_manager:
        # Use centralized normalizer
        canonical = normalize_symbol(symbol_ccxt)
        kucoin_fmt = convert_symbol(canonical, "kucoin")
        if kucoin_fmt:
            return kucoin_fmt
    
    # Fallback: manual conversion
    if "-" in symbol_ccxt:  # already dashed
        return symbol_ccxt
    if symbol_ccxt.endswith('USDT'):
        base = symbol_ccxt[:-4]
        return f"{base}-USDT"
    return symbol_ccxt

def sym_to_canonical(symbol_kucoin: str) -> str:
    """Convert KuCoin format back to canonical: BTC-USDT -> BTCUSDT"""
    if _has_symbol_manager:
        return normalize_symbol(symbol_kucoin)
    
    # Fallback: manual conversion
    return symbol_kucoin.replace('-', '').upper()

# KuCoin Futures contract symbols often use XBT for BTC and append 'M' for USDT Perp.
FUTS_MAP = {
    "BTCUSDT": "XBTUSDTM",
    "ETHUSDT": "ETHUSDTM",
    "SOLUSDT": "SOLUSDTM",
    "XRPUSDT": "XRPUSDTM",
    "DOGEUSDT": "DOGEUSDTM",
    "ADAUSDT": "ADAUSDTM",
    "AVAXUSDT": "AVAXUSDTM",
    "LINKUSDT": "LINKUSDTM",
    "UNIUSDT": "UNIUSDTM",
    "LTCUSDT": "LTCUSDTM",
}
def sym_futs_kucoin(symbol_ccxt: str) -> Optional[str]:
    return FUTS_MAP.get(symbol_ccxt)

# timeframe mapping for klines
TF_MAP = {
    "1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1hour", "4h": "4hour", "1d": "1day"
}

SPOT = KUCOIN["BASE_SPOT"].rstrip("/")
FUTS = KUCOIN["BASE_FUTURES"].rstrip("/")

SESS = requests.Session()
SESS.headers.update({"User-Agent": "WALI-RL/kucoin-ingestor"})

def _get(url: str, params: dict = None, base: str = SPOT) -> dict:
    full = f"{base}{url}"
    for i in range(3):
        try:
            resp = SESS.get(full, params=params, timeout=8)
            if resp.status_code == 429:
                # backoff if rate-limited
                time.sleep(0.5 + i)
                continue
            resp.raise_for_status()
            data = resp.json()
            # KuCoin wraps in {"code":"200000","data":...} or {"success":true,"data":...}
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            return data
        except Exception as e:
            if i == 2:
                log.error(f"GET {full} failed: {e}")
            time.sleep(0.3 * (i+1))
    return {}

def now_ms() -> int:
    return int(time.time() * 1000)

# -----------------------------------------------------------------------------
# Market-key write policy (T9 safety)
# -----------------------------------------------------------------------------
# KuCoin is a backup/fallback feed. To avoid clobbering fresher Binance/CoinAPI
# `market:{symbol}:{tf}` keys (which would make data appear stale), we only write
# to `market:*` when:
# - the key is missing, OR
# - the key is stale for that timeframe, OR
# - the existing key is already KuCoin-sourced.
#
# Override (old behavior): KUCOIN_MARKET_WRITE_MODE=always
# -----------------------------------------------------------------------------
KUCOIN_MARKET_WRITE_MODE = str(os.getenv("KUCOIN_MARKET_WRITE_MODE", "fallback") or "fallback").lower()

_TF_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
}


def _parse_ts_ms(d: dict) -> int:
    try:
        ts = d.get("timestamp") or d.get("ts_ms") or d.get("ts") or 0
        ts_f = float(ts)
        if ts_f < 1e12:
            ts_f *= 1000.0
        return int(ts_f)
    except Exception:
        return 0


def _max_age_ms_for_tf(tf: str) -> int:
    # Mirror scripts/validate_symbol_universe_data.py logic: allow up to ~2 candles.
    tf = str(tf or "").strip()
    sec = _TF_SECONDS.get(tf, 60)
    base_floor = 90 if tf in ("1m", "5m") else 600
    return int(max(base_floor, sec * 2) * 1000)


def _should_write_market_key(key: str, *, tf: str, new_ts_ms: int) -> bool:
    if KUCOIN_MARKET_WRITE_MODE == "always":
        return True
    if not R:
        return True
    try:
        existing_raw = R.get(key)
        if not existing_raw:
            return True
        try:
            existing = json.loads(existing_raw)
        except Exception:
            return True
        if not isinstance(existing, dict):
            return True

        existing_ts_ms = _parse_ts_ms(existing)
        if existing_ts_ms <= 0:
            return True
        if new_ts_ms > 0 and new_ts_ms < existing_ts_ms:
            # Never overwrite a newer market key with older data.
            return False

        src = str(existing.get("source") or "").lower()
        age_ms = max(0, now_ms() - existing_ts_ms)
        max_age_ms = _max_age_ms_for_tf(tf)

        # If the key is already KuCoin-sourced, allow forward progress (new candle) so
        # KuCoin can keep its own market keys fresh when it's the active fallback.
        if src.startswith("kucoin"):
            if new_ts_ms > existing_ts_ms:
                return True
            return age_ms > max_age_ms

        # Non-KuCoin source present: only overwrite when it is stale/missing (fallback behavior).
        return age_ms > max_age_ms
    except Exception:
        return True

# --- writers ---
def wkey(key: str, val):
    if not R: return
    try:
        if isinstance(val, (dict, list)):
            R.set(key, json.dumps(val, separators=(",",":")))
        elif isinstance(val, (int, float, str)):
            R.set(key, str(val))
        else:
            R.set(key, json.dumps(val))
    except Exception as e:
        log.error(f"Redis set {key} failed: {e}")

def heartbeat():
    # TODO: After each successful fetch/publish loop, write heartbeat with ms epoch
    ts_ms = int(time.time() * 1000)
    wkey("heartbeat:KuCoin", ts_ms)
    
    # TODO: After writing each batch, log non-zero keys for sanity during bring-up
    if int(time.time()) % 15 == 0:
        try:
            price_sample = R.get(f"price:{SYMBOLS[0]}") if R and SYMBOLS else "NA"
            ob_sample = R.hgetall(f"orderbook:top:{SYMBOLS[0]}") if R and SYMBOLS else {}
            print(f"[INGEST] sample {SYMBOLS[0] if SYMBOLS else 'BTCUSDT'} price={price_sample} ob(bid/ask)={[ob_sample.get('bid'), ob_sample.get('ask')]}")
        except Exception as e:
            pass  # Don't let logging break the main loop

# --- WebSocket streams for low-latency data ---
async def _websocket_ticker_stream(symbols: List[str], dm, redis_client):
    """WebSocket ticker stream for real-time price updates"""
    global last_data_timestamp
    
    try:
        # Get WebSocket connection token from KuCoin
        response = requests.post(f"{KUCOIN['BASE_SPOT']}/api/v1/bullet-public")
        if response.status_code != 200:
            log.error(f"Failed to get KuCoin WebSocket token: {response.status_code}")
            return
            
        token_data = response.json()['data']
        ws_url = f"{token_data['instanceServers'][0]['endpoint']}?token={token_data['token']}"
        
        async with websockets.connect(ws_url) as websocket:
            # Subscribe to ticker streams for all symbols
            subscribe_msg = {
                "id": int(time.time() * 1000),
                "type": "subscribe",
                "topic": "/market/ticker:all",
                "response": True
            }
            await websocket.send(json.dumps(subscribe_msg))
            log.info(f"🚀 KuCoin WebSocket ticker stream connected for backup price feed")
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    if data.get('type') == 'message' and data.get('topic') == '/market/ticker:all':
                        ticker_data = data.get('data', {})
                        symbol = ticker_data.get('symbol', '').replace('-', '')
                        
                        if symbol in symbols:
                            # Update timestamp for circuit breaker
                            stream_key = f"kucoin_ticker_{symbol}"
                            last_data_timestamp[stream_key] = time.time() * 1000
                            
                            # Process ticker data
                            await _process_websocket_ticker(symbol, ticker_data, dm, redis_client)
                            
                except Exception as e:
                    log.error(f"Error processing KuCoin ticker WebSocket message: {e}")
                    
    except Exception as e:
        log.error(f"KuCoin ticker WebSocket connection error: {e}")

async def _process_websocket_ticker(symbol: str, ticker_data: Dict, dm, redis_client):
    """Process WebSocket ticker data with low latency"""
    start_time = time.time()
    
    try:
        price = float(ticker_data.get('price', 0))
        bid = float(ticker_data.get('bestBid', 0))
        ask = float(ticker_data.get('bestAsk', 0))
        volume = float(ticker_data.get('vol', 0))
        ts = int(ticker_data.get('time', time.time() * 1000))
        
        # Store in Redis with KuCoin namespace
        ticker_obj = {
            "price": price,
            "bid": bid,
            "ask": ask,
            "volume_24h": volume,
            "timestamp": ts,
            "source": "kucoin_ws",
            "ex": "KUCOIN"
        }
        
        if redis_client:
            redis_client.set(f"kc:ws:ticker:{symbol}", json.dumps(ticker_obj), ex=60)
            
            # Store as backup price feed for circuit breaker system
            backup_data = {
                "symbol": symbol,
                "price": price,
                "bid": bid,
                "ask": ask,
                "timestamp": ts,
                "source": "kucoin_backup"
            }
            redis_client.set(f"backup_feed:{symbol}", json.dumps(backup_data), ex=30)
            
        # Check processing latency
        processing_time = (time.time() - start_time) * 1000
        if processing_time > LATENCY_THRESHOLD_MS:
            log.warning(f"⚠️ High KuCoin WS processing latency: {processing_time:.1f}ms for {symbol}")
            
    except Exception as e:
        log.error(f"❌ Error processing KuCoin WebSocket ticker for {symbol}: {e}")

def _start_kucoin_websocket_thread():
    """Start KuCoin WebSocket streams in background thread"""
    if not WEBSOCKET_ENABLED:
        log.info("🚫 KuCoin WebSocket disabled via KUCOIN_WEBSOCKET=0")
        return
        
    def _runner():
        dm = DataManager(Path(__file__).resolve().parent.parent / 'data' / 'live')
        redis_client = get_redis()
        uni = KUCOIN.get("UNIVERSE", [])
        asyncio.run(_websocket_ticker_stream(uni, dm, redis_client))
    
    t = threading.Thread(target=_runner, name="kucoin-websocket", daemon=True)
    t.start()
    log.info("🚀 KuCoin WebSocket thread started as backup price feed")

# --- spot L1 ticker ---
def poll_spot_tickers(symbols: List[str]):
    debug_log(f"Starting spot ticker polling for {len(symbols)} symbols")
    increment_counter(R, "poll_spot_tickers_calls")
    
    ts = now_ms()
    log.info(f"🔄 Polling spot tickers for {len(symbols)} symbols...")
    
    for s in symbols:
        ks = sym_spot_kucoin(s)
        debug_log(f"Fetching ticker for {s} (KuCoin symbol: {ks})")
        log.info(f"📊 Fetching {s} ticker from KuCoin...")
        
        data = _get("/api/v1/market/orderbook/level1", {"symbol": ks}, base=SPOT)
        if not data: 
            log.warning(f"❌ No data received for {s}")
            increment_counter(R, "ticker_fetch_errors")
            continue
            
        increment_counter(R, "ticker_fetch_success")
        out = {
            "ex": "KUCOIN",
            "symbol": s,
            "kucoinSymbol": ks,
            "bid": float(data.get("bestBid","0")) if data.get("bestBid") else None,
            "ask": float(data.get("bestAsk","0")) if data.get("bestAsk") else None,
            "last": float(data.get("price","0")) if data.get("price") else None,
            "size": float(data.get("size","0")) if data.get("size") else None,
            "vol24h": float(data.get("vol","0")) if data.get("vol") else None,
            "ts": ts
        }
        last_str = f"{out['last']:.4f}" if out['last'] is not None else "N/A"
        bid_str = f"{out['bid']:.4f}" if out['bid'] is not None else "N/A"
        ask_str = f"{out['ask']:.4f}" if out['ask'] is not None else "N/A"
        vol_str = f"{out['vol24h']:.2f}" if out['vol24h'] is not None else "N/A"
        log.info(f"✅ {s}: Last=${last_str}, Bid=${bid_str}, Ask=${ask_str}, Vol24h={vol_str}")
        debug_log(f"Successfully processed ticker data for {s}")
        
        # Store in KuCoin namespace
        wkey(f"kc:latest:{s}", out)
        
        # Store in market namespace for trainer compatibility (same format as Binance)
        if out['last'] is not None:
            market_data = {
                "price": out['last'],
                "bid": out['bid'],
                "ask": out['ask'],
                "volume_24h": out['vol24h'],
                "source": "kucoin",
                "timestamp": ts
            }
            # Use 1m freshness semantics for price (low-latency key)
            mkey = f"market:{s}:price"
            if _should_write_market_key(mkey, tf="1m", new_ts_ms=int(ts)):
                wkey(mkey, market_data)  # Trainer looks for market:{sym}:price
            increment_counter(R, "redis_writes")
            debug_log(f"Stored market data for {s} in Redis")

# --- OHLCV klines (latest bucket) ---
def poll_klines(symbols: List[str], tfs: List[str], dm=None):
    ts = now_ms()
    log.info(f"📈 Polling klines for {len(symbols)} symbols x {len(tfs)} timeframes...")
    for s in symbols:
        ks = sym_spot_kucoin(s)
        for tf in tfs:
            kt = TF_MAP.get(tf, "1min")
            log.info(f"🕒 Fetching {s} {tf} kline...")
            data = _get("/api/v1/market/candles", {"symbol": ks, "type": kt, "limit": 1}, base=SPOT)
            if not data:
                log.warning(f"❌ No kline data for {s} {tf}")
                continue
            # format: [time, open, close, high, low, volume, turnover]
            # KuCoin time is in seconds as string
            try:
                arr = data[0]
                out = {
                    "type": kt,
                    "ts": int(arr[0]) * 1000,
                    "o": float(arr[1]),
                    "c": float(arr[2]),
                    "h": float(arr[3]),
                    "l": float(arr[4]),
                    "v": float(arr[5]),
                    "turnover": float(arr[6]) if len(arr) > 6 and arr[6] is not None else None,
                    "symbol": s,
                    "kucoinSymbol": ks
                }
                o_str = f"{out['o']:.4f}" if out['o'] is not None else "N/A"
                h_str = f"{out['h']:.4f}" if out['h'] is not None else "N/A"
                l_str = f"{out['l']:.4f}" if out['l'] is not None else "N/A"
                c_str = f"{out['c']:.4f}" if out['c'] is not None else "N/A"
                v_str = f"{out['v']:.2f}" if out['v'] is not None else "N/A"
                log.info(f"✅ {s} {tf}: OHLC=${o_str}/{h_str}/{l_str}/{c_str}, Vol={v_str}")
                
                # Store in KuCoin namespace
                wkey(f"kc:kline:{s}:{tf}", out)
                
                # Store in market namespace for trainer compatibility 
                market_kline = {
                    "timestamp": out['ts'],
                    "open": out['o'],
                    "high": out['h'], 
                    "low": out['l'],
                    "close": out['c'],
                    "volume": out['v'],
                    "source": "kucoin"
                }
                mkey = f"market:{s}:{tf}"
                if _should_write_market_key(mkey, tf=tf, new_ts_ms=int(out['ts'])):
                    wkey(mkey, market_kline)  # Trainer looks for market:{sym}:{tf}
                
                # Write normalized OHLCV keys - backup source after Binance WebSocket
                if normalizer and ENABLE_NORMALIZATION:
                    try:
                        normalized_data = {
                            "symbol": s,
                            "timeframe": tf,
                            "timestamp": out['ts'],
                            "open": out['o'],
                            "high": out['h'],
                            "low": out['l'],
                            "close": out['c'],
                            "volume": out['v'],
                            "source": "kucoin"
                        }
                        normalized = normalizer.normalize(normalized_data, source="kucoin", enable_normalization=True)
                        normalized_key = f"features:kucoin:{s}:{tf}:normalized"
                        if R:
                            R.setex(normalized_key, 300, json.dumps(normalized))
                        log.debug(f"✅ Normalized KuCoin OHLCV: {normalized_key}")
                    except Exception as norm_err:
                        log.error(f"❌ Normalization error for {s} {tf}: {norm_err}")
                
                # Also write to OHLCV files (secondary writer)
                if dm and out['o'] is not None and out['c'] is not None:
                    bar = {
                        "timestamp": out['ts'],
                        "open": out['o'],
                        "high": out['h'],
                        "low": out['l'], 
                        "close": out['c'],
                        "volume": out['v'],
                        "source": "kucoin"
                    }
                    dm.append_live_bar(s, tf, bar)
            except Exception as e:
                log.warning(f"kline parse {s} {tf} failed: {e}")

# --- Futures funding & contract detail (OI/mark/index/premium) ---
def poll_futures_meta(symbols: List[str]):
    ts = now_ms()
    for s in symbols:
        fc = sym_futs_kucoin(s)
        if not fc:
            continue
        # funding (current)
        fr = _get("/api/ua/v1/market/funding-rate", {"symbol": fc}, base=SPOT)  # UA path proxied on spot host
        if fr:
            out_f = {
                "contract": fc,
                "symbol": s,
                "rate": float(fr.get("fundingRate","0")) if fr.get("fundingRate") else None,
                "predicted": float(fr.get("predictedFundingRate","0")) if fr.get("predictedFundingRate") else None,
                "nextTime": int(fr.get("nextFundingRateTime","0")) if fr.get("nextFundingRateTime") else None,
                "ts": ts
            }
            wkey(f"kc:funding:{s}", out_f)
        # symbol detail (OI, mark/index/premium etc) on futures host
        det = _get(f"/api/v1/contracts/{fc}", base=FUTS)
        if det:
            try:
                oi = float(det.get("openInterest")) if det.get("openInterest") is not None else None
                wkey(f"kc:open_interest:{s}", oi if oi is not None else "")
                out_mi = {
                    "mark": float(det.get("markPrice")) if det.get("markPrice") is not None else None,
                    "index": float(det.get("indexPrice")) if det.get("indexPrice") is not None else None,
                    "premium8h": det.get("premiumsSymbol8H"),
                    "premium1m": det.get("premiumsSymbol1M"),
                    "ts": ts,
                    "contract": fc,
                    "symbol": s
                }
                wkey(f"kc:mark_index:{s}", out_mi)
            except Exception as e:
                log.warning(f"symbol detail parse {s} failed: {e}")

# --- Optional: Partial L2 book (20 levels) ---
def poll_orderbook20(symbols: List[str]):
    ts = now_ms()
    for s in symbols:
        ks = sym_spot_kucoin(s)
        ob = _get("/api/v1/market/orderbook/level2_20", {"symbol": ks}, base=SPOT)
        if not ob:
            continue
        out = {"bids": ob.get("bids", []), "asks": ob.get("asks", []), "ts": ts, "symbol": s, "kucoinSymbol": ks}
        wkey(f"kc:orderbook20:{s}", out)

def write_unified_orderbook(symbols: List[str]):
    """Write orderbook data in unified format (orderbook:top/bids/asks) for feature_pipeline compatibility"""
    ts = now_ms()
    for s in symbols:
        # Try to get KuCoin orderbook data
        kc_key = f"kc:orderbook20:{s}"
        ob_data = R.get(kc_key) if R else None
        
        if not ob_data:
            continue
            
        try:
            if isinstance(ob_data, str):
                ob = json.loads(ob_data)
            else:
                ob = ob_data
                
            bids = ob.get("bids", [])
            asks = ob.get("asks", [])
            
            if not bids or not asks:
                continue
            
            # Calculate orderbook metrics
            best_bid = float(bids[0][0]) if bids else 0
            best_ask = float(asks[0][0]) if asks else 0
            
            # Calculate volumes
            bid_volume = sum(float(b[1]) for b in bids[:10])
            ask_volume = sum(float(a[1]) for a in asks[:10])
            total_volume = bid_volume + ask_volume
            
            # Calculate notional values
            bid_notional = sum(float(b[0]) * float(b[1]) for b in bids[:10])
            ask_notional = sum(float(a[0]) * float(a[1]) for a in asks[:10])
            
            # Calculate metrics
            spread = best_ask - best_bid if best_bid > 0 and best_ask > 0 else 0
            imbalance = (bid_volume - ask_volume) / total_volume if total_volume > 0 else 0
            
            # Write to unified format (compatible with feature_pipeline.old.py)
            summary = {
                "bid": best_bid,
                "ask": best_ask,
                "spread": spread,
                "imbalance": imbalance,
                "bid_volume": bid_volume,
                "ask_volume": ask_volume,
                "bid_notional": bid_notional,
                "ask_notional": ask_notional,
                "bid_depth": bid_notional,
                "ask_depth": ask_notional,
                "total_depth": bid_notional + ask_notional,
                "ts": ts,
                "source": "kucoin"
            }
            
            # Write to Redis in expected format
            if R:
                # Respect Binance as primary: if an existing book is marked binance and fresh (<5s), skip overwrite
                try:
                    existing = R.get(f"orderbook:top:{s}")
                    if existing:
                        parsed_existing = json.loads(existing)
                        ts_existing = int(parsed_existing.get('ts', 0)) if isinstance(parsed_existing, dict) else 0
                        is_binance = False
                        if isinstance(parsed_existing, dict):
                            is_binance = bool(parsed_existing.get('binance_symbol')) or parsed_existing.get('source') == 'binance'
                        if is_binance and ts_existing and ts - ts_existing < 5000:
                            continue
                except Exception:
                    pass

                R.set(f"orderbook:top:{s}", json.dumps(summary))
                R.set(f"orderbook:bids:{s}", json.dumps(bids[:50]))  # Top 50 levels
                R.set(f"orderbook:asks:{s}", json.dumps(asks[:50]))
                R.set(f"heartbeat:OrderBook:{s}", ts)
                
        except Exception as e:
            log.error(f"Error writing unified orderbook for {s}: {e}")

def main():
    """Main entry point with CLI argument parsing."""
    global VERBOSE_MODE
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="KuCoin Market Data Ingestor")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()
    
    VERBOSE_MODE = args.verbose
    
    if DEBUG_MODE or VERBOSE_MODE:
        print("[live_kucoin] Starting in debug/verbose mode")
        print(f"[live_kucoin] Debug mode: {DEBUG_MODE}")
        print(f"[live_kucoin] Verbose mode: {VERBOSE_MODE}")
    
    # Perform preflight checks
    if not safe_preflight_checks():
        print("[live_kucoin] Preflight checks failed, exiting")
        return
    
    if args.once:
        debug_log("Running single cycle (--once mode)")
        # Run one cycle of each polling function
        if not KUCOIN_ENABLED:
            log.warning("KUCOIN_ENABLED=0 (no-op). Enable in config to start ingest.")
            return
            
        uni = KUCOIN.get("UNIVERSE", [])
        tfs = KUCOIN.get("TIMEFRAMES", ["1m","5m","15m","1h","4h"])
        
        try:
            debug_log("Running single poll cycles...")
            # Initialize DataManager for OHLCV file writing in --once mode too
            dm = DataManager(Path(__file__).resolve().parent.parent / 'data' / 'live')
            poll_spot_tickers(uni)
            poll_klines(uni, tfs, dm)
            poll_futures_meta(uni)
            heartbeat()
            debug_log("Single cycle completed successfully")
        except Exception as e:
            log.error(f"Single cycle error: {e}")
    else:
        debug_log("Starting continuous mode")
        main_loop()

def main_loop():
    if not KUCOIN_ENABLED:
        log.warning("KUCOIN_ENABLED=0 (no-op). Enable in config to start ingest.")
        return
    
    # Initialize DataManager for OHLCV file writing
    dm = DataManager(Path(__file__).resolve().parent.parent / 'data' / 'live')
    
    uni = KUCOIN.get("UNIVERSE", [])
    tfs = KUCOIN.get("TIMEFRAMES", ["1m","5m","15m","1h","4h"])
    sec_tk = KUCOIN.get("TICKER_SEC", 3)
    sec_kl = KUCOIN.get("KLINES_SEC", 60)
    sec_fr = KUCOIN.get("FUNDING_SEC", 60)
    sec_ob = KUCOIN.get("ORDERBOOK_SEC", 30)

    t0_tk = t0_kl = t0_fr = t0_ob = 0
    log.info(f"Starting KuCoin ingest for {len(uni)} symbols...")
    debug_log(f"Polling intervals: tickers={sec_tk}s, klines={sec_kl}s, funding={sec_fr}s")
    
    # Start WebSocket stream as backup price feed
    _start_kucoin_websocket_thread()
    
    cycle_count = 0
    while True:
        now = time.time()
        try:
            if now - t0_tk >= sec_tk:
                poll_spot_tickers(uni)
                t0_tk = now
            if now - t0_kl >= sec_kl:
                poll_klines(uni, tfs, dm)
                t0_kl = now
            if now - t0_fr >= sec_fr:
                poll_futures_meta(uni)
                t0_fr = now
            if sec_ob and (now - t0_ob >= sec_ob):
                # Fetch orderbook data for all symbols
                poll_orderbook20(uni)
                # Also write to unified orderbook format for feature_pipeline
                write_unified_orderbook(uni)
                t0_ob = now
            heartbeat()
            
            cycle_count += 1
            if cycle_count % 100 == 0:  # Log every 100 cycles
                debug_log(f"Completed {cycle_count} cycles")
                increment_counter(R, "main_loop_cycles")
                
        except KeyboardInterrupt:
            debug_log("Keyboard interrupt received, shutting down")
            break
        except Exception as e:
            log.error(f"loop error: {e}")
            increment_counter(R, "main_loop_errors")
        time.sleep(0.25)

if __name__ == "__main__":
    import argparse
    main()
