from __future__ import annotations

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
