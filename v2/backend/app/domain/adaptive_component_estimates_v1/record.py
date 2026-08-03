from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields
from typing import Any

from .errors import AdaptiveComponentEstimateDomainError

SCHEMA_VERSION = "AdaptiveComponentEstimatesV1"
AUTHORITY_MODE = "SHADOW_DIAGNOSTIC_ONLY"
LIVE_GATE = "blocked_human_only"

AVAILABLE = "AVAILABLE"
UNAVAILABLE = "UNAVAILABLE"

CALIBRATED_PROBABILITY = "CALIBRATED_PROBABILITY"
EMPIRICAL_RATE = "EMPIRICAL_RATE"
EMPIRICAL_ESTIMATE = "EMPIRICAL_ESTIMATE"
HEURISTIC_SCORE = "HEURISTIC_SCORE"
POINT_ESTIMATE = "POINT_ESTIMATE"
FACT = "FACT"
CALIBRATED_DISTRIBUTION = "CALIBRATED_DISTRIBUTION"
EMPIRICAL_DISTRIBUTION = "EMPIRICAL_DISTRIBUTION"

_SCALAR_KINDS = frozenset(
    {
        CALIBRATED_PROBABILITY,
        EMPIRICAL_RATE,
        EMPIRICAL_ESTIMATE,
        HEURISTIC_SCORE,
        POINT_ESTIMATE,
        FACT,
    }
)
_DISTRIBUTION_KINDS = frozenset({CALIBRATED_DISTRIBUTION, EMPIRICAL_DISTRIBUTION})
_PROBABILITY_KINDS = frozenset({CALIBRATED_PROBABILITY, EMPIRICAL_RATE})
_CALIBRATED_KINDS = frozenset({CALIBRATED_PROBABILITY, CALIBRATED_DISTRIBUTION})
_EMPIRICAL_KINDS = frozenset({EMPIRICAL_RATE, EMPIRICAL_ESTIMATE, EMPIRICAL_DISTRIBUTION})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,95}$")
_TOLERANCE = 1e-9

COMPONENT_NAMES = (
    "confidence",
    "execution_quality",
    "exit_feasibility",
    "loss_risk",
    "mfe_mae",
    "microstructure",
    "outcome_memory",
    "regime",
)

REGIME_CATEGORIES = (
    "fakeout_risk",
    "liquidity_sweep",
    "no_trade",
    "ranging",
    "trending_down",
    "trending_up",
    "volatile_expansion",
)


@dataclass(frozen=True, slots=True)
class _ScalarMetricSpec:
    semantic_kinds: frozenset[str]
    unit: str
    value_type: str
    horizon_required: bool
    sample_required: bool
    minimum_value: float | None = None
    maximum_value: float | None = None


@dataclass(frozen=True, slots=True)
class _DistributionMetricSpec:
    semantic_kinds: frozenset[str]
    unit: str
    quantile_probabilities: tuple[float, ...]
    minimum_value: float | None = None
    maximum_value: float | None = None


_REQUIRED_SCALARS = {
    "confidence": frozenset({"calibrated_action_probability", "policy_uncertainty"}),
    "execution_quality": frozenset(
        {
            "estimated_delay_ms",
            "expected_transaction_cost_bps",
            "fill_probability",
            "minimum_executable_capital_usd",
            "partial_fill_probability",
            "rounded_valid_quantity",
            "venue_feasible",
        }
    ),
    "exit_feasibility": frozenset(
        {
            "exit_fill_probability",
            "exit_uncertainty",
            "profit_exit_probability",
            "stop_execution_probability",
        }
    ),
    "loss_risk": frozenset(
        {
            "correlation_contribution",
            "drawdown_contribution_bps",
            "liquidation_risk_probability",
            "loss_probability",
            "stop_out_probability",
        }
    ),
    "mfe_mae": frozenset(),
    "microstructure": frozenset(
        {
            "adverse_selection_probability",
            "available_liquidity_capacity_usd",
            "execution_uncertainty",
            "fill_probability",
            "short_horizon_reversal_probability",
        }
    ),
    "outcome_memory": frozenset(
        {
            "after_cost_expectancy_bps",
            "missed_tp_then_stop_probability",
            "posterior_uncertainty",
            "reversal_probability",
            "slippage_failure_probability",
            "win_rate_posterior_mean",
        }
    ),
    "regime": frozenset(),
}

_REQUIRED_DISTRIBUTIONS = {
    "confidence": frozenset(),
    "execution_quality": frozenset(
        {"fill_delay_ms_distribution", "transaction_cost_bps_distribution"}
    ),
    "exit_feasibility": frozenset(),
    "loss_risk": frozenset({"return_bps_distribution", "tail_loss_bps_distribution"}),
    "mfe_mae": frozenset({"mae_bps_distribution", "mfe_bps_distribution"}),
    "microstructure": frozenset({"market_impact_bps_distribution", "slippage_bps_distribution"}),
    "outcome_memory": frozenset(),
    "regime": frozenset(),
}

_REQUIRED_CATEGORICALS = {
    component: frozenset({"regime_probabilities"}) if component == "regime" else frozenset()
    for component in COMPONENT_NAMES
}

