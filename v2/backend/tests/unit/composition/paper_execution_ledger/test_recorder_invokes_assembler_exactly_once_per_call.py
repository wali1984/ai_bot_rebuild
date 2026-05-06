def test_recorder_invokes_assembler_exactly_once_per_call():
    from v2.backend.app.composition.paper_execution_ledger import build_paper_execution_ledger_recorder
    from v2.backend.app.domain.risk_gateway import RiskDecisionRecord

    n = [0]

    def clock():
        n[0] += 1
        return 1

    recorder = build_paper_execution_ledger_recorder(now_ms_clock=clock)
    recorder(
        decision=RiskDecisionRecord(
            risk_decision_id="risk_1",
            decision_id="decision_1",
            prediction_id="prediction_1",
            feature_snapshot_id="feature_1",
            symbol="BTCUSD",
            risk_decision_ts_ms=1,
            risk_action="allow",
            risk_reason_code="allow_proceed_long",
            input_decision_action="open_long",
            input_decision_reason_code="proceed_long",
            live_blocked=True,
        )
    )

    assert n == [1]
