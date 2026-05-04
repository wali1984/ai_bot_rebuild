from v2.backend.app.composition.trainer_parity.runtime import (
    build_trainer_liveness_evaluator,
)
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs


def test_evaluator_forwards_static_config_to_service(monkeypatch):
    captured = {}

    class FakeReader:
        def latest_stream_id(self, stream_name):
            return None

    def fake_service(first_arg, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        "v2.backend.app.composition.trainer_parity.runtime.make_real_redis_stream_latest_id_reader",
        lambda *args, **kwargs: FakeReader(),
    )
    monkeypatch.setattr(
        "v2.backend.app.composition.trainer_parity.runtime.evaluate_trainer_liveness",
        fake_service,
    )
    base_inputs = LivenessSnapshotBaseInputs(None, None, None, None, True, None, None, None, None, False, 7)
    growth_config = GrowthWindowConfig(window_ms=9, boundary_inclusive=True)
    now_ms_clock = lambda: 11

    evaluator = build_trainer_liveness_evaluator(
        base_inputs=base_inputs,
        growth_config=growth_config,
        now_ms_clock=now_ms_clock,
        prediction_stream_name="trainer:predictions",
        proposal_stream_name="trainer:proposals",
        max_history_per_stream=3,
    )
    evaluator((), ())

    assert captured["base_inputs"] is base_inputs
    assert captured["growth_config"] is growth_config
    assert captured["now_ms_clock"] is now_ms_clock
    assert captured["prediction_stream_name"] == "trainer:predictions"
    assert captured["proposal_stream_name"] == "trainer:proposals"
    assert captured["max_history_per_stream"] == 3
