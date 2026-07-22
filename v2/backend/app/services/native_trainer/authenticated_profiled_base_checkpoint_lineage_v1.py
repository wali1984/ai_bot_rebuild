from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    stable_sha256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    CheckpointManifest,
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (
    VERIFIED_SERVING_LINEAGE,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    model_parameter_fingerprint,
)

AUTHENTICATED_PROFILED_BASE_CHECKPOINT_LINEAGE_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_base_checkpoint_lineage_v1"
)
AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_supervised_checkpoint_publication_v1"
)
AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE: Final = (
    "AUTHENTICATED_PROFILED_SUPERVISED_NON_SERVING_CANDIDATE"
)
AUTHENTICATED_PROFILED_SUPERVISED_LEDGER_DISPOSITION: Final = (
    "AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_PERSISTED"
)
_ALLOWED_BASE_LINEAGES: Final = frozenset({VERIFIED_SERVING_LINEAGE})
_RESULT_TOKEN = object()
_SEAL_KEY = secrets.token_bytes(32)
_SEAL_DOMAIN: Final = b"authenticated_profiled_base_checkpoint_lineage_v1\0"


class AuthenticatedProfiledBaseCheckpointLineageV1Error(RuntimeError):
    """Exact base-checkpoint loading or lineage revalidation failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise AuthenticatedProfiledBaseCheckpointLineageV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(cast(str, value)) == 64
        and all(character in "0123456789abcdef" for character in cast(str, value))
    )


def _canonical_json(value: object, *, reason: str) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        _fail(reason)
    if not encoded:
        _fail(reason)
    return encoded


def _checkpoint_evidence_sha256(value: object) -> str:
    if type(value) is not dict:
        _fail("PROFILED_BASE_LINEAGE_CHECKPOINT_EVIDENCE_INVALID")
    try:
        return stable_sha256(value)
    except Exception as exc:
        raise AuthenticatedProfiledBaseCheckpointLineageV1Error(
            "PROFILED_BASE_LINEAGE_CHECKPOINT_EVIDENCE_INVALID"
        ) from exc


def _calibration_sha256(model: V2HybridPolicyModel) -> str:
    if type(model) is not V2HybridPolicyModel:
        _fail("PROFILED_BASE_LINEAGE_MODEL_TYPE_INVALID")
    return hashlib.sha256(
        _canonical_json(
            model.confidence_calibration_state,
            reason="PROFILED_BASE_LINEAGE_CALIBRATION_INVALID",
        )
    ).hexdigest()


def _binding_material(values: dict[str, Any]) -> dict[str, Any]:
    names = (
        "schema_version",
        "checkpoint_id",
        "checkpoint_weight_sha256",
        "checkpoint_weight_size_bytes",
        "checkpoint_evidence_digest",
        "checkpoint_generation",
        "checkpoint_semantic_digest",
        "checkpoint_causal_record_digest",
        "lineage_kind",
        "model_id",
        "model_input_dim",
        "model_parameter_fingerprint",
        "confidence_calibration_sha256",
        "checkpoint_feature_abi_binding_sha256",
        "exact_checkpoint_load_receipt_sha256",
        "checkpoint_artifact_verified",
        "exact_checkpoint_loaded",
        "checkpoint_write_authorized",
        "serving_authorized",
        "trading_authorized",
    )
    return {name: values[name] for name in names}


def _seal(material: dict[str, Any], *, owner_ids: tuple[int, ...]) -> bytes:
    return hmac.new(
        _SEAL_KEY,
        _SEAL_DOMAIN
        + _canonical_json(
            {"material": material, "owner_ids": list(owner_ids)},
            reason="PROFILED_BASE_LINEAGE_SEAL_MATERIAL_INVALID",
        ),
        hashlib.sha256,
    ).digest()


def _exact_manifest(
    *,
    manager: V2HybridCheckpointManager,
    model: V2HybridPolicyModel,
    expected_checkpoint_id: str,
) -> CheckpointManifest:
    if (
        type(manager) is not V2HybridCheckpointManager
        or type(model) is not V2HybridPolicyModel
    ):
        _fail("PROFILED_BASE_LINEAGE_OWNER_TYPES_INVALID")
    if (
        type(expected_checkpoint_id) is not str
        or not expected_checkpoint_id
        or expected_checkpoint_id != expected_checkpoint_id.strip()
        or Path(expected_checkpoint_id).name != expected_checkpoint_id
    ):
        _fail("PROFILED_BASE_LINEAGE_CHECKPOINT_ID_INVALID")
    try:
        manifests = manager.manifests(
            input_dim=model.input_dim,
            model_id=model.model_id,
            require_weight_blob=True,
        )
    except Exception as exc:
        raise AuthenticatedProfiledBaseCheckpointLineageV1Error(
            "PROFILED_BASE_LINEAGE_MANIFEST_SCAN_FAILED"
        ) from exc
    matches = tuple(
        manifest
        for manifest in manifests
        if manifest.checkpoint_id == expected_checkpoint_id
    )
    if len(matches) != 1:
        _fail("PROFILED_BASE_LINEAGE_CHECKPOINT_NOT_EXACTLY_RESOLVED")
    manifest = matches[0]
    if manifest.lineage_kind not in _ALLOWED_BASE_LINEAGES:
        _fail("PROFILED_BASE_LINEAGE_KIND_OR_EVIDENCE_INVALID")
    return manifest


def _verification_valid(
    *,
    manifest: CheckpointManifest,
    verification: dict[str, Any],
) -> bool:
    required_true = (
        "checkpoint_artifact_verified",
        "latest_checkpoint_loadable",
        "verification_is_non_mutating",
        "weight_file_sha256_verified",
        "model_parameter_fingerprint_verified",
        "checkpoint_evidence_verified",
        "checkpoint_identity_verified",
    )
    return bool(
        all(verification.get(field_name) is True for field_name in required_true)
        and verification.get("model_state_restored") is False
        and verification.get("checkpoint_id") == manifest.checkpoint_id
        and verification.get("weight_file_sha256") == manifest.weight_file_sha256
        and verification.get("observed_weight_file_sha256")
        == manifest.weight_file_sha256
        and verification.get("model_parameter_fingerprint")
        == manifest.model_parameter_fingerprint
        and verification.get("checkpoint_evidence_digest")
        == manifest.checkpoint_evidence_digest
        and verification.get("checkpoint_generation") == manifest.checkpoint_generation
        and verification.get("checkpoint_semantic_digest")
        == manifest.checkpoint_semantic_digest
        and verification.get("checkpoint_causal_record_digest")
        == manifest.checkpoint_causal_record_digest
    )


def _load_receipt_material(load: dict[str, Any]) -> dict[str, Any]:
    names = (
        "checkpoint_id",
        "weight_file_size_bytes",
        "weight_file_sha256",
        "private_checkpoint_copy_sha256",
        "private_checkpoint_copy_size_bytes",
        "model_parameter_fingerprint",
        "lineage_kind",
        "checkpoint_generation",
        "checkpoint_semantic_digest",
        "checkpoint_causal_record_digest",
        "checkpoint_evidence_digest",
        "confidence_calibration_state",
        "latest_checkpoint_loadable",
        "model_state_restored",
        "weight_file_sha256_verified",
        "model_parameter_fingerprint_verified",
        "checkpoint_evidence_verified",
        "checkpoint_identity_verified",
        "load_status",
    )
    if any(name not in load for name in names):
        _fail("PROFILED_BASE_LINEAGE_LOAD_RECEIPT_FIELDS_MISSING")
    return {name: load[name] for name in names}


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledBaseCheckpointLineageV1:
    schema_version: str
    checkpoint_id: str
    checkpoint_weight_sha256: str
    checkpoint_weight_size_bytes: int
    checkpoint_evidence_digest: str
    checkpoint_generation: int
    checkpoint_semantic_digest: str
    checkpoint_causal_record_digest: str
    lineage_kind: str
    model_id: str
    model_input_dim: int
    model_parameter_fingerprint: str
    confidence_calibration_sha256: str
    checkpoint_feature_abi_binding_sha256: str
    exact_checkpoint_load_receipt_sha256: str
    base_checkpoint_lineage_binding_sha256: str
    checkpoint_artifact_verified: bool
    exact_checkpoint_loaded: bool
    checkpoint_write_authorized: bool
    serving_authorized: bool
    trading_authorized: bool
    _manifest_owner: CheckpointManifest = field(repr=False, compare=False)
    _manager_owner: V2HybridCheckpointManager = field(repr=False, compare=False)
    _model_owner: V2HybridPolicyModel = field(repr=False, compare=False)
    _seal_mac: bytes = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        material = _binding_material(
            {name: getattr(self, name) for name in _binding_material_names()}
        )
        manifest = self._manifest_owner
        evidence_abi = manifest.checkpoint_evidence.get(
            "checkpoint_feature_abi_binding_v4"
        )
        observed_abi_sha256 = (
            stable_sha256(evidence_abi) if type(evidence_abi) is dict else ""
        )
        if (
            self._construction_token is not _RESULT_TOKEN
            or self.schema_version
            != AUTHENTICATED_PROFILED_BASE_CHECKPOINT_LINEAGE_V1_SCHEMA_VERSION
            or type(manifest) is not CheckpointManifest
            or type(self._manager_owner) is not V2HybridCheckpointManager
            or type(self._model_owner) is not V2HybridPolicyModel
            or not all(
                _valid_sha256(value)
                for value in (
                    self.checkpoint_weight_sha256,
                    self.checkpoint_evidence_digest,
                    self.checkpoint_semantic_digest,
                    self.checkpoint_causal_record_digest,
                    self.model_parameter_fingerprint,
                    self.confidence_calibration_sha256,
                    self.checkpoint_feature_abi_binding_sha256,
                    self.exact_checkpoint_load_receipt_sha256,
                    self.base_checkpoint_lineage_binding_sha256,
                )
            )
            or self.base_checkpoint_lineage_binding_sha256 != stable_sha256(material)
            or self.checkpoint_weight_size_bytes <= 0
            or self.checkpoint_generation <= 0
            or self.lineage_kind not in _ALLOWED_BASE_LINEAGES
            or manifest.checkpoint_id != self.checkpoint_id
            or manifest.weight_file_sha256 != self.checkpoint_weight_sha256
            or manifest.weight_file_size_bytes != self.checkpoint_weight_size_bytes
            or manifest.checkpoint_evidence_digest != self.checkpoint_evidence_digest
            or _checkpoint_evidence_sha256(manifest.checkpoint_evidence)
            != self.checkpoint_evidence_digest
            or manifest.checkpoint_generation != self.checkpoint_generation
            or manifest.checkpoint_semantic_digest != self.checkpoint_semantic_digest
            or manifest.checkpoint_causal_record_digest
            != self.checkpoint_causal_record_digest
            or manifest.lineage_kind != self.lineage_kind
            or manifest.model_id != self.model_id
            or manifest.input_dim != self.model_input_dim
            or manifest.model_parameter_fingerprint
            != self.model_parameter_fingerprint
            or observed_abi_sha256 != self.checkpoint_feature_abi_binding_sha256
            or model_parameter_fingerprint(self._model_owner)
            != self.model_parameter_fingerprint
            or _calibration_sha256(self._model_owner)
            != self.confidence_calibration_sha256
            or any(
                value is not expected
                for value, expected in (
                    (self.checkpoint_artifact_verified, True),
                    (self.exact_checkpoint_loaded, True),
                    (self.checkpoint_write_authorized, False),
                    (self.serving_authorized, False),
                    (self.trading_authorized, False),
                )
            )
            or type(self._seal_mac) is not bytes
            or not hmac.compare_digest(
                self._seal_mac,
                _seal(
                    material,
                    owner_ids=(
                        id(self._manifest_owner),
                        id(self._manager_owner),
                        id(self._model_owner),
                    ),
                ),
            )
        ):
            _fail("PROFILED_BASE_LINEAGE_RESULT_INVALID")

    def __reduce_ex__(self, _protocol: int) -> NoReturn:
        _fail("PROFILED_BASE_LINEAGE_COPY_OR_PICKLE_FORBIDDEN")


def _binding_material_names() -> tuple[str, ...]:
    return (
        "schema_version",
        "checkpoint_id",
        "checkpoint_weight_sha256",
        "checkpoint_weight_size_bytes",
        "checkpoint_evidence_digest",
        "checkpoint_generation",
        "checkpoint_semantic_digest",
        "checkpoint_causal_record_digest",
        "lineage_kind",
        "model_id",
        "model_input_dim",
        "model_parameter_fingerprint",
        "confidence_calibration_sha256",
        "checkpoint_feature_abi_binding_sha256",
        "exact_checkpoint_load_receipt_sha256",
        "checkpoint_artifact_verified",
        "exact_checkpoint_loaded",
        "checkpoint_write_authorized",
        "serving_authorized",
        "trading_authorized",
    )


def capture_authenticated_profiled_base_checkpoint_lineage_v1(
    *,
    base_model: V2HybridPolicyModel,
    base_checkpoint_manager: V2HybridCheckpointManager,
    expected_checkpoint_id: str,
) -> AuthenticatedProfiledBaseCheckpointLineageV1:
    """Load and seal the exact durable parent before optimizer execution."""

    manifest = _exact_manifest(
        manager=base_checkpoint_manager,
        model=base_model,
        expected_checkpoint_id=expected_checkpoint_id,
    )
    try:
        load = base_checkpoint_manager.load_latest_weights(
            base_model,
            allowed_lineage_kinds=frozenset({manifest.lineage_kind}),
            expected_checkpoint_id=manifest.checkpoint_id,
        )
        verification = base_checkpoint_manager.verify_manifest_artifact(manifest)
    except Exception as exc:
        raise AuthenticatedProfiledBaseCheckpointLineageV1Error(
            "PROFILED_BASE_LINEAGE_EXACT_LOAD_FAILED"
        ) from exc
    if (
        load.get("checkpoint_id") != manifest.checkpoint_id
        or load.get("latest_checkpoint_loadable") is not True
        or load.get("model_state_restored") is not True
        or load.get("weight_file_sha256_verified") is not True
        or load.get("model_parameter_fingerprint_verified") is not True
        or load.get("checkpoint_evidence_verified") is not True
        or load.get("checkpoint_identity_verified") is not True
        or load.get("weight_file_sha256") != manifest.weight_file_sha256
        or load.get("private_checkpoint_copy_sha256") != manifest.weight_file_sha256
        or load.get("model_parameter_fingerprint")
        != manifest.model_parameter_fingerprint
        or load.get("checkpoint_generation") != manifest.checkpoint_generation
        or load.get("checkpoint_semantic_digest")
        != manifest.checkpoint_semantic_digest
        or load.get("checkpoint_causal_record_digest")
        != manifest.checkpoint_causal_record_digest
        or load.get("checkpoint_evidence_digest")
        != manifest.checkpoint_evidence_digest
        or not _verification_valid(manifest=manifest, verification=verification)
        or model_parameter_fingerprint(base_model)
        != manifest.model_parameter_fingerprint
        or base_model.confidence_calibration_state
        != manifest.confidence_calibration_state
    ):
        _fail("PROFILED_BASE_LINEAGE_EXACT_LOAD_IDENTITY_INVALID")
    abi = manifest.checkpoint_evidence.get("checkpoint_feature_abi_binding_v4")
    if type(abi) is not dict:
        _fail("PROFILED_BASE_LINEAGE_FEATURE_ABI_BINDING_MISSING")
    values: dict[str, Any] = {
        "schema_version": AUTHENTICATED_PROFILED_BASE_CHECKPOINT_LINEAGE_V1_SCHEMA_VERSION,
        "checkpoint_id": manifest.checkpoint_id,
        "checkpoint_weight_sha256": manifest.weight_file_sha256,
        "checkpoint_weight_size_bytes": manifest.weight_file_size_bytes,
        "checkpoint_evidence_digest": manifest.checkpoint_evidence_digest,
        "checkpoint_generation": manifest.checkpoint_generation,
        "checkpoint_semantic_digest": manifest.checkpoint_semantic_digest,
        "checkpoint_causal_record_digest": manifest.checkpoint_causal_record_digest,
        "lineage_kind": manifest.lineage_kind,
        "model_id": manifest.model_id,
        "model_input_dim": manifest.input_dim,
        "model_parameter_fingerprint": manifest.model_parameter_fingerprint,
        "confidence_calibration_sha256": _calibration_sha256(base_model),
        "checkpoint_feature_abi_binding_sha256": stable_sha256(abi),
        "exact_checkpoint_load_receipt_sha256": stable_sha256(
            _load_receipt_material(load)
        ),
        "base_checkpoint_lineage_binding_sha256": "0" * 64,
        "checkpoint_artifact_verified": True,
        "exact_checkpoint_loaded": True,
        "checkpoint_write_authorized": False,
        "serving_authorized": False,
        "trading_authorized": False,
        "_manifest_owner": manifest,
        "_manager_owner": base_checkpoint_manager,
        "_model_owner": base_model,
        "_seal_mac": b"placeholder",
        "_construction_token": _RESULT_TOKEN,
    }
    material = _binding_material(values)
    values["base_checkpoint_lineage_binding_sha256"] = stable_sha256(material)
    material = _binding_material(values)
    values["_seal_mac"] = _seal(
        material,
        owner_ids=(id(manifest), id(base_checkpoint_manager), id(base_model)),
    )
    return AuthenticatedProfiledBaseCheckpointLineageV1(**values)


def revalidate_authenticated_profiled_base_checkpoint_lineage_v1(
    *,
    lineage: AuthenticatedProfiledBaseCheckpointLineageV1,
    base_model: V2HybridPolicyModel,
    base_checkpoint_manager: V2HybridCheckpointManager,
) -> CheckpointManifest:
    """Reopen and verify the exact pre-execution parent without reloading it."""

    if type(lineage) is not AuthenticatedProfiledBaseCheckpointLineageV1:
        _fail("PROFILED_BASE_LINEAGE_EXACT_TYPE_REQUIRED")
    lineage.__post_init__()
    if (
        lineage._model_owner is not base_model
        or lineage._manager_owner is not base_checkpoint_manager
    ):
        _fail("PROFILED_BASE_LINEAGE_OWNER_MISMATCH")
    manifest = _exact_manifest(
        manager=base_checkpoint_manager,
        model=base_model,
        expected_checkpoint_id=lineage.checkpoint_id,
    )
    if manifest is not lineage._manifest_owner:
        # Re-enumeration constructs a fresh immutable value. Require semantic
        # equality, while the process seal still owns the pre-execution object.
        if manifest != lineage._manifest_owner:
            _fail("PROFILED_BASE_LINEAGE_MANIFEST_CHANGED")
    try:
        verification = base_checkpoint_manager.verify_manifest_artifact(manifest)
    except Exception as exc:
        raise AuthenticatedProfiledBaseCheckpointLineageV1Error(
            "PROFILED_BASE_LINEAGE_REVERIFICATION_FAILED"
        ) from exc
    if (
        not _verification_valid(manifest=manifest, verification=verification)
        or model_parameter_fingerprint(base_model) != lineage.model_parameter_fingerprint
        or _calibration_sha256(base_model) != lineage.confidence_calibration_sha256
    ):
        _fail("PROFILED_BASE_LINEAGE_REVERIFICATION_IDENTITY_INVALID")
    return manifest


__all__ = (
    "AUTHENTICATED_PROFILED_BASE_CHECKPOINT_LINEAGE_V1_SCHEMA_VERSION",
    "AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE",
    "AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_SCHEMA_VERSION",
    "AUTHENTICATED_PROFILED_SUPERVISED_LEDGER_DISPOSITION",
    "AuthenticatedProfiledBaseCheckpointLineageV1",
    "AuthenticatedProfiledBaseCheckpointLineageV1Error",
    "capture_authenticated_profiled_base_checkpoint_lineage_v1",
    "revalidate_authenticated_profiled_base_checkpoint_lineage_v1",
)
