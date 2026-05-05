def test_evaluator_returns_assembler_result_unchanged() -> None:
    from v2.backend.app.composition.trainer_prediction_output import (
        build_trainer_prediction_output_evaluator,
    )

    kwargs = {
        "prediction_id": "pred_1",
        "feature_snapshot_id": "feat_1",
        "symbol": "BTCUSDT",
        "model_version": "model_1",
        "checkpoint_id": "checkpoint_1",
        "direction": "flat",
        "confidence_raw": 0.4,
        "confidence_calibrated": 0.5,
        "worker_id": "worker_1",
        "worker_health_status": "DEGRADED",
        "freshness_flag": "missing",
        "source_freshness_age_ms": None,
        "top_positive_feature_codes": ("pos_1",),
        "top_negative_feature_codes": ("neg_1",),
    }
    evaluator = build_trainer_prediction_output_evaluator(now_ms_clock=lambda: 456)
    result = evaluator(**kwargs)

    for name, value in kwargs.items():
        assert getattr(result, name) == value
    assert result.prediction_ts_ms == 456
