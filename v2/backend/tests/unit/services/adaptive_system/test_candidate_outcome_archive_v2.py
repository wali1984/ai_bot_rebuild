from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
    ARCHIVE_COVERAGE_SCHEMA_VERSION,
    ARCHIVE_RECEIPT_SCHEMA_VERSION,
    GENESIS_CHAIN_SHA256,
    CandidateOutcomeArchiveError,
    CandidateOutcomeArchiveV2,
)
from v2.backend.tests.unit.contracts.runtime_v2.test_candidate_decision_outcome_v2 import (
    _archive,
    _decision,
    _labels,
    _sha,
)


def _key_material() -> tuple[Ed25519PrivateKey, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key_hex = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )
    return private_key, public_key_hex


def _writer(
    path: Path,
    *,
    private_key: Ed25519PrivateKey | None = None,
    public_key_hex: str | None = None,
) -> tuple[CandidateOutcomeArchiveV2, Ed25519PrivateKey, str]:
    generated_private, generated_public = _key_material()
    private_key = private_key or generated_private
    public_key_hex = public_key_hex or generated_public
    return (
        CandidateOutcomeArchiveV2(
            archive_path=path,
            writer_id="candidate-outcome-writer-v2",
            writer_public_key_hex=public_key_hex,
            signer=private_key.sign,
        ),
        private_key,
        public_key_hex,
    )


def _revision_pair():
    first = _archive()
    decision = first.decision
    second = _archive(
        decision,
        _labels(decision),
        previous_archive_record_sha256=first.content_sha256(),
    )
    return first, second


def test_empty_archive_verifies_fail_closed_metadata(tmp_path: Path) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    status = archive.verify()
    assert status.verified is True
    assert status.row_count == 0
    assert status.terminal_chain_sha256 == GENESIS_CHAIN_SHA256
    assert status.exchange_action_taken is False


def test_append_decision_is_signed_fsynced_and_verifiable(tmp_path: Path) -> None:
    path = tmp_path / "candidate-outcomes.jsonl"
    archive, _, _ = _writer(path)
    first = _archive()
    receipt = archive.append(first, signed_at_ms=1_100_000)
    assert receipt.schema_version == ARCHIVE_RECEIPT_SCHEMA_VERSION
    assert receipt.record_content_sha256 == first.content_sha256()
    assert len(receipt.signature_hex) == 128
    assert receipt.idempotent_replay is False
    assert receipt.paper_only is True
    assert receipt.routes_to_live is False
    status = archive.verify()
    assert status.row_count == 1
    assert status.decision_revision_count == 1
    assert status.matured_revision_count == 0


def test_idempotent_retry_returns_original_receipt_without_duplicate(tmp_path: Path) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    first = _archive()
    original = archive.append(first, signed_at_ms=1_100_000)
    replay = archive.append(first, signed_at_ms=1_200_000)
    assert replay.receipt_id == original.receipt_id
    assert replay.signature_hex == original.signature_hex
    assert replay.signed_at_ms == original.signed_at_ms
    assert replay.idempotent_replay is True
    assert archive.verify().row_count == 1


def test_append_many_verifies_prefix_once_and_preserves_per_record_chain(tmp_path: Path) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    first = _archive()
    second = _archive(
        _decision(candidate_id="candidate-2"),
        archive_record_id="candidate-2-decision",
    )
    receipts = archive.append_many((first, second), signed_at_ms=1_100_000)
    assert len(receipts) == 2
    assert receipts[0].idempotent_replay is False
    assert receipts[1].idempotent_replay is False
    assert receipts[0].chain_sha256 != receipts[1].chain_sha256
    status = archive.verify()
    assert status.row_count == 2
    assert status.candidate_count == 2

    replay = archive.append_many((first, second), signed_at_ms=1_200_000)
    assert all(receipt.idempotent_replay is True for receipt in replay)
    assert archive.verify().row_count == 2


