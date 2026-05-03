from __future__ import annotations

from dataclasses import replace

from v2.backend.app.domain.trainer_liveness import (
    LivenessSignalSnapshot,
    LivenessSLAConfig,
    evaluate_liveness,
)


def test_healthy_snapshot_returns_no_alert(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    assert evaluate_liveness(healthy_snapshot, liveness_sla, now_ms=10_100) is None


def test_never_emitted_snapshot_with_growth_returns_no_alert(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    snapshot = replace(
        healthy_snapshot,
        last_prediction_ts_ms=None,
        last_gpu_batch_ts_ms=None,
        last_proposal_ts_ms=None,
        prediction_stream_id_growth=3,
    )

    assert evaluate_liveness(snapshot, liveness_sla, now_ms=20_000) is None


def test_zero_growth_with_unknown_rss_returns_no_alert(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    snapshot = replace(
        healthy_snapshot,
        trainer_rss_bytes=None,
        prediction_stream_id_growth=0,
    )

    assert evaluate_liveness(snapshot, liveness_sla, now_ms=10_100) is None
