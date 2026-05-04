from v2.backend.app.domain.liveness_stream_growth import StreamIdObservation
from v2.backend.app.domain.trainer_liveness_observation_collector import extend_observation_history


def _obs(stream_id: str, ts_ms: int) -> StreamIdObservation:
    return StreamIdObservation(
        stream_name="prediction",
        stream_id=stream_id,
        observation_ts_ms=ts_ms,
    )


def test_extend_history_returns_combined_tuple_when_under_max() -> None:
    history = (_obs("1-0", 10),)
    new = (_obs("2-0", 20),)

    result = extend_observation_history(history, new, max_total=5)

    assert result == history + new
    assert result is not history
    assert result is not new
