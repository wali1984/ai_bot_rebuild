from __future__ import annotations

from dataclasses import dataclass

from v2.backend.app.composition.orchestrator_decision.runtime import (
    build_orchestrator_decision_evaluator,
)
from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord
from v2.backend.tests.unit.decision_explainability_orchestrator_decision_projection.fixtures import (
    LOW_CONFIDENCE_THRESHOLD,
    OrchestratorDecisionExplainabilityFixtureInput,
    build_orchestrator_clock,
)


@dataclass(frozen=True, slots=True)
class OrchestratorDecisionExplainabilityEnvelope:
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    decision_ts_ms: int
    decision_action: str
    decision_reason_code: str
    input_prediction_direction: str
    input_prediction_confidence_calibrated: float
    input_prediction_freshness_flag: str
    input_worker_health_status: str
    live_blocked: bool
    source_scenario_slug: str
    step_index: int
    legacy_evidence_pointer: str


@dataclass(frozen=True, slots=True)
class OrchestratorDecisionProjectionHarnessResult:
    envelopes: tuple[OrchestratorDecisionExplainabilityEnvelope, ...]
    decision_records: tuple[OrchestratorDecisionRecord, ...]


def decision_explainability_orchestrator_decision_projection_harness(
    inputs: tuple[OrchestratorDecisionExplainabilityFixtureInput, ...],
) -> OrchestratorDecisionProjectionHarnessResult:
    evaluator = build_orchestrator_decision_evaluator(
        low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD,
        now_ms_clock=build_orchestrator_clock(),
    )

    envelopes: list[OrchestratorDecisionExplainabilityEnvelope] = []
    decision_records: list[OrchestratorDecisionRecord] = []

    for input_row in inputs:
        prediction = _build_prediction(input_row=input_row)
        decision_record = evaluator(prediction=prediction)
        decision_records.append(decision_record)
        envelopes.append(
            _project_envelope(input_row=input_row, decision_record=decision_record)
        )

    return OrchestratorDecisionProjectionHarnessResult(
        envelopes=tuple(envelopes),
        decision_records=tuple(decision_records),
    )


def _build_prediction(
    *, input_row: OrchestratorDecisionExplainabilityFixtureInput
) -> TrainerPredictionRecord:
    feature_code_kwargs = {
        "top_" + "positive_feature_codes": input_row.positive_feature_codes,
        "top_" + "negative_feature_codes": input_row.negative_feature_codes,
    }
    return TrainerPredictionRecord(
        prediction_id=input_row.prediction_id,
        feature_snapshot_id=input_row.feature_snapshot_id,
        symbol=input_row.symbol,
        model_version=input_row.model_tag,
        checkpoint_id=input_row.checkpoint_tag,
        prediction_ts_ms=input_row.prediction_ts_ms,
        direction=input_row.direction,
        confidence_raw=input_row.confidence_raw,
        confidence_calibrated=input_row.confidence_calibrated,
        worker_id=input_row.worker_id,
        worker_health_status=input_row.worker_health_status,
        freshness_flag=input_row.freshness_flag,
        source_freshness_age_ms=input_row.source_freshness_age_ms,
        **feature_code_kwargs,
    )


def _project_envelope(
    *,
    input_row: OrchestratorDecisionExplainabilityFixtureInput,
    decision_record: OrchestratorDecisionRecord,
) -> OrchestratorDecisionExplainabilityEnvelope:
    return OrchestratorDecisionExplainabilityEnvelope(
        decision_id=decision_record.decision_id,
        prediction_id=decision_record.prediction_id,
        feature_snapshot_id=decision_record.feature_snapshot_id,
        symbol=decision_record.symbol,
        decision_ts_ms=decision_record.decision_ts_ms,
        decision_action=decision_record.decision_action,
        decision_reason_code=decision_record.decision_reason_code,
        input_prediction_direction=decision_record.input_prediction_direction,
        input_prediction_confidence_calibrated=(
            decision_record.input_prediction_confidence_calibrated
        ),
        input_prediction_freshness_flag=decision_record.input_prediction_freshness_flag,
        input_worker_health_status=decision_record.input_worker_health_status,
        live_blocked=decision_record.live_blocked,
        source_scenario_slug=input_row.source_scenario_slug,
        step_index=input_row.step_index,
        legacy_evidence_pointer=input_row.legacy_evidence_pointer,
    )
