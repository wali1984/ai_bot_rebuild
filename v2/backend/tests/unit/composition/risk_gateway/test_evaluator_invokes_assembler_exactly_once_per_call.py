def test_evaluator_invokes_assembler_exactly_once_per_call():
    from v2.backend.app.composition.risk_gateway import build_risk_decision_evaluator
    from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord

    n = [0]

    def clock():
        n[0] += 1
        return 1

    evaluator = build_risk_decision_evaluator(now_ms_clock=clock)
    evaluator(
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

    assert n == [1]
