def test_recorder_propagates_deny_orchestrator_abstained_to_mirror_deny_orchestrator_abstained():
    from v2.backend.app.composition.paper_execution_ledger import build_paper_execution_ledger_recorder
    from v2.backend.app.domain.risk_gateway import RiskDecisionRecord

    recorder = build_paper_execution_ledger_recorder(now_ms_clock=lambda: 1)
    result = recorder(
        decision=RiskDecisionRecord(
            risk_decision_id="risk_4",
            decision_id="decision_4",
            prediction_id="prediction_4",
            feature_snapshot_id="feature_4",
            symbol="ADAUSD",
            risk_decision_ts_ms=1,
            risk_action="deny",
            risk_reason_code="deny_orchestrator_abstained",
            input_decision_action="abstain",
            input_decision_reason_code="abstain_low_confidence",
            live_blocked=True,
        )
    )

    assert result.ledger_action == "record_deny"
    assert result.ledger_reason_code == "mirror_deny_orchestrator_abstained"
    assert result.input_risk_action == "deny"
    assert result.input_risk_reason_code == "deny_orchestrator_abstained"
    assert result.live_blocked is True
