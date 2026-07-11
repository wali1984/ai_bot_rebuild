from __future__ import annotations

from typing import Any, Mapping


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def simulate_cross_margin_stress(
    *,
    equity_usd: float,
    available_margin_usd: float,
    target_notional_usd: float,
    allocated_margin_usd: float,
    recommended_leverage: float,
    max_loss_usd: float | None,
    hedge_plan: Mapping[str, Any] | None = None,
    requested_margin_mode: str | None = None,
    maintenance_margin_rate: float = 0.005,
    profit_factor: float | None = None,
    expectancy_usd: float | None = None,
) -> dict[str, Any]:
    equity = max(_f(equity_usd), 0.0)
    available = max(_f(available_margin_usd), 0.0)
    notional = max(_f(target_notional_usd), 0.0)
    leverage = max(_f(recommended_leverage, 1.0), 1.0)
    isolated_margin = max(_f(allocated_margin_usd), notional / leverage if leverage > 0 else notional)
    loss = max(_f(max_loss_usd), 0.0)
    hedge = dict(hedge_plan or {})
    hedge_margin = _f(hedge.get("hedge_margin_usd"))
    hedge_cost = _f(hedge.get("hedge_cost_usd"))
    hedge_risk_reduction = (
        _f(hedge.get("hedge_expected_risk_reduction_usd"))
        if hedge.get("hedge_required") is True
        and hedge.get("hedge_increases_liquidation_risk") is not True
        else 0.0
    )
    maintenance = notional * max(0.0, maintenance_margin_rate)
    stressed_loss = max(0.0, loss - hedge_risk_reduction)
    stress_used = stressed_loss + maintenance + hedge_margin + hedge_cost
    worst_case_loss = stressed_loss + hedge_cost
    buffer = max(0.0, available - stress_used)
    liquidation_buffer_usd = max(0.0, equity - stress_used)
    margin_call_risk = "HIGH" if buffer <= max(1.0, equity * 0.02) else ("MEDIUM" if buffer <= equity * 0.08 else "LOW")

    requested_cross = str(requested_margin_mode or "").lower().startswith("cross")
    pf_ok = profit_factor is None or profit_factor >= 1.0
    expectancy_ok = expectancy_usd is None or expectancy_usd > 0.0
    cross_safe = (
        requested_cross
        and
        notional > 0.0
        and pf_ok
        and expectancy_ok
        and margin_call_risk == "LOW"
        and liquidation_buffer_usd >= max(10.0, equity * 0.10)
        and hedge.get("hedge_increases_liquidation_risk") is not True
    )
    if requested_cross and cross_safe:
        recommended_margin_mode = "cross_paper_simulated"
        reason = "cross_margin_simulated_safe_under_portfolio_stress"
    elif requested_cross and not cross_safe:
        recommended_margin_mode = "isolated_paper_simulated"
        reason = "cross_margin_contagion_or_edge_risk_prefers_isolated"
    else:
        recommended_margin_mode = requested_margin_mode or "isolated_paper_simulated"
        reason = "isolated_margin_contains_tail_risk"

    return {
        "recommended_margin_mode": recommended_margin_mode,
        "isolated_margin_required_usd": round(isolated_margin, 8),
        "cross_margin_stress_used_usd": round(stress_used, 8),
        "cross_margin_hedge_risk_reduction_usd": round(hedge_risk_reduction, 8),
        "cross_margin_available_buffer_usd": round(buffer, 8),
        "portfolio_liquidation_buffer_usd": round(liquidation_buffer_usd, 8),
        "worst_case_portfolio_loss_usd": round(worst_case_loss, 8),
        "maintenance_margin_estimate_usd": round(maintenance, 8),
        "margin_call_risk": margin_call_risk,
        "cross_margin_safe": cross_safe,
        "why_cross_margin_or_isolated": reason,
        "exchange_margin_mode_mutation_allowed": False,
        "paper_only": True,
        "places_real_order": False,
    }
