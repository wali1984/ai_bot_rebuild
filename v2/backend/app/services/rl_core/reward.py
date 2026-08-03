"""V2 constrained reward (paper-only).

Pure CPU port of the legacy constrained reward shaping signal for paper-outcome
scoring. This module does NOT drive any training loop; it computes a reward
breakdown given a paper trade outcome dict.

Legacy references (cited by SHA256, file_runtime_copied_source_manifest.json):

- ``rl/reward_functions.py`` sha256
  ``87ef4602012cbbd944bdf506fb8f1646375e7732c3a93e87b0946db7a1cca853``
  size_bytes 31805
- ``rl/constrained_reward.py`` sha256
  ``69ff3c75b53d8d3d7844894954cf9d16f334e79e0c1bd39e9624a4482a459b2e``
  size_bytes 10861
- ``rl/fee_ratio_reward_shaping.py`` sha256
  ``e7edce3e29a6bf7236329245ba4a14436dc6f6b0a249ad0ad3d05760570bfc06``
  size_bytes 19427

Behaviors ported (paper-only):

1. Realized PnL credit (signed)
2. Fee penalty in bps of notional (subtractive)
3. Fee-ratio shaping (fee_bps / abs(expected_move_bps) penalty when fees
   dominate the predicted edge)
4. Drawdown penalty (Lagrangian-style proportional penalty above threshold)
5. No-trade-correct credit (small positive credit if the agent correctly
   declined to trade when the realized outcome was within noise)
6. Hard reward clamp to keep magnitudes bounded

Behaviors NOT ported here (and marked MISSING_IN_V2 in the service status):

- The full Lagrangian-tuned ConstrainedRewardShaper with persistent multipliers
  across training steps (this V2 implementation uses fixed weights for paper
  scoring; learning the multipliers requires the missing training loop).
- The fee_ratio gate stateful trade-count tracking from
  ``trading.fee_ratio_gate``.
- The MASA/PPO agent-blending reward signal contributions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

LEGACY_REWARD_FUNCTIONS_SHA256 = (
    "87ef4602012cbbd944bdf506fb8f1646375e7732c3a93e87b0946db7a1cca853"
)
LEGACY_CONSTRAINED_REWARD_SHA256 = (
    "69ff3c75b53d8d3d7844894954cf9d16f334e79e0c1bd39e9624a4482a459b2e"
)
LEGACY_FEE_RATIO_REWARD_SHAPING_SHA256 = (
    "e7edce3e29a6bf7236329245ba4a14436dc6f6b0a249ad0ad3d05760570bfc06"
)

# Default soft caps; the final reward is clamped to [-clamp, +clamp].
REWARD_CLAMP_DEFAULT = 5.0

# Default Lagrangian-style penalty weights (paper-only, fixed).
DEFAULT_DRAWDOWN_THRESHOLD_PCT = 0.05  # 5% account drawdown
DEFAULT_DRAWDOWN_LAMBDA = 4.0
DEFAULT_FEE_RATIO_WARNING = 0.30
DEFAULT_FEE_RATIO_HIGH = 0.50
DEFAULT_FEE_RATIO_CRITICAL = 0.80
DEFAULT_FEE_RATIO_PENALTY_WARNING = 0.10
DEFAULT_FEE_RATIO_PENALTY_HIGH = 0.25
DEFAULT_FEE_RATIO_PENALTY_CRITICAL = 0.50
DEFAULT_NO_TRADE_CORRECT_CREDIT = 0.05
DEFAULT_NO_TRADE_NOISE_BPS = 5.0


@dataclass(frozen=True)
class RewardComponents:
    """Breakdown of every reward credit and penalty.

    All fields are floats. ``total`` is the post-clamp sum; ``raw_total`` is
    the pre-clamp sum (informational).
    """

    realized_pnl_credit: float
    fee_penalty: float
    slippage_penalty: float
    fee_ratio_penalty: float
    drawdown_penalty: float
    no_trade_correct_credit: float
    raw_total: float
    total: float
    clamped: bool
    fee_ratio: float
    drawdown_pct_used: float

    def as_dict(self) -> dict[str, float | bool]:
        return asdict(self)


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fee_ratio_penalty_value(fee_ratio: float) -> float:
    """Step penalty mapping reproduced from fee_ratio_reward_shaping.py."""
    if fee_ratio >= DEFAULT_FEE_RATIO_CRITICAL:
        return DEFAULT_FEE_RATIO_PENALTY_CRITICAL
    if fee_ratio >= DEFAULT_FEE_RATIO_HIGH:
        return DEFAULT_FEE_RATIO_PENALTY_HIGH
    if fee_ratio >= DEFAULT_FEE_RATIO_WARNING:
        return DEFAULT_FEE_RATIO_PENALTY_WARNING
    return 0.0


def compute_constrained_reward(
    *,
    realized_pnl: float,
    notional_usd: float = 0.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
    expected_move_bps: float = 0.0,
    drawdown_pct: float = 0.0,
    drawdown_threshold_pct: float = DEFAULT_DRAWDOWN_THRESHOLD_PCT,
    drawdown_lambda: float = DEFAULT_DRAWDOWN_LAMBDA,
    trade_executed: bool = True,
    no_trade_outcome_bps: float = 0.0,
    no_trade_noise_bps: float = DEFAULT_NO_TRADE_NOISE_BPS,
    no_trade_correct_credit: float = DEFAULT_NO_TRADE_CORRECT_CREDIT,
    clamp: float = REWARD_CLAMP_DEFAULT,
) -> RewardComponents:
    """Compute a paper-outcome constrained reward.

    Args:
        realized_pnl: signed realized PnL in account-currency units. Positive
            when the trade was profitable.
        notional_usd: traded notional (USD-equivalent). Used to normalize fees
            against expected move and to detect non-trade no-op states.
        fee_bps: fees as basis points of notional (subtractive).
        slippage_bps: slippage as basis points of notional (subtractive).
        expected_move_bps: model-predicted expected move in basis points. Used
            as the denominator for the fee-ratio penalty.
        drawdown_pct: current account drawdown as a fraction (e.g. 0.05 = 5%).
        drawdown_threshold_pct: drawdown threshold above which the penalty
            engages.
        drawdown_lambda: Lagrangian-style multiplier on the drawdown excess.
        trade_executed: whether a trade was placed on this step.
        no_trade_outcome_bps: absolute price move that occurred while flat. If
            below ``no_trade_noise_bps`` and the agent did not trade, the
            no-trade-correct credit is awarded.
        no_trade_noise_bps: noise floor below which "not trading" is the
            correct outcome.
        no_trade_correct_credit: credit awarded for correct no-trade.
        clamp: absolute hard cap on the final reward.

    Returns:
        A :class:`RewardComponents` with the full breakdown.
    """
    pnl = _safe_float(realized_pnl)
    notional = max(_safe_float(notional_usd), 0.0)
    fee_bps_v = max(_safe_float(fee_bps), 0.0)
    slip_bps_v = max(_safe_float(slippage_bps), 0.0)
    expected_move = abs(_safe_float(expected_move_bps))
    drawdown = max(_safe_float(drawdown_pct), 0.0)
    dd_threshold = max(_safe_float(drawdown_threshold_pct), 0.0)
    dd_lambda = max(_safe_float(drawdown_lambda), 0.0)
    clamp_abs = abs(_safe_float(clamp, REWARD_CLAMP_DEFAULT))
    if clamp_abs == 0.0:
        clamp_abs = REWARD_CLAMP_DEFAULT

    realized_pnl_credit = pnl

    # Fee/slippage penalties expressed in the same units as PnL: bps of notional.
    fee_penalty = (fee_bps_v / 10_000.0) * notional if trade_executed else 0.0
    slippage_penalty = (
        (slip_bps_v / 10_000.0) * notional if trade_executed else 0.0
    )

    # Fee ratio: how much of the predicted edge the fee consumes.
    if trade_executed and expected_move > 0.0:
        fee_ratio = fee_bps_v / expected_move
    else:
        fee_ratio = 0.0
    fee_ratio_penalty = _fee_ratio_penalty_value(fee_ratio)

    # Drawdown penalty: Lagrangian-style proportional excess.
    drawdown_excess = max(0.0, drawdown - dd_threshold)
    drawdown_penalty = dd_lambda * drawdown_excess

    # No-trade-correct credit (only when flat and the move stayed within noise).
    if (
        not trade_executed
        and notional == 0.0
        and abs(_safe_float(no_trade_outcome_bps))
        < max(0.0, _safe_float(no_trade_noise_bps))
    ):
        ntc_credit = max(0.0, _safe_float(no_trade_correct_credit))
    else:
        ntc_credit = 0.0

    raw_total = (
        realized_pnl_credit
        - fee_penalty
        - slippage_penalty
        - fee_ratio_penalty
        - drawdown_penalty
        + ntc_credit
    )

    if raw_total > clamp_abs:
        total = clamp_abs
        clamped = True
    elif raw_total < -clamp_abs:
        total = -clamp_abs
        clamped = True
    else:
        total = raw_total
        clamped = False

    return RewardComponents(
        realized_pnl_credit=float(realized_pnl_credit),
        fee_penalty=float(fee_penalty),
        slippage_penalty=float(slippage_penalty),
        fee_ratio_penalty=float(fee_ratio_penalty),
        drawdown_penalty=float(drawdown_penalty),
        no_trade_correct_credit=float(ntc_credit),
        raw_total=float(raw_total),
        total=float(total),
        clamped=bool(clamped),
        fee_ratio=float(fee_ratio),
        drawdown_pct_used=float(drawdown),
    )
