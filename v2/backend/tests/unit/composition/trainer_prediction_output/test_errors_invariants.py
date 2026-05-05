def test_errors_invariants() -> None:
    from v2.backend.app.composition.trainer_prediction_output import (
        TrainerPredictionOutputCompositionError,
    )

    with_field = TrainerPredictionOutputCompositionError("some_code", field="some_field")
    assert with_field.code == "some_code"
    assert with_field.field == "some_field"
    assert str(with_field) == "some_code (some_field)"

    without_field = TrainerPredictionOutputCompositionError("some_code", field=None)
    assert str(without_field) == "some_code"
