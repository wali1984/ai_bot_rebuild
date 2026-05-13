#!/usr/bin/env python3
"""
Unified Real-Time Price Provider with Multi-Source Failover (v1.0)
===================================================================
Provides low-latency price data with automatic failover between sources.

Source Priority (configurable):
1. PRIMARY: CoinAPI WebSocket (already running for microstructure)
2. SECONDARY: Binance WebSocket (direct futures stream)
3. TERTIARY: CCXT REST (polling fallback)
4. QUATERNARY: KuCoin REST (last resort)
5. CACHE: Redis cache (if all external sources fail)

Failover Timings:
- Source considered stale after: 2 seconds (STALE_THRESHOLD_MS)
- Failover decision time: 500ms max
- Health check interval: 1 second
- Source recovery check: 5 seconds

Contract:
- Writes to: price:realtime:{SYMBOL} (JSON with price, source, ts_ms, latency_ms)
- Writes to: price:{SYMBOL} (simple price value for backward compatibility)
- Health metrics: metrics:price_provider:*

Author: WMA AI Trading System
Date: December 27, 2025
"""

import os
import sys
import json
import time
import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import deque
from enum import Enum
import aiohttp

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import redis
except ImportError:
    redis = None

try:
    import websockets
    from websockets.exceptions import ConnectionClosed, WebSocketException
except ImportError:
    websockets = None
    ConnectionClosed = Exception
    WebSocketException = Exception

try:
    import ccxt.async_support as ccxt_async
except ImportError:
    ccxt_async = None

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

def _internal_to_ccxt_binance_futures_symbol(symbol: str) -> str:
    """
    Convert internal symbol format (e.g., BTCUSDT) to CCXT Binance futures symbol
    format (e.g., BTC/USDT:USDT).
    """
    s = (symbol or "").upper().strip()
    if not s:
        return s
    if s.endswith("USDT") and len(s) > 4:
        base = s[:-4]
        return f"{base}/USDT:USDT"
    return s


def _ccxt_to_internal_symbol(symbol: str) -> str:
    """
    Convert CCXT market symbols like:
      - BTC/USDT:USDT
      - BTC/USDT
    into internal symbol format: BTCUSDT
    """
    s = (symbol or "").upper().strip()
    if not s:
        return s
    if ":" in s:
        s = s.split(":", 1)[0]
    return s.replace("/", "")


class PriceSource(Enum):
    """Price data sources in priority order."""
    COINAPI_WS = "coinapi_ws"
    BINANCE_WS = "binance_ws"  
    CCXT_REST = "ccxt_rest"
    KUCOIN_REST = "kucoin_rest"
    REDIS_CACHE = "redis_cache"
    UNKNOWN = "unknown"


@dataclass
class SourceConfig:
    """Configuration for each price source."""
    name: PriceSource
    enabled: bool = True
    priority: int = 0  # Lower = higher priority
    stale_threshold_ms: int = 2000  # Consider stale after 2s
    failover_delay_ms: int = 500  # Max time to wait before failover
    recovery_check_sec: float = 5.0  # Check if source recovered
    max_consecutive_failures: int = 5


@dataclass
class PriceData:
    """Standardized price data structure."""
    symbol: str
    price: float
    bid: float = 0.0
    ask: float = 0.0
    volume_24h: float = 0.0
    source: PriceSource = PriceSource.UNKNOWN
    ts_ms: int = 0
    received_ts_ms: int = 0
    latency_ms: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'price': self.price,
            'bid': self.bid,
            'ask': self.ask,
            'volume_24h': self.volume_24h,
            'source': self.source.value,
            'ts_ms': self.ts_ms,
            'received_ts_ms': self.received_ts_ms,
            'latency_ms': self.latency_ms,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class SourceHealth:
    """Health status for a price source."""
    source: PriceSource
    is_connected: bool = False
    is_healthy: bool = False
    last_update_ts_ms: int = 0
    consecutive_failures: int = 0
    total_messages: int = 0
    avg_latency_ms: float = 0.0
    last_error: str = ""
    
    # Latency tracking
    latency_samples: deque = field(default_factory=lambda: deque(maxlen=100))
    
    def record_success(self, latency_ms: int):
        self.consecutive_failures = 0
        self.total_messages += 1
        self.last_update_ts_ms = int(time.time() * 1000)
        self.latency_samples.append(latency_ms)
        if self.latency_samples:
            self.avg_latency_ms = sum(self.latency_samples) / len(self.latency_samples)
        self.is_healthy = True
    
    def record_failure(self, error: str):
        self.consecutive_failures += 1
        self.last_error = error
        if self.consecutive_failures >= 3:
            self.is_healthy = False


