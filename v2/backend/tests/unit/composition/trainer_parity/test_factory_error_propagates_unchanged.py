import pytest

from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.composition.trainer_parity.runtime import (
    build_trainer_liveness_evaluator,
)
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs


def test_factory_error_propagates_unchanged(monkeypatch):
    def fake_factory(*args, **kwargs):
        raise RedisStreamReaderError("must_be_set", field="V2_REDIS_URL")

    monkeypatch.setattr(
        "v2.backend.app.composition.trainer_parity.runtime.make_real_redis_stream_latest_id_reader",
        fake_factory,
    )
    base_inputs = LivenessSnapshotBaseInputs(None, None, None, None, False, None, None, None, None, False, 1)

    with pytest.raises(RedisStreamReaderError) as raised:
        build_trainer_liveness_evaluator(
            base_inputs=base_inputs,
            growth_config=GrowthWindowConfig(window_ms=1),
            now_ms_clock=lambda: 1,
            prediction_stream_name="trainer:predictions",
            proposal_stream_name="trainer:proposals",
            max_history_per_stream=1,
        )

    assert raised.value.code == "must_be_set"
    assert raised.value.field == "V2_REDIS_URL"
