def test_health_snapshot_invariants_status_in_allowed() -> None:
    import pytest

    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthDomainError, TrainerWorkerHealthSnapshot

    signal_snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    with pytest.raises(TrainerWorkerHealthDomainError) as exc:
        TrainerWorkerHealthSnapshot("INVALID", (), signal_snapshot, 1000)
    assert exc.value.reason == "invalid_status"
    assert exc.value.field == "status"
