from v2.backend.app.domain.external_manual_position_quarantine import (
    MANUAL_POSITION_QUARANTINED,
    ManualPositionFlag,
)
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.external_manual_position_quarantine import (
    assemble_external_position_quarantine_record,
)


def test_assemble_returns_record_for_quarantined_flag() -> None:
    record = assemble_external_position_quarantine_record(
        risk_decision_record=_risk_decision_record(),
        manual_position_flag=ManualPositionFlag(
            state=MANUAL_POSITION_QUARANTINED,
            live_blocked=True,
        ),
        trainer_model_version="hybrid_trainer_v2026_05",
        trainer_checkpoint_id="ckpt_hedge_close_residual_exposure_blocked_2026_05",
        trainer_confidence_raw=0.72,
        trainer_confidence_calibrated=0.69,
        trainer_worker_liveness="alive",
    )

    assert record.manual_position_flag.state == MANUAL_POSITION_QUARANTINED
    assert record.symbol == "LABUSDT"
    assert record.live_blocked is True


def _risk_decision_record() -> RiskDecisionRecord:
    return RiskDecisionRecord(
        risk_decision_id="risk-hedge",
        decision_id="decision-hedge",
        prediction_id="prediction-hedge",
        feature_snapshot_id="snapshot-hedge",
        symbol="LABUSDT",
        risk_decision_ts_ms=1,
        risk_action="deny",
        risk_reason_code="deny_default",
        input_decision_action="open_short",
        input_decision_reason_code="proceed_short",
        live_blocked=True,
    )
