"""V2 native RL policy CPU forward pass (P0.2B)."""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Sequence

LEGACY_SOURCES = {
    "rl/agents/masa_agent.py": {
        "sha256": "0c7496336ca00c0f006d9a294ea67e736e2c3f2a3e4202b98cd6925dff891080",
        "size_bytes": 21109,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/agents/masa_agent.py",
    },
    "rl/enhanced_architectures.py": {
        "sha256": "d7b2071a6c83edee5eb940d50e5578fb0b4dd14d54f9e577c65d2533409b8236",
        "size_bytes": 23252,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/enhanced_architectures.py",
    },
    "rl/gpu_cnn_policy.py": {
        "sha256": "881cfdad7650e9114e14c24a8d3d7bc2cbb5a4c1ce2a5fa8cb3fe2d50d3b4062",
        "size_bytes": 7843,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/gpu_cnn_policy.py",
    },
    "rl/hybrid_action_space.py": {
        "sha256": "abc7ecf1e655e4a018eeedcb4ad675c7bb35e101d4b5a42d432132243aed6c23",
        "size_bytes": 16553,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/hybrid_action_space.py",
    },
}

ACTION_LABELS = ("hold", "long", "short", "close", "hedge")
ACTION_COUNT = len(ACTION_LABELS)
HEDGE_ACTION_CLASSIFICATION = "FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE"
HEDGE_ACTION_INDEX = 4
POLICY_OBSERVATION_DIM = 26
POLICY_HIDDEN_DIM = 16
POLICY_SCHEMA_VERSION = "v2_native_policy_cpu_forward_v1"
MODEL_SOURCE_CLASSIFICATION = "V2_NATIVE_CPU_DETERMINISTIC_INIT_NO_CHECKPOINT"

MISSING_POLICY_COMPONENTS = (
    "ppo_clip_loss_MISSING_IN_P0_2B",
    "value_function_head_MISSING_IN_P0_2B",
    "gae_advantage_estimation_MISSING_IN_P0_2B",
    "lagrangian_safety_constraint_MISSING_IN_P0_2B",
    "checkpoint_weight_loading_DEFERRED_TO_P0_2C",
    "cpu_training_loop_DEFERRED_TO_P0_2D",
    "gpu_training_parity_DEFERRED_TO_P0_2E",
)


@dataclass(frozen=True)
class PolicyForwardResult:
    policy_id: str
    observation_feature_snapshot_id: str
    action_logits: tuple[float, ...]
    action_probabilities: tuple[float, ...]
    action_labels: tuple[str, ...]
    selected_action: str
    selected_action_index: int
    expected_move_bps_head: float | None
    model_source_classification: str
    hedge_action_classification: str
    missing_policy_components: tuple[str, ...]
    schema_version: str = POLICY_SCHEMA_VERSION


def _seeded_weights(seed: int, n: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0, 0.25) for _ in range(n)]


def _tanh(x: float) -> float:
    return math.tanh(x)


def _softmax(xs: Sequence[float]) -> list[float]:
    if not xs:
        return []
    m = max(xs)
    exps = [math.exp(x - m) for x in xs]
    s = sum(exps)
    return [e / s for e in exps] if s > 0 else [1.0 / len(xs)] * len(xs)


def _policy_id_from_weights(w1: list[float], b1: list[float], w2: list[float], b2: list[float]) -> str:
    h = hashlib.sha256()
    for arr in (w1, b1, w2, b2):
        for v in arr:
            h.update(f"{v:.12f}|".encode("utf-8"))
    return "v2_native_policy_cpu_" + h.hexdigest()[:32]


