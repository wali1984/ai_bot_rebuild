"""validate_stage_b_lineage tests."""

from __future__ import annotations

import dataclasses
from typing import Callable

import pytest

from v2.backend.app.domain.trainer_parity.errors import TrainerParityLineageError
from v2.backend.app.domain.trainer_parity.lineage_validator import (
    validate_stage_b_lineage,
)
from v2.backend.app.domain.trainer_parity.stage_a_record import StageATrainerRecord
from v2.backend.app.domain.trainer_parity.stage_b_record import StageBTrainerRecord


StageBBuilder = Callable[[StageATrainerRecord], StageBTrainerRecord]


def test_matching_pair_passes(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    validate_stage_b_lineage(record, valid_stage_a_record)


def test_mismatched_prediction_id_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    bad = dataclasses.replace(record, prediction_id="other-pred")
    with pytest.raises(TrainerParityLineageError) as exc:
        validate_stage_b_lineage(bad, valid_stage_a_record)
    assert exc.value.reason == "prediction_id"


def test_mismatched_feature_snapshot_id_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    bad = dataclasses.replace(record, feature_snapshot_id="other-snap")
    with pytest.raises(TrainerParityLineageError) as exc:
        validate_stage_b_lineage(bad, valid_stage_a_record)
    assert exc.value.reason == "feature_snapshot_id"


def test_mismatched_symbol_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    bad = dataclasses.replace(record, symbol="ETHUSDT")
    with pytest.raises(TrainerParityLineageError) as exc:
        validate_stage_b_lineage(bad, valid_stage_a_record)
    assert exc.value.reason == "symbol"


def test_signal_ts_before_prediction_ts_raises(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    bad = dataclasses.replace(
        record, signal_ts_ms=valid_stage_a_record.prediction_ts_ms - 1
    )
    with pytest.raises(TrainerParityLineageError) as exc:
        validate_stage_b_lineage(bad, valid_stage_a_record)
    assert exc.value.reason == "signal_ts_ms_before_prediction_ts_ms"


def test_signal_ts_equal_prediction_ts_passes(
    valid_stage_a_record: StageATrainerRecord,
    valid_stage_b_record: StageBBuilder,
) -> None:
    record = valid_stage_b_record(valid_stage_a_record)
    equal = dataclasses.replace(
        record, signal_ts_ms=valid_stage_a_record.prediction_ts_ms
    )
    validate_stage_b_lineage(equal, valid_stage_a_record)
