from __future__ import annotations

from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    StreamIdObservation,
    compute_stream_id_growth_in_window,
)


def _obs(stream_name: str, stream_id: str, ts_ms: int) -> StreamIdObservation:
    return StreamIdObservation(stream_name=stream_name, stream_id=stream_id, observation_ts_ms=ts_ms)


def test_empty_observations_returns_zero() -> None:
    assert (
        compute_stream_id_growth_in_window(
            (),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 0
    )


def test_all_observations_out_of_window_returns_zero() -> None:
    assert (
        compute_stream_id_growth_in_window(
            (_obs("prediction", "800-0", 800), _obs("prediction", "850-0", 850)),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 0
    )


def test_all_other_streams_returns_zero() -> None:
    assert (
        compute_stream_id_growth_in_window(
            (_obs("proposal", "950-0", 950),),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 0
    )


def test_mix_of_out_of_window_and_other_stream_returns_zero() -> None:
    assert (
        compute_stream_id_growth_in_window(
            (_obs("prediction", "850-0", 850), _obs("proposal", "950-0", 950)),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 0
    )
