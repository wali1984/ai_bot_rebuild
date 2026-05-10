from ._fixtures import TRAINER_FIELDS, dedupe_record


def test_dedupe_decision_record_carries_phase_2v_trainer_parity_fields() -> None:
    record = dedupe_record()
    assert record.model_version == TRAINER_FIELDS["model_version"]
    assert record.checkpoint_id == TRAINER_FIELDS["checkpoint_id"]
    assert record.confidence_raw == TRAINER_FIELDS["confidence_raw"]
    assert record.confidence_calibrated == TRAINER_FIELDS["confidence_calibrated"]
    assert record.trainer_worker_liveness == TRAINER_FIELDS["trainer_worker_liveness"]
