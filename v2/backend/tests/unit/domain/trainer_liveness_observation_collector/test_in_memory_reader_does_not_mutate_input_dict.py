from v2.backend.app.domain.trainer_liveness_observation_collector import InMemoryStreamLatestIdReader


def test_in_memory_reader_does_not_mutate_or_observe_input_dict_changes() -> None:
    latest_ids = {"trainer:prediction": "101-0"}
    reader = InMemoryStreamLatestIdReader(latest_ids)

    latest_ids["trainer:prediction"] = "202-0"
    latest_ids["trainer:proposal"] = "303-0"

    assert reader.latest_stream_id("trainer:prediction") == "101-0"
    assert reader.latest_stream_id("trainer:proposal") is None
