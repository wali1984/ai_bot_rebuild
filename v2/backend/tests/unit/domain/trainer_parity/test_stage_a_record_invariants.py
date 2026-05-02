"""StageATrainerRecord invariant tests."""

from __future__ import annotations

import dataclasses

import pytest

from v2.backend.app.domain.trainer_parity.errors import TrainerParityLineageError
from v2.backend.app.domain.trainer_parity.freshness_metadata import FreshnessMetadata
from v2.backend.app.domain.trainer_parity.stage_a_record import StageATrainerRecord


def test_valid_record_constructs(valid_stage_a_record: StageATrainerRecord) -> None:
    assert valid_stage_a_record.prediction_id == "pred-1"
    assert valid_stage_a_record.symbol == "BTCUSDT"


@pytest.mark.parametrize(
    "field",
    [
        "prediction_id",
        "feature_snapshot_id",
        "symbol",
        "model_version",
        "checkpoint_id",
        "worker_id",
        "worker_health_status",
    ],
)
def test_empty_string_fields_raise(
    valid_stage_a_record: StageATrainerRecord, field: str
) -> None:
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(valid_stage_a_record, **{field: ""})


def test_negative_prediction_ts_ms_raises(
    valid_stage_a_record: StageATrainerRecord,
) -> None:
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(valid_stage_a_record, prediction_ts_ms=-1)


@pytest.mark.parametrize("value", [-0.0001, 1.0001])
def test_confidence_raw_out_of_bounds_raises(
    valid_stage_a_record: StageATrainerRecord, value: float
) -> None:
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(valid_stage_a_record, confidence_raw=value)


@pytest.mark.parametrize("value", [-0.0001, 1.0001])
def test_confidence_calibrated_out_of_bounds_raises(
    valid_stage_a_record: StageATrainerRecord, value: float
) -> None:
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(valid_stage_a_record, confidence_calibrated=value)


def test_duplicate_top_positive_features_raises(
    valid_stage_a_record: StageATrainerRecord,
) -> None:
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(valid_stage_a_record, top_positive_features=("a", "a"))


def test_duplicate_top_negative_features_raises(
    valid_stage_a_record: StageATrainerRecord,
) -> None:
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(valid_stage_a_record, top_negative_features=("a", "a"))


def test_duplicate_source_key_references_raises(
    valid_stage_a_record: StageATrainerRecord,
) -> None:
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(valid_stage_a_record, source_key_references=("a", "a"))


def test_record_is_frozen(valid_stage_a_record: StageATrainerRecord) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        valid_stage_a_record.prediction_id = "changed"  # type: ignore[misc]


def test_freshness_metadata_field_wired(
    valid_stage_a_record: StageATrainerRecord,
    valid_freshness_metadata: FreshnessMetadata,
) -> None:
    assert valid_stage_a_record.freshness_metadata is valid_freshness_metadata
