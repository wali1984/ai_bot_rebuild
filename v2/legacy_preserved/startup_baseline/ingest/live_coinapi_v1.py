#!/usr/bin/env python3
"""
CoinAPI WebSocket V1 Ingestor - OHLCV + Metadata
=================================================
Supplements the DS (Data Stream) feed with V1-only data types:
- OHLCV candles (real-time, 1MIN-1DAY)
- Symbol volume metadata
- Exchange rates (VWAP-24H)

Rate Limiting:
- Shares API key with DS feed
- Coordinates via Redis to prevent combined rate limit hits
- Default: 10,000 msg/day limit shared across V1 + DS

Health Contract:
- Writes health metrics to metrics:coinapi:v1:*
- live_binance checks these to decide if OHLCV fallback needed

Author: WMA AI Trading System
Date: December 30, 2025
"""

import os
import sys
import json
import time
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
from dateutil.parser import isoparse
from collections import deque

try:
    import websockets
    from websockets.exceptions import ConnectionClosed, WebSocketException
except ImportError:
    websockets = None
    ConnectionClosed = Exception
    WebSocketException = Exception

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# Redis key patterns for health coordination
HEALTH_KEY_V1_LAST_OHLCV_TS = "metrics:coinapi:v1:last_ohlcv_ts"
HEALTH_KEY_V1_OHLCV_COUNT = "metrics:coinapi:v1:ohlcv_msgs_today"
HEALTH_KEY_V1_CONNECTED = "metrics:coinapi:v1:connected"
HEALTH_KEY_V1_SYMBOLS_ACTIVE = "metrics:coinapi:v1:symbols_active"
HEALTH_KEY_V1_ERROR_COUNT = "metrics:coinapi:v1:errors_today"

# Shared rate limit coordination
SHARED_RATE_KEY = "metrics:coinapi:shared:msgs_today"
SHARED_RATE_LIMIT = int(os.getenv("COINAPI_DAILY_MSG_LIMIT", "10000"))
V1_MSG_BUDGET_PCT = float(os.getenv("COINAPI_V1_BUDGET_PCT", "0.3"))  # 30% for V1


@dataclass
class OHLCVCandle:
    """OHLCV candle data from CoinAPI V1."""
    symbol: str
    period_id: str  # 1MIN, 5MIN, 15MIN, 1HRS, 4HRS, 1DAY
    time_period_start: str
    time_period_end: str
    time_open: Optional[str] = None
    time_close: Optional[str] = None
    price_open: float = 0.0
    price_high: float = 0.0
    price_low: float = 0.0
    price_close: float = 0.0
    volume_traded: float = 0.0
    trades_count: int = 0
    updated_ts_ms: int = 0
    
    def to_redis_hash(self) -> Dict[str, str]:
        """Convert to Redis hash format compatible with unified features."""
        return {
            'symbol': self.symbol,
            'period_id': self.period_id,
            'time_period_start': self.time_period_start,
            'time_period_end': self.time_period_end,
            'time_open': self.time_open or '',
            'time_close': self.time_close or '',
            'open': str(self.price_open),
            'high': str(self.price_high),
            'low': str(self.price_low),
            'close': str(self.price_close),
            'volume': str(self.volume_traded),
            'trades_count': str(self.trades_count),
            'updated_ts_ms': str(self.updated_ts_ms),
            'source': 'coinapi_v1',
        }
    
    def to_normalized_ohlcv(self) -> Dict[str, Any]:
        """Convert to normalized OHLCV format for feature pipeline."""
        return {
            'timestamp': self.time_period_start,
            'open': self.price_open,
            'high': self.price_high,
            'low': self.price_low,
            'close': self.price_close,
            'volume': self.volume_traded,
            'trades_count': self.trades_count,
            'source': 'coinapi_v1',
            'ts_ms': self.updated_ts_ms,
        }


