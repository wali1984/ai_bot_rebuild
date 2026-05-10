from v2.backend.app.domain.provenance_dedupe_attribution import DEDUPE_NEW
from v2.backend.app.services.provenance_dedupe_attribution import (
    assemble_dedupe_decision_record,
)

from v2.backend.tests.unit.domain.provenance_dedupe_attribution._fixtures import (
    TRAINER_FIELDS,
    risk_record,
)


def test_dedupe_service_assembles_record_for_valid_inputs() -> None:
    record = assemble_dedupe_decision_record(
        upstream_record=risk_record(),
        dedupe_state=DEDUPE_NEW,
        duplicate_of_decision_id=None,
        dedupe_reason="first_seen",
        trainer_model_version=TRAINER_FIELDS["model_version"],
        trainer_checkpoint_id=TRAINER_FIELDS["checkpoint_id"],
        trainer_confidence_raw=TRAINER_FIELDS["confidence_raw"],
        trainer_confidence_calibrated=TRAINER_FIELDS["confidence_calibrated"],
        trainer_worker_liveness=TRAINER_FIELDS["trainer_worker_liveness"],
    )
    assert record.dedupe_decision_id == "dedupe:decision-1:DEDUPE_NEW"
