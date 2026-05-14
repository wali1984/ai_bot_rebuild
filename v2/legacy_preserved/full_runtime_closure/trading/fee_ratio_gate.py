"""
Real-time Fee Ratio Gate using Binance API data
================================================
This module provides actual fee/profit ratio from Binance income history,
replacing the broken internal metric tracking which never gets populated.

INTEGRATION WITH ACTION CATEGORIES:
- Uses config.ACTION_CATEGORIES for allow/block decisions
- OPEN_RISK: Blocked when fee ratio > threshold
- HEDGE: Allowed (risk-reducing, needs protection capability)
- PROTECTIVE: Always allowed (exits must never be blocked)

Usage:
    from trading.fee_ratio_gate import should_block_for_fee_ratio, FeeRatioGate
    
    # Simple check
    blocked, reason, ratio = should_block_for_fee_ratio(symbol, action_type, action_category)
    if blocked:
        logger.warning(f"FEE_RATIO_BLOCK: {reason}")
        return None
    
    # Or use the gate class for more control
    gate = FeeRatioGate()
    if gate.should_block(action_name, action_category):
        ...
"""

import os
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Tuple, Optional, Dict, Set
from dataclasses import dataclass

logger = logging.getLogger("fee_ratio_gate")

# =============================================================================
# ACTION CATEGORY DEFINITIONS (Mirror from config.py for standalone use)
# =============================================================================
# These are used when config module is not available or for validation

# Actions that CREATE new exposure - BLOCKED when fee ratio exceeded
BLOCKED_CATEGORIES: Set[str] = {"OPEN_RISK"}

# Actions that are ALLOWED even when fee ratio exceeded
ALLOWED_CATEGORIES: Set[str] = {"HEDGE", "PROTECTIVE"}

# Action type mappings (action_type string → should block)
BLOCKED_ACTION_TYPES: Set[str] = {"open", "flip", "increase"}
ALLOWED_ACTION_TYPES: Set[str] = {"close", "decrease", "hold", "reduce", "exit", "protective"}

# Cache to avoid hitting Binance API too frequently
_fee_cache = {
    'last_fetch_ts': 0,
    'data': None,
    'lock': threading.Lock()
}

# Cache TTL - refresh every 5 minutes
CACHE_TTL_SECONDS = 300


@dataclass
class FeeRatioData:
    """Fee ratio metrics from Binance"""
    total_fees: float
    total_realized_pnl: float
    trade_count: int
    fee_ratio: float  # fees / abs(realized_pnl)
    net_pnl: float    # realized_pnl - fees
    fetch_time: float


def _fetch_binance_fee_ratio(hours: int = 24) -> Optional[FeeRatioData]:
    """
    Fetch actual fee and profit data from Binance Futures API.
    Uses income history which includes REALIZED_PNL and COMMISSION entries.
    """
    try:
        from binance.client import Client
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        
        if not api_key or not api_secret:
            logger.warning("[FEE_RATIO] No Binance API credentials configured")
            return None
        
        client = Client(api_key, api_secret)
        
        # Get income history for last N hours
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        
        income = client.futures_income_history(
            startTime=start_time, 
            endTime=end_time, 
            limit=1000
        )
        
        total_fees = 0.0
        total_realized = 0.0
        trade_count = 0
        
        for entry in income:
            income_type = entry['incomeType']
            amount = float(entry['income'])
            
            if income_type == 'COMMISSION':
                total_fees += abs(amount)
            elif income_type == 'REALIZED_PNL':
                total_realized += amount
                trade_count += 1
        
        # Calculate fee ratio
        if abs(total_realized) > 0:
            fee_ratio = total_fees / abs(total_realized)
        else:
            fee_ratio = float('inf') if total_fees > 0 else 0.0
        
        net_pnl = total_realized - total_fees
        
        return FeeRatioData(
            total_fees=total_fees,
            total_realized_pnl=total_realized,
            trade_count=trade_count,
            fee_ratio=fee_ratio,
            net_pnl=net_pnl,
            fetch_time=time.time()
        )
        
    except Exception as e:
        logger.error(f"[FEE_RATIO] Failed to fetch from Binance: {e}")
        return None


def get_fee_ratio_data(force_refresh: bool = False) -> Optional[FeeRatioData]:
    """
    Get cached fee ratio data, refreshing if stale.
    Thread-safe with lock protection.
    """
    global _fee_cache
    
    with _fee_cache['lock']:
        now = time.time()
        
        # Check if cache is valid
        if not force_refresh and _fee_cache['data'] is not None:
            age = now - _fee_cache['last_fetch_ts']
            if age < CACHE_TTL_SECONDS:
                return _fee_cache['data']
        
        # Fetch fresh data
        data = _fetch_binance_fee_ratio(hours=24)
        if data:
            _fee_cache['data'] = data
            _fee_cache['last_fetch_ts'] = now
        
        return _fee_cache['data']


