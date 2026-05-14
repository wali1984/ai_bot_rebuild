"""
Fee Ratio Aware Reward Shaping for RL Training
===============================================

Integrates fee ratio awareness into PPO and MASA training to:
1. Penalize rewards when fee ratio is high (teaches model to trade less)
2. Add fee ratio as observation feature (model sees fee state)
3. Shape rewards based on fee efficiency (reward fee-efficient trades)

This helps the model learn that:
- High fee ratios mean trading is unprofitable
- Should reduce trading frequency when fees > profits
- Prioritize higher-quality, longer-hold trades

Usage:
    from rl.fee_ratio_reward_shaping import FeeRatioRewardShaper, get_fee_ratio_features
    
    # In reward calculation:
    shaper = FeeRatioRewardShaper()
    shaped_reward = shaper.shape_reward(base_reward, action_category)
    
    # In observation building:
    fee_features = get_fee_ratio_features()
    obs = np.concatenate([base_obs, fee_features])
"""

import os
import time
import logging
import numpy as np
from typing import Dict, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger("fee_ratio_reward_shaping")

# =============================================================================
# CONFIGURATION - Load from config.py or use defaults
# =============================================================================

try:
    from config import (
        FEE_RATIO_REWARD_SHAPING_ENABLED as _CFG_ENABLED,
        FEE_RATIO_WARNING_THRESHOLD as _CFG_WARNING,
        FEE_RATIO_HIGH_THRESHOLD as _CFG_HIGH,
        FEE_RATIO_CRITICAL_THRESHOLD as _CFG_CRITICAL
    )
    FEE_RATIO_WARNING = _CFG_WARNING
    FEE_RATIO_HIGH = _CFG_HIGH
    FEE_RATIO_CRITICAL = _CFG_CRITICAL
    FEE_RATIO_REWARD_SHAPING_ENABLED = _CFG_ENABLED
except ImportError:
    # Fallback defaults if config not available
    FEE_RATIO_WARNING = float(os.getenv("FEE_RATIO_WARNING", "0.30"))
    FEE_RATIO_HIGH = float(os.getenv("FEE_RATIO_HIGH", "0.50"))
    FEE_RATIO_CRITICAL = float(os.getenv("FEE_RATIO_CRITICAL", "0.80"))
    FEE_RATIO_REWARD_SHAPING_ENABLED = os.getenv("FEE_RATIO_REWARD_SHAPING_ENABLED", "true").lower() in ("1", "true", "yes")

# Additional thresholds
FEE_RATIO_CATASTROPHIC = float(os.getenv("FEE_RATIO_CATASTROPHIC", "1.00"))  # 100% - maximum penalty

# Penalty multipliers for each threshold
FEE_PENALTY_WARNING = float(os.getenv("FEE_PENALTY_WARNING", "0.10"))    # -10% reward
FEE_PENALTY_HIGH = float(os.getenv("FEE_PENALTY_HIGH", "0.25"))          # -25% reward
FEE_PENALTY_CRITICAL = float(os.getenv("FEE_PENALTY_CRITICAL", "0.50"))  # -50% reward
FEE_PENALTY_CATASTROPHIC = float(os.getenv("FEE_PENALTY_CATASTROPHIC", "0.80"))  # -80% reward

# Whether to enable fee ratio reward shaping
FEE_RATIO_REWARD_SHAPING_ENABLED = os.getenv("FEE_RATIO_REWARD_SHAPING_ENABLED", "true").lower() in ("1", "true", "yes")


@dataclass
class FeeRatioState:
    """Current fee ratio state for training"""
    fee_ratio: float
    total_fees: float
    total_realized_pnl: float
    net_pnl: float
    trade_count: int
    is_valid: bool
    last_update: float


