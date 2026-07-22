from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_training_external_witness_runtime_v1 as witness_runtime_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_coordinator_state_v1 as state_module,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_runtime_v1 import (
    PROFILED_WITNESS_RUNTIME_RESULT_V1_SCHEMA_VERSION,
    ProfiledTrainingExternalWitnessRuntimeResultV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    stage_profiled_training_observation_completion_candidate_v1,
    stage_profiled_training_observation_consumption_epoch_v1,
    stage_profiled_training_observation_head_candidate_v1,
    stage_profiled_training_observation_page_receipt_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    authenticate_profiled_training_observation_manifest_v1,
    build_profiled_training_observation_manifest_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_model_feature_snapshot_record_v1 as base_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_observation_manifest_v1 as manifest_support,
)

STATE_KEY = b"profiled-coordinator-state-test-key-v1"
STATE_KEY_ID = "unit/profiled-coordinator-state-v1"
MANIFEST_KEY = manifest_support.AUTH_KEY
MANIFEST_KEY_ID = manifest_support.AUTH_KEY_ID
HEAD_KEY = b"profiled-coordinator-head-test-key-v1"
HEAD_KEY_ID = "unit/profiled-coordinator-head-v1"
EPOCH_KEY = b"profiled-coordinator-epoch-test-key-v1"
EPOCH_KEY_ID = "unit/profiled-coordinator-epoch-v1"
NAMESPACE = "unit/profiled-coordinator"
CONSUMER_LANE = "unit/profiled-coordinator-consumer"
STATUS_SHA256 = hashlib.sha256(b"publisher-status-cycle-one").hexdigest()

PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED = (
    state_module.PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED
)
PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED = (
    state_module.PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED
)
PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED = (
    state_module.PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED
)
PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED = (
    state_module.PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
)
PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED = (
    state_module.PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED
)
PROFILED_OBSERVATION_COORDINATOR_PREPARED = state_module.PROFILED_OBSERVATION_COORDINATOR_PREPARED
ProfiledTrainingObservationCoordinatorStateStoreV1 = (
    state_module.ProfiledTrainingObservationCoordinatorStateStoreV1
)
ProfiledTrainingObservationCoordinatorStateV1Error = (
    state_module.ProfiledTrainingObservationCoordinatorStateV1Error
)


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp_path = tmp_path_factory.mktemp("profiled-coordinator-state-evidence")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    base = base_support._build_evidence(tmp_path / "base")
    ledger, archive, observation, cost_root = manifest_support._setup_sources(
        source_root,
        base,
    )
    observation_dt = datetime.fromisoformat(observation.replace("Z", "+00:00")).astimezone(UTC)
    factory = (
        (observation_dt + timedelta(hours=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    build = build_profiled_training_observation_manifest_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=cost_root,
        label_archive=archive,
        manifest_root=(tmp_path / "manifests").absolute(),
        training_observed_at=observation,
        auth_key_id=MANIFEST_KEY_ID,
        hmac_key=MANIFEST_KEY,
        prepared_factory_wall_clock_observed_at=factory,
    )
    staging = ImmutableSourcePayloadStore((tmp_path / "staging-cas").absolute())
    head = stage_profiled_training_observation_head_candidate_v1(
        manifest_path=build.manifest_path,
        expected_manifest_id=build.manifest_id,
        expected_observation_time=build.observation_time,
        feature_ledger=ledger,
        label_archive=archive,
        staging_store=staging,
        namespace=NAMESPACE,
        consumer_lane=CONSUMER_LANE,
        manifest_hmac_key=MANIFEST_KEY,
        manifest_auth_key_id=MANIFEST_KEY_ID,
        head_hmac_key=HEAD_KEY,
        head_auth_key_id=HEAD_KEY_ID,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
    )
    authenticated = authenticate_profiled_training_observation_manifest_v1(
        manifest_path=build.manifest_path,
        hmac_key=MANIFEST_KEY,
        expected_auth_key_id=MANIFEST_KEY_ID,
        expected_manifest_id=build.manifest_id,
        expected_observation_time=build.observation_time,
    )
    return {
        "ledger": ledger,
        "archive": archive,
        "observation": observation,
        "factory": factory,
        "cost_root": cost_root,
        "build": build,
        "staging": staging,
        "head": head,
        "authenticated": authenticated,
    }


def _state_store(
    tmp_path: Path,
    *,
    state_key: bytes = STATE_KEY,
    state_key_id: str = STATE_KEY_ID,
    manifest_key: bytes = MANIFEST_KEY,
    manifest_key_id: str = MANIFEST_KEY_ID,
    head_key: bytes = HEAD_KEY,
    head_key_id: str = HEAD_KEY_ID,
    epoch_key: bytes = EPOCH_KEY,
    epoch_key_id: str = EPOCH_KEY_ID,
) -> Any:
    return ProfiledTrainingObservationCoordinatorStateStoreV1(
        pointer_path=(tmp_path / "coordinator" / "cursor.json").absolute(),
        immutable_store=ImmutableSourcePayloadStore(
            (tmp_path / "coordinator-state-cas").absolute()
        ),
        namespace=NAMESPACE,
        consumer_lane=CONSUMER_LANE,
        state_auth_key_id=state_key_id,
        state_hmac_key=state_key,
        manifest_auth_key_id=manifest_key_id,
        manifest_hmac_key=manifest_key,
        head_auth_key_id=head_key_id,
        head_hmac_key=head_key,
        epoch_auth_key_id=epoch_key_id,
        epoch_hmac_key=epoch_key,
    )


def _begin(store: Any, evidence: dict[str, Any]) -> Any:
    return store.begin_or_resume(
        publisher_status_sha256=STATUS_SHA256,
        observation_time=evidence["observation"],
        factory_wall_clock_observed_at=evidence["factory"],
    )


def _witness_result(head: Any) -> ProfiledTrainingExternalWitnessRuntimeResultV1:
    return ProfiledTrainingExternalWitnessRuntimeResultV1(
        schema_version=PROFILED_WITNESS_RUNTIME_RESULT_V1_SCHEMA_VERSION,
        operation_id=hashlib.sha256(b"unit-witness-operation").hexdigest(),
        witness_id="unit-independent-witness",
        witness_public_key_sha256=hashlib.sha256(b"unit-witness-public-key").hexdigest(),
        namespace=head.namespace,
        expected_sequence=head.revision - 1,
        anchored_sequence=head.revision,
        event_sha256=head.candidate_event_sha256,
        recovered_operation_ids=(),
        network_append_attempt_count=1,
        candidate_dispatched_after_recovery=True,
        candidate_was_recovered=False,
        journal_operation_count=1,
        journal_transition_count=2,
        journal_anchored_count=1,
        journal_pending_count=0,
        signed_head_durably_anchored=True,
        _construction_token=witness_runtime_module._RESULT_TOKEN,
    )


def _advance_to_epoch(store: Any, evidence: dict[str, Any]) -> tuple[tuple[Any, ...], Any]:
    prepared = _begin(store, evidence)
    manifest = store.persist_manifest(prepared, build=evidence["build"])
    head_state = store.persist_head(manifest, head=evidence["head"])
    anchored = store.persist_head_anchor(
        head_state,
        result=_witness_result(evidence["head"]),
    )
    epoch = stage_profiled_training_observation_consumption_epoch_v1(
        head_candidate=evidence["head"],
        staging_store=evidence["staging"],
        consumer_lane=CONSUMER_LANE,
        page_size=1,
        manifest_hmac_key=MANIFEST_KEY,
        manifest_auth_key_id=MANIFEST_KEY_ID,
        head_hmac_key=HEAD_KEY,
        head_auth_key_id=HEAD_KEY_ID,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
    )
    epoch_state = store.persist_epoch(anchored, epoch=epoch)
    return (prepared, manifest, head_state, anchored, epoch_state), epoch


def _advance_to_completion(store: Any, evidence: dict[str, Any]) -> tuple[Any, ...]:
    states, epoch = _advance_to_epoch(store, evidence)
    epoch_state = states[-1]
    page = stage_profiled_training_observation_page_receipt_v1(
        epoch=epoch,
        authenticated_manifest=evidence["authenticated"],
        staging_store=evidence["staging"],
        verified_at=evidence["factory"],
        manifest_hmac_key=MANIFEST_KEY,
        manifest_auth_key_id=MANIFEST_KEY_ID,
        head_hmac_key=HEAD_KEY,
        head_auth_key_id=HEAD_KEY_ID,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
    )
    page_state = store.persist_page(epoch_state, page=page)
    completion = stage_profiled_training_observation_completion_candidate_v1(
        epoch=epoch,
        staging_store=evidence["staging"],
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
        final_page_receipt=page,
    )
    completed = store.persist_completion(page_state, completion=completion)
    return (*states, page_state, completed)


def test_prepared_cursor_is_authenticated_durable_and_non_authoritative(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    store = _state_store(tmp_path)
    prepared = _begin(store, evidence)
    reloaded = store.load()
    integrity = store.verify_integrity()

    assert reloaded == prepared
    assert prepared.phase == PROFILED_OBSERVATION_COORDINATOR_PREPARED
    assert prepared.transition_sequence == 1
    assert prepared.publisher_status_sha256 == STATUS_SHA256
    assert prepared.manifest_path is None
    assert (
        len(
            {
                prepared.state_auth_key_commitment_sha256,
                prepared.manifest_auth_key_commitment_sha256,
                prepared.head_auth_key_commitment_sha256,
                prepared.epoch_auth_key_commitment_sha256,
            }
        )
        == 4
    )
    assert prepared.external_monotonic_manifest_head_verified is False
    assert prepared.full_consumption_external_ack_verified is False
    assert prepared.optimizer_admission_authorized is False
    assert prepared.checkpoint_write_authorized is False
    assert prepared.model_write_authorized is False
    assert prepared.prediction_authorized is False
    assert prepared.paper_trading_authorized is False
    assert prepared.live_execution_authorized is False
    assert prepared.order_submission_authorized is False
    assert prepared.execution_authorized is False
    assert prepared.runtime_wired is False
    assert integrity is not None
    assert integrity.transition_count == 1
    assert integrity.complete_chain_verified is True


def test_same_publisher_cycle_is_idempotent_without_new_transition(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    store = _state_store(tmp_path)
    first = _begin(store, evidence)
    replay = _begin(store, evidence)

    assert replay.state_event_sha256 == first.state_event_sha256
    assert replay.transition_sequence == 1


def test_same_cutoff_different_status_fails_closed(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    store = _state_store(tmp_path)
    _begin(store, evidence)

    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_SAME_CUTOFF_BINDING_CONFLICT",
    ):
        store.begin_or_resume(
            publisher_status_sha256=hashlib.sha256(b"conflicting-status").hexdigest(),
            observation_time=evidence["observation"],
            factory_wall_clock_observed_at=evidence["factory"],
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"manifest_key_id": STATE_KEY_ID},
        {"manifest_key": STATE_KEY},
    ],
)
def test_role_key_id_or_material_reuse_is_forbidden_before_state_write(
    tmp_path: Path,
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_ROLE_KEY_REUSE_FORBIDDEN",
    ):
        _state_store(tmp_path, **overrides)


def test_inflight_cycle_cannot_be_superseded_by_newer_status(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    store = _state_store(tmp_path)
    _begin(store, evidence)
    later = datetime.fromisoformat(evidence["observation"].replace("Z", "+00:00")) + timedelta(
        minutes=1
    )
    later_text = later.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")

    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_INFLIGHT_CYCLE_MUST_RESUME",
    ):
        store.begin_or_resume(
            publisher_status_sha256=hashlib.sha256(b"later-status").hexdigest(),
            observation_time=later_text,
            factory_wall_clock_observed_at=later_text,
        )


def test_full_local_chain_persists_exact_addresses_and_verifies_all_transitions(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    store = _state_store(tmp_path)
    states = _advance_to_completion(store, evidence)
    prepared, manifest, head, anchored, epoch, page, completed = states
    integrity = store.verify_integrity()

    assert prepared.phase == PROFILED_OBSERVATION_COORDINATOR_PREPARED
    assert manifest.phase == PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED
    assert head.phase == PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED
    assert anchored.phase == PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED
    assert epoch.phase == PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED
    assert page.page_end_ordinal == 1
    assert page.page_has_more_manifest_entries is False
    assert completed.phase == PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
    assert completed.signed_head_durably_anchored is True
    assert completed.completion_event_sha256 is not None
    assert completed.external_monotonic_manifest_head_verified is False
    assert completed.full_consumption_external_ack_verified is False
    assert completed.optimizer_admission_authorized is False
    assert integrity is not None
    assert integrity.transition_count == 7
    assert integrity.current_state_event_sha256 == completed.state_event_sha256


def test_new_cycle_copies_only_completed_head_and_completion_addresses(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    store = _state_store(tmp_path)
    completed = _advance_to_completion(store, evidence)[-1]
    later = datetime.fromisoformat(evidence["observation"].replace("Z", "+00:00")) + timedelta(
        hours=2
    )
    later_observation = (
        later.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
    later_factory = (
        (later + timedelta(hours=1))
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    next_cursor = store.begin_or_resume(
        publisher_status_sha256=hashlib.sha256(b"publisher-status-cycle-two").hexdigest(),
        observation_time=later_observation,
        factory_wall_clock_observed_at=later_factory,
    )

    assert next_cursor.phase == PROFILED_OBSERVATION_COORDINATOR_PREPARED
    assert next_cursor.transition_sequence == completed.transition_sequence + 1
    assert next_cursor.prior_completed_head_event_sha256 == completed.head_event_sha256
    assert next_cursor.prior_completed_head_event_byte_count == completed.head_event_byte_count
    assert next_cursor.prior_completed_completion_event_sha256 == completed.completion_event_sha256
    assert (
        next_cursor.prior_completed_completion_event_byte_count
        == completed.completion_event_byte_count
    )
    assert next_cursor.manifest_id is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"head_key": b"rotated-profiled-coordinator-head-key-v1"},
        {"head_key_id": "unit/profiled-coordinator-head-rotated-v1"},
    ],
)
def test_completed_chain_cannot_be_reopened_with_rotated_role_credentials(
    tmp_path: Path,
    evidence: dict[str, Any],
    overrides: dict[str, Any],
) -> None:
    store = _state_store(tmp_path)
    _advance_to_completion(store, evidence)
    rotated = _state_store(tmp_path, **overrides)

    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_ROLE_KEY_BINDING_MISMATCH",
    ):
        rotated.load()


@pytest.mark.parametrize(
    "branch_field",
    [
        "previous_page_receipt_event_sha256",
        "previous_page_transition_sha256",
        "previous_ordered_page_root_sha256",
    ],
)
def test_page_receipt_must_bind_exact_persisted_predecessor_branch(
    tmp_path: Path,
    evidence: dict[str, Any],
    branch_field: str,
) -> None:
    store = _state_store(tmp_path)
    states, epoch = _advance_to_epoch(store, evidence)
    epoch_state = states[-1]
    page = stage_profiled_training_observation_page_receipt_v1(
        epoch=epoch,
        authenticated_manifest=evidence["authenticated"],
        staging_store=evidence["staging"],
        verified_at=evidence["factory"],
        manifest_hmac_key=MANIFEST_KEY,
        manifest_auth_key_id=MANIFEST_KEY_ID,
        head_hmac_key=HEAD_KEY,
        head_auth_key_id=HEAD_KEY_ID,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
    )
    wrong_hash = hashlib.sha256(branch_field.encode("ascii")).hexdigest()
    if branch_field == "previous_page_transition_sha256":
        branch = replace(page, previous_page_transition_sha256=wrong_hash)
    else:
        branch = replace(
            page,
            _material={**page._material, branch_field: wrong_hash},
        )

    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_PAGE_BINDING_INVALID",
    ):
        store.persist_page(epoch_state, page=branch)


def test_completion_must_bind_exact_persisted_terminal_page(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    store = _state_store(tmp_path)
    states, epoch = _advance_to_epoch(store, evidence)
    epoch_state = states[-1]
    first_page = stage_profiled_training_observation_page_receipt_v1(
        epoch=epoch,
        authenticated_manifest=evidence["authenticated"],
        staging_store=evidence["staging"],
        verified_at=evidence["factory"],
        manifest_hmac_key=MANIFEST_KEY,
        manifest_auth_key_id=MANIFEST_KEY_ID,
        head_hmac_key=HEAD_KEY,
        head_auth_key_id=HEAD_KEY_ID,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
    )
    page_state = store.persist_page(epoch_state, page=first_page)
    alternate_clock = (
        (
            datetime.fromisoformat(evidence["factory"].replace("Z", "+00:00"))
            + timedelta(microseconds=1)
        )
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    alternate_page = stage_profiled_training_observation_page_receipt_v1(
        epoch=epoch,
        authenticated_manifest=evidence["authenticated"],
        staging_store=evidence["staging"],
        verified_at=alternate_clock,
        manifest_hmac_key=MANIFEST_KEY,
        manifest_auth_key_id=MANIFEST_KEY_ID,
        head_hmac_key=HEAD_KEY,
        head_auth_key_id=HEAD_KEY_ID,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
    )
    alternate_completion = stage_profiled_training_observation_completion_candidate_v1(
        epoch=epoch,
        staging_store=evidence["staging"],
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
        final_page_receipt=alternate_page,
    )

    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_COMPLETION_BINDING_INVALID",
    ):
        store.persist_completion(page_state, completion=alternate_completion)


def test_crash_after_state_cas_before_pointer_keeps_old_cursor_and_replays(
    tmp_path: Path,
    evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _state_store(tmp_path)
    prepared = _begin(store, evidence)
    store_type = type(store)
    original = store_type._atomic_write_pointer

    def crash_before_pointer(_: Any, __: bytes) -> None:
        raise ProfiledTrainingObservationCoordinatorStateV1Error("SIMULATED_PRE_POINTER_CRASH")

    monkeypatch.setattr(store_type, "_atomic_write_pointer", crash_before_pointer)
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="SIMULATED_PRE_POINTER_CRASH",
    ):
        store.persist_manifest(prepared, build=evidence["build"])
    assert store.load().state_event_sha256 == prepared.state_event_sha256

    monkeypatch.setattr(store_type, "_atomic_write_pointer", original)
    resumed = store.persist_manifest(prepared, build=evidence["build"])
    assert resumed.phase == PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED
    assert resumed.transition_sequence == 2


def test_crash_after_pointer_commit_resumes_new_state_and_rejects_stale_cursor(
    tmp_path: Path,
    evidence: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _state_store(tmp_path)
    prepared = _begin(store, evidence)
    store_type = type(store)
    original = store_type._atomic_write_pointer

    def crash_after_pointer(instance: Any, payload: bytes) -> None:
        original(instance, payload)
        raise ProfiledTrainingObservationCoordinatorStateV1Error("SIMULATED_POST_POINTER_CRASH")

    monkeypatch.setattr(store_type, "_atomic_write_pointer", crash_after_pointer)
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="SIMULATED_POST_POINTER_CRASH",
    ):
        store.persist_manifest(prepared, build=evidence["build"])
    resumed = store.load()
    assert resumed.phase == PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED

    monkeypatch.setattr(store_type, "_atomic_write_pointer", original)
    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_CURRENT_CURSOR_NOT_LATEST",
    ):
        store.persist_manifest(prepared, build=evidence["build"])


def test_wrong_state_hmac_key_cannot_load_authenticated_pointer(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    store = _state_store(tmp_path)
    _begin(store, evidence)
    wrong = _state_store(
        tmp_path,
        state_key=b"wrong-profiled-coordinator-state-key-v1",
    )

    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_POINTER_AUTHENTICATION_INVALID",
    ):
        wrong.load()


def test_pointer_tampering_fails_before_state_cas_is_trusted(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    store = _state_store(tmp_path)
    _begin(store, evidence)
    pointer = json.loads(store.pointer_path.read_text(encoding="ascii"))
    pointer["transition_sequence"] += 1
    store.pointer_path.write_text(
        json.dumps(pointer, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="ascii",
    )

    with pytest.raises(
        ProfiledTrainingObservationCoordinatorStateV1Error,
        match="PROFILED_COORDINATOR_POINTER_AUTHENTICATION_INVALID",
    ):
        store.load()


def test_zero_inventory_completion_requires_no_page_receipt(
    tmp_path: Path,
    evidence: dict[str, Any],
) -> None:
    zero_ledger = DurableFeatureSnapshotLedger((tmp_path / "zero-ledger.sqlite3").absolute())
    zero_ledger.initialize()
    build = build_profiled_training_observation_manifest_v1(
        ledger=zero_ledger,
        trusted_immutable_cost_store_root=evidence["cost_root"],
        label_archive=evidence["archive"],
        manifest_root=(tmp_path / "zero-manifests").absolute(),
        training_observed_at=evidence["observation"],
        auth_key_id=MANIFEST_KEY_ID,
        hmac_key=MANIFEST_KEY,
        prepared_factory_wall_clock_observed_at=evidence["factory"],
    )
    staging = ImmutableSourcePayloadStore((tmp_path / "zero-staging-cas").absolute())
    head = stage_profiled_training_observation_head_candidate_v1(
        manifest_path=build.manifest_path,
        expected_manifest_id=build.manifest_id,
        expected_observation_time=build.observation_time,
        feature_ledger=zero_ledger,
        label_archive=evidence["archive"],
        staging_store=staging,
        namespace=NAMESPACE,
        consumer_lane=CONSUMER_LANE,
        manifest_hmac_key=MANIFEST_KEY,
        manifest_auth_key_id=MANIFEST_KEY_ID,
        head_hmac_key=HEAD_KEY,
        head_auth_key_id=HEAD_KEY_ID,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
    )
    store = _state_store(tmp_path)
    cursor = _begin(store, {**evidence, "build": build})
    cursor = store.persist_manifest(cursor, build=build)
    cursor = store.persist_head(cursor, head=head)
    cursor = store.persist_head_anchor(cursor, result=_witness_result(head))
    epoch = stage_profiled_training_observation_consumption_epoch_v1(
        head_candidate=head,
        staging_store=staging,
        consumer_lane=CONSUMER_LANE,
        page_size=1,
        manifest_hmac_key=MANIFEST_KEY,
        manifest_auth_key_id=MANIFEST_KEY_ID,
        head_hmac_key=HEAD_KEY,
        head_auth_key_id=HEAD_KEY_ID,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
    )
    cursor = store.persist_epoch(cursor, epoch=epoch)
    completion = stage_profiled_training_observation_completion_candidate_v1(
        epoch=epoch,
        staging_store=staging,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
        final_page_receipt=None,
    )
    completed = store.persist_completion(cursor, completion=completion)

    assert completed.phase == PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
    assert completed.total_profiled_samples == 0
    assert completed.page_receipt_event_sha256 is None
    assert completed.completion_event_sha256 == completion.completion_event_sha256
