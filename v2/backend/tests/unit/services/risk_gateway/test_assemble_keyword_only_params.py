import pytest

from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


def test_assemble_keyword_only_params() -> None:
    decision = OrchestratorDecisionRecord(
        decision_id="dec_kw",
        prediction_id="pred_kw",
        feature_snapshot_id="snap_kw",
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
    with pytest.raises(TypeError):
        assemble_risk_decision_record(decision, lambda: 1)  # type: ignore[misc]

    assert assemble_risk_decision_record(
        decision=decision,
        now_ms_clock=lambda: 1,
    ).risk_decision_id == "rd_dec_kw"