def _build_deterministic_layers(seed: int = 0xC0DE_2B):
    n_w1 = POLICY_OBSERVATION_DIM * POLICY_HIDDEN_DIM
    n_b1 = POLICY_HIDDEN_DIM
    n_w2 = POLICY_HIDDEN_DIM * ACTION_COUNT
    n_b2 = ACTION_COUNT
    n_w_exp = POLICY_HIDDEN_DIM
    n_b_exp = 1
    w1 = _seeded_weights(seed, n_w1)
    b1 = _seeded_weights(seed + 1, n_b1)
    w2 = _seeded_weights(seed + 2, n_w2)
    b2 = _seeded_weights(seed + 3, n_b2)
    w_exp = _seeded_weights(seed + 4, n_w_exp)
    b_exp = _seeded_weights(seed + 5, n_b_exp)
    return w1, b1, w2, b2, w_exp, b_exp


def _linear(x: Sequence[float], w: Sequence[float], b: Sequence[float], in_dim: int, out_dim: int) -> list[float]:
    out: list[float] = []
    for j in range(out_dim):
        acc = b[j]
        for i in range(in_dim):
            acc += x[i] * w[j * in_dim + i]
        out.append(acc)
    return out


class V2NativeCPUPolicy:
    def __init__(self, *, seed: int = 0xC0DE_2B, mask_hedge: bool = True) -> None:
        self._seed = seed
        self._mask_hedge = bool(mask_hedge)
        (
            self._w1,
            self._b1,
            self._w2,
            self._b2,
            self._w_exp,
            self._b_exp,
        ) = _build_deterministic_layers(seed)
        self._policy_id = _policy_id_from_weights(self._w1, self._b1, self._w2, self._b2)

    @property
    def policy_id(self) -> str:
        return self._policy_id

    def forward(self, observation_tensor: Sequence[float], *, feature_snapshot_id: str = "") -> PolicyForwardResult:
        if len(observation_tensor) != POLICY_OBSERVATION_DIM:
            raise ValueError(
                f"observation_tensor must have {POLICY_OBSERVATION_DIM} values, "
                f"got {len(observation_tensor)}"
            )
        x = [float(v) for v in observation_tensor]
        hidden = _linear(x, self._w1, self._b1, POLICY_OBSERVATION_DIM, POLICY_HIDDEN_DIM)
        hidden = [_tanh(v) for v in hidden]
        logits = _linear(hidden, self._w2, self._b2, POLICY_HIDDEN_DIM, ACTION_COUNT)
        if self._mask_hedge:
            logits = list(logits)
            logits[HEDGE_ACTION_INDEX] = -1e9
        probs = _softmax(logits)
        sel_idx = max(range(ACTION_COUNT), key=lambda i: logits[i])
        sel_label = ACTION_LABELS[sel_idx]
        exp_raw = _linear(hidden, self._w_exp, self._b_exp, POLICY_HIDDEN_DIM, 1)[0]
        expected_move_bps_head = 200.0 * _tanh(exp_raw)
        return PolicyForwardResult(
            policy_id=self._policy_id,
            observation_feature_snapshot_id=str(feature_snapshot_id),
            action_logits=tuple(float(v) for v in logits),
            action_probabilities=tuple(float(v) for v in probs),
            action_labels=ACTION_LABELS,
            selected_action=sel_label,
            selected_action_index=sel_idx,
            expected_move_bps_head=float(expected_move_bps_head),
            model_source_classification=MODEL_SOURCE_CLASSIFICATION,
            hedge_action_classification=HEDGE_ACTION_CLASSIFICATION,
            missing_policy_components=MISSING_POLICY_COMPONENTS,
        )


def policy_invariants_snapshot() -> dict:
    return {
        "policy_schema_version": POLICY_SCHEMA_VERSION,
        "action_labels": list(ACTION_LABELS),
        "hedge_action_classification": HEDGE_ACTION_CLASSIFICATION,
        "model_source_classification": MODEL_SOURCE_CLASSIFICATION,
        "missing_policy_components": list(MISSING_POLICY_COMPONENTS),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "imports_torch": False,
        "imports_numpy": False,
        "imports_stable_baselines3": False,
        "imports_gymnasium": False,
        "imports_redis": False,
        "imports_exchange_sdk": False,
        "loads_checkpoint_weights": False,
        "places_exchange_orders": False,
        "writes_legacy_redis": False,
        "legacy_behavior_mapping": LEGACY_SOURCES,
    }
