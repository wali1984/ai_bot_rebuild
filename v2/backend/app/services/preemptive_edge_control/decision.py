"""Unified preemptive edge-control decision object."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.services.market_structure.decision_context import (
    evaluate_advanced_indicator_context,
)
from v2.backend.app.services.preemptive_edge_control.bucket_health import (
    build_bucket_health,
    candidate_bucket_assessment,
)
from v2.backend.app.services.preemptive_edge_control.candidate_loss_risk import (
    adaptive_microstructure_trust_threshold,
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
PREEMPTIVE_INPUT_SCHEMA_VERSION = "preemptive_edge_control_input_v2"
PREEMPTIVE_INPUT_HASH_ALGORITHM = "sha256(canonical-json-v1)"
PAPER_RISK_CONTROLLER_EXPLORATION_TIER = "PAPER_RISK_CONTROLLER_EXPLORATION"
CONSERVATIVE_LOSS_PROBABILITY_THRESHOLD = 0.80
PAPER_EXACT_ZERO_LOSS_SEMANTICS_CONTROL_FLAG = (
    "paper_exact_zero_loss_probability_semantics_v1"
)


class PreemptiveReplayError(ValueError):
    """Raised when a retained preemptive receipt cannot be replayed exactly."""

    def __init__(self, reason: str) -> None:
        self.reason = str(reason)
        super().__init__(self.reason)


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalized_side(candidate: Mapping[str, Any]) -> str | None:
    side = str(
        candidate.get("side") or candidate.get("action") or candidate.get("selected_action") or ""
    ).lower()
    if side in {"long", "buy"}:
        return "long"
    if side in {"short", "sell"}:
        return "short"
    return None


def _strategy(candidate: Mapping[str, Any]) -> str | None:
    value = (
        candidate.get("strategy_selected_mode")
        or candidate.get("strategy_id")
        or candidate.get("strategy_mode")
        or candidate.get("strategy_family")
    )
    return str(value).strip() if value not in (None, "") else None


def _regime(candidate: Mapping[str, Any]) -> str | None:
    value = (
        candidate.get("strategy_market_regime")
        or candidate.get("market_regime_at_entry")
        or candidate.get("market_regime")
    )
    return str(value).strip() if value not in (None, "") else None


def _trust_score(candidate: Mapping[str, Any]) -> float | None:
    trust = _f(
        _first_present(
            candidate.get("composite_microstructure_trust_score"),
            candidate.get("microstructure_trust_score"),
            candidate.get("public_orderbook_trust_score"),
        )
    )
    if trust is not None:
        return trust
    market_integrity = _f(candidate.get("market_state_integrity_score"))
    if market_integrity is None:
        return None
    return market_integrity / 100.0 if market_integrity > 1.0 else market_integrity


def _guardian_halted(guardian: Mapping[str, Any] | None) -> bool:
    if not isinstance(guardian, Mapping) or not guardian:
        return True
    status = str(guardian.get("status") or guardian.get("state") or "").upper()
    if any(token in status for token in ("HALTED", "BLOCKED", "SHADOW_ONLY")):
        return True
    for field in (
        "a_grade_new_entries_allowed",
        "new_entries_allowed",
        "guardian_new_entries_allowed",
    ):
        if guardian.get(field) is not None:
            return guardian.get(field) is not True
    return False


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _valid_probability(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = _f(value)
    if parsed is None or not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        return None
    return parsed


def adaptive_loss_probability_threshold(
    adaptive_tuning_state: Mapping[str, Any] | None,
) -> float:
    """Derive the loss block threshold without performing external I/O."""
    if not isinstance(adaptive_tuning_state, Mapping):
        return CONSERVATIVE_LOSS_PROBABILITY_THRESHOLD
    threshold = _valid_probability(adaptive_tuning_state.get("adaptive_loss_probability_threshold"))
    return threshold if threshold is not None else CONSERVATIVE_LOSS_PROBABILITY_THRESHOLD


def _snapshot_tuning_state(
    adaptive_tuning_state: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    if adaptive_tuning_state is None:
        return {}, "ABSENT_CONSERVATIVE_DEFAULTS"
    if not isinstance(adaptive_tuning_state, Mapping):
        return {}, "INVALID_CONSERVATIVE_DEFAULTS"
    try:
        snapshot = copy.deepcopy(dict(adaptive_tuning_state))
    except Exception:
        return {}, "INVALID_CONSERVATIVE_DEFAULTS"
    if not snapshot:
        return {}, "EMPTY_CONSERVATIVE_DEFAULTS"
    return snapshot, "VALID_EXPLICIT_SNAPSHOT"


def _snapshot_optional_mapping(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return copy.deepcopy(dict(value))
    except Exception:
        return None


def _canonical_hash_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {"__non_finite_float__": str(value).lower()}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return {"__naive_datetime__": value.isoformat(timespec="microseconds")}
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_hash_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list | tuple):
        return [_canonical_hash_value(item) for item in value]
    if isinstance(value, set | frozenset):
        canonical_items = [_canonical_hash_value(item) for item in value]
        return sorted(
            canonical_items,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ),
        )
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    return {"__unsupported_type__": (f"{type(value).__module__}.{type(value).__qualname__}")}


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _canonical_hash_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_payload_sha256(payload: Mapping[str, Any]) -> str | None:
    """Match the paper-loop full-payload snapshot hash for cross-receipt joins."""
    if not payload:
        return None
    canonical = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_preemptive_decision_time(
    decision_time: str | datetime | None,
) -> tuple[str, str, bool, Any]:
    runtime_now = datetime.now(UTC)
    if decision_time is None:
        return (
            runtime_now.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "RUNTIME_CLOCK",
            True,
            None,
        )
    parsed: datetime | None = None
    if isinstance(decision_time, datetime):
        parsed = decision_time
    elif isinstance(decision_time, str) and decision_time.strip():
        try:
            parsed = datetime.fromisoformat(decision_time.strip().replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    if parsed is not None and parsed.tzinfo is not None and parsed.utcoffset() is not None:
        normalized = (
            parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        )
        return (
            normalized,
            "EXPLICIT_ARGUMENT",
            True,
            normalized,
        )
    return (
        runtime_now.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "INVALID_EXPLICIT_ARGUMENT_RUNTIME_CLOCK_BLOCK",
        False,
        decision_time,
    )


def _preemptive_input_material(
    *,
    candidate: Mapping[str, Any],
    decision_time: str,
    decision_time_source: str,
    requested_decision_time: Any,
    decision_time_input_valid: bool,
    tuning_state: Mapping[str, Any],
    tuning_state_status: str,
    guardian: Mapping[str, Any] | None,
    bucket_quarantine_status: Mapping[str, Any] | None,
    control_flags: Mapping[str, Any],
    resolved_bucket_health_snapshot: Mapping[str, Any],
    bucket_assessment: Mapping[str, Any] | None = None,
    cost_evidence: Mapping[str, Any] | None = None,
    advanced_indicator_evidence: Mapping[str, Any] | None = None,
    altdata_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the complete immutable material consumed by the decision.

    Retaining this material makes the input hash independently reconstructible
    at the final paper-admission boundary.  A hash without its exact material
    would only detect accidental corruption, not receipt transplantation.
    """

    return {
        "schema_version": PREEMPTIVE_INPUT_SCHEMA_VERSION,
        "candidate": candidate,
        "resolved_bucket_health_snapshot": resolved_bucket_health_snapshot,
        "bucket_assessment": bucket_assessment,
        "cost_evidence": cost_evidence,
        "advanced_indicator_evidence": advanced_indicator_evidence,
        "altdata_evidence": altdata_evidence,
        "adaptive_tuning_state": tuning_state,
        "adaptive_tuning_state_status": tuning_state_status,
        "continuous_edge_guardian_gate": guardian,
        "bucket_quarantine_status": bucket_quarantine_status,
        "control_flags": control_flags,
        "clocks": {
            "preemptive_decision_time": decision_time,
            "preemptive_decision_time_source": decision_time_source,
            "preemptive_decision_time_input_valid": decision_time_input_valid,
            "requested_decision_time": requested_decision_time,
            "candidate_decision_time": candidate.get("decision_time"),
            "candidate_feature_cutoff": candidate.get("feature_cutoff"),
            "candidate_available_at": candidate.get("available_at"),
            "advanced_indicator_event_time": candidate.get("advanced_indicator_event_time"),
            "advanced_indicator_available_at": candidate.get("advanced_indicator_available_at"),
            "altdata_feature_cutoff": (altdata_evidence or {}).get("feature_cutoff"),
            "altdata_available_at": (altdata_evidence or {}).get("available_at"),
            "cost_source_timestamp": candidate.get("cost_source_timestamp"),
            "cost_decision_time": candidate.get("runtime_cost_decision_time"),
        },
    }


