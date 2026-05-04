def test_health_thresholds_invariants_must_be_at_least_one() -> None:
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
    for field in base:
        for bad_value in (0, -1):
            values = dict(base)
            values[field] = bad_value
            with pytest.raises(TrainerWorkerHealthDomainError) as exc:
                TrainerWorkerHealthThresholds(**values)
            assert exc.value.reason == "must_be_at_least_one"
            assert exc.value.field == field
