"""Unified preemptive edge-control decision object."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from v2.backend.app.services.preemptive_edge_control.bucket_health import (
    build_bucket_health,
    candidate_bucket_assessment,
)
from v2.backend.app.services.preemptive_edge_control.candidate_loss_risk import (
    assess_candidate_loss_risk,
)
from v2.backend.app.services.preemptive_edge_control.confidence_overstatement import (
    assess_confidence_overstatement,
)
from v2.backend.app.services.preemptive_edge_control.cost_edge_validator import assess_cost_edge
from v2.backend.app.services.preemptive_edge_control.exit_feasibility import (
    assess_exit_feasibility,
)
from v2.backend.app.services.preemptive_edge_control.portfolio_stress import (
    assess_portfolio_stress,
)
from v2.backend.app.services.preemptive_edge_control.regime_compatibility import (
    assess_regime_compatibility,
)
from v2.backend.app.services.preemptive_edge_control.schema import (
    canonicalize_preemptive_decision,
)
from v2.backend.app.services.market_structure.decision_context import (
    evaluate_advanced_indicator_context,
)

PREEMPTIVE_DECISIONS = {
    "ALLOW",
    "PAPER_RISK_CONTROLLER_EXPLORATION",
    "POSITIVE_EDGE_PROBATION_PAPER",
    "REDUCE_SIZE_PAPER_ONLY",
    "SHADOW_ONLY",
    "NO_TRADE",
    "CLOSE_OR_REDUCE_ONLY",
}

POSITIVE_EDGE_PROBATION_LOSS_PROBABILITY_BOUND = 0.65
POSITIVE_EDGE_PROBATION_MIN_EXIT_FEASIBILITY = 0.55
PAPER_RISK_CONTROLLER_EXPLORATION_LOSS_PROBABILITY_BOUND = 0.72
PAPER_RISK_CONTROLLER_EXPLORATION_MIN_EXIT_FEASIBILITY = 0.50

SCHEMA_VERSION = "preemptive_edge_control_decision_v1"
PAPER_RISK_CONTROLLER_EXPLORATION_TIER = "PAPER_RISK_CONTROLLER_EXPLORATION"


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalized_side(candidate: dict[str, Any]) -> str | None:
    side = str(candidate.get("side") or candidate.get("action") or candidate.get("selected_action") or "").lower()
    if side in {"long", "buy"}:
        return "long"
    if side in {"short", "sell"}:
        return "short"
    return None


def _strategy(candidate: dict[str, Any]) -> str | None:
    value = (
        candidate.get("strategy_selected_mode")
        or candidate.get("strategy_id")
        or candidate.get("strategy_mode")
        or candidate.get("strategy_family")
    )
    return str(value).strip() if value not in (None, "") else None


def _regime(candidate: dict[str, Any]) -> str | None:
    value = (
        candidate.get("strategy_market_regime")
        or candidate.get("market_regime_at_entry")
        or candidate.get("market_regime")
    )
    return str(value).strip() if value not in (None, "") else None


def _trust_score(candidate: dict[str, Any]) -> float | None:
    return _f(
        candidate.get("composite_microstructure_trust_score")
        or candidate.get("microstructure_trust_score")
        or candidate.get("public_orderbook_trust_score")
    )


def _guardian_halted(guardian: dict[str, Any] | None) -> bool:
    if not isinstance(guardian, dict) or not guardian:
        return True
    status = str(guardian.get("status") or guardian.get("state") or "").upper()
    if any(token in status for token in ("HALTED", "BLOCKED", "SHADOW_ONLY")):
        return True
    for field in ("a_grade_new_entries_allowed", "new_entries_allowed", "guardian_new_entries_allowed"):
        if guardian.get(field) is not None:
            return guardian.get(field) is not True
    return False


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _is_paper_risk_controller_exploration_candidate(candidate: dict[str, Any]) -> bool:
    tier = str(
        _first_present(
            candidate.get("paper_opportunity_tier"),
            candidate.get("tier"),
            candidate.get("exploration_tier"),
            candidate.get("paper_exploration_tier"),
        )
        or ""
    ).strip().upper()
    return (
        tier == PAPER_RISK_CONTROLLER_EXPLORATION_TIER
        or candidate.get("paper_risk_controller_exploration") is True
        or candidate.get("allow_paper_risk_controller_exploration") is True
    )


def _paper_exploration_specific_quarantine_key(key: Any) -> bool:
    normalized = str(key or "")
    return bool(normalized) and not normalized.startswith(
        ("side:", "timeframe:", "regime:")
    )


def _paper_exploration_bucket_quarantine_split(
    candidate: dict[str, Any],
    matched: list[str],
) -> tuple[list[str], list[str]]:
    if not _is_paper_risk_controller_exploration_candidate(candidate):
        return matched, []
    exact_from_paper_loop = {
        str(key)
        for key in candidate.get("paper_exploration_exact_blocked_bucket_keys") or []
    }
    if exact_from_paper_loop:
        hard = sorted(set(matched) & exact_from_paper_loop)
        advisory = sorted(set(matched) - set(hard))
        return hard, advisory
    hard = [key for key in matched if _paper_exploration_specific_quarantine_key(key)]
    advisory = [key for key in matched if key not in hard]
    return hard, advisory


def _decision_id(candidate: dict[str, Any], decision: str, reasons: list[str]) -> str:
    basis = {
        "symbol": candidate.get("symbol"),
        "timeframe": candidate.get("timeframe") or candidate.get("thesis_timeframe"),
        "side": _normalized_side(candidate),
        "strategy": _strategy(candidate),
        "prediction_id": candidate.get("prediction_id") or candidate.get("source_prediction_id"),
        "signal_id": candidate.get("signal_id"),
        "decision": decision,
        "reasons": reasons,
    }
    digest = hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[:24]
    return f"pec_{digest}"


def evaluate_candidate(
    candidate: dict[str, Any],
    *,
    closed_rows: list[dict[str, Any]] | None = None,
    bucket_health: dict[str, dict[str, Any]] | None = None,
    continuous_edge_guardian_gate: dict[str, Any] | None = None,
    bucket_quarantine_status: dict[str, Any] | None = None,
    allow_positive_edge_probation: bool = False,
    allow_paper_risk_controller_exploration: bool = False,
    allow_reduce_or_close: bool = False,
    altdata_confluence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a complete pre-entry decision object.

    Missing critical evidence fails closed. The only non-entry escape hatch is
    CLOSE_OR_REDUCE_ONLY for explicit reduce/close actions.
    """
    if not isinstance(candidate, dict) or not candidate:
        decision = "NO_TRADE"
        reasons = ["CANDIDATE_PAYLOAD_MISSING"]
        return canonicalize_preemptive_decision(
            {},
            {
                "schema_version": SCHEMA_VERSION,
                "preemptive_decision": decision,
                "preemptive_decision_id": _decision_id({}, decision, reasons),
                "preemptive_decision_reasons": reasons,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            },
            continuous_edge_guardian_gate=continuous_edge_guardian_gate,
        )

    action = str(candidate.get("action") or candidate.get("requested_action") or "").lower()
    if allow_reduce_or_close and (candidate.get("reduce_only") is True or action in {"close", "reduce"}):
        decision = "CLOSE_OR_REDUCE_ONLY"
        reasons = ["EXPLICIT_CLOSE_OR_REDUCE_ACTION"]
        return canonicalize_preemptive_decision(
            candidate,
            {
            "schema_version": SCHEMA_VERSION,
            "preemptive_decision": decision,
            "preemptive_decision_id": _decision_id(candidate, decision, reasons),
            "preemptive_decision_reasons": reasons,
            "allow_close": True,
            "allow_reduce": True,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            },
            continuous_edge_guardian_gate=continuous_edge_guardian_gate,
        )

    health = bucket_health if bucket_health is not None else build_bucket_health(closed_rows or [])
    bucket = candidate_bucket_assessment(
        health,
        symbol=candidate.get("symbol"),
        side=_normalized_side(candidate),
        timeframe=candidate.get("timeframe") or candidate.get("thesis_timeframe"),
        strategy_mode=_strategy(candidate),
        regime=_regime(candidate),
    )
    cost = assess_cost_edge(candidate)
    trust = _trust_score(candidate)
    confidence = assess_confidence_overstatement(
        confidence_raw=candidate.get("confidence_raw"),
        confidence_calibrated=candidate.get("confidence_calibrated") or candidate.get("confidence"),
        bucket_high_confidence_loss_rate=bucket.get("recent_high_confidence_loss_rate"),
        bucket_profit_factor=bucket.get("bucket_profit_factor"),
        microstructure_trust_score=trust,
    )
    regime = assess_regime_compatibility(candidate)
    exit_plan = assess_exit_feasibility(candidate, cost)
    portfolio = assess_portfolio_stress(
        candidate,
        expected_edge_after_cost_bps=cost.get("expected_edge_after_cost_bps"),
        bucket_profit_factor=bucket.get("bucket_profit_factor"),
    )
    advanced_candidate = dict(candidate)
    advanced_candidate["exit_feasibility_score"] = exit_plan.get("exit_feasibility_score")
    advanced_candidate["liquidity_exit_depth"] = exit_plan.get("liquidity_exit_depth")
    advanced_candidate["MFE_required_to_profit"] = exit_plan.get("MFE_required_to_profit")
    advanced_candidate["stop_distance_vs_noise"] = exit_plan.get("stop_distance_vs_noise")
    advanced = evaluate_advanced_indicator_context(advanced_candidate)
    loss = assess_candidate_loss_risk(
        cost_edge=cost,
        confidence=confidence,
        bucket=bucket,
        regime=regime,
        exit_plan=exit_plan,
        microstructure_trust_score=trust,
    )

    reasons: list[str] = []
    reasons.extend(cost.get("cost_edge_reasons") or [])
    reasons.extend(confidence.get("confidence_overstatement_reasons") or [])
    reasons.extend(regime.get("regime_compatibility_reasons") or [])
    reasons.extend(exit_plan.get("exit_feasibility_reasons") or [])
    reasons.extend(loss.get("pre_trade_loss_risk_reasons") or [])
    reasons.extend(advanced.get("advanced_indicator_block_reasons") or [])
    reasons.extend(advanced.get("advanced_indicator_caution_reasons") or [])
    reasons.extend(advanced.get("advanced_indicator_missing_evidence") or [])
    if bucket.get("negative_buckets"):
        reasons.append("BUCKET_PF_OR_EXPECTANCY_NEGATIVE")
    if bucket.get("bucket_evidence_missing"):
        reasons.append("BUCKET_EVIDENCE_INSUFFICIENT")
    if isinstance(bucket_quarantine_status, dict):
        blocked = set(str(x) for x in bucket_quarantine_status.get("blocked_bucket_keys") or [])
        matched = sorted(blocked & set(bucket.get("candidate_bucket_keys") or []))
        hard_matched, advisory_matched = _paper_exploration_bucket_quarantine_split(
            candidate,
            matched,
        )
        if hard_matched:
            reasons.append("BUCKET_QUARANTINE_MATCH")
            bucket["matched_quarantined_bucket_keys"] = hard_matched
        elif advisory_matched:
            bucket["advisory_quarantined_bucket_keys"] = advisory_matched

    guardian_halted = _guardian_halted(continuous_edge_guardian_gate)
    if guardian_halted:
        reasons.append("GUARDIAN_HALTED_OR_MISSING")

    # Alt-data confluence (CoinGlass+Santiment+Moralis fusion) is fail-safe
    # only: it can block, demote to reduce-size, or require a hedge. It can
    # never promote a decision toward ALLOW, and its absence never blocks.
    altdata_features = (
        altdata_confluence.get("features")
        if isinstance(altdata_confluence, dict)
        and isinstance(altdata_confluence.get("features"), dict)
        else {}
    )
    altdata_present = bool(altdata_features) and bool(
        (altdata_confluence or {}).get("actual_payload_present")
    )
    altdata_block = _f(altdata_features.get("altdata_trade_block_score"))
    altdata_reduce = _f(altdata_features.get("altdata_reduce_size_score"))
    altdata_hedge = _f(altdata_features.get("altdata_hedge_required_score"))
    altdata_distribution = _f(altdata_features.get("altdata_wallet_distribution_score"))
    altdata_sweep = _f(altdata_features.get("altdata_liquidation_sweep_risk_score"))
    altdata_euphoria = _f(altdata_features.get("altdata_social_euphoria_risk_score"))
    candidate_side = _normalized_side(candidate)
    altdata_block_hit = altdata_present and altdata_block is not None and altdata_block >= 0.70
    altdata_reduce_hit = altdata_present and altdata_reduce is not None and altdata_reduce >= 0.50
    altdata_hedge_required = altdata_present and altdata_hedge is not None and altdata_hedge >= 0.50
    altdata_distribution_conflict = (
        altdata_present
        and candidate_side == "long"
        and altdata_distribution is not None
        and altdata_distribution >= 0.60
    )
    if altdata_block_hit:
        reasons.append("ALTDATA_TRADE_BLOCK_SCORE_HIGH")
    if altdata_reduce_hit:
        reasons.append("ALTDATA_REDUCE_SIZE_SCORE_ELEVATED")
    if altdata_hedge_required:
        reasons.append("ALTDATA_HEDGE_REQUIRED")
    if altdata_distribution_conflict:
        reasons.append("ALTDATA_WALLET_DISTRIBUTION_CONFLICTS_LONG")
    if altdata_present and altdata_sweep is not None and altdata_sweep >= 0.70:
        reasons.append("ALTDATA_LIQUIDATION_SWEEP_RISK_HIGH")
    if altdata_present and altdata_euphoria is not None and altdata_euphoria >= 0.70:
        reasons.append("ALTDATA_SOCIAL_EUPHORIA_RISK_HIGH")
    altdata_high_risk_conflict = (
        altdata_block_hit
        or altdata_distribution_conflict
        or (altdata_present and altdata_sweep is not None and altdata_sweep >= 0.70)
        or (altdata_present and altdata_euphoria is not None and altdata_euphoria >= 0.70)
    )

    loss_probability = _f(loss.get("pre_trade_loss_probability")) or 1.0
    confidence_risk = _f(confidence.get("confidence_overstatement_risk")) or 0.0
    exit_score = _f(exit_plan.get("exit_feasibility_score")) or 0.0
    expected_edge = _f(cost.get("expected_edge_after_cost_bps"))
    atr_stop_cluster = (_f(bucket.get("recent_ATR_stop_risk")) or 0.0) >= 0.40
    micro_action = str(candidate.get("microstructure_action") or "").upper()
    matched_quarantine = bool(bucket.get("matched_quarantined_bucket_keys"))
    advanced_block = advanced.get("advanced_indicator_block") is True
    advanced_shadow = advanced.get("advanced_indicator_shadow") is True
    trust_not_no_trade = (
        micro_action not in {"NO_TRADE", "SHADOW_ONLY", "CLOSE_OR_REDUCE_ONLY"}
        and trust is not None
    )
    positive_edge_probation_eligible = (
        allow_positive_edge_probation
        and guardian_halted
        and not bucket.get("bucket_negative")
        and not matched_quarantine
        and expected_edge is not None
        and expected_edge > 0.0
        and loss_probability < POSITIVE_EDGE_PROBATION_LOSS_PROBABILITY_BOUND
        and confidence_risk < 0.75
        and exit_score >= POSITIVE_EDGE_PROBATION_MIN_EXIT_FEASIBILITY
        and trust_not_no_trade
        and not advanced_block
        and not advanced_shadow
    )
    paper_risk_controller_exploration_eligible = (
        allow_paper_risk_controller_exploration
        and
        guardian_halted
        and not bucket.get("bucket_negative")
        and not matched_quarantine
        and not atr_stop_cluster
        and expected_edge is not None
        and expected_edge > 0.0
        and loss_probability < PAPER_RISK_CONTROLLER_EXPLORATION_LOSS_PROBABILITY_BOUND
        and confidence_risk < 0.75
        and exit_score >= PAPER_RISK_CONTROLLER_EXPLORATION_MIN_EXIT_FEASIBILITY
        and trust_not_no_trade
        and not advanced_block
        and not altdata_high_risk_conflict
    )

    if (
        bucket.get("bucket_negative")
        or matched_quarantine
        or atr_stop_cluster
        or loss_probability >= 0.80
        or advanced_block
    ):
        decision = "NO_TRADE"
    elif positive_edge_probation_eligible:
        decision = "POSITIVE_EDGE_PROBATION_PAPER"
        reasons.append("GLOBAL_GUARDIAN_HALT_SCOPED_TO_PAPER_PROBATION")
    elif paper_risk_controller_exploration_eligible:
        decision = "PAPER_RISK_CONTROLLER_EXPLORATION"
        reasons.append("GLOBAL_GUARDIAN_HALT_SCOPED_TO_PAPER_RISK_CONTROLLER_EXPLORATION")
    elif expected_edge is None or expected_edge <= 0:
        decision = "NO_TRADE"
    elif exit_score < 0.35:
        decision = "NO_TRADE"
    elif guardian_halted:
        decision = "NO_TRADE"
    elif advanced_shadow:
        decision = "SHADOW_ONLY"
    elif confidence_risk >= 0.75 or exit_score < 0.55 or bucket.get("bucket_evidence_missing"):
        decision = "SHADOW_ONLY"
    elif micro_action == "REDUCE_SIZE" or (trust is not None and trust < 0.65):
        decision = (
            "REDUCE_SIZE_PAPER_ONLY"
            if not guardian_halted and expected_edge is not None and expected_edge > 0
            else "SHADOW_ONLY"
        )
    else:
        decision = "ALLOW"

    # Alt-data demotions run AFTER the base decision so they can only make
    # the outcome safer (ALLOW -> REDUCE -> NO_TRADE); they never promote.
    if altdata_block_hit and decision in {"ALLOW", "REDUCE_SIZE_PAPER_ONLY", "POSITIVE_EDGE_PROBATION_PAPER"}:
        decision = "NO_TRADE"
    elif (altdata_reduce_hit or altdata_distribution_conflict) and decision == "ALLOW":
        decision = "REDUCE_SIZE_PAPER_ONLY"

    if decision == "NO_TRADE":
        portfolio["target_notional_usd"] = 0.0
        portfolio["allocated_margin_usd"] = 0.0

    unique_reasons = list(dict.fromkeys(str(reason) for reason in reasons if str(reason)))
    return canonicalize_preemptive_decision(
        candidate,
        {
        "schema_version": SCHEMA_VERSION,
        "preemptive_decision": decision,
        "preemptive_decision_id": _decision_id(candidate, decision, unique_reasons),
        "preemptive_decision_reasons": unique_reasons,
        "pre_trade_loss_probability": loss.get("pre_trade_loss_probability"),
        "confidence_overstatement_risk": confidence.get("confidence_overstatement_risk"),
        "expected_edge_after_cost_bps": cost.get("expected_edge_after_cost_bps"),
        "altdata_confluence_present": altdata_present,
        "altdata_trade_block_score": altdata_block,
        "altdata_reduce_size_score": altdata_reduce,
        "altdata_hedge_required_score": altdata_hedge,
        "altdata_hedge_required": altdata_hedge_required,
        "altdata_wallet_distribution_score": altdata_distribution,
        "altdata_liquidation_sweep_risk_score": altdata_sweep,
        "altdata_social_euphoria_risk_score": altdata_euphoria,
        "altdata_feature_cutoff": (altdata_confluence or {}).get("feature_cutoff"),
        "altdata_providers_present": (altdata_confluence or {}).get("providers_present"),
        "altdata_can_approve_alone": False,
        "notional_weighted_bucket_expectancy": bucket.get("notional_weighted_bucket_expectancy"),
        "bucket_profit_factor": bucket.get("bucket_profit_factor"),
        "recent_high_confidence_loss_rate": bucket.get("recent_high_confidence_loss_rate"),
        "recent_ATR_stop_risk": bucket.get("recent_ATR_stop_risk"),
        "regime_compatibility_score": regime.get("regime_compatibility_score"),
        "microstructure_trust_score": trust,
        "trade_tape_confirmation_score": regime.get("trade_tape_confirmation_score"),
        "cross_venue_confirmation_score": regime.get("cross_venue_confirmation_score"),
        "liquidity_sweep_risk": regime.get("liquidity_sweep_risk"),
        "spread_slippage_funding_cost_bps": cost.get("spread_slippage_funding_cost_bps"),
        "exit_feasibility_score": exit_plan.get("exit_feasibility_score"),
        "stop_distance_vs_noise": exit_plan.get("stop_distance_vs_noise"),
        "MFE_required_to_profit": exit_plan.get("MFE_required_to_profit"),
        "portfolio_stress_after_trade": portfolio.get("portfolio_stress_after_trade"),
        "correlation_exposure_after_trade": portfolio.get("correlation_exposure_after_trade"),
        "risk_of_ruin_delta": portfolio.get("risk_of_ruin_delta"),
        "target_notional_usd": portfolio.get("target_notional_usd"),
        "allocated_margin_usd": portfolio.get("allocated_margin_usd"),
        "recommended_leverage": portfolio.get("recommended_leverage"),
        "recommended_margin_mode": portfolio.get("recommended_margin_mode"),
        "risk_budget_usd": portfolio.get("risk_budget_usd"),
        "max_loss_if_stop_hit": portfolio.get("max_loss_if_stop_hit"),
        "liquidation_price": portfolio.get("liquidation_price"),
        "liquidation_buffer": portfolio.get("liquidation_buffer"),
        "portfolio_exposure_after_trade": portfolio.get("portfolio_exposure_after_trade"),
        "advanced_indicator_consumed": advanced.get("advanced_indicator_consumed"),
        "advanced_indicator_status": advanced.get("advanced_indicator_status"),
        "advanced_indicator_block": advanced.get("advanced_indicator_block"),
        "advanced_indicator_shadow": advanced.get("advanced_indicator_shadow"),
        "advanced_indicator_block_reasons": advanced.get("advanced_indicator_block_reasons"),
        "advanced_indicator_caution_reasons": advanced.get("advanced_indicator_caution_reasons"),
        "advanced_indicator_missing_evidence": advanced.get("advanced_indicator_missing_evidence"),
        "advanced_indicator_confluence_score": advanced.get("advanced_indicator_confluence_score"),
        "advanced_indicator_exit_plan_inputs": advanced.get("advanced_indicator_exit_plan_inputs"),
        "fvg_standalone_allows_trade": advanced.get("fvg_standalone_allows_trade"),
        "fvg_present": advanced.get("fvg_present"),
        "fvg_side_aligned": advanced.get("fvg_side_aligned"),
        "candidate_bucket_keys": bucket.get("candidate_bucket_keys"),
        "negative_buckets": bucket.get("negative_buckets"),
        "insufficient_evidence_buckets": bucket.get("insufficient_evidence_buckets"),
        "matched_quarantined_bucket_keys": bucket.get("matched_quarantined_bucket_keys", []),
        "advisory_quarantined_bucket_keys": bucket.get("advisory_quarantined_bucket_keys", []),
        "admission_confidence": confidence.get("admission_confidence"),
        "raw_confidence": confidence.get("raw_confidence"),
        "calibrated_confidence": confidence.get("calibrated_confidence"),
        "allow_paper_fill": decision
        in {
            "ALLOW",
            "REDUCE_SIZE_PAPER_ONLY",
            "POSITIVE_EDGE_PROBATION_PAPER",
            "PAPER_RISK_CONTROLLER_EXPLORATION",
        },
        "allow_positive_edge_probation_paper": (
            decision == "POSITIVE_EDGE_PROBATION_PAPER"
        ),
        "allow_paper_risk_controller_exploration": (
            decision == "PAPER_RISK_CONTROLLER_EXPLORATION"
        ),
        "paper_risk_controller_exploration": (
            decision == "PAPER_RISK_CONTROLLER_EXPLORATION"
        ),
        "allow_reduced_size_paper_only": decision == "REDUCE_SIZE_PAPER_ONLY",
        "allow_live_dry_run": decision == "ALLOW",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        },
        continuous_edge_guardian_gate=continuous_edge_guardian_gate,
    )


