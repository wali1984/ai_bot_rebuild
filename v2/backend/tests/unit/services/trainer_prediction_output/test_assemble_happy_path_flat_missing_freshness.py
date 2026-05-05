from v2.backend.app.services.trainer_prediction_output import assemble_prediction_record


def test_assemble_happy_path_flat_missing_freshness() -> None:
    record = assemble_prediction_record(
        prediction_id="pred-flat-1",
        feature_snapshot_id="snapshot-flat-1",
        symbol="SOLUSDT",
        model_version="model-v3",
        checkpoint_id="checkpoint-3",
        direction="flat",
        confidence_raw=0.0,
        confidence_calibrated=0.0,
        worker_id="worker-3",
        worker_health_status="UNKNOWN",
        freshness_flag="missing",
        source_freshness_age_ms=None,
        top_positive_feature_codes=(),
        top_negative_feature_codes=(),
        now_ms_clock=lambda: 1_700_000_000_789,
    )

    assert record.prediction_id == "pred-flat-1"
    assert record.feature_snapshot_id == "snapshot-flat-1"
    assert record.symbol == "SOLUSDT"
    assert record.model_version == "model-v3"
    assert record.checkpoint_id == "checkpoint-3"
    assert record.prediction_ts_ms == 1_700_000_000_789
    assert record.direction == "flat"
    assert record.confidence_raw == 0.0
    assert record.confidence_calibrated == 0.0
    assert record.worker_id == "worker-3"
    assert record.worker_health_status == "UNKNOWN"
    assert record.freshness_flag == "missing"
    assert record.source_freshness_age_ms is None
    assert record.top_positive_feature_codes == ()
    assert record.top_negative_feature_codes == ()
