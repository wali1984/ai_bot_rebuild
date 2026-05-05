def test_assembler_not_invoked_at_build_time() -> None:
    from v2.backend.app.composition.trainer_prediction_output import (
        build_trainer_prediction_output_evaluator,
    )

    calls = [0]

    def clock() -> int:
        calls[0] += 1
        return 123

    evaluator = build_trainer_prediction_output_evaluator(now_ms_clock=clock)

    assert callable(evaluator)
    assert calls == [0]
