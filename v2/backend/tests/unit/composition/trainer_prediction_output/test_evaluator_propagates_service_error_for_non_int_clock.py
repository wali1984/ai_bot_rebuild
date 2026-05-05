import pytest


def test_evaluator_propagates_service_error_for_non_int_clock() -> None:
    from v2.backend.app.composition.trainer_prediction_output import (
        build_trainer_prediction_output_evaluator,
    )
    from v2.backend.app.services.trainer_prediction_output import (
        TrainerPredictionOutputServiceError,
    )

    evaluator = build_trainer_prediction_output_evaluator(now_ms_clock=lambda: 1.5)

    with pytest.raises(TrainerPredictionOutputServiceError) as exc_info:
        evaluator(
            prediction_id="pred_1",
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
            top_positive_feature_codes=("pos_1",),
            top_negative_feature_codes=("neg_1",),
        )

    assert exc_info.value.code == "must_be_int"
    assert exc_info.value.field == "now_ms_clock"
