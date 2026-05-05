import pytest

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionDomainError
from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord


def _record(**overrides: object) -> TrainerPredictionRecord:
    values = {"prediction_id": "p", "feature_snapshot_id": "s", "symbol": "BTCUSDT", "model_version": "m", "checkpoint_id": "c", "prediction_ts_ms": 0, "direction": "long", "confidence_raw": 0.5, "confidence_calibrated": 0.5, "worker_id": "w", "worker_health_status": "HEALTHY", "freshness_flag": "fresh", "source_freshness_age_ms": 0, "top_positive_feature_codes": (), "top_negative_feature_codes": ()}
    values.update(overrides)
    return TrainerPredictionRecord(**values)


def test_record_invariants_worker_health_status_in_allowed() -> None:
    for status in ("HEALTHY", "DEGRADED", "CRITICAL", "UNKNOWN"):
        assert _record(worker_health_status=status).worker_health_status == status
    for status in ("BAD", "healthy"):
        with pytest.raises(TrainerPredictionDomainError) as error:
            _record(worker_health_status=status)
        assert (error.value.field, error.value.reason) == ("worker_health_status", "invalid_worker_health_status")
    with pytest.raises(TrainerPredictionDomainError) as error:
        _record(worker_health_status=1)
    assert (error.value.field, error.value.reason) == ("worker_health_status", "must_be_str")
