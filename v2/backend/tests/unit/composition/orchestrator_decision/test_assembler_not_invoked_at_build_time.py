def test_assembler_not_invoked_at_build_time() -> None:
    from v2.backend.app.composition.orchestrator_decision import (
        build_orchestrator_decision_evaluator,
    )

    calls = [0]

    def clock() -> int:
        calls[0] += 1
        return 123

    build_orchestrator_decision_evaluator(
        low_confidence_threshold=0.5, now_ms_clock=clock
    )

    assert calls == [0]
