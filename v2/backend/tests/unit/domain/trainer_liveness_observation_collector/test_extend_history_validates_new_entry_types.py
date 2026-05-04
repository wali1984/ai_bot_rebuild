import pytest

from v2.backend.app.domain.trainer_liveness_observation_collector import (
    ObservationCollectorError,
    extend_observation_history,
)


def test_extend_history_rejects_non_observation_new_entry() -> None:
    with pytest.raises(ObservationCollectorError) as exc_info:
        extend_observation_history((), ("1-0",), max_total=1)  # type: ignore[arg-type]

    assert exc_info.value.code == "must_be_stream_id_observation"
    assert exc_info.value.field == "new"
