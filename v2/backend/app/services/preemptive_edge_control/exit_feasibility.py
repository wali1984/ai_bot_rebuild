"""Pre-entry exit feasibility checks."""

from __future__ import annotations

from typing import Any


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def assess_exit_feasibility(candidate: dict[str, Any], cost_edge: dict[str, Any]) -> dict[str, Any]:
    atr_bps = _f(
        candidate.get("entry_atr_bps")
        or candidate.get("atr_bps")
        or candidate.get("ATR_bps")
    )
    stop_distance = _f(
        candidate.get("stop_distance_bps")
        or candidate.get("stop_loss_bps")
        or candidate.get("max_loss_bps")
    )
    expected_edge = _f(cost_edge.get("expected_edge_after_cost_bps"))
    cost_bps = _f(cost_edge.get("spread_slippage_funding_cost_bps"))
    liquidity_depth = _f(
        candidate.get("liquidity_exit_depth")
        or candidate.get("orderbook_depth_usd")
        or candidate.get("top_of_book_depth_usd")
    )
    notional = _f(
        candidate.get("gross_notional_usd")
        or candidate.get("target_notional_usd")
        or candidate.get("notional")
    )

    reasons: list[str] = []
    score = 1.0

    if stop_distance is None:
        score = min(score, 0.35)
        reasons.append("STOP_DISTANCE_MISSING")
    if atr_bps is None:
        score = min(score, 0.55)
        reasons.append("ATR_NOISE_MISSING")
    if stop_distance is not None and atr_bps is not None and stop_distance <= max(atr_bps * 0.75, 1.0):
        score = min(score, 0.25)
        reasons.append("STOP_DISTANCE_INSIDE_NOISE")
    if expected_edge is None:
        score = min(score, 0.35)
        reasons.append("EXPECTED_EDGE_MISSING_FOR_EXIT_PLAN")
    # ``expected_edge_after_cost_bps`` is already net of the complete observed
    # cost contract.  Comparing it with ``cost_bps`` here would charge those
    # costs a second time.  Gross-edge cost coverage is enforced upstream by
    # ``assess_cost_edge`` when a gross move is supplied; an explicit net edge
    # is required only to remain positive.
    if expected_edge is not None and stop_distance is not None and expected_edge <= stop_distance * 0.5:
        score = min(score, 0.4)
        reasons.append("MFE_REQUIRED_UNREALISTIC_FOR_STOP_RISK")
    if liquidity_depth is not None and notional is not None and liquidity_depth < notional * 3.0:
        score = min(score, 0.45)
        reasons.append("EXIT_DEPTH_INSUFFICIENT")

    mfe_required = None
    if cost_bps is not None and stop_distance is not None:
        # Gross MFE needed to cover observed costs and retain the existing
        # half-stop reward/risk margin.  This is reported for audit; the
        # corresponding admission comparison above is performed in net units.
        mfe_required = cost_bps + max(stop_distance * 0.5, 0.0)

    return {
        "exit_feasibility_score": round(score, 8),
        "exit_feasibility_reasons": reasons,
        "stop_distance_bps": stop_distance,
        "ATR_bps": atr_bps,
        "stop_distance_vs_noise": (
            stop_distance / atr_bps if stop_distance is not None and atr_bps and atr_bps > 0 else None
        ),
        "MFE_required_to_profit": mfe_required,
        "MAE_risk": stop_distance,
        "timeframe_thesis_hold_window": candidate.get("timeframe"),
        "liquidity_exit_depth": liquidity_depth,
        "close_or_reduce_plan": {
            "close_allowed": True,
            "reduce_allowed": True,
            "paper_only": candidate.get("paper_only") is not False,
            "places_real_order": False,
        },
    }
