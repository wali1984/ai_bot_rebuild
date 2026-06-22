from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _side(action: str) -> str | None:
    text = str(action or "").lower()
    if text in {"long", "buy", "open_long", "proceed_long"} or text.endswith("_long"):
        return "long"
    if text in {"short", "sell", "open_short", "proceed_short"} or text.endswith("_short"):
        return "short"
    return None


@dataclass(frozen=True)
class AlphaLiquidityRiskConfig:
    min_liquidation_distance_bps: float = 35.0
    max_cascade_risk: float = 0.80
    max_adverse_wall_strength: float = 0.85
    min_microstructure_depth_usd: float = 5000.0


def evaluate_alpha_liquidity_risk(
    *,
    action: str,
    context: dict[str, Any] | None,
    config: AlphaLiquidityRiskConfig | None = None,
) -> dict[str, Any]:
    cfg = config or AlphaLiquidityRiskConfig()
    ctx = dict(context or {})
    side = _side(action)
    blockers: list[str] = []
    warnings: list[str] = []
    if side is None:
        blockers.append("ACTION_NOT_SUPPORTED_FOR_ALPHA_LIQUIDITY_RISK")
    if not ctx:
        blockers.append("ALPHA_LIQUIDITY_CONTEXT_MISSING")

    cascade = _float(ctx.get("liquidation_cascade_risk"))
    if cascade is not None and cascade >= cfg.max_cascade_risk:
        blockers.append("LIQUIDATION_CASCADE_RISK_TOO_HIGH")

    depth = _float(ctx.get("microstructure_liquidity_depth"))
    if depth is not None and depth < cfg.min_microstructure_depth_usd:
        blockers.append("MICROSTRUCTURE_DEPTH_TOO_THIN")

    wall = _float(ctx.get("orderbook_wall_strength"))
    pressure = str(ctx.get("liquidation_pressure_direction") or "").lower()
    if wall is not None and wall >= cfg.max_adverse_wall_strength:
        if side == "long" and pressure in {"down", "short", "sell"}:
            blockers.append("ADVERSE_ORDERBOOK_WALL_FOR_LONG")
        elif side == "short" and pressure in {"up", "long", "buy"}:
            blockers.append("ADVERSE_ORDERBOOK_WALL_FOR_SHORT")
        else:
            warnings.append("ORDERBOOK_WALL_REQUIRES_SIZE_REDUCTION")

    long_dist = _float(ctx.get("distance_to_long_liq_bps"))
    short_dist = _float(ctx.get("distance_to_short_liq_bps"))
    if side == "long" and long_dist is not None and long_dist <= cfg.min_liquidation_distance_bps:
        blockers.append("LONG_LIQUIDATION_DISTANCE_TOO_CLOSE")
    if side == "short" and short_dist is not None and short_dist <= cfg.min_liquidation_distance_bps:
        blockers.append("SHORT_LIQUIDATION_DISTANCE_TOO_CLOSE")

    strategy_bias = "neutral"
    if side == "long" and short_dist is not None and short_dist <= cfg.min_liquidation_distance_bps * 2:
        strategy_bias = "avoid_chasing_short_liquidation_cluster"
    if side == "short" and long_dist is not None and long_dist <= cfg.min_liquidation_distance_bps * 2:
        strategy_bias = "avoid_chasing_long_liquidation_cluster"
    if cascade is not None and cascade >= 0.50 and not blockers:
        strategy_bias = "reduce_size_liquidation_cascade_elevated"

    decision = "DENY_ALPHA_LIQUIDITY_RISK" if blockers else ("REDUCE_ALPHA_LIQUIDITY_RISK" if warnings else "ALLOW_ALPHA_LIQUIDITY_RISK")
    return {
        "allowed": not blockers,
        "risk_decision": decision,
        "risk_blockers": blockers,
        "risk_warnings": warnings,
        "orchestrator_signal_adjustment": "block" if blockers else ("reduce" if warnings else "none"),
        "strategy_bias": strategy_bias,
        "alpha_liquidity_context_used": True,
        "context": ctx,
    }


__all__ = ["AlphaLiquidityRiskConfig", "evaluate_alpha_liquidity_risk"]