def test_append_many_validation_failure_writes_no_partial_batch(tmp_path: Path) -> None:
    path = tmp_path / "candidate-outcomes.jsonl"
    archive, _, _ = _writer(path)
    first = _archive()
    invalid_second = _archive(
        _decision(candidate_id="candidate-2"),
        _labels(_decision(candidate_id="candidate-2")),
        archive_record_id="candidate-2-matured",
        previous_archive_record_sha256=_sha("missing-predecessor"),
    )
    with pytest.raises(
        CandidateOutcomeArchiveError,
        match="candidate_compare_and_swap_sequence_mismatch",
    ):
        archive.append_many((first, invalid_second), signed_at_ms=2_000_000)
    assert archive.verify().row_count == 0


def test_idempotency_key_collision_fails_closed(tmp_path: Path) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    first = _archive()
    archive.append(first, signed_at_ms=1_100_000)
    other = _archive(
        _decision(candidate_id="candidate-2"),
        archive_record_id=first.archive_record_id,
    )
    with pytest.raises(CandidateOutcomeArchiveError, match="idempotency_key_content_collision"):
        archive.append(other, signed_at_ms=1_100_000)


def test_matured_revision_uses_exact_candidate_compare_and_swap(tmp_path: Path) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    first, second = _revision_pair()
    archive.append(first, signed_at_ms=1_100_000)
    receipt = archive.append(second, signed_at_ms=2_000_000)
    assert receipt.archive_sequence == 2
    status = archive.verify()
    assert status.row_count == 2
    assert status.candidate_count == 1
    assert status.matured_revision_count == 1


def test_matured_revision_without_predecessor_fails_closed(tmp_path: Path) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    _, second = _revision_pair()
    with pytest.raises(
        CandidateOutcomeArchiveError,
        match="candidate_compare_and_swap_sequence_mismatch",
    ):
        archive.append(second, signed_at_ms=2_000_000)


def test_wrong_predecessor_hash_and_changed_decision_fail_closed(tmp_path: Path) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    first = _archive()
    archive.append(first, signed_at_ms=1_100_000)
    wrong_hash = _archive(first.decision, _labels(first.decision))
    with pytest.raises(CandidateOutcomeArchiveError, match="compare_and_swap_hash_mismatch"):
        archive.append(wrong_hash, signed_at_ms=2_000_000)
    changed_decision = _decision(
        prediction_id="prediction-2",
        prediction_sha256=_sha("prediction-2"),
    )
    changed = _archive(
        changed_decision,
        _labels(changed_decision),
        previous_archive_record_sha256=first.content_sha256(),
    )
    with pytest.raises(CandidateOutcomeArchiveError, match="decision_snapshot_changed"):
        archive.append(changed, signed_at_ms=2_000_000)


def test_signer_must_match_pinned_public_key(tmp_path: Path) -> None:
    signing_key, _ = _key_material()
    _, other_public = _key_material()
    archive, _, _ = _writer(
        tmp_path / "candidate-outcomes.jsonl",
        private_key=signing_key,
        public_key_hex=other_public,
    )
    with pytest.raises(CandidateOutcomeArchiveError, match="signature_does_not_match"):
        archive.append(_archive(), signed_at_ms=1_100_000)


def test_read_only_verifier_needs_no_private_key_but_cannot_append(tmp_path: Path) -> None:
    path = tmp_path / "candidate-outcomes.jsonl"
    writer, _, public_key_hex = _writer(path)
    writer.append(_archive(), signed_at_ms=1_100_000)
    verifier = CandidateOutcomeArchiveV2(
        archive_path=path,
        writer_id="candidate-outcome-writer-v2",
        writer_public_key_hex=public_key_hex,
        signer=None,
    )
    assert verifier.verify().verified is True
    with pytest.raises(CandidateOutcomeArchiveError, match="external_signer_required"):
        verifier.append(_archive(), signed_at_ms=1_100_000)


