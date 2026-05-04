from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    StreamIdObservation,
    compute_stream_id_growth_in_window,
)
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
    config = GrowthWindowConfig(1000)
    now_ms = 1000000
    result = evaluate_trainer_liveness(
        _FakeReader(),
        base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
        prediction_history=(StreamIdObservation("pred", "1-0", 999500),),
        proposal_history=(),
        growth_config=config,
        now_ms_clock=_FixedClock(now_ms),
        prediction_stream_name="pred",
        proposal_stream_name="prop",
        max_history_per_stream=3,
    )
    assert result.snapshot.prediction_stream_id_growth == compute_stream_id_growth_in_window(
        result.prediction_history,
        config,
        now_ms,
        stream_name="pred",
    )
