from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord
from v2.backend.app.services.orchestrator_decision import (
    assemble_orchestrator_decision_record,
)


def test_assemble_abstain_worker_unknown() -> None:
    record = assemble_orchestrator_decision_record(
        prediction=TrainerPredictionRecord(
            prediction_id="pred_worker_unknown",
            feature_snapshot_id="snap_worker_unknown",
            symbol="BTCUSDT",
            model_version="model",
            checkpoint_id="checkpoint",
            prediction_ts_ms=1,
            direction="long",
            confidence_raw=0.9,
            confidence_calibrated=0.9,
            worker_id="worker",
            worker_health_status="UNKNOWN",
            freshness_flag="fresh",
            source_freshness_age_ms=1,
            top_positive_feature_codes=("pos",),
            top_negative_feature_codes=("neg",),
        ),
        low_confidence_threshold=0.5,
        now_ms_clock=lambda: 1000,
    )

    assert record.decision_action == "abstain"
    assert record.decision_reason_code == "abstain_worker_unknown"
