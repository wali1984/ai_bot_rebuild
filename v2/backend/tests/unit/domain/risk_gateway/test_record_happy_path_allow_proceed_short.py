from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    RiskDecisionRecord,
)


def test_record_accepts_allow_proceed_short() -> None:
    record = RiskDecisionRecord(
        risk_decision_id="risk-short",
        decision_id="decision-short",
        prediction_id="prediction-short",
        feature_snapshot_id="feature-short",
        symbol="ETHUSDT",
        risk_decision_ts_ms=11,
        risk_action=RISK_DECISION_ACTION_ALLOW,
        risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        input_decision_action="open_short",
        input_decision_reason_code="proceed_short",
        live_blocked=True,
    )
    assert record.risk_action == RISK_DECISION_ACTION_ALLOW
    assert record.risk_reason_code == RISK_DECISION_REASON_ALLOW_PROCEED_SHORT
    assert record.input_decision_action == "open_short"
    assert record.input_decision_reason_code == "proceed_short"
