from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


def test_assemble_calls_clock_exactly_once() -> None:
    calls: list[int] = []
    decision = OrchestratorDecisionRecord(
        decision_id="dec_clock_once",
        prediction_id="pred_clock_once",
        feature_snapshot_id="snap_clock_once",
        symbol="BTCUSDT",
        decision_ts_ms=1,
        decision_action="open_long",
        decision_reason_code="proceed_long",
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.85,
        input_prediction_freshness_flag="fresh",
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )

    def clock() -> int:
        calls.append(1)
        return 1 if len(calls) == 1 else 999

    record = assemble_risk_decision_record(decision=decision, now_ms_clock=clock)

    assert len(calls) == 1
    assert record.risk_decision_ts_ms == 1
