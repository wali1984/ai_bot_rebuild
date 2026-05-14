"""
Constrained RL — Lagrangian Reward Shaping

Wraps the existing AdvancedRewardCalculator with Lagrangian constraint penalties:
  • Liquidation buffer constraint:  liq_distance > CRL_LIQ_BUFFER_MIN_PCT
  • Margin utilisation constraint:   margin_util < CRL_MARGIN_UTIL_MAX_PCT
  • Drawdown constraint:             drawdown < CRL_DRAWDOWN_MAX_PCT
  • Transaction cost penalty:        penalise excessive fees/slippage

Each constraint has an auto-tuning Lagrangian multiplier (λ) that increases when
the constraint is violated and decreases when satisfied, driving the policy to
naturally respect risk boundaries without hard-coding them.

Integration:
  - Wraps reward computation in the training loop
  - Called after base reward computed, before feeding to PPO
  - Multiplier state persists across training loops via checkpoint
"""

import logging
import time
import numpy as np
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


class ConstraintTracker:
    """Tracks a single constraint's violation history and auto-tunes its multiplier."""
    
    def __init__(
        self,
        name: str,
        threshold: float,
        direction: str = "max",  # "max" = value should be < threshold, "min" = value should be > threshold
        lambda_init: float = 0.1,
        lambda_lr: float = 0.001,
        lambda_max: float = 10.0,
    ):
        self.name = name
        self.threshold = threshold
        self.direction = direction
        self.lam = lambda_init
        self.lambda_lr = lambda_lr
        self.lambda_max = lambda_max
        
        # Statistics
        self.violation_count = 0
        self.total_count = 0
        self._violation_window = []
        self._window_size = 100
    
    def compute_penalty(self, value: float) -> float:
        """Compute penalty for current constraint value.
        
        Returns: penalty (>0 if violated, 0 if satisfied)
        """
        self.total_count += 1
        
        if self.direction == "max":
            # Value should be below threshold
            violation = max(0.0, value - self.threshold)
        else:
            # Value should be above threshold
            violation = max(0.0, self.threshold - value)
        
        is_violated = violation > 0
        self._violation_window.append(1.0 if is_violated else 0.0)
        if len(self._violation_window) > self._window_size:
            self._violation_window.pop(0)
        
        if is_violated:
            self.violation_count += 1
        
        # Update Lagrangian multiplier
        # λ increases when violated, decreases when satisfied
        if is_violated:
            self.lam = min(self.lambda_max, self.lam + self.lambda_lr * violation)
        else:
            self.lam = max(0.0, self.lam - self.lambda_lr * 0.1)
        
        return self.lam * violation
    
    @property
    def violation_rate(self) -> float:
        if not self._violation_window:
            return 0.0
        return np.mean(self._violation_window)
    
    def state_dict(self) -> dict:
        return {
            "name": self.name,
            "lam": self.lam,
            "violation_count": self.violation_count,
            "total_count": self.total_count,
        }
    
    def load_state_dict(self, state: dict) -> None:
        self.lam = state.get("lam", self.lam)
        self.violation_count = state.get("violation_count", 0)
        self.total_count = state.get("total_count", 0)


