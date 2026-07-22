from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.native_trainer import (
    profiled_training_external_witness_journal_v1 as journal_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_manifest_head_v1 as head_module,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FeatureSnapshotWriterLease,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_client_v1 import (
    PinnedProfiledTrainingExternalWitnessClientV1,
    ProfiledTrainingExternalWitnessClientV1Error,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_journal_v1 import (
    PROFILED_WITNESS_JOURNAL_APPEND_PREPARED,
    PROFILED_WITNESS_JOURNAL_GENESIS_TRANSITION_SHA256,
    PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED,
    ProfiledTrainingExternalWitnessJournalV1,
    ProfiledTrainingExternalWitnessJournalV1Error,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256,
    PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
    PROFILED_OBSERVATION_LOCAL_STAGING_STATUS,
    LocalProfiledTrainingObservationHeadCandidateV1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_external_witness_client_v1 as witness_support,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _candidate(
    tmp_path: Path,
    *,
    prepared: Any,
) -> LocalProfiledTrainingObservationHeadCandidateV1:
    staging_root = (tmp_path / "local-head-staging").absolute()
    staging_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging_root.chmod(0o700)
    material = json.loads(prepared.event_bytes)
    authority = {name: material[name] for name in head_module._authority_false()}
    ImmutableSourcePayloadStore(staging_root).put(
        prepared.event_bytes,
        expected_sha256=prepared.event_sha256,
        expected_byte_count=prepared.event_byte_count,
    )
    return LocalProfiledTrainingObservationHeadCandidateV1(
        staging_store_root=staging_root,
        candidate_event_sha256=prepared.event_sha256,
        candidate_event_byte_count=prepared.event_byte_count,
        candidate_id=material["candidate_id"],
        namespace=prepared.namespace,
        revision=prepared.expected_sequence + 1,
        previous_head_event_sha256=prepared.expected_event_sha256,
        previous_completion_candidate_sha256=material["previous_completion_candidate_sha256"],
        manifest_id=material["manifest_id"],
        observation_time=material["observation_time"],
        manifest_auth_key_id=material["manifest_auth_key_id"],
        head_auth_key_id=material["head_auth_key_id"],
        epoch_auth_key_id=material["epoch_auth_key_id"],
        epoch_auth_key_commitment_sha256=material["epoch_auth_key_commitment_sha256"],
        allowed_consumer_lane=material["allowed_consumer_lane"],
        local_status=PROFILED_OBSERVATION_LOCAL_STAGING_STATUS,
        full_manifest_authentication_verified=True,
        full_entry_inventory_verified=True,
        **authority,
        _manifest_key_sha256=_digest("manifest-key"),
        _head_key_sha256=_digest("head-key"),
        _epoch_key_sha256=_digest("epoch-key"),
        _material=material,
        _construction_token=head_module._HEAD_TOKEN,
    )


def _journal(tmp_path: Path) -> ProfiledTrainingExternalWitnessJournalV1:
    cas_root = (tmp_path / "witness-journal-cas").absolute()
    journal_path = (tmp_path / "witness-journal.sqlite3").absolute()
    return ProfiledTrainingExternalWitnessJournalV1(
        journal_path,
        immutable_store=ImmutableSourcePayloadStore(cas_root),
    )


def _client_bundle() -> (
    tuple[
        Ed25519PrivateKey,
        witness_support._SignedWitnessTransport,
        PinnedProfiledTrainingExternalWitnessClientV1,
    ]
):
    private_key = Ed25519PrivateKey.generate()
    transport = witness_support._SignedWitnessTransport(private_key)
    return private_key, transport, witness_support._client(private_key, transport)


def _restart_client(
    *,
    private_key: Ed25519PrivateKey,
    transport: witness_support._SignedWitnessTransport,
    journal: ProfiledTrainingExternalWitnessJournalV1,
) -> PinnedProfiledTrainingExternalWitnessClientV1:
    public_key = witness_support._raw_public_key(private_key)
    return PinnedProfiledTrainingExternalWitnessClientV1(
        transport=transport,
        witness_id=witness_support.WITNESS_ID,
        witness_public_key_bytes=public_key,
        expected_witness_public_key_sha256=hashlib.sha256(public_key).hexdigest(),
        trusted_head_envelope_bytes_by_namespace=(
            journal.persisted_signed_head_envelopes_by_namespace()
        ),
    )


def _prepared(
    client: PinnedProfiledTrainingExternalWitnessClientV1,
    *,
    label: str = "candidate-1",
    sequence: int = 0,
    previous_sha256: str = PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
    namespace: str = witness_support.NAMESPACE,
) -> Any:
    observation_time = (
        (datetime(2026, 7, 22, 12, 59, tzinfo=UTC) + timedelta(hours=sequence))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    event_material = {
        "candidate_id": _digest(label),
        "namespace": namespace,
        "revision": sequence + 1,
        "previous_head_event_sha256": previous_sha256,
        "previous_completion_candidate_sha256": (
            PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256
            if sequence == 0
            else _digest(f"completion-{sequence}")
        ),
        "manifest_id": _digest(f"manifest-{label}"),
        "observation_time": observation_time,
        "manifest_auth_key_id": "unit/manifest-key",
        "head_auth_key_id": "unit/head-key",
        "epoch_auth_key_id": "unit/epoch-key",
        "epoch_auth_key_commitment_sha256": _digest("epoch-key-commitment"),
        "allowed_consumer_lane": "unit/trainer-consumer",
        "full_manifest_authentication_verified": True,
        "full_entry_inventory_verified": True,
        "local_status": PROFILED_OBSERVATION_LOCAL_STAGING_STATUS,
        **head_module._authority_false(),
    }
    return client.prepare_compare_and_append(
        namespace=namespace,
        expected_sequence=sequence,
        expected_event_sha256=previous_sha256,
        event_bytes=witness_support._canonical(event_material),
    )


def test_initialize_is_empty_append_only_journal_without_network(tmp_path: Path) -> None:
    _private_key, transport, _client = _client_bundle()
    journal = _journal(tmp_path)

    journal.initialize()
    report = journal.verify_integrity()

    assert transport.requests == []
    assert report.operation_count == 0
    assert report.transition_count == 0
    assert report.pending_count == 0
    assert report.terminal_transition_sha256 == (PROFILED_WITNESS_JOURNAL_GENESIS_TRANSITION_SHA256)
    assert report.optimizer_admission_authorized is False
    assert report.checkpoint_write_authorized is False
    assert report.model_write_authorized is False
    assert report.prediction_authorized is False
    assert report.paper_trading_authorized is False
    assert report.live_execution_authorized is False
    assert report.order_submission_authorized is False
    assert report.execution_authorized is False
    assert report.runtime_wired is False


def test_prepared_append_is_durable_before_any_network_dispatch(tmp_path: Path) -> None:
    _private_key, transport, client = _client_bundle()
    journal = _journal(tmp_path)
    prepared = _prepared(client)
    candidate = _candidate(tmp_path, prepared=prepared)

    record = journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=candidate,
    )

    assert transport.requests == []
    assert record.state == PROFILED_WITNESS_JOURNAL_APPEND_PREPARED
    assert record.prepared == prepared
    assert record.prepared.request_bytes == prepared.request_bytes
    assert record.append_receipt is None
    assert record.signed_head_envelope_bytes is None
    assert (
        journal.immutable_store.get(
            prepared.event_sha256,
            expected_byte_count=prepared.event_byte_count,
        )
        == prepared.event_bytes
    )
    assert (
        journal.immutable_store.get(
            prepared.request_sha256,
            expected_byte_count=prepared.request_byte_count,
        )
        == prepared.request_bytes
    )
    report = journal.verify_integrity()
    assert (report.operation_count, report.transition_count) == (1, 1)
    assert (report.pending_count, report.anchored_count) == (1, 0)


def test_dispatch_then_anchor_survives_fresh_client_restart(tmp_path: Path) -> None:
    private_key, transport, client = _client_bundle()
    journal = _journal(tmp_path)
    prepared = _prepared(client)
    candidate = _candidate(tmp_path, prepared=prepared)
    pending = journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=candidate,
    )

    receipt = client.dispatch_prepared_append(pending.prepared)
    anchored = journal.commit_head_anchored(
        client=client,
        operation_id=pending.operation_id,
        append_receipt=receipt,
    )

    assert anchored.state == PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED
    assert anchored.append_receipt == receipt
    assert anchored.signed_head_envelope_bytes == client.trusted_head_envelope_bytes(
        namespace=prepared.namespace
    )
    assert len(transport.events) == 1
    restarted = _restart_client(
        private_key=private_key,
        transport=transport,
        journal=journal,
    )
    assert journal.load_pending_appends(client=restarted) == ()
    assert restarted.trusted_head_envelope_bytes(namespace=prepared.namespace) == (
        anchored.signed_head_envelope_bytes
    )
    report = journal.verify_integrity()
    assert (report.operation_count, report.transition_count) == (1, 2)
    assert (report.pending_count, report.anchored_count) == (0, 1)


def test_ambiguous_remote_success_replays_exact_request_once(tmp_path: Path) -> None:
    private_key, transport, client = _client_bundle()
    journal = _journal(tmp_path)
    prepared = _prepared(client, label="ambiguous-append-head")
    candidate = _candidate(tmp_path, prepared=prepared)
    pending = journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=candidate,
    )
    transport.fail_after_append_once = True

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_HTTP_TRANSPORT_FAILED",
    ):
        client.dispatch_prepared_append(pending.prepared)

    assert len(transport.events) == 1
    assert journal.verify_integrity().pending_count == 1
    restarted = _restart_client(
        private_key=private_key,
        transport=transport,
        journal=journal,
    )
    recovered = journal.load_pending_appends(client=restarted)
    assert len(recovered) == 1
    assert recovered[0].prepared.request_bytes == prepared.request_bytes
    receipt = restarted.dispatch_prepared_append(recovered[0].prepared)
    journal.commit_head_anchored(
        client=restarted,
        operation_id=recovered[0].operation_id,
        append_receipt=receipt,
    )

    assert len(transport.events) == 1
    posts = [request for request in transport.requests if request[0] == "POST"]
    assert len(posts) == 2
    assert posts[0][2:] == posts[1][2:]
    assert journal.verify_integrity().pending_count == 0


