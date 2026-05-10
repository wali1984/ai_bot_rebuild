import pytest

from v2.backend.app.domain.provenance_dedupe_attribution import DEDUPE_NEW
from v2.backend.app.services.provenance_dedupe_attribution import (
    DedupeServiceError,
    assemble_dedupe_decision_record,
)


def test_dedupe_service_rejects_non_record_upstream_input() -> None:
    with pytest.raises(DedupeServiceError):
        assemble_dedupe_decision_record(
            upstream_record=object(),
            dedupe_state=DEDUPE_NEW,
            duplicate_of_decision_id=None,
            dedupe_reason="first_seen",
            trainer_model_version="model",
            trainer_checkpoint_id="checkpoint",
            trainer_confidence_raw=0.5,
            trainer_confidence_calibrated=0.4,
            trainer_worker_liveness="alive",
        )
