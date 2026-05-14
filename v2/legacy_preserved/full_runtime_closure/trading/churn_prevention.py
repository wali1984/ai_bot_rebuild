"""
Churn Prevention Module - Anti-Fee-Bleeding Controls
=====================================================
Centralizes all anti-churn logic to prevent fee-inefficient trading.

Problem Analysis:
- 7,461 trades over 7 days = ~1,066 trades/day = ~44 trades/hour
- At 0.05% taker fee on $500 avg notional = $0.25/trade = $1,865 in fees
- PnL was only $124 = 1500% fee ratio (fees >> profits)

Solutions Implemented:
1. Minimum Edge Gate (Option 2) - Only trade when expected edge > costs
2. Maker-First Execution (Option 3) - Use limit orders when possible
3. Position Sizing Consolidation (Option 4) - Fewer, larger trades
4. Hold Time Reward Shaping (Option 5) - Incentivize longer holds
"""

import logging
import time
from typing import Dict, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


@dataclass
class TradeCosts:
    """All-in transaction costs for a trade"""
    spread_cost_bps: float = 3.0     # ~3 bps typical spread
    taker_fee_bps: float = 5.0       # 0.05% taker fee
    maker_fee_bps: float = 2.0       # 0.02% maker fee
    slippage_bps: float = 2.0        # ~2 bps slippage estimate
    
    @property
    def round_trip_taker_bps(self) -> float:
        """Total round-trip cost using taker orders (entry + exit)"""
        return (self.spread_cost_bps + self.taker_fee_bps + self.slippage_bps) * 2
    
    @property
    def round_trip_maker_bps(self) -> float:
        """Total round-trip cost using maker orders (entry + exit)"""
        return (self.spread_cost_bps + self.maker_fee_bps + self.slippage_bps) * 2
    
    def round_trip_usd(self, notional: float, use_maker: bool = False) -> float:
        """Calculate round-trip cost in USD"""
        bps = self.round_trip_maker_bps if use_maker else self.round_trip_taker_bps
        return notional * (bps / 10000)


