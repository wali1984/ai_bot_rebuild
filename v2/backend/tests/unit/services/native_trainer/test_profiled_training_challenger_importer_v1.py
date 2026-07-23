from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_training_challenger_importer_v1 as importer,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    iter_snapshots,
)
from v2.backend.app.services.native_trainer.model_edge_recovery_challenger import (
    _row_reject_reasons,
    freeze_dataset_from_archive,
)
from v2.backend.app.services.native_trainer.profiled_training_challenger_importer_v1 import (
    LABEL_SOURCE,
    import_profiled_training_observation_manifest_shard_to_challenger_archive_v1,
    import_profiled_training_ledger_shards_to_challenger_archive_v1,
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
    # Online shards use a bounded canonical-label range proof when no current
    # full-tail proof was supplied; forcing a global proof here would make a
    # continually appended archive part of the hot path.
    assert freeze.manifest["canonical_label_archive_integrity_verified"] is False
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


def test_manifest_shard_importer_reuses_authenticated_observation_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = base_support._build_evidence(tmp_path / "base")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    ledger, labels, observation, cost_root = manifest_support._setup_sources(
        source_root,
        evidence,
    )
    trusted_now = max(
        datetime.now(tz=UTC) + timedelta(days=1),
        datetime(2026, 7, 23, tzinfo=UTC),
    )
    monkeypatch.setattr(
        manifest_support.manifest_module,
        "_factory_wall_clock_now",
        lambda: trusted_now,
    )
    built = manifest_support.build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=labels,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=manifest_support.AUTH_KEY_ID,
        hmac_key=manifest_support.AUTH_KEY,
    )
    challenger_archive = (tmp_path / "manifest-challenger-archive").absolute()
    progress: list[dict[str, object]] = []

    first = import_profiled_training_observation_manifest_shard_to_challenger_archive_v1(
        manifest_path=built.manifest_path,
        manifest_hmac_key=manifest_support.AUTH_KEY,
        manifest_auth_key_id=manifest_support.AUTH_KEY_ID,
        expected_manifest_id=built.manifest_id,
        expected_observation_time=built.observation_time,
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=labels,
        challenger_archive_root=challenger_archive,
        progress_consumer=lambda report: progress.append(dict(report)),
    )

    assert first["imported_rows"] == 1
    assert first["duplicate_rows"] == 0
    assert first["source_admitted_entry_count"] == 1
    assert first["completed"] is True
    assert first["prediction_authorized"] is False
    assert len(progress) == 1
    assert progress[0]["checkpoint_path"] == first["checkpoint_path"]
    snapshot = next(iter_snapshots(challenger_archive, limit=1))
    assert _row_reject_reasons(snapshot) == []

    resumed = import_profiled_training_observation_manifest_shard_to_challenger_archive_v1(
        manifest_path=built.manifest_path,
        manifest_hmac_key=manifest_support.AUTH_KEY,
        manifest_auth_key_id=manifest_support.AUTH_KEY_ID,
        expected_manifest_id=built.manifest_id,
        expected_observation_time=built.observation_time,
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=labels,
        challenger_archive_root=challenger_archive,
    )
    assert resumed["shards_processed_this_run"] == 0
    assert resumed["completed"] is True


