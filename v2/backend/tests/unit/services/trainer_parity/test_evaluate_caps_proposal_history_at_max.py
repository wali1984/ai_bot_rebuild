from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig, StreamIdObservation
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.services.trainer_parity import evaluate_trainer_liveness


class _FakeReader:
    def __init__(self, values: dict[str, str | None]) -> None:
        self.values = values

    def latest_stream_id(self, stream_name: str) -> str | None:
        return self.values.get(stream_name)


def test_evaluate_caps_proposal_history_at_max():
    oldest = StreamIdObservation("prop", "1-0", 900)
    prior = (oldest, StreamIdObservation("prop", "2-0", 950))
    result = evaluate_trainer_liveness(
        _FakeReader({"pred": None, "prop": "3-0"}),
        base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
        prediction_history=(),
        proposal_history=prior,
        growth_config=GrowthWindowConfig(1000),
        now_ms_clock=lambda: 1000,
        prediction_stream_name="pred",
        proposal_stream_name="prop",
        max_history_per_stream=2,
    )
    assert len(result.proposal_history) == 2
    assert oldest not in result.proposal_history
