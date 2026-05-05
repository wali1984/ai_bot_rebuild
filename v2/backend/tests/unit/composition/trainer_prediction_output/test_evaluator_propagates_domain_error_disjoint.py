import pytest


def test_evaluator_propagates_domain_error_disjoint() -> None:
    from v2.backend.app.composition.trainer_prediction_output import (
        build_trainer_prediction_output_evaluator,
    )
    from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionDomainError

    evaluator = build_trainer_prediction_output_evaluator(now_ms_clock=lambda: 123)

    with pytest.raises(TrainerPredictionDomainError) as exc_info:
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
            top_positive_feature_codes=("a", "b"),
            top_negative_feature_codes=("b", "c"),
        )

    assert exc_info.value.reason == "must_be_disjoint_from_top_positive"
    assert exc_info.value.field == "top_negative_feature_codes"