class FeeRatioRewardShaper:
    """
    Shapes rewards based on fee ratio to teach model fee awareness.
    
    When fee ratio is high, the model should learn to:
    1. Trade less frequently
    2. Only take high-confidence trades
    3. Hold positions longer
    4. Avoid protective churn (frequent stop adjustments)
    """
    
    def __init__(
        self,
        warning_threshold: float = FEE_RATIO_WARNING,
        high_threshold: float = FEE_RATIO_HIGH,
        critical_threshold: float = FEE_RATIO_CRITICAL,
        catastrophic_threshold: float = FEE_RATIO_CATASTROPHIC,
        enabled: bool = FEE_RATIO_REWARD_SHAPING_ENABLED
    ):
        self.warning_threshold = warning_threshold
        self.high_threshold = high_threshold
        self.critical_threshold = critical_threshold
        self.catastrophic_threshold = catastrophic_threshold
        self.enabled = enabled
        
        # Cache fee ratio state
        self._fee_state: Optional[FeeRatioState] = None
        self._cache_ttl = 300  # 5 minute cache
        
        # Statistics
        self.stats = {
            'total_shaped': 0,
            'penalties_applied': 0,
            'total_penalty_amount': 0.0,
            'by_category': {'OPEN_RISK': 0, 'HEDGE': 0, 'PROTECTIVE': 0}
        }
        
        logger.info(f"FeeRatioRewardShaper initialized: enabled={enabled}, "
                   f"thresholds=[{warning_threshold:.0%}, {high_threshold:.0%}, "
                   f"{critical_threshold:.0%}, {catastrophic_threshold:.0%}]")
    
    def _get_fee_ratio_state(self, force_refresh: bool = False) -> FeeRatioState:
        """Get current fee ratio state, cached for efficiency."""
        now = time.time()
        
        # Use cache if valid
        if (not force_refresh and 
            self._fee_state is not None and 
            now - self._fee_state.last_update < self._cache_ttl):
            return self._fee_state
        
        # Fetch fresh data
        try:
            from trading.fee_ratio_gate import get_fee_ratio_data
            data = get_fee_ratio_data()
            
            if data is None:
                self._fee_state = FeeRatioState(
                    fee_ratio=0.0,
                    total_fees=0.0,
                    total_realized_pnl=0.0,
                    net_pnl=0.0,
                    trade_count=0,
                    is_valid=False,
                    last_update=now
                )
            else:
                self._fee_state = FeeRatioState(
                    fee_ratio=data.fee_ratio,
                    total_fees=data.total_fees,
                    total_realized_pnl=data.total_realized_pnl,
                    net_pnl=data.net_pnl,
                    trade_count=data.trade_count,
                    is_valid=True,
                    last_update=now
                )
        except Exception as e:
            logger.debug(f"Failed to get fee ratio state: {e}")
            self._fee_state = FeeRatioState(
                fee_ratio=0.0,
                total_fees=0.0,
                total_realized_pnl=0.0,
                net_pnl=0.0,
                trade_count=0,
                is_valid=False,
                last_update=now
            )
        
        return self._fee_state
    
    def get_penalty_multiplier(self, fee_ratio: float, action_category: str = "OPEN_RISK") -> Tuple[float, str]:
        """
        Calculate penalty multiplier based on fee ratio and action category.
        
        Args:
            fee_ratio: Current fee/profit ratio (0.0 - 1.0+)
            action_category: OPEN_RISK, HEDGE, or PROTECTIVE
            
        Returns:
            Tuple of (penalty_multiplier, reason)
            - penalty_multiplier: 0.0 to 1.0, where 1.0 = no penalty, 0.2 = 80% penalty
        """
        # PROTECTIVE actions get no fee penalty (exits must always be encouraged)
        if action_category == "PROTECTIVE":
            return 1.0, "PROTECTIVE_NO_PENALTY"
        
        # HEDGE actions get reduced penalty (hedging is risk-reducing)
        hedge_discount = 0.5 if action_category == "HEDGE" else 1.0
        
        # Calculate base penalty
        if fee_ratio >= self.catastrophic_threshold:
            base_penalty = FEE_PENALTY_CATASTROPHIC
            reason = f"CATASTROPHIC_FEE_RATIO ({fee_ratio:.1%})"
        elif fee_ratio >= self.critical_threshold:
            base_penalty = FEE_PENALTY_CRITICAL
            reason = f"CRITICAL_FEE_RATIO ({fee_ratio:.1%})"
        elif fee_ratio >= self.high_threshold:
            base_penalty = FEE_PENALTY_HIGH
            reason = f"HIGH_FEE_RATIO ({fee_ratio:.1%})"
        elif fee_ratio >= self.warning_threshold:
            base_penalty = FEE_PENALTY_WARNING
            reason = f"WARNING_FEE_RATIO ({fee_ratio:.1%})"
        else:
            return 1.0, f"NORMAL_FEE_RATIO ({fee_ratio:.1%})"
        
        # Apply hedge discount
        penalty = base_penalty * hedge_discount
        multiplier = 1.0 - penalty
        
        if action_category == "HEDGE":
            reason += f" (hedge discount: {hedge_discount})"
        
        return max(0.1, multiplier), reason  # Never reduce below 10%
    
    def shape_reward(
        self,
        base_reward: float,
        action_category: str = "OPEN_RISK",
        action_type: str = "unknown",
        trade_executed: bool = True
    ) -> Dict[str, float]:
        """
        Apply fee-ratio-aware reward shaping.
        
        Args:
            base_reward: Original reward from environment
            action_category: OPEN_RISK, HEDGE, or PROTECTIVE
            action_type: open, close, flip, etc.
            trade_executed: Whether a trade was actually executed
            
        Returns:
            Dict with shaped reward and components
        """
        self.stats['total_shaped'] += 1
        
        # Skip shaping if disabled or no trade executed
        if not self.enabled or not trade_executed:
            return {
                'base_reward': float(base_reward),
                'fee_ratio': 0.0,
                'penalty_multiplier': 1.0,
                'penalty_reason': 'SHAPING_DISABLED' if not self.enabled else 'NO_TRADE',
                'shaped_reward': float(base_reward),
                'penalty_applied': 0.0
            }
        
        # Get current fee ratio
        state = self._get_fee_ratio_state()
        
        if not state.is_valid:
            return {
                'base_reward': float(base_reward),
                'fee_ratio': 0.0,
                'penalty_multiplier': 1.0,
                'penalty_reason': 'NO_FEE_DATA',
                'shaped_reward': float(base_reward),
                'penalty_applied': 0.0
            }
        
        # Get penalty multiplier
        multiplier, reason = self.get_penalty_multiplier(state.fee_ratio, action_category)
        
        # Apply penalty to reward
        if base_reward > 0:
            # For positive rewards, reduce by penalty
            shaped_reward = base_reward * multiplier
        else:
            # For negative rewards, DON'T reduce the pain - losses should feel worse
            # when fee ratio is high (teaches model that trading in high-fee state hurts more)
            amplifier = 1.0 + (1.0 - multiplier) * 0.5  # 10-40% amplification
            shaped_reward = base_reward * amplifier
        
        penalty_applied = abs(base_reward - shaped_reward)
        
        # Update stats
        if multiplier < 1.0:
            self.stats['penalties_applied'] += 1
            self.stats['total_penalty_amount'] += penalty_applied
            self.stats['by_category'][action_category] = self.stats['by_category'].get(action_category, 0) + 1
        
        return {
            'base_reward': float(base_reward),
            'fee_ratio': float(state.fee_ratio),
            'penalty_multiplier': float(multiplier),
            'penalty_reason': reason,
            'shaped_reward': float(shaped_reward),
            'penalty_applied': float(penalty_applied),
            'total_fees': float(state.total_fees),
            'net_pnl': float(state.net_pnl),
            'trade_count': int(state.trade_count)
        }
    
    def get_statistics(self) -> Dict:
        """Get shaping statistics for monitoring."""
        total = max(1, self.stats['total_shaped'])
        return {
            **self.stats,
            'penalty_rate': self.stats['penalties_applied'] / total,
            'avg_penalty': self.stats['total_penalty_amount'] / max(1, self.stats['penalties_applied'])
        }


