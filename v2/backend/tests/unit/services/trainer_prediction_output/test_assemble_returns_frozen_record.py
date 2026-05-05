import dataclasses

import pytest

from v2.backend.app.services.trainer_prediction_output import assemble_prediction_record


def test_assemble_returns_frozen_record() -> None:
    record = assemble_prediction_record(
        prediction_id="pred-1",
        feature_snapshot_id="snapshot-1",
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
        top_positive_feature_codes=("alpha",),
        top_negative_feature_codes=("beta",),
        now_ms_clock=lambda: 1,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(record, "prediction_id", "changed")
