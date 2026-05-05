def test_evaluator_returns_trainer_prediction_record() -> None:
    from v2.backend.app.composition.trainer_prediction_output import (
        build_trainer_prediction_output_evaluator,
    )
    from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord

    evaluator = build_trainer_prediction_output_evaluator(now_ms_clock=lambda: 123)
    result = evaluator(
        prediction_id="pred_1",
        feature_snapshot_id="feat_1",
        symbol="BTCUSDT",
        model_version="model_1",
        checkpoint_id="checkpoint_1",
        direction="short",
        confidence_raw=0.4,
        confidence_calibrated=0.5,
        worker_id="worker_1",
        worker_health_status="HEALTHY",
        freshness_flag="fresh",
        source_freshness_age_ms=12,
        top_positive_feature_codes=("pos_1",),
        top_negative_feature_codes=("neg_1",),
    )

    assert isinstance(result, TrainerPredictionRecord)
