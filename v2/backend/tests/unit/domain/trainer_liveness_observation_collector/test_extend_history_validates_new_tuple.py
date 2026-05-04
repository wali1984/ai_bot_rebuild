import pytest

from v2.backend.app.domain.trainer_liveness_observation_collector import (
    ObservationCollectorError,
    extend_observation_history,
)


def test_extend_history_rejects_non_tuple_new() -> None:
    with pytest.raises(ObservationCollectorError) as exc_info:
        extend_observation_history((), [], max_total=1)  # type: ignore[arg-type]

    assert exc_info.value.code == "must_be_tuple"
    assert exc_info.value.field == "new"
