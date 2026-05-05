from v2.backend.app.services.trainer_prediction_output import assemble_prediction_record


def test_assemble_happy_path_long() -> None:
    record = assemble_prediction_record(
        prediction_id="pred-long-1",
        feature_snapshot_id="snapshot-long-1",
        symbol="BTCUSDT",
        model_version="model-v1",
        checkpoint_id="checkpoint-1",
        direction="long",
        confidence_raw=0.7,
        confidence_calibrated=0.65,
        worker_id="worker-1",
        worker_health_status="HEALTHY",
        freshness_flag="fresh",
        source_freshness_age_ms=250,
        top_positive_feature_codes=("alpha", "bravo"),
        top_negative_feature_codes=("charlie",),
        now_ms_clock=lambda: 1_700_000_000_123,
    )

    assert record.prediction_id == "pred-long-1"
    assert record.feature_snapshot_id == "snapshot-long-1"
    assert record.symbol == "BTCUSDT"
    assert record.model_version == "model-v1"
    assert record.checkpoint_id == "checkpoint-1"
    assert record.prediction_ts_ms == 1_700_000_000_123
    assert record.direction == "long"
    assert record.confidence_raw == 0.7
    assert record.confidence_calibrated == 0.65
    assert record.worker_id == "worker-1"
    assert record.worker_health_status == "HEALTHY"
    assert record.freshness_flag == "fresh"
    assert record.source_freshness_age_ms == 250
    assert record.top_positive_feature_codes == ("alpha", "bravo")
    assert record.top_negative_feature_codes == ("charlie",)
