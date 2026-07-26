"""Atomic model registry for the canonical serving runtime.

The registry is the ONLY way a checkpoint becomes the active serving model. No
env var, in-place edit, symlink flip, or trainer restart activates a checkpoint.
Activation is compare-and-set on the generation counter and always leaves a
rollback pointer + an immutable activation receipt.

Registry keys (per lane in {paper, strict}):
  v2:model_registry:{lane}:active     -> active record (generation, checkpoint, health)
  v2:model_registry:{lane}:candidate  -> pending candidate bundle
  v2:model_registry:{lane}:history    -> JSON list of prior active records (bounded)
  v2:model_registry:activation_receipts:{receipt_id} -> immutable receipt
"""
from __future__ import annotations

import json
from typing import Any

from v2.backend.app.contracts.runtime_v2.contracts import (
    CheckpointBundleV2,
    ModelActivationReceiptV2,
    canonical_sha256,
)

ACTIVE_KEY = "v2:model_registry:{lane}:active"
CANDIDATE_KEY = "v2:model_registry:{lane}:candidate"
HISTORY_KEY = "v2:model_registry:{lane}:history"
RECEIPT_KEY = "v2:model_registry:activation_receipts:{receipt_id}"
HISTORY_MAX = 50


def _get_json(client: Any, key: str) -> dict[str, Any] | None:
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return val if isinstance(val, dict) else None


def read_active(client: Any, *, lane: str = "paper") -> dict[str, Any] | None:
    return _get_json(client, ACTIVE_KEY.format(lane=lane))


def read_candidate(client: Any, *, lane: str = "paper") -> dict[str, Any] | None:
    return _get_json(client, CANDIDATE_KEY.format(lane=lane))


def register_candidate(
    client: Any, bundle: CheckpointBundleV2, *, lane: str = "paper"
) -> dict[str, Any]:
    """Publish a validated candidate bundle. Does NOT activate."""
    reasons = bundle.validate()
    if reasons:
        raise ValueError(f"candidate_bundle_invalid:{','.join(reasons)}")
    record = {
        "schema_version": "model_registry_candidate_v2",
        "lane": lane,
        "checkpoint_id": bundle.checkpoint_id,
        "checkpoint_classification": bundle.checkpoint_classification,
        "checkpoint_bundle": bundle.to_dict(),
        "checkpoint_bundle_sha256": bundle.content_sha256(),
        "feature_abi_sha256": bundle.feature_abi_sha256,
        "paper_only": True,
        "live_eligible": False,
    }
    client.set(CANDIDATE_KEY.format(lane=lane), json.dumps(record, default=str))
    return record


