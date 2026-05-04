from v2.backend.app.domain.liveness_stream_growth import (
    GrowthWindowConfig,
    StreamIdObservation,
    compute_stream_id_growth_in_window,
)
from v2.backend.app.domain.trainer_liveness_composition import LivenessSnapshotBaseInputs
from v2.backend.app.services.trainer_parity import evaluate_trainer_liveness


class _FakeReader:
    def __init__(self, values: dict[str, str | None]) -> None:
        self.values = values

    def latest_stream_id(self, stream_name: str) -> str | None:
        return self.values.get(stream_name)


class _MutableClock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def test_evaluate_returns_snapshot_with_growth_from_history():
    config = GrowthWindowConfig(1000)
    reader = _FakeReader({"pred": "3-0", "prop": "8-0"})
    clock = _MutableClock(1000)
    first = evaluate_trainer_liveness(
        reader,
        base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
        prediction_history=(
            StreamIdObservation("pred", "1-0", 900),
            StreamIdObservation("pred", "2-0", 950),
        ),
        proposal_history=(
            StreamIdObservation("prop", "6-0", 900),
            StreamIdObservation("prop", "7-0", 950),
        ),
        growth_config=config,
        now_ms_clock=clock,
        prediction_stream_name="pred",
        proposal_stream_name="prop",
        max_history_per_stream=5,
    )
    assert isinstance(first.snapshot.prediction_stream_id_growth, int)
    assert isinstance(first.snapshot.proposal_stream_id_growth, int)
    assert first.snapshot.prediction_stream_id_growth > 0
    assert first.snapshot.proposal_stream_id_growth > 0
    assert first.snapshot.prediction_stream_id_growth == compute_stream_id_growth_in_window(
        first.prediction_history,
        config,
        clock.value,
        stream_name="pred",
    )
    assert first.snapshot.proposal_stream_id_growth == compute_stream_id_growth_in_window(
        first.proposal_history,
        config,
        clock.value,
        stream_name="prop",
    )

    reader.values = {"pred": "4-0", "prop": "9-0"}
    clock.value = 1100
    second = evaluate_trainer_liveness(
        reader,
        base_inputs=LivenessSnapshotBaseInputs(1, 1, 1, 2, True, 1, 1, 1, 1, False, 1),
        prediction_history=first.prediction_history,
        proposal_history=first.proposal_history,
        growth_config=config,
        now_ms_clock=clock,
        prediction_stream_name="pred",
        proposal_stream_name="prop",
        max_history_per_stream=5,
    )
    assert isinstance(second.snapshot.prediction_stream_id_growth, int)
    assert isinstance(second.snapshot.proposal_stream_id_growth, int)
    assert second.snapshot.prediction_stream_id_growth > first.snapshot.prediction_stream_id_growth
    assert second.snapshot.proposal_stream_id_growth > first.snapshot.proposal_stream_id_growth
    assert second.snapshot.prediction_stream_id_growth == compute_stream_id_growth_in_window(
        second.prediction_history,
        config,
        clock.value,
        stream_name="pred",
    )
    assert second.snapshot.proposal_stream_id_growth == compute_stream_id_growth_in_window(
        second.proposal_history,
        config,
        clock.value,
        stream_name="prop",
    )
