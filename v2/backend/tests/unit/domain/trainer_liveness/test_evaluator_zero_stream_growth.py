from __future__ import annotations

from dataclasses import replace

from v2.backend.app.domain.trainer_liveness import (
    LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH,
    LivenessSignalSnapshot,
    LivenessSLAConfig,
    evaluate_liveness,
)


def test_zero_prediction_stream_growth_alerts_when_trainer_process_is_alive(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    alert = evaluate_liveness(
        replace(healthy_snapshot, prediction_stream_id_growth=0),
        liveness_sla,
        now_ms=10_100,
    )

    assert alert is not None
    assert LIVENESS_REASON_PREDICTION_STREAM_ZERO_GROWTH in alert.reasons


def test_zero_prediction_stream_growth_without_process_evidence_does_not_alert(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    alert = evaluate_liveness(
        replace(
            healthy_snapshot,
            trainer_pid=None,
            trainer_rss_bytes=None,
            prediction_stream_id_growth=0,
        ),
        liveness_sla,
        now_ms=10_100,
    )

    assert alert is None
