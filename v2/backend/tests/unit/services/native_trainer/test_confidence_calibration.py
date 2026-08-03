"""Checkpoint-bound profitability confidence calibration tests."""
from __future__ import annotations

from typing import Any

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_CALIBRATION_SCHEMA_VERSION,
    CONFIDENCE_FIT_PARTITION,
    CONFIDENCE_LABEL_SEMANTICS,
    expected_calibration_error,
    fit_temperature,
    normalize_calibration_state,
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
    assert fit["ece_after"] <= fit["ece_before"] + 1e-9
    assert fit["brier_after"] <= fit["brier_before"] + 1e-9
    assert fit["label_semantics"] == CONFIDENCE_LABEL_SEMANTICS
    assert fit["fit_partition"] == CONFIDENCE_FIT_PARTITION
    assert fit["validation_rows_used"] == 0


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
    assert two_rows["fitted"] is True
    assert two_rows["sample"] == 2


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
    fit = _fit_with_lineage([0.8, 0.2], [1, 0])
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
    fit = fit_temperature(
        [0.8, 0.2],
        [1, 0],
        row_ids=["win", "loss"],
        action_labels=["long", "short"],
    )
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
    fit = fit_temperature(
        [0.8, 0.2],
        [1, 0],
        row_ids=["win", "loss"],
        action_labels=["long", "short"],
    )
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
