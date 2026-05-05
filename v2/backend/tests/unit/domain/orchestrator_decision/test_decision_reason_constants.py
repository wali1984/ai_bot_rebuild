from v2.backend.app.domain.orchestrator_decision import (
    DECISION_REASON_ABSTAIN_FRESHNESS_MISSING,
    DECISION_REASON_ABSTAIN_FRESHNESS_STALE,
    DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
    DECISION_REASON_ABSTAIN_WORKER_CRITICAL,
    DECISION_REASON_ABSTAIN_WORKER_DEGRADED,
    DECISION_REASON_ABSTAIN_WORKER_UNKNOWN,
    DECISION_REASON_HOLD_FLAT_DIRECTION,
    DECISION_REASON_PROCEED_LONG,
    DECISION_REASON_PROCEED_SHORT,
)


def test_decision_reason_constants_are_exact_distinct_and_prefixed():
    abstain_values = (
        DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
        DECISION_REASON_ABSTAIN_FRESHNESS_STALE,
        DECISION_REASON_ABSTAIN_FRESHNESS_MISSING,
        DECISION_REASON_ABSTAIN_WORKER_DEGRADED,
        DECISION_REASON_ABSTAIN_WORKER_CRITICAL,
        DECISION_REASON_ABSTAIN_WORKER_UNKNOWN,
    )
    proceed_values = (DECISION_REASON_PROCEED_LONG, DECISION_REASON_PROCEED_SHORT)
    values = proceed_values + (DECISION_REASON_HOLD_FLAT_DIRECTION,) + abstain_values
    assert values == (
        "proceed_long",
        "proceed_short",
        "hold_flat_direction",
        "abstain_low_confidence",
        "abstain_freshness_stale",
        "abstain_freshness_missing",
        "abstain_worker_degraded",
        "abstain_worker_critical",
        "abstain_worker_unknown",
    )
    assert len(set(values)) == 9
    assert all(value.startswith("abstain_") for value in abstain_values)
    assert all(value.startswith("proceed_") for value in proceed_values)
