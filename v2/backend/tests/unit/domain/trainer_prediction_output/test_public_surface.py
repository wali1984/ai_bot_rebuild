def test_public_surface() -> None:
    from v2.backend.app.domain import trainer_prediction_output as output

    assert output.__all__ == (
        "TrainerPredictionDomainError",
        "TrainerPredictionRecord",
        "PREDICTION_DIRECTION_LONG",
        "PREDICTION_DIRECTION_SHORT",
        "PREDICTION_DIRECTION_FLAT",
        "PREDICTION_FRESHNESS_FRESH",
        "PREDICTION_FRESHNESS_STALE",
        "PREDICTION_FRESHNESS_MISSING",
    )
    assert sorted(name for name in output.__dict__ if not name.startswith("__")) == [
        "PREDICTION_DIRECTION_FLAT",
        "PREDICTION_DIRECTION_LONG",
        "PREDICTION_DIRECTION_SHORT",
        "PREDICTION_FRESHNESS_FRESH",
        "PREDICTION_FRESHNESS_MISSING",
        "PREDICTION_FRESHNESS_STALE",
        "TrainerPredictionDomainError",
        "TrainerPredictionRecord",
    ]
