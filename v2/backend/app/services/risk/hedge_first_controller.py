"""Hedge-first protection controller for negative positions.

When a position moves negative, do NOT panic-close first. Evaluate whether a
hedge reduces portfolio liquidation risk / drawdown slope / beta exposure
more than closing does. A hedge is a risk reducer, never a martingale: if it
increases portfolio maintenance margin or liquidation risk beyond its
benefit, it is rejected in favor of a partial de-risk close.

Pure computation over a portfolio snapshot; produces a plan, never an order.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from v2.backend.app.services.risk.cross_margin_liquidation import (
    marginal_liquidation_impact,
)

SCHEMA_VERSION = "hedge_first_controller_v1"

HEDGE_CANDIDATE_SYMBOLS = ("SAME_SYMBOL", "BTCUSDT", "ETHUSDT", "SOLUSDT", "TOP5_BASKET")


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _opposite(side: str) -> str:
    return "short" if str(side).lower() == "long" else "long"


def evaluate_hedge_first(
    *,
    position: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    hedge_mode: bool = False,
    generated_utc: str,
) -> dict[str, Any]:
    symbol = str(position.get("symbol") or "").upper()
    side = str(position.get("side") or "").lower()
    notional = _float(position.get("notional_usd")) or 0.0
    unrealized = _float(position.get("unrealized_pnl_usd")) or 0.0

    buffer_before = _float(snapshot.get("portfolio_liquidation_buffer_usd")) or 0.0
    worst_before = _float(snapshot.get("worst_case_liquidation_buffer_usd")) or buffer_before

    # Only negative (or worst-case-fragile) positions get a hedge evaluation.
    is_negative = unrealized < 0
    fragile = worst_before < buffer_before * 0.5

    candidates: list[dict[str, Any]] = []
    portfolio_risk_before = max(0.0, -worst_before) + max(0.0, -unrealized) + notional * 0.12
    for hedge_symbol in HEDGE_CANDIDATE_SYMBOLS:
        resolved_symbol = symbol if hedge_symbol == "SAME_SYMBOL" else hedge_symbol
        hedge_side = _opposite(side)
        if hedge_symbol == "SAME_SYMBOL" and not hedge_mode:
            candidates.append({
                "hedge_symbol": resolved_symbol, "hedge_side": hedge_side,
                "eligible": False, "reason": "same_symbol_hedge_requires_hedge_mode",
            })
            continue
        # Hedge sized to neutralize ~60% of directional exposure (partial).
        hedge_notional = round(notional * 0.6, 2)
        impact = marginal_liquidation_impact(
            snapshot=snapshot,
            added_notional_usd=hedge_notional,
            added_symbol=resolved_symbol,
            added_side=hedge_side,
        )
        # Risk reduction proxy: hedge offsets adverse beta but costs maintenance.
        risk_reduction_usd = hedge_notional * 0.6  # exposure neutralized
        net_benefit = risk_reduction_usd - impact["maintenance_margin_added_usd"]
        portfolio_risk_after = max(
            0.0,
            portfolio_risk_before - risk_reduction_usd + impact["maintenance_margin_added_usd"],
        )
        candidates.append({
            "hedge_symbol": resolved_symbol,
            "hedge_side": hedge_side,
            "eligible": True,
            "hedge_notional_usd": hedge_notional,
            "hedge_entry_type": "LIMIT_GTX_maker_first",
            "hedge_expected_cost_usd": round(hedge_notional * 6.0 / 10_000.0, 4),
            "liquidation_buffer_before_usd": impact["liquidation_buffer_before_usd"],
            "liquidation_buffer_after_usd": impact["liquidation_buffer_after_usd"],
            "worsens_liquidation_buffer": impact["worsens_liquidation_buffer"],
            "portfolio_risk_before": round(portfolio_risk_before, 2),
            "portfolio_risk_after": round(portfolio_risk_after, 2),
            "estimated_net_risk_benefit_usd": round(net_benefit, 2),
            "maintenance_drag_exceeds_benefit": net_benefit <= 0,
            "liquidation_buffer_collapses": impact["liquidation_buffer_after_usd"] <= 0,
        })

    eligible = [
        c
        for c in candidates
        if c.get("eligible")
        and c.get("estimated_net_risk_benefit_usd", 0) > 0
        and c.get("portfolio_risk_after", portfolio_risk_before) < portfolio_risk_before
        and not c.get("liquidation_buffer_collapses", True)
    ]
    eligible.sort(key=lambda c: -c["estimated_net_risk_benefit_usd"])
    best = eligible[0] if eligible else None

    # If no hedge beats holding/closing, prefer a partial de-risk close.
    hedge_required = bool((is_negative or fragile) and best is not None)
    if best is not None:
        why_hedge_beats_close = (
            f"hedge net risk benefit {best['estimated_net_risk_benefit_usd']} usd after "
            "maintenance drag; portfolio risk falls while liquidation buffer stays positive"
        )
        why_close_beats_hedge = None
        buffer_after = best["liquidation_buffer_after_usd"]
    else:
        why_hedge_beats_close = None
        why_close_beats_hedge = (
            "no hedge improves portfolio liquidation buffer beyond its maintenance-margin cost; "
            "partial reduce-only de-risk is safer"
        ) if (is_negative or fragile) else "position not negative; no action required"
        buffer_after = buffer_before

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "symbol": symbol,
        "position_side": side,
        "position_unrealized_pnl_usd": unrealized,
        "is_negative": is_negative,
        "portfolio_fragile_worst_case": fragile,
        "hedge_required": hedge_required,
        "hedge_symbol": best["hedge_symbol"] if best else None,
        "hedge_side": best["hedge_side"] if best else None,
        "hedge_notional_usd": best["hedge_notional_usd"] if best else 0.0,
        "hedge_entry_type": best["hedge_entry_type"] if best else None,
        "hedge_expected_cost_usd": best["hedge_expected_cost_usd"] if best else 0.0,
        "portfolio_risk_before": round(portfolio_risk_before, 2),
        "portfolio_risk_after": round(best["portfolio_risk_after"], 2) if best else round(portfolio_risk_before, 2),
        "liquidation_buffer_before_usd": round(buffer_before, 2),
        "liquidation_buffer_after_usd": round(buffer_after, 2),
        "why_hedge_beats_close": why_hedge_beats_close,
        "why_close_beats_hedge": why_close_beats_hedge,
        "recommended_action": "HEDGE" if hedge_required else ("PARTIAL_DERISK_CLOSE" if (is_negative or fragile) else "HOLD"),
        "hedge_exit_plan": "reduce-only close of hedge leg once portfolio buffer restored or thesis invalidated" if hedge_required else None,
        "is_martingale": False,
        "candidates": candidates,
        "places_real_order": False,
        "raw_key_exposed": False,
    }
