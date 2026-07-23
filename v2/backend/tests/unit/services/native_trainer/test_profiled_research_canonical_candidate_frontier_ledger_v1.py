from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_research_canonical_candidate_frontier_ledger_v1 as frontier,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.profiled_research_canonical_candidate_frontier_ledger_v1 import (  # noqa: E501
    CanonicalFrontierCandidateResultV1,
    CanonicalFrontierSelectionResultV1,
    ProfiledResearchCanonicalCandidateFrontierLedgerV1,
    ProfiledResearchCanonicalFrontierV1IntegrityError,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_research_finalized_outcome_ledger_v1 as outcome_support,
)


@pytest.fixture(autouse=True)
def _clear_inference_order_registry():  # noqa: ANN201
    inference = outcome_support.commitment_support.inference_support.inference
    with inference._PROCESS_SOURCE_ORDER_LOCK:  # noqa: SLF001
        inference._PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.clear()  # noqa: SLF001
    yield
    with inference._PROCESS_SOURCE_ORDER_LOCK:  # noqa: SLF001
        inference._PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.clear()  # noqa: SLF001


def _matured_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN202
    ready = outcome_support._ready_bundle(tmp_path, monkeypatch)  # noqa: SLF001
    matured = outcome_support._mature(ready)  # noqa: SLF001
    base = datetime.now(UTC) + timedelta(minutes=10)
    commitment_clocks = iter(
        base + timedelta(microseconds=index) for index in range(32)
    )
    outcome_clocks = iter(
        base + timedelta(seconds=1, microseconds=index) for index in range(32)
    )
    monkeypatch.setattr(
        outcome_support.commitment_support.commitment,
        "_utc_now",
        lambda: next(commitment_clocks),
    )
    monkeypatch.setattr(
        outcome_support.outcome,
        "_utc_now",
        lambda: next(outcome_clocks),
    )
    frontier_clocks = iter(
        base + timedelta(seconds=2, microseconds=index) for index in range(64)
    )
    monkeypatch.setattr(frontier, "_utc_now", lambda: next(frontier_clocks))
    store, commitment_ledger, committed, *_middle, outcome_ledger = ready
    ledger = ProfiledResearchCanonicalCandidateFrontierLedgerV1(
        tmp_path / "frontier.sqlite3",
        store=store,
    )
    return ledger, commitment_ledger, outcome_ledger, committed, matured


def test_seals_complete_source_pair_and_exact_model_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, commitments, outcomes, _committed, matured = _matured_bundle(
        tmp_path, monkeypatch
    )
    fingerprint = matured.outcome_contract["model_binding"][
        "model_parameter_fingerprint"
    ]

    result = ledger.seal_canonical_candidate(
        commitment_ledger=commitments,
        outcome_ledger=outcomes,
        model_parameter_fingerprint=fingerprint,
    )

    assert type(result) is CanonicalFrontierCandidateResultV1
    assert result.calibration_candidate_row_count == 1
    assert result.runtime_wired is False
    report = ledger.verify_integrity(
        commitment_ledger=commitments,
        outcome_ledger=outcomes,
    )
    assert report == {
        "status": "CANONICAL_FRONTIER_INTEGRITY_VERIFIED",
        "events_verified": 2,
        "selections_verified": 1,
        "candidates_verified": 1,
        "head_anchors_verified": 2,
        "runtime_wired": False,
    }


def test_same_source_pair_and_model_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, commitments, outcomes, _committed, matured = _matured_bundle(
        tmp_path, monkeypatch
    )
    fingerprint = matured.outcome_contract["model_binding"][
        "model_parameter_fingerprint"
    ]
    first = ledger.seal_canonical_candidate(
        commitment_ledger=commitments,
        outcome_ledger=outcomes,
        model_parameter_fingerprint=fingerprint,
    )
    second = ledger.seal_canonical_candidate(
        commitment_ledger=commitments,
        outcome_ledger=outcomes,
        model_parameter_fingerprint=fingerprint,
    )

    assert type(first) is CanonicalFrontierCandidateResultV1
    assert type(second) is CanonicalFrontierCandidateResultV1
    assert first.candidate_key_sha256 == second.candidate_key_sha256
    assert first.candidate_artifact_sha256 == second.candidate_artifact_sha256
    assert ledger.verify_integrity(
        commitment_ledger=commitments,
        outcome_ledger=outcomes,
    )["events_verified"] == 2


