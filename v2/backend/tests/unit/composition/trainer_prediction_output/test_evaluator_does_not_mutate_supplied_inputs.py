def test_evaluator_does_not_mutate_supplied_inputs() -> None:
    from v2.backend.app.composition.trainer_prediction_output import (
        build_trainer_prediction_output_evaluator,
    )

    prediction_id = "pred_1"
    positive = ("pos_1", "pos_2")
    negative = ("neg_1", "neg_2")
    before_prediction_id = prediction_id[:]
    before_positive = tuple(positive)
    before_negative = tuple(negative)

    evaluator = build_trainer_prediction_output_evaluator(now_ms_clock=lambda: 123)
    evaluator(
        prediction_id=prediction_id,
        feature_snapshot_id="feat_1",
        symbol="BTCUSDT",
        model_version="model_1",
        checkpoint_id="checkpoint_1",
        direction="long",
        confidence_raw=0.7,
        confidence_calibrated=0.6,
        worker_id="worker_1",
        worker_health_status="HEALTHY",
        freshness_flag="fresh",
        source_freshness_age_ms=12,
        top_positive_feature_codes=positive,
        top_negative_feature_codes=negative,
    )

    assert prediction_id == before_prediction_id
    assert positive == before_positive
    assert negative == before_negative
