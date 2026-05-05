def test_public_surface() -> None:
    import v2.backend.app.services.trainer_prediction_output as package

    assert package.__all__ == (
        "assemble_prediction_record",
        "TrainerPredictionOutputServiceError",
    )
    assert callable(package.assemble_prediction_record)
    assert isinstance(package.TrainerPredictionOutputServiceError, type)
    assert issubclass(package.TrainerPredictionOutputServiceError, ValueError)
