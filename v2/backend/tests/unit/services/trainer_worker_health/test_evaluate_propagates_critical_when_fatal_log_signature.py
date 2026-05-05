def test_evaluate_propagates_critical_when_fatal_log_signature() -> None:
    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import (
        HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
        HEALTH_STATUS_CRITICAL,
        TrainerWorkerHealthThresholds,
    )
    from v2.backend.app.services.trainer_worker_health import evaluate_worker_health

    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, True, 1000)
    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)

    result = evaluate_worker_health(snapshot, thresholds=thresholds, now_ms_clock=lambda: 1000)

    assert result.status == HEALTH_STATUS_CRITICAL
    assert HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED in result.reasons
    assert result.observation_ts_ms == snapshot.observation_ts_ms
    assert result.signal_snapshot is snapshot
