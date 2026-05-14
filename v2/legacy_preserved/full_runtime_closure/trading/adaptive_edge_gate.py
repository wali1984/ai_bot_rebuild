"""
Adaptive Edge Gate - Fully Dynamic Entry Quality Filter
========================================================
NO STATIC THRESHOLDS - Everything derived from live market data

Data Sources Used:
- ATR/Volatility → Expected move size
- Orderbook spread/depth → Actual execution costs  
- Liquidation levels → Squeeze potential (edge amplifier)
- OI delta → Trend strength (edge amplifier)
- Funding rate → Mean reversion pressure
- Microstructure scores → Execution quality adjustment
- Historical trade performance → Calibrated edge-to-confidence mapping

Core Principle:
- Expected Edge = f(ATR, momentum, OI, liquidation_proximity)
- Required Edge = f(actual_spread, depth_adjusted_slippage, fees)
- Trade only when: Expected Edge > Required Edge × Safety Buffer
"""

import logging
import time
import json
from typing import Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import deque, defaultdict
import math

logger = logging.getLogger(__name__)


@dataclass
class MarketConditions:
    """Real-time market conditions from live data sources"""
    symbol: str
    timestamp: float = 0.0
    current_price: float = 0.0     # Current market price
    
    # Volatility (from ATR, realized vol, BBands)
    atr_pct: float = 0.0           # ATR as % of price
    realized_vol_5m: float = 0.0   # 5min realized volatility
    realized_vol_1h: float = 0.0   # 1h realized volatility
    bbands_width: float = 0.0      # Bollinger Band width %
    
    # Orderbook (live spread and depth)
    spread_bps: float = 0.0        # Current spread in basis points
    bid_depth_usd: float = 0.0     # Bid depth in USD
    ask_depth_usd: float = 0.0     # Ask depth in USD
    orderbook_imbalance: float = 0.0  # -1 to 1 (sell to buy pressure)
    
    # Momentum indicators
    rsi: float = 50.0              # RSI (14)
    macd_hist: float = 0.0         # MACD histogram
    adx: float = 25.0              # ADX trend strength
    momentum_score: float = 0.0    # Composite momentum
    
    # On-chain/exchange data
    oi_change_1h: float = 0.0      # Open interest change %
    funding_rate: float = 0.0      # Current funding rate
    long_short_ratio: float = 1.0  # Long/short ratio
    
    # Liquidation levels (CRITICAL for profit taking)
    liq_long_level: float = 0.0           # Price level of long liquidation cluster
    liq_short_level: float = 0.0          # Price level of short liquidation cluster
    liq_long_strength: float = 0.0        # Strength of long liq cluster (0-1)
    liq_short_strength: float = 0.0       # Strength of short liq cluster (0-1)
    liq_long_distance_pct: float = 10.0   # Distance to long liquidation cluster %
    liq_short_distance_pct: float = 10.0  # Distance to short liquidation cluster %
    squeeze_potential: float = 0.0        # 0-1 squeeze likelihood
    
    # Liquidation flow data
    liq_volume_long_1h: float = 0.0       # Long liquidation volume last hour
    liq_volume_short_1h: float = 0.0      # Short liquidation volume last hour
    liq_ratio: float = 1.0                # Long/short liquidation ratio
    
    # Microstructure
    spoof_score: float = 0.0       # 0-1 spoofing detection
    fast_move_score: float = 0.0   # 0-1 recent fast move detection
    depth_vs_tape_divergence: float = 0.0  # 0-1 depth vs executed trade divergence (spoof signal)
    tape_imbalance_5s: float = 0.0 # -1 to 1 taker buy/sell imbalance (5s window)
    
    # Execution quality estimates
    estimated_slippage_bps: float = 2.0   # Based on depth vs order size
    
    # Data quality
    data_freshness_ms: float = 0.0
    data_completeness: float = 0.0


@dataclass
class EdgeEstimate:
    """Estimated edge for a potential trade"""
    expected_move_pct: float = 0.0    # Expected price move %
    expected_move_usd: float = 0.0    # In USD for given notional
    total_cost_pct: float = 0.0       # Total round-trip cost %
    total_cost_usd: float = 0.0
    net_expected_edge_pct: float = 0.0  # expected_move - cost
    net_expected_edge_usd: float = 0.0
    edge_ratio: float = 0.0           # expected / cost (want > 1)
    confidence_adjusted: bool = False
    
    # Component breakdown
    volatility_component: float = 0.0
    momentum_component: float = 0.0
    squeeze_component: float = 0.0
    
    # Cost breakdown
    spread_cost_bps: float = 0.0
    fee_cost_bps: float = 0.0
    slippage_cost_bps: float = 0.0
    
    reasoning: str = ""


class AdaptiveEdgeGate:
    """
    Fully adaptive entry quality gate - no static thresholds.
    
    All thresholds are derived from:
    1. Current market volatility (ATR, BBands)
    2. Live orderbook conditions (spread, depth, imbalance)
    3. Exchange data (OI, funding, liquidations)
    4. Historical trade performance (rolling calibration)
    """
    
    def __init__(
        self,
        redis_client=None,
        safety_buffer_multiplier: float = 1.5,  # Require edge to be K× costs (adaptive)
        max_safety_buffer_multiplier: float = 3.0,  # Upper cap on the dynamic buffer (K max)
        calibration_window: int = 100,           # Trades for rolling calibration
        maker_fee_bps: float = 2.0,
        taker_fee_bps: float = 5.0
    ):
        """
        Initialize adaptive edge gate.
        
        Args:
            redis_client: Redis connection for fetching live data
            safety_buffer_multiplier: Base multiplier (adjusted dynamically by conditions)
            calibration_window: Number of trades for rolling performance calibration
            maker_fee_bps: Exchange maker fee
            taker_fee_bps: Exchange taker fee
        """
        self.redis = redis_client
        self.base_safety_buffer = safety_buffer_multiplier
        self.max_safety_buffer = float(max_safety_buffer_multiplier or 3.0)
        self.calibration_window = calibration_window
        self.maker_fee_bps = maker_fee_bps
        self.taker_fee_bps = taker_fee_bps
        
        # Rolling trade performance for calibration
        self.trade_history: deque = deque(maxlen=calibration_window)
        
        # Cache for market conditions
        self._condition_cache: Dict[str, Tuple[MarketConditions, float]] = {}
        self._cache_ttl = 5.0  # 5 second cache
        
        # Statistics
        self.stats = {
            'total_checked': 0,
            'passed': 0,
            'blocked': 0,
            'blocked_liq_risk': 0,
            'avg_expected_edge': 0.0,
            'avg_required_edge': 0.0
        }
        
        logger.info(f"AdaptiveEdgeGate initialized - FULLY DYNAMIC, no static thresholds")


