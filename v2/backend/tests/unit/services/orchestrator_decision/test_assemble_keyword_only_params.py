import pytest

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord
from v2.backend.app.services.orchestrator_decision import (
    assemble_orchestrator_decision_record,
)


def test_assemble_keyword_only_params() -> None:
    prediction = TrainerPredictionRecord(
        prediction_id="pred_keyword",
        feature_snapshot_id="snap_keyword",
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
    )

    with pytest.raises(TypeError):
        assemble_orchestrator_decision_record(prediction, 0.5, lambda: 1)
    assert assemble_orchestrator_decision_record(
        prediction=prediction,
        low_confidence_threshold=0.5,
        now_ms_clock=lambda: 1,
    ).decision_id == "dec_pred_keyword"
