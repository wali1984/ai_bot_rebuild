from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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


@dataclass(frozen=True)
class AdaptiveHedgeConfig:
    max_hedge_budget_usd: float = 25.0
    max_hedge_ratio: float = 0.35
    require_risk_approval: bool = True


def evaluate_adaptive_hedge(
    *,
    position: dict[str, Any],
    hedge_intent: dict[str, Any] | None,
    config: AdaptiveHedgeConfig | None = None,
) -> dict[str, Any]:
    cfg = config or AdaptiveHedgeConfig()
    intent = dict(hedge_intent or {})
    blockers: list[str] = []
    if intent.get("hedge_intent") is not True:
        blockers.append("HEDGE_INTENT_REQUIRED")
    if not intent.get("hedge_reason"):
        blockers.append("HEDGE_REASON_REQUIRED")
    if not intent.get("unhedge_condition") and not intent.get("hedge_exit_reason"):
        blockers.append("HEDGE_EXIT_CONDITION_REQUIRED")
    budget = _float(intent.get("hedge_budget_usd"))
    if budget <= 0.0:
        blockers.append("HEDGE_BUDGET_REQUIRED")
    if budget > cfg.max_hedge_budget_usd:
        blockers.append("HEDGE_BUDGET_EXCEEDS_CAP")
    if cfg.require_risk_approval and intent.get("risk_approved") is not True:
        blockers.append("HEDGE_RISK_APPROVAL_REQUIRED")

    position_symbol = str(position.get("symbol") or "").upper()
    hedge_symbol = str(intent.get("symbol") or position_symbol).upper()
    position_side = str(position.get("side") or "").lower()
    hedge_side = str(intent.get("hedge_side") or intent.get("side") or "").lower()
    if position_symbol == hedge_symbol and {position_side, hedge_side} == {"long", "short"} and intent.get("hedge_intent") is not True:
        blockers.append("ACCIDENTAL_SAME_SYMBOL_HEDGE_BLOCKED")

    notional = _float(position.get("notional") or position.get("notional_usd"))
    requested = min(budget, max(0.0, notional * cfg.max_hedge_ratio))
    allowed = not blockers
    return {
        "hedge_allowed": allowed,
        "hedge_blockers": blockers,
        "hedge_type": intent.get("hedge_type") or "explicit_adaptive_hedge",
        "hedge_reason": intent.get("hedge_reason"),
        "hedge_exit_reason": intent.get("hedge_exit_reason") or intent.get("unhedge_condition"),
        "hedge_budget_usd": budget,
        "approved_hedge_notional_usd": requested if allowed else 0.0,
        "same_symbol_accidental_hedge_blocked": "ACCIDENTAL_SAME_SYMBOL_HEDGE_BLOCKED" in blockers,
        "requires_unhedge_condition": True,
        "paper_only": True,
        "places_real_order": False,
    }


def build_hedge_cost_benefit(
    *,
    hedge_id: str,
    hedge_notional_usd: float,
    fees: float,
    slippage: float,
    pnl_without_hedge: float,
    pnl_with_hedge: float,
) -> dict[str, Any]:
    cost = max(0.0, _float(fees) + _float(slippage))
    benefit = _float(pnl_with_hedge) - _float(pnl_without_hedge)
    return {
        "hedge_id": hedge_id,
        "hedge_notional_usd": _float(hedge_notional_usd),
        "hedge_cost_usd": cost,
        "hedge_benefit_usd": benefit,
        "net_hedge_benefit_usd": benefit - cost,
        "hedge_cost_benefit_tracked": True,
        "paper_only": True,
        "places_real_order": False,
    }


__all__ = ["AdaptiveHedgeConfig", "evaluate_adaptive_hedge", "build_hedge_cost_benefit"]
