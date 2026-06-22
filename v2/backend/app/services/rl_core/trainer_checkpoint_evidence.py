"""V2 trainer checkpoint evidence.

Read-only scanner for legacy checkpoint artifacts copied under
``legacy_reference``. It inventories checkpoint blobs and publishes
metadata evidence only. It does not deserialize pickle, torch, or
stable-baselines artifacts.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

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
DEFAULT_SCAN_ROOTS: tuple[Path, ...] = (
    Path("legacy_reference/.backups"),
    Path("legacy_reference/models/checkpoints"),
)


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


def build_trainer_checkpoint_evidence(
    roots: Iterable[Path] | None = None,
    *,
    sha256_compute_max_bytes: int = 32 * 1024 * 1024,
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
    return {
        "worker_id": WORKER_ID,
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated,
        "legacy_checkpoint_metadata_status": metadata_status,
        "checkpoint_evidence_status": metadata_status,
        "trainer_online_mode": (
            "V2_NATIVE_RL_CORE_WITH_LEGACY_CHECKPOINT_EVIDENCE"
            if primary is not None
            else "V2_NATIVE_RL_CORE_CHECKPOINT_EVIDENCE_MISSING"
        ),
        "checkpoint_blocker": WEIGHTS_NOT_LOADED if primary is not None else "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
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
        "checkpoint_weight_status": (
            WEIGHTS_NOT_LOADED if primary is not None else loading.weight_loading_status
        ),
        "model_shape_status": loading.model_shape_status,
        "missing_checkpoint_blockers": list(loading.missing_checkpoint_blockers),
        "weight_deserialization_performed": False,
        "model_weights_loaded_into_v2_process": False,
        "torch_imported": False,
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
