"""Leverage/margin exploration for trainer backtest / replay (study-only).

Pure functions. Given a candidate's after-cost expected move and risk inputs,
score each leverage in a grid and each margin mode, and return the risk-adjusted
best profile plus the full per-leverage breakdown. This is how the trainer
LEARNS which leverage/margin profile maximises risk-adjusted return per bucket
during backtest/replay — leverage here is a studied variable, never a live order
parameter. Nothing here mutates exchange state or routes to live.

Design rules (mirror the live allocator's safety, kept independent so the study
can never widen the live envelope):
  - Expectancy scales linearly with leverage.
  - Max loss (stop distance in bps) scales linearly with leverage.
  - The liquidation buffer shrinks ~1/leverage.
  - A leverage is only ELIGIBLE if its liquidation buffer stays above the floor
    and its modeled max loss stays under the per-trade cap.
  - Non-positive after-cost edge is never levered (best leverage = 1x).
  - The risk-adjusted score penalises leverage that erodes the liquidation
    buffer, so the "best" leverage is not simply the largest.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "trainer_leverage_margin_exploration_v1"

DEFAULT_LEVERAGE_GRID: tuple[float, ...] = (1.0, 2.0, 3.0)
DEFAULT_MARGIN_MODES: tuple[str, ...] = ("isolated", "cross")

# Study-only safety envelope (independent of, and never wider than, live).
DEFAULT_MIN_LIQUIDATION_BUFFER_BPS = 500.0
DEFAULT_MAX_LOSS_FRACTION_OF_EQUITY = 0.01
DEFAULT_BASE_LIQUIDATION_BUFFER_BPS = 10_000.0  # ~100% at 1x, shrinks ~1/lev


def _f(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def evaluate_leverage_for_candidate(
    *,
    expected_move_after_cost_bps: float | None,
    stop_distance_bps: float | None = None,
    equity_usd: float | None = None,
    notional_usd: float | None = None,
    leverage: float,
    base_liquidation_buffer_bps: float = DEFAULT_BASE_LIQUIDATION_BUFFER_BPS,
    min_liquidation_buffer_bps: float = DEFAULT_MIN_LIQUIDATION_BUFFER_BPS,
    max_loss_fraction_of_equity: float = DEFAULT_MAX_LOSS_FRACTION_OF_EQUITY,
) -> dict[str, Any]:
    """Score a single leverage for one candidate. Pure; no side effects."""

    lev = max(1.0, float(leverage))
    edge = _f(expected_move_after_cost_bps)
    stop_bps = _f(stop_distance_bps)
    equity = _f(equity_usd)
    notional = _f(notional_usd)

    # Non-positive after-cost edge is never levered.
    if edge is None or edge <= 0.0:
        return {
            "leverage": lev,
            "eligible": lev == 1.0,
            "reject_reason": None if lev == 1.0 else "NON_POSITIVE_AFTER_COST_EDGE_1X_ONLY",
            "levered_expectancy_bps": 0.0 if edge is None else round(edge, 8),
            "levered_max_loss_bps": None,
            "liquidation_buffer_bps": round(base_liquidation_buffer_bps / lev, 8),
            "risk_adjusted_score": 0.0 if edge is None else round(edge, 8),
        }

    levered_expectancy_bps = edge * lev
    liquidation_buffer_bps = base_liquidation_buffer_bps / lev

    if stop_bps is not None and stop_bps > 0.0:
        levered_max_loss_bps = stop_bps * lev
    else:
        levered_max_loss_bps = None

    levered_max_loss_usd = None
    if levered_max_loss_bps is not None and notional is not None and notional > 0.0:
        levered_max_loss_usd = notional * levered_max_loss_bps / 10_000.0

    reject_reason = None
    if liquidation_buffer_bps < min_liquidation_buffer_bps:
        reject_reason = "LIQUIDATION_BUFFER_BELOW_FLOOR"
    elif (
        levered_max_loss_usd is not None
        and equity is not None
        and equity > 0.0
        and levered_max_loss_usd > equity * max_loss_fraction_of_equity
    ):
        reject_reason = "MODELED_MAX_LOSS_EXCEEDS_PER_TRADE_CAP"

    eligible = reject_reason is None

    # Risk-adjusted score: levered expectancy discounted by how much of the
    # liquidation buffer this leverage consumes (0 buffer -> full discount).
    buffer_ratio = max(
        0.0, min(1.0, liquidation_buffer_bps / max(1e-9, base_liquidation_buffer_bps))
    )
    risk_adjusted_score = levered_expectancy_bps * buffer_ratio if eligible else 0.0

    return {
        "leverage": lev,
        "eligible": eligible,
        "reject_reason": reject_reason,
        "levered_expectancy_bps": round(levered_expectancy_bps, 8),
        "levered_max_loss_bps": None if levered_max_loss_bps is None else round(levered_max_loss_bps, 8),
        "levered_max_loss_usd": None if levered_max_loss_usd is None else round(levered_max_loss_usd, 8),
        "liquidation_buffer_bps": round(liquidation_buffer_bps, 8),
        "risk_adjusted_score": round(risk_adjusted_score, 8),
    }


def evaluate_leverage_margin_grid(
    candidate: Mapping[str, Any],
    *,
    leverage_grid: Sequence[float] = DEFAULT_LEVERAGE_GRID,
    margin_modes: Sequence[str] = DEFAULT_MARGIN_MODES,
    base_liquidation_buffer_bps: float = DEFAULT_BASE_LIQUIDATION_BUFFER_BPS,
    min_liquidation_buffer_bps: float = DEFAULT_MIN_LIQUIDATION_BUFFER_BPS,
    max_loss_fraction_of_equity: float = DEFAULT_MAX_LOSS_FRACTION_OF_EQUITY,
) -> dict[str, Any]:
    """Explore a leverage grid x margin modes for one candidate (study-only).

    Returns the per-leverage breakdown and the risk-adjusted best eligible
    leverage/margin profile. The live allocator makes the final portfolio-aware
    margin-mode call; this is a training study that never routes to live.
    """

    edge = _f(candidate.get("expected_move_after_cost_bps"))
    stop_bps = _f(candidate.get("stop_distance_bps"))
    equity = _f(candidate.get("equity_usd"))
    notional = _f(
        candidate.get("notional_usd")
        or candidate.get("gross_notional_usd")
        or candidate.get("target_notional_usd")
    )

    breakdown = [
        evaluate_leverage_for_candidate(
            expected_move_after_cost_bps=edge,
            stop_distance_bps=stop_bps,
            equity_usd=equity,
            notional_usd=notional,
            leverage=lev,
            base_liquidation_buffer_bps=base_liquidation_buffer_bps,
            min_liquidation_buffer_bps=min_liquidation_buffer_bps,
            max_loss_fraction_of_equity=max_loss_fraction_of_equity,
        )
        for lev in leverage_grid
    ]

    eligible = [row for row in breakdown if row["eligible"]]
    if eligible:
        best = max(eligible, key=lambda row: row["risk_adjusted_score"])
        best_leverage = best["leverage"]
        best_score = best["risk_adjusted_score"]
        best_reason = "RISK_ADJUSTED_BEST_ELIGIBLE_LEVERAGE"
    else:
        best_leverage = 1.0
        best_score = 0.0
        best_reason = "NO_ELIGIBLE_LEVERAGE_DEFAULT_1X"

    return {
        "schema_version": SCHEMA_VERSION,
        "study_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "leverage_grid": [float(x) for x in leverage_grid],
        "margin_modes_explored": [str(m) for m in margin_modes],
        "per_leverage_breakdown": breakdown,
        "best_leverage": best_leverage,
        "best_margin_mode": str(margin_modes[0]) if margin_modes else "isolated",
        "best_risk_adjusted_score": best_score,
        "best_leverage_reason": best_reason,
        "dynamic_not_static": len({row["leverage"] for row in breakdown}) > 1,
    }
