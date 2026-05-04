def test_evaluator_does_not_mutate_inputs() -> None:
    from dataclasses import asdict

    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthThresholds, evaluate_trainer_worker_health

    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)
    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    snapshot_id = id(snapshot)
    thresholds_id = id(thresholds)
    snapshot_fields = asdict(snapshot)
    threshold_fields = asdict(thresholds)

    evaluate_trainer_worker_health(snapshot, thresholds, 1000)

    assert id(snapshot) == snapshot_id
    assert id(thresholds) == thresholds_id
    assert asdict(snapshot) == snapshot_fields
    assert asdict(thresholds) == threshold_fields
