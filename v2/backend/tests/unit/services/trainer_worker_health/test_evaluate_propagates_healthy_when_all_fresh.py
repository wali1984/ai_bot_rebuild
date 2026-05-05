def test_evaluate_propagates_healthy_when_all_fresh() -> None:
    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import (
        HEALTH_STATUS_HEALTHY,
        TrainerWorkerHealthThresholds,
    )
    from v2.backend.app.services.trainer_worker_health import evaluate_worker_health

    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)

    result = evaluate_worker_health(snapshot, thresholds=thresholds, now_ms_clock=lambda: 1000)

    assert result.status == HEALTH_STATUS_HEALTHY
    assert result.reasons == ()
    assert result.observation_ts_ms == snapshot.observation_ts_ms
    assert result.signal_snapshot is snapshot
