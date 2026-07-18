"""Evidence-driven leverage exploration for trainer backtests (study-only).

This module does not size an order, mutate a margin mode, or route to live.  It
answers a narrower question: *given a complete, point-in-time risk estimate,
which leverage in the study grid has the best positive certainty equivalent?*

The inputs deliberately separate allocated margin from gross notional.  For a
fixed ``base_margin_usd``, gross notional is ``base_margin_usd * leverage``.
Both expected return and tail loss therefore grow with leverage.  The score is
the expected log change in account equity under a two-outcome approximation,
after conservatively shrinking the measured after-cost edge by its uncertainty,
drawdown, regime risk, and liquidity quality.  Unlike the former
``edge * leverage * (1 / leverage)`` score, this has real curvature and can
select 1x, 2x, or 3x rather than resolving every tie to the first grid item.

Missing evidence never becomes a default assumption.  It produces no leverage
recommendation.  Immutable study caps may be tightened by a caller but cannot
be widened.  Cross margin is reported as not evaluated because this local
candidate study has no account-wide covariance or contagion model; the
portfolio-aware paper allocator remains the authority for simulated margin.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "trainer_leverage_margin_exploration_v2"

DEFAULT_LEVERAGE_GRID: tuple[float, ...] = (1.0, 2.0, 3.0)
DEFAULT_MARGIN_MODES: tuple[str, ...] = ("isolated", "cross")

# Immutable study-only safety envelope.  A caller may tighten the liquidation
# floor or loss cap, but cannot loosen either value and cannot study leverage
# above the range that this component previously explored.
HARD_MAX_STUDY_LEVERAGE = 3.0
DEFAULT_MIN_LIQUIDATION_BUFFER_BPS = 500.0
DEFAULT_MAX_LOSS_FRACTION_OF_EQUITY = 0.01

REQUIRED_EVIDENCE_FIELDS: tuple[str, ...] = (
    "expected_move_after_cost_bps",
    "edge_uncertainty_bps",
    "edge_evidence_count",
    "edge_evidence_source",
    "edge_available_at",
    "loss_probability",
    "stop_distance_bps",
    "modeled_adverse_move_bps",
    "execution_uncertainty_bps",
    "equity_usd",
    "base_margin_usd",
    "available_margin_usd",
    "base_liquidation_buffer_bps",
    "drawdown_bps",
    "regime_risk_score",
    "liquidity_score",
    "risk_context_source",
    "risk_context_available_at",
    "decision_time",
)


def _f(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nonempty_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _append_once(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 10)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def evaluate_leverage_for_candidate(
    *,
    expected_move_after_cost_bps: float | None,
    edge_uncertainty_bps: float | None = None,
    edge_evidence_count: float | None = None,
    edge_evidence_source: str | None = None,
    edge_available_at: str | None = None,
    loss_probability: float | None = None,
    stop_distance_bps: float | None = None,
    modeled_adverse_move_bps: float | None = None,
    execution_uncertainty_bps: float | None = None,
    equity_usd: float | None = None,
    base_margin_usd: float | None = None,
    available_margin_usd: float | None = None,
    base_liquidation_buffer_bps: float | None = None,
    drawdown_bps: float | None = None,
    regime_risk_score: float | None = None,
    liquidity_score: float | None = None,
    risk_context_source: str | None = None,
    risk_context_available_at: str | None = None,
    decision_time: str | None = None,
    leverage: float,
    min_liquidation_buffer_bps: float = DEFAULT_MIN_LIQUIDATION_BUFFER_BPS,
    max_loss_fraction_of_equity: float = DEFAULT_MAX_LOSS_FRACTION_OF_EQUITY,
) -> dict[str, Any]:
    """Evaluate one study leverage without mutating any execution state.

    ``edge_uncertainty_bps`` is the uncertainty width already chosen by the
    upstream estimator (for example a lower-confidence-bound half width).  The
    module does not invent a confidence level. ``loss_probability`` is the
    measured probability of the modeled adverse outcome, not model confidence.
    """

    lev = _f(leverage)
    edge = _f(expected_move_after_cost_bps)
    uncertainty = _f(edge_uncertainty_bps)
    evidence_count = _f(edge_evidence_count)
    loss_prob = _f(loss_probability)
    stop_bps = _f(stop_distance_bps)
    adverse_bps = _f(modeled_adverse_move_bps)
    execution_uncertainty = _f(execution_uncertainty_bps)
    equity = _f(equity_usd)
    base_margin = _f(base_margin_usd)
    available_margin = _f(available_margin_usd)
    base_liquidation_buffer = _f(base_liquidation_buffer_bps)
    drawdown = _f(drawdown_bps)
    regime_risk = _f(regime_risk_score)
    liquidity = _f(liquidity_score)
    requested_min_buffer = _f(min_liquidation_buffer_bps)
    requested_max_loss_fraction = _f(max_loss_fraction_of_equity)
    edge_available = _timestamp(edge_available_at)
    risk_context_available = _timestamp(risk_context_available_at)
    decision = _timestamp(decision_time)

    reasons: list[str] = []
    if lev is None or lev < 1.0:
        _append_once(reasons, "INVALID_LEVERAGE")
    elif lev > HARD_MAX_STUDY_LEVERAGE:
        _append_once(reasons, "LEVERAGE_ABOVE_IMMUTABLE_STUDY_CAP")

    if edge is None:
        _append_once(reasons, "MISSING_EXPECTED_MOVE_AFTER_COST_BPS")
    elif edge <= 0.0:
        _append_once(reasons, "NON_POSITIVE_AFTER_COST_EDGE")
    if uncertainty is None:
        _append_once(reasons, "MISSING_EDGE_UNCERTAINTY_BPS")
    elif uncertainty <= 0.0:
        _append_once(reasons, "INVALID_EDGE_UNCERTAINTY_BPS")
    if evidence_count is None:
        _append_once(reasons, "MISSING_EDGE_EVIDENCE_COUNT")
    elif evidence_count < 1.0:
        _append_once(reasons, "INVALID_EDGE_EVIDENCE_COUNT")
    if _nonempty_text(edge_evidence_source) is None:
        _append_once(reasons, "MISSING_EDGE_EVIDENCE_SOURCE")
    if edge_available is None:
        _append_once(reasons, "MISSING_OR_INVALID_EDGE_AVAILABLE_AT")
    if loss_prob is None:
        _append_once(reasons, "MISSING_LOSS_PROBABILITY")
    elif not 0.0 < loss_prob < 1.0:
        _append_once(reasons, "INVALID_LOSS_PROBABILITY")
    if stop_bps is None:
        _append_once(reasons, "MISSING_STOP_DISTANCE_BPS")
    elif stop_bps <= 0.0:
        _append_once(reasons, "INVALID_STOP_DISTANCE_BPS")
    if adverse_bps is None:
        _append_once(reasons, "MISSING_MODELED_ADVERSE_MOVE_BPS")
    elif adverse_bps <= 0.0:
        _append_once(reasons, "INVALID_MODELED_ADVERSE_MOVE_BPS")
    if execution_uncertainty is None:
        _append_once(reasons, "MISSING_EXECUTION_UNCERTAINTY_BPS")
    elif execution_uncertainty < 0.0:
        _append_once(reasons, "INVALID_EXECUTION_UNCERTAINTY_BPS")
    if equity is None:
        _append_once(reasons, "MISSING_EQUITY_USD")
    elif equity <= 0.0:
        _append_once(reasons, "INVALID_EQUITY_USD")
    if base_margin is None:
        _append_once(reasons, "MISSING_BASE_MARGIN_USD")
    elif base_margin <= 0.0:
        _append_once(reasons, "INVALID_BASE_MARGIN_USD")
    if available_margin is None:
        _append_once(reasons, "MISSING_AVAILABLE_MARGIN_USD")
    elif available_margin <= 0.0:
        _append_once(reasons, "INVALID_AVAILABLE_MARGIN_USD")
    if base_margin is not None and available_margin is not None and base_margin > available_margin:
        _append_once(reasons, "BASE_MARGIN_EXCEEDS_AVAILABLE_MARGIN")
    if base_liquidation_buffer is None:
        _append_once(reasons, "MISSING_BASE_LIQUIDATION_BUFFER_BPS")
    elif base_liquidation_buffer <= 0.0:
        _append_once(reasons, "INVALID_BASE_LIQUIDATION_BUFFER_BPS")
    if drawdown is None:
        _append_once(reasons, "MISSING_DRAWDOWN_BPS")
    elif not 0.0 <= drawdown < 10_000.0:
        _append_once(reasons, "INVALID_DRAWDOWN_BPS")
    if regime_risk is None:
        _append_once(reasons, "MISSING_REGIME_RISK_SCORE")
    elif not 0.0 <= regime_risk <= 1.0:
        _append_once(reasons, "INVALID_REGIME_RISK_SCORE")
    if liquidity is None:
        _append_once(reasons, "MISSING_LIQUIDITY_SCORE")
    elif not 0.0 < liquidity <= 1.0:
        _append_once(reasons, "INVALID_LIQUIDITY_SCORE")
    if _nonempty_text(risk_context_source) is None:
        _append_once(reasons, "MISSING_RISK_CONTEXT_SOURCE")
    if risk_context_available is None:
        _append_once(reasons, "MISSING_OR_INVALID_RISK_CONTEXT_AVAILABLE_AT")
    if decision is None:
        _append_once(reasons, "MISSING_OR_INVALID_DECISION_TIME")
    if edge_available is not None and decision is not None and edge_available > decision:
        _append_once(reasons, "EDGE_AVAILABLE_AFTER_DECISION_TIME")
    if (
        risk_context_available is not None
        and decision is not None
        and risk_context_available > decision
    ):
        _append_once(reasons, "RISK_CONTEXT_AVAILABLE_AFTER_DECISION_TIME")

    if requested_min_buffer is None or requested_min_buffer <= 0.0:
        _append_once(reasons, "INVALID_MIN_LIQUIDATION_BUFFER_BPS")
        effective_min_buffer = DEFAULT_MIN_LIQUIDATION_BUFFER_BPS
    else:
        effective_min_buffer = max(DEFAULT_MIN_LIQUIDATION_BUFFER_BPS, requested_min_buffer)
    if requested_max_loss_fraction is None or not 0.0 < requested_max_loss_fraction < 1.0:
        _append_once(reasons, "INVALID_MAX_LOSS_FRACTION_OF_EQUITY")
        effective_max_loss_fraction = DEFAULT_MAX_LOSS_FRACTION_OF_EQUITY
    else:
        effective_max_loss_fraction = min(
            DEFAULT_MAX_LOSS_FRACTION_OF_EQUITY,
            requested_max_loss_fraction,
        )

    edge_lower_bound = (
        edge - uncertainty if edge is not None and uncertainty is not None else None
    )
    if edge_lower_bound is not None and edge_lower_bound <= 0.0:
        _append_once(reasons, "EDGE_LOWER_BOUND_NOT_POSITIVE")

    base_result: dict[str, Any] = {
        "leverage": lev,
        "eligible": False,
        "reject_reason": reasons[0] if reasons else None,
        "rejection_reasons": list(reasons),
        "input_evidence_complete": not reasons,
        "point_in_time_safe": not any(
            reason
            in {
                "MISSING_OR_INVALID_EDGE_AVAILABLE_AT",
                "MISSING_OR_INVALID_RISK_CONTEXT_AVAILABLE_AT",
                "MISSING_OR_INVALID_DECISION_TIME",
                "EDGE_AVAILABLE_AFTER_DECISION_TIME",
                "RISK_CONTEXT_AVAILABLE_AFTER_DECISION_TIME",
            }
            for reason in reasons
        ),
        "edge_available_at": edge_available_at,
        "risk_context_available_at": risk_context_available_at,
        "decision_time": decision_time,
        "edge_lower_bound_bps": _rounded(edge_lower_bound),
        "context_adjusted_edge_bps": None,
        "raw_levered_expectancy_bps": (
            _rounded(edge * lev) if edge is not None and lev is not None else None
        ),
        "levered_expectancy_bps": None,
        "levered_max_loss_bps": None,
        "levered_max_loss_usd": None,
        "gross_notional_usd": None,
        "allocated_margin_usd": _rounded(base_margin),
        "liquidation_buffer_bps": None,
        "stressed_liquidation_buffer_bps": None,
        "effective_min_liquidation_buffer_bps": _rounded(effective_min_buffer),
        "effective_max_loss_fraction_of_equity": _rounded(effective_max_loss_fraction),
        "certainty_equivalent_equity_bps": None,
        "risk_adjusted_score": None,
    }
    if reasons:
        return base_result

    # Type narrowing: every value below was validated above.
    assert lev is not None
    assert edge_lower_bound is not None
    assert loss_prob is not None
    assert stop_bps is not None
    assert adverse_bps is not None
    assert execution_uncertainty is not None
    assert equity is not None
    assert base_margin is not None
    assert available_margin is not None
    assert base_liquidation_buffer is not None
    assert drawdown is not None
    assert regime_risk is not None
    assert liquidity is not None

    drawdown_resilience = 1.0 - (drawdown / 10_000.0)
    regime_resilience = 1.0 - regime_risk
    context_quality = liquidity * regime_resilience * drawdown_resilience
    context_adjusted_edge = edge_lower_bound * context_quality

    # Tail loss includes the larger of the candidate stop and the independently
    # modeled adverse move, plus execution uncertainty.  It is never inferred
    # from model confidence.
    tail_loss_bps = max(stop_bps, adverse_bps) + execution_uncertainty
    gross_notional = base_margin * lev
    modeled_max_loss_usd = gross_notional * tail_loss_bps / 10_000.0
    loss_fraction_of_equity = modeled_max_loss_usd / equity
    liquidation_buffer = base_liquidation_buffer / lev
    stressed_liquidation_buffer = liquidation_buffer - tail_loss_bps

    safety_reasons: list[str] = []
    if stressed_liquidation_buffer < effective_min_buffer:
        _append_once(safety_reasons, "STRESSED_LIQUIDATION_BUFFER_BELOW_IMMUTABLE_FLOOR")
    if modeled_max_loss_usd > equity * effective_max_loss_fraction:
        _append_once(safety_reasons, "MODELED_MAX_LOSS_EXCEEDS_IMMUTABLE_PER_TRADE_CAP")
    if loss_fraction_of_equity >= 1.0:
        _append_once(safety_reasons, "MODELED_LOSS_EXHAUSTS_EQUITY")

    # Infer the winning outcome that is consistent with the conservative
    # context-adjusted mean and the measured loss probability, then compute
    # expected log equity.  Log utility supplies the missing leverage curvature:
    # downside compounds faster as exposure approaches account equity.
    implied_win_bps = (context_adjusted_edge + loss_prob * tail_loss_bps) / (1.0 - loss_prob)
    gain_fraction_of_equity = gross_notional * implied_win_bps / 10_000.0 / equity
    if loss_fraction_of_equity < 1.0:
        certainty_equivalent = (
            (1.0 - loss_prob) * math.log1p(gain_fraction_of_equity)
            + loss_prob * math.log1p(-loss_fraction_of_equity)
        ) * 10_000.0
    else:
        certainty_equivalent = float("-inf")
    if not math.isfinite(certainty_equivalent) or certainty_equivalent <= 0.0:
        _append_once(safety_reasons, "NON_POSITIVE_CERTAINTY_EQUIVALENT")

    eligible = not safety_reasons
    all_reasons = list(safety_reasons)
    base_result.update(
        {
            "eligible": eligible,
            "reject_reason": all_reasons[0] if all_reasons else None,
            "rejection_reasons": all_reasons,
            "input_evidence_complete": True,
            "point_in_time_safe": True,
            "context_quality_multiplier": _rounded(context_quality),
            "context_adjusted_edge_bps": _rounded(context_adjusted_edge),
            "levered_expectancy_bps": _rounded(context_adjusted_edge * lev),
            "levered_max_loss_bps": _rounded(tail_loss_bps * lev),
            "levered_max_loss_usd": _rounded(modeled_max_loss_usd),
            "gross_notional_usd": _rounded(gross_notional),
            "margin_utilization_fraction": _rounded(base_margin / available_margin),
            "modeled_tail_loss_bps": _rounded(tail_loss_bps),
            "modeled_loss_fraction_of_equity": _rounded(loss_fraction_of_equity),
            "implied_win_bps": _rounded(implied_win_bps),
            "liquidation_buffer_bps": _rounded(liquidation_buffer),
            "stressed_liquidation_buffer_bps": _rounded(stressed_liquidation_buffer),
            "certainty_equivalent_equity_bps": (
                _rounded(certainty_equivalent) if math.isfinite(certainty_equivalent) else None
            ),
            "risk_adjusted_score": _rounded(certainty_equivalent) if eligible else None,
        }
    )
    return base_result


def evaluate_leverage_margin_grid(
    candidate: Mapping[str, Any],
    *,
    leverage_grid: Sequence[float] = DEFAULT_LEVERAGE_GRID,
    margin_modes: Sequence[str] = DEFAULT_MARGIN_MODES,
    min_liquidation_buffer_bps: float = DEFAULT_MIN_LIQUIDATION_BUFFER_BPS,
    max_loss_fraction_of_equity: float = DEFAULT_MAX_LOSS_FRACTION_OF_EQUITY,
) -> dict[str, Any]:
    """Evaluate a study leverage grid and truthfully report margin scope."""

    normalized_grid = list(leverage_grid)
    breakdown = [
        evaluate_leverage_for_candidate(
            expected_move_after_cost_bps=_f(candidate.get("expected_move_after_cost_bps")),
            edge_uncertainty_bps=_f(candidate.get("edge_uncertainty_bps")),
            edge_evidence_count=_f(candidate.get("edge_evidence_count")),
            edge_evidence_source=_nonempty_text(candidate.get("edge_evidence_source")),
            edge_available_at=_nonempty_text(candidate.get("edge_available_at")),
            loss_probability=_f(candidate.get("loss_probability")),
            stop_distance_bps=_f(candidate.get("stop_distance_bps")),
            modeled_adverse_move_bps=_f(candidate.get("modeled_adverse_move_bps")),
            execution_uncertainty_bps=_f(candidate.get("execution_uncertainty_bps")),
            equity_usd=_f(candidate.get("equity_usd")),
            base_margin_usd=_f(candidate.get("base_margin_usd")),
            available_margin_usd=_f(candidate.get("available_margin_usd")),
            base_liquidation_buffer_bps=_f(candidate.get("base_liquidation_buffer_bps")),
            drawdown_bps=_f(candidate.get("drawdown_bps")),
            regime_risk_score=_f(candidate.get("regime_risk_score")),
            liquidity_score=_f(candidate.get("liquidity_score")),
            risk_context_source=_nonempty_text(candidate.get("risk_context_source")),
            risk_context_available_at=_nonempty_text(
                candidate.get("risk_context_available_at")
            ),
            decision_time=_nonempty_text(candidate.get("decision_time")),
            leverage=lev,
            min_liquidation_buffer_bps=min_liquidation_buffer_bps,
            max_loss_fraction_of_equity=max_loss_fraction_of_equity,
        )
        for lev in normalized_grid
    ]

    requested_margin_modes = [str(mode).strip().lower() for mode in margin_modes]
    margin_breakdown: list[dict[str, Any]] = []
    for mode in requested_margin_modes:
        if mode == "isolated":
            margin_breakdown.append(
                {
                    "margin_mode": mode,
                    "evaluated": True,
                    "eligible": True,
                    "reject_reason": None,
                }
            )
        elif mode == "cross":
            margin_breakdown.append(
                {
                    "margin_mode": mode,
                    "evaluated": False,
                    "eligible": False,
                    "reject_reason": (
                        "CROSS_MARGIN_REQUIRES_ACCOUNT_WIDE_STRESS_AND_CONTAGION_MODEL"
                    ),
                }
            )
        else:
            margin_breakdown.append(
                {
                    "margin_mode": mode,
                    "evaluated": False,
                    "eligible": False,
                    "reject_reason": "UNSUPPORTED_MARGIN_MODE",
                }
            )

    eligible = [row for row in breakdown if row["eligible"]]
    isolated_eligible = any(
        row["margin_mode"] == "isolated" and row["eligible"] for row in margin_breakdown
    )
    if eligible and isolated_eligible:
        # Prefer lower exposure only when certainty-equivalent scores are exactly
        # equal; unlike the old formula, ordinary candidates no longer all tie.
        best = max(
            eligible,
            key=lambda row: (float(row["risk_adjusted_score"]), -float(row["leverage"])),
        )
        best_leverage: float | None = float(best["leverage"])
        best_score: float | None = float(best["risk_adjusted_score"])
        best_margin_mode: str | None = "isolated"
        best_reason = "POSITIVE_CERTAINTY_EQUIVALENT_WITHIN_IMMUTABLE_SAFETY_ENVELOPE"
    else:
        best_leverage = None
        best_score = None
        best_margin_mode = None
        best_reason = (
            "NO_ELIGIBLE_LEVERAGE"
            if not eligible
            else "NO_SUPPORTED_ELIGIBLE_MARGIN_MODE"
        )

    input_rejection_reasons = sorted(
        {
            reason
            for row in breakdown
            if not row["input_evidence_complete"]
            for reason in row["rejection_reasons"]
        }
    )
    valid_grid_values = [row["leverage"] for row in breakdown if row["leverage"] is not None]
    effective_min_buffer = (
        breakdown[0]["effective_min_liquidation_buffer_bps"]
        if breakdown
        else DEFAULT_MIN_LIQUIDATION_BUFFER_BPS
    )
    effective_max_loss_fraction = (
        breakdown[0]["effective_max_loss_fraction_of_equity"]
        if breakdown
        else DEFAULT_MAX_LOSS_FRACTION_OF_EQUITY
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "study_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "scoring_model": "CONTEXT_SHRUNK_EDGE_EXPECTED_LOG_EQUITY_V1",
        "required_evidence_fields": list(REQUIRED_EVIDENCE_FIELDS),
        "input_evidence_complete": not input_rejection_reasons,
        "input_rejection_reasons": input_rejection_reasons,
        "leverage_grid": valid_grid_values,
        "per_leverage_breakdown": breakdown,
        "margin_modes_requested": requested_margin_modes,
        "margin_modes_evaluated": [
            row["margin_mode"] for row in margin_breakdown if row["evaluated"]
        ],
        "per_margin_mode_breakdown": margin_breakdown,
        "best_leverage": best_leverage,
        "best_margin_mode": best_margin_mode,
        "best_risk_adjusted_score": best_score,
        "best_leverage_reason": best_reason,
        "study_admission_allowed": best_leverage is not None and best_margin_mode is not None,
        "adaptive_evidence_driven": True,
        "dynamic_not_static": len(set(valid_grid_values)) > 1,
        "immutable_safety_envelope": {
            "hard_max_study_leverage": HARD_MAX_STUDY_LEVERAGE,
            "min_liquidation_buffer_bps": effective_min_buffer,
            "max_loss_fraction_of_equity": effective_max_loss_fraction,
        },
    }
