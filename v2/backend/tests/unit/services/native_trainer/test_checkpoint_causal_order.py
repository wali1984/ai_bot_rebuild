from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    checkpoint as checkpoint_module,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    CHECKPOINT_CAUSAL_ORDER_SCHEMA_VERSION,
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (
    NON_SERVING_CANDIDATE_LINEAGE,
    REJECTED_ATTEMPT_LINEAGE,
    VERIFIED_SERVING_LINEAGE,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    model_parameter_fingerprint,
)


def _mutate_model(model: V2HybridPolicyModel) -> None:
    if model.torch_available:
        assert model.torch is not None and model.net is not None
        with model.torch.no_grad():
            next(model.net.parameters()).view(-1)[0].add_(0.001)
    else:
        model._fallback_weights[0] += 0.001  # noqa: SLF001


def test_causal_generation_survives_clock_rollback_equal_clocks_and_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    generated = iter(
        (
            "2099-01-01T00:00:00Z",
            "2001-01-01T00:00:00Z",
            "2001-01-01T00:00:00Z",
            "1999-01-01T00:00:00Z",
        )
    )
    monkeypatch.setattr(checkpoint_module, "_utc_iso", lambda: next(generated))
    root = tmp_path / ".local_models" / "causal"
    serving = V2HybridCheckpointManager(root)
    candidate = V2HybridCheckpointManager(
        root / "non_serving_training_candidates"
    )
    rejected = V2HybridCheckpointManager(root / "rejected_optimizer_attempts")
    model = V2HybridPolicyModel(input_dim=4, seed=401)

    serving_manifest = serving.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=VERIFIED_SERVING_LINEAGE,
        checkpoint_evidence={"checkpoint_role": VERIFIED_SERVING_LINEAGE},
    )
    serving_fingerprint = model_parameter_fingerprint(model)
    _mutate_model(model)
    first_candidate = candidate.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=NON_SERVING_CANDIDATE_LINEAGE,
        parent_checkpoint_id=serving_manifest.checkpoint_id,
        parent_policy_fingerprint=serving_fingerprint,
        checkpoint_evidence={"checkpoint_role": NON_SERVING_CANDIDATE_LINEAGE},
    )
    _mutate_model(model)
    sibling_rejection = rejected.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=REJECTED_ATTEMPT_LINEAGE,
        parent_checkpoint_id=serving_manifest.checkpoint_id,
        parent_policy_fingerprint=serving_fingerprint,
        checkpoint_evidence={"checkpoint_role": REJECTED_ATTEMPT_LINEAGE},
    )
    _mutate_model(model)
    latest_candidate = candidate.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=NON_SERVING_CANDIDATE_LINEAGE,
        parent_checkpoint_id=first_candidate.checkpoint_id,
        parent_policy_fingerprint=first_candidate.model_parameter_fingerprint,
        checkpoint_evidence={
            "checkpoint_role": NON_SERVING_CANDIDATE_LINEAGE,
            "branch": "candidate_child",
        },
    )

    assert [
        serving_manifest.checkpoint_generation,
        first_candidate.checkpoint_generation,
        sibling_rejection.checkpoint_generation,
        latest_candidate.checkpoint_generation,
    ] == [1, 2, 3, 4]
    assert first_candidate.parent_checkpoint_generation == 1
    assert sibling_rejection.parent_checkpoint_generation == 1
    assert latest_candidate.parent_checkpoint_generation == 2
    assert candidate.latest_manifest().checkpoint_id == latest_candidate.checkpoint_id
    assert sibling_rejection.generated_utc == first_candidate.generated_utc
    assert latest_candidate.generated_utc < first_candidate.generated_utc
    verified = candidate.verify_manifest_artifact(latest_candidate)
    assert verified["checkpoint_artifact_verified"] is True
    assert verified["checkpoint_generation"] == 4
    assert verified["checkpoint_causal_order_schema_version"] == (
        CHECKPOINT_CAUSAL_ORDER_SCHEMA_VERSION
    )
    assert latest_candidate.checkpoint_evidence["checkpoint_generation"] == 4
    assert latest_candidate.checkpoint_evidence_digest


