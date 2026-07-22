from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer.authenticated_profiled_base_checkpoint_lineage_v1 import (  # noqa: E501
    AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_BASE_LINEAGE,
    AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_BASE_V1_SCHEMA_VERSION,
    AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_LEDGER_DISPOSITION,
    AuthenticatedProfiledBaseCheckpointLineageV1Error,
    ensure_authenticated_profiled_genesis_base_checkpoint_v1,
)
from v2.backend.app.services.native_trainer.checkpoint_feature_abi_binding_v4 import (
    deployed_checkpoint_feature_abi_binding_v4,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (  # noqa: E501
    VERIFIED_SERVING_LINEAGE,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (  # noqa: E501
    LOGICAL_MODEL_INPUT_COUNT,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_authenticated_profiled_supervised_optimizer_execution_v1 as execution_support,
)


@pytest.fixture
def genesis_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, Any]:
    execution_support._configure_cpu(monkeypatch)
    root = tmp_path / ".local_models" / "profiled-genesis"
    model = V2HybridPolicyModel(
        input_dim=LOGICAL_MODEL_INPUT_COUNT,
        checkpoint_feature_abi_binding=deployed_checkpoint_feature_abi_binding_v4(),
    )
    return {
        "root": root,
        "manager": V2HybridCheckpointManager(root),
        "model": model,
    }


def test_fresh_store_persists_generation_one_non_serving_genesis_exactly_once(
    genesis_runtime: dict[str, Any],
) -> None:
    manager = genesis_runtime["manager"]
    model = genesis_runtime["model"]

    first = ensure_authenticated_profiled_genesis_base_checkpoint_v1(
        base_model=model,
        base_checkpoint_manager=manager,
    )
    (manifest,) = manager.manifests(
        allowed_lineage_kinds=frozenset(
            {AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_BASE_LINEAGE}
        ),
        require_weight_blob=True,
    )
    manifest_path = manager.model_dir / f"{manifest.checkpoint_id}.json"
    weight_path = manager.model_dir / f"{manifest.checkpoint_id}.weights.npz"
    manifest_stat = manifest_path.stat()
    weight_stat = weight_path.stat()
    manifest_bytes = manifest_path.read_bytes()
    weight_bytes = weight_path.read_bytes()

    second = ensure_authenticated_profiled_genesis_base_checkpoint_v1(
        base_model=model,
        base_checkpoint_manager=manager,
    )

    contract = manifest.checkpoint_evidence[
        "authenticated_profiled_supervised_genesis_base"
    ]
    assert manifest.checkpoint_generation == 1
    assert manifest.parent_checkpoint_id is None
    assert manifest.parent_checkpoint_generation is None
    assert manifest.parent_policy_fingerprint is None
    assert manifest.consumed_ppo_update_keys == ()
    assert manifest.training_partition_digest is None
    assert contract["schema_version"] == (
        AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_BASE_V1_SCHEMA_VERSION
    )
    assert contract["ledger_disposition"] == (
        AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_LEDGER_DISPOSITION
    )
    assert contract["deterministic_untrained_initialization"] is True
    assert contract["market_data_consumed"] is False
    assert contract["training_sample_consumed"] is False
    assert contract["optimizer_step_completed"] is False
    assert contract["non_serving_base_only"] is True
    assert contract["checkpoint_write_authorized"] is True
    for field_name in (
        "prediction_authorized",
        "serving_authorized",
        "serving_activation_authorized",
        "serving_promotion_authorized",
        "ppo_training_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "exchange_access_authorized",
        "deployment_authorized",
        "order_submission_authorized",
        "execution_authorized",
        "runtime_wired",
    ):
        assert contract[field_name] is False
    assert first.checkpoint_id == second.checkpoint_id == manifest.checkpoint_id
    assert first.checkpoint_generation == second.checkpoint_generation == 1
    assert first.checkpoint_write_authorized is False
    assert first.serving_authorized is False
    assert first.trading_authorized is False
    assert manifest_path.stat().st_ino == manifest_stat.st_ino
    assert weight_path.stat().st_ino == weight_stat.st_ino
    assert manifest_path.read_bytes() == manifest_bytes
    assert weight_path.read_bytes() == weight_bytes
    assert manager.manifests(
        allowed_lineage_kinds=frozenset({VERIFIED_SERVING_LINEAGE}),
    ) == ()


def test_mutated_genesis_evidence_fails_closed(
    genesis_runtime: dict[str, Any],
) -> None:
    manager = genesis_runtime["manager"]
    model = genesis_runtime["model"]
    lineage = ensure_authenticated_profiled_genesis_base_checkpoint_v1(
        base_model=model,
        base_checkpoint_manager=manager,
    )
    manifest_path = manager.model_dir / f"{lineage.checkpoint_id}.json"
    original = manifest_path.read_bytes()
    payload = json.loads(original)
    payload["checkpoint_evidence"][
        "authenticated_profiled_supervised_genesis_base"
    ]["training_sample_consumed"] = True
    try:
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(
            AuthenticatedProfiledBaseCheckpointLineageV1Error,
            match="PROFILED_GENESIS_BASE_MANIFEST_SCAN_FAILED",
        ):
            ensure_authenticated_profiled_genesis_base_checkpoint_v1(
                base_model=model,
                base_checkpoint_manager=manager,
            )
    finally:
        manifest_path.write_bytes(original)


def test_verified_serving_parent_blocks_genesis_without_writing(
    genesis_runtime: dict[str, Any],
) -> None:
    manager = genesis_runtime["manager"]
    model = genesis_runtime["model"]
    serving = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=VERIFIED_SERVING_LINEAGE,
        checkpoint_evidence={"checkpoint_role": VERIFIED_SERVING_LINEAGE},
    )
    before = manager.manifests()

    with pytest.raises(
        AuthenticatedProfiledBaseCheckpointLineageV1Error,
        match="PROFILED_GENESIS_BASE_VERIFIED_SERVING_BASE_ALREADY_EXISTS",
    ):
        ensure_authenticated_profiled_genesis_base_checkpoint_v1(
            base_model=model,
            base_checkpoint_manager=manager,
        )

    assert manager.manifests() == before == (serving,)


