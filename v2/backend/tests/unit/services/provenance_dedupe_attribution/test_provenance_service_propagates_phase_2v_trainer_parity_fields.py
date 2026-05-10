from v2.backend.app.services.provenance_dedupe_attribution import (
    assemble_provenance_record,
)

from v2.backend.tests.unit.domain.provenance_dedupe_attribution._fixtures import (
    TRAINER_FIELDS,
    risk_record,
)


def test_provenance_service_propagates_phase_2v_trainer_parity_fields() -> None:
    record = assemble_provenance_record(
        upstream_record=risk_record(),
        source_id="coinank",
        ingestor_id="worker-a",
        source_ts_ms=1000,
        ingest_ts_ms=1250,
        trainer_model_version=TRAINER_FIELDS["model_version"],
        trainer_checkpoint_id=TRAINER_FIELDS["checkpoint_id"],
        trainer_confidence_raw=TRAINER_FIELDS["confidence_raw"],
        trainer_confidence_calibrated=TRAINER_FIELDS["confidence_calibrated"],
        trainer_worker_liveness=TRAINER_FIELDS["trainer_worker_liveness"],
    )
    assert record.model_version == TRAINER_FIELDS["model_version"]
    assert record.checkpoint_id == TRAINER_FIELDS["checkpoint_id"]
    assert record.confidence_raw == TRAINER_FIELDS["confidence_raw"]
    assert record.confidence_calibrated == TRAINER_FIELDS["confidence_calibrated"]
    assert record.trainer_worker_liveness == TRAINER_FIELDS["trainer_worker_liveness"]
