from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


@dataclass(frozen=True)
class AdaptiveHedgeConfig:
    max_hedge_budget_usd: float = 25.0
    max_hedge_ratio: float = 0.35
    require_risk_approval: bool = True


def evaluate_adaptive_hedge(
    *,
    position: dict[str, Any],
    hedge_intent: dict[str, Any] | None,
    config: AdaptiveHedgeConfig | None = None,
) -> dict[str, Any]:
    cfg = config or AdaptiveHedgeConfig()
    intent = dict(hedge_intent or {})
    blockers: list[str] = []
    if intent.get("hedge_intent") is not True:
        blockers.append("HEDGE_INTENT_REQUIRED")
    if not intent.get("hedge_reason"):
        blockers.append("HEDGE_REASON_REQUIRED")
    if not intent.get("unhedge_condition") and not intent.get("hedge_exit_reason"):
        blockers.append("HEDGE_EXIT_CONDITION_REQUIRED")
    budget = _float(intent.get("hedge_budget_usd"))
    if budget <= 0.0:
        blockers.append("HEDGE_BUDGET_REQUIRED")
    if budget > cfg.max_hedge_budget_usd:
        blockers.append("HEDGE_BUDGET_EXCEEDS_CAP")
    if cfg.require_risk_approval and intent.get("risk_approved") is not True:
        blockers.append("HEDGE_RISK_APPROVAL_REQUIRED")

    position_symbol = str(position.get("symbol") or "").upper()
    hedge_symbol = str(intent.get("symbol") or position_symbol).upper()
    position_side = str(position.get("side") or "").lower()
    hedge_side = str(intent.get("hedge_side") or intent.get("side") or "").lower()
    if position_symbol == hedge_symbol and {position_side, hedge_side} == {"long", "short"} and intent.get("hedge_intent") is not True:
        blockers.append("ACCIDENTAL_SAME_SYMBOL_HEDGE_BLOCKED")

    notional = _float(position.get("notional") or position.get("notional_usd"))
    requested = min(budget, max(0.0, notional * cfg.max_hedge_ratio))
    allowed = not blockers
    return {
        "hedge_allowed": allowed,
        "hedge_blockers": blockers,
        "hedge_type": intent.get("hedge_type") or "explicit_adaptive_hedge",
        "hedge_reason": intent.get("hedge_reason"),
        "hedge_exit_reason": intent.get("hedge_exit_reason") or intent.get("unhedge_condition"),
        "hedge_budget_usd": budget,
        "approved_hedge_notional_usd": requested if allowed else 0.0,
        "same_symbol_accidental_hedge_blocked": "ACCIDENTAL_SAME_SYMBOL_HEDGE_BLOCKED" in blockers,
        "requires_unhedge_condition": True,
        "paper_only": True,
        "places_real_order": False,
    }