def test_non_root_causal_record_blocks_late_genesis_without_advancing_ledger(
    genesis_runtime: dict[str, Any],
) -> None:
    root_manager = genesis_runtime["manager"]
    model = genesis_runtime["model"]
    candidate_manager = V2HybridCheckpointManager(
        genesis_runtime["root"] / "non_serving_training_candidates"
    )
    existing = candidate_manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="TEST_NON_SERVING_CAUSAL_RECORD",
        checkpoint_evidence={"checkpoint_role": "TEST_NON_SERVING_CAUSAL_RECORD"},
    )
    ledger_before = tuple(root_manager._read_causal_ledger())  # noqa: SLF001

    with pytest.raises(
        AuthenticatedProfiledBaseCheckpointLineageV1Error,
        match="PROFILED_GENESIS_BASE_CAUSAL_LEDGER_NOT_EMPTY",
    ):
        ensure_authenticated_profiled_genesis_base_checkpoint_v1(
            base_model=model,
            base_checkpoint_manager=root_manager,
        )

    assert root_manager.manifests() == ()
    assert candidate_manager.manifests() == (existing,)
    assert tuple(root_manager._read_causal_ledger()) == ledger_before  # noqa: SLF001


def test_expected_generation_guard_rejects_conflict_before_ledger_append(
    genesis_runtime: dict[str, Any],
) -> None:
    manager = genesis_runtime["manager"]
    model = genesis_runtime["model"]
    first = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="TEST_GENERATION_ONE",
        checkpoint_evidence={"checkpoint_role": "TEST_GENERATION_ONE"},
    )
    identical_retry = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind="TEST_GENERATION_ONE",
        checkpoint_evidence={"checkpoint_role": "TEST_GENERATION_ONE"},
        expected_checkpoint_generation=1,
    )
    ledger_before = tuple(manager._read_causal_ledger())  # noqa: SLF001

    with pytest.raises(RuntimeError, match="checkpoint_expected_generation_conflict"):
        manager.write_checkpoint(
            model=model,
            input_dim=model.input_dim,
            device=model.device,
            cuda_active=model.cuda_active,
            lineage_kind="TEST_LATE_GENESIS",
            checkpoint_evidence={"checkpoint_role": "TEST_LATE_GENESIS"},
            expected_checkpoint_generation=1,
        )

    assert identical_retry == first
    assert manager.manifests() == (first,)
    assert tuple(manager._read_causal_ledger()) == ledger_before  # noqa: SLF001
