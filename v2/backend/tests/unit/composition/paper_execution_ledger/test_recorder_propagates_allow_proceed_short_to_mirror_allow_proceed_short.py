def test_recorder_propagates_allow_proceed_short_to_mirror_allow_proceed_short():
    from v2.backend.app.composition.paper_execution_ledger import build_paper_execution_ledger_recorder
    from v2.backend.app.domain.risk_gateway import RiskDecisionRecord

    recorder = build_paper_execution_ledger_recorder(now_ms_clock=lambda: 1)
    result = recorder(
        decision=RiskDecisionRecord(
            risk_decision_id="risk_2",
            decision_id="decision_2",
            prediction_id="prediction_2",
            feature_snapshot_id="feature_2",
            symbol="ETHUSD",
            risk_decision_ts_ms=1,
            risk_action="allow",
            risk_reason_code="allow_proceed_short",
            input_decision_action="open_short",
            input_decision_reason_code="proceed_short",
            live_blocked=True,
        )
    )

    assert result.ledger_action == "record_allow"
    assert result.ledger_reason_code == "mirror_allow_proceed_short"
    assert result.input_risk_action == "allow"
    assert result.input_risk_reason_code == "allow_proceed_short"
    assert result.live_blocked is True
