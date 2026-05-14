"""
7-Action Hedge-Aware Reward Function
Enhanced reward system for 7-action hedge trading with momentum and exhaustion signals

DEPRECATED (2026-02-28): This module is DEAD CODE — never imported by gpu_environment.py
or hybrid_trainer.py. Reward shaping is handled directly in:
  - gpu_environment.py: _execute_trades_gpu_7action() (training rewards)
  - config.py: RL_HOLD_FLAT_PENALTY, RL_PROFITABLE_CLOSE_BONUS, RL_LOSS_PENALTY_MULT, etc.

Uses a DIFFERENT action space mapping (0=OPEN_LONG) than the canonical ontology (0=HOLD).
DO NOT import without updating the action mapping first.
"""

import numpy as np
import logging
from typing import Dict, Optional, List, Tuple
from enum import Enum
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class HedgeAction(Enum):
    """7-action enum for hedge-capable trading"""
    OPEN_LONG = 0
    OPEN_SHORT = 1
    INCREASE_LONG = 2
    INCREASE_SHORT = 3
    DECREASE_LONG = 4
    DECREASE_SHORT = 5
    CLOSE_ALL = 6


@dataclass
class ActionContext:
    """Context for action evaluation"""
    action: HedgeAction
    symbol: str
    size_pct: float
    leverage: float
    confidence: float
    momentum_signal: float
    exhaustion_signal: float
    existing_long_qty: float
    existing_short_qty: float
    portfolio_exposure: float


