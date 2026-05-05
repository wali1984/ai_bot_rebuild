def test_evaluate_rejects_clock_returning_negative_int() -> None:
    import pytest

    from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
    from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthThresholds
    from v2.backend.app.services.trainer_worker_health import (
        TrainerWorkerHealthServiceError,
        evaluate_worker_health,
    )

    snapshot = LivenessSignalSnapshot(None, None, None, None, False, None, None, None, None, 0, 0, False, 0)
    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)

    with pytest.raises(TrainerWorkerHealthServiceError) as raised:
        evaluate_worker_health(snapshot, thresholds=thresholds, now_ms_clock=lambda: -1)

    assert raised.value.code == "must_be_nonnegative"
    assert raised.value.field == "now_ms_clock"
