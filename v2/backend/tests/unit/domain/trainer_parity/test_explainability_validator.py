"""validate_stage_a_explainability tests."""

from __future__ import annotations

import dataclasses

import pytest

from v2.backend.app.domain.trainer_parity.errors import TrainerParityLineageError
from v2.backend.app.domain.trainer_parity.explainability_validator import (
    validate_stage_a_explainability,
)
from v2.backend.app.domain.trainer_parity.stage_a_record import (
    ConfidenceExplainability,
    StageATrainerRecord,
)


def _explain_via_object_new(
    *,
    confidence_components: tuple[tuple[str, float], ...],
    confidence_floor_applied: bool,
    confidence_ceiling_applied: bool,
    calibration_model_version: str,
    calibration_method: str,
) -> ConfidenceExplainability:
    obj = object.__new__(ConfidenceExplainability)
    object.__setattr__(obj, "confidence_components", confidence_components)
    object.__setattr__(obj, "confidence_floor_applied", confidence_floor_applied)
    object.__setattr__(obj, "confidence_ceiling_applied", confidence_ceiling_applied)
    object.__setattr__(obj, "calibration_model_version", calibration_model_version)
    object.__setattr__(obj, "calibration_method", calibration_method)
    return obj


def test_valid_record_passes(valid_stage_a_record: StageATrainerRecord) -> None:
    validate_stage_a_explainability(valid_stage_a_record)


def test_empty_components_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_confidence_explainability: ConfidenceExplainability,
) -> None:
    bad = _explain_via_object_new(
        confidence_components=(),
        confidence_floor_applied=valid_confidence_explainability.confidence_floor_applied,
        confidence_ceiling_applied=valid_confidence_explainability.confidence_ceiling_applied,
        calibration_model_version=valid_confidence_explainability.calibration_model_version,
        calibration_method=valid_confidence_explainability.calibration_method,
    )
    bad_record = dataclasses.replace(valid_stage_a_record, confidence_explainability=bad)
    with pytest.raises(TrainerParityLineageError):
        validate_stage_a_explainability(bad_record)


def test_duplicate_component_name_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_confidence_explainability: ConfidenceExplainability,
) -> None:
    bad = dataclasses.replace(
        valid_confidence_explainability,
        confidence_components=(("dup", 0.1), ("dup", 0.2)),
    )
    bad_record = dataclasses.replace(valid_stage_a_record, confidence_explainability=bad)
    with pytest.raises(TrainerParityLineageError):
        validate_stage_a_explainability(bad_record)


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf")])
def test_non_finite_contribution_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_confidence_explainability: ConfidenceExplainability,
    bad_value: float,
) -> None:
    bad = _explain_via_object_new(
        confidence_components=(("c", bad_value),),
        confidence_floor_applied=valid_confidence_explainability.confidence_floor_applied,
        confidence_ceiling_applied=valid_confidence_explainability.confidence_ceiling_applied,
        calibration_model_version=valid_confidence_explainability.calibration_model_version,
        calibration_method=valid_confidence_explainability.calibration_method,
    )
    bad_record = dataclasses.replace(valid_stage_a_record, confidence_explainability=bad)
    with pytest.raises(TrainerParityLineageError):
        validate_stage_a_explainability(bad_record)


def test_empty_calibration_model_version_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_confidence_explainability: ConfidenceExplainability,
) -> None:
    bad = dataclasses.replace(
        valid_confidence_explainability, calibration_model_version=""
    )
    bad_record = dataclasses.replace(valid_stage_a_record, confidence_explainability=bad)
    with pytest.raises(TrainerParityLineageError):
        validate_stage_a_explainability(bad_record)


def test_empty_calibration_method_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_confidence_explainability: ConfidenceExplainability,
) -> None:
    bad = dataclasses.replace(valid_confidence_explainability, calibration_method="")
    bad_record = dataclasses.replace(valid_stage_a_record, confidence_explainability=bad)
    with pytest.raises(TrainerParityLineageError):
        validate_stage_a_explainability(bad_record)


def test_both_top_features_empty_raises(
    valid_stage_a_record: StageATrainerRecord,
) -> None:
    bad_record = dataclasses.replace(
        valid_stage_a_record,
        top_positive_features=(),
        top_negative_features=(),
    )
    with pytest.raises(TrainerParityLineageError):
        validate_stage_a_explainability(bad_record)


def test_empty_source_key_references_raises(
    valid_stage_a_record: StageATrainerRecord,
) -> None:
    bad_record = dataclasses.replace(valid_stage_a_record, source_key_references=())
    with pytest.raises(TrainerParityLineageError):
        validate_stage_a_explainability(bad_record)


def test_freshness_metadata_smoke_check(
    valid_stage_a_record: StageATrainerRecord,
) -> None:
    validate_stage_a_explainability(valid_stage_a_record)
