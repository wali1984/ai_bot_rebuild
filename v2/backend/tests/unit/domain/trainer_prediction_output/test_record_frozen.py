from dataclasses import FrozenInstanceError

import pytest

from v2.backend.app.domain.trainer_prediction_output import TrainerPredictionRecord


def test_record_frozen() -> None:
    record_a = TrainerPredictionRecord("p", "s", "BTCUSDT", "m", "c", 0, "long", 0.5, 0.5, "w", "HEALTHY", "fresh", 0, (), ())
    record_b = TrainerPredictionRecord("p", "s", "BTCUSDT", "m", "c", 0, "long", 0.5, 0.5, "w", "HEALTHY", "fresh", 0, (), ())

    with pytest.raises(FrozenInstanceError):
        record_a.symbol = "ETHUSDT"
    assert hash(record_a) == hash(record_b)
