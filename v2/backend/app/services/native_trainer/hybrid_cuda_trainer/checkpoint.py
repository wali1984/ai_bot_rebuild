"""Safe local checkpoint manifest handling for V2 hybrid trainer."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CHECKPOINT_SOURCE, LIVE_GATE_BLOCKED
from .model import V2HybridPolicyModel


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    external_deserialization_used: bool = False


class V2HybridCheckpointManager:
    """Writes JSON manifests and refuses unapproved external deserialization."""

    def __init__(self, model_dir: Path) -> None:
        self.model_dir = Path(model_dir)

    def _validate_model_dir(self) -> None:
        text = str(self.model_dir)
        if not (text.startswith(".local_models") or "/.local_models/" in text):
            raise ValueError("checkpoint manifests must live under .local_models")

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
    ) -> CheckpointManifest:
        self._validate_model_dir()
        self.model_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_id = f"v2_hybrid_ckpt_{model_id[-24:]}"
        manifest = CheckpointManifest(
            checkpoint_id=checkpoint_id,
            checkpoint_source=CHECKPOINT_SOURCE,
            path=str(self.model_dir / f"{checkpoint_id}.json"),
            generated_utc=_utc_iso(),
            model_id=model_id,
            input_dim=int(input_dim),
            device=device,
            cuda_active=bool(cuda_active),
            weight_blob_written=bool(weight_blob_written),
            weight_file_path=weight_file_path,
            weight_file_format=weight_file_format,
            weight_file_size_bytes=weight_file_size_bytes,
        )
        path = Path(manifest.path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(manifest.__dict__, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        return manifest

    def write_checkpoint(
        self,
        *,
        model: V2HybridPolicyModel,
        input_dim: int,
        device: str,
        cuda_active: bool,
        write_weight_blob: bool = True,
    ) -> CheckpointManifest:
        self._validate_model_dir()
        checkpoint_id = f"v2_hybrid_ckpt_{model.model_id[-24:]}"
        weight: dict[str, Any] = {}
        if write_weight_blob:
            weight = model.save_weight_blob(self.model_dir / f"{checkpoint_id}.weights.npz")
        return self.write_manifest(
            model_id=model.model_id,
            input_dim=input_dim,
            device=device,
            cuda_active=cuda_active,
            weight_blob_written=bool(weight),
            weight_file_path=weight.get("weight_file_path"),
            weight_file_format=weight.get("weight_file_format"),
            weight_file_size_bytes=weight.get("weight_file_size_bytes"),
        )

    def latest_manifest(self, *, input_dim: int | None = None) -> CheckpointManifest | None:
        manifests: list[tuple[float, CheckpointManifest]] = []
        for path in self.model_dir.glob("v2_hybrid_ckpt_*.json"):
            if path.name.endswith(".tmp"):
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if input_dim is not None and int(raw.get("input_dim") or -1) != int(input_dim):
                continue
            manifests.append(
                (
                    path.stat().st_mtime,
                    CheckpointManifest(
                        checkpoint_id=str(raw.get("checkpoint_id") or path.stem),
                        checkpoint_source=str(raw.get("checkpoint_source") or CHECKPOINT_SOURCE),
                        path=str(raw.get("path") or path),
                        generated_utc=str(raw.get("generated_utc") or ""),
                        model_id=str(raw.get("model_id") or ""),
                        input_dim=int(raw.get("input_dim") or 0),
                        device=str(raw.get("device") or "unknown"),
                        cuda_active=bool(raw.get("cuda_active")),
                        weight_blob_written=bool(raw.get("weight_blob_written")),
                        weight_file_path=raw.get("weight_file_path"),
                        weight_file_format=raw.get("weight_file_format"),
                        weight_file_size_bytes=raw.get("weight_file_size_bytes"),
                        external_deserialization_used=bool(raw.get("external_deserialization_used", False)),
                    ),
                )
            )
        if not manifests:
            return None
        manifests.sort(key=lambda item: item[0], reverse=True)
        return manifests[0][1]

    def load_latest_weights(self, model: V2HybridPolicyModel) -> dict[str, Any]:
        manifest = self.latest_manifest(input_dim=model.input_dim)
        if manifest is None:
            return {
                "checkpoint_manifest_exists": False,
                "weight_blob_written": False,
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "load_status": "NO_COMPATIBLE_CHECKPOINT_MANIFEST",
            }
        if not manifest.weight_blob_written or not manifest.weight_file_path:
            return {
                "checkpoint_manifest_exists": True,
                "checkpoint_id": manifest.checkpoint_id,
                "weight_blob_written": False,
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "load_status": "CHECKPOINT_MANIFEST_HAS_NO_WEIGHT_BLOB",
            }
        try:
            loaded = model.load_weight_blob(Path(manifest.weight_file_path))
        except Exception as exc:
            return {
                "checkpoint_manifest_exists": True,
                "checkpoint_id": manifest.checkpoint_id,
                "weight_blob_written": True,
                "weight_file_path": manifest.weight_file_path,
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "load_status": f"LOAD_FAILED:{type(exc).__name__}",
            }
        return {
            "checkpoint_manifest_exists": True,
            "checkpoint_id": manifest.checkpoint_id,
            "weight_blob_written": True,
            "weight_file_path": manifest.weight_file_path,
            "weight_file_format": manifest.weight_file_format,
            "weight_file_size_bytes": manifest.weight_file_size_bytes,
            "safe_weight_format": manifest.weight_file_format == "npz",
            "latest_checkpoint_loadable": True,
            "model_state_restored": bool(loaded.get("model_state_restored")),
            "optimizer_state_restored_or_intentionally_not_required": True,
            "optimizer_state_note": "AdamW optimizer is intentionally recreated each cycle; model weights persist.",
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
            "safe_weight_format": (manifest.weight_file_format == "npz") if manifest else False,
            "external_deserialization_used": False,
            "torch_pickle_load_used": False,
            "operator_approval_required_for_external_blobs": True,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        }
