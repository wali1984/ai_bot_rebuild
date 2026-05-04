from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    collect_stream_id_observations,
)


def test_collect_returns_observations_in_input_order() -> None:
    reader = InMemoryStreamLatestIdReader(
        {
            "proposal": "20-0",
            "prediction": "10-0",
            "audit": "30-0",
        }
    )

    observations = collect_stream_id_observations(
        reader,
        stream_names=("prediction", "proposal", "audit"),
        clock_ms=lambda: 99,
    )

    assert tuple(observation.stream_name for observation in observations) == (
        "prediction",
        "proposal",
        "audit",
    )
    assert tuple(observation.stream_id for observation in observations) == (
        "10-0",
        "20-0",
        "30-0",
    )
