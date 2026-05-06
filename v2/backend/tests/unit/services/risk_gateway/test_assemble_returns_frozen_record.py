from dataclasses import FrozenInstanceError

import pytest

from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.services.risk_gateway import assemble_risk_decision_record


def test_assemble_returns_frozen_record() -> None:
    decision = OrchestratorDecisionRecord(
        decision_id="dec_frozen",
        prediction_id="pred_frozen",
        feature_snapshot_id="snap_frozen",
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
    record = assemble_risk_decision_record(decision=decision, now_ms_clock=lambda: 1)

    with pytest.raises(FrozenInstanceError):
        record.risk_decision_id = "changed"  # type: ignore[misc]
