from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord


def test_record_happy_path_flat() -> None:
    record = TrainerPredictionRecord(
        "pred-3", "snap-3", "SOLUSDT", "model-3", "ckpt-3", 125, "flat",
        0.0, 0.0, "worker-3", "UNKNOWN", "missing", None, (), ()
    )

    assert record.direction == "flat"
    assert record.confidence_raw == 0.0
    assert record.confidence_calibrated == 0.0
    assert record.source_freshness_age_ms is None
    assert record.top_negative_feature_codes == ()
