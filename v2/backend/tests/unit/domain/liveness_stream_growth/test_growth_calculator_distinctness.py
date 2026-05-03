from __future__ import annotations

from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    StreamIdObservation,
    compute_stream_id_growth_in_window,
)


def _obs(stream_name: str, stream_id: str, ts_ms: int) -> StreamIdObservation:
    return StreamIdObservation(stream_name=stream_name, stream_id=stream_id, observation_ts_ms=ts_ms)


def test_duplicate_stream_id_counts_once() -> None:
    assert (
        compute_stream_id_growth_in_window(
            (_obs("prediction", "100-0", 951), _obs("prediction", "100-0", 980)),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 1
    )


def test_textually_different_equal_ids_count_as_distinct() -> None:
    assert (
        compute_stream_id_growth_in_window(
            (_obs("prediction", "100-0", 951), _obs("prediction", "0100-0", 980)),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 2
    )


def test_same_id_different_timestamps_counts_once_when_in_window() -> None:
    assert (
        compute_stream_id_growth_in_window(
            (_obs("prediction", "100-0", 850), _obs("prediction", "100-0", 980)),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 1
    )


def test_distinctness_applies_after_stream_filter() -> None:
    assert (
        compute_stream_id_growth_in_window(
            (_obs("prediction", "100-0", 950), _obs("proposal", "100-0", 960)),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 1
    )
