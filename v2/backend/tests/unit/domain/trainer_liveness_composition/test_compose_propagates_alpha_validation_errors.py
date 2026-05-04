from __future__ import annotations

import pytest

from v2.backend.app.domain.trainer_liveness import LivenessDomainError
from v2.backend.app.domain.trainer_liveness_composition import compose_liveness_snapshot_with_growth
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig


def base_inputs(**overrides: object) -> LivenessSnapshotBaseInputs:
    values = {
        "trainer_pid": 101,
        "trainer_rss_bytes": 4096,
        "trainer_heartbeat_ts_ms": 900,
        "prediction_worker_pid": 202,
        "prediction_worker_alive": True,
        "last_prediction_ts_ms": 910,
        "last_gpu_batch_ts_ms": 920,
        "last_deconflict_ts_ms": 930,
        "last_proposal_ts_ms": 940,
        "fatal_log_signature_observed": False,
        "observation_ts_ms": 1000,
    }
    values.update(overrides)
    return LivenessSnapshotBaseInputs(**values)


def config() -> GrowthWindowConfig:
    return GrowthWindowConfig(window_ms=100)


def test_compose_propagates_alpha_validation_errors() -> None:
    with pytest.raises(LivenessDomainError, match="trainer_rss_bytes"):
        compose_liveness_snapshot_with_growth(
            base_inputs(trainer_pid=None, trainer_rss_bytes=4096),
            prediction_observations=(),
            proposal_observations=(),
            growth_config=config(),
            now_ms=1000,
            prediction_stream_name="prediction",
            proposal_stream_name="proposal",
        )
