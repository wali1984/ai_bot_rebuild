import pytest

from v2.backend.app.composition.trainer_worker_health import (
    TrainerWorkerHealthCompositionError,
    build_trainer_worker_health_evaluator,
)
from v2.backend.app.domain.trainer_worker_health import TrainerWorkerHealthThresholds


def test_validates_now_ms_clock_callable():
    thresholds = TrainerWorkerHealthThresholds(
        prediction_age_degraded_ms=10,
        prediction_age_critical_ms=20,
        gpu_batch_age_degraded_ms=30,
        gpu_batch_age_critical_ms=40,
        proposal_age_degraded_ms=50,
        proposal_age_critical_ms=60,
    )

    with pytest.raises(TrainerWorkerHealthCompositionError) as caught:
        build_trainer_worker_health_evaluator(thresholds=thresholds, now_ms_clock=42)

    assert caught.value.code == "must_be_callable"
    assert caught.value.field == "now_ms_clock"
