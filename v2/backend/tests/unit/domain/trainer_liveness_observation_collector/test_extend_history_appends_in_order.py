from v2.backend.app.domain.liveness_stream_growth import StreamIdObservation
from v2.backend.app.domain.trainer_liveness_observation_collector import extend_observation_history


def _obs(stream_id: str, ts_ms: int) -> StreamIdObservation:
    return StreamIdObservation(
        stream_name="prediction",
        stream_id=stream_id,
        observation_ts_ms=ts_ms,
    )


def test_extend_history_appends_new_after_history() -> None:
    first = _obs("1-0", 10)
    second = _obs("2-0", 20)
    third = _obs("3-0", 30)

    assert extend_observation_history((first, second), (third,), max_total=3) == (
        first,
        second,
        third,
    )
