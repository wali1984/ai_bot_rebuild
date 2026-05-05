from v2.backend.app.composition.trainer_worker_health import build_trainer_worker_health_evaluator
from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthThresholds


def test_returns_callable_evaluator():
    thresholds = TrainerWorkerHealthThresholds(
        prediction_age_degraded_ms=10,
        prediction_age_critical_ms=20,
        gpu_batch_age_degraded_ms=30,
        gpu_batch_age_critical_ms=40,
        proposal_age_degraded_ms=50,
        proposal_age_critical_ms=60,
    )

    evaluator = build_trainer_worker_health_evaluator(thresholds=thresholds, now_ms_clock=lambda: 1)

    assert callable(evaluator)
