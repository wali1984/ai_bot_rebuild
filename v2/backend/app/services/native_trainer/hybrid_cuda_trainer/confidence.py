"""PIT-safe profitability confidence targets and checkpoint-bound calibration.

``confidence_calibrated`` has one meaning in this module: the estimated
probability that the *selected directional action* realizes a strictly
positive net PnL after explicit fees, slippage, and funding.  Policy selection
probability and expected-move magnitude are deliberately not confidence
targets.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

CONFIDENCE_CALIBRATION_SCHEMA_VERSION = "v2_profitability_confidence_calibration_v3"
LEGACY_CONFIDENCE_CALIBRATION_SCHEMA_VERSION = (
    "v2_profitability_confidence_calibration_v2"
)
CONFIDENCE_HEAD_SCHEMA_VERSION = "v2_per_directional_action_profitability_head_v1"
CONFIDENCE_HEAD_ACTIONS = ("long", "short")
CONFIDENCE_HEAD_ACTION_INDEX = {
    action: index for index, action in enumerate(CONFIDENCE_HEAD_ACTIONS)
}
CONFIDENCE_LABEL_SEMANTICS = (
    "P_SELECTED_DIRECTIONAL_ACTION_RECOMPUTED_NET_PNL_AFTER_EXPLICIT_COSTS_GT_ZERO_V2"
)
CONFIDENCE_FIT_PARTITION = "PURGED_TRAIN_ONLY"
UNFITTED_CONFIDENCE_VALUE = 0.0
CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION = (
    "v2_confidence_nonregression_uncertainty_evidence_v2"
)
LEGACY_CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION = (
    "v2_confidence_nonregression_uncertainty_evidence_v1"
)
CONFIDENCE_UNCERTAINTY_METHOD = (
    "PAIRED_BRIER_AND_EXACT_CONFIDENCE_GROUPED_CUMULATIVE_RESIDUAL_"
    "SUPREMUM_FULL_SAMPLE_AND_EVERY_DELETE_ONE_NONREGRESSION_V1"
)
LEGACY_CONFIDENCE_UNCERTAINTY_METHOD = (
    "PAIRED_BRIER_SAMPLE_SE_AND_DELETE_ONE_ECE_JACKKNIFE_ONE_SE"
)
CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR = (
    "EXACT_CONFIDENCE_GROUPED_CUMULATIVE_RESIDUAL_SUPREMUM_V1"
)
CONFIDENCE_TEMPERATURE_FIT_METHOD = (
    "CONVEX_LOGIT_SCALE_SCORE_ROOT_ADJACENT_FLOATS_V1"
)
CONFIDENCE_TEMPERATURE_FIT_INTERIOR = "UNIQUE_FINITE_INTERIOR_SCORE_ROOT"
CONFIDENCE_TEMPERATURE_FIT_ZERO_SCALE = (
    "UNINFORMATIVE_ZERO_LOGIT_SCALE_BOUNDARY"
)
CONFIDENCE_UNCERTAINTY_EVIDENCE_FIELDS = (
    "calibration_error_estimator",
    "paired_brier_delta_per_row",
    "paired_brier_delta_mean",
    "paired_brier_delta_standard_error",
    "paired_brier_delta_one_standard_error_upper_bound",
    "paired_brier_uncertainty_available",
    "paired_brier_non_regression_proven",
    "ece_delta",
    "ece_leave_one_out_delta",
    "ece_jackknife_standard_error",
    "ece_one_standard_error_upper_bound",
    "ece_uncertainty_available",
    "ece_non_regression_proven",
    "uncertainty_row_count",
    "uncertainty_minimum_not_configured",
    "uncertainty_mathematical_minimum_rows",
)

# Retained only so the old CLI can produce a precise deprecation report.  The
# model no longer reads this path or an environment override: calibration must
# travel inside the same checkpoint blob as the weights it calibrates.
CONFIDENCE_TEMPERATURE_STATE_PATH = Path(
    os.getenv(
        "V2_CONFIDENCE_TEMPERATURE_STATE_PATH",
        "claude_worklog/trainer_atlas/confidence_temperature.json",
    )
)
DEFAULT_CONFIDENCE_TEMPERATURE = 1.0


def _finite_float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _strict_nonnegative_int(value: Any) -> int | None:
    """Parse a count without silently truncating fractional evidence."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return (
            int(value)
            if math.isfinite(value) and value.is_integer() and value >= 0
            else None
        )
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def _parse_utc(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _open_unit_probability(value: float) -> float:
    probability = float(value)
    endpoint_distance = 1.0 - math.nextafter(1.0, 0.0)
    if probability <= 0.0:
        return endpoint_distance
    if probability >= 1.0:
        return 1.0 - endpoint_distance
    return probability


def _stable_sigmoid(value: float) -> float:
    if value >= 0.0:
        decay = math.exp(-value)
        return 1.0 / (1.0 + decay)
    growth = math.exp(value)
    return growth / (1.0 + growth)


def _temperature_scaled(raw: float, temperature: float) -> float:
    probability = _open_unit_probability(raw)
    logit = math.log(probability / (1.0 - probability))
    return _stable_sigmoid(logit / float(temperature))


def logit_scaled_probability(raw: float, logit_scale: float) -> float:
    """Apply a nonnegative checkpoint-bound logit multiplier."""

    parsed_raw = _finite_float(raw)
    parsed_scale = _finite_float(logit_scale)
    if (
        parsed_raw is None
        or not 0.0 <= parsed_raw <= 1.0
        or parsed_scale is None
        or parsed_scale < 0.0
    ):
        raise ValueError("confidence_logit_scaling_input_invalid")
    return _stable_sigmoid(_logit(parsed_raw) * parsed_scale)


def temperature_scaled_probability(raw: float, temperature: float) -> float:
    """Apply finite positive temperature scaling without heuristic clipping."""

    parsed_raw = _finite_float(raw)
    parsed_temperature = _finite_float(temperature)
    if (
        parsed_raw is None
        or not 0.0 <= parsed_raw <= 1.0
        or parsed_temperature is None
        or parsed_temperature <= 0.0
    ):
        raise ValueError("confidence_temperature_scaling_input_invalid")
    return _temperature_scaled(parsed_raw, parsed_temperature)


def legacy_temperature_scaled_probability(raw: float, temperature: float) -> float:
    """Frozen V2 scaling used only to verify immutable legacy evidence."""

    probability = max(1e-6, min(1.0 - 1e-6, float(raw)))
    logit = math.log(probability / (1.0 - probability))
    scaled = max(-700.0, min(700.0, logit / float(temperature)))
    return 1.0 / (1.0 + math.exp(-scaled))


def confidence_uncertainty_evidence_digest(
    *,
    scope: str,
    evidence: Mapping[str, Any],
) -> str:
    """Hash the complete public confidence non-regression uncertainty proof."""

    normalized_scope = str(scope or "").strip().upper()
    valid_scopes = {"GLOBAL", *(action.upper() for action in CONFIDENCE_HEAD_ACTIONS)}
    if normalized_scope not in valid_scopes:
        raise ValueError("confidence_uncertainty_scope_invalid")

    def finite_sequence(field_name: str) -> list[float]:
        raw = evidence.get(field_name)
        if not isinstance(raw, Sequence) or isinstance(raw, str | bytes | bytearray):
            raise ValueError(f"confidence_uncertainty_{field_name}_invalid")
        parsed = [_finite_float(value) for value in raw]
        if any(value is None for value in parsed):
            raise ValueError(f"confidence_uncertainty_{field_name}_invalid")
        return [float(value) for value in parsed if value is not None]

    def optional_finite(field_name: str) -> float | None:
        raw = evidence.get(field_name)
        if raw is None:
            return None
        parsed = _finite_float(raw)
        if parsed is None:
            raise ValueError(f"confidence_uncertainty_{field_name}_invalid")
        return parsed

    row_count = _strict_nonnegative_int(evidence.get("uncertainty_row_count"))
    mathematical_minimum = _strict_nonnegative_int(
        evidence.get("uncertainty_mathematical_minimum_rows")
    )
    if row_count is None or mathematical_minimum is None:
        raise ValueError("confidence_uncertainty_count_invalid")
    boolean_fields = (
        "paired_brier_uncertainty_available",
        "paired_brier_non_regression_proven",
        "ece_uncertainty_available",
        "ece_non_regression_proven",
        "uncertainty_minimum_not_configured",
    )
    if any(
        not isinstance(evidence.get(field_name), bool)
        for field_name in boolean_fields
    ):
        raise ValueError("confidence_uncertainty_boolean_invalid")
    payload = {
        "schema_version": CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION,
        "scope": normalized_scope,
        "method": CONFIDENCE_UNCERTAINTY_METHOD,
        "calibration_error_estimator": evidence.get(
            "calibration_error_estimator"
        ),
        "paired_brier_delta_per_row": finite_sequence(
            "paired_brier_delta_per_row"
        ),
        "paired_brier_delta_mean": optional_finite("paired_brier_delta_mean"),
        "paired_brier_delta_standard_error": optional_finite(
            "paired_brier_delta_standard_error"
        ),
        "paired_brier_delta_one_standard_error_upper_bound": optional_finite(
            "paired_brier_delta_one_standard_error_upper_bound"
        ),
        "paired_brier_uncertainty_available": evidence[
            "paired_brier_uncertainty_available"
        ],
        "paired_brier_non_regression_proven": evidence[
            "paired_brier_non_regression_proven"
        ],
        "ece_delta": optional_finite("ece_delta"),
        "ece_leave_one_out_delta": finite_sequence("ece_leave_one_out_delta"),
        "ece_jackknife_standard_error": optional_finite(
            "ece_jackknife_standard_error"
        ),
        "ece_one_standard_error_upper_bound": optional_finite(
            "ece_one_standard_error_upper_bound"
        ),
        "ece_uncertainty_available": evidence["ece_uncertainty_available"],
        "ece_non_regression_proven": evidence["ece_non_regression_proven"],
        "uncertainty_row_count": row_count,
        "uncertainty_minimum_not_configured": evidence[
            "uncertainty_minimum_not_configured"
        ],
        "uncertainty_mathematical_minimum_rows": mathematical_minimum,
    }
    if (
        payload["calibration_error_estimator"]
        != CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR
    ):
        raise ValueError("confidence_uncertainty_calibration_error_estimator_invalid")
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def legacy_confidence_uncertainty_evidence_digest(
    *,
    scope: str,
    evidence: Mapping[str, Any],
) -> str:
    """Frozen V1 digest used only for immutable admission verification."""

    normalized_scope = str(scope or "").strip().upper()
    valid_scopes = {"GLOBAL", *(action.upper() for action in CONFIDENCE_HEAD_ACTIONS)}
    if normalized_scope not in valid_scopes:
        raise ValueError("confidence_uncertainty_scope_invalid")

    def finite_sequence(field_name: str) -> list[float]:
        raw = evidence.get(field_name)
        if not isinstance(raw, Sequence) or isinstance(
            raw,
            str | bytes | bytearray,
        ):
            raise ValueError(f"confidence_uncertainty_{field_name}_invalid")
        parsed = [_finite_float(value) for value in raw]
        if any(value is None for value in parsed):
            raise ValueError(f"confidence_uncertainty_{field_name}_invalid")
        return [float(value) for value in parsed if value is not None]

    def optional_finite(field_name: str) -> float | None:
        raw = evidence.get(field_name)
        if raw is None:
            return None
        parsed = _finite_float(raw)
        if parsed is None:
            raise ValueError(f"confidence_uncertainty_{field_name}_invalid")
        return parsed

    row_count = _strict_nonnegative_int(evidence.get("uncertainty_row_count"))
    mathematical_minimum = _strict_nonnegative_int(
        evidence.get("uncertainty_mathematical_minimum_rows")
    )
    if row_count is None or mathematical_minimum is None:
        raise ValueError("confidence_uncertainty_count_invalid")
    boolean_fields = (
        "paired_brier_uncertainty_available",
        "paired_brier_non_regression_proven",
        "ece_uncertainty_available",
        "ece_non_regression_proven",
        "uncertainty_minimum_not_configured",
    )
    if any(
        not isinstance(evidence.get(field_name), bool)
        for field_name in boolean_fields
    ):
        raise ValueError("confidence_uncertainty_boolean_invalid")
    payload = {
        "schema_version": LEGACY_CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION,
        "scope": normalized_scope,
        "method": LEGACY_CONFIDENCE_UNCERTAINTY_METHOD,
        "paired_brier_delta_per_row": finite_sequence(
            "paired_brier_delta_per_row"
        ),
        "paired_brier_delta_mean": optional_finite("paired_brier_delta_mean"),
        "paired_brier_delta_standard_error": optional_finite(
            "paired_brier_delta_standard_error"
        ),
        "paired_brier_delta_one_standard_error_upper_bound": optional_finite(
            "paired_brier_delta_one_standard_error_upper_bound"
        ),
        "paired_brier_uncertainty_available": evidence[
            "paired_brier_uncertainty_available"
        ],
        "paired_brier_non_regression_proven": evidence[
            "paired_brier_non_regression_proven"
        ],
        "ece_delta": optional_finite("ece_delta"),
        "ece_leave_one_out_delta": finite_sequence("ece_leave_one_out_delta"),
        "ece_jackknife_standard_error": optional_finite(
            "ece_jackknife_standard_error"
        ),
        "ece_one_standard_error_upper_bound": optional_finite(
            "ece_one_standard_error_upper_bound"
        ),
        "ece_uncertainty_available": evidence["ece_uncertainty_available"],
        "ece_non_regression_proven": evidence["ece_non_regression_proven"],
        "uncertainty_row_count": row_count,
        "uncertainty_minimum_not_configured": evidence[
            "uncertainty_minimum_not_configured"
        ],
        "uncertainty_mathematical_minimum_rows": mathematical_minimum,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def legacy_brier_score(
    raw_probs: Sequence[float],
    outcomes: Sequence[int],
    temperature: float = 1.0,
) -> float | None:
    """Frozen V2 Brier implementation for legacy artifact verification."""

    if len(raw_probs) != len(outcomes) or not raw_probs:
        return None
    errors = [
        (legacy_temperature_scaled_probability(raw, temperature) - int(outcome))
        ** 2
        for raw, outcome in zip(raw_probs, outcomes, strict=True)
    ]
    return sum(errors) / len(errors)


def legacy_expected_calibration_error(
    raw_probs: Sequence[float],
    outcomes: Sequence[int],
    temperature: float = 1.0,
    bins: int = 10,
) -> float:
    """Frozen equal-width V2 ECE for legacy artifact verification only."""

    if len(raw_probs) != len(outcomes) or not raw_probs or bins <= 0:
        return 0.0
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
    for raw, outcome in zip(raw_probs, outcomes, strict=True):
        probability = legacy_temperature_scaled_probability(raw, temperature)
        index = min(bins - 1, max(0, int(probability * bins)))
        buckets[index].append((probability, int(outcome)))
    error = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        confidence = sum(probability for probability, _ in bucket) / len(bucket)
        accuracy = sum(outcome for _, outcome in bucket) / len(bucket)
        error += (len(bucket) / len(raw_probs)) * abs(confidence - accuracy)
    return error


def _nll(raw_probs: Sequence[float], outcomes: Sequence[int], temperature: float) -> float:
    total = 0.0
    for raw, outcome in zip(raw_probs, outcomes, strict=True):
        probability = _open_unit_probability(_temperature_scaled(raw, temperature))
        total += -(
            outcome * math.log(probability)
            + (1 - outcome) * math.log(1.0 - probability)
        )
    return total / len(raw_probs) if raw_probs else float("inf")


def _scaled_probability(
    raw: float,
    *,
    temperature: float | None,
    logit_scale: float | None,
) -> float:
    if logit_scale is not None:
        if temperature is not None:
            raise ValueError("confidence_calibration_parameterization_conflict")
        return logit_scaled_probability(raw, logit_scale)
    return temperature_scaled_probability(
        raw,
        1.0 if temperature is None else temperature,
    )


def brier_score(
    raw_probs: Sequence[float],
    outcomes: Sequence[int],
    temperature: float | None = None,
    *,
    logit_scale: float | None = None,
) -> float | None:
    if len(raw_probs) != len(outcomes) or not raw_probs:
        return None
    errors: list[float] = []
    for raw, outcome in zip(raw_probs, outcomes, strict=True):
        probability = _finite_float(raw)
        if probability is None or not 0.0 <= probability <= 1.0:
            raise ValueError("confidence_calibration_probability_invalid")
        if isinstance(outcome, bool):
            label = int(outcome)
        elif outcome in (0, 1):
            label = int(outcome)
        else:
            raise ValueError("confidence_calibration_outcome_not_binary")
        calibrated = _scaled_probability(
            probability,
            temperature=temperature,
            logit_scale=logit_scale,
        )
        errors.append((calibrated - label) ** 2)
    return sum(errors) / len(errors)


def adaptive_reliability_partition(
    raw_probs: Sequence[float],
    outcomes: Sequence[int],
    temperature: float | None = None,
    *,
    logit_scale: float | None = None,
) -> tuple[float, list[dict[str, Any]]]:
    """Return a deterministic bin-free cumulative reliability discrepancy.

    Equal predicted probabilities are grouped after sorting.  For each exact
    confidence group the signed outcome-minus-confidence residual is added to
    a cumulative calibration process.  The metric is the supremum absolute
    cumulative residual divided by the number of rows.  Confidence values alone
    determine every boundary, so outcomes cannot select a partition that hides
    anti-calibration.  There is no bucket count, minimum block size,
    probability threshold, or market regime parameter.
    """

    if len(raw_probs) != len(outcomes):
        raise ValueError("confidence_calibration_input_length_mismatch")
    if not raw_probs:
        return 0.0, []
    parsed_temperature = (
        _finite_float(temperature) if temperature is not None else None
    )
    parsed_logit_scale = (
        _finite_float(logit_scale) if logit_scale is not None else None
    )
    if logit_scale is not None:
        if (
            temperature is not None
            or parsed_logit_scale is None
            or parsed_logit_scale < 0.0
        ):
            raise ValueError("confidence_calibration_logit_scale_invalid")
    elif temperature is not None and (
        parsed_temperature is None or parsed_temperature <= 0.0
    ):
        raise ValueError("confidence_calibration_temperature_invalid")
    ordered: list[tuple[float, int, int]] = []
    for index, (raw, outcome) in enumerate(
        zip(raw_probs, outcomes, strict=True)
    ):
        probability = _finite_float(raw)
        if probability is None or not 0.0 <= probability <= 1.0:
            raise ValueError("confidence_calibration_probability_invalid")
        if isinstance(outcome, bool):
            label = int(outcome)
        elif outcome in (0, 1):
            label = int(outcome)
        else:
            raise ValueError("confidence_calibration_outcome_not_binary")
        ordered.append(
            (
                _scaled_probability(
                    probability,
                    temperature=parsed_temperature,
                    logit_scale=parsed_logit_scale,
                ),
                label,
                index,
            )
        )
    ordered.sort(key=lambda row: (row[0], row[2]))
    exact_probability_groups: list[dict[str, Any]] = []
    for probability, label, original_index in ordered:
        if (
            exact_probability_groups
            and exact_probability_groups[-1]["maximum_probability"] == probability
        ):
            group = exact_probability_groups[-1]
            group["count"] += 1
            group["probability_sum"] += probability
            group["outcome_sum"] += label
            group["original_indices"].append(original_index)
        else:
            exact_probability_groups.append(
                {
                    "count": 1,
                    "probability_sum": probability,
                    "outcome_sum": label,
                    "minimum_probability": probability,
                    "maximum_probability": probability,
                    "original_indices": [original_index],
                }
            )
    total = len(ordered)
    cumulative_residual = 0.0
    supremum_absolute_residual = 0.0
    public_blocks: list[dict[str, Any]] = []
    for block_index, block in enumerate(exact_probability_groups):
        count = int(block["count"])
        average = float(block["probability_sum"]) / count
        empirical = float(block["outcome_sum"]) / count
        error = abs(average - empirical)
        group_residual = float(block["outcome_sum"]) - float(
            block["probability_sum"]
        )
        cumulative_residual += group_residual
        supremum_absolute_residual = max(
            supremum_absolute_residual,
            abs(cumulative_residual),
        )
        block_indices = cast(list[int], block["original_indices"])
        block_brier = sum(
            (
                _scaled_probability(
                    float(raw_probs[index]),
                    temperature=parsed_temperature,
                    logit_scale=parsed_logit_scale,
                )
                - int(outcomes[index])
            )
            ** 2
            for index in block_indices
        ) / count
        public_blocks.append(
            {
                "adaptive_block_index": block_index,
                "bucket_min": block["minimum_probability"],
                "bucket_max": block["maximum_probability"],
                "sample_count": count,
                "avg_confidence": average,
                "empirical_success_rate": empirical,
                "absolute_calibration_error": error,
                "group_residual": group_residual,
                "cumulative_residual": cumulative_residual,
                "brier_score": block_brier,
                "source_row_indices": block_indices,
                "partition_method": CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR,
            }
        )
    return supremum_absolute_residual / total, public_blocks


def expected_calibration_error(
    raw_probs: Sequence[float],
    outcomes: Sequence[int],
    temperature: float | None = None,
    *,
    logit_scale: float | None = None,
) -> float:
    """Compatibility name for bin-free cumulative reliability discrepancy."""

    error, _blocks = adaptive_reliability_partition(
        raw_probs,
        outcomes,
        temperature,
        logit_scale=logit_scale,
    )
    return error


def paired_confidence_nonregression_evidence(
    raw_probabilities: Sequence[float],
    outcomes: Sequence[int],
    *,
    logit_scale: float,
    scope: str,
) -> dict[str, Any]:
    """Build deterministic full-sample and every-delete-one evidence.

    Admission requires both the full observed metric and every delete-one
    recomputation to be non-regressing.  Standard errors remain descriptive
    telemetry; they are not used as an admission threshold.
    """

    if len(raw_probabilities) != len(outcomes):
        raise ValueError("confidence_uncertainty_input_length_mismatch")
    calibrated_probabilities = [
        logit_scaled_probability(raw, logit_scale)
        for raw in raw_probabilities
    ]
    paired_deltas = [
        (calibrated - int(outcome)) ** 2
        - (temperature_scaled_probability(raw, 1.0) - int(outcome)) ** 2
        for raw, calibrated, outcome in zip(
            raw_probabilities,
            calibrated_probabilities,
            outcomes,
            strict=True,
        )
    ]
    count = len(paired_deltas)
    paired_mean = sum(paired_deltas) / count if count else None
    paired_leave_one_out_means = [
        sum(
            value
            for index, value in enumerate(paired_deltas)
            if index != excluded
        )
        / (count - 1)
        for excluded in range(count)
    ] if count > 1 else []
    paired_standard_error: float | None = None
    if count > 1 and paired_mean is not None:
        sample_variance = sum(
            (value - paired_mean) ** 2 for value in paired_deltas
        ) / (count - 1)
        paired_standard_error = math.sqrt(sample_variance / count)
    paired_upper = (
        paired_mean + paired_standard_error
        if paired_mean is not None and paired_standard_error is not None
        else None
    )

    raw_error = (
        expected_calibration_error(raw_probabilities, outcomes)
        if count
        else None
    )
    calibrated_error = (
        expected_calibration_error(
            raw_probabilities,
            outcomes,
            logit_scale=logit_scale,
        )
        if count
        else None
    )
    error_delta = (
        calibrated_error - raw_error
        if raw_error is not None and calibrated_error is not None
        else None
    )
    error_leave_one_out_delta: list[float] = []
    if count > 1:
        for excluded in range(count):
            leave_one_out_probabilities = [
                value
                for index, value in enumerate(raw_probabilities)
                if index != excluded
            ]
            leave_one_out_outcomes = [
                value
                for index, value in enumerate(outcomes)
                if index != excluded
            ]
            error_leave_one_out_delta.append(
                expected_calibration_error(
                    leave_one_out_probabilities,
                    leave_one_out_outcomes,
                    logit_scale=logit_scale,
                )
                - expected_calibration_error(
                    leave_one_out_probabilities,
                    leave_one_out_outcomes,
                )
            )
    error_jackknife_standard_error: float | None = None
    if error_leave_one_out_delta:
        leave_one_out_mean = sum(error_leave_one_out_delta) / len(
            error_leave_one_out_delta
        )
        error_jackknife_standard_error = math.sqrt(
            ((count - 1) / count)
            * sum(
                (value - leave_one_out_mean) ** 2
                for value in error_leave_one_out_delta
            )
        )
    error_upper = (
        error_delta + error_jackknife_standard_error
        if error_delta is not None
        and error_jackknife_standard_error is not None
        else None
    )
    normalized_scope = str(scope).strip().upper()
    evidence: dict[str, Any] = {
        "calibration_error_estimator": CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR,
        "paired_brier_delta_per_row": paired_deltas,
        "paired_brier_delta_mean": paired_mean,
        "paired_brier_delta_standard_error": paired_standard_error,
        "paired_brier_delta_one_standard_error_upper_bound": paired_upper,
        "paired_brier_uncertainty_available": paired_standard_error is not None,
        "paired_brier_non_regression_proven": bool(
            paired_mean is not None
            and paired_mean <= 0.0
            and paired_leave_one_out_means
            and all(value <= 0.0 for value in paired_leave_one_out_means)
        ),
        "ece_delta": error_delta,
        "ece_leave_one_out_delta": error_leave_one_out_delta,
        "ece_jackknife_standard_error": error_jackknife_standard_error,
        "ece_one_standard_error_upper_bound": error_upper,
        "ece_uncertainty_available": (
            error_jackknife_standard_error is not None
        ),
        "ece_non_regression_proven": bool(
            error_delta is not None
            and error_delta <= 0.0
            and error_leave_one_out_delta
            and all(value <= 0.0 for value in error_leave_one_out_delta)
        ),
        "uncertainty_row_count": count,
        "uncertainty_minimum_not_configured": True,
        "uncertainty_mathematical_minimum_rows": 2,
        "uncertainty_evidence_schema_version": (
            CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION
        ),
        "uncertainty_scope": normalized_scope,
        "uncertainty_method": CONFIDENCE_UNCERTAINTY_METHOD,
    }
    evidence["uncertainty_evidence_digest"] = (
        confidence_uncertainty_evidence_digest(
            scope=normalized_scope,
            evidence=evidence,
        )
    )
    return evidence


def unfitted_calibration_state(reason: str) -> dict[str, Any]:
    return {
        "schema_version": CONFIDENCE_CALIBRATION_SCHEMA_VERSION,
        "fitted": False,
        "reason": str(reason or "CONFIDENCE_CALIBRATION_UNFITTED"),
        "temperature": None,
        "logit_scale": None,
        "temperature_fit_method": CONFIDENCE_TEMPERATURE_FIT_METHOD,
        "temperature_fit_boundary": None,
        "temperature_fit_bracket_expansions": 0,
        "temperature_fit_bisection_steps": 0,
        "temperature_fit_lower_logit_scale": None,
        "temperature_fit_upper_logit_scale": None,
        "temperature_fit_lower_score": None,
        "temperature_fit_upper_score": None,
        "calibration_error_estimator": CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR,
        "sample": 0,
        "positive_outcomes": 0,
        "negative_outcomes": 0,
        "fit_partition": CONFIDENCE_FIT_PARTITION,
        "validation_rows_used": 0,
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
        "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
        "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
        "action_counts": {action: 0 for action in CONFIDENCE_HEAD_ACTIONS},
        "model_parameter_fingerprint": None,
        "row_digest": None,
    }


def _legacy_unfitted_calibration_state(reason: str) -> dict[str, Any]:
    return {
        "schema_version": LEGACY_CONFIDENCE_CALIBRATION_SCHEMA_VERSION,
        "fitted": False,
        "reason": str(reason or "CONFIDENCE_CALIBRATION_UNFITTED"),
        "temperature": None,
        "sample": 0,
        "positive_outcomes": 0,
        "negative_outcomes": 0,
        "fit_partition": CONFIDENCE_FIT_PARTITION,
        "validation_rows_used": 0,
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
        "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
        "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
        "action_counts": {action: 0 for action in CONFIDENCE_HEAD_ACTIONS},
        "model_parameter_fingerprint": None,
        "row_digest": None,
    }


def normalize_legacy_calibration_state(
    state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Frozen V2 calibration-state verifier for immutable checkpoints."""

    if not isinstance(state, Mapping) or state.get("fitted") is not True:
        reason = (
            state.get("reason")
            if isinstance(state, Mapping)
            else "CHECKPOINT_CALIBRATION_STATE_MISSING"
        )
        return _legacy_unfitted_calibration_state(
            str(reason or "CONFIDENCE_CALIBRATION_UNFITTED")
        )
    temperature = _finite_float(state.get("temperature"))
    sample_count = _strict_nonnegative_int(state.get("sample"))
    positive_count = _strict_nonnegative_int(state.get("positive_outcomes"))
    negative_count = _strict_nonnegative_int(state.get("negative_outcomes"))
    validation_rows_used = _strict_nonnegative_int(
        state.get("validation_rows_used")
    )
    if None in (sample_count, positive_count, negative_count):
        return _legacy_unfitted_calibration_state(
            "CHECKPOINT_CALIBRATION_COUNTS_INVALID"
        )
    assert sample_count is not None
    assert positive_count is not None
    assert negative_count is not None
    row_digest = str(state.get("row_digest") or "")
    parameter_fingerprint = str(state.get("model_parameter_fingerprint") or "")
    valid_parameter_fingerprint = not parameter_fingerprint or (
        len(parameter_fingerprint) == 64
        and all(
            character in "0123456789abcdef"
            for character in parameter_fingerprint.lower()
        )
    )
    raw_action_counts = state.get("action_counts")
    try:
        if not isinstance(raw_action_counts, Mapping):
            raise TypeError
        parsed_action_counts = {
            action: _strict_nonnegative_int(raw_action_counts[action])
            for action in CONFIDENCE_HEAD_ACTIONS
        }
    except (KeyError, TypeError):
        parsed_action_counts = {action: None for action in CONFIDENCE_HEAD_ACTIONS}
    action_counts_valid = not any(
        value is None for value in parsed_action_counts.values()
    )
    action_counts = {
        action: int(parsed_action_counts[action] or 0)
        for action in CONFIDENCE_HEAD_ACTIONS
    }
    valid_digest = len(row_digest) == 64 and all(
        character in "0123456789abcdef" for character in row_digest.lower()
    )
    rejection_reason = None
    if state.get("schema_version") != LEGACY_CONFIDENCE_CALIBRATION_SCHEMA_VERSION:
        rejection_reason = "CHECKPOINT_CALIBRATION_SCHEMA_VERSION_INVALID"
    elif state.get("confidence_head_schema_version") != CONFIDENCE_HEAD_SCHEMA_VERSION:
        rejection_reason = "CHECKPOINT_CALIBRATION_CONFIDENCE_HEAD_SCHEMA_INVALID"
    elif tuple(state.get("confidence_head_actions") or ()) != CONFIDENCE_HEAD_ACTIONS:
        rejection_reason = "CHECKPOINT_CALIBRATION_CONFIDENCE_HEAD_ACTIONS_INVALID"
    elif not action_counts_valid:
        rejection_reason = "CHECKPOINT_CALIBRATION_COUNTS_INVALID"
    elif any(action_counts[action] <= 0 for action in CONFIDENCE_HEAD_ACTIONS):
        rejection_reason = (
            "CHECKPOINT_CALIBRATION_DIRECTIONAL_ACTION_COVERAGE_MISSING"
        )
    elif sum(action_counts.values()) != sample_count:
        rejection_reason = "CHECKPOINT_CALIBRATION_ACTION_COUNTS_MISMATCH"
    elif not valid_parameter_fingerprint:
        rejection_reason = "CHECKPOINT_CALIBRATION_MODEL_FINGERPRINT_INVALID"
    elif temperature is None or temperature <= 0.0:
        rejection_reason = "CHECKPOINT_CALIBRATION_TEMPERATURE_INVALID"
    elif state.get("label_semantics") != CONFIDENCE_LABEL_SEMANTICS:
        rejection_reason = "CHECKPOINT_CALIBRATION_LABEL_SEMANTICS_INVALID"
    elif state.get("fit_partition") != CONFIDENCE_FIT_PARTITION:
        rejection_reason = "CHECKPOINT_CALIBRATION_PARTITION_INVALID"
    elif validation_rows_used is None:
        rejection_reason = "CHECKPOINT_CALIBRATION_VALIDATION_ROW_COUNT_INVALID"
    elif validation_rows_used != 0:
        rejection_reason = "CHECKPOINT_CALIBRATION_USED_FORWARD_VALIDATION"
    elif sample_count != positive_count + negative_count:
        rejection_reason = "CHECKPOINT_CALIBRATION_COUNTS_MISMATCH"
    elif sample_count < 2 or positive_count <= 0 or negative_count <= 0:
        rejection_reason = "CHECKPOINT_CALIBRATION_CLASS_VARIATION_MISSING"
    elif not valid_digest:
        rejection_reason = "CHECKPOINT_CALIBRATION_ROW_DIGEST_INVALID"
    if rejection_reason is not None:
        return _legacy_unfitted_calibration_state(rejection_reason)
    assert temperature is not None
    normalized: dict[str, Any] = {
        "schema_version": LEGACY_CONFIDENCE_CALIBRATION_SCHEMA_VERSION,
        "fitted": True,
        "reason": None,
        "temperature": float(temperature),
        "sample": sample_count,
        "positive_outcomes": positive_count,
        "negative_outcomes": negative_count,
        "fit_partition": CONFIDENCE_FIT_PARTITION,
        "validation_rows_used": 0,
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
        "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
        "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
        "action_counts": action_counts,
        "model_parameter_fingerprint": (
            parameter_fingerprint.lower() if parameter_fingerprint else None
        ),
        "row_digest": row_digest.lower(),
    }
    for metric_name in (
        "win_rate",
        "nll_before",
        "nll_after",
        "ece_before",
        "ece_after",
        "brier_before",
        "brier_after",
    ):
        metric_value = _finite_float(state.get(metric_name))
        if metric_value is not None:
            normalized[metric_name] = metric_value
    return normalized


def _normalize_current_calibration_state(
    state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Validate a calibration state before inference or checkpoint restore."""
    if not isinstance(state, Mapping) or state.get("fitted") is not True:
        reason = (
            state.get("reason")
            if isinstance(state, Mapping)
            else "CHECKPOINT_CALIBRATION_STATE_MISSING"
        )
        return unfitted_calibration_state(str(reason or "CONFIDENCE_CALIBRATION_UNFITTED"))
    temperature = _finite_float(state.get("temperature"))
    logit_scale = _finite_float(state.get("logit_scale"))
    lower_logit_scale = _finite_float(
        state.get("temperature_fit_lower_logit_scale")
    )
    upper_logit_scale = _finite_float(
        state.get("temperature_fit_upper_logit_scale")
    )
    lower_score = _finite_float(state.get("temperature_fit_lower_score"))
    upper_score = _finite_float(state.get("temperature_fit_upper_score"))
    bracket_expansions = _strict_nonnegative_int(
        state.get("temperature_fit_bracket_expansions")
    )
    bisection_steps = _strict_nonnegative_int(
        state.get("temperature_fit_bisection_steps")
    )
    sample = state.get("sample")
    positives = state.get("positive_outcomes")
    negatives = state.get("negative_outcomes")
    sample_count = _strict_nonnegative_int(sample)
    positive_count = _strict_nonnegative_int(positives)
    negative_count = _strict_nonnegative_int(negatives)
    validation_rows_used = _strict_nonnegative_int(
        state.get("validation_rows_used")
    )
    if None in (sample_count, positive_count, negative_count):
        return unfitted_calibration_state("CHECKPOINT_CALIBRATION_COUNTS_INVALID")
    assert sample_count is not None
    assert positive_count is not None
    assert negative_count is not None
    row_digest = str(state.get("row_digest") or "")
    parameter_fingerprint = str(state.get("model_parameter_fingerprint") or "")
    valid_parameter_fingerprint = not parameter_fingerprint or (
        len(parameter_fingerprint) == 64
        and all(
            character in "0123456789abcdef"
            for character in parameter_fingerprint.lower()
        )
    )
    raw_action_counts = state.get("action_counts")
    try:
        if not isinstance(raw_action_counts, Mapping):
            raise TypeError
        parsed_action_counts = {
            action: _strict_nonnegative_int(raw_action_counts[action])
            for action in CONFIDENCE_HEAD_ACTIONS
        }
    except (KeyError, TypeError):
        parsed_action_counts = {action: None for action in CONFIDENCE_HEAD_ACTIONS}
    if any(value is None for value in parsed_action_counts.values()):
        action_counts = {action: 0 for action in CONFIDENCE_HEAD_ACTIONS}
        action_counts_valid = False
    else:
        action_counts = {
            action: int(cast(int, parsed_action_counts[action]))
            for action in CONFIDENCE_HEAD_ACTIONS
        }
        action_counts_valid = True
    valid_digest = len(row_digest) == 64 and all(
        character in "0123456789abcdef" for character in row_digest.lower()
    )
    fit_boundary = state.get("temperature_fit_boundary")
    interior_root_proof_valid = bool(
        fit_boundary == CONFIDENCE_TEMPERATURE_FIT_INTERIOR
        and temperature is not None
        and temperature > 0.0
        and logit_scale is not None
        and logit_scale > 0.0
        and temperature == 1.0 / logit_scale
        and lower_logit_scale is not None
        and upper_logit_scale is not None
        and lower_score is not None
        and upper_score is not None
        and lower_logit_scale >= 0.0
        and upper_logit_scale > lower_logit_scale
        and logit_scale in (lower_logit_scale, upper_logit_scale)
        and lower_score <= 0.0
        and upper_score >= 0.0
        and math.nextafter(lower_logit_scale, upper_logit_scale)
        == upper_logit_scale
    )
    zero_scale_proof_valid = bool(
        fit_boundary == CONFIDENCE_TEMPERATURE_FIT_ZERO_SCALE
        and state.get("temperature") is None
        and logit_scale == 0.0
        and bracket_expansions == 0
        and bisection_steps == 0
        and lower_logit_scale == 0.0
        and upper_logit_scale == 0.0
        and lower_score is not None
        and upper_score == lower_score
        and lower_score >= 0.0
    )
    rejection_reason = None
    if state.get("schema_version") != CONFIDENCE_CALIBRATION_SCHEMA_VERSION:
        rejection_reason = "CHECKPOINT_CALIBRATION_SCHEMA_VERSION_INVALID"
    elif state.get("confidence_head_schema_version") != CONFIDENCE_HEAD_SCHEMA_VERSION:
        rejection_reason = "CHECKPOINT_CALIBRATION_CONFIDENCE_HEAD_SCHEMA_INVALID"
    elif tuple(state.get("confidence_head_actions") or ()) != CONFIDENCE_HEAD_ACTIONS:
        rejection_reason = "CHECKPOINT_CALIBRATION_CONFIDENCE_HEAD_ACTIONS_INVALID"
    elif not action_counts_valid:
        rejection_reason = "CHECKPOINT_CALIBRATION_COUNTS_INVALID"
    elif any(action_counts[action] <= 0 for action in CONFIDENCE_HEAD_ACTIONS):
        rejection_reason = "CHECKPOINT_CALIBRATION_DIRECTIONAL_ACTION_COVERAGE_MISSING"
    elif sum(action_counts.values()) != sample_count:
        rejection_reason = "CHECKPOINT_CALIBRATION_ACTION_COUNTS_MISMATCH"
    elif not valid_parameter_fingerprint:
        rejection_reason = "CHECKPOINT_CALIBRATION_MODEL_FINGERPRINT_INVALID"
    elif logit_scale is None or logit_scale < 0.0:
        rejection_reason = "CHECKPOINT_CALIBRATION_LOGIT_SCALE_INVALID"
    elif state.get("temperature_fit_method") != CONFIDENCE_TEMPERATURE_FIT_METHOD:
        rejection_reason = "CHECKPOINT_CALIBRATION_FIT_METHOD_INVALID"
    elif fit_boundary not in {
        CONFIDENCE_TEMPERATURE_FIT_INTERIOR,
        CONFIDENCE_TEMPERATURE_FIT_ZERO_SCALE,
    }:
        rejection_reason = "CHECKPOINT_CALIBRATION_FIT_BOUNDARY_INVALID"
    elif state.get("calibration_error_estimator") != CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR:
        rejection_reason = "CHECKPOINT_CALIBRATION_ERROR_ESTIMATOR_INVALID"
    elif bracket_expansions is None or bisection_steps is None:
        rejection_reason = "CHECKPOINT_CALIBRATION_FIT_CONVERGENCE_INVALID"
    elif not (interior_root_proof_valid or zero_scale_proof_valid):
        rejection_reason = "CHECKPOINT_CALIBRATION_FIT_ROOT_PROOF_INVALID"
    elif state.get("label_semantics") != CONFIDENCE_LABEL_SEMANTICS:
        rejection_reason = "CHECKPOINT_CALIBRATION_LABEL_SEMANTICS_INVALID"
    elif state.get("fit_partition") != CONFIDENCE_FIT_PARTITION:
        rejection_reason = "CHECKPOINT_CALIBRATION_PARTITION_INVALID"
    elif validation_rows_used is None:
        rejection_reason = "CHECKPOINT_CALIBRATION_VALIDATION_ROW_COUNT_INVALID"
    elif validation_rows_used != 0:
        rejection_reason = "CHECKPOINT_CALIBRATION_USED_FORWARD_VALIDATION"
    elif sample_count != positive_count + negative_count:
        rejection_reason = "CHECKPOINT_CALIBRATION_COUNTS_MISMATCH"
    elif sample_count < 2 or positive_count <= 0 or negative_count <= 0:
        rejection_reason = "CHECKPOINT_CALIBRATION_CLASS_VARIATION_MISSING"
    elif not valid_digest:
        rejection_reason = "CHECKPOINT_CALIBRATION_ROW_DIGEST_INVALID"
    if rejection_reason is not None:
        return unfitted_calibration_state(rejection_reason)
    assert logit_scale is not None
    normalized: dict[str, Any] = {
        "schema_version": CONFIDENCE_CALIBRATION_SCHEMA_VERSION,
        "fitted": True,
        "reason": None,
        "temperature": float(temperature) if temperature is not None else None,
        "logit_scale": float(logit_scale),
        "temperature_fit_method": CONFIDENCE_TEMPERATURE_FIT_METHOD,
        "temperature_fit_boundary": fit_boundary,
        "temperature_fit_bracket_expansions": bracket_expansions,
        "temperature_fit_bisection_steps": bisection_steps,
        "temperature_fit_lower_logit_scale": lower_logit_scale,
        "temperature_fit_upper_logit_scale": upper_logit_scale,
        "temperature_fit_lower_score": lower_score,
        "temperature_fit_upper_score": upper_score,
        "calibration_error_estimator": CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR,
        "sample": sample_count,
        "positive_outcomes": positive_count,
        "negative_outcomes": negative_count,
        "fit_partition": CONFIDENCE_FIT_PARTITION,
        "validation_rows_used": 0,
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
        "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
        "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
        "action_counts": action_counts,
        "model_parameter_fingerprint": (
            parameter_fingerprint.lower() if parameter_fingerprint else None
        ),
        "row_digest": row_digest.lower(),
    }
    for metric_name in (
        "win_rate",
        "nll_before",
        "nll_after",
        "ece_before",
        "ece_after",
        "brier_before",
        "brier_after",
    ):
        metric_value = _finite_float(state.get(metric_name))
        if metric_value is not None:
            normalized[metric_name] = metric_value
    return normalized


def normalize_calibration_state(
    state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Version-dispatch checkpoint calibration without rewriting evidence."""

    if (
        isinstance(state, Mapping)
        and state.get("schema_version")
        == LEGACY_CONFIDENCE_CALIBRATION_SCHEMA_VERSION
    ):
        return normalize_legacy_calibration_state(state)
    return _normalize_current_calibration_state(state)


def _softplus(value: float) -> float:
    return max(value, 0.0) + math.log1p(math.exp(-abs(value)))


def _logit(probability: float) -> float:
    opened = _open_unit_probability(probability)
    return math.log(opened / (1.0 - opened))


def _logit_scale_score(
    logits: Sequence[float], labels: Sequence[int], logit_scale: float
) -> float:
    return sum(
        logit * (_stable_sigmoid(logit * logit_scale) - label)
        for logit, label in zip(logits, labels, strict=True)
    ) / len(logits)


def _logit_scale_nll(
    logits: Sequence[float], labels: Sequence[int], logit_scale: float
) -> float:
    return sum(
        _softplus(-logit * logit_scale)
        if label == 1
        else _softplus(logit * logit_scale)
        for logit, label in zip(logits, labels, strict=True)
    ) / len(logits)


def _finite_temperature_score_root(
    probabilities: Sequence[float], labels: Sequence[int]
) -> dict[str, Any] | None:
    """Solve the convex temperature score equation without search settings.

    The optimization parameter is the nonnegative logit multiplier beta=1/T.
    The optimum is either the honest beta=0 boundary or a finite interior
    root.  An interior root exists only when the score is negative at beta=0
    and strictly positive in the beta-to-infinity limit.  The bracket expands
    from the identity beta=1 according to the observed score, then bisects
    until its endpoints are adjacent IEEE-754 floats.  No caller bound, grid,
    tolerance, iteration count, sample threshold, or market threshold is used.
    """

    logits = [_logit(probability) for probability in probabilities]
    score_at_zero = _logit_scale_score(logits, labels, 0.0)
    limiting_score = sum(
        (
            logit * (1 - label)
            if logit > 0.0
            else -logit * label
            if logit < 0.0
            else 0.0
        )
        for logit, label in zip(logits, labels, strict=True)
    ) / len(logits)
    if not any(logit != 0.0 for logit in logits):
        return None
    if score_at_zero >= 0.0:
        return {
            "temperature": None,
            "logit_scale": 0.0,
            "temperature_fit_method": CONFIDENCE_TEMPERATURE_FIT_METHOD,
            "temperature_fit_boundary": CONFIDENCE_TEMPERATURE_FIT_ZERO_SCALE,
            "temperature_fit_bracket_expansions": 0,
            "temperature_fit_bisection_steps": 0,
            "temperature_fit_lower_logit_scale": 0.0,
            "temperature_fit_upper_logit_scale": 0.0,
            "temperature_fit_lower_score": score_at_zero,
            "temperature_fit_upper_score": score_at_zero,
            "calibration_error_estimator": (
                CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR
            ),
        }
    if limiting_score <= 0.0:
        return None
    lower = 0.0
    lower_score = score_at_zero
    upper = 1.0
    upper_score = _logit_scale_score(logits, labels, upper)
    expansions = 0
    while upper_score < 0.0:
        expanded = upper * 2.0
        if not math.isfinite(expanded):
            return None
        lower = upper
        lower_score = upper_score
        upper = expanded
        upper_score = _logit_scale_score(logits, labels, upper)
        expansions += 1
    bisection_steps = 0
    while math.nextafter(lower, upper) != upper:
        middle = lower + (upper - lower) / 2.0
        if middle in (lower, upper):
            break
        middle_score = _logit_scale_score(logits, labels, middle)
        if middle_score < 0.0:
            lower = middle
            lower_score = middle_score
        else:
            upper = middle
            upper_score = middle_score
        bisection_steps += 1
    if math.nextafter(lower, upper) != upper:
        return None
    fitted_scale = min(
        (lower, upper),
        key=lambda value: _logit_scale_nll(logits, labels, value),
    )
    if fitted_scale <= 0.0 or not math.isfinite(fitted_scale):
        return None
    temperature = 1.0 / fitted_scale
    if not math.isfinite(temperature) or temperature <= 0.0:
        return None
    return {
        "temperature": temperature,
        "logit_scale": fitted_scale,
        "temperature_fit_method": CONFIDENCE_TEMPERATURE_FIT_METHOD,
        "temperature_fit_boundary": CONFIDENCE_TEMPERATURE_FIT_INTERIOR,
        "temperature_fit_bracket_expansions": expansions,
        "temperature_fit_bisection_steps": bisection_steps,
        "temperature_fit_lower_logit_scale": lower,
        "temperature_fit_upper_logit_scale": upper,
        "temperature_fit_lower_score": lower_score,
        "temperature_fit_upper_score": upper_score,
        "calibration_error_estimator": CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR,
    }


def _legacy_nll(
    raw_probs: Sequence[float],
    outcomes: Sequence[int],
    temperature: float,
) -> float:
    total = 0.0
    for raw, outcome in zip(raw_probs, outcomes, strict=True):
        probability = max(
            1e-6,
            min(
                1.0 - 1e-6,
                legacy_temperature_scaled_probability(raw, temperature),
            ),
        )
        total += -(
            outcome * math.log(probability)
            + (1 - outcome) * math.log(1.0 - probability)
        )
    return total / len(raw_probs) if raw_probs else float("inf")


def fit_legacy_temperature(
    raw_probs: Sequence[float],
    outcomes: Sequence[int],
    *,
    row_ids: Sequence[str] | None = None,
    action_labels: Sequence[str] | None = None,
    fit_partition: str = CONFIDENCE_FIT_PARTITION,
    validation_rows_used: int = 0,
) -> dict[str, Any]:
    """Frozen V2 optimizer used only to verify immutable legacy artifacts."""

    if fit_partition != CONFIDENCE_FIT_PARTITION:
        return _legacy_unfitted_calibration_state(
            "CALIBRATION_PARTITION_NOT_PURGED_TRAIN_ONLY"
        )
    parsed_validation_rows_used = _strict_nonnegative_int(validation_rows_used)
    if parsed_validation_rows_used is None:
        return _legacy_unfitted_calibration_state(
            "CALIBRATION_VALIDATION_ROW_COUNT_INVALID"
        )
    if parsed_validation_rows_used != 0:
        return _legacy_unfitted_calibration_state(
            "CALIBRATION_FORWARD_VALIDATION_LEAKAGE_BLOCKED"
        )
    if len(raw_probs) != len(outcomes):
        return _legacy_unfitted_calibration_state(
            "CALIBRATION_INPUT_LENGTH_MISMATCH"
        )
    if row_ids is None or len(row_ids) != len(raw_probs):
        return _legacy_unfitted_calibration_state(
            "CALIBRATION_ROW_ID_LENGTH_MISMATCH"
        )
    if action_labels is None or len(action_labels) != len(raw_probs):
        return _legacy_unfitted_calibration_state(
            "CALIBRATION_ACTION_LABELS_MISSING_OR_LENGTH_MISMATCH"
        )
    probabilities: list[float] = []
    labels: list[int] = []
    actions: list[str] = []
    for raw, outcome, raw_action in zip(
        raw_probs,
        outcomes,
        action_labels,
        strict=True,
    ):
        probability = _finite_float(raw)
        if probability is None or not 0.0 <= probability <= 1.0:
            return _legacy_unfitted_calibration_state(
                "CALIBRATION_PROBABILITY_INVALID"
            )
        if isinstance(outcome, bool):
            label = int(outcome)
        elif outcome in (0, 1):
            label = int(outcome)
        else:
            return _legacy_unfitted_calibration_state(
                "CALIBRATION_OUTCOME_NOT_BINARY"
            )
        action = str(raw_action or "").strip().lower()
        if action not in CONFIDENCE_HEAD_ACTION_INDEX:
            return _legacy_unfitted_calibration_state(
                "CALIBRATION_DIRECTIONAL_ACTION_INVALID"
            )
        probabilities.append(probability)
        labels.append(label)
        actions.append(action)
    positives = sum(labels)
    negatives = len(labels) - positives
    if not labels or positives <= 0 or negatives <= 0:
        return _legacy_unfitted_calibration_state(
            "CALIBRATION_CLASS_VARIATION_MISSING"
        )
    action_counts = {
        action: actions.count(action) for action in CONFIDENCE_HEAD_ACTIONS
    }
    if any(action_counts[action] <= 0 for action in CONFIDENCE_HEAD_ACTIONS):
        return _legacy_unfitted_calibration_state(
            "CALIBRATION_DIRECTIONAL_ACTION_COVERAGE_MISSING"
        )
    lower_bound = 0.25
    upper_bound = 6.0
    grid = [
        lower_bound + (upper_bound - lower_bound) * index / 40.0
        for index in range(41)
    ]
    best_temperature = min(
        grid,
        key=lambda value: _legacy_nll(probabilities, labels, value),
    )
    radius = (upper_bound - lower_bound) / 40.0
    lower = max(lower_bound, best_temperature - radius)
    upper = min(upper_bound, best_temperature + radius)
    golden_ratio = (math.sqrt(5.0) - 1.0) / 2.0
    left = upper - golden_ratio * (upper - lower)
    right = lower + golden_ratio * (upper - lower)
    for _ in range(40):
        if _legacy_nll(probabilities, labels, left) < _legacy_nll(
            probabilities,
            labels,
            right,
        ):
            upper = right
        else:
            lower = left
        left = upper - golden_ratio * (upper - lower)
        right = lower + golden_ratio * (upper - lower)
    fitted_temperature = (lower + upper) / 2.0
    digest_material = [
        {
            "row_id": str(row_id),
            "selected_action": action,
            "raw_probability": probability,
            "outcome": label,
        }
        for row_id, action, probability, label in zip(
            row_ids,
            actions,
            probabilities,
            labels,
            strict=True,
        )
    ]
    row_digest = hashlib.sha256(
        json.dumps(
            digest_material,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    state = {
        "schema_version": LEGACY_CONFIDENCE_CALIBRATION_SCHEMA_VERSION,
        "fitted": True,
        "reason": None,
        "temperature": float(fitted_temperature),
        "sample": len(labels),
        "positive_outcomes": positives,
        "negative_outcomes": negatives,
        "win_rate": positives / len(labels),
        "nll_before": _legacy_nll(probabilities, labels, 1.0),
        "nll_after": _legacy_nll(probabilities, labels, fitted_temperature),
        "ece_before": legacy_expected_calibration_error(
            probabilities,
            labels,
            1.0,
        ),
        "ece_after": legacy_expected_calibration_error(
            probabilities,
            labels,
            fitted_temperature,
        ),
        "brier_before": legacy_brier_score(probabilities, labels, 1.0),
        "brier_after": legacy_brier_score(
            probabilities,
            labels,
            fitted_temperature,
        ),
        "fit_partition": CONFIDENCE_FIT_PARTITION,
        "validation_rows_used": 0,
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
        "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
        "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
        "action_counts": action_counts,
        "model_parameter_fingerprint": None,
        "row_digest": row_digest,
    }
    return normalize_legacy_calibration_state(state)


def fit_temperature(
    raw_probs: Sequence[float],
    outcomes: Sequence[int],
    *,
    row_ids: Sequence[str] | None = None,
    action_labels: Sequence[str] | None = None,
    fit_partition: str = CONFIDENCE_FIT_PARTITION,
    validation_rows_used: int = 0,
) -> dict[str, Any]:
    """Fit temperature using only a purged training partition.

    The mathematically necessary requirements are exact length agreement,
    finite probabilities, binary labels, and both outcome classes.  There is no
    arbitrary minimum-N admission shortcut.  Forward-validation rows are never
    accepted by this fitting API.
    """
    if fit_partition != CONFIDENCE_FIT_PARTITION:
        return unfitted_calibration_state("CALIBRATION_PARTITION_NOT_PURGED_TRAIN_ONLY")
    parsed_validation_rows_used = _strict_nonnegative_int(validation_rows_used)
    if parsed_validation_rows_used is None:
        return unfitted_calibration_state("CALIBRATION_VALIDATION_ROW_COUNT_INVALID")
    if parsed_validation_rows_used != 0:
        return unfitted_calibration_state("CALIBRATION_FORWARD_VALIDATION_LEAKAGE_BLOCKED")
    if len(raw_probs) != len(outcomes):
        return unfitted_calibration_state("CALIBRATION_INPUT_LENGTH_MISMATCH")
    if row_ids is None or len(row_ids) != len(raw_probs):
        return unfitted_calibration_state("CALIBRATION_ROW_ID_LENGTH_MISMATCH")
    if action_labels is None or len(action_labels) != len(raw_probs):
        return unfitted_calibration_state(
            "CALIBRATION_ACTION_LABELS_MISSING_OR_LENGTH_MISMATCH"
        )
    probabilities: list[float] = []
    labels: list[int] = []
    actions: list[str] = []
    for raw, outcome, raw_action in zip(
        raw_probs,
        outcomes,
        action_labels,
        strict=True,
    ):
        probability = _finite_float(raw)
        if probability is None or not 0.0 <= probability <= 1.0:
            return unfitted_calibration_state("CALIBRATION_PROBABILITY_INVALID")
        if isinstance(outcome, bool):
            label = int(outcome)
        elif outcome in (0, 1):
            label = int(outcome)
        else:
            return unfitted_calibration_state("CALIBRATION_OUTCOME_NOT_BINARY")
        action = str(raw_action or "").strip().lower()
        if action not in CONFIDENCE_HEAD_ACTION_INDEX:
            return unfitted_calibration_state("CALIBRATION_DIRECTIONAL_ACTION_INVALID")
        probabilities.append(probability)
        labels.append(label)
        actions.append(action)
    positives = sum(labels)
    negatives = len(labels) - positives
    if not labels or positives <= 0 or negatives <= 0:
        return unfitted_calibration_state("CALIBRATION_CLASS_VARIATION_MISSING")
    action_counts = {
        action: actions.count(action) for action in CONFIDENCE_HEAD_ACTIONS
    }
    if any(action_counts[action] <= 0 for action in CONFIDENCE_HEAD_ACTIONS):
        return unfitted_calibration_state(
            "CALIBRATION_DIRECTIONAL_ACTION_COVERAGE_MISSING"
        )
    fit_proof = _finite_temperature_score_root(probabilities, labels)
    if fit_proof is None:
        return unfitted_calibration_state(
            "CALIBRATION_FINITE_INTERIOR_TEMPERATURE_NOT_IDENTIFIABLE"
        )
    fitted_logit_scale = float(fit_proof["logit_scale"])
    identifiers = list(row_ids)
    digest_material = [
        {
            "row_id": str(row_id),
            "selected_action": action,
            "raw_probability": probability,
            "outcome": label,
        }
        for row_id, action, probability, label in zip(
            identifiers,
            actions,
            probabilities,
            labels,
            strict=True,
        )
    ]
    row_digest = hashlib.sha256(
        json.dumps(digest_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    logits = [_logit(probability) for probability in probabilities]
    brier_before = brier_score(probabilities, labels)
    brier_after = brier_score(
        probabilities,
        labels,
        logit_scale=fitted_logit_scale,
    )
    state = {
        "schema_version": CONFIDENCE_CALIBRATION_SCHEMA_VERSION,
        "fitted": True,
        "reason": None,
        **fit_proof,
        "sample": len(labels),
        "positive_outcomes": positives,
        "negative_outcomes": negatives,
        "win_rate": positives / len(labels),
        "nll_before": _logit_scale_nll(logits, labels, 1.0),
        "nll_after": _logit_scale_nll(logits, labels, fitted_logit_scale),
        "ece_before": expected_calibration_error(probabilities, labels),
        "ece_after": expected_calibration_error(
            probabilities,
            labels,
            logit_scale=fitted_logit_scale,
        ),
        "brier_before": brier_before,
        "brier_after": brier_after,
        "fit_partition": CONFIDENCE_FIT_PARTITION,
        "validation_rows_used": 0,
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
        "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
        "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
        "action_counts": action_counts,
        "model_parameter_fingerprint": None,
        "row_digest": row_digest,
    }
    return normalize_calibration_state(state)


def resolve_confidence_temperature(
    calibration_state: Mapping[str, Any] | None = None,
) -> float | None:
    """Return only a valid checkpoint-bound temperature; never use global state."""
    normalized = normalize_calibration_state(calibration_state)
    if normalized.get("fitted") is not True:
        return None
    fingerprint = str(normalized.get("model_parameter_fingerprint") or "")
    if len(fingerprint) != 64:
        return None
    temperature = _finite_float(normalized.get("temperature"))
    return temperature if temperature is not None and temperature > 0.0 else None


def resolve_confidence_logit_scale(
    calibration_state: Mapping[str, Any] | None = None,
) -> float | None:
    """Return a valid checkpoint-bound inverse temperature, including zero."""

    normalized = normalize_calibration_state(calibration_state)
    if normalized.get("fitted") is not True:
        return None
    fingerprint = str(normalized.get("model_parameter_fingerprint") or "")
    if len(fingerprint) != 64:
        return None
    if (
        normalized.get("schema_version")
        == LEGACY_CONFIDENCE_CALIBRATION_SCHEMA_VERSION
    ):
        temperature = _finite_float(normalized.get("temperature"))
        return (
            1.0 / temperature
            if temperature is not None and temperature > 0.0
            else None
        )
    logit_scale = _finite_float(normalized.get("logit_scale"))
    return logit_scale if logit_scale is not None and logit_scale >= 0.0 else None


def profitability_target_from_trust_row(
    trust_row: Mapping[str, Any],
    *,
    decision_time: Any = None,
    label_available_at: Any = None,
) -> dict[str, Any]:
    """Resolve one strict binary after-cost profitability target.

    A row that cannot prove clocks, closed-candle finality, directional action,
    entry/exit prices, side, closed quantity, a positive close-specific entry
    notional, and unit-explicit fee/slippage/funding USD evidence is excluded
    from confidence loss and calibration. Claimed gross/net USD/bps and outcome
    signs are consistency checks; the target comes only from recomputed close
    economics. The row may still be usable by other trainer heads.
    """
    outcome_targets = trust_row.get("outcome_targets")
    targets = outcome_targets if isinstance(outcome_targets, Mapping) else {}

    def blocked(reason: str) -> dict[str, Any]:
        return {
            "eligible": False,
            "target": None,
            "reason": reason,
            "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
        }

    if trust_row.get("accepted_for_training") is not True:
        return blocked("CONFIDENCE_TARGET_NOT_ACCEPTED_FOR_TRAINING")
    if trust_row.get("valid_for_training") is not True:
        return blocked("CONFIDENCE_TARGET_NOT_VALID_FOR_TRAINING")
    if trust_row.get("trainer_consumable") is not True:
        return blocked("CONFIDENCE_TARGET_NOT_TRAINER_CONSUMABLE")
    if trust_row.get("candle_closed_confirmed") is not True:
        return blocked("CONFIDENCE_TARGET_CANDLE_FINALITY_UNPROVEN")
    if trust_row.get("future_labels_used_as_features") is True:
        return blocked("CONFIDENCE_TARGET_FUTURE_LABEL_FEATURE_LEAKAGE")
    if trust_row.get("post_outcome_candidate_selection") is True:
        return blocked("CONFIDENCE_TARGET_POST_OUTCOME_SELECTION")

    resolved_decision_time = _parse_utc(
        _first_present(
            decision_time,
            trust_row.get("decision_time"),
            trust_row.get("decision_time_est"),
            trust_row.get("decision_cutoff_time_est"),
        )
    )
    resolved_label_time = _parse_utc(
        _first_present(
            label_available_at,
            trust_row.get("label_available_at"),
            trust_row.get("outcome_available_at"),
            trust_row.get("exit_time"),
            trust_row.get("close_event_time"),
            trust_row.get("closed_at"),
        )
    )
    explicit_exit_time = _parse_utc(
        _first_present(
            trust_row.get("exit_time"),
            trust_row.get("close_event_time"),
            trust_row.get("exit_price_utc"),
            trust_row.get("closed_at"),
            targets.get("exit_time"),
            targets.get("closed_at"),
        )
    )
    if resolved_decision_time is None:
        return blocked("CONFIDENCE_TARGET_DECISION_TIME_INVALID")
    if resolved_label_time is None or explicit_exit_time is None:
        return blocked("CONFIDENCE_TARGET_LABEL_FINALITY_TIME_UNPROVEN")
    if resolved_label_time < explicit_exit_time:
        return blocked("CONFIDENCE_TARGET_AVAILABLE_BEFORE_EXPLICIT_EXIT")
    if explicit_exit_time <= resolved_decision_time:
        return blocked("CONFIDENCE_TARGET_EXIT_NOT_STRICTLY_AFTER_DECISION")
    if resolved_label_time <= resolved_decision_time:
        return blocked("CONFIDENCE_TARGET_NOT_STRICTLY_AFTER_DECISION")

    required_decision_clocks = {
        "candle_close_time": trust_row.get("candle_close_time"),
        "feature_cutoff": _first_present(
            trust_row.get("feature_cutoff"),
            trust_row.get("decision_cutoff"),
        ),
        "available_at": _first_present(
            trust_row.get("available_at"),
            trust_row.get("source_available_time"),
        ),
    }
    parsed_decision_clocks: dict[str, datetime] = {}
    for field_name, raw_time in required_decision_clocks.items():
        parsed_time = _parse_utc(raw_time)
        if parsed_time is None:
            return blocked(f"CONFIDENCE_TARGET_{field_name.upper()}_INVALID")
        parsed_decision_clocks[field_name] = parsed_time
    if parsed_decision_clocks["available_at"] > resolved_decision_time:
        return blocked("CONFIDENCE_TARGET_AVAILABLE_AT_AFTER_DECISION")
    if parsed_decision_clocks["available_at"] == resolved_decision_time:
        return blocked(
            "CONFIDENCE_TARGET_AVAILABLE_AT_NOT_STRICTLY_BEFORE_DECISION"
        )
    if not (
        parsed_decision_clocks["candle_close_time"]
        <= parsed_decision_clocks["feature_cutoff"]
        <= parsed_decision_clocks["available_at"]
        < resolved_decision_time
    ):
        return blocked("CONFIDENCE_TARGET_DECISION_CLOCK_ORDER_INVALID")
    model_cutoffs: dict[str, datetime] = {}
    for field_name in ("masa_feature_cutoff", "ppo_feature_cutoff"):
        raw_time = trust_row.get(field_name)
        parsed_time = _parse_utc(raw_time)
        if parsed_time is None:
            return blocked(f"CONFIDENCE_TARGET_{field_name.upper()}_INVALID")
        model_cutoffs[field_name] = parsed_time
    if not (
        model_cutoffs["masa_feature_cutoff"]
        <= model_cutoffs["ppo_feature_cutoff"]
        <= resolved_decision_time
    ):
        return blocked("CONFIDENCE_TARGET_CROSS_MODEL_CUTOFF_ORDER_INVALID")

    actions = [
        str(value).strip().lower()
        for value in (
            targets.get("selected_action"),
            trust_row.get("selected_action"),
            trust_row.get("behavior_action"),
            trust_row.get("action"),
            trust_row.get("side"),
        )
        if value not in (None, "")
    ]
    if not actions:
        return blocked("CONFIDENCE_TARGET_SELECTED_ACTION_MISSING")
    if any(action not in {"long", "short"} for action in actions):
        return blocked("CONFIDENCE_TARGET_HOLD_OR_INVALID_ACTION_EXCLUDED")
    if len(set(actions)) != 1:
        return blocked("CONFIDENCE_TARGET_SELECTED_ACTION_IDENTITY_MISMATCH")
    side = str(trust_row.get("side") or "").strip().lower()
    if side not in {"long", "short"}:
        return blocked("CONFIDENCE_TARGET_SIDE_MISSING_OR_INVALID")
    if side != actions[0]:
        return blocked("CONFIDENCE_TARGET_SIDE_ACTION_MISMATCH")

    def consistent_economic_value(
        field_name: str,
        raw_values: Sequence[Any],
        *,
        required: bool = True,
    ) -> tuple[float | None, str | None]:
        present = [value for value in raw_values if value not in (None, "")]
        if not present:
            return (
                None,
                f"CONFIDENCE_TARGET_{field_name}_MISSING" if required else None,
            )
        parsed: list[float] = []
        for raw_value in present:
            value = _finite_float(raw_value)
            if value is None:
                return None, f"CONFIDENCE_TARGET_{field_name}_INVALID"
            parsed.append(value)
        reference = parsed[0]
        if any(
            not math.isclose(value, reference, rel_tol=1e-9, abs_tol=1e-9)
            for value in parsed[1:]
        ):
            return None, f"CONFIDENCE_TARGET_{field_name}_CONFLICT"
        return reference, None

    target_net_pnl_bps, reason = consistent_economic_value(
        "REALIZED_NET_PNL_BPS",
        (targets.get("realized_net_pnl_bps"),),
    )
    if reason is not None:
        return blocked(reason)
    row_net_pnl_bps, reason = consistent_economic_value(
        "REALIZED_NET_PNL_BPS",
        (trust_row.get("realized_net_pnl_bps"),),
    )
    if reason is not None:
        return blocked(reason)
    assert target_net_pnl_bps is not None and row_net_pnl_bps is not None
    if not math.isclose(
        target_net_pnl_bps,
        row_net_pnl_bps,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_REALIZED_NET_PNL_BPS_CONFLICT")

    target_net_pnl_usd, reason = consistent_economic_value(
        "REALIZED_NET_PNL_USD",
        (targets.get("realized_net_pnl_usd"),),
    )
    if reason is not None:
        return blocked(reason)
    row_net_pnl_usd, reason = consistent_economic_value(
        "REALIZED_NET_PNL_USD",
        (trust_row.get("realized_net_pnl_usd"),),
    )
    if reason is not None:
        return blocked(reason)
    assert target_net_pnl_usd is not None and row_net_pnl_usd is not None
    if not math.isclose(
        target_net_pnl_usd,
        row_net_pnl_usd,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_REALIZED_NET_PNL_USD_CONFLICT")

    stated_gross_pnl_usd, reason = consistent_economic_value(
        "REALIZED_GROSS_PNL_USD",
        (
            trust_row.get("realized_gross_pnl_usd"),
            trust_row.get("gross_realized_pnl_usd"),
            trust_row.get("realized_pnl_usd"),
            targets.get("realized_gross_pnl_usd"),
            targets.get("gross_realized_pnl_usd"),
            targets.get("realized_pnl_usd"),
        ),
    )
    if reason is not None:
        return blocked(reason)

    entry_price = _finite_float(trust_row.get("entry_price"))
    exit_price = _finite_float(trust_row.get("exit_price"))
    closed_quantity = _finite_float(trust_row.get("closed_quantity"))
    if entry_price is None or entry_price <= 0.0:
        return blocked("CONFIDENCE_TARGET_ENTRY_PRICE_MISSING_OR_INVALID")
    if exit_price is None or exit_price <= 0.0:
        return blocked("CONFIDENCE_TARGET_EXIT_PRICE_MISSING_OR_INVALID")
    if closed_quantity is None or closed_quantity <= 0.0:
        return blocked("CONFIDENCE_TARGET_CLOSED_QUANTITY_MISSING_OR_INVALID")
    recomputed_gross_pnl_usd = (
        (exit_price - entry_price) * closed_quantity
        if side == "long"
        else (entry_price - exit_price) * closed_quantity
    )
    assert stated_gross_pnl_usd is not None
    if not math.isclose(
        stated_gross_pnl_usd,
        recomputed_gross_pnl_usd,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_GROSS_PNL_PRICE_RECOMPUTATION_CONFLICT")

    row_close_notional_values = (
        trust_row.get("closed_entry_notional_usd"),
        trust_row.get("realized_pnl_notional_usd"),
    )
    target_close_notional_values = (
        targets.get("closed_entry_notional_usd"),
        targets.get("realized_pnl_notional_usd"),
    )
    close_specific_notional_present = any(
        value not in (None, "")
        for value in (*row_close_notional_values, *target_close_notional_values)
    )
    if close_specific_notional_present:
        row_pnl_notional_usd, reason = consistent_economic_value(
            "REALIZED_PNL_NOTIONAL_USD",
            row_close_notional_values,
        )
        if reason is not None:
            return blocked(reason)
        target_pnl_notional_usd, reason = consistent_economic_value(
            "REALIZED_PNL_NOTIONAL_USD",
            target_close_notional_values,
        )
        if reason is not None:
            return blocked(reason)
    else:
        # A legacy full-position notional is usable only when both the row and
        # its target envelope carry the same unambiguous value.  It is never
        # compared with a close-specific denominator: partial closes make those
        # quantities intentionally different.
        row_pnl_notional_usd, reason = consistent_economic_value(
            "REALIZED_PNL_NOTIONAL_USD",
            (
                trust_row.get("entry_notional_usd"),
                trust_row.get("gross_notional_usd"),
            ),
        )
        if reason is not None:
            return blocked(reason)
        target_pnl_notional_usd, reason = consistent_economic_value(
            "REALIZED_PNL_NOTIONAL_USD",
            (
                targets.get("entry_notional_usd"),
                targets.get("gross_notional_usd"),
            ),
        )
        if reason is not None:
            return blocked(reason)
    assert row_pnl_notional_usd is not None
    assert target_pnl_notional_usd is not None
    if not math.isclose(
        row_pnl_notional_usd,
        target_pnl_notional_usd,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_REALIZED_PNL_NOTIONAL_USD_CONFLICT")
    pnl_notional_usd = row_pnl_notional_usd
    gross_pnl_usd = recomputed_gross_pnl_usd
    assert pnl_notional_usd is not None
    if pnl_notional_usd <= 0.0:
        return blocked("CONFIDENCE_TARGET_REALIZED_PNL_NOTIONAL_USD_NOT_POSITIVE")
    recomputed_entry_notional_usd = entry_price * closed_quantity
    if not math.isclose(
        pnl_notional_usd,
        recomputed_entry_notional_usd,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_ENTRY_NOTIONAL_PRICE_RECOMPUTATION_CONFLICT")

    explicit_costs = {
        "fees": {
            "target_usd": (targets.get("fees_usd"),),
            "row_usd": (trust_row.get("fees_usd"),),
            "target_aliases": (targets.get("fees"),),
            "row_aliases": (trust_row.get("fees"),),
        },
        "slippage": {
            "target_usd": (targets.get("slippage_usd"),),
            "row_usd": (trust_row.get("slippage_usd"),),
            "target_aliases": (targets.get("slippage"),),
            "row_aliases": (trust_row.get("slippage"),),
        },
        "funding": {
            "target_usd": (
                targets.get("funding_pnl_usd"),
                targets.get("funding_usd"),
            ),
            "row_usd": (
                trust_row.get("funding_pnl_usd"),
                trust_row.get("funding_usd"),
            ),
            "target_aliases": (targets.get("funding"),),
            "row_aliases": (trust_row.get("funding"),),
        },
    }
    normalized_costs: dict[str, float] = {}
    for field_name, evidence in explicit_costs.items():
        target_usd_values = tuple(evidence["target_usd"])
        row_usd_values = tuple(evidence["row_usd"])
        target_value, reason = consistent_economic_value(
            f"EXPLICIT_{field_name.upper()}_USD",
            target_usd_values,
        )
        if reason is not None:
            return blocked(reason)
        row_value, reason = consistent_economic_value(
            f"EXPLICIT_{field_name.upper()}_USD",
            row_usd_values,
        )
        if reason is not None:
            return blocked(reason)
        assert target_value is not None and row_value is not None
        target_with_aliases, reason = consistent_economic_value(
            f"EXPLICIT_{field_name.upper()}_USD",
            (*target_usd_values, *tuple(evidence["target_aliases"])),
        )
        if reason is not None:
            return blocked(reason)
        row_with_aliases, reason = consistent_economic_value(
            f"EXPLICIT_{field_name.upper()}_USD",
            (*row_usd_values, *tuple(evidence["row_aliases"])),
        )
        if reason is not None:
            return blocked(reason)
        assert target_with_aliases is not None and row_with_aliases is not None
        if not math.isclose(
            target_with_aliases,
            row_with_aliases,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            return blocked(
                f"CONFIDENCE_TARGET_EXPLICIT_{field_name.upper()}_USD_CONFLICT"
            )
        if field_name in {"fees", "slippage"} and target_value < 0.0:
            return blocked(
                f"CONFIDENCE_TARGET_EXPLICIT_{field_name.upper()}_USD_NEGATIVE"
            )
        normalized_costs[field_name] = target_value

    exact_close_contract = {
        "paper_round_trip_cost_accounting_version": (
            "PAPER_ROUND_TRIP_CLOSE_COST_V1"
        ),
        "paper_cost_rate_scope": (
            "PER_SIDE_BPS_APPLIED_TO_CORRESPONDING_NOTIONAL"
        ),
        "paper_net_pnl_formula": (
            "realized_gross_pnl_usd - entry_fee_usd - exit_fee_usd - "
            "entry_slippage_usd - exit_slippage_usd + funding_pnl_usd"
        ),
        "round_trip_cost_provenance_status": (
            "COMPLETE_ENTRY_AND_EXIT_COST_PROVENANCE"
        ),
        "entry_cost_accounting_version": "PAPER_ENTRY_COST_BASIS_V1",
        "entry_cost_basis_status": (
            "COMPLETE_ENTRY_FEE_AND_SLIPPAGE_USD_BASIS"
        ),
        "exit_fee_rate_basis": (
            "ENTRY_BOUND_PER_SIDE_FEE_RATE_REUSED_FOR_PAPER_EXIT"
        ),
        "exit_slippage_provenance_status": (
            "EXIT_SPREAD_AVAILABLE_BY_CLOSE_TIME"
        ),
    }
    for field_name, expected_value in exact_close_contract.items():
        if trust_row.get(field_name) != expected_value:
            return blocked(
                f"CONFIDENCE_TARGET_{field_name.upper()}_INVALID"
            )
    for field_name in (
        "round_trip_cost_fallback_used",
        "entry_fee_fallback",
        "entry_slippage_fallback",
        "exit_fee_fallback",
        "exit_slippage_fallback",
    ):
        if trust_row.get(field_name) is not False:
            return blocked(f"CONFIDENCE_TARGET_{field_name.upper()}_NOT_FALSE")
    for field_name in (
        "entry_fee_source",
        "entry_slippage_source",
        "exit_fee_source",
        "exit_slippage_source",
    ):
        if not str(trust_row.get(field_name) or "").strip():
            return blocked(f"CONFIDENCE_TARGET_{field_name.upper()}_MISSING")

    component_names = (
        "entry_fee_usd",
        "exit_fee_usd",
        "total_fees_usd",
        "entry_slippage_usd",
        "exit_slippage_usd",
        "total_slippage_usd",
        "total_execution_costs_usd",
        "closed_exit_notional_usd",
        "entry_fee_bps_per_side",
        "exit_fee_bps_per_side",
        "entry_slippage_bps_per_side",
        "exit_slippage_bps_per_side",
    )
    components = {
        field_name: _finite_float(trust_row.get(field_name))
        for field_name in component_names
    }
    if any(value is None for value in components.values()):
        return blocked("CONFIDENCE_TARGET_EXACT_COST_COMPONENTS_MISSING")
    if any(float(value) < 0.0 for value in components.values() if value is not None):
        return blocked("CONFIDENCE_TARGET_EXACT_COST_COMPONENT_NEGATIVE")
    entry_fee_usd = float(components["entry_fee_usd"])
    exit_fee_usd = float(components["exit_fee_usd"])
    total_fees_usd = float(components["total_fees_usd"])
    entry_slippage_usd = float(components["entry_slippage_usd"])
    exit_slippage_usd = float(components["exit_slippage_usd"])
    total_slippage_usd = float(components["total_slippage_usd"])
    total_execution_costs_usd = float(components["total_execution_costs_usd"])
    closed_exit_notional_usd = float(components["closed_exit_notional_usd"])
    if not math.isclose(
        total_fees_usd,
        entry_fee_usd + exit_fee_usd,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ) or not math.isclose(
        total_fees_usd,
        normalized_costs["fees"],
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_FEE_COMPONENT_ARITHMETIC_CONFLICT")
    if not math.isclose(
        total_slippage_usd,
        entry_slippage_usd + exit_slippage_usd,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ) or not math.isclose(
        total_slippage_usd,
        normalized_costs["slippage"],
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_SLIPPAGE_COMPONENT_ARITHMETIC_CONFLICT")
    if not math.isclose(
        total_execution_costs_usd,
        total_fees_usd + total_slippage_usd,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_EXECUTION_COST_ARITHMETIC_CONFLICT")
    expected_exit_notional_usd = exit_price * closed_quantity
    if not math.isclose(
        closed_exit_notional_usd,
        expected_exit_notional_usd,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_EXIT_NOTIONAL_PRICE_RECOMPUTATION_CONFLICT")
    for rate_field, cost_usd, notional_usd in (
        ("entry_fee_bps_per_side", entry_fee_usd, pnl_notional_usd),
        ("exit_fee_bps_per_side", exit_fee_usd, closed_exit_notional_usd),
        (
            "entry_slippage_bps_per_side",
            entry_slippage_usd,
            pnl_notional_usd,
        ),
        (
            "exit_slippage_bps_per_side",
            exit_slippage_usd,
            closed_exit_notional_usd,
        ),
    ):
        observed_rate = float(components[rate_field])
        if not math.isclose(
            observed_rate,
            cost_usd / notional_usd * 10_000.0,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            return blocked("CONFIDENCE_TARGET_PER_SIDE_COST_RATE_ARITHMETIC_CONFLICT")
    exit_cost_available_at = _parse_utc(
        trust_row.get("exit_slippage_available_at")
    )
    if (
        exit_cost_available_at is None
        or exit_cost_available_at < resolved_decision_time
        or exit_cost_available_at > explicit_exit_time
    ):
        return blocked("CONFIDENCE_TARGET_EXIT_COST_CLOCK_ORDER_INVALID")

    recomputed_net_pnl_usd = (
        gross_pnl_usd
        - normalized_costs["fees"]
        - normalized_costs["slippage"]
        + normalized_costs["funding"]
    )
    if not math.isclose(
        target_net_pnl_usd,
        recomputed_net_pnl_usd,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_REALIZED_NET_PNL_USD_RECOMPUTATION_CONFLICT")
    recomputed_net_pnl_bps = recomputed_net_pnl_usd / pnl_notional_usd * 10_000.0
    if not math.isclose(
        target_net_pnl_bps,
        recomputed_net_pnl_bps,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_REALIZED_NET_PNL_BPS_RECOMPUTATION_CONFLICT")

    stated_gross_pnl_bps, reason = consistent_economic_value(
        "REALIZED_GROSS_PNL_BPS",
        (
            trust_row.get("realized_gross_pnl_bps"),
            trust_row.get("gross_realized_pnl_bps"),
            trust_row.get("realized_pnl_bps"),
            targets.get("realized_gross_pnl_bps"),
            targets.get("gross_realized_pnl_bps"),
            targets.get("realized_pnl_bps"),
        ),
        required=False,
    )
    if reason is not None:
        return blocked(reason)
    recomputed_gross_pnl_bps = gross_pnl_usd / pnl_notional_usd * 10_000.0
    if stated_gross_pnl_bps is not None and not math.isclose(
        stated_gross_pnl_bps,
        recomputed_gross_pnl_bps,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        return blocked("CONFIDENCE_TARGET_REALIZED_GROSS_PNL_BPS_RECOMPUTATION_CONFLICT")

    target = 1 if recomputed_net_pnl_usd > 0.0 else 0
    stated_profitable = _first_present(
        targets.get("action_was_profitable"),
        trust_row.get("action_was_profitable"),
    )
    if stated_profitable is not None and (
        not isinstance(stated_profitable, bool) or int(stated_profitable) != target
    ):
        return blocked("CONFIDENCE_TARGET_PROFITABILITY_LABEL_CONFLICT")
    trade_outcome = str(
        _first_present(targets.get("trade_outcome"), trust_row.get("trade_outcome"))
        or ""
    ).strip().upper()
    if trade_outcome:
        expected_outcome = "WIN" if target == 1 else (
            "BREAKEVEN" if recomputed_net_pnl_usd == 0.0 else "LOSS"
        )
        if trade_outcome != expected_outcome:
            return blocked("CONFIDENCE_TARGET_TRADE_OUTCOME_CONFLICT")

    row_id = str(
        _first_present(
            trust_row.get("trainer_feedback_id"),
            trust_row.get("decision_id"),
            trust_row.get("feature_snapshot_id"),
            trust_row.get("feature_vector_hash"),
        )
        or ""
    )
    if not row_id:
        return blocked("CONFIDENCE_TARGET_ROW_ID_MISSING")
    return {
        "eligible": True,
        "target": target,
        "reason": None,
        "selected_action": actions[0],
        "confidence_head_action_index": CONFIDENCE_HEAD_ACTION_INDEX[actions[0]],
        "realized_gross_pnl_usd": gross_pnl_usd,
        "realized_net_pnl_usd": recomputed_net_pnl_usd,
        "realized_net_pnl_bps": recomputed_net_pnl_bps,
        "realized_pnl_notional_usd": pnl_notional_usd,
        "explicit_costs": normalized_costs,
        "explicit_cost_units": "USD",
        "economics_formula": "gross_pnl_usd-fees_usd-slippage_usd+funding_pnl_usd",
        "decision_time": resolved_decision_time.isoformat().replace("+00:00", "Z"),
        "label_available_at": resolved_label_time.isoformat().replace("+00:00", "Z"),
        "row_id": row_id,
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
        "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
        "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
    }


def calibrate_confidence(
    *,
    raw_probability: float,
    data_coverage_percent: float,
    missing_feature_count: int,
    stale_feature_count: int,
    temperature: float | None = None,
    logit_scale: float | None = None,
    calibration_fitted: bool = False,
    calibration_reason: str | None = None,
    total_feature_count: int | None = None,
) -> dict[str, Any]:
    """Apply checkpoint-bound temperature scaling without changing semantics.

    Data-quality factors are exposed separately as a conservative admission
    score.  They no longer overwrite ``confidence_calibrated`` because doing so
    would turn a fitted probability into an undocumented heuristic.
    """
    raw = _finite_float(raw_probability)
    raw = max(0.0, min(1.0, raw)) if raw is not None else 0.0
    temperature_value = _finite_float(temperature)
    logit_scale_value = _finite_float(logit_scale)
    parameterization_valid = bool(
        (
            logit_scale is not None
            and temperature is None
            and logit_scale_value is not None
            and logit_scale_value >= 0.0
        )
        or (
            logit_scale is None
            and temperature_value is not None
            and temperature_value > 0.0
        )
    )
    fitted = bool(calibration_fitted and parameterization_valid)
    scaled = (
        _scaled_probability(
            raw,
            temperature=temperature_value if logit_scale is None else None,
            logit_scale=logit_scale_value if logit_scale is not None else None,
        )
        if fitted
        else UNFITTED_CONFIDENCE_VALUE
    )
    coverage = _finite_float(data_coverage_percent)
    coverage_factor = max(0.0, min(1.0, (coverage or 0.0) / 100.0))
    try:
        total = int(total_feature_count) if total_feature_count is not None else None
    except (TypeError, ValueError, OverflowError):
        total = None
    if total is not None and total > 0:
        missing_fraction = max(0.0, min(1.0, int(missing_feature_count) / total))
        stale_fraction = max(0.0, min(1.0, int(stale_feature_count) / total))
        missing_penalty = 1.0 - missing_fraction
        stale_penalty = 1.0 - stale_fraction
    else:
        missing_penalty = 0.0
        stale_penalty = 0.0
    quality_adjusted = (
        0.5
        + (scaled - 0.5)
        * coverage_factor
        * missing_penalty
        * stale_penalty
        if fitted
        else UNFITTED_CONFIDENCE_VALUE
    )
    resolved_temperature = (
        temperature_value
        if fitted and temperature_value is not None
        else (
            1.0 / logit_scale_value
            if fitted
            and logit_scale_value is not None
            and logit_scale_value > 0.0
            else None
        )
    )
    resolved_logit_scale = (
        logit_scale_value
        if fitted and logit_scale_value is not None
        else (
            1.0 / temperature_value
            if fitted and temperature_value is not None
            else None
        )
    )
    return {
        "confidence_raw": float(raw),
        "confidence_calibrated": float(scaled),
        "confidence_quality_adjusted_for_admission": float(
            max(0.0, min(1.0, quality_adjusted))
        ),
        "temperature": resolved_temperature,
        "logit_scale": resolved_logit_scale,
        "coverage_factor": float(coverage_factor),
        "missing_penalty": float(missing_penalty),
        "stale_penalty": float(stale_penalty),
        "used_calibration": fitted,
        "calibration_fitted": fitted,
        "calibration_reason": None
        if fitted
        else str(calibration_reason or "CHECKPOINT_CONFIDENCE_CALIBRATION_UNFITTED"),
        "calibration_source": (
            "checkpoint_bound_train_only_logit_scale_probability"
            if fitted
            else "unfitted_fail_closed"
        ),
        "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
        "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
        "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
        "probability_semantics_valid": fitted,
    }


def softmax(xs: list[float] | tuple[float, ...]) -> tuple[float, ...]:
    if not xs:
        return ()
    cleaned = [_finite_float(value) or 0.0 for value in xs]
    maximum = max(cleaned)
    exponentials = [
        math.exp(max(-700.0, min(700.0, value - maximum)))
        for value in cleaned
    ]
    total = sum(exponentials)
    if not math.isfinite(total) or total <= 0.0:
        return tuple(1.0 / len(xs) for _ in xs)
    return tuple(float(value / total) for value in exponentials)
