from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_authorization_client_v1 as completion_client_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_authorization_journal_v1 as completion_journal_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_authorization_runtime_v1 as completion_runtime_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_request_v1 as completion_request_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_coordinator_state_v1 as state_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_coordinator_v1 as coordinator_module,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_client_v1 import (
    ProfiledTrainingExternalWitnessClientV1Error,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_runtime_v1 import (
    ProfiledTrainingExternalWitnessRuntimeV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_coordinator_v1 import (
    PROFILED_COORDINATOR_COMPLETION_AUTHORIZED,
    PROFILED_COORDINATOR_LOCAL_COMPLETION,
    PROFILED_COORDINATOR_NO_NEW_CYCLE,
    PROFILED_COORDINATOR_WAITING_COMPLETION_AUTHORIZATION,
    PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS,
    ProfiledTrainingObservationCoordinatorV1,
    ProfiledTrainingObservationCoordinatorV1Error,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_base_publisher_cycle_status_v1 as status_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_model_feature_snapshot_record_v1 as base_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_optimizer_external_completion_request_v1 as completion_request_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_external_witness_client_v1 as witness_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_external_witness_journal_v1 as journal_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_observation_coordinator_state_v1 as state_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_observation_manifest_v1 as manifest_support,
)

PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED = (
    state_module.PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED
)
PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED = (
    state_module.PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
)
ProfiledTrainingObservationCoordinatorStateV1Error = (
    state_module.ProfiledTrainingObservationCoordinatorStateV1Error
)
ProfiledOptimizerCompletionAuthorizationClientV1Error = (
    completion_client_module.ProfiledOptimizerCompletionAuthorizationClientV1Error
)
ProfiledOptimizerCompletionAuthorizationRuntimeV1 = (
    completion_runtime_module.ProfiledOptimizerCompletionAuthorizationRuntimeV1
)


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("profiled-coordinator-caller")
    source_root = root / "sources"
    source_root.mkdir()
    base = base_support._build_evidence(root / "base")
    ledger, archive, observation, cost_root = manifest_support._setup_sources(
        source_root,
        base,
    )
    observation_dt = datetime.fromisoformat(observation.replace("Z", "+00:00")).astimezone(UTC)
    factory_dt = observation_dt + timedelta(hours=1)
    return {
        "ledger": ledger,
        "archive": archive,
        "observation": observation,
        "factory_dt": factory_dt,
        "cost_root": cost_root,
        "staging": ImmutableSourcePayloadStore((root / "staging-cas").absolute()),
    }


def _publisher_status(
    tmp_path: Path,
    *,
    observation: str,
    classification: str = "CYCLE_COMPLETE_ALL_SELECTED_AUTHENTICATED_OR_UNCHANGED",
) -> Path:
    status = status_support._status()
    completed = datetime.fromisoformat(observation.replace("Z", "+00:00")).astimezone(UTC)
    clocks = tuple(
        (completed - timedelta(seconds=offset))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
        for offset in (3, 2, 1, 0)
    )
    status.update(
        {
            "cycle_started_at": clocks[0],
            "discovery_completed_at": clocks[1],
            "selection_at": clocks[2],
            "cycle_completed_at": clocks[3],
            "cycle_elapsed_seconds": 3.0,
            "classification": classification,
        }
    )
    return status_support._write_status(tmp_path, status)


def _witness_runtime(
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ProfiledTrainingExternalWitnessRuntimeV1, Any]:
    monkeypatch.setattr(witness_support, "NAMESPACE", state_support.NAMESPACE)
    _private_key, transport, client = journal_support._client_bundle()
    journal_root = tmp_path / "witness"
    journal_root.mkdir()
    journal = journal_support._journal(journal_root)
    return (
        ProfiledTrainingExternalWitnessRuntimeV1(journal=journal, client=client),
        transport,
    )


@dataclass
class _SigningCompletionAuthorizationTransport:
    private_key: Any
    requests: list[dict[str, Any]] = field(default_factory=list)
    fail_after_authorization_once: bool = False

    def request(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        idempotency_key: str,
    ) -> Any:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "idempotency_key": idempotency_key,
            }
        )
        if self.fail_after_authorization_once:
            self.fail_after_authorization_once = False
            raise ProfiledOptimizerCompletionAuthorizationClientV1Error(
                "INJECTED_AMBIGUOUS_COMPLETION_AUTHORIZATION"
            )
        prepared = (
            completion_request_module.rehydrate_profiled_optimizer_external_completion_prepared_request_v1(
                request_bytes=body,
            )
        )
        envelope = completion_request_support._signed_envelope(
            prepared,
            private_key=self.private_key,
        )
        return completion_client_module.ProfiledOptimizerCompletionAuthorizationWireResponseV1(
            status_code=200,
            content_type="application/json",
            body=envelope,
        )


