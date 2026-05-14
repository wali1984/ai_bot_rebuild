"""
Anti-Churn Manager
==================
Implements comprehensive anti-churn protections for the trading system.

Features:
- Per-symbol execution caps by action type (hedge, partial close, flip)
- Warm start window to prevent burst after restart
- Hedge state machine with minimum intervals
- Signal freshness validation

Implements Addendum C: Anti-Churn Protections

Author: WMA AI Trading System
Date: December 24, 2025
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from enum import Enum

logger = logging.getLogger(__name__)


class ActionCategory(Enum):
    """Categories of actions for rate limiting."""
    HEDGE = "HEDGE"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    FLIP = "FLIP"
    ENTRY = "ENTRY"
    FULL_CLOSE = "FULL_CLOSE"
    OTHER = "OTHER"


class BlockReason(Enum):
    """Anti-churn block reasons for skip streams."""
    ANTI_CHURN_BLOCK = "ANTI_CHURN_BLOCK"
    HEDGE_STATE_COOLDOWN_BLOCK = "HEDGE_STATE_COOLDOWN_BLOCK"
    SYMBOL_RATE_LIMIT_BLOCK = "SYMBOL_RATE_LIMIT_BLOCK"
    WARM_START_BLOCK = "WARM_START_BLOCK"
    SIGNAL_STALE_BLOCK = "SIGNAL_STALE_BLOCK"


@dataclass
class ActionCount:
    """Tracks action counts per symbol per hour."""
    hedge_count: int = 0
    partial_close_count: int = 0
    flip_count: int = 0
    hour_start_ts: float = 0.0


class AntiChurnManager:
    """
    Manages anti-churn protections for the trading system.
    
    Enforces:
    - Per-symbol execution caps (configurable per action type)
    - Warm start window after restart
    - Hedge state machine cooldowns
    - Signal freshness validation
    """
    
    def __init__(self, startup_ts: float = None):
        """
        Initialize the Anti-Churn Manager.
        
        Args:
            startup_ts: Timestamp of system startup (for warm start calculation)
        """
        # Load config
        from config import (
            ANTI_CHURN_HEDGE_ADJUSTMENTS_PER_HOUR,
            ANTI_CHURN_PARTIAL_CLOSES_PER_HOUR,
            ANTI_CHURN_FLIPS_PER_HOUR,
            ANTI_CHURN_HEDGE_STATE_MIN_INTERVAL_SEC,
            ANTI_CHURN_WARM_START_WINDOW_SEC,
            TRADER_MAX_SIGNAL_AGE_MS,
        )
        
        self.max_hedge_per_hour = ANTI_CHURN_HEDGE_ADJUSTMENTS_PER_HOUR
        self.max_partial_close_per_hour = ANTI_CHURN_PARTIAL_CLOSES_PER_HOUR
        self.max_flips_per_hour = ANTI_CHURN_FLIPS_PER_HOUR
        self.hedge_state_min_interval = ANTI_CHURN_HEDGE_STATE_MIN_INTERVAL_SEC
        self.warm_start_window = ANTI_CHURN_WARM_START_WINDOW_SEC
        
        # State tracking
        self.startup_ts = startup_ts or time.time()
        self._action_counts: Dict[str, ActionCount] = defaultdict(ActionCount)
        self._last_hedge_action_ts: Dict[str, float] = {}
        self._total_blocked = 0
        self._total_allowed = 0
        
        logger.info(
            f"[ANTI_CHURN] Initialized: "
            f"max_hedge={self.max_hedge_per_hour}/hr, "
            f"max_partial={self.max_partial_close_per_hour}/hr, "
            f"max_flip={self.max_flips_per_hour}/hr, "
            f"hedge_interval={self.hedge_state_min_interval}s, "
            f"warm_start={self.warm_start_window}s"
        )
    
    def categorize_action(self, action_name: str) -> ActionCategory:
        """
        Categorize an action for rate limiting purposes.
        
        Args:
            action_name: The action name (e.g., "OPEN_LONG", "PARTIAL_CLOSE")
            
        Returns:
            ActionCategory enum value
        """
        action_upper = action_name.upper()
        
        if any(x in action_upper for x in ["HEDGE", "OPEN_HEDGE", "SCALE_HEDGE", "UNWIND_HEDGE"]):
            return ActionCategory.HEDGE
        elif any(x in action_upper for x in ["PARTIAL", "DECREASE"]):
            return ActionCategory.PARTIAL_CLOSE
        elif any(x in action_upper for x in ["FLIP", "CLOSE_AND_LONG", "CLOSE_AND_SHORT"]):
            return ActionCategory.FLIP
        elif any(x in action_upper for x in ["OPEN_LONG", "OPEN_SHORT", "INCREASE"]):
            return ActionCategory.ENTRY
        elif any(x in action_upper for x in ["CLOSE_LONG", "CLOSE_SHORT", "CLOSE"]):
            return ActionCategory.FULL_CLOSE
        else:
            return ActionCategory.OTHER
    
    def check_allowed(
        self,
        symbol: str,
        action_name: str,
        signal_ts_ms: int = 0
    ) -> Tuple[bool, Optional[BlockReason], str]:
        """
        Check if an action is allowed by anti-churn policy.
        
        Args:
            symbol: Trading symbol
            action_name: Action to execute
            signal_ts_ms: Original signal timestamp (for freshness check)
            
        Returns:
            (allowed, block_reason, detail_message)
        """
        from config import ENABLE_ANTI_CHURN_PROTECTIONS
        
        if not ENABLE_ANTI_CHURN_PROTECTIONS:
            return True, None, ""
        
        now = time.time()
        now_ms = int(now * 1000)
        
        # Categorize action early to check if it's protective
        category = self.categorize_action(action_name)
        
        # CRITICAL: Protective actions (FULL_CLOSE, DECREASE) should NEVER be blocked
        is_protective = category in {ActionCategory.FULL_CLOSE}
        is_reduce = any(x in action_name.upper() for x in ["DECREASE", "CLOSE_ALL", "STOP_LOSS", "TAKE_PROFIT"])
        
        if is_protective or is_reduce:
            logger.debug(f"[ANTI_CHURN] PROTECTIVE_BYPASS | {symbol} {action_name} | category={category.value}")
            self._total_allowed += 1
            return True, None, ""
        
        # Check warm start window (only for non-protective actions)
        if now - self.startup_ts < self.warm_start_window:
            detail = f"warm_start: {now - self.startup_ts:.0f}s < {self.warm_start_window}s"
            logger.info(f"[ANTI_CHURN] {BlockReason.WARM_START_BLOCK.value} | {symbol} | {detail}")
            self._total_blocked += 1
            return False, BlockReason.WARM_START_BLOCK, detail
        
        # Check signal freshness (if timestamp provided).
        # Uses TRADER_MAX_SIGNAL_AGE_MS from config (default 180s) instead of
        # hardcoded 60s so burst batches of 125 symbols are not all dropped.
        if signal_ts_ms > 0:
            signal_age_ms = now_ms - signal_ts_ms
            try:
                max_signal_age_ms = int(TRADER_MAX_SIGNAL_AGE_MS)
            except Exception:
                max_signal_age_ms = 180000
            if signal_age_ms > max_signal_age_ms:
                detail = f"signal_age={signal_age_ms}ms > max={max_signal_age_ms}ms"
                logger.info(f"[ANTI_CHURN] {BlockReason.SIGNAL_STALE_BLOCK.value} | {symbol} | {detail}")
                self._total_blocked += 1
                return False, BlockReason.SIGNAL_STALE_BLOCK, detail
        
        # Get or create action count for this symbol
        action_count = self._action_counts[symbol]
        
        # Reset if hour has passed
        if now - action_count.hour_start_ts >= 3600:
            action_count.hedge_count = 0
            action_count.partial_close_count = 0
            action_count.flip_count = 0
            action_count.hour_start_ts = now
        
        # Check limits based on category (already computed at top of function)
        if category == ActionCategory.HEDGE:
            if action_count.hedge_count >= self.max_hedge_per_hour:
                detail = f"hedge_count={action_count.hedge_count}/{self.max_hedge_per_hour}"
                logger.warning(f"[ANTI_CHURN] {BlockReason.SYMBOL_RATE_LIMIT_BLOCK.value} | {symbol} | {detail}")
                self._total_blocked += 1
                return False, BlockReason.SYMBOL_RATE_LIMIT_BLOCK, detail
            
            # Check hedge state cooldown
            last_hedge = self._last_hedge_action_ts.get(symbol, 0)
            if last_hedge > 0 and now - last_hedge < self.hedge_state_min_interval:
                detail = f"hedge_interval={now - last_hedge:.0f}s < {self.hedge_state_min_interval}s"
                logger.warning(f"[ANTI_CHURN] {BlockReason.HEDGE_STATE_COOLDOWN_BLOCK.value} | {symbol} | {detail}")
                self._total_blocked += 1
                return False, BlockReason.HEDGE_STATE_COOLDOWN_BLOCK, detail
        
        elif category == ActionCategory.PARTIAL_CLOSE:
            if action_count.partial_close_count >= self.max_partial_close_per_hour:
                detail = f"partial_count={action_count.partial_close_count}/{self.max_partial_close_per_hour}"
                logger.warning(f"[ANTI_CHURN] {BlockReason.SYMBOL_RATE_LIMIT_BLOCK.value} | {symbol} | {detail}")
                self._total_blocked += 1
                return False, BlockReason.SYMBOL_RATE_LIMIT_BLOCK, detail
        
        elif category == ActionCategory.FLIP:
            if action_count.flip_count >= self.max_flips_per_hour:
                detail = f"flip_count={action_count.flip_count}/{self.max_flips_per_hour}"
                logger.warning(f"[ANTI_CHURN] {BlockReason.SYMBOL_RATE_LIMIT_BLOCK.value} | {symbol} | {detail}")
                self._total_blocked += 1
                return False, BlockReason.SYMBOL_RATE_LIMIT_BLOCK, detail
        
        # Allowed
        self._total_allowed += 1
        return True, None, ""
    
    def record_execution(self, symbol: str, action_name: str):
        """
        Record an executed action for rate limiting.
        
        Args:
            symbol: Trading symbol
            action_name: Action that was executed
        """
        now = time.time()
        action_count = self._action_counts[symbol]
        
        # Reset if hour has passed
        if now - action_count.hour_start_ts >= 3600:
            action_count.hedge_count = 0
            action_count.partial_close_count = 0
            action_count.flip_count = 0
            action_count.hour_start_ts = now
        
        category = self.categorize_action(action_name)
        
        if category == ActionCategory.HEDGE:
            action_count.hedge_count += 1
            self._last_hedge_action_ts[symbol] = now
            logger.debug(f"[ANTI_CHURN] Recorded hedge execution: {symbol} | count={action_count.hedge_count}")
        
        elif category == ActionCategory.PARTIAL_CLOSE:
            action_count.partial_close_count += 1
            logger.debug(f"[ANTI_CHURN] Recorded partial close: {symbol} | count={action_count.partial_close_count}")
        
        elif category == ActionCategory.FLIP:
            action_count.flip_count += 1
            logger.debug(f"[ANTI_CHURN] Recorded flip: {symbol} | count={action_count.flip_count}")
    
    def get_symbol_limits(self, symbol: str) -> Dict:
        """Get current limits status for a symbol."""
        action_count = self._action_counts.get(symbol, ActionCount())
        return {
            'symbol': symbol,
            'hedge_count': action_count.hedge_count,
            'hedge_limit': self.max_hedge_per_hour,
            'partial_close_count': action_count.partial_close_count,
            'partial_close_limit': self.max_partial_close_per_hour,
            'flip_count': action_count.flip_count,
            'flip_limit': self.max_flips_per_hour,
            'last_hedge_ts': self._last_hedge_action_ts.get(symbol, 0),
            'hedge_cooldown_remaining': max(0, self.hedge_state_min_interval - (time.time() - self._last_hedge_action_ts.get(symbol, 0)))
        }
    
    def get_stats(self) -> Dict:
        """Get anti-churn statistics."""
        now = time.time()
        return {
            'total_blocked': self._total_blocked,
            'total_allowed': self._total_allowed,
            'block_rate': self._total_blocked / max(1, self._total_blocked + self._total_allowed),
            'warm_start_elapsed': now - self.startup_ts,
            'warm_start_active': now - self.startup_ts < self.warm_start_window,
            'symbols_tracked': len(self._action_counts),
        }
    
    def log_status(self):
        """Log current anti-churn status."""
        stats = self.get_stats()
        logger.info(
            f"ANTI_CHURN_STATUS | "
            f"blocked={stats['total_blocked']} | allowed={stats['total_allowed']} | "
            f"block_rate={stats['block_rate']*100:.1f}% | "
            f"warm_start={'ACTIVE' if stats['warm_start_active'] else 'INACTIVE'} | "
            f"symbols={stats['symbols_tracked']}"
        )


# Global singleton
_anti_churn_manager: Optional[AntiChurnManager] = None


def get_anti_churn_manager() -> AntiChurnManager:
    """Get or create the global AntiChurnManager instance."""
    global _anti_churn_manager
    
    if _anti_churn_manager is None:
        _anti_churn_manager = AntiChurnManager()
    
    return _anti_churn_manager


def check_anti_churn(
    symbol: str,
    action_name: str,
    signal_ts_ms: int = 0
) -> Tuple[bool, Optional[str], str]:
    """
    Convenience function to check anti-churn policy.
    
    Returns:
        (allowed, block_reason_str, detail)
    """
    manager = get_anti_churn_manager()
    allowed, reason, detail = manager.check_allowed(symbol, action_name, signal_ts_ms)
    reason_str = reason.value if reason else None
    return allowed, reason_str, detail


def record_execution(symbol: str, action_name: str):
    """Record an executed action for anti-churn tracking."""
    manager = get_anti_churn_manager()
    manager.record_execution(symbol, action_name)

