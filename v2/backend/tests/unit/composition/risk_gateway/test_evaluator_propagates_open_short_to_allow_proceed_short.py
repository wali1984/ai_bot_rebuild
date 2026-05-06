def test_evaluator_propagates_open_short_to_allow_proceed_short():
    from v2.backend.app.composition.risk_gateway import build_risk_decision_evaluator
    from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord

    evaluator = build_risk_decision_evaluator(now_ms_clock=lambda: 1)
    result = evaluator(
        decision=OrchestratorDecisionRecord(
            decision_id="decision_1",
            prediction_id="prediction_1",
            feature_snapshot_id="feature_1",
            symbol="BTCUSD",
            decision_ts_ms=1,
            decision_action="open_short",
            decision_reason_code="proceed_short",
            input_prediction_direction="short",
            input_prediction_confidence_calibrated=0.9,
            input_prediction_freshness_flag="fresh",
            input_worker_health_status="HEALTHY",
            live_blocked=True,
        )
    )

    assert result.risk_action == "allow"
    assert result.risk_reason_code == "allow_proceed_short"
    assert result.input_decision_action == "open_short"
    assert result.input_decision_reason_code == "proceed_short"
    assert result.live_blocked is True