def _authorization_runtimes(
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    ProfiledTrainingExternalWitnessRuntimeV1,
    Any,
    ProfiledOptimizerCompletionAuthorizationRuntimeV1,
    _SigningCompletionAuthorizationTransport,
]:
    monkeypatch.setattr(witness_support, "NAMESPACE", state_support.NAMESPACE)
    private_key, head_transport, head_client = journal_support._client_bundle()
    head_root = tmp_path / "witness"
    head_root.mkdir()
    head_runtime = ProfiledTrainingExternalWitnessRuntimeV1(
        journal=journal_support._journal(head_root),
        client=head_client,
    )
    public_key = witness_support._raw_public_key(private_key)
    completion_transport = _SigningCompletionAuthorizationTransport(private_key)
    completion_client = (
        completion_client_module.PinnedProfiledOptimizerCompletionAuthorizationClientV1(
            transport=completion_transport,
            witness_id=witness_support.WITNESS_ID,
            witness_public_key_bytes=public_key,
            expected_witness_public_key_sha256=hashlib.sha256(public_key).hexdigest(),
        )
    )
    completion_root = tmp_path / "completion-authorization"
    completion_root.mkdir()
    completion_journal = (
        completion_journal_module.ProfiledOptimizerCompletionAuthorizationJournalV1(
            (completion_root / "journal.sqlite3").absolute(),
            immutable_store=ImmutableSourcePayloadStore(
                (completion_root / "cas").absolute()
            ),
        )
    )
    return (
        head_runtime,
        head_transport,
        ProfiledOptimizerCompletionAuthorizationRuntimeV1(
            journal=completion_journal,
            client=completion_client,
        ),
        completion_transport,
    )


def _state_store(tmp_path: Path) -> Any:
    root = tmp_path / "state"
    root.mkdir()
    return state_support._state_store(root)


def _coordinator(
    tmp_path: Path,
    *,
    evidence: dict[str, Any],
    state_store: Any,
    status_path: Path,
    witness_runtime: ProfiledTrainingExternalWitnessRuntimeV1 | None,
    completion_authorization_runtime: (
        ProfiledOptimizerCompletionAuthorizationRuntimeV1 | None
    ) = None,
    ledger: DurableFeatureSnapshotLedger | None = None,
    label_archive: DurableCanonical5mLabelArchive | None = None,
    staging_store: ImmutableSourcePayloadStore | None = None,
    manifest_key: bytes = state_support.MANIFEST_KEY,
    wall_clock: Any = None,
) -> ProfiledTrainingObservationCoordinatorV1:
    observed_clock = wall_clock or (lambda: evidence["factory_dt"])
    return ProfiledTrainingObservationCoordinatorV1(
        state_store=state_store,
        status_path=status_path,
        feature_ledger=ledger or evidence["ledger"],
        label_archive=label_archive or evidence["archive"],
        trusted_immutable_cost_store_root=evidence["cost_root"],
        manifest_root=(tmp_path / "manifests").absolute(),
        staging_store=staging_store or evidence["staging"],
        namespace=state_support.NAMESPACE,
        consumer_lane=state_support.CONSUMER_LANE,
        manifest_auth_key_id=state_support.MANIFEST_KEY_ID,
        manifest_hmac_key=manifest_key,
        head_auth_key_id=state_support.HEAD_KEY_ID,
        head_hmac_key=state_support.HEAD_KEY,
        epoch_auth_key_id=state_support.EPOCH_KEY_ID,
        epoch_hmac_key=state_support.EPOCH_KEY,
        page_size=1,
        witness_runtime=witness_runtime,
        completion_authorization_runtime=completion_authorization_runtime,
        wall_clock=observed_clock,
    )


