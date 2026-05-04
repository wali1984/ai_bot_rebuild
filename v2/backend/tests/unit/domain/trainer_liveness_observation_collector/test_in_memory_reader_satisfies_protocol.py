from v2.backend.app.domain.trainer_liveness_observation_collector import (
    InMemoryStreamLatestIdReader,
    StreamLatestIdReader,
)


def test_in_memory_reader_satisfies_protocol() -> None:
    reader = InMemoryStreamLatestIdReader({"trainer:prediction": "101-0"})

    assert isinstance(reader, StreamLatestIdReader)