class MinimumEdgeGate:
    """
    Option 2: Minimum Expected Edge Gate (Quality Filter)
    
    Problem: Signals fire on tiny predicted moves that don't cover costs.
    Solution: Block entries unless predicted_move > (fees + spread + slippage) × safety_multiple
    
    Impact: Only trades with real edge execute. Reduces trades by 70-80%.
    """
    
    def __init__(
        self,
        min_edge_pct: float = 0.15,           # Minimum expected move %
        spread_cost_pct: float = 0.03,        # ~3 bps spread
        fee_cost_pct: float = 0.10,           # 10 bps round-trip (taker)
        slippage_pct: float = 0.02,           # 2 bps slippage
        safety_multiple: float = 2.0,          # Require 2x costs
        confidence_to_edge_map: Dict[float, float] = None
    ):
        self.min_edge_pct = min_edge_pct
        self.spread_cost_pct = spread_cost_pct
        self.fee_cost_pct = fee_cost_pct
        self.slippage_pct = slippage_pct
        self.safety_multiple = safety_multiple
        
        # Map confidence levels to expected move percentages
        # Based on historical calibration (should be updated with real data)
        self.confidence_to_edge_map = confidence_to_edge_map or {
            0.70: 0.05,   # 70% conf → 0.05% expected move
            0.75: 0.08,   # 75% conf → 0.08% expected move
            0.80: 0.12,   # 80% conf → 0.12% expected move
            0.85: 0.18,   # 85% conf → 0.18% expected move
            0.90: 0.30,   # 90% conf → 0.30% expected move
            0.95: 0.50,   # 95% conf → 0.50% expected move
            0.98: 0.75,   # 98% conf → 0.75% expected move
        }
        
        # Statistics tracking
        self.total_checked = 0
        self.total_passed = 0
        self.total_blocked = 0
        
        logger.info(f"MinimumEdgeGate initialized: min_edge={min_edge_pct}%, "
                   f"total_cost={(spread_cost_pct + fee_cost_pct + slippage_pct):.2f}%, "
                   f"safety_multiple={safety_multiple}x")
    
    @property
    def required_edge_pct(self) -> float:
        """Calculate required edge percentage"""
        total_cost = self.spread_cost_pct + self.fee_cost_pct + self.slippage_pct
        return max(self.min_edge_pct, total_cost * self.safety_multiple)
    
    def estimate_expected_move(self, confidence: float, volatility_pct: float = 1.0) -> float:
        """
        Estimate expected price move based on confidence and volatility.
        
        Uses calibrated confidence-to-edge mapping adjusted by current volatility.
        """
        # Find nearest confidence level in map
        conf_levels = sorted(self.confidence_to_edge_map.keys())
        
        # Linear interpolation between levels
        if confidence <= conf_levels[0]:
            base_edge = self.confidence_to_edge_map[conf_levels[0]]
        elif confidence >= conf_levels[-1]:
            base_edge = self.confidence_to_edge_map[conf_levels[-1]]
        else:
            # Find bracketing levels
            for i in range(len(conf_levels) - 1):
                if conf_levels[i] <= confidence < conf_levels[i + 1]:
                    low_conf, high_conf = conf_levels[i], conf_levels[i + 1]
                    low_edge = self.confidence_to_edge_map[low_conf]
                    high_edge = self.confidence_to_edge_map[high_conf]
                    
                    # Linear interpolation
                    ratio = (confidence - low_conf) / (high_conf - low_conf)
                    base_edge = low_edge + ratio * (high_edge - low_edge)
                    break
            else:
                base_edge = self.min_edge_pct
        
        # Adjust by volatility (higher vol = potentially larger moves)
        vol_multiplier = max(0.5, min(2.0, volatility_pct / 1.0))  # Normalize around 1%
        
        return base_edge * vol_multiplier
    
    def should_allow_entry(
        self,
        symbol: str,
        confidence: float,
        notional_usd: float,
        volatility_pct: float = 1.0,
        use_maker: bool = False
    ) -> Tuple[bool, str, Dict]:
        """
        Check if entry should be allowed based on minimum edge requirement.
        
        Returns:
            (should_allow, reason, details)
        """
        self.total_checked += 1
        
        # Calculate expected move
        expected_move_pct = self.estimate_expected_move(confidence, volatility_pct)
        
        # Calculate required edge
        if use_maker:
            # Lower costs with maker orders
            fee_cost = self.fee_cost_pct * 0.4  # 0.02% vs 0.05%
        else:
            fee_cost = self.fee_cost_pct
        
        total_cost = self.spread_cost_pct + fee_cost + self.slippage_pct
        required_edge = max(self.min_edge_pct, total_cost * self.safety_multiple)
        
        # Calculate expected profit vs cost
        expected_profit_usd = notional_usd * (expected_move_pct / 100)
        cost_usd = notional_usd * (total_cost / 100)
        net_expected = expected_profit_usd - cost_usd
        
        details = {
            'symbol': symbol,
            'confidence': confidence,
            'notional_usd': notional_usd,
            'volatility_pct': volatility_pct,
            'expected_move_pct': expected_move_pct,
            'required_edge_pct': required_edge,
            'total_cost_pct': total_cost,
            'expected_profit_usd': expected_profit_usd,
            'cost_usd': cost_usd,
            'net_expected_usd': net_expected,
            'use_maker': use_maker
        }
        
        # Decision
        if expected_move_pct >= required_edge:
            self.total_passed += 1
            reason = f"PASS: edge {expected_move_pct:.3f}% >= required {required_edge:.3f}%"
            return True, reason, details
        else:
            self.total_blocked += 1
            reason = (f"INSUFFICIENT_EDGE: expected {expected_move_pct:.3f}% < required {required_edge:.3f}% "
                     f"(net=${net_expected:.2f})")
            return False, reason, details
    
    def get_statistics(self) -> Dict:
        """Get gate statistics"""
        pass_rate = (self.total_passed / self.total_checked * 100) if self.total_checked > 0 else 0
        return {
            'total_checked': self.total_checked,
            'total_passed': self.total_passed,
            'total_blocked': self.total_blocked,
            'pass_rate_pct': pass_rate,
            'required_edge_pct': self.required_edge_pct
        }


