import pytest

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionDomainError
from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord


def _record(**overrides: object) -> TrainerPredictionRecord:
    values = {
        "prediction_id": "pred-1",
        "feature_snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "model_version": "model-1",
        "checkpoint_id": "ckpt-1",
        "prediction_ts_ms": 1,
        "direction": "long",
        "confidence_raw": 0.7,
        "confidence_calibrated": 0.6,
        "worker_id": "worker-1",
        "worker_health_status": "HEALTHY",
        "freshness_flag": "fresh",
        "source_freshness_age_ms": 0,
        "top_positive_feature_codes": ("p1",),
        "top_negative_feature_codes": ("n1",),
    }
    values.update(overrides)
    return TrainerPredictionRecord(**values)


def test_record_invariants_prediction_id_non_empty() -> None:
    for value in ("", "   "):
        with pytest.raises(TrainerPredictionDomainError) as error:
            _record(prediction_id=value)
        assert error.value.field == "prediction_id"
        assert error.value.reason in {"must_be_non_empty", "must_not_have_whitespace"}
    assert _record(prediction_id="pred-ok").prediction_id == "pred-ok"
