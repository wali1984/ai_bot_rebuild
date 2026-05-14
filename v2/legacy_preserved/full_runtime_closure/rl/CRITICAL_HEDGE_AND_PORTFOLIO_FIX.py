"""
CRITICAL FIX: Multi-Account Portfolio Tracking & Safe Hedge Module
====================================================================

This patch fixes the death spiral issue by:
1. Tracking BOTH trader accounts (primary + asjad) 
2. Implementing safe hedge logic with proper thresholds
3. Ensuring rewards/penalties consider full portfolio state
4. Injecting portfolio data into MASA workers for training

CRITICAL CHANGES:
- Prevents whipsaw pattern with higher confidence requirements (0.85 minimum)
- Tracks combined portfolio: equity, PNL, margin, positions
- Historical PNL tracking (1d, 7d, 30d) for context-aware decisions
- Emergency circuit breaker for rapid losses

Author: AI Assistant
Date: 2025-12-22
Status: PRODUCTION CRITICAL - 50% PORTFOLIO LOSS MITIGATION
"""

import os
import logging
from typing import Dict, Any, Optional, List, Tuple
from binance.client import Client

# Disable WebSocket helpers in trainer mode to avoid blocking initialization
PORTFOLIO_DISABLE_WS = os.getenv("PORTFOLIO_DISABLE_WS", "1").lower() in ("1", "true", "yes")
if PORTFOLIO_DISABLE_WS:
    BinanceWebSocketHelper = None
else:
    try:
        from binance_websocket import BinanceWebSocketHelper
    except ImportError:
        BinanceWebSocketHelper = None
from datetime import datetime, timedelta
import time
import numpy as np
from collections import deque, defaultdict
import os

from utils.binance_rate_limiter import BinanceRateLimiter
from config import SYMBOLS

logger = logging.getLogger(__name__)


