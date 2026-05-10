import pytest

from v2.backend.app.domain.degraded_state_fail_closed_gates import (
    DEGRADED_SOURCE_OK,
)
from v2.backend.app.services.degraded_state_fail_closed_gates import (
    DegradedStateFailClosedGatesServiceError,
    assemble_degraded_state_record,
)


def test_service_rejects_non_record_upstream_input() -> None:
    with pytest.raises(DegradedStateFailClosedGatesServiceError):
        assemble_degraded_state_record(
            upstream_record=object(),  # type: ignore[arg-type]
            smc_state=DEGRADED_SOURCE_OK,
            smc_age_ms=50,
            liq_state=DEGRADED_SOURCE_OK,
            liq_age_ms=60,
            oi_state=DEGRADED_SOURCE_OK,
            oi_age_ms=70,
            orderbook_state=DEGRADED_SOURCE_OK,
            orderbook_age_ms=80,
            trainer_model_version="hybrid_trainer_v2026_05",
            trainer_checkpoint_id="ckpt_duplicate_signal_blocked_2026_05",
            trainer_confidence_raw=0.71,
            trainer_confidence_calibrated=0.68,
            trainer_worker_liveness="alive",
        )
