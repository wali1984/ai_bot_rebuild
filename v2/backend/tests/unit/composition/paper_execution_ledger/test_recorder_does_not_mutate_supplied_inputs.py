def test_recorder_does_not_mutate_supplied_inputs():
    from v2.backend.app.composition.paper_execution_ledger import build_paper_execution_ledger_recorder
    from v2.backend.app.domain.risk_gateway import RiskDecisionRecord

    recorder = build_paper_execution_ledger_recorder(now_ms_clock=lambda: 1)
    decision = RiskDecisionRecord(
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
    original = (
        decision.risk_decision_id,
        decision.decision_id,
        decision.prediction_id,
        decision.feature_snapshot_id,
        decision.symbol,
        decision.risk_decision_ts_ms,
        decision.risk_action,
        decision.risk_reason_code,
        decision.input_decision_action,
        decision.input_decision_reason_code,
        decision.live_blocked,
    )

    recorder(decision=decision)

    assert (
        decision.risk_decision_id,
        decision.decision_id,
        decision.prediction_id,
        decision.feature_snapshot_id,
        decision.symbol,
        decision.risk_decision_ts_ms,
        decision.risk_action,
        decision.risk_reason_code,
        decision.input_decision_action,
        decision.input_decision_reason_code,
        decision.live_blocked,
    ) == original
