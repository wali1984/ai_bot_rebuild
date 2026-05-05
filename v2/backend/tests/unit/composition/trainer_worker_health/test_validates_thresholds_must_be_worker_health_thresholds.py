import pytest

from v2.backend.app.composition.trainer_worker_health import (
    TrainerWorkerHealthCompositionError,
    build_trainer_worker_health_evaluator,
)


def test_validates_thresholds_must_be_worker_health_thresholds():
    with pytest.raises(TrainerWorkerHealthCompositionError) as caught:
        build_trainer_worker_health_evaluator(thresholds=object(), now_ms_clock=lambda: 1)

    assert caught.value.code == "must_be_worker_health_thresholds"
    assert caught.value.field == "thresholds"
