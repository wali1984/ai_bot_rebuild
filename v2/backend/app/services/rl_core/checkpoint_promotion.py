"""Paper-only checkpoint promotion scanner (torch-native shape contract).

Reads operator-provided checkpoint blobs + sidecar metadata under
``.local_models/`` and decides whether the candidate is ready for a
separate Codex-reviewed shape inspection. NEVER loads weights into the V2
process. NEVER imports torch. NEVER deserializes pickle. NEVER reads
outside the approved directory. NEVER reads legacy filesystem paths.

Shape-contract orientation
==========================

The V2 native CPU forward pass in ``policy.py`` iterates the flat weight
buffer output-first (``w[j*in_dim + i]`` for output index ``j`` and input
index ``i``), which matches torch's ``nn.Linear(in, out).weight`` shape of
``[out, in]``. The canonical sidecar shape contract is therefore
torch-native output-first.

Legacy / metadata producers that emit input-first ``[in, out]`` may still
be accepted, but only if the sidecar explicitly declares
``tensor_shape_layout = "INPUT_FIRST"``. The scanner then normalizes those
shapes to the torch-native form and tags the candidate with
``shape_contract_orientation = METADATA_INPUT_FIRST_NORMALIZED``.

Without an explicit layout marker, the contract is enforced as torch
output-first. Anything else fails closed as ``SHAPE_MISMATCH``.
"""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any

APPROVED_ROOT = Path(".local_models")
BLOB_EXTENSIONS = (".pt", ".safetensors")
METADATA_SUFFIX = "_metadata.json"

REQUIRED_METADATA_FIELDS = (
    "checkpoint_id",
    "source_legacy_path",
    "source_legacy_sha256",
    "training_window_utc",
    "obs_dim",
    "action_count",
    "action_labels",
    "tensor_shapes_per_layer",
    "operator_signature_id",
    "paper_only",
    "approves_live",
    "approves_canary",
    "approves_legacy_shutdown",
)

TENSOR_SHAPE_LAYOUT_CONVENTION = "TORCH_NATIVE_OUTPUT_FIRST_OUT_IN"
TENSOR_SHAPE_LAYOUT_FIELD = "tensor_shape_layout"
TENSOR_SHAPE_LAYOUT_TORCH_OUTPUT_FIRST = "TORCH_OUTPUT_FIRST"
TENSOR_SHAPE_LAYOUT_INPUT_FIRST = "INPUT_FIRST"
TENSOR_SHAPE_LAYOUT_VALID = (
    TENSOR_SHAPE_LAYOUT_TORCH_OUTPUT_FIRST,
    TENSOR_SHAPE_LAYOUT_INPUT_FIRST,
)

ORIENTATION_TORCH_OUTPUT_FIRST = "TORCH_OUTPUT_FIRST"
ORIENTATION_METADATA_INPUT_FIRST_NORMALIZED = "METADATA_INPUT_FIRST_NORMALIZED"
ORIENTATION_SHAPE_MISMATCH = "SHAPE_MISMATCH"
ORIENTATION_NOT_EVALUATED = "NOT_EVALUATED"

V2_POLICY_SHAPE_CONTRACT: dict[str, Any] = {
    "obs_dim": 26,
    "hidden_dim": 16,
    "action_count": 5,
    "action_labels": ["hold", "long", "short", "close", "hedge"],
    "tensor_shape_layout_convention": TENSOR_SHAPE_LAYOUT_CONVENTION,
    "tensor_shape_layout_rationale": (
        "policy._linear indexes flat weights as w[j*in_dim+i] (output-first), "
        "matching torch nn.Linear(in,out).weight shape of [out, in]."
    ),
    "tensor_shapes_per_layer": {
        "w1": [16, 26],
        "b1": [16],
        "w2": [5, 16],
        "b2": [5],
        "w_exp": [1, 16],
        "b_exp": [1],
    },
    "tensor_shapes_per_layer_input_first_legacy_normalizable_form": {
        "w1": [26, 16],
        "b1": [16],
        "w2": [16, 5],
        "b2": [5],
        "w_exp": [16, 1],
        "b_exp": [1],
    },
    "tensor_flat_counts": {
        "w1": 416,
        "b1": 16,
        "w2": 80,
        "b2": 5,
        "w_exp": 16,
        "b_exp": 1,
    },
}

_WEIGHT_LAYERS_WITH_ORIENTATION = ("w1", "w2", "w_exp")
_BIAS_LAYERS = ("b1", "b2", "b_exp")

