from __future__ import annotations

from dataclasses import dataclass

from .errors import PaperExecutionLedgerDomainError


PAPER_LEDGER_ACTION_RECORD_ALLOW = "record_allow"
PAPER_LEDGER_ACTION_RECORD_DENY = "record_deny"

PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG = "mirror_allow_proceed_long"
PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT = "mirror_allow_proceed_short"
PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED = "mirror_deny_orchestrator_abstained"
PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD = "mirror_deny_orchestrator_held"
PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT = "mirror_deny_default"

_ALLOWED_LEDGER_ACTIONS = frozenset(
    {
        PAPER_LEDGER_ACTION_RECORD_ALLOW,
        PAPER_LEDGER_ACTION_RECORD_DENY,
    }
)
_ALLOWED_LEDGER_REASONS = frozenset(
    {
        PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
        PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
        PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
        PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
        PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
    }
)
_ALLOWED_INPUT_RISK_ACTIONS = frozenset({"allow", "deny"})
_ALLOWED_INPUT_RISK_REASONS = frozenset(
    {
        "allow_proceed_long",
        "allow_proceed_short",
        "deny_orchestrator_abstained",
        "deny_orchestrator_held",
        "deny_default",
    }
)
_IDENTIFIER_FIELDS = frozenset(
    {
        "paper_trade_id",
        "risk_decision_id",
        "decision_id",
        "prediction_id",
        "feature_snapshot_id",
    }
)
_ALLOW_LEDGER_REASONS = frozenset(
    {
        PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
        PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
    }
)
_DENY_LEDGER_REASONS = frozenset(
    {
        PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
        PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
        PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
    }
)


def _raise(reason: str, field: str) -> None:
    raise PaperExecutionLedgerDomainError(reason, field=field)


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
class PaperExecutionLedgerEntry:
    paper_trade_id: str
    risk_decision_id: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    ledger_entry_ts_ms: int
    ledger_action: str
    ledger_reason_code: str
    input_risk_action: str
    input_risk_reason_code: str
    live_blocked: bool

    def __post_init__(self) -> None:
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

        if not isinstance(self.ledger_entry_ts_ms, int) or isinstance(
            self.ledger_entry_ts_ms, bool
        ):
            _raise("must_be_int", "ledger_entry_ts_ms")
        if self.ledger_entry_ts_ms < 0:
            _raise("must_be_non_negative", "ledger_entry_ts_ms")

        _validate_member(
            self.ledger_action,
            _ALLOWED_LEDGER_ACTIONS,
            "ledger_action",
        )
        _validate_member(
            self.ledger_reason_code,
            _ALLOWED_LEDGER_REASONS,
            "ledger_reason_code",
        )
        _validate_member(
            self.input_risk_action,
            _ALLOWED_INPUT_RISK_ACTIONS,
            "input_risk_action",
        )
        _validate_member(
            self.input_risk_reason_code,
            _ALLOWED_INPUT_RISK_REASONS,
            "input_risk_reason_code",
        )

        if not isinstance(self.live_blocked, bool):
            _raise("must_be_bool", "live_blocked")
        if self.live_blocked is not True:
            _raise("paper_ledger_requires_live_blocked_true", "live_blocked")

        if self.ledger_action == PAPER_LEDGER_ACTION_RECORD_ALLOW:
            if not self.ledger_reason_code.startswith("mirror_allow_"):
                _raise(
                    "record_allow_requires_mirror_allow_prefix_reason",
                    "ledger_reason_code",
                )
            if self.input_risk_action != "allow":
                _raise(
                    "record_allow_requires_allow_input_risk_action",
                    "input_risk_action",
                )

        if self.ledger_action == PAPER_LEDGER_ACTION_RECORD_DENY:
            if not self.ledger_reason_code.startswith("mirror_deny_"):
                _raise(
                    "record_deny_requires_mirror_deny_prefix_reason",
                    "ledger_reason_code",
                )
            if self.input_risk_action != "deny":
                _raise(
                    "record_deny_requires_deny_input_risk_action",
                    "input_risk_action",
                )

        if (
            self.ledger_reason_code
            == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG
            and self.input_risk_reason_code != "allow_proceed_long"
        ):
            _raise(
                "mirror_allow_proceed_long_requires_allow_proceed_long_input_reason",
                "input_risk_reason_code",
            )
        if (
            self.ledger_reason_code
            == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT
            and self.input_risk_reason_code != "allow_proceed_short"
        ):
            _raise(
                "mirror_allow_proceed_short_requires_allow_proceed_short_input_reason",
                "input_risk_reason_code",
            )
        if (
            self.ledger_reason_code
            == PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED
            and self.input_risk_reason_code != "deny_orchestrator_abstained"
        ):
            _raise(
                "mirror_deny_orchestrator_abstained_requires_deny_orchestrator_abstained_input_reason",
                "input_risk_reason_code",
            )
        if (
            self.ledger_reason_code
            == PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD
            and self.input_risk_reason_code != "deny_orchestrator_held"
        ):
            _raise(
                "mirror_deny_orchestrator_held_requires_deny_orchestrator_held_input_reason",
                "input_risk_reason_code",
            )
        if (
            self.ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT
            and self.input_risk_reason_code != "deny_default"
        ):
            _raise(
                "mirror_deny_default_requires_deny_default_input_reason",
                "input_risk_reason_code",
            )
