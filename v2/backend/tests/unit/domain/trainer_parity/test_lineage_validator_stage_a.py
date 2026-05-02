"""validate_stage_a_lineage tests including defense-in-depth via object.__new__."""

from __future__ import annotations

import pytest

from v2.backend.app.domain.trainer_parity.errors import TrainerParityLineageError
from v2.backend.app.domain.trainer_parity.lineage_validator import (
    validate_stage_a_lineage,
)
from v2.backend.app.domain.trainer_parity.stage_a_record import StageATrainerRecord


def _record_with_blanked_field(
    base: StageATrainerRecord, target_field: str
) -> StageATrainerRecord:
    blank = object.__new__(StageATrainerRecord)
    for slot in StageATrainerRecord.__slots__:
        value = "" if slot == target_field else getattr(base, slot)
        object.__setattr__(blank, slot, value)
    return blank


def test_valid_record_passes(valid_stage_a_record: StageATrainerRecord) -> None:
    validate_stage_a_lineage(valid_stage_a_record)


def test_blank_prediction_id_raises(valid_stage_a_record: StageATrainerRecord) -> None:
    blanked = _record_with_blanked_field(valid_stage_a_record, "prediction_id")
    with pytest.raises(TrainerParityLineageError) as exc:
        validate_stage_a_lineage(blanked)
    assert exc.value.reason == "prediction_id"


def test_blank_feature_snapshot_id_raises(
    valid_stage_a_record: StageATrainerRecord,
) -> None:
    blanked = _record_with_blanked_field(valid_stage_a_record, "feature_snapshot_id")
    with pytest.raises(TrainerParityLineageError) as exc:
        validate_stage_a_lineage(blanked)
    assert exc.value.reason == "feature_snapshot_id"


def test_blank_symbol_raises(valid_stage_a_record: StageATrainerRecord) -> None:
    blanked = _record_with_blanked_field(valid_stage_a_record, "symbol")
    with pytest.raises(TrainerParityLineageError) as exc:
        validate_stage_a_lineage(blanked)
    assert exc.value.reason == "symbol"