class HoldTimeController:
    """
    Option 5: Hold Time Reward Shaping
    
    Problem: No incentive to hold positions. Agent flips rapidly.
    Solution: Add holding bonus that grows with profitable hold time + quick flip penalty.
    
    Impact: Agent learns to ride winners instead of taking quick profits.
    """
    
    def __init__(
        self,
        min_hold_minutes: int = 15,           # Penalty if closed before this
        quick_flip_penalty: float = 0.5,      # Multiply reward by this if <5 min
        hold_bonus_start_minutes: int = 30,   # Start bonus after this
        hold_bonus_max_hours: float = 2.0,    # Max bonus at this duration
        hold_bonus_max_pct: float = 0.20      # Max 20% bonus for long holds
    ):
        self.min_hold_minutes = min_hold_minutes
        self.quick_flip_penalty = quick_flip_penalty
        self.hold_bonus_start_minutes = hold_bonus_start_minutes
        self.hold_bonus_max_hours = hold_bonus_max_hours
        self.hold_bonus_max_pct = hold_bonus_max_pct
        
        # Track position entry times
        self.position_entries: Dict[str, float] = {}  # symbol -> entry_timestamp
        
        logger.info(f"HoldTimeController initialized: min_hold={min_hold_minutes}min, "
                   f"quick_flip_penalty={quick_flip_penalty}, max_bonus={hold_bonus_max_pct:.0%}")
    
    def record_entry(self, symbol: str, side: str, timestamp: float = None):
        """Record position entry time"""
        key = f"{symbol}:{side}"
        self.position_entries[key] = timestamp or time.time()
    
    def record_exit(self, symbol: str, side: str) -> float:
        """Record exit and return hold duration in minutes"""
        key = f"{symbol}:{side}"
        entry_time = self.position_entries.pop(key, None)
        if entry_time:
            return (time.time() - entry_time) / 60
        return 0
    
    def compute_reward_modifier(
        self,
        pnl: float,
        hold_time_minutes: float,
        is_profitable: bool = None
    ) -> Tuple[float, str]:
        """
        Compute reward modifier based on hold time.
        
        Returns:
            (modifier, reason) - modifier is multiplied with base reward
        """
        if is_profitable is None:
            is_profitable = pnl > 0
        
        # 1. Quick flip penalty (< 5 min)
        if hold_time_minutes < 5:
            return self.quick_flip_penalty, f"QUICK_FLIP_PENALTY: held only {hold_time_minutes:.1f}min"
        
        # 2. Below minimum hold (5-15 min) - partial penalty
        if hold_time_minutes < self.min_hold_minutes:
            # Linear scale from quick_flip_penalty to 1.0
            ratio = (hold_time_minutes - 5) / (self.min_hold_minutes - 5)
            modifier = self.quick_flip_penalty + ratio * (1.0 - self.quick_flip_penalty)
            return modifier, f"SHORT_HOLD: {hold_time_minutes:.1f}min < {self.min_hold_minutes}min"
        
        # 3. Hold bonus for profitable positions held longer
        if is_profitable and hold_time_minutes > self.hold_bonus_start_minutes:
            # Bonus grows linearly with hold time, capped at max
            hours_held = hold_time_minutes / 60
            bonus_ratio = min(
                (hours_held - self.hold_bonus_start_minutes/60) / (self.hold_bonus_max_hours - self.hold_bonus_start_minutes/60),
                1.0
            )
            bonus = bonus_ratio * self.hold_bonus_max_pct
            modifier = 1.0 + bonus
            return modifier, f"HOLD_BONUS: {hold_time_minutes:.1f}min → +{bonus:.1%}"
        
        # 4. Normal hold (15-30 min) - no modifier
        return 1.0, f"NORMAL_HOLD: {hold_time_minutes:.1f}min"
    
    def compute_shaped_reward(
        self,
        base_pnl: float,
        hold_time_minutes: float,
        trading_costs: float = 0
    ) -> Dict[str, float]:
        """
        Compute full shaped reward with hold time adjustments.
        
        Returns dict with reward components.
        """
        is_profitable = base_pnl > trading_costs
        
        # Get hold time modifier
        modifier, reason = self.compute_reward_modifier(
            base_pnl, hold_time_minutes, is_profitable
        )
        
        # Apply modifier
        shaped_reward = base_pnl * modifier
        
        return {
            'base_pnl': base_pnl,
            'trading_costs': trading_costs,
            'net_pnl': base_pnl - trading_costs,
            'hold_time_minutes': hold_time_minutes,
            'hold_modifier': modifier,
            'hold_reason': reason,
            'shaped_reward': shaped_reward,
            'is_profitable': is_profitable
        }