def test_manifest_shard_importer_reuses_prior_feature_record_with_new_label_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later label-observation receipt cannot rewrite an immutable feature row."""

    evidence = base_support._build_evidence(tmp_path / "base")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    ledger, labels, observation, cost_root = manifest_support._setup_sources(
        source_root,
        evidence,
    )
    trusted_now = max(
        datetime.now(tz=UTC) + timedelta(days=1),
        datetime(2026, 7, 23, tzinfo=UTC),
    )
    monkeypatch.setattr(
        manifest_support.manifest_module,
        "_factory_wall_clock_now",
        lambda: trusted_now,
    )
    first_manifest = manifest_support.build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=labels,
        manifest_root=(tmp_path / "first-manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=manifest_support.AUTH_KEY_ID,
        hmac_key=manifest_support.AUTH_KEY,
    )
    clone_path = (tmp_path / "canonical-label-clone.sqlite3").absolute()
    source_connection = sqlite3.connect(f"file:{labels.path}?mode=ro", uri=True)
    target_connection = sqlite3.connect(str(clone_path))
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    cloned_labels = manifest_support.DurableCanonical5mLabelArchive(clone_path)
    second_manifest = manifest_support.build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=cloned_labels,
        manifest_root=(tmp_path / "second-manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=manifest_support.AUTH_KEY_ID,
        hmac_key=manifest_support.AUTH_KEY,
    )
    challenger_archive = (tmp_path / "challenger-archive").absolute()

    first = import_profiled_training_observation_manifest_shard_to_challenger_archive_v1(
        manifest_path=first_manifest.manifest_path,
        manifest_hmac_key=manifest_support.AUTH_KEY,
        manifest_auth_key_id=manifest_support.AUTH_KEY_ID,
        expected_manifest_id=first_manifest.manifest_id,
        expected_observation_time=first_manifest.observation_time,
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=labels,
        challenger_archive_root=challenger_archive,
    )
    second = import_profiled_training_observation_manifest_shard_to_challenger_archive_v1(
        manifest_path=second_manifest.manifest_path,
        manifest_hmac_key=manifest_support.AUTH_KEY,
        manifest_auth_key_id=manifest_support.AUTH_KEY_ID,
        expected_manifest_id=second_manifest.manifest_id,
        expected_observation_time=second_manifest.observation_time,
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=cloned_labels,
        challenger_archive_root=challenger_archive,
        checkpoint_path=challenger_archive / "clone-label-receipt-checkpoint.json",
    )

    assert first["imported_rows"] == 1
    assert second["imported_rows"] == 0
    assert second["duplicate_rows"] == 1
    assert len(list(iter_snapshots(challenger_archive))) == 1


def test_sharded_importer_checkpoints_completed_cursor_without_reprocessing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = base_support._build_evidence(tmp_path / "base")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    ledger, labels, observation, cost_root = manifest_support._setup_sources(
        source_root,
        evidence,
    )
    challenger_archive = tmp_path / "sharded-challenger-archive"
    challenger_archive.mkdir()
    progress: list[dict[str, object]] = []
    integrity, reused, integrity_path = importer._load_or_verify_label_integrity(
        challenger_archive_root=challenger_archive,
        label_archive=labels,
    )
    assert integrity["archive_integrity_verified"] is True
    assert reused is False
    assert integrity_path.is_file()
    monkeypatch.setattr(
        importer,
        "write_checksum_manifest",
        lambda _root: (_ for _ in ()).throw(AssertionError("global checksum scan")),
    )
    monkeypatch.setattr(
        labels,
        "verify_integrity",
        lambda: (_ for _ in ()).throw(AssertionError("full label integrity scan")),
    )

    first = import_profiled_training_ledger_shards_to_challenger_archive_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=labels,
        challenger_archive_root=challenger_archive,
        training_observed_at=observation,
        shard_size=1,
        max_shards=2,
        progress_consumer=lambda report: progress.append(dict(report)),
    )

    assert first["total_imported_rows"] == 1
    assert first["shards_processed_this_run"] == 1
    assert first["completed"] is True
    assert len(progress) == 1
    assert progress[0]["imported_rows"] == 1
    assert progress[0]["checkpoint_path"] == first["checkpoint_path"]
    assert progress[0]["label_integrity_checkpoint_reused"] is True
    assert progress[0]["shards_remaining"] == 0

    resumed = import_profiled_training_ledger_shards_to_challenger_archive_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=labels,
        challenger_archive_root=challenger_archive,
        training_observed_at=observation,
        shard_size=1,
    )

    assert resumed["completed"] is True
    assert resumed["shards_processed_this_run"] == 0
