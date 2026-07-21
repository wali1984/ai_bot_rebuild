from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

HEDGE_DIRECTIVE_VALIDITY_SCHEMA_VERSION = (
    "PAPER_ADAPTIVE_HEDGE_DIRECTIVE_VALIDITY_V1"
)
HEDGE_DIRECTIVE_VALIDITY_POLICY_VERSION = (
    "OBSERVED_LIFECYCLE_CADENCE_PLUS_AUTHENTICATED_MARK_FRESHNESS_V1"
)
HEDGE_DIRECTIVE_VALIDITY_FORMULA = (
    "MIN(IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS,"
    "OBSERVED_LIFECYCLE_UPDATE_CADENCE_SECONDS+"
    "AUTHENTICATED_MARK_FRESHNESS_BUDGET_SECONDS)"
)
# This is an immutable fail-safe ceiling, not the directive's validity
# authority.  The effective lifetime is recomputed from observed lifecycle
# cadence plus the authenticated mark receipt's freshness budget and is
# normally much smaller.  The ceiling only prevents a stalled/poisoned cadence
# observation from granting an unbounded hedge instruction lifetime.
HEDGE_DIRECTIVE_IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS = 600.0
HEDGE_DIRECTIVE_QUEUE_SCHEMA_VERSION = "PAPER_ADAPTIVE_HEDGE_DIRECTIVE_QUEUE_V2"
HEDGE_DIRECTIVE_STORAGE_TTL_ROLE = (
    "OPERATIONAL_GARBAGE_COLLECTION_ONLY_NOT_VALIDITY_AUTHORITY"
)
HEDGE_DIRECTIVE_MARK_SOURCE = "binance_usdm_wss_mark_price_all_symbols"
HEDGE_DIRECTIVE_MARK_AUTHENTICATION_BOUNDARY = (
    "LOCAL_MARK_PRODUCER_TO_PAPER_CONSUMER_HMAC_SHA256_V1"
)
HEDGE_DIRECTIVE_MARK_CONSUMER_VALIDATION_BOUNDARY = (
    "PAPER_LOOP_EXCHANGE_MARK_CONSUMER_V1"
)
HEDGE_DIRECTIVE_MARK_CADENCE_POLICY_VERSION = (
    "BINANCE_USDM_MARK_PRICE_STREAM_1S_CADENCE_V1"
)


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


def _optional_finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _aware_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _sha256_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(char in "0123456789abcdef" for char in value)
    )


