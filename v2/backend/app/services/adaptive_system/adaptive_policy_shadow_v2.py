"""Build a paper-only adaptive shadow action for every production candidate.

The production Category-E decision is retained as a comparator.  Adaptive
estimates, objective scores and actions are derived exclusively from the
authenticated matured-outcome calibration and current point-in-time candidate
state.  The venue helper attests the exact selected action and never resizes it.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
from typing import Any, Mapping

from v2.backend.app.domain.adaptive_component_estimates_v1 import (
    AUTHORITY_MODE as COMPONENT_AUTHORITY_MODE,
    AVAILABLE,
    CALIBRATED_PROBABILITY,
    COMPONENT_NAMES,
    EMPIRICAL_DISTRIBUTION,
    EMPIRICAL_ESTIMATE,
    EMPIRICAL_RATE,
    FACT,
    LIVE_GATE,
    POINT_ESTIMATE,
    AdaptiveComponentEstimatesV1,
    CalibrationEvidenceV1,
    ComponentEstimateGroupV1,
    DistributionEstimateV1,
    QuantileV1,
    ScalarEstimateV1,
    unavailable_component_group,
)
from v2.backend.app.domain.adaptive_policy_action_v2 import (
    ACTION_CLOSE_EXISTING_EXPOSURE,
    ACTION_DIRECTIONAL_TRADE,
    ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
    ACTION_REDUCE_EXISTING_EXPOSURE,
    ACTION_REMAIN_FLAT,
    LIVE_GATE_BLOCKED_HUMAN_ONLY,
    POLICY_MODE_BOUNDED_EXPLORATION,
    POLICY_MODE_CHAMPION_EXPLOITATION,
    UNIT_CONTRACT_USD_BPS_SECONDS_PROBABILITY,
    ActionProbabilityV2,
    AdaptivePolicyActionV2,
    EntryPolicyV2,
    ExitPolicyV2,
    ExpectedCostBreakdownV2,
    HorizonReturnDistributionV2,
    ReturnQuantileV2,
)
from v2.backend.app.services.adaptive_system.adaptive_hard_validator_v2 import (
    sign_hard_constraint_validation_receipt,
)
from v2.backend.app.services.adaptive_system.adaptive_objective_reference_v2 import (
    evaluate_reference_objective,
)
from v2.backend.app.services.adaptive_system.adaptive_objective_v2 import (
    ACTION_INPUT_SCHEMA_VERSION,
    BOUNDED_EXPLORATION,
    CHAMPION_EXPLOITATION,
    FIT_EVIDENCE_SCHEMA_VERSION,
    MODE_ALLOCATION_SCHEMA_VERSION,
    UNIT_CONTRACT,
    WEIGHTS_SCHEMA_VERSION,
    ActionObjectiveInputsV2,
    AdaptivePolicyModeAllocationV2,
    FittedObjectiveEvidenceV2,
    LearnedObjectiveWeightsV2,
    evaluate_shadow_objective,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_calibration_v2 import (
    validate_candidate_outcome_calibration_v2,
)
from v2.backend.app.services.adaptive_system.selected_action_venue_feasibility_v2 import (
    DECISION_EXECUTABLE,
    SelectedActionVenueFeasibilityRequestV2,
    SelectedActionVenueFeasibilityV2,
    attest_selected_action_venue_feasibility,
)

SCHEMA_VERSION = "adaptive_policy_shadow_candidate_v2"
POLICY_ID = "candidate_outcome_adaptive_policy_v2"
POLICY_GENERATION = 1
PRODUCER_ID = "candidate_outcome_adaptive_shadow_v2"
SOURCE_SCHEMA = "candidate_outcome_calibration_v2"
MODEL_ID = "candidate_outcome_calibrator_v2"
_HORIZONS = {"5m": 300, "15m": 900, "1h": 3_600, "4h": 14_400}
_SHA_FIELDS = (
    "paper_exchange_filter_snapshot_hash",
    "paper_cycle_reservation_snapshot_hash",
    "paper_cycle_base_resource_evidence_hash",
    "paper_dynamic_envelope_reservation_evidence_hash",
)


class AdaptivePolicyShadowError(ValueError):
    pass


def _json_value(value: object) -> object:
    if dataclasses.is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    return value


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AdaptivePolicyShadowError(f"{field}:object_required")
    return dict(value)


def _identifier(value: object, field: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise AdaptivePolicyShadowError(f"{field}:identifier_required")
    return value


def _sha(value: object, field: str) -> str:
    text = _identifier(value, field)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise AdaptivePolicyShadowError(f"{field}:sha256_required")
    return text


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _finite(value: object, field: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise AdaptivePolicyShadowError(f"{field}:finite_number_required")
    return float(value)


def _positive_decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise AdaptivePolicyShadowError(f"{field}:decimal_required") from exc
    if not result.is_finite() or result <= 0:
        raise AdaptivePolicyShadowError(f"{field}:positive_decimal_required")
    return result


def _iso_ms(value: object, field: str) -> int:
    text = _identifier(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdaptivePolicyShadowError(f"{field}:iso_timestamp_required") from exc
    if parsed.tzinfo is None:
        raise AdaptivePolicyShadowError(f"{field}:timezone_required")
    return int(parsed.timestamp() * 1_000)


def _candidate_id(intent: Mapping[str, Any], registry: Mapping[str, Any]) -> str:
    policy_id = _identifier(intent.get("policy_id") or intent.get("candidate_id"), "policy_id")
    material = {
        "prediction_id": _identifier(intent.get("prediction_id"), "prediction_id"),
        "preemptive_decision_id": _identifier(
            intent.get("preemptive_decision_id"), "preemptive_decision_id"
        ),
        "policy_id": policy_id,
        "policy_sha256": _sha(intent.get("policy_fingerprint"), "policy_fingerprint"),
        "checkpoint_generation": registry.get("registry_generation"),
        "checkpoint_id": registry.get("checkpoint_id"),
    }
    return f"cdo2_{_canonical_sha256(material)}"


def _feature_abi_sha256(
    intent: Mapping[str, Any], registry: Mapping[str, Any]
) -> str:
    bundle = _mapping(registry.get("checkpoint_bundle"), "registry.checkpoint_bundle")
    active = _sha(bundle.get("feature_abi_sha256"), "registry.feature_abi_sha256")
    declared = intent.get("feature_abi_sha256")
    if declared not in {None, ""} and _sha(declared, "intent.feature_abi_sha256") != active:
        raise AdaptivePolicyShadowError("intent.feature_abi_sha256:active_registry_mismatch")
    return active


def _feature_builder_sha256(
    intent: Mapping[str, Any], registry: Mapping[str, Any]
) -> str:
    bundle = _mapping(registry.get("checkpoint_bundle"), "registry.checkpoint_bundle")
    active = _sha(
        bundle.get("serving_feature_builder_sha"),
        "registry.serving_feature_builder_sha",
    )
    declared = intent.get("feature_builder_sha256")
    if declared not in {None, ""} and _sha(
        declared, "intent.feature_builder_sha256"
    ) != active:
        raise AdaptivePolicyShadowError(
            "intent.feature_builder_sha256:active_registry_mismatch"
        )
    return active


def _weights(calibration: Mapping[str, Any]) -> LearnedObjectiveWeightsV2:
    raw = _mapping(calibration.get("learned_objective_weights"), "learned_objective_weights")
    evidence = FittedObjectiveEvidenceV2(
        schema_version=FIT_EVIDENCE_SCHEMA_VERSION,
        optimizer_id="candidate_outcome_walk_forward_objective_v2",
        optimizer_family="chronological_prefix_multiobjective",
        objective_parameter_fingerprint=_sha(
            raw.get("objective_parameter_fingerprint"),
            "objective_parameter_fingerprint",
        ),
        fit_receipt_sha256=_sha(calibration.get("fit_receipt_sha256"), "fit_receipt_sha256"),
        training_row_digest=_sha(calibration.get("fit_row_digest"), "fit_row_digest"),
        training_population_sha256=_sha(
            calibration.get("training_population_sha256"), "training_population_sha256"
        ),
        fit_window_start_ms=int(calibration["fit_window_start_ms"]),
        fit_window_end_ms=int(calibration["fit_window_end_ms"]),
        fit_record_available_at_ms=int(calibration["fit_record_available_at_ms"]),
        sample_count=int(calibration["fit_sample_count"]),
        checkpoint_generation=int(calibration["checkpoint_generation"]),
        checkpoint_id=_identifier(calibration.get("checkpoint_id"), "checkpoint_id"),
        checkpoint_sha256=_sha(calibration.get("checkpoint_sha256"), "checkpoint_sha256"),
        fitted=True,
        holdout_used_for_fitting=False,
        paper_only=True,
    )
    return LearnedObjectiveWeightsV2(
        schema_version=WEIGHTS_SCHEMA_VERSION,
        expected_after_cost_return=float(raw["expected_after_cost_return"]),
        drawdown_penalty=float(raw["drawdown_penalty"]),
        tail_loss_penalty=float(raw["tail_loss_penalty"]),
        liquidation_risk_penalty=float(raw["liquidation_risk_penalty"]),
        market_impact_penalty=float(raw["market_impact_penalty"]),
        funding_cost_penalty=float(raw["funding_cost_penalty"]),
        turnover_penalty=float(raw["turnover_penalty"]),
        concentration_penalty=float(raw["concentration_penalty"]),
        information_gain_reward=float(raw["information_gain_reward"]),
        unit_contract=UNIT_CONTRACT,
        evidence=evidence,
    )


def _allocation(
    calibration: Mapping[str, Any], *, state_id: str, state_sha256: str
) -> AdaptivePolicyModeAllocationV2:
    raw = _mapping(calibration.get("mode_allocation"), "mode_allocation")
    values = {
        "schema_version": MODE_ALLOCATION_SCHEMA_VERSION,
        "champion_exploitation_probability": float(
            raw["champion_exploitation_probability"]
        ),
        "bounded_exploration_probability": float(raw["bounded_exploration_probability"]),
        "fit_receipt_sha256": _sha(
            calibration.get("fit_receipt_sha256"), "fit_receipt_sha256"
        ),
        "optimizer_id": "candidate_outcome_adaptive_mode_allocator_v2",
        "state_id": state_id,
        "state_sha256": state_sha256,
        "checkpoint_generation": int(calibration["checkpoint_generation"]),
        "checkpoint_id": _identifier(calibration.get("checkpoint_id"), "checkpoint_id"),
        "checkpoint_sha256": _sha(
            calibration.get("checkpoint_sha256"), "checkpoint_sha256"
        ),
        "fit_window_start_ms": int(calibration["fit_window_start_ms"]),
        "fit_window_end_ms": int(calibration["fit_window_end_ms"]),
        "fit_record_available_at_ms": int(calibration["fit_record_available_at_ms"]),
        "fit_sample_count": int(calibration["fit_sample_count"]),
        "fit_row_digest": _sha(calibration.get("fit_row_digest"), "fit_row_digest"),
        "fit_population_sha256": _sha(
            calibration.get("training_population_sha256"), "training_population_sha256"
        ),
        "holdout_used_for_fitting": False,
        "paper_only": True,
        "fitted": True,
        "permanent_percentage": False,
    }
    return AdaptivePolicyModeAllocationV2(
        **values,
        allocation_parameter_fingerprint=_canonical_sha256(values),
    )


def _calibration_evidence(
    calibration: Mapping[str, Any], component: str, metric: str, sample_count: int
) -> CalibrationEvidenceV1:
    return CalibrationEvidenceV1(
        component_name=component,
        metric_name=metric,
        calibration_receipt_sha256=_sha(
            calibration.get("calibration_sha256"), "calibration_sha256"
        ),
        fitted=True,
        probability_semantics_valid=True,
        model_id=MODEL_ID,
        model_parameter_fingerprint=_sha(
            _mapping(
                calibration.get("learned_objective_weights"),
                "learned_objective_weights",
            ).get("objective_parameter_fingerprint"),
            "objective_parameter_fingerprint",
        ),
        row_digest=_sha(calibration.get("fit_row_digest"), "fit_row_digest"),
        calibration_population_sha256=_sha(
            calibration.get("training_population_sha256"), "training_population_sha256"
        ),
        calibration_window_start_ms=int(calibration["fit_window_start_ms"]),
        calibration_window_end_ms=int(calibration["fit_window_end_ms"]),
        sample_count=sample_count,
        checkpoint_generation=int(calibration["checkpoint_generation"]),
        checkpoint_id=_identifier(calibration.get("checkpoint_id"), "checkpoint_id"),
        checkpoint_sha256=_sha(
            calibration.get("checkpoint_sha256"), "checkpoint_sha256"
        ),
    )


def _scalar(
    *,
    name: str,
    value: float | bool,
    unit: str,
    semantic_kind: str,
    component: str,
    source_field: str,
    source_receipt: str,
    horizon_seconds: int | None,
    sample_count: int | None,
    calibration: Mapping[str, Any] | None = None,
) -> ScalarEstimateV1:
    calibrated = semantic_kind == CALIBRATED_PROBABILITY
    return ScalarEstimateV1(
        name=name,
        availability=AVAILABLE,
        semantic_kind=semantic_kind,
        value=value,
        unit=unit,
        horizon_seconds=horizon_seconds,
        sample_count=sample_count,
        producer_id=PRODUCER_ID,
        source_field=source_field,
        source_schema=SOURCE_SCHEMA,
        model_id=None if semantic_kind == FACT else MODEL_ID,
        calibration_evidence=(
            _calibration_evidence(calibration, component, name, int(sample_count))
            if calibrated and calibration is not None and sample_count is not None
            else None
        ),
        source_receipt_sha256s=(source_receipt,),
        unavailable_reason=None,
    )


def _distribution(
    *,
    name: str,
    values: Mapping[str, Any],
    horizon_seconds: int,
    sample_count: int,
    source_field: str,
    source_receipt: str,
) -> DistributionEstimateV1:
    return DistributionEstimateV1(
        name=name,
        availability=AVAILABLE,
        semantic_kind=EMPIRICAL_DISTRIBUTION,
        unit="milliseconds" if name == "fill_delay_ms_distribution" else "bps",
        horizon_seconds=horizon_seconds,
        quantiles=tuple(
            QuantileV1(float(probability), float(values[probability]))
            for probability in ("0.1", "0.5", "0.9")
        ),
        sample_count=sample_count,
        producer_id=PRODUCER_ID,
        source_field=source_field,
        source_schema=SOURCE_SCHEMA,
        model_id=MODEL_ID,
        calibration_evidence=None,
        source_receipt_sha256s=(source_receipt,),
        unavailable_reason=None,
    )


def _replace_group(
    group: ComponentEstimateGroupV1,
    *,
    scalars: tuple[ScalarEstimateV1, ...] = (),
    distributions: tuple[DistributionEstimateV1, ...] = (),
) -> ComponentEstimateGroupV1:
    scalar_map = {item.name: item for item in group.scalar_estimates}
    scalar_map.update({item.name: item for item in scalars})
    distribution_map = {item.name: item for item in group.distribution_estimates}
    distribution_map.update({item.name: item for item in distributions})
    return replace(
        group,
        scalar_estimates=tuple(scalar_map[name] for name in sorted(scalar_map)),
        distribution_estimates=tuple(
            distribution_map[name] for name in sorted(distribution_map)
        ),
    )


def _statistics(
    calibration: Mapping[str, Any], side: str, timeframe: str
) -> dict[str, Any]:
    groups = _mapping(calibration.get("side_timeframe_statistics"), "statistics")
    value = groups.get(f"{side}:{timeframe}")
    if not isinstance(value, Mapping):
        value = _mapping(calibration.get("global_statistics"), "global_statistics")
    return dict(value)


def _physical_plan(
    *, intent: Mapping[str, Any], statistics: Mapping[str, Any], side: str, mode: str
) -> dict[str, Any]:
    filters = _mapping(intent.get("paper_exchange_filter_snapshot"), "exchange_filter")
    reservation = _mapping(intent.get("paper_cycle_reservation_snapshot"), "reservation")
    derived = _mapping(reservation.get("derived"), "reservation.derived")
    economic = _mapping(intent.get("paper_allocator_economic_contract"), "economic_contract")
    model_inputs = _mapping(
        _mapping(economic.get("material"), "economic_contract.material").get("model_inputs"),
        "economic_contract.model_inputs",
    )
    envelope = _mapping(model_inputs.get("risk_envelope"), "risk_envelope")
    entry = _positive_decimal(intent.get("entry_price"), "entry_price")
    tick = _positive_decimal(filters.get("tick_size"), "tick_size")
    step = _positive_decimal(filters.get("step_size"), "step_size")
    minimum_quantity = _positive_decimal(filters.get("min_qty"), "min_qty")
    maximum_quantity = _positive_decimal(filters.get("max_qty"), "max_qty")
    minimum_notional = _positive_decimal(filters.get("min_notional"), "min_notional")
    leverage = _positive_decimal(envelope.get("max_effective_leverage"), "max_leverage")
    maximum_notional = min(
        _positive_decimal(derived.get("remaining_total_notional_usd"), "remaining_total"),
        _positive_decimal(derived.get("remaining_symbol_notional_usd"), "remaining_symbol"),
    )
    maximum_margin = _positive_decimal(
        derived.get("remaining_margin_after_buffer_usd"), "remaining_margin"
    )
    maximum_loss = min(
        _positive_decimal(
            derived.get("remaining_projected_stress_loss_usd"), "remaining_stress_loss"
        ),
        _positive_decimal(
            derived.get("remaining_per_candidate_risk_budget_usd"),
            "remaining_candidate_risk",
        ),
    )
    tail = max(Decimal("1"), abs(Decimal(str(statistics["mae_bps_quantiles"]["0.1"]))))
    transaction_cost = max(
        Decimal("0"), Decimal(str(statistics["transaction_cost_bps_quantiles"]["0.5"]))
    )
    expected = Decimal(str(statistics["after_cost_expectancy_bps"]))
    information = Decimal(str(statistics["posterior_uncertainty"]))
    positive_signal = max(Decimal("0"), expected) + (
        information * Decimal("100") if mode == BOUNDED_EXPLORATION else Decimal("0")
    )
    scale = positive_signal / (positive_signal + tail) if positive_signal > 0 else Decimal("0")
    risk_limited = maximum_loss * Decimal("10000") / (tail + transaction_cost)
    continuous_target = min(maximum_notional, maximum_margin * leverage, risk_limited) * scale
    with localcontext() as context:
        context.prec = 120
        minimum_step_quantity = max(
            minimum_quantity,
            (minimum_notional / entry / step).to_integral_value(rounding=ROUND_CEILING)
            * step,
        )
        selected_quantity = (
            (continuous_target / entry / step).to_integral_value(rounding=ROUND_FLOOR)
            * step
        )
        selected_quantity = max(minimum_step_quantity, selected_quantity)
        if selected_quantity > maximum_quantity:
            selected_quantity = maximum_quantity
        notional = selected_quantity * entry
        margin = notional / leverage
        raw_stop = (
            entry * (Decimal("1") - tail / Decimal("10000"))
            if side == "LONG"
            else entry * (Decimal("1") + tail / Decimal("10000"))
        )
        stop = (
            (raw_stop / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
            if side == "LONG"
            else (raw_stop / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        )
        raw_target = (
            entry * (Decimal("1") + Decimal(str(statistics["mfe_bps_quantiles"]["0.5"])) / Decimal("10000"))
            if side == "LONG"
            else entry * (Decimal("1") - Decimal(str(statistics["mfe_bps_quantiles"]["0.5"])) / Decimal("10000"))
        )
        profit_target = (
            (raw_target / tick).to_integral_value(rounding=ROUND_CEILING) * tick
            if side == "LONG"
            else (raw_target / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        )
    return {
        "side": side,
        "entry_price": entry,
        "stop_price": stop,
        "profit_target_price": profit_target,
        "selected_quantity": selected_quantity,
        "selected_notional_usd": notional,
        "selected_margin_usd": margin,
        "selected_leverage": leverage,
        "round_trip_cost_bps": transaction_cost,
        "venue_price_tick": tick,
        "venue_min_notional_usd": minimum_notional,
        "venue_max_notional_usd": _positive_decimal(
            model_inputs.get("max_qty"), "max_qty"
        )
        * entry,
        "venue_min_qty": minimum_quantity,
        "venue_max_qty": maximum_quantity,
        "venue_qty_step": step,
        "catastrophic_max_notional_usd": maximum_notional,
        "catastrophic_max_loss_usd": maximum_loss,
        "catastrophic_max_margin_usd": maximum_margin,
        "catastrophic_max_leverage": leverage,
        "remaining_notional_headroom_usd": maximum_notional,
        "remaining_loss_headroom_usd": maximum_loss,
        "available_collateral_usd": _positive_decimal(
            _mapping(intent.get("paper_cycle_base_resource_evidence"), "base_resources").get(
                "available_margin_usd"
            ),
            "available_margin_usd",
        ),
        "reserved_margin_usd": Decimal(str(derived.get("prior_reserved_margin_usd", 0.0))),
        "continuous_target_notional_usd": continuous_target,
        "adaptive_scale": scale,
    }


def _venue_attestation(
    *,
    intent: Mapping[str, Any],
    candidate_id: str,
    proposal_sha256: str,
    plan: Mapping[str, Any],
) -> SelectedActionVenueFeasibilityV2:
    filter_sha = _sha(
        intent.get("paper_exchange_filter_snapshot_hash"), "exchange_filter_snapshot_hash"
    )
    base_sha = _sha(
        intent.get("paper_cycle_base_resource_evidence_hash"), "base_resource_hash"
    )
    reservation_sha = _sha(
        intent.get("paper_cycle_reservation_snapshot_hash"), "reservation_snapshot_hash"
    )
    return attest_selected_action_venue_feasibility(
        SelectedActionVenueFeasibilityRequestV2(
            candidate_id=candidate_id,
            policy_action_sha256=proposal_sha256,
            venue_rules_receipt_sha256=filter_sha,
            capital_snapshot_sha256=base_sha,
            catastrophic_envelope_receipt_sha256=reservation_sha,
            side=str(plan["side"]),
            selected_entry_price=plan["entry_price"],
            selected_stop_price=plan["stop_price"],
            selected_notional_usd=plan["selected_notional_usd"],
            selected_leverage=plan["selected_leverage"],
            selected_margin_usd=plan["selected_margin_usd"],
            selected_round_trip_cost_bps=plan["round_trip_cost_bps"],
            venue_price_tick=plan["venue_price_tick"],
            venue_min_notional_usd=plan["venue_min_notional_usd"],
            venue_max_notional_usd=plan["venue_max_notional_usd"],
            venue_min_qty=plan["venue_min_qty"],
            venue_max_qty=plan["venue_max_qty"],
            venue_qty_step=plan["venue_qty_step"],
            catastrophic_max_notional_usd=plan["catastrophic_max_notional_usd"],
            catastrophic_max_loss_usd=plan["catastrophic_max_loss_usd"],
            catastrophic_max_margin_usd=plan["catastrophic_max_margin_usd"],
            catastrophic_max_leverage=plan["catastrophic_max_leverage"],
            remaining_catastrophic_notional_headroom_usd=plan[
                "remaining_notional_headroom_usd"
            ],
            remaining_catastrophic_loss_headroom_usd=plan[
                "remaining_loss_headroom_usd"
            ],
            available_collateral_usd=plan["available_collateral_usd"],
            reserved_margin_usd=plan["reserved_margin_usd"],
        )
    )


def _component_bundle(
    *,
    intent: Mapping[str, Any],
    calibration: Mapping[str, Any],
    registry: Mapping[str, Any],
    candidate_id: str,
    side: str,
    statistics: Mapping[str, Any],
    proposal_sha256: str,
    plan: Mapping[str, Any],
    venue: SelectedActionVenueFeasibilityV2,
    state_id: str,
    state_sha256: str,
    source_receipts: tuple[str, ...],
    generated_at_ms: int,
) -> AdaptiveComponentEstimatesV1:
    horizon = _HORIZONS[_identifier(intent.get("timeframe"), "timeframe")]
    n = int(statistics["sample_count"])
    calibration_sha = _sha(calibration.get("calibration_sha256"), "calibration_sha256")
    groups = {
        name: unavailable_component_group(name, reason="not_present_in_matured_candidate_labels")
        for name in COMPONENT_NAMES
    }
    groups["confidence"] = _replace_group(
        groups["confidence"],
        scalars=(
            _scalar(
                name="calibrated_action_probability",
                value=float(statistics["win_rate_posterior_mean"]),
                unit="probability_0_1",
                semantic_kind=CALIBRATED_PROBABILITY,
                component="confidence",
                source_field="win_rate_posterior_mean",
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
                calibration=calibration,
            ),
            _scalar(
                name="policy_uncertainty",
                value=float(statistics["posterior_uncertainty"]),
                unit="probability_0_1",
                semantic_kind=POINT_ESTIMATE,
                component="confidence",
                source_field="posterior_uncertainty",
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
            ),
        ),
    )
    groups["execution_quality"] = _replace_group(
        groups["execution_quality"],
        scalars=(
            _scalar(
                name="expected_transaction_cost_bps",
                value=float(statistics["transaction_cost_bps_quantiles"]["0.5"]),
                unit="bps",
                semantic_kind=POINT_ESTIMATE,
                component="execution_quality",
                source_field="transaction_cost_bps_quantiles.0.5",
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
            ),
            _scalar(
                name="fill_probability",
                value=1.0 - float(statistics["venue_infeasible_probability"]),
                unit="probability_0_1",
                semantic_kind=CALIBRATED_PROBABILITY,
                component="execution_quality",
                source_field="venue_infeasible_probability",
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
                calibration=calibration,
            ),
            _scalar(
                name="minimum_executable_capital_usd",
                value=float(plan["venue_min_notional_usd"] / plan["selected_leverage"]),
                unit="USD",
                semantic_kind=FACT,
                component="execution_quality",
                source_field="venue_min_notional_usd_divided_by_selected_leverage",
                source_receipt=_sha(
                    intent.get("paper_exchange_filter_snapshot_hash"), "exchange_filter_hash"
                ),
                horizon_seconds=None,
                sample_count=None,
            ),
            _scalar(
                name="rounded_valid_quantity",
                value=float(plan["selected_quantity"]),
                unit="base_asset_quantity",
                semantic_kind=FACT,
                component="execution_quality",
                source_field="policy_selected_discrete_quantity",
                source_receipt=_canonical_sha256(asdict(venue)),
                horizon_seconds=None,
                sample_count=None,
            ),
            _scalar(
                name="venue_feasible",
                value=venue.decision == DECISION_EXECUTABLE,
                unit="boolean",
                semantic_kind=FACT,
                component="execution_quality",
                source_field="selected_action_venue_feasibility",
                source_receipt=_canonical_sha256(asdict(venue)),
                horizon_seconds=None,
                sample_count=None,
            ),
        ),
        distributions=(
            _distribution(
                name="transaction_cost_bps_distribution",
                values=_mapping(
                    statistics["transaction_cost_bps_quantiles"],
                    "transaction_cost_bps_quantiles",
                ),
                horizon_seconds=horizon,
                sample_count=n,
                source_field="transaction_cost_bps_quantiles",
                source_receipt=calibration_sha,
            ),
        ),
    )
    groups["exit_feasibility"] = _replace_group(
        groups["exit_feasibility"],
        scalars=tuple(
            _scalar(
                name=name,
                value=value,
                unit="probability_0_1",
                semantic_kind=(
                    POINT_ESTIMATE if name == "exit_uncertainty" else CALIBRATED_PROBABILITY
                ),
                component="exit_feasibility",
                source_field=source_field,
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
                calibration=(None if name == "exit_uncertainty" else calibration),
            )
            for name, value, source_field in (
                (
                    "exit_fill_probability",
                    1.0 - float(statistics["slippage_failure_probability"]),
                    "slippage_failure_probability",
                ),
                ("exit_uncertainty", float(statistics["posterior_uncertainty"]), "posterior_uncertainty"),
                (
                    "profit_exit_probability",
                    float(statistics["profit_exit_probability"]),
                    "profit_exit_probability",
                ),
                (
                    "stop_execution_probability",
                    1.0 - float(statistics["slippage_failure_probability"]),
                    "slippage_failure_probability",
                ),
            )
        ),
    )
    groups["loss_risk"] = _replace_group(
        groups["loss_risk"],
        scalars=(
            _scalar(
                name="drawdown_contribution_bps",
                value=abs(float(statistics["mae_bps_quantiles"]["0.5"])),
                unit="bps",
                semantic_kind=POINT_ESTIMATE,
                component="loss_risk",
                source_field="mae_bps_quantiles.0.5",
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
            ),
            _scalar(
                name="loss_probability",
                value=float(statistics["loss_probability"]),
                unit="probability_0_1",
                semantic_kind=CALIBRATED_PROBABILITY,
                component="loss_risk",
                source_field="loss_probability",
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
                calibration=calibration,
            ),
            _scalar(
                name="stop_out_probability",
                value=float(statistics["stop_out_probability"]),
                unit="probability_0_1",
                semantic_kind=CALIBRATED_PROBABILITY,
                component="loss_risk",
                source_field="stop_out_probability",
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
                calibration=calibration,
            ),
        ),
        distributions=(
            _distribution(
                name="return_bps_distribution",
                values=_mapping(statistics["return_bps_quantiles"], "return_quantiles"),
                horizon_seconds=horizon,
                sample_count=n,
                source_field="return_bps_quantiles",
                source_receipt=calibration_sha,
            ),
            _distribution(
                name="tail_loss_bps_distribution",
                values=_mapping(statistics["tail_loss_bps_quantiles"], "tail_quantiles"),
                horizon_seconds=horizon,
                sample_count=n,
                source_field="tail_loss_bps_quantiles",
                source_receipt=calibration_sha,
            ),
        ),
    )
    groups["mfe_mae"] = _replace_group(
        groups["mfe_mae"],
        distributions=(
            _distribution(
                name="mae_bps_distribution",
                values=_mapping(statistics["mae_bps_quantiles"], "mae_quantiles"),
                horizon_seconds=horizon,
                sample_count=n,
                source_field="mae_bps_quantiles",
                source_receipt=calibration_sha,
            ),
            _distribution(
                name="mfe_bps_distribution",
                values=_mapping(statistics["mfe_bps_quantiles"], "mfe_quantiles"),
                horizon_seconds=horizon,
                sample_count=n,
                source_field="mfe_bps_quantiles",
                source_receipt=calibration_sha,
            ),
        ),
    )
    groups["microstructure"] = _replace_group(
        groups["microstructure"],
        scalars=(
            _scalar(
                name="adverse_selection_probability",
                value=float(statistics["slippage_failure_probability"]),
                unit="probability_0_1",
                semantic_kind=CALIBRATED_PROBABILITY,
                component="microstructure",
                source_field="slippage_failure_probability",
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
                calibration=calibration,
            ),
            _scalar(
                name="execution_uncertainty",
                value=float(statistics["posterior_uncertainty"]),
                unit="probability_0_1",
                semantic_kind=POINT_ESTIMATE,
                component="microstructure",
                source_field="posterior_uncertainty",
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
            ),
            _scalar(
                name="fill_probability",
                value=1.0 - float(statistics["venue_infeasible_probability"]),
                unit="probability_0_1",
                semantic_kind=CALIBRATED_PROBABILITY,
                component="microstructure",
                source_field="venue_infeasible_probability",
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
                calibration=calibration,
            ),
            _scalar(
                name="short_horizon_reversal_probability",
                value=float(statistics["reversal_probability"]),
                unit="probability_0_1",
                semantic_kind=CALIBRATED_PROBABILITY,
                component="microstructure",
                source_field="reversal_probability",
                source_receipt=calibration_sha,
                horizon_seconds=horizon,
                sample_count=n,
                calibration=calibration,
            ),
        ),
        distributions=(
            _distribution(
                name="market_impact_bps_distribution",
                values=_mapping(statistics["market_impact_bps_quantiles"], "impact_quantiles"),
                horizon_seconds=horizon,
                sample_count=n,
                source_field="market_impact_bps_quantiles",
                source_receipt=calibration_sha,
            ),
            _distribution(
                name="slippage_bps_distribution",
                values=_mapping(statistics["slippage_bps_quantiles"], "slippage_quantiles"),
                horizon_seconds=horizon,
                sample_count=n,
                source_field="slippage_bps_quantiles",
                source_receipt=calibration_sha,
            ),
        ),
    )
    groups["outcome_memory"] = _replace_group(
        groups["outcome_memory"],
        scalars=tuple(
            _scalar(
                name=name,
                value=float(statistics[source_field]),
                unit=unit,
                semantic_kind=kind,
                component="outcome_memory",
                source_field=source_field,
                source_receipt=calibration_sha,
                horizon_seconds=None,
                sample_count=n,
            )
            for name, source_field, unit, kind in (
                ("after_cost_expectancy_bps", "after_cost_expectancy_bps", "bps", EMPIRICAL_ESTIMATE),
                ("missed_tp_then_stop_probability", "missed_tp_then_stop_probability", "probability_0_1", EMPIRICAL_RATE),
                ("posterior_uncertainty", "posterior_uncertainty", "probability_0_1", POINT_ESTIMATE),
                ("reversal_probability", "reversal_probability", "probability_0_1", EMPIRICAL_RATE),
                ("slippage_failure_probability", "slippage_failure_probability", "probability_0_1", EMPIRICAL_RATE),
                ("win_rate_posterior_mean", "win_rate_posterior_mean", "probability_0_1", EMPIRICAL_RATE),
            )
        ),
    )
    prediction = _mapping(intent.get("entry_prediction_snapshot"), "entry_prediction_snapshot")
    feature_cutoff_ms = _iso_ms(prediction.get("feature_cutoff"), "feature_cutoff")
    source_available_at_ms = max(
        _iso_ms(prediction.get("available_at"), "prediction.available_at"),
        int(calibration["fit_record_available_at_ms"]),
    )
    if source_available_at_ms > generated_at_ms:
        raise AdaptivePolicyShadowError("source_available_at_ms:future_input_forbidden")
    return AdaptiveComponentEstimatesV1.create(
        candidate_id=candidate_id,
        prediction_id=_identifier(intent.get("prediction_id"), "prediction_id"),
        symbol=_identifier(intent.get("symbol"), "symbol").upper(),
        timeframe=_identifier(intent.get("timeframe"), "timeframe"),
        side=side,
        venue="binance_usdm_paper",
        order_type="MARKET_PAPER_IMMEDIATE_FILL",
        action_under_evaluation_sha256=proposal_sha256,
        state_id=state_id,
        state_sha256=state_sha256,
        feature_snapshot_id=_identifier(prediction.get("feature_snapshot_id"), "feature_snapshot_id"),
        feature_abi_sha256=_feature_abi_sha256(intent, registry),
        feature_builder_sha256=_feature_builder_sha256(intent, registry),
        checkpoint_generation=int(registry["registry_generation"]),
        checkpoint_id=_identifier(registry.get("checkpoint_id"), "checkpoint_id"),
        checkpoint_sha256=_sha(registry.get("checkpoint_bundle_sha256"), "checkpoint_sha256"),
        policy_id=POLICY_ID,
        source_receipt_sha256s=source_receipts,
        state_event_time_ms=feature_cutoff_ms,
        state_ingested_at_ms=_iso_ms(prediction.get("available_at"), "prediction.available_at"),
        feature_cutoff_ms=feature_cutoff_ms,
        source_available_at_ms=source_available_at_ms,
        producer_generated_at_ms=generated_at_ms,
        record_available_at_ms=generated_at_ms,
        decision_time_ms=generated_at_ms,
        latest_unclosed_kline_excluded=True,
        latest_unclosed_exclusion_method=_identifier(
            intent.get("entry_feature_latest_unclosed_exclusion_method")
            or "CLOSED_KLINE_FILTER_DECISION_TIME_BOUNDED_V1",
            "latest_unclosed_exclusion_method",
        ),
        latest_unclosed_exclusion_decision_time_ms=generated_at_ms,
        latest_closed_kline_close_time_ms=int(
            intent.get("entry_feature_latest_closed_kline_close_time_ms") or feature_cutoff_ms
        ),
        component_groups=tuple(groups[name] for name in COMPONENT_NAMES),
        authority_mode=COMPONENT_AUTHORITY_MODE,
        consumed_for_policy=False,
        consumed_for_admission=False,
        emits_trading_action=False,
        paper_only=True,
        live_gate=LIVE_GATE,
        routes_to_live=False,
        places_real_order=False,
        exchange_action_taken=False,
    )


def _hard_check_inputs(
    *,
    intent: Mapping[str, Any],
    paper_status: Mapping[str, Any],
    registry: Mapping[str, Any],
    calibration: Mapping[str, Any],
    action_sha256: str,
    state_sha256: str,
    venue_sha256: str,
    generated_at_ms: int,
    requires_execution_cost: bool,
    requires_physical_execution: bool,
) -> tuple[bool, dict[str, tuple[str, ...]], tuple[str, ...]]:
    intent_sha = _canonical_sha256(intent)
    status_sha = _canonical_sha256(paper_status)
    registry_sha = _canonical_sha256(registry)
    calibration_sha = _sha(calibration.get("calibration_sha256"), "calibration_sha256")
    reservation = intent.get("paper_cycle_reservation_snapshot")
    reservation = reservation if isinstance(reservation, Mapping) else {}
    filters = intent.get("paper_exchange_filter_snapshot")
    filters = filters if isinstance(filters, Mapping) else {}
    failures: list[str] = []
    if intent.get("paper_only") is not True or any(
        intent.get(field) is True
        for field in ("routes_to_live", "places_real_order", "exchange_action_taken")
    ):
        failures.append("authorization_and_paper_only")
    if registry.get("paper_only") is not True or registry.get("live_eligible") is not False:
        failures.append("identity_and_lineage")
    # Feed integrity is a source-authentication boundary, not a Category-E
    # trading preference. It therefore applies to every typed disposition,
    # including REMAIN_FLAT/NO_TRADE.
    if intent.get("feed_integrity_pass") is not True:
        failures.append("data_integrity_and_point_in_time")
    if requires_physical_execution and (
        reservation.get("status") != "PASS"
        or list(reservation.get("rejection_reasons") or [])
    ):
        failures.append("accounting_and_reservation_conservation")
    if requires_physical_execution and (
        filters.get("status") != "READY"
        or list(filters.get("rejection_reasons") or [])
    ):
        failures.append("venue_and_physical_feasibility")
    open_position_count = paper_status.get("open_position_count")
    position_state_valid = (
        paper_status.get("paper_only") is True
        and type(open_position_count) is int
        and open_position_count >= 0
        and (not requires_physical_execution or open_position_count == 0)
    )
    if not position_state_valid:
        failures.append("position_transition_validity")
    if requires_physical_execution and str(
        intent.get("microstructure_action") or ""
    ).strip().upper() == "CLOSE_OR_REDUCE_ONLY":
        # This is the one valid-unfavourable microstructure disposition that
        # changes the permissible position transition.  Its evidence remains
        # a calibrated objective input, but it cannot authorize a new entry.
        failures.append("position_transition_validity")
    prediction = intent.get("entry_prediction_snapshot")
    prediction = prediction if isinstance(prediction, Mapping) else {}
    if (
        intent.get("entry_feature_latest_unclosed_kline_excluded") is not True
        or not prediction.get("feature_cutoff")
        or not prediction.get("available_at")
    ):
        failures.append("data_integrity_and_point_in_time")
    cost_numeric_fields = (
        "fee_bps",
        "observed_spread_bps",
        "expected_slippage_bps",
        "expected_funding_bps",
        "depth_derived_price_impact_bps",
    )
    cost_values_valid = True
    for field in cost_numeric_fields:
        try:
            value = _finite(intent.get(field), field)
        except AdaptivePolicyShadowError:
            cost_values_valid = False
            continue
        if field != "expected_funding_bps" and value < 0.0:
            cost_values_valid = False
    try:
        cost_source_time_ms = _iso_ms(
            intent.get("cost_source_timestamp"), "cost_source_timestamp"
        )
    except AdaptivePolicyShadowError:
        cost_source_time_ms = generated_at_ms + 1
    cost_contract_valid = (
        intent.get("runtime_cost_capture_status") == "PRODUCTION_GRADE_COST_CAPTURE"
        and intent.get("runtime_cost_capture_source")
        == "V2_PAPER_RUNTIME_DECISION_TIME_COST_CAPTURE"
        and intent.get("production_grade_cost_flag") is True
        and intent.get("fallback_cost_flag") is False
        and list(intent.get("runtime_cost_capture_missing_fields") or []) == []
        and list(intent.get("runtime_cost_capture_unexplained_missing_fields") or []) == []
        and list(intent.get("runtime_cost_capture_temporal_reject_reasons") or []) == []
        and cost_values_valid
        and cost_source_time_ms <= generated_at_ms
    )
    if requires_execution_cost and not cost_contract_valid:
        failures.append("data_integrity_and_point_in_time")
    if requires_physical_execution:
        try:
            _microstructure_continuous_policy_inputs(intent)
        except AdaptivePolicyShadowError:
            failures.append("data_integrity_and_point_in_time")
    receipts = tuple(
        sorted(
            {
                value
                for value in (
                    action_sha256,
                    state_sha256,
                    venue_sha256,
                    calibration_sha,
                    _sha(registry.get("checkpoint_bundle_sha256"), "checkpoint_sha256"),
                    *(
                        intent.get(field)
                        for field in _SHA_FIELDS
                        if intent.get(field) is not None
                    ),
                )
                if isinstance(value, str) and len(value) == 64
            }
        )
    )
    reservation_sha = (
        intent.get("paper_cycle_reservation_snapshot_hash")
        if _is_sha256(intent.get("paper_cycle_reservation_snapshot_hash"))
        else _canonical_sha256(
            {
                "schema_version": "adaptive_missing_reservation_evidence_v1",
                "reservation": reservation,
                "requires_physical_execution": requires_physical_execution,
            }
        )
    )
    filter_sha = (
        intent.get("paper_exchange_filter_snapshot_hash")
        if _is_sha256(intent.get("paper_exchange_filter_snapshot_hash"))
        else _canonical_sha256(
            {
                "schema_version": "adaptive_missing_venue_evidence_v1",
                "filters": filters,
                "requires_physical_execution": requires_physical_execution,
            }
        )
    )
    checks = {
        "accounting_and_reservation_conservation": tuple(
            sorted({reservation_sha, status_sha, venue_sha256})
        ),
        "authorization_and_paper_only": tuple(sorted({intent_sha, registry_sha})),
        "catastrophic_loss_envelope": tuple(
            sorted({reservation_sha, venue_sha256})
        ),
        "data_integrity_and_point_in_time": tuple(sorted({calibration_sha, intent_sha})),
        "identity_and_lineage": tuple(sorted({action_sha256, registry_sha, state_sha256})),
        "position_transition_validity": tuple(sorted({intent_sha, status_sha})),
        "venue_and_physical_feasibility": tuple(
            sorted({filter_sha, venue_sha256})
        ),
    }
    return not failures, checks, tuple(sorted(set(failures)))


def _microstructure_continuous_policy_inputs(
    intent: Mapping[str, Any],
) -> dict[str, float]:
    """Validate the exact continuous estimates consumed by the typed action."""

    raw = intent.get("microstructure_continuous_estimates")
    estimates = _mapping(raw, "microstructure_continuous_estimates")
    if (
        estimates.get("schema_version") != "microstructure_continuous_estimates_v1"
        or estimates.get("status") != "PASS_CALIBRATED_CONTINUOUS_ESTIMATES"
        or estimates.get("complete") is not True
        or intent.get("microstructure_continuous_estimates_complete") is not True
    ):
        raise AdaptivePolicyShadowError("microstructure_continuous_estimates:incomplete")
    values = {
        "fill_probability": _finite(
            estimates.get("fill_probability"), "continuous.fill_probability"
        ),
        "slippage_bps": _finite(
            estimates.get("slippage_bps"), "continuous.slippage_bps"
        ),
        "market_impact_bps": _finite(
            estimates.get("market_impact_bps"), "continuous.market_impact_bps"
        ),
        "adverse_selection_probability": _finite(
            estimates.get("adverse_selection_probability"),
            "continuous.adverse_selection_probability",
        ),
    }
    if not 0.0 <= values["fill_probability"] <= 1.0:
        raise AdaptivePolicyShadowError("continuous.fill_probability:probability_required")
    if not 0.0 <= values["adverse_selection_probability"] <= 1.0:
        raise AdaptivePolicyShadowError(
            "continuous.adverse_selection_probability:probability_required"
        )
    if values["slippage_bps"] < 0.0 or values["market_impact_bps"] < 0.0:
        raise AdaptivePolicyShadowError("continuous.costs:nonnegative_required")
    return values


def _objective_action(
    *,
    action_id: str,
    action_sha256: str,
    selected_action: str,
    mode: str,
    statistics: Mapping[str, Any] | None,
    hard_pass: bool,
    hard_receipt: object | None,
    state_id: str,
    state_sha256: str,
    registry: Mapping[str, Any],
    decision_time_ms: int,
    performance_risk_multiplier: float = 1.0,
    microstructure_estimates: Mapping[str, float] | None = None,
) -> ActionObjectiveInputsV2:
    flat = selected_action == ACTION_REMAIN_FLAT
    stats = statistics or {}
    calibrated_slippage = (
        0.0 if flat else float(stats["slippage_bps_quantiles"]["0.5"])
    )
    calibrated_impact = (
        0.0 if flat else float(stats["market_impact_bps_quantiles"]["0.5"])
    )
    continuous = microstructure_estimates or {}
    effective_slippage = (
        0.0
        if flat
        else max(calibrated_slippage, float(continuous.get("slippage_bps", 0.0)))
    )
    effective_impact = (
        0.0
        if flat
        else max(calibrated_impact, float(continuous.get("market_impact_bps", 0.0)))
    )
    current_cost_delta = (effective_slippage - calibrated_slippage) + (
        effective_impact - calibrated_impact
    )
    return ActionObjectiveInputsV2.create(
        schema_version=ACTION_INPUT_SCHEMA_VERSION,
        action_id=action_id,
        action_sha256=action_sha256,
        state_id=state_id,
        state_sha256=state_sha256,
        decision_time_ms=decision_time_ms,
        checkpoint_generation=int(registry["registry_generation"]),
        checkpoint_id=_identifier(registry.get("checkpoint_id"), "checkpoint_id"),
        checkpoint_sha256=_sha(registry.get("checkpoint_bundle_sha256"), "checkpoint_sha256"),
        selected_action=selected_action,
        policy_mode=mode,
        expected_after_cost_return_bps=(
            0.0 if flat else float(stats["after_cost_expectancy_bps"]) - current_cost_delta
        ),
        expected_drawdown_contribution_bps=(
            0.0
            if flat
            else abs(float(stats["mae_bps_quantiles"]["0.5"]))
            * float(stats["loss_probability"])
            * performance_risk_multiplier
        ),
        expected_tail_loss_bps=(
            0.0
            if flat
            else float(stats["tail_loss_bps_quantiles"]["0.9"])
            * float(stats["loss_probability"])
        ),
        liquidation_risk_probability=(0.0 if flat else float(stats["stop_out_probability"])),
        expected_market_impact_bps=effective_impact,
        expected_funding_cost_bps=(0.0 if flat else abs(float(stats["funding_bps_mean"]))),
        expected_turnover_bps=(
            0.0 if flat else float(stats["transaction_cost_bps_quantiles"]["0.5"])
        ),
        expected_concentration_bps=0.0,
        expected_information_gain=(
            0.0 if flat or mode != BOUNDED_EXPLORATION else float(stats["posterior_uncertainty"])
        ),
        hard_constraints_satisfied=hard_pass,
        hard_validation_receipt=hard_receipt,
        unit_contract=UNIT_CONTRACT,
        paper_only=True,
    )


def _inactive_entry() -> EntryPolicyV2:
    return EntryPolicyV2(
        False, "not_applicable", "not_applicable", None, None, 0.0, "not_applicable", 0, False
    )


def _inactive_exit() -> ExitPolicyV2:
    return ExitPolicyV2(
        False,
        "not_applicable",
        None,
        0.0,
        "not_applicable",
        (),
        "not_applicable",
        None,
        "not_applicable",
        0,
    )


def _continuous_performance_risk_multiplier(
    paper_status: Mapping[str, Any],
) -> float:
    """Convert Category-E performance state into a bounded continuous penalty."""

    raw = paper_status.get("performance_risk_state")
    state = raw if isinstance(raw, Mapping) else {}

    def finite_or_neutral(value: Any, neutral: float) -> float:
        if type(value) not in {int, float} or not math.isfinite(float(value)):
            return neutral
        return float(value)

    drawdown_fraction = max(
        0.0,
        finite_or_neutral(state.get("current_drawdown_fraction"), 0.0),
    )
    profit_factor = finite_or_neutral(state.get("profit_factor"), 1.0)
    profit_factor_deficit = max(0.0, 1.0 - profit_factor)
    expectancy_bps = finite_or_neutral(state.get("expectancy_bps"), 0.0)
    expectancy_deficit_fraction = max(0.0, -expectancy_bps) / 10_000.0
    return min(
        10.0,
        1.0
        + drawdown_fraction
        + profit_factor_deficit
        + expectancy_deficit_fraction,
    )


def _policy_action(
    *,
    selected: ActionObjectiveInputsV2,
    intent: Mapping[str, Any],
    registry: Mapping[str, Any],
    calibration: Mapping[str, Any],
    evaluation: object,
    plan: Mapping[str, Any] | None,
    statistics: Mapping[str, Any] | None,
    state_id: str,
    state_sha256: str,
    source_receipts: tuple[str, ...],
    generated_at_ms: int,
    performance_risk_multiplier: float = 1.0,
) -> AdaptivePolicyActionV2:
    flat = selected.selected_action == ACTION_REMAIN_FLAT
    horizon = _HORIZONS[_identifier(intent.get("timeframe"), "timeframe")]
    prediction = _mapping(intent.get("entry_prediction_snapshot"), "entry_prediction_snapshot")
    if flat:
        entry_policy = _inactive_entry()
        exit_policy = _inactive_exit()
        return_quantiles = (ReturnQuantileV2(0.1, 0.0), ReturnQuantileV2(0.5, 0.0), ReturnQuantileV2(0.9, 0.0))
        costs = ExpectedCostBreakdownV2(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        after_cost = 0.0
        side = "flat"
        target_notional = target_margin = leverage = exposure = 0.0
        stop_price = None
        stop_distance = 0.0
        profit_target = None
        expected_drawdown = expected_tail = expected_slippage = expected_impact = 0.0
        fill_probability = 1.0
        adverse_selection = information_gain = 0.0
    else:
        assert plan is not None and statistics is not None
        continuous = _microstructure_continuous_policy_inputs(intent)
        entry = float(plan["entry_price"])
        stop_price = float(plan["stop_price"])
        stop_distance = abs(entry - stop_price) / entry * 10_000.0
        profit_target = float(plan["profit_target_price"])
        maximum_slippage = max(
            0.0,
            float(statistics["slippage_bps_quantiles"]["0.9"]),
            continuous["slippage_bps"],
        )
        entry_policy = EntryPolicyV2(
            True,
            "adaptive_policy_selected_market",
            "adaptive_objective_receipt_bound",
            entry,
            None,
            maximum_slippage,
            "paper_immediate_fill",
            30,
            False,
        )
        exit_policy = ExitPolicyV2(
            True,
            "adaptive_tail_quantile_mandatory_stop",
            stop_price,
            stop_distance,
            "adaptive_distribution_bound",
            (),
            "adaptive_mfe_distribution_target",
            profit_target,
            "adaptive_horizon_bound",
            horizon,
        )
        return_quantiles = tuple(
            ReturnQuantileV2(float(probability), float(statistics["return_bps_quantiles"][probability]))
            for probability in ("0.1", "0.5", "0.9")
        )
        fee = max(0.0, _finite(intent.get("fee_bps"), "fee_bps"))
        spread = max(0.0, _finite(intent.get("observed_spread_bps"), "spread_bps"))
        calibrated_slippage = max(
            0.0, float(statistics["slippage_bps_quantiles"]["0.5"])
        )
        calibrated_impact = max(
            0.0, float(statistics["market_impact_bps_quantiles"]["0.5"])
        )
        slippage = max(calibrated_slippage, continuous["slippage_bps"])
        impact = max(calibrated_impact, continuous["market_impact_bps"])
        funding = float(statistics["funding_bps_mean"])
        total = math.fsum((fee, spread, slippage, impact, funding))
        costs = ExpectedCostBreakdownV2(fee, spread, slippage, impact, funding, total)
        after_cost = float(statistics["after_cost_expectancy_bps"]) - (
            slippage - calibrated_slippage
        ) - (impact - calibrated_impact)
        side = str(plan["side"]).lower()
        target_notional = float(plan["selected_notional_usd"])
        target_margin = float(plan["selected_margin_usd"])
        leverage = float(plan["selected_leverage"])
        exposure = target_notional if side == "long" else -target_notional
        expected_drawdown = abs(float(statistics["mae_bps_quantiles"]["0.5"])) * float(
            statistics["loss_probability"]
        ) * performance_risk_multiplier
        expected_tail = float(statistics["tail_loss_bps_quantiles"]["0.9"]) * float(
            statistics["loss_probability"]
        )
        expected_slippage = slippage
        expected_impact = impact
        fill_probability = min(
            1.0 - float(statistics["venue_infeasible_probability"]),
            continuous["fill_probability"],
        )
        adverse_selection = max(
            float(statistics["slippage_failure_probability"]),
            continuous["adverse_selection_probability"],
        )
        information_gain = (
            float(statistics["posterior_uncertainty"])
            if selected.policy_mode == BOUNDED_EXPLORATION
            else 0.0
        )
    loss_probability = 1.0 if statistics is None else float(statistics["loss_probability"])
    flat_probability = min(1.0, max(0.01, loss_probability))
    directional_probability = 1.0 - flat_probability
    if not flat and directional_probability == 0.0:
        directional_probability = 0.01
        flat_probability = 0.99
    distribution = (
        ActionProbabilityV2(ACTION_DIRECTIONAL_TRADE, directional_probability),
        ActionProbabilityV2(ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE, 0.0),
        ActionProbabilityV2(ACTION_REDUCE_EXISTING_EXPOSURE, 0.0),
        ActionProbabilityV2(ACTION_CLOSE_EXISTING_EXPOSURE, 0.0),
        ActionProbabilityV2(ACTION_REMAIN_FLAT, flat_probability),
    )
    selected_distribution = HorizonReturnDistributionV2(
        horizon_seconds=horizon,
        expected_return_bps=after_cost,
        standard_deviation_bps=(return_quantiles[-1].return_bps - return_quantiles[0].return_bps) / 2.563,
        quantiles=return_quantiles,
    )
    feature_cutoff_ms = _iso_ms(prediction.get("feature_cutoff"), "feature_cutoff")
    selection_sha = _canonical_sha256(asdict(evaluation))
    reservation_value = intent.get("paper_cycle_reservation_snapshot")
    reservation = dict(reservation_value) if isinstance(reservation_value, Mapping) else {}
    reservation_snapshot_hash = reservation.get("snapshot_hash")
    if _is_sha256(reservation_snapshot_hash):
        envelope_sha = str(reservation_snapshot_hash)
        envelope_id = "paper_catastrophic_envelope_" + envelope_sha[:40]
    elif flat:
        envelope_sha = _canonical_sha256(
            {
                "schema_version": "adaptive_nonexecuting_flat_envelope_v1",
                "action_sha256": selected.action_sha256,
                "target_notional_usd": "0",
                "target_margin_usd": "0",
                "mutates_accounting": False,
                "submits_order": False,
            }
        )
        envelope_id = "paper_nonexecuting_flat_envelope_" + envelope_sha[:40]
        source_receipts = tuple(sorted({*source_receipts, envelope_sha}))
    else:
        raise AdaptivePolicyShadowError("reservation.snapshot_hash:sha256_required")
    return AdaptivePolicyActionV2.create(
        state_id=state_id,
        feature_snapshot_id=_identifier(prediction.get("feature_snapshot_id"), "feature_snapshot_id"),
        checkpoint_generation=int(registry["registry_generation"]),
        checkpoint_id=_identifier(registry.get("checkpoint_id"), "checkpoint_id"),
        checkpoint_sha256=_sha(registry.get("checkpoint_bundle_sha256"), "checkpoint_sha256"),
        feature_abi_sha256=_feature_abi_sha256(intent, registry),
        feature_builder_sha256=_feature_builder_sha256(intent, registry),
        policy_id=POLICY_ID,
        policy_generation=POLICY_GENERATION,
        policy_mode=(
            POLICY_MODE_BOUNDED_EXPLORATION
            if selected.policy_mode == BOUNDED_EXPLORATION
            else POLICY_MODE_CHAMPION_EXPLOITATION
        ),
        policy_parameter_fingerprint=_sha(
            _mapping(calibration["learned_objective_weights"], "weights")[
                "objective_parameter_fingerprint"
            ],
            "objective_parameter_fingerprint",
        ),
        calibration_sha256=_sha(calibration.get("calibration_sha256"), "calibration_sha256"),
        state_sha256=state_sha256,
        source_receipt_sha256s=source_receipts,
        selection_receipt_sha256=selection_sha,
        state_event_time_ms=feature_cutoff_ms,
        state_ingested_at_ms=_iso_ms(prediction.get("available_at"), "prediction.available_at"),
        source_available_at_ms=max(
            _iso_ms(prediction.get("available_at"), "prediction.available_at"),
            int(calibration["fit_record_available_at_ms"]),
        ),
        feature_cutoff_ms=feature_cutoff_ms,
        producer_generated_at_ms=generated_at_ms,
        record_available_at_ms=generated_at_ms,
        decision_time_ms=generated_at_ms,
        execution_time_ms=None,
        latest_unclosed_kline_excluded=True,
        latest_unclosed_exclusion_method=_identifier(
            intent.get("entry_feature_latest_unclosed_exclusion_method")
            or "CLOSED_KLINE_FILTER_DECISION_TIME_BOUNDED_V1",
            "latest_unclosed_exclusion_method",
        ),
        latest_unclosed_exclusion_decision_time_ms=generated_at_ms,
        latest_closed_kline_close_time_ms=int(
            intent.get("entry_feature_latest_closed_kline_close_time_ms") or feature_cutoff_ms
        ),
        primary_symbol=_identifier(intent.get("symbol"), "symbol").upper(),
        primary_timeframe=_identifier(intent.get("timeframe"), "timeframe"),
        primary_side=side,
        target_exposure_usd=exposure,
        target_notional_usd=target_notional,
        leverage=leverage,
        margin_mode_simulation=("none" if flat else "isolated_paper_simulated"),
        margin_allocation_usd=target_margin,
        entry_style=entry_policy.style,
        entry_price_policy=entry_policy.price_policy,
        maximum_entry_slippage=entry_policy.maximum_slippage_bps,
        order_duration_policy=entry_policy.order_duration_policy,
        entry_policy=entry_policy,
        protective_stop_policy=exit_policy.protective_stop_policy,
        stop_price=stop_price,
        stop_distance=stop_distance,
        partial_reduction_policy=exit_policy.partial_reduction_policy,
        profit_exit_policy=exit_policy.profit_exit_policy,
        time_exit_policy=exit_policy.time_exit_policy,
        expected_holding_horizon=(0 if flat else horizon),
        exit_policy=exit_policy,
        hedge_enabled=False,
        hedge_legs=(),
        hedge_ratios=(),
        expected_before_cost_return=after_cost + costs.total_cost_bps,
        expected_cost_breakdown=costs,
        expected_after_cost_return=after_cost,
        expected_return_distribution=(selected_distribution,),
        policy_evaluation_horizon_seconds=horizon,
        expected_drawdown_contribution=expected_drawdown,
        expected_tail_loss=expected_tail,
        expected_fill_probability=fill_probability,
        expected_slippage=expected_slippage,
        expected_market_impact=expected_impact,
        expected_adverse_selection=adverse_selection,
        expected_information_gain=information_gain,
        flat_probability=flat_probability,
        selected_action=selected.selected_action,
        action_distribution=distribution,
        policy_uncertainty=(1.0 if statistics is None else float(statistics["posterior_uncertainty"])),
        decision_rationale_codes=(
            "CALIBRATED_ADAPTIVE_OBJECTIVE",
            "HARD_CONSTRAINT_VALIDATED",
            "NONTERMINAL_LEARNING_CONTINUES",
            "PERFORMANCE_RISK_CONTINUOUS_OBJECTIVE_INPUT",
            *(() if flat else ("MICROSTRUCTURE_CONTINUOUS_ESTIMATES_CONSUMED",)),
        ),
        learning_continuation_action=(
            "label_and_evaluate_missed_opportunity" if flat else "mature_candidate_and_incremental_retrain"
        ),
        affected_position_ids=(),
        position_adjustments=(),
        reduce_only=False,
        operator_catastrophic_envelope_id=envelope_id,
        operator_catastrophic_envelope_sha256=envelope_sha,
        integrity_evidence_sha256=_canonical_sha256(source_receipts),
        execution_domain="PAPER",
        policy_authority_scope="trading_action_only",
        requires_hard_validator=True,
        execution_authority=False,
        hard_validator_decision_id=None,
        unit_contract=UNIT_CONTRACT_USD_BPS_SECONDS_PROBABILITY,
        paper_only=True,
        live_gate=LIVE_GATE_BLOCKED_HUMAN_ONLY,
        routes_to_live=False,
        places_real_order=False,
        exchange_action_taken=False,
        live_eligible=False,
        live_submission_ready=False,
    )


@dataclass(frozen=True, slots=True)
class AdaptivePolicyShadowCandidateV2:
    candidate_id: str
    source_intent_sha256: str
    production_decision: dict[str, Any]
    component_estimates: tuple[AdaptiveComponentEstimatesV1, ...]
    objective_inputs: tuple[ActionObjectiveInputsV2, ...]
    objective_evaluation: object
    venue_attestations: tuple[SelectedActionVenueFeasibilityV2, ...]
    action_dispositions: tuple[tuple[str, tuple[str, ...]], ...]
    selected_adaptive_action: AdaptivePolicyActionV2
    reference_utilities: tuple[tuple[str, float | None], ...]
    parity_disagreement_count: int
    parity_status: str
    paper_only: bool
    live_gate: str
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise AdaptivePolicyShadowError("schema_version:invalid")
        if self.parity_disagreement_count != 0 or self.parity_status != "PASS":
            raise AdaptivePolicyShadowError("reference_parity:disagreement")
        if self.paper_only is not True or self.live_gate != LIVE_GATE:
            raise AdaptivePolicyShadowError("safety:paper_only_human_block_required")
        if any((self.routes_to_live, self.places_real_order, self.exchange_action_taken)):
            raise AdaptivePolicyShadowError("safety:live_or_exchange_authority_forbidden")
        objective_ids = tuple(sorted(item.action_id for item in self.objective_inputs))
        disposition_ids = tuple(item[0] for item in self.action_dispositions)
        if disposition_ids != objective_ids:
            raise AdaptivePolicyShadowError("action_dispositions:exact_objective_coverage_required")
        if any(
            type(reasons) is not tuple or reasons != tuple(sorted(set(reasons)))
            for _action_id, reasons in self.action_dispositions
        ):
            raise AdaptivePolicyShadowError("action_dispositions:sorted_unique_reasons_required")

    @property
    def content_sha256(self) -> str:
        return _canonical_sha256(asdict(self))


def build_adaptive_policy_shadow_candidate(
    *,
    intent: Mapping[str, Any],
    feature_snapshot: Mapping[str, Any],
    paper_status: Mapping[str, Any],
    calibration: Mapping[str, Any],
    registry: Mapping[str, Any],
    validator_seed: bytes,
    generated_at_ms: int,
) -> AdaptivePolicyShadowCandidateV2:
    """Build and independently verify one shadow decision."""

    validate_candidate_outcome_calibration_v2(calibration)
    snapshot = _mapping(feature_snapshot, "feature_snapshot")
    prediction_before_normalization = _mapping(
        intent.get("entry_prediction_snapshot"), "entry_prediction_snapshot"
    )
    snapshot_id = _identifier(snapshot.get("feature_snapshot_id"), "feature_snapshot_id")
    if snapshot_id != prediction_before_normalization.get("feature_snapshot_id"):
        raise AdaptivePolicyShadowError("feature_snapshot:prediction_identity_mismatch")
    if snapshot.get("latest_unclosed_kline_excluded") is not True:
        raise AdaptivePolicyShadowError("feature_snapshot:unclosed_kline_not_excluded")
    if snapshot.get("trainer_consumable") is not True:
        raise AdaptivePolicyShadowError("feature_snapshot:not_trainer_consumable")
    if snapshot.get("feature_cutoff") != prediction_before_normalization.get("feature_cutoff"):
        raise AdaptivePolicyShadowError("feature_snapshot:feature_cutoff_mismatch")
    snapshot_content_sha = _sha(snapshot.get("content_sha256"), "snapshot.content_sha256")
    normalized_intent = dict(intent)
    normalized_intent.setdefault("entry_feature_latest_unclosed_kline_excluded", True)
    normalized_intent.setdefault(
        "entry_feature_latest_unclosed_exclusion_method",
        snapshot.get("latest_unclosed_exclusion_method"),
    )
    normalized_intent.setdefault(
        "entry_feature_latest_unclosed_exclusion_decision_time_ms",
        snapshot.get("latest_unclosed_exclusion_decision_time_ms"),
    )
    normalized_intent.setdefault(
        "entry_feature_latest_closed_kline_close_time_ms",
        snapshot.get("latest_closed_kline_close_time_ms"),
    )
    for field in (
        "entry_feature_latest_unclosed_kline_excluded",
        "entry_feature_latest_unclosed_exclusion_method",
        "entry_feature_latest_unclosed_exclusion_decision_time_ms",
        "entry_feature_latest_closed_kline_close_time_ms",
    ):
        if normalized_intent.get(field) is None:
            snapshot_field = field.removeprefix("entry_feature_")
            normalized_intent[field] = snapshot.get(snapshot_field)
    intent = normalized_intent
    if generated_at_ms <= int(calibration["fit_record_available_at_ms"]):
        raise AdaptivePolicyShadowError("generated_at_ms:must_follow_calibration_availability")
    if (
        calibration.get("checkpoint_generation") != registry.get("registry_generation")
        or calibration.get("checkpoint_id") != registry.get("checkpoint_id")
        or calibration.get("checkpoint_sha256") != registry.get("checkpoint_bundle_sha256")
    ):
        raise AdaptivePolicyShadowError("calibration:active_registry_mismatch")
    candidate_id = _candidate_id(intent, registry)
    source_intent_sha = _canonical_sha256(
        {
            "intent": intent,
            "verified_feature_snapshot_content_sha256": snapshot_content_sha,
        }
    )
    state_id = _identifier(
        intent.get("market_state_id")
        or _mapping(intent.get("entry_prediction_snapshot"), "prediction").get("mtf_snapshot_id"),
        "state_id",
    )
    state_sha = _canonical_sha256(
        {
            "candidate_id": candidate_id,
            "source_intent_sha256": source_intent_sha,
            "calibration_sha256": calibration["calibration_sha256"],
            "checkpoint_generation": registry["registry_generation"],
            "checkpoint_id": registry["checkpoint_id"],
        }
    )
    source_values: set[str] = {
        source_intent_sha,
        _sha(calibration.get("calibration_sha256"), "calibration_sha256"),
        _sha(registry.get("checkpoint_bundle_sha256"), "checkpoint_bundle_sha256"),
        _feature_abi_sha256(intent, registry),
        _feature_builder_sha256(intent, registry),
        snapshot_content_sha,
        _canonical_sha256(paper_status.get("performance_risk_state") or {}),
    }
    prediction = _mapping(intent.get("entry_prediction_snapshot"), "entry_prediction_snapshot")
    source_hashes = prediction.get("source_hashes")
    if isinstance(source_hashes, Mapping):
        source_values.update(
            value
            for value in source_hashes.values()
            if isinstance(value, str) and len(value) == 64
        )
    for field in _SHA_FIELDS:
        value = intent.get(field)
        if isinstance(value, str) and len(value) == 64:
            source_values.add(value)
    try:
        continuous_microstructure = _microstructure_continuous_policy_inputs(intent)
    except AdaptivePolicyShadowError:
        continuous_microstructure = None
    raw_continuous_microstructure = intent.get("microstructure_continuous_estimates")
    if isinstance(raw_continuous_microstructure, Mapping):
        source_values.add(_canonical_sha256(dict(raw_continuous_microstructure)))
    source_receipts = tuple(sorted(source_values))
    weights = _weights(calibration)
    allocation = _allocation(calibration, state_id=state_id, state_sha256=state_sha)
    performance_risk_multiplier = _continuous_performance_risk_multiplier(
        paper_status
    )
    objective_inputs: list[ActionObjectiveInputsV2] = []
    bundles: list[AdaptiveComponentEstimatesV1] = []
    attestations: list[SelectedActionVenueFeasibilityV2] = []
    action_dispositions: dict[str, tuple[str, ...]] = {}
    plans: dict[str, dict[str, Any]] = {}
    stats_by_action: dict[str, dict[str, Any]] = {}
    for side in ("LONG", "SHORT"):
        stats = _statistics(calibration, side, _identifier(intent.get("timeframe"), "timeframe"))
        for mode in (CHAMPION_EXPLOITATION, BOUNDED_EXPLORATION):
            action_id = f"{candidate_id}:{mode}:{side.lower()}"
            try:
                plan = _physical_plan(intent=intent, statistics=stats, side=side, mode=mode)
            except AdaptivePolicyShadowError as exc:
                blocker = f"PHYSICAL_PLAN_UNAVAILABLE:{exc}"
                proposal_sha = _canonical_sha256(
                    {
                        "schema_version": "adaptive_policy_unavailable_proposal_v2",
                        "candidate_id": candidate_id,
                        "action_id": action_id,
                        "side": side,
                        "mode": mode,
                        "physical_plan_available": False,
                        "physical_plan_blocker": blocker,
                        "calibration_sha256": calibration["calibration_sha256"],
                    }
                )
                objective_inputs.append(
                    _objective_action(
                        action_id=action_id,
                        action_sha256=proposal_sha,
                        selected_action=ACTION_DIRECTIONAL_TRADE,
                        mode=mode,
                        statistics=stats,
                        hard_pass=False,
                        hard_receipt=None,
                        state_id=state_id,
                        state_sha256=state_sha,
                        registry=registry,
                        decision_time_ms=generated_at_ms,
                        performance_risk_multiplier=performance_risk_multiplier,
                        microstructure_estimates=continuous_microstructure,
                    )
                )
                action_dispositions[action_id] = (blocker,)
                continue
            proposal = {
                "schema_version": "adaptive_policy_proposal_v2",
                "candidate_id": candidate_id,
                "action_id": action_id,
                "side": side,
                "mode": mode,
                "selected_entry_price": str(plan["entry_price"]),
                "selected_stop_price": str(plan["stop_price"]),
                "selected_quantity": str(plan["selected_quantity"]),
                "selected_notional_usd": str(plan["selected_notional_usd"]),
                "selected_leverage": str(plan["selected_leverage"]),
                "selected_margin_usd": str(plan["selected_margin_usd"]),
                "calibration_sha256": calibration["calibration_sha256"],
            }
            proposal_sha = _canonical_sha256(proposal)
            venue = _venue_attestation(
                intent=intent,
                candidate_id=candidate_id,
                proposal_sha256=proposal_sha,
                plan=plan,
            )
            venue_sha = _canonical_sha256(asdict(venue))
            hard_pass, checks, failures = _hard_check_inputs(
                intent=intent,
                paper_status=paper_status,
                registry=registry,
                calibration=calibration,
                action_sha256=proposal_sha,
                state_sha256=state_sha,
                venue_sha256=venue_sha,
                generated_at_ms=generated_at_ms,
                requires_execution_cost=True,
                requires_physical_execution=True,
            )
            hard_pass = hard_pass and venue.decision == DECISION_EXECUTABLE
            disposition_reasons = set(failures)
            if venue.decision != DECISION_EXECUTABLE:
                disposition_reasons.update(
                    f"venue:{reason}" for reason in venue.failed_checks
                )
            action_dispositions[action_id] = tuple(sorted(disposition_reasons))
            receipt = (
                sign_hard_constraint_validation_receipt(
                    validator_seed=validator_seed,
                    action_sha256=proposal_sha,
                    state_id=state_id,
                    state_sha256=state_sha,
                    checkpoint_generation=int(registry["registry_generation"]),
                    checkpoint_id=_identifier(registry.get("checkpoint_id"), "checkpoint_id"),
                    checkpoint_sha256=_sha(
                        registry.get("checkpoint_bundle_sha256"), "checkpoint_sha256"
                    ),
                    decision_time_ms=generated_at_ms,
                    evaluated_at_ms=generated_at_ms,
                    validator_generated_at_ms=generated_at_ms,
                    record_available_at_ms=generated_at_ms,
                    check_input_evidence_sha256s=checks,
                )
                if hard_pass
                else None
            )
            objective_inputs.append(
                _objective_action(
                    action_id=action_id,
                    action_sha256=proposal_sha,
                    selected_action=ACTION_DIRECTIONAL_TRADE,
                    mode=mode,
                    statistics=stats,
                    hard_pass=hard_pass,
                    hard_receipt=receipt,
                    state_id=state_id,
                    state_sha256=state_sha,
                    registry=registry,
                    decision_time_ms=generated_at_ms,
                    performance_risk_multiplier=performance_risk_multiplier,
                    microstructure_estimates=continuous_microstructure,
                )
            )
            bundles.append(
                _component_bundle(
                    intent=intent,
                    calibration=calibration,
                    registry=registry,
                    candidate_id=candidate_id,
                    side=side,
                    statistics=stats,
                    proposal_sha256=proposal_sha,
                    plan=plan,
                    venue=venue,
                    state_id=state_id,
                    state_sha256=state_sha,
                    source_receipts=tuple(sorted({*source_receipts, venue_sha})),
                    generated_at_ms=generated_at_ms,
                )
            )
            attestations.append(venue)
            plans[action_id] = plan
            stats_by_action[action_id] = stats
    flat_id = f"{candidate_id}:{CHAMPION_EXPLOITATION}:flat"
    flat_sha = _canonical_sha256(
        {
            "schema_version": "adaptive_policy_flat_proposal_v2",
            "candidate_id": candidate_id,
            "action_id": flat_id,
            "calibration_sha256": calibration["calibration_sha256"],
            "learning_continuation_action": "label_and_evaluate_missed_opportunity",
        }
    )
    flat_fact_sha = _canonical_sha256(
        {"selected_action": ACTION_REMAIN_FLAT, "mutates_accounting": False, "submits_order": False}
    )
    flat_pass, flat_checks, flat_failures = _hard_check_inputs(
        intent=intent,
        paper_status=paper_status,
        registry=registry,
        calibration=calibration,
        action_sha256=flat_sha,
        state_sha256=state_sha,
        venue_sha256=flat_fact_sha,
        generated_at_ms=generated_at_ms,
        requires_execution_cost=False,
        requires_physical_execution=False,
    )
    action_dispositions[flat_id] = tuple(sorted(flat_failures))
    flat_receipt = (
        sign_hard_constraint_validation_receipt(
            validator_seed=validator_seed,
            action_sha256=flat_sha,
            state_id=state_id,
            state_sha256=state_sha,
            checkpoint_generation=int(registry["registry_generation"]),
            checkpoint_id=_identifier(registry.get("checkpoint_id"), "checkpoint_id"),
            checkpoint_sha256=_sha(registry.get("checkpoint_bundle_sha256"), "checkpoint_sha256"),
            decision_time_ms=generated_at_ms,
            evaluated_at_ms=generated_at_ms,
            validator_generated_at_ms=generated_at_ms,
            record_available_at_ms=generated_at_ms,
            check_input_evidence_sha256s=flat_checks,
        )
        if flat_pass
        else None
    )
    objective_inputs.append(
        _objective_action(
            action_id=flat_id,
            action_sha256=flat_sha,
            selected_action=ACTION_REMAIN_FLAT,
            mode=CHAMPION_EXPLOITATION,
            statistics=None,
            hard_pass=flat_pass,
            hard_receipt=flat_receipt,
            state_id=state_id,
            state_sha256=state_sha,
            registry=registry,
            decision_time_ms=generated_at_ms,
            performance_risk_multiplier=performance_risk_multiplier,
            microstructure_estimates=None,
        )
    )
    ordered_inputs = tuple(sorted(objective_inputs, key=lambda item: item.action_id))
    evaluation = evaluate_shadow_objective(ordered_inputs, weights, allocation)
    reference = evaluate_reference_objective(ordered_inputs, weights)
    production_utilities = tuple(
        sorted((score.action_id, score.utility) for score in evaluation.scores)
    )
    disagreements = 0
    if evaluation.champion_action_id != reference.champion_action_id:
        disagreements += 1
    if evaluation.exploration_action_id != reference.exploration_action_id:
        disagreements += 1
    for production, expected in zip(production_utilities, reference.utilities, strict=True):
        if production[0] != expected[0] or (
            production[1] is None
        ) != (expected[1] is None):
            disagreements += 1
        elif production[1] is not None and expected[1] is not None and not math.isclose(
            production[1], expected[1], rel_tol=0.0, abs_tol=1e-12
        ):
            disagreements += 1
    if disagreements:
        raise AdaptivePolicyShadowError(
            f"reference_parity:disagreement_count={disagreements}"
        )
    draw = int(
        hashlib.sha256(f"{candidate_id}:{calibration['calibration_sha256']}".encode()).hexdigest()[:16],
        16,
    ) / float(2**64)
    choose_exploration = draw < allocation.bounded_exploration_probability
    selected_id = (
        evaluation.exploration_action_id
        if choose_exploration and evaluation.exploration_action_id is not None
        else evaluation.champion_action_id
    )
    if selected_id is None:
        raise AdaptivePolicyShadowError("objective:no_hard_valid_selection")
    selected_input = next(item for item in ordered_inputs if item.action_id == selected_id)
    selected_action = _policy_action(
        selected=selected_input,
        intent=intent,
        registry=registry,
        calibration=calibration,
        evaluation=evaluation,
        plan=plans.get(selected_id),
        statistics=stats_by_action.get(selected_id),
        state_id=state_id,
        state_sha256=state_sha,
        source_receipts=source_receipts,
        generated_at_ms=generated_at_ms,
        performance_risk_multiplier=performance_risk_multiplier,
    )
    production = {
        "preemptive_decision_id": intent.get("preemptive_decision_id"),
        "preemptive_decision": intent.get("preemptive_decision"),
        "preemptive_decision_reasons": list(intent.get("preemptive_decision_reasons") or []),
        "paper_fill_allowed": intent.get("paper_fill_allowed") is True,
        "allocator_decision": intent.get("allocator_decision"),
        "paper_fill_block_reason": intent.get("paper_fill_block_reason"),
        "static_category_e_authority_consumed_by_adaptive_shadow": False,
    }
    return AdaptivePolicyShadowCandidateV2(
        candidate_id=candidate_id,
        source_intent_sha256=source_intent_sha,
        production_decision=production,
        component_estimates=tuple(bundles),
        objective_inputs=ordered_inputs,
        objective_evaluation=evaluation,
        venue_attestations=tuple(attestations),
        action_dispositions=tuple(sorted(action_dispositions.items())),
        selected_adaptive_action=selected_action,
        reference_utilities=reference.utilities,
        parity_disagreement_count=0,
        parity_status="PASS",
        paper_only=True,
        live_gate=LIVE_GATE,
        routes_to_live=False,
        places_real_order=False,
        exchange_action_taken=False,
    )


__all__ = (
    "AdaptivePolicyShadowCandidateV2",
    "AdaptivePolicyShadowError",
    "build_adaptive_policy_shadow_candidate",
)
