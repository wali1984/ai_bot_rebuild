"""V2 checkpoint inventory + safe-load shim (P0.2C).

Inventories candidate checkpoint blobs under a configured root and
emits a metadata record per file. By design this module does NOT
deserialize any PyTorch state into the V2 process.

When real weights are unavailable, the classification is
``CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED``.

Legacy citation:

- v2/legacy_owned_runtime/rl/checkpoint_manager.py
    sha256=151d8808d53b7ba00edc4411569ba2f86519154d52da1997b300cec14c3e1ba8
    size_bytes=12300
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .checkpoint_metadata import CheckpointMetadata, parse_legacy_checkpoint_filename
from .policy import POLICY_OBSERVATION_DIM, ACTION_COUNT

LEGACY_CHECKPOINT_MANAGER_SHA256 = "151d8808d53b7ba00edc4411569ba2f86519154d52da1997b300cec14c3e1ba8"

CHECKPOINT_EXTENSIONS: tuple[str, ...] = (".pt", ".pth", ".ckpt", ".zip", ".pkl")
CHECKPOINT_METADATA_SUFFIXES: tuple[str, ...] = ("_metadata.json", ".meta.json")

STATUS_WEIGHTS_AVAILABLE = "CHECKPOINT_WEIGHT_LOAD_BLOCKED_NO_TORCH_IN_V2"
STATUS_OPERATOR_REQUIRED = "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
STATUS_NO_CANDIDATES = "NO_CHECKPOINT_CANDIDATES_FOUND"
STATUS_METADATA_ONLY = "CHECKPOINT_METADATA_ONLY_NO_WEIGHTS_LOADED"

MODEL_SHAPE_BLOCKED_NO_TORCH = "MODEL_SHAPE_VERIFICATION_BLOCKED_NO_TORCH"


@dataclass(frozen=True)
class CheckpointCandidate:
    path: str
    size_bytes: int
    mtime_utc: str
    sha256_hex: str
    extension: str
    parsed_metadata: Optional[CheckpointMetadata]
    sidecar_metadata_path: Optional[str]


@dataclass(frozen=True)
class CheckpointInventoryResult:
    scanned_roots: tuple[str, ...]
    candidates: tuple[CheckpointCandidate, ...]
    candidate_count: int
    status: str
    generated_utc: str
    scope: str = "PAPER_ONLY_METADATA_ONLY"


@dataclass(frozen=True)
class CheckpointLoadingResult:
    checkpoint_id: Optional[str]
    checkpoint_source: Optional[str]
    checkpoint_metadata_status: str
    weight_loading_status: str
    model_shape_status: str
    missing_checkpoint_blockers: tuple[str, ...]
    declared_observation_dim: int
    declared_action_count: int
    generated_utc: str


def _file_sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _iter_checkpoint_paths(root: Path) -> Iterable[Path]:
    if not root.exists() or not root.is_dir():
        return ()
    out: list[Path] = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            low = fn.lower()
            if any(low.endswith(ext) for ext in CHECKPOINT_EXTENSIONS):
                out.append(Path(dirpath) / fn)
    return out


def _sidecar_metadata(path: Path) -> Optional[Path]:
    for suffix in CHECKPOINT_METADATA_SUFFIXES:
        cand = path.with_name(path.stem + suffix)
        if cand.exists():
            return cand
    return None


def inventory_checkpoints(
    roots: Iterable[Path],
    *,
    sha256_compute_max_bytes: int = 200 * 1024 * 1024,
) -> CheckpointInventoryResult:
    scanned: list[str] = []
    cands: list[CheckpointCandidate] = []
    for root in roots:
        p = Path(root)
        scanned.append(str(p))
        for fp in _iter_checkpoint_paths(p):
            try:
                st = fp.stat()
            except OSError:
                continue
            if st.st_size > sha256_compute_max_bytes:
                sha = f"SHA256_SKIPPED_FILE_TOO_LARGE_{st.st_size}"
            else:
                try:
                    sha = _file_sha256(fp)
                except OSError:
                    sha = "SHA256_READ_FAILED"
            cands.append(CheckpointCandidate(
                path=str(fp),
                size_bytes=int(st.st_size),
                mtime_utc=_utc_iso(st.st_mtime),
                sha256_hex=sha,
                extension=fp.suffix.lower(),
                parsed_metadata=parse_legacy_checkpoint_filename(fp.name, sha256_if_known=sha),
                sidecar_metadata_path=str(_sidecar_metadata(fp)) if _sidecar_metadata(fp) else None,
            ))
    status = STATUS_NO_CANDIDATES if not cands else STATUS_METADATA_ONLY
    return CheckpointInventoryResult(
        scanned_roots=tuple(scanned),
        candidates=tuple(cands),
        candidate_count=len(cands),
        status=status,
        generated_utc=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def safe_load_checkpoint(
    inventory: CheckpointInventoryResult,
    *,
    selected_candidate_path: Optional[str] = None,
) -> CheckpointLoadingResult:
    """Refuse to load PyTorch weights into the V2 process.

    Always returns a metadata-only result with explicit blockers. The
    V2 control plane never deserializes legacy policy weights.
    """
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if not inventory.candidates:
        return CheckpointLoadingResult(
            checkpoint_id=None,
            checkpoint_source=None,
            checkpoint_metadata_status=STATUS_NO_CANDIDATES,
            weight_loading_status=STATUS_OPERATOR_REQUIRED,
            model_shape_status=MODEL_SHAPE_BLOCKED_NO_TORCH,
            missing_checkpoint_blockers=(
                "no_checkpoint_candidates_in_scan_roots",
                "operator_must_provide_or_authorize_checkpoint_blob",
                "v2_control_plane_does_not_load_torch_weights",
            ),
            declared_observation_dim=POLICY_OBSERVATION_DIM,
            declared_action_count=ACTION_COUNT,
            generated_utc=now_iso,
        )
    if selected_candidate_path is not None:
        sel = next((c for c in inventory.candidates if c.path == selected_candidate_path), None)
    else:
        sel = inventory.candidates[0]
    if sel is None:
        return CheckpointLoadingResult(
            checkpoint_id=None,
            checkpoint_source=selected_candidate_path,
            checkpoint_metadata_status="SELECTED_CANDIDATE_NOT_FOUND",
            weight_loading_status=STATUS_OPERATOR_REQUIRED,
            model_shape_status=MODEL_SHAPE_BLOCKED_NO_TORCH,
            missing_checkpoint_blockers=(
                "selected_candidate_path_not_in_inventory",
                "operator_must_provide_or_authorize_checkpoint_blob",
            ),
            declared_observation_dim=POLICY_OBSERVATION_DIM,
            declared_action_count=ACTION_COUNT,
            generated_utc=now_iso,
        )
    parsed = sel.parsed_metadata
    cid = parsed.checkpoint_id if parsed else f"unparsed_{sel.sha256_hex[:16]}"
    return CheckpointLoadingResult(
        checkpoint_id=cid,
        checkpoint_source=sel.path,
        checkpoint_metadata_status=STATUS_METADATA_ONLY,
        weight_loading_status=STATUS_OPERATOR_REQUIRED,
        model_shape_status=MODEL_SHAPE_BLOCKED_NO_TORCH,
        missing_checkpoint_blockers=(
            "v2_control_plane_does_not_load_torch_weights",
            "weight_shape_verification_requires_operator_approved_subprocess",
            "checkpoint_promotion_to_v2_requires_codex_review",
        ),
        declared_observation_dim=POLICY_OBSERVATION_DIM,
        declared_action_count=ACTION_COUNT,
        generated_utc=now_iso,
    )


def checkpoints_invariants_snapshot() -> dict:
    return {
        "legacy_checkpoint_manager_sha256": LEGACY_CHECKPOINT_MANAGER_SHA256,
        "loads_torch_weights": False,
        "imports_torch": False,
        "imports_numpy": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "checkpoint_extensions_scanned": list(CHECKPOINT_EXTENSIONS),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }
