def test_recorder_propagates_deny_orchestrator_held_to_mirror_deny_orchestrator_held():
    from v2.backend.app.composition.paper_execution_ledger import build_paper_execution_ledger_recorder
    from v2.backend.app.domain.risk_gateway import RiskDecisionRecord

    recorder = build_paper_execution_ledger_recorder(now_ms_clock=lambda: 1)
    result = recorder(
        decision=RiskDecisionRecord(
            risk_decision_id="risk_3",
            decision_id="decision_3",
            prediction_id="prediction_3",
            feature_snapshot_id="feature_3",
            symbol="SOLUSD",
            risk_decision_ts_ms=1,
            risk_action="deny",
            risk_reason_code="deny_orchestrator_held",
            input_decision_action="hold",
            input_decision_reason_code="hold_flat_direction",
            live_blocked=True,
        )
    )

    assert result.ledger_action == "record_deny"
    assert result.ledger_reason_code == "mirror_deny_orchestrator_held"
    assert result.input_risk_action == "deny"
    assert result.input_risk_reason_code == "deny_orchestrator_held"
    assert result.live_blocked is True
