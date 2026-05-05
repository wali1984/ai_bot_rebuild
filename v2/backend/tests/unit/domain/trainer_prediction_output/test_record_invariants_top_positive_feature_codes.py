import pytest

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionDomainError
from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord


def _record(**overrides: object) -> TrainerPredictionRecord:
    values = {"prediction_id": "p", "feature_snapshot_id": "s", "symbol": "BTCUSDT", "model_version": "m", "checkpoint_id": "c", "prediction_ts_ms": 0, "direction": "long", "confidence_raw": 0.5, "confidence_calibrated": 0.5, "worker_id": "w", "worker_health_status": "HEALTHY", "freshness_flag": "fresh", "source_freshness_age_ms": 0, "top_positive_feature_codes": (), "top_negative_feature_codes": ()}
    values.update(overrides)
    return TrainerPredictionRecord(**values)


def test_record_invariants_top_positive_feature_codes() -> None:
    for value in (["a"], {"a"}, {"a": 1}):
        with pytest.raises(TrainerPredictionDomainError) as error:
            _record(top_positive_feature_codes=value)
        assert (error.value.field, error.value.reason) == ("top_positive_feature_codes", "must_be_tuple")
    cases = [((1,), "must_be_str"), (("",), "must_be_non_empty"), (("has space",), "must_not_have_whitespace"), (("x" * 65,), "must_be_at_most_64_chars"), (tuple(str(i) for i in range(9)), "must_be_at_most_8_entries"), (("dup", "dup"), "must_be_unique")]
    for value, reason in cases:
        with pytest.raises(TrainerPredictionDomainError) as error:
            _record(top_positive_feature_codes=value)
        assert (error.value.field, error.value.reason) == ("top_positive_feature_codes", reason)
    assert _record(top_positive_feature_codes=()).top_positive_feature_codes == ()