def test_waits_without_witness_then_resumes_without_reading_new_status(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    state_store = _state_store(tmp_path)
    waiting = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=None,
    ).run_once()

    assert waiting.classification == PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS
    assert waiting.phase == PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED
    assert waiting.publisher_status_read_this_invocation is True
    assert waiting.new_cycle_started_this_invocation is True
    assert waiting.signed_head_durably_anchored is False
    assert waiting.full_consumption_locally_verified is False
    assert waiting.runtime_wired is False

    status_path.unlink()
    resumed = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=None,
    ).run_once()

    assert resumed.classification == PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS
    assert resumed.publisher_status_read_this_invocation is False
    assert resumed.new_cycle_started_this_invocation is False
    assert resumed.state_transitions_committed == 0
    assert resumed.cycle_id == waiting.cycle_id


def test_witness_resume_reaches_local_completion_and_same_cycle_is_noop(
    tmp_path: Path,
    evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    state_store = _state_store(tmp_path)
    unwitnessed = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=None,
    ).run_once()
    runtime, transport, completion_runtime, completion_transport = (
        _authorization_runtimes(tmp_path, monkeypatch=monkeypatch)
    )
    status_path.unlink()

    completed = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=runtime,
        completion_authorization_runtime=completion_runtime,
    ).run_once()

    assert unwitnessed.phase == PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED
    assert completed.classification == PROFILED_COORDINATOR_COMPLETION_AUTHORIZED
    assert completed.phase == PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
    assert completed.publisher_status_read_this_invocation is False
    assert completed.signed_head_durably_anchored is True
    assert completed.full_consumption_locally_verified is True
    assert completed.page_receipts_staged_this_invocation >= 1
    assert completed.complete_state_chain_verified is True
    assert completed.signed_completion_authorization_durably_anchored is True
    assert completed.external_monotonic_manifest_head_verified is True
    assert completed.full_consumption_external_ack_verified is True
    assert completed.optimizer_admission_authorized is True
    assert completed.optimizer_execution_authorized is False
    assert completed.checkpoint_write_authorized is False
    assert completed.model_write_authorized is False
    assert completed.prediction_authorized is False
    assert completed.paper_trading_authorized is False
    assert completed.live_execution_authorized is False
    assert completed.order_submission_authorized is False
    assert completed.execution_authorized is False
    assert completed.runtime_wired is False
    cursor_after_authorization = state_store.load()
    assert cursor_after_authorization is not None
    for field_name in (
        "external_monotonic_manifest_head_verified",
        "full_consumption_external_ack_verified",
        "optimizer_admission_authorized",
        "checkpoint_write_authorized",
        "model_write_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "order_submission_authorized",
        "execution_authorized",
        "runtime_wired",
    ):
        assert getattr(cursor_after_authorization, field_name) is False
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorV1Error,
        match="PROFILED_COORDINATOR_RESULT_INVALID",
    ):
        replace(completed, completion_authorization_request_sha256=None)
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorV1Error,
        match="PROFILED_COORDINATOR_RESULT_INVALID",
    ):
        replace(completed, optimizer_execution_authorized=True)

    request_count = len(transport.requests)
    completion_request_count = len(completion_transport.requests)
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    noop = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=runtime,
        completion_authorization_runtime=completion_runtime,
    ).run_once()

    assert noop.classification == PROFILED_COORDINATOR_NO_NEW_CYCLE
    assert noop.state_transitions_committed == 0
    assert noop.publisher_status_read_this_invocation is True
    assert len(transport.requests) == request_count
    assert len(completion_transport.requests) == completion_request_count
    assert noop.signed_completion_authorization_durably_anchored is True
    assert noop.optimizer_admission_authorized is True
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorV1Error,
        match="PROFILED_COORDINATOR_RESULT_INVALID",
    ):
        replace(noop, runtime_wired=True)
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorV1Error,
        match="PROFILED_COORDINATOR_COMPLETION_RESULT_INVALID",
    ):
        replace(noop, classification=PROFILED_COORDINATOR_LOCAL_COMPLETION)
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorV1Error,
        match="PROFILED_COORDINATOR_RESULT_INVALID",
    ):
        replace(
            noop,
            witness_runtime_configured=True,
            witness_network_append_attempts=2,
        )

    conflicting_status_path = _publisher_status(
        tmp_path,
        observation=evidence["observation"],
        classification="RESOURCE_HEADROOM_HOLD",
    )
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_SAME_CUTOFF_BINDING_CONFLICT",
    ):
        _coordinator(
            tmp_path,
            evidence=evidence,
            state_store=state_store,
            status_path=conflicting_status_path,
            witness_runtime=runtime,
            completion_authorization_runtime=completion_runtime,
        ).run_once()

    earlier_observation = (
        datetime.fromisoformat(evidence["observation"].replace("Z", "+00:00"))
        .astimezone(UTC)
        - timedelta(minutes=5)
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
    rollback_status_path = _publisher_status(tmp_path, observation=earlier_observation)
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_OBSERVATION_ROLLBACK",
    ):
        _coordinator(
            tmp_path,
            evidence=evidence,
            state_store=state_store,
            status_path=rollback_status_path,
            witness_runtime=runtime,
            completion_authorization_runtime=completion_runtime,
        ).run_once()

    later_observation = (
        datetime.fromisoformat(evidence["observation"].replace("Z", "+00:00"))
        .astimezone(UTC)
        + timedelta(minutes=5)
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
    later_status_path = _publisher_status(tmp_path, observation=later_observation)
    successor = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=later_status_path,
        witness_runtime=runtime,
        completion_authorization_runtime=completion_runtime,
    ).run_once()

    assert successor.classification == PROFILED_COORDINATOR_COMPLETION_AUTHORIZED
    assert successor.new_cycle_started_this_invocation is True
    assert successor.publisher_status_read_this_invocation is True
    assert successor.head_revision == 2
    assert successor.cycle_id != completed.cycle_id
    assert len(transport.events) == 2
    assert len(completion_transport.requests) == 2


