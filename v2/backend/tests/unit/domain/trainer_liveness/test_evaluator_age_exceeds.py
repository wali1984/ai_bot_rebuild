from __future__ import annotations

from dataclasses import replace

from v2.backend.app.domain.trainer_liveness import (
    LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA,
    LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,
    LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA,
    LivenessSignalSnapshot,
    LivenessSLAConfig,
    evaluate_liveness,
)


def test_prediction_age_exceeds_sla(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    alert = evaluate_liveness(
        replace(healthy_snapshot, last_prediction_ts_ms=9_000),
        liveness_sla,
        now_ms=10_100,
    )

    assert alert is not None
    assert LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA in alert.reasons


def test_gpu_batch_age_exceeds_sla(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    alert = evaluate_liveness(
        replace(healthy_snapshot, last_gpu_batch_ts_ms=9_000),
        liveness_sla,
        now_ms=10_100,
    )

    assert alert is not None
    assert LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA in alert.reasons


def test_proposal_age_exceeds_sla(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    alert = evaluate_liveness(
        replace(healthy_snapshot, last_proposal_ts_ms=9_000),
        liveness_sla,
        now_ms=10_100,
    )

    assert alert is not None
    assert LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA in alert.reasons