def canonical_preemptive_input_hash(input_material: Mapping[str, Any]) -> str:
    """Recompute the canonical preemptive-input hash from retained material."""

    return _canonical_sha256(input_material)


def _preemptive_input_bundle(**kwargs: Any) -> tuple[dict[str, Any], str]:
    material = _preemptive_input_material(**kwargs)
    return material, canonical_preemptive_input_hash(material)


def _preemptive_input_receipt(
    *,
    preemptive_input_material: Mapping[str, Any],
    preemptive_input_hash: str,
    decision_time: str,
    decision_time_source: str,
    decision_time_input_valid: bool,
    tuning_state: Mapping[str, Any],
    tuning_state_status: str,
) -> dict[str, Any]:
    loss_threshold_explicit = _valid_probability(
        tuning_state.get("adaptive_loss_probability_threshold")
    )
    if loss_threshold_explicit is not None:
        loss_threshold_source = "EXPLICIT_ADAPTIVE_TUNING_SNAPSHOT"
    else:
        loss_threshold_source = "CONSERVATIVE_DEFAULT_ABSENT_OR_INVALID"

    if "adaptive_microstructure_trust_threshold" in tuning_state:
        microstructure_threshold_source = (
            "EXPLICIT_ADAPTIVE_TUNING_SNAPSHOT"
            if _valid_probability(tuning_state.get("adaptive_microstructure_trust_threshold"))
            is not None
            else "CONSERVATIVE_DEFAULT_INVALID_EXPLICIT_THRESHOLD"
        )
    elif isinstance(tuning_state.get("enable_b_grade"), bool):
        microstructure_threshold_source = "DERIVED_FROM_EXPLICIT_B_GRADE_SNAPSHOT"
    else:
        microstructure_threshold_source = "CONSERVATIVE_DEFAULT_ABSENT_OR_INVALID"

    return {
        "preemptive_input_schema_version": PREEMPTIVE_INPUT_SCHEMA_VERSION,
        "preemptive_input_material": copy.deepcopy(dict(preemptive_input_material)),
        "preemptive_input_hash": preemptive_input_hash,
        "preemptive_input_hash_algorithm": PREEMPTIVE_INPUT_HASH_ALGORITHM,
        "preemptive_decision_time": decision_time,
        "preemptive_decision_time_source": decision_time_source,
        "preemptive_decision_time_input_valid": decision_time_input_valid,
        "adaptive_tuning_state_status": tuning_state_status,
        "adaptive_tuning_state_hash": _source_payload_sha256(tuning_state),
        "adaptive_loss_probability_threshold_used": (
            adaptive_loss_probability_threshold(tuning_state)
        ),
        "adaptive_loss_probability_threshold_source": loss_threshold_source,
        "adaptive_microstructure_trust_threshold_used": (
            adaptive_microstructure_trust_threshold(tuning_state)
        ),
        "adaptive_microstructure_trust_threshold_source": (microstructure_threshold_source),
    }


