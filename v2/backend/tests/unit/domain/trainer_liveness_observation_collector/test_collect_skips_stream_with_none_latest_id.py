from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    collect_stream_id_observations,
)


def test_collect_skips_stream_with_none_latest_id() -> None:
    reader = InMemoryStreamLatestIdReader(
        {
            "prediction": "1-0",
            "proposal": None,
            "audit": "3-0",
        }
    )

    observations = collect_stream_id_observations(
        reader,
        stream_names=("prediction", "proposal", "missing", "audit"),
        clock_ms=lambda: 42,
    )

    assert tuple(observation.stream_name for observation in observations) == (
        "prediction",
        "audit",
    )