class CoinAPIWebSocketV1:
    """
    CoinAPI WebSocket V1 client for OHLCV + metadata.
    
    V1-only features:
    - Real-time OHLCV candles (1MIN to 1DAY)
    - Symbol volume metadata
    - Exchange rates (VWAP-24H)
    
    Coordinates with DS feed via Redis for rate limiting.
    """
    
    # V1 endpoints
    ENDPOINTS = {
        'prod': 'wss://ws.coinapi.io/v1/',
        'sandbox': 'wss://ws-sandbox.coinapi.io/v1/',
    }
    
    # CoinAPI period ID mapping
    PERIOD_MAP = {
        '1m': '1MIN',
        '5m': '5MIN', 
        '15m': '15MIN',
        '1h': '1HRS',
        '4h': '4HRS',
        '1d': '1DAY',
    }
    
    # Reverse mapping for Redis keys
    PERIOD_REVERSE = {v: k for k, v in PERIOD_MAP.items()}
    
    def __init__(
        self,
        redis_client: Any = None,
        api_key: str = "",
        env: str = "prod",
        symbols: List[str] = None,
        timeframes: List[str] = None,
        exchange_id: str = "BINANCEFTS",
        subscribe_ohlcv: bool = True,
        subscribe_exrate: bool = False,
        subscribe_symbol: bool = False,
        watchdog_timeout_sec: int = 60,
        health_log_interval_sec: int = 60,
    ):
        self.redis = redis_client
        self.api_key = api_key or os.getenv("COINAPI_API_KEY", "")
        self.env = env or os.getenv("COINAPI_ENV", "prod")
        
        # Validate environment
        if self.env not in self.ENDPOINTS:
            logger.warning(f"[COINAPI_V1] Invalid env '{self.env}', defaulting to 'prod'")
            self.env = 'prod'
        
        self.ws_url = self.ENDPOINTS[self.env]
        self.exchange_id = exchange_id
        
        # Subscription config
        self.symbols = symbols or []
        self.timeframes = timeframes or ['1m', '5m', '15m', '1h', '4h']
        self.subscribe_ohlcv = subscribe_ohlcv
        self.subscribe_exrate = subscribe_exrate
        self.subscribe_symbol = subscribe_symbol
        
        # Connection state
        self.ws = None
        self.connected = False
        self._running = False
        
        # Symbol mapping
        self._internal_to_coinapi: Dict[str, str] = {}
        self._coinapi_to_internal: Dict[str, str] = {}
        
        # Metrics
        self._last_msg_ts: float = 0
        self._ohlcv_msgs_today: int = 0
        self._errors_today: int = 0
        self._last_health_log_ts: float = 0
        self._connected_since_ts: float = 0
        
        # Watchdog
        self.watchdog_timeout_sec = watchdog_timeout_sec
        self.health_log_interval_sec = health_log_interval_sec
        
        # Rate limiting
        self._msg_budget = int(SHARED_RATE_LIMIT * V1_MSG_BUDGET_PCT)
        
        logger.info(
            f"COINAPI_V1_INIT | env={self.env} | url={self.ws_url} | "
            f"exchange={self.exchange_id} | symbols={len(self.symbols)} | "
            f"timeframes={self.timeframes} | msg_budget={self._msg_budget}"
        )
    
    def _build_symbol_map(self):
        """Build symbol mapping for BINANCEFTS futures."""
        self._internal_to_coinapi.clear()
        self._coinapi_to_internal.clear()
        
        # Import symbol normalizer for consistent symbol handling
        try:
            from utils.symbol_manager import normalize_symbol, convert_symbol
        except ImportError:
            normalize_symbol = lambda s: s.upper().replace('/', '').replace('-', '')
            convert_symbol = None
        
        for sym in self.symbols:
            # Ensure symbol is in canonical format (BTCUSDT)
            canonical = normalize_symbol(sym) if normalize_symbol else sym.upper()
            
            # Internal: BTCUSDT -> CoinAPI: BINANCEFTS_PERP_BTC_USDT
            if convert_symbol:
                coinapi_sym = convert_symbol(canonical, "coinapi")
            else:
                base = canonical.replace('USDT', '')
                coinapi_sym = f"{self.exchange_id}_PERP_{base}_USDT"
            
            if coinapi_sym:
                self._internal_to_coinapi[canonical] = coinapi_sym
                self._coinapi_to_internal[coinapi_sym] = canonical
            
        logger.info(f"[COINAPI_V1] Built symbol map for {len(self._internal_to_coinapi)} symbols")
    
    def _check_rate_limit(self) -> bool:
        """
        Check if we're within rate limits.
        
        NOTE: CoinAPI WebSocket has data transfer limits (GB/day), NOT message count limits.
        The 10k/day limit applies to REST API calls only.
        
        For WebSocket, we track OHLCV messages for monitoring but don't enforce hard limits.
        """
        # WebSocket doesn't have message count limits, just data transfer
        # Always return True for WebSocket connections
        return True
    
    def _increment_rate_counters(self):
        """Increment rate limit counters in Redis (for monitoring, not enforcement)."""
        if not self.redis:
            return
        
        try:
            pipe = self.redis.pipeline()
            pipe.incr(SHARED_RATE_KEY)
            pipe.incr(HEALTH_KEY_V1_OHLCV_COUNT)
            # Set TTL to reset at midnight UTC
            now = datetime.now(timezone.utc)
            midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            ttl = int((midnight - now).total_seconds())
            pipe.expire(SHARED_RATE_KEY, ttl)
            pipe.expire(HEALTH_KEY_V1_OHLCV_COUNT, ttl)
            pipe.execute()
        except Exception as e:
            logger.debug(f"[COINAPI_V1] Rate counter increment error: {e}")
    
    def _update_health_metrics(self, connected: bool = True):
        """Update health metrics in Redis for coordination."""
        if not self.redis:
            return
        
        try:
            now_ts = int(time.time())
            pipe = self.redis.pipeline()
            pipe.set(HEALTH_KEY_V1_CONNECTED, "1" if connected else "0")
            pipe.set(HEALTH_KEY_V1_LAST_OHLCV_TS, str(now_ts))
            pipe.set(HEALTH_KEY_V1_SYMBOLS_ACTIVE, str(len(self.symbols)))
            pipe.set(HEALTH_KEY_V1_ERROR_COUNT, str(self._errors_today))
            pipe.execute()
        except Exception as e:
            logger.debug(f"[COINAPI_V1] Health metric update error: {e}")
    
    def _build_hello_message(self) -> Dict:
        """Build V1 hello/subscribe message."""
        hello = {
            "type": "hello",
            "apikey": self.api_key,
            "heartbeat": True,
            "subscribe_data_type": [],
            "subscribe_filter_symbol_id": [],
        }
        
        # Build symbol list
        coinapi_symbols = list(self._internal_to_coinapi.values())
        
        if self.subscribe_ohlcv:
            hello["subscribe_data_type"].append("ohlcv")
            hello["subscribe_filter_symbol_id"] = coinapi_symbols
            # Subscribe to specific periods
            hello["subscribe_filter_period_id"] = [
                self.PERIOD_MAP.get(tf, tf.upper()) for tf in self.timeframes
            ]
        
        if self.subscribe_exrate:
            hello["subscribe_data_type"].append("exrate")
            # Exchange rates are asset-based, not symbol-based
            hello["subscribe_filter_asset_id"] = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        if self.subscribe_symbol:
            hello["subscribe_data_type"].append("symbol")
            hello["subscribe_filter_symbol_id"] = coinapi_symbols
        
        return hello
    
    async def _process_ohlcv(self, msg: Dict):
        """Process OHLCV message and write to Redis."""
        try:
            symbol_id = msg.get('symbol_id', '')
            internal_sym = self._coinapi_to_internal.get(symbol_id)
            
            if not internal_sym:
                logger.debug(f"[COINAPI_V1] Unknown symbol: {symbol_id}")
                return
            
            period_id = msg.get('period_id', '')
            internal_tf = self.PERIOD_REVERSE.get(period_id, period_id.lower())
            
            # Parse candle
            candle = OHLCVCandle(
                symbol=internal_sym,
                period_id=period_id,
                time_period_start=msg.get('time_period_start', ''),
                time_period_end=msg.get('time_period_end', ''),
                time_open=msg.get('time_open'),
                time_close=msg.get('time_close'),
                price_open=float(msg.get('price_open', 0)),
                price_high=float(msg.get('price_high', 0)),
                price_low=float(msg.get('price_low', 0)),
                price_close=float(msg.get('price_close', 0)),
                volume_traded=float(msg.get('volume_traded', 0)),
                trades_count=int(msg.get('trades_count', 0)),
                updated_ts_ms=int(time.time() * 1000),
            )
            
            # Write to Redis
            if self.redis:
                # Primary key: latest OHLCV for feature pipeline
                ohlcv_key = f"latest:coinapi:ohlcv:{internal_sym}:{internal_tf}"
                self.redis.hset(ohlcv_key, mapping=candle.to_redis_hash())
                self.redis.expire(ohlcv_key, 3600)  # 1 hour TTL
                
                # Normalized key (same format as live_binance)
                normalized_key = f"normalized:ohlcv:{internal_sym}:{internal_tf}"
                self.redis.hset(normalized_key, mapping=candle.to_redis_hash())
                self.redis.expire(normalized_key, 3600)
                
                # CRITICAL: Write to market:{symbol}:{tf} for feature pipeline compatibility
                # This is the key that feature_pipeline.py reads from
                market_key = f"market:{internal_sym}:{internal_tf}"
                market_data = {
                    'timestamp': int(time.time() * 1000),
                    'open': candle.price_open,
                    'high': candle.price_high,
                    'low': candle.price_low,
                    'close': candle.price_close,
                    'volume': candle.volume_traded,
                    'source': 'coinapi_v1',
                }
                self.redis.set(market_key, json.dumps(market_data))
                
                # Also write latest:binance:ohlcv: format for trainer gates
                latest_ohlcv_key = f"latest:binance:ohlcv:{internal_sym}:{internal_tf}"
                latest_ohlcv_data = {
                    'ts_ms': int(time.time() * 1000),
                    'symbol': internal_sym,
                    'timeframe': internal_tf,
                    'open': candle.price_open,
                    'high': candle.price_high,
                    'low': candle.price_low,
                    'close': candle.price_close,
                    'volume': candle.volume_traded,
                    'source': 'coinapi_v1',
                }
                self.redis.set(latest_ohlcv_key, json.dumps(latest_ohlcv_data))

                # Rolling OHLCV list for TA service (CoinAPI fallback; bounded)
                try:
                    ts_ms = candle.updated_ts_ms
                    if candle.time_period_start:
                        try:
                            ts_ms = int(isoparse(candle.time_period_start).timestamp() * 1000)
                        except Exception:
                            pass

                    ohlcv_list_key = f"ohlcv:list:coinapi:{internal_sym}:{internal_tf}"
                    ohlcv_list_item = {
                        "timestamp": int(ts_ms),
                        "open": candle.price_open,
                        "high": candle.price_high,
                        "low": candle.price_low,
                        "close": candle.price_close,
                        "volume": candle.volume_traded,
                        "source": "coinapi_v1",
                    }
                    self.redis.rpush(ohlcv_list_key, json.dumps(ohlcv_list_item))
                    self.redis.ltrim(ohlcv_list_key, -2000, -1)
                    self.redis.expire(ohlcv_list_key, 86400 * 30)
                except Exception as _ohlcv_list_err:
                    logger.debug(f"[COINAPI_V1] OHLCV list write failed for {internal_sym}:{internal_tf}: {_ohlcv_list_err}")
                
                # Update health timestamp
                self._update_health_metrics(connected=True)
            
            self._ohlcv_msgs_today += 1
            self._last_msg_ts = time.time()
            
            # Rate-limited logging
            now = time.time()
            if now - self._last_health_log_ts > self.health_log_interval_sec:
                self._last_health_log_ts = now
                logger.info(
                    f"COINAPI_V1_OHLCV | {internal_sym}:{internal_tf} | "
                    f"O={candle.price_open:.2f} H={candle.price_high:.2f} "
                    f"L={candle.price_low:.2f} C={candle.price_close:.2f} | "
                    f"vol={candle.volume_traded:.2f} trades={candle.trades_count} | "
                    f"msgs_today={self._ohlcv_msgs_today}"
                )
            
        except Exception as e:
            self._errors_today += 1
            logger.error(f"[COINAPI_V1] OHLCV processing error: {e}")
    
    async def _process_exrate(self, msg: Dict):
        """Process exchange rate message."""
        try:
            asset_base = msg.get('asset_id_base', '')
            asset_quote = msg.get('asset_id_quote', 'USD')
            rate = float(msg.get('rate', 0))
            rate_type = msg.get('rate_type', '')
            
            if self.redis and rate > 0:
                key = f"exrate:coinapi:{asset_base}_{asset_quote}"
                self.redis.hset(key, mapping={
                    'asset_base': asset_base,
                    'asset_quote': asset_quote,
                    'rate': str(rate),
                    'rate_type': rate_type,
                    'time': msg.get('time', ''),
                    'updated_ts_ms': str(int(time.time() * 1000)),
                })
                self.redis.expire(key, 3600)
            
            logger.debug(f"[COINAPI_V1] ExRate: {asset_base}/{asset_quote} = {rate:.4f}")
            
        except Exception as e:
            logger.error(f"[COINAPI_V1] ExRate processing error: {e}")
    
    async def _process_symbol(self, msg: Dict):
        """Process symbol metadata message."""
        try:
            symbol_id = msg.get('symbol_id', '')
            internal_sym = self._coinapi_to_internal.get(symbol_id)
            
            if not internal_sym:
                return
            
            if self.redis:
                key = f"symbol:coinapi:{internal_sym}"
                self.redis.hset(key, mapping={
                    'symbol_id': symbol_id,
                    'volume_1hrs': str(msg.get('volume_1hrs', 0)),
                    'volume_1hrs_usd': str(msg.get('volume_1hrs_usd', 0)),
                    'volume_1day': str(msg.get('volume_1day', 0)),
                    'volume_1day_usd': str(msg.get('volume_1day_usd', 0)),
                    'price': str(msg.get('price', 0)),
                    'updated_ts_ms': str(int(time.time() * 1000)),
                })
                self.redis.expire(key, 3600)
            
        except Exception as e:
            logger.error(f"[COINAPI_V1] Symbol processing error: {e}")
    
    async def _message_handler(self, msg_str: str):
        """Handle incoming WebSocket message."""
        try:
            msg = json.loads(msg_str)
            msg_type = msg.get('type', '')
            
            # Increment rate counters
            self._increment_rate_counters()
            
            if msg_type == 'ohlcv':
                await self._process_ohlcv(msg)
            elif msg_type == 'exrate':
                await self._process_exrate(msg)
            elif msg_type == 'symbol':
                await self._process_symbol(msg)
            elif msg_type == 'heartbeat' or msg_type == 'hearbeat':  # CoinAPI typo
                self._last_msg_ts = time.time()
                logger.debug("[COINAPI_V1] Heartbeat received")
            elif msg_type == 'error':
                self._errors_today += 1
                logger.error(f"[COINAPI_V1] API Error: {msg.get('message', msg)}")
            elif msg_type == 'reconnect':
                logger.warning(f"[COINAPI_V1] Server requesting reconnect within {msg.get('within_seconds', 10)}s")
            else:
                logger.debug(f"[COINAPI_V1] Unknown message type: {msg_type}")
                
        except json.JSONDecodeError as e:
            logger.error(f"[COINAPI_V1] JSON decode error: {e}")
        except Exception as e:
            self._errors_today += 1
            logger.error(f"[COINAPI_V1] Message handler error: {e}")
    
    async def _watchdog(self):
        """Watchdog to detect stale connections."""
        while self._running:
            await asyncio.sleep(10)
            
            if not self.connected:
                continue
            
            elapsed = time.time() - self._last_msg_ts
            if elapsed > self.watchdog_timeout_sec:
                logger.warning(
                    f"[COINAPI_V1] WATCHDOG: No messages for {elapsed:.1f}s, triggering reconnect"
                )
                self._update_health_metrics(connected=False)
                if self.ws:
                    try:
                        await self.ws.close()
                    except Exception as close_err:
                        logger.debug(f"[COINAPI_V1] Watchdog close: {close_err}")
    
    async def connect_and_run(self):
        """Main connection loop with auto-reconnect."""
        self._running = True
        self._build_symbol_map()
        
        # Start watchdog
        watchdog_task = asyncio.create_task(self._watchdog())
        
        reconnect_delay = 1
        max_reconnect_delay = 60
        
        while self._running:
            try:
                # Check rate limit before connecting
                if not self._check_rate_limit():
                    logger.warning("[COINAPI_V1] Rate limited, waiting 60s...")
                    await asyncio.sleep(60)
                    continue
                
                logger.info(f"[COINAPI_V1] Connecting to {self.ws_url}...")
                
                async with websockets.connect(
                    self.ws_url,
                    # IMPORTANT: We request `heartbeat=true` in the hello message and we run an
                    # application watchdog. Disable client WS keepalive pings to avoid false
                    # disconnects on brief stalls ("keepalive ping timeout").
                    ping_interval=None,
                    close_timeout=5,
                ) as ws:
                    self.ws = ws
                    self.connected = True
                    self._connected_since_ts = time.time()
                    self._last_msg_ts = time.time()
                    reconnect_delay = 1  # Reset on successful connect
                    
                    logger.info("[COINAPI_V1] ✅ Connected")
                    self._update_health_metrics(connected=True)
                    
                    # Send hello/subscribe
                    hello = self._build_hello_message()
                    await ws.send(json.dumps(hello))
                    logger.info(
                        f"[COINAPI_V1] 📡 Subscribed: types={hello['subscribe_data_type']} "
                        f"symbols={len(hello.get('subscribe_filter_symbol_id', []))} "
                        f"periods={hello.get('subscribe_filter_period_id', [])}"
                    )
                    
                    # Message loop
                    async for msg in ws:
                        if not self._running:
                            break
                        await self._message_handler(msg)
                
            except ConnectionClosed as e:
                logger.warning(f"[COINAPI_V1] Connection closed: {e}")
            except WebSocketException as e:
                logger.error(f"[COINAPI_V1] WebSocket error: {e}")
            except Exception as e:
                logger.error(f"[COINAPI_V1] Unexpected error: {e}")
            finally:
                self.connected = False
                self._update_health_metrics(connected=False)
            
            if self._running:
                logger.info(f"[COINAPI_V1] Reconnecting in {reconnect_delay}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
        
        try:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass
        except Exception as e:
            logger.debug(f"[COINAPI_V1] Watchdog task cleanup: {e}")
        logger.info("[COINAPI_V1] Stopped")
    
    def stop(self):
        """Stop the client."""
        self._running = False
        if self.ws:
            asyncio.create_task(self.ws.close())


def _light_redis():
    """Plain Redis client — avoids utils.redis_client → config.py → torch in this ingestor."""
    import redis as _redis_mod

    return _redis_mod.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        decode_responses=True,
    )


