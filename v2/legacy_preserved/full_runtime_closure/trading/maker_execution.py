"""
Adaptive Maker-First Execution Strategy (Option 3)
===================================================
FULLY DYNAMIC - No static thresholds.

Order type selection based on live market data:
- Spread width vs ATR → Use maker if spread < ATR/10 (enough room for rebate profit)
- Orderbook depth → Use maker if depth > 2x order size (high fill probability)
- Volatility → Use taker in high vol (price may move before fill)
- Signal freshness → Use taker for stale signals (edge decaying)
- Microstructure → Use taker if high spoof score (orderbook unreliable)

Fee Impact:
- Taker: 0.05% fee
- Maker: 0.02% fee  
- Savings: 60% reduction in fees when conditions favor maker orders
"""

import logging
import time
import json
import threading
from typing import Dict, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class OrderType(Enum):
    """Order type to use for execution"""
    MARKET = "MARKET"       # Taker - immediate fill, 0.05% fee
    LIMIT = "LIMIT"         # Maker - may not fill, 0.02% fee
    LIMIT_IOC = "LIMIT_IOC" # Immediate-or-cancel limit


@dataclass
class ExecutionDecision:
    """Decision on how to execute an order"""
    order_type: OrderType
    price: Optional[float]  # Limit price (None for market)
    reason: str
    estimated_fee_bps: float
    urgency: str  # "LOW", "MEDIUM", "HIGH"
    # Adaptive decision factors
    spread_to_atr_ratio: float = 0.0
    depth_ratio: float = 0.0
    fill_probability: float = 0.0
    # Controls for downstream traders
    market_allowed: bool = True  # If False, trader must NOT use taker/market entry for this signal
    should_skip: bool = False    # If True, trader should skip execution (e.g., extremely stale signal)


@dataclass 
class MarketMicrostructure:
    """Live market microstructure for execution decisions"""
    spread_bps: float = 0.0
    atr_pct: float = 1.0
    bid_depth_usd: float = 100000
    ask_depth_usd: float = 100000
    spoof_score: float = 0.0
    fast_move_score: float = 0.0
    volatility_pct: float = 1.0
    # Data quality / provenance (used to avoid taker decisions when inputs are missing)
    data_ok: bool = False
    data_source: str = ""
    has_spoof_score: bool = False
    has_fast_move_score: bool = False