def test_positive_completion_without_authorization_runtime_cannot_advance_cycle(
    tmp_path: Path,
    evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    state_store = _state_store(tmp_path)
    witness_runtime, _transport = _witness_runtime(
        tmp_path,
        monkeypatch=monkeypatch,
    )
    waiting = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=witness_runtime,
    ).run_once()
    assert waiting.classification == (
        PROFILED_COORDINATOR_WAITING_COMPLETION_AUTHORIZATION
    )
    assert waiting.admitted_example_count > 0
    assert waiting.completion_authorization_runtime_configured is False
    assert waiting.signed_completion_authorization_durably_anchored is False
    assert waiting.optimizer_admission_authorized is False

    later_observation = (
        datetime.fromisoformat(evidence["observation"].replace("Z", "+00:00"))
        .astimezone(UTC)
        + timedelta(minutes=5)
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
    later_status_path = _publisher_status(tmp_path, observation=later_observation)
    still_waiting = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=later_status_path,
        witness_runtime=witness_runtime,
    ).run_once()

    assert still_waiting.classification == waiting.classification
    assert still_waiting.cycle_id == waiting.cycle_id
    assert still_waiting.publisher_status_sha256 == waiting.publisher_status_sha256
    assert still_waiting.publisher_status_read_this_invocation is False
    assert still_waiting.new_cycle_started_this_invocation is False
    assert still_waiting.state_transitions_committed == 0


def test_replayed_head_identity_mismatch_fails_before_completion_network(
    tmp_path: Path,
    evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    state_store = _state_store(tmp_path)
    witness_runtime, head_transport, completion_runtime, completion_transport = (
        _authorization_runtimes(tmp_path, monkeypatch=monkeypatch)
    )
    waiting = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=witness_runtime,
    ).run_once()
    assert waiting.classification == (
        PROFILED_COORDINATOR_WAITING_COMPLETION_AUTHORIZATION
    )
    head_request_count = len(head_transport.requests)
    original_anchor = ProfiledTrainingExternalWitnessRuntimeV1.anchor_head_candidate

    def changed_operation_id(
        self: ProfiledTrainingExternalWitnessRuntimeV1,
        **kwargs: Any,
    ) -> Any:
        result = original_anchor(self, **kwargs)
        return replace(
            result,
            operation_id=hashlib.sha256(b"changed-head-operation").hexdigest(),
        )

    monkeypatch.setattr(
        ProfiledTrainingExternalWitnessRuntimeV1,
        "anchor_head_candidate",
        changed_operation_id,
    )
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorV1Error,
        match="COMPLETION_HEAD_REAUTHENTICATION_FAILED",
    ):
        _coordinator(
            tmp_path,
            evidence=evidence,
            state_store=state_store,
            status_path=status_path,
            witness_runtime=witness_runtime,
            completion_authorization_runtime=completion_runtime,
        ).run_once()

    assert len(head_transport.requests) == head_request_count
    assert completion_transport.requests == []


