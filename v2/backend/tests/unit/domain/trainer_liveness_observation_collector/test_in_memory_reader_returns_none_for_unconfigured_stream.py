from v2.backend.app.domain.trainer_liveness_observation_collector import InMemoryStreamLatestIdReader


def test_in_memory_reader_returns_none_for_unconfigured_stream() -> None:
    reader = InMemoryStreamLatestIdReader({"trainer:prediction": "101-0"})

    assert reader.latest_stream_id("trainer:proposal") is None
