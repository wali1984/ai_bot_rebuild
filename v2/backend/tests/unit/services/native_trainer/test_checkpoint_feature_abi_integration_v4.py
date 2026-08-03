from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import struct
import zipfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from v2.backend.app.services.native_trainer import (
    checkpoint_feature_abi_binding_v4 as binding_module,
)
from v2.backend.app.services.native_trainer.checkpoint_feature_abi_binding_v4 import (
    CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM,
    CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256,
    canonical_deployed_checkpoint_feature_abi_binding_v4_json,
    deployed_checkpoint_feature_abi_binding_v4,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    checkpoint as checkpoint_module,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    model as model_module,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
    _private_checkpoint_copy,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    model_parameter_fingerprint,
)

_ABI_NPZ_KEY = "__checkpoint_feature_abi_binding_v4_json"
_ABI_EVIDENCE_KEY = "checkpoint_feature_abi_binding_v4"


def _production_model(seed: int) -> V2HybridPolicyModel:
    """Build a model that explicitly declares an audit-only artifact ABI."""

    return V2HybridPolicyModel(
        input_dim=CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM,
        seed=seed,
        checkpoint_feature_abi_binding=deployed_checkpoint_feature_abi_binding_v4(),
    )


def _model_state(model: V2HybridPolicyModel) -> tuple[str, bytes]:
    calibration = json.dumps(
        model.confidence_calibration_state,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    return model_parameter_fingerprint(model), calibration


def _distinct_production_target(seed: int) -> V2HybridPolicyModel:
    model = _production_model(seed)
    if model.torch_available and model.net is not None:
        with model.torch.no_grad():
            first = next(iter(model.net.parameters()))
            first.add_(0.125)
    else:
        model._fallback_weights[0] += 0.125
    return model


def _payload(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as archive:
        return {key: np.array(archive[key], copy=True) for key in archive.files}


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    with path.open("wb") as handle:
        np.savez_compressed(handle, **payload)


def _raw_npy(
    *,
    descr: str,
    shape: tuple[int, ...],
    payload: bytes = b"",
) -> bytes:
    header = repr(
        {
            "descr": descr,
            "fortran_order": False,
            "shape": shape,
        }
    ).encode("latin1")
    prefix_bytes = 10
    padding = (-((prefix_bytes + len(header) + 1) % 16)) % 16
    header = header + (b" " * padding) + b"\n"
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + payload


def _write_single_member_npz(
    path: Path,
    *,
    member: bytes,
    compression: int = zipfile.ZIP_STORED,
) -> None:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        archive.writestr("attacker.npy", member)


def _assert_v4_preflight_rejects_before_numpy(
    path: Path,
    *,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _production_model(883)
    original_import = checkpoint_module.importlib.import_module

    def guarded_import(name: str, *args: object, **kwargs: object) -> Any:
        if name == "numpy":
            raise AssertionError("NumPy accessed before declared-v4 preflight")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(
        checkpoint_module.importlib,
        "import_module",
        guarded_import,
    )
    with path.open("rb") as stream, pytest.raises(ValueError, match=reason):
        checkpoint_module._safe_npz_semantics(
            stream,
            model_id="declared-v4-preflight-test",
            checkpoint_feature_abi_binding=(
                deployed_checkpoint_feature_abi_binding_v4()
            ),
        )
    with path.open("rb") as stream, pytest.raises(ValueError, match=reason):
        target.load_weight_blob_stream(
            stream,
            source_label=str(path),
        )


def _retarget_manifest_weight(manifest_path: Path, weight_path: Path) -> None:
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["weight_file_size_bytes"] = weight_path.stat().st_size
    raw["weight_file_sha256"] = hashlib.sha256(weight_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(raw, indent=2, sort_keys=True),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _small_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    monkeypatch.setenv("V2_TRAINER_ATTENTION_ENABLED", "0")
    monkeypatch.setenv("V2_TRAINER_TEMPORAL_ENCODER", "")


def _rewrite_npz(
    source: Path,
    target: Path,
    *,
    replacement_binding_json: str | None,
) -> None:
    with np.load(source, allow_pickle=False) as archive:
        payload: dict[str, Any] = {
            key: np.array(archive[key], copy=True) for key in archive.files if key != _ABI_NPZ_KEY
        }
    if replacement_binding_json is not None:
        payload[_ABI_NPZ_KEY] = np.array([replacement_binding_json])
    with target.open("wb") as handle:
        np.savez_compressed(handle, **payload)


def test_production_weight_blob_embeds_exact_binding_and_direct_loads(
    tmp_path: Path,
) -> None:
    model = _production_model(811)
    weight_path = tmp_path / "bound.weights.npz"
    model.save_weight_blob(weight_path)

    with np.load(weight_path, allow_pickle=False) as archive:
        assert tuple(archive[_ABI_NPZ_KEY].shape) == (1,)
        assert str(archive[_ABI_NPZ_KEY][0]) == (
            canonical_deployed_checkpoint_feature_abi_binding_v4_json()
        )

    restored = _production_model(811)
    result = restored.load_weight_blob(weight_path)
    assert result["model_state_restored"] is True
    assert model_parameter_fingerprint(restored) == model_parameter_fingerprint(model)


def test_same_width_blob_without_binding_fails_before_model_mutation(
    tmp_path: Path,
) -> None:
    source_model = _production_model(821)
    source = tmp_path / "source.weights.npz"
    unbound = tmp_path / "unbound.weights.npz"
    source_model.save_weight_blob(source)
    _rewrite_npz(source, unbound, replacement_binding_json=None)

    target = _production_model(823)
    before = model_parameter_fingerprint(target)
    with pytest.raises(
        ValueError,
        match="metadata_missing:__checkpoint_feature_abi_binding_v4_json",
    ):
        target.load_weight_blob(unbound)
    assert model_parameter_fingerprint(target) == before


def test_coherently_rehashed_wrong_binding_fails_before_model_mutation(
    tmp_path: Path,
) -> None:
    source_model = _production_model(827)
    source = tmp_path / "source.weights.npz"
    forged_path = tmp_path / "forged.weights.npz"
    source_model.save_weight_blob(source)

    forged = deepcopy(deployed_checkpoint_feature_abi_binding_v4())
    forged["ordered_feature_names_sha256"] = "0" * 64
    material = {key: value for key, value in forged.items() if key != "binding_sha256"}
    forged["binding_sha256"] = binding_module._sha256_json(material)
    forged_json = json.dumps(
        forged,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    _rewrite_npz(
        source,
        forged_path,
        replacement_binding_json=forged_json,
    )

    target = _production_model(829)
    before = model_parameter_fingerprint(target)
    with pytest.raises(ValueError, match="DEPLOYED_ABI_MISMATCH"):
        target.load_weight_blob(forged_path)
    assert model_parameter_fingerprint(target) == before


def test_checkpoint_manager_binds_manifest_and_npz_and_verifies_both(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".local_models" / "abi-v4"
    model = _production_model(839)
    manager = V2HybridCheckpointManager(root)
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM,
        device=model.device,
        cuda_active=model.cuda_active,
        checkpoint_evidence={"test_scope": "checkpoint_feature_abi_v4"},
    )

    assert manifest.checkpoint_evidence[_ABI_EVIDENCE_KEY] == (
        deployed_checkpoint_feature_abi_binding_v4()
    )
    assert (
        manifest.checkpoint_evidence[_ABI_EVIDENCE_KEY]["binding_sha256"]
        == CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256
    )
    verification = manager.verify_manifest_artifact(manifest)
    assert verification["checkpoint_artifact_verified"] is True
    assert verification["artifact_verification_rejection_reasons"] == ()

    restored = _production_model(839)
    load_result = manager.load_latest_weights(restored)
    assert load_result["latest_checkpoint_loadable"] is True
    assert load_result["model_state_restored"] is True


def test_declared_load_rejects_manifest_binding_downgrade_before_private_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / ".local_models" / "abi-v4-downgrade"
    source = _production_model(847)
    manager = V2HybridCheckpointManager(root)
    manifest = manager.write_checkpoint(
        model=source,
        input_dim=source.input_dim,
        device=source.device,
        cuda_active=source.cuda_active,
    )
    downgraded = replace(
        manifest,
        checkpoint_evidence={
            key: value
            for key, value in manifest.checkpoint_evidence.items()
            if key != _ABI_EVIDENCE_KEY
        },
    )

    def unexpected_private_copy(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("binding downgrade must fail before artifact copy")

    monkeypatch.setattr(
        checkpoint_module,
        "_private_checkpoint_copy",
        unexpected_private_copy,
    )
    result = checkpoint_module._load_private_checkpoint_copy(
        source_path=root / f"{manifest.checkpoint_id}.weights.npz",
        manifest=downgraded,
        model=_production_model(847),
    )

    assert result["load_status"] == "CHECKPOINT_FEATURE_ABI_BINDING_MISMATCH"
    assert result["model_state_restored"] is False
    assert result["checkpoint_feature_abi_binding_verified"] is False


def test_checkpoint_writer_rejects_forged_binding_before_creating_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".local_models" / "forged-abi-v4"
    model = _production_model(853)
    forged = deepcopy(deployed_checkpoint_feature_abi_binding_v4())
    forged["ordered_requirement_classes_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="DIGEST_INVALID"):
        V2HybridCheckpointManager(root).write_checkpoint(
            model=model,
            input_dim=CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM,
            device=model.device,
            cuda_active=model.cuda_active,
            checkpoint_evidence={_ABI_EVIDENCE_KEY: forged},
        )
    assert not root.exists()


def test_nonproduction_dimension_does_not_claim_deployed_abi(tmp_path: Path) -> None:
    model = V2HybridPolicyModel(input_dim=4, seed=857)
    weight_path = tmp_path / "small.weights.npz"
    model.save_weight_blob(weight_path)
    with np.load(weight_path, allow_pickle=False) as archive:
        assert _ABI_NPZ_KEY not in archive.files

    restored = V2HybridPolicyModel(input_dim=4, seed=857)
    assert restored.load_weight_blob(weight_path)["model_state_restored"] is True


def test_checkpoint_writer_rejects_model_argument_dimension_mismatch(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".local_models" / "dimension-mismatch"
    model = V2HybridPolicyModel(input_dim=4, seed=859)

    with pytest.raises(ValueError, match="checkpoint_model_input_dim_mismatch"):
        V2HybridCheckpointManager(root).write_checkpoint(
            model=model,
            input_dim=CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM,
            device=model.device,
            cuda_active=model.cuda_active,
        )
    assert not root.exists()


@pytest.mark.parametrize("input_dim", ["4", 4.0, np.int64(4)])
def test_ordinary_model_preserves_int_convertible_input_dim(input_dim: object) -> None:
    assert V2HybridPolicyModel(input_dim=input_dim).input_dim == 4  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "input_dim",
    [True, "1784", 1784.0, np.int64(1784), 0, -1],
)
def test_declared_model_requires_builtin_positive_int(input_dim: object) -> None:
    with pytest.raises(ValueError, match="builtin_positive_int"):
        V2HybridPolicyModel(
            input_dim=input_dim,  # type: ignore[arg-type]
            checkpoint_feature_abi_binding=deployed_checkpoint_feature_abi_binding_v4(),
        )


def test_explicit_artifact_declaration_forks_model_id_without_runtime_authority() -> None:
    declared = _production_model(863)
    ordinary = V2HybridPolicyModel(
        input_dim=CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM,
        seed=863,
    )
    declaration = declared.checkpoint_feature_abi_declaration

    assert declared.model_id != ordinary.model_id
    assert declaration is not None
    assert declaration["binding_sha256"] == CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256
    assert declaration["training_tensor_values_bound"] is False
    assert declaration["per_slot_receipts_bound"] is False
    assert declaration["temporal_clocks_bound"] is False
    assert declaration["trainer_admission_authorized"] is False
    assert declared.forward(
        [0.0] * CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM
    ).model_id == declared.model_id


def test_ordinary_production_width_remains_forward_save_load_and_checkpoint_compatible(
    tmp_path: Path,
) -> None:
    source = V2HybridPolicyModel(
        input_dim=CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM,
        seed=877,
    )
    weight_path = tmp_path / "ordinary.weights.npz"
    source.save_weight_blob(weight_path)
    target = V2HybridPolicyModel(
        input_dim=CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM,
        seed=877,
    )
    with np.load(weight_path, allow_pickle=False) as archive:
        assert _ABI_NPZ_KEY not in archive.files

    assert target.load_weight_blob(weight_path)["model_state_restored"] is True
    assert target.forward(
        [0.0] * CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM
    ).model_id == target.model_id

    root = tmp_path / ".local_models" / "ordinary-production"
    manager = V2HybridCheckpointManager(root)
    manifest = manager.write_checkpoint(
        model=source,
        input_dim=source.input_dim,
        device=source.device,
        cuda_active=source.cuda_active,
    )
    assert _ABI_EVIDENCE_KEY not in manifest.checkpoint_evidence
    assert manager.load_latest_weights(target)["model_state_restored"] is True


def test_ordinary_checkpoint_lane_never_imports_v4_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_binding_import() -> Any:
        raise AssertionError("ordinary checkpoint imported v4 registry")

    monkeypatch.setattr(
        model_module,
        "_checkpoint_feature_abi_v4_module",
        forbidden_binding_import,
    )
    monkeypatch.setattr(
        checkpoint_module,
        "_checkpoint_feature_abi_v4_module",
        forbidden_binding_import,
    )
    source = V2HybridPolicyModel(input_dim=np.int64(4), seed=879)
    target = V2HybridPolicyModel(input_dim=np.int64(4), seed=879)
    root = tmp_path / ".local_models" / "ordinary-lazy-import"
    manager = V2HybridCheckpointManager(root)

    manifest = manager.write_checkpoint(
        model=source,
        input_dim=np.int64(4),
        device=source.device,
        cuda_active=source.cuda_active,
    )
    loaded = manager.load_latest_weights(target)

    assert _ABI_EVIDENCE_KEY not in manifest.checkpoint_evidence
    assert loaded["model_state_restored"] is True


def test_ordinary_direct_load_preserves_legacy_seed_keyset_and_calibration_rules(
    tmp_path: Path,
) -> None:
    source = V2HybridPolicyModel(input_dim=4, seed=881)
    original = tmp_path / "ordinary-source.weights.npz"
    legacy = tmp_path / "ordinary-legacy.weights.npz"
    source.save_weight_blob(original)
    payload = _payload(original)
    payload["__seed"] = np.array([999_999], dtype=np.int64)
    payload["__legacy_extra_metadata"] = np.array(["ignored-by-legacy-lane"])
    payload.pop("__confidence_calibration_state_json")
    _write_payload(legacy, payload)
    restored = V2HybridPolicyModel(input_dim=np.int64(4), seed=881)

    result = restored.load_weight_blob(legacy)

    assert result["model_state_restored"] is True
    assert result["confidence_calibration_reason"] == (
        "LEGACY_CHECKPOINT_CALIBRATION_STATE_MISSING"
        if restored.torch_available
        else "CPU_FALLBACK_HAS_NO_PROFITABILITY_CONFIDENCE_HEAD"
    )


def test_ordinary_private_copy_requires_neither_memfd_nor_procfs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "ordinary-artifact.bin"
    source.write_bytes(b"portable-ordinary-checkpoint")
    monkeypatch.delattr(checkpoint_module.os, "memfd_create", raising=False)

    with _private_checkpoint_copy(source) as snapshot:
        assert snapshot.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
        snapshot.stream.seek(0)
        assert snapshot.stream.read() == source.read_bytes()


def test_duplicate_npz_member_is_rejected_before_direct_model_mutation(
    tmp_path: Path,
) -> None:
    source_model = _production_model(887)
    source = tmp_path / "source.weights.npz"
    duplicate = tmp_path / "duplicate.weights.npz"
    source_model.save_weight_blob(source)
    forged_binding = deepcopy(deployed_checkpoint_feature_abi_binding_v4())
    forged_binding["ordered_feature_names_sha256"] = "0" * 64
    forged_json = json.dumps(
        forged_binding,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    encoded = io.BytesIO()
    np.save(encoded, np.array([forged_json]))
    with (
        zipfile.ZipFile(source, "r") as original,
        zipfile.ZipFile(
            duplicate,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as attacked,
    ):
        attacked.writestr(f"{_ABI_NPZ_KEY}.npy", encoded.getvalue())
        for info in original.infolist():
            attacked.writestr(info, original.read(info.filename))

    target = _distinct_production_target(887)
    before = _model_state(target)
    with duplicate.open("rb") as stream, pytest.raises(ValueError, match="duplicate"):
            checkpoint_module._safe_npz_semantics(
                stream,
                model_id=source_model.model_id,
                checkpoint_feature_abi_binding=(
                    deployed_checkpoint_feature_abi_binding_v4()
                ),
            )
    with pytest.raises(ValueError, match="duplicate"):
        target.load_weight_blob(duplicate)
    assert _model_state(target) == before


@pytest.mark.parametrize(
    ("constant_name", "value", "reason"),
    [
        ("MAX_V4_NPZ_MEMBER_COUNT", 1, "member_count"),
        ("MAX_V4_NPZ_MEMBER_UNCOMPRESSED_BYTES", 1, "member_size"),
        ("MAX_V4_NPZ_AGGREGATE_UNCOMPRESSED_BYTES", 1, "aggregate_size"),
        ("MAX_V4_NPZ_COMPRESSION_RATIO", 1, "compression_ratio"),
    ],
)
def test_declared_v4_archive_bounds_reject_before_numpy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    constant_name: str,
    value: int,
    reason: str,
) -> None:
    source = tmp_path / f"bounded-{constant_name}.weights.npz"
    _production_model(899).save_weight_blob(source)
    monkeypatch.setattr(model_module, constant_name, value)

    _assert_v4_preflight_rejects_before_numpy(
        source,
        reason=reason,
        monkeypatch=monkeypatch,
    )


def test_declared_v4_rejects_unsupported_compression_before_numpy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attacked = tmp_path / "bzip2.weights.npz"
    _write_single_member_npz(
        attacked,
        member=_raw_npy(descr="<f8", shape=(1,), payload=b"\0" * 8),
        compression=zipfile.ZIP_BZIP2,
    )

    _assert_v4_preflight_rejects_before_numpy(
        attacked,
        reason="member_flags",
        monkeypatch=monkeypatch,
    )


def test_declared_v4_rejects_encrypted_flag_before_numpy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attacked = tmp_path / "encrypted-flag.weights.npz"
    _write_single_member_npz(
        attacked,
        member=_raw_npy(descr="<f8", shape=(1,), payload=b"\0" * 8),
    )
    raw = bytearray(attacked.read_bytes())
    local = raw.index(b"PK\x03\x04")
    central = raw.index(b"PK\x01\x02")
    struct.pack_into("<H", raw, local + 6, struct.unpack_from("<H", raw, local + 6)[0] | 1)
    struct.pack_into(
        "<H",
        raw,
        central + 8,
        struct.unpack_from("<H", raw, central + 8)[0] | 1,
    )
    attacked.write_bytes(raw)

    _assert_v4_preflight_rejects_before_numpy(
        attacked,
        reason="member_flags",
        monkeypatch=monkeypatch,
    )


@pytest.mark.parametrize(
    ("member", "reason"),
    [
        (_raw_npy(descr="|O8", shape=(1,), payload=b"\0" * 8), "dtype_invalid"),
        (
            _raw_npy(
                descr="<f8",
                shape=(model_module.MAX_V4_NPZ_MEMBER_UNCOMPRESSED_BYTES,),
            ),
            "shape_allocation_bound",
        ),
    ],
)
def test_declared_v4_rejects_npy_dtype_or_shape_before_numpy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member: bytes,
    reason: str,
) -> None:
    attacked = tmp_path / f"{reason}.weights.npz"
    _write_single_member_npz(attacked, member=member)

    _assert_v4_preflight_rejects_before_numpy(
        attacked,
        reason=reason,
        monkeypatch=monkeypatch,
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing", "metadata_missing:__input_dim"),
        ("shape", "metadata_scalar_int64_invalid:__input_dim"),
        ("float", "metadata_scalar_int64_invalid:__input_dim"),
    ],
)
def test_malformed_input_dim_metadata_fails_before_direct_mutation(
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    source_model = _production_model(907)
    source = tmp_path / "source.weights.npz"
    attacked = tmp_path / f"{mutation}.weights.npz"
    source_model.save_weight_blob(source)
    payload = _payload(source)
    if mutation == "missing":
        payload.pop("__input_dim")
    elif mutation == "shape":
        payload["__input_dim"] = np.array([1784, 4], dtype=np.int64)
    else:
        payload["__input_dim"] = np.array([1784.9], dtype=np.float64)
    _write_payload(attacked, payload)
    target = _distinct_production_target(907)
    before = _model_state(target)

    with pytest.raises(ValueError, match=reason):
        target.load_weight_blob(attacked)
    assert _model_state(target) == before


@pytest.mark.parametrize(
    "attack",
    [
        "mixed_family",
        "extra_tensor",
        "extra_metadata",
        "wrong_dtype",
        "wrong_shape",
    ],
)
def test_adversarial_tensor_archives_fail_before_direct_mutation(
    tmp_path: Path,
    attack: str,
) -> None:
    source_model = _production_model(911)
    source = tmp_path / "source.weights.npz"
    attacked = tmp_path / f"{attack}.weights.npz"
    source_model.save_weight_blob(source)
    payload = _payload(source)
    torch_key = next(key for key in payload if key.startswith("torch::"))
    if attack == "mixed_family":
        payload["fallback::weights"] = np.zeros(
            len(source_model._fallback_weights),
            dtype=np.float64,
        )
    elif attack == "extra_tensor":
        payload["torch::attacker.extra"] = np.zeros((1,), dtype=np.float32)
    elif attack == "extra_metadata":
        payload["__attacker_metadata"] = np.array(["forbidden"])
    elif attack == "wrong_dtype":
        payload[torch_key] = payload[torch_key].astype(np.float64)
    else:
        shaped_key = next(
            key for key, value in payload.items() if key.startswith("torch::") and value.ndim > 1
        )
        payload[shaped_key] = payload[shaped_key].reshape(-1)
    _write_payload(attacked, payload)
    target = _distinct_production_target(911)
    before = _model_state(target)

    with pytest.raises(ValueError):
        target.load_weight_blob(attacked)
    assert _model_state(target) == before


def test_manager_rejects_mixed_parameter_families_without_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".local_models" / "mixed-manager"
    source_model = _production_model(919)
    manager = V2HybridCheckpointManager(root)
    manifest = manager.write_checkpoint(
        model=source_model,
        input_dim=source_model.input_dim,
        device=source_model.device,
        cuda_active=source_model.cuda_active,
    )
    weight_path = root / f"{manifest.checkpoint_id}.weights.npz"
    payload = _payload(weight_path)
    payload["fallback::weights"] = np.zeros(
        len(source_model._fallback_weights),
        dtype=np.float64,
    )
    _write_payload(weight_path, payload)
    _retarget_manifest_weight(
        root / f"{manifest.checkpoint_id}.json",
        weight_path,
    )
    target = _distinct_production_target(919)
    target._torch = None
    target._net = None
    before = _model_state(target)

    result = manager.load_latest_weights(target)

    assert result["model_state_restored"] is False
    assert "SAFE_NPZ_SEMANTIC_VERIFICATION_FAILED" in result["load_status"]
    assert _model_state(target) == before


@pytest.mark.parametrize("attack", ["missing_input", "extra_tensor", "wrong_dtype"])
def test_manager_rejects_malformed_or_unexpected_archive_before_mutation(
    tmp_path: Path,
    attack: str,
) -> None:
    root = tmp_path / ".local_models" / f"manager-{attack}"
    source_model = _production_model(923)
    manager = V2HybridCheckpointManager(root)
    manifest = manager.write_checkpoint(
        model=source_model,
        input_dim=source_model.input_dim,
        device=source_model.device,
        cuda_active=source_model.cuda_active,
    )
    weight_path = root / f"{manifest.checkpoint_id}.weights.npz"
    payload = _payload(weight_path)
    torch_key = next(key for key in payload if key.startswith("torch::"))
    if attack == "missing_input":
        payload.pop("__input_dim")
    elif attack == "extra_tensor":
        payload["torch::attacker.extra"] = np.zeros((1,), dtype=np.float32)
    else:
        payload[torch_key] = payload[torch_key].astype(np.float64)
    _write_payload(weight_path, payload)
    _retarget_manifest_weight(
        root / f"{manifest.checkpoint_id}.json",
        weight_path,
    )
    target = _distinct_production_target(923)
    before = _model_state(target)

    result = manager.load_latest_weights(target)

    assert result["model_state_restored"] is False
    assert result["load_status"] in {
        "CHECKPOINT_MANIFEST_SCAN_INVALID",
        "CHECKPOINT_CONTENT_IDENTITY_MISMATCH",
        "SAFE_NPZ_SEMANTIC_VERIFICATION_FAILED:ValueError",
    }
    assert _model_state(target) == before


def test_private_checkpoint_snapshot_is_sealed_and_read_only(
    tmp_path: Path,
) -> None:
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"immutable-checkpoint-bytes")

    with _private_checkpoint_copy(source, require_sealed=True) as snapshot:
        descriptor = snapshot.stream.fileno()
        assert fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
        with pytest.raises(OSError):
            os.pwrite(descriptor, b"X", 0)
        assert snapshot.sha256 == hashlib.sha256(b"immutable-checkpoint-bytes").hexdigest()
        snapshot.stream.seek(0)
        assert snapshot.stream.read() == b"immutable-checkpoint-bytes"


def test_private_checkpoint_snapshot_rejects_oversize_before_memfd_allocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "oversize-artifact.bin"
    source.write_bytes(b"123456789")
    monkeypatch.setattr(checkpoint_module, "MAX_PRIVATE_CHECKPOINT_COPY_BYTES", 8)
    memfd_called = False

    def unexpected_memfd(*_args: object, **_kwargs: object) -> int:
        nonlocal memfd_called
        memfd_called = True
        raise AssertionError("memfd allocation must not precede the size gate")

    monkeypatch.setattr(checkpoint_module.os, "memfd_create", unexpected_memfd)

    with pytest.raises(OSError, match="size_limit_exceeded"):
        with _private_checkpoint_copy(source, require_sealed=True):
            pass

    assert memfd_called is False


def test_checkpoint_manifest_rejects_nested_duplicate_binding_key(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".local_models" / "duplicate-manifest-key"
    model = _production_model(929)
    manager = V2HybridCheckpointManager(root)
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
    )
    manifest_path = root / f"{manifest.checkpoint_id}.json"
    text = manifest_path.read_text(encoding="utf-8")
    text = text.replace(
        '"audit_only": true,',
        '"audit_only": false,\n      "audit_only": true,',
        1,
    )
    manifest_path.write_text(text, encoding="utf-8")

    result = manager.load_latest_weights(_production_model(929))

    assert result["load_status"] == "CHECKPOINT_MANIFEST_SCAN_INVALID"
    assert any(
        "duplicate_json_key:audit_only" in error["reason"]
        for error in result["manifest_scan_errors"]
    )


def test_manifest_binding_requires_exact_declared_model_contract(
    tmp_path: Path,
) -> None:
    production_root = tmp_path / ".local_models" / "binding-string"
    production = _production_model(937)
    production._confidence_calibration_state = {
        "fitted": True,
        "reason": "RAW_PREWRITE_STATE_MUST_ROLL_BACK_BYTE_EXACTLY",
    }
    production_before = _model_state(production)
    with pytest.raises(ValueError, match="not_exact_dict"):
        V2HybridCheckpointManager(production_root).write_checkpoint(
            model=production,
            input_dim=production.input_dim,
            device=production.device,
            cuda_active=production.cuda_active,
            checkpoint_evidence={
                _ABI_EVIDENCE_KEY: (canonical_deployed_checkpoint_feature_abi_binding_v4_json())
            },
        )
    assert _model_state(production) == production_before
    nonproduction_root = tmp_path / ".local_models" / "nonproduction-null"
    nonproduction = V2HybridPolicyModel(input_dim=4, seed=941)
    with pytest.raises(ValueError, match="declaration_missing"):
        V2HybridCheckpointManager(nonproduction_root).write_checkpoint(
            model=nonproduction,
            input_dim=nonproduction.input_dim,
            device=nonproduction.device,
            cuda_active=nonproduction.cuda_active,
            checkpoint_evidence={_ABI_EVIDENCE_KEY: None},
        )

    assert not production_root.exists()
    assert not nonproduction_root.exists()


@pytest.mark.parametrize("input_dim", ["4", 4.0, np.int64(4)])
def test_ordinary_manifest_preserves_int_convertible_input_dim(
    tmp_path: Path,
    input_dim: object,
) -> None:
    root = tmp_path / ".local_models" / f"legacy-{type(input_dim).__name__}"
    manifest = V2HybridCheckpointManager(root).write_manifest(
        model_id="test-model",
        input_dim=input_dim,  # type: ignore[arg-type]
        device="cpu",
        cuda_active=False,
    )
    assert manifest.input_dim == 4


@pytest.mark.parametrize(
    "input_dim",
    [True, "1784", 1784.0, np.int64(1784), 0, -1],
)
def test_declared_manifest_requires_exact_builtin_input_dim(
    tmp_path: Path,
    input_dim: object,
) -> None:
    root = tmp_path / ".local_models" / f"declared-{type(input_dim).__name__}"
    with pytest.raises(ValueError):
        V2HybridCheckpointManager(root).write_manifest(
            model_id="test-model",
            input_dim=input_dim,  # type: ignore[arg-type]
            device="cpu",
            cuda_active=False,
            checkpoint_feature_abi_declaration=(
                deployed_checkpoint_feature_abi_binding_v4()
            ),
        )


def test_declared_cpu_fallback_preserves_audit_only_feature_layout(
    tmp_path: Path,
) -> None:
    model = _production_model(947)
    model._torch = None
    model._net = None
    weight_path = tmp_path / "declared-fallback.weights.npz"

    model.save_weight_blob(weight_path)
    with np.load(weight_path, allow_pickle=False) as archive:
        assert str(archive[_ABI_NPZ_KEY][0]) == (
            canonical_deployed_checkpoint_feature_abi_binding_v4_json()
        )

    restored = _production_model(947)
    restored._torch = None
    restored._net = None
    load_result = restored.load_weight_blob(weight_path)

    result = restored.forward(
        [0.0] * CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM
    )

    assert load_result["model_state_restored"] is True
    assert restored._fallback_weights == model._fallback_weights
    assert result.model_id == restored.model_id


def test_weight_save_failure_rolls_calibration_back_byte_exactly(
    tmp_path: Path,
) -> None:
    model = _production_model(953)
    model._confidence_calibration_state = {
        "fitted": True,
        "reason": "RAW_PRESAVE_STATE_MUST_ROLL_BACK_BYTE_EXACTLY",
    }
    before = _model_state(model)
    parent_is_file = tmp_path / "not-a-directory"
    parent_is_file.write_text("block", encoding="utf-8")

    with pytest.raises(OSError):
        model.save_weight_blob(parent_is_file / "forbidden.weights.npz")

    assert _model_state(model) == before


def test_direct_load_mutation_exception_rolls_parameters_and_calibration_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _production_model(967)
    weight_path = tmp_path / "source.weights.npz"
    source.save_weight_blob(weight_path)
    target = _distinct_production_target(967)
    target._confidence_calibration_state = {
        "fitted": False,
        "reason": "DIRECT_LOAD_ROLLBACK_SENTINEL",
    }
    assert target.net is not None
    assert target.torch is not None
    target.net.train(True)
    original_load = target.net.load_state_dict
    call_count = 0

    def fail_once(state: dict[str, Any], *, strict: bool = True) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            with target.torch.no_grad():
                next(iter(target.net.parameters())).view(-1)[0].add_(1.0)
            raise RuntimeError("injected_load_failure_after_partial_mutation")
        return original_load(state, strict=strict)

    monkeypatch.setattr(target.net, "load_state_dict", fail_once)
    before = _model_state(target)

    with pytest.raises(RuntimeError, match="injected_load_failure"):
        target.load_weight_blob(weight_path)

    assert call_count == 2
    assert _model_state(target) == before
    assert target.net.training is True