def test_ambiguous_completion_authorization_recovers_before_cycle_advancement(
    tmp_path: Path,
    evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    state_store = _state_store(tmp_path)
    witness_runtime, _head_transport, completion_runtime, completion_transport = (
        _authorization_runtimes(tmp_path, monkeypatch=monkeypatch)
    )
    completion_transport.fail_after_authorization_once = True
    coordinator = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=witness_runtime,
        completion_authorization_runtime=completion_runtime,
    )

    with pytest.raises(
        ProfiledOptimizerCompletionAuthorizationClientV1Error,
        match="INJECTED_AMBIGUOUS",
    ):
        coordinator.run_once()
    interrupted = state_store.load()
    assert interrupted is not None
    assert interrupted.phase == PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
    assert completion_runtime.journal.verify_integrity().pending_count == 1
    assert len(completion_transport.requests) == 1

    recovered = coordinator.run_once()
    assert recovered.classification == PROFILED_COORDINATOR_COMPLETION_AUTHORIZED
    assert recovered.publisher_status_read_this_invocation is False
    assert recovered.completion_authorization_operations_recovered == 1
    assert recovered.completion_authorization_network_attempts == 1
    assert recovered.signed_completion_authorization_durably_anchored is True
    assert recovered.optimizer_admission_authorized is True
    assert completion_runtime.journal.verify_integrity().pending_count == 0
    assert len(completion_transport.requests) == 2
    assert completion_transport.requests[0] == completion_transport.requests[1]

    noop = coordinator.run_once()
    assert noop.classification == PROFILED_COORDINATOR_NO_NEW_CYCLE
    assert noop.completion_authorization_network_attempts == 0
    assert len(completion_transport.requests) == 2


def test_ambiguous_witness_success_recovers_before_resuming_cursor(
    tmp_path: Path,
    evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    state_store = _state_store(tmp_path)
    runtime, transport = _witness_runtime(tmp_path, monkeypatch=monkeypatch)
    transport.fail_after_append_once = True
    coordinator = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=runtime,
    )

    with pytest.raises(ProfiledTrainingExternalWitnessClientV1Error):
        coordinator.run_once()
    interrupted = state_store.load()
    assert interrupted is not None
    assert interrupted.phase == PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED
    assert len(transport.events) == 1

    monkeypatch.setattr(
        ProfiledTrainingExternalWitnessRuntimeV1,
        "recover_pending_appends",
        lambda _self: (),
    )
    resumed = coordinator.run_once()

    assert resumed.classification == (
        PROFILED_COORDINATOR_WAITING_COMPLETION_AUTHORIZATION
    )
    assert resumed.publisher_status_read_this_invocation is False
    assert resumed.witness_operations_recovered == 1
    assert resumed.witness_network_append_attempts == 1
    assert resumed.signed_head_durably_anchored is True
    assert len(transport.events) == 1
    assert len([request for request in transport.requests if request[0] == "POST"]) == 2


def test_page_verification_clock_cannot_move_backward() -> None:
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorV1Error,
        match="PROFILED_COORDINATOR_PAGE_CLOCK_ROLLBACK",
    ):
        coordinator_module._require_nondecreasing_clock(
            previous="2026-07-22T15:00:00.000001Z",
            current="2026-07-22T15:00:00.000000Z",
        )
    assert (
        coordinator_module._require_nondecreasing_clock(
            previous="2026-07-22T15:00:00.000001Z",
            current="2026-07-22T15:00:00.000001Z",
        )
        == "2026-07-22T15:00:00.000001Z"
    )


