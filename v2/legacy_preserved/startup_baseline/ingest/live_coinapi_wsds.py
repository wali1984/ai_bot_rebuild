#!/usr/bin/env python3
"""
CoinAPI WebSocket DS Ingestor (v2.0)
=====================================
Primary low-latency microstructure feed via CoinAPI WebSocket Data Streaming (DS).

Contract:
1) Write msnap:coinapi_wsds:{SYMBOL} Redis hash with required fields
2) Update metrics:coinapi:ws:* health metrics on every message
3) Proper COINAPI_ENV handling (prod/sandbox endpoints)
4) Symbol mapping with BINANCEFTS for futures
5) Definitive INFO logs for connect/subscribe/snapshot/health
6) Watchdog for auto-reconnect if no messages for >30s

Author: WMA AI Trading System
Date: December 26, 2025 (v2.0 - Contract Compliance)
"""

import os
import sys
import json
import time
import random
import asyncio
import logging
import calendar
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set, Any, Tuple
from dataclasses import dataclass, field
from collections import deque

try:
    import websockets
    from websockets.exceptions import ConnectionClosed, WebSocketException
except ImportError:
    websockets = None
    ConnectionClosed = Exception
    WebSocketException = Exception

# EST timezone
try:
    import pytz
    EST = pytz.timezone('US/Eastern')
except ImportError:
    EST = timezone(timedelta(hours=-5))

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)


@dataclass
class MicrostructureSnapshot:
    """Microstructure snapshot data - CONTRACT COMPLIANT."""
    symbol: str
    source: str = "coinapi_wsds"
    exchange_id: str = "BINANCEFTS"
    updated_ts_ms: int = 0
    
    # Required fields (CONTRACT)
    mid_px: float = 0.0
    best_bid_px: float = 0.0
    best_ask_px: float = 0.0
    
    # Recommended fields
    best_bid_sz: float = 0.0
    best_ask_sz: float = 0.0
    spread: float = 0.0

    # Canonical aliases (backward compatible)
    # NOTE: We keep best_*_sz for existing consumers and also publish best_*_qty.
    best_bid_qty: float = 0.0
    best_ask_qty: float = 0.0
    
    # Extended fields
    microprice: float = 0.0
    book_bid_sum_5: float = 0.0
    book_ask_sum_5: float = 0.0
    imbalance_5: float = 0.0

    # Depth windows (notional, within +/- N bps of mid)
    depth_bps_10_bid_usd: float = 0.0
    depth_bps_10_ask_usd: float = 0.0
    depth_bps_10_total_usd: float = 0.0
    depth_bps_10_levels_used: int = 0
    depth_bps_25_bid_usd: float = 0.0
    depth_bps_25_ask_usd: float = 0.0
    depth_bps_25_total_usd: float = 0.0
    depth_bps_25_levels_used: int = 0
    
    # Derived scores
    churn_score: float = 0.0
    snapback_score: float = 0.0
    spoof_score: float = 0.0
    spoof_score_v1: float = 0.0  # legacy heuristic (debug)
    spoof_score_v2: float = 0.0  # v2 (tape + persistence aware)
    p_false_move: float = 0.0    # 0..1 heuristic probability of a false move
    fast_move_score: float = 0.0
    fast_move_max_1m: float = 0.0  # Rolling max over 1 minute for trainer
    fast_move_max_5m: float = 0.0  # Rolling max over 5 minutes for trainer
    fast_move_max_15m: float = 0.0  # Rolling max over 15 minutes for trainer

    # Tape / executed flow (only meaningful if `trade` subscription is enabled)
    trade_buy_notional_1s: float = 0.0
    trade_sell_notional_1s: float = 0.0
    trade_total_notional_1s: float = 0.0
    trade_imbalance_1s: float = 0.0  # (buy - sell) / total

    trade_buy_notional_5s: float = 0.0
    trade_sell_notional_5s: float = 0.0
    trade_total_notional_5s: float = 0.0
    trade_imbalance_5s: float = 0.0

    # Displayed-vs-executed divergence proxies
    impact_bps_1s: float = 0.0
    impact_per_musd_1s: float = 0.0
    
    # Quality metrics
    src_quality_score: float = 1.0
    src_staleness_ms: int = 0
    
    def to_redis_hash(self) -> Dict[str, str]:
        """Convert to Redis hash format - CONTRACT COMPLIANT."""
        return {
            # Required fields
            'updated_ts_ms': str(self.updated_ts_ms),
            'ts_ms': str(self.updated_ts_ms),
            'best_bid_px': str(self.best_bid_px),
            'best_ask_px': str(self.best_ask_px),
            'mid_px': str(self.mid_px),
            # Recommended fields
            'best_bid_sz': str(self.best_bid_sz),
            'best_ask_sz': str(self.best_ask_sz),
            'best_bid_qty': str(self.best_bid_qty),
            'best_ask_qty': str(self.best_ask_qty),
            'spread': str(self.spread),
            'source': self.source,
            'exchange_id': self.exchange_id,
            # Extended fields
            'microprice': str(self.microprice),
            'book_bid_sum_5': str(self.book_bid_sum_5),
            'book_ask_sum_5': str(self.book_ask_sum_5),
            'imbalance_5': str(self.imbalance_5),
            # Depth windows
            'depth_bps_10_bid_usd': str(self.depth_bps_10_bid_usd),
            'depth_bps_10_ask_usd': str(self.depth_bps_10_ask_usd),
            'depth_bps_10_total_usd': str(self.depth_bps_10_total_usd),
            'depth_bps_10_levels_used': str(int(self.depth_bps_10_levels_used or 0)),
            'depth_bps_25_bid_usd': str(self.depth_bps_25_bid_usd),
            'depth_bps_25_ask_usd': str(self.depth_bps_25_ask_usd),
            'depth_bps_25_total_usd': str(self.depth_bps_25_total_usd),
            'depth_bps_25_levels_used': str(int(self.depth_bps_25_levels_used or 0)),
            'churn_score': str(self.churn_score),
            'snapback_score': str(self.snapback_score),
            'spoof_score': str(self.spoof_score),
            'spoof_score_v1': str(self.spoof_score_v1),
            'spoof_score_v2': str(self.spoof_score_v2),
            'p_false_move': str(self.p_false_move),
            'fast_move_score': str(self.fast_move_score),
            'fast_move_max_1m': str(self.fast_move_max_1m),
            'fast_move_max_5m': str(self.fast_move_max_5m),
            'fast_move_max_15m': str(self.fast_move_max_15m),
            # Tape fields (may remain 0 when trade feed is disabled)
            'trade_buy_notional_1s': str(self.trade_buy_notional_1s),
            'trade_sell_notional_1s': str(self.trade_sell_notional_1s),
            'trade_total_notional_1s': str(self.trade_total_notional_1s),
            'trade_imbalance_1s': str(self.trade_imbalance_1s),
            'trade_buy_notional_5s': str(self.trade_buy_notional_5s),
            'trade_sell_notional_5s': str(self.trade_sell_notional_5s),
            'trade_total_notional_5s': str(self.trade_total_notional_5s),
            'trade_imbalance_5s': str(self.trade_imbalance_5s),
            'impact_bps_1s': str(self.impact_bps_1s),
            'impact_per_musd_1s': str(self.impact_per_musd_1s),
            'src_quality_score': str(self.src_quality_score),
            'src_staleness_ms': str(self.src_staleness_ms),
        }


@dataclass
class SymbolState:
    """Per-symbol state for microstructure calculations."""
    symbol: str
    coinapi_symbol_id: str = ""
    
    # Last snapshot
    last_snapshot: Optional[MicrostructureSnapshot] = None
    last_update_ts_ms: int = 0
    last_snapshot_log_ts: float = 0  # For rate-limited snapshot logging
    last_fast_move_log_ts: float = 0  # Rate-limit noisy fast-move INFO logs
    
    # Publish throttles (critical to prevent ingest lag → WS policy-violation disconnects)
    last_publish_ts_ms: int = 0
    last_microfeat_publish_ts_ms: int = 0
    
    # Orderbook state
    bids: List[List[float]] = field(default_factory=list)
    asks: List[List[float]] = field(default_factory=list)
    
    # Quote state
    best_bid_px: float = 0.0
    best_ask_px: float = 0.0
    best_bid_sz: float = 0.0
    best_ask_sz: float = 0.0
    
    # Trade state
    last_trade_px: float = 0.0
    last_trade_sz: float = 0.0
    last_trade_side: str = ""

    # Rolling trade buckets (executed flow confirmation; only populated if trade feed enabled)
    # Each entry is a small dict keyed by integer second: {'sec': int, 'buy_notional': float, ...}
    trade_buckets: deque = field(default_factory=lambda: deque(maxlen=30))
    
    # History for derived metrics
    imbalance_history: deque = field(default_factory=lambda: deque(maxlen=20))
    spread_history: deque = field(default_factory=lambda: deque(maxlen=20))
    tob_size_history: deque = field(default_factory=lambda: deque(maxlen=20))
    bid_sum_5_history: deque = field(default_factory=lambda: deque(maxlen=20))
    ask_sum_5_history: deque = field(default_factory=lambda: deque(maxlen=20))
    mid_price_history: deque = field(default_factory=lambda: deque(maxlen=50))  # Track mid prices for velocity
    mid_price_ts_history: deque = field(default_factory=lambda: deque(maxlen=50))  # Timestamps for velocity calc
    
    # Rolling max tracking for trainer consumption (trainer runs every 30s, needs persistence)
    fast_move_score_history: deque = field(default_factory=lambda: deque(maxlen=1800))  # ~15 min at 2 updates/sec
    fast_move_ts_history: deque = field(default_factory=lambda: deque(maxlen=1800))


