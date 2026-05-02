import json
from pathlib import Path

from v2.backend.app.services.feature_snapshots import FeatureSnapshotService


def payload():
    return json.loads(Path("v2/backend/tests/fixtures/feature_snapshots/sample_legacy_feature_payload.json").read_text())


def test_snapshot_tracks_missing_stale_and_unused_features():
    data = payload()
    data["feature_values"].pop("spread_bps")
    data["sources"]["binance_price"]["source_ts"] = "2026-05-02T05:00:00+00:00"
    data["feature_values"]["debug_unused_feature"] = 1.0
    snapshot = FeatureSnapshotService().build_snapshot(data)

    assert "spread_bps" in snapshot.missing_features
    assert "close" in snapshot.stale_features
    assert "debug_unused_feature" in snapshot.unused_features
    assert snapshot.confidence_input_ready is False

