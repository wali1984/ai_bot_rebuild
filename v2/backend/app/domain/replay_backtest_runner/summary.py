from __future__ import annotations

from dataclasses import dataclass

from .errors import ReplayBacktestRunnerDomainError


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


def _validate_count(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        _raise("must_be_int", field)
    if value < 0:
        _raise("must_be_non_negative", field)


@dataclass(frozen=True, slots=True)
class ReplayBacktestSummary:
    replay_summary_id: str
    replay_run_id: str
    summary_emitted_ts_ms: int
    total_steps_count: int
    record_allow_steps_count: int
    record_deny_steps_count: int
    mirror_allow_proceed_long_steps_count: int
    mirror_allow_proceed_short_steps_count: int
    mirror_deny_orchestrator_held_steps_count: int
    mirror_deny_orchestrator_abstained_steps_count: int
    mirror_deny_default_steps_count: int
    live_blocked: bool

    def __post_init__(self) -> None:
        _validate_identifier(self.replay_summary_id, "replay_summary_id")
        _validate_identifier(self.replay_run_id, "replay_run_id")

        if not isinstance(self.summary_emitted_ts_ms, int) or isinstance(
            self.summary_emitted_ts_ms, bool
        ):
            _raise("must_be_int", "summary_emitted_ts_ms")
        if self.summary_emitted_ts_ms < 0:
            _raise("must_be_non_negative", "summary_emitted_ts_ms")

        _validate_count(self.total_steps_count, "total_steps_count")
        _validate_count(self.record_allow_steps_count, "record_allow_steps_count")
        _validate_count(self.record_deny_steps_count, "record_deny_steps_count")
        _validate_count(
            self.mirror_allow_proceed_long_steps_count,
            "mirror_allow_proceed_long_steps_count",
        )
        _validate_count(
            self.mirror_allow_proceed_short_steps_count,
            "mirror_allow_proceed_short_steps_count",
        )
        _validate_count(
            self.mirror_deny_orchestrator_held_steps_count,
            "mirror_deny_orchestrator_held_steps_count",
        )
        _validate_count(
            self.mirror_deny_orchestrator_abstained_steps_count,
            "mirror_deny_orchestrator_abstained_steps_count",
        )
        _validate_count(
            self.mirror_deny_default_steps_count,
            "mirror_deny_default_steps_count",
        )

        if not isinstance(self.live_blocked, bool):
            _raise("must_be_bool", "live_blocked")
        if self.live_blocked is not True:
            _raise(
                "replay_backtest_summary_requires_live_blocked_true",
                "live_blocked",
            )

        if (
            self.record_allow_steps_count + self.record_deny_steps_count
            != self.total_steps_count
        ):
            _raise(
                "action_partition_sum_must_equal_total_steps_count",
                "total_steps_count",
            )
        if (
            self.mirror_allow_proceed_long_steps_count
            + self.mirror_allow_proceed_short_steps_count
            != self.record_allow_steps_count
        ):
            _raise(
                "allow_subreason_partition_sum_must_equal_record_allow_steps_count",
                "record_allow_steps_count",
            )
        if (
            self.mirror_deny_orchestrator_held_steps_count
            + self.mirror_deny_orchestrator_abstained_steps_count
            + self.mirror_deny_default_steps_count
            != self.record_deny_steps_count
        ):
            _raise(
                "deny_subreason_partition_sum_must_equal_record_deny_steps_count",
                "record_deny_steps_count",
            )