STATE_READY = "CHECKPOINT_PROMOTION_READY_FOR_CODEX_SHAPE_REVIEW"
STATE_SHAPE_MISMATCH = "CHECKPOINT_METADATA_PRESENT_SHAPE_MISMATCH"
STATE_METADATA_MISSING = "CHECKPOINT_METADATA_MISSING"
STATE_BLOB_MISSING = "CHECKPOINT_BLOB_MISSING"
STATE_OPERATOR_REQUIRED = "CHECKPOINT_OPERATOR_REQUIRED"

OPERATOR_INSTRUCTION = (
    "Place approved checkpoint + metadata under .local_models/ "
    "and rerun checkpoint promotion status."
)


@dataclasses.dataclass(frozen=True)
class CandidateResult:
    name: str
    blob_path: str | None
    metadata_path: str | None
    state: str
    metadata_errors: tuple[str, ...]
    shape_mismatch_fields: tuple[str, ...]
    shape_contract_orientation: str
    declared_tensor_shape_layout: str | None


def _list_candidate_names(root: Path) -> list[str]:
    if not root.exists() or not root.is_dir():
        return []
    seen: set[str] = set()
    for entry in sorted(root.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        for ext in BLOB_EXTENSIONS:
            if name.endswith(ext):
                seen.add(name[: -len(ext)])
        if name.endswith(METADATA_SUFFIX):
            seen.add(name[: -len(METADATA_SUFFIX)])
    return sorted(seen)


def _resolve_paths(root: Path, name: str) -> tuple[Path | None, Path | None]:
    blob: Path | None = None
    for ext in BLOB_EXTENSIONS:
        candidate = root / f"{name}{ext}"
        if candidate.exists():
            blob = candidate
            break
    meta = root / f"{name}{METADATA_SUFFIX}"
    if not meta.exists():
        meta = None
    return blob, meta


def _load_metadata(meta_path: Path) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, [f"metadata_unreadable: {exc.__class__.__name__}"]
    if not isinstance(data, dict):
        return {}, ["metadata_not_object"]
    for field in REQUIRED_METADATA_FIELDS:
        if field not in data:
            errors.append(f"missing_field: {field}")
    if data.get("paper_only") is not True:
        errors.append("paper_only_must_be_true")
    for forbidden in ("approves_live", "approves_canary", "approves_legacy_shutdown"):
        if data.get(forbidden) is not False:
            errors.append(f"{forbidden}_must_be_false")
    return data, errors


def _flat_count(shape: Any) -> int | None:
    if not isinstance(shape, list) or not shape:
        return None
    total = 1
    for dim in shape:
        if not isinstance(dim, int) or dim <= 0:
            return None
        total *= dim
    return total


def _normalize_input_first_weight(shape: list[int]) -> list[int]:
    if len(shape) != 2:
        return list(shape)
    return [shape[1], shape[0]]


def _resolve_declared_layout(metadata: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Return (declared_layout, layout_errors).

    A missing field defaults to torch output-first. Any value other than
    TORCH_OUTPUT_FIRST / INPUT_FIRST is a layout error and forces shape
    evaluation to fail closed.
    """
    if TENSOR_SHAPE_LAYOUT_FIELD not in metadata:
        return None, []
    raw = metadata.get(TENSOR_SHAPE_LAYOUT_FIELD)
    if not isinstance(raw, str):
        return None, [f"{TENSOR_SHAPE_LAYOUT_FIELD}_must_be_string"]
    if raw not in TENSOR_SHAPE_LAYOUT_VALID:
        return raw, [f"{TENSOR_SHAPE_LAYOUT_FIELD}_invalid_value: {raw}"]
    return raw, []


def _validate_shape_contract(
    metadata: dict[str, Any],
) -> tuple[list[str], str, str | None]:
    """Return (mismatch_fields, orientation, declared_layout).

    ``orientation`` is one of ``ORIENTATION_TORCH_OUTPUT_FIRST``,
    ``ORIENTATION_METADATA_INPUT_FIRST_NORMALIZED``,
    ``ORIENTATION_SHAPE_MISMATCH``.
    """
    mismatches: list[str] = []

    if metadata.get("obs_dim") != V2_POLICY_SHAPE_CONTRACT["obs_dim"]:
        mismatches.append("obs_dim")
    if metadata.get("action_count") != V2_POLICY_SHAPE_CONTRACT["action_count"]:
        mismatches.append("action_count")
    if list(metadata.get("action_labels") or []) != V2_POLICY_SHAPE_CONTRACT["action_labels"]:
        mismatches.append("action_labels")

    contract_torch = V2_POLICY_SHAPE_CONTRACT["tensor_shapes_per_layer"]
    contract_input_first = V2_POLICY_SHAPE_CONTRACT[
        "tensor_shapes_per_layer_input_first_legacy_normalizable_form"
    ]
    contract_flat = V2_POLICY_SHAPE_CONTRACT["tensor_flat_counts"]
    actual_shapes = metadata.get("tensor_shapes_per_layer")

    declared_layout, layout_errors = _resolve_declared_layout(metadata)
    for err in layout_errors:
        mismatches.append(err)

    if not isinstance(actual_shapes, dict):
        mismatches.append("tensor_shapes_per_layer_not_object")
        orientation = ORIENTATION_SHAPE_MISMATCH if mismatches else ORIENTATION_NOT_EVALUATED
        return mismatches, orientation, declared_layout

    # Flat counts must always match (transpose invariant).
    for layer, expected_flat in contract_flat.items():
        actual_flat = _flat_count(actual_shapes.get(layer))
        if actual_flat != expected_flat:
            mismatches.append(f"tensor_flat_counts.{layer}")

    # Bias shapes are orientation-independent.
    for layer in _BIAS_LAYERS:
        actual = actual_shapes.get(layer)
        if list(actual or []) != list(contract_torch[layer]):
            mismatches.append(f"tensor_shapes_per_layer.{layer}")

    if layout_errors:
        # Layout marker malformed → cannot decide orientation safely.
        return mismatches, ORIENTATION_SHAPE_MISMATCH, declared_layout

    if declared_layout == TENSOR_SHAPE_LAYOUT_INPUT_FIRST:
        # Operator explicitly opted into legacy [in, out] layout. Normalize
        # by transposing, then verify against torch-native contract.
        for layer in _WEIGHT_LAYERS_WITH_ORIENTATION:
            actual = actual_shapes.get(layer)
            if not isinstance(actual, list) or len(actual) != 2:
                mismatches.append(f"tensor_shapes_per_layer.{layer}")
                continue
            normalized = _normalize_input_first_weight(actual)
            if normalized != list(contract_torch[layer]):
                mismatches.append(f"tensor_shapes_per_layer.{layer}")
        if mismatches:
            return mismatches, ORIENTATION_SHAPE_MISMATCH, declared_layout
        return mismatches, ORIENTATION_METADATA_INPUT_FIRST_NORMALIZED, declared_layout

    # Default branch: declared_layout is None or TORCH_OUTPUT_FIRST.
    for layer in _WEIGHT_LAYERS_WITH_ORIENTATION:
        actual = actual_shapes.get(layer)
        if list(actual or []) != list(contract_torch[layer]):
            mismatches.append(f"tensor_shapes_per_layer.{layer}")

    if mismatches:
        return mismatches, ORIENTATION_SHAPE_MISMATCH, declared_layout
    return mismatches, ORIENTATION_TORCH_OUTPUT_FIRST, declared_layout


def _evaluate_candidate(root: Path, name: str) -> CandidateResult:
    blob, meta = _resolve_paths(root, name)
    if blob is None and meta is None:
        return CandidateResult(
            name=name,
            blob_path=None,
            metadata_path=None,
            state=STATE_OPERATOR_REQUIRED,
            metadata_errors=(),
            shape_mismatch_fields=(),
            shape_contract_orientation=ORIENTATION_NOT_EVALUATED,
            declared_tensor_shape_layout=None,
        )
    if blob is None:
        return CandidateResult(
            name=name,
            blob_path=None,
            metadata_path=str(meta) if meta else None,
            state=STATE_BLOB_MISSING,
            metadata_errors=(),
            shape_mismatch_fields=(),
            shape_contract_orientation=ORIENTATION_NOT_EVALUATED,
            declared_tensor_shape_layout=None,
        )
    if meta is None:
        return CandidateResult(
            name=name,
            blob_path=str(blob),
            metadata_path=None,
            state=STATE_METADATA_MISSING,
            metadata_errors=(),
            shape_mismatch_fields=(),
            shape_contract_orientation=ORIENTATION_NOT_EVALUATED,
            declared_tensor_shape_layout=None,
        )
    metadata, meta_errors = _load_metadata(meta)
    if meta_errors:
        return CandidateResult(
            name=name,
            blob_path=str(blob),
            metadata_path=str(meta),
            state=STATE_METADATA_MISSING,
            metadata_errors=tuple(meta_errors),
            shape_mismatch_fields=(),
            shape_contract_orientation=ORIENTATION_NOT_EVALUATED,
            declared_tensor_shape_layout=None,
        )
    mismatches, orientation, declared_layout = _validate_shape_contract(metadata)
    if mismatches:
        return CandidateResult(
            name=name,
            blob_path=str(blob),
            metadata_path=str(meta),
            state=STATE_SHAPE_MISMATCH,
            metadata_errors=(),
            shape_mismatch_fields=tuple(mismatches),
            shape_contract_orientation=orientation,
            declared_tensor_shape_layout=declared_layout,
        )
    return CandidateResult(
        name=name,
        blob_path=str(blob),
        metadata_path=str(meta),
        state=STATE_READY,
        metadata_errors=(),
        shape_mismatch_fields=(),
        shape_contract_orientation=orientation,
        declared_tensor_shape_layout=declared_layout,
    )


def scan_local_models(root: Path | None = None) -> dict[str, Any]:
    """Scan ``.local_models/`` and return the promotion status payload.

    Reads only the approved root; never touches legacy filesystem, never
    loads weights, never deserializes pickle, never reads outside the
    approved root.
    """
    resolved_root = Path(root) if root is not None else APPROVED_ROOT
    candidates_names = _list_candidate_names(resolved_root)
    if not resolved_root.exists():
        approved_root_status = "ABSENT"
    elif not candidates_names:
        approved_root_status = "EMPTY"
    else:
        approved_root_status = "POPULATED"
    results = [_evaluate_candidate(resolved_root, name) for name in candidates_names]
    state_counts: dict[str, int] = {
        STATE_READY: 0,
        STATE_SHAPE_MISMATCH: 0,
        STATE_METADATA_MISSING: 0,
        STATE_BLOB_MISSING: 0,
        STATE_OPERATOR_REQUIRED: 0,
    }
    orientation_counts: dict[str, int] = {
        ORIENTATION_TORCH_OUTPUT_FIRST: 0,
        ORIENTATION_METADATA_INPUT_FIRST_NORMALIZED: 0,
        ORIENTATION_SHAPE_MISMATCH: 0,
        ORIENTATION_NOT_EVALUATED: 0,
    }
    for r in results:
        state_counts[r.state] = state_counts.get(r.state, 0) + 1
        orientation_counts[r.shape_contract_orientation] = (
            orientation_counts.get(r.shape_contract_orientation, 0) + 1
        )
    if state_counts[STATE_READY] > 0:
        overall_state = STATE_READY
    elif state_counts[STATE_SHAPE_MISMATCH] > 0:
        overall_state = STATE_SHAPE_MISMATCH
    elif state_counts[STATE_METADATA_MISSING] > 0:
        overall_state = STATE_METADATA_MISSING
    elif state_counts[STATE_BLOB_MISSING] > 0:
        overall_state = STATE_BLOB_MISSING
    else:
        overall_state = STATE_OPERATOR_REQUIRED
    operator_required = overall_state == STATE_OPERATOR_REQUIRED
    payload: dict[str, Any] = {
        "schema_version": "v2_checkpoint_promotion_status_v2_torch_native_shape_contract",
        "approved_root": str(resolved_root),
        "approved_root_status": approved_root_status,
        "candidates": [
            {
                "name": r.name,
                "blob_path": r.blob_path,
                "metadata_path": r.metadata_path,
                "state": r.state,
                "metadata_errors": list(r.metadata_errors),
                "shape_mismatch_fields": list(r.shape_mismatch_fields),
                "shape_contract_orientation": r.shape_contract_orientation,
                "declared_tensor_shape_layout": r.declared_tensor_shape_layout,
            }
            for r in results
        ],
        "candidate_count": len(results),
        "state_counts": state_counts,
        "orientation_counts": orientation_counts,
        "overall_state": overall_state,
        "operator_instruction": OPERATOR_INSTRUCTION if operator_required else None,
        "v2_policy_shape_contract": V2_POLICY_SHAPE_CONTRACT,
        "tensor_shape_layout_convention": TENSOR_SHAPE_LAYOUT_CONVENTION,
        "no_weights_loaded": True,
        "no_legacy_filesystem_read": True,
        "no_pickle_deserialization_attempted": True,
        "no_torch_imported": True,
        "no_git_commit_of_checkpoint_blob": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    return payload
