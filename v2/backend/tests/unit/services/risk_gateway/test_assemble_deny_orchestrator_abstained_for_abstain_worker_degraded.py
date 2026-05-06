from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


def test_assemble_deny_orchestrator_abstained_for_abstain_worker_degraded() -> None:
    decision = OrchestratorDecisionRecord(
        decision_id="dec_abstain_degraded",
        prediction_id="pred_abstain_degraded",
        feature_snapshot_id="snap_abstain_degraded",
        symbol="BTCUSDT",
        decision_ts_ms=10,
        decision_action="abstain",
        decision_reason_code="abstain_worker_degraded",
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.85,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="DEGRADED",
        live_blocked=True,
    )
    record = assemble_risk_decision_record(decision=decision, now_ms_clock=lambda: 1000)

    assert record.risk_action == "deny"
    assert record.risk_reason_code == "deny_orchestrator_abstained"
    assert record.input_decision_reason_code == "abstain_worker_degraded"
