from __future__ import annotations

from dataclasses import replace

import pytest

from v2.backend.app.domain.trainer_liveness import (
    LIVENESS_REASON_GPU_BATCH_AGE_EXCEEDS_SLA,
    LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,
    LIVENESS_REASON_PROPOSAL_AGE_EXCEEDS_SLA,
    LivenessDomainError,
    LivenessSignalSnapshot,
    LivenessSLAConfig,
    evaluate_liveness,
)


def test_prediction_age_equal_to_sla_does_not_alert(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    alert = evaluate_liveness(
        replace(healthy_snapshot, last_prediction_ts_ms=9_600),
        liveness_sla,
        now_ms=10_100,
    )

    assert alert is None


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


def test_missing_prediction_timestamp_does_not_trigger_prediction_age(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    alert = evaluate_liveness(
        replace(
            healthy_snapshot,
            last_prediction_ts_ms=None,
            last_gpu_batch_ts_ms=19_950,
            last_proposal_ts_ms=19_940,
        ),
        liveness_sla,
        now_ms=20_000,
    )

    assert alert is None


def test_now_before_observation_raises(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    with pytest.raises(LivenessDomainError, match="now_before_observation"):
        evaluate_liveness(healthy_snapshot, liveness_sla, now_ms=9_999)


def test_negative_now_raises(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    with pytest.raises(LivenessDomainError, match="now_ms"):
        evaluate_liveness(healthy_snapshot, liveness_sla, now_ms=-1)