def should_block_for_fee_ratio(
    symbol: str,
    action_type: str,
    action_category: Optional[str] = None,
    action_name: Optional[str] = None,
    max_ratio: float = 0.40,
    min_trades: int = 20
) -> Tuple[bool, str, float]:
    """
    Check if signal should be blocked due to excessive fee ratio.
    
    Args:
        symbol: Trading symbol
        action_type: Type of action (open, flip, increase, close, etc)
        action_category: Category from config (OPEN_RISK, HEDGE, PROTECTIVE) - takes precedence
        action_name: Full action name for fallback category lookup
        max_ratio: Maximum allowed fee/profit ratio (default 40%)
        min_trades: Minimum trades required before enforcement (default 20)
    
    Returns:
        Tuple of (should_block, reason_string, fee_ratio)
    
    BLOCKING LOGIC:
        1. PROTECTIVE category → NEVER blocked (exits must always work)
        2. HEDGE category → NEVER blocked (risk-reducing, need protection capability)
        3. OPEN_RISK category → Blocked if fee_ratio > max_ratio
        4. If no category, fall back to action_type check
    """
    # Normalize inputs
    action_category = (action_category or "").upper()
    action_type = (action_type or "").lower()
    action_name = (action_name or "").upper()
    
    # 1. PROTECTIVE actions - NEVER BLOCK (exits must always work)
    if action_category == "PROTECTIVE":
        return False, "PROTECTIVE_CATEGORY_EXEMPT", 0.0
    
    # Also check action_name for protective patterns (redundant safety)
    protective_patterns = ["CLOSE", "DECREASE", "STOP_LOSS", "TAKE_PROFIT", "PARTIAL", "EXIT", "REDUCE"]
    if any(p in action_name for p in protective_patterns) and "OPEN" not in action_name and "FLIP" not in action_name:
        return False, "PROTECTIVE_ACTION_EXEMPT", 0.0
    
    # 2. HEDGE actions - NEVER BLOCK (risk-reducing, need hedging capability in adversity)
    if action_category == "HEDGE":
        return False, "HEDGE_CATEGORY_EXEMPT", 0.0
    
    if "HEDGE" in action_name:
        return False, "HEDGE_ACTION_EXEMPT", 0.0
    
    # 3. Check if this is an OPEN_RISK action (category or action_type)
    is_open_risk = (
        action_category == "OPEN_RISK" or 
        action_type in BLOCKED_ACTION_TYPES or
        any(p in action_name for p in ["OPEN_LONG", "OPEN_SHORT", "INCREASE", "FLIP"])
    )
    
    # Non-risk actions that aren't PROTECTIVE/HEDGE - allow through
    if not is_open_risk:
        return False, "NON_RISK_ACTION_EXEMPT", 0.0
    
    # 4. This is an OPEN_RISK action - check fee ratio
    data = get_fee_ratio_data()
    
    if data is None:
        # Fail-open: If we can't get data, don't block
        return False, "NO_FEE_DATA_AVAILABLE", 0.0
    
    # Need minimum history before enforcing
    if data.trade_count < min_trades:
        return False, f"INSUFFICIENT_HISTORY ({data.trade_count}/{min_trades})", data.fee_ratio
    
    # Check if fee ratio exceeds threshold
    if data.fee_ratio > max_ratio:
        reason = (
            f"EXCESSIVE_FEE_RATIO: {data.fee_ratio:.1%} > {max_ratio:.0%} | "
            f"fees=${data.total_fees:.2f} / pnl=${data.total_realized_pnl:.2f} | "
            f"net=${data.net_pnl:.2f} | trades={data.trade_count} | "
            f"category={action_category or action_type}"
        )
        return True, reason, data.fee_ratio
    
    # Within limits
    return False, f"FEE_RATIO_OK: {data.fee_ratio:.1%} <= {max_ratio:.0%}", data.fee_ratio


