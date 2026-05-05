import pytest


def test_evaluator_propagates_service_error_for_non_record_prediction() -> None:
    from v2.backend.app.composition.orchestrator_decision import (
        build_orchestrator_decision_evaluator,
    )
    from v2.backend.app.services.orchestrator_decision import OrchestratorDecisionServiceError

    evaluator = build_orchestrator_decision_evaluator(
        low_confidence_threshold=0.5, now_ms_clock=lambda: 123
    )

    with pytest.raises(OrchestratorDecisionServiceError) as exc:
        evaluator(prediction="not a record")

    assert exc.value.code == "must_be_trainer_prediction_record"
    assert exc.value.field == "prediction"
