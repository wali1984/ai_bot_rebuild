def test_public_surface() -> None:
    import v2.backend.app.domain.trainer_worker_health as package
    from v2.backend.app.domain.trainer_worker_health import errors, health_evaluator, health_snapshot, health_status, health_thresholds

    expected = (
        "TrainerWorkerHealthDomainError",
        "TrainerWorkerHealthThresholds",
        "TrainerWorkerHealthSnapshot",
        "evaluate_trainer_worker_health",
        "HEALTH_STATUS_HEALTHY",
        "HEALTH_STATUS_DEGRADED",
        "HEALTH_STATUS_CRITICAL",
        "HEALTH_STATUS_UNKNOWN",
        "HEALTH_REASON_PREDICTION_AGE_DEGRADED",
        "HEALTH_REASON_GPU_BATCH_AGE_DEGRADED",
        "HEALTH_REASON_PROPOSAL_AGE_DEGRADED",
        "HEALTH_REASON_PREDICTION_AGE_CRITICAL",
        "HEALTH_REASON_GPU_BATCH_AGE_CRITICAL",
        "HEALTH_REASON_PROPOSAL_AGE_CRITICAL",
        "HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH",
        "HEALTH_REASON_PREDICTION_WORKER_DEAD",
        "HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED",
        "HEALTH_REASON_NO_SIGNALS_OBSERVED",
    )
    assert package.__all__ == expected
    assert package.TrainerWorkerHealthDomainError is errors.TrainerWorkerHealthDomainError
    assert package.TrainerWorkerHealthThresholds is health_thresholds.TrainerWorkerHealthThresholds
    assert package.TrainerWorkerHealthSnapshot is health_snapshot.TrainerWorkerHealthSnapshot
    assert package.evaluate_trainer_worker_health is health_evaluator.evaluate_trainer_worker_health
    for name in expected[4:]:
        assert getattr(package, name) is getattr(health_status, name)