def build_hedge_cost_benefit(
    *,
    hedge_id: str,
    hedge_notional_usd: float,
    fees: float,
    slippage: float,
    pnl_without_hedge: float,
    pnl_with_hedge: float,
) -> dict[str, Any]:
    cost = max(0.0, _float(fees) + _float(slippage))
    benefit = _float(pnl_with_hedge) - _float(pnl_without_hedge)
    return {
        "hedge_id": hedge_id,
        "hedge_notional_usd": _float(hedge_notional_usd),
        "hedge_cost_usd": cost,
        "hedge_benefit_usd": benefit,
        "net_hedge_benefit_usd": benefit - cost,
        "hedge_cost_benefit_tracked": True,
        "paper_only": True,
        "places_real_order": False,
    }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def evaluate_adaptive_hedge_trigger(
    *,
    position_payload: dict[str, Any],
    pnl_bps: float | None,
    atr_stop_bps: float | None,
    portfolio_drawdown_bps: float = 0.0,
    drawdown_emergency_bps: float = 350.0,
    fee_bps: float = 4.0,
    slippage_bps: float = 2.0,
) -> dict[str, Any]:
    """Adaptive hedge trigger for an open paper position under adverse move.

    Operator requirement (2026-07-16): hedge instead of eating the full ATR
    stop, with everything scaled off the position's own state — NO fixed bps
    thresholds. High-confidence positions hedge EARLIER (they carry the most
    notional under adaptive sizing, so an unhedged stop-out there dominates
    portfolio expectancy).

    All bounds are fractions of the position's own ATR stop and excursions:
    - arm_fraction: fraction of the stop distance at which the hedge arms,
      shrinking with confidence and portfolio drawdown pressure.
    - hedge_ratio: fraction of the parent quantity to hedge, growing with
      confidence and adverse depth.
    - fee guard: the protection bought (remaining stop distance x ratio) must
      exceed the round-trip cost of the hedge leg, or no trigger.
    """
    hedge_state = str(position_payload.get("hedge_state") or "NO_HEDGE").upper()
    if hedge_state not in ("", "NO_HEDGE", "NONE"):
        return {"trigger": False, "reason": f"HEDGE_STATE_{hedge_state}_NOT_ELIGIBLE"}
    if pnl_bps is None or pnl_bps >= 0:
        return {"trigger": False, "reason": "POSITION_NOT_IN_ADVERSE_EXCURSION"}
    if atr_stop_bps is None or atr_stop_bps <= 0:
        return {"trigger": False, "reason": "ATR_STOP_DISTANCE_UNAVAILABLE"}
    adverse_bps = -float(pnl_bps)
    adverse_ratio = adverse_bps / float(atr_stop_bps)
    confidence = _float(
        position_payload.get("confidence_calibrated"),
        _float(position_payload.get("confidence_raw"), 0.5),
    )
    confidence_pressure = _clamp((confidence - 0.5) / 0.5, 0.0, 1.0)
    dd_pressure = _clamp(
        abs(_float(portfolio_drawdown_bps)) / max(1.0, abs(_float(drawdown_emergency_bps, 350.0))),
        0.0,
        1.0,
    )
    arm_fraction = _clamp(1.0 - 0.45 * confidence_pressure - 0.15 * dd_pressure, 0.35, 0.95)
    if adverse_ratio < arm_fraction:
        return {
            "trigger": False,
            "reason": "ADVERSE_RATIO_BELOW_ADAPTIVE_ARM_FRACTION",
            "adverse_ratio": round(adverse_ratio, 6),
            "arm_fraction": round(arm_fraction, 6),
        }
    # Only hedge while the adverse move is persisting (mark near max adverse
    # excursion). A position already recovering keeps its thesis unhedged.
    mae_bps = _float(position_payload.get("mae_bps"))
    if mae_bps > 0 and adverse_bps < 0.9 * mae_bps:
        return {
            "trigger": False,
            "reason": "ADVERSE_MOVE_ALREADY_RECOVERING_FROM_MAE",
            "adverse_bps": round(adverse_bps, 4),
            "mae_bps": round(mae_bps, 4),
        }
    hedge_ratio = _clamp(
        0.25 + 0.5 * confidence_pressure + 0.25 * min(1.0, adverse_ratio),
        0.25,
        0.9,
    )
    remaining_stop_bps = max(0.0, float(atr_stop_bps) - adverse_bps)
    expected_protection_bps = (adverse_bps + remaining_stop_bps) * hedge_ratio
    round_trip_cost_bps = (max(0.0, _float(fee_bps, 4.0)) + max(0.0, _float(slippage_bps, 2.0))) * 2.0
    if expected_protection_bps <= round_trip_cost_bps:
        return {
            "trigger": False,
            "reason": "HEDGE_COST_EXCEEDS_EXPECTED_PROTECTION",
            "expected_protection_bps": round(expected_protection_bps, 4),
            "round_trip_cost_bps": round(round_trip_cost_bps, 4),
        }
    side = str(position_payload.get("side") or "").lower()
    return {
        "trigger": True,
        "reason": "ADAPTIVE_ADVERSE_EXCURSION_HEDGE",
        "hedge_side": "long" if side == "short" else "short",
        "hedge_ratio": round(hedge_ratio, 6),
        "adverse_ratio": round(adverse_ratio, 6),
        "arm_fraction": round(arm_fraction, 6),
        "confidence_pressure": round(confidence_pressure, 6),
        "drawdown_pressure": round(dd_pressure, 6),
        "expected_protection_bps": round(expected_protection_bps, 4),
        "round_trip_cost_bps": round(round_trip_cost_bps, 4),
        "paper_only": True,
        "places_real_order": False,
    }


