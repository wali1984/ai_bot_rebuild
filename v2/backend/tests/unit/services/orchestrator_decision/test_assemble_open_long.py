from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord
from v2.backend.app.services.orchestrator_decision import (
    assemble_orchestrator_decision_record,
)


def test_assemble_open_long() -> None:
    prediction = TrainerPredictionRecord(
        prediction_id="pred_open_long",
        feature_snapshot_id="snap_open_long",
        symbol="BTCUSDT",
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
    )

    record = assemble_orchestrator_decision_record(
        prediction=prediction,
        low_confidence_threshold=0.5,
        now_ms_clock=lambda: 1000,
    )

    assert record.decision_action == "open_long"
    assert record.decision_reason_code == "proceed_long"
    assert record.decision_ts_ms == 1000
    assert record.decision_id == "dec_pred_open_long"
    assert record.live_blocked is True
    assert record.input_prediction_direction == prediction.direction
    assert record.input_prediction_confidence_calibrated == prediction.confidence_calibrated