class MultiAccountPortfolioTracker:
    """
    Tracks BOTH Binance accounts for complete portfolio awareness.
    Reads position data from Redis (published by traders) instead of direct API calls.
    Provides combined metrics for training/reward calculations.
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.primary_client: Optional[Client] = None
        self.asjad_client: Optional[Client] = None
        self.brother_client: Optional[Client] = None  # Alias for asjad
        
        # Combined portfolio state
        self.combined_state = {
            'total_equity': 0.0,
            'total_available_margin': 0.0,
            'total_used_margin': 0.0,
            'margin_ratio': 0.0,
            'total_unrealized_pnl': 0.0,
            'position_count': 0,
            'accounts': {}
        }
        
        # Cache for leverage per symbol (since Binance doesn't return it in positions)
        self.leverage_cache = {}
        self.leverage_cache_ttl = int(os.getenv("LEVERAGE_CACHE_SECONDS", "3600"))  # default 1h cache

        # Realized PnL tracking (per account and combined)
        self._income_cache: Dict[str, Dict[str, float]] = {}
        self._last_income_fetch: Dict[str, float] = {}
        self.income_fetch_interval = int(os.getenv("REALIZED_PNL_FETCH_SECONDS", "600"))  # 10 min - avoid hammering REST (weight=30)

        # Trade history (fetched once per restart per account)
        self._trade_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._trade_fetch_fetched: Dict[str, bool] = {}
        self._trade_cache_ts: Dict[str, float] = {}
        self.max_trade_history_days = int(os.getenv("TRADE_HISTORY_DAYS", "1"))
        self.trade_history_refresh_seconds = int(os.getenv("TRADE_HISTORY_REFRESH_SECONDS", "86400"))
        self.max_trades_per_account = int(os.getenv("TRADE_HISTORY_MAX_TRADES", "500"))
        self.max_trades_per_account_ctx = int(os.getenv("TRADE_HISTORY_MAX_TRADES_CTX", "200"))

        # Order history (fetched once per restart per account)
        self._order_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._order_fetch_fetched: Dict[str, bool] = {}
        self._order_cache_ts: Dict[str, float] = {}
        self.max_order_history_days = int(os.getenv("ORDER_HISTORY_DAYS", "30"))
        self.order_history_refresh_seconds = int(os.getenv("ORDER_HISTORY_REFRESH_SECONDS", "86400"))
        self.max_orders_per_account = int(os.getenv("ORDER_HISTORY_MAX_ORDERS", "500"))
        self.max_orders_per_account_ctx = int(os.getenv("ORDER_HISTORY_MAX_ORDERS_CTX", "200"))

        # Shared rate limiter to keep REST calls under IP quota across accounts
        safe_max = int(os.getenv("BINANCE_API_SAFE_CALLS_PER_MINUTE", "300"))
        safe_burst = int(os.getenv("BINANCE_API_BURST", "30"))
        self.rate_limiter = BinanceRateLimiter(max_per_minute=safe_max, burst=safe_burst)
        
        # Historical PNL tracking
        self.pnl_history_1d = deque(maxlen=1440)   # 1 minute snapshots for 24h
        self.pnl_history_7d = deque(maxlen=10080)  # 1 minute snapshots for 7d
        self.pnl_history_30d = deque(maxlen=43200) # 1 minute snapshots for 30d
        
        self.last_sync_time = 0
        self.sync_interval = 60  # Sync every 60 seconds

        # Optional websocket helpers per account to reduce REST load
        self.primary_ws_helper = None
        self.asjad_ws_helper = None
        self.ws_positions_stale_after = int(os.getenv("WS_POSITIONS_STALE_SECONDS", "30"))
        
        logger.info("🔄 Multi-account portfolio tracker initialized")
    
    def initialize_clients(self, primary_api_key: str, primary_api_secret: str,
                          asjad_api_key: str, asjad_api_secret: str):
        """Initialize both Binance clients"""
        try:
            self.primary_client = Client(
                api_key=primary_api_key,
                api_secret=primary_api_secret
            )
            logger.info("✅ Primary account client initialized (WAJID)")
            
            self.asjad_client = Client(
                api_key=asjad_api_key,
                api_secret=asjad_api_secret
            )
            logger.info("✅ Asjad account client initialized (ASJAD)")
            
            # Initialize websocket helpers to reduce REST usage
            if BinanceWebSocketHelper:
                try:
                    self.primary_ws_helper = BinanceWebSocketHelper(self.primary_client, SYMBOLS)
                    logger.info("🌐 Primary websocket helper initialized for portfolio tracker")
                except Exception as ws_err:
                    logger.warning(f"⚠️ Failed to init primary websocket helper: {ws_err}")
                    self.primary_ws_helper = None

                try:
                    self.asjad_ws_helper = BinanceWebSocketHelper(self.asjad_client, SYMBOLS)
                    logger.info("🌐 Asjad websocket helper initialized for portfolio tracker")
                except Exception as ws_err:
                    logger.warning(f"⚠️ Failed to init Asjad websocket helper: {ws_err}")
                    self.asjad_ws_helper = None
            
            # Initial sync
            self.sync_all_accounts()
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize multi-account clients: {e}")
            raise
    
    def _get_symbol_leverage(self, client: Client, symbol: str) -> float:
        """Get leverage for a symbol, with caching to avoid API spam"""
        cache_key = f"{id(client)}_{symbol}"
        
        # Check cache first (valid for 5 minutes)
        if cache_key in self.leverage_cache:
            cached_lev, cached_time = self.leverage_cache[cache_key]
            if time.time() - cached_time < self.leverage_cache_ttl:
                return cached_lev
        
        # Fetch from Binance
        try:
            self.rate_limiter.maybe_sleep()
            position_info = client.futures_position_information(symbol=symbol)
            if position_info and len(position_info) > 0:
                leverage = float(position_info[0].get('leverage', 1))
                self.leverage_cache[cache_key] = (leverage, time.time())
                return leverage
        except Exception as e:
            logger.debug(f"Could not fetch leverage for {symbol}: {e}")
        
        return 1.0  # Default to 1x if unavailable
    
    def _fetch_account_state_from_redis(self, account_id: str, account_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch account state from Redis (published by traders via WebSocket).
        This avoids direct API calls and uses real-time data from trader processes.
        """
        if not self.redis:
            logger.warning(f"⚠️ Redis not available, cannot fetch {account_name} state")
            return None
        
        try:
            import json
            # Get all position keys for this account from Redis
            # Pattern: wma:{account_id}:positions:{SYMBOL}
            pattern = f"wma:{account_id}:positions:*"
            position_keys = self.redis.keys(pattern)
            
            active_positions = []
            total_unrealized_pnl = 0.0
            total_used_margin = 0.0
            
            for key in position_keys:
                try:
                    pos_data = self.redis.hgetall(key)
                    if not pos_data:
                        continue
                    
                    symbol = pos_data.get(b'symbol' if isinstance(list(pos_data.keys())[0], bytes) else 'symbol', b'').decode() if isinstance(pos_data.get(b'symbol' if isinstance(list(pos_data.keys())[0], bytes) else 'symbol'), bytes) else pos_data.get('symbol', '')
                    if not symbol:
                        continue
                    
                    # Check both LONG and SHORT legs (hedge mode)
                    has_long_key = b'has_long' if isinstance(list(pos_data.keys())[0], bytes) else 'has_long'
                    has_short_key = b'has_short' if isinstance(list(pos_data.keys())[0], bytes) else 'has_short'
                    has_long = pos_data.get(has_long_key, b'False').decode() if isinstance(pos_data.get(has_long_key), bytes) else pos_data.get(has_long_key, 'False')
                    has_short = pos_data.get(has_short_key, b'False').decode() if isinstance(pos_data.get(has_short_key), bytes) else pos_data.get(has_short_key, 'False')
                    
                    # Parse LONG leg if exists
                    if has_long == 'True':
                        long_key = b'long' if isinstance(list(pos_data.keys())[0], bytes) else 'long'
                        long_data_raw = pos_data.get(long_key, b'{}').decode() if isinstance(pos_data.get(long_key), bytes) else pos_data.get(long_key, '{}')
                        if long_data_raw:
                            long_data = json.loads(long_data_raw)
                            if long_data.get('has_position') and float(long_data.get('size', 0)) > 0:
                                active_positions.append({
                                    'symbol': symbol,
                                    'side': 'LONG',
                                    'position_side': 'LONG',
                                    'size': float(long_data.get('size', 0)),
                                    'entry_price': float(long_data.get('entry_price', 0)),
                                    'mark_price': float(long_data.get('mark_price', 0)),
                                    'unrealized_pnl': float(long_data.get('unrealized_pnl', 0)),
                                    'pnl_pct': float(long_data.get('pnl_pct', 0)),
                                    'leverage': float(long_data.get('leverage', 1))
                                })
                                total_unrealized_pnl += float(long_data.get('unrealized_pnl', 0))
                                total_used_margin += float(long_data.get('margin_used', 0))
                    
                    # Parse SHORT leg if exists
                    if has_short == 'True':
                        short_key = b'short' if isinstance(list(pos_data.keys())[0], bytes) else 'short'
                        short_data_raw = pos_data.get(short_key, b'{}').decode() if isinstance(pos_data.get(short_key), bytes) else pos_data.get(short_key, '{}')
                        if short_data_raw:
                            short_data = json.loads(short_data_raw)
                            if short_data.get('has_position') and float(short_data.get('size', 0)) > 0:
                                active_positions.append({
                                    'symbol': symbol,
                                    'side': 'SHORT',
                                    'position_side': 'SHORT',
                                    'size': float(short_data.get('size', 0)),
                                    'entry_price': float(short_data.get('entry_price', 0)),
                                    'mark_price': float(short_data.get('mark_price', 0)),
                                    'unrealized_pnl': float(short_data.get('unrealized_pnl', 0)),
                                    'pnl_pct': float(short_data.get('pnl_pct', 0)),
                                    'leverage': float(short_data.get('leverage', 1))
                                })
                                total_unrealized_pnl += float(short_data.get('unrealized_pnl', 0))
                                total_used_margin += float(short_data.get('margin_used', 0))
                    
                except Exception as pos_err:
                    logger.debug(f"Failed to parse position from {key}: {pos_err}")
                    continue
            
            # Get account balance from trader's published data
            # Pattern: trader:{account_id}:balance
            balance_key = f"trader:{account_id}:balance"
            balance_data = self.redis.hgetall(balance_key)
            
            total_wallet_balance = 0.0
            total_margin_balance = 0.0
            available_balance = 0.0
            
            if balance_data:
                balance_key_type = b'balance' if isinstance(list(balance_data.keys())[0], bytes) else 'balance'
                margin_key_type = b'margin_balance' if isinstance(list(balance_data.keys())[0], bytes) else 'margin_balance'
                avail_key_type = b'available' if isinstance(list(balance_data.keys())[0], bytes) else 'available'
                
                total_wallet_balance = float(balance_data.get(balance_key_type, 0))
                total_margin_balance = float(balance_data.get(margin_key_type, total_wallet_balance))
                available_balance = float(balance_data.get(avail_key_type, 0))
            
            # Calculate margin ratio
            margin_ratio = 0.0
            if total_margin_balance > 0:
                # Approximate margin ratio based on used margin
                margin_ratio = (total_used_margin / total_margin_balance * 100) if total_margin_balance > 0 else 0
            
            logger.debug(f"📊 [REDIS_PORTFOLIO] {account_name}: {len(active_positions)} positions, equity=${total_margin_balance:.2f}, unrealized_pnl=${total_unrealized_pnl:.2f}")
            
            return {
                'account_name': account_name,
                'total_wallet_balance': total_wallet_balance,
                'equity': total_margin_balance,
                'available_balance': available_balance,
                'used_margin': total_used_margin,
                'margin_ratio': margin_ratio,
                'unrealized_pnl': total_unrealized_pnl,
                'positions': active_positions,
                'position_count': len(active_positions),
                'realized_pnl_1d': 0.0,  # TODO: Add realized PnL to trader's Redis publish
                'realized_pnl_7d': 0.0,
                'realized_pnl_30d': 0.0,
                'timestamp': time.time()
            }
            
        except Exception as e:
            import traceback
            logger.error(f"❌ Failed to fetch {account_name} from Redis: {e}")
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            return None
    
    def _fetch_account_state(self, client: Client, account_name: str, ws_helper: Optional[BinanceWebSocketHelper] = None) -> Dict[str, Any]:
        """Fetch complete account state including all portfolio metrics"""
        try:
            if not client:
                logger.warning(f"⚠️ {account_name} client not initialized, skipping fetch")
                return None
            
            self.rate_limiter.maybe_sleep()
            account_info = client.futures_account()
            self.rate_limiter.maybe_sleep()

            # Prefer websocket positions when fresh; fallback to REST
            positions: List[Dict[str, Any]] = []
            ws_ts = 0.0
            if ws_helper:
                try:
                    positions = ws_helper.get_positions()
                    ws_ts = ws_helper.get_positions_timestamp()
                except Exception:
                    positions, ws_ts = [], 0.0

            ws_fresh = positions and ws_ts and (time.time() - ws_ts) < self.ws_positions_stale_after

            if not ws_fresh:
                self.rate_limiter.maybe_sleep()
                positions = client.futures_position_information()
                if ws_helper:
                    try:
                        ws_helper.update_positions_from_rest(positions)
                    except Exception:
                        pass
            
            # Extract critical metrics
            total_wallet_balance = float(account_info.get('totalWalletBalance', 0))
            total_margin_balance = float(account_info.get('totalMarginBalance', 0))  # Equity
            available_balance = float(account_info.get('availableBalance', 0))
            total_unrealized_pnl = float(account_info.get('totalUnrealizedProfit', 0))
            total_position_margin = float(account_info.get('totalPositionInitialMargin', 0))
            total_maint_margin = float(account_info.get('totalMaintMargin', 0))
            
            # Calculate margin ratio (Binance formula)
            margin_ratio = (total_maint_margin / total_margin_balance * 100) if total_margin_balance > 0 else 0
            
            # Process positions
            active_positions = []
            for pos in positions:
                position_amt = float(pos.get('positionAmt') or pos.get('pa') or 0)
                if position_amt != 0:
                    symbol = pos.get('symbol') or pos.get('s')
                    entry_price = float(pos.get('entryPrice') or pos.get('ep') or 0)
                    mark_price = float(pos.get('markPrice') or pos.get('mp') or entry_price)
                    unrealized_pnl = float(pos.get('unRealizedProfit') or pos.get('up') or 0)
                    position_side = pos.get('positionSide') or pos.get('ps') or 'BOTH'
                    
                    # Get leverage - prefer from position data (WebSocket), fallback to API
                    leverage = float(pos.get('leverage') or pos.get('l') or 0)
                    if leverage < 1:
                        leverage = self._get_symbol_leverage(client, symbol)
                    
                    # Calculate PNL percentage
                    if entry_price > 0:
                        if position_amt > 0:  # LONG
                            pnl_pct = ((mark_price - entry_price) / entry_price) * 100
                        else:  # SHORT
                            pnl_pct = ((entry_price - mark_price) / entry_price) * 100
                    else:
                        pnl_pct = 0
                    
                    active_positions.append({
                        'symbol': symbol,
                        'side': 'LONG' if position_amt > 0 else 'SHORT',
                        'position_side': position_side,
                        'size': abs(position_amt),
                        'entry_price': entry_price,
                        'mark_price': mark_price,
                        'unrealized_pnl': unrealized_pnl,
                        'pnl_pct': pnl_pct,
                        'leverage': leverage
                    })

            # Realized PnL snapshots (1d/7d/30d) using income history; cached and throttled
            realized = self._fetch_realized_pnl(client, account_name)
            
            return {
                'account_name': account_name,
                'total_wallet_balance': total_wallet_balance,
                'equity': total_margin_balance,
                'available_balance': available_balance,
                'used_margin': total_position_margin,
                'margin_ratio': margin_ratio,
                'unrealized_pnl': total_unrealized_pnl,
                'positions': active_positions,
                'position_count': len(active_positions),
                'realized_pnl_1d': realized.get('pnl_1d', 0.0),
                'realized_pnl_7d': realized.get('pnl_7d', 0.0),
                'realized_pnl_30d': realized.get('pnl_30d', 0.0),
                'timestamp': time.time()
            }
            
        except Exception as e:
            import traceback
            logger.error(f"❌ Failed to fetch {account_name} account state: {e}")
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            return None

    def _fetch_realized_pnl(self, client: Client, account_name: str) -> Dict[str, float]:
        """Fetch recent realized PnL (and related income types) with SMART pagination.
        
        OPTIMIZATION: Do full 30-day fetch only on startup or every hour.
        For regular updates, only fetch last 1 day incrementally to minimize API calls.
        """
        now = time.time()
        last = self._last_income_fetch.get(account_name, 0)
        cached = self._income_cache.get(account_name, {})
        
        if now - last < self.income_fetch_interval:
            return cached

        income_types = ["REALIZED_PNL", "COMMISSION", "FUNDING_FEE"]
        now_ms = int(now * 1000)
        
        # SMART FETCH: Full 30d only on startup or every hour, otherwise just 1d incremental
        full_fetch_interval = 3600  # 1 hour between full fetches
        last_full = cached.get('last_full_fetch', 0)
        do_full_fetch = (now - last_full) >= full_fetch_interval or not cached
        
        if do_full_fetch:
            start_ms = now_ms - 30 * 24 * 3600 * 1000  # 30 days
            logger.info(f"[REALIZED_PNL] {account_name}: Starting FULL 30-day fetch...")
        else:
            # Incremental: only fetch last 1 day
            start_ms = now_ms - 1 * 24 * 3600 * 1000  # 1 day
            logger.debug(f"[REALIZED_PNL] {account_name}: Incremental 1-day fetch")
        
        end_ms = now_ms
        pnl_1d = pnl_7d = pnl_30d = 0.0
        total_records = 0

        try:
            for income_type in income_types:
                current_start = start_ms
                income_type_records = 0
                
                while True:
                    self.rate_limiter.maybe_sleep()
                    records = client.futures_income_history(
                        incomeType=income_type,
                        startTime=current_start,
                        endTime=end_ms,
                        limit=1000,
                    )
                    
                    if not records:
                        break
                    
                    batch_size = len(records)
                    income_type_records += batch_size
                    total_records += batch_size
                    
                    for rec in records:
                        amt = float(rec.get("income", 0.0))
                        ts = float(rec.get("time", 0))
                        age = now_ms - ts
                        if age <= 1 * 24 * 3600 * 1000:
                            pnl_1d += amt
                        if age <= 7 * 24 * 3600 * 1000:
                            pnl_7d += amt
                        if age <= 30 * 24 * 3600 * 1000:
                            pnl_30d += amt
                    
                    # CRITICAL: Check if we got less than limit - means no more records
                    if batch_size < 1000:
                        break
                    
                    # Move start time past last record for next page
                    last_ts = int(records[-1].get("time", 0))
                    if last_ts <= 0 or last_ts <= current_start:
                        # Safety: avoid infinite loop
                        break
                    current_start = last_ts + 1
                
                if income_type_records > 1000:
                    logger.debug(f"[REALIZED_PNL] {account_name} {income_type}: {income_type_records} records (paginated)")
            
            # Log if we found significant data
            if do_full_fetch:
                logger.info(f"[REALIZED_PNL] {account_name}: FULL 1d=${pnl_1d:.2f} 7d=${pnl_7d:.2f} 30d=${pnl_30d:.2f} ({total_records} records)")
            elif total_records > 100:
                logger.debug(f"[REALIZED_PNL] {account_name}: INCR 1d=${pnl_1d:.2f} ({total_records} records)")
            
            # For incremental fetch, merge with cached 7d/30d values
            if not do_full_fetch and cached:
                # Keep old 7d/30d, update 1d
                pnl_7d = cached.get('pnl_7d', 0.0)
                pnl_30d = cached.get('pnl_30d', 0.0)
            
            result = {
                "pnl_1d": pnl_1d,
                "pnl_7d": pnl_7d,
                "pnl_30d": pnl_30d,
                "total_records": total_records,
                "fetched_at": now,
                "last_full_fetch": now if do_full_fetch else cached.get('last_full_fetch', now),
            }
            self._income_cache[account_name] = result
            self._last_income_fetch[account_name] = now
            return result
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch realized PnL for {account_name}: {e}")
            return self._income_cache.get(account_name, {})

    def _fetch_recent_trades(self, client: Client, account_name: str) -> List[Dict[str, Any]]:
        """Fetch last N trades within the configured day window, paginated by fromId."""
        now = time.time()
        last_ts = self._trade_cache_ts.get(account_name, 0)
        if self._trade_fetch_fetched.get(account_name) and now - last_ts < self.trade_history_refresh_seconds:
            return self._trade_cache.get(account_name, [])

        try:
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - self.max_trade_history_days * 24 * 3600 * 1000
            trades: List[Dict[str, Any]] = []
            for sym in SYMBOLS:
                from_id = None
                attempts = 0
                while True:
                    self.rate_limiter.maybe_sleep()
                    params: Dict[str, Any] = {
                        "symbol": sym,
                        "startTime": start_ms,
                        "limit": 1000,
                    }
                    if from_id is not None:
                        params["fromId"] = from_id
                    batch = None
                    try:
                        batch = client.futures_account_trades(**params)
                    except Exception as e:
                        if ("-4165" in str(e) or "-1106" in str(e)) and attempts == 0:
                            # Retry once without startTime to satisfy Binance constraints
                            attempts += 1
                            params.pop("startTime", None)
                            params.pop("fromId", None)
                            try:
                                batch = client.futures_account_trades(**params)
                            except Exception:
                                raise
                        else:
                            raise
                    if not batch:
                        break
                    trades.extend(batch)
                    last_id = batch[-1].get("id")
                    if last_id is None or len(batch) < 1000:
                        break
                    from_id = last_id + 1

            # Normalize minimal fields and trim to most recent N
            parsed = []
            for t in trades:
                parsed.append({
                    "symbol": t.get("symbol"),
                    "side": t.get("side"),
                    "qty": float(t.get("qty", 0)),
                    "price": float(t.get("price", 0)),
                    "realized_pnl": float(t.get("realizedPnl", 0)),
                    "commission": float(t.get("commission", 0)),
                    "commission_asset": t.get("commissionAsset"),
                    "time": int(t.get("time", 0)),
                })
            parsed = sorted(parsed, key=lambda x: x.get("time", 0))[-self.max_trades_per_account:]
            self._trade_cache[account_name] = parsed
            self._trade_fetch_fetched[account_name] = True
            self._trade_cache_ts[account_name] = now
            return parsed
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch trades for {account_name}: {e}")
            return self._trade_cache.get(account_name, [])

    def _fetch_recent_orders(self, client: Client, account_name: str) -> List[Dict[str, Any]]:
        """Fetch recent order history per account to mirror Binance UI for audits/replay."""
        now = time.time()
        last_ts = self._order_cache_ts.get(account_name, 0)
        if self._order_fetch_fetched.get(account_name) and now - last_ts < self.order_history_refresh_seconds:
            return self._order_cache.get(account_name, [])

        try:
            now_ms = int(time.time() * 1000)
            start_ms = now_ms - self.max_order_history_days * 24 * 3600 * 1000
            orders: List[Dict[str, Any]] = []

            for sym in SYMBOLS:
                cursor = start_ms
                attempts = 0
                while True:
                    self.rate_limiter.maybe_sleep()
                    params: Dict[str, Any] = {
                        "symbol": sym,
                        "startTime": cursor,
                        "limit": 1000,
                    }
                    batch = None
                    try:
                        batch = client.futures_get_all_orders(**params)
                    except Exception as e:
                        # Older accounts may require tighter windows; fall back to 7d once
                        if "-4165" in str(e) and attempts == 0:
                            cursor = now_ms - 7 * 24 * 3600 * 1000
                            attempts += 1
                            continue
                        else:
                            raise

                    if not batch:
                        break

                    orders.extend(batch)

                    last_time = batch[-1].get("updateTime") or batch[-1].get("time")
                    if last_time is None or len(batch) < 1000:
                        break
                    cursor = int(last_time) + 1

            # Normalize minimal fields and trim to most recent N
            parsed = []
            for o in orders:
                parsed.append({
                    "symbol": o.get("symbol"),
                    "side": o.get("side"),
                    "type": o.get("type"),
                    "status": o.get("status"),
                    "orig_qty": float(o.get("origQty", 0)),
                    "executed_qty": float(o.get("executedQty", 0)),
                    "price": float(o.get("price", 0)),
                    "avg_price": float(o.get("avgPrice", 0)),
                    "reduce_only": bool(o.get("reduceOnly", False)),
                    "close_position": bool(o.get("closePosition", False)),
                    "position_side": o.get("positionSide"),
                    "time_in_force": o.get("timeInForce"),
                    "update_time": int(o.get("updateTime") or o.get("time", 0)),
                })

            parsed = sorted(parsed, key=lambda x: x.get("update_time", 0))[-self.max_orders_per_account:]
            self._order_cache[account_name] = parsed
            self._order_fetch_fetched[account_name] = True
            self._order_cache_ts[account_name] = now
            return parsed
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch orders for {account_name}: {e}")
            return self._order_cache.get(account_name, [])
    
    def sync_all_accounts(self) -> Dict[str, Any]:
        """Sync both accounts and return combined state - REDIS FIRST, API fallback"""
        now = time.time()
        
        # Rate limit syncing
        if now - self.last_sync_time < self.sync_interval:
            return self.combined_state
        
        try:
            # PRIORITY 1: Try to fetch from Redis (real-time trader data)
            primary_state = None
            asjad_state = None
            
            if self.redis:
                primary_state = self._fetch_account_state_from_redis("primary", "PRIMARY_WAJID")
                asjad_state = self._fetch_account_state_from_redis("asjad", "ASJAD")
            
            # FALLBACK: Use API if Redis failed (should never happen in production)
            if not primary_state and self.primary_client:
                logger.warning("⚠️ Redis failed for PRIMARY, falling back to API (slow)")
                primary_state = self._fetch_account_state(self.primary_client, "PRIMARY_WAJID", self.primary_ws_helper)
            
            if not asjad_state and self.asjad_client:
                logger.warning("⚠️ Redis failed for ASJAD, falling back to API (slow)")
                asjad_state = self._fetch_account_state(self.asjad_client, "ASJAD", self.asjad_ws_helper)
            
            if not primary_state or not asjad_state:
                logger.warning("⚠️ Failed to sync one or both accounts, using cached data")
                return self.combined_state
            
            # Combine metrics (keep per-account realized PnL separate as well)
            total_equity = primary_state['equity'] + asjad_state['equity']
            total_available = primary_state['available_balance'] + asjad_state['available_balance']
            total_used = primary_state['used_margin'] + asjad_state['used_margin']
            total_unrealized = primary_state['unrealized_pnl'] + asjad_state['unrealized_pnl']
            total_realized_1d = primary_state.get('realized_pnl_1d', 0.0) + asjad_state.get('realized_pnl_1d', 0.0)
            total_realized_7d = primary_state.get('realized_pnl_7d', 0.0) + asjad_state.get('realized_pnl_7d', 0.0)
            total_realized_30d = primary_state.get('realized_pnl_30d', 0.0) + asjad_state.get('realized_pnl_30d', 0.0)
            per_account_realized = {
                'primary': {
                    'pnl_1d': primary_state.get('realized_pnl_1d', 0.0),
                    'pnl_7d': primary_state.get('realized_pnl_7d', 0.0),
                    'pnl_30d': primary_state.get('realized_pnl_30d', 0.0),
                },
                'asjad': {
                    'pnl_1d': asjad_state.get('realized_pnl_1d', 0.0),
                    'pnl_7d': asjad_state.get('realized_pnl_7d', 0.0),
                    'pnl_30d': asjad_state.get('realized_pnl_30d', 0.0),
                },
            }
            total_positions = primary_state['position_count'] + asjad_state['position_count']
            
            # Combined margin ratio (weighted average)
            if total_equity > 0:
                combined_margin_ratio = (
                    (primary_state['margin_ratio'] * primary_state['equity'] +
                     asjad_state['margin_ratio'] * asjad_state['equity']) / total_equity
                )
            else:
                combined_margin_ratio = 0
            
            # Update combined state
            self.combined_state = {
                'total_equity': total_equity,
                'total_available_margin': total_available,
                'total_used_margin': total_used,
                'margin_ratio': combined_margin_ratio,
                'total_unrealized_pnl': total_unrealized,
                'total_realized_pnl_1d': total_realized_1d,
                'total_realized_pnl_7d': total_realized_7d,
                'total_realized_pnl_30d': total_realized_30d,
                'realized_per_account': per_account_realized,
                'position_count': total_positions,
                'accounts': {
                    'primary': primary_state,
                    'asjad': asjad_state
                },
                'timestamp': now
            }

            # One-time trade history fetch per restart
            if self.primary_client and not self._trade_fetch_fetched.get('primary'):
                self._fetch_recent_trades(self.primary_client, 'primary')
            if self.asjad_client and not self._trade_fetch_fetched.get('asjad'):
                self._fetch_recent_trades(self.asjad_client, 'asjad')

            # One-time order history fetch per restart
            if self.primary_client and not self._order_fetch_fetched.get('primary'):
                self._fetch_recent_orders(self.primary_client, 'primary')
            if self.asjad_client and not self._order_fetch_fetched.get('asjad'):
                self._fetch_recent_orders(self.asjad_client, 'asjad')
            
            # Track historical PNL
            pnl_snapshot = {
                'timestamp': now,
                'equity': total_equity,
                'unrealized_pnl': total_unrealized,
                'position_count': total_positions
            }
            self.pnl_history_1d.append(pnl_snapshot)
            self.pnl_history_7d.append(pnl_snapshot)
            self.pnl_history_30d.append(pnl_snapshot)
            
            self.last_sync_time = now
            
            logger.debug(f"💰 Portfolio synced: Equity=${total_equity:.2f}, "
                        f"Margin={combined_margin_ratio:.1f}%, "
                        f"PNL=${total_unrealized:.2f}, Positions={total_positions}")
            
            return self.combined_state
            
        except Exception as e:
            logger.error(f"❌ Failed to sync accounts: {e}")
            return self.combined_state
    
    def get_historical_pnl(self, period: str = '1d') -> Dict[str, float]:
        """Get historical PNL statistics for specified period"""
        if period == '1d':
            history = list(self.pnl_history_1d)
        elif period == '7d':
            history = list(self.pnl_history_7d)
        elif period == '30d':
            history = list(self.pnl_history_30d)
        else:
            return {'error': 'Invalid period'}
        
        if not history:
            return {'pnl': 0.0, 'pnl_pct': 0.0, 'samples': 0}
        
        start_equity = history[0]['equity']
        end_equity = history[-1]['equity']
        pnl = end_equity - start_equity
        pnl_pct = (pnl / start_equity * 100) if start_equity > 0 else 0
        
        return {
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'start_equity': start_equity,
            'end_equity': end_equity,
            'samples': len(history)
        }
    
    def get_portfolio_context_for_training(self) -> Dict[str, Any]:
        """
        Get comprehensive portfolio context for training/reward calculations.
        This is used by the trainer to make portfolio-aware decisions.
        """
        current = self.combined_state
        pnl_1d = self.get_historical_pnl('1d')
        pnl_7d = self.get_historical_pnl('7d')
        pnl_30d = self.get_historical_pnl('30d')
        
        return {
            # Current state
            'equity': current['total_equity'],
            'available_margin': current['total_available_margin'],
            'used_margin': current['total_used_margin'],
            'margin_ratio': current['margin_ratio'],
            'unrealized_pnl': current['total_unrealized_pnl'],
            'realized_pnl_1d': current.get('total_realized_pnl_1d', 0.0),
            'realized_pnl_7d': current.get('total_realized_pnl_7d', 0.0),
            'realized_pnl_30d': current.get('total_realized_pnl_30d', 0.0),
            'realized_per_account': current.get('realized_per_account', {}),
            'position_count': current['position_count'],
			
            # Historical performance (equity-based)
            'pnl_1d': pnl_1d['pnl'],
            'pnl_1d_pct': pnl_1d['pnl_pct'],
            'pnl_7d': pnl_7d['pnl'],
            'pnl_7d_pct': pnl_7d['pnl_pct'],
            'pnl_30d': pnl_30d['pnl'],
            'pnl_30d_pct': pnl_30d['pnl_pct'],
			
            # Risk metrics
            'margin_utilization_safe': current['margin_ratio'] < 30,  # < 30% is safe
            'position_count_safe': current['position_count'] < 20,    # < 20 positions is safe
            'equity_trend': 'up' if pnl_1d['pnl'] > 0 else 'down',
			
            # Per-account details
            'accounts': current['accounts'],
            'recent_trades_per_account': {
                k: v[-self.max_trades_per_account_ctx:]
                for k, v in self._trade_cache.items()
            },
            'recent_orders_per_account': {
                k: v[-self.max_orders_per_account_ctx:]
                for k, v in self._order_cache.items()
            },
            'timestamp': current['timestamp']
        }


