from v2.backend.app.composition.trainer_worker_health import build_trainer_worker_health_evaluator
from v2.backend.app.composition.trainer_worker_health import runtime
from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
from v2.backend.app.domain.trainer_worker_health import (
    HEALTH_STATUS_HEALTHY,
    TrainerWorkerHealthSnapshot,
    TrainerWorkerHealthThresholds,
)


def test_evaluator_invokes_service_exactly_once_per_call(monkeypatch):
    first = LivenessSignalSnapshot(1, 2, 3, 4, True, 90, 91, 92, 93, 1, 1, False, 100)
    second = LivenessSignalSnapshot(1, 2, 3, 4, True, 91, 92, 93, 94, 1, 1, False, 101)
    thresholds = TrainerWorkerHealthThresholds(10, 20, 30, 40, 50, 60)
    sentinel = TrainerWorkerHealthSnapshot(HEALTH_STATUS_HEALTHY, (), first, 100)
    calls = {"count": 0}

    def fake(candidate, *, thresholds, now_ms_clock):
        calls["count"] += 1
        return sentinel

    monkeypatch.setattr(runtime, "evaluate_worker_health", fake)
    evaluator = build_trainer_worker_health_evaluator(thresholds=thresholds, now_ms_clock=lambda: 102)

    evaluator(first)
    evaluator(second)

    assert calls["count"] == 2
