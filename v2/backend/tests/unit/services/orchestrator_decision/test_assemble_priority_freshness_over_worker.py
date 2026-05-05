from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord
from v2.backend.app.services.orchestrator_decision import (
    assemble_orchestrator_decision_record,
)


def test_assemble_priority_freshness_over_worker() -> None:
    record = assemble_orchestrator_decision_record(
        prediction=TrainerPredictionRecord(
            prediction_id="pred_priority_freshness",
            feature_snapshot_id="snap_priority_freshness",
            symbol="BTCUSDT",
            model_version="model",
            checkpoint_id="checkpoint",
            prediction_ts_ms=1,
            direction="long",
            confidence_raw=0.9,
            confidence_calibrated=0.9,
            worker_id="worker",
            worker_health_status="CRITICAL",
            freshness_flag="stale",
            source_freshness_age_ms=1_000_000,
            top_positive_feature_codes=("pos",),
            top_negative_feature_codes=("neg",),
        ),
        low_confidence_threshold=0.5,
        now_ms_clock=lambda: 1000,
    )

    assert record.decision_reason_code == "abstain_freshness_stale"