class SafeHedgeModule:
    """
    SAFE hedge module that prevents whipsaw death spirals.
    
    Key safety mechanisms:
    1. Higher confidence requirements (0.85 minimum, 0.90 for risky conditions)
    2. Portfolio-aware decisions (won't hedge if already losing heavily)
    3. Cooldown periods to prevent rapid flip-flopping
    4. Emergency circuit breaker for rapid losses
    """
    
    def __init__(self, portfolio_tracker: MultiAccountPortfolioTracker):
        self.portfolio_tracker = portfolio_tracker
        
        # Safety thresholds
        self.MIN_HEDGE_CONFIDENCE = 0.85  # Raised from 0.65 - prevents weak signals
        self.RISKY_CONDITION_CONFIDENCE = 0.90  # Even higher when portfolio is stressed
        self.MAX_LOSS_FOR_HEDGE = -5.0  # Don't hedge if position is losing > 5%
        self.MAX_PORTFOLIO_LOSS_FOR_AGGRESSIVE = -10.0  # % loss before switching to defensive
        
        # Cooldown tracking
        self.last_hedge_time = defaultdict(float)
        self.hedge_cooldown_seconds = 300  # 5 minutes minimum between hedges per symbol
        
        # Emergency circuit breaker
        self.rapid_loss_threshold = -100.0  # $ loss in short period
        self.rapid_loss_window = 3600  # 1 hour
        self.recent_losses = deque(maxlen=100)
        
        logger.info("🛡️ Safe hedge module initialized with strict safety thresholds")
    
    def should_hedge_position(self, symbol: str, current_side: str, predicted_action: str,
                             confidence: float, current_pnl_pct: float,
                             position_info: Dict) -> Tuple[bool, str]:
        """
        Determine if hedging is safe and advisable.
        
        Returns:
            (should_hedge: bool, reason: str)
        """
        
        # Get current portfolio state
        portfolio_ctx = self.portfolio_tracker.get_portfolio_context_for_training()
        
        # Safety check 1: Emergency circuit breaker
        if self._check_emergency_circuit_breaker():
            return (False, "🚨 EMERGENCY CIRCUIT BREAKER ACTIVE - No hedging allowed")
        
        # Safety check 2: Cooldown period
        now = time.time()
        if now - self.last_hedge_time[symbol] < self.hedge_cooldown_seconds:
            remaining = self.hedge_cooldown_seconds - (now - self.last_hedge_time[symbol])
            return (False, f"⏳ Hedge cooldown active ({remaining:.0f}s remaining)")
        
        # Safety check 3: Position loss check (don't hedge losing positions)
        if current_pnl_pct < self.MAX_LOSS_FOR_HEDGE:
            return (False, f"❌ Position losing too much ({current_pnl_pct:.1f}%) - cut instead of hedge")
        
        # Safety check 4: Portfolio stress check
        portfolio_stressed = (
            portfolio_ctx['margin_ratio'] > 40 or
            portfolio_ctx['pnl_1d_pct'] < self.MAX_PORTFOLIO_LOSS_FOR_AGGRESSIVE or
            not portfolio_ctx['margin_utilization_safe']
        )
        
        required_confidence = self.RISKY_CONDITION_CONFIDENCE if portfolio_stressed else self.MIN_HEDGE_CONFIDENCE
        
        # Safety check 5: Confidence requirement
        if confidence < required_confidence:
            return (False, f"⚠️ Confidence too low ({confidence:.2f} < {required_confidence:.2f})")
        
        # Safety check 6: Direction must be opposite
        if predicted_action == current_side:
            return (False, "⚠️ Predicted action same as current side - not a hedge")
        
        # Safety check 7: Ensure we have available margin
        if portfolio_ctx['available_margin'] < 100:  # Need at least $100 available
            return (False, f"⚠️ Insufficient margin (${portfolio_ctx['available_margin']:.2f})")
        
        # All safety checks passed - hedge is approved
        self.last_hedge_time[symbol] = now
        
        reason = (f"✅ SAFE HEDGE APPROVED: {current_side}→{predicted_action} @ {confidence:.2f} confidence, "
                 f"PNL={current_pnl_pct:.1f}%, Margin={portfolio_ctx['margin_ratio']:.1f}%")
        
        logger.info(f"🔄 {symbol}: {reason}")
        
        return (True, reason)
    
    def _check_emergency_circuit_breaker(self) -> bool:
        """Check if emergency circuit breaker should activate"""
        if len(self.recent_losses) < 5:
            return False
        
        # Calculate recent losses in the time window
        now = time.time()
        recent_loss_sum = sum(
            loss['amount'] for loss in self.recent_losses
            if now - loss['timestamp'] < self.rapid_loss_window
        )
        
        if recent_loss_sum < self.rapid_loss_threshold:
            logger.error(f"🚨 EMERGENCY CIRCUIT BREAKER TRIGGERED: ${recent_loss_sum:.2f} loss in {self.rapid_loss_window/60:.0f}min")
            return True
        
        return False
    
    def record_trade_result(self, symbol: str, pnl_usd: float, timestamp: float = None):
        """Record trade result for circuit breaker tracking"""
        if pnl_usd < 0:  # Only track losses
            self.recent_losses.append({
                'symbol': symbol,
                'amount': pnl_usd,
                'timestamp': timestamp or time.time()
            })


