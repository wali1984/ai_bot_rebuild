from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
    RiskDecisionRecord,
)


def test_record_accepts_deny_orchestrator_abstained() -> None:
    record = RiskDecisionRecord(
        risk_decision_id="risk-abstain",
        decision_id="decision-abstain",
        prediction_id="prediction-abstain",
        feature_snapshot_id="feature-abstain",
        symbol="BTCUSDT",
        risk_decision_ts_ms=12,
        risk_action=RISK_DECISION_ACTION_DENY,
        risk_reason_code=RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
        input_decision_action="abstain",
        input_decision_reason_code="abstain_low_confidence",
        live_blocked=True,
    )
    assert record.risk_action == RISK_DECISION_ACTION_DENY
    assert record.input_decision_reason_code == "abstain_low_confidence"
