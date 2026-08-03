"""Read-only checkpoint candidate inventory.

Scans approved roots and (read-only) the V2-owned legacy mirror for files
that *look like* trained-model checkpoints. NEVER deserializes any blob.
NEVER imports torch. NEVER reads outside the configured roots. NEVER
modifies the legacy filesystem at /home/wali/Desktop/AI BOT.
"""
from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from typing import Any

# Approved local roots that the V2 control plane is permitted to read.
APPROVED_LOCAL_ROOTS: tuple[str, ...] = (
    ".local_models",
    ".local_secrets",
    "v2/runtime",
)
# Read-only V2-owned mirror of legacy code. Files here are reference text
# only; even if they reference checkpoint paths, the V2 process must not
# deserialize them. We scan for filenames that look like blobs so we can
# honestly list "legacy reference exists" without ever loading it.
LEGACY_READONLY_ROOTS: tuple[str, ...] = (
    "v2/legacy_owned_runtime",
    "legacy_reference",
)
CHECKPOINT_EXTENSIONS: tuple[str, ...] = (
    ".pt",
    ".pth",
    ".ckpt",
    ".safetensors",
    ".pkl",
    ".pickle",
)
MAX_CANDIDATES_PER_ROOT = 200  # cap to keep the inventory bounded


@dataclasses.dataclass(frozen=True)
class CheckpointCandidate:
    path: str
    root_kind: str  # APPROVED_LOCAL or LEGACY_READONLY
    exists: bool
    readable: bool
    size_bytes: int | None
    sha256_first_64kib: str | None
    extension: str
    mtime_iso_utc: str | None
    possible_model_family: str
    source_classification: str