def test_prepared_commit_survives_postcommit_reopen_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _private_key, transport, client = _client_bundle()
    journal = _journal(tmp_path)
    prepared = _prepared(client, label="prepared-reopen-failure")
    candidate = _candidate(tmp_path, prepared=prepared)
    original = ProfiledTrainingExternalWitnessJournalV1._open_connection
    open_count = 0

    def fail_second_open(
        self: ProfiledTrainingExternalWitnessJournalV1,
        *,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> sqlite3.Connection:
        nonlocal open_count
        open_count += 1
        if open_count == 2:
            raise ProfiledTrainingExternalWitnessJournalV1Error(
                "INJECTED_POSTCOMMIT_REOPEN_FAILURE"
            )
        return original(self, writer_lease=writer_lease)

    monkeypatch.setattr(
        ProfiledTrainingExternalWitnessJournalV1,
        "_open_connection",
        fail_second_open,
    )
    with pytest.raises(
        ProfiledTrainingExternalWitnessJournalV1Error,
        match="INJECTED_POSTCOMMIT_REOPEN_FAILURE",
    ):
        journal.persist_prepared_append(
            client=client,
            prepared=prepared,
            head_candidate=candidate,
        )
    monkeypatch.setattr(
        ProfiledTrainingExternalWitnessJournalV1,
        "_open_connection",
        original,
    )

    assert transport.requests == []
    assert journal.verify_integrity().pending_count == 1
    recovered = journal.load_pending_appends(client=client)
    assert len(recovered) == 1
    assert recovered[0].prepared.request_bytes == prepared.request_bytes


def test_anchor_commit_survives_postcommit_reopen_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _private_key, _transport, client = _client_bundle()
    journal = _journal(tmp_path)
    prepared = _prepared(client, label="anchor-reopen-failure")
    pending = journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=_candidate(tmp_path, prepared=prepared),
    )
    receipt = client.dispatch_prepared_append(pending.prepared)
    original = ProfiledTrainingExternalWitnessJournalV1._open_connection
    open_count = 0

    def fail_second_open(
        self: ProfiledTrainingExternalWitnessJournalV1,
        *,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> sqlite3.Connection:
        nonlocal open_count
        open_count += 1
        if open_count == 2:
            raise ProfiledTrainingExternalWitnessJournalV1Error(
                "INJECTED_POSTCOMMIT_REOPEN_FAILURE"
            )
        return original(self, writer_lease=writer_lease)

    monkeypatch.setattr(
        ProfiledTrainingExternalWitnessJournalV1,
        "_open_connection",
        fail_second_open,
    )
    with pytest.raises(
        ProfiledTrainingExternalWitnessJournalV1Error,
        match="INJECTED_POSTCOMMIT_REOPEN_FAILURE",
    ):
        journal.commit_head_anchored(
            client=client,
            operation_id=pending.operation_id,
            append_receipt=receipt,
        )
    monkeypatch.setattr(
        ProfiledTrainingExternalWitnessJournalV1,
        "_open_connection",
        original,
    )

    report = journal.verify_integrity()
    assert (report.anchored_count, report.pending_count) == (1, 0)
    replayed = journal.commit_head_anchored(
        client=client,
        operation_id=pending.operation_id,
        append_receipt=receipt,
    )
    assert replayed.state == PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED


def test_exact_prepared_and_anchor_replays_are_idempotent(tmp_path: Path) -> None:
    _private_key, transport, client = _client_bundle()
    journal = _journal(tmp_path)
    prepared = _prepared(client)
    candidate = _candidate(tmp_path, prepared=prepared)
    first = journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=candidate,
    )
    repeated = journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=candidate,
    )
    assert repeated.operation_id == first.operation_id
    assert repeated.prepared_transition_sha256 == first.prepared_transition_sha256
    assert journal.verify_integrity().transition_count == 1

    receipt = client.dispatch_prepared_append(first.prepared)
    anchored = journal.commit_head_anchored(
        client=client,
        operation_id=first.operation_id,
        append_receipt=receipt,
    )
    replayed = journal.commit_head_anchored(
        client=client,
        operation_id=first.operation_id,
        append_receipt=receipt,
    )
    assert replayed == anchored
    assert journal.verify_integrity().transition_count == 2
    assert len(transport.events) == 1


