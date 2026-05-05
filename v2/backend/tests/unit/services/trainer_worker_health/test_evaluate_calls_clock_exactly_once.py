def test_evaluate_calls_clock_exactly_once() -> None:
    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthThresholds
    from v2.backend.app.services.trainer_worker_health import evaluate_worker_health

    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)
    calls = {"count": 0}

    def clock() -> int:
        calls["count"] += 1
        return 1000

    evaluate_worker_health(snapshot, thresholds=thresholds, now_ms_clock=clock)

    assert calls["count"] == 1
