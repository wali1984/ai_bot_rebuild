def test_health_snapshot_invariants_unknown_requires_no_signals_reason() -> None:
    import pytest

    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import (
        HEALTH_REASON_PREDICTION_WORKER_DEAD,
        HEALTH_STATUS_UNKNOWN,
        TrainerWorkerHealthDomainError,
        TrainerWorkerHealthSnapshot,
    )

    signal_snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    with pytest.raises(TrainerWorkerHealthDomainError) as exc:
        TrainerWorkerHealthSnapshot(HEALTH_STATUS_UNKNOWN, (HEALTH_REASON_PREDICTION_WORKER_DEAD,), signal_snapshot, 1000)
    assert exc.value.reason == "unknown_requires_no_signals_reason"
    assert exc.value.field == "reasons"
