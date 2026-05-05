from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_DENY_DEFAULT,
    RiskDecisionRecord,
)


def test_record_accepts_deny_default_with_open_short_input() -> None:
    record = RiskDecisionRecord(
        risk_decision_id="risk-default-short",
        decision_id="decision-default-short",
        prediction_id="prediction-default-short",
        feature_snapshot_id="feature-default-short",
        symbol="BTCUSDT",
        risk_decision_ts_ms=15,
        risk_action=RISK_DECISION_ACTION_DENY,
        risk_reason_code=RISK_DECISION_REASON_DENY_DEFAULT,
        input_decision_action="open_short",
        input_decision_reason_code="proceed_short",
        live_blocked=True,
    )
    assert record.input_decision_action == "open_short"