def _sha256_first_64kib(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            chunk = fh.read(64 * 1024)
            if not chunk:
                return None
            h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _mtime_iso(path: Path) -> str | None:
    try:
        ts = path.stat().st_mtime
    except OSError:
        return None
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _classify_family(path: Path) -> str:
    name = path.name.lower()
    if "policy" in name or "actor" in name:
        return "POLICY_OR_ACTOR_CANDIDATE"
    if "value" in name or "critic" in name:
        return "VALUE_OR_CRITIC_CANDIDATE"
    if "trainer" in name or "training" in name:
        return "TRAINER_STATE_CANDIDATE"
    if "checkpoint" in name or "ckpt" in name or "collapsed_checkpoint" in name:
        return "GENERAL_CHECKPOINT_CANDIDATE"
    if name.endswith(".safetensors"):
        return "SAFETENSORS_PROBABLE_WEIGHTS"
    if name.endswith((".pkl", ".pickle")):
        return "UNSAFE_PICKLE_NO_LOAD"
    return "UNKNOWN_BLOB"


def _classify_source(path: Path, root_kind: str, ext: str) -> str:
    if root_kind == "APPROVED_LOCAL" and str(path).startswith(".local_models"):
        return "APPROVED_LOCAL_MODEL_CANDIDATE"
    if ext in (".pkl", ".pickle"):
        return "UNSAFE_PICKLE_NO_LOAD"
    if root_kind == "LEGACY_READONLY":
        return "LEGACY_REFERENCE_ONLY"
    return "BLOCKED_NO_OPERATOR_APPROVAL"


def _scan_root(root: Path, root_kind: str) -> list[CheckpointCandidate]:
    candidates: list[CheckpointCandidate] = []
    if not root.exists():
        return candidates
    try:
        iter_ = root.rglob("*")
    except OSError:
        return candidates
    for path in iter_:
        if len(candidates) >= MAX_CANDIDATES_PER_ROOT:
            break
        try:
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext not in CHECKPOINT_EXTENSIONS:
                continue
            size = path.stat().st_size
            readable = True
            try:
                with path.open("rb") as fh:
                    fh.read(1)
            except OSError:
                readable = False
            sha = _sha256_first_64kib(path) if readable else None
            mtime = _mtime_iso(path)
            family = _classify_family(path)
            source = _classify_source(path, root_kind, ext)
            candidates.append(
                CheckpointCandidate(
                    path=str(path),
                    root_kind=root_kind,
                    exists=True,
                    readable=readable,
                    size_bytes=size,
                    sha256_first_64kib=sha,
                    extension=ext,
                    mtime_iso_utc=mtime,
                    possible_model_family=family,
                    source_classification=source,
                )
            )
        except (OSError, PermissionError):
            continue
    return candidates


def _count_extensions(root: Path) -> dict[str, int]:
    """Exhaustive bounded count by extension; never stores individual paths."""
    counts: dict[str, int] = {ext: 0 for ext in CHECKPOINT_EXTENSIONS}
    if not root.exists():
        return counts
    try:
        iter_ = root.rglob("*")
    except OSError:
        return counts
    for path in iter_:
        try:
            if not path.is_file():
                continue
            ext = path.suffix.lower()
            if ext in counts:
                counts[ext] += 1
        except (OSError, PermissionError):
            continue
    return counts


def build_inventory(
    repo_root: Path | None = None,
    approved_roots: tuple[str, ...] = APPROVED_LOCAL_ROOTS,
    legacy_roots: tuple[str, ...] = LEGACY_READONLY_ROOTS,
) -> dict[str, Any]:
    base = repo_root if repo_root is not None else Path(".")
    approved_results: list[CheckpointCandidate] = []
    legacy_results: list[CheckpointCandidate] = []
    for rel in approved_roots:
        approved_results.extend(_scan_root(base / rel, "APPROVED_LOCAL"))
    for rel in legacy_roots:
        legacy_results.extend(_scan_root(base / rel, "LEGACY_READONLY"))
    all_candidates = approved_results + legacy_results
    summary: dict[str, int] = {
        "APPROVED_LOCAL_MODEL_CANDIDATE": 0,
        "LEGACY_REFERENCE_ONLY": 0,
        "BLOCKED_NO_OPERATOR_APPROVAL": 0,
        "UNSAFE_PICKLE_NO_LOAD": 0,
    }
    for c in all_candidates:
        summary[c.source_classification] = summary.get(c.source_classification, 0) + 1
    # Exhaustive bounded count by extension across all roots (no per-path).
    ext_counts_legacy: dict[str, int] = {ext: 0 for ext in CHECKPOINT_EXTENSIONS}
    for rel in legacy_roots:
        partial = _count_extensions(base / rel)
        for ext, n in partial.items():
            ext_counts_legacy[ext] = ext_counts_legacy.get(ext, 0) + n
    ext_counts_approved: dict[str, int] = {ext: 0 for ext in CHECKPOINT_EXTENSIONS}
    for rel in approved_roots:
        partial = _count_extensions(base / rel)
        for ext, n in partial.items():
            ext_counts_approved[ext] = ext_counts_approved.get(ext, 0) + n
    truncated = (
        len(approved_results) >= MAX_CANDIDATES_PER_ROOT * len(approved_roots)
        or len(legacy_results) >= MAX_CANDIDATES_PER_ROOT * len(legacy_roots)
    )
    return {
        "schema_version": "v2_checkpoint_candidate_inventory_v1",
        "approved_local_roots_scanned": list(approved_roots),
        "legacy_readonly_roots_scanned": list(legacy_roots),
        "candidate_count_total": len(all_candidates),
        "candidate_count_approved_local": len(approved_results),
        "candidate_count_legacy_reference": len(legacy_results),
        "candidates_truncated_per_root_max": MAX_CANDIDATES_PER_ROOT,
        "candidates_truncated": truncated,
        "extension_counts_exhaustive_approved": ext_counts_approved,
        "extension_counts_exhaustive_legacy": ext_counts_legacy,
        "source_classification_counts": summary,
        "candidates": [dataclasses.asdict(c) for c in all_candidates],
        "no_blob_deserialized": True,
        "no_torch_imported": True,
        "no_legacy_filesystem_modified": True,
        "no_pickle_loaded": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
