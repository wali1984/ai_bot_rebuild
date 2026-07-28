from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    canonical_payload_json,
    canonical_payload_sha256,
)
from v2.backend.app.services.adaptive_system import candidate_outcome_archive_v2 as archive_module
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
    _evidence,
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


def _side_evidence(kind: str, side: str):
    evidence = _evidence(kind)
    payload = json.loads(evidence.payload_json)
    payload["side"] = side
    payload_json = canonical_payload_json(payload)
    return replace(
        evidence,
        payload_json=payload_json,
        payload_sha256=canonical_payload_sha256(payload_json),
    )


def _decision_record(
    candidate_id: str,
    *,
    decision_time_ms: int = 1_000_000,
    disposition: str = "REJECTED",
    side: str = "LONG",
):
    decision = _decision(
        candidate_id=candidate_id,
        decision_time_ms=decision_time_ms,
        record_generated_at_ms=decision_time_ms + 1,
        record_available_at_ms=decision_time_ms + 2,
        decision_disposition=disposition,
        proposed_action=_side_evidence("proposed_action", side),
        selected_action=_side_evidence("selected_action", side),
    )
    return _archive(
        decision,
        archive_record_id=f"{candidate_id}-revision-1",
        record_generated_at_ms=decision_time_ms + 3,
        record_available_at_ms=decision_time_ms + 4,
    )


def _rewrite_rows(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(
            f"{json.dumps(row, sort_keys=True, separators=(',', ':'))}\n"
            for row in rows
        ),
        encoding="utf-8",
    )


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


def test_append_many_returns_exact_post_fsync_verification(tmp_path: Path) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    first = _archive()
    second = _archive(
        _decision(candidate_id="candidate-2"),
        archive_record_id="candidate-2-decision",
    )
    receipts, appended = archive.append_many_with_verification(
        (first, second),
        signed_at_ms=1_100_000,
    )
    reread = archive.verify()
    assert len(receipts) == 2
    assert appended == reread
    assert appended.terminal_chain_sha256 == receipts[-1].chain_sha256


def test_streaming_append_preserves_receipts_cas_idempotency_and_terminal_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "candidate-outcomes.jsonl"
    archive, _, _ = _writer(path)
    first, matured = _revision_pair()
    original = archive.append(first, signed_at_ms=1_100_000)
    other = _decision_record("candidate-2")
    monkeypatch.setattr(
        archive,
        "_parse_rows",
        lambda: pytest.fail("streaming append must never materialize the prefix"),
    )

    wrong_predecessor = replace(
        matured,
        previous_archive_record_sha256="0" * 64,
    )
    with pytest.raises(
        CandidateOutcomeArchiveError,
        match="candidate_compare_and_swap_hash_mismatch",
    ):
        archive.append_many_with_verification(
            (wrong_predecessor, other),
            signed_at_ms=2_000_000,
        )
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1

    receipts, terminal = archive.append_many_with_verification(
        (matured, other),
        signed_at_ms=2_000_000,
    )

    assert [receipt.archive_sequence for receipt in receipts] == [2, 1]
    assert receipts[0].record_content_sha256 == matured.content_sha256()
    assert receipts[1].record_content_sha256 == other.content_sha256()
    assert receipts[0].idempotent_replay is False
    assert receipts[1].idempotent_replay is False
    assert terminal.row_count == 3
    assert terminal.decision_revision_count == 2
    assert terminal.matured_revision_count == 1
    assert terminal.candidate_count == 2
    assert terminal.terminal_chain_sha256 == receipts[-1].chain_sha256
    assert terminal.paper_only is True
    assert terminal.live_gate == "blocked_human_only"
    assert terminal.routes_to_live is False
    assert terminal.places_real_order is False
    assert terminal.exchange_action_taken is False

    streamed_terminal, _ = archive._verify_rows_and_select(
        archive._iter_rows(),
        validate_nested_contracts=True,
    )
    assert terminal == streamed_terminal

    replay, replay_terminal = archive.append_many_with_verification(
        (first, matured, other),
        signed_at_ms=2_100_000,
    )
    assert [receipt.receipt_id for receipt in replay] == [
        original.receipt_id,
        receipts[0].receipt_id,
        receipts[1].receipt_id,
    ]
    assert [receipt.signature_hex for receipt in replay] == [
        original.signature_hex,
        receipts[0].signature_hex,
        receipts[1].signature_hex,
    ]
    assert [receipt.signed_at_ms for receipt in replay] == [
        original.signed_at_ms,
        receipts[0].signed_at_ms,
        receipts[1].signed_at_ms,
    ]
    assert all(receipt.idempotent_replay is True for receipt in replay)
    assert replay_terminal == terminal
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


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


