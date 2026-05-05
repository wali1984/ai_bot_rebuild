from __future__ import annotations

import math
from collections.abc import Callable

from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_ACTION_HOLD,
    DECISION_ACTION_OPEN_LONG,
    DECISION_ACTION_OPEN_SHORT,
    DECISION_REASON_ABSTAIN_FRESHNESS_MISSING,
    DECISION_REASON_ABSTAIN_FRESHNESS_STALE,
    DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
    DECISION_REASON_ABSTAIN_WORKER_CRITICAL,
    DECISION_REASON_ABSTAIN_WORKER_DEGRADED,
    DECISION_REASON_ABSTAIN_WORKER_UNKNOWN,
    DECISION_REASON_HOLD_FLAT_DIRECTION,
    DECISION_REASON_PROCEED_LONG,
    DECISION_REASON_PROCEED_SHORT,
    OrchestratorDecisionRecord,
)
from v2.backend.app.domain.trainer_prediction_output import (
    PREDICTION_DIRECTION_FLAT,
    PREDICTION_DIRECTION_LONG,
    PREDICTION_DIRECTION_SHORT,
    PREDICTION_FRESHNESS_MISSING,
    PREDICTION_FRESHNESS_STALE,
    TrainerPredictionRecord,
)

from .errors import OrchestratorDecisionServiceError


def assemble_orchestrator_decision_record(
    *,
    prediction: TrainerPredictionRecord,
    low_confidence_threshold: float,
    now_ms_clock: Callable[[], int],
) -> OrchestratorDecisionRecord:
    if not isinstance(prediction, TrainerPredictionRecord):
        raise OrchestratorDecisionServiceError(
            "must_be_trainer_prediction_record", field="prediction"
        )
    if not isinstance(low_confidence_threshold, float) or isinstance(
        low_confidence_threshold, bool
    ):
        raise OrchestratorDecisionServiceError(
            "must_be_float", field="low_confidence_threshold"
        )
    if not math.isfinite(low_confidence_threshold):
        raise OrchestratorDecisionServiceError(
            "must_be_finite", field="low_confidence_threshold"
        )
    if not 0.0 <= low_confidence_threshold <= 1.0:
        raise OrchestratorDecisionServiceError(
            "must_be_in_unit_interval", field="low_confidence_threshold"
        )
    if not callable(now_ms_clock):
        raise OrchestratorDecisionServiceError(
            "must_be_callable", field="now_ms_clock"
        )

    now_ms = now_ms_clock()
    if type(now_ms) is not int:
        raise OrchestratorDecisionServiceError("must_be_int", field="now_ms_clock")
    if now_ms < 0:
        raise OrchestratorDecisionServiceError(
            "must_be_nonnegative", field="now_ms_clock"
        )
    if len(prediction.prediction_id) > 124:
        raise OrchestratorDecisionServiceError(
            "prediction_id_too_long_for_decision_id_derivation",
            field="prediction.prediction_id",
        )

    decision_id = "dec_" + prediction.prediction_id
    if prediction.freshness_flag == PREDICTION_FRESHNESS_MISSING:
        decision_action = DECISION_ACTION_ABSTAIN
        decision_reason_code = DECISION_REASON_ABSTAIN_FRESHNESS_MISSING
    elif prediction.freshness_flag == PREDICTION_FRESHNESS_STALE:
        decision_action = DECISION_ACTION_ABSTAIN
        decision_reason_code = DECISION_REASON_ABSTAIN_FRESHNESS_STALE
    elif prediction.worker_health_status == "CRITICAL":
        decision_action = DECISION_ACTION_ABSTAIN
        decision_reason_code = DECISION_REASON_ABSTAIN_WORKER_CRITICAL
    elif prediction.worker_health_status == "DEGRADED":
        decision_action = DECISION_ACTION_ABSTAIN
        decision_reason_code = DECISION_REASON_ABSTAIN_WORKER_DEGRADED
    elif prediction.worker_health_status == "UNKNOWN":
        decision_action = DECISION_ACTION_ABSTAIN
        decision_reason_code = DECISION_REASON_ABSTAIN_WORKER_UNKNOWN
    elif prediction.confidence_calibrated < low_confidence_threshold:
        decision_action = DECISION_ACTION_ABSTAIN
        decision_reason_code = DECISION_REASON_ABSTAIN_LOW_CONFIDENCE
    elif prediction.direction == PREDICTION_DIRECTION_FLAT:
        decision_action = DECISION_ACTION_HOLD
        decision_reason_code = DECISION_REASON_HOLD_FLAT_DIRECTION
    elif prediction.direction == PREDICTION_DIRECTION_LONG:
        decision_action = DECISION_ACTION_OPEN_LONG
        decision_reason_code = DECISION_REASON_PROCEED_LONG
    elif prediction.direction == PREDICTION_DIRECTION_SHORT:
        decision_action = DECISION_ACTION_OPEN_SHORT
        decision_reason_code = DECISION_REASON_PROCEED_SHORT

    return OrchestratorDecisionRecord(
        decision_id=decision_id,
        prediction_id=prediction.prediction_id,
        feature_snapshot_id=prediction.feature_snapshot_id,
        symbol=prediction.symbol,
        decision_ts_ms=now_ms,
        decision_action=decision_action,
        decision_reason_code=decision_reason_code,
        input_prediction_direction=prediction.direction,
        input_prediction_confidence_calibrated=prediction.confidence_calibrated,
        input_prediction_freshness_flag=prediction.freshness_flag,
        input_worker_health_status=prediction.worker_health_status,
        live_blocked=True,
    )
