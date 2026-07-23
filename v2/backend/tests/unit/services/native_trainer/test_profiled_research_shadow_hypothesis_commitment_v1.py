from __future__ import annotations

import inspect
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_research_shadow_hypothesis_commitment_v1 as commitment,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.paper_research_causal_cost_portable_closure_v1 import (  # noqa: E501
    publish_paper_research_causal_cost_portable_closure_v1,
)
from v2.backend.app.services.native_trainer.profiled_research_shadow_hypothesis_commitment_v1 import (  # noqa: E501
    PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_CLASSIFICATION,
    PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_SCHEMA_VERSION,
    ProfiledResearchShadowHypothesisCommitmentLedgerV1,
    ProfiledResearchShadowHypothesisCommitmentV1IntegrityError,
    ProfiledResearchShadowHypothesisCommitmentV1ValidationError,
    ProfiledResearchShadowHypothesisCommitmentWriterLease,
    ProfiledResearchShadowHypothesisCommitmentWriterLeaseError,
)
from v2.backend.app.services.native_trainer.profiled_research_shadow_hypothesis_v1 import (  # noqa: E501
    build_profiled_research_shadow_hypothesis_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_locally_authenticated_profiled_research_inference_v1 as inference_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_research_shadow_hypothesis_v1 as hypothesis_support,
)


@pytest.fixture(autouse=True)
def _clear_inference_order_registry():  # noqa: ANN201
    inference = inference_support.inference
    with inference._PROCESS_SOURCE_ORDER_LOCK:  # noqa: SLF001
        inference._PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.clear()  # noqa: SLF001
    yield
    with inference._PROCESS_SOURCE_ORDER_LOCK:  # noqa: SLF001
        inference._PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.clear()  # noqa: SLF001


def _clock(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):  # noqa: ANN202
    handle = inference_support._open_handle(  # noqa: SLF001
        monkeypatch,
        tmp_path / "raw" / "handle",
    )
    evidence = inference_support._build_evidence(  # noqa: SLF001
        monkeypatch,
        tmp_path / "raw" / "evidence",
    )
    inference_clocks = iter(
        (
            "2026-07-21T12:00:01.000000Z",
            "2026-07-21T12:00:02.000000Z",
        )
    )
    monkeypatch.setattr(
        inference_support.inference,
        "_utc_iso",
        lambda: next(inference_clocks),
    )
    raw = handle.infer_profiled_record_v2(
        record=evidence.record,
        transform_result=evidence.transformed,
        capture_set_contract=evidence.contract,
        capture_set_store=evidence.capture_store,
        artifact_store=evidence.artifact_store,
        source_provenance_ledger=evidence.source_ledger,
        source_provenance_entries=evidence.source_entries,
    )
    cost = hypothesis_support._cost_for_raw(  # noqa: SLF001
        raw,
        tmp_path / "cost",
        monkeypatch,
    )
    store = ImmutableSourcePayloadStore(tmp_path / "portable-cas")
    closure = publish_paper_research_causal_cost_portable_closure_v1(
        cost_evidence=cost,
        store=store,
    )
    hypothesis = build_profiled_research_shadow_hypothesis_v1(
        raw_inference=raw,
        cost_evidence=cost,
        store=store,
    )
    generated = _clock(hypothesis.contract["raw_inference_payload"]["hypothesis_generated_at"])
    decision = _clock(hypothesis.contract["raw_inference_payload"]["source_decision_time"])
    assert generated < decision + timedelta(seconds=900)
    commitment_clocks = iter(
        (
            generated + timedelta(seconds=1),
            generated + timedelta(seconds=1, microseconds=1),
        )
    )
    monkeypatch.setattr(commitment, "_utc_now", lambda: next(commitment_clocks))
    return store, closure, hypothesis


