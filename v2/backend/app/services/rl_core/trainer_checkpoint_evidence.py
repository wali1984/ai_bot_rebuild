"""V2 trainer checkpoint evidence.

Read-only scanner for legacy checkpoint artifacts copied under
``legacy_reference``. It inventories checkpoint blobs and publishes
metadata evidence only. It does not deserialize pickle, torch, or
stable-baselines artifacts.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Iterable

from .checkpoints import (
    CheckpointCandidate,
    inventory_checkpoints,
    safe_load_checkpoint,
)

WORKER_ID = "v2_trainer_checkpoint_evidence"
SCHEMA_VERSION = "v2_trainer_checkpoint_evidence_v1"
STATUS_PRESENT = "LEGACY_CHECKPOINT_METADATA_PRESENT"
STATUS_MISSING = "NO_LEGACY_CHECKPOINT_METADATA_FOUND"
WEIGHTS_NOT_LOADED = "LEGACY_CHECKPOINT_METADATA_PRESENT_WEIGHTS_NOT_DESERIALIZED_V2_SAFE_MODE"
NATIVE_STATUS_MISSING = "NO_V2_SAFE_NATIVE_CHECKPOINT_FOUND"
NATIVE_STATUS_LOAD_VERIFIED = "V2_SAFE_NATIVE_CHECKPOINT_LOAD_VERIFIED"
NATIVE_STATUS_LOAD_FAILED = "V2_SAFE_NATIVE_CHECKPOINT_LOAD_FAILED"
NATIVE_WEIGHT_LOADED = "V2_SAFE_NATIVE_WEIGHT_BLOB_LOADED"
DEFAULT_SCAN_ROOTS: tuple[Path, ...] = (
    Path("legacy_reference/.backups"),
    Path("legacy_reference/models/checkpoints"),
)
DEFAULT_NATIVE_MODEL_DIR = Path(".local_models/v2_native_rl_masa_ppo")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _candidate_sort_key(candidate: CheckpointCandidate) -> tuple[str, int, str]:
    created = (
        candidate.parsed_metadata.created_utc
        if candidate.parsed_metadata is not None
        else candidate.mtime_utc
    )
    return (created, candidate.size_bytes, candidate.path)


def _select_latest(candidates: Iterable[CheckpointCandidate]) -> CheckpointCandidate | None:
    items = list(candidates)
    if not items:
        return None
    return max(items, key=_candidate_sort_key)


def _candidate_summary(candidate: CheckpointCandidate | None) -> dict | None:
    if candidate is None:
        return None
    parsed = candidate.parsed_metadata.as_dict() if candidate.parsed_metadata else None
    return {
        "path": candidate.path,
        "size_bytes": candidate.size_bytes,
        "mtime_utc": candidate.mtime_utc,
        "sha256_hex": candidate.sha256_hex,
        "extension": candidate.extension,
        "parsed_metadata": parsed,
        "sidecar_metadata_path": candidate.sidecar_metadata_path,
        "checkpoint_id": (
            parsed.get("checkpoint_id")
            if isinstance(parsed, dict)
            else f"unparsed_{candidate.sha256_hex[:16]}"
        ),
    }


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _native_checkpoint_summary(model_dir: Path | None) -> dict[str, Any]:
    """Verify the latest V2-owned npz checkpoint without legacy deserialization."""
    if model_dir is None:
        return {
            "native_checkpoint_status": NATIVE_STATUS_MISSING,
            "native_checkpoint_id": None,
            "native_checkpoint_load_status": None,
            "native_model_weights_load_verified": False,
        }
    try:
        from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
            V2HybridCheckpointManager,
        )
        from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
            V2HybridPolicyModel,
        )
    except Exception as exc:
        return {
            "native_checkpoint_status": NATIVE_STATUS_LOAD_FAILED,
            "native_checkpoint_id": None,
            "native_checkpoint_load_status": f"IMPORT_FAILED:{type(exc).__name__}",
            "native_model_weights_load_verified": False,
        }
    manager = V2HybridCheckpointManager(Path(model_dir))
    latest_manifest = manager.latest_manifest()
    if latest_manifest is None:
        return {
            "native_checkpoint_status": NATIVE_STATUS_MISSING,
            "native_checkpoint_id": None,
            "native_checkpoint_load_status": "NO_COMPATIBLE_MANIFEST",
            "native_model_weights_load_verified": False,
        }
    load_status: dict[str, Any]
    try:
        probe = V2HybridPolicyModel(input_dim=int(latest_manifest.input_dim))
        load_status = manager.load_latest_weights(probe)
        native_torch_model_available = bool(probe.torch_available)
    except Exception as exc:
        native_torch_model_available = False
        load_status = {
            "checkpoint_id": latest_manifest.checkpoint_id,
            "latest_checkpoint_loadable": False,
            "model_state_restored": False,
            "load_status": f"LOAD_FAILED:{type(exc).__name__}",
        }
    active_weight_path = (
        Path(str(load_status.get("weight_file_path")))
        if load_status.get("weight_file_path")
        else None
    )
    verified = bool(
        load_status.get("latest_checkpoint_loadable")
        and load_status.get("model_state_restored")
        and load_status.get("safe_weight_format")
    )
    return {
        "native_checkpoint_status": (
            NATIVE_STATUS_LOAD_VERIFIED if verified else NATIVE_STATUS_LOAD_FAILED
        ),
        "native_checkpoint_id": load_status.get("checkpoint_id") or latest_manifest.checkpoint_id,
        "native_latest_metadata_checkpoint_id": (
            load_status.get("latest_metadata_checkpoint_id") or latest_manifest.checkpoint_id
        ),
        "native_metadata_only_manifest_ignored_for_weight_load": bool(
            load_status.get("metadata_only_manifest_ignored_for_weight_load")
        ),
        "native_checkpoint_manifest_path": latest_manifest.path,
        "native_checkpoint_weight_file_path": str(active_weight_path) if active_weight_path else None,
        "native_checkpoint_weight_file_format": load_status.get("weight_file_format"),
        "native_checkpoint_weight_file_size_bytes": load_status.get("weight_file_size_bytes"),
        "native_checkpoint_weight_sha256_hex": _sha256_file(active_weight_path),
        "native_checkpoint_load_status": load_status.get("load_status"),
        "native_checkpoint_load": load_status,
        "native_torch_model_available": native_torch_model_available,
        "native_model_weights_load_verified": verified,
        "safe_npz_weight_load_verified": verified,
        "external_deserialization_used_for_native_checkpoint": False,
        "pickle_deserialized_for_native_checkpoint": False,
    }


def build_trainer_checkpoint_evidence(
    roots: Iterable[Path] | None = None,
    *,
    sha256_compute_max_bytes: int = 32 * 1024 * 1024,
    native_model_dir: Path | None = None,
) -> dict:
    """Build a metadata-only checkpoint evidence payload."""
    scan_roots = tuple(roots or DEFAULT_SCAN_ROOTS)
    inventory = inventory_checkpoints(
        scan_roots,
        sha256_compute_max_bytes=sha256_compute_max_bytes,
    )
    candidates = tuple(inventory.candidates)
    primary = _select_latest(candidates)
    lower_name = lambda c: Path(c.path).name.lower()
    latest_ppo = _select_latest(
        c for c in candidates if c.extension == ".zip" or "ppo" in lower_name(c)
    )
    latest_masa = _select_latest(
        c for c in candidates if c.extension == ".pkl" or "masa" in lower_name(c)
    )
    latest_enterprise = _select_latest(
        c for c in candidates if c.extension == ".pt" or "enterprise_modules" in lower_name(c)
    )
    loading = safe_load_checkpoint(
        inventory,
        selected_candidate_path=primary.path if primary is not None else None,
    )
    selected = _candidate_summary(primary)
    selected_id = selected.get("checkpoint_id") if selected else None
    generated = _utc_iso()
    metadata_status = STATUS_PRESENT if primary is not None else STATUS_MISSING
    native = _native_checkpoint_summary(
        native_model_dir if native_model_dir is not None else (DEFAULT_NATIVE_MODEL_DIR if roots is None else None)
    )
    native_ready = native.get("native_checkpoint_status") == NATIVE_STATUS_LOAD_VERIFIED
    active_checkpoint_id = native.get("native_checkpoint_id") if native_ready else selected_id
    active_checkpoint_path = (
        native.get("native_checkpoint_weight_file_path")
        if native_ready
        else (selected.get("path") if selected else None)
    )
    legacy_blocker = WEIGHTS_NOT_LOADED if primary is not None else "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
    active_weight_status = NATIVE_WEIGHT_LOADED if native_ready else legacy_blocker
    return {
        "worker_id": WORKER_ID,
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated,
        "legacy_checkpoint_metadata_status": metadata_status,
        "checkpoint_evidence_status": (
            f"{NATIVE_STATUS_LOAD_VERIFIED}_WITH_{metadata_status}"
            if native_ready
            else metadata_status
        ),
        "trainer_online_mode": (
            "V2_NATIVE_RL_CORE_WITH_V2_SAFE_NATIVE_CHECKPOINT"
            if native_ready
            else (
                "V2_NATIVE_RL_CORE_WITH_LEGACY_CHECKPOINT_EVIDENCE"
                if primary is not None
                else "V2_NATIVE_RL_CORE_CHECKPOINT_EVIDENCE_MISSING"
            )
        ),
        "checkpoint_blocker": None if native_ready else legacy_blocker,
        "legacy_checkpoint_blocker": legacy_blocker,
        "active_checkpoint_id": active_checkpoint_id,
        "active_checkpoint_path": active_checkpoint_path,
        "active_checkpoint_source": "V2_SAFE_NATIVE_NPZ" if native_ready else "LEGACY_METADATA_ONLY",
        "active_checkpoint_blocker": None if native_ready else legacy_blocker,
        "active_checkpoint_weight_status": active_weight_status,
        "selected_checkpoint_id": selected_id,
        "selected_checkpoint_path": selected.get("path") if selected else None,
        "selected_checkpoint": selected,
        "selected_by_role": {
            "latest_any": selected,
            "latest_ppo": _candidate_summary(latest_ppo),
            "latest_masa": _candidate_summary(latest_masa),
            "latest_enterprise_modules": _candidate_summary(latest_enterprise),
        },
        "candidate_count": inventory.candidate_count,
        "scanned_roots": list(inventory.scanned_roots),
        "inventory_status": inventory.status,
        "checkpoint_loading": asdict(loading),
        "checkpoint_weight_status": active_weight_status,
        "legacy_checkpoint_weight_status": (
            WEIGHTS_NOT_LOADED if primary is not None else loading.weight_loading_status
        ),
        "model_shape_status": loading.model_shape_status,
        "missing_checkpoint_blockers": list(loading.missing_checkpoint_blockers),
        **native,
        "weight_deserialization_performed": False,
        "model_weights_loaded_into_v2_process": bool(native_ready),
        "model_weights_loaded_scope": (
            "checkpoint_evidence_safe_npz_probe" if native_ready else "none"
        ),
        "torch_imported": bool(native.get("native_torch_model_available")),
        "stable_baselines_imported": False,
        "pickle_deserialized": False,
        "writes_legacy_redis": False,
        "exchange_action_taken": False,
        "legacy_mutation_performed": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }
