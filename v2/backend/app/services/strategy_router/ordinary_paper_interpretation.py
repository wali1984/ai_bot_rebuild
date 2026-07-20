"""Paper-only interpretation of legacy strategy-router magnitude cliffs.

This module does not route orders and does not change :func:`route_strategy`.
It may only interpret the result of that router for an ordinary, scale-free
PAPER candidate which another component has already independently revalidated.

The legacy router mixes immutable safety decisions with fixed market-score
cutoffs.  Immutable PIT, transition, non-directional, close-only, and negative
performance quarantine decisions remain hard blocks here.  Market magnitudes
are represented by their actual bounded values and continuously contract an
already-safe PAPER sizing weight.  A missing, non-finite, or out-of-domain
magnitude fails closed.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    canonical_sha256,
)
from v2.backend.app.services.ordinary_paper_admission import (
    OrdinaryPaperAdmissionResult,
    ordinary_paper_admission_result_rejection_reasons,
)

from .service import MODE_NO_TRADE, MODE_REDUCE_SIZE, route_strategy

ORDINARY_PAPER_ROUTER_INTERPRETATION_SCHEMA_VERSION = (
    "v2_ordinary_paper_strategy_router_interpretation_v2"
)
ORDINARY_PAPER_ROUTER_CONTINUOUS_FORMULA = (
    "base_weight*geometric_mean(data_quality_fraction,masa_confidence,"
    "ppo_confidence,execution_success_probability,drawdown_headroom,"
    "volatility_headroom,liquidity_score,microstructure_trust_score,"
    "sweep_safety,timeframe_direction_alignment)"
)

# These are classifications of the existing router's telemetry, not tuning
# parameters.  None participates as a numerical boundary in the formula.
_SOFT_MAGNITUDE_REASONS = frozenset(
    {
        "ACTION_NOT_ALLOWED_BY_ROUTER",
        "CONFIDENCE_DISAGREEMENT",
        "DATA_QUALITY_BELOW_THRESHOLD",
        "DIRECTION_DISAGREEMENT",
        "DRAWDOWN_LIMIT_BLOCK",
        "DRAWDOWN_REDUCE_SIZE",
        "EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD",
        "EXECUTION_SUCCESS_SAMPLE_INSUFFICIENT_PAPER_SOFT_REDUCE",
        "HIGH_VOLATILITY_REDUCE_SIZE",
        "HTF_DIRECTION_CONFLICT",
        "LOWER_TIMEFRAME_TIMING_CONFLICT",
        "LOW_LIQUIDITY_REDUCE_SIZE",
        "MASA_CONFIDENCE_LOW",
        "MASA_CONFIDENCE_TOO_LOW",
        "MICROSTRUCTURE_ACTION_NO_TRADE",
        "MICROSTRUCTURE_ACTION_SHADOW_ONLY",
        "MICROSTRUCTURE_SWEEP_RISK_BLOCK",
        "MICROSTRUCTURE_SWEEP_RISK_REDUCE_SIZE",
        "MICROSTRUCTURE_TRUST_REDUCE_SIZE",
        "MICROSTRUCTURE_TRUST_SCORE_UNTRUSTED",
        "MID_TIMEFRAME_CONFLICT",
        "PPO_CONFIDENCE_LOW",
        "PPO_CONFIDENCE_TOO_LOW",
        "PPO_TRADE_MASA_NO_EDGE",
    }
)

_HARD_ROUTER_REASONS = frozenset(
    {
        "MASA_FUTURE_CUTOFF_BLOCK",
        "NEGATIVE_BUCKET_PERFORMANCE_QUARANTINE",
        "PAPER_LOSS_BUCKET_QUARANTINE",
        "POSITION_STATE_CONFLICT_BLOCK",
        "PPO_ACTION_NOT_TRADABLE",
        "PPO_HOLD_MASA_TRADE",
        "MICROSTRUCTURE_ACTION_CLOSE_OR_REDUCE_ONLY",
    }
)

_HARD_REASON_PREFIXES = (
    "PAPER_LOSS_BUCKET_QUARANTINE_MATCH:",
    "PIT_",
    "LOOKAHEAD_",
    "FUTURE_",
    "INVALID_TRANSITION_",
)

# Positive/diagnostic labels emitted by the authoritative router which do not
# represent a rejection or a magnitude cliff.  Every other unknown reason is
# a hard failure, even when ``block_reason`` is empty.
_BENIGN_TELEMETRY_REASONS = frozenset(
    {
        "CONFIRMED_MOMENTUM_RIDE_BREAKOUT",
        "CONFIRMED_MOMENTUM_RIDE_SWEEP_OVERRIDE",
        "PAPER_MAJOR_MOVE_EVIDENCE_BREAKOUT",
    }
)

_ROUTER_INPUT_FIELDS = (
    "market_state_envelope",
    "masa_predictions",
    "ppo_proposed_action",
    "current_position_state",
    "recent_execution_success_metrics",
    "volatility_liquidity_state",
    "data_quality_score",
    "current_drawdown_risk_state",
)
_ADMISSION_SOURCE_IDENTITY_FIELDS = (
    "prediction_id",
    "signal_id",
    "decision_id",
    "market_state_id",
    "symbol",
    "timeframe",
    "selected_action",
    "feature_snapshot_id",
    "feature_vector_hash",
    "input_feature_hash",
    "checkpoint_id",
    "model_version",
    "cycle_id",
    "process_instance_id",
    "candidate_policy_fingerprint",
    "source_redis_key",
    "replay_snapshot_id",
    "replay_snapshot_key",
    "replay_snapshot_content_sha256",
    "microstructure_trust_evidence_sha256",
)
_ADMISSION_PIT_FIELDS = (
    "source_event_time",
    "source_event_time_est",
    "source_received_time",
    "source_received_time_est",
    "source_available_time",
    "candle_open_time",
    "candle_close_time",
    "feature_cutoff",
    "available_at",
    "masa_feature_cutoff",
    "ppo_feature_cutoff",
    "ppo_decision_time",
    "decision_time",
)

_DIRECTION_ALIASES = {
    "buy": "long",
    "long": "long",
    "open_long": "long",
    "up": "long",
    "sell": "short",
    "short": "short",
    "open_short": "short",
    "down": "short",
}


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _direction(value: Any) -> str | None:
    return _DIRECTION_ALIASES.get(str(value or "").strip().lower())


def _reason_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [str(item) for item in value if str(item)]


def _strict_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _canonical_hash(value: Mapping[str, Any]) -> str | None:
    try:
        return canonical_sha256(value)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return None


def _original_trade_allowed(router_result: Mapping[str, Any], action: str | None) -> bool:
    explicit = router_result.get("strategy_trade_allowed")
    if isinstance(explicit, bool):
        return explicit
    allowed_actions = _reason_list(router_result.get("allowed_actions"))
    return bool(
        action in {"long", "short"}
        and router_result.get("block_reason") in (None, "")
        and str(router_result.get("selected_mode") or "") != MODE_NO_TRADE
        and action in allowed_actions
    )


def _passthrough_result(
    *,
    router_result: Mapping[str, Any],
    action: str | None,
    reason: str,
) -> dict[str, Any]:
    original_allowed = _original_trade_allowed(router_result, action)
    original_mode = str(router_result.get("selected_mode") or MODE_NO_TRADE)
    return {
        "schema_version": ORDINARY_PAPER_ROUTER_INTERPRETATION_SCHEMA_VERSION,
        "ordinary_paper_interpretation_claimed": False,
        "ordinary_paper_interpretation_applied": False,
        "interpretation_status": reason,
        "strategy_trade_allowed": original_allowed,
        "effective_mode": original_mode,
        "effective_action": action if original_allowed else "hold",
        "continuous_weight": None,
        "continuous_formula": None,
        "continuous_factors": {},
        "hard_reasons": [],
        "softened_reasons": [],
        "telemetry_reasons": _reason_list(router_result.get("reason_codes")),
        "original_router_trade_allowed": original_allowed,
        "original_router_selected_mode": original_mode,
        "original_router_block_reason": router_result.get("block_reason"),
        "original_router_reason_codes": _reason_list(router_result.get("reason_codes")),
        "original_router_telemetry": copy.deepcopy(dict(router_result)),
        "paper_only": False,
        "routes_to_live": False,
        "live_trade_allowed": False,
        "places_real_order": False,
        "exchange_mutation": False,
    }


def _bounded_unit_factor(
    *,
    name: str,
    value: Any,
    hard_reasons: list[str],
) -> float | None:
    numeric = _finite(value)
    if numeric is None:
        hard_reasons.append(f"ORDINARY_ROUTER_{name.upper()}_MISSING_OR_NONFINITE")
        return None
    if not 0.0 <= numeric <= 1.0:
        hard_reasons.append(f"ORDINARY_ROUTER_{name.upper()}_OUTSIDE_UNIT_INTERVAL")
        return None
    return numeric


def _router_magnitudes(
    router_result: Mapping[str, Any],
    ordinary_evidence: Mapping[str, Any],
    hard_reasons: list[str],
) -> dict[str, float]:
    explanation = _mapping(router_result.get("explanation"))

    base_weight = _bounded_unit_factor(
        name="base_weight",
        value=ordinary_evidence.get("ordinary_paper_effective_sizing_weight"),
        hard_reasons=hard_reasons,
    )
    # Admission-owned magnitudes never fall back to mutable router telemetry.
    # The router output has already been independently replayed from its exact
    # bound inputs; cross-checking it below detects a disagreement but cannot
    # replace the authenticated source value.
    data_quality_score = _finite(ordinary_evidence.get("orchestrator_market_state_integrity_score"))
    if data_quality_score is None:
        hard_reasons.append("ORDINARY_ROUTER_DATA_QUALITY_SCORE_MISSING_OR_NONFINITE")
        data_quality_fraction = None
    elif not 0.0 <= data_quality_score <= 100.0:
        hard_reasons.append("ORDINARY_ROUTER_DATA_QUALITY_SCORE_OUTSIDE_PERCENT")
        data_quality_fraction = None
    else:
        # Unit conversion only; 100 is the definition of percent, not a gate.
        data_quality_fraction = data_quality_score / 100.0

    masa_confidence = _bounded_unit_factor(
        name="masa_confidence",
        value=explanation.get("masa_confidence"),
        hard_reasons=hard_reasons,
    )
    ppo_confidence = _bounded_unit_factor(
        name="ppo_confidence",
        value=explanation.get("ppo_confidence"),
        hard_reasons=hard_reasons,
    )
    execution_success_probability = _bounded_unit_factor(
        name="execution_success_probability",
        value=explanation.get("execution_success_probability"),
        hard_reasons=hard_reasons,
    )

    drawdown_bps = _finite(explanation.get("current_drawdown_bps"))
    if drawdown_bps is None:
        hard_reasons.append("ORDINARY_ROUTER_DRAWDOWN_BPS_MISSING_OR_NONFINITE")
        drawdown_headroom = None
    else:
        # Basis points are converted to their unit fraction.  A drawdown cannot
        # exceed the whole reference equity under this bounded evidence schema.
        drawdown_fraction = drawdown_bps / 10_000.0
        if not 0.0 <= drawdown_fraction <= 1.0:
            hard_reasons.append("ORDINARY_ROUTER_DRAWDOWN_FRACTION_OUTSIDE_UNIT_INTERVAL")
            drawdown_headroom = None
        else:
            drawdown_headroom = 1.0 - drawdown_fraction

    volatility_fraction = _bounded_unit_factor(
        name="volatility_fraction",
        value=explanation.get("volatility"),
        hard_reasons=hard_reasons,
    )
    volatility_headroom = None if volatility_fraction is None else 1.0 - volatility_fraction
    liquidity_score = _bounded_unit_factor(
        name="liquidity_score",
        value=explanation.get("liquidity_score"),
        hard_reasons=hard_reasons,
    )
    microstructure_trust_score = _bounded_unit_factor(
        name="microstructure_trust_score",
        value=ordinary_evidence.get("orchestrator_microstructure_trust_score"),
        hard_reasons=hard_reasons,
    )
    sweep_risk_score = _bounded_unit_factor(
        name="sweep_risk_score",
        value=ordinary_evidence.get("orchestrator_sweep_risk_score"),
        hard_reasons=hard_reasons,
    )
    sweep_safety = None if sweep_risk_score is None else 1.0 - sweep_risk_score

    directions: list[str] = []
    for timeframe_name in ("higher_timeframe", "mid_timeframe", "lower_timeframe"):
        normalized = _direction(_mapping(explanation.get(timeframe_name)).get("direction"))
        if normalized is not None:
            directions.append(normalized)
    structural_direction = _direction(ordinary_evidence.get("selected_action"))
    if not directions:
        hard_reasons.append("ORDINARY_ROUTER_TIMEFRAME_DIRECTIONS_MISSING")
        timeframe_alignment = None
    elif structural_direction is None:
        hard_reasons.append("ORDINARY_ROUTER_STRUCTURAL_DIRECTION_MISSING")
        timeframe_alignment = None
    else:
        timeframe_alignment = sum(
            direction == structural_direction for direction in directions
        ) / len(directions)

    values = {
        "base_weight": base_weight,
        "data_quality_fraction": data_quality_fraction,
        "masa_confidence": masa_confidence,
        "ppo_confidence": ppo_confidence,
        "execution_success_probability": execution_success_probability,
        "drawdown_headroom": drawdown_headroom,
        "volatility_headroom": volatility_headroom,
        "liquidity_score": liquidity_score,
        "microstructure_trust_score": microstructure_trust_score,
        "sweep_safety": sweep_safety,
        "timeframe_direction_alignment": timeframe_alignment,
    }
    return {name: value for name, value in values.items() if value is not None}


def _router_input_rejection_reasons(
    *,
    router_result: Mapping[str, Any],
    router_input_material: Mapping[str, Any] | Any,
    ordinary_evidence: Mapping[str, Any],
    proposed_action: Any,
    current_position_state: Any,
) -> tuple[list[str], dict[str, Any], dict[str, Any] | None]:
    """Replay the router from exact inputs and bind source/PIT identities."""

    reasons: list[str] = []
    if not isinstance(router_input_material, Mapping):
        return ["ORDINARY_ROUTER_INPUT_MATERIAL_MISSING"], {}, None
    material = copy.deepcopy(dict(router_input_material))
    if set(material) != set(_ROUTER_INPUT_FIELDS):
        reasons.append("ORDINARY_ROUTER_INPUT_MATERIAL_FIELDS_INVALID")
    envelope = material.get("market_state_envelope")
    predictions = material.get("masa_predictions")
    if not isinstance(envelope, Mapping):
        reasons.append("ORDINARY_ROUTER_INPUT_MARKET_STATE_ENVELOPE_INVALID")
        envelope = {}
    if not isinstance(predictions, Sequence) or isinstance(predictions, str | bytes):
        reasons.append("ORDINARY_ROUTER_INPUT_MASA_PREDICTIONS_INVALID")
        predictions = []
    elif any(not isinstance(row, Mapping) for row in predictions):
        reasons.append("ORDINARY_ROUTER_INPUT_MASA_PREDICTION_ROW_INVALID")

    action = _direction(proposed_action)
    if _direction(material.get("ppo_proposed_action")) != action:
        reasons.append("ORDINARY_ROUTER_INPUT_PROPOSED_ACTION_MISMATCH")
    authoritative_state = str(current_position_state or "").strip().upper()
    if str(material.get("current_position_state") or "").strip().upper() != (authoritative_state):
        reasons.append("ORDINARY_ROUTER_INPUT_POSITION_STATE_MISMATCH")

    for field in _ADMISSION_SOURCE_IDENTITY_FIELDS:
        expected = ordinary_evidence.get(field)
        if expected in (None, ""):
            continue
        observed = envelope.get(field)
        if str(observed or "") != str(expected):
            reasons.append(f"ORDINARY_ROUTER_INPUT_SOURCE_IDENTITY_MISMATCH:{field}")

    admission_decision_time = _strict_utc(ordinary_evidence.get("decision_time"))
    for field in _ADMISSION_PIT_FIELDS:
        raw = ordinary_evidence.get(field)
        if raw in (None, ""):
            continue
        if str(envelope.get(field) or "") != str(raw):
            reasons.append(f"ORDINARY_ROUTER_INPUT_PIT_IDENTITY_MISMATCH:{field}")
        parsed = _strict_utc(raw)
        if parsed is None:
            reasons.append(f"ORDINARY_ROUTER_ADMISSION_PIT_CLOCK_INVALID:{field}")
        elif admission_decision_time is not None and parsed > admission_decision_time:
            reasons.append(f"ORDINARY_ROUTER_ADMISSION_PIT_CLOCK_FUTURE:{field}")
    for row in predictions:
        if not isinstance(row, Mapping):
            continue
        for field in ("feature_cutoff", "available_at", "candle_close_time"):
            raw = row.get(field)
            if raw in (None, ""):
                continue
            parsed = _strict_utc(raw)
            if parsed is None:
                reasons.append(f"ORDINARY_ROUTER_MASA_PIT_CLOCK_INVALID:{field}")
            elif admission_decision_time is not None and parsed > admission_decision_time:
                reasons.append(f"ORDINARY_ROUTER_MASA_PIT_CLOCK_FUTURE:{field}")

    replayed: dict[str, Any] | None = None
    if not reasons:
        try:
            replayed = route_strategy(
                market_state_envelope=envelope,
                masa_predictions=predictions,
                ppo_proposed_action=str(material.get("ppo_proposed_action") or ""),
                current_position_state=str(material.get("current_position_state") or ""),
                recent_execution_success_metrics=_mapping(
                    material.get("recent_execution_success_metrics")
                ),
                volatility_liquidity_state=_mapping(material.get("volatility_liquidity_state")),
                data_quality_score=_finite(material.get("data_quality_score")),
                current_drawdown_risk_state=_mapping(material.get("current_drawdown_risk_state")),
            )
        except Exception:
            reasons.append("ORDINARY_ROUTER_EXACT_INPUT_REPLAY_FAILED")
    if replayed is not None and dict(router_result) != replayed:
        reasons.append("ORDINARY_ROUTER_RESULT_MISMATCH_EXACT_INPUT_REPLAY")

    data_quality = _finite(ordinary_evidence.get("orchestrator_market_state_integrity_score"))
    replayed_quality = _finite(
        _mapping(replayed).get("explanation", {}).get("data_quality_score")
        if isinstance(_mapping(replayed).get("explanation"), Mapping)
        else None
    )
    if (
        replayed is not None
        and data_quality is not None
        and replayed_quality is not None
        and not math.isclose(data_quality, replayed_quality, rel_tol=1e-12, abs_tol=1e-15)
    ):
        reasons.append("ORDINARY_ROUTER_DATA_QUALITY_ADMISSION_BINDING_MISMATCH")
    replayed_explanation = _mapping(_mapping(replayed).get("explanation"))
    if replayed is not None and not math.isclose(
        _finite(replayed_explanation.get("ppo_confidence")) or -1.0,
        _finite(ordinary_evidence.get("confidence_calibrated")) or -2.0,
        rel_tol=1e-12,
        abs_tol=1e-15,
    ):
        reasons.append("ORDINARY_ROUTER_PPO_CONFIDENCE_ADMISSION_BINDING_MISMATCH")
    replayed_regime = _mapping(_mapping(replayed).get("regime_features"))
    for field, evidence_field in (
        ("microstructure_trust_score", "orchestrator_microstructure_trust_score"),
        ("sweep_risk", "orchestrator_sweep_risk_score"),
    ):
        replayed_value = _finite(replayed_regime.get(field))
        evidence_value = _finite(ordinary_evidence.get(evidence_field))
        if replayed is not None and (
            replayed_value is None
            or evidence_value is None
            or not math.isclose(
                replayed_value,
                evidence_value,
                rel_tol=1e-12,
                abs_tol=1e-15,
            )
        ):
            reasons.append(f"ORDINARY_ROUTER_{field.upper()}_ADMISSION_BINDING_MISMATCH")
    return sorted(set(reasons)), material, replayed


def _continuous_weight(factors: Mapping[str, float]) -> float:
    base_weight = factors["base_weight"]
    quality_factors = [value for name, value in factors.items() if name != "base_weight"]
    if any(value == 0.0 for value in quality_factors):
        return 0.0
    geometric_mean = math.exp(
        math.fsum(math.log(value) for value in quality_factors) / len(quality_factors)
    )
    return base_weight * geometric_mean


def interpret_ordinary_paper_router_result(
    *,
    router_result: Mapping[str, Any],
    router_input_material: Mapping[str, Any],
    ordinary_admission: OrdinaryPaperAdmissionResult,
    proposed_action: Any,
    current_position_state: Any,
) -> dict[str, Any]:
    """Interpret a router result only from factory-authenticated admission.

    The router output is independently replayed from the exact input material.
    Admission-owned source identities, PIT clocks, weights, and market/micro
    magnitudes come only from the immutable admission result.
    """

    router = dict(router_result) if isinstance(router_result, Mapping) else {}
    action = _direction(proposed_action)
    admission_reasons = ordinary_paper_admission_result_rejection_reasons(
        ordinary_admission,
        require_accepted=True,
    )
    if (
        type(ordinary_admission) is OrdinaryPaperAdmissionResult
        and ordinary_admission.claimed is False
    ):
        return _passthrough_result(
            router_result=router,
            action=action,
            reason="NOT_AN_INDEPENDENTLY_ACCEPTED_ORDINARY_PAPER_CANDIDATE",
        )

    evidence = (
        ordinary_admission.evidence
        if not admission_reasons and type(ordinary_admission) is OrdinaryPaperAdmissionResult
        else None
    )
    evidence = evidence if isinstance(evidence, dict) else {}
    hard_reasons: list[str] = list(admission_reasons)
    softened_reasons: list[str] = []
    telemetry_reasons: list[str] = []

    input_reasons, exact_input, replayed_router = _router_input_rejection_reasons(
        router_result=router,
        router_input_material=router_input_material,
        ordinary_evidence=evidence,
        proposed_action=proposed_action,
        current_position_state=current_position_state,
    )
    hard_reasons.extend(input_reasons)
    verified_router = replayed_router if replayed_router is not None else router

    if not evidence:
        hard_reasons.append("ORDINARY_ROUTER_ADMISSION_EVIDENCE_MISSING")
    if action is None:
        hard_reasons.append("ORDINARY_ROUTER_ACTION_NOT_DIRECTIONAL")
    evidence_direction = _direction(evidence.get("selected_action"))
    edge = _finite(evidence.get("expected_move_after_cost_bps"))
    if evidence_direction is None or edge is None or edge == 0.0:
        hard_reasons.append("ORDINARY_ROUTER_STRUCTURAL_DIRECTION_PROOF_MISSING")
    elif action != evidence_direction or (
        (evidence_direction == "long" and edge < 0.0)
        or (evidence_direction == "short" and edge > 0.0)
    ):
        hard_reasons.append("ORDINARY_ROUTER_STRUCTURAL_DIRECTION_PROOF_MISMATCH")
    if evidence.get("orchestrator_sweep_direction_uncertain") is not False:
        hard_reasons.append("ORDINARY_ROUTER_SWEEP_DIRECTION_CERTAINTY_NOT_PROVEN")

    position_state = str(current_position_state or "").strip().upper()
    if position_state != "FLAT":
        # An ordinary candidate represents a new directional PAPER entry.  It
        # must never reinterpret LONG->LONG, SHORT->SHORT, or a flip as valid.
        hard_reasons.append("ORDINARY_ROUTER_POSITION_NOT_FLAT_FOR_NEW_ENTRY")

    microstructure_action = str(
        _first_present(
            evidence.get("ordinary_paper_effective_microstructure_action"),
            evidence.get("orchestrator_microstructure_action"),
        )
        or ""
    ).upper()
    if microstructure_action not in {"ALLOW", "REDUCE_SIZE"}:
        hard_reasons.append("ORDINARY_ROUTER_MICROSTRUCTURE_ACTION_NOT_ROUTEABLE")

    router_block_reason = str(verified_router.get("block_reason") or "")
    all_router_reasons = _reason_list(verified_router.get("reason_codes"))
    if router_block_reason and router_block_reason not in all_router_reasons:
        all_router_reasons.append(router_block_reason)
    for reason in all_router_reasons:
        if reason in _SOFT_MAGNITUDE_REASONS:
            softened_reasons.append(reason)
        elif reason in _HARD_ROUTER_REASONS or reason.startswith(_HARD_REASON_PREFIXES):
            hard_reasons.append(reason)
        elif reason in _BENIGN_TELEMETRY_REASONS:
            telemetry_reasons.append(reason)
        else:
            hard_reasons.append(f"UNCLASSIFIED_ROUTER_REASON:{reason}")

    if (
        router_block_reason
        and router_block_reason not in _SOFT_MAGNITUDE_REASONS
        and router_block_reason not in _HARD_ROUTER_REASONS
        and not router_block_reason.startswith(_HARD_REASON_PREFIXES)
    ):
        hard_reasons.append(f"UNCLASSIFIED_ROUTER_BLOCK:{router_block_reason}")

    bucket_state = _mapping(verified_router.get("bucket_performance_state"))
    if (
        verified_router.get("bucket_quarantined") is True
        or bucket_state.get("negative_bucket") is True
    ):
        hard_reasons.append("NEGATIVE_BUCKET_PERFORMANCE_QUARANTINE")
    if _reason_list(verified_router.get("paper_loss_quarantine_matched_bucket_keys")):
        hard_reasons.append("PAPER_LOSS_BUCKET_QUARANTINE")

    factors = _router_magnitudes(verified_router, evidence, hard_reasons)
    required_factor_names = {
        "base_weight",
        "data_quality_fraction",
        "masa_confidence",
        "ppo_confidence",
        "execution_success_probability",
        "drawdown_headroom",
        "volatility_headroom",
        "liquidity_score",
        "microstructure_trust_score",
        "sweep_safety",
        "timeframe_direction_alignment",
    }
    continuous_weight = (
        _continuous_weight(factors)
        if not hard_reasons and set(factors) == required_factor_names
        else 0.0
    )
    if continuous_weight == 0.0 and not hard_reasons:
        hard_reasons.append("ORDINARY_ROUTER_CONTINUOUS_WEIGHT_ZERO")

    hard_reasons = sorted(set(hard_reasons))
    softened_reasons = sorted(set(softened_reasons))
    telemetry_reasons = sorted(set(telemetry_reasons))
    allowed = not hard_reasons and continuous_weight > 0.0
    effective_mode = MODE_REDUCE_SIZE if allowed else MODE_NO_TRADE
    original_allowed = _original_trade_allowed(router, action)
    original_mode = str(router.get("selected_mode") or MODE_NO_TRADE)
    router_result_sha256 = _canonical_hash(router)
    router_input_material_sha256 = _canonical_hash(exact_input)
    source_identity = {
        field: copy.deepcopy(evidence.get(field)) for field in _ADMISSION_SOURCE_IDENTITY_FIELDS
    }
    point_in_time_clocks = {
        field: copy.deepcopy(evidence.get(field)) for field in _ADMISSION_PIT_FIELDS
    }
    source_identity_sha256 = _canonical_hash(source_identity)
    point_in_time_clocks_sha256 = _canonical_hash(point_in_time_clocks)
    binding_material = {
        "admission_evidence_sha256": (
            ordinary_admission.evidence_sha256
            if type(ordinary_admission) is OrdinaryPaperAdmissionResult
            else None
        ),
        "router_result_sha256": router_result_sha256,
        "router_input_material_sha256": router_input_material_sha256,
        "source_identity_sha256": source_identity_sha256,
        "point_in_time_clocks_sha256": point_in_time_clocks_sha256,
        "proposed_action": str(proposed_action or "").strip().lower(),
        "current_position_state": str(current_position_state or "").strip().upper(),
    }
    binding_sha256 = _canonical_hash(binding_material)
    if any(
        value is None
        for value in (
            router_result_sha256,
            router_input_material_sha256,
            source_identity_sha256,
            point_in_time_clocks_sha256,
            binding_sha256,
        )
    ):
        hard_reasons = sorted(set(hard_reasons + ["ORDINARY_ROUTER_BINDING_HASH_INVALID"]))
        allowed = False
        continuous_weight = 0.0
        effective_mode = MODE_NO_TRADE

    return {
        "schema_version": ORDINARY_PAPER_ROUTER_INTERPRETATION_SCHEMA_VERSION,
        "ordinary_paper_interpretation_claimed": True,
        "ordinary_paper_interpretation_applied": True,
        "interpretation_status": (
            "CONTINUOUS_PAPER_SIZING_ACCEPTED" if allowed else "HARD_FAIL_CLOSED"
        ),
        "strategy_trade_allowed": allowed,
        "effective_mode": effective_mode,
        "effective_action": action if allowed else "hold",
        "continuous_weight": continuous_weight,
        "continuous_formula": ORDINARY_PAPER_ROUTER_CONTINUOUS_FORMULA,
        "continuous_factors": factors,
        "hard_reasons": hard_reasons,
        "softened_reasons": softened_reasons,
        "telemetry_reasons": telemetry_reasons,
        "original_router_trade_allowed": original_allowed,
        "original_router_selected_mode": original_mode,
        "original_router_block_reason": router.get("block_reason"),
        "original_router_reason_codes": _reason_list(router.get("reason_codes")),
        "original_router_telemetry": copy.deepcopy(router),
        "admission_evidence_sha256": binding_material["admission_evidence_sha256"],
        "router_result_sha256": router_result_sha256,
        "router_input_material_sha256": router_input_material_sha256,
        "admission_source_identity": source_identity,
        "admission_source_identity_sha256": source_identity_sha256,
        "admission_point_in_time_clocks": point_in_time_clocks,
        "admission_point_in_time_clocks_sha256": point_in_time_clocks_sha256,
        "authoritative_binding_sha256": binding_sha256,
        "paper_only": True,
        "routes_to_live": False,
        "live_trade_allowed": False,
        "places_real_order": False,
        "exchange_mutation": False,
    }


__all__ = (
    "ORDINARY_PAPER_ROUTER_CONTINUOUS_FORMULA",
    "ORDINARY_PAPER_ROUTER_INTERPRETATION_SCHEMA_VERSION",
    "interpret_ordinary_paper_router_result",
)
