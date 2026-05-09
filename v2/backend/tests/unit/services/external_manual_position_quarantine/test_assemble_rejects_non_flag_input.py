import pytest

from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.external_manual_position_quarantine import (
    ExternalManualPositionQuarantineServiceError,
    assemble_external_position_quarantine_record,
)


def test_assemble_rejects_non_flag_input() -> None:
    with pytest.raises(ExternalManualPositionQuarantineServiceError):
        assemble_external_position_quarantine_record(
            risk_decision_record=RiskDecisionRecord(
                risk_decision_id="risk-base",
                decision_id="decision-base",
                prediction_id="prediction-base",
                feature_snapshot_id="snapshot-base",
                symbol="BTCUSDT",
                risk_decision_ts_ms=1,
                risk_action="allow",
                risk_reason_code="allow_proceed_long",
                input_decision_action="open_long",
                input_decision_reason_code="proceed_long",
                live_blocked=True,
            ),
            manual_position_flag=object(),  # type: ignore[arg-type]
            trainer_model_version="hybrid_trainer_v2026_05",
            trainer_checkpoint_id="ckpt_base_2026_05",
            trainer_confidence_raw=0.51,
            trainer_confidence_calibrated=0.5,
            trainer_worker_liveness="alive",
        )