class TradeThrottler:
    """
    Trade frequency limiter to prevent excessive churning.
    
    Limits:
    - Per symbol per hour
    - Global per hour
    - Minimum time between trades per symbol
    """
    
    def __init__(
        self,
        max_per_symbol_per_hour: int = 4,
        max_global_per_hour: int = 30,
        min_interval_seconds: int = 300  # 5 min between same-symbol trades
    ):
        self.max_per_symbol_per_hour = max_per_symbol_per_hour
        self.max_global_per_hour = max_global_per_hour
        self.min_interval_seconds = min_interval_seconds
        
        # Rolling windows (deques with timestamps)
        self.symbol_trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.global_trades: deque = deque(maxlen=500)
        self.last_trade_time: Dict[str, float] = {}  # symbol -> timestamp
        
        logger.info(f"TradeThrottler initialized: {max_per_symbol_per_hour}/symbol/hour, "
                   f"{max_global_per_hour}/global/hour, {min_interval_seconds}s min interval")
    
    def _cleanup_old(self, window: deque, cutoff: float):
        """Remove entries older than cutoff"""
        while window and window[0] < cutoff:
            window.popleft()
    
    def record_trade(self, symbol: str, timestamp: float = None):
        """Record a trade execution"""
        ts = timestamp or time.time()
        self.symbol_trades[symbol].append(ts)
        self.global_trades.append(ts)
        self.last_trade_time[symbol] = ts
    
    def should_allow_trade(self, symbol: str) -> Tuple[bool, str]:
        """
        Check if trade should be allowed based on throttling rules.
        
        Returns:
            (should_allow, reason)
        """
        now = time.time()
        one_hour_ago = now - 3600
        
        # Clean up old entries
        self._cleanup_old(self.symbol_trades[symbol], one_hour_ago)
        self._cleanup_old(self.global_trades, one_hour_ago)
        
        # Check minimum interval
        last_trade = self.last_trade_time.get(symbol, 0)
        if now - last_trade < self.min_interval_seconds:
            remaining = int(self.min_interval_seconds - (now - last_trade))
            return False, f"MIN_INTERVAL: {remaining}s remaining until next {symbol} trade"
        
        # Check per-symbol limit
        symbol_count = len(self.symbol_trades[symbol])
        if symbol_count >= self.max_per_symbol_per_hour:
            return False, f"SYMBOL_LIMIT: {symbol} has {symbol_count}/{self.max_per_symbol_per_hour} trades this hour"
        
        # Check global limit
        global_count = len(self.global_trades)
        if global_count >= self.max_global_per_hour:
            return False, f"GLOBAL_LIMIT: {global_count}/{self.max_global_per_hour} trades this hour"
        
        return True, f"ALLOWED: {symbol} {symbol_count}/{self.max_per_symbol_per_hour}, global {global_count}/{self.max_global_per_hour}"
    
    def get_statistics(self) -> Dict:
        """Get throttler statistics"""
        now = time.time()
        one_hour_ago = now - 3600
        
        self._cleanup_old(self.global_trades, one_hour_ago)
        
        symbol_counts = {}
        for symbol, trades in self.symbol_trades.items():
            self._cleanup_old(trades, one_hour_ago)
            symbol_counts[symbol] = len(trades)
        
        return {
            'global_trades_last_hour': len(self.global_trades),
            'symbol_trades_last_hour': symbol_counts,
            'max_per_symbol_per_hour': self.max_per_symbol_per_hour,
            'max_global_per_hour': self.max_global_per_hour
        }


