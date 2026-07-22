from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    authenticated_profiled_supervised_checkpoint_publication_v1 as publication_module,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_base_checkpoint_lineage_v1 import (  # noqa: E501
    AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
    AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_BASE_LINEAGE,
    AuthenticatedProfiledBaseCheckpointLineageV1Error,
    capture_authenticated_profiled_base_checkpoint_lineage_v1,
    ensure_authenticated_profiled_genesis_base_checkpoint_v1,
    revalidate_authenticated_profiled_base_checkpoint_lineage_v1,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_corpus_v1 import (  # noqa: E501
    build_authenticated_profiled_optimizer_corpus_v1,
    validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (  # noqa: E501
    NON_SERVING_CANDIDATE_LINEAGE,
    checkpoint_lifecycle_lease,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (  # noqa: E501
    model_parameter_fingerprint,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_authenticated_profiled_optimizer_admission_v1 as admission_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_authenticated_profiled_supervised_optimizer_execution_v1 as execution_support,
)

adapter_evidence = admission_support.adapter_evidence


def _publish(
    *,
    bound_execution: Any,
    candidate_checkpoint_manager: V2HybridCheckpointManager,
) -> Any:
    base_manager = bound_execution._base_checkpoint_manager_owner
    with checkpoint_lifecycle_lease(
        base_manager.model_dir,
        owner_role="AUTHENTICATED_PROFILED_TRAINER",
    ) as lifecycle_lease:
        return publication_module.publish_authenticated_profiled_supervised_checkpoint_v1(
            bound_execution=bound_execution,
            candidate_checkpoint_manager=candidate_checkpoint_manager,
            lifecycle_lease=lifecycle_lease,
        )


@pytest.fixture(scope="module")
def corpus_bundle(adapter_evidence: dict[str, Any]) -> dict[str, Any]:
    admitted = admission_support._admit(adapter_evidence)
    before = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    after = build_authenticated_profiled_optimizer_corpus_v1((admitted,))
    authorization = validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
        before=before,
        after=after,
    )
    return {
        "before": before,
        "after": after,
        "authorization": authorization,
    }


@pytest.fixture(scope="module")
def publication_bundle(
    corpus_bundle: dict[str, Any],
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    monkeypatch = pytest.MonkeyPatch()
    execution_support._configure_cpu(monkeypatch)
    try:
        root = (
            tmp_path_factory.mktemp("authenticated-profiled-publication")
            / ".local_models"
            / "publication"
        )
        base_manager = V2HybridCheckpointManager(root)
        candidate_manager = V2HybridCheckpointManager(
            root / "non_serving_training_candidates"
        )
        base_model, trainer = execution_support._runtime(
            before_corpus=corpus_bundle["before"]
        )
        base_lineage = ensure_authenticated_profiled_genesis_base_checkpoint_v1(
            base_model=base_model,
            base_checkpoint_manager=base_manager,
        )
        (base_manifest,) = base_manager.manifests(
            input_dim=base_model.input_dim,
            model_id=base_model.model_id,
            allowed_lineage_kinds=frozenset(
                {AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_BASE_LINEAGE}
            ),
            require_weight_blob=True,
        )
        execution_inputs = execution_support._execution_inputs(
            corpus_bundle,
            model=base_model,
            trainer=trainer,
        )
        bound_execution = publication_module.execute_lineage_bound_authenticated_profiled_supervised_optimizer_v1(  # noqa: E501
            base_lineage=base_lineage,
            base_checkpoint_manager=base_manager,
            **execution_inputs,
        )
        base_fingerprint = model_parameter_fingerprint(base_model)
        candidate_fingerprint = model_parameter_fingerprint(
            bound_execution.candidate_model
        )
        first = _publish(
            bound_execution=bound_execution,
            candidate_checkpoint_manager=candidate_manager,
        )
        weight_path = candidate_manager.model_dir / (
            f"{first.candidate_checkpoint_id}.weights.npz"
        )
        manifest_path = candidate_manager.model_dir / (
            f"{first.candidate_checkpoint_id}.json"
        )
        first_weight_stat = weight_path.stat()
        first_manifest_bytes = manifest_path.read_bytes()
        first_weight_bytes = weight_path.read_bytes()
        second = _publish(
            bound_execution=bound_execution,
            candidate_checkpoint_manager=candidate_manager,
        )
        yield {
            "root": root,
            "base_manager": base_manager,
            "candidate_manager": candidate_manager,
            "base_model": base_model,
            "trainer": trainer,
            "base_manifest": base_manifest,
            "base_lineage": base_lineage,
            "bound_execution": bound_execution,
            "base_fingerprint": base_fingerprint,
            "candidate_fingerprint": candidate_fingerprint,
            "first": first,
            "second": second,
            "weight_path": weight_path,
            "manifest_path": manifest_path,
            "first_weight_stat": first_weight_stat,
            "first_manifest_bytes": first_manifest_bytes,
            "first_weight_bytes": first_weight_bytes,
            "corpus_bundle": corpus_bundle,
        }
    finally:
        monkeypatch.undo()


def test_exact_parent_is_loaded_and_revalidated_before_publication(
    publication_bundle: dict[str, Any],
) -> None:
    base_lineage = publication_bundle["base_lineage"]
    base_manifest = publication_bundle["base_manifest"]

    reopened = revalidate_authenticated_profiled_base_checkpoint_lineage_v1(
        lineage=base_lineage,
        base_model=publication_bundle["base_model"],
        base_checkpoint_manager=publication_bundle["base_manager"],
    )

    assert reopened == base_manifest
    assert base_lineage.checkpoint_id == base_manifest.checkpoint_id
    assert base_lineage.checkpoint_weight_sha256 == base_manifest.weight_file_sha256
    assert base_lineage.checkpoint_generation == 1
    assert base_lineage.checkpoint_artifact_verified is True
    assert base_lineage.exact_checkpoint_loaded is True
    assert base_lineage.checkpoint_write_authorized is False


def test_authenticated_candidate_is_durable_verified_and_non_serving(
    publication_bundle: dict[str, Any],
) -> None:
    result = publication_bundle["first"]
    manager = publication_bundle["candidate_manager"]
    manifest = result.checkpoint_manifest
    contract = manifest.checkpoint_evidence[
        "authenticated_profiled_supervised_publication"
    ]
    verification = manager.verify_manifest_artifact(manifest)

    assert result.lineage_kind == AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE
    assert result.base_checkpoint_id == publication_bundle["base_manifest"].checkpoint_id
    assert result.candidate_checkpoint_id == manifest.checkpoint_id
    assert result.candidate_checkpoint_generation == 2
    assert result.durable_publication_receipt_written is True
    assert result.durable_execution_receipt_written is False
    assert result.checkpoint_write_authorized is False
    assert result.candidate_checkpoint_artifact_verified is True
    assert manifest.parent_checkpoint_id == result.base_checkpoint_id
    assert manifest.parent_policy_fingerprint == publication_bundle["base_fingerprint"]
    assert contract["external_authorization_envelope_sha256"]
    assert contract["witness_public_key_sha256"]
    assert contract["optimizer_state_persisted"] is False
    assert contract["optimizer_state_contract"] == (
        "STATELESS_ADAMW_RECREATED_PER_AUTHENTICATED_ONE_STEP_EXECUTION"
    )
    assert verification["checkpoint_artifact_verified"] is True
    assert verification["checkpoint_identity_verified"] is True
    assert model_parameter_fingerprint(publication_bundle["base_model"]) == (
        publication_bundle["base_fingerprint"]
    )
    assert model_parameter_fingerprint(
        publication_bundle["bound_execution"].candidate_model
    ) == publication_bundle["candidate_fingerprint"]
    for field_name in publication_module._DOWNSTREAM_AUTHORITY_FALSE:
        assert getattr(result, field_name) is False
        assert contract[field_name] is False


def test_publication_requires_a_live_lifecycle_lease(
    publication_bundle: dict[str, Any],
) -> None:
    base_manager = publication_bundle["base_manager"]
    with checkpoint_lifecycle_lease(
        base_manager.model_dir,
        owner_role="AUTHENTICATED_PROFILED_TRAINER",
    ) as expired_lease:
        pass

    with pytest.raises(
        publication_module.AuthenticatedProfiledSupervisedCheckpointPublicationV1Error,
        match="PROFILED_SUPERVISED_PUBLICATION_LIFECYCLE_LEASE_INVALID",
    ):
        publication_module.publish_authenticated_profiled_supervised_checkpoint_v1(
            bound_execution=publication_bundle["bound_execution"],
            candidate_checkpoint_manager=publication_bundle["candidate_manager"],
            lifecycle_lease=expired_lease,
        )


def test_verified_existing_publication_is_recovered_without_optimizer_rerun(
    publication_bundle: dict[str, Any],
) -> None:
    first = publication_bundle["first"]
    contract = first.checkpoint_manifest.checkpoint_evidence[
        "authenticated_profiled_supervised_publication"
    ]

    recovered = publication_module.find_authenticated_profiled_supervised_publication_for_completion_v1(  # noqa: E501
        candidate_checkpoint_manager=publication_bundle["candidate_manager"],
        manifest_id=contract["manifest_id"],
        completion_event_sha256=contract["completion_event_sha256"],
        external_authorization_envelope_sha256=(
            contract["external_authorization_envelope_sha256"]
        ),
        witness_id=contract["witness_id"],
        witness_namespace=contract["witness_namespace"],
        witness_public_key_sha256=contract["witness_public_key_sha256"],
        witness_sequence=contract["witness_sequence"],
    )

    assert recovered is not None
    assert recovered.status == (
        publication_module.AUTHENTICATED_PROFILED_EXISTING_PUBLICATION_V1_STATUS
    )
    assert recovered.already_published is True
    assert recovered.checkpoint_artifact_verified is True
    assert recovered.witness_namespace == contract["witness_namespace"]
    assert recovered.base_checkpoint_id == first.base_checkpoint_id
    assert recovered.candidate_checkpoint_id == first.candidate_checkpoint_id
    assert recovered.candidate_checkpoint_generation == (
        first.candidate_checkpoint_generation
    )
    assert recovered.checkpoint_write_authorized is False
    assert recovered.serving_authorized is False
    assert recovered.trading_authorized is False


def test_existing_publication_lookup_returns_none_for_disjoint_completion(
    publication_bundle: dict[str, Any],
) -> None:
    assert publication_module.find_authenticated_profiled_supervised_publication_for_completion_v1(  # noqa: E501
        candidate_checkpoint_manager=publication_bundle["candidate_manager"],
        manifest_id="1" * 64,
        completion_event_sha256="2" * 64,
        external_authorization_envelope_sha256="3" * 64,
        witness_id="independent-witness",
        witness_namespace="independent-namespace",
        witness_public_key_sha256="4" * 64,
        witness_sequence=99,
    ) is None


def test_existing_publication_rejects_non_successor_witness_sequence(
    publication_bundle: dict[str, Any],
) -> None:
    contract = publication_bundle["first"].checkpoint_manifest.checkpoint_evidence[
        "authenticated_profiled_supervised_publication"
    ]
    inputs = {
        "candidate_checkpoint_manager": publication_bundle["candidate_manager"],
        "manifest_id": "1" * 64,
        "completion_event_sha256": "2" * 64,
        "external_authorization_envelope_sha256": "3" * 64,
        "witness_id": contract["witness_id"],
        "witness_namespace": contract["witness_namespace"],
        "witness_public_key_sha256": contract["witness_public_key_sha256"],
    }

    with pytest.raises(
        publication_module.AuthenticatedProfiledSupervisedCheckpointPublicationV1Error,
        match="PROFILED_SUPERVISED_PUBLICATION_WITNESS_SEQUENCE_NOT_SUCCESSOR",
    ):
        publication_module.find_authenticated_profiled_supervised_publication_for_completion_v1(  # noqa: E501
            **inputs,
            witness_sequence=contract["witness_sequence"],
        )
    with pytest.raises(
        publication_module.AuthenticatedProfiledSupervisedCheckpointPublicationV1Error,
        match="PROFILED_SUPERVISED_PUBLICATION_WITNESS_SEQUENCE_NOT_SUCCESSOR",
    ):
        publication_module.find_authenticated_profiled_supervised_publication_for_completion_v1(  # noqa: E501
            **{**inputs, "witness_public_key_sha256": "f" * 64},
            witness_sequence=contract["witness_sequence"],
        )
    assert (
        publication_module.find_authenticated_profiled_supervised_publication_for_completion_v1(  # noqa: E501
            **inputs,
            witness_sequence=contract["witness_sequence"] + 1,
        )
        is None
    )


def test_existing_publication_identity_overlap_conflict_fails_closed(
    publication_bundle: dict[str, Any],
) -> None:
    contract = publication_bundle["first"].checkpoint_manifest.checkpoint_evidence[
        "authenticated_profiled_supervised_publication"
    ]
    with pytest.raises(
        publication_module.AuthenticatedProfiledSupervisedCheckpointPublicationV1Error,
        match="PROFILED_SUPERVISED_EXISTING_PUBLICATION_IDENTITY_CONFLICT",
    ):
        publication_module.find_authenticated_profiled_supervised_publication_for_completion_v1(  # noqa: E501
            candidate_checkpoint_manager=publication_bundle["candidate_manager"],
            manifest_id="1" * 64,
            completion_event_sha256=contract["completion_event_sha256"],
            external_authorization_envelope_sha256=(
                contract["external_authorization_envelope_sha256"]
            ),
            witness_id=contract["witness_id"],
            witness_namespace=contract["witness_namespace"],
            witness_public_key_sha256=contract["witness_public_key_sha256"],
            witness_sequence=contract["witness_sequence"],
        )


def test_identical_retry_reuses_exact_manifest_weight_and_generation(
    publication_bundle: dict[str, Any],
) -> None:
    first = publication_bundle["first"]
    second = publication_bundle["second"]
    weight_path = publication_bundle["weight_path"]
    manifest_path = publication_bundle["manifest_path"]

    assert second.candidate_checkpoint_id == first.candidate_checkpoint_id
    assert second.candidate_checkpoint_generation == first.candidate_checkpoint_generation
    assert second.candidate_checkpoint_weight_sha256 == (
        first.candidate_checkpoint_weight_sha256
    )
    assert second.publication_idempotency_key == first.publication_idempotency_key
    assert second.publication_receipt_sha256 == first.publication_receipt_sha256
    assert weight_path.stat().st_ino == publication_bundle["first_weight_stat"].st_ino
    assert weight_path.read_bytes() == publication_bundle["first_weight_bytes"]
    assert manifest_path.read_bytes() == publication_bundle["first_manifest_bytes"]
    manifests = publication_bundle["candidate_manager"].manifests(
        input_dim=publication_bundle["base_model"].input_dim,
        model_id=publication_bundle["base_model"].model_id,
        allowed_lineage_kinds=frozenset(
            {AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}
        ),
        require_weight_blob=True,
    )
    assert [manifest.checkpoint_id for manifest in manifests] == [
        first.candidate_checkpoint_id
    ]


def test_lost_post_commit_acknowledgement_recovers_by_identical_retry(
    publication_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = publication_bundle["candidate_manager"]
    original_write = manager.write_checkpoint

    def write_then_lose_acknowledgement(**kwargs: Any) -> Any:
        original_write(**kwargs)
        raise RuntimeError("simulated_post_commit_ack_loss")

    monkeypatch.setattr(manager, "write_checkpoint", write_then_lose_acknowledgement)
    with pytest.raises(
        publication_module.AuthenticatedProfiledSupervisedCheckpointPublicationV1Error,
        match="PROFILED_SUPERVISED_PUBLICATION_CHECKPOINT_WRITE_FAILED",
    ):
        _publish(
            bound_execution=publication_bundle["bound_execution"],
            candidate_checkpoint_manager=manager,
        )
    monkeypatch.setattr(manager, "write_checkpoint", original_write)

    recovered = _publish(
        bound_execution=publication_bundle["bound_execution"],
        candidate_checkpoint_manager=manager,
    )

    assert recovered.candidate_checkpoint_id == (
        publication_bundle["first"].candidate_checkpoint_id
    )
    assert recovered.candidate_checkpoint_generation == 2
    assert publication_bundle["weight_path"].read_bytes() == (
        publication_bundle["first_weight_bytes"]
    )


def test_different_stage_clocks_converge_to_same_durable_publication(
    publication_bundle: dict[str, Any],
) -> None:
    trainer = publication_bundle["trainer"]
    start = trainer.training_observed_at + timedelta(minutes=5)
    clocks = iter(start + timedelta(seconds=offset) for offset in range(1, 8))
    inputs = execution_support._execution_inputs(
        publication_bundle["corpus_bundle"],
        model=publication_bundle["base_model"],
        trainer=trainer,
    )
    inputs["clock"] = lambda: next(clocks)
    rebound = publication_module.execute_lineage_bound_authenticated_profiled_supervised_optimizer_v1(  # noqa: E501
        base_lineage=publication_bundle["base_lineage"],
        base_checkpoint_manager=publication_bundle["base_manager"],
        **inputs,
    )
    converged = _publish(
        bound_execution=rebound,
        candidate_checkpoint_manager=publication_bundle["candidate_manager"],
    )

    assert rebound.execution.in_memory_execution_receipt_sha256 != (
        publication_bundle["bound_execution"].execution.in_memory_execution_receipt_sha256
    )
    assert rebound.lineage_bound_execution_sha256 == (
        publication_bundle["bound_execution"].lineage_bound_execution_sha256
    )
    assert converged.candidate_checkpoint_id == (
        publication_bundle["first"].candidate_checkpoint_id
    )
    assert converged.publication_receipt_sha256 == (
        publication_bundle["first"].publication_receipt_sha256
    )


def test_sealed_lineage_binding_rejects_post_hoc_rebinding(
    publication_bundle: dict[str, Any],
) -> None:
    with pytest.raises(
        publication_module.AuthenticatedProfiledSupervisedCheckpointPublicationV1Error,
        match="PROFILED_SUPERVISED_PUBLICATION_BOUND_EXECUTION_INVALID",
    ):
        replace(
            publication_bundle["bound_execution"],
            base_checkpoint_lineage_binding_sha256="0" * 64,
        )


def test_publication_receipt_is_sealed_and_manifest_accessor_is_detached(
    publication_bundle: dict[str, Any],
) -> None:
    result = publication_bundle["first"]
    detached = result.checkpoint_manifest
    detached.checkpoint_evidence["detached_mutation"] = True

    result.__post_init__()
    assert "detached_mutation" not in result.checkpoint_manifest.checkpoint_evidence
    with pytest.raises(
        publication_module.AuthenticatedProfiledSupervisedCheckpointPublicationV1Error,
        match="PROFILED_SUPERVISED_PUBLICATION_RESULT_COPY_OR_PICKLE_FORBIDDEN",
    ):
        copy(result)
    with pytest.raises(
        publication_module.AuthenticatedProfiledSupervisedCheckpointPublicationV1Error,
        match="PROFILED_SUPERVISED_PUBLICATION_RESULT_INVALID",
    ):
        replace(result, checkpoint_write_authorized=True)


def test_base_capability_detects_nested_manifest_evidence_mutation(
    publication_bundle: dict[str, Any],
) -> None:
    lineage = publication_bundle["base_lineage"]
    evidence = lineage._manifest_owner.checkpoint_evidence
    original = deepcopy(evidence)
    try:
        evidence["post_capture_mutation"] = True
        with pytest.raises(
            AuthenticatedProfiledBaseCheckpointLineageV1Error,
            match="PROFILED_BASE_LINEAGE_RESULT_INVALID",
        ):
            lineage.__post_init__()
    finally:
        evidence.clear()
        evidence.update(original)
    lineage.__post_init__()
    try:
        evidence["non_json_mutation"] = object()
        with pytest.raises(
            AuthenticatedProfiledBaseCheckpointLineageV1Error,
            match="PROFILED_BASE_LINEAGE_CHECKPOINT_EVIDENCE_INVALID",
        ):
            lineage.__post_init__()
    finally:
        evidence.clear()
        evidence.update(original)
    lineage.__post_init__()


def test_profiled_candidate_cannot_be_reopened_as_fresh_process_base(
    publication_bundle: dict[str, Any],
) -> None:
    with pytest.raises(
        AuthenticatedProfiledBaseCheckpointLineageV1Error,
        match="PROFILED_BASE_LINEAGE_KIND_OR_EVIDENCE_INVALID",
    ):
        capture_authenticated_profiled_base_checkpoint_lineage_v1(
            base_model=publication_bundle["bound_execution"].candidate_model,
            base_checkpoint_manager=publication_bundle["candidate_manager"],
            expected_checkpoint_id=(
                publication_bundle["first"].candidate_checkpoint_id
            ),
        )


def test_base_weight_tamper_fails_before_any_new_checkpoint_write(
    publication_bundle: dict[str, Any],
) -> None:
    base_manager = publication_bundle["base_manager"]
    base_manifest = publication_bundle["base_manifest"]
    base_weight_path = base_manager.model_dir / (
        f"{base_manifest.checkpoint_id}.weights.npz"
    )
    original = base_weight_path.read_bytes()
    profiled_before = publication_bundle["candidate_manager"].manifests(
        allowed_lineage_kinds=frozenset(
            {AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}
        )
    )
    tampered = bytearray(original)
    tampered[len(tampered) // 2] ^= 1
    try:
        base_weight_path.write_bytes(tampered)
        with pytest.raises(
            publication_module.AuthenticatedProfiledSupervisedCheckpointPublicationV1Error,
            match="PROFILED_SUPERVISED_PUBLICATION_PREWRITE_REVALIDATION_FAILED",
        ):
            _publish(
                bound_execution=publication_bundle["bound_execution"],
                candidate_checkpoint_manager=publication_bundle["candidate_manager"],
            )
    finally:
        base_weight_path.write_bytes(original)
    profiled_after = publication_bundle["candidate_manager"].manifests(
        allowed_lineage_kinds=frozenset(
            {AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}
        )
    )
    assert profiled_after == profiled_before


def test_missing_exact_parent_fails_closed_without_optimizer_execution(
    publication_bundle: dict[str, Any],
    tmp_path: Path,
) -> None:
    empty_manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "empty")
    with pytest.raises(
        AuthenticatedProfiledBaseCheckpointLineageV1Error,
        match="PROFILED_BASE_LINEAGE_CHECKPOINT_NOT_EXACTLY_RESOLVED",
    ):
        capture_authenticated_profiled_base_checkpoint_lineage_v1(
            base_model=publication_bundle["base_model"],
            base_checkpoint_manager=empty_manager,
            expected_checkpoint_id="missing-checkpoint",
        )
    assert empty_manager.manifests() == ()


def test_profiled_lineage_does_not_shadow_normal_candidate_selection(
    publication_bundle: dict[str, Any],
) -> None:
    manager = publication_bundle["candidate_manager"]
    base_manifest = publication_bundle["base_manifest"]
    normal = manager.write_checkpoint(
        model=publication_bundle["base_model"],
        input_dim=publication_bundle["base_model"].input_dim,
        device=publication_bundle["base_model"].device,
        cuda_active=publication_bundle["base_model"].cuda_active,
        lineage_kind=NON_SERVING_CANDIDATE_LINEAGE,
        parent_checkpoint_id=base_manifest.checkpoint_id,
        parent_policy_fingerprint=base_manifest.model_parameter_fingerprint,
        checkpoint_evidence={"checkpoint_role": NON_SERVING_CANDIDATE_LINEAGE},
    )

    selected_normal = manager.latest_manifest(
        input_dim=publication_bundle["base_model"].input_dim,
        model_id=publication_bundle["base_model"].model_id,
        allowed_lineage_kinds=frozenset({NON_SERVING_CANDIDATE_LINEAGE}),
    )
    selected_profiled = manager.latest_manifest(
        input_dim=publication_bundle["base_model"].input_dim,
        model_id=publication_bundle["base_model"].model_id,
        allowed_lineage_kinds=frozenset(
            {AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}
        ),
    )

    assert selected_normal == normal
    assert selected_profiled == publication_bundle["first"].checkpoint_manifest
    assert selected_normal.checkpoint_id != selected_profiled.checkpoint_id


def test_exported_publication_rejects_non_successor_across_model_and_key_rotation(
    publication_bundle: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = publication_bundle["candidate_manager"]
    base_manifest = publication_bundle["base_manifest"]
    first_contract = publication_bundle[
        "first"
    ].checkpoint_manifest.checkpoint_evidence[
        "authenticated_profiled_supervised_publication"
    ]
    cross_model_contract = deepcopy(first_contract)
    cross_model_contract.update(
        {
            "publication_idempotency_key": "a" * 64,
            "execution_idempotency_key": "b" * 64,
            "manifest_id": "c" * 64,
            "completion_event_sha256": "d" * 64,
            "external_authorization_envelope_sha256": "e" * 64,
            "witness_public_key_sha256": "f" * 64,
            "witness_sequence": first_contract["witness_sequence"] + 1,
        }
    )
    cross_model = V2HybridPolicyModel(
        input_dim=publication_bundle["base_model"].input_dim + 1,
        seed=313,
    )
    manager.write_checkpoint(
        model=cross_model,
        input_dim=cross_model.input_dim,
        device=cross_model.device,
        cuda_active=cross_model.cuda_active,
        lineage_kind=AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
        parent_checkpoint_id=base_manifest.checkpoint_id,
        parent_policy_fingerprint=base_manifest.model_parameter_fingerprint,
        training_partition_digest=publication_bundle["first"].training_partition_digest,
        checkpoint_evidence={
            "checkpoint_role": AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
            "authenticated_profiled_supervised_publication": cross_model_contract,
        },
    )
    original_contract = publication_module._publication_contract

    def rolled_back_contract(**kwargs: Any) -> dict[str, Any]:
        contract = deepcopy(original_contract(**kwargs))
        contract.update(
            {
                "publication_idempotency_key": "1" * 64,
                "execution_idempotency_key": "2" * 64,
                "manifest_id": "3" * 64,
                "completion_event_sha256": "4" * 64,
                "external_authorization_envelope_sha256": "5" * 64,
                "witness_public_key_sha256": "6" * 64,
                "witness_sequence": first_contract["witness_sequence"] + 1,
            }
        )
        return contract

    monkeypatch.setattr(
        publication_module,
        "_publication_contract",
        rolled_back_contract,
    )
    with pytest.raises(
        publication_module.AuthenticatedProfiledSupervisedCheckpointPublicationV1Error,
        match="PROFILED_SUPERVISED_PUBLICATION_WITNESS_SEQUENCE_NOT_SUCCESSOR",
    ):
        _publish(
            bound_execution=publication_bundle["bound_execution"],
            candidate_checkpoint_manager=publication_bundle["candidate_manager"],
        )


def test_reused_execution_identity_conflict_fails_before_another_write(
    publication_bundle: dict[str, Any],
) -> None:
    manager = publication_bundle["candidate_manager"]
    base_manifest = publication_bundle["base_manifest"]
    contract = deepcopy(
        publication_bundle["first"].checkpoint_manifest.checkpoint_evidence[
            "authenticated_profiled_supervised_publication"
        ]
    )
    contract["publication_idempotency_key"] = "0" * 64
    manager.write_checkpoint(
        model=publication_bundle["base_model"],
        input_dim=publication_bundle["base_model"].input_dim,
        device=publication_bundle["base_model"].device,
        cuda_active=publication_bundle["base_model"].cuda_active,
        lineage_kind=AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
        parent_checkpoint_id=base_manifest.checkpoint_id,
        parent_policy_fingerprint=base_manifest.model_parameter_fingerprint,
        training_partition_digest=publication_bundle["first"].training_partition_digest,
        checkpoint_evidence={
            "checkpoint_role": AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
            "authenticated_profiled_supervised_publication": contract,
        },
    )
    before = manager.manifests(
        allowed_lineage_kinds=frozenset(
            {AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}
        )
    )

    with pytest.raises(
        publication_module.AuthenticatedProfiledSupervisedCheckpointPublicationV1Error,
        match="PROFILED_SUPERVISED_PUBLICATION_EXECUTION_IDENTITY_CONFLICT",
    ):
        _publish(
            bound_execution=publication_bundle["bound_execution"],
            candidate_checkpoint_manager=manager,
        )

    after = manager.manifests(
        allowed_lineage_kinds=frozenset(
            {AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}
        )
    )
    assert after == before
