from v2.backend.app.domain.provenance_dedupe_attribution import (
    DEDUPE_STALE_OUT_OF_ORDER,
)
from v2.backend.app.services.provenance_dedupe_attribution import (
    assemble_dedupe_decision_record,
)

from v2.backend.tests.unit.domain.provenance_dedupe_attribution._fixtures import (
    TRAINER_FIELDS,
    risk_record,
)


def test_dedupe_service_derives_dedupe_decision_id_deterministically() -> None:
    record = assemble_dedupe_decision_record(
        upstream_record=risk_record(),
        dedupe_state=DEDUPE_STALE_OUT_OF_ORDER,
        duplicate_of_decision_id=None,
        dedupe_reason="stale_source_ts",
        trainer_model_version=TRAINER_FIELDS["model_version"],
        trainer_checkpoint_id=TRAINER_FIELDS["checkpoint_id"],
        trainer_confidence_raw=TRAINER_FIELDS["confidence_raw"],
        trainer_confidence_calibrated=TRAINER_FIELDS["confidence_calibrated"],
        trainer_worker_liveness=TRAINER_FIELDS["trainer_worker_liveness"],
    )
    assert record.dedupe_decision_id == "dedupe:decision-1:DEDUPE_STALE_OUT_OF_ORDER"
