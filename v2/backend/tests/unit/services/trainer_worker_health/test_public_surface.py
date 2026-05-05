def test_public_surface() -> None:
    from v2.backend.app.services import trainer_worker_health

    assert trainer_worker_health.__all__ == (
        "evaluate_worker_health",
        "TrainerWorkerHealthServiceError",
    )
    assert callable(trainer_worker_health.evaluate_worker_health)
    assert isinstance(trainer_worker_health.TrainerWorkerHealthServiceError, type)
    assert issubclass(trainer_worker_health.TrainerWorkerHealthServiceError, ValueError)
