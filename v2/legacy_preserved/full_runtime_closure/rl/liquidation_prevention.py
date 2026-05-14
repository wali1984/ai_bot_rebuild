"""
Liquidation Prevention & Execution Constraint Feedback System
=============================================================
Implements the 1st Feb 2026 architecture for preventing forced liquidations.

Components:
1. ExecutionEventPublisher - Instrumentation for trader constraint events
2. StressTracker - Rolling window tracker for account stress states
3. ExecutionConstraintConsumer - Consumes events and updates stress state
4. PortfolioGatekeeper - Enforces margin reserves and stress gating
5. RetroLiquidationPenalty - Decaying penalty for past liquidation events
6. RewardIntegrator - Wires penalty signals into RL reward calculation

Kill switches (from config.py):
- ENABLE_EXECUTION_EVENT_PUBLISHING
- ENABLE_STRESS_TRACKER
- ENABLE_TRAINER_STRESS_GATING
- ENABLE_FEEDBACK_FAILURE_PENALTIES
- ENABLE_TERMINAL_ON_EQUITY_COLLAPSE
- ENABLE_PORTFOLIO_AWARE_REWARD
- ENABLE_POST_CASCADE_COOLDOWN
- ENABLE_RETRO_LIQUIDATION_PENALTY
"""

import json
import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# =============================================================================
# STRESS STATE ENUM
# =============================================================================

class StressState(Enum):
    """Account stress levels based on execution constraint feedback"""
    NORMAL = "NORMAL"      # No recent risk incidents
    STRESS = "STRESS"      # Warning signs (repeated margin blocks, high utilization)
    EMERGENCY = "EMERGENCY"  # Critical failure imminent/occurred (equity collapse, CB)
    COOLDOWN = "COOLDOWN"  # Post-cascade recovery period


# =============================================================================
# EXECUTION EVENT STRUCTURE
# =============================================================================

@dataclass
class ExecutionEvent:
    """Structured execution constraint event"""
    ts_ms: int
    account_id: str
    symbol: str
    signal_id: str
    action: str
    category: str  # OPEN_RISK, HEDGE, REDUCE, CLOSE, SYSTEM
    status: str    # REJECTED, FAILED, EXECUTED
    reason_code: str  # FREE_MARGIN_BLOCK, -2019, CIRCUIT_BREAKER, EQUITY_COLLAPSE, etc.
    portfolio: Dict[str, float] = field(default_factory=dict)  # equity, margin, etc.
    exec: Dict[str, Any] = field(default_factory=dict)  # price, qty, maker
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts_ms": self.ts_ms,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "signal_id": self.signal_id,
            "action": self.action,
            "category": self.category,
            "status": self.status,
            "reason_code": self.reason_code,
            "portfolio": self.portfolio,
            "exec": self.exec
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ExecutionEvent":
        return cls(
            ts_ms=int(data.get("ts_ms", int(time.time() * 1000))),
            account_id=str(data.get("account_id", "unknown")),
            symbol=str(data.get("symbol", "")),
            signal_id=str(data.get("signal_id", "")),
            action=str(data.get("action", "")),
            category=str(data.get("category", "SYSTEM")),
            status=str(data.get("status", "UNKNOWN")),
            reason_code=str(data.get("reason_code", "")),
            portfolio=data.get("portfolio", {}),
            exec=data.get("exec", {})
        )


# =============================================================================
# COMPONENT 1: EXECUTION EVENT PUBLISHER (Trader-side instrumentation)
# =============================================================================

