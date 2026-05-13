import os, time, json, traceback, sys, threading, asyncio, socket
import ccxt
import aiohttp
import websockets
from aiohttp import resolver, TCPConnector
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict, deque
import logging
import psutil  # For memory monitoring
import gc  # For garbage collection

# System Python - no interpreter guard needed

# Path injection for WMA AI Bot
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent  # This should be 'c:\AI BOT'
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
        
# Interpreter guard replaced by utils.interpreter_guard

try:
    from config import get_live_config
    _config = get_live_config()
    SYMBOLS = _config.SYMBOLS
    TIMEFRAMES = _config.TIMEFRAMES
    try:
        _CONF_OB_MARKET = getattr(_config, 'ORDERBOOK_MARKET', None)
    except Exception:
        _CONF_OB_MARKET = None
    try:
        # Optional dedicated list; default to training SYMBOLS (10 coins)
        _ORDERBOOK_SYMBOLS = getattr(_config, 'ORDERBOOK_SYMBOLS', SYMBOLS)
    except Exception:
        _ORDERBOOK_SYMBOLS = SYMBOLS
    from utils.logger import get_logger
    from utils.data_manager import DataManager
    from utils.redis_client import get_redis
    from utils.data_normalizer import DataNormalizer
    from utils.binance_rate_limiter import (
        RedisBinanceRateLimiter,
        is_banned,
        set_ban,
    )
    from config import ENABLE_NORMALIZATION
    # import after path injection
    from utils.interrupt_lock import exit_if_already_running
    from utils.healthbeat import start_heartbeat, report_exit
    from utils.redis_hardening import create_hardened_redis_client
    from utils.websocket_limits import WebSocketLimiter, WebSocketLimitConfig
    # Import Telegram alerts for service notifications
    try:
        from telegram_alerts import TelegramNotifier
        TELEGRAM_AVAILABLE = True
    except ImportError:
        TELEGRAM_AVAILABLE = False
        TelegramNotifier = None
except ImportError as e:
    raise ImportError(f"Path injection failed, cannot import config/utils: {e}")

# Initialize data normalizer for schema standardization
normalizer = DataNormalizer()

# Fail-fast Redis health check - must be reachable before starting ingestor
try:
    from tools.health import assert_redis_up
    assert_redis_up()
except ImportError:
    print("[WARNING] Redis health check not available, proceeding...")
except SystemExit:
    raise  # Re-raise the Redis failure message

# Latency monitoring and WebSocket configuration
WEBSOCKET_ENABLED = os.getenv("BINANCE_WEBSOCKET", "1") == "1"
LATENCY_THRESHOLD_MS = int(os.getenv("LATENCY_THRESHOLD_MS", "1000"))  # Alert if >1s
# Use bounded dict to prevent memory leak - limit to 1000 entries
from collections import OrderedDict
class BoundedDict(OrderedDict):
    def __init__(self, maxsize=1000):
        super().__init__()
        self.maxsize = maxsize
    
    def __setitem__(self, key, value):
        if len(self) >= self.maxsize and key not in self:
            # Remove oldest item
            self.popitem(last=False)
        super().__setitem__(key, value)

last_data_timestamp = BoundedDict(maxsize=1000)  # Bounded to prevent memory leak
circuit_breaker_active = False
safe_mode_active = False  # Separate from circuit_breaker_active (which is used to slow REST polling)
# Updated by ANY healthy WS feed (kline and/or markPrice/bookTicker). Used for freeze detection.
last_ws_any_timestamp_ms = 0

logger = get_logger("live_binance")

MAX_WS_STREAMS = int(os.getenv("BINANCE_MAX_STREAMS", "1024"))
MAX_WS_CONNECTIONS = int(os.getenv("BINANCE_MAX_CONNECTIONS", "300"))
WS_CONNECTION_WINDOW_SECONDS = int(os.getenv("BINANCE_WS_CONNECTION_WINDOW_SECONDS", "300"))

_ws_limit_config = WebSocketLimitConfig(
    max_streams=MAX_WS_STREAMS,
    max_connections=MAX_WS_CONNECTIONS,
    window_seconds=WS_CONNECTION_WINDOW_SECONDS,
)
WS_LIMITER = WebSocketLimiter(_ws_limit_config, logger=logger)

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
        # Try synchronous fallback using the globally imported socket module
        try:
            result = socket.gethostbyname(host)
            logger.info(f"[preflight] Sync DNS OK for {host}: {result}")
            return True
        except Exception as sync_error:
            logger.error(f"[preflight] Sync DNS also failed for {host}: {sync_error}")
            return False

async def create_hardened_session():
    """Create aiohttp session with system DNS resolver (no aiodns/pycares)"""
    force_system = os.getenv("AIOHTTP_FORCE_SYSTEM_RESOLVER", "1") == "1"
    
    if force_system:
        # Force system resolver to avoid aiodns/pycares issues on Windows
        dns_resolver = resolver.DefaultResolver()
        connector = TCPConnector(
            resolver=dns_resolver,
            ssl=False,  # binance WS works without forcing ssl=True
            use_dns_cache=True,
            ttl_dns_cache=60,
            keepalive_timeout=30,
            enable_cleanup_closed=True,
            family=socket.AF_INET  # prefer IPv4 on Windows
        )
    else:
        # Legacy fallback path
        try:
            from aiohttp.resolver import AsyncResolver
            dns_resolver = AsyncResolver()  # uses aiodns if available
        except Exception:
            dns_resolver = None  # fallback to default resolver
            
        connector = TCPConnector(
            resolver=dns_resolver,
            ssl=False,
            use_dns_cache=True,
            ttl_dns_cache=60,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
    
    return aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(
            total=20, 
            connect=10, 
            sock_read=20
        )
    )

async def ws_connect_with_retry(session, url, max_retries=8):
    """Connect to WebSocket with exponential backoff retry"""
    delay = 1.0
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Connecting to WebSocket: {url} (attempt {attempt + 1})")
            await WS_LIMITER.acquire_async()
            # Use ClientWSTimeout for modern aiohttp, fallback for older versions
            try:
                from aiohttp import ClientWSTimeout
                ws_timeout = ClientWSTimeout(ws_close=10.0)
                ws = await session.ws_connect(
                    url, 
                    heartbeat=30, 
                    autoping=True,
                    timeout=ws_timeout
                )
            except (TypeError, ImportError):
                # older aiohttp fallback
                ws = await session.ws_connect(
                    url, 
                    heartbeat=30, 
                    autoping=True,
                    timeout=10.0
                )
            logger.info("WebSocket connected successfully")
            return ws
            
        except (aiohttp.ClientConnectorError, OSError, asyncio.TimeoutError) as e:
            logger.warning(f"WebSocket connect failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
                delay = min(delay * 1.8, 15)  # Exponential backoff, capped at 15s
            else:
                raise RuntimeError(f"WebSocket connect retries exhausted after {max_retries} attempts")
    
    raise RuntimeError("WebSocket connection failed")

# Optional duplication control (set env var to '1' to disable specific fetches if CoinAnk provides them)
DISABLE_OI = os.getenv("DISABLE_BINANCE_OI", "0") == "1"
DISABLE_FUNDING = os.getenv("DISABLE_BINANCE_FUNDING", "0") == "1"
DISABLE_OHLCV = os.getenv("DISABLE_BINANCE_OHLCV", "0") == "1"  # keep false normally (CoinAnk not primary OHLCV source)
DISABLE_PREMIUM_INDEX = os.getenv("DISABLE_BINANCE_PREMIUM", "0") == "1"  # includes mark/index price + basis
ENABLE_MARKPRICE_WS = os.getenv("ENABLE_BINANCE_MARKPRICE_WS", "1") == "1"  # futures markPrice@1s stream
ENABLE_BOOKTICKER_WS = os.getenv("ENABLE_BINANCE_BOOKTICKER_WS", "1") == "1"  # futures bookTicker stream (best bid/ask)
ENABLE_AGGTRADES_WS = os.getenv("ENABLE_BINANCE_AGGTRADES_WS", "1") == "1"  # futures aggTrades stream (real executed flow)

# CoinAPI V1 OHLCV fallback settings
# If CoinAPI V1 is providing OHLCV, we can skip Binance REST OHLCV to save rate limits
COINAPI_OHLCV_ENABLED = os.getenv("COINAPI_OHLCV_ENABLED", "true").lower() in ("true", "1", "yes")
COINAPI_OHLCV_STALE_THRESHOLD_SEC = int(os.getenv("COINAPI_OHLCV_STALE_THRESHOLD_SEC", "120"))  # 2 min stale = fallback to Binance


def _check_coinapi_ohlcv_healthy(redis_client, log_stale: bool = False) -> bool:
    """
    Check if CoinAPI V1 OHLCV feed is healthy.
    Returns True if CoinAPI is providing fresh OHLCV data.
    Returns False if stale/disconnected (Binance should take over).
    
    Health check keys:
    - metrics:coinapi:v1:connected (0/1)
    - metrics:coinapi:v1:last_ohlcv_ts (unix timestamp)
    
    Args:
        redis_client: Redis connection
        log_stale: If True, log a warning when stale (set False when calling in a loop)
    """
    if not COINAPI_OHLCV_ENABLED:
        return False  # CoinAPI OHLCV not enabled, use Binance
    
    if not redis_client:
        return False
    
    try:
        # Check if V1 is connected
        connected = redis_client.get("metrics:coinapi:v1:connected")
        if not connected or connected != "1":
            return False
        
        # Check staleness
        last_ohlcv_ts = redis_client.get("metrics:coinapi:v1:last_ohlcv_ts")
        if not last_ohlcv_ts:
            return False
        
        staleness = time.time() - float(last_ohlcv_ts)
        if staleness > COINAPI_OHLCV_STALE_THRESHOLD_SEC:
            if log_stale:
                logger.warning(
                    f"[COINAPI_FALLBACK] CoinAPI V1 OHLCV stale ({staleness:.1f}s > {COINAPI_OHLCV_STALE_THRESHOLD_SEC}s) "
                    f"- using Binance OHLCV"
                )
            return False
        
        return True
        
    except Exception as e:
        logger.debug(f"[COINAPI_FALLBACK] Health check error: {e}")
        return False


# Optional orderbook enable (Binance Futures USDT-M). Uses REST snapshot + WS diff stream.
ENABLE_ORDERBOOK = os.getenv("ENABLE_BINANCE_ORDERBOOK", "1") == "1"
# Market selection for orderbook: 'USDT-M' (futures USDT margined) or 'COIN-M' (coin margined)
# Default comes from config.py (COIN-M) unless overridden by env
ORDERBOOK_MARKET = os.getenv("ORDERBOOK_MARKET", (_CONF_OB_MARKET or "USDT-M")).upper()  # 'USDT-M' or 'COIN-M'
ORDERBOOK_LEVELS = int(os.getenv("ORDERBOOK_LEVELS", "50"))  # store top N levels to Redis
ORDERBOOK_REST_LIMIT = min(max(ORDERBOOK_LEVELS * 2, 100), 500)  # 100/200/500 allowed; weight increases with limit
ORDERBOOK_STREAM_INTERVAL = os.getenv("ORDERBOOK_STREAM_INTERVAL", "100ms")  # 100ms or 250ms

# Internal: orderbook state container per symbol
_ob_threads_started = False

def _to_binance_sym(sym: str) -> str:
    """Convert symbols like 'BTC/USDT' -> 'BTCUSDT'."""
    if not sym:
        return sym
    s = sym.replace('/', '').replace('-', '')
    return s.upper()

class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.last_update_id = None
        self.bids = {}  # price->qty
        self.asks = {}
        self.lock = threading.Lock()

    def apply_snapshot(self, last_update_id: int, bids: list, asks: list):
        with self.lock:
            self.last_update_id = last_update_id
            self.bids.clear()
            self.asks.clear()
            # Store top 200 levels from snapshot (good balance for analysis)
            for p, q in bids[:200]:
                qf = float(q)
                if qf > 0:
                    self.bids[float(p)] = qf
            for p, q in asks[:200]:
                qf = float(q)
                if qf > 0:
                    self.asks[float(p)] = qf

    def apply_diffs(self, u_first: int, u_last: int, bid_diffs: list, ask_diffs: list) -> bool:
        with self.lock:
            if self.last_update_id is None:
                return False
            # Ensure sequence continuity: expect u_first <= last_update_id+1 <= u_last for first event after snapshot
            if u_last < self.last_update_id:
                return False  # outdated
            # Apply bids
            for p, q in bid_diffs:
                price = float(p); qty = float(q)
                if qty == 0:
                    self.bids.pop(price, None)
                else:
                    self.bids[price] = qty
            # Apply asks
            for p, q in ask_diffs:
                price = float(p); qty = float(q)
                if qty == 0:
                    self.asks.pop(price, None)
                else:
                    self.asks[price] = qty
            
            # Trim orderbook to prevent unbounded growth
            # MEMORY FIX: Trim more aggressively at 150 entries instead of 200
            # to prevent accumulation during high-frequency updates
            if len(self.bids) > 150:
                sorted_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:150]
                self.bids = dict(sorted_bids)
            if len(self.asks) > 150:
                sorted_asks = sorted(self.asks.items(), key=lambda x: x[0])[:150]
                self.asks = dict(sorted_asks)
            
            self.last_update_id = u_last
            return True

    def topN(self, n: int):
        with self.lock:
            best_bids = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)[:n]
            best_asks = sorted(self.asks.items(), key=lambda x: x[0])[:n]
        return best_bids, best_asks

    def summary(self, n: int):
        bids, asks = self.topN(n)
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        spread = (best_ask - best_bid) if (best_bid and best_ask) else None
        bid_notional = sum(p * q for p, q in bids)
        ask_notional = sum(p * q for p, q in asks)
        imb = None
        tot = bid_notional + ask_notional
        if tot > 0:
            imb = (bid_notional - ask_notional) / tot
        return {
            'bid': best_bid,
            'ask': best_ask,
            'spread': spread,
            'levels': n,
            'bid_notional': bid_notional,
            'ask_notional': ask_notional,
            'imbalance': imb,
            'u': self.last_update_id
        }


