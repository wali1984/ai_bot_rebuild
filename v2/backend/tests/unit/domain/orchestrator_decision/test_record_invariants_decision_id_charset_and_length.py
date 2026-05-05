import pytest

from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_OPEN_LONG,
    DECISION_REASON_PROCEED_LONG,
    OrchestratorDecisionDomainError,
    OrchestratorDecisionRecord,
)


def test_record_rejects_invalid_decision_id_charset_and_length():
    base = {
        "decision_id": "decision-1",
        "prediction_id": "prediction-1",
        "feature_snapshot_id": "snapshot-1",
        "symbol": "BTCUSDT",
        "decision_ts_ms": 1,
        "decision_action": DECISION_ACTION_OPEN_LONG,
        "decision_reason_code": DECISION_REASON_PROCEED_LONG,
        "input_prediction_direction": "long",
        "input_prediction_confidence_calibrated": 0.85,
        "input_prediction_freshness_flag": "fresh",
        "input_worker_health_status": "HEALTHY",
        "live_blocked": True,
    }
    cases = (
        (42, "must_be_str"),
        ("", "must_be_non_empty"),
        (" abc", "must_not_have_whitespace"),
        ("a b", "must_not_have_whitespace"),
        ("x" * 129, "must_be_at_most_128_chars"),
    )
    for value, reason in cases:
        with pytest.raises(OrchestratorDecisionDomainError) as exc_info:
            OrchestratorDecisionRecord(**{**base, "decision_id": value})
        assert exc_info.value.field == "decision_id"
        assert exc_info.value.reason == reason
