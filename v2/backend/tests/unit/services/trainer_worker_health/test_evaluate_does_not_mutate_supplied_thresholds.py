def test_evaluate_does_not_mutate_supplied_thresholds() -> None:
    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthThresholds
    from v2.backend.app.services.trainer_worker_health import evaluate_worker_health

    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)
    thresholds_id = id(thresholds)
    before = (
        thresholds.prediction_age_degraded_ms,
        thresholds.prediction_age_critical_ms,
        thresholds.gpu_batch_age_degraded_ms,
        thresholds.gpu_batch_age_critical_ms,
        thresholds.proposal_age_degraded_ms,
        thresholds.proposal_age_critical_ms,
    )

    evaluate_worker_health(snapshot, thresholds=thresholds, now_ms_clock=lambda: 1000)

    after = (
        thresholds.prediction_age_degraded_ms,
        thresholds.prediction_age_critical_ms,
        thresholds.gpu_batch_age_degraded_ms,
        thresholds.gpu_batch_age_critical_ms,
        thresholds.proposal_age_degraded_ms,
        thresholds.proposal_age_critical_ms,
    )
    assert id(thresholds) == thresholds_id
    assert after == before