def test_zero_inventory_completes_without_page_receipt(
    tmp_path: Path,
    evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zero_ledger = DurableFeatureSnapshotLedger((tmp_path / "zero-ledger.sqlite3").absolute())
    zero_ledger.initialize()
    zero_staging = ImmutableSourcePayloadStore((tmp_path / "zero-staging").absolute())
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    state_store = _state_store(tmp_path)
    runtime, _transport = _witness_runtime(tmp_path, monkeypatch=monkeypatch)

    completed = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=runtime,
        ledger=zero_ledger,
        staging_store=zero_staging,
    ).run_once()

    assert completed.classification == PROFILED_COORDINATOR_LOCAL_COMPLETION
    assert completed.total_profiled_samples == 0
    assert completed.page_receipts_staged_this_invocation == 0
    cursor = state_store.load()
    assert cursor is not None
    assert cursor.page_receipt_event_sha256 is None
    assert cursor.completion_event_sha256 is not None


def test_all_label_unavailable_inventory_never_requests_authorization(
    tmp_path: Path,
    evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_archive = DurableCanonical5mLabelArchive(
        (tmp_path / "empty-label-archive.sqlite3").absolute()
    )
    empty_archive.initialize_empty_archive(
        initialization_intent_id="unit:coordinator:all-label-unavailable",
    )
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    state_store = _state_store(tmp_path)
    witness_runtime, _head_transport, completion_runtime, completion_transport = (
        _authorization_runtimes(tmp_path, monkeypatch=monkeypatch)
    )

    completed = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=witness_runtime,
        completion_authorization_runtime=completion_runtime,
        label_archive=empty_archive,
    ).run_once()

    assert completed.classification == PROFILED_COORDINATOR_LOCAL_COMPLETION
    assert completed.total_profiled_samples > 0
    assert completed.admitted_example_count == 0
    assert completed.label_unavailable_count == completed.total_profiled_samples
    assert completed.completion_authorization_runtime_configured is True
    assert completed.signed_completion_authorization_durably_anchored is False
    assert completed.optimizer_admission_authorized is False
    assert completion_transport.requests == []


def test_raw_protocol_key_must_match_state_store_commitment(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    state_store = _state_store(tmp_path)

    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_RUNTIME_BINDING_MISMATCH",
    ):
        _coordinator(
            tmp_path,
            evidence=evidence,
            state_store=state_store,
            status_path=status_path,
            witness_runtime=None,
            manifest_key=b"different-manifest-runtime-binding-key-v1",
        )
    assert state_store.pointer_path.exists() is False


def test_head_and_completion_runtime_witness_keys_must_match(
    tmp_path: Path,
    evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_root = tmp_path / "first-runtime"
    second_root = tmp_path / "second-runtime"
    first_root.mkdir()
    second_root.mkdir()
    witness_runtime, _head_transport, _completion_runtime, _transport = (
        _authorization_runtimes(first_root, monkeypatch=monkeypatch)
    )
    _other_head, _other_transport, wrong_completion_runtime, _wrong_transport = (
        _authorization_runtimes(second_root, monkeypatch=monkeypatch)
    )
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    state_store = _state_store(tmp_path)

    with pytest.raises(
        ProfiledTrainingObservationCoordinatorV1Error,
        match="COMPLETION_RUNTIME_WITNESS_MISMATCH",
    ):
        _coordinator(
            tmp_path,
            evidence=evidence,
            state_store=state_store,
            status_path=status_path,
            witness_runtime=witness_runtime,
            completion_authorization_runtime=wrong_completion_runtime,
        )


def test_invalid_wall_clock_fails_before_cursor_is_written(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    state_store = _state_store(tmp_path)
    coordinator = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=None,
        wall_clock=lambda: datetime(2026, 7, 22),
    )

    with pytest.raises(
        ProfiledTrainingObservationCoordinatorV1Error,
        match="PROFILED_COORDINATOR_WALL_CLOCK_INVALID",
    ):
        coordinator.run_once()
    assert state_store.pointer_path.exists() is False


def test_publisher_cutoff_after_factory_clock_fails_before_manifest(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    future_observation = (
        evidence["factory_dt"] + timedelta(microseconds=1)
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
    status_path = _publisher_status(tmp_path, observation=future_observation)
    state_store = _state_store(tmp_path)
    coordinator = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=None,
    )

    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_OBSERVATION_AFTER_FACTORY_CLOCK",
    ):
        coordinator.run_once()
    assert state_store.pointer_path.exists() is False
