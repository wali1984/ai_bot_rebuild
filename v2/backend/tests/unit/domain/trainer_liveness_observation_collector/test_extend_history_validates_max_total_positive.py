import pytest

from v2.backend.app.domain.trainer_liveness_observation_collector import (
    ObservationCollectorError,
    extend_observation_history,
)


def test_extend_history_rejects_non_positive_max_total() -> None:
    for value in (0, -1):
        with pytest.raises(ObservationCollectorError) as exc_info:
            extend_observation_history((), (), max_total=value)

        assert exc_info.value.code == "must_be_positive"
        assert exc_info.value.field == "max_total"
