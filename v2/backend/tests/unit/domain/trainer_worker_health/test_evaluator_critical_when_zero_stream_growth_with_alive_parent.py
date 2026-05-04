def test_evaluator_critical_when_zero_stream_growth_with_alive_parent() -> None:
    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import (
        HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH,
        HEALTH_STATUS_CRITICAL,
        TrainerWorkerHealthThresholds,
        evaluate_trainer_worker_health,
    )

    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)
    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 0, 5, False, 1000)
    result = evaluate_trainer_worker_health(snapshot, thresholds, 1000)

    assert result.status == HEALTH_STATUS_CRITICAL
    assert result.reasons == (HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH,)
