from ._fixtures import DEDUPE_DUPLICATE_OF_PRIOR, dedupe_record


def test_dedupe_decision_record_constructs_with_dedupe_duplicate_of_prior() -> None:
    record = dedupe_record(
        dedupe_decision_id="dedupe:decision-1:DEDUPE_DUPLICATE_OF_PRIOR",
        dedupe_state=DEDUPE_DUPLICATE_OF_PRIOR,
        duplicate_of_decision_id="decision-0",
    )
    assert record.duplicate_of_decision_id == "decision-0"
