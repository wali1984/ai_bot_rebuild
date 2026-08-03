"""V2 Native Reward Suite (P0.2A).

Combines:

- base PnL reward (realized_bps + unrealized_bps with discount)
- fee-aware reward (fee penalty + fee/expected_move shaping)
- constrained/safety penalty reward (drawdown, max position, time-in-trade)
- hedge reward placeholder: FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE

The hedge component is intentionally inert. Live hedge construction
remains blocked until the paper hedge engine is ported.

Legacy behavior sources consulted (read-only mirrors under
v2/legacy_owned_runtime/):

- rl/reward_functions.py
    sha256=87ef4602012cbbd944bdf506fb8f1646375e7732c3a93e87b0946db7a1cca853
    size=31805
- rl/constrained_reward.py
    sha256=69ff3c75b53d8d3d7844894954cf9d16f334e79e0c1bd39e9624a4482a459b2e
    size=10861
- rl/fee_ratio_reward_shaping.py
    sha256=e7edce3e29a6bf7236329245ba4a14436dc6f6b0a249ad0ad3d05760570bfc06
    size=19427
- rl/hedge_reward_functions.py
    sha256=54c1a5748ca61da84d3e697cf5260251f15cc802281c951f18b902bf522b41c9
    size=16526

Safety: pure stdlib; no torch, no Redis, no exchange SDK.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

LEGACY_SOURCES = {
    "rl/reward_functions.py": {
        "sha256": "87ef4602012cbbd944bdf506fb8f1646375e7732c3a93e87b0946db7a1cca853",
        "size_bytes": 31805,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/reward_functions.py",
    },
    "rl/constrained_reward.py": {
        "sha256": "69ff3c75b53d8d3d7844894954cf9d16f334e79e0c1bd39e9624a4482a459b2e",
        "size_bytes": 10861,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/constrained_reward.py",
    },
    "rl/fee_ratio_reward_shaping.py": {
        "sha256": "e7edce3e29a6bf7236329245ba4a14436dc6f6b0a249ad0ad3d05760570bfc06",
        "size_bytes": 19427,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/fee_ratio_reward_shaping.py",
    },
    "rl/hedge_reward_functions.py": {
        "sha256": "54c1a5748ca61da84d3e697cf5260251f15cc802281c951f18b902bf522b41c9",
        "size_bytes": 16526,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/hedge_reward_functions.py",
    },
}

HEDGE_REWARD_CLASSIFICATION = "FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE"


@dataclass(frozen=True)
class RewardComponents:
    base_pnl_reward_bps: float
    fee_aware_reward_bps: float
    constrained_safety_penalty_bps: float
    hedge_reward_bps: float
    hedge_reward_classification: str
    total_reward_bps: float
    clamped: bool


def base_pnl_reward(realized_bps: float, unrealized_bps: float, *,
                    unrealized_discount: float = 0.5) -> float:
    """Base reward: full credit for realized PnL, discounted credit for
    unrealized PnL while the position remains open.
    """
    return float(realized_bps) + float(unrealized_bps) * float(unrealized_discount)


def fee_aware_reward(*, realized_bps_delta: float, fee_bps_per_side: float,
                     slippage_bps_per_side: float, expected_move_after_cost_bps: float | None,
                     position_just_closed: bool, max_ratio: float = 0.5) -> float:
    """Fee-aware shaping.

    - Subtracts round-trip cost when a position just closed.
    - Adds a small penalty when fee_bps / |expected_move_after_cost_bps|
      exceeds max_ratio.
    """
    score = float(realized_bps_delta)
    if position_just_closed:
        score -= 2.0 * (float(fee_bps_per_side) + float(slippage_bps_per_side))
    if expected_move_after_cost_bps is not None and abs(expected_move_after_cost_bps) > 0:
        ratio = (fee_bps_per_side + slippage_bps_per_side) / abs(expected_move_after_cost_bps)
        if ratio > max_ratio:
            score -= 5.0 * (ratio - max_ratio)
    return score


def constrained_safety_penalty(*, drawdown_bps_abs: float, max_drawdown_bps: float,
                               time_in_trade_seconds: int, max_time_in_trade_seconds: int,
                               position_size_abs: float, max_position_size: float) -> float:
    """Returns a NEGATIVE bps penalty. Larger violations = larger negative.

    - drawdown over max_drawdown_bps: linear penalty.
    - time-in-trade over max: linear penalty.
    - position size over max: linear penalty.
    """
    penalty = 0.0
    if drawdown_bps_abs > max_drawdown_bps:
        penalty -= (drawdown_bps_abs - max_drawdown_bps)
    if time_in_trade_seconds > max_time_in_trade_seconds:
        penalty -= (time_in_trade_seconds - max_time_in_trade_seconds) * 0.01
    if position_size_abs > max_position_size:
        penalty -= (position_size_abs - max_position_size) * 0.5
    return float(penalty)


def hedge_reward_placeholder() -> tuple[float, str]:
    """Inert until the paper hedge engine is ported.

    Returns (reward_bps=0.0, classification='FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE').
    """
    return 0.0, HEDGE_REWARD_CLASSIFICATION


def compute_reward_suite(*,
                         realized_bps: float,
                         unrealized_bps: float,
                         realized_bps_delta: float,
                         position_just_closed: bool,
                         drawdown_bps_abs: float,
                         time_in_trade_seconds: int,
                         position_size_abs: float,
                         fee_bps_per_side: float = 5.0,
                         slippage_bps_per_side: float = 1.0,
                         expected_move_after_cost_bps: float | None = None,
                         max_drawdown_bps: float = 200.0,
                         max_time_in_trade_seconds: int = 3600,
                         max_position_size: float = 1.0,
                         hard_clamp_bps: float = 1000.0) -> RewardComponents:
    base = base_pnl_reward(realized_bps, unrealized_bps)
    fee_aware = fee_aware_reward(
        realized_bps_delta=realized_bps_delta,
        fee_bps_per_side=fee_bps_per_side,
        slippage_bps_per_side=slippage_bps_per_side,
        expected_move_after_cost_bps=expected_move_after_cost_bps,
        position_just_closed=position_just_closed,
    )
    safety = constrained_safety_penalty(
        drawdown_bps_abs=drawdown_bps_abs,
        max_drawdown_bps=max_drawdown_bps,
        time_in_trade_seconds=time_in_trade_seconds,
        max_time_in_trade_seconds=max_time_in_trade_seconds,
        position_size_abs=position_size_abs,
        max_position_size=max_position_size,
    )
    hedge_bps, hedge_class = hedge_reward_placeholder()
    total = base + fee_aware + safety + hedge_bps
    clamped = False
    if total > hard_clamp_bps:
        total = hard_clamp_bps
        clamped = True
    elif total < -hard_clamp_bps:
        total = -hard_clamp_bps
        clamped = True
    return RewardComponents(
        base_pnl_reward_bps=base,
        fee_aware_reward_bps=fee_aware,
        constrained_safety_penalty_bps=safety,
        hedge_reward_bps=hedge_bps,
        hedge_reward_classification=hedge_class,
        total_reward_bps=total,
        clamped=clamped,
    )


def reward_invariants_snapshot() -> dict:
    return {
        "hedge_reward_classification": HEDGE_REWARD_CLASSIFICATION,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "legacy_behavior_mapping": LEGACY_SOURCES,
    }
