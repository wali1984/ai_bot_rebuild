import pytest


def test_evaluator_keyword_only_params() -> None:
    from v2.backend.app.composition.trainer_prediction_output import (
        build_trainer_prediction_output_evaluator,
    )

    evaluator = build_trainer_prediction_output_evaluator(now_ms_clock=lambda: 123)

    with pytest.raises(TypeError):
        evaluator("pred_1")