_SCALAR_METRIC_SPECS = {
    "calibrated_action_probability": _ScalarMetricSpec(
        frozenset({CALIBRATED_PROBABILITY}), "probability_0_1", "float", True, True
    ),
    "policy_uncertainty": _ScalarMetricSpec(
        frozenset({POINT_ESTIMATE}), "probability_0_1", "float", True, False
    ),
    "estimated_delay_ms": _ScalarMetricSpec(
        frozenset({POINT_ESTIMATE}),
        "milliseconds",
        "float",
        True,
        False,
        minimum_value=0.0,
    ),
    "expected_transaction_cost_bps": _ScalarMetricSpec(
        frozenset({POINT_ESTIMATE}),
        "bps",
        "float",
        True,
        False,
        minimum_value=0.0,
    ),
    "fill_probability": _ScalarMetricSpec(
        frozenset({CALIBRATED_PROBABILITY}), "probability_0_1", "float", True, True
    ),
    "minimum_executable_capital_usd": _ScalarMetricSpec(
        frozenset({FACT}), "USD", "float", False, False, minimum_value=0.0
    ),
    "partial_fill_probability": _ScalarMetricSpec(
        frozenset({CALIBRATED_PROBABILITY}), "probability_0_1", "float", True, True
    ),
    "rounded_valid_quantity": _ScalarMetricSpec(
        frozenset({FACT}),
        "base_asset_quantity",
        "float",
        False,
        False,
        minimum_value=0.0,
    ),
    "venue_feasible": _ScalarMetricSpec(frozenset({FACT}), "boolean", "bool", False, False),
    "exit_fill_probability": _ScalarMetricSpec(
        frozenset({CALIBRATED_PROBABILITY}), "probability_0_1", "float", True, True
    ),
    "exit_uncertainty": _ScalarMetricSpec(
        frozenset({POINT_ESTIMATE}), "probability_0_1", "float", True, False
    ),
    "profit_exit_probability": _ScalarMetricSpec(
        frozenset({CALIBRATED_PROBABILITY}), "probability_0_1", "float", True, True
    ),
    "stop_execution_probability": _ScalarMetricSpec(
        frozenset({CALIBRATED_PROBABILITY}), "probability_0_1", "float", True, True
    ),
    "correlation_contribution": _ScalarMetricSpec(
        frozenset({POINT_ESTIMATE}),
        "correlation",
        "float",
        True,
        False,
        minimum_value=-1.0,
        maximum_value=1.0,
    ),
    "drawdown_contribution_bps": _ScalarMetricSpec(
        frozenset({POINT_ESTIMATE}), "bps", "float", True, False
    ),
    "liquidation_risk_probability": _ScalarMetricSpec(
        frozenset({CALIBRATED_PROBABILITY}), "probability_0_1", "float", True, True
    ),
    "loss_probability": _ScalarMetricSpec(
        frozenset({CALIBRATED_PROBABILITY}), "probability_0_1", "float", True, True
    ),
    "stop_out_probability": _ScalarMetricSpec(
        frozenset({CALIBRATED_PROBABILITY}), "probability_0_1", "float", True, True
    ),
    "adverse_selection_probability": _ScalarMetricSpec(
        frozenset({CALIBRATED_PROBABILITY}), "probability_0_1", "float", True, True
    ),
    "available_liquidity_capacity_usd": _ScalarMetricSpec(
        frozenset({POINT_ESTIMATE}),
        "USD",
        "float",
        True,
        False,
        minimum_value=0.0,
    ),
    "execution_uncertainty": _ScalarMetricSpec(
        frozenset({POINT_ESTIMATE}), "probability_0_1", "float", True, False
    ),
    "short_horizon_reversal_probability": _ScalarMetricSpec(
        frozenset({CALIBRATED_PROBABILITY}), "probability_0_1", "float", True, True
    ),
    "after_cost_expectancy_bps": _ScalarMetricSpec(
        frozenset({EMPIRICAL_ESTIMATE}), "bps", "float", False, True
    ),
    "missed_tp_then_stop_probability": _ScalarMetricSpec(
        frozenset({EMPIRICAL_RATE}), "probability_0_1", "float", False, True
    ),
    "posterior_uncertainty": _ScalarMetricSpec(
        frozenset({POINT_ESTIMATE}), "probability_0_1", "float", False, True
    ),
    "reversal_probability": _ScalarMetricSpec(
        frozenset({EMPIRICAL_RATE}), "probability_0_1", "float", False, True
    ),
    "slippage_failure_probability": _ScalarMetricSpec(
        frozenset({EMPIRICAL_RATE}), "probability_0_1", "float", False, True
    ),
    "win_rate_posterior_mean": _ScalarMetricSpec(
        frozenset({EMPIRICAL_RATE}), "probability_0_1", "float", False, True
    ),
}

_DISTRIBUTION_METRIC_SPECS = {
    "fill_delay_ms_distribution": _DistributionMetricSpec(
        frozenset({CALIBRATED_DISTRIBUTION, EMPIRICAL_DISTRIBUTION}),
        "milliseconds",
        (0.1, 0.5, 0.9),
        minimum_value=0.0,
    ),
    "transaction_cost_bps_distribution": _DistributionMetricSpec(
        frozenset({CALIBRATED_DISTRIBUTION, EMPIRICAL_DISTRIBUTION}),
        "bps",
        (0.1, 0.5, 0.9),
    ),
    "return_bps_distribution": _DistributionMetricSpec(
        frozenset({CALIBRATED_DISTRIBUTION, EMPIRICAL_DISTRIBUTION}),
        "bps",
        (0.1, 0.5, 0.9),
    ),
    "tail_loss_bps_distribution": _DistributionMetricSpec(
        frozenset({CALIBRATED_DISTRIBUTION, EMPIRICAL_DISTRIBUTION}),
        "bps",
        (0.1, 0.5, 0.9),
    ),
    "mae_bps_distribution": _DistributionMetricSpec(
        frozenset({CALIBRATED_DISTRIBUTION, EMPIRICAL_DISTRIBUTION}),
        "bps",
        (0.1, 0.5, 0.9),
    ),
    "mfe_bps_distribution": _DistributionMetricSpec(
        frozenset({CALIBRATED_DISTRIBUTION, EMPIRICAL_DISTRIBUTION}),
        "bps",
        (0.1, 0.5, 0.9),
    ),
    "market_impact_bps_distribution": _DistributionMetricSpec(
        frozenset({CALIBRATED_DISTRIBUTION, EMPIRICAL_DISTRIBUTION}),
        "bps",
        (0.1, 0.5, 0.9),
    ),
    "slippage_bps_distribution": _DistributionMetricSpec(
        frozenset({CALIBRATED_DISTRIBUTION, EMPIRICAL_DISTRIBUTION}),
        "bps",
        (0.1, 0.5, 0.9),
    ),
}

_SEMANTIC_FINGERPRINT_EXCLUDED = frozenset({"bundle_id"})


def _raise(reason: str, field: str) -> None:
    raise AdaptiveComponentEstimateDomainError(reason, field=field)


def _require_identifier(value: object, field: str, max_length: int = 160) -> None:
    if not isinstance(value, str) or not value:
        _raise("must_be_non_empty_string", field)
    if value.strip() != value or any(character.isspace() for character in value):
        _raise("must_not_have_whitespace", field)
    if len(value) > max_length:
        _raise(f"must_be_at_most_{max_length}_chars", field)


def _require_name(value: object, field: str) -> None:
    if not isinstance(value, str) or _NAME_RE.fullmatch(value) is None:
        _raise("must_be_lower_snake_case_name", field)


def _require_sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _raise("must_be_lowercase_sha256", field)


def _require_int(value: object, field: str, minimum: int = 0) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        _raise("must_be_int", field)
    if value < minimum:
        _raise(f"must_be_at_least_{minimum}", field)


def _require_finite(value: object, field: str) -> None:
    if not isinstance(value, float) or isinstance(value, bool) or not math.isfinite(value):
        _raise("must_be_finite_float", field)


