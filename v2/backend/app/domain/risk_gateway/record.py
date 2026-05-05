from __future__ import annotations

from dataclasses import dataclass

from .errors import RiskGatewayDomainError


RISK_DECISION_ACTION_ALLOW = "allow"
RISK_DECISION_ACTION_DENY = "deny"

RISK_DECISION_REASON_ALLOW_PROCEED_LONG = "allow_proceed_long"
RISK_DECISION_REASON_ALLOW_PROCEED_SHORT = "allow_proceed_short"
RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED = "deny_orchestrator_abstained"
RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD = "deny_orchestrator_held"
RISK_DECISION_REASON_DENY_DEFAULT = "deny_default"

_ALLOWED_RISK_ACTIONS = frozenset(
    {
        RISK_DECISION_ACTION_ALLOW,
        RISK_DECISION_ACTION_DENY,
    }
)
_ALLOWED_RISK_REASONS = frozenset(
    {
        RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
        RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
        RISK_DECISION_REASON_DENY_DEFAULT,
    }
)
_ALLOWED_INPUT_DECISION_ACTIONS = frozenset(
    {
        "open_long",
        "open_short",
        "hold",
        "abstain",
    }
)
_ALLOWED_INPUT_DECISION_REASONS = frozenset(
    {
        "proceed_long",
        "proceed_short",
        "hold_flat_direction",
        "abstain_low_confidence",
        "abstain_freshness_stale",
        "abstain_freshness_missing",
        "abstain_worker_degraded",
        "abstain_worker_critical",
        "abstain_worker_unknown",
    }
)
_TRADABLE_INPUT_DECISION_ACTIONS = frozenset({"open_long", "open_short"})


@dataclass(frozen=True, slots=True)
class RiskDecisionRecord:
    risk_decision_id: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    risk_decision_ts_ms: int
    risk_action: str
    risk_reason_code: str
    input_decision_action: str
    input_decision_reason_code: str
    live_blocked: bool

    def __post_init__(self) -> None:
        _validate_id_field(self.risk_decision_id, field="risk_decision_id")
        _validate_id_field(self.decision_id, field="decision_id")
        _validate_id_field(self.prediction_id, field="prediction_id")
        _validate_id_field(self.feature_snapshot_id, field="feature_snapshot_id")
        _validate_symbol(self.symbol)
        _validate_ts_ms(self.risk_decision_ts_ms)
        _validate_risk_action(self.risk_action)
        _validate_risk_reason_code(self.risk_reason_code)
        _validate_input_decision_action(self.input_decision_action)
        _validate_input_decision_reason_code(self.input_decision_reason_code)
        _validate_live_blocked(self.live_blocked)

        if self.risk_action == RISK_DECISION_ACTION_ALLOW:
            if not self.risk_reason_code.startswith("allow_"):
                raise RiskGatewayDomainError(
                    "allow_requires_allow_prefix_reason",
                    field="risk_reason_code",
                )

        if self.risk_action == RISK_DECISION_ACTION_DENY:
            if not self.risk_reason_code.startswith("deny_"):
                raise RiskGatewayDomainError(
                    "deny_requires_deny_prefix_reason",
                    field="risk_reason_code",
                )

        if self.risk_reason_code == RISK_DECISION_REASON_ALLOW_PROCEED_LONG:
            if self.input_decision_action != "open_long":
                raise RiskGatewayDomainError(
                    "allow_proceed_long_requires_open_long_input",
                    field="input_decision_action",
                )
            if self.input_decision_reason_code != "proceed_long":
                raise RiskGatewayDomainError(
                    "allow_proceed_long_requires_proceed_long_input_reason",
                    field="input_decision_reason_code",
                )

        if self.risk_reason_code == RISK_DECISION_REASON_ALLOW_PROCEED_SHORT:
            if self.input_decision_action != "open_short":
                raise RiskGatewayDomainError(
                    "allow_proceed_short_requires_open_short_input",
                    field="input_decision_action",
                )
            if self.input_decision_reason_code != "proceed_short":
                raise RiskGatewayDomainError(
                    "allow_proceed_short_requires_proceed_short_input_reason",
                    field="input_decision_reason_code",
                )

        if self.risk_reason_code == RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED:
            if self.input_decision_action != "abstain":
                raise RiskGatewayDomainError(
                    "deny_orchestrator_abstained_requires_abstain_input",
                    field="input_decision_action",
                )

        if self.risk_reason_code == RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD:
            if self.input_decision_action != "hold":
                raise RiskGatewayDomainError(
                    "deny_orchestrator_held_requires_hold_input",
                    field="input_decision_action",
                )

        if self.risk_reason_code == RISK_DECISION_REASON_DENY_DEFAULT:
            if self.input_decision_action not in _TRADABLE_INPUT_DECISION_ACTIONS:
                raise RiskGatewayDomainError(
                    "deny_default_requires_tradable_input",
                    field="input_decision_action",
                )


