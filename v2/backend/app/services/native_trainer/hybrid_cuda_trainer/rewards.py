"""Reward stack for V2 paper/shadow hybrid RL training."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class HybridRewardBreakdown:
    after_cost_return_bps: float
    fee_penalty_bps: float
    slippage_penalty_bps: float
    drawdown_penalty_bps: float
    churn_penalty_bps: float
    no_trade_correct_credit_bps: float
    false_positive_penalty_bps: float
    false_negative_penalty_bps: float
    liquidation_regime_penalty_bps: float
    risk_constraint_penalty_bps: float
    total_reward_bps: float

    def to_jsonable(self) -> dict:
        return asdict(self)


def compute_hybrid_reward(
    *,
    selected_action: str,
    expected_move_after_cost_bps: float,
    realized_after_cost_bps: float = 0.0,
    fee_bps_per_side: float = 5.0,
    slippage_bps_per_side: float = 1.0,
    drawdown_bps_abs: float = 0.0,
    churn_count: int = 0,
    liquidation_risk_score: float = 0.0,
    risk_constraint_violated: bool = False,
) -> HybridRewardBreakdown:
    """Compute a shaped reward with explicit cost and risk components."""

    action_is_trade = selected_action in {
        "long",
        "short",
        "close_long",
        "close_short",
        "reduce",
    }
    no_trade = selected_action == "hold"
    after_cost = float(realized_after_cost_bps or expected_move_after_cost_bps)
    fee_penalty = -float(fee_bps_per_side) * (2.0 if action_is_trade else 0.0)
    slippage_penalty = -float(slippage_bps_per_side) * (2.0 if action_is_trade else 0.0)
    drawdown_penalty = -max(0.0, float(drawdown_bps_abs) - 100.0) * 0.25
    churn_penalty = -max(0, int(churn_count)) * 1.5
    no_trade_correct_credit = 2.0 if no_trade and abs(expected_move_after_cost_bps) < 4.0 else 0.0
    false_positive_penalty = -8.0 if action_is_trade and expected_move_after_cost_bps < 0.0 else 0.0
    false_negative_penalty = -5.0 if no_trade and abs(expected_move_after_cost_bps) >= 8.0 else 0.0
    liquidation_penalty = -max(0.0, min(1.0, float(liquidation_risk_score))) * 6.0
    risk_penalty = -20.0 if risk_constraint_violated else 0.0
    total = (
        after_cost
        + fee_penalty
        + slippage_penalty
        + drawdown_penalty
        + churn_penalty
        + no_trade_correct_credit
        + false_positive_penalty
        + false_negative_penalty
        + liquidation_penalty
        + risk_penalty
    )
    total = max(-1000.0, min(1000.0, total))
    return HybridRewardBreakdown(
        after_cost_return_bps=float(after_cost),
        fee_penalty_bps=float(fee_penalty),
        slippage_penalty_bps=float(slippage_penalty),
        drawdown_penalty_bps=float(drawdown_penalty),
        churn_penalty_bps=float(churn_penalty),
        no_trade_correct_credit_bps=float(no_trade_correct_credit),
        false_positive_penalty_bps=float(false_positive_penalty),
        false_negative_penalty_bps=float(false_negative_penalty),
        liquidation_regime_penalty_bps=float(liquidation_penalty),
        risk_constraint_penalty_bps=float(risk_penalty),
        total_reward_bps=float(total),
    )


def reward_stack_status() -> dict:
    return {
        "after_cost_return": True,
        "fee_penalty": True,
        "slippage_penalty": True,
        "drawdown_penalty": True,
        "churn_penalty": True,
        "no_trade_correct_credit": True,
        "false_positive_penalty": True,
        "false_negative_penalty": True,
        "liquidation_regime_awareness": True,
        "risk_constraint_penalty": True,
        "paper_shadow_only": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
