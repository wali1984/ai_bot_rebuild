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
import hashlib
from pathlib import Path
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
RECEIPTS_KEY = "v2:model_registry:activation_receipts"
HISTORY_MAX = 50


def _serving_abi_v2_static_reasons(bundle: CheckpointBundleV2) -> list[str]:
    from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (
        ORDERED_FEATURE_NAMES,
        feature_abi_sha256,
        feature_builder_sha256,
    )

    if bundle.feature_abi_sha256 != feature_abi_sha256():
        return []
    reasons: list[str] = []
    path = Path(bundle.weight_file_path)
    if not path.is_file():
        reasons.append("CHECKPOINT_FILE_MISSING")
    elif hashlib.sha256(path.read_bytes()).hexdigest() != bundle.weight_sha256:
        reasons.append("CHECKPOINT_FILE_SHA256_MISMATCH")
    if bundle.ordered_feature_names != ORDERED_FEATURE_NAMES:
        reasons.append("SERVING_FEATURE_ORDER_MISMATCH")
    if bundle.training_feature_builder_sha != feature_builder_sha256():
        reasons.append("TRAINING_FEATURE_BUILDER_SHA_MISMATCH")
    if bundle.serving_feature_builder_sha != feature_builder_sha256():
        reasons.append("SERVING_FEATURE_BUILDER_SHA_MISMATCH")
    calibration = bundle.calibration_state
    if calibration.get("fitted") is not True:
        reasons.append("CALIBRATION_NOT_FITTED")
    if calibration.get("probability_semantics_valid") is not True:
        reasons.append("CALIBRATION_PROBABILITY_SEMANTICS_INVALID")
    if not calibration.get("row_digest"):
        reasons.append("CALIBRATION_ROW_DIGEST_MISSING")
    if calibration.get("model_parameter_fingerprint") != bundle.model_parameter_fingerprint:
        reasons.append("CALIBRATION_MODEL_FINGERPRINT_MISMATCH")
    if bundle.live_eligible or bundle.checkpoint_promotable:
        reasons.append("PAPER_CHECKPOINT_GAINED_FORBIDDEN_AUTHORITY")
    return reasons


def _serving_abi_v2_activation_reasons(
    bundle: CheckpointBundleV2,
    smoke: dict[str, Any],
) -> list[str]:
    from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (
        feature_abi_sha256,
    )

    if bundle.feature_abi_sha256 != feature_abi_sha256():
        return []
    reasons = _serving_abi_v2_static_reasons(bundle)
    required_true = (
        "checkpoint_hash_valid",
        "manifest_hash_valid",
        "feature_abi_valid",
        "calibration_valid",
        "train_serve_parity_valid",
        "shadow_prediction_valid",
        "no_live_authority",
        "rollback_ready",
    )
    for field in required_true:
        if smoke.get(field) is not True:
            reasons.append(f"ACTIVATION_{field.upper()}_NOT_PROVEN")
    try:
        directional_rate = float(smoke.get("serving_smoke_directional_rate"))
    except (TypeError, ValueError):
        directional_rate = 0.0
    if directional_rate <= 0.0:
        reasons.append("SERVING_SMOKE_DIRECTIONAL_RATE_ZERO")
    if smoke.get("all_predictions_one_action") is True:
        reasons.append("SERVING_SMOKE_ALL_PREDICTIONS_ONE_ACTION")
    if int(smoke.get("nonfinite_probabilities") or 0) > 0:
        reasons.append("SERVING_SMOKE_NONFINITE_PROBABILITIES")
    if smoke.get("feature_distribution_drift_above_limit") is not False:
        reasons.append("SERVING_FEATURE_DISTRIBUTION_DRIFT_ABOVE_LIMIT")
    return sorted(set(reasons))


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
    reasons.extend(_serving_abi_v2_static_reasons(bundle))
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
    reasons.extend(_serving_abi_v2_activation_reasons(bundle, serving_smoke_result))
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
    existing_receipts = _get_json(client, RECEIPTS_KEY) or {}
    receipt_rows = existing_receipts.get("rows")
    receipt_rows = list(receipt_rows) if isinstance(receipt_rows, list) else []
    receipt_rows.append(receipt.to_dict())
    client.set(
        RECEIPTS_KEY,
        json.dumps(
            {
                "schema_version": "model_activation_receipt_history_v2",
                "rows": receipt_rows[-HISTORY_MAX:],
            },
            default=str,
        ),
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
