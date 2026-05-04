from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)
from v2.backend.app.domain.trainer_liveness_observation_collector import (
    StreamLatestIdReader,
)


class FakeClient:
    def xrevrange(self, stream_name: str, *, max: str, min: str, count: int):
        return None


def test_reader_satisfies_stream_latest_id_reader_protocol() -> None:
    assert isinstance(RedisStreamLatestIdReader(FakeClient()), StreamLatestIdReader)
