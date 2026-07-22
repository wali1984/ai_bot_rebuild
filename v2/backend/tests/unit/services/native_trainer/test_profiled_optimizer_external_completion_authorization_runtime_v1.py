from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_authorization_client_v1 as client_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_authorization_journal_v1 as journal_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_authorization_runtime_v1 as runtime_module,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FeatureSnapshotWriterLease,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_optimizer_external_completion_request_v1 as request_support,
)

adapter_evidence = request_support.adapter_evidence
AUTHORIZATION_ANCHORED = journal_module.AUTHORIZATION_ANCHORED
PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RUNTIME_V1_SCHEMA_VERSION = (
    runtime_module.PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RUNTIME_V1_SCHEMA_VERSION
)
PinnedProfiledOptimizerCompletionAuthorizationClientV1 = (
    client_module.PinnedProfiledOptimizerCompletionAuthorizationClientV1
)
ProfiledOptimizerCompletionAuthorizationClientV1Error = (
    client_module.ProfiledOptimizerCompletionAuthorizationClientV1Error
)
ProfiledOptimizerCompletionAuthorizationJournalV1 = (
    journal_module.ProfiledOptimizerCompletionAuthorizationJournalV1
)
ProfiledOptimizerCompletionAuthorizationJournalV1Error = (
    journal_module.ProfiledOptimizerCompletionAuthorizationJournalV1Error
)
ProfiledOptimizerCompletionAuthorizationRuntimeV1 = (
    runtime_module.ProfiledOptimizerCompletionAuthorizationRuntimeV1
)
ProfiledOptimizerCompletionAuthorizationRuntimeV1Error = (
    runtime_module.ProfiledOptimizerCompletionAuthorizationRuntimeV1Error
)
ProfiledOptimizerCompletionAuthorizationWireResponseV1 = (
    client_module.ProfiledOptimizerCompletionAuthorizationWireResponseV1
)


@dataclass
class _RuntimeTransport:
    response: ProfiledOptimizerCompletionAuthorizationWireResponseV1
    requests: list[dict[str, Any]] = field(default_factory=list)
    observer: Callable[[], None] | None = None
    fail_after_dispatch_once: bool = False

    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        idempotency_key: str,
    ) -> ProfiledOptimizerCompletionAuthorizationWireResponseV1:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "idempotency_key": idempotency_key,
            }
        )
        if self.observer is not None:
            self.observer()
        if self.fail_after_dispatch_once:
            self.fail_after_dispatch_once = False
            raise ProfiledOptimizerCompletionAuthorizationClientV1Error(
                "INJECTED_AMBIGUOUS_COMPLETION_AUTHORIZATION"
            )
        return self.response


def _journal(tmp_path: Path) -> ProfiledOptimizerCompletionAuthorizationJournalV1:
    return ProfiledOptimizerCompletionAuthorizationJournalV1(
        (tmp_path / "authorization-journal.sqlite3").absolute(),
        immutable_store=ImmutableSourcePayloadStore(
            (tmp_path / "authorization-cas").absolute()
        ),
    )


def _client_bundle(
    evidence: dict[str, Any],
) -> tuple[
    _RuntimeTransport,
    PinnedProfiledOptimizerCompletionAuthorizationClientV1,
]:
    prepared = request_support._prepared(evidence)
    envelope = request_support._signed_envelope(prepared)
    transport = _RuntimeTransport(
        ProfiledOptimizerCompletionAuthorizationWireResponseV1(
            status_code=200,
            content_type="application/json",
            body=envelope,
        )
    )
    client = PinnedProfiledOptimizerCompletionAuthorizationClientV1(
        transport=transport,
        witness_id=prepared.witness_id,
        witness_public_key_bytes=evidence["public_key"],
        expected_witness_public_key_sha256=evidence["public_key_sha256"],
    )
    return transport, client


def _arguments(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "authenticated_manifest": evidence["authenticated"],
        "completion": evidence["completion"],
        "final_page": evidence["final_page"],
        "completion_staging_store": evidence["staging_store"],
        "manifest_head_anchor": request_support._head_anchor(evidence),
    }


