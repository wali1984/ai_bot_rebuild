from __future__ import annotations

from .alert import (
    LIVENESS_ALERT_CODE,
    LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
    LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA,
    LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,
    LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH,
    LIVENESS_REASON_PREDICTION_WORKER_DEAD,
    LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA,
    LivenessAlert,
)
from .errors import LivenessDomainError
from .signal_snapshot import LivenessSignalSnapshot
from .sla_config import LivenessSLAConfig


def evaluate_liveness(
    snapshot: LivenessSignalSnapshot,
    sla: LivenessSLAConfig,
    now_ms: int,
) -> LivenessAlert | None:
    if now_ms < 0:
        raise LivenessDomainError("must_be_nonnegative", field="now_ms")
    if now_ms < snapshot.observation_ts_ms:
        raise LivenessDomainError("now_before_observation", field="now_before_observation")

    reasons: list[str] = []

    if (
        snapshot.last_prediction_ts_ms is not None
        and now_ms - snapshot.last_prediction_ts_ms > sla.prediction_age_max_ms
    ):
        reasons.append(LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA)

    if (
        snapshot.last_gpu_batch_ts_ms is not None
        and now_ms - snapshot.last_gpu_batch_ts_ms > sla.gpu_batch_age_max_ms
    ):
        reasons.append(LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA)

    if (
        snapshot.last_proposal_ts_ms is not None
        and now_ms - snapshot.last_proposal_ts_ms > sla.proposal_age_max_ms
    ):
        reasons.append(LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA)

    if (
        snapshot.prediction_stream_id_growth == 0
        and snapshot.trainer_pid is not None
        and snapshot.trainer_rss_bytes is not None
        and snapshot.trainer_rss_bytes > 0
    ):
        reasons.append(LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH)

    if snapshot.prediction_worker_alive is False:
        reasons.append(LIVENESS_REASON_PREDICTION_WORKER_DEAD)

    if snapshot.fatal_log_signature_observed is True:
        reasons.append(LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED)

    if not reasons:
        return None

    return LivenessAlert(
        alert_code=LIVENESS_ALERT_CODE,
        reasons=tuple(reasons),
        observation_ts_ms=snapshot.observation_ts_ms,
        snapshot=snapshot,
    )
