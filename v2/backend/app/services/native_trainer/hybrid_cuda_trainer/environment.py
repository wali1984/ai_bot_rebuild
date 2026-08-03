"""V2 paper/shadow Gymnasium-compatible hybrid environment."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from .config import ACTION_LABELS, LIVE_GATE_BLOCKED
from .rewards import compute_hybrid_reward
from .tensor_builder import FeatureTensorRecord


@dataclass
class V2PaperShadowHybridEnv:
    """Minimal Gymnasium-style environment with the legacy 7-action contract."""

    examples: Sequence[Any]
    fee_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 1.0
    max_steps: int | None = None
    cursor: int = field(default=0, init=False)
    position_side: int = field(default=0, init=False)
    entry_edge_bps: float = field(default=0.0, init=False)
    realized_bps: float = field(default=0.0, init=False)
    action_history: list[int] = field(default_factory=list, init=False)

    action_labels: tuple[str, ...] = ACTION_LABELS

    def _example(self) -> Any:
        if not self.examples:
            raise RuntimeError("environment has no training examples")
        return self.examples[min(self.cursor, len(self.examples) - 1)]

    def _tensor(self, example: Any) -> FeatureTensorRecord:
        return example.tensor if hasattr(example, "tensor") else example

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        del seed, options
        self.cursor = 0
        self.position_side = 0
        self.entry_edge_bps = 0.0
        self.realized_bps = 0.0
        self.action_history = []
        tensor = self._tensor(self._example())
        return list(tensor.model_vector), {
            "lineage": self._lineage(tensor),
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        }

    def step(self, action: int):
        if action < 0 or action >= len(ACTION_LABELS):
            raise ValueError(f"unknown action index: {action}")
        ex = self._example()
        tensor = self._tensor(ex)
        label = ACTION_LABELS[action]
        expected = float(getattr(ex, "label_expected_move_after_cost_bps", 0.0))
        reward_realized = 0.0
        if label == "long" and self.position_side == 0:
            self.position_side = 1
            self.entry_edge_bps = expected
        elif label == "short" and self.position_side == 0:
            self.position_side = -1
            self.entry_edge_bps = expected
        elif label == "close_long" and self.position_side == 1:
            reward_realized = self.entry_edge_bps - 2 * (self.fee_bps_per_side + self.slippage_bps_per_side)
            self.realized_bps += reward_realized
            self.position_side = 0
        elif label == "close_short" and self.position_side == -1:
            reward_realized = -self.entry_edge_bps - 2 * (self.fee_bps_per_side + self.slippage_bps_per_side)
            self.realized_bps += reward_realized
            self.position_side = 0
        elif label == "reduce" and self.position_side != 0:
            reward_realized = 0.5 * self.entry_edge_bps * self.position_side
            self.realized_bps += reward_realized
        elif label == "hedge_reserved_fail_closed":
            reward_realized = -2.0

        self.action_history.append(action)
        churn = sum(1 for a in self.action_history[-5:] if ACTION_LABELS[a] != "hold")
        reward = compute_hybrid_reward(
            selected_action=label,
            expected_move_after_cost_bps=expected,
            realized_after_cost_bps=reward_realized if reward_realized else expected,
            fee_bps_per_side=self.fee_bps_per_side,
            slippage_bps_per_side=self.slippage_bps_per_side,
            drawdown_bps_abs=max(0.0, -self.realized_bps),
            churn_count=max(0, churn - 2),
            liquidation_risk_score=self._liquidation_risk(tensor),
            risk_constraint_violated=False,
        )
        self.cursor += 1
        max_steps = self.max_steps if self.max_steps is not None else len(self.examples)
        terminated = self.cursor >= len(self.examples)
        truncated = self.cursor >= max_steps
        next_tensor = self._tensor(self._example())
        info = {
            "lineage": self._lineage(tensor),
            "action_label": label,
            "reward_breakdown": reward.to_jsonable(),
            "position_side": self.position_side,
            "paper_fill_only": True,
            "exchange_mutation": False,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        }
        return list(next_tensor.model_vector), float(reward.total_reward_bps), bool(terminated), bool(truncated), info

    @staticmethod
    def _liquidation_risk(tensor: FeatureTensorRecord) -> float:
        values = dict(zip(tensor.feature_names, tensor.values))
        distance = values.get("liquidation_level_distance_bps")
        if distance is None or distance <= 0.0:
            return 0.0
        return float(max(0.0, min(1.0, math.exp(-abs(distance) / 100.0))))

    @staticmethod
    def _lineage(tensor: FeatureTensorRecord) -> dict[str, Any]:
        return {
            "tensor_id": tensor.tensor_id,
            "feature_snapshot_id": tensor.feature_snapshot_id,
            "symbol": tensor.symbol,
            "timeframe": tensor.timeframe,
            "data_coverage_percent": tensor.data_coverage_percent,
            "missing_feature_count": len(tensor.missing_feature_names),
            "stale_feature_count": len(tensor.stale_feature_names),
        }
