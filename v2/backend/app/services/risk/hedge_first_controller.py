"""Hedge-first protection controller for negative positions.

When a position moves negative, do NOT panic-close first. Evaluate whether a
hedge reduces portfolio liquidation risk / drawdown slope / beta exposure
more than closing does. A hedge is a risk reducer, never a martingale: if it
increases portfolio maintenance margin or liquidation risk beyond its
benefit, it is rejected in favor of a partial de-risk close.

Pure computation over a portfolio snapshot; produces a plan, never an order.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from v2.backend.app.services.risk.cross_margin_liquidation import (
    SCHEMA_VERSION as LIQUIDATION_SCHEMA_VERSION,
)
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


def _sha256_present(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _snapshot_evidence(
    snapshot: Any,
) -> tuple[float | None, float | None, list[str]]:
    """Validate all liquidation/stress evidence before decision arithmetic."""

    if not isinstance(snapshot, Mapping):
        return None, None, ["PORTFOLIO_STRESS_SNAPSHOT_NOT_MAPPING"]

    reasons: list[str] = []
    if snapshot.get("schema_version") != LIQUIDATION_SCHEMA_VERSION:
        reasons.append("PORTFOLIO_STRESS_SCHEMA_INVALID")
    if snapshot.get("authority_complete") is not True:
        reasons.append("PORTFOLIO_STRESS_NOT_AUTHORITATIVE")
    if snapshot.get("portfolio_level_computed") is not True:
        reasons.append("PORTFOLIO_STRESS_NOT_PORTFOLIO_LEVEL")
    if snapshot.get("adaptive_stress_authority_complete") is not True:
        reasons.append("PORTFOLIO_ADAPTIVE_STRESS_AUTHORITY_INCOMPLETE")
    if not _sha256_present(snapshot.get("adaptive_stress_evidence_sha256")):
        reasons.append("PORTFOLIO_ADAPTIVE_STRESS_HASH_INVALID")
    if snapshot.get("per_position_only") is not False:
        reasons.append("PORTFOLIO_STRESS_PER_POSITION_ONLY_INVALID")
    if snapshot.get("risk_decision_blocked") is not False:
        reasons.append("PORTFOLIO_STRESS_RISK_DECISION_BLOCKED")
    if snapshot.get("block_reasons") != []:
        reasons.append("PORTFOLIO_STRESS_BLOCK_REASONS_NOT_EMPTY")
    if not _sha256_present(snapshot.get("portfolio_snapshot_sha256")):
        reasons.append("PORTFOLIO_STRESS_PROVENANCE_HASH_INVALID")
    if not (
        snapshot.get("paper_only") is True
        and snapshot.get("routes_to_live") is False
        and snapshot.get("places_real_order") is False
    ):
        reasons.append("PORTFOLIO_STRESS_PAPER_ROUTE_SAFETY_INVALID")
    if reasons:
        return None, None, list(dict.fromkeys(reasons))

    open_position_count = snapshot.get("open_position_count")
    if (
        isinstance(open_position_count, bool)
        or not isinstance(open_position_count, int)
        or open_position_count <= 0
    ):
        reasons.append("PORTFOLIO_STRESS_OPEN_POSITION_COUNT_INVALID")

    buffer_before = _float(snapshot.get("portfolio_liquidation_buffer_usd"))
    worst_before = _float(snapshot.get("worst_case_liquidation_buffer_usd"))
    if buffer_before is None:
        reasons.append("PORTFOLIO_LIQUIDATION_BUFFER_MISSING_OR_NONFINITE")
    if worst_before is None:
        reasons.append("WORST_CASE_LIQUIDATION_BUFFER_MISSING_OR_NONFINITE")

    scenarios = snapshot.get("correlated_shock_scenarios")
    worst_scenario = snapshot.get("worst_case_scenario")
    if not isinstance(scenarios, Mapping) or not scenarios:
        reasons.append("CORRELATED_STRESS_SCENARIOS_MISSING_OR_MALFORMED")
    else:
        for scenario_name, scenario in scenarios.items():
            if not isinstance(scenario_name, str) or not scenario_name:
                reasons.append("CORRELATED_STRESS_SCENARIO_NAME_INVALID")
                continue
            if not isinstance(scenario, Mapping):
                reasons.append(f"CORRELATED_STRESS_SCENARIO_MALFORMED:{scenario_name}")
                continue
            numeric_fields = (
                "portfolio_pnl_delta_usd",
                "shocked_margin_balance_usd",
                "shocked_maintenance_margin_usd",
                "shocked_liquidation_buffer_usd",
            )
            if any(_float(scenario.get(field)) is None for field in numeric_fields):
                reasons.append(f"CORRELATED_STRESS_SCENARIO_NUMERIC_EVIDENCE_INVALID:{scenario_name}")
            if not isinstance(scenario.get("symbol_moves"), Mapping):
                reasons.append(
                    f"CORRELATED_STRESS_SCENARIO_SYMBOL_MOVES_INVALID:{scenario_name}"
                )
            if not isinstance(scenario.get("liquidation_breached"), bool):
                reasons.append(f"CORRELATED_STRESS_SCENARIO_BREACH_FLAG_INVALID:{scenario_name}")

        if not isinstance(worst_scenario, str) or worst_scenario not in scenarios:
            reasons.append("WORST_CASE_STRESS_SCENARIO_INVALID")
        elif isinstance(scenarios.get(worst_scenario), Mapping) and worst_before is not None:
            scenario_buffer = _float(
                scenarios[worst_scenario].get("shocked_liquidation_buffer_usd")
            )
            if scenario_buffer is not None and not math.isclose(
                scenario_buffer,
                worst_before,
                rel_tol=1e-9,
                abs_tol=1e-7,
            ):
                reasons.append("WORST_CASE_STRESS_BUFFER_MISMATCH")

    if not isinstance(snapshot.get("worst_case_liquidation_breached"), bool):
        reasons.append("WORST_CASE_LIQUIDATION_BREACH_FLAG_INVALID")
    if buffer_before is not None and worst_before is not None and worst_before > buffer_before:
        reasons.append("WORST_CASE_LIQUIDATION_BUFFER_EXCEEDS_CURRENT")

    return buffer_before, worst_before, list(dict.fromkeys(reasons))


def _marginal_evidence(
    impact: Any,
    *,
    expected_buffer_before: float,
    expected_symbol: str,
    expected_side: str,
    expected_stress_hash: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Normalize a marginal result only after its authority is established."""

    if not isinstance(impact, Mapping):
        return None, ["MARGINAL_LIQUIDATION_EVIDENCE_NOT_MAPPING"]

    reasons: list[str] = []
    if impact.get("authority_complete") is not True:
        reasons.append("MARGINAL_LIQUIDATION_EVIDENCE_NOT_AUTHORITATIVE")
    if impact.get("risk_decision_blocked") is not False:
        reasons.append("MARGINAL_LIQUIDATION_EVIDENCE_BLOCKED")
    if impact.get("block_reasons") != []:
        reasons.append("MARGINAL_LIQUIDATION_BLOCK_REASONS_NOT_EMPTY")
    if reasons:
        return None, list(dict.fromkeys(reasons))

    before = _float(impact.get("liquidation_buffer_before_usd"))
    after = _float(impact.get("liquidation_buffer_after_usd"))
    maintenance = _float(impact.get("maintenance_margin_added_usd"))
    improvement = _float(impact.get("marginal_stress_buffer_improvement_usd"))
    if before is None:
        reasons.append("MARGINAL_LIQUIDATION_BUFFER_BEFORE_INVALID")
    if after is None:
        reasons.append("MARGINAL_LIQUIDATION_BUFFER_AFTER_INVALID")
    if maintenance is None or maintenance < 0.0:
        reasons.append("MARGINAL_MAINTENANCE_MARGIN_INVALID")
    if improvement is None:
        reasons.append("MARGINAL_STRESS_BUFFER_IMPROVEMENT_INVALID")
    if not isinstance(impact.get("worsens_liquidation_buffer"), bool):
        reasons.append("MARGINAL_LIQUIDATION_WORSENS_FLAG_INVALID")
    if str(impact.get("added_symbol") or "").upper() != expected_symbol:
        reasons.append("MARGINAL_LIQUIDATION_SYMBOL_MISMATCH")
    if str(impact.get("added_side") or "").lower() != expected_side:
        reasons.append("MARGINAL_LIQUIDATION_SIDE_MISMATCH")
    if impact.get("adaptive_stress_evidence_sha256") != expected_stress_hash:
        reasons.append("MARGINAL_ADAPTIVE_STRESS_HASH_MISMATCH")

    if reasons:
        return None, list(dict.fromkeys(reasons))

    assert (
        before is not None
        and after is not None
        and maintenance is not None
        and improvement is not None
    )
    if not math.isclose(before, expected_buffer_before, rel_tol=1e-9, abs_tol=1e-7):
        reasons.append("MARGINAL_LIQUIDATION_BUFFER_BEFORE_MISMATCH")
    if not math.isclose(
        improvement,
        after - before,
        rel_tol=1e-9,
        abs_tol=1e-7,
    ):
        reasons.append("MARGINAL_STRESS_IMPROVEMENT_ARITHMETIC_INCOHERENT")
    if impact.get("worsens_liquidation_buffer") is not (after < before):
        reasons.append("MARGINAL_LIQUIDATION_WORSENS_FLAG_INCOHERENT")
    if reasons:
        return None, reasons
    return {
        "liquidation_buffer_before_usd": before,
        "liquidation_buffer_after_usd": after,
        "maintenance_margin_added_usd": maintenance,
        "marginal_stress_buffer_improvement_usd": improvement,
        "worsens_liquidation_buffer": impact["worsens_liquidation_buffer"],
    }, []


