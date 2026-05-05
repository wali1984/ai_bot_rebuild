from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import OrchestratorDecisionDomainError

DECISION_ACTION_OPEN_LONG = "open_long"
DECISION_ACTION_OPEN_SHORT = "open_short"
DECISION_ACTION_HOLD = "hold"
DECISION_ACTION_ABSTAIN = "abstain"

DECISION_REASON_PROCEED_LONG = "proceed_long"
DECISION_REASON_PROCEED_SHORT = "proceed_short"
DECISION_REASON_HOLD_FLAT_DIRECTION = "hold_flat_direction"
DECISION_REASON_ABSTAIN_LOW_CONFIDENCE = "abstain_low_confidence"
DECISION_REASON_ABSTAIN_FRESHNESS_STALE = "abstain_freshness_stale"
DECISION_REASON_ABSTAIN_FRESHNESS_MISSING = "abstain_freshness_missing"
DECISION_REASON_ABSTAIN_WORKER_DEGRADED = "abstain_worker_degraded"
DECISION_REASON_ABSTAIN_WORKER_CRITICAL = "abstain_worker_critical"
DECISION_REASON_ABSTAIN_WORKER_UNKNOWN = "abstain_worker_unknown"

_ALLOWED_DECISION_ACTIONS = frozenset(
    {
        DECISION_ACTION_OPEN_LONG,
        DECISION_ACTION_OPEN_SHORT,
        DECISION_ACTION_HOLD,
        DECISION_ACTION_ABSTAIN,
    }
)
_ALLOWED_DECISION_REASONS = frozenset(
    {
        DECISION_REASON_PROCEED_LONG,
        DECISION_REASON_PROCEED_SHORT,
        DECISION_REASON_HOLD_FLAT_DIRECTION,
        DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
        DECISION_REASON_ABSTAIN_FRESHNESS_STALE,
        DECISION_REASON_ABSTAIN_FRESHNESS_MISSING,
        DECISION_REASON_ABSTAIN_WORKER_DEGRADED,
        DECISION_REASON_ABSTAIN_WORKER_CRITICAL,
        DECISION_REASON_ABSTAIN_WORKER_UNKNOWN,
    }
)
_ALLOWED_INPUT_PREDICTION_DIRECTIONS = frozenset({"long", "short", "flat"})
_ALLOWED_INPUT_PREDICTION_FRESHNESS = frozenset({"fresh", "stale", "missing"})
_ALLOWED_INPUT_WORKER_HEALTH_STATUSES = frozenset(
    {"HEALTHY", "DEGRADED", "CRITICAL", "UNKNOWN"}
)


def _validate_identifier(value: str, *, field: str, max_length: int) -> None:
    if not isinstance(value, str):
        raise OrchestratorDecisionDomainError("must_be_str", field=field)
    if value == "":
        raise OrchestratorDecisionDomainError("must_be_non_empty", field=field)
    if value.strip() != value or any(character.isspace() for character in value):
        raise OrchestratorDecisionDomainError("must_not_have_whitespace", field=field)
    if len(value) > max_length:
        raise OrchestratorDecisionDomainError(
            f"must_be_at_most_{max_length}_chars", field=field
        )


def _validate_member(
    value: str, *, field: str, allowed_values: frozenset[str], reason: str
) -> None:
    if not isinstance(value, str):
        raise OrchestratorDecisionDomainError("must_be_str", field=field)
    if value not in allowed_values:
        raise OrchestratorDecisionDomainError(reason, field=field)