def test_matured_revision_uses_exact_candidate_compare_and_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    first, second = _revision_pair()
    archive.append(first, signed_at_ms=1_100_000)
    receipt = archive.append(second, signed_at_ms=2_000_000)
    assert receipt.archive_sequence == 2
    status = archive.verify()
    assert status.row_count == 2
    assert status.candidate_count == 1
    assert status.matured_revision_count == 1

    records = archive.read_verified_records()
    assert records == (first, second)
    parse_count = 0
    parse_rows = archive._parse_rows

    def counted_parse_rows():
        nonlocal parse_count
        parse_count += 1
        return parse_rows()

    monkeypatch.setattr(archive, "_parse_rows", counted_parse_rows)
    verification, latest = archive.read_verified_records_with_verification(
        latest_only=True
    )
    assert parse_count == 1
    assert verification.row_count == 2
    assert verification.terminal_chain_sha256 != GENESIS_CHAIN_SHA256
    assert latest == (second,)


def test_sequence_filtered_read_stream_verifies_all_rows_and_retains_only_matured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    first, second = _revision_pair()
    archive.append(first, signed_at_ms=1_100_000)
    archive.append(second, signed_at_ms=2_000_000)
    monkeypatch.setattr(
        archive,
        "_parse_rows",
        lambda: pytest.fail("streaming filtered read must not materialize every row"),
    )

    verification, records = (
        archive.read_verified_records_by_sequence_with_verification(
            archive_sequences=(2,)
        )
    )

    assert verification.row_count == 2
    assert verification.decision_revision_count == 1
    assert verification.matured_revision_count == 1
    assert verification.candidate_count == 1
    assert records == (second,)


def test_projected_snapshot_stream_binds_exact_copy_receipt_and_rejects_valid_prefix(
    tmp_path: Path,
) -> None:
    source_path = (tmp_path / "candidate-outcomes.jsonl").resolve()
    source, _, public_key_hex = _writer(source_path)
    first, second = _revision_pair()
    source.append(first, signed_at_ms=1_100_000)
    source.append(second, signed_at_ms=2_000_000)
    snapshot_path = (tmp_path / "snapshot.jsonl").resolve()
    receipt = source.copy_locked_snapshot(snapshot_path)
    reader = CandidateOutcomeArchiveV2(
        archive_path=snapshot_path,
        writer_id="candidate-outcome-writer-v2",
        writer_public_key_hex=public_key_hex,
        signer=None,
    )

    verification, projections = (
        reader.read_verified_projections_by_sequence_with_verification(
            archive_sequences=(2,),
            projector=lambda record: record.decision.candidate_id,
            expected_snapshot_sha256=receipt["snapshot_sha256"],
            expected_snapshot_size_bytes=receipt["source_size_bytes"],
        )
    )
    assert verification.matured_revision_count == 1
    assert projections == (second.decision.candidate_id,)

    first_complete_signed_row = snapshot_path.read_bytes().splitlines(
        keepends=True
    )[0]
    snapshot_path.write_bytes(first_complete_signed_row)
    with pytest.raises(
        CandidateOutcomeArchiveError,
        match="expected_snapshot_binding:content_mismatch",
    ):
        reader.read_verified_projections_by_sequence_with_verification(
            archive_sequences=(2,),
            projector=lambda record: record.decision.candidate_id,
            expected_snapshot_sha256=receipt["snapshot_sha256"],
            expected_snapshot_size_bytes=receipt["source_size_bytes"],
        )


