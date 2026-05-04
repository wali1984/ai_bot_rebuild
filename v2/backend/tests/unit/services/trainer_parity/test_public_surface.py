def test_public_surface():
    import v2.backend.app.services.trainer_parity as service

    assert service.__all__ == (
        "evaluate_trainer_liveness",
        "TrainerLivenessEvaluation",
        "TrainerParityServiceError",
    )
    assert callable(service.evaluate_trainer_liveness)
    assert isinstance(service.TrainerLivenessEvaluation, type)
    assert isinstance(service.TrainerParityServiceError, type)