class ExecutionEventPublisher:
    """
    Publishes structured execution constraint events to Redis stream.
    Called by traders when orders are blocked or fail due to margin/risk constraints.
    
    This is a lightweight helper - actual calls happen in trader code.
    """
    
    def __init__(self, redis_client, stream_name: str = None):
        self.redis = redis_client
        try:
            import config
            self.stream_name = stream_name or getattr(config, 'EXECUTION_FEEDBACK_STREAM', 'wma:trader:execution_feedback')
            self.enabled = getattr(config, 'ENABLE_EXECUTION_EVENT_PUBLISHING', True)
        except ImportError:
            self.stream_name = stream_name or 'wma:trader:execution_feedback'
            self.enabled = True
        
        logger.info(f"[EXEC-EVENT-PUB] Initialized (stream={self.stream_name}, enabled={self.enabled})")
    
    def publish(self, event: ExecutionEvent) -> Optional[str]:
        """Publish execution event to Redis stream"""
        if not self.enabled:
            return None
        
        if not self.redis:
            logger.warning("[EXEC-EVENT-PUB] No Redis client, skipping publish")
            return None
        
        try:
            payload = {"data": json.dumps(event.to_dict())}
            msg_id = self.redis.xadd(self.stream_name, payload, maxlen=10000)
            logger.debug(f"[EXEC-EVENT-PUB] Published {event.reason_code} for {event.symbol} (id={msg_id})")
            return msg_id
        except Exception as e:
            logger.error(f"[EXEC-EVENT-PUB] Failed to publish: {e}")
            return None
    
    def publish_margin_block(self, account_id: str, symbol: str, signal_id: str,
                             action: str, category: str, reason_code: str,
                             portfolio_snapshot: Dict = None, exec_details: Dict = None) -> Optional[str]:
        """Convenience method for margin-related blocks"""
        event = ExecutionEvent(
            ts_ms=int(time.time() * 1000),
            account_id=account_id,
            symbol=symbol,
            signal_id=signal_id,
            action=action,
            category=category,
            status="REJECTED",
            reason_code=reason_code,
            portfolio=portfolio_snapshot or {},
            exec=exec_details or {}
        )
        return self.publish(event)


# =============================================================================
# COMPONENT 2: STRESS TRACKER
# =============================================================================