def _runtime(
    *,
    journal: ProfiledOptimizerCompletionAuthorizationJournalV1,
    client: PinnedProfiledOptimizerCompletionAuthorizationClientV1,
    challenge_source: Callable[[], bytes] = lambda: request_support.FIXED_CHALLENGE,
) -> ProfiledOptimizerCompletionAuthorizationRuntimeV1:
    return ProfiledOptimizerCompletionAuthorizationRuntimeV1(
        journal=journal,
        client=client,
        challenge_source=challenge_source,
    )


def test_request_is_durable_before_network_and_admission_only_is_anchored(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    transport, client = _client_bundle(adapter_evidence)
    observed_pending: list[int] = []
    lease = FeatureSnapshotWriterLease.acquire(journal.path)
    transport.observer = lambda: observed_pending.append(
        journal.verify_integrity(writer_lease=lease).pending_count
    )
    try:
        result = ProfiledOptimizerCompletionAuthorizationRuntimeV1(
            journal=journal,
            client=client,
            challenge_source=lambda: request_support.FIXED_CHALLENGE,
            writer_lease=lease,
        ).authorize_completion(**_arguments(adapter_evidence))
    finally:
        lease.release()

    assert observed_pending == [1]
    assert result.schema_version == (
        PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RUNTIME_V1_SCHEMA_VERSION
    )
    assert result.network_authorization_attempt_count == 1
    assert result.request_dispatched_after_recovery is True
    assert result.request_was_recovered is False
    assert result.request_was_already_anchored is False
    assert result.request_durably_prepared is True
    assert result.signed_authorization_durably_anchored is True
    assert result.external_monotonic_manifest_head_verified is True
    assert result.full_consumption_external_ack_verified is True
    assert result.profiled_optimizer_admission_authorized is True
    assert result.optimizer_execution_authorized is False
    assert result.checkpoint_write_authorized is False
    assert result.model_write_authorized is False
    assert result.prediction_authorized is False
    assert result.paper_trading_authorized is False
    assert result.live_execution_authorized is False
    assert result.order_submission_authorized is False
    assert result.execution_authorized is False
    assert result.runtime_wired is False
    record = journal.load_request_for_completion(
        witness_id=client.witness_id,
        authorization_namespace=request_support.AUTHORIZATION_NAMESPACE,
        completion_event_sha256=adapter_evidence["completion"].completion_event_sha256,
        witness_public_key_bytes=client.witness_public_key_bytes,
    )
    assert record is not None and record.state == AUTHORIZATION_ANCHORED
    assert record.operation_id == result.operation_id
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationRuntimeV1Error,
        match="RUNTIME_RESULT_INVALID",
    ):
        replace(result, optimizer_execution_authorized=True)


def test_ambiguous_dispatch_recovers_exact_durable_request_after_restart(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    transport, client = _client_bundle(adapter_evidence)
    transport.fail_after_dispatch_once = True
    first_runtime = _runtime(journal=journal, client=client)

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationClientV1Error,
        match="INJECTED_AMBIGUOUS",
    ):
        first_runtime.authorize_completion(**_arguments(adapter_evidence))
    assert journal.verify_integrity().pending_count == 1
    assert len(transport.requests) == 1

    def challenge_must_not_be_regenerated() -> bytes:
        raise AssertionError("durable challenge must be reused")

    restarted = _runtime(
        journal=journal,
        client=client,
        challenge_source=challenge_must_not_be_regenerated,
    )
    result = restarted.authorize_completion(**_arguments(adapter_evidence))

    assert result.request_was_recovered is True
    assert result.request_dispatched_after_recovery is False
    assert result.request_was_already_anchored is False
    assert result.network_authorization_attempt_count == 1
    assert result.recovered_operation_ids == (result.operation_id,)
    assert journal.verify_integrity().pending_count == 0
    assert len(transport.requests) == 2
    assert transport.requests[0] == transport.requests[1]


