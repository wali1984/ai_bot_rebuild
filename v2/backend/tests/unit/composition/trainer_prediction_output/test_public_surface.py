def test_public_surface() -> None:
    from v2.backend.app.composition import trainer_prediction_output

    assert trainer_prediction_output.__all__ == (
        "build_trainer_prediction_output_evaluator",
        "TrainerPredictionOutputEvaluator",
        "TrainerPredictionOutputCompositionError",
    )
    assert callable(trainer_prediction_output.build_trainer_prediction_output_evaluator)
    assert issubclass(trainer_prediction_output.TrainerPredictionOutputCompositionError, Exception)
    assert trainer_prediction_output.TrainerPredictionOutputEvaluator is not None
