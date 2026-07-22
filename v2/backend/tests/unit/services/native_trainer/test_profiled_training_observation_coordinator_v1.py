from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_training_observation_coordinator_state_v1 as state_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_coordinator_v1 as coordinator_module,
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
    PROFILED_COORDINATOR_LOCAL_COMPLETION,
    PROFILED_COORDINATOR_NO_NEW_CYCLE,
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
    ledger: DurableFeatureSnapshotLedger | None = None,
    staging_store: ImmutableSourcePayloadStore | None = None,
    manifest_key: bytes = state_support.MANIFEST_KEY,
    wall_clock: Any = None,
) -> ProfiledTrainingObservationCoordinatorV1:
    observed_clock = wall_clock or (lambda: evidence["factory_dt"])
    return ProfiledTrainingObservationCoordinatorV1(
        state_store=state_store,
        status_path=status_path,
        feature_ledger=ledger or evidence["ledger"],
        label_archive=evidence["archive"],
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
    runtime, transport = _witness_runtime(tmp_path, monkeypatch=monkeypatch)
    status_path.unlink()

    completed = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=runtime,
    ).run_once()

    assert unwitnessed.phase == PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED
    assert completed.classification == PROFILED_COORDINATOR_LOCAL_COMPLETION
    assert completed.phase == PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
    assert completed.publisher_status_read_this_invocation is False
    assert completed.signed_head_durably_anchored is True
    assert completed.full_consumption_locally_verified is True
    assert completed.page_receipts_staged_this_invocation >= 1
    assert completed.complete_state_chain_verified is True
    assert completed.external_monotonic_manifest_head_verified is False
    assert completed.full_consumption_external_ack_verified is False
    assert completed.optimizer_admission_authorized is False
    assert completed.checkpoint_write_authorized is False
    assert completed.model_write_authorized is False
    assert completed.prediction_authorized is False
    assert completed.paper_trading_authorized is False
    assert completed.live_execution_authorized is False
    assert completed.order_submission_authorized is False
    assert completed.execution_authorized is False
    assert completed.runtime_wired is False

    request_count = len(transport.requests)
    status_path = _publisher_status(tmp_path, observation=evidence["observation"])
    noop = _coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=runtime,
    ).run_once()

    assert noop.classification == PROFILED_COORDINATOR_NO_NEW_CYCLE
    assert noop.state_transitions_committed == 0
    assert noop.publisher_status_read_this_invocation is True
    assert len(transport.requests) == request_count
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
    ).run_once()

    assert successor.classification == PROFILED_COORDINATOR_LOCAL_COMPLETION
    assert successor.new_cycle_started_this_invocation is True
    assert successor.publisher_status_read_this_invocation is True
    assert successor.head_revision == 2
    assert successor.cycle_id != completed.cycle_id
    assert len(transport.events) == 2


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

    assert resumed.classification == PROFILED_COORDINATOR_LOCAL_COMPLETION
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
