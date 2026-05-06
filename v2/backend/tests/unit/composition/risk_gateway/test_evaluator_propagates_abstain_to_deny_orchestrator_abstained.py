def test_evaluator_propagates_abstain_to_deny_orchestrator_abstained():
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
            decision_action="abstain",
            decision_reason_code="abstain_low_confidence",
            input_prediction_direction="flat",
            input_prediction_confidence_calibrated=0.4,
            input_prediction_freshness_flag="fresh",
            input_worker_health_status="HEALTHY",
            live_blocked=True,
        )
    )

    assert result.risk_action == "deny"
    assert result.risk_reason_code == "deny_orchestrator_abstained"
    assert result.input_decision_action == "abstain"
    assert result.input_decision_reason_code == "abstain_low_confidence"
    assert result.live_blocked is True
