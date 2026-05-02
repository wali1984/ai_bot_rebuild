import json
from pathlib import Path

from v2.backend.app.adapters.feature_pipeline.legacy_adapter import LegacyFeaturePipelineAdapter
from v2.backend.app.domain.features.validation import validate_trainer_input


def payload():
    return json.loads(Path("v2/backend/tests/fixtures/feature_snapshots/sample_legacy_feature_payload.json").read_text())


def test_trainer_input_contract_is_ready_for_complete_fresh_payload():
    snapshot = LegacyFeaturePipelineAdapter().to_feature_snapshot(payload())
    trainer_payload = snapshot.trainer_payload()

    assert validate_trainer_input(snapshot) == []
    assert trainer_payload["feature_snapshot_id"] == snapshot.feature_snapshot_id
    assert trainer_payload["confidence_input_ready"] is True
    assert trainer_payload["trainer_input_schema_version"] == "trainer_features.v1"
    assert "feature_values" in trainer_payload
