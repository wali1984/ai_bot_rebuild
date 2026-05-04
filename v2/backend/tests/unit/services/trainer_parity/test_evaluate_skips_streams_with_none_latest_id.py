from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig, StreamIdObservation
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.services.trainer_parity import evaluate_trainer_liveness


class _FakeReader:
    def __init__(self, values: dict[str, str | None]) -> None:
        self.values = values

    def latest_stream_id(self, stream_name: str) -> str | None:
        return self.values.get(stream_name)


def test_evaluate_skips_streams_with_none_latest_id():
    prediction_history = (StreamIdObservation("pred", "1-0", 900),)
    proposal_history = (StreamIdObservation("prop", "1-0", 900),)
    result = evaluate_trainer_liveness(
        _FakeReader({"pred": None, "prop": None}),
        base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
        prediction_history=prediction_history,
        proposal_history=proposal_history,
        growth_config=GrowthWindowConfig(1000),
        now_ms_clock=lambda: 1000,
        prediction_stream_name="pred",
        proposal_stream_name="prop",
        max_history_per_stream=3,
    )
    assert result.prediction_history == prediction_history
    assert result.proposal_history == proposal_history
