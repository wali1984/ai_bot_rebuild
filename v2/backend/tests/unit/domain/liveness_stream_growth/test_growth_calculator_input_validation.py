from __future__ import annotations

import pytest

from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    LivenessStreamGrowthDomainError,
    StreamIdObservation,
    compute_stream_id_growth_in_window,
)


def _observation() -> StreamIdObservation:
    return StreamIdObservation(stream_name="prediction", stream_id="1-0", observation_ts_ms=1)


def test_observations_as_list_raises_observations_not_tuple() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError) as exc_info:
        compute_stream_id_growth_in_window(
            [_observation()],  # type: ignore[arg-type]
            GrowthWindowConfig(window_ms=1),
            1,
            stream_name="prediction",
        )
    assert exc_info.value.reason == "observations_not_tuple"


def test_observations_as_generator_raises() -> None:
    observations = (_observation() for _ in range(1))
    with pytest.raises(LivenessStreamGrowthDomainError):
        compute_stream_id_growth_in_window(
            observations,  # type: ignore[arg-type]
            GrowthWindowConfig(window_ms=1),
            1,
            stream_name="prediction",
        )


def test_config_as_other_type_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        compute_stream_id_growth_in_window((), object(), 1, stream_name="prediction")  # type: ignore[arg-type]


def test_negative_now_ms_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        compute_stream_id_growth_in_window(
            (),
            GrowthWindowConfig(window_ms=1),
            -1,
            stream_name="prediction",
        )


def test_non_int_now_ms_raises() -> None:
    for now_ms in (1.0, True):
        with pytest.raises(LivenessStreamGrowthDomainError):
            compute_stream_id_growth_in_window(
                (),
                GrowthWindowConfig(window_ms=1),
                now_ms,  # type: ignore[arg-type]
                stream_name="prediction",
            )


def test_empty_stream_name_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        compute_stream_id_growth_in_window((), GrowthWindowConfig(window_ms=1), 1, stream_name="")


def test_stream_name_with_whitespace_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        compute_stream_id_growth_in_window(
            (),
            GrowthWindowConfig(window_ms=1),
            1,
            stream_name="pred stream",
        )


def test_stream_name_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        compute_stream_id_growth_in_window((), GrowthWindowConfig(window_ms=1), 1, "prediction")  # type: ignore[misc]
