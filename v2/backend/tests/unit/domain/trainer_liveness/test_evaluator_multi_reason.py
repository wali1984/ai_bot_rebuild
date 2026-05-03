from __future__ import annotations

from dataclasses import replace

from v2.backend.app.domain.trainer_liveness import (
    LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
    LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA,
    LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,
    LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH,
    LIVENESS_REASON_PREDICTION_WORKER_DEAD,
    LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA,
    LivenessSignalSnapshot,
    LivenessSLAConfig,
    evaluate_liveness,
)


def test_evaluator_collects_multiple_liveness_reasons(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    alert = evaluate_liveness(
        replace(
            healthy_snapshot,
            last_prediction_ts_ms=8_000,
            last_gpu_batch_ts_ms=8_000,
            last_proposal_ts_ms=8_000,
            prediction_worker_alive=False,
            prediction_stream_id_growth=0,
            fatal_log_signature_observed=True,
        ),
        liveness_sla,
        now_ms=10_100,
    )

    assert alert is not None
    assert alert.reasons == (
        LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,
        LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA,
        LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA,
        LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH,
        LIVENESS_REASON_PREDICTION_WORKER_DEAD,
        LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
    )


def test_evaluator_preserves_order_for_reason_subset(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    alert = evaluate_liveness(
        replace(
            healthy_snapshot,
            last_prediction_ts_ms=8_000,
            prediction_stream_id_growth=0,
            fatal_log_signature_observed=True,
        ),
        liveness_sla,
        now_ms=10_100,
    )

    assert alert is not None
    assert alert.reasons == (
        LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,
        LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH,
        LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
    )
