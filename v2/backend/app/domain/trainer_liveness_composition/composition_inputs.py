from __future__ import annotations

from dataclasses import dataclass

from .errors import TrainerLivenessCompositionError


@dataclass(frozen=True, slots=True)
class LivenessSnapshotBaseInputs:
    trainer_pid: int | None
    trainer_rss_bytes: int | None
    trainer_heartbeat_ts_ms: int | None
    prediction_worker_pid: int | None
    prediction_worker_alive: bool
    last_prediction_ts_ms: int | None
    last_gpu_batch_ts_ms: int | None
    last_deconflict_ts_ms: int | None
    last_proposal_ts_ms: int | None
    fatal_log_signature_observed: bool
    observation_ts_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.prediction_worker_alive, bool):
            raise TrainerLivenessCompositionError("must_be_bool", field="prediction_worker_alive")
        if not isinstance(self.fatal_log_signature_observed, bool):
            raise TrainerLivenessCompositionError(
                "must_be_bool",
                field="fatal_log_signature_observed",
            )
        if type(self.observation_ts_ms) is not int:
            raise TrainerLivenessCompositionError("must_be_int", field="observation_ts_ms")
        if self.observation_ts_ms < 0:
            raise TrainerLivenessCompositionError(
                "must_be_nonnegative",
                field="observation_ts_ms",
            )
