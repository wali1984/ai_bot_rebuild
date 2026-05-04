def test_evaluator_critical_proposal_age() -> None:
    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import (
        HEALTH_REASON_PROPOSAL_AGE_CRITICAL,
        HEALTH_STATUS_CRITICAL,
        TrainerWorkerHealthThresholds,
        evaluate_trainer_worker_health,
    )

    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)
    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 799, 5, 5, False, 1000)
    result = evaluate_trainer_worker_health(snapshot, thresholds, 1000)

    assert result.status == HEALTH_STATUS_CRITICAL
    assert result.reasons == (HEALTH_REASON_PROPOSAL_AGE_CRITICAL,)