class StressTracker:
    """
    Maintains rolling window metrics of execution constraint events per account.
    Computes stress state (NORMAL, STRESS, EMERGENCY, COOLDOWN) based on recent incidents.
    """
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        
        # Load config
        try:
            import config
            self.window_seconds = getattr(config, 'STRESS_TRACKER_WINDOW_SECONDS', 60)
            self.margin_block_threshold = getattr(config, 'STRESS_TRACKER_MARGIN_BLOCK_THRESHOLD', 3)
            self.cb_window_seconds = getattr(config, 'STRESS_TRACKER_CIRCUIT_BREAKER_WINDOW', 300)
            self.enabled = getattr(config, 'ENABLE_STRESS_TRACKER', True)
            self.cooldown_seconds = getattr(config, 'POST_CASCADE_COOLDOWN_SECONDS', 1800)
            self.cooldown_enabled = getattr(config, 'ENABLE_POST_CASCADE_COOLDOWN', False)
            self.liq_burst_threshold = getattr(config, 'POST_CASCADE_COOLDOWN_LIQ_BURST_THRESHOLD', 3)
            self.post_cascade_key_prefix = getattr(config, 'POST_CASCADE_REDIS_KEY_PREFIX', 'wma:post_cascade')
        except ImportError:
            self.window_seconds = 60
            self.margin_block_threshold = 3
            self.cb_window_seconds = 300
            self.enabled = True
            self.cooldown_seconds = 1800
            self.cooldown_enabled = False
            self.liq_burst_threshold = 3
            self.post_cascade_key_prefix = 'wma:post_cascade'
        
        # Per-account tracking
        self._events: Dict[str, List[ExecutionEvent]] = defaultdict(list)
        self._state: Dict[str, StressState] = defaultdict(lambda: StressState.NORMAL)
        self._cooldown_until: Dict[str, float] = {}  # account_id -> timestamp
        self._equity_collapse_ts: Dict[str, float] = {}  # Last collapse time
        self._lock = threading.Lock()
        
        # Metrics counters (for observability)
        self._metrics = defaultdict(lambda: {
            'free_margin_blocks_60s': 0,
            'api_2019_errors_60s': 0,
            'circuit_breaker_5m': 0,
            'equity_collapses_total': 0,
            'last_update_ts': 0
        })
        
        logger.info(f"[STRESS-TRACKER] Initialized (window={self.window_seconds}s, threshold={self.margin_block_threshold})")
    
    def record_event(self, event: ExecutionEvent):
        """Record an execution event and update stress state"""
        if not self.enabled:
            return
        
        with self._lock:
            account_id = event.account_id
            self._events[account_id].append(event)
            self._prune_old_events(account_id)
            self._update_stress_state(account_id, event)
    
    def _prune_old_events(self, account_id: str):
        """Remove events older than the tracking window"""
        now_ms = int(time.time() * 1000)
        max_window_ms = max(self.window_seconds, self.cb_window_seconds) * 1000
        cutoff_ms = now_ms - max_window_ms
        
        self._events[account_id] = [
            e for e in self._events[account_id]
            if e.ts_ms > cutoff_ms
        ]
    
    def _update_stress_state(self, account_id: str, latest_event: ExecutionEvent):
        """Update stress state based on recent events"""
        now = time.time()
        now_ms = int(now * 1000)
        old_state = self._state[account_id]
        
        # Check cooldown first
        if account_id in self._cooldown_until:
            if now < self._cooldown_until[account_id]:
                self._state[account_id] = StressState.COOLDOWN
                return
            else:
                del self._cooldown_until[account_id]
        
        events = self._events[account_id]
        
        # Count events in windows
        window_60s_ms = now_ms - (60 * 1000)
        window_5m_ms = now_ms - (300 * 1000)
        
        margin_blocks_60s = sum(1 for e in events if e.ts_ms > window_60s_ms 
                                and e.reason_code in ('FREE_MARGIN_BLOCK', 'MARGIN_CAP_BLOCK', 'RESERVED_MARGIN_BLOCK'))
        api_2019_60s = sum(1 for e in events if e.ts_ms > window_60s_ms and e.reason_code == '-2019')
        cb_5m = sum(1 for e in events if e.ts_ms > window_5m_ms and e.reason_code == 'CIRCUIT_BREAKER')
        equity_collapses = sum(1 for e in events if e.reason_code == 'EQUITY_COLLAPSE')
        
        # Update metrics
        self._metrics[account_id].update({
            'free_margin_blocks_60s': margin_blocks_60s,
            'api_2019_errors_60s': api_2019_60s,
            'circuit_breaker_5m': cb_5m,
            'equity_collapses_total': equity_collapses,
            'last_update_ts': now
        })
        
        # Determine state
        new_state = StressState.NORMAL
        
        # EMERGENCY conditions
        if latest_event.reason_code == 'EQUITY_COLLAPSE':
            new_state = StressState.EMERGENCY
            self._equity_collapse_ts[account_id] = now
            # Trigger cooldown if enabled
            if self.cooldown_enabled:
                self._cooldown_until[account_id] = now + self.cooldown_seconds
                new_state = StressState.COOLDOWN
                if old_state != StressState.COOLDOWN:
                    logger.warning(
                        f"POST_CASCADE_ENTER | account={account_id} | reason=EQUITY_COLLAPSE | "
                        f"cooldown_s={self.cooldown_seconds}"
                    )
                    try:
                        if self.redis:
                            key = f"{self.post_cascade_key_prefix}:{account_id}"
                            payload = {
                                "entered_ts": now,
                                "reason": "EQUITY_COLLAPSE",
                                "cooldown_s": self.cooldown_seconds,
                            }
                            self.redis.setex(key, int(self.cooldown_seconds), json.dumps(payload))
                    except Exception:
                        pass
                logger.warning(f"[STRESS-TRACKER] {account_id} entering COOLDOWN after EQUITY_COLLAPSE")
        
        elif equity_collapses >= self.liq_burst_threshold:
            new_state = StressState.EMERGENCY
            if self.cooldown_enabled:
                self._cooldown_until[account_id] = now + self.cooldown_seconds
                new_state = StressState.COOLDOWN
                if old_state != StressState.COOLDOWN:
                    logger.warning(
                        f"POST_CASCADE_ENTER | account={account_id} | reason=LIQ_BURST | "
                        f"cooldown_s={self.cooldown_seconds}"
                    )
                    try:
                        if self.redis:
                            key = f"{self.post_cascade_key_prefix}:{account_id}"
                            payload = {
                                "entered_ts": now,
                                "reason": "LIQ_BURST",
                                "cooldown_s": self.cooldown_seconds,
                            }
                            self.redis.setex(key, int(self.cooldown_seconds), json.dumps(payload))
                    except Exception:
                        pass
        
        elif cb_5m > 0 and (margin_blocks_60s >= self.margin_block_threshold or api_2019_60s > 0):
            new_state = StressState.EMERGENCY
        
        # STRESS conditions
        elif margin_blocks_60s >= self.margin_block_threshold:
            new_state = StressState.STRESS
        
        elif api_2019_60s > 0:
            new_state = StressState.STRESS
        
        elif cb_5m > 0:
            new_state = StressState.STRESS
        
        # Log state transitions
        if new_state != old_state:
            logger.warning(f"[STRESS-TRACKER] {account_id} state: {old_state.value} → {new_state.value} "
                          f"(margin_blocks={margin_blocks_60s}, api_2019={api_2019_60s}, cb={cb_5m})")
        
        self._state[account_id] = new_state
    
    def get_stress_state(self, account_id: str) -> StressState:
        """Get current stress state for account"""
        if not self.enabled:
            return StressState.NORMAL
        
        with self._lock:
            # Check cooldown expiry
            now = time.time()
            if account_id in self._cooldown_until:
                if now >= self._cooldown_until[account_id]:
                    del self._cooldown_until[account_id]
                    self._state[account_id] = StressState.NORMAL
                    try:
                        if self.redis:
                            key = f"{self.post_cascade_key_prefix}:{account_id}"
                            self.redis.delete(key)
                    except Exception:
                        pass
            
            return self._state.get(account_id, StressState.NORMAL)
    
    def get_metrics(self, account_id: str) -> Dict:
        """Get current metrics for observability"""
        with self._lock:
            return dict(self._metrics.get(account_id, {}))
    
    def should_deny_open(self, account_id: str) -> Tuple[bool, str]:
        """Check if opening new positions should be denied"""
        state = self.get_stress_state(account_id)
        
        if state == StressState.EMERGENCY:
            return True, "STRESS_STATE_EMERGENCY"
        elif state == StressState.COOLDOWN:
            return True, "POST_CASCADE_COOLDOWN"
        elif state == StressState.STRESS:
            # In STRESS, we allow but may want to warn
            return False, ""
        
        return False, ""
    
    def get_penalty_adjustment(self, account_id: str, base_reward: float) -> float:
        """Get reward penalty adjustment based on stress state"""
        state = self.get_stress_state(account_id)
        metrics = self.get_metrics(account_id)
        
        penalty = 0.0
        
        try:
            import config
            if state == StressState.STRESS:
                # Mild penalty during stress
                penalty = -0.1 * metrics.get('free_margin_blocks_60s', 0)
            elif state in (StressState.EMERGENCY, StressState.COOLDOWN):
                # Significant penalty during emergency/cooldown
                penalty = -1.0
                if metrics.get('equity_collapses_total', 0) > 0:
                    penalty += getattr(config, 'PENALTY_EQUITY_COLLAPSE', -50.0) / 10.0  # Spread over steps
        except ImportError:
            pass
        
        return base_reward + penalty


