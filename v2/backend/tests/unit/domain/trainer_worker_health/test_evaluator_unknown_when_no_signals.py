def test_evaluator_unknown_when_no_signals() -> None:
    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import (
        HEALTH_REASON_NO_SIGNALS_OBSERVED,
        HEALTH_STATUS_UNKNOWN,
        TrainerWorkerHealthThresholds,
        evaluate_trainer_worker_health,
    )

    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)
    snapshot = LivenessSignalSnapshot(None, None, None, None, False, None, None, None, None, 0, 0, False, 0)
    result = evaluate_trainer_worker_health(snapshot, thresholds, 0)

    assert result.status == HEALTH_STATUS_UNKNOWN
    assert result.reasons == (HEALTH_REASON_NO_SIGNALS_OBSERVED,)
