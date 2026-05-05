def test_errors_invariants() -> None:
    from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionDomainError

    plain = TrainerPredictionDomainError("bad")
    fielded = TrainerPredictionDomainError("bad", field="field_a")

    assert isinstance(plain, ValueError)
    assert plain.reason == "bad"
    assert plain.field is None
    assert str(plain) == "bad"
    assert fielded.reason == "bad"
    assert fielded.field == "field_a"
    assert str(fielded) == "field_a: bad"
