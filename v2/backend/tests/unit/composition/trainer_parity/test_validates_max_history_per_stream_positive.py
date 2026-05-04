import pytest

from v2.backend.app.composition.trainer_parity.errors import TrainerParityCompositionError
from v2.backend.app.composition.trainer_parity.runtime import (
    build_trainer_liveness_evaluator,
)
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs


def test_validates_max_history_per_stream_positive(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "v2.backend.app.composition.trainer_parity.runtime.make_real_redis_stream_latest_id_reader",
        lambda *args, **kwargs: calls.append(None),
    )
    base_inputs = LivenessSnapshotBaseInputs(None, None, None, None, False, None, None, None, None, False, 1)
    growth_config = GrowthWindowConfig(window_ms=1)

    with pytest.raises(TrainerParityCompositionError) as raised_zero:
        build_trainer_liveness_evaluator(
            base_inputs=base_inputs,
            growth_config=growth_config,
            now_ms_clock=lambda: 1,
            prediction_stream_name="trainer:predictions",
            proposal_stream_name="trainer:proposals",
            max_history_per_stream=0,
        )
    with pytest.raises(TrainerParityCompositionError) as raised_negative:
        build_trainer_liveness_evaluator(
            base_inputs=base_inputs,
            growth_config=growth_config,
            now_ms_clock=lambda: 1,
            prediction_stream_name="trainer:predictions",
            proposal_stream_name="trainer:proposals",
            max_history_per_stream=-1,
        )

    assert raised_zero.value.code == "must_be_positive"
    assert raised_zero.value.field == "max_history_per_stream"
    assert raised_negative.value.code == "must_be_positive"
    assert raised_negative.value.field == "max_history_per_stream"
    assert calls == []