def _compute_depth_bps_windows_from_top(
    top_bids: list,
    top_asks: list,
    mid_px: float,
    windows_bps: list,
) -> dict:
    """Compute notional depth within +/- N bps of mid from top-of-book lists."""
    out = {}
    if not mid_px or mid_px <= 0:
        for bps in windows_bps:
            out[f"depth_bps_{bps}_bid_usd"] = 0.0
            out[f"depth_bps_{bps}_ask_usd"] = 0.0
            out[f"depth_bps_{bps}_total_usd"] = 0.0
            out[f"depth_bps_{bps}_levels_used"] = 0
        return out

    for bps in windows_bps:
        thr_bid = float(mid_px) * (1.0 - (float(bps) / 10000.0))
        thr_ask = float(mid_px) * (1.0 + (float(bps) / 10000.0))
        bid_usd = 0.0
        ask_usd = 0.0
        levels = 0
        for p, q in (top_bids or []):
            try:
                px = float(p)
                qty = float(q)
            except Exception:
                continue
            if px <= 0 or qty <= 0:
                continue
            if px < thr_bid:
                break
            bid_usd += px * qty
            levels += 1
        for p, q in (top_asks or []):
            try:
                px = float(p)
                qty = float(q)
            except Exception:
                continue
            if px <= 0 or qty <= 0:
                continue
            if px > thr_ask:
                break
            ask_usd += px * qty
            levels += 1
        out[f"depth_bps_{bps}_bid_usd"] = float(bid_usd)
        out[f"depth_bps_{bps}_ask_usd"] = float(ask_usd)
        out[f"depth_bps_{bps}_total_usd"] = float(bid_usd + ask_usd)
        out[f"depth_bps_{bps}_levels_used"] = int(levels)
    return out

