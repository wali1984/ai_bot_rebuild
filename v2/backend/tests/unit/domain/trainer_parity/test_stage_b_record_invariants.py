"""StageBTrainerRecord invariant tests."""

from __future__ import annotations

import dataclasses
from typing import Callable

import pytest

from v2.backend.app.domain.trainer_parity.errors import TrainerParityLineageError
from v2.backend.app.domain.trainer_parity.stage_a_record import StageATrainerRecord
from v2.backend.app.domain.trainer_parity.stage_b_record import StageBTrainerRecord


StageBBuilder = Callable[[StageATrainerRecord], StageBTrainerRecord]


def test_valid_record_constructs(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    assert record.signal_id == "sig-1"
    assert record.action == "buy"


@pytest.mark.parametrize(
    "field",
    [
        "signal_id",
        "prediction_id",
        "feature_snapshot_id",
        "symbol",
        "action",
        "action_type",
    ],
)
def test_empty_string_fields_raise(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
    field: str,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(record, **{field: ""})


@pytest.mark.parametrize("value", [-0.0001, 1.0001])
def test_confidence_out_of_bounds_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
    value: float,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(record, confidence=value)


def test_negative_signal_ts_ms_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(record, signal_ts_ms=-1)


def test_action_outside_allowed_set_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(record, action="not-an-action")


def test_action_type_outside_allowed_set_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    with pytest.raises(TrainerParityLineageError):
        dataclasses.replace(record, action_type="not-an-action-type")


def test_record_is_frozen(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.signal_id = "changed"  # type: ignore[misc]