def test_causal_manifest_generation_tamper_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    manager = V2HybridCheckpointManager(tmp_path / ".local_models" / "tamper")
    model = V2HybridPolicyModel(input_dim=4, seed=409)
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        checkpoint_evidence={"checkpoint_role": "SERVING_CANDIDATE"},
    )
    path = Path(manifest.path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["checkpoint_generation"] = manifest.checkpoint_generation + 1
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(RuntimeError, match="checkpoint_manifest_scan_invalid"):
        manager.manifests()


def test_causal_ledger_hash_chain_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".local_models" / "ledger_tamper"
    manager = V2HybridCheckpointManager(root)
    for index in range(2):
        manager.write_manifest(
            model_id=f"ledger_tamper_model_{index}",
            input_dim=4,
            device="cpu",
            cuda_active=False,
            checkpoint_evidence={"index": index},
        )
    ledger = root / ".checkpoint-causal-order.jsonl"
    rows = ledger.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["generated_utc"] = "1990-01-01T00:00:00Z"
    rows[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="checkpoint_manifest_scan_invalid"):
        manager.manifests()


def test_torn_uncommitted_ledger_tail_is_recovered_under_global_lock(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".local_models" / "torn_tail"
    manager = V2HybridCheckpointManager(root)
    first = manager.write_manifest(
        model_id="torn_tail_model_1",
        input_dim=4,
        device="cpu",
        cuda_active=False,
        checkpoint_evidence={"index": 1},
    )
    ledger = root / ".checkpoint-causal-order.jsonl"
    with ledger.open("ab") as handle:
        handle.write(b'{"schema_version":"torn')

    assert manager.manifests()[0].checkpoint_id == first.checkpoint_id
    assert ledger.read_bytes().endswith(b"\n")
    second = manager.write_manifest(
        model_id="torn_tail_model_2",
        input_dim=4,
        device="cpu",
        cuda_active=False,
        checkpoint_evidence={"index": 2},
    )
    assert second.checkpoint_generation == 2


def test_deleted_parent_artifact_invalidates_descendant_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    root = tmp_path / ".local_models" / "parent_hole"
    serving = V2HybridCheckpointManager(root)
    candidate = V2HybridCheckpointManager(
        root / "non_serving_training_candidates"
    )
    model = V2HybridPolicyModel(input_dim=4, seed=413)
    parent = serving.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=VERIFIED_SERVING_LINEAGE,
        checkpoint_evidence={"checkpoint_role": VERIFIED_SERVING_LINEAGE},
    )
    _mutate_model(model)
    child = candidate.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=NON_SERVING_CANDIDATE_LINEAGE,
        parent_checkpoint_id=parent.checkpoint_id,
        parent_policy_fingerprint=parent.model_parameter_fingerprint,
        checkpoint_evidence={"checkpoint_role": NON_SERVING_CANDIDATE_LINEAGE},
    )
    Path(parent.path).unlink()
    Path(parent.weight_file_path or "").unlink()

    with pytest.raises(RuntimeError, match="checkpoint_manifest_scan_invalid"):
        candidate.manifests()
    verified = candidate.verify_manifest_artifact(child)
    assert verified["checkpoint_artifact_verified"] is False
    assert "CHECKPOINT_CAUSAL_ORDER_BINDING_INVALID" in verified[
        "artifact_verification_rejection_reasons"
    ]


def test_identical_semantics_in_different_stores_get_distinct_generations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    root = tmp_path / ".local_models" / "cross_store"
    serving = V2HybridCheckpointManager(root)
    candidate = V2HybridCheckpointManager(
        root / "non_serving_training_candidates"
    )
    model = V2HybridPolicyModel(input_dim=4, seed=417)
    kwargs = {
        "model": model,
        "input_dim": 4,
        "device": model.device,
        "cuda_active": model.cuda_active,
        "checkpoint_evidence": {"same": "semantics"},
    }
    root_manifest = serving.write_checkpoint(**kwargs)
    candidate_manifest = candidate.write_checkpoint(**kwargs)

    assert root_manifest.checkpoint_generation == 1
    assert candidate_manifest.checkpoint_generation == 2
    assert root_manifest.checkpoint_id != candidate_manifest.checkpoint_id
    _mutate_model(model)
    child = serving.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        parent_checkpoint_id=root_manifest.checkpoint_id,
        parent_policy_fingerprint=root_manifest.model_parameter_fingerprint,
        checkpoint_evidence={"child": True},
    )
    assert child.parent_checkpoint_generation == 1