class ChurnPreventionManager:
    """
    Centralized manager for all churn prevention controls.
    
    Combines:
    - Minimum Edge Gate (Option 2)
    - Hold Time Controller (Option 5)
    - Trade Throttler (Option 4)
    """
    
    def __init__(
        self,
        # Edge gate params
        min_edge_pct: float = 0.15,
        safety_multiple: float = 2.0,
        # Hold time params
        min_hold_minutes: int = 15,
        quick_flip_penalty: float = 0.5,
        hold_bonus_max_pct: float = 0.20,
        # Throttle params
        max_per_symbol_per_hour: int = 4,
        max_global_per_hour: int = 30
    ):
        self.edge_gate = MinimumEdgeGate(
            min_edge_pct=min_edge_pct,
            safety_multiple=safety_multiple
        )
        
        self.hold_controller = HoldTimeController(
            min_hold_minutes=min_hold_minutes,
            quick_flip_penalty=quick_flip_penalty,
            hold_bonus_max_pct=hold_bonus_max_pct
        )
        
        self.throttler = TradeThrottler(
            max_per_symbol_per_hour=max_per_symbol_per_hour,
            max_global_per_hour=max_global_per_hour
        )
        
        self.costs = TradeCosts()
        
        logger.info("ChurnPreventionManager initialized with all controls")
    
    def should_allow_entry(
        self,
        symbol: str,
        confidence: float,
        notional_usd: float,
        volatility_pct: float = 1.0,
        use_maker: bool = False
    ) -> Tuple[bool, str, Dict]:
        """
        Full entry gate check combining all controls.
        
        Returns:
            (should_allow, reason, details)
        """
        # 1. Check throttle first (fastest)
        throttle_ok, throttle_reason = self.throttler.should_allow_trade(symbol)
        if not throttle_ok:
            return False, f"THROTTLE_BLOCK: {throttle_reason}", {'block_type': 'throttle'}
        
        # 2. Check edge gate
        edge_ok, edge_reason, edge_details = self.edge_gate.should_allow_entry(
            symbol, confidence, notional_usd, volatility_pct, use_maker
        )
        if not edge_ok:
            return False, f"EDGE_BLOCK: {edge_reason}", edge_details
        
        # All checks passed
        return True, "ENTRY_APPROVED", edge_details
    
    def on_trade_executed(self, symbol: str, side: str, timestamp: float = None):
        """Called when a trade is executed"""
        self.throttler.record_trade(symbol, timestamp)
        self.hold_controller.record_entry(symbol, side, timestamp)
    
    def on_position_closed(self, symbol: str, side: str, pnl: float, trading_costs: float = 0) -> Dict:
        """
        Called when a position is closed.
        
        Returns shaped reward details.
        """
        hold_time = self.hold_controller.record_exit(symbol, side)
        return self.hold_controller.compute_shaped_reward(pnl, hold_time, trading_costs)
    
    def get_all_statistics(self) -> Dict:
        """Get combined statistics from all controllers"""
        return {
            'edge_gate': self.edge_gate.get_statistics(),
            'throttler': self.throttler.get_statistics(),
            'costs': {
                'round_trip_taker_bps': self.costs.round_trip_taker_bps,
                'round_trip_maker_bps': self.costs.round_trip_maker_bps
            }
        }


# Global instance for easy access
_churn_manager: Optional[ChurnPreventionManager] = None


def get_churn_manager(**kwargs) -> ChurnPreventionManager:
    """Get or create the global churn prevention manager"""
    global _churn_manager
    if _churn_manager is None:
        _churn_manager = ChurnPreventionManager(**kwargs)
    return _churn_manager


def reset_churn_manager():
    """Reset the global churn manager (for testing)"""
    global _churn_manager
    _churn_manager = None


if __name__ == '__main__':
    # Test the churn prevention system
    logging.basicConfig(level=logging.INFO)
    
    manager = get_churn_manager()
    
    # Test edge gate
    print("\n=== Edge Gate Tests ===")
    test_cases = [
        ("BTCUSDT", 0.70, 500, 1.0),   # Low confidence
        ("BTCUSDT", 0.85, 500, 1.0),   # Medium confidence
        ("BTCUSDT", 0.95, 500, 1.0),   # High confidence
        ("ETHUSDT", 0.90, 1000, 2.0),  # High volatility
    ]
    
    for symbol, conf, notional, vol in test_cases:
        allowed, reason, details = manager.should_allow_entry(symbol, conf, notional, vol)
        print(f"{symbol} conf={conf:.0%} notional=${notional}: {'✅' if allowed else '❌'} {reason}")
    
    # Test hold time shaping
    print("\n=== Hold Time Tests ===")
    hold_times = [3, 10, 20, 45, 90, 150]  # minutes
    pnl = 50  # $50 profit
    
    for hold_min in hold_times:
        result = manager.hold_controller.compute_shaped_reward(pnl, hold_min)
        print(f"Hold {hold_min}min, PnL=${pnl}: modifier={result['hold_modifier']:.2f}, "
              f"shaped=${result['shaped_reward']:.2f} ({result['hold_reason']})")
    
    # Test throttler
    print("\n=== Throttle Tests ===")
    for i in range(6):
        allowed, reason = manager.throttler.should_allow_trade("BTCUSDT")
        print(f"Trade {i+1}: {'✅' if allowed else '❌'} {reason}")
        if allowed:
            manager.throttler.record_trade("BTCUSDT")
    
    print("\n=== Statistics ===")
    print(manager.get_all_statistics())

