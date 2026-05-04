import pytest

from v2.backend.app.domain.liveness_stream_growth import LivenessStreamGrowthDomainError
from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    collect_stream_id_observations,
)


def test_collect_propagates_beta_observation_validation_unchanged() -> None:
    reader = InMemoryStreamLatestIdReader({"bad stream": "not-a-stream-id"})

    with pytest.raises(LivenessStreamGrowthDomainError) as exc_info:
        collect_stream_id_observations(
            reader,
            stream_names=("bad stream",),
            clock_ms=lambda: 1,
        )

    assert exc_info.value.reason == "must_not_have_whitespace"
    assert exc_info.value.field == "stream_name"
