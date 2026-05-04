from __future__ import annotations

from v2.backend.app.domain.trainer_liveness_composition import compose_liveness_snapshot_with_growth
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig


def base_inputs() -> LivenessSnapshotBaseInputs:
    return LivenessSnapshotBaseInputs(101, 4096, 900, 202, True, 910, 920, 930, 940, False, 1000)


def config() -> GrowthWindowConfig:
    return GrowthWindowConfig(window_ms=100)


def test_no_observations_produce_zero_growth() -> None:
    snapshot = compose_liveness_snapshot_with_growth(
        base_inputs(),
        prediction_observations=(),
        proposal_observations=(),
        growth_config=config(),
        now_ms=1000,
        prediction_stream_name="prediction",
        proposal_stream_name="proposal",
    )

    assert snapshot.prediction_stream_id_growth == 0
    assert snapshot.proposal_stream_id_growth == 0
