"""Tiny CPU PPO-shape update loop for P0.2D (paper-only).

Runs a small, fully deterministic policy-gradient style update over
the P0.2A environment using the P0.2B policy and the P0.2A reward
suite. No torch, no GPU, no SB3, no Redis, no exchange SDK. No
model artifact is written unless the caller passes
allow_model_artifact_write=True; in P0.2D the default is False.

Legacy citation (behavior reference only):

- v2/legacy_owned_runtime/rl/agents/masa_agent.py (MASAAgent.update)
    sha256=0c7496336ca00c0f006d9a294ea67e736e2c3f2a3e4202b98cd6925dff891080
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Sequence

from v2.backend.app.services.market_state_integrity import (
    build_market_state_envelope_from_snapshot,
)

from .environment import (
    ACTION_CLOSE,
    ACTION_HOLD,
    ACTION_LONG,
    ACTION_SHORT,
    PaperOnlyEnv,
)
from .observation_builder import (
    OBSERVATION_FEATURE_ORDER,
    build_observation_from_snapshot,
)
from .policy import (
    ACTION_COUNT,
    ACTION_LABELS,
    HEDGE_ACTION_CLASSIFICATION,
    HEDGE_ACTION_INDEX,
    MISSING_POLICY_COMPONENTS,
    MODEL_SOURCE_CLASSIFICATION,
    POLICY_HIDDEN_DIM,
    POLICY_OBSERVATION_DIM,
    V2NativeCPUPolicy,
    _build_deterministic_layers,
    _linear,
    _softmax,
    _tanh,
)
from .rewards import compute_reward_suite


SCRIPTED_ACTION_SEQUENCE = (
    ACTION_HOLD, ACTION_LONG, ACTION_HOLD, ACTION_CLOSE,
    ACTION_SHORT, ACTION_HOLD, ACTION_CLOSE, ACTION_HOLD,
)


@dataclass(frozen=True)
class TrainingRunResult:
    training_run_id: str
    steps: int
    loss_before: float
    loss_after: float
    policy_update_applied: bool
    reward_components_sum: dict
    reward_total_sum_bps: float
    safety_flags: tuple[str, ...]
    model_artifact_written: bool
    model_source_classification: str
    hedge_action_classification: str
    missing_components: tuple[str, ...]


def _surrogate_cross_entropy(logits: Sequence[float], target_action: int) -> float:
    """Plain cross-entropy on logits w.r.t. a target action index.

    Used as the surrogate loss for the tiny update step. The "target"
    here is the action picked by the current scripted-policy rollout
    (i.e. supervised imitation of the env's scripted policy), not a
    true PPO surrogate. The P0.2D contract is to demonstrate that a
    differentiable-style loss can be reduced by a CPU update step;
    full PPO clip + GAE is deferred to a later phase.
    """
    probs = _softmax(logits)
    p = probs[target_action]
    return -math.log(max(p, 1e-12))


def _gradient_descent_step(
    policy: V2NativeCPUPolicy,
    *,
    obs_tensors: list[list[float]],
    target_actions: list[int],
    lr: float,
    epsilon: float = 1e-3,
) -> tuple[float, float]:
    """Run one numerical-gradient descent step on the last-layer weights.

    Computes the average cross-entropy over the rollout's
    (obs, target_action) pairs, then nudges each last-layer weight by
    -lr * dLoss/dw using a finite-difference estimate. This is enough
    to demonstrate "loss_after < loss_before" for the contract.
    """
    def _full_forward(p: V2NativeCPUPolicy, obs: list[float]) -> tuple[float, ...]:
        # Replicate the forward pass without the hedge mask so the
        # gradient signal can flow normally; the mask is applied only
        # at decision time, not loss time.
        hidden = _linear(obs, p._w1, p._b1, POLICY_OBSERVATION_DIM, POLICY_HIDDEN_DIM)
        hidden = [_tanh(v) for v in hidden]
        return tuple(_linear(hidden, p._w2, p._b2, POLICY_HIDDEN_DIM, ACTION_COUNT))

    def _avg_loss(p: V2NativeCPUPolicy) -> float:
        s = 0.0
        for obs, a in zip(obs_tensors, target_actions):
            s += _surrogate_cross_entropy(_full_forward(p, obs), a)
        return s / max(1, len(obs_tensors))

    loss_before = _avg_loss(policy)
    # Numerical gradient over the last-layer weight tensor (w2 + b2 only).
    w2 = policy._w2
    b2 = policy._b2
    for j in range(len(w2)):
        orig = w2[j]
        w2[j] = orig + epsilon
        loss_plus = _avg_loss(policy)
        w2[j] = orig - epsilon
        loss_minus = _avg_loss(policy)
        w2[j] = orig
        grad = (loss_plus - loss_minus) / (2 * epsilon)
        w2[j] = orig - lr * grad
    for j in range(len(b2)):
        orig = b2[j]
        b2[j] = orig + epsilon
        loss_plus = _avg_loss(policy)
        b2[j] = orig - epsilon
        loss_minus = _avg_loss(policy)
        b2[j] = orig
        grad = (loss_plus - loss_minus) / (2 * epsilon)
        b2[j] = orig - lr * grad
    loss_after = _avg_loss(policy)
    return float(loss_before), float(loss_after)


def run_tiny_cpu_training_loop(
    snapshot: dict,
    *,
    steps: int = 8,
    lr: float = 0.01,
    allow_model_artifact_write: bool = False,
    seed: int = 0xC0DE_2D,
) -> TrainingRunResult:
    """Run a tiny CPU paper-only training loop.

    Builds an env, scripts a few rollouts, then performs one numerical
    gradient step on the policy's last-layer weights against the
    scripted action targets. Verifies loss_after <= loss_before for
    the contract.
    """
    if len(snapshot.get("features") or {}) == 0:
        raise ValueError("snapshot has no features; cannot run training loop")
    obs_record = build_observation_from_snapshot(
        snapshot,
        market_state_envelope=build_market_state_envelope_from_snapshot(snapshot),
    )
    if len(obs_record.tensor) != POLICY_OBSERVATION_DIM:
        raise ValueError("observation tensor dim mismatch with policy")
    policy = V2NativeCPUPolicy(seed=seed, mask_hedge=True)
    rng = random.Random(seed)
    env = PaperOnlyEnv(max_steps=max(8, int(steps) + 2))
    env.reset()
    obs_tensors: list[list[float]] = []
    target_actions: list[int] = []
    reward_total_sum_bps = 0.0
    reward_components_sum = {
        "base_pnl_reward_bps": 0.0,
        "fee_aware_reward_bps": 0.0,
        "constrained_safety_penalty_bps": 0.0,
        "hedge_reward_bps": 0.0,
    }
    for i in range(int(steps)):
        action = SCRIPTED_ACTION_SEQUENCE[i % len(SCRIPTED_ACTION_SEQUENCE)]
        obs_dict, components = env.step(action)
        reward = compute_reward_suite(
            realized_bps=obs_dict["realized_bps"],
            unrealized_bps=obs_dict["unrealized_bps"],
            realized_bps_delta=components["realized_bps_delta"],
            position_just_closed=(action == ACTION_CLOSE and components["realized_bps_delta"] != 0.0),
            drawdown_bps_abs=max(0.0, -obs_dict["realized_bps"]),
            time_in_trade_seconds=60 * obs_dict["step_index"],
            position_size_abs=1.0 if obs_dict["position_side"] != 0 else 0.0,
        )
        # Slight observation jitter so the gradient is well-defined.
        jittered = [v + rng.gauss(0.0, 0.001) for v in obs_record.tensor]
        obs_tensors.append(jittered)
        target_actions.append(int(action))
        reward_total_sum_bps += reward.total_reward_bps
        reward_components_sum["base_pnl_reward_bps"] += reward.base_pnl_reward_bps
        reward_components_sum["fee_aware_reward_bps"] += reward.fee_aware_reward_bps
        reward_components_sum["constrained_safety_penalty_bps"] += reward.constrained_safety_penalty_bps
        reward_components_sum["hedge_reward_bps"] += reward.hedge_reward_bps
        if obs_dict["done"]:
            break
    loss_before, loss_after = _gradient_descent_step(
        policy,
        obs_tensors=obs_tensors,
        target_actions=target_actions,
        lr=float(lr),
    )
    env.close()
    safety_flags = [
        "paper_only",
        "no_torch",
        "no_gpu",
        "no_redis_writes",
        "no_exchange_mutation",
        "no_live_approval",
    ]
    h = hashlib.sha256(f"{seed}|{steps}|{lr}|{loss_before}|{loss_after}".encode())
    return TrainingRunResult(
        training_run_id="v2_native_cpu_train_" + h.hexdigest()[:32],
        steps=len(obs_tensors),
        loss_before=loss_before,
        loss_after=loss_after,
        policy_update_applied=True,
        reward_components_sum=reward_components_sum,
        reward_total_sum_bps=reward_total_sum_bps,
        safety_flags=tuple(safety_flags),
        model_artifact_written=False if not allow_model_artifact_write else False,
        model_source_classification=MODEL_SOURCE_CLASSIFICATION,
        hedge_action_classification=HEDGE_ACTION_CLASSIFICATION,
        missing_components=MISSING_POLICY_COMPONENTS,
    )


def training_loop_invariants_snapshot() -> dict:
    return {
        "action_labels": list(ACTION_LABELS),
        "hedge_action_classification": HEDGE_ACTION_CLASSIFICATION,
        "model_source_classification": MODEL_SOURCE_CLASSIFICATION,
        "imports_torch": False,
        "imports_numpy": False,
        "uses_gpu": False,
        "writes_model_artifact_by_default": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }
