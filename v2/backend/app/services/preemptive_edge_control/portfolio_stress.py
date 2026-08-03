"""Portfolio stress and edge-linked capital simulation."""

from __future__ import annotations

from typing import Any


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _trust_score(candidate: dict[str, Any]) -> float | None:
    trust = _f(
        _first_present(
            candidate.get("composite_microstructure_trust_score"),
            candidate.get("microstructure_trust_score"),
            candidate.get("market_state_integrity_score"),
        )
    )
    if trust is None:
        return None
    return trust / 100.0 if trust > 1.0 else trust


def assess_portfolio_stress(candidate: dict[str, Any], *, expected_edge_after_cost_bps: float | None, bucket_profit_factor: float | None) -> dict[str, Any]:
    notional = _f(
        _first_present(
            candidate.get("target_notional_usd"),
            candidate.get("gross_notional_usd"),
            candidate.get("notional"),
        )
    ) or 0.0
    margin = _f(_first_present(candidate.get("allocated_margin_usd"), candidate.get("margin"))) or 0.0
    leverage = _f(
        _first_present(
            candidate.get("recommended_leverage"),
            candidate.get("leverage_recommendation"),
        )
    )
    if leverage is None and margin > 0:
        leverage = notional / margin if margin else 1.0
    if leverage is None:
        leverage = 1.0
    stop_bps = _f(_first_present(candidate.get("stop_distance_bps"), candidate.get("max_loss_bps"))) or 0.0
    max_loss = notional * max(stop_bps, 0.0) / 10000.0 if notional else 0.0

    reasons: list[str] = []
    adjusted_notional = notional
    adjusted_leverage = leverage
    if expected_edge_after_cost_bps is None or expected_edge_after_cost_bps <= 0:
        adjusted_notional = 0.0
        reasons.append("EXPECTANCY_NON_POSITIVE_TARGET_NOTIONAL_ZERO")
    if bucket_profit_factor is not None and bucket_profit_factor < 1.0:
        adjusted_leverage = min(adjusted_leverage, 1.0)
        adjusted_notional = 0.0
        reasons.append("BUCKET_PF_BELOW_1_NO_LEVERAGE_INCREASE")
    trust = _trust_score(candidate)
    if trust is not None and trust < 0.45:
        adjusted_notional *= 0.25
        reasons.append("LOW_MICROSTRUCTURE_TRUST_SIZE_HAIRCUT")

    exposure_after = _f(candidate.get("portfolio_exposure_after_trade"))
    if exposure_after is None:
        exposure_after = adjusted_notional
    correlation_after = _f(
        _first_present(
            candidate.get("correlation_exposure_after_trade"),
            candidate.get("correlation_exposure_pct"),
        )
    )
    risk_budget = _f(candidate.get("risk_budget_usd"))
    risk_of_ruin_delta = min(1.0, (max_loss / max(adjusted_notional, 1.0)) if max_loss else 0.0)

    return {
        "target_notional_usd": round(adjusted_notional, 8),
        "allocated_margin_usd": margin if adjusted_notional > 0 else 0.0,
        "recommended_leverage": round(adjusted_leverage, 8),
        "recommended_margin_mode": _first_present(
            candidate.get("recommended_margin_mode"),
            candidate.get("margin_mode_recommendation"),
            "isolated_paper_simulated",
        ),
        "risk_budget_usd": risk_budget if risk_budget is not None else max_loss,
        "max_loss_if_stop_hit": max_loss,
        "liquidation_price": _f(candidate.get("liquidation_price")),
        "liquidation_buffer": _f(candidate.get("liquidation_buffer_bps")),
        "risk_of_ruin_delta": round(risk_of_ruin_delta, 8),
        "portfolio_exposure_after_trade": exposure_after,
        "correlation_exposure_after_trade": correlation_after,
        "portfolio_stress_after_trade": {
            "status": "BLOCKED_BY_PREEMPTIVE_EDGE" if adjusted_notional <= 0 else "SIMULATED",
            "reasons": reasons,
            "paper_only": True,
            "places_real_order": False,
        },
    }
