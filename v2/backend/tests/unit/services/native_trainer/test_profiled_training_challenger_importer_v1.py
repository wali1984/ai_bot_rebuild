from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    iter_snapshots,
)
from v2.backend.app.services.native_trainer.model_edge_recovery_challenger import (
    _row_reject_reasons,
    freeze_dataset_from_archive,
)
from v2.backend.app.services.native_trainer.profiled_training_challenger_importer_v1 import (
    LABEL_SOURCE,
    import_profiled_training_ledger_to_challenger_archive_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_model_feature_snapshot_record_v1 as base_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_observation_manifest_v1 as manifest_support,
)


def test_importer_reconstructs_idempotent_pit_challenger_row(
    tmp_path: Path,
) -> None:
    evidence = base_support._build_evidence(tmp_path / "base")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    ledger, labels, observation, cost_root = manifest_support._setup_sources(
        source_root,
        evidence,
    )
    challenger_archive = tmp_path / "challenger-archive"

    first = import_profiled_training_ledger_to_challenger_archive_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=labels,
        challenger_archive_root=challenger_archive,
        training_observed_at=observation,
    )

    assert first.source_admitted_sample_count == 1
    assert first.label_paths_verified == 1
    assert first.imported_rows == 1
    assert first.duplicate_rows == 0
    assert first.rejected_rows == 0
    assert first.prediction_authorized is False
    assert first.paper_trading_authorized is False
    assert first.live_execution_authorized is False

    snapshot = next(iter_snapshots(challenger_archive, limit=1))
    assert _row_reject_reasons(snapshot) == []
    assert snapshot["label_source"] == LABEL_SOURCE
    assert snapshot["label_binding"]["source"] == LABEL_SOURCE
    assert snapshot["label_binding"]["label_binding_sha256"]
    assert snapshot["mtf_snapshot_id"].startswith("profiled-mtf:")
    assert snapshot["source_hashes"]["mtf_binding_sha256"]
    assert snapshot["source_hashes"]["canonical_label_binding_sha256"]
    assert snapshot["source_hashes"]["profiled_ledger_record_sha256"]
    assert snapshot["source_hashes"]["cost_capture_binding_sha256"]
    assert snapshot["source_hashes"]["cost_capture_receipt_sha256"]
    assert snapshot["candle_closed_confirmed"] is True
    assert snapshot["latest_unclosed_kline_excluded"] is True
    assert snapshot["features"]["fee_bps"] >= 0.0
    assert snapshot["features"]["expected_slippage_bps"] >= 0.0
    assert isinstance(snapshot["features"]["expected_funding_bps"], float)
    assert all(not name.startswith("future_") for name in snapshot["features"])
    assert all(not name.startswith("label_") for name in snapshot["features"])
    available_at = datetime.fromisoformat(snapshot["available_at"].replace("Z", "+00:00"))
    feature_cutoff = datetime.fromisoformat(
        snapshot["feature_cutoff"].replace("Z", "+00:00")
    )
    decision_time = datetime.fromisoformat(snapshot["decision_time"].replace("Z", "+00:00"))
    assert feature_cutoff.astimezone(UTC) <= available_at.astimezone(UTC)
    assert available_at.astimezone(UTC) <= decision_time.astimezone(UTC)

    freeze = freeze_dataset_from_archive(
        archive_root=challenger_archive,
        canonical_label_archive=labels,
        training_observed_at=observation,
    )
    assert len(freeze.rows) == 1
    assert freeze.manifest["canonical_label_archive_integrity_verified"] is True
    assert freeze.manifest["canonical_label_rows"] == 1
    assert freeze.rows[0].label_available_at > freeze.rows[0].decision_time
    assert freeze.rows[0].cost_evidence_hash

    second = import_profiled_training_ledger_to_challenger_archive_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=labels,
        challenger_archive_root=challenger_archive,
        training_observed_at=observation,
    )
    assert second.imported_rows == 0
    assert second.duplicate_rows == 1
    assert second.imported_snapshot_ids == first.imported_snapshot_ids
