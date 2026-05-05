from v2.backend.app.composition.trainer_worker_health import build_trainer_worker_health_evaluator
from v2.backend.app.composition.trainer_worker_health import runtime
from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthThresholds


def test_service_not_invoked_at_build_time(monkeypatch):
    thresholds = TrainerWorkerHealthThresholds(10, 20, 30, 40, 50, 60)
    calls = {"count": 0}

    def fake(candidate, *, thresholds, now_ms_clock):
        calls["count"] += 1

    monkeypatch.setattr(runtime, "evaluate_worker_health", fake)
    build_trainer_worker_health_evaluator(thresholds=thresholds, now_ms_clock=lambda: 101)

    assert calls["count"] == 0
