"""Safe local checkpoint manifest handling for V2 hybrid trainer."""
from __future__ import annotations

import fcntl
import hashlib
import importlib
import json
import os
import struct
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from .confidence import CONFIDENCE_HEAD_ACTIONS, CONFIDENCE_HEAD_SCHEMA_VERSION
from .config import ACTION_COUNT, CHECKPOINT_SOURCE, LIVE_GATE_BLOCKED
from .model import (
    ConfidenceHeadCheckpointIncompatibleError,
    V2HybridPolicyModel,
    _strict_npz_json,
    _strict_npz_member_keys,
    _strict_npz_scalar_int64,
    _strict_npz_scalar_text,
)

CHECKPOINT_EVIDENCE_SCHEMA_VERSION = "v2_hybrid_checkpoint_evidence_v1"
CHECKPOINT_CAUSAL_ORDER_SCHEMA_VERSION = "v2_hybrid_checkpoint_causal_order_v1"
_CHECKPOINT_CAUSAL_LEDGER_NAME = ".checkpoint-causal-order.jsonl"
_CHECKPOINT_CAUSAL_LOCK_NAME = ".checkpoint-causal-order.lock"
_CHECKPOINT_CAUSAL_GENESIS_DIGEST = "0" * 64
_CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD = "checkpoint_feature_abi_binding_v4"
# Immutable process-integrity bound for the anonymous in-memory checkpoint
# snapshot. The current deployed model serializes far below this envelope; a
# larger artifact must be rejected before memfd allocation instead of allowing
# an untrusted manifest/path to consume unbounded RAM. This is not a market,
# strategy, trainer-admission, or risk threshold.
MAX_PRIVATE_CHECKPOINT_COPY_BYTES = 512 * 1024 * 1024
_CHECKPOINT_STORE_SUBDIRECTORIES = frozenset(
    {"non_serving_training_candidates", "rejected_optimizer_attempts"}
)
_CAUSAL_EVIDENCE_FIELDS = frozenset(
    {
        "checkpoint_causal_order_schema_version",
        "checkpoint_causal_store",
        "checkpoint_generation",
        "parent_checkpoint_generation",
        "checkpoint_semantic_digest",
        "checkpoint_causal_record_digest",
    }
)


def _checkpoint_feature_abi_v4_module() -> Any:
    """Import registry-bound v4 code only for an explicit declaration."""

    return importlib.import_module(
        "v2.backend.app.services.native_trainer.checkpoint_feature_abi_binding_v4"
    )


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _strict_generated_utc(
    value: Any,
    *,
    allow_future_after_clock_rollback: bool = False,
) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("checkpoint_generated_utc_missing")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("checkpoint_generated_utc_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("checkpoint_generated_utc_naive")
    generated = parsed.astimezone(UTC)
    if not allow_future_after_clock_rollback and generated > datetime.now(UTC):
        raise ValueError("checkpoint_generated_utc_in_future")
    return generated


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            tmp_path = Path(handle.name)
        tmp_path.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()


@dataclass(frozen=True)
class _PrivateCheckpointCopy:
    """One private artifact copy shared by every load-time verifier."""

    stream: BinaryIO = field(repr=False, compare=False)
    sha256: str
    size_bytes: int


def _sha256_private_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    stream.seek(0)
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    stream.seek(0)
    return digest.hexdigest()


@contextmanager
def _private_checkpoint_copy(
    path: Path,
    *,
    require_sealed: bool = False,
) -> Iterator[_PrivateCheckpointCopy]:
    """Copy a mutable checkpoint path once into a private anonymous stream.

    The source handle is opened and consumed exactly once.  Hashing, safe NPZ
    inspection, and model restoration then share the anonymous temporary file,
    so replacing the source path cannot change the bytes admitted to the model.
    """
    if not require_sealed:
        # Preserve the pre-v4 portable TemporaryFile behavior for every
        # undeclared checkpoint. It requires neither memfd nor /procfs.
        with tempfile.TemporaryFile(mode="w+b") as private_stream:
            size_bytes = 0
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    private_stream.write(chunk)
                    size_bytes += len(chunk)
            private_stream.flush()
            private_stream.seek(0)
            with os.fdopen(os.dup(private_stream.fileno()), "rb") as read_stream:
                observed_sha256 = _sha256_private_stream(read_stream)
                yield _PrivateCheckpointCopy(
                    stream=read_stream,
                    sha256=observed_sha256,
                    size_bytes=size_bytes,
                )
        return
    try:
        initial_size_bytes = path.stat().st_size
    except OSError as exc:
        raise OSError("checkpoint_private_copy_source_stat_failed") from exc
    if initial_size_bytes > MAX_PRIVATE_CHECKPOINT_COPY_BYTES:
        raise OSError("checkpoint_private_copy_size_limit_exceeded")
    required_os_flags = ("MFD_ALLOW_SEALING", "MFD_CLOEXEC")
    required_seals = (
        "F_ADD_SEALS",
        "F_GET_SEALS",
        "F_SEAL_GROW",
        "F_SEAL_SEAL",
        "F_SEAL_SHRINK",
        "F_SEAL_WRITE",
    )
    if (
        not hasattr(os, "memfd_create")
        or any(not hasattr(os, name) for name in required_os_flags)
        or any(not hasattr(fcntl, name) for name in required_seals)
    ):
        raise OSError("sealed_private_checkpoint_copy_unavailable")
    write_fd = os.memfd_create(
        "v2-checkpoint-private",
        flags=os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING,
    )
    read_fd: int | None = None
    try:
        size_bytes = 0
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                if size_bytes + len(chunk) > MAX_PRIVATE_CHECKPOINT_COPY_BYTES:
                    raise OSError("checkpoint_private_copy_size_limit_exceeded")
                view = memoryview(chunk)
                while view:
                    written = os.write(write_fd, view)
                    if written <= 0:
                        raise OSError("sealed_private_checkpoint_copy_short_write")
                    view = view[written:]
                size_bytes += len(chunk)
        os.fsync(write_fd)
        seals = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
        fcntl.fcntl(write_fd, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(write_fd, fcntl.F_GET_SEALS) != seals:
            raise OSError("sealed_private_checkpoint_copy_seal_mismatch")
        os.lseek(write_fd, 0, os.SEEK_SET)
        read_fd = os.open(
            f"/proc/self/fd/{write_fd}",
            os.O_RDONLY | os.O_CLOEXEC,
        )
        os.close(write_fd)
        write_fd = -1
        if fcntl.fcntl(read_fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY:
            raise OSError("sealed_private_checkpoint_copy_not_read_only")
        with os.fdopen(read_fd, "rb") as read_only_stream:
            read_fd = None
            observed_sha256 = _sha256_private_stream(read_only_stream)
            yield _PrivateCheckpointCopy(
                stream=read_only_stream,
                sha256=observed_sha256,
                size_bytes=size_bytes,
            )
    finally:
        if read_fd is not None:
            os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"noncanonical_json_constant:{value}")


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError(f"duplicate_json_key:{key}")
        parsed[key] = value
    return parsed


def _strict_json_loads(value: str) -> Any:
    legacy = json.loads(value, parse_constant=_reject_json_constant)
    evidence = (
        legacy.get("checkpoint_evidence") if isinstance(legacy, dict) else None
    )
    if not (
        isinstance(evidence, dict)
        and _CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD in evidence
    ):
        return legacy
    return json.loads(
        value,
        object_pairs_hook=_reject_duplicate_json_pairs,
        parse_constant=_reject_json_constant,
    )


def _legacy_safe_npz_semantics(
    source: BinaryIO,
    *,
    model_id: str,
) -> dict[str, Any]:
    """Preserve pre-v4 undeclared NPZ inspection semantics exactly."""

    np = importlib.import_module("numpy")
    digest = hashlib.sha256()
    digest.update(b"v2_in_memory_served_policy_parameters_v1\0")
    digest.update(str(model_id).encode("utf-8"))
    digest.update(b"\0")
    source.seek(0)
    with np.load(source, allow_pickle=False) as data:
        format_values = data.get("__format_version")
        input_dim_values = data.get("__input_dim")
        head_schema_values = data.get("__confidence_head_schema_version")
        head_actions_values = data.get("__confidence_head_actions_json")
        calibration_values = data.get("__confidence_calibration_state_json")
        if (
            format_values is None
            or str(format_values[0]) != "v2_hybrid_policy_npz_v2"
            or input_dim_values is None
            or head_schema_values is None
            or head_actions_values is None
            or calibration_values is None
        ):
            raise ValueError("checkpoint_npz_semantic_metadata_missing")
        head_actions = tuple(
            json.loads(
                str(head_actions_values[0]),
                parse_constant=_reject_json_constant,
            )
        )
        calibration_state = json.loads(
            str(calibration_values[0]),
            parse_constant=_reject_json_constant,
        )
        if not isinstance(calibration_state, dict):
            raise ValueError("checkpoint_npz_calibration_state_not_object")
        torch_keys = sorted(
            str(key) for key in data.files if str(key).startswith("torch::")
        )
        fallback = data.get("fallback::weights")
        if torch_keys:
            for key in torch_keys:
                name = key.removeprefix("torch::")
                array = np.ascontiguousarray(data[key])
                if not bool(np.isfinite(array).all()):
                    raise ValueError("checkpoint_npz_parameter_nonfinite")
                digest.update(name.encode("utf-8"))
                digest.update(b"\0")
                digest.update(str(array.dtype).encode("ascii"))
                digest.update(b"\0")
                digest.update(
                    json.dumps(
                        list(array.shape),
                        separators=(",", ":"),
                    ).encode("ascii")
                )
                digest.update(b"\0")
                digest.update(memoryview(array).cast("B"))
        elif fallback is not None:
            values = np.asarray(fallback, dtype=np.float64).reshape(-1)
            if not bool(np.isfinite(values).all()) or values.size <= 0:
                raise ValueError("checkpoint_npz_fallback_parameters_invalid")
            for value in values.tolist():
                digest.update(struct.pack("!d", float(value)))
        else:
            raise ValueError("checkpoint_npz_parameter_payload_missing")
        return {
            "input_dim": int(input_dim_values[0]),
            "confidence_head_schema_version": str(head_schema_values[0]),
            "confidence_head_actions": head_actions,
            "confidence_calibration_state": calibration_state,
            "model_parameter_fingerprint": digest.hexdigest(),
        }


def _safe_npz_semantics(
    source: BinaryIO,
    *,
    model_id: str,
    model: V2HybridPolicyModel | None = None,
    checkpoint_feature_abi_binding: object | None = None,
) -> dict[str, Any]:
    """Read safe NPZ semantics without constructing or mutating a model."""
    if checkpoint_feature_abi_binding is None:
        return _legacy_safe_npz_semantics(source, model_id=model_id)

    binding_module = _checkpoint_feature_abi_v4_module()
    binding_module.verify_deployed_checkpoint_feature_abi_binding_v4(
        checkpoint_feature_abi_binding,
        checkpoint_input_dim=(
            model.input_dim
            if model is not None
            else binding_module.CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM
        ),
    )
    # The strict ZIP and NPY-header preflight runs before NumPy is imported.
    member_keys = frozenset(_strict_npz_member_keys(source))
    np = importlib.import_module("numpy")
    digest = hashlib.sha256()
    digest.update(b"v2_in_memory_served_policy_parameters_v1\0")
    digest.update(str(model_id).encode("utf-8"))
    digest.update(b"\0")
    if hasattr(source, "seek"):
        source.seek(0)
    if not hasattr(source, "read") or not hasattr(source, "seek"):
        raise ValueError("checkpoint_npz_seekable_stream_required")
    with np.load(source, allow_pickle=False) as data:
        format_version = _strict_npz_scalar_text(data, "__format_version")
        input_dim = _strict_npz_scalar_int64(data, "__input_dim")
        _strict_npz_scalar_int64(data, "__seed")
        torch_available = _strict_npz_scalar_int64(
            data,
            "__torch_available",
        )
        head_schema = _strict_npz_scalar_text(
            data,
            "__confidence_head_schema_version",
        )
        head_actions_json = _strict_npz_scalar_text(
            data,
            "__confidence_head_actions_json",
        )
        calibration_json = _strict_npz_scalar_text(
            data,
            "__confidence_calibration_state_json",
        )
        if format_version != "v2_hybrid_policy_npz_v2":
            raise ValueError("checkpoint_npz_format_version_invalid")
        if type(input_dim) is not int or input_dim <= 0:
            raise ValueError("checkpoint_npz_input_dim_invalid")
        if torch_available not in (0, 1):
            raise ValueError("checkpoint_npz_torch_available_invalid")
        expected_metadata = {
            "__format_version",
            "__input_dim",
            "__seed",
            "__torch_available",
            "__confidence_head_schema_version",
            "__confidence_head_actions_json",
            "__confidence_calibration_state_json",
        }
        feature_abi_binding_json: str | None = None
        feature_abi_binding_sha256: str | None = None
        if "__checkpoint_feature_abi_binding_v4_json" in member_keys:
            expected_metadata.add("__checkpoint_feature_abi_binding_v4_json")
            feature_abi_binding_json = _strict_npz_scalar_text(
                data,
                "__checkpoint_feature_abi_binding_v4_json",
            )
            verification = binding_module.verify_deployed_checkpoint_feature_abi_binding_v4(
                feature_abi_binding_json,
                checkpoint_input_dim=input_dim,
            )
            feature_abi_binding_sha256 = str(verification["binding_sha256"])
            if (
                feature_abi_binding_sha256
                != binding_module.CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256
            ):
                raise ValueError("checkpoint_npz_feature_abi_binding_mismatch")
        head_actions_raw = _strict_npz_json(head_actions_json)
        if type(head_actions_raw) is not list:
            raise ValueError("checkpoint_npz_head_actions_not_array")
        head_actions = tuple(head_actions_raw)
        calibration_state = _strict_npz_json(calibration_json)
        if type(calibration_state) is not dict:
            raise ValueError("checkpoint_npz_calibration_state_not_object")
        torch_keys = tuple(
            sorted(key for key in member_keys if key.startswith("torch::"))
        )
        fallback_present = "fallback::weights" in member_keys
        if bool(torch_keys) == fallback_present:
            raise ValueError("checkpoint_npz_parameter_family_ambiguous")
        if torch_keys:
            if torch_available != 1:
                raise ValueError("checkpoint_npz_torch_family_metadata_mismatch")
            expected_state: dict[str, Any] | None = None
            if model is not None:
                if model.model_id != model_id:
                    raise ValueError("checkpoint_npz_model_id_argument_mismatch")
                if model.torch is None or model.net is None:
                    raise ValueError("checkpoint_npz_torch_family_target_mismatch")
                expected_state = dict(model.net.state_dict())
                expected_torch_keys = frozenset(
                    f"torch::{name}" for name in expected_state
                )
                if frozenset(torch_keys) != expected_torch_keys:
                    raise ValueError("checkpoint_npz_torch_key_set_mismatch")
            if member_keys != frozenset(expected_metadata) | frozenset(torch_keys):
                raise ValueError("checkpoint_npz_unexpected_keys")
            for key in torch_keys:
                name = key.removeprefix("torch::")
                array = data[key]
                if expected_state is not None:
                    existing = expected_state[name]
                    expected_shape = tuple(existing.shape)
                    expected_dtype = str(
                        existing.detach().cpu().numpy().dtype
                    )
                else:
                    expected_shape = tuple(array.shape)
                    expected_dtype = "float32"
                if (
                    not expected_shape
                    or tuple(array.shape) != expected_shape
                    or str(array.dtype) != expected_dtype
                ):
                    raise ValueError(
                        "checkpoint_npz_parameter_shape_or_dtype_invalid"
                    )
                if not bool(np.isfinite(array).all()):
                    raise ValueError("checkpoint_npz_parameter_nonfinite")
                array = np.ascontiguousarray(array)
                digest.update(name.encode("utf-8"))
                digest.update(b"\0")
                digest.update(str(array.dtype).encode("ascii"))
                digest.update(b"\0")
                digest.update(
                    json.dumps(list(array.shape), separators=(",", ":")).encode(
                        "ascii"
                    )
                )
                digest.update(b"\0")
                digest.update(memoryview(array).cast("B"))
        else:
            if torch_available != 0:
                raise ValueError("checkpoint_npz_fallback_family_metadata_mismatch")
            if member_keys != frozenset(expected_metadata) | {"fallback::weights"}:
                raise ValueError("checkpoint_npz_unexpected_keys")
            values = data["fallback::weights"]
            if (
                tuple(values.shape) != (input_dim * ACTION_COUNT,)
                or str(values.dtype) != "float64"
                or not bool(np.isfinite(values).all())
            ):
                raise ValueError("checkpoint_npz_fallback_parameters_invalid")
            for value in values.tolist():
                digest.update(struct.pack("!d", float(value)))
        return {
            "input_dim": input_dim,
            "checkpoint_feature_abi_binding_json": feature_abi_binding_json,
            "checkpoint_feature_abi_binding_sha256": (
                feature_abi_binding_sha256
            ),
            "confidence_head_schema_version": head_schema,
            "confidence_head_actions": head_actions,
            "confidence_calibration_state": calibration_state,
            "model_parameter_fingerprint": digest.hexdigest(),
        }


def _canonical_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _manifest_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name}_not_integer")
    parsed = int(value)
    if float(value) != float(parsed):
        raise ValueError(f"{field_name}_not_integer")
    return parsed


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )


