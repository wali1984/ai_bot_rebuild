"""Generalized Advantage Estimation (P0.2G).

Pure stdlib GAE-Lambda implementation.

Definitions:

    delta_t   = r_t + gamma * V_{t+1} * (1 - done_t) - V_t
    A_t       = delta_t + gamma * lambda * (1 - done_t) * A_{t+1}
    returns_t = A_t + V_t

Done-mask handling: when done_t is truthy, the bootstrap from V_{t+1}
is zeroed AND the advantage propagation from A_{t+1} is zeroed. The
last bootstrap value is provided via the ``last_value`` argument.

Advantage normalization is an optional post-pass (subtract mean,
divide by std + eps) controlled by ``normalize_advantages``.

No torch import at module level. No Redis. No exchange SDK.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

GAE_SCHEMA_VERSION = "v2_native_gae_v1"
DEFAULT_GAMMA = 0.99
DEFAULT_LAMBDA = 0.95


@dataclass(frozen=True)
class GAEResult:
    advantages: tuple[float, ...]
    returns: tuple[float, ...]
    advantage_mean: float
    advantage_std: float
    normalized: bool
    gamma: float
    lam: float
    schema_version: str = GAE_SCHEMA_VERSION


def compute_gae(
    *,
    rewards: Sequence[float],
    values: Sequence[float],
    dones: Sequence[int | bool],
    last_value: float = 0.0,
    gamma: float = DEFAULT_GAMMA,
    lam: float = DEFAULT_LAMBDA,
    normalize_advantages: bool = False,
    norm_eps: float = 1e-8,
) -> GAEResult:
    """Compute GAE advantages and returns.

    ``rewards``, ``values``, and ``dones`` must have the same length.
    ``last_value`` is the bootstrap V_{T} after the final step.
    """
    n = len(rewards)
    if n == 0:
        raise ValueError("rewards must be non-empty")
    if not (n == len(values) == len(dones)):
        raise ValueError("rewards/values/dones must have equal length")
    if gamma < 0 or gamma > 1.0:
        raise ValueError("gamma must be in [0, 1]")
    if lam < 0 or lam > 1.0:
        raise ValueError("lam must be in [0, 1]")

    advantages = [0.0] * n
    next_value = float(last_value)
    next_adv = 0.0
    for t in reversed(range(n)):
        done_t = 1.0 if bool(dones[t]) else 0.0
        v_t = float(values[t])
        r_t = float(rewards[t])
        delta = r_t + gamma * next_value * (1.0 - done_t) - v_t
        adv = delta + gamma * lam * (1.0 - done_t) * next_adv
        advantages[t] = adv
        next_value = v_t
        next_adv = adv

    returns = [advantages[t] + float(values[t]) for t in range(n)]

    mean = sum(advantages) / n
    var = sum((a - mean) ** 2 for a in advantages) / n
    std = math.sqrt(var)

    if normalize_advantages and std > 0.0:
        normed = [(a - mean) / (std + norm_eps) for a in advantages]
        return GAEResult(
            advantages=tuple(normed),
            returns=tuple(returns),
            advantage_mean=0.0,
            advantage_std=1.0,
            normalized=True,
            gamma=float(gamma),
            lam=float(lam),
        )

    return GAEResult(
        advantages=tuple(advantages),
        returns=tuple(returns),
        advantage_mean=float(mean),
        advantage_std=float(std),
        normalized=False,
        gamma=float(gamma),
        lam=float(lam),
    )


def gae_invariants_snapshot() -> dict:
    return {
        "schema_version": GAE_SCHEMA_VERSION,
        "default_gamma": DEFAULT_GAMMA,
        "default_lambda": DEFAULT_LAMBDA,
        "imports_torch": False,
        "imports_numpy": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }
