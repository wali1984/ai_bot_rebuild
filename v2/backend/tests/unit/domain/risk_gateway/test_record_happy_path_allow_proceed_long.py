from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RiskDecisionRecord,
)


def test_record_accepts_allow_proceed_long() -> None:
    record = RiskDecisionRecord(
        risk_decision_id="risk-long",
        decision_id="decision-long",
        prediction_id="prediction-long",
        feature_snapshot_id="feature-long",
        symbol="BTCUSDT",
        risk_decision_ts_ms=10,
        risk_action=RISK_DECISION_ACTION_ALLOW,
        risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )
    assert record.risk_decision_id == "risk-long"
    assert record.decision_id == "decision-long"
    assert record.prediction_id == "prediction-long"
    assert record.feature_snapshot_id == "feature-long"
    assert record.symbol == "BTCUSDT"
    assert record.risk_decision_ts_ms == 10
    assert record.risk_action == RISK_DECISION_ACTION_ALLOW
    assert record.risk_reason_code == RISK_DECISION_REASON_ALLOW_PROCEED_LONG
    assert record.input_decision_action == "open_long"
    assert record.input_decision_reason_code == "proceed_long"
    assert record.live_blocked is True