def get_fee_ratio_features(normalize: bool = True) -> np.ndarray:
    """
    Get fee ratio features for observation space.
    
    Returns 4 features:
    1. fee_ratio: Current fee/profit ratio (0.0-2.0 normalized)
    2. fee_state: Discrete state (0=low, 0.5=medium, 1.0=high, 1.5=critical)
    3. net_efficiency: Net PnL efficiency (-1 to 1)
    4. trade_intensity: Trade count normalized (0-1)
    
    Args:
        normalize: Whether to normalize features to [-1, 1] range
        
    Returns:
        np.ndarray of shape (4,) with fee ratio features
    """
    try:
        from trading.fee_ratio_gate import get_fee_ratio_data
        data = get_fee_ratio_data()
        
        if data is None:
            return np.zeros(4, dtype=np.float32)
        
        # Feature 1: Fee ratio (capped at 2.0 for normalization)
        fee_ratio = min(2.0, data.fee_ratio) if normalize else data.fee_ratio
        
        # Feature 2: Discrete fee state
        if data.fee_ratio >= 1.0:
            fee_state = 1.5  # Critical
        elif data.fee_ratio >= 0.5:
            fee_state = 1.0  # High
        elif data.fee_ratio >= 0.3:
            fee_state = 0.5  # Medium
        else:
            fee_state = 0.0  # Low
        
        # Feature 3: Net efficiency (how much of gross profits we keep)
        if abs(data.total_realized_pnl) > 0.01:
            net_efficiency = data.net_pnl / abs(data.total_realized_pnl)
            net_efficiency = np.clip(net_efficiency, -1.0, 1.0)
        else:
            net_efficiency = 0.0
        
        # Feature 4: Trade intensity (normalized by expected trades per day)
        expected_trades_per_day = 50  # Reasonable baseline
        trade_intensity = min(1.0, data.trade_count / expected_trades_per_day)
        
        features = np.array([
            fee_ratio,
            fee_state,
            net_efficiency,
            trade_intensity
        ], dtype=np.float32)
        
        return features
        
    except Exception as e:
        logger.debug(f"Failed to get fee ratio features: {e}")
        return np.zeros(4, dtype=np.float32)