def test_commits_exact_hypothesis_before_label_and_reopens_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(
        tmp_path / "commitments.sqlite3"
    )

    committed = ledger.commit_hypothesis(
        hypothesis=hypothesis,
        cost_closure=closure,
        store=store,
    )

    assert committed.hypothesis_artifact_sha256 == hypothesis.artifact_sha256
    assert committed.cost_closure_address == closure.closure_address
    assert (
        _clock(committed.hypothesis_generated_at)
        <= _clock(committed.commit_observed_at)
        <= _clock(committed.commit_prepared_at)
        < _clock(committed.postcommit_observed_at)
        <= _clock(committed.postcommit_readback_at)
        < _clock(committed.label_earliest_available_at)
    )
    assert committed.pending_hypothesis_index_registered is True
    assert committed.durable_ex_ante_commitment_verified is True
    assert committed.portable_cost_source_closure_complete is True
    assert committed.restart_reopen_verified is True
    assert committed.outcome_maturation_authorized is False
    assert committed.calibration_input_authorized is False
    assert committed.trainer_admission_authorized is False
    assert committed.paper_trading_authorized is False
    assert committed.live_execution_authorized is False
    assert committed.runtime_wired is False
    assert committed.commitment_status == {
        "durable_ex_ante_commit_receipt_present": True,
        "pending_hypothesis_index_registered": True,
        "portable_cost_source_closure_complete": True,
        "restart_reopen_supported": True,
        "postcommit_readback_receipt_present": True,
        "outcome_maturation_authorized": False,
        "calibration_input_authorized": False,
    }
    assert len(committed.authorization) == 18
    assert set(committed.authorization.values()) == {False}
    contract = committed.hypothesis_contract
    assert contract["schema_version"] == "profiled_research_shadow_hypothesis_v1"
    raw_payload = contract["raw_inference_payload"]
    malformed_payloads = []
    unexpected_field = dict(raw_payload)
    unexpected_field.pop("checkpoint_id")
    unexpected_field["future_label_value"] = 1.0
    malformed_payloads.append(unexpected_field)
    for field_name, replacement in (
        ("total_feature_count", float(raw_payload["total_feature_count"])),
        ("available_feature_count", float(raw_payload["available_feature_count"])),
        ("data_coverage_percent", int(raw_payload["data_coverage_percent"])),
        ("expected_move_bps", int(raw_payload["expected_move_bps"])),
    ):
        malformed = dict(raw_payload)
        malformed[field_name] = replacement
        material = {
            key: value
            for key, value in malformed.items()
            if key != "hypothesis_binding_sha256"
        }
        malformed["hypothesis_binding_sha256"] = (
            inference_support.inference.stable_sha256(material)
        )
        malformed_payloads.append(malformed)
    for malformed in malformed_payloads:
        with pytest.raises(
            inference_support.inference.LocallyAuthenticatedProfiledResearchInferenceV1Error
        ):
            inference_support.inference.validate_portable_profiled_research_raw_inference_v2_payload(
                malformed
            )

    integrity = ledger.verify_integrity(store=store)
    assert integrity.total_committed_hypotheses == 1
    assert integrity.ex_ante_verified_hypotheses == 1
    assert integrity.quarantined_hypotheses == 0
    assert integrity.append_receipts_verified == 1
    assert integrity.postcommit_receipts_verified == 1
    assert integrity.pending_index_entries_verified == 1
    assert integrity.head_anchors_verified == 1
    assert integrity.cas_closures_verified == 1
    assert integrity.cas_head_anchors_verified == 1
    assert integrity.schema_verified is True
    assert integrity.clock_causality_verified is True

    pending = ledger.list_pending_hypotheses(store=store)
    assert len(pending) == 1
    assert pending[0].hypothesis_identity_sha256 == (
        committed.hypothesis_identity_sha256
    )
    commitment_contract = ledger._connect_readonly()  # noqa: SLF001
    try:
        row = commitment_contract.execute(
            "SELECT commitment_json FROM profiled_shadow_hypotheses"
        ).fetchone()
    finally:
        commitment_contract.close()
    assert row is not None
    payload = commitment._parse_exact_object(  # noqa: SLF001
        row["commitment_json"],
        reason="TEST_INVALID",
    )
    assert payload["schema_version"] == (
        PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_SCHEMA_VERSION
    )
    assert payload["classification"] == (
        PROFILED_RESEARCH_SHADOW_COMMITMENT_V1_CLASSIFICATION
    )
    assert payload["label_value_present"] is False
    assert payload["outcome_payload_present"] is False
    assert payload["future_data_consumed"] is False


