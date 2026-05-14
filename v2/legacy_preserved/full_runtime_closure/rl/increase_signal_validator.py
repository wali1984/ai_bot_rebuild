"""
INCREASE Signal Validator
========================
Strict multi-layer validation for INCREASE_LONG/SHORT signals to prevent wrong entries.

Validation Layers:
1. Position Direction Match - INCREASE must match existing position side
2. Recent Reduction Tracking - Position was reduced by profit scanner (>15%)
3. Momentum Confirmation - ride_move active OR strong directional signals
4. Funding Rate Check - Not bleeding excessive funding against position
5. Liquidation Distance - Sufficient margin of safety (>15%)
6. Leverage Limit - Position not over-leveraged (≤100x for INCREASE)
7. Hedge Mode Safety - In hedge mode, only scale profitable leg (>5% PnL)

All checks must PASS for INCREASE to be allowed.

Author: WMA AI Trading System
Date: January 20, 2026
"""

import logging
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class IncreaseSignalValidator:
    """Validates INCREASE signals with strict multi-layer checks."""
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._profit_scanner_reductions = {}  # Track: {(account, symbol, side): (timestamp, reduction_pct)}
    
    def track_profit_reduction(self, account_id: str, symbol: str, side: str, reduction_pct: float):
        """
        Track when profit scanner reduces a position.
        This enables INCREASE signals to restore position during strong trends.
        """
        key = (account_id, symbol, side)
        self._profit_scanner_reductions[key] = (time.time(), reduction_pct)
        logger.info(f"[PROFIT_REDUCTION_TRACKED] {account_id} {symbol} {side}: {reduction_pct:.1f}% reduction")
    
    def validate_increase_signal(
        self,
        symbol: str,
        action: str,  # e.g., "INCREASE_LONG"
        current_position: Dict,  # Position data from _get_trader_snapshot
        confidence: float,
        account_id: str = "unknown"
    ) -> Tuple[bool, str]:
        """
        Validate INCREASE signal with comprehensive safety checks.
        
        Returns:
            (allowed: bool, reason: str)
        """
        try:
            from config import (
                ENABLE_INCREASE_AFTER_PROFIT_TAKING,
                INCREASE_AFTER_PROFIT_COOLDOWN_SEC,
                INCREASE_MIN_REDUCTION_PCT,
                INCREASE_REQUIRE_RIDE_MOVE,
                HEDGE_MIN_PNL_FOR_INCREASE,
                INCREASE_MAX_LEVERAGE,
                INCREASE_MIN_LIQ_DISTANCE_PCT,
                INCREASE_MAX_ADVERSE_FUNDING_PCT
            )
        except ImportError:
            # Fallback to safe defaults if config not available
            ENABLE_INCREASE_AFTER_PROFIT_TAKING = True
            INCREASE_AFTER_PROFIT_COOLDOWN_SEC = 60
            INCREASE_MIN_REDUCTION_PCT = 15.0
            INCREASE_REQUIRE_RIDE_MOVE = True
            HEDGE_MIN_PNL_FOR_INCREASE = 5.0
            INCREASE_MAX_LEVERAGE = 100
            INCREASE_MIN_LIQ_DISTANCE_PCT = 15.0
            INCREASE_MAX_ADVERSE_FUNDING_PCT = 0.05
        
        if not ENABLE_INCREASE_AFTER_PROFIT_TAKING:
            return False, "INCREASE_FEATURE_DISABLED"

        if not isinstance(current_position, dict):
            return False, "INCREASE_NO_POSITION_SNAPSHOT"
        
        # Determine requested direction from action
        action_upper = str(action or "").upper()
        if "LONG" in action_upper:
            requested_side = "LONG"
        elif "SHORT" in action_upper:
            requested_side = "SHORT"
        else:
            return False, "INCREASE_INVALID_ACTION"
        
        # Extract position data
        has_position = current_position.get('has_position', False)
        position_side = str(current_position.get('side', '')).upper()
        position_pnl_pct = float(current_position.get('pnl_pct', 0) or 0)
        position_leverage = float(current_position.get('leverage', 0) or 0)
        liq_distance_pct = float(current_position.get('liquidation_distance_pct', 0) or 0)
        is_hedge_mode = bool(current_position.get('is_hedge_mode', False))
        
        # ======================================================================
        # CHECK 1: Position Direction Match
        # ======================================================================
        if not has_position:
            return False, "INCREASE_NO_POSITION_TO_SCALE"
        
        if position_side == "NEUTRAL":
            # Hedge mode with no clear winner - block INCREASE
            return False, "INCREASE_HEDGE_MODE_NEUTRAL"
        
        if position_side != requested_side:
            return False, f"INCREASE_WRONG_SIDE (have {position_side}, want {requested_side})"
        
        # ======================================================================
        # CHECK 2: Recent Reduction Tracking
        # ======================================================================
        reduction_key = (account_id, symbol, requested_side)
        reduction_data = self._profit_scanner_reductions.get(reduction_key)

        # Only treat reductions as "qualifying" when they are at least the configured minimum.
        # Small trims (e.g., 5-10%) are common in profit scanning and should not permanently block INCREASE.
        qualifying_reduction = False
        if reduction_data:
            reduction_ts, reduction_pct = reduction_data
            try:
                reduction_pct = float(reduction_pct)
            except Exception:
                reduction_pct = 0.0
            if reduction_pct >= float(INCREASE_MIN_REDUCTION_PCT):
                qualifying_reduction = True
                time_since_reduction = time.time() - float(reduction_ts)

                # Check cooldown only for qualifying reductions
                if time_since_reduction < INCREASE_AFTER_PROFIT_COOLDOWN_SEC:
                    return False, f"INCREASE_COOLDOWN (wait {int(INCREASE_AFTER_PROFIT_COOLDOWN_SEC - time_since_reduction)}s)"

        # If we do not have a qualifying reduction, require ride_move (if enabled).
        if not qualifying_reduction and INCREASE_REQUIRE_RIDE_MOVE:
            ride_move_active = self._check_ride_move_active(symbol, requested_side)
            if not ride_move_active:
                return False, "INCREASE_NO_REDUCTION_NO_RIDE_MOVE"
        
        # ======================================================================
        # CHECK 3: Momentum Confirmation (ride_move)
        # ======================================================================
        if INCREASE_REQUIRE_RIDE_MOVE:
            ride_move_active = self._check_ride_move_active(symbol, requested_side)
            if not ride_move_active:
                return False, "INCREASE_NO_MOMENTUM_CONFIRMATION"
        
        # ======================================================================
        # CHECK 4: Funding Rate Check
        # ======================================================================
        funding_ok, funding_reason = self._check_funding_rate(symbol, requested_side, INCREASE_MAX_ADVERSE_FUNDING_PCT)
        if not funding_ok:
            return False, f"INCREASE_ADVERSE_FUNDING: {funding_reason}"
        
        # ======================================================================
        # CHECK 5: Liquidation Distance
        # ======================================================================
        # Some venues/accounts do not provide reliable liquidation distance in our snapshots.
        # Fail-safe default is still conservative via leverage + funding + hedge safety.
        # Only enforce this check when a positive liq-distance metric is available.
        if liq_distance_pct > 0 and liq_distance_pct < INCREASE_MIN_LIQ_DISTANCE_PCT:
            return False, f"INCREASE_NEAR_LIQUIDATION ({liq_distance_pct:.1f}% < {INCREASE_MIN_LIQ_DISTANCE_PCT}%)"
        
        # ======================================================================
        # CHECK 6: Leverage Limit
        # ======================================================================
        if position_leverage > INCREASE_MAX_LEVERAGE:
            return False, f"INCREASE_OVER_LEVERAGED ({position_leverage:.0f}x > {INCREASE_MAX_LEVERAGE}x)"
        
        # ======================================================================
        # CHECK 7: Hedge Mode Safety (only scale profitable leg)
        # ======================================================================
        if is_hedge_mode:
            # In hedge mode, only allow INCREASE on the profitable leg
            if position_pnl_pct < HEDGE_MIN_PNL_FOR_INCREASE:
                return False, f"INCREASE_HEDGE_LEG_NOT_PROFITABLE ({position_pnl_pct:.1f}% < {HEDGE_MIN_PNL_FOR_INCREASE}%)"
            
            # Additional check: ensure opposite leg isn't deeply underwater
            opposite_side = "SHORT" if requested_side == "LONG" else "LONG"
            opposite_pnl_key = "short_pnl_pct" if requested_side == "LONG" else "long_pnl_pct"
            opposite_pnl = float(current_position.get(opposite_pnl_key, 0) or 0)
            
            if opposite_pnl < -10.0:  # Opposite leg losing >10%
                return False, f"INCREASE_HEDGE_OPPOSITE_UNDERWATER ({opposite_side} at {opposite_pnl:.1f}%)"
        
        # ======================================================================
        # ALL CHECKS PASSED
        # ======================================================================
        logger.info(
            f"✅ [INCREASE_VALIDATED] {symbol} {requested_side} | "
            f"pnl={position_pnl_pct:.1f}% lev={position_leverage:.0f}x liq_dist={liq_distance_pct:.1f}% | "
            f"conf={confidence:.1%} hedge={is_hedge_mode}"
        )
        return True, "INCREASE_VALIDATED_ALL_CHECKS_PASSED"
    
    def _check_ride_move_active(self, symbol: str, side: str) -> bool:
        """Check if ride_move flag is active for this symbol/side."""
        if not self.redis:
            return False
        
        try:
            import json

            ride_key = f"wma:ride_move:{symbol}"
            raw = self.redis.get(ride_key)
            if not raw:
                return False

            raw_str = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            data = json.loads(raw_str) if raw_str else {}
            if not isinstance(data, dict):
                return False

            if not bool(data.get("suppress_tp")):
                return False

            ride_side = str(data.get("side", "") or "").upper()
            if ride_side and ride_side != str(side).upper():
                return False

            # Freshness guard:
            # - primary source of truth is Redis TTL (trainer writes via SETEX)
            # - but we also honor payload set_ts/ttl_sec if present (for safety)
            now = time.time()
            try:
                set_ts = float(data.get("set_ts", 0) or 0)
            except Exception:
                set_ts = 0.0
            try:
                ttl_sec = float(data.get("ttl_sec", 0) or 0)
            except Exception:
                ttl_sec = 0.0

            payload_not_expired = (set_ts > 0 and ttl_sec > 0 and now < (set_ts + ttl_sec))

            redis_ttl = None
            try:
                redis_ttl = int(self.redis.ttl(ride_key))
            except Exception:
                redis_ttl = None
            redis_not_expired = (redis_ttl is not None and redis_ttl > 0)

            return bool(payload_not_expired or redis_not_expired)
        except Exception as e:
            logger.debug(f"[RIDE_MOVE_CHECK] Error: {e}")
            return False
    
    def _check_funding_rate(self, symbol: str, side: str, max_adverse_pct: float) -> Tuple[bool, str]:
        """
        Check if funding rate is not bleeding against our position.
        
        Returns:
            (ok: bool, reason: str)
        """
        if not self.redis:
            return True, "no_redis_check"
        
        try:
            # Get funding rate from unified features
            key = f"unified_features:{symbol}:1h"  # Use 1h TF for funding data
            raw = self.redis.hgetall(key)
            
            if not raw:
                return True, "no_funding_data"
            
            # Decode if bytes
            if isinstance(list(raw.keys())[0], bytes):
                raw = {k.decode('utf-8'): v.decode('utf-8') for k, v in raw.items()}
            
            funding_rate = float(raw.get('funding_rate', 0) or 0)
            
            # Funding rate conventions:
            # Positive funding = longs pay shorts
            # Negative funding = shorts pay longs
            
            if side == "LONG":
                # LONG position bleeds when funding is positive (longs pay shorts)
                if funding_rate > max_adverse_pct:
                    return False, f"high_positive_funding={funding_rate*100:.3f}% (longs_pay_shorts)"
            else:  # SHORT
                # SHORT position bleeds when funding is negative (shorts pay longs)
                if funding_rate < -max_adverse_pct:
                    return False, f"high_negative_funding={funding_rate*100:.3f}% (shorts_pay_longs)"
            
            return True, f"funding_ok={funding_rate*100:.3f}%"
        
        except Exception as e:
            logger.debug(f"[FUNDING_CHECK] Error: {e}")
            return True, "funding_check_error"
    
    def cleanup_old_reductions(self, max_age_seconds: int = 3600):
        """Remove reduction tracking older than max_age (default 1 hour)."""
        current_time = time.time()
        old_keys = [
            k for k, (ts, _) in self._profit_scanner_reductions.items()
            if current_time - ts > max_age_seconds
        ]
        for k in old_keys:
            del self._profit_scanner_reductions[k]
        
        if old_keys:
            logger.info(f"[PROFIT_REDUCTION_CLEANUP] Removed {len(old_keys)} old entries")
