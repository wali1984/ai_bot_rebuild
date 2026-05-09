import pytest

from v2.backend.app.domain.external_manual_position_quarantine import (
    MANUAL_POSITION_QUARANTINED,
    ManualPositionFlag,
)
from v2.backend.app.services.external_manual_position_quarantine import (
    ExternalManualPositionQuarantineServiceError,
    assemble_external_position_quarantine_record,
)


def test_assemble_rejects_non_record_input() -> None:
    with pytest.raises(ExternalManualPositionQuarantineServiceError):
        assemble_external_position_quarantine_record(
            risk_decision_record=object(),  # type: ignore[arg-type]
            manual_position_flag=ManualPositionFlag(
                state=MANUAL_POSITION_QUARANTINED,
                live_blocked=True,
            ),
            trainer_model_version="hybrid_trainer_v2026_05",
            trainer_checkpoint_id="ckpt_base_2026_05",
            trainer_confidence_raw=0.51,
            trainer_confidence_calibrated=0.5,
            trainer_worker_liveness="alive",
        )