def test_namespace_rejects_second_operation_while_first_is_pending(tmp_path: Path) -> None:
    _private_key, transport, client = _client_bundle()
    journal = _journal(tmp_path)
    first = _prepared(client, label="first-pending")
    journal.persist_prepared_append(
        client=client,
        prepared=first,
        head_candidate=_candidate(tmp_path, prepared=first),
    )
    second = _prepared(client, label="conflicting-pending")

    with pytest.raises(
        ProfiledTrainingExternalWitnessJournalV1Error,
        match="PROFILED_WITNESS_JOURNAL_NAMESPACE_PENDING_APPEND_EXISTS",
    ):
        journal.persist_prepared_append(
            client=client,
            prepared=second,
            head_candidate=_candidate(tmp_path, prepared=second),
        )

    assert transport.requests == []
    assert journal.verify_integrity().pending_count == 1


def test_sequential_anchors_bind_prior_signed_head(tmp_path: Path) -> None:
    private_key, transport, client = _client_bundle()
    journal = _journal(tmp_path)
    first_prepared = _prepared(client, label="head-one")
    first = journal.persist_prepared_append(
        client=client,
        prepared=first_prepared,
        head_candidate=_candidate(tmp_path, prepared=first_prepared),
    )
    first_receipt = client.dispatch_prepared_append(first.prepared)
    first_anchor = journal.commit_head_anchored(
        client=client,
        operation_id=first.operation_id,
        append_receipt=first_receipt,
    )

    restarted = _restart_client(
        private_key=private_key,
        transport=transport,
        journal=journal,
    )
    second_prepared = _prepared(
        restarted,
        label="head-two",
        sequence=1,
        previous_sha256=first_prepared.event_sha256,
    )
    second = journal.persist_prepared_append(
        client=restarted,
        prepared=second_prepared,
        head_candidate=_candidate(tmp_path, prepared=second_prepared),
    )
    second_receipt = restarted.dispatch_prepared_append(second.prepared)
    second_anchor = journal.commit_head_anchored(
        client=restarted,
        operation_id=second.operation_id,
        append_receipt=second_receipt,
    )

    assert first_anchor.anchored_transition_sequence == 2
    assert second.prepared_transition_sequence == 3
    assert second_anchor.anchored_transition_sequence == 4
    assert len(transport.events) == 2
    report = journal.verify_integrity()
    assert (report.operation_count, report.transition_count) == (2, 4)
    assert (report.pending_count, report.anchored_count) == (0, 2)
    latest = journal.persisted_signed_head_envelopes_by_namespace()
    assert latest[witness_support.NAMESPACE] == second_anchor.signed_head_envelope_bytes


