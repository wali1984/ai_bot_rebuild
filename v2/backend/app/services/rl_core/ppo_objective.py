"""PPO clipped surrogate objective (P0.2G).

Pure stdlib implementation of the PPO loss components:

- ratio = exp(new_log_prob - old_log_prob)
- clipped policy loss
- value loss (mse against returns)
- entropy bonus
- safety penalty integration (paper-only constrained reward)

No torch import at module level. No Redis. No exchange SDK.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

PPO_OBJECTIVE_SCHEMA_VERSION = "v2_native_ppo_objective_v1"
DEFAULT_CLIP_EPSILON = 0.2
DEFAULT_VALUE_LOSS_COEF = 0.5
DEFAULT_ENTROPY_COEF = 0.01
DEFAULT_SAFETY_PENALTY_COEF = 0.1


@dataclass(frozen=True)
class PPOLossBreakdown:
    policy_loss: float
    value_loss: float
    entropy_bonus: float
    safety_penalty: float
    total_loss: float
    ratio_mean: float
    ratio_clipped_fraction: float
    sample_count: int
    schema_version: str = PPO_OBJECTIVE_SCHEMA_VERSION


def ratio(new_log_prob: float, old_log_prob: float) -> float:
    return math.exp(float(new_log_prob) - float(old_log_prob))


def clipped_policy_loss_per_sample(
    *,
    r: float,
    advantage: float,
    clip_epsilon: float = DEFAULT_CLIP_EPSILON,
) -> tuple[float, bool]:
    """Returns (policy_loss_contribution, clipped_flag).

    PPO clip: L = -min(r * A, clip(r, 1-eps, 1+eps) * A).
    The negative sign converts the surrogate into a loss to minimize.
    """
    if clip_epsilon < 0:
        raise ValueError("clip_epsilon must be >= 0")
    lo = 1.0 - clip_epsilon
    hi = 1.0 + clip_epsilon
    r_clipped = min(hi, max(lo, r))
    unclipped = r * advantage
    clipped = r_clipped * advantage
    sel = min(unclipped, clipped)
    clipped_flag = (r > hi or r < lo)
    return -float(sel), bool(clipped_flag)


def mean_squared_value_loss(
    *, values_pred: Sequence[float], returns: Sequence[float]
) -> float:
    if len(values_pred) != len(returns):
        raise ValueError("values_pred and returns must be same length")
    if not values_pred:
        return 0.0
    s = 0.0
    for vp, r in zip(values_pred, returns):
        d = float(vp) - float(r)
        s += d * d
    return s / len(values_pred)


def discrete_entropy_per_sample(probs: Sequence[float]) -> float:
    """Shannon entropy in nats for a discrete distribution."""
    total = 0.0
    for p in probs:
        if p <= 0.0:
            continue
        total -= p * math.log(p)
    return float(total)


def mean_discrete_entropy(prob_rows: Sequence[Sequence[float]]) -> float:
    if not prob_rows:
        return 0.0
    s = 0.0
    for row in prob_rows:
        s += discrete_entropy_per_sample(row)
    return s / len(prob_rows)


def safety_penalty_mean(safety_penalties_bps: Sequence[float]) -> float:
    """Mean safety penalty (already negative when violations present).

    The PPO loss adds -safety_coef * penalty, so a more-negative penalty
    becomes a more-positive loss contribution. We normalize by 1e4 bps
    to keep magnitude comparable to value-loss scale.
    """
    if not safety_penalties_bps:
        return 0.0
    s = sum(float(p) for p in safety_penalties_bps)
    return s / len(safety_penalties_bps) / 1e4


def compute_ppo_loss(
    *,
    new_log_probs: Sequence[float],
    old_log_probs: Sequence[float],
    advantages: Sequence[float],
    values_pred: Sequence[float],
    returns: Sequence[float],
    action_prob_rows: Sequence[Sequence[float]],
    safety_penalties_bps: Sequence[float],
    clip_epsilon: float = DEFAULT_CLIP_EPSILON,
    value_loss_coef: float = DEFAULT_VALUE_LOSS_COEF,
    entropy_coef: float = DEFAULT_ENTROPY_COEF,
    safety_penalty_coef: float = DEFAULT_SAFETY_PENALTY_COEF,
) -> PPOLossBreakdown:
    n = len(new_log_probs)
    if n == 0:
        raise ValueError("ppo loss requires at least one sample")
    if not (n == len(old_log_probs) == len(advantages) == len(values_pred)
            == len(returns) == len(action_prob_rows)):
        raise ValueError("input sequence lengths must match")
    policy_total = 0.0
    clipped_count = 0
    ratio_sum = 0.0
    for i in range(n):
        r = ratio(new_log_probs[i], old_log_probs[i])
        ratio_sum += r
        pl, was_clipped = clipped_policy_loss_per_sample(
            r=r, advantage=float(advantages[i]), clip_epsilon=clip_epsilon
        )
        policy_total += pl
        if was_clipped:
            clipped_count += 1
    policy_loss = policy_total / n
    value_loss = mean_squared_value_loss(values_pred=values_pred, returns=returns)
    entropy_bonus = mean_discrete_entropy(action_prob_rows)
    safety_penalty = safety_penalty_mean(safety_penalties_bps)
    total = (
        policy_loss
        + value_loss_coef * value_loss
        - entropy_coef * entropy_bonus
        - safety_penalty_coef * safety_penalty
    )
    return PPOLossBreakdown(
        policy_loss=float(policy_loss),
        value_loss=float(value_loss),
        entropy_bonus=float(entropy_bonus),
        safety_penalty=float(safety_penalty),
        total_loss=float(total),
        ratio_mean=float(ratio_sum / n),
        ratio_clipped_fraction=float(clipped_count / n),
        sample_count=int(n),
    )


def ppo_objective_invariants_snapshot() -> dict:
    return {
        "schema_version": PPO_OBJECTIVE_SCHEMA_VERSION,
        "default_clip_epsilon": DEFAULT_CLIP_EPSILON,
        "default_value_loss_coef": DEFAULT_VALUE_LOSS_COEF,
        "default_entropy_coef": DEFAULT_ENTROPY_COEF,
        "default_safety_penalty_coef": DEFAULT_SAFETY_PENALTY_COEF,
        "imports_torch": False,
        "imports_numpy": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }
