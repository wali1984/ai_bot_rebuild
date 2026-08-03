from __future__ import annotations

from typing import Any, Mapping


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def size_hedge(
    exposure: Mapping[str, Any],
    *,
    risk_budget_usd: float,
    hedge_budget_usd: float,
    max_hedge_fraction_of_net_delta: float = 0.35,
) -> dict[str, Any]:
    net_delta = _f(exposure.get("net_delta_usd"))
    gross = _f(exposure.get("gross_exposure_usd"))
    abs_delta = abs(net_delta)
    if abs_delta <= 0.0 or gross <= 0.0:
        return {
            "hedge_symbol": None,
            "hedge_side": None,
            "hedge_notional_usd": 0.0,
            "hedge_margin_usd": 0.0,
            "hedge_leverage": 1.0,
            "hedge_size_reason": "portfolio_delta_balanced_or_empty",
        }

    budget_cap = max(0.0, max(_f(hedge_budget_usd), risk_budget_usd * 0.25))
    notional = min(abs_delta * max_hedge_fraction_of_net_delta, budget_cap * 10.0)
    notional = max(0.0, notional)
    side = "short" if net_delta > 0 else "long"
    return {
        "hedge_symbol": "BTCUSDT",
        "hedge_side": side,
        "hedge_notional_usd": round(notional, 8),
        "hedge_margin_usd": round(notional, 8),
        "hedge_leverage": 1.0,
        "hedge_size_reason": "opposite_delta_protective_hedge_budgeted_from_risk",
    }
