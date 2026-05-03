from __future__ import annotations

import pytest

from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    LivenessStreamGrowthDomainError,
)


def test_zero_window_ms_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        GrowthWindowConfig(window_ms=0)


def test_negative_window_ms_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        GrowthWindowConfig(window_ms=-1)


def test_non_int_window_ms_raises() -> None:
    for window_ms in (1.0, True, "1"):
        with pytest.raises(LivenessStreamGrowthDomainError):
            GrowthWindowConfig(window_ms=window_ms)  # type: ignore[arg-type]


def test_boundary_inclusive_int_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        GrowthWindowConfig(window_ms=1, boundary_inclusive=1)  # type: ignore[arg-type]


def test_boundary_inclusive_default_is_false() -> None:
    assert GrowthWindowConfig(window_ms=1).boundary_inclusive is False
