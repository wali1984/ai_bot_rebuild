from __future__ import annotations

from dataclasses import dataclass

from .degraded_source_state import (
    _ALLOWED_DEGRADED_SOURCE_STATES,
    _FAIL_CLOSED_TRIGGER_STATES,
)
from .errors import DegradedStateFailClosedGatesDomainError


_ALLOWED_TRAINER_WORKER_LIVENESS = frozenset({"alive", "degraded", "worker_dead"})


@dataclass(frozen=True, slots=True)
class DegradedStateRecord:
    degraded_state_id: str
    smc_state: str
    smc_age_ms: int
    liq_state: str
    liq_age_ms: int
    oi_state: str
    oi_age_ms: int
    orderbook_state: str
    orderbook_age_ms: int
    fail_closed: bool
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    risk_decision_id: str
    model_version: str
    checkpoint_id: str
    confidence_raw: float
    confidence_calibrated: float
    trainer_worker_liveness: str
    live_blocked: bool

    def __post_init__(self) -> None:
        _validate_id(self.degraded_state_id, field="degraded_state_id")
        _validate_source_state(self.smc_state, field="smc_state")
        _validate_age_ms(self.smc_age_ms, field="smc_age_ms")
        _validate_source_state(self.liq_state, field="liq_state")
        _validate_age_ms(self.liq_age_ms, field="liq_age_ms")
        _validate_source_state(self.oi_state, field="oi_state")
        _validate_age_ms(self.oi_age_ms, field="oi_age_ms")
        _validate_source_state(self.orderbook_state, field="orderbook_state")
        _validate_age_ms(self.orderbook_age_ms, field="orderbook_age_ms")
        _validate_fail_closed_bool(self.fail_closed)
        expected_fail_closed = (
            self.smc_state in _FAIL_CLOSED_TRIGGER_STATES
            or self.liq_state in _FAIL_CLOSED_TRIGGER_STATES
            or self.oi_state in _FAIL_CLOSED_TRIGGER_STATES
            or self.orderbook_state in _FAIL_CLOSED_TRIGGER_STATES
        )
        if self.fail_closed is not expected_fail_closed:
            raise DegradedStateFailClosedGatesDomainError(
                "fail_closed_inconsistent_with_per_source_states",
                field="fail_closed",
            )
        _validate_id(self.decision_id, field="decision_id")
        _validate_id(self.prediction_id, field="prediction_id")
        _validate_id(self.feature_snapshot_id, field="feature_snapshot_id")
        _validate_id(self.risk_decision_id, field="risk_decision_id")
        _validate_text(self.model_version, field="model_version")
        _validate_text(self.checkpoint_id, field="checkpoint_id")
        _validate_confidence(self.confidence_raw, field="confidence_raw")
        _validate_confidence(
            self.confidence_calibrated,
            field="confidence_calibrated",
        )
        _validate_trainer_worker_liveness(self.trainer_worker_liveness)
        _validate_live_blocked(self.live_blocked)


def _validate_text(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise DegradedStateFailClosedGatesDomainError("must_be_str", field=field)
    if value == "":
        raise DegradedStateFailClosedGatesDomainError(
            "must_be_non_empty",
            field=field,
        )


def _validate_id(value: str, *, field: str) -> None:
    _validate_text(value, field=field)
    if value != value.strip() or any(char.isspace() for char in value):
        raise DegradedStateFailClosedGatesDomainError(
            "must_not_have_whitespace",
            field=field,
        )
    if len(value) > 128:
        raise DegradedStateFailClosedGatesDomainError(
            "must_be_at_most_128_chars",
            field=field,
        )


def _validate_age_ms(value: int, *, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DegradedStateFailClosedGatesDomainError(
            "must_be_int",
            field=field,
        )
    if value < 0:
        raise DegradedStateFailClosedGatesDomainError(
            "must_be_nonnegative",
            field=field,
        )


def _validate_source_state(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise DegradedStateFailClosedGatesDomainError(
            "must_be_str",
            field=field,
        )
    if value not in _ALLOWED_DEGRADED_SOURCE_STATES:
        raise DegradedStateFailClosedGatesDomainError(
            "invalid_degraded_source_state",
            field=field,
        )


def _validate_fail_closed_bool(value: bool) -> None:
    if not isinstance(value, bool):
        raise DegradedStateFailClosedGatesDomainError(
            "must_be_bool",
            field="fail_closed",
        )


def _validate_confidence(value: float, *, field: str) -> None:
    if not isinstance(value, float) or isinstance(value, bool):
        raise DegradedStateFailClosedGatesDomainError("must_be_float", field=field)
    if value < 0.0 or value > 1.0:
        raise DegradedStateFailClosedGatesDomainError(
            "must_be_between_zero_and_one",
            field=field,
        )


def _validate_trainer_worker_liveness(value: str) -> None:
    if not isinstance(value, str):
        raise DegradedStateFailClosedGatesDomainError(
            "must_be_str",
            field="trainer_worker_liveness",
        )
    if value not in _ALLOWED_TRAINER_WORKER_LIVENESS:
        raise DegradedStateFailClosedGatesDomainError(
            "invalid_trainer_worker_liveness",
            field="trainer_worker_liveness",
        )


def _validate_live_blocked(value: bool) -> None:
    if not isinstance(value, bool):
        raise DegradedStateFailClosedGatesDomainError(
            "must_be_bool",
            field="live_blocked",
        )
    if value is not True:
        raise DegradedStateFailClosedGatesDomainError(
            "must_be_true",
            field="live_blocked",
        )
