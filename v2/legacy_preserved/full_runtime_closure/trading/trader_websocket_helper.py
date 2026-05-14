"""
Trader-Specific WebSocket Helper for Binance Futures
Handles mark price, index price, and user data streams with auto-reconnection and REST fallback.

Features:
- Mark price + Index price streams (1s updates)
- User data stream (positions, balance, orders)
- 3-minute REST fallback when websocket fails
- 2-minute reconnection retry loop
- Telegram alerts for connection status
- Health monitoring and staleness detection
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional
from datetime import datetime

try:
    from binance import ThreadedWebsocketManager
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
except ImportError:
    ThreadedWebsocketManager = None
    Client = None
    BinanceAPIException = Exception

# Import SYMBOLS from config if available
try:
    import config
    DEFAULT_SYMBOLS = getattr(config, 'SYMBOLS', [])
except ImportError:
    DEFAULT_SYMBOLS = []

logger = logging.getLogger(__name__)


class TraderWebSocketHelper:
    """
    Dedicated websocket manager for traders with resilient reconnection and REST fallback.
    
    REST Fallback Logic:
    - If websocket data is stale for >3 minutes, automatically fall back to REST API
    - Continue reconnection attempts every 2 minutes in background
    - Switch back to websocket once connection is restored
    
    Telegram Alerts:
    - Connection established
    - Connection lost (with reconnect info)
    - REST fallback activated
    - Websocket restored after fallback
    """
    
    # Thresholds
    STALE_THRESHOLD_SECONDS = 180  # 3 minutes - trigger REST fallback
    RECONNECT_INTERVAL_SECONDS = 120  # 2 minutes - reconnection retry interval
    KEEPALIVE_INTERVAL_SECONDS = 1800  # 30 minutes - listen key keepalive
    
    # Stream update frequencies
    MARK_PRICE_UPDATE_EXPECTED = 1.0  # 1s updates
    INDEX_PRICE_UPDATE_EXPECTED = 1.0  # 1s updates
    USER_DATA_UPDATE_EXPECTED = 5.0  # Account updates are event-driven, but check health
    
    def __init__(self, client: Client, symbols: Optional[List[str]] = None, telegram_notifier=None, account_id: str = "primary", redis_client=None):
        """
        Initialize trader websocket helper.
        
        Args:
            client: Binance client instance
            symbols: List of symbols to track (e.g., ['BTCUSDT', 'ETHUSDT']). 
                    If None, uses SYMBOLS from config.py
            telegram_notifier: Optional telegram alert instance
            account_id: Account identifier for logging/alerts
            redis_client: Optional Redis client for publishing portfolio state to trainer
        """
        if ThreadedWebsocketManager is None:
            raise RuntimeError("python-binance not available - websocket disabled")
        
        self._client = client
        self._redis = redis_client
        
        # Use provided symbols or fall back to config.SYMBOLS
        if symbols is None:
            if not DEFAULT_SYMBOLS:
                raise ValueError("No symbols provided and config.SYMBOLS is empty or not available")
            self._symbols = [s.upper() for s in DEFAULT_SYMBOLS]
            logger.info(f"[WS-INIT] Using {len(self._symbols)} symbols from config.py")
        else:
            self._symbols = [s.upper() for s in symbols]
            logger.info(f"[WS-INIT] Using {len(self._symbols)} provided symbols")
        self._notifier = telegram_notifier
        self._account_id = account_id
        # LIVE ONLY: Websocket helper always uses live endpoints.
        
        # WebSocket manager
        self._twm: Optional[ThreadedWebsocketManager] = None
        self._listen_key: Optional[str] = None
        
        # Data storage with thread safety
        self._mark_prices: Dict[str, float] = {}
        self._index_prices: Dict[str, float] = {}
        self._positions: List[Dict[str, Any]] = []
        self._balance: Dict[str, Any] = {}
        
        self._mark_lock = threading.Lock()
        self._index_lock = threading.Lock()
        self._positions_lock = threading.Lock()
        self._balance_lock = threading.Lock()
        
        # Timestamps for staleness detection
        self._mark_price_last_update: Dict[str, float] = {}
        self._index_price_last_update: Dict[str, float] = {}
        self._positions_last_update = 0.0
        self._balance_last_update = 0.0
        
        # Connection state
        self._connected = False
        self._connection_time = 0.0
        self._last_disconnect_time = 0.0
        self._fallback_mode = False
        self._stop_event = threading.Event()
        
        # Background threads
        self._reconnect_thread: Optional[threading.Thread] = None
        self._keepalive_thread: Optional[threading.Thread] = None
        self._health_monitor_thread: Optional[threading.Thread] = None
        
        # Start websocket connection
        self._start_websocket()
        
    # ========================================================================
    # PUBLIC API
    # ========================================================================
    
    def get_mark_price(self, symbol: str) -> Optional[float]:
        """Get mark price for symbol. Falls back to REST if stale."""
        with self._mark_lock:
            price = self._mark_prices.get(symbol)
            last_update = self._mark_price_last_update.get(symbol, 0)
        
        # Check staleness
        if price and (time.time() - last_update) < self.STALE_THRESHOLD_SECONDS:
            return price
        
        # Stale or missing - fetch from REST
        return self._fetch_mark_price_rest(symbol)
    
    def get_index_price(self, symbol: str) -> Optional[float]:
        """Get index price for symbol. Falls back to REST if stale."""
        with self._index_lock:
            price = self._index_prices.get(symbol)
            last_update = self._index_price_last_update.get(symbol, 0)
        
        if price and (time.time() - last_update) < self.STALE_THRESHOLD_SECONDS:
            return price
        
        return self._fetch_index_price_rest(symbol)
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get positions. Falls back to REST if stale."""
        with self._positions_lock:
            positions = list(self._positions)
            last_update = self._positions_last_update
        
        if positions and (time.time() - last_update) < self.STALE_THRESHOLD_SECONDS:
            return positions
        
        return self._fetch_positions_rest()
    
    def get_balance(self) -> Dict[str, Any]:
        """Get balance. Falls back to REST if stale."""
        with self._balance_lock:
            balance = dict(self._balance)
            last_update = self._balance_last_update
        
        if balance and (time.time() - last_update) < self.STALE_THRESHOLD_SECONDS:
            return balance
        
        return self._fetch_balance_rest()
    
    def is_connected(self) -> bool:
        """Check if websocket is actively connected."""
        return self._connected
    
    def is_fallback_mode(self) -> bool:
        """Check if currently using REST fallback."""
        return self._fallback_mode
    
    def get_connection_uptime(self) -> float:
        """Get current connection uptime in seconds."""
        if not self._connected:
            return 0.0
        return time.time() - self._connection_time
    
    def get_positions_timestamp(self) -> float:
        """Get timestamp of last positions update."""
        with self._positions_lock:
            return self._positions_last_update
    
    def get_balance_timestamp(self) -> float:
        """Get timestamp of last balance update."""
        with self._balance_lock:
            return self._balance_last_update
    
    def update_balance_from_rest(self, balance_data: Dict[str, Any]):
        """Update cached balance from REST API response (for cross-sync)."""
        with self._balance_lock:
            self._balance = {
                'balance': float(balance_data.get('balance', 0)),
                'available': float(balance_data.get('available', 0)),
                'timestamp': time.time()
            }
            self._balance_last_update = time.time()
    
    def update_positions_from_rest(self, positions_data: List[Dict[str, Any]]):
        """Update cached positions from REST API response (for cross-sync)."""
        with self._positions_lock:
            self._positions = positions_data
            self._positions_last_update = time.time()
    
    def update_mark_price_from_rest(self, symbol: str, price: float):
        """Update cached mark price from REST API (for cross-sync)."""
        with self._mark_lock:
            self._mark_prices[symbol] = price
            self._mark_price_last_update[symbol] = time.time()
    
    def stop(self):
        """Stop all websocket connections and background threads."""
        logger.info(f"[WS-STOP] Stopping websocket helper for account {self._account_id}")
        self._stop_event.set()
        
        # Stop threads
        for thread in [self._reconnect_thread, self._keepalive_thread, self._health_monitor_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=2)
        
        # Stop websocket manager
        if self._twm:
            try:
                self._twm.stop()
            except Exception as e:
                logger.debug(f"[WS-STOP] Error stopping TWM: {e}")
        
        self._connected = False
    
    # ========================================================================
    # WEBSOCKET MANAGEMENT
    # ========================================================================
    
    def _start_websocket(self):
        """Initialize websocket connections with error handling."""
        try:
            # Python 3.12 + python-binance threaded websockets can hit "Event loop is closed" if the
            # default loop state is inconsistent. Ensure a valid, open loop exists.
            try:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_closed():
                        raise RuntimeError("loop_closed")
                except Exception:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except Exception:
                pass

            # Create websocket manager
            self._twm = ThreadedWebsocketManager(
                api_key=self._client.API_KEY,
                api_secret=self._client.API_SECRET,
            )
            self._twm.start()
            
            # Start market data streams
            # NOTE: Mark price and index price not needed for traders - commented out to reduce websocket load
            # self._start_mark_price_streams()
            # self._start_index_price_streams()
            
            # Start user data stream (if it fails, remain in REST fallback mode; do NOT spam retries).
            user_ok = self._start_user_data_stream()
            if not user_ok:
                raise RuntimeError("user_stream_start_failed")
            
            # Mark as connected
            self._connected = True
            self._connection_time = time.time()
            self._fallback_mode = False
            
            # Start background threads
            self._start_health_monitor()
            self._start_reconnect_monitor()
            
            # Alert success
            uptime_msg = ""
            if self._last_disconnect_time > 0:
                downtime = time.time() - self._last_disconnect_time
                uptime_msg = f" (downtime: {downtime:.0f}s)"
            
            msg = f"✅ [WS-CONNECT] WebSocket connected for {self._account_id}{uptime_msg}"
            logger.info(msg)
            self._send_alert(msg)
            
        except Exception as e:
            logger.error(f"[WS-ERROR] Failed to start websocket: {e}", exc_info=True)
            self._connected = False
            self._fallback_mode = True
            
            msg = f"⚠️ [WS-FAIL] WebSocket failed for {self._account_id}: {e}. Using REST fallback."
            logger.warning(msg)
            self._send_alert(msg)
            
            # Start reconnection loop
            self._start_reconnect_monitor()
    
    # def _start_mark_price_streams(self):
    #     """Start mark price streams for all symbols."""
    #     for symbol in self._symbols:
    #         try:
    #             # Use @markPrice@1s for 1-second updates
    #             self._twm.start_symbol_mark_price_socket(
    #                 callback=self._handle_mark_price,
    #                 symbol=symbol.lower(),
    #                 fast=True  # 1s updates
    #             )
    #             logger.debug(f"[WS-MARK] Started mark price stream for {symbol}")
    #         except Exception as e:
    #             logger.warning(f"[WS-MARK] Failed to start mark price for {symbol}: {e}")
    #             # Seed from REST
    #             self._fetch_mark_price_rest(symbol)
    
    # def _start_index_price_streams(self):
    #     """Start index price streams for all pairs."""
    #     # Skip index price streams - they use different API not supported by ThreadedWebsocketManager
    #     # Index price is available in mark price stream response (field 'i')
    #     # We'll extract it from mark price updates instead
    #     logger.debug("[WS-INDEX] Using index price from mark price stream (field 'i')")
    #     return
    
    def _start_user_data_stream(self):
        """Start user data stream for account updates."""
        try:
            # Start user data stream. Note: python-binance manages listenKey internally for this call.
            # Avoid extra REST calls that can contribute to rate limits.
            self._twm.start_futures_user_socket(callback=self._handle_user_data)
            
            # Start keepalive thread
            self._keepalive_thread = threading.Thread(
                target=self._keepalive_loop,
                daemon=True,
                name=f"ws-keepalive-{self._account_id}"
            )
            self._keepalive_thread.start()
            
            logger.info(f"[WS-USER] Started user data stream for {self._account_id}")
            
            # Seed positions and balance from REST
            self._fetch_positions_rest()
            self._fetch_balance_rest()
            return True
        except Exception as e:
            logger.error(f"[WS-USER] Failed to start user data stream: {e}", exc_info=True)
            # Rate-limit safe backoff: do not spin reconnects aggressively.
            try:
                self._fallback_mode = True
                self._connected = False
                # exponential backoff with cap (5s -> 10s -> 20s ... up to 10m)
                if not hasattr(self, "_user_ws_failures"):
                    self._user_ws_failures = 0
                self._user_ws_failures += 1
                backoff = min(600, int(5 * (2 ** min(6, self._user_ws_failures))))
                self._next_reconnect_time = time.time() + backoff
                logger.warning(f"[WS-USER] Backing off reconnect for {backoff}s (failures={self._user_ws_failures})")
            except Exception:
                pass
            return False
    
    # ========================================================================
    # WEBSOCKET CALLBACKS
    # ========================================================================
    
    # def _handle_mark_price(self, msg: Dict[str, Any]):
    #     """Handle mark price updates (includes index price in field 'i')."""
    #     try:
    #         data = msg.get('data', msg)
    #         
    #         # Skip error messages
    #         if data.get('e') == 'error':
    #             return
    #         
    #         symbol = data.get('s', data.get('symbol'))
    #         mark_price_str = data.get('p', data.get('markPrice'))
    #         index_price_str = data.get('i', data.get('indexPrice'))  # Extract index price
    #         
    #         if not symbol:
    #             return
    #         
    #         # Update mark price
    #         if mark_price_str:
    #             mark_price = float(mark_price_str)
    #             with self._mark_lock:
    #                 self._mark_prices[symbol] = mark_price
    #                 self._mark_price_last_update[symbol] = time.time()
    #             logger.debug(f"[WS-MARK] {symbol} mark price: {mark_price}")
    #         
    #         # Update index price (from same stream)
    #         if index_price_str:
    #             index_price = float(index_price_str)
    #             with self._index_lock:
    #                 self._index_prices[symbol] = index_price
    #                 self._index_price_last_update[symbol] = time.time()
    #             logger.debug(f"[WS-INDEX] {symbol} index price: {index_price}")
    #         
    #     except Exception as e:
    #         logger.debug(f"[WS-MARK] Error processing mark price: {e}")
    
    # def _handle_index_price(self, msg: Dict[str, Any]):
    #     """Handle index price updates."""
    #     try:
    #         data = msg.get('data', msg)
    #         
    #         if data.get('e') == 'error':
    #             return
    #         
    #         # Index price uses pair notation (i field)
    #         pair = data.get('i')
    #         price_str = data.get('p')
    #         
    #         if not pair or not price_str:
    #             return
    #         
    #         price = float(price_str)
    #         
    #         # Convert pair back to symbol for storage (BTCUSD -> BTCUSDT)
    #         symbol = pair.replace('USD', 'USDT') if not pair.endswith('USDT') else pair
    #         
    #         with self._index_lock:
    #             self._index_prices[symbol] = price
    #             self._index_price_last_update[symbol] = time.time()
    #         
    #         logger.debug(f"[WS-INDEX] {symbol} index price: {price}")
    #         
    #     except Exception as e:
    #         logger.debug(f"[WS-INDEX] Error processing index price: {e}")
    
    def _handle_user_data(self, msg: Dict[str, Any]):
        """Handle user data stream updates (positions, balance, orders)."""
        try:
            data = msg.get('data', msg)
            event_type = data.get('e')
            
            if event_type == 'ACCOUNT_UPDATE':
                self._process_account_update(data)
            elif event_type == 'ORDER_TRADE_UPDATE':
                self._process_order_update(data)
            elif event_type == 'error':
                logger.warning(f"[WS-USER] Stream error: {data}")
            
        except Exception as e:
            logger.error(f"[WS-USER] Error processing user data: {e}", exc_info=True)
    
    def _process_account_update(self, data: Dict[str, Any]):
        """Process ACCOUNT_UPDATE event (positions and balance)."""
        account_data = data.get('a', {})
        
        # Calculate total unrealized PnL from positions
        total_unrealized_pnl = 0.0
        positions_payload = account_data.get('P', [])
        if positions_payload:
            for pos in positions_payload:
                try:
                    upnl = float(pos.get('up', 0) or 0)
                    total_unrealized_pnl += upnl
                except Exception:
                    pass
        
        # Update balance
        balances = account_data.get('B', [])
        if balances:
            for bal in balances:
                if bal.get('a') == 'USDT':  # Assuming USDT margin
                    wallet_balance = float(bal.get('wb', 0))
                    # Equity = wallet balance + unrealized PnL (matches totalMarginBalance from REST)
                    margin_balance = wallet_balance + total_unrealized_pnl
                    
                    with self._balance_lock:
                        self._balance = {
                            'balance': wallet_balance,
                            'available': float(bal.get('cw', 0)),  # Cross wallet balance
                            'margin_balance': margin_balance,  # CORRECT equity with unrealized PnL
                            'timestamp': time.time()
                        }
                        self._balance_last_update = time.time()
                    
                    # Publish to Redis for trainer's portfolio tracker
                    if self._redis:
                        try:
                            balance_key = f"trader:{self._account_id}:balance"
                            self._redis.hset(balance_key, mapping={
                                'balance': wallet_balance,
                                'margin_balance': margin_balance,  # CORRECT equity
                                'available': float(bal.get('cw', 0)),
                                'timestamp': time.time()
                            })
                            self._redis.expire(balance_key, 300)  # 5 min TTL
                        except Exception as redis_err:
                            logger.debug(f"[WS-BALANCE] Failed to publish to Redis: {redis_err}")
                    
                    logger.debug(f"[WS-BALANCE] Updated: wallet={wallet_balance:.2f}, equity={margin_balance:.2f}, upnl={total_unrealized_pnl:.2f}")
        
        # Update positions (delta merge)
        positions_payload = account_data.get('P', [])
        if positions_payload:
            with self._positions_lock:
                # Build position map
                pos_map = {
                    (p.get('symbol'), p.get('positionSide', 'BOTH')): p
                    for p in self._positions
                }
                
                # Merge deltas
                for raw_pos in positions_payload:
                    symbol = raw_pos.get('s')
                    side = raw_pos.get('ps', 'BOTH')
                    amt = float(raw_pos.get('pa', 0))
                    
                    key = (symbol, side)
                    
                    if abs(amt) > 0:
                        # Position open/updated (delta merge).
                        # NOTE: Binance futures user data stream `ACCOUNT_UPDATE` does NOT include liquidationPrice
                        # (and often doesn't include markPrice/leverage either). Preserve the last-known values
                        # from the existing snapshot (seeded by REST at startup or refreshed via REST fallback).
                        prev = pos_map.get(key, {}) if isinstance(pos_map.get(key), dict) else {}

                        # Preserve liquidation price from previous snapshot (cross / multi-asset aware).
                        # Field name from REST is `liquidationPrice`.
                        try:
                            prev_liq = float(prev.get('liquidationPrice') or prev.get('lp') or 0.0)
                        except Exception:
                            prev_liq = 0.0

                        def _float_or_prev(v, prev_v) -> float:
                            try:
                                if v is None or v == "":
                                    return float(prev_v or 0.0)
                                return float(v)
                            except Exception:
                                try:
                                    return float(prev_v or 0.0)
                                except Exception:
                                    return 0.0

                        def _int_or_prev(v, prev_v) -> int:
                            try:
                                if v is None or v == "":
                                    return int(prev_v or 1)
                                return int(float(v))
                            except Exception:
                                try:
                                    return int(prev_v or 1)
                                except Exception:
                                    return 1

                        pos_map[key] = {
                            'symbol': symbol,
                            'positionSide': side,
                            'positionAmt': amt,
                            'entryPrice': _float_or_prev(raw_pos.get('ep'), prev.get('entryPrice')),
                            'markPrice': _float_or_prev(raw_pos.get('mp'), prev.get('markPrice')),
                            'unRealizedProfit': _float_or_prev(raw_pos.get('up'), prev.get('unRealizedProfit')),
                            'leverage': _int_or_prev(raw_pos.get('l'), prev.get('leverage')),
                            'marginType': raw_pos.get('mt', prev.get('marginType', 'cross')),
                            # Preserve last known liquidation price from REST snapshot (not present in ACCOUNT_UPDATE)
                            'liquidationPrice': prev_liq,
                        }
                    else:
                        # Position closed
                        pos_map.pop(key, None)
                
                self._positions = list(pos_map.values())
                self._positions_last_update = time.time()
            
            logger.debug(f"[WS-POSITIONS] Updated: {len(self._positions)} positions")
    
    def _process_order_update(self, data: Dict[str, Any]):
        """Process ORDER_TRADE_UPDATE event."""
        order_data = data.get('o', {})
        symbol = order_data.get('s')
        status = order_data.get('X')  # Order status
        side = order_data.get('S')
        order_type = order_data.get('o')
        
        logger.debug(f"[WS-ORDER] {symbol} {side} {order_type} - Status: {status}")
    
    # ========================================================================
    # REST FALLBACK
    # ========================================================================
    
    def _fetch_mark_price_rest(self, symbol: str) -> Optional[float]:
        """Fetch mark price from REST API."""
        try:
            resp = self._client.futures_mark_price(symbol=symbol)
            price = float(resp.get('markPrice', 0))
            
            if price > 0:
                with self._mark_lock:
                    self._mark_prices[symbol] = price
                    self._mark_price_last_update[symbol] = time.time()
                
                logger.debug(f"[REST-MARK] {symbol}: {price}")
                return price
        except Exception as e:
            logger.debug(f"[REST-MARK] Failed for {symbol}: {e}")
        return None
    
    def _fetch_index_price_rest(self, symbol: str) -> Optional[float]:
        """Fetch index price from REST API."""
        try:
            # Index price is available in mark price endpoint
            resp = self._client.futures_mark_price(symbol=symbol)
            price = float(resp.get('indexPrice', 0))
            
            if price > 0:
                with self._index_lock:
                    self._index_prices[symbol] = price
                    self._index_price_last_update[symbol] = time.time()
                
                logger.debug(f"[REST-INDEX] {symbol}: {price}")
                return price
        except Exception as e:
            logger.debug(f"[REST-INDEX] Failed for {symbol}: {e}")
        return None
    
    def _fetch_positions_rest(self) -> List[Dict[str, Any]]:
        """Fetch positions from REST API."""
        try:
            positions_raw = self._client.futures_position_information()
            
            positions = []
            for pos in positions_raw:
                amt = float(pos.get('positionAmt', 0))
                if abs(amt) > 0:
                    positions.append({
                        'symbol': pos.get('symbol'),
                        'positionSide': pos.get('positionSide', 'BOTH'),
                        'positionAmt': amt,
                        'entryPrice': float(pos.get('entryPrice', 0)),
                        'markPrice': float(pos.get('markPrice', 0)),
                        'unRealizedProfit': float(pos.get('unRealizedProfit', 0)),
                        'leverage': int(pos.get('leverage', 1)),
                        'marginType': pos.get('marginType', 'cross'),
                        # CRITICAL: Use Binance-provided liquidation price (cross / multi-asset aware).
                        'liquidationPrice': float(pos.get('liquidationPrice', 0) or 0),
                    })
            
            with self._positions_lock:
                self._positions = positions
                self._positions_last_update = time.time()
            
            logger.debug(f"[REST-POSITIONS] Fetched {len(positions)} positions")
            return positions
            
        except Exception as e:
            logger.error(f"[REST-POSITIONS] Failed: {e}")
            return []
    
    def _fetch_balance_rest(self) -> Dict[str, Any]:
        """Fetch balance from REST API."""
        try:
            account = self._client.futures_account()
            
            balance = {
                'balance': float(account.get('totalWalletBalance', 0)),
                'available': float(account.get('availableBalance', 0)),
                'margin_balance': float(account.get('totalMarginBalance', 0)),
                'timestamp': time.time()
            }
            
            with self._balance_lock:
                self._balance = balance
                self._balance_last_update = time.time()
            
            # Publish to Redis for trainer's portfolio tracker
            if self._redis:
                try:
                    balance_key = f"trader:{self._account_id}:balance"
                    self._redis.hset(balance_key, mapping=balance)
                    self._redis.expire(balance_key, 300)  # 5 min TTL
                    logger.debug(f"[REST-BALANCE] Published to Redis: {balance_key}")
                except Exception as redis_err:
                    logger.debug(f"[REST-BALANCE] Failed to publish to Redis: {redis_err}")
            
            logger.debug(f"[REST-BALANCE] {balance}")
            return balance
            
        except Exception as e:
            logger.error(f"[REST-BALANCE] Failed: {e}")
            return {}
    
    # ========================================================================
    # BACKGROUND THREADS
    # ========================================================================
    
    def _keepalive_loop(self):
        """Keep listen key alive (runs every 30 minutes).
        
        Per Binance docs:
        - Listen key expires after 60 minutes without keepalive
        - Server sends ping every 3 minutes, expects pong within 10 minutes
        - We send keepalive immediately on connect, then every 30 minutes
        """
        # Send immediate keepalive on first connect (don't wait 30 min)
        try:
            if self._listen_key and self._connected:
                self._client.futures_stream_keepalive(self._listen_key)
                logger.info("[WS-KEEPALIVE] Initial listen key refresh on connect")
        except Exception as e:
            logger.warning(f"[WS-KEEPALIVE] Initial keepalive failed: {e}")
        
        while not self._stop_event.is_set():
            try:
                time.sleep(self.KEEPALIVE_INTERVAL_SECONDS)
                
                if self._listen_key and self._connected:
                    self._client.futures_stream_keepalive(self._listen_key)
                    logger.debug("[WS-KEEPALIVE] Listen key refreshed")
                    
            except Exception as e:
                logger.warning(f"[WS-KEEPALIVE] Failed: {e}")
    
    def _start_health_monitor(self):
        """Start health monitoring thread."""
        if self._health_monitor_thread and self._health_monitor_thread.is_alive():
            return
        
        self._health_monitor_thread = threading.Thread(
            target=self._health_monitor_loop,
            daemon=True,
            name=f"ws-health-{self._account_id}"
        )
        self._health_monitor_thread.start()
    
    def _health_monitor_loop(self):
        """Monitor websocket health and trigger fallback if needed."""
        while not self._stop_event.is_set():
            try:
                time.sleep(30)  # Check every 30 seconds
                
                if not self._connected:
                    continue
                
                now = time.time()
                stale_count = 0
                
                # NOTE: Mark price streams are disabled - skip staleness check
                # Mark prices are fetched via REST when needed by get_mark_price()
                
                # Check user data stream health (positions/balance)
                with self._positions_lock:
                    if (now - self._positions_last_update) > self.STALE_THRESHOLD_SECONDS:
                        stale_count += 1
                        logger.warning(f"[WS-HEALTH] User data stale: {now - self._positions_last_update:.0f}s")
                
                # Only trigger fallback if user data stream is stale
                if stale_count >= 1 and not self._fallback_mode:
                    self._activate_fallback()
                
            except Exception as e:
                logger.error(f"[WS-HEALTH] Monitor error: {e}", exc_info=True)
    
    def _activate_fallback(self):
        """Activate REST fallback mode."""
        self._fallback_mode = True
        self._connected = False
        self._last_disconnect_time = time.time()
        
        msg = f"⚠️ [WS-FALLBACK] WebSocket stale for {self._account_id}. Switching to REST fallback. Reconnecting every {self.RECONNECT_INTERVAL_SECONDS}s."
        logger.warning(msg)
        self._send_alert(msg)
    
    def _start_reconnect_monitor(self):
        """Start reconnection monitor thread."""
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            return
        
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop,
            daemon=True,
            name=f"ws-reconnect-{self._account_id}"
        )
        self._reconnect_thread.start()
    
    def _reconnect_loop(self):
        """Reconnection loop - attempts every 2 minutes when disconnected."""
        while not self._stop_event.is_set():
            try:
                # Respect any backoff window (rate-limit safe). Default cadence is RECONNECT_INTERVAL_SECONDS.
                now = time.time()
                next_ts = getattr(self, "_next_reconnect_time", 0.0) or 0.0
                if next_ts and now < next_ts:
                    time.sleep(max(1.0, float(next_ts - now)))
                else:
                    time.sleep(self.RECONNECT_INTERVAL_SECONDS)
                
                # Only reconnect if disconnected or in fallback
                if self._connected and not self._fallback_mode:
                    continue
                
                logger.info(f"[WS-RECONNECT] Attempting reconnection for {self._account_id}...")
                
                # Stop existing connections completely
                if self._twm:
                    try:
                        self._twm.stop()
                        # Wait for threads to fully stop
                        time.sleep(2)
                    except Exception as e:
                        logger.debug(f"[WS-RECONNECT] TWM stop error (ignored): {e}")
                    finally:
                        self._twm = None  # Clear reference to allow GC
                
                # Clear listen key
                self._listen_key = None
                
                # Attempt reconnection
                self._start_websocket()
                
                # Check if successful
                if self._connected and not self._fallback_mode:
                    msg = f"✅ [WS-RESTORED] WebSocket reconnected for {self._account_id}"
                    logger.info(msg)
                    self._send_alert(msg)
                
            except Exception as e:
                logger.error(f"[WS-RECONNECT] Failed: {e}", exc_info=True)
    
    # ========================================================================
    # UTILITIES
    # ========================================================================
    
    def _send_alert(self, message: str):
        """Send Telegram alert if notifier available."""
        if self._notifier:
            try:
                # TelegramNotifier.send_message is async; prefer sync-safe wrapper if present.
                send_sync = getattr(self._notifier, "send_message_sync", None)
                if callable(send_sync):
                    send_sync(message)
                else:
                    # Best-effort fallback (avoid "coroutine was never awaited" warnings)
                    import asyncio
                    try:
                        asyncio.run(self._notifier.send_message(message))  # type: ignore[attr-defined]
                    except RuntimeError:
                        # Running loop in this thread: fire-and-forget
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(self._notifier.send_message(message))  # type: ignore[attr-defined]
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"[TELEGRAM] Alert failed: {e}")


__all__ = ['TraderWebSocketHelper']
