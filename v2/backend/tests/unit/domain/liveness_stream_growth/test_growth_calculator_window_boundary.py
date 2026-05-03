from __future__ import annotations

from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    StreamIdObservation,
    compute_stream_id_growth_in_window,
)


def _obs(stream_id: str, ts_ms: int) -> StreamIdObservation:
    return StreamIdObservation(stream_name="prediction", stream_id=stream_id, observation_ts_ms=ts_ms)


def test_default_boundary_excludes_lower_bound() -> None:
    result = compute_stream_id_growth_in_window(
        (_obs("100-0", 900),),
        GrowthWindowConfig(window_ms=100),
        1000,
        stream_name="prediction",
    )
    assert result == 0


def test_default_boundary_includes_lower_bound_plus_one() -> None:
    result = compute_stream_id_growth_in_window(
        (_obs("101-0", 901),),
        GrowthWindowConfig(window_ms=100),
        1000,
        stream_name="prediction",
    )
    assert result == 1


def test_inclusive_boundary_includes_lower_bound() -> None:
    result = compute_stream_id_growth_in_window(
        (_obs("100-0", 900),),
        GrowthWindowConfig(window_ms=100, boundary_inclusive=True),
        1000,
        stream_name="prediction",
    )
    assert result == 1


def test_now_timestamp_is_included_for_both_boundary_policies() -> None:
    observations = (_obs("1000-0", 1000),)
    assert (
        compute_stream_id_growth_in_window(
            observations,
            GrowthWindowConfig(window_ms=100),
            1000,
            stream_name="prediction",
        )
        == 1
    )
    assert (
        compute_stream_id_growth_in_window(
            observations,
            GrowthWindowConfig(window_ms=100, boundary_inclusive=True),
            1000,
            stream_name="prediction",
        )
        == 1
    )


def test_zero_timestamp_with_now_less_than_window_follows_boundary_policy() -> None:
    result = compute_stream_id_growth_in_window(
        (_obs("0-0", 0),),
        GrowthWindowConfig(window_ms=100),
        50,
        stream_name="prediction",
    )
    assert result == 1
