from v2.backend.app.services.trainer_prediction_output import assemble_prediction_record


def test_assemble_happy_path_short() -> None:
    record = assemble_prediction_record(
        prediction_id="pred-short-1",
        feature_snapshot_id="snapshot-short-1",
        symbol="ETHUSDT",
        model_version="model-v2",
        checkpoint_id="checkpoint-2",
        direction="short",
        confidence_raw=0.4,
        confidence_calibrated=0.42,
        worker_id="worker-2",
        worker_health_status="DEGRADED",
        freshness_flag="stale",
        source_freshness_age_ms=9_000,
        top_positive_feature_codes=("delta",),
        top_negative_feature_codes=("echo", "foxtrot"),
        now_ms_clock=lambda: 1_700_000_000_456,
    )

    assert record.prediction_id == "pred-short-1"
    assert record.feature_snapshot_id == "snapshot-short-1"
    assert record.symbol == "ETHUSDT"
    assert record.model_version == "model-v2"
    assert record.checkpoint_id == "checkpoint-2"
    assert record.prediction_ts_ms == 1_700_000_000_456
    assert record.direction == "short"
    assert record.confidence_raw == 0.4
    assert record.confidence_calibrated == 0.42
    assert record.worker_id == "worker-2"
    assert record.worker_health_status == "DEGRADED"
    assert record.freshness_flag == "stale"
    assert record.source_freshness_age_ms == 9_000
    assert record.top_positive_feature_codes == ("delta",)
    assert record.top_negative_feature_codes == ("echo", "foxtrot")
