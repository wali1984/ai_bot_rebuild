def test_evaluator_returns_risk_decision_record():
    from v2.backend.app.composition.risk_gateway import build_risk_decision_evaluator
    from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
    from v2.backend.app.domain.risk_gateway import RiskDecisionRecord

    evaluator = build_risk_decision_evaluator(now_ms_clock=lambda: 1)
    result = evaluator(
        decision=OrchestratorDecisionRecord(
            decision_id="decision_1",
            prediction_id="prediction_1",
            feature_snapshot_id="feature_1",
            symbol="BTCUSD",
            decision_ts_ms=1,
            decision_action="hold",
            decision_reason_code="hold_flat_direction",
            input_prediction_direction="flat",
            input_prediction_confidence_calibrated=0.5,
            input_prediction_freshness_flag="fresh",
            input_worker_health_status="HEALTHY",
            live_blocked=True,
        )
    )

    assert isinstance(result, RiskDecisionRecord)
