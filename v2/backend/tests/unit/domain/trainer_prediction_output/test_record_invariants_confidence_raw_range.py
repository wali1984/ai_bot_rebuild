import math

import pytest

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionDomainError
from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord


def _record(**overrides: object) -> TrainerPredictionRecord:
    values = {"prediction_id": "p", "feature_snapshot_id": "s", "symbol": "BTCUSDT", "model_version": "m", "checkpoint_id": "c", "prediction_ts_ms": 0, "direction": "long", "confidence_raw": 0.5, "confidence_calibrated": 0.5, "worker_id": "w", "worker_health_status": "HEALTHY", "freshness_flag": "fresh", "source_freshness_age_ms": 0, "top_positive_feature_codes": (), "top_negative_feature_codes": ()}
    values.update(overrides)
    return TrainerPredictionRecord(**values)


def test_record_invariants_confidence_raw_range() -> None:
    for value, reason in ((-0.1, "must_be_in_unit_interval"), (1.1, "must_be_in_unit_interval"), (math.nan, "must_be_finite"), (math.inf, "must_be_finite"), (-math.inf, "must_be_finite")):
        with pytest.raises(TrainerPredictionDomainError) as error:
            _record(confidence_raw=value)
        assert (error.value.field, error.value.reason) == ("confidence_raw", reason)
    assert _record(confidence_raw=0.0).confidence_raw == 0.0
    assert _record(confidence_raw=0.5).confidence_raw == 0.5
    assert _record(confidence_raw=1.0).confidence_raw == 1.0
