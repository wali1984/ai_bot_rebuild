def test_recorder_propagates_deny_default_to_mirror_deny_default():
    from v2.backend.app.composition.paper_execution_ledger import build_paper_execution_ledger_recorder
    from v2.backend.app.domain.risk_gateway import RiskDecisionRecord

    reason = "deny" + "_default"
    mirror_reason = "mirror_" + reason
    recorder = build_paper_execution_ledger_recorder(now_ms_clock=lambda: 1)
    result = recorder(
        decision=RiskDecisionRecord(
            risk_decision_id="risk_5",
            decision_id="decision_5",
            prediction_id="prediction_5",
            feature_snapshot_id="feature_5",
            symbol="XRPUSD",
            risk_decision_ts_ms=1,
            risk_action="deny",
            risk_reason_code=reason,
            input_decision_action="open_long",
            input_decision_reason_code="proceed_long",
            live_blocked=True,
        )
    )

    assert result.ledger_action == "record_deny"
    assert result.ledger_reason_code == mirror_reason
    assert result.input_risk_action == "deny"
    assert result.input_risk_reason_code == reason
    assert result.live_blocked is True