# =============================================================================
# COMPONENT 3: PORTFOLIO GATEKEEPER
# =============================================================================

class PortfolioGatekeeper:
    """
    Enforces portfolio constraints and margin reserves.
    Integrates with StressTracker to gate risky actions.
    """
    
    def __init__(self, stress_tracker: StressTracker, redis_client=None):
        self.stress_tracker = stress_tracker
        self.redis = redis_client
        
        # Load config
        try:
            import config
            self.enabled = getattr(config, 'ENABLE_TRAINER_STRESS_GATING', True)
            self.min_free_margin_ratio = getattr(config, 'MIN_FREE_MARGIN_RATIO', 0.35)
            self.reserved_exit_usd = getattr(config, 'RESERVED_EXIT_USD', 250.0)
            self.reserved_exit_equity_pct = getattr(config, 'RESERVED_EXIT_EQUITY_PCT', 0.25)
        except ImportError:
            self.enabled = True
            self.min_free_margin_ratio = 0.35
            self.reserved_exit_usd = 250.0
            self.reserved_exit_equity_pct = 0.25
        
        logger.info(f"[PORTFOLIO-GATE] Initialized (min_free_margin={self.min_free_margin_ratio}, "
                   f"reserved_exit=${self.reserved_exit_usd})")
    
    def can_open_position(self, account_id: str, equity_usd: float, 
                          free_margin_usd: float, used_margin_usd: float) -> Tuple[bool, str]:
        """
        Check if opening a new position is allowed based on constraints.
        
        Returns:
            (allowed: bool, deny_reason: str)
        """
        if not self.enabled:
            return True, ""
        
        # Check stress state first
        stress_denied, stress_reason = self.stress_tracker.should_deny_open(account_id)
        if stress_denied:
            return False, stress_reason
        
        # Calculate margins
        equity = max(equity_usd, 1.0)
        free_margin_ratio = free_margin_usd / equity if equity > 0 else 0.0
        reserved_exit = max(equity * self.reserved_exit_equity_pct, self.reserved_exit_usd)
        
        # Check minimum free margin ratio
        if free_margin_ratio < self.min_free_margin_ratio:
            return False, f"FREE_MARGIN_RATIO_BLOCK (have {free_margin_ratio:.1%}, need {self.min_free_margin_ratio:.1%})"
        
        # Check reserved exit capital
        if free_margin_usd < reserved_exit:
            return False, f"RESERVED_MARGIN_BLOCK (have ${free_margin_usd:.0f}, need ${reserved_exit:.0f})"
        
        return True, ""
    
    def get_adjusted_position_size(self, account_id: str, equity_usd: float,
                                   free_margin_usd: float, requested_margin: float) -> float:
        """
        Return adjusted position margin that respects reserves.
        May return 0 if no position is allowed.
        """
        if not self.enabled:
            return requested_margin
        
        # Check if opening is allowed at all
        allowed, reason = self.can_open_position(account_id, equity_usd, free_margin_usd, 0.0)
        if not allowed:
            return 0.0
        
        # Calculate available margin after reserves
        reserved_exit = max(equity_usd * self.reserved_exit_equity_pct, self.reserved_exit_usd)
        min_free_after = equity_usd * self.min_free_margin_ratio
        
        available = free_margin_usd - max(reserved_exit, min_free_after)
        available = max(0.0, available)
        
        # Cap requested margin
        return min(requested_margin, available)


