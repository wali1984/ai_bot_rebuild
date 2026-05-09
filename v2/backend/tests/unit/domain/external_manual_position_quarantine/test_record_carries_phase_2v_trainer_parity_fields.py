from v2.backend.app.domain.external_manual_position_quarantine import (
    MANUAL_POSITION_QUARANTINED,
    ExternalPositionQuarantineRecord,
    ManualPositionFlag,
)


def test_record_carries_phase_2v_trainer_parity_fields() -> None:
    record = ExternalPositionQuarantineRecord(
        risk_decision_id="risk-hedge",
        decision_id="decision-hedge",
        prediction_id="prediction-hedge",
        feature_snapshot_id="snapshot-hedge",
        symbol="LABUSDT",
        risk_decision_ts_ms=1,
        manual_position_flag=ManualPositionFlag(
            state=MANUAL_POSITION_QUARANTINED,
            live_blocked=True,
        ),
        model_version="hybrid_trainer_v2026_05",
        checkpoint_id="ckpt_hedge_close_residual_exposure_blocked_2026_05",
        confidence_raw=0.72,
        confidence_calibrated=0.69,
        trainer_worker_liveness="alive",
        live_blocked=True,
    )

    assert record.model_version == "hybrid_trainer_v2026_05"
    assert record.checkpoint_id == "ckpt_hedge_close_residual_exposure_blocked_2026_05"
    assert record.confidence_raw == 0.72
    assert record.confidence_calibrated == 0.69
    assert record.trainer_worker_liveness == "alive"
