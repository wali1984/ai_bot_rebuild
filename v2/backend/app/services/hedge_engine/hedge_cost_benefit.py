from __future__ import annotations

from typing import Any, Mapping


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_hedge_cost_benefit(
    hedge: Mapping[str, Any],
    *,
    exposure: Mapping[str, Any],
    max_loss_usd: float | None,
    spread_bps: float,
    slippage_bps: float,
    fee_bps: float,
    funding_bps: float,
    liquidation_buffer_usd: float | None,
    same_direction_as_candidate: bool = False,
) -> dict[str, Any]:
    hedge_notional = _f(hedge.get("hedge_notional_usd"))
    cost_bps = max(0.0, spread_bps) + max(0.0, slippage_bps) + max(0.0, fee_bps) + abs(funding_bps)
    hedge_cost = hedge_notional * cost_bps / 10000.0
    gross_exposure = _f(exposure.get("gross_exposure_usd"))
    net_delta = abs(_f(exposure.get("net_delta_usd")))
    loss_anchor = max(_f(max_loss_usd), gross_exposure * 0.0025)
    expected_reduction = min(loss_anchor * 0.75, net_delta * 0.08, hedge_notional * 0.10)
    buffer = _f(liquidation_buffer_usd, default=loss_anchor)

    reject_reasons: list[str] = []
    if hedge_notional <= 0.0:
        reject_reasons.append("HEDGE_NOT_REQUIRED")
    if hedge_cost > expected_reduction:
        reject_reasons.append("HEDGE_COST_EXCEEDS_EXPECTED_RISK_REDUCTION")
    if hedge_notional > 0.0 and buffer <= 0.0:
        reject_reasons.append("HEDGE_WOULD_INCREASE_LIQUIDATION_RISK")
    if same_direction_as_candidate:
        reject_reasons.append("HEDGE_LOOKS_LIKE_AVERAGING_DOWN")

    allowed = not reject_reasons
    if not allowed:
        hedge_notional = 0.0

    return {
        "hedge_cost_usd": round(hedge_cost if allowed else 0.0, 8),
        "hedge_expected_risk_reduction_usd": round(expected_reduction if allowed else 0.0, 8),
        "hedge_net_benefit_usd": round((expected_reduction - hedge_cost) if allowed else 0.0, 8),
        "hedge_allowed": allowed,
        "hedge_reject_reasons": reject_reasons,
    }
