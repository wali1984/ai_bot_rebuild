from v2.backend.app.domain.liveness_stream_growth import GrowthWindowConfig, StreamIdObservation
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.services.trainer_parity import evaluate_trainer_liveness


class _FakeReader:
    def latest_stream_id(self, stream_name: str) -> str | None:
        return None


class _FixedClock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def test_evaluate_passes_now_ms_into_compose():
    result = evaluate_trainer_liveness(
        _FakeReader(),
        base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
        prediction_history=(StreamIdObservation("pred", "1-0", 999500),),
        proposal_history=(),
        growth_config=GrowthWindowConfig(1000),
        now_ms_clock=_FixedClock(1000000),
        prediction_stream_name="pred",
        proposal_stream_name="prop",
        max_history_per_stream=3,
    )
    assert result.snapshot.prediction_stream_id_growth == 1
