"""Checkpoint-bound profitability confidence calibration tests."""
from __future__ import annotations

import math
from typing import Any

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR,
    CONFIDENCE_CALIBRATION_SCHEMA_VERSION,
    CONFIDENCE_FIT_PARTITION,
    CONFIDENCE_LABEL_SEMANTICS,
    expected_calibration_error,
    fit_temperature,
    logit_scaled_probability,
    normalize_calibration_state,
    paired_confidence_nonregression_evidence,
    resolve_confidence_logit_scale,
    resolve_confidence_temperature,
)


def _overconfident_dataset(n: int = 400) -> tuple[list[float], list[int]]:
    raw, outcomes = [], []
    for index in range(n):
        raw.append(0.9)
        outcomes.append(1 if index % 20 < 11 else 0)
    return raw, outcomes


def _fit_with_lineage(
    raw: list[float],
    outcomes: list[int],
    **kwargs: Any,
) -> dict[str, Any]:
    return fit_temperature(
        raw,
        outcomes,
        row_ids=[f"row_{index}" for index in range(len(raw))],
        action_labels=[
            "long" if index % 2 == 0 else "short"
            for index in range(len(raw))
        ],
        **kwargs,
    )


def test_fit_temperature_spreads_overconfident_probabilities() -> None:
    raw, outcomes = _overconfident_dataset()
    fit = _fit_with_lineage(raw, outcomes)
    assert fit["fitted"] is True
    assert fit["temperature"] > 1.0
    assert fit["temperature"] > 6.0
    assert fit["logit_scale"] == 1.0 / fit["temperature"]
    assert fit["calibration_error_estimator"] == (
        CONFIDENCE_CALIBRATION_ERROR_ESTIMATOR
    )
    assert (
        math.nextafter(
            fit["temperature_fit_lower_logit_scale"],
            fit["temperature_fit_upper_logit_scale"],
        )
        == fit["temperature_fit_upper_logit_scale"]
    )
    assert fit["ece_after"] <= fit["ece_before"] + 1e-9
    assert fit["brier_after"] <= fit["brier_before"] + 1e-9
    assert fit["label_semantics"] == CONFIDENCE_LABEL_SEMANTICS
    assert fit["fit_partition"] == CONFIDENCE_FIT_PARTITION
    assert fit["validation_rows_used"] == 0

    reversed_fit = fit_temperature(
        list(reversed(raw)),
        list(reversed(outcomes)),
        row_ids=[f"reversed_{index}" for index in range(len(raw))],
        action_labels=[
            "short" if index % 2 == 0 else "long"
            for index in range(len(raw))
        ],
    )
    assert reversed_fit["logit_scale"] == fit["logit_scale"]
    assert reversed_fit["temperature_fit_lower_logit_scale"] == (
        fit["temperature_fit_lower_logit_scale"]
    )
    assert reversed_fit["temperature_fit_upper_logit_scale"] == (
        fit["temperature_fit_upper_logit_scale"]
    )


def test_fit_temperature_requires_both_profitability_classes_not_static_min_n() -> None:
    fit = _fit_with_lineage([0.9] * 10, [1] * 10)
    assert fit["fitted"] is False
    assert fit["reason"] == "CALIBRATION_CLASS_VARIATION_MISSING"
    assert fit["temperature"] is None

    two_rows = fit_temperature(
        [0.8, 0.2],
        [1, 0],
        row_ids=["win", "loss"],
        action_labels=["long", "short"],
    )
    assert two_rows["fitted"] is False
    assert two_rows["reason"] == (
        "CALIBRATION_FINITE_INTERIOR_TEMPERATURE_NOT_IDENTIFIABLE"
    )


def test_zero_logit_scale_boundary_is_represented_without_fake_temperature() -> None:
    fit = fit_temperature(
        [0.9, 0.1],
        [0, 1],
        row_ids=["loss", "win"],
        action_labels=["long", "short"],
    )
    assert fit["fitted"] is True
    assert fit["temperature"] is None
    assert fit["logit_scale"] == 0.0
    assert fit["temperature_fit_lower_logit_scale"] == 0.0
    assert fit["temperature_fit_upper_logit_scale"] == 0.0

    bound = {**fit, "model_parameter_fingerprint": "f" * 64}
    assert resolve_confidence_logit_scale(bound) == 0.0
    assert resolve_confidence_temperature(bound) is None


def test_bin_free_error_detects_ordered_anti_calibration() -> None:
    error = expected_calibration_error([0.1, 0.9], [1, 0])
    assert math.isclose(error, 0.45)

    with pytest.raises(ValueError, match="input_length_mismatch"):
        expected_calibration_error([0.1, 0.9], [1])


def test_all_half_probabilities_are_not_fit_identifiable() -> None:
    fit = fit_temperature(
        [0.5, 0.5, 0.5, 0.5],
        [1, 0, 1, 0],
        row_ids=["half-0", "half-1", "half-2", "half-3"],
        action_labels=["long", "short", "long", "short"],
    )
    assert fit["fitted"] is False
    assert fit["reason"] == (
        "CALIBRATION_FINITE_INTERIOR_TEMPERATURE_NOT_IDENTIFIABLE"
    )


