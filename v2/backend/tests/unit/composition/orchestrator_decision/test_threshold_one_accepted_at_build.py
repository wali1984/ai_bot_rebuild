def test_threshold_one_accepted_at_build() -> None:
    from v2.backend.app.composition.orchestrator_decision import (
        build_orchestrator_decision_evaluator,
    )

    evaluator = build_orchestrator_decision_evaluator(
        low_confidence_threshold=1.0, now_ms_clock=lambda: 0
    )

    assert callable(evaluator)
