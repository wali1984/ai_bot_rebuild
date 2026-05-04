from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.services.trainer_parity import evaluate_trainer_liveness


class _FakeReader:
    def __init__(self, values: dict[str, str | None]) -> None:
        self.values = values

    def latest_stream_id(self, stream_name: str) -> str | None:
        return self.values.get(stream_name)


class _RecordingClock:
    def __init__(self, value: int) -> None:
        self.value = value
        self.calls = []

    def __call__(self) -> int:
        self.calls.append("called")
        return self.value


def test_evaluate_calls_clock_exactly_once():
    clock = _RecordingClock(1000)
    evaluate_trainer_liveness(
        _FakeReader({"pred": "1-0", "prop": None}),
        base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
        prediction_history=(),
        proposal_history=(),
        growth_config=GrowthWindowConfig(1000),
        now_ms_clock=clock,
        prediction_stream_name="pred",
        proposal_stream_name="prop",
        max_history_per_stream=2,
    )
    assert len(clock.calls) == 1