async def _orderbook_worker(symbols):
    """Binance Futures USDT-M order book: REST snapshot + WS diff stream (combined)
    Implements pre-snapshot buffering of WS diffs to ensure continuity from the initial snapshot.
    MEMORY LEAK FIX: Reuse aiohttp sessions across reconnections instead of creating new ones.
    """
    logger.info(f"🔄 OrderBook worker starting for {len(symbols)} symbols...")
    try:
        import aiohttp  # type: ignore
        import requests  # type: ignore
        logger.info("✅ aiohttp and requests modules imported successfully")
    except Exception as e:
        logger.error(f"❌ aiohttp/requests not installed; orderbook stream disabled: {e}")
        return

    r = get_redis()
    # Build symbol lists for WS/REST depending on market, and a map to config symbols for Redis keys
    cfg_syms = [s for s in symbols]
    if ORDERBOOK_MARKET == 'COIN-M':
        # Convert e.g. BTCUSDT -> BTCUSD_PERP
        norm_symbols = [f"{s.replace('USDT','')}USD_PERP" for s in cfg_syms]
        ws_base = "wss://dstream.binance.com/stream?streams="
        rest_url = "https://dapi.binance.com/dapi/v1/depth"
    else:
        # Default USDT-M (centralize via binance_utils)
        norm_symbols = [_to_binance_sym(s) for s in cfg_syms]
        try:
            from trading.binance_utils import get_binance_futures_creds  # type: ignore
            creds = get_binance_futures_creds()
            # When using connector WS, stream prefix is typically fstream for live; non-live WS variants may differ.
            # Prefer env overrides from creds; otherwise choose based on configured mode.
            ws_base = (creds.fut_ws_base.replace('/ws','/stream?streams=') if creds.fut_ws_base.endswith('/ws') else creds.fut_ws_base)
            if not ws_base.endswith('streams='):
                # Normalize to stream aggregator endpoint
                if ws_base.endswith('/'):
                    ws_base = ws_base + 'stream?streams='
                else:
                    ws_base = ws_base + '/stream?streams='
            rest_url = f"{creds.fut_rest_base}/fapi/v1/depth"
        except Exception:
            # Fallback to known defaults
            ws_base = "wss://fstream.binance.com/stream?streams="
            rest_url = "https://fapi.binance.com/fapi/v1/depth"
    # Map stream symbol -> config symbol for keying
    stream_to_cfg = {ns: cfg for ns, cfg in zip(norm_symbols, cfg_syms)}
    books = {ns: OrderBook(ns) for ns in norm_symbols}
    have_snapshot = {ns: False for ns in norm_symbols}
    # Use bounded deques for per-symbol buffers to guarantee an upper memory bound
    buffers = {ns: deque(maxlen=2000) for ns in norm_symbols}  # buffer per symbol before snapshot arrives

    streams = '/'.join([f"{ns.lower()}@depth@{ORDERBOOK_STREAM_INTERVAL}" for ns in norm_symbols])
    ws_url = f"{ws_base}{streams}"

    WS_LIMITER.validate_stream_count(len(norm_symbols), context="orderbook_depth")

    # MEMORY LEAK FIX: Create sessions ONCE outside reconnection loop
    session = None
    http = None
    
    # Reconnection loop with session reuse
    reconnect_delay = 5
    max_reconnect_delay = 300
    
    while True:
        ws = None
        try:
            # Create sessions only if they don't exist (first run or after cleanup)
            if session is None:
                session = await create_hardened_session()
                logger.info("✅ Created main WebSocket session for orderbook")
            
            if http is None:
                http = await create_hardened_session()
                logger.info("✅ Created HTTP session for orderbook snapshots")
            
            # DNS preflight check based on market type
            if ORDERBOOK_MARKET == 'COIN-M':
                if not await _dns_preflight("dstream.binance.com"):
                    logger.error("DNS preflight failed for dstream.binance.com")
                    await asyncio.sleep(reconnect_delay)
                    continue
            else:
                if not await _dns_preflight("fstream.binance.com"):
                    logger.error("DNS preflight failed for fstream.binance.com")
                    await asyncio.sleep(reconnect_delay)
                    continue
            
            # Connect WebSocket (reusing session)
            ws = await ws_connect_with_retry(session, ws_url)
            
            logger.info(f"✅ Connected orderbook WebSocket for {len(symbols)} symbols")
            reconnect_delay = 5  # Reset on successful connection

            # Fetch initial REST snapshots after WS connect, then replay buffered diffs
            # Only fetch snapshots on first connection or after reconnection
            REST_URL = rest_url
            for ns in norm_symbols:
                if have_snapshot[ns]:
                    continue  # Skip if we already have a valid snapshot
                    
                attempts = 0
                while attempts < 3 and not have_snapshot[ns]:
                    attempts += 1
                    try:
                        async with http.get(REST_URL, params={"symbol": ns, "limit": ORDERBOOK_REST_LIMIT}, timeout=10) as resp:
                            if resp.status != 200:
                                txt = None
                                try:
                                    txt = await resp.text()
                                except Exception:
                                    pass
                                logger.warning(f"orderbook snapshot status {resp.status} for {ns} body={txt}")
                                await asyncio.sleep(0.5)
                                continue
                            data = await resp.json()
                            last_update_id = data.get('lastUpdateId')
                            if last_update_id is None:
                                logger.warning(f"orderbook snapshot for {ns}: lastUpdateId is None, skipping")
                                await asyncio.sleep(0.5)
                                continue
                            last_u = int(last_update_id)
                            bids = data.get('bids') or []
                            asks = data.get('asks') or []
                            books[ns].apply_snapshot(last_u, bids, asks)
                            have_snapshot[ns] = True
                            # Set initial heartbeat and top snapshot immediately after snapshot
                            try:
                                if r:
                                    ts0 = int(time.time() * 1000)
                                    cfg = stream_to_cfg.get(ns, ns)
                                    summ0 = books[ns].summary(ORDERBOOK_LEVELS)
                                    top_bids0, top_asks0 = books[ns].topN(ORDERBOOK_LEVELS)
                                    # Enrich orderbook:top with best sizes + top5 sums (used by spoof/MM modules)
                                    try:
                                        best_bid_sz0 = float(top_bids0[0][1]) if top_bids0 else 0.0
                                        best_ask_sz0 = float(top_asks0[0][1]) if top_asks0 else 0.0
                                        book_bid_sum_50 = float(sum(float(q) for _, q in (top_bids0[:5] or [])))
                                        book_ask_sum_50 = float(sum(float(q) for _, q in (top_asks0[:5] or [])))
                                        bid0 = float(summ0.get("bid") or 0)
                                        ask0 = float(summ0.get("ask") or 0)
                                        mid0 = (bid0 + ask0) / 2 if bid0 > 0 and ask0 > 0 else 0.0
                                        spread_bps0 = ((ask0 - bid0) / mid0 * 10000) if mid0 > 0 else 0.0
                                    except Exception:
                                        best_bid_sz0 = best_ask_sz0 = book_bid_sum_50 = book_ask_sum_50 = mid0 = spread_bps0 = 0.0

                                    bid_notional0 = float(summ0.get("bid_notional") or 0.0)
                                    ask_notional0 = float(summ0.get("ask_notional") or 0.0)
                                    total_depth0 = bid_notional0 + ask_notional0

                                    # Normalized depth hash for orchestrator fallback/picker
                                    try:
                                        depth_windows0 = _compute_depth_bps_windows_from_top(top_bids0, top_asks0, mid0, [10, 25])
                                        r.hset(
                                            f"ob:binance:depth:{cfg}",
                                            mapping={
                                                "ts_ms": str(ts0),
                                                "updated_ts_ms": str(ts0),
                                                "symbol": cfg,
                                                "binance_symbol": ns,
                                                "source": "binance_ws",
                                                "exchange_id": "BINANCE",
                                                "best_bid_px": str(bid0),
                                                "best_ask_px": str(ask0),
                                                "best_bid_qty": str(best_bid_sz0),
                                                "best_ask_qty": str(best_ask_sz0),
                                                "mid_px": str(mid0),
                                                "spread_bps": str(spread_bps0),
                                                **{k: str(v) for k, v in depth_windows0.items()},
                                            },
                                        )
                                        r.expire(f"ob:binance:depth:{cfg}", 60)
                                    except Exception:
                                        pass
                                    r.set(
                                        f"orderbook:top:{cfg}",
                                        json.dumps({
                                            **summ0,
                                            "ts": ts0,
                                            "updated_ts_ms": ts0,
                                            "binance_symbol": ns,
                                            "source": "binance_orderbook",
                                            "best_bid_sz": best_bid_sz0,
                                            "best_ask_sz": best_ask_sz0,
                                            "book_bid_sum_5": book_bid_sum_50,
                                            "book_ask_sum_5": book_ask_sum_50,
                                            "mid_px": mid0,
                                            "spread_bps": spread_bps0,
                                            "bid_depth": bid_notional0,
                                            "ask_depth": ask_notional0,
                                            "total_depth": total_depth0,
                                        })
                                    )
                                    r.set(f"orderbook:bids:{cfg}", json.dumps(top_bids0))
                                    r.set(f"orderbook:asks:{cfg}", json.dumps(top_asks0))
                                    r.set(f"heartbeat:OrderBook:{cfg}", ts0)
                            except Exception:
                                pass
                            # Replay buffered events for this symbol in arrival order
                            if buffers[ns]:
                                for ev in buffers[ns]:
                                    if ev.get('U') is None or ev.get('u') is None:
                                        continue
                                    U = int(ev['U']); u = int(ev['u'])
                                    if u <= last_u:
                                        continue
                                    if U <= last_u + 1 <= u:
                                        books[ns].apply_diffs(U, u, ev['b'], ev['a'])
                                    elif U > last_u + 1:
                                        # Gap detected; force re-snapshot next cycle
                                        have_snapshot[ns] = False
                                        break
                                buffers[ns].clear()
                    except Exception as e:
                        logger.warning(f"orderbook snapshot error {ns}: {type(e).__name__}: {e}")
                        await asyncio.sleep(0.5)
        except Exception:
            logger.error("orderbook snapshot batch failed:\n" + traceback.format_exc())

            # WS message loop
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.receive(), timeout=65)
                    except asyncio.TimeoutError:
                        try:
                            await ws.ping()
                        except Exception:
                            break
                        continue
                    except Exception as e:
                        logger.error(f"orderbook ws recv error: {e}")
                        break

                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    try:
                        payload = json.loads(msg.data)
                    except Exception:
                        continue
                    ev = payload.get('data') if isinstance(payload, dict) else None
                    if not isinstance(ev, dict):
                        continue
                    sym = ev.get('s')  # Binance symbol (e.g., BTCUSDT or BTCUSD_PERP)
                    U = ev.get('U')
                    u = ev.get('u')
                    bids = ev.get('b') or []
                    asks = ev.get('a') or []
                    if not sym or U is None or u is None:
                        continue

                    ob = books.get(sym)
                    if not ob:
                        continue

                    if not have_snapshot.get(sym):
                        # Buffer until snapshot arrives
                        if U is None or u is None:
                            continue
                        buf = buffers[sym]
                        # append will automatically drop oldest entries when maxlen exceeded
                        buf.append({'U': int(U), 'u': int(u), 'b': bids, 'a': asks})
                        continue

                    if ob.last_update_id is None:
                        continue
                    if U is None or u is None:
                        continue
                    last_id = ob.last_update_id
                    U = int(U); u = int(u)
                    if u <= last_id:
                        continue  # outdated
                    if U > last_id + 1:
                        # Missed an event; trigger re-snapshot
                        have_snapshot[sym] = False
                        buffers[sym].clear()
                        continue

                    ok = ob.apply_diffs(U, u, bids, asks)
                    if not ok:
                        continue

                    # Persist summary and top levels under CONFIG symbol keys
                    if r:
                        try:
                            ts = int(time.time() * 1000)
                            summ = ob.summary(ORDERBOOK_LEVELS)
                            cfg = stream_to_cfg.get(sym, sym)
                            top_bids, top_asks = ob.topN(ORDERBOOK_LEVELS)
                            # Enrich orderbook:top with best sizes + top5 sums (used by spoof/MM modules)
                            try:
                                best_bid_sz = float(top_bids[0][1]) if top_bids else 0.0
                                best_ask_sz = float(top_asks[0][1]) if top_asks else 0.0
                                book_bid_sum_5 = float(sum(float(q) for _, q in (top_bids[:5] or [])))
                                book_ask_sum_5 = float(sum(float(q) for _, q in (top_asks[:5] or [])))
                                bid = float(summ.get("bid") or 0)
                                ask = float(summ.get("ask") or 0)
                                mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0
                                spread_bps = ((ask - bid) / mid * 10000) if mid > 0 else 0.0
                            except Exception:
                                best_bid_sz = best_ask_sz = book_bid_sum_5 = book_ask_sum_5 = mid = spread_bps = 0.0

                            bid_notional = float(summ.get("bid_notional") or 0.0)
                            ask_notional = float(summ.get("ask_notional") or 0.0)
                            total_depth = bid_notional + ask_notional

                            # Normalized depth hash for orchestrator fallback/picker
                            try:
                                depth_windows = _compute_depth_bps_windows_from_top(top_bids, top_asks, mid, [10, 25])
                                r.hset(
                                    f"ob:binance:depth:{cfg}",
                                    mapping={
                                        "ts_ms": str(ts),
                                        "updated_ts_ms": str(ts),
                                        "symbol": cfg,
                                        "binance_symbol": sym,
                                        "source": "binance_ws",
                                        "exchange_id": "BINANCE",
                                        "best_bid_px": str(bid),
                                        "best_ask_px": str(ask),
                                        "best_bid_qty": str(best_bid_sz),
                                        "best_ask_qty": str(best_ask_sz),
                                        "mid_px": str(mid),
                                        "spread_bps": str(spread_bps),
                                        **{k: str(v) for k, v in depth_windows.items()},
                                    },
                                )
                                r.expire(f"ob:binance:depth:{cfg}", 60)
                            except Exception:
                                pass
                            r.set(
                                f"orderbook:top:{cfg}",
                                json.dumps({
                                    **summ,
                                    "ts": ts,
                                    "updated_ts_ms": ts,
                                    "binance_symbol": sym,
                                    "source": "binance_orderbook",
                                    "best_bid_sz": best_bid_sz,
                                    "best_ask_sz": best_ask_sz,
                                    "book_bid_sum_5": book_bid_sum_5,
                                    "book_ask_sum_5": book_ask_sum_5,
                                    "mid_px": mid,
                                    "spread_bps": spread_bps,
                                    "bid_depth": bid_notional,
                                    "ask_depth": ask_notional,
                                    "total_depth": total_depth,
                                })
                            )
                            r.set(f"orderbook:bids:{cfg}", json.dumps(top_bids))
                            r.set(f"orderbook:asks:{cfg}", json.dumps(top_asks))
                            r.set(f"heartbeat:OrderBook:{cfg}", ts)
                        except Exception:
                            pass
                        
            except Exception as e:
                logger.error(f"❌ Orderbook error: {e}")
            finally:
                # Close WebSocket connection but KEEP sessions for reuse
                if ws:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                ws = None
                
            # Exponential backoff for reconnection
            logger.info(f"🔄 Orderbook reconnecting in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

def _start_orderbook_thread():
    global _ob_threads_started
    if _ob_threads_started:
        logger.info("📊 OrderBook thread already started, skipping")
        return
    if not ENABLE_ORDERBOOK:
        logger.warning("⚠️ OrderBook is DISABLED (ENABLE_BINANCE_ORDERBOOK=0)")
        return
    
    _ob_threads_started = True
    logger.info(f"🚀 Starting OrderBook thread for {len(_ORDERBOOK_SYMBOLS)} symbols: {_ORDERBOOK_SYMBOLS}")
    
    # Start a lightweight thread running its own event loop
    symbols = [s for s in _ORDERBOOK_SYMBOLS]
    def _runner():
        try:
            logger.info(f"📡 OrderBook thread runner starting for {symbols}")
            asyncio.run(_orderbook_worker(symbols))
        except Exception as e:
            logger.error(f"❌ OrderBook thread died: {e}\n" + traceback.format_exc())
    t = threading.Thread(target=_runner, name="binance-orderbook", daemon=True)
    t.start()
    logger.info(f"✅ OrderBook thread started: {t.name} (daemon={t.daemon})")

# --- WebSocket Low-Latency Implementation ---

async def _markprice_bookticker_worker(symbols, redis_client):
    """Subscribe to markPrice@1s and bookTicker for configured symbols (futures)."""
    global last_ws_any_timestamp_ms
    if not symbols:
        return
    norm_syms = [_to_binance_sym(s) for s in symbols]
    streams = []
    if ENABLE_MARKPRICE_WS:
        streams += [f"{s.lower()}@markPrice@1s" for s in norm_syms]
    if ENABLE_BOOKTICKER_WS:
        streams += [f"{s.lower()}@bookTicker" for s in norm_syms]
    if not streams:
        return

    WS_LIMITER.validate_stream_count(len(streams), context="markprice_bookticker")
    stream_url = "wss://fstream.binance.com/stream?streams=" + "/".join(streams)
    logger.info(f"📡 Starting markPrice/bookTicker WS for {len(norm_syms)} symbols")

    reconnect_delay = 5
    max_reconnect_delay = 120
    while True:
        try:
            await WS_LIMITER.acquire_async()
            async with websockets.connect(stream_url, ping_interval=20, ping_timeout=60) as ws:
                logger.info("✅ MarkPrice/BookTicker WS connected")
                reconnect_delay = 5
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                    except Exception:
                        continue
                    payload = data.get('data') if isinstance(data, dict) else None
                    if not isinstance(payload, dict):
                        continue
                    stream = payload.get('s') or payload.get('symbol')
                    if not stream:
                        continue
                    sym = stream
                    ts_ms = int(payload.get('E')) if isinstance(payload.get('E'), (int, float)) else int(time.time() * 1000)
                    # Track last-known WS liveness (receipt-time; do not rely on exchange event timestamps)
                    last_ws_any_timestamp_ms = int(time.time() * 1000)

                    # markPrice event
                    if payload.get('e') == 'markPriceUpdate' or 'p' in payload or 'P' in payload:
                        try:
                            mark_val = None
                            if 'p' in payload:
                                mark_val = float(payload.get('p'))
                            elif 'P' in payload:
                                mark_val = float(payload.get('P'))
                            idx_val = float(payload.get('i')) if payload.get('i') is not None else None
                            basis_pct = (mark_val - idx_val) / idx_val if mark_val is not None and idx_val not in (None, 0) else None
                            pi_payload = {
                                'ts_ms': ts_ms,
                                'symbol': sym,
                                'exchange': 'Binance',
                                'mark_price': mark_val,
                                'index_price': idx_val,
                                'basis_pct': basis_pct,
                                'last_funding_rate': float(payload.get('r')) if payload.get('r') is not None else None,
                                'next_funding_time': int(payload.get('T')) if isinstance(payload.get('T'), (int, float)) else None
                            }
                            redis_client.set(f"latest:binance:mark_price:{sym}", json.dumps(pi_payload))
                            redis_client.set(f"latest:binance:index_price:{sym}", json.dumps(pi_payload))
                            redis_client.set(f"latest:binance:premium_index:{sym}", json.dumps(pi_payload))
                        except Exception:
                            pass

                    # bookTicker event
                    if payload.get('u') is not None and payload.get('b') is not None and payload.get('a') is not None:
                        try:
                            bid = float(payload.get('b'))
                            ask = float(payload.get('a'))
                            spread = ask - bid if bid and ask else 0.0
                            # bookTicker provides best bid/ask + quantities (B/A).
                            summary = {
                                'bid': bid,
                                'ask': ask,
                                'spread': spread,
                                'imbalance': payload.get('B') and payload.get('A') and (float(payload.get('B')) - float(payload.get('A'))) / (float(payload.get('B')) + float(payload.get('A')) + 1e-9),
                                'ts': ts_ms,
                                'updated_ts_ms': ts_ms,
                                'binance_symbol': sym,
                                'source': 'binance_bookticker',
                                'best_bid_sz': float(payload.get('B')) if payload.get('B') is not None else 0.0,
                                'best_ask_sz': float(payload.get('A')) if payload.get('A') is not None else 0.0,
                                'mid_px': (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0,
                                'spread_bps': ((ask - bid) / ((bid + ask) / 2) * 10000) if bid > 0 and ask > 0 else 0.0,
                            }
                            # Preserve depth fields from existing orderbook snapshot (if available)
                            try:
                                existing_raw = redis_client.get(f"orderbook:top:{sym}")
                                if existing_raw:
                                    existing = json.loads(existing_raw)
                                    for k in ("bid_depth", "ask_depth", "total_depth", "bid_notional", "ask_notional"):
                                        if existing.get(k) is not None:
                                            summary[k] = existing.get(k)
                                    if "total_depth" not in summary:
                                        bid_depth = float(summary.get("bid_depth") or 0.0)
                                        ask_depth = float(summary.get("ask_depth") or 0.0)
                                        summary["total_depth"] = bid_depth + ask_depth
                            except Exception:
                                pass
                            redis_client.set(f"orderbook:top:{sym}", json.dumps(summary))
                            redis_client.set(f"heartbeat:OrderBook:{sym}", ts_ms)
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"MarkPrice/BookTicker WS error: {e}; reconnecting in {reconnect_delay}s")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

# ═══════════════════════════════════════════════════════════════════════
# BINANCE aggTrades WebSocket — Real Executed Flow (Apr 2026)
#
# This is the CRITICAL missing piece for spoof detection.
# The depth chart (orderbook) shows INTENT, but aggTrades shows what
# actually EXECUTED. When depth says "buy pressure" but tape shows
# selling, that's the classic spoof pattern.
#
# Writes: msnap:binance_tape:{SYMBOL} Redis hash with rolling
# buy/sell notional in 1s, 5s, 30s windows + CVD + tape_imbalance.
# ═══════════════════════════════════════════════════════════════════════

# Per-symbol tape accumulator (module-level, thread-safe via GIL)
_TAPE_ACCUM = {}  # symbol -> {"buckets": deque, "cvd": float}
_TAPE_ACCUM_MAX_BUCKETS = 60  # Keep 60 seconds of 1-second buckets


def _get_tape_accum(symbol):
    """Get or create tape accumulator for a symbol."""
    from collections import deque
    if symbol not in _TAPE_ACCUM:
        _TAPE_ACCUM[symbol] = {
            "buckets": deque(maxlen=_TAPE_ACCUM_MAX_BUCKETS),
            "cvd": 0.0,
        }
    return _TAPE_ACCUM[symbol]


def _flush_tape_to_redis(symbol, redis_client):
    """Compute rolling taker buy/sell volumes and write to Redis."""
    accum = _TAPE_ACCUM.get(symbol)
    if not accum or not accum["buckets"]:
        return
    buckets = list(accum["buckets"])
    now_sec = int(time.time())

    buy_1s = sell_1s = buy_5s = sell_5s = buy_30s = sell_30s = 0.0
    count_1s = count_5s = count_30s = 0
    for b in reversed(buckets):
        age = now_sec - b["sec"]
        if age > 30:
            break
        buy_30s += b["buy_notional"]
        sell_30s += b["sell_notional"]
        count_30s += b["count"]
        if age <= 5:
            buy_5s += b["buy_notional"]
            sell_5s += b["sell_notional"]
            count_5s += b["count"]
        if age <= 1:
            buy_1s += b["buy_notional"]
            sell_1s += b["sell_notional"]
            count_1s += b["count"]

    total_1s = buy_1s + sell_1s + 1e-9
    total_5s = buy_5s + sell_5s + 1e-9
    total_30s = buy_30s + sell_30s + 1e-9

    payload = {
        "ts_ms": str(int(time.time() * 1000)),
        "symbol": symbol,
        # 1-second window
        "tape_buy_1s": str(round(buy_1s, 2)),
        "tape_sell_1s": str(round(sell_1s, 2)),
        "tape_total_1s": str(round(buy_1s + sell_1s, 2)),
        "tape_imbalance_1s": str(round((buy_1s - sell_1s) / total_1s, 6)),
        "tape_count_1s": str(count_1s),
        # 5-second window
        "tape_buy_5s": str(round(buy_5s, 2)),
        "tape_sell_5s": str(round(sell_5s, 2)),
        "tape_total_5s": str(round(buy_5s + sell_5s, 2)),
        "tape_imbalance_5s": str(round((buy_5s - sell_5s) / total_5s, 6)),
        "tape_count_5s": str(count_5s),
        # 30-second window
        "tape_buy_30s": str(round(buy_30s, 2)),
        "tape_sell_30s": str(round(sell_30s, 2)),
        "tape_total_30s": str(round(buy_30s + sell_30s, 2)),
        "tape_imbalance_30s": str(round((buy_30s - sell_30s) / total_30s, 6)),
        "tape_count_30s": str(count_30s),
        # CVD (cumulative volume delta since start)
        "tape_cvd": str(round(accum["cvd"], 2)),
        "source": "binance_aggtrades",
    }
    try:
        redis_client.hset(f"msnap:binance_tape:{symbol}", mapping=payload)
        redis_client.expire(f"msnap:binance_tape:{symbol}", 120)
    except Exception as e:
        logger.debug(f"TAPE_REDIS_WRITE_ERR | {symbol} | {e}")


async def _aggtrades_worker(symbols, redis_client):
    """Subscribe to aggTrade streams for real-time executed trade flow."""
    global last_ws_any_timestamp_ms
    if not symbols:
        return
    norm_syms = [_to_binance_sym(s) for s in symbols]
    streams = [f"{s.lower()}@aggTrade" for s in norm_syms]
    if not streams:
        return

    WS_LIMITER.validate_stream_count(len(streams), context="aggtrades")
    stream_url = "wss://fstream.binance.com/stream?streams=" + "/".join(streams)
    logger.info(f"📊 Starting aggTrades WS for {len(norm_syms)} symbols")

    reconnect_delay = 5
    max_reconnect_delay = 120
    last_flush = {}  # symbol -> last flush time

    while True:
        try:
            await WS_LIMITER.acquire_async()
            async with websockets.connect(stream_url, ping_interval=20, ping_timeout=60) as ws:
                logger.info("✅ aggTrades WS connected")
                reconnect_delay = 5
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                    except Exception:
                        continue
                    payload = data.get('data') if isinstance(data, dict) else None
                    if not isinstance(payload, dict):
                        continue
                    if payload.get('e') != 'aggTrade':
                        continue

                    sym = payload.get('s', '')
                    if not sym:
                        continue

                    # Track WS liveness
                    last_ws_any_timestamp_ms = int(time.time() * 1000)

                    try:
                        price = float(payload.get('p', 0))
                        qty = float(payload.get('q', 0))
                        is_buyer_maker = payload.get('m', False)  # True = seller is taker (sell aggression)
                        notional = price * qty

                        # Accumulate into 1-second buckets
                        accum = _get_tape_accum(sym)
                        now_sec = int(time.time())

                        # Get or create current bucket
                        if accum["buckets"] and accum["buckets"][-1]["sec"] == now_sec:
                            bucket = accum["buckets"][-1]
                        else:
                            bucket = {"sec": now_sec, "buy_notional": 0.0, "sell_notional": 0.0, "count": 0}
                            accum["buckets"].append(bucket)

                        if is_buyer_maker:
                            # Seller is taker = sell aggression
                            bucket["sell_notional"] += notional
                            accum["cvd"] -= notional
                        else:
                            # Buyer is taker = buy aggression
                            bucket["buy_notional"] += notional
                            accum["cvd"] += notional
                        bucket["count"] += 1

                        # Flush to Redis every ~1 second per symbol
                        last_sym_flush = last_flush.get(sym, 0)
                        if (now_sec - last_sym_flush) >= 1:
                            _flush_tape_to_redis(sym, redis_client)
                            last_flush[sym] = now_sec

                    except Exception as e:
                        logger.debug(f"AGGTRADE_PROCESS_ERR | {sym} | {e}")

        except Exception as e:
            logger.warning(f"aggTrades WS error: {e}; reconnecting in {reconnect_delay}s")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)


