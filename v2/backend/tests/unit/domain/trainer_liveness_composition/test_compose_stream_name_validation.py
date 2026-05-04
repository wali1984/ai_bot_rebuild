from __future__ import annotations

import pytest

from v2.backend.app.domain.trainer_liveness_composition import (
    LivenessSnapshotBaseInputs,
    TrainerLivenessCompositionError,
    compose_liveness_snapshot_with_growth,
)
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig


def base_inputs() -> LivenessSnapshotBaseInputs:
    return LivenessSnapshotBaseInputs(
        trainer_pid=101,
        trainer_rss_bytes=4096,
        trainer_heartbeat_ts_ms=900,
        prediction_worker_pid=202,
        prediction_worker_alive=True,
        last_prediction_ts_ms=910,
        last_gpu_batch_ts_ms=920,
        last_deconflict_ts_ms=930,
        last_proposal_ts_ms=940,
        fatal_log_signature_observed=False,
        observation_ts_ms=1000,
    )


def config() -> GrowthWindowConfig:
    return GrowthWindowConfig(window_ms=100)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prediction_stream_name", ""),
        ("prediction_stream_name", 1),
        ("proposal_stream_name", ""),
        ("proposal_stream_name", 1),
    ],
)
def test_compose_rejects_invalid_stream_names(field: str, value: object) -> None:
    kwargs = {
        "prediction_observations": (),
        "proposal_observations": (),
        "growth_config": config(),
        "now_ms": 1000,
        "prediction_stream_name": "prediction",
        "proposal_stream_name": "proposal",
    }
    kwargs[field] = value
    with pytest.raises(TrainerLivenessCompositionError, match=field):
        compose_liveness_snapshot_with_growth(base_inputs(), **kwargs)  # type: ignore[arg-type]
