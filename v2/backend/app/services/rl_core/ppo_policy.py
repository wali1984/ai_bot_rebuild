"""PPO-shape policy wrapper for P0.2B (paper-only).

Mirrors the legacy HybridPPO predict/forward surface in plain Python.
No torch, no SB3, no GPU, no checkpoint claim. Wraps V2NativeCPUPolicy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .policy import (
    ACTION_LABELS,
    HEDGE_ACTION_CLASSIFICATION,
    MISSING_POLICY_COMPONENTS,
    MODEL_SOURCE_CLASSIFICATION,
    PolicyForwardResult,
    V2NativeCPUPolicy,
)

LEGACY_ENHANCED_ARCH_SHA256 = "d7b2071a6c83edee5eb940d50e5578fb0b4dd14d54f9e577c65d2533409b8236"
LEGACY_GPU_CNN_POLICY_SHA256 = "881cfdad7650e9114e14c24a8d3d7bc2cbb5a4c1ce2a5fa8cb3fe2d50d3b4062"


@dataclass(frozen=True)
class PPOPredictResult:
    selected_action: str
    selected_action_index: int
    action_logits: tuple[float, ...]
    action_probabilities: tuple[float, ...]
    log_prob_selected: float
    expected_move_bps_head: float
    policy_id: str
    feature_snapshot_id: str
    hedge_action_classification: str
    model_source_classification: str
    missing_policy_components: tuple[str, ...]
    deterministic: bool


class V2NativePPOPolicy:
    """Paper-only PPO policy wrapper around the V2 native CPU policy."""

    def __init__(self, *, policy: V2NativeCPUPolicy | None = None) -> None:
        self._policy = policy or V2NativeCPUPolicy()

    @property
    def policy_id(self) -> str:
        return self._policy.policy_id

    def predict(
        self,
        observation_tensor: Sequence[float],
        *,
        deterministic: bool = True,
        feature_snapshot_id: str = "",
    ) -> PPOPredictResult:
        fr: PolicyForwardResult = self._policy.forward(
            observation_tensor, feature_snapshot_id=feature_snapshot_id
        )
        import math

        sel_idx = fr.selected_action_index
        p_sel = fr.action_probabilities[sel_idx]
        log_prob = math.log(max(p_sel, 1e-12))
        return PPOPredictResult(
            selected_action=fr.selected_action,
            selected_action_index=sel_idx,
            action_logits=fr.action_logits,
            action_probabilities=fr.action_probabilities,
            log_prob_selected=float(log_prob),
            expected_move_bps_head=float(fr.expected_move_bps_head or 0.0),
            policy_id=fr.policy_id,
            feature_snapshot_id=fr.observation_feature_snapshot_id,
            hedge_action_classification=fr.hedge_action_classification,
            model_source_classification=fr.model_source_classification,
            missing_policy_components=fr.missing_policy_components,
            deterministic=bool(deterministic),
        )


def ppo_invariants_snapshot() -> dict:
    return {
        "action_labels": list(ACTION_LABELS),
        "hedge_action_classification": HEDGE_ACTION_CLASSIFICATION,
        "model_source_classification": MODEL_SOURCE_CLASSIFICATION,
        "missing_policy_components": list(MISSING_POLICY_COMPONENTS),
        "legacy_enhanced_architectures_sha256": LEGACY_ENHANCED_ARCH_SHA256,
        "legacy_gpu_cnn_policy_sha256": LEGACY_GPU_CNN_POLICY_SHA256,
        "imports_torch": False,
        "imports_numpy": False,
        "imports_stable_baselines3": False,
        "loads_checkpoint_weights": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
