from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord
from v2.backend.app.services.orchestrator_decision import (
    assemble_orchestrator_decision_record,
)


def test_assemble_calls_clock_exactly_once() -> None:
    calls = []

    def clock() -> int:
        calls.append("called")
        return 1 if len(calls) == 1 else 999

    record = assemble_orchestrator_decision_record(
        prediction=TrainerPredictionRecord(
            prediction_id="pred_clock_once",
            feature_snapshot_id="snap_clock_once",
            symbol="BTCUSDT",
            model_version="model",
            checkpoint_id="checkpoint",
            prediction_ts_ms=1,
            direction="long",
            confidence_raw=0.9,
            confidence_calibrated=0.9,
            worker_id="worker",
            worker_health_status="HEALTHY",
            freshness_flag="fresh",
            source_freshness_age_ms=1,
            top_positive_feature_codes=("pos",),
            top_negative_feature_codes=("neg",),
        ),
        low_confidence_threshold=0.5,
        now_ms_clock=clock,
    )

    assert len(calls) == 1
    assert record.decision_ts_ms == 1
