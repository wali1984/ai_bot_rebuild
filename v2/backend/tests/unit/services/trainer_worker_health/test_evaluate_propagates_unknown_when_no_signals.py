def test_evaluate_propagates_unknown_when_no_signals() -> None:
    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import (
        HEALTH_REASON_NO_SIGNALS_OBSERVED,
        HEALTH_STATUS_UNKNOWN,
        TrainerWorkerHealthThresholds,
    )
    from v2.backend.app.services.trainer_worker_health import evaluate_worker_health

    snapshot = LivenessSignalSnapshot(None, None, None, None, False, None, None, None, None, 0, 0, False, 0)
    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)

    result = evaluate_worker_health(snapshot, thresholds=thresholds, now_ms_clock=lambda: 1000)

    assert result.status == HEALTH_STATUS_UNKNOWN
    assert result.reasons == (HEALTH_REASON_NO_SIGNALS_OBSERVED,)
    assert result.observation_ts_ms == snapshot.observation_ts_ms
    assert result.signal_snapshot is snapshot
