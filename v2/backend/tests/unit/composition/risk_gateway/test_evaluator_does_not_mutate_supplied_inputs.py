def test_evaluator_does_not_mutate_supplied_inputs():
    from v2.backend.app.composition.risk_gateway import build_risk_decision_evaluator
    from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord

    evaluator = build_risk_decision_evaluator(now_ms_clock=lambda: 1)
    decision = OrchestratorDecisionRecord(
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
    original = (
        decision.decision_id,
        decision.prediction_id,
        decision.feature_snapshot_id,
        decision.symbol,
        decision.decision_ts_ms,
        decision.decision_action,
        decision.decision_reason_code,
        decision.input_prediction_direction,
        decision.input_prediction_confidence_calibrated,
        decision.input_prediction_freshness_flag,
        decision.input_worker_health_status,
        decision.live_blocked,
    )

    evaluator(decision=decision)

    assert decision is decision
    assert (
        decision.decision_id,
        decision.prediction_id,
        decision.feature_snapshot_id,
        decision.symbol,
        decision.decision_ts_ms,
        decision.decision_action,
        decision.decision_reason_code,
        decision.input_prediction_direction,
        decision.input_prediction_confidence_calibrated,
        decision.input_prediction_freshness_flag,
        decision.input_worker_health_status,
        decision.live_blocked,
    ) == original
