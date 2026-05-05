import pytest

from v2.backend.app.composition.trainer_worker_health import build_trainer_worker_health_evaluator
from v2.backend.app.composition.trainer_worker_health import runtime
from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthThresholds
from v2.backend.app.services.trainer_worker_health import TrainerWorkerHealthServiceError


def test_evaluator_propagates_service_error(monkeypatch):
    snapshot = LivenessSignalSnapshot(1, 2, 3, 4, True, 90, 91, 92, 93, 1, 1, False, 100)
    thresholds = TrainerWorkerHealthThresholds(10, 20, 30, 40, 50, 60)

    def fake(candidate, *, thresholds, now_ms_clock):
        raise TrainerWorkerHealthServiceError("forced", field="snapshot")

    monkeypatch.setattr(runtime, "evaluate_worker_health", fake)
    evaluator = build_trainer_worker_health_evaluator(thresholds=thresholds, now_ms_clock=lambda: 101)

    with pytest.raises(TrainerWorkerHealthServiceError) as caught:
        evaluator(snapshot)

    assert caught.value.code == "forced"
    assert caught.value.field == "snapshot"
