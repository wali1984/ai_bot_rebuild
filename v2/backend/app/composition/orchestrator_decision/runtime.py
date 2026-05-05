from __future__ import annotations

import math
from collections.abc import Callable

from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord
from v2.backend.app.services.orchestrator_decision import assemble_orchestrator_decision_record

from .errors import OrchestratorDecisionCompositionError

OrchestratorDecisionEvaluator = Callable[..., OrchestratorDecisionRecord]


def build_orchestrator_decision_evaluator(
    *,
    low_confidence_threshold: float,
    now_ms_clock: Callable[[], int],
) -> OrchestratorDecisionEvaluator:
    if not isinstance(low_confidence_threshold, float) or isinstance(
        low_confidence_threshold, bool
    ):
        raise OrchestratorDecisionCompositionError(
            "must_be_float", field="low_confidence_threshold"
        )
    if not math.isfinite(low_confidence_threshold):
        raise OrchestratorDecisionCompositionError(
            "must_be_finite", field="low_confidence_threshold"
        )
    if not 0.0 <= low_confidence_threshold <= 1.0:
        raise OrchestratorDecisionCompositionError(
            "must_be_in_unit_interval", field="low_confidence_threshold"
        )
    if not callable(now_ms_clock):
        raise OrchestratorDecisionCompositionError(
            "must_be_callable", field="now_ms_clock"
        )

    _low_confidence_threshold = low_confidence_threshold
    _now_ms_clock = now_ms_clock

    def _evaluator(
        *, prediction: TrainerPredictionRecord
    ) -> OrchestratorDecisionRecord:
        return assemble_orchestrator_decision_record(
            prediction=prediction,
            low_confidence_threshold=_low_confidence_threshold,
            now_ms_clock=_now_ms_clock,
        )

    return _evaluator