@dataclass(frozen=True, slots=True)
class OrchestratorDecisionRecord:
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    decision_ts_ms: int
    decision_action: str
    decision_reason_code: str
    input_prediction_direction: str
    input_prediction_confidence_calibrated: float
    input_prediction_freshness_flag: str
    input_worker_health_status: str
    live_blocked: bool

    def __post_init__(self) -> None:
        _validate_identifier(self.decision_id, field="decision_id", max_length=128)
        _validate_identifier(self.prediction_id, field="prediction_id", max_length=128)
        _validate_identifier(
            self.feature_snapshot_id, field="feature_snapshot_id", max_length=128
        )
        _validate_identifier(self.symbol, field="symbol", max_length=32)
        if self.symbol != self.symbol.upper():
            raise OrchestratorDecisionDomainError(
                "must_be_uppercase", field="symbol"
            )

        if not isinstance(self.decision_ts_ms, int) or isinstance(
            self.decision_ts_ms, bool
        ):
            raise OrchestratorDecisionDomainError(
                "must_be_int", field="decision_ts_ms"
            )
        if self.decision_ts_ms < 0:
            raise OrchestratorDecisionDomainError(
                "must_be_nonnegative", field="decision_ts_ms"
            )

        _validate_member(
            self.decision_action,
            field="decision_action",
            allowed_values=_ALLOWED_DECISION_ACTIONS,
            reason="invalid_decision_action",
        )
        _validate_member(
            self.decision_reason_code,
            field="decision_reason_code",
            allowed_values=_ALLOWED_DECISION_REASONS,
            reason="invalid_decision_reason_code",
        )
        _validate_member(
            self.input_prediction_direction,
            field="input_prediction_direction",
            allowed_values=_ALLOWED_INPUT_PREDICTION_DIRECTIONS,
            reason="invalid_input_prediction_direction",
        )

        if not isinstance(
            self.input_prediction_confidence_calibrated, float
        ) or isinstance(self.input_prediction_confidence_calibrated, bool):
            raise OrchestratorDecisionDomainError(
                "must_be_float", field="input_prediction_confidence_calibrated"
            )
        if not math.isfinite(self.input_prediction_confidence_calibrated):
            raise OrchestratorDecisionDomainError(
                "must_be_finite", field="input_prediction_confidence_calibrated"
            )
        if not 0.0 <= self.input_prediction_confidence_calibrated <= 1.0:
            raise OrchestratorDecisionDomainError(
                "must_be_in_unit_interval",
                field="input_prediction_confidence_calibrated",
            )

        _validate_member(
            self.input_prediction_freshness_flag,
            field="input_prediction_freshness_flag",
            allowed_values=_ALLOWED_INPUT_PREDICTION_FRESHNESS,
            reason="invalid_input_prediction_freshness_flag",
        )
        _validate_member(
            self.input_worker_health_status,
            field="input_worker_health_status",
            allowed_values=_ALLOWED_INPUT_WORKER_HEALTH_STATUSES,
            reason="invalid_input_worker_health_status",
        )

        if not isinstance(self.live_blocked, bool):
            raise OrchestratorDecisionDomainError(
                "must_be_bool", field="live_blocked"
            )
        if self.live_blocked is not True:
            raise OrchestratorDecisionDomainError("must_be_true", field="live_blocked")

        if self.decision_action == DECISION_ACTION_OPEN_LONG:
            if self.decision_reason_code != DECISION_REASON_PROCEED_LONG:
                raise OrchestratorDecisionDomainError(
                    "open_long_requires_proceed_long_reason",
                    field="decision_reason_code",
                )
            if self.input_prediction_direction != "long":
                raise OrchestratorDecisionDomainError(
                    "open_long_requires_long_input_direction",
                    field="input_prediction_direction",
                )
        if self.decision_action == DECISION_ACTION_OPEN_SHORT:
            if self.decision_reason_code != DECISION_REASON_PROCEED_SHORT:
                raise OrchestratorDecisionDomainError(
                    "open_short_requires_proceed_short_reason",
                    field="decision_reason_code",
                )
            if self.input_prediction_direction != "short":
                raise OrchestratorDecisionDomainError(
                    "open_short_requires_short_input_direction",
                    field="input_prediction_direction",
                )
        if self.decision_action == DECISION_ACTION_HOLD:
            if self.decision_reason_code != DECISION_REASON_HOLD_FLAT_DIRECTION:
                raise OrchestratorDecisionDomainError(
                    "hold_requires_hold_flat_direction_reason",
                    field="decision_reason_code",
                )
            if self.input_prediction_direction != "flat":
                raise OrchestratorDecisionDomainError(
                    "hold_requires_flat_input_direction",
                    field="input_prediction_direction",
                )
        if self.decision_action == DECISION_ACTION_ABSTAIN:
            if not self.decision_reason_code.startswith("abstain_"):
                raise OrchestratorDecisionDomainError(
                    "abstain_requires_abstain_prefix_reason",
                    field="decision_reason_code",
                )
