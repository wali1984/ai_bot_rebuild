import pytest

from v2.backend.app.services.orchestrator_decision import (
    OrchestratorDecisionServiceError,
    assemble_orchestrator_decision_record,
)


def test_assemble_rejects_prediction_not_record() -> None:
    for prediction in (object(), None):
        with pytest.raises(OrchestratorDecisionServiceError) as excinfo:
            assemble_orchestrator_decision_record(
                prediction=prediction,
                low_confidence_threshold=0.5,
                now_ms_clock=lambda: 1,
            )
        assert (excinfo.value.code, excinfo.value.field) == (
            "must_be_trainer_prediction_record",
            "prediction",
        )