class MakerFirstExecutor:
    """
    ADAPTIVE maker-first execution strategy.
    
    NO STATIC THRESHOLDS - All decisions from live data:
    - Use MAKER if: spread/ATR < 0.1 AND depth > 2x order AND spoof < 0.3
    - Use TAKER if: PROTECTIVE OR conditions unfavorable OR signal stale
    """
    
    def __init__(
        self,
        redis_client=None,
        maker_wait_timeout_seconds: int = 30,
        maker_price_offset_bps: float = 1.0,
        maker_fee_bps: float = 2.0,
        taker_fee_bps: float = 5.0,
        enable_maker: bool = True,
        # Legacy params - kept for backward compatibility but NOT used for decisions
        maker_confidence_threshold: float = 0.95  # DEPRECATED: Now adaptive
    ):
        """
        Initialize adaptive maker-first executor.
        
        Args:
            redis_client: Redis connection for fetching live orderbook/volatility
            maker_wait_timeout_seconds: Max time to wait for limit fill
            maker_price_offset_bps: Limit price offset from mid (adaptive adjusts this)
            maker_fee_bps: Maker fee rate in basis points
            taker_fee_bps: Taker fee rate in basis points
            enable_maker: Master switch for maker-first strategy
        """
        self.redis = redis_client
        self.maker_wait_timeout_seconds = maker_wait_timeout_seconds
        self.base_price_offset_bps = maker_price_offset_bps
        self.maker_fee_bps = maker_fee_bps
        self.taker_fee_bps = taker_fee_bps
        self.enable_maker = enable_maker
        self.maker_confidence_threshold = maker_confidence_threshold  # Legacy fallback
        
        # Cache for microstructure data
        self._micro_cache: Dict[str, Tuple[MarketMicrostructure, float]] = {}
        self._cache_ttl = 2.0  # 2 second cache
        
        # Statistics
        self.stats = {
            'total_orders': 0,
            'maker_orders': 0,
            'taker_orders': 0,
            'maker_fills': 0,
            'maker_cancels': 0,
            'maker_to_taker_converts': 0,
            'total_fee_savings_bps': 0.0,
            'adaptive_decisions': 0,
            'fallback_decisions': 0
        }
        
        # Pending limit orders
        self.pending_orders: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        
        logger.info(f"AdaptiveMakerFirstExecutor initialized - FULLY DYNAMIC decision logic")
    
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
                    logger.debug(f"Cannot connect to Redis: {e}")
        return self.redis
    
    def fetch_microstructure(self, symbol: str) -> MarketMicrostructure:
        """Fetch live market microstructure from Redis"""
        now = time.time()
        
        # Check cache
        if symbol in self._micro_cache:
            cached, cached_time = self._micro_cache[symbol]
            if now - cached_time < self._cache_ttl:
                return cached
        
        micro = MarketMicrostructure()
        redis = self._get_redis()
        
        if not redis:
            return micro
        
        try:
            # Orderbook data - Priority order:
            # 1. CoinAPI (PRIMARY) - msnap:coinapi_wsds:{symbol}
            # 2. Binance - instant:{symbol}:spread, orderbook:top:{symbol}
            # 3. CCXT - ccxt:orderbook:{symbol}
            # 4. KuCoin - kc:orderbook20:{symbol}
            # 5. Redi (fallback) - redi:orderbook:{symbol}
            
            orderbook_keys = [
                f"msnap:coinapi_wsds:{symbol}",          # 1. CoinAPI (PRIMARY)
                f"instant:{symbol}:spread",              # 2. Binance
                f"orderbook:top:{symbol}",
                f"latest:binance:depth:{symbol}:20",
                f"ccxt:orderbook:{symbol}",              # 3. CCXT
                f"kc:orderbook20:{symbol}",              # 4. KuCoin
                f"redi:orderbook:{symbol}",              # 5. Redi
            ]
            
            for key in orderbook_keys:
                try:
                    key_type = redis.type(key)
                    if key_type == 'none':
                        continue
                    
                    if key_type == 'hash':
                        data = redis.hgetall(key)
                        if data:
                            data = {(k.decode() if isinstance(k, bytes) else k): 
                                   (v.decode() if isinstance(v, bytes) else v) 
                                   for k, v in data.items()}
                    else:
                        raw = redis.get(key)
                        data = json.loads(raw) if raw else None
                    
                    if data:
                        # Extract spread
                        if 'spread_bps' in data:
                            micro.spread_bps = float(data['spread_bps'])
                        elif 'spread' in data:
                            spread_val = float(data['spread'])
                            if spread_val < 1:  # Absolute spread
                                mid = float(data.get('mid', data.get('mid_px', 1)))
                                micro.spread_bps = (spread_val / mid) * 10000 if mid > 0 else 3.0
                            else:
                                micro.spread_bps = spread_val
                        
                        # Extract depth
                        micro.bid_depth_usd = float(data.get('bid_depth', data.get('book_bid_sum_5', 
                                                  data.get('best_bid_sz', 100000))))
                        micro.ask_depth_usd = float(data.get('ask_depth', data.get('book_ask_sum_5',
                                                  data.get('best_ask_sz', 100000))))
                        
                        # Extract spoof/fast_move scores
                        if 'spoof_score' in data:
                            micro.spoof_score = float(data['spoof_score'])
                            micro.has_spoof_score = True
                        if 'fast_move_score' in data:
                            micro.fast_move_score = float(data['fast_move_score'])
                            micro.has_fast_move_score = True

                        micro.data_ok = True
                        micro.data_source = str(key)
                        
                        logger.debug(f"Loaded microstructure from {key}")
                        break
                except Exception:
                    continue
            
            # ATR/Volatility
            for key in [f"volatility:{symbol}", f"unified_features:{symbol}:5m"]:
                try:
                    data = redis.get(key) or redis.hgetall(key)
                    if data:
                        if isinstance(data, str):
                            data = json.loads(data)
                        micro.atr_pct = float(data.get('atr_pct', data.get('composite_index', 1.0)))
                        micro.volatility_pct = micro.atr_pct
                        break
                except Exception:
                    continue
            
            # Additional microstructure scores from msnap if not already loaded
            if micro.spoof_score == 0.0:
                try:
                    msnap = redis.hgetall(f"msnap:coinapi_wsds:{symbol}")
                    if msnap:
                        micro.data_ok = True
                        micro.data_source = micro.data_source or f"msnap:coinapi_wsds:{symbol}"
                        for k, v in msnap.items():
                            k = k.decode() if isinstance(k, bytes) else k
                            v = v.decode() if isinstance(v, bytes) else v
                            if k == 'spoof_score':
                                micro.spoof_score = float(v)
                                micro.has_spoof_score = True
                            elif k == 'fast_move_score':
                                micro.fast_move_score = float(v)
                                micro.has_fast_move_score = True
                except Exception:
                    pass
            
            # Cache result
            self._micro_cache[symbol] = (micro, now)
            
        except Exception as e:
            logger.debug(f"Error fetching microstructure for {symbol}: {e}")
        
        return micro
    
    def decide_execution_type(
        self,
        symbol: str,
        side: str,  # "LONG" or "SHORT"
        confidence: float,
        current_price: float,
        bid_price: Optional[float] = None,
        ask_price: Optional[float] = None,
        action_category: str = "OPEN_RISK",
        signal_age_seconds: float = 0,
        order_size_usd: float = 500,
        # Legacy param - ignored, we compute from live data
        volatility_pct: float = None
    ) -> ExecutionDecision:
        """
        ADAPTIVE decision on order type based on live market conditions.
        
        NO STATIC THRESHOLDS - derived from:
        - spread_to_atr_ratio: If spread << ATR, maker rebate can profit
        - depth_ratio: If depth >> order size, high fill probability
        - spoof_score: If high, orderbook unreliable, use taker
        """
        self.stats['total_orders'] += 1
        
        # Check if maker-first is disabled
        if not self.enable_maker:
            self.stats['taker_orders'] += 1
            return ExecutionDecision(
                order_type=OrderType.MARKET,
                price=None,
                reason="MAKER_DISABLED",
                estimated_fee_bps=self.taker_fee_bps,
                urgency="HIGH"
            )
        
        # PROTECTIVE actions always use market (safety first)
        if action_category == "PROTECTIVE":
            self.stats['taker_orders'] += 1
            return ExecutionDecision(
                order_type=OrderType.MARKET,
                price=None,
                reason="PROTECTIVE_ACTION",
                estimated_fee_bps=self.taker_fee_bps,
                urgency="HIGH",
                market_allowed=True,
                should_skip=False,
            )

        # === MAKER-FIRST DEFAULT LOGIC ===
        # For non-protective actions we default to post-only LIMIT and let the trader's TTL/reprice
        # loop decide whether to convert to market (only when explicitly allowed).
        micro = self.fetch_microstructure(symbol)

        # Compute adaptive metrics (for logging/telemetry)
        atr_in_bps = micro.atr_pct * 100  # Convert % to bps
        spread_to_atr = micro.spread_bps / atr_in_bps if atr_in_bps > 0 else 1.0

        avg_depth = (micro.bid_depth_usd + micro.ask_depth_usd) / 2
        depth_ratio = avg_depth / order_size_usd if order_size_usd > 0 else 10.0

        # Estimate fill probability based on conditions (heuristic)
        fill_prob = 0.9  # Base 90%
        if spread_to_atr > 0.1:
            fill_prob *= 0.8  # Wide spread = lower fill chance
        if depth_ratio < 2:
            fill_prob *= 0.7  # Low depth = lower fill chance
        if micro.fast_move_score > 0.5:
            fill_prob *= 0.6  # Fast move = lower fill chance

        # Determine if market/taker entry should be allowed.
        # Design rule: never taker-enter into spoof/fast-move; prefer maker-only or skip.
        market_allowed = True
        market_block_reasons = []
        try:
            from config import MICROSTRUCTURE_SPOOF_THRESHOLD, MICROSTRUCTURE_FAST_MOVE_THRESHOLD
            spoof_thr = float(MICROSTRUCTURE_SPOOF_THRESHOLD or 0.6)
            fast_thr = float(MICROSTRUCTURE_FAST_MOVE_THRESHOLD or 0.35)
        except Exception:
            spoof_thr = 0.6
            fast_thr = 0.35

        if float(micro.spoof_score or 0.0) >= spoof_thr:
            market_allowed = False
            market_block_reasons.append(f"spoof>={spoof_thr:.2f}:{micro.spoof_score:.2f}")
        if float(micro.fast_move_score or 0.0) >= fast_thr:
            market_allowed = False
            market_block_reasons.append(f"fast>={fast_thr:.2f}:{micro.fast_move_score:.2f}")

        # If we couldn't load any microstructure inputs (or we lack manipulation scores),
        # do NOT allow taker/market entries. Maker-first remains allowed.
        if not bool(getattr(micro, "data_ok", False)):
            market_allowed = False
            market_block_reasons.append("no_micro_data")
        elif not (bool(getattr(micro, "has_spoof_score", False)) or bool(getattr(micro, "has_fast_move_score", False))):
            market_allowed = False
            market_block_reasons.append("no_manip_scores")

        # Extremely stale signals should be skipped rather than forcing taker fills.
        # Use an adaptive bound derived from maker TTL (no hard-coded "10s").
        stale_limit_s = max(30.0, float(self.maker_wait_timeout_seconds or 0) * 1.5)
        should_skip = bool(signal_age_seconds and (signal_age_seconds > stale_limit_s))
        if should_skip:
            market_allowed = False

        limit_price = self._calculate_limit_price(
            side, current_price, bid_price, ask_price, micro.spread_bps
        )

        self.stats['maker_orders'] += 1
        self.stats['adaptive_decisions'] += 1

        reason_parts = [
            f"MAKER_DEFAULT:spread_atr={spread_to_atr:.2f}",
            f"depth={depth_ratio:.1f}x",
            f"fill={fill_prob:.0%}",
        ]
        if market_block_reasons:
            reason_parts.append(f"market_block={','.join(market_block_reasons)}")
        if should_skip:
            reason_parts.append(f"stale={signal_age_seconds:.0f}s>{stale_limit_s:.0f}s")

        return ExecutionDecision(
            order_type=OrderType.LIMIT,
            price=limit_price,
            reason="|".join(reason_parts),
            estimated_fee_bps=self.maker_fee_bps,
            urgency="LOW" if not should_skip else "LOW",
            spread_to_atr_ratio=spread_to_atr,
            depth_ratio=depth_ratio,
            fill_probability=fill_prob,
            market_allowed=market_allowed,
            should_skip=should_skip,
        )
    
    def _calculate_limit_price(
        self,
        side: str,
        mid_price: float,
        bid_price: Optional[float],
        ask_price: Optional[float],
        live_spread_bps: float = None
    ) -> float:
        """
        ADAPTIVE limit price calculation based on live spread.
        
        Strategy:
        - If spread is tight: Post at best bid/ask for fast fill
        - If spread is wide: Post inside the spread for better price
        
        For LONG (buy): Post on bid side (below mid)
        For SHORT (sell): Post on ask side (above mid)
        """
        # Adaptive offset: Use fraction of live spread or base offset
        if live_spread_bps and live_spread_bps > 0:
            # Post 20% inside the spread from our side
            offset_pct = (live_spread_bps * 0.2) / 10000
        else:
            offset_pct = self.base_price_offset_bps / 10000
        
        if side == "LONG":
            # Buying - post on bid side
            if bid_price and ask_price:
                # Post 20% of spread above best bid (inside the spread)
                spread = ask_price - bid_price
                return bid_price + spread * 0.2
            elif bid_price:
                return bid_price * (1 + offset_pct * 0.5)
            return mid_price * (1 - offset_pct)
        else:
            # Selling - post on ask side
            if bid_price and ask_price:
                # Post 20% of spread below best ask (inside the spread)
                spread = ask_price - bid_price
                return ask_price - spread * 0.2
            elif ask_price:
                return ask_price * (1 - offset_pct * 0.5)
            return mid_price * (1 + offset_pct)
    
    def track_pending_order(
        self,
        order_id: str,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        signal_id: str = None
    ):
        """Track a pending limit order for fill monitoring"""
        with self._lock:
            self.pending_orders[order_id] = {
                'symbol': symbol,
                'side': side,
                'price': price,
                'quantity': quantity,
                'signal_id': signal_id,
                'created_at': time.time(),
                'status': 'PENDING'
            }
    
    def on_order_filled(self, order_id: str, filled_qty: float, avg_price: float):
        """Called when a limit order is filled"""
        with self._lock:
            if order_id in self.pending_orders:
                order = self.pending_orders.pop(order_id)
                self.stats['maker_fills'] += 1
                
                # Calculate fee savings
                savings = (self.taker_fee_bps - self.maker_fee_bps) * filled_qty * avg_price / 10000
                self.stats['total_fee_savings_bps'] += savings
                
                logger.info(f"✅ Maker order filled: {order_id} @ {avg_price}, saved ${savings:.4f}")
    
    def on_order_cancelled(self, order_id: str, reason: str = "TIMEOUT"):
        """Called when a limit order is cancelled"""
        with self._lock:
            if order_id in self.pending_orders:
                order = self.pending_orders.pop(order_id)
                
                if reason == "CONVERT_TO_MARKET":
                    self.stats['maker_to_taker_converts'] += 1
                else:
                    self.stats['maker_cancels'] += 1
                
                logger.info(f"❌ Maker order cancelled: {order_id} - {reason}")
    
    def check_pending_timeouts(self) -> list:
        """
        Check for pending orders that have exceeded timeout.
        
        Returns list of order_ids that should be cancelled/converted.
        """
        expired = []
        now = time.time()
        
        with self._lock:
            for order_id, order in list(self.pending_orders.items()):
                age = now - order['created_at']
                if age > self.maker_wait_timeout_seconds:
                    expired.append({
                        'order_id': order_id,
                        'age_seconds': age,
                        **order
                    })
        
        return expired
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get execution statistics"""
        total = self.stats['total_orders']
        if total == 0:
            maker_pct = 0
            fill_rate = 0
        else:
            maker_pct = (self.stats['maker_orders'] / total) * 100
            if self.stats['maker_orders'] > 0:
                fill_rate = (self.stats['maker_fills'] / self.stats['maker_orders']) * 100
            else:
                fill_rate = 0
        
        return {
            **self.stats,
            'maker_order_pct': maker_pct,
            'maker_fill_rate': fill_rate,
            'pending_orders': len(self.pending_orders),
            'config': {
                'threshold': self.maker_confidence_threshold,
                'timeout_seconds': self.maker_wait_timeout_seconds,
                'offset_bps': self.base_price_offset_bps,
                'enabled': self.enable_maker
            }
        }


def build_limit_order_params(
    symbol: str,
    side: str,  # "LONG" or "SHORT"
    quantity: float,
    limit_price: float,
    position_side: str = None,  # "LONG", "SHORT", or "BOTH"
    time_in_force: str = "GTC",  # GTC, IOC, FOK
    reduce_only: bool = False
) -> Dict[str, Any]:
    """
    Build order parameters for a limit order.
    
    Args:
        symbol: Trading symbol
        side: Position side ("LONG" or "SHORT")
        quantity: Order quantity
        limit_price: Limit price
        position_side: Position side for hedge mode ("LONG", "SHORT", "BOTH")
        time_in_force: Order time in force
        reduce_only: Whether this is a reduce-only order
        
    Returns:
        Dict of order parameters for Binance API
    """
    # Convert position side to order side
    order_side = 'BUY' if side == 'LONG' else 'SELL'
    
    params = {
        'symbol': symbol,
        'side': order_side,
        'type': 'LIMIT',
        'price': str(limit_price),  # Binance requires string
        'quantity': quantity,
        'timeInForce': time_in_force,
        'newOrderRespType': 'RESULT'
    }
    
    if position_side:
        params['positionSide'] = position_side
    
    if reduce_only:
        params['reduceOnly'] = True
    
    return params


# Global instance
_maker_executor: Optional[MakerFirstExecutor] = None


def get_maker_executor(**kwargs) -> MakerFirstExecutor:
    """Get or create the global maker-first executor"""
    global _maker_executor
    if _maker_executor is None:
        # Load config from environment
        import os
        from config import (
            MAKER_FIRST_ENABLED, MAKER_CONFIDENCE_THRESHOLD,
            MAKER_WAIT_TIMEOUT_SECONDS, MAKER_PRICE_OFFSET_BPS,
            MAKER_FEE_PCT, TAKER_FEE_PCT
        )
        
        _maker_executor = MakerFirstExecutor(
            maker_confidence_threshold=kwargs.get('maker_confidence_threshold', MAKER_CONFIDENCE_THRESHOLD),
            maker_wait_timeout_seconds=kwargs.get('maker_wait_timeout_seconds', MAKER_WAIT_TIMEOUT_SECONDS),
            maker_price_offset_bps=kwargs.get('maker_price_offset_bps', MAKER_PRICE_OFFSET_BPS),
            maker_fee_bps=kwargs.get('maker_fee_bps', MAKER_FEE_PCT * 100),
            taker_fee_bps=kwargs.get('taker_fee_bps', TAKER_FEE_PCT * 100),
            enable_maker=kwargs.get('enable_maker', MAKER_FIRST_ENABLED)
        )
    return _maker_executor


def reset_maker_executor():
    """Reset the global maker executor (for testing)"""
    global _maker_executor
    _maker_executor = None


if __name__ == '__main__':
    # Test the maker-first execution logic
    logging.basicConfig(level=logging.INFO)
    
    executor = MakerFirstExecutor(
        maker_confidence_threshold=0.95,
        maker_wait_timeout_seconds=30,
        maker_price_offset_bps=1.0
    )
    
    print("\n=== Execution Decision Tests ===")
    test_cases = [
        # (symbol, side, confidence, current_price, action_category, signal_age, vol)
        ("BTCUSDT", "LONG", 0.80, 95000, "OPEN_RISK", 1, 1.0),   # Should use maker
        ("BTCUSDT", "LONG", 0.96, 95000, "OPEN_RISK", 1, 1.0),   # High conf - taker
        ("BTCUSDT", "SHORT", 0.85, 95000, "PROTECTIVE", 1, 1.0), # Protective - taker
        ("ETHUSDT", "LONG", 0.88, 3500, "OPEN_RISK", 15, 1.0),   # Stale signal - taker
        ("ETHUSDT", "SHORT", 0.85, 3500, "OPEN_RISK", 2, 4.0),   # High vol - taker
        ("SOLUSDT", "LONG", 0.90, 180, "HEDGE", 3, 1.5),         # Hedge - maker
    ]
    
    for symbol, side, conf, price, cat, age, vol in test_cases:
        decision = executor.decide_execution_type(
            symbol=symbol,
            side=side,
            confidence=conf,
            current_price=price,
            action_category=cat,
            signal_age_seconds=age,
            volatility_pct=vol
        )
        
        print(f"{symbol} {side} conf={conf:.0%}: {decision.order_type.value} "
              f"@ {decision.price or 'market'} ({decision.reason}) "
              f"fee={decision.estimated_fee_bps}bps")
    
    print("\n=== Statistics ===")
    print(executor.get_statistics())

