def test_evaluator_does_not_mutate_supplied_inputs() -> None:
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
    original = prediction
    snapshot = (
        prediction.prediction_id,
        prediction.feature_snapshot_id,
        prediction.symbol,
        prediction.model_version,
        prediction.checkpoint_id,
        prediction.prediction_ts_ms,
        prediction.direction,
        prediction.confidence_raw,
        prediction.confidence_calibrated,
        prediction.worker_id,
        prediction.worker_health_status,
        prediction.freshness_flag,
        prediction.source_freshness_age_ms,
        prediction.top_positive_feature_codes,
        prediction.top_negative_feature_codes,
    )

    evaluator(prediction=prediction)

    assert prediction is original
    assert snapshot == (
        prediction.prediction_id,
        prediction.feature_snapshot_id,
        prediction.symbol,
        prediction.model_version,
        prediction.checkpoint_id,
        prediction.prediction_ts_ms,
        prediction.direction,
        prediction.confidence_raw,
        prediction.confidence_calibrated,
        prediction.worker_id,
        prediction.worker_health_status,
        prediction.freshness_flag,
        prediction.source_freshness_age_ms,
        prediction.top_positive_feature_codes,
        prediction.top_negative_feature_codes,
    )
