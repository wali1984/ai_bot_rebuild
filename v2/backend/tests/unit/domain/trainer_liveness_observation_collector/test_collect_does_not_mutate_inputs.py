from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    collect_stream_id_observations,
)


def test_collect_does_not_mutate_inputs() -> None:
    latest_ids = {"prediction": "1-0", "proposal": "2-0"}
    reader = InMemoryStreamLatestIdReader(latest_ids)
    stream_names = ("prediction", "proposal")

    observations = collect_stream_id_observations(
        reader,
        stream_names=stream_names,
        clock_ms=lambda: 10,
    )

    latest_ids["prediction"] = "99-0"

    assert stream_names == ("prediction", "proposal")
    assert tuple(observation.stream_id for observation in observations) == ("1-0", "2-0")
    assert collect_stream_id_observations(
        reader,
        stream_names=("prediction",),
        clock_ms=lambda: 11,
    )[0].stream_id == "1-0"