# =============================================================================
# COMPONENT 5: RETRO LIQUIDATION PENALTY
# =============================================================================

class RetroLiquidationPenalty:
    """
    Applies decaying penalty for known past liquidation events.
    Loads from a JSON file or Redis key, applies penalty over N steps.
    """
    
    # Known liquidation events (can be loaded from file)
    KNOWN_LIQUIDATIONS = [
        # Format: (timestamp_ms, account_id, symbol, equity_lost_usd)
        # Primary account liquidation - Jan 2026
        {"ts_ms": 1737590400000, "account_id": "primary", "symbol": "MULTIPLE", "equity_lost": 500.0},
        # Asjad account liquidation - Jan 2026
        {"ts_ms": 1737676800000, "account_id": "asjad", "symbol": "MULTIPLE", "equity_lost": 300.0},
    ]
    
    def __init__(self, redis_client=None):
        self.redis = redis_client
        
        # Load config
        try:
            import config
            self.enabled = getattr(config, 'ENABLE_RETRO_LIQUIDATION_PENALTY', True)
            self.decay_steps = getattr(config, 'RETRO_LIQUIDATION_PENALTY_DECAY_STEPS', 10000)
            self.initial_penalty = getattr(config, 'RETRO_LIQUIDATION_PENALTY_INITIAL', -5.0)
        except ImportError:
            self.enabled = True
            self.decay_steps = 10000
            self.initial_penalty = -5.0
        
        # State
        self._step_count = 0
        self._applied_penalty_total = 0.0
        self._liquidation_events = list(self.KNOWN_LIQUIDATIONS)
        
        # Try to load additional events from file
        self._load_from_file()
        
        logger.info(f"[RETRO-LIQ-PENALTY] Initialized with {len(self._liquidation_events)} known events "
                   f"(decay_steps={self.decay_steps}, initial={self.initial_penalty})")
    
    def _load_from_file(self):
        """Load additional liquidation events from JSON file if exists"""
        try:
            path = "data/liquidation_history.json"
            if os.path.exists(path):
                with open(path, 'r') as f:
                    events = json.load(f)
                    self._liquidation_events.extend(events)
                    logger.info(f"[RETRO-LIQ-PENALTY] Loaded {len(events)} events from {path}")
        except Exception as e:
            logger.debug(f"[RETRO-LIQ-PENALTY] No history file: {e}")
    
    def record_liquidation(self, account_id: str, symbol: str, equity_lost: float):
        """Record a new liquidation event for future training runs"""
        event = {
            "ts_ms": int(time.time() * 1000),
            "account_id": account_id,
            "symbol": symbol,
            "equity_lost": equity_lost
        }
        self._liquidation_events.append(event)
        
        # Persist to file
        try:
            os.makedirs("data", exist_ok=True)
            with open("data/liquidation_history.json", 'w') as f:
                json.dump(self._liquidation_events, f, indent=2)
            logger.info(f"[RETRO-LIQ-PENALTY] Recorded new liquidation for {account_id}")
        except Exception as e:
            logger.warning(f"[RETRO-LIQ-PENALTY] Failed to persist: {e}")
    
    def get_penalty(self, account_id: str = None) -> float:
        """
        Get current decaying penalty for past liquidations.
        Penalty decays linearly from initial_penalty to 0 over decay_steps.
        """
        if not self.enabled or self._step_count >= self.decay_steps:
            return 0.0
        
        # Count applicable events
        if account_id:
            n_events = sum(1 for e in self._liquidation_events if e.get('account_id') == account_id)
        else:
            n_events = len(self._liquidation_events)
        
        if n_events == 0:
            return 0.0
        
        # Linear decay
        decay_factor = 1.0 - (self._step_count / self.decay_steps)
        decay_factor = max(0.0, min(1.0, decay_factor))
        
        # Penalty scales with number of events
        penalty = self.initial_penalty * n_events * decay_factor / max(n_events, 1)
        return penalty
    
    def step(self):
        """Increment step counter (call once per training step)"""
        self._step_count += 1
    
    def get_total_applied(self) -> float:
        """Get total penalty applied so far"""
        return self._applied_penalty_total


