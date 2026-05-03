from __future__ import annotations

import pytest

from v2.backend.app.domain.trainer_liveness.alert import (
    LIVENESS_ALERT_CODE,
    LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
    LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,
    LivenessAlert,
)
from v2.backend.app.domain.trainer_liveness import LivenessDomainError, LivenessSignalSnapshot


def test_alert_accepts_known_reason(healthy_snapshot: LivenessSignalSnapshot) -> None:
    alert = LivenessAlert(
        alert_code=LIVENESS_ALERT_CODE,
        reasons=(LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,),
        observation_ts_ms=healthy_snapshot.observation_ts_ms,
        snapshot=healthy_snapshot,
    )

    assert alert.reasons == (LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,)


def test_alert_rejects_duplicate_reasons(healthy_snapshot: LivenessSignalSnapshot) -> None:
    with pytest.raises(LivenessDomainError, match="duplicate_reasons"):
        LivenessAlert(
            alert_code=LIVENESS_ALERT_CODE,
            reasons=(
                LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
                LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
            ),
            observation_ts_ms=healthy_snapshot.observation_ts_ms,
            snapshot=healthy_snapshot,
        )


def test_alert_rejects_unknown_reason(healthy_snapshot: LivenessSignalSnapshot) -> None:
    with pytest.raises(LivenessDomainError, match="unknown_reason"):
        LivenessAlert(
            alert_code=LIVENESS_ALERT_CODE,
            reasons=("unknown",),
            observation_ts_ms=healthy_snapshot.observation_ts_ms,
            snapshot=healthy_snapshot,
        )


def test_alert_rejects_observation_mismatch(healthy_snapshot: LivenessSignalSnapshot) -> None:
    with pytest.raises(LivenessDomainError, match="must_match_snapshot"):
        LivenessAlert(
            alert_code=LIVENESS_ALERT_CODE,
            reasons=(LIVENESS_REASON_PREDICTION_AGE_EXCEEDS_SLA,),
            observation_ts_ms=healthy_snapshot.observation_ts_ms + 1,
            snapshot=healthy_snapshot,
        )