def test_due_missing_outcome_waits_without_consuming_candidate_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, commitments, committed = outcome_support._committed_bundle(  # noqa: SLF001
        tmp_path, monkeypatch
    )
    outcomes = outcome_support.ProfiledResearchFinalizedOutcomeLedgerV1(
        tmp_path / "outcomes.sqlite3"
    )
    outcomes.recover_pending_postcommit_readbacks(store=store)
    ledger = ProfiledResearchCanonicalCandidateFrontierLedgerV1(
        tmp_path / "frontier.sqlite3", store=store
    )
    label_at = outcome_support._clock(committed.label_earliest_available_at)  # noqa: SLF001
    commitment_snapshot_clocks = iter(
        label_at + timedelta(seconds=1, microseconds=index)
        for index in range(8)
    )
    monkeypatch.setattr(
        outcome_support.commitment_support.commitment,
        "_utc_now",
        lambda: next(commitment_snapshot_clocks),
    )
    outcome_snapshot_clocks = iter(
        label_at + timedelta(seconds=2, microseconds=index)
        for index in range(8)
    )
    monkeypatch.setattr(
        outcome_support.outcome,
        "_utc_now",
        lambda: next(outcome_snapshot_clocks),
    )
    clocks = iter(
        label_at + timedelta(seconds=3, microseconds=index)
        for index in range(8)
    )
    monkeypatch.setattr(frontier, "_utc_now", lambda: next(clocks))

    result = ledger.seal_canonical_candidate(
        commitment_ledger=commitments,
        outcome_ledger=outcomes,
        model_parameter_fingerprint=committed.hypothesis_contract[
            "raw_inference_payload"
        ]["model_parameter_fingerprint"],
    )

    assert type(result) is CanonicalFrontierSelectionResultV1
    assert result.terminal_accounting_complete is False
    assert result.due_missing_outcome_count == 1
    assert result.runtime_wired is False
    connection = sqlite3.connect(ledger.path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM frontier_candidates").fetchone()[0] == 0
    finally:
        connection.close()


def test_factory_and_database_tamper_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, commitments, outcomes, _committed, matured = _matured_bundle(
        tmp_path, monkeypatch
    )
    fingerprint = matured.outcome_contract["model_binding"][
        "model_parameter_fingerprint"
    ]
    result = ledger.seal_canonical_candidate(
        commitment_ledger=commitments,
        outcome_ledger=outcomes,
        model_parameter_fingerprint=fingerprint,
    )
    assert type(result) is CanonicalFrontierCandidateResultV1
    forged = replace(result, calibration_candidate_row_count=2)
    with pytest.raises(
        ProfiledResearchCanonicalFrontierV1IntegrityError,
        match="FRONTIER_CANDIDATE_RESULT_SEAL_INVALID",
    ):
        _ = forged.runtime_wired

    connection = sqlite3.connect(ledger.path)
    try:
        exact_append_trigger = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'trigger'
              AND name = 'frontier_append_receipts_no_update'
            """
        ).fetchone()[0]
        connection.execute("DROP TRIGGER frontier_append_receipts_no_update")
        connection.execute(
            """
            UPDATE frontier_append_receipts
            SET event_type = 'CANDIDATE' WHERE event_sequence = 1
            """
        )
        connection.executescript(exact_append_trigger)
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(
        ProfiledResearchCanonicalFrontierV1IntegrityError,
        match="FRONTIER_APPEND_RECEIPT_INVALID",
    ):
        ledger.verify_integrity(
            commitment_ledger=commitments,
            outcome_ledger=outcomes,
        )

    connection = sqlite3.connect(ledger.path)
    try:
        connection.execute("DROP TRIGGER frontier_append_receipts_no_update")
        connection.execute(
            """
            UPDATE frontier_append_receipts
            SET event_type = 'SELECTION' WHERE event_sequence = 1
            """
        )
        connection.executescript(exact_append_trigger)
        connection.commit()
        connection.execute("DROP TRIGGER frontier_events_no_update")
        connection.execute(
            """
            CREATE TRIGGER frontier_events_no_update
            BEFORE UPDATE ON frontier_events BEGIN SELECT 1; END
            """
        )
        connection.execute(
            "UPDATE frontier_events SET stable_key_sha256 = ? WHERE event_sequence = 2",
            ("0" * 64,),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ProfiledResearchCanonicalFrontierV1IntegrityError):
        ledger.verify_integrity(
            commitment_ledger=commitments,
            outcome_ledger=outcomes,
        )


def test_restart_recovers_durable_selection_tail_before_new_source_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, commitments, outcomes, _committed, matured = _matured_bundle(
        tmp_path, monkeypatch
    )
    fingerprint = matured.outcome_contract["model_binding"][
        "model_parameter_fingerprint"
    ]
    commitment_snapshot = commitments.capture_inventory_snapshot(store=ledger.store)
    outcome_snapshot = outcomes.capture_inventory_snapshot(store=ledger.store)
    ledger._ensure_initialized()  # noqa: SLF001
    transaction_id = ledger._append_selection_initial(  # noqa: SLF001
        source_pair=frontier._source_pair_binding(  # noqa: SLF001
            commitment_snapshot, outcome_snapshot
        ),
        commitment_snapshot=commitment_snapshot,
        outcome_snapshot=outcome_snapshot,
    )
    rows = ledger._all_rows(require_postcommit=False)  # noqa: SLF001
    assert rows[-1]["transaction_id"] == transaction_id
    assert rows[-1]["postcommit_readback_at"] is None

    reopened = ProfiledResearchCanonicalCandidateFrontierLedgerV1(
        ledger.path, store=ledger.store
    )
    result = reopened.seal_canonical_candidate(
        commitment_ledger=commitments,
        outcome_ledger=outcomes,
        model_parameter_fingerprint=fingerprint,
    )

    assert type(result) is CanonicalFrontierCandidateResultV1
    assert reopened.verify_integrity(
        commitment_ledger=commitments,
        outcome_ledger=outcomes,
    )["events_verified"] == 2


def test_completed_integrity_reopens_selected_source_snapshot_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, commitments, outcomes, _committed, matured = _matured_bundle(
        tmp_path, monkeypatch
    )
    fingerprint = matured.outcome_contract["model_binding"][
        "model_parameter_fingerprint"
    ]
    ledger.seal_canonical_candidate(
        commitment_ledger=commitments,
        outcome_ledger=outcomes,
        model_parameter_fingerprint=fingerprint,
    )
    connection = sqlite3.connect(ledger.path)
    try:
        artifact = frontier._parse_exact_object(  # noqa: SLF001
            connection.execute(
                "SELECT artifact_json FROM frontier_events WHERE event_type = 'SELECTION'"
            ).fetchone()[0],
            reason="TEST_SELECTION_JSON_INVALID",
        )
    finally:
        connection.close()
    relative_path = artifact["source_pair_binding"][
        "commitment_snapshot_cas_address"
    ]["relative_path"]
    (ledger.store.root_path / relative_path).unlink()

    with pytest.raises(
        ProfiledResearchCanonicalFrontierV1IntegrityError,
        match="FRONTIER_COMMITMENT_SNAPSHOT_REOPEN_FAILED",
    ):
        ledger.verify_integrity(
            commitment_ledger=commitments,
            outcome_ledger=outcomes,
        )


def test_candidate_tail_recovery_requires_candidate_root_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, commitments, outcomes, _committed, matured = _matured_bundle(
        tmp_path, monkeypatch
    )
    fingerprint = matured.outcome_contract["model_binding"][
        "model_parameter_fingerprint"
    ]
    commitment_snapshot = commitments.capture_inventory_snapshot(store=ledger.store)
    outcome_snapshot = outcomes.capture_inventory_snapshot(store=ledger.store)
    commitment_rows = commitment_snapshot.ordered_inventory
    outcome_rows = outcome_snapshot.ordered_inventory
    ledger._ensure_initialized()  # noqa: SLF001
    selection_transaction = ledger._append_selection_initial(  # noqa: SLF001
        source_pair=frontier._source_pair_binding(  # noqa: SLF001
            commitment_snapshot, outcome_snapshot
        ),
        commitment_snapshot=commitment_snapshot,
        outcome_snapshot=outcome_snapshot,
    )
    ledger._write_postcommit(  # noqa: SLF001
        transaction_id=selection_transaction,
        accounting_sources=(commitment_rows, outcome_rows),
    )
    selection_row = ledger._all_rows(require_postcommit=True)[0]  # noqa: SLF001
    candidate_transaction = ledger._append_candidate_initial(  # noqa: SLF001
        selection_row=selection_row,
        accounting_address=ledger._post_accounting_address(  # noqa: SLF001
            selection_row
        ),
        model_binding=frontier._model_binding_for_fingerprint(  # noqa: SLF001
            outcome_rows,
            model_parameter_fingerprint=fingerprint,
        ),
        candidate_rows=frontier._candidate_rows_for_model(  # noqa: SLF001
            outcome_rows,
            model_parameter_fingerprint=fingerprint,
        ),
    )
    pending = next(
        row
        for row in ledger._all_rows(require_postcommit=False)  # noqa: SLF001
        if row["transaction_id"] == candidate_transaction
    )
    artifact = frontier.validate_profiled_research_canonical_frontier_candidate_v1(
        pending["artifact_json"].encode("ascii")
    )
    relative_path = artifact["candidate_inventory_root_cas_address"][
        "relative_path"
    ]
    (ledger.store.root_path / relative_path).unlink()

    with pytest.raises(
        ProfiledResearchCanonicalFrontierV1IntegrityError,
        match="FRONTIER_ROOT_CAS_REOPEN_FAILED",
    ):
        ledger.seal_canonical_candidate(
            commitment_ledger=commitments,
            outcome_ledger=outcomes,
            model_parameter_fingerprint=fingerprint,
        )


def test_terminal_accounting_boundary_and_quarantine_are_explicit() -> None:
    sha = "a" * 64
    base = {
        "sequence": 1,
        "hypothesis_identity_sha256": sha,
        "hypothesis_artifact_sha256": "b" * 64,
        "append_receipt_sha256": "c" * 64,
        "postcommit_receipt_sha256": "d" * 64,
        "record_chain_sha256": "e" * 64,
        "decision_time": "2026-01-01T00:00:00.000000Z",
        "label_earliest_available_at": "2026-01-01T00:15:00.000000Z",
        "checkpoint_id": "checkpoint-1",
        "checkpoint_generation": 1,
        "model_parameter_fingerprint": "f" * 64,
        "disposition": "EX_ANTE_VERIFIED_AWAITING_TERMINAL_ACCOUNTING",
    }
    rows, counts, complete = frontier._build_terminal_accounting(  # noqa: SLF001
        [base], [], selection_anchored_at="2026-01-01T00:15:00.000Z"
    )
    assert rows[0]["terminal_disposition"] == "DUE_OUTCOME_MISSING"
    assert counts["due_outcome_missing"] == 1
    assert complete is False

    quarantined = dict(base)
    quarantined["disposition"] = "QUARANTINED_EX_ANTE_DURABILITY_FAILED"
    rows, counts, complete = frontier._build_terminal_accounting(  # noqa: SLF001
        [quarantined], [], selection_anchored_at="2026-01-01T00:00:01.000Z"
    )
    assert rows[0]["terminal_disposition"] == "QUARANTINED_EX_ANTE_DURABILITY"
    assert counts["quarantined_ex_ante_durability"] == 1
    assert complete is True

    between_observation_and_logical_readback = dict(base)
    between_observation_and_logical_readback[
        "label_earliest_available_at"
    ] = "2026-01-01T00:00:00.000500Z"
    rows, counts, complete = frontier._build_terminal_accounting(  # noqa: SLF001
        [between_observation_and_logical_readback],
        [],
        selection_anchored_at="2026-01-01T00:00:00.000400Z",
    )
    assert rows[0]["terminal_disposition"] == "PENDING_LABEL_NOT_AVAILABLE_AT_FRONTIER"
    assert counts["due_outcome_missing"] == 0
    assert complete is True


def test_candidate_inventory_pages_exactly_at_128_129_boundary(
    tmp_path: Path,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "cas")
    rows = [
        {
            "sequence": sequence,
            "calibration_row_id": f"{sequence:064x}",
            "hypothesis_identity_sha256": "1" * 64,
            "hypothesis_artifact_sha256": "2" * 64,
            "outcome_artifact_sha256": "3" * 64,
            "outcome_material_sha256": "4" * 64,
            "label_source_binding_sha256": "5" * 64,
            "append_receipt_sha256": "6" * 64,
            "postcommit_receipt_sha256": "7" * 64,
            "record_chain_sha256": "8" * 64,
            "decision_time": "2026-01-01T00:00:00.000000Z",
            "actual_label_available_at": "2026-01-01T00:15:00.000000Z",
            "maturation_observed_at": "2026-01-01T00:15:01.000000Z",
            "postcommit_readback_at": "2026-01-01T00:15:02.000Z",
            "selected_action": "long",
            "raw_probability": 0.5,
            "observed_strictly_positive_net_pnl": True,
            "model_binding_sha256": "9" * 64,
        }
        for sequence in range(1, 130)
    ]
    root_key = "a" * 64
    address, published = frontier._publish_paged_root(  # noqa: SLF001
        rows=rows,
        root_key_sha256=root_key,
        page_schema_version=(
            frontier.PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_PAGE_V1_SCHEMA_VERSION
        ),
        root_schema_version=(
            frontier.PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_ROOT_V1_SCHEMA_VERSION
        ),
        genesis_page_sha256=frontier._GENESIS_CANDIDATE_PAGE_SHA256,  # noqa: SLF001
        counts={"calibration_candidate_rows": 129},
        store=store,
        row_kind="CANDIDATE",
    )
    reopened, reopened_rows = frontier._load_paged_root(  # noqa: SLF001
        root_address=address,
        expected_root_key_sha256=root_key,
        page_schema_version=(
            frontier.PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_PAGE_V1_SCHEMA_VERSION
        ),
        root_schema_version=(
            frontier.PROFILED_RESEARCH_CANONICAL_FRONTIER_CANDIDATE_ROOT_V1_SCHEMA_VERSION
        ),
        genesis_page_sha256=frontier._GENESIS_CANDIDATE_PAGE_SHA256,  # noqa: SLF001
        store=store,
        row_kind="CANDIDATE",
    )

    assert len(published["ordered_page_descriptors"]) == 2
    assert published["ordered_page_descriptors"][0]["row_count"] == 128
    assert published["ordered_page_descriptors"][1]["row_count"] == 1
    assert reopened == published
    assert reopened_rows == rows
