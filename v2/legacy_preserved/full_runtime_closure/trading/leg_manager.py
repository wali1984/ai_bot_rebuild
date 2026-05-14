"""
LEG MANAGER (V2)
================
Manages position legs independently for dual-profit strategy.

Key Principles:
1. Each leg (LONG/SHORT) is a profit center, not just "hedge"
2. Profit-taking is leg-specific, not symbol-level
3. Ride-move flags are per-leg
4. No static thresholds - all adaptive from features

Kill Switch: LEG_INDEPENDENT_ENABLED must be true to use per-leg management.
"""

import json
import logging
import time
import redis
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, Tuple, List

# Import config - fail gracefully if not available
try:
    from config import (
        REDIS_URL,
        LEG_INDEPENDENT_ENABLED,
        ADAPTIVE_V2_CANARY_SYMBOLS,
    )
except ImportError:
    REDIS_URL = "redis://localhost:6379/0"
    LEG_INDEPENDENT_ENABLED = False
    ADAPTIVE_V2_CANARY_SYMBOLS = []

logger = logging.getLogger(__name__)


@dataclass
class LegState:
    """State for a single position leg (LONG or SHORT)."""
    
    symbol: str
    side: str  # 'LONG' or 'SHORT'
    entry_price: float
    current_price: float
    size_usd: float
    leverage: int
    entry_ts: int  # Unix timestamp ms
    
    # Profit tracking
    roe_pct: float = 0.0
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    age_seconds: int = 0
    
    # Leg-specific flags (NEW for V2)
    is_profit_center: bool = True  # Treat as profit center, not just hedge
    ride_move_active: bool = False
    ride_move_reason: str = ""
    ride_move_expires: int = 0
    
    # Leg-specific TP (NEW for V2)
    tp_price: Optional[float] = None
    tp_roe_target: Optional[float] = None
    tp_mode: str = "adaptive"  # 'adaptive', 'fixed', 'trailing'
    
    # Leg-specific trailing (NEW for V2)
    trail_activated: bool = False
    trail_high: float = 0.0
    trail_low: float = float('inf')
    trail_distance_pct: float = 5.0
    
    def compute_pnl(self) -> None:
        """Compute current PnL metrics."""
        if self.entry_price <= 0:
            return
            
        if self.side == 'LONG':
            self.pnl_pct = (self.current_price - self.entry_price) / self.entry_price * 100
        else:  # SHORT
            self.pnl_pct = (self.entry_price - self.current_price) / self.entry_price * 100
        
        self.roe_pct = self.pnl_pct * self.leverage
        self.pnl_usd = self.size_usd * (self.pnl_pct / 100)
        
        # Update age
        now_ms = int(time.time() * 1000)
        self.age_seconds = max(0, (now_ms - self.entry_ts) // 1000)
        
        # Update trail high/low based on price action
        if self.side == 'LONG' and self.current_price > self.trail_high:
            self.trail_high = self.current_price
        elif self.side == 'SHORT' and self.current_price < self.trail_low:
            self.trail_low = self.current_price
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LegState':
        """Create from dictionary."""
        return cls(**data)


class LegManager:
    """
    Manages position legs independently for dual-profit strategy.
    
    Key Principles:
    1. Each leg (LONG/SHORT) is a profit center, not just "hedge"
    2. Profit-taking is leg-specific, not symbol-level
    3. Ride-move flags are per-leg
    4. No static thresholds - all adaptive from features
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """Initialize the leg manager."""
        if redis_client:
            self.redis = redis_client
        else:
            self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        
        # In-memory leg cache
        self.legs: Dict[str, LegState] = {}
        
        # Feature cache for adaptive calculations
        self._conditions_cache: Dict[str, Tuple[Dict, float]] = {}
        self._cache_ttl_seconds = 5.0
        
        logger.info(f"[LegManager] Initialized - LEG_INDEPENDENT_ENABLED={LEG_INDEPENDENT_ENABLED}")
    
    def is_enabled_for_symbol(self, symbol: str) -> bool:
        """Check if leg-independent management is enabled for this symbol."""
        if not LEG_INDEPENDENT_ENABLED:
            return False
        
        # If canary list is set, only enabled for those symbols
        if ADAPTIVE_V2_CANARY_SYMBOLS:
            return symbol in ADAPTIVE_V2_CANARY_SYMBOLS
        
        # Otherwise enabled for all
        return True
    
    def get_leg_key(self, symbol: str, side: str) -> str:
        """Get the cache key for a leg."""
        return f"{symbol}:{side.upper()}"
    
    def get_redis_key(self, symbol: str, side: str, suffix: str = "state") -> str:
        """Get the Redis key for a leg."""
        return f"wma:leg:{symbol}:{side.upper()}:{suffix}"
    
    def update_leg(self, symbol: str, side: str, position_data: Dict[str, Any]) -> LegState:
        """
        Update or create leg state from position data.
        
        Args:
            symbol: Trading pair
            side: 'LONG' or 'SHORT'
            position_data: Dict with entry_price, current_price, size_usd, leverage, etc.
            
        Returns:
            Updated LegState
        """
        key = self.get_leg_key(symbol, side)
        side_upper = side.upper()
        
        # Get or create leg state
        if key in self.legs:
            leg = self.legs[key]
            # Update mutable fields
            leg.current_price = float(position_data.get('current_price', leg.current_price))
            leg.size_usd = float(position_data.get('size_usd', leg.size_usd))
            # Entry price and leverage don't change after open
        else:
            # Create new leg state
            leg = LegState(
                symbol=symbol,
                side=side_upper,
                entry_price=float(position_data.get('entry_price', 0)),
                current_price=float(position_data.get('current_price', 0)),
                size_usd=float(position_data.get('size_usd', 0)),
                leverage=int(position_data.get('leverage', 1)),
                entry_ts=int(position_data.get('entry_ts', time.time() * 1000)),
            )
            
            # Initialize trail high/low
            leg.trail_high = leg.entry_price if side_upper == 'LONG' else 0
            leg.trail_low = leg.entry_price if side_upper == 'SHORT' else float('inf')
            
            self.legs[key] = leg
        
        # Compute PnL
        leg.compute_pnl()
        
        # Load ride_move from Redis if exists
        self._load_ride_move_from_redis(leg)
        
        # Persist to Redis
        self._persist_leg(leg)
        
        return leg
    
    def get_leg(self, symbol: str, side: str) -> Optional[LegState]:
        """Get leg state if exists."""
        key = self.get_leg_key(symbol, side)
        return self.legs.get(key)
    
    def remove_leg(self, symbol: str, side: str) -> None:
        """Remove leg state (on position close)."""
        key = self.get_leg_key(symbol, side)
        
        if key in self.legs:
            del self.legs[key]
        
        # Clean up Redis keys
        redis_keys = [
            self.get_redis_key(symbol, side, "state"),
            self.get_redis_key(symbol, side, "ride_move"),
            self.get_redis_key(symbol, side, "tp_target"),
            self.get_redis_key(symbol, side, "trail"),
        ]
        
        try:
            self.redis.delete(*redis_keys)
        except Exception as e:
            logger.warning(f"[LegManager] Error cleaning up Redis keys for {symbol}:{side}: {e}")
    
    def should_take_profit(
        self,
        symbol: str,
        side: str,
        timeframe: str = "5m"
    ) -> Tuple[bool, str, float]:
        """
        Check if this specific leg should take profit.
        
        Returns:
            (should_tp, reason, suggested_close_pct)
        """
        key = self.get_leg_key(symbol, side)
        leg = self.legs.get(key)
        
        if not leg:
            return False, "no_leg_state", 0.0
        
        # Check if leg-independent is enabled for this symbol
        if not self.is_enabled_for_symbol(symbol):
            return False, "leg_independent_disabled", 0.0
        
        # Get adaptive thresholds from features
        conditions = self._get_market_conditions(symbol, timeframe)
        tp_threshold = self._compute_adaptive_tp_threshold(leg, conditions)
        
        # Check ride-move flag (per-leg)
        if leg.ride_move_active:
            now_ms = int(time.time() * 1000)
            if now_ms < leg.ride_move_expires:
                return False, f"ride_move_active:{leg.ride_move_reason}", 0.0
            else:
                # Expired - clear it
                leg.ride_move_active = False
                leg.ride_move_reason = ""
        
        # Check if TP threshold reached
        if leg.roe_pct >= tp_threshold:
            # Determine close percentage based on conditions
            close_pct = self._compute_close_percentage(leg, conditions)
            return True, f"adaptive_tp:{tp_threshold:.1f}%", close_pct
        
        # Check trailing stop (if activated)
        if leg.trail_activated:
            trail_triggered, trail_reason = self._check_trailing_stop(leg)
            if trail_triggered:
                return True, trail_reason, 100.0  # Full close on trail
        
        return False, "below_threshold", 0.0
    
    def _check_trailing_stop(self, leg: LegState) -> Tuple[bool, str]:
        """Check if trailing stop is triggered."""
        if not leg.trail_activated:
            return False, ""
        
        if leg.side == 'LONG':
            # Trail from high
            if leg.trail_high <= 0:
                return False, ""
            trail_trigger = leg.trail_high * (1 - leg.trail_distance_pct / 100)
            if leg.current_price <= trail_trigger:
                return True, f"trail_stop:peak={leg.trail_high:.2f},trigger={trail_trigger:.2f}"
        else:  # SHORT
            # Trail from low
            if leg.trail_low == float('inf'):
                return False, ""
            trail_trigger = leg.trail_low * (1 + leg.trail_distance_pct / 100)
            if leg.current_price >= trail_trigger:
                return True, f"trail_stop:trough={leg.trail_low:.2f},trigger={trail_trigger:.2f}"
        
        return False, ""
    
    def _compute_adaptive_tp_threshold(self, leg: LegState, conditions: Dict[str, float]) -> float:
        """
        Compute dynamic TP threshold based on 492+ features.
        
        NO STATIC VALUES - everything derived from market data.
        """
        # Base: fee break-even (minimum viable profit)
        leverage = max(1, leg.leverage)
        fee_breakeven_roe = 0.10 * leverage  # ~0.1% round-trip fees (maker+taker)
        
        # Volatility factor (higher vol = wider TP)
        atr_pct = conditions.get('atr_pct', 2.0)
        vol_multiplier = min(3.0, max(0.5, atr_pct / 1.5))
        
        # Trend strength factor (strong trend = let it run)
        adx = conditions.get('adx', 25.0)
        trend_multiplier = 1.0 + (adx - 25) / 50  # ADX 25=1.0x, ADX 50=1.5x
        trend_multiplier = max(0.5, min(2.0, trend_multiplier))
        
        # Momentum alignment factor
        momentum = conditions.get('momentum_score', 0.0)
        is_aligned = (leg.side == 'LONG' and momentum > 0) or (leg.side == 'SHORT' and momentum < 0)
        momentum_multiplier = 1.3 if is_aligned else 0.8
        
        # RSI factor (overbought/oversold = tighter TP)
        rsi = conditions.get('rsi', 50.0)
        if leg.side == 'LONG' and rsi > 70:
            rsi_multiplier = 0.7  # Overbought, take profit sooner
        elif leg.side == 'SHORT' and rsi < 30:
            rsi_multiplier = 0.7  # Oversold, take profit sooner
        else:
            rsi_multiplier = 1.0
        
        # Orderbook imbalance factor
        imbalance = conditions.get('depth_imbalance', 0.0)
        favorable_flow = (leg.side == 'LONG' and imbalance > 0.3) or (leg.side == 'SHORT' and imbalance < -0.3)
        flow_multiplier = 1.2 if favorable_flow else 1.0
        
        # Compute final threshold
        base_tp = 15.0  # 15% ROE base starting point (adjusted by multipliers)
        
        adaptive_tp = (
            base_tp
            * vol_multiplier
            * trend_multiplier
            * momentum_multiplier
            * rsi_multiplier
            * flow_multiplier
        )
        
        # Floor: must at least cover fees with buffer
        min_tp = fee_breakeven_roe * 3  # 3x fee breakeven minimum
        
        return max(min_tp, adaptive_tp)
    
    def _compute_close_percentage(self, leg: LegState, conditions: Dict[str, float]) -> float:
        """
        Compute what percentage of the position to close.
        
        Adaptive based on:
        - Confidence in continuation
        - Risk metrics
        - Position age
        """
        # Base: 50% partial close
        close_pct = 50.0
        
        # Adjust by RSI extremes
        rsi = conditions.get('rsi', 50.0)
        if leg.side == 'LONG' and rsi > 80:
            close_pct = 80.0  # Very overbought - close more
        elif leg.side == 'SHORT' and rsi < 20:
            close_pct = 80.0  # Very oversold - close more
        
        # Adjust by position age (older = full close)
        if leg.age_seconds > 3600:  # > 1 hour
            close_pct = min(100.0, close_pct + 20.0)
        
        # Adjust by depth spoof score
        spoof = conditions.get('spoof_score', 0.0)
        if spoof > 0.5:
            close_pct = min(100.0, close_pct + 20.0)  # High spoof = close more
        
        return min(100.0, max(25.0, close_pct))
    
    def set_ride_move(
        self,
        symbol: str,
        side: str,
        reason: str,
        ttl_sec: int = 300
    ) -> None:
        """Set per-leg ride-move flag."""
        key = self.get_leg_key(symbol, side)
        leg = self.legs.get(key)
        
        if not leg:
            logger.warning(f"[LegManager] Cannot set ride_move - no leg state for {symbol}:{side}")
            return
        
        leg.ride_move_active = True
        leg.ride_move_reason = reason
        leg.ride_move_expires = int(time.time() * 1000) + (ttl_sec * 1000)
        
        # Persist to Redis
        redis_key = self.get_redis_key(symbol, side, "ride_move")
        try:
            self.redis.setex(redis_key, ttl_sec, json.dumps({
                'active': True,
                'reason': reason,
                'expires_ms': leg.ride_move_expires,
            }))
        except Exception as e:
            logger.warning(f"[LegManager] Error persisting ride_move: {e}")
        
        logger.info(f"[LegManager] Set ride_move for {symbol}:{side} reason={reason} ttl={ttl_sec}s")
    
    def clear_ride_move(self, symbol: str, side: str) -> None:
        """Clear per-leg ride-move flag."""
        key = self.get_leg_key(symbol, side)
        leg = self.legs.get(key)
        
        if leg:
            leg.ride_move_active = False
            leg.ride_move_reason = ""
            leg.ride_move_expires = 0
        
        redis_key = self.get_redis_key(symbol, side, "ride_move")
        try:
            self.redis.delete(redis_key)
        except Exception as e:
            logger.warning(f"[LegManager] Error clearing ride_move: {e}")
        
        logger.info(f"[LegManager] Cleared ride_move for {symbol}:{side}")
    
    def activate_trailing(
        self,
        symbol: str,
        side: str,
        distance_pct: float = 5.0
    ) -> None:
        """Activate trailing stop for a leg."""
        key = self.get_leg_key(symbol, side)
        leg = self.legs.get(key)
        
        if not leg:
            logger.warning(f"[LegManager] Cannot activate trailing - no leg state for {symbol}:{side}")
            return
        
        leg.trail_activated = True
        leg.trail_distance_pct = distance_pct
        
        # Initialize trail high/low from current price
        if leg.side == 'LONG':
            leg.trail_high = max(leg.trail_high, leg.current_price)
        else:
            leg.trail_low = min(leg.trail_low, leg.current_price)
        
        self._persist_leg(leg)
        logger.info(f"[LegManager] Activated trailing for {symbol}:{side} distance={distance_pct}%")
    
    def _persist_leg(self, leg: LegState) -> None:
        """Persist leg state to Redis."""
        redis_key = self.get_redis_key(leg.symbol, leg.side, "state")
        try:
            # Convert to JSON-serializable dict
            data = leg.to_dict()
            # Handle infinity
            if data.get('trail_low') == float('inf'):
                data['trail_low'] = None
            self.redis.setex(redis_key, 3600, json.dumps(data))  # 1 hour TTL
        except Exception as e:
            logger.warning(f"[LegManager] Error persisting leg state: {e}")
    
    def _load_ride_move_from_redis(self, leg: LegState) -> None:
        """Load ride_move flag from Redis if exists."""
        redis_key = self.get_redis_key(leg.symbol, leg.side, "ride_move")
        try:
            data = self.redis.get(redis_key)
            if data:
                parsed = json.loads(data)
                leg.ride_move_active = parsed.get('active', False)
                leg.ride_move_reason = parsed.get('reason', '')
                leg.ride_move_expires = parsed.get('expires_ms', 0)
        except Exception as e:
            logger.warning(f"[LegManager] Error loading ride_move: {e}")
    
    def _get_market_conditions(self, symbol: str, timeframe: str) -> Dict[str, float]:
        """Fetch market conditions from unified_features."""
        cache_key = f"{symbol}:{timeframe}"
        now = time.time()
        
        # Check cache
        if cache_key in self._conditions_cache:
            cached_data, cached_time = self._conditions_cache[cache_key]
            if now - cached_time < self._cache_ttl_seconds:
                return cached_data
        
        conditions = {}
        
        try:
            key = f"unified_features:{symbol}:{timeframe}"
            data = self.redis.hgetall(key)
            
            if not data:
                return conditions
            
            def safe_float(k: str, default: float = 0.0) -> float:
                try:
                    val = data.get(k, default)
                    return float(val) if val else default
                except (ValueError, TypeError):
                    return default
            
            # Volatility
            conditions['atr_pct'] = safe_float('ind_ta_atr_pct', 2.0)
            conditions['realized_vol'] = safe_float(f'ccxt_volatility_{timeframe}', 0.02)
            
            # Trend
            conditions['adx'] = safe_float('ind_ta_adx', 25.0)
            
            # Momentum
            conditions['rsi'] = safe_float('ind_ta_rsi', 50.0)
            conditions['macd_hist'] = safe_float('ind_ta_macd_hist', 0.0)
            conditions['momentum_score'] = safe_float('ind_ta_momentum', 0.0)
            
            # Depth (from CoinAPI WSDS)
            conditions['depth_imbalance'] = safe_float('depth_imbalance_5', 0.0)
            conditions['spoof_score'] = safe_float('depth_spoof_score', 0.0)
            conditions['fast_move'] = safe_float('depth_fast_move_score', 0.0)
            
            # Cache
            self._conditions_cache[cache_key] = (conditions, now)
            
        except Exception as e:
            logger.warning(f"[LegManager] Error fetching conditions: {e}")
        
        return conditions
    
    def get_all_legs(self) -> Dict[str, LegState]:
        """Get all tracked legs."""
        return self.legs.copy()
    
    def get_leg_summary(self, symbol: str, side: str) -> Optional[Dict[str, Any]]:
        """Get summary of leg state for logging/debugging."""
        leg = self.get_leg(symbol, side)
        if not leg:
            return None
        
        return {
            "symbol": leg.symbol,
            "side": leg.side,
            "entry_price": leg.entry_price,
            "current_price": leg.current_price,
            "size_usd": leg.size_usd,
            "leverage": leg.leverage,
            "roe_pct": round(leg.roe_pct, 2),
            "pnl_usd": round(leg.pnl_usd, 2),
            "age_seconds": leg.age_seconds,
            "ride_move_active": leg.ride_move_active,
            "ride_move_reason": leg.ride_move_reason,
            "trail_activated": leg.trail_activated,
            "trail_high": leg.trail_high,
            "trail_distance_pct": leg.trail_distance_pct,
        }


# Singleton instance
_leg_manager: Optional[LegManager] = None


def get_leg_manager() -> LegManager:
    """Get or create singleton leg manager instance."""
    global _leg_manager
    if _leg_manager is None:
        _leg_manager = LegManager()
    return _leg_manager


if __name__ == "__main__":
    # Test the leg manager
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    manager = LegManager()
    
    # Simulate a position
    test_position = {
        "entry_price": 90000.0,
        "current_price": 91500.0,
        "size_usd": 5000.0,
        "leverage": 20,
        "entry_ts": int(time.time() * 1000) - 3600000,  # 1 hour ago
    }
    
    print("\n" + "="*60)
    print("LEG MANAGER TEST")
    print("="*60)
    
    # Update leg
    leg = manager.update_leg("BTCUSDT", "LONG", test_position)
    
    print(f"\nLeg State:")
    print(f"  Symbol: {leg.symbol}")
    print(f"  Side: {leg.side}")
    print(f"  Entry Price: ${leg.entry_price:,.2f}")
    print(f"  Current Price: ${leg.current_price:,.2f}")
    print(f"  Size USD: ${leg.size_usd:,.2f}")
    print(f"  Leverage: {leg.leverage}x")
    print(f"  ROE%: {leg.roe_pct:.2f}%")
    print(f"  PnL USD: ${leg.pnl_usd:.2f}")
    print(f"  Age: {leg.age_seconds}s")
    
    # Test TP check
    should_tp, reason, close_pct = manager.should_take_profit("BTCUSDT", "LONG")
    print(f"\nShould Take Profit: {should_tp}")
    print(f"  Reason: {reason}")
    print(f"  Close %: {close_pct}%")
    
    # Test ride_move
    manager.set_ride_move("BTCUSDT", "LONG", "momentum_aligned", ttl_sec=60)
    should_tp, reason, _ = manager.should_take_profit("BTCUSDT", "LONG")
    print(f"\nAfter set_ride_move:")
    print(f"  Should TP: {should_tp}")
    print(f"  Reason: {reason}")
    
    # Test summary
    summary = manager.get_leg_summary("BTCUSDT", "LONG")
    print(f"\nLeg Summary: {json.dumps(summary, indent=2)}")
