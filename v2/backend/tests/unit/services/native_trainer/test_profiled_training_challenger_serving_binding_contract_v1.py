"""Corpus-contract tests: the profiled ledger -> challenger archive -> serving
dataset path must carry the RICH finalized label binding so authenticated rows
actually reach ``build_serving_dataset_v2`` training.

Deliverables covered:
1. The serving builder requires ``directional_cost_evidence`` in the binding
   (the pre-fix sparse ``profiled_training_challenger_label_binding_v1`` was
   rejected with ``COST_EVIDENCE_MISSING``).
2/3. The shards importer now emits the rich
   ``profiled_training_finalized_label_binding_v1`` and its row is admitted by
   ``build_serving_dataset_v2._build_row``; a genuinely label-missing row still
   rejects (true negative).
4. A label archive appended-to between proof capture and verification still
   verifies via a fresh per-read re-proof rather than fail-closing stale.

None of these relaxes a PIT or receipt-commitment rule: the rich binding copies
the sample's own authenticated cost evidence and the fully re-verified canonical
label path into the schema the serving builder consumes.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    iter_snapshots,
)
from v2.backend.app.services.native_trainer.profiled_training_challenger_importer_v1 import (
    import_profiled_training_ledger_shards_to_challenger_archive_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    load_profiled_training_ledger_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    ProfiledTrainingObservationManifestV1Error,
    build_finalized_label_binding_v1,
    derive_label_archive_fixed_observation_proof_v1,
)
from v2.backend.app.services.prediction_serving.serving_dataset_v2 import _build_row
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_model_feature_snapshot_record_v1 as base_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_observation_manifest_v1 as manifest_support,
)

RICH_BINDING_SCHEMA = "profiled_training_finalized_label_binding_v1"


def _sources(tmp_path: Path, *, label_rows: int = 49):
    evidence = base_support._build_evidence(tmp_path / "base")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    return manifest_support._setup_sources(source_root, evidence, label_rows=label_rows)


def _import_single_row(tmp_path: Path):
    ledger, labels, observation, cost_root = _sources(tmp_path)
    challenger_archive = tmp_path / "challenger-archive"
    result = import_profiled_training_ledger_shards_to_challenger_archive_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=labels,
        challenger_archive_root=challenger_archive,
        training_observed_at=observation,
        shard_size=1,
        max_shards=4,
    )
    assert result["total_imported_rows"] == 1, result
    snapshot = next(iter_snapshots(challenger_archive, limit=1))
    return snapshot


def _identity(snapshot):
    return {
        "snapshot_id": snapshot["snapshot_id"],
        "content_sha256": snapshot["content_sha256"],
        "row_identity": snapshot["snapshot_id"],
    }


def test_shards_importer_emits_rich_finalized_binding(tmp_path: Path) -> None:
    snapshot = _import_single_row(tmp_path)
    binding = snapshot["label_binding"]
    assert binding["schema_version"] == RICH_BINDING_SCHEMA
    assert isinstance(binding["directional_cost_evidence"], dict)
    assert {"long_net_bps", "short_net_bps"} <= set(binding["directional_cost_evidence"])
    assert binding["label_target_action"] in {"long", "short", "hold"}
    assert binding["future_labels_not_in_feature_tensor"] is True
    # The authenticated cost/label receipts are carried through unchanged.
    assert binding["directional_cost_evidence_sha256"]
    assert binding["label_append_receipt_sha256s"]
    assert binding["label_postcommit_receipt_sha256s"]


def test_shards_importer_row_now_reaches_serving_build_row(tmp_path: Path) -> None:
    # Before the fix this raised ValueError('COST_EVIDENCE_MISSING'); the row now
    # carries the rich binding so the serving dataset builder admits it.
    snapshot = _import_single_row(tmp_path)
    row = _build_row(_identity(snapshot), snapshot)
    assert row["target_action"] in {"long", "short", "hold"}
    assert isinstance(row["long_net_bps"], float)
    assert isinstance(row["short_net_bps"], float)
    assert row["label_binding_sha256"] == snapshot["label_binding"]["label_binding_sha256"]
    assert row["cost_evidence_sha256"] == (
        snapshot["label_binding"]["directional_cost_evidence_sha256"]
    )


def test_serving_build_row_requires_directional_cost_evidence_in_binding(
    tmp_path: Path,
) -> None:
    # Documents the exact schema gap the fix closes: the pre-fix sparse binding
    # had no directional_cost_evidence. Stripping it from an otherwise valid
    # feature-complete record reproduces the original COST_EVIDENCE_MISSING.
    snapshot = _import_single_row(tmp_path)
    sparse = dict(snapshot)
    sparse["label_binding"] = {
        key: value
        for key, value in snapshot["label_binding"].items()
        if key != "directional_cost_evidence"
    }
    with pytest.raises(ValueError, match="COST_EVIDENCE_MISSING"):
        _build_row(_identity(snapshot), sparse)


def test_label_missing_row_still_rejects(tmp_path: Path) -> None:
    # True negative: an authenticated sample whose canonical 5m label path is not
    # yet finalized (horizon needs 3 candles; only 2 exist) is never imported and
    # therefore never reaches the serving builder.
    ledger, labels, observation, cost_root = _sources(tmp_path, label_rows=2)
    challenger_archive = tmp_path / "challenger-archive-missing"
    result = import_profiled_training_ledger_shards_to_challenger_archive_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=labels,
        challenger_archive_root=challenger_archive,
        training_observed_at=observation,
        shard_size=1,
        max_shards=4,
    )
    assert result["total_imported_rows"] == 0, result
    assert result["total_rejections_by_reason"], result
    assert list(iter_snapshots(challenger_archive)) == []


def test_finalized_label_binding_reproofs_after_append_between_capture_and_verify(
    tmp_path: Path,
) -> None:
    ledger, labels, observation, cost_root = _sources(tmp_path)
    observation_dt = datetime.fromisoformat(observation.replace("Z", "+00:00"))
    batch = load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        training_observed_at=observation,
        scan_limit=8,
        after_sequence=0,
    )
    assert len(batch.samples) == 1
    sample = batch.samples[0]

    # Capture a full integrity proof + high water.
    integrity, high_water = derive_label_archive_fixed_observation_proof_v1(
        archive=labels,
        observation=observation_dt,
    )
    assert integrity is not None and high_water is not None

    # The live archive advances (contiguous later candles) AFTER the proof was
    # captured, making the captured proof stale. The sample's immutable label
    # path (earlier candles) is unchanged.
    decision = datetime.fromisoformat(sample.decision_time.replace("Z", "+00:00"))
    slot_start = decision.replace(minute=(decision.minute // 5) * 5, second=0, microsecond=0)
    extension_start = slot_start + timedelta(minutes=5 * 49)
    labels.append_candles(
        manifest_support._label_candles(
            decision_time=extension_start.isoformat().replace("+00:00", "Z"),
            entry_price=30_000.0,
            rows=2,
        )
    )

    # With the stale captured proof, a genuine path fail-closes (control) ...
    with pytest.raises(
        ProfiledTrainingObservationManifestV1Error,
        match="MOVED_DURING_BUILD",
    ):
        build_finalized_label_binding_v1(
            sample=sample,
            archive=labels,
            observation=observation_dt,
            archive_integrity=integrity,
            archive_high_water=high_water,
            allow_fresh_reproof=False,
        )

    # ... but the per-read fresh re-proof re-verifies the still-immutable path.
    binding, reasons = build_finalized_label_binding_v1(
        sample=sample,
        archive=labels,
        observation=observation_dt,
        archive_integrity=integrity,
        archive_high_water=high_water,
    )
    assert binding is not None, reasons
    assert binding["schema_version"] == RICH_BINDING_SCHEMA
    assert isinstance(binding["directional_cost_evidence"], dict)
