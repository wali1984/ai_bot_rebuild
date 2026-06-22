from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


STRATEGY_FAMILIES: tuple[str, ...] = (
    "trend_following",
    "mean_reversion",
    "breakout",
    "momentum",
    "funding_oi_divergence",
    "liquidation_cascade",
    "orderbook_imbalance",
    "ta_confirmation",
    "microstructure_reversal",
    "volatility_regime",
    "public_intel_confirmation",
    "no_trade_preservation",
    "hedged_protection",
    "profit_protection",
    "drawdown_recovery",
)


@dataclass(frozen=True)
class StrategyWeightConfig:
    min_closed_trades: int = 10
    insufficient_sample_cap: float = 0.35
    min_weight: float = 0.05
    max_weight: float = 2.0
    drawdown_reduce_bps: float = 250.0


def _float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _family(row: dict[str, Any]) -> str:
    value = str(row.get("strategy_family") or row.get("strategy_id") or "unknown").strip()
    return value if value else "unknown"


def compute_adaptive_strategy_weights(
    outcomes: list[dict[str, Any]],
    *,
    current_weights: dict[str, float] | None = None,
    config: StrategyWeightConfig | None = None,
) -> dict[str, Any]:
    cfg = config or StrategyWeightConfig()
    weights = {family: float((current_weights or {}).get(family, 1.0)) for family in STRATEGY_FAMILIES}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in outcomes:
        if isinstance(row, dict):
            grouped[_family(row)].append(row)

    rows: list[dict[str, Any]] = []
    for family in STRATEGY_FAMILIES:
        samples = grouped.get(family, [])
        count = len(samples)
        pnl = [_float(row.get("realized_pnl_bps")) for row in samples]
        wins = [value for value in pnl if value > 0.0]
        losses = [value for value in pnl if value < 0.0]
        recent_pnl = sum(pnl[-20:])
        expectancy = sum(pnl) / count if count else 0.0
        win_rate = len(wins) / count if count else 0.0
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = None if gross_loss == 0.0 and gross_win == 0.0 else (999.0 if gross_loss == 0.0 else gross_win / gross_loss)
        running = 0.0
        peak = 0.0
        max_drawdown = 0.0
        for value in pnl:
            running += value
            peak = max(peak, running)
            max_drawdown = max(max_drawdown, peak - running)

        base = weights[family]
        if count < cfg.min_closed_trades:
            new_weight = min(base, cfg.insufficient_sample_cap)
            reason = "INSUFFICIENT_SAMPLE_CAP"
        elif expectancy > 0.0 and (profit_factor or 0.0) > 1.2 and max_drawdown < cfg.drawdown_reduce_bps:
            new_weight = min(cfg.max_weight, base * 1.20)
            reason = "PROFITABLE_STRATEGY_WEIGHT_INCREASE"
        elif expectancy <= 0.0 or (profit_factor is not None and profit_factor < 1.0):
            new_weight = max(cfg.min_weight, base * 0.65)
            reason = "LOSING_STRATEGY_WEIGHT_DECREASE"
        elif max_drawdown >= cfg.drawdown_reduce_bps:
            new_weight = max(cfg.min_weight, base * 0.75)
            reason = "DRAWDOWN_HEAVY_STRATEGY_WEIGHT_REDUCTION"
        else:
            new_weight = base
            reason = "STABLE_STRATEGY_WEIGHT"
        weights[family] = new_weight
        rows.append(
            {
                "strategy_family": family,
                "closed_trade_count": count,
                "win_rate": win_rate,
                "expectancy_after_cost_bps": expectancy,
                "profit_factor": profit_factor,
                "max_drawdown": max_drawdown,
                "recent_pnl": recent_pnl,
                "current_weight": new_weight,
                "weight_change_reason": reason,
            }
        )
    return {
        "strategy_weights": weights,
        "strategy_runtime_rows": rows,
        "outcome_count": len(outcomes),
        "adaptive_from_realized_outcomes": True,
        "static_strategy_selection": False,
    }


__all__ = ["STRATEGY_FAMILIES", "StrategyWeightConfig", "compute_adaptive_strategy_weights"]
