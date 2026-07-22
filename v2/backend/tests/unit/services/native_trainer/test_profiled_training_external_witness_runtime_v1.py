from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_training_external_witness_runtime_v1 as runtime_module,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FeatureSnapshotWriterLease,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_client_v1 import (
    PinnedProfiledTrainingExternalWitnessClientV1,
    ProfiledTrainingExternalWitnessClientV1Error,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_journal_v1 import (
    ProfiledTrainingExternalWitnessJournalV1,
    ProfiledTrainingExternalWitnessJournalV1Error,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_runtime_v1 import (
    PROFILED_WITNESS_RUNTIME_RESULT_V1_SCHEMA_VERSION,
    ProfiledTrainingExternalWitnessRuntimeV1,
    ProfiledTrainingExternalWitnessRuntimeV1Error,
    restore_pinned_profiled_training_external_witness_client_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_external_witness_client_v1 as witness_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_external_witness_journal_v1 as journal_support,
)


def _candidate_bundle(
    tmp_path: Path,
    client: PinnedProfiledTrainingExternalWitnessClientV1,
    *,
    label: str = "runtime-head",
) -> tuple[Any, Any]:
    prepared = journal_support._prepared(client, label=label)
    return prepared, journal_support._candidate(tmp_path, prepared=prepared)


def test_candidate_is_durable_before_runtime_performs_network_io(tmp_path: Path) -> None:
    _private_key, transport, client = journal_support._client_bundle()
    journal = journal_support._journal(tmp_path)
    _prepared, candidate = _candidate_bundle(tmp_path, client)
    lease = FeatureSnapshotWriterLease.acquire(journal.path)
    observed_pending: list[int] = []
    original_request = transport.request

    def request_with_durability_probe(**kwargs: Any) -> Any:
        if kwargs["method"] == "POST":
            observed_pending.append(journal.verify_integrity(writer_lease=lease).pending_count)
        return original_request(**kwargs)

    transport.request = request_with_durability_probe  # type: ignore[method-assign]
    try:
        runtime = ProfiledTrainingExternalWitnessRuntimeV1(
            journal=journal,
            client=client,
            writer_lease=lease,
        )
        result = runtime.anchor_head_candidate(head_candidate=candidate)
    finally:
        lease.release()

    assert observed_pending == [1]
    assert result.schema_version == PROFILED_WITNESS_RUNTIME_RESULT_V1_SCHEMA_VERSION
    assert result.signed_head_durably_anchored is True
    assert result.network_append_attempt_count == 1
    assert result.candidate_dispatched_after_recovery is True
    assert result.candidate_was_recovered is False
    assert result.journal_pending_count == 0
    assert result.journal_anchored_count == 1
    assert result.external_monotonic_manifest_head_verified is False
    assert result.full_consumption_external_ack_verified is False
    assert result.optimizer_admission_authorized is False
    assert result.checkpoint_write_authorized is False
    assert result.model_write_authorized is False
    assert result.prediction_authorized is False
    assert result.paper_trading_authorized is False
    assert result.live_execution_authorized is False
    assert result.order_submission_authorized is False
    assert result.execution_authorized is False
    assert result.runtime_wired is False
    with pytest.raises(
        ProfiledTrainingExternalWitnessRuntimeV1Error,
        match="PROFILED_WITNESS_RUNTIME_RESULT_CONTRACT_INVALID",
    ):
        replace(result, runtime_wired=True)


def test_ambiguous_remote_success_recovers_exact_request_after_restart(
    tmp_path: Path,
) -> None:
    private_key, transport, client = journal_support._client_bundle()
    journal = journal_support._journal(tmp_path)
    _prepared, candidate = _candidate_bundle(tmp_path, client, label="runtime-ambiguous")
    runtime = ProfiledTrainingExternalWitnessRuntimeV1(
        journal=journal,
        client=client,
    )
    transport.fail_after_append_once = True

    with pytest.raises(
        ProfiledTrainingExternalWitnessClientV1Error,
        match="PROFILED_WITNESS_HTTP_TRANSPORT_FAILED",
    ):
        runtime.anchor_head_candidate(head_candidate=candidate)

    assert journal.verify_integrity().pending_count == 1
    assert len(transport.events) == 1
    restarted_client = restore_pinned_profiled_training_external_witness_client_v1(
        journal=journal,
        transport=transport,
        witness_id=witness_support.WITNESS_ID,
        witness_public_key_bytes=witness_support._raw_public_key(private_key),
        expected_witness_public_key_sha256=hashlib.sha256(
            witness_support._raw_public_key(private_key)
        ).hexdigest(),
    )
    restarted = ProfiledTrainingExternalWitnessRuntimeV1(
        journal=journal,
        client=restarted_client,
    )
    recovered = restarted.recover_pending_appends()

    assert len(recovered) == 1
    assert recovered[0].operation_id
    assert journal.verify_integrity().pending_count == 0
    assert len(transport.events) == 1
    posts = [request for request in transport.requests if request[0] == "POST"]
    assert len(posts) == 2
    assert posts[0][2:] == posts[1][2:]


def test_recovered_current_candidate_is_not_dispatched_twice(tmp_path: Path) -> None:
    private_key, transport, client = journal_support._client_bundle()
    journal = journal_support._journal(tmp_path)
    _prepared, candidate = _candidate_bundle(tmp_path, client, label="runtime-recovered")
    runtime = ProfiledTrainingExternalWitnessRuntimeV1(journal=journal, client=client)
    transport.fail_after_append_once = True
    with pytest.raises(ProfiledTrainingExternalWitnessClientV1Error):
        runtime.anchor_head_candidate(head_candidate=candidate)

    restarted_client = restore_pinned_profiled_training_external_witness_client_v1(
        journal=journal,
        transport=transport,
        witness_id=witness_support.WITNESS_ID,
        witness_public_key_bytes=witness_support._raw_public_key(private_key),
        expected_witness_public_key_sha256=hashlib.sha256(
            witness_support._raw_public_key(private_key)
        ).hexdigest(),
    )
    restarted = ProfiledTrainingExternalWitnessRuntimeV1(
        journal=journal,
        client=restarted_client,
    )
    result = restarted.anchor_head_candidate(head_candidate=candidate)

    assert result.candidate_was_recovered is True
    assert result.candidate_dispatched_after_recovery is False
    assert result.network_append_attempt_count == 1
    assert result.recovered_operation_ids == (result.operation_id,)
    assert len(transport.events) == 1
    assert journal.verify_integrity().transition_count == 2


def test_already_anchored_candidate_replay_performs_no_network_io(tmp_path: Path) -> None:
    _private_key, transport, client = journal_support._client_bundle()
    journal = journal_support._journal(tmp_path)
    _prepared, candidate = _candidate_bundle(tmp_path, client, label="runtime-replay")
    runtime = ProfiledTrainingExternalWitnessRuntimeV1(journal=journal, client=client)
    first = runtime.anchor_head_candidate(head_candidate=candidate)
    request_count = len(transport.requests)
    replay = runtime.anchor_head_candidate(head_candidate=candidate)

    assert replay.operation_id == first.operation_id
    assert replay.network_append_attempt_count == 0
    assert replay.candidate_dispatched_after_recovery is False
    assert replay.candidate_was_recovered is False
    assert len(transport.requests) == request_count
    assert len(transport.events) == 1


def test_pending_operation_rejects_changed_witness_key_before_network(
    tmp_path: Path,
) -> None:
    _private_key, original_transport, original_client = journal_support._client_bundle()
    journal = journal_support._journal(tmp_path)
    prepared, candidate = _candidate_bundle(tmp_path, original_client, label="runtime-key")
    journal.persist_prepared_append(
        client=original_client,
        prepared=prepared,
        head_candidate=candidate,
    )
    _wrong_private, wrong_transport, wrong_client = journal_support._client_bundle()
    runtime = ProfiledTrainingExternalWitnessRuntimeV1(
        journal=journal,
        client=wrong_client,
    )

    with pytest.raises(
        ProfiledTrainingExternalWitnessJournalV1Error,
        match="PROFILED_WITNESS_JOURNAL_CLIENT_REAUTHENTICATION_FAILED",
    ):
        runtime.recover_pending_appends()

    assert original_transport.requests == []
    assert wrong_transport.requests == []
    assert journal.verify_integrity().pending_count == 1


def test_restore_helper_reauthenticates_durable_signed_head(tmp_path: Path) -> None:
    private_key, transport, client = journal_support._client_bundle()
    journal = journal_support._journal(tmp_path)
    _prepared, candidate = _candidate_bundle(tmp_path, client, label="runtime-restore")
    runtime = ProfiledTrainingExternalWitnessRuntimeV1(journal=journal, client=client)
    result = runtime.anchor_head_candidate(head_candidate=candidate)

    restored = restore_pinned_profiled_training_external_witness_client_v1(
        journal=journal,
        transport=transport,
        witness_id=witness_support.WITNESS_ID,
        witness_public_key_bytes=witness_support._raw_public_key(private_key),
        expected_witness_public_key_sha256=hashlib.sha256(
            witness_support._raw_public_key(private_key)
        ).hexdigest(),
    )

    assert restored.trusted_head_envelope_bytes(
        namespace=candidate.namespace
    ) == client.trusted_head_envelope_bytes(namespace=candidate.namespace)
    assert result.event_sha256 == candidate.candidate_event_sha256


def test_pending_recovery_resource_limit_fails_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _private_key, transport, client = journal_support._client_bundle()
    journal = journal_support._journal(tmp_path)
    prepared, candidate = _candidate_bundle(tmp_path, client, label="runtime-resource")
    journal.persist_prepared_append(
        client=client,
        prepared=prepared,
        head_candidate=candidate,
    )
    monkeypatch.setattr(
        runtime_module,
        "MAX_PROFILED_WITNESS_RUNTIME_PENDING_RECOVERIES",
        0,
    )
    runtime = ProfiledTrainingExternalWitnessRuntimeV1(journal=journal, client=client)

    with pytest.raises(
        ProfiledTrainingExternalWitnessRuntimeV1Error,
        match="PROFILED_WITNESS_RUNTIME_PENDING_RECOVERY_RESOURCE_LIMIT_EXCEEDED",
    ):
        runtime.recover_pending_appends()

    assert transport.requests == []
    assert journal.verify_integrity().pending_count == 1


def test_unrelated_pending_operation_is_anchored_before_new_candidate_dispatch(
    tmp_path: Path,
) -> None:
    _private_key, transport, client = journal_support._client_bundle()
    journal = journal_support._journal(tmp_path)
    pending_prepared, pending_candidate = _candidate_bundle(
        tmp_path,
        client,
        label="runtime-older-pending",
    )
    journal.persist_prepared_append(
        client=client,
        prepared=pending_prepared,
        head_candidate=pending_candidate,
    )
    new_prepared = journal_support._prepared(
        client,
        label="runtime-new-other-namespace",
        namespace="unit/runtime-other-namespace",
    )
    new_candidate = journal_support._candidate(tmp_path, prepared=new_prepared)
    runtime = ProfiledTrainingExternalWitnessRuntimeV1(journal=journal, client=client)

    # The shared fake witness intentionally implements only its default
    # namespace.  The second append therefore fails, but only after the older
    # default-namespace operation has been durably anchored.
    with pytest.raises(ProfiledTrainingExternalWitnessClientV1Error):
        runtime.anchor_head_candidate(head_candidate=new_candidate)

    posts = [request for request in transport.requests if request[0] == "POST"]
    assert len(posts) == 2
    assert posts[0][1].endswith("/profiled-trainer/events:compare-and-append")
    assert posts[1][1].endswith("/unit%2Fruntime-other-namespace/events:compare-and-append")
    report = journal.verify_integrity()
    assert (report.anchored_count, report.pending_count) == (1, 1)


def test_wrong_writer_lease_is_rejected_at_runtime_construction(tmp_path: Path) -> None:
    _private_key, _transport, client = journal_support._client_bundle()
    journal = journal_support._journal(tmp_path)
    wrong_path = (tmp_path / "wrong-runtime-journal.sqlite3").absolute()
    wrong_lease = FeatureSnapshotWriterLease.acquire(wrong_path)
    try:
        with pytest.raises(
            ProfiledTrainingExternalWitnessRuntimeV1Error,
            match="PROFILED_WITNESS_RUNTIME_WRITER_LEASE_INVALID",
        ):
            ProfiledTrainingExternalWitnessRuntimeV1(
                journal=journal,
                client=client,
                writer_lease=wrong_lease,
            )
    finally:
        wrong_lease.release()


def test_remote_success_before_local_anchor_failure_recovers_idempotently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _private_key, transport, client = journal_support._client_bundle()
    journal = journal_support._journal(tmp_path)
    _prepared, candidate = _candidate_bundle(
        tmp_path,
        client,
        label="runtime-anchor-failure",
    )
    runtime = ProfiledTrainingExternalWitnessRuntimeV1(journal=journal, client=client)
    original_commit = ProfiledTrainingExternalWitnessJournalV1.commit_head_anchored
    injected = False

    def fail_first_anchor(
        self: ProfiledTrainingExternalWitnessJournalV1,
        **kwargs: Any,
    ) -> Any:
        nonlocal injected
        if not injected:
            injected = True
            raise ProfiledTrainingExternalWitnessJournalV1Error("INJECTED_RUNTIME_ANCHOR_FAILURE")
        return original_commit(self, **kwargs)

    monkeypatch.setattr(
        ProfiledTrainingExternalWitnessJournalV1,
        "commit_head_anchored",
        fail_first_anchor,
    )
    with pytest.raises(
        ProfiledTrainingExternalWitnessJournalV1Error,
        match="INJECTED_RUNTIME_ANCHOR_FAILURE",
    ):
        runtime.anchor_head_candidate(head_candidate=candidate)
    assert len(transport.events) == 1
    assert journal.verify_integrity().pending_count == 1

    result = runtime.anchor_head_candidate(head_candidate=candidate)
    assert result.candidate_was_recovered is True
    assert result.candidate_dispatched_after_recovery is False
    assert result.network_append_attempt_count == 1
    assert journal.verify_integrity().pending_count == 0
    assert len(transport.events) == 1
