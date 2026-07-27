from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from v2.backend.app.domain.adaptive_component_estimates_v1 import (
    AVAILABLE,
    FACT,
    HEURISTIC_SCORE,
    AdaptiveComponentEstimatesV1,
    ComponentEstimateGroupV1,
    ScalarEstimateV1,
    unavailable_component_group,
)


@dataclass(frozen=True, slots=True)
class LegacyCandidateProjectionContextV1:
    candidate_id: str
    prediction_id: str
    symbol: str
    timeframe: str
    side: str
    venue: str
    order_type: str
    action_under_evaluation_sha256: str
    state_id: str
    state_sha256: str
    feature_snapshot_id: str
    feature_abi_sha256: str
    feature_builder_sha256: str
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    policy_id: str
    source_receipt_sha256s: tuple[str, ...]
    state_event_time_ms: int
    state_ingested_at_ms: int
    feature_cutoff_ms: int
    source_available_at_ms: int
    producer_generated_at_ms: int
    record_available_at_ms: int
    decision_time_ms: int
    latest_unclosed_kline_excluded: bool
    latest_unclosed_exclusion_method: str
    latest_unclosed_exclusion_decision_time_ms: int
    latest_closed_kline_close_time_ms: int
    source_producer_id: str
    source_schema: str


_DIAGNOSTIC_FIELDS: dict[str, tuple[str, ...]] = {
    "confidence": ("confidence_calibrated", "confidence_raw", "confidence"),
    "execution_quality": ("execution_quality_score",),
    "exit_feasibility": ("exit_feasibility_score",),
    "loss_risk": ("pre_trade_loss_probability", "loss_probability"),
    "mfe_mae": ("mfe_mae_score",),
    "microstructure": (
        "microstructure_quality_score",
        "microstructure_trust_score",
        "fvg_microstructure_trust_score",
    ),
    "outcome_memory": ("outcome_memory_score",),
    "regime": ("regime_confidence",),
}

_DIAGNOSTIC_ACTION_FIELDS: dict[str, str] = {
    "confidence": "confidence_action",
    "execution_quality": "execution_quality_action",
    "exit_feasibility": "exit_feasibility_action",
    "loss_risk": "loss_risk_action",
    "mfe_mae": "mfe_mae_action",
    "microstructure": "microstructure_action",
    "outcome_memory": "outcome_memory_action",
    "regime": "regime_action",
}


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def _diagnostic_estimates(
    source: Mapping[str, Any],
    *,
    component_name: str,
    context: LegacyCandidateProjectionContextV1,
) -> tuple[ScalarEstimateV1, ...]:
    estimates: list[ScalarEstimateV1] = []
    for source_field in _DIAGNOSTIC_FIELDS[component_name]:
        value = _finite_float(source.get(source_field))
        if value is None:
            continue
        estimates.append(
            ScalarEstimateV1(
                name=f"{component_name}_heuristic_{source_field}",
                availability=AVAILABLE,
                semantic_kind=HEURISTIC_SCORE,
                value=value,
                unit="legacy_score",
                horizon_seconds=None,
                sample_count=None,
                producer_id=context.source_producer_id,
                source_field=source_field,
                source_schema=context.source_schema,
                model_id=f"legacy_{component_name}_diagnostic_v1",
                calibration_evidence=None,
                source_receipt_sha256s=context.source_receipt_sha256s,
                unavailable_reason=None,
            )
        )
    return tuple(sorted(estimates, key=lambda item: item.name))


def _source_diagnostic_action(
    source: Mapping[str, Any],
    component_name: str,
) -> str | None:
    value = source.get(_DIAGNOSTIC_ACTION_FIELDS[component_name])
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or any(character.isspace() for character in normalized):
        return None
    return normalized