# =============================================================================
# COMPONENT 6: REWARD INTEGRATOR
# =============================================================================

class LiquidationAwareRewardIntegrator:
    """
    Integrates liquidation prevention signals into RL reward calculation.
    Wraps existing PortfolioAwareRewardFunction to add execution constraint penalties.
    """
    
    def __init__(self, portfolio_reward_fn, stress_tracker: StressTracker,
                 retro_penalty: RetroLiquidationPenalty, redis_client=None):
        self.portfolio_reward_fn = portfolio_reward_fn
        self.stress_tracker = stress_tracker
        self.retro_penalty = retro_penalty
        self.redis = redis_client
        
        # Load config
        try:
            import config
            self.enabled = getattr(config, 'ENABLE_FEEDBACK_FAILURE_PENALTIES', True)
            self.terminal_on_collapse = getattr(config, 'ENABLE_TERMINAL_ON_EQUITY_COLLAPSE', True)
            self.portfolio_aware = getattr(config, 'ENABLE_PORTFOLIO_AWARE_REWARD', True)
            
            # Penalty magnitudes
            self.penalty_free_margin = getattr(config, 'PENALTY_FREE_MARGIN_BLOCK', -0.5)
            self.penalty_margin_cap = getattr(config, 'PENALTY_MARGIN_CAP_BLOCK', -0.3)
            self.penalty_api_2019 = getattr(config, 'PENALTY_INSUFFICIENT_MARGIN_2019', -1.0)
            self.penalty_circuit_breaker = getattr(config, 'PENALTY_CIRCUIT_BREAKER', -2.0)
            self.penalty_equity_collapse = getattr(config, 'PENALTY_EQUITY_COLLAPSE', -50.0)
        except ImportError:
            self.enabled = True
            self.terminal_on_collapse = True
            self.portfolio_aware = True
            self.penalty_free_margin = -0.5
            self.penalty_margin_cap = -0.3
            self.penalty_api_2019 = -1.0
            self.penalty_circuit_breaker = -2.0
            self.penalty_equity_collapse = -50.0
        
        # Tracking
        self._pending_penalties: Dict[str, List[float]] = defaultdict(list)
        self._collapse_flags: Dict[str, bool] = {}
        
        logger.info(f"[REWARD-INTEGRATOR] Initialized (enabled={self.enabled}, "
                   f"terminal_collapse={self.terminal_on_collapse})")
    
    def record_execution_event(self, event: ExecutionEvent):
        """Record an execution event that may trigger penalties"""
        if not self.enabled:
            return
        
        account_id = event.account_id
        reason = event.reason_code
        
        penalty = 0.0
        if reason == 'FREE_MARGIN_BLOCK':
            penalty = self.penalty_free_margin
        elif reason == 'MARGIN_CAP_BLOCK':
            penalty = self.penalty_margin_cap
        elif reason == '-2019':
            penalty = self.penalty_api_2019
        elif reason == 'CIRCUIT_BREAKER':
            penalty = self.penalty_circuit_breaker
        elif reason == 'EQUITY_COLLAPSE':
            penalty = self.penalty_equity_collapse
            self._collapse_flags[account_id] = True
            # Record in retro penalty for future runs
            if self.retro_penalty:
                self.retro_penalty.record_liquidation(
                    account_id=account_id,
                    symbol=event.symbol,
                    equity_lost=event.portfolio.get('equity_usd', 0.0)
                )
        
        if penalty != 0.0:
            self._pending_penalties[account_id].append(penalty)
            logger.debug(f"[REWARD-INTEGRATOR] Queued penalty {penalty} for {account_id} ({reason})")
    
    def calculate_reward(self, base_reward: float, symbol: str, action: int,
                        simulated_pnl: float, account_id: str = "default") -> Tuple[float, bool]:
        """
        Calculate adjusted reward with liquidation prevention penalties.
        
        Returns:
            (adjusted_reward, should_terminate)
        """
        # Start with portfolio-aware reward if available and enabled
        if self.portfolio_aware and self.portfolio_reward_fn:
            try:
                adjusted = self.portfolio_reward_fn.calculate_reward(
                    base_reward=base_reward,
                    symbol=symbol,
                    action=action,
                    simulated_pnl=simulated_pnl
                )
            except Exception as e:
                logger.debug(f"[REWARD-INTEGRATOR] Portfolio reward failed: {e}")
                adjusted = base_reward
        else:
            adjusted = base_reward
        
        # Add stress-state penalty
        if self.stress_tracker:
            adjusted = self.stress_tracker.get_penalty_adjustment(account_id, adjusted)
        
        # Add retro liquidation penalty
        if self.retro_penalty:
            adjusted += self.retro_penalty.get_penalty(account_id)
            self.retro_penalty.step()
        
        # Apply pending event penalties
        if account_id in self._pending_penalties:
            for p in self._pending_penalties[account_id]:
                adjusted += p
            self._pending_penalties[account_id].clear()
        
        # Check for terminal condition (equity collapse)
        should_terminate = False
        if self.terminal_on_collapse and self._collapse_flags.get(account_id, False):
            should_terminate = True
            self._collapse_flags[account_id] = False
            logger.warning(f"[REWARD-INTEGRATOR] Terminal condition: EQUITY_COLLAPSE for {account_id}")
        
        return adjusted, should_terminate