def evaluate_adaptive_hedge_unwind(
    *,
    parent_payload: dict[str, Any],
    hedge_payload: dict[str, Any],
    parent_pnl_bps: float | None,
    hedge_pnl_bps: float | None,
    hedge_best_excursion_bps: float | None,
    parent_atr_stop_bps: float | None,
    hedge_hold_seconds: float | None = None,
    max_hold_seconds: float | None = None,
    fee_bps: float = 4.0,
    slippage_bps: float = 2.0,
) -> dict[str, Any]:
    """Adaptive pair management for an active parent+hedge pair.

    Actions: HOLD | UNWIND_HEDGE | CLOSE_BOTH | ORPHAN_UNWIND. All bounds are
    fractions of the pair's own excursions/stop — no fixed bps constants.
    - UNWIND_HEDGE: the adverse move exhausted (hedge leg retraced an adaptive
      fraction of its own best excursion — hedge banks its profit, parent
      thesis resumes) or the parent recovered past its hedge-entry PnL plus
      round-trip cost.
    - CLOSE_BOTH: pair net PnL breached an adaptive multiple of the parent's
      own ATR stop, or the pair exceeded its maximum hold.
    """
    if not parent_payload:
        return {"action": "ORPHAN_UNWIND", "reason": "PARENT_POSITION_MISSING"}
    parent_pnl = _float(parent_pnl_bps)
    hedge_pnl = _float(hedge_pnl_bps)
    net_pair_pnl_bps = parent_pnl + hedge_pnl
    round_trip_cost_bps = (max(0.0, _float(fee_bps, 4.0)) + max(0.0, _float(slippage_bps, 2.0))) * 2.0
    parent_pnl_at_hedge = _float(hedge_payload.get("hedge_entry_parent_pnl_bps"))
    if max_hold_seconds and hedge_hold_seconds and hedge_hold_seconds >= max_hold_seconds:
        return {
            "action": "CLOSE_BOTH",
            "reason": "HEDGE_PAIR_MAX_HOLD_EXCEEDED",
            "net_pair_pnl_bps": round(net_pair_pnl_bps, 4),
        }
    if parent_atr_stop_bps and parent_atr_stop_bps > 0:
        # Pair drawdown measures deterioration SINCE hedge entry (the hedge
        # leg starts at 0 and the parent's adverse excursion at hedge entry is
        # the baseline) — the pair must not bleed another adaptive multiple of
        # the parent's own stop after hedging.
        pair_dd_limit_bps = 1.5 * float(parent_atr_stop_bps)
        additional_drawdown_bps = parent_pnl_at_hedge - net_pair_pnl_bps
        if additional_drawdown_bps >= pair_dd_limit_bps:
            return {
                "action": "CLOSE_BOTH",
                "reason": "PAIR_DRAWDOWN_EXCEEDED_ADAPTIVE_LIMIT",
                "net_pair_pnl_bps": round(net_pair_pnl_bps, 4),
                "additional_drawdown_since_hedge_bps": round(additional_drawdown_bps, 4),
                "pair_drawdown_limit_bps": round(pair_dd_limit_bps, 4),
            }
    confidence = _float(
        parent_payload.get("confidence_calibrated"),
        _float(parent_payload.get("confidence_raw"), 0.5),
    )
    confidence_pressure = _clamp((confidence - 0.5) / 0.5, 0.0, 1.0)
    if parent_pnl >= parent_pnl_at_hedge + round_trip_cost_bps and parent_pnl > -round_trip_cost_bps:
        return {
            "action": "UNWIND_HEDGE",
            "reason": "PARENT_THESIS_RESUMED_PAST_HEDGE_ENTRY",
            "net_pair_pnl_bps": round(net_pair_pnl_bps, 4),
            "parent_pnl_bps": round(parent_pnl, 4),
            "parent_pnl_at_hedge_bps": round(parent_pnl_at_hedge, 4),
        }
    best_excursion = _float(hedge_best_excursion_bps)
    if best_excursion > round_trip_cost_bps:
        exhaustion_fraction = _clamp(0.35 + 0.3 * (1.0 - confidence_pressure), 0.35, 0.75)
        retrace_bps = best_excursion - hedge_pnl
        if retrace_bps >= exhaustion_fraction * best_excursion:
            return {
                "action": "UNWIND_HEDGE",
                "reason": "ADVERSE_MOVE_EXHAUSTED_HEDGE_BANKS_PROFIT",
                "net_pair_pnl_bps": round(net_pair_pnl_bps, 4),
                "hedge_best_excursion_bps": round(best_excursion, 4),
                "hedge_retrace_bps": round(retrace_bps, 4),
                "exhaustion_fraction": round(exhaustion_fraction, 6),
            }
    return {
        "action": "HOLD",
        "net_pair_pnl_bps": round(net_pair_pnl_bps, 4),
        "parent_pnl_bps": round(parent_pnl, 4),
        "hedge_pnl_bps": round(hedge_pnl, 4),
    }


__all__ = [
    "AdaptiveHedgeConfig",
    "evaluate_adaptive_hedge",
    "build_hedge_cost_benefit",
    "evaluate_adaptive_hedge_trigger",
    "evaluate_adaptive_hedge_unwind",
]