def _verify_checkpoint_feature_abi_evidence(
    *,
    input_dim: int,
    evidence: dict[str, Any],
) -> None:
    if _CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD in evidence:
        binding_module = _checkpoint_feature_abi_v4_module()
        supplied = evidence[_CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD]
        if type(supplied) is not dict:
            raise ValueError("checkpoint_feature_abi_binding_not_exact_dict")
        binding_module.verify_deployed_checkpoint_feature_abi_binding_v4(
            supplied,
            checkpoint_input_dim=input_dim,
        )


def _bind_checkpoint_feature_abi_evidence(
    *,
    input_dim: int,
    evidence: dict[str, Any],
    feature_abi_declaration: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Bind an optional model declaration without granting tensor authority."""

    bound = dict(evidence)
    if feature_abi_declaration is not None:
        binding_module = _checkpoint_feature_abi_v4_module()
        if type(feature_abi_declaration) is not dict:
            raise ValueError("checkpoint_feature_abi_declaration_not_exact_dict")
        binding_module.verify_deployed_checkpoint_feature_abi_binding_v4(
            feature_abi_declaration,
            checkpoint_input_dim=input_dim,
        )
        supplied_present = _CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD in bound
        supplied = bound.get(_CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD)
        if supplied_present:
            if type(supplied) is not dict:
                raise ValueError("checkpoint_feature_abi_binding_not_exact_dict")
            binding_module.verify_deployed_checkpoint_feature_abi_binding_v4(
                supplied,
                checkpoint_input_dim=input_dim,
            )
        expected = binding_module.deployed_checkpoint_feature_abi_binding_v4()
        if feature_abi_declaration != expected:
            raise ValueError("checkpoint_feature_abi_declaration_mismatch")
        if supplied_present and supplied != expected:
            raise ValueError("checkpoint_feature_abi_binding_mismatch")
        bound[_CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD] = expected
    elif _CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD in bound:
        raise ValueError("checkpoint_feature_abi_declaration_missing")
    _verify_checkpoint_feature_abi_evidence(
        input_dim=input_dim,
        evidence=bound,
    )
    return bound


def _checkpoint_feature_abi_matches_npz(
    *,
    input_dim: int,
    evidence: dict[str, Any],
    safe_semantics: dict[str, Any],
) -> bool:
    try:
        _verify_checkpoint_feature_abi_evidence(
            input_dim=input_dim,
            evidence=evidence,
        )
    except ValueError:
        return False
    declared = evidence.get(_CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD)
    if declared is None:
        return (
            safe_semantics.get("checkpoint_feature_abi_binding_json") is None
            and safe_semantics.get("checkpoint_feature_abi_binding_sha256") is None
        )
    binding_module = _checkpoint_feature_abi_v4_module()
    return (
        safe_semantics.get("checkpoint_feature_abi_binding_json")
        == binding_module.canonical_deployed_checkpoint_feature_abi_binding_v4_json()
        and safe_semantics.get("checkpoint_feature_abi_binding_sha256")
        == binding_module.CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256
        and evidence.get(_CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD)
        == binding_module.deployed_checkpoint_feature_abi_binding_v4()
    )


def _base_checkpoint_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        field_name: value
        for field_name, value in evidence.items()
        if field_name not in _CAUSAL_EVIDENCE_FIELDS
    }


def _checkpoint_semantic_digest(
    *,
    model_id: str,
    input_dim: int,
    checkpoint_causal_store: str,
    confidence_calibration_state: dict[str, Any],
    model_parameter_fingerprint: str | None,
    lineage_kind: str,
    parent_checkpoint_id: str | None,
    parent_policy_fingerprint: str | None,
    consumed_ppo_update_keys: tuple[str, ...],
    training_partition_digest: str | None,
    checkpoint_evidence: dict[str, Any],
) -> str:
    """Hash stable checkpoint semantics before assigning causal generation.

    Wall-clock time, filesystem paths, and serialized-size metadata are excluded:
    none identifies a policy generation, and all can vary across an idempotent
    crash retry.  Model parameters, calibration, lineage, exact-PPO inputs, and
    role evidence are included and are independently bound to the NPZ artifact.
    """
    return _canonical_digest(
        {
            "schema_version": CHECKPOINT_CAUSAL_ORDER_SCHEMA_VERSION,
            "model_id": str(model_id),
            "input_dim": int(input_dim),
            "checkpoint_causal_store": checkpoint_causal_store,
            "confidence_calibration_state": dict(confidence_calibration_state),
            "model_parameter_fingerprint": model_parameter_fingerprint,
            "lineage_kind": str(lineage_kind),
            "parent_checkpoint_id": parent_checkpoint_id,
            "parent_policy_fingerprint": parent_policy_fingerprint,
            "consumed_ppo_update_keys": list(consumed_ppo_update_keys),
            "training_partition_digest": training_partition_digest,
            "checkpoint_evidence": _base_checkpoint_evidence(
                dict(checkpoint_evidence)
            ),
        }
    )


@dataclass(frozen=True)
class _CausalGenerationRecord:
    checkpoint_generation: int
    checkpoint_causal_store: str
    checkpoint_semantic_digest: str
    parent_checkpoint_id: str | None
    parent_checkpoint_generation: int | None
    generated_utc: str
    previous_record_digest: str
    checkpoint_causal_record_digest: str

    def payload_without_digest(self) -> dict[str, Any]:
        return {
            "schema_version": CHECKPOINT_CAUSAL_ORDER_SCHEMA_VERSION,
            "checkpoint_generation": self.checkpoint_generation,
            "checkpoint_causal_store": self.checkpoint_causal_store,
            "checkpoint_semantic_digest": self.checkpoint_semantic_digest,
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "parent_checkpoint_generation": self.parent_checkpoint_generation,
            "generated_utc": self.generated_utc,
            "previous_record_digest": self.previous_record_digest,
        }

    def payload(self) -> dict[str, Any]:
        return {
            **self.payload_without_digest(),
            "checkpoint_causal_record_digest": (
                self.checkpoint_causal_record_digest
            ),
        }


@dataclass(frozen=True)
class CheckpointManifest:
    checkpoint_id: str
    checkpoint_source: str
    path: str
    generated_utc: str
    model_id: str
    input_dim: int
    device: str
    cuda_active: bool
    weight_blob_written: bool
    weight_file_path: str | None = None
    weight_file_format: str | None = None
    weight_file_size_bytes: int | None = None
    confidence_calibration_fitted: bool = False
    confidence_calibration_temperature: float | None = None
    confidence_calibration_sample: int = 0
    confidence_calibration_reason: str | None = None
    confidence_calibration_fit_partition: str | None = None
    confidence_calibration_validation_rows_used: int = 0
    confidence_calibration_label_semantics: str | None = None
    confidence_head_schema_version: str | None = None
    confidence_head_actions: tuple[str, ...] = ()
    confidence_calibration_long_sample: int = 0
    confidence_calibration_short_sample: int = 0
    confidence_calibration_model_parameter_fingerprint: str | None = None
    confidence_calibration_row_digest: str | None = None
    confidence_calibration_state: dict[str, Any] = field(default_factory=dict)
    model_parameter_fingerprint: str | None = None
    weight_file_sha256: str | None = None
    lineage_kind: str = "SERVING_CANDIDATE"
    parent_checkpoint_id: str | None = None
    parent_policy_fingerprint: str | None = None
    consumed_ppo_update_keys: tuple[str, ...] = ()
    training_partition_digest: str | None = None
    checkpoint_evidence_schema_version: str | None = None
    checkpoint_evidence: dict[str, Any] = field(default_factory=dict)
    checkpoint_evidence_digest: str | None = None
    checkpoint_causal_order_schema_version: str | None = None
    checkpoint_causal_store: str | None = None
    checkpoint_generation: int = 0
    parent_checkpoint_generation: int | None = None
    checkpoint_semantic_digest: str | None = None
    checkpoint_causal_record_digest: str | None = None
    external_deserialization_used: bool = False


def _load_private_checkpoint_copy(
    *,
    source_path: Path,
    manifest: CheckpointManifest,
    model: V2HybridPolicyModel,
) -> dict[str, Any]:
    """Verify and restore one checkpoint from one private byte identity."""

    def failure(load_status: str, **evidence: Any) -> dict[str, Any]:
        return {
            "private_checkpoint_copy_verified": False,
            "latest_checkpoint_loadable": False,
            "model_state_restored": False,
            "load_status": load_status,
            **evidence,
        }

    try:
        model_feature_abi_declaration = model.checkpoint_feature_abi_declaration
    except Exception as exc:  # noqa: BLE001 - fail before reading artifact bytes
        return failure(
            "CHECKPOINT_FEATURE_ABI_DECLARATION_INVALID",
            checkpoint_feature_abi_binding_verified=False,
            load_error_reason=str(exc) or type(exc).__name__,
        )
    manifest_feature_abi_binding = manifest.checkpoint_evidence.get(
        _CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD
    )
    if model_feature_abi_declaration != manifest_feature_abi_binding:
        return failure(
            "CHECKPOINT_FEATURE_ABI_BINDING_MISMATCH",
            checkpoint_feature_abi_binding_verified=False,
        )

    try:
        with _private_checkpoint_copy(
            source_path,
            require_sealed=(model_feature_abi_declaration is not None),
        ) as snapshot:
            expected_sha256 = str(manifest.weight_file_sha256 or "")
            if not _is_sha256(expected_sha256):
                return failure(
                    "WEIGHT_BLOB_SHA256_MISSING",
                    weight_file_sha256_verified=False,
                )
            if snapshot.sha256 != expected_sha256:
                return failure(
                    "WEIGHT_BLOB_SHA256_MISMATCH",
                    weight_file_sha256_verified=False,
                    observed_weight_file_sha256=snapshot.sha256,
                )
            if manifest.weight_file_size_bytes is None:
                return failure(
                    "WEIGHT_BLOB_SIZE_MISSING",
                    weight_file_sha256_verified=True,
                )
            try:
                expected_size = _manifest_int(
                    manifest.weight_file_size_bytes,
                    field_name="weight_file_size_bytes",
                )
            except (TypeError, ValueError, OverflowError):
                return failure(
                    "WEIGHT_BLOB_SIZE_INVALID",
                    weight_file_sha256_verified=True,
                )
            if expected_size <= 0 or snapshot.size_bytes != expected_size:
                return failure(
                    "WEIGHT_BLOB_SIZE_MISMATCH",
                    weight_file_sha256_verified=True,
                    observed_weight_file_size_bytes=snapshot.size_bytes,
                )
            try:
                feature_abi_binding = manifest_feature_abi_binding
                if feature_abi_binding is None:
                    safe_semantics = _safe_npz_semantics(
                        snapshot.stream,
                        model_id=manifest.model_id,
                    )
                else:
                    safe_semantics = _safe_npz_semantics(
                        snapshot.stream,
                        model_id=manifest.model_id,
                        model=model,
                        checkpoint_feature_abi_binding=feature_abi_binding,
                    )
            except Exception as exc:  # noqa: BLE001 - fail before model mutation
                confidence_head_incompatible = isinstance(exc, ValueError) and (
                    "checkpoint_npz_semantic_metadata_missing" in str(exc)
                )
                return failure(
                    (
                        "LOAD_FAILED:ConfidenceHeadCheckpointIncompatibleError"
                        if confidence_head_incompatible
                        else "SAFE_NPZ_SEMANTIC_VERIFICATION_FAILED:"
                        f"{type(exc).__name__}"
                    ),
                    pre_deserialization_semantic_verification=False,
                    checkpoint_confidence_head_compatible=False,
                    checkpoint_identity_verified=False,
                    confidence_calibration_fitted=False,
                    confidence_calibration_reason=(
                        "CHECKPOINT_CONFIDENCE_HEAD_INCOMPATIBLE"
                        if confidence_head_incompatible
                        else "CHECKPOINT_SAFE_NPZ_SEMANTICS_INVALID"
                    ),
                    load_error_reason=(
                        "CHECKPOINT_CONFIDENCE_HEAD_NOT_PER_DIRECTIONAL_ACTION_V1"
                        if confidence_head_incompatible
                        else str(exc)
                    ),
                    weight_file_sha256_verified=True,
                )
            if safe_semantics.get("input_dim") != model.input_dim:
                return failure(
                    "SAFE_NPZ_INPUT_DIM_MISMATCH",
                    pre_deserialization_semantic_verification=False,
                    checkpoint_confidence_head_compatible=False,
                    checkpoint_identity_verified=False,
                    weight_file_sha256_verified=True,
                )
            if not _checkpoint_feature_abi_matches_npz(
                input_dim=model.input_dim,
                evidence=dict(manifest.checkpoint_evidence),
                safe_semantics=safe_semantics,
            ):
                return failure(
                    "CHECKPOINT_FEATURE_ABI_BINDING_MISMATCH",
                    pre_deserialization_semantic_verification=False,
                    checkpoint_feature_abi_binding_verified=False,
                    checkpoint_identity_verified=False,
                    weight_file_sha256_verified=True,
                )
            if (
                safe_semantics.get("confidence_head_schema_version")
                != CONFIDENCE_HEAD_SCHEMA_VERSION
                or tuple(safe_semantics.get("confidence_head_actions") or ())
                != tuple(CONFIDENCE_HEAD_ACTIONS)
            ):
                return failure(
                    "LOAD_FAILED:ConfidenceHeadCheckpointIncompatibleError",
                    pre_deserialization_semantic_verification=False,
                    checkpoint_confidence_head_compatible=False,
                    checkpoint_identity_verified=False,
                    confidence_calibration_fitted=False,
                    confidence_calibration_reason=(
                        "CHECKPOINT_CONFIDENCE_HEAD_INCOMPATIBLE"
                    ),
                    load_error_reason=(
                        "CHECKPOINT_CONFIDENCE_HEAD_NOT_PER_DIRECTIONAL_ACTION_V1"
                    ),
                    weight_file_sha256_verified=True,
                )
            if (
                safe_semantics.get("confidence_calibration_state")
                != manifest.confidence_calibration_state
                or safe_semantics.get("model_parameter_fingerprint")
                != manifest.model_parameter_fingerprint
            ):
                return failure(
                    "CHECKPOINT_CONTENT_IDENTITY_MISMATCH",
                    pre_deserialization_semantic_verification=False,
                    checkpoint_confidence_head_compatible=True,
                    checkpoint_identity_verified=False,
                    weight_file_sha256_verified=True,
                )
            if _sha256_private_stream(snapshot.stream) != snapshot.sha256:
                return failure(
                    "PRIVATE_CHECKPOINT_COPY_MUTATED_DURING_VERIFICATION",
                    pre_deserialization_semantic_verification=False,
                    checkpoint_confidence_head_compatible=True,
                    checkpoint_identity_verified=False,
                    weight_file_sha256_verified=False,
                )
            try:
                loaded = model.load_weight_blob_stream(
                    snapshot.stream,
                    source_label=str(source_path),
                )
            except ConfidenceHeadCheckpointIncompatibleError as exc:
                return failure(
                    "LOAD_FAILED:ConfidenceHeadCheckpointIncompatibleError",
                    checkpoint_confidence_head_compatible=False,
                    confidence_calibration_fitted=False,
                    confidence_calibration_reason=(
                        "CHECKPOINT_CONFIDENCE_HEAD_INCOMPATIBLE"
                    ),
                    load_error_reason=str(exc),
                    weight_file_sha256_verified=True,
                )
            except Exception as exc:  # noqa: BLE001 - report fail-closed evidence
                return failure(
                    f"LOAD_FAILED:{type(exc).__name__}",
                    weight_file_sha256_verified=True,
                )
            return {
                "private_checkpoint_copy_verified": True,
                "private_checkpoint_source_open_count": 1,
                "private_checkpoint_copy_sha256": snapshot.sha256,
                "private_checkpoint_copy_size_bytes": snapshot.size_bytes,
                "safe_semantics": safe_semantics,
                "loaded": loaded,
                "weight_file_sha256_verified": True,
            }
    except OSError as exc:
        return failure(
            f"PRIVATE_CHECKPOINT_COPY_FAILED:{type(exc).__name__}",
            weight_file_sha256_verified=False,
        )


class V2HybridCheckpointManager:
    """Writes JSON manifests and refuses unapproved external deserialization."""

    def __init__(self, model_dir: Path) -> None:
        self.model_dir = Path(model_dir)
        self._manifest_scan_errors: list[dict[str, str]] = []

    def _validate_model_dir(self) -> None:
        text = str(self.model_dir)
        if not (text.startswith(".local_models") or "/.local_models/" in text):
            raise ValueError("checkpoint manifests must live under .local_models")

    @property
    def _causal_root(self) -> Path:
        if self.model_dir.name in _CHECKPOINT_STORE_SUBDIRECTORIES:
            return self.model_dir.parent
        return self.model_dir

    @property
    def _causal_ledger_path(self) -> Path:
        return self._causal_root / _CHECKPOINT_CAUSAL_LEDGER_NAME

    @property
    def _causal_store(self) -> str:
        if self.model_dir.name in _CHECKPOINT_STORE_SUBDIRECTORIES:
            return self.model_dir.name
        return "serving_root"

    def _read_causal_ledger(
        self,
        *,
        repair_torn_tail: bool = False,
    ) -> tuple[_CausalGenerationRecord, ...]:
        path = self._causal_ledger_path
        if not path.exists():
            return ()
        records: list[_CausalGenerationRecord] = []
        previous_digest = _CHECKPOINT_CAUSAL_GENESIS_DIGEST
        semantic_digests: set[str] = set()
        expected_fields = {
            "schema_version",
            "checkpoint_generation",
            "checkpoint_causal_store",
            "checkpoint_semantic_digest",
            "parent_checkpoint_id",
            "parent_checkpoint_generation",
            "generated_utc",
            "previous_record_digest",
            "checkpoint_causal_record_digest",
        }
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise RuntimeError("checkpoint_causal_ledger_unreadable") from exc
        if content and not content.endswith(b"\n"):
            if not repair_torn_tail:
                raise RuntimeError("checkpoint_causal_ledger_torn_tail")
            committed_length = content.rfind(b"\n") + 1
            try:
                with path.open("r+b") as handle:
                    handle.truncate(committed_length)
                    handle.flush()
                    os.fsync(handle.fileno())
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError as exc:
                raise RuntimeError(
                    "checkpoint_causal_ledger_torn_tail_repair_failed"
                ) from exc
            content = content[:committed_length]
        try:
            lines = content.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise RuntimeError("checkpoint_causal_ledger_invalid_utf8") from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                raise RuntimeError(
                    f"checkpoint_causal_ledger_blank_row:{line_number}"
                )
            try:
                raw = _strict_json_loads(line)
                if not isinstance(raw, dict) or set(raw) != expected_fields:
                    raise ValueError("causal_ledger_fields_invalid")
                if raw.get("schema_version") != CHECKPOINT_CAUSAL_ORDER_SCHEMA_VERSION:
                    raise ValueError("causal_ledger_schema_invalid")
                generation = _manifest_int(
                    raw.get("checkpoint_generation"),
                    field_name="checkpoint_generation",
                )
                if generation != line_number:
                    raise ValueError("causal_ledger_generation_not_contiguous")
                checkpoint_causal_store = str(
                    raw.get("checkpoint_causal_store") or ""
                )
                if checkpoint_causal_store not in {
                    "serving_root",
                    *_CHECKPOINT_STORE_SUBDIRECTORIES,
                }:
                    raise ValueError("causal_ledger_store_invalid")
                semantic_digest = str(raw.get("checkpoint_semantic_digest") or "")
                if not _is_sha256(semantic_digest):
                    raise ValueError("causal_ledger_semantic_digest_invalid")
                if semantic_digest in semantic_digests:
                    raise ValueError("causal_ledger_semantic_digest_duplicate")
                parent_checkpoint_id = raw.get("parent_checkpoint_id")
                if parent_checkpoint_id is not None and (
                    not isinstance(parent_checkpoint_id, str)
                    or not parent_checkpoint_id
                    or Path(parent_checkpoint_id).name != parent_checkpoint_id
                ):
                    raise ValueError("causal_ledger_parent_id_invalid")
                raw_parent_generation = raw.get("parent_checkpoint_generation")
                parent_generation = (
                    None
                    if raw_parent_generation is None
                    else _manifest_int(
                        raw_parent_generation,
                        field_name="parent_checkpoint_generation",
                    )
                )
                if parent_checkpoint_id is None and parent_generation is not None:
                    raise ValueError("causal_ledger_parent_generation_without_parent")
                if parent_checkpoint_id is not None and (
                    parent_generation is None
                    or parent_generation < 0
                    or parent_generation >= generation
                ):
                    raise ValueError("causal_ledger_parent_generation_invalid")
                generated_utc = str(raw.get("generated_utc") or "")
                _strict_generated_utc(
                    generated_utc,
                    allow_future_after_clock_rollback=True,
                )
                if raw.get("previous_record_digest") != previous_digest:
                    raise ValueError("causal_ledger_chain_predecessor_mismatch")
                record = _CausalGenerationRecord(
                    checkpoint_generation=generation,
                    checkpoint_causal_store=checkpoint_causal_store,
                    checkpoint_semantic_digest=semantic_digest,
                    parent_checkpoint_id=parent_checkpoint_id,
                    parent_checkpoint_generation=parent_generation,
                    generated_utc=generated_utc,
                    previous_record_digest=previous_digest,
                    checkpoint_causal_record_digest=str(
                        raw.get("checkpoint_causal_record_digest") or ""
                    ),
                )
                if (
                    not _is_sha256(record.checkpoint_causal_record_digest)
                    or _canonical_digest(record.payload_without_digest())
                    != record.checkpoint_causal_record_digest
                ):
                    raise ValueError("causal_ledger_record_digest_invalid")
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError(
                    f"checkpoint_causal_ledger_invalid:{line_number}"
                ) from exc
            records.append(record)
            semantic_digests.add(semantic_digest)
            previous_digest = record.checkpoint_causal_record_digest
        return tuple(records)

    def _read_causal_ledger_with_tail_recovery(
        self,
    ) -> tuple[_CausalGenerationRecord, ...]:
        try:
            return self._read_causal_ledger()
        except RuntimeError as exc:
            if str(exc) != "checkpoint_causal_ledger_torn_tail":
                raise
        with self._exclusive_write_lock():
            return self._read_causal_ledger(repair_torn_tail=True)

    def _append_causal_record(self, record: _CausalGenerationRecord) -> None:
        path = self._causal_ledger_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    record.payload(),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _causal_manifest_paths(self, checkpoint_id: str) -> tuple[Path, ...]:
        if not checkpoint_id or Path(checkpoint_id).name != checkpoint_id:
            return ()
        roots = (self._causal_root,) + tuple(
            self._causal_root / directory
            for directory in sorted(_CHECKPOINT_STORE_SUBDIRECTORIES)
        )
        return tuple(
            path
            for path in (root / f"{checkpoint_id}.json" for root in roots)
            if path.is_file()
        )

    def _validate_lineage_artifact(self, raw: dict[str, Any]) -> None:
        checkpoint_id = str(raw.get("checkpoint_id") or "")
        if raw.get("weight_blob_written") is not True:
            raise ValueError("checkpoint_lineage_weight_missing")
        if raw.get("weight_file_format") != "npz":
            raise ValueError("checkpoint_lineage_weight_format_invalid")
        resolved = self._resolve_weight_path(
            raw.get("weight_file_path"),
            checkpoint_id,
        )
        if resolved is None:
            raise ValueError("checkpoint_lineage_weight_path_unresolved")
        expected_sha256 = str(raw.get("weight_file_sha256") or "")
        expected_size = _manifest_int(
            raw.get("weight_file_size_bytes"),
            field_name="weight_file_size_bytes",
        )
        evidence = raw.get("checkpoint_evidence")
        require_sealed = (
            type(evidence) is dict
            and _CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD in evidence
        )
        with _private_checkpoint_copy(
            resolved,
            require_sealed=require_sealed,
        ) as snapshot:
            if (
                not _is_sha256(expected_sha256)
                or snapshot.sha256 != expected_sha256
            ):
                raise ValueError("checkpoint_lineage_weight_sha256_invalid")
            if expected_size <= 0 or snapshot.size_bytes != expected_size:
                raise ValueError("checkpoint_lineage_weight_size_invalid")
            feature_abi_binding = (
                evidence.get(_CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD)
                if type(evidence) is dict
                else None
            )
            if feature_abi_binding is None:
                semantics = _safe_npz_semantics(
                    snapshot.stream,
                    model_id=str(raw.get("model_id") or ""),
                )
            else:
                semantics = _safe_npz_semantics(
                    snapshot.stream,
                    model_id=str(raw.get("model_id") or ""),
                    checkpoint_feature_abi_binding=feature_abi_binding,
                )
        if (
            semantics.get("input_dim")
            != _manifest_int(raw.get("input_dim"), field_name="input_dim")
            or semantics.get("model_parameter_fingerprint")
            != raw.get("model_parameter_fingerprint")
            or semantics.get("confidence_calibration_state")
            != raw.get("confidence_calibration_state")
        ):
            raise ValueError("checkpoint_lineage_weight_semantics_invalid")
        raw_evidence = raw.get("checkpoint_evidence")
        if not _checkpoint_feature_abi_matches_npz(
            input_dim=_manifest_int(raw.get("input_dim"), field_name="input_dim"),
            evidence=(dict(raw_evidence) if isinstance(raw_evidence, dict) else {}),
            safe_semantics=semantics,
        ):
            raise ValueError("checkpoint_lineage_feature_abi_binding_invalid")

    def _validate_causal_manifest(
        self,
        raw: dict[str, Any],
        *,
        ledger_records: tuple[_CausalGenerationRecord, ...],
        verify_lineage_artifacts: bool = True,
    ) -> int:
        causal_fields = {
            "checkpoint_causal_order_schema_version",
            "checkpoint_causal_store",
            "checkpoint_generation",
            "parent_checkpoint_generation",
            "checkpoint_semantic_digest",
            "checkpoint_causal_record_digest",
        }
        present = causal_fields.intersection(raw)
        if not present:
            return 0
        if present != causal_fields:
            raise ValueError("checkpoint_causal_fields_partial")
        if (
            raw.get("checkpoint_causal_order_schema_version")
            != CHECKPOINT_CAUSAL_ORDER_SCHEMA_VERSION
        ):
            raise ValueError("checkpoint_causal_schema_invalid")
        if raw.get("checkpoint_source") != CHECKPOINT_SOURCE:
            raise ValueError("checkpoint_causal_source_invalid")
        if raw.get("checkpoint_causal_store") != self._causal_store:
            raise ValueError("checkpoint_causal_store_invalid")
        generation = _manifest_int(
            raw.get("checkpoint_generation"),
            field_name="checkpoint_generation",
        )
        if generation <= 0 or generation > len(ledger_records):
            raise ValueError("checkpoint_generation_invalid")
        semantic_digest = str(raw.get("checkpoint_semantic_digest") or "")
        record_digest = str(raw.get("checkpoint_causal_record_digest") or "")
        if not _is_sha256(semantic_digest) or not _is_sha256(record_digest):
            raise ValueError("checkpoint_causal_digest_invalid")
        parent_checkpoint_id = raw.get("parent_checkpoint_id")
        raw_parent_generation = raw.get("parent_checkpoint_generation")
        parent_generation = (
            None
            if raw_parent_generation is None
            else _manifest_int(
                raw_parent_generation,
                field_name="parent_checkpoint_generation",
            )
        )
        if parent_checkpoint_id is None and parent_generation is not None:
            raise ValueError("checkpoint_parent_generation_without_parent")
        if parent_checkpoint_id is not None and (
            parent_generation is None
            or parent_generation < 0
            or parent_generation >= generation
        ):
            raise ValueError("checkpoint_parent_generation_invalid")
        evidence = raw.get("checkpoint_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("checkpoint_causal_evidence_missing")
        _verify_checkpoint_feature_abi_evidence(
            input_dim=_manifest_int(raw.get("input_dim"), field_name="input_dim"),
            evidence=dict(evidence),
        )
        evidence_bindings = {
            "checkpoint_causal_order_schema_version": (
                CHECKPOINT_CAUSAL_ORDER_SCHEMA_VERSION
            ),
            "checkpoint_causal_store": self._causal_store,
            "checkpoint_generation": generation,
            "parent_checkpoint_generation": parent_generation,
            "checkpoint_semantic_digest": semantic_digest,
            "checkpoint_causal_record_digest": record_digest,
        }
        if any(
            evidence.get(field_name) != expected
            for field_name, expected in evidence_bindings.items()
        ):
            raise ValueError("checkpoint_causal_evidence_binding_mismatch")
        if (
            raw.get("checkpoint_evidence_schema_version")
            != CHECKPOINT_EVIDENCE_SCHEMA_VERSION
            or raw.get("checkpoint_evidence_digest")
            != _canonical_digest(evidence)
        ):
            raise ValueError("checkpoint_evidence_digest_mismatch")
        observed_semantic_digest = _checkpoint_semantic_digest(
            model_id=str(raw.get("model_id") or ""),
            input_dim=_manifest_int(raw.get("input_dim"), field_name="input_dim"),
            checkpoint_causal_store=self._causal_store,
            confidence_calibration_state=(
                dict(raw.get("confidence_calibration_state"))
                if isinstance(raw.get("confidence_calibration_state"), dict)
                else {}
            ),
            model_parameter_fingerprint=raw.get("model_parameter_fingerprint"),
            lineage_kind=str(raw.get("lineage_kind") or "SERVING_CANDIDATE"),
            parent_checkpoint_id=parent_checkpoint_id,
            parent_policy_fingerprint=raw.get("parent_policy_fingerprint"),
            consumed_ppo_update_keys=tuple(
                str(value) for value in (raw.get("consumed_ppo_update_keys") or ())
            ),
            training_partition_digest=raw.get("training_partition_digest"),
            checkpoint_evidence=evidence,
        )
        if observed_semantic_digest != semantic_digest:
            raise ValueError("checkpoint_semantic_digest_mismatch")
        manifest_fingerprint = str(raw.get("model_parameter_fingerprint") or "")
        calibration_state = raw.get("confidence_calibration_state")
        if (
            _is_sha256(manifest_fingerprint)
            and isinstance(calibration_state, dict)
            and calibration_state
        ):
            calibration_fingerprint = _canonical_digest(calibration_state)
            state_fingerprint = _canonical_digest(
                {
                    "confidence_calibration_fingerprint": calibration_fingerprint,
                    "checkpoint_evidence_digest": raw.get(
                        "checkpoint_evidence_digest"
                    ),
                }
            )
            expected_checkpoint_id = (
                f"v2_hybrid_ckpt_{str(raw.get('model_id') or '')[-8:]}_"
                f"{manifest_fingerprint[:16]}_{state_fingerprint[:12]}"
            )
        else:
            expected_checkpoint_id = (
                f"v2_hybrid_ckpt_{str(raw.get('model_id') or '')[-8:]}_"
                f"{semantic_digest[:16]}_{record_digest[:12]}"
            )
        if raw.get("checkpoint_id") != expected_checkpoint_id:
            raise ValueError("checkpoint_causal_content_identity_mismatch")
        record = ledger_records[generation - 1]
        if (
            record.checkpoint_generation != generation
            or record.checkpoint_causal_store != self._causal_store
            or record.checkpoint_semantic_digest != semantic_digest
            or record.parent_checkpoint_id != parent_checkpoint_id
            or record.parent_checkpoint_generation != parent_generation
            or record.generated_utc != raw.get("generated_utc")
            or record.checkpoint_causal_record_digest != record_digest
        ):
            raise ValueError("checkpoint_causal_ledger_binding_mismatch")
        if parent_checkpoint_id is not None:
            parent_paths = self._causal_manifest_paths(parent_checkpoint_id)
            if len(parent_paths) != 1:
                raise ValueError("checkpoint_causal_parent_manifest_unavailable")
            parent_manager = V2HybridCheckpointManager(parent_paths[0].parent)
            parent_raw = _strict_json_loads(
                parent_paths[0].read_text(encoding="utf-8")
            )
            if not isinstance(parent_raw, dict):
                raise ValueError("checkpoint_causal_parent_manifest_invalid")
            observed_parent_generation = parent_manager._validate_causal_manifest(
                parent_raw,
                ledger_records=ledger_records,
                verify_lineage_artifacts=verify_lineage_artifacts,
            )
            if observed_parent_generation == 0:
                if (
                    parent_raw.get("checkpoint_id") != parent_checkpoint_id
                    or parent_raw.get("checkpoint_source")
                    not in (None, CHECKPOINT_SOURCE)
                ):
                    raise ValueError("checkpoint_legacy_parent_identity_invalid")
                _strict_generated_utc(parent_raw.get("generated_utc"))
            if (
                observed_parent_generation != parent_generation
                or parent_raw.get("model_parameter_fingerprint")
                != raw.get("parent_policy_fingerprint")
            ):
                raise ValueError("checkpoint_causal_parent_binding_mismatch")
            if verify_lineage_artifacts:
                parent_manager._validate_lineage_artifact(parent_raw)
        return generation

    def _parent_checkpoint_generation(
        self,
        *,
        parent_checkpoint_id: str | None,
        parent_policy_fingerprint: str | None,
        ledger_records: tuple[_CausalGenerationRecord, ...],
    ) -> int | None:
        if parent_checkpoint_id is None:
            return None
        paths = self._causal_manifest_paths(parent_checkpoint_id)
        if not paths:
            raise RuntimeError("checkpoint_parent_manifest_missing")
        if len(paths) != 1:
            raise RuntimeError("checkpoint_parent_manifest_ambiguous")
        try:
            raw = _strict_json_loads(paths[0].read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("checkpoint_parent_manifest_not_object")
            if raw.get("checkpoint_id") != parent_checkpoint_id:
                raise ValueError("checkpoint_parent_identity_mismatch")
            if raw.get("checkpoint_source") not in (None, CHECKPOINT_SOURCE):
                raise ValueError("checkpoint_parent_source_invalid")
            if not isinstance(raw.get("model_id"), str) or not raw.get("model_id"):
                raise ValueError("checkpoint_parent_model_id_invalid")
            if (
                _manifest_int(raw.get("input_dim"), field_name="input_dim")
                <= 0
            ):
                raise ValueError("checkpoint_parent_input_dim_invalid")
            if not isinstance(raw.get("weight_blob_written"), bool):
                raise ValueError("checkpoint_parent_weight_flag_invalid")
            if not _is_sha256(parent_policy_fingerprint):
                raise ValueError("checkpoint_parent_policy_fingerprint_invalid")
            if raw.get("model_parameter_fingerprint") != parent_policy_fingerprint:
                raise ValueError("checkpoint_parent_policy_fingerprint_mismatch")
            parent_manager = V2HybridCheckpointManager(paths[0].parent)
            generation = parent_manager._validate_causal_manifest(
                raw,
                ledger_records=ledger_records,
            )
            parent_manager._validate_lineage_artifact(raw)
            _strict_generated_utc(
                raw.get("generated_utc"),
                allow_future_after_clock_rollback=generation > 0,
            )
        except (OSError, TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError("checkpoint_parent_manifest_invalid") from exc
        return generation

    def _allocate_causal_generation(
        self,
        *,
        checkpoint_semantic_digest: str,
        parent_checkpoint_id: str | None,
        parent_policy_fingerprint: str | None,
    ) -> _CausalGenerationRecord:
        records = self._read_causal_ledger(repair_torn_tail=True)
        parent_generation = self._parent_checkpoint_generation(
            parent_checkpoint_id=parent_checkpoint_id,
            parent_policy_fingerprint=parent_policy_fingerprint,
            ledger_records=records,
        )
        for record in records:
            if record.checkpoint_semantic_digest == checkpoint_semantic_digest:
                if (
                    record.checkpoint_causal_store != self._causal_store
                    or record.parent_checkpoint_id != parent_checkpoint_id
                    or record.parent_checkpoint_generation != parent_generation
                ):
                    raise RuntimeError(
                        "checkpoint_causal_semantic_identity_conflict"
                    )
                return record
        generation = len(records) + 1
        if parent_generation is not None and parent_generation >= generation:
            raise RuntimeError("checkpoint_parent_generation_not_predecessor")
        previous_digest = (
            records[-1].checkpoint_causal_record_digest
            if records
            else _CHECKPOINT_CAUSAL_GENESIS_DIGEST
        )
        base_record = _CausalGenerationRecord(
            checkpoint_generation=generation,
            checkpoint_causal_store=self._causal_store,
            checkpoint_semantic_digest=checkpoint_semantic_digest,
            parent_checkpoint_id=parent_checkpoint_id,
            parent_checkpoint_generation=parent_generation,
            generated_utc=_utc_iso(),
            previous_record_digest=previous_digest,
            checkpoint_causal_record_digest="",
        )
        record = _CausalGenerationRecord(
            **{
                **base_record.__dict__,
                "checkpoint_causal_record_digest": _canonical_digest(
                    base_record.payload_without_digest()
                ),
            }
        )
        self._append_causal_record(record)
        return record

    @contextmanager
    def _exclusive_write_lock(self) -> Iterator[None]:
        self._causal_root.mkdir(parents=True, exist_ok=True)
        lock_path = self._causal_root / _CHECKPOINT_CAUSAL_LOCK_NAME
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def write_manifest(
        self,
        *,
        model_id: str,
        input_dim: int,
        device: str,
        cuda_active: bool,
        weight_blob_written: bool = False,
        weight_file_path: str | None = None,
        weight_file_format: str | None = None,
        weight_file_size_bytes: int | None = None,
        confidence_calibration_state: dict[str, Any] | None = None,
        checkpoint_id: str | None = None,
        model_parameter_fingerprint: str | None = None,
        weight_file_sha256: str | None = None,
        lineage_kind: str = "SERVING_CANDIDATE",
        parent_checkpoint_id: str | None = None,
        parent_policy_fingerprint: str | None = None,
        consumed_ppo_update_keys: tuple[str, ...] = (),
        training_partition_digest: str | None = None,
        checkpoint_evidence: dict[str, Any] | None = None,
        checkpoint_evidence_digest: str | None = None,
        checkpoint_feature_abi_declaration: dict[str, object] | None = None,
        _causal_record: _CausalGenerationRecord | None = None,
        _semantic_digest: str | None = None,
    ) -> CheckpointManifest:
        self._validate_model_dir()
        if (
            checkpoint_feature_abi_declaration is not None
            and type(input_dim) is not int
        ):
            raise ValueError("input_dim_not_integer")
        strict_input_dim = _manifest_int(input_dim, field_name="input_dim")
        calibration = dict(confidence_calibration_state or {})
        ordered_consumed_keys = tuple(dict.fromkeys(consumed_ppo_update_keys))
        base_evidence = _bind_checkpoint_feature_abi_evidence(
            input_dim=strict_input_dim,
            evidence=_base_checkpoint_evidence(dict(checkpoint_evidence or {})),
            feature_abi_declaration=checkpoint_feature_abi_declaration,
        )
        self.model_dir.mkdir(parents=True, exist_ok=True)
        semantic_digest = _semantic_digest
        if semantic_digest is None:
            semantic_digest = _checkpoint_semantic_digest(
                model_id=model_id,
                input_dim=input_dim,
                checkpoint_causal_store=self._causal_store,
                confidence_calibration_state=calibration,
                model_parameter_fingerprint=model_parameter_fingerprint,
                lineage_kind=lineage_kind,
                parent_checkpoint_id=parent_checkpoint_id,
                parent_policy_fingerprint=parent_policy_fingerprint,
                consumed_ppo_update_keys=ordered_consumed_keys,
                training_partition_digest=training_partition_digest,
                checkpoint_evidence=base_evidence,
            )
        if not isinstance(semantic_digest, str) or not _is_sha256(semantic_digest):
            raise ValueError("checkpoint_semantic_digest_invalid")
        if _causal_record is None:
            with self._exclusive_write_lock():
                record = self._allocate_causal_generation(
                    checkpoint_semantic_digest=semantic_digest,
                    parent_checkpoint_id=parent_checkpoint_id,
                    parent_policy_fingerprint=parent_policy_fingerprint,
                )
                return self.write_manifest(
                    model_id=model_id,
                    input_dim=input_dim,
                    device=device,
                    cuda_active=cuda_active,
                    weight_blob_written=weight_blob_written,
                    weight_file_path=weight_file_path,
                    weight_file_format=weight_file_format,
                    weight_file_size_bytes=weight_file_size_bytes,
                    confidence_calibration_state=calibration,
                    checkpoint_id=checkpoint_id,
                    model_parameter_fingerprint=model_parameter_fingerprint,
                    weight_file_sha256=weight_file_sha256,
                    lineage_kind=lineage_kind,
                    parent_checkpoint_id=parent_checkpoint_id,
                    parent_policy_fingerprint=parent_policy_fingerprint,
                    consumed_ppo_update_keys=ordered_consumed_keys,
                    training_partition_digest=training_partition_digest,
                    checkpoint_evidence=base_evidence,
                    checkpoint_evidence_digest=checkpoint_evidence_digest,
                    checkpoint_feature_abi_declaration=(
                        checkpoint_feature_abi_declaration
                    ),
                    _causal_record=record,
                    _semantic_digest=semantic_digest,
                )
        if (
            _causal_record.checkpoint_semantic_digest != semantic_digest
            or _causal_record.parent_checkpoint_id != parent_checkpoint_id
        ):
            raise ValueError("checkpoint_causal_record_semantics_mismatch")
        checkpoint_id = checkpoint_id or (
            f"v2_hybrid_ckpt_{model_id[-8:]}_"
            f"{semantic_digest[:16]}_"
            f"{_causal_record.checkpoint_causal_record_digest[:12]}"
        )
        evidence = {
            **base_evidence,
            "checkpoint_causal_order_schema_version": (
                CHECKPOINT_CAUSAL_ORDER_SCHEMA_VERSION
            ),
            "checkpoint_causal_store": self._causal_store,
            "checkpoint_generation": _causal_record.checkpoint_generation,
            "parent_checkpoint_generation": (
                _causal_record.parent_checkpoint_generation
            ),
            "checkpoint_semantic_digest": semantic_digest,
            "checkpoint_causal_record_digest": (
                _causal_record.checkpoint_causal_record_digest
            ),
        }
        causal_evidence_digest = _canonical_digest(evidence)
        if (
            checkpoint_evidence_digest is not None
            and checkpoint_evidence_digest != causal_evidence_digest
        ):
            raise ValueError("checkpoint_causal_evidence_digest_mismatch")
        manifest = CheckpointManifest(
            checkpoint_id=checkpoint_id,
            checkpoint_source=CHECKPOINT_SOURCE,
            path=str(self.model_dir / f"{checkpoint_id}.json"),
            generated_utc=_causal_record.generated_utc,
            model_id=model_id,
            input_dim=strict_input_dim,
            device=device,
            cuda_active=bool(cuda_active),
            weight_blob_written=bool(weight_blob_written),
            weight_file_path=weight_file_path,
            weight_file_format=weight_file_format,
            weight_file_size_bytes=weight_file_size_bytes,
            confidence_calibration_fitted=calibration.get("fitted") is True,
            confidence_calibration_temperature=(
                float(calibration["temperature"])
                if calibration.get("fitted") is True
                and calibration.get("temperature") is not None
                else None
            ),
            confidence_calibration_sample=int(calibration.get("sample") or 0),
            confidence_calibration_reason=calibration.get("reason"),
            confidence_calibration_fit_partition=calibration.get("fit_partition"),
            confidence_calibration_validation_rows_used=int(
                calibration.get("validation_rows_used") or 0
            ),
            confidence_calibration_label_semantics=calibration.get("label_semantics"),
            confidence_head_schema_version=calibration.get(
                "confidence_head_schema_version"
            ),
            confidence_head_actions=tuple(
                str(action)
                for action in (calibration.get("confidence_head_actions") or ())
            ),
            confidence_calibration_long_sample=int(
                (calibration.get("action_counts") or {}).get("long") or 0
            ),
            confidence_calibration_short_sample=int(
                (calibration.get("action_counts") or {}).get("short") or 0
            ),
            confidence_calibration_model_parameter_fingerprint=calibration.get(
                "model_parameter_fingerprint"
            ),
            confidence_calibration_row_digest=calibration.get("row_digest"),
            confidence_calibration_state=calibration,
            model_parameter_fingerprint=model_parameter_fingerprint,
            weight_file_sha256=weight_file_sha256,
            lineage_kind=str(lineage_kind),
            parent_checkpoint_id=parent_checkpoint_id,
            parent_policy_fingerprint=parent_policy_fingerprint,
            consumed_ppo_update_keys=ordered_consumed_keys,
            training_partition_digest=training_partition_digest,
            checkpoint_evidence_schema_version=(
                CHECKPOINT_EVIDENCE_SCHEMA_VERSION
                if causal_evidence_digest
                else None
            ),
            checkpoint_evidence=evidence,
            checkpoint_evidence_digest=causal_evidence_digest,
            checkpoint_causal_order_schema_version=(
                CHECKPOINT_CAUSAL_ORDER_SCHEMA_VERSION
            ),
            checkpoint_causal_store=self._causal_store,
            checkpoint_generation=_causal_record.checkpoint_generation,
            parent_checkpoint_generation=(
                _causal_record.parent_checkpoint_generation
            ),
            checkpoint_semantic_digest=semantic_digest,
            checkpoint_causal_record_digest=(
                _causal_record.checkpoint_causal_record_digest
            ),
        )
        path = Path(manifest.path)
        _atomic_write_text(path, json.dumps(manifest.__dict__, indent=2, sort_keys=True))
        return manifest

    def write_checkpoint(
        self,
        *,
        model: V2HybridPolicyModel,
        input_dim: int,
        device: str,
        cuda_active: bool,
        write_weight_blob: bool = True,
        lineage_kind: str = "SERVING_CANDIDATE",
        parent_checkpoint_id: str | None = None,
        parent_policy_fingerprint: str | None = None,
        consumed_ppo_update_keys: tuple[str, ...] = (),
        training_partition_digest: str | None = None,
        checkpoint_evidence: dict[str, Any] | None = None,
    ) -> CheckpointManifest:
        """Write atomically while rolling model state back on every failure."""

        # Checkpoint writing can normalize calibration metadata but does not
        # mutate model parameters. Avoid duplicating the deployed model on GPU.
        model_state_before = model._mutable_state_snapshot(
            include_model_parameters=False,
        )
        try:
            return self._write_checkpoint_impl(
                model=model,
                input_dim=input_dim,
                device=device,
                cuda_active=cuda_active,
                write_weight_blob=write_weight_blob,
                lineage_kind=lineage_kind,
                parent_checkpoint_id=parent_checkpoint_id,
                parent_policy_fingerprint=parent_policy_fingerprint,
                consumed_ppo_update_keys=consumed_ppo_update_keys,
                training_partition_digest=training_partition_digest,
                checkpoint_evidence=checkpoint_evidence,
            )
        except Exception:
            model._restore_mutable_state_snapshot(model_state_before)
            raise

    def _write_checkpoint_impl(
        self,
        *,
        model: V2HybridPolicyModel,
        input_dim: int,
        device: str,
        cuda_active: bool,
        write_weight_blob: bool = True,
        lineage_kind: str = "SERVING_CANDIDATE",
        parent_checkpoint_id: str | None = None,
        parent_policy_fingerprint: str | None = None,
        consumed_ppo_update_keys: tuple[str, ...] = (),
        training_partition_digest: str | None = None,
        checkpoint_evidence: dict[str, Any] | None = None,
    ) -> CheckpointManifest:
        self._validate_model_dir()
        try:
            parsed_input_dim = _manifest_int(input_dim, field_name="input_dim")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("checkpoint_model_input_dim_mismatch") from exc
        if parsed_input_dim != model.input_dim:
            raise ValueError("checkpoint_model_input_dim_mismatch")
        feature_abi_declaration = model.checkpoint_feature_abi_declaration
        if feature_abi_declaration is not None and type(input_dim) is not int:
            raise ValueError("checkpoint_model_input_dim_mismatch")
        input_dim = parsed_input_dim
        from .on_policy_behavior import model_parameter_fingerprint

        calibration_state = model.set_confidence_calibration_state(
            model.confidence_calibration_state
        )
        parameter_fingerprint = model_parameter_fingerprint(model)
        calibration_fingerprint = hashlib.sha256(
            json.dumps(
                calibration_state,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        ordered_consumed_keys = tuple(dict.fromkeys(consumed_ppo_update_keys))
        base_evidence = _bind_checkpoint_feature_abi_evidence(
            input_dim=input_dim,
            evidence={
                **dict(checkpoint_evidence or {}),
                "schema_version": CHECKPOINT_EVIDENCE_SCHEMA_VERSION,
                "lineage_kind": str(lineage_kind),
                "parent_checkpoint_id": parent_checkpoint_id,
                "parent_policy_fingerprint": parent_policy_fingerprint,
                "consumed_ppo_update_keys": list(ordered_consumed_keys),
                "training_partition_digest": training_partition_digest,
            },
            feature_abi_declaration=feature_abi_declaration,
        )
        with self._exclusive_write_lock():
            semantic_digest = _checkpoint_semantic_digest(
                model_id=model.model_id,
                input_dim=input_dim,
                checkpoint_causal_store=self._causal_store,
                confidence_calibration_state=calibration_state,
                model_parameter_fingerprint=parameter_fingerprint,
                lineage_kind=lineage_kind,
                parent_checkpoint_id=parent_checkpoint_id,
                parent_policy_fingerprint=parent_policy_fingerprint,
                consumed_ppo_update_keys=ordered_consumed_keys,
                training_partition_digest=training_partition_digest,
                checkpoint_evidence=base_evidence,
            )
            causal_record = self._allocate_causal_generation(
                checkpoint_semantic_digest=semantic_digest,
                parent_checkpoint_id=parent_checkpoint_id,
                parent_policy_fingerprint=parent_policy_fingerprint,
            )
            evidence = {
                **base_evidence,
                "checkpoint_causal_order_schema_version": (
                    CHECKPOINT_CAUSAL_ORDER_SCHEMA_VERSION
                ),
                "checkpoint_causal_store": self._causal_store,
                "checkpoint_generation": causal_record.checkpoint_generation,
                "parent_checkpoint_generation": (
                    causal_record.parent_checkpoint_generation
                ),
                "checkpoint_semantic_digest": semantic_digest,
                "checkpoint_causal_record_digest": (
                    causal_record.checkpoint_causal_record_digest
                ),
            }
            evidence_digest = _canonical_digest(evidence)
            checkpoint_state_fingerprint = _canonical_digest(
                {
                    "confidence_calibration_fingerprint": calibration_fingerprint,
                    "checkpoint_evidence_digest": evidence_digest,
                }
            )
            checkpoint_id = (
                f"v2_hybrid_ckpt_{model.model_id[-8:]}_"
                f"{parameter_fingerprint[:16]}_{checkpoint_state_fingerprint[:12]}"
            )
            weight: dict[str, Any] = {}
            weight_path = self.model_dir / f"{checkpoint_id}.weights.npz"
            manifest_path = self.model_dir / f"{checkpoint_id}.json"
            if manifest_path.exists():
                try:
                    existing = _strict_json_loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    raise RuntimeError("checkpoint_existing_manifest_invalid") from exc
                expected_fields = {
                    "checkpoint_id": checkpoint_id,
                    "model_id": model.model_id,
                    "model_parameter_fingerprint": parameter_fingerprint,
                    "confidence_calibration_state": calibration_state,
                    "checkpoint_evidence": evidence,
                    "checkpoint_evidence_digest": evidence_digest,
                }
                if any(
                    existing.get(field_name) != expected
                    for field_name, expected in expected_fields.items()
                ):
                    raise RuntimeError(
                        "checkpoint_existing_semantic_identity_conflict"
                    )
                existing_has_weight = existing.get("weight_blob_written") is True
                if existing_has_weight:
                    if not weight_path.is_file():
                        raise RuntimeError("checkpoint_existing_weight_missing")
                    existing_sha = str(existing.get("weight_file_sha256") or "")
                    actual_digest = hashlib.sha256()
                    with weight_path.open("rb") as handle:
                        for chunk in iter(
                            lambda: handle.read(1024 * 1024), b""
                        ):
                            actual_digest.update(chunk)
                    if (
                        len(existing_sha) != 64
                        or actual_digest.hexdigest() != existing_sha
                    ):
                        raise RuntimeError("checkpoint_existing_weight_sha256_conflict")
                elif write_weight_blob:
                    raise RuntimeError(
                        "checkpoint_metadata_identity_cannot_replace_with_weight"
                    )
                rows = self._manifest_rows(
                    input_dim=input_dim,
                    model_id=model.model_id,
                    require_weight_blob=existing_has_weight,
                )
                if self._manifest_scan_errors:
                    raise RuntimeError("checkpoint_manifest_scan_invalid")
                for _mtime, existing_manifest in rows:
                    if existing_manifest.checkpoint_id == checkpoint_id:
                        return existing_manifest
                raise RuntimeError("checkpoint_existing_manifest_unreadable")
            if weight_path.exists():
                if write_weight_blob:
                    quarantine = self.model_dir / (
                        f".{weight_path.name}.orphan.{os.getpid()}.{datetime.now(UTC).timestamp():.0f}"
                    )
                    weight_path.replace(quarantine)
                    directory_fd = os.open(weight_path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                else:
                    raise RuntimeError(
                        "checkpoint_metadata_write_refuses_orphan_weight"
                    )
            if write_weight_blob:
                weight = model.save_weight_blob(weight_path)
                weight_path = Path(str(weight.get("weight_file_path") or ""))
                if not weight_path.is_file():
                    raise RuntimeError("checkpoint_weight_blob_not_durable")
                with weight_path.open("rb") as handle:
                    os.fsync(handle.fileno())
                directory_fd = os.open(weight_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                digest = hashlib.sha256()
                with weight_path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                weight["weight_file_sha256"] = digest.hexdigest()
            return self.write_manifest(
                model_id=model.model_id,
                input_dim=input_dim,
                device=device,
                cuda_active=cuda_active,
                weight_blob_written=bool(weight),
                weight_file_path=weight.get("weight_file_path"),
                weight_file_format=weight.get("weight_file_format"),
                weight_file_size_bytes=weight.get("weight_file_size_bytes"),
                confidence_calibration_state=calibration_state,
                checkpoint_id=checkpoint_id,
                model_parameter_fingerprint=parameter_fingerprint,
                weight_file_sha256=weight.get("weight_file_sha256"),
                lineage_kind=lineage_kind,
                parent_checkpoint_id=parent_checkpoint_id,
                parent_policy_fingerprint=parent_policy_fingerprint,
                consumed_ppo_update_keys=ordered_consumed_keys,
                training_partition_digest=training_partition_digest,
                checkpoint_evidence=evidence,
                checkpoint_evidence_digest=evidence_digest,
                checkpoint_feature_abi_declaration=feature_abi_declaration,
                _causal_record=causal_record,
                _semantic_digest=semantic_digest,
            )

    def _resolve_weight_path(self, weight_file_path: Any, checkpoint_id: str) -> Path | None:
        """Resolve only the manager-owned, exact checkpoint artifact.

        Manifests may store a repo-root-relative ``weight_file_path`` (the live
        dir does), so a tool invoked from a different working directory would
        fail to find it and wrongly report NO_COMPATIBLE_WEIGHT_BLOB_MANIFEST.
        The blob is always written to ``model_dir/{checkpoint_id}.weights.npz``.
        Never follow a manifest-controlled external path: a stale stored path is
        tolerated only by resolving the canonical manager-owned filename.
        """
        del weight_file_path
        if not checkpoint_id or Path(checkpoint_id).name != checkpoint_id:
            return None
        candidate = self.model_dir / f"{checkpoint_id}.weights.npz"
        try:
            model_root = self.model_dir.resolve(strict=True)
            resolved = candidate.resolve(strict=True)
            if resolved.parent == model_root and resolved.is_file():
                return resolved
        except OSError:
            return None
        return None

    def _manifest_rows(
        self,
        *,
        input_dim: int | None = None,
        model_id: str | None = None,
        allowed_lineage_kinds: frozenset[str] | None = None,
        require_weight_blob: bool = False,
        verify_lineage_artifacts: bool = True,
    ) -> list[tuple[tuple[int, int, datetime, str], CheckpointManifest]]:
        self._manifest_scan_errors = []
        manifests: list[
            tuple[tuple[int, int, datetime, str], CheckpointManifest]
        ] = []
        try:
            ledger_records = self._read_causal_ledger_with_tail_recovery()
        except RuntimeError as exc:
            self._manifest_scan_errors.append(
                {"path": str(self._causal_ledger_path), "reason": str(exc)}
            )
            return []
        for path in self.model_dir.glob("v2_hybrid_ckpt_*.json"):
            if path.name.endswith(".tmp"):
                continue
            try:
                raw = _strict_json_loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                self._manifest_scan_errors.append(
                    {
                        "path": str(path),
                        "reason": str(exc) or type(exc).__name__,
                    }
                )
                continue
            if not isinstance(raw, dict) or any(
                field_name not in raw
                for field_name in (
                    "checkpoint_id",
                    "model_id",
                    "input_dim",
                    "weight_blob_written",
                )
            ):
                self._manifest_scan_errors.append(
                    {"path": str(path), "reason": "CORE_MANIFEST_FIELDS_MISSING"}
                )
                continue
            try:
                raw_input_dim = _manifest_int(
                    raw.get("input_dim"), field_name="input_dim"
                )
                if raw_input_dim <= 0:
                    raise ValueError("input_dim_not_positive")
                raw_evidence = raw.get("checkpoint_evidence")
                _verify_checkpoint_feature_abi_evidence(
                    input_dim=raw_input_dim,
                    evidence=(dict(raw_evidence) if isinstance(raw_evidence, dict) else {}),
                )
                if not isinstance(raw.get("checkpoint_id"), str) or not str(
                    raw.get("checkpoint_id")
                ):
                    raise ValueError("checkpoint_id_not_string")
                if str(raw.get("checkpoint_id")) != path.stem:
                    raise ValueError("checkpoint_id_filename_mismatch")
                if not isinstance(raw.get("model_id"), str) or not str(
                    raw.get("model_id")
                ):
                    raise ValueError("model_id_not_string")
                if not isinstance(raw.get("weight_blob_written"), bool):
                    raise ValueError("weight_blob_written_not_boolean")
                checkpoint_generation = self._validate_causal_manifest(
                    raw,
                    ledger_records=ledger_records,
                    verify_lineage_artifacts=verify_lineage_artifacts,
                )
                generated_utc = _strict_generated_utc(
                    raw.get("generated_utc"),
                    allow_future_after_clock_rollback=checkpoint_generation > 0,
                )
                calibration_sample = _manifest_int(
                    raw.get("confidence_calibration_sample") or 0,
                    field_name="confidence_calibration_sample",
                )
                calibration_validation_rows = _manifest_int(
                    raw.get("confidence_calibration_validation_rows_used") or 0,
                    field_name="confidence_calibration_validation_rows_used",
                )
                calibration_long_sample = _manifest_int(
                    raw.get("confidence_calibration_long_sample") or 0,
                    field_name="confidence_calibration_long_sample",
                )
                calibration_short_sample = _manifest_int(
                    raw.get("confidence_calibration_short_sample") or 0,
                    field_name="confidence_calibration_short_sample",
                )
                for count in (
                    calibration_sample,
                    calibration_validation_rows,
                    calibration_long_sample,
                    calibration_short_sample,
                ):
                    if count < 0:
                        raise ValueError("checkpoint_manifest_negative_count")
                head_actions_raw = raw.get("confidence_head_actions") or ()
                consumed_keys_raw = raw.get("consumed_ppo_update_keys") or ()
                if not isinstance(head_actions_raw, list | tuple):
                    raise ValueError("confidence_head_actions_not_sequence")
                if not isinstance(consumed_keys_raw, list | tuple):
                    raise ValueError("consumed_ppo_update_keys_not_sequence")
            except (TypeError, ValueError, OverflowError) as exc:
                self._manifest_scan_errors.append(
                    {
                        "path": str(path),
                        "reason": str(exc) or type(exc).__name__,
                    }
                )
                continue
            if input_dim is not None and raw_input_dim != int(input_dim):
                continue
            if model_id is not None and str(raw.get("model_id") or "") != model_id:
                continue
            lineage_kind = str(raw.get("lineage_kind") or "LEGACY_SERVING_CANDIDATE")
            if (
                allowed_lineage_kinds is not None
                and lineage_kind not in allowed_lineage_kinds
            ):
                continue
            manifests.append(
                (
                    (
                        1 if checkpoint_generation > 0 else 0,
                        checkpoint_generation,
                        (
                            datetime.min.replace(tzinfo=UTC)
                            if checkpoint_generation > 0
                            else generated_utc
                        ),
                        str(raw["checkpoint_id"]),
                    ),
                    CheckpointManifest(
                        checkpoint_id=str(raw.get("checkpoint_id") or path.stem),
                        checkpoint_source=str(raw.get("checkpoint_source") or CHECKPOINT_SOURCE),
                        path=str(raw.get("path") or path),
                        generated_utc=str(raw.get("generated_utc") or ""),
                        model_id=str(raw.get("model_id") or ""),
                        input_dim=raw_input_dim,
                        device=str(raw.get("device") or "unknown"),
                        cuda_active=bool(raw.get("cuda_active")),
                        weight_blob_written=bool(raw.get("weight_blob_written")),
                        weight_file_path=raw.get("weight_file_path"),
                        weight_file_format=raw.get("weight_file_format"),
                        weight_file_size_bytes=raw.get("weight_file_size_bytes"),
                        confidence_calibration_fitted=bool(
                            raw.get("confidence_calibration_fitted", False)
                        ),
                        confidence_calibration_temperature=raw.get(
                            "confidence_calibration_temperature"
                        ),
                        confidence_calibration_sample=calibration_sample,
                        confidence_calibration_reason=raw.get(
                            "confidence_calibration_reason"
                        ),
                        confidence_calibration_fit_partition=raw.get(
                            "confidence_calibration_fit_partition"
                        ),
                        confidence_calibration_validation_rows_used=(
                            calibration_validation_rows
                        ),
                        confidence_calibration_label_semantics=raw.get(
                            "confidence_calibration_label_semantics"
                        ),
                        confidence_head_schema_version=raw.get(
                            "confidence_head_schema_version"
                        ),
                        confidence_head_actions=tuple(
                            str(action)
                            for action in head_actions_raw
                        ),
                        confidence_calibration_long_sample=calibration_long_sample,
                        confidence_calibration_short_sample=calibration_short_sample,
                        confidence_calibration_model_parameter_fingerprint=raw.get(
                            "confidence_calibration_model_parameter_fingerprint"
                        ),
                        confidence_calibration_row_digest=raw.get(
                            "confidence_calibration_row_digest"
                        ),
                        confidence_calibration_state=(
                            dict(raw.get("confidence_calibration_state"))
                            if isinstance(
                                raw.get("confidence_calibration_state"), dict
                            )
                            else {}
                        ),
                        model_parameter_fingerprint=raw.get(
                            "model_parameter_fingerprint"
                        ),
                        weight_file_sha256=raw.get("weight_file_sha256"),
                        lineage_kind=str(
                            raw.get("lineage_kind") or "LEGACY_SERVING_CANDIDATE"
                        ),
                        parent_checkpoint_id=raw.get("parent_checkpoint_id"),
                        parent_policy_fingerprint=raw.get(
                            "parent_policy_fingerprint"
                        ),
                        consumed_ppo_update_keys=tuple(
                            str(value)
                            for value in consumed_keys_raw
                        ),
                        training_partition_digest=raw.get(
                            "training_partition_digest"
                        ),
                        checkpoint_evidence_schema_version=raw.get(
                            "checkpoint_evidence_schema_version"
                        ),
                        checkpoint_evidence=(
                            dict(raw.get("checkpoint_evidence"))
                            if isinstance(raw.get("checkpoint_evidence"), dict)
                            else {}
                        ),
                        checkpoint_evidence_digest=raw.get(
                            "checkpoint_evidence_digest"
                        ),
                        checkpoint_causal_order_schema_version=raw.get(
                            "checkpoint_causal_order_schema_version"
                        ),
                        checkpoint_causal_store=raw.get(
                            "checkpoint_causal_store"
                        ),
                        checkpoint_generation=checkpoint_generation,
                        parent_checkpoint_generation=(
                            raw.get("parent_checkpoint_generation")
                            if checkpoint_generation > 0
                            else None
                        ),
                        checkpoint_semantic_digest=raw.get(
                            "checkpoint_semantic_digest"
                        ),
                        checkpoint_causal_record_digest=raw.get(
                            "checkpoint_causal_record_digest"
                        ),
                        external_deserialization_used=bool(
                            raw.get("external_deserialization_used", False)
                        ),
                    ),
                )
            )
        if require_weight_blob:
            manifests = [
                (sort_key, manifest)
                for sort_key, manifest in manifests
                if manifest.weight_blob_written
                and self._resolve_weight_path(
                    manifest.weight_file_path, manifest.checkpoint_id
                )
                is not None
            ]
        manifests.sort(key=lambda item: item[0], reverse=True)
        return manifests

    def latest_manifest(
        self,
        *,
        input_dim: int | None = None,
        model_id: str | None = None,
        allowed_lineage_kinds: frozenset[str] | None = None,
        verify_lineage_artifacts: bool = True,
    ) -> CheckpointManifest | None:
        manifests = self._manifest_rows(
            input_dim=input_dim,
            model_id=model_id,
            allowed_lineage_kinds=allowed_lineage_kinds,
            verify_lineage_artifacts=verify_lineage_artifacts,
        )
        if not manifests:
            return None
        return manifests[0][1]

    def manifests(
        self,
        *,
        input_dim: int | None = None,
        model_id: str | None = None,
        allowed_lineage_kinds: frozenset[str] | None = None,
        require_weight_blob: bool = False,
        verify_lineage_artifacts: bool = True,
    ) -> tuple[CheckpointManifest, ...]:
        """Return every matching manifest, newest first, or fail on scan damage.

        ``verify_lineage_artifacts=False`` is a metadata-only preflight for a
        caller that must establish an external admission contract before any
        NPZ is inspected. Such a caller must subsequently use
        :meth:`verify_manifest_artifact` and an exact-ID guarded load.
        """
        rows = self._manifest_rows(
            input_dim=input_dim,
            model_id=model_id,
            allowed_lineage_kinds=allowed_lineage_kinds,
            require_weight_blob=require_weight_blob,
            verify_lineage_artifacts=verify_lineage_artifacts,
        )
        if self._manifest_scan_errors:
            raise RuntimeError("checkpoint_manifest_scan_invalid")
        return tuple(manifest for _mtime, manifest in rows)

    def verify_manifest_artifact(
        self,
        manifest: CheckpointManifest,
    ) -> dict[str, Any]:
        """Verify one durable checkpoint without mutating a serving model.

        Startup reconciliation must inspect every optimizer-attempt artifact,
        including historical candidates which are not the latest checkpoint.
        Loading each artifact into the serving model would both mutate policy
        state and make recovery order-dependent.  This verifier reads only the
        explicit no-pickle NPZ representation and binds its bytes, parameter
        semantics, calibration, evidence, lineage, and content-addressed ID.
        """
        reasons: list[str] = []
        resolved_weight_path = self._resolve_weight_path(
            manifest.weight_file_path, manifest.checkpoint_id
        )
        if manifest.checkpoint_source != CHECKPOINT_SOURCE:
            reasons.append("CHECKPOINT_SOURCE_INVALID")
        if manifest.external_deserialization_used:
            reasons.append("EXTERNAL_DESERIALIZATION_NOT_ALLOWED")
        if not manifest.weight_blob_written:
            reasons.append("WEIGHT_BLOB_NOT_WRITTEN")
        if manifest.weight_file_format != "npz":
            reasons.append("WEIGHT_FORMAT_NOT_SAFE_NPZ")
        if resolved_weight_path is None or not resolved_weight_path.is_file():
            reasons.append("WEIGHT_BLOB_PATH_UNRESOLVED")
        elif resolved_weight_path.suffix != ".npz":
            reasons.append("WEIGHT_BLOB_SUFFIX_NOT_NPZ")

        observed_sha256: str | None = None
        observed_size_bytes: int | None = None
        semantics: dict[str, Any] = {}
        if resolved_weight_path is not None and resolved_weight_path.is_file():
            try:
                with _private_checkpoint_copy(
                    resolved_weight_path,
                    require_sealed=(
                        _CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD
                        in manifest.checkpoint_evidence
                    ),
                ) as snapshot:
                    observed_sha256 = snapshot.sha256
                    observed_size_bytes = snapshot.size_bytes
                    try:
                        feature_abi_binding = manifest.checkpoint_evidence.get(
                            _CHECKPOINT_FEATURE_ABI_EVIDENCE_FIELD
                        )
                        if feature_abi_binding is None:
                            semantics = _safe_npz_semantics(
                                snapshot.stream,
                                model_id=manifest.model_id,
                            )
                        else:
                            semantics = _safe_npz_semantics(
                                snapshot.stream,
                                model_id=manifest.model_id,
                                checkpoint_feature_abi_binding=(
                                    feature_abi_binding
                                ),
                            )
                    except Exception as exc:  # noqa: BLE001 - fail-closed evidence
                        reasons.append(
                            "WEIGHT_BLOB_SEMANTIC_READ_FAILED:"
                            f"{type(exc).__name__}"
                        )
            except OSError:
                reasons.append("WEIGHT_BLOB_HASH_FAILED")
            expected_sha256 = str(manifest.weight_file_sha256 or "")
            if len(expected_sha256) != 64:
                reasons.append("WEIGHT_BLOB_SHA256_MISSING")
            elif observed_sha256 != expected_sha256:
                reasons.append("WEIGHT_BLOB_SHA256_MISMATCH")
            if manifest.weight_file_size_bytes is None:
                reasons.append("WEIGHT_BLOB_SIZE_MISSING")
            else:
                try:
                    expected_size = _manifest_int(
                        manifest.weight_file_size_bytes,
                        field_name="weight_file_size_bytes",
                    )
                    if (
                        expected_size <= 0
                        or observed_size_bytes != expected_size
                    ):
                        reasons.append("WEIGHT_BLOB_SIZE_MISMATCH")
                except (OSError, TypeError, ValueError, OverflowError):
                    reasons.append("WEIGHT_BLOB_SIZE_INVALID")

        parameter_fingerprint = str(
            semantics.get("model_parameter_fingerprint") or ""
        )
        manifest_fingerprint = str(manifest.model_parameter_fingerprint or "")
        if len(manifest_fingerprint) != 64:
            reasons.append("MODEL_PARAMETER_FINGERPRINT_MISSING")
        elif parameter_fingerprint != manifest_fingerprint:
            reasons.append("MODEL_PARAMETER_FINGERPRINT_MISMATCH")
        if semantics:
            if semantics.get("input_dim") != manifest.input_dim:
                reasons.append("CHECKPOINT_INPUT_DIM_MISMATCH")
            if (
                semantics.get("confidence_head_schema_version")
                != CONFIDENCE_HEAD_SCHEMA_VERSION
            ):
                reasons.append("CONFIDENCE_HEAD_SCHEMA_MISMATCH")
            if tuple(semantics.get("confidence_head_actions") or ()) != tuple(
                CONFIDENCE_HEAD_ACTIONS
            ):
                reasons.append("CONFIDENCE_HEAD_ACTIONS_MISMATCH")
            if (
                semantics.get("confidence_calibration_state")
                != manifest.confidence_calibration_state
            ):
                reasons.append("CONFIDENCE_CALIBRATION_STATE_MISMATCH")

        evidence = dict(manifest.checkpoint_evidence)
        if not _checkpoint_feature_abi_matches_npz(
            input_dim=manifest.input_dim,
            evidence=evidence,
            safe_semantics=semantics,
        ):
            reasons.append("CHECKPOINT_FEATURE_ABI_BINDING_MISMATCH")
        evidence_digest = str(manifest.checkpoint_evidence_digest or "")
        if (
            manifest.checkpoint_evidence_schema_version
            != CHECKPOINT_EVIDENCE_SCHEMA_VERSION
        ):
            reasons.append("CHECKPOINT_EVIDENCE_SCHEMA_MISMATCH")
        if len(evidence_digest) != 64 or not evidence:
            reasons.append("CHECKPOINT_EVIDENCE_MISSING")
        else:
            try:
                observed_evidence_digest = _canonical_digest(evidence)
            except (TypeError, ValueError, OverflowError):
                observed_evidence_digest = ""
            if observed_evidence_digest != evidence_digest:
                reasons.append("CHECKPOINT_EVIDENCE_DIGEST_MISMATCH")
        evidence_bindings: tuple[tuple[str, Any], ...] = (
            ("schema_version", CHECKPOINT_EVIDENCE_SCHEMA_VERSION),
            ("lineage_kind", manifest.lineage_kind),
            ("parent_checkpoint_id", manifest.parent_checkpoint_id),
            ("parent_policy_fingerprint", manifest.parent_policy_fingerprint),
            (
                "consumed_ppo_update_keys",
                list(manifest.consumed_ppo_update_keys),
            ),
            ("training_partition_digest", manifest.training_partition_digest),
        )
        for field_name, expected in evidence_bindings:
            if evidence.get(field_name) != expected:
                reasons.append(f"CHECKPOINT_EVIDENCE_{field_name.upper()}_MISMATCH")
        if manifest.checkpoint_generation > 0:
            causal_evidence_bindings: tuple[tuple[str, Any], ...] = (
                (
                    "checkpoint_causal_order_schema_version",
                    manifest.checkpoint_causal_order_schema_version,
                ),
                (
                    "checkpoint_causal_store",
                    manifest.checkpoint_causal_store,
                ),
                ("checkpoint_generation", manifest.checkpoint_generation),
                (
                    "parent_checkpoint_generation",
                    manifest.parent_checkpoint_generation,
                ),
                ("checkpoint_semantic_digest", manifest.checkpoint_semantic_digest),
                (
                    "checkpoint_causal_record_digest",
                    manifest.checkpoint_causal_record_digest,
                ),
            )
            for field_name, expected in causal_evidence_bindings:
                if evidence.get(field_name) != expected:
                    reasons.append(
                        f"CHECKPOINT_EVIDENCE_{field_name.upper()}_MISMATCH"
                    )
            try:
                observed_generation = self._validate_causal_manifest(
                    dict(manifest.__dict__),
                    ledger_records=self._read_causal_ledger_with_tail_recovery(),
                )
                if observed_generation != manifest.checkpoint_generation:
                    raise ValueError("checkpoint_generation_mismatch")
            except (RuntimeError, TypeError, ValueError, OverflowError):
                reasons.append("CHECKPOINT_CAUSAL_ORDER_BINDING_INVALID")

        checkpoint_identity_verified = False
        if manifest_fingerprint and evidence_digest and manifest.confidence_calibration_state:
            try:
                calibration_fingerprint = _canonical_digest(
                    manifest.confidence_calibration_state
                )
                state_fingerprint = _canonical_digest(
                    {
                        "confidence_calibration_fingerprint": calibration_fingerprint,
                        "checkpoint_evidence_digest": evidence_digest,
                    }
                )
                expected_checkpoint_id = (
                    f"v2_hybrid_ckpt_{manifest.model_id[-8:]}_"
                    f"{manifest_fingerprint[:16]}_{state_fingerprint[:12]}"
                )
                checkpoint_identity_verified = (
                    manifest.checkpoint_id == expected_checkpoint_id
                )
            except (TypeError, ValueError, OverflowError):
                checkpoint_identity_verified = False
        if not checkpoint_identity_verified:
            reasons.append("CHECKPOINT_CONTENT_IDENTITY_MISMATCH")

        verified = not reasons
        return {
            "checkpoint_artifact_verified": verified,
            "latest_checkpoint_loadable": verified,
            "model_state_restored": False,
            "verification_is_non_mutating": True,
            "checkpoint_id": manifest.checkpoint_id,
            "checkpoint_path": manifest.path,
            "weight_file_path": manifest.weight_file_path,
            "resolved_weight_file_path": (
                str(resolved_weight_path) if resolved_weight_path else None
            ),
            "weight_file_sha256": manifest.weight_file_sha256,
            "observed_weight_file_sha256": observed_sha256,
            "weight_file_sha256_verified": bool(
                observed_sha256
                and observed_sha256 == manifest.weight_file_sha256
            ),
            "model_id": manifest.model_id,
            "model_parameter_fingerprint": parameter_fingerprint or None,
            "model_parameter_fingerprint_verified": bool(
                parameter_fingerprint
                and parameter_fingerprint == manifest.model_parameter_fingerprint
            ),
            "lineage_kind": manifest.lineage_kind,
            "parent_checkpoint_id": manifest.parent_checkpoint_id,
            "checkpoint_causal_order_schema_version": (
                manifest.checkpoint_causal_order_schema_version
            ),
            "checkpoint_causal_store": manifest.checkpoint_causal_store,
            "checkpoint_generation": manifest.checkpoint_generation,
            "parent_checkpoint_generation": manifest.parent_checkpoint_generation,
            "checkpoint_semantic_digest": manifest.checkpoint_semantic_digest,
            "checkpoint_causal_record_digest": (
                manifest.checkpoint_causal_record_digest
            ),
            "parent_policy_fingerprint": manifest.parent_policy_fingerprint,
            "consumed_ppo_update_keys": list(manifest.consumed_ppo_update_keys),
            "training_partition_digest": manifest.training_partition_digest,
            "checkpoint_evidence": evidence,
            "checkpoint_evidence_digest": manifest.checkpoint_evidence_digest,
            "checkpoint_evidence_verified": bool(
                evidence_digest and "CHECKPOINT_EVIDENCE_DIGEST_MISMATCH" not in reasons
            ),
            "checkpoint_identity_verified": checkpoint_identity_verified,
            "artifact_verification_rejection_reasons": tuple(sorted(set(reasons))),
            "load_status": (
                "VERIFIED_WITHOUT_MODEL_MUTATION"
                if verified
                else "ARTIFACT_VERIFICATION_FAILED"
            ),
        }

    def load_latest_weights(
        self,
        model: V2HybridPolicyModel,
        *,
        allowed_lineage_kinds: frozenset[str] | None = None,
        expected_checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        # Report the newest same-shape metadata row for operator visibility, but
        # only deserialize a weight artifact with the exact architecture/model ID.
        pre_deserialization_exact_id_guard = expected_checkpoint_id is not None
        latest_metadata_manifest = self.latest_manifest(
            input_dim=model.input_dim,
            allowed_lineage_kinds=allowed_lineage_kinds,
            verify_lineage_artifacts=(
                not pre_deserialization_exact_id_guard
            ),
        )
        manifest_rows = self._manifest_rows(
            input_dim=model.input_dim,
            model_id=model.model_id,
            allowed_lineage_kinds=allowed_lineage_kinds,
            require_weight_blob=True,
            verify_lineage_artifacts=(
                not pre_deserialization_exact_id_guard
            ),
        )
        if self._manifest_scan_errors:
            evidence_digest_invalid = any(
                error.get("reason") == "checkpoint_evidence_digest_mismatch"
                for error in self._manifest_scan_errors
            )
            return {
                "checkpoint_manifest_exists": True,
                "checkpoint_id": None,
                "weight_blob_written": False,
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "checkpoint_evidence_verified": False,
                "manifest_scan_errors": list(self._manifest_scan_errors),
                "load_status": (
                    "CHECKPOINT_EVIDENCE_DIGEST_MISMATCH"
                    if evidence_digest_invalid
                    else "CHECKPOINT_MANIFEST_SCAN_INVALID"
                ),
            }
        if expected_checkpoint_id is None:
            manifest = manifest_rows[0][1] if manifest_rows else None
        else:
            # An external durable activation record may deliberately point to
            # an older verified checkpoint while a newer artifact is staged but
            # not yet activated. Exact-ID loads must select that bound manifest,
            # not compare the requested ID only against the newest row.
            manifest = next(
                (
                    candidate
                    for _sort_key, candidate in manifest_rows
                    if candidate.checkpoint_id == expected_checkpoint_id
                ),
                None,
            )
        if expected_checkpoint_id is not None and (
            type(expected_checkpoint_id) is not str
            or not expected_checkpoint_id
            or expected_checkpoint_id != expected_checkpoint_id.strip()
        ):
            return {
                "checkpoint_manifest_exists": manifest is not None,
                "checkpoint_id": manifest.checkpoint_id if manifest else None,
                "expected_checkpoint_id": expected_checkpoint_id,
                "weight_blob_written": False,
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "load_status": "EXPECTED_CHECKPOINT_ID_INVALID",
            }
        if manifest is None:
            return {
                "checkpoint_manifest_exists": latest_metadata_manifest is not None,
                "checkpoint_id": (
                    latest_metadata_manifest.checkpoint_id
                    if latest_metadata_manifest
                    else None
                ),
                "weight_blob_written": False,
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "expected_checkpoint_id": expected_checkpoint_id,
                "load_status": (
                    "EXPECTED_CHECKPOINT_ID_NOT_AVAILABLE"
                    if expected_checkpoint_id is not None
                    else "NO_COMPATIBLE_WEIGHT_BLOB_MANIFEST"
                ),
            }
        if expected_checkpoint_id is not None:
            try:
                observed_generation = self._validate_causal_manifest(
                    dict(manifest.__dict__),
                    ledger_records=self._read_causal_ledger_with_tail_recovery(),
                    verify_lineage_artifacts=True,
                )
                if observed_generation != manifest.checkpoint_generation:
                    raise ValueError("checkpoint_generation_mismatch")
            except (OSError, RuntimeError, TypeError, ValueError, OverflowError):
                return {
                    "checkpoint_manifest_exists": True,
                    "checkpoint_id": manifest.checkpoint_id,
                    "expected_checkpoint_id": expected_checkpoint_id,
                    "weight_blob_written": bool(manifest.weight_blob_written),
                    "latest_checkpoint_loadable": False,
                    "model_state_restored": False,
                    "load_status": "EXPECTED_CHECKPOINT_CAUSAL_LINEAGE_INVALID",
                }
        resolved_weight_path = self._resolve_weight_path(
            manifest.weight_file_path, manifest.checkpoint_id
        )
        if resolved_weight_path is None:
            return {
                "checkpoint_manifest_exists": True,
                "checkpoint_id": manifest.checkpoint_id,
                "weight_blob_written": True,
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "load_status": "WEIGHT_BLOB_PATH_UNRESOLVED",
            }
        if manifest.checkpoint_evidence_digest:
            if (
                manifest.checkpoint_evidence_schema_version
                != CHECKPOINT_EVIDENCE_SCHEMA_VERSION
            ):
                return {
                    "checkpoint_manifest_exists": True,
                    "checkpoint_id": manifest.checkpoint_id,
                    "latest_checkpoint_loadable": False,
                    "model_state_restored": False,
                    "checkpoint_evidence_verified": False,
                    "load_status": "CHECKPOINT_EVIDENCE_SCHEMA_MISMATCH",
                }
            observed_evidence_digest = hashlib.sha256(
                json.dumps(
                    manifest.checkpoint_evidence,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if observed_evidence_digest != manifest.checkpoint_evidence_digest:
                return {
                    "checkpoint_manifest_exists": True,
                    "checkpoint_id": manifest.checkpoint_id,
                    "latest_checkpoint_loadable": False,
                    "model_state_restored": False,
                    "checkpoint_evidence_verified": False,
                    "load_status": "CHECKPOINT_EVIDENCE_DIGEST_MISMATCH",
                }
            if not manifest.confidence_calibration_state:
                return {
                    "checkpoint_manifest_exists": True,
                    "checkpoint_id": manifest.checkpoint_id,
                    "latest_checkpoint_loadable": False,
                    "model_state_restored": False,
                    "checkpoint_evidence_verified": True,
                    "checkpoint_identity_verified": False,
                    "load_status": "CHECKPOINT_CALIBRATION_STATE_BINDING_MISSING",
                }
            calibration_fingerprint = hashlib.sha256(
                json.dumps(
                    manifest.confidence_calibration_state,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            checkpoint_state_fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "confidence_calibration_fingerprint": calibration_fingerprint,
                        "checkpoint_evidence_digest": (
                            manifest.checkpoint_evidence_digest
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            expected_checkpoint_id = (
                f"v2_hybrid_ckpt_{manifest.model_id[-8:]}_"
                f"{str(manifest.model_parameter_fingerprint or '')[:16]}_"
                f"{checkpoint_state_fingerprint[:12]}"
            )
            if (
                len(str(manifest.model_parameter_fingerprint or "")) != 64
                or manifest.checkpoint_id != expected_checkpoint_id
            ):
                return {
                    "checkpoint_manifest_exists": True,
                    "checkpoint_id": manifest.checkpoint_id,
                    "latest_checkpoint_loadable": False,
                    "model_state_restored": False,
                    "checkpoint_evidence_verified": True,
                    "checkpoint_identity_verified": False,
                    "load_status": "CHECKPOINT_CONTENT_IDENTITY_MISMATCH",
                }
            if manifest.model_id != model.model_id:
                return {
                    "checkpoint_manifest_exists": True,
                    "checkpoint_id": manifest.checkpoint_id,
                    "latest_checkpoint_loadable": False,
                    "model_state_restored": False,
                    "checkpoint_evidence_verified": True,
                    "checkpoint_identity_verified": True,
                    "load_status": "CHECKPOINT_MODEL_ARCHITECTURE_ID_MISMATCH",
                }
        model_state_before = model._mutable_state_snapshot()
        private_load = _load_private_checkpoint_copy(
            source_path=resolved_weight_path,
            manifest=manifest,
            model=model,
        )
        if private_load.get("private_checkpoint_copy_verified") is not True:
            model._restore_mutable_state_snapshot(model_state_before)
            return {
                "checkpoint_manifest_exists": True,
                "checkpoint_id": manifest.checkpoint_id,
                "weight_blob_written": True,
                "weight_file_path": manifest.weight_file_path,
                **private_load,
            }
        loaded = dict(private_load["loaded"])
        from .on_policy_behavior import model_parameter_fingerprint

        try:
            restored_fingerprint = model_parameter_fingerprint(model)
        except Exception as exc:  # noqa: BLE001 - restore before fail-closed return
            model._restore_mutable_state_snapshot(model_state_before)
            return {
                "checkpoint_manifest_exists": True,
                "checkpoint_id": manifest.checkpoint_id,
                "weight_blob_written": True,
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "model_parameter_fingerprint_verified": False,
                "load_error_reason": str(exc) or type(exc).__name__,
                "load_status": "MODEL_PARAMETER_FINGERPRINT_UNAVAILABLE",
            }
        if (
            manifest.model_parameter_fingerprint
            and restored_fingerprint != manifest.model_parameter_fingerprint
        ):
            model._restore_mutable_state_snapshot(model_state_before)
            return {
                "checkpoint_manifest_exists": True,
                "checkpoint_id": manifest.checkpoint_id,
                "weight_blob_written": True,
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "weight_file_sha256_verified": bool(manifest.weight_file_sha256),
                "model_parameter_fingerprint_verified": False,
                "load_status": "MODEL_PARAMETER_FINGERPRINT_MISMATCH",
            }
        checkpoint_identity_verified = False
        if manifest.checkpoint_evidence_digest:
            calibration_fingerprint = hashlib.sha256(
                json.dumps(
                    model.confidence_calibration_state,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            checkpoint_state_fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "confidence_calibration_fingerprint": calibration_fingerprint,
                        "checkpoint_evidence_digest": (
                            manifest.checkpoint_evidence_digest
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            expected_checkpoint_id = (
                f"v2_hybrid_ckpt_{model.model_id[-8:]}_"
                f"{restored_fingerprint[:16]}_{checkpoint_state_fingerprint[:12]}"
            )
            if (
                manifest.model_id != model.model_id
                or manifest.checkpoint_id != expected_checkpoint_id
            ):
                model._restore_mutable_state_snapshot(model_state_before)
                return {
                    "checkpoint_manifest_exists": True,
                    "checkpoint_id": manifest.checkpoint_id,
                    "latest_checkpoint_loadable": False,
                    "model_state_restored": False,
                    "weight_file_sha256_verified": bool(
                        manifest.weight_file_sha256
                    ),
                    "model_parameter_fingerprint_verified": True,
                    "checkpoint_evidence_verified": True,
                    "checkpoint_identity_verified": False,
                    "load_status": "CHECKPOINT_CONTENT_IDENTITY_MISMATCH",
                }
            checkpoint_identity_verified = True
        return {
            "checkpoint_manifest_exists": True,
            "checkpoint_id": manifest.checkpoint_id,
            "latest_metadata_checkpoint_id": (
                latest_metadata_manifest.checkpoint_id
                if latest_metadata_manifest
                else manifest.checkpoint_id
            ),
            "metadata_only_manifest_ignored_for_weight_load": bool(
                latest_metadata_manifest
                and latest_metadata_manifest.checkpoint_id != manifest.checkpoint_id
            ),
            "weight_blob_written": True,
            "weight_file_path": manifest.weight_file_path,
            "resolved_weight_file_path": str(resolved_weight_path),
            "weight_file_format": manifest.weight_file_format,
            "weight_file_size_bytes": manifest.weight_file_size_bytes,
            "safe_weight_format": manifest.weight_file_format == "npz",
            "weight_file_sha256": manifest.weight_file_sha256,
            "weight_file_sha256_verified": bool(manifest.weight_file_sha256),
            "private_checkpoint_copy_verified": True,
            "private_checkpoint_source_open_count": private_load[
                "private_checkpoint_source_open_count"
            ],
            "private_checkpoint_copy_sha256": private_load[
                "private_checkpoint_copy_sha256"
            ],
            "private_checkpoint_copy_size_bytes": private_load[
                "private_checkpoint_copy_size_bytes"
            ],
            "model_parameter_fingerprint": restored_fingerprint,
            "model_parameter_fingerprint_verified": bool(
                manifest.model_parameter_fingerprint
                and restored_fingerprint == manifest.model_parameter_fingerprint
            ),
            "lineage_kind": manifest.lineage_kind,
            "parent_checkpoint_id": manifest.parent_checkpoint_id,
            "checkpoint_causal_order_schema_version": (
                manifest.checkpoint_causal_order_schema_version
            ),
            "checkpoint_causal_store": manifest.checkpoint_causal_store,
            "checkpoint_generation": manifest.checkpoint_generation,
            "parent_checkpoint_generation": manifest.parent_checkpoint_generation,
            "checkpoint_semantic_digest": manifest.checkpoint_semantic_digest,
            "checkpoint_causal_record_digest": (
                manifest.checkpoint_causal_record_digest
            ),
            "parent_policy_fingerprint": manifest.parent_policy_fingerprint,
            "consumed_ppo_update_keys": list(
                manifest.consumed_ppo_update_keys
            ),
            "training_partition_digest": manifest.training_partition_digest,
            "checkpoint_evidence_schema_version": (
                manifest.checkpoint_evidence_schema_version
            ),
            "checkpoint_evidence": dict(manifest.checkpoint_evidence),
            "checkpoint_evidence_digest": manifest.checkpoint_evidence_digest,
            "checkpoint_evidence_verified": bool(
                manifest.checkpoint_evidence_digest
            ),
            "checkpoint_identity_verified": checkpoint_identity_verified,
            "checkpoint_confidence_head_compatible": True,
            "pre_deserialization_semantic_verification": True,
            "latest_checkpoint_loadable": True,
            "model_state_restored": bool(loaded.get("model_state_restored")),
            "optimizer_state_restored_or_intentionally_not_required": True,
            "optimizer_state_note": (
                "AdamW optimizer is intentionally recreated each cycle; "
                "model weights persist."
            ),
            "confidence_calibration_fitted": loaded.get(
                "confidence_calibration_fitted"
            ),
            "confidence_calibration_reason": loaded.get(
                "confidence_calibration_reason"
            ),
            "confidence_calibration_state": dict(
                model.confidence_calibration_state
            ),
            "load_status": "LOADED",
        }

    def status(self, manifest: CheckpointManifest | None = None) -> dict[str, Any]:
        return {
            "checkpoint_source": CHECKPOINT_SOURCE,
            "checkpoint_id": manifest.checkpoint_id if manifest else None,
            "checkpoint_manifest_path": manifest.path if manifest else None,
            "weight_blob_written": manifest.weight_blob_written if manifest else False,
            "weight_file_path": manifest.weight_file_path if manifest else None,
            "weight_file_format": manifest.weight_file_format if manifest else None,
            "weight_file_size_bytes": manifest.weight_file_size_bytes if manifest else None,
            "confidence_calibration_fitted": (
                manifest.confidence_calibration_fitted if manifest else False
            ),
            "confidence_calibration_temperature": (
                manifest.confidence_calibration_temperature if manifest else None
            ),
            "confidence_calibration_sample": (
                manifest.confidence_calibration_sample if manifest else 0
            ),
            "confidence_calibration_reason": (
                manifest.confidence_calibration_reason if manifest else None
            ),
            "confidence_calibration_fit_partition": (
                manifest.confidence_calibration_fit_partition if manifest else None
            ),
            "confidence_calibration_validation_rows_used": (
                manifest.confidence_calibration_validation_rows_used if manifest else 0
            ),
            "confidence_calibration_label_semantics": (
                manifest.confidence_calibration_label_semantics if manifest else None
            ),
            "confidence_head_schema_version": (
                manifest.confidence_head_schema_version if manifest else None
            ),
            "confidence_head_actions": (
                list(manifest.confidence_head_actions) if manifest else []
            ),
            "confidence_calibration_long_sample": (
                manifest.confidence_calibration_long_sample if manifest else 0
            ),
            "confidence_calibration_short_sample": (
                manifest.confidence_calibration_short_sample if manifest else 0
            ),
            "confidence_calibration_model_parameter_fingerprint": (
                manifest.confidence_calibration_model_parameter_fingerprint
                if manifest
                else None
            ),
            "confidence_calibration_row_digest": (
                manifest.confidence_calibration_row_digest if manifest else None
            ),
            "confidence_calibration_state": (
                dict(manifest.confidence_calibration_state) if manifest else {}
            ),
            "model_parameter_fingerprint": (
                manifest.model_parameter_fingerprint if manifest else None
            ),
            "weight_file_sha256": manifest.weight_file_sha256 if manifest else None,
            "lineage_kind": manifest.lineage_kind if manifest else None,
            "parent_checkpoint_id": manifest.parent_checkpoint_id if manifest else None,
            "checkpoint_causal_order_schema_version": (
                manifest.checkpoint_causal_order_schema_version
                if manifest
                else None
            ),
            "checkpoint_causal_store": (
                manifest.checkpoint_causal_store if manifest else None
            ),
            "checkpoint_generation": (
                manifest.checkpoint_generation if manifest else 0
            ),
            "parent_checkpoint_generation": (
                manifest.parent_checkpoint_generation if manifest else None
            ),
            "checkpoint_semantic_digest": (
                manifest.checkpoint_semantic_digest if manifest else None
            ),
            "checkpoint_causal_record_digest": (
                manifest.checkpoint_causal_record_digest if manifest else None
            ),
            "parent_policy_fingerprint": (
                manifest.parent_policy_fingerprint if manifest else None
            ),
            "consumed_ppo_update_keys": (
                list(manifest.consumed_ppo_update_keys) if manifest else []
            ),
            "training_partition_digest": (
                manifest.training_partition_digest if manifest else None
            ),
            "checkpoint_evidence_schema_version": (
                manifest.checkpoint_evidence_schema_version if manifest else None
            ),
            "checkpoint_evidence": (
                dict(manifest.checkpoint_evidence) if manifest else {}
            ),
            "checkpoint_evidence_digest": (
                manifest.checkpoint_evidence_digest if manifest else None
            ),
            "safe_weight_format": (manifest.weight_file_format == "npz") if manifest else False,
            "external_deserialization_used": False,
            "torch_pickle_load_used": False,
            "operator_approval_required_for_external_blobs": True,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        }
