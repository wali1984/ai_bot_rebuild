from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord
from v2.backend.app.services.orchestrator_decision import (
    assemble_orchestrator_decision_record,
)


def test_assemble_at_threshold_is_not_low_confidence() -> None:
    record = assemble_orchestrator_decision_record(
        prediction=TrainerPredictionRecord(
            prediction_id="pred_at_threshold",
            feature_snapshot_id="snap_at_threshold",
            symbol="BTCUSDT",
            model_version="model",
            checkpoint_id="checkpoint",
            prediction_ts_ms=1,
            direction="long",
            confidence_raw=0.5,
            confidence_calibrated=0.5,
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

    assert record.decision_action == "open_long"
    assert record.decision_reason_code == "proceed_long"
