from v2.backend.app.composition.trainer_parity.runtime import (
    build_trainer_liveness_evaluator,
)
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs


def test_factory_not_called_again_by_evaluator(monkeypatch):
    calls = []

    class FakeReader:
        def latest_stream_id(self, stream_name):
            return None

    def fake_factory(*args, **kwargs):
        calls.append(None)
        return FakeReader()

    monkeypatch.setattr(
        "v2.backend.app.composition.trainer_parity.runtime.make_real_redis_stream_latest_id_reader",
        fake_factory,
    )
    monkeypatch.setattr(
        "v2.backend.app.composition.trainer_parity.runtime.evaluate_trainer_liveness",
        lambda *args, **kwargs: object(),
    )
    base_inputs = LivenessSnapshotBaseInputs(None, None, None, None, False, None, None, None, None, False, 1)
    growth_config = GrowthWindowConfig(window_ms=1)
    evaluator = build_trainer_liveness_evaluator(
        base_inputs=base_inputs,
        growth_config=growth_config,
        now_ms_clock=lambda: 1,
        prediction_stream_name="trainer:predictions",
        proposal_stream_name="trainer:proposals",
        max_history_per_stream=1,
    )

    evaluator((), ())

    assert len(calls) == 1