def _venue_fact(
    source: Mapping[str, Any],
    context: LegacyCandidateProjectionContextV1,
) -> ScalarEstimateV1 | None:
    value = source.get("venue_feasible")
    if not isinstance(value, bool):
        return None
    return ScalarEstimateV1(
        name="venue_feasible",
        availability=AVAILABLE,
        semantic_kind=FACT,
        value=value,
        unit="boolean",
        horizon_seconds=None,
        sample_count=None,
        producer_id=context.source_producer_id,
        source_field="venue_feasible",
        source_schema=context.source_schema,
        model_id=None,
        calibration_evidence=None,
        source_receipt_sha256s=context.source_receipt_sha256s,
        unavailable_reason=None,
    )


def _replace_required_scalar(
    group: ComponentEstimateGroupV1,
    estimate: ScalarEstimateV1,
) -> ComponentEstimateGroupV1:
    scalars = {item.name: item for item in group.scalar_estimates}
    scalars[estimate.name] = estimate
    return replace(
        group,
        scalar_estimates=tuple(scalars[name] for name in sorted(scalars)),
    )


def project_legacy_candidate_diagnostics(
    source: Mapping[str, Any],
    context: LegacyCandidateProjectionContextV1,
) -> AdaptiveComponentEstimatesV1:
    """Project legacy paper evidence without granting it calibrated policy authority."""

    if not isinstance(source, Mapping):
        raise TypeError("source must be a mapping")
    groups: list[ComponentEstimateGroupV1] = []
    for component_name in _DIAGNOSTIC_FIELDS:
        group = unavailable_component_group(
            component_name,
            reason="calibrated_component_estimate_not_available",
            source_diagnostic_action=_source_diagnostic_action(source, component_name),
        )
        group = replace(
            group,
            diagnostic_scalar_estimates=_diagnostic_estimates(
                source,
                component_name=component_name,
                context=context,
            ),
        )
        if component_name == "execution_quality":
            fact = _venue_fact(source, context)
            if fact is not None:
                group = _replace_required_scalar(group, fact)
        groups.append(group)

    return AdaptiveComponentEstimatesV1.create(
        candidate_id=context.candidate_id,
        prediction_id=context.prediction_id,
        symbol=context.symbol,
        timeframe=context.timeframe,
        side=context.side,
        venue=context.venue,
        order_type=context.order_type,
        action_under_evaluation_sha256=context.action_under_evaluation_sha256,
        state_id=context.state_id,
        state_sha256=context.state_sha256,
        feature_snapshot_id=context.feature_snapshot_id,
        feature_abi_sha256=context.feature_abi_sha256,
        feature_builder_sha256=context.feature_builder_sha256,
        checkpoint_generation=context.checkpoint_generation,
        checkpoint_id=context.checkpoint_id,
        checkpoint_sha256=context.checkpoint_sha256,
        policy_id=context.policy_id,
        source_receipt_sha256s=context.source_receipt_sha256s,
        state_event_time_ms=context.state_event_time_ms,
        state_ingested_at_ms=context.state_ingested_at_ms,
        feature_cutoff_ms=context.feature_cutoff_ms,
        source_available_at_ms=context.source_available_at_ms,
        producer_generated_at_ms=context.producer_generated_at_ms,
        record_available_at_ms=context.record_available_at_ms,
        decision_time_ms=context.decision_time_ms,
        latest_unclosed_kline_excluded=context.latest_unclosed_kline_excluded,
        latest_unclosed_exclusion_method=context.latest_unclosed_exclusion_method,
        latest_unclosed_exclusion_decision_time_ms=(
            context.latest_unclosed_exclusion_decision_time_ms
        ),
        latest_closed_kline_close_time_ms=context.latest_closed_kline_close_time_ms,
        component_groups=tuple(groups),
        authority_mode="SHADOW_DIAGNOSTIC_ONLY",
        consumed_for_policy=False,
        consumed_for_admission=False,
        emits_trading_action=False,
        paper_only=True,
        live_gate="blocked_human_only",
        routes_to_live=False,
        places_real_order=False,
        exchange_action_taken=False,
    )


__all__ = (
    "LegacyCandidateProjectionContextV1",
    "project_legacy_candidate_diagnostics",
)
