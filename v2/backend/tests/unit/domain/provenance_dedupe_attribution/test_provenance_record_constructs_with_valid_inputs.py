from ._fixtures import provenance_record


def test_provenance_record_constructs_with_valid_inputs() -> None:
    record = provenance_record()
    assert record.provenance_id == "prov:decision-1:coinank:worker-a"
    assert record.freshness_ms == 250
