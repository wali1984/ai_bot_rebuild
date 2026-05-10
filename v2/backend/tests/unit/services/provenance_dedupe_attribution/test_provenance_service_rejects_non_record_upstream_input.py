import pytest

from v2.backend.app.services.provenance_dedupe_attribution import (
    ProvenanceServiceError,
    assemble_provenance_record,
)


def test_provenance_service_rejects_non_record_upstream_input() -> None:
    with pytest.raises(ProvenanceServiceError):
        assemble_provenance_record(
            upstream_record=object(),
            source_id="coinank",
            ingestor_id="worker-a",
            source_ts_ms=1000,
            ingest_ts_ms=1250,
            trainer_model_version="model",
            trainer_checkpoint_id="checkpoint",
            trainer_confidence_raw=0.5,
            trainer_confidence_calibrated=0.4,
            trainer_worker_liveness="alive",
        )
