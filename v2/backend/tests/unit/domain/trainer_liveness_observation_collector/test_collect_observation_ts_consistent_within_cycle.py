from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    collect_stream_id_observations,
)


def test_collect_observation_ts_consistent_within_cycle() -> None:
    reader = InMemoryStreamLatestIdReader(
        {
            "prediction": "1-0",
            "proposal": "2-0",
        }
    )

    observations = collect_stream_id_observations(
        reader,
        stream_names=("prediction", "proposal"),
        clock_ms=lambda: 777,
    )

    assert tuple(observation.observation_ts_ms for observation in observations) == (777, 777)
