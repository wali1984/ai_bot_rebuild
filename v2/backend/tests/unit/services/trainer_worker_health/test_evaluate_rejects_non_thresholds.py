def test_evaluate_rejects_non_thresholds() -> None:
    import pytest

    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.services.trainer_worker_health import (
        TrainerWorkerHealthServiceError,
        evaluate_worker_health,
    )

    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)

    with pytest.raises(TrainerWorkerHealthServiceError) as raised:
        evaluate_worker_health(snapshot, thresholds=object(), now_ms_clock=lambda: 1000)

    assert raised.value.code == "must_be_worker_health_thresholds"
    assert raised.value.field == "thresholds"
