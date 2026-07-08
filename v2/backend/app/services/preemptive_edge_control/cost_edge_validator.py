"""Pre-trade edge after observed costs.

The admission layer must reason about net edge before any fill. This module is
pure and paper/live-dry-run safe: it only normalizes candidate fields and emits
block reasons.
"""

from __future__ import annotations

from typing import Any


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def assess_cost_edge(candidate: dict[str, Any]) -> dict[str, Any]:
    spread = _f(
        candidate.get("actual_observed_spread_entry_bps")
        or candidate.get("observed_spread_bps")
        or candidate.get("bid_ask_spread_bps")
        or candidate.get("spread_bps")
    )
    slippage = _f(candidate.get("expected_slippage_bps") or candidate.get("slippage_bps"))
    fee = _f(candidate.get("pre_trade_fee_bps") or candidate.get("fee_bps"))
    funding = _f(candidate.get("funding_bps") or candidate.get("funding_rate_bps"))
    gross_edge = _f(
        candidate.get("expected_move_bps")
        or candidate.get("price_target_bps")
        or candidate.get("expected_gross_move_bps")
    )
    explicit_net = _f(candidate.get("expected_move_after_cost_bps"))

    cost_parts = [value for value in (spread, slippage, fee, funding) if value is not None]
    cost_bps = sum(abs(value) for value in cost_parts) if cost_parts else None
    if explicit_net is not None:
        net_edge = explicit_net
    elif gross_edge is not None and cost_bps is not None:
        net_edge = gross_edge - cost_bps
    else:
        net_edge = None

    reasons: list[str] = []
    if net_edge is None:
        reasons.append("EXPECTED_EDGE_AFTER_COST_MISSING")
    elif net_edge <= 0:
        reasons.append("EXPECTED_EDGE_AFTER_COST_NON_POSITIVE")
    if cost_bps is None:
        reasons.append("SPREAD_SLIPPAGE_FUNDING_COST_MISSING")
    elif gross_edge is not None and gross_edge <= cost_bps:
        reasons.append("EXPECTED_MOVE_DOES_NOT_COVER_COST")

    return {
        "expected_edge_after_cost_bps": net_edge,
        "spread_slippage_funding_cost_bps": cost_bps,
        "spread_bps": spread,
        "slippage_bps": slippage,
        "fee_bps": fee,
        "funding_bps": funding,
        "cost_edge_valid": not reasons,
        "cost_edge_reasons": reasons,
    }