def _require_sorted_shas(value: object, field: str, *, allow_empty: bool) -> None:
    if type(value) is not tuple:
        _raise("must_be_tuple", field)
    if not allow_empty and not value:
        _raise("must_be_non_empty", field)
    if len(set(value)) != len(value) or value != tuple(sorted(value)):
        _raise("must_be_unique_and_sorted", field)
    for index, item in enumerate(value):
        _require_sha256(item, f"{field}[{index}]")


def _require_exact_keys(value: object, expected: frozenset[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _raise("must_be_object", field)
    actual = frozenset(value)
    if actual != expected:
        _raise(
            "exact_keys_required:"
            f"missing={sorted(expected - actual)}:"
            f"extra={sorted(actual - expected)}",
            field,
        )
    return value


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _raise("duplicate_json_key", key)
        result[key] = value
    return result


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class QuantileV1:
    probability: float
    value: float

    def __post_init__(self) -> None:
        _require_finite(self.probability, "quantile.probability")
        if not 0.0 < self.probability < 1.0:
            _raise("must_be_strictly_inside_unit_interval", "quantile.probability")
        _require_finite(self.value, "quantile.value")


@dataclass(frozen=True, slots=True)
class CategoryProbabilityV1:
    category: str
    probability: float

    def __post_init__(self) -> None:
        _require_name(self.category, "category_probability.category")
        _require_finite(self.probability, "category_probability.probability")
        if not 0.0 <= self.probability <= 1.0:
            _raise("must_be_in_unit_interval", "category_probability.probability")


@dataclass(frozen=True, slots=True)
class CalibrationEvidenceV1:
    component_name: str
    metric_name: str
    calibration_receipt_sha256: str
    fitted: bool
    probability_semantics_valid: bool
    model_id: str
    model_parameter_fingerprint: str
    row_digest: str
    calibration_population_sha256: str
    calibration_window_start_ms: int
    calibration_window_end_ms: int
    sample_count: int
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str

    def __post_init__(self) -> None:
        if self.component_name not in COMPONENT_NAMES:
            _raise("invalid_component", "calibration.component_name")
        _require_name(self.metric_name, "calibration.metric_name")
        for field in (
            "calibration_receipt_sha256",
            "model_parameter_fingerprint",
            "row_digest",
            "calibration_population_sha256",
            "checkpoint_sha256",
        ):
            _require_sha256(getattr(self, field), f"calibration.{field}")
        _require_identifier(self.model_id, "calibration.model_id")
        _require_identifier(self.checkpoint_id, "calibration.checkpoint_id")
        if self.fitted is not True:
            _raise("must_be_true", "calibration.fitted")
        if self.probability_semantics_valid is not True:
            _raise("must_be_true", "calibration.probability_semantics_valid")
        _require_int(
            self.calibration_window_start_ms,
            "calibration.calibration_window_start_ms",
        )
        _require_int(
            self.calibration_window_end_ms,
            "calibration.calibration_window_end_ms",
        )
        if self.calibration_window_start_ms > self.calibration_window_end_ms:
            _raise("window_order_invalid", "calibration.calibration_window_end_ms")
        _require_int(self.sample_count, "calibration.sample_count", 1)
        _require_int(self.checkpoint_generation, "calibration.checkpoint_generation", 1)


@dataclass(frozen=True, slots=True)
class ScalarEstimateV1:
    name: str
    availability: str
    semantic_kind: str
    value: float | bool | None
    unit: str | None
    horizon_seconds: int | None
    sample_count: int | None
    producer_id: str | None
    source_field: str | None
    source_schema: str | None
    model_id: str | None
    calibration_evidence: CalibrationEvidenceV1 | None
    source_receipt_sha256s: tuple[str, ...]
    unavailable_reason: str | None

    def __post_init__(self) -> None:
        _require_name(self.name, "scalar.name")
        if self.availability not in {AVAILABLE, UNAVAILABLE}:
            _raise("invalid_availability", f"scalar.{self.name}.availability")
        _require_sorted_shas(
            self.source_receipt_sha256s,
            f"scalar.{self.name}.source_receipt_sha256s",
            allow_empty=self.availability == UNAVAILABLE,
        )
        if self.availability == UNAVAILABLE:
            if self.semantic_kind != UNAVAILABLE:
                _raise("unavailable_requires_UNAVAILABLE_kind", f"scalar.{self.name}")
            if any(
                value is not None
                for value in (
                    self.value,
                    self.unit,
                    self.horizon_seconds,
                    self.sample_count,
                    self.producer_id,
                    self.source_field,
                    self.source_schema,
                    self.model_id,
                    self.calibration_evidence,
                )
            ):
                _raise("unavailable_requires_null_estimate_fields", f"scalar.{self.name}")
            if not isinstance(self.unavailable_reason, str) or not self.unavailable_reason.strip():
                _raise("unavailable_reason_required", f"scalar.{self.name}")
            return
        if self.semantic_kind not in _SCALAR_KINDS:
            _raise("invalid_semantic_kind", f"scalar.{self.name}.semantic_kind")
        for field in ("producer_id", "source_field", "source_schema"):
            _require_identifier(getattr(self, field), f"scalar.{self.name}.{field}")
        if self.semantic_kind == FACT:
            if self.model_id is not None:
                _raise("fact_forbids_model_id", f"scalar.{self.name}.model_id")
        else:
            _require_identifier(self.model_id, f"scalar.{self.name}.model_id")
        if not isinstance(self.unit, str) or not self.unit:
            _raise("unit_required", f"scalar.{self.name}.unit")
        if self.unavailable_reason is not None:
            _raise("available_forbids_unavailable_reason", f"scalar.{self.name}")
        if isinstance(self.value, bool):
            if self.semantic_kind != FACT or self.unit != "boolean":
                _raise("bool_requires_FACT_boolean", f"scalar.{self.name}.value")
        else:
            _require_finite(self.value, f"scalar.{self.name}.value")
        if self.horizon_seconds is not None:
            _require_int(self.horizon_seconds, f"scalar.{self.name}.horizon_seconds", 1)
        if self.sample_count is not None:
            _require_int(self.sample_count, f"scalar.{self.name}.sample_count")
        if self.unit == "probability_0_1":
            if not isinstance(self.value, float):
                _raise("probability_unit_requires_float", f"scalar.{self.name}")
            if not 0.0 <= self.value <= 1.0:
                _raise("must_be_in_unit_interval", f"scalar.{self.name}.value")
        spec = _SCALAR_METRIC_SPECS.get(self.name)
        if spec is not None:
            if self.semantic_kind not in spec.semantic_kinds:
                _raise("semantic_kind_does_not_match_metric", f"scalar.{self.name}")
            if self.unit != spec.unit:
                _raise("unit_does_not_match_metric", f"scalar.{self.name}")
            if spec.value_type == "bool" and not isinstance(self.value, bool):
                _raise("value_type_does_not_match_metric", f"scalar.{self.name}")
            if spec.value_type == "float" and (
                not isinstance(self.value, float) or isinstance(self.value, bool)
            ):
                _raise("value_type_does_not_match_metric", f"scalar.{self.name}")
            if spec.horizon_required and self.horizon_seconds is None:
                _raise("horizon_required_for_metric", f"scalar.{self.name}")
            if spec.sample_required and (self.sample_count is None or self.sample_count < 1):
                _raise("positive_sample_required_for_metric", f"scalar.{self.name}")
            if isinstance(self.value, float):
                if spec.minimum_value is not None and self.value < spec.minimum_value:
                    _raise("value_below_metric_minimum", f"scalar.{self.name}")
                if spec.maximum_value is not None and self.value > spec.maximum_value:
                    _raise("value_above_metric_maximum", f"scalar.{self.name}")
        elif self.semantic_kind != HEURISTIC_SCORE or "heuristic" not in self.name:
            _raise("unknown_metric_requires_namespaced_heuristic", f"scalar.{self.name}")
        if self.semantic_kind in _CALIBRATED_KINDS:
            if not isinstance(self.calibration_evidence, CalibrationEvidenceV1):
                _raise("structured_calibration_evidence_required", f"scalar.{self.name}")
            if (
                self.calibration_evidence.metric_name != self.name
                or self.calibration_evidence.model_id != self.model_id
            ):
                _raise("calibration_identity_mismatch", f"scalar.{self.name}")
            if self.sample_count != self.calibration_evidence.sample_count:
                _raise("calibration_sample_count_mismatch", f"scalar.{self.name}")
        elif self.calibration_evidence is not None:
            _raise("noncalibrated_kind_forbids_calibration_evidence", f"scalar.{self.name}")
        if self.semantic_kind in _EMPIRICAL_KINDS and (
            self.sample_count is None or self.sample_count < 1
        ):
            _raise("empirical_kind_requires_positive_sample", f"scalar.{self.name}")


@dataclass(frozen=True, slots=True)
class DistributionEstimateV1:
    name: str
    availability: str
    semantic_kind: str
    unit: str | None
    horizon_seconds: int | None
    quantiles: tuple[QuantileV1, ...]
    sample_count: int | None
    producer_id: str | None
    source_field: str | None
    source_schema: str | None
    model_id: str | None
    calibration_evidence: CalibrationEvidenceV1 | None
    source_receipt_sha256s: tuple[str, ...]
    unavailable_reason: str | None

    def __post_init__(self) -> None:
        _require_name(self.name, "distribution.name")
        if self.availability not in {AVAILABLE, UNAVAILABLE}:
            _raise("invalid_availability", f"distribution.{self.name}.availability")
        _require_sorted_shas(
            self.source_receipt_sha256s,
            f"distribution.{self.name}.source_receipt_sha256s",
            allow_empty=self.availability == UNAVAILABLE,
        )
        if self.availability == UNAVAILABLE:
            if self.semantic_kind != UNAVAILABLE:
                _raise("unavailable_requires_UNAVAILABLE_kind", f"distribution.{self.name}")
            if (
                self.unit is not None
                or self.horizon_seconds is not None
                or self.quantiles
                or self.sample_count is not None
                or self.producer_id is not None
                or self.source_field is not None
                or self.source_schema is not None
                or self.model_id is not None
                or self.calibration_evidence is not None
            ):
                _raise("unavailable_requires_null_estimate_fields", f"distribution.{self.name}")
            if not isinstance(self.unavailable_reason, str) or not self.unavailable_reason.strip():
                _raise("unavailable_reason_required", f"distribution.{self.name}")
            return
        if self.semantic_kind not in _DISTRIBUTION_KINDS:
            _raise("invalid_semantic_kind", f"distribution.{self.name}.semantic_kind")
        for field in ("producer_id", "source_field", "source_schema", "model_id"):
            _require_identifier(getattr(self, field), f"distribution.{self.name}.{field}")
        if not isinstance(self.unit, str) or not self.unit:
            _raise("unit_required", f"distribution.{self.name}.unit")
        _require_int(self.horizon_seconds, f"distribution.{self.name}.horizon_seconds", 1)
        if type(self.quantiles) is not tuple or not self.quantiles:
            _raise("quantiles_required", f"distribution.{self.name}.quantiles")
        if any(not isinstance(item, QuantileV1) for item in self.quantiles):
            _raise("must_contain_QuantileV1", f"distribution.{self.name}.quantiles")
        probabilities = tuple(item.probability for item in self.quantiles)
        values = tuple(item.value for item in self.quantiles)
        if probabilities != tuple(sorted(set(probabilities))):
            _raise("probabilities_must_be_unique_and_sorted", f"distribution.{self.name}")
        if values != tuple(sorted(values)):
            _raise("values_must_be_nondecreasing", f"distribution.{self.name}")
        spec = _DISTRIBUTION_METRIC_SPECS.get(self.name)
        if spec is None:
            _raise("unknown_distribution_metric", f"distribution.{self.name}")
        if self.semantic_kind not in spec.semantic_kinds:
            _raise("semantic_kind_does_not_match_metric", f"distribution.{self.name}")
        if self.unit != spec.unit:
            _raise("unit_does_not_match_metric", f"distribution.{self.name}")
        if probabilities != spec.quantile_probabilities:
            _raise("quantile_grid_does_not_match_metric", f"distribution.{self.name}")
        if spec.minimum_value is not None and any(value < spec.minimum_value for value in values):
            _raise("value_below_metric_minimum", f"distribution.{self.name}")
        if spec.maximum_value is not None and any(value > spec.maximum_value for value in values):
            _raise("value_above_metric_maximum", f"distribution.{self.name}")
        if self.unavailable_reason is not None:
            _raise("available_forbids_unavailable_reason", f"distribution.{self.name}")
        if self.sample_count is not None:
            _require_int(self.sample_count, f"distribution.{self.name}.sample_count")
        if self.semantic_kind in _CALIBRATED_KINDS:
            if not isinstance(self.calibration_evidence, CalibrationEvidenceV1):
                _raise(
                    "structured_calibration_evidence_required",
                    f"distribution.{self.name}",
                )
            if (
                self.calibration_evidence.metric_name != self.name
                or self.calibration_evidence.model_id != self.model_id
            ):
                _raise("calibration_identity_mismatch", f"distribution.{self.name}")
            if self.sample_count != self.calibration_evidence.sample_count:
                _raise("calibration_sample_count_mismatch", f"distribution.{self.name}")
        elif self.calibration_evidence is not None:
            _raise(
                "noncalibrated_kind_forbids_calibration_evidence",
                f"distribution.{self.name}",
            )
        if self.semantic_kind in _EMPIRICAL_KINDS and (
            self.sample_count is None or self.sample_count < 1
        ):
            _raise("empirical_kind_requires_positive_sample", f"distribution.{self.name}")


@dataclass(frozen=True, slots=True)
class CategoricalEstimateV1:
    name: str
    availability: str
    semantic_kind: str
    probabilities: tuple[CategoryProbabilityV1, ...]
    horizon_seconds: int | None
    sample_count: int | None
    producer_id: str | None
    source_field: str | None
    source_schema: str | None
    model_id: str | None
    calibration_evidence: CalibrationEvidenceV1 | None
    source_receipt_sha256s: tuple[str, ...]
    unavailable_reason: str | None

    def __post_init__(self) -> None:
        _require_name(self.name, "categorical.name")
        if self.availability not in {AVAILABLE, UNAVAILABLE}:
            _raise("invalid_availability", f"categorical.{self.name}.availability")
        _require_sorted_shas(
            self.source_receipt_sha256s,
            f"categorical.{self.name}.source_receipt_sha256s",
            allow_empty=self.availability == UNAVAILABLE,
        )
        if self.availability == UNAVAILABLE:
            if self.semantic_kind != UNAVAILABLE:
                _raise("unavailable_requires_UNAVAILABLE_kind", f"categorical.{self.name}")
            if (
                self.probabilities
                or self.horizon_seconds is not None
                or self.sample_count is not None
                or self.producer_id is not None
                or self.source_field is not None
                or self.source_schema is not None
                or self.model_id is not None
                or self.calibration_evidence is not None
            ):
                _raise("unavailable_requires_null_estimate_fields", f"categorical.{self.name}")
            if not isinstance(self.unavailable_reason, str) or not self.unavailable_reason.strip():
                _raise("unavailable_reason_required", f"categorical.{self.name}")
            return
        if self.semantic_kind not in _DISTRIBUTION_KINDS:
            _raise("invalid_semantic_kind", f"categorical.{self.name}.semantic_kind")
        if self.name != "regime_probabilities":
            _raise("unknown_categorical_metric", f"categorical.{self.name}")
        for field in ("producer_id", "source_field", "source_schema", "model_id"):
            _require_identifier(getattr(self, field), f"categorical.{self.name}.{field}")
        if type(self.probabilities) is not tuple or not self.probabilities:
            _raise("probabilities_required", f"categorical.{self.name}.probabilities")
        if any(not isinstance(item, CategoryProbabilityV1) for item in self.probabilities):
            _raise("must_contain_CategoryProbabilityV1", f"categorical.{self.name}")
        categories = tuple(item.category for item in self.probabilities)
        if categories != tuple(sorted(set(categories))):
            _raise("categories_must_be_unique_and_sorted", f"categorical.{self.name}")
        if categories != REGIME_CATEGORIES:
            _raise("must_cover_exact_regime_categories", f"categorical.{self.name}")
        if not math.isclose(
            math.fsum(item.probability for item in self.probabilities),
            1.0,
            rel_tol=0.0,
            abs_tol=_TOLERANCE,
        ):
            _raise("probabilities_must_sum_to_one", f"categorical.{self.name}")
        _require_int(self.horizon_seconds, f"categorical.{self.name}.horizon_seconds", 1)
        if self.unavailable_reason is not None:
            _raise("available_forbids_unavailable_reason", f"categorical.{self.name}")
        if self.sample_count is not None:
            _require_int(self.sample_count, f"categorical.{self.name}.sample_count")
        if self.semantic_kind in _CALIBRATED_KINDS:
            if not isinstance(self.calibration_evidence, CalibrationEvidenceV1):
                _raise(
                    "structured_calibration_evidence_required",
                    f"categorical.{self.name}",
                )
            if (
                self.calibration_evidence.metric_name != self.name
                or self.calibration_evidence.model_id != self.model_id
            ):
                _raise("calibration_identity_mismatch", f"categorical.{self.name}")
            if self.sample_count != self.calibration_evidence.sample_count:
                _raise("calibration_sample_count_mismatch", f"categorical.{self.name}")
        elif self.calibration_evidence is not None:
            _raise(
                "noncalibrated_kind_forbids_calibration_evidence",
                f"categorical.{self.name}",
            )
        if self.semantic_kind in _EMPIRICAL_KINDS and (
            self.sample_count is None or self.sample_count < 1
        ):
            _raise("empirical_kind_requires_positive_sample", f"categorical.{self.name}")


@dataclass(frozen=True, slots=True)
class ComponentEstimateGroupV1:
    component_name: str
    scalar_estimates: tuple[ScalarEstimateV1, ...]
    distribution_estimates: tuple[DistributionEstimateV1, ...]
    categorical_estimates: tuple[CategoricalEstimateV1, ...]
    diagnostic_scalar_estimates: tuple[ScalarEstimateV1, ...]
    source_diagnostic_action: str | None
    diagnostic_only: bool
    consumed_for_policy: bool
    consumed_for_admission: bool

    def __post_init__(self) -> None:
        if self.component_name not in COMPONENT_NAMES:
            _raise("invalid_component", "component_name")
        for field, values, expected, expected_type in (
            (
                "scalar_estimates",
                self.scalar_estimates,
                _REQUIRED_SCALARS[self.component_name],
                ScalarEstimateV1,
            ),
            (
                "distribution_estimates",
                self.distribution_estimates,
                _REQUIRED_DISTRIBUTIONS[self.component_name],
                DistributionEstimateV1,
            ),
            (
                "categorical_estimates",
                self.categorical_estimates,
                _REQUIRED_CATEGORICALS[self.component_name],
                CategoricalEstimateV1,
            ),
        ):
            if type(values) is not tuple:
                _raise("must_be_tuple", f"{self.component_name}.{field}")
            if any(not isinstance(item, expected_type) for item in values):
                _raise("invalid_estimate_type", f"{self.component_name}.{field}")
            names = tuple(item.name for item in values)
            if names != tuple(sorted(expected)):
                _raise(
                    f"must_cover_required_metrics:{sorted(expected)}",
                    f"{self.component_name}.{field}",
                )
        if type(self.diagnostic_scalar_estimates) is not tuple:
            _raise("must_be_tuple", f"{self.component_name}.diagnostic_scalar_estimates")
        if any(not isinstance(item, ScalarEstimateV1) for item in self.diagnostic_scalar_estimates):
            _raise(
                "invalid_estimate_type",
                f"{self.component_name}.diagnostic_scalar_estimates",
            )
        diagnostic_names = tuple(item.name for item in self.diagnostic_scalar_estimates)
        if diagnostic_names != tuple(sorted(set(diagnostic_names))):
            _raise(
                "diagnostic_names_must_be_unique_and_sorted",
                f"{self.component_name}.diagnostic_scalar_estimates",
            )
        for estimate in self.diagnostic_scalar_estimates:
            if estimate.availability != AVAILABLE or estimate.semantic_kind != HEURISTIC_SCORE:
                _raise(
                    "diagnostics_must_be_available_heuristic_scores",
                    f"{self.component_name}.diagnostic_scalar_estimates",
                )
            if f"{self.component_name}_heuristic_" not in estimate.name:
                _raise(
                    "diagnostic_name_must_be_component_namespaced",
                    f"{self.component_name}.diagnostic_scalar_estimates",
                )
        if self.source_diagnostic_action is not None:
            _require_identifier(
                self.source_diagnostic_action,
                f"{self.component_name}.source_diagnostic_action",
                96,
            )
        if self.diagnostic_only is not True:
            _raise("must_be_true", f"{self.component_name}.diagnostic_only")
        if self.consumed_for_policy is not False or self.consumed_for_admission is not False:
            _raise("shadow_group_forbids_authority", self.component_name)


def unavailable_component_group(
    component_name: str,
    *,
    reason: str,
    source_diagnostic_action: str | None = None,
) -> ComponentEstimateGroupV1:
    """Build an explicit missing-data group without manufacturing zero estimates."""

    if component_name not in COMPONENT_NAMES:
        _raise("invalid_component", "component_name")
    if not isinstance(reason, str) or not reason.strip():
        _raise("unavailable_reason_required", component_name)
    scalars = tuple(
        ScalarEstimateV1(
            name=name,
            availability=UNAVAILABLE,
            semantic_kind=UNAVAILABLE,
            value=None,
            unit=None,
            horizon_seconds=None,
            sample_count=None,
            producer_id=None,
            source_field=None,
            source_schema=None,
            model_id=None,
            calibration_evidence=None,
            source_receipt_sha256s=(),
            unavailable_reason=reason,
        )
        for name in sorted(_REQUIRED_SCALARS[component_name])
    )
    distributions = tuple(
        DistributionEstimateV1(
            name=name,
            availability=UNAVAILABLE,
            semantic_kind=UNAVAILABLE,
            unit=None,
            horizon_seconds=None,
            quantiles=(),
            sample_count=None,
            producer_id=None,
            source_field=None,
            source_schema=None,
            model_id=None,
            calibration_evidence=None,
            source_receipt_sha256s=(),
            unavailable_reason=reason,
        )
        for name in sorted(_REQUIRED_DISTRIBUTIONS[component_name])
    )
    categoricals = tuple(
        CategoricalEstimateV1(
            name=name,
            availability=UNAVAILABLE,
            semantic_kind=UNAVAILABLE,
            probabilities=(),
            horizon_seconds=None,
            sample_count=None,
            producer_id=None,
            source_field=None,
            source_schema=None,
            model_id=None,
            calibration_evidence=None,
            source_receipt_sha256s=(),
            unavailable_reason=reason,
        )
        for name in sorted(_REQUIRED_CATEGORICALS[component_name])
    )
    return ComponentEstimateGroupV1(
        component_name=component_name,
        scalar_estimates=scalars,
        distribution_estimates=distributions,
        categorical_estimates=categoricals,
        diagnostic_scalar_estimates=(),
        source_diagnostic_action=source_diagnostic_action,
        diagnostic_only=True,
        consumed_for_policy=False,
        consumed_for_admission=False,
    )


@dataclass(frozen=True, slots=True)
class AdaptiveComponentEstimatesV1:
    bundle_id: str
    candidate_id: str
    prediction_id: str
    symbol: str
    timeframe: str
    side: str
    venue: str
    order_type: str
    action_under_evaluation_sha256: str
    state_id: str
    state_sha256: str
    feature_snapshot_id: str
    feature_abi_sha256: str
    feature_builder_sha256: str
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    policy_id: str
    source_receipt_sha256s: tuple[str, ...]
    state_event_time_ms: int
    state_ingested_at_ms: int
    feature_cutoff_ms: int
    source_available_at_ms: int
    producer_generated_at_ms: int
    record_available_at_ms: int
    decision_time_ms: int
    latest_unclosed_kline_excluded: bool
    latest_unclosed_exclusion_method: str
    latest_unclosed_exclusion_decision_time_ms: int
    latest_closed_kline_close_time_ms: int
    component_groups: tuple[ComponentEstimateGroupV1, ...]
    authority_mode: str
    consumed_for_policy: bool
    consumed_for_admission: bool
    emits_trading_action: bool
    paper_only: bool
    live_gate: str
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            _raise("invalid_schema_version", "schema_version")
        for field in (
            "bundle_id",
            "candidate_id",
            "prediction_id",
            "state_id",
            "feature_snapshot_id",
            "checkpoint_id",
            "policy_id",
            "timeframe",
            "venue",
            "order_type",
            "latest_unclosed_exclusion_method",
        ):
            _require_identifier(getattr(self, field), field)
        if not isinstance(self.symbol, str) or re.fullmatch(r"[A-Z0-9]{2,32}", self.symbol) is None:
            _raise("must_be_uppercase_alphanumeric_venue_symbol", "symbol")
        if self.side not in {"LONG", "SHORT"}:
            _raise("must_be_LONG_or_SHORT", "side")
        for field in (
            "action_under_evaluation_sha256",
            "state_sha256",
            "feature_abi_sha256",
            "feature_builder_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        _require_int(self.checkpoint_generation, "checkpoint_generation", 1)
        _require_sha256(self.checkpoint_sha256, "checkpoint_sha256")
        _require_sorted_shas(
            self.source_receipt_sha256s,
            "source_receipt_sha256s",
            allow_empty=False,
        )
        for field in (
            "state_event_time_ms",
            "state_ingested_at_ms",
            "feature_cutoff_ms",
            "source_available_at_ms",
            "producer_generated_at_ms",
            "record_available_at_ms",
            "decision_time_ms",
            "latest_unclosed_exclusion_decision_time_ms",
            "latest_closed_kline_close_time_ms",
        ):
            _require_int(getattr(self, field), field)
        if self.state_event_time_ms > self.state_ingested_at_ms:
            _raise("point_in_time_order_invalid", "state_ingested_at_ms")
        if self.state_event_time_ms > self.feature_cutoff_ms:
            _raise("point_in_time_order_invalid", "feature_cutoff_ms")
        if max(self.state_ingested_at_ms, self.feature_cutoff_ms) > self.source_available_at_ms:
            _raise("point_in_time_order_invalid", "source_available_at_ms")
        if self.source_available_at_ms > self.producer_generated_at_ms:
            _raise("point_in_time_order_invalid", "producer_generated_at_ms")
        if self.record_available_at_ms != max(
            self.source_available_at_ms, self.producer_generated_at_ms
        ):
            _raise("must_equal_effective_availability", "record_available_at_ms")
        if self.record_available_at_ms > self.decision_time_ms:
            _raise("point_in_time_order_invalid", "decision_time_ms")
        if self.latest_unclosed_kline_excluded is not True:
            _raise("must_be_true", "latest_unclosed_kline_excluded")
        if self.latest_unclosed_exclusion_decision_time_ms != self.decision_time_ms:
            _raise(
                "must_equal_decision_time",
                "latest_unclosed_exclusion_decision_time_ms",
            )
        if self.latest_closed_kline_close_time_ms > self.feature_cutoff_ms:
            _raise("must_not_exceed_feature_cutoff", "latest_closed_kline_close_time_ms")
        if type(self.component_groups) is not tuple:
            _raise("must_be_tuple", "component_groups")
        if any(not isinstance(item, ComponentEstimateGroupV1) for item in self.component_groups):
            _raise("must_contain_ComponentEstimateGroupV1", "component_groups")
        names = tuple(item.component_name for item in self.component_groups)
        if names != COMPONENT_NAMES:
            _raise("must_cover_components_in_canonical_order", "component_groups")
        bundle_receipts = frozenset(self.source_receipt_sha256s)
        for group in self.component_groups:
            estimates = (
                *group.scalar_estimates,
                *group.distribution_estimates,
                *group.categorical_estimates,
                *group.diagnostic_scalar_estimates,
            )
            for estimate in estimates:
                if not frozenset(estimate.source_receipt_sha256s).issubset(bundle_receipts):
                    _raise(
                        "estimate_receipts_must_be_bundle_receipt_subset",
                        f"{group.component_name}.{estimate.name}",
                    )
                evidence = estimate.calibration_evidence
                if evidence is None:
                    continue
                if evidence.calibration_receipt_sha256 not in bundle_receipts:
                    _raise(
                        "calibration_receipt_must_be_bundle_receipt",
                        f"{group.component_name}.{estimate.name}",
                    )
                if evidence.component_name != group.component_name:
                    _raise(
                        "calibration_component_mismatch",
                        f"{group.component_name}.{estimate.name}",
                    )
                if (
                    evidence.checkpoint_generation != self.checkpoint_generation
                    or evidence.checkpoint_id != self.checkpoint_id
                    or evidence.checkpoint_sha256 != self.checkpoint_sha256
                ):
                    _raise(
                        "calibration_checkpoint_mismatch",
                        f"{group.component_name}.{estimate.name}",
                    )
                if evidence.calibration_window_end_ms > self.decision_time_ms:
                    _raise(
                        "calibration_window_exceeds_decision_time",
                        f"{group.component_name}.{estimate.name}",
                    )
                if estimate.sample_count != evidence.sample_count:
                    _raise(
                        "calibration_sample_count_mismatch",
                        f"{group.component_name}.{estimate.name}",
                    )
        if self.authority_mode != AUTHORITY_MODE:
            _raise("must_be_shadow_diagnostic_only", "authority_mode")
        for field in (
            "consumed_for_policy",
            "consumed_for_admission",
            "emits_trading_action",
            "routes_to_live",
            "places_real_order",
            "exchange_action_taken",
        ):
            if getattr(self, field) is not False:
                _raise("must_be_false", field)
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")
        if self.live_gate != LIVE_GATE:
            _raise("must_be_blocked_human_only", "live_gate")
        if self.bundle_id != self.expected_bundle_id:
            _raise("must_match_deterministic_identity", "bundle_id")

    def _semantic_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        for field in _SEMANTIC_FINGERPRINT_EXCLUDED:
            payload.pop(field)
        return payload

    @property
    def semantic_fingerprint_sha256(self) -> str:
        return _canonical_hash(self._semantic_payload())

    @property
    def expected_bundle_id(self) -> str:
        identity = {
            "schema_version": self.schema_version,
            "state_id": self.state_id,
            "decision_time_ms": self.decision_time_ms,
            "semantic_fingerprint_sha256": self.semantic_fingerprint_sha256,
        }
        return f"ace1_{_canonical_hash(identity)}"

    @classmethod
    def create(cls, **values: Any) -> AdaptiveComponentEstimatesV1:
        if "bundle_id" in values or "semantic_fingerprint_sha256" in values:
            _raise("must_be_derived", "bundle_id")
        material = dict(values)
        material.setdefault("schema_version", SCHEMA_VERSION)
        expected = frozenset(item.name for item in fields(cls)) - {"bundle_id"}
        _require_exact_keys(material, expected, "create")
        semantic_fingerprint = _canonical_hash(asdict_value(material))
        identity = {
            "schema_version": material["schema_version"],
            "state_id": material["state_id"],
            "decision_time_ms": material["decision_time_ms"],
            "semantic_fingerprint_sha256": semantic_fingerprint,
        }
        return cls(bundle_id=f"ace1_{_canonical_hash(identity)}", **material)

    def to_payload(self) -> dict[str, Any]:
        payload = asdict_value(asdict(self))
        payload["semantic_fingerprint_sha256"] = self.semantic_fingerprint_sha256
        return payload

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_payload(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_payload(cls, payload: object) -> AdaptiveComponentEstimatesV1:
        expected = frozenset(item.name for item in fields(cls)) | {"semantic_fingerprint_sha256"}
        raw = dict(_require_exact_keys(payload, expected, "payload"))
        stored_fingerprint = raw.pop("semantic_fingerprint_sha256")
        _require_sha256(stored_fingerprint, "semantic_fingerprint_sha256")
        raw["source_receipt_sha256s"] = _list_to_tuple(
            raw["source_receipt_sha256s"], "source_receipt_sha256s"
        )
        groups = raw["component_groups"]
        if not isinstance(groups, list):
            _raise("must_be_list", "component_groups")
        raw["component_groups"] = tuple(
            _parse_group(item, index) for index, item in enumerate(groups)
        )
        record = cls(**raw)
        if record.semantic_fingerprint_sha256 != stored_fingerprint:
            _raise("must_match_semantic_payload", "semantic_fingerprint_sha256")
        return record

    @classmethod
    def from_json(cls, encoded: str) -> AdaptiveComponentEstimatesV1:
        if not isinstance(encoded, str):
            _raise("must_be_string", "encoded")
        try:
            payload = json.loads(encoded, object_pairs_hook=_reject_duplicate_json_keys)
        except AdaptiveComponentEstimateDomainError:
            raise
        except (json.JSONDecodeError, ValueError) as exc:
            raise AdaptiveComponentEstimateDomainError("invalid_json", field="encoded") from exc
        return cls.from_payload(payload)


def asdict_value(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return {key: asdict_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [asdict_value(item) for item in value]
    return value


def _list_to_tuple(value: object, field: str) -> tuple[Any, ...]:
    if not isinstance(value, list):
        _raise("must_be_list", field)
    return tuple(value)


def _parse_calibration(
    payload: object,
    field: str,
) -> CalibrationEvidenceV1 | None:
    if payload is None:
        return None
    return CalibrationEvidenceV1(
        **_require_exact_keys(
            payload,
            frozenset(item.name for item in fields(CalibrationEvidenceV1)),
            field,
        )
    )


def _parse_scalar(payload: object, field: str) -> ScalarEstimateV1:
    raw = dict(
        _require_exact_keys(
            payload,
            frozenset(item.name for item in fields(ScalarEstimateV1)),
            field,
        )
    )
    raw["source_receipt_sha256s"] = _list_to_tuple(
        raw["source_receipt_sha256s"], f"{field}.source_receipt_sha256s"
    )
    raw["calibration_evidence"] = _parse_calibration(
        raw["calibration_evidence"], f"{field}.calibration_evidence"
    )
    return ScalarEstimateV1(**raw)


def _parse_distribution(payload: object, field: str) -> DistributionEstimateV1:
    raw = dict(
        _require_exact_keys(
            payload,
            frozenset(item.name for item in fields(DistributionEstimateV1)),
            field,
        )
    )
    raw_quantiles = _list_to_tuple(raw["quantiles"], f"{field}.quantiles")
    quantile_keys = frozenset(item.name for item in fields(QuantileV1))
    raw["quantiles"] = tuple(
        QuantileV1(**_require_exact_keys(item, quantile_keys, f"{field}.quantiles[{index}]"))
        for index, item in enumerate(raw_quantiles)
    )
    raw["source_receipt_sha256s"] = _list_to_tuple(
        raw["source_receipt_sha256s"], f"{field}.source_receipt_sha256s"
    )
    raw["calibration_evidence"] = _parse_calibration(
        raw["calibration_evidence"], f"{field}.calibration_evidence"
    )
    return DistributionEstimateV1(**raw)


def _parse_categorical(payload: object, field: str) -> CategoricalEstimateV1:
    raw = dict(
        _require_exact_keys(
            payload,
            frozenset(item.name for item in fields(CategoricalEstimateV1)),
            field,
        )
    )
    raw_probabilities = _list_to_tuple(raw["probabilities"], f"{field}.probabilities")
    probability_keys = frozenset(item.name for item in fields(CategoryProbabilityV1))
    raw["probabilities"] = tuple(
        CategoryProbabilityV1(
            **_require_exact_keys(item, probability_keys, f"{field}.probabilities[{index}]")
        )
        for index, item in enumerate(raw_probabilities)
    )
    raw["source_receipt_sha256s"] = _list_to_tuple(
        raw["source_receipt_sha256s"], f"{field}.source_receipt_sha256s"
    )
    raw["calibration_evidence"] = _parse_calibration(
        raw["calibration_evidence"], f"{field}.calibration_evidence"
    )
    return CategoricalEstimateV1(**raw)


def _parse_group(payload: object, index: int) -> ComponentEstimateGroupV1:
    field = f"component_groups[{index}]"
    raw = dict(
        _require_exact_keys(
            payload,
            frozenset(item.name for item in fields(ComponentEstimateGroupV1)),
            field,
        )
    )
    raw["scalar_estimates"] = tuple(
        _parse_scalar(item, f"{field}.scalar_estimates[{item_index}]")
        for item_index, item in enumerate(
            _list_to_tuple(raw["scalar_estimates"], f"{field}.scalar_estimates")
        )
    )
    raw["distribution_estimates"] = tuple(
        _parse_distribution(item, f"{field}.distribution_estimates[{item_index}]")
        for item_index, item in enumerate(
            _list_to_tuple(raw["distribution_estimates"], f"{field}.distribution_estimates")
        )
    )
    raw["categorical_estimates"] = tuple(
        _parse_categorical(item, f"{field}.categorical_estimates[{item_index}]")
        for item_index, item in enumerate(
            _list_to_tuple(raw["categorical_estimates"], f"{field}.categorical_estimates")
        )
    )
    raw["diagnostic_scalar_estimates"] = tuple(
        _parse_scalar(item, f"{field}.diagnostic_scalar_estimates[{item_index}]")
        for item_index, item in enumerate(
            _list_to_tuple(
                raw["diagnostic_scalar_estimates"],
                f"{field}.diagnostic_scalar_estimates",
            )
        )
    )
    return ComponentEstimateGroupV1(**raw)


__all__ = (
    "AUTHORITY_MODE",
    "AVAILABLE",
    "CALIBRATED_DISTRIBUTION",
    "CALIBRATED_PROBABILITY",
    "CalibrationEvidenceV1",
    "COMPONENT_NAMES",
    "EMPIRICAL_DISTRIBUTION",
    "EMPIRICAL_ESTIMATE",
    "EMPIRICAL_RATE",
    "FACT",
    "HEURISTIC_SCORE",
    "LIVE_GATE",
    "POINT_ESTIMATE",
    "REGIME_CATEGORIES",
    "SCHEMA_VERSION",
    "UNAVAILABLE",
    "AdaptiveComponentEstimatesV1",
    "CategoricalEstimateV1",
    "CategoryProbabilityV1",
    "ComponentEstimateGroupV1",
    "DistributionEstimateV1",
    "QuantileV1",
    "ScalarEstimateV1",
    "unavailable_component_group",
)
