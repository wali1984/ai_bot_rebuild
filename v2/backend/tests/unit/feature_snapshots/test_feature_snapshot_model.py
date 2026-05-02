import json
from pathlib import Path

from v2.backend.app.services.feature_snapshots import FeatureSnapshotService


def payload():
    return json.loads(Path("v2/backend/tests/fixtures/feature_snapshots/sample_legacy_feature_payload.json").read_text())


def test_feature_snapshot_model_contains_required_lineage_fields():
    snapshot = FeatureSnapshotService().build_snapshot(payload())

    assert snapshot.feature_snapshot_id.startswith("feature_snapshot_")
    assert snapshot.canonical_symbol_id == "BINANCE-USDM-BTC-USDT-PERP"
    assert snapshot.legacy_symbol == "BTCUSDT"
    assert snapshot.source_key_refs
    assert snapshot.source_ingestor_refs
    assert "live_coinank.py" in snapshot.source_ingestor_refs
    assert snapshot.trainer_input_schema_version == "trainer_features.v1"