class CoinAPIWebSocketDS:
    """
    CoinAPI WebSocket DS client for low-latency microstructure data.
    
    CONTRACT COMPLIANCE (v2.0):
    1. Write msnap:coinapi_wsds:{SYMBOL} with required fields
    2. Update health metrics on every message
    3. Proper environment handling
    4. Symbol mapping with BINANCEFTS
    5. Definitive INFO logs
    6. Watchdog for auto-reconnect
    """
    
    # Endpoints by environment
    ENDPOINTS = {
        'prod': {
            'ws': 'wss://ws.coinapi.io/v1/',
            'rest': 'https://rest.coinapi.io',
        },
        'sandbox': {
            'ws': 'wss://ws-sandbox.coinapi.io/v1/',
            'rest': 'https://rest-sandbox.coinapi.io',
        }
    }
    
    def __init__(
        self,
        redis_client: Any = None,
        api_key: str = "",
        env: str = "prod",
        subscribe_data_types: List[str] = None,
        max_subscribed_symbols: int = 30,
        stale_threshold_ms: int = 1500,
        log_interval_sec: int = 60,
        bytes_soft_cap_gb: float = 450,
        bytes_hard_cap_gb: float = 500,
        watchdog_timeout_sec: int = 30,
        max_reconnect_loops: int = 10,
        reconnect_window_sec: int = 300,
        exchange_id: str = "BINANCEFTS",
    ):
        self.redis = redis_client
        self.api_key = api_key or os.getenv("COINAPI_API_KEY", "")
        self.env = env or os.getenv("COINAPI_ENV", "prod")
        
        # Validate environment
        if self.env not in self.ENDPOINTS:
            logger.warning(f"[COINAPI_WSDS] Invalid env '{self.env}', defaulting to 'prod'")
            self.env = 'prod'
        
        # Get endpoints for environment
        endpoints = self.ENDPOINTS[self.env]
        self.wsds_url = os.getenv("COINAPI_WSDS_URL", endpoints['ws'])
        self.exchange_id = exchange_id or os.getenv("COINAPI_PRIMARY_EXCHANGE_ID", "BINANCEFTS")
        
        self.subscribe_data_types = subscribe_data_types or ["quote", "trade", "orderbooks"]
        # --------------------------------------------------------------------
        # PERF + HEALTH: Avoid full depth orderbook payloads unless explicitly
        # requested. Full L2 books can be massive (tens of thousands of levels)
        # and will cause ingest lag → staleness → trainer MICROSTRUCTURE_FAIL_CLOSED.
        #
        # In practice, CoinAPI "book" payloads are often far larger than what we
        # actually need. If full-book is configured but not explicitly allowed,
        # we *drop* the full-book subscription and rely on quote+trade (L1 BBO),
        # which is far lighter and keeps the microstructure feed healthy.
        #
        # Opt-out: set COINAPI_ALLOW_FULL_BOOK=true (e.g., in the environment).
        # If you want *some* depth without full L2, set COINAPI_SUBSCRIBE_DATA_TYPES
        # to include book20/book50 (we will respect those).
        # --------------------------------------------------------------------
        # Normalize + apply safety downgrades (in-place) so .env cannot accidentally re-enable heavy feeds.
        raw_types = [str(t or "").strip().lower() for t in (self.subscribe_data_types or []) if str(t or "").strip()]
        effective = list(raw_types)
        reasons = []

        # Default: do NOT allow full L2 books (too heavy, increases lag and can trigger
        # trainer MICROSTRUCTURE_FAIL_CLOSED). Opt-in explicitly if needed.
        try:
            allow_full_book = os.getenv("COINAPI_ALLOW_FULL_BOOK", "false").lower() in ("true", "1", "yes")
        except Exception:
            allow_full_book = False

        # PERF: `trade` can be extremely high volume (BTC/ETH) and is not required for the
        # majority of microstructure overlays. Make it explicit opt-in.
        try:
            allow_trade = os.getenv("COINAPI_ALLOW_TRADE", "false").lower() in ("true", "1", "yes")
        except Exception:
            allow_trade = False
        if (not allow_trade) and ("trade" in effective):
            effective = [t for t in effective if t != "trade"]
            reasons.append("trade_lag_prevention")

        # Downgrade full-book payloads unless explicitly allowed.
        full_book_tokens = ("book", "orderbooks", "orderbook")
        wants_full_book = any(t in full_book_tokens for t in effective)
        wants_topn_book = any(t.startswith("book") and t not in ("book",) for t in effective)  # book5/book20/book50
        if (not allow_full_book) and wants_full_book and (not wants_topn_book):
            effective = [t for t in effective if t not in full_book_tokens and t]
            # Ensure we keep at least quote if user accidentally configured book-only.
            if "quote" not in effective:
                effective.insert(0, "quote")
            # Add lightweight depth (top 5)
            effective.append("book5")
            reasons.append("full_book_lag_prevention")

        # Ensure non-empty & de-dupe while preserving order.
        if not effective:
            effective = ["quote", "book5"]
        seen = set()
        effective = [t for t in effective if not (t in seen or seen.add(t))]

        if effective != raw_types:
            self.subscribe_data_types = effective
            logger.warning(
                f"COINAPI_WSDS_SUBSCRIBE_TYPES_DOWNGRADED | "
                f"configured={raw_types} -> effective={self.subscribe_data_types} | "
                f"reason={'+'.join(reasons) if reasons else 'normalized'}"
            )
        self.max_subscribed_symbols = max_subscribed_symbols
        self.stale_threshold_ms = stale_threshold_ms
        self.log_interval_sec = log_interval_sec
        self.bytes_soft_cap_gb = bytes_soft_cap_gb
        self.bytes_hard_cap_gb = bytes_hard_cap_gb
        
        # Watchdog config
        self.watchdog_timeout_sec = watchdog_timeout_sec
        self.max_reconnect_loops = max_reconnect_loops
        self.reconnect_window_sec = reconnect_window_sec
        
        # Connection state
        self.ws = None
        self.connected = False
        self.subscribed_symbols: Set[str] = set()
        self._internal_to_coinapi: Dict[str, str] = {}
        self._coinapi_to_internal: Dict[str, str] = {}
        
        # Symbol state
        self._symbol_states: Dict[str, SymbolState] = {}
        
        # Metrics (CONTRACT: update on every message)
        self._last_msg_ts: float = 0
        self._bytes_received_today: int = 0
        self._msgs_received_today: int = 0
        self._last_health_log_ts: float = 0
        self._last_staleness_update_ts: float = 0
        self._connected_since_ts: float = 0
        
        # PERF: throttle heavy Redis writes (snapshot/microfeat). Keeping these unthrottled
        # can create a feedback loop: lag → server buffer → policy violation (1008) → reconnect loop.
        self._publish_min_interval_ms = int(os.getenv("COINAPI_WSDS_PUBLISH_MIN_INTERVAL_MS", "250"))  # 4 Hz/symbol
        self._microfeat_min_interval_ms = int(os.getenv("COINAPI_WSDS_MICROFEAT_MIN_INTERVAL_MS", "1000"))  # 1 Hz/symbol
        
        # PERF: batch WS health metrics writes (Redis) instead of writing on every single message.
        self._metrics_flush_interval_sec = float(os.getenv("COINAPI_WS_METRICS_FLUSH_SEC", "1.0"))
        self._metrics_last_flush_ts: float = 0.0
        self._metrics_bytes_since_flush: int = 0
        self._metrics_msgs_since_flush: int = 0
        
        # Reconnect tracking
        self._reconnect_times: deque = deque(maxlen=50)
        self._running = False
        
        logger.info(
            f"COINAPI_WS_INIT | env={self.env} | url={self.wsds_url} | "
            f"exchange_id={self.exchange_id} | data_types={self.subscribe_data_types} | "
            f"max_symbols={self.max_subscribed_symbols} | watchdog_timeout={watchdog_timeout_sec}s"
        )
    
    def _get_msnap_key(self, internal_symbol: str) -> str:
        """Get Redis key for microstructure snapshot - CONTRACT FORMAT."""
        return f"msnap:coinapi_wsds:{internal_symbol}"
    
    def _get_symbolmap_key(self, internal_symbol: str) -> str:
        """Get Redis key for symbol mapping."""
        return f"coinapi:symbolmap:{internal_symbol}"
    
    def _get_symbol_state(self, internal_symbol: str) -> SymbolState:
        """Get or create symbol state."""
        if internal_symbol not in self._symbol_states:
            coinapi_id = self._internal_to_coinapi.get(internal_symbol, "")
            self._symbol_states[internal_symbol] = SymbolState(
                symbol=internal_symbol,
                coinapi_symbol_id=coinapi_id,
            )
        return self._symbol_states[internal_symbol]
    
    def _update_health_metrics(self, bytes_received: int):
        """
        CONTRACT: Update WS health metrics in Redis on every message.
        - metrics:coinapi:ws:last_msg_ts
        - metrics:coinapi:ws:msgs_today (INCR)
        - metrics:coinapi:ws:bytes_today (INCR)
        - metrics:coinapi:shared:msgs_today (INCR) - Shared with V1 for rate limiting
        """
        now = time.time()
        self._last_msg_ts = now
        self._bytes_received_today += bytes_received
        self._msgs_received_today += 1
        self._metrics_bytes_since_flush += bytes_received
        self._metrics_msgs_since_flush += 1
        
        # Batch Redis writes to reduce per-message overhead (key for WSDS stability).
        if not self.redis:
            return
        if now - self._metrics_last_flush_ts < self._metrics_flush_interval_sec:
            return
        
        self._metrics_last_flush_ts = now
        try:
            today = datetime.now(timezone.utc).strftime("%Y%m%d")
            pipe = self.redis.pipeline()
            
            # Last message timestamp (seconds)
            pipe.set("metrics:coinapi:ws:last_msg_ts", str(now))
            
            # Daily counters (batched)
            if self._metrics_bytes_since_flush:
                pipe.incrby(f"metrics:coinapi:ws:bytes:{today}", int(self._metrics_bytes_since_flush))
            if self._metrics_msgs_since_flush:
                pipe.incrby(f"metrics:coinapi:ws:msgs:{today}", int(self._metrics_msgs_since_flush))
            pipe.set("metrics:coinapi:ws:bytes_today", str(self._bytes_received_today))
            pipe.set("metrics:coinapi:ws:msgs_today", str(self._msgs_received_today))
            
            # NOTE: shared:msgs_today is for REST; do not touch it here.
            
            # Keep daily keys around for a couple days (ops visibility)
            pipe.expire(f"metrics:coinapi:ws:bytes:{today}", 172800)
            pipe.expire(f"metrics:coinapi:ws:msgs:{today}", 172800)
            
            pipe.execute()
        except Exception as e:
            logger.debug(f"[COINAPI_WSDS] Metrics update error: {e}")
        finally:
            self._metrics_bytes_since_flush = 0
            self._metrics_msgs_since_flush = 0
    
    def _update_staleness_metrics(self):
        """
        CONTRACT: Update staleness p50/p95 every 10 seconds.
        """
        now = time.time()
        if now - self._last_staleness_update_ts < 10:
            return
        
        self._last_staleness_update_ts = now
        now_ms = int(now * 1000)
        
        staleness_values = []
        for state in self._symbol_states.values():
            if state.last_update_ts_ms > 0:
                staleness = now_ms - state.last_update_ts_ms
                if 0 <= staleness < 60000:  # Valid staleness (0-60s)
                    staleness_values.append(staleness)
        
        if not staleness_values:
            return
        
        staleness_values.sort()
        n = len(staleness_values)
        staleness_p50 = staleness_values[n // 2]
        staleness_p95 = staleness_values[min(int(n * 0.95), n - 1)]
        
        if self.redis:
            try:
                pipe = self.redis.pipeline()
                pipe.set("metrics:coinapi:ws:staleness_p50_ms", str(staleness_p50))
                pipe.set("metrics:coinapi:ws:staleness_p95_ms", str(staleness_p95))
                pipe.execute()
            except Exception as e:
                logger.debug(f"[COINAPI_WSDS] Staleness metrics error: {e}")
    
    def _map_symbol(self, internal_symbol: str) -> Optional[str]:
        """
        CONTRACT: Map internal symbol to CoinAPI symbol ID.
        Uses COINAPI_PRIMARY_EXCHANGE_ID (default BINANCEFTS).
        Logs and skips if mapping fails.
        """
        # Standard mapping depends on exchange type:
        # BINANCEFTS -> BINANCEFTS_PERP_BTC_USDT (futures)
        # BINANCE -> BINANCE_SPOT_BTC_USDT (spot)
        base = internal_symbol.replace('USDT', '').replace('1000', '')
        
        # Handle 1000XXXUSDT format (e.g., 1000SHIBUSDT)
        if internal_symbol.startswith('1000'):
            base = '1000' + base
        
        # Determine market type based on exchange ID
        if self.exchange_id == 'BINANCEFTS':
            market_type = 'PERP'
        else:
            market_type = 'SPOT'
        
        coinapi_id = f"{self.exchange_id}_{market_type}_{base}_USDT"
        
        # Store mapping in Redis for health tools
        if self.redis:
            try:
                mapping_data = {
                    'internal_symbol': internal_symbol,
                    'coinapi_symbol_id': coinapi_id,
                    'exchange_id': self.exchange_id,
                    'mapped_at': str(time.time()),
                }
                self.redis.hset(self._get_symbolmap_key(internal_symbol), mapping=mapping_data)
                self.redis.expire(self._get_symbolmap_key(internal_symbol), 86400)
            except Exception:
                pass
        
        return coinapi_id
    
    def _build_hello_message(self, symbols: List[str]) -> Dict:
        """Build DS hello message."""
        return {
            "type": "hello",
            "apikey": self.api_key,
            "heartbeat": True,
            "subscribe_data_type": self.subscribe_data_types,
            "subscribe_filter_symbol_id": symbols,
        }
    
    def _parse_timestamp(self, ts_str: str) -> int:
        """Parse CoinAPI timestamp to epoch ms."""
        now_ms = int(time.time() * 1000)
        if not ts_str:
            return now_ms

        # Performance-critical: avoid datetime.strptime per message (slow).
        # CoinAPI timestamps are ISO-8601 UTC, e.g. "2025-12-31T23:10:23.5750000Z".
        try:
            if 'T' in ts_str:
                s = ts_str.rstrip('Z')
                year = int(s[0:4])
                month = int(s[5:7])
                day = int(s[8:10])
                hour = int(s[11:13])
                minute = int(s[14:16])
                second = int(s[17:19])

                ms = 0
                if len(s) > 19 and s[19] == '.':
                    frac = s[20:]
                    # Use first 3 digits as milliseconds (pad right if shorter)
                    ms = int((frac + "000")[:3])

                epoch_sec = calendar.timegm((year, month, day, hour, minute, second))
                return int(epoch_sec * 1000 + ms)

            return int(float(ts_str) * 1000)
        except Exception:
            return now_ms
    
    def _process_quote(self, msg: Dict):
        """Process quote message."""
        symbol_id = msg.get('symbol_id', '')
        internal_symbol = self._coinapi_to_internal.get(symbol_id)
        if not internal_symbol and symbol_id:
            # Robust fallback: infer internal symbol from CoinAPI symbol_id.
            # Some feeds may emit quote/trade symbol IDs that differ slightly from our
            # initial mapping (e.g., PERP vs SPOT variants). We only trade USDT pairs.
            try:
                parts = str(symbol_id).split('_')
                if len(parts) >= 4 and parts[-1] == 'USDT':
                    inferred = f"{parts[-2]}USDT"
                    internal_symbol = inferred
                    # Cache so next message is O(1)
                    self._coinapi_to_internal[symbol_id] = inferred
            except Exception:
                internal_symbol = None
        if not internal_symbol:
            # Log a few unknowns for debugging (avoid log spam)
            try:
                c = getattr(self, "_unknown_quote_symbol_count", 0)
                if c < 3:
                    logger.warning(f"COINAPI_WS_UNKNOWN_SYMBOL | type=quote | symbol_id={symbol_id}")
                setattr(self, "_unknown_quote_symbol_count", c + 1)
            except Exception:
                pass
            return
        
        state = self._get_symbol_state(internal_symbol)
        state.best_bid_px = float(msg.get('bid_price', 0) or 0)
        state.best_ask_px = float(msg.get('ask_price', 0) or 0)
        state.best_bid_sz = float(msg.get('bid_size', 0) or 0)
        state.best_ask_sz = float(msg.get('ask_size', 0) or 0)
        # IMPORTANT: For staleness/health gating, use local receive time (now).
        # Exchange/CoinAPI timestamps can be delayed for large payloads, which
        # would make the trainer fail-closed despite the feed being alive.
        state.last_update_ts_ms = int(time.time() * 1000)
        
        self._compute_and_publish_snapshot(internal_symbol, state)
    
    def _process_trade(self, msg: Dict):
        """Process trade message."""
        symbol_id = msg.get('symbol_id', '')
        internal_symbol = self._coinapi_to_internal.get(symbol_id)
        if not internal_symbol and symbol_id:
            try:
                parts = str(symbol_id).split('_')
                if len(parts) >= 4 and parts[-1] == 'USDT':
                    inferred = f"{parts[-2]}USDT"
                    internal_symbol = inferred
                    self._coinapi_to_internal[symbol_id] = inferred
            except Exception:
                internal_symbol = None
        if not internal_symbol:
            try:
                c = getattr(self, "_unknown_trade_symbol_count", 0)
                if c < 3:
                    logger.warning(f"COINAPI_WS_UNKNOWN_SYMBOL | type=trade | symbol_id={symbol_id}")
                setattr(self, "_unknown_trade_symbol_count", c + 1)
            except Exception:
                pass
            return
        
        state = self._get_symbol_state(internal_symbol)
        trade_price = float(msg.get('price', 0) or 0)
        trade_size = float(msg.get('size', 0) or 0)
        trade_side = msg.get('taker_side', 'UNKNOWN')
        
        state.last_trade_px = trade_price
        state.last_trade_sz = trade_size
        state.last_trade_side = trade_side
        # See _process_quote: use receive time for health/staleness.
        now_ms = int(time.time() * 1000)
        state.last_update_ts_ms = now_ms

        # Maintain small rolling buckets of executed flow (buy/sell notional) for tape confirmation.
        # This is intentionally lightweight and bounded to avoid ingest lag.
        try:
            if trade_price > 0 and trade_size > 0:
                sec = int(now_ms // 1000)
                bucket = state.trade_buckets[-1] if state.trade_buckets else None
                if (not bucket) or (bucket.get('sec') != sec):
                    bucket = {
                        'sec': sec,
                        'buy_notional': 0.0,
                        'sell_notional': 0.0,
                        'buy_qty': 0.0,
                        'sell_qty': 0.0,
                        'count': 0,
                    }
                    state.trade_buckets.append(bucket)
                notional = float(trade_price) * float(trade_size)
                if str(trade_side).upper() == "BUY":
                    bucket['buy_notional'] += notional
                    bucket['buy_qty'] += float(trade_size)
                elif str(trade_side).upper() == "SELL":
                    bucket['sell_notional'] += notional
                    bucket['sell_qty'] += float(trade_size)
                bucket['count'] += 1
        except Exception:
            pass
        
        # Infer bid/ask from trade if no quote data
        if trade_price > 0 and (state.best_bid_px == 0 or state.best_ask_px == 0):
            spread = trade_price * 0.0001
            if trade_side == 'BUY':
                state.best_ask_px = trade_price
                state.best_bid_px = trade_price - spread
            elif trade_side == 'SELL':
                state.best_bid_px = trade_price
                state.best_ask_px = trade_price + spread
            else:
                state.best_bid_px = trade_price - spread / 2
                state.best_ask_px = trade_price + spread / 2
        
        self._compute_and_publish_snapshot(internal_symbol, state)
    
    def _process_book(self, msg: Dict):
        """Process orderbook message."""
        symbol_id = msg.get('symbol_id', '')
        internal_symbol = self._coinapi_to_internal.get(symbol_id)
        if not internal_symbol and symbol_id:
            try:
                parts = str(symbol_id).split('_')
                if len(parts) >= 4 and parts[-1] == 'USDT':
                    inferred = f"{parts[-2]}USDT"
                    internal_symbol = inferred
                    self._coinapi_to_internal[symbol_id] = inferred
            except Exception:
                internal_symbol = None
        if not internal_symbol:
            try:
                c = getattr(self, "_unknown_book_symbol_count", 0)
                if c < 3:
                    logger.warning(f"COINAPI_WS_UNKNOWN_SYMBOL | type=book | symbol_id={symbol_id}")
                setattr(self, "_unknown_book_symbol_count", c + 1)
            except Exception:
                pass
            return
        
        state = self._get_symbol_state(internal_symbol)
        bids = msg.get('bids', [])
        asks = msg.get('asks', [])
        
        if bids:
            if isinstance(bids[0], dict):
                state.bids = [[float(b.get('price', 0)), float(b.get('size', 0))] for b in bids[:50]]
            else:
                state.bids = [[float(b[0]), float(b[1])] for b in bids[:50] if len(b) >= 2]
            
            if state.bids:
                state.best_bid_px = state.bids[0][0]
                state.best_bid_sz = state.bids[0][1]
        
        if asks:
            if isinstance(asks[0], dict):
                state.asks = [[float(a.get('price', 0)), float(a.get('size', 0))] for a in asks[:50]]
            else:
                state.asks = [[float(a[0]), float(a[1])] for a in asks[:50] if len(a) >= 2]
            
            if state.asks:
                state.best_ask_px = state.asks[0][0]
                state.best_ask_sz = state.asks[0][1]
        
        # See _process_quote: use receive time for health/staleness.
        state.last_update_ts_ms = int(time.time() * 1000)
        self._compute_and_publish_snapshot(internal_symbol, state)
    
    def _compute_and_publish_snapshot(self, internal_symbol: str, state: SymbolState):
        """Compute microstructure metrics and publish to Redis."""
        now_ms = int(time.time() * 1000)
        
        # Throttle snapshot publishing (Redis writes) per symbol.
        if self._publish_min_interval_ms > 0 and state.last_publish_ts_ms:
            if (now_ms - state.last_publish_ts_ms) < self._publish_min_interval_ms:
                return
        state.last_publish_ts_ms = now_ms
        
        ts_to_use = state.last_update_ts_ms or now_ms
        staleness = now_ms - ts_to_use
        
        if staleness < -5000 or staleness > 3600000:
            ts_to_use = now_ms
        
        snapshot = MicrostructureSnapshot(
            symbol=internal_symbol,
            source='coinapi_wsds',
            exchange_id=self.exchange_id,
            updated_ts_ms=ts_to_use,
        )
        
        # Basic prices
        snapshot.best_bid_px = state.best_bid_px
        snapshot.best_ask_px = state.best_ask_px
        snapshot.best_bid_sz = state.best_bid_sz
        snapshot.best_ask_sz = state.best_ask_sz
        snapshot.best_bid_qty = state.best_bid_sz
        snapshot.best_ask_qty = state.best_ask_sz
        
        # CONTRACT: mid_px = (best_bid_px + best_ask_px) / 2
        if snapshot.best_bid_px > 0 and snapshot.best_ask_px > 0:
            snapshot.mid_px = (snapshot.best_bid_px + snapshot.best_ask_px) / 2
            snapshot.spread = (snapshot.best_ask_px - snapshot.best_bid_px) / snapshot.mid_px * 10000
            
            total_size = snapshot.best_bid_sz + snapshot.best_ask_sz
            if total_size > 0:
                snapshot.microprice = (
                    snapshot.best_bid_px * snapshot.best_ask_sz +
                    snapshot.best_ask_px * snapshot.best_bid_sz
                ) / total_size
        
        # Depth aggregates
        # If we aren't subscribed to full orderbooks (or depth is unavailable),
        # fall back to best bid/ask sizes as a lightweight proxy.
        bid_sum_5 = sum(b[1] for b in state.bids[:5]) if state.bids else max(0.0, float(state.best_bid_sz or 0.0))
        ask_sum_5 = sum(a[1] for a in state.asks[:5]) if state.asks else max(0.0, float(state.best_ask_sz or 0.0))
        snapshot.book_bid_sum_5 = bid_sum_5
        snapshot.book_ask_sum_5 = ask_sum_5
        
        if bid_sum_5 + ask_sum_5 > 0:
            snapshot.imbalance_5 = (bid_sum_5 - ask_sum_5) / (bid_sum_5 + ask_sum_5)

        # Depth windows (notional) for orchestrator execution gating.
        def _compute_depth_window(bps: int) -> Tuple[float, float, int]:
            if snapshot.mid_px <= 0:
                return 0.0, 0.0, 0
            thr_bid = snapshot.mid_px * (1.0 - (float(bps) / 10000.0))
            thr_ask = snapshot.mid_px * (1.0 + (float(bps) / 10000.0))
            bid_usd = 0.0
            ask_usd = 0.0
            levels = 0
            # Bids are expected best-first (desc). Break on first outside band.
            for px, qty in (state.bids or []):
                try:
                    px_f = float(px)
                    qty_f = float(qty)
                except Exception:
                    continue
                if px_f <= 0 or qty_f <= 0:
                    continue
                if px_f < thr_bid:
                    break
                bid_usd += px_f * qty_f
                levels += 1
            # Asks are expected best-first (asc). Break on first outside band.
            for px, qty in (state.asks or []):
                try:
                    px_f = float(px)
                    qty_f = float(qty)
                except Exception:
                    continue
                if px_f <= 0 or qty_f <= 0:
                    continue
                if px_f > thr_ask:
                    break
                ask_usd += px_f * qty_f
                levels += 1
            return float(bid_usd), float(ask_usd), int(levels)

        bid10, ask10, lvl10 = _compute_depth_window(10)
        snapshot.depth_bps_10_bid_usd = bid10
        snapshot.depth_bps_10_ask_usd = ask10
        snapshot.depth_bps_10_total_usd = float(bid10 + ask10)
        snapshot.depth_bps_10_levels_used = lvl10

        bid25, ask25, lvl25 = _compute_depth_window(25)
        snapshot.depth_bps_25_bid_usd = bid25
        snapshot.depth_bps_25_ask_usd = ask25
        snapshot.depth_bps_25_total_usd = float(bid25 + ask25)
        snapshot.depth_bps_25_levels_used = lvl25
        
        # Track history
        state.imbalance_history.append(snapshot.imbalance_5)
        state.spread_history.append(snapshot.spread)
        state.tob_size_history.append(snapshot.best_bid_sz + snapshot.best_ask_sz)
        state.bid_sum_5_history.append(snapshot.book_bid_sum_5)
        state.ask_sum_5_history.append(snapshot.book_ask_sum_5)
        
        # ------------------------------------------------------------------
        # Derived scores
        # ------------------------------------------------------------------
        snapshot.churn_score = self._compute_churn_score(state)
        snapshot.snapback_score = self._compute_snapback_score(state)
        snapshot.fast_move_score = self._compute_fast_move_score(state)
        
        # Compute rolling max scores for trainer consumption (trainer runs every 30s)
        snapshot.fast_move_max_1m, snapshot.fast_move_max_5m, snapshot.fast_move_max_15m = self._compute_fast_move_rolling_max(state, snapshot.fast_move_score)
        
        # ------------------------------------------------------------------
        # Tape / executed flow + impact proxies (only meaningful if trade feed enabled)
        # ------------------------------------------------------------------
        try:
            now_sec = int(now_ms // 1000)
            cutoff_1s = now_sec  # current second bucket
            cutoff_5s = now_sec - 4  # inclusive window of ~5 seconds

            buy_1s = sell_1s = buy_5s = sell_5s = 0.0
            for b in reversed(state.trade_buckets):
                sec = int(b.get('sec', 0) or 0)
                if sec < cutoff_5s:
                    break
                buy_n = float(b.get('buy_notional', 0.0) or 0.0)
                sell_n = float(b.get('sell_notional', 0.0) or 0.0)
                buy_5s += buy_n
                sell_5s += sell_n
                if sec >= cutoff_1s:
                    buy_1s += buy_n
                    sell_1s += sell_n

            snapshot.trade_buy_notional_1s = buy_1s
            snapshot.trade_sell_notional_1s = sell_1s
            snapshot.trade_total_notional_1s = buy_1s + sell_1s
            snapshot.trade_imbalance_1s = (buy_1s - sell_1s) / (snapshot.trade_total_notional_1s + 1e-9)

            snapshot.trade_buy_notional_5s = buy_5s
            snapshot.trade_sell_notional_5s = sell_5s
            snapshot.trade_total_notional_5s = buy_5s + sell_5s
            snapshot.trade_imbalance_5s = (buy_5s - sell_5s) / (snapshot.trade_total_notional_5s + 1e-9)
        except Exception:
            pass

        # Price impact vs executed volume (impact-per-volume proxy)
        try:
            impact_bps_1s = 0.0
            if snapshot.mid_px > 0 and len(state.mid_price_history) >= 3:
                target_ts = now_ms - 1000
                old_price = None
                for i in range(len(state.mid_price_ts_history) - 1, -1, -1):
                    if state.mid_price_ts_history[i] <= target_ts:
                        old_price = state.mid_price_history[i]
                        break
                if old_price and old_price > 0:
                    impact_bps_1s = abs(snapshot.mid_px - old_price) / old_price * 10000.0
            snapshot.impact_bps_1s = float(impact_bps_1s)

            if snapshot.trade_total_notional_1s > 0:
                snapshot.impact_per_musd_1s = float(snapshot.impact_bps_1s) / (float(snapshot.trade_total_notional_1s) / 1_000_000.0 + 1e-9)
            else:
                snapshot.impact_per_musd_1s = 0.0
        except Exception:
            pass

        # Spoof scores (v1 + v2) + p_false_move
        snapshot.spoof_score_v1 = self._compute_spoof_score_v1(state)
        snapshot.spoof_score_v2, snapshot.p_false_move = self._compute_spoof_score_v2(state, snapshot)
        snapshot.spoof_score = snapshot.spoof_score_v2
        squeeze_metrics = self._compute_squeeze_metrics(state, snapshot)
        
        # Quality
        snapshot.src_staleness_ms = now_ms - snapshot.updated_ts_ms
        snapshot.src_quality_score = max(0, 1.0 - snapshot.src_staleness_ms / self.stale_threshold_ms)
        
        state.last_snapshot = snapshot
        self._publish_snapshot(snapshot, state)
        
        # Write microfeat keys for proactive analyzer (squeeze, returns, etc.)
        if self._microfeat_min_interval_ms <= 0 or (now_ms - state.last_microfeat_publish_ts_ms) >= self._microfeat_min_interval_ms:
            state.last_microfeat_publish_ts_ms = now_ms
            self._publish_microfeat(internal_symbol, state, snapshot, squeeze_metrics)
    
    def _compute_churn_score(self, state: SymbolState) -> float:
        if len(state.tob_size_history) < 3:
            return 0.0
        sizes = list(state.tob_size_history)
        mean_size = sum(sizes) / len(sizes)
        if mean_size <= 0:
            return 0.0
        changes = [abs(sizes[i] - sizes[i-1]) for i in range(1, len(sizes))]
        avg_change = sum(changes) / len(changes) if changes else 0
        return min(1.0, avg_change / mean_size)
    
    def _compute_snapback_score(self, state: SymbolState) -> float:
        if len(state.imbalance_history) < 5:
            return 0.0
        imbalances = list(state.imbalance_history)
        prev_avg = sum(imbalances[-5:-2]) / 3 if len(imbalances) >= 5 else 0
        recent_avg = sum(imbalances[-3:]) / 3
        if abs(prev_avg) > 0.3 and prev_avg * recent_avg < 0:
            return min(1.0, abs(prev_avg - recent_avg))
        return 0.0
    
    def _compute_spoof_score_v1(self, state: SymbolState) -> float:
        """Legacy spoof score (fragility proxy): churn + snapback + spread spike."""
        score = self._compute_churn_score(state) * 0.4 + self._compute_snapback_score(state) * 0.4
        if len(state.spread_history) >= 5:
            spreads = list(state.spread_history)
            avg = sum(spreads[:-1]) / (len(spreads) - 1) if len(spreads) > 1 else spreads[-1]
            if avg > 0 and spreads[-1] > avg * 1.5:
                score += 0.2
        return float(min(1.0, max(0.0, score)))

    def _compute_spoof_score_v2(self, state: SymbolState, snapshot: MicrostructureSnapshot) -> Tuple[float, float]:
        """
        SpoofScore v2 (best-effort with WSDS data):

        - Keeps v1 as one component (fragility proxy)
        - Adds tape confirmation (when available)
        - Adds persistence/ghost-liquidity proxy from depth sums
        - Adds imbalance-to-impact proxy (displayed pressure vs realized impact)

        Returns: (spoof_score_v2, p_false_move)
        """
        v1 = float(getattr(snapshot, "spoof_score_v1", 0.0) or 0.0)

        # 1) Ghost liquidity proxy: rapid depth pull after a surge
        ghost = 0.0
        try:
            if len(state.bid_sum_5_history) >= 4 and len(state.ask_sum_5_history) >= 4:
                bid_hist = list(state.bid_sum_5_history)[-4:]
                ask_hist = list(state.ask_sum_5_history)[-4:]
                # Compare last step drop versus prior mean (surge->pull)
                bid_prev = float(bid_hist[-2] or 0.0)
                bid_curr = float(bid_hist[-1] or 0.0)
                ask_prev = float(ask_hist[-2] or 0.0)
                ask_curr = float(ask_hist[-1] or 0.0)
                bid_drop = max(0.0, (bid_prev - bid_curr) / (bid_prev + 1e-9))
                ask_drop = max(0.0, (ask_prev - ask_curr) / (ask_prev + 1e-9))
                # Only count it as "ghosty" if there was a surge shortly before
                bid_base = float(sum(bid_hist[:-1]) / max(1, len(bid_hist[:-1])))
                ask_base = float(sum(ask_hist[:-1]) / max(1, len(ask_hist[:-1])))
                bid_surge = 1.0 if bid_prev > (bid_base * 1.5 + 1e-9) else 0.0
                ask_surge = 1.0 if ask_prev > (ask_base * 1.5 + 1e-9) else 0.0
                ghost = max(bid_drop * bid_surge, ask_drop * ask_surge)
                ghost = float(min(1.0, ghost / 0.5))  # normalize: 50% pull ~= 1.0
        except Exception:
            ghost = 0.0

        # 2) Displayed vs executed divergence (requires non-trivial tape)
        divergence = 0.0
        tape_ok = False
        try:
            min_tape_notional_1s = float(os.getenv("MICRO_SPOOF_MIN_TAPE_NOTIONAL_1S", "20000"))
            tape_total = float(getattr(snapshot, "trade_total_notional_1s", 0.0) or 0.0)
            tape_ok = tape_total >= min_tape_notional_1s
            if tape_ok:
                disp_imb = float(getattr(snapshot, "imbalance_5", 0.0) or 0.0)
                tape_imb = float(getattr(snapshot, "trade_imbalance_1s", 0.0) or 0.0)
                if abs(disp_imb) > 0.35 and abs(tape_imb) > 0.10:
                    # If displayed pressure contradicts executed flow, spoof risk increases
                    if disp_imb * tape_imb < 0:
                        divergence = min(1.0, abs(disp_imb) + abs(tape_imb))
                # Displayed pressure with *neutral* tape is also suspicious (but weaker)
                if divergence <= 0 and abs(disp_imb) > 0.6 and abs(tape_imb) < 0.05:
                    divergence = 0.35
        except Exception:
            divergence = 0.0

        # 3) Imbalance-to-impact proxy: high displayed pressure but low realized impact
        iir = 0.0
        try:
            disp_imb = float(getattr(snapshot, "imbalance_5", 0.0) or 0.0)
            impact_bps = float(getattr(snapshot, "impact_bps_1s", 0.0) or 0.0)
            # normalize: 0 bps -> 1.0, 10 bps -> 0.0 (we only care about "no impact")
            impact_norm = min(1.0, max(0.0, impact_bps / 10.0))
            iir = min(1.0, (abs(disp_imb) / 0.8)) * (1.0 - impact_norm)
        except Exception:
            iir = 0.0

        # Regime dampener: in legitimate fast markets, reduce spoof severity (avoid false positives).
        try:
            fast_move = float(getattr(snapshot, "fast_move_score", 0.0) or 0.0)
        except Exception:
            fast_move = 0.0
        regime_factor = float(max(0.5, 1.0 - 0.35 * fast_move))  # never drop below 0.5

        # Combine (weights tuned for precision over recall).
        raw = 0.25 * v1 + 0.25 * ghost + 0.25 * divergence + 0.25 * iir
        spoof_v2 = float(min(1.0, max(0.0, raw * regime_factor)))

        # p_false_move is intentionally more conservative: requires divergence/ghost/IIR
        p_false = float(min(1.0, max(0.0, 0.35 * ghost + 0.35 * divergence + 0.30 * iir)))
        # If we don't have tape, we keep p_false_move lower (abstain rather than assert false).
        if not tape_ok:
            p_false *= 0.6

        return spoof_v2, p_false

    def _compute_spoof_score(self, state: SymbolState) -> float:
        """Back-compat alias (v1)."""
        return self._compute_spoof_score_v1(state)
    
    def _compute_fast_move_score(self, state: SymbolState) -> float:
        """Compute fast move score from live orderbook, price velocity, trade flow.

        Components (max contribution):
        1. Price velocity 1s/5s     — max 0.35  (real mid-price movement)
        2. Spread widening          — max 0.15  (liquidity withdrawal)
        3. Orderbook depth shift    — max 0.20  (bid/ask depth ratio change)
        4. Trade flow imbalance     — max 0.15  (taker buy vs sell pressure)
        5. Microprice jump          — max 0.15  (inter-snapshot price gap)
        Total cap: 1.0
        """
        score = 0.0
        current_mid = (state.best_bid_px + state.best_ask_px) / 2 if state.best_bid_px > 0 else 0
        now_ms = int(time.time() * 1000)

        if current_mid > 0:
            state.mid_price_history.append(current_mid)
            state.mid_price_ts_history.append(now_ms)

        # 1. Price velocity (1s and 5s) — raised thresholds for genuine moves
        if len(state.mid_price_history) >= 5 and current_mid > 0:
            prices = list(state.mid_price_history)
            timestamps = list(state.mid_price_ts_history)

            target_ts = now_ms - 1000
            old_price = None
            for i in range(len(timestamps) - 1, -1, -1):
                if timestamps[i] <= target_ts:
                    old_price = prices[i]
                    break
            if old_price and old_price > 0:
                velocity_1s = abs(current_mid - old_price) / old_price * 100
                if velocity_1s > 0.04:
                    score += min(0.25, (velocity_1s - 0.04) / 0.12)

            target_ts_5s = now_ms - 5000
            old_price_5s = None
            for i in range(len(timestamps) - 1, -1, -1):
                if timestamps[i] <= target_ts_5s:
                    old_price_5s = prices[i]
                    break
            if old_price_5s and old_price_5s > 0:
                velocity_5s = abs(current_mid - old_price_5s) / old_price_5s * 100
                if velocity_5s > 0.08:
                    score += min(0.10, (velocity_5s - 0.08) / 0.20)

        # 2. Spread widening vs rolling average
        if len(state.spread_history) >= 5:
            spreads = list(state.spread_history)
            avg = sum(spreads[:-1]) / max(1, len(spreads) - 1)
            if avg > 0 and spreads[-1] > avg * 2.0:
                score += min(0.15, (spreads[-1] / avg - 2.0) * 0.10)

        # 3. Orderbook depth shift — bid/ask sum ratio divergence
        if len(state.bid_sum_5_history) >= 3 and len(state.ask_sum_5_history) >= 3:
            bids = list(state.bid_sum_5_history)
            asks = list(state.ask_sum_5_history)
            cur_bid, cur_ask = max(bids[-1], 1e-9), max(asks[-1], 1e-9)
            prev_bid = max(sum(bids[:-1]) / max(1, len(bids) - 1), 1e-9)
            prev_ask = max(sum(asks[:-1]) / max(1, len(asks) - 1), 1e-9)
            ratio_now = cur_bid / cur_ask
            ratio_prev = prev_bid / prev_ask
            ratio_delta = abs(ratio_now - ratio_prev)
            if ratio_delta > 0.20:
                score += min(0.20, (ratio_delta - 0.20) / 0.40)

        # 4. Trade flow imbalance (taker buy vs sell in last 5s)
        if state.trade_buckets:
            cutoff = int(now_ms // 1000) - 5
            buy_5s = sell_5s = 0.0
            for b in reversed(state.trade_buckets):
                sec = int(b.get('sec', 0) or 0)
                if sec < cutoff:
                    break
                buy_5s += float(b.get('buy_notional', 0.0) or 0.0)
                sell_5s += float(b.get('sell_notional', 0.0) or 0.0)
            total = buy_5s + sell_5s
            if total > 0:
                flow_imb = abs(buy_5s - sell_5s) / total
                if flow_imb > 0.40:
                    score += min(0.15, (flow_imb - 0.40) / 0.40)

        # 5. Microprice jump vs last snapshot
        if state.last_snapshot and state.last_snapshot.microprice > 0 and current_mid > 0:
            jump_pct = abs(current_mid - state.last_snapshot.microprice) / state.last_snapshot.microprice * 100
            if jump_pct > 0.06:
                score += min(0.15, (jump_pct - 0.06) / 0.20)

        return min(1.0, score)
    
    def _compute_fast_move_rolling_max(self, state: SymbolState, current_score: float) -> tuple:
        """Compute rolling max fast_move_score over 1m, 5m, and 15m windows.
        
        This allows the trainer (which runs every 30s) to still see that a fast move
        occurred even if it happened 10-60 seconds ago and has since calmed down.
        
        Returns: (max_1m, max_5m, max_15m)
        """
        now_ms = int(time.time() * 1000)
        
        # Track score with timestamp
        state.fast_move_score_history.append(current_score)
        state.fast_move_ts_history.append(now_ms)
        
        # Compute max over 1 minute window
        cutoff_1m = now_ms - 60_000
        max_1m = current_score
        for i, (score, ts) in enumerate(zip(state.fast_move_score_history, state.fast_move_ts_history)):
            if ts >= cutoff_1m:
                max_1m = max(max_1m, score)
        
        # Compute max over 5 minute window
        cutoff_5m = now_ms - 300_000
        max_5m = current_score
        for i, (score, ts) in enumerate(zip(state.fast_move_score_history, state.fast_move_ts_history)):
            if ts >= cutoff_5m:
                max_5m = max(max_5m, score)
        
        # Compute max over 15 minute window
        cutoff_15m = now_ms - 900_000
        max_15m = current_score
        for i, (score, ts) in enumerate(zip(state.fast_move_score_history, state.fast_move_ts_history)):
            if ts >= cutoff_15m:
                max_15m = max(max_15m, score)
        
        # Log significant rolling max values (but not too often)
        if max_1m > 0.3 and current_score < max_1m * 0.8:
            logger.debug(f"[FAST_MOVE_PERSIST] {state.symbol} max_1m={max_1m:.2f} max_5m={max_5m:.2f} max_15m={max_15m:.2f} current={current_score:.2f}")
        
        return (max_1m, max_5m, max_15m)
    
    def _compute_squeeze_metrics(self, state: SymbolState, snapshot: MicrostructureSnapshot) -> dict:
        """Compute squeeze metrics from price velocity and orderbook data.
        
        Returns dict with squeeze indicators for proactive analyzer:
        - ret_5s, ret_15s, ret_30s, ret_60s: Price returns over windows
        - accel_5s, accel_15s: Acceleration (change in returns)
        - is_squeeze: Boolean if squeeze conditions met
        - squeeze_magnitude: 0-1 score
        - squeeze_direction: -1 (bearish), 0 (none), +1 (bullish)
        """
        metrics = {
            'ret_5s': 0.0,
            'ret_15s': 0.0,
            'ret_30s': 0.0,
            'ret_60s': 0.0,
            'accel_5s': 0.0,
            'accel_15s': 0.0,
            'volatility_30s': 0.0,
            'volatility_60s': 0.0,
            'orderbook_imbalance': snapshot.imbalance_5,
            'is_squeeze': False,
            'squeeze_direction': 0,
            'squeeze_magnitude': 0.0,
            'liq_burst_long_usd': 0.0,
            'liq_burst_short_usd': 0.0,
        }
        
        if len(state.mid_price_history) < 3:
            return metrics
        
        prices = list(state.mid_price_history)
        timestamps = list(state.mid_price_ts_history)
        current_price = prices[-1]
        now_ms = timestamps[-1] if timestamps else int(time.time() * 1000)
        
        # Calculate returns over different windows
        def get_price_at_age(target_age_ms):
            target_ts = now_ms - target_age_ms
            for i in range(len(timestamps) - 1, -1, -1):
                if timestamps[i] <= target_ts:
                    return prices[i]
            return prices[0] if prices else current_price
        
        price_5s = get_price_at_age(5000)
        price_15s = get_price_at_age(15000)
        price_30s = get_price_at_age(30000)
        price_60s = get_price_at_age(60000)
        
        if price_5s > 0:
            metrics['ret_5s'] = (current_price - price_5s) / price_5s * 100
        if price_15s > 0:
            metrics['ret_15s'] = (current_price - price_15s) / price_15s * 100
        if price_30s > 0:
            metrics['ret_30s'] = (current_price - price_30s) / price_30s * 100
        if price_60s > 0:
            metrics['ret_60s'] = (current_price - price_60s) / price_60s * 100
        
        # Calculate acceleration
        if len(prices) >= 5:
            prev_ret_5s = (prices[-3] - prices[-5]) / prices[-5] * 100 if prices[-5] > 0 else 0
            metrics['accel_5s'] = metrics['ret_5s'] - prev_ret_5s
        if len(prices) >= 10:
            prev_ret_15s = (prices[-5] - prices[-10]) / prices[-10] * 100 if prices[-10] > 0 else 0
            metrics['accel_15s'] = metrics['ret_15s'] - prev_ret_15s
        
        # Calculate volatility (std dev of returns over window)
        if len(prices) >= 10:
            returns_30s = []
            for i in range(1, min(len(prices), 10)):
                if prices[i-1] > 0:
                    returns_30s.append((prices[i] - prices[i-1]) / prices[i-1] * 100)
            if returns_30s:
                metrics['volatility_30s'] = (sum(r**2 for r in returns_30s) / len(returns_30s)) ** 0.5
        
        # Detect squeeze conditions
        squeeze_score = 0.0
        direction = 0
        
        # Strong directional move
        if abs(metrics['ret_15s']) > 0.3:  # 0.3% in 15s
            squeeze_score += 0.35
            direction = 1 if metrics['ret_15s'] > 0 else -1
        
        # Acceleration aligned with direction  
        if abs(metrics['accel_15s']) > 0.15:
            squeeze_score += 0.2
        
        # Orderbook imbalance aligned with direction
        if direction != 0:
            if (direction > 0 and snapshot.imbalance_5 > 0.3) or \
               (direction < 0 and snapshot.imbalance_5 < -0.3):
                squeeze_score += 0.2
        
        # Spread widening (stress signal)
        if len(state.spread_history) >= 3:
            spreads = list(state.spread_history)
            avg_spread = sum(spreads[:-1]) / (len(spreads) - 1) if len(spreads) > 1 else spreads[-1]
            if avg_spread > 0 and spreads[-1] > avg_spread * 1.5:
                squeeze_score += 0.15
        
        # Fast move component
        if snapshot.fast_move_score > 0.4:
            squeeze_score += 0.1
        
        metrics['squeeze_magnitude'] = min(1.0, squeeze_score)
        metrics['squeeze_direction'] = direction
        metrics['is_squeeze'] = squeeze_score >= 0.5
        
        return metrics
    
    def _publish_microfeat(self, symbol: str, state: SymbolState, snapshot: MicrostructureSnapshot, squeeze_metrics: dict):
        """Publish microfeat keys for proactive analyzer consumption.
        
        Key: microfeat:{symbol}:{tf}
        Contains: ret_5s, ret_15s, squeeze_magnitude, etc.
        """
        if self.redis is None:
            return
        
        try:
            now_ms = int(time.time() * 1000)
            
            # Write for multiple timeframes (proactive analyzer checks 1m and 5m)
            for tf in ['1m', '5m']:
                key = f"microfeat:{symbol}:{tf}"
                
                data = {
                    'ts_ms': str(now_ms),
                    'symbol': symbol,
                    'timeframe': tf,
                    'ret_5s': str(squeeze_metrics.get('ret_5s', 0)),
                    'ret_15s': str(squeeze_metrics.get('ret_15s', 0)),
                    'ret_30s': str(squeeze_metrics.get('ret_30s', 0)),
                    'ret_60s': str(squeeze_metrics.get('ret_60s', 0)),
                    'accel_5s': str(squeeze_metrics.get('accel_5s', 0)),
                    'accel_15s': str(squeeze_metrics.get('accel_15s', 0)),
                    'volatility_30s': str(squeeze_metrics.get('volatility_30s', 0)),
                    'volatility_60s': str(squeeze_metrics.get('volatility_60s', 0)),
                    'orderbook_imbalance': str(squeeze_metrics.get('orderbook_imbalance', 0)),
                    'is_squeeze': str(int(squeeze_metrics.get('is_squeeze', False))),
                    'squeeze_direction': str(squeeze_metrics.get('squeeze_direction', 0)),
                    'squeeze_magnitude': str(squeeze_metrics.get('squeeze_magnitude', 0)),
                    'liq_burst_long_usd': str(squeeze_metrics.get('liq_burst_long_usd', 0)),
                    'liq_burst_short_usd': str(squeeze_metrics.get('liq_burst_short_usd', 0)),
                    'spoof_score': str(snapshot.spoof_score),
                        'spoof_score_v1': str(getattr(snapshot, 'spoof_score_v1', 0.0) or 0.0),
                        'spoof_score_v2': str(getattr(snapshot, 'spoof_score_v2', 0.0) or 0.0),
                        'p_false_move': str(getattr(snapshot, 'p_false_move', 0.0) or 0.0),
                    'fast_move_score': str(snapshot.fast_move_score),
                    'snapback_score': str(snapshot.snapback_score),
                        'trade_total_notional_1s': str(getattr(snapshot, 'trade_total_notional_1s', 0.0) or 0.0),
                        'trade_imbalance_1s': str(getattr(snapshot, 'trade_imbalance_1s', 0.0) or 0.0),
                        'impact_bps_1s': str(getattr(snapshot, 'impact_bps_1s', 0.0) or 0.0),
                        'impact_per_musd_1s': str(getattr(snapshot, 'impact_per_musd_1s', 0.0) or 0.0),
                }
                
                self.redis.hset(key, mapping=data)
                self.redis.expire(key, 120)  # 2 minute TTL
                
        except Exception as e:
            logger.debug(f"[MICROFEAT] Redis write error for {symbol}: {e}")
    
    def _publish_snapshot(self, snapshot: MicrostructureSnapshot, state: SymbolState):
        """Publish snapshot to Redis with rate-limited logging."""
        if self.redis is None:
            return
        
        try:
            key = self._get_msnap_key(snapshot.symbol)
            self.redis.hset(key, mapping=snapshot.to_redis_hash())
            self.redis.expire(key, 300)  # 5 minute TTL - survives reconnection attempts
            
            # CONTRACT: Rate-limited snapshot logging (every 10s per symbol)
            now = time.time()
            if now - state.last_snapshot_log_ts >= 10:
                state.last_snapshot_log_ts = now
                # Include depth info in log
                depth_status = "DEPTH_OK" if (snapshot.book_bid_sum_5 > 0 and snapshot.book_ask_sum_5 > 0) else "NO_DEPTH"
                logger.info(
                    f"COINAPI_WS_SNAPSHOT_WRITE | {snapshot.symbol} | {depth_status} | "
                    f"mid_px={snapshot.mid_px:.4f} | bid={snapshot.best_bid_px:.4f} | ask={snapshot.best_ask_px:.4f} | "
                    f"bid_sum_5={snapshot.book_bid_sum_5:.2f} | ask_sum_5={snapshot.book_ask_sum_5:.2f} | "
                    f"imbalance={snapshot.imbalance_5:.4f} | staleness_ms={snapshot.src_staleness_ms}"
                )
        except Exception as e:
            logger.debug(f"[COINAPI_WSDS] Redis publish error: {e}")
    
    def _log_health(self):
        """CONTRACT: Log health summary every 60s."""
        now = time.time()
        if now - self._last_health_log_ts < self.log_interval_sec:
            return
        
        self._last_health_log_ts = now
        now_ms = int(now * 1000)
        
        # Compute staleness
        staleness_values = []
        for state in self._symbol_states.values():
            if state.last_update_ts_ms > 0:
                staleness = now_ms - state.last_update_ts_ms
                if 0 <= staleness < 60000:
                    staleness_values.append(staleness)
        
        staleness_p50 = staleness_p95 = 0
        if staleness_values:
            staleness_values.sort()
            n = len(staleness_values)
            staleness_p50 = staleness_values[n // 2]
            staleness_p95 = staleness_values[min(int(n * 0.95), n - 1)]
        
        last_msg_age = now - self._last_msg_ts if self._last_msg_ts > 0 else -1
        bytes_gb = self._bytes_received_today / (1024 ** 3)
        
        # Compute depth readiness (how many symbols have depth data)
        depth_ready_count = 0
        for state in self._symbol_states.values():
            if state.bids and state.asks and len(state.bids) >= 5 and len(state.asks) >= 5:
                depth_ready_count += 1
        
        # Get message type counts
        msg_counts = getattr(self, '_msg_type_counts', {'quote': 0, 'trade': 0, 'book': 0})
        
        logger.info(
            f"COINAPI_HEALTH | ws_connected={self.connected} | "
            f"subscribed_symbols_count={len(self.subscribed_symbols)} | "
            f"depth_ready={depth_ready_count}/{len(self._symbol_states)} | "
            f"quotes={msg_counts.get('quote', 0)} | books={msg_counts.get('book', 0)} | trades={msg_counts.get('trade', 0)} | "
            f"msgs_today={self._msgs_received_today} | "
            f"last_msg_age_sec={last_msg_age:.1f} | "
            f"staleness_p50_ms={staleness_p50} | staleness_p95_ms={staleness_p95} | "
            f"bytes_today_gb={bytes_gb:.3f}"
        )
    
    async def _watchdog(self):
        """
        CONTRACT: Watchdog - reconnect if no messages for >30s.
        Exit nonzero if too many reconnect loops.
        """
        while self._running:
            await asyncio.sleep(5)
            
            if not self.connected:
                continue
            
            now = time.time()
            last_msg_age = now - self._last_msg_ts if self._last_msg_ts > 0 else 0
            
            if last_msg_age > self.watchdog_timeout_sec:
                logger.warning(
                    f"COINAPI_WS_WATCHDOG | no_msg_for={last_msg_age:.1f}s > {self.watchdog_timeout_sec}s | "
                    f"forcing_reconnect"
                )
                if self.ws:
                    try:
                        await self.ws.close()
                    except Exception:
                        pass
                self.connected = False
                self._reconnect_times.append(now)
        
        # Check for reconnect loops
        recent_reconnects = sum(1 for t in self._reconnect_times if now - t < self.reconnect_window_sec)
        if recent_reconnects >= self.max_reconnect_loops:
            logger.error(
                f"COINAPI_WS_RECONNECT_LOOP | {recent_reconnects} reconnects in {self.reconnect_window_sec}s | "
                f"exiting nonzero for systemd restart"
            )
            sys.exit(1)
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message."""
        # PERF: avoid encoding to compute byte length; approximate is enough for metrics.
        try:
            self._update_health_metrics(len(message) if isinstance(message, (str, bytes, bytearray)) else 0)
        except Exception:
            self._update_health_metrics(0)
        
        try:
            msg = json.loads(message)
            msg_type = msg.get('type', '')
            
            # Track message type counts
            if not hasattr(self, '_msg_type_counts'):
                self._msg_type_counts = {'quote': 0, 'trade': 0, 'book': 0, 'heartbeat': 0, 'other': 0}
            
            if msg_type == 'quote':
                self._msg_type_counts['quote'] += 1
                self._process_quote(msg)
            elif msg_type == 'trade':
                self._msg_type_counts['trade'] += 1
                self._process_trade(msg)
            elif msg_type in ('book', 'book5', 'book20', 'book50', 'orderbooks', 'orderbook', 'l2'):
                self._msg_type_counts['book'] += 1
                self._process_book(msg)
                # Log first few book messages for debugging (include is_snapshot)
                if self._msg_type_counts['book'] <= 10:
                    is_snapshot = msg.get('is_snapshot', False)
                    logger.info(f"[COINAPI_WS] ORDER_BOOK received | type={msg_type} | is_snapshot={is_snapshot} | "
                               f"symbol={msg.get('symbol_id', '?')} | bids={len(msg.get('bids', []))} | asks={len(msg.get('asks', []))}")
            elif msg_type in ('heartbeat', 'hearbeat'):  # CoinAPI typo in 'hearbeat'
                self._msg_type_counts['heartbeat'] += 1
            elif msg_type == 'error':
                logger.error(f"COINAPI_WS_ERROR | {msg.get('message', '')}")
            elif msg_type == 'exchangeRate':
                pass
            else:
                self._msg_type_counts['other'] += 1
                # Log unknown types to understand what we're getting
                if self._msg_type_counts['other'] <= 10:
                    logger.warning(f"[COINAPI_WSDS] Unknown message type: {msg_type} | keys={list(msg.keys())[:5]}")
            
        except json.JSONDecodeError as e:
            logger.debug(f"[COINAPI_WSDS] JSON parse error: {e}")
        except Exception as e:
            logger.error(f"[COINAPI_WSDS] Message handling error: {e}")
        
        # Periodic updates
        self._update_staleness_metrics()
        self._log_health()
    
    async def connect(self, symbols_to_subscribe: List[str]):
        """Connect to WebSocket and subscribe to symbols."""
        if not self.api_key:
            logger.error("COINAPI_WS_CONNECT_FAIL | reason=no_api_key")
            return
        
        # Map symbols
        coinapi_symbols = []
        mapped_count = 0
        skipped_count = 0
        
        for sym in symbols_to_subscribe[:self.max_subscribed_symbols]:
            coinapi_id = self._map_symbol(sym)
            if coinapi_id:
                coinapi_symbols.append(coinapi_id)
                self._internal_to_coinapi[sym] = coinapi_id
                self._coinapi_to_internal[coinapi_id] = sym
                mapped_count += 1
            else:
                logger.warning(f"COINAPI_WS_SYMBOL_MAP_FAIL | symbol={sym}")
                skipped_count += 1
        
        if not coinapi_symbols:
            logger.error("COINAPI_WS_SUBSCRIBE_FAIL | reason=no_valid_symbols")
            return
        
        logger.info(
            f"COINAPI_WS_SYMBOL_MAP | mapped={mapped_count} | skipped={skipped_count} | "
            f"exchange_id={self.exchange_id}"
        )
        
        hello_msg = self._build_hello_message(coinapi_symbols)
        
        try:
            logger.info(f"COINAPI_WS_CONNECTING | url={self.wsds_url} | env={self.env}")
            
            async with websockets.connect(
                self.wsds_url,
                # IMPORTANT: CoinAPI streams frequent messages (and we request `heartbeat=true`),
                # and we already have an application watchdog. Client-side WS keepalive pings
                # can cause false disconnects ("keepalive ping timeout") under brief stalls.
                # Disable automatic ping/pong and rely on message + watchdog freshness.
                ping_interval=None,
                close_timeout=5,
                max_size=10 * 1024 * 1024,  # 10MB max frame size (was default 1MB)
                max_queue=1024,  # Increase message queue size
            ) as ws:
                self.ws = ws
                self.connected = True
                self._connected_since_ts = time.time()
                self._last_msg_ts = time.time()
                self.subscribed_symbols = set(coinapi_symbols)
                
                # Send hello
                await ws.send(json.dumps(hello_msg))
                
                logger.info(
                    f"COINAPI_WS_CONNECT_OK | subscribed={len(coinapi_symbols)} | "
                    f"data_types={self.subscribe_data_types}"
                )
                logger.info(
                    f"COINAPI_WS_SUBSCRIBE_OK | symbols={list(self._internal_to_coinapi.keys())[:5]}... | "
                    f"total={len(coinapi_symbols)}"
                )
                
                # Update Redis with connection status
                if self.redis:
                    try:
                        self.redis.set("metrics:coinapi:ws:connected", "1")
                        self.redis.set("metrics:coinapi:ws:connected_ts", str(self._connected_since_ts))
                        # Also update last_connected_ts for promotion controller compatibility
                        self.redis.set("metrics:coinapi:ws:last_connected_ts", str(self._connected_since_ts))
                        self.redis.set("metrics:coinapi:ws:subscribed_count", str(len(coinapi_symbols)))
                    except Exception:
                        pass
                
                # Message loop
                async for message in ws:
                    if not self._running:
                        break
                    
                    # Log message size for debugging (only large messages)
                    msg_size = len(message) if isinstance(message, (str, bytes)) else 0
                    if msg_size > 500_000:  # Log messages > 500KB
                        logger.info(f"COINAPI_WS_LARGE_MSG | size={msg_size/1024/1024:.2f}MB | "
                                  f"type={type(message).__name__}")
                    
                    await self._handle_message(message)
                    
        except ConnectionClosed as e:
            logger.warning(f"COINAPI_WS_CONNECT_FAIL | reason=connection_closed | detail={e}")
        except WebSocketException as e:
            logger.error(f"COINAPI_WS_CONNECT_FAIL | reason=websocket_error | detail={e}")
        except Exception as e:
            logger.error(f"COINAPI_WS_CONNECT_FAIL | reason=exception | detail={e}")
        finally:
            self.connected = False
            self._connected_since_ts = 0
            self.ws = None
            if self.redis:
                try:
                    self.redis.set("metrics:coinapi:ws:connected", "0")
                except Exception:
                    pass
    
    async def run(self, symbols: List[str]):
        """Run with automatic reconnection and watchdog."""
        self._running = True
        backoff_schedule = [1, 2, 5, 10, 30, 60]
        reconnect_attempt = 0
        
        # Start watchdog
        watchdog_task = asyncio.create_task(self._watchdog())
        
        try:
            while self._running:
                await self.connect(symbols)
                
                if not self._running:
                    break
                
                # Reconnect with backoff
                backoff = backoff_schedule[min(reconnect_attempt, len(backoff_schedule) - 1)]
                jitter = random.uniform(0, backoff * 0.3)
                wait_time = backoff + jitter
                
                reconnect_attempt += 1
                self._reconnect_times.append(time.time())
                
                logger.info(f"COINAPI_WS_RECONNECT | attempt={reconnect_attempt} | wait={wait_time:.1f}s")
                await asyncio.sleep(wait_time)
        finally:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass
    
    def stop(self):
        """Stop the WebSocket client."""
        self._running = False
        if self.ws:
            asyncio.create_task(self.ws.close())


def run_coinapi_wsds(symbols: List[str] = None):
    """
    Run CoinAPI WebSocket DS ingestor.
    
    CONTRACT: Fail-fast if COINAPI_API_KEY missing.
    """
    import redis as redis_lib
    
    # Load config
    try:
        from config import (
            ENABLE_COINAPI, COINAPI_API_KEY, COINAPI_ENV,
            COINAPI_SUBSCRIBE_DATA_TYPES, COINAPI_MAX_SUBSCRIBED_SYMBOLS,
            COINAPI_STALE_WS_MS, COINAPI_LOG_EVERY_SEC,
            COINAPI_WS_BYTES_DAILY_SOFT_CAP_GB, COINAPI_WS_BYTES_DAILY_HARD_CAP_GB,
            COINAPI_PRIMARY_EXCHANGE_ID,
            COINAPI_ENABLE_WEBSOCKET,
        )
        
        # Dynamic symbol loading - supports hot-reload without restart
        try:
            from utils.symbol_manager import get_symbols_cached
            SYMBOLS = get_symbols_cached()
        except ImportError:
            from config import SYMBOLS
    except ImportError as e:
        logger.error(f"[COINAPI_WSDS] Config import error: {e}")
        return
    
    if not ENABLE_COINAPI:
        logger.info("[COINAPI_WSDS] CoinAPI disabled (ENABLE_COINAPI=false)")
        return
    
    if not COINAPI_ENABLE_WEBSOCKET:
        logger.info("[COINAPI_WSDS] WebSocket disabled (COINAPI_ENABLE_WEBSOCKET=false)")
        return
    
    # CONTRACT: Fail-fast if no API key
    if not COINAPI_API_KEY:
        logger.error("COINAPI_WS_CONNECT_FAIL | reason=COINAPI_API_KEY_MISSING")
        logger.error("[COINAPI_WSDS] Set COINAPI_API_KEY in .env to enable microstructure feed")
        sys.exit(1)
    
    logger.info(f"[COINAPI_WSDS] API Key: {COINAPI_API_KEY[:8]}...{COINAPI_API_KEY[-4:]}")
    logger.info(f"[COINAPI_WSDS] Environment: {COINAPI_ENV}")
    logger.info(f"[COINAPI_WSDS] Exchange ID: {COINAPI_PRIMARY_EXCHANGE_ID}")
    
    # Get symbols
    if symbols is None:
        symbols = SYMBOLS
    
    # Connect to Redis
    redis_client = redis_lib.Redis(host='localhost', port=6379, decode_responses=False)
    
    # Create client
    client = CoinAPIWebSocketDS(
        redis_client=redis_client,
        api_key=COINAPI_API_KEY,
        env=COINAPI_ENV,
        subscribe_data_types=COINAPI_SUBSCRIBE_DATA_TYPES,
        max_subscribed_symbols=COINAPI_MAX_SUBSCRIBED_SYMBOLS,
        stale_threshold_ms=COINAPI_STALE_WS_MS,
        log_interval_sec=COINAPI_LOG_EVERY_SEC,
        bytes_soft_cap_gb=COINAPI_WS_BYTES_DAILY_SOFT_CAP_GB,
        bytes_hard_cap_gb=COINAPI_WS_BYTES_DAILY_HARD_CAP_GB,
        exchange_id=COINAPI_PRIMARY_EXCHANGE_ID,
    )
    
    # Run
    asyncio.run(client.run(symbols))


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
    run_coinapi_wsds()
