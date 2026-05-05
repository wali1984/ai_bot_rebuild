from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord
from v2.backend.app.services.orchestrator_decision import (
    assemble_orchestrator_decision_record,
)


def test_assemble_propagates_input_lineage_fields() -> None:
    record = assemble_orchestrator_decision_record(
        prediction=TrainerPredictionRecord(
            prediction_id="pred_lineage_xyz",
            feature_snapshot_id="snap_lineage_xyz",
            symbol="ETHUSDT",
            model_version="model",
            checkpoint_id="checkpoint",
            prediction_ts_ms=1,
            direction="long",
            confidence_raw=0.85,
            confidence_calibrated=0.85,
            worker_id="worker",
            worker_health_status="HEALTHY",
            freshness_flag="fresh",
            source_freshness_age_ms=1,
            top_positive_feature_codes=("pos",),
            top_negative_feature_codes=("neg",),
        ),
        low_confidence_threshold=0.5,
        now_ms_clock=lambda: 1000,
    )

    assert record.prediction_id == "pred_lineage_xyz"
    assert record.feature_snapshot_id == "snap_lineage_xyz"
    assert record.symbol == "ETHUSDT"
    assert record.input_prediction_direction == "long"
    assert record.input_prediction_confidence_calibrated == 0.85
    assert record.input_prediction_freshness_flag == "fresh"
    assert record.input_worker_health_status == "HEALTHY"
    assert record.live_blocked is True