def test_record_payload_tamper_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "candidate-outcomes.jsonl"
    archive, _, _ = _writer(path)
    archive.append(_archive(), signed_at_ms=1_100_000)
    row = json.loads(path.read_text(encoding="utf-8"))
    row["record"]["decision"]["symbol"] = "TAMPERUSDT"
    path.write_text(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(CandidateOutcomeArchiveError, match="record_content_sha256_mismatch"):
        archive.verify()


def test_signature_and_chain_tamper_are_detected(tmp_path: Path) -> None:
    signature_path = tmp_path / "signature.jsonl"
    archive, _, _ = _writer(signature_path)
    archive.append(_archive(), signed_at_ms=1_100_000)
    row = json.loads(signature_path.read_text(encoding="utf-8"))
    row["signature_hex"] = "0" * 128
    signature_path.write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CandidateOutcomeArchiveError, match="signature_invalid"):
        archive.verify()

    chain_path = tmp_path / "chain.jsonl"
    chain_archive, _, _ = _writer(chain_path)
    chain_archive.append(_archive(), signed_at_ms=1_100_000)
    chain_row = json.loads(chain_path.read_text(encoding="utf-8"))
    chain_row["chain_sha256"] = _sha("forged-chain")
    chain_path.write_text(
        json.dumps(chain_row, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CandidateOutcomeArchiveError, match="chain_sha256_mismatch"):
        chain_archive.verify()


def test_partial_json_row_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "candidate-outcomes.jsonl"
    archive, _, _ = _writer(path)
    path.write_text('{"partial":', encoding="utf-8")
    with pytest.raises(CandidateOutcomeArchiveError, match="invalid_or_partial_json"):
        archive.verify()


def test_coverage_reports_exact_missing_and_unexpected_ids(tmp_path: Path) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    first, second = _revision_pair()
    archive.append(first, signed_at_ms=1_100_000)
    missing = archive.coverage(
        expected_candidate_ids=("candidate-1", "candidate-2"),
        eligible_matured_candidate_ids=("candidate-1",),
    )
    assert missing.schema_version == ARCHIVE_COVERAGE_SCHEMA_VERSION
    assert missing.candidate_recording_coverage == 0.5
    assert missing.eligible_matured_label_coverage == 0.0
    assert missing.missing_candidate_ids == ("candidate-2",)
    assert missing.unexplained_candidate_drops == 2
    assert missing.unexplained_candidate_drops_zero is False

    archive.append(second, signed_at_ms=2_000_000)
    complete = archive.coverage(
        expected_candidate_ids=("candidate-1",),
        eligible_matured_candidate_ids=("candidate-1",),
    )
    assert complete.candidate_recording_coverage_100_percent is True
    assert complete.matured_label_coverage_100_percent is True
    assert complete.unexplained_candidate_drops_zero is True


def test_coverage_rejects_post_hoc_unexpected_matured_records(tmp_path: Path) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    first, second = _revision_pair()
    archive.append(first, signed_at_ms=1_100_000)
    archive.append(second, signed_at_ms=2_000_000)
    status = archive.coverage(
        expected_candidate_ids=("candidate-1",),
        eligible_matured_candidate_ids=(),
    )
    assert status.unexpected_matured_candidate_ids == ("candidate-1",)
    assert status.matured_label_coverage_100_percent is False


def test_coverage_input_universe_must_be_sorted_and_unique(tmp_path: Path) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    with pytest.raises(CandidateOutcomeArchiveError, match="must_be_sorted_unique_tuple"):
        archive.coverage(
            expected_candidate_ids=("candidate-2", "candidate-1"),
            eligible_matured_candidate_ids=(),
        )


def test_archive_path_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "linked.jsonl"
    link.symlink_to(target)
    archive, _, _ = _writer(link)
    with pytest.raises(CandidateOutcomeArchiveError, match="symlink_path_forbidden"):
        archive.verify()


def test_archive_path_must_be_absolute() -> None:
    private_key, public_key_hex = _key_material()
    with pytest.raises(
        CandidateOutcomeArchiveError,
        match="must_be_absolute_without_parent_traversal",
    ):
        CandidateOutcomeArchiveV2(
            archive_path=Path("relative/candidate-outcomes.jsonl"),
            writer_id="candidate-outcome-writer-v2",
            writer_public_key_hex=public_key_hex,
            signer=private_key.sign,
        )


def test_archive_parent_symlink_is_rejected(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    archive, _, _ = _writer(linked_parent / "candidate-outcomes.jsonl")
    with pytest.raises(CandidateOutcomeArchiveError, match="symlink_parent_forbidden"):
        archive.verify()
