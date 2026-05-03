from __future__ import annotations

import pytest

from v2.backend.app.domain.liveness_stream_growth import (
    LivenessStreamGrowthDomainError,
    StreamIdObservation,
)


def test_parsed_id_returns_int_tuple() -> None:
    value = StreamIdObservation(stream_name="prediction", stream_id="123-4", observation_ts_ms=1)
    assert value.parsed_id() == (123, 4)
    assert all(type(part) is int for part in value.parsed_id())


def test_parsed_id_accepts_large_realistic_literals() -> None:
    value = StreamIdObservation(
        stream_name="prediction",
        stream_id="17751529641234567890-9000000000000000000",
        observation_ts_ms=1,
    )
    assert value.parsed_id() == (17751529641234567890, 9000000000000000000)


def test_parsed_id_raises_when_state_is_bypassed() -> None:
    value = StreamIdObservation(stream_name="prediction", stream_id="123-4", observation_ts_ms=1)
    object.__setattr__(value, "stream_id", "1.0-0")
    with pytest.raises(LivenessStreamGrowthDomainError):
        value.parsed_id()
