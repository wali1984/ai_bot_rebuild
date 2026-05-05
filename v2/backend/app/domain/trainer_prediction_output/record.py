from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import TrainerPredictionDomainError


PREDICTION_DIRECTION_LONG = "long"
PREDICTION_DIRECTION_SHORT = "short"
PREDICTION_DIRECTION_FLAT = "flat"
PREDICTION_FRESHNESS_FRESH = "fresh"
PREDICTION_FRESHNESS_STALE = "stale"
PREDICTION_FRESHNESS_MISSING = "missing"

_ALLOWED_DIRECTIONS = frozenset(
    {PREDICTION_DIRECTION_LONG, PREDICTION_DIRECTION_SHORT, PREDICTION_DIRECTION_FLAT}
)
_ALLOWED_FRESHNESS = frozenset(
    {
        PREDICTION_FRESHNESS_FRESH,
        PREDICTION_FRESHNESS_STALE,
        PREDICTION_FRESHNESS_MISSING,
    }
)
_ALLOWED_WORKER_HEALTH_STATUSES = frozenset({"HEALTHY", "DEGRADED", "CRITICAL", "UNKNOWN"})


def _raise(reason: str, field: str) -> None:
    raise TrainerPredictionDomainError(reason, field=field)


def _ensure_id(value: str, field: str, max_length: int) -> None:
    if not isinstance(value, str):
        _raise("must_be_str", field)
    if len(value) < 1:
        _raise("must_be_non_empty", field)
    if value.strip() != value or any(character.isspace() for character in value):
        _raise("must_not_have_whitespace", field)
    if len(value) > max_length:
        _raise(f"must_be_at_most_{max_length}_chars", field)


def _ensure_non_empty_string(value: str, field: str, max_length: int) -> None:
    if not isinstance(value, str):
        _raise("must_be_str", field)
    if len(value) < 1:
        _raise("must_be_non_empty", field)
    if len(value) > max_length:
        _raise(f"must_be_at_most_{max_length}_chars", field)


def _ensure_nonnegative_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        _raise("must_be_int", field)
    if value < 0:
        _raise("must_be_nonnegative", field)


def _ensure_confidence(value: float, field: str) -> None:
    if not isinstance(value, float) or isinstance(value, bool):
        _raise("must_be_float", field)
    if not math.isfinite(value):
        _raise("must_be_finite", field)
    if value < 0.0 or value > 1.0:
        _raise("must_be_in_unit_interval", field)


def _ensure_feature_codes(value: tuple[str, ...], field: str) -> None:
    if type(value) is not tuple:
        _raise("must_be_tuple", field)
    if len(value) > 8:
        _raise("must_be_at_most_8_entries", field)

    seen = set()
    for code in value:
        if not isinstance(code, str):
            _raise("must_be_str", field)
        if len(code) < 1:
            _raise("must_be_non_empty", field)
        if code.strip() != code or any(character.isspace() for character in code):
            _raise("must_not_have_whitespace", field)
        if len(code) > 64:
            _raise("must_be_at_most_64_chars", field)
        if code in seen:
            _raise("must_be_unique", field)
        seen.add(code)


@dataclass(frozen=True, slots=True)
class TrainerPredictionRecord:
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    model_version: str
    checkpoint_id: str
    prediction_ts_ms: int
    direction: str
    confidence_raw: float
    confidence_calibrated: float
    worker_id: str
    worker_health_status: str
    freshness_flag: str
    source_freshness_age_ms: int | None
    top_positive_feature_codes: tuple[str, ...]
    top_negative_feature_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _ensure_id(self.prediction_id, "prediction_id", 128)
        _ensure_id(self.feature_snapshot_id, "feature_snapshot_id", 128)

        if not isinstance(self.symbol, str):
            _raise("must_be_str", "symbol")
        if len(self.symbol) < 1:
            _raise("must_be_non_empty", "symbol")
        if self.symbol.strip() != self.symbol or any(character.isspace() for character in self.symbol):
            _raise("must_not_have_whitespace", "symbol")
        if len(self.symbol) > 32:
            _raise("must_be_at_most_32_chars", "symbol")
        if self.symbol != self.symbol.upper():
            _raise("must_be_uppercase", "symbol")

        _ensure_non_empty_string(self.model_version, "model_version", 64)
        _ensure_non_empty_string(self.checkpoint_id, "checkpoint_id", 128)
        _ensure_nonnegative_int(self.prediction_ts_ms, "prediction_ts_ms")

        if not isinstance(self.direction, str):
            _raise("must_be_str", "direction")
        if self.direction not in _ALLOWED_DIRECTIONS:
            _raise("invalid_direction", "direction")

        _ensure_confidence(self.confidence_raw, "confidence_raw")
        _ensure_confidence(self.confidence_calibrated, "confidence_calibrated")
        _ensure_non_empty_string(self.worker_id, "worker_id", 64)

        if not isinstance(self.worker_health_status, str):
            _raise("must_be_str", "worker_health_status")
        if self.worker_health_status not in _ALLOWED_WORKER_HEALTH_STATUSES:
            _raise("invalid_worker_health_status", "worker_health_status")

        if not isinstance(self.freshness_flag, str):
            _raise("must_be_str", "freshness_flag")
        if self.freshness_flag not in _ALLOWED_FRESHNESS:
            _raise("invalid_freshness_flag", "freshness_flag")

        if self.source_freshness_age_ms is not None:
            if not isinstance(self.source_freshness_age_ms, int) or isinstance(
                self.source_freshness_age_ms, bool
            ):
                _raise("must_be_int_or_none", "source_freshness_age_ms")
            if self.source_freshness_age_ms < 0:
                _raise("must_be_nonnegative", "source_freshness_age_ms")

        _ensure_feature_codes(self.top_positive_feature_codes, "top_positive_feature_codes")
        _ensure_feature_codes(self.top_negative_feature_codes, "top_negative_feature_codes")

        if set(self.top_positive_feature_codes).intersection(self.top_negative_feature_codes):
            _raise("must_be_disjoint_from_top_positive", "top_negative_feature_codes")
        if (
            self.freshness_flag == PREDICTION_FRESHNESS_MISSING
            and self.source_freshness_age_ms is not None
        ):
            _raise("missing_requires_none_age", "source_freshness_age_ms")
        if self.freshness_flag in {
            PREDICTION_FRESHNESS_FRESH,
            PREDICTION_FRESHNESS_STALE,
        } and self.source_freshness_age_ms is None:
            _raise("freshness_requires_int_age", "source_freshness_age_ms")