def summarize_decisions(decisions: list[dict[str, Any]], *, accepted_rows: list[dict[str, Any]] | None = None, generated_utc: str | None = None) -> dict[str, Any]:
    accepted_rows = accepted_rows or []
    counts: dict[str, int] = {}
    missing = 0
    high_loss_accepted = 0
    reduce_without_guardian = 0
    accepted_advanced_indicator_block = 0
    for item in decisions:
        decision = str(item.get("preemptive_decision") or "MISSING")
        counts[decision] = counts.get(decision, 0) + 1
    action_counts: dict[str, int] = {}
    for item in decisions:
        action = str(item.get("preemptive_action") or "MISSING")
        action_counts[action] = action_counts.get(action, 0) + 1
    for row in accepted_rows:
        decision = row.get("preemptive_decision")
        if not decision:
            missing += 1
        if (_f(row.get("pre_trade_loss_probability")) or 0.0) >= 0.80:
            high_loss_accepted += 1
        if (
            row.get("paper_opportunity_tier") == "A_PLUS_BOOTSTRAP_REDUCED_SIZE"
            and row.get("reduce_size_guardian_approved") is not True
        ):
            reduce_without_guardian += 1
        if row.get("advanced_indicator_block") is True:
            accepted_advanced_indicator_block += 1
    return {
        "schema_version": "preemptive_edge_control_status_v1",
        "generated_utc": generated_utc,
        "decision_counts": counts,
        "action_counts": action_counts,
        "candidate_count": len(decisions),
        "accepted_count": len(accepted_rows),
        "accepted_without_preemptive_decision": missing,
        "accepted_high_loss_probability_count": high_loss_accepted,
        "reduced_size_without_guardian_approval_count": reduce_without_guardian,
        "accepted_advanced_indicator_block_count": accepted_advanced_indicator_block,
        "hard_fail": bool(
            missing
            or high_loss_accepted
            or reduce_without_guardian
            or accepted_advanced_indicator_block
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
