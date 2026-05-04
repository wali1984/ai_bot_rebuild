from v2.backend.app.composition.trainer_parity.runtime import (
    build_trainer_liveness_evaluator,
)
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs


def test_calls_factory_with_both_kwargs(monkeypatch):
    calls = []
    env = {"V2_REDIS_URL": "redis://env:6379/0"}

    class FakeReader:
        def latest_stream_id(self, stream_name):
            return None

    def fake_factory(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeReader()

    monkeypatch.setattr(
        "v2.backend.app.composition.trainer_parity.runtime.make_real_redis_stream_latest_id_reader",
        fake_factory,
    )
    base_inputs = LivenessSnapshotBaseInputs(None, None, None, None, False, None, None, None, None, False, 1)
    growth_config = GrowthWindowConfig(window_ms=1)

    build_trainer_liveness_evaluator(
        base_inputs=base_inputs,
        growth_config=growth_config,
        now_ms_clock=lambda: 1,
        prediction_stream_name="trainer:predictions",
        proposal_stream_name="trainer:proposals",
        max_history_per_stream=1,
        env=env,
        url="redis://h:6379/0",
    )

    assert calls == [((), {"url": "redis://h:6379/0", "env": env})]
