from v2.backend.app.domain.external_manual_position_quarantine import (
    MANUAL_POSITION_NOT_PRESENT,
    ExternalPositionQuarantineRecord,
    ManualPositionFlag,
)


def test_record_constructs_with_not_present_flag() -> None:
    record = ExternalPositionQuarantineRecord(
        risk_decision_id="risk-1",
        decision_id="decision-1",
        prediction_id="prediction-1",
        feature_snapshot_id="snapshot-1",
        symbol="BTCUSDT",
        risk_decision_ts_ms=1,
        manual_position_flag=ManualPositionFlag(
            state=MANUAL_POSITION_NOT_PRESENT,
            live_blocked=True,
        ),
        model_version="hybrid_trainer_v2026_05",
        checkpoint_id="ckpt_base_2026_05",
        confidence_raw=0.51,
        confidence_calibrated=0.5,
        trainer_worker_liveness="alive",
        live_blocked=True,
    )

    assert record.manual_position_flag.state == MANUAL_POSITION_NOT_PRESENT