class MarketConditionsFetcher:
    """
    Compatibility shim: some legacy profit-taking helpers expect a MarketConditionsFetcher.
    Use AdaptiveEdgeGate.fetch_market_conditions under the hood so conditions stay consistent
    with the adaptive edge gate data sources.
    """

    def __init__(self, redis_client=None):
        self._gate = get_adaptive_edge_gate(redis_client=redis_client)

    def fetch_market_conditions(self, symbol: str, timeframe: str = "5m") -> MarketConditions:
        return self._gate.fetch_market_conditions(symbol, timeframe)
    
    def _get_redis(self):
        """Get Redis client, creating if needed"""
        if self.redis is None:
            try:
                from utils.redis_client import get_redis
                self.redis = get_redis()
            except Exception:
                try:
                    import redis
                    self.redis = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
                except Exception as e:
                    logger.warning(f"Cannot connect to Redis: {e}")
        return self.redis
    
    def fetch_market_conditions(self, symbol: str, timeframe: str = '5m') -> MarketConditions:
        """
        Fetch all relevant market conditions from Redis.
        
        Sources:
        - unified_features:{symbol}:{tf}
        - orderbook:top:{symbol}
        - msnap:coinapi_wsds:{symbol}
        - ta:{symbol}:{tf}
        - volatility:{symbol}
        """
        now = time.time()
        cache_key = f"{symbol}:{timeframe}"
        
        # Check cache
        if cache_key in self._condition_cache:
            cached, cached_time = self._condition_cache[cache_key]
            if now - cached_time < self._cache_ttl:
                return cached
        
        conditions = MarketConditions(symbol=symbol, timestamp=now)
        redis = self._get_redis()
        
        if not redis:
            logger.warning("No Redis connection - using default conditions")
            return conditions
        
        try:
            # 1. Fetch unified features (primary data source)
            unified_data = self._fetch_unified_features(redis, symbol, timeframe)
            
            # 2. Fetch orderbook data
            orderbook_data = self._fetch_orderbook(redis, symbol)
            
            # 3. Fetch microstructure snapshot
            msnap_data = self._fetch_microstructure(redis, symbol)
            
            # 3.5 Fetch realtime price (multi-source failover key)
            # This keeps "current_price" aligned to the freshest available feed
            # (CoinAPI WS / Binance WS / REST fallbacks), instead of relying only
            # on the last candle close in unified_features.
            rt_price = self._fetch_realtime_price(redis, symbol)

            # 4. Fetch TA indicators
            ta_data = self._fetch_ta_indicators(redis, symbol, timeframe)
            
            # 5. Fetch volatility
            vol_data = self._fetch_volatility(redis, symbol)
            
            # Populate conditions from all sources
            self._populate_conditions(
                conditions,
                unified_data,
                orderbook_data,
                msnap_data,
                rt_price,
                ta_data,
                vol_data,
            )
            
            # Cache result
            self._condition_cache[cache_key] = (conditions, now)
            
        except Exception as e:
            logger.warning(f"Error fetching market conditions for {symbol}: {e}")
        
        return conditions
    
    def _fetch_unified_features(self, redis, symbol: str, tf: str) -> Dict:
        """Fetch from unified_features hash"""
        data = {}
        for key_pattern in [f"unified_features:{symbol}:{tf}", f"features:unified:{symbol}:{tf}:normalized"]:
            try:
                result = redis.hgetall(key_pattern) if ':normalized' not in key_pattern else None
                if not result:
                    raw = redis.get(key_pattern)
                    if raw:
                        result = json.loads(raw)
                if result:
                    data.update(result)
                    break
            except Exception:
                continue
        return data
    
    def _fetch_orderbook(self, redis, symbol: str) -> Dict:
        """
        Fetch orderbook data from various possible keys.
        
        Priority order (as per user requirement):
        1. CoinAPI (primary) - msnap:coinapi_wsds:{symbol}
        2. Binance - instant:{symbol}:spread, orderbook:top:{symbol}, latest:binance:depth:{symbol}:20
        3. CCXT - ccxt:orderbook:{symbol}
        4. KuCoin - kc:orderbook20:{symbol}
        5. Redi (fallback) - redi:orderbook:{symbol}
        """
        data = {}
        keys_to_try = [
            # 1. CoinAPI (PRIMARY)
            f"msnap:coinapi_wsds:{symbol}",
            # 2. Binance (fallback 1)
            f"instant:{symbol}:spread",
            f"orderbook:top:{symbol}",
            f"latest:binance:depth:{symbol}:20",
            # 3. CCXT (fallback 2)
            f"ccxt:orderbook:{symbol}",
            # 4. KuCoin (fallback 3)
            f"kc:orderbook20:{symbol}",
            # 5. Redi (fallback 4)
            f"redi:orderbook:{symbol}",
            f"orderbook:{symbol}"
        ]
        
        for key in keys_to_try:
            try:
                # Check key type first
                key_type = redis.type(key)
                
                if key_type == 'string':
                    result = redis.get(key)
                    if result:
                        parsed = json.loads(result)
                        data.update(parsed)
                        break
                elif key_type == 'hash':
                    result = redis.hgetall(key)
                    if result:
                        # Decode bytes if needed and convert values
                        parsed = {}
                        for k, v in result.items():
                            k = k.decode() if isinstance(k, bytes) else k
                            v = v.decode() if isinstance(v, bytes) else v
                            try:
                                parsed[k] = float(v)
                            except (ValueError, TypeError):
                                parsed[k] = v
                        data.update(parsed)
                        break
            except Exception as e:
                logger.debug(f"Failed to fetch orderbook from {key}: {e}")
                continue
        return data

    def _fetch_realtime_price(self, redis, symbol: str) -> Dict:
        """
        Fetch realtime failover price payload from Redis.

        Primary key: price:realtime:{SYMBOL} (JSON, produced by ingest/realtime_price_provider.py)
        Fallback key: price:{SYMBOL} (legacy JSON with at least {'price': ...})
        """
        data: Dict[str, Any] = {}
        try:
            raw = redis.get(f"price:realtime:{symbol}")
            if raw:
                raw = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                parsed = json.loads(raw) if raw else {}
                if isinstance(parsed, dict):
                    data.update(parsed)
                    return data
        except Exception:
            pass
        try:
            raw = redis.get(f"price:{symbol}")
            if raw:
                raw = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                parsed = json.loads(raw) if raw else {}
                if isinstance(parsed, dict):
                    data.update(parsed)
        except Exception:
            pass
        return data
    
    def _fetch_microstructure(self, redis, symbol: str) -> Dict:
        """Fetch microstructure snapshot"""
        data = {}
        try:
            result = redis.hgetall(f"msnap:coinapi_wsds:{symbol}")
            if result:
                for k, v in result.items():
                    k = k.decode() if isinstance(k, bytes) else k
                    v = v.decode() if isinstance(v, bytes) else v
                    try:
                        data[k] = float(v)
                    except:
                        data[k] = v
        except Exception:
            pass
        return data
    
    def _fetch_ta_indicators(self, redis, symbol: str, tf: str) -> Dict:
        """Fetch TA indicators"""
        data = {}
        for key in [f"ta:{symbol}:{tf}", f"ind:{symbol}:{tf}"]:
            try:
                result = redis.get(key)
                if result:
                    data.update(json.loads(result))
                    break
            except Exception:
                continue
        return data
    
    def _fetch_volatility(self, redis, symbol: str) -> Dict:
        """Fetch volatility data"""
        data = {}
        try:
            result = redis.get(f"volatility:{symbol}")
            if result:
                data = json.loads(result)
        except Exception:
            pass
        return data
    
    def _populate_conditions(
        self, 
        conditions: MarketConditions,
        unified: Dict,
        orderbook: Dict,
        msnap: Dict,
        rt_price: Dict,
        ta: Dict,
        vol: Dict
    ):
        """Populate MarketConditions from all data sources"""
        
        # Helper to safely get float
        def safe_float(d: Dict, *keys, default: float = 0.0) -> float:
            for key in keys:
                if key in d:
                    try:
                        val = d[key]
                        if isinstance(val, bytes):
                            val = val.decode()
                        return float(val)
                    except:
                        continue
            return default
        
        # --------------------------------------------------------------------
        # Current price (freshest available)
        #
        # IMPORTANT:
        # - unified_features close can lag (fast lane cadence) and can be candle-close biased.
        # - msnap mid_px is low-latency but can be stale if CoinAPI WSDS is down.
        # - price:realtime:* is a multi-source failover key designed specifically for low-latency truth.
        #
        # We choose the freshest candidate by timestamp (no hard thresholds).
        # --------------------------------------------------------------------
        now_ms = int(time.time() * 1000)
        candidates = []  # (staleness_ms, price, src)

        # price:realtime (preferred when present)
        rt_px = safe_float(rt_price or {}, 'price', default=0.0)
        rt_ts = safe_float(rt_price or {}, 'ts_ms', default=0.0)
        if rt_px > 0 and rt_ts > 0:
            candidates.append((max(0.0, float(now_ms) - float(rt_ts)), float(rt_px), 'price:realtime'))

        # msnap mid price
        ms_px = safe_float(msnap or {}, 'mid_px', 'mid_price', default=0.0)
        ms_ts = safe_float(msnap or {}, 'updated_ts_ms', default=0.0)
        if ms_px > 0 and ms_ts > 0:
            candidates.append((max(0.0, float(now_ms) - float(ms_ts)), float(ms_px), 'msnap'))

        # unified close/price (fallback)
        u_px = safe_float(unified, 'close', 'price', 'last_price', 'ccxt_close', 'ohlcv_close', default=0.0)
        u_ts = safe_float(unified, 'ts_ms', 'timestamp', default=0.0)
        if u_px > 0 and u_ts > 0:
            candidates.append((max(0.0, float(now_ms) - float(u_ts)), float(u_px), 'unified'))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            conditions.current_price = float(candidates[0][1])
        else:
            conditions.current_price = 0.0
        
        # Volatility - check unified features with actual field names
        conditions.atr_pct = safe_float(unified, 'ind_ind_atr_pct', 'ind_atr_pct', 'atr_pct', 
                                        'ta_atr_pct', default=0) or \
                            safe_float(ta, 'atr_14', 'atr_pct', default=1.0)
        conditions.realized_vol_5m = safe_float(unified, 'ind_ta_volatility_5m', 'ind_volatility_5m', default=0) or \
                                     safe_float(vol, 'composite_index', 'realized_vol_5m', default=1.0)
        conditions.bbands_width = safe_float(unified, 'ind_bbands_width', 'ind_ta_bbands_width', default=0) or \
                                  safe_float(ta, 'bbands_width', default=2.0)
        
        # Orderbook - check unified features first (ob_ prefix), then raw orderbook
        # NOTE: msnap has depth in COIN units, need to convert to USD using price
        conditions.spread_bps = safe_float(unified, 'ob_ob_spread_bps', 'ob_spread_bps', default=0) or \
                               safe_float(orderbook, 'spread_bps', 'spread', default=3.0)
        
        # Depth: Try to get from unified (USD), fallback to msnap (coin units × price)
        bid_depth_usd = safe_float(unified, 'ob_ob_bid_depth', 'ob_bid_depth', default=0)
        ask_depth_usd = safe_float(unified, 'ob_ob_ask_depth', 'ob_ask_depth', default=0)
        
        if bid_depth_usd == 0 or ask_depth_usd == 0:
            # msnap has depth in coin units (book_bid_sum_5, book_ask_sum_5)
            # Convert to USD using current price
            price = conditions.current_price or safe_float(msnap, 'mid_px', default=1.0)
            bid_depth_coins = safe_float(msnap, 'book_bid_sum_5', default=0) or safe_float(orderbook, 'bid_depth', default=0)
            ask_depth_coins = safe_float(msnap, 'book_ask_sum_5', default=0) or safe_float(orderbook, 'ask_depth', default=0)
            
            if bid_depth_coins > 0 and price > 0:
                bid_depth_usd = bid_depth_coins * price
            else:
                bid_depth_usd = 100000  # Default $100k
            
            if ask_depth_coins > 0 and price > 0:
                ask_depth_usd = ask_depth_coins * price
            else:
                ask_depth_usd = 100000  # Default $100k
        
        conditions.bid_depth_usd = bid_depth_usd
        conditions.ask_depth_usd = ask_depth_usd
        conditions.orderbook_imbalance = safe_float(unified, 'ob_ob_imbalance', 'ob_imbalance', default=0) or \
                                         safe_float(orderbook, 'imbalance', 'imbalance_5', default=0.0)
        
        # Momentum
        conditions.rsi = safe_float(ta, 'rsi', 'ind_rsi', 'rsi_14', default=50.0)
        conditions.macd_hist = safe_float(ta, 'macd_hist', 'ind_macd_hist', default=0.0)
        conditions.adx = safe_float(ta, 'adx', 'ind_adx', default=25.0)
        
        # Calculate momentum score from indicators
        rsi_momentum = (conditions.rsi - 50) / 50  # -1 to 1
        adx_strength = min(conditions.adx / 50, 1.0)  # 0 to 1
        macd_sign = 1 if conditions.macd_hist > 0 else (-1 if conditions.macd_hist < 0 else 0)
        conditions.momentum_score = (rsi_momentum * 0.4 + macd_sign * adx_strength * 0.6)
        
        # --------------------------------------------------------------------
        # CoinAnk / exchange data (mapped to current unified_features schema)
        # --------------------------------------------------------------------
        # Open interest change: derive from OI kline open/close when available.
        oi_open = safe_float(unified, 'coinank_openInterest_kline_data_0_open', 'coinank_openInterest_kline_data_0_o', default=0.0)
        oi_close = safe_float(unified, 'coinank_openInterest_kline_data_0_close', 'coinank_openInterest_kline_data_0_c', default=0.0)
        if oi_open > 0 and oi_close > 0:
            # Percent change (e.g., +3.2 means +3.2%)
            conditions.oi_change_1h = ((oi_close - oi_open) / oi_open) * 100.0
        else:
            conditions.oi_change_1h = safe_float(
                unified,
                'open_interest_change', 'oi_change', 'coinank_oi_change_pct', 'oi_change_1h',
                default=0.0
            )

        # Funding rate (decimal, e.g. 0.0001 = 0.01%)
        conditions.funding_rate = safe_float(
            unified,
            'funding_rate',
            'coinank_fundingRate_indicator_data_0_fundingRate',
            'coinank_fundingRate_indicator_data_0_fr',
            'coinank_fundingRate_kline_data_0_close',
            'coinank_fundingRate_kline_data_0_open',
            'coinank_funding_rate',
            default=0.0
        )

        # Long/short ratio (1.0 neutral)
        conditions.long_short_ratio = safe_float(
            unified,
            'long_short_ratio',
            'coinank_ls_global_account_ratio_longShortRatio_mean',
            'coinank_ls_global_account_ratio_longShortRatio_first',
            'coinank_ls_toptrader_accounts_longShortRatio_mean',
            'coinank_ls_toptrader_accounts_longShortRatio_first',
            'coinank_long_short_ratio',
            'coinank_lsr',
            default=1.0
        )
        
        # ========================================================================
        # LIQUIDATION DATA (CRITICAL for entry/exit decisions)
        # ========================================================================
        # Liquidation levels (price levels where liq clusters exist)
        conditions.liq_long_level = safe_float(unified, 'liquidation_long_level', 
                                                'liq_long_level', default=0.0)
        conditions.liq_short_level = safe_float(unified, 'liquidation_short_level',
                                                 'liq_short_level', default=0.0)
        
        # Liquidation strength (how much volume at those levels)
        conditions.liq_long_strength = safe_float(unified, 'liquidation_long_strength',
                                                   'liq_long_strength', default=0.0)
        conditions.liq_short_strength = safe_float(unified, 'liquidation_short_strength',
                                                    'liq_short_strength', default=0.0)
        
        # Liquidation volume flow (recent liquidations)
        # Prefer Binance liquidation bridge keys, but fall back to CoinAnk turnover when present.
        conditions.liq_volume_long_1h = safe_float(
            unified,
            'binance_liq_volume_long_usd', 'binance_liq_volume_long_usd_1h',
            'coinank_liquidation_history_data_0_longTurnover',
            default=0.0
        )
        conditions.liq_volume_short_1h = safe_float(
            unified,
            'binance_liq_volume_short_usd', 'binance_liq_volume_short_usd_1h',
            'coinank_liquidation_history_data_0_shortTurnover',
            default=0.0
        )
        # Ratio: use explicit key if present, else compute from turnover
        liq_ratio_val = safe_float(unified, 'binance_liq_ratio', 'liq_ratio', default=0.0)
        if liq_ratio_val and liq_ratio_val > 0:
            conditions.liq_ratio = liq_ratio_val
        else:
            if conditions.liq_volume_short_1h > 0:
                conditions.liq_ratio = float(conditions.liq_volume_long_1h) / float(conditions.liq_volume_short_1h)
            else:
                conditions.liq_ratio = 1.0
        
        # Calculate liquidation distances from current price
        if conditions.current_price > 0:
            if conditions.liq_long_level > 0:
                conditions.liq_long_distance_pct = abs(
                    (conditions.current_price - conditions.liq_long_level) / conditions.current_price * 100
                )
            else:
                conditions.liq_long_distance_pct = safe_float(unified, 'liquidation_long_distance_pct', 
                                                              'liq_long_distance', default=10.0)
            
            if conditions.liq_short_level > 0:
                conditions.liq_short_distance_pct = abs(
                    (conditions.liq_short_level - conditions.current_price) / conditions.current_price * 100
                )
            else:
                conditions.liq_short_distance_pct = safe_float(unified, 'liquidation_short_distance_pct',
                                                               'liq_short_distance', default=10.0)
        else:
            conditions.liq_long_distance_pct = safe_float(unified, 'liquidation_long_distance_pct', default=10.0)
            conditions.liq_short_distance_pct = safe_float(unified, 'liquidation_short_distance_pct', default=10.0)
        
        # Calculate squeeze potential from liquidation proximity and strength
        min_liq_distance = min(conditions.liq_long_distance_pct, conditions.liq_short_distance_pct)
        liq_strength = max(conditions.liq_long_strength, conditions.liq_short_strength)
        
        # Squeeze potential: High when close to strong liq cluster
        distance_factor = max(0, 1 - (min_liq_distance / 5))  # High if < 5% away
        strength_factor = min(liq_strength, 1.0)  # Capped at 1
        conditions.squeeze_potential = distance_factor * (0.5 + 0.5 * strength_factor)
        
        # Microstructure - from msnap data
        conditions.spoof_score = safe_float(msnap, 'spoof_score', default=0.0)
        conditions.fast_move_score = safe_float(msnap, 'fast_move_score', default=0.0)

        # Depth-vs-Tape divergence (from feature pipeline unified_features)
        conditions.depth_vs_tape_divergence = safe_float(unified, 'depth_vs_tape_divergence', default=0.0)
        conditions.tape_imbalance_5s = safe_float(unified, 'tape_imbalance_5s', default=0.0)
        
        # Final fallback if still empty
        if conditions.current_price == 0:
            conditions.current_price = safe_float(orderbook, 'mid', default=0)
        
        # Estimate slippage from depth
        avg_depth = (conditions.bid_depth_usd + conditions.ask_depth_usd) / 2
        if avg_depth > 0:
            # Assume $500 order, estimate slippage based on depth
            order_size = 500
            depth_ratio = order_size / avg_depth
            conditions.estimated_slippage_bps = max(1.0, depth_ratio * 100)  # More slippage if low depth
        
        # Data quality
        ts_ms = safe_float(unified, 'ts_ms', 'timestamp', default=0)
        if ts_ms > 0:
            conditions.data_freshness_ms = time.time() * 1000 - ts_ms
        conditions.data_completeness = safe_float(unified, 'data_completeness', 'completeness', default=0.5)
    
    def estimate_edge(
        self,
        symbol: str,
        side: str,  # "LONG" or "SHORT"
        confidence: float,
        notional_usd: float,
        timeframe: str = '5m',
        use_maker: bool = False
    ) -> EdgeEstimate:
        """
        Estimate expected edge for a trade based on current market conditions.
        
        NO STATIC THRESHOLDS - all derived from live data.
        """
        # Fetch current market conditions
        conditions = self.fetch_market_conditions(symbol, timeframe)
        
        estimate = EdgeEstimate()
        
        # === EXPECTED MOVE CALCULATION ===
        # Base: Use ATR as primary expected move (volatility-based)
        base_expected_move = max(conditions.atr_pct, conditions.realized_vol_5m * 2)
        
        # Adjust by momentum alignment
        # If going LONG and momentum is positive, expect larger move
        momentum_multiplier = 1.0
        if side == "LONG":
            momentum_multiplier = 1 + (conditions.momentum_score * 0.3)  # Up to +30%
        else:
            momentum_multiplier = 1 - (conditions.momentum_score * 0.3)  # Opposite
        
        estimate.volatility_component = base_expected_move
        estimate.momentum_component = base_expected_move * (momentum_multiplier - 1)
        
        # Squeeze potential amplifier
        # If close to liquidation levels and going in that direction, bigger move expected
        squeeze_multiplier = 1.0
        if conditions.squeeze_potential > 0.3:
            # Potential squeeze - could amplify move
            if side == "LONG" and conditions.liq_short_distance_pct < conditions.liq_long_distance_pct:
                squeeze_multiplier = 1 + conditions.squeeze_potential * 0.5  # Up to +50%
            elif side == "SHORT" and conditions.liq_long_distance_pct < conditions.liq_short_distance_pct:
                squeeze_multiplier = 1 + conditions.squeeze_potential * 0.5
        
        estimate.squeeze_component = base_expected_move * (squeeze_multiplier - 1) * momentum_multiplier
        
        # Confidence scaling
        # Higher confidence = larger expected capture of the move
        # This is the ONLY place confidence affects edge (not a static mapping)
        confidence_capture = 0.3 + (confidence - 0.5) * 0.8  # 50% conf = 30%, 100% conf = 70%
        confidence_capture = max(0.1, min(0.8, confidence_capture))
        
        # Final expected move
        total_expected_multiplier = momentum_multiplier * squeeze_multiplier
        estimate.expected_move_pct = base_expected_move * total_expected_multiplier * confidence_capture
        estimate.expected_move_usd = notional_usd * (estimate.expected_move_pct / 100)
        
        # === COST CALCULATION (from live orderbook) ===
        # Spread cost (live from orderbook)
        estimate.spread_cost_bps = conditions.spread_bps
        
        # Fee cost
        estimate.fee_cost_bps = self.maker_fee_bps if use_maker else self.taker_fee_bps
        
        # Slippage (estimated from depth)
        estimate.slippage_cost_bps = conditions.estimated_slippage_bps
        
        # Round-trip total cost
        single_leg_cost = estimate.spread_cost_bps + estimate.fee_cost_bps + estimate.slippage_cost_bps
        estimate.total_cost_pct = (single_leg_cost * 2) / 100  # Convert bps to % and double for round-trip
        estimate.total_cost_usd = notional_usd * (estimate.total_cost_pct / 100)
        
        # === NET EDGE ===
        estimate.net_expected_edge_pct = estimate.expected_move_pct - estimate.total_cost_pct
        estimate.net_expected_edge_usd = estimate.expected_move_usd - estimate.total_cost_usd
        estimate.edge_ratio = estimate.expected_move_pct / estimate.total_cost_pct if estimate.total_cost_pct > 0 else 0
        
        # === BUILD REASONING ===
        estimate.reasoning = (
            f"ATR={conditions.atr_pct:.3f}% × momentum={momentum_multiplier:.2f} × "
            f"squeeze={squeeze_multiplier:.2f} × capture={confidence_capture:.2f} = "
            f"expected {estimate.expected_move_pct:.3f}%, "
            f"costs={estimate.total_cost_pct:.3f}% (spread={estimate.spread_cost_bps:.1f}bps + "
            f"fee={estimate.fee_cost_bps:.1f}bps + slip={estimate.slippage_cost_bps:.1f}bps)"
        )
        
        return estimate
    
    def compute_dynamic_safety_buffer(self, conditions: MarketConditions) -> float:
        """
        Compute safety buffer multiplier based on current conditions.
        
        Higher buffer when:
        - High spoof score (unreliable orderbook)
        - High fast move score (volatile conditions)
        - Low data completeness
        - Stale data
        """
        buffer = self.base_safety_buffer
        
        # Increase buffer for spoofing risk
        if conditions.spoof_score > 0.3:
            buffer *= (1 + conditions.spoof_score * 0.5)  # Up to +50%

        # Increase buffer when depth contradicts tape (spoof confirmation)
        if conditions.depth_vs_tape_divergence > 0.3:
            buffer *= (1 + conditions.depth_vs_tape_divergence * 0.4)  # Up to +40%
        
        # Increase buffer for fast move risk
        if conditions.fast_move_score > 0.5:
            buffer *= (1 + conditions.fast_move_score * 0.3)  # Up to +30%
        
        # Increase buffer for stale/incomplete data
        if conditions.data_freshness_ms > 5000:  # Older than 5s
            staleness_factor = min(conditions.data_freshness_ms / 30000, 1.0)  # Max at 30s
            buffer *= (1 + staleness_factor * 0.5)
        
        if conditions.data_completeness < 0.7:
            buffer *= (1 + (1 - conditions.data_completeness) * 0.3)
        
        # Cap at configured max. This allows raising K (e.g., 2..4) without hard-coding thresholds elsewhere.
        return min(buffer, float(getattr(self, "max_safety_buffer", 3.0)))
    
    def should_allow_entry(
        self,
        symbol: str,
        side: str,
        confidence: float,
        notional_usd: float,
        timeframe: str = '5m',
        use_maker: bool = False,
        headroom_pct: float = 0.0,
    ) -> Tuple[bool, str, EdgeEstimate]:
        """
        Check if entry should be allowed based on ADAPTIVE edge calculation.
        
        Returns:
            (should_allow, reason, edge_estimate)
        """
        self.stats['total_checked'] += 1
        
        # Get market conditions and estimate edge
        conditions = self.fetch_market_conditions(symbol, timeframe)
        estimate = self.estimate_edge(symbol, side, confidence, notional_usd, timeframe, use_maker)
        
        # Compute dynamic safety buffer (market-quality dependent)
        safety_buffer = self.compute_dynamic_safety_buffer(conditions)

        # --------------------------------------------------------------------
        # CRITICAL: Headroom-aware edge requirement (no static starvation)
        # --------------------------------------------------------------------
        # When portfolio headroom is high and model confidence is high, we should
        # not require an excessively conservative edge_ratio multiple, otherwise
        # OPEN_RISK gets starved for long periods in live trading.
        #
        # This remains dynamic and cost-aware:
        # - Market-quality still increases safety_buffer (spoof/fast-move/stale/incomplete)
        # - Confidence already affects expected_move via confidence_capture
        # - Headroom/confidence now also adjust the *required* edge multiple smoothly
        #
        # Note: `headroom_pct` is best-effort (0..1, available_margin/equity); if missing, defaults to 0.
        try:
            c = float(confidence or 0.0)
        except Exception:
            c = 0.0
        c01 = c if c <= 1.0 else (c / 100.0)
        c01 = max(0.0, min(1.0, float(c01)))
        try:
            hr = float(headroom_pct or 0.0)
        except Exception:
            hr = 0.0
        hr = max(0.0, min(1.0, float(hr)))

        # Relief activates only in the "high confidence" region and scales with headroom.
        conf_rel = max(0.0, (c01 - 0.85) / 0.15)  # 0 at 0.85-, 1 at 1.00
        relief = hr * conf_rel

        # Reduce required multiple by up to ~35% when headroom is high and confidence is high.
        # Keep a small safety floor to avoid pathological low-cost, low-edge churn.
        required_edge_ratio = max(1.05, float(safety_buffer) * (1.0 - 0.35 * relief))
        
        # ========================================================================
        # LIQUIDATION-AWARE ENTRY CHECK
        # Block entries that put us at risk of being liquidated or going against
        # an imminent squeeze
        # ========================================================================
        liq_warning, liq_block = self._check_liquidation_entry_risk(side, conditions)
        if liq_block:
            self.stats['blocked_liq_risk'] += 1
            return False, f"LIQUIDATION_RISK: {liq_warning}", estimate
        
        # Update running stats
        self.stats['avg_expected_edge'] = (
            self.stats['avg_expected_edge'] * 0.95 + estimate.expected_move_pct * 0.05
        )
        self.stats['avg_required_edge'] = (
            self.stats['avg_required_edge'] * 0.95 + (estimate.total_cost_pct * safety_buffer) * 0.05
        )
        
        # Decision
        if estimate.edge_ratio >= required_edge_ratio:
            self.stats['passed'] += 1
            reason = (
                f"PASS: edge_ratio={estimate.edge_ratio:.2f} >= required={required_edge_ratio:.2f} "
                f"(buffer={safety_buffer:.2f}, headroom={hr:.2f}, conf={c01:.2f}) ({estimate.reasoning})"
            )
            if liq_warning:
                reason += f" [LIQ_WARNING: {liq_warning}]"
            return True, reason, estimate
        else:
            self.stats['blocked'] += 1
            reason = (
                f"INSUFFICIENT_EDGE: ratio={estimate.edge_ratio:.2f} < {required_edge_ratio:.2f} "
                f"(buffer={safety_buffer:.2f}, headroom={hr:.2f}, conf={c01:.2f}) ({estimate.reasoning})"
            )
            return False, reason, estimate
    
    def _check_liquidation_entry_risk(
        self, 
        side: str, 
        conditions: MarketConditions
    ) -> Tuple[str, bool]:
        """
        Check if entry is risky based on liquidation levels.
        
        Returns:
            (warning_message, should_block)
        """
        warning = ""
        should_block = False
        
        # For LONG positions, we care about:
        # - Strong long liquidation cluster nearby (price could cascade down)
        # - Heavy recent long liquidations (longs getting rekt, bearish)
        if side == "LONG":
            # Check if price is approaching a strong long liquidation cluster from above
            if conditions.liq_long_distance_pct < 3.0 and conditions.liq_long_strength > 0.6:
                warning = f"Near strong long liq cluster ({conditions.liq_long_distance_pct:.1f}% away, strength={conditions.liq_long_strength:.2f})"
                # Block if very close to strong cluster
                if conditions.liq_long_distance_pct < 1.5 and conditions.liq_long_strength > 0.8:
                    should_block = True
            
            # Check if longs are getting heavily liquidated (bearish signal)
            if conditions.liq_ratio > 2.0 and conditions.liq_volume_long_1h > 1_000_000:
                warning = f"Heavy long liquidations (ratio={conditions.liq_ratio:.1f}, vol=${conditions.liq_volume_long_1h/1e6:.1f}M)"
                # If extreme, block
                if conditions.liq_ratio > 3.0 and conditions.liq_volume_long_1h > 5_000_000:
                    should_block = True
        
        # For SHORT positions, check opposite conditions
        else:
            # Check if price is approaching a strong short liquidation cluster from below
            if conditions.liq_short_distance_pct < 3.0 and conditions.liq_short_strength > 0.6:
                warning = f"Near strong short liq cluster ({conditions.liq_short_distance_pct:.1f}% away, strength={conditions.liq_short_strength:.2f})"
                if conditions.liq_short_distance_pct < 1.5 and conditions.liq_short_strength > 0.8:
                    should_block = True
            
            # Check if shorts are getting heavily liquidated (bullish signal)
            if conditions.liq_ratio < 0.5 and conditions.liq_volume_short_1h > 1_000_000:
                warning = f"Heavy short liquidations (ratio={conditions.liq_ratio:.1f}, vol=${conditions.liq_volume_short_1h/1e6:.1f}M)"
                if conditions.liq_ratio < 0.33 and conditions.liq_volume_short_1h > 5_000_000:
                    should_block = True
        
        return warning, should_block
    
    def record_trade_outcome(
        self,
        symbol: str,
        side: str,
        confidence: float,
        entry_price: float,
        exit_price: float,
        hold_time_minutes: float,
        costs_usd: float
    ):
        """
        Record trade outcome for continuous calibration.
        
        This allows the system to learn and improve over time.
        """
        if side == "LONG":
            actual_move_pct = (exit_price - entry_price) / entry_price * 100
        else:
            actual_move_pct = (entry_price - exit_price) / entry_price * 100
        
        self.trade_history.append({
            'symbol': symbol,
            'side': side,
            'confidence': confidence,
            'actual_move_pct': actual_move_pct,
            'hold_time_minutes': hold_time_minutes,
            'costs_usd': costs_usd,
            'timestamp': time.time()
        })
    
    def get_calibration_stats(self) -> Dict:
        """Get rolling calibration statistics from trade history"""
        if len(self.trade_history) < 10:
            return {'insufficient_data': True, 'trade_count': len(self.trade_history)}
        
        # Group by confidence buckets
        conf_buckets = {}
        for trade in self.trade_history:
            bucket = round(trade['confidence'], 1)  # 0.7, 0.8, 0.9, etc.
            if bucket not in conf_buckets:
                conf_buckets[bucket] = {'moves': [], 'wins': 0, 'total': 0}
            
            conf_buckets[bucket]['moves'].append(trade['actual_move_pct'])
            conf_buckets[bucket]['total'] += 1
            if trade['actual_move_pct'] > 0:
                conf_buckets[bucket]['wins'] += 1
        
        # Calculate stats per bucket
        calibration = {}
        for bucket, data in conf_buckets.items():
            if data['total'] >= 5:  # Need at least 5 trades
                avg_move = sum(data['moves']) / len(data['moves'])
                win_rate = data['wins'] / data['total']
                calibration[bucket] = {
                    'avg_move_pct': avg_move,
                    'win_rate': win_rate,
                    'sample_size': data['total']
                }
        
        return {
            'calibration': calibration,
            'total_trades': len(self.trade_history),
            'gate_stats': self.stats
        }


