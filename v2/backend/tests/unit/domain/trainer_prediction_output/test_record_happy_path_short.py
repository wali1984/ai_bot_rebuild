from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord


def test_record_happy_path_short() -> None:
    record = TrainerPredictionRecord(
        "pred-2", "snap-2", "ETHUSDT", "model-2", "ckpt-2", 124, "short",
        0.2, 0.25, "worker-2", "DEGRADED", "stale", 999, ("p3",), ("n3", "n4")
    )

    assert record.prediction_id == "pred-2"
    assert record.symbol == "ETHUSDT"
    assert record.direction == "short"
    assert record.worker_health_status == "DEGRADED"
    assert record.source_freshness_age_ms == 999
