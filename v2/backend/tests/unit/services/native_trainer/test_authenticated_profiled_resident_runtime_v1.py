from __future__ import annotations

import hashlib
import itertools
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn

import pytest

from v2.backend.app.services.native_trainer import (
    authenticated_profiled_resident_runtime_v1 as resident_module,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_base_checkpoint_lineage_v1 import (  # noqa: E501
    AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
    AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_BASE_LINEAGE,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_v1 import (  # noqa: E501
    PROFILED_RESIDENT_ALREADY_PUBLISHED,
    PROFILED_RESIDENT_PUBLICATION_COMPLETED,
    PROFILED_RESIDENT_WAITING_EXTERNAL_AUTHORIZATION,
    PROFILED_RESIDENT_WAITING_LOCAL_COMPLETION,
    AuthenticatedProfiledResidentRuntimeConfigV1,
    AuthenticatedProfiledResidentRuntimeV1Error,
    run_authenticated_profiled_resident_cycle_v1,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_sample_identity import (  # noqa: E501
    manifest_paths,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.profiled_optimizer_external_completion_authorization_journal_v1 import (  # noqa: E501
    ProfiledOptimizerCompletionAuthorizationJournalV1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_authenticated_profiled_supervised_optimizer_execution_v1 as execution_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_model_feature_snapshot_record_v1 as base_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_observation_coordinator_state_v1 as state_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_observation_coordinator_v1 as coordinator_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_observation_manifest_v1 as manifest_support,
)

_INPUT_BUDGET = 8 * 1024 * 1024
_STATE_BUDGET = 64 * 1024 * 1024
_CHECKPOINT_BUDGET = 128 * 1024 * 1024


@pytest.fixture
def resident_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, Any]:
    execution_support._configure_cpu(monkeypatch)
    source_root = tmp_path / "sources"
    source_root.mkdir()
    base = base_support._build_evidence(tmp_path / "base")
    ledger, archive, observation, cost_root = manifest_support._setup_sources(
        source_root,
        base,
    )
    observation_dt = datetime.fromisoformat(observation.replace("Z", "+00:00")).astimezone(UTC)
    evidence = {
        "ledger": ledger,
        "archive": archive,
        "observation": observation,
        "factory_dt": observation_dt + timedelta(hours=1),
        "cost_root": cost_root,
        "staging": ImmutableSourcePayloadStore((tmp_path / "staging-cas").absolute()),
    }
    status_path = coordinator_support._publisher_status(
        tmp_path,
        observation=observation,
    )
    state_store = coordinator_support._state_store(tmp_path)
    head_runtime, _head_transport, completion_runtime, _completion_transport = (
        coordinator_support._authorization_runtimes(
            tmp_path,
            monkeypatch=monkeypatch,
        )
    )
    completed = coordinator_support._coordinator(
        tmp_path,
        evidence=evidence,
        state_store=state_store,
        status_path=status_path,
        witness_runtime=head_runtime,
        completion_authorization_runtime=completion_runtime,
    ).run_once()
    cursor = state_store.load()
    assert cursor is not None
    record = completion_runtime.journal.load_request_for_completion(
        witness_id=completion_runtime.client.witness_id,
        authorization_namespace=completed.completion_authorization_namespace,
        completion_event_sha256=cursor.completion_event_sha256,
        witness_public_key_bytes=(completion_runtime.client.witness_public_key_bytes),
    )
    assert record is not None and record.verified is not None
    accepted_at = datetime.fromisoformat(
        record.verified.accepted_at.replace("Z", "+00:00")
    ).astimezone(UTC)
    ticks = itertools.count(1)

    def strict_clock() -> datetime:
        return accepted_at + timedelta(seconds=next(ticks))

    model_dir = (tmp_path / ".local_models" / "resident-profiled").absolute()
    config = AuthenticatedProfiledResidentRuntimeConfigV1(
        state_store=state_store,
        completion_authorization_journal=completion_runtime.journal,
        feature_ledger=ledger,
        completion_staging_store=evidence["staging"],
        trusted_immutable_cost_store_root=cost_root,
        repo_root=tmp_path.absolute(),
        model_dir=model_dir,
        namespace=state_support.NAMESPACE,
        consumer_lane=state_support.CONSUMER_LANE,
        manifest_auth_key_id=state_support.MANIFEST_KEY_ID,
        manifest_hmac_key=state_support.MANIFEST_KEY,
        head_auth_key_id=state_support.HEAD_KEY_ID,
        head_hmac_key=state_support.HEAD_KEY,
        epoch_auth_key_id=state_support.EPOCH_KEY_ID,
        epoch_hmac_key=state_support.EPOCH_KEY,
        witness_id=completion_runtime.client.witness_id,
        witness_namespace=completed.completion_authorization_namespace,
        witness_public_key_bytes=(completion_runtime.client.witness_public_key_bytes),
        expected_witness_public_key_sha256=hashlib.sha256(
            completion_runtime.client.witness_public_key_bytes
        ).hexdigest(),
        page_limit=1,
        validation_fraction=0.2,
        optimizer_input_byte_budget=_INPUT_BUDGET,
        state_resource_budget_bytes=_STATE_BUDGET,
        checkpoint_serialization_byte_budget=_CHECKPOINT_BUDGET,
        clock=strict_clock,
    )
    return {
        "config": config,
        "cursor": cursor,
        "completed": completed,
        "record": record,
        "model_dir": model_dir,
    }


def test_coordinator_to_genesis_optimizer_to_publication_end_to_end(
    resident_bundle: dict[str, Any],
) -> None:
    result = run_authenticated_profiled_resident_cycle_v1(resident_bundle["config"])
    base_manager = V2HybridCheckpointManager(resident_bundle["model_dir"])
    candidate_manager = V2HybridCheckpointManager(
        resident_bundle["model_dir"] / "non_serving_training_candidates"
    )
    (genesis,) = base_manager.manifests(
        allowed_lineage_kinds=frozenset({AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_BASE_LINEAGE}),
        require_weight_blob=True,
    )
    (candidate,) = candidate_manager.manifests(
        allowed_lineage_kinds=frozenset({AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}),
        require_weight_blob=True,
    )

    assert result.classification == PROFILED_RESIDENT_PUBLICATION_COMPLETED
    assert result.cycle_id == resident_bundle["cursor"].cycle_id
    assert result.manifest_id == resident_bundle["cursor"].manifest_id
    assert result.completion_event_sha256 == (resident_bundle["cursor"].completion_event_sha256)
    assert result.witness_namespace == resident_bundle["config"].witness_namespace
    assert result.admitted_example_count == 1
    assert result.base_checkpoint_id == genesis.checkpoint_id
    assert result.candidate_checkpoint_id == candidate.checkpoint_id
    assert result.candidate_checkpoint_generation == 2
    assert candidate.parent_checkpoint_id == genesis.checkpoint_id
    assert result.optimizer_execution_completed is True
    assert result.checkpoint_publication_completed is True
    assert result.checkpoint_artifact_verified is True
    assert result.checkpoint_write_authorized is False
    assert all(
        getattr(result, field_name) is False for field_name in resident_module._DOWNSTREAM_FALSE
    )
    with pytest.raises(
        AuthenticatedProfiledResidentRuntimeV1Error,
        match="PROFILED_RESIDENT_RESULT_INVALID",
    ):
        replace(result, base_checkpoint_id=None)


def test_restart_recovers_publication_before_any_admission_or_optimizer(
    resident_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = run_authenticated_profiled_resident_cycle_v1(resident_bundle["config"])
    candidate_manager = V2HybridCheckpointManager(
        resident_bundle["model_dir"] / "non_serving_training_candidates"
    )
    (manifest_before,) = candidate_manager.manifests(
        allowed_lineage_kinds=frozenset({AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}),
        require_weight_blob=True,
    )
    manifest_path = Path(manifest_before.path)
    weight_path = Path(manifest_before.weight_file_path)
    manifest_stat = manifest_path.stat()
    weight_stat = weight_path.stat()

    def forbidden_admission(**_kwargs: Any) -> NoReturn:
        raise AssertionError("admission must not run after durable publication")

    monkeypatch.setattr(
        resident_module,
        "admit_authenticated_profiled_optimizer_manifest_batch_v1",
        forbidden_admission,
    )
    recovered = run_authenticated_profiled_resident_cycle_v1(resident_bundle["config"])

    assert first.classification == PROFILED_RESIDENT_PUBLICATION_COMPLETED
    assert recovered.classification == PROFILED_RESIDENT_ALREADY_PUBLISHED
    assert recovered.base_checkpoint_id == first.base_checkpoint_id
    assert recovered.candidate_checkpoint_id == first.candidate_checkpoint_id
    assert recovered.witness_namespace == first.witness_namespace
    assert recovered.optimizer_execution_completed is False
    assert recovered.checkpoint_publication_completed is False
    assert recovered.already_published is True
    assert manifest_path.stat().st_ino == manifest_stat.st_ino
    assert weight_path.stat().st_ino == weight_stat.st_ino
    assert candidate_manager.manifests(
        allowed_lineage_kinds=frozenset({AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE})
    ) == (manifest_before,)


def test_empty_coordinator_state_waits_without_checkpoint_mutation(
    resident_bundle: dict[str, Any],
    tmp_path: Path,
) -> None:
    empty_root = tmp_path / "empty-state-root"
    empty_root.mkdir()
    empty_state = coordinator_support._state_store(empty_root)
    config = replace(resident_bundle["config"], state_store=empty_state)

    result = run_authenticated_profiled_resident_cycle_v1(config)

    assert result.classification == PROFILED_RESIDENT_WAITING_LOCAL_COMPLETION
    assert result.state_event_sha256 is None
    assert result.optimizer_execution_completed is False
    assert not resident_bundle["model_dir"].exists()


def test_present_corrupt_activation_manifest_forbids_genesis_fallback(
    resident_bundle: dict[str, Any],
) -> None:
    activation_path = manifest_paths(resident_bundle["config"].repo_root)[-1]
    activation_path.parent.mkdir(parents=True)
    activation_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        AuthenticatedProfiledResidentRuntimeV1Error,
        match="PROFILED_RESIDENT_SERVING_ACTIVATION_MANIFEST_INVALID",
    ):
        run_authenticated_profiled_resident_cycle_v1(resident_bundle["config"])
    assert (
        V2HybridCheckpointManager(resident_bundle["model_dir"]).manifests(
            allowed_lineage_kinds=frozenset(
                {AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_BASE_LINEAGE}
            )
        )
        == ()
    )


def test_cursor_movement_after_corpus_materialization_forbids_publication(
    resident_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_snapshot = resident_module._state_snapshot
    calls = 0

    def moving_snapshot(config: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_snapshot(config)
        return None

    monkeypatch.setattr(resident_module, "_state_snapshot", moving_snapshot)
    with pytest.raises(
        AuthenticatedProfiledResidentRuntimeV1Error,
        match="PROFILED_RESIDENT_COORDINATOR_STATE_MOVED_DURING_MATERIALIZATION",
    ):
        run_authenticated_profiled_resident_cycle_v1(resident_bundle["config"])
    assert calls == 2
    candidate_manager = V2HybridCheckpointManager(
        resident_bundle["model_dir"] / "non_serving_training_candidates"
    )
    assert (
        candidate_manager.manifests(
            allowed_lineage_kinds=frozenset({AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE})
        )
        == ()
    )


def test_runtime_config_redacts_and_rejects_reused_hmac_roles(
    resident_bundle: dict[str, Any],
) -> None:
    config = resident_bundle["config"]

    assert "manifest_hmac_key=" not in repr(config)
    assert "head_hmac_key=" not in repr(config)
    assert "epoch_hmac_key=" not in repr(config)
    with pytest.raises(
        AuthenticatedProfiledResidentRuntimeV1Error,
        match="PROFILED_RESIDENT_CONFIG_INVALID",
    ):
        replace(config, head_hmac_key=config.manifest_hmac_key)


def test_local_completion_without_anchored_authorization_waits_without_training(
    resident_bundle: dict[str, Any],
    tmp_path: Path,
) -> None:
    journal_root = (tmp_path / "empty-authorization").absolute()
    journal_root.mkdir()
    empty_journal = ProfiledOptimizerCompletionAuthorizationJournalV1(
        journal_root / "journal.sqlite3",
        immutable_store=ImmutableSourcePayloadStore(journal_root / "cas"),
    )
    config = replace(
        resident_bundle["config"],
        completion_authorization_journal=empty_journal,
    )

    result = run_authenticated_profiled_resident_cycle_v1(config)

    assert result.classification == PROFILED_RESIDENT_WAITING_EXTERNAL_AUTHORIZATION
    assert result.manifest_id == resident_bundle["cursor"].manifest_id
    assert result.optimizer_execution_completed is False
    assert not resident_bundle["model_dir"].exists()
