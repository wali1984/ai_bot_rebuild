import pytest


def test_evaluator_keyword_only_params() -> None:
    from v2.backend.app.composition.orchestrator_decision import (
        build_orchestrator_decision_evaluator,
    )
    from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord

    evaluator = build_orchestrator_decision_evaluator(
        low_confidence_threshold=0.5, now_ms_clock=lambda: 123
    )
    prediction = TrainerPredictionRecord(
        prediction_id="pred_1",
        feature_snapshot_id="feat_1",
        symbol="BTCUSDT",
        model_version="model_1",
        checkpoint_id="checkpoint_1",
        prediction_ts_ms=1,
        direction="flat",
        confidence_raw=0.8,
        confidence_calibrated=0.7,
        worker_id="worker_1",
        worker_health_status="HEALTHY",
        freshness_flag="fresh",
        source_freshness_age_ms=12,
        top_positive_feature_codes=("pos_1",),
        top_negative_feature_codes=("neg_1",),
    )

    with pytest.raises(TypeError):
        evaluator(prediction)
