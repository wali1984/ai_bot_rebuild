from __future__ import annotations

from dataclasses import dataclass

from .errors import ExternalManualPositionQuarantineDomainError
from .flag import ManualPositionFlag


_ALLOWED_TRAINER_WORKER_LIVENESS = frozenset(
    {
        "alive",
        "degraded",
        "worker_dead",
    }
)


@dataclass(frozen=True, slots=True)
class ExternalPositionQuarantineRecord:
    risk_decision_id: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    risk_decision_ts_ms: int
    manual_position_flag: ManualPositionFlag
    model_version: str
    checkpoint_id: str
    confidence_raw: float
    confidence_calibrated: float
    trainer_worker_liveness: str
    live_blocked: bool

    def __post_init__(self) -> None:
        _validate_id_field(self.risk_decision_id, field="risk_decision_id")
        _validate_id_field(self.decision_id, field="decision_id")
        _validate_id_field(self.prediction_id, field="prediction_id")
        _validate_id_field(self.feature_snapshot_id, field="feature_snapshot_id")
        _validate_symbol(self.symbol)
        _validate_ts_ms(self.risk_decision_ts_ms)
        _validate_manual_position_flag(self.manual_position_flag)
        _validate_text(self.model_version, field="model_version")
        _validate_text(self.checkpoint_id, field="checkpoint_id")
        _validate_confidence(self.confidence_raw, field="confidence_raw")
        _validate_confidence(
            self.confidence_calibrated,
            field="confidence_calibrated",
        )
        _validate_trainer_worker_liveness(self.trainer_worker_liveness)
        _validate_live_blocked(self.live_blocked)


def _validate_id_field(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise ExternalManualPositionQuarantineDomainError("must_be_str", field=field)
    if value == "":
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_non_empty",
            field=field,
        )
    if value != value.strip() or any(char.isspace() for char in value):
        raise ExternalManualPositionQuarantineDomainError(
            "must_not_have_whitespace",
            field=field,
        )
    if len(value) > 128:
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_at_most_128_chars",
            field=field,
        )


def _validate_symbol(value: str) -> None:
    if not isinstance(value, str):
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_str",
            field="symbol",
        )
    if value == "":
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_non_empty",
            field="symbol",
        )
    if any(char.isspace() for char in value):
        raise ExternalManualPositionQuarantineDomainError(
            "must_not_have_whitespace",
            field="symbol",
        )
    if len(value) > 32:
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_at_most_32_chars",
            field="symbol",
        )
    if value != value.upper():
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_uppercase",
            field="symbol",
        )


def _validate_ts_ms(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_int",
            field="risk_decision_ts_ms",
        )
    if value < 0:
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_nonnegative",
            field="risk_decision_ts_ms",
        )


def _validate_manual_position_flag(value: ManualPositionFlag) -> None:
    if not isinstance(value, ManualPositionFlag):
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_manual_position_flag",
            field="manual_position_flag",
        )


def _validate_text(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise ExternalManualPositionQuarantineDomainError("must_be_str", field=field)
    if value == "":
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_non_empty",
            field=field,
        )


def _validate_confidence(value: float, *, field: str) -> None:
    if not isinstance(value, float) or isinstance(value, bool):
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_float",
            field=field,
        )
    if value < 0.0 or value > 1.0:
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_between_zero_and_one",
            field=field,
        )


def _validate_trainer_worker_liveness(value: str) -> None:
    if not isinstance(value, str):
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_str",
            field="trainer_worker_liveness",
        )
    if value not in _ALLOWED_TRAINER_WORKER_LIVENESS:
        raise ExternalManualPositionQuarantineDomainError(
            "invalid_trainer_worker_liveness",
            field="trainer_worker_liveness",
        )


def _validate_live_blocked(value: bool) -> None:
    if not isinstance(value, bool):
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_bool",
            field="live_blocked",
        )
    if value is not True:
        raise ExternalManualPositionQuarantineDomainError(
            "must_be_true",
            field="live_blocked",
        )
