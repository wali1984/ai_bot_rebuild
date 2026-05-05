import pytest


def test_validates_low_confidence_threshold_not_finite() -> None:
    from v2.backend.app.composition.orchestrator_decision import (
        OrchestratorDecisionCompositionError,
        build_orchestrator_decision_evaluator,
    )

    for value in (float("inf"), float("nan"), float("-inf")):
        with pytest.raises(OrchestratorDecisionCompositionError) as exc:
            build_orchestrator_decision_evaluator(
                low_confidence_threshold=value, now_ms_clock=lambda: 0
            )
        assert exc.value.code == "must_be_finite"
        assert exc.value.field == "low_confidence_threshold"