class FeeRatioGate:
    """
    Object-oriented fee ratio gate for more sophisticated integration.
    Can be instantiated once and reused, or used as singleton.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self, max_ratio: float = 0.40, min_trades: int = 20):
        self.max_ratio = max_ratio
        self.min_trades = min_trades
        self._last_log_ts = 0
        self._log_interval = 300  # Log summary every 5 min
        
    @classmethod
    def get_instance(cls, max_ratio: float = 0.40, min_trades: int = 20) -> 'FeeRatioGate':
        """Get singleton instance (thread-safe)"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(max_ratio, min_trades)
        return cls._instance
    
    def get_action_category(self, action_name: str) -> str:
        """
        Get action category, preferring config.get_action_category if available.
        Falls back to internal classification.
        """
        try:
            from config import get_action_category
            return get_action_category(action_name)
        except ImportError:
            pass
        
        # Internal fallback classification
        action_upper = (action_name or "").upper()
        
        # PROTECTIVE: Pure exits
        if any(p in action_upper for p in ["CLOSE", "DECREASE", "STOP_LOSS", "TAKE_PROFIT", "PARTIAL"]):
            if "OPEN" not in action_upper and "FLIP" not in action_upper:
                return "PROTECTIVE"
        
        # HEDGE
        if "HEDGE" in action_upper:
            return "HEDGE"
        
        # OPEN_RISK: New exposure
        if any(p in action_upper for p in ["OPEN", "INCREASE", "FLIP", "ADD"]):
            return "OPEN_RISK"
        
        # Default to PROTECTIVE (safe)
        return "PROTECTIVE"
    
    def should_block(
        self, 
        action_name: str, 
        action_category: Optional[str] = None,
        action_type: Optional[str] = None,
        symbol: str = "UNKNOWN"
    ) -> Tuple[bool, str, float]:
        """
        Check if action should be blocked.
        
        Args:
            action_name: Full action name (e.g., "OPEN_LONG", "CLOSE_SHORT")
            action_category: Pre-computed category (OPEN_RISK, HEDGE, PROTECTIVE)
            action_type: Action type string (open, close, flip, etc)
            symbol: Symbol for logging
            
        Returns:
            Tuple of (should_block, reason, fee_ratio)
        """
        # Resolve category
        if not action_category:
            action_category = self.get_action_category(action_name)
        
        # Resolve action_type from action_name if not provided
        if not action_type:
            action_upper = (action_name or "").upper()
            if "OPEN" in action_upper and "CLOSE" not in action_upper:
                action_type = "open"
            elif "FLIP" in action_upper or ("CLOSE" in action_upper and "OPEN" in action_upper):
                action_type = "flip"
            elif "INCREASE" in action_upper:
                action_type = "increase"
            elif "CLOSE" in action_upper or "DECREASE" in action_upper:
                action_type = "close"
            else:
                action_type = "unknown"
        
        blocked, reason, ratio = should_block_for_fee_ratio(
            symbol=symbol,
            action_type=action_type,
            action_category=action_category,
            action_name=action_name,
            max_ratio=self.max_ratio,
            min_trades=self.min_trades
        )
        
        # Periodic logging
        now = time.time()
        if now - self._last_log_ts > self._log_interval:
            logger.info(get_fee_summary())
            self._last_log_ts = now
        
        return blocked, reason, ratio
    
    def is_gate_active(self) -> bool:
        """Check if gate is currently blocking (fee ratio > threshold)"""
        data = get_fee_ratio_data()
        if data is None:
            return False
        if data.trade_count < self.min_trades:
            return False
        return data.fee_ratio > self.max_ratio
    
    def get_current_ratio(self) -> float:
        """Get current fee ratio"""
        data = get_fee_ratio_data()
        return data.fee_ratio if data else 0.0
    
    def get_status(self) -> Dict:
        """Get full status for monitoring/dashboards"""
        data = get_fee_ratio_data()
        if data is None:
            return {
                'available': False,
                'ratio': 0.0,
                'threshold': self.max_ratio,
                'gate_active': False,
                'error': 'No data available'
            }
        
        return {
            'available': True,
            'ratio': data.fee_ratio,
            'threshold': self.max_ratio,
            'gate_active': data.fee_ratio > self.max_ratio and data.trade_count >= self.min_trades,
            'total_fees': data.total_fees,
            'total_realized_pnl': data.total_realized_pnl,
            'net_pnl': data.net_pnl,
            'trade_count': data.trade_count,
            'min_trades_required': self.min_trades,
            'fetch_time': data.fetch_time
        }


def get_fee_summary() -> str:
    """Get human-readable fee summary for logging"""
    data = get_fee_ratio_data()
    if data is None:
        return "[FEE] No data available"
    
    status = "🚨 CRITICAL" if data.fee_ratio > 1.0 else ("⚠️ HIGH" if data.fee_ratio > 0.5 else "✅ OK")
    return (
        f"[FEE_SUMMARY] {status} | "
        f"Ratio: {data.fee_ratio:.1%} | "
        f"Fees: ${data.total_fees:.2f} | "
        f"PnL: ${data.total_realized_pnl:.2f} | "
        f"Net: ${data.net_pnl:.2f} | "
        f"Trades: {data.trade_count} (24h)"
    )
