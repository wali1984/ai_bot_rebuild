from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from v2.backend.app.cli.v2_candidate_outcome_dataset_builder import (
    CandidateOutcomeDatasetBuilderError,
    _archive_reader,
    build_once,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
    CandidateOutcomeArchiveError,
    CandidateOutcomeArchiveV2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_serving_dataset_v2 import (
    build_candidate_outcome_row,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    append_snapshot,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_archive_v2 import (
    _writer,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_serving_dataset_v2 import (
    _base_dataset,
    _matured_record,
)


def test_build_once_verifies_signed_archive_and_durable_snapshot(tmp_path: Path) -> None:
    matured, snapshot = _matured_record()
    first = replace(
        matured,
        archive_record_id=f"{matured.decision.candidate_id}-decision",
        archive_sequence=1,
        matured_labels=None,
        previous_archive_record_sha256=None,
        record_generated_at_ms=matured.decision.record_available_at_ms,
        record_available_at_ms=matured.decision.record_available_at_ms,
    )
    assert matured.previous_archive_record_sha256 == first.content_sha256()
    archive_path = (tmp_path / "candidate-outcomes.jsonl").resolve()
    writer, _, _ = _writer(archive_path)
    writer.append(first, signed_at_ms=first.record_available_at_ms)
    writer.append(matured, signed_at_ms=matured.record_available_at_ms)
    feature_root = (tmp_path / "features").resolve()
    append_snapshot(snapshot, root=feature_root, update_checksum_manifest=False)
    template = build_candidate_outcome_row(
        matured,
        snapshot_loader=lambda _snapshot_id: snapshot,
        source_archive_chain_sha256=writer.verify().terminal_chain_sha256,
    )
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps(_base_dataset(template)), encoding="utf-8")

    dataset, manifest, parity, receipt = build_once(
        base_dataset_path=base_path,
        candidate_archive_path=archive_path,
        feature_archive_root=feature_root,
    )

    assert receipt["status"] == "PASS"
    assert receipt["candidate_records_fully_accounted"] is True
    assert receipt["candidate_archive_verification"]["verified"] is True
    assert manifest["source_high_watermark"]["candidate_archive_candidate_count"] == 1
    assert any(row.get("candidate_id") == matured.decision.candidate_id for row in dataset["rows"])
    assert parity["activation_eligible"] is False


def test_archive_reader_rejects_untrusted_writer(tmp_path: Path) -> None:
    path = (tmp_path / "candidate-outcomes.jsonl").resolve()
    path.write_text(
        json.dumps(
            {
                "writer_id": "untrusted",
                "writer_public_key_hex": "a" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CandidateOutcomeDatasetBuilderError, match="WRITER_ID_UNTRUSTED"):
        _archive_reader(path)


def test_read_only_archive_has_no_signer_or_append_authority(tmp_path: Path) -> None:
    path = (tmp_path / "candidate-outcomes.jsonl").resolve()
    writer, _, _ = _writer(path)
    matured, _ = _matured_record()
    first = replace(
        matured,
        archive_record_id=f"{matured.decision.candidate_id}-decision",
        archive_sequence=1,
        matured_labels=None,
        previous_archive_record_sha256=None,
        record_generated_at_ms=matured.decision.record_available_at_ms,
        record_available_at_ms=matured.decision.record_available_at_ms,
    )
    writer.append(first, signed_at_ms=first.record_available_at_ms)

    reader = _archive_reader(path)

    assert isinstance(reader, CandidateOutcomeArchiveV2)
    with pytest.raises(CandidateOutcomeArchiveError, match="signer_required"):
        reader.append(first, signed_at_ms=first.record_available_at_ms + 1)
