from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.domain.liveness_stream_growth.errors import (
    LivenessStreamGrowthDomainError,
)
from v2.backend.app.domain.trainer_liveness.errors import LivenessDomainError
from v2.backend.app.domain.trainer_liveness_composition.errors import (
    TrainerLivenessCompositionError,
)
from v2.backend.app.domain.trainer_liveness_observation_collector.errors import (
    ObservationCollectorError,
)


def test_errors_format_and_lineage() -> None:
    assert str(RedisStreamReaderError("c")) == "c"
    assert str(RedisStreamReaderError("c", field="f")) == "c (f)"
    for error_type in (
        ObservationCollectorError,
        LivenessStreamGrowthDomainError,
        LivenessDomainError,
        TrainerLivenessCompositionError,
    ):
        assert not issubclass(RedisStreamReaderError, error_type)
