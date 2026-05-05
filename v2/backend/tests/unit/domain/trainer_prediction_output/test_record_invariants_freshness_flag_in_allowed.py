import pytest

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionDomainError
from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord


def _record(**overrides: object) -> TrainerPredictionRecord:
    values = {"prediction_id": "p", "feature_snapshot_id": "s", "symbol": "BTCUSDT", "model_version": "m", "checkpoint_id": "c", "prediction_ts_ms": 0, "direction": "long", "confidence_raw": 0.5, "confidence_calibrated": 0.5, "worker_id": "w", "worker_health_status": "HEALTHY", "freshness_flag": "fresh", "source_freshness_age_ms": 0, "top_positive_feature_codes": (), "top_negative_feature_codes": ()}
    values.update(overrides)
    return TrainerPredictionRecord(**values)


def test_record_invariants_freshness_flag_in_allowed() -> None:
    assert _record(freshness_flag="fresh", source_freshness_age_ms=0).freshness_flag == "fresh"
    assert _record(freshness_flag="stale", source_freshness_age_ms=1).freshness_flag == "stale"
    assert _record(freshness_flag="missing", source_freshness_age_ms=None).freshness_flag == "missing"
    with pytest.raises(TrainerPredictionDomainError) as error:
        _record(freshness_flag="old")
    assert (error.value.field, error.value.reason) == ("freshness_flag", "invalid_freshness_flag")
    with pytest.raises(TrainerPredictionDomainError) as error:
        _record(freshness_flag=1)
    assert (error.value.field, error.value.reason) == ("freshness_flag", "must_be_str")