def _blocked_result(
    *,
    generated_utc: str,
    symbol: str,
    side: str,
    unrealized: float | None,
    reasons: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "symbol": symbol,
        "position_side": side or None,
        "position_unrealized_pnl_usd": unrealized,
        "is_negative": None,
        "portfolio_fragile_worst_case": None,
        "hedge_required": False,
        "hedge_symbol": None,
        "hedge_side": None,
        "hedge_notional_usd": None,
        "hedge_entry_type": None,
        "hedge_expected_cost_usd": None,
        "portfolio_risk_before": None,
        "portfolio_risk_after": None,
        "liquidation_buffer_before_usd": None,
        "liquidation_buffer_after_usd": None,
        "why_hedge_beats_close": None,
        "why_close_beats_hedge": None,
        "recommended_action": "BLOCKED",
        "hedge_exit_plan": None,
        "is_martingale": False,
        "candidates": [],
        "authority_complete": False,
        "risk_decision_blocked": True,
        "block_reasons": list(dict.fromkeys(reasons)),
        "places_real_order": False,
        "raw_key_exposed": False,
    }


def evaluate_hedge_first(
    *,
    position: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    hedge_mode: bool = False,
    generated_utc: str,
) -> dict[str, Any]:
    if not isinstance(position, Mapping):
        return _blocked_result(
            generated_utc=generated_utc,
            symbol="",
            side="",
            unrealized=None,
            reasons=["POSITION_EVIDENCE_NOT_MAPPING"],
        )

    symbol = str(position.get("symbol") or "").strip().upper()
    side = str(position.get("side") or "").strip().lower()
    buffer_before, worst_before, snapshot_reasons = _snapshot_evidence(snapshot)
    if snapshot_reasons:
        return _blocked_result(
            generated_utc=generated_utc,
            symbol=symbol,
            side=side,
            unrealized=None,
            reasons=snapshot_reasons,
        )

    notional = _float(position.get("notional_usd"))
    unrealized = _float(position.get("unrealized_pnl_usd"))
    position_reasons: list[str] = []
    if not symbol:
        position_reasons.append("POSITION_SYMBOL_MISSING")
    if side not in {"long", "short"}:
        position_reasons.append("POSITION_SIDE_INVALID")
    if notional is None or notional <= 0.0:
        position_reasons.append("POSITION_NOTIONAL_MISSING_NONFINITE_OR_NON_POSITIVE")
    if unrealized is None:
        position_reasons.append("POSITION_UNREALIZED_PNL_MISSING_OR_NONFINITE")

    if position_reasons:
        return _blocked_result(
            generated_utc=generated_utc,
            symbol=symbol,
            side=side,
            unrealized=unrealized,
            reasons=position_reasons,
        )

    assert notional is not None and unrealized is not None
    assert buffer_before is not None and worst_before is not None
    maintenance_by_symbol = snapshot.get("hedge_candidate_maintenance")
    if not isinstance(maintenance_by_symbol, Mapping):
        return _blocked_result(
            generated_utc=generated_utc,
            symbol=symbol,
            side=side,
            unrealized=unrealized,
            reasons=["HEDGE_CANDIDATE_MAINTENANCE_EVIDENCE_MISSING"],
        )

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
        maintenance = maintenance_by_symbol.get(resolved_symbol)
        if not isinstance(maintenance, Mapping):
            return _blocked_result(
                generated_utc=generated_utc,
                symbol=symbol,
                side=side,
                unrealized=unrealized,
                reasons=[f"HEDGE_CANDIDATE_MAINTENANCE_MISSING:{resolved_symbol}"],
            )
        maint_rate = _float(maintenance.get("maintenance_margin_rate"))
        maint_cum = _float(maintenance.get("maintenance_margin_cum"))
        if (
            maintenance.get("authority_complete") is not True
            or not _sha256_present(maintenance.get("evidence_sha256"))
            or maint_rate is None
            or not 0.0 < maint_rate < 1.0
            or maint_cum is None
            or maint_cum < 0.0
        ):
            return _blocked_result(
                generated_utc=generated_utc,
                symbol=symbol,
                side=side,
                unrealized=unrealized,
                reasons=[f"HEDGE_CANDIDATE_MAINTENANCE_INVALID:{resolved_symbol}"],
            )
        # Hedge sized to neutralize ~60% of directional exposure (partial).
        hedge_notional = round(notional * 0.6, 2)
        try:
            raw_impact = marginal_liquidation_impact(
                snapshot=snapshot,
                added_notional_usd=hedge_notional,
                added_symbol=resolved_symbol,
                added_side=hedge_side,
                added_maint_rate=maint_rate,
                added_maint_cum=maint_cum,
            )
        except Exception as exc:  # noqa: BLE001 - risk decisions must fail closed
            return _blocked_result(
                generated_utc=generated_utc,
                symbol=symbol,
                side=side,
                unrealized=unrealized,
                reasons=[f"MARGINAL_LIQUIDATION_EVALUATION_FAILED:{type(exc).__name__}"],
            )
        impact, impact_reasons = _marginal_evidence(
            raw_impact,
            expected_buffer_before=worst_before,
            expected_symbol=resolved_symbol,
            expected_side=hedge_side,
            expected_stress_hash=str(snapshot["adaptive_stress_evidence_sha256"]),
        )
        if impact is None:
            return _blocked_result(
                generated_utc=generated_utc,
                symbol=symbol,
                side=side,
                unrealized=unrealized,
                reasons=impact_reasons,
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
        buffer_after = worst_before

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
        "portfolio_risk_after": (
            round(best["portfolio_risk_after"], 2)
            if best
            else round(portfolio_risk_before, 2)
        ),
        "liquidation_buffer_before_usd": round(worst_before, 2),
        "liquidation_buffer_after_usd": round(buffer_after, 2),
        "why_hedge_beats_close": why_hedge_beats_close,
        "why_close_beats_hedge": why_close_beats_hedge,
        "recommended_action": (
            "HEDGE"
            if hedge_required
            else ("PARTIAL_DERISK_CLOSE" if (is_negative or fragile) else "HOLD")
        ),
        "hedge_exit_plan": (
            "reduce-only close of hedge leg once portfolio buffer restored or thesis invalidated"
            if hedge_required
            else None
        ),
        "is_martingale": False,
        "candidates": candidates,
        "authority_complete": True,
        "risk_decision_blocked": False,
        "block_reasons": [],
        "places_real_order": False,
        "raw_key_exposed": False,
    }