def _validate_id_field(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise RiskGatewayDomainError("must_be_str", field=field)
    if value == "":
        raise RiskGatewayDomainError("must_be_non_empty", field=field)
    if value != value.strip() or any(char.isspace() for char in value):
        raise RiskGatewayDomainError("must_not_have_whitespace", field=field)
    if len(value) > 128:
        raise RiskGatewayDomainError("must_be_at_most_128_chars", field=field)


def _validate_symbol(value: str) -> None:
    if not isinstance(value, str):
        raise RiskGatewayDomainError("must_be_str", field="symbol")
    if value == "":
        raise RiskGatewayDomainError("must_be_non_empty", field="symbol")
    if any(char.isspace() for char in value):
        raise RiskGatewayDomainError("must_not_have_whitespace", field="symbol")
    if len(value) > 32:
        raise RiskGatewayDomainError("must_be_at_most_32_chars", field="symbol")
    if value != value.upper():
        raise RiskGatewayDomainError("must_be_uppercase", field="symbol")


def _validate_ts_ms(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise RiskGatewayDomainError("must_be_int", field="risk_decision_ts_ms")
    if value < 0:
        raise RiskGatewayDomainError("must_be_nonnegative", field="risk_decision_ts_ms")


def _validate_risk_action(value: str) -> None:
    if not isinstance(value, str):
        raise RiskGatewayDomainError("must_be_str", field="risk_action")
    if value not in _ALLOWED_RISK_ACTIONS:
        raise RiskGatewayDomainError("invalid_risk_action", field="risk_action")


def _validate_risk_reason_code(value: str) -> None:
    if not isinstance(value, str):
        raise RiskGatewayDomainError("must_be_str", field="risk_reason_code")
    if value not in _ALLOWED_RISK_REASONS:
        raise RiskGatewayDomainError(
            "invalid_risk_reason_code",
            field="risk_reason_code",
        )


def _validate_input_decision_action(value: str) -> None:
    if not isinstance(value, str):
        raise RiskGatewayDomainError("must_be_str", field="input_decision_action")
    if value not in _ALLOWED_INPUT_DECISION_ACTIONS:
        raise RiskGatewayDomainError(
            "invalid_input_decision_action",
            field="input_decision_action",
        )


def _validate_input_decision_reason_code(value: str) -> None:
    if not isinstance(value, str):
        raise RiskGatewayDomainError(
            "must_be_str",
            field="input_decision_reason_code",
        )
    if value not in _ALLOWED_INPUT_DECISION_REASONS:
        raise RiskGatewayDomainError(
            "invalid_input_decision_reason_code",
            field="input_decision_reason_code",
        )


def _validate_live_blocked(value: bool) -> None:
    if not isinstance(value, bool):
        raise RiskGatewayDomainError("must_be_bool", field="live_blocked")
    if value is not True:
        raise RiskGatewayDomainError("must_be_true", field="live_blocked")
