from __future__ import annotations

from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    StreamIdObservation,
    compute_stream_id_growth_in_window,
)


def _obs(stream_name: str, stream_id: str, ts_ms: int) -> StreamIdObservation:
    return StreamIdObservation(stream_name=stream_name, stream_id=stream_id, observation_ts_ms=ts_ms)


def test_mixed_stream_tuple_filters_to_matching_stream_name() -> None:
    assert (
        compute_stream_id_growth_in_window(
            (
                _obs("prediction", "100-0", 950),
                _obs("proposal", "101-0", 960),
                _obs("prediction", "102-0", 970),
            ),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 2
    )


def test_zero_matching_rows_returns_zero() -> None:
    assert (
        compute_stream_id_growth_in_window(
            (_obs("proposal", "101-0", 960),),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 0
    )


def test_name_filter_and_window_filter_both_apply() -> None:
    assert (
        compute_stream_id_growth_in_window(
            (
                _obs("prediction", "100-0", 850),
                _obs("proposal", "101-0", 960),
            ),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 0
    )
