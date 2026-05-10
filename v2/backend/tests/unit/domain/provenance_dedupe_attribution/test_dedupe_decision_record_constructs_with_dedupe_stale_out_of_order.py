from ._fixtures import DEDUPE_STALE_OUT_OF_ORDER, dedupe_record


def test_dedupe_decision_record_constructs_with_dedupe_stale_out_of_order() -> None:
    record = dedupe_record(
        dedupe_decision_id="dedupe:decision-1:DEDUPE_STALE_OUT_OF_ORDER",
        dedupe_state=DEDUPE_STALE_OUT_OF_ORDER,
        duplicate_of_decision_id=None,
        dedupe_reason="stale_source_ts",
    )
    assert record.dedupe_state == DEDUPE_STALE_OUT_OF_ORDER
