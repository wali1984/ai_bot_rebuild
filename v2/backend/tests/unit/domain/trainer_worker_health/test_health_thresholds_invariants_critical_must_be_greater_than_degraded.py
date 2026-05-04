def test_health_thresholds_invariants_critical_must_be_greater_than_degraded() -> None:
    import pytest

    from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthDomainError, TrainerWorkerHealthThresholds

    base = {
        "prediction_age_degraded_ms": 100,
        "prediction_age_critical_ms": 200,
        "gpu_batch_age_degraded_ms": 100,
        "gpu_batch_age_critical_ms": 200,
        "proposal_age_degraded_ms": 100,
        "proposal_age_critical_ms": 200,
    }
    for degraded_field, critical_field in (
        ("prediction_age_degraded_ms", "prediction_age_critical_ms"),
        ("gpu_batch_age_degraded_ms", "gpu_batch_age_critical_ms"),
        ("proposal_age_degraded_ms", "proposal_age_critical_ms"),
    ):
        for degraded_value, critical_value in ((100, 100), (101, 100)):
            values = dict(base)
            values[degraded_field] = degraded_value
            values[critical_field] = critical_value
            with pytest.raises(TrainerWorkerHealthDomainError) as exc:
                TrainerWorkerHealthThresholds(**values)
            assert exc.value.reason == "critical_must_be_greater_than_degraded"
            assert exc.value.field == critical_field