def _is_paper_risk_controller_exploration_candidate(candidate: dict[str, Any]) -> bool:
    tier = (
        str(
            _first_present(
                candidate.get("paper_opportunity_tier"),
                candidate.get("tier"),
                candidate.get("exploration_tier"),
                candidate.get("paper_exploration_tier"),
            )
            or ""
        )
        .strip()
        .upper()
    )
    return (
        tier == PAPER_RISK_CONTROLLER_EXPLORATION_TIER
        or candidate.get("paper_risk_controller_exploration") is True
        or candidate.get("allow_paper_risk_controller_exploration") is True
    )


def _paper_exploration_specific_quarantine_key(key: Any) -> bool:
    normalized = str(key or "")
    return bool(normalized) and not normalized.startswith(("side:", "timeframe:", "regime:"))


def _paper_exploration_bucket_quarantine_split(
    candidate: dict[str, Any],
    matched: list[str],
) -> tuple[list[str], list[str]]:
    if not _is_paper_risk_controller_exploration_candidate(candidate):
        return matched, []
    exact_from_paper_loop = {
        str(key) for key in candidate.get("paper_exploration_exact_blocked_bucket_keys") or []
    }
    if exact_from_paper_loop:
        hard = sorted(set(matched) & exact_from_paper_loop)
        advisory = sorted(set(matched) - set(hard))
        return hard, advisory
    hard = [key for key in matched if _paper_exploration_specific_quarantine_key(key)]
    advisory = [key for key in matched if key not in hard]
    return hard, advisory