# Default source configurations with failover timings
DEFAULT_SOURCE_CONFIGS = {
    PriceSource.COINAPI_WS: SourceConfig(
        name=PriceSource.COINAPI_WS,
        priority=1,
        stale_threshold_ms=2000,  # 2s - CoinAPI should be fastest
        failover_delay_ms=300,
        recovery_check_sec=5.0,
    ),
    PriceSource.BINANCE_WS: SourceConfig(
        name=PriceSource.BINANCE_WS,
        priority=2,
        stale_threshold_ms=2000,  # 2s
        failover_delay_ms=500,
        recovery_check_sec=5.0,
    ),
    PriceSource.CCXT_REST: SourceConfig(
        name=PriceSource.CCXT_REST,
        priority=3,
        stale_threshold_ms=5000,  # 5s - REST is slower
        failover_delay_ms=1000,
        recovery_check_sec=10.0,
    ),
    PriceSource.KUCOIN_REST: SourceConfig(
        name=PriceSource.KUCOIN_REST,
        priority=4,
        stale_threshold_ms=5000,  # 5s
        failover_delay_ms=1000,
        recovery_check_sec=15.0,
    ),
    PriceSource.REDIS_CACHE: SourceConfig(
        name=PriceSource.REDIS_CACHE,
        priority=99,  # Last resort
        stale_threshold_ms=60000,  # 60s - cache can be old
        failover_delay_ms=100,  # Fast failover from cache
        recovery_check_sec=30.0,
    ),
}


# =============================================================================
# Price Provider Core
# =============================================================================

