from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RiskDecisionRecord,
)


def test_record_accepts_deny_orchestrator_held() -> None:
    record = RiskDecisionRecord(
        risk_decision_id="risk-held",
        decision_id="decision-held",
        prediction_id="prediction-held",
        feature_snapshot_id="feature-held",
        symbol="BTCUSDT",
        risk_decision_ts_ms=13,
        risk_action=RISK_DECISION_ACTION_DENY,
        risk_reason_code=RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
        input_decision_action="hold",
        input_decision_reason_code="hold_flat_direction",
        live_blocked=True,
    )
    assert record.risk_action == RISK_DECISION_ACTION_DENY
    assert record.input_decision_action == "hold"
