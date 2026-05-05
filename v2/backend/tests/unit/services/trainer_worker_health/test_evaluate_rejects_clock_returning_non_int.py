def test_evaluate_rejects_clock_returning_non_int() -> None:
    import pytest

    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthThresholds
    from v2.backend.app.services.trainer_worker_health import (
        TrainerWorkerHealthServiceError,
        evaluate_worker_health,
    )

    snapshot = LivenessSignalSnapshot(123, 4096, 1000, 456, True, 1000, 1000, 1000, 1000, 5, 5, False, 1000)
    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)

    with pytest.raises(TrainerWorkerHealthServiceError) as raised:
        evaluate_worker_health(snapshot, thresholds=thresholds, now_ms_clock=lambda: "42")

    assert raised.value.code == "must_be_int"
    assert raised.value.field == "now_ms_clock"
