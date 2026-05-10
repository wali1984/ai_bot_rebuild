from ._fixtures import DEDUPE_NEW, dedupe_record


def test_dedupe_decision_record_constructs_with_dedupe_new() -> None:
    record = dedupe_record(dedupe_state=DEDUPE_NEW, duplicate_of_decision_id=None)
    assert record.dedupe_state == DEDUPE_NEW
    assert record.duplicate_of_decision_id is None
