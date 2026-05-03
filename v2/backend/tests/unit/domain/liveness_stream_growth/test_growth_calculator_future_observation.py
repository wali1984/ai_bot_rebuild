from __future__ import annotations

import pytest

from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    LivenessStreamGrowthDomainError,
    StreamIdObservation,
    compute_stream_id_growth_in_window,
)


def _obs(stream_name: str, stream_id: str, ts_ms: int) -> StreamIdObservation:
    return StreamIdObservation(stream_name=stream_name, stream_id=stream_id, observation_ts_ms=ts_ms)


def test_single_future_observation_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError) as exc_info:
        compute_stream_id_growth_in_window(
            (_obs("prediction", "1001-0", 1001),),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
    assert exc_info.value.reason == "observation_in_future"


def test_future_observation_at_end_still_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        compute_stream_id_growth_in_window(
            (_obs("prediction", "950-0", 950), _obs("prediction", "1001-0", 1001)),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )


def test_future_observation_for_non_matching_stream_still_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        compute_stream_id_growth_in_window(
            (_obs("proposal", "1001-0", 1001),),
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )


def test_future_observation_at_now_zero_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        compute_stream_id_growth_in_window(
            (_obs("prediction", "1-0", 1),),
            GrowthWindowConfig(window_ms=1),
            0,
            stream_name="prediction",
        )
