def test_evaluator_now_before_observation_rejected() -> None:
    import pytest

    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthDomainError, TrainerWorkerHealthThresholds, evaluate_trainer_worker_health

    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)
    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    with pytest.raises(TrainerWorkerHealthDomainError) as exc:
        evaluate_trainer_worker_health(snapshot, thresholds, 999)
    assert exc.value.reason == "now_before_observation"
    assert exc.value.field == "now_ms"