def _load_symbols_light() -> List[str]:
    """
    Active symbols without importing config/torch (same key as symbol_manager).
    Order: COINAPI_V1_SYMBOLS env → Redis config:symbols:active → config.SYMBOLS last resort.
    """
    csv_syms = os.getenv("COINAPI_V1_SYMBOLS", "").strip()
    if csv_syms:
        out = [s.strip().upper() for s in csv_syms.split(",") if s.strip()]
        if out:
            return out

    try:
        r = _light_redis()
        raw = r.get("config:symbols:active")
        if raw:
            if isinstance(raw, str):
                data = json.loads(raw)
            elif isinstance(raw, bytes):
                data = json.loads(raw.decode("utf-8"))
            else:
                data = raw
            if isinstance(data, list) and data:
                return [str(s).upper().strip() for s in data if s]
    except Exception as e:
        logger.debug(f"[COINAPI_V1] Redis symbol load failed: {e}")

    try:
        from config import SYMBOLS as _sym  # noqa: PLC0415 — last resort only

        return list(_sym)
    except Exception:
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def _load_timeframes_light() -> List[str]:
    tfs = os.getenv("COINAPI_V1_TIMEFRAMES", "").strip()
    if tfs:
        return [x.strip() for x in tfs.split(",") if x.strip()]
    try:
        from config import TIMEFRAMES as _tf  # noqa: PLC0415

        return list(_tf)
    except Exception:
        return ["1m", "5m", "15m", "1h", "4h"]