class FeeAwareMASAWrapper:
    """
    Wrapper for MASA agent that incorporates fee ratio awareness.
    
    Modifies action logits based on fee ratio:
    - When fee ratio is high, reduce confidence in OPEN_RISK actions
    - When fee ratio is low, normal operation
    """
    
    def __init__(self, masa_agent, fee_penalty_scale: float = 0.5):
        """
        Args:
            masa_agent: The underlying MASA agent
            fee_penalty_scale: How much to penalize action logits (0.0-1.0)
        """
        self.agent = masa_agent
        self.fee_penalty_scale = fee_penalty_scale
        self._shaper = FeeRatioRewardShaper()
        
        logger.info(f"FeeAwareMASAWrapper initialized with penalty_scale={fee_penalty_scale}")
    
    def get_action_and_value(self, obs, **kwargs):
        """
        Get action and value, adjusting logits based on fee ratio.
        
        When fee ratio is high:
        - Reduce logits for OPEN actions (index 0 and 2 typically)
        - Keep HOLD logits unchanged (index 1 typically)
        """
        import torch
        
        # Get base action logits and value
        action_logits, value, is_valid = self.agent.get_action_and_value(obs, **kwargs)
        
        # Get fee ratio state
        state = self._shaper._get_fee_ratio_state()
        
        if not state.is_valid or state.fee_ratio < FEE_RATIO_WARNING:
            # Normal operation when fee ratio is low
            return action_logits, value, is_valid
        
        # Adjust logits based on fee ratio
        # Typically: action 0 = OPEN_SHORT, action 1 = HOLD, action 2 = OPEN_LONG
        # We want to reduce confidence in action 0 and 2 (opening positions)
        
        # Calculate penalty
        if state.fee_ratio >= FEE_RATIO_CRITICAL:
            penalty = 2.0 * self.fee_penalty_scale  # Strong penalty
        elif state.fee_ratio >= FEE_RATIO_HIGH:
            penalty = 1.0 * self.fee_penalty_scale  # Moderate penalty
        else:
            penalty = 0.5 * self.fee_penalty_scale  # Mild penalty
        
        # Apply penalty to non-HOLD actions
        # This makes HOLD more likely when fee ratio is high
        adjusted_logits = action_logits.clone()
        
        # Reduce logits for opening actions (typically indices 0 and 2)
        if action_logits.shape[-1] >= 3:
            adjusted_logits[..., 0] -= penalty  # OPEN_SHORT
            adjusted_logits[..., 2] -= penalty  # OPEN_LONG
        
        logger.debug(f"[FEE_AWARE_MASA] Applied penalty={penalty:.2f} for fee_ratio={state.fee_ratio:.1%}")
        
        return adjusted_logits, value, is_valid
    
    def __getattr__(self, name):
        """Forward other attributes to the underlying agent."""
        return getattr(self.agent, name)


