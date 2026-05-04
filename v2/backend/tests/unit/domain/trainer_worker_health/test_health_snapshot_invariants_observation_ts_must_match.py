def test_health_snapshot_invariants_observation_ts_must_match() -> None:
    import pytest

    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import HEALTH_STATUS_HEALTHY, TrainerWorkerHealthDomainError, TrainerWorkerHealthSnapshot

    signal_snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    with pytest.raises(TrainerWorkerHealthDomainError) as exc:
        TrainerWorkerHealthSnapshot(HEALTH_STATUS_HEALTHY, (), signal_snapshot, 999)
    assert exc.value.reason == "must_match_snapshot"
    assert exc.value.field == "observation_ts_ms"
