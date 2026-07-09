from __future__ import annotations

from typing import Any, Mapping, Sequence

from v2.backend.app.services.hedge_engine import evaluate_hedge_intent


def _float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number


def _side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "long", "open_long"}:
        return "long"
    if text in {"sell", "short", "open_short"}:
        return "short"
    return text


def _opposite_side(value: Any) -> str | None:
    side = _side(value)
    if side == "long":
        return "short"
    if side == "short":
        return "long"
    return None


def _cash_plan(reason: str) -> dict[str, Any]:
    return {
        "hedge_required": False,
        "hedge_symbol": None,
        "hedge_side": None,
        "hedge_notional_usd": 0.0,
        "hedge_reason": reason,
        "hedge_expected_cost_usd": 0.0,
        "hedge_max_loss_reduction_usd": 0.0,
        "hedge_liquidation_risk_delta_usd": 0.0,
    }


def simulate_hedge_plan(
    *,
    candidate: Mapping[str, Any],
    positions: Sequence[Mapping[str, Any]] | None = None,
    equity_usd: float | None = None,
    risk_budget_usd: float = 0.0,
    hedge_budget_usd: float = 0.0,
    max_loss_usd: float | None = None,
    expected_net_pnl_usd: float | None = None,
    liquidation_buffer_usd: float | None = None,
    spread_bps: float = 0.0,
    slippage_bps: float = 0.0,
    fee_bps: float = 0.0,
    funding_bps: float = 0.0,
    correlation_exposure_pct: float | None = None,
    primary_candidate_passed: bool = False,
    hedge_mode_supported: bool = False,
) -> dict[str, Any]:
    """Simulate hedge options without allowing a hedge to rescue a bad entry."""
    base_candidate = dict(candidate)
    no_hedge = _cash_plan("no_hedge_baseline")
    cash_no_trade = _cash_plan("cash_no_trade_hedge_when_primary_not_passed")
    partial_hedge = _cash_plan("partial_hedge_not_selected")
    correlated_hedge = _cash_plan("correlated_hedge_not_selected")
    opposite_side = _opposite_side(base_candidate.get("side") or base_candidate.get("action"))

    if not primary_candidate_passed:
        return {
            **cash_no_trade,
            "hedge_action": "NO_HEDGE",
            "hedge_state": "NO_HEDGE_PRIMARY_REJECTED",
            "hedge_mode_supported": hedge_mode_supported,
            "scenarios": {
                "no_hedge": no_hedge,
                "partial_hedge": partial_hedge,
                "correlated_hedge": correlated_hedge,
                "opposite_side_hedge": {
                    **cash_no_trade,
                    "hedge_side": opposite_side,
                    "hedge_reason": "opposite_side_hedge_blocked_until_primary_candidate_passes",
                },
                "cash_no_trade": cash_no_trade,
            },
            "routes_to_live": False,
            "places_real_order": False,
        }

    raw_plan = evaluate_hedge_intent(
        candidate=base_candidate,
        positions=positions or (),
        equity_usd=equity_usd,
        risk_budget_usd=risk_budget_usd,
        hedge_budget_usd=hedge_budget_usd,
        max_loss_usd=max_loss_usd,
        expected_net_pnl_usd=expected_net_pnl_usd,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        fee_bps=fee_bps,
        funding_bps=funding_bps,
        correlation_exposure_pct=correlation_exposure_pct,
        liquidation_buffer_usd=liquidation_buffer_usd,
        edge_remains=_float(expected_net_pnl_usd) > 0.0,
    )
    hedge_cost = _float(raw_plan.get("hedge_cost_usd"))
    risk_reduction = _float(raw_plan.get("hedge_expected_risk_reduction_usd"))
    liquidation_delta = -risk_reduction if raw_plan.get("hedge_increases_liquidation_risk") is not True else hedge_cost
    selected = {
        "hedge_required": bool(raw_plan.get("hedge_required")),
        "hedge_symbol": raw_plan.get("hedge_symbol"),
        "hedge_side": raw_plan.get("hedge_side"),
        "hedge_notional_usd": _float(raw_plan.get("hedge_notional_usd")),
        "hedge_reason": raw_plan.get("hedge_reason"),
        "hedge_expected_cost_usd": hedge_cost,
        "hedge_max_loss_reduction_usd": risk_reduction,
        "hedge_liquidation_risk_delta_usd": round(liquidation_delta, 8),
    }
    return {
        **selected,
        "hedge_action": raw_plan.get("hedge_action"),
        "hedge_state": raw_plan.get("hedge_state"),
        "hedge_mode_supported": hedge_mode_supported,
        "hedge_exit_plan": raw_plan.get("hedge_exit_plan") or {},
        "scenarios": {
            "no_hedge": no_hedge,
            "partial_hedge": {
                **selected,
                "hedge_notional_usd": round(selected["hedge_notional_usd"] * 0.5, 8),
                "hedge_reason": "partial_hedge_simulated",
            },
            "correlated_hedge": {
                **selected,
                "hedge_reason": "correlated_hedge_simulated",
            },
            "opposite_side_hedge": {
                **selected,
                "hedge_side": selected["hedge_side"] or opposite_side,
                "hedge_reason": "opposite_side_hedge_simulated_when_position_mode_supports_it",
            },
            "cash_no_trade": cash_no_trade,
        },
        "routes_to_live": False,
        "places_real_order": False,
    }
