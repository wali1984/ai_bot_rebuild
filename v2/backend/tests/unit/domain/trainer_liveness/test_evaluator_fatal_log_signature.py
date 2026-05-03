from __future__ import annotations

from dataclasses import replace

from v2.backend.app.domain.trainer_liveness import (
    LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED,
    LivenessSignalSnapshot,
    LivenessSLAConfig,
    evaluate_liveness,
)


def test_fatal_log_signature_triggers_liveness_alert(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    alert = evaluate_liveness(
        replace(healthy_snapshot, fatal_log_signature_observed=True),
        liveness_sla,
        now_ms=10_100,
    )

    assert alert is not None
    assert LIVENESS_REASON_FATAL_LOG_SIGNATURE_OBSERVED in alert.reasons
