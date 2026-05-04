from __future__ import annotations

from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot

from .errors import TrainerWorkerHealthDomainError
from .health_snapshot import TrainerWorkerHealthSnapshot
from .health_status import (
    HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
    HEALTH_REASON_GPU_BATCH_AGE_CRITICAL,
    HEALTH_REASON_GPU_BATCH_AGE_DEGRADED,
    HEALTH_REASON_NO_SIGNALS_OBSERVED,
    HEALTH_REASON_PREDICTION_AGE_CRITICAL,
    HEALTH_REASON_PREDICTION_AGE_DEGRADED,
    HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH,
    HEALTH_REASON_PREDICTION_WORKER_DEAD,
    HEALTH_REASON_PROPOSAL_AGE_CRITICAL,
    HEALTH_REASON_PROPOSAL_AGE_DEGRADED,
    HEALTH_STATUS_CRITICAL,
    HEALTH_STATUS_DEGRADED,
    HEALTH_STATUS_HEALTHY,
    HEALTH_STATUS_UNKNOWN,
)
from .health_thresholds import TrainerWorkerHealthThresholds


def evaluate_trainer_worker_health(
    snapshot: LivenessSignalSnapshot,
    thresholds: TrainerWorkerHealthThresholds,
    now_ms: int,
) -> TrainerWorkerHealthSnapshot:
    if not isinstance(snapshot, LivenessSignalSnapshot):
        raise TrainerWorkerHealthDomainError("must_be_liveness_signal_snapshot", field="snapshot")
    if not isinstance(thresholds, TrainerWorkerHealthThresholds):
        raise TrainerWorkerHealthDomainError("must_be_worker_health_thresholds", field="thresholds")
    if type(now_ms) is not int:
        raise TrainerWorkerHealthDomainError("must_be_int", field="now_ms")
    if now_ms < 0:
        raise TrainerWorkerHealthDomainError("must_be_nonnegative", field="now_ms")
    if now_ms < snapshot.observation_ts_ms:
        raise TrainerWorkerHealthDomainError("now_before_observation", field="now_ms")

    no_signals = (
        snapshot.trainer_pid is None
        and snapshot.trainer_rss_bytes is None
        and snapshot.trainer_heartbeat_ts_ms is None
        and snapshot.prediction_worker_pid is None
        and snapshot.prediction_worker_alive is False
        and snapshot.last_prediction_ts_ms is None
        and snapshot.last_gpu_batch_ts_ms is None
        and snapshot.last_deconflict_ts_ms is None
        and snapshot.last_proposal_ts_ms is None
        and snapshot.prediction_stream_id_growth == 0
        and snapshot.proposal_stream_id_growth == 0
        and snapshot.fatal_log_signature_observed is False
    )
    if no_signals:
        return TrainerWorkerHealthSnapshot(
            status=HEALTH_STATUS_UNKNOWN,
            reasons=(HEALTH_REASON_NO_SIGNALS_OBSERVED,),
            signal_snapshot=snapshot,
            observation_ts_ms=snapshot.observation_ts_ms,
        )

    critical_reasons: list[str] = []
    if (
        snapshot.last_prediction_ts_ms is not None
        and now_ms - snapshot.last_prediction_ts_ms > thresholds.prediction_age_critical_ms
    ):
        critical_reasons.append(HEALTH_REASON_PREDICTION_AGE_CRITICAL)
    if (
        snapshot.last_gpu_batch_ts_ms is not None
        and now_ms - snapshot.last_gpu_batch_ts_ms > thresholds.gpu_batch_age_critical_ms
    ):
        critical_reasons.append(HEALTH_REASON_GPU_BATCH_AGE_CRITICAL)
    if (
        snapshot.last_proposal_ts_ms is not None
        and now_ms - snapshot.last_proposal_ts_ms > thresholds.proposal_age_critical_ms
    ):
        critical_reasons.append(HEALTH_REASON_PROPOSAL_AGE_CRITICAL)
    if (
        snapshot.prediction_stream_id_growth == 0
        and snapshot.trainer_pid is not None
        and snapshot.trainer_rss_bytes is not None
        and snapshot.trainer_rss_bytes > 0
    ):
        critical_reasons.append(HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH)
    if snapshot.prediction_worker_alive is False and snapshot.prediction_worker_pid is not None:
        critical_reasons.append(HEALTH_REASON_PREDICTION_WORKER_DEAD)
    if snapshot.fatal_log_signature_observed is True:
        critical_reasons.append(HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED)

    degraded_reasons: list[str] = []
    if (
        snapshot.last_prediction_ts_ms is not None
        and HEALTH_REASON_PREDICTION_AGE_CRITICAL not in critical_reasons
        and now_ms - snapshot.last_prediction_ts_ms > thresholds.prediction_age_degraded_ms
    ):
        degraded_reasons.append(HEALTH_REASON_PREDICTION_AGE_DEGRADED)
    if (
        snapshot.last_gpu_batch_ts_ms is not None
        and HEALTH_REASON_GPU_BATCH_AGE_CRITICAL not in critical_reasons
        and now_ms - snapshot.last_gpu_batch_ts_ms > thresholds.gpu_batch_age_degraded_ms
    ):
        degraded_reasons.append(HEALTH_REASON_GPU_BATCH_AGE_DEGRADED)
    if (
        snapshot.last_proposal_ts_ms is not None
        and HEALTH_REASON_PROPOSAL_AGE_CRITICAL not in critical_reasons
        and now_ms - snapshot.last_proposal_ts_ms > thresholds.proposal_age_degraded_ms
    ):
        degraded_reasons.append(HEALTH_REASON_PROPOSAL_AGE_DEGRADED)

    if len(critical_reasons) > 0:
        return TrainerWorkerHealthSnapshot(
            status=HEALTH_STATUS_CRITICAL,
            reasons=tuple(critical_reasons + degraded_reasons),
            signal_snapshot=snapshot,
            observation_ts_ms=snapshot.observation_ts_ms,
        )
    if len(degraded_reasons) > 0:
        return TrainerWorkerHealthSnapshot(
            status=HEALTH_STATUS_DEGRADED,
            reasons=tuple(degraded_reasons),
            signal_snapshot=snapshot,
            observation_ts_ms=snapshot.observation_ts_ms,
        )
    return TrainerWorkerHealthSnapshot(
        status=HEALTH_STATUS_HEALTHY,
        reasons=(),
        signal_snapshot=snapshot,
        observation_ts_ms=snapshot.observation_ts_ms,
    )