class RealtimePriceProvider:
    """
    Unified real-time price provider with multi-source failover.
    
    Monitors multiple price sources and automatically fails over to the next
    available source when the primary becomes stale or unavailable.
    """
    
    def __init__(
        self,
        redis_client: Any = None,
        symbols: List[str] = None,
        source_configs: Dict[PriceSource, SourceConfig] = None,
        health_check_interval_sec: float = 1.0,
        publish_interval_ms: int = 100,  # Publish at most every 100ms
        binance_feed_mode: str = "auto",  # auto|redis|direct (direct = connect here)
    ):
        self.redis = redis_client
        self.symbols = symbols or []
        self.source_configs = source_configs or DEFAULT_SOURCE_CONFIGS
        self.health_check_interval_sec = health_check_interval_sec
        self.publish_interval_ms = publish_interval_ms
        self._binance_feed_mode = (binance_feed_mode or "auto").lower().strip()
        
        # State
        self._running = False
        self._lock = threading.Lock()
        
        # Per-symbol state
        self._prices: Dict[str, PriceData] = {}
        self._last_publish_ts: Dict[str, int] = {}
        
        # Per-source health
        self._source_health: Dict[PriceSource, SourceHealth] = {
            source: SourceHealth(source=source) for source in PriceSource
        }
        
        # Active source per symbol (allows per-symbol failover)
        self._active_source: Dict[str, PriceSource] = {}
        
        # WebSocket connections
        self._binance_ws = None
        self._coinapi_subscribed = False
        
        # REST clients
        self._ccxt_exchange = None
        self._http_session = None
        
        logger.info(
            f"[PRICE_PROVIDER] Initialized | symbols={len(self.symbols)} | "
            f"sources={[s.value for s in self.source_configs.keys() if self.source_configs[s].enabled]}"
        )
    
    # -------------------------------------------------------------------------
    # Source: CoinAPI WebSocket (reads from existing msnap keys)
    # -------------------------------------------------------------------------
    
    def _check_coinapi_price(self, symbol: str) -> Optional[PriceData]:
        """
        Read price from CoinAPI microstructure snapshot (already populated by live_coinapi_wsds.py).
        Key: msnap:coinapi_wsds:{SYMBOL}
        """
        if not self.redis:
            return None
        
        try:
            key = f"msnap:coinapi_wsds:{symbol}"
            data = self.redis.hgetall(key)
            
            if not data:
                return None
            
            # Parse snapshot data
            updated_ts_ms = int(data.get('updated_ts_ms', 0))
            mid_px = float(data.get('mid_px', 0))
            best_bid = float(data.get('best_bid_px', 0))
            best_ask = float(data.get('best_ask_px', 0))
            
            if mid_px <= 0 and best_bid > 0 and best_ask > 0:
                mid_px = (best_bid + best_ask) / 2
            
            if mid_px <= 0:
                return None
            
            now_ms = int(time.time() * 1000)
            latency_ms = now_ms - updated_ts_ms if updated_ts_ms > 0 else 0
            
            return PriceData(
                symbol=symbol,
                price=mid_px,
                bid=best_bid,
                ask=best_ask,
                source=PriceSource.COINAPI_WS,
                ts_ms=updated_ts_ms,
                received_ts_ms=now_ms,
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.debug(f"[PRICE_PROVIDER] CoinAPI read error for {symbol}: {e}")
            return None

    def _should_use_binance_redis_feed(self) -> bool:
        """
        Decide whether Binance prices should be read from Redis keys populated by
        `ingest/live_binance.py` instead of opening a direct Binance WebSocket here.

        Modes:
        - auto  : use Redis feed if available, else direct WS (if enabled)
        - redis : force Redis feed
        - direct: force direct WS
        """
        mode = self._binance_feed_mode
        if mode == "redis":
            return True
        if mode == "direct":
            return False

        # auto mode: prefer Redis feed if keys exist
        if not self.redis or not self.symbols:
            return False
        try:
            probe = self.symbols[0]
            return bool(self.redis.exists(f"latest:binance:mark_price:{probe}"))
        except Exception:
            return False

    def _check_binance_redis_price(self, symbol: str) -> Optional[PriceData]:
        """
        Read Binance WS-derived price from Redis keys written by `ingest/live_binance.py`.

        - Mark price: latest:binance:mark_price:{SYMBOL}
        - Top of book: orderbook:top:{SYMBOL}
        """
        if not self.redis:
            return None

        try:
            now_ms = int(time.time() * 1000)

            bid = 0.0
            ask = 0.0
            ts_ms = 0
            price = 0.0

            # Prefer top-of-book mid if available (more "tradeable" than mark)
            ob_raw = self.redis.get(f"orderbook:top:{symbol}")
            if ob_raw:
                try:
                    ob = json.loads(ob_raw)
                    bid = float(ob.get("bid", 0) or 0)
                    ask = float(ob.get("ask", 0) or 0)
                    ts_ms = int(ob.get("ts", 0) or 0)
                    if bid > 0 and ask > 0:
                        price = (bid + ask) / 2.0
                except Exception:
                    pass

            mk_raw = self.redis.get(f"latest:binance:mark_price:{symbol}")
            if mk_raw:
                try:
                    mk = json.loads(mk_raw)
                    mk_ts = int(mk.get("ts_ms", 0) or 0)
                    if mk_ts > ts_ms:
                        ts_ms = mk_ts
                    mk_price = float(mk.get("mark_price", 0) or 0)
                    if price <= 0 and mk_price > 0:
                        price = mk_price
                except Exception:
                    pass

            if price <= 0 or ts_ms <= 0:
                return None

            latency_ms = now_ms - ts_ms if ts_ms > 0 else 0

            return PriceData(
                symbol=symbol,
                price=price,
                bid=bid,
                ask=ask,
                source=PriceSource.BINANCE_WS,
                ts_ms=ts_ms,
                received_ts_ms=now_ms,
                latency_ms=latency_ms,
            )
        except Exception as e:
            logger.debug(f"[PRICE_PROVIDER] Binance(redis) read error for {symbol}: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # Source: Binance WebSocket (direct connection)
    # -------------------------------------------------------------------------
    
    async def _start_binance_ws(self):
        """Start Binance WebSocket for real-time prices."""
        if not websockets:
            logger.warning("[PRICE_PROVIDER] websockets not installed - Binance WS disabled")
            return
        
        # Build combined stream URL for all symbols
        streams = [f"{s.lower()}@markPrice@1s" for s in self.symbols]
        stream_url = f"wss://fstream.binance.com/stream?streams={'/'.join(streams)}"
        
        logger.info(f"[PRICE_PROVIDER] Connecting Binance WS for {len(self.symbols)} symbols...")
        
        retry_count = 0
        
        while self._running:
            try:
                async with websockets.connect(stream_url, ping_interval=20, ping_timeout=10) as ws:
                    self._binance_ws = ws
                    self._source_health[PriceSource.BINANCE_WS].is_connected = True
                    logger.info("[PRICE_PROVIDER] ✅ Binance WS connected")
                    retry_count = 0  # Reset on successful connection
                    
                    async for message in ws:
                        if not self._running:
                            break
                        
                        try:
                            data = json.loads(message)
                            await self._process_binance_message(data)
                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            logger.debug(f"[PRICE_PROVIDER] Binance message error: {e}")
                            
            except (ConnectionClosed, WebSocketException) as e:
                logger.warning(f"[PRICE_PROVIDER] Binance WS disconnected: {e}")
                self._source_health[PriceSource.BINANCE_WS].is_connected = False
                self._source_health[PriceSource.BINANCE_WS].record_failure(str(e))
                
            except Exception as e:
                logger.error(f"[PRICE_PROVIDER] Binance WS error: {e}")
                self._source_health[PriceSource.BINANCE_WS].record_failure(str(e))
            
            retry_count += 1
            if self._running:
                wait_time = min(60, 2 ** retry_count)
                logger.info(f"[PRICE_PROVIDER] Binance WS reconnecting in {wait_time}s (attempt {retry_count})")
                await asyncio.sleep(wait_time)
    
    async def _process_binance_message(self, data: Dict):
        """Process Binance WebSocket message."""
        try:
            if 'data' not in data:
                return
            
            msg = data['data']
            event_type = msg.get('e', '')
            
            if event_type == 'markPriceUpdate':
                symbol = msg.get('s', '')  # e.g., BTCUSDT
                mark_price = float(msg.get('p', 0))
                event_time = int(msg.get('E', 0))
                
                if symbol and mark_price > 0:
                    now_ms = int(time.time() * 1000)
                    latency_ms = now_ms - event_time if event_time > 0 else 0
                    
                    price_data = PriceData(
                        symbol=symbol,
                        price=mark_price,
                        source=PriceSource.BINANCE_WS,
                        ts_ms=event_time,
                        received_ts_ms=now_ms,
                        latency_ms=latency_ms,
                    )
                    
                    self._update_price(symbol, price_data)
                    self._source_health[PriceSource.BINANCE_WS].record_success(latency_ms)
                    
        except Exception as e:
            logger.debug(f"[PRICE_PROVIDER] Binance process error: {e}")
    
    # -------------------------------------------------------------------------
    # Source: CCXT REST (polling fallback)
    # -------------------------------------------------------------------------
    
    async def _init_ccxt(self):
        """Initialize CCXT exchange client."""
        if not ccxt_async:
            logger.warning("[PRICE_PROVIDER] ccxt not installed - CCXT REST disabled")
            return
        
        try:
            self._ccxt_exchange = ccxt_async.binance({
                'enableRateLimit': True,
                'options': {'defaultType': 'future'},
            })
            logger.info("[PRICE_PROVIDER] ✅ CCXT initialized")
        except Exception as e:
            logger.error(f"[PRICE_PROVIDER] CCXT init failed: {e}")
    
    async def _fetch_ccxt_prices(self) -> Dict[str, PriceData]:
        """Fetch prices via CCXT REST API."""
        if not self._ccxt_exchange:
            await self._init_ccxt()
        
        if not self._ccxt_exchange:
            return {}
        
        results = {}
        
        try:
            # Fetch all tickers at once (more efficient)
            ccxt_symbols = [_internal_to_ccxt_binance_futures_symbol(s) for s in self.symbols]
            tickers = await self._ccxt_exchange.fetch_tickers(ccxt_symbols)
            now_ms = int(time.time() * 1000)
            
            for ccxt_symbol, ticker in tickers.items():
                if ticker and ticker.get('last'):
                    internal_symbol = _ccxt_to_internal_symbol(ccxt_symbol)
                    if internal_symbol not in self.symbols:
                        continue
                    results[internal_symbol] = PriceData(
                        symbol=internal_symbol,
                        price=float(ticker['last']),
                        bid=float(ticker.get('bid', 0) or 0),
                        ask=float(ticker.get('ask', 0) or 0),
                        volume_24h=float(ticker.get('quoteVolume', 0) or 0),
                        source=PriceSource.CCXT_REST,
                        ts_ms=int(ticker.get('timestamp', now_ms)),
                        received_ts_ms=now_ms,
                        latency_ms=0,  # REST doesn't have true latency
                    )
            
            self._source_health[PriceSource.CCXT_REST].record_success(0)
            
        except Exception as e:
            logger.warning(f"[PRICE_PROVIDER] CCXT fetch error: {e}")
            self._source_health[PriceSource.CCXT_REST].record_failure(str(e))
        
        return results
    
    # -------------------------------------------------------------------------
    # Source: KuCoin REST (last external resort)
    # -------------------------------------------------------------------------
    
    async def _fetch_kucoin_prices(self) -> Dict[str, PriceData]:
        """Fetch prices via KuCoin REST API."""
        results = {}
        
        if not self._http_session:
            self._http_session = aiohttp.ClientSession()
        
        try:
            # KuCoin futures ticker endpoint
            url = "https://api-futures.kucoin.com/api/v1/contracts/active"
            
            async with self._http_session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    now_ms = int(time.time() * 1000)
                    
                    for contract in data.get('data', []):
                        # Map KuCoin symbol to internal format
                        kc_symbol = contract.get('symbol', '')  # e.g., XBTUSDTM
                        mark_price = float(contract.get('markPrice', 0) or 0)
                        
                        # Convert to our symbol format
                        internal_symbol = kc_symbol.replace('USDTM', 'USDT').replace('XBT', 'BTC')
                        
                        if internal_symbol in self.symbols and mark_price > 0:
                            results[internal_symbol] = PriceData(
                                symbol=internal_symbol,
                                price=mark_price,
                                source=PriceSource.KUCOIN_REST,
                                ts_ms=now_ms,
                                received_ts_ms=now_ms,
                                latency_ms=0,
                            )
            
            self._source_health[PriceSource.KUCOIN_REST].record_success(0)
            
        except Exception as e:
            logger.warning(f"[PRICE_PROVIDER] KuCoin fetch error: {e}")
            self._source_health[PriceSource.KUCOIN_REST].record_failure(str(e))
        
        return results
    
    # -------------------------------------------------------------------------
    # Source: Redis Cache (final fallback)
    # -------------------------------------------------------------------------
    
    def _get_cached_price(self, symbol: str) -> Optional[PriceData]:
        """Get cached price from Redis as final fallback."""
        if not self.redis:
            return None
        
        try:
            # Try new realtime key first
            data = self.redis.get(f"price:realtime:{symbol}")
            if data:
                parsed = json.loads(data)
                now_ms = int(time.time() * 1000)
                return PriceData(
                    symbol=symbol,
                    price=float(parsed.get('price', 0)),
                    bid=float(parsed.get('bid', 0)),
                    ask=float(parsed.get('ask', 0)),
                    source=PriceSource.REDIS_CACHE,
                    ts_ms=int(parsed.get('ts_ms', 0)),
                    received_ts_ms=now_ms,
                    latency_ms=now_ms - int(parsed.get('ts_ms', now_ms)),
                )
            
            # Try legacy price key
            legacy_data = self.redis.get(f"price:{symbol}")
            if legacy_data:
                try:
                    parsed = json.loads(legacy_data)
                    price = float(parsed.get('price', 0))
                except (json.JSONDecodeError, TypeError):
                    price = float(legacy_data)
                
                if price > 0:
                    now_ms = int(time.time() * 1000)
                    return PriceData(
                        symbol=symbol,
                        price=price,
                        source=PriceSource.REDIS_CACHE,
                        ts_ms=now_ms,
                        received_ts_ms=now_ms,
                        latency_ms=0,
                    )
                    
        except Exception as e:
            logger.debug(f"[PRICE_PROVIDER] Redis cache read error for {symbol}: {e}")
        
        return None
    
    # -------------------------------------------------------------------------
    # Price Selection & Failover Logic
    # -------------------------------------------------------------------------
    
    def _select_best_price(self, symbol: str) -> Optional[PriceData]:
        """
        Select the best price for a symbol based on source priority and staleness.
        
        Failover Logic:
        1. Check sources in priority order
        2. Skip source if stale (exceeds stale_threshold_ms)
        3. Skip source if unhealthy (consecutive failures >= max)
        4. Use first valid source found
        5. Fall back to Redis cache if all else fails
        """
        now_ms = int(time.time() * 1000)
        
        # Sort sources by priority
        sorted_sources = sorted(
            self.source_configs.items(),
            key=lambda x: x[1].priority
        )
        
        for source, config in sorted_sources:
            if not config.enabled:
                continue
            
            health = self._source_health[source]
            
            # Skip unhealthy sources (unless it's cache)
            if source != PriceSource.REDIS_CACHE:
                if health.consecutive_failures >= config.max_consecutive_failures:
                    continue
            
            # Get price from source
            price_data = None
            
            if source == PriceSource.COINAPI_WS:
                price_data = (
                    self._prices.get(f"{symbol}:{PriceSource.COINAPI_WS.value}")
                    or self._check_coinapi_price(symbol)
                )
            elif source == PriceSource.BINANCE_WS:
                # If we are in "redis" (or auto+redis available) mode, read from
                # Redis keys populated by ingest/live_binance.py. Otherwise, use
                # direct WS cache populated by _start_binance_ws().
                price_data = self._prices.get(f"{symbol}:{PriceSource.BINANCE_WS.value}") or self._prices.get(f"{symbol}:binance")
                if not price_data and self._should_use_binance_redis_feed():
                    price_data = self._check_binance_redis_price(symbol)
                    if price_data:
                        with self._lock:
                            self._prices[f"{symbol}:{PriceSource.BINANCE_WS.value}"] = price_data
            elif source == PriceSource.REDIS_CACHE:
                price_data = self._get_cached_price(symbol)
            # CCXT and KuCoin are fetched periodically, check cached values
            elif source in (PriceSource.CCXT_REST, PriceSource.KUCOIN_REST):
                price_data = self._prices.get(f"{symbol}:{source.value}")
            
            if not price_data:
                continue
            
            # Check staleness
            staleness_ms = now_ms - price_data.ts_ms if price_data.ts_ms > 0 else 0
            
            if staleness_ms > config.stale_threshold_ms:
                logger.debug(
                    f"[PRICE_PROVIDER] {symbol} {source.value} stale: "
                    f"{staleness_ms}ms > {config.stale_threshold_ms}ms threshold"
                )
                continue
            
            # Valid price found
            return price_data
        
        return None
    
    def _update_price(self, symbol: str, price_data: PriceData):
        """Update price for a symbol and publish to Redis."""
        with self._lock:
            # Store with source suffix for source-specific lookups
            self._prices[f"{symbol}:{price_data.source.value}"] = price_data
            
            # Check if this should become the active price
            current = self._prices.get(symbol)
            now_ms = int(time.time() * 1000)
            
            # Update if no current price, or new price is from higher priority source,
            # or current price is stale
            should_update = False
            
            if not current:
                should_update = True
            else:
                current_config = self.source_configs.get(current.source)
                new_config = self.source_configs.get(price_data.source)
                
                # Higher priority source
                if new_config and current_config and new_config.priority < current_config.priority:
                    should_update = True
                # Same source - always update
                elif price_data.source == current.source:
                    should_update = True
                # Current is stale
                elif current_config and (now_ms - current.ts_ms) > current_config.stale_threshold_ms:
                    should_update = True
            
            if should_update:
                self._prices[symbol] = price_data
                self._active_source[symbol] = price_data.source
                
                # Publish to Redis (rate limited)
                last_publish = self._last_publish_ts.get(symbol, 0)
                if (now_ms - last_publish) >= self.publish_interval_ms:
                    self._publish_to_redis(symbol, price_data)
                    self._last_publish_ts[symbol] = now_ms
    
    def _publish_to_redis(self, symbol: str, price_data: PriceData):
        """Publish price to Redis keys."""
        if not self.redis:
            return
        
        try:
            pipe = self.redis.pipeline()
            
            # New detailed key
            pipe.set(f"price:realtime:{symbol}", price_data.to_json())
            pipe.expire(f"price:realtime:{symbol}", 60)  # 60s TTL
            
            # Legacy compatibility key (simple JSON)
            legacy = {
                'price': price_data.price,
                'change_24h': 0,  # Not tracked here
            }
            pipe.set(f"price:{symbol}", json.dumps(legacy))
            
            # Health metrics
            pipe.hset(f"metrics:price_provider:{symbol}", mapping={
                'source': price_data.source.value,
                'price': str(price_data.price),
                'ts_ms': str(price_data.ts_ms),
                'latency_ms': str(price_data.latency_ms),
                'updated_at': str(int(time.time() * 1000)),
            })
            pipe.expire(f"metrics:price_provider:{symbol}", 300)
            
            pipe.execute()
            
        except Exception as e:
            logger.debug(f"[PRICE_PROVIDER] Redis publish error for {symbol}: {e}")
    
    # -------------------------------------------------------------------------
    # Health Check & Failover Loop
    # -------------------------------------------------------------------------
    
    async def _health_check_loop(self):
        """Periodic health check and failover evaluation."""
        while self._running:
            try:
                now_ms = int(time.time() * 1000)
                
                for symbol in self.symbols:
                    # Refresh per-source caches (do NOT force them active here).
                    # We always select the active price via _select_best_price(), which
                    # applies staleness thresholds and avoids publishing stale CoinAPI.
                    coinapi_price = self._check_coinapi_price(symbol)
                    if coinapi_price:
                        with self._lock:
                            self._prices[f"{symbol}:{PriceSource.COINAPI_WS.value}"] = coinapi_price
                        self._source_health[PriceSource.COINAPI_WS].record_success(coinapi_price.latency_ms)

                    if self._should_use_binance_redis_feed():
                        bn_price = self._check_binance_redis_price(symbol)
                        if bn_price:
                            with self._lock:
                                self._prices[f"{symbol}:{PriceSource.BINANCE_WS.value}"] = bn_price
                            self._source_health[PriceSource.BINANCE_WS].record_success(bn_price.latency_ms)
                    
                    # Select best price and update if needed
                    best = self._select_best_price(symbol)
                    if best:
                        self._update_price(symbol, best)
                
                # Log health summary periodically
                if hasattr(self, '_last_health_log') and (time.time() - self._last_health_log) > 60:
                    self._log_health_summary()
                    self._last_health_log = time.time()
                elif not hasattr(self, '_last_health_log'):
                    self._last_health_log = time.time()
                
            except Exception as e:
                logger.error(f"[PRICE_PROVIDER] Health check error: {e}")
            
            await asyncio.sleep(self.health_check_interval_sec)
    
    async def _ccxt_polling_loop(self):
        """Periodic CCXT REST polling (every 2 seconds)."""
        while self._running:
            try:
                # Avoid hammering REST when at least one WS-derived source is healthy.
                # We only poll CCXT if BOTH CoinAPI and Binance are stale/missing for ANY symbol.
                now_ms = int(time.time() * 1000)
                need_ccxt = False
                for sym in self.symbols:
                    with self._lock:
                        coin = self._prices.get(f"{sym}:{PriceSource.COINAPI_WS.value}")
                        bn = self._prices.get(f"{sym}:{PriceSource.BINANCE_WS.value}")

                    coin_cfg = self.source_configs.get(PriceSource.COINAPI_WS)
                    bn_cfg = self.source_configs.get(PriceSource.BINANCE_WS)
                    coin_ok = bool(
                        coin
                        and coin.ts_ms > 0
                        and coin_cfg
                        and (now_ms - coin.ts_ms) <= coin_cfg.stale_threshold_ms
                    )
                    bn_ok = bool(
                        bn
                        and bn.ts_ms > 0
                        and bn_cfg
                        and (now_ms - bn.ts_ms) <= bn_cfg.stale_threshold_ms
                    )

                    if not (coin_ok or bn_ok):
                        need_ccxt = True
                        break

                if not need_ccxt:
                    await asyncio.sleep(5.0)
                    continue

                prices = await self._fetch_ccxt_prices()
                for symbol, price_data in prices.items():
                    with self._lock:
                        self._prices[f"{symbol}:{PriceSource.CCXT_REST.value}"] = price_data
                    
                    # Only use if higher priority sources are stale
                    with self._lock:
                        current = self._prices.get(symbol)
                    if not current or current.source in (PriceSource.CCXT_REST, PriceSource.KUCOIN_REST, PriceSource.REDIS_CACHE):
                        self._update_price(symbol, price_data)
                        
            except Exception as e:
                logger.debug(f"[PRICE_PROVIDER] CCXT polling error: {e}")
            
            await asyncio.sleep(5.0)  # Poll every 5 seconds (fallback-only)
    
    async def _kucoin_polling_loop(self):
        """Periodic KuCoin REST polling (every 5 seconds)."""
        while self._running:
            try:
                prices = await self._fetch_kucoin_prices()
                for symbol, price_data in prices.items():
                    self._prices[f"{symbol}:{PriceSource.KUCOIN_REST.value}"] = price_data
                    
            except Exception as e:
                logger.debug(f"[PRICE_PROVIDER] KuCoin polling error: {e}")
            
            await asyncio.sleep(5.0)  # Poll every 5 seconds
    
    def _log_health_summary(self):
        """Log health summary for all sources."""
        lines = ["[PRICE_PROVIDER] Health Summary:"]
        
        for source in PriceSource:
            if source == PriceSource.UNKNOWN:
                continue
            
            health = self._source_health[source]
            config = self.source_configs.get(source)
            
            if config and config.enabled:
                status = "✅" if health.is_healthy else "❌"
                lines.append(
                    f"  {status} {source.value}: msgs={health.total_messages} "
                    f"avg_latency={health.avg_latency_ms:.0f}ms "
                    f"failures={health.consecutive_failures}"
                )
        
        # Active sources per symbol summary
        source_counts = {}
        for symbol, source in self._active_source.items():
            source_counts[source.value] = source_counts.get(source.value, 0) + 1
        
        lines.append(f"  Active sources: {source_counts}")
        
        logger.info("\n".join(lines))
    
    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol (simple API)."""
        price_data = self._prices.get(symbol)
        return price_data.price if price_data else None
    
    def get_price_data(self, symbol: str) -> Optional[PriceData]:
        """Get full price data for a symbol."""
        return self._prices.get(symbol)
    
    def get_all_prices(self) -> Dict[str, float]:
        """Get all current prices."""
        return {
            symbol: data.price
            for symbol, data in self._prices.items()
            if ':' not in symbol and data.price > 0
        }
    
    async def start(self):
        """Start the price provider."""
        self._running = True
        logger.info(f"[PRICE_PROVIDER] Starting with {len(self.symbols)} symbols...")
        
        # Start tasks (respect enabled flags to avoid unnecessary API pressure)
        tasks = [asyncio.create_task(self._health_check_loop())]

        if self.source_configs.get(PriceSource.CCXT_REST) and self.source_configs[PriceSource.CCXT_REST].enabled:
            tasks.append(asyncio.create_task(self._ccxt_polling_loop()))
        else:
            logger.info("[PRICE_PROVIDER] CCXT REST disabled - polling loop not started")

        if self.source_configs.get(PriceSource.KUCOIN_REST) and self.source_configs[PriceSource.KUCOIN_REST].enabled:
            tasks.append(asyncio.create_task(self._kucoin_polling_loop()))
        else:
            logger.info("[PRICE_PROVIDER] KuCoin REST disabled - polling loop not started")
        
        # Start Binance WebSocket if enabled
        if self.source_configs[PriceSource.BINANCE_WS].enabled:
            if self._should_use_binance_redis_feed():
                logger.info("[PRICE_PROVIDER] Binance source: using Redis feed from live_binance (no direct WS)")
            else:
                tasks.append(asyncio.create_task(self._start_binance_ws()))
        
        logger.info("[PRICE_PROVIDER] ✅ All price source tasks started")
        
        # Wait for all tasks
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("[PRICE_PROVIDER] Tasks cancelled")
    
    async def stop(self):
        """Stop the price provider."""
        self._running = False
        
        if self._binance_ws:
            await self._binance_ws.close()
        
        if self._ccxt_exchange:
            await self._ccxt_exchange.close()
        
        if self._http_session:
            await self._http_session.close()
        
        logger.info("[PRICE_PROVIDER] Stopped")


# =============================================================================
# Singleton Instance & Helper Functions
# =============================================================================

_price_provider: Optional[RealtimePriceProvider] = None


def get_price_provider() -> Optional[RealtimePriceProvider]:
    """Get the singleton price provider instance."""
    return _price_provider


def init_price_provider(
    redis_client: Any,
    symbols: List[str],
    **kwargs
) -> RealtimePriceProvider:
    """Initialize the global price provider."""
    global _price_provider
    _price_provider = RealtimePriceProvider(
        redis_client=redis_client,
        symbols=symbols,
        **kwargs
    )
    return _price_provider


async def get_realtime_price(symbol: str) -> Optional[float]:
    """Quick helper to get a price."""
    if _price_provider:
        return _price_provider.get_price(symbol)
    return None


# =============================================================================
# Standalone Runner
# =============================================================================

async def main():
    """Run price provider standalone."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Real-time Price Provider")
    parser.add_argument("--symbols", nargs="+", help="Symbols to track")
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Get symbols + config knobs (best effort) - prefer dynamic symbol manager
    main_config = None
    try:
        import config as main_config  # type: ignore
        # Dynamic symbol loading - supports hot-reload without restart
        try:
            from utils.symbol_manager import get_symbols_cached
            symbols = args.symbols or get_symbols_cached() or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        except ImportError:
            symbols = args.symbols or getattr(main_config, "SYMBOLS", None) or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    except Exception:
        symbols = args.symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    # Build source configs from config.py when available (prevents accidental REST spam)
    source_configs = None
    try:
        if main_config is not None:
            source_configs = {
                PriceSource.COINAPI_WS: SourceConfig(
                    name=PriceSource.COINAPI_WS,
                    enabled=getattr(main_config, "PRICE_SOURCE_COINAPI_ENABLED", True),
                    priority=int(getattr(main_config, "PRICE_SOURCE_COINAPI_PRIORITY", 1)),
                    stale_threshold_ms=int(getattr(main_config, "PRICE_STALE_COINAPI_MS", 2000)),
                ),
                PriceSource.BINANCE_WS: SourceConfig(
                    name=PriceSource.BINANCE_WS,
                    enabled=getattr(main_config, "PRICE_SOURCE_BINANCE_ENABLED", True),
                    priority=int(getattr(main_config, "PRICE_SOURCE_BINANCE_PRIORITY", 2)),
                    stale_threshold_ms=int(getattr(main_config, "PRICE_STALE_BINANCE_MS", 2000)),
                ),
                PriceSource.CCXT_REST: SourceConfig(
                    name=PriceSource.CCXT_REST,
                    enabled=getattr(main_config, "PRICE_SOURCE_CCXT_ENABLED", True),
                    priority=int(getattr(main_config, "PRICE_SOURCE_CCXT_PRIORITY", 3)),
                    stale_threshold_ms=int(getattr(main_config, "PRICE_STALE_CCXT_MS", 5000)),
                ),
                PriceSource.KUCOIN_REST: SourceConfig(
                    name=PriceSource.KUCOIN_REST,
                    enabled=getattr(main_config, "PRICE_SOURCE_KUCOIN_ENABLED", True),
                    priority=int(getattr(main_config, "PRICE_SOURCE_KUCOIN_PRIORITY", 4)),
                    stale_threshold_ms=int(getattr(main_config, "PRICE_STALE_KUCOIN_MS", 5000)),
                ),
                PriceSource.REDIS_CACHE: SourceConfig(
                    name=PriceSource.REDIS_CACHE,
                    enabled=getattr(main_config, "PRICE_SOURCE_CACHE_ENABLED", True),
                    priority=int(getattr(main_config, "PRICE_SOURCE_CACHE_PRIORITY", 99)),
                    stale_threshold_ms=int(getattr(main_config, "PRICE_STALE_CACHE_MS", 60000)),
                ),
            }
    except Exception:
        source_configs = None
    
    # Connect to Redis
    try:
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        r.ping()
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        return
    
    # Create and start provider
    provider = init_price_provider(
        redis_client=r,
        symbols=symbols,
        source_configs=source_configs,
        health_check_interval_sec=float(getattr(main_config, "PRICE_HEALTH_CHECK_INTERVAL_SEC", 1.0)) if main_config else 1.0,
        publish_interval_ms=int(getattr(main_config, "PRICE_PUBLISH_INTERVAL_MS", 100)) if main_config else 100,
        binance_feed_mode="auto",
    )
    
    try:
        await provider.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await provider.stop()


if __name__ == "__main__":
    asyncio.run(main())
