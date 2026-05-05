def test_returns_callable_evaluator() -> None:
    from v2.backend.app.composition.orchestrator_decision import (
        build_orchestrator_decision_evaluator,
    )

    clock = lambda: 123
    evaluator = build_orchestrator_decision_evaluator(
        low_confidence_threshold=0.5, now_ms_clock=clock
    )

    assert callable(evaluator)
    assert evaluator is not clock