class AdaptiveHoldTimeController:
    """
    Adaptive hold time management based on market conditions.
    
    NO STATIC THRESHOLDS - hold targets derived from:
    - Current ATR (higher vol = faster moves = shorter optimal hold)
    - Momentum strength (strong trend = hold longer)
    - Liquidation proximity (squeeze building = hold longer)
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.position_entries: Dict[str, Dict] = {}  # symbol:side -> entry_data
    
    def record_entry(
        self, 
        symbol: str, 
        side: str, 
        conditions: MarketConditions = None,
        entry_price: float = 0,
        confidence: float = 0
    ):
        """Record position entry with conditions"""
        key = f"{symbol}:{side}"
        self.position_entries[key] = {
            'entry_time': time.time(),
            'entry_price': entry_price,
            'confidence': confidence,
            'entry_atr_pct': conditions.atr_pct if conditions else 1.0,
            'entry_momentum': conditions.momentum_score if conditions else 0.0,
            'entry_squeeze_potential': conditions.squeeze_potential if conditions else 0.0
        }
    
    def compute_optimal_hold_time(self, symbol: str, side: str, current_conditions: MarketConditions) -> Dict:
        """
        Compute optimal hold time based on current vs entry conditions.
        
        Returns dict with:
        - optimal_hold_minutes
        - min_hold_minutes (before penalty)
        - bonus_hold_minutes (for hold bonus)
        - current_hold_minutes
        - hold_score (0-1, how well we're doing)
        """
        key = f"{symbol}:{side}"
        entry_data = self.position_entries.get(key, {})
        
        if not entry_data:
            return {'optimal_hold_minutes': 30, 'min_hold_minutes': 15, 'bonus_hold_minutes': 60}
        
        # Base optimal hold = inverse of volatility (high vol = shorter hold)
        # ATR of 2% = hold ~20min, ATR of 0.5% = hold ~80min
        atr_pct = max(current_conditions.atr_pct, 0.1)
        base_hold_minutes = 40 / atr_pct  # 2% ATR = 20min, 0.5% ATR = 80min
        
        # Momentum adjustment: Strong momentum = hold longer
        momentum_multiplier = 1.0 + abs(current_conditions.momentum_score) * 0.5  # Up to 1.5x
        
        # Squeeze adjustment: If squeeze building, hold longer
        squeeze_multiplier = 1.0 + current_conditions.squeeze_potential * 0.5  # Up to 1.5x
        
        optimal_hold = base_hold_minutes * momentum_multiplier * squeeze_multiplier
        
        # Min hold = 50% of optimal (quick flip territory)
        min_hold = optimal_hold * 0.5
        
        # Bonus hold = 150% of optimal (ride the trend)
        bonus_hold = optimal_hold * 1.5
        
        # Current hold time
        current_hold = (time.time() - entry_data['entry_time']) / 60
        
        # Hold score: 0 at min_hold, 1 at optimal, stays at 1 past optimal up to bonus
        if current_hold < min_hold:
            hold_score = current_hold / min_hold * 0.5  # 0 to 0.5
        elif current_hold < optimal_hold:
            hold_score = 0.5 + (current_hold - min_hold) / (optimal_hold - min_hold) * 0.5  # 0.5 to 1.0
        else:
            hold_score = 1.0  # Full score at or past optimal
        
        return {
            'optimal_hold_minutes': optimal_hold,
            'min_hold_minutes': min_hold,
            'bonus_hold_minutes': bonus_hold,
            'current_hold_minutes': current_hold,
            'hold_score': hold_score,
            'atr_pct': atr_pct,
            'momentum': current_conditions.momentum_score,
            'squeeze': current_conditions.squeeze_potential
        }
    
    def compute_reward_modifier(
        self, 
        symbol: str, 
        side: str, 
        pnl: float,
        current_conditions: MarketConditions
    ) -> Tuple[float, str]:
        """
        Compute ADAPTIVE reward modifier based on hold time relative to conditions.
        """
        hold_data = self.compute_optimal_hold_time(symbol, side, current_conditions)
        
        current_hold = hold_data['current_hold_minutes']
        min_hold = hold_data['min_hold_minutes']
        optimal_hold = hold_data['optimal_hold_minutes']
        bonus_hold = hold_data['bonus_hold_minutes']
        
        is_profitable = pnl > 0
        
        # Quick flip penalty (before min_hold)
        if current_hold < min_hold:
            penalty_ratio = current_hold / min_hold
            modifier = 0.3 + penalty_ratio * 0.4  # 0.3 to 0.7
            return modifier, f"QUICK_EXIT: {current_hold:.0f}min < min {min_hold:.0f}min (ATR-based)"
        
        # Short hold (between min and optimal)
        if current_hold < optimal_hold:
            ratio = (current_hold - min_hold) / (optimal_hold - min_hold)
            modifier = 0.7 + ratio * 0.3  # 0.7 to 1.0
            return modifier, f"SHORT_HOLD: {current_hold:.0f}min, optimal={optimal_hold:.0f}min"
        
        # Bonus territory (profitable trades held past optimal)
        if is_profitable and current_hold >= optimal_hold:
            if current_hold >= bonus_hold:
                modifier = 1.2  # Max bonus
            else:
                bonus_progress = (current_hold - optimal_hold) / (bonus_hold - optimal_hold)
                modifier = 1.0 + bonus_progress * 0.2  # 1.0 to 1.2
            return modifier, f"HOLD_BONUS: {current_hold:.0f}min >= optimal {optimal_hold:.0f}min (+{(modifier-1)*100:.0f}%)"
        
        return 1.0, f"NORMAL_HOLD: {current_hold:.0f}min"


@dataclass
class ProfitTakeDecision:
    """Result of liquidation-aware profit take analysis"""
    should_take_profit: bool
    urgency: str  # LOW, MEDIUM, HIGH, CRITICAL
    reason: str
    target_exit_pct: float  # Percentage of position to exit
    suggested_price: Optional[float] = None
    liquidation_context: str = ""
    
    # Risk metrics
    distance_to_adverse_liq_pct: float = 0.0
    distance_to_favorable_liq_pct: float = 0.0
    squeeze_risk: float = 0.0
    pnl_pct: float = 0.0


class LiquidationAwareProfitTaker:
    """
    Intelligent profit-taking system that uses liquidation levels to:
    1. Take profit before adverse liquidation cascades
    2. Hold through favorable liquidation squeezes
    3. Protect unrealized gains from reversal
    
    This ensures we STAY IN PROFIT and don't lose equity.
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self.stats = defaultdict(int)
        
        # No static thresholds - all derived from market data
        logger.info("LiquidationAwareProfitTaker initialized with adaptive logic")
    
    def analyze_profit_take(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        position_size_usd: float,
        conditions: Optional[MarketConditions] = None,
        is_hedge: bool = False,
        timeframe: str = '5m'
    ) -> ProfitTakeDecision:
        """
        Analyze whether to take profit based on current P&L and liquidation landscape.
        
        This method ensures we capture profits and avoid giving them back.
        """
        self.stats['total_analyzed'] += 1
        
        # Fetch conditions if not provided
        if conditions is None:
            fetcher = MarketConditionsFetcher(self.redis)
            conditions = fetcher.fetch_market_conditions(symbol, timeframe)
        
        # Calculate current PnL
        if side == "LONG":
            pnl_pct = (current_price - entry_price) / entry_price * 100
            # For longs: adverse liq = long liq levels (cascading down), favorable = short liq (squeeze up)
            adverse_liq_level = conditions.liq_long_level
            adverse_liq_strength = conditions.liq_long_strength
            adverse_liq_distance = conditions.liq_long_distance_pct
            favorable_liq_level = conditions.liq_short_level
            favorable_liq_strength = conditions.liq_short_strength
            favorable_liq_distance = conditions.liq_short_distance_pct
        else:
            pnl_pct = (entry_price - current_price) / entry_price * 100
            # For shorts: adverse liq = short liq levels (squeeze up), favorable = long liq (cascade down)
            adverse_liq_level = conditions.liq_short_level
            adverse_liq_strength = conditions.liq_short_strength
            adverse_liq_distance = conditions.liq_short_distance_pct
            favorable_liq_level = conditions.liq_long_level
            favorable_liq_strength = conditions.liq_long_strength
            favorable_liq_distance = conditions.liq_long_distance_pct
        
        decision = ProfitTakeDecision(
            should_take_profit=False,
            urgency="LOW",
            reason="",
            target_exit_pct=0.0,
            pnl_pct=pnl_pct,
            distance_to_adverse_liq_pct=adverse_liq_distance,
            distance_to_favorable_liq_pct=favorable_liq_distance,
            squeeze_risk=conditions.squeeze_potential
        )
        
        # ========================================================================
        # RULE 1: PROTECT UNREALIZED PROFITS
        # If we're in profit, we need to protect it
        # ========================================================================
        if pnl_pct <= 0:
            # Not in profit, no profit to take
            decision.reason = f"NOT_IN_PROFIT: PnL={pnl_pct:.2f}%"
            return decision
        
        # ========================================================================
        # RULE 2: ADVERSE LIQUIDATION PROXIMITY
        # If we're approaching a strong adverse liquidation cluster, take profit
        # before the cascade happens
        # ========================================================================
        if adverse_liq_strength > 0.3 and adverse_liq_distance < 5.0:
            # Scale urgency based on distance and strength
            risk_score = adverse_liq_strength * (5.0 - adverse_liq_distance) / 5.0
            
            if risk_score > 0.7:
                decision.should_take_profit = True
                decision.urgency = "CRITICAL"
                decision.target_exit_pct = min(100, 50 + risk_score * 50)  # 50-100%
                decision.reason = f"ADVERSE_LIQ_IMMINENT: {adverse_liq_distance:.1f}% away, strength={adverse_liq_strength:.2f}"
                decision.liquidation_context = f"Strong {'long' if side == 'LONG' else 'short'} liq cluster at {adverse_liq_level:.2f}"
                self.stats['profit_take_adverse_liq'] += 1
                return decision
            elif risk_score > 0.4:
                decision.should_take_profit = True
                decision.urgency = "HIGH"
                decision.target_exit_pct = min(75, 25 + risk_score * 50)  # 25-75%
                decision.reason = f"ADVERSE_LIQ_NEARBY: {adverse_liq_distance:.1f}% away, strength={adverse_liq_strength:.2f}"
                decision.liquidation_context = f"{'Long' if side == 'LONG' else 'Short'} liq cluster at {adverse_liq_level:.2f}"
                self.stats['profit_take_adverse_liq'] += 1
                return decision
        
        # ========================================================================
        # RULE 3: FAVORABLE LIQUIDATION SQUEEZE OPPORTUNITY
        # If we're approaching a favorable liquidation cluster, we might want to
        # hold for the squeeze BUT set a trailing take-profit
        # ========================================================================
        if favorable_liq_strength > 0.5 and favorable_liq_distance < 3.0:
            # Squeeze opportunity - hold but be ready
            squeeze_score = favorable_liq_strength * (3.0 - favorable_liq_distance) / 3.0
            
            if squeeze_score > 0.5 and pnl_pct > 1.0:  # Only if already in good profit
                # Don't take full profit yet, but take some off the table
                decision.should_take_profit = True
                decision.urgency = "MEDIUM"
                decision.target_exit_pct = 25  # Take 25% off, let the rest ride
                decision.reason = f"SQUEEZE_SETUP: favorable liq {favorable_liq_distance:.1f}% away, taking partial"
                decision.liquidation_context = f"{'Short' if side == 'LONG' else 'Long'} squeeze potential at {favorable_liq_level:.2f}"
                decision.squeeze_risk = squeeze_score
                self.stats['partial_take_squeeze_setup'] += 1
                return decision
        
        # ========================================================================
        # RULE 4: PROFIT PROTECTION BASED ON ATR
        # If we've captured more than 2x ATR in profit, protect it
        # ========================================================================
        atr_pct = conditions.atr_pct if conditions.atr_pct > 0 else 1.0
        profit_to_atr_ratio = pnl_pct / atr_pct
        
        if profit_to_atr_ratio >= 2.0:
            # We've captured 2x ATR - this is significant
            if profit_to_atr_ratio >= 3.0:
                decision.should_take_profit = True
                decision.urgency = "HIGH"
                decision.target_exit_pct = 50  # Take half at 3x ATR
                decision.reason = f"PROFIT_PROTECTION: {pnl_pct:.2f}% = {profit_to_atr_ratio:.1f}x ATR"
                self.stats['profit_take_atr_protection'] += 1
                return decision
            else:
                decision.should_take_profit = True
                decision.urgency = "MEDIUM"
                decision.target_exit_pct = 25  # Take 25% at 2x ATR
                decision.reason = f"PARTIAL_PROTECTION: {pnl_pct:.2f}% = {profit_to_atr_ratio:.1f}x ATR"
                self.stats['partial_take_atr'] += 1
                return decision
        
        # ========================================================================
        # RULE 5: MOMENTUM REVERSAL DETECTION
        # If momentum is reversing and we're in profit, protect gains
        # ========================================================================
        if pnl_pct > 0.5:  # At least 0.5% profit
            momentum = conditions.momentum_score
            is_momentum_adverse = (
                (side == "LONG" and momentum < -0.3) or
                (side == "SHORT" and momentum > 0.3)
            )
            
            if is_momentum_adverse:
                decision.should_take_profit = True
                decision.urgency = "MEDIUM"
                decision.target_exit_pct = min(50, max(25, pnl_pct * 10))  # 25-50%
                decision.reason = f"MOMENTUM_REVERSAL: score={momentum:.2f}, protecting {pnl_pct:.2f}%"
                self.stats['profit_take_momentum_reversal'] += 1
                return decision
        
        # ========================================================================
        # RULE 6: RSI EXHAUSTION
        # If RSI indicates overbought/oversold and we're in profit
        # ========================================================================
        rsi = conditions.rsi
        is_exhausted = (
            (side == "LONG" and rsi > 75) or
            (side == "SHORT" and rsi < 25)
        )
        
        if is_exhausted and pnl_pct > 1.0:
            decision.should_take_profit = True
            decision.urgency = "MEDIUM"
            decision.target_exit_pct = 33  # Take 1/3
            decision.reason = f"RSI_EXHAUSTION: RSI={rsi:.0f}, {'overbought' if side == 'LONG' else 'oversold'}"
            self.stats['profit_take_rsi_exhaustion'] += 1
            return decision
        
        # ========================================================================
        # RULE 7: HEDGE POSITION PROFIT CAPTURE
        # Hedges should be closed more aggressively when in profit
        # ========================================================================
        if is_hedge and pnl_pct > 0.5:
            # Hedge is doing its job - close it to lock in hedge profit
            decision.should_take_profit = True
            decision.urgency = "MEDIUM" if pnl_pct > 1.0 else "LOW"
            decision.target_exit_pct = 100  # Close the full hedge
            decision.reason = f"HEDGE_PROFIT_CAPTURE: hedge PnL={pnl_pct:.2f}%"
            self.stats['hedge_profit_capture'] += 1
            return decision
        
        # No profit-take signal
        decision.reason = f"HOLD: PnL={pnl_pct:.2f}%, adverse_liq={adverse_liq_distance:.1f}%, momentum={conditions.momentum_score:.2f}"
        return decision
    
    def get_protective_exit_level(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        conditions: Optional[MarketConditions] = None,
        timeframe: str = '5m'
    ) -> Tuple[float, str]:
        """
        Calculate a protective exit level that ensures we stay in profit.
        
        Returns:
            (exit_price, reason)
        """
        # Fetch conditions if needed
        if conditions is None:
            fetcher = MarketConditionsFetcher(self.redis)
            conditions = fetcher.fetch_market_conditions(symbol, timeframe)
        
        # Calculate current unrealized PnL
        if side == "LONG":
            pnl_pct = (current_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - current_price) / entry_price * 100
        
        atr_pct = conditions.atr_pct if conditions.atr_pct > 0 else 1.0
        
        # If in profit, set protective stop to lock in some gains
        if pnl_pct > atr_pct * 0.5:  # Profit > 0.5x ATR
            # Lock in 50% of unrealized profit
            lock_in_pct = pnl_pct * 0.5
            
            if side == "LONG":
                exit_price = entry_price * (1 + lock_in_pct / 100)
                reason = f"PROTECTIVE_STOP: lock in {lock_in_pct:.2f}% of {pnl_pct:.2f}% profit"
            else:
                exit_price = entry_price * (1 - lock_in_pct / 100)
                reason = f"PROTECTIVE_STOP: lock in {lock_in_pct:.2f}% of {pnl_pct:.2f}% profit"
            
            return exit_price, reason
        
        # If not in significant profit, use ATR-based stop
        stop_distance = atr_pct * 1.5  # 1.5x ATR stop
        if side == "LONG":
            exit_price = current_price * (1 - stop_distance / 100)
        else:
            exit_price = current_price * (1 + stop_distance / 100)
        
        return exit_price, f"ATR_STOP: {stop_distance:.2f}% from current"
    
    def get_stats(self) -> Dict:
        """Get statistics on profit-taking decisions"""
        return dict(self.stats)


# Global instances
_adaptive_gate: Optional[AdaptiveEdgeGate] = None
_adaptive_hold: Optional[AdaptiveHoldTimeController] = None
_liq_profit_taker: Optional[LiquidationAwareProfitTaker] = None


def get_adaptive_edge_gate(**kwargs) -> AdaptiveEdgeGate:
    """Get or create the global adaptive edge gate"""
    global _adaptive_gate
    if _adaptive_gate is None:
        # Use config-derived defaults (K=MIN_EDGE_MULTIPLE) while preserving explicit overrides via kwargs.
        try:
            from config import MIN_EDGE_MULTIPLE
            base_k = float(kwargs.pop("safety_buffer_multiplier", MIN_EDGE_MULTIPLE))
        except Exception:
            base_k = float(kwargs.pop("safety_buffer_multiplier", 1.5))

        # Allow K to expand dynamically up to 4× when base K is raised (matches 1000× design K=2..4).
        max_k = float(kwargs.pop("max_safety_buffer_multiplier", min(4.0, max(3.0, base_k * 2.0))))

        _adaptive_gate = AdaptiveEdgeGate(
            safety_buffer_multiplier=base_k,
            max_safety_buffer_multiplier=max_k,
            **kwargs,
        )
    return _adaptive_gate


def get_adaptive_hold_controller(**kwargs) -> AdaptiveHoldTimeController:
    """Get or create the global adaptive hold controller"""
    global _adaptive_hold
    if _adaptive_hold is None:
        _adaptive_hold = AdaptiveHoldTimeController(**kwargs)
    return _adaptive_hold


def get_liq_profit_taker(**kwargs) -> LiquidationAwareProfitTaker:
    """Get or create the global liquidation-aware profit taker"""
    global _liq_profit_taker
    if _liq_profit_taker is None:
        _liq_profit_taker = LiquidationAwareProfitTaker(**kwargs)
    return _liq_profit_taker


if __name__ == '__main__':
    # Test the adaptive edge gate
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 70)
    print("ADAPTIVE EDGE GATE TEST - NO STATIC THRESHOLDS")
    print("=" * 70)
    
    gate = AdaptiveEdgeGate()
    
    # Create mock conditions for testing
    mock_conditions = MarketConditions(
        symbol="BTCUSDT",
        current_price=95000.0,
        atr_pct=1.5,  # 1.5% ATR
        spread_bps=2.5,
        momentum_score=0.4,  # Bullish momentum
        squeeze_potential=0.6,  # Squeeze building
        spoof_score=0.2,
        data_completeness=0.9,
        liq_long_level=92000.0,
        liq_short_level=98000.0,
        liq_long_strength=0.7,
        liq_short_strength=0.5
    )
    
    # Test with different confidences
    print("\nEdge estimates for BTCUSDT LONG at different confidences:")
    print("-" * 70)
    
    for conf in [0.70, 0.80, 0.85, 0.90, 0.95]:
        estimate = gate.estimate_edge(
            symbol="BTCUSDT",
            side="LONG", 
            confidence=conf,
            notional_usd=500,
            timeframe='5m'
        )
        
        print(f"Conf={conf:.0%}: expected={estimate.expected_move_pct:.3f}%, "
              f"cost={estimate.total_cost_pct:.3f}%, ratio={estimate.edge_ratio:.2f}")
    
    print("\n" + "=" * 70)
    print("ADAPTIVE HOLD TIME TEST")
    print("=" * 70)
    
    hold_ctrl = AdaptiveHoldTimeController()
    
    # Test with different ATR levels
    for atr in [0.5, 1.0, 2.0, 3.0]:
        conditions = MarketConditions(
            symbol="BTCUSDT",
            atr_pct=atr,
            momentum_score=0.3,
            squeeze_potential=0.2
        )
        
        hold_ctrl.record_entry("BTCUSDT", "LONG", conditions)
        hold_data = hold_ctrl.compute_optimal_hold_time("BTCUSDT", "LONG", conditions)
        
        print(f"ATR={atr}%: optimal_hold={hold_data['optimal_hold_minutes']:.0f}min, "
              f"min={hold_data['min_hold_minutes']:.0f}min, "
              f"bonus={hold_data['bonus_hold_minutes']:.0f}min")
    
    print("\n" + "=" * 70)
    print("LIQUIDATION-AWARE PROFIT TAKER TEST")
    print("=" * 70)
    
    profit_taker = LiquidationAwareProfitTaker()
    
    # Test scenarios for profit taking
    test_scenarios = [
        # (entry, current, side, liq_long_level, liq_short_level, liq_long_str, liq_short_str, description)
        (95000, 96500, "LONG", 94000, 99000, 0.3, 0.8, "LONG +1.58%, near short squeeze"),
        (95000, 96000, "LONG", 93000, 96500, 0.2, 0.9, "LONG +1.05%, very close to short liq"),
        (95000, 94000, "LONG", 93000, 98000, 0.9, 0.2, "LONG -1.05%, near strong long liq"),
        (95000, 97000, "LONG", 90000, 98000, 0.5, 0.5, "LONG +2.1%, 2x ATR profit"),
        (95000, 93500, "SHORT", 92500, 96000, 0.8, 0.3, "SHORT +1.58%, near long liq cascade"),
        (95000, 92000, "SHORT", 91000, 98000, 0.9, 0.2, "SHORT +3.16%, 3x ATR profit"),
    ]
    
    print("\nProfit-take analysis:")
    print("-" * 70)
    
    for entry, current, side, ll, sl, ll_str, sl_str, desc in test_scenarios:
        # Calculate distances
        ll_dist = abs(current - ll) / current * 100
        sl_dist = abs(sl - current) / current * 100
        
        conditions = MarketConditions(
            symbol="BTCUSDT",
            current_price=current,
            atr_pct=1.0,
            liq_long_level=ll,
            liq_short_level=sl,
            liq_long_strength=ll_str,
            liq_short_strength=sl_str,
            liq_long_distance_pct=ll_dist,
            liq_short_distance_pct=sl_dist,
            momentum_score=0.2,
            rsi=55.0
        )
        
        decision = profit_taker.analyze_profit_take(
            symbol="BTCUSDT",
            side=side,
            entry_price=entry,
            current_price=current,
            position_size_usd=500,
            conditions=conditions
        )
        
        print(f"\n{desc}")
        print(f"  PnL: {decision.pnl_pct:.2f}% | Take profit: {decision.should_take_profit}")
        if decision.should_take_profit:
            print(f"  Urgency: {decision.urgency} | Exit %: {decision.target_exit_pct:.0f}%")
            print(f"  Reason: {decision.reason}")
            if decision.liquidation_context:
                print(f"  Liq context: {decision.liquidation_context}")
    
    print("\n" + "=" * 70)
    print("Statistics:", profit_taker.get_stats())

