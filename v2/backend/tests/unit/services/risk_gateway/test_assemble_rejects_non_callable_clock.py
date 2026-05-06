import pytest

from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import (
    RiskGatewayServiceError,
    assemble_risk_decision_record,
)


def test_assemble_rejects_non_callable_clock() -> None:
    decision = OrchestratorDecisionRecord(
        decision_id="dec_bad_clock",
        prediction_id="pred_bad_clock",
        feature_snapshot_id="snap_bad_clock",
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
        assemble_risk_decision_record(decision=decision, now_ms_clock=42)  # type: ignore[arg-type]

    assert exc_info.value.code == "must_be_callable"
    assert exc_info.value.field == "now_ms_clock"
