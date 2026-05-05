import pytest


def test_validates_now_ms_clock_callable() -> None:
    from v2.backend.app.composition.orchestrator_decision import (
        OrchestratorDecisionCompositionError,
        build_orchestrator_decision_evaluator,
    )

    for value in (42, None):
        with pytest.raises(OrchestratorDecisionCompositionError) as exc:
            build_orchestrator_decision_evaluator(
                low_confidence_threshold=0.5, now_ms_clock=value
            )
        assert exc.value.code == "must_be_callable"
        assert exc.value.field == "now_ms_clock"
