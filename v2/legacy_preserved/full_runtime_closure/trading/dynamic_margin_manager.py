"""
DYNAMIC MARGIN MANAGER (V2)
===========================
Adaptive margin utilization based on real-time market conditions.

Uses unified_features to determine safe margin levels, reducing caps
when market conditions are risky (high volatility, near liquidations,
wide spreads, counter-trend momentum).

Kill Switch: MARGIN_85_ENABLED must be true to use V2 caps.
"""

import json
import logging
import redis
from typing import Dict, Any, Optional, Tuple

# Import config - fail gracefully if not available
try:
    from config import (
        REDIS_URL,
        # V2 caps (elevated)
        MAX_MARGIN_UTIL_OPEN_V2_PCT,
        MAX_MARGIN_UTIL_HEDGE_V2_PCT,
        MAX_MARGIN_UTIL_ABSOLUTE_V2_PCT,
        # V1 caps (legacy)
        MAX_MARGIN_UTIL_OPEN_PCT,
        MAX_MARGIN_UTIL_HEDGE_PCT,
        MAX_MARGIN_UTIL_ABSOLUTE_PCT,
        # Adaptive settings
        MARGIN_85_ENABLED,
        MARGIN_ADAPTIVE_MAX_REDUCTION_PCT,
        MARGIN_RISK_WEIGHT_VOLATILITY,
        MARGIN_RISK_WEIGHT_LIQUIDATION,
        MARGIN_RISK_WEIGHT_SPREAD,
        MARGIN_RISK_WEIGHT_MOMENTUM,
        # Floors
        MARGIN_FLOOR_OPEN_PCT,
        MARGIN_FLOOR_HEDGE_PCT,
        MARGIN_FLOOR_ABSOLUTE_PCT,
    )
except ImportError:
    # Fallback defaults
    REDIS_URL = "redis://localhost:6379/0"
    MAX_MARGIN_UTIL_OPEN_V2_PCT = 60.0
    MAX_MARGIN_UTIL_HEDGE_V2_PCT = 80.0
    MAX_MARGIN_UTIL_ABSOLUTE_V2_PCT = 85.0
    MAX_MARGIN_UTIL_OPEN_PCT = 50.0
    MAX_MARGIN_UTIL_HEDGE_PCT = 70.0
    MAX_MARGIN_UTIL_ABSOLUTE_PCT = 75.0
    MARGIN_85_ENABLED = False
    MARGIN_ADAPTIVE_MAX_REDUCTION_PCT = 20.0
    MARGIN_RISK_WEIGHT_VOLATILITY = 0.35
    MARGIN_RISK_WEIGHT_LIQUIDATION = 0.30
    MARGIN_RISK_WEIGHT_SPREAD = 0.20
    MARGIN_RISK_WEIGHT_MOMENTUM = 0.15
    MARGIN_FLOOR_OPEN_PCT = 30.0
    MARGIN_FLOOR_HEDGE_PCT = 50.0
    MARGIN_FLOOR_ABSOLUTE_PCT = 60.0

logger = logging.getLogger(__name__)


