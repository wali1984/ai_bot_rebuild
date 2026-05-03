from __future__ import annotations

from dataclasses import dataclass

from .errors import LivenessDomainError


def _ensure_optional_nonnegative(value: int | None, field: str) -> None:
    if value is not None and value < 0:
        raise LivenessDomainError("must_be_nonnegative", field=field)


def _ensure_optional_positive(value: int | None, field: str) -> None:
    if value is not None and value <= 0:
        raise LivenessDomainError("must_be_positive", field=field)


@dataclass(frozen=True, slots=True)
class LivenessSignalSnapshot:
    trainer_pid: int | None
    trainer_rss_bytes: int | None
    trainer_heartbeat_ts_ms: int | None
    prediction_worker_pid: int | None
    prediction_worker_alive: bool
    last_prediction_ts_ms: int | None
    last_gpu_batch_ts_ms: int | None
    # Captured for lineage/explainability; alpha liveness does not alert on deconflict freshness.
    last_deconflict_ts_ms: int | None
    last_proposal_ts_ms: int | None
    prediction_stream_id_growth: int
    proposal_stream_id_growth: int
    fatal_log_signature_observed: bool
    observation_ts_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.prediction_worker_alive, bool):
            raise LivenessDomainError("must_be_bool", field="prediction_worker_alive")
        if not isinstance(self.fatal_log_signature_observed, bool):
            raise LivenessDomainError("must_be_bool", field="fatal_log_signature_observed")
        if self.observation_ts_ms < 0:
            raise LivenessDomainError("must_be_nonnegative", field="observation_ts_ms")
        if self.prediction_stream_id_growth < 0:
            raise LivenessDomainError("must_be_nonnegative", field="prediction_stream_id_growth")
        if self.proposal_stream_id_growth < 0:
            raise LivenessDomainError("must_be_nonnegative", field="proposal_stream_id_growth")

        _ensure_optional_positive(self.trainer_pid, "trainer_pid")
        _ensure_optional_positive(self.prediction_worker_pid, "prediction_worker_pid")
        _ensure_optional_nonnegative(self.trainer_rss_bytes, "trainer_rss_bytes")
        _ensure_optional_nonnegative(self.trainer_heartbeat_ts_ms, "trainer_heartbeat_ts_ms")
        _ensure_optional_nonnegative(self.last_prediction_ts_ms, "last_prediction_ts_ms")
        _ensure_optional_nonnegative(self.last_gpu_batch_ts_ms, "last_gpu_batch_ts_ms")
        _ensure_optional_nonnegative(self.last_deconflict_ts_ms, "last_deconflict_ts_ms")
        _ensure_optional_nonnegative(self.last_proposal_ts_ms, "last_proposal_ts_ms")

        if self.trainer_pid is None and self.trainer_rss_bytes is not None:
            raise LivenessDomainError("rss_requires_trainer_pid", field="trainer_rss_bytes")
        if self.prediction_worker_pid is None and self.prediction_worker_alive is True:
            raise LivenessDomainError("alive_requires_worker_pid", field="prediction_worker_alive")