def build_adaptive_hedge_directive_validity(
    *,
    previous_cycle_generated_utc: Any,
    directive_generated_utc: Any,
    mark_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build point-in-time validity from observed cadence and mark freshness.

    No configured/default duration authorizes the directive.  A directive is
    eligible only when there is a prior lifecycle timestamp (an actual cadence
    observation) and an authenticated, current mark receipt.  The immutable
    maximum is a safety ceiling only.
    """

    previous_at = _aware_utc(previous_cycle_generated_utc)
    generated_at = _aware_utc(directive_generated_utc)
    evidence = mark_evidence if isinstance(mark_evidence, dict) else {}
    mark_event_at = _aware_utc(evidence.get("event_time"))
    mark_generated_at = _aware_utc(evidence.get("generated_at"))
    mark_available_at = _aware_utc(evidence.get("available_at"))
    source_freshness = _optional_finite_float(
        evidence.get("freshness_budget_seconds")
    )
    source_expected_interval = _optional_finite_float(
        evidence.get("expected_update_interval_seconds")
    )
    rejection_reasons: list[str] = []
    if previous_at is None or generated_at is None:
        rejection_reasons.append("HEDGE_DIRECTIVE_CADENCE_CLOCK_MISSING_OR_INVALID")
    elif previous_at >= generated_at:
        rejection_reasons.append("HEDGE_DIRECTIVE_CADENCE_CLOCK_ORDER_INVALID")
    if evidence.get("authority_complete") is not True:
        rejection_reasons.append("HEDGE_DIRECTIVE_MARK_AUTHORITY_INCOMPLETE")
    if None in (mark_event_at, mark_generated_at, mark_available_at, generated_at):
        rejection_reasons.append("HEDGE_DIRECTIVE_MARK_CLOCK_MISSING_OR_INVALID")
    elif not mark_event_at <= mark_generated_at <= mark_available_at <= generated_at:
        rejection_reasons.append("HEDGE_DIRECTIVE_MARK_CLOCK_ORDER_INVALID")
    if (
        source_freshness is None
        or source_freshness <= 0.0
        or source_expected_interval is None
        or source_expected_interval <= 0.0
        or not math.isclose(
            source_freshness,
            source_expected_interval,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        rejection_reasons.append("HEDGE_DIRECTIVE_MARK_CADENCE_CONTRACT_INVALID")
    elif generated_at is not None and mark_event_at is not None:
        mark_age_seconds = (generated_at - mark_event_at).total_seconds()
        if mark_age_seconds < 0.0 or mark_age_seconds > source_freshness:
            rejection_reasons.append("HEDGE_DIRECTIVE_MARK_STALE_AT_GENERATION")
    exact_mark_authority_fields = {
        "source": HEDGE_DIRECTIVE_MARK_SOURCE,
        "authentication_boundary": HEDGE_DIRECTIVE_MARK_AUTHENTICATION_BOUNDARY,
        "consumer_validation_boundary": (
            HEDGE_DIRECTIVE_MARK_CONSUMER_VALIDATION_BOUNDARY
        ),
        "cadence_policy_version": HEDGE_DIRECTIVE_MARK_CADENCE_POLICY_VERSION,
    }
    for field_name, expected in exact_mark_authority_fields.items():
        if evidence.get(field_name) != expected:
            rejection_reasons.append(
                f"HEDGE_DIRECTIVE_MARK_{field_name.upper()}_MISMATCH"
            )
    if not _sha256_hex(evidence.get("evidence_sha256")):
        rejection_reasons.append("HEDGE_DIRECTIVE_MARK_EVIDENCE_HASH_INVALID")

    observed_cadence = (
        (generated_at - previous_at).total_seconds()
        if previous_at is not None and generated_at is not None and previous_at < generated_at
        else None
    )
    adaptive_budget = (
        min(
            HEDGE_DIRECTIVE_IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS,
            observed_cadence + source_freshness,
        )
        if observed_cadence is not None
        and observed_cadence > 0.0
        and source_freshness is not None
        and source_freshness > 0.0
        else None
    )
    expires_at = (
        generated_at + timedelta(seconds=adaptive_budget)
        if generated_at is not None and adaptive_budget is not None
        else None
    )
    return {
        "schema_version": HEDGE_DIRECTIVE_VALIDITY_SCHEMA_VERSION,
        "policy_version": HEDGE_DIRECTIVE_VALIDITY_POLICY_VERSION,
        "authority_complete": not rejection_reasons,
        "rejection_reasons": list(dict.fromkeys(rejection_reasons)),
        "cadence_observation_from": (
            _utc_iso(previous_at) if previous_at is not None else None
        ),
        "cadence_observation_to": (
            _utc_iso(generated_at) if generated_at is not None else None
        ),
        "observed_lifecycle_update_cadence_seconds": observed_cadence,
        "authenticated_mark_freshness_budget_seconds": source_freshness,
        "authenticated_mark_expected_update_interval_seconds": (
            source_expected_interval
        ),
        "adaptive_freshness_budget_seconds": adaptive_budget,
        "valid_until": _utc_iso(expires_at) if expires_at is not None else None,
        "immutable_max_safety_lifetime_seconds": (
            HEDGE_DIRECTIVE_IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS
        ),
        "lifetime_formula": HEDGE_DIRECTIVE_VALIDITY_FORMULA,
        "mark_event_time": evidence.get("event_time"),
        "mark_generated_at": evidence.get("generated_at"),
        "mark_available_at": evidence.get("available_at"),
        "mark_source": evidence.get("source"),
        "mark_authentication_boundary": evidence.get("authentication_boundary"),
        "mark_consumer_validation_boundary": evidence.get(
            "consumer_validation_boundary"
        ),
        "mark_cadence_policy_version": evidence.get("cadence_policy_version"),
        "mark_evidence_sha256": evidence.get("evidence_sha256"),
        "paper_only": True,
        "places_real_order": False,
    }


def validate_adaptive_hedge_directive_validity(
    *,
    directive_generated_utc: Any,
    validity_envelope: dict[str, Any] | None,
    observed_at: Any,
) -> dict[str, Any]:
    """Recompute one directive's adaptive lifetime at the consumer boundary."""

    validity = validity_envelope if isinstance(validity_envelope, dict) else {}
    generated_at = _aware_utc(directive_generated_utc)
    observed = _aware_utc(observed_at)
    cadence_from = _aware_utc(validity.get("cadence_observation_from"))
    cadence_to = _aware_utc(validity.get("cadence_observation_to"))
    valid_until = _aware_utc(validity.get("valid_until"))
    mark_event_at = _aware_utc(validity.get("mark_event_time"))
    mark_generated_at = _aware_utc(validity.get("mark_generated_at"))
    mark_available_at = _aware_utc(validity.get("mark_available_at"))
    observed_cadence = _optional_finite_float(
        validity.get("observed_lifecycle_update_cadence_seconds")
    )
    source_freshness = _optional_finite_float(
        validity.get("authenticated_mark_freshness_budget_seconds")
    )
    source_expected_interval = _optional_finite_float(
        validity.get("authenticated_mark_expected_update_interval_seconds")
    )
    adaptive_budget = _optional_finite_float(
        validity.get("adaptive_freshness_budget_seconds")
    )
    safety_cap = _optional_finite_float(
        validity.get("immutable_max_safety_lifetime_seconds")
    )
    reasons: list[str] = []
    exact_fields = {
        "schema_version": HEDGE_DIRECTIVE_VALIDITY_SCHEMA_VERSION,
        "policy_version": HEDGE_DIRECTIVE_VALIDITY_POLICY_VERSION,
        "lifetime_formula": HEDGE_DIRECTIVE_VALIDITY_FORMULA,
        "immutable_max_safety_lifetime_seconds": (
            HEDGE_DIRECTIVE_IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS
        ),
        "paper_only": True,
        "places_real_order": False,
        "authority_complete": True,
    }
    for field_name, expected in exact_fields.items():
        if validity.get(field_name) != expected:
            reasons.append(f"HEDGE_DIRECTIVE_VALIDITY_{field_name.upper()}_MISMATCH")
    if validity.get("rejection_reasons") != []:
        reasons.append("HEDGE_DIRECTIVE_VALIDITY_PRODUCER_REJECTIONS_PRESENT")
    if None in (generated_at, observed, cadence_from, cadence_to, valid_until):
        reasons.append("HEDGE_DIRECTIVE_VALIDITY_CLOCK_MISSING_OR_INVALID")
    elif not cadence_from < cadence_to == generated_at <= observed:
        reasons.append("HEDGE_DIRECTIVE_VALIDITY_CLOCK_ORDER_INVALID")
    if (
        observed_cadence is None
        or observed_cadence <= 0.0
        or cadence_from is None
        or cadence_to is None
        or not math.isclose(
            observed_cadence,
            (cadence_to - cadence_from).total_seconds(),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    ):
        reasons.append("HEDGE_DIRECTIVE_OBSERVED_CADENCE_RECONCILIATION_FAILED")
    if (
        source_freshness is None
        or source_freshness <= 0.0
        or source_expected_interval is None
        or source_expected_interval <= 0.0
        or not math.isclose(
            source_freshness,
            source_expected_interval,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        reasons.append("HEDGE_DIRECTIVE_SOURCE_CADENCE_CONTRACT_INVALID")
    if None in (mark_event_at, mark_generated_at, mark_available_at, generated_at):
        reasons.append("HEDGE_DIRECTIVE_VALIDITY_MARK_CLOCK_MISSING_OR_INVALID")
    elif not mark_event_at <= mark_generated_at <= mark_available_at <= generated_at:
        reasons.append("HEDGE_DIRECTIVE_VALIDITY_MARK_CLOCK_ORDER_INVALID")
    elif (
        source_freshness is not None
        and (generated_at - mark_event_at).total_seconds() > source_freshness
    ):
        reasons.append("HEDGE_DIRECTIVE_VALIDITY_MARK_STALE_AT_GENERATION")
    expected_budget = (
        min(
            HEDGE_DIRECTIVE_IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS,
            observed_cadence + source_freshness,
        )
        if observed_cadence is not None
        and observed_cadence > 0.0
        and source_freshness is not None
        and source_freshness > 0.0
        else None
    )
    if (
        adaptive_budget is None
        or expected_budget is None
        or safety_cap != HEDGE_DIRECTIVE_IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS
        or not math.isclose(
            adaptive_budget,
            expected_budget,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    ):
        reasons.append("HEDGE_DIRECTIVE_ADAPTIVE_BUDGET_RECONCILIATION_FAILED")
    expected_valid_until = (
        generated_at + timedelta(seconds=expected_budget)
        if generated_at is not None and expected_budget is not None
        else None
    )
    if (
        expected_valid_until is None
        or valid_until is None
        or abs((valid_until - expected_valid_until).total_seconds()) > 0.001
    ):
        reasons.append("HEDGE_DIRECTIVE_VALID_UNTIL_RECONCILIATION_FAILED")
    if not _sha256_hex(validity.get("mark_evidence_sha256")):
        reasons.append("HEDGE_DIRECTIVE_VALIDITY_MARK_EVIDENCE_HASH_INVALID")
    exact_mark_authority_fields = {
        "mark_source": HEDGE_DIRECTIVE_MARK_SOURCE,
        "mark_authentication_boundary": (
            HEDGE_DIRECTIVE_MARK_AUTHENTICATION_BOUNDARY
        ),
        "mark_consumer_validation_boundary": (
            HEDGE_DIRECTIVE_MARK_CONSUMER_VALIDATION_BOUNDARY
        ),
        "mark_cadence_policy_version": (
            HEDGE_DIRECTIVE_MARK_CADENCE_POLICY_VERSION
        ),
    }
    for field_name, expected in exact_mark_authority_fields.items():
        if validity.get(field_name) != expected:
            reasons.append(
                f"HEDGE_DIRECTIVE_VALIDITY_{field_name.upper()}_MISMATCH"
            )
    expired = (
        observed is not None and valid_until is not None and observed > valid_until
    )
    if expired:
        reasons.append("HEDGE_DIRECTIVE_ADAPTIVE_VALIDITY_EXPIRED")
    age_seconds = (
        max(0.0, (observed - generated_at).total_seconds())
        if observed is not None and generated_at is not None and observed >= generated_at
        else None
    )
    remaining_seconds = (
        max(0.0, (valid_until - observed).total_seconds())
        if observed is not None and valid_until is not None
        else None
    )
    return {
        "valid": not reasons,
        "expired": expired,
        "rejection_reasons": list(dict.fromkeys(reasons)),
        "age_seconds": age_seconds,
        "remaining_seconds": remaining_seconds,
        "adaptive_freshness_budget_seconds": adaptive_budget,
        "immutable_max_safety_lifetime_seconds": (
            HEDGE_DIRECTIVE_IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS
        ),
    }


def hedge_directive_storage_ttl_seconds(
    directives: list[dict[str, Any]],
    *,
    observed_at: Any,
) -> int | None:
    """Return garbage-collection TTL; never grants directive authority."""

    remaining: list[float] = []
    for directive in directives:
        if not isinstance(directive, dict):
            continue
        status = validate_adaptive_hedge_directive_validity(
            directive_generated_utc=directive.get("generated_utc"),
            validity_envelope=directive.get("validity_envelope"),
            observed_at=observed_at,
        )
        if status.get("valid") is True:
            value = _optional_finite_float(status.get("remaining_seconds"))
            if value is not None and value > 0.0:
                remaining.append(value)
    if not remaining:
        return None
    return max(
        1,
        int(
            math.ceil(
                min(
                    max(remaining),
                    HEDGE_DIRECTIVE_IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS,
                )
            )
        ),
    )


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


def hedge_arm_fraction(
    confidence_calibrated: float | None,
    portfolio_drawdown_bps: float = 0.0,
    drawdown_emergency_bps: float = 350.0,
) -> float:
    """Fraction of the ATR stop at which the adaptive hedge arms.

    Shared by the runtime trigger below and by hedge-AWARE SIZING in the
    capital allocator (2026-07-17): with the hedge engine active, a
    position's true worst-case adverse excursion is bounded near this
    fraction of its stop (plus hedge execution drag), not the full stop —
    so the allocator may size risk_budget against the smaller distance.
    Identical formula to the trigger so sizing and protection can never
    disagree about where the hedge arms.
    """
    confidence = _float(confidence_calibrated, 0.5)
    confidence_pressure = _clamp((confidence - 0.5) / 0.5, 0.0, 1.0)
    dd_pressure = _clamp(
        abs(_float(portfolio_drawdown_bps))
        / max(1.0, abs(_float(drawdown_emergency_bps, 350.0))),
        0.0,
        1.0,
    )
    return _clamp(1.0 - 0.45 * confidence_pressure - 0.15 * dd_pressure, 0.35, 0.95)


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
    arm_fraction = hedge_arm_fraction(
        confidence, portfolio_drawdown_bps, drawdown_emergency_bps
    )
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
    "HEDGE_DIRECTIVE_IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS",
    "HEDGE_DIRECTIVE_MARK_AUTHENTICATION_BOUNDARY",
    "HEDGE_DIRECTIVE_MARK_CADENCE_POLICY_VERSION",
    "HEDGE_DIRECTIVE_MARK_CONSUMER_VALIDATION_BOUNDARY",
    "HEDGE_DIRECTIVE_MARK_SOURCE",
    "HEDGE_DIRECTIVE_QUEUE_SCHEMA_VERSION",
    "HEDGE_DIRECTIVE_STORAGE_TTL_ROLE",
    "HEDGE_DIRECTIVE_VALIDITY_POLICY_VERSION",
    "HEDGE_DIRECTIVE_VALIDITY_SCHEMA_VERSION",
    "evaluate_adaptive_hedge",
    "build_hedge_cost_benefit",
    "build_adaptive_hedge_directive_validity",
    "evaluate_adaptive_hedge_trigger",
    "evaluate_adaptive_hedge_unwind",
    "hedge_directive_storage_ttl_seconds",
    "validate_adaptive_hedge_directive_validity",
]
