from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.cli import v2_candidate_outcome_dataset_builder as builder
from v2.backend.app.cli.v2_candidate_outcome_dataset_builder import (
    CandidateOutcomeDatasetBuilderError,
    _archive_reader,
    _canonical_bytes,
    _write_immutable,
    build_once,
    finalize_signed_build_receipt,
)
from v2.backend.app.services.adaptive_system import (
    candidate_outcome_serving_dataset_v2 as serving_dataset,
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


def test_build_once_verifies_signed_archive_and_durable_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    writer, _, public_key_hex = _writer(archive_path)
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
    monkeypatch.setattr(
        builder,
        "PINNED_BASE_DATASET_FILE_SHA256",
        builder._sha256_bytes(base_path.read_bytes()),
    )
    monkeypatch.setattr(
        builder,
        "PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX",
        public_key_hex,
    )
    monkeypatch.setattr(
        serving_dataset,
        "PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX",
        public_key_hex,
    )

    dataset, manifest, parity, receipt = build_once(
        base_dataset_path=base_path,
        candidate_archive_path=archive_path,
        feature_archive_root=feature_root,
    )
    repeated = build_once(
        base_dataset_path=base_path,
        candidate_archive_path=archive_path,
        feature_archive_root=feature_root,
    )

    assert repeated == (dataset, manifest, parity, receipt)
    assert receipt["status"] == "PASS"
    assert receipt["candidate_records_fully_accounted"] is True
    assert receipt["candidate_archive_verification"]["verified"] is True
    assert receipt["paper_only"] is True
    assert receipt["live_gate"] == "blocked_human_only"
    assert receipt["routes_to_live"] is False
    assert receipt["places_real_order"] is False
    assert receipt["exchange_action_taken"] is False
    assert receipt["generated_at"] == max(
        row["label_available_at"] for row in dataset["rows"]
    )
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


def test_read_only_archive_has_no_signer_or_append_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = (tmp_path / "candidate-outcomes.jsonl").resolve()
    writer, _, public_key_hex = _writer(path)
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

    monkeypatch.setattr(
        builder,
        "PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX",
        public_key_hex,
    )
    reader = _archive_reader(path)

    assert isinstance(reader, CandidateOutcomeArchiveV2)
    with pytest.raises(CandidateOutcomeArchiveError, match="signer_required"):
        reader.append(first, signed_at_ms=first.record_available_at_ms + 1)


def test_archive_reader_rejects_self_signed_alternate_key(tmp_path: Path) -> None:
    path = (tmp_path / "candidate-outcomes.jsonl").resolve()
    writer, _, public_key_hex = _writer(path)
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

    with pytest.raises(
        CandidateOutcomeDatasetBuilderError,
        match="PUBLIC_KEY_UNTRUSTED",
    ):
        _archive_reader(path)
    assert public_key_hex != "bbff6e85cd6954ae5aff4ee2ec5d2078de96bf8f8750aaa889d2ea4712c5b4d9"


def _receipt_signer() -> tuple[bytes, Ed25519PrivateKey, str]:
    private_seed = bytes(range(32))
    private_key = Ed25519PrivateKey.from_private_bytes(private_seed)
    public_key_hex = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    return private_seed, private_key, public_key_hex


def _unsigned_v3_receipt() -> dict[str, object]:
    return {
        "schema_version": builder.SCHEMA_VERSION,
        "generated_at": "2026-07-28T12:00:00Z",
        "status": "PASS",
        "source_high_watermark_sha256": "a" * 64,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _artifact_hashes() -> dict[str, str]:
    return {
        "adaptive_serving_compatible_dataset_v2.json": "1" * 64,
        "adaptive_serving_compatible_dataset_manifest_v2.json": "2" * 64,
        "adaptive_train_serve_feature_parity_report_v2.json": "3" * 64,
    }


def test_signed_build_receipt_is_byte_deterministic_idempotent_and_secret_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_seed, _, public_key_hex = _receipt_signer()
    monkeypatch.setattr(
        builder,
        "PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX",
        public_key_hex,
    )
    credentials_directory = tmp_path / "credentials"
    credentials_directory.mkdir()
    credential_path = credentials_directory / builder.RECEIPT_SIGNING_CREDENTIAL_NAME
    credential_path.write_bytes(private_seed)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials_directory))
    private_key, loaded_public_key_hex = builder._load_receipt_signing_key()
    assert loaded_public_key_hex == public_key_hex

    first = finalize_signed_build_receipt(
        _unsigned_v3_receipt(),
        artifact_file_sha256s=_artifact_hashes(),
        signer=private_key.sign,
        writer_public_key_hex=public_key_hex,
    )
    second = finalize_signed_build_receipt(
        _unsigned_v3_receipt(),
        artifact_file_sha256s=_artifact_hashes(),
        signer=private_key.sign,
        writer_public_key_hex=public_key_hex,
    )
    first_bytes = _canonical_bytes(first, pretty=True)
    second_bytes = _canonical_bytes(second, pretty=True)

    assert first == second
    assert first_bytes == second_bytes
    assert private_seed not in first_bytes
    assert private_seed.hex().encode("ascii") not in first_bytes
    assert first["paper_only"] is True
    assert first["live_gate"] == "blocked_human_only"
    assert first["routes_to_live"] is False
    assert first["places_real_order"] is False
    assert first["exchange_action_taken"] is False

    target = tmp_path / "candidate_outcome_dataset_build_receipt_v3.json"
    first_sha = _write_immutable(target, first)
    second_sha = _write_immutable(target, second)
    assert first_sha == second_sha
    assert target.read_bytes() == first_bytes


def test_signed_build_receipt_rejects_alternate_self_signed_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, trusted_private, trusted_public_hex = _receipt_signer()
    alternate_private = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    alternate_public_hex = (
        alternate_private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    monkeypatch.setattr(
        builder,
        "PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX",
        trusted_public_hex,
    )

    with pytest.raises(
        CandidateOutcomeDatasetBuilderError,
        match="PINNED_KEY_REQUIRED",
    ):
        finalize_signed_build_receipt(
            _unsigned_v3_receipt(),
            artifact_file_sha256s=_artifact_hashes(),
            signer=alternate_private.sign,
            writer_public_key_hex=alternate_public_hex,
        )

    with pytest.raises(
        CandidateOutcomeDatasetBuilderError,
        match="SIGNATURE_DOES_NOT_MATCH_PINNED_KEY",
    ):
        finalize_signed_build_receipt(
            _unsigned_v3_receipt(),
            artifact_file_sha256s=_artifact_hashes(),
            signer=alternate_private.sign,
            writer_public_key_hex=trusted_public_hex,
        )

    trusted = finalize_signed_build_receipt(
        _unsigned_v3_receipt(),
        artifact_file_sha256s=_artifact_hashes(),
        signer=trusted_private.sign,
        writer_public_key_hex=trusted_public_hex,
    )
    assert trusted["receipt_writer_public_key_hex"] == trusted_public_hex
