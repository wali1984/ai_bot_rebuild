"""
Signal State Manager - Comprehensive Signal Deduplication System
================================================================

This module provides a centralized state machine for managing signal generation.
It replaces fragmented deduplication logic with a unified approach that tracks:
1. Signal state per symbol (IDLE, PENDING, EXECUTED)
2. Position state changes (side, size, PnL)
3. Price movements
4. Action history with timestamps

Key Design Principles:
- State-aware: Only generate signals when state actually changes
- Position-aware: Track position changes, not just signal history
- Execution-feedback: Mark signals as executed when trader confirms
- Fail-safe: Conservative defaults (block when uncertain)
"""

import time
import threading
import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class SignalState(Enum):
    """State of a signal for a symbol"""
    IDLE = "idle"              # No active signal - can generate
    PENDING = "pending"        # Signal sent, awaiting execution
    EXECUTED = "executed"      # Signal was executed by trader


@dataclass
class PositionSnapshot:
    """Snapshot of position state at time of signal"""
    has_position: bool = False
    side: str = "FLAT"         # LONG, SHORT, FLAT
    size: float = 0.0          # Position size
    entry_price: float = 0.0   # Entry price
    pnl_pct: float = 0.0       # Current PnL %
    timestamp_ms: int = 0      # When snapshot was taken


@dataclass  
class SignalRecord:
    """Record of a signal sent for a symbol"""
    signal_id: str             # Unique ID (stream_id or generated)
    action_name: str           # OPEN_LONG, CLOSE_SHORT, etc.
    action_category: str       # OPEN_RISK, PROTECTIVE, HEDGE
    confidence: float
    price_at_signal: float
    position_snapshot: PositionSnapshot
    timestamp_ms: int
    state: SignalState = SignalState.PENDING
    execution_result: str = ""  # EXECUTED, REJECTED, EXPIRED
    execution_ts_ms: int = 0