# =============================================================================
# SINGLETON INITIALIZATION
# =============================================================================

_stress_tracker: Optional[StressTracker] = None
_gatekeeper: Optional[PortfolioGatekeeper] = None
_retro_penalty: Optional[RetroLiquidationPenalty] = None
_reward_integrator: Optional[LiquidationAwareRewardIntegrator] = None
_event_publisher: Optional[ExecutionEventPublisher] = None


def initialize_liquidation_prevention(redis_client, portfolio_reward_fn=None):
    """
    Initialize the complete liquidation prevention system.
    Call from trainer during startup.
    
    Returns:
        (stress_tracker, gatekeeper, retro_penalty, reward_integrator, event_publisher)
    """
    global _stress_tracker, _gatekeeper, _retro_penalty, _reward_integrator, _event_publisher
    
    # Create components
    _stress_tracker = StressTracker(redis_client)
    _gatekeeper = PortfolioGatekeeper(_stress_tracker, redis_client)
    _retro_penalty = RetroLiquidationPenalty(redis_client)
    _event_publisher = ExecutionEventPublisher(redis_client)
    
    _reward_integrator = LiquidationAwareRewardIntegrator(
        portfolio_reward_fn=portfolio_reward_fn,
        stress_tracker=_stress_tracker,
        retro_penalty=_retro_penalty,
        redis_client=redis_client
    )
    
    logger.info("🛡️ [LIQ-PREVENTION] Complete liquidation prevention system initialized")
    
    return _stress_tracker, _gatekeeper, _retro_penalty, _reward_integrator, _event_publisher


def get_stress_tracker() -> Optional[StressTracker]:
    return _stress_tracker


def get_gatekeeper() -> Optional[PortfolioGatekeeper]:
    return _gatekeeper


def get_retro_penalty() -> Optional[RetroLiquidationPenalty]:
    return _retro_penalty


def get_reward_integrator() -> Optional[LiquidationAwareRewardIntegrator]:
    return _reward_integrator


def get_event_publisher() -> Optional[ExecutionEventPublisher]:
    return _event_publisher
