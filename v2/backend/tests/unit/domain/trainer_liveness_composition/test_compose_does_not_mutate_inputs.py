from __future__ import annotations

from v2.backend.app.domain.trainer_liveness_composition import compose_liveness_snapshot_with_growth
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig, StreamIdObservation


def base_inputs() -> LivenessSnapshotBaseInputs:
    return LivenessSnapshotBaseInputs(101, 4096, 900, 202, True, 910, 920, 930, 940, False, 1000)


def config() -> GrowthWindowConfig:
    return GrowthWindowConfig(window_ms=100)


def obs(stream_name: str, stream_id: str, ts_ms: int) -> StreamIdObservation:
    return StreamIdObservation(stream_name=stream_name, stream_id=stream_id, observation_ts_ms=ts_ms)


def test_compose_does_not_mutate_inputs() -> None:
    base = base_inputs()
    prediction_observations = (obs("prediction", "900-0", 950),)
    proposal_observations = (obs("proposal", "901-0", 960),)
    growth_config = config()
    before = (base, prediction_observations, proposal_observations, growth_config)

    compose_liveness_snapshot_with_growth(
        base,
        prediction_observations=prediction_observations,
        proposal_observations=proposal_observations,
        growth_config=growth_config,
        now_ms=1000,
        prediction_stream_name="prediction",
        proposal_stream_name="proposal",
    )

    after = (base, prediction_observations, proposal_observations, growth_config)
    assert after == before
    assert after[0] is before[0]
    assert after[1] is before[1]
    assert after[2] is before[2]
    assert after[3] is before[3]