def activate(
    client: Any,
    bundle: CheckpointBundleV2,
    *,
    lane: str = "paper",
    activated_by: str,
    activation_reason: str,
    serving_smoke_result: dict[str, Any],
    health_state: str = "HEALTHY",
    expected_generation: int | None = None,
) -> ModelActivationReceiptV2:
    """Atomically advance the active generation to this bundle (compare-and-set).

    expected_generation, when provided, must equal the current active generation
    or the activation fails (optimistic CAS) — prevents lost updates from a racing
    activator. Always records rollback pointer + immutable receipt.
    """
    reasons = bundle.validate()
    if reasons:
        raise ValueError(f"activation_bundle_invalid:{','.join(reasons)}")
    if not bundle.paper_eligible:
        raise ValueError("activation_bundle_not_paper_eligible")

    active_key = ACTIVE_KEY.format(lane=lane)
    # Optimistic CAS via WATCH/MULTI when the client supports pipelines.
    prev = read_active(client, lane=lane)
    prev_generation = int(prev.get("registry_generation", 0)) if prev else 0
    if expected_generation is not None and expected_generation != prev_generation:
        raise ValueError(
            f"activation_generation_conflict:expected={expected_generation}:actual={prev_generation}"
        )
    new_generation = prev_generation + 1
    prev_checkpoint_id = prev.get("checkpoint_id") if prev else None
    activated_at = serving_smoke_result.get("generated_utc") or serving_smoke_result.get("activated_at")
    if not activated_at:
        activated_at = str(serving_smoke_result.get("latest_prediction_time") or "")
    if not activated_at:
        raise ValueError("activation_requires_real_smoke_timestamp")

    receipt_id = "activation_" + canonical_sha256(
        {
            "lane": lane, "checkpoint_id": bundle.checkpoint_id,
            "generation": new_generation, "activated_at": activated_at,
        }
    )[:24]
    active_record = {
        "schema_version": "model_registry_active_v2",
        "lane": lane,
        "registry_generation": new_generation,
        "checkpoint_id": bundle.checkpoint_id,
        "checkpoint_classification": bundle.checkpoint_classification,
        "checkpoint_bundle": bundle.to_dict(),
        "checkpoint_bundle_path": bundle.weight_file_path,
        "checkpoint_bundle_sha256": bundle.content_sha256(),
        "feature_abi_sha256": bundle.feature_abi_sha256,
        "activated_at": activated_at,
        "activated_by": activated_by,
        "activation_reason": activation_reason,
        "previous_checkpoint_id": prev_checkpoint_id,
        "rollback_checkpoint_id": prev_checkpoint_id,
        "rollback_record": prev,
        "health_state": health_state,
        "serving_smoke_result": serving_smoke_result,
        "receipt_id": receipt_id,
        "paper_only": True,
        "live_eligible": False,
    }

    def _commit(pipe: Any = None) -> None:
        target = pipe if pipe is not None else client
        target.set(active_key, json.dumps(active_record, default=str))
        if prev:
            history = _get_json(client, HISTORY_KEY.format(lane=lane)) or {}
            rows = history.get("rows") if isinstance(history, dict) else None
            rows = list(rows) if isinstance(rows, list) else []
            rows.append(prev)
            rows = rows[-HISTORY_MAX:]
            target.set(
                HISTORY_KEY.format(lane=lane),
                json.dumps({"schema_version": "model_registry_history_v2", "rows": rows}, default=str),
            )

    try:
        pipe = client.pipeline()
        pipe.watch(active_key)
        current = _get_json(client, active_key)
        cur_gen = int(current.get("registry_generation", 0)) if current else 0
        if cur_gen != prev_generation:
            pipe.reset()
            raise ValueError(
                f"activation_cas_conflict:read={prev_generation}:now={cur_gen}"
            )
        pipe.multi()
        _commit(pipe)
        pipe.execute()
    except AttributeError:
        _commit(None)

    receipt = ModelActivationReceiptV2(
        receipt_id=receipt_id,
        registry_key=active_key,
        registry_generation=new_generation,
        previous_generation=prev_generation,
        checkpoint_id=bundle.checkpoint_id,
        checkpoint_bundle_sha256=bundle.content_sha256(),
        feature_abi_sha256=bundle.feature_abi_sha256,
        activated_at=activated_at,
        activated_by=activated_by,
        activation_reason=activation_reason,
        previous_checkpoint_id=prev_checkpoint_id,
        rollback_checkpoint_id=prev_checkpoint_id,
        serving_smoke_result=serving_smoke_result,
        health_state=health_state,
    )
    client.set(
        RECEIPT_KEY.format(receipt_id=receipt_id),
        json.dumps(receipt.to_dict(), default=str),
    )
    return receipt


def rollback(client: Any, *, lane: str = "paper", rolled_back_by: str, reason: str) -> dict[str, Any]:
    """Restore the previous active record (advancing generation forward)."""
    active = read_active(client, lane=lane)
    if not active:
        raise ValueError("rollback_no_active_record")
    prev = active.get("rollback_record")
    if not isinstance(prev, dict):
        raise ValueError("rollback_no_previous_record")
    new_generation = int(active.get("registry_generation", 0)) + 1
    restored = dict(prev)
    restored["registry_generation"] = new_generation
    restored["health_state"] = "ROLLED_BACK_RESTORE"
    restored["activation_reason"] = f"rollback:{reason}"
    restored["activated_by"] = rolled_back_by
    restored["rolled_back_from_checkpoint_id"] = active.get("checkpoint_id")
    client.set(ACTIVE_KEY.format(lane=lane), json.dumps(restored, default=str))
    return restored