class ConstrainedRewardShaper:
    """Lagrangian-constrained reward shaping for RL training.
    
    Augments the base reward with soft penalty terms for risk constraint violations.
    The Lagrangian multipliers auto-tune to make the policy naturally respect limits.
    """
    
    def __init__(
        self,
        liq_buffer_min_pct: float = 5.0,
        margin_util_max_pct: float = 30.0,
        drawdown_max_pct: float = 5.0,
        lambda_lr: float = 0.001,
        lambda_init: float = 0.1,
        lambda_max: float = 10.0,
        cost_penalty_weight: float = 0.3,
    ):
        # Constraint trackers
        self.constraints = {
            "liq_buffer": ConstraintTracker(
                name="liq_buffer",
                threshold=liq_buffer_min_pct,
                direction="min",  # liq distance should be ABOVE threshold
                lambda_init=lambda_init,
                lambda_lr=lambda_lr,
                lambda_max=lambda_max,
            ),
            "margin_util": ConstraintTracker(
                name="margin_util",
                threshold=margin_util_max_pct,
                direction="max",  # margin util should be BELOW threshold
                lambda_init=lambda_init,
                lambda_lr=lambda_lr,
                lambda_max=lambda_max,
            ),
            "drawdown": ConstraintTracker(
                name="drawdown",
                threshold=drawdown_max_pct,
                direction="max",  # drawdown should be BELOW threshold
                lambda_init=lambda_init,
                lambda_lr=lambda_lr,
                lambda_max=lambda_max,
            ),
        }
        
        self.cost_penalty_weight = cost_penalty_weight
        self._last_log_ts = 0.0
        
        logger.info(
            f"[CRL] Initialized: liq_min={liq_buffer_min_pct}%, "
            f"margin_max={margin_util_max_pct}%, dd_max={drawdown_max_pct}%, "
            f"cost_weight={cost_penalty_weight}"
        )
    
    def shape_reward(
        self,
        base_reward: float,
        liq_distance_pct: Optional[float] = None,
        margin_util_pct: Optional[float] = None,
        drawdown_pct: Optional[float] = None,
        fees_usd: float = 0.0,
        slippage_bps: float = 0.0,
        notional_usd: float = 0.0,
    ) -> Tuple[float, Dict[str, float]]:
        """Apply Lagrangian constraint penalties to base reward.
        
        Args:
            base_reward: Original reward from AdvancedRewardCalculator
            liq_distance_pct: Current liquidation distance (%)
            margin_util_pct: Current margin utilisation (%)
            drawdown_pct: Current portfolio drawdown (%)
            fees_usd: Transaction fees incurred
            slippage_bps: Observed slippage in basis points
            notional_usd: Trade notional for fee normalization
        
        Returns:
            shaped_reward: Reward after constraint penalties
            breakdown: Dict of individual penalty components
        """
        total_penalty = 0.0
        breakdown = {"base_reward": base_reward}
        
        # Liquidation buffer constraint
        if liq_distance_pct is not None:
            penalty = self.constraints["liq_buffer"].compute_penalty(liq_distance_pct)
            total_penalty += penalty
            breakdown["liq_buffer_penalty"] = penalty
            breakdown["liq_buffer_lambda"] = self.constraints["liq_buffer"].lam
        
        # Margin utilisation constraint
        if margin_util_pct is not None:
            penalty = self.constraints["margin_util"].compute_penalty(margin_util_pct)
            total_penalty += penalty
            breakdown["margin_util_penalty"] = penalty
            breakdown["margin_util_lambda"] = self.constraints["margin_util"].lam
        
        # Drawdown constraint
        if drawdown_pct is not None:
            penalty = self.constraints["drawdown"].compute_penalty(drawdown_pct)
            total_penalty += penalty
            breakdown["drawdown_penalty"] = penalty
            breakdown["drawdown_lambda"] = self.constraints["drawdown"].lam
        
        # Transaction cost penalty
        cost_penalty = 0.0
        if notional_usd > 0:
            fee_ratio = fees_usd / notional_usd
            slip_ratio = slippage_bps / 10_000.0
            cost_penalty = self.cost_penalty_weight * (fee_ratio + slip_ratio)
        total_penalty += cost_penalty
        breakdown["cost_penalty"] = cost_penalty
        
        shaped_reward = base_reward - total_penalty
        breakdown["total_penalty"] = total_penalty
        breakdown["shaped_reward"] = shaped_reward
        
        # Throttled logging
        now = time.time()
        if now - self._last_log_ts > 120:
            self._last_log_ts = now
            rates = {
                name: f"{ct.violation_rate*100:.1f}%"
                for name, ct in self.constraints.items()
            }
            lambdas = {
                name: f"{ct.lam:.4f}"
                for name, ct in self.constraints.items()
            }
            logger.info(
                f"[CRL] Violation rates: {rates} | Lambdas: {lambdas} | "
                f"Last penalty={total_penalty:.4f}"
            )
        
        return shaped_reward, breakdown
    
    def shape_reward_batch(
        self,
        base_rewards: np.ndarray,
        liq_distances: Optional[np.ndarray] = None,
        margin_utils: Optional[np.ndarray] = None,
        drawdowns: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, Dict[str, float]]:
        """Vectorised reward shaping for batch training.
        
        Args:
            base_rewards: (N,) array of base rewards
            liq_distances: (N,) array of liq distances (or None)
            margin_utils: (N,) array of margin utilisation (or None)
            drawdowns: (N,) array of drawdowns (or None)
        
        Returns:
            shaped: (N,) array of shaped rewards
            stats: dict with aggregated stats
        """
        N = len(base_rewards)
        penalties = np.zeros(N, dtype=np.float32)
        
        for i in range(N):
            liq = float(liq_distances[i]) if liq_distances is not None else None
            mu = float(margin_utils[i]) if margin_utils is not None else None
            dd = float(drawdowns[i]) if drawdowns is not None else None
            
            _, breakdown = self.shape_reward(
                float(base_rewards[i]),
                liq_distance_pct=liq,
                margin_util_pct=mu,
                drawdown_pct=dd,
            )
            penalties[i] = breakdown.get("total_penalty", 0.0)
        
        shaped = base_rewards - penalties
        stats = {
            "mean_penalty": float(penalties.mean()),
            "max_penalty": float(penalties.max()),
            "mean_shaped_reward": float(shaped.mean()),
        }
        
        return shaped, stats
    
    def state_dict(self) -> dict:
        return {
            name: ct.state_dict() for name, ct in self.constraints.items()
        }
    
    def load_state_dict(self, state: dict) -> None:
        for name, ct_state in state.items():
            if name in self.constraints:
                self.constraints[name].load_state_dict(ct_state)
        logger.info("[CRL] State dict loaded")