def test_maturation_stream_selects_exact_oldest_due_bounded_symmetric_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    matured_first = _decision_record("matured-candidate")
    matured_second = _archive(
        matured_first.decision,
        _labels(matured_first.decision),
        archive_record_id="matured-candidate-revision-2",
        previous_archive_record_sha256=matured_first.content_sha256(),
    )
    records = (
        _decision_record(
            "b-long-tie",
            decision_time_ms=1_200_000,
            disposition="REJECTED",
            side="LONG",
        ),
        _decision_record(
            "actual-close-required",
            decision_time_ms=1_050_000,
            disposition="SELECTED_TRADE",
            side="SHORT",
        ),
        _decision_record(
            "z-long-oldest",
            decision_time_ms=1_100_000,
            disposition="REJECTED",
            side="LONG",
        ),
        matured_first,
        _decision_record(
            "a-short-tie",
            decision_time_ms=1_200_000,
            disposition="INFEASIBLE",
            side="SHORT",
        ),
        _decision_record(
            "late-short",
            decision_time_ms=2_200_000,
            disposition="REJECTED",
            side="SHORT",
        ),
        matured_second,
    )
    archive.append_many(records, signed_at_ms=3_000_000)
    monkeypatch.setattr(
        archive,
        "_parse_rows",
        lambda: pytest.fail("maturation stream must never materialize all rows"),
    )

    verification, selection = (
        archive.read_verified_maturation_batch_with_verification(
            signed_at_ms=3_000_000,
            max_candidates=2,
            actual_close_required_dispositions=frozenset(
                {"SELECTED_TRADE", "SELECTED_RISK_REDUCED", "SELECTED_HEDGED"}
            ),
        )
    )

    assert verification.row_count == 7
    assert verification.decision_revision_count == 6
    assert verification.matured_revision_count == 1
    assert verification.candidate_count == 6
    assert selection.horizon_due_candidate_count == 4
    assert selection.selected_actual_pending_count == 1
    assert selection.label_candidate_count == 3
    assert [record.decision.candidate_id for record in selection.records] == [
        "z-long-oldest",
        "a-short-tie",
    ]
    assert [record.decision.decision_disposition for record in selection.records] == [
        "REJECTED",
        "INFEASIBLE",
    ]
    assert [
        json.loads(record.decision.selected_action.payload_json)["side"]
        for record in selection.records
    ] == ["LONG", "SHORT"]
    assert all(record.archive_sequence == 1 for record in selection.records)
    assert all(record.paper_only is True for record in selection.records)
    assert all(record.live_gate == "blocked_human_only" for record in selection.records)
    assert all(record.routes_to_live is False for record in selection.records)
    assert all(record.places_real_order is False for record in selection.records)
    assert all(record.exchange_action_taken is False for record in selection.records)
    assert verification.paper_only is True
    assert verification.routes_to_live is False
    assert verification.places_real_order is False
    assert verification.exchange_action_taken is False


@pytest.mark.parametrize(
    ("tamper", "reason"),
    [
        ("signature", "signature_invalid"),
        ("hash", "record_content_sha256_mismatch"),
        (
            "nested",
            "nested_contract_invalid:record_generated_at_ms:must_be_positive_int",
        ),
    ],
)
def test_maturation_stream_rejects_tamper_in_unselected_row(
    tmp_path: Path,
    tamper: str,
    reason: str,
) -> None:
    path = tmp_path / f"{tamper}.jsonl"
    archive, private_key, _ = _writer(path)
    archive.append_many(
        (
            _decision_record("candidate-a"),
            _decision_record("candidate-z"),
        ),
        signed_at_ms=2_000_000,
    )
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    unselected = rows[1]
    if tamper == "signature":
        unselected["signature_hex"] = "0" * 128
    elif tamper == "hash":
        unselected["record"]["record_generated_at_ms"] = 1
    else:
        unselected["record"]["record_generated_at_ms"] = 0
        unselected["record_content_sha256"] = archive_module._sha256(
            unselected["record"]
        )
        unselected["chain_sha256"] = archive_module._chain_sha256(
            previous_chain_sha256=unselected["previous_chain_sha256"],
            row_index=unselected["row_index"],
            archive_record_id=unselected["archive_record_id"],
            candidate_id=unselected["candidate_id"],
            archive_sequence=unselected["archive_sequence"],
            record_content_sha256=unselected["record_content_sha256"],
        )
        unselected["signature_hex"] = private_key.sign(
            archive_module._signature_material(unselected)
        ).hex()
    _rewrite_rows(path, rows)

    with pytest.raises(CandidateOutcomeArchiveError, match=reason):
        archive.read_verified_maturation_batch_with_verification(
            signed_at_ms=2_000_000,
            max_candidates=1,
            actual_close_required_dispositions=frozenset({"SELECTED_TRADE"}),
        )


