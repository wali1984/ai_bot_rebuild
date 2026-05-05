def test_evaluate_rejects_non_snapshot() -> None:
    import pytest

    from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthThresholds
    from v2.backend.app.services.trainer_worker_health import (
        TrainerWorkerHealthServiceError,
        evaluate_worker_health,
    )

    thresholds = TrainerWorkerHealthThresholds(100, 200, 100, 200, 100, 200)

    with pytest.raises(TrainerWorkerHealthServiceError) as raised:
        evaluate_worker_health(object(), thresholds=thresholds, now_ms_clock=lambda: 1000)

    assert raised.value.code == "must_be_liveness_signal_snapshot"
    assert raised.value.field == "snapshot"
