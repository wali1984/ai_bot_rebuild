from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot
from v2.backend.app.domain.trainer_worker_health import (
    TrainerWorkerHealthSnapshot,
    TrainerWorkerHealthThresholds,
    evaluate_trainer_worker_health,
)

from .errors import TrainerWorkerHealthServiceError


def evaluate_worker_health(
    snapshot: LivenessSignalSnapshot,
    *,
    thresholds: TrainerWorkerHealthThresholds,
    now_ms_clock: Callable[[], int],
) -> TrainerWorkerHealthSnapshot:
    if not isinstance(snapshot, LivenessSignalSnapshot):
        raise TrainerWorkerHealthServiceError(
            "must_be_liveness_signal_snapshot",
            field="snapshot",
        )
    if not isinstance(thresholds, TrainerWorkerHealthThresholds):
        raise TrainerWorkerHealthServiceError(
            "must_be_worker_health_thresholds",
            field="thresholds",
        )
    if not callable(now_ms_clock):
        raise TrainerWorkerHealthServiceError("must_be_callable", field="now_ms_clock")

    now_ms = now_ms_clock()

    if type(now_ms) is not int:
        raise TrainerWorkerHealthServiceError("must_be_int", field="now_ms_clock")
    if now_ms < 0:
        raise TrainerWorkerHealthServiceError("must_be_nonnegative", field="now_ms_clock")
    if now_ms < snapshot.observation_ts_ms:
        raise TrainerWorkerHealthServiceError("now_before_observation", field="now_ms_clock")

    return evaluate_trainer_worker_health(snapshot, thresholds, now_ms)