def test_maturation_stream_rejects_second_locked_reread_candidate_set_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    archive.append_many(
        (
            _decision_record("candidate-a"),
            _decision_record("candidate-b"),
        ),
        signed_at_ms=2_000_000,
    )
    stored_rows = tuple(archive._iter_rows())
    iteration_count = 0

    def inconsistent_locked_view():
        nonlocal iteration_count
        iteration_count += 1
        rows = stored_rows
        if iteration_count == 2:
            rows = tuple(
                row for row in rows if row["candidate_id"] != "candidate-a"
            )
        return iter(rows)

    monkeypatch.setattr(archive, "_iter_rows", inconsistent_locked_view)

    with pytest.raises(
        CandidateOutcomeArchiveError,
        match="maturation_batch:selected_candidate_set_mismatch",
    ):
        archive.read_verified_maturation_batch_with_verification(
            signed_at_ms=2_000_000,
            max_candidates=1,
            actual_close_required_dispositions=frozenset({"SELECTED_TRADE"}),
        )
    assert iteration_count == 2


def test_maturation_stream_rejects_same_id_set_nested_record_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    original = _decision_record("verified-candidate")
    archive.append(original, signed_at_ms=2_000_000)
    signed_rows = tuple(archive._iter_rows())
    substituted = json.loads(json.dumps(signed_rows[0]))
    substituted["record"] = _decision_record("unverified-candidate").to_dict()
    assert substituted["candidate_id"] == original.decision.candidate_id
    iteration_count = 0

    def substituted_locked_view():
        nonlocal iteration_count
        iteration_count += 1
        if iteration_count == 1:
            return iter(signed_rows)
        return iter((substituted,))

    monkeypatch.setattr(archive, "_iter_rows", substituted_locked_view)

    with pytest.raises(
        CandidateOutcomeArchiveError,
        match=(
            "maturation_batch\\[verified-candidate\\]:"
            "selected_record_content_hash_mismatch"
        ),
    ):
        archive.read_verified_maturation_batch_with_verification(
            signed_at_ms=2_000_000,
            max_candidates=1,
            actual_close_required_dispositions=frozenset({"SELECTED_TRADE"}),
        )
    assert iteration_count == 2


def test_large_maturation_stream_materializes_only_bounded_selected_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")
    record_count = 64
    max_candidates = 3
    archive.append_many(
        tuple(
            _decision_record(
                f"candidate-{index:03d}",
                disposition="REJECTED" if index % 2 == 0 else "INFEASIBLE",
                side="LONG" if index % 2 == 0 else "SHORT",
            )
            for index in range(record_count)
        ),
        signed_at_ms=2_000_000,
    )
    monkeypatch.setattr(
        archive,
        "_parse_rows",
        lambda: pytest.fail("large maturation stream must not materialize all rows"),
    )
    original_iter_rows = archive._iter_rows
    original_convert = archive_module.candidate_decision_outcome_from_dict
    active_pass = 0
    conversion_candidate_ids: dict[int, list[str]] = {}

    def tracked_iter_rows():
        nonlocal active_pass
        active_pass += 1
        yield from original_iter_rows()

    def tracked_convert(payload):
        conversion_candidate_ids.setdefault(active_pass, []).append(
            payload["decision"]["candidate_id"]
        )
        return original_convert(payload)

    monkeypatch.setattr(archive, "_iter_rows", tracked_iter_rows)
    monkeypatch.setattr(
        archive_module,
        "candidate_decision_outcome_from_dict",
        tracked_convert,
    )

    verification, selection = (
        archive.read_verified_maturation_batch_with_verification(
            signed_at_ms=2_000_000,
            max_candidates=max_candidates,
            actual_close_required_dispositions=frozenset({"SELECTED_TRADE"}),
        )
    )

    expected_ids = [f"candidate-{index:03d}" for index in range(max_candidates)]
    assert verification.row_count == record_count
    assert selection.horizon_due_candidate_count == record_count
    assert selection.label_candidate_count == record_count
    assert len(selection.records) == max_candidates
    assert [record.decision.candidate_id for record in selection.records] == expected_ids
    assert len(conversion_candidate_ids[1]) == record_count
    assert conversion_candidate_ids[2] == expected_ids
    assert sum(map(len, conversion_candidate_ids.values())) == (
        record_count + max_candidates
    )


