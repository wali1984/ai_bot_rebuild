def test_evaluate_returns_worker_health_snapshot() -> None:
    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import (
        TrainerWorkerHealthSnapshot,
        TrainerWorkerHealthThresholds,
    )
    from v2.backend.app.services.trainer_worker_health import evaluate_worker_health

    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)

    result = evaluate_worker_health(snapshot, thresholds=thresholds, now_ms_clock=lambda: 1000)

    assert isinstance(result, TrainerWorkerHealthSnapshot)