class DynamicMarginManager:
    """
    Adaptive margin utilization based on real-time market conditions.
    
    Uses unified_features (492+ fields) to determine safe margin levels.
    Reduces caps when conditions are risky to protect capital.
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """Initialize the margin manager."""
        if redis_client:
            self.redis = redis_client
        else:
            self.redis = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        
        # Cache for conditions to avoid repeated Redis calls
        self._conditions_cache: Dict[str, Tuple[Dict, float]] = {}
        self._cache_ttl_seconds = 5.0  # Refresh conditions every 5s
        
        logger.info(f"[DynamicMarginManager] Initialized - MARGIN_85_ENABLED={MARGIN_85_ENABLED}")
    
    def get_safe_margin_cap(
        self,
        symbol: str,
        action_type: str,
        timeframe: str = "5m"
    ) -> float:
        """
        Calculate safe margin cap based on current conditions.
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            action_type: 'open', 'hedge', or 'absolute'
            timeframe: Timeframe for features (default 5m for trading)
            
        Returns:
            Safe margin utilization percentage (0-85)
        """
        # Get base caps based on kill switch
        if MARGIN_85_ENABLED:
            base_caps = {
                'open': MAX_MARGIN_UTIL_OPEN_V2_PCT,
                'hedge': MAX_MARGIN_UTIL_HEDGE_V2_PCT,
                'absolute': MAX_MARGIN_UTIL_ABSOLUTE_V2_PCT,
            }
            floors = {
                'open': MARGIN_FLOOR_OPEN_PCT,
                'hedge': MARGIN_FLOOR_HEDGE_PCT,
                'absolute': MARGIN_FLOOR_ABSOLUTE_PCT,
            }
        else:
            # Use legacy V1 caps (no adaptive reduction)
            base_caps = {
                'open': MAX_MARGIN_UTIL_OPEN_PCT,
                'hedge': MAX_MARGIN_UTIL_HEDGE_PCT,
                'absolute': MAX_MARGIN_UTIL_ABSOLUTE_PCT,
            }
            # Return immediately without adaptive reduction when V2 disabled
            return base_caps.get(action_type, MAX_MARGIN_UTIL_OPEN_PCT)
        
        base = base_caps.get(action_type, MAX_MARGIN_UTIL_OPEN_V2_PCT)
        floor = floors.get(action_type, MARGIN_FLOOR_OPEN_PCT)
        
        # Get market conditions
        conditions = self._fetch_conditions(symbol, timeframe)
        
        # If no conditions available, use base cap (fail-safe)
        if not conditions:
            logger.debug(f"[DynamicMarginManager] No conditions for {symbol}, using base cap {base}%")
            return base
        
        # Calculate risk factors (each returns 0.0 to 1.0)
        vol_factor = self._volatility_risk(conditions)
        liq_factor = self._liquidation_risk(conditions)
        spread_factor = self._spread_risk(conditions)
        momentum_factor = self._momentum_risk(conditions)
        
        # Combined risk score (weighted average)
        risk_score = (
            MARGIN_RISK_WEIGHT_VOLATILITY * vol_factor +
            MARGIN_RISK_WEIGHT_LIQUIDATION * liq_factor +
            MARGIN_RISK_WEIGHT_SPREAD * spread_factor +
            MARGIN_RISK_WEIGHT_MOMENTUM * momentum_factor
        )
        
        # Clamp to 0-1
        risk_score = max(0.0, min(1.0, risk_score))
        
        # Reduce cap based on risk
        reduction = risk_score * MARGIN_ADAPTIVE_MAX_REDUCTION_PCT
        safe_cap = base - reduction
        
        # Apply floor
        safe_cap = max(safe_cap, floor)
        
        logger.debug(
            f"[DynamicMarginManager] {symbol} {action_type}: "
            f"base={base}% risk={risk_score:.2f} reduction={reduction:.1f}% "
            f"safe_cap={safe_cap:.1f}%"
        )
        
        return round(safe_cap, 2)
    
    def _fetch_conditions(self, symbol: str, timeframe: str) -> Dict[str, float]:
        """
        Fetch market conditions from unified_features.
        
        Returns dict with normalized condition values.
        """
        import time
        
        cache_key = f"{symbol}:{timeframe}"
        now = time.time()
        
        # Check cache
        if cache_key in self._conditions_cache:
            cached_data, cached_time = self._conditions_cache[cache_key]
            if now - cached_time < self._cache_ttl_seconds:
                return cached_data
        
        conditions = {}
        
        try:
            # Fetch from unified_features
            key = f"unified_features:{symbol}:{timeframe}"
            data = self.redis.hgetall(key)
            
            if not data:
                return conditions
            
            # Extract relevant features for risk calculation
            def safe_float(k: str, default: float = 0.0) -> float:
                try:
                    val = data.get(k, default)
                    return float(val) if val else default
                except (ValueError, TypeError):
                    return default
            
            # Volatility metrics
            conditions['atr_pct'] = safe_float('ind_ta_atr_pct', 2.0)
            conditions['realized_vol_5m'] = safe_float(f'ccxt_volatility_{timeframe}', 0.02)
            conditions['bb_width_pct'] = safe_float('ind_ta_bb_width_pct', 4.0)
            
            # Liquidation metrics (NEW from enhanced liquidation engine)
            conditions['liq_long_distance_pct'] = safe_float('liquidation_long_distance_pct', 10.0)
            conditions['liq_short_distance_pct'] = safe_float('liquidation_short_distance_pct', 10.0)
            conditions['liq_staleness_ms'] = safe_float('liquidation_staleness_ms', 0)
            conditions['liq_is_stale'] = safe_float('liquidation_is_stale', 0)
            
            # Spread metrics (from CoinAPI WSDS depth features)
            conditions['spread'] = safe_float('depth_spread', 0.001)
            conditions['depth_imbalance'] = safe_float('depth_imbalance_5', 0.0)
            conditions['spoof_score'] = safe_float('depth_spoof_score', 0.0)
            conditions['fast_move_score'] = safe_float('depth_fast_move_score', 0.0)
            
            # Momentum metrics
            conditions['rsi'] = safe_float('ind_ta_rsi', 50.0)
            conditions['macd_hist'] = safe_float('ind_ta_macd_hist', 0.0)
            conditions['price_change_pct'] = safe_float(f'ccxt_price_change_{timeframe}_pct', 0.0)
            
            # Cache the result
            self._conditions_cache[cache_key] = (conditions, now)
            
        except Exception as e:
            logger.warning(f"[DynamicMarginManager] Error fetching conditions for {symbol}: {e}")
        
        return conditions
    
    def _volatility_risk(self, conditions: Dict[str, float]) -> float:
        """
        Higher volatility = higher risk score.
        
        Returns 0.0 (low risk) to 1.0 (high risk).
        """
        atr_pct = conditions.get('atr_pct', 2.0)
        realized_vol = conditions.get('realized_vol_5m', 0.02)
        bb_width = conditions.get('bb_width_pct', 4.0)
        
        # Normalize each to 0-1 scale
        # ATR: 5% or higher = max risk
        atr_risk = min(1.0, atr_pct / 5.0)
        
        # Realized vol: 5% or higher = max risk
        vol_risk = min(1.0, realized_vol / 0.05)
        
        # BB width: 10% or higher = max risk
        bb_risk = min(1.0, bb_width / 10.0)
        
        return (atr_risk + vol_risk + bb_risk) / 3.0
    
    def _liquidation_risk(self, conditions: Dict[str, float]) -> float:
        """
        Closer to liquidation clusters = higher risk.
        
        Returns 0.0 (low risk) to 1.0 (high risk).
        """
        liq_long_dist = conditions.get('liq_long_distance_pct', 10.0)
        liq_short_dist = conditions.get('liq_short_distance_pct', 10.0)
        liq_is_stale = conditions.get('liq_is_stale', 0)
        
        # If liquidation data is stale, use moderate risk assumption
        if liq_is_stale > 0:
            return 0.5
        
        # Closer distance = higher risk (inverse relationship)
        # 5% or more distance = low risk (0.0)
        # 0% distance = max risk (1.0)
        min_dist = min(liq_long_dist, liq_short_dist)
        
        # Handle edge cases
        if min_dist >= 100.0:  # No valid liquidation data
            return 0.3  # Moderate assumption
        
        return max(0.0, 1.0 - (min_dist / 5.0))
    
    def _spread_risk(self, conditions: Dict[str, float]) -> float:
        """
        Wider spread = higher risk (illiquid market).
        
        Returns 0.0 (low risk) to 1.0 (high risk).
        """
        spread = conditions.get('spread', 0.001)
        spoof_score = conditions.get('spoof_score', 0.0)
        
        # Spread: 0.1% or higher = max risk
        # BTC typical spread is ~0.001% (very tight)
        spread_risk = min(1.0, spread / 0.001)  # 0.1% spread = risk 1.0
        
        # Spoof score directly maps to risk (0-1 already)
        spoof_risk = min(1.0, spoof_score)
        
        # Weight spread more than spoof
        return 0.7 * spread_risk + 0.3 * spoof_risk
    
    def _momentum_risk(self, conditions: Dict[str, float]) -> float:
        """
        Counter-trend momentum = higher risk for new entries.
        
        Returns 0.0 (low risk) to 1.0 (high risk).
        """
        rsi = conditions.get('rsi', 50.0)
        fast_move = conditions.get('fast_move_score', 0.0)
        
        # Extreme RSI = higher risk (overbought/oversold)
        # RSI 50 = neutral (0 risk), RSI 30/70 = moderate, RSI 20/80 = high
        rsi_deviation = abs(rsi - 50.0)
        rsi_risk = min(1.0, rsi_deviation / 30.0)  # RSI 20 or 80 = risk 1.0
        
        # Fast move score directly indicates momentum exhaustion risk
        fast_move_risk = min(1.0, fast_move)
        
        return 0.6 * rsi_risk + 0.4 * fast_move_risk
    
    def get_margin_status(self, symbol: str, timeframe: str = "5m") -> Dict[str, Any]:
        """
        Get detailed margin status for debugging/monitoring.
        
        Returns dict with all factors and calculated caps.
        """
        conditions = self._fetch_conditions(symbol, timeframe)
        
        vol_factor = self._volatility_risk(conditions)
        liq_factor = self._liquidation_risk(conditions)
        spread_factor = self._spread_risk(conditions)
        momentum_factor = self._momentum_risk(conditions)
        
        risk_score = (
            MARGIN_RISK_WEIGHT_VOLATILITY * vol_factor +
            MARGIN_RISK_WEIGHT_LIQUIDATION * liq_factor +
            MARGIN_RISK_WEIGHT_SPREAD * spread_factor +
            MARGIN_RISK_WEIGHT_MOMENTUM * momentum_factor
        )
        
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "margin_85_enabled": MARGIN_85_ENABLED,
            "conditions": conditions,
            "risk_factors": {
                "volatility": round(vol_factor, 4),
                "liquidation": round(liq_factor, 4),
                "spread": round(spread_factor, 4),
                "momentum": round(momentum_factor, 4),
            },
            "risk_score": round(risk_score, 4),
            "caps": {
                "open": self.get_safe_margin_cap(symbol, "open", timeframe),
                "hedge": self.get_safe_margin_cap(symbol, "hedge", timeframe),
                "absolute": self.get_safe_margin_cap(symbol, "absolute", timeframe),
            },
        }


# Singleton instance for easy import
_margin_manager: Optional[DynamicMarginManager] = None


def get_margin_manager() -> DynamicMarginManager:
    """Get or create singleton margin manager instance."""
    global _margin_manager
    if _margin_manager is None:
        _margin_manager = DynamicMarginManager()
    return _margin_manager


if __name__ == "__main__":
    # Test the margin manager
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    manager = DynamicMarginManager()
    
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    
    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"MARGIN STATUS: {symbol}")
        print('='*60)
        
        status = manager.get_margin_status(symbol)
        
        print(f"  MARGIN_85_ENABLED: {status['margin_85_enabled']}")
        print(f"  Risk Score: {status['risk_score']}")
        print(f"  Risk Factors:")
        for k, v in status['risk_factors'].items():
            print(f"    - {k}: {v}")
        print(f"  Safe Caps:")
        for k, v in status['caps'].items():
            print(f"    - {k}: {v}%")
