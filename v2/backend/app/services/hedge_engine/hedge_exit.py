from __future__ import annotations

from typing import Any, Mapping


def build_hedge_exit_plan(hedge: Mapping[str, Any], *, hedge_allowed: bool, hedge_reason: str) -> dict[str, Any]:
    if not hedge_allowed:
        return {
            "status": "NO_HEDGE_EXIT_PLAN_REQUIRED",
            "reason": hedge_reason,
            "close_trigger": None,
            "reduce_trigger": None,
        }
    return {
        "status": "HEDGE_EXIT_PLAN_ACTIVE",
        "reason": hedge_reason,
        "close_trigger": "risk_reduction_realized_or_primary_thesis_invalidated",
        "reduce_trigger": "net_delta_returns_inside_budget",
        "max_hold": "same_or_shorter_than_primary_position_thesis_window",
        "hedge_symbol": hedge.get("hedge_symbol"),
        "hedge_side": hedge.get("hedge_side"),
        "paper_only": True,
        "places_real_order": False,
    }
