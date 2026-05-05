from v2.backend.app.composition.trainer_worker_health import build_trainer_worker_health_evaluator
from v2.backend.app.composition.trainer_worker_health import runtime
from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
from v2.backend.app.domain.trainer_worker_health import (
    HEALTH_STATUS_HEALTHY,
    TrainerWorkerHealthSnapshot,
    TrainerWorkerHealthThresholds,
)


def test_evaluator_forwards_thresholds_to_service(monkeypatch):
    snapshot = LivenessSignalSnapshot(1, 2, 3, 4, True, 90, 91, 92, 93, 1, 1, False, 100)
    thresholds = TrainerWorkerHealthThresholds(11, 21, 31, 41, 51, 61)
    sentinel = TrainerWorkerHealthSnapshot(HEALTH_STATUS_HEALTHY, (), snapshot, 100)
    captured = {}

    def fake(candidate, *, thresholds, now_ms_clock):
        captured["thresholds"] = thresholds
        return sentinel

    monkeypatch.setattr(runtime, "evaluate_worker_health", fake)
    evaluator = build_trainer_worker_health_evaluator(thresholds=thresholds, now_ms_clock=lambda: 101)

    evaluator(snapshot)

    assert id(captured["thresholds"]) == id(thresholds)