def test_well_formed_legacy_parent_gets_zero_generation_migration_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    root = tmp_path / ".local_models" / "legacy_migration"
    root.mkdir(parents=True)
    model = V2HybridPolicyModel(input_dim=4, seed=419)
    parent_fingerprint = model_parameter_fingerprint(model)
    legacy_id = "v2_hybrid_ckpt_legacy_parent"
    legacy_path = root / f"{legacy_id}.json"
    weight_path = root / f"{legacy_id}.weights.npz"
    weight = model.save_weight_blob(weight_path)
    weight_sha256 = hashlib.sha256(weight_path.read_bytes()).hexdigest()
    legacy_path.write_text(
        json.dumps(
            {
                "checkpoint_id": legacy_id,
                "checkpoint_source": "V2_LOCAL_TRAINED",
                "path": str(legacy_path),
                "generated_utc": "2026-01-01T00:00:00Z",
                "model_id": model.model_id,
                "input_dim": 4,
                "device": model.device,
                "cuda_active": model.cuda_active,
                "weight_blob_written": True,
                "weight_file_path": weight["weight_file_path"],
                "weight_file_format": weight["weight_file_format"],
                "weight_file_size_bytes": weight["weight_file_size_bytes"],
                "weight_file_sha256": weight_sha256,
                "model_parameter_fingerprint": parent_fingerprint,
                "confidence_calibration_state": (
                    model.confidence_calibration_state
                ),
            }
        ),
        encoding="utf-8",
    )
    _mutate_model(model)
    manager = V2HybridCheckpointManager(root)
    child = manager.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        parent_checkpoint_id=legacy_id,
        parent_policy_fingerprint=parent_fingerprint,
        checkpoint_evidence={"migration": "legacy_parent"},
    )

    assert child.checkpoint_generation == 1
    assert child.parent_checkpoint_generation == 0
    assert manager.latest_manifest().checkpoint_id == child.checkpoint_id


def test_malformed_legacy_parent_is_not_used_as_migration_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    root = tmp_path / ".local_models" / "bad_legacy"
    root.mkdir(parents=True)
    model = V2HybridPolicyModel(input_dim=4, seed=421)
    fingerprint = model_parameter_fingerprint(model)
    legacy_id = "v2_hybrid_ckpt_bad_legacy_parent"
    (root / f"{legacy_id}.json").write_text(
        json.dumps(
            {
                "checkpoint_id": legacy_id,
                "generated_utc": "2026-01-01T00:00:00",
                "model_id": model.model_id,
                "input_dim": 4,
                "weight_blob_written": False,
                "model_parameter_fingerprint": fingerprint,
            }
        ),
        encoding="utf-8",
    )
    manager = V2HybridCheckpointManager(root)

    with pytest.raises(RuntimeError, match="checkpoint_parent_manifest_invalid"):
        manager.write_checkpoint(
            model=model,
            input_dim=4,
            device=model.device,
            cuda_active=model.cuda_active,
            parent_checkpoint_id=legacy_id,
            parent_policy_fingerprint=fingerprint,
        )


def test_shared_generation_ledger_serializes_concurrent_store_writers(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".local_models" / "concurrent"

    def write(index: int):
        directory = (
            root / "non_serving_training_candidates"
            if index % 2 == 0
            else root / "rejected_optimizer_attempts"
        )
        return V2HybridCheckpointManager(directory).write_manifest(
            model_id=f"concurrent_model_{index:04d}",
            input_dim=4,
            device="cpu",
            cuda_active=False,
            lineage_kind=(
                NON_SERVING_CANDIDATE_LINEAGE
                if index % 2 == 0
                else REJECTED_ATTEMPT_LINEAGE
            ),
            checkpoint_evidence={"writer_index": index},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        manifests = list(executor.map(write, range(16)))

    generations = {manifest.checkpoint_generation for manifest in manifests}
    assert generations == set(range(1, 17))
    ledger = root / ".checkpoint-causal-order.jsonl"
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 16
    for manager_dir in (
        root / "non_serving_training_candidates",
        root / "rejected_optimizer_attempts",
    ):
        manager = V2HybridCheckpointManager(manager_dir)
        assert len(manager.manifests()) == 8