def test_public_commit_api_accepts_no_clock_label_or_outcome_input() -> None:
    parameters = inspect.signature(
        ProfiledResearchShadowHypothesisCommitmentLedgerV1.commit_hypothesis
    ).parameters

    assert tuple(parameters) == (
        "self",
        "hypothesis",
        "cost_closure",
        "store",
        "writer_lease",
    )
    forbidden_fragments = ("clock", "time", "label", "outcome", "price", "return")
    assert not any(
        fragment in parameter
        for parameter in parameters
        for fragment in forbidden_fragments
    )


def test_rejects_commit_at_label_boundary_without_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    label_clock = _clock(
        hypothesis.contract["raw_inference_payload"]["source_decision_time"]
    ) + timedelta(seconds=900)
    monkeypatch.setattr(commitment, "_utc_now", lambda: label_clock)
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(
        tmp_path / "late.sqlite3"
    )

    with pytest.raises(
        ProfiledResearchShadowHypothesisCommitmentV1ValidationError,
        match="SHADOW_COMMITMENT_EX_ANTE_WINDOW_CLOSED",
    ):
        ledger.commit_hypothesis(
            hypothesis=hypothesis,
            cost_closure=closure,
            store=store,
        )

    connection = sqlite3.connect(tmp_path / "late.sqlite3")
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM profiled_shadow_hypotheses"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM profiled_shadow_commitment_append_receipts"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM profiled_shadow_pending_hypothesis_index"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_identical_retry_is_idempotent_and_preserves_one_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(
        tmp_path / "idempotent.sqlite3"
    )
    first = ledger.commit_hypothesis(
        hypothesis=hypothesis,
        cost_closure=closure,
        store=store,
    )
    monkeypatch.setattr(
        commitment,
        "_utc_now",
        lambda: _clock(first.label_earliest_available_at) + timedelta(days=1),
    )

    second = ledger.commit_hypothesis(
        hypothesis=hypothesis,
        cost_closure=closure,
        store=store,
    )

    assert second.transaction_id == first.transaction_id
    assert second.commit_prepared_at == first.commit_prepared_at
    assert second.append_receipt_sha256 == first.append_receipt_sha256
    assert second.postcommit_readback_receipt_sha256 == (
        first.postcommit_readback_receipt_sha256
    )
    integrity = ledger.verify_integrity(store=store)
    assert integrity.total_committed_hypotheses == 1
    assert integrity.append_receipts_verified == 1
    assert integrity.postcommit_receipts_verified == 1


def test_recovers_crash_gap_after_append_commit_before_postcommit_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    path = tmp_path / "recover.sqlite3"
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(path)

    def injected_crash(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("INJECTED_AFTER_APPEND_COMMIT")

    monkeypatch.setattr(ledger, "_write_postcommit_readback", injected_crash)
    with pytest.raises(RuntimeError, match="INJECTED_AFTER_APPEND_COMMIT"):
        ledger.commit_hypothesis(
            hypothesis=hypothesis,
            cost_closure=closure,
            store=store,
        )

    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM profiled_shadow_hypotheses"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM profiled_shadow_commitment_append_receipts"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM profiled_shadow_commitment_postcommit_receipts"
        ).fetchone()[0] == 0
    finally:
        connection.close()

    restarted = ProfiledResearchShadowHypothesisCommitmentLedgerV1(path)
    recovered = restarted.recover_pending_postcommit_readbacks(store=store)
    assert recovered == {
        "status": "SHADOW_COMMITMENT_POSTCOMMIT_RECOVERY_COMPLETE",
        "pending_transactions": 1,
        "recovered_transactions": 1,
        "ex_ante_verified_transactions": 1,
        "quarantined_transactions": 0,
    }
    integrity = restarted.verify_integrity(store=store)
    assert integrity.total_committed_hypotheses == 1
    assert integrity.postcommit_receipts_verified == 1