def test_global_transition_chain_allows_interleaved_namespaces(tmp_path: Path) -> None:
    _private_key, transport, client = _client_bundle()
    journal = _journal(tmp_path)
    first_prepared = _prepared(client, label="first-namespace")
    first = journal.persist_prepared_append(
        client=client,
        prepared=first_prepared,
        head_candidate=_candidate(tmp_path, prepared=first_prepared),
    )
    other_prepared = _prepared(
        client,
        label="other-namespace",
        namespace="profiled-trainer-other",
    )
    other = journal.persist_prepared_append(
        client=client,
        prepared=other_prepared,
        head_candidate=_candidate(tmp_path, prepared=other_prepared),
    )
    assert (first.prepared_transition_sequence, other.prepared_transition_sequence) == (
        1,
        2,
    )

    receipt = client.dispatch_prepared_append(first.prepared)
    anchored = journal.commit_head_anchored(
        client=client,
        operation_id=first.operation_id,
        append_receipt=receipt,
    )

    assert anchored.anchored_transition_sequence == 3
    report = journal.verify_integrity()
    assert (report.operation_count, report.transition_count) == (2, 3)
    assert (report.anchored_count, report.pending_count, report.namespace_count) == (
        1,
        1,
        2,
    )
    assert len(transport.events) == 1


