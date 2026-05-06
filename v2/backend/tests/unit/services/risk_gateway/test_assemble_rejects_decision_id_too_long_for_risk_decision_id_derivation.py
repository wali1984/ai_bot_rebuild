import pytest

from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import (
    RiskGatewayServiceError,
    assemble_risk_decision_record,
)


def test_assemble_rejects_decision_id_too_long_for_risk_decision_id_derivation() -> None:
    too_long = OrchestratorDecisionRecord(
        decision_id="a" * 126,
        prediction_id="pred_long_id",
        feature_snapshot_id="snap_long_id",
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
    with pytest.raises(RiskGatewayServiceError) as exc_info:
        assemble_risk_decision_record(decision=too_long, now_ms_clock=lambda: 1)
    assert exc_info.value.code == "decision_id_too_long_for_risk_decision_id_derivation"
    assert exc_info.value.field == "decision.decision_id"

    ok = OrchestratorDecisionRecord(
        decision_id="b" * 125,
        prediction_id="pred_ok_id",
        feature_snapshot_id="snap_ok_id",
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
    assert assemble_risk_decision_record(
        decision=ok,
        now_ms_clock=lambda: 1,
    ).risk_decision_id == "rd_" + ("b" * 125)
