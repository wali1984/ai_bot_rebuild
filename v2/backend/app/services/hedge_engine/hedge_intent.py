from __future__ import annotations

from typing import Any, Mapping, Sequence

from .hedge_cost_benefit import evaluate_hedge_cost_benefit
from .hedge_exit import build_hedge_exit_plan
from .hedge_sizing import size_hedge
from .portfolio_exposure import compute_portfolio_exposure


ALLOWED_HEDGE_ACTIONS = {
    "NO_HEDGE",
    "REDUCE_POSITION",
    "CLOSE_POSITION",
    "PROTECTIVE_HEDGE",
    "PAIR_HEDGE",
    "BETA_HEDGE",
    "MARKET_REGIME_HEDGE",
    "CROSS_MARGIN_RISK_OFF",
}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "long", "open_long"}:
        return "long"
    if text in {"sell", "short", "open_short"}:
        return "short"
    return text


def evaluate_hedge_intent(
    *,
    candidate: Mapping[str, Any] | None = None,
    positions: Sequence[Mapping[str, Any]] | None = None,
    equity_usd: float | None = None,
    risk_budget_usd: float = 0.0,
    hedge_budget_usd: float = 0.0,
    max_loss_usd: float | None = None,
    expected_net_pnl_usd: float | None = None,
    spread_bps: float = 0.0,
    slippage_bps: float = 0.0,
    fee_bps: float = 0.0,
    funding_bps: float = 0.0,
    correlation_exposure_pct: float | None = None,
    liquidation_buffer_usd: float | None = None,
    invalid_position: bool = False,
    edge_remains: bool = True,
) -> dict[str, Any]:
    candidate_dict = dict(candidate or {})
    exposure = compute_portfolio_exposure(
        positions,
        candidate=candidate_dict,
        equity_usd=equity_usd,
        correlation_exposure_pct=correlation_exposure_pct,
    )
    max_loss = _f(max_loss_usd)
    expected_net = _f(expected_net_pnl_usd)

    action = "NO_HEDGE"
    reason = "hedge_not_required_current_exposure_inside_budget"
    hedge_required = False
    if invalid_position:
        action = "CLOSE_POSITION"
        reason = "invalid_position_close_or_reduce_before_any_hedge"
    elif not edge_remains or expected_net <= 0.0:
        action = "REDUCE_POSITION"
        reason = "no_positive_edge_reduce_before_hedge"
    elif _f(exposure.get("correlation_exposure_pct")) >= 0.12 or abs(_f(exposure.get("net_delta_usd"))) > max(25.0, max_loss * 10.0):
        action = "PROTECTIVE_HEDGE"
        reason = "net_delta_or_correlation_pressure_requires_protection"
        hedge_required = True

    sized = size_hedge(
        exposure,
        risk_budget_usd=risk_budget_usd,
        hedge_budget_usd=hedge_budget_usd,
    )
    same_direction = _side(candidate_dict.get("side") or candidate_dict.get("action")) == _side(sized.get("hedge_side"))
    cost_benefit = evaluate_hedge_cost_benefit(
        sized,
        exposure=exposure,
        max_loss_usd=max_loss,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        fee_bps=fee_bps,
        funding_bps=funding_bps,
        liquidation_buffer_usd=liquidation_buffer_usd,
        same_direction_as_candidate=same_direction,
    )

    hedge_allowed = bool(cost_benefit.get("hedge_allowed")) and action == "PROTECTIVE_HEDGE"
    if action == "PROTECTIVE_HEDGE" and not hedge_allowed:
        action = "REDUCE_POSITION"
        reason = "hedge_rejected_reduce_or_no_trade_instead:" + ",".join(cost_benefit.get("hedge_reject_reasons") or [])
        hedge_required = False
    if action not in ALLOWED_HEDGE_ACTIONS:
        action = "NO_HEDGE"
        reason = "invalid_hedge_action_sanitized_to_no_hedge"
        hedge_required = False

    exit_plan = build_hedge_exit_plan(sized, hedge_allowed=hedge_allowed, hedge_reason=reason)
    return {
        **exposure,
        "hedge_required": hedge_required,
        "hedge_action": action,
        "hedge_reason": reason,
        "hedge_state": action,
        "hedge_symbol": sized.get("hedge_symbol") if hedge_allowed else None,
        "hedge_side": sized.get("hedge_side") if hedge_allowed else None,
        "hedge_notional_usd": sized.get("hedge_notional_usd") if hedge_allowed else 0.0,
        "hedge_margin_usd": sized.get("hedge_margin_usd") if hedge_allowed else 0.0,
        "hedge_leverage": sized.get("hedge_leverage") if hedge_allowed else 1.0,
        **cost_benefit,
        "hedge_exit_plan": exit_plan,
        "hedge_increases_liquidation_risk": "HEDGE_WOULD_INCREASE_LIQUIDATION_RISK" in (cost_benefit.get("hedge_reject_reasons") or []),
        "hedge_averaging_down_rejected": "HEDGE_LOOKS_LIKE_AVERAGING_DOWN" in (cost_benefit.get("hedge_reject_reasons") or []),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
