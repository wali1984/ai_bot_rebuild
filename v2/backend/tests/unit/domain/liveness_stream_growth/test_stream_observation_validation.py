from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from v2.backend.app.domain.liveness_stream_growth import (
    LivenessStreamGrowthDomainError,
    StreamIdObservation,
)


def test_empty_stream_name_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        StreamIdObservation(stream_name="", stream_id="1-0", observation_ts_ms=1)


def test_stream_name_with_whitespace_raises() -> None:
    for stream_name in (" prediction", "prediction ", "pred stream", "pred\tstream"):
        with pytest.raises(LivenessStreamGrowthDomainError):
            StreamIdObservation(stream_name=stream_name, stream_id="1-0", observation_ts_ms=1)


def test_stream_name_with_path_separator_raises() -> None:
    for stream_name in ("pred/stream", "pred\\stream"):
        with pytest.raises(LivenessStreamGrowthDomainError):
            StreamIdObservation(stream_name=stream_name, stream_id="1-0", observation_ts_ms=1)


def test_stream_name_with_control_chars_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        StreamIdObservation(stream_name="pred\x00stream", stream_id="1-0", observation_ts_ms=1)


def test_stream_id_lacking_separator_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        StreamIdObservation(stream_name="prediction", stream_id="10", observation_ts_ms=1)


def test_stream_id_with_multiple_separators_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        StreamIdObservation(stream_name="prediction", stream_id="10-1-0", observation_ts_ms=1)


def test_stream_id_parts_that_are_not_decimal_raise() -> None:
    for stream_id in ("0x1-0", "1.0-0", "-1-0", "1--0"):
        with pytest.raises(LivenessStreamGrowthDomainError):
            StreamIdObservation(stream_name="prediction", stream_id=stream_id, observation_ts_ms=1)


def test_stream_id_with_leading_whitespace_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        StreamIdObservation(stream_name="prediction", stream_id=" 1-0", observation_ts_ms=1)


def test_stream_id_with_very_large_parts_is_accepted() -> None:
    value = StreamIdObservation(
        stream_name="prediction",
        stream_id=f"{2**80}-{2**70}",
        observation_ts_ms=1,
    )
    assert value.parsed_id() == (2**80, 2**70)


def test_negative_observation_ts_ms_raises() -> None:
    with pytest.raises(LivenessStreamGrowthDomainError):
        StreamIdObservation(stream_name="prediction", stream_id="1-0", observation_ts_ms=-1)


def test_non_int_observation_ts_ms_raises() -> None:
    for observation_ts_ms in (1.0, True, "1"):
        with pytest.raises(LivenessStreamGrowthDomainError):
            StreamIdObservation(
                stream_name="prediction",
                stream_id="1-0",
                observation_ts_ms=observation_ts_ms,  # type: ignore[arg-type]
            )


def test_frozen_dataclass_mutation_raises() -> None:
    value = StreamIdObservation(stream_name="prediction", stream_id="1-0", observation_ts_ms=1)
    with pytest.raises(FrozenInstanceError):
        value.stream_id = "2-0"  # type: ignore[misc]