class PortfolioAwareRewardFunction:
    """
    Enhanced reward function that considers full portfolio state AND actual trade history.
    Prevents the model from optimizing simulated rewards while losing real money.
    
    UPDATED: Now integrates with TradeOutcomeTracker for actual PnL from executed trades.
    """
    
    def __init__(self, portfolio_tracker: MultiAccountPortfolioTracker, feedback_tracker=None):
        self.portfolio_tracker = portfolio_tracker
        self.feedback_tracker = feedback_tracker  # TradeOutcomeTracker instance
        
        # Symbol-specific performance multipliers (learned from actual trades)
        self._symbol_performance = {}
        
        logger.info("💰 Portfolio-aware reward function initialized (with trade history support)")
    
    def set_feedback_tracker(self, feedback_tracker):
        """Inject feedback tracker after initialization"""
        self.feedback_tracker = feedback_tracker
        logger.info("🔗 [PORTFOLIO-REWARD] TradeOutcomeTracker connected")
    
    def calculate_reward(self, base_reward: float, symbol: str, action: int,
                        simulated_pnl: float) -> float:
        """
        Calculate reward that heavily weighs REAL portfolio performance AND actual trade history.
        
        Args:
            base_reward: Simulated reward from environment
            symbol: Trading symbol
            action: Action taken
            simulated_pnl: PNL from simulated environment
            
        Returns:
            Adjusted reward that considers real portfolio state and actual trades
        """
        
        # Get real portfolio context
        portfolio_ctx = self.portfolio_tracker.get_portfolio_context_for_training()
        
        # NEW: Get actual trade feedback if available
        actual_trade_weight = 0.0
        actual_pnl_component = 0.0
        
        if self.feedback_tracker:
            try:
                # Use REAL trade outcomes instead of simulated
                actual_adjusted = self.feedback_tracker.get_reward_adjustment(
                    symbol=symbol,
                    base_reward=base_reward
                )
                if abs(actual_adjusted - base_reward) > 0.01:
                    # Actual trade history available - weight it heavily
                    actual_trade_weight = 0.4  # 40% from actual trades
                    actual_pnl_component = actual_adjusted
                    logger.debug(f"🎯 [ACTUAL-TRADE] {symbol}: Using real PnL={actual_adjusted:.4f} (sim={base_reward:.4f})")
            except Exception as e:
                logger.debug(f"Feedback tracker lookup failed for {symbol}: {e}")
        
        # Adjust weights based on whether we have actual trade data
        if actual_trade_weight > 0:
            # Have actual trade history - reduce reliance on current portfolio state
            realized_weight = 0.3  # Reduced from 0.5
            unrealized_weight = 0.2  # Reduced from 0.3
            simulated_weight = 0.1  # Reduced from 0.2
            # actual_trade_weight = 0.4 (already set above)
        else:
            # No actual trade history - use original weights
            realized_weight = 0.5
            unrealized_weight = 0.3
            simulated_weight = 0.2

        equity = max(portfolio_ctx['equity'], 1.0)
        # Use total realized, but keep per-account available in ctx if downstream wants account-level reward routing
        realized_pnl_norm = portfolio_ctx.get('realized_pnl_1d', 0.0) / equity
        unrealized_pnl_norm = portfolio_ctx.get('pnl_1d', 0.0) / equity

        adjusted_reward = (
            realized_weight * realized_pnl_norm +
            unrealized_weight * unrealized_pnl_norm +
            simulated_weight * base_reward +
            actual_trade_weight * actual_pnl_component  # NEW: Actual trade component
        )
        
        # Apply portfolio state penalties/bonuses
        
        # Penalty for high margin utilization (risky)
        if portfolio_ctx['margin_ratio'] > 50:
            margin_penalty = -0.5 * (portfolio_ctx['margin_ratio'] - 50) / 50
            adjusted_reward += margin_penalty
        
        # Penalty for too many positions (overtrading)
        if portfolio_ctx['position_count'] > 20:
            overtrading_penalty = -0.3 * (portfolio_ctx['position_count'] - 20) / 10
            adjusted_reward += overtrading_penalty
        
        # Bonus for efficient margin use (< 30% utilization with profits)
        if portfolio_ctx['margin_ratio'] < 30 and portfolio_ctx['pnl_1d'] > 0:
            efficiency_bonus = 0.2
            adjusted_reward += efficiency_bonus
        
        # Heavy penalty for negative 7-day trend (learning from sustained losses)
        if portfolio_ctx['pnl_7d_pct'] < -5.0:
            sustained_loss_penalty = -1.0 * abs(portfolio_ctx['pnl_7d_pct']) / 100
            adjusted_reward += sustained_loss_penalty
        
        return adjusted_reward