def test_fresh_process_reopens_only_ledger_and_cas_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    ledger_path = tmp_path / "restart.sqlite3"
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(ledger_path)
    committed = ledger.commit_hypothesis(
        hypothesis=hypothesis,
        cost_closure=closure,
        store=store,
    )
    repo = Path(__file__).resolve().parents[6]
    script = """
import json
import sys
from pathlib import Path
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer import (
    profiled_research_shadow_hypothesis_commitment_v1 as commitment,
)
ledger = commitment.ProfiledResearchShadowHypothesisCommitmentLedgerV1(
    Path(sys.argv[1])
)
store = ImmutableSourcePayloadStore(Path(sys.argv[2]))
opened = ledger.open_committed_hypothesis(
    hypothesis_artifact_sha256=sys.argv[3],
    store=store,
)
integrity = ledger.verify_integrity(store=store)
print(json.dumps({
    "artifact": opened.hypothesis_artifact_sha256,
    "pending": len(ledger.list_pending_hypotheses(store=store)),
    "commits": integrity.total_committed_hypotheses,
    "cas": integrity.cas_closures_verified,
    "runtime_wired": opened.runtime_wired,
}, sort_keys=True))
"""

    restarted = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-c",
            script,
            str(ledger_path),
            str(store.root_path),
            committed.hypothesis_artifact_sha256,
        ],
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(repo)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(restarted.stdout) == {
        "artifact": committed.hypothesis_artifact_sha256,
        "cas": 1,
        "commits": 1,
        "pending": 1,
        "runtime_wired": False,
    }


def test_missing_hypothesis_cas_object_blocks_restart_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(
        tmp_path / "missing.sqlite3"
    )
    committed = ledger.commit_hypothesis(
        hypothesis=hypothesis,
        cost_closure=closure,
        store=store,
    )
    store.path_for(committed.hypothesis_artifact_sha256).unlink()

    with pytest.raises(
        ProfiledResearchShadowHypothesisCommitmentV1IntegrityError,
        match="SHADOW_COMMITMENT_RESTART_CAS_REOPEN_FAILED",
    ):
        ProfiledResearchShadowHypothesisCommitmentLedgerV1(
            tmp_path / "missing.sqlite3"
        ).open_committed_hypothesis(
            hypothesis_artifact_sha256=committed.hypothesis_artifact_sha256,
            store=ImmutableSourcePayloadStore(store.root_path),
        )