class SignalStateManager:
    """
    Centralized signal state management with sophisticated deduplication.
    
    Prevents duplicate signals by tracking:
    - Signal state (IDLE → PENDING → EXECUTED/EXPIRED)
    - Position changes (new position, closed, PnL thresholds)
    - Price movements (significant change allows new signal)
    - Cooldown periods per action type
    
    Usage:
        manager = SignalStateManager(redis_client)
        
        # Before generating signal:
        should_generate, reason = manager.should_generate_signal(
            symbol="BTCUSDT",
            action_name="CLOSE_LONG",
            action_category="PROTECTIVE",
            confidence=0.85,
            current_price=50000.0,
            position_info={...}
        )
        
        if should_generate:
            # Generate and publish signal
            stream_id = publish_signal(...)
            manager.record_signal_sent(symbol, action_name, stream_id, ...)
        
        # When trader reports execution:
        manager.mark_signal_executed(symbol, stream_id, "EXECUTED")
    """
    
    # Cooldown periods by action category (in seconds)
    DEFAULT_COOLDOWNS = {
        'OPEN_RISK': 300,     # 5 minutes between OPEN signals
        'HEDGE': 180,         # 3 minutes between HEDGE signals
        'PROTECTIVE': 60,     # 1 minute between PROTECTIVE signals (safety critical)
    }
    
    # Price change thresholds to override cooldown (percentage)
    PRICE_CHANGE_THRESHOLD = {
        'OPEN_RISK': 1.0,     # 1% price change allows new entry
        'HEDGE': 0.7,         # 0.7% price change allows new hedge
        'PROTECTIVE': 0.3,    # 0.3% price change allows new exit
    }
    
    # PnL change thresholds to override cooldown (percentage points)
    PNL_CHANGE_THRESHOLD = {
        'OPEN_RISK': 2.0,     # 2% PnL change
        'HEDGE': 1.5,         # 1.5% PnL change
        'PROTECTIVE': 0.5,    # 0.5% PnL change (more sensitive for exits)
    }
    
    # Max pending signal age before auto-expiring (milliseconds)
    PENDING_SIGNAL_TTL_MS = 120_000  # 2 minutes
    
    def __init__(self, redis_client=None):
        """
        Initialize Signal State Manager.
        
        Args:
            redis_client: Optional Redis client for persistence/cross-process state
        """
        self._redis = redis_client
        self._lock = threading.Lock()
        
        # In-memory state tracking (per symbol)
        self._signal_records: Dict[str, SignalRecord] = {}  # symbol -> last signal record
        self._position_snapshots: Dict[str, PositionSnapshot] = {}  # symbol -> last known position
        self._signal_history: Dict[str, list] = defaultdict(list)  # symbol -> list of recent records
        
        # Statistics
        self._stats = {
            'signals_allowed': 0,
            'signals_blocked': 0,
            'blocked_by_pending': 0,
            'blocked_by_cooldown': 0,
            'blocked_by_duplicate': 0,
            'overridden_by_price': 0,
            'overridden_by_pnl': 0,
            'overridden_by_position': 0,
        }
        
        logger.info("🔄 SignalStateManager initialized - Centralized signal deduplication active")
    
    def should_generate_signal(
        self,
        symbol: str,
        action_name: str,
        action_category: str,
        confidence: float,
        current_price: float,
        position_info: Optional[Dict[str, Any]] = None,
        timeframe: str = "multi"
    ) -> Tuple[bool, str]:
        """
        Determine if a signal should be generated based on state analysis.
        
        Args:
            symbol: Trading pair (BTCUSDT)
            action_name: Normalized action (OPEN_LONG, CLOSE_SHORT, etc.)
            action_category: Category (OPEN_RISK, HEDGE, PROTECTIVE)
            confidence: Model confidence 0-1
            current_price: Current market price
            position_info: Current position dict (has_position, side, pnl_pct, etc.)
            timeframe: Signal timeframe (5m, 15m, multi)
            
        Returns:
            Tuple of (should_generate: bool, reason: str)
        """
        with self._lock:
            now_ms = int(time.time() * 1000)
            
            # Build current position snapshot
            current_pos = self._build_position_snapshot(position_info, now_ms)
            
            # Get last signal for this symbol
            last_record = self._signal_records.get(symbol)
            last_pos = self._position_snapshots.get(symbol)
            
            # ============================================================
            # CHECK 1: First signal for symbol - always allow
            # ============================================================
            if last_record is None:
                self._stats['signals_allowed'] += 1
                return True, f"FIRST_SIGNAL:{symbol}"
            
            # ============================================================
            # CHECK 2: Pending signal timeout - expire and allow retry
            # ============================================================
            if last_record.state == SignalState.PENDING:
                age_ms = now_ms - last_record.timestamp_ms
                
                if age_ms >= self.PENDING_SIGNAL_TTL_MS:
                    # Pending signal expired - mark and allow new signal
                    last_record.state = SignalState.EXECUTED
                    last_record.execution_result = "EXPIRED"
                    last_record.execution_ts_ms = now_ms
                    logger.info(f"[SIGNAL_EXPIRED] {symbol} {last_record.action_name} "
                              f"age={age_ms/1000:.1f}s - allowing new signal")
                else:
                    # Still pending - check if situation changed
                    override, override_reason = self._check_override_conditions(
                        symbol, action_name, action_category, 
                        confidence, current_price, current_pos,
                        last_record, last_pos
                    )
                    
                    if override:
                        # Situation changed enough to allow new signal
                        logger.info(f"[PENDING_OVERRIDE] {symbol} {action_name}: {override_reason}")
                        self._stats['signals_allowed'] += 1
                        return True, f"PENDING_OVERRIDE:{override_reason}"
                    
                    # Still pending with no significant change
                    self._stats['signals_blocked'] += 1
                    self._stats['blocked_by_pending'] += 1
                    return False, f"PENDING_ACTIVE:{last_record.action_name}:{age_ms/1000:.0f}s_old"
            
            # ============================================================
            # CHECK 3: Same action deduplication (action + category match)
            # ============================================================
            if (last_record.action_name == action_name and 
                last_record.action_category == action_category):
                
                # Check if cooldown expired
                cooldown_ms = self.DEFAULT_COOLDOWNS.get(action_category, 300) * 1000
                age_ms = now_ms - last_record.timestamp_ms
                
                if age_ms < cooldown_ms:
                    # Within cooldown - check override conditions
                    override, override_reason = self._check_override_conditions(
                        symbol, action_name, action_category,
                        confidence, current_price, current_pos,
                        last_record, last_pos
                    )
                    
                    if override:
                        logger.info(f"[COOLDOWN_OVERRIDE] {symbol} {action_name}: {override_reason}")
                        self._stats['signals_allowed'] += 1
                        return True, f"COOLDOWN_OVERRIDE:{override_reason}"
                    
                    # Duplicate within cooldown
                    self._stats['signals_blocked'] += 1
                    self._stats['blocked_by_cooldown'] += 1
                    return False, f"COOLDOWN_ACTIVE:{action_category}:{(cooldown_ms-age_ms)/1000:.0f}s_remaining"
            
            # ============================================================
            # CHECK 4: Action change detection
            # ============================================================
            if last_record.action_name != action_name:
                # Different action - generally allow but check for flip storms
                if self._is_flip_storm(symbol, action_name, last_record):
                    self._stats['signals_blocked'] += 1
                    return False, f"FLIP_STORM_BLOCK:too_many_direction_changes"
                
                logger.info(f"[ACTION_CHANGE] {symbol}: {last_record.action_name} → {action_name}")
                self._stats['signals_allowed'] += 1
                return True, f"ACTION_CHANGE:{last_record.action_name}→{action_name}"
            
            # ============================================================
            # CHECK 5: Position state change
            # ============================================================
            position_changed, change_reason = self._check_position_change(current_pos, last_pos)
            if position_changed:
                logger.info(f"[POSITION_CHANGE] {symbol}: {change_reason}")
                self._stats['signals_allowed'] += 1
                self._stats['overridden_by_position'] += 1
                return True, f"POSITION_CHANGE:{change_reason}"
            
            # ============================================================
            # DEFAULT: Allow if cooldown expired
            # ============================================================
            cooldown_ms = self.DEFAULT_COOLDOWNS.get(action_category, 300) * 1000
            age_ms = now_ms - last_record.timestamp_ms
            
            if age_ms >= cooldown_ms:
                self._stats['signals_allowed'] += 1
                return True, f"COOLDOWN_EXPIRED:{age_ms/1000:.0f}s>={cooldown_ms/1000:.0f}s"
            
            # Blocked by default
            self._stats['signals_blocked'] += 1
            self._stats['blocked_by_duplicate'] += 1
            return False, f"DUPLICATE_SUPPRESSED:no_change_detected"
    
    def record_signal_sent(
        self,
        symbol: str,
        action_name: str,
        action_category: str,
        signal_id: str,
        confidence: float,
        price: float,
        position_info: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record that a signal was sent (for tracking state).
        
        Call this AFTER successfully publishing to Redis stream.
        """
        with self._lock:
            now_ms = int(time.time() * 1000)
            pos_snapshot = self._build_position_snapshot(position_info, now_ms)
            
            record = SignalRecord(
                signal_id=signal_id,
                action_name=action_name,
                action_category=action_category,
                confidence=confidence,
                price_at_signal=price,
                position_snapshot=pos_snapshot,
                timestamp_ms=now_ms,
                state=SignalState.PENDING
            )
            
            # Update state
            self._signal_records[symbol] = record
            self._position_snapshots[symbol] = pos_snapshot
            
            # Track history (keep last 10)
            self._signal_history[symbol].append(record)
            if len(self._signal_history[symbol]) > 10:
                self._signal_history[symbol] = self._signal_history[symbol][-10:]
            
            logger.debug(f"[SIGNAL_RECORDED] {symbol} {action_name} id={signal_id} state=PENDING")
    
    def mark_signal_executed(
        self,
        symbol: str,
        signal_id: str,
        result: str = "EXECUTED"
    ) -> None:
        """
        Mark a signal as executed by trader.
        
        Call this when trader reports execution (success or rejection).
        
        Args:
            symbol: Trading pair
            signal_id: Stream ID of the signal
            result: EXECUTED, REJECTED, SKIPPED
        """
        with self._lock:
            record = self._signal_records.get(symbol)
            if record and record.signal_id == signal_id:
                record.state = SignalState.EXECUTED
                record.execution_result = result
                record.execution_ts_ms = int(time.time() * 1000)
                logger.debug(f"[SIGNAL_EXECUTED] {symbol} {record.action_name} result={result}")
    
    def mark_position_changed(
        self,
        symbol: str,
        position_info: Dict[str, Any]
    ) -> None:
        """
        Update position snapshot when position changes.
        
        This helps detect when signals should be regenerated.
        """
        with self._lock:
            now_ms = int(time.time() * 1000)
            self._position_snapshots[symbol] = self._build_position_snapshot(position_info, now_ms)
            
            # Also update record state if it was pending
            record = self._signal_records.get(symbol)
            if record and record.state == SignalState.PENDING:
                record.state = SignalState.EXECUTED
                record.execution_result = "POSITION_CHANGE"
                record.execution_ts_ms = now_ms
    
    def get_stats(self) -> Dict[str, Any]:
        """Get deduplication statistics."""
        with self._lock:
            total = self._stats['signals_allowed'] + self._stats['signals_blocked']
            block_rate = (self._stats['signals_blocked'] / total * 100) if total > 0 else 0
            return {
                **self._stats,
                'total_evaluated': total,
                'block_rate_pct': block_rate,
            }
    
    def _build_position_snapshot(
        self,
        position_info: Optional[Dict[str, Any]],
        timestamp_ms: int
    ) -> PositionSnapshot:
        """Build position snapshot from position dict."""
        if not position_info:
            return PositionSnapshot(timestamp_ms=timestamp_ms)
        
        return PositionSnapshot(
            has_position=bool(position_info.get('has_position', False)),
            side=str(position_info.get('side', 'FLAT')).upper(),
            size=float(position_info.get('size', 0) or position_info.get('positionAmt', 0) or 0),
            entry_price=float(position_info.get('entry_price', 0) or position_info.get('entryPrice', 0) or 0),
            pnl_pct=float(position_info.get('pnl_pct', 0) or position_info.get('unrealizedProfit', 0) or 0),
            timestamp_ms=timestamp_ms
        )
    
    def _check_override_conditions(
        self,
        symbol: str,
        action_name: str,
        action_category: str,
        confidence: float,
        current_price: float,
        current_pos: PositionSnapshot,
        last_record: SignalRecord,
        last_pos: Optional[PositionSnapshot]
    ) -> Tuple[bool, str]:
        """
        Check if conditions warrant overriding cooldown/pending status.
        
        Returns:
            Tuple of (should_override: bool, reason: str)
        """
        reasons = []
        
        # 1. Price change override
        if last_record.price_at_signal > 0 and current_price > 0:
            price_delta_pct = abs((current_price - last_record.price_at_signal) / 
                                 last_record.price_at_signal) * 100
            threshold = self.PRICE_CHANGE_THRESHOLD.get(action_category, 1.0)
            
            if price_delta_pct >= threshold:
                reasons.append(f"price_change_{price_delta_pct:.2f}%>={threshold}%")
                self._stats['overridden_by_price'] += 1
        
        # 2. PnL change override (for exits)
        if last_pos and current_pos.has_position and last_pos.has_position:
            pnl_delta = abs(current_pos.pnl_pct - last_pos.pnl_pct)
            threshold = self.PNL_CHANGE_THRESHOLD.get(action_category, 1.0)
            
            if pnl_delta >= threshold:
                reasons.append(f"pnl_change_{pnl_delta:.2f}pp>={threshold}pp")
                self._stats['overridden_by_pnl'] += 1
        
        # 3. Position state change (opened/closed/flipped)
        position_changed, change_reason = self._check_position_change(current_pos, last_pos)
        if position_changed:
            reasons.append(f"position_{change_reason}")
        
        # 4. Confidence jump (significant increase in model confidence)
        if confidence - last_record.confidence >= 0.10:  # 10% conf jump
            reasons.append(f"conf_jump_{last_record.confidence:.2f}→{confidence:.2f}")
        
        if reasons:
            return True, "+".join(reasons)
        
        return False, ""
    
    def _check_position_change(
        self,
        current: PositionSnapshot,
        last: Optional[PositionSnapshot]
    ) -> Tuple[bool, str]:
        """Check if position state changed significantly."""
        if last is None:
            return True, "first_snapshot"
        
        # Position opened
        if current.has_position and not last.has_position:
            return True, f"opened_{current.side}"
        
        # Position closed
        if not current.has_position and last.has_position:
            return True, f"closed_{last.side}"
        
        # Side flipped
        if current.side != last.side and current.has_position:
            return True, f"flipped_{last.side}→{current.side}"
        
        # Size changed significantly (>20%)
        if last.size > 0 and current.size > 0:
            size_change = abs(current.size - last.size) / last.size
            if size_change >= 0.2:
                return True, f"size_change_{size_change:.0%}"
        
        return False, ""
    
    def _is_flip_storm(
        self,
        symbol: str,
        new_action: str,
        last_record: SignalRecord
    ) -> bool:
        """
        Detect flip storms (rapid back-and-forth direction changes).
        
        Returns True if this would be the 3rd+ direction flip in 10 minutes.
        """
        history = self._signal_history.get(symbol, [])
        if len(history) < 2:
            return False
        
        now_ms = int(time.time() * 1000)
        ten_min_ms = 600_000
        
        # Count direction changes in last 10 minutes
        flip_count = 0
        prev_direction = None
        
        for record in history:
            if now_ms - record.timestamp_ms > ten_min_ms:
                continue
            
            # Determine direction
            direction = None
            if 'LONG' in record.action_name.upper():
                direction = 'LONG'
            elif 'SHORT' in record.action_name.upper():
                direction = 'SHORT'
            
            if direction and prev_direction and direction != prev_direction:
                flip_count += 1
            
            prev_direction = direction
        
        # Check new action direction
        new_direction = None
        if 'LONG' in new_action.upper():
            new_direction = 'LONG'
        elif 'SHORT' in new_action.upper():
            new_direction = 'SHORT'
        
        if new_direction and prev_direction and new_direction != prev_direction:
            flip_count += 1
        
        # Block if 3+ flips in 10 minutes
        return flip_count >= 3


# Singleton instance
_signal_state_manager: Optional[SignalStateManager] = None
_manager_lock = threading.Lock()


def get_signal_state_manager(redis_client=None) -> SignalStateManager:
    """
    Get singleton SignalStateManager instance.
    
    Thread-safe lazy initialization.
    """
    global _signal_state_manager
    
    if _signal_state_manager is None:
        with _manager_lock:
            if _signal_state_manager is None:
                _signal_state_manager = SignalStateManager(redis_client)
    
    return _signal_state_manager
