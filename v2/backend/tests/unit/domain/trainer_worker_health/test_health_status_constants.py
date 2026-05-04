def test_health_status_constants() -> None:
    from v2.backend.app.domain.trainer_worker_health import (
        HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
        HEALTH_REASON_GPU_BATCH_AGE_CRITICAL,
        HEALTH_REASON_GPU_BATCH_AGE_DEGRADED,
        HEALTH_REASON_NO_SIGNALS_OBSERVED,
        HEALTH_REASON_PREDICTION_AGE_CRITICAL,
        HEALTH_REASON_PREDICTION_AGE_DEGRADED,
        HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH,
        HEALTH_REASON_PREDICTION_WORKER_DEAD,
        HEALTH_REASON_PROPOSAL_AGE_CRITICAL,
        HEALTH_REASON_PROPOSAL_AGE_DEGRADED,
        HEALTH_STATUS_CRITICAL,
        HEALTH_STATUS_DEGRADED,
        HEALTH_STATUS_HEALTHY,
        HEALTH_STATUS_UNKNOWN,
    )

    statuses = (HEALTH_STATUS_HEALTHY, HEALTH_STATUS_DEGRADED, HEALTH_STATUS_CRITICAL, HEALTH_STATUS_UNKNOWN)
    reasons = (
        HEALTH_REASON_PREDICTION_AGE_DEGRADED,
        HEALTH_REASON_GPU_BATCH_AGE_DEGRADED,
        HEALTH_REASON_PROPOSAL_AGE_DEGRADED,
        HEALTH_REASON_PREDICTION_AGE_CRITICAL,
        HEALTH_REASON_GPU_BATCH_AGE_CRITICAL,
        HEALTH_REASON_PROPOSAL_AGE_CRITICAL,
        HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH,
        HEALTH_REASON_PREDICTION_WORKER_DEAD,
        HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
        HEALTH_REASON_NO_SIGNALS_OBSERVED,
    )

    assert statuses == ("HEALTHY", "DEGRADED", "CRITICAL", "UNKNOWN")
    assert reasons == (
        "prediction_age_degraded",
        "gpu_batch_age_degraded",
        "proposal_age_degraded",
        "prediction_age_critical",
        "gpu_batch_age_critical",
        "proposal_age_critical",
        "prediction_stream_zero_growth",
        "prediction_worker_dead",
        "fatal_log_signature_observed",
        "no_signals_observed",
    )
    assert len(set(statuses)) == 4
    assert len(set(reasons)) == 10
    assert set(statuses).isdisjoint(reasons)