def test_immutable_triggers_and_receipt_hash_detect_database_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    path = tmp_path / "tamper.sqlite3"
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(path)
    ledger.commit_hypothesis(
        hypothesis=hypothesis,
        cost_closure=closure,
        store=store,
    )

    connection = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="rows_are_immutable"):
            connection.execute(
                """
                UPDATE profiled_shadow_hypotheses
                SET symbol = 'ETHUSDT'
                """
            )
        connection.rollback()
        trigger_sql = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'trigger'
              AND name = 'profiled_shadow_commitment_append_receipts_no_update'
            """
        ).fetchone()[0]
        connection.execute(
            "DROP TRIGGER profiled_shadow_commitment_append_receipts_no_update"
        )
        connection.execute(
            """
            UPDATE profiled_shadow_commitment_append_receipts
            SET receipt_json = '{}'
            """
        )
        connection.execute(trigger_sql)
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        ProfiledResearchShadowHypothesisCommitmentV1IntegrityError,
        match="SHADOW_COMMITMENT_APPEND_OR_INDEX_RECEIPT_INVALID",
    ):
        ledger.verify_integrity(store=store)


def test_public_result_replacement_and_writer_contention_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    path = tmp_path / "sealed.sqlite3"
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(path)
    committed = ledger.commit_hypothesis(
        hypothesis=hypothesis,
        cost_closure=closure,
        store=store,
    )
    with pytest.raises(TypeError):
        replace(committed, runtime_wired=True)
    forged = replace(committed, record_chain_sha256="0" * 64)
    with pytest.raises(
        ProfiledResearchShadowHypothesisCommitmentV1IntegrityError,
        match="SHADOW_COMMITMENT_RESULT_FACTORY_SEAL_INVALID",
    ):
        _ = forged.runtime_wired

    with ProfiledResearchShadowHypothesisCommitmentWriterLease.acquire(path):
        with pytest.raises(
            ProfiledResearchShadowHypothesisCommitmentWriterLeaseError,
            match="SHADOW_COMMITMENT_WRITER_LEASE_ALREADY_HELD",
        ):
            ProfiledResearchShadowHypothesisCommitmentWriterLease.acquire(path)
        with pytest.raises(
            ProfiledResearchShadowHypothesisCommitmentV1IntegrityError,
            match="SHADOW_COMMITMENT_READER_LEASE_WRITER_ACTIVE",
        ):
            ledger.verify_integrity(store=store)


def test_reader_snapshot_lease_spans_cas_and_head_catalog_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    path = tmp_path / "reader-snapshot.sqlite3"
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(path)
    ledger.commit_hypothesis(
        hypothesis=hypothesis,
        cost_closure=closure,
        store=store,
    )
    original_cas = ledger._verify_rows_cas  # noqa: SLF001
    original_catalog = ledger._verify_head_anchor_catalog  # noqa: SLF001
    writer_exclusion_probes = 0

    def probe_writer_exclusion() -> None:
        nonlocal writer_exclusion_probes
        with pytest.raises(
            ProfiledResearchShadowHypothesisCommitmentWriterLeaseError,
            match="SHADOW_COMMITMENT_WRITER_LEASE_ALREADY_HELD",
        ):
            ProfiledResearchShadowHypothesisCommitmentWriterLease.acquire(path)
        writer_exclusion_probes += 1

    def guarded_cas(rows, *, store):  # noqa: ANN001, ANN202
        probe_writer_exclusion()
        return original_cas(rows, store=store)

    def guarded_catalog(rows):  # noqa: ANN001, ANN202
        probe_writer_exclusion()
        return original_catalog(rows)

    monkeypatch.setattr(ledger, "_verify_rows_cas", guarded_cas)
    monkeypatch.setattr(ledger, "_verify_head_anchor_catalog", guarded_catalog)

    assert ledger.verify_integrity(store=store).cas_closures_verified == 1
    assert writer_exclusion_probes == 2


@pytest.mark.parametrize("lease_binding", ("constructor", "per_call"))
def test_commit_reuses_caller_owned_writer_lease_for_final_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lease_binding: str,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    path = tmp_path / f"external-{lease_binding}.sqlite3"
    lease = ProfiledResearchShadowHypothesisCommitmentWriterLease.acquire(path)
    try:
        ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(
            path,
            writer_lease=lease if lease_binding == "constructor" else None,
        )
        committed = ledger.commit_hypothesis(
            hypothesis=hypothesis,
            cost_closure=closure,
            store=store,
            writer_lease=lease if lease_binding == "per_call" else None,
        )

        assert committed.runtime_wired is False
        assert committed.durable_ex_ante_commitment_verified is True
        if lease_binding == "constructor":
            assert ledger.verify_integrity(store=store).cas_closures_verified == 1
    finally:
        lease.release()

    assert committed.runtime_wired is False


def test_transaction_crossing_label_boundary_is_durably_quarantined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    generated = _clock(
        hypothesis.contract["raw_inference_payload"]["hypothesis_generated_at"]
    )
    label_clock = _clock(
        hypothesis.contract["raw_inference_payload"]["source_decision_time"]
    ) + timedelta(seconds=900)
    clocks = iter(
        (
            generated + timedelta(seconds=1),
            label_clock + timedelta(microseconds=100),
        )
    )
    monkeypatch.setattr(commitment, "_utc_now", lambda: next(clocks))
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(
        tmp_path / "crossed.sqlite3"
    )

    with pytest.raises(
        ProfiledResearchShadowHypothesisCommitmentV1ValidationError,
        match="SHADOW_COMMITMENT_EX_ANTE_DURABILITY_UNVERIFIED",
    ):
        ledger.commit_hypothesis(
            hypothesis=hypothesis,
            cost_closure=closure,
            store=store,
        )

    integrity = ledger.verify_integrity(store=store)
    assert integrity.total_committed_hypotheses == 1
    assert integrity.ex_ante_verified_hypotheses == 0
    assert integrity.quarantined_hypotheses == 1
    assert integrity.postcommit_receipts_verified == 1
    assert ledger.list_pending_hypotheses(store=store) == ()
    connection = sqlite3.connect(tmp_path / "crossed.sqlite3")
    try:
        row = connection.execute(
            """
            SELECT ex_ante_durability_verified, readback_receipt_json
            FROM profiled_shadow_commitment_postcommit_receipts
            """
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert row[0] == 0
    assert json.loads(row[1])[
        "durable_commit_observed_before_label_availability"
    ] is False


@pytest.mark.parametrize("post_delta_microseconds", (0, -100))
def test_postcommit_raw_clock_tie_or_rollback_is_quarantined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    post_delta_microseconds: int,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    generated = _clock(
        hypothesis.contract["raw_inference_payload"]["hypothesis_generated_at"]
    )
    commit_observed = generated + timedelta(seconds=1)
    clocks = iter(
        (
            commit_observed,
            commit_observed
            + timedelta(microseconds=post_delta_microseconds),
        )
    )
    monkeypatch.setattr(commitment, "_utc_now", lambda: next(clocks))
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(
        tmp_path / f"raw-clock-{post_delta_microseconds}.sqlite3"
    )

    with pytest.raises(
        ProfiledResearchShadowHypothesisCommitmentV1ValidationError,
        match="SHADOW_COMMITMENT_EX_ANTE_DURABILITY_UNVERIFIED",
    ):
        ledger.commit_hypothesis(
            hypothesis=hypothesis,
            cost_closure=closure,
            store=store,
        )

    integrity = ledger.verify_integrity(store=store)
    assert integrity.ex_ante_verified_hypotheses == 0
    assert integrity.quarantined_hypotheses == 1
    assert ledger.list_pending_hypotheses(store=store) == ()


def test_raw_commit_clock_preceding_hypothesis_fails_even_when_ceil_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    generated = _clock(
        hypothesis.contract["raw_inference_payload"]["hypothesis_generated_at"]
    )
    monkeypatch.setattr(
        commitment,
        "_utc_now",
        lambda: generated - timedelta(microseconds=100),
    )
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(
        tmp_path / "source-skew.sqlite3"
    )

    with pytest.raises(
        ProfiledResearchShadowHypothesisCommitmentV1ValidationError,
        match="SHADOW_COMMITMENT_INTERNAL_CLOCK_PRECEDES_HYPOTHESIS",
    ):
        ledger.commit_hypothesis(
            hypothesis=hypothesis,
            cost_closure=closure,
            store=store,
        )


def test_raw_postcommit_before_label_survives_logical_clock_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    generated = _clock(
        hypothesis.contract["raw_inference_payload"]["hypothesis_generated_at"]
    )
    label_clock = _clock(
        hypothesis.contract["raw_inference_payload"]["source_decision_time"]
    ) + timedelta(seconds=900)
    clocks = iter(
        (
            generated + timedelta(seconds=1),
            label_clock - timedelta(microseconds=100),
        )
    )
    monkeypatch.setattr(commitment, "_utc_now", lambda: next(clocks))
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(
        tmp_path / "submillisecond-ex-ante.sqlite3"
    )

    committed = ledger.commit_hypothesis(
        hypothesis=hypothesis,
        cost_closure=closure,
        store=store,
    )

    assert _clock(committed.postcommit_observed_at) < label_clock
    assert _clock(committed.postcommit_readback_at) == label_clock
    assert committed.durable_ex_ante_commitment_verified is True


def test_same_name_noop_trigger_substitution_fails_schema_sql_pin(
    tmp_path: Path,
) -> None:
    path = tmp_path / "schema.sqlite3"
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(path)
    with ledger.writer_lease() as lease:
        ledger._ensure_initialized(writer_lease=lease)  # noqa: SLF001
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "DROP TRIGGER profiled_shadow_hypotheses_no_update"
        )
        connection.execute(
            """
            CREATE TRIGGER profiled_shadow_hypotheses_no_update
            BEFORE UPDATE ON profiled_shadow_hypotheses
            BEGIN
                SELECT 1;
            END
            """
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        ProfiledResearchShadowHypothesisCommitmentV1IntegrityError,
        match="SHADOW_COMMITMENT_SCHEMA_INVALID",
    ):
        ledger.verify_integrity(
            store=ImmutableSourcePayloadStore(tmp_path / "empty-cas")
        )


def test_initialization_failure_rolls_back_schema_and_metadata_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "initialization.sqlite3"
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(path)
    original_validate = commitment._validate_schema  # noqa: SLF001

    def injected_failure(_connection):  # noqa: ANN001, ANN202
        raise RuntimeError("INJECTED_BEFORE_INITIALIZATION_COMMIT")

    monkeypatch.setattr(commitment, "_validate_schema", injected_failure)
    with pytest.raises(
        RuntimeError,
        match="INJECTED_BEFORE_INITIALIZATION_COMMIT",
    ):
        with ledger.writer_lease() as lease:
            ledger._ensure_initialized(writer_lease=lease)  # noqa: SLF001
    monkeypatch.setattr(commitment, "_validate_schema", original_validate)

    connection = sqlite3.connect(path)
    try:
        objects = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
        assert objects == []
        assert connection.execute("PRAGMA application_id").fetchone()[0] == 0
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        connection.close()

    with ledger.writer_lease() as lease:
        ledger._ensure_initialized(writer_lease=lease)  # noqa: SLF001
    integrity = ledger.verify_integrity(
        store=ImmutableSourcePayloadStore(tmp_path / "empty-cas")
    )
    assert integrity.total_committed_hypotheses == 0
    assert integrity.schema_verified is True


def test_recovers_postcommit_database_to_head_catalog_crash_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    path = tmp_path / "catalog-recovery.sqlite3"
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(path)

    def injected_catalog_crash(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("INJECTED_AFTER_POSTCOMMIT_DATABASE_COMMIT")

    monkeypatch.setattr(
        ledger,
        "_publish_head_anchor_catalog_entry",
        injected_catalog_crash,
    )
    with pytest.raises(
        RuntimeError,
        match="INJECTED_AFTER_POSTCOMMIT_DATABASE_COMMIT",
    ):
        ledger.commit_hypothesis(
            hypothesis=hypothesis,
            cost_closure=closure,
            store=store,
        )
    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM profiled_shadow_commitment_postcommit_receipts"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM profiled_shadow_commitment_head_anchors"
        ).fetchone()[0] == 1
    finally:
        connection.close()
    catalog_root = path.with_name(path.name + ".head-anchor-cas")
    assert not catalog_root.exists()

    restarted = ProfiledResearchShadowHypothesisCommitmentLedgerV1(path)
    recovery = restarted.recover_pending_postcommit_readbacks(store=store)
    assert recovery["pending_transactions"] == 0
    assert recovery["recovered_transactions"] == 0
    assert recovery["ex_ante_verified_transactions"] == 1
    assert len(tuple((catalog_root / "sha256").glob("*/*"))) == 1
    assert restarted.verify_integrity(store=store).cas_head_anchors_verified == 1


def test_enumerable_head_catalog_detects_complete_sqlite_suffix_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, closure, hypothesis = _bundle(tmp_path, monkeypatch)
    path = tmp_path / "truncate.sqlite3"
    ledger = ProfiledResearchShadowHypothesisCommitmentLedgerV1(path)
    ledger.commit_hypothesis(
        hypothesis=hypothesis,
        cost_closure=closure,
        store=store,
    )
    tables = (
        "profiled_shadow_commitment_head_anchors",
        "profiled_shadow_commitment_postcommit_receipts",
        "profiled_shadow_commitment_append_receipts",
        "profiled_shadow_pending_hypothesis_index",
        "profiled_shadow_hypotheses",
    )
    connection = sqlite3.connect(path)
    try:
        trigger_sql = {
            table: connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
                (f"{table}_no_delete",),
            ).fetchone()[0]
            for table in tables
        }
        for table in tables:
            connection.execute(f"DROP TRIGGER {table}_no_delete")  # noqa: S608
        for table in tables:
            connection.execute(f"DELETE FROM {table}")  # noqa: S608
        for table in reversed(tables):
            connection.execute(trigger_sql[table])
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(
        ProfiledResearchShadowHypothesisCommitmentV1IntegrityError,
        match="SHADOW_COMMITMENT_HEAD_ANCHOR_CATALOG_MEMBERSHIP_INVALID",
    ):
        ledger.verify_integrity(store=store)


def test_clock_ceiling_is_conservative_at_submillisecond_deadline() -> None:
    label_available_at = datetime(
        2026,
        7,
        21,
        12,
        15,
        0,
        900500,
        tzinfo=UTC,
    )
    observed_after_label = label_available_at + timedelta(microseconds=100)

    persisted_observation = commitment._ceil_millisecond(  # noqa: SLF001
        observed_after_label
    )

    assert persisted_observation == datetime(
        2026,
        7,
        21,
        12,
        15,
        0,
        901000,
        tzinfo=UTC,
    )
    assert persisted_observation >= label_available_at