def test_anchored_completion_replay_uses_no_network_or_new_challenge(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    transport, client = _client_bundle(adapter_evidence)
    first = _runtime(journal=journal, client=client).authorize_completion(
        **_arguments(adapter_evidence)
    )
    request_count = len(transport.requests)

    def challenge_must_not_be_regenerated() -> bytes:
        raise AssertionError("anchored request must be replayed")

    replay = _runtime(
        journal=journal,
        client=client,
        challenge_source=challenge_must_not_be_regenerated,
    ).authorize_completion(**_arguments(adapter_evidence))

    assert replay.operation_id == first.operation_id
    assert replay.request_was_already_anchored is True
    assert replay.request_was_recovered is False
    assert replay.request_dispatched_after_recovery is False
    assert replay.network_authorization_attempt_count == 0
    assert len(transport.requests) == request_count


def test_changed_local_binding_fails_before_pending_request_is_dispatched(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    transport, client = _client_bundle(adapter_evidence)
    transport.fail_after_dispatch_once = True
    runtime = _runtime(journal=journal, client=client)
    with pytest.raises(ProfiledOptimizerCompletionAuthorizationClientV1Error):
        runtime.authorize_completion(**_arguments(adapter_evidence))
    request_count = len(transport.requests)
    changed = _arguments(adapter_evidence)
    changed["manifest_head_anchor"] = replace(
        changed["manifest_head_anchor"],
        event_sha256=hashlib.sha256(b"changed-head").hexdigest(),
    )

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationRuntimeV1Error,
        match="LOCAL_BINDING_MISMATCH",
    ):
        runtime.authorize_completion(**changed)

    assert len(transport.requests) == request_count
    assert journal.verify_integrity().pending_count == 1


def test_remote_success_before_local_anchor_failure_recovers_idempotently(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal(tmp_path)
    transport, client = _client_bundle(adapter_evidence)
    runtime = _runtime(journal=journal, client=client)
    original_commit = (
        ProfiledOptimizerCompletionAuthorizationJournalV1.commit_authorization_anchored
    )
    injected = False

    def fail_first_anchor(
        self: ProfiledOptimizerCompletionAuthorizationJournalV1,
        **kwargs: Any,
    ) -> Any:
        nonlocal injected
        if not injected:
            injected = True
            raise ProfiledOptimizerCompletionAuthorizationJournalV1Error(
                "INJECTED_AUTHORIZATION_ANCHOR_FAILURE"
            )
        return original_commit(self, **kwargs)

    monkeypatch.setattr(
        ProfiledOptimizerCompletionAuthorizationJournalV1,
        "commit_authorization_anchored",
        fail_first_anchor,
    )
    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationJournalV1Error,
        match="INJECTED_AUTHORIZATION_ANCHOR_FAILURE",
    ):
        runtime.authorize_completion(**_arguments(adapter_evidence))
    assert journal.verify_integrity().pending_count == 1
    assert len(transport.requests) == 1

    result = runtime.authorize_completion(**_arguments(adapter_evidence))
    assert result.request_was_recovered is True
    assert result.network_authorization_attempt_count == 1
    assert journal.verify_integrity().pending_count == 0
    assert len(transport.requests) == 2
    assert transport.requests[0] == transport.requests[1]


def test_pending_request_rejects_changed_witness_key_before_network(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    transport, client = _client_bundle(adapter_evidence)
    transport.fail_after_dispatch_once = True
    with pytest.raises(ProfiledOptimizerCompletionAuthorizationClientV1Error):
        _runtime(journal=journal, client=client).authorize_completion(
            **_arguments(adapter_evidence)
        )
    request_count = len(transport.requests)
    wrong_key = b"w" * 32
    wrong_client = PinnedProfiledOptimizerCompletionAuthorizationClientV1(
        transport=transport,
        witness_id=client.witness_id,
        witness_public_key_bytes=wrong_key,
        expected_witness_public_key_sha256=hashlib.sha256(wrong_key).hexdigest(),
    )

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationRuntimeV1Error,
        match="HEAD_WITNESS_MISMATCH",
    ):
        _runtime(journal=journal, client=wrong_client).authorize_completion(
            **_arguments(adapter_evidence)
        )

    assert len(transport.requests) == request_count
    assert journal.verify_integrity().pending_count == 1


def test_pending_recovery_resource_limit_fails_before_network(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal(tmp_path)
    transport, client = _client_bundle(adapter_evidence)
    transport.fail_after_dispatch_once = True
    runtime = _runtime(journal=journal, client=client)
    with pytest.raises(ProfiledOptimizerCompletionAuthorizationClientV1Error):
        runtime.authorize_completion(**_arguments(adapter_evidence))
    request_count = len(transport.requests)
    monkeypatch.setattr(
        runtime_module,
        "MAX_PROFILED_OPTIMIZER_AUTHORIZATION_PENDING_RECOVERIES",
        0,
    )

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationRuntimeV1Error,
        match="PENDING_RECOVERY_RESOURCE_LIMIT_EXCEEDED",
    ):
        runtime.recover_pending_authorizations()

    assert len(transport.requests) == request_count
    assert journal.verify_integrity().pending_count == 1


def test_invalid_signed_response_leaves_exact_request_pending(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    transport, client = _client_bundle(adapter_evidence)
    transport.response = ProfiledOptimizerCompletionAuthorizationWireResponseV1(
        status_code=200,
        content_type="application/json",
        body=b"{}",
    )

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationClientV1Error,
        match="RESPONSE_UNVERIFIED",
    ):
        _runtime(journal=journal, client=client).authorize_completion(
            **_arguments(adapter_evidence)
        )

    assert len(transport.requests) == 1
    report = journal.verify_integrity()
    assert (report.operation_count, report.pending_count) == (1, 1)


def test_zero_admitted_inventory_fails_before_challenge_journal_or_network(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    transport, client = _client_bundle(adapter_evidence)
    arguments = _arguments(adapter_evidence)
    arguments["authenticated_manifest"] = replace(
        adapter_evidence["authenticated"],
        admitted_example_count=0,
        label_unavailable_count=(
            adapter_evidence["authenticated"].total_profiled_samples
        ),
    )
    challenge_calls = 0

    def challenge_source() -> bytes:
        nonlocal challenge_calls
        challenge_calls += 1
        return request_support.FIXED_CHALLENGE

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationRuntimeV1Error,
        match="ZERO_ADMITTED_FORBIDDEN",
    ):
        _runtime(
            journal=journal,
            client=client,
            challenge_source=challenge_source,
        ).authorize_completion(**arguments)

    assert challenge_calls == 0
    assert transport.requests == []
    assert not journal.path.exists()


def test_head_witness_mismatch_fails_before_journal_or_network(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    transport, client = _client_bundle(adapter_evidence)
    arguments = _arguments(adapter_evidence)
    arguments["manifest_head_anchor"] = replace(
        arguments["manifest_head_anchor"],
        witness_id="different/profiled-witness",
    )

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationRuntimeV1Error,
        match="HEAD_WITNESS_MISMATCH",
    ):
        _runtime(journal=journal, client=client).authorize_completion(**arguments)

    assert transport.requests == []
    assert not journal.path.exists()


@pytest.mark.parametrize("challenge", (b"x" * 31, bytearray(b"x" * 32)))
def test_invalid_generated_challenge_fails_before_persistence_or_network(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
    challenge: Any,
) -> None:
    journal = _journal(tmp_path)
    transport, client = _client_bundle(adapter_evidence)
    runtime = _runtime(
        journal=journal,
        client=client,
        challenge_source=lambda: challenge,
    )

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationRuntimeV1Error,
        match="CHALLENGE_INVALID",
    ):
        runtime.authorize_completion(**_arguments(adapter_evidence))

    assert transport.requests == []
    report = journal.verify_integrity()
    assert (report.operation_count, report.pending_count) == (0, 0)


