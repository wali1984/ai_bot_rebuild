import pytest

from v2.backend.app.services.trainer_prediction_output import (
    TrainerPredictionOutputServiceError,
    assemble_prediction_record,
)


def test_assemble_rejects_clock_returning_non_int() -> None:
    class Stub:
        pass

    for value in ("42", 42.0, Stub(), True):
        with pytest.raises(TrainerPredictionOutputServiceError) as exc_info:
            assemble_prediction_record(
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
                now_ms_clock=lambda value=value: value,
            )

        assert exc_info.value.code == "must_be_int"
        assert exc_info.value.field == "now_ms_clock"
