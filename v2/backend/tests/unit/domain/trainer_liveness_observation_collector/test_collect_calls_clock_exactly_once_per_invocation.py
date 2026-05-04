from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    collect_stream_id_observations,
)


def test_collect_calls_clock_exactly_once_per_invocation() -> None:
    reader = InMemoryStreamLatestIdReader(
        {
            "prediction": "1-0",
            "proposal": "2-0",
        }
    )
    calls = 0

    def clock_ms() -> int:
        nonlocal calls
        calls += 1
        return 123

    collect_stream_id_observations(
        reader,
        stream_names=("prediction", "proposal"),
        clock_ms=clock_ms,
    )

    assert calls == 1