def test_wrong_writer_lease_is_rejected_at_construction(
    tmp_path: Path,
    adapter_evidence: dict[str, Any],
) -> None:
    journal = _journal(tmp_path)
    _transport, client = _client_bundle(adapter_evidence)
    wrong_path = (tmp_path / "wrong-journal.sqlite3").absolute()
    wrong_lease = FeatureSnapshotWriterLease.acquire(wrong_path)
    try:
        with pytest.raises(
            ProfiledOptimizerCompletionAuthorizationRuntimeV1Error,
            match="WRITER_LEASE_INVALID",
        ):
            ProfiledOptimizerCompletionAuthorizationRuntimeV1(
                journal=journal,
                client=client,
                writer_lease=wrong_lease,
            )
    finally:
        wrong_lease.release()


def test_runtime_has_no_optimizer_checkpoint_signer_or_trading_authority() -> None:
    module_path = (
        Path(__file__).resolve().parents[6]
        / "v2/backend/app/services/native_trainer/"
        "profiled_optimizer_external_completion_authorization_runtime_v1.py"
    )
    source = module_path.read_text(encoding="utf-8")

    assert "Ed25519PrivateKey" not in source
    assert "optimizer.step" not in source
    assert "torch.save" not in source
    assert "submit_order" not in source
    assert "profiled_training_external_witness_journal_v1" not in source
