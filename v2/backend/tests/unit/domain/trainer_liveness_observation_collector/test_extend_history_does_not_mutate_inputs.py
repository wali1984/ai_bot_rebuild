from v2.backend.app.domain.liveness_stream_growth import StreamIdObservation
from v2.backend.app.domain.trainer_liveness_observation_collector import extend_observation_history


def _obs(stream_id: str, ts_ms: int) -> StreamIdObservation:
    return StreamIdObservation(
        stream_name="prediction",
        stream_id=stream_id,
        observation_ts_ms=ts_ms,
    )


def test_extend_history_does_not_mutate_inputs() -> None:
    history = (_obs("1-0", 10), _obs("2-0", 20))
    new = (_obs("3-0", 30),)
    original_history = tuple(history)
    original_new = tuple(new)

    extend_observation_history(history, new, max_total=2)

    assert history == original_history
    assert new == original_new
