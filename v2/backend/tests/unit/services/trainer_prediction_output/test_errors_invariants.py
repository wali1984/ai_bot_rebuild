from v2.backend.app.services.trainer_prediction_output import (
    TrainerPredictionOutputServiceError,
)


def test_errors_invariants() -> None:
    error = TrainerPredictionOutputServiceError("some_code", field="some_field")

    assert error.code == "some_code"
    assert error.field == "some_field"
    assert str(error) == "some_code (some_field)"
    assert repr(error) == (
        "TrainerPredictionOutputServiceError(code='some_code', field='some_field')"
    )
