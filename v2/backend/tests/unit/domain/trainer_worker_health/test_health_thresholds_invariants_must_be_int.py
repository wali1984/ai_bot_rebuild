def test_health_thresholds_invariants_must_be_int() -> None:
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
        values = dict(base)
        values[field] = 1.0
        with pytest.raises(TrainerWorkerHealthDomainError) as exc:
            TrainerWorkerHealthThresholds(**values)
        assert exc.value.reason == "must_be_int"
        assert exc.value.field == field

    values = dict(base)
    values["prediction_age_degraded_ms"] = True
    with pytest.raises(TrainerWorkerHealthDomainError) as exc:
        TrainerWorkerHealthThresholds(**values)
    assert exc.value.reason == "must_be_int"
    assert exc.value.field == "prediction_age_degraded_ms"
