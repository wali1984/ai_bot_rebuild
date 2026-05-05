import pytest


def test_validates_low_confidence_threshold_above_one() -> None:
    from v2.backend.app.composition.orchestrator_decision import (
        OrchestratorDecisionCompositionError,
        build_orchestrator_decision_evaluator,
    )

    with pytest.raises(OrchestratorDecisionCompositionError) as exc:
        build_orchestrator_decision_evaluator(
            low_confidence_threshold=1.0001, now_ms_clock=lambda: 0
        )
    assert exc.value.code == "must_be_in_unit_interval"
    assert exc.value.field == "low_confidence_threshold"