def integrate_fee_ratio_into_reward(
    base_reward: float,
    action_category: str,
    trade_executed: bool = True,
    shaper: Optional[FeeRatioRewardShaper] = None
) -> float:
    """
    Convenience function to integrate fee ratio shaping into existing reward calculations.
    
    Args:
        base_reward: Original reward
        action_category: OPEN_RISK, HEDGE, or PROTECTIVE
        trade_executed: Whether a trade was executed
        shaper: Optional existing shaper instance
        
    Returns:
        Shaped reward incorporating fee ratio awareness
    """
    if shaper is None:
        shaper = FeeRatioRewardShaper()
    
    result = shaper.shape_reward(
        base_reward=base_reward,
        action_category=action_category,
        trade_executed=trade_executed
    )
    
    return result['shaped_reward']


# =============================================================================
# SINGLETON INSTANCES
# =============================================================================

_global_shaper: Optional[FeeRatioRewardShaper] = None

def get_fee_ratio_shaper() -> FeeRatioRewardShaper:
    """Get singleton fee ratio shaper instance."""
    global _global_shaper
    if _global_shaper is None:
        _global_shaper = FeeRatioRewardShaper()
    return _global_shaper


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("FEE RATIO REWARD SHAPING TEST")
    print("=" * 70)
    
    shaper = FeeRatioRewardShaper()
    
    # Test different scenarios
    test_cases = [
        {"base_reward": 1.0, "action_category": "OPEN_RISK", "desc": "Positive OPEN_RISK"},
        {"base_reward": -0.5, "action_category": "OPEN_RISK", "desc": "Negative OPEN_RISK"},
        {"base_reward": 1.0, "action_category": "HEDGE", "desc": "Positive HEDGE"},
        {"base_reward": 1.0, "action_category": "PROTECTIVE", "desc": "Positive PROTECTIVE"},
    ]
    
    for tc in test_cases:
        result = shaper.shape_reward(
            base_reward=tc['base_reward'],
            action_category=tc['action_category']
        )
        print(f"\n{tc['desc']}:")
        print(f"  Base: {result['base_reward']:.3f} → Shaped: {result['shaped_reward']:.3f}")
        print(f"  Fee Ratio: {result['fee_ratio']:.1%}, Multiplier: {result['penalty_multiplier']:.2f}")
        print(f"  Reason: {result['penalty_reason']}")
    
    print("\n" + "=" * 70)
    print("Fee Ratio Features:")
    features = get_fee_ratio_features()
    print(f"  fee_ratio: {features[0]:.3f}")
    print(f"  fee_state: {features[1]:.1f}")
    print(f"  net_efficiency: {features[2]:.3f}")
    print(f"  trade_intensity: {features[3]:.3f}")
    
    print("\n" + "=" * 70)
    print("✅ Test complete!")
