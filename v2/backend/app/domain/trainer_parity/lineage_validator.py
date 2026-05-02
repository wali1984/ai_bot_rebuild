"""Pure-function lineage validators binding Stage B -> Stage A -> snapshot -> symbol.

These functions perform no I/O and import no legacy modules. They are the
defense-in-depth layer behind dataclass `__post_init__` invariants and the
single source of structured-reason strings for downstream observability.
"""

from __future__ import annotations

from .errors import TrainerParityLineageError
from .stage_a_record import StageATrainerRecord
from .stage_b_record import StageBTrainerRecord


def validate_stage_a_lineage(record: StageATrainerRecord) -> None:
    """Defense-in-depth validation of Stage A lineage fields."""
    if not record.prediction_id:
        raise TrainerParityLineageError("prediction_id", field="prediction_id")
    if not record.feature_snapshot_id:
        raise TrainerParityLineageError(
            "feature_snapshot_id", field="feature_snapshot_id"
        )
    if not record.symbol:
        raise TrainerParityLineageError("symbol", field="symbol")


def validate_stage_b_lineage(
    stage_b: StageBTrainerRecord, stage_a: StageATrainerRecord
) -> None:
    """Confirm Stage B record is derived from the supplied Stage A record."""
    if stage_b.prediction_id != stage_a.prediction_id:
        raise TrainerParityLineageError("prediction_id", field="prediction_id")
    if stage_b.feature_snapshot_id != stage_a.feature_snapshot_id:
        raise TrainerParityLineageError(
            "feature_snapshot_id", field="feature_snapshot_id"
        )
    if stage_b.symbol != stage_a.symbol:
        raise TrainerParityLineageError("symbol", field="symbol")
    if stage_b.signal_ts_ms < stage_a.prediction_ts_ms:
        raise TrainerParityLineageError(
            "signal_ts_ms_before_prediction_ts_ms", field="signal_ts_ms"
        )
