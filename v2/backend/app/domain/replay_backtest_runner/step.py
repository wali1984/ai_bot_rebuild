from __future__ import annotations

from dataclasses import dataclass

from .errors import ReplayBacktestRunnerDomainError


STEP_ACTION_RECORD_ALLOW = "step_record_allow"
STEP_ACTION_RECORD_DENY = "step_record_deny"

STEP_REASON_MIRROR_ALLOW_PROCEED_LONG = "step_mirror_allow_proceed_long"
STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT = "step_mirror_allow_proceed_short"
STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD = "step_mirror_deny_orchestrator_held"
STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED = (
    "step_mirror_deny_orchestrator_abstained"
)
STEP_REASON_MIRROR_DENY_DEFAULT = "step_mirror_deny_default"

_ALLOWED_STEP_ACTIONS = frozenset(
    {
        STEP_ACTION_RECORD_ALLOW,
        STEP_ACTION_RECORD_DENY,
    }
)
_ALLOWED_STEP_REASONS = frozenset(
    {
        STEP_REASON_MIRROR_ALLOW_PROCEED_LONG,
        STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT,
        STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
        STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
        STEP_REASON_MIRROR_DENY_DEFAULT,
    }
)
_ALLOWED_INPUT_PAPER_ACTIONS = frozenset({"record_allow", "record_deny"})
_ALLOWED_INPUT_PAPER_REASONS = frozenset(
    {
        "mirror_allow_proceed_long",
        "mirror_allow_proceed_short",
        "mirror_deny_orchestrator_held",
        "mirror_deny_orchestrator_abstained",
        "mirror_deny_default",
    }
)


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


def _validate_member(value: str, allowed_values: frozenset[str], field: str) -> None:
    if not isinstance(value, str):
        _raise("must_be_str", field)
    if value not in allowed_values:
        _raise("unsupported_value", field)


@dataclass(frozen=True, slots=True)
class ReplayBacktestStep:
    replay_step_id: str
    replay_run_id: str
    paper_trade_id: str
    risk_decision_id: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    step_ts_ms: int
    step_action: str
    step_reason_code: str
    input_paper_action: str
    input_paper_reason_code: str
    live_blocked: bool

    def __post_init__(self) -> None:
        _validate_identifier(self.replay_step_id, "replay_step_id")
        _validate_identifier(self.replay_run_id, "replay_run_id")
        _validate_identifier(self.paper_trade_id, "paper_trade_id")
        _validate_identifier(self.risk_decision_id, "risk_decision_id")
        _validate_identifier(self.decision_id, "decision_id")
        _validate_identifier(self.prediction_id, "prediction_id")
        _validate_identifier(self.feature_snapshot_id, "feature_snapshot_id")

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

        if not isinstance(self.step_ts_ms, int) or isinstance(self.step_ts_ms, bool):
            _raise("must_be_int", "step_ts_ms")
        if self.step_ts_ms < 0:
            _raise("must_be_non_negative", "step_ts_ms")

        _validate_member(self.step_action, _ALLOWED_STEP_ACTIONS, "step_action")
        _validate_member(
            self.step_reason_code,
            _ALLOWED_STEP_REASONS,
            "step_reason_code",
        )
        _validate_member(
            self.input_paper_action,
            _ALLOWED_INPUT_PAPER_ACTIONS,
            "input_paper_action",
        )
        _validate_member(
            self.input_paper_reason_code,
            _ALLOWED_INPUT_PAPER_REASONS,
            "input_paper_reason_code",
        )

        if not isinstance(self.live_blocked, bool):
            _raise("must_be_bool", "live_blocked")
        if self.live_blocked is not True:
            _raise(
                "replay_backtest_step_requires_live_blocked_true",
                "live_blocked",
            )

        if self.step_action == STEP_ACTION_RECORD_ALLOW:
            if not self.step_reason_code.startswith("step_mirror_allow_"):
                _raise(
                    "step_record_allow_requires_step_mirror_allow_prefix_reason",
                    "step_reason_code",
                )
            if self.input_paper_action != "record_allow":
                _raise(
                    "step_record_allow_requires_record_allow_input_paper_action",
                    "input_paper_action",
                )

        if self.step_action == STEP_ACTION_RECORD_DENY:
            if not self.step_reason_code.startswith("step_mirror_deny_"):
                _raise(
                    "step_record_deny_requires_step_mirror_deny_prefix_reason",
                    "step_reason_code",
                )
            if self.input_paper_action != "record_deny":
                _raise(
                    "step_record_deny_requires_record_deny_input_paper_action",
                    "input_paper_action",
                )

        if (
            self.step_reason_code == STEP_REASON_MIRROR_ALLOW_PROCEED_LONG
            and self.input_paper_reason_code != "mirror_allow_proceed_long"
        ):
            _raise(
                "step_mirror_allow_proceed_long_requires_mirror_allow_proceed_long_input_reason",
                "input_paper_reason_code",
            )
        if (
            self.step_reason_code == STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT
            and self.input_paper_reason_code != "mirror_allow_proceed_short"
        ):
            _raise(
                "step_mirror_allow_proceed_short_requires_mirror_allow_proceed_short_input_reason",
                "input_paper_reason_code",
            )
        if (
            self.step_reason_code == STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD
            and self.input_paper_reason_code != "mirror_deny_orchestrator_held"
        ):
            _raise(
                "step_mirror_deny_orchestrator_held_requires_mirror_deny_orchestrator_held_input_reason",
                "input_paper_reason_code",
            )
        if (
            self.step_reason_code == STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED
            and self.input_paper_reason_code != "mirror_deny_orchestrator_abstained"
        ):
            _raise(
                "step_mirror_deny_orchestrator_abstained_requires_mirror_deny_orchestrator_abstained_input_reason",
                "input_paper_reason_code",
            )
        if (
            self.step_reason_code == STEP_REASON_MIRROR_DENY_DEFAULT
            and self.input_paper_reason_code != "mirror_deny_default"
        ):
            _raise(
                "step_mirror_deny_default_requires_mirror_deny_default_input_reason",
                "input_paper_reason_code",
            )
