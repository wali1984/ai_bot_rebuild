from __future__ import annotations

from dataclasses import dataclass

from .errors import LivenessStreamGrowthDomainError


_STREAM_NAME_ALLOWED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_:.-")


def _ensure_stream_name(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise LivenessStreamGrowthDomainError("must_be_str", field=field)
    if value == "":
        raise LivenessStreamGrowthDomainError("must_be_nonempty", field=field)
    if value != value.strip():
        raise LivenessStreamGrowthDomainError("must_not_have_edge_whitespace", field=field)
    if any(char.isspace() for char in value):
        raise LivenessStreamGrowthDomainError("must_not_have_whitespace", field=field)
    if "/" in value or "\\" in value:
        raise LivenessStreamGrowthDomainError("must_not_have_path_separator", field=field)
    if any(char not in _STREAM_NAME_ALLOWED for char in value):
        raise LivenessStreamGrowthDomainError("invalid_characters", field=field)


def _parse_stream_id(value: str, *, field: str) -> tuple[int, int]:
    if not isinstance(value, str):
        raise LivenessStreamGrowthDomainError("must_be_str", field=field)
    if value == "":
        raise LivenessStreamGrowthDomainError("must_be_nonempty", field=field)
    if value.count("-") != 1:
        raise LivenessStreamGrowthDomainError("must_have_single_separator", field=field)

    ms_part, seq_part = value.split("-", 1)
    if not _is_ascii_decimal(ms_part) or not _is_ascii_decimal(seq_part):
        raise LivenessStreamGrowthDomainError("must_be_decimal_stream_id", field=field)

    ms = int(ms_part, 10)
    seq = int(seq_part, 10)
    if ms < 0 or seq < 0:
        raise LivenessStreamGrowthDomainError("must_be_nonnegative", field=field)
    return ms, seq


def _is_ascii_decimal(value: str) -> bool:
    return value != "" and all("0" <= char <= "9" for char in value)


@dataclass(frozen=True, slots=True)
class StreamIdObservation:
    stream_name: str
    stream_id: str
    observation_ts_ms: int

    def __post_init__(self) -> None:
        _ensure_stream_name(self.stream_name, field="stream_name")
        _parse_stream_id(self.stream_id, field="stream_id")
        if type(self.observation_ts_ms) is not int:
            raise LivenessStreamGrowthDomainError("must_be_int", field="observation_ts_ms")
        if self.observation_ts_ms < 0:
            raise LivenessStreamGrowthDomainError("must_be_nonnegative", field="observation_ts_ms")

    def parsed_id(self) -> tuple[int, int]:
        return _parse_stream_id(self.stream_id, field="stream_id")