def _start_aggtrades_thread():
    """Start the aggTrades WebSocket thread for real-time tape data."""
    if not ENABLE_AGGTRADES_WS:
        logger.info("aggTrades WS disabled (set ENABLE_BINANCE_AGGTRADES_WS=1 to enable)")
        return
    def _runner():
        try:
            r = get_redis()
            asyncio.run(_aggtrades_worker(_ORDERBOOK_SYMBOLS, r))
        except Exception as e:
            logger.error(f"aggTrades thread died: {e}\n" + traceback.format_exc())
    t = threading.Thread(target=_runner, name="binance-aggtrades-tape", daemon=True)
    t.start()
    logger.info(f"✅ aggTrades tape thread started: {t.name}")


def _start_markprice_bookticker_thread():
    if not (ENABLE_MARKPRICE_WS or ENABLE_BOOKTICKER_WS):
        logger.info("MarkPrice/BookTicker WS disabled")
        return
    def _runner():
        try:
            r = get_redis()
            asyncio.run(_markprice_bookticker_worker(_ORDERBOOK_SYMBOLS, r))
        except Exception as e:
            logger.error(f"MarkPrice/BookTicker thread died: {e}\n" + traceback.format_exc())
    t = threading.Thread(target=_runner, name="binance-markprice-bookticker", daemon=True)
    t.start()
    logger.info(f"✅ MarkPrice/BookTicker thread started: {t.name}")

async def _websocket_kline_stream(symbols, timeframes, dm, redis_client):
    """
    WebSocket stream for real-time kline/OHLCV data from Binance
    Reduces latency from 2-3s REST polling to ~100ms streaming
    """
    global last_data_timestamp, circuit_breaker_active, last_ws_any_timestamp_ms
    
    # Build stream names for all symbol/timeframe combinations
    streams = []
    for symbol in symbols:
        for tf in timeframes:
            # Convert our timeframe to Binance format (1m, 5m, 15m, 1h, 4h, 1d)
            binance_tf = tf.lower()
            stream_name = f"{symbol.lower()}@kline_{binance_tf}"
            streams.append(stream_name)

    WS_LIMITER.validate_stream_count(len(streams), context="kline")
    
    # IMPORTANT: Combined streams require the `/stream?streams=` endpoint and wrap payload under `{"stream": "...", "data": {...}}`.
    stream_url = "wss://fstream.binance.com/stream?streams=" + "/".join(streams)
    
    logger.info(f"🌐 Starting WebSocket kline stream for {len(streams)} streams")
    logger.info(f"📡 WebSocket URL: {stream_url[:100]}...")
    
    reconnect_delay = 5
    max_reconnect_delay = 300
    
    websocket = None
    while True:
        try:
            await WS_LIMITER.acquire_async()
            websocket = await websockets.connect(stream_url, ping_interval=20, ping_timeout=60)
            logger.info("✅ WebSocket connected to Binance futures")
            reconnect_delay = 5  # Reset on successful connection
            circuit_breaker_active = False
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    payload = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
                    await _process_kline_message(payload, dm, redis_client)
                    
                    # Update last data timestamp for freeze detection
                    current_time = time.time() * 1000
                    sym_for_key = None
                    if isinstance(payload, dict):
                        sym_for_key = payload.get("s") or (payload.get("k") or {}).get("s")
                    stream_key = f"{sym_for_key or 'unknown'}@kline"
                    last_data_timestamp[stream_key] = current_time
                    # Any WS message indicates the overall WS subsystem is alive
                    last_ws_any_timestamp_ms = current_time
                    
                except json.JSONDecodeError:
                    logger.warning("⚠️ Invalid JSON received from WebSocket")
                except Exception as e:
                    logger.error(f"❌ Error processing WebSocket message: {e}")
                        
        except websockets.exceptions.ConnectionClosed:
            logger.warning(f"🔌 WebSocket connection closed, reconnecting in {reconnect_delay}s...")
        except Exception as e:
            logger.error(f"❌ WebSocket error: {e}")
        finally:
            # MEMORY LEAK FIX: Ensure websocket is properly closed
            if websocket is not None:
                try:
                    if not websocket.closed:
                        await websocket.close()
                    logger.debug("🔐 WebSocket connection properly closed")
                except Exception as close_err:
                    logger.warning(f"Error closing websocket: {close_err}")
                finally:
                    websocket = None  # Clear reference to allow garbage collection
        
        # Connection issues -> slow REST polling (do NOT automatically activate SAFE MODE)
        circuit_breaker_active = True
        
        # Exponential backoff for reconnection
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
        logger.info(f"🔄 Attempting WebSocket reconnection...")