class HedgeRewardCalculator:
    """
    Advanced reward calculator for 7-action hedge trading system.
    
    Rewards:
    - Opening into momentum (OPEN_LONG on uptrend, OPEN_SHORT on downtrend)
    - Partial sizing on favorable moves (INCREASE_* when profitable)
    - Closing into exhaustion (CLOSE_ALL when momentum exhausted)
    
    Penalties:
    - Thrashing (frequent position changes)
    - Over-sizing (position too large for signal strength)
    - Wrong-direction opens (OPEN_LONG on downtrend)
    """
    
    def __init__(
        self,
        momentum_reward_scale: float = 2.0,
        partial_reward_scale: float = 1.5,
        exhaustion_reward_scale: float = 1.8,
        thrashing_penalty_scale: float = -1.0,
        sizing_penalty_scale: float = -0.5,
        direction_penalty_scale: float = -1.5,
        min_hold_minutes: int = 20
    ):
        """
        Initialize hedge reward calculator.
        
        Args:
            momentum_reward_scale: Reward multiplier for opening into momentum
            partial_reward_scale: Reward multiplier for smart partial sizing
            exhaustion_reward_scale: Reward multiplier for closing into exhaustion
            thrashing_penalty_scale: Penalty for frequent position changes
            sizing_penalty_scale: Penalty for over-sizing relative to signal strength
            direction_penalty_scale: Penalty for counter-momentum opens
            min_hold_minutes: Minimum hold time before position changes
        """
        self.momentum_reward_scale = momentum_reward_scale
        self.partial_reward_scale = partial_reward_scale
        self.exhaustion_reward_scale = exhaustion_reward_scale
        self.thrashing_penalty_scale = thrashing_penalty_scale
        self.sizing_penalty_scale = sizing_penalty_scale
        self.direction_penalty_scale = direction_penalty_scale
        self.min_hold_minutes = min_hold_minutes
        
        # Track action history for thrashing detection
        self.action_history = deque(maxlen=10)
        self.position_changes = deque(maxlen=20)
        self.last_action_time = {}  # symbol -> timestamp
        
        logger.info("HedgeRewardCalculator initialized for 7-action system")
    
    def calculate_hedge_reward(
        self,
        action_context: ActionContext,
        base_pnl_reward: float,
        timestamp: Optional[float] = None
    ) -> Dict[str, float]:
        """
        Calculate reward components for hedge action.
        
        Args:
            action_context: Full context for action evaluation
            base_pnl_reward: Base PnL-based reward from traditional calculator
            timestamp: Action timestamp for thrashing detection
            
        Returns:
            Dictionary with reward components and total hedge reward
        """
        reward_components = {
            'base_pnl': base_pnl_reward,
            'momentum_bonus': 0.0,
            'partial_bonus': 0.0,
            'exhaustion_bonus': 0.0,
            'thrashing_penalty': 0.0,
            'sizing_penalty': 0.0,
            'direction_penalty': 0.0,
            'hedge_reward': 0.0
        }
        
        # 1. Momentum alignment reward
        momentum_bonus = self._calculate_momentum_reward(action_context)
        reward_components['momentum_bonus'] = momentum_bonus
        
        # 2. Partial sizing reward
        partial_bonus = self._calculate_partial_reward(action_context)
        reward_components['partial_bonus'] = partial_bonus
        
        # 3. Exhaustion timing reward
        exhaustion_bonus = self._calculate_exhaustion_reward(action_context)
        reward_components['exhaustion_bonus'] = exhaustion_bonus
        
        # 4. Thrashing penalty
        thrashing_penalty = self._calculate_thrashing_penalty(
            action_context, timestamp
        )
        reward_components['thrashing_penalty'] = thrashing_penalty
        
        # 5. Sizing appropriateness penalty
        sizing_penalty = self._calculate_sizing_penalty(action_context)
        reward_components['sizing_penalty'] = sizing_penalty
        
        # 6. Direction alignment penalty
        direction_penalty = self._calculate_direction_penalty(action_context)
        reward_components['direction_penalty'] = direction_penalty
        
        # Combine hedge-specific components
        hedge_reward = (
            momentum_bonus +
            partial_bonus +
            exhaustion_bonus +
            thrashing_penalty +
            sizing_penalty +
            direction_penalty
        )
        
        reward_components['hedge_reward'] = hedge_reward
        reward_components['total_reward'] = base_pnl_reward + hedge_reward
        
        # Record action for thrashing detection
        self._record_action(action_context, timestamp)
        
        return reward_components
    
    def _calculate_momentum_reward(self, ctx: ActionContext) -> float:
        """
        Reward for opening positions aligned with momentum.
        
        High reward for:
        - OPEN_LONG when momentum_signal > 0.5
        - OPEN_SHORT when momentum_signal < -0.5
        """
        if ctx.action not in [HedgeAction.OPEN_LONG, HedgeAction.OPEN_SHORT]:
            return 0.0
        
        # Momentum alignment strength
        momentum_strength = abs(ctx.momentum_signal)
        
        # Check alignment
        if ctx.action == HedgeAction.OPEN_LONG:
            alignment = max(0, ctx.momentum_signal)  # Positive momentum
        else:  # OPEN_SHORT
            alignment = max(0, -ctx.momentum_signal)  # Negative momentum
        
        # Reward = signal strength × alignment × confidence × scale
        momentum_reward = (
            momentum_strength * 
            alignment * 
            ctx.confidence * 
            self.momentum_reward_scale
        )
        
        return momentum_reward
    
    def _calculate_partial_reward(self, ctx: ActionContext) -> float:
        """
        Reward for smart partial position sizing.
        
        High reward for:
        - INCREASE_LONG when long position is profitable and momentum continues
        - DECREASE_LONG when momentum weakening but still positive
        """
        if ctx.action not in [
            HedgeAction.INCREASE_LONG, HedgeAction.INCREASE_SHORT,
            HedgeAction.DECREASE_LONG, HedgeAction.DECREASE_SHORT
        ]:
            return 0.0
        
        # Check if we have existing position to modify
        if ctx.action in [HedgeAction.INCREASE_LONG, HedgeAction.DECREASE_LONG]:
            existing_qty = ctx.existing_long_qty
            direction_signal = ctx.momentum_signal
        else:
            existing_qty = ctx.existing_short_qty
            direction_signal = -ctx.momentum_signal
        
        if existing_qty <= 0:
            return 0.0  # No position to modify
        
        # Reward smart partial sizing
        if ctx.action in [HedgeAction.INCREASE_LONG, HedgeAction.INCREASE_SHORT]:
            # Increasing position - reward if momentum continues
            partial_reward = max(0, direction_signal) * ctx.confidence
        else:
            # Decreasing position - reward if momentum weakening
            momentum_weakness = max(0, 0.3 - abs(direction_signal))
            partial_reward = momentum_weakness * ctx.confidence
        
        return partial_reward * self.partial_reward_scale
    
    def _calculate_exhaustion_reward(self, ctx: ActionContext) -> float:
        """
        Reward for closing positions when momentum is exhausted.
        
        High reward for CLOSE_ALL when:
        - High exhaustion signal (momentum reversal likely)
        - Existing positions that could be at risk
        """
        if ctx.action != HedgeAction.CLOSE_ALL:
            return 0.0
        
        # Check if we have positions to close
        total_exposure = abs(ctx.existing_long_qty) + abs(ctx.existing_short_qty)
        if total_exposure <= 0:
            return -0.1  # Small penalty for unnecessary CLOSE_ALL
        
        # Reward based on exhaustion signal strength
        exhaustion_strength = max(0, ctx.exhaustion_signal)
        
        # Bonus if we have significant exposure during exhaustion
        exposure_factor = min(1.0, total_exposure / 0.1)  # Normalize to 10% exposure
        
        exhaustion_reward = (
            exhaustion_strength * 
            exposure_factor * 
            ctx.confidence * 
            self.exhaustion_reward_scale
        )
        
        return exhaustion_reward
    
    def _calculate_thrashing_penalty(
        self, 
        ctx: ActionContext, 
        timestamp: Optional[float]
    ) -> float:
        """
        Penalize frequent position changes (thrashing).
        
        Penalty increases with:
        - Multiple position changes within min_hold_minutes
        - Rapid action-counteraction cycles
        """
        if timestamp is None:
            return 0.0
        
        symbol = ctx.symbol
        
        # Check time since last action on this symbol
        if symbol in self.last_action_time:
            time_since_last = timestamp - self.last_action_time[symbol]
            minutes_since_last = time_since_last / 60.0
            
            if minutes_since_last < self.min_hold_minutes:
                # Penalty for too-frequent changes
                time_violation = (self.min_hold_minutes - minutes_since_last) / self.min_hold_minutes
                thrashing_penalty = time_violation * self.thrashing_penalty_scale
                return thrashing_penalty
        
        return 0.0
    
    def _calculate_sizing_penalty(self, ctx: ActionContext) -> float:
        """
        Penalize position sizing inappropriate for signal strength.
        
        Penalty for:
        - Large position size with low confidence
        - Large position size with weak signals
        """
        # Skip if not position-changing action
        if ctx.action in [HedgeAction.CLOSE_ALL]:
            return 0.0
        
        # Signal strength (combination of momentum and confidence)
        signal_strength = (abs(ctx.momentum_signal) + ctx.confidence) / 2.0
        
        # Position size appropriateness
        appropriate_size = signal_strength * 0.08  # Max 8% at full signal
        size_excess = max(0, ctx.size_pct - appropriate_size)
        
        # Penalty for over-sizing
        sizing_penalty = size_excess * 10.0 * self.sizing_penalty_scale  # Scale up penalty
        
        return sizing_penalty
    
    def _calculate_direction_penalty(self, ctx: ActionContext) -> float:
        """
        Penalize opening positions against momentum.
        
        Strong penalty for:
        - OPEN_LONG when momentum_signal < -0.3
        - OPEN_SHORT when momentum_signal > 0.3
        """
        if ctx.action not in [HedgeAction.OPEN_LONG, HedgeAction.OPEN_SHORT]:
            return 0.0
        
        # Check direction alignment
        if ctx.action == HedgeAction.OPEN_LONG:
            if ctx.momentum_signal < -0.3:  # Opening long against downtrend
                misalignment = abs(ctx.momentum_signal + 0.3)
                return misalignment * self.direction_penalty_scale
        else:  # OPEN_SHORT
            if ctx.momentum_signal > 0.3:  # Opening short against uptrend
                misalignment = abs(ctx.momentum_signal - 0.3)
                return misalignment * self.direction_penalty_scale
        
        return 0.0
    
    def _record_action(self, ctx: ActionContext, timestamp: Optional[float]):
        """Record action for thrashing detection"""
        if timestamp is not None:
            self.last_action_time[ctx.symbol] = timestamp
            
        action_record = {
            'symbol': ctx.symbol,
            'action': ctx.action,
            'timestamp': timestamp,
            'size': ctx.size_pct
        }
        
        self.action_history.append(action_record)
        
        # Track position changes
        if ctx.action != HedgeAction.CLOSE_ALL:
            self.position_changes.append(action_record)
    
    def get_reward_summary(self) -> Dict[str, float]:
        """Get summary statistics of recent rewards"""
        # Count actions in recent history
        action_counts = {}
        for record in self.action_history:
            action_name = record['action'].name
            action_counts[action_name] = action_counts.get(action_name, 0) + 1
        
        return {
            'total_actions': len(self.action_history),
            'position_changes': len(self.position_changes),
            'action_distribution': action_counts,
            'thrashing_potential': len(self.position_changes) / max(1, len(self.action_history))
        }


