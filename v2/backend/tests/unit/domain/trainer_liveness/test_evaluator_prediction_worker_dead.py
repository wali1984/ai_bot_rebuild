from __future__ import annotations

from dataclasses import replace

from v2.backend.app.domain.trainer_liveness import (
    LIVENESS_REASON_PREDICTION_WORKER_DEAD,
    LivenessSignalSnapshot,
    LivenessSLAConfig,
    evaluate_liveness,
)


def test_prediction_worker_dead_alerts_even_when_stream_growth_is_nonzero(
    healthy_snapshot: LivenessSignalSnapshot,
    liveness_sla: LivenessSLAConfig,
) -> None:
    alert = evaluate_liveness(
        replace(
            healthy_snapshot,
            prediction_worker_alive=False,
            prediction_stream_id_growth=4,
        ),
        liveness_sla,
        now_ms=10_100,
    )

    assert alert is not None
    assert alert.reasons == (LIVENESS_REASON_PREDICTION_WORKER_DEAD,)
