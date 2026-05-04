from v2.backend.app.composition.trainer_parity.runtime import (
    build_trainer_liveness_evaluator,
)
from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig, StreamIdObservation
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs


def test_evaluator_does_not_mutate_supplied_histories(monkeypatch):
    class FakeReader:
        def latest_stream_id(self, stream_name):
            return None

    monkeypatch.setattr(
        "v2.backend.app.composition.trainer_parity.runtime.make_real_redis_stream_latest_id_reader",
        lambda *args, **kwargs: FakeReader(),
    )
    monkeypatch.setattr(
        "v2.backend.app.composition.trainer_parity.runtime.evaluate_trainer_liveness",
        lambda *args, **kwargs: object(),
    )
    base_inputs = LivenessSnapshotBaseInputs(None, None, None, None, False, None, None, None, None, False, 1)
    growth_config = GrowthWindowConfig(window_ms=1)
    pred_history = (StreamIdObservation("trainer:predictions", "1-0", 1),)
    prop_history = (StreamIdObservation("trainer:proposals", "2-0", 1),)
    before_pred = tuple(pred_history)
    before_prop = tuple(prop_history)
    pred_id = id(pred_history)
    prop_id = id(prop_history)
    pred_element_ids = tuple(id(item) for item in pred_history)
    prop_element_ids = tuple(id(item) for item in prop_history)

    evaluator = build_trainer_liveness_evaluator(
        base_inputs=base_inputs,
        growth_config=growth_config,
        now_ms_clock=lambda: 1,
        prediction_stream_name="trainer:predictions",
        proposal_stream_name="trainer:proposals",
        max_history_per_stream=1,
    )
    evaluator(pred_history, prop_history)

    assert pred_history == before_pred
    assert prop_history == before_prop
    assert id(pred_history) == pred_id
    assert id(prop_history) == prop_id
    assert tuple(id(item) for item in pred_history) == pred_element_ids
    assert tuple(id(item) for item in prop_history) == prop_element_ids
