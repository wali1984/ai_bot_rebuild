"""
Minimum Hold Time Enforcement System
Prevents position thrashing by enforcing hold time requirements
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum
import json

logger = logging.getLogger(__name__)


class HoldTimeViolationType(Enum):
    """Types of hold time violations"""
    POSITION_TOO_NEW = "position_too_new"
    FLIP_TOO_SOON = "flip_too_soon" 
    CLOSE_TOO_SOON = "close_too_soon"
    EMERGENCY_OVERRIDE = "emergency_override"


@dataclass
class PositionTiming:
    """Timing information for position management"""
    symbol: str
    side: str  # "LONG", "SHORT"
    entry_time: float
    last_modify_time: float
    quantity: float
    avg_price: float
    hold_time_minutes: float
    can_modify_after: float  # timestamp when modifications are allowed
    can_close_after: float   # timestamp when closing is allowed
    emergency_close_allowed: bool = False
    emergency_reason: Optional[str] = None


class MinimumHoldTimeEnforcer:
    """
    Enforces minimum hold times to prevent position thrashing.
    
    Key Features:
    - 15-30 minute minimum hold times per position
    - Emergency CLOSE_ALL override for critical situations
    - Per-symbol tracking of position timing
    - Side-flip prevention (LONG->SHORT too quickly)
    - Graduated penalties for violations
    """
    
    def __init__(
        self,
        min_hold_minutes: int = 20,
        min_modify_minutes: int = 5,
        emergency_conditions: List[str] = None,
        violation_penalty_multiplier: float = 2.0,
        max_violations_per_hour: int = 3
    ):
        """
        Initialize hold time enforcer.
        
        Args:
            min_hold_minutes: Minimum time before closing positions
            min_modify_minutes: Minimum time between modifications
            emergency_conditions: Conditions allowing emergency override
            violation_penalty_multiplier: Penalty multiplier for violations
            max_violations_per_hour: Max violations allowed per hour
        """
        self.min_hold_minutes = min_hold_minutes
        self.min_modify_minutes = min_modify_minutes
        self.violation_penalty_multiplier = violation_penalty_multiplier
        self.max_violations_per_hour = max_violations_per_hour
        
        # Emergency conditions that allow override
        self.emergency_conditions = emergency_conditions or [
            "daily_loss_limit_breach",
            "margin_call_risk", 
            "circuit_breaker_triggered",
            "extreme_volatility",
            "system_shutdown"
        ]
        
        # Position tracking
        self.position_timings: Dict[str, Dict[str, PositionTiming]] = {}  # symbol -> side -> timing
        self.violation_history: List[Tuple[float, str, str]] = []  # (timestamp, symbol, violation_type)
        self.total_violations = 0
        
        logger.info(f"MinimumHoldTimeEnforcer initialized: {min_hold_minutes}min hold, {min_modify_minutes}min modify")
    
    def register_position_open(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        timestamp: Optional[float] = None
    ) -> PositionTiming:
        """
        Register a new position opening.
        
        Args:
            symbol: Trading symbol
            side: Position side ("LONG" or "SHORT")
            quantity: Position quantity
            price: Entry price
            timestamp: Position entry time
            
        Returns:
            PositionTiming object
        """
        if timestamp is None:
            timestamp = time.time()
        
        timing = PositionTiming(
            symbol=symbol,
            side=side,
            entry_time=timestamp,
            last_modify_time=timestamp,
            quantity=quantity,
            avg_price=price,
            hold_time_minutes=self.min_hold_minutes,
            can_modify_after=timestamp + (self.min_modify_minutes * 60),
            can_close_after=timestamp + (self.min_hold_minutes * 60)
        )
        
        # Initialize symbol if needed
        if symbol not in self.position_timings:
            self.position_timings[symbol] = {}
        
        self.position_timings[symbol][side] = timing
        
        logger.info(f"Registered {side} position for {symbol}: hold until {time.ctime(timing.can_close_after)}")
        return timing
    
    def can_close_position(
        self,
        symbol: str,
        side: str,
        emergency_reason: Optional[str] = None,
        current_time: Optional[float] = None
    ) -> Tuple[bool, str, Optional[float]]:
        """
        Check if position can be closed.
        
        Args:
            symbol: Trading symbol
            side: Position side
            emergency_reason: Reason for emergency close
            current_time: Current timestamp
            
        Returns:
            (can_close, reason, time_remaining_seconds)
        """
        if current_time is None:
            current_time = time.time()
        
        # Check if position exists
        if symbol not in self.position_timings or side not in self.position_timings[symbol]:
            return True, "No position to close", None
        
        timing = self.position_timings[symbol][side]
        
        # Check emergency override
        if emergency_reason and emergency_reason in self.emergency_conditions:
            self._record_emergency_override(symbol, side, emergency_reason, current_time)
            return True, f"Emergency override: {emergency_reason}", None
        
        # Check minimum hold time
        if current_time >= timing.can_close_after:
            return True, "Hold time requirement met", None
        
        # Calculate remaining time
        time_remaining = timing.can_close_after - current_time
        minutes_remaining = time_remaining / 60.0
        
        return False, f"Hold time not met: {minutes_remaining:.1f} min remaining", time_remaining
    
    def can_modify_position(
        self,
        symbol: str,
        side: str,
        modification_type: str = "size_change",
        current_time: Optional[float] = None
    ) -> Tuple[bool, str, Optional[float]]:
        """
        Check if position can be modified (increase/decrease).
        
        Args:
            symbol: Trading symbol
            side: Position side
            modification_type: Type of modification
            current_time: Current timestamp
            
        Returns:
            (can_modify, reason, time_remaining_seconds)
        """
        if current_time is None:
            current_time = time.time()
        
        # Check if position exists
        if symbol not in self.position_timings or side not in self.position_timings[symbol]:
            return True, "No existing position", None
        
        timing = self.position_timings[symbol][side]
        
        # Check minimum modify time
        if current_time >= timing.can_modify_after:
            return True, "Modification allowed", None
        
        # Calculate remaining time
        time_remaining = timing.can_modify_after - current_time
        minutes_remaining = time_remaining / 60.0
        
        return False, f"Modify time not met: {minutes_remaining:.1f} min remaining", time_remaining
    
    def can_side_flip(
        self,
        symbol: str,
        from_side: str,
        to_side: str,
        emergency_reason: Optional[str] = None,
        current_time: Optional[float] = None
    ) -> Tuple[bool, str, Optional[float]]:
        """
        Check if can flip from one side to another (LONG->SHORT or SHORT->LONG).
        
        Args:
            symbol: Trading symbol
            from_side: Current position side
            to_side: Target position side
            emergency_reason: Emergency reason for flip
            current_time: Current timestamp
            
        Returns:
            (can_flip, reason, time_remaining_seconds)
        """
        # First check if we can close the existing position
        can_close, close_reason, close_time_remaining = self.can_close_position(
            symbol, from_side, emergency_reason, current_time
        )
        
        if not can_close:
            return False, f"Cannot flip: {close_reason}", close_time_remaining
        
        # Check recent violation history for this symbol
        if current_time is None:
            current_time = time.time()
        
        recent_violations = [
            v for v in self.violation_history 
            if v[0] > (current_time - 3600) and v[1] == symbol  # Last hour
        ]
        
        if len(recent_violations) >= self.max_violations_per_hour:
            return False, "Too many recent violations for this symbol", None
        
        return True, "Side flip allowed", None
    
    def execute_close_all(
        self,
        emergency_reason: str = "CLOSE_ALL_triggered",
        current_time: Optional[float] = None
    ) -> Dict[str, List[str]]:
        """
        Execute emergency CLOSE_ALL - overrides all hold time requirements.
        
        Args:
            emergency_reason: Reason for CLOSE_ALL
            current_time: Current timestamp
            
        Returns:
            Dictionary of closed positions by symbol
        """
        if current_time is None:
            current_time = time.time()
        
        closed_positions = {}
        
        for symbol, sides in self.position_timings.items():
            closed_sides = []
            for side, timing in sides.items():
                # Record emergency override
                self._record_emergency_override(symbol, side, emergency_reason, current_time)
                closed_sides.append(side)
            
            if closed_sides:
                closed_positions[symbol] = closed_sides
        
        # Clear all position timings
        self.position_timings.clear()
        
        logger.warning(f"CLOSE_ALL executed: {emergency_reason} - cleared all positions")
        return closed_positions
    
    def update_position_modify(
        self,
        symbol: str,
        side: str,
        new_quantity: float,
        current_time: Optional[float] = None
    ):
        """
        Update position timing after modification.
        
        Args:
            symbol: Trading symbol
            side: Position side
            new_quantity: New position quantity
            current_time: Current timestamp
        """
        if current_time is None:
            current_time = time.time()
        
        if symbol in self.position_timings and side in self.position_timings[symbol]:
            timing = self.position_timings[symbol][side]
            timing.last_modify_time = current_time
            timing.quantity = new_quantity
            timing.can_modify_after = current_time + (self.min_modify_minutes * 60)
            
            logger.info(f"Updated {side} position timing for {symbol}: next modify after {time.ctime(timing.can_modify_after)}")
    
    def close_position(
        self,
        symbol: str,
        side: str,
        current_time: Optional[float] = None
    ) -> bool:
        """
        Close a position and remove its timing.
        
        Args:
            symbol: Trading symbol
            side: Position side
            current_time: Current timestamp
            
        Returns:
            Success flag
        """
        if symbol in self.position_timings and side in self.position_timings[symbol]:
            del self.position_timings[symbol][side]
            
            # Clean up empty symbol entries
            if not self.position_timings[symbol]:
                del self.position_timings[symbol]
            
            logger.info(f"Closed {side} position timing for {symbol}")
            return True
        
        return False
    
    def get_hold_time_status(self) -> Dict[str, Dict[str, Dict]]:
        """
        Get comprehensive hold time status for all positions.
        
        Returns:
            Nested dict with timing status for all positions
        """
        current_time = time.time()
        status = {}
        
        for symbol, sides in self.position_timings.items():
            status[symbol] = {}
            
            for side, timing in sides.items():
                can_close, close_reason, close_remaining = self.can_close_position(
                    symbol, side, current_time=current_time
                )
                can_modify, modify_reason, modify_remaining = self.can_modify_position(
                    symbol, side, current_time=current_time
                )
                
                status[symbol][side] = {
                    "entry_time": timing.entry_time,
                    "entry_time_str": time.ctime(timing.entry_time),
                    "hold_minutes_elapsed": (current_time - timing.entry_time) / 60.0,
                    "min_hold_minutes": timing.hold_time_minutes,
                    "can_close": can_close,
                    "close_reason": close_reason,
                    "close_remaining_minutes": close_remaining / 60.0 if close_remaining else None,
                    "can_modify": can_modify,
                    "modify_reason": modify_reason,
                    "modify_remaining_minutes": modify_remaining / 60.0 if modify_remaining else None,
                    "quantity": timing.quantity,
                    "avg_price": timing.avg_price
                }
        
        return status
    
    def get_violation_summary(self) -> Dict[str, any]:
        """Get summary of hold time violations"""
        current_time = time.time()
        
        # Count violations by type in last hour
        hour_ago = current_time - 3600
        recent_violations = [v for v in self.violation_history if v[0] > hour_ago]
        
        violation_types = {}
        for _, symbol, vtype in recent_violations:
            violation_types[vtype] = violation_types.get(vtype, 0) + 1
        
        return {
            "total_violations_all_time": self.total_violations,
            "violations_last_hour": len(recent_violations),
            "max_allowed_per_hour": self.max_violations_per_hour,
            "violation_types_last_hour": violation_types,
            "violation_rate_compliance": len(recent_violations) <= self.max_violations_per_hour
        }
    
    def _record_violation(
        self,
        symbol: str,
        violation_type: str,
        current_time: float
    ):
        """Record a hold time violation"""
        self.violation_history.append((current_time, symbol, violation_type))
        self.total_violations += 1
        
        # Keep only last 24 hours of violations
        day_ago = current_time - 86400
        self.violation_history = [v for v in self.violation_history if v[0] > day_ago]
        
        logger.warning(f"Hold time violation: {symbol} - {violation_type}")
    
    def _record_emergency_override(
        self,
        symbol: str,
        side: str,
        reason: str,
        current_time: float
    ):
        """Record an emergency override"""
        if symbol in self.position_timings and side in self.position_timings[symbol]:
            timing = self.position_timings[symbol][side]
            timing.emergency_close_allowed = True
            timing.emergency_reason = reason
        
        self._record_violation(symbol, HoldTimeViolationType.EMERGENCY_OVERRIDE.value, current_time)
        logger.warning(f"Emergency override: {symbol} {side} - {reason}")


if __name__ == "__main__":
    # Test the minimum hold time enforcer
    logging.basicConfig(level=logging.INFO)
    
    enforcer = MinimumHoldTimeEnforcer(min_hold_minutes=20, min_modify_minutes=5)
    
    print("🧪 Testing Minimum Hold Time Enforcement...")
    
    # Register a position
    current_time = time.time()
    timing = enforcer.register_position_open("BTCUSDT", "LONG", 0.1, 50000, current_time)
    
    print(f"Registered BTCUSDT LONG position at {time.ctime(current_time)}")
    
    # Test immediate close (should fail)
    can_close, reason, remaining = enforcer.can_close_position("BTCUSDT", "LONG", current_time=current_time)
    print(f"Can close immediately: {can_close} - {reason}")
    if remaining:
        print(f"  Time remaining: {remaining/60:.1f} minutes")
    
    # Test modification (should fail initially)
    can_modify, reason, remaining = enforcer.can_modify_position("BTCUSDT", "LONG", current_time=current_time)
    print(f"Can modify immediately: {can_modify} - {reason}")
    
    # Test after 10 minutes
    future_time = current_time + (10 * 60)
    can_modify, reason, remaining = enforcer.can_modify_position("BTCUSDT", "LONG", current_time=future_time)
    print(f"Can modify after 10 min: {can_modify} - {reason}")
    
    # Test emergency close
    can_close, reason, remaining = enforcer.can_close_position(
        "BTCUSDT", "LONG", 
        emergency_reason="daily_loss_limit_breach",
        current_time=current_time
    )
    print(f"Can emergency close: {can_close} - {reason}")
    
    # Test CLOSE_ALL
    print(f"\nBefore CLOSE_ALL: {len(enforcer.position_timings)} symbols with positions")
    closed = enforcer.execute_close_all("system_shutdown")
    print(f"CLOSE_ALL result: {closed}")
    print(f"After CLOSE_ALL: {len(enforcer.position_timings)} symbols with positions")
    
    # Get violation summary
    summary = enforcer.get_violation_summary()
    print(f"\nViolation Summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")