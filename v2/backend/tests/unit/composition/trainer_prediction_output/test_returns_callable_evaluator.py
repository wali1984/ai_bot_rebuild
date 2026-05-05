def test_returns_callable_evaluator() -> None:
    from v2.backend.app.composition.trainer_prediction_output import (
        build_trainer_prediction_output_evaluator,
    )

    clock = lambda: 123
    evaluator = build_trainer_prediction_output_evaluator(now_ms_clock=clock)
    assert callable(evaluator)
    assert evaluator is not clock