async def main():
    """Main entry point."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    SYMBOLS = _load_symbols_light()
    logger.info(f"[COINAPI_V1] Using symbols: {len(SYMBOLS)} (light loader, no redis_client pool)")

    TIMEFRAMES = _load_timeframes_light()
    
    # Redis connection
    redis_client = _light_redis()
    
    # API key check
    api_key = os.getenv("COINAPI_API_KEY", "")
    if not api_key:
        logger.error("[COINAPI_V1] COINAPI_API_KEY not set!")
        raise SystemExit(2)
    
    # Create client
    watchdog_sec = int(os.getenv("COINAPI_V1_WATCHDOG_SEC", "120"))

    client = CoinAPIWebSocketV1(
        redis_client=redis_client,
        api_key=api_key,
        symbols=SYMBOLS,
        timeframes=TIMEFRAMES,
        subscribe_ohlcv=True,
        subscribe_exrate=os.getenv("COINAPI_V1_SUBSCRIBE_EXRATE", "true").lower()
        in ("1", "true", "yes"),
        subscribe_symbol=False,
        watchdog_timeout_sec=watchdog_sec,
    )
    
    # Run
    try:
        await client.connect_and_run()
    except KeyboardInterrupt:
        logger.info("[COINAPI_V1] Interrupted")
        client.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    backoff = 1.0
    max_backoff = 120.0
    while True:
        try:
            asyncio.run(main())
            logger.warning("[COINAPI_V1] main() returned; restarting in %.0fs", backoff)
        except KeyboardInterrupt:
            logger.info("[COINAPI_V1] Exiting on KeyboardInterrupt")
            raise
        except Exception as e:
            logger.exception("[COINAPI_V1] Fatal error, restarting: %s", e)
        time.sleep(backoff)
        backoff = min(backoff * 2.0, max_backoff)
