import pytest

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionDomainError
from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord


def _record(**overrides: object) -> TrainerPredictionRecord:
    values = {"prediction_id": "p", "feature_snapshot_id": "s", "symbol": "BTCUSDT", "model_version": "m", "checkpoint_id": "c", "prediction_ts_ms": 0, "direction": "long", "confidence_raw": 0.5, "confidence_calibrated": 0.5, "worker_id": "w", "worker_health_status": "HEALTHY", "freshness_flag": "fresh", "source_freshness_age_ms": 0, "top_positive_feature_codes": (), "top_negative_feature_codes": ()}
    values.update(overrides)
    return TrainerPredictionRecord(**values)


def test_record_invariants_feature_snapshot_id() -> None:
    cases = [("", "must_be_non_empty"), ("has space", "must_not_have_whitespace"), ("x" * 129, "must_be_at_most_128_chars")]
    for value, reason in cases:
        with pytest.raises(TrainerPredictionDomainError) as error:
            _record(feature_snapshot_id=value)
        assert (error.value.field, error.value.reason) == ("feature_snapshot_id", reason)
    with pytest.raises(TrainerPredictionDomainError) as error:
        _record(feature_snapshot_id=object())
    assert (error.value.field, error.value.reason) == ("feature_snapshot_id", "must_be_str")
    assert len(_record(feature_snapshot_id="x" * 128).feature_snapshot_id) == 128
