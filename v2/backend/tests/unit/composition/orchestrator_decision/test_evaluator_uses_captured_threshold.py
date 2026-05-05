def test_evaluator_uses_captured_threshold() -> None:
    from v2.backend.app.composition.orchestrator_decision import (
        build_orchestrator_decision_evaluator,
    )
    from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord

    prediction = TrainerPredictionRecord(
        prediction_id="pred_1",
        feature_snapshot_id="feat_1",
        symbol="BTCUSDT",
        model_version="model_1",
        checkpoint_id="checkpoint_1",
        prediction_ts_ms=1,
        direction="long",
        confidence_raw=0.8,
        confidence_calibrated=0.65,
        worker_id="worker_1",
        worker_health_status="HEALTHY",
        freshness_flag="fresh",
        source_freshness_age_ms=12,
        top_positive_feature_codes=("pos_1",),
        top_negative_feature_codes=("neg_1",),
    )

    high_threshold = build_orchestrator_decision_evaluator(
        low_confidence_threshold=0.7, now_ms_clock=lambda: 123
    )
    low_threshold = build_orchestrator_decision_evaluator(
        low_confidence_threshold=0.5, now_ms_clock=lambda: 123
    )

    high_result = high_threshold(prediction=prediction)
    low_result = low_threshold(prediction=prediction)

    assert high_result.decision_action == "abstain"
    assert high_result.decision_reason_code == "abstain_low_confidence"
    assert low_result.decision_action == "open_long"
    assert low_result.decision_reason_code == "proceed_long"
