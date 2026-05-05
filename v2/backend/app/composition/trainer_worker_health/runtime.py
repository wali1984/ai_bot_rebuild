from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
from v2.backend.app.domain.trainer_worker_health import (
    TrainerWorkerHealthSnapshot,
    TrainerWorkerHealthThresholds,
)
from v2.backend.app.services.trainer_worker_health import evaluate_worker_health

from .errors import TrainerWorkerHealthCompositionError

TrainerWorkerHealthEvaluator = Callable[
    [LivenessSignalSnapshot],
    TrainerWorkerHealthSnapshot,
]


def build_trainer_worker_health_evaluator(
    *,
    thresholds: TrainerWorkerHealthThresholds,
    now_ms_clock: Callable[[], int],
) -> TrainerWorkerHealthEvaluator:
    if not isinstance(thresholds, TrainerWorkerHealthThresholds):
        raise TrainerWorkerHealthCompositionError(
            "must_be_worker_health_thresholds",
            field="thresholds",
        )
    if not callable(now_ms_clock):
        raise TrainerWorkerHealthCompositionError(
            "must_be_callable",
            field="now_ms_clock",
        )

    _thresholds = thresholds
    _now_ms_clock = now_ms_clock

    def _evaluator(snapshot: LivenessSignalSnapshot) -> TrainerWorkerHealthSnapshot:
        return evaluate_worker_health(
            snapshot,
            thresholds=_thresholds,
            now_ms_clock=_now_ms_clock,
        )

    return _evaluator