def test_changed_witness_key_cannot_rehydrate_pending_request(tmp_path: Path) -> None:
    _private_key, _transport, client = _client_bundle()
    journal = _journal(tmp_path)
    prepared = _prepared(client)
    journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=_candidate(tmp_path, prepared=prepared),
    )
    other_private = Ed25519PrivateKey.generate()
    other_transport = witness_support._SignedWitnessTransport(other_private)
    other_client = witness_support._client(other_private, other_transport)

    with pytest.raises(
        ProfiledTrainingExternalWitnessJournalV1Error,
        match="PROFILED_WITNESS_JOURNAL_CLIENT_REAUTHENTICATION_FAILED",
    ):
        journal.load_pending_appends(client=other_client)

    assert other_transport.requests == []


def test_update_delete_and_wrong_writer_lease_fail_closed(tmp_path: Path) -> None:
    _private_key, _transport, client = _client_bundle()
    journal = _journal(tmp_path)
    prepared = _prepared(client)
    record = journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=_candidate(tmp_path, prepared=prepared),
    )

    connection = sqlite3.connect(journal.path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="update_forbidden"):
            connection.execute(
                "UPDATE witness_journal_operations SET manifest_id = ? WHERE operation_id = ?",
                (_digest("mutated"), record.operation_id),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="delete_forbidden"):
            connection.execute(
                "DELETE FROM witness_journal_transitions WHERE operation_id = ?",
                (record.operation_id,),
            )
        connection.rollback()
    finally:
        connection.close()
    assert journal.verify_integrity().pending_count == 1

    wrong_path = (tmp_path / "wrong-journal.sqlite3").absolute()
    wrong_lease = FeatureSnapshotWriterLease.acquire(wrong_path)
    try:
        with pytest.raises(
            ProfiledTrainingExternalWitnessJournalV1Error,
            match="PROFILED_WITNESS_JOURNAL_WRITER_LEASE_INVALID",
        ):
            journal.initialize(writer_lease=wrong_lease)
    finally:
        wrong_lease.release()