async def _process_kline_message(data, dm, redis_client):
    """Process individual kline/OHLCV message from WebSocket"""
    global last_data_timestamp
    
    if 'k' not in data:
        return
        
    kline = data['k']
    symbol = kline['s']  # BTCUSDT
    interval = kline['i']  # 1m, 5m, etc.
    is_closed = kline['x']  # True if kline is closed (complete)
    
    # Only process closed klines for consistent data
    if not is_closed:
        return
    
    # Only log closed klines at DEBUG level to prevent memory leak
    logger.debug(f"📊 Kline: {symbol}:{interval}, Closed: {is_closed}")
        
    start_time = time.time()
    
    # Extract OHLCV data
    timestamp = int(kline['t'])
    open_price = float(kline['o'])
    high_price = float(kline['h'])
    low_price = float(kline['l'])
    close_price = float(kline['c'])
    volume = float(kline['v'])

    # Extract taker buy volume (Binance kline fields V, Q, n)
    taker_buy_base_vol = float(kline.get('V', 0))
    taker_buy_quote_vol = float(kline.get('Q', 0))
    num_trades = int(kline.get('n', 0))
    taker_buy_ratio = taker_buy_base_vol / volume if volume > 0 else 0.5
    taker_sell_ratio = 1.0 - taker_buy_ratio
    
    # Create bar data structure
    bar = {
        "timestamp": timestamp,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
        "taker_buy_base_vol": taker_buy_base_vol,
        "taker_buy_quote_vol": taker_buy_quote_vol,
        "taker_buy_ratio": round(taker_buy_ratio, 6),
        "taker_sell_ratio": round(taker_sell_ratio, 6),
        "num_trades": num_trades,
        "source": "binance_ws"
    }
    
    # Convert Binance interval to lowercase for consistency with config.TIMEFRAMES
    # Binance sends '1m', '5m', etc - keep lowercase to match standard
    timeframe = interval.lower()
    
    # Write to file (same as REST version)
    if dm:
        dm.append_live_bar(symbol, timeframe, bar)
    
    # Write to Redis
    if redis_client:
        try:
            redis_client.set(f"market:{symbol}:{timeframe}", json.dumps(bar))
            redis_client.set(
                f"latest:binance:ohlcv:{symbol}:{timeframe}",
                json.dumps({
                    "price": close_price,
                    "volume": volume,
                    "timestamp": timestamp,
                    "source": "binance_ws"
                })
            )

            # Rolling OHLCV list for TA service (Binance source of truth; bounded)
            try:
                ohlcv_list_key = f"ohlcv:list:binance:{symbol}:{timeframe}"
                ohlcv_list_item = {
                    "timestamp": int(timestamp),
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "close": close_price,
                    "volume": volume,
                    "source": "binance_ws",
                }
                redis_client.rpush(ohlcv_list_key, json.dumps(ohlcv_list_item))
                redis_client.ltrim(ohlcv_list_key, -2000, -1)
                redis_client.expire(ohlcv_list_key, 86400 * 30)
            except Exception as _ohlcv_list_err:
                # Keep ingestion resilient; TA can fall back to files/other sources
                logger.debug(f"OHLCV list write failed for {symbol}:{timeframe}: {_ohlcv_list_err}")
            
            # Update price and volatility keys for 1m timeframe (same as REST loop)
            if timeframe == '1m':
                # Calculate simple volatility proxy: (high-low)/open * 100
                vol_proxy = None
                if open_price > 0:
                    vol_proxy = (high_price - low_price) / open_price * 100.0
                
                # Update price key
                redis_client.set(f"price:{symbol}", json.dumps({
                    'price': close_price,
                    'source': 'binance_ws'
                }))
                redis_client.set(f"price:last:{symbol}", str(close_price))
                
                # Update volatility key
                if vol_proxy is not None:
                    redis_client.set(f"volatility:{symbol}", json.dumps({
                        'composite_index': vol_proxy
                    }))
            
            # Write CCXT-compatible keys for backward compatibility (replaces live_ccxt.py)
            # These keys are used as fallbacks by adaptive_edge_gate, maker_execution, etc.
            try:
                # ccxt:ticker:{symbol} - hash with ticker data
                ticker_data = {
                    'symbol': symbol,
                    'timestamp': str(timestamp),
                    'last': str(close_price),
                    'open': str(open_price),
                    'high': str(high_price),
                    'low': str(low_price),
                    'close': str(close_price),
                    'volume': str(volume),
                    'source': 'binance_ws'
                }
                redis_client.hset(f"ccxt:ticker:{symbol}", mapping=ticker_data)
                redis_client.expire(f"ccxt:ticker:{symbol}", 60)
                
                # ccxt:latest:{symbol}:{timeframe} - hash with latest candle
                latest_data = {
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'timestamp': str(timestamp),
                    'open': str(open_price),
                    'high': str(high_price),
                    'low': str(low_price),
                    'close': str(close_price),
                    'volume': str(volume)
                }
                redis_client.hset(f"ccxt:latest:{symbol}:{timeframe}", mapping=latest_data)
                redis_client.expire(f"ccxt:latest:{symbol}:{timeframe}", 300)
            except Exception as ccxt_err:
                logger.debug(f"CCXT-compat key write failed: {ccxt_err}")
            
            # Write normalized OHLCV keys - PRIMARY SOURCE for unified features
            # This replaces CCXT as the main OHLCV provider
            try:
                if ENABLE_NORMALIZATION:
                    # Prepare data for normalization
                    bar_with_meta = {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "timestamp": timestamp,
                        "open": open_price,
                        "high": high_price,
                        "low": low_price,
                        "close": close_price,
                        "volume": volume,
                        "source": "binance_ws"
                    }
                    
                    # Normalize using the generic normalize method
                    normalized = normalizer.normalize(bar_with_meta, source="binance_ws", enable_normalization=True)
                    normalized_key = f"features:binance_ws:{symbol}:{timeframe}:normalized"
                    redis_client.setex(normalized_key, 300, json.dumps(normalized))
                    
                    # DEBUG level to prevent memory leak from excessive logging
                    logger.debug(f"✅ Normalized OHLCV: {normalized_key}")
            except Exception as norm_err:
                logger.error(f"❌ Normalization error for {symbol} {timeframe}: {norm_err}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
            
            # Track processing latency
            processing_time = (time.time() - start_time) * 1000
            if processing_time > LATENCY_THRESHOLD_MS:
                logger.warning(f"⚠️ High processing latency: {processing_time:.1f}ms for {symbol} {timeframe}")
                
        except Exception as e:
            logger.error(f"❌ Redis write error for {symbol} {timeframe}: {e}")
    
    logger.debug(f"📊 WebSocket: {symbol} {timeframe} - ${close_price:.4f}, Vol: {volume:.2f}")

def _start_websocket_thread():
    """Start WebSocket streams in background thread"""
    if not WEBSOCKET_ENABLED:
        logger.info("🚫 WebSocket disabled via BINANCE_WEBSOCKET=0")
        return
    if DISABLE_OHLCV:
        # Keep top-of-book WS (markPrice/bookTicker) enabled; only disable kline/OHLCV WS.
        logger.info("📈 Binance kline/OHLCV WS disabled via DISABLE_BINANCE_OHLCV=1")
        return
        
    def _runner():
        dm = DataManager(Path(__file__).resolve().parent.parent / 'data' / 'live')
        redis_client = get_redis()
        asyncio.run(_websocket_kline_stream(SYMBOLS, TIMEFRAMES, dm, redis_client))
    
    t = threading.Thread(target=_runner, name="binance-websocket", daemon=True)
    t.start()
    logger.info("🚀 WebSocket thread started for low-latency data")

def _check_circuit_breaker():
    """Check for data freeze and activate circuit breaker if needed"""
    global safe_mode_active, last_ws_any_timestamp_ms, last_data_timestamp
    
    current_time = time.time() * 1000
    # IMPORTANT: Do NOT fail-safe the whole system because 1–2 low-liquidity symbols stopped emitting klines.
    # SAFE MODE should only activate when *all* websocket feeds go silent (pricing becomes untrustworthy).
    freeze_threshold = int(os.getenv("BINANCE_WS_FREEZE_THRESHOLD_MS", "5000"))  # default 5s

    if not last_ws_any_timestamp_ms:
        return  # no ws messages observed yet

    ws_silent_ms = current_time - float(last_ws_any_timestamp_ms)
    is_frozen = ws_silent_ms > freeze_threshold

    # Compute stale stream sample for debugging (does not drive activation).
    stale_streams = []
    try:
        stale_cutoff = current_time - freeze_threshold
        for stream_key, last_update in last_data_timestamp.items():
            if last_update < stale_cutoff:
                stale_streams.append(stream_key)
    except Exception:
        stale_streams = []

    if is_frozen and not safe_mode_active:
        safe_mode_active = True
        logger.warning(
            f"🚨 WS FREEZE DETECTED - No WS messages for {ws_silent_ms/1000:.1f}s (> {freeze_threshold/1000:.1f}s). "
            f"Activating SAFE MODE. stale_streams_sample={stale_streams[:5]}..."
        )
        _activate_safe_mode()
    elif (not is_frozen) and safe_mode_active:
        safe_mode_active = False
        logger.info("✅ WS FLOW RESUMED - Deactivating SAFE MODE")
        _deactivate_safe_mode()

def _activate_safe_mode():
    """Activate safe mode during exchange freeze/high latency"""
    redis_client = get_redis()
    
    try:
        # Set safe mode flag for other components (trader, etc.)
        if redis_client:
            safe_mode_data = {
                'active': True,
                'reason': 'data_freeze',
                'timestamp': int(time.time() * 1000),
                'triggered_by': 'live_binance_circuit_breaker'
            }
            redis_client.set('safe_mode:binance', json.dumps(safe_mode_data), ex=300)  # 5 min expiry
            
            # Alert other components
            redis_client.publish('alerts:safe_mode', json.dumps({
                'action': 'activate',
                'exchange': 'binance',
                'reason': 'data_freeze_detected',
                'timestamp': int(time.time() * 1000)
            }))
            
        logger.warning("🛡️ SAFE MODE ACTIVATED - Signaling components to cancel orders and reduce exposure")
        
        # Log safe mode activation for monitoring
        safe_mode_log = {
            'event': 'safe_mode_activated',
            'exchange': 'binance',
            'reason': 'circuit_breaker_triggered',
            'timestamp': int(time.time() * 1000),
            'stale_streams': len([k for k, v in last_data_timestamp.items() 
                                if time.time() * 1000 - v > 2000])
        }
        
        if redis_client:
            redis_client.lpush('log:safe_mode_events', json.dumps(safe_mode_log))
            redis_client.ltrim('log:safe_mode_events', 0, 99)  # Keep last 100 events
            
    except Exception as e:
        logger.error(f"❌ Error activating safe mode: {e}")

def _deactivate_safe_mode():
    """Deactivate safe mode when data flow resumes"""
    redis_client = get_redis()
    
    try:
        if redis_client:
            # Clear safe mode flag
            redis_client.delete('safe_mode:binance')
            
            # Alert components that it's safe to resume
            redis_client.publish('alerts:safe_mode', json.dumps({
                'action': 'deactivate', 
                'exchange': 'binance',
                'timestamp': int(time.time() * 1000)
            }))
            
        logger.info("✅ SAFE MODE DEACTIVATED - Normal operations can resume")
        
        # Log safe mode deactivation
        safe_mode_log = {
            'event': 'safe_mode_deactivated',
            'exchange': 'binance', 
            'timestamp': int(time.time() * 1000)
        }
        
        if redis_client:
            redis_client.lpush('log:safe_mode_events', json.dumps(safe_mode_log))
            redis_client.ltrim('log:safe_mode_events', 0, 99)
            
    except Exception as e:
        logger.error(f"❌ Error deactivating safe mode: {e}")

def _check_alternative_feeds():
    """Check if we can detect price movements from alternative sources when Binance is frozen"""
    redis_client = get_redis()
    
    if not redis_client:
        return
        
    try:
        # Check KuCoin feed as backup price reference
        alternative_prices = {}
        binance_prices = {}
        
        # Get recent prices from both exchanges for comparison
        for symbol in SYMBOLS[:3]:  # Check top 3 symbols
            # Get KuCoin price if available
            kc_key = f"kc:latest:{symbol}"
            kc_data = redis_client.get(kc_key)
            if kc_data:
                kc_parsed = json.loads(kc_data)
                alternative_prices[symbol] = {
                    'price': float(kc_parsed.get('last', 0)),
                    'timestamp': kc_parsed.get('ts', 0),
                    'source': 'kucoin'
                }
            
            # Get Binance price  
            bn_key = f"price:last:{symbol}"
            bn_price = redis_client.get(bn_key)
            if bn_price:
                binance_prices[symbol] = {
                    'price': float(bn_price),
                    'timestamp': time.time() * 1000,
                    'source': 'binance'
                }
        
        # Compare prices and detect significant divergence
        for symbol in alternative_prices:
            if symbol in binance_prices:
                alt_price = alternative_prices[symbol]['price']
                bn_price = binance_prices[symbol]['price']
                
                if alt_price > 0 and bn_price > 0:
                    divergence = abs(alt_price - bn_price) / bn_price * 100
                    
                    if divergence > 5.0:  # More than 5% divergence
                        logger.warning(f"🚨 PRICE DIVERGENCE: {symbol} KuCoin=${alt_price:.4f} vs Binance=${bn_price:.4f} ({divergence:.1f}%)")
                        
                        # Store divergence alert
                        divergence_alert = {
                            'symbol': symbol,
                            'kucoin_price': alt_price,
                            'binance_price': bn_price,
                            'divergence_pct': divergence,
                            'timestamp': int(time.time() * 1000)
                        }
                        
                        redis_client.lpush('alerts:price_divergence', json.dumps(divergence_alert))
                        redis_client.ltrim('alerts:price_divergence', 0, 49)  # Keep last 50
                        
    except Exception as e:
        logger.error(f"❌ Error checking alternative feeds: {e}")

# --- Local Orderbook Mirror for Instant Price/Spread Access ---

# Global orderbook mirrors (symbol -> {bids: [...], asks: [...], timestamp: ...})
# Use BoundedDict to prevent unlimited growth (max 50 symbols)
local_orderbooks = BoundedDict(maxsize=50)
orderbook_lock = threading.Lock()

async def _websocket_orderbook_stream(symbols, redis_client):
    """
    WebSocket stream for real-time orderbook data from Binance
    Maintains local mirror for instant spread/price calculations
    """
    global local_orderbooks
    global last_ws_any_timestamp_ms
    
    # Build stream names for orderbook depth
    streams = []
    for symbol in symbols[:5]:  # Limit to 5 symbols to avoid rate limits
        stream_name = f"{symbol.lower()}@depth20@100ms"  # 20 levels, 100ms updates
        streams.append(stream_name)

    WS_LIMITER.validate_stream_count(len(streams), context="local_orderbook")
    
    # Combined streams require `/stream?streams=` and wrap payload under `data`.
    stream_url = "wss://fstream.binance.com/stream?streams=" + "/".join(streams)
    
    logger.info(f"📊 Starting WebSocket orderbook stream for {len(streams)} symbols")
    
    reconnect_delay = 5
    max_reconnect_delay = 300
    
    while True:
        try:
            await WS_LIMITER.acquire_async()
            async with websockets.connect(stream_url, ping_interval=20, ping_timeout=60) as websocket:
                logger.info("✅ WebSocket orderbook connected to Binance futures")
                reconnect_delay = 5
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        payload = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else data
                        await _process_orderbook_message(payload, redis_client)
                        # Liveness marker (WS flow)
                        last_ws_any_timestamp_ms = int(time.time() * 1000)
                        
                    except json.JSONDecodeError:
                        logger.warning("⚠️ Invalid JSON in orderbook stream")
                    except Exception as e:
                        logger.error(f"❌ Error processing orderbook: {e}")
                        
        except websockets.exceptions.ConnectionClosed:
            logger.warning(f"🔌 Orderbook WebSocket closed, reconnecting in {reconnect_delay}s...")
        except Exception as e:
            logger.error(f"❌ Orderbook WebSocket error: {e}")
            
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

async def _process_orderbook_message(data, redis_client):
    """Process orderbook depth message and update local mirror"""
    global local_orderbooks, orderbook_lock
    
    if 'b' not in data or 'a' not in data:
        return
    
    symbol = data.get('s', '')
    if not symbol:
        return
        
    bids = [[float(price), float(qty)] for price, qty in data['b'][:50]]  # Top 50 levels
    asks = [[float(price), float(qty)] for price, qty in data['a'][:50]]  # Top 50 levels
    timestamp = time.time() * 1000
    
    # Update local mirror with thread safety
    with orderbook_lock:
        local_orderbooks[symbol] = {
            'bids': sorted(bids, key=lambda x: x[0], reverse=True)[:50],  # Highest first
            'asks': sorted(asks, key=lambda x: x[0])[:50],  # Lowest first
            'timestamp': timestamp,
            'symbol': symbol
        }
    
    # Calculate spread and mid price
    if bids and asks:
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        mid_price = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
        spread_bps = (spread / mid_price) * 10000 if mid_price > 0 else 0
        
        # Store instant access data in Redis
        if redis_client:
            try:
                instant_data = {
                    'symbol': symbol,
                    'bid': best_bid,
                    'ask': best_ask,
                    'mid': mid_price,
                    'spread': spread,
                    'spread_bps': spread_bps,
                    'timestamp': timestamp,
                    'source': 'binance_ws_depth'
                }
                
                redis_client.set(f"instant:{symbol}:spread", json.dumps(instant_data))
                redis_client.set(f"latest:binance:depth:{symbol}:20", json.dumps({
                    'bids': bids[:5],  # Top 5 levels
                    'asks': asks[:5],
                    'timestamp': timestamp
                }))
                
            except Exception as e:
                logger.error(f"❌ Redis orderbook write error: {e}")
        
        logger.debug(f"📊 {symbol} spread: ${spread:.4f} ({spread_bps:.1f}bps), mid: ${mid_price:.4f}")

def get_instant_spread(symbol):
    """Get instant spread from local orderbook mirror (no API call needed)"""
    with orderbook_lock:
        if symbol in local_orderbooks:
            ob = local_orderbooks[symbol]
            if ob['bids'] and ob['asks']:
                best_bid = ob['bids'][0][0]
                best_ask = ob['asks'][0][0]
                return {
                    'bid': best_bid,
                    'ask': best_ask,  
                    'spread': best_ask - best_bid,
                    'mid': (best_bid + best_ask) / 2,
                    'timestamp': ob['timestamp']
                }
    return None

def get_instant_price(symbol):
    """Get instant mid price from local orderbook (no latency)"""
    spread_data = get_instant_spread(symbol)
    return spread_data['mid'] if spread_data else None


# ============================================================================
# P2-8: SPOOF DETECTION SYSTEM
# ============================================================================

def detect_spoof_pattern(symbol: str, threshold_ratio: float = 0.5) -> dict:
    """
    P2-8: Detect potential orderbook spoofing patterns.
    
    Spoofing indicators:
    1. Large wall at specific level (>50% of visible liquidity on that side)
    2. Thin opposite side (imbalanced order book)
    3. Wall just outside best bid/ask (common spoof placement)
    4. Abnormal size concentration in top 3 levels vs rest
    
    Args:
        symbol: Trading pair symbol (e.g., 'BTCUSDT')
        threshold_ratio: Ratio threshold for wall detection (0.5 = 50%)
    
    Returns:
        dict with:
            - is_spoof: bool - True if spoof pattern detected
            - confidence: float - Confidence level (0-1)
            - direction: str - 'bid' or 'ask' or 'none'
            - wall_level: float - Price level of suspected wall
            - wall_size: float - Size of suspected wall
            - reason: str - Human-readable explanation
    """
    with orderbook_lock:
        if symbol not in local_orderbooks:
            return {
                'is_spoof': False,
                'confidence': 0.0,
                'direction': 'none',
                'wall_level': 0.0,
                'wall_size': 0.0,
                'reason': 'No orderbook data available'
            }
        
        ob = local_orderbooks[symbol]
        bids = ob.get('bids', [])
        asks = ob.get('asks', [])
        
        if not bids or not asks:
            return {
                'is_spoof': False,
                'confidence': 0.0,
                'direction': 'none',
                'wall_level': 0.0,
                'wall_size': 0.0,
                'reason': 'Empty orderbook'
            }
    
    # Analyze bid side for walls
    bid_volumes = [float(b[1]) for b in bids[:20]]  # Top 20 levels
    total_bid_volume = sum(bid_volumes) + 1e-8
    
    # Analyze ask side for walls
    ask_volumes = [float(a[1]) for a in asks[:20]]
    total_ask_volume = sum(ask_volumes) + 1e-8
    
    # Find max concentration in single level
    max_bid_vol = max(bid_volumes) if bid_volumes else 0
    max_bid_ratio = max_bid_vol / total_bid_volume
    max_bid_idx = bid_volumes.index(max_bid_vol) if max_bid_vol > 0 else 0
    
    max_ask_vol = max(ask_volumes) if ask_volumes else 0
    max_ask_ratio = max_ask_vol / total_ask_volume
    max_ask_idx = ask_volumes.index(max_ask_vol) if max_ask_vol > 0 else 0
    
    # Top 3 concentration (legitimate liquidity is usually distributed)
    top3_bid_ratio = sum(bid_volumes[:3]) / total_bid_volume
    top3_ask_ratio = sum(ask_volumes[:3]) / total_ask_volume
    
    # Imbalance detection
    total_imbalance = (total_bid_volume - total_ask_volume) / (total_bid_volume + total_ask_volume)
    
    # Detect spoof patterns
    spoof_detected = False
    spoof_confidence = 0.0
    spoof_direction = 'none'
    wall_level = 0.0
    wall_size = 0.0
    reasons = []
    
    # Pattern 1: Single level wall (>threshold_ratio of total liquidity)
    if max_bid_ratio > threshold_ratio:
        spoof_detected = True
        spoof_confidence = min(1.0, max_bid_ratio * 1.5)  # Scale confidence
        spoof_direction = 'bid'
        wall_level = float(bids[max_bid_idx][0])
        wall_size = max_bid_vol
        reasons.append(f"Bid wall at level {max_bid_idx+1}: {max_bid_ratio:.1%} of total bid liquidity")
    
    if max_ask_ratio > threshold_ratio:
        # If both sides have walls, take the higher confidence
        if max_ask_ratio > max_bid_ratio:
            spoof_detected = True
            spoof_confidence = min(1.0, max_ask_ratio * 1.5)
            spoof_direction = 'ask'
            wall_level = float(asks[max_ask_idx][0])
            wall_size = max_ask_vol
        reasons.append(f"Ask wall at level {max_ask_idx+1}: {max_ask_ratio:.1%} of total ask liquidity")
    
    # Pattern 2: Extreme imbalance with concentrated wall (amplifies spoof signal)
    if abs(total_imbalance) > 0.6 and (max_bid_ratio > 0.3 or max_ask_ratio > 0.3):
        spoof_confidence = min(1.0, spoof_confidence + 0.2)
        imbalance_dir = 'bid' if total_imbalance > 0 else 'ask'
        reasons.append(f"Extreme {imbalance_dir} imbalance: {abs(total_imbalance):.1%}")
    
    # Pattern 3: Wall just outside spread (levels 2-5 are common spoof locations)
    if max_bid_idx in [1, 2, 3, 4] and max_bid_ratio > 0.3:
        spoof_confidence = min(1.0, spoof_confidence + 0.15)
        reasons.append(f"Bid wall at suspicious level {max_bid_idx+1} (just below best bid)")
    
    if max_ask_idx in [1, 2, 3, 4] and max_ask_ratio > 0.3:
        spoof_confidence = min(1.0, spoof_confidence + 0.15)
        reasons.append(f"Ask wall at suspicious level {max_ask_idx+1} (just above best ask)")
    
    return {
        'is_spoof': spoof_detected,
        'confidence': round(spoof_confidence, 3),
        'direction': spoof_direction,
        'wall_level': wall_level,
        'wall_size': wall_size,
        'bid_concentration': round(max_bid_ratio, 3),
        'ask_concentration': round(max_ask_ratio, 3),
        'imbalance': round(total_imbalance, 3),
        'reason': ' | '.join(reasons) if reasons else 'No spoof patterns detected',
        'timestamp': time.time()
    }


def get_market_microstructure(symbol: str) -> dict:
    """
    Get comprehensive market microstructure analysis including spoof detection.
    
    Returns:
        dict with spread, depth, imbalance, and spoof analysis
    """
    spread_data = get_instant_spread(symbol)
    spoof_data = detect_spoof_pattern(symbol)
    
    if not spread_data:
        return {
            'symbol': symbol,
            'available': False,
            'timestamp': time.time()
        }
    
    with orderbook_lock:
        ob = local_orderbooks.get(symbol, {})
        bids = ob.get('bids', [])[:10]
        asks = ob.get('asks', [])[:10]
    
    # Calculate depth metrics
    bid_depth = sum(float(b[1]) for b in bids) if bids else 0
    ask_depth = sum(float(a[1]) for a in asks) if asks else 0
    total_depth = bid_depth + ask_depth
    depth_imbalance = (bid_depth - ask_depth) / (total_depth + 1e-8)
    
    return {
        'symbol': symbol,
        'available': True,
        'spread': spread_data,
        'depth': {
            'bid_depth': round(bid_depth, 4),
            'ask_depth': round(ask_depth, 4),
            'total_depth': round(total_depth, 4),
            'imbalance': round(depth_imbalance, 4)
        },
        'spoof': spoof_data,
        'trade_safety': {
            # Score 0-100, higher = safer to trade
            'score': max(0, 100 - (spoof_data['confidence'] * 50) - (abs(depth_imbalance) * 20)),
            'flags': []
        },
        'timestamp': time.time()
    }

def _start_orderbook_websocket_thread():
    """Start orderbook WebSocket streams in background thread"""
    if not WEBSOCKET_ENABLED:
        return
        
    def _runner():
        redis_client = get_redis()
        # Use top 5 liquid symbols for orderbook monitoring
        main_symbols = SYMBOLS[:5]  
        asyncio.run(_websocket_orderbook_stream(main_symbols, redis_client))
    
    t = threading.Thread(target=_runner, name="binance-orderbook-ws", daemon=True)
    t.start()
    logger.info("📊 Orderbook WebSocket thread started for instant spread access")

def fetch_loop():
    dm = DataManager(Path(__file__).resolve().parent.parent / 'data' / 'live')
    try:
        import ccxt
        exchange = ccxt.binance({"enableRateLimit": True})
    except Exception as e:
        logger.error(f"Exchange init failed: {e}")
        return
    r = get_redis()
    # Shared (Redis) rate limiter across all Binance REST-using processes (traders + ingestors).
    # IMPORTANT: All processes must use the SAME redis_key + rate/burst, otherwise the shared
    # token bucket becomes inconsistent and can overshoot the real Binance limit.
    safe_max = int(os.getenv("BINANCE_API_SAFE_CALLS_PER_MINUTE", "300"))
    safe_burst = int(os.getenv("BINANCE_API_BURST", "30"))
    limiter_key = os.getenv("BINANCE_LIMITER_KEY", "binance:limits:rest")
    rest_limiter = RedisBinanceRateLimiter(redis_key=limiter_key, max_per_minute=safe_max, burst=safe_burst)
    # Optional single-instance guard for Binance ingestor
    try:
        if r and os.getenv("BINANCE_SINGLETON", "1") == "1":
            _lock_key = "lock:live_binance"
            got = r.set(_lock_key, str(int(time.time()*1000)), nx=True, ex=120)
            if not got:
                logger.warning("Another live_binance instance holds the lock; exiting.")
                return
    except Exception:
        pass
    
    # Track consecutive ban errors for backoff logic
    ban_error_count = 0
    last_ban_time = 0
    ban_backoff_until = 0
    consecutive_error_count = 0  # Track consecutive errors for emergency brake
    MAX_CONSECUTIVE_ERRORS = 50  # Emergency stop after 50 consecutive errors
    
    # Local in-memory sparkline buffers (avoid unbounded lists in Redis)
    # Use bounded deques to prevent unbounded memory growth
    spark_buffers = {s: deque(maxlen=200) for s in SYMBOLS}
    # Track last 24h reference close for change calculation
    ref_prices = {s: None for s in SYMBOLS}
    ref_ts = {s: 0 for s in SYMBOLS}

    # Per-symbol REST refresh gates (reduce redundant REST load; avoid bans).
    oi_refresh_sec = int(os.getenv("BINANCE_OI_REFRESH_SEC", "120"))
    premium_refresh_sec = int(os.getenv("BINANCE_PREMIUM_REFRESH_SEC", "120"))
    funding_refresh_sec = int(os.getenv("BINANCE_FUNDING_REFRESH_SEC", "300"))
    last_oi_fetch_ts: dict = {s: 0.0 for s in SYMBOLS}
    last_premium_fetch_ts: dict = {s: 0.0 for s in SYMBOLS}
    last_funding_fetch_ts: dict = {s: 0.0 for s in SYMBOLS}
    # Start orderbook stream (background) if enabled
    _start_orderbook_thread()
    
    # Start WebSocket streams for low-latency data
    _start_websocket_thread()
    
    # Start orderbook WebSocket for instant spread calculations
    _start_orderbook_websocket_thread()

    # Start markPrice/bookTicker streams for fast top-of-book + funding/mark alignment
    _start_markprice_bookticker_thread()

    # Start aggTrades stream for real-time executed trade flow (spoof detection)
    _start_aggtrades_thread()
    
    # Track cycle count for circuit breaker checks
    cycle_count = 0
    
    # Exchange recreation timer - periodically recreate to flush HTTP sessions
    last_exchange_recreate = time.time()
    exchange_recreate_interval = 10  # CRITICAL FIX: Recreate every 10 seconds - prevents CCXT session pool bloat
    
    # Memory monitoring
    process = psutil.Process(os.getpid())
    last_memory_check = time.time()
    memory_check_interval = 20  # Check every 20 seconds (more frequent)
    max_memory_mb = 1500  # LOWERED: Alert if over 1.5GB (should stay under 1GB normally)
    emergency_memory_mb = 3000  # LOWERED: Emergency restart if > 3GB (was 8GB - too lenient)
    memory_warning_count = 0  # Track consecutive warnings
    last_gc_collect = time.time()
    gc_collect_interval = 30  # Force garbage collection every 30 seconds
    
    while True:
        current_time = time.time()

        # Shared ban guard across processes: if banned, pause REST work.
        if r:
            banned, remaining_ms = is_banned(r)
            if banned:
                sleep_for = min(max(remaining_ms / 1000, 5), 120)
                logger.warning(f"🚫 [GLOBAL BAN] Skipping REST; ban window remaining ~{remaining_ms/1000:.0f}s")
                time.sleep(sleep_for)
                continue
        
        # CCXT Exchange Recreation - prevent HTTP session pool bloat
        if current_time - last_exchange_recreate > exchange_recreate_interval:
            try:
                # AGGRESSIVE SESSION CLEANUP - close all internal connections
                old_exchange = exchange  # Keep reference for proper cleanup
                
                # Close old exchange HTTP session to cleanup connection pool
                # ccxt uses requests.Session internally which must be explicitly closed
                if hasattr(old_exchange, 'session'):
                    try:
                        session = old_exchange.session
                        if hasattr(session, 'close'):
                            session.close()
                            logger.info("🔒 Closed ccxt HTTP session")
                        
                        # Force connection pool cleanup (requests.Session stores adapters)
                        if hasattr(session, 'adapters'):
                            for adapter in session.adapters.values():
                                if hasattr(adapter, 'close'):
                                    adapter.close()
                            logger.info("🔒 Closed HTTP adapter connection pools")
                    except Exception as close_err:
                        logger.warning(f"Session cleanup error: {close_err}")
                
                # Nullify old reference before GC
                old_exchange = None
                
                # Force aggressive garbage collection (all generations)
                import gc
                gc.collect(0)  # Young generation
                gc.collect(1)  # Middle generation  
                gc.collect(2)  # Old generation
                
                # Recreate exchange with fresh session
                exchange = ccxt.binance({"enableRateLimit": True})
                last_exchange_recreate = current_time
                logger.info(f"♻️ Recreated ccxt exchange (every {exchange_recreate_interval}s) - memory cleanup complete")
            except Exception as e:
                logger.error(f"❌ Exchange recreation error: {e}")
        
        # Periodic forced garbage collection - prevent memory buildup
        if current_time - last_gc_collect > gc_collect_interval:
            try:
                import gc
                collected = gc.collect()
                last_gc_collect = current_time
                logger.debug(f"🗑️ Periodic GC freed {collected} objects")
            except Exception as gc_err:
                logger.warning(f"GC error: {gc_err}")
        
        # Memory monitoring - check every 20 seconds
        if current_time - last_memory_check > memory_check_interval:
            try:
                mem_info = process.memory_info()
                memory_mb = mem_info.rss / 1024 / 1024
                
                logger.info(f"💾 Memory: {memory_mb:.0f} MB RSS, {mem_info.vms / 1024 / 1024:.0f} MB VMS")
                
                # Emergency restart if memory exceeds critical threshold
                if memory_mb > emergency_memory_mb:
                    logger.error(f"🚨 EMERGENCY: Memory {memory_mb:.0f} MB exceeds {emergency_memory_mb} MB - RESTARTING PROCESS")
                    # Exit to allow systemd/supervisor to restart
                    import sys
                    sys.exit(99)  # Special exit code for memory emergency
                
                if memory_mb > max_memory_mb:
                    memory_warning_count += 1
                    logger.warning(f"⚠️ HIGH MEMORY #{memory_warning_count}: {memory_mb:.0f} MB exceeds {max_memory_mb} MB threshold")
                    
                    # Aggressive cleanup
                    import gc
                    
                    # Clear sparkline buffers (oldest data)
                    # MEMORY FIX: deque with maxlen=200 automatically manages size
                    # Recreating deques causes massive memory churn - REMOVED
                    logger.info("🧹 Sparkline buffers auto-managed by deque maxlen=200")
                    
                    # Force triple garbage collection
                    collected_total = 0
                    for i in range(3):
                        collected = gc.collect(i)
                        collected_total += collected
                    logger.info(f"🗑️ Garbage collection freed {collected_total} objects (3 passes)")
                    
                    # Re-check after GC
                    mem_info_after = process.memory_info()
                    memory_mb_after = mem_info_after.rss / 1024 / 1024
                    freed_mb = memory_mb - memory_mb_after
                    logger.info(f"💾 After cleanup: {memory_mb_after:.0f} MB RSS (freed {freed_mb:.0f} MB)")
                    
                    # If still high after 3 warnings, restart
                    if memory_warning_count >= 3 and memory_mb_after > max_memory_mb:
                        logger.error(f"🚨 Memory still high after 3 cleanup attempts - RESTARTING PROCESS")
                        import sys
                        sys.exit(98)  # Exit code for persistent memory issues
                else:
                    # Reset warning count if memory drops below threshold
                    if memory_warning_count > 0:
                        logger.info(f"✅ Memory back to normal: {memory_mb:.0f} MB (was {memory_warning_count} warnings)")
                    memory_warning_count = 0
                    
                last_memory_check = current_time
            except Exception as e:
                logger.error(f"❌ Memory monitoring error: {e}")
        
        print(f"🔄 [CYCLE] Starting Binance fetch cycle for {len(SYMBOLS)} symbols x {len(TIMEFRAMES)} timeframes...")
        
        # Log memory at start of each cycle for leak detection
        try:
            cycle_mem = process.memory_info().rss / 1024 / 1024
            logger.info(f"💾 [CYCLE START] Memory: {cycle_mem:.0f} MB RSS")  # Changed to INFO level for visibility
        except Exception:
            pass
        
        # Emergency brake: if too many consecutive errors, sleep longer
        if consecutive_error_count > MAX_CONSECUTIVE_ERRORS:
            emergency_sleep = 600  # 10 minutes
            logger.critical(f"🚨 [EMERGENCY BRAKE] {consecutive_error_count} consecutive errors. Sleeping {emergency_sleep}s to prevent CPU burnout.")
            time.sleep(emergency_sleep)
            consecutive_error_count = 0  # Reset after emergency sleep
        logger.info(f"[CYCLE] Starting Binance fetch cycle for {len(SYMBOLS)} symbols x {len(TIMEFRAMES)} timeframes...")
        
        # Check CoinAPI health ONCE per cycle (not per symbol-tf combo) to avoid log spam
        # Pass log_stale=True so we get ONE warning per cycle when stale
        coinapi_healthy = _check_coinapi_ohlcv_healthy(r, log_stale=True)
        if coinapi_healthy:
            logger.info("[COINAPI_OK] CoinAPI V1 OHLCV healthy - skipping Binance REST OHLCV")
        
        for sym in SYMBOLS:
            for tf in TIMEFRAMES:
                current_time = time.time()  # Move outside the try block for error handler access
                try:
                    # ------------------------------------------------------------------
                    # IMPORTANT BAN FIX:
                    # Open interest / premium index / funding are NOT timeframe-dependent.
                    # Previously they were executed once-per-(symbol,timeframe), multiplying
                    # REST calls by len(TIMEFRAMES) and causing Binance bans.
                    #
                    # Run them at most once per symbol per cycle (and also TTL-gated).
                    # ------------------------------------------------------------------
                    is_first_tf = bool(TIMEFRAMES) and (tf == TIMEFRAMES[0])
                    if is_first_tf:
                        # Open interest (REST-only). TTL-gate; avoid per-tf amplification.
                        if (not DISABLE_OI) and (current_time - float(last_oi_fetch_ts.get(sym, 0.0) or 0.0) >= oi_refresh_sec):
                            try:
                                rest_limiter.maybe_sleep(cost=1)
                                oi = exchange.fapiPublicGetOpenInterest({"symbol": sym})
                                last_oi_fetch_ts[sym] = current_time
                                if r and oi:
                                    r.set(f"market:{sym}:oi", json.dumps(oi))
                                    # Flat latest mirror
                                    try:
                                        # Binance futures open interest response: {"symbol": "BTCUSDT", "openInterest": "12345.67", "time": 1700000000000}
                                        oi_val = None
                                        if isinstance(oi.get('openInterest'), (int, float, str)):
                                            try:
                                                oi_val = float(oi.get('openInterest'))
                                            except Exception:
                                                oi_val = None
                                        elif isinstance(oi.get('value'), (int, float, str)):
                                            try:
                                                oi_val = float(oi.get('value'))
                                            except Exception:
                                                oi_val = None

                                        ts_ms = None
                                        for ts_key in ('time', 'timestamp', 'ts'):
                                            if isinstance(oi.get(ts_key), (int, float)):
                                                ts_ms = int(oi.get(ts_key))
                                                break
                                        if ts_ms is None:
                                            ts_ms = int(time.time() * 1000)

                                        r.set(f"latest:binance:oi:{sym}:spot", json.dumps({
                                            'ts_ms': ts_ms,
                                            'symbol': sym,
                                            'exchange': 'Binance',
                                            'oi': oi_val
                                        }))
                                        # Add legacy key without suffix to satisfy feature pipeline expectations
                                        r.set(f"latest:binance:oi:{sym}", json.dumps({
                                            'ts_ms': ts_ms,
                                            'symbol': sym,
                                            'exchange': 'Binance',
                                            'openInterest': oi_val
                                        }))
                                    except Exception:
                                        pass
                            except Exception as e:
                                logger.warning(f"OI fetch error {sym}: {e}")

                        # Premium index + funding are available via markPrice@1s WS.
                        # Only use REST fallback if markPrice WS is disabled.
                        if (not DISABLE_PREMIUM_INDEX) and (not ENABLE_MARKPRICE_WS) and (current_time - float(last_premium_fetch_ts.get(sym, 0.0) or 0.0) >= premium_refresh_sec):
                            try:
                                rest_limiter.maybe_sleep(cost=1)
                                pi = exchange.fapiPublicGetPremiumIndex({"symbol": sym})
                                last_premium_fetch_ts[sym] = current_time
                                if r and pi:
                                    r.set(f"market:{sym}:premium_index", json.dumps(pi))
                                    mark_val = None
                                    idx_val = None
                                    try:
                                        if isinstance(pi.get('markPrice'), (int, float, str)):
                                            mark_val = float(pi.get('markPrice'))
                                    except Exception:
                                        mark_val = None
                                    try:
                                        if isinstance(pi.get('indexPrice'), (int, float, str)):
                                            idx_val = float(pi.get('indexPrice'))
                                    except Exception:
                                        idx_val = None

                                    ts_ms_pi = None
                                    for ts_key in ('time', 'timestamp', 'T', 'E'):
                                        if isinstance(pi.get(ts_key), (int, float)):
                                            ts_ms_pi = int(pi.get(ts_key))
                                            break
                                    if ts_ms_pi is None:
                                        ts_ms_pi = int(time.time() * 1000)

                                    basis_pct = None
                                    try:
                                        if idx_val not in (None, 0):
                                            basis_pct = (mark_val - idx_val) / idx_val if mark_val is not None else None
                                    except Exception:
                                        basis_pct = None

                                    payload_pi = {
                                        'ts_ms': ts_ms_pi,
                                        'symbol': sym,
                                        'exchange': 'Binance',
                                        'mark_price': mark_val,
                                        'index_price': idx_val,
                                        'basis_pct': basis_pct,
                                        'last_funding_rate': float(pi.get('lastFundingRate')) if isinstance(pi.get('lastFundingRate'), (int, float, str)) else None,
                                        'next_funding_time': int(pi.get('nextFundingTime')) if isinstance(pi.get('nextFundingTime'), (int, float)) else None
                                    }
                                    try:
                                        r.set(f"latest:binance:mark_price:{sym}", json.dumps(payload_pi))
                                        r.set(f"latest:binance:index_price:{sym}", json.dumps(payload_pi))
                                        r.set(f"latest:binance:premium_index:{sym}", json.dumps(payload_pi))
                                    except Exception:
                                        pass
                            except Exception as e:
                                logger.warning(f"Premium index fetch error {sym}: {e}")

                        if (not DISABLE_FUNDING) and (not ENABLE_MARKPRICE_WS) and (current_time - float(last_funding_fetch_ts.get(sym, 0.0) or 0.0) >= funding_refresh_sec):
                            try:
                                rest_limiter.maybe_sleep(cost=1)
                                fr = exchange.fapiPublicGetFundingRate({"symbol": sym, "limit": 1})
                                last_funding_fetch_ts[sym] = current_time
                                if r and fr:
                                    r.set(f"market:{sym}:funding", json.dumps(fr[-1]))
                                    # Flat latest mirror
                                    try:
                                        fr_last = fr[-1]
                                        ts_ms_f = int(fr_last.get('fundingTime')) if isinstance(fr_last.get('fundingTime'), (int,float)) else int(time.time()*1000)
                                        funding_val = None
                                        if isinstance(fr_last.get('fundingRate'), (int, float, str)):
                                            try:
                                                funding_val = float(fr_last.get('fundingRate'))
                                            except Exception:
                                                funding_val = None
                                        payload_funding = {
                                            'ts_ms': ts_ms_f,
                                            'symbol': sym,
                                            'exchange': 'Binance',
                                            'funding_rate': funding_val,
                                            'fundingRate': funding_val
                                        }
                                        r.set(f"latest:binance:funding:{sym}:8h", json.dumps(payload_funding))
                                        # Add legacy key without timeframe suffix for feature pipeline compatibility
                                        r.set(f"latest:binance:funding:{sym}", json.dumps(payload_funding))
                                    except Exception:
                                        pass
                            except Exception as e:
                                logger.warning(f"Funding fetch error {sym}: {e}")

                    if not DISABLE_OHLCV and not coinapi_healthy:
                        # Skip REST calls if we're in a ban backoff period
                        if current_time < ban_backoff_until:
                            logger.debug(f"⏳ [SKIP] Skipping {sym} {tf} - in ban backoff until {datetime.fromtimestamp(ban_backoff_until).strftime('%H:%M:%S')}")
                            continue
                        
                        print(f"📈 [FETCH] Fetching {sym} {tf} from Binance...")
                        logger.info(f"[FETCH] Fetching {sym} {tf} from Binance...")
                        rest_limiter.maybe_sleep(cost=5)
                        ohlcv = exchange.fetch_ohlcv(sym, timeframe=tf, limit=2)
                        if ohlcv and len(ohlcv) > 0:
                            logger.debug(f"📊 [DEBUG] {sym} {tf} OHLCV data: {ohlcv[-1] if ohlcv else 'None'}")
                            if len(ohlcv[-1]) >= 6:
                                ts, o, h, l, c, v = ohlcv[-1]
                                consecutive_error_count = 0  # Reset on successful fetch
                            else:
                                logger.warning(f"⚠️ [DATA] {sym} {tf} incomplete OHLCV data: {ohlcv[-1]} (expected 6 fields, got {len(ohlcv[-1])})")
                                continue
                            bar = {"timestamp": ts, "ts": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}
                            logger.debug(f"[SUCCESS] {sym} {tf}: OHLC=${o:.4f}/${h:.4f}/${l:.4f}/${c:.4f}, Vol={v:.2f}")
                            dm.append_live_bar(sym, tf, bar)
                            if r:
                                r.set(f"market:{sym}:{tf}", json.dumps(bar))
                                # Flat latest mirror for OHLCV to satisfy latest:* gates
                                try:
                                    r.set(
                                        f"latest:binance:ohlcv:{sym}:{tf}",
                                        json.dumps({
                                            'ts_ms': int(ts),
                                            'symbol': sym,
                                            'timeframe': tf,
                                            'open': o,
                                            'high': h,
                                            'low': l,
                                            'close': c,
                                            'volume': v
                                        })
                                    )
                                except Exception:
                                    pass
                                # For primary timeframe (1m) update price:* keys & spark
                                if tf == '1m':
                                    # Initialize 24h reference every 24h or first time
                                    now = time.time()
                                    if ref_prices[sym] is None or now - ref_ts[sym] > 86400:
                                        ref_prices[sym] = c
                                        ref_ts[sym] = now
                                    change_24h = None
                                    try:
                                        if ref_prices[sym]:
                                            change_24h = (c - ref_prices[sym]) / ref_prices[sym] * 100.0
                                    except Exception:
                                        change_24h = None
                                    # Simple volatility proxy: (high-low)/open * 100 for this bar
                                    vol_proxy = None
                                    try:
                                        if o:
                                            vol_proxy = (h - l) / o * 100.0
                                    except Exception:
                                        vol_proxy = None
                                    # Maintain sparkline buffer (latest 200 closes)
                                    # MEMORY FIX: deque with maxlen=200 automatically drops oldest entries
                                    buf = spark_buffers[sym]
                                    buf.append(c)  # Deque with maxlen handles size limiting automatically
                                    try:
                                        r.set(f"price:{sym}", json.dumps({
                                            'price': c,
                                            'change_24h': change_24h
                                        }))
                                        # Add a plain last price for super-fast reads & PnL calc (no JSON parse)
                                        r.set(f"price:last:{sym}", str(c))
                                        r.set(f"volatility:{sym}", json.dumps({
                                            'composite_index': vol_proxy
                                        }))
                                        r.set(f"spark:{sym}", json.dumps(buf))
                                    except Exception:
                                        pass
                except Exception as e:
                    error_str = str(e)
                    consecutive_error_count += 1  # Track consecutive errors
                    
                    # Check for geo-restriction error (451) - CRITICAL FIX
                    if "451" in error_str or "restricted location" in error_str.lower():
                        ban_error_count += 1
                        last_ban_time = time.time()
                        
                        # Long backoff for geo-restriction: start 5 min, max 30 min
                        backoff_seconds = min(300 * (2 ** min(ban_error_count - 1, 3)), 1800)
                        ban_backoff_until = current_time + backoff_seconds
                        
                        logger.error(f"🚫 [GEO-BLOCK] {sym} {tf} - Binance geo-restriction (451). Backing off for {backoff_seconds}s until {datetime.fromtimestamp(ban_backoff_until).strftime('%H:%M:%S')}")
                        logger.error(f"⚠️ [ACTION REQUIRED] Consider using VPN or switching to binance.us if in US")
                        
                        # After 3 geo-blocks, enter long sleep mode
                        if ban_error_count >= 3:
                            logger.critical(f"🔥 [CRITICAL] Multiple geo-blocks ({ban_error_count}). Entering extended backoff mode.")
                            ban_backoff_until = current_time + 3600  # 1 hour
                    
                    # Check for Binance rate limit ban error (-1003)
                    elif "-1003" in error_str and "Way too many requests" in error_str:
                        ban_error_count += 1
                        last_ban_time = time.time()
                        
                        # Exponential backoff: start with 60s, max 300s (5 min)
                        backoff_seconds = min(60 * (2 ** min(ban_error_count - 1, 3)), 300)
                        ban_backoff_until = current_time + backoff_seconds
                        
                        logger.warning(f"🚫 [BAN] {sym} {tf} - Rate limit ban detected (count: {ban_error_count}). Backing off for {backoff_seconds}s until {datetime.fromtimestamp(ban_backoff_until).strftime('%H:%M:%S')}")

                        # Write shared ban flag so all processes pause REST
                        try:
                            # Try to extract ban-until timestamp if present; otherwise use backoff window
                            retry_ms = None
                            for token in error_str.split():
                                if token.isdigit() and len(token) >= 10:
                                    try:
                                        val = int(token)
                                        if val > 1_600_000_000_000:  # plausibly ms epoch
                                            retry_ms = val
                                            break
                                    except Exception:
                                        pass
                            until_ms = retry_ms if retry_ms else int((current_time + backoff_seconds) * 1000)
                            set_ban(r, until_ms, source="live_binance", reason="-1003 Way too many requests")
                        except Exception:
                            pass
                        
                        # If we're getting too many bans, suggest websocket usage
                        if ban_error_count >= 3:
                            logger.error(f"🔥 [CRITICAL] Multiple consecutive bans ({ban_error_count}). Consider using websocket-only mode or different IP.")
                    else:
                        # Reset ban counter on non-ban errors
                        if ban_error_count > 0:
                            logger.info(f"✅ [RECOVERY] Non-ban error encountered, resetting ban counter (was {ban_error_count})")
                            ban_error_count = 0
                        logger.warning(f"fetch error {sym} {tf}: {e}")
                        
                # Cooperative yield after each symbol+timeframe iteration
                time.sleep(0.01)
        if r:
            try:
                now_ms = int(time.time()*1000)
                r.set('ingest:binance:last_ts', now_ms)
                # TTL policy: no expiry here; retention is indefinite. Freshness judged by timestamp age.
                # Other components may read aliases like heartbeat:writer:binance.
                r.set('heartbeat:IngestBinance', now_ms)
                # refresh singleton lock TTL periodically
                try:
                    if os.getenv("BINANCE_SINGLETON", "1") == "1":
                        r.expire('lock:live_binance', 120)
                except Exception:
                    pass
            except Exception:
                pass
        # Check circuit breaker every few cycles
        cycle_count += 1
        if cycle_count % 5 == 0:  # Check every 5 cycles
            _check_circuit_breaker()
        
        # If kline/OHLCV WebSocket is active, reduce REST polling frequency
        if WEBSOCKET_ENABLED and (not DISABLE_OHLCV) and not circuit_breaker_active:
            # WebSocket provides real-time data, so REST polling can be slower
            sleep_time = 30  # 30 seconds instead of 5
            logger.debug(f"💤 WebSocket active - REST sleeping {sleep_time}s (low priority)")
        else:
            # Fallback REST polling - MUST be slow to avoid rate limits!
            # 13 symbols × 5 TFs = 65 calls/cycle. Binance limit is 2400/min.
            # At 60s sleep: 65 calls/min = 2.7% of limit (SAFE)
            # At 30s sleep: 130 calls/min = 5.4% of limit (OK with other processes)
            sleep_time = 60  # Changed from 5 to 60 seconds to prevent rate limit bans
            if circuit_breaker_active:
                logger.warning(f"⚠️ Circuit breaker active - using REST fallback (sleep {sleep_time}s)")
        
        # Cooperative yield before sleep
        time.sleep(0.01)
        time.sleep(sleep_time)

def main():
    """Supervisor to keep Binance ingestion alive (restart on errors)."""
    backoff = 5
    while True:
        try:
            fetch_loop()
            # fetch_loop is designed to run forever; if it returns, honor exit
            break
        except KeyboardInterrupt:
            logger.info("Stopped by user")
            break
        except Exception:
            err = traceback.format_exc()
            logger.error("Fatal error in live_binance:\n" + err)
            try:
                r = get_redis()
                if r:
                    r.set('proc:last_error:IngestBinance', err)
            except Exception:
                pass
            time.sleep(min(backoff, 180))
            backoff = min(backoff * 2, 180)
            # Cooperative yield in supervisor loop
            time.sleep(0.01)

if __name__ == "__main__":
    # Always log startup
    print(f"[{datetime.now()}] Binance OHLCV & Orderbook Ingestor starting...")
    print(f"🎯 Target symbols: {SYMBOLS}")
    print(f"📊 Timeframes: {TIMEFRAMES}")
    
    # Log OHLCV source configuration
    if DISABLE_OHLCV:
        print("📈 OHLCV: DISABLED via DISABLE_BINANCE_OHLCV")
    elif COINAPI_OHLCV_ENABLED:
        print(f"📈 OHLCV: CoinAPI V1 PRIMARY (Binance fallback if stale >{COINAPI_OHLCV_STALE_THRESHOLD_SEC}s)")
    else:
        print("📈 OHLCV: Binance REST (CoinAPI V1 disabled)")
    
    # Log Binance-only data sources (not available in CoinAPI)
    print("📊 Binance-Only Data (CoinAPI N/A):")
    print(f"   - funding_rate: {'ENABLED' if not DISABLE_FUNDING else 'DISABLED'} via markPrice@1s stream")
    print(f"   - premium_index/basis: {'ENABLED' if not DISABLE_PREMIUM_INDEX else 'DISABLED'}")
    print(f"   - open_interest: {'ENABLED' if not DISABLE_OI else 'DISABLED'}")
    print(f"   - mark_price WS: {'ENABLED' if ENABLE_MARKPRICE_WS else 'DISABLED'}")
    print(f"   - book_ticker WS: {'ENABLED' if ENABLE_BOOKTICKER_WS else 'DISABLED'}")
    
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
                f"📊 <b>BINANCE DATA INGESTOR STARTED</b>\n\n"
                f"Service: Live OHLCV & Orderbook\n"
                f"Symbols: {len(SYMBOLS)} pairs\n"
                f"Timeframes: {len(TIMEFRAMES)}\n"
                f"WebSocket: {'Enabled' if WEBSOCKET_ENABLED else 'Disabled'}\n"
                f"Status: ACTIVE",
                parse_mode="HTML",
                forward_to_private=True
            ))
            loop.close()
        except Exception as e:
            logger.debug(f"Failed to send startup notification: {e}")
    
    try:
        exit_if_already_running(name="live_binance", ttl_if_stale_seconds=600)
    except SystemExit:
        raise
    except Exception:
        pass
    r = None
    try:
        r = get_redis()
    except Exception:
        r = None
    try:
        start_heartbeat(r, "IngestBinance")
    except Exception:
        pass
    try:
        main()
        try:
            report_exit(r, "IngestBinance", "ok", "completed")
        except Exception:
            pass
        # Send shutdown notification
        if telegram_notifier:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(telegram_notifier.send_message(
                    "🛑 <b>BINANCE DATA INGESTOR STOPPED</b>\n\n"
                    "Service: Live OHLCV & Orderbook\n"
                    "Status: STOPPED NORMALLY",
                    parse_mode="HTML",
                    forward_to_private=True
                ))
                loop.close()
            except Exception as e:
                logger.debug(f"Failed to send shutdown notification: {e}")
    except KeyboardInterrupt:
        logger.info("🛑 Ingestor stopped by user")
        if telegram_notifier:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(telegram_notifier.send_message(
                    "🛑 <b>BINANCE DATA INGESTOR STOPPED</b>\n\n"
                    "Service: Live OHLCV & Orderbook\n"
                    "Status: STOPPED BY USER",
                    parse_mode="HTML",
                    forward_to_private=True
                ))
                loop.close()
            except Exception as e:
                logger.debug(f"Failed to send shutdown notification: {e}")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        if telegram_notifier:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(telegram_notifier.send_message(
                    f"❌ <b>BINANCE DATA INGESTOR ERROR</b>\n\n"
                    f"Service: Live OHLCV & Orderbook\n"
                    f"Status: CRASHED\n"
                    f"Error: {str(e)[:200]}...",
                    parse_mode="HTML",
                    forward_to_private=True
                ))
                loop.close()
            except Exception as alert_e:
                logger.debug(f"Failed to send error notification: {alert_e}")
    except Exception as e:
        try:
            report_exit(r, "IngestBinance", "error", repr(e))
        except Exception:
            pass
        raise
