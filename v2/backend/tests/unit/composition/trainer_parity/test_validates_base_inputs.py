import pytest

from v2.backend.app.composition.trainer_parity.errors import TrainerParityCompositionError
from v2.backend.app.composition.trainer_parity.runtime import (
    build_trainer_liveness_evaluator,
)
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig


def test_validates_base_inputs(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "v2.backend.app.composition.trainer_parity.runtime.make_real_redis_stream_latest_id_reader",
        lambda *args, **kwargs: calls.append(None),
    )

    with pytest.raises(TrainerParityCompositionError) as raised:
        build_trainer_liveness_evaluator(
            base_inputs=object(),
            growth_config=GrowthWindowConfig(window_ms=1),
            now_ms_clock=lambda: 1,
            prediction_stream_name="trainer:predictions",
            proposal_stream_name="trainer:proposals",
            max_history_per_stream=1,
        )

    assert raised.value.code == "must_be_liveness_snapshot_base_inputs"
    assert raised.value.field == "base_inputs"
    assert calls == []