def test_schema_or_cas_tamper_is_detected(tmp_path: Path) -> None:
    _private_key, _transport, client = _client_bundle()
    journal = _journal(tmp_path)
    prepared = _prepared(client)
    journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=_candidate(tmp_path, prepared=prepared),
    )
    event_path = journal.immutable_store.path_for(prepared.event_sha256)
    event_path.chmod(0o600)
    event_path.write_bytes(b"tampered-event")
    event_path.chmod(0o400)

    with pytest.raises(
        ProfiledTrainingExternalWitnessJournalV1Error,
        match="PROFILED_WITNESS_JOURNAL_CAS_EVIDENCE_INVALID",
    ):
        journal.verify_integrity()


def test_resource_count_gate_precedes_cas_evidence_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _private_key, _transport, client = _client_bundle()
    journal = _journal(tmp_path)
    prepared = _prepared(client, label="resource-count-first")
    journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=_candidate(tmp_path, prepared=prepared),
    )
    event_path = journal.immutable_store.path_for(prepared.event_sha256)
    event_path.chmod(0o600)
    event_path.write_bytes(b"tampered-event")
    event_path.chmod(0o400)
    monkeypatch.setattr(journal_module, "MAX_PROFILED_WITNESS_JOURNAL_TRANSITIONS", 0)

    with pytest.raises(
        ProfiledTrainingExternalWitnessJournalV1Error,
        match="PROFILED_WITNESS_JOURNAL_TRANSITION_RESOURCE_LIMIT_EXCEEDED",
    ):
        journal.verify_integrity()


def test_capacity_reserves_one_future_anchor_for_every_pending_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _private_key, transport, client = _client_bundle()
    journal = _journal(tmp_path)
    monkeypatch.setattr(journal_module, "MAX_PROFILED_WITNESS_JOURNAL_TRANSITIONS", 4)

    first_prepared = _prepared(
        client,
        label="capacity-a",
    )
    first = journal.persist_prepared_append(
        client=client,
        prepared=first_prepared,
        head_candidate=_candidate(tmp_path, prepared=first_prepared),
    )
    second_prepared = _prepared(
        client,
        label="capacity-b",
        namespace="unit/profiled-capacity-b",
    )
    journal.persist_prepared_append(
        client=client,
        prepared=second_prepared,
        head_candidate=_candidate(tmp_path, prepared=second_prepared),
    )
    report = journal.verify_integrity()
    assert (report.transition_count, report.pending_count) == (2, 2)

    third_prepared = _prepared(
        client,
        label="capacity-c",
        namespace="unit/profiled-capacity-c",
    )
    with pytest.raises(
        ProfiledTrainingExternalWitnessJournalV1Error,
        match="PROFILED_WITNESS_JOURNAL_TRANSITION_CAPACITY_RESERVED",
    ):
        journal.persist_prepared_append(
            client=client,
            prepared=third_prepared,
            head_candidate=_candidate(tmp_path, prepared=third_prepared),
        )
    assert transport.requests == []
    assert journal.verify_integrity().operation_count == 2
    assert not journal.immutable_store.path_for(third_prepared.event_sha256).exists()
    assert not journal.immutable_store.path_for(third_prepared.request_sha256).exists()

    receipt = client.dispatch_prepared_append(first.prepared)
    journal.commit_head_anchored(
        client=client,
        operation_id=first.operation_id,
        append_receipt=receipt,
    )
    anchored_report = journal.verify_integrity()
    assert (anchored_report.transition_count, anchored_report.pending_count) == (3, 1)


def test_signed_head_reverification_rejects_tampering(tmp_path: Path) -> None:
    _private_key, _transport, client = _client_bundle()
    journal = _journal(tmp_path)
    prepared = _prepared(client)
    pending = journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=_candidate(tmp_path, prepared=prepared),
    )
    receipt = client.dispatch_prepared_append(pending.prepared)
    head_bytes = client.trusted_head_envelope_bytes(namespace=prepared.namespace)

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_EVENT",
    ):
        client.verify_signed_head_envelope(
            signed_head_envelope_bytes=head_bytes[:-1] + b"0",
            expected_namespace=prepared.namespace,
            expected_sequence=receipt.sequence,
            expected_previous_event_sha256=prepared.expected_event_sha256,
            expected_event_sha256=prepared.event_sha256,
            expected_event_bytes=prepared.event_bytes,
        )

    assert journal.verify_integrity().pending_count == 1