def create_hedge_reward_function(config: Dict = None) -> HedgeRewardCalculator:
    """
    Factory function to create configured hedge reward calculator.
    
    Args:
        config: Configuration dict with reward parameters
        
    Returns:
        Configured HedgeRewardCalculator
    """
    if config is None:
        config = {}
    
    return HedgeRewardCalculator(
        momentum_reward_scale=config.get('momentum_reward_scale', 2.0),
        partial_reward_scale=config.get('partial_reward_scale', 1.5),
        exhaustion_reward_scale=config.get('exhaustion_reward_scale', 1.8),
        thrashing_penalty_scale=config.get('thrashing_penalty_scale', -1.0),
        sizing_penalty_scale=config.get('sizing_penalty_scale', -0.5),
        direction_penalty_scale=config.get('direction_penalty_scale', -1.5),
        min_hold_minutes=config.get('min_hold_minutes', 20)
    )


if __name__ == "__main__":
    # Test the hedge reward calculator
    logging.basicConfig(level=logging.INFO)
    
    calc = HedgeRewardCalculator()
    
    # Test momentum reward (good case)
    ctx_good = ActionContext(
        action=HedgeAction.OPEN_LONG,
        symbol="BTCUSDT",
        size_pct=0.05,
        leverage=3.0,
        confidence=0.85,
        momentum_signal=0.7,  # Strong uptrend
        exhaustion_signal=0.1,
        existing_long_qty=0.0,
        existing_short_qty=0.0,
        portfolio_exposure=0.15
    )
    
    good_rewards = calc.calculate_hedge_reward(ctx_good, base_pnl_reward=0.02)
    print("🟢 Good momentum alignment rewards:")
    for component, value in good_rewards.items():
        if value != 0:
            print(f"  {component}: {value:.4f}")
    
    # Test direction penalty (bad case)
    ctx_bad = ActionContext(
        action=HedgeAction.OPEN_LONG,
        symbol="ETHUSDT",
        size_pct=0.08,
        leverage=5.0,
        confidence=0.6,
        momentum_signal=-0.6,  # Strong downtrend - wrong direction!
        exhaustion_signal=0.2,
        existing_long_qty=0.0,
        existing_short_qty=0.0,
        portfolio_exposure=0.25
    )
    
    bad_rewards = calc.calculate_hedge_reward(ctx_bad, base_pnl_reward=0.01)
    print("\n🔴 Bad direction alignment penalties:")
    for component, value in bad_rewards.items():
        if value != 0:
            print(f"  {component}: {value:.4f}")
    
    print(f"\n📊 Reward Summary: {calc.get_reward_summary()}")