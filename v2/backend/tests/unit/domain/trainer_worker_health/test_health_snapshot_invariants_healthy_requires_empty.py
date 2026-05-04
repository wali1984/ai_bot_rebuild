def test_health_snapshot_invariants_healthy_requires_empty() -> None:
    import pytest

    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import (
        HEALTH_REASON_PREDICTION_WORKER_DEAD,
        HEALTH_STATUS_HEALTHY,
        TrainerWorkerHealthDomainError,
        TrainerWorkerHealthSnapshot,
    )

    signal_snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    with pytest.raises(TrainerWorkerHealthDomainError) as exc:
        TrainerWorkerHealthSnapshot(HEALTH_STATUS_HEALTHY, (HEALTH_REASON_PREDICTION_WORKER_DEAD,), signal_snapshot, 1000)
    assert exc.value.reason == "healthy_requires_empty_reasons"
    assert exc.value.field == "reasons"
