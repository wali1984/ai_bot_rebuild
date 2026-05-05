import pytest


def test_validates_now_ms_clock_callable() -> None:
    from v2.backend.app.composition.trainer_prediction_output import (
        TrainerPredictionOutputCompositionError,
        build_trainer_prediction_output_evaluator,
    )

    for bad_clock in (42, None):
        with pytest.raises(TrainerPredictionOutputCompositionError) as exc_info:
            build_trainer_prediction_output_evaluator(now_ms_clock=bad_clock)
        assert exc_info.value.code == "must_be_callable"
        assert exc_info.value.field == "now_ms_clock"