def test_endpoint_opening_is_symmetric() -> None:
    lower = logit_scaled_probability(0.0, 1.0)
    upper = logit_scaled_probability(1.0, 1.0)
    assert lower > 0.0
    assert upper < 1.0
    assert abs(lower - (1.0 - upper)) <= math.ulp(1.0)


def test_nonregression_uses_full_and_every_delete_one_not_one_se_threshold() -> None:
    evidence = paired_confidence_nonregression_evidence(
        [0.9, 0.8, 0.7, 0.6],
        [0, 0, 1, 1],
        logit_scale=0.0,
        scope="GLOBAL",
    )
    assert evidence["paired_brier_delta_one_standard_error_upper_bound"] > 0.0
    assert evidence["paired_brier_non_regression_proven"] is True
    assert evidence["ece_non_regression_proven"] is True


def test_forward_validation_rows_are_rejected_from_fitting_api() -> None:
    fit = fit_temperature(
        [0.8, 0.2],
        [1, 0],
        row_ids=["win", "loss"],
        action_labels=["long", "short"],
        validation_rows_used=1,
    )
    assert fit["fitted"] is False
    assert fit["reason"] == "CALIBRATION_FORWARD_VALIDATION_LEAKAGE_BLOCKED"


def test_calibration_counts_reject_fractional_or_boolean_evidence() -> None:
    raw, outcomes = _overconfident_dataset()
    fit = _fit_with_lineage(raw, outcomes)
    fractional = normalize_calibration_state({**fit, "sample": 2.5})
    assert fractional["fitted"] is False
    assert fractional["reason"] == "CHECKPOINT_CALIBRATION_COUNTS_INVALID"

    boolean_validation_count = fit_temperature(
        [0.8, 0.2],
        [1, 0],
        row_ids=["win", "loss"],
        action_labels=["long", "short"],
        validation_rows_used=False,
    )
    assert boolean_validation_count["fitted"] is False
    assert boolean_validation_count["reason"] == (
        "CALIBRATION_VALIDATION_ROW_COUNT_INVALID"
    )


def test_length_mismatch_fails_closed_instead_of_zip_truncation() -> None:
    fit = fit_temperature(
        [0.8, 0.2],
        [1],
        row_ids=["win", "loss"],
        action_labels=["long", "short"],
    )
    assert fit["fitted"] is False
    assert fit["reason"] == "CALIBRATION_INPUT_LENGTH_MISMATCH"


def test_ece_is_lower_after_fitted_temperature() -> None:
    raw, outcomes = _overconfident_dataset()
    fit = _fit_with_lineage(raw, outcomes)
    assert expected_calibration_error(raw, outcomes, fit["temperature"]) <= (
        expected_calibration_error(raw, outcomes, 1.0) + 1e-9
    )


def test_temperature_resolver_accepts_only_valid_checkpoint_state(monkeypatch) -> None:
    raw, outcomes = _overconfident_dataset()
    fit = _fit_with_lineage(raw, outcomes)
    assert resolve_confidence_temperature(fit) is None
    structurally_bound = {
        **fit,
        "model_parameter_fingerprint": "f" * 64,
    }
    assert resolve_confidence_temperature(structurally_bound) == fit["temperature"]

    monkeypatch.setenv("V2_TRAINER_CONFIDENCE_TEMPERATURE", "1.9")
    assert resolve_confidence_temperature(None) is None
    assert resolve_confidence_temperature({"fitted": True, "temperature": 1.9}) is None


def test_calibration_fit_requires_directional_action_lineage() -> None:
    missing_actions = fit_temperature(
        [0.8, 0.2],
        [1, 0],
        row_ids=["win", "loss"],
    )
    assert missing_actions["fitted"] is False
    assert missing_actions["reason"] == (
        "CALIBRATION_ACTION_LABELS_MISSING_OR_LENGTH_MISMATCH"
    )

    one_direction = fit_temperature(
        [0.8, 0.2],
        [1, 0],
        row_ids=["win", "loss"],
        action_labels=["long", "long"],
    )
    assert one_direction["fitted"] is False
    assert one_direction["reason"] == (
        "CALIBRATION_DIRECTIONAL_ACTION_COVERAGE_MISSING"
    )


def test_legacy_claimed_net_sign_calibration_state_is_invalidated() -> None:
    raw, outcomes = _overconfident_dataset()
    fit = _fit_with_lineage(raw, outcomes)
    assert fit["schema_version"] == CONFIDENCE_CALIBRATION_SCHEMA_VERSION
    assert fit["label_semantics"] == CONFIDENCE_LABEL_SEMANTICS

    legacy = {
        **fit,
        "label_semantics": (
            "P_SELECTED_DIRECTIONAL_ACTION_REALIZED_NET_PNL_"
            "AFTER_EXPLICIT_COSTS_GT_ZERO_V1"
        ),
        "model_parameter_fingerprint": "f" * 64,
    }
    normalized = normalize_calibration_state(legacy)

    assert normalized["fitted"] is False
    assert normalized["reason"] == "CHECKPOINT_CALIBRATION_LABEL_SEMANTICS_INVALID"