# Integration instructions for hybrid_trainer.py
INTEGRATION_INSTRUCTIONS = """
=============================================================================
INTEGRATION INSTRUCTIONS FOR hybrid_trainer.py
=============================================================================

1. ADD IMPORTS (top of file):
   from rl.CRITICAL_HEDGE_AND_PORTFOLIO_FIX import (
       MultiAccountPortfolioTracker,
       SafeHedgeModule,
       PortfolioAwareRewardFunction
   )

2. IN __init__ METHOD (around line 3510, after self._live_config = get_live_config()):
   
   # Initialize multi-account portfolio tracker
   self.portfolio_tracker = MultiAccountPortfolioTracker()
   
   # Check if we have asjad credentials
   asjad_api_key = getattr(self._live_config, 'BINANCE_ASJAD_API_KEY', None)
   asjad_api_secret = getattr(self._live_config, 'BINANCE_ASJAD_API_SECRET', None)
   
   if asjad_api_key and asjad_api_secret:
       # Initialize both accounts (live)
       self.portfolio_tracker.initialize_clients(
           primary_api_key=self._live_config.BINANCE_FUT_API_KEY,
           primary_api_secret=self._live_config.BINANCE_FUT_API_SECRET,
           asjad_api_key=asjad_api_key,
           asjad_api_secret=asjad_api_secret,
       )
       logger.info("✅ Multi-account portfolio tracking ENABLED (primary + asjad)")
       
       # Initialize safe hedge module
       self.safe_hedge = SafeHedgeModule(self.portfolio_tracker)
       
       # Initialize portfolio-aware rewards
       self.portfolio_reward_fn = PortfolioAwareRewardFunction(self.portfolio_tracker)
   else:
       logger.warning("⚠️ Asjad account credentials not found - single account mode")
       self.safe_hedge = None
       self.portfolio_reward_fn = None

3. UPDATE sync_real_portfolio() METHOD (line 5135):
   
   def sync_real_portfolio(self):
       # Sync real portfolio data from BOTH Binance accounts
       
       # Use multi-account tracker if available
       if hasattr(self, 'portfolio_tracker') and self.portfolio_tracker:
           combined_state = self.portfolio_tracker.sync_all_accounts()
           
           # Return in expected format
           return {
               'balance': combined_state['total_equity'],
               'positions': {}, # Aggregate positions from both accounts
               'using_real_data': True,
               'available_margin': combined_state['total_available_margin'],
               'used_margin': combined_state['total_used_margin'],
               'margin_utilization': combined_state['margin_ratio'],
               'total_margin_balance': combined_state['total_equity'],
               'max_withdraw': combined_state['total_available_margin'],
               'unrealized_pnl': combined_state['total_unrealized_pnl'],
               'position_count': combined_state['position_count'],
               
               # Historical context
               'pnl_1d': self.portfolio_tracker.get_historical_pnl('1d')['pnl'],
               'pnl_7d': self.portfolio_tracker.get_historical_pnl('7d')['pnl'],
               'pnl_30d': self.portfolio_tracker.get_historical_pnl('30d')['pnl'],
           }
       
       # Fallback to single account (existing code)
       if not self.binance_client:
           ... (keep existing fallback code)

4. UPDATE REWARD CALCULATION (in training loop, search for reward calculation):
   
   # After base_reward is calculated
   if hasattr(self, 'portfolio_reward_fn') and self.portfolio_reward_fn:
       # Use portfolio-aware reward
       adjusted_reward = self.portfolio_reward_fn.calculate_reward(
           base_reward=base_reward,
           symbol=symbol,
           action=action,
           simulated_pnl=simulated_pnl
       )
       logger.debug(f"💰 [PORTFOLIO-REWARD] Base: {base_reward:.4f} → Adjusted: {adjusted_reward:.4f}")
       base_reward = adjusted_reward

5. ADD HEDGE SAFETY CHECK (when deciding to hedge, search for hedge logic):
   
   # Before executing hedge action
   if hasattr(self, 'safe_hedge') and self.safe_hedge:
       should_hedge, reason = self.safe_hedge.should_hedge_position(
           symbol=symbol,
           current_side=current_side,
           predicted_action=predicted_action,
           confidence=confidence,
           current_pnl_pct=current_pnl_pct,
           position_info=position_info
       )
       
       if not should_hedge:
           logger.info(f"🛡️ [{symbol}] Hedge blocked: {reason}")
           # Don't execute hedge, use safer action (HOLD or CLOSE)
           continue
       else:
           logger.info(f"✅ [{symbol}] {reason}")
           # Proceed with hedge

6. ADD TO .env FILE:
   # Asjad Account Credentials
   BINANCE_ASJAD_API_KEY=<asjad_api_key>
   BINANCE_ASJAD_API_SECRET=<asjad_api_secret>

7. UPDATE MASA WORKERS (in masa worker code):
   # Before getting action from MASA agent, inject portfolio context
   if hasattr(trainer, 'portfolio_tracker'):
       portfolio_ctx = trainer.portfolio_tracker.get_portfolio_context_for_training()
       # Add portfolio features to observation
       obs_with_portfolio = np.concatenate([
           obs,
           [portfolio_ctx['margin_ratio'] / 100],  # Normalize
           [portfolio_ctx['position_count'] / 50],  # Normalize
           [max(min(portfolio_ctx['pnl_1d_pct'] / 100, 1), -1)],  # Clamp and normalize
       ])
       obs = obs_with_portfolio

=============================================================================
TESTING CHECKLIST:
=============================================================================
[ ] 1. Verify both accounts connect successfully (check logs for "✅ Primary account" and "✅ Asjad account")
[ ] 2. Monitor combined equity tracking (logs should show total equity from both)
[ ] 3. Verify hedge blocking works (try to trigger hedge with low confidence, should be blocked)
[ ] 4. Check portfolio-aware rewards are being calculated (look for "[PORTFOLIO-REWARD]" in logs)
[ ] 5. Verify historical PNL tracking (1d, 7d, 30d metrics in logs)
[ ] 6. Test emergency circuit breaker (simulate rapid losses, should stop hedging)
[ ] 7. Monitor margin ratio calculation (should match Binance UI)
[ ] 8. Verify MASA workers receive portfolio context

=============================================================================
"""

if __name__ == "__main__":
    print(INTEGRATION_INSTRUCTIONS)
    print("\n✅ Critical hedge and portfolio fix module loaded successfully")
    print("⚠️  IMPORTANT: Follow integration instructions to apply fixes to hybrid_trainer.py")