def recompute_preemptive_decision_id(
    candidate: Mapping[str, Any],
    decision: str,
    reasons: list[str],
    *,
    preemptive_input_hash: str,
) -> str:
    basis = {
        "symbol": candidate.get("symbol"),
        "timeframe": candidate.get("timeframe") or candidate.get("thesis_timeframe"),
        "side": _normalized_side(candidate),
        "strategy": _strategy(candidate),
        "prediction_id": candidate.get("prediction_id") or candidate.get("source_prediction_id"),
        "signal_id": candidate.get("signal_id"),
        "decision": decision,
        "reasons": reasons,
        "preemptive_input_hash": preemptive_input_hash,
    }
    digest = hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[
        :24
    ]
    return f"pec_{digest}"


def _decision_id(
    candidate: dict[str, Any],
    decision: str,
    reasons: list[str],
    *,
    preemptive_input_hash: str,
) -> str:
    return recompute_preemptive_decision_id(
        candidate,
        decision,
        reasons,
        preemptive_input_hash=preemptive_input_hash,
    )


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
    adaptive_tuning_state: Mapping[str, Any] | None = None,
    decision_time: str | datetime | None = None,
    _paper_exact_zero_loss_semantics: bool = False,
) -> dict[str, Any]:
    """Return a complete pre-entry decision object.

    Missing critical evidence fails closed. The only non-entry escape hatch is
    CLOSE_OR_REDUCE_ONLY for explicit reduce/close actions.
    """
    try:
        candidate_snapshot = copy.deepcopy(candidate) if isinstance(candidate, dict) else {}
    except Exception:
        candidate_snapshot = {}
    guardian_snapshot = _snapshot_optional_mapping(continuous_edge_guardian_gate)
    quarantine_snapshot = _snapshot_optional_mapping(bucket_quarantine_status)
    altdata_snapshot = _snapshot_optional_mapping(altdata_confluence)
    try:
        bucket_health_snapshot = (
            copy.deepcopy(bucket_health) if isinstance(bucket_health, dict) else None
        )
    except Exception:
        bucket_health_snapshot = None
    try:
        closed_rows_snapshot = copy.deepcopy(closed_rows) if isinstance(closed_rows, list) else []
    except Exception:
        closed_rows_snapshot = []
    tuning_state, tuning_state_status = _snapshot_tuning_state(adaptive_tuning_state)
    (
        resolved_decision_time,
        decision_time_source,
        decision_time_input_valid,
        requested_decision_time,
    ) = _resolve_preemptive_decision_time(decision_time)
    control_flags = {
        "allow_positive_edge_probation": allow_positive_edge_probation,
        "allow_paper_risk_controller_exploration": (allow_paper_risk_controller_exploration),
        "allow_reduce_or_close": allow_reduce_or_close,
    }
    if _paper_exact_zero_loss_semantics:
        # This flag is part of the authenticated input material.  Paper replay
        # can therefore reproduce exact-zero handling without silently
        # changing the shared evaluator used by live readiness and transport.
        control_flags[PAPER_EXACT_ZERO_LOSS_SEMANTICS_CONTROL_FLAG] = True

    if not candidate_snapshot:
        decision = "NO_TRADE"
        reasons = ["CANDIDATE_PAYLOAD_MISSING"]
        if not decision_time_input_valid:
            reasons.append("PREEMPTIVE_DECISION_TIME_INVALID")
        preemptive_input_material, preemptive_input_hash = _preemptive_input_bundle(
            candidate={},
            decision_time=resolved_decision_time,
            decision_time_source=decision_time_source,
            requested_decision_time=requested_decision_time,
            decision_time_input_valid=decision_time_input_valid,
            tuning_state=tuning_state,
            tuning_state_status=tuning_state_status,
            guardian=guardian_snapshot,
            bucket_quarantine_status=quarantine_snapshot,
            control_flags=control_flags,
            resolved_bucket_health_snapshot={},
            altdata_evidence=altdata_snapshot,
        )
        return canonicalize_preemptive_decision(
            {},
            {
                "schema_version": SCHEMA_VERSION,
                "preemptive_decision": decision,
                "preemptive_decision_id": _decision_id(
                    {},
                    decision,
                    reasons,
                    preemptive_input_hash=preemptive_input_hash,
                ),
                "preemptive_decision_reasons": reasons,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
                **_preemptive_input_receipt(
                    preemptive_input_material=preemptive_input_material,
                    preemptive_input_hash=preemptive_input_hash,
                    decision_time=resolved_decision_time,
                    decision_time_source=decision_time_source,
                    decision_time_input_valid=decision_time_input_valid,
                    tuning_state=tuning_state,
                    tuning_state_status=tuning_state_status,
                ),
            },
            continuous_edge_guardian_gate=guardian_snapshot,
        )

    candidate = candidate_snapshot
    bucket_quarantine_status = quarantine_snapshot
    altdata_confluence = altdata_snapshot
    continuous_edge_guardian_gate = guardian_snapshot

    action = str(candidate.get("action") or candidate.get("requested_action") or "").lower()
    if allow_reduce_or_close and (
        candidate.get("reduce_only") is True or action in {"close", "reduce"}
    ):
        decision = "CLOSE_OR_REDUCE_ONLY"
        reasons = ["EXPLICIT_CLOSE_OR_REDUCE_ACTION"]
        if not decision_time_input_valid:
            reasons.append("PREEMPTIVE_DECISION_TIME_INVALID_CLOSE_ONLY_ALLOWED")
        close_cost = assess_cost_edge(candidate)
        close_advanced = evaluate_advanced_indicator_context(candidate)
        preemptive_input_material, preemptive_input_hash = _preemptive_input_bundle(
            candidate=candidate,
            decision_time=resolved_decision_time,
            decision_time_source=decision_time_source,
            requested_decision_time=requested_decision_time,
            decision_time_input_valid=decision_time_input_valid,
            tuning_state=tuning_state,
            tuning_state_status=tuning_state_status,
            guardian=guardian_snapshot,
            bucket_quarantine_status=quarantine_snapshot,
            control_flags=control_flags,
            resolved_bucket_health_snapshot={},
            cost_evidence=close_cost,
            advanced_indicator_evidence=close_advanced,
            altdata_evidence=altdata_snapshot,
        )
        return canonicalize_preemptive_decision(
            candidate,
            {
                "schema_version": SCHEMA_VERSION,
                "preemptive_decision": decision,
                "preemptive_decision_id": _decision_id(
                    candidate,
                    decision,
                    reasons,
                    preemptive_input_hash=preemptive_input_hash,
                ),
                "preemptive_decision_reasons": reasons,
                "allow_close": True,
                "allow_reduce": True,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
                **_preemptive_input_receipt(
                    preemptive_input_material=preemptive_input_material,
                    preemptive_input_hash=preemptive_input_hash,
                    decision_time=resolved_decision_time,
                    decision_time_source=decision_time_source,
                    decision_time_input_valid=decision_time_input_valid,
                    tuning_state=tuning_state,
                    tuning_state_status=tuning_state_status,
                ),
            },
            continuous_edge_guardian_gate=continuous_edge_guardian_gate,
        )

    health = (
        bucket_health_snapshot
        if bucket_health_snapshot is not None
        else build_bucket_health(closed_rows_snapshot)
    )
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
        adaptive_tuning_state=tuning_state,
    )

    reasons = []
    reasons.extend(cost.get("cost_edge_reasons") or [])
    reasons.extend(confidence.get("confidence_overstatement_reasons") or [])
    reasons.extend(regime.get("regime_compatibility_reasons") or [])
    reasons.extend(exit_plan.get("exit_feasibility_reasons") or [])
    reasons.extend(loss.get("pre_trade_loss_risk_reasons") or [])
    reasons.extend(advanced.get("advanced_indicator_block_reasons") or [])
    reasons.extend(advanced.get("advanced_indicator_caution_reasons") or [])
    reasons.extend(advanced.get("advanced_indicator_missing_evidence") or [])
    if not decision_time_input_valid:
        reasons.append("PREEMPTIVE_DECISION_TIME_INVALID")
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

    # Alt-data confluence (CoinGlass+Moralis fusion) is fail-safe
    # only: it can block, demote to reduce-size, or require a hedge. It can
    # never promote a decision toward ALLOW, and its absence never blocks.
    altdata_row = altdata_confluence if isinstance(altdata_confluence, Mapping) else {}
    altdata_features_value = altdata_row.get("features")
    altdata_features = altdata_features_value if isinstance(altdata_features_value, Mapping) else {}
    altdata_present = bool(altdata_features) and bool(altdata_row.get("actual_payload_present"))
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

    if _paper_exact_zero_loss_semantics:
        parsed_loss_probability = _f(loss.get("pre_trade_loss_probability"))
        loss_probability = 1.0 if parsed_loss_probability is None else parsed_loss_probability
    else:
        # Preserve the historical shared/live behavior exactly.  Paper-only
        # exact-zero handling is available only through the paper adapter.
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

    adaptive_loss_prob_threshold = adaptive_loss_probability_threshold(tuning_state)

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
        and guardian_halted
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
        or loss_probability >= adaptive_loss_prob_threshold
        or advanced_block
        or not decision_time_input_valid
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
    if altdata_block_hit and decision in {
        "ALLOW",
        "REDUCE_SIZE_PAPER_ONLY",
        "POSITIVE_EDGE_PROBATION_PAPER",
    }:
        decision = "NO_TRADE"
    elif (altdata_reduce_hit or altdata_distribution_conflict) and decision == "ALLOW":
        decision = "REDUCE_SIZE_PAPER_ONLY"

    if decision == "NO_TRADE":
        portfolio["target_notional_usd"] = 0.0
        portfolio["allocated_margin_usd"] = 0.0

    unique_reasons = list(dict.fromkeys(str(reason) for reason in reasons if str(reason)))
    preemptive_input_material, preemptive_input_hash = _preemptive_input_bundle(
        candidate=candidate,
        decision_time=resolved_decision_time,
        decision_time_source=decision_time_source,
        requested_decision_time=requested_decision_time,
        decision_time_input_valid=decision_time_input_valid,
        tuning_state=tuning_state,
        tuning_state_status=tuning_state_status,
        guardian=guardian_snapshot,
        bucket_quarantine_status=quarantine_snapshot,
        control_flags=control_flags,
        resolved_bucket_health_snapshot=health,
        bucket_assessment=bucket,
        cost_evidence=cost,
        advanced_indicator_evidence=advanced,
        altdata_evidence=altdata_snapshot,
    )
    return canonicalize_preemptive_decision(
        candidate,
        {
            "schema_version": SCHEMA_VERSION,
            "preemptive_decision": decision,
            "preemptive_decision_id": _decision_id(
                candidate,
                decision,
                unique_reasons,
                preemptive_input_hash=preemptive_input_hash,
            ),
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
            "notional_weighted_bucket_expectancy": bucket.get(
                "notional_weighted_bucket_expectancy"
            ),
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
            "advanced_indicator_caution_reasons": advanced.get(
                "advanced_indicator_caution_reasons"
            ),
            "advanced_indicator_missing_evidence": advanced.get(
                "advanced_indicator_missing_evidence"
            ),
            "advanced_indicator_confluence_score": advanced.get(
                "advanced_indicator_confluence_score"
            ),
            "advanced_indicator_exit_plan_inputs": advanced.get(
                "advanced_indicator_exit_plan_inputs"
            ),
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
            "allow_positive_edge_probation_paper": (decision == "POSITIVE_EDGE_PROBATION_PAPER"),
            "allow_paper_risk_controller_exploration": (
                decision == "PAPER_RISK_CONTROLLER_EXPLORATION"
            ),
            "paper_risk_controller_exploration": (decision == "PAPER_RISK_CONTROLLER_EXPLORATION"),
            "allow_reduced_size_paper_only": decision == "REDUCE_SIZE_PAPER_ONLY",
            "allow_live_dry_run": decision == "ALLOW",
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            **_preemptive_input_receipt(
                preemptive_input_material=preemptive_input_material,
                preemptive_input_hash=preemptive_input_hash,
                decision_time=resolved_decision_time,
                decision_time_source=decision_time_source,
                decision_time_input_valid=decision_time_input_valid,
                tuning_state=tuning_state,
                tuning_state_status=tuning_state_status,
            ),
        },
        continuous_edge_guardian_gate=continuous_edge_guardian_gate,
    )


