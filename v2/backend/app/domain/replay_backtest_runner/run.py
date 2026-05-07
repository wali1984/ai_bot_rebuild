from __future__ import annotations

from dataclasses import dataclass

from .errors import ReplayBacktestRunnerDomainError


RUN_MODE_REPLAY = "replay"
RUN_MODE_BACKTEST = "backtest"

_ALLOWED_RUN_MODES = frozenset({RUN_MODE_REPLAY, RUN_MODE_BACKTEST})


def _raise(reason: str, field: str) -> None:
    raise ReplayBacktestRunnerDomainError(reason, field=field)


def _validate_identifier(value: str, field: str) -> None:
    if not isinstance(value, str):
        _raise("must_be_str", field)
    if value == "":
        _raise("must_be_non_empty", field)
    if value != value.strip():
        _raise("must_not_have_outer_whitespace", field)
    if any(character.isspace() for character in value):
        _raise("must_not_contain_whitespace", field)
    if len(value) > 128:
        _raise("must_be_at_most_128_chars", field)


@dataclass(frozen=True, slots=True)
class ReplayBacktestRun:
    replay_run_id: str
    run_mode: str
    symbol: str
    run_started_ts_ms: int
    run_ended_ts_ms: int
    live_blocked: bool

    def __post_init__(self) -> None:
        _validate_identifier(self.replay_run_id, "replay_run_id")

        if not isinstance(self.run_mode, str):
            _raise("must_be_str", "run_mode")
        if self.run_mode not in _ALLOWED_RUN_MODES:
            _raise("unsupported_value", "run_mode")

        if not isinstance(self.symbol, str):
            _raise("must_be_str", "symbol")
        if self.symbol == "":
            _raise("must_be_non_empty", "symbol")
        if any(character.isspace() for character in self.symbol):
            _raise("must_not_contain_whitespace", "symbol")
        if len(self.symbol) > 32:
            _raise("must_be_at_most_32_chars", "symbol")
        if self.symbol != self.symbol.upper():
            _raise("must_be_uppercase", "symbol")

        if not isinstance(self.run_started_ts_ms, int) or isinstance(
            self.run_started_ts_ms, bool
        ):
            _raise("must_be_int", "run_started_ts_ms")
        if self.run_started_ts_ms < 0:
            _raise("must_be_non_negative", "run_started_ts_ms")

        if not isinstance(self.run_ended_ts_ms, int) or isinstance(
            self.run_ended_ts_ms, bool
        ):
            _raise("must_be_int", "run_ended_ts_ms")
        if self.run_ended_ts_ms < self.run_started_ts_ms:
            _raise(
                "run_ended_ts_ms_must_be_ge_run_started_ts_ms",
                "run_ended_ts_ms",
            )

        if not isinstance(self.live_blocked, bool):
            _raise("must_be_bool", "live_blocked")
        if self.live_blocked is not True:
            _raise(
                "replay_backtest_run_requires_live_blocked_true",
                "live_blocked",
            )
