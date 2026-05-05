import pytest

from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_REASON_ABSTAIN_FRESHNESS_MISSING,
    DECISION_REASON_ABSTAIN_FRESHNESS_STALE,
    DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
    DECISION_REASON_ABSTAIN_WORKER_CRITICAL,
    DECISION_REASON_ABSTAIN_WORKER_DEGRADED,
    DECISION_REASON_ABSTAIN_WORKER_UNKNOWN,
    DECISION_REASON_PROCEED_LONG,
    OrchestratorDecisionDomainError,
    OrchestratorDecisionRecord,
)


def test_abstain_requires_abstain_prefix_reason():
    base = {
        "decision_id": "decision-1",
        "prediction_id": "prediction-1",
        "feature_snapshot_id": "snapshot-1",
        "symbol": "BTCUSDT",
        "decision_ts_ms": 1,
        "decision_action": DECISION_ACTION_ABSTAIN,
        "decision_reason_code": DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
        "input_prediction_direction": "long",
        "input_prediction_confidence_calibrated": 0.85,
        "input_prediction_freshness_flag": "fresh",
        "input_worker_health_status": "HEALTHY",
        "live_blocked": True,
    }
    with pytest.raises(OrchestratorDecisionDomainError) as exc_info:
        OrchestratorDecisionRecord(
            **{**base, "decision_reason_code": DECISION_REASON_PROCEED_LONG}
        )
    assert exc_info.value.field == "decision_reason_code"
    assert exc_info.value.reason == "abstain_requires_abstain_prefix_reason"
    for reason in (
        DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
        DECISION_REASON_ABSTAIN_FRESHNESS_STALE,
        DECISION_REASON_ABSTAIN_FRESHNESS_MISSING,
        DECISION_REASON_ABSTAIN_WORKER_DEGRADED,
        DECISION_REASON_ABSTAIN_WORKER_CRITICAL,
        DECISION_REASON_ABSTAIN_WORKER_UNKNOWN,
    ):
        assert OrchestratorDecisionRecord(**{**base, "decision_reason_code": reason})