def replay_preemptive_decision(
    input_material: Mapping[str, Any],
    *,
    expected_input_hash: str | None = None,
    _paper_exact_zero_loss_semantics: bool = False,
) -> dict[str, Any]:
    """Re-evaluate one decision solely from its retained immutable inputs.

    Replay deliberately performs no Redis, environment, or other external read.
    Only v2 material with an explicit aware decision clock is replayable.  Older
    material omitted the resolved bucket-health snapshot, so accepting it would
    require inventing evidence and is therefore unsafe.

    The regenerated material must hash identically to the supplied material.
    This proves that retained derived evidence (bucket assessment, costs, and
    advanced-indicator assessment) agrees with a fresh run of the canonical
    evaluator before its decision is trusted by a final admission boundary.
    """

    if not isinstance(input_material, Mapping):
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_INPUT_NOT_MAPPING")
    try:
        material_snapshot = copy.deepcopy(dict(input_material))
    except Exception as exc:
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_INPUT_NOT_MATERIALIZABLE") from exc

    if material_snapshot.get("schema_version") != PREEMPTIVE_INPUT_SCHEMA_VERSION:
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_UNSUPPORTED_INPUT_SCHEMA")

    candidate = material_snapshot.get("candidate")
    if not isinstance(candidate, Mapping):
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_CANDIDATE_NOT_MAPPING")
    resolved_bucket_health = material_snapshot.get("resolved_bucket_health_snapshot")
    if not isinstance(resolved_bucket_health, Mapping):
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_BUCKET_HEALTH_NOT_MAPPING")
    tuning_state = material_snapshot.get("adaptive_tuning_state")
    if not isinstance(tuning_state, Mapping):
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_ADAPTIVE_TUNING_NOT_MAPPING")
    control_flags = material_snapshot.get("control_flags")
    if not isinstance(control_flags, Mapping):
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_CONTROL_FLAGS_NOT_MAPPING")
    required_control_flags = (
        "allow_positive_edge_probation",
        "allow_paper_risk_controller_exploration",
        "allow_reduce_or_close",
    )
    if any(type(control_flags.get(field)) is not bool for field in required_control_flags):
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_CONTROL_FLAGS_INVALID")
    material_uses_paper_exact_zero = (
        control_flags.get(PAPER_EXACT_ZERO_LOSS_SEMANTICS_CONTROL_FLAG) is True
    )
    if material_uses_paper_exact_zero != _paper_exact_zero_loss_semantics:
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_LOSS_SEMANTICS_MISMATCH")

    clocks = material_snapshot.get("clocks")
    if not isinstance(clocks, Mapping):
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_CLOCKS_NOT_MAPPING")
    decision_time = clocks.get("preemptive_decision_time")
    if (
        clocks.get("preemptive_decision_time_source") != "EXPLICIT_ARGUMENT"
        or clocks.get("preemptive_decision_time_input_valid") is not True
        or not isinstance(decision_time, str)
        or not decision_time
        or clocks.get("requested_decision_time") != decision_time
    ):
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_DECISION_TIME_NOT_EXPLICIT_AND_REPLAYABLE")

    def optional_mapping(field: str) -> dict[str, Any] | None:
        value = material_snapshot.get(field)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise PreemptiveReplayError(f"PREEMPTIVE_REPLAY_OPTIONAL_MAPPING_INVALID:{field}")
        try:
            return copy.deepcopy(dict(value))
        except Exception as exc:
            raise PreemptiveReplayError(
                f"PREEMPTIVE_REPLAY_OPTIONAL_MAPPING_NOT_MATERIALIZABLE:{field}"
            ) from exc

    try:
        supplied_material_hash = canonical_preemptive_input_hash(material_snapshot)
    except (TypeError, ValueError) as exc:
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_INPUT_HASH_RECOMPUTATION_FAILED") from exc
    if expected_input_hash is not None and expected_input_hash != supplied_material_hash:
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_EXPECTED_INPUT_HASH_MISMATCH")

    replayed = evaluate_candidate(
        copy.deepcopy(dict(candidate)),
        closed_rows=[],
        bucket_health=copy.deepcopy(dict(resolved_bucket_health)),
        continuous_edge_guardian_gate=optional_mapping("continuous_edge_guardian_gate"),
        bucket_quarantine_status=optional_mapping("bucket_quarantine_status"),
        allow_positive_edge_probation=control_flags["allow_positive_edge_probation"],
        allow_paper_risk_controller_exploration=control_flags[
            "allow_paper_risk_controller_exploration"
        ],
        allow_reduce_or_close=control_flags["allow_reduce_or_close"],
        altdata_confluence=optional_mapping("altdata_evidence"),
        adaptive_tuning_state=copy.deepcopy(dict(tuning_state)),
        decision_time=decision_time,
        _paper_exact_zero_loss_semantics=_paper_exact_zero_loss_semantics,
    )
    replayed_material = replayed.get("preemptive_input_material")
    if not isinstance(replayed_material, Mapping):
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_RESULT_INPUT_MATERIAL_MISSING")
    try:
        replayed_material_hash = canonical_preemptive_input_hash(replayed_material)
    except (TypeError, ValueError) as exc:
        raise PreemptiveReplayError(
            "PREEMPTIVE_REPLAY_RESULT_INPUT_HASH_RECOMPUTATION_FAILED"
        ) from exc
    if replayed_material_hash != supplied_material_hash:
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_MATERIAL_REGENERATION_MISMATCH")
    if replayed.get("preemptive_input_hash") != supplied_material_hash:
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_RESULT_INPUT_HASH_MISMATCH")
    return replayed


def summarize_decisions(
    decisions: list[dict[str, Any]],
    *,
    accepted_rows: list[dict[str, Any]] | None = None,
    generated_utc: str | None = None,
    adaptive_tuning_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    accepted_rows = accepted_rows or []
    counts: dict[str, int] = {}
    missing = 0
    high_loss_accepted = 0
    reduce_without_guardian = 0
    accepted_advanced_indicator_block = 0
    tuning_state, _ = _snapshot_tuning_state(adaptive_tuning_state)
    adaptive_loss_prob_threshold = adaptive_loss_probability_threshold(tuning_state)
    for item in decisions:
        decision = str(item.get("preemptive_decision") or "MISSING")
        counts[decision] = counts.get(decision, 0) + 1
    action_counts: dict[str, int] = {}
    for item in decisions:
        action = str(item.get("preemptive_action") or "MISSING")
        action_counts[action] = action_counts.get(action, 0) + 1
    for row in accepted_rows:
        row_decision = row.get("preemptive_decision")
        if not row_decision:
            missing += 1
        if (_f(row.get("pre_trade_loss_probability")) or 0.0) >= adaptive_loss_prob_threshold:
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
