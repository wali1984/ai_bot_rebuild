import pytest

from v2.backend.app.composition.trainer_parity.errors import TrainerParityCompositionError
from v2.backend.app.composition.trainer_parity.runtime import (
    build_trainer_liveness_evaluator,
)
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs


def test_validates_prediction_stream_name_nonempty_str(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "v2.backend.app.composition.trainer_parity.runtime.make_real_redis_stream_latest_id_reader",
        lambda *args, **kwargs: calls.append(None),
    )
    base_inputs = LivenessSnapshotBaseInputs(None, None, None, None, False, None, None, None, None, False, 1)
    growth_config = GrowthWindowConfig(window_ms=1)

    with pytest.raises(TrainerParityCompositionError) as raised_type:
        build_trainer_liveness_evaluator(
            base_inputs=base_inputs,
            growth_config=growth_config,
            now_ms_clock=lambda: 1,
            prediction_stream_name=42,
            proposal_stream_name="trainer:proposals",
            max_history_per_stream=1,
        )
    with pytest.raises(TrainerParityCompositionError) as raised_empty:
        build_trainer_liveness_evaluator(
            base_inputs=base_inputs,
            growth_config=growth_config,
            now_ms_clock=lambda: 1,
            prediction_stream_name="",
            proposal_stream_name="trainer:proposals",
            max_history_per_stream=1,
        )

    assert raised_type.value.code == "must_be_nonempty_str"
    assert raised_type.value.field == "prediction_stream_name"
    assert raised_empty.value.code == "must_be_nonempty_str"
    assert raised_empty.value.field == "prediction_stream_name"
    assert calls == []
