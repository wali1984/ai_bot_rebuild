import pytest

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionDomainError
from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord


def _record(**overrides: object) -> TrainerPredictionRecord:
    values = {"prediction_id": "p", "feature_snapshot_id": "s", "symbol": "BTCUSDT", "model_version": "m", "checkpoint_id": "c", "prediction_ts_ms": 0, "direction": "long", "confidence_raw": 0.5, "confidence_calibrated": 0.5, "worker_id": "w", "worker_health_status": "HEALTHY", "freshness_flag": "fresh", "source_freshness_age_ms": 0, "top_positive_feature_codes": (), "top_negative_feature_codes": ()}
    values.update(overrides)
    return TrainerPredictionRecord(**values)


def test_record_invariants_freshness_missing_requires_none_age() -> None:
    with pytest.raises(TrainerPredictionDomainError) as error:
        _record(freshness_flag="missing", source_freshness_age_ms=0)
    assert (error.value.field, error.value.reason) == ("source_freshness_age_ms", "missing_requires_none_age")
    assert _record(freshness_flag="missing", source_freshness_age_ms=None).source_freshness_age_ms is None
