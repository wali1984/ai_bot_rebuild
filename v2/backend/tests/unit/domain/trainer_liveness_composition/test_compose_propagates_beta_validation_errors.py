from __future__ import annotations

import pytest

from v2.backend.app.domain.liveness_stream_growth import LivenessStreamGrowthDomainError
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig, StreamIdObservation
from v2.backend.app.domain.trainer_liveness_composition import compose_liveness_snapshot_with_growth
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs


def base_inputs() -> LivenessSnapshotBaseInputs:
    return LivenessSnapshotBaseInputs(101, 4096, 900, 202, True, 910, 920, 930, 940, False, 1000)


def config() -> GrowthWindowConfig:
    return GrowthWindowConfig(window_ms=100)


def obs(stream_name: str, stream_id: str, ts_ms: int) -> StreamIdObservation:
    return StreamIdObservation(stream_name=stream_name, stream_id=stream_id, observation_ts_ms=ts_ms)


def test_compose_propagates_beta_validation_errors() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError, match="observation_in_future"):
        compose_liveness_snapshot_with_growth(
            base_inputs(),
            prediction_observations=(obs("prediction", "900-0", 1001),),
            proposal_observations=(),
            growth_config=config(),
            now_ms=1000,
            prediction_stream_name="prediction",
            proposal_stream_name="proposal",
        )
