from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord


def test_record_happy_path_long() -> None:
    record = TrainerPredictionRecord(
        "pred-1", "snap-1", "BTCUSDT", "model-1", "ckpt-1", 123, "long",
        0.8, 0.75, "worker-1", "HEALTHY", "fresh", 10, ("p1", "p2"), ("n1",)
    )

    assert record.prediction_id == "pred-1"
    assert record.feature_snapshot_id == "snap-1"
    assert record.symbol == "BTCUSDT"
    assert record.direction == "long"
    assert record.top_positive_feature_codes == ("p1", "p2")