def test_sequence_filtered_read_rejects_unselected_prefix_tamper(tmp_path: Path) -> None:
    path = tmp_path / "candidate-outcomes.jsonl"
    archive, _, _ = _writer(path)
    first, second = _revision_pair()
    archive.append(first, signed_at_ms=1_100_000)
    archive.append(second, signed_at_ms=2_000_000)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["signature_hex"] = "0" * 128
    path.write_text(
        "".join(
            f"{json.dumps(row, sort_keys=True, separators=(',', ':'))}\n"
            for row in rows
        ),
        encoding="utf-8",
    )

    with pytest.raises(CandidateOutcomeArchiveError, match="signature_invalid"):
        archive.read_verified_records_by_sequence_with_verification(
            archive_sequences=(2,)
        )


def test_sequence_filtered_read_rejects_resigned_nested_invalid_prefix(
    tmp_path: Path,
) -> None:
    path = tmp_path / "candidate-outcomes.jsonl"
    archive, private_key, _ = _writer(path)
    first, second = _revision_pair()
    archive.append(first, signed_at_ms=1_100_000)
    archive.append(second, signed_at_ms=2_000_000)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    rows[0]["record"]["record_generated_at_ms"] = 0
    rows[0]["record_content_sha256"] = archive_module._sha256(rows[0]["record"])
    rows[0]["chain_sha256"] = archive_module._chain_sha256(
        previous_chain_sha256=GENESIS_CHAIN_SHA256,
        row_index=1,
        archive_record_id=rows[0]["archive_record_id"],
        candidate_id=rows[0]["candidate_id"],
        archive_sequence=1,
        record_content_sha256=rows[0]["record_content_sha256"],
    )
    rows[0]["signature_hex"] = private_key.sign(
        archive_module._signature_material(rows[0])
    ).hex()

    rows[1]["record"]["previous_archive_record_sha256"] = rows[0][
        "record_content_sha256"
    ]
    rows[1]["previous_candidate_record_sha256"] = rows[0]["record_content_sha256"]
    rows[1]["record_content_sha256"] = archive_module._sha256(rows[1]["record"])
    rows[1]["previous_chain_sha256"] = rows[0]["chain_sha256"]
    rows[1]["chain_sha256"] = archive_module._chain_sha256(
        previous_chain_sha256=rows[0]["chain_sha256"],
        row_index=2,
        archive_record_id=rows[1]["archive_record_id"],
        candidate_id=rows[1]["candidate_id"],
        archive_sequence=2,
        record_content_sha256=rows[1]["record_content_sha256"],
    )
    rows[1]["signature_hex"] = private_key.sign(
        archive_module._signature_material(rows[1])
    ).hex()
    path.write_text(
        "".join(
            f"{json.dumps(row, sort_keys=True, separators=(',', ':'))}\n"
            for row in rows
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        CandidateOutcomeArchiveError,
        match="nested_contract_invalid:record_generated_at_ms:must_be_positive_int",
    ):
        archive.read_verified_records_by_sequence_with_verification(
            archive_sequences=(2,)
        )


@pytest.mark.parametrize("archive_sequences", [(), (2, 1), (2, 2), (3,), (True,)])
def test_sequence_filtered_read_requires_canonical_revision_subset(
    tmp_path: Path,
    archive_sequences: tuple[int, ...],
) -> None:
    archive, _, _ = _writer(tmp_path / "candidate-outcomes.jsonl")

    with pytest.raises(
        CandidateOutcomeArchiveError,
        match="canonical_nonempty_subset_of_1_2_required",
    ):
        archive.read_verified_records_by_sequence_with_verification(
            archive_sequences=archive_sequences
        )


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
