from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_DENY_DEFAULT,
    RiskDecisionRecord,
)


def test_record_accepts_deny_default_with_open_long_input() -> None:
    record = RiskDecisionRecord(
        risk_decision_id="risk-default-long",
        decision_id="decision-default-long",
        prediction_id="prediction-default-long",
        feature_snapshot_id="feature-default-long",
        symbol="BTCUSDT",
        risk_decision_ts_ms=14,
        risk_action=RISK_DECISION_ACTION_DENY,
        risk_reason_code=RISK_DECISION_REASON_DENY_DEFAULT,
        input_decision_action="open_long",
        input_decision_reason_code="proceed_long",
        live_blocked=True,
    )
    assert record.input_decision_action == "open_long"
